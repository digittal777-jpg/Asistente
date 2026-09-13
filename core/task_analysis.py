from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List

from core.skill_family_mapping import create_trainable_draft, infer_skill_family
from core.skills import normalize_text


@dataclass
class TaskAnalysisResult:
    primary_objective: str
    objective_type: str
    required_knowledge: List[str]
    required_skills: List[str]
    prerequisites: List[str]
    complexity_score: float
    estimated_learning_days: int
    analysis_timestamp: int
    knowledge_base: Dict[str, object] = field(default_factory=dict)


class TaskAnalyzer:
    """Descompone objetivos en conocimiento, skills y prerequisitos entrenables."""

    TEMPLATE_KNOWLEDGE_TOPICS: Dict[str, List[str]] = {
        "minecraft": [
            "minecraft controles basicos",
            "minecraft primeros recursos",
            "minecraft crafteo basico",
            "minecraft combate basico",
            "minecraft supervivencia temprana",
        ],
        "terraria": [
            "terraria controles basicos",
            "terraria primeros recursos",
            "terraria crafteo basico",
            "terraria combate basico",
            "terraria early game",
        ],
        "web_development": [
            "node.js proyecto basico",
            "servidor web minimo o express",
            "html formulario de suma",
            "javascript para capturar y sumar entradas",
            "pruebas y depuracion de app web basica",
        ],
    }

    OBJECTIVE_TEMPLATES: Dict[str, Dict[str, object]] = {
        "minecraft": {
            "keywords": ["minecraft"],
            "required_skills": [
                "minecraft_movement",
                "minecraft_mining",
                "minecraft_crafting",
                "minecraft_combat",
                "minecraft_survival",
            ],
            "prerequisites": ["skill:mouse", "skill:teclado"],
            "complexity": 0.75,
            "days": 14,
        },
        "terraria": {
            "keywords": ["terraria", "terarria"],
            "required_skills": [
                "terraria_movement",
                "terraria_mining",
                "terraria_crafting",
                "terraria_combat",
                "terraria_boss_fight",
            ],
            "prerequisites": ["skill:mouse", "skill:teclado"],
            "complexity": 0.68,
            "days": 12,
        },
        "python": {
            "keywords": ["python", "programacion", "programming"],
            "required_skills": [
                "python_syntax",
                "python_data_structures",
                "python_functions",
                "python_debugging",
            ],
            "prerequisites": ["skill:teclado", "skill:investigar"],
            "complexity": 0.58,
            "days": 21,
        },
        "web_development": {
            "keywords": [
                "node.js",
                "nodejs",
                "express",
                "aplicacion web",
                "aplicación web",
                "web app",
                "pagina web",
                "página web",
                "sitio web",
                "backend web",
                "frontend web",
            ],
            "required_skills": [
                "nodejs_project_setup",
                "webapp_basic_routes",
                "webapp_sum_ui",
                "webapp_event_handling",
                "webapp_debugging",
            ],
            "prerequisites": ["skill:teclado", "skill:investigar"],
            "complexity": 0.64,
            "days": 18,
        },
        "web_automation": {
            "keywords": ["web", "automation", "browser", "formulario", "navegador"],
            "required_skills": [
                "browser_navigation",
                "form_filling",
                "data_extraction",
                "error_recovery",
            ],
            "prerequisites": ["skill:mouse", "skill:teclado", "skill:investigar"],
            "complexity": 0.6,
            "days": 10,
        },
        "desktop_organization": {
            "keywords": ["escritorio", "desktop", "archivos", "folders", "carpetas"],
            "required_skills": [
                "desktop_first_drag",
                "file_verification",
                "selection_recovery",
            ],
            "prerequisites": ["skill:mouse", "skill:investigar"],
            "complexity": 0.48,
            "days": 7,
        },
    }

    FAMILY_PREREQUISITES: Dict[str, List[str]] = {
        "vision": ["skill:visualizacion"],
        "research": ["skill:investigar", "skill:teclado"],
        "browser": ["skill:mouse", "skill:teclado"],
        "file_manager": ["skill:mouse"],
        "documents": ["skill:teclado"],
        "application": ["skill:mouse", "skill:teclado"],
        "game": ["skill:mouse", "skill:teclado"],
    }

    FAMILY_COMPLEXITY: Dict[str, float] = {
        "vision": 0.45,
        "research": 0.7,
        "browser": 0.5,
        "file_manager": 0.45,
        "documents": 0.4,
        "application": 0.5,
        "game": 0.8,
    }

    FAMILY_DAYS: Dict[str, int] = {
        "vision": 10,
        "research": 14,
        "browser": 7,
        "file_manager": 7,
        "documents": 7,
        "application": 10,
        "game": 21,
    }

    def analyze_task(self, objective: str) -> TaskAnalysisResult:
        objective = str(objective or "").strip()
        normalized = normalize_text(objective)
        objective_type = self._detect_objective_type(normalized)
        template = self.OBJECTIVE_TEMPLATES.get(objective_type)

        if template:
            required_skills = [str(item) for item in template["required_skills"]]
            prerequisites = [str(item) for item in template["prerequisites"]]
            complexity = float(template["complexity"])
            days = int(template["days"])
            knowledge = list(self.TEMPLATE_KNOWLEDGE_TOPICS.get(objective_type, self._extract_knowledge_topics(required_skills)))
            knowledge_base = {
                "template_type": objective_type,
                "family": infer_skill_family(objective_type, objective, objective),
            }
            return TaskAnalysisResult(
                primary_objective=objective,
                objective_type=objective_type,
                required_knowledge=knowledge,
                required_skills=required_skills,
                prerequisites=prerequisites,
                complexity_score=complexity,
                estimated_learning_days=days,
                analysis_timestamp=int(time.time()),
                knowledge_base=knowledge_base,
            )

        return self._generic_analysis(objective)

    def _detect_objective_type(self, normalized_objective: str) -> str:
        if self._looks_like_web_development_objective(normalized_objective):
            return "web_development"
        for objective_type, template in self.OBJECTIVE_TEMPLATES.items():
            keywords = [normalize_text(str(item)) for item in template.get("keywords", [])]
            if any(keyword and keyword in normalized_objective for keyword in keywords):
                return objective_type
        return "generic"

    @staticmethod
    def _looks_like_web_development_objective(normalized_objective: str) -> bool:
        build_verbs = (
            "hacer",
            "crear",
            "construir",
            "desarrollar",
            "programar",
            "codificar",
        )
        web_terms = (
            "node.js",
            "nodejs",
            "express",
            "aplicacion web",
            "web app",
            "pagina web",
            "sitio web",
            "backend",
            "frontend",
        )
        if any(term in normalized_objective for term in ("node.js", "nodejs", "express")):
            return True
        return any(verb in normalized_objective for verb in build_verbs) and any(
            term in normalized_objective for term in web_terms
        )

    @staticmethod
    def _extract_knowledge_topics(required_skills: List[str]) -> List[str]:
        topics: List[str] = []
        for skill in required_skills:
            topic = str(skill).replace("_", " ").strip()
            if topic:
                topics.append(topic)
        return topics

    def _generic_analysis(self, objective: str) -> TaskAnalysisResult:
        family = infer_skill_family(objective, objective, objective)
        draft = create_trainable_draft(
            skill_id=normalize_text(objective).replace(" ", "_") or "generic_skill",
            skill_name=objective,
            description=objective,
            family=family,
        )
        required_skills = [str(draft.skill_id or normalize_text(objective).replace(" ", "_") or "generic_task_skill")]
        return TaskAnalysisResult(
            primary_objective=objective,
            objective_type="generic",
            required_knowledge=[objective, f"{objective} guide", f"{objective} workflow"],
            required_skills=required_skills,
            prerequisites=self._draft_prerequisites(family),
            complexity_score=float(self.FAMILY_COMPLEXITY.get(family, 0.5)),
            estimated_learning_days=int(self.FAMILY_DAYS.get(family, 7)),
            analysis_timestamp=int(time.time()),
            knowledge_base={
                "family": family,
                "trainable_draft": draft.to_dict(),
            },
        )

    def _draft_prerequisites(self, family: str) -> List[str]:
        defaults = list(self.FAMILY_PREREQUISITES.get(family, ["skill:mouse", "skill:teclado"]))
        filtered = [item for item in defaults if item != "skill:investigar"]
        return filtered or ["skill:mouse", "skill:teclado"]
