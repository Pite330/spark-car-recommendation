from __future__ import annotations

import csv
from pathlib import Path


FLOAT_FIELDS = {
    "price_min_wan",
    "price_max_wan",
    "price_mid_wan",
    "range_km",
    "fuel_consumption",
    "heat_score",
    "normalized_heat",
    "data_completeness",
}
INTEGER_FIELDS = {"seats", "horsepower", "model_year", "sales"}


def _number(value: str | None, converter):
    if value is None or not value.strip():
        return None
    return converter(float(value)) if converter is int else converter(value)


def load_cars(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        raise FileNotFoundError(f"标准车型数据不存在：{path}，请先运行 Spark 清洗任务")

    cars: list[dict[str, object]] = []
    with path.open(encoding="utf-8", newline="") as file:
        for raw in csv.DictReader(file):
            car: dict[str, object] = dict(raw)
            for field in FLOAT_FIELDS:
                if field in car:
                    car[field] = _number(raw.get(field), float)
            for field in INTEGER_FIELDS:
                if field in car:
                    car[field] = _number(raw.get(field), int)
            tags = str(raw.get("scenario_tags", ""))
            car["scenario_tags"] = [tag for tag in tags.split("|") if tag]
            cars.append(car)
    return cars
