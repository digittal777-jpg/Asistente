from __future__ import annotations

import ctypes
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.assistant_bootstrap import initialize_assistant_runtime
from core.automation import AutomationDependencyError
from core.command_parser import CommandAction, CommandParser, set_default_parser
from core.command_router import CommandRouter
from core.data_paths import DataPaths
from core.gui import RaphelGUI
from core.perception import ObservationBundle, PerceptionEngine
from core.remote_console import RemoteConsoleServer
from core.skills import normalize_text
from core.task_planner import TaskPlan, TaskPlanner
from core.task_executor import TaskExecutor
from core.vision import ScreenVision, VisionDependencyError, VisionSnapshot


class RaphelAssistant:
    INPUT_TRAINING_STOP_HOTKEY_TEXT = "mantener ESC 1.2s, Ctrl+Alt+S o Pause/Break"
    _INPUT_TRAINING_ESCAPE_HOLD_SECONDS = 1.2

    def __init__(self) -> None:
        self.base_dir = Path(__file__).resolve().parent.parent
        self.paths = DataPaths.from_base_dir(self.base_dir)
        self.paths.ensure_base_structure()
        initialize_assistant_runtime(self)
        self._current_action_trace: List[Dict[str, Any]] = []
        self._last_context_signature = ""
        self._artifacts: Dict[str, Any] = {}
        self._last_plan: Optional[TaskPlan] = None
        self.remote_console = RemoteConsoleServer(self, logger=self.logger)

        self.vision.add_snapshot_listener(self._on_vision_snapshot)
        if self.config.get("vision", {}).get("enabled", True):
            self.start_vision_monitor()

        self.logger.info("Raphel inicializado correctamente.")

    def add_status_listener(self, callback: Callable[[str, str], None]) -> None:
        self._status_listeners.append(callback)

    def add_context_listener(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self._context_listeners.append(callback)

    def set_confirmation_provider(self, callback: Optional[Callable[[str], bool]]) -> None:
        self._confirmation_provider = callback

    def emit_status(self, message: str, level: str = "info") -> None:
        for callback in self._status_listeners:
            try:
                callback(message, level)
            except Exception:
                continue

    def emit_context(self, context: Dict[str, Any]) -> None:
        for callback in self._context_listeners:
            try:
                callback(context)
            except Exception:
                continue

    def _notify(self, message: str) -> None:
        print(message)
        self.emit_status(message, "info")
        self.logger.info(message)
        self.history.record("notification", {"message": message})

    def _on_vision_snapshot(self, snapshot: VisionSnapshot) -> None:
        try:
            self.memory.save_vision_snapshot(snapshot)
        except Exception:
            self.logger.exception("No se pudo guardar snapshot de vision")

        payload = self._build_context_payload_from_snapshot(snapshot)
        self.emit_context(payload)

        perception = payload.get("perception", {})
        signature = (
            f"{snapshot.active_app}|{snapshot.active_site}|{snapshot.active_window}|"
            f"{perception.get('scene_kind', '')}"
        )
        if signature != self._last_context_signature:
            self._last_context_signature = signature
            message = self._format_context_message(snapshot)
            self.emit_status(message, "context")

    def run_console(self) -> None:
        print("Raphel listo. Escribe 'help' para ver comandos.")
        while self.running:
            try:
                command = input("Raphel> ").strip()
                result = self.handle_command(command)
                print(result)
            except KeyboardInterrupt:
                print("\nCerrando Raphel...")
                break
            except Exception as exc:
                print(f"Error: {exc}")
                self.logger.exception("Error en modo consola")
        self.shutdown()

    def run_gui(self) -> None:
        RaphelGUI(self).run()

    def shutdown(self) -> None:
        self.stop_input_training_loop()
        self.remote_console.stop()
        self.reminders.stop()
        self.stop_vision_monitor()

    def handle_command(self, raw_command: str) -> str:
        self._current_action_trace = []
        self.emit_status(f"Procesando: {raw_command}", "info")
        try:
            response = self.router.route(raw_command)
            self._remember_interaction(raw_command, response, success=True)
            self.history.record("command", {"command": raw_command, "response": response})
            self.logger.info("Comando procesado: %s", raw_command)
            self.emit_status("Comando completado.", "info")
            return response
        except Exception as exc:
            self.logger.exception("Fallo procesando comando: %s", raw_command)
            self.history.record("error", {"command": raw_command, "error": str(exc)})
            self._remember_interaction(raw_command, f"Error: {exc}", success=False)
            self.emit_status(str(exc), "error")
            return f"Error: {exc}"

    def describe_command_plan(self, command: str) -> Optional[str]:
        if not self.router.is_natural_command(command):
            return None
        vision_snapshot = self.get_latest_vision_snapshot()
        interpretation = self.command_parser.interpret_command(command, vision_context=vision_snapshot)
        if self.task_planner.should_plan(command, interpretation):
            plan = self.task_planner.build_plan(command, interpretation, vision_snapshot)
            self._last_plan = plan
            return self.task_planner.summarize_plan(plan)
        return self.command_parser.summarize_interpretation(interpretation)

    def get_latest_vision_snapshot(self, refresh: bool = False) -> Optional[VisionSnapshot]:
        try:
            return self.vision.get_latest_snapshot(refresh=refresh)
        except Exception:
            return None

    def get_latest_perception(
        self,
        refresh: bool = False,
        snapshot: Optional[VisionSnapshot] = None,
    ) -> Optional[ObservationBundle]:
        try:
            if snapshot is not None:
                return self.perception.observe_snapshot(snapshot)
            return self.perception.observe(refresh=refresh)
        except Exception:
            return None

    def _build_context_payload_from_snapshot(
        self,
        snapshot: Optional[VisionSnapshot],
    ) -> Dict[str, Any]:
        perception = self.get_latest_perception(refresh=False, snapshot=snapshot)
        return {
            "snapshot": snapshot.to_dict() if snapshot else {},
            "perception": perception.to_dict() if perception else {},
        }

    def get_context_payload(self) -> Dict[str, Any]:
        snapshot = self.get_latest_vision_snapshot()
        return self._build_context_payload_from_snapshot(snapshot)

    def start_vision_monitor(self) -> str:
        started = self.vision.start_monitor(
            interval_seconds=float(self.config.get("vision", {}).get("interval_seconds", 1.5)),
            light_ocr=bool(self.config.get("vision", {}).get("light_ocr", True)),
        )
        return "Vision continua activada." if started else "La vision continua ya estaba activa."

    def stop_vision_monitor(self) -> str:
        stopped = self.vision.stop_monitor()
        return "Vision continua detenida." if stopped else "La vision continua ya estaba detenida."

    def vision_status(self) -> str:
        snapshot = self.get_latest_vision_snapshot()
        if not snapshot:
            return "Vision sin snapshot todavia."
        status = "activa" if self.vision.is_monitoring else "detenida"
        perception = self.get_latest_perception(refresh=False, snapshot=snapshot)
        return (
            f"Vision {status}. Ventana activa: {snapshot.active_window or 'ninguna'} | "
            f"App: {snapshot.active_app or 'desconocida'} | Sitio: {snapshot.active_site or 'desconocido'}"
            + (
                f" | Escena: {perception.scene_kind}"
                if perception and perception.scene_kind
                else ""
            )
        )

    def calibration_status(self) -> str:
        manifest_path = self.vision.profile_manifest_path
        if not manifest_path.exists():
            return "No hay perfil de calibracion local todavia."
        return f"Perfil de calibracion local listo en: {manifest_path}"

    def ui_calibration_targets(self) -> List[Dict[str, str]]:
        return [
            {"name": "youtube_search_bar", "app": "youtube"},
            {"name": "youtube_search_button", "app": "youtube"},
            {"name": "google_search_bar", "app": "google"},
            {"name": "google_result_card", "app": "google"},
            {"name": "browser_address_bar", "app": "browser"},
            {"name": "taskbar_brave", "app": "taskbar"},
            {"name": "taskbar_word", "app": "taskbar"},
            {"name": "taskbar_spotify", "app": "taskbar"},
            {"name": "document_body", "app": "word"},
        ]

    def calibrate_ui_target(
        self,
        name: str,
        app: str,
        size: Optional[tuple[int, int]] = None,
    ) -> str:
        x, y = self.automation.get_mouse_position()
        path = self.vision.calibrate_template_from_point(
            name=name,
            center_x=x,
            center_y=y,
            app=app,
            size=size,
        )
        self.emit_status(f"Template calibrado: {name} -> {path}", "info")
        self.history.record("calibrate_ui_target", {"name": name, "app": app, "path": path})
        return path

    def learn_from_interaction(
        self,
        user_command: str,
        actions_taken: List[Dict[str, Any]],
        result: str,
    ) -> str:
        interaction_id = self.memory.learn_from_interaction(
            user_command,
            actions_taken,
            result,
            context=self.get_context_payload(),
        )
        return f"Interaccion aprendida y guardada con ID {interaction_id}."

    def _dispatch(self, action: str, args: List[str]) -> str:
        if action not in {"help", "exit", "skills", "history", "natural"}:
            self._current_action_trace.append({"action": action, "params": {"args": args}})

        if action == "help":
            return self._help_text()
        if action == "exit":
            self.running = False
            return "Raphel cerrara la sesion."
        if action == "skills":
            return self._list_skills()
        if action == "vision-status":
            return self.vision_status()
        if action == "vision-on":
            return self.start_vision_monitor()
        if action == "vision-off":
            return self.stop_vision_monitor()
        if action == "calibrate-ui":
            return self.calibration_status()
        if action == "memory":
            return self.read_recent_history()
        if action == "learning-status":
            return self.learning_status()
        if action == "doctor":
            return self.run_doctor()
        if action == "p1-validation":
            execute_live = any(arg in {"--execute-live", "execute-live", "live"} for arg in args or [])
            supervised = any(arg in {"--supervised", "supervised"} for arg in args or [])
            return self.run_p1_validation(execute_live=execute_live, supervised=supervised)
        if action == "reevaluate-levels":
            return self.reevaluate_skill_levels()
        if action == "reset-runtime":
            return self.reset_runtime()
        if action == "remote-console-start":
            port = int(args[0]) if args else None
            return self.start_remote_console(port=port, expose_online=False)
        if action == "remote-console-online":
            port = int(args[0]) if args else None
            return self.start_remote_console(port=port, expose_online=True)
        if action == "remote-console-stop":
            return self.stop_remote_console()
        if action == "remote-console-status":
            return self.remote_console_status()
        if action == "input-training-start":
            attempts = int(args[0]) if args else None
            return self.start_input_training_loop(
                mouse_attempts=attempts,
                keyboard_attempts=attempts,
            )
        if action == "input-training-stop":
            return self.stop_input_training_loop()
        if action == "input-training-status":
            return self.input_training_status()
        if action == "skill-learn":
            parsed = self._parse_skill_budget_request(args[0] if args else "")
            return self.learn_skill(
                skill=parsed["skill"],
                goal=parsed.get("goal"),
                attempts=parsed.get("attempts"),
                minutes=parsed.get("minutes"),
                create_document=parsed.get("create_document", False),
            )
        if action == "skill-practice":
            parsed = self._parse_skill_budget_request(args[0] if args else "")
            return self.practice_skill(
                skill=parsed["skill"],
                attempts=parsed.get("attempts"),
                minutes=parsed.get("minutes"),
            )
        if action == "skill-evaluate":
            return self.evaluate_skill(args[0] if args else "")
        if action == "skill-use":
            create_document = len(args) > 2 and args[2].strip().lower() == "document"
            return self.use_skill(
                skill=args[0],
                goal=args[1],
                create_document=create_document,
            )
        if action == "skill-bootstrap":
            return self.bootstrap_skill_profiles()
        if action == "skill-status":
            return self.skill_status(args[0] if args else None)
        if action == "autonomous-learn":
            return self.autonomous_learn(args[0] if args else "")
        if action == "autonomous-status":
            return self.autonomous_status()
        if action == "desktop-organize":
            return self.organize_desktop()
        if action == "desktop-organize-fast":
            return self.organize_desktop(execution_mode="legacy_filesystem")
        if action == "desktop-arrange-icons":
            return self.arrange_desktop_icons()
        if action == "desktop-practice-mouse":
            attempts = int(args[0]) if args else None
            return self.practice_desktop_mouse(attempts=attempts)
        if action == "desktop-practice-mouse-move":
            attempts = int(args[0]) if args else None
            return self.practice_mouse_movement(attempts=attempts)
        if action == "desktop-practice-mouse-click":
            attempts = int(args[0]) if args else None
            return self.practice_mouse_click(attempts=attempts)
        if action == "desktop-practice-mouse-double-click":
            attempts = int(args[0]) if args else None
            return self.practice_mouse_double_click(attempts=attempts)
        if action == "desktop-practice-mouse-right-click":
            attempts = int(args[0]) if args else None
            return self.practice_mouse_right_click(attempts=attempts)
        if action == "desktop-practice-mouse-selection":
            attempts = int(args[0]) if args else None
            return self.practice_mouse_selection(attempts=attempts)
        if action == "desktop-practice-mouse-detection":
            attempts = int(args[0]) if args else None
            return self.practice_mouse_detection(attempts=attempts)
        if action == "desktop-practice-mouse-workflow":
            attempts = int(args[0]) if args else None
            return self.practice_mouse_workflow(attempts=attempts)
        if action == "desktop-undo-last":
            return self.undo_last_desktop_organization()
        if action == "desktop-icons":
            return self.list_desktop_icons()
        if action == "desktop-learn":
            name, aliases = self._split_named_aliases(args[0])
            return self.train_desktop_icon(name, aliases=aliases)
        if action == "desktop-click":
            return self.click_desktop_icon(args[0], open_icon=False)
        if action == "desktop-open":
            return self.click_desktop_icon(args[0], open_icon=True)
        if action == "run-skill":
            return self.skill_manager.run_skill(args[0])
        if action == "learn-file":
            return self._learn_from_file(args[0])
        if action == "learn":
            return self._learn_from_command(args)
        if action == "feedback":
            return self._learn_feedback_from_command(args)
        if action == "open-project":
            return self.open_project(args[0])
        if action == "open-browser":
            url = args[1] if len(args) > 1 else None
            return self.open_browser(args[0], url=url)
        if action == "open-app":
            return self.open_application(args[0])
        if action == "open-folder":
            return self.open_folder(args[0])
        if action == "open-url":
            return self.open_url(args[0])
        if action == "type":
            return self.write_text(args[0])
        if action == "write-window":
            return self.write_text_to_window(args[0], args[1])
        if action == "hotkey":
            return self.hotkey(*[part.strip() for part in args if part.strip()])
        if action == "click":
            return self.click(int(args[0]), int(args[1]))
        if action == "drag":
            return self.drag_mouse(int(args[0]), int(args[1]), int(args[2]), int(args[3]))
        if action == "move":
            return self.move_mouse(int(args[0]), int(args[1]))
        if action == "click-image":
            return self.click_image(args[0])
        if action == "screenshot":
            path = args[0] if args else None
            return self.take_screenshot(path)
        if action == "google":
            return self.search_google(args[0])
        if action == "youtube":
            return self.search_youtube(args[0])
        if action == "spotify":
            return self.open_spotify_search(args[0])
        if action == "volume":
            return self.adjust_volume(args[0], int(args[1]))
        if action == "volume-set":
            return self.set_volume_percent(int(args[0]))
        if action == "media":
            return self.media_control(args[0])
        if action == "ocr":
            return self.extract_text()
        if action == "find-text":
            return self.find_text(args[0])
        if action == "pixel-color":
            return self.pixel_color(int(args[0]), int(args[1]))
        if action == "find-color":
            rgb = [int(args[0]), int(args[1]), int(args[2])]
            return self.find_color(rgb, int(args[3]))
        if action == "focus-window":
            return self.focus_window(args[0])
        if action == "close-window":
            return self.close_window(args[0]) if args else self.close_current_window()
        if action == "maximize-window":
            return self.maximize_current_window()
        if action == "minimize-all":
            return self.minimize_all_windows()
        if action == "tab":
            return self.browser_tab(args[0])
        if action == "remind":
            return self.add_reminder(int(args[0]), args[1])
        if action == "history":
            return self.read_recent_history()
        if action == "natural":
            return self.process_natural_language(args[0])
        raise ValueError(f"Accion no soportada: {action}")

    def _help_text(self) -> str:
        examples = "\n".join(f"- {item}" for item in CommandParser.supported_examples())
        return (
            "Raphel entiende comandos compuestos, contexto de pantalla y tareas planificadas.\n"
            "Ejemplos:\n"
            f"{examples}\n\n"
            "Escritorio:\n"
            "- desktop-organize (visible, con aprendizaje)\n"
            "- desktop-organize-fast (solo si activas fallback legacy)\n"
            "- desktop-arrange-icons (ordena visualmente los iconos)\n"
            "- desktop-practice-mouse 4 (practica drag con archivos temporales)\n"
            "- desktop-practice-mouse-move 100 (practica movimiento basico)\n"
            "- desktop-practice-mouse-click 100\n"
            "- desktop-practice-mouse-double-click 100\n"
            "- desktop-practice-mouse-right-click 100\n"
            "- desktop-practice-mouse-selection 100\n"
            "- desktop-practice-mouse-workflow 100\n"
            "- desktop-undo-last\n"
            "- desktop-learn Brave\n"
            "- desktop-click Brave\n"
            "- desktop-open Spotify\n"
            "- desktop-icons\n\n"
            "Calibracion visual:\n"
            "- calibrate-ui\n\n"
            "Aprendizaje inteligente:\n"
            "- learning-status\n\n"
            "- doctor\n"
            "- p1-validation\n"
            "- p1-validation --execute-live\n\n"
            "- reevaluate-levels\n"
            "- reset\n"
            "- autonomous-learn aprende a jugar minecraft\n"
            "- autonomous-status\n\n"
            "Consola remota:\n"
            "- remote-console-start 8765\n"
            "- remote-console-online 8765\n"
            "- remote-console-status\n"
            "- remote-console-stop\n\n"
            "Entrenamiento continuo:\n"
            "- input-training-start 6\n"
            "- input-training-status\n"
            "- input-training-stop\n"
            f"- parada rapida: {self.INPUT_TRAINING_STOP_HOTKEY_TEXT}\n\n"
            "Habilidades aprendibles:\n"
            "- skill-learn teclado\n"
            "- skill-practice investigar 10 minutos\n"
            "- skill-evaluate youtube\n"
            "- skill-use investigar|Rimuru Tempest\n"
            "- skill-bootstrap\n"
            "- skill-status\n\n"
            "Correccion por feedback:\n"
            "- feedback Abre Brvae y entra a Yotube|[{\"action\":\"ensure_browser\",\"params\":{\"browser\":\"brave\"}},{\"action\":\"ensure_site\",\"params\":{\"site\":\"youtube\",\"browser\":\"brave\"}}]\n\n"
            "Notas:\n"
            "- Durante entrenamiento infinito, mantener ESC 1.2s es la salida de emergencia mas facil.\n"
            "- Mueve el mouse a la esquina superior izquierda para activar FAILSAFE de pyautogui.\n"
            "- Algunas funciones requieren customtkinter, pygetwindow, rapidfuzz y Tesseract OCR."
        )

    def _list_skills(self) -> str:
        skills = self.skill_manager.list_skills()
        if not skills:
            return "No hay skills registradas."
        lines = []
        for skill in skills:
            kind = skill.metadata.get("kind", "unknown")
            trigger_preview = ", ".join(skill.triggers[:3]) if skill.triggers else "sin triggers"
            lines.append(f"- {skill.name} [{kind}] :: {skill.description} | triggers: {trigger_preview}")
        return "\n".join(lines)

    def _learn_from_command(self, args: List[str]) -> str:
        if len(args) != 3:
            raise ValueError("Formato learn invalido. Usa: learn nombre|descripcion|[{...}]")
        name, description, raw_steps = args
        steps = json.loads(raw_steps)
        path = self.learn_new_skill(name, description, steps, triggers=[name])
        return f"Nueva skill guardada en: {path}"

    def _learn_from_file(self, json_path: str) -> str:
        path = Path(json_path)
        if not path.is_absolute():
            path = self.base_dir / path
        if not path.exists():
            raise FileNotFoundError(f"No existe el archivo de skill: {path}")
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        learned_path = self.learn_new_skill(
            payload["name"],
            payload["description"],
            payload["steps"],
            triggers=payload.get("triggers"),
        )
        return f"Skill importada y guardada en: {learned_path}"

    def _learn_feedback_from_command(self, args: List[str]) -> str:
        if len(args) != 2:
            raise ValueError("Formato feedback invalido. Usa: feedback comando|[{...}]")
        user_command, raw_actions = args
        correct_actions = json.loads(raw_actions)
        return str(self.learn_from_feedback(user_command, correct_actions))

    def _parse_skill_budget_request(self, raw: str) -> Dict[str, Any]:
        text = (raw or "").strip()
        if not text:
            raise ValueError("Debes indicar una habilidad.")
        minutes_match = re.search(r"\b(\d{1,3})\s*min(?:uto)?s?\b", text, flags=re.IGNORECASE)
        attempts_match = re.search(r"\b(\d{1,3})\s*(?:veces|intentos?)\b", text, flags=re.IGNORECASE)
        create_document = bool(re.search(r"\b(?:word|documento|docx)\b", text, flags=re.IGNORECASE))
        clean = re.sub(r"\b\d{1,3}\s*min(?:uto)?s?\b", "", text, flags=re.IGNORECASE)
        clean = re.sub(r"\b\d{1,3}\s*(?:veces|intentos?)\b", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\b(?:en|durante)\b", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"^(?:el|la|los|las)\s+", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s+", " ", clean).strip(" |")
        skill_part = clean
        goal: Optional[str] = None
        if "|" in clean:
            skill_part, goal = [segment.strip() for segment in clean.split("|", 1)]
        return {
            "skill": skill_part,
            "goal": goal,
            "minutes": int(minutes_match.group(1)) if minutes_match else None,
            "attempts": int(attempts_match.group(1)) if attempts_match else None,
            "create_document": create_document,
        }

    def run_doctor(self) -> str:
        from core.doctor import RaphelDoctor

        doctor = RaphelDoctor(self.base_dir, config=self.config)
        report = doctor.run()
        output_path = doctor.write_report(report)
        return doctor.format_report(report, output_path)

    def run_p1_validation(self, execute_live: bool = False, supervised: bool = False) -> str:
        from core.p1_validation import P1LiveValidator

        validator = P1LiveValidator(self.base_dir, assistant_factory=lambda: self)
        report = validator.run(execute_live=execute_live, supervised=supervised)
        output_path = validator.write_report(report)
        return validator.format_report(report, output_path)

    def confirm_action(self, prompt: str) -> bool:
        if self._confirmation_provider:
            return bool(self._confirmation_provider(prompt))
        answer = input(f"{prompt} [s/N]: ").strip().lower()
        return answer in {"s", "si", "y", "yes"}

    def is_dangerous(self, text: str) -> bool:
        keywords = self.config.get("dangerous_keywords", [])
        lowered = text.lower()
        return any(keyword in lowered for keyword in keywords)

    def execute_action(self, action: str, step: Dict[str, Any]) -> str:
        original_step = dict(step)
        step = self.learning.adapt_action(action, original_step, context=self.get_context_payload())
        trace_entry = {"action": action, "params": dict(step)}
        if step != original_step:
            trace_entry["learned_adaptation"] = {"before": original_step, "after": dict(step)}
            self.emit_status(f"Aprendizaje ajusto accion {action}.", "info")
        self._current_action_trace.append(trace_entry)
        action_map = {
            "open_application": lambda s: self.open_application(s["target"], extra_args=s.get("extra_args")),
            "open_project": lambda s: self.open_project(
                s["name"], application=s.get("application", "visual studio code")
            ),
            "open_browser": lambda s: self.open_browser(
                s["browser"], url=s.get("url"), private=bool(s.get("private", False))
            ),
            "open_url": lambda s: self.open_url(
                s["url"],
                browser_name=s.get("browser"),
                private=bool(s.get("private", False)),
            ),
            "ensure_browser": lambda s: self.ensure_browser(
                browser=s.get("browser"),
                site=s.get("site"),
                private=bool(s.get("private", False)),
            ),
            "ensure_site": lambda s: self.ensure_site(
                site=s["site"],
                browser=s.get("browser"),
                private=bool(s.get("private", False)),
            ),
            "smart_site_search": lambda s: self.smart_site_search(
                destination=s["destination"],
                query=s["query"],
                browser=s.get("browser"),
                private=bool(s.get("private", False)),
            ),
            "smart_spotify_play": lambda s: self.smart_spotify_play(s["query"]),
            "write_active_context": lambda s: self.write_active_context(s["text"]),
            "capture_research_summary": lambda s: self.capture_research_summary(s["topic"]),
            "create_document": lambda s: self.create_document(
                application=s.get("application", "word"),
                title=s["title"],
                content=s.get("content"),
                filename=s.get("filename"),
                use_last_summary=bool(s.get("use_last_summary", False)),
            ),
            "learn_skill": lambda s: self.learn_skill(
                skill=s["skill"],
                goal=s.get("goal"),
                attempts=s.get("attempts"),
                minutes=s.get("minutes"),
                create_document=bool(s.get("create_document", False)),
            ),
            "practice_skill": lambda s: self.practice_skill(
                skill=s["skill"],
                attempts=s.get("attempts"),
                minutes=s.get("minutes"),
            ),
            "evaluate_skill": lambda s: self.evaluate_skill(s["skill"]),
            "use_skill": lambda s: self.use_skill(
                skill=s["skill"],
                goal=s["goal"],
                create_document=bool(s.get("create_document", False)),
            ),
            "skill_status": lambda s: self.skill_status(s.get("skill")),
            "reevaluate_skill_levels": lambda s: self.reevaluate_skill_levels(),
            "autonomous_learn": lambda s: self.autonomous_learn(
                s["objective"],
                use_research=bool(s.get("use_research", True)),
            ),
            "autonomous_status": lambda s: self.autonomous_status(),
            "start_input_training_loop": lambda s: self.start_input_training_loop(
                mouse_attempts=s.get("mouse_attempts"),
                keyboard_attempts=s.get("keyboard_attempts"),
                pause_seconds=float(s.get("pause_seconds", 2.0)),
            ),
            "stop_input_training_loop": lambda s: self.stop_input_training_loop(),
            "input_training_status": lambda s: self.input_training_status(),
            "execute_complex_task": lambda s: self.execute_complex_task(s),
            "open_folder": lambda s: self.open_folder(s.get("path") or s["target"]),
            "open_spotify_search": lambda s: self.open_spotify_search(s["query"]),
            "write_text": lambda s: self.write_text(
                s["text"], use_clipboard=s.get("use_clipboard", False)
            ),
            "write_text_to_window": lambda s: self.write_text_to_window(
                s["window_title"],
                s["text"],
                press_enter=s.get("press_enter", False),
                search_shortcut=s.get("search_shortcut"),
            ),
            "locate_and_click": lambda s: self.mouse_controller.locate_and_click(
                image_template=s["target"],
                confidence=float(s.get("confidence", 0.8)),
                timeout=float(s.get("timeout", 10)),
                button=s.get("button", "left"),
                app=s.get("app"),
            ),
            "locate_and_type": lambda s: self.mouse_controller.locate_and_type(
                target_name=s["target"],
                text=s["text"],
                confidence=float(s.get("confidence", 0.8)),
                timeout=float(s.get("timeout", 10)),
                select_all=bool(s.get("select_all", True)),
                press_enter=bool(s.get("press_enter", False)),
                use_clipboard=bool(s.get("use_clipboard", True)),
                interval=float(s.get("interval", 0.02)),
                app=s.get("app"),
            ),
            "click": lambda s: self.click(int(s["x"]), int(s["y"]), button=s.get("button", "left")),
            "move_mouse": lambda s: self.move_mouse(int(s["x"]), int(s["y"])),
            "drag_mouse": lambda s: self.drag_mouse(
                int(s["start_x"]),
                int(s["start_y"]),
                int(s["end_x"]),
                int(s["end_y"]),
            ),
            "wait": lambda s: self.automation.wait(float(s["seconds"])),
            "hotkey": lambda s: self.hotkey(*s["keys"]),
            "press_keys": lambda s: self.press_keys(s["keys"]),
            "search_google": lambda s: self.search_google(
                s["query"], browser=s.get("browser"), private=bool(s.get("private", False))
            ),
            "search_youtube": lambda s: self.search_youtube(
                s["query"], browser=s.get("browser"), private=bool(s.get("private", False))
            ),
            "take_screenshot": lambda s: self.take_screenshot(s.get("path")),
            "click_image": lambda s: self.click_image(
                s["template_path"], confidence=float(s.get("confidence", 0.85))
            ),
            "set_volume": lambda s: self.adjust_volume(s["direction"], int(s.get("steps", 5))),
            "set_volume_percent": lambda s: self.set_volume_percent(int(s["percent"])),
            "media_control": lambda s: self.media_control(s["mode"]),
            "run_shell": lambda s: self.run_shell(
                s["command"], dangerous=bool(s.get("dangerous", False))
            ),
            "ocr": lambda s: self.extract_text(),
            "find_text": lambda s: self.find_text(s["target_text"]),
            "find_color": lambda s: self.find_color(s["target_rgb"], int(s.get("tolerance", 10))),
            "focus_window": lambda s: self.focus_window(s["title"]),
            "close_current_window": lambda s: self.close_current_window(
                skip_confirmation=s.get("skip_confirmation", False)
            ),
            "close_window": lambda s: self.close_window(
                s["title"], skip_confirmation=s.get("skip_confirmation", False)
            ),
            "minimize_all_windows": lambda s: self.minimize_all_windows(),
            "maximize_current_window": lambda s: self.maximize_current_window(),
            "browser_tab": lambda s: self.browser_tab(s["mode"]),
            "organize_desktop": lambda s: self.organize_desktop(
                root_name=s.get("root_name"),
                move_shortcuts=s.get("move_shortcuts"),
                move_folders=s.get("move_folders"),
                skip_confirmation=s.get("skip_confirmation", False),
                execution_mode=s.get("execution_mode"),
            ),
            "arrange_desktop_icons": lambda s: self.arrange_desktop_icons(
                sort_by=s.get("sort_by", "name"),
                skip_confirmation=s.get("skip_confirmation", False),
            ),
            "practice_desktop_mouse": lambda s: self.practice_desktop_mouse(
                attempts=s.get("attempts"),
                skip_confirmation=s.get("skip_confirmation", False),
            ),
            "practice_mouse_movement": lambda s: self.practice_mouse_movement(
                attempts=s.get("attempts"),
                skip_confirmation=s.get("skip_confirmation", False),
            ),
            "practice_mouse_click": lambda s: self.practice_mouse_click(
                attempts=s.get("attempts"),
                skip_confirmation=s.get("skip_confirmation", False),
            ),
            "practice_mouse_double_click": lambda s: self.practice_mouse_double_click(
                attempts=s.get("attempts"),
                skip_confirmation=s.get("skip_confirmation", False),
            ),
            "practice_mouse_right_click": lambda s: self.practice_mouse_right_click(
                attempts=s.get("attempts"),
                skip_confirmation=s.get("skip_confirmation", False),
            ),
            "practice_mouse_selection": lambda s: self.practice_mouse_selection(
                attempts=s.get("attempts"),
                skip_confirmation=s.get("skip_confirmation", False),
            ),
            "practice_mouse_detection": lambda s: self.practice_mouse_detection(
                attempts=s.get("attempts"),
                skip_confirmation=s.get("skip_confirmation", False),
            ),
            "practice_mouse_workflow": lambda s: self.practice_mouse_workflow(
                attempts=s.get("attempts"),
                skip_confirmation=s.get("skip_confirmation", False),
            ),
            "desktop_undo_last": lambda s: self.undo_last_desktop_organization(
                skip_confirmation=s.get("skip_confirmation", False)
            ),
            "train_desktop_icon": lambda s: self.train_desktop_icon(
                s["name"],
                aliases=s.get("aliases"),
                capture_size=tuple(s["capture_size"]) if s.get("capture_size") else None,
            ),
            "click_desktop_icon": lambda s: self.click_desktop_icon(
                s["name"],
                open_icon=bool(s.get("open_icon", False)),
            ),
            "list_desktop_icons": lambda s: self.list_desktop_icons(),
            "run_skill": lambda s: self.skill_manager.run_skill(s["name"]),
        }
        if action not in action_map:
            raise ValueError(f"Accion de skill no soportada: {action}")
        try:
            result = action_map[action](step)
            self.learning.record_action_result(
                action=action,
                params=step,
                result=result,
                success=not str(result).lower().startswith("error"),
                context=self.get_context_payload(),
            )
            return result
        except Exception as exc:
            self.learning.record_action_result(
                action=action,
                params=step,
                result=str(exc),
                success=False,
                context=self.get_context_payload(),
            )
            raise

    def process_natural_language(self, command: str) -> str:
        vision_snapshot = self.get_latest_vision_snapshot()
        interpretation = self.command_parser.interpret_command(command, vision_context=vision_snapshot)
        if not interpretation.steps:
            learned = self.learning.suggest_command_actions(command)
            if learned:
                actions, note = learned
                interpretation.steps = actions
                interpretation.notes.append(note)
            else:
                note = interpretation.notes[0] if interpretation.notes else "No entendi el comando."
                return (
                    "No pude interpretar ese comando con seguridad.\n"
                    f"Detalle: {note}\n"
                    "Prueba con una frase mas directa o usa 'help'."
                )
        if interpretation.notes:
            for note in interpretation.notes:
                self.emit_status(note, "info")

        if self.task_planner.should_plan(command, interpretation):
            plan = self.task_planner.build_plan(command, interpretation, vision_snapshot)
            return self._execute_plan(plan)

        results: List[str] = []
        for step in interpretation.steps:
            if step.requires_confirmation:
                if not self.confirm_action(f"{step.summary}. Continuar?"):
                    results.append(f"Accion cancelada: {step.summary}")
                    self.emit_status(f"Cancelado: {step.summary}", "info")
                    continue
                step.params.setdefault("skip_confirmation", True)
            self.emit_status(f"Ejecutando: {step.summary}", "info")
            result = self.execute_action(step.action, step.params)
            results.append(result)
        return "\n".join(results)

    def _execute_plan(self, plan: TaskPlan) -> str:
        self._last_plan = plan
        task_id = self.memory.record_task_plan(plan.original_command, plan.intent, plan.to_dict())
        try:
            summary = self.task_executor.run_task(plan)
            self.memory.update_task_run(task_id, "completed", summary[:3000])
            return summary
        except Exception as exc:
            summary = f"Error: {exc}"
            self.memory.update_task_run(task_id, "failed", summary[:3000])
            raise

    def execute_complex_task(self, params: Dict[str, Any]) -> str:
        return self.task_executor.run_research_document(
            topic=params["topic"],
            browser=params.get("browser", self.config.get("default_browser", "brave")),
            document_app=params.get("document_app", "word"),
            result_count=int(params.get("result_count", 5)),
        )

    def ensure_browser(
        self,
        browser: Optional[str] = None,
        site: Optional[str] = None,
        private: bool = False,
    ) -> str:
        preferred_browser = self._resolve_browser_name(
            browser or self.memory.get_preference("preferred_browser", self.config.get("default_browser", "brave"))
        )
        snapshot = self.get_latest_vision_snapshot(refresh=True)

        if snapshot:
            if site:
                window = self._find_window_by_site(snapshot, site, preferred_browser)
                if window:
                    self.focus_window(window)
                    return f"Contexto reutilizado: {window}"
            browser_window = self._find_window_by_app(snapshot, preferred_browser)
            if browser_window:
                self.focus_window(browser_window)
                if site:
                    return self.ensure_site(site=site, browser=preferred_browser, private=private)
                return f"Navegador reutilizado: {browser_window}"

        return self.open_browser(preferred_browser or "brave", private=private)

    def ensure_site(
        self,
        site: str,
        browser: Optional[str] = None,
        private: bool = False,
    ) -> str:
        canonical_site = normalize_text(site)
        preferred_browser = self._resolve_browser_name(
            browser or self.memory.get_preference("preferred_browser", self.config.get("default_browser", "brave"))
        )
        snapshot = self.get_latest_vision_snapshot(refresh=True)

        if snapshot:
            active_match = snapshot.active_site and normalize_text(snapshot.active_site) == canonical_site
            if active_match and (not preferred_browser or snapshot.active_app == preferred_browser):
                return f"Sitio ya listo en la ventana activa: {snapshot.active_site}"

            window = self._find_window_by_site(snapshot, canonical_site, preferred_browser)
            if window:
                self.focus_window(window)
                return f"Sitio reutilizado: {window}"

        self.ensure_browser(browser=preferred_browser, private=private)
        url = self._site_to_url(canonical_site)
        if self._navigate_active_browser_to_url(url):
            return f"Sitio abierto en navegador existente: {canonical_site}"
        return self.open_url(url, browser_name=preferred_browser, private=private)

    def smart_site_search(
        self,
        destination: str,
        query: str,
        browser: Optional[str] = None,
        private: bool = False,
    ) -> str:
        return self.task_executor.run_search_flow(
            destination=destination,
            query=query,
            browser=browser,
            private=private,
        )

    def smart_spotify_play(self, query: str) -> str:
        snapshot = self.get_latest_vision_snapshot(refresh=True)
        spotify_window = self._find_window_by_app(snapshot, "spotify") if snapshot else None
        if spotify_window:
            self.focus_window(spotify_window)
            time.sleep(0.2)
            try:
                self.automation.hotkey("ctrl", "l")
                self.automation.write_text(query, use_clipboard=True)
                self.automation.press_keys(["enter"])
                result = f"Spotify reutilizado para buscar: {query}"
                self.history.record("smart_spotify_play", {"query": query, "result": result})
                self.emit_status(result, "info")
                return result
            except Exception:
                self.logger.exception("Fallo reutilizando Spotify; usando fallback")
        return self.open_spotify_search(query)

    def write_active_context(self, text: str) -> str:
        snapshot = self.get_latest_vision_snapshot(refresh=True)
        target_hints = ["youtube_search_bar", "google_search_bar", "google_results_search_bar", "document_body"]
        if snapshot and snapshot.active_app == "spotify":
            target_hints.insert(0, "spotify_search_bar")
        if self._write_into_active_hint(target_hints, text, press_enter=False):
            return f"Texto escrito en el contexto activo: {text}"
        return self.write_text(text, use_clipboard=True)

    def capture_research_summary(self, topic: str) -> str:
        def _capture() -> str:
            raw_text = self.task_executor.collect_page_text(max_scrolls_per_page=2)
            summary = self.task_planner.summarize_text(raw_text, max_sentences=5)
            if not summary:
                summary = (
                    f"- No se pudo extraer suficiente texto visible sobre {topic}.\n"
                    "- Revisa la pagina abierta y vuelve a pedir el resumen."
                )

            self._artifacts["last_research_topic"] = topic
            self._artifacts["last_summary"] = f"Resumen de {topic}\n\n{summary}"
            return f"Resumen local preparado para {topic}."

        return self._safe_automation_call(
            "capture_research_summary",
            {"topic": topic},
            _capture,
        )

    def create_document(
        self,
        application: str,
        title: str,
        content: Optional[str] = None,
        filename: Optional[str] = None,
        use_last_summary: bool = False,
    ) -> str:
        document_content = content or ""
        if use_last_summary:
            document_content = self._artifacts.get("last_summary", document_content)
        if not document_content.strip():
            document_content = f"{title}\n\nDocumento creado por Raphel."
        full_text = f"{title}\n\n{document_content}".strip()
        output_path = self.task_executor._build_document_path(title, application)
        if filename:
            output_dir = Path(self.config.get("document_output_dir"))
            output_path = output_dir / filename
        saved_path = self.task_executor.save_document(
            title=title,
            content=full_text,
            application=application,
            output_path=output_path,
        )
        return f"Documento preparado y guardado en: {saved_path}"

    def learning_status(self) -> str:
        autonomous_status = self.autonomous_learning_system.get_learning_status()
        return "\n\n".join(
            [
                self.learning.summarize(),
                self.learning_skill_engine.summarize_for_learning_status(),
                (
                    "Aprendizaje autonomo:\n"
                    f"- Objetivos completados: {len(autonomous_status.get('objectives_completed', []))}\n"
                    f"- Historial: {autonomous_status.get('learning_history_count', 0)}\n"
                    f"- Sesiones: {autonomous_status.get('total_sessions', 0)}\n"
                    f"- Horas: {autonomous_status.get('total_hours', 0.0):.2f}\n"
                    f"- Tasa media: {autonomous_status.get('average_success_rate', 0.0):.1%}"
                ),
            ]
        )

    def learn_skill(
        self,
        skill: str,
        goal: Optional[str] = None,
        attempts: Optional[int] = None,
        minutes: Optional[int] = None,
        create_document: bool = False,
    ) -> str:
        return self._safe_automation_call(
            "learn_skill",
            {
                "skill": skill,
                "goal": goal,
                "attempts": attempts,
                "minutes": minutes,
                "create_document": create_document,
            },
            lambda: self._learn_skill_with_possible_autonomous_upgrade(
                skill=skill,
                goal=goal,
                attempts=attempts,
                minutes=minutes,
                create_document=create_document,
            ),
        )

    def practice_skill(
        self,
        skill: str,
        goal: Optional[str] = None,
        attempts: Optional[int] = None,
        minutes: Optional[int] = None,
    ) -> str:
        return self._safe_automation_call(
            "practice_skill",
            {"skill": skill, "goal": goal, "attempts": attempts, "minutes": minutes},
            lambda: self.learning_skill_engine.practice_skill(
                requested_skill=skill,
                goal=goal,
                requested_attempts=attempts,
                requested_minutes=minutes,
            ),
        )

    def evaluate_skill(self, skill: str) -> str:
        return self._safe_automation_call(
            "evaluate_skill",
            {"skill": skill},
            lambda: self.learning_skill_engine.evaluate_skill(skill),
        )

    def use_skill(
        self,
        skill: str,
        goal: str,
        create_document: bool = False,
    ) -> str:
        return self._safe_automation_call(
            "use_skill",
            {"skill": skill, "goal": goal, "create_document": create_document},
            lambda: self.learning_skill_engine.use_skill(
                requested_skill=skill,
                goal=goal,
                create_document=create_document,
            ),
        )

    def skill_status(self, skill: Optional[str] = None) -> str:
        return self.learning_skill_engine.skill_status(skill)

    def bootstrap_skill_profiles(self) -> str:
        return self.learning_skill_engine.bootstrap_starter_profiles()

    def reevaluate_skill_levels(self) -> str:
        self.learning_skill_engine.reevaluate_all_profiles()
        lines = ["Reevaluacion exponencial 0-6 completada:"]
        for skill_id, profile in sorted(self.learning_skill_engine.state.get("profiles", {}).items()):
            lines.append(
                f"- {profile.get('display_name', skill_id)} :: legado {profile.get('current_level', 1)} "
                f"-> exp {profile.get('exponential_level', 0)}/6"
            )
        return "\n".join(lines)

    def autonomous_learn(self, objective: str, use_research: bool = True) -> str:
        result = self.autonomous_learning_system.learn(objective, use_research=use_research)
        return self._format_autonomous_learning_result(result)

    def autonomous_status(self) -> str:
        payload = self.autonomous_learning_system.get_learning_status()
        completed = payload.get("objectives_completed", [])
        return (
            "Estado autonomo:\n"
            f"- Objetivos completados: {len(completed)}\n"
            f"- Historial: {payload.get('learning_history_count', 0)}\n"
            f"- Sesiones: {payload.get('total_sessions', 0)}\n"
            f"- Horas: {payload.get('total_hours', 0.0):.2f}\n"
            f"- Tasa media: {payload.get('average_success_rate', 0.0):.1%}"
        )

    def _learn_skill_with_possible_autonomous_upgrade(
        self,
        skill: str,
        goal: Optional[str] = None,
        attempts: Optional[int] = None,
        minutes: Optional[int] = None,
        create_document: bool = False,
    ) -> str:
        objective = self._autonomous_learning_objective(skill, goal)
        if self._should_promote_learning_objective_to_autonomous(
            skill=skill,
            goal=goal,
            attempts=attempts,
            minutes=minutes,
        ):
            result = self.autonomous_learning_system.learn(objective, use_research=True)
            return self._format_autonomous_learning_result(result, promoted_from="learn_skill")
        return self.learning_skill_engine.learn_skill(
            requested_skill=skill,
            goal=goal,
            requested_attempts=attempts,
            requested_minutes=minutes,
            create_document=create_document,
        )

    def _should_promote_learning_objective_to_autonomous(
        self,
        skill: str,
        goal: Optional[str] = None,
        attempts: Optional[int] = None,
        minutes: Optional[int] = None,
    ) -> bool:
        if attempts is not None or minutes is not None:
            return False
        objective = self._autonomous_learning_objective(skill, goal)
        if not objective:
            return False
        resolver = getattr(self.learning_skill_engine, "_resolve_skill", None)
        if not callable(resolver):
            return False
        resolved = resolver(skill)
        if bool(resolved.get("supported")):
            return str(resolved.get("template_kind", "") or "") == "game_foundation"
        return True

    @staticmethod
    def _autonomous_learning_objective(skill: str, goal: Optional[str] = None) -> str:
        return str(goal or skill or "").strip()

    def _format_autonomous_learning_result(
        self,
        result: Dict[str, Any],
        promoted_from: str = "",
    ) -> str:
        report = str(result.get("final_report", "Aprendizaje autonomo ejecutado.")).strip()
        lines = [report]
        if promoted_from:
            lines.append(f"Ruta usada: {promoted_from} -> autonomous_learn")

        total_sessions = int(result.get("total_sessions", 0) or 0)
        verified_sessions = int(result.get("verified_sessions", 0) or 0)
        if total_sessions or verified_sessions:
            lines.append(f"Sesiones verificadas: {verified_sessions}/{total_sessions}")

        assets = int(result.get("knowledge_assets_collected", 0) or 0)
        bootstrap = result.get("research_bootstrap", {})
        if isinstance(bootstrap, dict) and (assets or bootstrap):
            fallback_used = "si" if bool(bootstrap.get("fallback_used")) else "no"
            topic_count = len(list(bootstrap.get("topics", []) or []))
            lines.append(
                f"Bootstrap de investigacion: assets={assets} | temas={topic_count} | fallback={fallback_used}"
            )

        curriculum = result.get("curriculum")
        progress = result.get("progress")
        total_phases = len(getattr(curriculum, "phases", []) or [])
        completed_phases = len(getattr(progress, "phases_completed", []) or [])
        if total_phases:
            lines.append(f"Fases completadas: {completed_phases}/{total_phases}")
        return "\n".join(lines)

    def start_input_training_loop(
        self,
        mouse_attempts: Optional[int] = None,
        keyboard_attempts: Optional[int] = None,
        pause_seconds: float = 2.0,
    ) -> str:
        mouse_budget = self._normalize_input_training_attempts(mouse_attempts, default=6)
        keyboard_budget = self._normalize_input_training_attempts(keyboard_attempts, default=mouse_budget)
        pause = max(0.5, min(float(pause_seconds), 60.0))
        self.infinite_training_loop.configure_budgets(
            mouse_attempts=mouse_budget,
            keyboard_attempts=keyboard_budget,
            pause_seconds=pause,
        )
        with self._input_training_lock:
            if self._input_training_thread and self._input_training_thread.is_alive():
                return self.input_training_status()
            self._input_training_stop_event.clear()
            self._clear_input_training_stop_flag()
            self._input_training_cycle_count = 0
            self._input_training_last_result = "iniciando"
            self._input_training_thread = threading.Thread(
                target=self._run_input_training_loop,
                args=(mouse_budget, keyboard_budget, pause),
                daemon=True,
                name="RaphelInputTrainingLoop",
            )
            self._input_training_thread.start()
        return (
            "Entrenamiento continuo autonomo iniciado. "
            "Se detiene con 'input-training-stop', 'para el entrenamiento continuo' "
            f"o {self.INPUT_TRAINING_STOP_HOTKEY_TEXT}."
        )

    def stop_input_training_loop(self) -> str:
        with self._input_training_lock:
            thread = self._input_training_thread
            running = bool(thread and thread.is_alive())
            self._input_training_stop_event.set()
            self._write_input_training_stop_flag()
        if running and thread:
            thread.join(timeout=1.5)
            if thread.is_alive():
                return (
                    "Detencion solicitada. Terminara al cerrar el ciclo actual del curriculum infinito."
                )
        return "Entrenamiento continuo autonomo detenido."

    def input_training_status(self) -> str:
        thread = self._input_training_thread
        running = bool(thread and thread.is_alive())
        state = "corriendo" if running else "detenido"
        return (
            f"Entrenamiento continuo autonomo: {state}. "
            f"Parada rapida: {self.INPUT_TRAINING_STOP_HOTKEY_TEXT}. "
            f"Ciclos completados: {self._input_training_cycle_count}. "
            f"Ultimo resultado: {self._input_training_last_result}"
        )

    def training_runtime_snapshot(self) -> Dict[str, Any]:
        thread = self._input_training_thread
        running = bool(thread and thread.is_alive())
        return {
            "running": running,
            "cycle_count": int(self._input_training_cycle_count),
            "last_result": str(self._input_training_last_result),
            "stop_hint": self.INPUT_TRAINING_STOP_HOTKEY_TEXT,
        }

    def start_remote_console(
        self,
        port: Optional[int] = None,
        expose_online: bool = False,
        token: Optional[str] = None,
    ) -> str:
        host = "0.0.0.0" if expose_online else "127.0.0.1"
        current = self.remote_console.status_payload()
        resolved_port = int(port or current.get("port") or 8765)
        try:
            payload = self.remote_console.start(host=host, port=resolved_port, token=token)
        except OSError as exc:
            return (
                f"No se pudo abrir la consola remota en {host}:{resolved_port}. "
                f"Detalle: {exc}. Si el puerto ya esta ocupado, prueba por ejemplo "
                f"'remote-console-online {resolved_port + 1}'."
            )
        return self._format_remote_console_status(
            payload,
            expose_online=expose_online,
            prefix="Consola remota iniciada.",
        )

    def reset_runtime(self) -> str:
        previous_remote = self.remote_console.status_payload()
        remote_running = bool(previous_remote.get("running"))
        remote_host = str(previous_remote.get("host") or "127.0.0.1")
        remote_port = int(previous_remote.get("port") or 8765)
        remote_token = str(previous_remote.get("token") or "") or None

        self.learning_skill_engine.state = self.learning_skill_engine._load_state()
        self.learning_skill_engine.reevaluate_all_profiles()

        remote_line = "Consola remota sin cambios: estaba detenida."
        if remote_running:
            try:
                payload = self.remote_console.start(
                    host=remote_host,
                    port=remote_port,
                    token=remote_token,
                )
                remote_line = (
                    "Consola remota preservada: "
                    f"{payload.get('primary_url') or payload.get('listen_url')}"
                )
            except OSError as exc:
                remote_line = f"Consola remota no se pudo reafirmar: {exc}"

        return "\n".join(
            [
                "Reset de runtime completado.",
                "- Estado de habilidades recargado desde disco y reevaluado.",
                f"- {remote_line}",
                "- Nota: esto reaplica estado y configuracion; cambios estructurales de codigo Python aun requieren reiniciar raphel.py.",
            ]
        )

    def stop_remote_console(self) -> str:
        payload = self.remote_console.stop()
        return self._format_remote_console_status(
            payload,
            expose_online=payload.get("host") == "0.0.0.0",
            prefix="Consola remota detenida.",
        )

    def remote_console_status(self) -> str:
        payload = self.remote_console.status_payload()
        return self._format_remote_console_status(
            payload,
            expose_online=payload.get("host") == "0.0.0.0",
            prefix="Estado de consola remota.",
        )

    def _format_remote_console_status(
        self,
        payload: Dict[str, Any],
        expose_online: bool,
        prefix: str,
    ) -> str:
        urls = [str(item) for item in payload.get("access_urls", []) if str(item).strip()]
        lines = [
            prefix,
            f"- Estado: {'activa' if payload.get('running') else 'detenida'}",
            f"- Bind: {payload.get('host', '127.0.0.1')}:{payload.get('port', 8765)}",
            f"- Token: {payload.get('token_hint', 'auto')}",
        ]
        if urls:
            lines.append("- URLs:")
            lines.extend(f"  * {url}" for url in urls[:6])
        if expose_online:
            lines.append(
                "- Nota: para acceso publico por Internet aun necesitas tunel o port forwarding; "
                "desde otra computadora en la misma red ya deberia servir."
            )
        return "\n".join(lines)

    def _run_input_training_loop(
        self,
        mouse_attempts: int,
        keyboard_attempts: int,
        pause_seconds: float,
    ) -> None:
        while not self._input_training_should_stop():
            self._input_training_cycle_count += 1
            cycle_number = self._input_training_cycle_count
            try:
                step_summaries: List[str] = []
                steps = self._build_input_training_cycle_steps(
                    cycle_number=cycle_number,
                    mouse_attempts=mouse_attempts,
                    keyboard_attempts=keyboard_attempts,
                )
                for label, runner in steps:
                    if self._input_training_should_stop():
                        break
                    self.emit_status(
                        f"Entrenamiento continuo ciclo {cycle_number}: entrenando {label}.",
                        "info",
                    )
                    step_results = self._run_input_training_step_with_retry(label, runner, cycle_number)
                    step_summaries.extend(step_results)
                    if step_results:
                        self._input_training_last_result = f"ciclo {cycle_number}: {step_results[-1]}"
                if not self._input_training_should_stop():
                    sync_result = self._sync_input_training_learning_profiles(cycle_number)
                    if sync_result:
                        step_summaries.append(f"sync={self._compact_training_result(sync_result)}")
                completed = len([item for item in step_summaries if "=" in item])
                tail = " | ".join(step_summaries[-3:]) if step_summaries else "sin pasos ejecutados"
                self._input_training_last_result = (
                    f"ciclo {cycle_number}: pase completo con {completed} resultado(s). {tail}"
                )
            except Exception as exc:
                if self._is_pyautogui_failsafe_error(exc):
                    self._input_training_last_result = (
                        f"ciclo {cycle_number}: detenido por fail-safe de mouse. "
                        "El puntero llego a una esquina o una ventana invalida intento moverlo alli."
                    )
                    self.logger.warning("Entrenamiento continuo detenido por fail-safe: %s", exc)
                else:
                    self._input_training_last_result = f"ciclo {cycle_number}: detenido por error: {exc}"
                    self.logger.exception("Entrenamiento continuo detenido por error")
                self._input_training_stop_event.set()
                self._write_input_training_stop_flag()
                break
            self._sleep_input_training_pause(pause_seconds)

    def _build_input_training_cycle_steps(
        self,
        cycle_number: int,
        mouse_attempts: int,
        keyboard_attempts: int,
    ) -> List[tuple[str, Callable[[], str]]]:
        rng = self._input_training_rng
        mouse_level = self._input_training_skill_level("skill:mouse")
        visual_level = self._input_training_skill_level("skill:visualizacion")
        keyboard_level = self._input_training_skill_level("skill:teclado")
        research_level = self._input_training_skill_level("skill:investigar")
        window_level = self._input_training_skill_level("skill:window_management")
        youtube_level = self._input_training_skill_level("skill:youtube")
        visual_scenario, visual_target_level = self._input_training_level_scenario(
            visual_level,
            [
                (1, "visual_context_identity", 0),
                (2, "visual_target_reacquire", 2),
                (3, "visual_scene_transition", 3),
                (4, "visual_workflow_precondition", 4),
                (5, "visual_adversarial_recovery", 5),
            ],
        )
        keyboard_scenario, keyboard_target_level = self._input_training_level_scenario(
            keyboard_level,
            [
                (1, "keyboard_text_entry", 0),
                (2, "keyboard_browser_address_focus", 2),
                (3, "keyboard_explorer_search", 2),
                (4, "keyboard_window_switch", 4),
                (5, "keyboard_multiapp_chain", 5),
            ],
        )
        research_scenario, research_target_level = self._input_training_level_scenario(
            research_level,
            [
                (1, "research_single_source", 0),
                (2, "research_multi_query", 2),
                (3, "research_structured_extract", 3),
                (4, "research_cross_verify", 4),
                (5, "research_autonomous_discovery", 5),
            ],
        )
        window_scenario, window_target_level = self._input_training_level_scenario(
            window_level,
            [
                (1, "explorer_window_layout_stable", 1),
                (2, "explorer_window_layout_repair", 2),
                (3, "explorer_window_occlusion_recovery", 3),
                (4, "explorer_window_occlusion_recovery", 3),
                (5, "explorer_window_occlusion_recovery", 3),
            ],
        )

        def forced_step(
            label: str,
            domain: str,
            skill_id: str,
            scenario_id: str,
            target_level: int,
            runner: str = "practice_skill",
            family: Optional[str] = None,
            base_scenario_id: Optional[str] = None,
            training_goal: Optional[str] = None,
        ) -> tuple[str, Callable[[], str]]:
            scenario: Dict[str, Any] = {
                "scenario_id": scenario_id,
                "runner": runner,
                "target_level": target_level,
            }
            if family:
                scenario["family"] = family
            if base_scenario_id:
                scenario["base_scenario_id"] = base_scenario_id
            if training_goal:
                scenario["training_goal"] = training_goal
            return (
                label,
                lambda domain=domain, scenario=scenario, skill_id=skill_id, label=label: (
                    self._run_input_training_forced_scenario(label, domain, scenario, skill_id)
                ),
            )

        steps: List[tuple[str, Callable[[], str]]] = [
            forced_step(
                "teclado",
                "keyboard",
                "skill:teclado",
                keyboard_scenario,
                keyboard_target_level,
                family="keyboard",
            ),
            forced_step(
                "acomodo de ventanas",
                "file_manager/explorer",
                "skill:window_management",
                window_scenario,
                window_target_level,
                family="file_manager",
            ),
            forced_step(
                "visualizacion",
                "perception",
                "skill:visualizacion",
                visual_scenario,
                visual_target_level,
                family="perception",
            ),
            forced_step(
                "investigar",
                "research",
                "skill:investigar",
                research_scenario,
                research_target_level,
                family="research",
            ),
            forced_step(
                "youtube",
                "browser",
                "skill:youtube",
                "browser_form_fill",
                max(3, youtube_level),
                family="browser",
                training_goal="buscar tutorial visible en youtube",
            ),
            forced_step(
                "interpretacion audiovisual youtube",
                "browser",
                "skill:youtube",
                "youtube_audio_visual_interpretation",
                max(3, youtube_level),
                family="browser",
                base_scenario_id="browser_form_fill",
                training_goal="tutorial basico con transcripcion o texto visible",
            ),
            (
                "mouse movimiento",
                lambda: self._run_input_training_forced_scenario(
                    "mouse movimiento",
                    "vision/detection",
                    {"scenario_id": "ui_detect_visible", "runner": "practice_mouse_movement", "target_level": 0},
                    "skill:mouse",
                ),
            ),
            (
                "mouse click",
                lambda: self._run_input_training_forced_scenario(
                    "mouse click",
                    "vision/detection",
                    {"scenario_id": "mouse_click_visible", "runner": "practice_mouse_click", "target_level": 1},
                    "skill:mouse",
                ),
            ),
            (
                "mouse doble click",
                lambda: self._run_input_training_forced_scenario(
                    "mouse doble click",
                    "vision/detection",
                    {"scenario_id": "mouse_click_reopened_window", "runner": "practice_mouse_double_click", "target_level": 1},
                    "skill:mouse",
                ),
            ),
            (
                "mouse click derecho",
                lambda: self._run_input_training_forced_scenario(
                    "mouse click derecho",
                    "vision/detection",
                    {"scenario_id": "mouse_right_click_visible", "runner": "practice_mouse_right_click", "target_level": 1},
                    "skill:mouse",
                ),
            ),
            (
                "mouse drag",
                lambda: self._run_input_training_forced_scenario(
                    "mouse drag",
                    "selection/workflow",
                    {
                        "scenario_id": "desktop_drag_constrained",
                        "runner": "practice_desktop_mouse",
                        "target_level": max(2, min(5, mouse_level)),
                    },
                    "skill:mouse",
                ),
            ),
            (
                "mouse flujo",
                lambda: self._run_input_training_forced_scenario(
                    "mouse flujo",
                    "selection/workflow",
                    {
                        "scenario_id": "desktop_drag_real_verify",
                        "runner": "practice_mouse_workflow",
                        "target_level": max(3, min(5, mouse_level)),
                    },
                    "skill:mouse",
                ),
            ),
        ]
        rng.shuffle(steps)
        return steps

    def _run_input_training_forced_scenario(
        self,
        label: str,
        domain: str,
        scenario: Dict[str, Any],
        skill_id: str,
    ) -> str:
        result = self.infinite_training_loop.run_one_cycle(
            preferred_domain=domain,
            forced_scenario=scenario,
            forced_skill_id=skill_id,
        )
        return self.infinite_training_loop.summarize_result(result)

    @staticmethod
    def _input_training_level_scenario(
        level: int,
        choices: List[tuple[int, str, int]],
    ) -> tuple[str, int]:
        safe_level = max(1, min(5, int(level or 1)))
        selected = choices[0]
        for candidate in choices:
            if safe_level >= candidate[0]:
                selected = candidate
        return selected[1], selected[2]

    def _run_input_training_step_with_retry(
        self,
        label: str,
        runner: Callable[[], str],
        cycle_number: int,
    ) -> List[str]:
        results: List[str] = []
        try:
            result = runner()
        except RuntimeError as exc:
            if self._is_input_training_step_unavailable_error(exc):
                result = self._format_input_training_step_unavailable(label, exc)
                self.emit_status(
                    f"Entrenamiento continuo ciclo {cycle_number}: {result}.",
                    "warning",
                )
                return [f"{label}={self._compact_training_result(result)}"]
            raise
        results.append(f"{label}={self._compact_training_result(result)}")
        retries = self._input_training_retry_limit(label)
        for retry_index in range(1, retries + 1):
            if self._input_training_should_stop() or not self._input_training_result_needs_retry(result):
                break
            self.emit_status(
                (
                    f"Entrenamiento continuo ciclo {cycle_number}: "
                    f"{label} fallo o quedo bajo; reintento {retry_index}/{retries}."
                ),
                "warning",
            )
            self._sleep_input_training_pause(0.35)
            try:
                result = runner()
            except RuntimeError as exc:
                if self._is_input_training_step_unavailable_error(exc):
                    result = self._format_input_training_step_unavailable(label, exc)
                    self.emit_status(
                        f"Entrenamiento continuo ciclo {cycle_number}: {result}.",
                        "warning",
                    )
                    results.append(
                        f"{label} reintento {retry_index}={self._compact_training_result(result)}"
                    )
                    break
                raise
            results.append(
                f"{label} reintento {retry_index}={self._compact_training_result(result)}"
            )
        return results

    @staticmethod
    def _is_input_training_step_unavailable_error(exc: Exception) -> bool:
        if not isinstance(exc, RuntimeError):
            return False
        normalized = normalize_text(str(exc))
        unavailable_tokens = (
            "no esta disponible ahora",
            "todas las habilidades del dominio estan bloqueadas",
            "no hay habilidades entrenables activas",
            "no tiene habilidades activas entrenables",
            "no esta activa para entrenar",
            "habilidad base de",
        )
        return any(token in normalized for token in unavailable_tokens)

    @staticmethod
    def _format_input_training_step_unavailable(label: str, exc: Exception) -> str:
        reason = str(exc).strip() or "habilidad no disponible"
        return f"{label} omitido: {reason}"

    def _sync_input_training_learning_profiles(self, cycle_number: int) -> str:
        self.emit_status(
            f"Entrenamiento continuo ciclo {cycle_number}: sincronizando niveles.",
            "info",
        )
        sync_results = [
            self.learning_skill_engine.sync_mouse_profile_from_desktop_practice(),
            self.learning_skill_engine.sync_visual_profile_from_desktop_practice(),
            self.learning_skill_engine.sync_window_management_profile_from_desktop_practice(),
        ]
        return "\n".join(str(item) for item in sync_results if str(item).strip())

    def _input_training_attempt_variant(
        self,
        base_attempts: int,
        level: int = 1,
        cycle_number: int = 1,
    ) -> int:
        base = max(1, int(base_attempts))
        safe_level = max(1, min(5, int(level or 1)))
        level_multiplier = 1.0 + ((safe_level - 1) * 0.22)
        cycle_multiplier = 1.0 + min(0.45, max(0, int(cycle_number) - 1) * 0.025)
        target = max(1, int(round(base * level_multiplier * cycle_multiplier)))
        spread = max(1, int(round(target * (0.22 + safe_level * 0.025))))
        return max(1, min(100, target + self._input_training_rng.randint(-spread, spread)))

    def _input_training_skill_level(self, skill_id: str) -> int:
        try:
            profiles = getattr(self.learning_skill_engine, "state", {}).get("profiles", {})
            profile = profiles.get(skill_id, {})
            return max(1, min(5, int(profile.get("current_level", 1))))
        except Exception:
            return 1

    def _input_training_retry_limit(self, label: str) -> int:
        normalized = normalize_text(label)
        if "teclado" in normalized:
            return 1
        if any(token in normalized for token in ("investigar", "youtube", "audiovisual")):
            return 1
        if any(token in normalized for token in ("ventana", "acomodo")):
            return 1
        if "visualizacion" in normalized:
            level = self._input_training_skill_level("skill:visualizacion")
            return 2 if level >= 4 and any(token in normalized for token in ("flujo", "seleccion", "deteccion")) else 1
        level = self._input_training_skill_level("skill:mouse")
        return 2 if level >= 4 and "drag" in normalized else 1

    @staticmethod
    def _input_training_result_needs_retry(result: str) -> bool:
        text = str(result or "")
        normalized = normalize_text(text)
        failure_match = re.search(r"fallos:\s*(\d+)", text, flags=re.IGNORECASE)
        if failure_match and int(failure_match.group(1)) > 0:
            return True
        rate_match = re.search(r"tasa:\s*(\d+(?:\.\d+)?)\s*%", text, flags=re.IGNORECASE)
        if rate_match and float(rate_match.group(1)) < 85.0:
            return True
        retry_tokens = (
            "aun necesita practica",
            "detenido por error",
            "no pude",
            "failed",
            "status=failure",
            "verified=no",
            "verificado=no",
            "retry",
        )
        return any(token in normalized for token in retry_tokens)

    def input_training_stop_requested(self) -> bool:
        if not self._input_training_loop_is_active():
            return False
        return self._input_training_should_stop()

    def _input_training_should_stop(self) -> bool:
        if self._input_training_stop_event.is_set() or self._input_training_stop_path.exists():
            return True
        if self._input_training_hotkey_stop_requested():
            self._request_input_training_stop_from_hotkey()
            return True
        return False

    def _input_training_loop_is_active(self) -> bool:
        thread = getattr(self, "_input_training_thread", None)
        return bool(thread and thread.is_alive())

    def _input_training_hotkey_stop_requested(self) -> bool:
        if not self._input_training_loop_is_active() or not hasattr(ctypes, "windll"):
            self._input_training_escape_started_at = None
            return False

        user32 = ctypes.windll.user32

        def pressed(vk_code: int) -> bool:
            return bool(user32.GetAsyncKeyState(vk_code) & 0x8000)

        vk_control = 0x11
        vk_menu = 0x12
        vk_pause = 0x13
        vk_escape = 0x1B
        vk_s = 0x53

        try:
            if pressed(vk_pause):
                return True
            if pressed(vk_control) and pressed(vk_menu) and pressed(vk_s):
                return True
            if pressed(vk_escape):
                now = time.monotonic()
                if self._input_training_escape_started_at is None:
                    self._input_training_escape_started_at = now
                    return False
                return (
                    now - self._input_training_escape_started_at
                    >= self._INPUT_TRAINING_ESCAPE_HOLD_SECONDS
                )
            self._input_training_escape_started_at = None
        except Exception:
            self._input_training_escape_started_at = None
        return False

    def _request_input_training_stop_from_hotkey(self) -> None:
        if not self._input_training_stop_event.is_set():
            self._input_training_last_result = (
                f"detenido por atajo de emergencia ({self.INPUT_TRAINING_STOP_HOTKEY_TEXT})"
            )
            self.emit_status(
                f"Entrenamiento continuo detenido por atajo de emergencia: "
                f"{self.INPUT_TRAINING_STOP_HOTKEY_TEXT}.",
                "warning",
            )
        self._input_training_stop_event.set()
        self._write_input_training_stop_flag()

    def _sleep_input_training_pause(self, pause_seconds: float) -> None:
        deadline = time.time() + pause_seconds
        while time.time() < deadline:
            if self._input_training_should_stop():
                return
            time.sleep(0.1)

    def _write_input_training_stop_flag(self) -> None:
        try:
            self._input_training_stop_path.parent.mkdir(parents=True, exist_ok=True)
            self._input_training_stop_path.write_text(
                datetime.now().isoformat(timespec="seconds"),
                encoding="utf-8",
            )
        except Exception:
            self.logger.exception("No se pudo escribir bandera de stop del entrenamiento continuo")

    def _clear_input_training_stop_flag(self) -> None:
        try:
            if self._input_training_stop_path.exists():
                self._input_training_stop_path.unlink()
        except Exception:
            self.logger.exception("No se pudo limpiar bandera de stop del entrenamiento continuo")

    @staticmethod
    def _normalize_input_training_attempts(value: Optional[int], default: int) -> int:
        if value is None:
            return max(1, min(int(default), 100))
        return max(1, min(int(value), 100))

    @staticmethod
    def _compact_training_result(result: str) -> str:
        first_line = str(result).strip().splitlines()[0] if str(result).strip() else "sin salida"
        return first_line[:160]

    @staticmethod
    def _is_pyautogui_failsafe_error(exc: Exception) -> bool:
        return (
            exc.__class__.__name__ == "FailSafeException"
            or "fail-safe" in str(exc).lower()
            or "failsafe" in str(exc).lower()
        )

    def list_desktop_icons(self) -> str:
        return self.desktop_trainer.list_icons_text()

    def arrange_desktop_icons(
        self,
        sort_by: str = "name",
        skip_confirmation: bool = False,
    ) -> str:
        if not skip_confirmation and not self.confirm_action(
            "Ordenar visualmente los iconos del escritorio puede cambiar su distribucion. Continuar?"
        ):
            return "Accion cancelada por seguridad."
        return self._safe_automation_call(
            "arrange_desktop_icons",
            {"sort_by": sort_by},
            lambda: self.desktop_trainer.arrange_icons(sort_by=sort_by),
        )

    def practice_desktop_mouse(
        self,
        attempts: Optional[int] = None,
        skip_confirmation: bool = False,
    ) -> str:
        if not skip_confirmation and not self.confirm_action(
            "Practicar mouse creara archivos temporales dentro de _Raphel_Practica_Mouse. Continuar?"
        ):
            return "Accion cancelada por seguridad."
        return self._safe_automation_call(
            "practice_desktop_mouse",
            {"attempts": attempts},
            lambda: self.desktop_learning_organizer.practice_mouse(attempts=attempts),
        )

    def practice_mouse_movement(
        self,
        attempts: Optional[int] = None,
        skip_confirmation: bool = False,
    ) -> str:
        if not skip_confirmation and not self.confirm_action(
            "Practicar movimiento movera el puntero a puntos seguros de la pantalla. Continuar?"
        ):
            return "Accion cancelada por seguridad."
        return self._safe_automation_call(
            "practice_mouse_movement",
            {"attempts": attempts},
            lambda: self.desktop_learning_organizer.practice_mouse_movement(attempts=attempts),
        )

    def practice_mouse_click(
        self,
        attempts: Optional[int] = None,
        skip_confirmation: bool = False,
    ) -> str:
        if not skip_confirmation and not self.confirm_action(
            "Practicar click simple movera el puntero y hara clicks en puntos seguros. Continuar?"
        ):
            return "Accion cancelada por seguridad."
        return self._safe_automation_call(
            "practice_mouse_click",
            {"attempts": attempts},
            lambda: self.desktop_learning_organizer.practice_mouse_click(attempts=attempts),
        )

    def practice_mouse_double_click(
        self,
        attempts: Optional[int] = None,
        skip_confirmation: bool = False,
    ) -> str:
        if not skip_confirmation and not self.confirm_action(
            "Practicar doble click movera el puntero y hara dobles clicks en puntos seguros. Continuar?"
        ):
            return "Accion cancelada por seguridad."
        return self._safe_automation_call(
            "practice_mouse_double_click",
            {"attempts": attempts},
            lambda: self.desktop_learning_organizer.practice_mouse_double_click(attempts=attempts),
        )

    def practice_mouse_right_click(
        self,
        attempts: Optional[int] = None,
        skip_confirmation: bool = False,
    ) -> str:
        if not skip_confirmation and not self.confirm_action(
            "Practicar click derecho abrira menus contextuales y los cerrara con Esc. Continuar?"
        ):
            return "Accion cancelada por seguridad."
        return self._safe_automation_call(
            "practice_mouse_right_click",
            {"attempts": attempts},
            lambda: self.desktop_learning_organizer.practice_mouse_right_click(attempts=attempts),
        )

    def practice_mouse_selection(
        self,
        attempts: Optional[int] = None,
        skip_confirmation: bool = False,
    ) -> str:
        if not skip_confirmation and not self.confirm_action(
            "Practicar seleccion visual creara archivos temporales y verificara seleccion azul. Continuar?"
        ):
            return "Accion cancelada por seguridad."
        return self._safe_automation_call(
            "practice_mouse_selection",
            {"attempts": attempts},
            lambda: self.desktop_learning_organizer.practice_mouse_selection(attempts=attempts),
        )

    def practice_mouse_detection(
        self,
        attempts: Optional[int] = None,
        skip_confirmation: bool = False,
    ) -> str:
        if not skip_confirmation and not self.confirm_action(
            "Practicar deteccion visual creara distractores temporales y verificara reencontrar el archivo correcto. Continuar?"
        ):
            return "Accion cancelada por seguridad."
        return self._safe_automation_call(
            "practice_mouse_detection",
            {"attempts": attempts},
            lambda: self.desktop_learning_organizer.practice_mouse_detection(attempts=attempts),
        )

    def practice_mouse_workflow(
        self,
        attempts: Optional[int] = None,
        skip_confirmation: bool = False,
    ) -> str:
        if not skip_confirmation and not self.confirm_action(
            "Practicar flujo completo usara archivos temporales y verificara movimientos seguros. Continuar?"
        ):
            return "Accion cancelada por seguridad."
        return self._safe_automation_call(
            "practice_mouse_workflow",
            {"attempts": attempts},
            lambda: self.desktop_learning_organizer.practice_mouse_workflow(attempts=attempts),
        )

    def train_desktop_icon(
        self,
        name: str,
        aliases: Optional[List[str]] = None,
        capture_size: Optional[tuple[int, int]] = None,
    ) -> str:
        return self._safe_automation_call(
            "train_desktop_icon",
            {
                "name": name,
                "aliases": aliases or [],
                "capture_size": list(capture_size) if capture_size else None,
            },
            lambda: self.desktop_trainer.learn_icon(
                name=name,
                aliases=aliases,
                capture_size=capture_size,
            ),
        )

    def click_desktop_icon(self, name: str, open_icon: bool = False) -> str:
        return self._safe_automation_call(
            "click_desktop_icon",
            {"name": name, "open_icon": open_icon},
            lambda: self.desktop_trainer.click_icon(name=name, open_icon=open_icon),
        )

    def organize_desktop(
        self,
        root_name: Optional[str] = None,
        move_shortcuts: Optional[bool] = None,
        move_folders: Optional[bool] = None,
        skip_confirmation: bool = False,
        execution_mode: Optional[str] = None,
    ) -> str:
        preview = self.desktop_trainer.preview_organization(
            root_name=root_name,
            move_shortcuts=move_shortcuts,
            move_folders=move_folders,
        )
        if not preview.operations:
            return "El escritorio ya esta limpio o no hay elementos configurados para mover."
        settings = self.config.get("desktop_organizer", {})
        resolved_mode = execution_mode or settings.get("execution_mode", "ui_learning")
        if resolved_mode in {"legacy_filesystem", "filesystem", "fast"} and not bool(
            settings.get("allow_legacy_filesystem_fallback", False)
        ):
            return (
                "El modo rapido por filesystem esta desactivado por seguridad. "
                "Activa desktop_organizer.allow_legacy_filesystem_fallback para usarlo."
            )

        require_confirmation = bool(settings.get("require_confirmation", True))
        if not skip_confirmation and require_confirmation:
            prompt = self.desktop_trainer.build_confirmation_prompt(preview)
            if not self.confirm_action(prompt):
                return "Accion cancelada por seguridad."

        if resolved_mode in {"legacy_filesystem", "filesystem", "fast"}:
            return self._safe_automation_call(
                "organize_desktop_legacy",
                {
                    "root_name": root_name,
                    "move_shortcuts": move_shortcuts,
                    "move_folders": move_folders,
                    "moves": len(preview.operations),
                },
                lambda: self.desktop_trainer.organize_desktop(
                    root_name=root_name,
                    move_shortcuts=move_shortcuts,
                    move_folders=move_folders,
                ),
            )

        return self._safe_automation_call(
            "organize_desktop_visible",
            {
                "root_name": root_name,
                "move_shortcuts": move_shortcuts,
                "move_folders": move_folders,
                "execution_mode": resolved_mode,
                "moves": len(preview.operations),
            },
            lambda: self.desktop_learning_organizer.organize(
                preview=preview,
                root_name=root_name,
                move_shortcuts=move_shortcuts,
                move_folders=move_folders,
            ),
        )

    def undo_last_desktop_organization(self, skip_confirmation: bool = False) -> str:
        if not skip_confirmation and not self.confirm_action(
            "Deshacer la ultima sesion visible de ordenado del escritorio. Continuar?"
        ):
            return "Accion cancelada por seguridad."
        return self._safe_automation_call(
            "desktop_undo_last",
            {},
            lambda: self.desktop_learning_organizer.undo_last_session(),
        )

    def open_application(self, target: str, extra_args: Optional[List[str]] = None) -> str:
        canonical = self._resolve_application_name(target)
        return self._safe_automation_call(
            "open_application",
            {"target": canonical, "extra_args": extra_args or []},
            lambda: self.automation.open_application(
                canonical,
                application_catalog=self.config.get("applications", {}),
                extra_args=extra_args,
            ),
        )

    def open_project(self, name: str, application: str = "visual studio code") -> str:
        resolved_path = self._resolve_project_path(name)
        canonical_app = self._resolve_application_name(application)
        return self._safe_automation_call(
            "open_project",
            {"name": name, "application": canonical_app, "path": resolved_path},
            lambda: self.automation.open_application(
                canonical_app,
                application_catalog=self.config.get("applications", {}),
                extra_args=[resolved_path],
            ),
        )

    def open_browser(self, browser: str, url: Optional[str] = None, private: bool = False) -> str:
        canonical = self._resolve_browser_name(browser)
        return self._safe_automation_call(
            "open_browser",
            {"browser": canonical, "url": url, "private": private},
            lambda: self.automation.open_browser(
                canonical,
                browser_paths=self.config.get("browser_paths", {}),
                url=url,
                private=private,
            ),
        )

    def open_url(
        self,
        url: str,
        browser_name: Optional[str] = None,
        private: bool = False,
    ) -> str:
        safe_url = self._normalize_url(url)
        canonical_browser = self._resolve_browser_name(browser_name) if browser_name else None
        return self._safe_automation_call(
            "open_url",
            {"url": safe_url, "browser": canonical_browser, "private": private},
            lambda: self.automation.open_url(
                safe_url,
                browser_name=canonical_browser,
                browser_paths=self.config.get("browser_paths", {}),
                private=private,
            ),
        )

    def open_folder(self, folder_name_or_path: str) -> str:
        resolved = self._resolve_folder_target(folder_name_or_path)
        return self._safe_automation_call(
            "open_folder",
            {"path": resolved},
            lambda: self.automation.open_folder(resolved),
        )

    def open_spotify_search(self, query: str) -> str:
        return self._safe_automation_call(
            "open_spotify_search",
            {"query": query},
            lambda: self.automation.open_spotify_search(
                query,
                self.config.get("spotify_search_url"),
            ),
        )

    def write_text(self, text: str, use_clipboard: bool = False) -> str:
        return self._safe_automation_call(
            "write_text",
            {"text": text, "use_clipboard": use_clipboard},
            lambda: self.automation.write_text(text, use_clipboard=use_clipboard),
        )

    def write_text_to_window(
        self,
        window_title: str,
        text: str,
        press_enter: bool = False,
        search_shortcut: Optional[str] = None,
    ) -> str:
        resolved_title = self._resolve_window_title(window_title)
        return self._safe_automation_call(
            "write_text_to_window",
            {
                "window_title": resolved_title,
                "text": text,
                "press_enter": press_enter,
                "search_shortcut": search_shortcut,
            },
            lambda: self.automation.write_text_to_window(
                resolved_title,
                text,
                press_enter=press_enter,
                search_shortcut=search_shortcut,
            ),
        )

    def click(self, x: int, y: int, button: str = "left") -> str:
        return self._safe_automation_call(
            "click",
            {"x": x, "y": y, "button": button},
            lambda: self.automation.click(x, y, button=button),
        )

    def move_mouse(self, x: int, y: int) -> str:
        return self._safe_automation_call(
            "move_mouse",
            {"x": x, "y": y},
            lambda: self.automation.move_mouse(x, y),
        )

    def drag_mouse(self, start_x: int, start_y: int, end_x: int, end_y: int) -> str:
        return self._safe_automation_call(
            "drag_mouse",
            {
                "start_x": start_x,
                "start_y": start_y,
                "end_x": end_x,
                "end_y": end_y,
            },
            lambda: self.automation.drag_mouse(start_x, start_y, end_x, end_y),
        )

    def press_keys(self, keys: List[str]) -> str:
        return self._safe_automation_call(
            "press_keys",
            {"keys": keys},
            lambda: self.automation.press_keys(keys),
        )

    def hotkey(self, *keys: str) -> str:
        return self._safe_automation_call(
            "hotkey",
            {"keys": list(keys)},
            lambda: self.automation.hotkey(*keys),
        )

    def click_image(
        self,
        template_path: str,
        confidence: float = 0.85,
        region: Optional[tuple] = None,
    ) -> str:
        match = self.vision.locate_image(template_path, confidence=confidence, region=region)
        if not match:
            return "No se encontro la imagen en pantalla."
        click_result = self.click(match.x, match.y)
        return (
            f"Imagen encontrada con confianza {match.confidence:.2f} en ({match.x}, {match.y}). "
            f"{click_result}"
        )

    def take_screenshot(self, save_path: Optional[str] = None) -> str:
        if not save_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = str(self.base_dir / "screenshots" / f"shot_{timestamp}.png")
        self.vision.capture_screen(save_path=save_path)
        self.history.record("screenshot", {"path": save_path})
        self.emit_status(f"Screenshot guardado en: {save_path}", "info")
        return f"Screenshot guardado en: {save_path}"

    def search_google(
        self,
        query: str,
        browser: Optional[str] = None,
        private: bool = False,
    ) -> str:
        canonical_browser = self._resolve_browser_name(browser) if browser else None
        return self._safe_automation_call(
            "search_google",
            {"query": query, "browser": canonical_browser, "private": private},
            lambda: self.automation.search_google(
                query,
                self.config.get("google_url"),
                browser_name=canonical_browser,
                browser_paths=self.config.get("browser_paths", {}),
                private=private,
            ),
        )

    def search_youtube(
        self,
        query: str,
        browser: Optional[str] = None,
        private: bool = False,
    ) -> str:
        canonical_browser = self._resolve_browser_name(browser) if browser else None
        return self._safe_automation_call(
            "search_youtube",
            {"query": query, "browser": canonical_browser, "private": private},
            lambda: self.automation.search_youtube(
                query,
                self.config.get("youtube_search_url"),
                browser_name=canonical_browser,
                browser_paths=self.config.get("browser_paths", {}),
                private=private,
            ),
        )

    def media_control(self, mode: str) -> str:
        return self._safe_automation_call(
            "media_control",
            {"mode": mode},
            lambda: self.automation.media_control(mode),
        )

    def adjust_volume(self, direction: str, steps: int = 5) -> str:
        return self._safe_automation_call(
            "adjust_volume",
            {"direction": direction, "steps": steps},
            lambda: self.automation.set_volume(direction, steps),
        )

    def set_volume_percent(self, percent: int) -> str:
        return self._safe_automation_call(
            "set_volume_percent",
            {"percent": percent},
            lambda: self.automation.set_volume_percent(percent),
        )

    def focus_window(self, title: str) -> str:
        resolved = self._resolve_window_title(title)
        return self._safe_automation_call(
            "focus_window",
            {"title": resolved},
            lambda: self.automation.focus_window(resolved),
        )

    def close_current_window(self, skip_confirmation: bool = False) -> str:
        if not skip_confirmation and not self.confirm_action(
            "Cerrar la ventana actual puede perder cambios no guardados. Continuar?"
        ):
            return "Accion cancelada por seguridad."
        return self._safe_automation_call(
            "close_current_window",
            {},
            lambda: self.automation.close_current_window(),
        )

    def close_window(self, title: str, skip_confirmation: bool = False) -> str:
        if not skip_confirmation and not self.confirm_action(
            f"Cerrar la ventana '{title}' puede perder cambios no guardados. Continuar?"
        ):
            return "Accion cancelada por seguridad."
        resolved = self._resolve_window_title(title)
        return self._safe_automation_call(
            "close_window",
            {"title": resolved},
            lambda: self.automation.close_window(resolved),
        )

    def minimize_all_windows(self) -> str:
        return self._safe_automation_call(
            "minimize_all_windows",
            {},
            lambda: self.automation.minimize_all_windows(),
        )

    def maximize_current_window(self) -> str:
        return self._safe_automation_call(
            "maximize_current_window",
            {},
            lambda: self.automation.maximize_current_window(),
        )

    def browser_tab(self, mode: str) -> str:
        return self._safe_automation_call(
            "browser_tab",
            {"mode": mode},
            lambda: self.automation.browser_tab(mode),
        )

    def extract_text(self) -> str:
        text = self.vision.extract_text()
        self.history.record("ocr", {"text": text})
        return text if text else "OCR sin texto detectable."

    def find_text(self, target_text: str) -> str:
        found = self.vision.find_text(target_text)
        self.history.record("find_text", {"target": target_text, "found": found})
        return f"Texto {'encontrado' if found else 'no encontrado'}: {target_text}"

    def pixel_color(self, x: int, y: int) -> str:
        rgb = self.vision.get_pixel_color(x, y)
        self.history.record("pixel_color", {"x": x, "y": y, "rgb": rgb})
        return f"Color en ({x}, {y}): {rgb}"

    def find_color(self, target_rgb: List[int], tolerance: int = 10) -> str:
        positions = self.vision.find_color(target_rgb, tolerance=tolerance)
        self.history.record(
            "find_color",
            {"target_rgb": target_rgb, "tolerance": tolerance, "matches": len(positions)},
        )
        if not positions:
            return f"No se encontro el color {target_rgb}."
        preview = ", ".join(str(position) for position in positions[:5])
        return f"Coincidencias detectadas: {len(positions)}. Primeras posiciones: {preview}"

    def add_reminder(self, seconds: int, message: str) -> str:
        reminder = self.reminders.add_in_seconds(message, seconds)
        self.history.record("add_reminder", reminder)
        return f"Recordatorio programado para {reminder['due_at']}: {message}"

    def read_recent_history(self, limit: int = 10) -> str:
        history_summary = self.memory.summarize_recent_memory(limit=limit)
        step_logs = self.memory.get_recent_step_logs(limit=min(8, limit))
        if not step_logs:
            return history_summary
        lines = [history_summary, "", "Pasos recientes:"]
        for item in step_logs:
            lines.append(
                f"- [{item['created_at']}] {item['task_intent']} :: {item['step_name']} :: {item['status']}"
            )
        return "\n".join(lines)

    def learn_new_skill(
        self,
        name: str,
        description: str,
        steps: List[Dict[str, Any]],
        triggers: Optional[List[str]] = None,
    ) -> Path:
        path = self.skill_manager.learn_new_skill(name, description, steps, triggers=triggers)
        self.history.record(
            "learn_new_skill",
            {
                "name": name,
                "description": description,
                "steps": steps,
                "triggers": triggers or [name],
                "path": str(path),
            },
        )
        return path

    def learn_from_feedback(
        self,
        user_command: str,
        correct_actions: List[Dict[str, Any] | CommandAction],
    ) -> str:
        feedback_path = self.command_parser.learn_from_feedback(user_command, correct_actions)
        self.history.record(
            "learn_from_feedback",
            {
                "user_command": user_command,
                "correct_actions": [
                    action if isinstance(action, dict) else action.__dict__
                    for action in correct_actions
                ],
                "path": str(feedback_path),
            },
        )
        return f"Feedback aprendido y guardado en: {feedback_path}"

    def run_shell(self, command: str, dangerous: bool = False) -> str:
        if dangerous or self.is_dangerous(command):
            if not self.confirm_action(f"Comando potencialmente peligroso: {command}. Continuar?"):
                return "Accion cancelada por seguridad."
        return self._safe_automation_call(
            "run_shell",
            {"command": command, "dangerous": dangerous},
            lambda: self.automation.run_shell(command, dangerous=False),
        )

    def _resolve_folder_target(self, folder_name_or_path: str) -> str:
        folders = self.config.get("frequent_folders", {})
        normalized_target = normalize_text(folder_name_or_path)
        for alias, folder_path in folders.items():
            if normalize_text(alias) == normalized_target:
                return folder_path
        for alias, folder_path in folders.items():
            if normalized_target in normalize_text(alias):
                return folder_path
        return folder_name_or_path

    @staticmethod
    def _split_named_aliases(raw_value: str) -> tuple[str, List[str]]:
        if "|" not in raw_value:
            return raw_value.strip(), []
        name, alias_block = raw_value.split("|", 1)
        aliases = [item.strip() for item in alias_block.split(",") if item.strip()]
        return name.strip(), aliases

    def _resolve_application_name(self, target: str) -> str:
        applications = self.config.get("applications", {})
        normalized_target = normalize_text(target)
        for app_name, data in applications.items():
            aliases = [app_name, *data.get("aliases", [])] if isinstance(data, dict) else [app_name]
            if any(normalized_target == normalize_text(alias) for alias in aliases):
                return app_name
        for app_name, data in applications.items():
            aliases = [app_name, *data.get("aliases", [])] if isinstance(data, dict) else [app_name]
            if any(normalized_target in normalize_text(alias) for alias in aliases):
                return app_name
        return target

    def _resolve_browser_name(self, browser: Optional[str]) -> Optional[str]:
        if not browser:
            return None
        normalized_target = normalize_text(browser)
        for app_name, data in self.config.get("applications", {}).items():
            aliases = [app_name, *data.get("aliases", [])] if isinstance(data, dict) else [app_name]
            if app_name in {"brave", "chrome", "edge", "firefox"}:
                if any(normalized_target == normalize_text(alias) for alias in aliases):
                    return app_name
        return browser

    def _resolve_window_title(self, title: str) -> str:
        aliases = self.config.get("window_aliases", {})
        normalized_target = normalize_text(title)
        for alias, real_title in aliases.items():
            if normalize_text(alias) == normalized_target:
                return real_title
        return title

    def _resolve_project_path(self, project_name: str) -> str:
        normalized_target = normalize_text(project_name)
        configured = self.config.get("project_aliases", {})
        for alias, path in configured.items():
            if normalize_text(alias) == normalized_target or normalized_target in normalize_text(alias):
                return path

        default_aliases = {
            normalize_text(self.base_dir.name): str(self.base_dir),
            "raphel": str(self.base_dir),
            "asistente": str(self.base_dir),
        }
        for alias, path in default_aliases.items():
            if normalized_target == alias or normalized_target in alias:
                return path

        parent = self.base_dir.parent
        sibling_matches: Dict[str, str] = {}
        for child in parent.iterdir():
            if child.is_dir():
                sibling_matches[normalize_text(child.name)] = str(child)
        for alias, path in sibling_matches.items():
            if normalized_target == alias or normalized_target in alias:
                return path

        raise FileNotFoundError(f"No se pudo resolver el proyecto '{project_name}'.")

    @staticmethod
    def _normalize_url(url: str) -> str:
        if url.startswith(("http://", "https://")):
            return url
        return f"https://{url}"

    def _site_to_url(self, site: str) -> str:
        aliases = self.config.get("url_aliases", {})
        return aliases.get(site, f"https://{site}")

    def _find_window_by_site(
        self,
        snapshot: VisionSnapshot,
        site: str,
        browser: Optional[str] = None,
    ) -> Optional[str]:
        normalized_site = normalize_text(site)
        preferred_browser = normalize_text(browser or "")
        for window in snapshot.windows:
            if browser and normalize_text(window.app_name or "") != preferred_browser:
                continue
            if normalize_text(window.site_hint or "") == normalized_site or normalized_site in normalize_text(window.title):
                return window.title
        return None

    def _find_window_by_app(self, snapshot: Optional[VisionSnapshot], app_name: Optional[str]) -> Optional[str]:
        if not snapshot or not app_name:
            return None
        normalized_app = normalize_text(app_name)
        for window in snapshot.windows:
            if normalize_text(window.app_name or "") == normalized_app:
                return window.title
        return None

    def _navigate_active_browser_to_url(self, url: str) -> bool:
        try:
            self.automation.hotkey("ctrl", "l")
            self.automation.write_text(url, use_clipboard=True)
            self.automation.press_keys(["enter"])
            self.history.record("navigate_active_browser", {"url": url})
            return True
        except Exception:
            self.logger.exception("No se pudo reutilizar la barra de direccion")
            return False

    def _write_into_active_hint(
        self,
        hint_names: List[str],
        text: str,
        press_enter: bool = False,
        select_all: bool = True,
    ) -> bool:
        snapshot = self.get_latest_vision_snapshot(refresh=True)
        if not snapshot:
            return False

        for hint_name in hint_names:
            element = self.vision.find_ui_element(hint_name, snapshot=snapshot)
            if not element:
                continue
            try:
                self.automation.move_mouse(element.x, element.y, duration=0.22)
                self.automation.click(element.x, element.y, duration=0.06)
                time.sleep(0.1)
                if select_all:
                    self.automation.hotkey("ctrl", "a")
                self.automation.write_text(text, use_clipboard=True)
                if press_enter:
                    self.automation.press_keys(["enter"])
                self.history.record(
                    "write_into_active_hint",
                    {"hint": hint_name, "text": text, "press_enter": press_enter},
                )
                return True
            except Exception:
                self.logger.exception("Fallo escribiendo con hint %s", hint_name)
        return False

    def _save_document_backup(self, filename: str, content: str) -> str:
        output_dir = Path(self.config.get("document_output_dir", str(Path.home() / "Documents" / "Raphel")))
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / filename
        path.write_text(content, encoding="utf-8")
        return str(path)

    def _remember_interaction(self, raw_command: str, response: str, success: bool) -> None:
        context = self.get_context_payload()
        try:
            self.memory.learn_from_interaction(
                raw_command,
                self._current_action_trace,
                response,
                context=context,
                success=success,
            )
        except Exception:
            self.logger.exception("No se pudo guardar memoria de la interaccion")
        try:
            self.learning.record_command_result(
                command=raw_command,
                actions_taken=self._current_action_trace,
                result=response,
                success=success,
                context=context,
            )
        except Exception:
            self.logger.exception("No se pudo actualizar aprendizaje inteligente")

    @staticmethod
    def _format_context_message(snapshot: VisionSnapshot) -> str:
        return (
            f"Contexto activo -> ventana: {snapshot.active_window or 'ninguna'} | "
            f"app: {snapshot.active_app or 'desconocida'} | sitio: {snapshot.active_site or 'desconocido'}"
        )

    def _safe_automation_call(
        self,
        action_name: str,
        payload: Dict[str, Any],
        callback: Callable[[], str],
    ) -> str:
        self.emit_status(f"Accion: {action_name}", "info")
        try:
            result = callback()
            self.history.record(action_name, {"payload": payload, "result": result})
            self.learning.record_action_result(
                action=action_name,
                params=payload,
                result=result,
                success=not str(result).lower().startswith("error"),
                context=self.get_context_payload(),
            )
            self.emit_status(result, "info")
            return result
        except (AutomationDependencyError, VisionDependencyError) as exc:
            self.learning.record_action_result(
                action=action_name,
                params=payload,
                result=str(exc),
                success=False,
                context=self.get_context_payload(),
            )
            raise RuntimeError(f"Dependencia faltante: {exc}") from exc
        except Exception as exc:
            self.learning.record_action_result(
                action=action_name,
                params=payload,
                result=str(exc),
                success=False,
                context=self.get_context_payload(),
            )
            raise
