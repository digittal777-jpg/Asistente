from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from core.data_paths import DataPaths
from core.logging_utils import ensure_directory


JSON_SUFFIXES = {".json", ".jsonl", ".db", ".stop"}


@dataclass
class CleanupDecision:
    action: str
    source_path: str
    relative_path: str
    reason: str
    target_path: str = ""


@dataclass
class CleanupPlan:
    created_at: str
    snapshot_targets: List[str] = field(default_factory=list)
    decisions: List[CleanupDecision] = field(default_factory=list)


class CleanupPlanner:
    def __init__(self, paths: DataPaths, logger: Any = None) -> None:
        self.paths = paths
        self.logger = logger

    def build_plan(self) -> CleanupPlan:
        created_at = datetime.now().isoformat(timespec="seconds")
        latest_manifest_targets = self._latest_manifest_targets()
        referenced_learning_files = self._referenced_learning_session_files()
        decisions: List[CleanupDecision] = []
        snapshot_targets: Set[str] = set()
        for path in sorted(self.paths.data_dir.rglob("*")):
            if not path.is_file():
                continue
            if self.paths.archive_dir in path.parents:
                continue
            decision = self._classify_path(
                path,
                latest_manifest_targets=latest_manifest_targets,
                referenced_learning_files=referenced_learning_files,
            )
            decisions.append(decision)
            if decision.action in {"archive", "quarantine", "regenerate"} or (
                path.suffix.lower() in JSON_SUFFIXES and path.parent == self.paths.data_dir
            ):
                snapshot_targets.add(str(path))
        return CleanupPlan(
            created_at=created_at,
            snapshot_targets=sorted(snapshot_targets),
            decisions=decisions,
        )

    def _classify_path(
        self,
        path: Path,
        *,
        latest_manifest_targets: Set[Path],
        referenced_learning_files: Set[Path],
    ) -> CleanupDecision:
        rel = path.relative_to(self.paths.data_dir)
        rel_text = rel.as_posix()

        for _, (canonical, legacy) in self.paths.runtime_file_pairs().items():
            if path == legacy and canonical != legacy:
                return CleanupDecision(
                    action="regenerate",
                    source_path=str(path),
                    relative_path=rel_text,
                    target_path=str(canonical),
                    reason="Migrar artefacto regenerable al directorio runtime canónico.",
                )
            if path == canonical:
                return CleanupDecision(
                    action="keep",
                    source_path=str(path),
                    relative_path=rel_text,
                    reason="Ruta runtime canónica activa.",
                )

        keep_top_level = {
            self.paths.learning_profiles_path,
            self.paths.training_results_path,
            self.paths.desktop_mouse_strategy_path,
            self.paths.action_history_path,
            self.paths.intelligent_learning_path,
            self.paths.recovery_attempts_path,
            self.paths.command_feedback_path,
            self.paths.raphel_memory_db_path,
            self.paths.dictionary_path,
        }
        if path in keep_top_level:
            return CleanupDecision("keep", str(path), rel_text, "Fuente de verdad persistente del sistema.")

        if path == self.paths.default_ui_profile_manifest_path or self.paths.ui_profiles_dir in path.parents:
            return CleanupDecision("keep", str(path), rel_text, "Perfil de UI/calibración activo.")

        if path.name.startswith("learning_skill_profiles.before_manual_cleanup_"):
            return CleanupDecision("archive", str(path), rel_text, "Backup manual legado fuera del set activo.")

        if self.paths.runtime_smoke_dir in path.parents:
            return CleanupDecision("archive", str(path), rel_text, "Artefacto de runtime smoke fuera del set activo.")

        if self.paths.learning_sessions_dir in path.parents:
            if "_keyboard_runtime" in rel.parts:
                return CleanupDecision("archive", str(path), rel_text, "Artefacto temporal de runtime de teclado.")
            if path.suffix.lower() == ".json":
                try:
                    json.loads(path.read_text(encoding="utf-8-sig"))
                except Exception:
                    return CleanupDecision("quarantine", str(path), rel_text, "Manifiesto de aprendizaje corrupto.")
                return CleanupDecision("keep", str(path), rel_text, "Manifiesto de aprendizaje activo.")
            if path in referenced_learning_files:
                return CleanupDecision("keep", str(path), rel_text, "Archivo de sesión referenciado por un manifiesto.")
            return CleanupDecision("archive", str(path), rel_text, "Artefacto huérfano de learning session.")

        if self.paths.organizer_sessions_dir in path.parents:
            if path.name.startswith("latest"):
                return CleanupDecision("keep", str(path), rel_text, "Puntero activo del organizer.")
            if path.name.startswith(("workflow_practice_", "session_", "undo_")):
                return CleanupDecision("keep", str(path), rel_text, "Manifiesto de organizer usado por rebuild/undo.")
            if path in latest_manifest_targets:
                return CleanupDecision("keep", str(path), rel_text, "Manifiesto apuntado por latest*.json.")
            if path.suffix.lower() == ".json":
                try:
                    json.loads(path.read_text(encoding="utf-8-sig"))
                except Exception:
                    return CleanupDecision("quarantine", str(path), rel_text, "Manifiesto de organizer corrupto.")
            return CleanupDecision("archive", str(path), rel_text, "Historial de organizer fuera del set activo.")

        if path.parent == self.paths.data_dir:
            return CleanupDecision("archive", str(path), rel_text, "Artefacto raíz fuera del set activo.")

        return CleanupDecision("keep", str(path), rel_text, "Archivo conservado por política conservadora.")

    def _latest_manifest_targets(self) -> Set[Path]:
        targets: Set[Path] = set()
        if not self.paths.organizer_sessions_dir.exists():
            return targets
        for latest_path in self.paths.organizer_sessions_dir.glob("latest*.json"):
            try:
                payload = json.loads(latest_path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            manifest_path = Path(str(payload.get("manifest_path", "") or ""))
            if manifest_path.exists():
                targets.add(manifest_path.resolve())
        return targets

    def _referenced_learning_session_files(self) -> Set[Path]:
        referenced: Set[Path] = set()
        if not self.paths.learning_sessions_dir.exists():
            return referenced
        for manifest_path in self.paths.learning_sessions_dir.glob("*.json"):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            referenced.add(manifest_path.resolve())
            for found_path in self._extract_data_paths(payload):
                if self.paths.learning_sessions_dir in found_path.parents or found_path == self.paths.learning_sessions_dir:
                    referenced.add(found_path.resolve())
        return referenced

    def _extract_data_paths(self, payload: Any) -> Set[Path]:
        discovered: Set[Path] = set()

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                for item in value.values():
                    visit(item)
                return
            if isinstance(value, list):
                for item in value:
                    visit(item)
                return
            if not isinstance(value, str):
                return
            text = value.strip()
            if not text:
                return
            candidate = Path(text)
            try:
                resolved = candidate.resolve(strict=False)
            except Exception:
                return
            try:
                resolved.relative_to(self.paths.data_dir.resolve())
            except Exception:
                return
            if resolved.exists():
                discovered.add(resolved)

        visit(payload)
        return discovered


class CleanupExecutor:
    def __init__(self, paths: DataPaths, logger: Any = None) -> None:
        self.paths = paths
        self.logger = logger

    def execute(self, plan: CleanupPlan) -> Dict[str, Any]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_root = self.paths.archive_dir / timestamp
        snapshot_dir = archive_root / "snapshot"
        ensure_directory(snapshot_dir)
        self._create_snapshot(plan.snapshot_targets, snapshot_dir)

        report: Dict[str, Any] = {
            "created_at": plan.created_at,
            "executed_at": datetime.now().isoformat(timespec="seconds"),
            "snapshot_dir": str(snapshot_dir),
            "snapshot_targets": list(plan.snapshot_targets),
            "kept": [],
            "archived": [],
            "quarantined": [],
            "regenerated": [],
        }
        for decision in plan.decisions:
            source = Path(decision.source_path)
            if decision.action == "keep":
                report["kept"].append(asdict(decision))
                continue
            if decision.action == "archive":
                target = archive_root / "archived" / decision.relative_path
                self._move_with_parents(source, target)
                decision.target_path = str(target)
                report["archived"].append(asdict(decision))
                continue
            if decision.action == "quarantine":
                target = archive_root / "quarantined" / decision.relative_path
                self._move_with_parents(source, target)
                decision.target_path = str(target)
                report["quarantined"].append(asdict(decision))
                continue
            if decision.action == "regenerate":
                target = Path(decision.target_path)
                ensure_directory(target.parent)
                if source.exists() and not target.exists():
                    shutil.copy2(source, target)
                legacy_archive = archive_root / "archived" / decision.relative_path
                if source.exists():
                    self._move_with_parents(source, legacy_archive)
                report["regenerated"].append(asdict(decision))
                continue
        report_path = archive_root / "cleanup_report.json"
        ensure_directory(report_path.parent)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        report["report_path"] = str(report_path)
        return report

    def _create_snapshot(self, targets: Iterable[str], snapshot_dir: Path) -> None:
        for raw_path in targets:
            source = Path(raw_path)
            if not source.exists():
                continue
            try:
                relative = source.relative_to(self.paths.data_dir)
            except Exception:
                relative = Path(source.name)
            destination = snapshot_dir / relative
            ensure_directory(destination.parent)
            shutil.copy2(source, destination)

    @staticmethod
    def _move_with_parents(source: Path, target: Path) -> None:
        if not source.exists():
            return
        ensure_directory(target.parent)
        if target.exists():
            target.unlink()
        shutil.move(str(source), str(target))
