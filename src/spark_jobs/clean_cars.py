"""用 PySpark 清洗 16888 公开车型快照并生成推荐主表与统计证据。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

# Hadoop 3 在 Java 23 上调用 Subject.getSubject 时需要显式允许兼容模式。
os.environ.setdefault("JAVA_TOOL_OPTIONS", "-Djava.security.manager=allow")

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T


DEFAULT_INPUT = Path("data/raw/16888_cars_snapshot.csv")
DEFAULT_OUTPUT_DIR = Path("data/processed")

RAW_SCHEMA = T.StructType(
    [
        T.StructField("source_key", T.StringType(), True),
        T.StructField("series_id", T.StringType(), True),
        T.StructField("model_name", T.StringType(), True),
        T.StructField("brand", T.StringType(), True),
        T.StructField("price_min_wan", T.DoubleType(), True),
        T.StructField("price_max_wan", T.DoubleType(), True),
        T.StructField("level_name", T.StringType(), True),
        T.StructField("body_structure", T.StringType(), True),
        T.StructField("energy_type", T.StringType(), True),
        T.StructField("seats", T.IntegerType(), True),
        T.StructField("range_km", T.DoubleType(), True),
        T.StructField("fuel_consumption", T.DoubleType(), True),
        T.StructField("horsepower", T.IntegerType(), True),
        T.StructField("model_year", T.IntegerType(), True),
        T.StructField("sales", T.IntegerType(), True),
        T.StructField("sales_period", T.StringType(), True),
        T.StructField("trim_count", T.IntegerType(), True),
        T.StructField("source_url", T.StringType(), True),
        T.StructField("options_url", T.StringType(), True),
        T.StructField("sales_url", T.StringType(), True),
        T.StructField("captured_at", T.DateType(), True),
    ]
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_dataframe(raw: DataFrame) -> DataFrame:
    """标准化字段并生成可解释特征，不推断 16888 未提供的续航等参数。"""
    body_type = (
        F.when(F.col("level_name").contains("SUV"), "SUV")
        .when(F.col("level_name").contains("MPV"), "MPV")
        .when(F.col("level_name").contains("跑车"), "跑车")
        .when(F.col("level_name").contains("轻客"), "轻客")
        .when(F.col("body_structure").contains("两厢"), "两厢车")
        .when(
            F.col("level_name").rlike("微型车|小型车|紧凑型车|中型车|中大型车|大型车"),
            "轿车",
        )
        .otherwise(F.trim("body_structure"))
    )
    valid = (
        raw.select(
            F.trim("source_key").alias("source_key"),
            F.trim("series_id").alias("series_id"),
            F.trim("model_name").alias("model_name"),
            F.trim("brand").alias("brand"),
            "price_min_wan",
            F.when(F.col("price_max_wan") >= F.col("price_min_wan"), F.col("price_max_wan"))
            .otherwise(F.col("price_min_wan"))
            .alias("price_max_wan"),
            body_type.alias("body_type"),
            F.trim("energy_type").alias("energy_type"),
            F.when(F.col("seats").between(2, 9), F.col("seats")).alias("seats"),
            F.when(F.col("range_km") > 0, F.col("range_km")).alias("range_km"),
            F.when(F.col("fuel_consumption").between(0.1, 30), F.col("fuel_consumption")).alias(
                "fuel_consumption"
            ),
            F.when(F.col("horsepower") > 0, F.col("horsepower")).alias("horsepower"),
            F.when(F.col("model_year").between(2000, 2100), F.col("model_year")).alias(
                "model_year"
            ),
            F.when(F.col("sales") >= 0, F.col("sales")).alias("sales"),
            "sales_period",
            "trim_count",
            "source_url",
            "options_url",
            "sales_url",
            F.col("captured_at").alias("updated_at"),
        )
        .filter(
            F.col("source_key").isNotNull()
            & F.col("model_name").isNotNull()
            & F.col("brand").isNotNull()
            & (F.col("price_min_wan") > 0)
            & F.col("body_type").isNotNull()
            & F.col("energy_type").isin("燃油", "纯电", "插混", "增程", "混动")
        )
        .dropDuplicates(["source_key"])
    )

    sales_log = F.when(F.col("sales") > 0, F.log(F.col("sales") + F.lit(1)))
    max_sales_log = valid.select(F.max(sales_log).alias("value")).first()["value"]
    normalized_heat = F.when(
        F.lit(max_sales_log).isNotNull() & (F.lit(max_sales_log) > 0),
        F.round(sales_log / F.lit(max_sales_log), 4),
    ).otherwise(F.lit(None).cast(T.DoubleType()))

    with_features = valid.withColumns(
        {
            "car_id": F.concat(F.lit("car_"), F.substring(F.sha2("source_key", 256), 1, 12)),
            "price_mid_wan": F.round(
                (F.col("price_min_wan") + F.col("price_max_wan")) / 2, 2
            ),
            "normalized_heat": normalized_heat,
            "heat_score": normalized_heat,
            "source": F.lit("16888.com 车主之家"),
        }
    )

    tags = F.array_compact(
        F.array(
            F.when(
                (F.col("energy_type") == "纯电")
                | F.col("energy_type").isin("插混", "增程", "混动")
                | (F.col("fuel_consumption") <= 8.5),
                F.lit("城市通勤"),
            ),
            F.when(
                (F.col("seats") >= 5) & F.col("body_type").isin("SUV", "MPV"),
                F.lit("家庭出行"),
            ),
            F.when(
                F.col("energy_type").isin("燃油", "插混", "增程", "混动")
                | (F.col("range_km") >= 500),
                F.lit("长途出行"),
            ),
        )
    )
    optional_present = sum(
        F.when(F.col(name).isNotNull(), F.lit(1)).otherwise(F.lit(0))
        for name in [
            "seats",
            "range_km",
            "fuel_consumption",
            "horsepower",
            "model_year",
            "sales",
        ]
    )

    return (
        with_features.withColumns(
            {
                "scenario_tags": F.concat_ws("|", tags),
                "data_completeness": F.round((F.lit(6) + optional_present) / F.lit(12), 2),
            }
        )
        .select(
            "car_id",
            "series_id",
            "model_name",
            "brand",
            "price_min_wan",
            "price_max_wan",
            "price_mid_wan",
            "body_type",
            "energy_type",
            "seats",
            "range_km",
            "fuel_consumption",
            "horsepower",
            "model_year",
            "sales",
            "sales_period",
            "trim_count",
            "heat_score",
            "normalized_heat",
            "scenario_tags",
            "data_completeness",
            "source",
            "source_url",
            "options_url",
            "sales_url",
            "updated_at",
        )
        .orderBy("car_id")
    )


def collect_stats(cars: DataFrame, input_rows: int, output_rows: int) -> dict[str, object]:
    def distribution(column: str) -> list[dict[str, object]]:
        return [
            {column: row[column], "count": row["count"]}
            for row in cars.groupBy(column).count().orderBy(F.desc("count"), column).collect()
        ]

    price = cars.select(
        F.round(F.min("price_min_wan"), 2).alias("min"),
        F.round(F.max("price_max_wan"), 2).alias("max"),
        F.round(F.avg("price_mid_wan"), 2).alias("average"),
    ).first()
    sales = cars.select(
        F.max("sales_period").alias("latest_period"),
        F.max("sales").alias("max_monthly_sales"),
    ).first()
    return {
        "input_rows": input_rows,
        "output_rows": output_rows,
        "removed_rows": input_rows - output_rows,
        "price_wan": price.asDict(),
        "sales": sales.asDict(),
        "energy_distribution": distribution("energy_type"),
        "body_distribution": distribution("body_type"),
    }


def write_single_csv(cars: DataFrame, output_file: Path, temp_dir: Path) -> None:
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    cars.coalesce(1).write.mode("overwrite").option("header", True).csv(str(temp_dir))
    part_file = next(temp_dir.glob("part-*.csv"))
    output_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(part_file), output_file)
    shutil.rmtree(temp_dir)


def run(input_path: Path, output_dir: Path) -> dict[str, object]:
    if not input_path.exists():
        raise FileNotFoundError(f"原始数据不存在：{input_path}")
    spark = (
        SparkSession.builder.master("local[*]")
        .appName("spark-car-recommendation-clean")
        .config("spark.sql.session.timeZone", "Asia/Shanghai")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    try:
        raw = spark.read.option("header", True).schema(RAW_SCHEMA).csv(str(input_path))
        input_rows = raw.count()
        cars = clean_dataframe(raw).cache()
        output_rows = cars.count()
        stats = collect_stats(cars, input_rows, output_rows)

        output_dir.mkdir(parents=True, exist_ok=True)
        write_single_csv(cars, output_dir / "cars.csv", output_dir / "_spark_tmp")
        cars.coalesce(1).write.mode("overwrite").parquet(str(output_dir / "cars.parquet"))
        (output_dir / "stats.json").write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        metadata = {
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "spark_version": spark.version,
            "data_source": "16888.com 车主之家",
            "input_file": str(input_path),
            "input_sha256": file_sha256(input_path),
            "output_file": str(output_dir / "cars.csv"),
            **{key: stats[key] for key in ["input_rows", "output_rows", "removed_rows"]},
        }
        (output_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"stats": stats, "metadata": metadata}
    finally:
        spark.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="PySpark 16888 汽车数据清洗任务")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    print(json.dumps(run(args.input, args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
