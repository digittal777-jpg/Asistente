from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logging_utils import ensure_directory
from core.skills import normalize_text
from core.training_models import RecoveryAttempt


VISION_PLAYBOOKS: Dict[str, List[str]] = {
    "detection_lost": ["retry_with_focus", "ocr_fallback", "manual"],
    "action_failed_3x": ["copy_clipboard", "explorer_fallback", "manual_position"],
    "verification_failed": ["verify_again", "check_alt_location", "inspect_fs"],
}

RESEARCH_PLAYBOOKS: Dict[str, List[str]] = {
    "page_timeout": ["retry_url", "search_keywords", "cache"],
    "poor_quality": ["skip_page", "search_specific", "ocr_screenshot"],
    "ocr_failed": ["retry_ocr", "capture_again", "manual_entry"],
}

GENERIC_PLAYBOOKS: Dict[str, List[str]] = {
    "detection": ["retry_with_focus", "ocr_fallback", "manual"],
    "action": ["retry_action", "copy_clipboard", "manual_position"],
    "verification": ["verify_again", "check_alt_location", "inspect_fs"],
}


class RecoveryEngine:
    def __init__(
        self,
        base_dir: Path,
        learning: Optional[Any] = None,
        logger: Optional[Any] = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.learning = learning
        self.logger = logger
        self.path = self.base_dir / "data" / "recovery_attempts.jsonl"
        ensure_directory(self.path.parent)

    def get_next_strategy(self, failure: Dict[str, Any]) -> RecoveryAttempt:
        domain = normalize_text(str(failure.get("domain", ""))) or "generic"
        failure_stage = normalize_text(str(failure.get("failure_stage", ""))) or "action"
        attempted_strategies = [str(item) for item in failure.get("attempted_strategies", [])]
        scenario_id = str(failure.get("training_scenario_id", ""))
        failure_session_id = str(failure.get("failure_session_id", ""))
        reason = str(failure.get("failure_reason", ""))
        candidates = self._playbook_candidates(domain, failure_stage)
        candidates = [item for item in candidates if item not in attempted_strategies] or candidates

        chosen = ""
        if self.learning and hasattr(self.learning, "preferred_recovery_strategy"):
            try:
                chosen = self.learning.preferred_recovery_strategy(
                    domain=domain,
                    candidates=candidates,
                    failure_stage=failure_stage,
                ) or ""
            except Exception:
                chosen = ""
        if not chosen:
            chosen = candidates[0] if candidates else "manual"

        reasoning = (
            f"Playbook {domain}:{failure_stage} prioriza '{chosen}' "
            f"despues de intentar {attempted_strategies or ['ninguna']}."
        )
        return RecoveryAttempt(
            domain=domain,
            training_scenario_id=scenario_id,
            failure_session_id=failure_session_id,
            failure_stage=failure_stage,
            failure_reason=reason,
            attempted_strategies=attempted_strategies,
            chosen_next_strategy=chosen,
            strategy_reasoning=reasoning,
            confidence_in_recovery=self._confidence(domain, chosen),
            is_playbook_decision=True,
        )

    def record_attempt(self, attempt: RecoveryAttempt) -> None:
        payload = attempt.to_dict()
        payload["recorded_at"] = int(time.time())
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        if self.learning and hasattr(self.learning, "record_recovery_attempt"):
            try:
                self.learning.record_recovery_attempt(
                    domain=normalize_text(payload.get("domain", "")) or "generic",
                    failure_stage=payload["failure_stage"],
                    failure_reason=payload["failure_reason"],
                    attempted_strategies=payload["attempted_strategies"],
                    chosen_next_strategy=payload["chosen_next_strategy"],
                    verified_outcome=bool(payload.get("recovery_verified")),
                    context={"failure_session_id": payload["failure_session_id"]},
                )
            except Exception:
                if self.logger:
                    self.logger.exception("No se pudo registrar recovery attempt en intelligent learning")

    def _playbook_candidates(self, domain: str, failure_stage: str) -> List[str]:
        if "research" in domain:
            return RESEARCH_PLAYBOOKS.get(failure_stage, RESEARCH_PLAYBOOKS.get("poor_quality", []))
        if "vision" in domain or "desktop" in domain or "selection" in domain:
            return VISION_PLAYBOOKS.get(failure_stage, VISION_PLAYBOOKS.get("detection_lost", []))
        return GENERIC_PLAYBOOKS.get(failure_stage, GENERIC_PLAYBOOKS.get("action", []))

    def _confidence(self, domain: str, strategy: str) -> float:
        if self.learning and hasattr(self.learning, "state"):
            try:
                recoveries = self.learning.state.get("recoveries", {}).get(domain, {})
                entry = recoveries.get(strategy, {})
                successes = float(entry.get("verified_recoveries", 0))
                failures = float(entry.get("failed_recoveries", 0))
                total = successes + failures
                if total > 0:
                    return round(successes / total, 4)
            except Exception:
                return 0.5
        return 0.5
