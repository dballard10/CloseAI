"""Shared data contracts that flow between the agents.

Everything that crosses an agent boundary is one of these models. Keeping the
contracts in one place makes the pipeline easy to reason about and gives Weave
clean, structured inputs/outputs to render in its trace tree.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Action(str, Enum):
    """What the policy agent decides to do with a detected entity.

    MASK is reversible (placeholder -> original is stored in the entity map and
    restored after the model responds). GENERALIZE and DROP are deliberately
    irreversible: the original never leaves the machine.
    """

    MASK = "mask"            # replace with a reversible placeholder, e.g. [PERSON_1]
    GENERALIZE = "generalize"  # coarsen, e.g. 37 -> "30s", "Cambridge" -> "New England"
    DROP = "drop"            # remove entirely, never sent, never restored
    KEEP = "keep"            # leave untouched (low-risk and high-utility)


class Span(BaseModel):
    """A character span in the original text flagged as sensitive by a detector."""

    start: int
    end: int
    entity_type: str
    text: str
    score: float = 1.0
    source: str = "unknown"  # "presidio" | "llm" | "merged"
    # Free-form note, mostly used by the LLM detector to explain *why* it flagged
    # something contextual (e.g. "implicit identifier: 'my manager at Cambridge'").
    reason: Optional[str] = None

    def overlaps(self, other: "Span") -> bool:
        return self.start < other.end and other.start < self.end


class EntityDecision(BaseModel):
    """A span plus the policy agent's decision and the concrete replacement."""

    span: Span
    action: Action
    # The string that physically replaces the span in the outgoing text.
    # For MASK this is the placeholder, for GENERALIZE the coarsened value,
    # for DROP an empty string, for KEEP the original text.
    replacement: str
    # Present only for reversible (MASK) entities so the re-identifier can undo it.
    placeholder: Optional[str] = None


class MaskResult(BaseModel):
    """Output of the masker: the safe text plus the secret map to reverse it."""

    original_text: str
    masked_text: str
    decisions: list[EntityDecision] = Field(default_factory=list)
    # placeholder -> original text. This NEVER leaves the local machine.
    entity_map: dict[str, str] = Field(default_factory=dict)


class PipelineResult(BaseModel):
    """Everything produced by one round-trip through CloseAI."""

    original_prompt: str
    masked_prompt: str
    raw_model_response: str          # what the closed model returned (still masked)
    reidentified_response: str       # placeholders swapped back to originals
    mask_result: MaskResult
    # Coarse stats that are nice to show in a demo / log to Weave.
    n_detected: int = 0
    n_masked: int = 0
    n_generalized: int = 0
    n_dropped: int = 0
    n_kept: int = 0


RiskLevel = Literal["low", "medium", "high"]
ConsultMode = Literal["hr", "legal", "healthcare", "education", "general"]


class SensitiveEntity(BaseModel):
    text: str
    type: str
    risk: RiskLevel
    replacementHint: str | None = None


class CheckerResult(BaseModel):
    passed: bool
    riskLevel: RiskLevel
    leakageTypes: list[str] = Field(default_factory=list)
    leakedItems: list[str] = Field(default_factory=list)
    explanation: str | None = None
    recommendedFix: str | None = None


class UtilityResult(BaseModel):
    utilityScore: float
    preservedConcepts: list[str] = Field(default_factory=list)
    missingUsefulContext: list[str] = Field(default_factory=list)


class ExternalConsultantResponse(BaseModel):
    advice: str
    suggestedStructure: list[str] = Field(default_factory=list)
    outputFormat: str | None = None
    finalizerInstructions: str | None = None
    risks: list[str] = Field(default_factory=list)


class PromptVersions(BaseModel):
    deidPrompt: str = "deid_prompt:v4-trusted-llm-semantic-abstraction"
    checkerPrompt: str = "checker_prompt:v4-trusted-llm-privacy-and-utility"
    repairPrompt: str = "repair_prompt:v3-trusted-llm-retry-plus-safety"


class WeaveMetadata(BaseModel):
    traceName: str = "closedai-private-consult-run"
    project: str = "closedai"
    status: str = "offline-compatible"
    runId: str | None = None
    traceId: str | None = None
    dashboardUrl: str | None = None
    trackingStatus: str = "not_configured"
    evalScores: dict[str, float] = Field(default_factory=dict)
    promptComparison: list[dict[str, float | str]] = Field(default_factory=list)


class RunRequest(BaseModel):
    rawPrompt: str
    mode: ConsultMode = "general"


class RunResponse(BaseModel):
    rawPrompt: str
    detectedEntities: list[SensitiveEntity] = Field(default_factory=list)
    initialSanitizedPrompt: str
    checkerResult: CheckerResult
    repairedSanitizedPrompt: str | None = None
    finalCheckerResult: CheckerResult
    utilityResult: UtilityResult
    externalCallAllowed: bool
    externalConsultantResponse: ExternalConsultantResponse | None = None
    finalAnswer: str
    weaveTraceUrl: str | None = None
    promptVersions: PromptVersions = Field(default_factory=PromptVersions)
    weaveMetadata: WeaveMetadata = Field(default_factory=WeaveMetadata)
