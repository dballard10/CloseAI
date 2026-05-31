"""Agent 3 — reconciler.

Takes the union of the Presidio and LLM detector spans. The asymmetry of the
problem drives the design: a false positive costs a little utility, a false
negative is a leak. So we deliberately bias toward over-detection and merge
rather than filter.

When two spans overlap we merge them into the widest covering span and pick the
more specific / higher-confidence label, recording both sources.
"""

from __future__ import annotations

from ..observability import op
from ..schemas import Span

# Lower rank == more specific / more sensitive, wins label conflicts on merge.
_TYPE_PRIORITY = {
    "US_SSN": 0,
    "CREDIT_CARD": 0,
    "US_BANK_NUMBER": 0,
    "CRYPTO": 0,
    "EMAIL_ADDRESS": 1,
    "PHONE_NUMBER": 1,
    "IP_ADDRESS": 1,
    "US_PASSPORT": 1,
    "US_DRIVER_LICENSE": 1,
    "PERSON": 2,
    "ORGANIZATION": 3,
    "ORG": 3,
    "LOCATION": 4,
    "GPE": 4,
    "AGE": 5,
    "DATE_TIME": 6,
    "CONTEXTUAL_IDENTIFIER": 7,
}


class Reconciler:
    @op
    def reconcile(
        self, text: str, presidio_spans: list[Span], llm_spans: list[Span]
    ) -> list[Span]:
        spans = sorted(
            [*presidio_spans, *llm_spans], key=lambda s: (s.start, -(s.end - s.start))
        )
        merged: list[Span] = []
        for span in spans:
            if merged and span.overlaps(merged[-1]):
                merged[-1] = self._merge(text, merged[-1], span)
            else:
                merged.append(span)
        return merged

    @staticmethod
    def _merge(text: str, a: Span, b: Span) -> Span:
        start = min(a.start, b.start)
        end = max(a.end, b.end)
        # Choose label by specificity, breaking ties by score.
        rank_a = (_TYPE_PRIORITY.get(a.entity_type, 50), -a.score)
        rank_b = (_TYPE_PRIORITY.get(b.entity_type, 50), -b.score)
        winner = a if rank_a <= rank_b else b
        sources = sorted({a.source, b.source})
        return Span(
            start=start,
            end=end,
            entity_type=winner.entity_type,
            text=text[start:end],
            score=max(a.score, b.score),
            source="+".join(sources) if len(sources) > 1 else winner.source,
            reason=a.reason or b.reason,
        )
