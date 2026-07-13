from __future__ import annotations

import math

from src.spark_jobs.analyze_parameter_sales import (
    average_ranks,
    benjamini_hochberg,
    classify_parameter,
    consolidated_parameter_results,
    encode_energy_type,
    feature_name,
    spearman,
    summarize_evidence,
)


def quality_row(**overrides):
    row = {
        "rows": 100,
        "blank_rows": 0,
        "numeric_rows": 0,
        "standard_rows": 0,
        "optional_rows": 0,
        "mixed_rows": 0,
        "absent_rows": 0,
    }
    row.update(overrides)
    return row


def test_parameter_classification_distinguishes_numeric_equipment_and_text():
    assert classify_parameter(quality_row(numeric_rows=90)) == "numeric"
    assert classify_parameter(quality_row(standard_rows=40, absent_rows=60)) == "equipment"
    assert classify_parameter(quality_row()) == "categorical"


def test_feature_names_are_stable_and_type_specific():
    assert feature_name("numeric", "0|基本参数|最高车速") == feature_name(
        "numeric", "0|基本参数|最高车速"
    )
    assert feature_name("numeric", "x") != feature_name("equipment", "x")


def test_rank_and_spearman_handle_ties():
    assert average_ranks([10, 20, 20, 40]) == [1.0, 2.5, 2.5, 4.0]
    rho, p_value = spearman([1, 2, 3, 4, 5], [2, 4, 6, 8, 10])
    assert math.isclose(rho, 1.0)
    assert p_value < 0.001


def test_benjamini_hochberg_is_monotonic_in_sorted_order():
    adjusted = benjamini_hochberg([0.01, 0.04, 0.03, float("nan")])
    assert adjusted[:3] == [0.03, 0.04, 0.04]
    assert math.isnan(adjusted[3])


def test_energy_type_mapping_uses_ordered_numeric_values():
    assert encode_energy_type("纯电") == 1.0
    assert encode_energy_type("插混") == 0.5
    assert encode_energy_type("燃油") == 0.0
    assert encode_energy_type(None) is None


def test_evidence_summary_requires_adjusted_signal_and_direction_agreement():
    assert summarize_evidence(0.25, 0.005, 0.12) == ("strong", "positive")
    assert summarize_evidence(-0.18, 0.03, -0.04) == ("moderate", "negative")
    assert summarize_evidence(0.21, 0.001, -0.02) == ("weak", "mixed")
    assert summarize_evidence(None, None, None) == ("not_evaluated", "not_evaluated")


def test_consolidated_results_keep_unmodeled_parameters_and_refuse_trend_claims():
    quality = [
        {
            "feature_name": "equip_abc",
            "group_name": "安全装备",
            "parameter_name": "主动刹车",
            "parameter_type": "equipment",
            "selected_for_model": True,
            "excluded_reason": "",
        },
        {
            "feature_name": "",
            "group_name": "基本参数",
            "parameter_name": "车款人气",
            "parameter_type": "numeric",
            "selected_for_model": False,
            "excluded_reason": "target_leakage",
        },
    ]
    associations = [
        {
            "feature_name": "equip_abc",
            "n": 300,
            "spearman_rho": 0.23,
            "fdr_q_value": 0.004,
        }
    ]
    importance = [
        {
            "feature_name": "equip_abc",
            "elastic_net_coefficient": 0.08,
            "random_forest_importance": 0.03,
        }
    ]

    rows = consolidated_parameter_results(quality, associations, importance)

    assert len(rows) == 2
    active_brake = next(row for row in rows if row["parameter_name"] == "主动刹车")
    popularity = next(row for row in rows if row["parameter_name"] == "车款人气")
    assert active_brake["evidence_strength"] == "strong"
    assert active_brake["association_direction"] == "positive"
    assert active_brake["trend_status"] == "insufficient_history"
    assert popularity["evidence_strength"] == "not_evaluated"
    assert popularity["excluded_reason"] == "target_leakage"
    assert popularity["trend_status"] == "insufficient_history"
