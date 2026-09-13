from __future__ import annotations

import math
from typing import Iterable, List, Optional

from core.training_models import DomainTrainingState


DOMAIN_PRIORITY_RANKS = {
    "keyboard": 1,
    "perception": 1,
    "vision/detection": 1,
    "selection/workflow": 2,
    "research": 1,
    "browser": 3,
    "file_manager/explorer": 3,
    "document_editor": 4,
    "application_workflow": 4,
    "game_foundation": 5,
}


class SkillScheduler:
    def __init__(
        self,
        priority_weight: float = 0.30,
        weakness_weight: float = 0.35,
        stagnation_weight: float = 0.15,
        freshness_weight: float = 0.10,
        operational_weight: float = 0.10,
    ) -> None:
        self.priority_weight = priority_weight
        self.weakness_weight = weakness_weight
        self.stagnation_weight = stagnation_weight
        self.freshness_weight = freshness_weight
        self.operational_weight = operational_weight

    def score_domain(self, state: DomainTrainingState) -> float:
        priority_score = (9 - max(1, int(state.priority_rank))) / 8
        weakness_score = max(0.0, (1.0 - float(state.success_rate))) * (1.0 + float(state.fallback_rate))
        stagnation_score = math.log(1 + max(0.0, float(state.days_stagnant)) / 2.0) / math.log(8)
        freshness_score = max(0.0, min(1.0, float(state.freshness_score)))
        operational_score = max(0.0, min(1.0, float(state.operational_score)))
        return (
            self.priority_weight * priority_score
            + self.weakness_weight * weakness_score
            + self.stagnation_weight * stagnation_score
            + self.freshness_weight * freshness_score
            + self.operational_weight * operational_score
        )

    def rank_domains(self, states: Iterable[DomainTrainingState]) -> List[DomainTrainingState]:
        return sorted(states, key=self.score_domain, reverse=True)

    def next_domain(self, states: Iterable[DomainTrainingState]) -> Optional[DomainTrainingState]:
        ranked = self.rank_domains(states)
        return ranked[0] if ranked else None

    @staticmethod
    def default_domain_states() -> List[DomainTrainingState]:
        return [
            DomainTrainingState(
                domain=domain,
                priority_rank=priority_rank,
                success_rate=0.0,
                fallback_rate=0.0,
                days_stagnant=0.0,
                freshness_score=1.0,
                operational_score=0.0,
                active_skill_ids=[],
            )
            for domain, priority_rank in DOMAIN_PRIORITY_RANKS.items()
        ]
