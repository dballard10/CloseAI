"""The orchestrator that wires the agents into one de-identify -> query -> re-identify flow.

This is the heart of the "agent orchestration" story. Every step is its own
Weave op, so a single call to ``deidentify_and_query`` renders as a clean trace
tree in the Weave UI showing the agents collaborating.

Data flow:

    text
     ├─(parallel)→ PresidioDetector.detect ─┐
     │             LLMDetector.detect ──────┤
     │                                      ▼
     │                          Reconciler.reconcile  (union, over-detect)
     │                                      ▼
     │                          PolicyAgent.decide    (mask/generalize/drop/keep)
     │                                      ▼
     │                          Masker.mask           (-> masked text + entity map)
     ▼                                      ▼
    [ masked text leaves the machine ]  ClosedModelClient.complete
                                            ▼
                          Reidentifier.reidentify     (placeholders -> originals)
                                            ▼
                                  final user-facing answer
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from .agents import (
    LLMDetector,
    Masker,
    PolicyAgent,
    PresidioDetector,
    Reconciler,
    Reidentifier,
)
from .config import Settings
from .llm_client import ClosedModelClient
from .observability import init_weave, op
from .schemas import Action, MaskResult, PipelineResult


class CloseAIPipeline:
    def __init__(self, settings: Settings | None = None, init_tracing: bool = True):
        self.settings = settings or Settings()
        if init_tracing:
            init_weave(self.settings.weave_project)

        self.presidio = PresidioDetector(
            spacy_model=self.settings.spacy_model,
            threshold=self.settings.presidio_threshold,
        )
        self.llm_detector = LLMDetector(
            host=self.settings.ollama_host,
            model=self.settings.ollama_model,
            enabled=self.settings.enable_llm_detector,
        )
        self.reconciler = Reconciler()
        self.policy = PolicyAgent(self.settings.policy, self.settings.fallback_action)
        self.masker = Masker()
        self.reidentifier = Reidentifier()
        self.model = ClosedModelClient(
            self.settings.provider,
            self.settings.model,
            ollama_host=self.settings.ollama_host,
        )

    def model_client(
        self, provider: str | None = None, model: str | None = None
    ) -> ClosedModelClient:
        """Create a request-local model client when provider/model are overridden."""
        if provider is None and model is None:
            return self.model
        return ClosedModelClient(
            provider or self.settings.provider,
            model or self.settings.model,
            ollama_host=self.settings.ollama_host,
        )

    @op
    def deidentify(self, text: str) -> MaskResult:
        """Run detection -> reconcile -> policy -> mask. No network egress here."""
        # The two detectors are independent: run them concurrently.
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_presidio = pool.submit(self.presidio.detect, text)
            f_llm = pool.submit(self.llm_detector.detect, text)
            presidio_spans = f_presidio.result()
            llm_spans = f_llm.result()

        spans = self.reconciler.reconcile(text, presidio_spans, llm_spans)
        decisions = self.policy.decide(spans)
        return self.masker.mask(text, decisions)

    @op
    def deidentify_and_query(
        self,
        text: str,
        system: str | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> PipelineResult:
        """Full round-trip: de-identify, send to the closed model, re-identify."""
        mask_result = self.deidentify(text)
        client = self.model_client(provider=provider, model=model)
        raw_response = client.complete(mask_result.masked_text, system=system)
        return self.build_result(text, mask_result, raw_response)

    def build_result(
        self, text: str, mask_result: MaskResult, raw_response: str
    ) -> PipelineResult:
        """Assemble the user-facing result after the closed model responds."""
        final = self.reidentifier.reidentify(raw_response, mask_result.entity_map)
        actions = [d.action for d in mask_result.decisions]
        return PipelineResult(
            original_prompt=text,
            masked_prompt=mask_result.masked_text,
            raw_model_response=raw_response,
            reidentified_response=final,
            mask_result=mask_result,
            n_detected=len(mask_result.decisions),
            n_surrogated=actions.count(Action.SURROGATE),
            n_described=actions.count(Action.DESCRIBE),
            n_dropped=actions.count(Action.DROP),
            n_kept=actions.count(Action.KEEP),
        )
