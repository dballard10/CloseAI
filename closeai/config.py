"""Central configuration. Everything is overridable via environment variables.

The policy map is the privacy-vs-utility tuning knob: change one line to make
the system more aggressive (more DROP/MASK) or more useful (more KEEP).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .schemas import Action

# Default per-entity policy. Bias: keep the prompt natural English. Identifiers
# become realistic surrogates (reversible); quantitative facts become natural
# descriptions; the most dangerous secrets are dropped.
DEFAULT_POLICY: dict[str, Action] = {
    # Direct identifiers -> realistic fake of the same type (restored later).
    "PERSON": Action.SURROGATE,
    "EMAIL_ADDRESS": Action.SURROGATE,
    "PHONE_NUMBER": Action.SURROGATE,
    "IP_ADDRESS": Action.SURROGATE,
    "URL": Action.SURROGATE,
    "IBAN_CODE": Action.SURROGATE,
    "MEDICAL_LICENSE": Action.SURROGATE,
    "US_DRIVER_LICENSE": Action.SURROGATE,
    "US_PASSPORT": Action.SURROGATE,
    "ORGANIZATION": Action.SURROGATE,
    "ORG": Action.SURROGATE,
    # Places are names too -> swap for a believable fake city (reads naturally).
    "LOCATION": Action.SURROGATE,
    "GPE": Action.SURROGATE,
    # Hyper-sensitive secrets -> describe (never sent, even as a fake), but keep
    # the sentence natural: "my SSN is a confidential number".
    "US_SSN": Action.DESCRIBE,
    "CREDIT_CARD": Action.DESCRIBE,
    "CRYPTO": Action.DESCRIBE,
    "US_BANK_NUMBER": Action.DESCRIBE,
    # Quasi-identifiers / metrics -> natural-language description.
    "AGE": Action.DESCRIBE,
    "DATE_TIME": Action.DESCRIBE,
    "NRP": Action.DESCRIBE,  # nationality / religious / political group
    # Contextual phrases the LLM detector flags -> describe rather than name-swap
    # (a fake name mid-phrase reads worse than a neutral description).
    "CONTEXTUAL_IDENTIFIER": Action.DESCRIBE,
}

# Action used when an entity type isn't in the map above. We over-protect with a
# reversible surrogate so nothing real ever leaks.
FALLBACK_ACTION = Action.SURROGATE


@dataclass
class Settings:
    weave_project: str = field(default_factory=lambda: os.getenv("WEAVE_PROJECT", "closeai"))

    # Local LLM detector (Ollama).
    ollama_host: str = field(default_factory=lambda: os.getenv("OLLAMA_HOST", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3.2"))
    enable_llm_detector: bool = field(
        default_factory=lambda: os.getenv("ENABLE_LLM_DETECTOR", "1") not in ("0", "false", "False")
    )

    # spaCy model used by Presidio.
    spacy_model: str = field(default_factory=lambda: os.getenv("SPACY_MODEL", "en_core_web_lg"))

    # Closed-source model — a local Ollama model (auto-resolves if not installed).
    model: str = field(default_factory=lambda: os.getenv("CLOSEAI_MODEL", "llama3.2"))

    # Detection threshold for Presidio (0-1). Lower => more recall, more FPs.
    presidio_threshold: float = field(
        default_factory=lambda: float(os.getenv("PRESIDIO_THRESHOLD", "0.35"))
    )

    policy: dict[str, Action] = field(default_factory=lambda: dict(DEFAULT_POLICY))
    fallback_action: Action = FALLBACK_ACTION
