"""Central configuration. Everything is overridable via environment variables.

The policy map is the privacy-vs-utility tuning knob: change one line to make
the system more aggressive (more DROP/MASK) or more useful (more KEEP).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .schemas import Action

# Default per-entity policy. Bias: anything that uniquely identifies a person
# is masked or dropped; coarse attributes are generalized; low-risk stays.
DEFAULT_POLICY: dict[str, Action] = {
    # Direct identifiers -> reversible mask (restored after the model answers).
    "PERSON": Action.MASK,
    "EMAIL_ADDRESS": Action.MASK,
    "PHONE_NUMBER": Action.MASK,
    "IP_ADDRESS": Action.MASK,
    "URL": Action.MASK,
    "IBAN_CODE": Action.MASK,
    "MEDICAL_LICENSE": Action.MASK,
    "US_DRIVER_LICENSE": Action.MASK,
    "US_PASSPORT": Action.MASK,
    "ORGANIZATION": Action.MASK,
    "ORG": Action.MASK,
    # Hyper-sensitive secrets -> drop. They are useless to the model anyway and
    # a leak is catastrophic, so they never leave the machine in any form.
    "US_SSN": Action.DROP,
    "CREDIT_CARD": Action.DROP,
    "CRYPTO": Action.DROP,
    "US_BANK_NUMBER": Action.DROP,
    # Quasi-identifiers -> generalize (keep utility, kill precision).
    "LOCATION": Action.GENERALIZE,
    "GPE": Action.GENERALIZE,
    "AGE": Action.GENERALIZE,
    "DATE_TIME": Action.GENERALIZE,
    "NRP": Action.GENERALIZE,  # nationality / religious / political group
    # Catch-all for contextual entities the LLM detector invents a type for.
    "CONTEXTUAL_IDENTIFIER": Action.MASK,
}

# Action used when an entity type isn't in the map above. We over-protect.
FALLBACK_ACTION = Action.MASK


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

    # Closed-source model provider: "openai" | "anthropic" | "wandb" | "echo".
    provider: str = field(default_factory=lambda: os.getenv("CLOSEAI_PROVIDER", "openai"))
    model: str = field(default_factory=lambda: os.getenv("CLOSEAI_MODEL", "gpt-4o-mini"))

    # Detection threshold for Presidio (0-1). Lower => more recall, more FPs.
    presidio_threshold: float = field(
        default_factory=lambda: float(os.getenv("PRESIDIO_THRESHOLD", "0.35"))
    )

    policy: dict[str, Action] = field(default_factory=lambda: dict(DEFAULT_POLICY))
    fallback_action: Action = FALLBACK_ACTION
