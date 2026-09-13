from __future__ import annotations

import json
import os
import random
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.data_paths import DataPaths
from core.desktop_trainer import DesktopMoveOperation, DesktopOrganizationPreview, DesktopTrainer
from core.logging_utils import ensure_directory
from core.organizer_store import OrganizerSessionStore
from core.skills import normalize_text


@dataclass
class DesktopLearningMoveRecord:
    source: str
    destination: str
    category: str
    gesture: str
    status: str
    duration_seconds: float = 0.0
    verified: bool = False
    error: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    path_taken: str = ""
    fallback_used: bool = False
    desktop_attempt: Dict[str, Any] = field(default_factory=dict)
    fallback_attempt: Dict[str, Any] = field(default_factory=dict)


class DesktopDragAttemptError(RuntimeError):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage


@dataclass
class DesktopLearningSession:
    session_id: str
    created_at: str
    mode: str
    gesture_policy: str
    desktop_path: str
    root_folder: str
    manifest_path: str
    moves: List[DesktopLearningMoveRecord] = field(default_factory=list)
    skipped: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["completed"] = sum(1 for move in self.moves if move.status == "completed")
        payload["completed_with_fallback"] = sum(
            1 for move in self.moves if move.status == "completed_with_fallback"
        )
        payload["failed"] = sum(1 for move in self.moves if move.status == "failed")
        payload["manual_review"] = sum(
            1 for move in self.moves if move.status == "requires_manual_review"
        )
        payload["desktop_successes"] = sum(
            1 for move in self.moves if move.path_taken == "desktop_drag" and move.verified
        )
        desktop_failures_by_stage: Dict[str, int] = {}
        for move in self.moves:
            attempt = move.desktop_attempt or {}
            if not attempt or attempt.get("verified"):
                continue
            stage = str(attempt.get("failure_stage") or "unknown")
            desktop_failures_by_stage[stage] = int(desktop_failures_by_stage.get(stage, 0)) + 1
        payload["desktop_failures_by_stage"] = desktop_failures_by_stage
        return payload


class DesktopLearningOrganizer:
    """Organiza el escritorio mediante acciones visibles y aprende del resultado."""

    UIA_CLIENT_CLSID = "{FF48DBA4-60EF-4201-AA87-54103EEF594E}"

    DEFAULT_DRAG_PROFILES = [
        {
            "name": "center_visible_item",
            "source_horizontal": 0.42,
            "source_vertical": 0.46,
            "destination_horizontal": 0.54,
            "destination_vertical": 0.48,
            "duration": 0.9,
            "drag_style": "smooth_hold",
            "pre_hold": 0.2,
            "post_hold": 0.1,
            "steps": 12,
            "wiggle_pixels": 0,
        },
        {
            "name": "upper_list_row",
            "source_horizontal": 0.28,
            "source_vertical": 0.32,
            "destination_horizontal": 0.62,
            "destination_vertical": 0.42,
            "duration": 1.05,
            "drag_style": "upper_row_slow_start",
            "pre_hold": 0.3,
            "post_hold": 0.12,
            "steps": 16,
            "wiggle_pixels": 6,
        },
        {
            "name": "left_icon_grid",
            "source_horizontal": 0.22,
            "source_vertical": 0.36,
            "destination_horizontal": 0.72,
            "destination_vertical": 0.46,
            "duration": 1.15,
            "drag_style": "threshold_wiggle",
            "pre_hold": 0.35,
            "post_hold": 0.15,
            "steps": 18,
            "wiggle_pixels": 12,
        },
        {
            "name": "slow_center_visible_item",
            "source_horizontal": 0.46,
            "source_vertical": 0.52,
            "destination_horizontal": 0.58,
            "destination_vertical": 0.55,
            "duration": 1.35,
            "drag_style": "slow_hold_release",
            "pre_hold": 0.45,
            "post_hold": 0.22,
            "steps": 22,
            "wiggle_pixels": 4,
        },
    ]

    def __init__(
        self,
        base_dir: Path,
        config: Any,
        trainer: DesktopTrainer,
        automation: Any,
        vision: Any,
        memory: Any,
        logger: Optional[Any] = None,
        progress_callback: Optional[Callable[[str, str], None]] = None,
        file_selector: Optional[Callable[[Path], None]] = None,
        stop_checker: Optional[Callable[[], bool]] = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.config = config
        self.trainer = trainer
        self.automation = automation
        self.vision = vision
        self.memory = memory
        self.logger = logger
        self.progress_callback = progress_callback
        self._uses_default_file_selector = file_selector is None
        self.file_selector = file_selector or self._select_file_with_explorer
        self.stop_checker = stop_checker or (lambda: False)
        self.sleep = sleeper
        self.paths = DataPaths.from_base_dir(self.base_dir)
        self.store = OrganizerSessionStore(self.paths, logger=self.logger)
        self.sessions_dir = self.store.sessions_dir
        self.strategy_path = self.store.strategy_path
        self._explorer_ready = False
        self._known_explorer_titles: set[str] = set()
        settings = self.config.get("desktop_organizer", {})
        self.close_temporary_explorer_windows = bool(
            settings.get("close_temporary_explorer_windows", True)
        )
        self.max_temporary_explorer_windows = max(
            1,
            int(settings.get("max_temporary_explorer_windows", 2)),
        )
        self._temporary_explorer_windows = 0
        self.reuse_explorer_windows_per_session = bool(
            settings.get("reuse_explorer_windows_per_session", True)
        )
        self.restore_previous_window_after_session = bool(
            settings.get("restore_previous_window_after_session", True)
        )
        self._reuse_session_explorer_windows = False
        self._session_drag_window_assignments: Dict[str, Path] = {}
        self._session_previous_active_window_title = ""
        self._last_selected_item_detection: Dict[str, Any] = {}
        self._uia_client: Optional[Any] = None
        self._uia_init_failed = False
        self.paths.ensure_base_structure()
        self.drag_strategy = self._load_drag_strategy()

    def organize(
        self,
        preview: Optional[DesktopOrganizationPreview] = None,
        root_name: Optional[str] = None,
        move_shortcuts: Optional[bool] = None,
        move_folders: Optional[bool] = None,
    ) -> str:
        preview = preview or self.trainer.preview_organization(
            root_name=root_name,
            move_shortcuts=move_shortcuts,
            move_folders=move_folders,
        )
        if not preview.operations:
            return "El escritorio ya esta limpio o no hay elementos configurados para mover."

        settings = self.config.get("desktop_organizer", {})
        max_batch_size = max(1, int(settings.get("max_batch_size", 50)))
        auto_continue_batches = bool(settings.get("auto_continue_batches", False))
        requested_gesture_policy = str(settings.get("ui_move_gesture", "mixed_gradual"))
        gesture_policy = self._resolve_real_file_gesture_policy(requested_gesture_policy)
        session = self._new_session(preview, gesture_policy=gesture_policy)
        if gesture_policy != requested_gesture_policy:
            session.notes.append(
                "Drag real desactivado hasta que el modo practica de mouse tenga suficientes exitos."
            )

        all_operations = list(preview.operations)
        operations = all_operations[:max_batch_size]
        total_candidates = len(all_operations)
        if total_candidates > max_batch_size and auto_continue_batches:
            operations = all_operations
            total_batches = (total_candidates + max_batch_size - 1) // max_batch_size
            session.notes.append(
                f"Continuacion automatica por lotes activada: {total_batches} lote(s) de hasta {max_batch_size} elemento(s)."
            )
        elif total_candidates > max_batch_size:
            session.notes.append(
                f"Se limito la sesion a {max_batch_size} elemento(s); "
                f"quedan {total_candidates - max_batch_size} pendiente(s)."
            )

        self._record_session_header(session)
        self._begin_explorer_reuse_session(enabled=self.reuse_explorer_windows_per_session)
        try:
            self._prepare_root_and_categories(preview, operations, session)

            batch_total = max(1, (len(operations) + max_batch_size - 1) // max_batch_size)
            for batch_index, start in enumerate(range(0, len(operations), max_batch_size), start=1):
                batch_operations = operations[start : start + max_batch_size]
                if batch_total > 1:
                    self._emit(
                        f"Procesando lote visible {batch_index}/{batch_total} ({len(batch_operations)} elemento(s)).",
                        "info",
                    )
                for operation in batch_operations:
                    record = self._move_operation_visible(operation, preview, session, gesture_policy)
                    session.moves.append(record)
                    self._record_move(session, record)
                    self._write_manifest(session)
        finally:
            self._end_explorer_reuse_session("terminar ordenado visible")

        self._record_session_header(session)
        self._write_manifest(session)
        self._write_latest_pointer(session)
        return self._summarize_session(session, total_candidates=total_candidates)

    def practice_mouse(self, attempts: Optional[int] = None) -> str:
        settings = self.config.get("desktop_organizer", {})
        attempt_count = self._bounded_practice_attempts(
            attempts,
            default_value=int(settings.get("mouse_practice_attempts", 4)),
        )
        root_name = str(settings.get("mouse_practice_root_name", "_Raphel_Practica_Mouse"))
        desktop = self._desktop_path()
        root = desktop / root_name
        session_id = f"practice_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        session_root = root / session_id
        ensure_directory(session_root)

        session = DesktopLearningSession(
            session_id=session_id,
            created_at=datetime.now().isoformat(timespec="seconds"),
            mode="mouse_practice",
            gesture_policy="drag_practice",
            desktop_path=str(desktop),
            root_folder=str(session_root),
            manifest_path=str(self.sessions_dir / f"{session_id}.json"),
        )
        session.notes.append(
            "Sesion segura: solo usa archivos temporales creados dentro de la carpeta de practica."
        )

        self._record_session_header(session)
        profiles = self._practice_profile_sequence(attempt_count)
        for index in range(attempt_count):
            if self._stop_requested():
                self._mark_practice_stopped(session, "drag")
                break
            attempt_root = session_root / f"intento_{index + 1:02d}"
            source_dir = attempt_root / f"Entrada_{index + 1:02d}"
            destination_dir = attempt_root / f"Destino_{index + 1:02d}"
            ensure_directory(source_dir)
            ensure_directory(destination_dir)
            self._clean_drag_practice_files(source_dir, destination_dir)

            practice_layout = self._create_drag_practice_layout(
                source_dir=source_dir,
                session_id=session.session_id,
                attempt_number=index + 1,
            )
            source = Path(practice_layout["target_path"])
            destination = destination_dir / source.name
            if destination.exists():
                destination.unlink()

            started = time.perf_counter()
            profile = profiles[index % len(profiles)]
            profile_name = str(profile.get("name", "unknown"))
            self._emit(
                f"Intento drag practica {index + 1}/{attempt_count} usando perfil {profile_name}.",
                "info",
            )
            record = self._attempt_drag_move(
                source=source,
                destination=destination,
                category="PracticaMouse",
                session=session,
                gesture="drag_practice",
                started=started,
                profile_override=profile,
            )
            record.details["practice"] = True
            record.details["practice_profile"] = record.details.get("profile", "unknown")
            record.details["practice_layout"] = practice_layout
            record = self._finish_move_record(record, source)
            session.moves.append(record)
            self._record_move(session, record)
            self._write_manifest(session)

        self._record_mouse_practice_summary(session)
        self._record_session_header(session)
        self._write_manifest(session)
        self._write_latest_practice_pointer(session)
        return self._summarize_practice_session(session)

    def practice_mouse_movement(self, attempts: Optional[int] = None) -> str:
        settings = self.config.get("desktop_organizer", {})
        attempt_count = self._bounded_practice_attempts(
            attempts,
            default_value=int(settings.get("mouse_movement_practice_attempts", 12)),
        )
        tolerance = max(1, int(settings.get("mouse_move_tolerance_pixels", 12)))
        desktop = self._desktop_path()
        session_id = f"movement_practice_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        session = DesktopLearningSession(
            session_id=session_id,
            created_at=datetime.now().isoformat(timespec="seconds"),
            mode="mouse_movement_practice",
            gesture_policy="move_mouse_practice",
            desktop_path=str(desktop),
            root_folder=str(desktop),
            manifest_path=str(self.sessions_dir / f"{session_id}.json"),
        )
        session.notes.append(
            "Sesion segura: solo mueve el puntero a puntos visibles y verifica posicion; no toca archivos."
        )

        self._record_session_header(session)
        for index, target in enumerate(self._movement_practice_points(attempt_count), start=1):
            if self._stop_requested():
                self._mark_practice_stopped(session, "movimiento de mouse")
                break
            started = time.perf_counter()
            x, y = target
            self._emit(f"Practica movimiento mouse {index}/{attempt_count}: ({x}, {y})", "info")
            actual: Optional[Tuple[int, int]] = None
            error_pixels: Optional[float] = None
            try:
                self.automation.move_mouse(x, y, duration=0.22)
                self.sleep(0.08)
                actual = self._get_mouse_position()
                if actual:
                    error_pixels = self._distance_pixels(target, actual)
                    verified = error_pixels <= tolerance
                else:
                    verified = False
                status = "completed" if verified else "failed"
                error = "" if verified else "El puntero no quedo dentro de la tolerancia configurada."
            except Exception as exc:
                verified = False
                status = "failed"
                error = str(exc)

            record = DesktopLearningMoveRecord(
                source="mouse",
                destination=f"point:{x},{y}",
                category="PracticaMovimientoMouse",
                gesture="move_mouse_practice",
                status=status,
                duration_seconds=round(time.perf_counter() - started, 3),
                verified=verified,
                error=error,
                details={
                    "target": [x, y],
                    "actual": list(actual) if actual else None,
                    "error_pixels": round(error_pixels, 3) if error_pixels is not None else None,
                    "tolerance_pixels": tolerance,
                    "practice": True,
                },
            )
            session.moves.append(record)
            self._record_move(session, record)
            self._record_mouse_step(
                reason="practica movimiento mouse",
                status=status,
                payload=record.details,
            )
            self._write_manifest(session)

        self._record_mouse_movement_practice_summary(session, tolerance=tolerance)
        self._record_session_header(session)
        self._write_manifest(session)
        self._write_latest_movement_practice_pointer(session)
        return self._summarize_movement_practice_session(session)

    def practice_mouse_click(self, attempts: Optional[int] = None) -> str:
        settings = self.config.get("desktop_organizer", {})
        return self._practice_mouse_gesture(
            skill_key="click",
            mode="mouse_click_practice",
            gesture="click_practice",
            category="PracticaClickMouse",
            summary_label="click simple",
            attempts=attempts,
            default_attempts=int(settings.get("mouse_click_practice_attempts", 20)),
            button="left",
            clicks=1,
            close_menu=False,
        )

    def practice_mouse_double_click(self, attempts: Optional[int] = None) -> str:
        settings = self.config.get("desktop_organizer", {})
        return self._practice_mouse_gesture(
            skill_key="double_click",
            mode="mouse_double_click_practice",
            gesture="double_click_practice",
            category="PracticaDobleClickMouse",
            summary_label="doble click",
            attempts=attempts,
            default_attempts=int(settings.get("mouse_double_click_practice_attempts", 20)),
            button="left",
            clicks=2,
            close_menu=False,
        )

    def practice_mouse_right_click(self, attempts: Optional[int] = None) -> str:
        settings = self.config.get("desktop_organizer", {})
        return self._practice_mouse_gesture(
            skill_key="right_click",
            mode="mouse_right_click_practice",
            gesture="right_click_practice",
            category="PracticaClickDerechoMouse",
            summary_label="click derecho",
            attempts=attempts,
            default_attempts=int(settings.get("mouse_right_click_practice_attempts", 20)),
            button="right",
            clicks=1,
            close_menu=True,
        )

    def practice_mouse_selection(self, attempts: Optional[int] = None) -> str:
        settings = self.config.get("desktop_organizer", {})
        attempt_count = self._bounded_practice_attempts(
            attempts,
            default_value=int(settings.get("mouse_selection_practice_attempts", 20)),
        )
        root_name = str(settings.get("mouse_practice_root_name", "_Raphel_Practica_Mouse"))
        desktop = self._desktop_path()
        source_dir = desktop / root_name / "Seleccion"
        ensure_directory(source_dir)

        session_id = f"selection_practice_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        session = DesktopLearningSession(
            session_id=session_id,
            created_at=datetime.now().isoformat(timespec="seconds"),
            mode="mouse_selection_practice",
            gesture_policy="selection_visual_practice",
            desktop_path=str(desktop),
            root_folder=str(source_dir),
            manifest_path=str(self.sessions_dir / f"{session_id}.json"),
        )
        session.notes.append(
            "Sesion segura: crea archivos temporales y verifica si la seleccion visual fue detectada."
        )

        self._record_session_header(session)
        for index in range(1, attempt_count + 1):
            if self._stop_requested():
                self._mark_practice_stopped(session, "seleccion visual")
                break
            source = source_dir / f"raphel_practica_seleccion_{session.session_id}_{index:02d}.txt"
            source.write_text("Archivo temporal para practicar seleccion visual.\n", encoding="utf-8")
            started = time.perf_counter()
            point: Optional[Tuple[int, int]] = None
            confirmed_point: Optional[Tuple[int, int]] = None
            moved_mouse_to_selection = False
            verification_method = ""
            try:
                self._emit(f"Practica seleccion visual {index}/{attempt_count}: {source.name}", "info")
                if self._uses_default_file_selector:
                    self._select_file_for_selection_practice(source)
                else:
                    self.file_selector(source)
                self.sleep(0.45)
                point, confirmed_point, verification_method = self._confirm_file_item_selection(source)
                moved_mouse_to_selection = point is not None
                verified = confirmed_point is not None
                status = "completed" if verified else "failed"
                error = "" if verified else "No confirme visualmente la seleccion despues del click."
            except Exception as exc:
                verified = False
                status = "failed"
                error = str(exc)
            finally:
                self._tidy_temporary_explorer_windows(f"terminar seleccion visual {source.name}")

            record = DesktopLearningMoveRecord(
                source=str(source),
                destination="visual-selection",
                category="PracticaSeleccionVisual",
                gesture="selection_visual_practice",
                status=status,
                duration_seconds=round(time.perf_counter() - started, 3),
                verified=verified,
                error=error,
                details={
                    "selected_file": source.name,
                    "point": list(point) if point else None,
                    "confirmed_point": list(confirmed_point) if confirmed_point else None,
                    "moved_mouse_to_selection": moved_mouse_to_selection,
                    "verification_method": verification_method,
                    "practice": True,
                },
            )
            session.moves.append(record)
            self._record_move(session, record)
            self._record_mouse_step(
                reason="practica seleccion visual",
                status=status,
                payload=record.details,
            )
            self._write_manifest(session)

        self._record_mouse_simple_practice_summary(
            session=session,
            skill_key="selection",
            summary_label="seleccion visual",
        )
        self._record_session_header(session)
        self._write_manifest(session)
        self._write_latest_gesture_practice_pointer(session, skill_key="selection")
        return self._summarize_simple_practice_session(session, "selection", "seleccion visual")

    def practice_mouse_detection(self, attempts: Optional[int] = None) -> str:
        settings = self.config.get("desktop_organizer", {})
        attempt_count = self._bounded_practice_attempts(
            attempts,
            default_value=int(settings.get("mouse_selection_practice_attempts", 20)),
        )
        root_name = str(settings.get("mouse_practice_root_name", "_Raphel_Practica_Mouse"))
        desktop = self._desktop_path()
        source_dir = desktop / root_name / "Deteccion"
        ensure_directory(source_dir)

        session_id = f"detection_practice_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        session = DesktopLearningSession(
            session_id=session_id,
            created_at=datetime.now().isoformat(timespec="seconds"),
            mode="mouse_detection_practice",
            gesture_policy="detection_visual_practice",
            desktop_path=str(desktop),
            root_folder=str(source_dir),
            manifest_path=str(self.sessions_dir / f"{session_id}.json"),
        )
        session.notes.append(
            "Sesion segura: crea distractores temporales y verifica deteccion reutilizable del archivo correcto."
        )

        self._record_session_header(session)
        for index in range(1, attempt_count + 1):
            if self._stop_requested():
                self._mark_practice_stopped(session, "deteccion visual")
                break

            layout = self._create_drag_practice_layout(
                source_dir=source_dir,
                session_id=session.session_id,
                attempt_number=index,
            )
            source = Path(layout["target_path"])
            started = time.perf_counter()
            point: Optional[Tuple[int, int]] = None
            confirmed_point: Optional[Tuple[int, int]] = None
            verification_method = ""
            selection_method = "not_selected"
            initial_detection: Dict[str, Any] = {}
            reused_detection: Dict[str, Any] = {}
            reused_detection_confirmed = False
            try:
                self._emit(f"Practica deteccion visual {index}/{attempt_count}: {source.name}", "info")
                self._open_folder_visible(source.parent, click_body=True)
                self.sleep(0.18)
                selection_method = self._select_file_for_drag(source)
                self.sleep(0.22)
                initial_detection = dict(
                    self._find_file_item_detection_with_uia(source) or self._last_selected_item_detection
                )
                point, confirmed_point, verification_method = self._confirm_file_item_selection(source)
                self.sleep(0.14)
                reused_detection = dict(
                    self._find_file_item_detection_with_uia(source) or self._last_selected_item_detection
                )
                reused_point = reused_detection.get("point") if isinstance(reused_detection, dict) else None
                reused_detection_confirmed = isinstance(reused_point, list) and len(reused_point) == 2
                verified = bool(initial_detection) and confirmed_point is not None and reused_detection_confirmed
                status = "completed" if verified else "failed"
                error = (
                    ""
                    if verified
                    else "No logre detectar, confirmar y reutilizar la deteccion del archivo correcto."
                )
            except Exception as exc:
                verified = False
                status = "failed"
                error = str(exc)
            finally:
                self._clean_drag_practice_files(source_dir)
                self._tidy_temporary_explorer_windows(f"terminar deteccion visual {source.name}")

            record = DesktopLearningMoveRecord(
                source=str(source),
                destination="visual-detection",
                category="PracticaDeteccionVisual",
                gesture="detection_visual_practice",
                status=status,
                duration_seconds=round(time.perf_counter() - started, 3),
                verified=verified,
                error=error,
                details={
                    "selected_file": source.name,
                    "point": list(point) if point else None,
                    "confirmed_point": list(confirmed_point) if confirmed_point else None,
                    "selection_method": selection_method,
                    "verification_method": verification_method,
                    "initial_detection": initial_detection,
                    "reused_detection": reused_detection,
                    "reused_detection_confirmed": reused_detection_confirmed,
                    "distractor_count": layout.get("distractor_count", 0),
                    "practice_layout": layout,
                    "practice": True,
                },
            )
            session.moves.append(record)
            self._record_move(session, record)
            self._record_mouse_step(
                reason="practica deteccion visual",
                status=status,
                payload=record.details,
            )
            self._write_manifest(session)

        self._record_mouse_detection_practice_summary(session)
        self._record_session_header(session)
        self._write_manifest(session)
        self._write_latest_gesture_practice_pointer(session, skill_key="detection")
        return self._summarize_detection_practice_session(session)

    def practice_mouse_workflow(self, attempts: Optional[int] = None) -> str:
        settings = self.config.get("desktop_organizer", {})
        attempt_count = self._bounded_practice_attempts(
            attempts,
            default_value=int(settings.get("mouse_workflow_practice_attempts", 5)),
        )
        root_name = str(settings.get("mouse_practice_root_name", "_Raphel_Practica_Mouse"))
        desktop = self._desktop_path()
        root = desktop / root_name
        source_dir = root / "FlujoEntrada"
        destination_dir = root / "FlujoDestino"
        ensure_directory(source_dir)
        ensure_directory(destination_dir)

        session_id = f"workflow_practice_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        session = DesktopLearningSession(
            session_id=session_id,
            created_at=datetime.now().isoformat(timespec="seconds"),
            mode="mouse_workflow_practice",
            gesture_policy="safe_workflow_practice",
            desktop_path=str(desktop),
            root_folder=str(root),
            manifest_path=str(self.sessions_dir / f"{session_id}.json"),
        )
        session.notes.append(
            "Sesion segura: practica seleccion, drag/fallback y verificacion con archivos temporales."
        )
        session.notes.append(
            (
                "Entrenamiento Windows guiado: enfocar Explorer, navegar origen/destino, "
                "seleccionar item visible y verificar el movimiento sin depender de resultados de busqueda."
            )
        )

        self._record_session_header(session)
        self._begin_explorer_reuse_session(enabled=self.reuse_explorer_windows_per_session)
        try:
            for index in range(1, attempt_count + 1):
                if self._stop_requested():
                    self._mark_practice_stopped(session, "flujo completo seguro")
                    break
                source = source_dir / f"raphel_practica_flujo_{session.session_id}_{index:02d}.txt"
                destination = destination_dir / source.name
                source.write_text("Archivo temporal para practicar flujo completo.\n", encoding="utf-8")
                if destination.exists():
                    destination.unlink()
                record = self._move_path_visible(
                    source=source,
                    destination=destination,
                    category="PracticaFlujoSeguro",
                    session=session,
                    gesture="drag_then_cut_paste",
                )
                record.details["practice"] = True
                record.details["safe_workflow"] = True
                record.details["instruction_profile"] = "windows_explorer_guided_workflow"
                record.details["instruction_scope"] = "window_focus+folder_navigation+visible_selection+move+verification"
                record.details["instruction_steps"] = self._windows_workflow_instruction_steps(
                    source,
                    destination,
                )
                session.moves.append(record)
                self._record_move(session, record)
                self._write_manifest(session)
        finally:
            self._end_explorer_reuse_session("terminar practica flujo completo")

        self._record_mouse_simple_practice_summary(
            session=session,
            skill_key="workflow",
            summary_label="flujo completo seguro",
        )
        self._record_session_header(session)
        self._write_manifest(session)
        self._write_latest_gesture_practice_pointer(session, skill_key="workflow")
        return self._summarize_simple_practice_session(session, "workflow", "flujo completo seguro")

    def undo_last_session(self) -> str:
        latest = self.store.read_latest_pointer("latest.json")
        if not latest:
            return "No hay una sesion de ordenado visible para deshacer."
        manifest_path = Path(str(latest.get("manifest_path", "")))
        if not manifest_path.exists():
            return "No encontre el manifiesto de la ultima sesion."

        payload = self._read_json(manifest_path)
        completed_moves = [
            move
            for move in payload.get("moves", [])
            if move.get("status") == "completed" and move.get("verified")
        ]
        if not completed_moves:
            return "La ultima sesion no tiene movimientos completados para deshacer."

        undo_session = DesktopLearningSession(
            session_id=f"undo_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            created_at=datetime.now().isoformat(timespec="seconds"),
            mode="ui_learning_undo",
            gesture_policy=str(payload.get("gesture_policy", "mixed_gradual")),
            desktop_path=str(payload.get("desktop_path", "")),
            root_folder=str(payload.get("root_folder", "")),
            manifest_path="",
        )
        undo_session.manifest_path = str(self.sessions_dir / f"{undo_session.session_id}.json")

        for move in reversed(completed_moves):
            reverse_operation = DesktopMoveOperation(
                source=str(move["destination"]),
                destination=str(move["source"]),
                category=str(move.get("category", "Undo")),
                kind="file",
            )
            record = self._move_path_visible(
                source=Path(reverse_operation.source),
                destination=Path(reverse_operation.destination),
                category=reverse_operation.category,
                session=undo_session,
                gesture="cut_paste_visible_undo",
            )
            undo_session.moves.append(record)
            self._record_move(undo_session, record)
            self._write_manifest(undo_session)

        self._write_manifest(undo_session)
        completed = sum(1 for move in undo_session.moves if move.status == "completed")
        failed = sum(1 for move in undo_session.moves if move.status == "failed")
        return (
            f"Deshacer visible completado. Restaurados: {completed}. "
            f"Fallidos: {failed}. Manifiesto: {undo_session.manifest_path}"
        )

    def _prepare_root_and_categories(
        self,
        preview: DesktopOrganizationPreview,
        operations: List[DesktopMoveOperation],
        session: DesktopLearningSession,
    ) -> None:
        root = Path(preview.root_folder)
        desktop = Path(preview.desktop_path)
        self._ensure_folder_visible(parent=desktop, folder=root, session=session)
        for category in sorted({operation.category for operation in operations}):
            created = self._ensure_folder_visible(parent=root, folder=root / category, session=session)
            if not created:
                session.skipped.append(
                    {
                        "category": category,
                        "reason": f"No se pudo preparar la carpeta visible {root / category}",
                    }
                )

    def _ensure_folder_visible(
        self,
        parent: Path,
        folder: Path,
        session: DesktopLearningSession,
    ) -> bool:
        if folder.exists():
            session.notes.append(f"Carpeta ya existia: {folder}")
            return True
        self._emit(f"Creando carpeta visible: {folder.name}", "info")
        attempts = 2
        for attempt in range(1, attempts + 1):
            try:
                if attempt > 1:
                    self._emit(f"Reintentando creacion visible de {folder.name}...", "warning")
                    self._explorer_ready = False
                self._open_folder_visible(parent, click_body=True)
                self._click_explorer_body("preparar creacion de carpeta")
                self.automation.press_keys(["esc"])
                self.automation.hotkey("ctrl", "shift", "n")
                self.sleep(0.35)
                self.automation.write_text(folder.name, use_clipboard=True)
                self.sleep(0.15)
                self.automation.press_keys(["enter"])
                if self._wait_for_path(folder, timeout=2.5):
                    session.notes.append(f"Carpeta creada por UI: {folder}")
                    return True
            except Exception as exc:
                session.notes.append(f"Intento {attempt} fallo creando {folder}: {exc}")
                self._cancel_possible_dialog()

        session.notes.append(f"No se pudo crear por UI: {folder}")
        return False

    def _move_operation_visible(
        self,
        operation: DesktopMoveOperation,
        preview: DesktopOrganizationPreview,
        session: DesktopLearningSession,
        gesture_policy: str,
    ) -> DesktopLearningMoveRecord:
        source = Path(operation.source)
        raw_destination = Path(preview.root_folder) / operation.category / source.name
        if raw_destination.exists():
            return DesktopLearningMoveRecord(
                source=str(source),
                destination=str(raw_destination),
                category=operation.category,
                gesture="none",
                status="requires_manual_review",
                verified=False,
                error="Destino existente; no se sobrescribe ni se renombra automaticamente.",
            )
        return self._move_path_visible(
            source=source,
            destination=raw_destination,
            category=operation.category,
            session=session,
            gesture=self._resolve_gesture(gesture_policy),
        )

    def _move_path_visible(
        self,
        source: Path,
        destination: Path,
        category: str,
        session: DesktopLearningSession,
        gesture: str,
    ) -> DesktopLearningMoveRecord:
        started = time.perf_counter()
        if not source.exists():
            return DesktopLearningMoveRecord(
                source=str(source),
                destination=str(destination),
                category=category,
                gesture=gesture,
                status="failed",
                duration_seconds=0.0,
                verified=False,
                error="El origen ya no existe.",
            )
        if destination.exists():
            return DesktopLearningMoveRecord(
                source=str(source),
                destination=str(destination),
                category=category,
                gesture=gesture,
                status="requires_manual_review",
                duration_seconds=0.0,
                verified=False,
                error="Destino existente; movimiento omitido.",
            )

        try:
            desktop_drag_record: Optional[DesktopLearningMoveRecord] = None
            drag_record: Optional[DesktopLearningMoveRecord] = None
            if gesture in {"drag_then_cut_paste", "drag_and_drop"}:
                if self._should_try_desktop_surface_drag(source):
                    desktop_drag_record = self._attempt_desktop_surface_drag_move(
                        source=source,
                        destination=destination,
                        category=category,
                        session=session,
                        gesture=gesture,
                        started=started,
                    )
                    if desktop_drag_record.verified:
                        desktop_drag_record = self._finalize_move_history(
                            final_record=desktop_drag_record,
                            path_taken="desktop_drag",
                            desktop_record=desktop_drag_record,
                        )
                        return self._finish_move_record(desktop_drag_record, source)
                    self._emit(
                        (
                            f"El drag desde escritorio real no movio {source.name}; "
                            "continuo con rescate visible en Explorer."
                        ),
                        "warning",
                    )
                    session.notes.append(
                        f"Fallback tras drag desde escritorio fallido: {source} -> {destination}"
                    )
                drag_record = self._attempt_drag_move(
                    source=source,
                    destination=destination,
                    category=category,
                    session=session,
                    gesture=gesture,
                        started=started,
                    )
                if drag_record.verified or gesture == "drag_and_drop":
                    drag_record = self._finalize_move_history(
                        final_record=drag_record,
                        path_taken="explorer_drag",
                        desktop_record=desktop_drag_record,
                        explorer_record=drag_record,
                    )
                    return self._finish_move_record(drag_record, source)
                self._emit(
                    f"El arrastre no movio {source.name}; aplicando rescate con cortar/pegar visible.",
                    "warning",
                )
                session.notes.append(f"Fallback tras drag fallido: {source} -> {destination}")

            record = self._attempt_visible_cut_paste_move(
                source=source,
                destination=destination,
                category=category,
                gesture=gesture,
                started=started,
            )
            record = self._finalize_move_history(
                final_record=record,
                path_taken="visible_cut_paste",
                desktop_record=desktop_drag_record,
                explorer_record=drag_record,
                cut_paste_record=record,
            )
            return self._finish_move_record(record, source)
        except Exception as exc:
            self._cancel_possible_dialog()
            record = DesktopLearningMoveRecord(
                source=str(source),
                destination=str(destination),
                category=category,
                gesture=gesture,
                status="failed",
                duration_seconds=round(time.perf_counter() - started, 3),
                verified=False,
                error=str(exc),
            )
            return self._finish_move_record(record, source)

    def _attempt_visible_cut_paste_move(
        self,
        source: Path,
        destination: Path,
        category: str,
        gesture: str,
        started: float,
    ) -> DesktopLearningMoveRecord:
        try:
            self._emit(f"Seleccionando visible: {source.name}", "info")
            selection_method = ""
            if self._reuse_session_explorer_windows:
                self._ensure_drag_window_for_side(source.parent, side="left")
                try:
                    selection_method = self._select_file_for_drag(source)
                except Exception as exc:
                    self._emit(
                        (
                            f"La reseleccion dentro de la ventana reutilizada fallo para {source.name}; "
                            "caigo al selector general."
                        ),
                        "warning",
                    )
                    self._record_mouse_step(
                        reason="reseleccionar archivo para cut/paste reutilizado",
                        status="failed",
                        payload={"source": str(source), "error": str(exc)},
                    )
                    self.file_selector(source)
                    selection_method = "fallback_file_selector"
            else:
                self.file_selector(source)
                selection_method = "general_file_selector"
            self.sleep(0.5)
            self._move_mouse_inside_explorer("ubicar archivo seleccionado")
            self.automation.hotkey("ctrl", "x")
            self.sleep(0.25)
            if self._reuse_session_explorer_windows:
                self._ensure_drag_window_for_side(destination.parent, side="right")
            else:
                self._open_folder_visible(destination.parent, click_body=True)
            self._click_explorer_body("preparar pegado")
            self.sleep(0.25)
            self.automation.hotkey("ctrl", "v")
            self._wait_for_path(destination, timeout=3.0)

            verified = (not source.exists()) and destination.exists()
            if not verified:
                self._cancel_possible_dialog()
                status = "failed"
                error = (
                    "La verificacion fallo: origen/destino no reflejan el movimiento esperado "
                    f"(origen_existe={source.exists()}, destino_existe={destination.exists()})."
                )
                self._emit(
                    (
                        f"Rescate cut/paste no verificado para {source.name}: "
                        f"origen_existe={source.exists()}, destino_existe={destination.exists()}."
                    ),
                    "warning",
                )
            else:
                status = "completed"
                error = ""
                self._emit(f"Rescate cut/paste verificado: {source.name} llego a {destination.parent.name}.", "info")

            return DesktopLearningMoveRecord(
                source=str(source),
                destination=str(destination),
                category=category,
                gesture=gesture,
                status=status,
                duration_seconds=round(time.perf_counter() - started, 3),
                verified=verified,
                error=error,
                details={
                    "attempted_cut_paste": True,
                    "operation": "visible_ctrl_x_ctrl_v",
                    "selection_method": selection_method,
                    "reused_session_windows": self._reuse_session_explorer_windows,
                    "source_exists_after": source.exists(),
                    "destination_exists_after": destination.exists(),
                },
            )
        except Exception as exc:
            self._cancel_possible_dialog()
            return DesktopLearningMoveRecord(
                source=str(source),
                destination=str(destination),
                category=category,
                gesture=gesture,
                status="failed",
                duration_seconds=round(time.perf_counter() - started, 3),
                verified=False,
                error=str(exc),
                details={
                    "attempted_cut_paste": True,
                    "operation": "visible_ctrl_x_ctrl_v",
                    "reused_session_windows": self._reuse_session_explorer_windows,
                    "error": str(exc),
                },
            )

    def _should_try_desktop_surface_drag(self, source: Path) -> bool:
        settings = self.config.get("desktop_organizer", {})
        if not bool(settings.get("desktop_surface_source_first", True)):
            return False
        if not hasattr(self.automation, "minimize_all_windows"):
            return False
        try:
            return source.parent == self._desktop_path()
        except Exception:
            return False

    def _attempt_payload_from_record(
        self,
        record: DesktopLearningMoveRecord,
        attempt_type: str,
    ) -> Dict[str, Any]:
        details = dict(record.details or {})
        payload = {
            "attempt_type": attempt_type,
            "status": record.status,
            "verified": record.verified,
            "error": record.error,
            "duration_seconds": record.duration_seconds,
            "failure_stage": str(details.get("failure_stage") or ""),
            "failure_reason": str(details.get("failure_reason") or record.error or ""),
            "selection_method": str(details.get("selection_method") or ""),
            "source_strategy": str(details.get("source_strategy") or ""),
            "source_point": details.get("source_point"),
            "destination_point": details.get("destination_point"),
            "selection_detection": details.get("selection_detection") or {},
            "selection_footprint": details.get("selection_footprint") or {},
            "destination_window": details.get("destination_window") or {},
            "pre_drag_verification": details.get("pre_drag_verification") or {},
            "drag_details": details.get("drag_details") or {},
            "details": details,
        }
        return payload

    def _finalize_move_history(
        self,
        final_record: DesktopLearningMoveRecord,
        path_taken: str,
        desktop_record: Optional[DesktopLearningMoveRecord] = None,
        explorer_record: Optional[DesktopLearningMoveRecord] = None,
        cut_paste_record: Optional[DesktopLearningMoveRecord] = None,
    ) -> DesktopLearningMoveRecord:
        prior_failed_attempts = [
            record
            for record in (desktop_record, explorer_record)
            if record is not None and record is not final_record and not record.verified
        ]
        fallback_used = bool(prior_failed_attempts)
        if final_record.verified:
            final_record.status = "completed_with_fallback" if fallback_used else "completed"

        final_record.path_taken = path_taken
        final_record.fallback_used = fallback_used
        final_record.desktop_attempt = (
            self._attempt_payload_from_record(desktop_record, "desktop_drag")
            if desktop_record is not None
            else {}
        )

        fallback_attempt: Dict[str, Any] = {}
        if path_taken == "explorer_drag" and desktop_record is not None and explorer_record is not None:
            fallback_attempt = self._attempt_payload_from_record(explorer_record, "explorer_drag")
        elif path_taken == "visible_cut_paste":
            if explorer_record is not None:
                fallback_attempt = self._attempt_payload_from_record(explorer_record, "explorer_drag")
                if cut_paste_record is not None:
                    fallback_attempt["next_fallback"] = self._attempt_payload_from_record(
                        cut_paste_record,
                        "visible_cut_paste",
                    )
            elif desktop_record is not None and cut_paste_record is not None:
                fallback_attempt = self._attempt_payload_from_record(
                    cut_paste_record,
                    "visible_cut_paste",
                )
        final_record.fallback_attempt = fallback_attempt

        details = dict(final_record.details or {})
        details["path_taken"] = path_taken
        details["fallback_used"] = fallback_used
        if final_record.desktop_attempt:
            details["desktop_attempt"] = final_record.desktop_attempt
        if final_record.fallback_attempt:
            details["fallback_attempt"] = final_record.fallback_attempt
        final_record.details = details
        return final_record

    def _attempt_desktop_surface_drag_move(
        self,
        source: Path,
        destination: Path,
        category: str,
        session: DesktopLearningSession,
        gesture: str,
        started: float,
    ) -> DesktopLearningMoveRecord:
        source_point: Optional[Tuple[int, int]] = None
        destination_point: Optional[Tuple[int, int]] = None
        selection_detection: Dict[str, Any] = {}
        selection_footprint: Dict[str, Any] = {}
        destination_window: Dict[str, Any] = {}
        pre_drag_verification: Dict[str, Any] = {}
        profile = dict(self._choose_drag_profile(category))
        profile_name = str(profile.get("name", "unknown"))
        snap_side = "right"
        try:
            self._emit(f"Intentando drag fase 2 desde escritorio real: {source.name}", "info")
            source_point, selection_detection = self._select_desktop_item_for_drag(source)
            if not source_point:
                raise DesktopDragAttemptError(
                    "desktop_detection",
                    f"No pude detectar {source.name} directamente en el escritorio.",
                )

            selection_footprint = self._build_selection_footprint(source, source_point, selection_detection)
            snap_side = self._preferred_destination_snap_side(source_point, selection_detection)
            try:
                destination_window = self._open_destination_window_for_drag(
                    destination.parent,
                    preferred_side=snap_side,
                )
            except Exception as exc:
                raise DesktopDragAttemptError(
                    "desktop_focus",
                    f"No pude abrir o enfocar la ventana destino para {destination.parent.name}: {exc}",
                ) from exc
            pre_drag_verification = self._revalidate_desktop_drag_continuity(
                source=source,
                source_point=source_point,
                selection_detection=selection_detection,
                destination_window=destination_window,
                snap_side=snap_side,
            )
            if not pre_drag_verification.get("coherent", False):
                failure_stage = (
                    "source_occluded"
                    if pre_drag_verification.get("source_occluded")
                    else "selection_persistence"
                )
                raise DesktopDragAttemptError(
                    failure_stage,
                    str(
                        pre_drag_verification.get("reason")
                        or "La seleccion del escritorio perdio continuidad antes del drag."
                    ),
                )

            destination_point = self._body_point_from_window_snapshot(
                destination_window.get("window") or {},
                horizontal=float(profile.get("destination_horizontal", 0.62)),
                vertical=float(profile.get("destination_vertical", 0.42)),
            ) or self._explorer_body_point(
                horizontal=float(profile.get("destination_horizontal", 0.62)),
                vertical=float(profile.get("destination_vertical", 0.42)),
            )
            if not destination_point:
                raise DesktopDragAttemptError(
                    "drag_execution",
                    "No pude calcular el punto destino para el drag fase 2.",
                )

            drag_details = self._perform_drag_with_profile(
                source_point[0],
                source_point[1],
                destination_point[0],
                destination_point[1],
                profile,
            )
            self._wait_for_path(destination, timeout=3.0)
            verified = (not source.exists()) and destination.exists()
            error = ""
            if not verified:
                error = "El drag desde escritorio real no produjo el movimiento esperado."
            return DesktopLearningMoveRecord(
                source=str(source),
                destination=str(destination),
                category=category,
                gesture=gesture,
                status="completed" if verified else "failed",
                duration_seconds=round(time.perf_counter() - started, 3),
                verified=verified,
                error=error,
                details={
                    "attempted_drag": True,
                    "desktop_surface": True,
                    "profile": profile_name,
                    "selection_method": "desktop_uia_file_item",
                    "source_strategy": "desktop_surface_uia",
                    "selection_footprint": selection_footprint,
                    "destination_window": destination_window,
                    "pre_drag_verification": pre_drag_verification,
                    "snap_side": snap_side,
                    "source_point": list(source_point),
                    "destination_point": list(destination_point) if destination_point else None,
                    "selection_detection": selection_detection,
                    "drag_details": drag_details,
                    "failure_stage": "" if verified else "post_drag_verification",
                    "failure_reason": error,
                },
            )
        except Exception as exc:
            self._cancel_possible_dialog()
            failure_stage = (
                exc.stage
                if isinstance(exc, DesktopDragAttemptError)
                else "drag_execution"
            )
            return DesktopLearningMoveRecord(
                source=str(source),
                destination=str(destination),
                category=category,
                gesture=gesture,
                status="failed",
                duration_seconds=round(time.perf_counter() - started, 3),
                verified=False,
                error=str(exc),
                details={
                    "attempted_drag": True,
                    "desktop_surface": True,
                    "profile": profile_name,
                    "selection_method": "desktop_uia_file_item",
                    "source_strategy": "desktop_surface_uia",
                    "selection_footprint": selection_footprint,
                    "destination_window": destination_window,
                    "pre_drag_verification": pre_drag_verification,
                    "snap_side": snap_side,
                    "source_point": list(source_point) if source_point else None,
                    "destination_point": list(destination_point) if destination_point else None,
                    "selection_detection": selection_detection,
                    "failure_stage": failure_stage,
                    "failure_reason": str(exc),
                },
            )

    def _attempt_drag_move(
        self,
        source: Path,
        destination: Path,
        category: str,
        session: DesktopLearningSession,
        gesture: str,
        started: float,
        profile_override: Optional[Dict[str, Any]] = None,
    ) -> DesktopLearningMoveRecord:
        source_point: Optional[tuple[int, int]] = None
        destination_point: Optional[tuple[int, int]] = None
        profile = dict(profile_override or self._choose_drag_profile(category))
        profile_name = str(profile.get("name", "unknown"))
        planned_profile_name = profile_name
        used_visual_selection = False
        confirmed_visual_selection = False
        source_strategy = "estimated_profile"
        selection_detection: Dict[str, Any] = {}
        pre_drag_verification: Dict[str, Any] = {}
        window_layout_repair: Dict[str, Any] = {}
        try:
            self._emit(f"Preparando arrastre visible: {source.name}", "info")
            self._prepare_drag_windows(source.parent, destination.parent)
            if self._should_force_strict_window_layout(category):
                self._stabilize_explorer_drag_layout(
                    source.parent,
                    destination.parent,
                    reason=f"aplicar layout estricto aprendido para {category}",
                )
            selection_method = self._select_file_for_drag(source)
            self.sleep(0.45)
            source_window = self._active_or_first_explorer_window()
            source_point, used_visual_selection, confirmed_visual_selection = (
                self._confirm_file_item_for_drag(source)
            )
            selection_detection = dict(self._last_selected_item_detection)
            if not source_point or not confirmed_visual_selection:
                self._emit(
                    "La seleccion inicial no quedo confirmada; intento seleccionar "
                    "el primer resultado con teclado.",
                    "warning",
                )
                self._select_search_result_with_keyboard(source)
                self.sleep(0.25)
                source_point, used_visual_selection, confirmed_visual_selection = (
                    self._confirm_file_item_for_drag(source)
                )
                selection_detection = dict(self._last_selected_item_detection)
                selection_method = f"{selection_method}+keyboard_result"
            if source_point and confirmed_visual_selection:
                self._emit(
                    f"Seleccion visual detectada para drag en {source_point}; "
                    f"confirmada={confirmed_visual_selection}",
                    "info",
                )
            else:
                source_strategy = "selection_unconfirmed" if source_point else "selection_required"
                profile_name = "source_visual_selection"
                message = (
                    f"No pude confirmar visualmente el archivo {source.name}; "
                    "cancelo este drag para no aprender desde una seleccion dudosa."
                )
                self._emit(message, "warning")
                raise RuntimeError(message)

            self._focus_folder_window(
                destination.parent,
                "volver a Salida/Destino para calcular punto de destino",
            )
            destination_window = self._active_or_first_explorer_window()
            pre_drag_verification = self._revalidate_explorer_drag_continuity(
                source=source,
                source_point=source_point,
                selection_detection=selection_detection,
                source_window=source_window,
                destination_window=destination_window,
                destination=destination,
            )
            if not pre_drag_verification.get("coherent", False):
                window_layout_repair = self._repair_explorer_drag_layout(
                    source=source,
                    destination=destination,
                    category=category,
                    selection_method=selection_method,
                    source_point=source_point,
                    selection_detection=selection_detection,
                )
                repaired_verification = dict(window_layout_repair.get("verification") or {})
                if window_layout_repair.get("recovered"):
                    selection_method = f"{selection_method}+layout_repair"
                    repaired_point = window_layout_repair.get("source_point") or []
                    if isinstance(repaired_point, list) and len(repaired_point) == 2:
                        source_point = (int(repaired_point[0]), int(repaired_point[1]))
                    repaired_detection = window_layout_repair.get("selection_detection") or {}
                    if isinstance(repaired_detection, dict) and repaired_detection:
                        selection_detection = repaired_detection
                    pre_drag_verification = repaired_verification
                    self._focus_folder_window(
                        destination.parent,
                        "volver a Salida/Destino despues de reparar layout",
                    )
                    destination_window = self._active_or_first_explorer_window()
                else:
                    reason = str(
                        repaired_verification.get("reason")
                        or pre_drag_verification.get("reason")
                        or window_layout_repair.get("reason")
                        or "La disposicion de ventanas no permite un drag fiable."
                    )
                    self._emit(
                        (
                            f"Bloqueo visual antes del drag para {source.name}: {reason} "
                            "Cambio a rescate verificado en vez de insistir con mas arrastres."
                        ),
                        "warning",
                    )
                    raise RuntimeError(reason)
            if not pre_drag_verification.get("coherent", False):
                reason = str(
                    pre_drag_verification.get("reason")
                    or "La disposicion de ventanas no permite un drag fiable."
                )
                self._emit(
                    (
                        f"Bloqueo visual antes del drag para {source.name}: {reason} "
                        "Cambio a rescate verificado en vez de insistir con mas arrastres."
                    ),
                    "warning",
                )
                raise RuntimeError(reason)
            destination_point = self._explorer_body_point(
                horizontal=float(profile.get("destination_horizontal", 0.54)),
                vertical=float(profile.get("destination_vertical", 0.48)),
            )
            if not destination_point:
                raise RuntimeError("No pude calcular punto de destino para el arrastre.")

            source_strategy = "vision_selected_item" if used_visual_selection else "estimated_profile"
            end_x, end_y = destination_point
            verified, source_point, drag_attempts = self._try_drag_source_candidates(
                source=source,
                destination=destination,
                initial_source_point=source_point,
                destination_point=destination_point,
                profile=profile,
                profile_name=profile_name,
                planned_profile_name=planned_profile_name,
                selection_method=selection_method,
                source_strategy=source_strategy,
                used_visual_selection=used_visual_selection,
                confirmed_visual_selection=confirmed_visual_selection,
                selection_detection=selection_detection,
            )
            selected_attempt = drag_attempts[-1] if drag_attempts else {}
            drag_details = dict(selected_attempt.get("drag_details") or {})
            if verified:
                self._refine_drag_profile(
                    profile_name=profile_name,
                    source_point=source_point,
                    destination_point=destination_point,
                    source_window=source_window,
                    destination_window=destination_window,
                    duration=float(profile.get("duration", 0.9)),
                )
            self._learn_drag_outcome(
                profile_name=profile_name,
                category=category,
                success=verified,
                details={
                    "source": str(source),
                    "destination": str(destination),
                    "source_point": list(source_point),
                    "destination_point": list(destination_point),
                    "planned_profile": planned_profile_name,
                    "selection_method": selection_method,
                    "source_strategy": source_strategy,
                    "visual_selection": used_visual_selection,
                    "confirmed_visual_selection": confirmed_visual_selection,
                    "selection_detection": selection_detection,
                    "pre_drag_verification": pre_drag_verification,
                    "window_layout_mode": self._window_layout_mode_for_category(category),
                    "window_layout_repair": window_layout_repair,
                    "drag_details": drag_details,
                    "drag_attempts": drag_attempts,
                },
            )
            return DesktopLearningMoveRecord(
                source=str(source),
                destination=str(destination),
                category=category,
                gesture=gesture,
                status="completed" if verified else "failed",
                duration_seconds=round(time.perf_counter() - started, 3),
                verified=verified,
                error="" if verified else "El arrastre no produjo el movimiento esperado.",
                details={
                    "attempted_drag": True,
                    "profile": profile_name,
                    "planned_profile": planned_profile_name,
                    "selection_method": selection_method,
                    "source_strategy": source_strategy,
                    "visual_selection": used_visual_selection,
                    "confirmed_visual_selection": confirmed_visual_selection,
                    "source_point": list(source_point),
                    "destination_point": list(destination_point),
                    "selection_detection": selection_detection,
                    "pre_drag_verification": pre_drag_verification,
                    "window_layout_mode": self._window_layout_mode_for_category(category),
                    "window_layout_repair": window_layout_repair,
                    "drag_details": drag_details,
                    "drag_attempts": drag_attempts,
                },
            )
        except Exception as exc:
            self._cancel_possible_dialog()
            self._learn_drag_outcome(
                profile_name=profile_name,
                category=category,
                success=False,
                details={
                    "source": str(source),
                    "destination": str(destination),
                    "source_point": list(source_point) if source_point else None,
                    "destination_point": list(destination_point) if destination_point else None,
                    "planned_profile": planned_profile_name,
                    "selection_method": locals().get("selection_method", "not_selected"),
                    "source_strategy": source_strategy,
                    "visual_selection": used_visual_selection,
                    "confirmed_visual_selection": confirmed_visual_selection,
                    "selection_detection": selection_detection,
                    "pre_drag_verification": pre_drag_verification,
                    "window_layout_mode": self._window_layout_mode_for_category(category),
                    "window_layout_repair": window_layout_repair,
                    "error": str(exc),
                },
            )
            return DesktopLearningMoveRecord(
                source=str(source),
                destination=str(destination),
                category=category,
                gesture=gesture,
                status="failed",
                duration_seconds=round(time.perf_counter() - started, 3),
                verified=False,
                error=str(exc),
                details={
                    "attempted_drag": True,
                    "profile": profile_name,
                    "planned_profile": planned_profile_name,
                    "selection_method": locals().get("selection_method", "not_selected"),
                    "source_strategy": source_strategy,
                    "visual_selection": used_visual_selection,
                    "confirmed_visual_selection": confirmed_visual_selection,
                    "source_point": list(source_point) if source_point else None,
                    "destination_point": list(destination_point) if destination_point else None,
                    "selection_detection": selection_detection,
                    "pre_drag_verification": pre_drag_verification,
                    "window_layout_mode": self._window_layout_mode_for_category(category),
                    "window_layout_repair": window_layout_repair,
                },
            )

    def _try_drag_source_candidates(
        self,
        source: Path,
        destination: Path,
        initial_source_point: Tuple[int, int],
        destination_point: Tuple[int, int],
        profile: Dict[str, Any],
        profile_name: str,
        planned_profile_name: str,
        selection_method: str,
        source_strategy: str,
        used_visual_selection: bool,
        confirmed_visual_selection: bool,
        selection_detection: Dict[str, Any],
    ) -> Tuple[bool, Tuple[int, int], List[Dict[str, Any]]]:
        candidates = self._build_drag_source_candidates(initial_source_point, selection_detection)
        attempts: List[Dict[str, Any]] = []
        selected_point = initial_source_point

        for index, candidate in enumerate(candidates, start=1):
            point = tuple(candidate["point"])
            selected_point = (int(point[0]), int(point[1]))
            if index > 1:
                if not source.exists():
                    break
                self._emit(
                    (
                        f"Recalibrando drag: {source.name}, "
                        f"punto anterior no funciono; pruebo {candidate['label']}."
                    ),
                    "warning",
                )
                self._focus_folder_window(
                    source.parent,
                    "volver a origen para recalibrar seleccion",
                )
                self.sleep(0.15)
                try:
                    self._select_file_for_drag(source)
                    self.sleep(0.22)
                    reselected_point, _, reselected_confirmed = self._confirm_file_item_for_drag(source)
                    if not reselected_confirmed:
                        self._emit(
                            "No confirme seleccion al recalibrar; pruebo el siguiente punto conocido.",
                            "warning",
                        )
                    elif reselected_point:
                        fresh_detection = dict(self._last_selected_item_detection)
                        if fresh_detection:
                            selection_detection = fresh_detection
                            refreshed_candidates = self._build_drag_source_candidates(
                                reselected_point,
                                selection_detection,
                            )
                            current_label = str(candidate["label"])
                            candidate = next(
                                (
                                    item
                                    for item in refreshed_candidates
                                    if item["label"] == current_label
                                ),
                                refreshed_candidates[min(index - 1, len(refreshed_candidates) - 1)],
                            )
                            point = tuple(candidate["point"])
                            selected_point = (int(point[0]), int(point[1]))
                except Exception as exc:
                    self._emit(f"No pude recalibrar seleccion de drag: {exc}", "warning")

            start_x, start_y = selected_point
            end_x, end_y = destination_point
            self._focus_folder_window(
                source.parent,
                "volver a origen para iniciar drag desde el archivo",
            )
            self.sleep(0.15)
            self._emit(
                (
                    f"Subintento drag {index}/{len(candidates)} ({candidate['label']}): "
                    f"({start_x}, {start_y}) -> ({end_x}, {end_y})."
                ),
                "info",
            )
            self._emit(
                (
                    f"Puntos drag calculados ({profile_name}): "
                    f"({start_x}, {start_y}) -> ({end_x}, {end_y}); "
                    f"seleccion_visual={used_visual_selection}; "
                    f"confirmada={confirmed_visual_selection}"
                ),
                "info",
            )
            self._emit(
                f"Arrastrando con mouse: {source.name} -> {destination.parent.name}",
                "info",
            )
            drag_details = self._perform_drag_with_profile(start_x, start_y, end_x, end_y, profile)
            self._wait_for_path(destination, timeout=3.0)
            verified = (not source.exists()) and destination.exists()
            attempt_payload = {
                "candidate_index": index,
                "candidate_count": len(candidates),
                "candidate": candidate,
                "source": str(source),
                "destination": str(destination),
                "start": [start_x, start_y],
                "end": [end_x, end_y],
                "profile": profile_name,
                "planned_profile": planned_profile_name,
                "selection_method": selection_method,
                "source_strategy": source_strategy,
                "visual_selection": used_visual_selection,
                "confirmed_visual_selection": confirmed_visual_selection,
                "selection_detection": selection_detection,
                "drag_details": drag_details,
                "source_exists_after": source.exists(),
                "destination_exists_after": destination.exists(),
                "verified": verified,
            }
            attempts.append(attempt_payload)
            self._record_mouse_step(
                reason="subintento drag archivo a carpeta",
                status="success" if verified else "failure",
                payload=attempt_payload,
            )
            if verified:
                self._emit(
                    f"Drag verificado: {source.name} llego a {destination.parent.name} con {candidate['label']}.",
                    "info",
                )
                return True, selected_point, attempts
            self._emit(
                (
                    f"Drag no verificado con {candidate['label']} para {source.name}: "
                    f"origen_existe={source.exists()}, destino_existe={destination.exists()}."
                ),
                "warning",
            )

        return False, selected_point, attempts

    def _build_drag_source_candidates(
        self,
        source_point: Tuple[int, int],
        selection_detection: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        bounds = selection_detection.get("bounds") if selection_detection else None
        raw_candidates: List[Tuple[str, int, int]] = []
        if isinstance(bounds, list) and len(bounds) == 4:
            left, top, right, bottom = [int(value) for value in bounds]
            width = max(1, right - left)
            height = max(1, bottom - top)
            center_y = top + int(height * 0.52)
            upper_y = top + int(height * 0.35)
            lower_y = top + int(height * 0.68)
            # Explorer puede pintar toda la fila azul; estos puntos exploran icono, texto y fila.
            raw_candidates.extend(
                [
                    ("icono_izquierda", left + min(24, max(8, width - 4)), center_y),
                    ("texto_inicio", left + min(48, max(10, width - 4)), center_y),
                    ("texto_medio", left + min(78, max(12, width - 4)), center_y),
                    ("fila_arriba", left + min(48, max(10, width - 4)), upper_y),
                    ("fila_abajo", left + min(48, max(10, width - 4)), lower_y),
                ]
            )
            point = selection_detection.get("point")
            if isinstance(point, list) and len(point) == 2:
                raw_candidates.insert(0, ("punto_detectado", int(point[0]), int(point[1])))
        raw_candidates.append(("punto_inicial", int(source_point[0]), int(source_point[1])))

        seen: set[Tuple[int, int]] = set()
        candidates: List[Dict[str, Any]] = []
        for label, x, y in raw_candidates:
            key = (int(x), int(y))
            if key in seen:
                continue
            seen.add(key)
            candidates.append({"label": label, "point": [int(x), int(y)]})
        return candidates[:6] or [{"label": "punto_inicial", "point": [int(source_point[0]), int(source_point[1])]}]

    def _perform_drag_with_profile(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        duration = float(profile.get("duration", 0.9))
        drag_style = str(profile.get("drag_style", "smooth_hold"))
        pre_hold = float(profile.get("pre_hold", 0.2))
        post_hold = float(profile.get("post_hold", 0.1))
        steps = max(4, int(profile.get("steps", 12)))
        wiggle_pixels = max(0, int(profile.get("wiggle_pixels", 0)))
        details = {
            "style": drag_style,
            "duration": duration,
            "pre_hold": pre_hold,
            "post_hold": post_hold,
            "steps": steps,
            "wiggle_pixels": wiggle_pixels,
        }
        self._emit(
            (
                f"Estilo drag: {drag_style} "
                f"(hold={pre_hold}s, pasos={steps}, wiggle={wiggle_pixels}px)."
            ),
            "info",
        )
        if hasattr(self.automation, "drag_mouse_precise"):
            self.automation.drag_mouse_precise(
                start_x,
                start_y,
                end_x,
                end_y,
                duration=duration,
                button="left",
                pre_hold=pre_hold,
                post_hold=post_hold,
                steps=steps,
                wiggle_pixels=wiggle_pixels,
            )
            details["method"] = "drag_mouse_precise"
            return details

        self.automation.move_mouse(start_x, start_y, duration=0.2)
        self.sleep(max(0.0, min(pre_hold, 0.4)))
        self.automation.drag_mouse(
            start_x,
            start_y,
            end_x,
            end_y,
            duration=duration,
        )
        details["method"] = "drag_mouse"
        return details

    def _confirm_file_item_for_drag(
        self,
        source: Path,
    ) -> Tuple[Optional[Tuple[int, int]], bool, bool]:
        uia_detection = self._find_file_item_detection_with_uia(source)
        if uia_detection:
            point_raw = uia_detection.get("point") or []
            if isinstance(point_raw, list) and len(point_raw) == 2:
                point = (int(point_raw[0]), int(point_raw[1]))
                self._last_selected_item_detection = dict(uia_detection)
                try:
                    self._emit(
                        f"UIA encontro el archivo para drag en {point}: {source.name}",
                        "info",
                    )
                    self.automation.move_mouse(point[0], point[1], duration=0.2)
                    self.sleep(0.06)
                    self.automation.click(point[0], point[1], duration=0.06)
                    self.sleep(0.16)
                    self._record_mouse_step(
                        reason="confirmar archivo exacto para drag",
                        status="confirmed",
                        payload={"source": str(source), "detection": uia_detection},
                    )
                    return point, True, True
                except Exception as exc:
                    self._emit(f"UIA encontro archivo pero no pude confirmarlo con click: {exc}", "warning")

        return self._confirm_selected_item_for_drag()

    def _confirm_file_item_selection(
        self,
        source: Path,
    ) -> Tuple[Optional[Tuple[int, int]], Optional[Tuple[int, int]], str]:
        uia_detection = self._find_file_item_detection_with_uia(source)
        if uia_detection:
            point_raw = uia_detection.get("point") or []
            if isinstance(point_raw, list) and len(point_raw) == 2:
                point = (int(point_raw[0]), int(point_raw[1]))
                if self._point_within_usable_screen(point):
                    self._last_selected_item_detection = dict(uia_detection)
                    self._emit(f"UIA encontro archivo para seleccion en {point}: {source.name}", "info")
                    self.automation.move_mouse(point[0], point[1], duration=0.2)
                    self.sleep(0.06)
                    self.automation.click(point[0], point[1], duration=0.06)
                    self.sleep(0.18)
                    visual_confirmed = self._find_selected_item_point()
                    confirmed = visual_confirmed or point
                    method = "visual_after_uia_click" if visual_confirmed else "uia_file_item_click"
                    self._record_mouse_step(
                        reason="confirmar seleccion exacta",
                        status="confirmed",
                        payload={
                            "source": str(source),
                            "point": list(point),
                            "confirmed_point": list(confirmed),
                            "method": method,
                            "detection": uia_detection,
                        },
                    )
                    return point, confirmed, method

        point = self._find_selected_item_point()
        if not point:
            return None, None, "visual_selection_missing"
        if not self._point_within_usable_screen(point):
            return None, None, "visual_selection_offscreen"
        self._emit(f"Mouse UI: click sobre seleccion detectada en {point}", "info")
        self.automation.move_mouse(point[0], point[1], duration=0.22)
        self.sleep(0.06)
        self.automation.click(point[0], point[1], duration=0.06)
        self.sleep(0.12)
        confirmed = self._find_selected_item_point()
        return point, confirmed, "visual_selection_click"

    def _get_uia_client(self) -> Optional[Any]:
        if self._uia_client is not None:
            return self._uia_client
        if self._uia_init_failed:
            return None
        try:
            import comtypes.client

            uia_module = comtypes.client.GetModule("UIAutomationCore.dll")
            interface = getattr(uia_module, "IUIAutomation", None)
            create_kwargs = {"interface": interface} if interface is not None else {}
            try:
                self._uia_client = comtypes.client.CreateObject(
                    "UIAutomationClient.CUIAutomation",
                    **create_kwargs,
                )
            except OSError:
                self._uia_client = comtypes.client.CreateObject(
                    self.UIA_CLIENT_CLSID,
                    **create_kwargs,
                )
            return self._uia_client
        except Exception as exc:
            self._uia_init_failed = True
            self._emit(f"UIA no pudo inicializarse para drag: {exc}", "warning")
            return None

    def _find_file_item_detection_with_uia(self, source: Path) -> Optional[Dict[str, Any]]:
        if not hasattr(self.automation, "get_active_window_title"):
            return None
        try:
            import ctypes
            uia = self._get_uia_client()
            if uia is None:
                return None
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return None
            root = uia.ElementFromHandle(hwnd)
            if not root:
                return None

            names = [source.name]
            if source.stem not in names:
                names.append(source.stem)

            element = None
            match_name = ""
            for name in names:
                condition = uia.CreatePropertyCondition(30005, name)
                element = root.FindFirst(4, condition)
                if element:
                    match_name = name
                    break

            if element is None:
                true_condition = uia.CreateTrueCondition()
                descendants = root.FindAll(4, true_condition)
                max_items = min(int(getattr(descendants, "Length", 0)), 1200)
                target_tokens = [normalize_text(source.name), normalize_text(source.stem)]
                for index in range(max_items):
                    candidate = descendants.GetElement(index)
                    candidate_name = str(getattr(candidate, "CurrentName", "") or "")
                    normalized_name = normalize_text(candidate_name)
                    if any(token and token in normalized_name for token in target_tokens):
                        element = candidate
                        match_name = candidate_name
                        break
            if element is None:
                return None

            rect = element.CurrentBoundingRectangle
            left = int(getattr(rect, "left", 0))
            top = int(getattr(rect, "top", 0))
            right = int(getattr(rect, "right", 0))
            bottom = int(getattr(rect, "bottom", 0))
            if right <= left or bottom <= top:
                return None
            width = right - left
            height = bottom - top
            point_offset = max(3, min(max(3, width - 3), max(18, int(width * 0.18))))
            point_x = left + point_offset
            point_y = top + int(height * 0.52)
            if not self._point_within_usable_screen((point_x, point_y)):
                return None
            return {
                "point": [point_x, point_y],
                "bounds": [left, top, right, bottom],
                "matches": 1,
                "selected_width": width,
                "selected_height": height,
                "point_strategy": "uia_file_item",
                "window_title": self.automation.get_active_window_title(),
                "uia_match_name": match_name,
            }
        except Exception as exc:
            self._emit(f"UIA no pudo localizar archivo para drag: {exc}", "warning")
            return None

    def _confirm_selected_item_for_drag(self) -> Tuple[Optional[Tuple[int, int]], bool, bool]:
        point = self._find_selected_item_point()
        if not point:
            return None, False, False

        confirmed_point: Optional[Tuple[int, int]] = None
        try:
            self._emit(f"Mouse UI: confirmar seleccion para drag en {point}", "info")
            self.automation.move_mouse(point[0], point[1], duration=0.22)
            self.sleep(0.06)
            self.automation.click(point[0], point[1], duration=0.06)
            self.sleep(0.18)
            confirmed_point = self._find_selected_item_point()
            if confirmed_point:
                point = confirmed_point
            self._record_mouse_step(
                reason="confirmar seleccion para drag",
                status="confirmed" if confirmed_point else "clicked_unconfirmed",
                payload={
                    "point": list(point),
                    "confirmed_point": list(confirmed_point) if confirmed_point else None,
                },
            )
        except Exception as exc:
            self._emit(f"No pude confirmar seleccion con click antes del drag: {exc}", "warning")
            self._record_mouse_step(
                reason="confirmar seleccion para drag",
                status="failed",
                payload={"point": list(point), "error": str(exc)},
            )
        return point, True, confirmed_point is not None

    def _select_file_for_drag(self, source: Path) -> str:
        if not self._uses_default_file_selector:
            self.file_selector(source)
            return "custom_file_selector"

        self._remember_explorer_folder(source.parent)
        direct_method = self._select_file_in_current_folder_with_uia(source)
        if direct_method:
            return direct_method

        if self._is_controlled_practice_source(source):
            self._select_file_direct_for_drag(source)
            return "practice_direct_select_window"

        return self._select_file_by_visible_search_for_drag(
            source,
            method="visible_search_ctrl_f",
        )

    def _select_file_by_visible_search_for_drag(self, source: Path, method: str) -> str:
        if not self._ensure_explorer_context(
            source.parent,
            reason=f"restaurar Explorer antes de buscar {source.name}",
        ):
            raise DesktopDragAttemptError(
                "desktop_selection",
                (
                    "La ventana activa no es Explorer; bloqueo la busqueda con Ctrl+F "
                    f"para evitar contaminar el aprendizaje con otra app: {source.name}."
                ),
            )
        self._emit(f"Buscando archivo visible para drag: {source.name}", "info")
        self._click_explorer_body(f"enfocar lista de {source.parent.name} antes de buscar")
        self.sleep(0.12)
        self.automation.hotkey("ctrl", "f")
        self.sleep(0.18)
        self.automation.hotkey("ctrl", "a")
        self.sleep(0.05)
        self.automation.write_text(source.name, use_clipboard=True)
        self.sleep(0.18)
        self.automation.press_keys(["enter"])
        self.sleep(0.95)
        self._focus_search_results_with_keyboard()
        self._record_mouse_step(
            reason="buscar y seleccionar archivo para drag",
            status="selected",
            payload={"source": str(source), "method": method},
        )
        return method

    def _select_file_in_current_folder_with_uia(self, source: Path) -> Optional[str]:
        detection = self._find_file_item_detection_with_uia(source)
        if not detection:
            return None
        point = detection.get("point") or []
        if not isinstance(point, list) or len(point) != 2:
            return None
        x, y = int(point[0]), int(point[1])
        self._emit(f"Buscando archivo visible con UIA en carpeta actual: {source.name}", "info")
        self.automation.move_mouse(x, y, duration=0.22)
        self.sleep(0.06)
        self.automation.click(x, y, duration=0.06)
        self.sleep(0.18)
        self._last_selected_item_detection = dict(detection)
        self._record_mouse_step(
            reason="seleccionar archivo visible con uia",
            status="selected",
            payload={"source": str(source), "method": "uia_folder_item_click", "detection": detection},
        )
        return "uia_folder_item_click"

    def _is_controlled_practice_source(self, source: Path) -> bool:
        parent_name = str(source.parent.name or "").lower()
        source_name = str(source.name or "").lower()
        if "raphel_practica_" not in source_name:
            return False
        practice_folders = {"seleccion", "deteccion", "flujoentrada"}
        if parent_name in practice_folders or parent_name.startswith("entrada"):
            return True
        return "raphel_practica_drag_" in source_name or "raphel_practica_flujo_" in source_name

    def _windows_workflow_instruction_steps(self, source: Path, destination: Path) -> List[str]:
        return [
            f"Enfocar la ventana de Explorer de origen: {source.parent.name}.",
            f"Seleccionar visualmente el archivo correcto: {source.name}.",
            f"Cambiar el foco a la ventana destino: {destination.parent.name}.",
            f"Mover o pegar {source.name} en la carpeta destino visible.",
            f"Verificar que el archivo ya no exista en origen y si exista en destino.",
        ]

    def _prepare_drag_windows(self, source_folder: Path, destination_folder: Path) -> None:
        if self._reuse_session_explorer_windows:
            self._prepare_drag_windows_with_reuse(source_folder, destination_folder)
            return
        self._open_source_window_for_drag(source_folder)
        self._open_destination_window_for_drag(destination_folder)
        self._focus_folder_window(source_folder, "volver a Entrada para seleccionar archivo")

    def _prepare_drag_windows_with_reuse(self, source_folder: Path, destination_folder: Path) -> None:
        self._ensure_drag_window_for_side(source_folder, side="left")
        self._ensure_drag_window_for_side(destination_folder, side="right")
        self._focus_folder_window(source_folder, "volver a Entrada para seleccionar archivo")

    def _ensure_drag_window_for_side(self, folder: Path, side: str) -> None:
        assigned = self._session_drag_window_assignments.get(side)
        if assigned and assigned == folder and self._focus_assigned_drag_window(side):
            self._move_mouse_inside_explorer(f"enfocar {'origen' if side == 'left' else 'destino'} drag {folder.name}", click=True)
            return

        if assigned and self._focus_assigned_drag_window(side):
            self._navigate_active_explorer_to_folder(folder)
            self._session_drag_window_assignments[side] = folder
            self._move_mouse_inside_explorer(
                f"reusar {'origen' if side == 'left' else 'destino'} drag {folder.name}",
                click=True,
            )
            return

        if side == "left":
            self._open_source_window_for_drag(folder)
        else:
            self._open_destination_window_for_drag(folder)
        self._session_drag_window_assignments[side] = folder

    def _focus_assigned_drag_window(self, side: str) -> bool:
        folder = self._session_drag_window_assignments.get(side)
        if not folder:
            return False
        try:
            self._focus_folder_window(folder, f"reusar ventana {'origen' if side == 'left' else 'destino'}")
            return True
        except Exception:
            return False

    def _navigate_active_explorer_to_folder(self, folder: Path) -> None:
        self._remember_explorer_folder(folder)
        self.automation.hotkey("alt", "d")
        self.sleep(0.12)
        self.automation.write_text(str(folder), use_clipboard=True)
        self.sleep(0.08)
        self.automation.press_keys(["enter"])
        self.sleep(0.35)
        self._explorer_ready = True
        self._record_mouse_step(
            reason="reusar explorer y navegar a carpeta",
            status="navigated",
            payload={"folder": str(folder)},
        )

    def _open_source_window_for_drag(self, folder: Path) -> None:
        if not folder.exists():
            raise FileNotFoundError(f"No existe la carpeta origen para drag: {folder}")
        self._remember_explorer_folder(folder)
        self.automation.open_folder(str(folder))
        self._register_temporary_explorer_window(f"abrir origen drag {folder}")
        self._explorer_ready = True
        self.sleep(0.55)
        self._snap_active_window("left")
        self.sleep(0.35)
        self._move_mouse_inside_explorer(f"enfocar origen drag {folder.name}", click=True)

    def _focus_search_results_with_keyboard(self) -> None:
        self.automation.press_keys(["tab"])
        self.sleep(0.1)
        self.automation.press_keys(["tab"])
        self.sleep(0.1)
        self.automation.hotkey("ctrl", "a")
        self.sleep(0.18)
        self._record_mouse_step(
            reason="enfocar resultados de busqueda con teclado",
            status="selected",
            payload={"keys": ["tab", "tab", "ctrl+a"]},
        )

    def _select_search_result_with_keyboard(self, source: Path) -> None:
        self.automation.press_keys(["tab"])
        self.sleep(0.08)
        self.automation.press_keys(["down"])
        self.sleep(0.08)
        self.automation.press_keys(["space"])
        self.sleep(0.14)
        self._record_mouse_step(
            reason="seleccionar resultado de busqueda con teclado",
            status="selected",
            payload={"source": str(source), "keys": ["tab", "down", "space"]},
        )

    def _select_file_direct_for_drag(self, source: Path) -> None:
        self._remember_explorer_folder(source.parent)
        self._emit(f"Seleccion directa verificable para drag: {source.name}", "info")
        self._open_file_select_window(source)
        self._register_temporary_explorer_window(f"seleccionar archivo directo {source.name}")
        self._explorer_ready = True
        self.sleep(0.75)
        self._record_mouse_step(
            reason="seleccionar archivo directo para drag",
            status="selected",
            payload={"source": str(source), "method": "explorer_select"},
        )

    def _clean_drag_practice_files(self, *folders: Path) -> None:
        removed = 0
        for folder in folders:
            try:
                for path in folder.glob("*.txt"):
                    if path.is_file():
                        path.unlink()
                        removed += 1
            except Exception as exc:
                self._emit(f"No pude limpiar temporales de practica en {folder}: {exc}", "warning")
        if removed:
            self._record_mouse_step(
                reason="limpiar archivos temporales de drag",
                status="cleaned",
                payload={"removed": removed},
            )

    def _create_drag_practice_layout(
        self,
        source_dir: Path,
        session_id: str,
        attempt_number: int,
    ) -> Dict[str, Any]:
        ensure_directory(source_dir)
        settings = self.config.get("desktop_organizer", {})
        distractor_min = max(2, int(settings.get("mouse_practice_distractor_count_min", 6)))
        distractor_max = max(distractor_min, int(settings.get("mouse_practice_distractor_count_max", 12)))
        rng = random.Random(f"{session_id}:{attempt_number}:practice_layout")
        distractor_count = rng.randint(distractor_min, distractor_max)
        total_files = distractor_count + 1
        target_slot = rng.randint(0, total_files - 1)

        distractor_labels = [
            "alpha",
            "beta",
            "gamma",
            "delta",
            "kappa",
            "sigma",
            "omega",
            "nota",
            "borrador",
            "resumen",
            "anexo",
            "control",
            "prueba",
            "visual",
            "mouse",
            "drag",
        ]
        rng.shuffle(distractor_labels)

        created_paths: List[Path] = []
        distractor_paths: List[Path] = []
        base_timestamp = time.time() - float(total_files + 5)

        distractor_index = 0
        for slot in range(total_files):
            if slot == target_slot:
                filename = (
                    f"{slot + 1:02d}_raphel_practica_drag_"
                    f"{session_id}_{attempt_number:02d}.txt"
                )
                path = source_dir / filename
                path.write_text(
                    (
                        "Archivo temporal de practica de Raphel.\n"
                        "Si aparece aqui, no es un archivo del usuario.\n"
                    ),
                    encoding="utf-8",
                )
                target_path = path
            else:
                label = distractor_labels[distractor_index % len(distractor_labels)]
                distractor_index += 1
                filename = f"{slot + 1:02d}_{label}_{session_id}_{attempt_number:02d}.txt"
                path = source_dir / filename
                path.write_text(
                    "Archivo distractor temporal para que Raphel practique busqueda visual.\n",
                    encoding="utf-8",
                )
                distractor_paths.append(path)
            timestamp = base_timestamp + float(slot)
            os.utime(path, (timestamp, timestamp))
            created_paths.append(path)

        layout = {
            "source_dir": str(source_dir),
            "target_path": str(target_path),
            "target_slot": target_slot + 1,
            "total_files": total_files,
            "distractor_count": distractor_count,
            "created_files": [str(path) for path in created_paths],
            "distractors": [str(path) for path in distractor_paths],
        }
        self._record_mouse_step(
            reason="crear layout de practica drag",
            status="created",
            payload=layout,
        )
        return layout

    def _open_folder_visible(self, folder: Path, click_body: bool = False) -> None:
        if not folder.exists():
            raise FileNotFoundError(f"No existe la carpeta visible: {folder}")
        self._remember_explorer_folder(folder)
        active_app = self._active_app_name()

        if not self._explorer_ready or active_app != "explorer":
            self.automation.open_folder(str(folder))
            self._register_temporary_explorer_window(f"abrir carpeta {folder}")
            self._explorer_ready = True
        else:
            try:
                self.automation.hotkey("alt", "d")
                self.automation.write_text(str(folder), use_clipboard=True)
                self.automation.press_keys(["enter"])
            except Exception:
                self.automation.open_folder(str(folder))
                self._register_temporary_explorer_window(f"abrir carpeta {folder}")
                self._explorer_ready = True
        self.sleep(0.35)
        self._move_mouse_inside_explorer(f"enfocar carpeta {folder.name}", click=click_body)
        try:
            active_app = self._active_app_name()
            if active_app and active_app != "explorer":
                self._emit(f"Explorer no es la ventana activa segun vision: {active_app}", "warning")
        except Exception as exc:
            self._emit(f"Vision no confirmo Explorer; continuo con verificacion de archivos: {exc}", "warning")

    def _show_desktop_surface(self) -> None:
        self._emit("Mostrando el escritorio real para arrastre fase 2.", "info")
        self.automation.minimize_all_windows()
        self.sleep(0.35)
        self._record_mouse_step(
            reason="mostrar escritorio real",
            status="visible",
            payload={"phase": 2},
        )

    def _build_selection_footprint(
        self,
        source: Path,
        source_point: Tuple[int, int],
        selection_detection: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "source": str(source),
            "point": list(source_point),
            "bounds": list(selection_detection.get("bounds") or []),
            "window_title": str(selection_detection.get("window_title") or ""),
            "uia_match_name": str(selection_detection.get("uia_match_name") or ""),
            "selected_width": selection_detection.get("selected_width"),
            "selected_height": selection_detection.get("selected_height"),
            "confirmed": True,
        }

    def _bounds_from_payload(self, bounds: Any) -> Optional[Tuple[int, int, int, int]]:
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
            return None
        try:
            left, top, right, bottom = [int(value) for value in bounds]
        except Exception:
            return None
        if right <= left or bottom <= top:
            return None
        return left, top, right, bottom

    def _point_inside_bounds(
        self,
        point: Tuple[int, int],
        bounds: Optional[Tuple[int, int, int, int]],
    ) -> bool:
        if bounds is None:
            return False
        x, y = int(point[0]), int(point[1])
        left, top, right, bottom = bounds
        return left <= x <= right and top <= y <= bottom

    def _bounds_overlap(
        self,
        first: Optional[Tuple[int, int, int, int]],
        second: Optional[Tuple[int, int, int, int]],
    ) -> bool:
        if first is None or second is None:
            return False
        left_a, top_a, right_a, bottom_a = first
        left_b, top_b, right_b, bottom_b = second
        return not (right_a <= left_b or right_b <= left_a or bottom_a <= top_b or bottom_b <= top_a)

    def _window_snapshot(self, window: Any) -> Dict[str, Any]:
        if window is None:
            return {}
        try:
            left = int(getattr(window, "left", 0))
            top = int(getattr(window, "top", 0))
            width = int(getattr(window, "width", 0))
            height = int(getattr(window, "height", 0))
        except Exception:
            return {}
        if width <= 0 or height <= 0:
            return {}
        return {
            "title": str(getattr(window, "title", "") or ""),
            "app_name": str(getattr(window, "app_name", "") or ""),
            "left": left,
            "top": top,
            "right": left + width,
            "bottom": top + height,
            "width": width,
            "height": height,
            "is_active": bool(getattr(window, "is_active", False)),
            "assumed": False,
        }

    def _assumed_snapped_window_snapshot(self, side: str) -> Dict[str, Any]:
        bounds = self._screen_bounds_for_safety()
        if not bounds:
            return {}
        left, top, width, height = bounds
        half_width = max(1, width // 2)
        snap_left = left if side == "left" else left + half_width
        snap_width = half_width if side == "left" else max(1, width - half_width)
        return {
            "title": "",
            "app_name": "explorer",
            "left": snap_left,
            "top": top,
            "right": snap_left + snap_width,
            "bottom": top + height,
            "width": snap_width,
            "height": height,
            "is_active": True,
            "assumed": True,
            "snap_side": side,
        }

    def _body_point_from_window_snapshot(
        self,
        window_snapshot: Dict[str, Any],
        horizontal: float,
        vertical: float,
    ) -> Optional[Tuple[int, int]]:
        try:
            left = int(window_snapshot.get("left", 0))
            top = int(window_snapshot.get("top", 0))
            width = int(window_snapshot.get("width", 0))
            height = int(window_snapshot.get("height", 0))
        except Exception:
            return None
        if width <= 0 or height <= 0:
            return None
        x = int(left + max(120, width * horizontal))
        y = int(top + max(160, height * vertical))
        point = (x, y)
        if not self._point_within_usable_screen(point):
            return None
        return point

    def _preferred_destination_snap_side(
        self,
        source_point: Tuple[int, int],
        selection_detection: Dict[str, Any],
    ) -> str:
        right_window = self._assumed_snapped_window_snapshot("right")
        right_bounds = self._bounds_from_payload(right_window.get("bounds")) if right_window else None
        if right_bounds is None and right_window:
            right_bounds = self._bounds_from_payload(
                [
                    right_window.get("left"),
                    right_window.get("top"),
                    right_window.get("right"),
                    right_window.get("bottom"),
                ]
            )
        source_bounds = self._bounds_from_payload(selection_detection.get("bounds"))
        if self._point_inside_bounds(source_point, right_bounds) or self._bounds_overlap(source_bounds, right_bounds):
            return "left"
        return "right"

    def _revalidate_explorer_drag_continuity(
        self,
        source: Path,
        source_point: Tuple[int, int],
        selection_detection: Dict[str, Any],
        source_window: Any,
        destination_window: Any,
        destination: Path,
    ) -> Dict[str, Any]:
        source_snapshot = self._window_snapshot(source_window)
        destination_snapshot = self._window_snapshot(destination_window)
        source_bounds = self._bounds_from_payload(selection_detection.get("bounds"))
        if source_bounds is None and source_snapshot:
            source_bounds = self._bounds_from_payload(
                [
                    source_snapshot.get("left"),
                    source_snapshot.get("top"),
                    source_snapshot.get("right"),
                    source_snapshot.get("bottom"),
                ]
            )
        destination_bounds = None
        if destination_snapshot:
            destination_bounds = self._bounds_from_payload(
                [
                    destination_snapshot.get("left"),
                    destination_snapshot.get("top"),
                    destination_snapshot.get("right"),
                    destination_snapshot.get("bottom"),
                ]
            )

        expected_source_title = normalize_text(source.parent.name)
        expected_destination_title = normalize_text(destination.parent.name)
        detection_title = normalize_text(str(selection_detection.get("window_title") or ""))
        source_title = normalize_text(str(source_snapshot.get("title") or ""))
        destination_title = normalize_text(str(destination_snapshot.get("title") or ""))

        source_title_coherent = (
            not source_title
            or not expected_source_title
            or expected_source_title in source_title
            or source_title in expected_source_title
        )
        detection_title_coherent = (
            not detection_title
            or not expected_source_title
            or expected_source_title in detection_title
            or detection_title in expected_source_title
        )
        destination_title_coherent = (
            not destination_title
            or not expected_destination_title
            or expected_destination_title in destination_title
            or destination_title in expected_destination_title
        )
        point_visible = self._point_within_usable_screen(source_point)
        source_occluded = bool(destination_bounds) and (
            self._point_inside_bounds(source_point, destination_bounds)
            or self._bounds_overlap(source_bounds, destination_bounds)
        )
        coherent = (
            point_visible
            and source_title_coherent
            and detection_title_coherent
            and destination_title_coherent
            and not source_occluded
        )
        reason = ""
        if not point_visible:
            reason = "El punto seleccionado para el drag quedo fuera de pantalla."
        elif not source_title_coherent or not detection_title_coherent:
            reason = "La seleccion confirmada ya no coincide con la ventana origen esperada."
        elif not destination_title_coherent:
            reason = "La ventana activa no coincide de forma coherente con la carpeta destino."
        elif source_occluded:
            reason = "La ventana destino tapo la fila seleccionada en Explorer antes del drag."

        return {
            "coherent": coherent,
            "reason": reason,
            "point_visible": point_visible,
            "source_title_coherent": source_title_coherent,
            "detection_title_coherent": detection_title_coherent,
            "destination_title_coherent": destination_title_coherent,
            "source_occluded": source_occluded,
            "source_point": list(source_point),
            "source_bounds": list(source_bounds) if source_bounds else [],
            "source_window": source_snapshot,
            "destination_window": destination_snapshot,
        }

    def _stabilize_explorer_drag_layout(
        self,
        source_folder: Path,
        destination_folder: Path,
        reason: str,
    ) -> None:
        self._emit(f"Mouse UI: reacomodar ventanas Explorer ({reason})", "info")
        if self._reuse_session_explorer_windows:
            self._ensure_drag_window_for_side(source_folder, side="left")
            self._focus_folder_window(source_folder, f"{reason}: origen")
            self._snap_active_window("left")
            self.sleep(0.18)
            self._move_mouse_inside_explorer(f"{reason}: origen", click=True)
            self._ensure_drag_window_for_side(destination_folder, side="right")
            self._focus_folder_window(destination_folder, f"{reason}: destino")
            self._snap_active_window("right")
            self.sleep(0.18)
            self._move_mouse_inside_explorer(f"{reason}: destino", click=True)
            self._focus_folder_window(source_folder, "volver a origen tras reacomodar ventanas")
            return

        self._focus_folder_window(source_folder, f"{reason}: origen")
        self._snap_active_window("left")
        self.sleep(0.18)
        self._move_mouse_inside_explorer(f"{reason}: origen", click=True)
        self._focus_folder_window(destination_folder, f"{reason}: destino")
        self._snap_active_window("right")
        self.sleep(0.18)
        self._move_mouse_inside_explorer(f"{reason}: destino", click=True)
        self._focus_folder_window(source_folder, "volver a origen tras reacomodar ventanas")

    def _repair_explorer_drag_layout(
        self,
        source: Path,
        destination: Path,
        category: str,
        selection_method: str,
        source_point: Tuple[int, int],
        selection_detection: Dict[str, Any],
    ) -> Dict[str, Any]:
        repair = {
            "attempted": True,
            "recovered": False,
            "layout_mode": "strict_split_explorer_halves",
            "selection_method_before": selection_method,
            "source_point": list(source_point),
            "selection_detection": dict(selection_detection),
            "verification": {},
            "source_window": {},
            "destination_window": {},
        }
        try:
            self._emit(
                (
                    f"Reacomodando ventanas para {source.name}: "
                    "origen a la izquierda y destino a la derecha."
                ),
                "warning",
            )
            self._stabilize_explorer_drag_layout(
                source.parent,
                destination.parent,
                reason=f"reparar layout de ventanas para {category}",
            )
            self.sleep(0.18)
            self._focus_folder_window(source.parent, "reconfirmar origen tras reparar layout")
            self._select_file_for_drag(source)
            self.sleep(0.2)
            repaired_point, _repaired_visual, repaired_confirmed = self._confirm_file_item_for_drag(source)
            repaired_detection = dict(self._last_selected_item_detection) or dict(selection_detection)
            source_window = self._active_or_first_explorer_window()
            self._focus_folder_window(destination.parent, "validar destino tras reparar layout")
            destination_window = self._active_or_first_explorer_window()
            verification = self._revalidate_explorer_drag_continuity(
                source=source,
                source_point=repaired_point or source_point,
                selection_detection=repaired_detection,
                source_window=source_window,
                destination_window=destination_window,
                destination=destination,
            )
            repair["source_window"] = self._window_snapshot(source_window)
            repair["destination_window"] = self._window_snapshot(destination_window)
            repair["verification"] = verification
            repair["selection_detection"] = repaired_detection
            repair["selection_confirmed"] = bool(repaired_confirmed)
            if repaired_point:
                repair["source_point"] = [int(repaired_point[0]), int(repaired_point[1])]
            if repaired_confirmed and verification.get("coherent", False):
                repair["recovered"] = True
                return repair
            repair["reason"] = (
                "No pude reconfirmar la seleccion tras reacomodar ventanas."
                if not repaired_confirmed
                else str(
                    verification.get("reason") or "La disposicion reparada sigue sin permitir un drag fiable."
                )
            )
            return repair
        except Exception as exc:
            repair["reason"] = str(exc)
            return repair

    def _revalidate_desktop_drag_continuity(
        self,
        source: Path,
        source_point: Tuple[int, int],
        selection_detection: Dict[str, Any],
        destination_window: Dict[str, Any],
        snap_side: str,
    ) -> Dict[str, Any]:
        destination_snapshot = dict(destination_window.get("window") or {})
        if not destination_snapshot:
            destination_snapshot = self._assumed_snapped_window_snapshot(snap_side)
        destination_bounds = self._bounds_from_payload(
            [
                destination_snapshot.get("left"),
                destination_snapshot.get("top"),
                destination_snapshot.get("right"),
                destination_snapshot.get("bottom"),
            ]
        )
        source_bounds = self._bounds_from_payload(selection_detection.get("bounds"))
        normalized_source = normalize_text(source.name)
        normalized_match = normalize_text(
            str(selection_detection.get("uia_match_name") or selection_detection.get("window_title") or "")
        )
        name_coherent = (
            not normalized_match
            or (
                bool(normalized_source)
                and (normalized_source in normalized_match or normalized_match in normalized_source)
            )
        )
        point_visible = self._point_within_usable_screen(source_point)
        source_occluded = self._point_inside_bounds(source_point, destination_bounds) or self._bounds_overlap(
            source_bounds,
            destination_bounds,
        )
        coherent = bool(selection_detection) and point_visible and name_coherent and not source_occluded
        reason = ""
        if not point_visible:
            reason = "El punto fuente del escritorio quedo fuera de pantalla antes del drag."
        elif not name_coherent:
            reason = "La huella de seleccion no coincide de forma coherente con el archivo esperado."
        elif source_occluded:
            reason = "La ventana destino tapo el icono seleccionado del escritorio."
        return {
            "coherent": coherent,
            "reason": reason,
            "point_visible": point_visible,
            "name_coherent": name_coherent,
            "source_occluded": source_occluded,
            "snap_side": snap_side,
            "source_point": list(source_point),
            "source_bounds": list(source_bounds) if source_bounds else [],
            "destination_window": destination_snapshot,
        }

    def _select_desktop_item_for_drag(
        self,
        source: Path,
    ) -> Tuple[Optional[Tuple[int, int]], Dict[str, Any]]:
        try:
            self._show_desktop_surface()
        except Exception as exc:
            raise DesktopDragAttemptError(
                "desktop_focus",
                f"No pude mostrar el escritorio real para {source.name}: {exc}",
            ) from exc
        self.sleep(0.15)
        detection = self._find_file_item_detection_with_uia(source) or {}
        point_raw = detection.get("point") if isinstance(detection, dict) else None
        if not isinstance(point_raw, list) or len(point_raw) != 2:
            raise DesktopDragAttemptError(
                "desktop_detection",
                f"UIA no detecto {source.name} directamente en el escritorio.",
            )
        point = (int(point_raw[0]), int(point_raw[1]))
        if not self._point_within_usable_screen(point):
            raise DesktopDragAttemptError(
                "desktop_detection",
                f"El punto detectado para {source.name} quedo fuera de pantalla.",
            )
        self._last_selected_item_detection = dict(detection)
        try:
            self.automation.move_mouse(point[0], point[1], duration=0.22)
            self.sleep(0.06)
            self.automation.click(point[0], point[1], duration=0.06)
        except Exception as exc:
            raise DesktopDragAttemptError(
                "desktop_selection",
                f"No pude seleccionar {source.name} en el escritorio: {exc}",
            ) from exc
        self.sleep(0.12)
        self._record_mouse_step(
            reason="seleccionar archivo en escritorio real",
            status="selected",
            payload={"source": str(source), "point": list(point), "detection": detection},
        )
        return point, dict(detection)

    def _select_file_with_explorer(self, source: Path) -> None:
        try:
            self._remember_explorer_folder(source.parent)
            self._open_folder_visible(source.parent, click_body=True)
            self.sleep(0.25)
            direct_method = self._select_file_in_current_folder_with_uia(source)
            if direct_method:
                self._record_mouse_step(
                    reason="seleccionar archivo con explorer",
                    status="selected",
                    payload={"source": str(source), "method": direct_method},
                )
                return
            if self._is_controlled_practice_source(source):
                self._select_file_direct_for_drag(source)
                self._record_mouse_step(
                    reason="seleccionar archivo con explorer",
                    status="selected",
                    payload={"source": str(source), "method": "practice_direct_select_window"},
                )
                return
            if not self._ensure_explorer_context(
                source.parent,
                reason=f"restaurar Explorer antes de buscar {source.name}",
            ):
                raise DesktopDragAttemptError(
                    "desktop_selection",
                    (
                        "La ventana activa no es Explorer; bloqueo la busqueda con Ctrl+F "
                        f"para evitar ejecutar atajos en otra app: {source.name}."
                    ),
                )
            self.automation.hotkey("ctrl", "f")
            self.sleep(0.15)
            self.automation.hotkey("ctrl", "a")
            self.sleep(0.05)
            self.automation.write_text(source.name, use_clipboard=True)
            self.sleep(0.15)
            self.automation.press_keys(["enter"])
            self.sleep(0.12)
            self._record_mouse_step(
                reason="seleccionar archivo con explorer",
                status="selected",
                payload={"source": str(source)},
            )
        except Exception:
            self._open_file_select_window(source)
            self._register_temporary_explorer_window(f"seleccionar archivo {source.name}")
            self._explorer_ready = True

    def _select_file_for_selection_practice(self, source: Path) -> None:
        self._remember_explorer_folder(source.parent)
        self._open_file_select_window(source)
        self._register_temporary_explorer_window(f"seleccionar visualmente {source.name}")
        self._explorer_ready = True
        self.sleep(0.65)
        try:
            self._move_mouse_inside_explorer(f"enfocar seleccion {source.parent.name}", click=False)
        except Exception as exc:
            self._emit(f"No pude enfocar Explorer tras /select: {exc}", "warning")

    def _open_file_select_window(self, source: Path) -> None:
        if hasattr(self.automation, "open_file_select"):
            self.automation.open_file_select(str(source))
        else:
            subprocess.Popen(["explorer.exe", f"/select,{source}"])

    def _open_destination_window_for_drag(
        self,
        folder: Path,
        preferred_side: str = "right",
    ) -> Dict[str, Any]:
        if not folder.exists():
            raise FileNotFoundError(f"No existe la carpeta destino para drag: {folder}")
        self._remember_explorer_folder(folder)
        self.automation.open_folder(str(folder))
        self._register_temporary_explorer_window(f"abrir destino drag {folder}")
        self._explorer_ready = True
        self.sleep(0.55)
        snap_side = "left" if preferred_side == "left" else "right"
        self._snap_active_window(snap_side)
        self.sleep(0.35)
        self._move_mouse_inside_explorer(f"enfocar destino drag {folder.name}", click=True)
        window_snapshot = self._window_snapshot(self._active_or_first_explorer_window())
        if not window_snapshot:
            window_snapshot = self._assumed_snapped_window_snapshot(snap_side)
        info = {
            "folder": str(folder),
            "snap_side": snap_side,
            "window": window_snapshot,
            "body_point": list(
                self._body_point_from_window_snapshot(window_snapshot, horizontal=0.54, vertical=0.45) or ()
            ),
        }
        self._record_mouse_step(
            reason="abrir destino drag desde escritorio",
            status="ready",
            payload=info,
        )
        return info

    def _finish_move_record(
        self,
        record: DesktopLearningMoveRecord,
        source: Path,
    ) -> DesktopLearningMoveRecord:
        if self._reuse_session_explorer_windows:
            return record
        self._tidy_temporary_explorer_windows(f"terminar movimiento {source.name}")
        return record

    def _begin_explorer_reuse_session(self, enabled: bool) -> None:
        self._reuse_session_explorer_windows = enabled
        self._session_drag_window_assignments = {}
        self._session_previous_active_window_title = self._active_window_title() if enabled else ""

    def _end_explorer_reuse_session(self, reason: str) -> None:
        try:
            self._tidy_temporary_explorer_windows(reason)
            if self.restore_previous_window_after_session and self._session_previous_active_window_title:
                self._restore_previous_window_focus()
        finally:
            self._reuse_session_explorer_windows = False
            self._session_drag_window_assignments = {}
            self._session_previous_active_window_title = ""

    def _active_window_title(self) -> str:
        try:
            snapshot = self.vision.get_latest_snapshot(refresh=True)
            windows = getattr(snapshot, "windows", []) or []
            active = next((item for item in windows if getattr(item, "is_active", False)), None)
            return str(getattr(active, "title", "") or "").strip()
        except Exception:
            return ""

    def _restore_previous_window_focus(self) -> None:
        title = self._session_previous_active_window_title.strip()
        if not title:
            return
        try:
            self._emit(f"Restaurando ventana previa: {title}", "info")
            if hasattr(self.automation, "focus_window"):
                self.automation.focus_window(title)
                self.sleep(0.2)
        except Exception as exc:
            self._emit(f"No pude restaurar la ventana previa: {exc}", "warning")

    def _register_temporary_explorer_window(self, reason: str) -> None:
        self._temporary_explorer_windows += 1
        self._record_mouse_step(
            reason="registrar explorer temporal",
            status="opened",
            payload={
                "reason": reason,
                "open_count": self._temporary_explorer_windows,
            },
        )

    def _remember_explorer_folder(self, folder: Path) -> None:
        values = {folder.name, str(folder)}
        try:
            desktop = self._desktop_path()
            if folder == desktop:
                values.update({"Desktop", "Escritorio"})
        except Exception:
            pass
        for value in values:
            cleaned = normalize_text(str(value))
            if cleaned:
                self._known_explorer_titles.add(cleaned)

    def _folder_focus_titles(self, folder: Path) -> List[str]:
        titles: List[str] = []
        desktop_aliases: List[str] = []
        path_title = str(folder)

        def add(value: Any) -> None:
            text = str(value or "").strip()
            if text and text not in titles:
                titles.append(text)

        add(folder.name)
        try:
            desktop = self._desktop_path()
            if folder == desktop:
                desktop_aliases.extend(["Desktop", "Escritorio"])
        except Exception:
            pass
        for alias in desktop_aliases:
            add(alias)
        add(path_title)
        return titles

    def _is_known_explorer_window(self, window: Any) -> bool:
        if getattr(window, "app_name", None) == "explorer":
            return True
        title = normalize_text(str(getattr(window, "title", "") or ""))
        if not title:
            return False
        if title in self._known_explorer_titles:
            return True
        return any(known and known in title for known in self._known_explorer_titles)

    def _is_usable_window_geometry(self, window: Any) -> bool:
        try:
            left = int(getattr(window, "left", 0))
            top = int(getattr(window, "top", 0))
            width = int(getattr(window, "width", 0))
            height = int(getattr(window, "height", 0))
        except Exception:
            return False
        if width <= 80 or height <= 80:
            return False
        if left <= -30000 or top <= -30000:
            return False
        try:
            if bool(getattr(window, "isMinimized", False)):
                return False
        except Exception:
            pass
        bounds = self._screen_bounds_for_safety()
        if bounds:
            screen_left, screen_top, screen_width, screen_height = bounds
            screen_right = screen_left + screen_width
            screen_bottom = screen_top + screen_height
            right = left + width
            bottom = top + height
            if right <= screen_left or left >= screen_right:
                return False
            if bottom <= screen_top or top >= screen_bottom:
                return False
        return True

    def _point_within_usable_screen(self, point: Tuple[int, int]) -> bool:
        x, y = int(point[0]), int(point[1])
        if x <= -30000 or y <= -30000:
            return False
        bounds = self._screen_bounds_for_safety()
        if not bounds:
            return x >= -5000 and y >= -5000
        left, top, width, height = bounds
        return left <= x < left + width and top <= y < top + height

    def _desktop_point_safe_for_drag(self, point: Tuple[int, int]) -> bool:
        bounds = self._screen_bounds_for_safety()
        if not bounds:
            return True
        left, _top, width, _height = bounds
        desktop_drag_safe_right_edge = left + int(width * 0.58)
        return int(point[0]) <= desktop_drag_safe_right_edge

    def _screen_bounds_for_safety(self) -> Optional[Tuple[int, int, int, int]]:
        try:
            bounds = self.vision._screen_bounds()
            if bounds and len(bounds) == 4:
                left, top, width, height = [int(value) for value in bounds]
                if width > 0 and height > 0:
                    return left, top, width, height
        except Exception:
            pass
        return None

    def _tidy_temporary_explorer_windows(self, reason: str) -> None:
        if not self.close_temporary_explorer_windows:
            return
        if self._temporary_explorer_windows <= 0:
            return

        closed = 0
        attempts = min(
            self._temporary_explorer_windows,
            max(self.max_temporary_explorer_windows, 3),
        )
        for attempt in range(attempts):
            if self._close_active_temporary_explorer_window(reason):
                closed += 1
                continue
            if attempt == attempts - 1:
                break
            self._focus_next_window_for_cleanup()
            if self._close_active_temporary_explorer_window(reason):
                closed += 1
            else:
                break

        if closed:
            self._record_mouse_step(
                reason="limpiar explorers temporales",
                status="closed",
                payload={
                    "reason": reason,
                    "closed": closed,
                    "remaining_count": self._temporary_explorer_windows,
                },
            )

    def _close_active_temporary_explorer_window(self, reason: str) -> bool:
        if self._temporary_explorer_windows <= 0:
            return False
        active_app = self._active_app_name()
        if active_app and active_app != "explorer":
            return False
        if not active_app:
            return False
        try:
            self._emit(f"Cerrando Explorer temporal de aprendizaje: {reason}", "info")
            self.automation.hotkey("alt", "f4")
            self.sleep(0.25)
            self._temporary_explorer_windows = max(0, self._temporary_explorer_windows - 1)
            self._explorer_ready = self._temporary_explorer_windows > 0
            return True
        except Exception as exc:
            self._emit(f"No pude cerrar Explorer temporal: {exc}", "warning")
            return False

    def _attempt_drag_move_with_profile_sequence(
        self,
        source: Path,
        destination: Path,
        category: str,
        session: DesktopLearningSession,
        gesture: str,
        started: float,
        profiles: List[Dict[str, Any]],
    ) -> DesktopLearningMoveRecord:
        profile = profiles[0] if profiles else {}
        return self._attempt_drag_move(
            source=source,
            destination=destination,
            category=category,
            session=session,
            gesture=gesture,
            started=started,
            profile_override=profile,
        )
        last_record: Optional[DesktopLearningMoveRecord] = None
        for profile in profiles:
            record = self._attempt_drag_move(
                source=source,
                destination=destination,
                category=category,
                session=session,
                gesture=gesture,
                started=started,
                profile_override=profile,
            )
            if record.verified:
                return record
            last_record = record
            failed_profile = str(record.details.get("profile") or profile.get("name") or "unknown")
            self._emit(
                (
                    f"Perfil drag fallo ({failed_profile}) para {source.name}; "
                    "probando siguiente perfil si queda alguno."
                ),
                "warning",
            )
            self._finish_move_record(record, source)
        
        self._emit(
            f"Todos los perfiles de drag fallaron para {source.name}; intentando fallback a cut/paste...",
            "warning",
        )
        try:
            # Seleccionar archivo en Explorer (abre carpeta padre y busca)
            self.file_selector(source)
            self.sleep(0.8)
            # Cerrar diálogo de búsqueda (Escape) si está abierto
            self.automation.press_keys(["escape"])
            self.sleep(0.15)
            # No cliqueamos el body antes de cortar, porque eso puede deseleccionar el archivo.
            # Simplemente asumimos que el archivo sigue seleccionado tras la búsqueda.
            self.automation.hotkey("ctrl", "x")
            self.sleep(0.35)
            # Abrir carpeta destino
            self._open_folder_visible(destination.parent, click_body=True)
            self.sleep(0.35)
            # Click en el body del explorer para el foco antes de pegar
            self._click_explorer_body("preparar destino para paste")
            self.sleep(0.15)
            # Pegar archivo
            self.automation.hotkey("ctrl", "v")
            self.sleep(0.8)
            # Verificar que se completó
            self._wait_for_path(destination, timeout=3.0)
            verified = (not source.exists()) and destination.exists()
            if verified:
                self._emit(f"Fallback exitoso para {source.name} usando cut/paste", "info")
                return DesktopLearningMoveRecord(
                    source=str(source),
                    destination=str(destination),
                    category=category,
                    gesture=gesture,
                    status="completed",
                    duration_seconds=round(time.perf_counter() - started, 3),
                    verified=True,
                    error="",
                    details={
                        "attempted_drag": False,
                        "drag_failed_all_profiles": True,
                        "fallback_cut_paste": True,
                    },
                )
        except Exception as exc:
            self._emit(f"Fallback cut/paste tambien fallo: {exc}", "warning")
            self._cancel_possible_dialog()
        
        return last_record or DesktopLearningMoveRecord(
            source=str(source),
            destination=str(destination),
            category=category,
            gesture=gesture,
            status="failed",
            duration_seconds=round(time.perf_counter() - started, 3),
            verified=False,
            error="No se pudo completar el arrastre con ningun perfil de practica.",
        )

    def _focus_next_window_for_cleanup(self) -> None:
        try:
            if hasattr(self.automation, "alt_tab"):
                self.automation.alt_tab()
            else:
                self.automation.hotkey("alt", "tab")
            self.sleep(0.2)
        except Exception as exc:
            self._emit(f"No pude cambiar de ventana para limpiar Explorer: {exc}", "warning")

    def _focus_folder_window(self, folder: Path, reason: str) -> None:
        self._remember_explorer_folder(folder)
        titles = self._folder_focus_titles(folder)
        display_title = folder.name
        self._emit(f"Mouse UI: {reason}: {display_title}", "info")

        if not hasattr(self.automation, "focus_window"):
            self._focus_other_drag_window(reason)
            return

        last_error: Optional[Exception] = None
        for title in titles:
            try:
                self.automation.focus_window(title)
                self.sleep(0.35)
                self._explorer_ready = True
                self._move_mouse_inside_explorer(f"enfocar ventana {display_title}", click=False)
                self._record_mouse_step(
                    reason=reason,
                    status="focused",
                    payload={
                        "method": "focus_window",
                        "folder": str(folder),
                        "title": title,
                        "attempted_titles": titles,
                    },
                )
                return
            except Exception as exc:
                last_error = exc

        self._emit(
            (
                f"No pude enfocar {display_title} por titulo ({last_error}); "
                "uso cambio de ventana como respaldo."
            ),
            "warning",
        )
        self._focus_other_drag_window(reason)

    def _focus_other_drag_window(self, reason: str) -> None:
        try:
            self._emit(f"Mouse UI: {reason}", "info")
            if hasattr(self.automation, "alt_tab"):
                self.automation.alt_tab()
            else:
                self.automation.hotkey("alt", "tab")
            self.sleep(0.35)
            self._record_mouse_step(
                reason=reason,
                status="focused",
                payload={"method": "alt_tab"},
            )
        except Exception as exc:
            self._emit(f"No pude cambiar de ventana durante drag: {exc}", "warning")

    def _active_app_name(self) -> str:
        try:
            snapshot = self.vision.get_latest_snapshot(refresh=True)
            windows = getattr(snapshot, "windows", []) or []
            active = next((item for item in windows if getattr(item, "is_active", False)), None)
            if active and self._is_known_explorer_window(active):
                return "explorer"
            return str(getattr(snapshot, "active_app", "") or "")
        except Exception:
            return ""

    def _ensure_explorer_context(self, folder: Path, reason: str) -> bool:
        active_app = normalize_text(self._active_app_name())
        if active_app == "explorer":
            return True
        self._focus_folder_window(folder, reason)
        self.sleep(0.2)
        active_app = normalize_text(self._active_app_name())
        if active_app == "explorer":
            return True
        self._open_folder_visible(folder, click_body=True)
        self.sleep(0.25)
        active_app = normalize_text(self._active_app_name())
        return active_app == "explorer"

    def _snap_active_window(self, side: str) -> None:
        keys = ("winleft", "left") if side == "left" else ("winleft", "right")
        try:
            self.automation.hotkey(*keys)
            self._record_mouse_step(
                reason=f"acomodar ventana {side} para drag",
                status="hotkey",
                payload={"keys": list(keys)},
            )
        except Exception as exc:
            self._emit(f"No pude acomodar ventana para drag: {exc}", "warning")

    def _move_mouse_inside_explorer(self, reason: str, click: bool = False) -> None:
        point = self._explorer_body_point()
        if not point:
            self._record_mouse_step(
                reason=reason,
                status="skipped",
                payload={"reason": "No hay ventana Explorer visible y usable."},
            )
            return
        x, y = point
        if not self._point_within_usable_screen((x, y)):
            self._emit(f"Ignoro punto Explorer fuera de pantalla para {reason}: ({x}, {y})", "warning")
            self._record_mouse_step(
                reason=reason,
                status="skipped",
                payload={"x": x, "y": y, "reason": "offscreen_point"},
            )
            return
        self._emit(f"Mouse UI: {reason} en ({x}, {y})", "info")
        self.automation.move_mouse(x, y, duration=0.28)
        self.sleep(0.08)
        if click:
            self.automation.click(x, y, duration=0.06)
            self.sleep(0.12)
        self._record_mouse_step(
            reason=reason,
            status="clicked" if click else "moved",
            payload={"x": x, "y": y, "click": click},
        )

    def _click_explorer_body(self, reason: str) -> None:
        self._move_mouse_inside_explorer(reason, click=True)

    def _explorer_body_point(
        self,
        horizontal: float = 0.5,
        vertical: float = 0.45,
    ) -> Optional[tuple[int, int]]:
        try:
            snapshot = self.vision.get_latest_snapshot(refresh=True)
            windows = getattr(snapshot, "windows", []) or []
            active = next((item for item in windows if getattr(item, "is_active", False)), None)
            known_explorers = [item for item in windows if self._is_known_explorer_window(item)]
            explorer = (
                active
                if active
                and self._is_known_explorer_window(active)
                and self._is_usable_window_geometry(active)
                else None
            )
            if not explorer:
                explorer = next(
                    (item for item in known_explorers if self._is_usable_window_geometry(item)),
                    None,
                )
            if explorer and getattr(explorer, "width", 0) > 0 and getattr(explorer, "height", 0) > 0:
                x = int(explorer.left + max(120, explorer.width * horizontal))
                y = int(explorer.top + max(160, explorer.height * vertical))
                return x, y
            if known_explorers:
                self._emit(
                    "Explorer detectado solo en geometria no usable; usare fallback de pantalla.",
                    "warning",
                )
        except Exception as exc:
            self._emit(f"No pude calcular punto de Explorer desde vision: {exc}", "warning")

        try:
            bounds = self.vision._screen_bounds()
            if bounds:
                left, top, width, height = bounds
                return int(left + width * horizontal), int(top + height * vertical)
        except Exception:
            return None
        return None

    def _find_selected_item_point(self) -> Optional[Tuple[int, int]]:
        self._last_selected_item_detection = {}
        explorer = self._active_or_first_explorer_window()
        if not explorer:
            return None
        try:
            left = int(getattr(explorer, "left", 0))
            top = int(getattr(explorer, "top", 0))
            width = int(getattr(explorer, "width", 0))
            height = int(getattr(explorer, "height", 0))
            if width <= 0 or height <= 0 or not self._is_usable_window_geometry(explorer):
                return None
            region = (
                left + int(width * 0.14),
                top + int(height * 0.16),
                max(160, int(width * 0.78)),
                max(120, int(height * 0.72)),
            )
            image = self.vision.capture_screen(region=region)
        except Exception as exc:
            self._emit(f"No pude capturar seleccion visual de Explorer: {exc}", "warning")
            return None

        pixels = image.load()
        min_x = min_y = 10**9
        max_x = max_y = -1
        matches = 0
        width, height = image.size
        for y in range(0, height, 3):
            for x in range(0, width, 3):
                r, g, b = pixels[x, y][:3]
                blue_selection = b >= 145 and g >= 70 and r <= 135 and (b - r) >= 55
                accent_selection = b >= 120 and g >= 95 and r <= 170 and abs(b - g) >= 15
                if blue_selection or accent_selection:
                    matches += 1
                    min_x = min(min_x, x)
                    min_y = min(min_y, y)
                    max_x = max(max_x, x)
                    max_y = max(max_y, y)

        if matches < 18 or max_x <= min_x or max_y <= min_y:
            return None
        selected_width = max_x - min_x
        selected_height = max_y - min_y
        if selected_width > 90:
            anchor_offset = min(72, max(28, int(selected_width * 0.08)))
            local_x = min(max_x - 8, min_x + anchor_offset)
            point_strategy = "left_anchor_near_icon"
        else:
            local_x = int((min_x + max_x) / 2)
            point_strategy = "selection_center"
        center_x = region[0] + local_x
        center_y = region[1] + int((min_y + max_y) / 2)
        if not self._point_within_usable_screen((center_x, center_y)):
            return None
        bounds = [
            region[0] + min_x,
            region[1] + min_y,
            region[0] + max_x,
            region[1] + max_y,
        ]
        self._last_selected_item_detection = {
            "point": [center_x, center_y],
            "bounds": bounds,
            "matches": matches,
            "selected_width": selected_width,
            "selected_height": selected_height,
            "point_strategy": point_strategy,
            "window_title": str(getattr(explorer, "title", "") or ""),
        }
        self._record_mouse_step(
            reason="detectar seleccion visual",
            status="detected",
            payload={
                "x": center_x,
                "y": center_y,
                "matches": matches,
                "bounds": bounds,
                "selected_width": selected_width,
                "selected_height": selected_height,
                "point_strategy": point_strategy,
                "window_title": str(getattr(explorer, "title", "") or ""),
            },
        )
        return center_x, center_y

    def _active_or_first_explorer_window(self) -> Optional[Any]:
        try:
            snapshot = self.vision.get_latest_snapshot(refresh=True)
            windows = getattr(snapshot, "windows", []) or []
            active = next((item for item in windows if getattr(item, "is_active", False)), None)
            if active and self._is_known_explorer_window(active) and self._is_usable_window_geometry(active):
                return active
            return next(
                (
                    item
                    for item in windows
                    if self._is_known_explorer_window(item) and self._is_usable_window_geometry(item)
                ),
                None,
            )
        except Exception:
            return None

    def _load_drag_strategy(self) -> Dict[str, Any]:
        return self.store.load_drag_strategy(self._merge_default_drag_profiles)

    def _merge_default_drag_profiles(self, loaded: Dict[str, Any]) -> Dict[str, Any]:
        strategy = {
            "version": 1,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "profiles": {},
            "categories": {},
            "practice": {},
            "attempts": [],
            "window_management": {},
        }
        strategy.update({key: value for key, value in loaded.items() if key in strategy})
        profiles = strategy.setdefault("profiles", {})
        window_management = strategy.setdefault("window_management", {})
        window_management.setdefault("strict_split_enabled", False)
        window_management.setdefault("repair_attempts", 0)
        window_management.setdefault("repair_successes", 0)
        window_management.setdefault("repair_failures", 0)
        window_management.setdefault("source_occlusion_failures", 0)
        window_management.setdefault("successful_split_layouts", 0)
        window_management.setdefault("last_result", "new")
        for profile in self.DEFAULT_DRAG_PROFILES:
            current = profiles.setdefault(profile["name"], {})
            current.update({key: value for key, value in profile.items() if key not in current})
            current.setdefault("successes", 0)
            current.setdefault("failures", 0)
            current.setdefault("last_result", "new")
        profiles.setdefault(
            "vision_selected_item",
            {
                "name": "vision_selected_item",
                "successes": 0,
                "failures": 0,
                "last_result": "new",
            },
        )
        profiles.setdefault(
            "source_visual_selection",
            {
                "name": "source_visual_selection",
                "successes": 0,
                "failures": 0,
                "last_result": "new",
            },
        )
        return strategy

    def _choose_drag_profile(self, category: str) -> Dict[str, Any]:
        categories = self.drag_strategy.setdefault("categories", {})
        preferred_name = categories.get(category, {}).get("preferred_profile")
        profiles = self.drag_strategy.setdefault("profiles", {})
        if preferred_name and preferred_name in profiles:
            return dict(profiles[preferred_name])

        candidates = [
            profile
            for name, profile in profiles.items()
            if name not in {"vision_selected_item", "source_visual_selection"}
        ]
        if not candidates:
            return dict(self.DEFAULT_DRAG_PROFILES[0])

        def score(profile: Dict[str, Any]) -> float:
            successes = float(profile.get("successes", 0))
            failures = float(profile.get("failures", 0))
            return (successes * 3.0) - (failures * 1.25)

        return dict(max(candidates, key=score))

    def _window_layout_mode_for_category(self, category: str) -> str:
        categories = self.drag_strategy.setdefault("categories", {})
        category_stats = categories.setdefault(category, {"preferred_profile": "", "successes": 0, "failures": 0})
        preferred = str(category_stats.get("preferred_window_layout") or "").strip()
        if preferred:
            return preferred
        window_management = self.drag_strategy.setdefault("window_management", {})
        if bool(window_management.get("strict_split_enabled")):
            return "strict_split_explorer_halves"
        return "balanced_split_explorer"

    def _should_force_strict_window_layout(self, category: str) -> bool:
        return self._window_layout_mode_for_category(category) == "strict_split_explorer_halves"

    def _normalize_point_to_window(
        self,
        point: Optional[Tuple[int, int]],
        window: Optional[Any],
    ) -> Optional[Dict[str, float]]:
        if not point:
            return None
        if window is not None:
            try:
                left = int(getattr(window, "left", 0))
                top = int(getattr(window, "top", 0))
                width = int(getattr(window, "width", 0))
                height = int(getattr(window, "height", 0))
                if width > 0 and height > 0:
                    return {
                        "horizontal": min(max((point[0] - left) / width, 0.0), 1.0),
                        "vertical": min(max((point[1] - top) / height, 0.0), 1.0),
                    }
            except Exception:
                pass
        try:
            bounds = self.vision._screen_bounds()
            if bounds:
                left, top, width, height = bounds
                if width > 0 and height > 0:
                    return {
                        "horizontal": min(max((point[0] - left) / width, 0.0), 1.0),
                        "vertical": min(max((point[1] - top) / height, 0.0), 1.0),
                    }
        except Exception:
            pass
        return None

    def _blend_profile_value(self, current: float, observed: float, alpha: float = 0.2) -> float:
        return float(max(0.0, min(1.0, current * (1.0 - alpha) + observed * alpha)))

    def _refine_drag_profile(
        self,
        profile_name: str,
        source_point: Tuple[int, int],
        destination_point: Tuple[int, int],
        source_window: Optional[Any],
        destination_window: Optional[Any],
        duration: float,
    ) -> None:
        profiles = self.drag_strategy.setdefault("profiles", {})
        profile = profiles.setdefault(profile_name, {"name": profile_name, "successes": 0, "failures": 0})
        source_coords = self._normalize_point_to_window(source_point, source_window)
        destination_coords = self._normalize_point_to_window(destination_point, destination_window)
        if source_coords:
            profile["source_horizontal"] = self._blend_profile_value(
                float(profile.get("source_horizontal", 0.42)), source_coords["horizontal"]
            )
            profile["source_vertical"] = self._blend_profile_value(
                float(profile.get("source_vertical", 0.46)), source_coords["vertical"]
            )
        if destination_coords:
            profile["destination_horizontal"] = self._blend_profile_value(
                float(profile.get("destination_horizontal", 0.54)), destination_coords["horizontal"]
            )
            profile["destination_vertical"] = self._blend_profile_value(
                float(profile.get("destination_vertical", 0.48)), destination_coords["vertical"]
            )
        profile["duration"] = float(
            profile.get("duration", duration) * 0.85 + duration * 0.15
        )
        self.drag_strategy["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_drag_strategy()
        self._record_mouse_step(
            reason="refinar perfil de drag",
            status="updated",
            payload={
                "profile": profile_name,
                "source_coords": source_coords,
                "destination_coords": destination_coords,
                "duration": profile["duration"],
            },
        )

    def _learn_drag_outcome(
        self,
        profile_name: str,
        category: str,
        success: bool,
        details: Dict[str, Any],
    ) -> None:
        profiles = self.drag_strategy.setdefault("profiles", {})
        profile = profiles.setdefault(profile_name, {"name": profile_name, "successes": 0, "failures": 0})
        key = "successes" if success else "failures"
        profile[key] = int(profile.get(key, 0)) + 1
        profile["last_result"] = "success" if success else "failure"
        profile["last_updated"] = datetime.now().isoformat(timespec="seconds")

        categories = self.drag_strategy.setdefault("categories", {})
        category_stats = categories.setdefault(category, {"preferred_profile": "", "successes": 0, "failures": 0})
        category_stats["successes" if success else "failures"] = int(
            category_stats.get("successes" if success else "failures", 0)
        ) + 1
        if success:
            category_stats["preferred_profile"] = profile_name
        elif category_stats.get("preferred_profile") == profile_name:
            category_stats["preferred_profile"] = ""

        pre_drag_verification = details.get("pre_drag_verification") or {}
        window_layout_repair = details.get("window_layout_repair") or {}
        window_management = self.drag_strategy.setdefault("window_management", {})
        if pre_drag_verification.get("source_occluded"):
            window_management["source_occlusion_failures"] = int(
                window_management.get("source_occlusion_failures", 0)
            ) + 1
            window_management["strict_split_enabled"] = True
            category_stats["preferred_window_layout"] = "strict_split_explorer_halves"
        elif success and details.get("window_layout_mode") == "strict_split_explorer_halves":
            window_management["successful_split_layouts"] = int(
                window_management.get("successful_split_layouts", 0)
            ) + 1
            category_stats["preferred_window_layout"] = "strict_split_explorer_halves"

        if window_layout_repair.get("attempted"):
            window_management["repair_attempts"] = int(window_management.get("repair_attempts", 0)) + 1
            if window_layout_repair.get("recovered"):
                window_management["repair_successes"] = int(window_management.get("repair_successes", 0)) + 1
                window_management["strict_split_enabled"] = True
                category_stats["preferred_window_layout"] = "strict_split_explorer_halves"
            else:
                window_management["repair_failures"] = int(window_management.get("repair_failures", 0)) + 1
        window_management["last_result"] = "success" if success else "failure"
        window_management["last_updated"] = datetime.now().isoformat(timespec="seconds")

        attempts = self.drag_strategy.setdefault("attempts", [])
        attempts.append(
            {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "profile": profile_name,
                "category": category,
                "success": success,
                "details": details,
            }
        )
        self.drag_strategy["attempts"] = attempts[-100:]
        self.drag_strategy["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_drag_strategy()

        self._record_mouse_step(
            reason="aprender resultado drag",
            status="success" if success else "failure",
            payload={
                "profile": profile_name,
                "category": category,
                "success": success,
                "details": details,
            },
        )

    def _save_drag_strategy(self) -> None:
        self.store.save_drag_strategy(self.drag_strategy)

    def _record_mouse_step(self, reason: str, status: str, payload: Dict[str, Any]) -> None:
        if hasattr(self.memory, "record_step_log"):
            self.memory.record_step_log(
                task_intent="desktop_mouse_learning",
                step_name=reason,
                status=status,
                detail=json.dumps(payload, ensure_ascii=False),
            )

    def _wait_for_path(self, path: Path, timeout: float = 2.5) -> bool:
        deadline = time.time() + timeout
        while time.time() <= deadline:
            if path.exists():
                return True
            self.sleep(0.15)
        return path.exists()

    def _cancel_possible_dialog(self) -> None:
        try:
            self.automation.press_keys(["esc"])
        except Exception:
            pass

    def _resolve_gesture(self, gesture_policy: str) -> str:
        if gesture_policy == "drag_and_drop":
            return "drag_and_drop"
        if gesture_policy in {"mixed_gradual", "drag_then_cut_paste", "drag_first"}:
            return "drag_then_cut_paste"
        return "cut_paste_visible"

    def _bounded_practice_attempts(self, attempts: Optional[int], default_value: int) -> int:
        settings = self.config.get("desktop_organizer", {})
        max_attempts = max(1, int(settings.get("mouse_practice_max_attempts", 100)))
        requested = default_value if attempts is None else int(attempts)
        return max(1, min(requested, max_attempts))

    def _resolve_real_file_gesture_policy(self, gesture_policy: str) -> str:
        gesture = self._resolve_gesture(gesture_policy)
        if gesture not in {"drag_then_cut_paste", "drag_and_drop"}:
            return gesture_policy
        if self._real_drag_allowed():
            return gesture_policy
        return "cut_paste_visible"

    def _real_drag_allowed(self) -> bool:
        settings = self.config.get("desktop_organizer", {})
        if not bool(settings.get("require_mouse_practice_for_real_drag", True)):
            return True
        practice = self.drag_strategy.get("practice", {})
        return bool(practice.get("real_drag_enabled", False))

    def _desktop_path(self) -> Path:
        folders = self.config.get("frequent_folders", {})
        desktop_raw = folders.get("desktop") or folders.get("escritorio") or str(Path.home() / "Desktop")
        desktop = Path(desktop_raw).expanduser()
        if not desktop.exists():
            raise FileNotFoundError(f"No se encontro el escritorio en: {desktop}")
        return desktop

    def _movement_practice_points(self, count: int) -> List[Tuple[int, int]]:
        try:
            bounds = self.vision._screen_bounds()
            if bounds:
                left, top, width, height = bounds
            else:
                left, top, width, height = 0, 0, 1200, 800
        except Exception:
            left, top, width, height = 0, 0, 1200, 800

        ratios = [
            (0.50, 0.50),
            (0.25, 0.30),
            (0.75, 0.30),
            (0.25, 0.70),
            (0.75, 0.70),
            (0.50, 0.25),
            (0.50, 0.75),
            (0.35, 0.50),
            (0.65, 0.50),
        ]
        rng = random.Random(f"movement:{time.time_ns()}:{count}")
        rng.shuffle(ratios)
        margin = max(40, min(80, int(min(width, height) * 0.12)))
        jitter_x = max(8, min(90, int(width * 0.055)))
        jitter_y = max(8, min(70, int(height * 0.055)))
        points: List[Tuple[int, int]] = []
        for index in range(count):
            horizontal, vertical = ratios[index % len(ratios)]
            wave_offset = ((index // len(ratios)) % 5 - 2) * 14
            random_x = rng.randint(-jitter_x, jitter_x)
            random_y = rng.randint(-jitter_y, jitter_y)
            x = int(left + min(max(width * horizontal + wave_offset + random_x, margin), width - margin))
            y = int(top + min(max(height * vertical - wave_offset + random_y, margin), height - margin))
            points.append((x, y))
        return points

    def _get_mouse_position(self) -> Optional[Tuple[int, int]]:
        if not hasattr(self.automation, "get_mouse_position"):
            return None
        try:
            x, y = self.automation.get_mouse_position()
            return int(x), int(y)
        except Exception:
            return None

    @staticmethod
    def _distance_pixels(target: Tuple[int, int], actual: Tuple[int, int]) -> float:
        dx = float(target[0] - actual[0])
        dy = float(target[1] - actual[1])
        return (dx * dx + dy * dy) ** 0.5

    def _practice_profiles(self) -> List[Dict[str, Any]]:
        profiles = self.drag_strategy.setdefault("profiles", {})
        ordered: List[Dict[str, Any]] = []
        for default_profile in self.DEFAULT_DRAG_PROFILES:
            profile = profiles.get(default_profile["name"], default_profile)
            ordered.append(dict(profile))

        def score(profile: Dict[str, Any]) -> float:
            successes = float(profile.get("successes", 0))
            failures = float(profile.get("failures", 0))
            return (successes * 3.0) - (failures * 1.25)

        ordered.sort(key=score, reverse=True)
        return ordered or [dict(self.DEFAULT_DRAG_PROFILES[0])]

    def _practice_profile_sequence(self, count: int) -> List[Dict[str, Any]]:
        profiles = self._practice_profiles()
        if not profiles:
            return [dict(self.DEFAULT_DRAG_PROFILES[0]) for _ in range(max(1, count))]
        sequence: List[Dict[str, Any]] = []
        while len(sequence) < max(1, count):
            batch = [dict(profile) for profile in profiles]
            random.shuffle(batch)
            sequence.extend(batch)
        return sequence[: max(1, count)]

    def _record_mouse_practice_summary(self, session: DesktopLearningSession) -> None:
        settings = self.config.get("desktop_organizer", {})
        required_rate = float(settings.get("mouse_practice_required_success_rate", 0.7))
        min_successes = max(1, int(settings.get("mouse_practice_min_successes", 3)))
        total = len(session.moves)
        successes = sum(1 for move in session.moves if move.verified)
        failures = total - successes
        success_rate = successes / total if total else 0.0
        real_drag_enabled = success_rate >= required_rate and successes >= min_successes

        self.drag_strategy["practice"] = {
            "last_session_id": session.session_id,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "attempts": total,
            "successes": successes,
            "failures": failures,
            "success_rate": round(success_rate, 3),
            "required_success_rate": required_rate,
            "min_successes": min_successes,
            "real_drag_enabled": real_drag_enabled,
            "recommendation": (
                "drag_real_allowed"
                if real_drag_enabled
                else "keep_practicing_or_use_cut_paste_visible_for_real_files"
            ),
        }
        self._save_drag_strategy()
        self._record_mouse_step(
            reason="resumen practica mouse",
            status="enabled" if real_drag_enabled else "needs_practice",
            payload=self.drag_strategy["practice"],
        )

    def _record_mouse_movement_practice_summary(
        self,
        session: DesktopLearningSession,
        tolerance: int,
    ) -> None:
        attempts = len(session.moves)
        successes = sum(1 for move in session.moves if move.verified)
        failures = attempts - successes
        errors = [
            float(move.details["error_pixels"])
            for move in session.moves
            if move.details.get("error_pixels") is not None
        ]
        average_error = sum(errors) / len(errors) if errors else 0.0
        max_error = max(errors) if errors else 0.0
        success_rate = successes / attempts if attempts else 0.0
        reliable = success_rate >= 0.9

        practice = self.drag_strategy.setdefault("practice", {})
        practice["movement"] = {
            "last_session_id": session.session_id,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "attempts": attempts,
            "successes": successes,
            "failures": failures,
            "success_rate": round(success_rate, 3),
            "tolerance_pixels": tolerance,
            "average_error_pixels": round(average_error, 3),
            "max_error_pixels": round(max_error, 3),
            "reliable": reliable,
        }
        self.drag_strategy["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_drag_strategy()
        self._record_mouse_step(
            reason="resumen practica movimiento mouse",
            status="reliable" if reliable else "needs_practice",
            payload=practice["movement"],
        )

    def _practice_mouse_gesture(
        self,
        skill_key: str,
        mode: str,
        gesture: str,
        category: str,
        summary_label: str,
        attempts: Optional[int],
        default_attempts: int,
        button: str,
        clicks: int,
        close_menu: bool,
    ) -> str:
        settings = self.config.get("desktop_organizer", {})
        attempt_count = self._bounded_practice_attempts(attempts, default_value=default_attempts)
        tolerance = max(1, int(settings.get("mouse_move_tolerance_pixels", 12)))
        desktop = self._desktop_path()
        session_id = f"{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        session = DesktopLearningSession(
            session_id=session_id,
            created_at=datetime.now().isoformat(timespec="seconds"),
            mode=mode,
            gesture_policy=gesture,
            desktop_path=str(desktop),
            root_folder=str(desktop),
            manifest_path=str(self.sessions_dir / f"{session_id}.json"),
        )
        session.notes.append(
            f"Sesion segura: practica {summary_label} en puntos visibles sin mover archivos."
        )

        self._record_session_header(session)
        for index, target in enumerate(self._movement_practice_points(attempt_count), start=1):
            if self._stop_requested():
                self._mark_practice_stopped(session, summary_label)
                break
            started = time.perf_counter()
            x, y = target
            self._emit(f"Practica {summary_label} {index}/{attempt_count}: ({x}, {y})", "info")
            actual: Optional[Tuple[int, int]] = None
            error_pixels: Optional[float] = None
            try:
                self.automation.move_mouse(x, y, duration=0.22)
                self.sleep(0.06)
                self.automation.click(
                    x,
                    y,
                    button=button,
                    clicks=clicks,
                    duration=0.06,
                )
                self.sleep(0.08)
                if close_menu:
                    self._cancel_possible_dialog()
                actual = self._get_mouse_position()
                if actual:
                    error_pixels = self._distance_pixels(target, actual)
                    verified = error_pixels <= tolerance
                else:
                    verified = False
                status = "completed" if verified else "failed"
                error = "" if verified else "El gesto termino fuera de la tolerancia configurada."
            except Exception as exc:
                if close_menu:
                    self._cancel_possible_dialog()
                verified = False
                status = "failed"
                error = str(exc)

            record = DesktopLearningMoveRecord(
                source="mouse",
                destination=f"point:{x},{y}",
                category=category,
                gesture=gesture,
                status=status,
                duration_seconds=round(time.perf_counter() - started, 3),
                verified=verified,
                error=error,
                details={
                    "target": [x, y],
                    "actual": list(actual) if actual else None,
                    "error_pixels": round(error_pixels, 3) if error_pixels is not None else None,
                    "tolerance_pixels": tolerance,
                    "button": button,
                    "clicks": clicks,
                    "practice": True,
                },
            )
            session.moves.append(record)
            self._record_move(session, record)
            self._record_mouse_step(
                reason=f"practica {summary_label}",
                status=status,
                payload=record.details,
            )
            self._write_manifest(session)

        self._record_mouse_gesture_practice_summary(
            session=session,
            skill_key=skill_key,
            summary_label=summary_label,
            tolerance=tolerance,
        )
        self._record_session_header(session)
        self._write_manifest(session)
        self._write_latest_gesture_practice_pointer(session, skill_key=skill_key)
        return self._summarize_gesture_practice_session(session, skill_key, summary_label)

    def _record_mouse_gesture_practice_summary(
        self,
        session: DesktopLearningSession,
        skill_key: str,
        summary_label: str,
        tolerance: int,
    ) -> None:
        attempts = len(session.moves)
        successes = sum(1 for move in session.moves if move.verified)
        failures = attempts - successes
        errors = [
            float(move.details["error_pixels"])
            for move in session.moves
            if move.details.get("error_pixels") is not None
        ]
        average_error = sum(errors) / len(errors) if errors else 0.0
        max_error = max(errors) if errors else 0.0
        success_rate = successes / attempts if attempts else 0.0
        reliable = success_rate >= 0.9

        practice = self.drag_strategy.setdefault("practice", {})
        practice[skill_key] = {
            "last_session_id": session.session_id,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "skill": summary_label,
            "attempts": attempts,
            "successes": successes,
            "failures": failures,
            "success_rate": round(success_rate, 3),
            "tolerance_pixels": tolerance,
            "average_error_pixels": round(average_error, 3),
            "max_error_pixels": round(max_error, 3),
            "reliable": reliable,
        }
        self.drag_strategy["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_drag_strategy()
        self._record_mouse_step(
            reason=f"resumen practica {summary_label}",
            status="reliable" if reliable else "needs_practice",
            payload=practice[skill_key],
        )

    def _record_mouse_simple_practice_summary(
        self,
        session: DesktopLearningSession,
        skill_key: str,
        summary_label: str,
    ) -> None:
        attempts = len(session.moves)
        successes = sum(1 for move in session.moves if move.verified)
        failures = attempts - successes
        success_rate = successes / attempts if attempts else 0.0
        reliable = success_rate >= 0.9

        practice = self.drag_strategy.setdefault("practice", {})
        practice[skill_key] = {
            "last_session_id": session.session_id,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "skill": summary_label,
            "attempts": attempts,
            "successes": successes,
            "failures": failures,
            "success_rate": round(success_rate, 3),
            "reliable": reliable,
        }
        self.drag_strategy["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_drag_strategy()
        self._record_mouse_step(
            reason=f"resumen practica {summary_label}",
            status="reliable" if reliable else "needs_practice",
            payload=practice[skill_key],
        )

    def _record_mouse_detection_practice_summary(
        self,
        session: DesktopLearningSession,
    ) -> None:
        attempts = len(session.moves)
        successes = sum(1 for move in session.moves if move.verified)
        failures = attempts - successes
        confirmed = sum(1 for move in session.moves if move.details.get("confirmed_point"))
        reused = sum(1 for move in session.moves if move.details.get("reused_detection_confirmed"))
        success_rate = successes / attempts if attempts else 0.0
        reuse_rate = reused / attempts if attempts else 0.0
        reliable = success_rate >= 0.9 and reuse_rate >= 0.8

        practice = self.drag_strategy.setdefault("practice", {})
        practice["detection"] = {
            "last_session_id": session.session_id,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "skill": "deteccion visual",
            "attempts": attempts,
            "successes": successes,
            "failures": failures,
            "success_rate": round(success_rate, 3),
            "confirmed_detections": confirmed,
            "reused_detections": reused,
            "reuse_rate": round(reuse_rate, 3),
            "reliable": reliable,
        }
        self.drag_strategy["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_drag_strategy()
        self._record_mouse_step(
            reason="resumen practica deteccion visual",
            status="reliable" if reliable else "needs_practice",
            payload=practice["detection"],
        )

    def _new_session(
        self,
        preview: DesktopOrganizationPreview,
        gesture_policy: str,
    ) -> DesktopLearningSession:
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        manifest_path = self.sessions_dir / f"{session_id}.json"
        return DesktopLearningSession(
            session_id=session_id,
            created_at=datetime.now().isoformat(timespec="seconds"),
            mode="ui_learning",
            gesture_policy=gesture_policy,
            desktop_path=preview.desktop_path,
            root_folder=preview.root_folder,
            manifest_path=str(manifest_path),
        )

    def _record_session_header(self, session: DesktopLearningSession) -> None:
        if not hasattr(self.memory, "record_desktop_learning_session"):
            return
        self.memory.record_desktop_learning_session(
            session_id=session.session_id,
            mode=session.mode,
            desktop_path=session.desktop_path,
            root_folder=session.root_folder,
            manifest_path=session.manifest_path,
            summary=session.to_dict(),
        )

    def _record_move(self, session: DesktopLearningSession, record: DesktopLearningMoveRecord) -> None:
        detail = asdict(record)
        if hasattr(self.memory, "record_desktop_learning_move"):
            self.memory.record_desktop_learning_move(
                session_id=session.session_id,
                source=record.source,
                destination=record.destination,
                category=record.category,
                gesture=record.gesture,
                status=record.status,
                error=record.error,
                duration_seconds=record.duration_seconds,
                verified=record.verified,
                details=detail,
            )
        if hasattr(self.memory, "record_step_log"):
            self.memory.record_step_log(
                task_intent="desktop_learning",
                step_name=Path(record.source).name,
                status=record.status,
                detail=json.dumps(detail, ensure_ascii=False),
            )

    def _write_manifest(self, session: DesktopLearningSession) -> None:
        path = self.store.write_manifest(session.to_dict())
        session.manifest_path = str(path)

    def _write_latest_pointer(self, session: DesktopLearningSession) -> None:
        self.store.write_latest_pointer(
            "latest.json",
            session_id=session.session_id,
            manifest_path=session.manifest_path,
        )

    def _write_latest_practice_pointer(self, session: DesktopLearningSession) -> None:
        self.store.write_latest_pointer(
            "latest_mouse_practice.json",
            session_id=session.session_id,
            manifest_path=session.manifest_path,
        )

    def _write_latest_movement_practice_pointer(self, session: DesktopLearningSession) -> None:
        self.store.write_latest_pointer(
            "latest_mouse_movement_practice.json",
            session_id=session.session_id,
            manifest_path=session.manifest_path,
        )

    def _write_latest_gesture_practice_pointer(
        self,
        session: DesktopLearningSession,
        skill_key: str,
    ) -> None:
        self.store.write_latest_pointer(
            f"latest_mouse_{skill_key}_practice.json",
            session_id=session.session_id,
            manifest_path=session.manifest_path,
        )

    def _summarize_session(self, session: DesktopLearningSession, total_candidates: int) -> str:
        completed = sum(1 for move in session.moves if move.status == "completed")
        completed_with_fallback = sum(
            1 for move in session.moves if move.status == "completed_with_fallback"
        )
        failed = sum(1 for move in session.moves if move.status == "failed")
        manual = sum(1 for move in session.moves if move.status == "requires_manual_review")
        pending = max(0, total_candidates - len(session.moves))
        extra = f" Pendientes por limite de lote: {pending}." if pending else ""
        learning_note = next(
            (note for note in session.notes if note.startswith("Drag real desactivado")),
            "",
        )
        prefix = f"{learning_note} " if learning_note else ""
        return (
            f"{prefix}Ordenado visible completado. "
            f"Movidos: {completed + completed_with_fallback}. "
            f"Con fallback: {completed_with_fallback}. "
            f"Revision manual: {manual}. Fallidos: {failed}."
            f"{extra} Manifiesto: {session.manifest_path}"
        )

    def _summarize_practice_session(self, session: DesktopLearningSession) -> str:
        completed = sum(1 for move in session.moves if move.verified)
        failed = len(session.moves) - completed
        practice = self.drag_strategy.get("practice", {})
        success_rate = float(practice.get("success_rate", 0.0)) * 100
        status = (
            "Drag real habilitado para proximas sesiones."
            if practice.get("real_drag_enabled")
            else "Drag real aun suspendido; seguire usando cortar/pegar visible en archivos reales."
        )
        return (
            "Practica de mouse completada. "
            f"Exitos: {completed}. Fallos: {failed}. Tasa: {success_rate:.0f}%. "
            f"{status} Manifiesto: {session.manifest_path}"
        )

    def _summarize_movement_practice_session(self, session: DesktopLearningSession) -> str:
        completed = sum(1 for move in session.moves if move.verified)
        failed = len(session.moves) - completed
        movement = self.drag_strategy.get("practice", {}).get("movement", {})
        success_rate = float(movement.get("success_rate", 0.0)) * 100
        average_error = float(movement.get("average_error_pixels", 0.0))
        status = (
            "Movimiento basico confiable."
            if movement.get("reliable")
            else "Movimiento basico aun necesita practica."
        )
        return (
            "Practica de movimiento de mouse completada. "
            f"Exitos: {completed}. Fallos: {failed}. Tasa: {success_rate:.0f}%. "
            f"Error promedio: {average_error:.1f}px. {status} "
            f"Manifiesto: {session.manifest_path}"
        )

    def _summarize_gesture_practice_session(
        self,
        session: DesktopLearningSession,
        skill_key: str,
        summary_label: str,
    ) -> str:
        completed = sum(1 for move in session.moves if move.verified)
        failed = len(session.moves) - completed
        practice = self.drag_strategy.get("practice", {}).get(skill_key, {})
        success_rate = float(practice.get("success_rate", 0.0)) * 100
        average_error = float(practice.get("average_error_pixels", 0.0))
        status = (
            f"{summary_label.capitalize()} confiable."
            if practice.get("reliable")
            else f"{summary_label.capitalize()} aun necesita practica."
        )
        return (
            f"Practica de {summary_label} completada. "
            f"Exitos: {completed}. Fallos: {failed}. Tasa: {success_rate:.0f}%. "
            f"Error promedio: {average_error:.1f}px. {status} "
            f"Manifiesto: {session.manifest_path}"
        )

    def _summarize_simple_practice_session(
        self,
        session: DesktopLearningSession,
        skill_key: str,
        summary_label: str,
    ) -> str:
        completed = sum(1 for move in session.moves if move.verified)
        failed = len(session.moves) - completed
        practice = self.drag_strategy.get("practice", {}).get(skill_key, {})
        success_rate = float(practice.get("success_rate", 0.0)) * 100
        status = (
            f"{summary_label.capitalize()} confiable."
            if practice.get("reliable")
            else f"{summary_label.capitalize()} aun necesita practica."
        )
        return (
            f"Practica de {summary_label} completada. "
            f"Exitos: {completed}. Fallos: {failed}. Tasa: {success_rate:.0f}%. "
            f"{status} Manifiesto: {session.manifest_path}"
        )

    def _summarize_detection_practice_session(self, session: DesktopLearningSession) -> str:
        completed = sum(1 for move in session.moves if move.verified)
        failed = len(session.moves) - completed
        practice = self.drag_strategy.get("practice", {}).get("detection", {})
        success_rate = float(practice.get("success_rate", 0.0)) * 100
        reuse_rate = float(practice.get("reuse_rate", 0.0)) * 100
        status = (
            "Deteccion visual reutilizable confiable."
            if practice.get("reliable")
            else "Deteccion visual aun necesita practica."
        )
        return (
            "Practica de deteccion visual completada. "
            f"Exitos: {completed}. Fallos: {failed}. Tasa: {success_rate:.0f}%. "
            f"Reutilizacion: {reuse_rate:.0f}%. {status} "
            f"Manifiesto: {session.manifest_path}"
        )

    def _emit(self, message: str, level: str = "info") -> None:
        if self.logger:
            log_method = getattr(self.logger, level if hasattr(self.logger, level) else "info")
            log_method(message)
        if self.progress_callback:
            self.progress_callback(message, level)

    def _stop_requested(self) -> bool:
        try:
            return bool(self.stop_checker())
        except Exception as exc:
            self._emit(f"No pude consultar parada externa del entrenamiento: {exc}", "warning")
            return False

    def _mark_practice_stopped(
        self,
        session: DesktopLearningSession,
        summary_label: str,
    ) -> None:
        note = "Detenido por solicitud externa antes de completar todos los intentos."
        if note not in session.notes:
            session.notes.append(note)
        self._emit(f"Practica de {summary_label} detenida por solicitud externa.", "warning")

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
