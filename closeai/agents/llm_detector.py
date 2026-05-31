"""Agent 2 — local LLM detector (via Ollama).

Presidio is great at structured PII but blind to *contextual* identifiers:
"my manager at the Cambridge office", "the only female VP in our 12-person
startup", "the patient I admitted last Tuesday in the Boston ER". A small
instruction-tuned model running locally through Ollama reads the whole sentence
and flags these.

Crucially this never leaves the machine — that's the whole point of CloseAI, so
even the *detector* is local. The model returns spans of text; we map those
strings back to character offsets ourselves (LLMs can't be trusted to count
characters).

Degrades gracefully: if Ollama is unreachable we return no spans and let
Presidio carry the round. Detection is additive, so a missing detector only
costs recall, it never crashes the pipeline.
"""

from __future__ import annotations

import json
import re

from ..observability import log_llm_call, op
from ..schemas import Span

_SYSTEM_PROMPT = """You are a privacy detection agent. Your job is to find every \
piece of text that could identify a specific person, organization, or place \
when combined with other context — including INDIRECT and CONTEXTUAL clues that \
simple pattern matchers miss.

Examples of what to flag:
- names, emails, phones, addresses, IDs (obvious)
- job title + employer ("the CFO at Acme")
- unique relationships ("my manager at the Cambridge office")
- rare attributes that single someone out ("the only deaf engineer on the team")
- specific places/dates that narrow identity ("admitted last Tuesday in Boston")
- ages, locations, organizations

Bias HARD toward over-detection. A false positive costs a little usefulness; a \
missed identifier is a privacy leak. When unsure, flag it.

Respond with a JSON object of the form:
{"entities": [{"text": "<exact substring from the input>", "type": "<UPPER_SNAKE_CASE>", "reason": "<short why>"}]}
Use types like PERSON, ORGANIZATION, LOCATION, AGE, DATE_TIME, JOB_TITLE, \
CONTEXTUAL_IDENTIFIER. Each "text" MUST be an exact substring of the input. \
If nothing is sensitive, return {"entities": []}.
"""

# JSON schema passed to Ollama's structured-output `format` field. This forces
# the model to return {"entities": [...]} instead of a bare object/array, which
# is what made small local models inconsistent before.
_FORMAT_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "type": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["text", "type"],
            },
        }
    },
    "required": ["entities"],
}

# Preference order when auto-resolving an installed model. Earlier = better at
# instruction-following / JSON. We match by prefix so tags/sizes don't matter.
_MODEL_PREFERENCE = ("llama3", "qwen2.5", "qwen2", "mistral", "gemma", "phi", "llama2")


class LLMDetector:
    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "llama3.2",
        enabled: bool = True,
    ):
        self.host = host.rstrip("/")
        self.model = model
        self.enabled = enabled
        self._resolved_model: str | None = None

    @op
    def detect(self, text: str) -> list[Span]:
        if not self.enabled:
            return []
        model = self._resolve_model()
        if not model:
            return []
        raw = self._call_ollama(text, model)
        if not raw:
            return []
        items = self._parse_json(raw)
        return self._to_spans(text, items)

    def _resolve_model(self) -> str | None:
        """Pick a model that is actually installed in Ollama.

        Uses the configured model if present, otherwise falls back to the best
        available one by preference order, otherwise the first installed model.
        Result is cached so we only hit /api/tags once.
        """
        if self._resolved_model is not None:
            return self._resolved_model or None

        available = self._list_models()
        if available is None:  # Ollama unreachable
            self._resolved_model = ""
            return None
        if not available:
            print("[LLMDetector] No Ollama models installed; skipping LLM detection.")
            self._resolved_model = ""
            return None

        chosen = None
        if self.model in available:
            chosen = self.model
        else:
            # Allow "llama3.2" to match "llama3.2:latest" and vice versa.
            base = self.model.split(":")[0]
            for name in available:
                if name.split(":")[0] == base:
                    chosen = name
                    break
        if chosen is None:
            for pref in _MODEL_PREFERENCE:
                for name in available:
                    if name.startswith(pref):
                        chosen = name
                        break
                if chosen:
                    break
        if chosen is None:
            chosen = available[0]

        if chosen != self.model:
            print(
                f"[LLMDetector] configured model '{self.model}' not installed; "
                f"using '{chosen}' (installed: {', '.join(available)})."
            )
        self._resolved_model = chosen
        return chosen

    def _list_models(self) -> list[str] | None:
        try:
            import requests
        except Exception:  # pragma: no cover
            return None
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=10)
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
        except Exception as exc:  # pragma: no cover - Ollama down
            print(f"[LLMDetector] Ollama unreachable at {self.host} ({exc}); skipping.")
            return None

    def _call_ollama(self, text: str, model: str) -> str:
        try:
            import requests
        except Exception:  # pragma: no cover
            return ""
        try:
            resp = requests.post(
                f"{self.host}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": text},
                    ],
                    "stream": False,
                    "format": _FORMAT_SCHEMA,
                    "options": {"temperature": 0.0},
                },
                timeout=120,
            )
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "")
            log_llm_call(
                provider="ollama",
                model=model,
                stage="legacy.local_detector",
                system=_SYSTEM_PROMPT,
                user=text,
                response=content,
                json_mode=True,
                schema=_FORMAT_SCHEMA,
                endpoint=self.host,
            )
            return content
        except Exception as exc:  # pragma: no cover - network/Ollama down
            log_llm_call(
                provider="ollama",
                model=model,
                stage="legacy.local_detector",
                system=_SYSTEM_PROMPT,
                user=text,
                error=str(exc),
                json_mode=True,
                schema=_FORMAT_SCHEMA,
                endpoint=self.host,
            )
            print(f"[LLMDetector] Ollama call failed ({exc}); skipping LLM detection.")
            return ""

    @staticmethod
    def _parse_json(raw: str) -> list[dict]:
        raw = raw.strip()
        try:
            data = json.loads(raw)
        except Exception:
            match = re.search(r"[\[{].*[\]}]", raw, re.DOTALL)
            if not match:
                return []
            try:
                data = json.loads(match.group(0))
            except Exception:
                return []
        if isinstance(data, dict):
            for key in ("entities", "items", "results", "spans"):
                if isinstance(data.get(key), list):
                    return data[key]
            # A single entity object like {"text": ..., "type": ...}.
            if "text" in data:
                return [data]
            return []
        return data if isinstance(data, list) else []

    @staticmethod
    def _to_spans(text: str, items: list[dict]) -> list[Span]:
        spans: list[Span] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            fragment = (item.get("text") or "").strip()
            if not fragment:
                continue
            entity_type = (item.get("type") or "CONTEXTUAL_IDENTIFIER").upper().replace(" ", "_")
            reason = item.get("reason")
            # Map every occurrence of the fragment back to char offsets.
            for m in re.finditer(re.escape(fragment), text):
                spans.append(
                    Span(
                        start=m.start(),
                        end=m.end(),
                        entity_type=entity_type,
                        text=fragment,
                        score=0.6,
                        source="llm",
                        reason=reason,
                    )
                )
        return spans
