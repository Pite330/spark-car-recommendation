"""用 PySpark 清洗公开车型快照并生成推荐主表与统计证据。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

# Hadoop 3 在 Java 23 上调用 Subject.getSubject 时需要显式允许安全管理器兼容模式。
# Java 17/21 同样接受该开关；只设置子进程环境，不修改用户全局 Java 配置。
os.environ.setdefault("JAVA_TOOL_OPTIONS", "-Djava.security.manager=allow")

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T


DEFAULT_INPUT = Path("data/raw/china_car_prices_snapshot.csv")
DEFAULT_OUTPUT_DIR = Path("data/processed")
USD_TO_CNY = 7.20

RAW_SCHEMA = T.StructType(
    [
        T.StructField("source_slug", T.StringType(), True),
        T.StructField("brand", T.StringType(), True),
        T.StructField("model_name", T.StringType(), True),
        T.StructField("powertrain", T.StringType(), True),
        T.StructField("price_usd", T.DoubleType(), True),
        T.StructField("body_style", T.StringType(), True),
        T.StructField("model_year", T.IntegerType(), True),
        T.StructField("range_km", T.DoubleType(), True),
        T.StructField("horsepower", T.IntegerType(), True),
        T.StructField("seats", T.IntegerType(), True),
        T.StructField("source_url", T.StringType(), True),
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
    """将原始英文展示字段映射为 MVP 标准字段，不推断缺失参数。"""
    body_type = (
        F.when(F.upper(F.trim("body_style")) == "SEDAN", "轿车")
        .when(F.upper(F.trim("body_style")) == "HATCHBACK", "两厢车")
        .when(F.upper(F.trim("body_style")) == "SUV", "SUV")
        .when(F.upper(F.trim("body_style")) == "MPV", "MPV")
        .when(F.upper(F.trim("body_style")) == "PICKUP", "皮卡")
        .when(F.upper(F.trim("body_style")) == "WAGON", "旅行车")
        .when(F.upper(F.trim("body_style")).isin("COUPE", "SPORTS CAR"), "跑车")
        .otherwise(F.initcap(F.trim("body_style")))
    )
    energy_type = (
        F.when(F.upper(F.trim("powertrain")) == "ICE", "燃油")
        .when(F.upper(F.trim("powertrain")) == "BEV", "纯电")
        .when(F.upper(F.trim("powertrain")) == "PHEV", "插混")
        .when(F.upper(F.trim("powertrain")) == "EREV", "增程")
        .when(F.upper(F.trim("powertrain")).isin("HEV", "HYBRID"), "混动")
        .when(F.upper(F.trim("powertrain")) == "FCEV", "氢能")
        .otherwise(F.upper(F.trim("powertrain")))
    )

    normalized = (
        raw.select(
            F.trim("source_slug").alias("source_slug"),
            F.trim("model_name").alias("model_name"),
            F.trim("brand").alias("brand"),
            "price_usd",
            body_type.alias("body_type"),
            energy_type.alias("energy_type"),
            "seats",
            "range_km",
            "horsepower",
            "model_year",
            "source_url",
            F.col("captured_at").alias("updated_at"),
        )
        .filter(
            F.col("source_slug").isNotNull()
            & F.col("model_name").isNotNull()
            & F.col("brand").isNotNull()
            & (F.col("price_usd") > 0)
            & F.col("body_type").isNotNull()
            & F.col("energy_type").isNotNull()
        )
        .filter(F.col("seats").isNull() | F.col("seats").between(2, 9))
        .filter(F.col("range_km").isNull() | (F.col("range_km") > 0))
        .dropDuplicates(["source_slug"])
    )

    price_wan = F.round(F.col("price_usd") * F.lit(USD_TO_CNY) / F.lit(10_000), 2)
    with_core = normalized.withColumns(
        {
            "car_id": F.concat(F.lit("car_"), F.substring(F.sha2("source_slug", 256), 1, 12)),
            "price_min_wan": price_wan,
            "price_max_wan": price_wan,
            "price_mid_wan": price_wan,
            "fuel_consumption": F.lit(None).cast(T.DoubleType()),
            "sales": F.lit(None).cast(T.IntegerType()),
            "heat_score": F.lit(None).cast(T.DoubleType()),
            "normalized_heat": F.lit(None).cast(T.DoubleType()),
            "source": F.lit("chinacarprices.com public model listing"),
        }
    )

    tag_array = F.array_compact(
        F.array(
            F.when(
                ((F.col("energy_type") == "纯电") & (F.col("range_km") >= 250))
                | F.col("energy_type").isin("插混", "增程", "混动", "燃油"),
                F.lit("城市通勤"),
            ),
            F.when(
                (F.col("seats") >= 5) & F.col("body_type").isin("SUV", "MPV", "旅行车"),
                F.lit("家庭出行"),
            ),
            F.when(
                (F.col("range_km") >= 500)
                | F.col("energy_type").isin("插混", "增程", "混动", "燃油"),
                F.lit("长途出行"),
            ),
        )
    )
    optional_present = sum(
        F.when(F.col(name).isNotNull(), F.lit(1)).otherwise(F.lit(0))
        for name in ["seats", "range_km", "horsepower", "model_year"]
    )

    return (
        with_core.withColumns(
            {
                "scenario_tags": F.concat_ws("|", tag_array),
                "data_completeness": F.round((F.lit(6) + optional_present) / F.lit(10), 2),
            }
        )
        .select(
            "car_id",
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
            "heat_score",
            "normalized_heat",
            "scenario_tags",
            "data_completeness",
            "source",
            "source_url",
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
    return {
        "input_rows": input_rows,
        "output_rows": output_rows,
        "removed_rows": input_rows - output_rows,
        "price_wan": price.asDict(),
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
            "input_file": str(input_path),
            "input_sha256": file_sha256(input_path),
            "output_file": str(output_dir / "cars.csv"),
            "usd_to_cny_fixed_rate": USD_TO_CNY,
            **{key: stats[key] for key in ["input_rows", "output_rows", "removed_rows"]},
        }
        (output_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"stats": stats, "metadata": metadata}
    finally:
        spark.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="PySpark 汽车数据清洗任务")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    result = run(args.input, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
