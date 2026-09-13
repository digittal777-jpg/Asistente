from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from core.skill_family_mapping import create_trainable_draft, infer_skill_family
from core.skills import normalize_text
from core.task_analysis import TaskAnalysisResult


@dataclass
class Phase:
    phase_id: str
    name: str
    description: str
    skills: List[str]
    scenarios: List[dict]
    target_level: int
    prerequisites: List[str]
    estimated_days: int
    success_criteria: Dict[str, object] = field(default_factory=dict)


@dataclass
class Curriculum:
    objective: str
    phases: List[Phase]
    total_estimated_days: int
    success_criteria: List[dict]
    curriculum_version: int
    created_date: int
    dependency_graph: Dict[str, List[str]]


class CurriculumPlanner:
    """Ordena skills por dependencias y genera escenarios por fase."""

    SKILL_SCENARIO_OVERRIDES: Dict[str, List[dict]] = {
        "minecraft_movement": [
            {"scenario_id": "game_input_foundation", "level": 0},
            {"scenario_id": "game_control_lookup", "level": 1},
        ],
        "minecraft_mining": [
            {"scenario_id": "game_control_lookup", "level": 1},
            {"scenario_id": "game_goal_chain", "level": 4},
        ],
        "minecraft_crafting": [
            {"scenario_id": "game_control_lookup", "level": 1},
            {"scenario_id": "game_goal_chain", "level": 4},
        ],
        "minecraft_combat": [
            {"scenario_id": "game_control_lookup", "level": 1},
            {"scenario_id": "game_goal_chain", "level": 4},
        ],
        "minecraft_survival": [
            {"scenario_id": "game_control_lookup", "level": 1},
            {"scenario_id": "game_goal_chain", "level": 4},
        ],
        "terraria_movement": [
            {"scenario_id": "game_input_foundation", "level": 0},
            {"scenario_id": "game_control_lookup", "level": 1},
        ],
        "terraria_mining": [
            {"scenario_id": "game_control_lookup", "level": 1},
            {"scenario_id": "game_goal_chain", "level": 4},
        ],
        "terraria_crafting": [
            {"scenario_id": "game_control_lookup", "level": 1},
            {"scenario_id": "game_goal_chain", "level": 4},
        ],
        "terraria_combat": [
            {"scenario_id": "game_control_lookup", "level": 1},
            {"scenario_id": "game_goal_chain", "level": 4},
        ],
        "terraria_boss_fight": [
            {"scenario_id": "game_control_lookup", "level": 1},
            {"scenario_id": "game_goal_chain", "level": 4},
        ],
        "desktop_first_drag": [
            {"scenario_id": "desktop_drag_constrained", "level": 2},
            {"scenario_id": "desktop_drag_no_fallback", "level": 2},
        ],
        "selection_recovery": [
            {"scenario_id": "desktop_recovery_verified", "level": 4},
            {"scenario_id": "desktop_adversarial_verify", "level": 5},
        ],
        "file_verification": [
            {"scenario_id": "explorer_move_verified", "level": 3},
            {"scenario_id": "desktop_autonomous_discovery", "level": 5},
        ],
        "browser_navigation": [
            {"scenario_id": "browser_open_google", "level": 0},
            {"scenario_id": "browser_search_result", "level": 2},
        ],
        "form_filling": [
            {"scenario_id": "browser_search_result", "level": 2},
            {"scenario_id": "browser_form_fill", "level": 3},
        ],
        "data_extraction": [
            {"scenario_id": "browser_search_result", "level": 2},
            {"scenario_id": "browser_form_fill", "level": 3},
        ],
    }

    SKILL_DEPENDENCIES: Dict[str, List[str]] = {
        "minecraft_movement": [],
        "minecraft_mining": ["minecraft_movement"],
        "minecraft_crafting": ["minecraft_mining"],
        "minecraft_combat": ["minecraft_movement", "minecraft_crafting"],
        "minecraft_survival": ["minecraft_movement", "minecraft_mining", "minecraft_crafting"],
        "terraria_movement": [],
        "terraria_mining": ["terraria_movement"],
        "terraria_crafting": ["terraria_mining"],
        "terraria_combat": ["terraria_movement", "terraria_crafting"],
        "terraria_boss_fight": ["terraria_combat", "terraria_mining"],
        "python_syntax": [],
        "python_data_structures": ["python_syntax"],
        "python_functions": ["python_syntax"],
        "python_debugging": ["python_functions"],
        "browser_navigation": [],
        "form_filling": ["browser_navigation"],
        "data_extraction": ["browser_navigation"],
        "error_recovery": ["browser_navigation"],
        "desktop_first_drag": ["skill:mouse"],
        "selection_recovery": ["desktop_first_drag"],
        "file_verification": ["desktop_first_drag"],
    }

    PHASE_LABELS = {
        0: ("phase_foundation", "Fundacion", "Base de control, foco y reconocimiento"),
        1: ("phase_core", "Core", "Operacion practica de la habilidad"),
        2: ("phase_mastery", "Mastery", "Integracion y verificacion real"),
    }

    def create_curriculum(
        self,
        task_analysis: TaskAnalysisResult,
        knowledge_assets: List[dict] | None = None,
    ) -> Curriculum:
        ordered_skills, dependency_graph, depth_map = self._topological_order(task_analysis.required_skills)
        grouped = self._group_by_phase(ordered_skills, depth_map)
        phases: List[Phase] = []

        for phase_index, skills in grouped:
            phase_id, phase_name, description = self.PHASE_LABELS.get(
                phase_index,
                (f"phase_{phase_index}", f"Phase {phase_index}", "Fase generada automaticamente"),
            )
            scenarios = self._phase_scenarios(skills, phase_index, knowledge_assets or [])
            phases.append(
                Phase(
                    phase_id=phase_id,
                    name=phase_name,
                    description=description,
                    skills=skills,
                    scenarios=scenarios,
                    target_level=min(6, max(1, phase_index + 2)),
                    prerequisites=self._phase_prerequisites(skills),
                    estimated_days=max(1, len(skills) * (phase_index + 1)),
                    success_criteria={
                        "min_verified_scenarios": max(2, len(scenarios)),
                        "target_level": min(6, max(1, phase_index + 2)),
                    },
                )
            )

        return Curriculum(
            objective=task_analysis.primary_objective,
            phases=phases,
            total_estimated_days=max(task_analysis.estimated_learning_days, sum(phase.estimated_days for phase in phases)),
            success_criteria=[phase.success_criteria for phase in phases],
            curriculum_version=1,
            created_date=int(time.time()),
            dependency_graph=dependency_graph,
        )

    def _topological_order(self, skills: List[str]) -> Tuple[List[str], Dict[str, List[str]], Dict[str, int]]:
        normalized_skills = [str(skill) for skill in skills]
        graph: Dict[str, List[str]] = {}
        indegree: Dict[str, int] = {}
        depth: Dict[str, int] = {}

        for skill in normalized_skills:
            dependencies = list(self.SKILL_DEPENDENCIES.get(skill, []))
            graph[skill] = dependencies
            indegree.setdefault(skill, 0)
            depth.setdefault(skill, 0)
            for dependency in dependencies:
                indegree.setdefault(dependency, 0)
                depth.setdefault(dependency, 0)
                indegree[skill] = indegree.get(skill, 0) + 1

        reverse: Dict[str, List[str]] = defaultdict(list)
        for skill, dependencies in graph.items():
            for dependency in dependencies:
                reverse[dependency].append(skill)

        queue = deque(sorted(skill for skill, degree in indegree.items() if degree == 0))
        ordered: List[str] = []
        while queue:
            node = queue.popleft()
            ordered.append(node)
            for dependent in reverse.get(node, []):
                indegree[dependent] -= 1
                depth[dependent] = max(depth.get(dependent, 0), depth.get(node, 0) + 1)
                if indegree[dependent] == 0:
                    queue.append(dependent)

        if len(ordered) != len(indegree):
            cycle_nodes = [skill for skill, degree in indegree.items() if degree > 0]
            raise ValueError(f"Curriculum invalido: dependencias ciclicas detectadas en {cycle_nodes}")

        ordered_filtered = [skill for skill in ordered if skill in normalized_skills]
        return ordered_filtered, graph, depth

    def _group_by_phase(self, ordered_skills: List[str], depth_map: Dict[str, int]) -> List[Tuple[int, List[str]]]:
        buckets: Dict[int, List[str]] = defaultdict(list)
        for skill in ordered_skills:
            depth = int(depth_map.get(skill, 0))
            if depth <= 0:
                phase_index = 0
            elif depth == 1:
                phase_index = 1
            else:
                phase_index = 2
            buckets[phase_index].append(skill)
        return sorted((phase_index, skills) for phase_index, skills in buckets.items() if skills)

    def _phase_scenarios(self, skills: List[str], phase_index: int, knowledge_assets: List[dict]) -> List[dict]:
        scenarios: List[dict] = []
        for skill in skills:
            family = infer_skill_family(skill, skill, skill)
            draft = create_trainable_draft(skill, skill.replace("_", " "), skill, family=family)
            templates = self.SKILL_SCENARIO_OVERRIDES.get(skill, [dict(item) for item in draft.scenario_templates[:2]])
            for template in templates:
                base_scenario_id = str(template.get("scenario_id", f"{skill}_phase_{phase_index}"))
                scenarios.append(
                    {
                        "objective": f"Entrenar {skill.replace('_', ' ')}",
                        "training_goal": self._scenario_training_goal(skill, base_scenario_id),
                        "skill_id": skill,
                        "family": family,
                        "domain": self._scenario_runtime_domain(base_scenario_id, family),
                        "scenario_id": self._skill_specific_scenario_id(skill, base_scenario_id),
                        "base_scenario_id": base_scenario_id,
                        "level": int(template.get("level", 0) or 0),
                        "target_level": min(6, max(1, phase_index + 2)),
                        "min_sessions": 2 if phase_index == 0 else 3,
                        "verification_rules": draft.verification_rules,
                        "knowledge_assets": knowledge_assets[:3],
                    }
                )
            if not draft.scenario_templates:
                scenarios.append(
                    {
                        "objective": f"Entrenar {skill.replace('_', ' ')}",
                        "training_goal": self._scenario_training_goal(skill, f"{normalize_text(skill).replace(' ', '_')}_generic"),
                        "skill_id": skill,
                        "family": family,
                        "domain": self._scenario_runtime_domain("", family),
                        "scenario_id": f"{normalize_text(skill).replace(' ', '_')}__generic",
                        "base_scenario_id": f"{normalize_text(skill).replace(' ', '_')}_generic",
                        "level": 0,
                        "target_level": min(6, max(1, phase_index + 2)),
                        "min_sessions": 2,
                        "verification_rules": draft.verification_rules,
                        "knowledge_assets": knowledge_assets[:3],
                    }
                )
        return scenarios

    def _phase_prerequisites(self, skills: List[str]) -> List[str]:
        seen: List[str] = []
        for skill in skills:
            for dependency in self.SKILL_DEPENDENCIES.get(skill, []):
                if dependency not in skills and dependency not in seen:
                    seen.append(dependency)
        return seen

    @staticmethod
    def _skill_specific_scenario_id(skill: str, base_scenario_id: str) -> str:
        skill_slug = normalize_text(skill).replace(" ", "_") or "skill"
        base_slug = normalize_text(base_scenario_id).replace(" ", "_") or "scenario"
        return f"{skill_slug}__{base_slug}"

    @staticmethod
    def _scenario_runtime_domain(base_scenario_id: str, family: str) -> str:
        normalized = normalize_text(base_scenario_id)
        if normalized.startswith("research"):
            return "research"
        if normalized.startswith("browser"):
            return "browser"
        if normalized.startswith("explorer"):
            return "file_manager/explorer"
        if normalized.startswith("document"):
            return "document_editor"
        if normalized.startswith("application"):
            return "application_workflow"
        if normalized.startswith("game"):
            return "game_foundation"
        if normalized.startswith("desktop"):
            return "selection/workflow"
        if normalized.startswith("ui detect") or normalized.startswith("mouse click") or normalized.startswith("ocr partial"):
            return "vision/detection"

        fallback = {
            "vision": "vision/detection",
            "research": "research",
            "browser": "browser",
            "file_manager": "file_manager/explorer",
            "documents": "document_editor",
            "application": "application_workflow",
            "game": "game_foundation",
        }
        return fallback.get(family, "application_workflow")

    @staticmethod
    def _scenario_training_goal(skill: str, base_scenario_id: str) -> str:
        normalized_skill = normalize_text(skill)
        if "minecraft" in normalized_skill or "terraria" in normalized_skill:
            game_name = "minecraft" if "minecraft" in normalized_skill else "terraria"
            if "movement" in normalized_skill:
                return f"{game_name} movimiento y controles basicos"
            if "mining" in normalized_skill:
                return f"{game_name} minar recursos basicos"
            if "crafting" in normalized_skill:
                return f"{game_name} craftear objetos basicos"
            if "combat" in normalized_skill:
                return f"{game_name} combate basico y respuesta segura"
            if "survival" in normalized_skill:
                return f"{game_name} supervivencia temprana y prioridades"
            if "boss" in normalized_skill:
                return f"{game_name} preparacion para jefe y recuperacion"
            return f"{game_name} controles basicos"
        if skill == "desktop_first_drag":
            return "drag seguro y verificado"
        if skill == "selection_recovery":
            return "recuperacion de seleccion y reintentos seguros"
        if skill == "file_verification":
            return "verificar resultado real del archivo"
        if base_scenario_id.startswith("research_"):
            return skill.replace("_", " ")
        return skill.replace("_", " ")
