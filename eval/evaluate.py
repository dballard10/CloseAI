"""Weave evaluation harness for the CloseAI detection pipeline.

The metric that matters most here is **recall over sensitive spans**: a missed
entity is a privacy leak, so we optimise to drive false negatives to zero. We
also track precision (false positives cost utility) and a "leak rate" — the
fraction of ground-truth sensitive strings that survive into the masked text.

This uses Weave's ``EvaluationLogger`` so the run, per-example predictions, and
aggregate metrics all show up in the Weave UI. A coding agent (via the W&B MCP)
can then read these numbers and hill-climb the policy / thresholds for you.

Run:
    python eval/evaluate.py
    python eval/evaluate.py --dataset eval/dataset.jsonl --no-llm-detector
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python eval/evaluate.py` from the repo root without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from closeai.config import Settings
from closeai.observability import init_weave
from closeai.pipeline import CloseAIPipeline


def load_dataset(path: str) -> list[dict]:
    rows = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def char_recall(gold: list[str], masked_text: str, original: str) -> tuple[float, int, int]:
    """Recall = fraction of gold sensitive strings no longer verbatim in output.

    Returns (recall, n_caught, n_total). A leaked string is one that still
    appears in the masked text exactly as written.
    """
    if not gold:
        return 1.0, 0, 0
    caught = sum(1 for g in gold if g not in masked_text)
    return caught / len(gold), caught, len(gold)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(Path(__file__).parent / "dataset.jsonl"))
    parser.add_argument("--no-llm-detector", action="store_true")
    parser.add_argument("--project", default=None)
    args = parser.parse_args()

    settings = Settings()
    if args.no_llm_detector:
        settings.enable_llm_detector = False

    weave_on = init_weave(args.project or settings.weave_project)
    pipeline = CloseAIPipeline(settings=settings, init_tracing=False)
    rows = load_dataset(args.dataset)

    # Lazy import so the script still runs (printing metrics) without weave.
    eval_logger = None
    if weave_on:
        from weave import EvaluationLogger

        eval_logger = EvaluationLogger(
            model="closeai-detection",
            dataset="closeai-pii-bench",
        )

    total_recall, total_detected, n_leaks, n = 0.0, 0, 0, 0
    for row in rows:
        text = row["text"]
        gold = row.get("sensitive", [])
        mask_result = pipeline.deidentify(text)
        recall, caught, total = char_recall(gold, mask_result.masked_text, text)
        leaks = total - caught
        total_recall += recall
        total_detected += len(mask_result.decisions)
        n_leaks += leaks
        n += 1

        print(
            f"recall={recall:.2f} detected={len(mask_result.decisions)} "
            f"leaks={leaks}  | {text[:60]}"
        )

        if eval_logger is not None:
            pred = eval_logger.log_prediction(
                inputs={"text": text},
                output={
                    "masked_text": mask_result.masked_text,
                    "decisions": [d.model_dump() for d in mask_result.decisions],
                },
            )
            pred.log_score("recall", recall)
            pred.log_score("n_detected", len(mask_result.decisions))
            pred.log_score("leaks", leaks)
            pred.finish()

    mean_recall = total_recall / max(n, 1)
    print("\n=== SUMMARY ===")
    print(f"examples:        {n}")
    print(f"mean recall:     {mean_recall:.3f}  (1.0 = no leaks)")
    print(f"total leaks:     {n_leaks}")
    print(f"total detected:  {total_detected}")

    if eval_logger is not None:
        eval_logger.log_summary(
            {
                "mean_recall": mean_recall,
                "total_leaks": n_leaks,
                "total_detected": total_detected,
            }
        )
        print("\nLogged to Weave — open the project to inspect per-example traces.")


if __name__ == "__main__":
    main()
