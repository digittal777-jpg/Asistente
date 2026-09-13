from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TrainingScenarioResult:
    skill_id: str
    domain: str
    scenario_id: str
    level: int
    status: str
    verified: bool
    session_id: str = ""
    timestamp: int = 0
    failure_stage: Optional[str] = None
    fallback_used: Optional[str] = None
    attempted_strategies: List[str] = field(default_factory=list)
    chosen_strategy: str = ""
    retryable: bool = False
    metrics: Dict[str, Any] = field(default_factory=dict)
    evidence: Dict[str, Any] = field(default_factory=dict)
    verified_outcome: Dict[str, Any] = field(default_factory=dict)
    error_log: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SkillGate:
    skill_id: str
    from_level: int
    to_level: int
    required_scenarios: List[str]
    min_success_rate: float
    max_fallback_rate: float
    min_verified_sessions: int
    max_days_to_gate: int
    verified_scenarios_passed: List[str] = field(default_factory=list)
    verified_sessions_count: int = 0
    current_success_rate: float = 0.0
    current_fallback_rate: float = 0.0
    gate_passed: bool = False
    gate_passed_date: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TrainableDraft:
    skill_id: str
    skill_name: str
    description: str
    family: str
    scenario_templates: List[dict]
    verification_rules: Dict[str, Any]
    missing_capabilities: List[str] = field(default_factory=list)
    readiness_blockers: List[str] = field(default_factory=list)
    estimated_training_days: int = 7
    created_date: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RecoveryAttempt:
    domain: str
    training_scenario_id: str
    failure_session_id: str
    failure_stage: str
    failure_reason: str
    attempted_strategies: List[str]
    chosen_next_strategy: str
    strategy_reasoning: str
    recovery_session_id: str = ""
    recovery_succeeded: bool = False
    recovery_verified: bool = False
    verified_outcome: Dict[str, Any] = field(default_factory=dict)
    confidence_in_recovery: float = 0.0
    is_playbook_decision: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModelAssistDecision:
    model_id: str
    decision_type: str
    input_type: str
    score: float
    recommendation: str
    used: bool
    fallback_reason: Optional[str] = None
    heuristic_score: Optional[float] = None
    timestamp: int = 0
    session_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OptimizedProfile:
    skill_id: str
    level: int
    primary_strategy: str
    fallback_strategies: List[str]
    recovery_playbook: Dict[str, List[str]]
    success_rate: float
    confidence: float
    sample_size: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DomainTrainingState:
    domain: str
    priority_rank: int
    success_rate: float
    fallback_rate: float
    days_stagnant: float
    freshness_score: float
    operational_score: float
    last_level_progress_days: float = 0.0
    active_skill_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
