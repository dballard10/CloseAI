from __future__ import annotations

from closeai.private_consult import PrivateConsultPipeline, should_call_external


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
    assert "Sarah Klein" in result.finalAnswer


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
