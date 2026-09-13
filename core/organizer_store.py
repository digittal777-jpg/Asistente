from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.data_paths import DataPaths
from core.logging_utils import ensure_directory


class OrganizerSessionStore:
    def __init__(self, paths: DataPaths, logger: Any = None) -> None:
        self.paths = paths
        self.sessions_dir = paths.organizer_sessions_dir
        self.strategy_path = paths.desktop_mouse_strategy_path
        self.logger = logger
        ensure_directory(self.sessions_dir)
        ensure_directory(self.strategy_path.parent)

    def manifest_path_for(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.json"

    def read_json(self, path: Path) -> Dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def load_drag_strategy(self, merge_defaults: Callable[[Dict[str, Any]], Dict[str, Any]]) -> Dict[str, Any]:
        if self.strategy_path.exists():
            try:
                return merge_defaults(self.read_json(self.strategy_path))
            except Exception:
                if self.logger:
                    self.logger.warning("No se pudo cargar desktop_mouse_strategy.json")
        return merge_defaults({})

    def save_drag_strategy(self, payload: Dict[str, Any]) -> None:
        self.strategy_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def read_latest_pointer(self, filename: str = "latest.json") -> Dict[str, Any]:
        latest_path = self.sessions_dir / filename
        if not latest_path.exists():
            return {}
        try:
            return self.read_json(latest_path)
        except Exception:
            return {}

    def write_manifest(self, session_payload: Dict[str, Any]) -> Path:
        session_id = str(session_payload.get("session_id", "") or "")
        manifest_path = self.manifest_path_for(session_id)
        ensure_directory(manifest_path.parent)
        manifest_path.write_text(json.dumps(session_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return manifest_path

    def write_latest_pointer(
        self,
        filename: str,
        *,
        session_id: str,
        manifest_path: str,
        updated_at: Optional[str] = None,
    ) -> Path:
        payload = {
            "session_id": session_id,
            "manifest_path": manifest_path,
            "updated_at": updated_at or datetime.now().isoformat(timespec="seconds"),
        }
        pointer_path = self.sessions_dir / filename
        pointer_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return pointer_path

    def iter_session_payloads(self, pattern: str = "*.json") -> List[Tuple[Path, Dict[str, Any]]]:
        payloads: List[Tuple[Path, Dict[str, Any]]] = []
        for path in sorted(self.sessions_dir.glob(pattern)):
            try:
                payloads.append((path, self.read_json(path)))
            except Exception:
                continue
        return payloads
