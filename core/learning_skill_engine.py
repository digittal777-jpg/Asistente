from __future__ import annotations

import json
import random
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from core.data_paths import DataPaths
from core.history_store import TrainingHistoryStore
from core.logging_utils import ensure_directory
from core.organizer_store import OrganizerSessionStore
from core.profile_store import ProfileStore
from core.session_store import LearningSessionStore
from core.skill_family_mapping import create_trainable_draft
from core.skills import normalize_text
from core.task_executor import TaskExecutor
from core.training_domain_runners import create_default_training_domain_runners
from core.training_models import TrainingScenarioResult
from core.verification_desktop_first import DesktopFirstVerifier
from core.verification_research import ResearchVerifier
from core.verification_visual import VisualPerceptionVerifier


class LearningSkillEngine:
    """Motor general para habilidades aprendibles con niveles, gates y sesiones."""

    PROFILE_SCHEMA_VERSION = 3
    VERIFICATION_VERSION = 3
    HISTORY_REBUILD_VERSION = 4
    MAX_SKILL_LEVEL = 5
    MODAL_TOKENS = (
        "guardar como",
        "save as",
        "quieres guardar los cambios",
        "do you want to save your changes",
        "open file",
        "abrir archivo",
    )
    BROWSER_LEAVE_SITE_TOKENS = (
        "quieres salir del sitio web",
        "salir del sitio web",
        "do you want to leave this site",
        "leave site",
        "changes you made may not be saved",
        "es posible que los cambios no se guarden",
        "los cambios no se guarden",
    )
    BROWSER_APPS = {"brave", "chrome", "edge", "firefox"}
    DOCUMENT_APPS = {"word", "libreoffice writer", "notepad"}
    FILE_MANAGER_APPS = {"explorer"}
    GAME_SKILL_KEYWORDS = (
        "jugar",
        "juego",
        "partida",
        "terraria",
        "terarria",
        "minecraft",
        "videojuego",
        "videogame",
    )
    GAME_ALIASES: Dict[str, Tuple[str, ...]] = {
        "terraria": ("terraria", "terarria"),
        "minecraft": ("minecraft",),
    }
    KEYBOARD_LEVEL3_GOALS: Tuple[str, ...] = (
        "nota rapida de practica",
        "linea corta para verificar foco",
        "registro visible de teclado",
        "texto editable de control",
        "frase segura con numeros",
        "prueba de reemplazo en bloc",
    )
    KEYBOARD_HISTORY_SCENARIO_LEVELS: Dict[str, int] = {
        "document_write_basic": 1,
        "keyboard_text_entry": 1,
        "browser_open_google": 2,
        "browser_search_result": 2,
        "keyboard_browser_address_focus": 2,
        "keyboard_explorer_open": 2,
        "keyboard_explorer_search": 2,
        "document_replace_text": 3,
        "document_save_verified": 3,
        "explorer_move_verified": 3,
        "keyboard_window_switch": 4,
        "keyboard_window_focus": 4,
        "keyboard_window_close": 4,
        "keyboard_minimize_all": 4,
        "keyboard_maximize_window": 4,
        "keyboard_multiapp_chain": 5,
    }
    RESEARCH_HISTORY_SCENARIO_LEVELS: Dict[str, int] = {
        "research_single_source": 1,
        "research_multi_query": 2,
        "research_structured_extract": 3,
        "research_discard_poor": 3,
        "research_to_document": 4,
        "research_cross_verify": 4,
        "research_adversarial_recovery": 5,
        "research_autonomous_discovery": 5,
    }
    VISUAL_HISTORY_SCENARIO_LEVELS: Dict[str, int] = {
        "visual_context_identity": 1,
        "visual_target_reacquire": 2,
        "visual_scene_transition": 3,
        "visual_workflow_precondition": 4,
        "visual_adversarial_recovery": 5,
    }
    RESEARCH_RECOVERABLE_FAILURES: Tuple[str, ...] = (
        "visible_google_results",
        "page_text_quality",
        "page_poor_quality",
        "stuck_on_google",
        "wrong_active_window",
        "opened_result_but_empty",
        "ocr_unavailable",
        "back_navigation_failed",
        "modal_detected",
        "file_dialog_detected",
    )
    RESEARCH_TOPIC_LIBRARY: Tuple[str, ...] = (
        "automatizacion de escritorio",
        "atajos de teclado en windows",
        "gestion de archivos",
        "ocr para documentos",
        "seguridad de contrasenas",
        "copias de seguridad locales",
        "navegacion eficiente en brave",
        "organizacion del escritorio",
        "python listas y diccionarios",
        "diagnostico de red basico",
        "historia de la computacion",
        "energia solar residencial",
        "mejores practicas de productividad",
        "terraria crafting early game",
        "minecraft redstone basico",
        "resolucion de errores comunes en windows",
    )
    RESEARCH_DICTIONARY_ALLOWLIST: Tuple[str, ...] = (
        "guia",
        "resumen",
        "explicacion",
        "historia",
        "conceptos",
        "fundamentos",
        "tecnicas",
        "analisis",
        "comparacion",
        "contexto",
        "manual",
        "ejemplos",
        "documentacion",
        "errores",
        "pasos",
        "practico",
    )
    RESEARCH_FALLBACK_MODIFIERS: Tuple[str, ...] = (
        "guia",
        "resumen tecnico",
        "explicacion practica",
        "conceptos clave",
        "paso a paso",
        "errores comunes",
        "comparativa",
        "ejemplos practicos",
        "documentacion",
        "mejores practicas",
    )
    RESEARCH_TOPIC_CATEGORY_BONUS: Dict[str, float] = {
        "desktop": 3.5,
        "documents": 3.0,
        "browser": 2.5,
        "games": 1.5,
        "general": 1.0,
        "coding": -1.0,
    }
    RESEARCH_CODING_TOKENS: Tuple[str, ...] = (
        "python",
        "codigo",
        "programacion",
        "script",
        "json",
        "api",
    )

    SUPPORTED_SKILLS: Dict[str, Dict[str, Any]] = {
        "teclado": {
            "display_name": "Usar teclado",
            "family": "motor_ui",
            "template_kind": "keyboard",
            "aliases": (
                "teclado",
                "usar teclado",
                "uso de teclado",
                "escribir con teclado",
                "keyboard",
            ),
        },
        "youtube": {
            "display_name": "Usar YouTube",
            "family": "ui_workflow",
            "template_kind": "site_workflow",
            "aliases": (
                "youtube",
                "usar youtube",
                "uso de youtube",
                "buscar en youtube",
                "interpretar youtube",
                "interpretar videos",
                "interpretacion de video",
                "interpretacion visual",
                "interpretacion audiovisual",
                "intepretacion audiovisual",
                "interpretacion de sonido",
                "intepretacion de sonido",
                "interpretacion de sonido y visual",
                "intepretacion de sonido y visual",
                "interpretacion visual y sonido",
                "sonido y visual",
            ),
        },
        "investigar": {
            "display_name": "Investigar",
            "family": "cognitive_workflow",
            "template_kind": "research_workflow",
            "aliases": (
                "investigar",
                "investigacion",
                "investigación",
                "hacer investigacion",
                "hacer investigación",
                "research",
            ),
        },
        "visualizacion": {
            "display_name": "Visualizacion",
            "family": "visual_perception",
            "template_kind": "visual_perception",
            "aliases": (
                "visualizacion",
                "vista de contexto",
                "contexto visual",
                "aprende visualizacion",
                "entrena visualizacion",
            ),
        },
        "mouse": {
            "display_name": "Usar ratón",
            "family": "motor_ui",
            "template_kind": "mouse_control",
            "aliases": (
                "mouse",
                "usar mouse",
                "usar el mouse",
                "control de mouse",
                "manejo del mouse",
                "ratón",
                "usar ratón",
                "usar el ratón",
            ),
        },
        "window_management": {
            "display_name": "Administrar ventanas",
            "family": "ui_workflow",
            "template_kind": "window_management",
            "aliases": (
                "window management",
                "administrar ventanas",
                "manejo de ventanas",
                "acomodo de ventanas",
                "acomodar ventanas",
                "uso inteligente de ventanas",
                "organizar ventanas",
                "explorer lado a lado",
                "ventanas windows",
            ),
        },
    }
    STARTER_BOOTSTRAP_TARGETS: Tuple[str, ...] = (
        "visualizacion",
        "youtube",
        "interpretacion de sonido y visual",
        "investigar",
        "window_management",
        "brave",
        "explorer",
        "notepad",
        "mouse",
        "teclado",
        "jugar terraria",
    )
    MOUSE_TRAINING_STEPS: Dict[int, Tuple[Tuple[str, str, str], ...]] = {
        1: (
            ("movement", "practice_mouse_movement", "movimiento basico"),
            ("click", "practice_mouse_click", "click simple"),
            ("double_click", "practice_mouse_double_click", "doble click"),
            ("right_click", "practice_mouse_right_click", "click derecho"),
        ),
        2: (
            ("drag", "practice_mouse", "drag seguro"),
            ("movement", "practice_mouse_movement", "movimiento preciso"),
            ("click", "practice_mouse_click", "click estable"),
        ),
        3: (
            ("drag", "practice_mouse", "drag seguro"),
            ("click", "practice_mouse_click", "click sostenido"),
            ("double_click", "practice_mouse_double_click", "doble click sostenido"),
        ),
        4: (
            ("drag", "practice_mouse", "drag seguro avanzado"),
            ("movement", "practice_mouse_movement", "movimiento preciso avanzado"),
            ("right_click", "practice_mouse_right_click", "click derecho avanzado"),
        ),
        5: (
            ("drag", "practice_mouse", "drag nocturno"),
            ("click", "practice_mouse_click", "click preciso nocturno"),
            ("double_click", "practice_mouse_double_click", "doble click nocturno"),
            ("right_click", "practice_mouse_right_click", "click derecho nocturno"),
            ("movement", "practice_mouse_movement", "movimiento nocturno"),
        ),
    }
    MOUSE_PROFILE_SYNC_STEPS: Tuple[Tuple[str, int, str], ...] = (
        ("movement", 1, "movimiento basico"),
        ("click", 1, "click simple"),
        ("double_click", 1, "doble click"),
        ("right_click", 1, "click derecho"),
        ("drag", 2, "drag seguro"),
    )
    VISUAL_PROFILE_SYNC_STEPS: Tuple[Tuple[str, int, str, str], ...] = (
        ("detection", 2, "deteccion visual", "visual_target_reacquire"),
        ("selection", 4, "seleccion visual", "visual_workflow_precondition"),
        ("workflow", 5, "flujo completo seguro", "visual_adversarial_recovery"),
    )
    WINDOW_MANAGEMENT_LEVEL_RUNS: Dict[int, int] = {
        1: 1,
        2: 2,
        3: 2,
        4: 3,
        5: 3,
    }

    def __init__(
        self,
        base_dir: Path,
        config: Any,
        memory: Any,
        learning: Any,
        automation: Any,
        task_executor: Any,
        mouse_controller: Any,
        assistant: Any,
        logger: Optional[Any] = None,
        progress_callback: Optional[Callable[[str, str], None]] = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.config = config
        self.memory = memory
        self.learning = learning
        self.automation = automation
        self.task_executor = task_executor
        self.mouse = mouse_controller
        self.assistant = assistant
        self.logger = logger
        self.progress_callback = progress_callback
        self.sleep = sleeper
        self._research_dictionary_terms_cache: Optional[List[str]] = None

        self.paths = DataPaths.from_base_dir(self.base_dir)
        self.paths.ensure_base_structure()
        self.profile_store = ProfileStore(self.paths, logger=self.logger)
        self.session_store = LearningSessionStore(self.paths, logger=self.logger)
        self.history_store = TrainingHistoryStore(self.paths, logger=self.logger)
        self.organizer_store = OrganizerSessionStore(self.paths, logger=self.logger)
        self.profiles_path = self.profile_store.path
        self.sessions_dir = self.session_store.sessions_dir
        self.training_results_path = self.history_store.training_results_path
        self.domain_runners = create_default_training_domain_runners()
        self.desktop_verifier = DesktopFirstVerifier()
        self.research_verifier = ResearchVerifier()
        self.visual_verifier = VisualPerceptionVerifier()
        self.state = self._load_state()
        rebuilt = self._reconcile_profiles_from_history()
        reevaluated = self.reevaluate_all_profiles()
        if rebuilt and not reevaluated:
            self._save_state()

    def learn_skill(
        self,
        requested_skill: str,
        goal: Optional[str] = None,
        requested_attempts: Optional[int] = None,
        requested_minutes: Optional[int] = None,
        create_document: bool = False,
    ) -> str:
        return self._run_session(
            mode="learn",
            requested_skill=requested_skill,
            goal=goal,
            requested_attempts=requested_attempts,
            requested_minutes=requested_minutes,
            create_document=create_document,
        )

    def practice_skill(
        self,
        requested_skill: str,
        goal: Optional[str] = None,
        requested_attempts: Optional[int] = None,
        requested_minutes: Optional[int] = None,
    ) -> str:
        return self._run_session(
            mode="practice",
            requested_skill=requested_skill,
            goal=goal,
            requested_attempts=requested_attempts,
            requested_minutes=requested_minutes,
        )

    def evaluate_skill(self, requested_skill: str) -> str:
        return self._run_session(
            mode="evaluate",
            requested_skill=requested_skill,
        )

    def use_skill(
        self,
        requested_skill: str,
        goal: str,
        create_document: bool = False,
    ) -> str:
        return self._run_session(
            mode="use",
            requested_skill=requested_skill,
            goal=goal,
            create_document=create_document,
        )

    def sync_mouse_profile_from_desktop_practice(self) -> str:
        profile = self._ensure_profile(
            skill_id="skill:mouse",
            display_name=self.SUPPORTED_SKILLS["mouse"]["display_name"],
            family=self.SUPPORTED_SKILLS["mouse"]["family"],
            supported=True,
            template_kind="mouse_control",
            canonical_entity="mouse",
        )
        strategy = self._read_mouse_strategy()
        synced_sessions = profile.setdefault("input_training_synced_mouse_sessions", [])
        if not isinstance(synced_sessions, list):
            synced_sessions = []
            profile["input_training_synced_mouse_sessions"] = synced_sessions
        synced_set = {str(item) for item in synced_sessions}

        imported: List[Dict[str, Any]] = []
        for metric_key, default_level, label in self.MOUSE_PROFILE_SYNC_STEPS:
            metric = self._mouse_practice_metric(strategy, metric_key)
            if not metric:
                continue
            level = self._mouse_sync_level_for(metric_key, default_level, profile)
            session_id = str(metric.get("session_id") or "").strip()
            if not session_id:
                session_id = (
                    f"{metric_key}:{metric.get('attempts', 0)}:"
                    f"{metric.get('successes', 0)}:{metric.get('failures', 0)}"
                )
            sync_id = f"level{level}:{metric_key}:{session_id}"
            legacy_sync_id = f"{metric_key}:{session_id}"
            session_already_synced = any(
                existing == legacy_sync_id
                or existing.endswith(f":{metric_key}:{session_id}")
                for existing in synced_set
            )
            if sync_id in synced_set or session_already_synced:
                continue

            successes = int(metric.get("successes", 0))
            failures = int(metric.get("failures", 0))
            attempts = int(metric.get("attempts", successes + failures) or successes + failures)
            workflow_successes = successes if metric.get("workflow_success") else 0
            cycle = self._empty_cycle(
                cycle_number=len(synced_set) + len(imported) + 1,
                level=level,
                requested_attempts=attempts,
                requested_minutes=None,
            )
            cycle.update(
                {
                    "status": "completed" if successes else "retry",
                    "successes": successes,
                    "failures": failures,
                    "verified_successes": successes,
                    "workflow_successes": workflow_successes,
                    "summary": (
                        f"Mouse nivel {level}: sincronizado desde entrenamiento continuo "
                        f"{label} ({successes}/{max(1, successes + failures)} ok)."
                    ),
                    "steps": [
                        {
                            "skill": metric_key,
                            "source": "desktop_mouse_strategy",
                            "session_id": session_id,
                            "attempts": attempts,
                            "successes": successes,
                            "failures": failures,
                            "success_rate": metric.get("success_rate", 0.0),
                            "reliable": bool(metric.get("reliable")),
                        }
                    ],
                    "strategies_tried": [f"sync:{metric_key}"],
                    "verifications": [session_id],
                }
            )
            self._accumulate_metrics(profile, level, cycle)
            synced_sessions.append(sync_id)
            imported.append(
                {
                    "metric": metric_key,
                    "label": label,
                    "level": level,
                    "session_id": session_id,
                    "successes": successes,
                    "failures": failures,
                }
            )

        if not imported:
            self._refresh_mouse_profile_from_strategy(profile)
            latest_session_id = self._latest_mouse_practice_session_id(strategy)
            if latest_session_id:
                profile["last_session_id"] = latest_session_id
            profile["updated_at"] = self._now()
            self.state.setdefault("profiles", {})["skill:mouse"] = profile
            self._save_state()
            return "Perfil mouse: sin sesiones nuevas para sincronizar."

        promoted = self._apply_promotions(profile)
        self._finalize_profile_state(
            profile,
            meaningful_success=any(item["successes"] > 0 for item in imported),
        )
        profile["last_input_training_sync"] = {
            "updated_at": self._now(),
            "imported_count": len(imported),
            "imported": imported[-10:],
            "promoted": promoted,
            "current_level": profile.get("current_level", 1),
        }
        profile["last_session_id"] = str(imported[-1]["session_id"])
        self.state.setdefault("profiles", {})["skill:mouse"] = profile
        self._save_state()
        total_successes = sum(item["successes"] for item in imported)
        total_failures = sum(item["failures"] for item in imported)
        promotion_text = " con promocion" if promoted else ""
        return (
            f"Perfil mouse sincronizado{promotion_text}: {len(imported)} sesion(es), "
            f"{total_successes} exitos + {total_failures} fallos. "
            f"Nivel actual: {profile.get('current_level', 1)}."
        )

    def sync_visual_profile_from_desktop_practice(self) -> str:
        profile = self._ensure_profile(
            skill_id="skill:visualizacion",
            display_name=self.SUPPORTED_SKILLS["visualizacion"]["display_name"],
            family=self.SUPPORTED_SKILLS["visualizacion"]["family"],
            supported=True,
            template_kind="visual_perception",
            canonical_entity="visualizacion",
        )
        strategy = self._read_mouse_strategy()
        synced_sessions = profile.setdefault("input_training_synced_visual_sessions", [])
        if not isinstance(synced_sessions, list):
            synced_sessions = []
            profile["input_training_synced_visual_sessions"] = synced_sessions
        synced_set = {str(item) for item in synced_sessions}

        imported: List[Dict[str, Any]] = []
        for metric_key, default_level, label, scenario_id in self.VISUAL_PROFILE_SYNC_STEPS:
            metric = self._mouse_practice_metric(strategy, metric_key)
            if not metric:
                continue
            level = self._visual_sync_level_for(metric_key, default_level, profile)
            session_id = str(metric.get("session_id") or "").strip()
            if not session_id:
                session_id = (
                    f"{metric_key}:{metric.get('attempts', 0)}:"
                    f"{metric.get('successes', 0)}:{metric.get('failures', 0)}"
                )
            sync_id = f"level{level}:{metric_key}:{session_id}"
            if sync_id in synced_set:
                continue

            successes = int(metric.get("successes", 0))
            failures = int(metric.get("failures", 0))
            attempts = int(metric.get("attempts", successes + failures) or successes + failures)
            cycle = self._empty_cycle(
                cycle_number=len(synced_set) + len(imported) + 1,
                level=level,
                requested_attempts=attempts,
                requested_minutes=None,
            )
            cycle.update(
                {
                    "status": "completed" if successes else "retry",
                    "successes": successes,
                    "failures": failures,
                    "verified_successes": successes,
                    "workflow_successes": successes if level >= 4 else 0,
                    "summary": (
                        f"Visualizacion nivel {level}: sincronizada desde entrenamiento continuo "
                        f"{label} ({successes}/{max(1, successes + failures)} ok)."
                    ),
                    "steps": [
                        {
                            "step": scenario_id,
                            "scenario_id": scenario_id,
                            "skill": metric_key,
                            "source": "desktop_mouse_strategy",
                            "session_id": session_id,
                            "attempts": attempts,
                            "successes": successes,
                            "failures": failures,
                            "success_rate": metric.get("success_rate", 0.0),
                            "reliable": bool(metric.get("reliable")),
                            "verification": scenario_id,
                            "success": bool(successes > 0),
                            "evidence": {
                                "base_scenario_id": scenario_id,
                                "practice_metric": metric_key,
                                "verification_source": "desktop_mouse_strategy",
                                "confidence": float(metric.get("success_rate", 0.0) or 0.0),
                            },
                        }
                    ],
                    "strategies_tried": [f"sync:{metric_key}"],
                    "verifications": [session_id],
                }
            )
            self._accumulate_metrics(profile, level, cycle)
            synced_sessions.append(sync_id)
            imported.append(
                {
                    "metric": metric_key,
                    "label": label,
                    "scenario_id": scenario_id,
                    "level": level,
                    "session_id": session_id,
                    "successes": successes,
                    "failures": failures,
                }
            )

        if not imported:
            profile["updated_at"] = self._now()
            latest_session_id = self._latest_visual_practice_session_id(strategy)
            if latest_session_id:
                profile["last_session_id"] = latest_session_id
            self.state.setdefault("profiles", {})["skill:visualizacion"] = profile
            self._save_state()
            return "Perfil visualizacion: sin sesiones nuevas para sincronizar."

        promoted = self._apply_promotions(profile)
        self._finalize_profile_state(
            profile,
            meaningful_success=any(item["successes"] > 0 for item in imported),
        )
        profile["last_input_training_sync"] = {
            "updated_at": self._now(),
            "imported_count": len(imported),
            "imported": imported[-10:],
            "promoted": promoted,
            "current_level": profile.get("current_level", 1),
        }
        profile["last_session_id"] = str(imported[-1]["session_id"])
        self.state.setdefault("profiles", {})["skill:visualizacion"] = profile
        self._save_state()
        total_successes = sum(item["successes"] for item in imported)
        total_failures = sum(item["failures"] for item in imported)
        promotion_text = " con promocion" if promoted else ""
        return (
            f"Perfil visualizacion sincronizado{promotion_text}: {len(imported)} sesion(es), "
            f"{total_successes} exitos + {total_failures} fallos. "
            f"Nivel actual: {profile.get('current_level', 1)}."
        )

    def sync_window_management_profile_from_desktop_practice(self) -> str:
        profile = self._ensure_profile(
            skill_id="skill:window_management",
            display_name=self.SUPPORTED_SKILLS["window_management"]["display_name"],
            family=self.SUPPORTED_SKILLS["window_management"]["family"],
            supported=True,
            template_kind="window_management",
            canonical_entity="window_management",
        )
        strategy = self._read_mouse_strategy()
        synced_sessions = profile.setdefault("input_training_synced_window_management_sessions", [])
        if not isinstance(synced_sessions, list):
            synced_sessions = []
            profile["input_training_synced_window_management_sessions"] = synced_sessions
        synced_set = {str(item) for item in synced_sessions}

        imported: List[Dict[str, Any]] = []
        for entry in self._window_management_sync_entries():
            session_id = str(entry.get("session_id") or "").strip()
            if not session_id:
                continue
            sync_id = f"window_management:{session_id}"
            if sync_id in synced_set:
                continue

            level = max(
                1,
                min(
                    int(profile.get("current_level", 1) or 1),
                    int(profile.get("max_level", self.MAX_SKILL_LEVEL) or self.MAX_SKILL_LEVEL),
                ),
            )
            success = bool(entry.get("success"))
            verified_moves = int(entry.get("verified_moves", 0) or 0)
            total_moves = int(entry.get("total_moves", 0) or 0)
            cycle = self._empty_cycle(
                cycle_number=len(synced_set) + len(imported) + 1,
                level=level,
                requested_attempts=max(1, total_moves),
                requested_minutes=None,
            )
            cycle.update(
                {
                    "status": "completed" if success else "retry",
                    "successes": int(success),
                    "failures": int(not success),
                    "verified_successes": int(success),
                    "workflow_successes": int(success),
                    "summary": (
                        f"Window management nivel {level}: sincronizado desde practica de layout estricto "
                        f"({verified_moves}/{max(1, total_moves)} movimientos verificados)."
                    ),
                    "steps": [
                        {
                            "step": "window_management_workflow_sync",
                            "strategy": "strict_split_explorer_halves",
                            "verification": "window_layout_and_workflow",
                            "success": success,
                            "failure_stage": "" if success else "window_layout",
                            "session_id": session_id,
                            "reason": (
                                "layout estricto con workflow verificado"
                                if success
                                else "No vi un workflow completo verificado con layout estricto en esta sesion."
                            ),
                            "evidence": {
                                "manifest_path": str(entry.get("manifest_path", "")),
                                "strict_split_hits": int(entry.get("strict_split_hits", 0) or 0),
                                "repair_attempted": bool(entry.get("repair_attempted")),
                                "repair_recovered": bool(entry.get("repair_recovered")),
                                "verified_moves": verified_moves,
                                "total_moves": total_moves,
                            },
                        }
                    ],
                    "strategies_tried": ["sync:strict_split_explorer_halves"],
                    "verifications": [session_id],
                }
            )
            self._accumulate_metrics(profile, level, cycle)
            promoted_now = self._apply_promotions(profile)
            synced_sessions.append(sync_id)
            synced_set.add(sync_id)
            imported.append(
                {
                    "session_id": session_id,
                    "level": level,
                    "successes": int(success),
                    "failures": int(not success),
                    "promoted": promoted_now,
                    "manifest_path": str(entry.get("manifest_path", "")),
                }
            )
            self.record_training_result(
                TrainingScenarioResult(
                    skill_id="skill:window_management",
                    domain="file_manager/explorer",
                    scenario_id=(
                        "explorer_window_layout_repair"
                        if bool(entry.get("repair_attempted"))
                        else "explorer_window_layout_stable"
                    ),
                    session_id=session_id,
                    timestamp=int(entry.get("timestamp", 0) or 0),
                    level=level,
                    status="success" if success else "failure",
                    verified=success,
                    failure_stage="" if success else "window_layout",
                    attempted_strategies=["strict_split_explorer_halves"],
                    chosen_strategy="strict_split_explorer_halves",
                    metrics={
                        "verified_moves": verified_moves,
                        "total_moves": total_moves,
                        "strict_split_hits": int(entry.get("strict_split_hits", 0) or 0),
                    },
                    evidence={
                        "manifest_path": str(entry.get("manifest_path", "")),
                        "repair_attempted": bool(entry.get("repair_attempted")),
                        "repair_recovered": bool(entry.get("repair_recovered")),
                    },
                    verified_outcome={
                        "verified_moves": verified_moves,
                        "total_moves": total_moves,
                        "success": success,
                    },
                )
            )

        latest_session_id = self._window_management_latest_session_id(strategy)
        if not imported:
            self._refresh_window_management_profile_from_strategy(profile)
            if latest_session_id:
                profile["last_session_id"] = latest_session_id
            profile["updated_at"] = self._now()
            self.state.setdefault("profiles", {})["skill:window_management"] = profile
            self._save_state()
            return "Perfil window management: sin sesiones nuevas para sincronizar."

        promoted = any(bool(item.get("promoted")) for item in imported)
        self._finalize_profile_state(
            profile,
            meaningful_success=any(item["successes"] > 0 for item in imported),
            hard_failure=not any(item["successes"] > 0 for item in imported),
        )
        profile["last_input_training_sync_window_management"] = {
            "updated_at": self._now(),
            "imported_count": len(imported),
            "imported": imported[-12:],
            "promoted": promoted,
            "current_level": profile.get("current_level", 1),
        }
        profile["last_session_id"] = latest_session_id or str(imported[-1]["session_id"])
        self.state.setdefault("profiles", {})["skill:window_management"] = profile
        self._save_state()
        total_successes = sum(item["successes"] for item in imported)
        total_failures = sum(item["failures"] for item in imported)
        promotion_text = " con promocion" if promoted else ""
        return (
            f"Perfil window management sincronizado{promotion_text}: {len(imported)} sesion(es), "
            f"{total_successes} exitos + {total_failures} fallos. "
            f"Nivel actual: {profile.get('current_level', 1)}."
        )

    def _mouse_sync_level_for(
        self,
        metric_key: str,
        default_level: int,
        profile: Dict[str, Any],
    ) -> int:
        current_level = max(1, int(profile.get("current_level", 1)))
        max_level = max(1, int(profile.get("max_level", self.MAX_SKILL_LEVEL)))
        current_level = min(current_level, max_level)
        if current_level >= 3 and metric_key in {"drag", "detection", "selection", "workflow"}:
            return current_level
        if current_level >= 4 and metric_key in {"movement", "click", "double_click", "right_click"}:
            return current_level
        return max(1, min(default_level, max_level))

    def _latest_mouse_practice_session_id(self, strategy: Optional[Dict[str, Any]] = None) -> str:
        payload = strategy if strategy is not None else self._read_mouse_strategy()
        latest = ""
        for metric_key, _default_level, _label in self.MOUSE_PROFILE_SYNC_STEPS:
            metric = self._mouse_practice_metric(payload, metric_key)
            if not metric:
                continue
            session_id = str(metric.get("session_id") or metric.get("last_session_id") or "").strip()
            if session_id:
                latest = session_id
        return latest

    def _visual_sync_level_for(self, metric_key: str, default_level: int, profile: Dict[str, Any]) -> int:
        current_level = max(1, int(profile.get("current_level", 1) or 1))
        max_level = int(profile.get("max_level", self.MAX_SKILL_LEVEL) or self.MAX_SKILL_LEVEL)
        if current_level >= 4 and metric_key in {"selection", "workflow"}:
            return min(current_level, max_level)
        if current_level >= 2 and metric_key == "detection":
            return min(current_level, max_level)
        return max(1, min(default_level, max_level))

    def _latest_visual_practice_session_id(self, strategy: Optional[Dict[str, Any]] = None) -> str:
        payload = strategy if strategy is not None else self._read_mouse_strategy()
        latest = ""
        for metric_key, _default_level, _label, _scenario_id in self.VISUAL_PROFILE_SYNC_STEPS:
            metric = self._mouse_practice_metric(payload, metric_key)
            if not metric:
                continue
            session_id = str(metric.get("session_id") or metric.get("last_session_id") or "").strip()
            if session_id:
                latest = session_id
        return latest

    def _window_management_latest_session_id(self, strategy: Optional[Dict[str, Any]] = None) -> str:
        entries = self._window_management_sync_entries()
        if entries:
            return str(entries[-1].get("session_id", "") or "")
        summary = self._window_management_data_summary(strategy)
        return str(summary.get("workflow_session_id", "") or "")

    def _window_management_sync_entries(self) -> List[Dict[str, Any]]:
        session_dir = self.organizer_store.sessions_dir
        if not session_dir.exists():
            return []
        entries: List[Dict[str, Any]] = []
        for manifest_path in sorted(session_dir.glob("workflow_practice_*.json")):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            entry = self._window_management_sync_entry_from_manifest(payload, manifest_path)
            if entry:
                entries.append(entry)
        entries.sort(key=lambda item: (int(item.get("timestamp", 0) or 0), str(item.get("session_id", ""))))
        return entries

    def _window_management_sync_entry_from_manifest(
        self,
        payload: Dict[str, Any],
        manifest_path: Path,
    ) -> Optional[Dict[str, Any]]:
        session_id = str(payload.get("session_id", "") or "").strip()
        if not session_id:
            return None
        moves = payload.get("moves", [])
        if not isinstance(moves, list) or not moves:
            return None
        total_moves = len(moves)
        verified_moves = 0
        completed_moves = 0
        strict_split_hits = 0
        repair_attempted = False
        repair_recovered = False
        for move in moves:
            if not isinstance(move, dict):
                continue
            details = move.get("details", {}) if isinstance(move.get("details", {}), dict) else {}
            repair = (
                details.get("window_layout_repair", {})
                if isinstance(details.get("window_layout_repair", {}), dict)
                else {}
            )
            layout_mode = normalize_text(
                str(
                    details.get("window_layout_mode")
                    or repair.get("layout_mode")
                    or ""
                )
            )
            if layout_mode == "strict_split_explorer_halves":
                strict_split_hits += 1
            if bool(repair.get("attempted")):
                repair_attempted = True
            if bool(repair.get("recovered")):
                repair_recovered = True
            if bool(move.get("verified")):
                verified_moves += 1
            status = normalize_text(str(move.get("status", "")))
            if status in {"completed", "completed_with_fallback"}:
                completed_moves += 1
        if strict_split_hits <= 0 and not repair_attempted:
            return None
        created_at = str(payload.get("created_at", "") or "").strip()
        timestamp = self._timestamp_from_iso(created_at)
        if not timestamp:
            try:
                timestamp = int(manifest_path.stat().st_mtime)
            except Exception:
                timestamp = 0
        success = total_moves > 0 and completed_moves == total_moves and verified_moves == total_moves
        return {
            "session_id": session_id,
            "created_at": created_at,
            "timestamp": timestamp,
            "manifest_path": str(manifest_path),
            "total_moves": total_moves,
            "verified_moves": verified_moves,
            "completed_moves": completed_moves,
            "strict_split_hits": strict_split_hits,
            "repair_attempted": repair_attempted,
            "repair_recovered": repair_recovered,
            "success": success,
        }

    def skill_status(self, requested_skill: Optional[str] = None) -> str:
        profiles = self.state.get("profiles", {})
        if requested_skill:
            resolved = self._resolve_skill(requested_skill)
            profile = profiles.get(resolved["skill_id"])
            if not profile:
                return f"No hay perfil aprendido para '{requested_skill}'."
            return self._format_profile_status(profile)

        if not profiles:
            return "No hay perfiles de habilidades aprendibles todavia."

        snapshot_map = {
            str(item.get("skill_id", "")): item
            for item in self.training_progress_snapshot(limit=max(1, len(profiles))).get("profiles", [])
        }
        lines = ["Motor de habilidades aprendibles:"]
        for skill_id in sorted(profiles.keys()):
            profile = profiles[skill_id]
            readiness = "listo" if profile.get("real_usage_ready") else "aun en practica"
            progress = snapshot_map.get(skill_id, {})
            lines.append(
                f"- {profile.get('display_name', skill_id)} :: nivel legado {profile.get('current_level', 1)} | "
                f"nivel exp {profile.get('exponential_level', 0)}/6 | "
                f"estado {profile.get('state', 'draft')} | uso real {readiness} | "
                f"empuje {progress.get('coach_focus', 'sin foco')}"
            )
        lines.append(f"Archivo: {self.profiles_path}")
        return "\n".join(lines)

    def summarize_for_learning_status(self) -> str:
        snapshot = self.training_progress_snapshot()
        profiles = snapshot.get("profiles", [])
        if not profiles:
            return "Habilidades aprendibles: sin perfiles todavia."
        lines = ["Habilidades aprendibles:"]
        for profile in profiles:
            stuck_scene = str(profile.get("dominant_failure_scene", "") or "")
            emergency_feedback = str(profile.get("dominant_emergency_feedback", "") or "")
            blockage = ""
            if stuck_scene:
                blockage = stuck_scene
                if emergency_feedback:
                    blockage = f"{blockage}/{emergency_feedback}"
            lines.append(
                f"- {profile.get('display_name', profile.get('skill_id', 'skill'))}: "
                f"legado {profile.get('current_level', 1)} | "
                f"exp={profile.get('exponential_level', 0)}/6 | "
                f"tendencia={profile.get('trend', 'sin senal')} | "
                f"gate={profile.get('next_gate_status', 'n/a')} | "
                f"readiness={'si' if profile.get('real_usage_ready') else 'no'} | "
                f"atasco={blockage or profile.get('dominant_failure_stage', 'sin atasco')} | "
                f"empuje={profile.get('coach_focus', 'sin foco')}"
            )
        return "\n".join(lines)

    def training_progress_snapshot(self, limit: int = 12) -> Dict[str, Any]:
        profiles: List[Dict[str, Any]] = []
        for profile in self.state.get("profiles", {}).values():
            profiles.append(self._profile_progress_snapshot(profile))
        profiles.sort(
            key=lambda item: (
                0 if item.get("lagging") else 1,
                int(item.get("exponential_level", 0)),
                int(item.get("current_level", 1)),
                str(item.get("display_name", "")),
            )
        )
        return {
            "generated_at": int(time.time()),
            "profiles": profiles[: max(1, int(limit))],
        }

    def bootstrap_starter_profiles(self, requested_skills: Optional[List[str]] = None) -> str:
        targets = requested_skills or list(self.STARTER_BOOTSTRAP_TARGETS)
        bootstrapped: List[Dict[str, Any]] = []
        seen_skill_ids: set[str] = set()
        for target in targets:
            resolved = self._resolve_skill(target)
            if not resolved.get("supported"):
                continue
            skill_id = str(resolved["skill_id"])
            if skill_id in seen_skill_ids:
                continue
            seen_skill_ids.add(skill_id)
            existed = skill_id in self.state.get("profiles", {})
            profile = self._ensure_profile(
                skill_id=skill_id,
                display_name=str(resolved["display_name"]),
                family=str(resolved["family"]),
                supported=True,
                template_kind=str(resolved.get("template_kind", "draft")),
                canonical_entity=str(resolved.get("canonical_entity", "")),
            )
            verified_total = self._profile_verified_total(profile)
            needs_starter_draft = not existed or verified_total <= 0
            payload = self._starter_bootstrap_payload(profile, verified_total=verified_total, existed=existed)
            profile["starter_bootstrap"] = payload
            self._merge_preferred_strategies(profile, payload.get("preferred_strategies", {}))
            if needs_starter_draft:
                profile["trainable_draft"] = self._starter_trainable_draft(profile, payload)
            profile["last_investigation_summary"] = self._starter_bootstrap_summary(
                profile=profile,
                payload=payload,
                verified_total=verified_total,
                needs_starter_draft=needs_starter_draft,
            )
            profile["state"] = "active"
            profile["updated_at"] = self._now()
            bootstrapped.append(
                {
                    "display_name": profile.get("display_name", skill_id),
                    "skill_id": skill_id,
                    "verified_total": verified_total,
                    "starter_draft": needs_starter_draft,
                    "scenario_count": len(payload.get("scenario_templates", [])),
                    "coach_focus": payload.get("coach_focus", ""),
                }
            )

        if bootstrapped:
            self._save_state()

        if not bootstrapped:
            return "No encontre habilidades soportadas para arrancar."
        lines = [
            "Empujon inicial aplicado sin subir niveles ni inventar verificados.",
            "Politica: el arranque solo agrega rutas, requisitos y foco; los niveles siguen dependiendo de evidencia real.",
        ]
        for item in bootstrapped:
            mode = "arranque completo" if item["starter_draft"] else "refuerzo de ruta"
            lines.append(
                f"- {item['display_name']}: {mode} | verificados reales={item['verified_total']} | "
                f"escenarios={item['scenario_count']} | foco={item['coach_focus']}"
            )
        lines.append(f"Archivo: {self.profiles_path}")
        return "\n".join(lines)

    def _starter_bootstrap_payload(
        self,
        profile: Dict[str, Any],
        verified_total: int,
        existed: bool,
    ) -> Dict[str, Any]:
        blueprint = self._starter_bootstrap_blueprint(profile)
        previous = profile.get("starter_bootstrap", {})
        created_at = (
            str(previous.get("created_at", "")).strip()
            if isinstance(previous, dict)
            else ""
        ) or self._now()
        prerequisites = self._starter_prerequisite_snapshot(blueprint.get("prerequisite_skill_ids", []))
        return {
            "kind": "starter_bootstrap",
            "created_at": created_at,
            "updated_at": self._now(),
            "source": "warm_start_without_verified_credit",
            "skill_id": profile.get("skill_id", ""),
            "display_name": profile.get("display_name", ""),
            "existed_before_bootstrap": bool(existed),
            "verified_total_at_bootstrap": int(verified_total),
            "credit_policy": "No suma exitos, verificados, readiness ni niveles; solo prepara rutas de entrenamiento.",
            "coach_focus": blueprint["coach_focus"],
            "next_training_goal": blueprint["next_training_goal"],
            "scenario_templates": blueprint["scenario_templates"],
            "verification_rules": blueprint["verification_rules"],
            "missing_capabilities": blueprint["missing_capabilities"],
            "readiness_blockers": blueprint["readiness_blockers"],
            "preferred_strategies": blueprint["preferred_strategies"],
            "prerequisites": prerequisites,
            "draft_family": blueprint["draft_family"],
        }

    def _starter_bootstrap_blueprint(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        skill_id = normalize_text(str(profile.get("skill_id", "")))
        template_kind = normalize_text(str(profile.get("template_kind", "")))
        canonical = normalize_text(str(profile.get("canonical_entity", "")))

        if template_kind == "visual_perception" or "visualizacion" in skill_id:
            return {
                "draft_family": "vision",
                "coach_focus": "ver primero, actuar despues",
                "next_training_goal": "confirmar ventana, objetivo y precondicion visual antes de mover o escribir",
                "scenario_templates": [
                    {
                        "scenario_id": "visual_context_identity",
                        "description": "identificar app y ventana activa con evidencia fresca",
                        "level": 1,
                    },
                    {
                        "scenario_id": "visual_target_reacquire",
                        "description": "reencontrar el objetivo visible despues de cambiar foco",
                        "level": 2,
                    },
                    {
                        "scenario_id": "visual_workflow_precondition",
                        "description": "validar origen, destino y control visible antes del workflow",
                        "level": 4,
                    },
                ],
                "verification_rules": {
                    "requires_current_visual_evidence": True,
                    "minimum_confidence": 0.85,
                    "must_confirm_target_before_action": True,
                },
                "missing_capabilities": ["fresh_visual_snapshot_if_ocr_unavailable"],
                "readiness_blockers": ["necesita verificacion visual fresca; el arranque no cuenta como exito"],
                "preferred_strategies": {
                    "observe_before_action": True,
                    "reuse_desktop_strategy_manifest": True,
                    "cut_attempt_when_target_is_lost": True,
                },
                "prerequisite_skill_ids": ["skill:mouse", "skill:window_management", "app:explorer"],
            }

        if template_kind == "site_workflow" or canonical == "youtube" or "youtube" in skill_id:
            return {
                "draft_family": "browser",
                "coach_focus": "entrar al video y capturar evidencia legible",
                "next_training_goal": "buscar YouTube y extraer transcript, texto visible o contexto verificable del video",
                "scenario_templates": [
                    {
                        "scenario_id": "browser_open_google",
                        "description": "abrir navegador y confirmar sitio activo",
                        "level": 1,
                    },
                    {
                        "scenario_id": "browser_search_result",
                        "description": "buscar video y confirmar transicion fuera de resultados",
                        "level": 2,
                    },
                    {
                        "scenario_id": "youtube_audio_visual_interpretation",
                        "description": "interpretar usando transcript, subtitulos o texto visible verificable",
                        "level": 3,
                    },
                ],
                "verification_rules": {
                    "requires_active_site_confirmation": True,
                    "requires_transcript_or_visible_text": True,
                    "no_audio_credit_without_transcript_or_ocr": True,
                },
                "missing_capabilities": ["direct_audio_understanding_pipeline"],
                "readiness_blockers": [
                    "sonido real directo aun no cuenta; debe apoyarse en transcript, subtitulos, OCR o texto visible"
                ],
                "preferred_strategies": {
                    "youtube_search_via_browser": True,
                    "prefer_transcript_or_captions": True,
                    "discard_video_without_text_evidence": True,
                },
                "prerequisite_skill_ids": ["app:brave", "skill:investigar", "skill:visualizacion"],
            }

        if template_kind == "research_workflow" or "investigar" in skill_id:
            return {
                "draft_family": "research",
                "coach_focus": "abrir fuente real y medir texto util",
                "next_training_goal": "salir de Google, capturar pagina util y resumir solo con evidencia",
                "scenario_templates": [
                    {
                        "scenario_id": "research_single_source",
                        "description": "abrir una fuente util y comprobar texto capturable",
                        "level": 1,
                    },
                    {
                        "scenario_id": "research_multi_query",
                        "description": "probar variantes si la fuente inicial no sirve",
                        "level": 2,
                    },
                    {
                        "scenario_id": "research_cross_verify",
                        "description": "comparar fuentes antes de cerrar conclusion",
                        "level": 4,
                    },
                ],
                "verification_rules": {
                    "minimum_sources": 1,
                    "requires_useful_page_text": True,
                    "must_leave_search_results": True,
                },
                "missing_capabilities": ["robust_page_text_capture_when_site_blocks_ocr"],
                "readiness_blockers": ["no debe declarar investigado si sigue en resultados o texto vacio"],
                "preferred_strategies": {
                    "fallback_query_variants": True,
                    "discard_poor_sources": True,
                    "write_summary_from_captured_text": True,
                },
                "prerequisite_skill_ids": ["app:brave", "skill:visualizacion"],
            }

        if template_kind == "window_management" or "window_management" in skill_id:
            return {
                "draft_family": "file_manager",
                "coach_focus": "acomodar antes de mover",
                "next_training_goal": "mantener Explorer lado a lado y reparar oclusion antes del drag",
                "scenario_templates": [
                    {
                        "scenario_id": "explorer_window_layout_stable",
                        "description": "dejar origen y destino visibles sin taparse",
                        "level": 1,
                    },
                    {
                        "scenario_id": "explorer_window_layout_repair",
                        "description": "reparar ventanas tapadas antes de continuar",
                        "level": 2,
                    },
                    {
                        "scenario_id": "explorer_window_occlusion_recovery",
                        "description": "recuperar layout cuando el origen queda oculto",
                        "level": 3,
                    },
                ],
                "verification_rules": {
                    "requires_visible_source_and_destination": True,
                    "requires_strict_split_or_repair_evidence": True,
                },
                "missing_capabilities": [],
                "readiness_blockers": ["si origen o destino se tapa, debe reparar layout antes de contar avance"],
                "preferred_strategies": {
                    "window_layout_mode": "strict_split_explorer_halves",
                    "repair_before_drag": True,
                },
                "prerequisite_skill_ids": ["skill:mouse", "app:explorer"],
            }

        if template_kind == "keyboard" or "teclado" in skill_id:
            return {
                "draft_family": "documents",
                "coach_focus": "proteger contexto antes de escribir",
                "next_training_goal": "confirmar foco editable, escribir y releer en la misma sesion",
                "scenario_templates": [
                    {
                        "scenario_id": "keyboard_text_entry",
                        "description": "escribir texto corto y verificar captura",
                        "level": 1,
                    },
                    {
                        "scenario_id": "keyboard_browser_address_focus",
                        "description": "usar barra del navegador sin abrir modales",
                        "level": 2,
                    },
                    {
                        "scenario_id": "keyboard_multiapp_chain",
                        "description": "encadenar teclado entre app, navegador y ventana",
                        "level": 5,
                    },
                ],
                "verification_rules": {
                    "requires_active_editable_context": True,
                    "must_close_or_avoid_modals": True,
                    "requires_readback": True,
                },
                "missing_capabilities": [],
                "readiness_blockers": ["un modal de abrir/guardar invalida el intento"],
                "preferred_strategies": {
                    "confirm_focus_before_typing": True,
                    "readback_after_typing": True,
                },
                "prerequisite_skill_ids": ["app:notepad", "app:brave"],
            }

        if template_kind == "mouse_control" or "mouse" in skill_id:
            return {
                "draft_family": "vision",
                "coach_focus": "objetivo visible antes del gesto",
                "next_training_goal": "mover, clickear o arrastrar solo con destino confirmado",
                "scenario_templates": [
                    {
                        "scenario_id": "ui_detect_visible",
                        "description": "detectar objetivo antes de mover",
                        "level": 1,
                    },
                    {
                        "scenario_id": "mouse_right_click_visible",
                        "description": "abrir menu contextual y confirmar resultado",
                        "level": 1,
                    },
                    {
                        "scenario_id": "desktop_drag_real_verify",
                        "description": "arrastrar con verificacion real de destino",
                        "level": 3,
                    },
                ],
                "verification_rules": {
                    "requires_visible_target": True,
                    "requires_post_action_verification": True,
                },
                "missing_capabilities": [],
                "readiness_blockers": ["el movimiento sin resultado comprobado no cuenta"],
                "preferred_strategies": {
                    "reuse_desktop_drag_profile": True,
                    "lower_to_selection_when_drag_fails": True,
                },
                "prerequisite_skill_ids": ["skill:visualizacion", "skill:window_management"],
            }

        if template_kind == "browser_app":
            return {
                "draft_family": "browser",
                "coach_focus": "anclar navegador antes de navegar",
                "next_training_goal": "confirmar Brave activo, sitio correcto y transicion real",
                "scenario_templates": [
                    {
                        "scenario_id": "browser_open_google",
                        "description": "abrir navegador y confirmar pagina activa",
                        "level": 1,
                    },
                    {
                        "scenario_id": "browser_search_result",
                        "description": "buscar y confirmar resultados visibles",
                        "level": 2,
                    },
                    {
                        "scenario_id": "browser_form_fill",
                        "description": "interactuar con un campo visible y verificar estado",
                        "level": 3,
                    },
                ],
                "verification_rules": {
                    "requires_active_window_confirmation": True,
                    "requires_site_transition_confirmation": True,
                },
                "missing_capabilities": [],
                "readiness_blockers": ["no encadenar pasos si la pagina no cambia"],
                "preferred_strategies": {
                    "confirm_browser_foreground": True,
                    "cut_when_stuck_on_results": True,
                },
                "prerequisite_skill_ids": ["skill:visualizacion"],
            }

        if template_kind == "file_manager":
            return {
                "draft_family": "file_manager",
                "coach_focus": "fijar ruta y seleccion",
                "next_training_goal": "confirmar Explorer activo, ruta correcta y seleccion visible",
                "scenario_templates": [
                    {
                        "scenario_id": "explorer_open_workspace",
                        "description": "abrir Explorer en ruta de trabajo",
                        "level": 1,
                    },
                    {
                        "scenario_id": "explorer_select_item",
                        "description": "seleccionar item correcto con evidencia visible",
                        "level": 2,
                    },
                    {
                        "scenario_id": "explorer_move_verified",
                        "description": "mover archivo y comprobar destino",
                        "level": 3,
                    },
                ],
                "verification_rules": {
                    "requires_filesystem_verification": True,
                    "requires_visible_selection": True,
                },
                "missing_capabilities": [],
                "readiness_blockers": ["sin seleccion y ruta confirmadas no debe mover archivos"],
                "preferred_strategies": {
                    "confirm_explorer_path": True,
                    "select_before_drag": True,
                },
                "prerequisite_skill_ids": ["skill:mouse", "skill:window_management"],
            }

        if template_kind == "document_editor":
            return {
                "draft_family": "documents",
                "coach_focus": "escribir y releer",
                "next_training_goal": "crear texto verificable, reemplazarlo y comprobar archivo si guarda",
                "scenario_templates": [
                    {
                        "scenario_id": "document_write_basic",
                        "description": "escribir texto basico y capturarlo",
                        "level": 1,
                    },
                    {
                        "scenario_id": "document_replace_text",
                        "description": "reemplazar texto y verificar captura",
                        "level": 2,
                    },
                    {
                        "scenario_id": "document_save_verified",
                        "description": "guardar y comprobar archivo real",
                        "level": 3,
                    },
                ],
                "verification_rules": {
                    "requires_text_readback": True,
                    "requires_saved_file_for_save_scenarios": True,
                },
                "missing_capabilities": [],
                "readiness_blockers": ["captura vacia o foco equivocado invalida la escritura"],
                "preferred_strategies": {
                    "confirm_editable_body": True,
                    "readback_after_edit": True,
                },
                "prerequisite_skill_ids": ["skill:teclado"],
            }

        if template_kind == "game_foundation":
            return {
                "draft_family": "game",
                "coach_focus": "base de controles antes del juego vivo",
                "next_training_goal": "investigar controles y practicar input sin declarar dominio del juego real",
                "scenario_templates": [
                    {
                        "scenario_id": "game_input_foundation",
                        "description": "practicar base de teclado y mouse del juego",
                        "level": 1,
                    },
                    {
                        "scenario_id": "game_control_lookup",
                        "description": "investigar controles y registrar acciones verificables",
                        "level": 2,
                    },
                    {
                        "scenario_id": "game_goal_chain",
                        "description": "encadenar acciones orientadas a objetivo cuando haya backend visual",
                        "level": 4,
                    },
                ],
                "verification_rules": {
                    "requires_game_window_or_control_documentation": True,
                    "foundation_only_until_backend": True,
                },
                "missing_capabilities": ["game_state_verification"],
                "readiness_blockers": ["sin backend del juego solo cuenta base de controles, no dominio completo"],
                "preferred_strategies": {
                    "research_controls_first": True,
                    "reuse_keyboard_mouse_foundation": True,
                },
                "prerequisite_skill_ids": ["skill:teclado", "skill:mouse", "skill:investigar"],
            }

        return {
            "draft_family": "application",
            "coach_focus": "crear mapa de app",
            "next_training_goal": "abrir aplicacion, confirmar foco y mapear controles visibles",
            "scenario_templates": [
                {
                    "scenario_id": "application_open_verify",
                    "description": "abrir aplicacion y verificar foco",
                    "level": 1,
                },
                {
                    "scenario_id": "application_click_target",
                    "description": "accionar control visible y verificar efecto",
                    "level": 2,
                },
                {
                    "scenario_id": "application_goal_workflow",
                    "description": "ejecutar flujo util completo",
                    "level": 3,
                },
            ],
            "verification_rules": {
                "requires_active_window_confirmation": True,
                "requires_post_action_verification": True,
            },
            "missing_capabilities": ["application_specific_ui_map"],
            "readiness_blockers": ["necesita mapa visual de controles antes de automatizar"],
            "preferred_strategies": {
                "confirm_app_foreground": True,
                "map_visible_controls_first": True,
            },
            "prerequisite_skill_ids": ["skill:visualizacion", "skill:mouse"],
        }

    def _starter_trainable_draft(self, profile: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        draft = create_trainable_draft(
            skill_id=str(profile.get("skill_id", "")),
            skill_name=str(profile.get("display_name", "")),
            description=str(payload.get("next_training_goal", "")),
            family=str(payload.get("draft_family", "application")),
        ).to_dict()
        draft["scenario_templates"] = list(payload.get("scenario_templates", []))
        draft["verification_rules"] = dict(payload.get("verification_rules", {}))
        draft["missing_capabilities"] = list(payload.get("missing_capabilities", []))
        draft["readiness_blockers"] = list(payload.get("readiness_blockers", []))
        draft["starter_prerequisites"] = list(payload.get("prerequisites", []))
        draft["bootstrap_kind"] = "starter_bootstrap"
        draft["credit_policy"] = payload.get("credit_policy", "")
        return draft

    def _starter_prerequisite_snapshot(self, prerequisite_skill_ids: List[str]) -> List[Dict[str, Any]]:
        snapshots: List[Dict[str, Any]] = []
        profiles = self.state.get("profiles", {})
        for skill_id in prerequisite_skill_ids:
            profile = profiles.get(skill_id)
            snapshots.append(
                {
                    "skill_id": skill_id,
                    "present": bool(profile),
                    "verified_total": self._profile_verified_total(profile) if profile else 0,
                    "highest_verified_level": int(profile.get("highest_verified_level", 0) or 0) if profile else 0,
                    "real_usage_ready": bool(profile.get("real_usage_ready")) if profile else False,
                }
            )
        return snapshots

    def _profile_verified_total(self, profile: Optional[Dict[str, Any]]) -> int:
        if not profile:
            return 0
        metric_total = 0
        for metrics in profile.get("level_metrics", {}).values():
            if isinstance(metrics, dict):
                metric_total += int(metrics.get("verified_count", 0) or 0)
        skill_id = str(profile.get("skill_id", ""))
        history_total = len([item for item in self._profile_training_history(skill_id) if item.verified]) if skill_id else 0
        return max(metric_total, history_total)

    @staticmethod
    def _merge_preferred_strategies(profile: Dict[str, Any], preferred: Any) -> None:
        if not isinstance(preferred, dict):
            return
        strategies = profile.setdefault("preferred_strategies", {})
        if not isinstance(strategies, dict):
            strategies = {}
            profile["preferred_strategies"] = strategies
        for key, value in preferred.items():
            strategies[key] = value

    @staticmethod
    def _starter_bootstrap_summary(
        profile: Dict[str, Any],
        payload: Dict[str, Any],
        verified_total: int,
        needs_starter_draft: bool,
    ) -> str:
        draft_label = "perfil de arranque completo" if needs_starter_draft else "ruta reforzada"
        return (
            f"{draft_label} para {profile.get('display_name', profile.get('skill_id', 'habilidad'))}: "
            f"foco={payload.get('coach_focus', 'entrenar con evidencia')}; "
            f"verificados reales conservados={verified_total}; "
            "no se subieron niveles ni readiness sin pruebas."
        )

    def _profile_progress_snapshot(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        skill_id = str(profile.get("skill_id", ""))
        history = self._profile_training_history(skill_id) if skill_id else []
        recent = history[-8:] if len(history) > 8 else history
        verified_recent = [item for item in recent if item.verified]
        verified_all = [item for item in history if item.verified]
        successful_recent = [
            item for item in recent if item.status in {"success", "success_with_fallback"}
        ]
        recent_success_rate = (
            round(len(successful_recent) / len(recent), 4)
            if recent
            else 0.0
        )
        days_since_verified = (
            self._days_since_verified(verified_all[-1])
            if verified_all
            else 30.0
        )
        trend, lagging_reason = self._progress_trend_for_profile(
            profile=profile,
            recent=recent,
            recent_success_rate=recent_success_rate,
            verified_recent_count=len(verified_recent),
            days_since_verified=days_since_verified,
        )
        coaching = self._profile_coaching_snapshot(
            profile=profile,
            recent=recent,
            recent_success_rate=recent_success_rate,
        )
        return {
            "skill_id": skill_id,
            "display_name": profile.get("display_name", skill_id),
            "current_level": int(profile.get("current_level", 1) or 1),
            "exponential_level": int(profile.get("exponential_level", 0) or 0),
            "real_usage_ready": bool(profile.get("real_usage_ready")),
            "trend": trend,
            "lagging": trend in {"atrasado", "estancado"},
            "lagging_reason": lagging_reason,
            "recent_success_rate": recent_success_rate,
            "recent_verified_count": len(verified_recent),
            "days_since_verified": round(days_since_verified, 2),
            "next_gate_status": self._next_gate_status(profile),
            "last_session_id": str(profile.get("last_session_id", "")),
            "template_kind": str(profile.get("template_kind", "draft")),
            "behavior_summary": coaching.get("behavior_summary", ""),
            "coach_focus": coaching.get("coach_focus", ""),
            "coach_message": coaching.get("coach_message", ""),
            "dominant_failure_stage": coaching.get("dominant_failure_stage", ""),
            "dominant_failure_scene": coaching.get("dominant_failure_scene", ""),
            "dominant_emergency_feedback": coaching.get("dominant_emergency_feedback", ""),
            "dominant_success_strategy": coaching.get("dominant_success_strategy", ""),
            "dominant_failure_strategy": coaching.get("dominant_failure_strategy", ""),
        }

    def _progress_trend_for_profile(
        self,
        profile: Dict[str, Any],
        recent: List[TrainingScenarioResult],
        recent_success_rate: float,
        verified_recent_count: int,
        days_since_verified: float,
    ) -> Tuple[str, str]:
        consecutive_failed = int(profile.get("consecutive_failed_sessions", 0) or 0)
        exp_level = int(profile.get("exponential_level", 0) or 0)
        if exp_level >= 6:
            return "optimizado", ""
        if verified_recent_count > 0 and recent_success_rate >= 0.75 and consecutive_failed == 0:
            return "subiendo", ""
        if consecutive_failed >= 2:
            return "atrasado", f"{consecutive_failed} sesiones fallidas consecutivas."
        if recent and recent_success_rate < 0.4:
            return "atrasado", f"tasa reciente baja: {recent_success_rate:.0%}."
        if days_since_verified >= 7.0:
            return "estancado", f"lleva {days_since_verified:.1f} dias sin verificacion."
        if recent_success_rate >= 0.55 or verified_recent_count > 0:
            return "estable", ""
        return "sin senal", "aun no junta evidencia consistente."

    def _next_gate_status(self, profile: Dict[str, Any]) -> str:
        current_level = int(profile.get("current_level", 1) or 1)
        max_level = int(profile.get("max_level", self.MAX_SKILL_LEVEL) or self.MAX_SKILL_LEVEL)
        if current_level >= max_level:
            exp_level = int(profile.get("exponential_level", 0) or 0)
            max_exp_level = int(profile.get("max_exponential_level", 6) or 6)
            if exp_level >= max_exp_level:
                return "optimizado"
            return f"fase exponencial {exp_level}/{max_exp_level}"
        next_level = current_level + 1
        gate_key = f"{current_level}_to_{next_level}"
        metrics = profile.get("level_metrics", {}).get(str(current_level), {})
        gate = profile.get("gates", {}).get(gate_key, {})
        success_rate = float(metrics.get("success_rate", 0.0) or 0.0)
        verified_count = int(metrics.get("verified_count", 0) or 0)
        workflow_successes = int(metrics.get("workflow_successes", 0) or 0)
        target_rate = float(gate.get("success_rate", 0.0) or 0.0)
        target_verified = int(gate.get("verified_count", 0) or 0)
        target_workflows = int(gate.get("workflow_successes", 0) or 0)
        ready = (
            success_rate >= target_rate
            and verified_count >= target_verified
            and workflow_successes >= target_workflows
        )
        if ready:
            return f"{current_level}->{next_level} listo"
        return (
            f"{current_level}->{next_level}: "
            f"tasa {success_rate:.2f}/{target_rate:.2f} | "
            f"ver {verified_count}/{target_verified} | "
            f"wf {workflow_successes}/{target_workflows}"
        )

    @staticmethod
    def _dominant_result_strategy(results: List[TrainingScenarioResult]) -> str:
        strategies = [
            str(
                item.chosen_strategy
                or item.fallback_used
                or (item.attempted_strategies[0] if item.attempted_strategies else "")
            ).strip()
            for item in results
        ]
        filtered = [item for item in strategies if item]
        if not filtered:
            return ""
        return Counter(filtered).most_common(1)[0][0]

    @staticmethod
    def _research_scene_from_history_item(item: TrainingScenarioResult) -> str:
        evidence = item.evidence if isinstance(item.evidence, dict) else {}
        scene_id = str(evidence.get("scene_id", "") or "").strip()
        if scene_id:
            return scene_id
        stage = normalize_text(str(item.failure_stage or ""))
        if stage in {"stuck_on_google", "visible_google_results"}:
            return "google_results"
        if "modal" in stage:
            return "modal"
        if "dialog" in stage:
            return "file_dialog"
        if stage in {"opened_result_but_empty", "ocr_unavailable", "page_poor_quality"}:
            return "blocked_page"
        return ""

    def _research_feedback_from_history_item(self, item: TrainingScenarioResult) -> str:
        evidence = item.evidence if isinstance(item.evidence, dict) else {}
        feedback = str(evidence.get("emergency_feedback", "") or "").strip()
        if feedback:
            return feedback
        scene_id = self._research_scene_from_history_item(item)
        reason = normalize_text(
            str(
                item.error_log
                or evidence.get("source_quality_reason")
                or ""
            )
        )
        if "ayuda lateral" in reason or "ruido de plataforma" in reason:
            return "abrimos ayuda lateral"
        if "no parece alinearse con la consulta" in reason:
            return "la pagina sirve pero no coincide con la consulta"
        feedback_by_scene = {
            "google_results": "seguimos en resultados",
            "modal": "hay modal",
            "file_dialog": "hay dialogo de archivo",
            "blocked_page": "pagina bloqueada o vacia",
        }
        return feedback_by_scene.get(scene_id, "")

    def _profile_coaching_snapshot(
        self,
        profile: Dict[str, Any],
        recent: List[TrainingScenarioResult],
        recent_success_rate: float,
    ) -> Dict[str, str]:
        if not recent:
            starter = profile.get("starter_bootstrap", {})
            if isinstance(starter, dict) and starter:
                return {
                    "behavior_summary": "Arranque guiado listo; falta evidencia fresca.",
                    "coach_focus": str(starter.get("coach_focus", "juntar evidencia base")),
                    "coach_message": str(
                        starter.get(
                            "next_training_goal",
                            "Primero necesita intentos verificados para saber que corregir.",
                        )
                    ),
                    "dominant_failure_stage": "",
                    "dominant_failure_scene": "",
                    "dominant_emergency_feedback": "",
                    "dominant_success_strategy": "",
                    "dominant_failure_strategy": "",
                }
            return {
                "behavior_summary": "Sin historial reciente suficiente.",
                "coach_focus": "juntar evidencia base",
                "coach_message": "Primero necesita intentos verificados para saber que corregir.",
                "dominant_failure_stage": "",
                "dominant_failure_scene": "",
                "dominant_emergency_feedback": "",
                "dominant_success_strategy": "",
                "dominant_failure_strategy": "",
            }

        verified_recent = [item for item in recent if item.verified]
        successful_recent = [
            item for item in recent if item.status in {"success", "success_with_fallback"}
        ]
        failed_recent = [item for item in recent if not item.verified]
        success_strategy = self._dominant_result_strategy(successful_recent)
        failure_strategy = self._dominant_result_strategy(failed_recent)
        dominant_failure_stage = ""
        dominant_failure_count = 0
        dominant_failure_scene = ""
        dominant_emergency_feedback = ""
        if failed_recent:
            stage_counts = Counter(
                normalize_text(str(item.failure_stage or "")) or "action"
                for item in failed_recent
            )
            dominant_failure_stage, dominant_failure_count = stage_counts.most_common(1)[0]
            scene_counts = Counter(
                scene_id
                for scene_id in (self._research_scene_from_history_item(item) for item in failed_recent)
                if scene_id
            )
            if scene_counts:
                dominant_failure_scene = scene_counts.most_common(1)[0][0]
            feedback_counts = Counter(
                feedback
                for feedback in (self._research_feedback_from_history_item(item) for item in failed_recent)
                if feedback
            )
            if feedback_counts:
                dominant_emergency_feedback = feedback_counts.most_common(1)[0][0]

        behavior_parts: List[str] = []
        if dominant_failure_stage:
            behavior_parts.append(
                f"falla mas en {dominant_failure_stage.replace('_', ' ')} ({dominant_failure_count})"
            )
        if dominant_failure_scene:
            behavior_parts.append(f"escena dominante {dominant_failure_scene}")
        if dominant_emergency_feedback:
            behavior_parts.append(f"feedback {dominant_emergency_feedback}")
        if success_strategy:
            behavior_parts.append(f"mejor via reciente {success_strategy}")
        elif recent_success_rate >= 0.75:
            behavior_parts.append("mantiene una base estable")
        elif failed_recent:
            behavior_parts.append("todavia no fija una via confiable")
        behavior_summary = "; ".join(behavior_parts) or "Movimiento reciente mixto."

        coach_focus, coach_message = self._profile_coaching_message(
            profile=profile,
            dominant_failure_stage=dominant_failure_stage,
            dominant_failure_scene=dominant_failure_scene,
            dominant_emergency_feedback=dominant_emergency_feedback,
            success_strategy=success_strategy,
            failure_strategy=failure_strategy,
            recent_success_rate=recent_success_rate,
            verified_recent_count=len(verified_recent),
            failed_recent_count=len(failed_recent),
        )
        return {
            "behavior_summary": behavior_summary,
            "coach_focus": coach_focus,
            "coach_message": coach_message,
            "dominant_failure_stage": dominant_failure_stage,
            "dominant_failure_scene": dominant_failure_scene,
            "dominant_emergency_feedback": dominant_emergency_feedback,
            "dominant_success_strategy": success_strategy,
            "dominant_failure_strategy": failure_strategy,
        }

    def _profile_coaching_message(
        self,
        profile: Dict[str, Any],
        dominant_failure_stage: str,
        dominant_failure_scene: str,
        dominant_emergency_feedback: str,
        success_strategy: str,
        failure_strategy: str,
        recent_success_rate: float,
        verified_recent_count: int,
        failed_recent_count: int,
    ) -> Tuple[str, str]:
        template_kind = normalize_text(str(profile.get("template_kind", "")))
        skill_id = normalize_text(str(profile.get("skill_id", "")))
        preferred_success = success_strategy or "la via actual"

        if failed_recent_count == 0 and recent_success_rate >= 0.85:
            return (
                "subir dificultad con control",
                f"Conserva {preferred_success} y sube un paso la dificultad sin soltar la verificacion dura.",
            )
        if failed_recent_count == 0 and verified_recent_count > 0:
            return (
                "consolidar la base",
                f"Repite {preferred_success} hasta que la verificacion salga estable sin rescates extra.",
            )

        if template_kind == "research_workflow" or "investigar" in skill_id:
            if dominant_failure_scene == "google_results" or dominant_failure_stage == "stuck_on_google":
                return (
                    "salir de resultados y abrir fuente real",
                    (
                        f"Cuando se quede en Google, corta pronto el intento y vuelve a {preferred_success}; "
                        "no sigas empujando click visible si la pagina no cambia."
                    ),
                )
            if dominant_emergency_feedback == "abrimos ayuda lateral":
                return (
                    "descartar ayuda lateral y volver a resultados",
                    "Si abre ayuda lateral o ruido de plataforma, descartalo rapido y vuelve a resultados antes de gastar OCR.",
                )
            if dominant_failure_scene == "modal":
                return (
                    "limpiar modal antes de leer",
                    "Si aparece un modal encima de la fuente, cierralo primero; leer el fondo no cuenta como investigar.",
                )
            if dominant_failure_scene == "file_dialog":
                return (
                    "cerrar dialogo de archivo y recuperar foco",
                    "Si se abre un cuadro de archivo, cancelalo y reconfirma Brave antes de seguir investigando.",
                )
            if dominant_emergency_feedback == "la pagina sirve pero no coincide con la consulta":
                return (
                    "cambiar a una fuente alineada",
                    "Si la pagina tiene texto pero no coincide con la consulta, descartala rapido y abre otra fuente mas alineada.",
                )
            if dominant_failure_scene == "blocked_page":
                return (
                    "abandonar bloqueos y buscar otra fuente",
                    "Si la pagina esta bloqueada, vacia o sin lectura util, no insistas: vuelve a resultados y cambia de fuente.",
                )
            if dominant_failure_stage in {"opened_result_but_empty", "ocr_unavailable", "page_poor_quality"}:
                return (
                    "elegir paginas capturables",
                    "Antes de resumir, confirma texto util; si abre vacio o flojo, descarta esa fuente y cambia de pagina.",
                )
            if dominant_failure_stage == "visible_google_results":
                return (
                    "asegurar contexto antes de investigar",
                    "Primero confirma barra y resultados visibles de Google; luego abre fuentes y mide texto util.",
                )

        if template_kind == "mouse_control" or skill_id == "skill:mouse":
            if "drag" in normalize_text(failure_strategy) or dominant_failure_stage in {"action", "post_drag_verification"}:
                return (
                    "bajar a seleccion verificable antes del drag",
                    "Si el drag falla varias veces, baja a deteccion+seleccion confirmada y cambia de gesto antes de gastar todo el ciclo.",
                )
            if dominant_failure_stage in {"detection_lost", "selection_lost", "verification"}:
                return (
                    "ver primero, mover despues",
                    "Primero confirma el objetivo visual; luego mueve y verifica tolerancia o seleccion antes del siguiente paso.",
                )

        if template_kind == "window_management":
            if dominant_failure_stage in {"source_occluded", "window_layout", "wrong_active_window", "verification"}:
                return (
                    "acomodar antes de mover",
                    "Si origen y destino se montan, rehace el layout izquierda/derecha antes del drag; no sigas con ventanas tapadas.",
                )
            if "repair" in dominant_failure_stage or "layout" in normalize_text(failure_strategy):
                return (
                    "reparar el layout y reconfirmar",
                    "Despues de reacomodar ventanas, reconfirma la seleccion visible antes de mover el archivo.",
                )

        if template_kind == "keyboard" or "teclado" in skill_id:
            if "modal" in dominant_failure_stage or "dialog" in dominant_failure_stage:
                return (
                    "proteger el contexto antes de escribir",
                    "Antes de practicar texto, limpia dialogos y confirma la ventana activa; escribir sobre un modal no cuenta como avance.",
                )

        if template_kind == "browser_app":
            if dominant_failure_stage in {"window_site_transition", "stuck_on_google", "visible_google_results"}:
                return (
                    "cerrar la transicion del navegador antes del siguiente paso",
                    (
                        f"No encadenes mas pasos si la pagina no cambia; confirma cambio real de sitio o titulo y "
                        f"vuelve a {preferred_success}."
                    ),
                )
            if dominant_failure_stage in {"strict_real", "wrong_active_window"}:
                return (
                    "anclar navegador y sitio antes de seguir",
                    "Primero deja Brave en frente y en el sitio correcto; luego busca, abre o navega.",
                )

        if template_kind == "site_workflow":
            if dominant_failure_stage in {"window_site_transition", "visible_google_results", "stuck_on_google"}:
                return (
                    "salir del buscador y entrar al sitio objetivo",
                    "No des por bueno el paso mientras siga en resultados; primero entra al sitio o video y luego verifica contenido.",
                )
            if "transcript" in dominant_failure_stage or "visible_text" in dominant_failure_stage:
                return (
                    "capturar evidencia del sitio antes de continuar",
                    "Antes de resumir o avanzar, confirma transcript o texto visible util dentro del sitio actual.",
                )

        if template_kind == "document_editor":
            if dominant_failure_stage in {"capture_selected_text", "document_write_basic", "document_replace_text"}:
                return (
                    "escribir y releer en la misma sesion",
                    "Despues de escribir, relee el texto capturado antes de seguir; si la captura sale vacia, corrige foco y seleccion primero.",
                )
            if dominant_failure_stage in {"strict_real", "wrong_active_window"}:
                return (
                    "anclar el editor antes de editar",
                    "Confirma documento activo y cuerpo editable antes de teclear; sin eso, cualquier escritura cuenta como desvio.",
                )
            if "save" in dominant_failure_stage:
                return (
                    "guardar y comprobar archivo real",
                    "No cierres el ciclo hasta ver el archivo guardado donde corresponde.",
                )

        if template_kind == "file_manager":
            if dominant_failure_stage in {"explorer_move_verified", "post_drag_verification", "verification", "action"} or "drag" in normalize_text(failure_strategy):
                return (
                    "confirmar origen y destino antes de insistir",
                    "Si mover falla, valida seleccion visible y corta temprano a un fallback verificable; no gastes todo el ciclo en el mismo drag.",
                )
            if dominant_failure_stage in {"explorer_search_focus", "strict_real", "wrong_active_window"}:
                return (
                    "fijar explorer y ruta antes de operar",
                    "Asegura Explorer activo, carpeta correcta y seleccion visible antes de buscar, renombrar o mover.",
                )

        if template_kind == "application_workflow":
            if dominant_failure_stage in {"strict_real", "wrong_active_window"}:
                return (
                    "reconstruir contexto antes del workflow",
                    "Primero reabre o reenfoca la app correcta y solo despues retoma la secuencia completa.",
                )

        if template_kind == "game_foundation":
            if not bool(profile.get("game_backend_ready", False)):
                return (
                    "cerrar el backend especifico del juego",
                    "La base de teclado y mouse ya existe, pero el siguiente salto es amarrarla al juego real sin fingir dominio completo.",
                )

        if success_strategy and failure_strategy and success_strategy != failure_strategy:
            return (
                "apoyarse mas en la via que si verifica",
                f"Apoyate mas en {success_strategy} y corta antes {failure_strategy} cuando vuelva a desviarse.",
            )
        return (
            "corregir un solo factor por intento",
            "Reduce el cambio por intento: misma meta, una sola correccion, y verificacion dura al final de cada vuelta.",
        )

    def _run_session(
        self,
        mode: str,
        requested_skill: str,
        goal: Optional[str] = None,
        requested_attempts: Optional[int] = None,
        requested_minutes: Optional[int] = None,
        create_document: bool = False,
    ) -> str:
        resolved = self._resolve_skill(requested_skill)
        skill_id = resolved["skill_id"]
        profile = self._ensure_profile(
            skill_id=skill_id,
            display_name=resolved["display_name"],
            family=resolved["family"],
            supported=resolved["supported"],
            template_kind=resolved.get("template_kind", "draft"),
            canonical_entity=resolved.get("canonical_entity", ""),
        )
        normalized_goal = (goal or "").strip()
        if normalize_text(normalized_goal) == normalize_text(requested_skill):
            normalized_goal = ""
        session = self._new_session(
            mode=mode,
            skill_id=skill_id,
            display_name=profile["display_name"],
            goal=normalized_goal,
            user_requested_document=create_document,
            start_level=int(profile.get("current_level", 1)),
        )
        task_id = self.memory.record_task_plan(
            original_command=self._session_command_label(mode, requested_skill, normalized_goal),
            intent="learning_skill",
            plan={
                "mode": mode,
                "skill_id": skill_id,
                "goal": normalized_goal,
                "start_level": session["start_level"],
            },
        )

        try:
            if not resolved["supported"]:
                if mode in {"practice", "evaluate", "use"} and self._activate_generic_supported_profile(
                    profile,
                    requested_skill=requested_skill,
                    goal=normalized_goal,
                ):
                    resolved["supported"] = True
                    resolved["template_kind"] = str(profile.get("template_kind", "draft") or "draft")
                else:
                    self._run_draft_analysis(profile, session, requested_skill, normalized_goal)
                    self._persist_session(profile, session, final_status="completed")
                    self.memory.update_task_run(task_id, "completed", session["summary"][:3000])
                    return session["summary"]

            session_attempts, session_minutes = self._resolve_session_budgets(
                requested_attempts=requested_attempts,
                requested_minutes=requested_minutes,
                skill_id=skill_id,
                level=int(profile.get("current_level", 1)),
            )

            max_cycles = int(self._settings().get("max_cycles_per_session", 3))
            meaningful_success = False
            promoted = False
            hard_failure_session = False
            for cycle_number in range(1, max_cycles + 1):
                current_level = int(profile.get("current_level", 1))
                cycle = self._execute_supported_cycle(
                    skill_id=skill_id,
                    level=current_level,
                    mode=mode,
                    goal=normalized_goal,
                    requested_attempts=session_attempts,
                    requested_minutes=session_minutes,
                    create_document=create_document,
                    cycle_number=cycle_number,
                )
                session["cycles"].append(cycle)
                self._record_cycle_logs(skill_id, current_level, cycle)
                self._accumulate_metrics(profile, current_level, cycle)
                if cycle.get("verified_successes", 0) > 0 or cycle.get("workflow_successes", 0) > 0:
                    meaningful_success = True
                if not meaningful_success and self._cycle_failure_is_hard(profile, cycle):
                    hard_failure_session = True
                if cycle.get("status") == "stopped":
                    session["decisions"].append(
                        "Detenido: solicitud externa del entrenamiento continuo."
                    )
                    break
                cycle_failure_text = normalize_text(
                    " ".join(str(item) for item in cycle.get("context_failures", []))
                    + " "
                    + str(cycle.get("summary", ""))
                )
                if any(token in cycle_failure_text for token in ("abrir", "open file", "apertura")):
                    session["decisions"].append("Detenido: aparecio un cuadro de apertura de archivo.")
                    break
                previous_level = current_level
                cycle_promoted = self._apply_promotions(profile)
                promoted = promoted or cycle_promoted
                if int(profile.get("current_level", 1)) != previous_level:
                    session["decisions"].append(
                        f"Promocion de nivel {previous_level} -> {profile['current_level']}"
                    )
                    if mode == "learn" and cycle_number < max_cycles:
                        continue
                if mode in {"practice", "evaluate", "use"}:
                    break
                if meaningful_success and not cycle_promoted:
                    break

            self._finalize_profile_state(profile, meaningful_success, hard_failure=hard_failure_session)
            self._finalize_session_summary(profile, session, promoted=promoted, meaningful_success=meaningful_success)
            status = "completed" if session["final_decision"] != "blocked" else "failed"
            self._persist_session(profile, session, final_status=status)
            self.memory.update_task_run(task_id, status, session["summary"][:3000])
            return session["summary"]
        except Exception as exc:
            session["final_decision"] = "blocked"
            session["summary"] = f"Sesion de aprendizaje interrumpida para {profile['display_name']}: {exc}"
            self._append_blocker(profile, str(exc))
            self._persist_session(profile, session, final_status="failed")
            self.memory.update_task_run(task_id, "failed", session["summary"][:3000])
            raise

    def _run_draft_analysis(
        self,
        profile: Dict[str, Any],
        session: Dict[str, Any],
        requested_skill: str,
        goal: str,
    ) -> None:
        topic = goal or requested_skill
        decomposition = self._draft_skill_decomposition(topic)
        draft = create_trainable_draft(
            skill_id=str(profile.get("skill_id", requested_skill)),
            skill_name=str(profile.get("display_name", requested_skill)),
            description=topic,
        )
        draft_payload = draft.to_dict()
        discovery = self._discover_draft_knowledge(topic, draft_payload)
        profile["state"] = "draft"
        profile["supported"] = False
        profile["trainable_draft"] = draft_payload
        if discovery:
            profile["last_investigation_summary"] = str(discovery.get("profile_summary", "")).strip() or (
                f"Analisis preliminar para '{topic}': se encontro contexto base para orientar el draft."
            )
            self.memory.record_step_log(
                task_intent=f"learning_skill:{profile.get('skill_id', requested_skill)}",
                step_name="draft_research_discovery",
                status="completed",
                detail=json.dumps(discovery, ensure_ascii=False)[:3000],
            )
        else:
            profile["last_investigation_summary"] = (
                f"Analisis preliminar para '{topic}': Raphel aun no tiene una habilidad oficial, "
                "pero ya quedo mapeada una ruta entrenable por familia."
            )
        profile["last_decomposition"] = decomposition
        profile["updated_at"] = self._now()
        session["cycles"].append(
            {
                "cycle_number": 1,
                "level": 0,
                "status": "draft_only",
                "steps": [],
                "strategies_tried": [],
                "verifications": [],
                "successes": 0,
                "failures": 0,
                "verified_successes": 0,
                "workflow_successes": 0,
                "summary": "Habilidad no soportada directamente; se creo draft entrenable con curriculum base.",
                "decomposition": decomposition,
                "trainable_draft": draft_payload,
                "draft_discovery": discovery or {},
            }
        )
        session["final_decision"] = "draft_only"
        session["summary"] = self._format_draft_summary(profile, topic, decomposition)

    def _discover_draft_knowledge(
        self,
        topic: str,
        draft_payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        executor = getattr(self, "task_executor", None)
        researcher = getattr(executor, "perform_research", None)
        if not callable(researcher):
            return None

        family = str(draft_payload.get("family", "application") or "application")
        browser = str(self.config.get("default_browser", "brave") or "brave")
        queries = self._draft_research_queries(topic, family)
        if not queries:
            return None

        knowledge_assets: List[Dict[str, Any]] = []
        combined_sources: List[str] = []
        summary_chunks: List[str] = []
        findings_chunks: List[str] = []
        useful_source_total = 0
        used_queries: List[str] = []

        for query in queries[:2]:
            try:
                research = researcher(topic=query, browser=browser, result_count=2)
            except TypeError:
                research = researcher(query, browser=browser, result_count=2)
            except Exception:
                continue
            if not isinstance(research, dict):
                continue

            used_queries.append(query)
            useful_source_count = int(research.get("useful_source_count", 0) or 0)
            summary = str(research.get("summary", "") or "").strip()
            findings = str(research.get("findings", "") or "").strip()
            reviewed_sources = [
                str(item)
                for item in research.get("reviewed_sources", [])
                if str(item).strip()
            ]
            if useful_source_count <= 0 and not summary and not reviewed_sources:
                continue

            knowledge_assets.append(
                {
                    "query": query,
                    "summary": summary,
                    "findings": findings,
                    "useful_source_count": useful_source_count,
                    "reviewed_sources": reviewed_sources[:5],
                }
            )
            useful_source_total += useful_source_count
            for source in reviewed_sources:
                if source not in combined_sources:
                    combined_sources.append(source)
            if summary and summary not in summary_chunks:
                summary_chunks.append(summary)
            if findings and findings not in findings_chunks:
                findings_chunks.append(findings)

        if not knowledge_assets:
            return None

        draft_payload["knowledge_assets"] = knowledge_assets
        draft_payload["research_queries"] = used_queries
        draft_payload["research_summary"] = " ".join(summary_chunks).strip()
        draft_payload["research_findings"] = " ".join(findings_chunks).strip()
        draft_payload["useful_source_count"] = useful_source_total

        research_profile = self.state.get("profiles", {}).get("skill:investigar", {})
        blocked_note = ""
        if str(research_profile.get("state", "active") or "active") == "blocked":
            blocked_note = " Se uso investigacion directa del motor porque skill:investigar esta bloqueada."
        profile_summary = (
            f"Descubrimiento autonomo para '{topic}': {max(0, useful_source_total)} fuente(s) utiles "
            f"en {len(used_queries)} consulta(s).{blocked_note}"
        )
        if draft_payload.get("research_summary"):
            profile_summary += f" Resumen base: {draft_payload['research_summary']}"

        return {
            "queries": used_queries,
            "knowledge_assets": knowledge_assets,
            "useful_source_count": useful_source_total,
            "reviewed_sources": combined_sources,
            "summary": draft_payload.get("research_summary", ""),
            "findings": draft_payload.get("research_findings", ""),
            "profile_summary": profile_summary.strip(),
        }

    def _draft_research_queries(self, topic: str, family: str) -> List[str]:
        base = str(topic or "").strip()
        if not base:
            return []
        family_key = normalize_text(family)
        candidates = [base]
        if family_key == "game":
            candidates.extend(
                [
                    f"{base} controles basicos",
                    f"{base} primeros pasos",
                    f"{base} early game",
                ]
            )
        elif family_key == "research":
            candidates.extend(
                [
                    f"{base} fuentes confiables",
                    f"{base} paso a paso",
                    f"{base} resumen practico",
                ]
            )
        elif family_key == "browser":
            candidates.extend(
                [
                    f"{base} tutorial",
                    f"{base} flujo de trabajo",
                    f"{base} mejores practicas",
                ]
            )
        elif family_key == "documents":
            candidates.extend(
                [
                    f"{base} tutorial basico",
                    f"{base} guardado verificado",
                    f"{base} plantilla",
                ]
            )
        elif family_key == "file_manager":
            candidates.extend(
                [
                    f"{base} explorer windows",
                    f"{base} mover archivos",
                    f"{base} seleccion correcta",
                ]
            )
        else:
            candidates.extend(
                [
                    f"{base} tutorial",
                    f"{base} flujo de trabajo",
                    f"{base} guia practica",
                ]
            )

        ordered: List[str] = []
        for candidate in candidates:
            text = str(candidate).strip()
            if text and text not in ordered:
                ordered.append(text)
        return ordered

    def record_training_result(self, result: TrainingScenarioResult) -> None:
        self.history_store.append_training_result(result)
        target_profile = self.state.get("profiles", {}).get(result.skill_id)
        if target_profile is not None:
            self._reevaluate_profile(result.skill_id, target_profile)
            self._save_state()

    def reevaluate_skill(self, skill_id: str) -> Dict[str, Any]:
        profile = self.state.get("profiles", {}).get(skill_id)
        if not profile:
            raise KeyError(f"No existe perfil para {skill_id}")
        self._reevaluate_profile(skill_id, profile)
        self._save_state()
        return dict(profile)

    def _execute_supported_cycle(
        self,
        skill_id: str,
        level: int,
        mode: str,
        goal: str,
        requested_attempts: Optional[int],
        requested_minutes: Optional[int],
        create_document: bool,
        cycle_number: int,
    ) -> Dict[str, Any]:
        profile = self.state.get("profiles", {}).get(skill_id, {})
        template_kind = profile.get("template_kind", "")
        runner = self.domain_runners.get(template_kind)
        if runner is None:
            raise ValueError(f"Habilidad soportada desconocida: {skill_id}")
        return runner.run(
            self,
            profile=profile,
            level=level,
            mode=mode,
            goal=goal,
            requested_attempts=requested_attempts,
            requested_minutes=requested_minutes,
            create_document=create_document,
            cycle_number=cycle_number,
        )

    def _run_keyboard_cycle(
        self,
        level: int,
        mode: str,
        goal: str,
        requested_attempts: Optional[int],
        requested_minutes: Optional[int],
        cycle_number: int,
    ) -> Dict[str, Any]:
        samples = list(self._skill_settings("keyboard").get("sample_texts", [])) or [
            "raphel aprende rapido",
            "teclado visible y seguro",
        ]
        random.shuffle(samples)
        workspace = self.sessions_dir / f"keyboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        ensure_directory(workspace)
        cycle = self._empty_cycle(
            cycle_number=cycle_number,
            level=level,
            requested_attempts=requested_attempts,
            requested_minutes=requested_minutes,
        )
        stopped = False

        if self._external_stop_requested():
            stopped = self._mark_cycle_external_stop(cycle)
        elif level == 1:
            attempts = requested_attempts or int(self._skill_settings("keyboard").get("default_attempts_level_1", 8))
            prepared = self._prepare_plain_notepad_session(workspace / "keyboard_level1.txt")
            if not prepared:
                before = self._capture_context(refresh=True)
                reason = (
                    self._unexpected_modal_reason(before, expected_app="notepad")
                    or "No se pudo preparar un editor seguro de Notepad."
                )
                detail = self._failure_detail(
                    step="keyboard_prepare_notepad",
                    strategy="open_notepad_training_file",
                    verification="safe_editor_context",
                    before=before,
                    reason=reason,
                )
                cycle["steps"].append(detail)
                cycle["strategies_tried"].append(detail["strategy"])
                cycle["verifications"].append(detail["verification"])
                cycle["failures"] += 1
                cycle["context_failures"].append(reason)
                cycle["status"] = "retry"
                cycle["summary"] = "Teclado nivel 1: 0 verificados; el editor seguro no quedo listo."
                return cycle
            try:
                for index in range(attempts):
                    if self._external_stop_requested():
                        stopped = self._mark_cycle_external_stop(cycle)
                        break
                    text = samples[index % len(samples)]
                    success, detail = self._keyboard_write_and_verify(text)
                    cycle["steps"].append(detail)
                    cycle["strategies_tried"].append(detail.get("strategy", "direct_typing"))
                    cycle["verifications"].append(detail.get("verification", ""))
                    cycle["successes" if success else "failures"] += 1
                    cycle["verified_successes"] += int(success)
                    if detail.get("context_failure"):
                        cycle["context_failures"].append(detail["context_failure"])
                    failure_text = normalize_text(
                        f"{detail.get('context_failure', '')} {detail.get('reason', '')} {detail.get('verification', '')}"
                    )
                    if not success and any(token in failure_text for token in ("abrir", "open file", "apertura")):
                        break
            finally:
                self._finalize_plain_notepad_session()
        elif level == 2:
            workflows = [
                self._keyboard_explorer_open_workflow,
                self._keyboard_browser_address_focus_workflow,
                self._keyboard_explorer_search_workflow,
            ]
            random.shuffle(workflows)
            goal_hint = goal or "raphel teclado navegador"
            for workflow in workflows[: requested_attempts or int(self._skill_settings("keyboard").get("default_workflows_level_2", 3))]:
                if self._external_stop_requested():
                    stopped = self._mark_cycle_external_stop(cycle)
                    break
                success, detail = workflow(goal_hint, workspace)
                cycle["steps"].append(detail)
                cycle["strategies_tried"].append(detail.get("strategy", workflow.__name__))
                cycle["verifications"].append(detail.get("verification", ""))
                cycle["successes" if success else "failures"] += 1
                cycle["verified_successes"] += int(success)
                cycle["workflow_successes"] += int(success)
                if detail.get("context_failure"):
                    cycle["context_failures"].append(detail["context_failure"])
        elif level == 3:
            workflows = [
                self._keyboard_explorer_search_workflow,
                self._keyboard_explorer_rename_workflow,
                self._keyboard_notepad_save_workflow,
                self._keyboard_notepad_replace_workflow,
            ]
            random.shuffle(workflows)
            goal_hint = goal or "raphel teclado navegador"
            for workflow in workflows[: requested_attempts or int(self._skill_settings("keyboard").get("default_workflows_level_3", 3))]:
                if self._external_stop_requested():
                    stopped = self._mark_cycle_external_stop(cycle)
                    break
                success, detail = workflow(goal_hint, workspace)
                cycle["steps"].append(detail)
                cycle["strategies_tried"].append(detail.get("strategy", workflow.__name__))
                cycle["verifications"].append(detail.get("verification", ""))
                cycle["successes" if success else "failures"] += 1
                cycle["verified_successes"] += int(success)
                cycle["workflow_successes"] += int(success)
                if detail.get("context_failure"):
                    cycle["context_failures"].append(detail["context_failure"])
        elif level == 4:
            workflows = [
                self._keyboard_window_switch_workflow,
                self._keyboard_window_focus_workflow,
                self._keyboard_window_close_workflow,
                self._keyboard_minimize_all_workflow,
                self._keyboard_maximize_window_workflow,
            ]
            random.shuffle(workflows)
            goal_hint = goal or "raphel cambio de ventana"
            for workflow in workflows[: requested_attempts or int(self._skill_settings("keyboard").get("default_workflows_level_4", 3))]:
                if self._external_stop_requested():
                    stopped = self._mark_cycle_external_stop(cycle)
                    break
                success, detail = workflow(goal_hint, workspace)
                cycle["steps"].append(detail)
                cycle["strategies_tried"].append(detail.get("strategy", workflow.__name__))
                cycle["verifications"].append(detail.get("verification", ""))
                cycle["successes" if success else "failures"] += 1
                cycle["verified_successes"] += int(success)
                cycle["workflow_successes"] += int(success)
                if detail.get("context_failure"):
                    cycle["context_failures"].append(detail["context_failure"])
        else:
            if goal.strip():
                workflows = max(1, requested_attempts or int(self._skill_settings("keyboard").get("default_workflows_level_5", 2)))
                goal_options = self._keyboard_level_three_goals(goal)
                for index in range(workflows):
                    if self._external_stop_requested():
                        stopped = self._mark_cycle_external_stop(cycle)
                        break
                    if index > 0 and index % len(goal_options) == 0:
                        random.shuffle(goal_options)
                    training_goal = self._keyboard_training_goal_variant(
                        goal_options[index % len(goal_options)],
                        cycle_number=cycle_number,
                        attempt_number=index + 1,
                        fixed_goal=bool(goal.strip()),
                    )
                    success, detail = self._keyboard_goal_workflow(training_goal, workspace)
                    detail["training_goal"] = training_goal
                    cycle["steps"].append(detail)
                    cycle["strategies_tried"].append(detail.get("strategy", "goal_workflow"))
                    cycle["verifications"].append(detail.get("verification", ""))
                    cycle["successes" if success else "failures"] += 1
                    cycle["verified_successes"] += int(success)
                    cycle["workflow_successes"] += int(success)
                    if detail.get("context_failure"):
                        cycle["context_failures"].append(detail["context_failure"])
            else:
                workflows = [
                    self._keyboard_multiapp_workflow,
                    self._keyboard_window_switch_workflow,
                    self._keyboard_notepad_save_workflow,
                ]
                random.shuffle(workflows)
                goal_hint = "raphel workflow multiapp"
                for workflow in workflows[: requested_attempts or int(self._skill_settings("keyboard").get("default_workflows_level_5", 2))]:
                    if self._external_stop_requested():
                        stopped = self._mark_cycle_external_stop(cycle)
                        break
                    success, detail = workflow(goal_hint, workspace)
                    cycle["steps"].append(detail)
                    cycle["strategies_tried"].append(detail.get("strategy", workflow.__name__))
                    cycle["verifications"].append(detail.get("verification", ""))
                    cycle["successes" if success else "failures"] += 1
                    cycle["verified_successes"] += int(success)
                    cycle["workflow_successes"] += int(success)
                    if detail.get("context_failure"):
                        cycle["context_failures"].append(detail["context_failure"])

        total_attempts = cycle["successes"] + cycle["failures"]
        if stopped:
            cycle["status"] = "stopped"
            cycle["summary"] = (
                f"Teclado nivel {level}: detenido por solicitud externa con "
                f"{cycle['verified_successes']} verificados de {total_attempts} intento(s)."
            )
        else:
            cycle["status"] = "completed" if cycle["verified_successes"] > 0 else "retry"
            cycle["summary"] = (
                f"Teclado nivel {level}: {cycle['verified_successes']} verificados de "
                f"{total_attempts} intento(s)."
            )
        return cycle

    def _external_stop_requested(self) -> bool:
        checker = getattr(self.assistant, "input_training_stop_requested", None)
        if not callable(checker):
            return False
        try:
            return bool(checker())
        except Exception as exc:
            self._emit(f"No pude consultar parada externa del entrenamiento: {exc}", "warning")
            return False

    @staticmethod
    def _mark_cycle_external_stop(cycle: Dict[str, Any]) -> bool:
        reason = "Detenido por solicitud externa del entrenamiento continuo."
        if reason not in cycle["context_failures"]:
            cycle["context_failures"].append(reason)
        return True

    def _keyboard_level_three_goals(self, goal: str) -> List[str]:
        if goal.strip():
            return [goal.strip()]
        options = list(self._skill_settings("keyboard").get("level_3_goals", [])) or list(
            self.KEYBOARD_LEVEL3_GOALS
        )
        random.shuffle(options)
        return [str(item).strip() for item in options if str(item).strip()] or ["nota rapida de practica"]

    @staticmethod
    def _keyboard_training_goal_variant(
        base_goal: str,
        cycle_number: int,
        attempt_number: int,
        fixed_goal: bool = False,
    ) -> str:
        if fixed_goal:
            return base_goal
        token = random.randint(1000, 9999)
        suffixes = ("alfa", "beta", "gamma", "delta", "sigma", "omega")
        suffix = random.choice(suffixes)
        return f"{base_goal} {suffix}-{cycle_number}-{attempt_number}-{token}"

    def _run_youtube_cycle(
        self,
        level: int,
        mode: str,
        goal: str,
        requested_attempts: Optional[int],
        requested_minutes: Optional[int],
        cycle_number: int,
    ) -> Dict[str, Any]:
        settings = self._skill_settings("youtube")
        queries = list(settings.get("sample_queries", [])) or ["rimuru tempest resumen"]
        cycle = self._empty_cycle(
            cycle_number=cycle_number,
            level=level,
            requested_attempts=requested_attempts,
            requested_minutes=requested_minutes,
        )
        if level == 1:
            attempts = requested_attempts or int(settings.get("default_attempts_level_1", 6))
            for index in range(attempts):
                query = goal or queries[index % len(queries)]
                success, detail = self._youtube_search_attempt(query)
                cycle["steps"].append(detail)
                cycle["strategies_tried"].append(detail.get("strategy", "youtube_search"))
                cycle["verifications"].append(detail.get("verification", ""))
                cycle["successes" if success else "failures"] += 1
                cycle["verified_successes"] += int(success)
        elif level == 2:
            workflows = max(1, requested_attempts or int(settings.get("default_workflows_level_2", 3)))
            for index in range(workflows):
                query = goal or queries[index % len(queries)]
                success, detail = self._youtube_open_result_attempt(query)
                cycle["steps"].append(detail)
                cycle["strategies_tried"].append(detail.get("strategy", "tab_navigation"))
                cycle["verifications"].append(detail.get("verification", ""))
                cycle["successes" if success else "failures"] += 1
                cycle["verified_successes"] += int(success)
                cycle["workflow_successes"] += int(success)
        else:
            workflows = max(1, requested_attempts or int(settings.get("default_workflows_level_3", 2)))
            for _ in range(workflows):
                success, detail = self._youtube_goal_workflow(goal or queries[0])
                cycle["steps"].append(detail)
                cycle["strategies_tried"].append(detail.get("strategy", "goal_query"))
                cycle["verifications"].append(detail.get("verification", ""))
                cycle["successes" if success else "failures"] += 1
                cycle["verified_successes"] += int(success)
                cycle["workflow_successes"] += int(success)

        cycle["status"] = "completed" if cycle["verified_successes"] > 0 else "retry"
        cycle["summary"] = (
            f"YouTube nivel {level}: {cycle['verified_successes']} verificados de "
            f"{cycle['successes'] + cycle['failures']} intento(s)."
        )
        return cycle

    def _run_research_cycle(
        self,
        level: int,
        mode: str,
        goal: str,
        requested_attempts: Optional[int],
        requested_minutes: Optional[int],
        create_document: bool,
        cycle_number: int,
    ) -> Dict[str, Any]:
        settings = self._skill_settings("research")
        research_profile = self.state.get("profiles", {}).get("skill:investigar", {})
        exp_level = int(research_profile.get("exponential_level", 0) or 0)
        variation_seed = self._next_research_variation_seed(research_profile)
        topic = self._choose_research_topic(
            requested_goal=goal,
            level=level,
            exp_level=exp_level,
            cycle_number=variation_seed,
        )
        challenge = self._build_research_challenge(
            topic=topic,
            level=level,
            exp_level=exp_level,
            cycle_number=variation_seed,
        )
        cycle = self._empty_cycle(
            cycle_number=cycle_number,
            level=level,
            requested_attempts=requested_attempts,
            requested_minutes=requested_minutes,
        )
        cycle["challenge"] = challenge
        if level == 1:
            variants = challenge["query_variants"]
            attempts = requested_attempts or int(settings.get("default_attempts_level_1", 4))
            result_indices = self._expand_research_result_indices(
                challenge["result_indices"],
                max_candidates=max(3, attempts),
            )
            cycle["challenge"]["result_indices"] = list(result_indices)
            for index in range(attempts):
                query = variants[index % len(variants)]
                result_index = result_indices[index % len(result_indices)]
                success, detail = self._research_query_attempt(query, result_index=result_index)
                cycle["steps"].append(detail)
                cycle["strategies_tried"].append(detail.get("strategy", "query_variant"))
                cycle["verifications"].append(detail.get("verification", ""))
                cycle["successes" if success else "failures"] += 1
                cycle["verified_successes"] += int(success)
                if detail.get("context_failure"):
                    cycle["context_failures"].append(detail["context_failure"])
        elif level == 2:
            workflows = max(1, requested_attempts or int(settings.get("default_workflows_level_2", 2)))
            for _ in range(workflows):
                success, detail = self._research_summary_attempt(
                    topic,
                    query_variants=challenge["query_variants"],
                    result_indices=challenge["result_indices"],
                )
                cycle["steps"].append(detail)
                cycle["strategies_tried"].append(detail.get("strategy", "perform_research"))
                cycle["verifications"].append(detail.get("verification", ""))
                cycle["successes" if success else "failures"] += 1
                cycle["verified_successes"] += int(success)
                cycle["workflow_successes"] += int(success)
                if detail.get("context_failure"):
                    cycle["context_failures"].append(detail["context_failure"])
        else:
            workflows = max(1, requested_attempts or int(settings.get("default_workflows_level_3", 1)))
            for _ in range(workflows):
                success, detail = self._research_goal_workflow(
                    topic,
                    create_document=create_document,
                    query_variants=challenge["query_variants"],
                    result_indices=challenge["result_indices"],
                )
                if level == 4:
                    detail["step"] = "research_cross_verify_workflow"
                    detail.setdefault("evidence", {}).setdefault(
                        "equivalent_scenarios",
                        ["research_to_document", "research_cross_verify"],
                    )
                elif level >= 5:
                    detail["step"] = "research_adversarial_recovery"
                    detail.setdefault("evidence", {}).setdefault(
                        "equivalent_scenarios",
                        [
                            "research_to_document",
                            "research_cross_verify",
                            "research_adversarial_recovery",
                            "research_autonomous_discovery",
                        ],
                    )
                cycle["steps"].append(detail)
                cycle["strategies_tried"].append(detail.get("strategy", "goal_research"))
                cycle["verifications"].append(detail.get("verification", ""))
                cycle["successes" if success else "failures"] += 1
                cycle["verified_successes"] += int(success)
                cycle["workflow_successes"] += int(success)
                if detail.get("context_failure"):
                    cycle["context_failures"].append(detail["context_failure"])

        tab_cleanup = self._rotate_research_browser_tab_for_next_cycle()
        cycle["browser_tab_cleanup"] = tab_cleanup
        if tab_cleanup.get("context_failure") and not tab_cleanup.get("skipped"):
            cycle["context_failures"].append(tab_cleanup["context_failure"])
        cycle["status"] = "completed" if cycle["verified_successes"] > 0 else "retry"
        cycle["summary"] = (
            f"Investigar nivel {level}: {cycle['verified_successes']} verificados de "
            f"{cycle['successes'] + cycle['failures']} intento(s)."
        )
        return cycle

    @staticmethod
    def _next_research_variation_seed(profile: Dict[str, Any]) -> int:
        current = int(profile.get("research_variation_seed", 0) or 0)
        next_value = current + 1
        profile["research_variation_seed"] = next_value
        return next_value

    def _run_mouse_control_cycle(
        self,
        level: int,
        mode: str,
        goal: str,
        requested_attempts: Optional[int],
        requested_minutes: Optional[int],
        cycle_number: int,
    ) -> Dict[str, Any]:
        cycle = self._empty_cycle(
            cycle_number=cycle_number,
            level=level,
            requested_attempts=requested_attempts,
            requested_minutes=requested_minutes,
        )

        organizer = getattr(self.assistant, "desktop_learning_organizer", None)
        if organizer is None:
            legacy_summary = self._legacy_mouse_data_summary()
            cycle["status"] = "retry"
            cycle["context_failures"].append("No hay entrenador de escritorio conectado para mouse.")
            cycle["summary"] = (
                f"Mouse nivel {level}: historial detectado "
                f"({legacy_summary['successes']} exitos, {legacy_summary['failures']} fallos), "
                "pero falta conectar DesktopLearningOrganizer."
            )
            return cycle

        steps = self._mouse_training_steps_for(level, goal, mode)
        if not steps:
            cycle["status"] = "retry"
            cycle["summary"] = f"Mouse nivel {level}: no hay pasos de entrenamiento configurados."
            return cycle

        attempts_per_step = self._mouse_attempt_budget_for_step(requested_attempts, len(steps))
        step_summaries: List[str] = []
        for metric_key, method_name, label in steps:
            method = getattr(organizer, method_name, None)
            if not callable(method):
                cycle["context_failures"].append(f"Entrenador sin metodo {method_name}.")
                continue

            self._emit(f"Mouse nivel {level}: practicando {label}.", "info")
            try:
                result_text = method(attempts=attempts_per_step)
            except TypeError:
                result_text = method(attempts_per_step)
            except Exception as exc:
                cycle["failures"] += 1
                cycle["context_failures"].append(f"{label}: {exc}")
                step_summaries.append(f"{label}: error")
                continue

            metric = self._mouse_practice_metric(self._read_mouse_strategy(), metric_key)
            if not metric:
                cycle["context_failures"].append(f"{label}: no encontre resumen verificable.")
                step_summaries.append(f"{label}: sin resumen")
                continue

            successes = int(metric.get("successes", 0))
            failures = int(metric.get("failures", 0))
            cycle["successes"] += successes
            cycle["failures"] += failures
            cycle["verified_successes"] += successes
            if metric.get("workflow_success"):
                cycle["workflow_successes"] += successes
            cycle["steps"].append(
                {
                    "skill": metric_key,
                    "method": method_name,
                    "attempts": metric.get("attempts", successes + failures),
                    "successes": successes,
                    "failures": failures,
                    "success_rate": metric.get("success_rate", 0.0),
                    "session_id": metric.get("session_id", ""),
                    "reliable": bool(metric.get("reliable")),
                }
            )
            cycle["strategies_tried"].append(method_name)
            if metric.get("session_id"):
                cycle["verifications"].append(str(metric["session_id"]))
            compact_result = str(result_text).split(" Manifiesto:", 1)[0].strip()
            if compact_result:
                cycle.setdefault("evidence", []).append(compact_result)
            step_summaries.append(f"{label}: {successes}/{successes + failures} ok")

        legacy_summary = self._legacy_mouse_data_summary()
        if legacy_summary.get("best_strategy"):
            cycle["strategies_tried"].append(str(legacy_summary["best_strategy"]))
        total = cycle["successes"] + cycle["failures"]
        success_rate = cycle["successes"] / total if total else 0.0
        cycle["status"] = "completed" if cycle["verified_successes"] > 0 else "retry"
        cycle["summary"] = (
            f"Mouse nivel {level}: entrenador de escritorio ejecutado | "
            f"{cycle['successes']} exitos + {cycle['failures']} fallos "
            f"(tasa: {success_rate:.1%}) | pasos: {', '.join(step_summaries)}"
        )
        return cycle

    def _run_visual_perception_cycle(
        self,
        level: int,
        mode: str,
        goal: str,
        requested_attempts: Optional[int],
        requested_minutes: Optional[int],
        cycle_number: int,
    ) -> Dict[str, Any]:
        cycle = self._empty_cycle(
            cycle_number=cycle_number,
            level=level,
            requested_attempts=requested_attempts,
            requested_minutes=requested_minutes,
        )
        scenario_id = self._visual_scenario_for(level, goal, mode)
        attempts = self._visual_attempt_budget(level, requested_attempts, requested_minutes)
        step_summaries: List[str] = []
        for attempt_index in range(attempts):
            step = self._run_visual_scenario_attempt(
                scenario_id=scenario_id,
                level=level,
                attempt_index=attempt_index,
            )
            cycle["steps"].append(step)
            strategy = str(step.get("strategy") or "")
            if strategy:
                cycle["strategies_tried"].append(strategy)
            if step.get("success"):
                cycle["successes"] += 1
            else:
                cycle["failures"] += 1
            if step.get("verified"):
                cycle["verified_successes"] += 1
                if scenario_id in {"visual_scene_transition", "visual_workflow_precondition", "visual_adversarial_recovery"}:
                    cycle["workflow_successes"] += 1
            marker = str(step.get("session_marker") or f"{scenario_id}:{attempt_index + 1}")
            cycle["verifications"].append(marker)
            label = "ok" if step.get("verified") else ("parcial" if step.get("success") else "fallo")
            step_summaries.append(f"{scenario_id}:{label}")

        total = cycle["successes"] + cycle["failures"]
        success_rate = cycle["successes"] / total if total else 0.0
        cycle["status"] = "completed" if cycle["verified_successes"] > 0 else "retry"
        cycle["summary"] = (
            f"Visualizacion nivel {level}: {scenario_id} | "
            f"{cycle['verified_successes']} verificados de {total} intento(s) "
            f"(tasa bruta: {success_rate:.1%}) | pasos: {', '.join(step_summaries)}"
        )
        return cycle

    def _visual_scenario_for(self, level: int, goal: str, mode: str) -> str:
        normalized_goal = normalize_text(goal)
        if any(token in normalized_goal for token in ("vista de contexto", "contexto visual", "contexto", "escena")):
            return "visual_context_identity"
        if any(token in normalized_goal for token in ("reencontrar", "reacquire", "reacquirir", "deteccion", "detectar")):
            return "visual_target_reacquire"
        if any(token in normalized_goal for token in ("transicion", "transicionar", "cambio de escena")):
            return "visual_scene_transition"
        if any(token in normalized_goal for token in ("precondicion", "precondiciones", "workflow")):
            return "visual_workflow_precondition"
        if any(token in normalized_goal for token in ("adversarial", "recovery", "recuperacion")):
            return "visual_adversarial_recovery"
        scenario_by_level = {
            1: "visual_context_identity",
            2: "visual_target_reacquire",
            3: "visual_scene_transition",
            4: "visual_workflow_precondition",
            5: "visual_adversarial_recovery",
        }
        return scenario_by_level.get(max(1, min(self.MAX_SKILL_LEVEL, int(level or 1))), "visual_context_identity")

    def _visual_attempt_budget(
        self,
        level: int,
        requested_attempts: Optional[int],
        requested_minutes: Optional[int],
    ) -> int:
        settings = self._skill_settings("visualization")
        safe_level = max(1, min(self.MAX_SKILL_LEVEL, int(level or 1)))
        default_attempts = int(settings.get(f"default_attempts_level_{safe_level}", 2) or 2)
        attempts = max(1, int(requested_attempts or default_attempts))
        if requested_minutes:
            attempts = max(attempts, min(20, int(requested_minutes) * 2))
        return min(20, attempts)

    def _run_visual_scenario_attempt(
        self,
        scenario_id: str,
        level: int,
        attempt_index: int,
    ) -> Dict[str, Any]:
        before = self._capture_perception_bundle(refresh=True)
        if before is None:
            return {
                "step": scenario_id,
                "scenario_id": scenario_id,
                "skill": "visualizacion",
                "strategy": "observe_snapshot",
                "verification": scenario_id,
                "success": False,
                "verified": False,
                "failure_stage": "no_perception",
                "failure_reason": "No pude capturar un bundle de percepcion.",
                "captured_chars": 0,
                "evidence": {
                    "base_scenario_id": scenario_id,
                    "verification_source": "none",
                },
                "session_marker": f"{scenario_id}:{attempt_index + 1}:empty",
            }

        before_payload = before.to_dict()
        selected_before = self._selected_target_payload(before_payload)
        evidence = {
            "base_scenario_id": scenario_id,
            "initial_scene_kind": before_payload.get("scene_kind", ""),
            "scene_kind": before_payload.get("scene_kind", ""),
            "confidence": float(before_payload.get("confidence", 0.0) or 0.0),
            "selected_target_id": before_payload.get("selected_target_id"),
            "selected_target_confidence": float((selected_before or {}).get("confidence", 0.0) or 0.0),
            "selected_target_role": str((selected_before or {}).get("semantic_role", "") or ""),
            "actable_target_count": int(before_payload.get("evidence", {}).get("actable_target_count", 0) or 0),
            "blocking_reason": str(before_payload.get("blocking_reason", "") or ""),
            "ocr_only": self._observation_is_ocr_only(before_payload),
            "verification_source": "perception_bundle",
        }
        success = False
        verified = False
        strategy = "observe_snapshot"

        if scenario_id == "visual_context_identity":
            success = bool(
                before_payload.get("scene_kind") not in {"", "unknown"}
                and before_payload.get("selected_target_id")
            )
            verification = self.visual_verifier.verify(
                TrainingScenarioResult(
                    skill_id="skill:visualizacion",
                    domain="perception",
                    scenario_id=scenario_id,
                    level=level,
                    status="success" if success else "failure",
                    verified=success,
                    evidence=evidence,
                )
            )
            verified = bool(verification.get("context_identity_verified"))
            evidence.update(verification.get("verified_outcome", {}))
        elif scenario_id == "visual_target_reacquire":
            strategy = "observe_reacquire"
            after = self._capture_perception_bundle(refresh=True)
            after_payload = after.to_dict() if after is not None else {}
            reacquire = self._evaluate_reacquire(before, after)
            evidence.update(
                {
                    "final_scene_kind": str(after_payload.get("scene_kind", "") or before_payload.get("scene_kind", "")),
                    "reacquire": reacquire,
                    "selected_target_id": before_payload.get("selected_target_id") or after_payload.get("selected_target_id"),
                }
            )
            success = bool(reacquire.get("matched"))
            verification = self.visual_verifier.verify(
                TrainingScenarioResult(
                    skill_id="skill:visualizacion",
                    domain="perception",
                    scenario_id=scenario_id,
                    level=level,
                    status="success" if success else "failure",
                    verified=success,
                    evidence=evidence,
                )
            )
            verified = bool(verification.get("target_reacquire_verified"))
            evidence.update(verification.get("verified_outcome", {}))
        elif scenario_id == "visual_scene_transition":
            strategy = self._induce_visual_transition(str(before_payload.get("scene_kind", "") or ""))
            self.sleep(float(self._skill_settings("visualization").get("observation_pause_seconds", 0.12) or 0.12))
            after = self._capture_perception_bundle(refresh=True)
            after_payload = after.to_dict() if after is not None else {}
            success = bool(
                strategy
                and after_payload
                and str(after_payload.get("scene_kind", "") or "") not in {"", "unknown"}
                and str(after_payload.get("scene_kind", "") or "") != str(before_payload.get("scene_kind", "") or "")
            )
            evidence.update(
                {
                    "final_scene_kind": str(after_payload.get("scene_kind", "") or ""),
                    "transition_strategy": strategy,
                }
            )
            verification = self.visual_verifier.verify(
                TrainingScenarioResult(
                    skill_id="skill:visualizacion",
                    domain="perception",
                    scenario_id=scenario_id,
                    level=level,
                    status="success" if success else "failure",
                    verified=success,
                    evidence=evidence,
                )
            )
            verified = bool(verification.get("scene_transition_verified"))
            evidence.update(verification.get("verified_outcome", {}))
        elif scenario_id == "visual_workflow_precondition":
            selected_confidence = float(evidence.get("selected_target_confidence", 0.0) or 0.0)
            precondition_ready = bool(
                before_payload.get("scene_kind") not in {"", "unknown", "browser_serp"}
                and before_payload.get("selected_target_id")
                and selected_confidence >= 0.70
                and not before_payload.get("blocking_reason")
                and str((selected_before or {}).get("verification_role", "") or "")
            )
            evidence.update(
                {
                    "precondition_ready": precondition_ready,
                    "verification_role": str((selected_before or {}).get("verification_role", "") or ""),
                }
            )
            success = precondition_ready
            verification = self.visual_verifier.verify(
                TrainingScenarioResult(
                    skill_id="skill:visualizacion",
                    domain="perception",
                    scenario_id=scenario_id,
                    level=level,
                    status="success" if success else "failure",
                    verified=success,
                    evidence=evidence,
                )
            )
            verified = bool(verification.get("workflow_precondition_verified"))
            evidence.update(verification.get("verified_outcome", {}))
        else:
            initial_blocked = bool(
                before_payload.get("blocking_reason")
                or before_payload.get("scene_kind") in {"", "unknown"}
                or not before_payload.get("selected_target_id")
                or float(before_payload.get("confidence", 0.0) or 0.0) < 0.70
            )
            strategy = self._induce_visual_transition(str(before_payload.get("scene_kind", "") or ""))
            self.sleep(float(self._skill_settings("visualization").get("observation_pause_seconds", 0.12) or 0.12))
            after = self._capture_perception_bundle(refresh=True)
            after_payload = after.to_dict() if after is not None else {}
            recovery_target = self._selected_target_payload(after_payload)
            recovered = bool(
                initial_blocked
                and after_payload
                and str(after_payload.get("scene_kind", "") or "") not in {"", "unknown"}
                and after_payload.get("selected_target_id")
                and not after_payload.get("blocking_reason")
                and float(after_payload.get("confidence", 0.0) or 0.0) >= 0.70
            )
            evidence.update(
                {
                    "initial_blocked": initial_blocked,
                    "recovered": recovered,
                    "final_scene_kind": str(after_payload.get("scene_kind", "") or ""),
                    "recovery_target_confidence": float((recovery_target or {}).get("confidence", 0.0) or 0.0),
                    "transition_strategy": strategy,
                }
            )
            success = recovered
            verification = self.visual_verifier.verify(
                TrainingScenarioResult(
                    skill_id="skill:visualizacion",
                    domain="perception",
                    scenario_id=scenario_id,
                    level=level,
                    status="success" if success else "failure",
                    verified=success,
                    evidence=evidence,
                )
            )
            verified = bool(verification.get("adversarial_recovery_verified"))
            evidence.update(verification.get("verified_outcome", {}))

        return {
            "step": scenario_id,
            "scenario_id": scenario_id,
            "skill": "visualizacion",
            "strategy": strategy or "observe_snapshot",
            "verification": scenario_id,
            "success": success,
            "verified": verified,
            "captured_chars": 0,
            "failure_stage": "" if verified else str(evidence.get("blocking_reason") or scenario_id),
            "context_failure": "" if verified else str(evidence.get("blocking_reason") or ""),
            "evidence": evidence,
            "session_marker": f"{scenario_id}:{attempt_index + 1}:{before_payload.get('selected_target_id', '')}",
        }

    def _capture_perception_bundle(self, refresh: bool = False) -> Optional[Any]:
        getter = getattr(self.assistant, "get_latest_perception", None)
        if callable(getter):
            bundle = getter(refresh=refresh)
            if bundle is not None:
                return bundle
        snapshot_getter = getattr(self.assistant, "get_latest_vision_snapshot", None)
        snapshot = snapshot_getter(refresh=refresh) if callable(snapshot_getter) else None
        perception = getattr(self.assistant, "perception", None)
        observe_snapshot = getattr(perception, "observe_snapshot", None)
        if callable(observe_snapshot) and snapshot is not None:
            return observe_snapshot(snapshot)
        return None

    @staticmethod
    def _selected_target_payload(bundle_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        selected_target_id = str(bundle_payload.get("selected_target_id") or "")
        for target in bundle_payload.get("targets", []):
            if str(target.get("target_id") or "") == selected_target_id:
                return target
        return None

    @staticmethod
    def _observation_is_ocr_only(bundle_payload: Dict[str, Any]) -> bool:
        has_text = bool(str(bundle_payload.get("ocr_text", "") or "").strip())
        targets = bundle_payload.get("targets", [])
        return has_text and not targets

    def _evaluate_reacquire(self, before: Any, after: Optional[Any]) -> Dict[str, Any]:
        if before is None or after is None:
            return {
                "matched": False,
                "reason": "missing_observation",
            }
        perception = getattr(self.assistant, "perception", None)
        evaluator = getattr(perception, "evaluate_target_reacquire", None)
        if callable(evaluator):
            return evaluator(before, after)
        return {"matched": False, "reason": "missing_reacquire_evaluator"}

    def _induce_visual_transition(self, initial_scene_kind: str) -> str:
        scene_kind = normalize_text(initial_scene_kind)
        ensure_browser = getattr(self.assistant, "ensure_browser", None)
        open_folder = getattr(self.assistant, "open_folder", None)
        open_application = getattr(self.assistant, "open_application", None)
        if scene_kind == "browser_serp" and callable(ensure_browser):
            ensure_browser(browser="brave", site="youtube", private=False)
            return "ensure_browser:youtube"
        if scene_kind in {"youtube_results", "youtube_watch"} and callable(ensure_browser):
            ensure_browser(browser="brave", site="google", private=False)
            return "ensure_browser:google"
        if scene_kind == "explorer" and callable(ensure_browser):
            ensure_browser(browser="brave", site="google", private=False)
            return "explorer_to_browser"
        if callable(open_folder):
            open_folder("Desktop")
            return "open_folder:desktop"
        if callable(open_application):
            open_application("brave")
            return "open_application:brave"
        return "observe_only"

    def _run_window_management_cycle(
        self,
        level: int,
        mode: str,
        goal: str,
        requested_attempts: Optional[int],
        requested_minutes: Optional[int],
        cycle_number: int,
    ) -> Dict[str, Any]:
        cycle = self._empty_cycle(
            cycle_number=cycle_number,
            level=level,
            requested_attempts=requested_attempts,
            requested_minutes=requested_minutes,
        )

        organizer = getattr(self.assistant, "desktop_learning_organizer", None)
        if organizer is None:
            cycle["status"] = "retry"
            cycle["context_failures"].append("No hay DesktopLearningOrganizer para entrenar ventanas.")
            cycle["summary"] = (
                f"Window management nivel {level}: falta el organizador de escritorio para practicar layout real."
            )
            return cycle

        runs = max(1, int(requested_attempts or self.WINDOW_MANAGEMENT_LEVEL_RUNS.get(level, 1)))
        attempts_per_run = max(
            2,
            int(
                self._skill_settings("window_management").get(
                    "workflow_attempts_per_run",
                    min(6, max(3, level + 2)),
                )
            ),
        )
        step_summaries: List[str] = []

        for run_index in range(runs):
            before_summary = self._window_management_data_summary()
            self._request_window_management_training_mode()
            self._emit(
                (
                    f"Window management nivel {level}: practica {run_index + 1}/{runs} "
                    "con layout estricto de Explorer."
                ),
                "info",
            )
            try:
                result_text = organizer.practice_mouse_workflow(attempts=attempts_per_run)
            except Exception as exc:
                cycle["failures"] += 1
                cycle["context_failures"].append(f"workflow ventanas: {exc}")
                step_summaries.append("layout: error")
                continue

            after_summary = self._window_management_data_summary()
            workflow_delta = max(0, after_summary["workflow_successes"] - before_summary["workflow_successes"])
            repair_delta = max(0, after_summary["repair_successes"] - before_summary["repair_successes"])
            split_delta = max(
                0,
                after_summary["successful_split_layouts"] - before_summary["successful_split_layouts"],
            )
            verified = bool(
                after_summary["strict_split_enabled"]
                and after_summary["workflow_reliable"]
                and (workflow_delta > 0 or repair_delta > 0 or split_delta > 0)
            )
            reason = (
                "layout estricto activo con workflow verificado"
                if verified
                else "No vi evidencia suficiente de layout estable y verificado en esta vuelta."
            )
            detail = {
                "step": "window_management_workflow",
                "strategy": "strict_split_explorer_halves",
                "verification": "window_layout_and_workflow",
                "success": verified,
                "failure_stage": "" if verified else "window_layout",
                "reason": reason,
                "captured_chars": 0,
                "evidence": {
                    "current_session_verified": verified,
                    "strict_split_enabled": after_summary["strict_split_enabled"],
                    "workflow_reliable": after_summary["workflow_reliable"],
                    "workflow_successes_delta": workflow_delta,
                    "repair_successes_delta": repair_delta,
                    "successful_split_layouts_delta": split_delta,
                    "before_summary": before_summary,
                    "after_summary": after_summary,
                    "raw_result": str(result_text),
                },
            }
            cycle["steps"].append(detail)
            cycle["strategies_tried"].append("strict_split_explorer_halves")
            if after_summary.get("workflow_session_id"):
                cycle["verifications"].append(str(after_summary["workflow_session_id"]))
            cycle["successes" if verified else "failures"] += 1
            cycle["verified_successes"] += int(verified)
            cycle["workflow_successes"] += int(verified)
            step_summaries.append(
                (
                    f"layout estricto ok"
                    if verified
                    else "layout aun inestable"
                )
            )

        total = cycle["successes"] + cycle["failures"]
        success_rate = cycle["successes"] / total if total else 0.0
        cycle["status"] = "completed" if cycle["verified_successes"] > 0 else "retry"
        cycle["summary"] = (
            f"Window management nivel {level}: {cycle['successes']} exitos + {cycle['failures']} fallos "
            f"(tasa: {success_rate:.1%}) | pasos: {', '.join(step_summaries) or 'sin evidencia'}"
        )
        return cycle

    def _run_game_foundation_cycle(
        self,
        game_name: str,
        level: int,
        mode: str,
        goal: str,
        requested_attempts: Optional[int],
        requested_minutes: Optional[int],
        cycle_number: int,
    ) -> Dict[str, Any]:
        display_game = self._display_game_name(game_name)
        topic = goal or f"{display_game} controles basicos"
        cycle = self._empty_cycle(
            cycle_number=cycle_number,
            level=level,
            requested_attempts=requested_attempts,
            requested_minutes=requested_minutes,
        )
        sub_attempts = self._game_foundation_attempt_budget(requested_attempts)

        subcycles: List[Tuple[str, Dict[str, Any]]] = []

        def add_subcycle(label: str, runner: Callable[[], Dict[str, Any]]) -> None:
            try:
                subcycles.append((label, runner()))
            except Exception as exc:
                subcycles.append(
                    (
                        label,
                        self._game_foundation_failure_cycle(
                            label=label,
                            reason=str(exc),
                            level=level,
                            requested_attempts=sub_attempts,
                            requested_minutes=requested_minutes,
                            cycle_number=cycle_number,
                        ),
                    )
                )

        keyboard_level = 1 if level <= 1 else min(self.MAX_SKILL_LEVEL, level)
        add_subcycle(
            "teclado",
            lambda: self._run_keyboard_cycle(
                    level=keyboard_level,
                    mode="practice",
                    goal=f"{display_game} controles basicos",
                    requested_attempts=sub_attempts,
                    requested_minutes=requested_minutes,
                    cycle_number=cycle_number,
                ),
        )
        add_subcycle(
            "mouse",
            lambda: self._run_mouse_control_cycle(
                    level=min(self.MAX_SKILL_LEVEL, max(1, level)),
                    mode="practice",
                    goal="flujo completo seguro",
                    requested_attempts=sub_attempts,
                    requested_minutes=requested_minutes,
                    cycle_number=cycle_number,
                ),
        )
        if level >= 2 or any(token in normalize_text(topic) for token in ("control", "guia", "wiki")):
            add_subcycle(
                "investigacion",
                lambda: self._run_research_cycle(
                        level=1,
                        mode="practice",
                        goal=f"{display_game} controles basicos",
                        requested_attempts=1,
                        requested_minutes=1,
                        create_document=False,
                        cycle_number=cycle_number,
                    ),
            )

        summaries: List[str] = []
        for label, subcycle in subcycles:
            self._merge_game_foundation_subcycle(cycle, label, subcycle)
            summary = str(subcycle.get("summary", "")).strip()
            if summary:
                summaries.append(f"{label}: {summary}")

        profile = self.state.get("profiles", {}).get(f"jugar_{game_name}", {})
        if profile:
            profile["last_decomposition"] = self._game_skill_decomposition(display_game)
            profile["last_investigation_summary"] = (
                f"Base compuesta para jugar {display_game}: se entrenan teclado, mouse y, "
                "cuando aplica, busqueda de controles. No se lanza ni controla el juego real todavia."
            )
            profile["game_backend_ready"] = False

        total = cycle["successes"] + cycle["failures"]
        success_rate = cycle["successes"] / total if total else 0.0
        cycle["status"] = "completed" if cycle["verified_successes"] > 0 else "retry"
        cycle["summary"] = (
            f"Juego {display_game} nivel {level}: base entrenada con teclado+mouse | "
            f"{cycle['successes']} exitos + {cycle['failures']} fallos "
            f"(tasa: {success_rate:.1%}). "
            "Backend especifico del juego pendiente; no se afirmo dominio real del juego."
        )
        if summaries:
            cycle["evidence"] = summaries[:4]
        return cycle

    def _merge_game_foundation_subcycle(
        self,
        target: Dict[str, Any],
        label: str,
        subcycle: Dict[str, Any],
    ) -> None:
        target["successes"] += int(subcycle.get("successes", 0))
        target["failures"] += int(subcycle.get("failures", 0))
        target["verified_successes"] += int(subcycle.get("verified_successes", 0))
        target["workflow_successes"] += int(subcycle.get("workflow_successes", 0))
        target["context_failures"].extend(str(item) for item in subcycle.get("context_failures", []))
        target["strategies_tried"].extend(
            f"{label}:{item}" for item in subcycle.get("strategies_tried", [])
        )
        target["verifications"].extend(
            f"{label}:{item}" for item in subcycle.get("verifications", [])
        )
        target["steps"].append(
            {
                "skill": label,
                "success": int(subcycle.get("verified_successes", 0)) > 0,
                "status": subcycle.get("status", "retry"),
                "summary": subcycle.get("summary", ""),
                "successes": subcycle.get("successes", 0),
                "failures": subcycle.get("failures", 0),
                "verified_successes": subcycle.get("verified_successes", 0),
                "workflow_successes": subcycle.get("workflow_successes", 0),
                "substeps": subcycle.get("steps", [])[:6],
            }
        )

    def _game_foundation_failure_cycle(
        self,
        label: str,
        reason: str,
        level: int,
        requested_attempts: Optional[int],
        requested_minutes: Optional[int],
        cycle_number: int,
    ) -> Dict[str, Any]:
        cycle = self._empty_cycle(
            cycle_number=cycle_number,
            level=level,
            requested_attempts=requested_attempts,
            requested_minutes=requested_minutes,
        )
        cycle["status"] = "retry"
        cycle["failures"] = 1
        cycle["context_failures"].append(reason)
        cycle["summary"] = f"Subhabilidad {label}: no se pudo ejecutar ({reason})."
        cycle["steps"].append(
            {
                "skill": label,
                "success": False,
                "status": "retry",
                "reason": reason,
            }
        )
        return cycle

    @staticmethod
    def _game_foundation_attempt_budget(requested_attempts: Optional[int]) -> Optional[int]:
        if requested_attempts is None:
            return None
        return max(1, min(20, int(requested_attempts) // 2 or 1))

    def _mouse_training_steps_for(
        self,
        level: int,
        goal: str,
        mode: str,
    ) -> Tuple[Tuple[str, str, str], ...]:
        normalized_goal = normalize_text(goal)
        if "doble" in normalized_goal and "click" in normalized_goal:
            return (("double_click", "practice_mouse_double_click", "doble click"),)
        if "derecho" in normalized_goal and "click" in normalized_goal:
            return (("right_click", "practice_mouse_right_click", "click derecho"),)
        if "click" in normalized_goal or "clic" in normalized_goal:
            return (("click", "practice_mouse_click", "click simple"),)
        if any(token in normalized_goal for token in ("mover", "movimiento", "puntero")):
            return (("movement", "practice_mouse_movement", "movimiento basico"),)
        if any(token in normalized_goal for token in ("drag", "arrastre", "arrastrar")):
            return (("drag", "practice_mouse", "drag seguro"),)
        safe_level = max(1, min(self.MAX_SKILL_LEVEL, int(level)))
        return self.MOUSE_TRAINING_STEPS.get(safe_level, self.MOUSE_TRAINING_STEPS[1])

    @staticmethod
    def _mouse_attempt_budget_for_step(requested_attempts: Optional[int], step_count: int) -> Optional[int]:
        if requested_attempts is None:
            return None
        return max(1, int(requested_attempts) // max(1, step_count))

    def _write_mouse_strategy(self, payload: Dict[str, Any]) -> None:
        self.history_store.write_mouse_strategy(payload)

    def _read_mouse_strategy(self) -> Dict[str, Any]:
        return self.history_store.read_mouse_strategy()

    def _request_window_management_training_mode(self) -> Dict[str, Any]:
        payload = self._read_mouse_strategy()
        window_management = payload.setdefault("window_management", {})
        window_management.setdefault("repair_attempts", 0)
        window_management.setdefault("repair_successes", 0)
        window_management.setdefault("repair_failures", 0)
        window_management.setdefault("source_occlusion_failures", 0)
        window_management.setdefault("successful_split_layouts", 0)
        window_management["strict_split_enabled"] = True
        window_management["last_training_request"] = self._now()
        self._write_mouse_strategy(payload)
        return payload

    def _window_management_data_summary(self, strategy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = strategy if strategy is not None else self._read_mouse_strategy()
        practice = payload.get("practice", {}) if isinstance(payload.get("practice", {}), dict) else {}
        workflow = practice.get("workflow", {}) if isinstance(practice.get("workflow", {}), dict) else {}
        window_management = (
            payload.get("window_management", {}) if isinstance(payload.get("window_management", {}), dict) else {}
        )
        repair_attempts = int(window_management.get("repair_attempts", 0) or 0)
        repair_successes = int(window_management.get("repair_successes", 0) or 0)
        repair_failures = int(window_management.get("repair_failures", 0) or 0)
        successful_split_layouts = int(window_management.get("successful_split_layouts", 0) or 0)
        workflow_successes = int(workflow.get("successes", 0) or 0)
        workflow_failures = int(workflow.get("failures", 0) or 0)
        workflow_attempts = int(workflow.get("attempts", workflow_successes + workflow_failures) or 0)
        workflow_success_rate = float(
            workflow.get(
                "success_rate",
                (workflow_successes / max(1, workflow_successes + workflow_failures)) if (workflow_successes or workflow_failures) else 0.0,
            )
            or 0.0
        )
        repair_success_rate = repair_successes / repair_attempts if repair_attempts else 0.0
        return {
            "strict_split_enabled": bool(window_management.get("strict_split_enabled")),
            "repair_attempts": repair_attempts,
            "repair_successes": repair_successes,
            "repair_failures": repair_failures,
            "source_occlusion_failures": int(window_management.get("source_occlusion_failures", 0) or 0),
            "successful_split_layouts": successful_split_layouts,
            "repair_success_rate": repair_success_rate,
            "workflow_attempts": workflow_attempts,
            "workflow_successes": workflow_successes,
            "workflow_failures": workflow_failures,
            "workflow_success_rate": workflow_success_rate,
            "workflow_reliable": bool(workflow.get("reliable", workflow_success_rate >= 0.9)),
            "workflow_session_id": str(workflow.get("last_session_id", "") or ""),
            "real_usage_ready": bool(
                window_management.get("strict_split_enabled")
                and successful_split_layouts >= 3
                and (repair_attempts == 0 or repair_success_rate >= 0.6)
                and bool(workflow.get("reliable", workflow_success_rate >= 0.9))
            ),
        }

    def _mouse_practice_metric(self, strategy: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
        practice = strategy.get("practice", {})
        if not isinstance(practice, dict):
            return None
        source = practice if key == "drag" else practice.get(key, {})
        if not isinstance(source, dict):
            return None
        successes = int(source.get("successes", 0) or 0)
        failures = int(source.get("failures", 0) or 0)
        attempts = int(source.get("attempts", successes + failures) or 0)
        if attempts <= 0 and successes + failures <= 0:
            return None
        total = successes + failures
        if total <= 0:
            total = attempts
            failures = max(0, attempts - successes)
        success_rate = float(source.get("success_rate", successes / total if total else 0.0) or 0.0)
        if key == "drag":
            reliable = bool(source.get("real_drag_enabled", success_rate >= 0.7))
        else:
            reliable = bool(source.get("reliable", success_rate >= 0.9))
        return {
            "attempts": attempts or total,
            "successes": successes,
            "failures": failures,
            "success_rate": success_rate,
            "session_id": source.get("last_session_id", ""),
            "reliable": reliable,
            "workflow_success": key in {"drag", "workflow"} and reliable,
        }

    def _legacy_mouse_data_summary(self, strategy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = strategy if strategy is not None else self._read_mouse_strategy()
        profiles_data = data.get("profiles", {}) if isinstance(data, dict) else {}
        categories = data.get("categories", {}) if isinstance(data, dict) else {}

        profile_successes = 0
        profile_failures = 0
        best_strategy = ""
        best_rate = -1.0
        for profile_name, profile_info in profiles_data.items():
            successes = int(profile_info.get("successes", 0) or 0)
            failures = int(profile_info.get("failures", 0) or 0)
            profile_successes += successes
            profile_failures += failures
            total = successes + failures
            rate = successes / total if total else 0.0
            if successes > 0 and rate > best_rate:
                best_rate = rate
                best_strategy = str(profile_name)

        category_successes = sum(int(item.get("successes", 0) or 0) for item in categories.values())
        category_failures = sum(int(item.get("failures", 0) or 0) for item in categories.values())
        successes = max(profile_successes, category_successes)
        failures = max(profile_failures, category_failures)
        total = successes + failures
        success_rate = successes / total if total else 0.0
        return {
            "successes": successes,
            "failures": failures,
            "success_rate": round(success_rate, 4),
            "best_strategy": best_strategy,
            "real_usage_ready": self._mouse_real_usage_ready(data),
        }

    def _mouse_real_usage_ready(self, strategy: Optional[Dict[str, Any]] = None) -> bool:
        data = strategy if strategy is not None else self._read_mouse_strategy()
        if not isinstance(data, dict):
            return False
        practice = data.get("practice", {})
        if not isinstance(practice, dict):
            return False
        drag_ready = bool(practice.get("real_drag_enabled"))
        movement_ready = bool(practice.get("movement", {}).get("reliable"))
        required_click_metrics = ("click", "double_click", "right_click")
        click_ready = True
        attempted_click = False
        for metric_key in required_click_metrics:
            metric = practice.get(metric_key, {})
            if not isinstance(metric, dict):
                continue
            attempted = bool(metric.get("last_session_id")) or int(metric.get("attempts", 0) or 0) > 0
            if not attempted:
                continue
            attempted_click = True
            if not bool(metric.get("reliable")):
                click_ready = False
                break
        if not attempted_click:
            click_ready = bool(practice.get("click", {}).get("reliable", True))
        return bool(drag_ready and movement_ready and click_ready)

    def _keyboard_write_and_verify(self, text: str) -> Tuple[bool, Dict[str, Any]]:
        self._emit(f"Practica teclado: escribiendo '{text[:30]}'", "info")
        before = self._capture_context(refresh=True)
        context_failure = self._unexpected_modal_reason(before, expected_app="notepad")
        if context_failure:
            recovered = self._recover_keyboard_editor_context()
            if recovered:
                before = self._capture_context(refresh=True)
                context_failure = self._unexpected_modal_reason(before, expected_app="notepad")
        if context_failure:
            return False, self._failure_detail(
                step="keyboard_write_verify",
                strategy="direct_typing",
                verification="strict_context",
                before=before,
                reason=context_failure,
                text=text,
            )

        clicked = self._click_visible_hint("document_body", expected_app="notepad")
        if not clicked:
            recovered = self._recover_keyboard_editor_context()
            if recovered:
                clicked = self._click_visible_hint("document_body", expected_app="notepad")
        if not clicked:
            before = self._capture_context(refresh=True)
            return False, self._failure_detail(
                step="keyboard_write_verify",
                strategy="direct_typing",
                verification="document_body_focus",
                before=before,
                reason="No pude enfocar el cuerpo del Bloc de notas.",
                text=text,
                target_control_used="document_body",
            )

        focused = self._capture_context(refresh=True)
        focus_failure = self._unexpected_modal_reason(focused, expected_app="notepad")
        if focus_failure:
            return False, self._failure_detail(
                step="keyboard_write_verify",
                strategy="direct_typing",
                verification="strict_context_after_focus",
                before=focused,
                reason=focus_failure,
                text=text,
                target_control_used="document_body",
            )

        if not self._clear_active_editor():
            before = self._capture_context(refresh=True)
            reason = (
                self._unexpected_modal_reason(before, expected_app="notepad")
                or "No pude limpiar el editor sin cambiar de contexto."
            )
            if self._open_file_dialog_visible(before):
                self._close_open_file_dialog_if_present()
            return False, self._failure_detail(
                step="keyboard_write_verify",
                strategy="direct_typing",
                verification="safe_clear_editor",
                before=before,
                reason=reason,
                text=text,
                target_control_used="document_body",
            )
        pre_write = self._capture_context(refresh=True)
        pre_write_failure = self._unexpected_modal_reason(pre_write, expected_app="notepad")
        if pre_write_failure:
            if self._open_file_dialog_visible(pre_write):
                self._close_open_file_dialog_if_present()
            return False, self._failure_detail(
                step="keyboard_write_verify",
                strategy="direct_typing",
                verification="strict_context_before_write",
                before=pre_write,
                reason=pre_write_failure,
                text=text,
                target_control_used="document_body",
            )

        direct_success, direct_detail = self._keyboard_write_attempt(text, use_clipboard=False)
        if direct_success:
            self._clear_active_editor()
            return direct_success, direct_detail

        if direct_detail.get("verification") in {"capture_selected_text", "write_error"} and not direct_detail.get("context_failure"):
            fallback_success, fallback_detail = self._keyboard_write_attempt(text, use_clipboard=True)
            fallback_detail["rescue_used"] = True
            fallback_detail["fallback_source"] = direct_detail
            self._clear_active_editor()
            return fallback_success, fallback_detail

        self._clear_active_editor()
        return direct_success, direct_detail

    def _keyboard_write_attempt(self, text: str, use_clipboard: bool) -> Tuple[bool, Dict[str, Any]]:
        strategy = "clipboard_paste" if use_clipboard else "direct_typing"
        try:
            if use_clipboard:
                self.automation.write_text(text, interval=0.01, use_clipboard=True)
                self.learning.record_strategy_result("text_entry:keyboard_skill", strategy, True)
            else:
                strategy = self._write_text_with_learning("text_entry:keyboard_skill", text, allow_clipboard=False)
        except Exception as exc:
            after = self._capture_context(refresh=True)
            return False, self._failure_detail(
                step="keyboard_write_verify",
                strategy=strategy,
                verification="write_error",
                before=self._capture_context(refresh=True),
                reason=f"Error de escritura: {exc}",
                text=text,
                target_control_used="document_body",
                rescue_used=use_clipboard,
            )

        open_dialog = self._open_file_dialog_visible(self._capture_context(refresh=True))
        if open_dialog:
            self._close_open_file_dialog_if_present()
            before = self._capture_context(refresh=True)
            return False, self._failure_detail(
                step="keyboard_write_verify",
                strategy=strategy,
                verification="strict_context_after_write",
                before=before,
                reason="Se abrio un cuadro de apertura de archivo durante la escritura.",
                text=text,
                target_control_used="document_body",
                rescue_used=use_clipboard,
            )

        self.sleep(0.25)
        captured = self._capture_editor_text(expected_app="notepad") or ""
        after = self._capture_context(refresh=True)
        normalized_expected = normalize_text(text)
        normalized_captured = normalize_text(captured)
        exact_match = normalized_expected == normalized_captured
        after_failure = self._unexpected_modal_reason(after, expected_app="notepad")
        reason = ""
        if after_failure:
            reason = after_failure
        elif not exact_match:
            reason = (
                f"Texto capturado no coincide. Esperado: {normalized_expected!r}, capturado: {normalized_captured!r}."
            )

        success = exact_match and not after_failure
        detail = {
            "step": "keyboard_write_verify",
            "text": text,
            "captured_preview": captured[:120],
            "strategy": strategy,
            "verification": "capture_selected_text",
            "success": success,
            "context_failure": after_failure or "",
            "reason": reason,
            "rescue_used": use_clipboard,
            "evidence": self._build_evidence(
                before=self._capture_context(refresh=False),
                after=after,
                target_control_used="document_body",
                selected_text_preview=captured[:120],
                verification_reason="" if success else reason or "El texto capturado no coincide exactamente.",
                rescue_used=use_clipboard,
            ),
        }
        return success, detail

    def _keyboard_browser_search_workflow(self, goal: str, workspace: Path) -> Tuple[bool, Dict[str, Any]]:
        return self._visible_google_search(query=goal, browser_name="brave", step_name="keyboard_browser_search")

    def _keyboard_explorer_open_workflow(self, goal: str, workspace: Path) -> Tuple[bool, Dict[str, Any]]:
        before = self._capture_context(refresh=True)
        try:
            self.automation.hotkey("winleft", "e")
            self.sleep(1.0)
        except Exception as exc:
            return False, self._failure_detail(
                step="keyboard_explorer_open",
                strategy="win_e",
                verification="active_app_explorer",
                before=before,
                reason=f"No se pudo lanzar Explorer con Win+E: {exc}",
                rescue_used=False,
            )
        after = self._capture_context(refresh=True)
        success = self._looks_like_explorer_context(after)
        reason = "" if success else "Win+E no dejo Explorer como app activa."
        return success, {
            "step": "keyboard_explorer_open",
            "strategy": "win_e",
            "verification": "active_app_explorer",
            "success": success,
            "context_failure": "" if success else reason,
            "evidence": self._build_evidence(
                before=before,
                after=after,
                target_control_used="win_e",
                selected_text_preview="",
                verification_reason=reason,
                rescue_used=False,
            ),
        }

    def _keyboard_browser_address_focus_workflow(self, goal: str, workspace: Path) -> Tuple[bool, Dict[str, Any]]:
        destination = "google.com"
        expected_site = "google"
        if str(goal).strip() and ("http" in normalize_text(goal) or ".com" in normalize_text(goal)):
            destination = goal.strip()
        return self._visible_address_navigation(
            browser_name="brave",
            destination_text=destination,
            expected_site=expected_site,
            step_name="keyboard_browser_address_focus",
        )

    def _keyboard_explorer_search_workflow(self, goal: str, workspace: Path) -> Tuple[bool, Dict[str, Any]]:
        ensure_directory(workspace)
        search_file = workspace / "buscar_teclado_ctrl_f.txt"
        search_file.write_text("buscar con teclado", encoding="utf-8")
        self.assistant.open_folder(str(workspace))
        self.sleep(1.0)
        before = self._capture_context(refresh=True)
        if not self._looks_like_explorer_context(before):
            return False, self._failure_detail(
                step="keyboard_explorer_search",
                strategy="ctrl_f_search",
                verification="explorer_search_focus",
                before=before,
                reason="Explorer no quedo activo antes de intentar Ctrl+F.",
                text=search_file.name,
                target_control_used="ctrl_f",
            )
        try:
            self.automation.hotkey("ctrl", "f")
            self.sleep(0.12)
            self.automation.hotkey("ctrl", "a")
            self.sleep(0.05)
            self._write_text_with_learning("text_entry:explorer_search", search_file.name, allow_clipboard=True)
            self.automation.press_keys(["enter"])
            self.sleep(0.8)
            self.automation.press_keys(["tab"])
            self.sleep(0.08)
            self.automation.press_keys(["tab"])
            self.sleep(0.08)
            self.automation.hotkey("ctrl", "a")
            self.sleep(0.18)
        except Exception as exc:
            return False, self._failure_detail(
                step="keyboard_explorer_search",
                strategy="ctrl_f_search",
                verification="explorer_search_focus",
                before=before,
                reason=f"Fallo la busqueda con Ctrl+F: {exc}",
                text=search_file.name,
                target_control_used="ctrl_f",
            )
        after = self._capture_context(refresh=True)
        success = self._looks_like_explorer_context(after)
        reason = "" if success else "Ctrl+F no dejo un contexto estable de Explorer."
        return success, {
            "step": "keyboard_explorer_search",
            "strategy": "ctrl_f_search",
            "verification": "explorer_search_focus",
            "success": success,
            "query": search_file.name,
            "context_failure": "" if success else reason,
            "evidence": self._build_evidence(
                before=before,
                after=after,
                target_control_used="ctrl_f",
                selected_text_preview=search_file.name,
                verification_reason=reason,
                rescue_used=False,
            ),
        }

    def _keyboard_explorer_rename_workflow(self, goal: str, workspace: Path) -> Tuple[bool, Dict[str, Any]]:
        ensure_directory(workspace)
        source = workspace / "rename_me.txt"
        target = workspace / "rename_ok.txt"
        source.write_text("raphel", encoding="utf-8")
        if target.exists():
            target.unlink()
        self.automation.open_file_select(str(source))
        self.sleep(1.0)
        self.automation.press_keys(["f2"])
        self.sleep(0.2)
        self._write_text_with_learning("text_entry:keyboard_rename", target.stem)
        self.automation.press_keys(["enter"])
        self.sleep(0.8)
        success = target.exists()
        return success, {
            "step": "keyboard_explorer_rename",
            "strategy": "f2_rename",
            "verification": "filesystem_exists",
            "success": success,
            "source": str(source),
            "target": str(target),
        }

    def _keyboard_notepad_save_workflow(self, goal: str, workspace: Path) -> Tuple[bool, Dict[str, Any]]:
        ensure_directory(workspace)
        target = workspace / "keyboard_saved_note.txt"
        text = f"{goal or 'guardado teclado'} {random.randint(100, 999)}"
        prepared = self._prepare_plain_notepad_session(target)
        if not prepared:
            before = self._capture_context(refresh=True)
            return False, self._failure_detail(
                step="keyboard_notepad_save",
                strategy="ctrl_s",
                verification="file_saved",
                before=before,
                reason="No se pudo preparar Notepad para guardar.",
                text=text,
                target_control_used="ctrl_s",
            )
        try:
            success, detail = self._keyboard_write_and_verify(text)
            if not success:
                detail["step"] = "keyboard_notepad_save"
                return success, detail
            before_save = self._capture_context(refresh=True)
            shortcut_used = "ctrl_s"
            try:
                self.automation.hotkey("ctrl", "shift", "s")
                shortcut_used = "ctrl_shift_s"
                self.sleep(0.4)
            except Exception:
                pass
            try:
                self.automation.hotkey("ctrl", "s")
                self.sleep(0.5)
            except Exception as exc:
                return False, self._failure_detail(
                    step="keyboard_notepad_save",
                    strategy=shortcut_used,
                    verification="file_saved",
                    before=before_save,
                    reason=f"No se pudo ejecutar el guardado: {exc}",
                    text=text,
                    target_control_used=shortcut_used,
                )
            saved_text = target.read_text(encoding="utf-8", errors="ignore") if target.exists() else ""
            after = self._capture_context(refresh=True)
            file_exists = target.exists()
            success = file_exists and normalize_text(text) in normalize_text(saved_text)
            reason = "" if success else "El archivo guardado no contiene el texto esperado."
            return success, {
                "step": "keyboard_notepad_save",
                "strategy": shortcut_used,
                "verification": "file_saved",
                "success": success,
                "context_failure": "" if success else reason,
                "document_result": str(target),
                "evidence": self._build_evidence(
                    before=before_save,
                    after=after,
                    target_control_used=shortcut_used,
                    selected_text_preview=text[:120],
                    verification_reason=reason,
                    rescue_used=False,
                ),
            }
        finally:
            self._finalize_plain_notepad_session()

    def _keyboard_notepad_replace_workflow(self, goal: str, workspace: Path) -> Tuple[bool, Dict[str, Any]]:
        self._prepare_plain_notepad_session(workspace / "keyboard_notepad_workflow.txt")
        try:
            verification_word = random.choice(("verificado", "confirmado", "registrado", "validado"))
            text = f"{goal}\n{verification_word} con teclado {random.randint(100, 999)}"
            success, detail = self._keyboard_write_and_verify(text)
            detail["step"] = "keyboard_notepad_replace"
            return success, detail
        finally:
            self._finalize_plain_notepad_session()

    def _keyboard_window_switch_workflow(self, goal: str, workspace: Path) -> Tuple[bool, Dict[str, Any]]:
        self.assistant.open_application("notepad")
        self.sleep(0.6)
        self.assistant.ensure_browser(browser="brave", private=False)
        self.sleep(0.6)
        before = self._capture_context(refresh=True)
        try:
            if hasattr(self.automation, "alt_tab"):
                self.automation.alt_tab()
            else:
                self.automation.hotkey("alt", "tab")
            self.sleep(0.4)
        except Exception as exc:
            return False, self._failure_detail(
                step="keyboard_window_switch",
                strategy="alt_tab",
                verification="window_changed",
                before=before,
                reason=f"No se pudo ejecutar Alt+Tab: {exc}",
                target_control_used="alt_tab",
            )
        after = self._capture_context(refresh=True)
        success = normalize_text(after.get("window_title", "")) != normalize_text(before.get("window_title", ""))
        reason = "" if success else "Alt+Tab no cambio la ventana activa."
        return success, {
            "step": "keyboard_window_switch",
            "strategy": "alt_tab",
            "verification": "window_changed",
            "success": success,
            "context_failure": "" if success else reason,
            "evidence": self._build_evidence(
                before=before,
                after=after,
                target_control_used="alt_tab",
                selected_text_preview="",
                verification_reason=reason,
                rescue_used=False,
            ),
        }

    def _keyboard_window_focus_workflow(self, goal: str, workspace: Path) -> Tuple[bool, Dict[str, Any]]:
        self.assistant.open_application("notepad")
        self.sleep(0.5)
        before = self._capture_context(refresh=True)
        try:
            self.assistant.focus_window("Bloc de notas")
            self.sleep(0.35)
        except Exception as exc:
            return False, self._failure_detail(
                step="keyboard_window_focus",
                strategy="focus_window",
                verification="focused_window",
                before=before,
                reason=f"No se pudo enfocar la ventana objetivo: {exc}",
                target_control_used="focus_window",
            )
        after = self._capture_context(refresh=True)
        success = self._context_title_matches_expected_app(after.get("window_title", ""), "notepad")
        reason = "" if success else "focus_window no dejo Notepad como ventana activa."
        return success, {
            "step": "keyboard_window_focus",
            "strategy": "focus_window",
            "verification": "focused_window",
            "success": success,
            "context_failure": "" if success else reason,
            "evidence": self._build_evidence(
                before=before,
                after=after,
                target_control_used="focus_window",
                selected_text_preview="",
                verification_reason=reason,
                rescue_used=False,
            ),
        }

    def _keyboard_window_close_workflow(self, goal: str, workspace: Path) -> Tuple[bool, Dict[str, Any]]:
        self.assistant.open_application("notepad")
        self.sleep(0.6)
        before = self._capture_context(refresh=True)
        try:
            self.automation.hotkey("alt", "f4")
            self.sleep(0.5)
        except Exception as exc:
            return False, self._failure_detail(
                step="keyboard_window_close",
                strategy="alt_f4",
                verification="window_closed_or_changed",
                before=before,
                reason=f"No se pudo cerrar la ventana con Alt+F4: {exc}",
                target_control_used="alt_f4",
            )
        after = self._capture_context(refresh=True)
        success = normalize_text(after.get("window_title", "")) != normalize_text(before.get("window_title", ""))
        reason = "" if success else "Alt+F4 no cambio la ventana activa."
        return success, {
            "step": "keyboard_window_close",
            "strategy": "alt_f4",
            "verification": "window_closed_or_changed",
            "success": success,
            "context_failure": "" if success else reason,
            "evidence": self._build_evidence(
                before=before,
                after=after,
                target_control_used="alt_f4",
                selected_text_preview="",
                verification_reason=reason,
                rescue_used=False,
            ),
        }

    def _keyboard_minimize_all_workflow(self, goal: str, workspace: Path) -> Tuple[bool, Dict[str, Any]]:
        self.assistant.open_application("notepad")
        self.sleep(0.5)
        before = self._capture_context(refresh=True)
        try:
            self.automation.hotkey("winleft", "m")
            self.sleep(0.4)
        except Exception as exc:
            return False, self._failure_detail(
                step="keyboard_minimize_all",
                strategy="win_m",
                verification="window_changed",
                before=before,
                reason=f"No se pudo minimizar con Win+M: {exc}",
                target_control_used="win_m",
            )
        after = self._capture_context(refresh=True)
        success = normalize_text(after.get("window_title", "")) != normalize_text(before.get("window_title", ""))
        reason = "" if success else "Win+M no cambio la ventana activa."
        return success, {
            "step": "keyboard_minimize_all",
            "strategy": "win_m",
            "verification": "window_changed",
            "success": success,
            "context_failure": "" if success else reason,
            "evidence": self._build_evidence(
                before=before,
                after=after,
                target_control_used="win_m",
                selected_text_preview="",
                verification_reason=reason,
                rescue_used=False,
            ),
        }

    def _keyboard_maximize_window_workflow(self, goal: str, workspace: Path) -> Tuple[bool, Dict[str, Any]]:
        self.assistant.open_application("notepad")
        self.sleep(0.5)
        before = self._capture_context(refresh=True)
        try:
            self.automation.hotkey("winleft", "up")
            self.sleep(0.35)
        except Exception as exc:
            return False, self._failure_detail(
                step="keyboard_maximize_window",
                strategy="win_up",
                verification="window_focus_persisted",
                before=before,
                reason=f"No se pudo maximizar con Win+Up: {exc}",
                target_control_used="win_up",
            )
        after = self._capture_context(refresh=True)
        success = self._context_title_matches_expected_app(after.get("window_title", ""), "notepad")
        reason = "" if success else "Win+Up perdio el foco de la ventana objetivo."
        return success, {
            "step": "keyboard_maximize_window",
            "strategy": "win_up",
            "verification": "window_focus_persisted",
            "success": success,
            "context_failure": "" if success else reason,
            "evidence": self._build_evidence(
                before=before,
                after=after,
                target_control_used="win_up",
                selected_text_preview="",
                verification_reason=reason,
                rescue_used=False,
            ),
        }

    def _keyboard_multiapp_workflow(self, goal: str, workspace: Path) -> Tuple[bool, Dict[str, Any]]:
        steps: List[Dict[str, Any]] = []
        success, open_detail = self._keyboard_explorer_open_workflow(goal, workspace)
        steps.append(open_detail)
        if not success:
            return False, {
                "step": "keyboard_multiapp_chain",
                "strategy": "multiapp_keyboard_chain",
                "verification": "multiapp_chain",
                "success": False,
                "context_failure": open_detail.get("context_failure", ""),
                "child_steps": steps,
                "evidence": dict(open_detail.get("evidence", {})),
            }
        search_success, search_detail = self._keyboard_explorer_search_workflow(goal, workspace)
        steps.append(search_detail)
        focus_success, focus_detail = self._keyboard_browser_address_focus_workflow("google.com", workspace)
        steps.append(focus_detail)
        switch_success, switch_detail = self._keyboard_window_switch_workflow(goal, workspace)
        steps.append(switch_detail)
        chain_success = all(item.get("success") for item in steps[-3:])
        return chain_success, {
            "step": "keyboard_multiapp_chain",
            "strategy": "multiapp_keyboard_chain",
            "verification": "multiapp_chain",
            "success": chain_success,
            "context_failure": "" if chain_success else (
                search_detail.get("context_failure")
                or focus_detail.get("context_failure")
                or switch_detail.get("context_failure")
                or ""
            ),
            "child_steps": steps,
            "evidence": dict(switch_detail.get("evidence", {})),
        }

    def _keyboard_goal_workflow(self, goal: str, workspace: Path) -> Tuple[bool, Dict[str, Any]]:
        normalized_goal = normalize_text(goal)
        if "win+e" in normalized_goal or "explorer" in normalized_goal or "explorador" in normalized_goal:
            if "ctrl+f" in normalized_goal or "buscar" in normalized_goal:
                return self._keyboard_explorer_search_workflow(goal, workspace)
            return self._keyboard_explorer_open_workflow(goal, workspace)
        if "ctrl+l" in normalized_goal or "alt+d" in normalized_goal or "barra" in normalized_goal:
            return self._keyboard_browser_address_focus_workflow(goal or "google.com", workspace)
        if "renombra" in normalized_goal or "rename" in normalized_goal:
            return self._keyboard_explorer_rename_workflow(goal, workspace)
        if "guardar" in normalized_goal or "ctrl+s" in normalized_goal:
            return self._keyboard_notepad_save_workflow(goal, workspace)
        if "alt+tab" in normalized_goal or "cambia de ventana" in normalized_goal:
            return self._keyboard_window_switch_workflow(goal, workspace)
        if "focus_window" in normalized_goal or "enfoca ventana" in normalized_goal:
            return self._keyboard_window_focus_workflow(goal, workspace)
        if "alt+f4" in normalized_goal or "cerrar ventana" in normalized_goal:
            return self._keyboard_window_close_workflow(goal, workspace)
        if "win+m" in normalized_goal or "minimiza" in normalized_goal:
            return self._keyboard_minimize_all_workflow(goal, workspace)
        if "win+up" in normalized_goal or "maximiza" in normalized_goal:
            return self._keyboard_maximize_window_workflow(goal, workspace)
        if "busca" in normalized_goal or "google" in normalized_goal or "youtube" in normalized_goal:
            if "youtube" in normalized_goal:
                return self._visible_youtube_search(query=goal, browser_name="brave", step_name="keyboard_goal_search")
            return self._visible_google_search(query=goal, browser_name="brave", step_name="keyboard_goal_search")
        if "multiapp" in normalized_goal or "flujo" in normalized_goal:
            return self._keyboard_multiapp_workflow(goal, workspace)
        return self._keyboard_notepad_replace_workflow(goal, workspace)

    def _run_browser_app_cycle(
        self,
        browser_name: str,
        level: int,
        goal: str,
        requested_attempts: Optional[int],
        requested_minutes: Optional[int],
        cycle_number: int,
    ) -> Dict[str, Any]:
        settings = self._skill_settings("browser_app")
        attempts = max(1, requested_attempts or int(settings.get("default_attempts_level_1", 3)))
        cycle = self._empty_cycle(cycle_number, level, requested_attempts, requested_minutes)
        query = goal or "raphel navegador visible"
        for _ in range(attempts):
            if level == 1:
                success, detail = self._visible_address_navigation(
                    browser_name=browser_name,
                    destination_text="google.com",
                    expected_site="google",
                    step_name=f"{browser_name}_open_google",
                )
            elif level == 2:
                success, detail = self._visible_google_search(
                    query=query,
                    browser_name=browser_name,
                    step_name=f"{browser_name}_google_search",
                )
            else:
                normalized_goal = normalize_text(goal)
                if "youtube" in normalized_goal:
                    success, detail = self._visible_youtube_search(
                        query=goal or "rimuru tempest",
                        browser_name=browser_name,
                        step_name=f"{browser_name}_goal_search",
                    )
                else:
                    success, detail = self._visible_google_search(
                        query=query,
                        browser_name=browser_name,
                        step_name=f"{browser_name}_goal_search",
                    )
            cycle["steps"].append(detail)
            cycle["strategies_tried"].append(detail.get("strategy", "visible_browser"))
            cycle["verifications"].append(detail.get("verification", "strict_real"))
            cycle["successes" if success else "failures"] += 1
            cycle["verified_successes"] += int(success)
            cycle["workflow_successes"] += int(success and level >= 2)
            if detail.get("context_failure"):
                cycle["context_failures"].append(detail["context_failure"])
        cycle["status"] = "completed" if cycle["verified_successes"] > 0 else "retry"
        cycle["summary"] = (
            f"{browser_name.title()} nivel {level}: {cycle['verified_successes']} verificados de "
            f"{cycle['successes'] + cycle['failures']} intento(s)."
        )
        return cycle

    def _run_document_editor_cycle(
        self,
        application: str,
        level: int,
        goal: str,
        requested_attempts: Optional[int],
        requested_minutes: Optional[int],
        cycle_number: int,
    ) -> Dict[str, Any]:
        settings = self._skill_settings("document_editor")
        attempts = max(1, requested_attempts or int(settings.get("default_attempts_level_1", 3)))
        cycle = self._empty_cycle(cycle_number, level, requested_attempts, requested_minutes)
        workspace = self.sessions_dir / f"{application}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        ensure_directory(workspace)
        sample = goal or f"{application} visible y verificado"
        for _ in range(attempts):
            if level == 1:
                success, detail = self._document_editor_write_and_verify(application, sample)
            elif level == 2:
                success, detail = self._document_editor_save_workflow(application, sample, workspace)
            else:
                success, detail = self._document_editor_goal_workflow(application, goal or sample, workspace)
            cycle["steps"].append(detail)
            cycle["strategies_tried"].append(detail.get("strategy", "direct_typing"))
            cycle["verifications"].append(detail.get("verification", "strict_real"))
            cycle["successes" if success else "failures"] += 1
            cycle["verified_successes"] += int(success)
            cycle["workflow_successes"] += int(success and level >= 2)
            if detail.get("context_failure"):
                cycle["context_failures"].append(detail["context_failure"])
        cycle["status"] = "completed" if cycle["verified_successes"] > 0 else "retry"
        cycle["summary"] = (
            f"{application.title()} nivel {level}: {cycle['verified_successes']} verificados de "
            f"{cycle['successes'] + cycle['failures']} intento(s)."
        )
        return cycle

    def _run_site_workflow_cycle(
        self,
        site_name: str,
        level: int,
        mode: str,
        goal: str,
        requested_attempts: Optional[int],
        requested_minutes: Optional[int],
        cycle_number: int,
    ) -> Dict[str, Any]:
        settings = self._skill_settings(site_name if site_name in {"youtube", "google"} else "site_workflow")
        attempts = max(1, requested_attempts or int(settings.get("default_attempts_level_1", 3)))
        cycle = self._empty_cycle(cycle_number, level, requested_attempts, requested_minutes)
        query = goal or "rimuru tempest"
        for _ in range(attempts):
            if site_name == "youtube":
                success, detail = self._visible_youtube_search(query=query, browser_name="brave", step_name=f"{site_name}_search")
                if success and level >= 2:
                    success, detail = self._youtube_open_result_attempt(query)
                    if level >= 3 and success:
                        success, detail = self._youtube_goal_workflow(goal or query, preopened_detail=detail)
            elif site_name == "google":
                success, detail = self._visible_google_search(query=query, browser_name="brave", step_name=f"{site_name}_search")
                if success and level >= 2:
                    success, detail = self._visible_open_google_result(query, index=1, step_name="google_open_result")
            else:
                success, detail = self._visible_site_navigation(site_name=site_name, browser_name="brave", step_name=f"{site_name}_visible_open")
            cycle["steps"].append(detail)
            cycle["strategies_tried"].append(detail.get("strategy", "visible_site"))
            cycle["verifications"].append(detail.get("verification", "strict_real"))
            cycle["successes" if success else "failures"] += 1
            cycle["verified_successes"] += int(success)
            cycle["workflow_successes"] += int(success and level >= 2)
            if detail.get("context_failure"):
                cycle["context_failures"].append(detail["context_failure"])
        cycle["status"] = "completed" if cycle["verified_successes"] > 0 else "retry"
        cycle["summary"] = (
            f"{site_name.title()} nivel {level}: {cycle['verified_successes']} verificados de "
            f"{cycle['successes'] + cycle['failures']} intento(s)."
        )
        return cycle

    def _run_file_manager_cycle(
        self,
        application: str,
        level: int,
        goal: str,
        requested_attempts: Optional[int],
        requested_minutes: Optional[int],
        cycle_number: int,
    ) -> Dict[str, Any]:
        cycle = self._empty_cycle(cycle_number, level, requested_attempts, requested_minutes)
        workspace = self.sessions_dir / f"explorer_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        ensure_directory(workspace)
        attempts = max(1, requested_attempts or 2)
        for _ in range(attempts):
            if level == 1:
                success, detail = self._file_manager_open_and_verify(application, workspace)
            elif level == 2:
                success, detail = self._keyboard_explorer_rename_workflow(goal or "raphel rename", workspace)
            else:
                success, detail = self._file_manager_goal_workflow(application, goal or "renombra un archivo", workspace)
            cycle["steps"].append(detail)
            cycle["strategies_tried"].append(detail.get("strategy", "explorer_visible"))
            cycle["verifications"].append(detail.get("verification", "strict_real"))
            cycle["successes" if success else "failures"] += 1
            cycle["verified_successes"] += int(success)
            cycle["workflow_successes"] += int(success and level >= 2)
            if detail.get("context_failure"):
                cycle["context_failures"].append(detail["context_failure"])
        cycle["status"] = "completed" if cycle["verified_successes"] > 0 else "retry"
        cycle["summary"] = (
            f"{application.title()} nivel {level}: {cycle['verified_successes']} verificados de "
            f"{cycle['successes'] + cycle['failures']} intento(s)."
        )
        return cycle

    def _run_application_workflow_cycle(
        self,
        application: str,
        level: int,
        goal: str,
        requested_attempts: Optional[int],
        requested_minutes: Optional[int],
        cycle_number: int,
    ) -> Dict[str, Any]:
        cycle = self._empty_cycle(cycle_number, level, requested_attempts, requested_minutes)
        success, detail = self._generic_application_open_and_verify(application)
        cycle["steps"].append(detail)
        cycle["strategies_tried"].append(detail.get("strategy", "open_and_focus"))
        cycle["verifications"].append(detail.get("verification", "strict_real"))
        cycle["successes" if success else "failures"] += 1
        cycle["verified_successes"] += int(success)
        cycle["workflow_successes"] += int(success and level >= 2)
        if detail.get("context_failure"):
            cycle["context_failures"].append(detail["context_failure"])
        cycle["status"] = "completed" if success else "retry"
        cycle["summary"] = (
            f"{application.title()} nivel {level}: {cycle['verified_successes']} verificados de "
            f"{cycle['successes'] + cycle['failures']} intento(s)."
        )
        return cycle

    def _visible_address_navigation(
        self,
        browser_name: str,
        destination_text: str,
        expected_site: str,
        step_name: str,
    ) -> Tuple[bool, Dict[str, Any]]:
        self._focus_or_launch_known_app(browser_name)
        before = self._capture_context(refresh=True)
        if self._browser_leave_site_prompt_visible(context=before, refresh=True):
            self._resolve_browser_leave_site_prompt(leave=True, browser_name=browser_name)
            before = self._capture_context(refresh=True)
        context_failure = self._unexpected_modal_reason(before, expected_app=browser_name)
        if context_failure:
            return False, self._failure_detail(
                step=step_name,
                strategy="visible_address_navigation",
                verification="strict_real",
                before=before,
                reason=context_failure,
                text=destination_text,
                target_control_used="browser_address_bar",
            )
        target_control_used = self._focus_browser_address_bar(browser_name=browser_name)
        if not target_control_used and not self._click_visible_hint("browser_address_bar", expected_app=browser_name):
            return False, self._failure_detail(
                step=step_name,
                strategy="visible_address_navigation",
                verification="strict_real",
                before=before,
                reason="No pude enfocar la barra de direcciones visible.",
                text=destination_text,
                target_control_used="browser_address_bar",
            )
        target_control_used = target_control_used or "browser_address_bar"
        strategy = self._write_text_with_learning("text_entry:browser_address", destination_text, allow_clipboard=False)
        self.automation.press_keys(["enter"])
        self.sleep(0.75)
        after = self._capture_context(refresh=True)
        if self._browser_leave_site_prompt_visible(context=after, refresh=True):
            self._resolve_browser_leave_site_prompt(leave=True, browser_name=browser_name)
            self.sleep(0.65)
            after = self._capture_context(refresh=True)
        after_failure = self._unexpected_modal_reason(after, expected_app=browser_name)
        success = not after_failure and self._context_matches_site(after, expected_site)
        detail = {
            "step": step_name,
            "strategy": strategy,
            "verification": "window_site_transition",
            "destination_text": destination_text,
            "success": success,
            "context_failure": after_failure or "",
            "evidence": self._build_evidence(
                before=before,
                after=after,
                target_control_used=target_control_used,
                selected_text_preview="",
                verification_reason="" if success else (after_failure or f"No se confirmo el sitio {expected_site}."),
                rescue_used=False,
            ),
        }
        return success, detail

    def _focus_browser_address_bar(self, browser_name: str = "brave") -> str:
        for shortcut, target_name in (
            (("ctrl", "l"), "browser_address_bar_shortcut"),
            (("alt", "d"), "browser_address_bar_alt_d"),
        ):
            try:
                self.automation.hotkey(*shortcut)
                self.sleep(0.12)
            except Exception:
                continue
            current = self._capture_context(refresh=True)
            failure = self._unexpected_modal_reason(current, expected_app=browser_name)
            if not failure:
                return target_name
        return ""

    def _visible_site_navigation(
        self,
        site_name: str,
        browser_name: str,
        step_name: str,
    ) -> Tuple[bool, Dict[str, Any]]:
        url = str(self.config.get("url_aliases", {}).get(site_name, f"https://{site_name}"))
        destination_text = re.sub(r"^https?://", "", url).strip("/")
        return self._visible_address_navigation(
            browser_name=browser_name,
            destination_text=destination_text,
            expected_site=site_name,
            step_name=step_name,
        )

    def _visible_google_search(
        self,
        query: str,
        browser_name: str,
        step_name: str,
    ) -> Tuple[bool, Dict[str, Any]]:
        reuse_success, reuse_detail = self._visible_google_search_in_current_tab(
            query=query,
            browser_name=browser_name,
            step_name=step_name,
        )
        if reuse_success:
            return True, reuse_detail

        fresh_tab_success, fresh_tab_detail = self._visible_google_search_via_new_tab(
            query=query,
            browser_name=browser_name,
            step_name=step_name,
        )
        if fresh_tab_success:
            return True, fresh_tab_detail
        if reuse_detail.get("context_failure") and not fresh_tab_detail.get("context_failure"):
            fresh_tab_detail["context_failure"] = reuse_detail["context_failure"]
        fresh_tab_detail.setdefault("fallbacks_tried", []).append("current_tab_reuse")
        return False, fresh_tab_detail

    def _visible_google_search_in_current_tab(
        self,
        query: str,
        browser_name: str,
        step_name: str,
    ) -> Tuple[bool, Dict[str, Any]]:

        nav_success, nav_detail = self._visible_site_navigation("google", browser_name, f"{step_name}_open_google")
        if not nav_success:
            nav_detail["step"] = step_name
            return False, nav_detail
        before = self._capture_context(refresh=True)
        target_candidates = (
            ["google_results_search_bar", "google_search_bar"]
            if self._google_results_page_context(before)
            else ["google_search_bar", "google_results_search_bar"]
        )
        target_name = ""
        for candidate in target_candidates:
            if self._click_visible_hint(candidate, expected_app=browser_name, expected_site="google"):
                target_name = candidate
                break
        if not target_name:
            return False, self._failure_detail(
                step=step_name,
                strategy="visible_google_search",
                verification="strict_real",
                before=before,
                reason="No pude enfocar un campo visible de Google.",
                text=query,
                target_control_used="google_search_bar",
            )
        try:
            self.automation.hotkey("ctrl", "a")
            self.sleep(0.05)
        except Exception:
            pass
        strategy = self._write_text_with_learning("text_entry:search", query, allow_clipboard=False)
        self.automation.press_keys(["enter"])
        self.sleep(1.0)
        after = self._capture_context(refresh=True)
        after_failure = self._unexpected_modal_reason(after, expected_app=browser_name, expected_site="google")
        snapshot = self.assistant.get_latest_vision_snapshot(refresh=True)
        result_hint = None
        if snapshot:
            result_hint = self.assistant.vision.find_ui_element("google_result_card_1", snapshot=snapshot)
        results_confirmed = self._google_results_context_matches_query(after, query)
        if not after_failure and self._context_matches_site(after, "google") and not results_confirmed:
            fallback_url = self._google_search_url(query)
            fallback_success, fallback_detail = self._visible_address_navigation(
                browser_name=browser_name,
                destination_text=fallback_url,
                expected_site="google",
                step_name=f"{step_name}_search_url",
            )
            if fallback_success:
                strategy = f"{strategy}+address_search_url"
                target_name = str(
                    fallback_detail.get("evidence", {}).get("target_control_used")
                    or "browser_address_bar"
                )
                after = self._capture_context(refresh=True)
                after_failure = self._unexpected_modal_reason(after, expected_app=browser_name, expected_site="google")
                snapshot = self.assistant.get_latest_vision_snapshot(refresh=True)
                result_hint = None
                if snapshot:
                    result_hint = self.assistant.vision.find_ui_element("google_result_card_1", snapshot=snapshot)
                results_confirmed = self._google_results_context_matches_query(after, query)
        success = (
            not after_failure
            and self._context_matches_site(after, "google")
            and result_hint is not None
            and results_confirmed
        )
        detail = {
            "step": step_name,
            "strategy": strategy,
            "verification": "visible_google_results",
            "query": query,
            "success": success,
            "context_failure": after_failure or "",
            "evidence": self._build_evidence(
                before=before,
                after=after,
                target_control_used=target_name,
                selected_text_preview=query[:120],
                verification_reason="" if success else (
                    after_failure
                    or "No se confirmo una pagina de resultados de Google para la busqueda."
                ),
                rescue_used=False,
            ),
        }
        return success, detail

    def _visible_google_search_via_new_tab(
        self,
        query: str,
        browser_name: str,
        step_name: str,
    ) -> Tuple[bool, Dict[str, Any]]:
        self._focus_or_launch_known_app(browser_name)
        before = self._capture_context(refresh=True)
        if self._browser_leave_site_prompt_visible(context=before, refresh=True):
            self._resolve_browser_leave_site_prompt(leave=True, browser_name=browser_name)
            before = self._capture_context(refresh=True)
        before_failure = self._unexpected_modal_reason(before, expected_app=browser_name)
        if before_failure:
            return False, self._failure_detail(
                step=step_name,
                strategy="fresh_tab_google_search",
                verification="strict_real",
                before=before,
                reason=before_failure,
                text=query,
                target_control_used="browser_new_tab",
            )
        try:
            self.automation.hotkey("ctrl", "t")
            self.sleep(0.18)
        except Exception as exc:
            return False, self._failure_detail(
                step=step_name,
                strategy="fresh_tab_google_search",
                verification="strict_real",
                before=before,
                reason=f"No pude abrir una pestana nueva del navegador: {exc}",
                text=query,
                target_control_used="browser_new_tab",
            )

        search_url = self._google_search_url(query)
        nav_success, nav_detail = self._visible_address_navigation(
            browser_name=browser_name,
            destination_text=search_url,
            expected_site="google",
            step_name=f"{step_name}_search_url",
        )
        if not nav_success:
            nav_detail["step"] = step_name
            nav_detail["strategy"] = f"{nav_detail.get('strategy', 'direct_typing')}+fresh_tab_search_url"
            return False, nav_detail

        after = self._capture_context(refresh=True)
        after_failure = self._unexpected_modal_reason(after, expected_app=browser_name, expected_site="google")
        snapshot = self.assistant.get_latest_vision_snapshot(refresh=True)
        result_hint = None
        if snapshot:
            result_hint = self.assistant.vision.find_ui_element("google_result_card_1", snapshot=snapshot)
        results_confirmed = self._google_results_context_matches_query(after, query)
        success = (
            not after_failure
            and self._context_matches_site(after, "google")
            and result_hint is not None
            and results_confirmed
        )
        target_control_used = str(
            nav_detail.get("evidence", {}).get("target_control_used") or "browser_address_bar"
        )
        detail = {
            "step": step_name,
            "strategy": f"{nav_detail.get('strategy', 'direct_typing')}+fresh_tab_search_url",
            "verification": "visible_google_results",
            "query": query,
            "success": success,
            "context_failure": after_failure or "",
            "evidence": self._build_evidence(
                before=before,
                after=after,
                target_control_used=target_control_used,
                selected_text_preview=query[:120],
                verification_reason="" if success else (
                    after_failure
                    or "No se confirmo una pagina de resultados de Google desde una pestana nueva."
                ),
                rescue_used=True,
            ),
        }
        if success:
            previous_tab_cleanup = self._close_previous_browser_tab_after_new_tab(
                browser_name=browser_name,
                step_name=f"{step_name}_close_previous_tab",
            )
            detail["evidence"]["previous_tab_cleanup"] = previous_tab_cleanup
            if previous_tab_cleanup.get("context_failure") and not detail.get("context_failure"):
                detail["context_failure"] = previous_tab_cleanup["context_failure"]
        return success, detail

    def _rotate_research_browser_tab_for_next_cycle(self, browser_name: str = "brave") -> Dict[str, Any]:
        step_name = "research_cycle_tab_rotation"
        before = self._capture_context(refresh=True)
        normalized_browser = normalize_text(browser_name)
        active_app = normalize_text(before.get("active_app", ""))
        if active_app != normalized_browser and not self._context_title_matches_expected_app(
            before.get("window_title", ""),
            normalized_browser,
        ):
            return {
                "step": step_name,
                "strategy": "open_clean_tab+close_previous_tab",
                "verification": "browser_tab_rotation",
                "success": False,
                "skipped": True,
                "context_failure": "",
                "reason": f"No rote pestanas porque {browser_name} no esta activo.",
                "evidence": self._build_evidence(
                    before=before,
                    after=before,
                    target_control_used="browser_tab_rotation",
                    selected_text_preview="",
                    verification_reason=f"No rote pestanas porque {browser_name} no esta activo.",
                    rescue_used=False,
                ),
            }
        if self._browser_leave_site_prompt_visible(context=before, refresh=True):
            self._resolve_browser_leave_site_prompt(leave=True, browser_name=browser_name)
            before = self._capture_context(refresh=True)
        before_failure = self._unexpected_modal_reason(before, expected_app=browser_name)
        if before_failure:
            return self._browser_tab_rotation_detail(
                step_name=step_name,
                before=before,
                after=before,
                success=False,
                reason=before_failure,
                skipped=False,
                rescue_used=False,
            )
        try:
            self.automation.hotkey("ctrl", "t")
            self.sleep(0.18)
        except Exception as exc:
            return self._browser_tab_rotation_detail(
                step_name=step_name,
                before=before,
                after=self._capture_context(refresh=True),
                success=False,
                reason=f"No pude abrir una pestana limpia para el siguiente ciclo: {exc}",
                skipped=False,
                rescue_used=False,
            )
        return self._close_previous_browser_tab_after_new_tab(
            browser_name=browser_name,
            step_name=step_name,
            before=before,
        )

    def _close_previous_browser_tab_after_new_tab(
        self,
        browser_name: str,
        step_name: str,
        before: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        before = before or self._capture_context(refresh=True)
        try:
            self.automation.hotkey("ctrl", "shift", "tab")
            self.sleep(0.08)
            self.automation.hotkey("ctrl", "w")
            self.sleep(0.18)
        except Exception as exc:
            return self._browser_tab_rotation_detail(
                step_name=step_name,
                before=before,
                after=self._capture_context(refresh=True),
                success=False,
                reason=f"No pude cerrar la pestana anterior del navegador: {exc}",
                skipped=False,
                rescue_used=True,
            )
        after = self._capture_context(refresh=True)
        if self._browser_leave_site_prompt_visible(context=after, refresh=True):
            self._resolve_browser_leave_site_prompt(leave=True, browser_name=browser_name)
            after = self._capture_context(refresh=True)
        after_failure = self._unexpected_modal_reason(after, expected_app=browser_name)
        normalized_browser = normalize_text(browser_name)
        active_app = normalize_text(after.get("active_app", ""))
        browser_still_active = active_app == normalized_browser or self._context_title_matches_expected_app(
            after.get("window_title", ""),
            normalized_browser,
        )
        success = not after_failure and browser_still_active
        reason = "" if success else (after_failure or f"No pude confirmar {browser_name} activo tras cerrar la pestana anterior.")
        return self._browser_tab_rotation_detail(
            step_name=step_name,
            before=before,
            after=after,
            success=success,
            reason=reason,
            skipped=False,
            rescue_used=True,
        )

    def _browser_tab_rotation_detail(
        self,
        step_name: str,
        before: Dict[str, str],
        after: Dict[str, str],
        success: bool,
        reason: str,
        skipped: bool,
        rescue_used: bool,
    ) -> Dict[str, Any]:
        return {
            "step": step_name,
            "strategy": "open_clean_tab+close_previous_tab",
            "verification": "browser_tab_rotation",
            "success": bool(success),
            "skipped": bool(skipped),
            "context_failure": "" if success or skipped else reason,
            "reason": reason,
            "evidence": self._build_evidence(
                before=before,
                after=after,
                target_control_used="browser_tab_rotation",
                selected_text_preview="",
                verification_reason=reason,
                rescue_used=rescue_used,
            ),
        }

    def _visible_youtube_search(
        self,
        query: str,
        browser_name: str,
        step_name: str,
    ) -> Tuple[bool, Dict[str, Any]]:
        nav_success, nav_detail = self._visible_site_navigation("youtube", browser_name, f"{step_name}_open_youtube")
        if not nav_success:
            nav_detail["step"] = step_name
            return False, nav_detail
        before = self._capture_context(refresh=True)
        if not self._click_visible_hint("youtube_search_bar", expected_app=browser_name, expected_site="youtube"):
            return self._visible_youtube_search_by_url(
                query=query,
                browser_name=browser_name,
                step_name=step_name,
                before=before,
                reason="No pude enfocar la barra visible de YouTube.",
            )
        strategy = self._write_text_with_learning("text_entry:search", query, allow_clipboard=False)
        try:
            if self._click_visible_hint("youtube_search_button", expected_app=browser_name, expected_site="youtube"):
                self.sleep(0.2)
            else:
                self.automation.press_keys(["enter"])
        except Exception:
            self.automation.press_keys(["enter"])
        self.sleep(1.0)
        after = self._capture_context(refresh=True)
        after_failure = self._unexpected_modal_reason(after, expected_app=browser_name, expected_site="youtube")
        success = not after_failure and self._context_matches_site(after, "youtube")
        if not success:
            return self._visible_youtube_search_by_url(
                query=query,
                browser_name=browser_name,
                step_name=step_name,
                before=before,
                reason=after_failure or "No se confirmo la busqueda visible en YouTube.",
                previous_strategy=strategy,
            )
        detail = {
            "step": step_name,
            "strategy": strategy,
            "verification": "youtube_results_visible",
            "query": query,
            "success": success,
            "context_failure": after_failure or "",
            "evidence": self._build_evidence(
                before=before,
                after=after,
                target_control_used="youtube_search_bar",
                selected_text_preview=query[:120],
                verification_reason="" if success else (after_failure or "No se confirmo la busqueda visible en YouTube."),
                rescue_used=False,
            ),
        }
        return success, detail

    def _visible_youtube_search_by_url(
        self,
        query: str,
        browser_name: str,
        step_name: str,
        before: Dict[str, str],
        reason: str,
        previous_strategy: str = "",
    ) -> Tuple[bool, Dict[str, Any]]:
        fallback_url = self._youtube_search_url(query)
        fallback_success, fallback_detail = self._visible_address_navigation(
            browser_name=browser_name,
            destination_text=fallback_url,
            expected_site="youtube",
            step_name=f"{step_name}_search_url",
        )
        after = self._capture_context(refresh=True)
        after_failure = self._unexpected_modal_reason(after, expected_app=browser_name, expected_site="youtube")
        success = fallback_success and not after_failure and self._context_matches_site(after, "youtube")
        strategy = str(fallback_detail.get("strategy", "address_search_url"))
        if previous_strategy:
            strategy = f"{previous_strategy}+{strategy}"
        return success, {
            "step": step_name,
            "strategy": strategy,
            "verification": "youtube_results_url",
            "query": query,
            "success": success,
            "context_failure": after_failure or ("" if success else reason),
            "evidence": self._build_evidence(
                before=before,
                after=after,
                target_control_used=str(
                    fallback_detail.get("evidence", {}).get("target_control_used")
                    or "browser_address_bar"
                ),
                selected_text_preview=query[:120],
                verification_reason="" if success else (after_failure or reason),
                rescue_used=True,
            ),
        }

    def _visible_open_google_result(
        self,
        query: str,
        index: int = 1,
        step_name: str = "google_open_result",
    ) -> Tuple[bool, Dict[str, Any]]:
        search_success, search_detail = self._visible_google_search(query=query, browser_name="brave", step_name=f"{step_name}_search")
        if not search_success:
            search_detail["step"] = step_name
            return False, search_detail
        before = self._capture_context(refresh=True)
        baseline_title = normalize_text(before.get("window_title", ""))
        opened = self.task_executor._open_google_result(index)
        self.sleep(1.1)
        after = self._capture_context(refresh=True)
        after_title = normalize_text(after.get("window_title", ""))
        after_failure = self._unexpected_modal_reason(after, expected_app="brave")
        success = opened and not after_failure and bool(after_title) and after_title != baseline_title
        detail = {
            "step": step_name,
            "strategy": f"google_result_card_{index}",
            "verification": "active_window_title_changed",
            "query": query,
            "success": success,
            "context_failure": after_failure or "",
            "evidence": self._build_evidence(
                before=before,
                after=after,
                target_control_used=f"google_result_card_{index}",
                selected_text_preview="",
                verification_reason="" if success else (after_failure or "El titulo de la pagina no cambio tras abrir el resultado."),
                rescue_used=False,
            ),
        }
        return success, detail

    def _youtube_search_attempt(self, query: str) -> Tuple[bool, Dict[str, Any]]:
        return self._visible_youtube_search(query=query, browser_name="brave", step_name="youtube_search")

    def _visible_open_youtube_result(
        self,
        query: str,
        index: int = 1,
        step_name: str = "youtube_open_result",
    ) -> Tuple[bool, Dict[str, Any]]:
        search_success, search_detail = self._visible_youtube_search(
            query=query,
            browser_name="brave",
            step_name=f"{step_name}_search",
        )
        if not search_success:
            search_detail["step"] = step_name
            return False, search_detail
        before = self._capture_context(refresh=True)
        baseline_title = normalize_text(before.get("window_title", ""))
        target_candidates = [f"youtube_result_title_{index}", f"youtube_result_card_{index}"]
        if index == 1:
            target_candidates.extend(["youtube_result_title", "youtube_result_card"])
        target_used = ""
        for target_name in target_candidates:
            if self._click_visible_hint(target_name, expected_app="brave", expected_site="youtube"):
                target_used = target_name
                break
        if not target_used:
            return False, self._failure_detail(
                step=step_name,
                strategy="youtube_result_visible_click",
                verification="active_window_title_changed",
                before=before,
                reason="No se encontro un resultado visible confiable de YouTube para abrir.",
                text=query,
                target_control_used=f"youtube_result_card_{index}",
            )
        self.sleep(1.2)
        after = self._capture_context(refresh=True)
        after_title = normalize_text(after.get("window_title", ""))
        after_failure = self._unexpected_modal_reason(after, expected_app="brave")
        success = not after_failure and bool(after_title) and after_title != baseline_title
        detail = {
            "step": step_name,
            "strategy": f"{target_used}_visible",
            "verification": "active_window_title_changed",
            "query": query,
            "success": success,
            "context_failure": after_failure or "",
            "evidence": self._build_evidence(
                before=before,
                after=after,
                target_control_used=target_used,
                selected_text_preview=query[:120],
                verification_reason="" if success else (
                    after_failure or "El titulo del video/pagina no cambio tras el click visible en YouTube."
                ),
                rescue_used=False,
            ),
        }
        return success, detail

    def _youtube_open_result_attempt(self, query: str) -> Tuple[bool, Dict[str, Any]]:
        visible_success, visible_detail = self._visible_open_youtube_result(
            query=query,
            index=1,
            step_name="youtube_open_result",
        )
        if visible_success:
            return True, visible_detail
        settings = self._skill_settings("youtube")
        tab_strategies = [int(value) for value in settings.get("result_tab_strategies", [3, 5, 7])]
        baseline = self._capture_context(refresh=True)
        baseline_title = normalize_text(baseline.get("window_title", ""))
        for tab_count in tab_strategies:
            for _ in range(tab_count):
                self.automation.press_keys(["tab"])
                self.sleep(0.06)
            self.automation.press_keys(["enter"])
            self.sleep(1.3)
            after = self._capture_context(refresh=True)
            after_title = normalize_text(after.get("window_title", ""))
            after_failure = self._unexpected_modal_reason(after, expected_app="brave")
            success = not after_failure and bool(after_title) and after_title != baseline_title
            if success:
                self.learning.record_strategy_result("skill:youtube_open_result", f"tab_{tab_count}", True)
                return True, {
                    "step": "youtube_open_result",
                    "strategy": f"tab_{tab_count}",
                    "verification": "active_window_title_changed",
                    "success": True,
                    "context_failure": "",
                    "evidence": self._build_evidence(
                        before=baseline,
                        after=after,
                        target_control_used="youtube_result_tab_navigation",
                        selected_text_preview=query[:120],
                        verification_reason="",
                        rescue_used=False,
                    ),
                }
            self.learning.record_strategy_result("skill:youtube_open_result", f"tab_{tab_count}", False)
            self.automation.hotkey("alt", "left")
            self.sleep(1.0)
        return False, self._failure_detail(
            step="youtube_open_result",
            strategy="youtube_result_visible_click+tab_navigation",
            verification="active_window_title_changed",
            before=baseline,
            reason="No se logro abrir un resultado visible de YouTube.",
            text=query,
            target_control_used="youtube_result_tab_navigation",
        )

    def _youtube_goal_workflow(
        self,
        goal: str,
        preopened_detail: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        query = goal.strip() or "tutorial teclado rapido"
        if preopened_detail is not None:
            success = bool(preopened_detail.get("success"))
            detail = dict(preopened_detail)
        else:
            success, detail = self._youtube_open_result_attempt(query)
        detail["step"] = "youtube_goal_workflow"
        detail["goal"] = goal
        if not success:
            detail["justification"] = ""
            return False, detail

        settings = self._skill_settings("youtube")
        minimum_visible_chars = int(settings.get("minimum_visible_capture_chars", 180))
        minimum_transcript_chars = int(settings.get("minimum_transcript_capture_chars", 220))
        capture = self._capture_youtube_learning_evidence(
            minimum_visible_chars=minimum_visible_chars,
            minimum_transcript_chars=minimum_transcript_chars,
        )
        captured_chars = int(capture.get("captured_chars", 0) or 0)
        capture_success = bool(capture.get("success"))
        evidence = dict(detail.get("evidence", {}) if isinstance(detail.get("evidence", {}), dict) else {})
        evidence.update(
            self._standardized_learning_evidence_fields(
                source_kind="youtube_video",
                transcript_available=bool(capture.get("transcript_available")),
                transcript_chars=int(capture.get("transcript_chars", 0) or 0),
                visible_text_chars=int(capture.get("visible_text_chars", 0) or 0),
                page_usefulness_label=str(capture.get("page_usefulness_label", "poor") or "poor"),
                verification_source=str(capture.get("verification_source", "youtube_insufficient_capture")),
                current_session_verified=capture_success,
            )
        )
        evidence.update(
            {
                "captured_chars": captured_chars,
                "visible_text_verification": "youtube_transcript_or_visible_text",
                "used_scrolls": int(capture.get("used_scrolls", 0) or 0),
                "transcript_target_control_used": str(capture.get("target_control_used", "") or ""),
            }
        )
        detail.update(
            {
                "strategy": f"{detail.get('strategy', 'youtube_open_result')}+transcript_or_visible_text",
                "verification": "youtube_transcript_or_visible_text",
                "captured_chars": captured_chars,
                "success": capture_success,
                "context_failure": "" if capture_success else (
                    str(capture.get("failure_reason", "") or (
                        "No se capturo transcript ni texto visible suficiente del video de YouTube."
                    ))
                ),
                "evidence": evidence,
                "justification": str(capture.get("justification", "") or ""),
            }
        )
        return capture_success, detail

    def _capture_youtube_learning_evidence(
        self,
        minimum_visible_chars: int,
        minimum_transcript_chars: int,
    ) -> Dict[str, Any]:
        settings = self._skill_settings("youtube")
        transcript_capture = {
            "text": "",
            "success": False,
            "transcript_available": False,
            "target_control_used": "",
            "context_failure": "",
        }
        if bool(settings.get("prefer_transcript_first", True)):
            transcript_capture = self._capture_youtube_transcript_text(
                minimum_chars=minimum_transcript_chars
            )

        visible_capture = self._capture_youtube_page_text(minimum_chars=minimum_visible_chars)
        transcript_text = str(transcript_capture.get("text", "") or "")
        visible_text = str(visible_capture.get("text", "") or "")
        transcript_chars = len(transcript_text.strip())
        visible_chars = len(visible_text.strip())
        transcript_available = bool(transcript_capture.get("success"))
        visible_success = bool(visible_capture.get("success"))
        success = transcript_available or visible_success
        if transcript_available:
            verification_source = "youtube_transcript_ocr"
            usefulness = "useful"
            justification = "Video abierto, transcript capturado y evidencia visible disponible."
        elif visible_success:
            verification_source = "youtube_visible_ocr"
            usefulness = "mixed" if transcript_capture.get("attempted") else "useful"
            justification = "Video abierto y texto visible util capturado dentro de YouTube."
        else:
            verification_source = "youtube_insufficient_capture"
            usefulness = "poor"
            justification = ""

        failure_reason = ""
        if not success:
            if transcript_capture.get("attempted") and not transcript_capture.get("transcript_available"):
                failure_reason = "Se intento abrir la transcripcion, pero no hubo transcript util en la sesion actual."
            if visible_chars <= 0:
                failure_reason = (
                    f"{failure_reason} No hubo OCR visible util del video." if failure_reason
                    else "No hubo OCR visible util del video."
                )
            elif visible_chars < minimum_visible_chars:
                failure_reason = (
                    f"{failure_reason} El OCR visible quedo por debajo de {minimum_visible_chars} caracteres utiles."
                    if failure_reason
                    else f"El OCR visible quedo por debajo de {minimum_visible_chars} caracteres utiles."
                )

        return {
            "success": success,
            "transcript_available": transcript_available,
            "transcript_chars": transcript_chars,
            "visible_text_chars": visible_chars,
            "captured_chars": max(transcript_chars, visible_chars),
            "page_usefulness_label": usefulness,
            "verification_source": verification_source,
            "used_scrolls": int(visible_capture.get("used_scrolls", 0) or 0),
            "target_control_used": str(transcript_capture.get("target_control_used", "") or ""),
            "failure_reason": failure_reason.strip(),
            "justification": justification,
        }

    def _capture_youtube_transcript_text(self, minimum_chars: int) -> Dict[str, Any]:
        transcript_panel = self._open_youtube_transcript_panel()
        if not transcript_panel.get("success"):
            return {
                "text": "",
                "success": False,
                "attempted": True,
                "transcript_available": False,
                "target_control_used": str(transcript_panel.get("target_control_used", "") or ""),
                "context_failure": str(transcript_panel.get("context_failure", "") or ""),
            }
        captured = self.task_executor.collect_page_text(max_scrolls_per_page=0) or ""
        looks_unhelpful = bool(
            hasattr(self.task_executor, "_looks_unhelpful")
            and self.task_executor._looks_unhelpful(captured)
        )
        text = str(captured or "")
        chars = len(text.strip())
        success = chars >= minimum_chars and not looks_unhelpful
        return {
            "text": text,
            "success": success,
            "attempted": True,
            "transcript_available": success,
            "target_control_used": str(transcript_panel.get("target_control_used", "") or ""),
            "context_failure": "" if success else str(
                transcript_panel.get("context_failure", "") or "No se capto transcript suficiente del video."
            ),
        }

    def _open_youtube_transcript_panel(self) -> Dict[str, Any]:
        before = self._capture_context(refresh=True)
        failure = self._unexpected_modal_reason(before, expected_app="brave", expected_site="youtube")
        if failure:
            return {
                "success": False,
                "target_control_used": "youtube_transcript_toggle",
                "context_failure": failure,
            }

        if self._click_visible_hint("youtube_transcript_toggle", expected_app="brave", expected_site="youtube"):
            self.sleep(0.45)
            after = self._capture_context(refresh=True)
            after_failure = self._unexpected_modal_reason(after, expected_app="brave", expected_site="youtube")
            return {
                "success": not after_failure,
                "target_control_used": "youtube_transcript_toggle",
                "context_failure": after_failure or "",
            }

        if self._click_visible_hint("youtube_more_actions_button", expected_app="brave", expected_site="youtube"):
            self.sleep(0.2)
            if self._click_visible_hint("youtube_transcript_toggle", expected_app="brave", expected_site="youtube"):
                self.sleep(0.45)
                after = self._capture_context(refresh=True)
                after_failure = self._unexpected_modal_reason(after, expected_app="brave", expected_site="youtube")
                return {
                    "success": not after_failure,
                    "target_control_used": "youtube_more_actions_button+youtube_transcript_toggle",
                    "context_failure": after_failure or "",
                }

        return {
            "success": False,
            "target_control_used": "youtube_transcript_toggle",
            "context_failure": "No se encontro un control visible confiable para abrir la transcripcion de YouTube.",
        }

    def _capture_youtube_page_text(self, minimum_chars: int) -> Dict[str, Any]:
        best_text = ""
        best_scrolls = 0
        success = False
        for scrolls in (0, 1):
            captured = self.task_executor.collect_page_text(max_scrolls_per_page=scrolls) or ""
            if len(captured.strip()) >= len(best_text.strip()):
                best_text = captured
                best_scrolls = scrolls
            looks_unhelpful = bool(
                hasattr(self.task_executor, "_looks_unhelpful")
                and self.task_executor._looks_unhelpful(captured)
            )
            if len(captured.strip()) >= minimum_chars and not looks_unhelpful:
                best_text = captured
                best_scrolls = scrolls
                success = True
                break
        return {
            "text": best_text,
            "success": success,
            "used_scrolls": best_scrolls,
        }

    def _research_query_attempt(self, query: str, result_index: int = 1) -> Tuple[bool, Dict[str, Any]]:
        search_success, search_detail = self._visible_google_search(
            query=query,
            browser_name="brave",
            step_name="research_query_attempt",
        )
        if not search_success:
            evidence = dict(search_detail.get("evidence", {}) if isinstance(search_detail.get("evidence", {}), dict) else {})
            evidence["hard_failure"] = False
            search_detail.update(
                {
                    "step": "research_query_attempt",
                    "verification": "visible_google_results",
                    "opened": False,
                    "captured_chars": 0,
                    "success": False,
                    "failure_stage": "visible_google_results",
                    "hard_failure": False,
                    "evidence": evidence,
                }
            )
            return False, search_detail

        minimum_chars = int(self._skill_settings("research").get("minimum_query_capture_chars", 500))
        candidate_indices = self._expand_research_result_indices([result_index], max_candidates=3)
        google_scene = TaskExecutor.detect_research_scene(
            "Google - Brave",
            capture_context={"active_site": "google"},
        )
        last_failure = self._research_failure_detail(
            query=query,
            result_index=max(1, int(result_index)),
            stage="stuck_on_google",
            reason="No se obtuvo una transicion valida desde Google.",
            evidence=search_detail.get("evidence", {}),
            **self._research_scene_fields(google_scene),
            emit_feedback=False,
        )
        baseline = self._capture_context(refresh=True)
        for attempt_index, candidate_index in enumerate(candidate_indices):
            rescue_used = attempt_index > 0
            baseline = self._capture_context(refresh=True)
            baseline_title = normalize_text(baseline.get("window_title", ""))
            if not self._is_google_results_context(baseline, query=query):
                restored = self._research_restore_google_results(query)
                baseline = self._capture_context(refresh=True)
                baseline_title = normalize_text(baseline.get("window_title", ""))
                if not restored:
                    last_failure = self._research_failure_detail(
                        query=query,
                        result_index=candidate_index,
                        stage="back_navigation_failed",
                        reason="No pude volver a Google para reintentar otro resultado.",
                        evidence=search_detail.get("evidence", {}),
                        rescue_used=rescue_used,
                        hard_failure=False,
                    )
                    continue
            opened = self.task_executor._open_google_result(max(1, int(candidate_index)))
            current = self._wait_for_research_page_open(baseline_title)
            page_title = str(current.get("window_title", "") or f"resultado_{max(1, int(candidate_index))}")
            after_open_context_failure = self._unexpected_modal_reason(current, expected_app="brave")
            if after_open_context_failure:
                context_quality = self._classify_research_source(
                    query,
                    page_title,
                    "",
                    capture_context=self._build_research_capture_context(
                        page_title,
                        current,
                        {
                            "modal_detected": "modal" in normalize_text(after_open_context_failure)
                            or "dialogo" in normalize_text(after_open_context_failure),
                            "file_dialog_detected": self._open_file_dialog_visible(current),
                            "visible_text_verified": False,
                        },
                    ),
                )
                last_failure = self._research_failure_detail(
                    query=query,
                    result_index=candidate_index,
                    stage="wrong_active_window",
                    reason=after_open_context_failure,
                    opened=bool(opened),
                    page_title=page_title,
                    evidence=search_detail.get("evidence", {}),
                    rescue_used=rescue_used,
                    hard_failure=False,
                    source_kind=str(context_quality.get("source_kind", "web_page") or "web_page"),
                    title_matches_query=bool(context_quality.get("title_matches_query")),
                    source_quality_reason=str(context_quality.get("reason", "") or ""),
                    **self._research_scene_fields(context_quality),
                )
                self._research_restore_google_results(query)
                continue
            if (
                not opened
                or normalize_text(page_title) == baseline_title
                or self._is_google_results_context(current, query=query)
            ):
                keyboard_opened, keyboard_after, keyboard_strategy = self._research_open_result_with_tab_navigation(
                    baseline_title
                )
                if keyboard_opened:
                    current = keyboard_after
                    page_title = str(current.get("window_title", "") or f"resultado_{max(1, int(candidate_index))}")
                    capture = self._capture_research_page_text(minimum_chars=minimum_chars)
                    page_text = str(capture.get("text", "") or "")
                    captured_chars = len(page_text.strip())
                    capture_context = self._build_research_capture_context(page_title, current, capture)
                    source_quality = self._classify_research_source(
                        query,
                        page_title,
                        page_text,
                        capture_context=capture_context,
                    )
                    scene_fields = self._research_scene_fields(source_quality)
                    if capture.get("success") and bool(source_quality.get("counts_as_useful")):
                        navigation_restored = self._return_to_google_results()
                        detail = {
                            "step": "research_query_attempt",
                            "strategy": f"{search_detail.get('strategy', 'visible_google_search')}+{keyboard_strategy}",
                            "verification": "page_text_quality",
                            "query": query,
                            "result_index": max(1, int(candidate_index)),
                            "opened": True,
                            "page_title": page_title,
                            "captured_chars": captured_chars,
                            "success": True,
                            "context_failure": "",
                            "rescue_used": True,
                            "failure_stage": "",
                            "scene_id": scene_fields["scene_id"],
                            "scene_variant": scene_fields["scene_variant"],
                            "emergency_feedback": scene_fields["emergency_feedback"],
                            "evidence": self._research_query_evidence(
                                search_detail.get("evidence", {}),
                                page_title=page_title,
                                captured_chars=captured_chars,
                                rescue_used=True,
                                hard_failure=not navigation_restored,
                                page_usefulness_label=str(source_quality.get("page_usefulness_label", "useful") or "useful"),
                                useful_source_count=int(source_quality.get("useful_source_count", 1) or 1),
                                current_session_verified=True,
                                verification_source="research_page_capture_rescue",
                                source_kind=str(source_quality.get("source_kind", "web_page") or "web_page"),
                                title_matches_query=bool(source_quality.get("title_matches_query")),
                                source_quality_reason=str(source_quality.get("reason", "") or ""),
                                scene_id=scene_fields["scene_id"],
                                scene_variant=scene_fields["scene_variant"],
                                emergency_feedback=scene_fields["emergency_feedback"],
                                read_policy=scene_fields["read_policy"],
                                ignore_policy=scene_fields["ignore_policy"],
                                valid_exit_rule=scene_fields["valid_exit_rule"],
                            ),
                        }
                        return True, detail
                    if capture.get("success"):
                        last_failure = self._research_failure_detail(
                            query=query,
                            result_index=candidate_index,
                            stage="page_poor_quality",
                            reason=str(source_quality.get("reason", "") or "La fuente abierta no conto como util."),
                            evidence=search_detail.get("evidence", {}),
                            opened=True,
                            page_title=page_title,
                            captured_chars=captured_chars,
                            rescue_used=True,
                            hard_failure=False,
                            source_kind=str(source_quality.get("source_kind", "web_page") or "web_page"),
                            title_matches_query=bool(source_quality.get("title_matches_query")),
                            source_quality_reason=str(source_quality.get("reason", "") or ""),
                            **scene_fields,
                        )
                        self._research_restore_google_results(query)
                        continue
                last_failure = self._research_failure_detail(
                    query=query,
                    result_index=candidate_index,
                    stage="stuck_on_google",
                    reason="El click no saco al navegador de la pagina de resultados.",
                    opened=bool(opened),
                    page_title=page_title,
                    evidence=search_detail.get("evidence", {}),
                    rescue_used=rescue_used,
                    hard_failure=False,
                    **self._research_scene_fields(google_scene),
                )
                self._research_restore_google_results(query)
                continue
            capture = self._capture_research_page_text(minimum_chars=minimum_chars)
            page_text = str(capture.get("text", "") or "")
            captured_chars = len(page_text.strip())
            capture_context = self._build_research_capture_context(page_title, current, capture)
            source_quality = self._classify_research_source(
                query,
                page_title,
                page_text,
                capture_context=capture_context,
            )
            scene_fields = self._research_scene_fields(source_quality)
            if capture.get("success"):
                if not bool(source_quality.get("counts_as_useful")):
                    last_failure = self._research_failure_detail(
                        query=query,
                        result_index=candidate_index,
                        stage="page_poor_quality",
                        reason=str(source_quality.get("reason", "") or "La fuente abierta no conto como util."),
                        evidence=search_detail.get("evidence", {}),
                        opened=True,
                        page_title=page_title,
                        captured_chars=captured_chars,
                        rescue_used=rescue_used,
                        hard_failure=False,
                        source_kind=str(source_quality.get("source_kind", "web_page") or "web_page"),
                        title_matches_query=bool(source_quality.get("title_matches_query")),
                        source_quality_reason=str(source_quality.get("reason", "") or ""),
                        **scene_fields,
                    )
                    self._research_restore_google_results(query)
                    continue
                navigation_restored = self._return_to_google_results()
                detail = {
                    "step": "research_query_attempt",
                    "strategy": search_detail.get("strategy", "visible_google_search"),
                    "verification": "page_text_quality",
                    "query": query,
                    "result_index": max(1, int(candidate_index)),
                    "opened": True,
                    "page_title": page_title,
                    "captured_chars": captured_chars,
                    "success": True,
                    "context_failure": "",
                    "rescue_used": rescue_used,
                    "failure_stage": "",
                    "scene_id": scene_fields["scene_id"],
                    "scene_variant": scene_fields["scene_variant"],
                    "emergency_feedback": scene_fields["emergency_feedback"],
                    "evidence": self._research_query_evidence(
                        search_detail.get("evidence", {}),
                        page_title=page_title,
                        captured_chars=captured_chars,
                        rescue_used=rescue_used,
                        hard_failure=not navigation_restored,
                        page_usefulness_label=str(source_quality.get("page_usefulness_label", "useful") or "useful"),
                        useful_source_count=int(source_quality.get("useful_source_count", 1) or 1),
                        current_session_verified=True,
                        verification_source="research_page_capture",
                        source_kind=str(source_quality.get("source_kind", "web_page") or "web_page"),
                        title_matches_query=bool(source_quality.get("title_matches_query")),
                        source_quality_reason=str(source_quality.get("reason", "") or ""),
                        scene_id=scene_fields["scene_id"],
                        scene_variant=scene_fields["scene_variant"],
                        emergency_feedback=scene_fields["emergency_feedback"],
                        read_policy=scene_fields["read_policy"],
                        ignore_policy=scene_fields["ignore_policy"],
                        valid_exit_rule=scene_fields["valid_exit_rule"],
                    ),
                }
                return True, detail
            failure_stage = "page_poor_quality"
            failure_reason = (
                f"No se abrio un resultado con al menos {minimum_chars} caracteres utiles; "
                "no se considera investigacion verificada."
            )
            hard_failure = True
            if capture.get("file_dialog_detected"):
                failure_stage = "file_dialog_detected"
                failure_reason = str(source_quality.get("reason", "") or "Hay un dialogo de archivo bloqueando la captura.")
                hard_failure = False
            elif capture.get("modal_detected"):
                failure_stage = "modal_detected"
                failure_reason = str(
                    source_quality.get("reason", "")
                    or capture.get("modal_reason")
                    or "Hay un modal bloqueando la captura de la pagina."
                )
                hard_failure = False
            elif capture.get("ocr_unavailable"):
                failure_stage = "ocr_unavailable"
                failure_reason = "No hubo lectura OCR util en la pagina abierta."
                hard_failure = False
            elif captured_chars == 0:
                failure_stage = "opened_result_but_empty"
                failure_reason = "Se abrio una pagina, pero la captura quedo vacia."
                hard_failure = False
            last_failure = self._research_failure_detail(
                query=query,
                result_index=candidate_index,
                stage=failure_stage,
                reason=failure_reason,
                opened=True,
                page_title=page_title,
                captured_chars=captured_chars,
                evidence=search_detail.get("evidence", {}),
                rescue_used=rescue_used,
                hard_failure=hard_failure,
                source_kind=str(source_quality.get("source_kind", "web_page") or "web_page"),
                title_matches_query=bool(source_quality.get("title_matches_query")),
                source_quality_reason=str(source_quality.get("reason", "") or ""),
                **scene_fields,
            )
            self._research_restore_google_results(query)
        return False, last_failure

    def _wait_for_research_page_open(
        self,
        baseline_title: str,
        timeout_seconds: Optional[float] = None,
    ) -> Dict[str, str]:
        timeout = float(
            timeout_seconds
            or self._skill_settings("research").get("result_open_timeout_seconds", 1.6)
        )
        deadline = time.time() + max(0.4, timeout)
        last = self._capture_context(refresh=True)
        baseline = normalize_text(baseline_title)
        while time.time() < deadline:
            current = self._capture_context(refresh=True)
            current_title = normalize_text(current.get("window_title", ""))
            last = current
            if current_title and current_title != baseline and not self._is_google_results_context(current):
                return current
            self.sleep(0.18)
        return last

    def _capture_research_page_text(self, minimum_chars: int) -> Dict[str, Any]:
        """Capture research page text with strict validation."""
        best_text = ""
        best_scrolls = 0
        success = False
        
        # Check for unexpected modals or browser dialogs FIRST
        context = self._capture_context(refresh=True)
        if self._open_file_dialog_visible(context):
            return {
                "text": "",
                "success": False,
                "used_scrolls": 0,
                "ocr_unavailable": True,
                "modal_detected": False,
                "file_dialog_detected": True,
                "modal_reason": "",
            }
        modal_check = self._unexpected_modal_reason(context, expected_app="brave")
        if modal_check:
            return {
                "text": "",
                "success": False,
                "used_scrolls": 0,
                "ocr_unavailable": True,
                "modal_detected": True,
                "file_dialog_detected": False,
                "modal_reason": modal_check,
            }
        
        for scrolls in (0, 1, 2):
            captured = self.task_executor.collect_page_text(max_scrolls_per_page=scrolls) or ""
            captured_strip = captured.strip()
            
            if len(captured_strip) >= len(best_text.strip()):
                best_text = captured
                best_scrolls = scrolls
            
            # Check if text looks unhelpful
            looks_unhelpful = bool(
                hasattr(self.task_executor, "_looks_unhelpful")
                and self.task_executor._looks_unhelpful(captured)
            )
            
            # Check for common modal/error keywords in captured text
            modal_keywords = (
                "save as",
                "do you want to save",
                "do you want to save your changes",
                "guardar como",
                "quieres guardar los cambios",
                "page not found",
                "404 not found",
                "404 error",
                "file name:",
                "nombre de archivo",
            )
            has_modal_keywords = any(keyword in captured_strip.lower() for keyword in modal_keywords)
            
            if len(captured_strip) >= minimum_chars and not looks_unhelpful and not has_modal_keywords:
                success = True
                best_text = captured
                best_scrolls = scrolls
                break
        
        return {
            "text": best_text,
            "success": success,
            "used_scrolls": best_scrolls,
            "captured_chars": len(best_text.strip()),
            "ocr_unavailable": not bool(getattr(self.assistant, "vision", None)) and len(best_text.strip()) == 0,
            "modal_detected": False,
            "file_dialog_detected": False,
        }

    def _return_to_google_results(self) -> bool:
        timeout = float(self._skill_settings("research").get("result_back_timeout_seconds", 1.0))
        if self._wait_for_google_results_context(timeout=0.1):
            return True
        current = self._capture_context(refresh=True)
        if self._browser_leave_site_prompt_visible(context=current, refresh=True):
            self._resolve_browser_leave_site_prompt(leave=True, browser_name="brave")
            if self._wait_for_google_results_context(timeout=timeout):
                return True
        try:
            self.automation.hotkey("alt", "left")
        except Exception:
            return False
        if self._wait_for_google_results_context(timeout=timeout):
            return True
        current = self._capture_context(refresh=True)
        if self._browser_leave_site_prompt_visible(context=current, refresh=True):
            self._resolve_browser_leave_site_prompt(leave=True, browser_name="brave")
            if self._wait_for_google_results_context(timeout=timeout):
                return True
        try:
            self.automation.hotkey("ctrl", "w")
        except Exception:
            return False
        if self._wait_for_google_results_context(timeout=timeout):
            return True
        current = self._capture_context(refresh=True)
        if self._browser_leave_site_prompt_visible(context=current, refresh=True):
            self._resolve_browser_leave_site_prompt(leave=True, browser_name="brave")
            return self._wait_for_google_results_context(timeout=timeout)
        return False

    def _wait_for_google_results_context(self, timeout: float) -> bool:
        deadline = time.time() + max(0.15, timeout)
        while time.time() < deadline:
            current = self._capture_context(refresh=True)
            if self._is_google_results_context(current):
                return True
            self.sleep(0.15)
        return False

    def _research_restore_google_results(self, query: str) -> bool:
        current = self._capture_context(refresh=True)
        if self._is_google_results_context(current, query=query):
            return True
        if self._return_to_google_results():
            return True
        restored, _detail = self._visible_google_search(
            query=query,
            browser_name="brave",
            step_name="research_restore_google",
        )
        return bool(restored)

    def _research_open_result_with_tab_navigation(
        self,
        baseline_title: str,
    ) -> Tuple[bool, Dict[str, str], str]:
        baseline = normalize_text(baseline_title)
        last = self._capture_context(refresh=True)
        for tab_count in (2, 4, 6):
            for _ in range(tab_count):
                self.automation.press_keys(["tab"])
                self.sleep(0.05)
            self.automation.press_keys(["enter"])
            self.sleep(1.0)
            current = self._capture_context(refresh=True)
            title = normalize_text(current.get("window_title", ""))
            if (
                title
                and title != baseline
                and not self._context_matches_site(current, "google")
                and not self._looks_like_google_results_title(current.get("window_title", ""))
            ):
                return True, current, f"tab_{tab_count}"
            last = current
        return False, last, "tab_navigation"

    @staticmethod
    def _looks_like_google_results_title(title: str) -> bool:
        normalized = normalize_text(title)
        if not normalized:
            return False
        return normalized in {"google", "google - brave"} or "buscar con google" in normalized or "search - google" in normalized

    @staticmethod
    def _research_scene_fields(source_quality: Dict[str, Any]) -> Dict[str, str]:
        return {
            "scene_id": str(source_quality.get("scene_id", "") or ""),
            "scene_variant": str(source_quality.get("scene_variant", "") or ""),
            "emergency_feedback": str(source_quality.get("emergency_feedback", "") or ""),
            "read_policy": str(source_quality.get("read_policy", "") or ""),
            "ignore_policy": str(source_quality.get("ignore_policy", "") or ""),
            "valid_exit_rule": str(source_quality.get("valid_exit_rule", "") or ""),
        }

    def _build_research_capture_context(
        self,
        page_title: str,
        context: Optional[Dict[str, Any]] = None,
        capture: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = dict(context or {})
        payload["window_title"] = str(page_title or payload.get("window_title", "") or "")
        capture = capture or {}
        for key in (
            "modal_detected",
            "modal_reason",
            "file_dialog_detected",
            "transcript_available",
            "visible_text_verified",
        ):
            if key in capture:
                payload[key] = capture.get(key)
        if "visible_text_verified" not in payload and "success" in capture:
            payload["visible_text_verified"] = bool(capture.get("success"))
        return payload

    def _classify_research_source(
        self,
        query: str,
        page_title: str,
        page_text: str,
        capture_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        classifier = getattr(self.task_executor, "classify_research_source", None)
        if callable(classifier):
            return dict(
                classifier(
                    query,
                    page_title,
                    page_text,
                    capture_context=capture_context,
                )
                or {}
            )
        return dict(
            TaskExecutor.classify_research_source(
                query,
                page_title,
                page_text,
                capture_context=capture_context,
            )
            or {}
        )

    def _classify_research_source_from_manifest(
        self,
        query: str,
        page_title: str,
        captured_chars: int,
        source_kind: str = "",
    ) -> Dict[str, Any]:
        synthetic_text = "texto util de investigacion " * 40 if int(captured_chars or 0) >= 500 else "texto corto"
        quality = self._classify_research_source(
            query,
            page_title,
            synthetic_text,
            capture_context={
                "visible_text_verified": int(captured_chars or 0) >= 500,
                "transcript_available": source_kind == "youtube_video" and int(captured_chars or 0) >= 500,
            },
        )
        if source_kind:
            quality["source_kind"] = str(source_kind)
        if int(captured_chars or 0) < 500:
            quality.update(
                {
                    "counts_as_useful": False,
                    "useful_source_count": 0,
                    "page_usefulness_label": "poor",
                }
            )
        return quality

    def _research_query_evidence(
        self,
        base_evidence: Dict[str, Any],
        page_title: str,
        captured_chars: int,
        rescue_used: bool,
        hard_failure: bool,
        page_usefulness_label: str,
        useful_source_count: int = 0,
        current_session_verified: bool = False,
        verification_source: str = "research_page_capture",
        source_kind: str = "web_page",
        title_matches_query: bool = False,
        source_quality_reason: str = "",
        scene_id: str = "",
        scene_variant: str = "",
        emergency_feedback: str = "",
        read_policy: str = "",
        ignore_policy: str = "",
        valid_exit_rule: str = "",
    ) -> Dict[str, Any]:
        evidence = dict(base_evidence or {})
        evidence.update(
            {
                "page_title": page_title,
                "captured_chars": captured_chars,
                "hard_failure": hard_failure,
                "page_usefulness_label": page_usefulness_label,
                "rescue_used": rescue_used,
                "useful_source_count": useful_source_count,
                "title_matches_query": bool(title_matches_query),
                "source_quality_reason": str(source_quality_reason or "").strip(),
                "scene_id": str(scene_id or "").strip(),
                "scene_variant": str(scene_variant or "").strip(),
                "emergency_feedback": str(emergency_feedback or "").strip(),
                "read_policy": str(read_policy or "").strip(),
                "ignore_policy": str(ignore_policy or "").strip(),
                "valid_exit_rule": str(valid_exit_rule or "").strip(),
            }
        )
        evidence.update(
            self._standardized_learning_evidence_fields(
                source_kind=source_kind,
                transcript_available=False,
                transcript_chars=0,
                visible_text_chars=captured_chars,
                page_usefulness_label=page_usefulness_label,
                verification_source=verification_source,
                current_session_verified=current_session_verified,
            )
        )
        return evidence

    def _emit_research_emergency_feedback(self, feedback: str, reason: str = "") -> None:
        normalized_feedback = str(feedback or "").strip()
        if not normalized_feedback:
            return
        normalized_reason = str(reason or "").strip()
        if normalized_reason and normalize_text(normalized_reason) != normalize_text(normalized_feedback):
            self._emit(f"Investigacion: {normalized_feedback}. {normalized_reason}", "warning")
            return
        self._emit(f"Investigacion: {normalized_feedback}.", "warning")

    def _research_failure_detail(
        self,
        query: str,
        result_index: int,
        stage: str,
        reason: str,
        evidence: Dict[str, Any],
        opened: bool = False,
        page_title: str = "",
        captured_chars: int = 0,
        rescue_used: bool = False,
        hard_failure: bool = True,
        source_kind: str = "web_page",
        title_matches_query: bool = False,
        source_quality_reason: str = "",
        scene_id: str = "",
        scene_variant: str = "",
        emergency_feedback: str = "",
        read_policy: str = "",
        ignore_policy: str = "",
        valid_exit_rule: str = "",
        emit_feedback: bool = True,
    ) -> Dict[str, Any]:
        if emit_feedback:
            self._emit_research_emergency_feedback(emergency_feedback, reason)
        return {
            "step": "research_query_attempt",
            "strategy": "visible_google_search",
            "verification": "page_text_quality" if stage not in {"visible_google_results"} else stage,
            "query": query,
            "result_index": max(1, int(result_index)),
            "opened": opened,
            "page_title": page_title,
            "captured_chars": captured_chars,
            "success": False,
            "context_failure": reason if stage in {"wrong_active_window", "visible_google_results"} else "",
            "failure_reason": reason,
            "failure_stage": stage,
            "rescue_used": rescue_used,
            "hard_failure": hard_failure,
            "scene_id": scene_id,
            "scene_variant": scene_variant,
            "emergency_feedback": emergency_feedback,
            "evidence": self._research_query_evidence(
                evidence,
                page_title=page_title,
                captured_chars=captured_chars,
                rescue_used=rescue_used,
                hard_failure=hard_failure,
                page_usefulness_label="poor" if captured_chars < 500 else "mixed",
                useful_source_count=0,
                source_kind=source_kind,
                title_matches_query=title_matches_query,
                source_quality_reason=source_quality_reason,
                scene_id=scene_id,
                scene_variant=scene_variant,
                emergency_feedback=emergency_feedback,
                read_policy=read_policy,
                ignore_policy=ignore_policy,
                valid_exit_rule=valid_exit_rule,
            ),
        }


    def _research_summary_attempt(
        self,
        topic: str,
        query_variants: Optional[List[str]] = None,
        result_indices: Optional[List[int]] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        result = self._collect_visible_research(
            topic,
            result_count=int(self._skill_settings("research").get("default_result_count", 3)),
            query_variants=query_variants,
            result_indices=result_indices,
        )
        useful_sources = int(result.get("useful_source_count", 0))
        summary = str(result.get("summary", "")).strip()
        findings = str(result.get("findings", "")).strip()
        captured_chars = len(str(result.get("merged_text", "") or ""))
        discard_precision = self._research_discard_precision(result)
        success = useful_sources >= 2 and len(summary) >= 20
        return success, {
            "step": "research_summary_attempt",
            "strategy": "visible_research_summary",
            "verification": "sources_and_summary",
            "useful_source_count": useful_sources,
            "captured_chars": captured_chars,
            "discard_precision": discard_precision,
            "summary_preview": summary[:180],
            "research_summary": summary,
            "research_findings": findings,
            "queries_used": result.get("queries_used", []),
            "visited_titles": result.get("reviewed_sources", []),
            "discarded_titles": result.get("discarded_titles", []),
            "discard_reasons": result.get("discard_reasons", []),
            "context_failure": result.get("context_failure", ""),
            "success": success,
            "evidence": self._research_step_evidence(
                result,
                equivalent_scenarios=["research_structured_extract", "research_discard_poor"],
                current_session_verified=success,
                verification_source="research_visible_summary",
            ),
        }

    def _research_goal_workflow(
        self,
        topic: str,
        create_document: bool = False,
        query_variants: Optional[List[str]] = None,
        result_indices: Optional[List[int]] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        result = self._collect_visible_research(
            topic,
            result_count=int(self._skill_settings("research").get("default_result_count", 3)),
            query_variants=query_variants,
            result_indices=result_indices,
        )
        useful_sources = int(result.get("useful_source_count", 0))
        summary = str(result.get("summary", "")).strip()
        findings = str(result.get("findings", "")).strip()
        captured_chars = len(str(result.get("merged_text", "") or ""))
        discard_precision = self._research_discard_precision(result)
        success = useful_sources >= 2 and len(summary) >= 20
        saved_path = ""
        if success and create_document:
            saved_path = self._extract_document_path(
                self.assistant.create_document(
                application="word",
                title=f"Resumen - {topic}",
                content=summary,
                )
            )
        detail = {
            "step": "research_goal_workflow",
            "strategy": "goal_research_visible",
            "verification": "sources_and_summary",
            "useful_source_count": useful_sources,
            "captured_chars": captured_chars,
            "discard_precision": discard_precision,
            "summary_preview": summary[:180],
            "research_summary": summary,
            "research_findings": findings,
            "document_result": saved_path,
            "queries_used": result.get("queries_used", []),
            "visited_titles": result.get("reviewed_sources", []),
            "discarded_titles": result.get("discarded_titles", []),
            "discard_reasons": result.get("discard_reasons", []),
            "context_failure": result.get("context_failure", ""),
            "success": success,
            "evidence": self._research_step_evidence(
                result,
                document_path=saved_path,
                current_session_verified=success,
                verification_source="research_goal_workflow",
            ),
        }
        return success, detail

    @staticmethod
    def _research_discard_precision(result: Dict[str, Any]) -> float:
        useful_sources = int(result.get("useful_source_count", 0) or 0)
        discarded = len([item for item in result.get("discarded_titles", []) if str(item).strip()])
        total = useful_sources + discarded
        return useful_sources / total if total else 0.0

    def _research_step_evidence(
        self,
        result: Dict[str, Any],
        document_path: str = "",
        equivalent_scenarios: Optional[List[str]] = None,
        current_session_verified: bool = False,
        verification_source: str = "research_summary_capture",
    ) -> Dict[str, Any]:
        evidence = dict(result.get("evidence", {}) if isinstance(result.get("evidence", {}), dict) else {})
        useful_source_count = int(result.get("useful_source_count", 0) or 0)
        captured_chars = len(str(result.get("merged_text", "") or ""))
        summary = str(result.get("summary", "") or "").strip()
        page_label = "useful" if useful_source_count >= 2 and len(summary) >= 20 else (
            "mixed" if useful_source_count >= 1 or captured_chars >= 180 else "poor"
        )
        evidence.update(
            {
                "useful_source_count": useful_source_count,
                "reviewed_sources": list(result.get("reviewed_sources", []))[:5],
                "visited_titles": list(result.get("visited_titles", []))[:5],
                "queries_used": list(result.get("queries_used", []))[:6],
                "discarded_titles": list(result.get("discarded_titles", []))[:6],
                "discard_reasons": list(result.get("discard_reasons", []))[:6],
                "captured_chars": captured_chars,
                "research_summary": summary,
                "research_findings": str(result.get("findings", "") or "").strip(),
                "discard_precision": self._research_discard_precision(result),
            }
        )
        evidence.update(
            self._standardized_learning_evidence_fields(
                source_kind="web_page",
                transcript_available=False,
                transcript_chars=0,
                visible_text_chars=captured_chars,
                page_usefulness_label=page_label,
                verification_source=verification_source,
                current_session_verified=current_session_verified,
            )
        )
        if equivalent_scenarios:
            evidence["equivalent_scenarios"] = [str(item) for item in equivalent_scenarios if str(item).strip()]
        if document_path:
            evidence["document_path"] = document_path
            evidence["output_path"] = document_path
        return evidence

    @staticmethod
    def _extract_document_path(document_result: Any) -> str:
        text = str(document_result or "").strip()
        prefix = "Documento preparado y guardado en:"
        if text.startswith(prefix):
            return text[len(prefix):].strip()
        return text

    def _capture_context(self, refresh: bool = False) -> Dict[str, str]:
        snapshot = None
        try:
            snapshot = self.assistant.get_latest_vision_snapshot(refresh=refresh)
        except Exception:
            snapshot = None
        snapshot_window = str(getattr(snapshot, "active_window", "") or "")
        snapshot_app = str(getattr(snapshot, "active_app", "") or "")
        snapshot_site = str(getattr(snapshot, "active_site", "") or "")
        window_title = ""
        try:
            window_title = str(self.automation.get_active_window_title() or "")
        except Exception:
            window_title = ""
        resolved_window = window_title or snapshot_window
        active_app, active_site = self._reconcile_context_identity(
            resolved_window,
            snapshot_window=snapshot_window,
            snapshot_app=snapshot_app,
            snapshot_site=snapshot_site,
        )
        return {
            "window_title": resolved_window,
            "active_window": resolved_window or snapshot_window,
            "active_app": active_app,
            "active_site": active_site,
        }

    def _reconcile_context_identity(
        self,
        window_title: str,
        snapshot_window: str,
        snapshot_app: str,
        snapshot_site: str,
    ) -> Tuple[str, str]:
        normalized_title = normalize_text(window_title)
        normalized_snapshot_window = normalize_text(snapshot_window)
        normalized_snapshot_app = normalize_text(snapshot_app)
        normalized_snapshot_site = normalize_text(snapshot_site)
        inferred_app = self._infer_app_from_window_title(window_title)
        inferred_site = self._infer_site_from_window_title(window_title)
        if not normalized_title:
            return snapshot_app, snapshot_site
        if not normalized_snapshot_window or normalized_title == normalized_snapshot_window:
            return snapshot_app or inferred_app, snapshot_site or inferred_site
        if normalized_snapshot_app and self._context_title_matches_expected_app(window_title, normalized_snapshot_app):
            resolved_site = snapshot_site
            if normalized_snapshot_site and normalized_snapshot_site not in normalized_title:
                resolved_site = inferred_site
            return snapshot_app or inferred_app, resolved_site or inferred_site
        return inferred_app, inferred_site

    @classmethod
    def _infer_app_from_window_title(cls, window_title: str) -> str:
        title = normalize_text(window_title)
        if not title:
            return ""
        aliases = {
            "brave": ("brave",),
            "chrome": ("google chrome", "chrome"),
            "edge": ("microsoft edge", "edge"),
            "firefox": ("firefox",),
            "notepad": ("bloc de notas", "notepad"),
            "word": ("microsoft word", "word"),
            "libreoffice writer": ("libreoffice writer", "writer"),
            "explorer": ("file explorer", "explorador", "este equipo", "this pc", "escritorio"),
            "cmd": ("cmd.exe", "powershell", "pwsh", "terminal"),
        }
        for app_name, tokens in aliases.items():
            if any(token and token in title for token in tokens):
                return app_name
        return ""

    @staticmethod
    def _infer_site_from_window_title(window_title: str) -> str:
        title = normalize_text(window_title)
        if not title:
            return ""
        aliases = {
            "google": (
                "buscar con google",
                "search - google",
                "google - brave",
                "google - edge",
                "google - firefox",
                "google chrome - google",
            ),
            "youtube": ("youtube",),
            "gmail": ("gmail",),
            "spotify": ("spotify",),
        }
        for site_name, tokens in aliases.items():
            if any(token and token in title for token in tokens):
                return site_name
        return ""

    def _unexpected_modal_reason(
        self,
        context: Dict[str, str],
        expected_app: Optional[str] = None,
        expected_site: Optional[str] = None,
    ) -> str:
        window_title = normalize_text(context.get("window_title", ""))
        active_app = normalize_text(context.get("active_app", ""))
        active_site = normalize_text(context.get("active_site", ""))
        normalized_expected_app = normalize_text(expected_app or "")
        normalized_expected_site = normalize_text(expected_site or "")
        browser_expected = normalized_expected_app in self.BROWSER_APPS or normalized_expected_app == "browser"
        if (
            browser_expected
            or active_app in self.BROWSER_APPS
            or normalized_expected_site in {"google", "youtube", "gmail"}
        ) and self._browser_leave_site_prompt_visible(context=context, refresh=False):
            return "Dialogo del navegador: salir del sitio web"
        if self._looks_like_unexpected_modal_title(window_title):
            return f"Ventana modal inesperada: {context.get('window_title', '')}"
        if expected_app:
            if normalized_expected_app == "browser":
                if active_app not in self.BROWSER_APPS and not self._context_title_matches_expected_app(
                    window_title,
                    normalized_expected_app,
                ):
                    return f"App activa inesperada: {context.get('active_app', '') or 'desconocida'}"
            elif active_app:
                if active_app != normalized_expected_app:
                    return f"App activa inesperada: {context.get('active_app', '')}"
                if window_title and not self._context_title_matches_expected_app(
                    window_title,
                    normalized_expected_app,
                ):
                    return f"Ventana activa inesperada: {context.get('window_title', '')}"
            elif not self._context_title_matches_expected_app(window_title, normalized_expected_app):
                return (
                    "App activa inesperada: desconocida "
                    f"({context.get('window_title', '') or 'sin titulo'})"
                )
        if expected_site:
            if active_site and active_site != normalized_expected_site:
                return f"Sitio activo inesperado: {context.get('active_site', '')}"
        return ""

    def _context_title_matches_expected_app(self, window_title: str, expected_app: str) -> bool:
        title = normalize_text(window_title)
        expected = normalize_text(expected_app)
        if not title:
            return False
        aliases = {
            "notepad": ("notepad", "bloc de notas"),
            "word": ("word", "microsoft word"),
            "libreoffice writer": ("libreoffice writer", "writer"),
            "explorer": ("explorer", "file explorer", "explorador", "escritorio", "este equipo", "this pc"),
            "brave": ("brave",),
            "chrome": ("chrome", "google chrome"),
            "edge": ("edge", "microsoft edge"),
            "firefox": ("firefox",),
            "browser": tuple(self.BROWSER_APPS),
        }
        if expected == "notepad":
            if title.endswith(".txt") or title.endswith(".txt - bloc de notas"):
                return True
            if "bloc de notas" in title or "notepad" in title:
                return True
        return any(token and token in title for token in aliases.get(expected, (expected,)))

    def _looks_like_explorer_context(self, context: Dict[str, str]) -> bool:
        active_app = normalize_text(context.get("active_app", ""))
        title = str(context.get("window_title", "") or "")
        normalized_title = normalize_text(title)
        if active_app == "explorer":
            return True
        if self._context_title_matches_expected_app(title, "explorer"):
            return True
        if active_app:
            return False
        if not normalized_title or self._looks_like_unexpected_modal_title(normalized_title):
            return False
        if any(token in normalized_title for token in ("brave", "chrome", "edge", "firefox", "notepad", "bloc de notas", "word", "visual studio code")):
            return False
        return True

    def _is_open_file_dialog(self, window_title: str) -> bool:
        title = normalize_text(window_title)
        if not title:
            return False
        if any(token in title for token in ("guardar", "save")):
            return False
        if title in {"abrir", "open"}:
            return True
        return any(token in title for token in ("abrir archivo", "open file", "choose file", "select file"))

    def _visible_open_file_dialog_titles(
        self,
        context: Optional[Dict[str, str]] = None,
        refresh: bool = True,
    ) -> List[str]:
        titles: List[str] = []

        def add_title(value: Any) -> None:
            text = str(value or "").strip()
            if text and text not in titles:
                titles.append(text)

        if context:
            add_title(context.get("window_title", ""))
            add_title(context.get("active_window", ""))

        try:
            for title in self.automation.list_windows():
                add_title(title)
        except Exception:
            pass

        try:
            snapshot = self.assistant.get_latest_vision_snapshot(refresh=refresh)
        except Exception:
            snapshot = None
        if snapshot:
            add_title(getattr(snapshot, "active_window", ""))
            for window in getattr(snapshot, "windows", []) or []:
                add_title(getattr(window, "title", ""))

        return [title for title in titles if self._is_open_file_dialog(title)]

    def _open_file_dialog_visible(self, context: Optional[Dict[str, str]] = None) -> bool:
        return bool(self._visible_open_file_dialog_titles(context=context, refresh=True))

    def _focus_dialog_title(self, title: str) -> None:
        try:
            if hasattr(self.assistant, "focus_window"):
                self.assistant.focus_window(title)
                return
        except Exception:
            pass
        try:
            if hasattr(self.automation, "focus_window"):
                self.automation.focus_window(title)
        except Exception:
            pass

    def _close_open_file_dialog_if_present(self, max_attempts: int = 3) -> bool:
        acted = False
        for attempt in range(max_attempts):
            context = self._capture_context(refresh=True)
            dialog_titles = self._visible_open_file_dialog_titles(context=context, refresh=True)
            if not dialog_titles:
                return acted

            acted = True
            title = dialog_titles[0]
            self._emit(
                f"Intento {attempt + 1}/{max_attempts}: cierro cuadro de apertura de archivo.",
                "warning",
            )
            self._focus_dialog_title(title)
            try:
                self.automation.press_keys(["esc"])
                self.sleep(0.35)
            except Exception:
                pass
            if not self._open_file_dialog_visible():
                return True

            self._focus_dialog_title(title)
            try:
                self.automation.hotkey("alt", "f4")
                self.sleep(0.45)
            except Exception:
                pass
            if not self._open_file_dialog_visible():
                return True

        return acted and not self._open_file_dialog_visible()

    def _text_looks_like_browser_leave_site_prompt(self, text: str) -> bool:
        normalized = normalize_text(text)
        if not normalized:
            return False
        return any(token in normalized for token in self.BROWSER_LEAVE_SITE_TOKENS)

    def _capture_browser_prompt_text(self, refresh: bool = True) -> str:
        fragments: List[str] = []
        seen: set[str] = set()

        def add_fragment(text: str) -> None:
            normalized = normalize_text(text)
            if normalized and normalized not in seen:
                seen.add(normalized)
                fragments.append(str(text).strip())

        try:
            snapshot = self.assistant.get_latest_vision_snapshot(refresh=refresh)
        except Exception:
            snapshot = None

        if snapshot:
            add_fragment(str(getattr(snapshot, "ocr_excerpt", "") or ""))
            add_fragment(str(getattr(snapshot, "active_window", "") or ""))
            for window in getattr(snapshot, "windows", []) or []:
                add_fragment(str(getattr(window, "title", "") or ""))

            extractor = getattr(self.task_executor, "_extract_text_with_fallbacks", None)
            preferred_regions = getattr(self.task_executor, "_preferred_text_regions", None)
            languages_for_snapshot = getattr(self.task_executor, "_ocr_languages_for_snapshot", None)
            if callable(extractor) and callable(preferred_regions) and callable(languages_for_snapshot):
                active_window = next(
                    (item for item in getattr(snapshot, "windows", []) or [] if getattr(item, "is_active", False)),
                    None,
                )
                try:
                    for region_name, region in preferred_regions(snapshot, active_window):
                        if region_name not in {
                            "active_window_full",
                            "browser_primary_reading_region",
                            "browser_content_region",
                        }:
                            continue
                        extracted = str(
                            extractor(region=region, languages=languages_for_snapshot(snapshot)) or ""
                        ).strip()
                        if extracted:
                            add_fragment(extracted)
                        if self._text_looks_like_browser_leave_site_prompt(extracted):
                            break
                except Exception:
                    pass

        return "\n".join(fragment for fragment in fragments if fragment)

    def _browser_leave_site_prompt_visible(
        self,
        context: Optional[Dict[str, str]] = None,
        refresh: bool = True,
    ) -> bool:
        current = context or self._capture_context(refresh=refresh)
        active_app = normalize_text(current.get("active_app", ""))
        window_title = str(current.get("window_title", "") or "")
        if active_app and active_app not in self.BROWSER_APPS and not any(
            token in normalize_text(window_title) for token in self.BROWSER_APPS
        ):
            return False

        candidates: List[str] = [
            window_title,
            str(current.get("active_window", "") or ""),
        ]

        try:
            candidates.extend(str(title or "") for title in self.automation.list_windows())
        except Exception:
            pass

        try:
            snapshot = self.assistant.get_latest_vision_snapshot(refresh=refresh)
        except Exception:
            snapshot = None
        if snapshot:
            candidates.append(str(getattr(snapshot, "active_window", "") or ""))
            candidates.append(str(getattr(snapshot, "ocr_excerpt", "") or ""))
            for window in getattr(snapshot, "windows", []) or []:
                candidates.append(str(getattr(window, "title", "") or ""))

        for candidate in candidates:
            if self._text_looks_like_browser_leave_site_prompt(candidate):
                return True

        if not refresh:
            return False
        return self._text_looks_like_browser_leave_site_prompt(
            self._capture_browser_prompt_text(refresh=refresh)
        )

    def _resolve_browser_leave_site_prompt(
        self,
        leave: bool = True,
        browser_name: str = "brave",
        max_attempts: int = 3,
    ) -> bool:
        acted = False
        sequences: List[Tuple[str, ...]] = [
            ("enter",),
            ("tab", "enter"),
            ("shift+tab", "enter"),
        ]
        if not leave:
            sequences = [
                ("tab", "enter"),
                ("enter",),
                ("shift+tab", "enter"),
            ]

        for attempt, sequence in enumerate(sequences[:max_attempts], start=1):
            current = self._capture_context(refresh=True)
            if not self._browser_leave_site_prompt_visible(context=current, refresh=True):
                return acted
            acted = True
            self._emit(
                f"Dialogo de salida del navegador detectado; intento {attempt}/{max_attempts} para continuar.",
                "warning",
            )
            self._focus_or_launch_known_app(browser_name)
            try:
                for key in sequence:
                    if key == "shift+tab":
                        self.automation.hotkey("shift", "tab")
                    else:
                        self.automation.press_keys([key])
                    self.sleep(0.12)
            except Exception:
                continue
            self.sleep(0.45)
        return acted and not self._browser_leave_site_prompt_visible(refresh=True)

    def _looks_like_unexpected_modal_title(self, window_title: str) -> bool:
        title = normalize_text(window_title)
        if not title:
            return False
        if title in {"abrir", "open", "guardar", "save"}:
            return True
        return any(token in title for token in self.MODAL_TOKENS)

    def _build_evidence(
        self,
        before: Dict[str, str],
        after: Dict[str, str],
        target_control_used: str,
        selected_text_preview: str,
        verification_reason: str,
        rescue_used: bool,
    ) -> Dict[str, Any]:
        return {
            "window_title_before": before.get("window_title", ""),
            "window_title_after": after.get("window_title", ""),
            "active_app_before": before.get("active_app", ""),
            "active_app_after": after.get("active_app", ""),
            "active_site_before": before.get("active_site", ""),
            "active_site_after": after.get("active_site", ""),
            "selected_text_preview": selected_text_preview,
            "target_control_used": target_control_used,
            "verification_reason": verification_reason,
            "rescue_used": rescue_used,
        }

    @staticmethod
    def _standardized_learning_evidence_fields(
        source_kind: str,
        transcript_available: bool,
        transcript_chars: int,
        visible_text_chars: int,
        page_usefulness_label: str,
        verification_source: str,
        current_session_verified: bool,
    ) -> Dict[str, Any]:
        normalized_label = str(page_usefulness_label or "").strip() or "unknown"
        return {
            "source_kind": str(source_kind or "").strip() or "unknown",
            "transcript_available": bool(transcript_available),
            "transcript_chars": max(0, int(transcript_chars or 0)),
            "visible_text_chars": max(0, int(visible_text_chars or 0)),
            "page_usefulness_label": normalized_label,
            "verification_source": str(verification_source or "").strip() or "unknown",
            "current_session_verified": bool(current_session_verified),
            "captured_chars": max(0, int(max(transcript_chars or 0, visible_text_chars or 0))),
        }

    def _failure_detail(
        self,
        step: str,
        strategy: str,
        verification: str,
        before: Dict[str, str],
        reason: str,
        text: str = "",
        target_control_used: str = "",
        rescue_used: bool = False,
    ) -> Dict[str, Any]:
        return {
            "step": step,
            "text": text,
            "strategy": strategy,
            "verification": verification,
            "success": False,
            "context_failure": reason,
            "evidence": self._build_evidence(
                before=before,
                after=before,
                target_control_used=target_control_used,
                selected_text_preview=text[:120],
                verification_reason=reason,
                rescue_used=rescue_used,
            ),
        }

    def _click_visible_hint(
        self,
        target_name: str,
        expected_app: Optional[str] = None,
        expected_site: Optional[str] = None,
    ) -> bool:
        snapshot = self.assistant.get_latest_vision_snapshot(refresh=True)
        if not snapshot:
            return False
        if expected_app and self._unexpected_modal_reason(self._capture_context(refresh=False), expected_app=expected_app):
            return False
        if expected_site and self._unexpected_modal_reason(self._capture_context(refresh=False), expected_site=expected_site):
            return False
        element = self.assistant.vision.find_ui_element(target_name, snapshot=snapshot)
        if not element:
            return False
        self.automation.move_mouse(int(element.x), int(element.y), duration=0.22)
        self.sleep(0.06)
        self.automation.click(int(element.x), int(element.y), duration=0.05)
        self.sleep(0.08)
        return True

    def _prepare_plain_notepad_session(self, training_path: Optional[Path] = None) -> bool:
        self._dismiss_editor_modal_if_present()
        if self._open_file_dialog_visible():
            self._emit("Hay un cuadro de apertura activo; cancelo la preparacion segura.", "warning")
            return False
        target_path = training_path or (
            self.sessions_dir / "_keyboard_runtime" / f"keyboard_training_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )
        ensure_directory(target_path.parent)
        target_path.write_text("", encoding="utf-8")
        self.sleep(0.2)
        
        # Intentar abrir Notepad con el archivo
        self.assistant.open_application("notepad", extra_args=[str(target_path)])
        self.sleep(2.0)  # Tiempo inicial más largo para permitir que Notepad se abra completamente
        
        # Cerrar cualquier diálogo modal que pueda estar abierto
        self._dismiss_editor_modal_if_present()
        self.sleep(1.0)
        if self._open_file_dialog_visible():
            self._close_open_file_dialog_if_present(max_attempts=5)
        if self._open_file_dialog_visible():
            self._emit("No se pudo cerrar el cuadro de apertura de archivo; abortare este ciclo.", "warning")
            return False
        
        # Reintentos agresivos para cerrar el cuadro de diálogo de apertura de archivo
        max_dialog_close_attempts = 5
        for attempt in range(max_dialog_close_attempts):
            context = self._capture_context(refresh=True)
            window_title = context.get("window_title", "")
            
            if self._is_open_file_dialog(window_title):
                self._emit(f"Intento {attempt + 1}/{max_dialog_close_attempts}: Cerrando cuadro de apertura de archivo.", "warning")
                try:
                    # Intentar presionar ESC
                    self.automation.press_keys(["esc"])
                    self.sleep(0.8)
                    
                    # Verificar si se cerró
                    context = self._capture_context(refresh=True)
                    if not self._is_open_file_dialog(context.get("window_title", "")):
                        self._emit("Cuadro de diálogo cerrado exitosamente.", "info")
                        break
                    
                    # Si ESC no funcionó, intentar Alt+F4
                    self.automation.hotkey("alt", "f4")
                    self.sleep(0.8)
                    
                    # Verificar de nuevo
                    context = self._capture_context(refresh=True)
                    if not self._is_open_file_dialog(context.get("window_title", "")):
                        self._emit("Cuadro de diálogo cerrado con Alt+F4.", "info")
                        break
                except Exception as e:
                    self._emit(f"Error al intentar cerrar el cuadro: {e}", "warning")
            else:
                # No hay cuadro de diálogo abierto, salir del loop
                break
            
            self.sleep(0.5)
        
        # Verificar el estado final
        context = self._capture_context(refresh=True)
        if self._unexpected_modal_reason(context, expected_app="notepad"):
            self._focus_existing_notepad_window(target_path)
            self.sleep(0.5)
            context = self._capture_context(refresh=True)
        
        if self._unexpected_modal_reason(context, expected_app="notepad"):
            self._emit("No se pudo confirmar el editor de Notepad durante la preparacion.", "warning")
            return False
        
        if self._click_visible_hint("document_body", expected_app="notepad"):
            return self._clear_active_editor()
        return False

    def _finalize_plain_notepad_session(self) -> None:
        try:
            self.automation.hotkey("alt", "f4")
            self.sleep(1.0)
            self._dismiss_editor_modal_if_present()
            self.sleep(0.5)
        except Exception:
            pass

    def _dismiss_editor_modal_if_present(self) -> bool:
        context = self._capture_context(refresh=True)
        if self._open_file_dialog_visible(context):
            return self._close_open_file_dialog_if_present(max_attempts=3)
        title = normalize_text(context.get("window_title", ""))
        if self._looks_like_unexpected_modal_title(title):
            try:
                # Primer intento: ESC
                self.automation.press_keys(["esc"])
                self.sleep(0.8)
                
                next_context = self._capture_context(refresh=True)
                next_title = normalize_text(next_context.get("window_title", ""))
                
                # Si persiste, intentar Alt+F4
                if self._looks_like_unexpected_modal_title(next_title):
                    try:
                        self.automation.hotkey("alt", "f4")
                        self.sleep(0.8)
                        
                        # Último intento: Tab + Enter
                        final_context = self._capture_context(refresh=True)
                        if self._looks_like_unexpected_modal_title(normalize_text(final_context.get("window_title", ""))):
                            self._emit("El modal persiste tras ESC y Alt+F4; no confirmo botones inseguros.", "warning")
                    except Exception:
                        pass
                return True
            except Exception:
                return False
        if not self._context_title_matches_expected_app(title, "notepad"):
            return False
        return self._dismiss_plain_editor_prompt_if_present()

    def _dismiss_plain_editor_prompt_if_present(self) -> bool:
        context = self._capture_context(refresh=True)
        if self._open_file_dialog_visible(context):
            return self._close_open_file_dialog_if_present(max_attempts=3)
        title = normalize_text(context.get("window_title", ""))
        
        if self._is_open_file_dialog(title):
            try:
                # Primer intento: ESC
                self.automation.press_keys(["esc"])
                self.sleep(0.8)
                
                next_context = self._capture_context(refresh=True)
                next_title = normalize_text(next_context.get("window_title", ""))
                
                # Si el diálogo persiste, intentar Alt+F4
                if self._is_open_file_dialog(next_title):
                    self.automation.hotkey("alt", "f4")
                    self.sleep(0.8)
                    
                    # Verificación final
                    final_context = self._capture_context(refresh=True)
                    if self._is_open_file_dialog(normalize_text(final_context.get("window_title", ""))):
                        # Último recurso: cerrar la ventana de forma más agresiva
                        self._emit("El cuadro de apertura persiste; no confirmo el boton por defecto.", "warning")
                
                return True
            except Exception:
                return False
        
        if not any(token in title for token in ("guardar", "save", "open", "abrir")):
            if not self._context_title_matches_expected_app(title, "notepad"):
                return False
            return self._dismiss_notepad_save_prompt_if_present()
        
        try:
            self.automation.press_keys(["right"])
            self.sleep(0.25)
            self.automation.press_keys(["enter"])
            self.sleep(1.0)
            return True
        except Exception:
            return False

    def _recover_keyboard_editor_context(self) -> bool:
        if self._dismiss_editor_modal_if_present():
            self.sleep(0.5)
        context = self._capture_context(refresh=True)
        if self._open_file_dialog_visible(context):
            self._close_open_file_dialog_if_present(max_attempts=3)
            context = self._capture_context(refresh=True)
        if self._open_file_dialog_visible(context):
            return False
        if self._unexpected_modal_reason(context, expected_app="notepad"):
            prepared = self._prepare_plain_notepad_session()
            if not prepared:
                return False
            context = self._capture_context(refresh=True)
        if self._unexpected_modal_reason(context, expected_app="notepad"):
            return False
        self._click_visible_hint("document_body", expected_app="notepad")
        return True

    def _focus_existing_notepad_window(self, target_path: Optional[Path] = None) -> bool:
        needles = ["bloc de notas", "notepad"]
        if target_path:
            needles.insert(0, normalize_text(target_path.stem))
            needles.insert(0, normalize_text(target_path.name))
        try:
            titles = self.automation.list_windows()
        except Exception:
            titles = []
        for title in titles:
            normalized = normalize_text(title)
            if self._is_open_file_dialog(normalized):
                continue
            if any(needle and needle in normalized for needle in needles):
                self._focus_dialog_title(title)
                return True
        return False

    def _focus_existing_window_for_app(self, app_name: str) -> bool:
        normalized_app = normalize_text(app_name)
        if not normalized_app:
            return False
        titles: List[str] = []

        def add_title(value: Any) -> None:
            text = str(value or "").strip()
            if text and text not in titles:
                titles.append(text)

        try:
            for title in self.automation.list_windows():
                add_title(title)
        except Exception:
            pass

        try:
            snapshot = self.assistant.get_latest_vision_snapshot(refresh=True)
        except Exception:
            snapshot = None
        if snapshot:
            add_title(getattr(snapshot, "active_window", ""))
            for window in getattr(snapshot, "windows", []) or []:
                add_title(getattr(window, "title", ""))

        for title in titles:
            if self._is_open_file_dialog(title):
                continue
            if self._context_title_matches_expected_app(title, normalized_app):
                self._focus_dialog_title(title)
                self.sleep(0.35)
                return True
        return False

    def _focus_or_launch_known_app(self, app_name: str) -> None:
        normalized_app = normalize_text(app_name)
        current = self._capture_context(refresh=True)
        if (
            normalize_text(current.get("active_app", "")) == normalized_app
            and self._context_title_matches_expected_app(current.get("window_title", ""), normalized_app)
        ):
            return
        if normalized_app in self.DOCUMENT_APPS or normalized_app == "explorer":
            if normalized_app == "notepad" and self._focus_existing_notepad_window():
                return
            if self._focus_existing_window_for_app(normalized_app):
                return
        if normalized_app in self.BROWSER_APPS:
            if hasattr(self.assistant, "ensure_browser"):
                self.assistant.ensure_browser(browser=normalized_app, private=False)
            else:
                self.assistant.open_application(normalized_app)
            self.sleep(0.8)
            return
        if normalized_app == "explorer":
            if hasattr(self.assistant, "open_folder"):
                self.assistant.open_folder(str(self.base_dir))
            else:
                self.assistant.open_application("explorer")
            self.sleep(0.8)
            return
        snapshot = self.assistant.get_latest_vision_snapshot(refresh=True)
        if snapshot:
            for window in getattr(snapshot, "windows", []):
                if normalize_text(getattr(window, "app_name", "") or "") == normalized_app:
                    if hasattr(self.assistant, "focus_window"):
                        self.assistant.focus_window(window.title)
                    self.sleep(0.5)
                    return
        self.assistant.open_application(normalized_app)
        self.sleep(1.0)

    def _context_matches_site(self, context: Dict[str, str], expected_site: str) -> bool:
        normalized_expected = normalize_text(expected_site)
        active_site = normalize_text(context.get("active_site", ""))
        title = normalize_text(context.get("window_title", ""))
        return active_site == normalized_expected or normalized_expected in title

    def _google_search_url(self, query: str) -> str:
        template = str(self.config.get("google_url", "https://www.google.com/search?q={query}"))
        return template.format(query=quote_plus(query))

    def _youtube_search_url(self, query: str) -> str:
        template = str(
            self.config.get(
                "youtube_search_url",
                "https://www.youtube.com/results?search_query={query}",
            )
        )
        return template.format(query=quote_plus(query))

    def _google_results_context_matches_query(self, context: Dict[str, str], query: str) -> bool:
        title = normalize_text(context.get("window_title", ""))
        if not title:
            return False
        query_tokens = [
            token
            for token in normalize_text(query).split()
            if len(token) >= 3 and token not in {"con", "para", "sobre", "guia"}
        ]
        if not query_tokens:
            return False
        search_markers = ("buscar con google", "search - google", "google search", "resultados de google")
        return any(token in title for token in query_tokens[:3]) and any(
            marker in title for marker in search_markers
        )

    def _google_results_page_context(self, context: Dict[str, str]) -> bool:
        title = normalize_text(context.get("window_title", ""))
        if not title:
            return False
        if title in {"google", "google - brave"}:
            return True
        return any(marker in title for marker in ("buscar con google", "search - google", "google search"))

    def _is_google_results_context(self, context: Dict[str, str], query: str = "") -> bool:
        title = str(context.get("window_title", "") or "")
        if self._looks_like_google_results_title(title):
            return True
        if query and self._google_results_context_matches_query(context, query):
            return True
        active_site = normalize_text(context.get("active_site", ""))
        return active_site == "google" and self._google_results_page_context(context)

    def _generic_application_open_and_verify(self, application: str) -> Tuple[bool, Dict[str, Any]]:
        self._focus_or_launch_known_app(application)
        after = self._capture_context(refresh=True)
        failure = self._unexpected_modal_reason(after, expected_app=application if application != "explorer" else None)
        success = not failure and (
            normalize_text(after.get("active_app", "")) == normalize_text(application)
            or normalize_text(application) in normalize_text(after.get("window_title", ""))
        )
        detail = {
            "step": f"{application}_open_and_verify",
            "strategy": "open_and_focus",
            "verification": "active_window_matches",
            "success": success,
            "context_failure": failure or "",
            "evidence": self._build_evidence(
                before={},
                after=after,
                target_control_used="window_focus",
                selected_text_preview="",
                verification_reason="" if success else (failure or "La ventana activa no coincide con la aplicacion esperada."),
                rescue_used=False,
            ),
        }
        return success, detail

    def _document_editor_write_and_verify(self, application: str, text: str) -> Tuple[bool, Dict[str, Any]]:
        self._focus_or_launch_known_app(application)
        before = self._capture_context(refresh=True)
        expected_app = "word" if normalize_text(application) == "word" else normalize_text(application)
        failure = self._unexpected_modal_reason(before, expected_app=expected_app)
        if failure:
            return False, self._failure_detail(
                step=f"{application}_write_verify",
                strategy="direct_typing",
                verification="strict_real",
                before=before,
                reason=failure,
                text=text,
                target_control_used="document_body",
            )
        target_control_used = "document_body"
        rescue_used = False
        strategy = "direct_typing"
        if not self._click_visible_hint("document_body", expected_app=expected_app):
            if normalize_text(application) == "word":
                try:
                    self.automation.hotkey("ctrl", "n")
                    self.sleep(0.6)
                    rescue_used = True
                    strategy = "direct_typing+ctrl_n"
                except Exception:
                    pass
                current = self._capture_context(refresh=True)
                current_failure = self._unexpected_modal_reason(current, expected_app=expected_app)
                if current_failure:
                    return False, self._failure_detail(
                        step=f"{application}_write_verify",
                        strategy=strategy,
                        verification="strict_real",
                        before=before,
                        reason=current_failure,
                        text=text,
                        target_control_used="document_body",
                        rescue_used=rescue_used,
                    )
            if self._click_visible_hint("document_body", expected_app=expected_app):
                self.sleep(0.1)
            else:
                return False, self._failure_detail(
                    step=f"{application}_write_verify",
                    strategy=strategy,
                    verification="strict_real",
                    before=before,
                    reason="No pude enfocar el cuerpo del documento.",
                    text=text,
                    target_control_used="document_body",
                    rescue_used=rescue_used,
                )
        current = self._capture_context(refresh=True)
        current_failure = self._unexpected_modal_reason(current, expected_app=expected_app)
        if current_failure:
            return False, self._failure_detail(
                step=f"{application}_write_verify",
                strategy=strategy,
                verification="strict_real",
                before=before,
                reason=current_failure,
                text=text,
                target_control_used=target_control_used,
                rescue_used=rescue_used,
            )
        if not self._clear_active_editor(expected_app=expected_app):
            return False, self._failure_detail(
                step=f"{application}_write_verify",
                strategy=strategy,
                verification="strict_real",
                before=before,
                reason="No se pudo limpiar el editor activo sin perder el foco real.",
                text=text,
                target_control_used=target_control_used,
                rescue_used=rescue_used,
            )
        strategy = self._write_text_with_learning(f"text_entry:{application}_body", text, allow_clipboard=False)
        self.sleep(0.25)
        captured = self._capture_editor_text(expected_app=expected_app) or ""
        after = self._capture_context(refresh=True)
        after_failure = self._unexpected_modal_reason(after, expected_app=expected_app)
        if not normalize_text(captured) and not after_failure:
            rescue_used = True
            self._click_visible_hint("document_body", expected_app=expected_app)
            self.sleep(0.12)
            captured = self._capture_editor_text(expected_app=expected_app) or ""
            after = self._capture_context(refresh=True)
            after_failure = self._unexpected_modal_reason(after, expected_app=expected_app)
        success = normalize_text(captured) == normalize_text(text) and not after_failure
        visible_chars = len(str(captured).strip())
        verification_reason = ""
        if not success:
            if after_failure:
                verification_reason = after_failure
            elif not normalize_text(captured):
                verification_reason = "La captura de texto quedo vacia en la sesion actual."
            else:
                verification_reason = "El texto capturado no coincide exactamente."
        detail = {
            "step": f"{application}_write_verify",
            "strategy": strategy,
            "verification": "capture_selected_text",
            "text": text,
            "captured_preview": captured[:120],
            "success": success,
            "context_failure": after_failure or "",
            "evidence": self._build_evidence(
                before=before,
                after=after,
                target_control_used=target_control_used,
                selected_text_preview=captured[:120],
                verification_reason=verification_reason,
                rescue_used=rescue_used,
            ),
        }
        detail["evidence"].update(
            self._standardized_learning_evidence_fields(
                source_kind="document_editor",
                transcript_available=False,
                transcript_chars=0,
                visible_text_chars=visible_chars,
                page_usefulness_label="verified_text" if success else ("empty" if not normalize_text(captured) else "mismatch"),
                verification_source="capture_selected_text",
                current_session_verified=success,
            )
        )
        return success, detail

    def _document_editor_save_workflow(self, application: str, text: str, workspace: Path) -> Tuple[bool, Dict[str, Any]]:
        filename = workspace / f"{normalize_text(application).replace(' ', '_')}_{datetime.now().strftime('%H%M%S')}.txt"
        success, detail = self._document_editor_write_and_verify(application, text)
        if not success:
            detail["step"] = f"{application}_save_workflow"
            return False, detail
        before = self._capture_context(refresh=True)
        try:
            self.automation.hotkey("ctrl", "shift", "s")
        except Exception:
            self.automation.hotkey("ctrl", "s")
        self.sleep(1.0)
        save_context = self._capture_context(refresh=True)
        save_title = normalize_text(save_context.get("window_title", ""))
        if not any(token in save_title for token in ("guardar como", "save as", "guardar", "save")):
            return False, self._failure_detail(
                step=f"{application}_save_workflow",
                strategy="save_dialog",
                verification="strict_real",
                before=before,
                reason="No se detecto un dialogo visible de guardado.",
                text=str(filename),
                target_control_used="save_dialog",
            )
        self._write_text_with_learning(f"text_entry:{application}_save_path", str(filename), allow_clipboard=False)
        self.automation.press_keys(["enter"])
        self.sleep(1.0)
        success = filename.exists()
        after = self._capture_context(refresh=True)
        detail = {
            "step": f"{application}_save_workflow",
            "strategy": "save_dialog",
            "verification": "file_exists_and_visible_dialog",
            "success": success,
            "output_path": str(filename),
            "context_failure": "" if success else "El archivo no aparecio despues del guardado.",
            "evidence": self._build_evidence(
                before=save_context,
                after=after,
                target_control_used="save_dialog",
                selected_text_preview=str(filename),
                verification_reason="" if success else "El archivo final no existe despues del guardado.",
                rescue_used=False,
            ),
        }
        return success, detail

    def _document_editor_goal_workflow(self, application: str, goal: str, workspace: Path) -> Tuple[bool, Dict[str, Any]]:
        if any(token in normalize_text(goal) for token in ("guardar", "save")):
            return self._document_editor_save_workflow(application, goal, workspace)
        return self._document_editor_write_and_verify(application, goal)

    def _file_manager_open_and_verify(self, application: str, workspace: Path) -> Tuple[bool, Dict[str, Any]]:
        self.assistant.open_folder(str(workspace))
        self.sleep(1.0)
        after = self._capture_context(refresh=True)
        failure = self._unexpected_modal_reason(after)
        success = not failure and (
            normalize_text(after.get("active_app", "")) == "explorer"
            or normalize_text(workspace.name) in normalize_text(after.get("window_title", ""))
            or "explorer" in normalize_text(after.get("window_title", ""))
        )
        detail = {
            "step": "explorer_open_workspace",
            "strategy": "open_folder",
            "verification": "active_window_matches",
            "workspace": str(workspace),
            "success": success,
            "context_failure": failure or "",
            "evidence": self._build_evidence(
                before={},
                after=after,
                target_control_used="explorer_window",
                selected_text_preview="",
                verification_reason="" if success else (failure or "La ventana activa no parece Explorer."),
                rescue_used=False,
            ),
        }
        return success, detail

    def _file_manager_goal_workflow(self, application: str, goal: str, workspace: Path) -> Tuple[bool, Dict[str, Any]]:
        return self._keyboard_explorer_rename_workflow(goal, workspace)

    def _collect_visible_research(
        self,
        topic: str,
        result_count: int = 3,
        query_variants: Optional[List[str]] = None,
        result_indices: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        queries = [
            str(item).strip()
            for item in (query_variants or [topic])
            if str(item).strip()
        ]
        if not queries:
            queries = [topic]
        planned_indices = [max(1, int(item)) for item in (result_indices or list(range(1, max(2, result_count + 1))))]
        collected_texts: List[str] = []
        reviewed_sources: List[str] = []
        useful_sources: List[Dict[str, Any]] = []
        discarded_titles: List[str] = []
        discard_reasons: List[str] = []
        seen_titles: set[str] = set()
        seen_text_signatures: set[str] = set()
        context_failure = ""
        last_evidence: Dict[str, Any] = {}
        queries_used: List[str] = []
        minimum_chars = int(self._skill_settings("research").get("minimum_summary_capture_chars", 260))
        candidate_indices = self._expand_research_result_indices(
            planned_indices,
            max_candidates=max(5, len(planned_indices) + 2),
        )

        for query in queries:
            search_success, search_detail = self._visible_google_search(
                query=query,
                browser_name="brave",
                step_name="research_visible_search",
            )
            last_evidence = search_detail.get("evidence", {})
            if not search_success:
                context_failure = search_detail.get("context_failure", "No se pudo abrir Google.")
                discarded_titles.append(f"{query} :: sin resultados visibles")
                discard_reasons.append(context_failure)
                continue

            queries_used.append(query)
            results_title = self._capture_context(refresh=True)
            for index in candidate_indices:
                if len(useful_sources) >= max(1, result_count):
                    break
                baseline_title = normalize_text(results_title.get("window_title", ""))
                opened = self.task_executor._open_google_result(index)
                current = self._wait_for_research_page_open(baseline_title)
                page_title = str(current.get("window_title", "") or f"resultado_{index}")
                page_title_key = normalize_text(page_title)
                if (
                    not opened
                    or page_title_key == baseline_title
                    or self._context_matches_site(current, "google")
                    or self._looks_like_google_results_title(page_title)
                ):
                    keyboard_opened, keyboard_after, _keyboard_strategy = self._research_open_result_with_tab_navigation(
                        baseline_title
                    )
                    if keyboard_opened:
                        current = keyboard_after
                        page_title = str(current.get("window_title", "") or f"resultado_{index}")
                        page_title_key = normalize_text(page_title)
                    else:
                        discarded_titles.append(page_title)
                        discard_reasons.append("No hubo transicion visible de pagina.")
                        if opened:
                            self._return_to_google_results()
                        continue
                if self._context_matches_site(current, "google") or self._looks_like_google_results_title(page_title):
                    discarded_titles.append(page_title)
                    discard_reasons.append("No hubo transicion visible de pagina.")
                    self._return_to_google_results()
                    continue
                if page_title_key in seen_titles:
                    discarded_titles.append(page_title)
                    discard_reasons.append("Fuente repetida; busco otra distinta.")
                    self._return_to_google_results()
                    continue
                capture = self._capture_research_page_text(minimum_chars=minimum_chars)
                page_text = str(capture.get("text", "") or "")
                text_signature = normalize_text(page_text[:220])
                is_duplicate_text = bool(text_signature and text_signature in seen_text_signatures)
                source_quality = self._classify_research_source(
                    query,
                    page_title,
                    page_text,
                    capture_context=self._build_research_capture_context(page_title, current, capture),
                )
                if not page_text:
                    discarded_titles.append(page_title)
                    discard_reasons.append(
                        "OCR no devolvio texto util." if capture.get("ocr_unavailable") else "La pagina abrio vacia."
                    )
                elif is_duplicate_text:
                    discarded_titles.append(page_title)
                    discard_reasons.append("Contenido repetido; intento otra fuente.")
                elif not bool(source_quality.get("counts_as_useful")):
                    discarded_titles.append(page_title)
                    discard_reasons.append(str(source_quality.get("reason", "") or "Contenido pobre, vacio o bloqueado."))
                else:
                    collected_texts.append(page_text)
                    reviewed_sources.append(page_title)
                    seen_titles.add(page_title_key)
                    if text_signature:
                        seen_text_signatures.add(text_signature)
                    useful_sources.append(
                        {
                            "index": index,
                            "query": query,
                            "title": page_title,
                            "captured_chars": len(page_text),
                            "source_kind": str(source_quality.get("source_kind", "web_page") or "web_page"),
                            "scene_id": str(source_quality.get("scene_id", "") or ""),
                            "scene_variant": str(source_quality.get("scene_variant", "") or ""),
                            "emergency_feedback": str(source_quality.get("emergency_feedback", "") or ""),
                        }
                    )
                self._return_to_google_results()
                results_title = self._capture_context(refresh=True)
            if len(useful_sources) >= max(1, result_count):
                break
        merged_text = self.task_executor._merge_texts(collected_texts) if collected_texts else ""
        summary = self.assistant.task_planner.summarize_text(merged_text, max_sentences=6) if merged_text else ""
        findings = self.assistant.task_planner.summarize_text(merged_text, max_sentences=5) if merged_text else ""
        return {
            "topic": topic,
            "queries_used": queries_used or queries[:1],
            "reviewed_sources": reviewed_sources,
            "visited_titles": reviewed_sources,
            "discarded_titles": discarded_titles,
            "discard_reasons": discard_reasons,
            "useful_sources": useful_sources,
            "useful_source_count": len(useful_sources),
            "merged_text": merged_text,
            "summary": summary,
            "findings": findings,
            "search_method": "visible_google_bar",
            "context_failure": context_failure,
            "evidence": last_evidence,
        }

    def _empty_cycle(
        self,
        cycle_number: int,
        level: int,
        requested_attempts: Optional[int],
        requested_minutes: Optional[int],
    ) -> Dict[str, Any]:
        return {
            "cycle_number": cycle_number,
            "level": level,
            "attempt_budget": requested_attempts,
            "time_budget_minutes": requested_minutes,
            "status": "retry",
            "steps": [],
            "strategies_tried": [],
            "verifications": [],
            "successes": 0,
            "failures": 0,
            "verified_successes": 0,
            "workflow_successes": 0,
            "context_failures": [],
            "summary": "",
        }

    def _resolve_session_budgets(
        self,
        requested_attempts: Optional[int],
        requested_minutes: Optional[int],
        skill_id: str,
        level: int,
    ) -> Tuple[Optional[int], Optional[int]]:
        settings = self._settings()
        max_attempts = int(settings.get("max_attempts_per_cycle", 20))
        max_minutes = int(settings.get("max_minutes_per_cycle", 10))
        attempts = requested_attempts
        minutes = requested_minutes
        if attempts is not None:
            attempts = max(1, min(int(attempts), max_attempts))
        if minutes is not None:
            minutes = max(1, min(int(minutes), max_minutes))
            if attempts is None:
                attempts = max(2, min(max_attempts, int(minutes) * 2))
        return attempts, minutes

    def _accumulate_metrics(self, profile: Dict[str, Any], level: int, cycle: Dict[str, Any]) -> None:
        metrics = profile.setdefault("level_metrics", {}).setdefault(str(level), self._empty_metrics())
        metrics["successes"] = int(metrics.get("successes", 0)) + int(cycle.get("successes", 0))
        metrics["failures"] = int(metrics.get("failures", 0)) + int(cycle.get("failures", 0))
        metrics["verified_count"] = int(metrics.get("verified_count", 0)) + int(cycle.get("verified_successes", 0))
        metrics["workflow_successes"] = int(metrics.get("workflow_successes", 0)) + int(cycle.get("workflow_successes", 0))
        metrics["sessions"] = int(metrics.get("sessions", 0)) + 1
        total = metrics["successes"] + metrics["failures"]
        metrics["success_rate"] = round(metrics["successes"] / total, 4) if total else 0.0
        metrics["last_cycle_summary"] = cycle.get("summary", "")
        if int(cycle.get("verified_successes", 0)) > 0:
            profile["highest_verified_level"] = max(
                int(profile.get("highest_verified_level", 1)),
                int(level),
            )

    def _apply_promotions(self, profile: Dict[str, Any]) -> bool:
        promoted = False
        gates = profile.get("gates", {})
        current_level = int(profile.get("current_level", 1))
        max_level = int(profile.get("max_level", self.MAX_SKILL_LEVEL) or self.MAX_SKILL_LEVEL)
        while current_level < max_level:
            next_level = current_level + 1
            metrics = profile.get("level_metrics", {}).get(str(current_level), {})
            gate = gates.get(f"{current_level}_to_{next_level}", {})
            if not self._passes_gate(metrics, gate):
                break
            profile["current_level"] = next_level
            profile["state"] = "active"
            profile["real_usage_ready"] = True
            if current_level >= 2:
                profile["highest_verified_level"] = max(
                    int(profile.get("highest_verified_level", 1)),
                    current_level,
                )
            promoted = True
            current_level = next_level
        return promoted

    def _passes_gate(self, metrics: Dict[str, Any], gate: Dict[str, Any]) -> bool:
        success_rate = float(metrics.get("success_rate", 0.0))
        verified_count = int(metrics.get("verified_count", 0))
        workflow_successes = int(metrics.get("workflow_successes", 0))
        minimum_success = float(gate.get("success_rate", 1.0))
        minimum_verified = int(gate.get("verified_count", 0))
        minimum_workflows = int(gate.get("workflow_successes", 0))
        return (
            success_rate >= minimum_success
            and verified_count >= minimum_verified
            and workflow_successes >= minimum_workflows
        )

    def _cycle_failure_is_hard(self, profile: Dict[str, Any], cycle: Dict[str, Any]) -> bool:
        if cycle.get("verified_successes", 0) or cycle.get("workflow_successes", 0):
            return False
        template_kind = normalize_text(str(profile.get("template_kind", "") or ""))
        if template_kind != "research_workflow":
            return True
        steps = cycle.get("steps", [])
        if not isinstance(steps, list) or not steps:
            return True
        for step in steps:
            evidence = step.get("evidence", {}) if isinstance(step.get("evidence", {}), dict) else {}
            if "hard_failure" in step and step.get("hard_failure") is False:
                continue
            if evidence.get("hard_failure") is True:
                return True
            stage = normalize_text(str(step.get("failure_stage") or step.get("verification") or ""))
            if stage and stage not in self.RESEARCH_RECOVERABLE_FAILURES:
                return True
        return False

    def _finalize_profile_state(
        self,
        profile: Dict[str, Any],
        meaningful_success: bool,
        hard_failure: bool = True,
    ) -> None:
        if meaningful_success:
            profile["consecutive_failed_sessions"] = 0
            if profile.get("supported"):
                profile["state"] = "active"
        else:
            if hard_failure:
                profile["consecutive_failed_sessions"] = int(profile.get("consecutive_failed_sessions", 0)) + 1
                threshold = int(self._settings().get("blocked_after_failed_sessions", 3))
                if profile["consecutive_failed_sessions"] >= threshold:
                    profile["state"] = "blocked"
                    self._append_blocker(
                        profile,
                        f"Se alcanzo el umbral de {threshold} sesiones fallidas consecutivas.",
                    )
        if profile.get("skill_id") == "skill:mouse":
            self._refresh_mouse_profile_from_strategy(profile)
        if profile.get("skill_id") == "skill:window_management":
            self._refresh_window_management_profile_from_strategy(profile)
        if profile.get("template_kind") == "game_foundation":
            profile["real_usage_ready"] = bool(profile.get("game_backend_ready", False))
        profile["updated_at"] = self._now()

    def _finalize_session_summary(
        self,
        profile: Dict[str, Any],
        session: Dict[str, Any],
        promoted: bool,
        meaningful_success: bool,
    ) -> None:
        if profile.get("state") == "blocked":
            session["final_decision"] = "blocked"
        elif promoted:
            session["final_decision"] = "promoted"
        else:
            session["final_decision"] = "stay"
        session["end_level"] = int(profile.get("current_level", 1))
        last_cycle = session["cycles"][-1] if session["cycles"] else {}
        lines = [
            f"Habilidad: {profile.get('display_name')}",
            f"Nivel actual: {profile.get('current_level', 1)}",
            f"Nivel verificado maximo: {profile.get('highest_verified_level', 1)}",
            f"Uso real listo: {'si' if profile.get('real_usage_ready') else 'no'}",
            f"Decision final: {session['final_decision']}",
        ]
        if last_cycle:
            lines.append(last_cycle.get("summary", ""))
        if session.get("decisions"):
            lines.append("Decisiones:")
            lines.extend(f"- {item}" for item in session["decisions"])
        coaching = self._profile_progress_snapshot(profile)
        if coaching.get("behavior_summary"):
            lines.append(f"Comportamiento reciente: {coaching['behavior_summary']}")
        if coaching.get("coach_message"):
            lines.append(f"Empuje siguiente: {coaching['coach_message']}")
        if session["final_decision"] == "blocked" and profile.get("last_blockers"):
            lines.append(f"Ultimo bloqueo: {profile['last_blockers'][-1]}")
        session["summary"] = "\n".join(item for item in lines if item)

    def _persist_session(self, profile: Dict[str, Any], session: Dict[str, Any], final_status: str) -> None:
        self.state.setdefault("profiles", {})[profile["skill_id"]] = profile
        self._save_state()
        manifest_path = self.session_store.manifest_path_for(str(session["session_id"]))
        session["manifest_path"] = str(manifest_path)
        research_note_path = self._persist_research_session_note(profile, session)
        if research_note_path:
            session["research_note_path"] = research_note_path
            profile["last_research_note_path"] = research_note_path
            profile["last_investigation_summary"] = str(session.get("summary", "") or "").strip()
            note_line = f"Nota de investigacion: {research_note_path}"
            if note_line not in session["summary"]:
                session["summary"] = "\n".join(
                    item for item in [str(session.get("summary", "") or "").strip(), note_line] if item
                )
        self.session_store.write_session_payload(session)
        profile["last_session_id"] = session["session_id"]
        profile["updated_at"] = self._now()
        self._save_state()

    def _persist_research_session_note(self, profile: Dict[str, Any], session: Dict[str, Any]) -> str:
        if str(profile.get("template_kind", "")) != "research_workflow" and str(profile.get("skill_id", "")) != "skill:investigar":
            return ""

        topic = str(session.get("goal", "") or "").strip()
        queries: List[str] = []
        verified_pages: List[Dict[str, Any]] = []
        useful_sources: List[Dict[str, Any]] = []
        discarded: List[Tuple[str, str]] = []
        summary_text = ""
        findings_text = ""
        document_path = ""

        def add_unique_text(bucket: List[str], value: Any) -> None:
            text = str(value or "").strip()
            if text and text not in bucket:
                bucket.append(text)

        for cycle in session.get("cycles", []):
            if not topic:
                challenge = cycle.get("challenge", {}) if isinstance(cycle.get("challenge", {}), dict) else {}
                topic = str(challenge.get("topic", "") or "").strip() or topic
            for step in cycle.get("steps", []):
                if not isinstance(step, dict):
                    continue
                add_unique_text(queries, step.get("query", ""))
                for query in step.get("queries_used", []) or []:
                    add_unique_text(queries, query)
                for source in step.get("useful_sources", []) or []:
                    if isinstance(source, dict):
                        useful_sources.append(
                            {
                                "query": str(source.get("query", "") or ""),
                                "title": str(source.get("title", "") or ""),
                                "captured_chars": int(source.get("captured_chars", 0) or 0),
                                "scene_id": str(source.get("scene_id", "") or ""),
                                "emergency_feedback": str(source.get("emergency_feedback", "") or ""),
                            }
                        )
                page_title = str(step.get("page_title", "") or "").strip()
                if step.get("success") and page_title:
                    verified_pages.append(
                        {
                            "query": str(step.get("query", "") or ""),
                            "title": page_title,
                            "captured_chars": int(step.get("captured_chars", 0) or 0),
                            "strategy": str(step.get("strategy", "") or ""),
                            "scene_id": str(step.get("scene_id", "") or ""),
                            "emergency_feedback": str(step.get("emergency_feedback", "") or ""),
                        }
                    )
                discarded_titles = [str(item).strip() for item in (step.get("discarded_titles", []) or []) if str(item).strip()]
                discard_reasons = [str(item).strip() for item in (step.get("discard_reasons", []) or [])]
                for index, title in enumerate(discarded_titles):
                    reason = discard_reasons[index] if index < len(discard_reasons) else ""
                    pair = (title, reason)
                    if pair not in discarded:
                        discarded.append(pair)
                if (not step.get("success")) and page_title and str(step.get("failure_reason", "") or "").strip():
                    scene_id = str(step.get("scene_id", "") or "")
                    feedback = str(step.get("emergency_feedback", "") or "")
                    decorated_reason = str(step.get("failure_reason", "") or "").strip()
                    if scene_id:
                        decorated_reason = f"{decorated_reason} | scene={scene_id}"
                    if feedback:
                        decorated_reason = f"{decorated_reason} | feedback={feedback}"
                    pair = (page_title, decorated_reason)
                    if pair not in discarded:
                        discarded.append(pair)
                if not summary_text:
                    summary_text = str(
                        step.get("research_summary")
                        or step.get("summary_preview")
                        or ""
                    ).strip()
                if not findings_text:
                    findings_text = str(step.get("research_findings") or "").strip()
                if not document_path:
                    document_path = str(
                        step.get("document_result")
                        or step.get("document_path")
                        or (step.get("evidence", {}) if isinstance(step.get("evidence", {}), dict) else {}).get("document_path")
                        or ""
                    ).strip()

        if not any([topic, queries, verified_pages, useful_sources, discarded, summary_text, findings_text, document_path]):
            return ""

        lines = [
            "# Nota de investigacion",
            "",
            f"Sesion: {session.get('session_id', '')}",
            f"Habilidad: {session.get('display_name', 'Investigar')}",
            f"Tema: {topic or '(sin tema especifico)'}",
            f"Nivel inicial: {session.get('start_level', 1)}",
            f"Nivel final: {session.get('end_level', session.get('start_level', 1))}",
            f"Decision final: {session.get('final_decision', 'stay')}",
        ]
        if queries:
            lines.extend(["", "## Consultas usadas"])
            lines.extend(f"- {query}" for query in queries)
        if verified_pages:
            lines.extend(["", "## Paginas verificadas"])
            lines.extend(
                f"- {item['title']} | query={item['query'] or 'n/a'} | chars={item['captured_chars']} | estrategia={item['strategy'] or 'n/a'}"
                f"{' | scene=' + item['scene_id'] if item.get('scene_id') else ''}"
                f"{' | feedback=' + item['emergency_feedback'] if item.get('emergency_feedback') else ''}"
                for item in verified_pages
            )
        elif useful_sources:
            lines.extend(["", "## Fuentes utiles"])
            lines.extend(
                f"- {item['title'] or 'fuente sin titulo'} | query={item['query'] or 'n/a'} | chars={item['captured_chars']}"
                f"{' | scene=' + item['scene_id'] if item.get('scene_id') else ''}"
                f"{' | feedback=' + item['emergency_feedback'] if item.get('emergency_feedback') else ''}"
                for item in useful_sources
            )
        if summary_text:
            lines.extend(["", "## Resumen aprendido", summary_text])
        if findings_text:
            lines.extend(["", "## Hallazgos", findings_text])
        if discarded:
            lines.extend(["", "## Descartes"])
            lines.extend(
                f"- {title}: {reason or 'sin razon registrada'}"
                for title, reason in discarded
            )
        if document_path:
            lines.extend(["", "## Documento formal", document_path])
        lines.extend(["", "## Resumen del motor", str(session.get("summary", "") or "").strip()])

        try:
            return self.session_store.write_research_note(str(session["session_id"]), lines)
        except Exception:
            return ""

    def _format_profile_status(self, profile: Dict[str, Any]) -> str:
        progress = self._profile_progress_snapshot(profile)
        lines = [
            f"Habilidad: {profile.get('display_name')}",
            f"- Estado: {profile.get('state', 'draft')}",
            f"- Familia derivada: {profile.get('template_kind', 'draft')}",
            f"- Nivel legado actual: {profile.get('current_level', 1)}",
            f"- Nivel exponencial: {profile.get('exponential_level', 0)}/6",
            f"- Nivel verificado maximo: {profile.get('highest_verified_level', 1)}",
            f"- Uso real listo: {'si' if profile.get('real_usage_ready') else 'no'}",
            f"- Verification version: {profile.get('verification_version', 0)}",
            f"- Tendencia actual: {progress.get('trend', 'sin senal')}",
            f"- Gate siguiente: {progress.get('next_gate_status', 'n/a')}",
        ]
        if progress.get("lagging_reason"):
            lines.append(f"- Riesgo actual: {progress['lagging_reason']}")
        if progress.get("behavior_summary"):
            lines.append(f"- Comportamiento reciente: {progress['behavior_summary']}")
        if progress.get("dominant_failure_scene"):
            stuck_scene = str(progress.get("dominant_failure_scene", "") or "")
            feedback = str(progress.get("dominant_emergency_feedback", "") or "")
            scene_line = f"- Escena dominante: {stuck_scene}"
            if feedback:
                scene_line += f" | feedback={feedback}"
            lines.append(scene_line)
        if progress.get("coach_focus"):
            lines.append(f"- Empuje recomendado: {progress['coach_focus']}")
        if progress.get("coach_message"):
            lines.append(f"- Guia concreta: {progress['coach_message']}")
        reevaluation_summary = str(profile.get("reevaluation_summary", "") or "").strip()
        if reevaluation_summary:
            lines.append(f"- Reevaluacion: {reevaluation_summary}")
        gate_reports = profile.get("gate_reports", {})
        if isinstance(gate_reports, dict) and gate_reports:
            lines.append("- Gates exponenciales:")
            for gate_name, report in gate_reports.items():
                if not isinstance(report, dict):
                    continue
                lines.append(
                    f"  * {gate_name}: passed={'si' if report.get('gate_passed') else 'no'} | "
                    f"success={report.get('current_success_rate', 0)} | "
                    f"fallback={report.get('current_fallback_rate', 0)} | "
                    f"verificados={report.get('verified_sessions_count', 0)}"
                )
        for level in range(1, int(profile.get("max_level", self.MAX_SKILL_LEVEL)) + 1):
            level_key = str(level)
            metrics = profile.get("level_metrics", {}).get(level_key, {})
            if metrics:
                lines.append(
                    f"- Nivel {level_key}: tasa {metrics.get('success_rate', 0):.2f} | "
                    f"verificados {metrics.get('verified_count', 0)} | "
                    f"workflows {metrics.get('workflow_successes', 0)}"
                )
        if profile.get("last_blockers"):
            lines.append(f"- Ultimo bloqueo: {profile['last_blockers'][-1]}")
        if profile.get("metrics_invalidated"):
            lines.append(f"- Metricas reiniciadas: {profile.get('invalidated_reason', 'si')}")
        if profile.get("trainable_draft"):
            draft = profile["trainable_draft"]
            lines.append(
                f"- Draft entrenable: familia={draft.get('family', 'application')} | "
                f"bloqueos={', '.join(draft.get('readiness_blockers', [])) or 'ninguno'}"
            )
        if profile.get("starter_bootstrap"):
            starter = profile["starter_bootstrap"]
            templates = [
                str(item.get("scenario_id", ""))
                for item in starter.get("scenario_templates", [])
                if isinstance(item, dict) and str(item.get("scenario_id", "")).strip()
            ]
            lines.append(
                f"- Arranque guiado: foco={starter.get('coach_focus', 'n/a')} | "
                f"escenarios={', '.join(templates[:3]) or 'ninguno'} | sin credito falso"
            )
        if profile.get("optimized_profile"):
            optimized = profile["optimized_profile"]
            lines.append(
                f"- Perfil optimizado: estrategia principal={optimized.get('primary_strategy', 'n/a')} | "
                f"confianza={optimized.get('confidence', 0)}"
            )
        if profile.get("last_research_note_path"):
            lines.append(f"- Nota de investigacion: {profile['last_research_note_path']}")
        if profile.get("last_session_id"):
            lines.append(f"- Ultima sesion: {profile['last_session_id']}")
        return "\n".join(lines)

    def _repair_supported_profile_state(self, profile: Dict[str, Any]) -> None:
        if not profile.get("supported"):
            return
        blockers = [
            str(item)
            for item in profile.get("last_blockers", [])
            if "Habilidad soportada desconocida" not in str(item)
        ]
        profile["last_blockers"] = blockers
        if profile.get("state") == "draft" or (profile.get("state") == "blocked" and not blockers):
            profile["state"] = "active"
        if profile.get("skill_id") == "skill:mouse":
            self._migrate_legacy_mouse_metrics(profile)
            self._refresh_mouse_profile_from_strategy(profile)
        if profile.get("skill_id") == "skill:window_management":
            self._refresh_window_management_profile_from_strategy(profile)

    def _refresh_mouse_profile_from_strategy(self, profile: Dict[str, Any]) -> None:
        summary = self._legacy_mouse_data_summary()
        profile["legacy_mouse_summary"] = summary
        preferred = profile.setdefault("preferred_strategies", {})
        if summary.get("best_strategy"):
            preferred["desktop_drag_profile"] = summary["best_strategy"]
        ready = bool(summary.get("real_usage_ready"))
        profile["real_usage_ready"] = ready
        if ready:
            profile["highest_verified_level"] = max(int(profile.get("highest_verified_level", 0)), 1)

    def _refresh_window_management_profile_from_strategy(self, profile: Dict[str, Any]) -> None:
        summary = self._window_management_data_summary()
        profile["window_management_summary"] = summary
        preferred = profile.setdefault("preferred_strategies", {})
        if summary.get("strict_split_enabled"):
            preferred["window_layout_mode"] = "strict_split_explorer_halves"
        else:
            preferred.pop("window_layout_mode", None)
        ready = bool(summary.get("real_usage_ready"))
        profile["real_usage_ready"] = ready
        if ready:
            profile["highest_verified_level"] = max(int(profile.get("highest_verified_level", 0)), 1)

    def _migrate_legacy_mouse_metrics(self, profile: Dict[str, Any]) -> None:
        if profile.get("legacy_mouse_metrics_migrated"):
            return
        level_one = profile.get("level_metrics", {}).get("1", {})
        summary = normalize_text(str(level_one.get("last_cycle_summary", "")))
        imported_as_metrics = "historicos" in summary or "importado" in summary
        if imported_as_metrics:
            profile["legacy_mouse_summary"] = self._legacy_mouse_data_summary()
            profile["level_metrics"] = self._default_level_metrics()
            profile["current_level"] = 1
            profile["highest_verified_level"] = 0
            profile["metrics_invalidated"] = True
            profile["invalidated_reason"] = (
                "Metricas historicas del mouse movidas a legacy_mouse_summary; "
                "los niveles ahora se verifican con practica real."
            )
        profile["legacy_mouse_metrics_migrated"] = True

    def _ensure_profile(
        self,
        skill_id: str,
        display_name: str,
        family: str,
        supported: bool,
        template_kind: str = "draft",
        canonical_entity: str = "",
    ) -> Dict[str, Any]:
        profiles = self.state.setdefault("profiles", {})
        if skill_id in profiles:
            profile = profiles[skill_id]
            if bool(profile.get("supported")) and not supported:
                supported = True
                family = str(profile.get("family", family) or family)
                template_kind = str(profile.get("template_kind", template_kind) or template_kind)
                canonical_entity = str(profile.get("canonical_entity", canonical_entity) or canonical_entity)
            profile["display_name"] = display_name
            profile["family"] = family
            profile["supported"] = supported
            profile["template_kind"] = template_kind
            profile["canonical_entity"] = canonical_entity
            profile["gates"] = self._default_gates()
            profile_metrics = profile.setdefault("level_metrics", {})
            for level_key, empty_metrics in self._default_level_metrics().items():
                profile_metrics.setdefault(level_key, empty_metrics)
            profile["max_level"] = self.MAX_SKILL_LEVEL
            profile.setdefault("level_system", "legacy_1_5_with_exponential_0_6")
            profile.setdefault("exponential_level", 0)
            profile.setdefault("max_exponential_level", 6)
            profile.setdefault("optimized_profile", {})
            profile.setdefault("gate_reports", {})
            profile.setdefault("trainable_draft", {})
            profile.setdefault("reevaluation_summary", "")
            profile.setdefault("verification_version", self.VERIFICATION_VERSION)
            profile.setdefault("profile_schema_version", self.PROFILE_SCHEMA_VERSION)
            profile.setdefault("history_rebuild_version", 0)
            self._repair_supported_profile_state(profile)
            return profile
        profile = self._default_profile(
            skill_id=skill_id,
            display_name=display_name,
            family=family,
            supported=supported,
            template_kind=template_kind,
            canonical_entity=canonical_entity,
        )
        profiles[skill_id] = profile
        self._repair_supported_profile_state(profile)
        return profile

    def _activate_generic_supported_profile(
        self,
        profile: Dict[str, Any],
        requested_skill: str,
        goal: str,
    ) -> bool:
        draft_payload = profile.get("trainable_draft", {})
        if not isinstance(draft_payload, dict) or not draft_payload:
            draft_payload = create_trainable_draft(
                skill_id=str(profile.get("skill_id", requested_skill)),
                skill_name=str(profile.get("display_name", requested_skill)),
                description=goal or requested_skill,
            ).to_dict()
            profile["trainable_draft"] = draft_payload

        family_key = normalize_text(
            str(draft_payload.get("family") or draft_payload.get("draft_family") or "application")
        )
        template_kind = self._generic_template_kind_for_draft_family(family_key)
        if not template_kind:
            return False

        canonical_entity = self._generic_canonical_entity_for_draft_family(
            family_key=family_key,
            requested_skill=requested_skill,
            goal=goal,
        )
        profile["family"] = str(draft_payload.get("family") or family_key or "application")
        profile["supported"] = True
        profile["state"] = "active"
        profile["template_kind"] = template_kind
        if canonical_entity:
            profile["canonical_entity"] = canonical_entity
        if family_key == "game":
            profile.setdefault("game_backend_ready", False)
        if not str(profile.get("last_investigation_summary", "") or "").strip():
            profile["last_investigation_summary"] = (
                f"Ruta generica activada para '{goal or requested_skill}': "
                f"familia={family_key} -> template={template_kind}."
            )
        self._repair_supported_profile_state(profile)
        return True

    @staticmethod
    def _generic_template_kind_for_draft_family(family_key: str) -> str:
        mapping = {
            "vision": "visual_perception",
            "research": "research_workflow",
            "browser": "browser_app",
            "file_manager": "file_manager",
            "documents": "document_editor",
            "application": "document_editor",
            "game": "game_foundation",
        }
        return mapping.get(family_key, "document_editor")

    def _generic_canonical_entity_for_draft_family(
        self,
        family_key: str,
        requested_skill: str,
        goal: str,
    ) -> str:
        if family_key == "research":
            return "investigar"
        if family_key == "browser":
            return str(self.config.get("default_browser", "brave") or "brave")
        if family_key == "file_manager":
            return "explorer"
        if family_key in {"documents", "application"}:
            preferred = self._match_application_alias("visual studio code")
            if preferred:
                return preferred
            return self._match_application_alias("notepad") or "notepad"
        if family_key == "game":
            return self._game_canonical_entity(goal or requested_skill)
        return ""

    def _default_profile(
        self,
        skill_id: str,
        display_name: str,
        family: str,
        supported: bool,
        template_kind: str = "draft",
        canonical_entity: str = "",
    ) -> Dict[str, Any]:
        profile = {
            "skill_id": skill_id,
            "display_name": display_name,
            "family": family,
            "template_kind": template_kind,
            "canonical_entity": canonical_entity,
            "state": "active" if supported else "draft",
            "supported": supported,
            "current_level": 1,
            "max_level": self.MAX_SKILL_LEVEL,
            "highest_verified_level": 0,
            "real_usage_ready": False,
            "level_metrics": self._default_level_metrics(),
            "gates": self._default_gates(),
            "preferred_strategies": {},
            "last_investigation_summary": "",
            "last_decomposition": [],
            "last_blockers": [],
            "consecutive_failed_sessions": 0,
            "verification_version": self.VERIFICATION_VERSION,
            "profile_schema_version": self.PROFILE_SCHEMA_VERSION,
            "metrics_invalidated": False,
            "invalidated_reason": "",
            "level_system": "legacy_1_5_with_exponential_0_6",
            "exponential_level": 0,
            "max_exponential_level": 6,
            "optimized_profile": {},
            "gate_reports": {},
            "trainable_draft": {},
            "reevaluation_summary": "",
            "history_rebuild_version": self.HISTORY_REBUILD_VERSION,
            "updated_at": self._now(),
        }
        
        # Auto-import legacy mouse data for mouse skill
        if skill_id == "skill:mouse":
            legacy_import = self._import_legacy_mouse_data()
            if legacy_import:
                profile.update(legacy_import)
        
        return profile

    def _default_level_metrics(self) -> Dict[str, Dict[str, Any]]:
        return {
            str(level): self._empty_metrics()
            for level in range(1, self.MAX_SKILL_LEVEL + 1)
        }

    @staticmethod
    def _empty_metrics() -> Dict[str, Any]:
        return {
            "successes": 0,
            "failures": 0,
            "verified_count": 0,
            "workflow_successes": 0,
            "sessions": 0,
            "success_rate": 0.0,
            "last_cycle_summary": "",
        }

    def _default_gates(self) -> Dict[str, Dict[str, Any]]:
        settings = self._settings()
        gates = settings.get("gates", {})
        default_gate_values = {
            "1_to_2": {
                "success_rate": 0.85,
                "verified_count": 20,
                "workflow_successes": 0,
            },
            "2_to_3": {
                "success_rate": 0.75,
                "verified_count": 0,
                "workflow_successes": 10,
            },
            "3_to_4": {
                "success_rate": 0.86,
                "verified_count": 30,
                "workflow_successes": 16,
            },
            "4_to_5": {
                "success_rate": 0.9,
                "verified_count": 50,
                "workflow_successes": 28,
            },
        }
        resolved: Dict[str, Dict[str, Any]] = {}
        for key, defaults in default_gate_values.items():
            configured = gates.get(key, {})
            resolved[key] = {
                "success_rate": float(configured.get("success_rate", defaults["success_rate"])),
                "verified_count": int(configured.get("verified_count", defaults["verified_count"])),
                "workflow_successes": int(configured.get("workflow_successes", defaults["workflow_successes"])),
            }
        return resolved

    def _import_legacy_mouse_data(self) -> Optional[Dict[str, Any]]:
        """Conecta el historial viejo sin convertirlo en metricas nuevas de nivel."""
        legacy_data = self._read_mouse_strategy()
        if not legacy_data:
            return None
        summary = self._legacy_mouse_data_summary(legacy_data)
        if summary["successes"] == 0 and not summary["real_usage_ready"]:
            return None
        preferred: Dict[str, Any] = {}
        if summary.get("best_strategy"):
            preferred["desktop_drag_profile"] = summary["best_strategy"]
        return {
            "real_usage_ready": bool(summary["real_usage_ready"]),
            "highest_verified_level": 1 if summary["real_usage_ready"] else 0,
            "legacy_mouse_summary": summary,
            "legacy_mouse_metrics_migrated": True,
            "preferred_strategies": preferred,
            "last_investigation_summary": (
                "Historial viejo de mouse conectado; los nuevos niveles se verifican "
                "ejecutando DesktopLearningOrganizer."
            ),
        }

    def _new_session(
        self,
        mode: str,
        skill_id: str,
        display_name: str,
        goal: str,
        user_requested_document: bool,
        start_level: int,
    ) -> Dict[str, Any]:
        safe_skill_id = self._safe_session_slug(skill_id)
        session_id = f"{safe_skill_id}_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        return {
            "session_id": session_id,
            "created_at": self._now(),
            "mode": mode,
            "skill_id": skill_id,
            "display_name": display_name,
            "goal": goal,
            "user_requested_document": user_requested_document,
            "start_level": start_level,
            "end_level": start_level,
            "cycles": [],
            "decisions": [],
            "context_failures": [],
            "final_decision": "stay",
            "summary": "",
            "manifest_path": "",
        }

    def _resolve_skill(self, requested_skill: str) -> Dict[str, Any]:
        normalized = normalize_text(requested_skill)
        stripped = re.sub(r"^(aprende|practica|practicar|evalua|evaluar|usa|usar)\s+", "", normalized).strip()
        stripped = re.sub(r"^(a\s+usar|uso\s+de)\s+", "", stripped).strip()
        stripped = re.sub(r"^para\s+", "", stripped).strip()
        if self._is_game_skill(stripped):
            game_name = self._game_canonical_entity(stripped)
            return {
                "skill_id": f"jugar_{game_name}",
                "display_name": f"Jugar {self._display_game_name(game_name)}",
                "family": "game_foundation",
                "supported": True,
                "template_kind": "game_foundation",
                "canonical_entity": game_name,
            }

        for skill_id, metadata in self.SUPPORTED_SKILLS.items():
            aliases = [normalize_text(alias) for alias in metadata.get("aliases", [])]
            if stripped == skill_id or stripped in aliases or skill_id in stripped:
                return {
                    "skill_id": f"skill:{skill_id}",
                    "display_name": metadata["display_name"],
                    "family": metadata["family"],
                    "supported": True,
                    "template_kind": metadata.get("template_kind", "draft"),
                    "canonical_entity": skill_id,
                }

        if site_name := self._match_site_alias(stripped):
            return {
                "skill_id": f"site:{site_name}",
                "display_name": f"Usar {site_name.title()}",
                "family": "ui_workflow",
                "supported": True,
                "template_kind": "site_workflow",
                "canonical_entity": site_name,
            }

        if app_name := self._match_application_alias(stripped):
            template_kind = self._template_kind_for_application(app_name)
            family = {
                "browser_app": "ui_workflow",
                "document_editor": "document_workflow",
                "file_manager": "ui_workflow",
            }.get(template_kind, "ui_workflow")
            return {
                "skill_id": f"app:{app_name}",
                "display_name": f"Usar {app_name.title()}",
                "family": family,
                "supported": True,
                "template_kind": template_kind,
                "canonical_entity": app_name,
            }

        slug = re.sub(r"[^a-z0-9]+", "_", stripped or normalized).strip("_") or "habilidad"
        return {
            "skill_id": slug,
            "display_name": requested_skill.strip() or slug,
            "family": "draft",
            "supported": False,
            "template_kind": "draft",
            "canonical_entity": "",
        }

    def _is_game_skill(self, text: str) -> bool:
        normalized = normalize_text(text)
        return any(keyword in normalized for keyword in self.GAME_SKILL_KEYWORDS)

    def _game_canonical_entity(self, text: str) -> str:
        normalized = normalize_text(text)
        for canonical, aliases in self.GAME_ALIASES.items():
            if any(alias in normalized for alias in aliases):
                return canonical
        cleaned = re.sub(
            r"^(?:jugar|juego|partida|videojuego|videogame)\s+(?:a\s+)?",
            "",
            normalized,
        ).strip()
        cleaned = re.sub(r"\b(?:aprende|aprender|practica|practicar|entrena|entrenar)\b", "", cleaned).strip()
        return re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_") or "juego"

    @staticmethod
    def _display_game_name(game_name: str) -> str:
        known = {"terraria": "Terraria", "minecraft": "Minecraft"}
        return known.get(game_name, game_name.replace("_", " ").title())

    @staticmethod
    def _game_skill_decomposition(display_game: str) -> List[Dict[str, Any]]:
        return [
            {
                "name": f"investigar controles de {display_game}",
                "status": "partial",
                "primitives": ["smart_site_search", "collect_page_text"],
            },
            {
                "name": f"entrenar teclado para {display_game}",
                "status": "ready",
                "primitives": ["write_text", "hotkey", "press_keys"],
            },
            {
                "name": f"entrenar mouse para {display_game}",
                "status": "ready",
                "primitives": ["movement", "click", "drag", "workflow"],
            },
            {
                "name": f"controlar {display_game} en vivo",
                "status": "pending_backend",
                "primitives": ["game_window_detection", "game_state_verification"],
            },
        ]

    def _match_application_alias(self, text: str) -> Optional[str]:
        catalog = self.config.get("applications", {})
        normalized = normalize_text(text)
        for app_name, data in catalog.items():
            aliases = [app_name]
            if isinstance(data, dict):
                aliases.extend(str(item) for item in data.get("aliases", []))
            normalized_aliases = [normalize_text(item) for item in aliases if str(item).strip()]
            if normalized in normalized_aliases:
                return str(app_name)
            if any(alias and alias in normalized for alias in normalized_aliases):
                return str(app_name)
        return None

    def _match_site_alias(self, text: str) -> Optional[str]:
        catalog = self.config.get("url_aliases", {})
        normalized = normalize_text(text)
        for site_name in catalog.keys():
            alias = normalize_text(str(site_name))
            if normalized == alias or alias in normalized:
                return str(site_name)
        return None

    def _template_kind_for_application(self, app_name: str) -> str:
        normalized = normalize_text(app_name)
        if normalized in self.BROWSER_APPS:
            return "browser_app"
        if normalized in self.DOCUMENT_APPS:
            return "document_editor"
        if normalized in self.FILE_MANAGER_APPS:
            return "file_manager"
        return "application_workflow"

    def _format_draft_summary(
        self,
        profile: Dict[str, Any],
        topic: str,
        decomposition: List[Dict[str, Any]],
    ) -> str:
        lines = [
            f"Habilidad no soportada aun: {topic}",
            "Se creo un perfil draft con descomposicion preliminar.",
            "Subhabilidades estimadas:",
        ]
        for item in decomposition:
            lines.append(
                f"- {item['name']}: {item['status']} | primitivas={', '.join(item['primitives']) or 'ninguna'}"
            )
        draft = profile.get("trainable_draft", {})
        if isinstance(draft, dict) and draft:
            lines.append("Ruta entrenable generada:")
            lines.append(
                f"- Familia: {draft.get('family', 'application')} | dias estimados: {draft.get('estimated_training_days', 7)}"
            )
            templates = [str(item.get("scenario_id", "")) for item in draft.get("scenario_templates", []) if isinstance(item, dict)]
            if templates:
                lines.append(f"- Scenarios base: {', '.join(templates)}")
            blockers = draft.get("readiness_blockers", [])
            if blockers:
                lines.append(f"- Bloqueos actuales: {', '.join(str(item) for item in blockers)}")
            research_queries = [str(item) for item in draft.get("research_queries", []) if str(item).strip()]
            if research_queries:
                lines.append(f"- Consultas de descubrimiento: {', '.join(research_queries)}")
            if draft.get("useful_source_count"):
                lines.append(f"- Fuentes utiles detectadas: {draft.get('useful_source_count', 0)}")
            research_summary = str(draft.get("research_summary", "") or "").strip()
            if research_summary:
                lines.append(f"- Resumen investigado: {research_summary}")
        if any(keyword in normalize_text(topic) for keyword in ("jugar", "juego", "partida", "terraria", "minecraft", "videojuego", "videogame")):
            lines.append(
                "Recomendacion: primero fortalece 'teclado' y 'mouse'; 'investigar' ayuda como acelerador, pero no es requisito duro."
            )
        lines.append("Limite actual: la familia ya es entrenable, pero puede necesitar mapas UI o backends especificos para salir de foundation.")
        return "\n".join(lines)

    def _draft_skill_decomposition(self, topic: str) -> List[Dict[str, Any]]:
        normalized = normalize_text(topic)
        decomposition: List[Dict[str, Any]] = []
        if "youtube" in normalized:
            decomposition.extend(
                [
                    {"name": "abrir youtube", "status": "ready", "primitives": ["ensure_site", "smart_site_search"]},
                    {"name": "abrir resultados", "status": "partial", "primitives": ["tab_navigation", "vision"]},
                ]
            )
        elif "teclado" in normalized:
            decomposition.extend(
                [
                    {"name": "escritura basica", "status": "ready", "primitives": ["write_text", "capture_selected_text"]},
                    {"name": "atajos y navegacion", "status": "partial", "primitives": ["hotkey", "press_keys"]},
                ]
            )
        elif "investig" in normalized:
            decomposition.extend(
                [
                    {"name": "formular busquedas", "status": "ready", "primitives": ["smart_site_search"]},
                    {"name": "capturar texto visible", "status": "ready", "primitives": ["collect_page_text"]},
                    {"name": "comparar fuentes", "status": "partial", "primitives": ["perform_research"]},
                ]
            )
        elif any(keyword in normalized for keyword in ("jugar", "juego", "partida", "terraria", "minecraft", "videojuego", "videogame")):
            decomposition.extend(
                [
                    {
                        "name": "investigar el juego",
                        "status": "partial",
                        "primitives": ["smart_site_search", "collect_page_text"],
                    },
                    {
                        "name": "usar teclado en el juego",
                        "status": "partial",
                        "primitives": ["write_text", "hotkey", "press_keys"],
                    },
                    {
                        "name": "mapear interfaz del juego",
                        "status": "partial",
                        "primitives": ["vision", "mouse", "automation"],
                    },
                ]
            )
        else:
            decomposition.extend(
                [
                    {"name": "analisis de interfaz", "status": "partial", "primitives": ["vision", "mouse", "automation"]},
                    {"name": "practica segura", "status": "missing", "primitives": []},
                    {"name": "verificacion", "status": "partial", "primitives": ["step_logs", "task_runs"]},
                ]
            )
        return decomposition

    def _record_cycle_logs(self, skill_id: str, level: int, cycle: Dict[str, Any]) -> None:
        for index, step in enumerate(cycle.get("steps", []), start=1):
            self.memory.record_step_log(
                task_intent=f"learning_skill:{skill_id}",
                step_name=f"nivel_{level}_paso_{index}",
                status="completed" if step.get("success") else "failed",
                detail=json.dumps(step, ensure_ascii=False)[:3000],
            )

    def _choose_research_topic(
        self,
        requested_goal: str,
        level: int,
        exp_level: int,
        cycle_number: int,
    ) -> str:
        goal = str(requested_goal or "").strip()
        if goal:
            return goal
        pool = self._ranked_research_topics(
            requested_goal=goal,
            level=level,
            exp_level=exp_level,
            cycle_number=cycle_number,
        )
        recent_queries = self._recent_research_queries(limit=18)
        for candidate in pool:
            normalized_candidate = normalize_text(candidate)
            if all(normalized_candidate not in query for query in recent_queries):
                return candidate
        return pool[0]

    @classmethod
    def _research_topic_category(cls, topic: str) -> str:
        normalized = normalize_text(topic)
        if any(token in normalized for token in cls.RESEARCH_CODING_TOKENS):
            return "coding"
        if any(token in normalized for token in ("escritorio", "teclado", "windows", "red")):
            return "desktop"
        if any(token in normalized for token in ("brave", "navegacion", "browser")):
            return "browser"
        if any(token in normalized for token in ("ocr", "document", "archivo", "copias")):
            return "documents"
        if any(token in normalized for token in ("terraria", "minecraft")):
            return "games"
        return "general"

    def _ranked_research_topics(
        self,
        requested_goal: str,
        level: int,
        exp_level: int,
        cycle_number: int,
    ) -> List[str]:
        goal = normalize_text(requested_goal)
        wants_coding = any(token in goal for token in self.RESEARCH_CODING_TOKENS)
        pool = list(self.RESEARCH_TOPIC_LIBRARY)
        start_index = (max(1, level) + max(0, exp_level) + max(1, cycle_number) - 1) % len(pool)
        rotated = pool[start_index:] + pool[:start_index]
        recent_outcomes = self._recent_research_outcomes(limit=24)
        recent_queries = [item["query"] for item in recent_outcomes if item.get("query")]
        failed_queries = [
            item["query"]
            for item in recent_outcomes
            if item.get("query") and not item.get("verified")
        ]
        ranked: List[Tuple[float, int, str]] = []
        for offset, candidate in enumerate(rotated):
            normalized_candidate = normalize_text(candidate)
            category = self._research_topic_category(candidate)
            if category == "coding" and not wants_coding:
                continue
            recent_mentions = sum(1 for query in recent_queries if normalized_candidate in query)
            failed_mentions = sum(1 for query in failed_queries if normalized_candidate in query)
            score = float(self.RESEARCH_TOPIC_CATEGORY_BONUS.get(category, 0.0))
            score -= recent_mentions * 2.0
            score -= failed_mentions * 3.0
            ranked.append((score, offset, candidate))
        if not ranked:
            return rotated
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [candidate for _, _, candidate in ranked]

    def _build_research_challenge(
        self,
        topic: str,
        level: int,
        exp_level: int,
        cycle_number: int,
    ) -> Dict[str, Any]:
        query_variants = self._research_variants(
            topic,
            level=level,
            exp_level=exp_level,
            cycle_number=cycle_number,
        )
        result_indices = self._research_result_indices(
            level=level,
            exp_level=exp_level,
            cycle_number=cycle_number,
        )
        return {
            "topic": topic,
            "query_variants": query_variants,
            "result_indices": result_indices,
            "legacy_level": int(level),
            "exponential_level": int(exp_level),
        }

    def _recent_research_outcomes(self, limit: int = 18) -> List[Dict[str, Any]]:
        outcomes: List[Dict[str, Any]] = []
        for result in self.history_store.structured_results_for_skill("skill:investigar"):
            evidence = result.evidence if isinstance(result.evidence, dict) else {}
            query = normalize_text(str(evidence.get("selected_text_preview") or ""))
            if query:
                outcomes.append({"query": query, "verified": bool(result.verified)})
        return outcomes[-max(1, int(limit)) :]

    def _recent_research_queries(self, limit: int = 18) -> List[str]:
        outcomes = self._recent_research_outcomes(limit=limit)
        return [str(item.get("query", "")) for item in outcomes if str(item.get("query", "")).strip()]

    def _research_dictionary_terms(self) -> List[str]:
        if self._research_dictionary_terms_cache is not None:
            return list(self._research_dictionary_terms_cache)
        allowed_map = {
            normalize_text(term): term
            for term in self.RESEARCH_DICTIONARY_ALLOWLIST
        }
        found_terms: List[str] = []
        dictionary_path = self.paths.dictionary_path
        if dictionary_path.exists():
            with dictionary_path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except Exception:
                        continue
                    normalized_term = normalize_text(payload.get("", ""))
                    original_term = allowed_map.get(normalized_term)
                    if original_term and original_term not in found_terms:
                        found_terms.append(original_term)
                        if len(found_terms) >= len(self.RESEARCH_DICTIONARY_ALLOWLIST):
                            break
        if not found_terms:
            found_terms = list(self.RESEARCH_DICTIONARY_ALLOWLIST[:8])
        self._research_dictionary_terms_cache = found_terms
        return list(found_terms)

    def _research_query_modifiers(
        self,
        level: int,
        exp_level: int,
        cycle_number: int,
    ) -> List[str]:
        base_terms = self._research_dictionary_terms()
        fallback_terms = list(self.RESEARCH_FALLBACK_MODIFIERS)
        pool: List[str] = []
        for item in [*base_terms, *fallback_terms]:
            text = str(item).strip()
            if text and text not in pool:
                pool.append(text)
        if not pool:
            return ["guia", "resumen tecnico", "documentacion"]
        start_index = (max(1, level) * 2 + max(0, exp_level) + max(1, cycle_number) - 1) % len(pool)
        rotated = pool[start_index:] + pool[:start_index]
        limit = 4 if level <= 1 else 6 if level == 2 else 8
        return rotated[:limit]

    def _research_result_indices(self, level: int, exp_level: int, cycle_number: int) -> List[int]:
        pool = [1, 2, 3, 4, 5]
        start_index = (max(1, level) + max(0, exp_level) + max(1, cycle_number) - 1) % len(pool)
        rotated = pool[start_index:] + pool[:start_index]
        count = 2 if level <= 1 else 3 if level == 2 else 4
        return rotated[:count]

    @staticmethod
    def _expand_research_result_indices(
        planned_indices: List[int],
        max_candidates: int = 5,
    ) -> List[int]:
        ordered: List[int] = []
        for index in planned_indices:
            normalized = max(1, int(index))
            if normalized not in ordered:
                ordered.append(normalized)
        for candidate in [1, 2, 3, 4, 5]:
            if candidate not in ordered:
                ordered.append(candidate)
            if len(ordered) >= max(1, int(max_candidates)):
                break
        return ordered[: max(1, int(max_candidates))]

    def _research_variants(
        self,
        topic: str,
        level: int = 1,
        exp_level: int = 0,
        cycle_number: int = 1,
    ) -> List[str]:
        variants: List[str] = []
        configured = self._skill_settings("research").get("query_variants", ["{topic}"])
        for item in configured:
            rendered = str(item).format(topic=topic).strip()
            if rendered and rendered not in variants:
                variants.append(rendered)
        for modifier in self._research_query_modifiers(level, exp_level, cycle_number):
            rendered = f"{topic} {modifier}".strip()
            if rendered and rendered not in variants:
                variants.append(rendered)
        if level >= 2 or exp_level >= 2:
            for suffix in ("comparativa", "casos de uso", "errores comunes"):
                rendered = f"{topic} {suffix}"
                if rendered not in variants:
                    variants.append(rendered)
        if level >= 3 or exp_level >= 3:
            for suffix in ("documentacion", "mejores practicas", "analisis"):
                rendered = f"{topic} {suffix}"
                if rendered not in variants:
                    variants.append(rendered)
        return variants or [topic]

    def _write_text_with_learning(self, domain: str, text: str, allow_clipboard: bool = True) -> str:
        strategies = ["direct_typing"]
        if allow_clipboard:
            strategies.append("clipboard_paste")
        ordered = self._rank_strategies(domain, strategies)
        last_error: Optional[Exception] = None
        for strategy in ordered:
            try:
                use_clipboard = strategy == "clipboard_paste"
                self.automation.write_text(text, interval=0.01, use_clipboard=use_clipboard)
                self.learning.record_strategy_result(domain, strategy, True)
                return strategy
            except Exception as exc:
                last_error = exc
                self.learning.record_strategy_result(domain, strategy, False)
        raise RuntimeError("No se pudo escribir texto con ninguna estrategia.") from last_error

    def _prepare_notepad_training_file(self, target_path: Path) -> None:
        ensure_directory(target_path.parent)
        target_path.write_text("", encoding="utf-8")
        self.assistant.open_application("notepad", extra_args=[str(target_path)])
        self.sleep(1.0)
        if self._dismiss_notepad_save_prompt_if_present():
            self.assistant.open_application("notepad", extra_args=[str(target_path)])
            self.sleep(1.0)
        self._clear_active_editor()

    def _finalize_notepad_training_file(self, target_path: Path) -> None:
        try:
            self.automation.hotkey("ctrl", "s")
            self.sleep(0.35)
            active_title = normalize_text(self.automation.get_active_window_title() or "")
            if "guardar como" in active_title or "save as" in active_title:
                self.automation.write_text(str(target_path), use_clipboard=True)
                self.automation.press_keys(["enter"])
                self.sleep(0.6)
        except Exception:
            pass
        try:
            self.automation.hotkey("alt", "f4")
            self.sleep(0.4)
            self._dismiss_notepad_save_prompt_if_present()
        except Exception:
            pass

    def _dismiss_notepad_save_prompt_if_present(self) -> bool:
        if self._open_file_dialog_visible():
            return self._close_open_file_dialog_if_present(max_attempts=3)
        context = self._capture_context(refresh=True)
        title = normalize_text(context.get("window_title", ""))
        if not self._looks_like_unexpected_modal_title(title) and not self._context_title_matches_expected_app(
            title,
            "notepad",
        ):
            return False
        try:
            captured = self._capture_editor_text(expected_app="notepad") or ""
        except Exception:
            return False
        normalized = normalize_text(captured)
        prompt_tokens = (
            "quieres guardar los cambios",
            "do you want to save your changes",
            "bloc de notas",
            "notepad",
        )
        if not any(token in normalized for token in prompt_tokens):
            return False
        self._emit("Detecte un dialogo previo de guardado en Notepad; lo descarto para limpiar la practica.", "warning")
        try:
            self.automation.press_keys(["right"])
            self.sleep(0.15)
            self.automation.press_keys(["enter"])
            self.sleep(0.8)
            return True
        except Exception:
            return False

    def _clear_active_editor(self, expected_app: str = "notepad") -> bool:
        context = self._capture_context(refresh=True)
        if self._open_file_dialog_visible(context) or self._unexpected_modal_reason(context, expected_app=expected_app):
            return False
        try:
            self.automation.hotkey(*self._select_all_shortcut(expected_app))
            self.sleep(0.08)
            context = self._capture_context(refresh=True)
            if self._open_file_dialog_visible(context) or self._unexpected_modal_reason(context, expected_app=expected_app):
                return False
            self.automation.press_keys(["backspace"])
            self.sleep(0.08)
            context = self._capture_context(refresh=True)
            if self._open_file_dialog_visible(context) or self._unexpected_modal_reason(context, expected_app=expected_app):
                return False
            return True
        except Exception:
            return False

    def _select_all_shortcut(self, expected_app: str = "notepad") -> Tuple[str, str]:
        if normalize_text(expected_app) == "notepad":
            return ("ctrl", "e")
        return ("ctrl", "a")

    def _capture_editor_text(self, expected_app: str = "notepad") -> str:
        context = self._capture_context(refresh=True)
        failure = self._unexpected_modal_reason(context, expected_app=expected_app)
        if failure:
            if normalize_text(expected_app) == "notepad" and self._focus_existing_notepad_window():
                self.sleep(0.2)
                context = self._capture_context(refresh=True)
                failure = self._unexpected_modal_reason(context, expected_app=expected_app)
            if failure:
                return ""
        shortcut = self._select_all_shortcut(expected_app)
        try:
            return self.automation.capture_selected_text(
                select_all=True,
                select_all_shortcut=shortcut,
            )
        except TypeError:
            self.automation.hotkey(*shortcut)
            return self.automation.capture_selected_text(select_all=False)

    def _rank_strategies(self, domain: str, candidates: List[str]) -> List[str]:
        preferred = self.learning.preferred_strategy(domain, candidates)
        if not preferred or preferred not in candidates:
            return list(candidates)
        return [preferred, *[candidate for candidate in candidates if candidate != preferred]]

    def _settings(self) -> Dict[str, Any]:
        settings = self.config.get("learning_skills", {})
        return settings if isinstance(settings, dict) else {}

    def _skill_settings(self, key: str) -> Dict[str, Any]:
        settings = self._settings().get(key, {})
        return settings if isinstance(settings, dict) else {}

    def _session_command_label(self, mode: str, requested_skill: str, goal: str) -> str:
        suffix = f" | {goal}" if goal else ""
        return f"{mode}:{requested_skill}{suffix}"

    @staticmethod
    def _safe_session_slug(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("._-") or "session"

    def _append_blocker(self, profile: Dict[str, Any], message: str) -> None:
        blockers = list(profile.get("last_blockers", []))
        blockers.append(message)
        profile["last_blockers"] = blockers[-5:]

    def _emit(self, message: str, level: str = "info") -> None:
        if self.progress_callback:
            try:
                self.progress_callback(message, level)
            except Exception:
                pass
        if self.logger:
            log_fn = getattr(self.logger, level, None) or getattr(self.logger, "info", None)
            if log_fn:
                try:
                    log_fn(message)
                except Exception:
                    pass

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _load_state(self) -> Dict[str, Any]:
        return self.profile_store.load_state(
            profile_schema_version=self.PROFILE_SCHEMA_VERSION,
            now_provider=self._now,
            normalize_profile=self._normalize_loaded_profile,
        )

    def _with_defaults(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        state = {
            "version": self.PROFILE_SCHEMA_VERSION,
            "updated_at": self._now(),
            "profiles": {},
        }
        state["updated_at"] = payload.get("updated_at", state["updated_at"])
        normalized_profiles: Dict[str, Dict[str, Any]] = {}
        raw_profiles = payload.get("profiles", {})
        for key, raw_profile in raw_profiles.items():
            profile = self._normalize_loaded_profile(key, raw_profile)
            normalized_profiles[profile["skill_id"]] = profile
        state["profiles"] = normalized_profiles
        return state

    def _normalize_loaded_profile(self, key: str, raw_profile: Dict[str, Any]) -> Dict[str, Any]:
        original_id = str(raw_profile.get("skill_id") or key)
        resolved = self._resolve_skill(raw_profile.get("display_name") or original_id)
        if original_id in {"teclado", "investigar", "youtube"}:
            remap = {
                "teclado": self._resolve_skill("teclado"),
                "investigar": self._resolve_skill("investigar"),
                "youtube": self._resolve_skill("youtube"),
            }
            resolved = remap[original_id]
        elif ":" in original_id:
            resolved["skill_id"] = original_id
            resolved["display_name"] = raw_profile.get("display_name", resolved["display_name"])

        profile = self._default_profile(
            skill_id=resolved["skill_id"],
            display_name=raw_profile.get("display_name", resolved["display_name"]),
            family=raw_profile.get("family", resolved["family"]),
            supported=bool(raw_profile.get("supported", resolved.get("supported", False))),
            template_kind=raw_profile.get("template_kind", resolved.get("template_kind", "draft")),
            canonical_entity=raw_profile.get("canonical_entity", resolved.get("canonical_entity", "")),
        )
        for field_name, value in raw_profile.items():
            if field_name == "skill_id":
                continue
            profile[field_name] = value
        profile["skill_id"] = resolved["skill_id"]
        profile["template_kind"] = raw_profile.get("template_kind", resolved.get("template_kind", "draft"))
        profile["canonical_entity"] = raw_profile.get("canonical_entity", resolved.get("canonical_entity", ""))
        profile["profile_schema_version"] = self.PROFILE_SCHEMA_VERSION
        profile["history_rebuild_version"] = int(raw_profile.get("history_rebuild_version", 0) or 0)
        if int(profile.get("verification_version", 0)) != self.VERIFICATION_VERSION:
            if not self._requires_metric_reset_for_verification_upgrade(profile):
                profile["verification_version"] = self.VERIFICATION_VERSION
                self._repair_supported_profile_state(profile)
                return profile
            profile["level_metrics"] = self._default_level_metrics()
            profile["current_level"] = 1
            profile["highest_verified_level"] = 0
            profile["real_usage_ready"] = False
            profile["state"] = "active" if profile.get("supported") else "draft"
            profile["consecutive_failed_sessions"] = 0
            profile["metrics_invalidated"] = True
            profile["invalidated_reason"] = (
                f"Metricas reiniciadas por migracion a verificacion estricta v{self.VERIFICATION_VERSION}."
            )
            profile["verification_version"] = self.VERIFICATION_VERSION
        self._repair_supported_profile_state(profile)
        return profile

    @staticmethod
    def _requires_metric_reset_for_verification_upgrade(profile: Dict[str, Any]) -> bool:
        return (
            profile.get("skill_id") == "skill:teclado"
            or normalize_text(profile.get("template_kind", "")) == "keyboard"
        )

    def _save_state(self) -> None:
        self.profile_store.save_state(self.state, updated_at=self._now())

    def _reconcile_profiles_from_history(self) -> bool:
        changed = False
        for profile in self.state.get("profiles", {}).values():
            changed = self._rebuild_profile_from_history(profile) or changed
        return changed

    def reevaluate_all_profiles(self) -> bool:
        changed = False
        for skill_id, profile in self.state.get("profiles", {}).items():
            updated = self._reevaluate_profile(skill_id, profile)
            changed = changed or updated
        if changed:
            self._save_state()
        return changed

    def _rebuild_profile_from_history(self, profile: Dict[str, Any]) -> bool:
        skill_id = str(profile.get("skill_id", "") or "")
        template_kind = normalize_text(str(profile.get("template_kind", "") or ""))
        if skill_id not in {"skill:teclado", "skill:investigar", "skill:visualizacion"} and template_kind not in {
            "keyboard",
            "research_workflow",
            "visual_perception",
        }:
            return False
        if int(profile.get("history_rebuild_version", 0) or 0) >= self.HISTORY_REBUILD_VERSION:
            return False

        previous = {
            "current_level": int(profile.get("current_level", 1) or 1),
            "highest_verified_level": int(profile.get("highest_verified_level", 0) or 0),
            "real_usage_ready": bool(profile.get("real_usage_ready")),
            "consecutive_failed_sessions": int(profile.get("consecutive_failed_sessions", 0) or 0),
            "state": str(profile.get("state", "draft") or "draft"),
            "level_metrics": json.dumps(profile.get("level_metrics", {}), sort_keys=True, ensure_ascii=False),
            "last_blockers": json.dumps(profile.get("last_blockers", []), sort_keys=True, ensure_ascii=False),
        }
        history = self._dedupe_training_history(self._profile_training_history(skill_id))
        if not history:
            profile["history_rebuild_version"] = self.HISTORY_REBUILD_VERSION
            return previous["state"] != str(profile.get("state", "draft") or "draft")
        rebuilt_metrics = self._rebuild_level_metrics_from_history(profile, history)
        profile["level_metrics"] = rebuilt_metrics
        profile["current_level"] = self._legacy_level_from_metrics(profile)
        profile["highest_verified_level"] = self._highest_verified_level_from_history(profile, history)
        profile["real_usage_ready"] = bool(profile["current_level"] >= 2 or profile["highest_verified_level"] >= 2)
        profile["consecutive_failed_sessions"] = self._consecutive_failed_sessions_from_history(profile, history)
        threshold = int(self._settings().get("blocked_after_failed_sessions", 3))
        blockers = [
            str(item)
            for item in profile.get("last_blockers", [])
            if "sesiones fallidas consecutivas" not in str(item)
        ]
        profile["last_blockers"] = blockers
        if profile["consecutive_failed_sessions"] >= threshold:
            profile["state"] = "blocked"
            self._append_blocker(
                profile,
                f"Se alcanzo el umbral de {threshold} sesiones fallidas consecutivas.",
            )
        elif profile.get("supported"):
            profile["state"] = "active"
        profile["metrics_invalidated"] = True
        profile["invalidated_reason"] = (
            f"Campos derivados reconstruidos desde evidencia real con history rebuild v{self.HISTORY_REBUILD_VERSION}."
        )
        profile["history_rebuild_version"] = self.HISTORY_REBUILD_VERSION
        profile["updated_at"] = self._now()

        current = {
            "current_level": int(profile.get("current_level", 1) or 1),
            "highest_verified_level": int(profile.get("highest_verified_level", 0) or 0),
            "real_usage_ready": bool(profile.get("real_usage_ready")),
            "consecutive_failed_sessions": int(profile.get("consecutive_failed_sessions", 0) or 0),
            "state": str(profile.get("state", "draft") or "draft"),
            "level_metrics": json.dumps(profile.get("level_metrics", {}), sort_keys=True, ensure_ascii=False),
            "last_blockers": json.dumps(profile.get("last_blockers", []), sort_keys=True, ensure_ascii=False),
        }
        return previous != current

    def _reevaluate_profile(self, skill_id: str, profile: Dict[str, Any]) -> bool:
        previous_level = int(profile.get("exponential_level", 0) or 0)
        previous_reports = dict(profile.get("gate_reports", {}) or {})
        previous_optimized = dict(profile.get("optimized_profile", {}) or {})
        previous_summary = str(profile.get("reevaluation_summary", "") or "")
        legacy_level = int(profile.get("current_level", 1) or 1)
        reports: Dict[str, Any] = {}
        optimized_profile: Dict[str, Any] = {}
        raw_level = 0

        history = self._profile_training_history(skill_id)
        if normalize_text(skill_id) in {"skill:mouse", "desktop-first"} or profile.get("template_kind") == "mouse_control":
            evaluation = self.desktop_verifier.evaluate_history(history)
            raw_level = int(evaluation.get("level", 0) or 0)
            reports = dict(evaluation.get("gates", {}))
            optimized_profile = dict(evaluation.get("optimized_profile") or {})
        elif skill_id == "skill:visualizacion" or profile.get("template_kind") == "visual_perception":
            evaluation = self.visual_verifier.evaluate_history(history)
            raw_level = int(evaluation.get("level", 0) or 0)
            reports = dict(evaluation.get("gates", {}))
            optimized_profile = dict(evaluation.get("optimized_profile") or {})
        elif skill_id == "skill:investigar" or profile.get("template_kind") == "research_workflow":
            evaluation = self.research_verifier.evaluate_history(history)
            raw_level = int(evaluation.get("level", 0) or 0)
            reports = dict(evaluation.get("gates", {}))
            optimized_profile = dict(evaluation.get("optimized_profile") or {})
        else:
            raw_level = self._generic_exponential_level_from_metrics(profile)
            reports = {}
            optimized_profile = dict(profile.get("optimized_profile") or {})

        legacy_cap = self._max_exponential_level_for_legacy(legacy_level)
        new_level = min(raw_level, legacy_cap)
        cap_note = ""
        if new_level != raw_level:
            cap_note = f" Limitado por legacy a exp {new_level}/{legacy_cap}."

        summary = (
            f"Reevaluado desde legacy nivel {legacy_level} a exponencial {new_level} "
            f"usando {len(history)} scenario result(s).{cap_note}"
        )
        profile["level_system"] = "legacy_1_5_with_exponential_0_6"
        profile["exponential_level"] = new_level
        profile["max_exponential_level"] = 6
        profile["gate_reports"] = reports
        profile["optimized_profile"] = optimized_profile
        profile["reevaluation_summary"] = summary
        return (
            previous_level != new_level
            or previous_reports != reports
            or previous_optimized != optimized_profile
            or previous_summary != summary
        )

    def _dedupe_training_history(self, history: List[TrainingScenarioResult]) -> List[TrainingScenarioResult]:
        ordered = sorted(history, key=lambda item: (item.timestamp, item.session_id, item.scenario_id, item.status))
        unique: List[TrainingScenarioResult] = []
        seen: set[tuple[str, str, int, str, bool]] = set()
        for item in ordered:
            key = (
                str(item.session_id or ""),
                str(item.scenario_id or ""),
                int(item.timestamp or 0),
                str(item.status or ""),
                bool(item.verified),
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def _rebuild_level_metrics_from_history(
        self,
        profile: Dict[str, Any],
        history: List[TrainingScenarioResult],
    ) -> Dict[str, Dict[str, Any]]:
        metrics_map = self._default_level_metrics()
        sessions_by_level: Dict[str, set[str]] = {key: set() for key in metrics_map}
        for result in history:
            assigned_level = self._legacy_level_for_history_result(profile, result)
            hard_verified = self._result_has_hard_verification(result)
            success = hard_verified and result.status in {"success", "success_with_fallback"}
            credited_levels = [assigned_level]
            if success and assigned_level > 1:
                credited_levels = list(range(1, assigned_level + 1))
            for credited_level in credited_levels:
                level = str(credited_level)
                metrics = metrics_map.setdefault(level, self._empty_metrics())
                if success:
                    metrics["successes"] = int(metrics.get("successes", 0)) + 1
                elif credited_level == assigned_level:
                    metrics["failures"] = int(metrics.get("failures", 0)) + 1
                if hard_verified:
                    metrics["verified_count"] = int(metrics.get("verified_count", 0)) + 1
                if hard_verified and self._result_counts_as_workflow(profile, result, credited_level):
                    metrics["workflow_successes"] = int(metrics.get("workflow_successes", 0)) + 1
                session_key = str(result.session_id or f"{result.timestamp}:{result.scenario_id}:{level}")
                if session_key not in sessions_by_level[level]:
                    sessions_by_level[level].add(session_key)
                    metrics["sessions"] = int(metrics.get("sessions", 0)) + 1
                metrics["last_cycle_summary"] = (
                    f"Reconstruido desde {result.scenario_id}: "
                    f"{'ok' if success else 'failure'} | verificado={'si' if result.verified else 'no'}"
                )
        for metrics in metrics_map.values():
            total = int(metrics.get("successes", 0)) + int(metrics.get("failures", 0))
            metrics["success_rate"] = round(int(metrics.get("successes", 0)) / total, 4) if total else 0.0
        return metrics_map

    def _legacy_level_from_metrics(self, profile: Dict[str, Any]) -> int:
        current_level = 1
        max_level = int(profile.get("max_level", self.MAX_SKILL_LEVEL) or self.MAX_SKILL_LEVEL)
        gates = profile.get("gates", {})
        while current_level < max_level:
            next_level = current_level + 1
            metrics = profile.get("level_metrics", {}).get(str(current_level), {})
            gate = gates.get(f"{current_level}_to_{next_level}", {})
            if not self._passes_gate(metrics, gate):
                break
            current_level = next_level
        return current_level

    def _result_has_hard_verification(self, result: TrainingScenarioResult) -> bool:
        evidence = dict(result.evidence or {})
        explicit = evidence.get("current_session_verified")
        if explicit is not None:
            return bool(explicit)

        page_label = normalize_text(str(evidence.get("page_usefulness_label", "")) or "")
        if page_label in {"poor", "mixed", "empty", "unknown"}:
            return False

        visible_chars = int(
            evidence.get("visible_text_chars", evidence.get("captured_chars", 0)) or 0
        )
        transcript_chars = int(evidence.get("transcript_chars", 0) or 0)
        if visible_chars <= 0 and transcript_chars <= 0:
            return False

        verification_source = normalize_text(str(evidence.get("verification_source", "")) or "")
        if not verification_source:
            return False

        return True

    def _legacy_level_for_history_result(
        self,
        profile: Dict[str, Any],
        result: TrainingScenarioResult,
    ) -> int:
        scenario_keys = {str(result.scenario_id or "")}
        base = str((result.evidence or {}).get("base_scenario_id") or "")
        if base:
            scenario_keys.add(base)
        template_kind = normalize_text(str(profile.get("template_kind", "") or ""))
        if template_kind == "keyboard" or str(profile.get("skill_id")) == "skill:teclado":
            for scenario_key in scenario_keys:
                level = self.KEYBOARD_HISTORY_SCENARIO_LEVELS.get(scenario_key)
                if level:
                    return level
        if template_kind == "research_workflow" or str(profile.get("skill_id")) == "skill:investigar":
            for scenario_key in scenario_keys:
                level = self.RESEARCH_HISTORY_SCENARIO_LEVELS.get(scenario_key)
                if level:
                    return level
        if template_kind == "visual_perception" or str(profile.get("skill_id")) == "skill:visualizacion":
            for scenario_key in scenario_keys:
                level = self.VISUAL_HISTORY_SCENARIO_LEVELS.get(scenario_key)
                if level:
                    return level
        return max(1, min(self.MAX_SKILL_LEVEL, int(result.level or 1)))

    def _result_counts_as_workflow(
        self,
        profile: Dict[str, Any],
        result: TrainingScenarioResult,
        assigned_level: int,
    ) -> bool:
        template_kind = normalize_text(str(profile.get("template_kind", "") or ""))
        if template_kind == "research_workflow":
            return assigned_level >= 2 and self._result_has_hard_verification(result)
        if template_kind == "keyboard":
            return assigned_level >= 2 and self._result_has_hard_verification(result)
        return assigned_level >= 2 and self._result_has_hard_verification(result)

    def _highest_verified_level_from_history(
        self,
        profile: Dict[str, Any],
        history: List[TrainingScenarioResult],
    ) -> int:
        levels = [
            self._legacy_level_for_history_result(profile, item)
            for item in history
            if item.verified
        ]
        return max(levels, default=0)

    def _consecutive_failed_sessions_from_history(
        self,
        profile: Dict[str, Any],
        history: List[TrainingScenarioResult],
    ) -> int:
        session_order: List[str] = []
        grouped: Dict[str, List[TrainingScenarioResult]] = {}
        for item in sorted(history, key=lambda row: (row.timestamp, row.session_id, row.scenario_id)):
            session_key = str(item.session_id or f"{item.timestamp}:{item.scenario_id}")
            if session_key not in grouped:
                grouped[session_key] = []
                session_order.append(session_key)
            grouped[session_key].append(item)
        consecutive = 0
        for session_key in session_order:
            attempts = grouped[session_key]
            meaningful_success = any(
                self._result_counts_as_verified_session_success(item)
                for item in attempts
            )
            if meaningful_success:
                consecutive = 0
                continue
            if self._session_failure_is_hard(profile, attempts):
                consecutive += 1
            else:
                consecutive = 0
        return consecutive

    def _result_counts_as_verified_session_success(self, item: TrainingScenarioResult) -> bool:
        if self._result_has_hard_verification(item):
            return True
        evidence = dict(item.evidence or {})
        return bool(evidence.get("current_session_verified"))

    def _session_failure_is_hard(
        self,
        profile: Dict[str, Any],
        attempts: List[TrainingScenarioResult],
    ) -> bool:
        template_kind = normalize_text(str(profile.get("template_kind", "") or ""))
        if template_kind != "research_workflow":
            return True
        for item in attempts:
            evidence = dict(item.evidence or {})
            if evidence.get("hard_failure") is False:
                continue
            if evidence.get("hard_failure") is True:
                return True
            stage = normalize_text(str(item.failure_stage or ""))
            if stage and stage not in self.RESEARCH_RECOVERABLE_FAILURES:
                return True
        return False

    def _max_exponential_level_for_legacy(self, legacy_level: int) -> int:
        legacy = max(0, int(legacy_level or 0))
        if legacy <= 0:
            return 0
        if legacy >= self.MAX_SKILL_LEVEL:
            return 6
        return min(legacy, 4)

    def _generic_exponential_level_from_metrics(self, profile: Dict[str, Any]) -> int:
        metrics_map = profile.get("level_metrics", {})
        verified_count = sum(int(metrics.get("verified_count", 0) or 0) for metrics in metrics_map.values())
        workflow_successes = sum(int(metrics.get("workflow_successes", 0) or 0) for metrics in metrics_map.values())
        successes = sum(int(metrics.get("successes", 0) or 0) for metrics in metrics_map.values())
        failures = sum(int(metrics.get("failures", 0) or 0) for metrics in metrics_map.values())
        total = successes + failures
        success_rate = successes / total if total else 0.0
        ready = bool(profile.get("real_usage_ready"))

        if (
            profile.get("optimized_profile")
            and ready
            and verified_count >= 50
            and workflow_successes >= 10
            and success_rate >= 0.80
        ):
            return 6
        if ready and verified_count >= 50 and workflow_successes >= 8 and success_rate >= 0.80:
            return 5
        if ready and verified_count >= 30 and workflow_successes >= 4 and success_rate >= 0.85:
            return 4
        if ready and verified_count >= 20 and workflow_successes >= 2 and success_rate >= 0.90:
            return 3
        if verified_count >= 12 and workflow_successes >= 1 and success_rate >= 0.95:
            return 2
        if verified_count >= 5 and success_rate >= 0.99 and failures == 0:
            return 1
        return 0

    def _profile_training_history(self, skill_id: str) -> List[TrainingScenarioResult]:
        normalized = normalize_text(skill_id)
        results: List[TrainingScenarioResult] = self._structured_history_results(skill_id)
        if normalized == "desktop-first":
            results.extend(self._desktop_history_results())
        elif normalized == "skill:mouse" or self.state.get("profiles", {}).get(skill_id, {}).get("template_kind") == "mouse_control":
            results.extend(self._mouse_strategy_results())
        elif normalized == "skill:visualizacion" or self.state.get("profiles", {}).get(skill_id, {}).get("template_kind") == "visual_perception":
            results.extend(self._visual_strategy_results())
        else:
            for manifest_path in sorted(self.sessions_dir.glob("*.json")):
                try:
                    payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
                except Exception:
                    continue
                if payload.get("skill_id") != skill_id:
                    continue
                results.extend(self._scenario_results_from_learning_manifest(payload))
        return sorted(results, key=lambda item: (item.timestamp, item.session_id, item.scenario_id))

    def _structured_history_results(self, skill_id: str) -> List[TrainingScenarioResult]:
        return self.history_store.structured_results_for_skill(skill_id)

    def _desktop_history_results(self) -> List[TrainingScenarioResult]:
        results: List[TrainingScenarioResult] = []
        session_dir = self.organizer_store.sessions_dir
        if not session_dir.exists():
            return results
        for manifest_path in sorted(session_dir.glob("session_*.json")):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            for index, move in enumerate(payload.get("moves", []), start=1):
                details = move.get("details", {}) if isinstance(move.get("details", {}), dict) else {}
                status = str(move.get("status", "failure"))
                results.append(
                    TrainingScenarioResult(
                        skill_id="desktop-first",
                        domain="selection/workflow",
                        scenario_id="desktop_drag_real_verify",
                        level=4 if move.get("verified") else 3,
                        status="success_with_fallback" if status == "completed_with_fallback" else ("success" if move.get("verified") else "failure"),
                        verified=bool(move.get("verified")),
                        session_id=str(payload.get("session_id", "")),
                        failure_stage=(
                            details.get("desktop_attempt", {}).get("failure_stage")
                            if isinstance(details.get("desktop_attempt", {}), dict)
                            else details.get("failure_stage")
                        ),
                        fallback_used="explorer_fallback" if details.get("fallback_used") else None,
                        attempted_strategies=[
                            str(item)
                            for item in [
                                details.get("desktop_attempt", {}).get("attempt_type"),
                                details.get("fallback_attempt", {}).get("attempt_type"),
                                (details.get("fallback_attempt", {}) or {}).get("next_fallback", {}).get("attempt_type"),
                            ]
                            if item
                        ],
                        chosen_strategy=str(details.get("path_taken") or details.get("profile") or ""),
                        metrics={
                            "latency_ms": float(move.get("duration_seconds", 0.0) or 0.0) * 1000.0,
                            "verification_latency_ms": float(move.get("duration_seconds", 0.0) or 0.0) * 1000.0,
                        },
                        evidence={
                            "destination_path": move.get("destination"),
                            "destination": move.get("destination"),
                            "source_file_size": None,
                            "selection_detection": details.get("selection_detection", {}),
                        },
                        verified_outcome={"verified": bool(move.get("verified")), "path_taken": details.get("path_taken", "")},
                    )
                )
        return results

    def _mouse_strategy_results(self) -> List[TrainingScenarioResult]:
        payload = self._read_mouse_strategy()
        if not payload:
            return []
        practice = payload.get("practice", {}) if isinstance(payload.get("practice", {}), dict) else {}
        metric_to_scenario = {
            "movement": "ui_detect_visible",
            "click": "mouse_click_visible",
            "double_click": "mouse_click_reopened_window",
            "right_click": "mouse_click_reopened_window",
            "drag": "desktop_drag_constrained",
        }
        results: List[TrainingScenarioResult] = []
        for metric_key, scenario_id in metric_to_scenario.items():
            metric: Dict[str, Any]
            if metric_key == "drag":
                metric = practice if isinstance(practice, dict) and practice.get("last_session_id") else {}
            else:
                metric = practice.get(metric_key, {}) if isinstance(practice.get(metric_key, {}), dict) else {}
            if not metric:
                continue
            successes = int(metric.get("successes", 0) or 0)
            failures = int(metric.get("failures", 0) or 0)
            total = max(1, int(metric.get("attempts", successes + failures) or (successes + failures or 1)))
            success_rate = float(metric.get("success_rate", successes / total if total else 0.0) or 0.0)
            base_session_id = str(metric.get("session_id") or metric.get("last_session_id") or metric_key)
            capped_total = min(total, 40)
            for attempt_index in range(capped_total):
                is_success = attempt_index < successes
                results.append(
                    TrainingScenarioResult(
                        skill_id="skill:mouse",
                        domain="vision/detection",
                        scenario_id=scenario_id,
                        level=2 if metric_key == "drag" else 1,
                        status="success" if is_success else "failure",
                        verified=is_success,
                        session_id=f"{base_session_id}_{attempt_index + 1}",
                        fallback_used=None,
                        attempted_strategies=[metric_key],
                        chosen_strategy=str(metric_key),
                        metrics={
                            "success_rate": success_rate,
                            "attempts": total,
                        },
                        evidence={
                            "practice_metric": metric_key,
                            "reliable": bool(metric.get("reliable") or metric.get("real_drag_enabled")),
                        },
                        verified_outcome={
                            "successes": successes,
                            "failures": failures,
                            "success_rate": success_rate,
                            "attempt_index": attempt_index + 1,
                        },
                    )
                )
        return results

    def _visual_strategy_results(self) -> List[TrainingScenarioResult]:
        payload = self._read_mouse_strategy()
        if not payload:
            return []
        metric_to_scenario = {
            "detection": "visual_target_reacquire",
            "selection": "visual_workflow_precondition",
            "workflow": "visual_adversarial_recovery",
        }
        results: List[TrainingScenarioResult] = []
        for metric_key, scenario_id in metric_to_scenario.items():
            metric = self._mouse_practice_metric(payload, metric_key)
            if not metric:
                continue
            successes = int(metric.get("successes", 0) or 0)
            failures = int(metric.get("failures", 0) or 0)
            total = max(1, int(metric.get("attempts", successes + failures) or (successes + failures or 1)))
            success_rate = float(metric.get("success_rate", successes / total if total else 0.0) or 0.0)
            base_session_id = str(metric.get("session_id") or metric_key)
            capped_total = min(total, 40)
            for attempt_index in range(capped_total):
                is_success = attempt_index < successes
                results.append(
                    TrainingScenarioResult(
                        skill_id="skill:visualizacion",
                        domain="perception",
                        scenario_id=scenario_id,
                        level=self.VISUAL_HISTORY_SCENARIO_LEVELS.get(scenario_id, 1),
                        status="success" if is_success else "failure",
                        verified=is_success and bool(metric.get("reliable")),
                        session_id=f"{base_session_id}_{attempt_index + 1}",
                        attempted_strategies=[metric_key],
                        chosen_strategy=str(metric_key),
                        metrics={
                            "success_rate": success_rate,
                            "attempts": total,
                            "confidence": success_rate,
                        },
                        evidence={
                            "practice_metric": metric_key,
                            "base_scenario_id": scenario_id,
                            "verification_source": "desktop_mouse_strategy",
                            "confidence": success_rate,
                            "selected_target_confidence": success_rate,
                            "actable_target_count": 1 if is_success else 0,
                            "selected_target_id": metric_key if is_success else "",
                            "scene_kind": "browser_article" if metric_key != "workflow" else "youtube_watch",
                            "initial_blocked": metric_key == "workflow" and not is_success,
                            "recovered": metric_key == "workflow" and is_success,
                            "precondition_ready": metric_key == "selection" and is_success,
                            "reacquire": {
                                "matched": metric_key == "detection" and is_success,
                                "delta_px": 0.0 if is_success else None,
                                "stable_signature_match": bool(is_success),
                            },
                            "ocr_only": False,
                        },
                        verified_outcome={
                            "successes": successes,
                            "failures": failures,
                            "success_rate": success_rate,
                            "attempt_index": attempt_index + 1,
                        },
                    )
                )
        return results

    def _scenario_results_from_learning_manifest(self, payload: Dict[str, Any]) -> List[TrainingScenarioResult]:
        skill_id = str(payload.get("skill_id", ""))
        results: List[TrainingScenarioResult] = []
        created_at = str(payload.get("created_at", ""))
        session_id = str(payload.get("session_id", ""))
        for cycle in payload.get("cycles", []):
            level = int(cycle.get("level", 0) or 0)
            for index, step in enumerate(cycle.get("steps", []), start=1):
                evidence = step.get("evidence", {}) if isinstance(step.get("evidence", {}), dict) else {}
                if skill_id == "skill:mouse" and "successes" in step:
                    successes = int(step.get("successes", 0) or 0)
                    failures = int(step.get("failures", 0) or 0)
                    total = max(1, successes + failures)
                    results.append(
                        TrainingScenarioResult(
                            skill_id=skill_id,
                            domain=self._manifest_skill_domain(skill_id),
                            scenario_id=str(step.get("skill") or f"mouse_step_{index}"),
                            level=max(0, min(6, level)),
                            status="success" if successes > 0 and failures == 0 else ("success_with_fallback" if successes > failures else "failure"),
                            verified=bool(successes > 0),
                            session_id=session_id,
                            timestamp=self._timestamp_from_iso(created_at),
                            failure_stage="action" if failures else None,
                            fallback_used=None,
                            attempted_strategies=[str(step.get("method", ""))],
                            chosen_strategy=str(step.get("method", "")),
                            retryable=failures > 0,
                            metrics={
                                "success_rate": float(step.get("success_rate", successes / total if total else 0.0) or 0.0),
                                "attempts": int(step.get("attempts", total) or total),
                            },
                            evidence={"session_id": step.get("session_id", ""), "reliable": bool(step.get("reliable"))},
                            verified_outcome={"successes": successes, "failures": failures},
                        )
                    )
                    continue
                scenario_id = str(step.get("scenario_id") or "") or self._manifest_step_to_scenario_id(skill_id, step, index)
                step_success = bool(step.get("success"))
                status = "success" if step_success else "failure"
                if evidence.get("rescue_used"):
                    status = "success_with_fallback" if step_success else "failure"
                enriched_evidence = dict(evidence)
                metrics = {
                    "captured_chars": int(
                        step.get("captured_chars", 0)
                        or enriched_evidence.get("captured_chars", 0)
                        or 0
                    ),
                    "unique_facts": 0,
                }
                if skill_id == "skill:investigar":
                    reviewed_sources = [
                        str(item)
                        for item in (step.get("visited_titles") or enriched_evidence.get("reviewed_sources") or [])
                        if str(item).strip()
                    ]
                    queries_used = [
                        str(item)
                        for item in (step.get("queries_used") or enriched_evidence.get("queries_used") or [])
                        if str(item).strip()
                    ]
                    discarded_titles = [
                        str(item)
                        for item in (step.get("discarded_titles") or enriched_evidence.get("discarded_titles") or [])
                        if str(item).strip()
                    ]
                    discard_reasons = [
                        str(item)
                        for item in (step.get("discard_reasons") or enriched_evidence.get("discard_reasons") or [])
                        if str(item).strip()
                    ]
                    document_path = str(
                        step.get("document_result")
                        or enriched_evidence.get("document_path")
                        or enriched_evidence.get("output_path")
                        or ""
                    )
                    useful_source_count = int(
                        step.get("useful_source_count", 0)
                        or enriched_evidence.get("useful_source_count", 0)
                        or len(reviewed_sources)
                    )
                    discard_precision = float(
                        step.get("discard_precision", 0.0)
                        or enriched_evidence.get("discard_precision", 0.0)
                        or 0.0
                    )
                    if discard_precision <= 0.0 and useful_source_count + len(discarded_titles) > 0:
                        discard_precision = useful_source_count / (useful_source_count + len(discarded_titles))
                    if str(step.get("step") or "") == "research_query_attempt":
                        page_title = str(step.get("page_title") or enriched_evidence.get("page_title") or "")
                        query_text = str(step.get("query") or "")
                        source_quality = self._classify_research_source_from_manifest(
                            query=query_text,
                            page_title=page_title,
                            captured_chars=metrics["captured_chars"],
                            source_kind=str(enriched_evidence.get("source_kind") or ""),
                        )
                        step_success = step_success and bool(source_quality.get("counts_as_useful"))
                        if not step_success and page_title:
                            discarded_titles.append(page_title)
                            discard_reasons.append(str(source_quality.get("reason", "") or "La fuente historica no cuenta como util."))
                        useful_source_count = int(source_quality.get("useful_source_count", 0) or 0)
                    enriched_evidence.update(
                        {
                            "reviewed_sources": reviewed_sources[:5],
                            "visited_titles": reviewed_sources[:5],
                            "queries_used": queries_used[:6],
                            "discarded_titles": discarded_titles[:6],
                            "discard_reasons": discard_reasons[:6],
                            "useful_source_count": useful_source_count,
                            "research_summary": str(
                                step.get("research_summary")
                                or step.get("summary_preview")
                                or enriched_evidence.get("research_summary")
                                or ""
                            ).strip(),
                            "research_findings": str(
                                step.get("research_findings")
                                or enriched_evidence.get("research_findings")
                                or ""
                            ).strip(),
                            "discard_precision": discard_precision,
                            "page_title": str(step.get("page_title") or enriched_evidence.get("page_title") or ""),
                            "title_matches_query": bool(
                                source_quality.get("title_matches_query")
                            ) if str(step.get("step") or "") == "research_query_attempt" else bool(
                                enriched_evidence.get("title_matches_query")
                            ),
                            "source_quality_reason": str(
                                source_quality.get("reason", "") or enriched_evidence.get("source_quality_reason", "")
                            ).strip() if str(step.get("step") or "") == "research_query_attempt" else str(
                                enriched_evidence.get("source_quality_reason", "") or ""
                            ).strip(),
                            "source_kind": str(
                                source_quality.get("source_kind", enriched_evidence.get("source_kind", "web_page"))
                            ) if str(step.get("step") or "") == "research_query_attempt" else str(
                                enriched_evidence.get("source_kind", "web_page")
                            ),
                            "scene_id": str(
                                source_quality.get("scene_id", enriched_evidence.get("scene_id", ""))
                            ) if str(step.get("step") or "") == "research_query_attempt" else str(
                                enriched_evidence.get("scene_id", "")
                            ),
                            "scene_variant": str(
                                source_quality.get("scene_variant", enriched_evidence.get("scene_variant", ""))
                            ) if str(step.get("step") or "") == "research_query_attempt" else str(
                                enriched_evidence.get("scene_variant", "")
                            ),
                            "emergency_feedback": str(
                                source_quality.get("emergency_feedback", enriched_evidence.get("emergency_feedback", ""))
                            ).strip() if str(step.get("step") or "") == "research_query_attempt" else str(
                                enriched_evidence.get("emergency_feedback", "") or ""
                            ).strip(),
                            "read_policy": str(
                                source_quality.get("read_policy", enriched_evidence.get("read_policy", ""))
                            ) if str(step.get("step") or "") == "research_query_attempt" else str(
                                enriched_evidence.get("read_policy", "")
                            ),
                            "ignore_policy": str(
                                source_quality.get("ignore_policy", enriched_evidence.get("ignore_policy", ""))
                            ) if str(step.get("step") or "") == "research_query_attempt" else str(
                                enriched_evidence.get("ignore_policy", "")
                            ),
                            "valid_exit_rule": str(
                                source_quality.get("valid_exit_rule", enriched_evidence.get("valid_exit_rule", ""))
                            ) if str(step.get("step") or "") == "research_query_attempt" else str(
                                enriched_evidence.get("valid_exit_rule", "")
                            ),
                            "page_usefulness_label": str(
                                source_quality.get("page_usefulness_label", enriched_evidence.get("page_usefulness_label", "poor"))
                            ) if str(step.get("step") or "") == "research_query_attempt" else str(
                                enriched_evidence.get("page_usefulness_label", "poor")
                            ),
                            "current_session_verified": step_success if str(step.get("step") or "") == "research_query_attempt" else bool(
                                enriched_evidence.get("current_session_verified", step_success)
                            ),
                        }
                    )
                    if document_path:
                        enriched_evidence["document_path"] = document_path
                        enriched_evidence["output_path"] = document_path
                    metrics["discard_precision"] = discard_precision
                    metrics["useful_source_count"] = useful_source_count
                    status = "success" if step_success else "failure"
                    if evidence.get("rescue_used"):
                        status = "success_with_fallback" if step_success else "failure"
                metrics["unique_facts"] = metrics["captured_chars"] // 500 if metrics["captured_chars"] else 0
                result = TrainingScenarioResult(
                    skill_id=skill_id,
                    domain=self._manifest_skill_domain(skill_id),
                    scenario_id=scenario_id,
                    level=max(0, min(5, level + (1 if step_success else 0))),
                    status=status,
                    verified=step_success,
                    session_id=session_id,
                    timestamp=self._timestamp_from_iso(created_at),
                    failure_stage=str(step.get("failure_stage") or step.get("verification") or step.get("step") or ""),
                    fallback_used="copy_to_clipboard" if evidence.get("rescue_used") else None,
                    attempted_strategies=[str(item) for item in cycle.get("strategies_tried", [])],
                    chosen_strategy=str(step.get("strategy") or ""),
                    retryable=not step_success,
                    metrics=metrics,
                    evidence=enriched_evidence,
                    verified_outcome={"verification": step.get("verification", ""), "success": bool(step.get("success"))},
                    error_log=str(step.get("failure_reason", "") or step.get("context_failure", "") or ""),
                )
                if skill_id == "skill:investigar":
                    verification = self.research_verifier.verify(result)
                    result.verified_outcome.update(verification.get("verified_outcome", {}))
                    result.verified = bool(step.get("success")) and bool(
                        verification.get("single_source_verified")
                        or verification.get("multi_query_verified")
                        or verification.get("verified")
                        or verification.get("file_exists")
                    )
                elif skill_id == "skill:visualizacion":
                    result.level = self.VISUAL_HISTORY_SCENARIO_LEVELS.get(scenario_id, max(1, min(5, level)))
                    verification = self.visual_verifier.verify(result)
                    result.verified_outcome.update(verification.get("verified_outcome", {}))
                    result.verified = bool(step.get("success")) and bool(
                        verification.get("context_identity_verified")
                        or verification.get("target_reacquire_verified")
                        or verification.get("scene_transition_verified")
                        or verification.get("workflow_precondition_verified")
                        or verification.get("adversarial_recovery_verified")
                    )
                results.append(result)
        return results

    def training_domain_states(self) -> List[Dict[str, Any]]:
        states: List[Dict[str, Any]] = []
        for domain in (
            "keyboard",
            "perception",
            "vision/detection",
            "selection/workflow",
            "research",
            "browser",
            "file_manager/explorer",
            "document_editor",
            "application_workflow",
            "game_foundation",
        ):
            results = self._results_for_domain(domain)
            active_profiles = self._profiles_for_domain(domain)
            verified = [item for item in results if item.verified]
            recent = results[-20:] if len(results) > 20 else results
            successes = sum(1 for item in recent if item.status in {"success", "success_with_fallback"})
            fallback_count = sum(1 for item in recent if item.fallback_used)
            success_rate = successes / len(recent) if recent else 0.0
            fallback_rate = fallback_count / len(recent) if recent else 0.0
            freshness_score = 1.0 if not recent else max(0.0, 1.0 - min(1.0, self._days_since_result(recent[-1]) / 14.0))
            days_stagnant = self._days_since_verified(verified[-1]) if verified else 30.0
            operational_score = 0.0
            if any(not bool(profile.get("real_usage_ready")) for profile in active_profiles):
                operational_score += 0.3
            if any(int(profile.get("exponential_level", 0) or 0) <= 2 for profile in active_profiles):
                operational_score += 0.4
            states.append(
                {
                    "domain": domain,
                    "success_rate": success_rate,
                    "fallback_rate": fallback_rate,
                    "days_stagnant": days_stagnant,
                    "freshness_score": freshness_score,
                    "operational_score": min(1.0, operational_score),
                    "active_skill_ids": [str(profile.get("skill_id")) for profile in active_profiles],
                }
            )
        return states

    def _results_for_domain(self, domain: str) -> List[TrainingScenarioResult]:
        results: List[TrainingScenarioResult] = []
        for skill_id, profile in self.state.get("profiles", {}).items():
            if not self._profile_matches_domain(profile, domain):
                continue
            results.extend(
                item for item in self._profile_training_history(skill_id) if item.domain == domain
            )
        return sorted(results, key=lambda item: (item.timestamp, item.session_id, item.scenario_id))

    def _profiles_for_domain(self, domain: str) -> List[Dict[str, Any]]:
        return [
            profile
            for profile in self.state.get("profiles", {}).values()
            if self._profile_matches_domain(profile, domain)
        ]

    def _profile_matches_domain(self, profile: Dict[str, Any], domain: str) -> bool:
        return self._profile_domain(profile) == domain

    def _profile_domain(self, profile: Dict[str, Any]) -> str:
        template_kind = normalize_text(str(profile.get("template_kind", "")))
        skill_id = normalize_text(str(profile.get("skill_id", "")))
        if template_kind == "keyboard" or skill_id == "skill:teclado":
            return "keyboard"
        if template_kind == "mouse_control" or skill_id == "skill:mouse":
            return "vision/detection"
        if template_kind == "visual_perception" or skill_id == "skill:visualizacion":
            return "perception"
        if template_kind == "window_management" or skill_id == "skill:window_management":
            return "file_manager/explorer"
        if template_kind == "research_workflow" or "investigar" in skill_id:
            return "research"
        if template_kind in {"browser_app", "site_workflow"}:
            return "browser"
        if template_kind == "file_manager":
            return "file_manager/explorer"
        if template_kind == "document_editor":
            return "document_editor"
        if template_kind == "game_foundation" or "jugar_" in skill_id:
            return "game_foundation"
        return "application_workflow"

    @staticmethod
    def _days_since_result(result: TrainingScenarioResult) -> float:
        if not result.timestamp:
            return 30.0
        return max(0.0, (time.time() - float(result.timestamp)) / 86400.0)

    def _days_since_verified(self, result: TrainingScenarioResult) -> float:
        return self._days_since_result(result)

    @staticmethod
    def _timestamp_from_iso(value: str) -> int:
        try:
            return int(datetime.fromisoformat(value).timestamp())
        except Exception:
            return 0

    @staticmethod
    def _manifest_skill_domain(skill_id: str) -> str:
        normalized = normalize_text(skill_id)
        if "teclado" in normalized:
            return "keyboard"
        if "visualizacion" in normalized:
            return "perception"
        if "investigar" in normalized:
            return "research"
        if "brave" in normalized or "youtube" in normalized:
            return "browser"
        if "word" in normalized or "notepad" in normalized:
            return "document_editor"
        if "window_management" in normalized:
            return "file_manager/explorer"
        if "explorer" in normalized:
            return "file_manager/explorer"
        if "jugar" in normalized or "terraria" in normalized or "minecraft" in normalized:
            return "game_foundation"
        if "mouse" in normalized:
            return "vision/detection"
        return "application_workflow"

    @staticmethod
    def _manifest_step_to_scenario_id(skill_id: str, step: Dict[str, Any], index: int) -> str:
        normalized_skill = normalize_text(skill_id)
        step_name = normalize_text(str(step.get("step", "") or f"step_{index}"))
        step_skill = normalize_text(str(step.get("skill", "") or ""))
        verification = normalize_text(str(step.get("verification", "") or "base"))
        explicit_scenario = normalize_text(str(step.get("scenario_id", "") or ""))
        if explicit_scenario:
            return explicit_scenario
        if "visualizacion" in normalized_skill:
            if verification in {
                "visual_context_identity",
                "visual_target_reacquire",
                "visual_scene_transition",
                "visual_workflow_precondition",
                "visual_adversarial_recovery",
            }:
                return verification
            if "reacquire" in step_name or "deteccion" in step_name:
                return "visual_target_reacquire"
            if "trans" in step_name:
                return "visual_scene_transition"
            if "precondition" in step_name or "workflow" in step_name:
                return "visual_workflow_precondition"
            if "recovery" in step_name or "adversarial" in step_name:
                return "visual_adversarial_recovery"
            return "visual_context_identity"
        if "investigar" in normalized_skill:
            failure_stage = normalize_text(str(step.get("failure_stage") or ""))
            if step_name == "research_query_attempt" or "page_text_quality" in verification:
                if "adversarial" in failure_stage:
                    return "research_adversarial_recovery"
                if "autonomous" in failure_stage:
                    return "research_autonomous_discovery"
                if "cross_verify" in failure_stage:
                    return "research_cross_verify"
                return "research_single_source" if int(step.get("captured_chars", 0) or 0) < 500 else "research_multi_query"
            if step_name == "research_summary_attempt" or "sources_and_summary" in verification:
                if float(step.get("discard_precision", 0.0) or 0.0) >= 0.70:
                    return "research_discard_poor"
                return "research_structured_extract"
            if "document" in step_name or "save" in step_name:
                return "research_to_document"
            if "cross_verify" in step_name:
                return "research_cross_verify"
            if "adversarial" in step_name:
                return "research_adversarial_recovery"
            if "autonomous" in step_name:
                return "research_autonomous_discovery"
        if "window_management" in normalized_skill:
            failure_stage = normalize_text(str(step.get("failure_stage") or ""))
            if "occlusion" in failure_stage or "occluded" in failure_stage:
                return "explorer_window_occlusion_recovery"
            if "repair" in step_name or "repair" in verification or "repair" in failure_stage:
                return "explorer_window_layout_repair"
            return "explorer_window_layout_stable"
        if "brave" in normalized_skill or "youtube" in normalized_skill:
            if "open" in step_name and "google" in step_name:
                return "browser_open_google"
            if "search" in step_name or "result" in step_name:
                return "browser_search_result"
            return "browser_form_fill"
        if "teclado" in normalized_skill:
            keyboard_map = {
                "keyboard_write_verify": "keyboard_text_entry",
                "keyboard_explorer_open": "keyboard_explorer_open",
                "keyboard_explorer_search": "keyboard_explorer_search",
                "keyboard_notepad_save": "document_save_verified",
                "keyboard_window_switch": "keyboard_window_switch",
                "keyboard_window_focus": "keyboard_window_focus",
                "keyboard_window_close": "keyboard_window_close",
                "keyboard_minimize_all": "keyboard_minimize_all",
                "keyboard_maximize_window": "keyboard_maximize_window",
                "keyboard_multiapp_chain": "keyboard_multiapp_chain",
                "keyboard_browser_address_focus": "keyboard_browser_address_focus",
            }
            if step_name in keyboard_map:
                return keyboard_map[step_name]
        if "word" in normalized_skill or "notepad" in normalized_skill:
            if "save" in step_name or "goal" in step_name:
                return "document_save_verified"
            if "replace" in step_name or "workflow" in step_name:
                return "document_replace_text"
            return "document_write_basic"
        if "explorer" in normalized_skill:
            if "rename" in step_name or "goal" in step_name:
                return "explorer_move_verified"
            if "open" in step_name:
                return "explorer_open_workspace"
            return "explorer_select_item"
        if "jugar" in normalized_skill:
            if "investig" in step_skill:
                return "game_control_lookup"
            if "goal" in step_name or "workflow" in step_name:
                return "game_goal_chain"
            return "game_input_foundation"
        return f"{step_name}:{verification}"
