from __future__ import annotations

from .errors import RecommendationError
from .reasons import build_template_reason
from .validation import validate_request


WEIGHTS = {
    "price": 0.35,
    "body_type": 0.20,
    "energy_type": 0.20,
    "scenario": 0.15,
    "brand": 0.05,
    "heat": 0.05,
}

PUBLIC_FIELDS = [
    "car_id",
    "model_name",
    "brand",
    "price_min_wan",
    "price_max_wan",
    "body_type",
    "energy_type",
    "seats",
    "range_km",
    "fuel_consumption",
    "horsepower",
    "model_year",
    "sales",
    "sales_period",
    "normalized_heat",
    "data_completeness",
]


class RecommendationEngine:
    def __init__(self, cars: list[dict[str, object]]) -> None:
        self.cars = list(cars)
        self.by_id = {str(car["car_id"]): car for car in self.cars}

    def catalog_context(self) -> dict[str, object]:
        def values(field: str) -> list[str]:
            return sorted({str(car[field]) for car in self.cars if car.get(field)})

        energy_counts: dict[str, int] = {}
        body_counts: dict[str, int] = {}
        for car in self.cars:
            energy = str(car.get("energy_type") or "其他")
            body = str(car.get("body_type") or "其他")
            energy_counts[energy] = energy_counts.get(energy, 0) + 1
            body_counts[body] = body_counts.get(body, 0) + 1
        return {
            "car_count": len(self.cars),
            "brands": values("brand"),
            "body_types": values("body_type"),
            "energy_types": values("energy_type"),
            "energy_distribution": [
                {"name": key, "value": value}
                for key, value in sorted(energy_counts.items(), key=lambda item: (-item[1], item[0]))
            ],
            "body_distribution": [
                {"name": key, "value": value}
                for key, value in sorted(body_counts.items(), key=lambda item: (-item[1], item[0]))
            ],
        }

    @staticmethod
    def _core_match(car: dict[str, object], request: dict[str, object], budget_max: float) -> bool:
        price_min = float(car["price_min_wan"])
        price_max = float(car.get("price_max_wan") or price_min)
        if price_min > budget_max or price_max < float(request["budget_min_wan"]):
            return False
        if request["body_type"] and car.get("body_type") != request["body_type"]:
            return False
        if request["energy_type"] and car.get("energy_type") != request["energy_type"]:
            return False
        min_seats = request.get("min_seats")
        if min_seats is not None:
            seats = car.get("seats")
            if seats is None or int(seats) < int(min_seats):
                return False
        min_sales = request.get("min_sales")
        if min_sales is not None:
            sales = car.get("sales")
            if sales is None or int(sales) < int(min_sales):
                return False
        return True

    def _filter(self, request: dict[str, object]) -> tuple[list[dict[str, object]], list[str]]:
        budget_max = float(request["budget_max_wan"])
        candidates = [car for car in self.cars if self._core_match(car, request, budget_max)]
        relaxed: list[str] = []

        brands = set(request["brands"])
        if brands:
            brand_matches = [car for car in candidates if car.get("brand") in brands]
            if len(brand_matches) >= 3:
                candidates = brand_matches
            else:
                relaxed.append("品牌偏好（候选不足 3 款）")

        scenario = str(request["scenario"])
        if scenario:
            scenario_matches = [
                car for car in candidates if scenario in (car.get("scenario_tags") or [])
            ]
            if len(scenario_matches) >= 3:
                candidates = scenario_matches
            else:
                relaxed.append("使用场景（候选不足 3 款）")

        if len(candidates) < 3:
            expanded_max = round(budget_max * 1.10, 2)
            expanded = [car for car in self.cars if self._core_match(car, request, expanded_max)]
            if len(expanded) > len(candidates):
                candidates = expanded
                relaxed.append(f"预算上限放宽 10% 至 {expanded_max:.2f} 万元")
        return candidates, relaxed

    @staticmethod
    def _price_score(car: dict[str, object], request: dict[str, object]) -> float:
        budget_min = float(request["budget_min_wan"])
        budget_max = float(request["budget_max_wan"])
        budget_mid = (budget_min + budget_max) / 2
        span = max(budget_max - budget_min, 1)
        price_mid = float(car.get("price_mid_wan") or car["price_min_wan"])
        return max(0.0, 1 - abs(price_mid - budget_mid) / span)

    @staticmethod
    def _price_factor(car: dict[str, object], request: dict[str, object]) -> str:
        price = float(car.get("price_mid_wan") or car["price_min_wan"])
        budget_min = float(request["budget_min_wan"])
        budget_max = float(request["budget_max_wan"])
        third = max((budget_max - budget_min) / 3, 0.01)
        if budget_min + third <= price <= budget_max - third:
            return "价格位于预算中段"
        if budget_min <= price <= budget_max:
            return "价格处于预算范围内"
        return "价格在放宽后的预算范围内"

    def _score(self, car: dict[str, object], request: dict[str, object]) -> dict[str, object]:
        factors: list[tuple[str, float, float]] = [
            (self._price_factor(car, request), self._price_score(car, request), WEIGHTS["price"])
        ]
        if request["body_type"]:
            factors.append(
                (f"符合{request['body_type']}车身偏好", 1.0, WEIGHTS["body_type"])
            )
        if request["energy_type"]:
            factors.append(
                (f"符合{request['energy_type']}能源偏好", 1.0, WEIGHTS["energy_type"])
            )
        if request["scenario"] and car.get("scenario_tags") is not None:
            matched = request["scenario"] in (car.get("scenario_tags") or [])
            factors.append(
                (f"参数适合{request['scenario']}", 1.0 if matched else 0.0, WEIGHTS["scenario"])
            )
        if request["brands"]:
            matched = car.get("brand") in request["brands"]
            factors.append(("符合品牌偏好", 1.0 if matched else 0.0, WEIGHTS["brand"]))
        heat = car.get("normalized_heat")
        if heat is not None:
            factors.append(("热度表现较好", float(heat), WEIGHTS["heat"]))

        denominator = sum(weight for _, _, weight in factors)
        score = 100 * sum(value * weight for _, value, weight in factors) / denominator
        ranked_labels = [
            label
            for label, value, _ in sorted(
                factors, key=lambda item: (-(item[1] * item[2]), item[0])
            )
            if value > 0
        ]

        if car.get("range_km") is not None:
            ranked_labels.append(f"标注续航 {float(car['range_km']):.0f} 公里")
        if car.get("seats") is not None:
            ranked_labels.append(f"提供 {int(car['seats'])} 座布局")
        if car.get("horsepower") is not None:
            ranked_labels.append(f"标注功率 {int(car['horsepower'])} 马力")

        matched_factors = list(dict.fromkeys(ranked_labels))[:3]
        public = {field: car[field] for field in PUBLIC_FIELDS if car.get(field) not in (None, "")}
        public.update(
            {
                "score": round(score, 1),
                "matched_factors": matched_factors,
                "reason": build_template_reason(str(car["model_name"]), matched_factors),
                "reason_source": "template",
            }
        )
        return public

    def recommend(self, payload: object) -> dict[str, object]:
        request = validate_request(payload)
        candidates, relaxed = self._filter(request)
        scored = [self._score(car, request) for car in candidates]

        def sort_key(item: dict[str, object]) -> tuple[object, ...]:
            original = self.by_id[str(item["car_id"])]
            completeness = float(original.get("data_completeness") or 0)
            heat = float(original.get("normalized_heat") or 0)
            return (-float(item["score"]), -completeness, -heat, str(item["model_name"]))

        scored.sort(key=sort_key)
        return {
            "total_candidates": len(candidates),
            "relaxed_conditions": relaxed,
            "recommendations": scored[: int(request["limit"])],
            "normalized_request": request,
        }

    def compare(self, car_ids: object) -> list[dict[str, object]]:
        if not isinstance(car_ids, list) or not 2 <= len(car_ids) <= 3:
            raise RecommendationError(
                "INVALID_COMPARE_COUNT", "请选择 2—3 款车型进行对比", "car_ids"
            )
        if len(set(car_ids)) != len(car_ids):
            raise RecommendationError("DUPLICATE_CAR", "对比车型不能重复", "car_ids")

        missing = [car_id for car_id in car_ids if str(car_id) not in self.by_id]
        if missing:
            raise RecommendationError(
                "CAR_NOT_FOUND", f"车型不存在：{missing[0]}", "car_ids", status_code=404
            )
        return [
            {
                field: self.by_id[str(car_id)][field]
                for field in PUBLIC_FIELDS
                if self.by_id[str(car_id)].get(field) not in (None, "")
            }
            for car_id in car_ids
        ]
