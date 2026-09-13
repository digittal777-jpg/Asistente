from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import shutil
import unittest

from core.desktop_learning_organizer import DesktopLearningMoveRecord, DesktopLearningOrganizer


class FakeConfig:
    def __init__(self, desktop_path: Path) -> None:
        self.desktop_path = desktop_path

    def get(self, key, default=None):
        if key == "frequent_folders":
            return {"desktop": str(self.desktop_path), "escritorio": str(self.desktop_path)}
        if key == "desktop_organizer":
            return {
                "root_folder_name": "_Raphel_Ordenado",
                "execution_mode": "ui_learning",
                "ui_move_gesture": "mixed_gradual",
                "max_batch_size": 50,
                "auto_continue_batches": True,
                "close_temporary_explorer_windows": True,
                "max_temporary_explorer_windows": 2,
                "reuse_explorer_windows_per_session": True,
                "restore_previous_window_after_session": True,
                "require_mouse_practice_for_real_drag": False,
                "mouse_practice_root_name": "_Raphel_Practica_Mouse",
                "mouse_practice_attempts": 2,
                "mouse_practice_distractor_count_min": 6,
                "mouse_practice_distractor_count_max": 12,
                "mouse_movement_practice_attempts": 3,
                "mouse_click_practice_attempts": 3,
                "mouse_double_click_practice_attempts": 3,
                "mouse_right_click_practice_attempts": 3,
                "mouse_selection_practice_attempts": 3,
                "mouse_workflow_practice_attempts": 2,
                "mouse_practice_max_attempts": 100,
                "mouse_move_tolerance_pixels": 12,
                "mouse_practice_required_success_rate": 0.7,
                "mouse_practice_min_successes": 1,
                "move_shortcuts": False,
                "move_folders": False,
                "skip_names": ["desktop.ini", "_Raphel_Ordenado"],
            }
        return default


class FakeVision:
    def get_latest_snapshot(self, refresh=False):
        class Snapshot:
            active_app = "explorer"
            windows = []

        return Snapshot()

    def _screen_bounds(self):
        return (0, 0, 1200, 800)


class FakeMemory:
    def __init__(self):
        self.sessions = []
        self.moves = []
        self.step_logs = []

    def record_desktop_learning_session(self, **kwargs):
        self.sessions.append(kwargs)

    def record_desktop_learning_move(self, **kwargs):
        self.moves.append(kwargs)

    def record_step_log(self, **kwargs):
        self.step_logs.append(kwargs)


class FakeAutomation:
    def __init__(self):
        self.current_folder = None
        self.selected_source = None
        self.pending_cut = None
        self.creating_folder = False
        self.address_mode = False
        self.pending_address = ""
        self.pending_folder_name = ""
        self.mouse_position = (0, 0)
        self.drag_drop_target = None
        self.calls = []

    def open_folder(self, folder_path: str):
        self.current_folder = Path(folder_path)
        if self.current_folder.name.startswith("Destino"):
            self.drag_drop_target = self.current_folder
        self.calls.append(("open_folder", str(self.current_folder)))
        return f"opened {folder_path}"

    def open_file_select(self, file_path: str):
        path = Path(file_path)
        self.current_folder = path.parent
        self.selected_source = path
        self.calls.append(("open_file_select", str(path)))
        return f"selected {file_path}"

    def focus_window(self, title: str):
        self.calls.append(("focus_window", title))
        if self.current_folder and self.current_folder.name != title:
            candidate = self.current_folder.parent / title
            if candidate.exists():
                self.current_folder = candidate
                if candidate.name.startswith("Destino"):
                    self.drag_drop_target = candidate
        return f"focused {title}"

    def hotkey(self, *keys: str):
        self.calls.append(("hotkey", keys))
        if keys == ("ctrl", "shift", "n"):
            self.creating_folder = True
        elif keys == ("alt", "d"):
            self.address_mode = True
        elif keys == ("ctrl", "x"):
            self.pending_cut = self.selected_source
        elif keys == ("ctrl", "v") and self.pending_cut and self.current_folder:
            destination = self.current_folder / self.pending_cut.name
            shutil.move(str(self.pending_cut), str(destination))
            self.pending_cut = None
        return "hotkey"

    def write_text(self, text: str, use_clipboard: bool = False):
        self.calls.append(("write_text", text, use_clipboard))
        if self.creating_folder:
            self.pending_folder_name = text
        elif self.address_mode:
            self.pending_address = text
        return "write"

    def press_keys(self, keys):
        self.calls.append(("press_keys", tuple(keys)))
        if self.creating_folder and "enter" in keys and self.current_folder:
            (self.current_folder / self.pending_folder_name).mkdir()
            self.creating_folder = False
            self.pending_folder_name = ""
        elif self.address_mode and "enter" in keys:
            self.current_folder = Path(self.pending_address)
            self.address_mode = False
            self.pending_address = ""
        return "press"

    def move_mouse(self, x: int, y: int, duration: float = 0.25):
        self.calls.append(("move_mouse", x, y, duration))
        self.mouse_position = (x, y)
        return "move"

    def get_mouse_position(self):
        self.calls.append(("get_mouse_position", self.mouse_position))
        return self.mouse_position

    def click(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
        interval: float = 0.1,
        duration: float = 0.15,
    ):
        self.calls.append(("click", x, y, button, clicks, interval, duration))
        return "click"

    def drag_mouse(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.4,
        button: str = "left",
    ):
        self.calls.append(("drag_mouse", start_x, start_y, end_x, end_y, duration, button))
        target_folder = self.drag_drop_target or self.current_folder
        if self.selected_source and target_folder:
            destination = target_folder / self.selected_source.name
            shutil.move(str(self.selected_source), str(destination))
            self.selected_source = None
        return "drag"


class DesktopLearningOrganizerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base_dir = Path(self.temp_dir.name) / "app"
        self.desktop = Path(self.temp_dir.name) / "Desktop"
        self.base_dir.mkdir()
        self.desktop.mkdir()
        self.document = self.desktop / "nota.txt"
        self.document.write_text("hola", encoding="utf-8")

        self.config = FakeConfig(self.desktop)
        self.automation = FakeAutomation()
        self.memory = FakeMemory()

        from core.desktop_trainer import DesktopTrainer

        self.trainer = DesktopTrainer(
            base_dir=self.base_dir,
            config=self.config,
            vision=FakeVision(),
            mouse_controller=None,
            automation=self.automation,
        )

        def select_file(path: Path) -> None:
            self.automation.selected_source = path
            self.automation.calls.append(("select_file", str(path)))
            self.organizer._explorer_ready = True

        self.organizer = DesktopLearningOrganizer(
            base_dir=self.base_dir,
            config=self.config,
            trainer=self.trainer,
            automation=self.automation,
            vision=FakeVision(),
            memory=self.memory,
            file_selector=select_file,
            sleeper=lambda _seconds: None,
        )

    def test_visible_organize_moves_file_and_records_learning(self):
        original_find = self.organizer._find_selected_item_point
        self.organizer._find_selected_item_point = lambda: (333, 222)

        try:
            result = self.organizer.organize()
        finally:
            self.organizer._find_selected_item_point = original_find

        destination = self.desktop / "_Raphel_Ordenado" / "Documentos" / "nota.txt"
        self.assertFalse(self.document.exists())
        self.assertTrue(destination.exists())
        self.assertIn("Ordenado visible completado", result)
        self.assertEqual(self.memory.moves[0]["status"], "completed")
        self.assertEqual(self.memory.moves[0]["gesture"], "drag_then_cut_paste")
        self.assertTrue((self.base_dir / "data" / "desktop_organizer_sessions" / "latest.json").exists())
        self.assertTrue(any(call[0] == "drag_mouse" for call in self.automation.calls))
        self.assertFalse(any(call == ("hotkey", ("ctrl", "x")) for call in self.automation.calls))
        self.assertFalse(any(call == ("hotkey", ("ctrl", "v")) for call in self.automation.calls))
        self.assertTrue(any(call[0] == "move_mouse" for call in self.automation.calls))
        self.assertTrue(any(call[0] == "click" for call in self.automation.calls))
        self.assertIn(("hotkey", ("alt", "f4")), self.automation.calls)
        strategy = json.loads((self.base_dir / "data" / "desktop_mouse_strategy.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(strategy["profiles"]["center_visible_item"]["successes"], 1)
        self.assertEqual(strategy["categories"]["Documentos"]["preferred_profile"], "center_visible_item")

    def test_drag_failure_falls_back_to_cut_paste(self):
        original_drag = self.automation.drag_mouse

        def failed_drag(*args, **kwargs):
            self.automation.calls.append(("drag_mouse_failed", args, kwargs))
            return "drag_failed"

        self.automation.drag_mouse = failed_drag

        original_find = self.organizer._find_selected_item_point
        self.organizer._find_selected_item_point = lambda: (333, 222)

        try:
            result = self.organizer.organize()
        finally:
            self.organizer._find_selected_item_point = original_find

        destination = self.desktop / "_Raphel_Ordenado" / "Documentos" / "nota.txt"
        self.assertFalse(self.document.exists())
        self.assertTrue(destination.exists())
        self.assertIn("Ordenado visible completado", result)
        self.assertIn(("hotkey", ("ctrl", "x")), self.automation.calls)
        self.assertIn(("hotkey", ("ctrl", "v")), self.automation.calls)
        self.assertEqual(self.memory.moves[0]["status"], "completed_with_fallback")
        self.assertEqual(self.memory.moves[0]["details"]["path_taken"], "visible_cut_paste")
        self.assertTrue(self.memory.moves[0]["details"]["fallback_used"])
        self.assertEqual(
            self.memory.moves[0]["details"]["fallback_attempt"]["attempt_type"],
            "explorer_drag",
        )
        self.assertEqual(
            self.memory.moves[0]["details"]["fallback_attempt"]["next_fallback"]["attempt_type"],
            "visible_cut_paste",
        )
        strategy = json.loads((self.base_dir / "data" / "desktop_mouse_strategy.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(strategy["profiles"]["center_visible_item"]["failures"], 1)

    def test_existing_destination_requires_manual_review(self):
        conflict_dir = self.desktop / "_Raphel_Ordenado" / "Documentos"
        conflict_dir.mkdir(parents=True)
        (conflict_dir / "nota.txt").write_text("existente", encoding="utf-8")

        result = self.organizer.organize()

        self.assertTrue(self.document.exists())
        self.assertIn("Revision manual: 1", result)
        self.assertEqual(self.memory.moves[0]["status"], "requires_manual_review")

    def test_mouse_practice_uses_temporary_files_and_updates_gate(self):
        original_find = self.organizer._find_selected_item_point
        self.organizer._find_selected_item_point = lambda: (333, 222)

        try:
            result = self.organizer.practice_mouse(attempts=2)
        finally:
            self.organizer._find_selected_item_point = original_find

        practice_root = self.desktop / "_Raphel_Practica_Mouse"
        self.assertTrue(practice_root.exists())
        self.assertIn("Practica de mouse completada", result)
        self.assertIn("Drag real habilitado", result)
        self.assertTrue(any(call[0] == "drag_mouse" for call in self.automation.calls))
        strategy = json.loads((self.base_dir / "data" / "desktop_mouse_strategy.json").read_text(encoding="utf-8"))
        self.assertTrue(strategy["practice"]["real_drag_enabled"])
        self.assertEqual(strategy["practice"]["successes"], 2)
        self.assertTrue((self.base_dir / "data" / "desktop_organizer_sessions" / "latest_mouse_practice.json").exists())
        layout = self.memory.moves[-1]["details"]["details"].get("practice_layout", {})
        self.assertGreaterEqual(int(layout.get("total_files", 0)), 7)
        self.assertGreaterEqual(int(layout.get("target_slot", 0)), 1)

    def test_practice_profiles_orders_profiles_by_score(self):
        self.organizer.drag_strategy["profiles"]["center_visible_item"]["successes"] = 4
        self.organizer.drag_strategy["profiles"]["center_visible_item"]["failures"] = 0
        self.organizer.drag_strategy["profiles"]["upper_list_row"]["successes"] = 0
        self.organizer.drag_strategy["profiles"]["upper_list_row"]["failures"] = 5
        ordered = self.organizer._practice_profiles()
        self.assertEqual(ordered[0]["name"], "center_visible_item")
        self.assertEqual(ordered[-1]["name"], "upper_list_row")

    def test_practice_profile_sequence_covers_profiles_before_repeating(self):
        sequence = self.organizer._practice_profile_sequence(4)
        names = [item["name"] for item in sequence]

        self.assertEqual(len(names), 4)
        self.assertEqual(set(names), {item["name"] for item in self.organizer.DEFAULT_DRAG_PROFILES})

    def test_open_destination_window_uses_separate_window_for_drag(self):
        self.organizer._explorer_ready = True
        destination = self.desktop / "Destino"
        destination.mkdir(exist_ok=True)
        self.automation.current_folder = self.desktop

        self.organizer._open_destination_window_for_drag(destination)

        self.assertIn(("open_folder", str(destination)), self.automation.calls)
        self.assertNotIn(("write_text", str(destination), True), self.automation.calls)

    def test_open_destination_window_opens_folder_if_explorer_not_active(self):
        destination = self.desktop / "Destino"
        destination.mkdir(exist_ok=True)
        self.organizer._explorer_ready = True
        self.automation.current_folder = self.desktop

        class Snapshot:
            active_app = "powershell"
            windows = []

        self.organizer.vision.get_latest_snapshot = lambda refresh=False: Snapshot()
        self.organizer._open_destination_window_for_drag(destination)

        self.assertIn(("open_folder", str(destination)), self.automation.calls)

    def test_select_file_reuses_explorer_if_ready(self):
        source = self.desktop / "reuso.txt"
        source.write_text("reuso", encoding="utf-8")
        self.organizer._explorer_ready = True
        self.automation.current_folder = self.desktop

        self.organizer._select_file_with_explorer(source)

        self.assertIn(("hotkey", ("alt", "d")), self.automation.calls)
        self.assertIn(("write_text", str(self.desktop), True), self.automation.calls)
        self.assertIn(("press_keys", ("enter",)), self.automation.calls)
        self.assertIn(("hotkey", ("ctrl", "f")), self.automation.calls)
        self.assertIn(("write_text", source.name, True), self.automation.calls)

    def test_select_file_with_explorer_uses_direct_select_for_workflow_practice_file(self):
        source = self.desktop / "_Raphel_Practica_Mouse" / "FlujoEntrada" / "raphel_practica_flujo_demo_01.txt"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("workflow", encoding="utf-8")
        self.organizer._explorer_ready = True
        self.automation.current_folder = source.parent

        self.organizer._select_file_with_explorer(source)

        self.assertIn(("open_file_select", str(source)), self.automation.calls)
        self.assertFalse(any(call == ("hotkey", ("ctrl", "f")) for call in self.automation.calls))

    def test_default_drag_selection_searches_filename_visibly(self):
        source = self.desktop / "buscar-visible.txt"
        destination = self.desktop / "Destino"
        source.write_text("buscar", encoding="utf-8")
        destination.mkdir(exist_ok=True)
        self.organizer._uses_default_file_selector = True
        self.organizer.file_selector = self.organizer._select_file_with_explorer

        self.organizer._prepare_drag_windows(source.parent, destination)
        self.organizer._select_file_for_drag(source)

        self.assertIn(("open_folder", str(self.desktop)), self.automation.calls)
        self.assertIn(("open_folder", str(destination)), self.automation.calls)
        self.assertIn(("focus_window", self.desktop.name), self.automation.calls)
        self.assertIn(("hotkey", ("ctrl", "f")), self.automation.calls)
        self.assertIn(("write_text", source.name, True), self.automation.calls)
        self.assertIn(("press_keys", ("enter",)), self.automation.calls)
        self.assertGreaterEqual(
            sum(1 for call in self.automation.calls if call == ("hotkey", ("ctrl", "a"))),
            2,
        )

    def test_move_path_visible_prefers_desktop_surface_drag_before_explorer_windows(self):
        destination = self.desktop / "Destino"
        destination.mkdir(exist_ok=True)
        session = self.organizer._new_session(
            self.trainer.preview_organization(),
            gesture_policy="drag_then_cut_paste",
        )
        calls = []
        original_surface = self.organizer._attempt_desktop_surface_drag_move
        original_explorer = self.organizer._attempt_drag_move
        original_should_try = self.organizer._should_try_desktop_surface_drag
        self.organizer._should_try_desktop_surface_drag = lambda _source: True

        def desktop_surface(*args, **kwargs):
            calls.append("desktop")
            return DesktopLearningMoveRecord(
                source=str(self.document),
                destination=str(destination / self.document.name),
                category="Documentos",
                gesture="drag_then_cut_paste",
                status="completed",
                verified=True,
                details={"desktop_surface": True},
            )

        self.organizer._attempt_desktop_surface_drag_move = desktop_surface
        self.organizer._attempt_drag_move = lambda *args, **kwargs: self.fail(
            "No debio usar Explorer si el drag de escritorio ya fue verificado."
        )

        try:
            result = self.organizer._move_path_visible(
                source=self.document,
                destination=destination / self.document.name,
                category="Documentos",
                session=session,
                gesture="drag_then_cut_paste",
            )
        finally:
            self.organizer._attempt_desktop_surface_drag_move = original_surface
            self.organizer._attempt_drag_move = original_explorer
            self.organizer._should_try_desktop_surface_drag = original_should_try

        self.assertTrue(result.verified)
        self.assertEqual(calls, ["desktop"])
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.path_taken, "desktop_drag")
        self.assertFalse(result.fallback_used)
        self.assertEqual(result.desktop_attempt["attempt_type"], "desktop_drag")
        session.moves.append(result)
        self.assertEqual(session.to_dict()["desktop_successes"], 1)

    def test_move_path_visible_falls_back_to_explorer_when_desktop_surface_drag_fails(self):
        destination = self.desktop / "Destino"
        destination.mkdir(exist_ok=True)
        session = self.organizer._new_session(
            self.trainer.preview_organization(),
            gesture_policy="drag_then_cut_paste",
        )
        calls = []
        original_surface = self.organizer._attempt_desktop_surface_drag_move
        original_explorer = self.organizer._attempt_drag_move
        original_should_try = self.organizer._should_try_desktop_surface_drag
        self.organizer._should_try_desktop_surface_drag = lambda _source: True

        def desktop_surface(*args, **kwargs):
            calls.append("desktop")
            return DesktopLearningMoveRecord(
                source=str(self.document),
                destination=str(destination / self.document.name),
                category="Documentos",
                gesture="drag_then_cut_paste",
                status="failed",
                verified=False,
                error="desktop failed",
                details={
                    "desktop_surface": True,
                    "failure_stage": "selection_persistence",
                    "failure_reason": "desktop failed",
                },
            )

        def explorer_drag(*args, **kwargs):
            calls.append("explorer")
            return DesktopLearningMoveRecord(
                source=str(self.document),
                destination=str(destination / self.document.name),
                category="Documentos",
                gesture="drag_then_cut_paste",
                status="completed",
                verified=True,
                details={"desktop_surface": False},
            )

        self.organizer._attempt_desktop_surface_drag_move = desktop_surface
        self.organizer._attempt_drag_move = explorer_drag

        try:
            result = self.organizer._move_path_visible(
                source=self.document,
                destination=destination / self.document.name,
                category="Documentos",
                session=session,
                gesture="drag_then_cut_paste",
            )
        finally:
            self.organizer._attempt_desktop_surface_drag_move = original_surface
            self.organizer._attempt_drag_move = original_explorer
            self.organizer._should_try_desktop_surface_drag = original_should_try

        self.assertTrue(result.verified)
        self.assertEqual(calls, ["desktop", "explorer"])
        self.assertEqual(result.status, "completed_with_fallback")
        self.assertEqual(result.path_taken, "explorer_drag")
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.desktop_attempt["failure_stage"], "selection_persistence")
        self.assertEqual(result.fallback_attempt["attempt_type"], "explorer_drag")

    def test_manifest_keeps_desktop_failure_history_when_explorer_rescues_move(self):
        destination = self.desktop / "_Raphel_Ordenado" / "Documentos" / self.document.name
        original_surface = self.organizer._attempt_desktop_surface_drag_move
        original_explorer = self.organizer._attempt_drag_move
        original_should_try = self.organizer._should_try_desktop_surface_drag
        original_find = self.organizer._find_selected_item_point
        self.organizer._should_try_desktop_surface_drag = lambda _source: True
        self.organizer._find_selected_item_point = lambda: (333, 222)

        def desktop_surface(*args, **kwargs):
            return DesktopLearningMoveRecord(
                source=str(self.document),
                destination=str(destination),
                category="Documentos",
                gesture="drag_then_cut_paste",
                status="failed",
                verified=False,
                error="desktop failed",
                details={
                    "desktop_surface": True,
                    "failure_stage": "selection_persistence",
                    "failure_reason": "desktop failed",
                    "source_point": [222, 111],
                },
            )

        def explorer_drag(*args, **kwargs):
            shutil.move(str(self.document), str(destination))
            return DesktopLearningMoveRecord(
                source=str(self.document),
                destination=str(destination),
                category="Documentos",
                gesture="drag_then_cut_paste",
                status="completed",
                verified=True,
                details={
                    "desktop_surface": False,
                    "source_point": [333, 222],
                    "destination_point": [900, 350],
                },
            )

        self.organizer._attempt_desktop_surface_drag_move = desktop_surface
        self.organizer._attempt_drag_move = explorer_drag

        try:
            self.organizer.organize()
        finally:
            self.organizer._attempt_desktop_surface_drag_move = original_surface
            self.organizer._attempt_drag_move = original_explorer
            self.organizer._should_try_desktop_surface_drag = original_should_try
            self.organizer._find_selected_item_point = original_find

        latest = json.loads(
            (self.base_dir / "data" / "desktop_organizer_sessions" / "latest.json").read_text(encoding="utf-8")
        )
        manifest = json.loads(Path(latest["manifest_path"]).read_text(encoding="utf-8"))
        move = manifest["moves"][0]
        self.assertEqual(move["status"], "completed_with_fallback")
        self.assertEqual(move["path_taken"], "explorer_drag")
        self.assertTrue(move["fallback_used"])
        self.assertEqual(move["desktop_attempt"]["failure_stage"], "selection_persistence")
        self.assertEqual(move["fallback_attempt"]["attempt_type"], "explorer_drag")
        self.assertEqual(manifest["completed_with_fallback"], 1)
        self.assertEqual(manifest["desktop_failures_by_stage"]["selection_persistence"], 1)

    def test_preferred_destination_snap_side_moves_window_left_when_source_is_on_right_edge(self):
        side = self.organizer._preferred_destination_snap_side(
            (1100, 240),
            {"bounds": [1020, 210, 1180, 270]},
        )

        self.assertEqual(side, "left")

    def test_revalidate_desktop_drag_continuity_marks_source_occluded(self):
        verification = self.organizer._revalidate_desktop_drag_continuity(
            source=self.document,
            source_point=(950, 240),
            selection_detection={
                "bounds": [900, 220, 1080, 270],
                "uia_match_name": self.document.name,
            },
            destination_window={
                "window": {
                    "left": 800,
                    "top": 0,
                    "right": 1200,
                    "bottom": 800,
                    "width": 400,
                    "height": 800,
                }
            },
            snap_side="right",
        )

        self.assertFalse(verification["coherent"])
        self.assertTrue(verification["source_occluded"])
        self.assertIn("tapo", verification["reason"])

    def test_revalidate_explorer_drag_continuity_marks_occluded_source_row(self):
        source = self.desktop / "_Raphel_Practica_Mouse" / "FlujoEntrada" / "sample.txt"
        destination = self.desktop / "_Raphel_Practica_Mouse" / "FlujoDestino" / "sample.txt"
        verification = self.organizer._revalidate_explorer_drag_continuity(
            source=source,
            source_point=(614, 469),
            selection_detection={
                "bounds": [507, 458, 1105, 480],
                "window_title": "FlujoEntrada",
                "uia_match_name": source.name,
            },
            source_window=SimpleNamespace(
                title="FlujoEntrada",
                app_name="explorer",
                left=0,
                top=25,
                width=1040,
                height=540,
                is_active=False,
            ),
            destination_window=SimpleNamespace(
                title="FlujoDestino",
                app_name="explorer",
                left=250,
                top=95,
                width=860,
                height=540,
                is_active=True,
            ),
            destination=destination,
        )

        self.assertFalse(verification["coherent"])
        self.assertTrue(verification["source_occluded"])
        self.assertIn("tapo", verification["reason"])

    def test_attempt_drag_move_aborts_before_drag_when_destination_window_taps_source(self):
        source_dir = self.desktop / "_Raphel_Practica_Mouse" / "FlujoEntrada"
        destination_dir = self.desktop / "_Raphel_Practica_Mouse" / "FlujoDestino"
        source_dir.mkdir(parents=True, exist_ok=True)
        destination_dir.mkdir(parents=True, exist_ok=True)
        source = source_dir / "raphel_practica_flujo_workflow_practice_01.txt"
        destination = destination_dir / source.name
        source.write_text("workflow", encoding="utf-8")
        session = self.organizer._new_session(
            self.trainer.preview_organization(),
            gesture_policy="drag_then_cut_paste",
        )

        original_prepare = self.organizer._prepare_drag_windows
        original_select = self.organizer._select_file_for_drag
        original_confirm = self.organizer._confirm_file_item_for_drag
        original_active_window = self.organizer._active_or_first_explorer_window

        windows = iter(
            [
                SimpleNamespace(
                    title="FlujoEntrada",
                    app_name="explorer",
                    left=0,
                    top=25,
                    width=1040,
                    height=540,
                    is_active=False,
                ),
                SimpleNamespace(
                    title="FlujoDestino",
                    app_name="explorer",
                    left=250,
                    top=95,
                    width=860,
                    height=540,
                    is_active=True,
                ),
            ]
        )

        self.organizer._prepare_drag_windows = lambda *_args, **_kwargs: None
        self.organizer._select_file_for_drag = lambda _source: "uia_folder_item_click"

        def confirm_file_for_drag(_source: Path):
            self.organizer._last_selected_item_detection = {
                "bounds": [507, 458, 1105, 480],
                "window_title": "FlujoEntrada",
                "uia_match_name": source.name,
            }
            return (614, 469), True, True

        self.organizer._confirm_file_item_for_drag = confirm_file_for_drag
        self.organizer._active_or_first_explorer_window = lambda: next(windows)

        try:
            record = self.organizer._attempt_drag_move(
                source=source,
                destination=destination,
                category="PracticaFlujoSeguro",
                session=session,
                gesture="drag_then_cut_paste",
                started=0.0,
            )
        finally:
            self.organizer._prepare_drag_windows = original_prepare
            self.organizer._select_file_for_drag = original_select
            self.organizer._confirm_file_item_for_drag = original_confirm
            self.organizer._active_or_first_explorer_window = original_active_window

        self.assertFalse(record.verified)
        self.assertIn("tapo", record.error)
        self.assertTrue(record.details["pre_drag_verification"]["source_occluded"])
        self.assertFalse(any(call[0] == "drag_mouse" for call in self.automation.calls))

    def test_learn_drag_outcome_enables_strict_window_layout_after_occlusion(self):
        self.organizer._learn_drag_outcome(
            profile_name="upper_list_row",
            category="PracticaFlujoSeguro",
            success=False,
            details={
                "pre_drag_verification": {
                    "source_occluded": True,
                    "reason": "La ventana destino tapo la fila seleccionada en Explorer antes del drag.",
                },
                "window_layout_mode": "balanced_split_explorer",
                "window_layout_repair": {"attempted": True, "recovered": False},
            },
        )

        strategy = self.organizer.drag_strategy
        self.assertTrue(strategy["window_management"]["strict_split_enabled"])
        self.assertEqual(strategy["window_management"]["source_occlusion_failures"], 1)
        self.assertEqual(strategy["window_management"]["repair_attempts"], 1)
        self.assertEqual(strategy["window_management"]["repair_failures"], 1)
        self.assertEqual(
            strategy["categories"]["PracticaFlujoSeguro"]["preferred_window_layout"],
            "strict_split_explorer_halves",
        )

    def test_attempt_drag_move_applies_learned_strict_window_layout(self):
        source_dir = self.desktop / "_Raphel_Practica_Mouse" / "FlujoEntrada"
        destination_dir = self.desktop / "_Raphel_Practica_Mouse" / "FlujoDestino"
        source_dir.mkdir(parents=True, exist_ok=True)
        destination_dir.mkdir(parents=True, exist_ok=True)
        source = source_dir / "raphel_practica_flujo_workflow_practice_02.txt"
        destination = destination_dir / source.name
        source.write_text("workflow", encoding="utf-8")
        session = self.organizer._new_session(
            self.trainer.preview_organization(),
            gesture_policy="drag_then_cut_paste",
        )

        self.organizer.drag_strategy["window_management"]["strict_split_enabled"] = True
        calls = []
        original_stabilize = self.organizer._stabilize_explorer_drag_layout
        original_prepare = self.organizer._prepare_drag_windows
        original_select = self.organizer._select_file_for_drag
        original_confirm = self.organizer._confirm_file_item_for_drag
        original_focus = self.organizer._focus_folder_window
        original_active = self.organizer._active_or_first_explorer_window
        original_body = self.organizer._explorer_body_point
        original_drag = self.organizer._try_drag_source_candidates
        original_revalidate = self.organizer._revalidate_explorer_drag_continuity

        self.organizer._stabilize_explorer_drag_layout = lambda *args, **kwargs: calls.append("stabilize")
        self.organizer._prepare_drag_windows = lambda *_args, **_kwargs: None
        self.organizer._select_file_for_drag = lambda _source: "uia_folder_item_click"
        self.organizer._confirm_file_item_for_drag = lambda _source: ((320, 240), True, True)
        self.organizer._focus_folder_window = lambda *_args, **_kwargs: None
        self.organizer._active_or_first_explorer_window = lambda: SimpleNamespace(
            title="FlujoEntrada",
            app_name="explorer",
            left=0,
            top=0,
            width=600,
            height=800,
            is_active=True,
        )
        self.organizer._explorer_body_point = lambda **_kwargs: (900, 300)
        self.organizer._try_drag_source_candidates = lambda **_kwargs: (True, (320, 240), [])
        self.organizer._revalidate_explorer_drag_continuity = lambda **_kwargs: {"coherent": True}
        self.organizer._last_selected_item_detection = {
            "bounds": [260, 220, 420, 260],
            "window_title": "FlujoEntrada",
            "uia_match_name": source.name,
        }

        try:
            record = self.organizer._attempt_drag_move(
                source=source,
                destination=destination,
                category="PracticaFlujoSeguro",
                session=session,
                gesture="drag_then_cut_paste",
                started=0.0,
            )
        finally:
            self.organizer._stabilize_explorer_drag_layout = original_stabilize
            self.organizer._prepare_drag_windows = original_prepare
            self.organizer._select_file_for_drag = original_select
            self.organizer._confirm_file_item_for_drag = original_confirm
            self.organizer._focus_folder_window = original_focus
            self.organizer._active_or_first_explorer_window = original_active
            self.organizer._explorer_body_point = original_body
            self.organizer._try_drag_source_candidates = original_drag
            self.organizer._revalidate_explorer_drag_continuity = original_revalidate

        self.assertTrue(record.verified)
        self.assertEqual(calls, ["stabilize"])
        self.assertEqual(record.details["window_layout_mode"], "strict_split_explorer_halves")

    def test_focus_folder_window_tries_localized_desktop_title_before_alt_tab(self):
        calls = []
        original_focus_window = self.automation.focus_window

        def localized_focus(title: str):
            calls.append(title)
            if title == "Desktop":
                raise RuntimeError("No se encontro ninguna ventana con titulo similar a 'Desktop'.")
            if title == "Escritorio":
                return "focused Escritorio"
            return original_focus_window(title)

        self.automation.focus_window = localized_focus

        self.organizer._focus_folder_window(self.desktop, "volver a origen para seleccionar archivo")

        self.assertEqual(calls[:2], ["Desktop", "Escritorio"])
        self.assertFalse(any(call == ("hotkey", ("alt", "tab")) for call in self.automation.calls))

    def test_drag_selection_prefers_uia_item_in_current_folder(self):
        source = self.desktop / "uia-visible.txt"
        destination = self.desktop / "Destino"
        source.write_text("uia", encoding="utf-8")
        destination.mkdir(exist_ok=True)
        self.organizer._uses_default_file_selector = True
        self.organizer.file_selector = self.organizer._select_file_with_explorer
        original_uia = self.organizer._find_file_item_detection_with_uia
        self.organizer._find_file_item_detection_with_uia = lambda _source: {
            "point": [333, 222],
            "bounds": [300, 200, 520, 260],
            "point_strategy": "uia_file_item",
            "window_title": self.desktop.name,
        }

        try:
            self.organizer._prepare_drag_windows(source.parent, destination)
            method = self.organizer._select_file_for_drag(source)
        finally:
            self.organizer._find_file_item_detection_with_uia = original_uia

        self.assertEqual(method, "uia_folder_item_click")
        self.assertIn(("move_mouse", 333, 222, 0.22), self.automation.calls)
        self.assertTrue(any(call[0] == "click" and call[1] == 333 and call[2] == 222 for call in self.automation.calls))
        self.assertFalse(any(call == ("hotkey", ("ctrl", "f")) for call in self.automation.calls))

    def test_practice_layout_creates_randomized_target_slot_and_clutter(self):
        layout = self.organizer._create_drag_practice_layout(
            source_dir=self.desktop / "Entrada_Prueba",
            session_id="practice_test",
            attempt_number=3,
        )

        self.assertGreaterEqual(layout["total_files"], 7)
        self.assertEqual(len(layout["created_files"]), layout["total_files"])
        self.assertEqual(len(layout["distractors"]), layout["distractor_count"])
        self.assertIn("raphel_practica_drag_", Path(layout["target_path"]).name)
        self.assertTrue(1 <= layout["target_slot"] <= layout["total_files"])

    def test_mouse_practice_respects_requested_drag_attempt_count(self):
        drag_calls = {"count": 0}
        original_drag = self.automation.drag_mouse
        original_find = self.organizer._find_selected_item_point

        def failed_drag(start_x, start_y, end_x, end_y, duration=0.4, button="left"):
            drag_calls["count"] += 1
            self.automation.calls.append(("drag_mouse", start_x, start_y, end_x, end_y, duration, button))
            return "failed"

        self.automation.drag_mouse = failed_drag
        self.organizer._find_selected_item_point = lambda: (333, 222)
        try:
            result = self.organizer.practice_mouse(attempts=1)
        finally:
            self.automation.drag_mouse = original_drag
            self.organizer._find_selected_item_point = original_find

        self.assertIn("Practica de mouse completada", result)
        self.assertEqual(drag_calls["count"], 1)
        strategy = json.loads((self.base_dir / "data" / "desktop_mouse_strategy.json").read_text(encoding="utf-8"))
        self.assertEqual(strategy["practice"]["attempts"], 1)
        self.assertEqual(strategy["practice"]["failures"], 1)

    def test_drag_practice_does_not_drag_without_visual_selection(self):
        self.organizer._uses_default_file_selector = True
        self.organizer.file_selector = self.organizer._select_file_with_explorer

        result = self.organizer.practice_mouse(attempts=1)

        self.assertIn("Practica de mouse completada", result)
        self.assertFalse(any(call[0] == "drag_mouse" for call in self.automation.calls))
        opened_destinations = [
            Path(call[1])
            for call in self.automation.calls
            if call[0] == "open_folder" and Path(call[1]).name.startswith("Destino")
        ]
        opened_sources = [
            Path(call[1])
            for call in self.automation.calls
            if call[0] == "open_folder" and Path(call[1]).name.startswith("Entrada")
        ]
        self.assertTrue(opened_destinations)
        self.assertEqual(len(opened_sources), 1)
        self.assertFalse(any(call == ("hotkey", ("ctrl", "f")) for call in self.automation.calls))
        move_details = self.memory.moves[-1]["details"]["details"]
        self.assertEqual(move_details["profile"], "source_visual_selection")
        self.assertEqual(move_details["source_strategy"], "selection_required")
        self.assertIsNone(move_details["source_point"])
        self.assertEqual(move_details["selection_method"], "practice_direct_select_window+keyboard_result")
        self.assertIn("seleccion dudosa", self.memory.moves[-1]["error"])

    def test_drag_practice_does_not_drag_with_unconfirmed_selection(self):
        responses = iter([(333, 222), None, (333, 222), None])
        original_find = self.organizer._find_selected_item_point
        self.organizer._find_selected_item_point = lambda: next(responses, None)

        try:
            result = self.organizer.practice_mouse(attempts=1)
        finally:
            self.organizer._find_selected_item_point = original_find

        self.assertIn("Practica de mouse completada", result)
        self.assertFalse(any(call[0] == "drag_mouse" for call in self.automation.calls))
        move_details = self.memory.moves[-1]["details"]["details"]
        self.assertEqual(move_details["profile"], "source_visual_selection")
        self.assertEqual(move_details["source_strategy"], "selection_unconfirmed")
        self.assertFalse(move_details["confirmed_visual_selection"])
        self.assertIn("seleccion dudosa", self.memory.moves[-1]["error"])

    def test_drag_confirms_visual_selection_before_dragging(self):
        original_find = self.organizer._find_selected_item_point
        self.organizer._find_selected_item_point = lambda: (333, 222)

        try:
            result = self.organizer.practice_mouse(attempts=1)
        finally:
            self.organizer._find_selected_item_point = original_find

        self.assertIn("Practica de mouse completada", result)
        first_drag_index = next(
            index for index, call in enumerate(self.automation.calls) if call[0] == "drag_mouse"
        )
        confirm_click_index = next(
            index
            for index, call in enumerate(self.automation.calls)
            if call[0] == "click" and call[1] == 333 and call[2] == 222
        )
        self.assertLess(confirm_click_index, first_drag_index)
        move_details = self.memory.moves[-1]["details"]["details"]
        self.assertEqual(move_details["source_strategy"], "vision_selected_item")
        self.assertNotEqual(move_details["profile"], "vision_selected_item")

    def test_drag_source_candidates_explore_selected_bounds(self):
        candidates = self.organizer._build_drag_source_candidates(
            (442, 361),
            {
                "point": [442, 361],
                "bounds": [400, 330, 900, 390],
                "point_strategy": "uia_file_item",
            },
        )

        labels = [candidate["label"] for candidate in candidates]
        self.assertIn("punto_detectado", labels)
        self.assertIn("icono_izquierda", labels)
        self.assertIn("texto_inicio", labels)
        self.assertIn("fila_arriba", labels)
        self.assertGreater(len(candidates), 3)

    def test_mouse_movement_practice_records_accuracy(self):
        result = self.organizer.practice_mouse_movement(attempts=3)

        self.assertIn("Practica de movimiento de mouse completada", result)
        strategy = json.loads((self.base_dir / "data" / "desktop_mouse_strategy.json").read_text(encoding="utf-8"))
        movement = strategy["practice"]["movement"]
        self.assertTrue(movement["reliable"])
        self.assertEqual(movement["attempts"], 3)
        self.assertEqual(movement["successes"], 3)
        self.assertEqual(movement["average_error_pixels"], 0.0)
        self.assertTrue(
            (self.base_dir / "data" / "desktop_organizer_sessions" / "latest_mouse_movement_practice.json").exists()
        )

    def test_mouse_movement_practice_stops_before_next_attempt(self):
        self.organizer.stop_checker = lambda: True

        result = self.organizer.practice_mouse_movement(attempts=3)

        self.assertIn("Practica de movimiento de mouse completada", result)
        self.assertFalse(any(call[0] == "move_mouse" for call in self.automation.calls))
        strategy = json.loads((self.base_dir / "data" / "desktop_mouse_strategy.json").read_text(encoding="utf-8"))
        movement = strategy["practice"]["movement"]
        self.assertEqual(movement["attempts"], 0)
        self.assertEqual(movement["successes"], 0)

    def test_mouse_click_practices_record_separate_skills(self):
        click_result = self.organizer.practice_mouse_click(attempts=2)
        double_result = self.organizer.practice_mouse_double_click(attempts=2)
        right_result = self.organizer.practice_mouse_right_click(attempts=2)

        self.assertIn("Practica de click simple completada", click_result)
        self.assertIn("Practica de doble click completada", double_result)
        self.assertIn("Practica de click derecho completada", right_result)
        strategy = json.loads((self.base_dir / "data" / "desktop_mouse_strategy.json").read_text(encoding="utf-8"))
        self.assertEqual(strategy["practice"]["click"]["successes"], 2)
        self.assertEqual(strategy["practice"]["double_click"]["successes"], 2)
        self.assertEqual(strategy["practice"]["right_click"]["successes"], 2)
        self.assertTrue(any(call[0] == "click" and call[3] == "left" and call[4] == 1 for call in self.automation.calls))
        self.assertTrue(any(call[0] == "click" and call[3] == "left" and call[4] == 2 for call in self.automation.calls))
        self.assertTrue(any(call[0] == "click" and call[3] == "right" for call in self.automation.calls))
        self.assertIn(("press_keys", ("esc",)), self.automation.calls)

    def test_mouse_selection_and_workflow_practices_record_skills(self):
        original_find = self.organizer._find_selected_item_point
        self.organizer._find_selected_item_point = lambda: (320, 240)

        selection_result = self.organizer.practice_mouse_selection(attempts=2)
        workflow_result = self.organizer.practice_mouse_workflow(attempts=2)

        self.organizer._find_selected_item_point = original_find
        self.assertIn("Practica de seleccion visual completada", selection_result)
        self.assertIn("Practica de flujo completo seguro completada", workflow_result)
        strategy = json.loads((self.base_dir / "data" / "desktop_mouse_strategy.json").read_text(encoding="utf-8"))
        self.assertEqual(strategy["practice"]["selection"]["successes"], 2)
        self.assertEqual(strategy["practice"]["workflow"]["successes"], 2)
        self.assertTrue(strategy["practice"]["selection"]["reliable"])
        self.assertTrue(strategy["practice"]["workflow"]["reliable"])
        selection_sources = [
            Path(call[1]).name
            for call in self.automation.calls
            if call[0] == "select_file" and "raphel_practica_seleccion" in call[1]
        ]
        self.assertEqual(len(set(selection_sources)), 2)
        self.assertFalse(any(call == ("hotkey", ("ctrl", "f")) for call in self.automation.calls))
        self.assertTrue(any(call[0] == "move_mouse" and call[1] == 320 and call[2] == 240 for call in self.automation.calls))
        self.assertTrue(any(call[0] == "click" and call[1] == 320 and call[2] == 240 for call in self.automation.calls))
        move_details = self.memory.moves[-1]["details"]["details"]
        self.assertEqual(move_details["instruction_profile"], "windows_explorer_guided_workflow")
        self.assertEqual(
            move_details["instruction_scope"],
            "window_focus+folder_navigation+visible_selection+move+verification",
        )
        self.assertEqual(len(move_details["instruction_steps"]), 5)
        self.assertTrue(
            (self.base_dir / "data" / "desktop_organizer_sessions" / "latest_mouse_selection_practice.json").exists()
        )
        self.assertTrue(
            (self.base_dir / "data" / "desktop_organizer_sessions" / "latest_mouse_workflow_practice.json").exists()
        )

    def test_mouse_detection_practice_records_reusable_detection(self):
        organizer = DesktopLearningOrganizer(
            base_dir=self.base_dir,
            config=self.config,
            trainer=self.trainer,
            automation=self.automation,
            vision=FakeVision(),
            memory=self.memory,
            sleeper=lambda _seconds: None,
        )
        original_detection = organizer._find_file_item_detection_with_uia
        original_confirm = organizer._confirm_file_item_selection
        organizer._find_file_item_detection_with_uia = lambda _source: {
            "point": [333, 222],
            "bounds": [300, 210, 360, 240],
            "matches": 1,
            "selected_width": 60,
            "selected_height": 30,
            "point_strategy": "uia_file_item",
            "window_title": "Deteccion",
            "uia_match_name": "sample.txt",
        }
        organizer._confirm_file_item_selection = lambda _source: ((333, 222), (333, 222), "uia_file_item_click")

        try:
            result = organizer.practice_mouse_detection(attempts=2)
        finally:
            organizer._find_file_item_detection_with_uia = original_detection
            organizer._confirm_file_item_selection = original_confirm

        self.assertIn("Practica de deteccion visual completada", result)
        strategy = json.loads((self.base_dir / "data" / "desktop_mouse_strategy.json").read_text(encoding="utf-8"))
        self.assertEqual(strategy["practice"]["detection"]["successes"], 2)
        self.assertEqual(strategy["practice"]["detection"]["reused_detections"], 2)
        self.assertTrue(strategy["practice"]["detection"]["reliable"])
        self.assertTrue(any(call[0] == "open_folder" for call in self.automation.calls))
        self.assertTrue(any(call[0] == "click" and call[1] == 333 and call[2] == 222 for call in self.automation.calls))
        self.assertTrue(
            (self.base_dir / "data" / "desktop_organizer_sessions" / "latest_mouse_detection_practice.json").exists()
        )

    def test_selection_practice_uses_explicit_file_select_with_default_selector(self):
        organizer = DesktopLearningOrganizer(
            base_dir=self.base_dir,
            config=self.config,
            trainer=self.trainer,
            automation=self.automation,
            vision=FakeVision(),
            memory=self.memory,
            sleeper=lambda _seconds: None,
        )
        source = self.desktop / "_Raphel_Practica_Mouse" / "Seleccion" / "sample.txt"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("sample", encoding="utf-8")

        organizer._select_file_for_selection_practice(source)

        self.assertIn(("open_file_select", str(source)), self.automation.calls)

    def test_explorer_offscreen_geometry_falls_back_to_screen_bounds(self):
        class OffscreenVision(FakeVision):
            def get_latest_snapshot(self, refresh=False):
                return SimpleNamespace(
                    active_app="explorer",
                    windows=[
                        SimpleNamespace(
                            title="Seleccion",
                            app_name="explorer",
                            left=-31880,
                            top=-31840,
                            width=200,
                            height=120,
                            is_active=True,
                        )
                    ],
                )

        self.organizer.vision = OffscreenVision()
        self.organizer._remember_explorer_folder(self.desktop / "_Raphel_Practica_Mouse" / "Seleccion")

        self.assertEqual(self.organizer._explorer_body_point(), (600, 360))
        self.organizer._move_mouse_inside_explorer("test offscreen", click=True)
        self.assertIn(("move_mouse", 600, 360, 0.28), self.automation.calls)
        self.assertTrue(any(call[0] == "click" and call[1] == 600 and call[2] == 360 for call in self.automation.calls))

    def test_workflow_reuses_explorer_windows_between_moves(self):
        original_find = self.organizer._find_selected_item_point
        self.organizer._find_selected_item_point = lambda: (320, 240)

        try:
            result = self.organizer.practice_mouse_workflow(attempts=2)
        finally:
            self.organizer._find_selected_item_point = original_find

        self.assertIn("Practica de flujo completo seguro completada", result)
        open_folder_calls = [call for call in self.automation.calls if call[0] == "open_folder"]
        self.assertEqual(len(open_folder_calls), 2)
        self.assertGreaterEqual(
            sum(
                1
                for call in self.automation.calls
                if call == ("focus_window", "FlujoEntrada") or call == ("focus_window", "FlujoDestino")
            ),
            2,
        )
        self.assertFalse(any(call == ("hotkey", ("ctrl", "f")) for call in self.automation.calls))

    def test_cut_paste_rescue_reuses_session_windows_without_opening_select_window(self):
        source_dir = self.desktop / "_Raphel_Practica_Mouse" / "FlujoEntrada"
        destination_dir = self.desktop / "_Raphel_Practica_Mouse" / "FlujoDestino"
        source_dir.mkdir(parents=True, exist_ok=True)
        destination_dir.mkdir(parents=True, exist_ok=True)
        source = source_dir / "raphel_practica_flujo_workflow_practice_01.txt"
        destination = destination_dir / source.name
        source.write_text("workflow", encoding="utf-8")

        organizer = DesktopLearningOrganizer(
            base_dir=self.base_dir,
            config=self.config,
            trainer=self.trainer,
            automation=self.automation,
            vision=FakeVision(),
            memory=self.memory,
            sleeper=lambda _seconds: None,
        )
        organizer._reuse_session_explorer_windows = True
        organizer._uses_default_file_selector = True
        organizer.file_selector = organizer._select_file_with_explorer

        selection_calls = []
        original_select_for_drag = organizer._select_file_for_drag

        def select_inside_reused_window(path: Path) -> str:
            selection_calls.append(path)
            self.automation.selected_source = path
            return "uia_folder_item_click"

        organizer._select_file_for_drag = select_inside_reused_window

        try:
            record = organizer._attempt_visible_cut_paste_move(
                source=source,
                destination=destination,
                category="workflow",
                gesture="drag_then_cut_paste",
                started=0.0,
            )
        finally:
            organizer._select_file_for_drag = original_select_for_drag

        self.assertTrue(record.verified)
        self.assertEqual(record.status, "completed")
        self.assertFalse(source.exists())
        self.assertTrue(destination.exists())
        self.assertEqual(selection_calls, [source])
        self.assertFalse(any(call[0] == "open_file_select" for call in self.automation.calls))
        self.assertIn(("hotkey", ("ctrl", "x")), self.automation.calls)
        self.assertIn(("hotkey", ("ctrl", "v")), self.automation.calls)
        self.assertTrue(record.details["reused_session_windows"])
        self.assertEqual(record.details["selection_method"], "uia_folder_item_click")

    def test_organize_restores_previous_window_after_session(self):
        original_find = self.organizer._find_selected_item_point
        self.organizer._find_selected_item_point = lambda: (333, 222)

        class Snapshot:
            active_app = "powershell"
            windows = [
                type("Window", (), {"title": "Mi Terminal", "is_active": True})(),
                type("Window", (), {"title": self.desktop.name, "is_active": False})(),
            ]

        self.organizer.vision.get_latest_snapshot = lambda refresh=False: Snapshot()

        try:
            self.organizer.organize()
        finally:
            self.organizer._find_selected_item_point = original_find

        self.assertIn(("focus_window", "Mi Terminal"), self.automation.calls)

    def test_organize_auto_continues_batches_until_all_files_finish(self):
        for index in range(1, 55):
            (self.desktop / f"nota_{index:02d}.txt").write_text("hola", encoding="utf-8")

        original_find = self.organizer._find_selected_item_point
        self.organizer._find_selected_item_point = lambda: (333, 222)

        try:
            result = self.organizer.organize()
        finally:
            self.organizer._find_selected_item_point = original_find

        destination_dir = self.desktop / "_Raphel_Ordenado" / "Documentos"
        moved_files = list(destination_dir.glob("*.txt"))
        self.assertEqual(len(moved_files), 55)
        self.assertNotIn("Pendientes por limite de lote", result)
        manifest = json.loads(
            (self.base_dir / "data" / "desktop_organizer_sessions" / "latest.json").read_text(encoding="utf-8")
        )
        session_payload = json.loads(Path(manifest["manifest_path"]).read_text(encoding="utf-8"))
        self.assertTrue(
            any("Continuacion automatica por lotes activada" in note for note in session_payload["notes"])
        )


if __name__ == "__main__":
    unittest.main()
