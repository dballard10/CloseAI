"""Smoke tests that run with zero external dependencies.

They force the regex/echo fallbacks (no Presidio model, no Ollama, no API key,
no Weave login) so CI / a fresh clone can verify the core round-trip works.
"""

from __future__ import annotations

from closeai.config import Settings
from closeai.pipeline import CloseAIPipeline


def _pipeline() -> CloseAIPipeline:
    settings = Settings()
    settings.enable_llm_detector = False  # no Ollama in CI
    settings.provider = "echo"            # no API key in CI
    return CloseAIPipeline(settings=settings, init_tracing=False)


def test_email_and_ssn_are_caught_and_reversible():
    p = _pipeline()
    text = "Email jane@acme.com, SSN 123-45-6789."
    result = p.deidentify_and_query(text)

    # The sensitive strings must not survive into what leaves the machine.
    assert "jane@acme.com" not in result.masked_prompt
    assert "123-45-6789" not in result.masked_prompt

    # Email is reversible (MASK) -> restored in the final answer.
    assert "jane@acme.com" in result.reidentified_response
    # SSN is DROP -> never restored, never present anywhere outbound.
    assert "123-45-6789" not in result.reidentified_response


def test_no_pii_passes_through_unchanged():
    p = _pipeline()
    text = "Two cups of flour and a pinch of salt."
    result = p.deidentify(text)
    assert result.masked_text == text
    assert result.entity_map == {}


def test_entity_map_round_trips():
    p = _pipeline()
    mask = p.deidentify("Reach me at bob@corp.io.")
    assert mask.masked_text != mask.original_text
    restored = p.reidentifier.reidentify(mask.masked_text, mask.entity_map)
    assert restored == mask.original_text
