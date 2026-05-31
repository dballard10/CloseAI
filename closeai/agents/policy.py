"""Agent 4 — policy agent.

This is where the privacy-vs-utility tradeoff actually lives. Detection just
finds candidates; the policy decides, *per entity*, whether to:

  - MASK       reversible placeholder, restored after the model answers
  - GENERALIZE coarsen it (exact age -> range, city -> region, date -> month)
  - DROP       delete it entirely (hyper-sensitive secrets)
  - KEEP       leave it (low risk, high utility)

Decisions are driven by a config map (see ``config.DEFAULT_POLICY``) so you can
retune the whole system's aggressiveness without touching code. Generalization
logic lives here too.
"""

from __future__ import annotations

import re

from ..observability import op
from ..schemas import Action, EntityDecision, Span

# Coarse US-region grouping for a few well-known cities. In a real system this
# would be a gazetteer; for the demo a small map shows the idea convincingly.
_CITY_TO_REGION = {
    "cambridge": "New England",
    "boston": "New England",
    "new york": "the Northeast US",
    "brooklyn": "the Northeast US",
    "san francisco": "the Bay Area",
    "oakland": "the Bay Area",
    "palo alto": "the Bay Area",
    "seattle": "the Pacific Northwest",
    "austin": "the South Central US",
    "chicago": "the Midwest US",
    "los angeles": "Southern California",
    "london": "the UK",
    "paris": "France",
}

_AGE_RE = re.compile(r"(\d{1,3})")
_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")


class PolicyAgent:
    def __init__(self, policy: dict[str, Action], fallback: Action):
        self.policy = policy
        self.fallback = fallback

    @op
    def decide(self, spans: list[Span]) -> list[EntityDecision]:
        # Stable per-type counters so placeholders read [PERSON_1], [PERSON_2]...
        counters: dict[str, int] = {}
        decisions: list[EntityDecision] = []
        for span in spans:
            action = self.policy.get(span.entity_type, self.fallback)
            replacement, placeholder = self._render(span, action, counters)
            decisions.append(
                EntityDecision(
                    span=span,
                    action=action,
                    replacement=replacement,
                    placeholder=placeholder,
                )
            )
        return decisions

    def _render(
        self, span: Span, action: Action, counters: dict[str, int]
    ) -> tuple[str, str | None]:
        if action == Action.KEEP:
            return span.text, None
        if action == Action.DROP:
            return "", None
        if action == Action.GENERALIZE:
            return self._generalize(span), None
        # MASK -> reversible placeholder.
        counters[span.entity_type] = counters.get(span.entity_type, 0) + 1
        placeholder = f"[{span.entity_type}_{counters[span.entity_type]}]"
        return placeholder, placeholder

    def _generalize(self, span: Span) -> str:
        t = span.entity_type
        raw = span.text.strip()
        if t == "AGE":
            m = _AGE_RE.search(raw)
            if m:
                age = int(m.group(1))
                bucket = (age // 10) * 10
                return f"in their {bucket}s"
            return "an undisclosed age"
        if t in ("LOCATION", "GPE"):
            region = _CITY_TO_REGION.get(raw.lower())
            return region if region else "a redacted location"
        if t == "DATE_TIME":
            m = _YEAR_RE.search(raw)
            if m:
                return f"around {m.group(1)}"
            return "a redacted date"
        if t == "NRP":
            return "a demographic group"
        # Unknown generalizable type -> safe coarse label.
        return f"a redacted {t.lower().replace('_', ' ')}"
