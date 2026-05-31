"""Re-identifier — runs after the closed model responds.

The closed model only ever saw placeholders like ``[PERSON_1]``. Whatever it
writes back, we swap those tokens for the real values from the entity map so the
end user sees a natural, fully-restored answer.

Only MASK entities are reversible by design: GENERALIZE and DROP intentionally
have no entry in the map, so they stay coarse/removed forever.
"""

from __future__ import annotations

from ..observability import op


class Reidentifier:
    @op
    def reidentify(self, response: str, entity_map: dict[str, str]) -> str:
        out = response
        # Replace longer placeholders first to avoid partial-token collisions
        # (e.g. [PERSON_1] vs [PERSON_11]).
        for placeholder in sorted(entity_map, key=len, reverse=True):
            out = out.replace(placeholder, entity_map[placeholder])
        return out
