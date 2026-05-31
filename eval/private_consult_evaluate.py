from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from closeai.private_consult import PrivateConsultPipeline


DATASET = Path(__file__).with_name("private_consult_dataset.json")


def direct_leakage_score(sanitized: str, expected_removed: list[str]) -> dict:
    leaked = [item for item in expected_removed if item.lower() in sanitized.lower()]
    return {"passed": len(leaked) == 0, "leaked": leaked, "score": 1.0 if not leaked else 0.0}


def preservation_score(sanitized: str, expected_preserved: list[str]) -> dict:
    kept = [item for item in expected_preserved if item.lower() in sanitized.lower()]
    missing = [item for item in expected_preserved if item.lower() not in sanitized.lower()]
    return {"score": len(kept) / max(1, len(expected_preserved)), "kept": kept, "missing": missing}


def checker_accuracy(checker_result: dict, expected_passed: bool) -> dict:
    correct = checker_result["passed"] == expected_passed
    return {"score": 1.0 if correct else 0.0, "correct": correct, "expected": expected_passed, "actual": checker_result["passed"]}


def repair_success(before_check: dict, after_check: dict) -> dict:
    repaired = not before_check["passed"] and after_check["passed"]
    return {"score": 1.0 if repaired else 0.0, "repaired": repaired}


def main() -> None:
    examples = json.loads(DATASET.read_text())
    pipeline = PrivateConsultPipeline(init_tracing=False, use_llm=False)
    rows = []
    for example in examples:
        result = pipeline.run(example["raw"], example["mode"])
        outbound = result.repairedSanitizedPrompt or result.initialSanitizedPrompt
        direct = direct_leakage_score(outbound, example["expected_removed"])
        preserve = preservation_score(outbound, example["expected_preserved"])
        checker = checker_accuracy(result.finalCheckerResult.model_dump(), direct["passed"])
        repair = repair_success(result.checkerResult.model_dump(), result.finalCheckerResult.model_dump())
        rows.append(
            {
                "mode": example["mode"],
                "direct_leakage": direct["score"],
                "preservation": preserve["score"],
                "checker_accuracy": checker["score"],
                "repair_success": repair["score"],
            }
        )

    summary = {
        "n": len(rows),
        "direct_leakage": mean(row["direct_leakage"] for row in rows),
        "preservation": mean(row["preservation"] for row in rows),
        "checker_accuracy": mean(row["checker_accuracy"] for row in rows),
        "repair_success": mean(row["repair_success"] for row in rows),
    }
    print(json.dumps({"summary": summary, "rows": rows}, indent=2))


if __name__ == "__main__":
    main()
