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
        if _WEAVE_AVAILABLE:
            return weave.op()(func)
        return func

    # Parametrised usage: @op(name="...")
    def decorator(func: Callable) -> Callable:
        if _WEAVE_AVAILABLE:
            return weave.op(*op_args, **op_kwargs)(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        return wrapper

    return decorator


def weave_available() -> bool:
    return _WEAVE_AVAILABLE
