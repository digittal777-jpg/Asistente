from __future__ import annotations

import hashlib
import os
from collections import Counter
from typing import Dict, List, Optional

from core.training_models import OptimizedProfile, SkillGate, TrainingScenarioResult


DESKTOP_FIRST_GATES: Dict[int, SkillGate] = {
    0: SkillGate(
        skill_id="desktop-first",
        from_level=0,
        to_level=1,
        required_scenarios=["ui_detect_visible", "mouse_click_visible"],
        min_success_rate=1.0,
        max_fallback_rate=0.0,
        min_verified_sessions=5,
        max_days_to_gate=1,
    ),
    1: SkillGate(
        skill_id="desktop-first",
        from_level=1,
        to_level=2,
        required_scenarios=["ui_detect_distracted", "mouse_click_reopened_window"],
        min_success_rate=0.95,
        max_fallback_rate=0.05,
        min_verified_sessions=10,
        max_days_to_gate=2,
    ),
    2: SkillGate(
        skill_id="desktop-first",
        from_level=2,
        to_level=3,
        required_scenarios=["desktop_drag_constrained", "desktop_drag_no_fallback"],
        min_success_rate=0.85,
        max_fallback_rate=0.0,
        min_verified_sessions=15,
        max_days_to_gate=3,
    ),
    3: SkillGate(
        skill_id="desktop-first",
        from_level=3,
        to_level=4,
        required_scenarios=["desktop_drag_real_verify", "desktop_recovery_verified"],
        min_success_rate=0.75,
        max_fallback_rate=0.10,
        min_verified_sessions=20,
        max_days_to_gate=5,
    ),
    4: SkillGate(
        skill_id="desktop-first",
        from_level=4,
        to_level=5,
        required_scenarios=["desktop_adversarial_verify"],
        min_success_rate=0.60,
        max_fallback_rate=0.30,
        min_verified_sessions=30,
        max_days_to_gate=7,
    ),
    5: SkillGate(
        skill_id="desktop-first",
        from_level=5,
        to_level=6,
        required_scenarios=["desktop_autonomous_discovery"],
        min_success_rate=0.50,
        max_fallback_rate=1.0,
        min_verified_sessions=50,
        max_days_to_gate=14,
    ),
}

DESKTOP_SCENARIO_EQUIVALENTS: Dict[str, set[str]] = {
    "ui_detect_visible": {"ui_detect_visible", "mouse_click_visible"},
    "mouse_click_visible": {"mouse_click_visible"},
    "ui_detect_distracted": {"ui_detect_distracted", "ocr_partial_region"},
    "mouse_click_reopened_window": {"mouse_click_reopened_window"},
    "desktop_drag_constrained": {"desktop_drag_constrained", "desktop_drag_real_verify"},
    "desktop_drag_no_fallback": {"desktop_drag_no_fallback", "desktop_recovery_verified"},
    "desktop_drag_real_verify": {"desktop_drag_real_verify"},
    "desktop_recovery_verified": {"desktop_recovery_verified"},
    "desktop_adversarial_verify": {"desktop_adversarial_verify", "desktop_recovery_verified"},
    "desktop_autonomous_discovery": {"desktop_adversarial_verify", "desktop_recovery_verified"},
}


class DesktopFirstVerifier:
    def verify(self, result: TrainingScenarioResult) -> Dict[str, object]:
        if result.level <= 1:
            return self.verify_level_0_1(result)
        if result.level == 2:
            return self.verify_level_2(result)
        if result.level in {3, 4}:
            return self.verify_level_3_4(result)
        return self.verify_level_5(result)

    def verify_level_0_1(self, result: TrainingScenarioResult) -> Dict[str, object]:
        action_logged = bool(
            result.evidence.get("target_control_used")
            or result.evidence.get("selection_detection")
            or result.evidence.get("session_id")
        )
        return {
            "action_logged": action_logged,
            "verified_outcome": {"action_logged": action_logged},
        }

    def verify_level_2(self, result: TrainingScenarioResult) -> Dict[str, object]:
        clean = self.verify_level_0_1(result)["action_logged"] and not result.fallback_used
        return {
            "multiple_attempts_clean": clean,
            "verified_outcome": {"multiple_attempts_clean": clean, "fallback_used": result.fallback_used},
        }

    def verify_level_3_4(self, result: TrainingScenarioResult) -> Dict[str, object]:
        destination_path = str(result.evidence.get("destination_path") or result.evidence.get("destination") or "")
        expected_size = result.evidence.get("source_file_size") or result.evidence.get("expected_size")
        expected_checksum = result.evidence.get("source_checksum") or result.evidence.get("expected_checksum")

        file_exists = bool(destination_path and os.path.exists(destination_path))
        actual_size: Optional[int] = os.path.getsize(destination_path) if file_exists else None
        size_matches = actual_size == expected_size if expected_size is not None and file_exists else None
        checksum_valid = True
        if file_exists and expected_checksum:
            with open(destination_path, "rb") as handle:
                checksum_valid = hashlib.md5(handle.read()).hexdigest() == expected_checksum

        return {
            "file_exists": file_exists,
            "size_matches": size_matches,
            "checksum_valid": checksum_valid,
            "verified_outcome": {
                "destination_path": destination_path,
                "file_exists": file_exists,
                "expected_size": expected_size,
                "actual_size": actual_size,
                "checksum_valid": checksum_valid,
            },
        }

    def verify_level_5(self, result: TrainingScenarioResult) -> Dict[str, object]:
        base = self.verify_level_3_4(result)
        base["adversarial_verified"] = bool(base.get("file_exists")) and result.verified
        return base

    def evaluate_history(self, history: List[TrainingScenarioResult]) -> Dict[str, object]:
        if not history:
            return {"level": 0, "optimized_profile": None, "gates": {}}

        level = 0
        gate_reports: Dict[str, Dict[str, object]] = {}
        for from_level in range(0, 6):
            gate = DESKTOP_FIRST_GATES[from_level]
            relevant = [item for item in history if item.level >= gate.from_level]
            passed, report = self._gate_report(gate, relevant)
            gate_reports[f"{gate.from_level}_to_{gate.to_level}"] = report
            if not passed:
                break
            level = gate.to_level

        optimized_profile = self._optimized_profile(history) if level >= 5 else None
        if optimized_profile:
            level = 6
        return {
            "level": level,
            "optimized_profile": optimized_profile.to_dict() if optimized_profile else None,
            "gates": gate_reports,
        }

    def _gate_report(self, gate: SkillGate, history: List[TrainingScenarioResult]) -> tuple[bool, Dict[str, object]]:
        relevant = [item for item in history if self._relevant_to_gate(item, gate)]
        verified = [item for item in relevant if item.verified]
        success_count = sum(1 for item in relevant if item.status in {"success", "success_with_fallback"})
        fallback_count = sum(1 for item in relevant if item.fallback_used)
        success_rate = success_count / len(relevant) if relevant else 0.0
        fallback_rate = fallback_count / len(relevant) if relevant else 0.0
        scenario_hits = {key for item in verified for key in self._scenario_keys(item)}
        passed = (
            len(verified) >= gate.min_verified_sessions
            and success_rate >= gate.min_success_rate
            and fallback_rate <= gate.max_fallback_rate
            and all(self._scenario_satisfied(required, scenario_hits) for required in gate.required_scenarios)
        )
        return passed, {
            "verified_sessions_count": len(verified),
            "current_success_rate": round(success_rate, 4),
            "current_fallback_rate": round(fallback_rate, 4),
            "verified_scenarios_passed": sorted(scenario_hits),
            "gate_passed": passed,
        }

    @staticmethod
    def _scenario_satisfied(required: str, hits: set[str]) -> bool:
        accepted = DESKTOP_SCENARIO_EQUIVALENTS.get(required, {required})
        return any(item in hits for item in accepted)

    @staticmethod
    def _relevant_to_gate(item: TrainingScenarioResult, gate: SkillGate) -> bool:
        accepted = set()
        for required in gate.required_scenarios:
            accepted.update(DESKTOP_SCENARIO_EQUIVALENTS.get(required, {required}))
        return bool(accepted.intersection(DesktopFirstVerifier._scenario_keys(item)))

    @staticmethod
    def _scenario_keys(item: TrainingScenarioResult) -> set[str]:
        keys = {str(item.scenario_id or "")}
        evidence = dict(item.evidence or {})
        base = str(evidence.get("base_scenario_id") or "")
        if base:
            keys.add(base)
        equivalents = evidence.get("equivalent_scenarios", [])
        if isinstance(equivalents, list):
            keys.update(str(value) for value in equivalents if str(value).strip())
        return {value for value in keys if value}

    def _optimized_profile(self, history: List[TrainingScenarioResult]) -> Optional[OptimizedProfile]:
        if len(history) < 10:
            return None
        sorted_history = sorted(
            history,
            key=lambda item: (
                0 if item.status == "success" else 1,
                1 if item.fallback_used else 0,
                float(item.metrics.get("latency_ms", item.metrics.get("verification_latency_ms", 0.0) or 0.0)),
            ),
        )
        top_k = max(1, int(round(len(sorted_history) * 0.2)))
        best = sorted_history[:top_k]
        strategy_counter = Counter(item.chosen_strategy or "unknown" for item in best)
        fallback_counter = Counter(item.fallback_used for item in best if item.fallback_used)
        success_rate = sum(1 for item in best if item.verified) / len(best)
        return OptimizedProfile(
            skill_id="desktop-first",
            level=6,
            primary_strategy=strategy_counter.most_common(1)[0][0],
            fallback_strategies=[name for name, _count in fallback_counter.most_common(3)],
            recovery_playbook={},
            success_rate=round(success_rate, 4),
            confidence=round(min(1.0, 0.6 + success_rate * 0.4), 4),
            sample_size=len(best),
        )
