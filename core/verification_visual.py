from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional

from core.perception import ACTION_CONFIDENCE_THRESHOLD, REACQUIRE_DELTA_THRESHOLD
from core.training_models import OptimizedProfile, SkillGate, TrainingScenarioResult


VISUAL_GATES: Dict[int, SkillGate] = {
    0: SkillGate(
        skill_id="visualizacion",
        from_level=0,
        to_level=1,
        required_scenarios=["visual_context_identity"],
        min_success_rate=1.0,
        max_fallback_rate=0.0,
        min_verified_sessions=4,
        max_days_to_gate=1,
    ),
    1: SkillGate(
        skill_id="visualizacion",
        from_level=1,
        to_level=2,
        required_scenarios=["visual_target_reacquire"],
        min_success_rate=0.85,
        max_fallback_rate=0.10,
        min_verified_sessions=6,
        max_days_to_gate=3,
    ),
    2: SkillGate(
        skill_id="visualizacion",
        from_level=2,
        to_level=3,
        required_scenarios=["visual_scene_transition"],
        min_success_rate=0.80,
        max_fallback_rate=0.15,
        min_verified_sessions=8,
        max_days_to_gate=5,
    ),
    3: SkillGate(
        skill_id="visualizacion",
        from_level=3,
        to_level=4,
        required_scenarios=["visual_workflow_precondition"],
        min_success_rate=0.80,
        max_fallback_rate=0.20,
        min_verified_sessions=10,
        max_days_to_gate=7,
    ),
    4: SkillGate(
        skill_id="visualizacion",
        from_level=4,
        to_level=5,
        required_scenarios=["visual_adversarial_recovery"],
        min_success_rate=0.70,
        max_fallback_rate=0.25,
        min_verified_sessions=12,
        max_days_to_gate=10,
    ),
    5: SkillGate(
        skill_id="visualizacion",
        from_level=5,
        to_level=6,
        required_scenarios=["visual_adversarial_recovery"],
        min_success_rate=0.60,
        max_fallback_rate=0.30,
        min_verified_sessions=16,
        max_days_to_gate=14,
    ),
}


class VisualPerceptionVerifier:
    def verify(self, result: TrainingScenarioResult) -> Dict[str, object]:
        scenario_id = str(result.scenario_id or "")
        if scenario_id == "visual_context_identity":
            return self.verify_context_identity(result)
        if scenario_id == "visual_target_reacquire":
            return self.verify_target_reacquire(result)
        if scenario_id == "visual_scene_transition":
            return self.verify_scene_transition(result)
        if scenario_id == "visual_workflow_precondition":
            return self.verify_workflow_precondition(result)
        if scenario_id == "visual_adversarial_recovery":
            return self.verify_adversarial_recovery(result)
        return {"verified": False, "verified_outcome": {"reason": "unsupported_visual_scenario"}}

    def verify_context_identity(self, result: TrainingScenarioResult) -> Dict[str, object]:
        evidence = dict(result.evidence or {})
        scene_kind = str(evidence.get("scene_kind") or "")
        confidence = float(evidence.get("confidence", 0.0) or 0.0)
        actable_targets = int(evidence.get("actable_target_count", 0) or 0)
        selected_target_id = str(evidence.get("selected_target_id") or "")
        ocr_only = bool(evidence.get("ocr_only"))
        ok = (
            scene_kind not in {"", "unknown"}
            and confidence >= ACTION_CONFIDENCE_THRESHOLD
            and actable_targets >= 1
            and bool(selected_target_id)
            and not ocr_only
        )
        return {
            "context_identity_verified": ok,
            "verified_outcome": {
                "scene_kind": scene_kind,
                "confidence": confidence,
                "actable_target_count": actable_targets,
                "selected_target_id": selected_target_id,
            },
        }

    def verify_target_reacquire(self, result: TrainingScenarioResult) -> Dict[str, object]:
        evidence = dict(result.evidence or {})
        reacquire = dict(evidence.get("reacquire") or {})
        ocr_only = bool(evidence.get("ocr_only"))
        matched = bool(reacquire.get("matched"))
        delta_px = reacquire.get("delta_px")
        stable_signature_match = bool(reacquire.get("stable_signature_match"))
        delta_ok = delta_px is not None and float(delta_px) <= REACQUIRE_DELTA_THRESHOLD
        ok = bool(matched and not ocr_only and (stable_signature_match or delta_ok))
        return {
            "target_reacquire_verified": ok,
            "verified_outcome": {
                "matched": matched,
                "delta_px": delta_px,
                "stable_signature_match": stable_signature_match,
                "current_target_id": str(reacquire.get("current_target_id") or ""),
            },
        }

    def verify_scene_transition(self, result: TrainingScenarioResult) -> Dict[str, object]:
        evidence = dict(result.evidence or {})
        initial_scene = str(evidence.get("initial_scene_kind") or "")
        final_scene = str(evidence.get("final_scene_kind") or "")
        scene_changed = initial_scene not in {"", "unknown"} and final_scene not in {"", "unknown"} and initial_scene != final_scene
        return {
            "scene_transition_verified": scene_changed,
            "verified_outcome": {
                "initial_scene_kind": initial_scene,
                "final_scene_kind": final_scene,
                "scene_changed": scene_changed,
            },
        }

    def verify_workflow_precondition(self, result: TrainingScenarioResult) -> Dict[str, object]:
        evidence = dict(result.evidence or {})
        precondition_ready = bool(evidence.get("precondition_ready"))
        confidence = float(evidence.get("selected_target_confidence", 0.0) or 0.0)
        scene_kind = str(evidence.get("scene_kind") or "")
        blocking_reason = str(evidence.get("blocking_reason") or "")
        verification_source = str(evidence.get("verification_source") or "")
        ok = (
            scene_kind not in {"", "unknown", "browser_serp"}
            and precondition_ready
            and confidence >= ACTION_CONFIDENCE_THRESHOLD
            and not blocking_reason
            and verification_source != "ocr_only"
        )
        return {
            "workflow_precondition_verified": ok,
            "verified_outcome": {
                "scene_kind": scene_kind,
                "precondition_ready": precondition_ready,
                "selected_target_confidence": confidence,
                "blocking_reason": blocking_reason,
            },
        }

    def verify_adversarial_recovery(self, result: TrainingScenarioResult) -> Dict[str, object]:
        evidence = dict(result.evidence or {})
        initial_blocked = bool(evidence.get("initial_blocked"))
        recovered = bool(evidence.get("recovered"))
        recovery_confidence = float(evidence.get("recovery_target_confidence", 0.0) or 0.0)
        ocr_only = bool(evidence.get("ocr_only"))
        ok = initial_blocked and recovered and recovery_confidence >= ACTION_CONFIDENCE_THRESHOLD and not ocr_only
        return {
            "adversarial_recovery_verified": ok,
            "verified_outcome": {
                "initial_blocked": initial_blocked,
                "recovered": recovered,
                "recovery_target_confidence": recovery_confidence,
            },
        }

    def evaluate_history(self, history: List[TrainingScenarioResult]) -> Dict[str, object]:
        if not history:
            return {"level": 0, "optimized_profile": None, "gates": {}}
        level = 0
        gate_reports: Dict[str, Dict[str, object]] = {}
        for from_level in range(0, 6):
            gate = VISUAL_GATES[from_level]
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
        relevant = list(history)
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
            and all(required in scenario_hits for required in gate.required_scenarios)
        )
        return passed, {
            "verified_sessions_count": len(verified),
            "current_success_rate": round(success_rate, 4),
            "current_fallback_rate": round(fallback_rate, 4),
            "verified_scenarios_passed": sorted(scenario_hits),
            "gate_passed": passed,
        }

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
        if len(history) < 8:
            return None
        sorted_history = sorted(
            history,
            key=lambda item: (
                0 if item.status == "success" else 1,
                1 if item.fallback_used else 0,
                -float(item.metrics.get("confidence", 0.0) or 0.0),
            ),
        )
        top_k = max(1, int(round(len(sorted_history) * 0.2)))
        best = sorted_history[:top_k]
        strategy_counter = Counter(item.chosen_strategy or "unknown" for item in best)
        fallback_counter = Counter(item.fallback_used for item in best if item.fallback_used)
        success_rate = sum(1 for item in best if item.verified) / len(best)
        return OptimizedProfile(
            skill_id="visualizacion",
            level=6,
            primary_strategy=strategy_counter.most_common(1)[0][0],
            fallback_strategies=[name for name, _count in fallback_counter.most_common(3)],
            recovery_playbook={},
            success_rate=round(success_rate, 4),
            confidence=round(min(1.0, 0.6 + success_rate * 0.4), 4),
            sample_size=len(best),
        )
