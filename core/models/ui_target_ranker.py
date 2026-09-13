from __future__ import annotations

from typing import Dict, Iterable, List, Optional


class UITargetRankerModel:
    """Ranker heurístico con slot opcional para ONNX."""

    def __init__(self, model_path: Optional[str] = None) -> None:
        self.model_path = model_path
        self.runtime = None

    def rank_candidates(
        self,
        candidates: Iterable[Dict[str, object]],
        context: Optional[Dict[str, object]] = None,
    ) -> List[Dict[str, object]]:
        context = context or {}
        target_level = int(context.get("target_level", 0) or 0)
        ranked: List[Dict[str, object]] = []
        for candidate in candidates:
            payload = dict(candidate)
            level = int(payload.get("level", 0) or 0)
            closeness = 1.0 - min(1.0, abs(level - target_level) / 6.0)
            priority_bonus = 0.25 if str(payload.get("scenario_id", "")).endswith("verify") else 0.0
            heuristic_score = round(max(0.0, closeness + priority_bonus), 4)
            payload["_heuristic_score"] = heuristic_score
            payload["_score"] = heuristic_score
            ranked.append(payload)
        return sorted(ranked, key=lambda item: float(item.get("_score", 0.0)), reverse=True)
