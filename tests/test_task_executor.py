from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from core.task_executor import TaskExecutor


class FakeConfig:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def get(self, key, default=None):
        if key == "google_url":
            return "https://www.google.com/search?q={query}"
        if key == "youtube_search_url":
            return "https://www.youtube.com/results?search_query={query}"
        if key == "document_output_dir":
            return str(self.output_dir)
        if key == "research_automation":
            return {
                "prefer_direct_typing_for_search": True,
                "search_direct_typing_interval": 0.01,
                "document_direct_typing_max_chars": 1800,
                "document_direct_typing_interval": 0.006,
            }
        return default


class FakeMemory:
    def __init__(self):
        self.step_logs = []
        self.document_outputs = []

    def get_preference(self, _key, default=None):
        return default

    def record_step_log(self, *args, **kwargs):
        self.step_logs.append((args, kwargs))

    def record_document_output(self, *args):
        self.document_outputs.append(args)


class FakeLearning:
    def __init__(self):
        self.strategy_results = []
        self.action_results = []
        self.preferred = {}

    def preferred_strategy(self, domain, candidates):
        preferred = self.preferred.get(domain)
        if preferred in candidates:
            return preferred
        return candidates[0] if candidates else None

    def record_strategy_result(self, domain, strategy, success):
        self.strategy_results.append((domain, strategy, success))

    def record_action_result(self, action, params, result, success, context=None):
        self.action_results.append(
            {
                "action": action,
                "params": params,
                "result": result,
                "success": success,
                "context": context or {},
            }
        )


class FakeHistory:
    def __init__(self):
        self.records = []

    def record(self, action, payload):
        self.records.append((action, payload))


class FakeTaskPlanner:
    @staticmethod
    def summarize_text(text, max_sentences=5):
        cleaned = " ".join((text or "").split())
        return f"- {cleaned[:80]}" if cleaned else ""


class FakeMouse:
    def __init__(self):
        self.type_calls = []
        self.click_calls = []
        self.click_at_calls = []
        self.focus_calls = []

    def locate_and_type(self, **kwargs):
        self.type_calls.append(kwargs)
        return "typed"

    def click_ui_target(self, target_name, timeout=0, app=None):
        self.click_calls.append((target_name, timeout, app))
        return "clicked"

    def click_at(self, x, y, button="left", duration=0.18):
        self.click_at_calls.append(
            {
                "x": x,
                "y": y,
                "button": button,
                "duration": duration,
            }
        )
        return "clicked"

    def focus_or_launch_app(self, app_name, taskbar_target=None, launch_callback=None):
        self.focus_calls.append((app_name, taskbar_target))
        return launch_callback() if launch_callback else f"focused {app_name}"


class FailingMouse(FakeMouse):
    def focus_or_launch_app(self, app_name, taskbar_target=None, launch_callback=None):
        self.focus_calls.append((app_name, taskbar_target))
        raise RuntimeError("word no disponible")


class FakeAutomation:
    def __init__(self):
        self.write_calls = []
        self.hotkeys = []
        self.presses = []
        self.active_title = "Documento1 - Word"

    def hotkey(self, *keys):
        self.hotkeys.append(keys)
        return "hotkey"

    def press_keys(self, keys):
        self.presses.append(tuple(keys))
        return "press"

    def write_text(self, text, interval=0.02, use_clipboard=False):
        self.write_calls.append(
            {
                "text": text,
                "interval": interval,
                "use_clipboard": use_clipboard,
            }
        )
        return "write"

    def get_active_window_title(self):
        return self.active_title


class FakeAssistant:
    def __init__(self, output_dir: Path):
        self.memory = FakeMemory()
        self.learning = FakeLearning()
        self.history = FakeHistory()
        self.task_planner = FakeTaskPlanner()
        self.config = FakeConfig(output_dir)
        self._current_action_trace = []
        self._artifacts = {}

    def ensure_site(self, destination, browser=None, private=False):
        return f"{destination}:{browser}:{private}"

    def open_application(self, target):
        return f"opened {target}"

    @staticmethod
    def _resolve_application_name(application):
        return application

    @staticmethod
    def get_context_payload():
        return {"active_app": "test"}


class FakeLogger:
    def info(self, _message):
        return None

    def warning(self, _message):
        return None


class FakeVisionWindow:
    def __init__(self, left, top, width, height, is_active=True):
        self.left = left
        self.top = top
        self.width = width
        self.height = height
        self.is_active = is_active


class FakeVisionElement:
    def __init__(self, name, x, y, width, height):
        self.name = name
        self.x = x
        self.y = y
        self.width = width
        self.height = height


class FocusedVision:
    def __init__(self, active_site="google"):
        self.calls = []
        self.lookup_calls = []
        self.snapshot = type(
            "Snapshot",
            (),
            {
                "active_site": active_site,
                "windows": [FakeVisionWindow(0, 0, 1600, 900, True)],
            },
        )()
        self.elements = {
            "google_results_primary_region": FakeVisionElement("google_results_primary_region", 420, 470, 560, 420),
            "google_results_column": FakeVisionElement("google_results_column", 430, 480, 600, 480),
            "google_result_title_1": FakeVisionElement("google_result_title_1", 300, 286, 360, 34),
            "google_result_card_1": FakeVisionElement("google_result_card_1", 360, 300, 520, 84),
            "youtube_transcript_region": FakeVisionElement("youtube_transcript_region", 1248, 648, 320, 360),
            "youtube_captions_region": FakeVisionElement("youtube_captions_region", 700, 486, 720, 72),
            "youtube_watch_primary_region": FakeVisionElement("youtube_watch_primary_region", 700, 500, 760, 260),
            "youtube_watch_metadata_region": FakeVisionElement("youtube_watch_metadata_region", 700, 680, 760, 220),
            "youtube_watch_sidebar_region": FakeVisionElement("youtube_watch_sidebar_region", 1260, 520, 280, 420),
            "youtube_results_primary_region": FakeVisionElement("youtube_results_primary_region", 680, 500, 720, 280),
            "youtube_results_column": FakeVisionElement("youtube_results_column", 700, 520, 760, 420),
        }

    def get_latest_snapshot(self, refresh=False):
        return self.snapshot

    def find_ui_element(self, name, snapshot=None):
        self.lookup_calls.append(name)
        return self.elements.get(name)

    def extract_text(self, region=None, lang="eng"):
        self.calls.append((region, lang))
        if lang == "spa+eng":
            raise RuntimeError("spa language data missing")
        return "texto util de investigacion " * 25


class TaskExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.output_dir = Path(self.temp_dir.name) / "docs"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.assistant = FakeAssistant(self.output_dir)
        self.mouse = FakeMouse()
        self.automation = FakeAutomation()
        self.executor = TaskExecutor(
            assistant=self.assistant,
            vision=None,
            mouse_controller=self.mouse,
            automation=self.automation,
            memory=self.assistant.memory,
            logger=FakeLogger(),
        )

    def test_search_flow_prefers_direct_typing_and_records_learning(self):
        result = self.executor.run_search_flow("google", "drag inteligente", browser="brave", private=False)

        self.assertIn("Busqueda autonoma enviada a Google", result)
        self.assertFalse(self.mouse.type_calls[0]["use_clipboard"])
        self.assertEqual(self.mouse.type_calls[0]["interval"], 0.01)
        self.assertIn(("text_entry:search", "direct_typing", True), self.assistant.learning.strategy_results)
        self.assertEqual(self.assistant.learning.action_results[-1]["action"], "smart_site_search")
        self.assertEqual(self.assistant.learning.action_results[-1]["params"]["text_entry_strategy"], "direct_typing")

    def test_save_document_prefers_direct_typing_for_short_content(self):
        output_path = self.output_dir / "reporte.docx"
        saved = self.executor.save_document(
            title="Reporte",
            content="Linea 1\n\nLinea 2",
            application="word",
            output_path=output_path,
        )

        self.assertEqual(saved, str(output_path))
        content_writes = self.automation.write_calls[:-1]
        self.assertTrue(content_writes)
        self.assertTrue(all(not call["use_clipboard"] for call in content_writes))
        self.assertTrue(any(call["text"] == str(output_path) and call["use_clipboard"] for call in self.automation.write_calls))
        self.assertIn(("text_entry:document_body", "direct_typing", True), self.assistant.learning.strategy_results)
        self.assertEqual(self.assistant.learning.action_results[-1]["action"], "create_document")
        self.assertEqual(self.assistant.learning.action_results[-1]["params"]["text_entry_strategy"], "direct_typing")

    def test_save_document_word_fallback_is_real_docx(self):
        executor = TaskExecutor(
            assistant=self.assistant,
            vision=None,
            mouse_controller=FailingMouse(),
            automation=self.automation,
            memory=self.assistant.memory,
            logger=FakeLogger(),
        )
        output_path = self.output_dir / "minecraft.docx"

        saved = executor.save_document(
            title="Minecraft",
            content="Linea de investigacion",
            application="word",
            output_path=output_path,
        )

        self.assertEqual(saved, str(output_path))
        self.assertTrue(output_path.exists())
        with zipfile.ZipFile(output_path) as package:
            self.assertIn("word/document.xml", package.namelist())
            document_xml = package.read("word/document.xml").decode("utf-8")
        self.assertIn("Linea de investigacion", document_xml)

    def test_perform_research_returns_reusable_structure(self):
        self.executor.run_search_flow = lambda destination, query, browser=None, private=False: "ok"
        self.executor._open_google_result = lambda index: index <= 2
        self.executor.collect_page_text = lambda max_scrolls_per_page=2: "texto util de investigacion " * 40
        self.automation.active_title = "Rimuru Tempest guia oficial - Brave"

        result = self.executor.perform_research("Rimuru", browser="brave", result_count=2)

        self.assertEqual(result["topic"], "Rimuru")
        self.assertEqual(result["useful_source_count"], 2)
        self.assertTrue(result["summary"])
        self.assertEqual(len(result["reviewed_sources"]), 2)

    def test_classify_research_source_rejects_untitled_youtube_and_mismatch_titles(self):
        untitled = TaskExecutor.classify_research_source(
            "terraria crafting early game",
            "Sin título - Brave",
            "texto util de investigacion " * 40,
        )
        youtube = TaskExecutor.classify_research_source(
            "terraria crafting early game",
            "How to craft 200 health Healing potions in Terraria - YouTube - Brave",
            "texto util de investigacion " * 40,
        )
        mismatch = TaskExecutor.classify_research_source(
            "terraria crafting early game",
            "Introducción a Redstone: Comprender y aplicar los conceptos básicos - Brave",
            "texto util de investigacion " * 40,
        )

        self.assertFalse(untitled["counts_as_useful"])
        self.assertIn("ambiguo", untitled["reason"].lower())
        self.assertFalse(youtube["counts_as_useful"])
        self.assertIn("youtube", youtube["reason"].lower())
        self.assertFalse(mismatch["counts_as_useful"])
        self.assertIn("consulta", mismatch["reason"].lower())

    def test_classify_research_source_assigns_scene_taxonomy_for_google_help_and_article(self):
        google = TaskExecutor.classify_research_source(
            "rimuru tempest",
            "Rimuru Tempest - Buscar con Google - Brave",
            "texto util de investigacion " * 20,
            capture_context={"active_site": "google"},
        )
        help_noise = TaskExecutor.classify_research_source(
            "listas de tareas google",
            "Lista de tareas de tu Cuenta de Google - Ayuda de Busqueda web de Google - Brave",
            "texto util de investigacion " * 40,
            capture_context={"active_site": "google", "visible_text_verified": True},
        )
        help_page = TaskExecutor.classify_research_source(
            "minecraft support signs guide",
            "Minecraft support signs guide - Help Center - Brave",
            "texto util de investigacion " * 40,
            capture_context={"visible_text_verified": True},
        )
        article = TaskExecutor.classify_research_source(
            "minecraft copper farm",
            "Minecraft copper farm guide - Brave",
            "texto util de investigacion " * 40,
            capture_context={"visible_text_verified": True},
        )

        self.assertEqual("google_results", google["scene_id"])
        self.assertEqual("seguimos en resultados", google["emergency_feedback"])
        self.assertEqual("help_page", help_noise["scene_id"])
        self.assertEqual("abrimos ayuda lateral", help_noise["emergency_feedback"])
        self.assertFalse(help_noise["counts_as_useful"])
        self.assertEqual("help_page", help_page["scene_id"])
        self.assertTrue(help_page["counts_as_useful"])
        self.assertEqual("article_page", article["scene_id"])
        self.assertTrue(article["counts_as_useful"])

    def test_classify_research_source_detects_modal_file_dialog_and_blocked_page(self):
        modal = TaskExecutor.classify_research_source(
            "minecraft copper farm",
            "Confirm form resubmission - Brave",
            "",
            capture_context={"modal_detected": True},
        )
        dialog = TaskExecutor.classify_research_source(
            "minecraft copper farm",
            "Open",
            "",
            capture_context={"file_dialog_detected": True},
        )
        blocked = TaskExecutor.classify_research_source(
            "minecraft copper farm",
            "Access denied - Brave",
            "request blocked",
            capture_context={"visible_text_verified": False},
        )

        self.assertEqual("modal", modal["scene_id"])
        self.assertEqual("hay modal", modal["emergency_feedback"])
        self.assertFalse(modal["counts_as_useful"])
        self.assertEqual("file_dialog", dialog["scene_id"])
        self.assertEqual("hay dialogo de archivo", dialog["emergency_feedback"])
        self.assertFalse(dialog["counts_as_useful"])
        self.assertEqual("blocked_page", blocked["scene_id"])
        self.assertEqual("pagina bloqueada o vacia", blocked["emergency_feedback"])
        self.assertFalse(blocked["counts_as_useful"])

    def test_classify_research_source_allows_verified_youtube_text(self):
        youtube = TaskExecutor.classify_research_source(
            "rimuru tempest analysis",
            "Rimuru Tempest analysis - YouTube - Brave",
            "transcripcion visible de youtube " * 40,
            capture_context={"visible_text_verified": True},
        )

        self.assertEqual("youtube_watch", youtube["scene_id"])
        self.assertTrue(youtube["counts_as_useful"])

    def test_return_to_google_results_closes_current_tab_when_back_does_not_restore_google(self):
        vision = FocusedVision()
        vision.snapshot.active_site = ""
        executor = TaskExecutor(
            assistant=self.assistant,
            vision=vision,
            mouse_controller=self.mouse,
            automation=self.automation,
            memory=self.assistant.memory,
            logger=FakeLogger(),
        )

        def hotkey(*keys):
            self.automation.hotkeys.append(keys)
            if keys == ("ctrl", "w"):
                self.automation.active_title = "Rimuru - Buscar con Google - Brave"
                vision.snapshot.active_site = "google"
            return "hotkey"

        self.automation.active_title = "Fuente util - Brave"
        self.automation.hotkey = hotkey

        restored = executor._return_to_google_results()

        self.assertTrue(restored)
        self.assertEqual(self.automation.hotkeys[:2], [("alt", "left"), ("ctrl", "w")])

    def test_collect_page_text_prefers_focused_regions_and_language_fallback(self):
        executor = TaskExecutor(
            assistant=self.assistant,
            vision=FocusedVision(),
            mouse_controller=self.mouse,
            automation=self.automation,
            memory=self.assistant.memory,
            logger=FakeLogger(),
        )
        self.automation.capture_selected_text = lambda select_all=True: ""
        self.automation.scroll = lambda amount: amount

        text = executor.collect_page_text(max_scrolls_per_page=0)

        self.assertIn("texto util de investigacion", text)
        self.assertGreaterEqual(len(executor.vision.calls), 2)
        first_region, first_lang = executor.vision.calls[0]
        self.assertEqual(first_lang, "spa+eng")
        self.assertEqual(first_region, (140, 260, 560, 420))
        self.assertEqual(executor.vision.calls[1][1], "eng")

    def test_collect_page_text_prioritizes_youtube_watch_regions(self):
        executor = TaskExecutor(
            assistant=self.assistant,
            vision=FocusedVision(active_site="youtube"),
            mouse_controller=self.mouse,
            automation=self.automation,
            memory=self.assistant.memory,
            logger=FakeLogger(),
        )
        self.automation.capture_selected_text = lambda select_all=True: ""
        self.automation.scroll = lambda amount: amount

        text = executor.collect_page_text(max_scrolls_per_page=0)

        self.assertIn("texto util de investigacion", text)
        first_region, first_lang = executor.vision.calls[0]
        self.assertEqual(first_lang, "spa+eng")
        self.assertEqual(first_region, (1088, 468, 320, 360))

    def test_collect_page_text_avoids_select_all_on_google_results(self):
        executor = TaskExecutor(
            assistant=self.assistant,
            vision=FocusedVision(active_site="google"),
            mouse_controller=self.mouse,
            automation=self.automation,
            memory=self.assistant.memory,
            logger=FakeLogger(),
        )
        selection_calls = []
        self.automation.capture_selected_text = lambda select_all=True: selection_calls.append(select_all) or ""
        self.automation.scroll = lambda amount: amount

        text = executor.collect_page_text(max_scrolls_per_page=0)

        self.assertIn("texto util de investigacion", text)
        self.assertEqual(selection_calls, [])

    def test_collect_page_text_uses_select_all_fallback_for_generic_page(self):
        class EmptyVision(FocusedVision):
            def __init__(self):
                super().__init__(active_site="")

            def extract_text(self, region=None, lang="eng"):
                self.calls.append((region, lang))
                return ""

        executor = TaskExecutor(
            assistant=self.assistant,
            vision=EmptyVision(),
            mouse_controller=self.mouse,
            automation=self.automation,
            memory=self.assistant.memory,
            logger=FakeLogger(),
        )
        selection_calls = []
        self.automation.capture_selected_text = (
            lambda select_all=True: selection_calls.append(select_all) or "texto visible de respaldo " * 10
        )
        self.automation.scroll = lambda amount: amount

        text = executor.collect_page_text(max_scrolls_per_page=0)

        self.assertIn("texto visible de respaldo", text)
        self.assertEqual(selection_calls, [True])

    def test_collect_page_text_uses_select_all_fallback_for_help_page(self):
        class EmptyVision(FocusedVision):
            def __init__(self):
                super().__init__(active_site="")

            def extract_text(self, region=None, lang="eng"):
                self.calls.append((region, lang))
                return ""

        executor = TaskExecutor(
            assistant=self.assistant,
            vision=EmptyVision(),
            mouse_controller=self.mouse,
            automation=self.automation,
            memory=self.assistant.memory,
            logger=FakeLogger(),
        )
        self.automation.active_title = "Minecraft support signs guide - Help Center - Brave"
        selection_calls = []
        self.automation.capture_selected_text = (
            lambda select_all=True: selection_calls.append(select_all) or "texto visible de ayuda " * 12
        )
        self.automation.scroll = lambda amount: amount

        text = executor.collect_page_text(max_scrolls_per_page=0)

        self.assertIn("texto visible de ayuda", text)
        self.assertEqual(selection_calls, [True])

    def test_collect_page_text_avoids_select_all_on_file_dialog_scene(self):
        executor = TaskExecutor(
            assistant=self.assistant,
            vision=FocusedVision(active_site=""),
            mouse_controller=self.mouse,
            automation=self.automation,
            memory=self.assistant.memory,
            logger=FakeLogger(),
        )
        self.automation.active_title = "Open"
        selection_calls = []
        self.automation.capture_selected_text = lambda select_all=True: selection_calls.append(select_all) or ""
        self.automation.scroll = lambda amount: amount

        executor.collect_page_text(max_scrolls_per_page=0)

        self.assertEqual(selection_calls, [])

    def test_open_google_result_varies_click_point_between_calls(self):
        executor = TaskExecutor(
            assistant=self.assistant,
            vision=FocusedVision(),
            mouse_controller=self.mouse,
            automation=self.automation,
            memory=self.assistant.memory,
            logger=FakeLogger(),
        )

        first = executor._open_google_result(1)
        second = executor._open_google_result(1)

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(len(self.mouse.click_at_calls), 2)
        self.assertNotEqual(
            (self.mouse.click_at_calls[0]["x"], self.mouse.click_at_calls[0]["y"]),
            (self.mouse.click_at_calls[1]["x"], self.mouse.click_at_calls[1]["y"]),
        )

    def test_open_google_result_prefers_title_hint_when_available(self):
        vision = FocusedVision()
        executor = TaskExecutor(
            assistant=self.assistant,
            vision=vision,
            mouse_controller=self.mouse,
            automation=self.automation,
            memory=self.assistant.memory,
            logger=FakeLogger(),
        )

        opened = executor._open_google_result(1)

        self.assertTrue(opened)
        self.assertEqual(vision.lookup_calls[0], "google_result_title_1")
        self.assertEqual(len(self.mouse.click_at_calls), 1)
        self.assertLess(self.mouse.click_at_calls[0]["y"], vision.elements["google_result_card_1"].y)


if __name__ == "__main__":
    unittest.main()
