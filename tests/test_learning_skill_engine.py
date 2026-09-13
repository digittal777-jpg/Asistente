from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from core.learning_skill_engine import LearningSkillEngine
from core.perception import PerceptionEngine
from core.training_models import TrainingScenarioResult


class FakeConfig:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def get(self, key, default=None):
        if key == "learning_skills":
            return {
                "max_cycles_per_session": 3,
                "max_attempts_per_cycle": 20,
                "max_minutes_per_cycle": 10,
                "blocked_after_failed_sessions": 3,
                "gates": {
                    "1_to_2": {"success_rate": 0.85, "verified_count": 20},
                    "2_to_3": {"success_rate": 0.75, "workflow_successes": 10},
                },
                "keyboard": {"default_attempts_level_1": 8},
                "youtube": {"default_attempts_level_1": 6},
                "research": {
                    "default_attempts_level_1": 4,
                    "default_result_count": 3,
                    "query_variants": [
                        "{topic}",
                        "{topic} guia",
                        "{topic} overview",
                    ],
                },
                "visualization": {
                    "default_attempts_level_1": 2,
                    "default_attempts_level_2": 2,
                    "default_attempts_level_3": 2,
                    "default_attempts_level_4": 2,
                    "default_attempts_level_5": 2,
                    "observation_pause_seconds": 0.0,
                },
                "browser_app": {"default_attempts_level_1": 2},
                "document_editor": {"default_attempts_level_1": 2},
                "site_workflow": {"default_attempts_level_1": 2},
                "window_management": {
                    "default_attempts_level_1": 1,
                    "workflow_attempts_per_run": 3,
                },
            }
        if key == "applications":
            return {
                "notepad": {"aliases": ["bloc de notas", "bloc"]},
                "word": {"aliases": ["microsoft word"]},
                "brave": {"aliases": ["brave browser"]},
                "explorer": {"aliases": ["explorador", "explorador de archivos"]},
            }
        if key == "url_aliases":
            return {
                "google": "https://www.google.com",
                "youtube": "https://www.youtube.com",
            }
        return default


class FakeMemory:
    def __init__(self) -> None:
        self.step_logs = []
        self.tasks = []
        self.updates = []

    def record_task_plan(self, original_command, intent, plan):
        self.tasks.append((original_command, intent, plan))
        return len(self.tasks)

    def update_task_run(self, task_id, status, result_summary):
        self.updates.append((task_id, status, result_summary))

    def record_step_log(self, task_intent, step_name, status, detail):
        self.step_logs.append((task_intent, step_name, status, detail))


class FakeLearning:
    def preferred_strategy(self, _domain, candidates):
        return candidates[0] if candidates else None

    def record_strategy_result(self, _domain, _strategy, _success):
        return None


class FakeAutomation:
    def __init__(self):
        self.press_calls = []
        self.hotkeys = []
        self.last_written = ""
        self.active_title = "Bloc de notas"
        self.window_titles = [self.active_title]

    def write_text(self, _text, interval=0.01, use_clipboard=False):
        self.last_written = _text
        return "ok"

    def hotkey(self, *_keys):
        self.hotkeys.append(_keys)
        return "ok"

    def capture_selected_text(self, select_all=True, select_all_shortcut=("ctrl", "a")):
        if select_all:
            self.hotkeys.append(tuple(select_all_shortcut))
        return self.last_written or "texto verificado"

    def press_keys(self, _keys):
        self.press_calls.append(tuple(_keys))
        return "ok"

    def open_file_select(self, _path):
        return "ok"

    def get_active_window_title(self):
        return self.active_title

    def list_windows(self):
        return list(self.window_titles)

    def move_mouse(self, *_args, **_kwargs):
        return "ok"

    def click(self, *_args, **_kwargs):
        return "ok"

    def alt_tab(self, repeats=1, delay=0.25):
        self.hotkeys.append(("alt", "tab"))
        return "ok"


class FakeElement:
    def __init__(self, name, x=400, y=250):
        self.name = name
        self.x = x
        self.y = y
        self.width = 120
        self.height = 40
        self.confidence = 0.9


class FakeWindow:
    def __init__(self, title, app_name, site_hint=None, is_active=True):
        self.title = title
        self.app_name = app_name
        self.site_hint = site_hint
        self.is_active = is_active


class FakeSnapshot:
    def __init__(self, active_window="Bloc de notas", active_app="notepad", active_site="", elements=None, ocr_excerpt=""):
        self.active_window = active_window
        self.active_app = active_app
        self.active_site = active_site
        self.ocr_excerpt = ocr_excerpt
        self.windows = [FakeWindow(active_window, active_app, active_site, True)]
        self.elements = list(elements or [])


class FakeVision:
    @staticmethod
    def find_ui_element(name, snapshot=None):
        current = snapshot
        if current:
            for element in getattr(current, "elements", []):
                if getattr(element, "name", "") == name:
                    return element
        return FakeElement(name)


class FakeTaskExecutor:
    def __init__(self):
        self.opened_result_indices = []

    def run_search_flow(self, destination, query, browser=None, private=False):
        return f"Busqueda autonoma enviada a {destination}: {query}"

    def _open_google_result(self, index):
        self.opened_result_indices.append(index)
        return True

    def collect_page_text(self, max_scrolls_per_page=1):
        return "texto util de investigacion " * 12

    @staticmethod
    def _looks_unhelpful(text):
        return len(str(text).strip()) < 120

    @staticmethod
    def _merge_texts(chunks):
        return "\n".join(str(item) for item in chunks if str(item).strip())

    def perform_research(self, topic, browser, result_count=3):
        return {
            "topic": topic,
            "reviewed_sources": ["Fuente 1", "Fuente 2"],
            "useful_sources": [{"index": 1}, {"index": 2}],
            "useful_source_count": 2,
            "merged_text": "texto util " * 30,
            "summary": "Resumen util de investigacion",
            "findings": "Hallazgos utiles",
        }


class FakeAssistant:
    class FakePlanner:
        @staticmethod
        def summarize_text(text, max_sentences=5):
            return text[:80]

    def __init__(self) -> None:
        self.task_planner = self.FakePlanner()
        self.open_calls = []
        self.browser_calls = []
        self.focus_calls = []
        self.folder_calls = []
        self.vision = FakeVision()
        self._snapshot = FakeSnapshot(elements=[FakeElement("document_body")])
        self.perception = PerceptionEngine(self)
        self.desktop_learning_organizer = None

    def open_application(self, target, extra_args=None):
        self.open_calls.append((target, extra_args or []))
        normalized = str(target).lower()
        active_site = ""
        if normalized in {"brave", "chrome", "edge", "firefox"}:
            active_site = "google"
        self._snapshot = FakeSnapshot(
            active_window=str(target).title(),
            active_app=normalized,
            active_site=active_site,
            elements=[
                FakeElement("document_body"),
                FakeElement("browser_address_bar"),
                FakeElement("google_search_bar"),
                FakeElement("google_results_search_bar"),
                FakeElement("google_result_card_1"),
                FakeElement("youtube_search_bar"),
                FakeElement("youtube_search_button"),
            ],
        )
        return f"opened {target}"

    def ensure_browser(self, browser=None, site=None, private=False):
        self.browser_calls.append((browser, site, private))
        active_site = site or ""
        self._snapshot = FakeSnapshot(
            active_window=str(browser).title(),
            active_app=str(browser or "brave"),
            active_site=active_site,
            elements=[
                FakeElement("browser_address_bar"),
                FakeElement("google_search_bar"),
                FakeElement("google_results_search_bar"),
                FakeElement("google_result_card_1"),
                FakeElement("youtube_search_bar"),
                FakeElement("youtube_search_button"),
            ],
        )
        return f"browser {browser}"

    def open_folder(self, target):
        self.folder_calls.append(target)
        self._snapshot = FakeSnapshot(active_window=str(target), active_app="explorer", active_site="", elements=[])
        return f"folder {target}"

    def focus_window(self, title):
        self.focus_calls.append(title)
        self._snapshot.active_window = title
        return f"focus {title}"

    def get_latest_vision_snapshot(self, refresh=False):
        return self._snapshot

    def get_latest_snapshot(self, refresh=False):
        return self.get_latest_vision_snapshot(refresh=refresh)

    def get_latest_perception(self, refresh=False):
        return self.perception.observe(refresh=refresh)

    def create_document(self, application, title, content=None, filename=None, use_last_summary=False):
        return f"Documento preparado y guardado en: {title}.docx"


class FakeMouseLearningOrganizer:
    def __init__(self, strategy_path: Path) -> None:
        self.strategy_path = strategy_path
        self.calls = []
        self.counter = 0

    def practice_mouse_movement(self, attempts=None):
        return self._record("movement", attempts)

    def practice_mouse_click(self, attempts=None):
        return self._record("click", attempts)

    def practice_mouse_double_click(self, attempts=None):
        return self._record("double_click", attempts)

    def practice_mouse_right_click(self, attempts=None):
        return self._record("right_click", attempts)

    def practice_mouse_selection(self, attempts=None):
        return self._record("selection", attempts)

    def practice_mouse_detection(self, attempts=None):
        return self._record("detection", attempts)

    def practice_mouse_workflow(self, attempts=None):
        return self._record("workflow", attempts)

    def practice_mouse(self, attempts=None):
        return self._record("drag", attempts)

    def _record(self, key, attempts):
        self.counter += 1
        attempts = max(1, int(attempts or 3))
        self.calls.append((key, attempts))
        payload = {}
        if self.strategy_path.exists():
            payload = json.loads(self.strategy_path.read_text(encoding="utf-8"))
        practice = payload.setdefault("practice", {})
        session_id = f"{key}_{self.counter}"
        if key == "drag":
            practice.update(
                {
                    "last_session_id": session_id,
                    "attempts": attempts,
                    "successes": attempts,
                    "failures": 0,
                    "success_rate": 1.0,
                    "real_drag_enabled": True,
                }
            )
        else:
            practice[key] = {
                "last_session_id": session_id,
                "attempts": attempts,
                "successes": attempts,
                "failures": 0,
                "success_rate": 1.0,
                "reliable": True,
            }
        payload.setdefault("profiles", {})["upper_list_row"] = {
            "successes": 3,
            "failures": 0,
        }
        if key == "workflow":
            payload.setdefault("categories", {})["PracticaFlujoSeguro"] = {
                "successes": attempts,
                "failures": 0,
            }
            window_management = payload.setdefault("window_management", {})
            window_management["strict_split_enabled"] = True
            window_management["repair_attempts"] = int(window_management.get("repair_attempts", 0) or 0) + attempts
            window_management["repair_successes"] = int(window_management.get("repair_successes", 0) or 0) + attempts
            window_management["repair_failures"] = int(window_management.get("repair_failures", 0) or 0)
            window_management["source_occlusion_failures"] = int(
                window_management.get("source_occlusion_failures", 0) or 0
            )
            window_management["successful_split_layouts"] = int(
                window_management.get("successful_split_layouts", 0) or 0
            ) + attempts
            window_management["last_result"] = "success"
        self.strategy_path.parent.mkdir(parents=True, exist_ok=True)
        self.strategy_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return f"Practica {key} completada. Manifiesto: fake.json"


class FakeLogger:
    def info(self, _message):
        return None

    def warning(self, _message):
        return None

    def exception(self, _message):
        return None


class StubLearningSkillEngine(LearningSkillEngine):
    def __init__(self, *args, queued_cycles=None, **kwargs):
        self.queued_cycles = list(queued_cycles or [])
        super().__init__(*args, **kwargs)

    def _execute_supported_cycle(
        self,
        skill_id,
        level,
        mode,
        goal,
        requested_attempts,
        requested_minutes,
        create_document,
        cycle_number,
    ):
        if self.queued_cycles:
            cycle = dict(self.queued_cycles.pop(0))
            cycle.setdefault("cycle_number", cycle_number)
            cycle.setdefault("level", level)
            cycle.setdefault("attempt_budget", requested_attempts)
            cycle.setdefault("time_budget_minutes", requested_minutes)
            cycle.setdefault("status", "completed")
            cycle.setdefault("steps", [])
            cycle.setdefault("strategies_tried", [])
            cycle.setdefault("verifications", [])
            cycle.setdefault("summary", "ciclo stub")
            return cycle
        return super()._execute_supported_cycle(
            skill_id=skill_id,
            level=level,
            mode=mode,
            goal=goal,
            requested_attempts=requested_attempts,
            requested_minutes=requested_minutes,
            create_document=create_document,
            cycle_number=cycle_number,
        )


class LearningSkillEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base_dir = Path(self.temp_dir.name)
        self.engine = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=FakeAutomation(),
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=FakeAssistant(),
            logger=FakeLogger(),
            queued_cycles=[],
        )

    def test_creates_supported_profile(self):
        self.engine.queued_cycles = [
            {"successes": 5, "failures": 0, "verified_successes": 5, "workflow_successes": 0}
        ]
        self.engine.learn_skill("teclado")
        profile = self.engine.state["profiles"]["skill:teclado"]
        self.assertEqual(profile["skill_id"], "skill:teclado")
        self.assertTrue(self.engine.profiles_path.exists())

    def test_bootstrap_starter_profiles_does_not_grant_verified_credit(self):
        result = self.engine.bootstrap_starter_profiles(["visualizacion", "youtube"])

        self.assertIn("sin subir niveles", result)
        youtube = self.engine.state["profiles"]["skill:youtube"]
        visual = self.engine.state["profiles"]["skill:visualizacion"]
        self.assertEqual(youtube["current_level"], 1)
        self.assertEqual(youtube["highest_verified_level"], 0)
        self.assertFalse(youtube["real_usage_ready"])
        self.assertEqual(youtube["level_metrics"]["1"]["verified_count"], 0)
        self.assertTrue(youtube["starter_bootstrap"]["scenario_templates"])
        self.assertTrue(youtube["trainable_draft"]["scenario_templates"])
        self.assertIn("No suma exitos", youtube["starter_bootstrap"]["credit_policy"])
        self.assertEqual(visual["level_metrics"]["1"]["verified_count"], 0)
        self.assertEqual(visual["starter_bootstrap"]["coach_focus"], "ver primero, actuar despues")

    def test_unsupported_skill_creates_draft_profile(self):
        result = self.engine.learn_skill("teletransportacion cuantica")
        self.assertIn("draft", result.lower())
        profile = self.engine.state["profiles"]["teletransportacion_cuantica"]
        self.assertEqual(profile["state"], "draft")
        self.assertFalse(profile["supported"])
        self.assertIn("trainable_draft", profile)
        self.assertTrue(profile["trainable_draft"]["scenario_templates"])

    def test_unsupported_skill_uses_direct_discovery_when_investigar_is_blocked(self):
        self.engine.state["profiles"]["skill:investigar"] = self.engine._default_profile(
            skill_id="skill:investigar",
            display_name="Investigar",
            family="cognitive_workflow",
            supported=True,
            template_kind="research_workflow",
            canonical_entity="investigar",
        )
        self.engine.state["profiles"]["skill:investigar"]["state"] = "blocked"

        result = self.engine.learn_skill("teletransportacion cuantica")

        self.assertIn("draft", result.lower())
        profile = self.engine.state["profiles"]["teletransportacion_cuantica"]
        draft = profile["trainable_draft"]
        self.assertTrue(draft.get("knowledge_assets"))
        self.assertTrue(draft.get("research_queries"))
        self.assertIn("skill:investigar esta bloqueada", profile["last_investigation_summary"])

    def test_unsupported_skill_still_creates_draft_when_direct_discovery_fails(self):
        class FailingResearchExecutor(FakeTaskExecutor):
            def perform_research(self, topic, browser, result_count=3):
                raise RuntimeError("research down")

        self.engine.task_executor = FailingResearchExecutor()

        result = self.engine.learn_skill("teletransportacion cuantica")

        self.assertIn("draft", result.lower())
        profile = self.engine.state["profiles"]["teletransportacion_cuantica"]
        self.assertEqual(profile["state"], "draft")
        self.assertFalse(profile["trainable_draft"].get("knowledge_assets"))

    def test_game_skill_uses_foundation_training_profile(self):
        self.engine.queued_cycles = [
            {"successes": 8, "failures": 0, "verified_successes": 8, "workflow_successes": 2}
        ]
        result = self.engine.learn_skill("jugar terraria")
        self.assertIn("Jugar Terraria", result)
        profile = self.engine.state["profiles"]["jugar_terraria"]
        self.assertEqual(profile["state"], "active")
        self.assertTrue(profile["supported"])
        self.assertEqual(profile["template_kind"], "game_foundation")
        self.assertEqual(profile["canonical_entity"], "terraria")

    def test_unsupported_skill_practice_activates_generic_supported_runner(self):
        self.engine.queued_cycles = [
            {"successes": 3, "failures": 0, "verified_successes": 3, "workflow_successes": 1}
        ]

        result = self.engine.practice_skill(
            "nodejs_project_setup",
            goal="configurar proyecto node.js basico",
            requested_attempts=1,
        )

        profile = self.engine.state["profiles"]["nodejs_project_setup"]
        self.assertTrue(profile["supported"])
        self.assertEqual(profile["template_kind"], "document_editor")
        self.assertEqual(profile["canonical_entity"], "notepad")
        self.assertNotIn("Habilidad no soportada aun", result)

    def test_promotes_from_level_one_to_two_when_gate_passes(self):
        self.engine.queued_cycles = [
            {"successes": 20, "failures": 0, "verified_successes": 20, "workflow_successes": 0},
            {"successes": 0, "failures": 1, "verified_successes": 0, "workflow_successes": 0},
        ]
        self.engine.learn_skill("teclado")
        profile = self.engine.state["profiles"]["skill:teclado"]
        self.assertEqual(profile["current_level"], 2)
        self.assertTrue(profile["real_usage_ready"])

    def test_promotes_from_level_two_to_three_when_gate_passes(self):
        self.engine.state["profiles"]["skill:investigar"] = self.engine._default_profile(
            "skill:investigar",
            "Investigar",
            "cognitive_workflow",
            True,
            template_kind="research_workflow",
            canonical_entity="investigar",
        )
        self.engine.state["profiles"]["skill:investigar"]["current_level"] = 2
        self.engine.queued_cycles = [
            {"successes": 10, "failures": 0, "verified_successes": 10, "workflow_successes": 10},
            {"successes": 0, "failures": 1, "verified_successes": 0, "workflow_successes": 0},
        ]
        self.engine.learn_skill("investigar")
        profile = self.engine.state["profiles"]["skill:investigar"]
        self.assertEqual(profile["current_level"], 3)

    def test_blocks_profile_after_repeated_failed_sessions(self):
        for _ in range(3):
            self.engine.queued_cycles = [
                {"successes": 0, "failures": 5, "verified_successes": 0, "workflow_successes": 0},
                {"successes": 0, "failures": 5, "verified_successes": 0, "workflow_successes": 0},
                {"successes": 0, "failures": 5, "verified_successes": 0, "workflow_successes": 0},
            ]
            self.engine.learn_skill("youtube")
        profile = self.engine.state["profiles"]["skill:youtube"]
        self.assertEqual(profile["state"], "blocked")

    def test_skill_status_includes_current_level(self):
        self.engine.queued_cycles = [
            {"successes": 20, "failures": 0, "verified_successes": 20, "workflow_successes": 0},
            {"successes": 0, "failures": 1, "verified_successes": 0, "workflow_successes": 0},
        ]
        self.engine.learn_skill("teclado")
        status = self.engine.skill_status("teclado")
        self.assertIn("Nivel legado actual", status)
        self.assertIn("Nivel exponencial", status)
        self.assertIn("teclado", status.lower())

    def test_record_training_result_reevaluates_research_profile_to_exponential_level_one(self):
        profile = self.engine._ensure_profile(
            skill_id="skill:investigar",
            display_name="Investigar",
            family="cognitive_workflow",
            supported=True,
            template_kind="research_workflow",
            canonical_entity="investigar",
        )
        for idx in range(5):
            self.engine.record_training_result(
                TrainingScenarioResult(
                    skill_id="skill:investigar",
                    domain="research",
                    scenario_id="research_single_source",
                    session_id=f"research_{idx}",
                    timestamp=idx + 1,
                    level=0,
                    status="success",
                    verified=True,
                    metrics={"captured_chars": 800},
                    evidence={
                        "captured_chars": 800,
                        "useful_source_count": 1,
                        "current_session_verified": True,
                        "verification_source": "research_test",
                        "visible_text_chars": 800,
                    },
                    verified_outcome={"single_source_verified": True},
                )
            )
        self.assertGreaterEqual(profile["exponential_level"], 1)

    def test_research_manifest_preserves_summary_sources_and_document_path(self):
        payload = {
            "skill_id": "skill:investigar",
            "session_id": "research_manifest_1",
            "created_at": "2026-05-17T10:00:00",
            "cycles": [
                {
                    "level": 3,
                    "strategies_tried": ["goal_research_visible"],
                    "steps": [
                        {
                            "step": "research_goal_workflow",
                            "strategy": "goal_research_visible",
                            "verification": "sources_and_summary",
                            "success": True,
                            "captured_chars": 3200,
                            "useful_source_count": 3,
                            "discard_precision": 0.75,
                            "research_summary": "Resumen util para terraria early game",
                            "research_findings": "Hallazgo A. Hallazgo B.",
                            "queries_used": ["terraria controles basicos", "terraria early game"],
                            "visited_titles": ["Wiki", "Guia 1", "Foro 1"],
                            "discarded_titles": ["Spam"],
                            "discard_reasons": ["Contenido pobre"],
                            "document_result": "C:\\temp\\terraria_resumen.txt",
                            "evidence": {"verification_reason": "ok"},
                        }
                    ],
                }
            ],
        }

        results = self.engine._scenario_results_from_learning_manifest(payload)

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result.evidence["research_summary"], "Resumen util para terraria early game")
        self.assertEqual(result.evidence["document_path"], "C:\\temp\\terraria_resumen.txt")
        self.assertEqual(result.evidence["queries_used"][0], "terraria controles basicos")
        self.assertEqual(result.evidence["reviewed_sources"], ["Wiki", "Guia 1", "Foro 1"])
        self.assertGreater(result.metrics["discard_precision"], 0.7)
        self.assertGreaterEqual(result.metrics["useful_source_count"], 3)

    def test_research_manifest_reclassifies_untitled_single_source_success_as_noise(self):
        payload = {
            "skill_id": "skill:investigar",
            "session_id": "research_manifest_noise",
            "created_at": "2026-05-19T07:55:41",
            "cycles": [
                {
                    "level": 1,
                    "steps": [
                        {
                            "step": "research_query_attempt",
                            "strategy": "direct_typing",
                            "verification": "page_text_quality",
                            "query": "terraria crafting early game",
                            "page_title": "Sin título - Brave",
                            "captured_chars": 2400,
                            "success": True,
                            "evidence": {
                                "useful_source_count": 1,
                                "page_usefulness_label": "useful",
                                "current_session_verified": True,
                            },
                        }
                    ],
                }
            ],
        }

        results = self.engine._scenario_results_from_learning_manifest(payload)

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertFalse(result.verified)
        self.assertEqual(result.status, "failure")
        self.assertEqual(result.evidence["useful_source_count"], 0)
        self.assertIn("ambiguo", result.evidence["source_quality_reason"].lower())

    def test_dynamic_word_skill_is_supported(self):
        self.engine.queued_cycles = [
            {"successes": 1, "failures": 0, "verified_successes": 1, "workflow_successes": 0}
        ]
        self.engine.learn_skill("word")
        profile = self.engine.state["profiles"]["app:word"]
        self.assertTrue(profile["supported"])
        self.assertEqual(profile["template_kind"], "document_editor")
        self.assertNotEqual(profile["state"], "draft")

    def test_dynamic_brave_skill_is_supported(self):
        self.engine.queued_cycles = [
            {"successes": 1, "failures": 0, "verified_successes": 1, "workflow_successes": 0}
        ]
        self.engine.learn_skill("brave")
        profile = self.engine.state["profiles"]["app:brave"]
        self.assertTrue(profile["supported"])
        self.assertEqual(profile["template_kind"], "browser_app")

    def test_dynamic_window_management_skill_is_supported(self):
        self.engine.queued_cycles = [
            {"successes": 1, "failures": 0, "verified_successes": 1, "workflow_successes": 1}
        ]
        self.engine.learn_skill("acomodo de ventanas")
        profile = self.engine.state["profiles"]["skill:window_management"]
        self.assertTrue(profile["supported"])
        self.assertEqual(profile["template_kind"], "window_management")
        self.assertEqual(profile["canonical_entity"], "window_management")

    def test_visualizacion_skill_is_supported(self):
        assistant = FakeAssistant()
        assistant.ensure_browser(browser="brave", site="google")
        engine = LearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=FakeAutomation(),
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
        )

        result = engine.learn_skill("aprende visualizacion", requested_attempts=2)
        profile = engine.state["profiles"]["skill:visualizacion"]

        self.assertIn("Visualizacion nivel 1", result)
        self.assertTrue(profile["supported"])
        self.assertEqual(profile["template_kind"], "visual_perception")
        self.assertEqual(profile["canonical_entity"], "visualizacion")

    def test_mouse_skill_uses_desktop_training_backend(self):
        assistant = FakeAssistant()
        organizer = FakeMouseLearningOrganizer(self.base_dir / "data" / "desktop_mouse_strategy.json")
        assistant.desktop_learning_organizer = organizer
        engine = LearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=FakeAutomation(),
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
        )

        result = engine.learn_skill("mouse", requested_attempts=20)
        profile = engine.state["profiles"]["skill:mouse"]

        self.assertIn("entrenador de escritorio", result)
        self.assertEqual(profile["state"], "active")
        self.assertTrue(profile["real_usage_ready"])
        self.assertEqual(
            [name for name, _attempts in organizer.calls[:4]],
            ["movement", "click", "double_click", "right_click"],
        )
        self.assertNotIn("Habilidad soportada desconocida", "\n".join(profile["last_blockers"]))

    def test_window_management_skill_uses_desktop_workflow_backend(self):
        assistant = FakeAssistant()
        organizer = FakeMouseLearningOrganizer(self.base_dir / "data" / "desktop_mouse_strategy.json")
        assistant.desktop_learning_organizer = organizer
        engine = LearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=FakeAutomation(),
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
        )

        result = engine.learn_skill("window management", requested_attempts=1)
        profile = engine.state["profiles"]["skill:window_management"]
        status = engine.skill_status("window management")

        self.assertIn("Window management nivel 1", result)
        self.assertEqual(organizer.calls, [("workflow", 3)])
        self.assertEqual(profile["state"], "active")
        self.assertEqual(
            profile["preferred_strategies"].get("window_layout_mode"),
            "strict_split_explorer_halves",
        )
        self.assertIn("Nivel exponencial", status)

    def test_mouse_profile_sync_imports_infinite_training_metrics_once(self):
        assistant = FakeAssistant()
        organizer = FakeMouseLearningOrganizer(self.base_dir / "data" / "desktop_mouse_strategy.json")
        for method_name in (
            "practice_mouse_movement",
            "practice_mouse_click",
            "practice_mouse_double_click",
            "practice_mouse_right_click",
            "practice_mouse",
            "practice_mouse_detection",
            "practice_mouse_selection",
            "practice_mouse_workflow",
        ):
            getattr(organizer, method_name)(attempts=6)
        assistant.desktop_learning_organizer = organizer
        engine = LearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=FakeAutomation(),
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
        )

        result = engine.sync_mouse_profile_from_desktop_practice()
        profile = engine.state["profiles"]["skill:mouse"]
        second_result = engine.sync_mouse_profile_from_desktop_practice()

        self.assertIn("Perfil mouse sincronizado", result)
        self.assertEqual(profile["current_level"], 2)
        self.assertEqual(profile["level_metrics"]["1"]["verified_count"], 24)
        self.assertEqual(profile["level_metrics"]["2"]["workflow_successes"], 6)
        self.assertEqual(len(profile["input_training_synced_mouse_sessions"]), 5)
        self.assertEqual(profile["last_session_id"], "drag_5")
        self.assertIn("sin sesiones nuevas", second_result)
        self.assertEqual(profile["level_metrics"]["1"]["verified_count"], 24)

    def test_mouse_profile_sync_puts_new_advanced_sessions_on_current_level(self):
        assistant = FakeAssistant()
        organizer = FakeMouseLearningOrganizer(self.base_dir / "data" / "desktop_mouse_strategy.json")
        for method_name in (
            "practice_mouse_movement",
            "practice_mouse_click",
            "practice_mouse_double_click",
            "practice_mouse_right_click",
            "practice_mouse",
            "practice_mouse_detection",
            "practice_mouse_selection",
            "practice_mouse_workflow",
        ):
            getattr(organizer, method_name)(attempts=6)
        assistant.desktop_learning_organizer = organizer
        engine = LearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=FakeAutomation(),
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
        )

        engine.sync_mouse_profile_from_desktop_practice()
        organizer.practice_mouse(attempts=6)
        result = engine.sync_mouse_profile_from_desktop_practice()
        profile = engine.state["profiles"]["skill:mouse"]

        self.assertIn("1 sesion", result)
        self.assertEqual(profile["current_level"], 3)
        self.assertEqual(profile["level_metrics"]["2"]["workflow_successes"], 12)
        self.assertEqual(profile["last_session_id"], "drag_9")
        self.assertTrue(
            any(
                item.startswith("level2:drag:")
                for item in profile["input_training_synced_mouse_sessions"]
            )
        )

    def test_visual_profile_sync_imports_detection_selection_and_workflow_once(self):
        assistant = FakeAssistant()
        organizer = FakeMouseLearningOrganizer(self.base_dir / "data" / "desktop_mouse_strategy.json")
        for method_name in (
            "practice_mouse_movement",
            "practice_mouse_click",
            "practice_mouse_double_click",
            "practice_mouse_right_click",
            "practice_mouse",
            "practice_mouse_detection",
            "practice_mouse_selection",
            "practice_mouse_workflow",
        ):
            getattr(organizer, method_name)(attempts=6)
        assistant.desktop_learning_organizer = organizer
        engine = LearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=FakeAutomation(),
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
        )

        result = engine.sync_visual_profile_from_desktop_practice()
        profile = engine.state["profiles"]["skill:visualizacion"]
        second_result = engine.sync_visual_profile_from_desktop_practice()

        self.assertIn("Perfil visualizacion sincronizado", result)
        self.assertEqual(profile["current_level"], 1)
        self.assertEqual(profile["level_metrics"]["2"]["verified_count"], 6)
        self.assertEqual(profile["level_metrics"]["4"]["workflow_successes"], 6)
        self.assertEqual(profile["level_metrics"]["5"]["workflow_successes"], 6)
        self.assertEqual(len(profile["input_training_synced_visual_sessions"]), 3)
        self.assertEqual(profile["last_session_id"], "workflow_8")
        self.assertIn("sin sesiones nuevas", second_result)

    def test_window_management_profile_sync_imports_workflow_manifests_once(self):
        strategy_path = self.base_dir / "data" / "desktop_mouse_strategy.json"
        strategy_path.parent.mkdir(parents=True, exist_ok=True)
        strategy_path.write_text(
            json.dumps(
                {
                    "practice": {
                        "workflow": {
                            "last_session_id": "workflow_practice_20260518_161900",
                            "attempts": 6,
                            "successes": 6,
                            "failures": 0,
                            "success_rate": 1.0,
                            "reliable": True,
                        }
                    },
                    "window_management": {
                        "strict_split_enabled": True,
                        "repair_attempts": 24,
                        "repair_successes": 20,
                        "repair_failures": 4,
                        "source_occlusion_failures": 4,
                        "successful_split_layouts": 24,
                    },
                }
            ),
            encoding="utf-8",
        )
        session_dir = self.base_dir / "data" / "desktop_organizer_sessions"
        session_dir.mkdir(parents=True, exist_ok=True)
        for idx in range(20):
            payload = {
                "session_id": f"workflow_practice_20260518_16{idx:02d}00",
                "created_at": f"2026-05-18T16:{idx:02d}:00",
                "moves": [
                    {
                        "status": "completed",
                        "verified": True,
                        "details": {
                            "window_layout_mode": "strict_split_explorer_halves",
                            "window_layout_repair": {
                                "attempted": idx % 2 == 0,
                                "recovered": idx % 2 == 0,
                                "layout_mode": "strict_split_explorer_halves",
                            },
                        },
                    },
                    {
                        "status": "completed",
                        "verified": True,
                        "details": {
                            "window_layout_mode": "strict_split_explorer_halves",
                            "window_layout_repair": {},
                        },
                    },
                ],
            }
            (session_dir / f"{payload['session_id']}.json").write_text(
                json.dumps(payload, indent=2),
                encoding="utf-8",
            )

        engine = LearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=FakeAutomation(),
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=FakeAssistant(),
            logger=FakeLogger(),
        )

        result = engine.sync_window_management_profile_from_desktop_practice()
        profile = engine.state["profiles"]["skill:window_management"]
        second_result = engine.sync_window_management_profile_from_desktop_practice()

        self.assertIn("Perfil window management sincronizado", result)
        self.assertEqual(profile["current_level"], 2)
        self.assertEqual(profile["level_metrics"]["1"]["verified_count"], 20)
        self.assertEqual(profile["level_metrics"]["1"]["workflow_successes"], 20)
        self.assertEqual(len(profile["input_training_synced_window_management_sessions"]), 20)
        self.assertEqual(profile["last_session_id"], "workflow_practice_20260518_161900")
        self.assertIn("sin sesiones nuevas", second_result)

    def test_default_mouse_profile_has_five_levels_and_gates(self):
        profile = self.engine._default_profile(
            skill_id="skill:mouse",
            display_name="Usar raton",
            family="motor_ui",
            supported=True,
            template_kind="mouse_control",
            canonical_entity="mouse",
        )

        self.assertEqual(profile["max_level"], 5)
        self.assertIn("5", profile["level_metrics"])
        self.assertIn("4_to_5", profile["gates"])

    def test_mouse_profile_migrates_stale_draft_import(self):
        profiles_path = self.base_dir / "data" / "learning_skill_profiles.json"
        profiles_path.parent.mkdir(parents=True, exist_ok=True)
        profiles_path.write_text(
            json.dumps(
                {
                    "version": 2,
                    "profiles": {
                        "skill:mouse": {
                            "skill_id": "skill:mouse",
                            "display_name": "Usar raton",
                            "family": "motor_ui",
                            "template_kind": "mouse_control",
                            "canonical_entity": "mouse",
                            "state": "draft",
                            "supported": True,
                            "current_level": 1,
                            "highest_verified_level": 1,
                            "real_usage_ready": False,
                            "level_metrics": {
                                "1": {
                                    "successes": 562,
                                    "failures": 1336,
                                    "verified_count": 562,
                                    "workflow_successes": 0,
                                    "sessions": 1,
                                    "success_rate": 0.2961,
                                    "last_cycle_summary": "Mouse nivel 1: Datos historicos consolidados",
                                },
                                "2": self.engine._empty_metrics(),
                                "3": self.engine._empty_metrics(),
                            },
                            "gates": self.engine._default_gates(),
                            "preferred_strategies": {},
                            "last_blockers": ["Habilidad soportada desconocida: skill:mouse"],
                            "verification_version": 3,
                            "profile_schema_version": 2,
                        }
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        engine = LearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=FakeAutomation(),
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=FakeAssistant(),
            logger=FakeLogger(),
        )
        profile = engine.state["profiles"]["skill:mouse"]

        self.assertEqual(profile["state"], "active")
        self.assertEqual(profile["last_blockers"], [])
        self.assertTrue(profile["legacy_mouse_metrics_migrated"])
        self.assertEqual(profile["level_metrics"]["1"]["successes"], 0)

    def test_browser_navigation_uses_address_bar_shortcut(self):
        assistant = FakeAssistant()

        class BrowserAutomation(FakeAutomation):
            def __init__(self):
                super().__init__()
                self.active_title = "Brave"

            def press_keys(self, keys):
                result = super().press_keys(keys)
                if keys == ["enter"]:
                    assistant._snapshot = FakeSnapshot(
                        active_window="Google - Brave",
                        active_app="brave",
                        active_site="google",
                        elements=[FakeElement("browser_address_bar")],
                    )
                    self.active_title = "Google - Brave"
                return result

        automation = BrowserAutomation()
        engine = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=automation,
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
            queued_cycles=[],
        )

        success, detail = engine._visible_address_navigation("brave", "google.com", "google", "brave_open_google")

        self.assertTrue(success)
        self.assertIn(("ctrl", "l"), automation.hotkeys)
        self.assertEqual("browser_address_bar_shortcut", detail["evidence"]["target_control_used"])

    def test_google_homepage_hint_is_not_search_success(self):
        self.assertFalse(
            self.engine._google_results_context_matches_query(
                {"window_title": "Google - Brave", "active_site": "google"},
                "Rimuru Tempest",
            )
        )
        self.assertTrue(
            self.engine._google_results_context_matches_query(
                {"window_title": "Rimuru Tempest - Buscar con Google - Brave", "active_site": "google"},
                "Rimuru Tempest",
            )
        )

    def test_google_search_prefers_current_tab_before_fresh_tab(self):
        order = []

        def current_tab(**_kwargs):
            order.append("reuse")
            return True, {
                "step": "google_search",
                "strategy": "visible_google_search",
                "verification": "visible_google_results",
                "success": True,
                "context_failure": "",
                "evidence": {"rescue_used": False},
            }

        def fresh_tab(**_kwargs):
            order.append("fresh")
            return True, {
                "step": "google_search",
                "strategy": "fresh_tab_google_search",
                "verification": "visible_google_results",
                "success": True,
                "context_failure": "",
                "evidence": {"rescue_used": True},
            }

        self.engine._visible_google_search_in_current_tab = current_tab
        self.engine._visible_google_search_via_new_tab = fresh_tab

        success, detail = self.engine._visible_google_search("Rimuru Tempest", "brave", "google_search")

        self.assertTrue(success)
        self.assertEqual(["reuse"], order)
        self.assertEqual("visible_google_search", detail["strategy"])

    def test_google_search_falls_back_to_fresh_tab_after_reuse_failure(self):
        order = []

        def current_tab(**_kwargs):
            order.append("reuse")
            return False, {
                "step": "google_search",
                "strategy": "visible_google_search",
                "verification": "visible_google_results",
                "success": False,
                "context_failure": "No pude reutilizar la pestana actual.",
                "evidence": {"rescue_used": False},
            }

        def fresh_tab(**_kwargs):
            order.append("fresh")
            return True, {
                "step": "google_search",
                "strategy": "direct_typing+fresh_tab_search_url",
                "verification": "visible_google_results",
                "success": True,
                "context_failure": "",
                "evidence": {"rescue_used": True},
            }

        self.engine._visible_google_search_in_current_tab = current_tab
        self.engine._visible_google_search_via_new_tab = fresh_tab

        success, detail = self.engine._visible_google_search("Rimuru Tempest", "brave", "google_search")

        self.assertTrue(success)
        self.assertEqual(["reuse", "fresh"], order)
        self.assertIn("fresh_tab_search_url", detail["strategy"])

    def test_fresh_tab_search_closes_previous_tab_after_success(self):
        cleanup_calls = []
        self.engine._capture_context = lambda refresh=True: {
            "window_title": "Rimuru Tempest - Buscar con Google - Brave",
            "active_window": "Rimuru Tempest - Buscar con Google - Brave",
            "active_app": "brave",
            "active_site": "google",
        }
        self.engine._visible_address_navigation = lambda **_kwargs: (
            True,
            {
                "strategy": "direct_typing",
                "evidence": {"target_control_used": "browser_address_bar"},
            },
        )

        def close_previous(**kwargs):
            cleanup_calls.append((kwargs["browser_name"], kwargs["step_name"]))
            return {
                "step": kwargs["step_name"],
                "strategy": "open_clean_tab+close_previous_tab",
                "verification": "browser_tab_rotation",
                "success": True,
                "context_failure": "",
                "evidence": {},
            }

        self.engine._close_previous_browser_tab_after_new_tab = close_previous

        success, detail = self.engine._visible_google_search_via_new_tab(
            "Rimuru Tempest",
            "brave",
            "google_search",
        )

        self.assertTrue(success)
        self.assertEqual([("brave", "google_search_close_previous_tab")], cleanup_calls)
        self.assertTrue(detail["evidence"]["previous_tab_cleanup"]["success"])

    def test_google_search_falls_back_to_address_url_when_visible_search_stays_on_same_page(self):
        assistant = FakeAssistant()

        class GoogleFallbackAutomation(FakeAutomation):
            def __init__(self):
                super().__init__()
                self.active_title = "Google - Brave"
                self.window_titles = [self.active_title]

            def press_keys(self, keys):
                result = super().press_keys(keys)
                if keys == ["enter"] and "google.com/search?q=" in self.last_written:
                    assistant._snapshot = FakeSnapshot(
                        active_window="Rimuru Tempest - Buscar con Google - Brave",
                        active_app="brave",
                        active_site="google",
                        elements=[FakeElement("browser_address_bar"), FakeElement("google_result_card_1")],
                    )
                    self.active_title = "Rimuru Tempest - Buscar con Google - Brave"
                    self.window_titles = [self.active_title]
                elif keys == ["enter"]:
                    assistant._snapshot = FakeSnapshot(
                        active_window="Google - Brave",
                        active_app="brave",
                        active_site="google",
                        elements=[FakeElement("google_search_bar")],
                    )
                    self.active_title = "Google - Brave"
                    self.window_titles = [self.active_title]
                return result

        automation = GoogleFallbackAutomation()
        engine = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=automation,
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
            queued_cycles=[],
        )
        assistant._snapshot = FakeSnapshot(
            active_window="Google - Brave",
            active_app="brave",
            active_site="google",
            elements=[FakeElement("google_search_bar")],
        )
        engine._visible_google_search_via_new_tab = lambda **_kwargs: (
            False,
            {
                "step": "google_search",
                "strategy": "fresh_tab_google_search",
                "verification": "visible_google_results",
                "success": False,
                "context_failure": "",
                "evidence": {},
            },
        )

        success, detail = engine._visible_google_search("Rimuru Tempest", "brave", "google_search")

        self.assertTrue(success)
        self.assertIn(("ctrl", "a"), automation.hotkeys)
        self.assertIn("google.com/search?q=", automation.last_written)
        self.assertIn("address_search_url", detail["strategy"])
        self.assertFalse(detail["evidence"]["rescue_used"])

    def test_browser_leave_site_prompt_text_detection(self):
        self.assertTrue(
            self.engine._text_looks_like_browser_leave_site_prompt(
                "¿Quieres salir del sitio web? Es posible que los cambios no se guarden."
            )
        )

    def test_browser_leave_site_prompt_resolution_accepts_leave(self):
        assistant = FakeAssistant()

        class LeaveSiteAutomation(FakeAutomation):
            def press_keys(self, keys):
                result = super().press_keys(keys)
                if keys == ["enter"]:
                    assistant._snapshot = FakeSnapshot(
                        active_window="Google - Brave",
                        active_app="brave",
                        active_site="google",
                        elements=[FakeElement("browser_address_bar")],
                    )
                    self.active_title = "Google - Brave"
                    self.window_titles = [self.active_title]
                return result

        automation = LeaveSiteAutomation()
        engine = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=automation,
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
            queued_cycles=[],
        )
        assistant._snapshot = FakeSnapshot(
            active_window="Formulario bloqueado - Brave",
            active_app="brave",
            active_site="google",
            elements=[FakeElement("browser_address_bar")],
            ocr_excerpt="Quieres salir del sitio web. Es posible que los cambios no se guarden.",
        )
        automation.active_title = "Formulario bloqueado - Brave"
        automation.window_titles = [automation.active_title]

        resolved = engine._resolve_browser_leave_site_prompt()

        self.assertTrue(resolved)
        self.assertIn(("enter",), automation.press_calls)

    def test_youtube_search_falls_back_to_results_url(self):
        assistant = FakeAssistant()

        class YouTubeFallbackAutomation(FakeAutomation):
            def __init__(self):
                super().__init__()
                self.active_title = "Brave"

            def press_keys(self, keys):
                result = super().press_keys(keys)
                if keys == ["enter"] and "youtube.com/results" in self.last_written:
                    assistant._snapshot = FakeSnapshot(
                        active_window="minecraft - YouTube - Brave",
                        active_app="brave",
                        active_site="youtube",
                        elements=[FakeElement("browser_address_bar")],
                    )
                    self.active_title = "minecraft - YouTube - Brave"
                elif keys == ["enter"]:
                    assistant._snapshot = FakeSnapshot(
                        active_window="YouTube - Brave",
                        active_app="brave",
                        active_site="youtube",
                        elements=[FakeElement("browser_address_bar")],
                    )
                    self.active_title = "YouTube - Brave"
                return result

        automation = YouTubeFallbackAutomation()
        engine = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=automation,
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
            queued_cycles=[],
        )
        engine._click_visible_hint = lambda target_name, **_kwargs: False if target_name == "youtube_search_bar" else True

        success, detail = engine._visible_youtube_search("minecraft", "brave", "youtube_search")

        self.assertTrue(success)
        self.assertEqual("youtube_results_url", detail["verification"])
        self.assertTrue(detail["evidence"]["rescue_used"])
        self.assertIn("youtube.com/results", automation.last_written)

    def test_youtube_open_result_prefers_visible_click_before_tab_navigation(self):
        assistant = FakeAssistant()

        class YouTubeVisibleResultAutomation(FakeAutomation):
            def __init__(self):
                super().__init__()
                self.active_title = "minecraft redstone - YouTube - Brave"
                self.window_titles = [self.active_title]

        automation = YouTubeVisibleResultAutomation()
        engine = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=automation,
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
            queued_cycles=[],
        )
        assistant._snapshot = FakeSnapshot(
            active_window="minecraft redstone - YouTube - Brave",
            active_app="brave",
            active_site="youtube",
            elements=[FakeElement("youtube_search_bar"), FakeElement("youtube_result_title_1")],
        )
        engine._visible_youtube_search = lambda **_kwargs: (
            True,
            {"strategy": "visible_youtube_search", "context_failure": "", "evidence": {}},
        )

        def click_visible(target_name, **_kwargs):
            if target_name.startswith("youtube_result"):
                assistant._snapshot = FakeSnapshot(
                    active_window="Tutorial Redstone Basico - YouTube - Brave",
                    active_app="brave",
                    active_site="youtube",
                    elements=[FakeElement("browser_address_bar")],
                )
                automation.active_title = "Tutorial Redstone Basico - YouTube - Brave"
                automation.window_titles = [automation.active_title]
                return True
            return False

        engine._click_visible_hint = click_visible

        success, detail = engine._youtube_open_result_attempt("minecraft redstone")

        self.assertTrue(success)
        self.assertIn("youtube_result_title_1_visible", detail["strategy"])
        self.assertFalse(any(call == ("tab",) for call in automation.press_calls))

    def test_youtube_goal_workflow_uses_visible_text_fallback_when_transcript_is_unavailable(self):
        assistant = FakeAssistant()
        automation = FakeAutomation()
        engine = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=automation,
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
            queued_cycles=[],
        )
        engine._youtube_open_result_attempt = lambda _query: (
            True,
            {
                "step": "youtube_open_result",
                "strategy": "youtube_result_title_1_visible",
                "verification": "active_window_title_changed",
                "success": True,
                "context_failure": "",
                "evidence": {},
            },
        )
        engine.task_executor.collect_page_text = lambda max_scrolls_per_page=1: "tutorial visible de youtube " * 20

        success, detail = engine._youtube_goal_workflow("minecraft redstone")

        self.assertTrue(success)
        self.assertEqual("youtube_transcript_or_visible_text", detail["verification"])
        self.assertIn("transcript_or_visible_text", detail["strategy"])
        self.assertGreaterEqual(detail["captured_chars"], 180)
        self.assertFalse(detail["evidence"]["transcript_available"])
        self.assertEqual("youtube_visible_ocr", detail["evidence"]["verification_source"])

    def test_youtube_goal_workflow_prefers_transcript_capture_when_available(self):
        assistant = FakeAssistant()
        assistant._snapshot = FakeSnapshot(
            active_window="Tutorial Redstone Basico - YouTube - Brave",
            active_app="brave",
            active_site="youtube",
            elements=[FakeElement("youtube_transcript_toggle")],
        )
        automation = FakeAutomation()
        automation.active_title = "Tutorial Redstone Basico - YouTube - Brave"
        automation.window_titles = [automation.active_title]
        engine = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=automation,
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
            queued_cycles=[],
        )
        engine._youtube_open_result_attempt = lambda _query: (
            True,
            {
                "step": "youtube_open_result",
                "strategy": "youtube_result_title_1_visible",
                "verification": "active_window_title_changed",
                "success": True,
                "context_failure": "",
                "evidence": {},
            },
        )
        engine.task_executor.collect_page_text = lambda max_scrolls_per_page=0: "transcripcion verificada de youtube " * 20

        success, detail = engine._youtube_goal_workflow("minecraft redstone")

        self.assertTrue(success)
        self.assertTrue(detail["evidence"]["transcript_available"])
        self.assertEqual("youtube_transcript_ocr", detail["evidence"]["verification_source"])
        self.assertGreaterEqual(detail["evidence"]["transcript_chars"], 220)

    def test_youtube_goal_workflow_fails_when_transcript_and_visible_text_are_insufficient(self):
        assistant = FakeAssistant()
        automation = FakeAutomation()
        engine = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=automation,
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
            queued_cycles=[],
        )
        engine._youtube_open_result_attempt = lambda _query: (
            True,
            {
                "step": "youtube_open_result",
                "strategy": "youtube_result_title_1_visible",
                "verification": "active_window_title_changed",
                "success": True,
                "context_failure": "",
                "evidence": {},
            },
        )
        engine.task_executor.collect_page_text = lambda max_scrolls_per_page=0: "corto"

        success, detail = engine._youtube_goal_workflow("minecraft redstone")

        self.assertFalse(success)
        self.assertEqual("poor", detail["evidence"]["page_usefulness_label"])
        self.assertEqual("youtube_insufficient_capture", detail["evidence"]["verification_source"])

    def test_keyboard_explorer_open_uses_win_e(self):
        assistant = FakeAssistant()

        class ExplorerAutomation(FakeAutomation):
            def hotkey(self, *keys):
                result = super().hotkey(*keys)
                if keys == ("winleft", "e"):
                    assistant._snapshot = FakeSnapshot(active_window="Explorador de archivos", active_app="explorer")
                    self.active_title = "Explorador de archivos"
                return result

        automation = ExplorerAutomation()
        engine = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=automation,
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
            queued_cycles=[],
        )

        success, detail = engine._keyboard_explorer_open_workflow("abrir explorer", self.base_dir)

        self.assertTrue(success)
        self.assertIn(("winleft", "e"), automation.hotkeys)
        self.assertEqual("win_e", detail["strategy"])

    def test_focus_browser_address_bar_falls_back_to_alt_d(self):
        assistant = FakeAssistant()

        class AddressAutomation(FakeAutomation):
            def hotkey(self, *keys):
                if keys == ("ctrl", "l"):
                    raise RuntimeError("ctrl+l blocked")
                return super().hotkey(*keys)

        automation = AddressAutomation()
        engine = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=automation,
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
            queued_cycles=[],
        )
        assistant.ensure_browser(browser="brave", private=False)
        automation.active_title = "Brave"

        target = engine._focus_browser_address_bar("brave")

        self.assertEqual("browser_address_bar_alt_d", target)
        self.assertIn(("alt", "d"), automation.hotkeys)

    def test_keyboard_explorer_search_uses_ctrl_f(self):
        class ExplorerAssistant(FakeAssistant):
            def __init__(self, automation):
                super().__init__()
                self._automation = automation

            def open_folder(self, target):
                result = super().open_folder(target)
                self._automation.active_title = "Explorador de archivos"
                self._snapshot = FakeSnapshot(
                    active_window="Explorador de archivos",
                    active_app="explorer",
                    active_site="",
                    elements=[],
                )
                return result

        automation = FakeAutomation()
        assistant = ExplorerAssistant(automation)
        engine = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=automation,
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
            queued_cycles=[],
        )

        success, detail = engine._keyboard_explorer_search_workflow("buscar archivo", self.base_dir / "workspace")

        self.assertTrue(success)
        self.assertIn(("ctrl", "f"), automation.hotkeys)
        self.assertEqual("explorer_search_focus", detail["verification"])

    def test_keyboard_window_switch_uses_alt_tab(self):
        assistant = FakeAssistant()

        class WindowAutomation(FakeAutomation):
            def __init__(self):
                super().__init__()
                self.active_title = "Brave"

            def alt_tab(self, repeats=1, delay=0.25):
                super().alt_tab(repeats=repeats, delay=delay)
                assistant._snapshot = FakeSnapshot(active_window="Bloc de notas", active_app="notepad")
                self.active_title = "Bloc de notas"
                return "ok"

        automation = WindowAutomation()
        engine = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=automation,
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
            queued_cycles=[],
        )
        assistant.ensure_browser(browser="brave", private=False)

        success, detail = engine._keyboard_window_switch_workflow("cambiar ventana", self.base_dir)

        self.assertTrue(success)
        self.assertIn(("alt", "tab"), automation.hotkeys)
        self.assertEqual("window_changed", detail["verification"])

    def test_research_query_marks_stuck_on_google_as_recoverable(self):
        self.engine._visible_google_search = lambda **_kwargs: (
            True,
            {"strategy": "visible_google_search", "context_failure": "", "evidence": {}},
        )
        self.engine._capture_context = lambda refresh=True: {
            "window_title": "Rimuru Tempest - Buscar con Google - Brave",
            "active_app": "brave",
            "active_site": "google",
        }
        self.engine._wait_for_research_page_open = lambda baseline_title, timeout_seconds=None: {
            "window_title": "Rimuru Tempest - Buscar con Google - Brave",
            "active_app": "brave",
            "active_site": "google",
        }
        self.engine._research_restore_google_results = lambda query: True

        success, detail = self.engine._research_query_attempt("Rimuru Tempest")

        self.assertFalse(success)
        self.assertEqual("stuck_on_google", detail["failure_stage"])
        self.assertFalse(detail["hard_failure"])
        self.assertEqual("google_results", detail["scene_id"])
        self.assertEqual("seguimos en resultados", detail["emergency_feedback"])

    def test_research_query_treats_google_help_page_as_poor_source_not_stuck(self):
        self.engine._visible_google_search = lambda **_kwargs: (
            True,
            {"strategy": "visible_google_search", "context_failure": "", "evidence": {}},
        )
        self.engine._capture_context = lambda refresh=True: {
            "window_title": "listas de tareas - Buscar con Google - Brave",
            "active_app": "brave",
            "active_site": "google",
        }
        self.engine._wait_for_research_page_open = lambda baseline_title, timeout_seconds=None: {
            "window_title": "Lista de tareas de tu Cuenta de Google - Android - Ayuda de Busqueda web de Google - Brave",
            "active_app": "brave",
            "active_site": "google",
        }

        class RichResearchExecutor(FakeTaskExecutor):
            def collect_page_text(self, max_scrolls_per_page=1):
                return "texto util de investigacion " * 40

        self.engine.task_executor = RichResearchExecutor()
        self.engine._return_to_google_results = lambda: True
        self.engine._research_restore_google_results = lambda query: True

        success, detail = self.engine._research_query_attempt("listas de tareas google")

        self.assertFalse(success)
        self.assertEqual("page_poor_quality", detail["failure_stage"])
        self.assertIn("ruido", detail["failure_reason"].lower())
        self.assertEqual("help_page", detail["scene_id"])
        self.assertEqual("abrimos ayuda lateral", detail["emergency_feedback"])

    def test_research_query_requires_useful_result_text(self):
        self.engine._visible_google_search = lambda **_kwargs: (
            True,
            {"strategy": "visible_google_search", "context_failure": "", "evidence": {}},
        )
        self.engine._capture_context = lambda refresh=True: {
            "window_title": "Resultado pobre - Brave" if not refresh else "Rimuru Tempest - Buscar con Google - Brave",
            "active_app": "brave",
            "active_site": "" if not refresh else "google",
        }

        class PoorResearchExecutor(FakeTaskExecutor):
            def collect_page_text(self, max_scrolls_per_page=1):
                return "muy corto"

        self.engine.task_executor = PoorResearchExecutor()
        self.engine._wait_for_research_page_open = lambda baseline_title, timeout_seconds=None: {
            "window_title": "Resultado pobre - Brave",
            "active_app": "brave",
            "active_site": "",
        }
        self.engine._return_to_google_results = lambda: True
        self.engine._research_restore_google_results = lambda query: True

        success, detail = self.engine._research_query_attempt("Rimuru Tempest")

        self.assertFalse(success)
        self.assertEqual("page_poor_quality", detail["failure_stage"])
        self.assertIn("500 caracteres utiles", detail["failure_reason"])
        self.assertEqual("article_page", detail["scene_id"])
        self.assertEqual("pagina bloqueada o vacia", detail["emergency_feedback"])

    def test_research_query_persists_file_dialog_feedback(self):
        self.engine._visible_google_search = lambda **_kwargs: (
            True,
            {"strategy": "visible_google_search", "context_failure": "", "evidence": {}},
        )
        self.engine._capture_context = lambda refresh=True: {
            "window_title": "Rimuru Tempest - Buscar con Google - Brave" if refresh else "Open",
            "active_app": "brave",
            "active_site": "google" if refresh else "",
        }
        self.engine._wait_for_research_page_open = lambda baseline_title, timeout_seconds=None: {
            "window_title": "Open",
            "active_app": "brave",
            "active_site": "",
        }
        self.engine._open_file_dialog_visible = lambda context=None: True
        self.engine._research_restore_google_results = lambda query: True
        self.engine._return_to_google_results = lambda: True

        success, detail = self.engine._research_query_attempt("Rimuru Tempest")

        self.assertFalse(success)
        self.assertEqual("wrong_active_window", detail["failure_stage"])
        self.assertEqual("file_dialog", detail["scene_id"])
        self.assertEqual("hay dialogo de archivo", detail["emergency_feedback"])

    def test_return_to_google_results_closes_current_tab_when_back_does_not_restore_google(self):
        state = {"site": "", "title": "Fuente util - Brave"}

        def capture_context(refresh=True):
            return {
                "window_title": state["title"],
                "active_app": "brave",
                "active_site": state["site"],
            }

        def hotkey(*keys):
            self.engine.automation.hotkeys.append(keys)
            if keys == ("ctrl", "w"):
                state["site"] = "google"
                state["title"] = "Rimuru Tempest - Buscar con Google - Brave"
            return "ok"

        self.engine._capture_context = capture_context
        self.engine.automation.hotkey = hotkey
        self.engine.sleep = lambda _seconds: None
        original_skill_settings = self.engine._skill_settings
        self.engine._skill_settings = lambda family: (
            {"result_back_timeout_seconds": 0.05}
            if family == "research"
            else original_skill_settings(family)
        )

        restored = self.engine._return_to_google_results()

        self.assertTrue(restored)
        self.assertEqual(self.engine.automation.hotkeys[:2], [("alt", "left"), ("ctrl", "w")])

    def test_research_restore_google_results_does_not_treat_google_help_page_as_results(self):
        self.engine._capture_context = lambda refresh=True: {
            "window_title": "Lista de tareas de tu Cuenta de Google - Android - Ayuda de Busqueda web de Google - Brave",
            "active_app": "brave",
            "active_site": "google",
        }
        calls = []
        self.engine._return_to_google_results = lambda: calls.append("back") or True
        self.engine._visible_google_search = lambda **_kwargs: (False, {})

        restored = self.engine._research_restore_google_results("listas de tareas google")

        self.assertTrue(restored)
        self.assertEqual(calls, ["back"])

    def test_research_cycle_leaves_clean_tab_and_closes_previous_tab(self):
        state = {"selected": "old"}
        old_title = "Rimuru Tempest - Buscar con Google - Brave"
        new_title = "Nueva pestana - Brave"

        def set_browser_tab(title, site):
            self.engine.automation.active_title = title
            self.engine.automation.window_titles = [title]
            self.engine.assistant._snapshot = FakeSnapshot(
                active_window=title,
                active_app="brave",
                active_site=site,
                elements=[
                    FakeElement("browser_address_bar"),
                    FakeElement("google_results_search_bar"),
                    FakeElement("google_result_card_1"),
                ],
            )

        set_browser_tab(old_title, "google")

        def hotkey(*keys):
            self.engine.automation.hotkeys.append(keys)
            if keys == ("ctrl", "t"):
                state["selected"] = "new"
                set_browser_tab(new_title, "")
            elif keys == ("ctrl", "shift", "tab"):
                state["selected"] = "old"
                set_browser_tab(old_title, "google")
            elif keys == ("ctrl", "w") and state["selected"] == "old":
                state["selected"] = "new"
                set_browser_tab(new_title, "")
            return "ok"

        self.engine.automation.hotkey = hotkey
        self.engine.sleep = lambda _seconds: None
        self.engine._research_query_attempt = lambda *_args, **_kwargs: (
            True,
            {
                "step": "research_query_attempt",
                "strategy": "visible_google_search",
                "verification": "page_text_quality",
                "success": True,
                "context_failure": "",
                "evidence": {},
            },
        )

        cycle = self.engine._run_research_cycle(
            level=1,
            mode="practice",
            goal="Rimuru Tempest",
            requested_attempts=1,
            requested_minutes=None,
            create_document=False,
            cycle_number=1,
        )

        self.assertTrue(cycle["browser_tab_cleanup"]["success"])
        self.assertEqual(self.engine.automation.active_title, new_title)
        self.assertEqual(self.engine.automation.hotkeys[-3:], [("ctrl", "t"), ("ctrl", "shift", "tab"), ("ctrl", "w")])

    def test_capture_research_page_text_retries_with_scroll_when_first_capture_is_short(self):
        calls = []

        class LayeredExecutor(FakeTaskExecutor):
            def collect_page_text(self, max_scrolls_per_page=1):
                calls.append(max_scrolls_per_page)
                if max_scrolls_per_page == 0:
                    return "corto"
                return "texto util de investigacion " * 30

        self.engine.task_executor = LayeredExecutor()
        self.engine.automation.active_title = "Fuente util - Brave"
        self.engine.assistant._snapshot = FakeSnapshot(
            active_window="Fuente util - Brave",
            active_app="brave",
            active_site="",
            elements=[FakeElement("browser_address_bar")],
        )

        capture = self.engine._capture_research_page_text(minimum_chars=260)

        self.assertGreaterEqual(len(capture["text"]), 260)
        self.assertTrue(capture["success"])
        self.assertEqual(calls, [0, 1])

    def test_capture_research_page_text_allows_legit_error_articles(self):
        class ErrorArticleExecutor(FakeTaskExecutor):
            def collect_page_text(self, max_scrolls_per_page=1):
                return "errores comunes y prevencion en productividad " * 24

        self.engine.task_executor = ErrorArticleExecutor()
        self.engine.automation.active_title = "Articulo util - Brave"
        self.engine.assistant._snapshot = FakeSnapshot(
            active_window="Articulo util - Brave",
            active_app="brave",
            active_site="",
            elements=[FakeElement("browser_address_bar")],
        )

        capture = self.engine._capture_research_page_text(minimum_chars=260)

        self.assertTrue(capture["success"])
        self.assertGreaterEqual(capture["captured_chars"], 260)

    def test_capture_context_drops_stale_browser_snapshot_when_terminal_has_focus(self):
        self.engine.automation.active_title = r"C:\Windows\System32\cmd.exe - py  raphel.py"
        self.engine.assistant._snapshot = FakeSnapshot(
            active_window="Google - Brave",
            active_app="brave",
            active_site="google",
            elements=[FakeElement("google_search_bar")],
        )

        context = self.engine._capture_context(refresh=True)

        self.assertEqual(context["window_title"], r"C:\Windows\System32\cmd.exe - py  raphel.py")
        self.assertEqual(context["active_app"], "cmd")
        self.assertEqual(context["active_site"], "")

    def test_page_text_quality_is_recoverable_for_research_history(self):
        profile = self.engine._default_profile(
            "skill:investigar",
            "Investigar",
            "cognitive_workflow",
            True,
            template_kind="research_workflow",
            canonical_entity="investigar",
        )
        history = [
            TrainingScenarioResult(
                skill_id="skill:investigar",
                domain="research",
                scenario_id="research_single_source",
                level=1,
                status="failure",
                verified=False,
                session_id="research_soft_1",
                timestamp=1,
                failure_stage="page_text_quality",
                evidence={"hard_failure": False},
            )
        ]

        consecutive = self.engine._consecutive_failed_sessions_from_history(profile, history)

        self.assertEqual(consecutive, 0)

    def test_recoverable_research_failure_does_not_increment_block_counter(self):
        profile = self.engine._default_profile(
            "skill:investigar",
            "Investigar",
            "cognitive_workflow",
            True,
            template_kind="research_workflow",
            canonical_entity="investigar",
        )

        self.engine._finalize_profile_state(profile, meaningful_success=False, hard_failure=False)

        self.assertEqual(profile["consecutive_failed_sessions"], 0)
        self.assertEqual(profile["state"], "active")

    def test_consecutive_failed_sessions_ignore_unverified_success_without_fresh_session_proof(self):
        profile = self.engine._default_profile(
            "app:word",
            "Word",
            "application_workflow",
            True,
            template_kind="document_editor",
            canonical_entity="word",
        )
        history = [
            TrainingScenarioResult(
                skill_id="app:word",
                domain="document_editor",
                scenario_id="document_write_basic",
                level=1,
                status="failure",
                verified=False,
                session_id="word_fail_1",
                timestamp=1,
                failure_stage="capture_selected_text",
                evidence={},
            ),
            TrainingScenarioResult(
                skill_id="app:word",
                domain="document_editor",
                scenario_id="document_write_basic",
                level=1,
                status="success",
                verified=False,
                session_id="word_soft_success",
                timestamp=2,
                evidence={"current_session_verified": False},
            ),
        ]

        consecutive = self.engine._consecutive_failed_sessions_from_history(profile, history)

        self.assertEqual(consecutive, 2)

    def test_consecutive_failed_sessions_reset_with_fresh_verified_session_evidence(self):
        profile = self.engine._default_profile(
            "app:word",
            "Word",
            "application_workflow",
            True,
            template_kind="document_editor",
            canonical_entity="word",
        )
        history = [
            TrainingScenarioResult(
                skill_id="app:word",
                domain="document_editor",
                scenario_id="document_write_basic",
                level=1,
                status="failure",
                verified=False,
                session_id="word_fail_1",
                timestamp=1,
                failure_stage="capture_selected_text",
                evidence={},
            ),
            TrainingScenarioResult(
                skill_id="app:word",
                domain="document_editor",
                scenario_id="document_write_basic",
                level=1,
                status="success",
                verified=False,
                session_id="word_recovered",
                timestamp=2,
                evidence={"current_session_verified": True},
            ),
        ]

        consecutive = self.engine._consecutive_failed_sessions_from_history(profile, history)

        self.assertEqual(consecutive, 0)

    def test_history_rebuild_reconstructs_keyboard_levels_from_real_results(self):
        profiles_path = self.base_dir / "data" / "learning_skill_profiles.json"
        profiles_path.parent.mkdir(parents=True, exist_ok=True)
        profiles_path.write_text(
            json.dumps(
                {
                    "version": 2,
                    "profiles": {
                        "skill:teclado": {
                            "skill_id": "skill:teclado",
                            "display_name": "Usar teclado",
                            "family": "motor_ui",
                            "supported": True,
                            "template_kind": "keyboard",
                            "canonical_entity": "teclado",
                            "current_level": 1,
                            "highest_verified_level": 0,
                            "real_usage_ready": False,
                            "verification_version": 3,
                            "profile_schema_version": 2,
                            "history_rebuild_version": 0,
                        }
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        results = []
        for idx in range(20):
            results.append(
                TrainingScenarioResult(
                    skill_id="skill:teclado",
                    domain="application_workflow",
                    scenario_id="document_write_basic",
                    level=1,
                    status="success",
                    verified=True,
                    session_id=f"kbd_l1_{idx}",
                    timestamp=idx + 1,
                    evidence={
                        "current_session_verified": True,
                        "verification_source": "history_rebuild_test",
                        "visible_text_chars": 400,
                    },
                ).to_dict()
            )
        for idx in range(10):
            results.append(
                TrainingScenarioResult(
                    skill_id="skill:teclado",
                    domain="application_workflow",
                    scenario_id="browser_search_result",
                    level=2,
                    status="success",
                    verified=True,
                    session_id=f"kbd_l2_{idx}",
                    timestamp=100 + idx,
                    evidence={
                        "current_session_verified": True,
                        "verification_source": "history_rebuild_test",
                        "visible_text_chars": 600,
                    },
                ).to_dict()
            )
        training_results_path = self.base_dir / "data" / "training_scenario_results.jsonl"
        training_results_path.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in results) + "\n",
            encoding="utf-8",
        )

        reloaded = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=FakeAutomation(),
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=FakeAssistant(),
            logger=FakeLogger(),
            queued_cycles=[],
        )
        profile = reloaded.state["profiles"]["skill:teclado"]

        self.assertEqual(profile["current_level"], 3)
        self.assertTrue(profile["real_usage_ready"])
        self.assertEqual(profile["history_rebuild_version"], reloaded.HISTORY_REBUILD_VERSION)

    def test_expand_research_result_indices_adds_subattempts_without_duplicates(self):
        expanded = self.engine._expand_research_result_indices([3, 1, 3], max_candidates=5)

        self.assertEqual(expanded[:2], [3, 1])
        self.assertEqual(len(expanded), 5)
        self.assertEqual(len(set(expanded)), len(expanded))

    def test_research_variation_seed_changes_challenge_between_sessions(self):
        profile = self.engine._ensure_profile(
            skill_id="skill:investigar",
            display_name="Investigar",
            family="cognitive_workflow",
            supported=True,
            template_kind="research_workflow",
            canonical_entity="investigar",
        )

        first_seed = self.engine._next_research_variation_seed(profile)
        second_seed = self.engine._next_research_variation_seed(profile)
        first = self.engine._build_research_challenge("seguridad de contrasenas", 1, 0, first_seed)
        second = self.engine._build_research_challenge("seguridad de contrasenas", 1, 0, second_seed)

        self.assertNotEqual(first_seed, second_seed)
        self.assertNotEqual(first["result_indices"], second["result_indices"])

    def test_research_cycle_level_one_expands_result_indices_instead_of_repeating_same_two(self):
        self.engine._visible_google_search = lambda **_kwargs: (
            True,
            {"strategy": "visible_google_search", "context_failure": "", "evidence": {}},
        )
        self.engine._capture_context = lambda refresh=True: {
            "window_title": "Resultado util - Brave",
            "active_app": "brave",
            "active_site": "",
        }
        self.engine._wait_for_research_page_open = lambda baseline_title, timeout_seconds=None: {
            "window_title": f"Seguridad de contraseñas guia {len(self.engine.task_executor.opened_result_indices) + 1} - Brave",
            "active_app": "brave",
            "active_site": "",
        }
        self.engine._return_to_google_results = lambda: None

        class RichResearchExecutor(FakeTaskExecutor):
            def collect_page_text(self, max_scrolls_per_page=1):
                return "texto util de investigacion " * 24

        self.engine.task_executor = RichResearchExecutor()

        cycle = self.engine._run_research_cycle(
            level=1,
            mode="practice",
            goal="seguridad de contrasenas",
            requested_attempts=4,
            requested_minutes=1,
            create_document=False,
            cycle_number=1,
        )

        self.assertEqual(cycle["successes"], 4)
        self.assertGreaterEqual(len(set(self.engine.task_executor.opened_result_indices)), 3)

    def test_research_variants_rotate_topic_and_dictionary_modifiers(self):
        data_dir = self.base_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "dictionary-es.json").write_text(
            "\n".join(
                [
                    json.dumps({"": "guia"}),
                    json.dumps({"": "comparacion"}),
                    json.dumps({"": "documentacion"}),
                ]
            ),
            encoding="utf-8",
        )

        topic = self.engine._choose_research_topic("", level=1, exp_level=0, cycle_number=2)
        variants = self.engine._research_variants(topic, level=2, exp_level=2, cycle_number=2)

        self.assertNotEqual(topic, "Rimuru Tempest")
        self.assertTrue(any("comparacion" in item for item in variants))
        self.assertGreaterEqual(len(variants), 6)

    def test_choose_research_topic_avoids_coding_topics_during_autonomous_rotation(self):
        selected_topics = {
            self.engine._choose_research_topic("", level=1, exp_level=0, cycle_number=cycle_number)
            for cycle_number in range(1, 20)
        }

        self.assertNotIn("python listas y diccionarios", selected_topics)

    def test_choose_research_topic_deprioritizes_recent_failed_topic(self):
        payload = {
            "skill_id": "skill:investigar",
            "verified": False,
            "evidence": {
                "selected_text_preview": "automatizacion de escritorio guia",
            },
        }
        self.engine.training_results_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine.training_results_path.write_text(
            json.dumps(payload) + "\n",
            encoding="utf-8",
        )

        topic = self.engine._choose_research_topic("", level=1, exp_level=0, cycle_number=1)

        self.assertNotEqual(topic, "automatizacion de escritorio")

    def test_research_practice_persists_readable_note_even_without_document_workflow(self):
        self.engine.queued_cycles = [
            {
                "successes": 1,
                "failures": 0,
                "verified_successes": 1,
                "workflow_successes": 0,
                "summary": "Investigar nivel 1: 1 verificados de 1 intento(s).",
                "challenge": {
                    "topic": "seguridad de contrasenas",
                },
                "steps": [
                    {
                        "step": "research_query_attempt",
                        "strategy": "visible_google_search+tab_2",
                        "verification": "page_text_quality",
                        "query": "seguridad de contrasenas guia",
                        "page_title": "Guia de seguridad - Brave",
                        "captured_chars": 840,
                        "success": True,
                        "scene_id": "article_page",
                        "emergency_feedback": "",
                        "context_failure": "",
                        "evidence": {
                            "current_session_verified": True,
                            "scene_id": "article_page",
                            "scene_variant": "general_web_page",
                            "emergency_feedback": "",
                        },
                    }
                ],
            }
        ]

        summary = self.engine.learn_skill("investigar")
        profile = self.engine.state["profiles"]["skill:investigar"]
        note_path = Path(profile["last_research_note_path"])

        self.assertTrue(note_path.exists())
        note_text = note_path.read_text(encoding="utf-8")
        self.assertIn("seguridad de contrasenas", note_text)
        self.assertIn("Guia de seguridad - Brave", note_text)
        self.assertIn("seguridad de contrasenas guia", note_text)
        self.assertIn("scene=article_page", note_text)
        self.assertIn("Nota de investigacion:", summary)

    def test_training_progress_snapshot_marks_lagging_profiles(self):
        profile = self.engine._default_profile(
            skill_id="skill:investigar",
            display_name="Investigar",
            family="cognitive_workflow",
            supported=True,
            template_kind="research_workflow",
            canonical_entity="investigar",
        )
        profile["consecutive_failed_sessions"] = 2
        self.engine.state["profiles"]["skill:investigar"] = profile

        snapshot = self.engine.training_progress_snapshot()
        investigar = next(item for item in snapshot["profiles"] if item["skill_id"] == "skill:investigar")

        self.assertEqual(investigar["trend"], "atrasado")
        self.assertTrue(investigar["lagging"])
        self.assertIn("sesiones fallidas", investigar["lagging_reason"])

    def test_research_profile_coaching_highlights_stuck_on_google(self):
        self.engine.state["profiles"]["skill:investigar"] = self.engine._default_profile(
            skill_id="skill:investigar",
            display_name="Investigar",
            family="cognitive_workflow",
            supported=True,
            template_kind="research_workflow",
            canonical_entity="investigar",
        )
        self.engine.record_training_result(
            TrainingScenarioResult(
                skill_id="skill:investigar",
                domain="research",
                scenario_id="research_single_source",
                session_id="research_fail_1",
                timestamp=1,
                level=1,
                status="failure",
                verified=False,
                failure_stage="stuck_on_google",
                chosen_strategy="visible_google_search",
                attempted_strategies=["visible_google_search"],
                evidence={"scene_id": "google_results", "emergency_feedback": "seguimos en resultados"},
                error_log="El click no saco al navegador de Google.",
            )
        )
        self.engine.record_training_result(
            TrainingScenarioResult(
                skill_id="skill:investigar",
                domain="research",
                scenario_id="research_single_source",
                session_id="research_fail_2",
                timestamp=2,
                level=1,
                status="failure",
                verified=False,
                failure_stage="stuck_on_google",
                chosen_strategy="visible_google_search",
                attempted_strategies=["visible_google_search"],
                evidence={"scene_id": "google_results", "emergency_feedback": "seguimos en resultados"},
                error_log="El click no saco al navegador de Google.",
            )
        )
        self.engine.record_training_result(
            TrainingScenarioResult(
                skill_id="skill:investigar",
                domain="research",
                scenario_id="research_single_source",
                session_id="research_ok_1",
                timestamp=3,
                level=1,
                status="success",
                verified=True,
                chosen_strategy="direct_typing+fresh_tab_search_url+tab_2",
                attempted_strategies=["direct_typing+fresh_tab_search_url+tab_2"],
                metrics={"captured_chars": 1800},
                evidence={"captured_chars": 1800},
                verified_outcome={"single_source_verified": True},
            )
        )

        snapshot = self.engine.training_progress_snapshot()
        investigar = next(item for item in snapshot["profiles"] if item["skill_id"] == "skill:investigar")
        status = self.engine.skill_status("investigar")
        overview = self.engine.summarize_for_learning_status()

        self.assertIn("stuck on google", investigar["behavior_summary"])
        self.assertIn("google_results", investigar["behavior_summary"])
        self.assertEqual("google_results", investigar["dominant_failure_scene"])
        self.assertEqual("seguimos en resultados", investigar["dominant_emergency_feedback"])
        self.assertEqual(investigar["coach_focus"], "salir de resultados y abrir fuente real")
        self.assertIn("click visible", investigar["coach_message"])
        self.assertIn("Empuje recomendado", status)
        self.assertIn("Escena dominante: google_results", status)
        self.assertIn("Guia concreta", status)
        self.assertIn("atasco=google_results/seguimos en resultados", overview)

    def test_document_editor_profile_coaching_highlights_capture_selected_text(self):
        self.engine.state["profiles"]["app:word"] = self.engine._default_profile(
            skill_id="app:word",
            display_name="Usar Word",
            family="ui_workflow",
            supported=True,
            template_kind="document_editor",
            canonical_entity="word",
        )
        self.engine.record_training_result(
            TrainingScenarioResult(
                skill_id="app:word",
                domain="document_editor",
                scenario_id="document_write_basic",
                session_id="word_fail_1",
                timestamp=1,
                level=1,
                status="failure",
                verified=False,
                failure_stage="capture_selected_text",
                chosen_strategy="direct_typing",
                attempted_strategies=["direct_typing"],
                error_log="No se pudo releer el texto escrito.",
            )
        )

        snapshot = self.engine.training_progress_snapshot()
        word = next(item for item in snapshot["profiles"] if item["skill_id"] == "app:word")
        status = self.engine.skill_status("word")

        self.assertEqual(word["coach_focus"], "escribir y releer en la misma sesion")
        self.assertIn("captura sale vacia", word["coach_message"])
        self.assertIn("Empuje recomendado", status)

    def test_browser_profile_coaching_highlights_window_site_transition(self):
        self.engine.state["profiles"]["app:brave"] = self.engine._default_profile(
            skill_id="app:brave",
            display_name="Usar Brave",
            family="ui_workflow",
            supported=True,
            template_kind="browser_app",
            canonical_entity="brave",
        )
        self.engine.record_training_result(
            TrainingScenarioResult(
                skill_id="app:brave",
                domain="browser",
                scenario_id="browser_search_result",
                session_id="brave_fail_1",
                timestamp=1,
                level=1,
                status="failure",
                verified=False,
                failure_stage="window_site_transition",
                chosen_strategy="visible_google_search",
                attempted_strategies=["visible_google_search"],
                error_log="La pagina no cambio.",
            )
        )
        self.engine.record_training_result(
            TrainingScenarioResult(
                skill_id="app:brave",
                domain="browser",
                scenario_id="browser_open_google",
                session_id="brave_ok_1",
                timestamp=2,
                level=1,
                status="success",
                verified=True,
                chosen_strategy="direct_typing",
                attempted_strategies=["direct_typing"],
            )
        )

        snapshot = self.engine.training_progress_snapshot()
        brave = next(item for item in snapshot["profiles"] if item["skill_id"] == "app:brave")
        overview = self.engine.skill_status()

        self.assertEqual(brave["coach_focus"], "cerrar la transicion del navegador antes del siguiente paso")
        self.assertIn("pagina no cambia", brave["coach_message"])
        self.assertIn("empuje cerrar la transicion del navegador antes del siguiente paso", overview.lower())

    def test_rebuild_metrics_ignores_unverified_evidence_even_when_result_marked_verified(self):
        profile = self.engine._default_profile(
            "skill:investigar",
            "Investigar",
            "cognitive_workflow",
            True,
            template_kind="research_workflow",
            canonical_entity="investigar",
        )
        result = TrainingScenarioResult(
            skill_id="skill:investigar",
            domain="research",
            scenario_id="research_single_source",
            level=1,
            status="success",
            verified=True,
            session_id="legacy_unverified",
            timestamp=1,
            evidence={"current_session_verified": False, "page_usefulness_label": "poor"},
        )

        metrics = self.engine._rebuild_level_metrics_from_history(profile, [result])

        self.assertEqual(metrics["1"]["successes"], 0)
        self.assertEqual(metrics["1"]["failures"], 1)
        self.assertEqual(metrics["1"]["verified_count"], 0)

    def test_invalidates_old_metrics_when_verification_version_is_old(self):
        self.engine.state["profiles"]["teclado"] = {
            "skill_id": "teclado",
            "display_name": "Usar teclado",
            "family": "motor_ui",
            "supported": True,
            "current_level": 3,
            "highest_verified_level": 3,
            "real_usage_ready": True,
            "level_metrics": {
                "1": {"successes": 99, "failures": 0, "verified_count": 99, "workflow_successes": 0, "sessions": 1, "success_rate": 1.0, "last_cycle_summary": "viejo"},
                "2": {"successes": 10, "failures": 0, "verified_count": 10, "workflow_successes": 10, "sessions": 1, "success_rate": 1.0, "last_cycle_summary": "viejo"},
                "3": {"successes": 5, "failures": 0, "verified_count": 5, "workflow_successes": 5, "sessions": 1, "success_rate": 1.0, "last_cycle_summary": "viejo"},
            },
            "verification_version": 1,
        }
        self.engine._save_state()
        reloaded = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=FakeAutomation(),
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=FakeAssistant(),
            logger=FakeLogger(),
            queued_cycles=[],
        )
        profile = reloaded.state["profiles"]["skill:teclado"]
        self.assertEqual(profile["current_level"], 1)
        self.assertEqual(profile["highest_verified_level"], 0)
        self.assertTrue(profile["metrics_invalidated"])

    def test_verification_upgrade_preserves_non_keyboard_metrics(self):
        self.engine.state["profiles"]["skill:investigar"] = {
            "skill_id": "skill:investigar",
            "display_name": "Investigar",
            "family": "cognitive_workflow",
            "supported": True,
            "template_kind": "research_workflow",
            "canonical_entity": "investigar",
            "current_level": 2,
            "highest_verified_level": 2,
            "real_usage_ready": True,
            "level_metrics": {
                "1": {"successes": 20, "failures": 0, "verified_count": 20, "workflow_successes": 0, "sessions": 1, "success_rate": 1.0, "last_cycle_summary": "viejo"},
                "2": {"successes": 10, "failures": 0, "verified_count": 10, "workflow_successes": 10, "sessions": 1, "success_rate": 1.0, "last_cycle_summary": "viejo"},
                "3": {"successes": 0, "failures": 0, "verified_count": 0, "workflow_successes": 0, "sessions": 0, "success_rate": 0.0, "last_cycle_summary": ""},
            },
            "verification_version": 1,
        }
        self.engine._save_state()
        reloaded = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=FakeAutomation(),
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=FakeAssistant(),
            logger=FakeLogger(),
            queued_cycles=[],
        )

        profile = reloaded.state["profiles"]["skill:investigar"]
        self.assertEqual(profile["current_level"], 2)
        self.assertEqual(profile["level_metrics"]["1"]["verified_count"], 20)
        self.assertFalse(profile["metrics_invalidated"])

    def test_openai_browser_title_is_not_file_dialog(self):
        reason = self.engine._unexpected_modal_reason(
            {"window_title": "OpenAI - Brave", "active_app": "brave", "active_site": ""},
            expected_app="browser",
        )

        self.assertEqual("", reason)

    def test_dismisses_previous_notepad_save_prompt(self):
        class PromptAutomation(FakeAutomation):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def capture_selected_text(self, select_all=True, select_all_shortcut=("ctrl", "a")):
                self.calls += 1
                if self.calls == 1:
                    return "[Window Title]\r\nBloc de notas\r\n\r\n[Main Instruction]\r\n¿Quieres guardar los cambios?"
                return ""

        assistant = FakeAssistant()
        automation = PromptAutomation()
        engine = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=automation,
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
            queued_cycles=[],
        )

        target = self.base_dir / "temp" / "keyboard.txt"
        engine._prepare_notepad_training_file(target)

        self.assertGreaterEqual(len(assistant.open_calls), 2)
        self.assertIn(("right",), automation.press_calls)
        self.assertIn(("enter",), automation.press_calls)

    def test_prepare_plain_notepad_session_dismisses_open_dialog_with_escape(self):
        class OpenDialogAutomation(FakeAutomation):
            def __init__(self):
                super().__init__()
                self.active_title = "Abrir"

            def press_keys(self, keys):
                result = super().press_keys(keys)
                if keys == ["esc"]:
                    self.active_title = "Bloc de notas"
                    if hasattr(self, "assistant"):
                        self.assistant._snapshot = FakeSnapshot(
                            active_window="Bloc de notas",
                            active_app="notepad",
                            elements=[FakeElement("document_body")],
                        )
                return result

        assistant = FakeAssistant()
        automation = OpenDialogAutomation()
        automation.assistant = assistant
        engine = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=automation,
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
            queued_cycles=[],
        )

        result = engine._prepare_plain_notepad_session(self.base_dir / "temp" / "keyboard.txt")

        self.assertTrue(result)
        self.assertIn(("esc",), automation.press_calls)
        self.assertTrue(any(call[0] == "notepad" for call in assistant.open_calls))

    def test_prepare_plain_notepad_session_aborts_when_open_dialog_persists(self):
        class PersistentOpenDialogAutomation(FakeAutomation):
            def __init__(self):
                super().__init__()
                self.active_title = "Abrir"

        assistant = FakeAssistant()
        automation = PersistentOpenDialogAutomation()
        engine = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=automation,
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
            queued_cycles=[],
        )

        result = engine._prepare_plain_notepad_session(self.base_dir / "temp" / "keyboard.txt")

        self.assertFalse(result)
        self.assertIn(("esc",), automation.press_calls)
        self.assertFalse(assistant.open_calls)

    def test_keyboard_write_refuses_open_dialog_without_typing(self):
        class OpenDialogAutomation(FakeAutomation):
            def __init__(self):
                super().__init__()
                self.active_title = "Abrir archivo"

        class OpenDialogAssistant(FakeAssistant):
            def __init__(self):
                super().__init__()
                self._snapshot = FakeSnapshot(active_window="Abrir archivo", active_app="", elements=[])

            def open_application(self, target, extra_args=None):
                self.open_calls.append((target, extra_args or []))
                self._snapshot = FakeSnapshot(active_window="Abrir archivo", active_app="", elements=[])
                return f"opened {target}"

        assistant = OpenDialogAssistant()
        automation = OpenDialogAutomation()
        engine = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=automation,
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
            queued_cycles=[],
        )

        success, detail = engine._keyboard_write_and_verify("raphel aprende rapido")

        self.assertFalse(success)
        self.assertEqual("", automation.last_written)
        self.assertIn("Abrir archivo", detail["context_failure"])

    def test_keyboard_write_falls_back_to_clipboard_on_direct_typing_failure(self):
        class ClipboardFallbackAutomation(FakeAutomation):
            def __init__(self):
                super().__init__()
                self.write_attempts = []

            def write_text(self, text, interval=0.01, use_clipboard=False):
                self.write_attempts.append(use_clipboard)
                if use_clipboard:
                    self.last_written = text
                else:
                    self.last_written = "texto incorrecto"
                return "ok"

        assistant = FakeAssistant()
        automation = ClipboardFallbackAutomation()
        engine = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=automation,
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
            queued_cycles=[],
        )

        success, detail = engine._keyboard_write_and_verify("raphel aprende rapido")

        self.assertTrue(success)
        self.assertTrue(detail.get("rescue_used"))
        self.assertEqual(detail.get("strategy"), "clipboard_paste")
        self.assertEqual(automation.write_attempts, [False, True])
        self.assertIn("fallback_source", detail)

    def test_keyboard_notepad_uses_spanish_safe_select_all_shortcut(self):
        automation = FakeAutomation()
        engine = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=automation,
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=FakeAssistant(),
            logger=FakeLogger(),
            queued_cycles=[],
        )

        success, _detail = engine._keyboard_write_and_verify("raphel aprende rapido")

        self.assertTrue(success)
        self.assertIn(("ctrl", "e"), automation.hotkeys)
        self.assertNotIn(("ctrl", "a"), automation.hotkeys)

    def test_keyboard_capture_refuses_console_even_with_stale_notepad_snapshot(self):
        class ConsoleAutomation(FakeAutomation):
            def __init__(self):
                super().__init__()
                self.active_title = r"C:\Windows\System32\cmd.exe"

            def capture_selected_text(self, select_all=True, select_all_shortcut=("ctrl", "a")):
                raise KeyboardInterrupt("ctrl+c reached console")

        assistant = FakeAssistant()
        assistant._snapshot = FakeSnapshot(
            active_window="Bloc de notas",
            active_app="notepad",
            elements=[FakeElement("document_body")],
        )
        automation = ConsoleAutomation()
        engine = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=automation,
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
            queued_cycles=[],
        )

        self.assertEqual("", engine._capture_editor_text(expected_app="notepad"))
        self.assertFalse(automation.hotkeys)

    def test_dismiss_plain_editor_open_file_dialog_with_escape(self):
        class OpenDialogAssistant(FakeAssistant):
            def __init__(self):
                super().__init__()
                self._snapshot = FakeSnapshot(active_window="Abrir archivo", active_app="", elements=[])

        class DialogAutomation(FakeAutomation):
            def __init__(self):
                super().__init__()
                self.pressed = []

            def press_keys(self, keys):
                self.pressed.append(tuple(keys))
                if keys == ["esc"]:
                    self.active_title = "Bloc de notas"
                    assistant._snapshot = FakeSnapshot(active_window="Bloc de notas", active_app="notepad", elements=[])
                return "ok"

        assistant = OpenDialogAssistant()
        automation = DialogAutomation()
        engine = StubLearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=automation,
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
            queued_cycles=[],
        )

        result = engine._dismiss_plain_editor_prompt_if_present()

        self.assertTrue(result)
        self.assertIn(("esc",), automation.pressed)

    def test_context_title_matches_notepad_untitled_window(self):
        self.assertTrue(
            self.engine._context_title_matches_expected_app("Sin título - Bloc de notas", "notepad")
        )
        self.assertTrue(
            self.engine._context_title_matches_expected_app("Untitled - Notepad", "notepad")
        )

    def test_namespaced_skill_session_id_is_windows_safe(self):
        session = self.engine._new_session(
            mode="learn",
            skill_id="skill:teclado",
            display_name="Usar teclado",
            goal="",
            user_requested_document=False,
            start_level=1,
        )

        self.assertNotIn(":", session["session_id"])
        self.assertTrue(session["session_id"].startswith("skill_teclado_learn_"))

    def test_keyboard_level_three_default_goals_are_varied(self):
        goals = {
            self.engine._keyboard_training_goal_variant(goal, cycle_number=1, attempt_number=index + 1)
            for index, goal in enumerate(self.engine._keyboard_level_three_goals(""))
        }

        self.assertGreater(len(goals), 1)
        self.assertFalse(any(goal == "escribe una busqueda corta" for goal in goals))

    def test_keyboard_cycle_respects_external_stop_before_notepad(self):
        assistant = FakeAssistant()
        assistant.input_training_stop_requested = lambda: True
        engine = LearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=FakeAutomation(),
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
            sleeper=lambda _seconds: None,
        )

        cycle = engine._run_keyboard_cycle(
            level=1,
            mode="practice",
            goal="",
            requested_attempts=2,
            requested_minutes=None,
            cycle_number=1,
        )

        self.assertEqual(cycle["status"], "stopped")
        self.assertEqual(cycle["successes"] + cycle["failures"], 0)
        self.assertIn("solicitud externa", cycle["summary"])

    def test_next_gate_status_shows_exponential_phase_after_legacy(self):
        profile = self.engine._default_profile(
            "skill:mouse",
            "Usar mouse",
            "motor_ui",
            True,
        )
        profile["current_level"] = self.engine.MAX_SKILL_LEVEL
        profile["exponential_level"] = 2
        profile["max_exponential_level"] = 6

        gate = self.engine._next_gate_status(profile)

        self.assertEqual(gate, "fase exponencial 2/6")

    def test_mouse_real_usage_ready_ignores_visual_detection_after_split(self):
        ready = self.engine._mouse_real_usage_ready(
            {
                "practice": {
                    "real_drag_enabled": True,
                    "movement": {"reliable": True},
                    "click": {"reliable": True},
                    "detection": {
                        "last_session_id": "detection_1",
                        "attempts": 6,
                        "reliable": False,
                    },
                },
                "categories": {"PracticaFlujoSeguro": {"successes": 3, "failures": 0}},
            }
        )

        self.assertTrue(ready)

    def test_refresh_mouse_profile_from_strategy_clears_stale_ready_flag(self):
        strategy_path = self.base_dir / "data" / "desktop_mouse_strategy.json"
        strategy_path.parent.mkdir(parents=True, exist_ok=True)
        strategy_path.write_text(
            json.dumps(
                {
                    "profiles": {"upper_list_row": {"successes": 3, "failures": 0}},
                    "categories": {"PracticaFlujoSeguro": {"successes": 3, "failures": 0}},
                    "practice": {
                        "real_drag_enabled": True,
                        "movement": {"reliable": True},
                        "click": {"reliable": True},
                        "detection": {
                            "last_session_id": "detection_1",
                            "attempts": 6,
                            "successes": 5,
                            "failures": 1,
                            "reliable": False,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        profile = self.engine._default_profile(
            "skill:mouse",
            "Usar mouse",
            "motor_ui",
            True,
        )
        profile["real_usage_ready"] = True

        self.engine._refresh_mouse_profile_from_strategy(profile)

        self.assertTrue(profile["real_usage_ready"])

    def test_refresh_window_management_profile_from_strategy_sets_layout_preference(self):
        strategy_path = self.base_dir / "data" / "desktop_mouse_strategy.json"
        strategy_path.parent.mkdir(parents=True, exist_ok=True)
        strategy_path.write_text(
            json.dumps(
                {
                    "window_management": {
                        "strict_split_enabled": True,
                        "repair_attempts": 6,
                        "repair_successes": 5,
                        "repair_failures": 1,
                        "source_occlusion_failures": 0,
                        "successful_split_layouts": 6,
                    },
                    "practice": {
                        "workflow": {
                            "last_session_id": "workflow_1",
                            "attempts": 6,
                            "successes": 6,
                            "failures": 0,
                            "success_rate": 1.0,
                            "reliable": True,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        profile = self.engine._default_profile(
            "skill:window_management",
            "Administrar ventanas",
            "ui_workflow",
            True,
            template_kind="window_management",
            canonical_entity="window_management",
        )

        self.engine._refresh_window_management_profile_from_strategy(profile)

        self.assertEqual(
            profile["preferred_strategies"].get("window_layout_mode"),
            "strict_split_explorer_halves",
        )
        self.assertTrue(profile["real_usage_ready"])
        self.assertEqual(profile["window_management_summary"]["workflow_session_id"], "workflow_1")

    def test_generic_exponential_is_capped_by_legacy_foundation(self):
        profile = self.engine._default_profile(
            "app:brave",
            "Usar Brave",
            "ui_workflow",
            True,
        )
        profile["current_level"] = 1
        profile["real_usage_ready"] = True
        profile["level_metrics"]["1"] = {
            "successes": 30,
            "failures": 0,
            "verified_count": 30,
            "workflow_successes": 12,
            "sessions": 6,
            "success_rate": 1.0,
            "last_cycle_summary": "Brave nivel 1: 30 verificados",
        }

        changed = self.engine._reevaluate_profile("app:brave", profile)

        self.assertTrue(changed)
        self.assertEqual(profile["exponential_level"], 1)
        self.assertIn("Limitado por legacy a exp 1/1.", profile["reevaluation_summary"])

    def test_generic_exponential_requires_real_workflow_for_level_two(self):
        profile = self.engine._default_profile(
            "app:brave",
            "Usar Brave",
            "ui_workflow",
            True,
        )
        profile["real_usage_ready"] = False
        profile["level_metrics"]["1"] = {
            "successes": 18,
            "failures": 0,
            "verified_count": 18,
            "workflow_successes": 0,
            "sessions": 4,
            "success_rate": 1.0,
            "last_cycle_summary": "Brave nivel 1: 18 verificados",
        }

        level = self.engine._generic_exponential_level_from_metrics(profile)

        self.assertEqual(level, 1)

    def test_hard_verification_requires_real_evidence(self):
        result = TrainingScenarioResult(
            skill_id="skill:investigar",
            domain="research",
            scenario_id="research_single_source",
            level=1,
            status="success",
            verified=True,
            evidence={},
        )

        self.assertFalse(self.engine._result_has_hard_verification(result))

    def test_focus_or_launch_known_app_reuses_existing_word_window_title(self):
        assistant = FakeAssistant()
        assistant._snapshot = FakeSnapshot(active_window="Windows PowerShell", active_app="powershell", elements=[])
        automation = FakeAutomation()
        automation.active_title = "Windows PowerShell"
        automation.window_titles = ["Windows PowerShell", "Document7 - Word"]
        engine = LearningSkillEngine(
            base_dir=self.base_dir,
            config=FakeConfig(self.base_dir),
            memory=FakeMemory(),
            learning=FakeLearning(),
            automation=automation,
            task_executor=FakeTaskExecutor(),
            mouse_controller=None,
            assistant=assistant,
            logger=FakeLogger(),
        )

        engine._focus_or_launch_known_app("word")

        self.assertIn("Document7 - Word", assistant.focus_calls)
        self.assertFalse(assistant.open_calls)

    def test_document_editor_write_reuses_word_document_without_forcing_ctrl_n(self):
        self.engine.assistant._snapshot = FakeSnapshot(
            active_window="Document1 - Word",
            active_app="word",
            active_site="",
            elements=[FakeElement("document_body")],
        )
        self.engine.automation.active_title = "Document1 - Word"
        self.engine.automation.window_titles = ["Document1 - Word"]

        success, _detail = self.engine._document_editor_write_and_verify("word", "texto verificado")

        self.assertTrue(success)
        self.assertNotIn(("ctrl", "n"), self.engine.automation.hotkeys)

    def test_document_editor_write_fails_when_selected_text_capture_is_empty(self):
        self.engine.assistant._snapshot = FakeSnapshot(
            active_window="Document1 - Word",
            active_app="word",
            active_site="",
            elements=[FakeElement("document_body")],
        )
        self.engine.automation.active_title = "Document1 - Word"
        self.engine.automation.window_titles = ["Document1 - Word"]
        self.engine.automation.capture_selected_text = lambda select_all=True, select_all_shortcut=("ctrl", "a"): ""

        success, detail = self.engine._document_editor_write_and_verify("word", "texto verificado")

        self.assertFalse(success)
        self.assertEqual("empty", detail["evidence"]["page_usefulness_label"])
        self.assertFalse(detail["evidence"]["current_session_verified"])
        self.assertIn("captura de texto quedo vacia", detail["evidence"]["verification_reason"].lower())


if __name__ == "__main__":
    unittest.main()
