from __future__ import annotations

import os
from collections import Counter
from typing import Dict, List, Optional

from core.skills import normalize_text
from core.training_models import OptimizedProfile, SkillGate, TrainingScenarioResult


RESEARCH_GATES: Dict[int, SkillGate] = {
    0: SkillGate(
        skill_id="investigar",
        from_level=0,
        to_level=1,
        required_scenarios=["research_single_source"],
        min_success_rate=1.0,
        max_fallback_rate=0.0,
        min_verified_sessions=5,
        max_days_to_gate=1,
    ),
    1: SkillGate(
        skill_id="investigar",
        from_level=1,
        to_level=2,
        required_scenarios=["research_multi_query"],
        min_success_rate=0.95,
        max_fallback_rate=0.10,
        min_verified_sessions=8,
        max_days_to_gate=3,
    ),
    2: SkillGate(
        skill_id="investigar",
        from_level=2,
        to_level=3,
        required_scenarios=["research_structured_extract", "research_discard_poor"],
        min_success_rate=0.85,
        max_fallback_rate=0.15,
        min_verified_sessions=12,
        max_days_to_gate=5,
    ),
    3: SkillGate(
        skill_id="investigar",
        from_level=3,
        to_level=4,
        required_scenarios=["research_to_document", "research_cross_verify"],
        min_success_rate=0.80,
        max_fallback_rate=0.25,
        min_verified_sessions=15,
        max_days_to_gate=7,
    ),
    4: SkillGate(
        skill_id="investigar",
        from_level=4,
        to_level=5,
        required_scenarios=["research_adversarial_recovery"],
        min_success_rate=0.70,
        max_fallback_rate=0.25,
        min_verified_sessions=30,
        max_days_to_gate=14,
    ),
    5: SkillGate(
        skill_id="investigar",
        from_level=5,
        to_level=6,
        required_scenarios=["research_autonomous_discovery"],
        min_success_rate=0.50,
        max_fallback_rate=1.0,
        min_verified_sessions=50,
        max_days_to_gate=21,
    ),
}


class ResearchVerifier:
    @staticmethod
    def _is_hard_verified(result: TrainingScenarioResult) -> bool:
        evidence = dict(result.evidence or {})
        metrics = dict(result.metrics or {})
        if result.verified is False:
            return False
        if bool(evidence.get("current_session_verified")):
            return True
        if bool(evidence.get("verified")):
            return True
        if bool(evidence.get("hard_verified")):
            return True
        if bool(metrics.get("hard_verified")):
            return True
        if evidence.get("visible_text_chars") is not None:
            chars = int(evidence.get("visible_text_chars", 0) or 0)
            if chars >= 300:
                return True
        return False

    def verify(self, result: TrainingScenarioResult) -> Dict[str, object]:
        if result.level <= 1:
            return self.verify_level_0_1(result)
        if result.level == 2:
            return self.verify_level_2(result)
        if result.level in {3, 4}:
            return self.verify_level_3_4(result)
        return self.verify_level_5(result)

    def verify_level_0_1(self, result: TrainingScenarioResult) -> Dict[str, object]:
        useful_sources = int(result.evidence.get("useful_source_count", 0) or 0)
        captured_chars = int(result.evidence.get("captured_chars", 0) or 0)
        page_label = normalize_text(str(result.evidence.get("page_usefulness_label", "") or ""))
        if not page_label:
            page_label = "useful" if useful_sources >= 1 and captured_chars >= 500 else "poor"
        current_session_verified = bool(result.evidence.get("current_session_verified", result.verified))
        ok = current_session_verified and useful_sources >= 1 and page_label == "useful"
        return {
            "single_source_verified": ok,
            "verified_outcome": {
                "useful_source_count": useful_sources,
                "captured_chars": captured_chars,
                "page_usefulness_label": page_label,
                "current_session_verified": current_session_verified,
            },
        }

    def verify_level_2(self, result: TrainingScenarioResult) -> Dict[str, object]:
        useful_sources = int(result.evidence.get("useful_source_count", 0) or 0)
        poor_precision = float(result.metrics.get("discard_precision", 0.0) or 0.0)
        ok = self._is_hard_verified(result) and useful_sources >= 3 and poor_precision >= 0.70
        return {
            "multi_query_verified": ok,
            "verified_outcome": {
                "useful_source_count": useful_sources,
                "discard_precision": poor_precision,
            },
        }

    def verify_level_3_4(self, result: TrainingScenarioResult) -> Dict[str, object]:
        document_path = str(result.evidence.get("document_path") or result.evidence.get("output_path") or "")
        keywords = list(result.evidence.get("keywords", []))
        unique_facts = int(result.metrics.get("unique_facts", result.evidence.get("unique_facts", 0)) or 0)
        file_exists = bool(document_path and os.path.exists(document_path))
        size_ok = os.path.getsize(document_path) >= 5120 if file_exists else False
        keyword_hits = 0
        if file_exists and keywords:
            try:
                content = open(document_path, "r", encoding="utf-8", errors="ignore").read().lower()
                keyword_hits = sum(1 for kw in keywords if str(kw).lower() in content)
            except Exception:
                keyword_hits = 0
        ok = self._is_hard_verified(result) and file_exists and size_ok and unique_facts >= 5 and (not keywords or keyword_hits >= 3)
        return {
            "file_exists": file_exists,
            "size_ok": size_ok,
            "unique_facts": unique_facts,
            "keyword_hits": keyword_hits,
            "verified_outcome": {
                "document_path": document_path,
                "file_exists": file_exists,
                "size_bytes": os.path.getsize(document_path) if file_exists else 0,
                "unique_facts": unique_facts,
                "keyword_hits": keyword_hits,
            },
            "verified": ok,
        }

    def verify_level_5(self, result: TrainingScenarioResult) -> Dict[str, object]:
        base = self.verify_level_3_4(result)
        base["adversarial_verified"] = bool(base.get("verified"))
        return base

    def evaluate_history(self, history: List[TrainingScenarioResult]) -> Dict[str, object]:
        if not history:
            return {"level": 0, "optimized_profile": None, "gates": {}}
        level = 0
        gate_reports: Dict[str, Dict[str, object]] = {}
        for from_level in range(0, 6):
            gate = RESEARCH_GATES[from_level]
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
        relevant = [item for item in history if self._is_hard_verified(item)]
        verified = relevant
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
        if len(history) < 10:
            return None
        sorted_history = sorted(
            history,
            key=lambda item: (
                0 if item.status == "success" else 1,
                1 if item.fallback_used else 0,
                -int(item.metrics.get("unique_facts", 0) or 0),
            ),
        )
        top_k = max(1, int(round(len(sorted_history) * 0.2)))
        best = sorted_history[:top_k]
        strategy_counter = Counter(item.chosen_strategy or "unknown" for item in best)
        fallback_counter = Counter(item.fallback_used for item in best if item.fallback_used)
        success_rate = sum(1 for item in best if item.verified) / len(best)
        return OptimizedProfile(
            skill_id="investigar",
            level=6,
            primary_strategy=strategy_counter.most_common(1)[0][0],
            fallback_strategies=[name for name, _count in fallback_counter.most_common(3)],
            recovery_playbook={},
            success_rate=round(success_rate, 4),
            confidence=round(min(1.0, 0.6 + success_rate * 0.4), 4),
            sample_size=len(best),
        )
