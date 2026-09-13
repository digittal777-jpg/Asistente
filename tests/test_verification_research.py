from core.training_models import TrainingScenarioResult
from core.verification_research import ResearchVerifier


def test_research_verifier_accepts_current_session_evidence() -> None:
    verifier = ResearchVerifier()
    result = TrainingScenarioResult(
        skill_id="skill:investigar",
        domain="research",
        scenario_id="research_multi_query",
        level=2,
        status="success",
        verified=True,
        evidence={
            "current_session_verified": True,
            "useful_source_count": 3,
            "visible_text_chars": 900,
        },
        metrics={"discard_precision": 0.8},
    )

    assert verifier._is_hard_verified(result) is True
