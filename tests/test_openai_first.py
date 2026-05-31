from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient

from closeai.config import Settings
from closeai.llm_client import ClosedModelClient
from closeai.observability import sanitize_for_trace
from closeai.pipeline import CloseAIPipeline
from closeai.schemas import MaskResult


RAW_PII = "Ask Jane Doe at jane@example.com or 555-123-4567. SSN 123-45-6789."
MASKED_PII = "Ask [PERSON_1] at [EMAIL_ADDRESS_1] or [PHONE_NUMBER_1]. SSN ."


def test_openai_client_receives_only_deidentified_prompt(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    captured = {}

    class FakeCompletions:
        def create(self, model, messages):
            captured["model"] = model
            captured["messages"] = messages
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="Hello [PERSON_1].")
                    )
                ]
            )

    class FakeOpenAI:
        def __init__(self, *args, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    result = ClosedModelClient("openai", "gpt-test").complete(
        MASKED_PII,
        system="Answer carefully.",
    )

    user_message = captured["messages"][-1]["content"]
    assert captured["model"] == "gpt-test"
    assert result == "Hello [PERSON_1]."
    assert user_message == MASKED_PII
    for raw in ("Jane Doe", "jane@example.com", "555-123-4567", "123-45-6789"):
        assert raw not in user_message


def test_pipeline_passes_masked_prompt_to_model_client(monkeypatch):
    settings = Settings()
    settings.enable_llm_detector = False
    settings.provider = "openai"
    pipeline = CloseAIPipeline(settings=settings, init_tracing=False)
    mask_result = MaskResult(
        original_text=RAW_PII,
        masked_text=MASKED_PII,
        entity_map={"[PERSON_1]": "Jane Doe"},
    )
    captured = {}

    monkeypatch.setattr(pipeline, "deidentify", lambda text: mask_result)

    def fake_complete(self, prompt, system=None):
        captured["prompt"] = prompt
        return "Hello [PERSON_1]."

    monkeypatch.setattr(ClosedModelClient, "complete", fake_complete)

    result = pipeline.deidentify_and_query(RAW_PII, provider="openai")

    assert captured["prompt"] == MASKED_PII
    assert result.reidentified_response == "Hello Jane Doe."
    for raw in ("Jane Doe", "jane@example.com", "555-123-4567", "123-45-6789"):
        assert raw not in captured["prompt"]


def test_trace_sanitizer_removes_local_pii_by_default(monkeypatch):
    monkeypatch.delenv("CLOSEAI_TRACE_RAW", raising=False)
    payload = {
        "original_prompt": RAW_PII,
        "masked_prompt": MASKED_PII,
        "mask_result": {
            "original_text": RAW_PII,
            "masked_text": MASKED_PII,
            "entity_map": {"[PERSON_1]": "Jane Doe"},
            "decisions": [{"span": {"text": "Jane Doe"}, "replacement": "[PERSON_1]"}],
        },
        "reidentified_response": "Hello Jane Doe.",
    }

    sanitized = sanitize_for_trace(payload)

    assert sanitized["masked_prompt"] == MASKED_PII
    assert sanitized["mask_result"]["masked_text"] == MASKED_PII
    for raw in ("Jane Doe", "jane@example.com", "555-123-4567", "123-45-6789"):
        assert raw not in str(sanitized)


def _client(monkeypatch) -> TestClient:
    monkeypatch.setenv("ENABLE_LLM_DETECTOR", "0")
    monkeypatch.setenv("WEAVE_DISABLED", "true")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    server = importlib.import_module("app.server")
    server._pipeline.llm_detector.enabled = False
    server._consult_pipeline.use_llm = False
    server._approval_sessions.clear()
    return TestClient(server.app)


def test_query_returns_structured_error_when_openai_key_missing(monkeypatch):
    client = _client(monkeypatch)

    resp = client.post("/api/query", json={"text": RAW_PII, "provider": "openai"})
    body = resp.json()

    assert resp.status_code == 400
    assert body["ok"] is False
    assert body["error"]["provider"] == "openai"
    assert "OPENAI_API_KEY" in body["error"]["message"]
    assert "Jane Doe" not in body["masked_prompt"]
    assert "jane@example.com" not in body["masked_prompt"]
    assert body["mask_result"]["masked_text"] == body["masked_prompt"]


def test_query_provider_override_echo_still_works(monkeypatch):
    client = _client(monkeypatch)

    resp = client.post("/api/query", json={"text": RAW_PII, "provider": "echo"})
    body = resp.json()

    assert resp.status_code == 200
    assert "echo provider" in body["raw_model_response"]
    assert "Jane Doe" not in body["masked_prompt"]
    assert "jane@example.com" not in body["masked_prompt"]
    assert "123-45-6789" not in body["masked_prompt"]


def test_classify_returns_reviewable_prompt_without_model_call(monkeypatch):
    client = _client(monkeypatch)

    resp = client.post(
        "/api/classify",
        json={
            "text": "Sarah Klein at Acme Robotics in Boston requested medical leave after a panic disorder diagnosis.",
            "mode": "hr",
        },
    )
    body = resp.json()

    assert resp.status_code == 200
    assert body["session_id"]
    assert "classified_prompt" in body
    assert "Sarah Klein" not in body["classified_prompt"]
    assert "checker_result" in body
    assert "utility_result" in body


def test_approve_and_query_sends_only_classified_prompt(monkeypatch):
    client = _client(monkeypatch)

    classify_resp = client.post(
        "/api/classify",
        json={
            "text": "My landlord Mark Benson at 45 Winter Street in Cambridge is keeping my security deposit.",
            "mode": "legal",
        },
    )
    classified = classify_resp.json()

    approve_resp = client.post(
        "/api/approve-and-query",
        json={
            "session_id": classified["session_id"],
            "provider": "echo",
        },
    )
    body = approve_resp.json()

    assert approve_resp.status_code == 200
    assert "echo provider" in body["model_response"]
    assert "Mark Benson" not in body["classified_prompt"]
    assert "45 Winter Street" not in body["classified_prompt"]
    assert "Mark Benson" not in body["model_response"]
    assert "45 Winter Street" not in body["model_response"]
