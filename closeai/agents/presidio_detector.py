"""Agent 1 — Presidio detector.

Fast, deterministic, recall-friendly detection of the *structured* PII: emails,
phone numbers, SSNs, credit cards, IBANs, plus names/locations/orgs via the
spaCy NER model that Presidio wraps.

If ``presidio-analyzer`` isn't installed (or its spaCy model is missing) we fall
back to a regex-only detector so the pipeline always runs in a demo. The regex
fallback covers the structured patterns; the contextual misses are exactly what
the LLM detector (agent 2) is there to catch.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..observability import op
from ..schemas import Span

# Minimal, deliberately greedy regexes used as both fallback and safety net.
_FALLBACK_PATTERNS: dict[str, re.Pattern] = {
    "PERSON": re.compile(
        r"\b(?:I(?:'m| am)|my name is|Patient|Ask|Contact|Email|Call)\s+"
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b"
    ),
    "EMAIL_ADDRESS": re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
    "PHONE_NUMBER": re.compile(r"(?:\+?\d{1,3}[\s.\-]?)?(?:\(?\d{3}\)?[\s.\-]?)\d{3}[\s.\-]?\d{4}"),
    "US_SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "CREDIT_CARD": re.compile(r"\b(?:\d[ \-]?){13,16}\b"),
    "IP_ADDRESS": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "URL": re.compile(r"https?://[^\s]+"),
    "AGE": re.compile(r"\b(?:age(?:d)?\s+)?(\d{1,3})\s*(?:years?\s*old|yo|y/o)\b", re.I),
}


class PresidioDetector:
    """Wraps Presidio's AnalyzerEngine, with a regex fallback."""

    def __init__(self, spacy_model: str = "en_core_web_lg", threshold: float = 0.35):
        self.threshold = threshold
        self._analyzer = None
        self._mode = "regex"
        try:
            import spacy
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider

            if not spacy.util.is_package(spacy_model) and not Path(spacy_model).exists():
                raise RuntimeError(
                    f"spaCy model '{spacy_model}' is not installed; "
                    "run `python -m spacy download en_core_web_lg` to enable NER."
                )
            provider = NlpEngineProvider(
                nlp_configuration={
                    "nlp_engine_name": "spacy",
                    "models": [{"lang_code": "en", "model_name": spacy_model}],
                }
            )
            self._analyzer = AnalyzerEngine(nlp_engine=provider.create_engine())
            self._mode = "presidio"
        except Exception as exc:  # pragma: no cover - depends on install
            print(
                f"[PresidioDetector] presidio/spaCy unavailable ({exc}); "
                "using regex fallback."
            )

    @property
    def mode(self) -> str:
        return self._mode

    @op
    def detect(self, text: str) -> list[Span]:
        if self._mode == "presidio":
            return self._detect_presidio(text) + self._detect_regex(text)
        return self._detect_regex(text)

    def _detect_presidio(self, text: str) -> list[Span]:
        results = self._analyzer.analyze(  # type: ignore[union-attr]
            text=text, language="en", score_threshold=self.threshold
        )
        spans: list[Span] = []
        for r in results:
            spans.append(
                Span(
                    start=r.start,
                    end=r.end,
                    entity_type=r.entity_type,
                    text=text[r.start : r.end],
                    score=float(r.score),
                    source="presidio",
                )
            )
        return spans

    def _detect_regex(self, text: str) -> list[Span]:
        spans: list[Span] = []
        for entity_type, pattern in _FALLBACK_PATTERNS.items():
            for m in pattern.finditer(text):
                start, end = (m.start(1), m.end(1)) if m.lastindex else (m.start(), m.end())
                spans.append(
                    Span(
                        start=start,
                        end=end,
                        entity_type=entity_type,
                        text=text[start:end],
                        score=0.9,
                        source="presidio",
                    )
                )
        return spans
