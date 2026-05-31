"""Smoke tests that run with zero external dependencies.

They force the regex fallback (no Presidio model, no Ollama, no Weave login) and
test the de-identify -> re-identify round-trip directly, without calling a live
model — so CI / a fresh clone can verify the core privacy guarantee offline.
"""

from __future__ import annotations

from closeai.config import Settings
from closeai.pipeline import CloseAIPipeline


def _pipeline() -> CloseAIPipeline:
    settings = Settings()
    settings.enable_llm_detector = False  # no Ollama in CI
    return CloseAIPipeline(settings=settings, init_tracing=False)


def test_email_is_surrogated_and_reversible():
    p = _pipeline()
    mask = p.deidentify("Email jane@acme.com please.")

    # Real email must not survive into what would leave the machine.
    assert "jane@acme.com" not in mask.masked_text
    # It's a reversible surrogate, so it lives in the entity map...
    assert "jane@acme.com" in mask.entity_map.values()

    # ...and a model that echoes the surrogate gets re-identified back.
    restored = p.reidentifier.reidentify(mask.masked_text, mask.entity_map)
    assert "jane@acme.com" in restored


def test_ssn_is_described_and_never_restored():
    p = _pipeline()
    mask = p.deidentify("My SSN is 123-45-6789.")

    # The real SSN is described, not sent, and never stored for reversal.
    assert "123-45-6789" not in mask.masked_text
    assert "123-45-6789" not in mask.entity_map.values()
    restored = p.reidentifier.reidentify(mask.masked_text, mask.entity_map)
    assert "123-45-6789" not in restored


def test_no_pii_passes_through_unchanged():
    p = _pipeline()
    text = "Two cups of flour and a pinch of salt."
    mask = p.deidentify(text)
    assert mask.masked_text == text
    assert mask.entity_map == {}
