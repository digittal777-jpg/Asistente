from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from core.command_parser import CommandAction
from core.data_paths import DataPaths
from core.logging_utils import ensure_directory
from core.skills import normalize_text

try:
    from rapidfuzz import fuzz, process

    RAPIDFUZZ_AVAILABLE = True
except ImportError:  # pragma: no cover
    from difflib import SequenceMatcher

    RAPIDFUZZ_AVAILABLE = False


class IntelligentLearningEngine:
    """Aprendizaje adaptativo general para comandos, acciones y preferencias."""

    SAFE_REPLAY_ACTIONS = {
        "ensure_browser",
        "ensure_site",
        "smart_site_search",
        "smart_spotify_play",
        "open_application",
        "open_folder",
        "open_project",
        "open_url",
        "write_active_context",
        "write_text_to_window",
        "browser_tab",
        "minimize_all_windows",
        "maximize_current_window",
        "set_volume",
        "set_volume_percent",
        "media_control",
        "list_desktop_icons",
        "click_desktop_icon",
        "skill_status",
    }

    UNSAFE_REPLAY_ACTIONS = {
        "close_current_window",
        "close_window",
        "run_shell",
        "organize_desktop",
        "practice_desktop_mouse",
        "practice_mouse_movement",
        "practice_mouse_click",
        "practice_mouse_double_click",
        "practice_mouse_right_click",
        "practice_mouse_detection",
        "practice_mouse_selection",
        "practice_mouse_workflow",
        "desktop_undo_last",
        "drag_mouse",
        "click",
        "move_mouse",
        "hotkey",
        "press_keys",
        "write_text",
        "learn_skill",
        "practice_skill",
        "evaluate_skill",
        "use_skill",
    }

    def __init__(self, base_dir: Path, memory: Any, config: Any, logger: Optional[Any] = None) -> None:
        self.base_dir = Path(base_dir)
        self.paths = DataPaths.from_base_dir(self.base_dir)
        self.memory = memory
        self.config = config
        self.logger = logger
        self.path = self.paths.intelligent_learning_path
        ensure_directory(self.path.parent)
        self.state = self._load_state()

    def suggest_command_actions(self, command: str) -> Optional[Tuple[List[CommandAction], str]]:
        normalized = normalize_text(command)
        command_memory = self.state.get("commands", {})
        if not command_memory:
            return None

        if normalized in command_memory:
            payload = command_memory[normalized]
            return self._actions_from_payload(payload), "Comando resuelto por aprendizaje inteligente exacto."

        best_key, score = self._best_match(normalized, command_memory.keys(), score_cutoff=90.0)
        if not best_key:
            return None
        payload = command_memory[best_key]
        if int(payload.get("successes", 0)) < 1:
            return None
        note = f"Comando resuelto por aprendizaje inteligente con similitud {score:.1f}."
        return self._actions_from_payload(payload), note

    def adapt_action(self, action: str, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        adapted = dict(params)
        preferences = self.state.setdefault("preferences", {})

        if action in {"smart_site_search", "ensure_site", "ensure_browser", "open_browser"}:
            if not adapted.get("browser"):
                destination = normalize_text(str(adapted.get("destination") or adapted.get("site") or "default"))
                browser = (
                    preferences.get("preferred_browser_by_destination", {}).get(destination)
                    or preferences.get("preferred_browser")
                    or self.memory.get_preference("preferred_browser", None)
                )
                if browser:
                    adapted["browser"] = browser

        if action == "create_document" and not adapted.get("application"):
            document_app = preferences.get("preferred_document_app") or self.memory.get_preference(
                "preferred_document_app",
                None,
            )
            if document_app:
                adapted["application"] = document_app

        if action == "smart_site_search":
            destination = normalize_text(str(adapted.get("destination", "")))
            preferred_target = preferences.get("preferred_search_target_by_destination", {}).get(destination)
            if preferred_target:
                adapted["preferred_target"] = preferred_target

        if adapted != params:
            self.record_learning_event(
                kind="action_adapted",
                subject=action,
                status="adapted",
                detail={"before": params, "after": adapted, "context": context or {}},
            )
        return adapted

    def record_action_result(
        self,
        action: str,
        params: Dict[str, Any],
        result: str,
        success: bool,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        action_stats = self.state.setdefault("actions", {}).setdefault(
            action,
            {"successes": 0, "failures": 0, "last_result": "", "last_params": {}, "last_error": ""},
        )
        action_stats["successes" if success else "failures"] = int(
            action_stats.get("successes" if success else "failures", 0)
        ) + 1
        action_stats["last_result"] = "success" if success else "failure"
        action_stats["last_params"] = params
        action_stats["last_error"] = "" if success else str(result)[:500]
        action_stats["updated_at"] = datetime.now().isoformat(timespec="seconds")

        self._learn_preferences_from_action(action, params, success)
        self.record_learning_event(
            kind="action_result",
            subject=action,
            status="success" if success else "failure",
            detail={"params": params, "result": str(result)[:1000], "context": context or {}},
            save=False,
        )
        self._save()

    def record_command_result(
        self,
        command: str,
        actions_taken: Iterable[Dict[str, Any]],
        result: str,
        success: bool,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        actions = list(actions_taken)
        normalized = normalize_text(command)
        commands = self.state.setdefault("commands", {})
        command_entry = commands.setdefault(
            normalized,
            {
                "command": command,
                "successes": 0,
                "failures": 0,
                "actions": [],
                "last_result": "",
                "safe_replay": False,
            },
        )
        command_entry["successes" if success else "failures"] = int(
            command_entry.get("successes" if success else "failures", 0)
        ) + 1
        command_entry["last_result"] = "success" if success else "failure"
        command_entry["updated_at"] = datetime.now().isoformat(timespec="seconds")

        safe_actions = self._safe_replay_actions(actions)
        if success and safe_actions:
            command_entry["actions"] = safe_actions
            command_entry["safe_replay"] = True
        elif not command_entry.get("actions"):
            command_entry["actions"] = []
            command_entry["safe_replay"] = False

        self.record_learning_event(
            kind="command_result",
            subject=normalized,
            status="success" if success else "failure",
            detail={
                "command": command,
                "actions": actions,
                "result": str(result)[:1000],
                "context": context or {},
                "safe_replay": bool(command_entry.get("safe_replay")),
            },
            save=False,
        )
        self._save()

    def record_strategy_result(
        self,
        domain: str,
        strategy: str,
        success: bool,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        strategies = self.state.setdefault("strategies", {}).setdefault(domain, {})
        entry = strategies.setdefault(strategy, {"successes": 0, "failures": 0, "last_result": ""})
        entry["successes" if success else "failures"] = int(entry.get("successes" if success else "failures", 0)) + 1
        entry["last_result"] = "success" if success else "failure"
        entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.record_learning_event(
            kind="strategy_result",
            subject=f"{domain}:{strategy}",
            status="success" if success else "failure",
            detail=detail or {},
            save=False,
        )
        self._save()

    def preferred_strategy(self, domain: str, candidates: Sequence[str]) -> Optional[str]:
        if not candidates:
            return None
        strategies = self.state.get("strategies", {}).get(domain, {})

        def score(name: str) -> float:
            entry = strategies.get(name, {})
            return float(entry.get("successes", 0)) * 3.0 - float(entry.get("failures", 0)) * 1.2

        return max(candidates, key=score)

    def preferred_recovery_strategy(
        self,
        domain: str,
        candidates: Sequence[str],
        failure_stage: str,
    ) -> Optional[str]:
        if not candidates:
            return None
        normalized_domain = normalize_text(domain) or "generic"
        normalized_stage = normalize_text(failure_stage) or "action"
        recoveries = (
            self.state.get("recoveries", {})
            .get(normalized_domain, {})
            .get(normalized_stage, {})
        )

        def score(name: str) -> float:
            entry = recoveries.get(name, {})
            verified = float(entry.get("verified_recoveries", 0))
            failed = float(entry.get("failed_recoveries", 0))
            chosen = float(entry.get("times_chosen", 0))
            return verified * 3.5 - failed * 1.5 + min(1.0, chosen * 0.05)

        return max(candidates, key=score)

    def record_recovery_attempt(
        self,
        domain: str,
        failure_stage: str,
        failure_reason: str,
        attempted_strategies: Sequence[str],
        chosen_next_strategy: str,
        verified_outcome: bool,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        normalized_domain = normalize_text(domain) or "generic"
        normalized_stage = normalize_text(failure_stage) or "action"
        recoveries = self.state.setdefault("recoveries", {}).setdefault(normalized_domain, {})
        stage_bucket = recoveries.setdefault(normalized_stage, {})
        entry = stage_bucket.setdefault(
            chosen_next_strategy,
            {
                "times_chosen": 0,
                "verified_recoveries": 0,
                "failed_recoveries": 0,
                "last_failure_reason": "",
            },
        )
        entry["times_chosen"] = int(entry.get("times_chosen", 0)) + 1
        key = "verified_recoveries" if verified_outcome else "failed_recoveries"
        entry[key] = int(entry.get(key, 0)) + 1
        entry["last_failure_reason"] = failure_reason[:500]
        entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.record_learning_event(
            kind="recovery_attempt",
            subject=f"{normalized_domain}:{normalized_stage}:{chosen_next_strategy}",
            status="verified" if verified_outcome else "failed",
            detail={
                "failure_reason": failure_reason,
                "attempted_strategies": list(attempted_strategies),
                "context": context or {},
            },
            save=False,
        )
        self._save()

    def record_model_assist_decision(
        self,
        model_id: str,
        decision_type: str,
        input_type: str,
        score: float,
        recommendation: str,
        used: bool,
        fallback_reason: Optional[str] = None,
        heuristic_score: Optional[float] = None,
        session_id: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        decisions = self.state.setdefault("model_assists", [])
        decisions.append(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "model_id": model_id,
                "decision_type": decision_type,
                "input_type": input_type,
                "score": float(score),
                "recommendation": recommendation,
                "used": bool(used),
                "fallback_reason": fallback_reason,
                "heuristic_score": heuristic_score,
                "session_id": session_id,
                "context": context or {},
            }
        )
        self.state["model_assists"] = decisions[-300:]
        self.record_learning_event(
            kind="model_assist",
            subject=f"{model_id}:{decision_type}",
            status="used" if used else "ignored",
            detail={
                "score": float(score),
                "recommendation": recommendation,
                "fallback_reason": fallback_reason,
                "heuristic_score": heuristic_score,
                "session_id": session_id,
            },
            save=False,
        )
        self._save()

    def summarize(self) -> str:
        actions = self.state.get("actions", {})
        commands = self.state.get("commands", {})
        strategies = self.state.get("strategies", {})
        events = self.state.get("events", [])
        learned_commands = sum(1 for item in commands.values() if item.get("safe_replay"))
        lines = [
            "Aprendizaje inteligente:",
            f"- Comandos recordados: {len(commands)} ({learned_commands} reutilizables)",
            f"- Acciones observadas: {len(actions)}",
            f"- Dominios con estrategias: {len(strategies)}",
        ]
        if events:
            lines.append("Eventos recientes:")
            for event in events[-5:]:
                lines.append(
                    f"- [{event.get('created_at')}] {event.get('kind')} "
                    f"{event.get('subject')} :: {event.get('status')}"
                )
        lines.append(f"Archivo: {self.path}")
        return "\n".join(lines)

    def record_learning_event(
        self,
        kind: str,
        subject: str,
        status: str,
        detail: Dict[str, Any],
        save: bool = True,
    ) -> None:
        events = self.state.setdefault("events", [])
        event = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "kind": kind,
            "subject": subject,
            "status": status,
            "detail": detail,
        }
        events.append(event)
        self.state["events"] = events[-200:]
        if hasattr(self.memory, "record_step_log"):
            try:
                self.memory.record_step_log(
                    task_intent="intelligent_learning",
                    step_name=f"{kind}:{subject}",
                    status=status,
                    detail=json.dumps(detail, ensure_ascii=False)[:3000],
                )
            except Exception:
                pass
        if save:
            self._save()

    def _learn_preferences_from_action(self, action: str, params: Dict[str, Any], success: bool) -> None:
        if not success:
            return
        preferences = self.state.setdefault("preferences", {})
        browser = params.get("browser")
        if browser:
            preferences["preferred_browser"] = browser
            destination = normalize_text(str(params.get("destination") or params.get("site") or "default"))
            preferences.setdefault("preferred_browser_by_destination", {})[destination] = browser
        if action == "create_document" and params.get("application"):
            preferences["preferred_document_app"] = params.get("application")
        if action == "smart_site_search" and params.get("preferred_target"):
            destination = normalize_text(str(params.get("destination", "")))
            preferences.setdefault("preferred_search_target_by_destination", {})[destination] = params["preferred_target"]

    def _safe_replay_actions(self, actions: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        serialized: List[Dict[str, Any]] = []
        seen = set()
        for raw in actions:
            action = str(raw.get("action", ""))
            if action in self.UNSAFE_REPLAY_ACTIONS or action not in self.SAFE_REPLAY_ACTIONS:
                return []
            params = raw.get("params", {})
            if not isinstance(params, dict):
                return []
            signature = json.dumps({"action": action, "params": params}, sort_keys=True, ensure_ascii=False)
            if signature in seen:
                continue
            seen.add(signature)
            serialized.append(
                {
                    "action": action,
                    "params": dict(params),
                    "summary": raw.get("summary", action),
                    "requires_confirmation": False,
                    "intent": raw.get("intent", "learned"),
                }
            )
        return serialized if serialized else []

    @staticmethod
    def _actions_from_payload(payload: Dict[str, Any]) -> List[CommandAction]:
        actions = payload.get("actions", [])
        return [CommandAction(**item) for item in actions]

    def _load_state(self) -> Dict[str, Any]:
        if self.path.exists():
            try:
                with self.path.open("r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                return self._with_defaults(loaded)
            except Exception:
                if self.logger:
                    self.logger.exception("No se pudo cargar intelligent_learning.json")
        return self._with_defaults({})

    @staticmethod
    def _with_defaults(loaded: Dict[str, Any]) -> Dict[str, Any]:
        state = {
            "version": 1,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "commands": {},
            "actions": {},
            "strategies": {},
            "recoveries": {},
            "model_assists": [],
            "preferences": {},
            "events": [],
        }
        for key, value in loaded.items():
            if key in state:
                state[key] = value
        return state

    def _save(self) -> None:
        self.state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.path.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _best_match(query: str, choices: Iterable[str], score_cutoff: float) -> Tuple[Optional[str], float]:
        choice_list = list(choices)
        if not choice_list:
            return None, 0.0
        if RAPIDFUZZ_AVAILABLE:
            result = process.extractOne(query, choice_list, scorer=fuzz.WRatio, score_cutoff=score_cutoff)
            if result:
                return str(result[0]), float(result[1])
            return None, 0.0

        best_choice: Optional[str] = None
        best_score = 0.0
        for choice in choice_list:
            score = SequenceMatcher(None, query, choice).ratio() * 100
            if score > best_score:
                best_choice = str(choice)
                best_score = float(score)
        if best_score >= score_cutoff:
            return best_choice, best_score
        return None, 0.0
