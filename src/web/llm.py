from __future__ import annotations

import json
import os
from pathlib import Path

import requests


class LLMReasonWriter:
    """DeepSeek / OpenAI 兼容接口适配；失败时保留模板原因。"""

    def __init__(self) -> None:
        self.enabled = os.getenv("LLM_ENABLED", "false").lower() == "true"
        self.provider = os.getenv("LLM_PROVIDER", "deepseek").strip().lower()
        if self.provider == "deepseek":
            self.api_base = os.getenv(
                "DEEPSEEK_API_BASE", "https://api.deepseek.com"
            ).rstrip("/")
            self.api_key = self._secret("DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY_FILE")
            self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
        elif self.provider == "openai_compatible":
            self.api_base = os.getenv("LLM_API_BASE", "").rstrip("/")
            self.api_key = self._secret("LLM_API_KEY", "LLM_API_KEY_FILE")
            self.model = os.getenv("LLM_MODEL", "")
        else:
            self.api_base = ""
            self.api_key = ""
            self.model = ""
        self.timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "8"))

    @staticmethod
    def _secret(value_name: str, file_name: str) -> str:
        value = os.getenv(value_name, "").strip()
        if value:
            return value
        secret_file = os.getenv(file_name, "").strip()
        if not secret_file:
            return ""
        try:
            return Path(secret_file).expanduser().read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    @property
    def display_name(self) -> str:
        return "DeepSeek" if self.provider == "deepseek" else "兼容模型"

    @property
    def available(self) -> bool:
        return bool(self.enabled and self.api_base and self.api_key and self.model)

    def rewrite(self, recommendation: dict[str, object]) -> str:
        if not self.available:
            raise RuntimeError("LLM 未启用或配置不完整")
        facts = {
            "model_name": recommendation["model_name"],
            "matched_factors": recommendation["matched_factors"],
            "score": recommendation["score"],
        }
        payload: dict[str, object] = {
            "model": self.model,
            "temperature": 0.2,
            "max_tokens": 100,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你只负责把给定 JSON 中的推荐依据改写成一句中文说明。"
                        "不得新增车辆参数、不得更换车型、不得声称实时价格。"
                    ),
                },
                {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
            ],
        }
        if self.provider == "deepseek":
            # 短句改写不需要推理链；DeepSeek V4 默认开启思考，需显式关闭。
            payload["thinking"] = {"type": "disabled"}

        response = requests.post(
            f"{self.api_base}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
        if not content or len(content) > 300:
            raise ValueError("LLM 返回内容为空或过长")
        return content
