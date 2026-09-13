from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.data_paths import DataPaths
from core.logging_utils import ensure_directory


class LearningSessionStore:
    def __init__(self, paths: DataPaths, logger: Any = None) -> None:
        self.paths = paths
        self.sessions_dir = paths.learning_sessions_dir
        self.logger = logger
        ensure_directory(self.sessions_dir)

    def manifest_path_for(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.json"

    def research_note_path_for(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}_research_note.md"

    def write_session_payload(self, session: Dict[str, Any]) -> Path:
        manifest_path = self.manifest_path_for(str(session.get("session_id", "")))
        session["manifest_path"] = str(manifest_path)
        ensure_directory(manifest_path.parent)
        manifest_path.write_text(json.dumps(session, indent=2, ensure_ascii=False), encoding="utf-8")
        return manifest_path

    def write_research_note(self, session_id: str, lines: List[str]) -> str:
        path = self.research_note_path_for(session_id)
        ensure_directory(path.parent)
        path.write_text("\n".join(item for item in lines if item is not None), encoding="utf-8")
        return str(path)

    def iter_manifest_paths(self, pattern: str = "*.json") -> List[Path]:
        return sorted(self.sessions_dir.glob(pattern))

    def read_json_payload(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            if self.logger:
                self.logger.warning(f"No se pudo leer manifiesto de sesion: {path}")
            return None
