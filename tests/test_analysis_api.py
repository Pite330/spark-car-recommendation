from __future__ import annotations

import csv
import json
from pathlib import Path

from src.web.app import create_app


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _analysis_fixture(path: Path) -> None:
    path.mkdir()
    (path / "model_metrics.json").write_text(
        json.dumps(
            {
                "sales_period": "2026-06",
                "analysis_rows": 425,
                "parameter_definitions": 187,
                "adapter_features": 137,
                "model_features": 2,
                "fdr_significant_features_0_05": 1,
                "incremental_mean_r2": {"elastic_net": 0.04, "random_forest": 0.05},
                "model_metrics": {
                    "baseline_elastic_net": {"mean": {"r2": 0.2, "rmse": 1.9, "mae": 1.5}},
                    "full_elastic_net": {"mean": {"r2": 0.24, "rmse": 1.8, "mae": 1.4}},
                    "full_random_forest": {"mean": {"r2": 0.25, "rmse": 1.7, "mae": 1.3}},
                },
                "interpretation": "探索性关联，不代表因果影响",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    common = [
        {"feature_name": "feature_low", "group_name": "安全", "parameter_name": "B", "parameter_type": "equipment"},
        {"feature_name": "feature_high", "group_name": "动力", "parameter_name": "A", "parameter_type": "numeric"},
    ]
    _write_csv(
        path / "univariate_associations.csv",
        ["feature_name", "group_name", "parameter_name", "parameter_type", "spearman_rho", "fdr_q_value"],
        [
            {**common[0], "spearman_rho": -0.1, "fdr_q_value": 0.2},
            {**common[1], "spearman_rho": 0.3, "fdr_q_value": 0.01},
        ],
    )
    _write_csv(
        path / "parameter_importance.csv",
        ["feature_name", "group_name", "parameter_name", "parameter_type", "elastic_net_coefficient", "random_forest_importance"],
        [
            {**common[0], "elastic_net_coefficient": -0.2, "random_forest_importance": 0.1},
            {**common[1], "elastic_net_coefficient": 0.4, "random_forest_importance": 0.9},
        ],
    )
    _write_csv(
        path / "parameter_quality.csv",
        ["feature_name", "group_name", "parameter_name", "parameter_type", "selected_for_adapter", "selected_for_model"],
        [
            {**common[0], "selected_for_adapter": "True", "selected_for_model": "True"},
            {**common[1], "selected_for_adapter": "True", "selected_for_model": "True"},
        ],
    )
    _write_csv(
        path / "consolidated_parameter_results.csv",
        [
            "feature_name", "group_name", "parameter_name", "parameter_type",
            "spearman_rho", "fdr_q_value", "elastic_net_coefficient",
            "random_forest_importance", "evidence_strength",
            "association_direction", "trend_status", "excluded_reason",
        ],
        [
            {**common[0], "spearman_rho": -0.1, "fdr_q_value": 0.2, "elastic_net_coefficient": -0.2, "random_forest_importance": 0.1, "evidence_strength": "weak", "association_direction": "negative", "trend_status": "insufficient_history", "excluded_reason": ""},
            {**common[1], "spearman_rho": 0.3, "fdr_q_value": 0.01, "elastic_net_coefficient": 0.4, "random_forest_importance": 0.9, "evidence_strength": "strong", "association_direction": "positive", "trend_status": "insufficient_history", "excluded_reason": ""},
            {"feature_name": "", "group_name": "外部配置", "parameter_name": "C", "parameter_type": "categorical", "spearman_rho": "", "fdr_q_value": "", "elastic_net_coefficient": "", "random_forest_importance": "", "evidence_strength": "not_evaluated", "association_direction": "not_evaluated", "trend_status": "insufficient_history", "excluded_reason": "unsupported_type"},
        ],
    )


def test_analysis_overview_merges_and_sorts_features(tmp_path, dataset_file):
    analysis_dir = tmp_path / "analysis"
    _analysis_fixture(analysis_dir)
    app = create_app(
        {"TESTING": True, "DATASET_PATH": str(dataset_file)}, analysis_dir=analysis_dir
    )

    response = app.test_client().get("/api/analysis/overview?limit=1")

    assert response.status_code == 200
    assert response.json["available"] is True
    assert response.json["sales_period"] == "2026-06"
    assert response.json["incremental_r2"] == {"elastic_net": 0.04, "random_forest": 0.05}
    assert [metric["key"] for metric in response.json["metrics"]] == [
        "baseline_elastic_net",
        "full_elastic_net",
        "full_random_forest",
    ]
    assert response.json["top_parameters"] == [
        {
            "feature_name": "feature_high",
            "group_name": "动力",
            "parameter_name": "A",
            "parameter_type": "numeric",
            "spearman_rho": 0.3,
            "fdr_q_value": 0.01,
            "elastic_net_coefficient": 0.4,
            "random_forest_importance": 0.9,
            "evidence_strength": "strong",
            "association_direction": "positive",
            "trend_status": "insufficient_history",
            "excluded_reason": "",
        }
    ]
    all_parameters = app.test_client().get("/api/analysis/overview?limit=10").json[
        "top_parameters"
    ]
    assert len(all_parameters) == 3
    assert all_parameters[-1]["feature_name"] == "raw:外部配置|C"
    assert all_parameters[-1]["evidence_strength"] == "not_evaluated"


def test_missing_analysis_is_a_degraded_200_and_recommendation_still_works(tmp_path, dataset_file):
    app = create_app(
        {
            "TESTING": True,
            "DATASET_PATH": str(dataset_file),
            "ANALYSIS_DIR": str(tmp_path / "missing"),
        }
    )
    client = app.test_client()

    overview = client.get("/api/analysis/overview")
    health = client.get("/api/health")
    recommendation = client.post(
        "/api/recommend",
        json={
            "budget_min_wan": 15,
            "budget_max_wan": 20,
            "body_type": "SUV",
            "energy_type": "纯电",
            "brands": [],
            "scenario": "城市通勤",
            "min_seats": 5,
            "limit": 5,
            "use_llm": False,
        },
    )

    assert overview.status_code == 200
    assert overview.json["available"] is False
    assert overview.json["top_parameters"] == []
    assert len(overview.json["warnings"]) == 4
    assert health.status_code == 200
    assert health.json["dataset_loaded"] is True
    assert recommendation.status_code == 200
    assert recommendation.json["recommendations"]


def test_analysis_limit_validation(tmp_path, dataset_file):
    app = create_app(
        {"TESTING": True, "DATASET_PATH": str(dataset_file)}, analysis_dir=tmp_path
    )
    client = app.test_client()

    for value in ("0", "501", "abc", "1.5"):
        response = client.get(f"/api/analysis/overview?limit={value}")
        assert response.status_code == 400
        assert response.json["error"] == {
            "code": "INVALID_LIMIT",
            "message": "limit 必须是 1 到 500 之间的整数",
            "field": "limit",
        }
