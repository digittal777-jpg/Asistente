from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.recovery_engine import RecoveryEngine


class FakeLearning:
    def __init__(self):
        self.calls = []
        self.state = {"recoveries": {}}

    def record_recovery_attempt(self, **kwargs):
        self.calls.append(kwargs)


class RecoveryEngineTests(unittest.TestCase):
    def test_record_attempt_keeps_domain_for_learning_feedback(self):
        with TemporaryDirectory() as temp_dir:
            learning = FakeLearning()
            engine = RecoveryEngine(Path(temp_dir), learning=learning)
            attempt = engine.get_next_strategy(
                {
                    "domain": "research",
                    "training_scenario_id": "research_single_source",
                    "failure_session_id": "session_1",
                    "failure_stage": "poor_quality",
                    "failure_reason": "pagina floja",
                    "attempted_strategies": ["search_keywords"],
                }
            )
            engine.record_attempt(attempt)
            self.assertTrue(learning.calls)
            self.assertEqual(learning.calls[0]["domain"], "research")


if __name__ == "__main__":
    unittest.main()
