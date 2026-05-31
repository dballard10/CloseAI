"""Agent 5 — masker.

Applies the policy plan to the text and writes the entity map. It rewrites the
string right-to-left so earlier offsets stay valid as later spans change length.

The entity map (placeholder -> original) is the *only* artifact that can undo
the de-identification, and it never leaves the local process.
"""

from __future__ import annotations

from ..observability import op
from ..schemas import Action, EntityDecision, MaskResult


class Masker:
    @op
    def mask(self, text: str, decisions: list[EntityDecision]) -> MaskResult:
        entity_map: dict[str, str] = {}
        # Apply from the end so we never invalidate earlier character offsets.
        ordered = sorted(decisions, key=lambda d: d.span.start, reverse=True)
        out = text
        for d in ordered:
            span = d.span
            original = text[span.start : span.end]
            out = out[: span.start] + d.replacement + out[span.end :]
            if d.action == Action.MASK and d.placeholder:
                entity_map[d.placeholder] = original
        return MaskResult(
            original_text=text,
            masked_text=out,
            decisions=decisions,
            entity_map=entity_map,
        )
