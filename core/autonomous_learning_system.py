from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from core.curriculum_planner import CurriculumPlanner
from core.self_training_orchestrator import SelfTrainingOrchestrator
from core.skills import normalize_text
from core.task_analysis import TaskAnalyzer


class AutonomousLearningSystem:
    """Sistema autonomo: analiza, investiga y se entrena con el loop infinito."""

    RESEARCH_BOOTSTRAP_TEMPLATES: Dict[str, List[Dict[str, Any]]] = {
        "default": [
            {"base_scenario_id": "research_single_source", "level": 0, "target_level": 1},
            {"base_scenario_id": "research_multi_query", "level": 1, "target_level": 2},
            {"base_scenario_id": "research_structured_extract", "level": 2, "target_level": 3},
        ],
        "game": [
            {"base_scenario_id": "research_single_source", "level": 0, "target_level": 1},
            {"base_scenario_id": "research_multi_query", "level": 1, "target_level": 2},
            {"base_scenario_id": "research_structured_extract", "level": 2, "target_level": 3},
            {"base_scenario_id": "research_to_document", "level": 3, "target_level": 3, "create_document": True},
        ],
        "research": [
            {"base_scenario_id": "research_single_source", "level": 0, "target_level": 1},
            {"base_scenario_id": "research_multi_query", "level": 1, "target_level": 2},
            {"base_scenario_id": "research_cross_verify", "level": 3, "target_level": 3, "create_document": True},
        ],
    }

    def __init__(
        self,
        infinite_loop: Any,
        assistant: Optional[Any] = None,
        task_executor: Optional[Any] = None,
        logger: Optional[Any] = None,
    ) -> None:
        self.infinite_loop = infinite_loop
        self.assistant = assistant
        self.task_executor = task_executor
        self.logger = logger
        self.analyzer = TaskAnalyzer()
        self.planner = CurriculumPlanner()
        self.orchestrator = SelfTrainingOrchestrator(infinite_loop, self.planner, logger=logger)
        self.learning_history: List[Dict[str, Any]] = []
        self.objectives_completed: List[str] = []

    def learn(self, objective: str, use_research: bool = True) -> Dict[str, Any]:
        objective = str(objective or "").strip()
        task_analysis = self.analyzer.analyze_task(objective)
        knowledge_assets: List[dict] = []
        research_bootstrap: Dict[str, Any] = {"topics": [], "loop_sessions": [], "fallback_used": False}

        if use_research:
            knowledge_assets, research_bootstrap = self._collect_research_assets(objective, task_analysis)

        if not isinstance(task_analysis.knowledge_base, dict):
            task_analysis.knowledge_base = {}
        task_analysis.knowledge_base["knowledge_assets"] = knowledge_assets[:5]
        task_analysis.knowledge_base["research_bootstrap"] = research_bootstrap

        result = self.orchestrator.learn(objective, task_analysis, knowledge_assets)
        result["knowledge_assets_collected"] = len(knowledge_assets)
        result["research_bootstrap"] = research_bootstrap
        history_entry = {
            "objective": objective,
            "timestamp": int(time.time()),
            "result": result,
        }
        self.learning_history.append(history_entry)
        if result.get("success"):
            self.objectives_completed.append(objective)
        return result

    def preview_curriculum(self, objective: str) -> Dict[str, Any]:
        analysis = self.analyzer.analyze_task(objective)
        curriculum = self.planner.create_curriculum(analysis, [])
        return {"analysis": analysis, "curriculum": curriculum}

    def get_learning_status(self) -> Dict[str, Any]:
        total_sessions = sum(int(item["result"].get("total_sessions", 0)) for item in self.learning_history)
        total_hours = sum(float(item["result"].get("total_hours", 0.0)) for item in self.learning_history)
        average_success_rate = (
            sum(float(item["result"]["progress"].success_rate) for item in self.learning_history) / len(self.learning_history)
            if self.learning_history
            else 0.0
        )
        return {
            "objectives_completed": list(self.objectives_completed),
            "learning_history_count": len(self.learning_history),
            "total_sessions": total_sessions,
            "total_hours": total_hours,
            "average_success_rate": average_success_rate,
        }

    def _collect_research_assets(
        self,
        objective: str,
        task_analysis: Any,
    ) -> tuple[List[dict], Dict[str, Any]]:
        topics = self._research_topics(objective, task_analysis)
        bootstrap = {
            "topics": topics,
            "loop_sessions": [],
            "fallback_used": False,
        }
        if not topics:
            return [], bootstrap

        loop_assets = self._loop_research_assets(task_analysis, topics, bootstrap)
        combined_assets = list(loop_assets)
        if len(combined_assets) < 2:
            fallback_assets = self._direct_research_assets(
                topics,
                covered_topics={str(item.get("topic", "")) for item in combined_assets},
            )
            if fallback_assets:
                bootstrap["fallback_used"] = True
                bootstrap["fallback_assets"] = len(fallback_assets)
                combined_assets.extend(fallback_assets)
        bootstrap["knowledge_assets"] = len(combined_assets)
        return combined_assets[:6], bootstrap

    def _loop_research_assets(
        self,
        task_analysis: Any,
        topics: List[str],
        bootstrap: Dict[str, Any],
    ) -> List[dict]:
        runner = getattr(self.infinite_loop, "run_one_cycle", None)
        if not callable(runner):
            return []

        scenarios = self._research_bootstrap_scenarios(task_analysis, topics)
        assets: List[dict] = []
        for scenario in scenarios:
            session_record = {
                "topic": scenario.get("training_goal", ""),
                "scenario_id": scenario.get("scenario_id", ""),
                "base_scenario_id": scenario.get("base_scenario_id", ""),
            }
            try:
                result = runner(
                    preferred_domain="research",
                    forced_scenario=scenario,
                    forced_skill_id="skill:investigar",
                )
            except Exception as exc:
                if self.logger:
                    try:
                        self.logger.warning(f"Bootstrap de research fallo para {session_record['topic']}: {exc}")
                    except Exception:
                        pass
                session_record.update({"verified": False, "status": "failure", "error": str(exc)})
                bootstrap["loop_sessions"].append(session_record)
                continue

            session_record.update(
                {
                    "verified": bool(getattr(result, "verified", False)),
                    "status": str(getattr(result, "status", "")),
                    "session_id": str(getattr(result, "session_id", "")),
                }
            )
            asset = self._knowledge_asset_from_result(str(scenario.get("training_goal", "")), scenario, result)
            if asset:
                assets.append(asset)
                session_record["knowledge_asset"] = {
                    "summary": str(asset.get("summary", ""))[:180],
                    "useful_source_count": int(asset.get("useful_source_count", 0) or 0),
                }
            bootstrap["loop_sessions"].append(session_record)
        return assets

    def _direct_research_assets(self, topics: List[str], covered_topics: set[str]) -> List[dict]:
        if not self.task_executor or not hasattr(self.task_executor, "perform_research"):
            return []

        assets: List[dict] = []
        for topic in topics[:4]:
            if topic in covered_topics:
                continue
            try:
                research = self.task_executor.perform_research(topic=topic, browser="brave", result_count=3)
            except TypeError:
                research = self.task_executor.perform_research(topic, browser="brave", result_count=3)
            except Exception as exc:
                if self.logger:
                    try:
                        self.logger.warning(f"Fallback de research directo fallo para {topic}: {exc}")
                    except Exception:
                        pass
                research = None
            if not isinstance(research, dict):
                continue
            normalized = self._normalize_research_asset(dict(research), verification_source="direct_research_fallback")
            normalized.setdefault("topic", topic)
            if self._asset_has_verified_substance(normalized):
                assets.append(normalized)
        return assets

    def _research_topics(self, objective: str, task_analysis: Any) -> List[str]:
        family = self._analysis_family(task_analysis)
        objective_type = str(getattr(task_analysis, "objective_type", "") or "").strip()
        base_topic = objective_type if objective_type and objective_type != "generic" else objective
        engine = getattr(self.infinite_loop, "learning_skill_engine", None)
        query_builder = getattr(engine, "_draft_research_queries", None)

        candidates: List[str] = []
        if callable(query_builder):
            candidates.extend(query_builder(base_topic, family))
            candidates.extend(list(getattr(task_analysis, "required_knowledge", []) or [])[:3])
        else:
            candidates.extend([base_topic, *(list(getattr(task_analysis, "required_knowledge", []) or [])[:3])])

        ordered: List[str] = []
        seen: set[str] = set()
        for item in candidates:
            topic = " ".join(str(item or "").strip().split())
            if not topic:
                continue
            normalized = normalize_text(topic)
            if normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(topic)
        return ordered[:6]

    def _research_bootstrap_scenarios(self, task_analysis: Any, topics: List[str]) -> List[dict]:
        family = self._analysis_family(task_analysis)
        templates = self.RESEARCH_BOOTSTRAP_TEMPLATES.get(family, self.RESEARCH_BOOTSTRAP_TEMPLATES["default"])
        scenarios: List[dict] = []
        for index, template in enumerate(templates):
            topic = topics[min(index, len(topics) - 1)]
            base_scenario_id = str(template.get("base_scenario_id", "research_single_source"))
            topic_slug = normalize_text(topic).replace(" ", "_")[:48] or f"topic_{index + 1}"
            scenarios.append(
                {
                    "objective": f"Investigar {topic}",
                    "training_goal": topic,
                    "skill_id": "skill:investigar",
                    "family": "research",
                    "domain": "research",
                    "scenario_id": f"autonomous_research__{base_scenario_id}__{topic_slug}",
                    "base_scenario_id": base_scenario_id,
                    "level": int(template.get("level", 0) or 0),
                    "target_level": int(template.get("target_level", 1) or 1),
                    "create_document": bool(template.get("create_document")),
                    "verification_rules": {"bootstrap": True, "family": family},
                }
            )
        return scenarios

    @staticmethod
    def _analysis_family(task_analysis: Any) -> str:
        knowledge_base = getattr(task_analysis, "knowledge_base", {})
        if isinstance(knowledge_base, dict):
            family = str(knowledge_base.get("family", "") or "").strip()
            if family:
                return family
        objective_type = str(getattr(task_analysis, "objective_type", "") or "").strip()
        if objective_type in {"minecraft", "terraria"}:
            return "game"
        return "application"

    @staticmethod
    def _knowledge_asset_from_result(topic: str, scenario: Dict[str, Any], result: Any) -> Optional[dict]:
        if not bool(getattr(result, "verified", False)):
            return None
        evidence = dict(getattr(result, "evidence", {}) or {})
        metrics = dict(getattr(result, "metrics", {}) or {})
        reviewed_sources = list(evidence.get("reviewed_sources") or evidence.get("visited_titles") or [])
        summary = str(evidence.get("research_summary") or evidence.get("summary_preview") or "").strip()
        findings = str(evidence.get("research_findings") or "").strip()
        useful_source_count = int(
            evidence.get("useful_source_count", 0)
            or metrics.get("useful_source_count", 0)
            or len(reviewed_sources)
        )
        document_path = str(evidence.get("document_path") or evidence.get("output_path") or "")
        captured_chars = int(evidence.get("captured_chars", 0) or metrics.get("captured_chars", 0) or 0)
        queries_used = [
            str(item).strip()
            for item in (evidence.get("queries_used") or [])
            if str(item).strip()
        ]
        if not summary and not findings and useful_source_count <= 0 and not document_path and captured_chars <= 0:
            return None
        asset = {
            "topic": topic,
            "summary": summary,
            "findings": findings,
            "reviewed_sources": reviewed_sources[:5],
            "queries_used": queries_used[:6],
            "useful_source_count": useful_source_count,
            "captured_chars": captured_chars,
            "document_path": document_path,
            "scenario_id": str(getattr(result, "scenario_id", "")),
            "base_scenario_id": str(evidence.get("base_scenario_id") or scenario.get("base_scenario_id", "")),
            "page_title": str(evidence.get("page_title") or ""),
            "discard_precision": float(metrics.get("discard_precision", 0.0) or evidence.get("discard_precision", 0.0) or 0.0),
            "source_kind": str(evidence.get("source_kind") or "web_page"),
            "transcript_available": bool(evidence.get("transcript_available")),
            "transcript_chars": int(evidence.get("transcript_chars", 0) or 0),
            "visible_text_chars": int(
                evidence.get("visible_text_chars", 0)
                or evidence.get("captured_chars", 0)
                or metrics.get("captured_chars", 0)
                or 0
            ),
            "page_usefulness_label": str(evidence.get("page_usefulness_label") or "unknown"),
            "current_session_verified": bool(evidence.get("current_session_verified", True)),
            "verification_source": str(evidence.get("verification_source") or "loop_research_bootstrap"),
        }
        asset = AutonomousLearningSystem._normalize_research_asset(asset, verification_source=str(asset["verification_source"]))
        if not AutonomousLearningSystem._asset_has_verified_substance(asset):
            return None
        return asset

    @staticmethod
    def _normalize_research_asset(asset: dict, verification_source: str) -> dict:
        normalized = dict(asset or {})
        summary = str(normalized.get("summary", "") or "").strip()
        findings = str(normalized.get("findings", "") or "").strip()
        useful_source_count = int(normalized.get("useful_source_count", 0) or 0)
        transcript_chars = int(normalized.get("transcript_chars", 0) or 0)
        visible_text_chars = int(
            normalized.get("visible_text_chars", 0)
            or normalized.get("captured_chars", 0)
            or len(summary)
            or len(findings)
            or 0
        )
        source_kind = str(normalized.get("source_kind") or "web_page")
        page_usefulness_label = str(normalized.get("page_usefulness_label") or "").strip()
        if not page_usefulness_label:
            if source_kind == "youtube_video":
                page_usefulness_label = "useful" if transcript_chars >= 160 else ("mixed" if visible_text_chars >= 220 else "poor")
            else:
                page_usefulness_label = (
                    "useful"
                    if useful_source_count >= 2 or (useful_source_count >= 1 and (len(summary) >= 20 or len(findings) >= 20))
                    else "mixed" if useful_source_count >= 1 or visible_text_chars >= 220
                    else "poor"
                )
        normalized.update(
            {
                "source_kind": source_kind,
                "transcript_available": bool(normalized.get("transcript_available")),
                "transcript_chars": transcript_chars,
                "visible_text_chars": visible_text_chars,
                "captured_chars": max(transcript_chars, visible_text_chars),
                "page_usefulness_label": page_usefulness_label,
                "verification_source": str(verification_source or normalized.get("verification_source") or "unknown"),
            }
        )
        return normalized

    @staticmethod
    def _research_asset_title_is_ambiguous(title: str) -> bool:
        raw = str(title or "").strip().lower()
        normalized = normalize_text(title)
        if not raw or not normalized:
            return False
        if "sin titulo" in normalized or "untitled" in raw:
            return True
        return raw.startswith("http://") or raw.startswith("https://") or "youtube.com/watch" in raw or "youtu.be/" in raw

    @staticmethod
    def _asset_has_verified_substance(asset: dict) -> bool:
        source_kind = normalize_text(str(asset.get("source_kind", "") or "web_page"))
        useful_source_count = int(asset.get("useful_source_count", 0) or 0)
        transcript_chars = int(asset.get("transcript_chars", 0) or 0)
        visible_text_chars = int(asset.get("visible_text_chars", 0) or asset.get("captured_chars", 0) or 0)
        summary = str(asset.get("summary", "") or "").strip()
        findings = str(asset.get("findings", "") or "").strip()
        label = normalize_text(str(asset.get("page_usefulness_label", "") or ""))
        page_title = str(asset.get("page_title", "") or "")
        document_path = str(asset.get("document_path", "") or "")
        if AutonomousLearningSystem._research_asset_title_is_ambiguous(page_title):
            return False
        if source_kind == "youtube_video":
            if bool(asset.get("transcript_available")) and transcript_chars >= 160:
                return True
            return visible_text_chars >= 220 and label in {"useful", "mixed"}
        if useful_source_count >= 2:
            return True
        if useful_source_count >= 1 and label in {"useful", "mixed"} and (len(summary) >= 20 or len(findings) >= 20):
            return True
        if document_path and (len(summary) >= 20 or len(findings) >= 20):
            return True
        return False
