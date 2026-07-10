from __future__ import annotations

from src.web.llm import LLMReasonWriter


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": "这是一条 DeepSeek 推荐说明。"}}]}


def test_deepseek_defaults_and_request(monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-key")
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr("src.web.llm.requests.post", fake_post)
    writer = LLMReasonWriter()
    reason = writer.rewrite(
        {"model_name": "车型A", "matched_factors": ["价格符合预算"], "score": 90}
    )

    assert writer.available is True
    assert writer.provider == "deepseek"
    assert writer.model == "deepseek-v4-flash"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["json"]["thinking"] == {"type": "disabled"}
    assert captured["json"]["stream"] is False
    assert captured["headers"]["Authorization"] == "Bearer test-only-key"
    assert reason == "这是一条 DeepSeek 推荐说明。"


def test_deepseek_key_can_be_read_from_private_file(monkeypatch, tmp_path):
    key_file = tmp_path / "deepseek-key"
    key_file.write_text("file-key\n", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY_FILE", str(key_file))

    writer = LLMReasonWriter()
    assert writer.api_key == "file-key"
