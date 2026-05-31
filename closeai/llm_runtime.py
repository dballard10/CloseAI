"""LLM clients for the ClosedAI privacy-gate pipeline.

Trusted steps use a local Ollama model. The external consultant can use W&B
Inference, but it only ever receives sanitized text after the privacy gate.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import requests


JSON_OBJECT_SCHEMA = {
    "type": "object",
    "additionalProperties": True,
}


class LocalLLM:
    def __init__(
        self,
        host: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        self.host = (host or os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
        self.model = model or os.getenv("CLOSEDAI_LOCAL_MODEL") or os.getenv("OLLAMA_MODEL", "llama3.2")
        self.timeout = timeout or int(os.getenv("CLOSEDAI_LOCAL_TIMEOUT", "180"))
        self._resolved_model: str | None = None

    def available(self) -> bool:
        return self.resolve_model() is not None

    def resolve_model(self) -> str | None:
        if self._resolved_model is not None:
            return self._resolved_model or None
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=5)
            response.raise_for_status()
            models = [item["name"] for item in response.json().get("models", [])]
        except Exception:
            self._resolved_model = ""
            return None

        if not models:
            self._resolved_model = ""
            return None

        chosen = self._match_model(models, self.model)
        if chosen is None:
            for preferred in ("llama3.2", "llama3", "granite", "gemma3", "qwen2.5", "mistral"):
                chosen = self._match_model(models, preferred)
                if chosen:
                    break
        self._resolved_model = chosen or models[0]
        return self._resolved_model

    @staticmethod
    def _match_model(models: list[str], requested: str) -> str | None:
        if requested in models:
            return requested
        base = requested.split(":")[0]
        return next((model for model in models if model.split(":")[0] == base), None)

    def chat_json(self, system: str, user: str, schema: dict[str, Any] | None = None) -> dict[str, Any] | None:
        raw = self.chat(system, user, schema=schema or JSON_OBJECT_SCHEMA)
        if raw is None:
            return None
        return parse_json_object(raw)

    def chat(self, system: str, user: str, schema: dict[str, Any] | None = None) -> str | None:
        model = self.resolve_model()
        if not model:
            return None
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": 0.0},
        }
        if schema is not None:
            payload["format"] = schema
        try:
            response = requests.post(f"{self.host}/api/chat", json=payload, timeout=self.timeout)
            response.raise_for_status()
            content = response.json().get("message", {}).get("content", "")
            return strip_thinking(content)
        except Exception:
            return None


class WANDbInferenceClient:
    def __init__(self):
        self.base_url = os.getenv("WANDB_INFERENCE_BASE_URL", "https://api.inference.wandb.ai/v1")
        self.api_key = os.getenv("WANDB_API_KEY")
        self.model = os.getenv("CLOSEDAI_EXTERNAL_MODEL", "meta-llama/Llama-3.1-8B-Instruct")

    def available(self) -> bool:
        return bool(self.api_key)

    def chat_json(self, system: str, user: str) -> dict[str, Any] | None:
        if not self.api_key:
            return None
        try:
            from openai import OpenAI

            client = OpenAI(base_url=self.base_url, api_key=self.api_key)
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or ""
            return parse_json_object(content)
        except Exception:
            return None


def parse_json_object(raw: str) -> dict[str, Any] | None:
    text = strip_thinking(raw).strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except Exception:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def strip_thinking(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
