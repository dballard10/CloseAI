"""Agent 4 — policy agent.

This is where the privacy-vs-utility tradeoff actually lives. Detection just
finds candidates; the policy decides, *per entity*, how to rewrite it so the
outgoing prompt stays **natural English** while leaking nothing:

  - SURROGATE  swap in a realistic fake of the same type (Jane Doe -> Maria
               Lopez, an email -> a fake email). Reversible: restored after the
               model answers.
  - DESCRIBE   turn a quantitative/identifying fact into a natural-language
               description (37 -> "in their late 30s", a city -> "a city in New
               England"). Irreversible.
  - DROP       delete entirely (hyper-sensitive and useless to the model).
  - KEEP       leave it (low risk, high utility).

Decisions are driven by a config map (see ``config.DEFAULT_POLICY``). The
generalisation/description logic and the surrogate generator both live behind
this agent.
"""

from __future__ import annotations

import re

from ..observability import op
from ..schemas import Action, EntityDecision, Span
from .surrogate import SurrogateGenerator

# Coarse US-region grouping for a few well-known cities, used by DESCRIBE.
_CITY_TO_REGION = {
    "cambridge": "New England", "boston": "New England",
    "new york": "the Northeast US", "brooklyn": "the Northeast US",
    "san francisco": "the Bay Area", "oakland": "the Bay Area",
    "palo alto": "the Bay Area", "seattle": "the Pacific Northwest",
    "austin": "the South Central US", "chicago": "the Midwest US",
    "los angeles": "Southern California", "london": "the UK", "paris": "France",
}

_AGE_RE = re.compile(r"(\d{1,3})")
_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
_NUM_RE = re.compile(r"\d[\d,\.]*")


class PolicyAgent:
    def __init__(self, policy: dict[str, Action], fallback: Action, seed: int | None = None):
        self.policy = policy
        self.fallback = fallback
        self.surrogates = SurrogateGenerator(seed=seed)

    @op
    def decide(self, spans: list[Span]) -> list[EntityDecision]:
        decisions: list[EntityDecision] = []
        for span in spans:
            action = self.policy.get(span.entity_type, self.fallback)
            replacement, surrogate = self._render(span, action)
            decisions.append(
                EntityDecision(
                    span=span,
                    action=action,
                    replacement=replacement,
                    surrogate=surrogate,
                )
            )
        return decisions

    def _render(self, span: Span, action: Action) -> tuple[str, str | None]:
        if action == Action.KEEP:
            return span.text, None
        if action == Action.DROP:
            return "", None
        if action == Action.DESCRIBE:
            return self._describe(span), None
        # SURROGATE -> realistic fake, reversible.
        fake = self.surrogates.for_entity(span.entity_type, span.text)
        return fake, fake

    def _describe(self, span: Span) -> str:
        t = span.entity_type
        raw = span.text.strip()
        if t == "AGE":
            m = _AGE_RE.search(raw)
            if m:
                return self._describe_age(int(m.group(1)))
            return "an undisclosed age"
        if t in ("LOCATION", "GPE"):
            region = _CITY_TO_REGION.get(raw.lower())
            return f"a city in {region}" if region else "an undisclosed location"
        if t == "DATE_TIME":
            return self._describe_date(raw)
        if t == "NRP":
            return "a demographic group"
        if t in ("US_SSN", "CREDIT_CARD", "US_BANK_NUMBER", "CRYPTO"):
            return "a confidential number"
        # Generic numeric "metric" -> a rough magnitude description.
        if _NUM_RE.search(raw):
            return self._describe_number(raw)
        return f"an undisclosed {t.lower().replace('_', ' ')}"

    @staticmethod
    def _describe_age(age: int) -> str:
        if age < 13:
            return "a child"
        if age < 20:
            return "a teenager"
        decade = (age // 10) * 10
        within = age % 10
        band = "early" if within <= 3 else "mid" if within <= 6 else "late"
        return f"in their {band} {decade}s"

    @staticmethod
    def _describe_date(raw: str) -> str:
        m = _YEAR_RE.search(raw)
        if m:
            return f"around {m.group(1)}"
        low = raw.lower()
        if any(w in low for w in ("today", "yesterday", "tuesday", "monday",
                                  "wednesday", "thursday", "friday", "week")):
            return "recently"
        if "month" in low:
            return "in recent months"
        return "at an undisclosed time"

    @staticmethod
    def _describe_number(raw: str) -> str:
        digits = re.sub(r"[^\d]", "", raw)
        if not digits:
            return "an undisclosed amount"
        n = len(digits.lstrip("0")) or 1
        scale = {
            1: "a single-digit figure", 2: "a two-digit figure",
            3: "a figure in the hundreds", 4: "a figure in the thousands",
            5: "a five-figure amount", 6: "a six-figure amount",
        }
        return scale.get(n, "a large figure")
