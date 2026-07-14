from __future__ import annotations

import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
import requests

from src.recommender import RecommendationEngine, RecommendationError
from src.recommender.loader import load_cars
from src.web.analysis_loader import load_analysis_overview
from src.web.llm import LLMReasonWriter


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = PROJECT_ROOT / "data/processed/cars.csv"
DEFAULT_ANALYSIS_DIR = PROJECT_ROOT / "data/processed/analysis"


def create_app(
    config: dict[str, object] | None = None,
    *,
    analysis_dir: str | Path | None = None,
) -> Flask:
    load_dotenv(PROJECT_ROOT / ".env")
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_mapping(
        DATASET_PATH=os.getenv("CAR_DATASET_PATH", str(DEFAULT_DATASET)),
        ANALYSIS_DIR=os.getenv("CAR_ANALYSIS_DIR", str(DEFAULT_ANALYSIS_DIR)),
        JSON_AS_ASCII=False,
    )
    if config:
        app.config.update(config)
    if analysis_dir is not None:
        app.config["ANALYSIS_DIR"] = str(analysis_dir)

    engine: RecommendationEngine | None = None
    dataset_error: str | None = None
    try:
        engine = RecommendationEngine(load_cars(Path(str(app.config["DATASET_PATH"]))))
    except (FileNotFoundError, OSError, ValueError) as exc:
        dataset_error = str(exc)

    llm = LLMReasonWriter()
    app.extensions["recommendation_engine"] = engine
    app.extensions["dataset_error"] = dataset_error
    app.extensions["llm_writer"] = llm

    def require_engine() -> RecommendationEngine:
        current = app.extensions.get("recommendation_engine")
        if current is None:
            raise RecommendationError(
                "DATASET_UNAVAILABLE",
                str(app.extensions.get("dataset_error") or "标准车型数据未加载"),
                status_code=503,
            )
        return current

    @app.get("/")
    def index():
        context = engine.catalog_context() if engine else {
            "car_count": 0,
            "brands": [],
            "body_types": [],
            "energy_types": [],
            "energy_distribution": [],
            "body_distribution": [],
        }
        return render_template(
            "index.html",
            catalog=context,
            dataset_error=dataset_error,
            llm_enabled=llm.available,
            llm_label=llm.display_name,
            llm_model=llm.model,
        )

    @app.get("/api/health")
    def health():
        current = app.extensions.get("recommendation_engine")
        return jsonify(
            {
                "status": "ok" if current else "degraded",
                "dataset_loaded": current is not None,
                "car_count": len(current.cars) if current else 0,
                "llm_enabled": llm.available,
                "llm_provider": llm.provider,
                "llm_model": llm.model,
            }
        )

    @app.get("/api/analysis/overview")
    def analysis_overview():
        raw_limit = request.args.get("limit", "187")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise RecommendationError(
                "INVALID_LIMIT", "limit 必须是 1 到 500 之间的整数", field="limit"
            )
        if not 1 <= limit <= 500:
            raise RecommendationError(
                "INVALID_LIMIT", "limit 必须是 1 到 500 之间的整数", field="limit"
            )
        return jsonify(
            load_analysis_overview(Path(str(app.config["ANALYSIS_DIR"])), limit=limit)
        )

    @app.post("/api/recommend")
    def recommend():
        result = require_engine().recommend(request.get_json(silent=True))
        normalized = result.pop("normalized_request")
        if normalized["use_llm"]:
            for item in result["recommendations"]:
                try:
                    item["reason"] = llm.rewrite(item)
                    item["reason_source"] = "llm"
                    item["reason_provider"] = llm.provider
                except (requests.RequestException, RuntimeError, ValueError, KeyError, TypeError):
                    item["reason_source"] = "template"
                    item.pop("reason_provider", None)
        result["request_id"] = f"local-{uuid.uuid4().hex[:8]}"
        return jsonify(result)

    @app.post("/api/compare")
    def compare():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise RecommendationError("INVALID_JSON", "请求体必须是 JSON 对象")
        cars = require_engine().compare(payload.get("car_ids"))
        return jsonify({"cars": cars})

    @app.errorhandler(RecommendationError)
    def handle_recommendation_error(error: RecommendationError):
        return jsonify(error.to_dict()), error.status_code

    @app.errorhandler(404)
    def handle_not_found(_error):
        return jsonify({"error": {"code": "NOT_FOUND", "message": "接口不存在"}}), 404

    @app.errorhandler(Exception)
    def handle_unexpected(error: Exception):
        app.logger.exception("未处理异常", exc_info=error)
        return jsonify(
            {"error": {"code": "INTERNAL_ERROR", "message": "服务暂时不可用，请稍后重试"}}
        ), 500

    return app


if __name__ == "__main__":
    create_app().run(
        host=os.getenv("APP_HOST", "127.0.0.1"),
        port=int(os.getenv("APP_PORT", "5000")),
        debug=False,
    )
