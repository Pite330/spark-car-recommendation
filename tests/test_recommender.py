from __future__ import annotations

import pytest

from src.recommender import RecommendationEngine, RecommendationError


BASE_REQUEST = {
    "budget_min_wan": 15,
    "budget_max_wan": 20,
    "body_type": "SUV",
    "energy_type": "纯电",
    "brands": [],
    "scenario": "城市通勤",
    "min_seats": 5,
    "limit": 5,
    "use_llm": False,
}


def test_recommendation_is_deterministic_and_explainable(sample_cars):
    engine = RecommendationEngine(sample_cars)
    first = engine.recommend(BASE_REQUEST)
    second = engine.recommend(BASE_REQUEST)

    assert [car["car_id"] for car in first["recommendations"]] == [
        car["car_id"] for car in second["recommendations"]
    ]
    assert len(first["recommendations"]) == 4
    assert all(len(car["matched_factors"]) >= 2 for car in first["recommendations"])
    assert all(car["reason_source"] == "template" for car in first["recommendations"])


def test_invalid_budget_is_rejected(sample_cars):
    with pytest.raises(RecommendationError) as captured:
        RecommendationEngine(sample_cars).recommend(
            {**BASE_REQUEST, "budget_min_wan": 21, "budget_max_wan": 20}
        )
    assert captured.value.code == "INVALID_BUDGET"


def test_brand_is_relaxed_when_it_would_leave_too_few_candidates(sample_cars):
    result = RecommendationEngine(sample_cars).recommend(
        {**BASE_REQUEST, "brands": ["品牌乙"]}
    )
    assert any("品牌偏好" in item for item in result["relaxed_conditions"])
    assert len(result["recommendations"]) >= 3


def test_budget_expansion_is_reported(sample_cars):
    result = RecommendationEngine(sample_cars).recommend(
        {**BASE_REQUEST, "budget_min_wan": 19, "budget_max_wan": 20}
    )
    assert any("预算上限放宽" in item for item in result["relaxed_conditions"])


def test_missing_optional_fields_do_not_block_recommendation(sample_cars):
    for car in sample_cars:
        car["range_km"] = None
        car["normalized_heat"] = None
    result = RecommendationEngine(sample_cars).recommend(BASE_REQUEST)
    assert result["recommendations"]
    assert all("score" in car for car in result["recommendations"])


def test_minimum_sales_filters_unknown_and_low_sales_cars(sample_cars):
    sample_cars[-1]["sales"] = None
    result = RecommendationEngine(sample_cars).recommend(
        {**BASE_REQUEST, "min_sales": 500}
    )
    assert len(result["recommendations"]) == 3
    assert all(car["sales"] >= 500 for car in result["recommendations"])


def test_compare_accepts_two_or_three_known_cars(sample_cars):
    engine = RecommendationEngine(sample_cars)
    cars = engine.compare(["car_0", "car_1"])
    assert [car["car_id"] for car in cars] == ["car_0", "car_1"]
    assert [car["sales"] for car in cars] == [1200, 900]
    assert [car["trim_count"] for car in cars] == [3, 4]

    with pytest.raises(RecommendationError) as captured:
        engine.compare(["car_0"])
    assert captured.value.code == "INVALID_COMPARE_COUNT"
