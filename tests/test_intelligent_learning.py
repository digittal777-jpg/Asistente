from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.intelligent_learning import IntelligentLearningEngine


class FakeMemory:
    def __init__(self):
        self.preferences = {}
        self.step_logs = []

    def get_preference(self, key, default=None):
        return self.preferences.get(key, default)

    def record_step_log(self, **kwargs):
        self.step_logs.append(kwargs)


class FakeConfig:
    def get(self, _key, default=None):
        return default


class IntelligentLearningTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base_dir = Path(self.temp_dir.name)
        self.memory = FakeMemory()
        self.engine = IntelligentLearningEngine(self.base_dir, self.memory, FakeConfig())

    def test_learns_safe_command_and_suggests_similar_command(self):
        self.engine.record_command_result(
            command="buscame arroz con pollo en youtube",
            actions_taken=[
                {
                    "action": "smart_site_search",
                    "params": {"destination": "youtube", "query": "arroz con pollo", "browser": "brave"},
                    "summary": "Buscar en YouTube",
                    "intent": "search",
                }
            ],
            result="ok",
            success=True,
            context={},
        )

        suggestion = self.engine.suggest_command_actions("busca arroz con pollo en yutube")

        self.assertIsNotNone(suggestion)
        actions, note = suggestion
        self.assertIn("aprendizaje inteligente", note)
        self.assertEqual(actions[0].action, "smart_site_search")
        self.assertEqual(actions[0].params["destination"], "youtube")

    def test_adapts_browser_from_successful_action(self):
        self.engine.record_action_result(
            action="smart_site_search",
            params={"destination": "youtube", "browser": "brave", "query": "lofi"},
            result="ok",
            success=True,
        )

        adapted = self.engine.adapt_action(
            "smart_site_search",
            {"destination": "youtube", "query": "anime"},
            context={},
        )

        self.assertEqual(adapted["browser"], "brave")

    def test_strategy_scoring_prefers_successful_strategy(self):
        self.engine.record_strategy_result("search:google", "google_search_bar", False)
        self.engine.record_strategy_result("search:google", "browser_address_bar", True)

        preferred = self.engine.preferred_strategy(
            "search:google",
            ["google_search_bar", "browser_address_bar"],
        )

        self.assertEqual(preferred, "browser_address_bar")


if __name__ == "__main__":
    unittest.main()
