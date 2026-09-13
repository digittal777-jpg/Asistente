from __future__ import annotations

import json
from typing import Any, Callable, Dict

from core.data_paths import DataPaths
from core.logging_utils import ensure_directory


class ProfileStore:
    def __init__(self, paths: DataPaths, logger: Any = None) -> None:
        self.paths = paths
        self.path = paths.learning_profiles_path
        self.logger = logger
        ensure_directory(self.path.parent)

    def load_state(
        self,
        *,
        profile_schema_version: int,
        now_provider: Callable[[], str],
        normalize_profile: Callable[[str, Dict[str, Any]], Dict[str, Any]],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if self.path.exists():
            try:
                with self.path.open("r", encoding="utf-8-sig") as handle:
                    payload = json.load(handle)
            except Exception:
                if self.logger:
                    self.logger.exception("No se pudo cargar learning_skill_profiles.json")
        state = {
            "version": profile_schema_version,
            "updated_at": str(payload.get("updated_at") or now_provider()),
            "profiles": {},
        }
        raw_profiles = payload.get("profiles", {})
        if not isinstance(raw_profiles, dict):
            raw_profiles = {}
        for key, raw_profile in raw_profiles.items():
            if not isinstance(raw_profile, dict):
                continue
            profile = normalize_profile(str(key), raw_profile)
            state["profiles"][profile["skill_id"]] = profile
        return state

    def save_state(self, state: Dict[str, Any], *, updated_at: str) -> None:
        state["updated_at"] = updated_at
        self.path.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
