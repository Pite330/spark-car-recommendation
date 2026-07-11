from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any


ANALYSIS_FILES = (
    "model_metrics.json",
    "univariate_associations.csv",
    "parameter_importance.csv",
    "parameter_quality.csv",
)

METRIC_LABELS = {
    "baseline_elastic_net": "控制变量基线",
    "full_elastic_net": "Elastic Net（含配置参数）",
    "full_random_forest": "随机森林（含配置参数）",
}


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _integer(value: object) -> int:
    number = _number(value)
    return int(number) if number is not None else 0


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON 顶层必须是对象")
    return payload


def _read_csv(path: Path, required_fields: set[str]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing = sorted(required_fields - fields)
        if missing:
            raise ValueError(f"缺少字段: {', '.join(missing)}")
        return [dict(row) for row in reader]


def _safe_read(
    analysis_dir: Path,
    filename: str,
    reader,
    warnings: list[str],
):
    path = analysis_dir / filename
    try:
        return reader(path), True
    except FileNotFoundError:
        warnings.append(f"分析结果文件缺失：{filename}")
    except (OSError, UnicodeError, csv.Error, json.JSONDecodeError, ValueError) as exc:
        warnings.append(f"分析结果文件无法读取：{filename}（{exc}）")
    return None, False


def load_analysis_overview(analysis_dir: Path, limit: int = 24) -> dict[str, object]:
    """加载可选的离线分析结果；任何单文件失败都返回可序列化的降级响应。"""
    warnings: list[str] = []
    metrics_data, metrics_ok = _safe_read(
        analysis_dir, "model_metrics.json", _read_json, warnings
    )
    associations, associations_ok = _safe_read(
        analysis_dir,
        "univariate_associations.csv",
        lambda path: _read_csv(path, {"feature_name", "spearman_rho", "fdr_q_value"}),
        warnings,
    )
    importance, importance_ok = _safe_read(
        analysis_dir,
        "parameter_importance.csv",
        lambda path: _read_csv(
            path,
            {
                "feature_name",
                "group_name",
                "parameter_name",
                "parameter_type",
                "elastic_net_coefficient",
                "random_forest_importance",
            },
        ),
        warnings,
    )
    quality, quality_ok = _safe_read(
        analysis_dir,
        "parameter_quality.csv",
        lambda path: _read_csv(
            path,
            {"feature_name", "selected_for_adapter", "selected_for_model"},
        ),
        warnings,
    )
    consolidated_path = analysis_dir / "consolidated_parameter_results.csv"
    consolidated = None
    consolidated_ok = not consolidated_path.exists()
    if consolidated_path.exists():
        consolidated, consolidated_ok = _safe_read(
            analysis_dir,
            "consolidated_parameter_results.csv",
            lambda path: _read_csv(
                path,
                {
                    "feature_name",
                    "group_name",
                    "parameter_name",
                    "parameter_type",
                    "spearman_rho",
                    "fdr_q_value",
                    "elastic_net_coefficient",
                    "random_forest_importance",
                    "evidence_strength",
                    "association_direction",
                    "trend_status",
                },
            ),
            warnings,
        )

    metrics_data = metrics_data or {}
    associations = associations or []
    importance = importance or []
    quality = quality or []
    consolidated = consolidated or []

    association_by_feature = {
        row.get("feature_name", ""): row for row in associations if row.get("feature_name")
    }
    quality_by_feature = {
        row.get("feature_name", ""): row for row in quality if row.get("feature_name")
    }
    source_rows = consolidated if consolidated else importance
    top_parameters: list[dict[str, object]] = []
    for row in source_rows:
        original_feature_name = row.get("feature_name", "")
        if not original_feature_name and not consolidated:
            continue
        group_name = row.get("group_name") or ""
        parameter_name = row.get("parameter_name") or ""
        feature_name = original_feature_name or f"raw:{group_name}|{parameter_name}"
        association = association_by_feature.get(original_feature_name, {})
        quality_row = quality_by_feature.get(original_feature_name, {})
        top_parameters.append(
            {
                "feature_name": feature_name,
                "group_name": row.get("group_name") or quality_row.get("group_name") or "",
                "parameter_name": row.get("parameter_name") or quality_row.get("parameter_name") or "",
                "parameter_type": row.get("parameter_type") or quality_row.get("parameter_type") or "",
                "spearman_rho": _number(association.get("spearman_rho")),
                "fdr_q_value": _number(association.get("fdr_q_value")),
                "elastic_net_coefficient": _number(row.get("elastic_net_coefficient")),
                "random_forest_importance": _number(row.get("random_forest_importance")),
                "evidence_strength": row.get("evidence_strength") or "",
                "association_direction": row.get("association_direction") or "",
                "trend_status": row.get("trend_status") or metrics_data.get("trend_status") or "",
                "excluded_reason": row.get("excluded_reason") or quality_row.get("excluded_reason") or "",
            }
        )
    top_parameters.sort(
        key=lambda row: row["random_forest_importance"]
        if row["random_forest_importance"] is not None
        else -1.0,
        reverse=True,
    )

    raw_models = metrics_data.get("model_metrics", {})
    model_metrics = raw_models if isinstance(raw_models, dict) else {}
    metrics: list[dict[str, object]] = []
    for key, label in METRIC_LABELS.items():
        model = model_metrics.get(key, {})
        mean = model.get("mean", {}) if isinstance(model, dict) else {}
        if not isinstance(mean, dict):
            mean = {}
        metrics.append(
            {
                "key": key,
                "label": label,
                "r2": _number(mean.get("r2")),
                "rmse": _number(mean.get("rmse")),
                "mae": _number(mean.get("mae")),
            }
        )

    incremental = metrics_data.get("incremental_mean_r2", {})
    incremental = incremental if isinstance(incremental, dict) else {}
    significant_from_csv = sum(
        value is not None and value < 0.05
        for value in (_number(row.get("fdr_q_value")) for row in associations)
    )
    selected_adapter = sum(
        str(row.get("selected_for_adapter", "")).lower() == "true" for row in quality
    )
    selected_model = sum(
        str(row.get("selected_for_model", "")).lower() == "true" for row in quality
    )
    interpretation = metrics_data.get("interpretation")
    if isinstance(interpretation, str) and interpretation:
        warnings.append(interpretation)
    trend_reason = metrics_data.get("trend_status_reason")
    if isinstance(trend_reason, str) and trend_reason:
        warnings.append(trend_reason)

    return {
        "available": metrics_ok and associations_ok and importance_ok and quality_ok and consolidated_ok,
        "sales_period": metrics_data.get("sales_period") or None,
        "analysis_rows": _integer(metrics_data.get("analysis_rows")),
        "parameter_definitions": _integer(metrics_data.get("parameter_definitions")) or len(quality),
        "adapter_features": _integer(metrics_data.get("adapter_features")) or selected_adapter,
        "model_features": _integer(metrics_data.get("model_features")) or selected_model,
        "significant_features": _integer(metrics_data.get("fdr_significant_features_0_05"))
        or significant_from_csv,
        "incremental_r2": {
            "elastic_net": _number(incremental.get("elastic_net")),
            "random_forest": _number(incremental.get("random_forest")),
        },
        "metrics": metrics,
        "top_parameters": top_parameters[:limit],
        "trend_status": metrics_data.get("trend_status") or "insufficient_history",
        "trend_status_reason": trend_reason or "仅有单期配置快照，暂不输出未来趋势判断",
        "warnings": warnings,
    }
