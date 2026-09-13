from __future__ import annotations

import json
import re
import socket
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from core.data_paths import DataPaths
from core.models.page_usefulness_classifier import PageUsefulnessClassifier
from core.models.ui_target_ranker import UITargetRankerModel
from core.skills import normalize_text
from core.training_catalog import DOMAIN_SCENARIOS as TRAINING_DOMAIN_SCENARIOS, ORDERED_TRAINING_DOMAINS
from core.training_models import DomainTrainingState, TrainingScenarioResult
from core.training_scheduler import DOMAIN_PRIORITY_RANKS, SkillScheduler
from core.vision import tesseract_runtime_available


class CurrentSessionVerifier:
    """Verificador conservador: solo acepta evidencia fresca de la sesion actual."""

    def __init__(self, family: str) -> None:
        self.family = family

    def verify(self, result: TrainingScenarioResult) -> Dict[str, object]:
        current_session_verified = bool(result.evidence.get("current_session_verified"))
        return {
            "verified": current_session_verified,
            "verified_outcome": {
                "current_session_verified": current_session_verified,
                "verification_family": self.family,
                "verification_source": result.evidence.get("verification_source", "unknown"),
                "base_scenario_id": result.evidence.get("base_scenario_id", ""),
            },
        }


class InfiniteTrainingLoop:
    """Loop continuo con scheduler ponderado, verificación y recuperación auditable."""

    LEGACY_DOMAIN_SCENARIOS: Dict[str, List[Dict[str, Any]]] = {
        "keyboard": [
            {"scenario_id": "keyboard_text_entry", "runner": "practice_skill", "skill_label": "teclado", "level": 0, "family": "keyboard"},
            {"scenario_id": "keyboard_browser_address_focus", "runner": "practice_skill", "skill_label": "teclado", "level": 2, "family": "keyboard"},
            {"scenario_id": "keyboard_explorer_search", "runner": "practice_skill", "skill_label": "teclado", "level": 2, "family": "keyboard"},
            {"scenario_id": "keyboard_window_switch", "runner": "practice_skill", "skill_label": "teclado", "level": 4, "family": "keyboard"},
            {"scenario_id": "keyboard_multiapp_chain", "runner": "practice_skill", "skill_label": "teclado", "level": 5, "family": "keyboard"},
        ],
        "perception": [
            {"scenario_id": "visual_context_identity", "runner": "practice_skill", "skill_label": "visualizacion", "level": 0, "family": "perception"},
            {"scenario_id": "visual_target_reacquire", "runner": "practice_skill", "skill_label": "visualizacion", "level": 2, "family": "perception"},
            {"scenario_id": "visual_scene_transition", "runner": "practice_skill", "skill_label": "visualizacion", "level": 3, "family": "perception"},
            {"scenario_id": "visual_workflow_precondition", "runner": "practice_skill", "skill_label": "visualizacion", "level": 4, "family": "perception"},
            {"scenario_id": "visual_adversarial_recovery", "runner": "practice_skill", "skill_label": "visualizacion", "level": 5, "family": "perception"},
        ],
        "vision/detection": [
            {"scenario_id": "ui_detect_visible", "runner": "practice_mouse_movement", "skill_label": "mouse", "level": 0},
            {"scenario_id": "mouse_click_visible", "runner": "practice_mouse_click", "skill_label": "mouse", "level": 1},
            {"scenario_id": "mouse_click_reopened_window", "runner": "practice_mouse_double_click", "skill_label": "mouse", "level": 1},
            {"scenario_id": "mouse_right_click_visible", "runner": "practice_mouse_right_click", "skill_label": "mouse", "level": 1},
            {"scenario_id": "ui_detect_distracted", "runner": "practice_mouse_detection", "skill_label": "mouse", "level": 2},
            {"scenario_id": "ocr_partial_region", "runner": "practice_mouse_selection", "skill_label": "mouse", "level": 2},
        ],
        "selection/workflow": [
            {"scenario_id": "desktop_drag_constrained", "runner": "practice_desktop_mouse", "skill_label": "mouse", "level": 2},
            {"scenario_id": "desktop_drag_no_fallback", "runner": "practice_mouse_selection", "skill_label": "mouse", "level": 2},
            {"scenario_id": "desktop_drag_real_verify", "runner": "practice_mouse_workflow", "skill_label": "mouse", "level": 3},
            {"scenario_id": "desktop_recovery_verified", "runner": "practice_mouse_workflow", "skill_label": "mouse", "level": 4},
            {"scenario_id": "desktop_adversarial_verify", "runner": "practice_mouse_workflow", "skill_label": "mouse", "level": 5},
            {"scenario_id": "desktop_autonomous_discovery", "runner": "practice_mouse_workflow", "skill_label": "mouse", "level": 5},
        ],
        "research": [
            {"scenario_id": "research_single_source", "runner": "practice_skill", "skill_label": "investigar", "level": 0},
            {"scenario_id": "research_multi_query", "runner": "practice_skill", "skill_label": "investigar", "level": 2},
            {"scenario_id": "research_structured_extract", "runner": "practice_skill", "skill_label": "investigar", "level": 3},
            {"scenario_id": "research_discard_poor", "runner": "practice_skill", "skill_label": "investigar", "level": 3},
            {"scenario_id": "research_to_document", "runner": "practice_skill", "skill_label": "investigar", "level": 4, "create_document": True},
            {"scenario_id": "research_cross_verify", "runner": "practice_skill", "skill_label": "investigar", "level": 4, "create_document": True},
            {"scenario_id": "research_adversarial_recovery", "runner": "practice_skill", "skill_label": "investigar", "level": 5, "create_document": True},
            {"scenario_id": "research_autonomous_discovery", "runner": "practice_skill", "skill_label": "investigar", "level": 5, "create_document": True},
        ],
        "browser": [
            {"scenario_id": "browser_open_google", "runner": "practice_skill", "skill_label": "brave", "level": 0},
            {"scenario_id": "browser_search_result", "runner": "practice_skill", "skill_label": "brave", "level": 2},
            {"scenario_id": "browser_form_fill", "runner": "practice_skill", "skill_label": "youtube", "level": 3},
            {
                "scenario_id": "youtube_audio_visual_interpretation",
                "base_scenario_id": "browser_form_fill",
                "runner": "practice_skill",
                "skill_label": "youtube",
                "level": 3,
                "family": "browser",
                "training_goal": "tutorial basico con transcripcion o texto visible",
            },
        ],
        "file_manager/explorer": [
            {"scenario_id": "explorer_open_workspace", "runner": "practice_skill", "skill_label": "explorer", "level": 0},
            {"scenario_id": "explorer_select_item", "runner": "practice_skill", "skill_label": "explorer", "level": 1},
            {"scenario_id": "explorer_window_layout_stable", "runner": "practice_skill", "skill_label": "window management", "level": 1},
            {"scenario_id": "explorer_window_layout_repair", "runner": "practice_skill", "skill_label": "window management", "level": 2},
            {"scenario_id": "explorer_window_occlusion_recovery", "runner": "practice_skill", "skill_label": "window management", "level": 3},
            {"scenario_id": "explorer_move_verified", "runner": "practice_skill", "skill_label": "explorer", "level": 3},
        ],
        "document_editor": [
            {"scenario_id": "document_write_basic", "runner": "practice_skill", "skill_label": "notepad", "level": 0},
            {"scenario_id": "document_replace_text", "runner": "practice_skill", "skill_label": "notepad", "level": 1},
            {"scenario_id": "document_save_verified", "runner": "practice_skill", "skill_label": "notepad", "level": 3},
        ],
        "application_workflow": [
            {"scenario_id": "application_open_verify", "runner": "practice_skill", "skill_label": "youtube", "level": 0},
            {"scenario_id": "application_click_target", "runner": "practice_skill", "skill_label": "youtube", "level": 1},
            {"scenario_id": "application_goal_workflow", "runner": "practice_skill", "skill_label": "youtube", "level": 3},
        ],
        "game_foundation": [
            {"scenario_id": "game_input_foundation", "runner": "practice_skill", "skill_label": "jugar terraria", "level": 0},
            {"scenario_id": "game_control_lookup", "runner": "practice_skill", "skill_label": "jugar terraria", "level": 1},
            {"scenario_id": "game_goal_chain", "runner": "practice_skill", "skill_label": "jugar terraria", "level": 4},
        ],
    }

    DOMAIN_SCENARIOS: Dict[str, List[Dict[str, Any]]] = TRAINING_DOMAIN_SCENARIOS

    def __init__(
        self,
        base_dir: Path,
        assistant: Any,
        learning_skill_engine: Any,
        scheduler: Optional[SkillScheduler] = None,
        recovery_engine: Optional[Any] = None,
        logger: Optional[Any] = None,
        progress_callback: Optional[Callable[[str, str], None]] = None,
        stop_checker: Optional[Callable[[], bool]] = None,
        ui_target_ranker: Optional[UITargetRankerModel] = None,
        page_usefulness_classifier: Optional[PageUsefulnessClassifier] = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.paths = DataPaths.from_base_dir(self.base_dir)
        self.assistant = assistant
        self.learning_skill_engine = learning_skill_engine
        self.scheduler = scheduler or SkillScheduler()
        self.recovery_engine = recovery_engine
        self.logger = logger
        self.progress_callback = progress_callback
        self.stop_checker = stop_checker
        self.ui_target_ranker = ui_target_ranker or UITargetRankerModel()
        self.page_usefulness_classifier = page_usefulness_classifier or PageUsefulnessClassifier()
        self.history_path = self.paths.resolve_runtime_path("infinite_training_history")
        self.dataset_path = self.paths.resolve_runtime_path("runtime_training_dataset")
        self.session_history: List[TrainingScenarioResult] = []
        self.mouse_attempts = 6
        self.keyboard_attempts = 6
        self.pause_seconds = 2.0
        self.domain_repeat_cooldown = 2
        self.recent_domains: List[str] = []
        self._blocked_domain_notices: Set[str] = set()
        self._session_verifiers: Dict[str, CurrentSessionVerifier] = {
            family: CurrentSessionVerifier(family)
            for family in ("keyboard", "browser", "file_manager", "documents", "application", "game")
        }
        self.paths.ensure_base_structure()

    def configure_budgets(
        self,
        mouse_attempts: Optional[int] = None,
        keyboard_attempts: Optional[int] = None,
        pause_seconds: Optional[float] = None,
    ) -> None:
        if mouse_attempts is not None:
            self.mouse_attempts = max(1, int(mouse_attempts))
        if keyboard_attempts is not None:
            self.keyboard_attempts = max(1, int(keyboard_attempts))
        if pause_seconds is not None:
            self.pause_seconds = max(0.5, float(pause_seconds))

    def run_one_cycle(
        self,
        preferred_domain: Optional[str] = None,
        forced_scenario: Optional[Dict[str, Any]] = None,
        forced_skill_id: Optional[str] = None,
    ) -> TrainingScenarioResult:
        state_objects = self._build_domain_states()
        selected_state = self._select_domain_state(state_objects, preferred_domain)
        domain = selected_state.domain
        self._internet_available_cache = None
        self._remember_domain_selection(domain)
        _, _, seeded_profile = self._select_skill(domain, forced_skill_id)
        seeded_level = int(seeded_profile.get("exponential_level", 0) or 0) if seeded_profile else 0
        available_skill_labels = self._domain_available_skill_labels(domain, forced_skill_id)
        scenario = self._select_scenario(
            domain,
            seeded_level,
            forced_scenario,
            allowed_skill_labels=available_skill_labels,
        )
        skill_id, skill_label, profile = self._select_skill(
            domain,
            forced_skill_id,
            preferred_skill_label=str(scenario.get("skill_label", "") or ""),
        )
        current_exp_level = int(profile.get("exponential_level", 0) or 0) if profile else 0
        effective_level = self._effective_scenario_level(scenario, current_exp_level)
        ranking_meta = scenario.pop("_ranking_meta", {})
        previous_history_signatures = self._history_signatures(skill_id)

        raw_result = self._execute_scenario(domain, scenario, skill_label)
        history_candidates = self._fresh_history_results(skill_id, previous_history_signatures)
        result = self._build_structured_result(
            domain=domain,
            skill_id=skill_id,
            scenario=scenario,
            raw_result=raw_result,
            profile=profile,
            default_level=effective_level,
            history_candidates=history_candidates,
        )
        if ranking_meta and getattr(getattr(self.assistant, "learning", None), "record_model_assist_decision", None):
            self.assistant.learning.record_model_assist_decision(
                model_id="ui_target_ranker_heuristic_v1",
                decision_type="ranking",
                input_type="candidates",
                score=float(ranking_meta.get("score", 0.0)),
                recommendation=str(ranking_meta.get("scenario_id", scenario.get("scenario_id", ""))),
                used=True,
                heuristic_score=float(ranking_meta.get("heuristic_score", ranking_meta.get("score", 0.0))),
                session_id=result.session_id,
                context={"domain": domain},
            )

        self._apply_domain_specific_model_assists(result, raw_result)
        result = self._verify_result(domain, skill_id, scenario, result)
        result = self._recover_if_needed(domain, result, scenario, skill_label, profile, raw_result)
        self.learning_skill_engine.record_training_result(result)
        self.session_history.append(result)
        self._append_jsonl(self.history_path, result.to_dict())
        self._append_jsonl(self.dataset_path, self._dataset_entry(result, raw_result, scenario))
        return result

    def run_sessions(
        self,
        count: int,
        preferred_domain: Optional[str] = None,
        pause_seconds: Optional[float] = None,
    ) -> List[TrainingScenarioResult]:
        if pause_seconds is not None:
            self.pause_seconds = max(0.0, float(pause_seconds))
        results: List[TrainingScenarioResult] = []
        for _ in range(max(1, int(count))):
            if self.stop_checker and self.stop_checker():
                break
            results.append(self.run_one_cycle(preferred_domain=preferred_domain))
            if self.pause_seconds:
                time.sleep(self.pause_seconds)
        return results

    def summarize_result(self, result: TrainingScenarioResult) -> str:
        return (
            f"{result.domain} :: {result.skill_id} :: {result.scenario_id} :: "
            f"status={result.status} verified={'si' if result.verified else 'no'} "
            f"fallback={result.fallback_used or 'ninguno'} exp={result.level}/6"
        )

    def _build_domain_states(self) -> List[DomainTrainingState]:
        current = {item["domain"]: item for item in self.learning_skill_engine.training_domain_states()}
        states: List[DomainTrainingState] = []
        for default_state in self.scheduler.default_domain_states():
            payload = current.get(default_state.domain, {})
            states.append(
                DomainTrainingState(
                    domain=default_state.domain,
                    priority_rank=DOMAIN_PRIORITY_RANKS.get(default_state.domain, default_state.priority_rank),
                    success_rate=float(payload.get("success_rate", default_state.success_rate)),
                    fallback_rate=float(payload.get("fallback_rate", default_state.fallback_rate)),
                    days_stagnant=float(payload.get("days_stagnant", default_state.days_stagnant)),
                    freshness_score=float(payload.get("freshness_score", default_state.freshness_score)),
                    operational_score=float(payload.get("operational_score", default_state.operational_score)),
                    active_skill_ids=list(payload.get("active_skill_ids", default_state.active_skill_ids)),
                )
            )
        return states

    def _select_domain_state(
        self,
        states: Iterable[DomainTrainingState],
        preferred_domain: Optional[str],
    ) -> DomainTrainingState:
        state_list = list(states)
        if preferred_domain:
            normalized = str(preferred_domain)
            for state in state_list:
                if state.domain == normalized:
                    ready, reason = self._domain_selection_ready(state.domain)
                    if not ready:
                        raise RuntimeError(f"El dominio {state.domain} no esta disponible ahora: {reason}")
                    return state
        ranked = self._usable_ranked_domain_states(state_list)
        if not ranked:
            raise RuntimeError("No hay dominios disponibles para el loop infinito.")
        if self.domain_repeat_cooldown > 0:
            cooldown_set = set(self.recent_domains[-self.domain_repeat_cooldown :])
            for state in ranked:
                if state.domain not in cooldown_set:
                    return state
        return ranked[0]

    def _usable_ranked_domain_states(
        self,
        states: Iterable[DomainTrainingState],
    ) -> List[DomainTrainingState]:
        usable: List[DomainTrainingState] = []
        for state in self.scheduler.rank_domains(states):
            ready, reason = self._domain_selection_ready(state.domain)
            if ready:
                usable.append(state)
            else:
                self._report_blocked_domain(state.domain, reason)
        return usable

    def _domain_selection_ready(self, domain: str) -> Tuple[bool, str]:
        runtime_ready, runtime_reason = self._domain_runtime_ready(domain)
        if not runtime_ready:
            return runtime_ready, runtime_reason
        skill_ready, skill_reason = self._domain_has_selectable_skill(domain)
        if not skill_ready:
            return False, skill_reason
        scenario_ready, scenario_reason = self._domain_has_selectable_scenario(domain)
        if not scenario_ready:
            return False, scenario_reason
        return True, ""

    def _domain_runtime_ready(self, domain: str) -> Tuple[bool, str]:
        if domain == "research":
            return tesseract_runtime_available()
        return True, ""

    def _internet_available(self) -> bool:
        cache = getattr(self, "_internet_available_cache", None)
        if cache is not None:
            return cache

        for host, port in (("8.8.8.8", 53), ("1.1.1.1", 53)):
            try:
                with socket.create_connection((host, port), timeout=1):
                    self._internet_available_cache = True
                    return True
            except OSError:
                continue

        for url in ("https://www.google.com/generate_204", "http://example.com/"):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(request, timeout=2) as response:
                    status = getattr(response, "status", None)
                    if status is None:
                        status = response.getcode() if callable(getattr(response, "getcode", None)) else None
                    if status and 200 <= int(status) < 300:
                        self._internet_available_cache = True
                        return True
            except Exception:
                continue

        self._internet_available_cache = False
        return False

    def _scenario_requires_internet(self, domain: str, scenario: Dict[str, Any]) -> bool:
        scenario_id = str(scenario.get("scenario_id", ""))
        if domain in {"research", "browser", "application_workflow"}:
            return True
        if scenario_id == "keyboard_browser_address_focus":
            return True
        return False

    def _domain_has_selectable_scenario(self, domain: str) -> Tuple[bool, str]:
        internet_available = self._internet_available()
        candidates = []
        for scenario in self.DOMAIN_SCENARIOS.get(domain, []):
            if self._scenario_requires_internet(domain, scenario) and not internet_available:
                continue
            candidates.append(scenario)
        if not candidates:
            if internet_available:
                return False, "no hay escenarios disponibles"
            return False, "no hay escenarios disponibles sin internet"
        return True, ""

    def _domain_has_selectable_skill(self, domain: str) -> Tuple[bool, str]:
        engine = getattr(self, "learning_skill_engine", None)
        profiles = getattr(engine, "state", {}).get("profiles", {}) if engine else {}
        if not isinstance(profiles, dict) or not profiles:
            return True, ""

        if self._domain_skill_options(domain):
            return True, ""

        matching = [
            profile
            for profile in profiles.values()
            if self._profile_matches_domain_for_loop(profile, domain)
        ]
        if not matching:
            return True, ""

        selectable = [profile for profile in matching if self._profile_selectable_for_loop(profile)]
        if selectable:
            return True, ""

        if any(str(profile.get("state", "active") or "active") == "blocked" for profile in matching):
            return False, "todas las habilidades del dominio estan bloqueadas"
        return False, "no hay habilidades entrenables activas"

    def _domain_available_skill_labels(
        self,
        domain: str,
        forced_skill_id: Optional[str],
    ) -> List[str]:
        if forced_skill_id:
            return []
        labels: List[str] = []
        seen: Set[str] = set()
        for _, skill_label, _ in self._domain_skill_options(domain):
            normalized = normalize_text(skill_label)
            if normalized in seen:
                continue
            seen.add(normalized)
            labels.append(skill_label)
        return labels

    def _domain_skill_options(self, domain: str) -> List[Tuple[str, str, Dict[str, Any]]]:
        engine = getattr(self, "learning_skill_engine", None)
        profiles = getattr(engine, "state", {}).get("profiles", {}) if engine else {}
        if not isinstance(profiles, dict):
            profiles = {}

        options: List[Tuple[str, str, Dict[str, Any]]] = []
        seen_ids: Set[str] = set()

        matching_profiles = [
            profile
            for profile in profiles.values()
            if self._profile_matches_domain_for_loop(profile, domain)
            and self._profile_selectable_for_loop(profile)
        ]
        matching_profiles = sorted(
            matching_profiles,
            key=lambda item: (
                int(item.get("real_usage_ready", False)),
                int(item.get("exponential_level", 0) or 0),
                int(item.get("current_level", 1) or 1),
            ),
        )
        for profile in matching_profiles:
            skill_id = str(profile.get("skill_id") or "").strip()
            if not skill_id or skill_id in seen_ids:
                continue
            seen_ids.add(skill_id)
            options.append((skill_id, self._skill_label_from_profile(skill_id, profile), profile))

        for skill_label in self._domain_loop_skill_labels(domain):
            resolved = self._resolve_loop_skill(skill_label, profiles)
            if not resolved:
                continue
            skill_id, resolved_label, profile = resolved
            if skill_id in seen_ids:
                continue
            if not self._profile_matches_domain_for_loop(profile, domain):
                continue
            if not self._profile_selectable_for_loop(profile):
                continue
            seen_ids.add(skill_id)
            options.append((skill_id, resolved_label, profile))
        return options

    def _resolve_loop_skill(
        self,
        skill_label: str,
        profiles: Dict[str, Dict[str, Any]],
    ) -> Optional[Tuple[str, str, Dict[str, Any]]]:
        engine = getattr(self, "learning_skill_engine", None)
        resolver = getattr(engine, "_resolve_skill", None)
        if not callable(resolver):
            return None
        resolved = resolver(skill_label)
        if not isinstance(resolved, dict):
            return None
        skill_id = str(resolved.get("skill_id") or "").strip()
        if not skill_id:
            return None
        profile = dict(resolved)
        existing = profiles.get(skill_id, {})
        if isinstance(existing, dict):
            profile.update(existing)
        profile.setdefault("skill_id", skill_id)
        if not profile.get("canonical_entity"):
            profile["canonical_entity"] = resolved.get("canonical_entity", "")
        if "supported" not in profile:
            profile["supported"] = bool(resolved.get("supported", False))
        return skill_id, self._skill_label_from_profile(skill_id, profile), profile

    def _domain_loop_skill_labels(self, domain: str) -> List[str]:
        labels: List[str] = []
        seen: Set[str] = set()
        for scenario in self.DOMAIN_SCENARIOS.get(domain, []):
            skill_label = str(scenario.get("skill_label", "") or "").strip()
            if not skill_label:
                continue
            normalized = normalize_text(skill_label)
            if normalized in seen:
                continue
            seen.add(normalized)
            labels.append(skill_label)
        return labels

    def _profile_matches_domain_for_loop(self, profile: Dict[str, Any], domain: str) -> bool:
        engine = getattr(self, "learning_skill_engine", None)
        if engine and hasattr(engine, "_profile_matches_domain"):
            return bool(engine._profile_matches_domain(profile, domain))
        return False

    @staticmethod
    def _profile_selectable_for_loop(profile: Dict[str, Any]) -> bool:
        state = str(profile.get("state", "active") or "active")
        supported = bool(profile.get("supported", True))
        return supported and state not in {"blocked", "draft"}

    def _report_blocked_domain(self, domain: str, reason: str) -> None:
        notice_key = f"{domain}|{reason}"
        if notice_key in self._blocked_domain_notices:
            return
        self._blocked_domain_notices.add(notice_key)
        message = f"Loop infinito omite {domain}: {reason}"
        if self.logger:
            self.logger.warning(message)
        if self.progress_callback:
            self.progress_callback(message, "warning")

    def _remember_domain_selection(self, domain: str) -> None:
        self.recent_domains.append(domain)
        keep = max(4, self.domain_repeat_cooldown * 3)
        if len(self.recent_domains) > keep:
            self.recent_domains = self.recent_domains[-keep:]

    def _select_skill(
        self,
        domain: str,
        forced_skill_id: Optional[str],
        preferred_skill_label: str = "",
    ) -> Tuple[str, str, Dict[str, Any]]:
        profiles = self.learning_skill_engine.state.get("profiles", {})
        if forced_skill_id:
            profile = profiles.get(forced_skill_id, {})
            return forced_skill_id, self._skill_label_from_profile(forced_skill_id, profile), profile

        if preferred_skill_label:
            resolved = self._resolve_loop_skill(preferred_skill_label, profiles)
            if resolved:
                skill_id, skill_label, profile = resolved
                if self._profile_matches_domain_for_loop(profile, domain):
                    if not self._profile_selectable_for_loop(profile):
                        raise RuntimeError(f"La habilidad {skill_label} de {domain} no esta activa para entrenar.")
                    return skill_id, skill_label, profile

        matching_profiles = [
            profile
            for profile in profiles.values()
            if self.learning_skill_engine._profile_domain(profile) == domain
        ]
        candidates = [
            profile
            for profile in matching_profiles
            if self._profile_selectable_for_loop(profile)
        ]
        if candidates:
            profile = sorted(
                candidates,
                key=lambda item: (
                    int(item.get("real_usage_ready", False)),
                    int(item.get("exponential_level", 0) or 0),
                    int(item.get("current_level", 1) or 1),
                ),
            )[0]
            skill_id = str(profile.get("skill_id"))
            return skill_id, self._skill_label_from_profile(skill_id, profile), profile

        loop_options = self._domain_skill_options(domain)
        if loop_options:
            return loop_options[0]

        if matching_profiles:
            raise RuntimeError(f"El dominio {domain} no tiene habilidades activas entrenables.")

        fallback = {
            "keyboard": ("skill:teclado", "teclado"),
            "perception": ("skill:visualizacion", "visualizacion"),
            "vision/detection": ("skill:mouse", "mouse"),
            "selection/workflow": ("skill:mouse", "mouse"),
            "research": ("skill:investigar", "investigar"),
            "browser": ("app:brave", "brave"),
            "file_manager/explorer": ("app:explorer", "explorer"),
            "document_editor": ("app:notepad", "notepad"),
            "application_workflow": ("site:youtube", "youtube"),
            "game_foundation": ("jugar_terraria", "jugar terraria"),
        }
        fallback_entry = fallback.get(domain)
        if not fallback_entry:
            raise RuntimeError(f"El loop infinito no tiene fallback configurado para el dominio {domain}.")
        skill_id, skill_label = fallback_entry
        fallback_profile = profiles.get(skill_id, {})
        if fallback_profile and not self._profile_selectable_for_loop(fallback_profile):
            raise RuntimeError(f"La habilidad base de {domain} no esta activa para entrenar.")
        return skill_id, skill_label, fallback_profile

    @staticmethod
    def _skill_label_from_profile(skill_id: str, profile: Dict[str, Any]) -> str:
        canonical = str(profile.get("canonical_entity", "") or "")
        if canonical:
            if normalize_text(skill_id).startswith("jugar_"):
                return f"jugar {canonical}"
            return canonical
        if skill_id.startswith("skill:"):
            return skill_id.split(":", 1)[1]
        if skill_id.startswith("app:") or skill_id.startswith("site:"):
            return skill_id.split(":", 1)[1]
        if skill_id.startswith("jugar_"):
            return skill_id.replace("_", " ")
        return skill_id

    def _select_scenario(
        self,
        domain: str,
        current_exp_level: int,
        forced_scenario: Optional[Dict[str, Any]],
        allowed_skill_labels: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if forced_scenario:
            return self._resolve_forced_scenario(domain, forced_scenario)
        internet_available = self._internet_available()
        candidates = [dict(item) for item in self.DOMAIN_SCENARIOS.get(domain, [])]
        if not candidates:
            raise RuntimeError(f"No hay escenarios configurados para {domain}.")
        if not internet_available:
            candidates = [
                item
                for item in candidates
                if not self._scenario_requires_internet(domain, item)
            ]
            if not candidates:
                raise RuntimeError(f"No hay escenarios configurados para {domain} disponibles sin internet.")
        if allowed_skill_labels:
            allowed = {normalize_text(label) for label in allowed_skill_labels if str(label).strip()}
            filtered = [
                item
                for item in candidates
                if normalize_text(str(item.get("skill_label", "") or "")) in allowed
            ]
            if filtered:
                candidates = filtered
        ranked = self.ui_target_ranker.rank_candidates(
            candidates,
            context={"target_level": current_exp_level, "domain": domain},
        )
        selected = dict(ranked[0])
        selected["_ranking_meta"] = {
            "scenario_id": selected.get("scenario_id", ""),
            "score": float(selected.get("_score", 0.0) or 0.0),
            "heuristic_score": float(selected.get("_heuristic_score", selected.get("_score", 0.0)) or 0.0),
        }
        return selected

    def _execute_scenario(self, domain: str, scenario: Dict[str, Any], skill_label: str) -> str:
        runner_name = str(scenario.get("runner", ""))
        goal = str(scenario.get("training_goal") or scenario.get("objective") or "").strip()
        attempts = (
            self.mouse_attempts
            if "mouse" in skill_label or domain in {"perception"} or domain.startswith("vision") or domain.startswith("selection")
            else self.keyboard_attempts
        )
        if runner_name == "practice_skill":
            if bool(scenario.get("create_document")):
                return self.assistant.learn_skill(
                    skill=skill_label,
                    goal=goal or skill_label,
                    attempts=attempts,
                    minutes=1 if domain == "research" else None,
                    create_document=True,
                )
            return self.assistant.practice_skill(
                skill=skill_label,
                goal=goal or None,
                attempts=attempts,
                minutes=1 if domain == "research" else None,
            )
        if runner_name == "practice_mouse_movement":
            return self.assistant.practice_mouse_movement(attempts=attempts, skip_confirmation=True)
        if runner_name == "practice_mouse_click":
            return self.assistant.practice_mouse_click(attempts=attempts, skip_confirmation=True)
        if runner_name == "practice_mouse_double_click":
            return self.assistant.practice_mouse_double_click(attempts=attempts, skip_confirmation=True)
        if runner_name == "practice_mouse_right_click":
            return self.assistant.practice_mouse_right_click(attempts=attempts, skip_confirmation=True)
        if runner_name == "practice_mouse_detection":
            return self.assistant.practice_mouse_detection(attempts=attempts, skip_confirmation=True)
        if runner_name == "practice_mouse_selection":
            return self.assistant.practice_mouse_selection(attempts=attempts, skip_confirmation=True)
        if runner_name == "practice_mouse_workflow":
            return self.assistant.practice_mouse_workflow(attempts=attempts, skip_confirmation=True)
        if runner_name == "practice_desktop_mouse":
            return self.assistant.practice_desktop_mouse(attempts=attempts, skip_confirmation=True)
        raise RuntimeError(f"Runner no soportado en loop infinito: {runner_name}")

    def _build_structured_result(
        self,
        domain: str,
        skill_id: str,
        scenario: Dict[str, Any],
        raw_result: str,
        profile: Dict[str, Any],
        default_level: int,
        history_candidates: List[TrainingScenarioResult],
    ) -> TrainingScenarioResult:
        result = self._result_from_current_session(
            domain=domain,
            skill_id=skill_id,
            scenario=scenario,
            raw_result=raw_result,
            default_level=default_level,
            history_candidates=history_candidates,
        )
        if result is None and skill_id == "skill:mouse":
            result = self._mouse_result_from_strategy(
                domain=domain,
                scenario=scenario,
                raw_result=raw_result,
                default_level=default_level,
            )
        if result is None:
            result = self._synthetic_result_from_raw(
                domain=domain,
                skill_id=skill_id,
                scenario=scenario,
                raw_result=raw_result,
                default_level=default_level,
            )
        result.domain = domain
        result.skill_id = skill_id
        result.scenario_id = str(scenario.get("scenario_id", result.scenario_id))
        result.level = max(int(result.level or 0), int(default_level or 0))
        result.evidence = dict(result.evidence or {})
        result.evidence["base_scenario_id"] = str(
            scenario.get("base_scenario_id") or scenario.get("scenario_id", result.scenario_id)
        )
        if scenario.get("knowledge_assets"):
            result.evidence.setdefault("knowledge_assets", list(scenario.get("knowledge_assets", []))[:3])
        if not result.notes:
            result.notes = raw_result[:1000]
        return result

    def _mouse_result_from_strategy(
        self,
        domain: str,
        scenario: Dict[str, Any],
        raw_result: str,
        default_level: int,
    ) -> TrainingScenarioResult:
        metric_key = self._mouse_metric_key_for_scenario(str(scenario.get("scenario_id", "")))
        strategy_reader = getattr(self.learning_skill_engine, "_read_mouse_strategy", None)
        payload = strategy_reader() if callable(strategy_reader) else {}
        practice = payload.get("practice", {}) if isinstance(payload.get("practice", {}), dict) else {}
        metric = practice if metric_key == "drag" and practice.get("last_session_id") else practice.get(metric_key, {})
        metric = metric if isinstance(metric, dict) else {}
        successes = int(metric.get("successes", 0) or 0)
        failures = int(metric.get("failures", 0) or 0)
        total = max(1, successes + failures)
        success_rate = float(metric.get("success_rate", successes / total if total else 0.0) or 0.0)
        session_id = str(metric.get("session_id") or metric.get("last_session_id") or "")
        manifest_evidence = self._desktop_practice_manifest_evidence(session_id)
        return TrainingScenarioResult(
            skill_id="skill:mouse",
            domain=domain,
            scenario_id=str(scenario.get("scenario_id", metric_key)),
            session_id=session_id,
            timestamp=int(time.time()),
            level=max(0, default_level),
            status="success" if successes > 0 and failures == 0 else ("success_with_fallback" if successes > failures else "failure"),
            verified=bool(successes > 0),
            failure_stage="action" if failures else None,
            fallback_used=None,
            attempted_strategies=[metric_key],
            chosen_strategy=metric_key,
            retryable=failures > 0,
            metrics={"success_rate": success_rate, "attempts": int(metric.get("attempts", total) or total)},
            evidence={
                "practice_metric": metric_key,
                "raw_result": raw_result,
                "session_id": session_id,
                "selection_detection": {"reliable": bool(metric.get("reliable") or metric.get("real_drag_enabled"))},
                **manifest_evidence,
            },
            verified_outcome={"successes": successes, "failures": failures},
            notes=raw_result[:1000],
        )

    def _desktop_practice_manifest_evidence(self, session_id: str) -> Dict[str, Any]:
        clean_session_id = str(session_id or "").strip()
        if not clean_session_id or any(token in clean_session_id for token in (":", "\\", "/")):
            return {}
        manifest_path = Path(self.base_dir) / "data" / "desktop_organizer_sessions" / f"{clean_session_id}.json"
        if not manifest_path.exists():
            return {}
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return {"manifest_path": str(manifest_path)}
        moves = payload.get("moves", [])
        if not isinstance(moves, list):
            moves = []
        verified_moves = [item for item in moves if isinstance(item, dict) and bool(item.get("verified"))]
        selected = verified_moves[0] if verified_moves else (moves[0] if moves and isinstance(moves[0], dict) else {})
        destination_path = str(selected.get("destination") or "")
        source_path = str(selected.get("source") or "")
        evidence: Dict[str, Any] = {
            "manifest_path": str(manifest_path),
            "verified_moves": len(verified_moves),
            "total_moves": len(moves),
        }
        if destination_path:
            evidence["destination_path"] = destination_path
            evidence["destination"] = destination_path
        if source_path:
            evidence["source_path"] = source_path
        return evidence

    def _verify_result(
        self,
        domain: str,
        skill_id: str,
        scenario: Dict[str, Any],
        result: TrainingScenarioResult,
    ) -> TrainingScenarioResult:
        family = self._scenario_family(domain, scenario)
        verification_rules = dict(scenario.get("verification_rules", {}))
        verifier = self._family_verifier(family, skill_id)
        if verifier is None:
            if verification_rules:
                result.verified = False
                result.failure_stage = result.failure_stage or "verification_missing"
                result.verified_outcome.update(
                    {
                        "verification_missing": True,
                        "verification_family": family,
                        "verification_rules": verification_rules,
                    }
                )
            return result
        verification = verifier.verify(result)
        verified_flag = self._verification_passed(verification)
        result.verified = result.verified and verified_flag if result.verified else verified_flag
        result.verified_outcome.update(verification.get("verified_outcome", {}))
        if not result.verified and not result.failure_stage:
            result.failure_stage = "verification"
        return result

    def _recover_if_needed(
        self,
        domain: str,
        result: TrainingScenarioResult,
        scenario: Dict[str, Any],
        skill_label: str,
        profile: Dict[str, Any],
        raw_result: str,
    ) -> TrainingScenarioResult:
        if result.verified:
            return result
        if self.recovery_engine is None:
            return result
        recovery = self.recovery_engine.get_next_strategy(
            {
                "domain": domain,
                "training_scenario_id": result.scenario_id,
                "failure_session_id": result.session_id,
                "failure_stage": result.failure_stage or "verification",
                "failure_reason": result.error_log or raw_result[:500],
                "attempted_strategies": result.attempted_strategies,
            }
        )
        recovery.recovery_session_id = f"recovery_{int(time.time())}"
        retry_history_signatures = self._history_signatures(result.skill_id)
        retry_raw = self._execute_scenario(domain, scenario, skill_label)
        retry_candidates = self._fresh_history_results(result.skill_id, retry_history_signatures)
        retry_result = self._build_structured_result(
            domain=domain,
            skill_id=result.skill_id,
            scenario=scenario,
            raw_result=retry_raw,
            profile=profile,
            default_level=self._effective_scenario_level(scenario, result.level),
            history_candidates=retry_candidates,
        )
        self._apply_domain_specific_model_assists(retry_result, retry_raw)
        retry_result = self._verify_result(domain, result.skill_id, scenario, retry_result)
        retry_result.attempted_strategies = list(dict.fromkeys(list(result.attempted_strategies) + [recovery.chosen_next_strategy] + list(retry_result.attempted_strategies)))
        retry_result.fallback_used = recovery.chosen_next_strategy
        retry_result.status = "success_with_fallback" if retry_result.verified else retry_result.status
        recovery.recovery_succeeded = retry_result.verified
        recovery.recovery_verified = retry_result.verified
        recovery.verified_outcome = dict(retry_result.verified_outcome)
        self.recovery_engine.record_attempt(recovery)
        return retry_result if retry_result.verified else result

    def _result_from_current_session(
        self,
        domain: str,
        skill_id: str,
        scenario: Dict[str, Any],
        raw_result: str,
        default_level: int,
        history_candidates: List[TrainingScenarioResult],
    ) -> Optional[TrainingScenarioResult]:
        candidate = self._match_history_candidate(domain, scenario, history_candidates)
        if candidate is None:
            return None
        base_scenario_id = str(scenario.get("base_scenario_id") or scenario.get("scenario_id", candidate.scenario_id))
        evidence = dict(candidate.evidence or {})
        evidence.update(
            {
                "raw_result": raw_result[:1000],
                "base_scenario_id": base_scenario_id,
                "current_session_verified": bool(candidate.verified),
                "history_observed_scenario_id": candidate.scenario_id,
                "verification_source": "current_session_history",
            }
        )
        verified_outcome = dict(candidate.verified_outcome or {})
        verified_outcome.setdefault("current_session_observed", True)
        return TrainingScenarioResult(
            skill_id=skill_id,
            domain=domain,
            scenario_id=str(scenario.get("scenario_id", base_scenario_id)),
            session_id=str(candidate.session_id or f"loop_{int(time.time())}"),
            timestamp=int(time.time()),
            level=max(int(candidate.level or 0), int(default_level or 0)),
            status=str(candidate.status or "failure"),
            verified=bool(candidate.verified),
            failure_stage=candidate.failure_stage,
            fallback_used=candidate.fallback_used,
            attempted_strategies=list(candidate.attempted_strategies or [str(scenario.get("runner", ""))]),
            chosen_strategy=str(candidate.chosen_strategy or scenario.get("runner", "")),
            retryable=bool(candidate.retryable),
            metrics={
                **dict(candidate.metrics or {}),
                "raw_result_length": len(raw_result),
                "fresh_history_matches": len(history_candidates),
            },
            evidence=evidence,
            verified_outcome=verified_outcome,
            error_log=candidate.error_log,
            notes=raw_result[:1000],
        )

    def _synthetic_result_from_raw(
        self,
        domain: str,
        skill_id: str,
        scenario: Dict[str, Any],
        raw_result: str,
        default_level: int,
    ) -> TrainingScenarioResult:
        normalized = raw_result.lower()
        success = not any(token in normalized for token in ("error", "fallo", "blocked", "cancelad", "no se pudo"))
        return TrainingScenarioResult(
            skill_id=skill_id,
            domain=domain,
            scenario_id=str(scenario.get("scenario_id", "generic")),
            session_id=f"loop_{int(time.time())}",
            timestamp=int(time.time()),
            level=max(0, default_level),
            status="success" if success else "failure",
            verified=False,
            failure_stage=None if success else "action",
            retryable=True,
            metrics={"raw_result_length": len(raw_result), "fresh_history_matches": 0},
            evidence={
                "raw_result": raw_result[:1000],
                "base_scenario_id": str(scenario.get("base_scenario_id") or scenario.get("scenario_id", "")),
                "current_session_verified": False,
                "verification_source": "synthetic_result",
            },
            verified_outcome={"raw_success": success, "current_session_observed": False},
            notes=raw_result[:1000],
        )

    def _apply_domain_specific_model_assists(self, result: TrainingScenarioResult, raw_result: str) -> None:
        if result.domain != "research":
            return
        source_text = ""
        if isinstance(result.evidence, dict):
            source_text = str(result.evidence.get("merged_text") or result.evidence.get("raw_result") or raw_result)
        decision = self.page_usefulness_classifier.classify(source_text)
        result.metrics["page_usefulness_score"] = float(decision.get("score", 0.0))
        result.evidence["page_usefulness_label"] = str(decision.get("label", "unknown"))
        recorder = getattr(getattr(self.assistant, "learning", None), "record_model_assist_decision", None)
        if recorder:
            recorder(
                model_id="page_usefulness_classifier_heuristic_v1",
                decision_type="classification",
                input_type="text",
                score=float(decision.get("score", 0.0)),
                recommendation=str(decision.get("label", "unknown")),
                used=True,
                session_id=result.session_id,
                context={"domain": result.domain, "scenario_id": result.scenario_id},
            )

    def _resolve_forced_scenario(self, domain: str, forced_scenario: Dict[str, Any]) -> Dict[str, Any]:
        resolved = dict(forced_scenario)
        base_scenario_id = str(resolved.get("base_scenario_id") or resolved.get("scenario_id") or "")
        template = self._scenario_template_for(domain, base_scenario_id)
        if template:
            merged = dict(template)
            merged.update(resolved)
            merged.setdefault("base_scenario_id", base_scenario_id or merged.get("scenario_id", ""))
            return merged
        if not resolved.get("runner"):
            raise RuntimeError(f"Escenario forzado sin runner resolvible: {resolved}")
        resolved.setdefault("base_scenario_id", base_scenario_id)
        return resolved

    def _scenario_template_for(self, domain: str, scenario_id: str) -> Optional[Dict[str, Any]]:
        scenario_id = str(scenario_id or "").strip()
        if not scenario_id:
            return None
        candidates = self.DOMAIN_SCENARIOS.get(domain, [])
        for item in candidates:
            if str(item.get("scenario_id", "")) == scenario_id:
                return dict(item)
        for items in self.DOMAIN_SCENARIOS.values():
            for item in items:
                if str(item.get("scenario_id", "")) == scenario_id:
                    return dict(item)
        return None

    @staticmethod
    def _effective_scenario_level(scenario: Dict[str, Any], current_level: int) -> int:
        return max(
            int(current_level or 0),
            int(scenario.get("level", 0) or 0),
            int(scenario.get("target_level", 0) or 0),
        )

    def _history_signatures(self, skill_id: str) -> Set[Tuple[str, str, int, str, bool, int]]:
        history_reader = getattr(self.learning_skill_engine, "_profile_training_history", None)
        if not callable(history_reader):
            return set()
        return {self._result_signature(item) for item in history_reader(skill_id)}

    def _fresh_history_results(
        self,
        skill_id: str,
        previous_signatures: Set[Tuple[str, str, int, str, bool, int]],
    ) -> List[TrainingScenarioResult]:
        history_reader = getattr(self.learning_skill_engine, "_profile_training_history", None)
        if not callable(history_reader):
            return []
        return [
            item
            for item in history_reader(skill_id)
            if self._result_signature(item) not in previous_signatures
        ]

    @staticmethod
    def _result_signature(result: TrainingScenarioResult) -> Tuple[str, str, int, str, bool, int]:
        return (
            str(result.session_id or ""),
            str(result.scenario_id or ""),
            int(result.timestamp or 0),
            str(result.status or ""),
            bool(result.verified),
            int(result.level or 0),
        )

    def _match_history_candidate(
        self,
        domain: str,
        scenario: Dict[str, Any],
        history_candidates: List[TrainingScenarioResult],
    ) -> Optional[TrainingScenarioResult]:
        if not history_candidates:
            return None
        scenario_id = str(scenario.get("scenario_id", "") or "")
        base_scenario_id = str(scenario.get("base_scenario_id", "") or scenario_id)

        def score(item: TrainingScenarioResult) -> Tuple[int, int, int, int, int]:
            keys = self._scenario_keys(item)
            return (
                int(scenario_id in keys),
                int(base_scenario_id in keys),
                int(item.domain == domain),
                int(item.verified),
                int(item.timestamp or 0),
            )

        return max(history_candidates, key=score)

    @staticmethod
    def _scenario_keys(result: TrainingScenarioResult) -> Set[str]:
        keys = {str(result.scenario_id or "")}
        evidence = dict(result.evidence or {})
        base = str(evidence.get("base_scenario_id") or "")
        if base:
            keys.add(base)
        equivalents = evidence.get("equivalent_scenarios", [])
        if isinstance(equivalents, list):
            keys.update(str(item) for item in equivalents if str(item).strip())
        return {item for item in keys if item}

    @staticmethod
    def _scenario_family(domain: str, scenario: Dict[str, Any]) -> str:
        explicit = str(scenario.get("family", "") or "").strip()
        if explicit:
            return explicit
        mapping = {
            "keyboard": "keyboard",
            "perception": "perception",
            "vision/detection": "vision",
            "selection/workflow": "vision",
            "research": "research",
            "browser": "browser",
            "file_manager/explorer": "file_manager",
            "document_editor": "documents",
            "application_workflow": "application",
            "game_foundation": "game",
        }
        return mapping.get(domain, "application")

    def _family_verifier(self, family: str, skill_id: str) -> Optional[Any]:
        if skill_id == "skill:visualizacion" or family == "perception":
            return getattr(self.learning_skill_engine, "visual_verifier", None)
        if skill_id == "skill:mouse" or family == "vision":
            return getattr(self.learning_skill_engine, "desktop_verifier", None)
        if skill_id == "skill:investigar" or family == "research":
            return getattr(self.learning_skill_engine, "research_verifier", None)
        return getattr(self, "_session_verifiers", {}).get(family)

    @staticmethod
    def _verification_passed(verification: Dict[str, Any]) -> bool:
        return bool(
            verification.get("verified")
            or verification.get("file_exists")
            or verification.get("action_logged")
            or verification.get("single_source_verified")
            or verification.get("multi_query_verified")
            or verification.get("multiple_attempts_clean")
            or verification.get("adversarial_verified")
            or verification.get("current_session_verified")
            or verification.get("context_identity_verified")
            or verification.get("target_reacquire_verified")
            or verification.get("scene_transition_verified")
            or verification.get("workflow_precondition_verified")
            or verification.get("adversarial_recovery_verified")
        )

    @staticmethod
    def _dataset_entry(result: TrainingScenarioResult, raw_result: str, scenario: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "timestamp": int(time.time()),
            "skill_id": result.skill_id,
            "domain": result.domain,
            "scenario_id": result.scenario_id,
            "level": result.level,
            "status": result.status,
            "verified": result.verified,
            "failure_stage": result.failure_stage,
            "fallback_used": result.fallback_used,
            "metrics": result.metrics,
            "evidence": result.evidence,
            "verified_outcome": result.verified_outcome,
            "raw_result": raw_result[:1000],
            "scenario": dict(scenario),
        }

    @staticmethod
    def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    @staticmethod
    def _mouse_metric_key_for_scenario(scenario_id: str) -> str:
        normalized = str(scenario_id)
        if "detect" in normalized:
            return "detection"
        if "double" in normalized or "reopened" in normalized:
            return "double_click"
        if "right" in normalized:
            return "right_click"
        if "click" in normalized:
            return "click"
        if "selection" in normalized or "no_fallback" in normalized:
            return "selection"
        if "workflow" in normalized or "recovery" in normalized or "adversarial" in normalized:
            return "workflow"
        if "drag" in normalized:
            return "drag"
        return "movement"
