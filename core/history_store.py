from __future__ import annotations

import json
from typing import Any, Dict, List

from core.data_paths import DataPaths
from core.logging_utils import ensure_directory
from core.training_models import TrainingScenarioResult


class TrainingHistoryStore:
    def __init__(self, paths: DataPaths, logger: Any = None) -> None:
        self.paths = paths
        self.training_results_path = paths.training_results_path
        self.desktop_mouse_strategy_path = paths.desktop_mouse_strategy_path
        self.logger = logger
        ensure_directory(self.training_results_path.parent)
        ensure_directory(self.desktop_mouse_strategy_path.parent)

    def append_training_result(self, result: TrainingScenarioResult) -> None:
        with self.training_results_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")

    def structured_results_for_skill(self, skill_id: str) -> List[TrainingScenarioResult]:
        if not self.training_results_path.exists():
            return []
        results: List[TrainingScenarioResult] = []
        with self.training_results_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if str(payload.get("skill_id", "")) != skill_id:
                    continue
                try:
                    results.append(TrainingScenarioResult(**payload))
                except TypeError:
                    continue
        return results

    def read_mouse_strategy(self) -> Dict[str, Any]:
        if not self.desktop_mouse_strategy_path.exists():
            return {}
        try:
            return json.loads(self.desktop_mouse_strategy_path.read_text(encoding="utf-8-sig"))
        except Exception:
            if self.logger:
                self.logger.warning("No se pudo cargar desktop_mouse_strategy.json")
            return {}

    def write_mouse_strategy(self, payload: Dict[str, Any]) -> None:
        self.desktop_mouse_strategy_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
