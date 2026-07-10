from __future__ import annotations

from src.web.app import create_app


REQUEST = {
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


def test_health_recommend_and_compare(dataset_file):
    app = create_app({"TESTING": True, "DATASET_PATH": str(dataset_file)})
    client = app.test_client()

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json["dataset_loaded"] is True
    assert health.json["car_count"] == 5
    assert health.json["llm_provider"] == "deepseek"
    assert health.json["llm_model"] == "deepseek-v4-flash"

    response = client.post("/api/recommend", json=REQUEST)
    assert response.status_code == 200
    assert response.json["request_id"].startswith("local-")
    assert 3 <= len(response.json["recommendations"]) <= 5

    ids = [item["car_id"] for item in response.json["recommendations"][:2]]
    compared = client.post("/api/compare", json={"car_ids": ids})
    assert compared.status_code == 200
    assert [car["car_id"] for car in compared.json["cars"]] == ids


def test_llm_failure_keeps_template_result(dataset_file, monkeypatch):
    app = create_app({"TESTING": True, "DATASET_PATH": str(dataset_file)})
    writer = app.extensions["llm_writer"]
    monkeypatch.setattr(writer, "rewrite", lambda _item: (_ for _ in ()).throw(RuntimeError()))

    response = app.test_client().post("/api/recommend", json={**REQUEST, "use_llm": True})
    assert response.status_code == 200
    assert all(item["reason_source"] == "template" for item in response.json["recommendations"])
    assert all(item["reason"] for item in response.json["recommendations"])
    assert all("reason_provider" not in item for item in response.json["recommendations"])


def test_deepseek_success_is_identified(dataset_file, monkeypatch):
    app = create_app({"TESTING": True, "DATASET_PATH": str(dataset_file)})
    writer = app.extensions["llm_writer"]
    monkeypatch.setattr(writer, "rewrite", lambda _item: "DeepSeek 生成的推荐说明。")

    response = app.test_client().post("/api/recommend", json={**REQUEST, "use_llm": True})
    assert response.status_code == 200
    assert all(item["reason_source"] == "llm" for item in response.json["recommendations"])
    assert all(item["reason_provider"] == "deepseek" for item in response.json["recommendations"])
    assert all(item["reason"] == "DeepSeek 生成的推荐说明。" for item in response.json["recommendations"])


def test_invalid_api_requests_return_contract_errors(dataset_file):
    app = create_app({"TESTING": True, "DATASET_PATH": str(dataset_file)})
    client = app.test_client()

    invalid = client.post("/api/recommend", json={**REQUEST, "budget_min_wan": 25})
    assert invalid.status_code == 400
    assert invalid.json["error"]["code"] == "INVALID_BUDGET"

    missing = client.post("/api/compare", json={"car_ids": ["car_0", "missing"]})
    assert missing.status_code == 404
    assert missing.json["error"]["code"] == "CAR_NOT_FOUND"
