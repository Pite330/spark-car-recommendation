from __future__ import annotations

from .errors import RecommendationError


ALLOWED_SCENARIOS = {"城市通勤", "家庭出行", "长途出行"}


def _required_number(payload: dict[str, object], field: str, label: str) -> float:
    value = payload.get(field)
    if value is None or isinstance(value, bool):
        raise RecommendationError("MISSING_FIELD", f"请填写{label}", field)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RecommendationError("INVALID_NUMBER", f"{label}必须是数字", field) from exc
    if number <= 0:
        raise RecommendationError("INVALID_BUDGET", f"{label}必须大于 0", field)
    return number


def validate_request(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise RecommendationError("INVALID_JSON", "请求体必须是 JSON 对象")

    budget_min = _required_number(payload, "budget_min_wan", "预算下限")
    budget_max = _required_number(payload, "budget_max_wan", "预算上限")
    if budget_min > budget_max:
        raise RecommendationError(
            "INVALID_BUDGET", "预算下限不能高于预算上限", "budget_min_wan"
        )

    brands = payload.get("brands") or []
    if not isinstance(brands, list) or any(not isinstance(item, str) for item in brands):
        raise RecommendationError("INVALID_BRANDS", "品牌偏好必须是字符串数组", "brands")

    limit = payload.get("limit", 5)
    if isinstance(limit, bool):
        raise RecommendationError("INVALID_LIMIT", "推荐数量必须是 3—5", "limit")
    try:
        limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise RecommendationError("INVALID_LIMIT", "推荐数量必须是 3—5", "limit") from exc
    if limit < 3 or limit > 5:
        raise RecommendationError("INVALID_LIMIT", "推荐数量必须是 3—5", "limit")

    min_seats = payload.get("min_seats")
    if min_seats not in (None, ""):
        try:
            min_seats = int(min_seats)
        except (TypeError, ValueError) as exc:
            raise RecommendationError("INVALID_SEATS", "最低座位数必须是整数", "min_seats") from exc
        if min_seats < 2 or min_seats > 9:
            raise RecommendationError("INVALID_SEATS", "最低座位数必须在 2—9 之间", "min_seats")
    else:
        min_seats = None

    scenario = str(payload.get("scenario") or "").strip()
    if scenario and scenario not in ALLOWED_SCENARIOS:
        raise RecommendationError("INVALID_SCENARIO", "不支持该使用场景", "scenario")

    return {
        "budget_min_wan": round(budget_min, 2),
        "budget_max_wan": round(budget_max, 2),
        "body_type": str(payload.get("body_type") or "").strip(),
        "energy_type": str(payload.get("energy_type") or "").strip(),
        "brands": sorted({item.strip() for item in brands if item.strip()}),
        "scenario": scenario,
        "min_seats": min_seats,
        "limit": limit,
        "use_llm": bool(payload.get("use_llm", False)),
    }
