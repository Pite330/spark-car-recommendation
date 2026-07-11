"""将 16888 完整配置长表适配为车系特征，并分析其与同月销量的关联。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Iterable

os.environ.setdefault("JAVA_TOOL_OPTIONS", "-Djava.security.manager=allow")

from pyspark.ml import Pipeline
from pyspark.ml.evaluation import RegressionEvaluator
from pyspark.ml.feature import OneHotEncoder, StandardScaler, StringIndexer, VectorAssembler
from pyspark.ml.regression import LinearRegression, RandomForestRegressor
from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T


DEFAULT_INPUT_DIR = Path("data/raw/16888_full/tables")
DEFAULT_OUTPUT_DIR = Path("data/processed/analysis")

LEAKAGE_PARAMETERS = {"全国4S最低报价", "车款人气"}
CATEGORICAL_CONTROLS = ["brand", "level_name", "body_structure"]
NUMERIC_CONTROLS = ["price_median_wan", "model_year_max", "trim_count", "energy_type"]

PARAMETER_SCHEMA = T.StructType(
    [
        T.StructField("trim_id", T.StringType(), True),
        T.StructField("series_id", T.StringType(), True),
        T.StructField("parameter_key", T.StringType(), True),
        T.StructField("group_id", T.StringType(), True),
        T.StructField("group_name", T.StringType(), True),
        T.StructField("parameter_name", T.StringType(), True),
        T.StructField("value_raw", T.StringType(), True),
        T.StructField("value_text", T.StringType(), True),
        T.StructField("value_numeric", T.DoubleType(), True),
        T.StructField("value_unit", T.StringType(), True),
        T.StructField("equipment_state", T.StringType(), True),
        T.StructField("captured_at", T.StringType(), True),
    ]
)

TRIM_SCHEMA = T.StructType(
    [
        T.StructField("trim_id", T.StringType(), True),
        T.StructField("series_id", T.StringType(), True),
        T.StructField("trim_name", T.StringType(), True),
        T.StructField("model_year", T.IntegerType(), True),
        T.StructField("status", T.StringType(), True),
        T.StructField("energy_type_raw", T.StringType(), True),
        T.StructField("displacement", T.StringType(), True),
        T.StructField("transmission", T.StringType(), True),
        T.StructField("drive_style", T.StringType(), True),
        T.StructField("body_structure", T.StringType(), True),
        T.StructField("seats_raw", T.StringType(), True),
        T.StructField("options_url", T.StringType(), True),
        T.StructField("captured_at", T.StringType(), True),
    ]
)

SALES_SCHEMA = T.StructType(
    [
        T.StructField("series_id", T.StringType(), True),
        T.StructField("sales_period", T.StringType(), True),
        T.StructField("sales", T.IntegerType(), True),
        T.StructField("overall_rank", T.StringType(), True),
        T.StructField("manufacturer_share", T.StringType(), True),
        T.StructField("manufacturer_rank", T.StringType(), True),
        T.StructField("segment_rank", T.StringType(), True),
        T.StructField("registration_related", T.StringType(), True),
        T.StructField("sales_url", T.StringType(), True),
        T.StructField("captured_at", T.StringType(), True),
    ]
)


def feature_name(kind: str, parameter_key: str) -> str:
    prefix = "num" if kind == "numeric" else "equip"
    return f"{prefix}_{hashlib.sha1(parameter_key.encode('utf-8')).hexdigest()[:12]}"


def encode_energy_type(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lower = text.lower()
    if any(token in lower for token in ["纯电", "电动", "电驱", "新能源", "ev", "纯电动"]):
        return 1.0
    if any(token in lower for token in ["插混", "混动", "增程", "油电", "hev", "phev", "erev"]):
        return 0.5
    if any(token in lower for token in ["燃油", "汽油", "柴油", "油气", "内燃"]):
        return 0.0
    return None


def classify_parameter(row: dict[str, object]) -> str:
    rows = int(row["rows"])
    non_blank = rows - int(row["blank_rows"])
    numeric_rows = int(row["numeric_rows"])
    symbol_rows = int(row["standard_rows"]) + int(row["optional_rows"]) + int(row["mixed_rows"])
    recognized_equipment = symbol_rows + int(row["absent_rows"])
    numeric_ratio = numeric_rows / max(non_blank, 1)
    equipment_ratio = recognized_equipment / max(rows, 1)
    if numeric_rows >= 20 and numeric_ratio >= 0.5:
        return "numeric"
    if symbol_rows > 0 and equipment_ratio >= 0.5:
        return "equipment"
    return "categorical"


def average_ranks(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        rank = (index + 1 + end) / 2
        for position in range(index, end):
            ranks[ordered[position][0]] = rank
        index = end
    return ranks


def pearson(values_x: list[float], values_y: list[float]) -> float:
    if len(values_x) != len(values_y) or len(values_x) < 3:
        return float("nan")
    mean_x, mean_y = mean(values_x), mean(values_y)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(values_x, values_y))
    denominator = math.sqrt(
        sum((x - mean_x) ** 2 for x in values_x)
        * sum((y - mean_y) ** 2 for y in values_y)
    )
    return numerator / denominator if denominator else float("nan")


def spearman(values_x: list[float], values_y: list[float]) -> tuple[float, float]:
    rho = pearson(average_ranks(values_x), average_ranks(values_y))
    if math.isnan(rho):
        return rho, float("nan")
    bounded = min(abs(rho), 0.999999)
    statistic = bounded * math.sqrt((len(values_x) - 2) / max(1 - bounded**2, 1e-12))
    # n >= 30 时使用正态近似；本项目保留的特征至少覆盖 20% 同月样本。
    p_value = math.erfc(statistic / math.sqrt(2))
    return rho, p_value


def benjamini_hochberg(p_values: list[float]) -> list[float]:
    valid = [(index, value) for index, value in enumerate(p_values) if not math.isnan(value)]
    adjusted = [float("nan")] * len(p_values)
    running = 1.0
    total = len(valid)
    for rank, (index, value) in reversed(list(enumerate(sorted(valid, key=lambda item: item[1]), 1))):
        running = min(running, value * total / rank)
        adjusted[index] = min(running, 1.0)
    return adjusted


def write_csv(path: Path, rows: Iterable[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def mode_by_series(frame: DataFrame, value_column: str, alias: str) -> DataFrame:
    valid = frame.filter(F.col(value_column).isNotNull() & (F.trim(F.col(value_column)) != ""))
    counts = valid.groupBy("series_id", value_column).count()
    window = Window.partitionBy("series_id").orderBy(F.desc("count"), F.asc(value_column))
    return (
        counts.withColumn("position", F.row_number().over(window))
        .filter(F.col("position") == 1)
        .select("series_id", F.col(value_column).alias(alias))
    )


def parameter_quality(parameters: DataFrame) -> tuple[list[dict[str, object]], DataFrame]:
    stats = (
        parameters.groupBy("parameter_key", "group_id", "group_name", "parameter_name")
        .agg(
            F.count("*").alias("rows"),
            F.sum(F.when(F.col("value_text") == "", 1).otherwise(0)).alias("blank_rows"),
            F.sum(F.when(F.col("value_numeric").isNotNull(), 1).otherwise(0)).alias("numeric_rows"),
            F.sum(F.when(F.col("equipment_state") == "standard", 1).otherwise(0)).alias("standard_rows"),
            F.sum(F.when(F.col("equipment_state") == "optional", 1).otherwise(0)).alias("optional_rows"),
            F.sum(F.when(F.col("equipment_state") == "mixed", 1).otherwise(0)).alias("mixed_rows"),
            F.sum(F.when(F.col("value_text").isin("-", "--"), 1).otherwise(0)).alias("absent_rows"),
            F.approx_count_distinct("value_text").alias("distinct_values"),
        )
        .collect()
    )
    quality: list[dict[str, object]] = []
    mapping_rows: list[tuple[str, str, str]] = []
    for spark_row in stats:
        row = spark_row.asDict()
        kind = classify_parameter(row)
        if row["parameter_name"] in LEAKAGE_PARAMETERS:
            excluded_reason = "target_leakage"
        elif row["parameter_name"] == "厂商指导价(元)":
            excluded_reason = "control_only"
        else:
            excluded_reason = ""
        selected_for_adapter = kind in {"numeric", "equipment"} and not excluded_reason
        name = feature_name(kind, str(row["parameter_key"])) if selected_for_adapter else ""
        recognized = (
            int(row["numeric_rows"])
            if kind == "numeric"
            else int(row["standard_rows"])
            + int(row["optional_rows"])
            + int(row["mixed_rows"])
            + int(row["absent_rows"])
        )
        quality_row = {
            **row,
            "parameter_type": kind,
            "recognized_rate": round(recognized / max(int(row["rows"]), 1), 6),
            "feature_name": name,
            "selected_for_adapter": selected_for_adapter,
            "selected_for_model": False,
            "model_coverage": "",
            "model_stddev": "",
            "excluded_reason": excluded_reason,
        }
        quality.append(quality_row)
        if selected_for_adapter:
            mapping_rows.append((str(row["parameter_key"]), kind, name))
    schema = T.StructType(
        [
            T.StructField("parameter_key", T.StringType(), False),
            T.StructField("parameter_type", T.StringType(), False),
            T.StructField("feature_name", T.StringType(), False),
        ]
    )
    mapping = parameters.sparkSession.createDataFrame(mapping_rows, schema=schema)
    return quality, mapping


def build_series_features(parameters: DataFrame, mapping: DataFrame) -> DataFrame:
    adapted = (
        parameters.join(F.broadcast(mapping), "parameter_key", "inner")
        .withColumn(
            "equipment_value",
            F.when(F.col("equipment_state") == "standard", 1.0)
            .when(F.col("equipment_state") == "optional", 0.5)
            .when(F.col("equipment_state") == "mixed", 0.75)
            .when(F.col("value_text").isin("-", "--"), 0.0),
        )
    )
    numeric = (
        adapted.filter((F.col("parameter_type") == "numeric") & F.col("value_numeric").isNotNull())
        .groupBy("series_id", "parameter_key", "feature_name")
        .agg(F.expr("percentile_approx(value_numeric, 0.5, 10000)").alias("feature_value"))
    )
    equipment = (
        adapted.filter((F.col("parameter_type") == "equipment") & F.col("equipment_value").isNotNull())
        .groupBy("series_id", "parameter_key", "feature_name")
        .agg(F.avg("equipment_value").alias("feature_value"))
    )
    return numeric.unionByName(equipment)


def build_controls(parameters: DataFrame, trims: DataFrame) -> DataFrame:
    brand = mode_by_series(parameters.filter(F.col("parameter_name") == "厂商"), "value_text", "brand")
    level = mode_by_series(parameters.filter(F.col("parameter_name") == "级别"), "value_text", "level_name")
    energy = (
        mode_by_series(trims, "energy_type_raw", "energy_type")
        .withColumn("energy_type", F.udf(encode_energy_type, T.DoubleType())(F.col("energy_type")))
    )
    body = mode_by_series(trims, "body_structure", "body_structure")
    price = (
        parameters.filter((F.col("parameter_name") == "厂商指导价(元)") & F.col("value_numeric").isNotNull())
        .groupBy("series_id")
        .agg(F.expr("percentile_approx(value_numeric, 0.5, 10000)").alias("price_median_wan"))
    )
    trim_stats = trims.groupBy("series_id").agg(
        F.countDistinct("trim_id").alias("trim_count"),
        F.max("model_year").alias("model_year_max"),
    )
    return (
        trim_stats.join(brand, "series_id", "left")
        .join(level, "series_id", "left")
        .join(energy, "series_id", "left")
        .join(body, "series_id", "left")
        .join(price, "series_id", "left")
    )


def build_target(
    sales: DataFrame,
    controls: DataFrame | None = None,
    *,
    history_window: int = 10,
) -> tuple[str, DataFrame]:
    """以最近 history_window 期的销量/销售额趋势作为监督学习标签。"""
    latest_period = sales.filter(F.col("sales").isNotNull()).agg(F.max("sales_period")).first()[0]
    power = 0.8

    sales_with_value = sales.filter(F.col("sales").isNotNull() & (F.col("sales") >= 0))
    if controls is not None:
        sales_with_value = (
            sales_with_value.join(
                controls.select("series_id", "price_median_wan"),
                "series_id",
                "left",
            )
            .withColumn(
                "sales_value",
                F.when(
                    F.col("price_median_wan").isNotNull(),
                    F.col("sales") * F.col("price_median_wan"),
                ).otherwise(F.col("sales")),
            )
        )
    else:
        sales_with_value = sales_with_value.withColumn("sales_value", F.col("sales"))

    ordered = sales_with_value.withColumn(
        "sales_period_key",
        F.regexp_replace(F.col("sales_period"), "[^0-9]", ""),
    )
    order_window = Window.partitionBy("series_id").orderBy("sales_period_key", "sales_period")
    ranked = (
        ordered.withColumn("period_rank", F.row_number().over(order_window))
        .withColumn("period_total", F.count("*").over(Window.partitionBy("series_id")))
    )
    selected = ranked.withColumn(
        "history_window",
        F.least(F.col("period_total"), F.lit(history_window)),
    ).filter(F.col("period_rank") > F.col("period_total") - F.col("history_window"))

    history_windowed = selected.withColumn(
        "history_index",
        F.row_number().over(
            Window.partitionBy("series_id").orderBy("sales_period_key", "sales_period")
        ),
    )
    latest_value = (
        history_windowed.withColumn(
            "latest_history_index",
            F.max("history_index").over(Window.partitionBy("series_id")),
        )
        .withColumn(
            "latest_sales_value",
            F.when(
                F.col("history_index") == F.col("latest_history_index"),
                F.col("sales_value"),
            ).otherwise(None),
        )
    )
    aggregated = (
        latest_value.groupBy("series_id")
        .agg(
            F.count("*").alias("history_points"),
            F.count_distinct("sales_value").alias("distinct_sales_values"),
            F.sum(F.col("history_index") - 1).alias("sum_x"),
            F.sum("sales_value").alias("sum_y"),
            F.sum((F.col("history_index") - 1) * F.col("sales_value")).alias("sum_xy"),
            F.sum((F.col("history_index") - 1) * (F.col("history_index") - 1)).alias("sum_xx"),
            F.max("latest_sales_value").alias("latest_sales_value"),
        )
    )
    target = (
        aggregated.filter((F.col("history_points") >= 2) & (F.col("distinct_sales_values") > 1))
        .withColumn(
            "slope",
            F.when(
                (F.col("history_points") * F.col("sum_xx") - F.col("sum_x") * F.col("sum_x")) != 0,
                (
                    F.col("history_points") * F.col("sum_xy") - F.col("sum_x") * F.col("sum_y")
                ) / (
                    F.col("history_points") * F.col("sum_xx") - F.col("sum_x") * F.col("sum_x")
                ),
            ).otherwise(None),
        )
        .withColumn(
            "target_log_sales",
            F.when(
                F.col("slope").isNotNull() & F.col("latest_sales_value").isNotNull(),
                F.col("slope") * F.pow(F.col("latest_sales_value").cast("double"), F.lit(power)),
            ).otherwise(None),
        )
        .select("series_id", "target_log_sales")
        .filter(F.col("target_log_sales").isNotNull())
    )
    return latest_period, target


def select_model_features(
    series_features: DataFrame,
    target: DataFrame,
    quality: list[dict[str, object]],
    *,
    minimum_coverage: float,
    max_features: int,
) -> tuple[list[str], list[dict[str, object]]]:
    target_count = target.count()
    stats = (
        series_features.join(target.select("series_id"), "series_id", "inner")
        .groupBy("feature_name")
        .agg(F.count("feature_value").alias("present"), F.stddev_pop("feature_value").alias("stddev"))
        .withColumn("coverage", F.col("present") / F.lit(target_count))
        .filter((F.col("coverage") >= minimum_coverage) & (F.col("stddev") > 1e-9))
        .orderBy(F.desc("coverage"), F.desc("stddev"), "feature_name")
        .limit(max_features)
        .collect()
    )
    selected = [row["feature_name"] for row in stats]
    model_stats = {row["feature_name"]: row.asDict() for row in stats}
    for row in quality:
        name = str(row["feature_name"])
        if name in model_stats:
            row["selected_for_model"] = True
            row["model_coverage"] = round(float(model_stats[name]["coverage"]), 6)
            row["model_stddev"] = round(float(model_stats[name]["stddev"]), 6)
    return selected, quality


def build_analysis_dataset(
    series_features: DataFrame,
    controls: DataFrame,
    target: DataFrame,
    selected_features: list[str],
) -> DataFrame:
    long_selected = series_features.filter(F.col("feature_name").isin(selected_features))
    wide = long_selected.groupBy("series_id").pivot("feature_name", selected_features).agg(F.first("feature_value"))
    analysis = target.join(controls, "series_id", "inner").join(wide, "series_id", "left")
    for column in CATEGORICAL_CONTROLS:
        analysis = analysis.fillna({column: "未知"})
    medians = analysis.agg(
        *[
            F.expr(f"percentile_approx(`{column}`, 0.5, 10000)").alias(column)
            for column in NUMERIC_CONTROLS + selected_features
        ]
    ).first().asDict()
    fill_values = {column: float(value) for column, value in medians.items() if value is not None}
    return analysis.fillna(fill_values)


def pipeline_for(feature_columns: list[str], estimator, *, scale_features: bool = False) -> Pipeline:
    indexed = [f"{column}_index" for column in CATEGORICAL_CONTROLS]
    encoded = [f"{column}_onehot" for column in CATEGORICAL_CONTROLS]
    stages = [
        StringIndexer(inputCol=source, outputCol=target, handleInvalid="keep")
        for source, target in zip(CATEGORICAL_CONTROLS, indexed)
    ]
    stages.append(OneHotEncoder(inputCols=indexed, outputCols=encoded, handleInvalid="keep"))
    stages.append(
        VectorAssembler(
            inputCols=encoded + NUMERIC_CONTROLS + feature_columns,
            outputCol="features",
            handleInvalid="keep",
        )
    )
    if scale_features:
        # Elastic Net 的惩罚依赖特征量纲。仅做方差缩放、不中心化，避免 One-Hot
        # 向量被转成稠密向量；截距仍可吸收均值差异。
        stages.append(
            StandardScaler(
                inputCol="features",
                outputCol="scaled_features",
                withMean=False,
                withStd=True,
            )
        )
    stages.append(estimator)
    return Pipeline(stages=stages)


def evaluate_models(analysis: DataFrame, feature_columns: list[str], folds: int) -> tuple[dict[str, object], dict[str, dict[str, float]]]:
    folded = analysis.withColumn("fold", F.pmod(F.xxhash64("brand"), F.lit(folds)))
    specs = {
        "baseline_elastic_net": (
            [],
            lambda: LinearRegression(
                featuresCol="scaled_features", labelCol="target_log_sales",
                predictionCol="prediction", regParam=0.1,
                elasticNetParam=0.5, maxIter=200,
            ),
        ),
        "full_elastic_net": (
            feature_columns,
            lambda: LinearRegression(
                featuresCol="scaled_features", labelCol="target_log_sales",
                predictionCol="prediction", regParam=0.1,
                elasticNetParam=0.5, maxIter=200,
            ),
        ),
        "full_random_forest": (
            feature_columns,
            lambda: RandomForestRegressor(
                labelCol="target_log_sales", predictionCol="prediction", numTrees=80,
                maxDepth=6, minInstancesPerNode=5, seed=20260711,
            ),
        ),
    }
    evaluators = {
        metric: RegressionEvaluator(
            labelCol="target_log_sales", predictionCol="prediction", metricName=metric
        )
        for metric in ["rmse", "mae", "r2"]
    }
    results: dict[str, object] = {}
    for model_name, (columns, factory) in specs.items():
        fold_results = []
        for fold in range(folds):
            train = folded.filter(F.col("fold") != fold)
            test = folded.filter(F.col("fold") == fold)
            if not test.take(1):
                continue
            model = pipeline_for(
                columns, factory(), scale_features=model_name.endswith("elastic_net")
            ).fit(train)
            predictions = model.transform(test)
            fold_results.append(
                {"fold": fold, **{name: evaluator.evaluate(predictions) for name, evaluator in evaluators.items()}}
            )
        results[model_name] = {
            "folds": fold_results,
            "mean": {
                metric: round(mean(row[metric] for row in fold_results), 6)
                for metric in evaluators
            },
        }

    importance: dict[str, dict[str, float]] = defaultdict(dict)
    relevant_names = set(feature_columns) | set(CATEGORICAL_CONTROLS) | set(NUMERIC_CONTROLS)

    def normalize_feature_name(name: str) -> str | None:
        if name in relevant_names:
            return name
        for control_name in CATEGORICAL_CONTROLS:
            if name == control_name or name.startswith(f"{control_name}_"):
                return control_name
        for control_name in NUMERIC_CONTROLS:
            if name == control_name or name.startswith(f"{control_name}_"):
                return control_name
        return None

    for model_name, factory in [
        ("elastic_net", specs["full_elastic_net"][1]),
        ("random_forest", specs["full_random_forest"][1]),
    ]:
        fitted = pipeline_for(
            feature_columns, factory(), scale_features=model_name == "elastic_net"
        ).fit(analysis)
        transformed = fitted.transform(analysis)
        metadata = transformed.schema["features"].metadata.get("ml_attr", {}).get("attrs", {})
        attributes = sorted(
            [attribute for values in metadata.values() for attribute in values],
            key=lambda attribute: attribute["idx"],
        )
        names = [attribute.get("name", str(attribute["idx"])) for attribute in attributes]
        estimator_model = fitted.stages[-1]
        values = (
            estimator_model.coefficients.toArray().tolist()
            if model_name == "elastic_net"
            else estimator_model.featureImportances.toArray().tolist()
        )
        for name, value in zip(names, values):
            target_name = normalize_feature_name(name)
            if target_name is None:
                continue
            if target_name in relevant_names:
                importance[target_name][model_name] = importance[target_name].get(model_name, 0.0) + float(value)
    return results, importance


def summarize_evidence(
    spearman_rho: float | None,
    fdr_q_value: float | None,
    elastic_net_coefficient: float | None,
) -> tuple[str, str]:
    """把三种模型信号压缩成保守、可解释的证据标签。

    随机森林重要度没有方向，且基于结点不纯度的数值偏向会放大连续特征，
    因而不参与证据强度或方向判定，只作为补充排序信息输出。
    """

    if spearman_rho is None or math.isnan(spearman_rho):
        return "not_evaluated", "not_evaluated"

    coefficient = elastic_net_coefficient or 0.0
    rho_direction = 1 if spearman_rho > 0 else -1 if spearman_rho < 0 else 0
    coefficient_direction = 1 if coefficient > 1e-12 else -1 if coefficient < -1e-12 else 0
    if abs(spearman_rho) < 0.05 and coefficient_direction == 0:
        direction = "neutral"
    elif coefficient_direction and rho_direction and coefficient_direction != rho_direction:
        direction = "mixed"
    elif rho_direction > 0:
        direction = "positive"
    elif rho_direction < 0:
        direction = "negative"
    else:
        direction = "neutral"

    q_value = fdr_q_value if fdr_q_value is not None else float("nan")
    directions_agree = coefficient_direction == 0 or coefficient_direction == rho_direction
    if (
        not math.isnan(q_value)
        and q_value <= 0.01
        and abs(spearman_rho) >= 0.2
        and coefficient_direction != 0
        and directions_agree
    ):
        strength = "strong"
    elif (
        not math.isnan(q_value)
        and q_value <= 0.05
        and abs(spearman_rho) >= 0.1
        and directions_agree
    ):
        strength = "moderate"
    else:
        strength = "weak"
    return strength, direction


def consolidated_parameter_results(
    quality: list[dict[str, object]],
    associations: list[dict[str, object]],
    importance_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    """合并质量、单变量和模型结果；未建模参数也保留一行供 API 加载。"""

    association_by_feature = {str(row["feature_name"]): row for row in associations}
    importance_by_feature = {str(row["feature_name"]): row for row in importance_rows}
    results: list[dict[str, object]] = []
    for source in quality:
        name = str(source.get("feature_name") or "")
        association = association_by_feature.get(name, {}) if name else {}
        importance = importance_by_feature.get(name, {}) if name else {}
        rho = association.get("spearman_rho")
        q_value = association.get("fdr_q_value")
        coefficient = importance.get("elastic_net_coefficient")
        strength, direction = summarize_evidence(
            float(rho) if rho is not None else None,
            float(q_value) if q_value is not None else None,
            float(coefficient) if coefficient is not None else None,
        )
        results.append(
            {
                "feature_name": name,
                "group_name": source["group_name"],
                "parameter_name": source["parameter_name"],
                "parameter_type": source["parameter_type"],
                "selected_for_model": source["selected_for_model"],
                "excluded_reason": source["excluded_reason"],
                "n": association.get("n", ""),
                "spearman_rho": rho if rho is not None else "",
                "fdr_q_value": q_value if q_value is not None else "",
                "elastic_net_coefficient": coefficient if coefficient is not None else "",
                "random_forest_importance": importance.get("random_forest_importance", ""),
                "evidence_strength": strength,
                "association_direction": direction,
                # 当前只有单期配置快照，年款也不是参数生效时间，禁止输出趋势判断。
                "trend_status": "insufficient_history",
            }
        )
    return sorted(results, key=lambda row: (str(row["group_name"]), str(row["parameter_name"])))


def univariate_associations(
    series_features: DataFrame,
    target: DataFrame,
    controls: DataFrame | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    joined = (
        series_features.join(target.select("series_id", "target_log_sales"), "series_id", "inner")
        .select("feature_name", "feature_value", "target_log_sales")
        .collect()
    )
    grouped: dict[str, tuple[list[float], list[float]]] = defaultdict(lambda: ([], []))
    for row in joined:
        grouped[row["feature_name"]][0].append(float(row["feature_value"]))
        grouped[row["feature_name"]][1].append(float(row["target_log_sales"]))
    for name, (values, targets) in grouped.items():
        rho, p_value = spearman(values, targets)
        rows.append({"feature_name": name, "n": len(values), "spearman_rho": rho, "p_value": p_value})

    if controls is not None:
        target_with_controls = target.join(controls, "series_id", "inner")
        for column in NUMERIC_CONTROLS:
            values = target_with_controls.select(column, "target_log_sales").collect()
            if not values:
                continue
            numeric_values: list[float] = []
            target_values: list[float] = []
            for row in values:
                candidate = row[column]
                if candidate is None:
                    continue
                try:
                    numeric = float(candidate)
                except (TypeError, ValueError):
                    continue
                numeric_values.append(numeric)
                target_values.append(float(row["target_log_sales"]))
            if len(numeric_values) >= 3 and len(numeric_values) == len(target_values):
                rho, p_value = spearman(numeric_values, target_values)
                rows.append(
                    {
                        "feature_name": column,
                        "n": len(numeric_values),
                        "spearman_rho": rho,
                        "p_value": p_value,
                    }
                )

    adjusted = benjamini_hochberg([float(row["p_value"]) for row in rows])
    for row, q_value in zip(rows, adjusted):
        row["fdr_q_value"] = q_value
    return sorted(rows, key=lambda row: (float(row["fdr_q_value"]), -abs(float(row["spearman_rho"]))))


def write_parquet(frame: DataFrame, path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    frame.write.mode("overwrite").parquet(str(path))


def run(
    input_dir: Path,
    output_dir: Path,
    *,
    minimum_coverage: float = 0.2,
    max_features: int = 120,
    folds: int = 5,
) -> dict[str, object]:
    required = ["trim_parameters.csv.gz", "trims.csv", "series_month_sales.csv"]
    missing = [name for name in required if not (input_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"缺少完整参数分析输入：{', '.join(missing)}")
    spark = (
        SparkSession.builder.master("local[4]")
        .appName("spark-car-parameter-sales-analysis")
        .config("spark.sql.session.timeZone", "Asia/Shanghai")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "16")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    try:
        parameters = spark.read.option("header", True).schema(PARAMETER_SCHEMA).csv(str(input_dir / "trim_parameters.csv.gz")).cache()
        trims = spark.read.option("header", True).schema(TRIM_SCHEMA).csv(str(input_dir / "trims.csv")).cache()
        sales = spark.read.option("header", True).schema(SALES_SCHEMA).csv(str(input_dir / "series_month_sales.csv")).cache()

        quality, mapping = parameter_quality(parameters)
        series_features = build_series_features(parameters, mapping).cache()
        controls = build_controls(parameters, trims).cache()
        latest_period, target = build_target(sales, controls)
        selected, quality = select_model_features(
            series_features, target, quality,
            minimum_coverage=minimum_coverage, max_features=max_features,
        )
        selected_long = series_features.filter(F.col("feature_name").isin(selected)).cache()
        analysis = build_analysis_dataset(selected_long, controls, target, selected).cache()

        associations = univariate_associations(selected_long, target, controls)
        metrics, importance = evaluate_models(analysis, selected, folds)
        quality_by_feature = {str(row["feature_name"]): row for row in quality if row["feature_name"]}
        control_name_map = {
            "brand": "品牌",
            "level_name": "级别",
            "energy_type": "能源类型",
            "body_structure": "车身结构",
            "price_median_wan": "指导价格",
            "model_year_max": "车型年份上限",
            "trim_count": "车款数量",
        }
        control_quality_rows = [
            {
                "feature_name": name,
                "group_name": "control",
                "parameter_name": control_name_map.get(name, name),
                "parameter_type": "control",
                "selected_for_model": True,
                "excluded_reason": "control_only",
            }
            for name in CATEGORICAL_CONTROLS + NUMERIC_CONTROLS
        ]
        for association in associations:
            feature_name = str(association["feature_name"])
            if feature_name in quality_by_feature:
                source = quality_by_feature[feature_name]
                association.update(
                    {
                        "group_name": source["group_name"],
                        "parameter_name": source["parameter_name"],
                        "parameter_type": source["parameter_type"],
                    }
                )
            elif feature_name in control_name_map:
                association.update(
                    {
                        "group_name": "control",
                        "parameter_name": control_name_map[feature_name],
                        "parameter_type": "control",
                    }
                )
        importance_rows = []
        for name in selected:
            source = quality_by_feature[name]
            importance_rows.append(
                {
                    "feature_name": name,
                    "group_name": source["group_name"],
                    "parameter_name": source["parameter_name"],
                    "parameter_type": source["parameter_type"],
                    "elastic_net_coefficient": importance.get(name, {}).get("elastic_net", 0.0),
                    "random_forest_importance": importance.get(name, {}).get("random_forest", 0.0),
                }
            )
        for name in CATEGORICAL_CONTROLS + NUMERIC_CONTROLS:
            importance_rows.append(
                {
                    "feature_name": name,
                    "group_name": "control",
                    "parameter_name": name,
                    "parameter_type": "control",
                    "elastic_net_coefficient": importance.get(name, {}).get("elastic_net", 0.0),
                    "random_forest_importance": importance.get(name, {}).get("random_forest", 0.0),
                }
            )
        importance_rows.sort(key=lambda row: float(row["random_forest_importance"]), reverse=True)
        consolidated_rows = consolidated_parameter_results(
            quality + control_quality_rows,
            associations,
            importance_rows,
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        write_parquet(selected_long, output_dir / "series_features.parquet")
        write_parquet(analysis, output_dir / "analysis_dataset.parquet")
        quality_fields = [
            "parameter_key", "group_id", "group_name", "parameter_name", "rows", "blank_rows",
            "numeric_rows", "standard_rows", "optional_rows", "mixed_rows", "absent_rows",
            "distinct_values", "parameter_type", "recognized_rate", "feature_name",
            "selected_for_adapter", "selected_for_model", "model_coverage", "model_stddev",
            "excluded_reason",
        ]
        write_csv(output_dir / "parameter_quality.csv", quality, quality_fields)
        write_csv(
            output_dir / "univariate_associations.csv", associations,
            [
                "feature_name", "group_name", "parameter_name", "parameter_type",
                "n", "spearman_rho", "p_value", "fdr_q_value",
            ],
        )
        write_csv(
            output_dir / "parameter_importance.csv", importance_rows,
            ["feature_name", "group_name", "parameter_name", "parameter_type", "elastic_net_coefficient", "random_forest_importance"],
        )
        write_csv(
            output_dir / "consolidated_parameter_results.csv",
            consolidated_rows,
            [
                "feature_name", "group_name", "parameter_name", "parameter_type",
                "selected_for_model", "excluded_reason", "n", "spearman_rho",
                "fdr_q_value", "elastic_net_coefficient", "random_forest_importance",
                "evidence_strength", "association_direction", "trend_status",
            ],
        )
        summary = {
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "sales_period": latest_period,
            "analysis_rows": analysis.count(),
            "parameter_definitions": len(quality),
            "adapter_features": sum(bool(row["selected_for_adapter"]) for row in quality),
            "model_features": len(selected),
            "minimum_coverage": minimum_coverage,
            "brand_grouped_folds": folds,
            "excluded_leakage_parameters": sorted(LEAKAGE_PARAMETERS),
            "model_metrics": metrics,
            "incremental_mean_r2": {
                "elastic_net": round(
                    metrics["full_elastic_net"]["mean"]["r2"]
                    - metrics["baseline_elastic_net"]["mean"]["r2"],
                    6,
                ),
                "random_forest": round(
                    metrics["full_random_forest"]["mean"]["r2"]
                    - metrics["baseline_elastic_net"]["mean"]["r2"],
                    6,
                ),
            },
            "fdr_significant_features_0_05": sum(
                float(row["fdr_q_value"]) < 0.05 for row in associations
            ),
            "trend_status": "insufficient_history",
            "trend_status_reason": "仅有单期配置快照，不能估计配置渗透趋势或预测未来趋势",
            "importance_notes": {
                "elastic_net_coefficient": "基于方差缩放特征的全样本拟合系数，用于方向参考",
                "random_forest_importance": "全样本拟合的结点不纯度重要度，仅用于补充排序，不参与证据等级",
            },
            "interpretation": "探索性关联，不代表配置参数对销量的因果影响",
        }
        (output_dir / "model_metrics.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return summary
    finally:
        spark.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="分析 16888 完整配置参数与同月车系销量关联")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--minimum-coverage", type=float, default=0.2)
    parser.add_argument("--max-features", type=int, default=120)
    parser.add_argument("--folds", type=int, default=5)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.input_dir, args.output_dir,
                minimum_coverage=args.minimum_coverage,
                max_features=args.max_features,
                folds=args.folds,
            ),
            ensure_ascii=False, indent=2,
        )
    )


if __name__ == "__main__":
    main()
