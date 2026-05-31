from __future__ import annotations

from closeai.private_consult import (
    PrivateConsultPipeline,
    _normalize_checker_leaked_items,
    should_call_external,
)


def _pipeline() -> PrivateConsultPipeline:
    return PrivateConsultPipeline(init_tracing=False, use_llm=False)


def test_hr_example_repairs_before_external_call():
    result = _pipeline().run(
        "Sarah Klein at Acme Robotics in Boston requested medical leave after a panic disorder diagnosis. "
        "Two weeks later, her manager Alex put her on a PIP. Help me write a careful HR response.",
        "hr",
    )

    assert result.checkerResult.passed is False
    assert "Acme Robotics" in result.checkerResult.leakedItems
    assert result.repairedSanitizedPrompt is not None
    assert "Acme Robotics" not in result.repairedSanitizedPrompt
    assert "panic disorder" not in result.repairedSanitizedPrompt
    assert result.finalCheckerResult.passed is True
    assert result.externalCallAllowed is True
    assert result.externalConsultantResponse is not None
    assert result.finalAnswer.startswith("Finalizer failed:")


def test_legal_example_does_not_send_raw_identifiers():
    result = _pipeline().run(
        "My landlord Mark Benson at 45 Winter Street in Cambridge says he will keep my security deposit because of damage from March 7.",
        "legal",
    )
    outbound = result.repairedSanitizedPrompt or result.initialSanitizedPrompt

    assert "Mark Benson" not in outbound
    assert "45 Winter Street" not in outbound
    assert "Cambridge" not in outbound
    assert result.finalCheckerResult.passed is True
    assert should_call_external(result.finalCheckerResult, result.utilityResult) is True


def test_checker_does_not_treat_privacy_category_labels_as_leaks():
    sanitized = (
        "A worker at a company visited an urgent care clinic after experiencing symptoms during work. "
        "A staff member allegedly spoke personal information out loud, including full name, date of birth, "
        "insurance details, symptoms, and contact information. The user wants a firm complaint letter asking "
        "the clinic to correct contact information, explain what happened, assess whether it was a privacy "
        "violation, and describe prevention steps."
    )

    leaked = _normalize_checker_leaked_items(
        [
            "full name",
            "date of birth",
            "insurance details",
            "symptoms",
            "contact information",
            "actual-policy-123",
        ],
        sanitized,
    )

    assert leaked == []
