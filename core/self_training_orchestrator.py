from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.curriculum_planner import Curriculum, CurriculumPlanner, Phase
from core.task_analysis import TaskAnalysisResult
from core.training_models import TrainingScenarioResult


@dataclass
class LearningProgress:
    objective: str
    phases_completed: List[str] = field(default_factory=list)
    total_sessions: int = 0
    total_hours: float = 0.0
    success_rate: float = 0.0
    current_phase_id: str = ""
    timestamp: int = 0


class SelfTrainingOrchestrator:
    """Orquesta el aprendizaje autónomo apoyándose en el loop infinito."""

    def __init__(
        self,
        loop: Any,
        planner: CurriculumPlanner,
        logger: Optional[Any] = None,
    ) -> None:
        self.loop = loop
        self.planner = planner
        self.logger = logger
        self.current_curriculum: Optional[Curriculum] = None
        self.progress = LearningProgress(objective="", timestamp=int(time.time()))
        self.session_results: List[TrainingScenarioResult] = []

    def learn(
        self,
        objective: str,
        task_analysis: TaskAnalysisResult,
        knowledge_assets: Optional[List[dict]] = None,
        max_attempts_per_scenario: int = 8,
    ) -> Dict[str, Any]:
        start_time = time.time()
        self.current_curriculum = self.planner.create_curriculum(task_analysis, knowledge_assets or [])
        self.progress = LearningProgress(objective=objective, timestamp=int(time.time()))
        self.session_results = []
        all_phases_completed = True

        for phase in self.current_curriculum.phases:
            self.progress.current_phase_id = phase.phase_id
            phase_sessions, phase_success_rate, phase_completed = self._train_phase(
                phase,
                max_attempts_per_scenario=max_attempts_per_scenario,
            )
            if phase_completed and phase.phase_id not in self.progress.phases_completed:
                self.progress.phases_completed.append(phase.phase_id)
            all_phases_completed = all_phases_completed and phase_completed
            self.progress.total_sessions += phase_sessions
            if self.logger:
                self.logger.info(
                    "Fase autonoma %s: %s | sesiones=%s | tasa=%.2f",
                    phase.phase_id,
                    "completada" if phase_completed else "incompleta",
                    phase_sessions,
                    phase_success_rate,
                )

        elapsed_hours = max(0.0, (time.time() - start_time) / 3600.0)
        verified_results = [item for item in self.session_results if item.verified]
        successes = [item for item in self.session_results if item.status in {"success", "success_with_fallback"}]
        self.progress.total_hours = elapsed_hours
        self.progress.success_rate = len(successes) / len(self.session_results) if self.session_results else 0.0
        self.progress.timestamp = int(time.time())
        autonomous_success = all_phases_completed and bool(verified_results)

        return {
            "success": autonomous_success,
            "objective": objective,
            "curriculum": self.current_curriculum,
            "progress": self.progress,
            "total_sessions": self.progress.total_sessions,
            "total_hours": elapsed_hours,
            "verified_sessions": len(verified_results),
            "final_report": self._final_report(objective),
        }

    def _train_phase(self, phase: Phase, max_attempts_per_scenario: int) -> tuple[int, float, bool]:
        phase_sessions = 0
        phase_successes = 0
        phase_completed = True
        for scenario in phase.scenarios:
            scenario_verified = 0
            attempts = 0
            preferred_domain = self._scenario_domain(scenario)
            while scenario_verified < int(scenario.get("min_sessions", 2)) and attempts < max_attempts_per_scenario:
                result = self.loop.run_one_cycle(
                    preferred_domain=preferred_domain,
                    forced_scenario=scenario,
                    forced_skill_id=str(scenario.get("skill_id", "") or ""),
                )
                self.session_results.append(result)
                phase_sessions += 1
                attempts += 1
                if result.verified and result.status in {"success", "success_with_fallback"}:
                    scenario_verified += 1
                    phase_successes += 1
            if scenario_verified < int(scenario.get("min_sessions", 2)):
                phase_completed = False
        success_rate = phase_successes / phase_sessions if phase_sessions else 0.0
        return phase_sessions, success_rate, phase_completed

    @staticmethod
    def _scenario_domain(scenario: Dict[str, Any]) -> str:
        explicit_domain = str(scenario.get("domain", "") or "").strip()
        if explicit_domain:
            return explicit_domain
        family = str(scenario.get("family", "application"))
        mapping = {
            "vision": "vision/detection",
            "research": "research",
            "browser": "browser",
            "file_manager": "file_manager/explorer",
            "documents": "document_editor",
            "application": "application_workflow",
            "game": "game_foundation",
        }
        return mapping.get(family, "application_workflow")

    def _final_report(self, objective: str) -> str:
        total_phases = len(self.current_curriculum.phases) if self.current_curriculum else 0
        completed = len(self.progress.phases_completed)
        status = "completado" if total_phases and completed >= total_phases else "incompleto"
        return (
            f"Aprendizaje autonomo {status} para '{objective}'. "
            f"Fases: {completed}/{total_phases} | "
            f"sesiones: {self.progress.total_sessions} | "
            f"tasa: {self.progress.success_rate:.1%}"
        )
