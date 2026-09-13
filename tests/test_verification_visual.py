import unittest

from core.training_models import TrainingScenarioResult
from core.verification_visual import VisualPerceptionVerifier


class VisualPerceptionVerifierTests(unittest.TestCase):
    def setUp(self):
        self.verifier = VisualPerceptionVerifier()

    def _result(self, scenario_id, evidence, success=True):
        return TrainingScenarioResult(
            skill_id="skill:visualizacion",
            domain="perception",
            scenario_id=scenario_id,
            level=1,
            status="success" if success else "failure",
            verified=success,
            evidence=evidence,
        )

    def test_context_identity_requires_scene_target_and_non_ocr_only(self):
        verified = self.verifier.verify(
            self._result(
                "visual_context_identity",
                {
                    "scene_kind": "browser_article",
                    "confidence": 0.81,
                    "actable_target_count": 1,
                    "selected_target_id": "browser_content_region",
                    "ocr_only": False,
                },
            )
        )
        blocked = self.verifier.verify(
            self._result(
                "visual_context_identity",
                {
                    "scene_kind": "browser_article",
                    "confidence": 0.81,
                    "actable_target_count": 1,
                    "selected_target_id": "browser_content_region",
                    "ocr_only": True,
                },
            )
        )

        self.assertTrue(verified["context_identity_verified"])
        self.assertFalse(blocked["context_identity_verified"])

    def test_target_reacquire_requires_match(self):
        verified = self.verifier.verify(
            self._result(
                "visual_target_reacquire",
                {
                    "ocr_only": False,
                    "reacquire": {
                        "matched": True,
                        "delta_px": 8.0,
                        "stable_signature_match": True,
                        "current_target_id": "google_result_card_1",
                    },
                },
            )
        )
        blocked = self.verifier.verify(
            self._result(
                "visual_target_reacquire",
                {
                    "ocr_only": False,
                    "reacquire": {
                        "matched": False,
                        "delta_px": 52.0,
                        "stable_signature_match": False,
                        "current_target_id": "",
                    },
                },
                success=False,
            )
        )

        self.assertTrue(verified["target_reacquire_verified"])
        self.assertFalse(blocked["target_reacquire_verified"])

    def test_scene_transition_fails_when_scene_does_not_change(self):
        result = self.verifier.verify(
            self._result(
                "visual_scene_transition",
                {
                    "initial_scene_kind": "browser_serp",
                    "final_scene_kind": "browser_serp",
                },
                success=False,
            )
        )

        self.assertFalse(result["scene_transition_verified"])

    def test_workflow_precondition_fails_for_ocr_only_or_serp(self):
        serp = self.verifier.verify(
            self._result(
                "visual_workflow_precondition",
                {
                    "scene_kind": "browser_serp",
                    "precondition_ready": True,
                    "selected_target_confidence": 0.85,
                    "blocking_reason": "",
                    "verification_source": "perception_bundle",
                },
                success=False,
            )
        )
        ocr_only = self.verifier.verify(
            self._result(
                "visual_workflow_precondition",
                {
                    "scene_kind": "browser_article",
                    "precondition_ready": True,
                    "selected_target_confidence": 0.85,
                    "blocking_reason": "",
                    "verification_source": "ocr_only",
                },
                success=False,
            )
        )

        self.assertFalse(serp["workflow_precondition_verified"])
        self.assertFalse(ocr_only["workflow_precondition_verified"])

    def test_adversarial_recovery_requires_blocked_then_recovered(self):
        verified = self.verifier.verify(
            self._result(
                "visual_adversarial_recovery",
                {
                    "initial_blocked": True,
                    "recovered": True,
                    "recovery_target_confidence": 0.82,
                    "ocr_only": False,
                },
            )
        )
        blocked = self.verifier.verify(
            self._result(
                "visual_adversarial_recovery",
                {
                    "initial_blocked": False,
                    "recovered": True,
                    "recovery_target_confidence": 0.82,
                    "ocr_only": False,
                },
                success=False,
            )
        )

        self.assertTrue(verified["adversarial_recovery_verified"])
        self.assertFalse(blocked["adversarial_recovery_verified"])


if __name__ == "__main__":
    unittest.main()
