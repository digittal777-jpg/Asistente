from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol


class TrainingDomainRunner(Protocol):
    def run(
        self,
        engine: Any,
        *,
        profile: Dict[str, Any],
        level: int,
        mode: str,
        goal: str,
        requested_attempts: Optional[int],
        requested_minutes: Optional[int],
        create_document: bool,
        cycle_number: int,
    ) -> Dict[str, Any]:
        ...


@dataclass(frozen=True)
class MethodTrainingDomainRunner:
    method_name: str
    profile_argument: Optional[str] = None
    include_mode: bool = False
    include_create_document: bool = False

    def run(
        self,
        engine: Any,
        *,
        profile: Dict[str, Any],
        level: int,
        mode: str,
        goal: str,
        requested_attempts: Optional[int],
        requested_minutes: Optional[int],
        create_document: bool,
        cycle_number: int,
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "level": level,
            "goal": goal,
            "requested_attempts": requested_attempts,
            "requested_minutes": requested_minutes,
            "cycle_number": cycle_number,
        }
        if self.include_mode:
            kwargs["mode"] = mode
        if self.include_create_document:
            kwargs["create_document"] = create_document
        if self.profile_argument:
            kwargs[self.profile_argument] = str(profile.get("canonical_entity", "") or "")
        return getattr(engine, self.method_name)(**kwargs)


DEFAULT_TRAINING_DOMAIN_RUNNERS: Dict[str, TrainingDomainRunner] = {
    "keyboard": MethodTrainingDomainRunner("_run_keyboard_cycle", include_mode=True),
    "research_workflow": MethodTrainingDomainRunner(
        "_run_research_cycle",
        include_mode=True,
        include_create_document=True,
    ),
    "visual_perception": MethodTrainingDomainRunner(
        "_run_visual_perception_cycle",
        include_mode=True,
    ),
    "browser_app": MethodTrainingDomainRunner("_run_browser_app_cycle", profile_argument="browser_name"),
    "document_editor": MethodTrainingDomainRunner(
        "_run_document_editor_cycle",
        profile_argument="application",
    ),
    "site_workflow": MethodTrainingDomainRunner(
        "_run_site_workflow_cycle",
        profile_argument="site_name",
        include_mode=True,
    ),
    "file_manager": MethodTrainingDomainRunner(
        "_run_file_manager_cycle",
        profile_argument="application",
    ),
    "application_workflow": MethodTrainingDomainRunner(
        "_run_application_workflow_cycle",
        profile_argument="application",
    ),
    "mouse_control": MethodTrainingDomainRunner("_run_mouse_control_cycle", include_mode=True),
    "window_management": MethodTrainingDomainRunner("_run_window_management_cycle", include_mode=True),
    "game_foundation": MethodTrainingDomainRunner(
        "_run_game_foundation_cycle",
        profile_argument="game_name",
        include_mode=True,
    ),
}


def create_default_training_domain_runners() -> Dict[str, TrainingDomainRunner]:
    return dict(DEFAULT_TRAINING_DOMAIN_RUNNERS)
