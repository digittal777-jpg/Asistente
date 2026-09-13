import unittest

from core.assistant import RaphelAssistant


class SnapshotStub:
    def to_dict(self):
        return {
            "active_window": "Google Search",
            "active_app": "brave",
            "active_site": "google",
        }


class PerceptionStub:
    def to_dict(self):
        return {
            "scene_kind": "browser_serp",
            "selected_target_id": "google_result_card_1",
        }


class AssistantContextTests(unittest.TestCase):
    def test_get_context_payload_returns_snapshot_and_perception_layers(self):
        assistant = RaphelAssistant.__new__(RaphelAssistant)
        assistant.get_latest_vision_snapshot = lambda refresh=False: SnapshotStub()
        assistant.get_latest_perception = lambda refresh=False, snapshot=None: PerceptionStub()

        payload = assistant.get_context_payload()

        self.assertEqual(set(payload.keys()), {"snapshot", "perception"})
        self.assertEqual(payload["snapshot"]["active_app"], "brave")
        self.assertEqual(payload["perception"]["scene_kind"], "browser_serp")

    def test_learn_skill_promotes_open_objective_to_autonomous_learning(self):
        assistant = RaphelAssistant.__new__(RaphelAssistant)
        assistant._safe_automation_call = lambda _action, _payload, callback: callback()
        assistant.learning_skill_engine = type(
            "Engine",
            (),
            {
                "_resolve_skill": lambda self, _skill: {
                    "supported": False,
                    "template_kind": "draft",
                },
                "learn_skill": lambda self, **_kwargs: "direct learn",
            },
        )()
        assistant.autonomous_learning_system = type(
            "Auto",
            (),
            {
                "learn": lambda self, objective, use_research=True: {
                    "final_report": f"Aprendizaje autonomo para {objective}",
                    "objective": objective,
                    "knowledge_assets_collected": 2,
                    "research_bootstrap": {"topics": [objective], "fallback_used": False},
                    "total_sessions": 4,
                    "verified_sessions": 2,
                    "curriculum": type("Curriculum", (), {"phases": [object(), object()]})(),
                    "progress": type("Progress", (), {"phases_completed": ["phase_foundation"]})(),
                }
            },
        )()

        result = assistant.learn_skill("hacer una aplicacion web basica para sumar con node.js")

        self.assertIn("Ruta usada: learn_skill -> autonomous_learn", result)
        self.assertIn("node.js", result)

    def test_learn_skill_keeps_direct_route_for_supported_skill(self):
        assistant = RaphelAssistant.__new__(RaphelAssistant)
        assistant._safe_automation_call = lambda _action, _payload, callback: callback()
        assistant.learning_skill_engine = type(
            "Engine",
            (),
            {
                "_resolve_skill": lambda self, _skill: {
                    "supported": True,
                    "template_kind": "keyboard",
                },
                "learn_skill": lambda self, **_kwargs: "direct learn",
            },
        )()
        assistant.autonomous_learning_system = type(
            "Auto",
            (),
            {"learn": lambda self, objective, use_research=True: {"final_report": f"auto {objective}"}},
        )()

        result = assistant.learn_skill("teclado")

        self.assertEqual(result, "direct learn")


if __name__ == "__main__":
    unittest.main()
