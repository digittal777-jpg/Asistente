import unittest

from core.autonomous_learning_system import AutonomousLearningSystem
from core.curriculum_planner import CurriculumPlanner
from core.task_analysis import TaskAnalyzer
from core.training_models import TrainingScenarioResult


class StubLoop:
    def __init__(self, verified=True, status="success", research_verified=None):
        self.calls = []
        self.verified = verified
        self.status = status
        self.research_verified = verified if research_verified is None else research_verified

    def run_one_cycle(self, preferred_domain=None, forced_scenario=None, forced_skill_id=None):
        forced_scenario = dict(forced_scenario or {})
        scenario_id = forced_scenario.get("scenario_id", "stub")
        domain = preferred_domain or "application_workflow"
        scenario_verified = self.research_verified if domain == "research" else self.verified
        goal = str(forced_scenario.get("training_goal", "") or "")
        self.calls.append(
            {
                "domain": domain,
                "scenario_id": scenario_id,
                "base_scenario_id": forced_scenario.get("base_scenario_id", scenario_id),
                "forced_skill_id": forced_skill_id,
                "goal": goal,
            }
        )
        evidence = {
            "base_scenario_id": forced_scenario.get("base_scenario_id", scenario_id),
            "captured_chars": 1800,
        }
        metrics = {"captured_chars": 1800}
        if domain == "research":
            evidence.update(
                {
                    "reviewed_sources": ["Guia 1", "Wiki", "Foro 1"],
                    "queries_used": [goal] if goal else [],
                    "useful_source_count": 3,
                    "research_summary": f"Resumen verificado de {goal}",
                    "research_findings": f"Hallazgos clave de {goal}",
                    "discard_precision": 0.8,
                }
            )
            metrics.update({"useful_source_count": 3, "discard_precision": 0.8})
        return TrainingScenarioResult(
            skill_id=forced_skill_id or forced_scenario.get("skill_id", "skill:mouse"),
            domain=domain,
            scenario_id=scenario_id,
            session_id=f"session_{len(self.calls)}",
            timestamp=len(self.calls),
            level=max(1, int(forced_scenario.get("target_level", 1) or 1)),
            status=self.status,
            verified=scenario_verified,
            metrics=metrics,
            evidence=evidence,
            verified_outcome={"verified": scenario_verified},
        )


class FakeTaskExecutor:
    def __init__(self):
        self.calls = []

    def perform_research(self, topic, browser="brave", result_count=3):
        self.calls.append((topic, browser, result_count))
        return {
            "topic": topic,
            "browser": browser,
            "result_count": result_count,
            "summary": f"Resumen de {topic}",
            "reviewed_sources": ["Fuente 1", "Fuente 2"],
            "useful_source_count": 2,
        }


class WeakTaskExecutor(FakeTaskExecutor):
    def perform_research(self, topic, browser="brave", result_count=3):
        self.calls.append((topic, browser, result_count))
        return {
            "topic": topic,
            "browser": browser,
            "result_count": result_count,
            "summary": "",
            "findings": "",
            "reviewed_sources": [],
            "useful_source_count": 0,
            "captured_chars": 24,
        }


class AutonomousLearningStackTests(unittest.TestCase):
    def test_task_analyzer_detects_template(self):
        analyzer = TaskAnalyzer()
        result = analyzer.analyze_task("aprende a jugar terraria")
        self.assertEqual(result.objective_type, "terraria")
        self.assertIn("terraria_movement", result.required_skills)
        self.assertIn("terraria controles basicos", result.required_knowledge)

    def test_task_analyzer_detects_web_development_objective(self):
        analyzer = TaskAnalyzer()
        result = analyzer.analyze_task("hacer una aplicacion web basica para sumar con node.js")

        self.assertEqual(result.objective_type, "web_development")
        self.assertIn("nodejs_project_setup", result.required_skills)
        self.assertIn("node.js proyecto basico", result.required_knowledge)

    def test_curriculum_planner_orders_minecraft_dependencies(self):
        analyzer = TaskAnalyzer()
        task = analyzer.analyze_task("learn to play minecraft")
        planner = CurriculumPlanner()
        curriculum = planner.create_curriculum(task, [])
        ordered = [skill for phase in curriculum.phases for skill in phase.skills]
        self.assertLess(ordered.index("minecraft_movement"), ordered.index("minecraft_mining"))
        self.assertLess(ordered.index("minecraft_mining"), ordered.index("minecraft_crafting"))
        scenario_ids = [item["scenario_id"] for phase in curriculum.phases for item in phase.scenarios]
        self.assertEqual(len(scenario_ids), len(set(scenario_ids)))
        self.assertTrue(all("__" in scenario_id for scenario_id in scenario_ids))
        self.assertTrue(all(item.get("base_scenario_id") for phase in curriculum.phases for item in phase.scenarios))
        self.assertTrue(all(item.get("domain") for phase in curriculum.phases for item in phase.scenarios))

    def test_generic_analysis_uses_single_draft_skill_without_hard_research_prerequisite(self):
        analyzer = TaskAnalyzer()
        result = analyzer.analyze_task("teletransportacion cuantica")

        self.assertEqual(result.required_skills, ["teletransportacion_cuantica"])
        self.assertNotIn("skill:investigar", result.prerequisites)

    def test_autonomous_learning_system_runs_end_to_end(self):
        loop = StubLoop()
        executor = FakeTaskExecutor()
        system = AutonomousLearningSystem(loop, task_executor=executor)
        result = system.learn("aprende a jugar terraria", use_research=True)

        self.assertTrue(result["success"])
        self.assertGreater(result["total_sessions"], 0)
        self.assertGreater(result["verified_sessions"], 0)
        self.assertGreater(result["knowledge_assets_collected"], 0)
        self.assertTrue(loop.calls)
        self.assertEqual(loop.calls[0]["domain"], "research")
        self.assertTrue(any(call["domain"] == "game_foundation" for call in loop.calls))
        self.assertTrue(all(call["forced_skill_id"] for call in loop.calls))
        self.assertFalse(executor.calls)
        curriculum_assets = [
            scenario["knowledge_assets"]
            for phase in result["curriculum"].phases
            for scenario in phase.scenarios
        ]
        self.assertTrue(any(asset_list for asset_list in curriculum_assets))

    def test_autonomous_learning_system_falls_back_to_direct_research_when_loop_bootstrap_is_unverified(self):
        loop = StubLoop(research_verified=False)
        executor = FakeTaskExecutor()
        system = AutonomousLearningSystem(loop, task_executor=executor)

        result = system.learn("aprende a jugar terraria", use_research=True)

        self.assertTrue(result["success"])
        self.assertTrue(result["research_bootstrap"]["fallback_used"])
        self.assertGreater(len(executor.calls), 0)
        self.assertGreater(result["knowledge_assets_collected"], 0)

    def test_autonomous_learning_system_discards_weak_direct_research_assets(self):
        loop = StubLoop(research_verified=False)
        executor = WeakTaskExecutor()
        system = AutonomousLearningSystem(loop, task_executor=executor)

        assets = system._direct_research_assets(["terraria combate"], covered_topics=set())

        self.assertEqual(assets, [])

    def test_knowledge_asset_from_result_rejects_weak_youtube_evidence_without_transcript_or_ocr(self):
        result = TrainingScenarioResult(
            skill_id="skill:youtube",
            domain="browser",
            scenario_id="youtube_goal_workflow",
            session_id="session_weak_video",
            timestamp=1,
            level=3,
            status="success",
            verified=True,
            metrics={"captured_chars": 30},
            evidence={
                "source_kind": "youtube_video",
                "summary_preview": "",
                "transcript_available": False,
                "transcript_chars": 0,
                "visible_text_chars": 30,
                "captured_chars": 30,
                "page_usefulness_label": "poor",
            },
            verified_outcome={"verified": True},
        )

        asset = AutonomousLearningSystem._knowledge_asset_from_result(
            "minecraft redstone",
            {"base_scenario_id": "research_single_source"},
            result,
        )

        self.assertIsNone(asset)

    def test_knowledge_asset_from_result_rejects_raw_single_source_research_noise(self):
        result = TrainingScenarioResult(
            skill_id="skill:investigar",
            domain="research",
            scenario_id="research_single_source",
            session_id="session_raw_single_source",
            timestamp=1,
            level=1,
            status="success",
            verified=True,
            metrics={"captured_chars": 1400, "useful_source_count": 1},
            evidence={
                "page_title": "Sin título - Brave",
                "source_kind": "web_page",
                "captured_chars": 1400,
                "visible_text_chars": 1400,
                "useful_source_count": 1,
                "page_usefulness_label": "useful",
                "current_session_verified": True,
            },
            verified_outcome={"single_source_verified": True},
        )

        asset = AutonomousLearningSystem._knowledge_asset_from_result(
            "terraria crafting early game",
            {"base_scenario_id": "research_single_source"},
            result,
        )

        self.assertIsNone(asset)

    def test_autonomous_learning_system_requires_verified_progress(self):
        loop = StubLoop(verified=False, status="success", research_verified=False)
        system = AutonomousLearningSystem(loop, task_executor=FakeTaskExecutor())

        result = system.learn("aprende a jugar terraria", use_research=True)

        self.assertFalse(result["success"])
        self.assertEqual(result["verified_sessions"], 0)
        self.assertEqual(result["progress"].phases_completed, [])


if __name__ == "__main__":
    unittest.main()
