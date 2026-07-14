from __future__ import annotations

import csv

import pytest


@pytest.fixture
def sample_cars():
    return [
        {
            "car_id": f"car_{index}",
            "model_name": f"测试车型 {index}",
            "brand": "品牌甲" if index < 4 else "品牌乙",
            "price_min_wan": price,
            "price_max_wan": price,
            "price_mid_wan": price,
            "body_type": "SUV",
            "energy_type": "纯电",
            "seats": 5,
            "range_km": 400 + index * 25,
            "fuel_consumption": None,
            "horsepower": 150 + index * 10,
            "model_year": 2025,
            "sales": [1200, 900, 600, 300, 100][index],
            "sales_period": "2026-06",
            "trim_count": 3 + index,
            "normalized_heat": None,
            "scenario_tags": ["城市通勤", "家庭出行"],
            "data_completeness": 1.0,
        }
        for index, price in enumerate([15.5, 17.5, 18.5, 19.5, 20.8])
    ]


@pytest.fixture
def dataset_file(tmp_path, sample_cars):
    path = tmp_path / "cars.csv"
    fields = list(sample_cars[0])
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for car in sample_cars:
            row = dict(car)
            row["scenario_tags"] = "|".join(row["scenario_tags"])
            writer.writerow(row)
    return path
