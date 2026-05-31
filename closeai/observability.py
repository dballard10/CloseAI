"""W&B Weave instrumentation.

Weave is the sponsor tool we lean on for *agent observability*. Every agent
method and the top-level pipeline are decorated with ``@op`` (an alias for
``weave.op``). Once ``init_weave()`` has run, calling the pipeline produces a
full trace tree in the Weave UI:

    deidentify_and_query
    ├── PresidioDetector.detect
    ├── LLMDetector.detect
    ├── Reconciler.reconcile
    ├── PolicyAgent.decide
    ├── Masker.mask
    ├── ClosedModelClient.complete
    └── Reidentifier.reidentify

That trace *is* the "multiple agents working together" story for the judges.

Everything degrades gracefully: if ``weave`` is not installed or
``init_weave()`` is never called, ``op`` becomes a no-op decorator and the code
runs identically (just without traces).
"""

from __future__ import annotations

import functools
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

try:  # pragma: no cover - import guard
    import weave  # type: ignore

    _WEAVE_AVAILABLE = True
except Exception:  # pragma: no cover
    weave = None  # type: ignore
    _WEAVE_AVAILABLE = False

_INITIALIZED = False


def _weave_configured() -> bool:
    return bool(os.getenv("WANDB_API_KEY") or os.getenv("WANDB_API_KEY_FILE"))


def init_weave(project: str | None = None) -> bool:
    """Initialise Weave tracing. Returns True if Weave is actually active.

    Safe to call multiple times. Reads the project name from the argument, then
    ``WEAVE_PROJECT``, then falls back to ``closeai``.
    """

    global _INITIALIZED
    if not _WEAVE_AVAILABLE:
        return False
    if _INITIALIZED:
        return True
    if not _weave_configured():
        return False

    project = project or os.getenv("WEAVE_PROJECT", "closeai")
    try:
        weave.init(project)
        _INITIALIZED = True
        return True
    except Exception as exc:  # pragma: no cover - network/login issues
        print(f"[observability] Weave init failed ({exc}); running without traces.")
        return False


def op(*op_args: Any, **op_kwargs: Any) -> Callable:
    """``@op`` decorator that maps to ``weave.op`` when available, else no-op.

    Supports both ``@op`` and ``@op(name=...)`` usage.
    """

    # Bare decorator usage: @op
    if len(op_args) == 1 and callable(op_args[0]) and not op_kwargs:
        func = op_args[0]
        if _WEAVE_AVAILABLE and _weave_configured():
            return weave.op()(func)
        return func

    # Parametrised usage: @op(name="...")
    def decorator(func: Callable) -> Callable:
        if _WEAVE_AVAILABLE and _weave_configured():
            return weave.op(*op_args, **op_kwargs)(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        return wrapper

    return decorator


def weave_available() -> bool:
    return _WEAVE_AVAILABLE


@dataclass
class WeaveRunTracker:
    project: str
    raw_prompt: str
    mode: str
    model_status: str
    route: str
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    client: Any | None = None
    parent_call: Any | None = None
    ui_url: str | None = None
    trace_id: str | None = None
    enabled: bool = False
    stage_count: int = 0
    _finished: bool = False

    def start(self) -> "WeaveRunTracker":
        if not init_weave(self.project):
            return self
        try:
            from weave.trace.context import weave_client_context  # type: ignore

            self.client = weave_client_context.require_weave_client()
            self.parent_call = self.client.create_call(
                "closedai.privacy_gate_run",
                {
                    "run_id": self.run_id,
                    "raw_prompt": self.raw_prompt,
                    "mode": self.mode,
                    "route": self.route,
                },
                attributes={
                    "closedai": {
                        "run_id": self.run_id,
                        "route": self.route,
                        "mode": self.mode,
                        "model_status": self.model_status,
                        "environment": os.getenv("CLOSEDAI_ENV", "local"),
                    }
                },
                display_name=f"ClosedAI privacy gate {self.run_id[:8]}",
            )
            self.ui_url = getattr(self.parent_call, "ui_url", None)
            self.trace_id = getattr(self.parent_call, "trace_id", None)
            self.enabled = True
        except Exception as exc:
            print(f"[observability] Weave run tracking failed ({exc}); continuing without parent trace.")
        return self

    def stage(
        self,
        name: str,
        inputs: dict[str, Any] | None = None,
        output: Any | None = None,
    ) -> None:
        if not self.enabled or self.client is None or self.parent_call is None:
            return
        try:
            self.stage_count += 1
            call = self.client.create_call(
                f"closedai.stage.{name}",
                {
                    "run_id": self.run_id,
                    "stage": name,
                    **(inputs or {}),
                },
                parent=self.parent_call,
                attributes={
                    "closedai": {
                        "run_id": self.run_id,
                        "stage": name,
                        "stage_index": self.stage_count,
                    }
                },
                display_name=f"{self.stage_count:02d}. {name.replace('_', ' ')}",
            )
            self.client.finish_call(call, output=output)
        except Exception as exc:
            print(f"[observability] Weave stage tracking failed for {name} ({exc}).")

    def finish(self, output: Any | None = None, exception: BaseException | None = None) -> None:
        if self._finished:
            return
        self._finished = True
        if not self.enabled or self.client is None or self.parent_call is None:
            return
        try:
            self.client.finish_call(
                self.parent_call,
                output={
                    "run_id": self.run_id,
                    "stage_count": self.stage_count,
                    **(output if isinstance(output, dict) else {"output": output}),
                },
                exception=exception,
            )
            self.client.finish(use_progress_bar=False)
        except Exception as exc:
            print(f"[observability] Weave finish failed ({exc}).")


def create_run_tracker(
    project: str,
    raw_prompt: str,
    mode: str,
    model_status: str,
    route: str,
) -> WeaveRunTracker:
    return WeaveRunTracker(
        project=project,
        raw_prompt=raw_prompt,
        mode=mode,
        model_status=model_status,
        route=route,
    ).start()
