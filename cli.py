"""CloseAI command-line demo.

Examples:
    python cli.py "Hi, I'm Jane Doe (jane@acme.com), my SSN is 123-45-6789."
    python cli.py --deidentify-only "My manager at the Cambridge office is 37."
    echo "..." | python cli.py
"""

from __future__ import annotations

import argparse
import sys

from closeai.config import Settings
from closeai.pipeline import CloseAIPipeline


def _print_decisions(result) -> None:
    print("\n=== DETECTED ENTITIES ===")
    if not result.decisions:
        print("  (none)")
    for d in result.decisions:
        s = d.span
        line = (
            f"  [{d.action.value.upper():10}] {s.entity_type:22} "
            f"'{s.text}' -> '{d.replacement}'  (src={s.source}, score={s.score:.2f})"
        )
        print(line)
        if s.reason:
            print(f"               ↳ {s.reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description="CloseAI de-identifying LLM proxy")
    parser.add_argument("prompt", nargs="?", help="prompt text (or pipe via stdin)")
    parser.add_argument("--deidentify-only", action="store_true", help="skip the model call")
    parser.add_argument("--provider", help="override CLOSEAI_PROVIDER (openai|anthropic|wandb|echo)")
    parser.add_argument("--model", help="override CLOSEAI_MODEL")
    parser.add_argument("--no-trace", action="store_true", help="disable Weave tracing")
    args = parser.parse_args()

    prompt = args.prompt or sys.stdin.read().strip()
    if not prompt:
        parser.error("provide a prompt argument or pipe text via stdin")

    settings = Settings()
    if args.provider:
        settings.provider = args.provider
    if args.model:
        settings.model = args.model

    pipeline = CloseAIPipeline(settings=settings, init_tracing=not args.no_trace)

    print("\n=== ORIGINAL PROMPT ===")
    print(prompt)

    if args.deidentify_only:
        mask_result = pipeline.deidentify(prompt)
        _print_decisions(mask_result)
        print("\n=== MASKED PROMPT (safe to send) ===")
        print(mask_result.masked_text)
        return

    result = pipeline.deidentify_and_query(prompt)
    _print_decisions(result.mask_result)
    print("\n=== MASKED PROMPT (sent to closed model) ===")
    print(result.masked_prompt)
    print("\n=== RAW MODEL RESPONSE (still masked) ===")
    print(result.raw_model_response)
    print("\n=== RE-IDENTIFIED RESPONSE (shown to user) ===")
    print(result.reidentified_response)
    print(
        f"\n[stats] detected={result.n_detected} masked={result.n_masked} "
        f"generalized={result.n_generalized} dropped={result.n_dropped} "
        f"kept={result.n_kept}"
    )


if __name__ == "__main__":
    main()
