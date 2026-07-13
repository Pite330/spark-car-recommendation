from __future__ import annotations

import json
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_spark_outputs_and_metadata_exist():
    processed = ROOT / "data/processed"
    cars = processed / "cars.csv"
    stats = json.loads((processed / "stats.json").read_text(encoding="utf-8"))
    metadata = json.loads((processed / "metadata.json").read_text(encoding="utf-8"))

    assert cars.exists() and cars.stat().st_size > 500
    assert metadata["spark_version"]
    assert metadata["data_source"] == "16888.com 车主之家"
    assert metadata["input_file"].endswith("data/raw/16888_full/tables")
    assert metadata["input_rows"] >= metadata["output_rows"] >= 1000
    with cars.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == metadata["output_rows"]
    assert len({row["series_id"] for row in rows}) >= 1500
    assert {row["energy_type"] for row in rows} == {"燃油", "纯电", "插混", "增程", "混动"}
    assert stats["sales"]["latest_period"]
    assert stats["energy_distribution"]
    assert stats["body_distribution"]
