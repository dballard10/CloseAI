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
from typing import Any, Callable

try:  # pragma: no cover - import guard
    import weave  # type: ignore

    _WEAVE_AVAILABLE = True
except Exception:  # pragma: no cover
    weave = None  # type: ignore
    _WEAVE_AVAILABLE = False

_INITIALIZED = False

_SENSITIVE_TRACE_KEYS = {
    "text",
    "original_text",
    "original_prompt",
    "raw_model_response",
    "reidentified_response",
    "entity_map",
}

_REDACTED = "[REDACTED_LOCAL_PII]"


def _weave_disabled() -> bool:
    return os.getenv("WEAVE_DISABLED", "").lower() in ("1", "true", "yes")


def _trace_raw() -> bool:
    return os.getenv("CLOSEAI_TRACE_RAW", "").lower() in ("1", "true", "yes")


def sanitize_for_trace(value: Any) -> Any:
    """Strip locally sensitive fields before Weave persists trace data."""
    if _trace_raw():
        return value
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if str(key) in _SENSITIVE_TRACE_KEYS:
                sanitized[key] = _REDACTED
            else:
                sanitized[key] = sanitize_for_trace(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_for_trace(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_for_trace(item) for item in value)
    return value


def _privacy_op_kwargs(op_kwargs: dict[str, Any]) -> dict[str, Any]:
    if _trace_raw():
        return op_kwargs
    with_privacy = dict(op_kwargs)
    with_privacy.setdefault("postprocess_inputs", sanitize_for_trace)
    with_privacy.setdefault("postprocess_output", sanitize_for_trace)
    return with_privacy


def init_weave(project: str | None = None) -> bool:
    """Initialise Weave tracing. Returns True if Weave is actually active.

    Safe to call multiple times. Reads the project name from the argument, then
    ``WEAVE_PROJECT``, then falls back to ``closeai``.
    """

    global _INITIALIZED
    if _weave_disabled() or not _WEAVE_AVAILABLE:
        return False
    if _INITIALIZED:
        return True

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
        if _WEAVE_AVAILABLE and not _weave_disabled():
            return weave.op(**_privacy_op_kwargs({}))(func)
        return func

    # Parametrised usage: @op(name="...")
    def decorator(func: Callable) -> Callable:
        if _WEAVE_AVAILABLE and not _weave_disabled():
            return weave.op(*op_args, **_privacy_op_kwargs(op_kwargs))(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        return wrapper

    return decorator


def weave_available() -> bool:
    return _WEAVE_AVAILABLE
