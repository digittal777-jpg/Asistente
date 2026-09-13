import unittest
from unittest.mock import patch

from core.training_models import DomainTrainingState, TrainingScenarioResult
from core.training_scheduler import SkillScheduler
from core.training_loop_infinite import InfiniteTrainingLoop
from core.verification_desktop_first import DESKTOP_FIRST_GATES, DESKTOP_SCENARIO_EQUIVALENTS
from core.verification_research import RESEARCH_GATES


class FakeLoopLearningSkillEngine:
    def __init__(self) -> None:
        self.state = {"profiles": {}}
        self.desktop_verifier = None
        self.research_verifier = None
        self.visual_verifier = type(
            "VisualVerifier",
            (),
            {
                "verify": lambda self, result: {
                    "context_identity_verified": bool(result.evidence.get("current_session_verified")),
                    "target_reacquire_verified": bool(result.evidence.get("current_session_verified")),
                    "scene_transition_verified": bool(result.evidence.get("current_session_verified")),
                    "workflow_precondition_verified": bool(result.evidence.get("current_session_verified")),
                    "adversarial_recovery_verified": bool(result.evidence.get("current_session_verified")),
                    "verified_outcome": {
                        "current_session_verified": bool(result.evidence.get("current_session_verified")),
                        "verification_family": "perception",
                    },
                }
            },
        )()
        self.history = {}
        self.recorded = None

    @staticmethod
    def _profile_matches_domain(profile, domain):
        template_kind = str(profile.get("template_kind", ""))
        if template_kind == "keyboard":
            return domain == "keyboard"
        if template_kind == "visual_perception":
            return domain == "perception"
        if template_kind == "research_workflow":
            return domain == "research"
        if template_kind in {"browser_app", "site_workflow"}:
            return domain == "browser"
        if template_kind in {"file_manager", "window_management"}:
            return domain == "file_manager/explorer"
        if template_kind == "document_editor":
            return domain == "document_editor"
        return False

    @staticmethod
    def _profile_domain(profile):
        template_kind = str(profile.get("template_kind", ""))
        if template_kind == "keyboard":
            return "keyboard"
        if template_kind == "visual_perception":
            return "perception"
        if template_kind == "research_workflow":
            return "research"
        if template_kind in {"browser_app", "site_workflow"}:
            return "browser"
        if template_kind in {"file_manager", "window_management"}:
            return "file_manager/explorer"
        if template_kind == "document_editor":
            return "document_editor"
        return "application_workflow"

    @staticmethod
    def _resolve_skill(requested_skill):
        normalized = str(requested_skill or "").strip().lower()
        mapping = {
            "teclado": {
                "skill_id": "skill:teclado",
                "canonical_entity": "teclado",
                "template_kind": "keyboard",
                "supported": True,
            },
            "investigar": {
                "skill_id": "skill:investigar",
                "canonical_entity": "investigar",
                "template_kind": "research_workflow",
                "supported": True,
            },
            "visualizacion": {
                "skill_id": "skill:visualizacion",
                "canonical_entity": "visualizacion",
                "template_kind": "visual_perception",
                "supported": True,
            },
            "brave": {
                "skill_id": "app:brave",
                "canonical_entity": "brave",
                "template_kind": "browser_app",
                "supported": True,
            },
            "youtube": {
                "skill_id": "site:youtube",
                "canonical_entity": "youtube",
                "template_kind": "site_workflow",
                "supported": True,
            },
            "explorer": {
                "skill_id": "app:explorer",
                "canonical_entity": "explorer",
                "template_kind": "file_manager",
                "supported": True,
            },
            "window management": {
                "skill_id": "skill:window_management",
                "canonical_entity": "window_management",
                "template_kind": "window_management",
                "supported": True,
            },
            "notepad": {
                "skill_id": "app:notepad",
                "canonical_entity": "notepad",
                "template_kind": "document_editor",
                "supported": True,
            },
            "word": {
                "skill_id": "app:word",
                "canonical_entity": "word",
                "template_kind": "document_editor",
                "supported": True,
            },
            "mouse": {
                "skill_id": "skill:mouse",
                "canonical_entity": "mouse",
                "template_kind": "mouse_control",
                "supported": True,
            },
            "jugar terraria": {
                "skill_id": "jugar_terraria",
                "canonical_entity": "terraria",
                "template_kind": "game_foundation",
                "supported": True,
            },
        }
        resolved = dict(mapping.get(normalized, {}))
        if not resolved:
            return {"skill_id": normalized or "draft", "template_kind": "draft", "supported": False}
        resolved.setdefault("display_name", requested_skill)
        resolved.setdefault("family", "ui_workflow")
        return resolved

    def training_domain_states(self):
        return []

    def _profile_training_history(self, skill_id):
        return list(self.history.get(skill_id, []))

    def add_history(self, skill_id, result):
        self.history.setdefault(skill_id, []).append(result)

    def record_training_result(self, result):
        self.recorded = result


class FakeLoopAssistant:
    def __init__(self, practice_hook=None, learn_hook=None):
        self.practice_hook = practice_hook
        self.learn_hook = learn_hook
        self.learning = None
        self.calls = []

    def practice_skill(self, skill, goal=None, attempts=None, minutes=None):
        self.calls.append(("practice_skill", skill, goal, attempts, minutes))
        if callable(self.practice_hook):
            return self.practice_hook(skill=skill, goal=goal, attempts=attempts, minutes=minutes)
        return "practice ok"

    def learn_skill(self, skill, goal=None, attempts=None, minutes=None, create_document=False):
        self.calls.append(("learn_skill", skill, goal, attempts, minutes, create_document))
        if callable(self.learn_hook):
            return self.learn_hook(
                skill=skill,
                goal=goal,
                attempts=attempts,
                minutes=minutes,
                create_document=create_document,
            )
        if callable(self.practice_hook):
            return self.practice_hook(
                skill=skill,
                goal=goal,
                attempts=attempts,
                minutes=minutes,
                create_document=create_document,
            )
        return "learn ok"

    @staticmethod
    def practice_mouse_movement(attempts=None, skip_confirmation=True):
        return "mouse movement ok"

    @staticmethod
    def practice_mouse_click(attempts=None, skip_confirmation=True):
        return "mouse click ok"

    @staticmethod
    def practice_mouse_double_click(attempts=None, skip_confirmation=True):
        return "mouse double click ok"

    @staticmethod
    def practice_mouse_right_click(attempts=None, skip_confirmation=True):
        return "mouse right click ok"

    @staticmethod
    def practice_mouse_detection(attempts=None, skip_confirmation=True):
        return "mouse detect ok"

    @staticmethod
    def practice_mouse_selection(attempts=None, skip_confirmation=True):
        return "mouse selection ok"

    @staticmethod
    def practice_mouse_workflow(attempts=None, skip_confirmation=True):
        return "mouse workflow ok"

    @staticmethod
    def practice_desktop_mouse(attempts=None, skip_confirmation=True):
        return "desktop mouse ok"


class FakeRecoveryEngine:
    def __init__(self):
        self.called = False
        self.recorded = []

    def get_next_strategy(self, failure):
        self.called = True
        return type(
            "Recovery",
            (),
            {
                "chosen_next_strategy": "retry_alt",
                "strategy_reasoning": "retry alt",
                "attempted_strategies": [],
                "recovery_session_id": "",
                "recovery_succeeded": False,
                "recovery_verified": False,
                "verified_outcome": {},
                "confidence_in_recovery": 0.5,
                "is_playbook_decision": True,
                "domain": failure["domain"],
                "training_scenario_id": failure["training_scenario_id"],
                "failure_session_id": failure["failure_session_id"],
                "failure_stage": failure["failure_stage"],
                "failure_reason": failure["failure_reason"],
            },
        )()

    def record_attempt(self, attempt):
        self.recorded.append(attempt)


class InfiniteTrainingLoopTests(unittest.TestCase):
    @staticmethod
    def _make_loop() -> InfiniteTrainingLoop:
        loop = InfiniteTrainingLoop.__new__(InfiniteTrainingLoop)
        loop.scheduler = SkillScheduler()
        loop.domain_repeat_cooldown = 2
        loop.recent_domains = []
        loop._blocked_domain_notices = set()
        loop.logger = None
        loop.progress_callback = None
        loop.learning_skill_engine = FakeLoopLearningSkillEngine()
        loop._session_verifiers = {}
        return loop

    @staticmethod
    def _make_runtime_loop(engine, assistant, recovery_engine=None, domain="browser") -> InfiniteTrainingLoop:
        loop = InfiniteTrainingLoop.__new__(InfiniteTrainingLoop)
        loop.base_dir = "."
        loop.assistant = assistant
        loop.learning_skill_engine = engine
        loop.scheduler = SkillScheduler()
        loop.recovery_engine = recovery_engine
        loop.logger = None
        loop.progress_callback = None
        loop.stop_checker = None
        loop.ui_target_ranker = type("Ranker", (), {"rank_candidates": lambda self, candidates, context=None: candidates})()
        loop.page_usefulness_classifier = type("Classifier", (), {"classify": lambda self, text: {"score": 0.0, "label": "unknown"}})()
        loop.history_path = None
        loop.dataset_path = None
        loop.session_history = []
        loop.mouse_attempts = 6
        loop.keyboard_attempts = 6
        loop.pause_seconds = 0
        loop.domain_repeat_cooldown = 0
        loop.recent_domains = []
        loop._blocked_domain_notices = set()
        loop._session_verifiers = {
            family: type("Verifier", (), {"verify": lambda self, result, family=family: {
                "verified": bool(result.evidence.get("current_session_verified")),
                "verified_outcome": {
                    "current_session_verified": bool(result.evidence.get("current_session_verified")),
                    "verification_family": family,
                },
            }})()
            for family in ("keyboard", "browser", "file_manager", "documents", "application", "game")
        }
        loop._append_jsonl = lambda *args, **kwargs: None
        loop._build_domain_states = lambda: []
        loop._select_domain_state = lambda states, preferred_domain: type("State", (), {"domain": preferred_domain or domain})()
        return loop

    def test_skill_label_from_profile_handles_game_skill_with_canonical_entity(self):
        label = InfiniteTrainingLoop._skill_label_from_profile(
            "jugar_terraria",
            {"canonical_entity": "terraria"},
        )

        self.assertEqual(label, "jugar terraria")

    def test_skill_label_from_profile_handles_plain_skill_and_app_ids(self):
        self.assertEqual(
            InfiniteTrainingLoop._skill_label_from_profile("skill:investigar", {}),
            "investigar",
        )
        self.assertEqual(
            InfiniteTrainingLoop._skill_label_from_profile("app:brave", {}),
            "brave",
        )

    def test_select_domain_state_skips_research_when_tesseract_is_missing(self):
        loop = self._make_loop()
        states = [
            DomainTrainingState("research", 1, 0.05, 0.0, 30.0, 1.0, 0.7),
            DomainTrainingState("browser", 3, 0.30, 0.0, 1.0, 0.9, 0.7),
        ]

        with patch("core.training_loop_infinite.tesseract_runtime_available", return_value=(False, "missing tesseract")):
            selected = loop._select_domain_state(states, None)

        self.assertEqual(selected.domain, "browser")

    def test_domain_has_selectable_scenario_skips_browser_when_no_internet(self):
        loop = self._make_loop()
        with patch.object(loop, "_internet_available", return_value=False):
            ready, reason = loop._domain_has_selectable_scenario("browser")

        self.assertFalse(ready)
        self.assertEqual(reason, "no hay escenarios disponibles sin internet")

    def test_select_domain_state_skips_browser_when_no_internet(self):
        loop = self._make_loop()
        states = [
            DomainTrainingState("browser", 1, 0.05, 0.0, 30.0, 1.0, 0.7),
            DomainTrainingState("document_editor", 2, 0.50, 0.0, 5.0, 0.8, 0.9),
        ]

        with patch.object(loop, "_internet_available", return_value=False):
            selected = loop._select_domain_state(states, None)

        self.assertEqual(selected.domain, "document_editor")

    def test_internet_available_uses_http_fallback_when_tcp_probe_fails(self):
        loop = self._make_loop()

        class DummyResponse:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, exc_type, exc_value, traceback):
                return False

            def getcode(self_inner):
                return 204

        with patch("core.training_loop_infinite.socket.create_connection", side_effect=OSError("blocked")):
            with patch("core.training_loop_infinite.urllib.request.urlopen", return_value=DummyResponse()):
                self.assertTrue(loop._internet_available())

    def test_internet_available_returns_false_when_all_checks_fail(self):
        loop = self._make_loop()

        with patch("core.training_loop_infinite.socket.create_connection", side_effect=OSError("blocked")):
            with patch("core.training_loop_infinite.urllib.request.urlopen", side_effect=Exception("offline")):
                self.assertFalse(loop._internet_available())

    def test_select_domain_state_rotates_away_from_recent_domain_when_possible(self):
        loop = self._make_loop()
        loop.recent_domains = ["research"]
        states = [
            DomainTrainingState("research", 1, 0.05, 0.0, 30.0, 1.0, 0.7),
            DomainTrainingState("browser", 3, 0.30, 0.0, 1.0, 0.9, 0.7),
            DomainTrainingState("vision/detection", 1, 1.0, 0.0, 30.0, 0.0, 0.4),
        ]

        with patch("core.training_loop_infinite.tesseract_runtime_available", return_value=(True, "")):
            selected = loop._select_domain_state(states, None)

        self.assertEqual(selected.domain, "browser")

    def test_select_domain_state_skips_domain_when_only_profile_is_blocked(self):
        loop = self._make_loop()
        loop.learning_skill_engine.state["profiles"] = {
            "skill:investigar": {
                "skill_id": "skill:investigar",
                "template_kind": "research_workflow",
                "state": "blocked",
                "supported": True,
            },
            "app:brave": {
                "skill_id": "app:brave",
                "template_kind": "browser_app",
                "state": "active",
                "supported": True,
            },
        }
        states = [
            DomainTrainingState("research", 1, 0.05, 0.0, 30.0, 1.0, 0.7),
            DomainTrainingState("browser", 3, 0.30, 0.0, 1.0, 0.9, 0.7),
        ]

        with patch("core.training_loop_infinite.tesseract_runtime_available", return_value=(True, "")):
            selected = loop._select_domain_state(states, None)

        self.assertEqual(selected.domain, "browser")

    def test_domain_has_selectable_document_editor_skill_when_word_is_blocked(self):
        loop = self._make_loop()
        loop.learning_skill_engine.state["profiles"] = {
            "app:word": {
                "skill_id": "app:word",
                "template_kind": "document_editor",
                "state": "blocked",
                "supported": True,
                "canonical_entity": "word",
            }
        }

        ready, reason = loop._domain_has_selectable_skill("document_editor")

        self.assertTrue(ready)
        self.assertEqual(reason, "")

    def test_domain_has_selectable_file_manager_skill_when_explorer_is_blocked(self):
        loop = self._make_loop()
        loop.learning_skill_engine.state["profiles"] = {
            "app:explorer": {
                "skill_id": "app:explorer",
                "template_kind": "file_manager",
                "state": "blocked",
                "supported": True,
                "canonical_entity": "explorer",
            }
        }

        ready, reason = loop._domain_has_selectable_skill("file_manager/explorer")

        self.assertTrue(ready)
        self.assertEqual(reason, "")

    def test_select_skill_has_perception_fallback_for_visualizacion(self):
        loop = self._make_loop()

        skill_id, skill_label, profile = loop._select_skill("perception", None)

        self.assertEqual(skill_id, "skill:visualizacion")
        self.assertEqual(skill_label, "visualizacion")
        self.assertEqual(profile.get("template_kind"), "visual_perception")

    def test_run_one_cycle_accepts_perception_domain_without_keyerror(self):
        engine = FakeLoopLearningSkillEngine()
        engine.state["profiles"]["skill:visualizacion"] = {
            "skill_id": "skill:visualizacion",
            "template_kind": "visual_perception",
            "state": "active",
            "supported": True,
            "canonical_entity": "visualizacion",
            "exponential_level": 0,
        }
        assistant = FakeLoopAssistant(practice_hook=lambda **_: "visual practice ok")
        loop = self._make_runtime_loop(engine, assistant, domain="perception")

        result = loop.run_one_cycle(
            preferred_domain="perception",
            forced_scenario={
                "scenario_id": "visual_context_identity",
                "runner": "practice_skill",
                "family": "perception",
            },
            forced_skill_id="skill:visualizacion",
        )

        self.assertEqual(result.domain, "perception")
        self.assertEqual(result.skill_id, "skill:visualizacion")
        self.assertEqual(result.scenario_id, "visual_context_identity")

    def test_run_one_cycle_accepts_keyboard_domain(self):
        engine = FakeLoopLearningSkillEngine()
        engine.state["profiles"]["skill:teclado"] = {
            "skill_id": "skill:teclado",
            "template_kind": "keyboard",
            "state": "active",
            "supported": True,
            "canonical_entity": "teclado",
            "exponential_level": 0,
        }
        assistant = FakeLoopAssistant(practice_hook=lambda **_: "teclado practice ok")
        loop = self._make_runtime_loop(engine, assistant, domain="keyboard")

        result = loop.run_one_cycle(
            preferred_domain="keyboard",
            forced_scenario={
                "scenario_id": "keyboard_text_entry",
                "runner": "practice_skill",
                "family": "keyboard",
            },
            forced_skill_id="skill:teclado",
        )

        self.assertEqual(result.domain, "keyboard")
        self.assertEqual(result.skill_id, "skill:teclado")
        self.assertEqual(result.scenario_id, "keyboard_text_entry")

    def test_run_one_cycle_does_not_reuse_old_history_when_no_fresh_session_exists(self):
        engine = FakeLoopLearningSkillEngine()
        engine.state["profiles"]["app:brave"] = {
            "skill_id": "app:brave",
            "template_kind": "browser_app",
            "state": "active",
            "supported": True,
            "canonical_entity": "brave",
            "exponential_level": 0,
        }
        engine.add_history(
            "app:brave",
            TrainingScenarioResult(
                skill_id="app:brave",
                domain="browser",
                scenario_id="browser_open_google",
                session_id="old_success",
                timestamp=1,
                level=1,
                status="success",
                verified=True,
                metrics={"origin": "history"},
                evidence={"raw_result": "old"},
                verified_outcome={"verified": True},
            ),
        )
        assistant = FakeLoopAssistant(practice_hook=lambda **_: "error: browser no abrio correctamente")
        loop = self._make_runtime_loop(engine, assistant, domain="browser")

        result = loop.run_one_cycle(
            preferred_domain="browser",
            forced_scenario={"scenario_id": "browser_search_result", "runner": "practice_skill", "family": "browser"},
            forced_skill_id="app:brave",
        )

        self.assertNotEqual(result.session_id, "old_success")
        self.assertEqual(result.scenario_id, "browser_search_result")
        self.assertEqual(result.status, "failure")
        self.assertFalse(result.verified)
        self.assertEqual(result.evidence.get("verification_source"), "synthetic_result")

    def test_run_one_cycle_uses_fresh_current_session_candidate_and_respects_target_level(self):
        engine = FakeLoopLearningSkillEngine()
        engine.state["profiles"]["app:brave"] = {
            "skill_id": "app:brave",
            "template_kind": "browser_app",
            "state": "active",
            "supported": True,
            "canonical_entity": "brave",
            "exponential_level": 1,
        }

        def practice_hook(**kwargs):
            engine.add_history(
                "app:brave",
                TrainingScenarioResult(
                    skill_id="app:brave",
                    domain="browser",
                    scenario_id="browser_search_result",
                    session_id="fresh_browser",
                    timestamp=2,
                    level=1,
                    status="success",
                    verified=True,
                    metrics={"from_history": True},
                    evidence={},
                    verified_outcome={"verified": True},
                ),
            )
            return "browser ok"

        assistant = FakeLoopAssistant(practice_hook=practice_hook)
        loop = self._make_runtime_loop(engine, assistant, domain="browser")

        result = loop.run_one_cycle(
            preferred_domain="browser",
            forced_scenario={
                "scenario_id": "browser_navigation__browser_search_result",
                "base_scenario_id": "browser_search_result",
                "family": "browser",
                "runner": "practice_skill",
                "training_goal": "buscar resultado visible",
                "target_level": 4,
            },
            forced_skill_id="app:brave",
        )

        self.assertEqual(result.session_id, "fresh_browser")
        self.assertEqual(result.scenario_id, "browser_navigation__browser_search_result")
        self.assertEqual(result.level, 4)
        self.assertTrue(result.verified)
        self.assertEqual(result.evidence.get("base_scenario_id"), "browser_search_result")
        self.assertEqual(assistant.calls[0][2], "buscar resultado visible")

    def test_run_one_cycle_uses_scenario_skill_label_for_document_editor(self):
        engine = FakeLoopLearningSkillEngine()
        engine.state["profiles"]["app:word"] = {
            "skill_id": "app:word",
            "template_kind": "document_editor",
            "state": "blocked",
            "supported": True,
            "canonical_entity": "word",
            "exponential_level": 0,
        }
        assistant = FakeLoopAssistant(practice_hook=lambda **_: "documento practicado")
        loop = self._make_runtime_loop(engine, assistant, domain="document_editor")

        result = loop.run_one_cycle(
            preferred_domain="document_editor",
            forced_scenario={"scenario_id": "document_write_basic", "family": "documents"},
        )

        self.assertEqual(assistant.calls[0][0], "practice_skill")
        self.assertEqual(assistant.calls[0][1], "notepad")
        self.assertEqual(result.skill_id, "app:notepad")
        self.assertEqual(result.scenario_id, "document_write_basic")

    def test_recovery_runs_when_status_is_success_but_verification_fails(self):
        class ResearchVerifier:
            def __init__(self):
                self.calls = 0

            def verify(self, result):
                self.calls += 1
                useful_sources = int(result.evidence.get("useful_source_count", 0) or 0)
                return {
                    "single_source_verified": useful_sources >= 1,
                    "verified_outcome": {"useful_source_count": useful_sources},
                }

        engine = FakeLoopLearningSkillEngine()
        engine.research_verifier = ResearchVerifier()
        engine.state["profiles"]["skill:investigar"] = {
            "skill_id": "skill:investigar",
            "template_kind": "research_workflow",
            "state": "active",
            "supported": True,
            "canonical_entity": "investigar",
            "exponential_level": 0,
        }
        attempt_counter = {"count": 0}

        def practice_hook(**kwargs):
            attempt_counter["count"] += 1
            useful_sources = 0 if attempt_counter["count"] == 1 else 1
            engine.add_history(
                "skill:investigar",
                TrainingScenarioResult(
                    skill_id="skill:investigar",
                    domain="research",
                    scenario_id="research_single_source",
                    session_id=f"research_{attempt_counter['count']}",
                    timestamp=attempt_counter["count"],
                    level=1,
                    status="success",
                    verified=True,
                    metrics={},
                    evidence={"useful_source_count": useful_sources},
                    verified_outcome={"verified": True},
                ),
            )
            return "investigacion completada"

        recovery = FakeRecoveryEngine()
        assistant = FakeLoopAssistant(practice_hook=practice_hook)
        loop = self._make_runtime_loop(engine, assistant, recovery_engine=recovery, domain="research")

        result = loop.run_one_cycle(
            preferred_domain="research",
            forced_scenario={"scenario_id": "research_single_source", "runner": "practice_skill", "family": "research"},
            forced_skill_id="skill:investigar",
        )

        self.assertTrue(recovery.called)
        self.assertTrue(result.verified)
        self.assertEqual(result.status, "success_with_fallback")
        self.assertEqual(result.fallback_used, "retry_alt")

    def test_select_scenario_resolves_forced_scenario_template_and_runner(self):
        loop = self._make_loop()

        scenario = loop._select_scenario(
            "research",
            0,
            {
                "scenario_id": "custom__research_cross_verify",
                "base_scenario_id": "research_cross_verify",
                "family": "research",
                "target_level": 4,
            },
        )

        self.assertEqual(scenario["scenario_id"], "custom__research_cross_verify")
        self.assertEqual(scenario["runner"], "practice_skill")
        self.assertTrue(scenario["create_document"])
        self.assertEqual(scenario["base_scenario_id"], "research_cross_verify")

    def test_missing_verifier_fails_closed_when_rules_exist(self):
        engine = FakeLoopLearningSkillEngine()
        engine.state["profiles"]["app:brave"] = {
            "skill_id": "app:brave",
            "template_kind": "browser_app",
            "state": "active",
            "supported": True,
            "canonical_entity": "brave",
            "exponential_level": 0,
        }
        assistant = FakeLoopAssistant(practice_hook=lambda **_: "ejecucion sin evidencia fresca")
        loop = self._make_runtime_loop(engine, assistant, domain="browser")

        result = loop.run_one_cycle(
            preferred_domain="browser",
            forced_scenario={
                "scenario_id": "mystery__scenario",
                "base_scenario_id": "browser_search_result",
                "family": "unknown_family",
                "runner": "practice_skill",
                "verification_rules": {"requires_magic_proof": True},
            },
            forced_skill_id="app:brave",
        )

        self.assertFalse(result.verified)
        self.assertEqual(result.failure_stage, "verification_missing")
        self.assertTrue(result.verified_outcome.get("verification_missing"))

    def test_gate_contract_covers_required_scenarios(self):
        available = {item["scenario_id"] for values in InfiniteTrainingLoop.DOMAIN_SCENARIOS.values() for item in values}

        for gate in RESEARCH_GATES.values():
            for required in gate.required_scenarios:
                self.assertIn(required, available)

        for gate in DESKTOP_FIRST_GATES.values():
            for required in gate.required_scenarios:
                self.assertTrue(required in available or required in DESKTOP_SCENARIO_EQUIVALENTS)


if __name__ == "__main__":
    unittest.main()
