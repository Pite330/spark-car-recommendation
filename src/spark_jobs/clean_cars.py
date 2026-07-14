from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("JAVA_TOOL_OPTIONS", "-Djava.security.manager=allow")

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T


DEFAULT_INPUT = Path("data/raw/16888_full/tables")
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

FULL_SERIES_SCHEMA = T.StructType(
    [
        T.StructField("series_id", T.StringType(), True),
        T.StructField("series_name", T.StringType(), True),
        T.StructField("list_price_min_wan", T.DoubleType(), True),
        T.StructField("list_price_max_wan", T.DoubleType(), True),
        T.StructField("body_hints", T.StringType(), True),
        T.StructField("energy_hints", T.StringType(), True),
        T.StructField("source_url", T.StringType(), True),
        T.StructField("options_url", T.StringType(), True),
        T.StructField("sales_url", T.StringType(), True),
        T.StructField("captured_at", T.StringType(), True),
    ]
)

FULL_TRIM_SCHEMA = T.StructType(
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

FULL_PARAMETER_SCHEMA = T.StructType(
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

FULL_SALES_SCHEMA = T.StructType(
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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def input_sha256(path: Path) -> str:
    if path.is_file():
        return file_sha256(path)
    digest = hashlib.sha256()
    for child in sorted(path.glob("*.csv*")):
        digest.update(child.name.encode("utf-8"))
        digest.update(file_sha256(child).encode("ascii"))
    return digest.hexdigest()


def normalized_energy_type(column):
    text = F.lower(F.trim(column))
    return (
        F.when(text.contains("插电式混合") | text.contains("插混") | text.contains("phev"), "插混")
        .when(text.contains("增程"), "增程")
        .when(text.contains("纯电"), "纯电")
        .when(
            text.contains("油电混合")
            | text.contains("非插电式混合")
            | text.contains("轻混")
            | text.contains("电驱")
            | text.contains("hev"),
            "混动",
        )
        .when(
            text.contains("汽油")
            | text.contains("柴油")
            | text.contains("cng")
            | text.contains("天然气")
            | text.contains("燃油"),
            "燃油",
        )
    )


def full_tables_dataframe(spark: SparkSession, tables: Path) -> DataFrame:
    required = ["series.csv", "trims.csv", "trim_parameters.csv.gz", "series_month_sales.csv"]
    missing = [name for name in required if not (tables / name).exists()]
    if missing:
        raise FileNotFoundError(f"完整车型表缺失：{', '.join(missing)}")

    series = spark.read.option("header", True).schema(FULL_SERIES_SCHEMA).csv(str(tables / "series.csv"))
    trims = spark.read.option("header", True).schema(FULL_TRIM_SCHEMA).csv(str(tables / "trims.csv"))
    parameters = spark.read.option("header", True).schema(FULL_PARAMETER_SCHEMA).csv(
        str(tables / "trim_parameters.csv.gz")
    )
    sales = spark.read.option("header", True).schema(FULL_SALES_SCHEMA).csv(
        str(tables / "series_month_sales.csv")
    )

    trim_base = trims.select(
        "trim_id",
        "series_id",
        normalized_energy_type(F.col("energy_type_raw")).alias("energy_type"),
        F.trim("body_structure").alias("body_structure"),
        F.expr(
            "try_cast(regexp_extract(seats_raw, '([2-9])(?!.*[2-9])', 1) as int)"
        ).alias("seats"),
        "model_year",
    ).filter(F.col("energy_type").isNotNull())

    trim_summary = trim_base.groupBy("series_id", "energy_type").agg(
        F.min(F.when(~F.col("body_structure").isin("", "-"), F.col("body_structure"))).alias(
            "body_structure"
        ),
        F.max("seats").alias("seats"),
        F.max("model_year").alias("model_year"),
        F.countDistinct("trim_id").alias("trim_count"),
    )

    relevant_names = ["厂商指导价(元)", "厂商", "级别", "工信部综合油耗(L)", "最大马力(Ps)"]
    grouped_parameters = (
        parameters.filter(F.col("parameter_name").isin(relevant_names))
        .join(trim_base.select("trim_id", "series_id", "energy_type"), ["trim_id", "series_id"], "inner")
        .groupBy("series_id", "energy_type")
        .agg(
            F.first(F.when(F.col("parameter_name") == "厂商", F.col("value_text")), ignorenulls=True).alias("brand"),
            F.first(F.when(F.col("parameter_name") == "级别", F.col("value_text")), ignorenulls=True).alias("level_name"),
            F.min(F.when(F.col("parameter_name") == "厂商指导价(元)", F.col("value_numeric"))).alias("parameter_price_min_wan"),
            F.max(F.when(F.col("parameter_name") == "厂商指导价(元)", F.col("value_numeric"))).alias("parameter_price_max_wan"),
            F.expr("percentile_approx(IF(parameter_name = '工信部综合油耗(L)', value_numeric, NULL), 0.5, 1000)").alias("fuel_consumption"),
            F.expr("percentile_approx(IF(parameter_name = '最大马力(Ps)', value_numeric, NULL), 0.5, 1000)").cast("int").alias("horsepower"),
        )
    )

    latest_period = sales.filter(F.col("sales").isNotNull()).agg(F.max("sales_period")).first()[0]
    latest_sales = (
        sales.filter((F.col("sales_period") == latest_period) & (F.col("sales") >= 0))
        .groupBy("series_id")
        .agg(F.max("sales").alias("sales"))
        .withColumn("sales_period", F.lit(latest_period))
    )

    return (
        series.join(trim_summary, "series_id", "inner")
        .join(grouped_parameters, ["series_id", "energy_type"], "left")
        .join(latest_sales, "series_id", "left")
        .select(
            F.concat_ws("-", F.col("series_id"), F.col("energy_type")).alias("source_key"),
            "series_id",
            F.col("series_name").alias("model_name"),
            "brand",
            F.coalesce("parameter_price_min_wan", "list_price_min_wan").alias("price_min_wan"),
            F.coalesce("parameter_price_max_wan", "list_price_max_wan").alias("price_max_wan"),
            F.coalesce("level_name", "body_hints").alias("level_name"),
            "body_structure",
            "energy_type",
            "seats",
            F.lit(None).cast("double").alias("range_km"),
            "fuel_consumption",
            "horsepower",
            "model_year",
            "sales",
            "sales_period",
            "trim_count",
            "source_url",
            "options_url",
            "sales_url",
            F.to_date("captured_at").alias("captured_at"),
        )
    )


def clean_dataframe(raw: DataFrame) -> DataFrame:
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
            & ~F.trim(F.col("brand")).isin("", "-", "--")
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
        raw = (
            full_tables_dataframe(spark, input_path)
            if input_path.is_dir()
            else spark.read.option("header", True).schema(RAW_SCHEMA).csv(str(input_path))
        )
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
            "input_sha256": input_sha256(input_path),
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
