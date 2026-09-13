from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Tuple

from core.logging_utils import ensure_directory


@dataclass(frozen=True)
class DataPaths:
    base_dir: Path
    data_dir: Path
    archive_dir: Path
    runtime_dir: Path
    learning_profiles_path: Path
    learning_sessions_dir: Path
    training_results_path: Path
    organizer_sessions_dir: Path
    desktop_mouse_strategy_path: Path
    infinite_training_history_path: Path
    legacy_infinite_training_history_path: Path
    runtime_training_dataset_path: Path
    legacy_runtime_training_dataset_path: Path
    input_training_stop_path: Path
    legacy_input_training_stop_path: Path
    action_history_path: Path
    intelligent_learning_path: Path
    recovery_attempts_path: Path
    command_feedback_path: Path
    raphel_memory_db_path: Path
    dictionary_path: Path
    ui_profiles_dir: Path
    default_ui_profile_dir: Path
    default_ui_profile_manifest_path: Path
    runtime_smoke_dir: Path

    @classmethod
    def from_base_dir(cls, base_dir: Path) -> "DataPaths":
        root = Path(base_dir)
        data_dir = root / "data"
        runtime_dir = data_dir / "runtime"
        ui_profiles_dir = data_dir / "ui_profiles"
        default_ui_profile_dir = ui_profiles_dir / "default"
        return cls(
            base_dir=root,
            data_dir=data_dir,
            archive_dir=data_dir / "archive",
            runtime_dir=runtime_dir,
            learning_profiles_path=data_dir / "learning_skill_profiles.json",
            learning_sessions_dir=data_dir / "learning_skill_sessions",
            training_results_path=data_dir / "training_scenario_results.jsonl",
            organizer_sessions_dir=data_dir / "desktop_organizer_sessions",
            desktop_mouse_strategy_path=data_dir / "desktop_mouse_strategy.json",
            infinite_training_history_path=runtime_dir / "infinite_training_history.jsonl",
            legacy_infinite_training_history_path=data_dir / "infinite_training_history.jsonl",
            runtime_training_dataset_path=runtime_dir / "runtime_training_dataset.jsonl",
            legacy_runtime_training_dataset_path=data_dir / "runtime_training_dataset.jsonl",
            input_training_stop_path=runtime_dir / "input_training_loop.stop",
            legacy_input_training_stop_path=data_dir / "input_training_loop.stop",
            action_history_path=data_dir / "action_history.jsonl",
            intelligent_learning_path=data_dir / "intelligent_learning.json",
            recovery_attempts_path=data_dir / "recovery_attempts.jsonl",
            command_feedback_path=data_dir / "command_feedback.json",
            raphel_memory_db_path=data_dir / "raphel_memory.db",
            dictionary_path=data_dir / "dictionary-es.json",
            ui_profiles_dir=ui_profiles_dir,
            default_ui_profile_dir=default_ui_profile_dir,
            default_ui_profile_manifest_path=default_ui_profile_dir / "manifest.json",
            runtime_smoke_dir=data_dir / "runtime_smoke",
        )

    def ensure_base_structure(self) -> None:
        for path in (
            self.data_dir,
            self.archive_dir,
            self.runtime_dir,
            self.learning_sessions_dir,
            self.organizer_sessions_dir,
            self.ui_profiles_dir,
            self.default_ui_profile_dir,
        ):
            ensure_directory(path)
        for parent in (
            self.learning_profiles_path.parent,
            self.training_results_path.parent,
            self.desktop_mouse_strategy_path.parent,
            self.action_history_path.parent,
            self.intelligent_learning_path.parent,
            self.recovery_attempts_path.parent,
            self.command_feedback_path.parent,
            self.raphel_memory_db_path.parent,
            self.dictionary_path.parent,
            self.infinite_training_history_path.parent,
            self.runtime_training_dataset_path.parent,
            self.input_training_stop_path.parent,
        ):
            ensure_directory(parent)

    def runtime_file_pairs(self) -> Dict[str, Tuple[Path, Path]]:
        return {
            "infinite_training_history": (
                self.infinite_training_history_path,
                self.legacy_infinite_training_history_path,
            ),
            "runtime_training_dataset": (
                self.runtime_training_dataset_path,
                self.legacy_runtime_training_dataset_path,
            ),
            "input_training_stop": (
                self.input_training_stop_path,
                self.legacy_input_training_stop_path,
            ),
        }

    def resolve_runtime_path(self, name: str) -> Path:
        canonical, legacy = self.runtime_file_pairs()[name]
        if canonical.exists() or not legacy.exists():
            return canonical
        return legacy

    def known_persistent_files(self) -> Iterable[Path]:
        yield self.learning_profiles_path
        yield self.training_results_path
        yield self.desktop_mouse_strategy_path
        yield self.action_history_path
        yield self.intelligent_learning_path
        yield self.recovery_attempts_path
        yield self.raphel_memory_db_path
        yield self.dictionary_path
        yield self.legacy_infinite_training_history_path
        yield self.legacy_runtime_training_dataset_path
        yield self.legacy_input_training_stop_path
        yield self.infinite_training_history_path
        yield self.runtime_training_dataset_path
        yield self.input_training_stop_path
