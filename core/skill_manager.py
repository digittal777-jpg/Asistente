from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.logging_utils import ensure_directory
from core.skills import JsonSkill, Skill


def slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip()).strip("_").lower()


class SkillManager:
    def __init__(self, base_dir: Path, assistant: Any) -> None:
        self.base_dir = base_dir
        self.assistant = assistant
        self.skills_dir = base_dir / "skills"
        self.learned_dir = self.skills_dir / "learned"
        ensure_directory(self.learned_dir)
        self._skills: Dict[str, Skill] = {}
        self.reload_skills()

    def reload_skills(self) -> None:
        loaded: Dict[str, Skill] = {}
        for skill in self._load_python_skills():
            loaded[slugify(skill.name)] = skill
        for skill in self._load_json_skills():
            loaded[slugify(skill.name)] = skill
        self._skills = loaded

    def register_skill(self, skill: Skill) -> None:
        self._skills[slugify(skill.name)] = skill

    def learn_new_skill(
        self,
        name: str,
        description: str,
        steps: List[Dict[str, Any]],
        triggers: Optional[List[str]] = None,
    ) -> Path:
        slug = slugify(name)
        payload = {
            "name": name,
            "description": description,
            "triggers": triggers or [name],
            "steps": steps,
        }
        skill_path = self.learned_dir / f"{slug}.json"
        with skill_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        self.reload_skills()
        return skill_path

    def list_skills(self) -> List[Skill]:
        self.reload_skills()
        return sorted(self._skills.values(), key=lambda item: item.name.lower())

    def run_skill(self, name: str, **kwargs: Any) -> str:
        self.reload_skills()
        normalized = slugify(name)
        skill = self._skills.get(normalized)
        if not skill:
            raise KeyError(f"No existe una skill llamada '{name}'.")
        return skill.execute(self.assistant, **kwargs)

    def find_skill_by_trigger(self, command: str) -> Optional[Tuple[Skill, float]]:
        self.reload_skills()
        best_skill: Optional[Skill] = None
        best_score = 0.0
        for skill in self._skills.values():
            score = skill.match_score(command)
            if score > best_score:
                best_skill = skill
                best_score = score
        if best_skill and best_score >= 0.72:
            return best_skill, best_score
        return None

    def _load_python_skills(self) -> List[Skill]:
        skills: List[Skill] = []
        for file_path in self.skills_dir.glob("*.py"):
            if file_path.name.startswith("_") or file_path.name == "__init__.py":
                continue
            skill = self._load_python_skill(file_path)
            if skill:
                skill.metadata.setdefault("kind", "python")
                skill.metadata.setdefault("source", file_path.name)
                skills.append(skill)
        return skills

    def _load_python_skill(self, file_path: Path) -> Optional[Skill]:
        spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
        if not spec or not spec.loader:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if hasattr(module, "build_skill"):
            skill = module.build_skill()
            if isinstance(skill, Skill):
                return skill

        skill = getattr(module, "SKILL", None)
        if isinstance(skill, Skill):
            return skill

        metadata = getattr(module, "SKILL_METADATA", None)
        runner = getattr(module, "run", None)
        if metadata and callable(runner):
            return Skill(
                name=metadata["name"],
                description=metadata["description"],
                triggers=metadata.get("triggers", [metadata["name"]]),
                handler=runner,
                metadata={"kind": "python", "source": file_path.name},
            )
        return None

    def _load_json_skills(self) -> List[Skill]:
        skills: List[Skill] = []
        for file_path in self.learned_dir.glob("*.json"):
            with file_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            skills.append(
                JsonSkill(
                    name=payload["name"],
                    description=payload["description"],
                    triggers=payload.get("triggers", [payload["name"]]),
                    steps=payload.get("steps", []),
                    metadata={"kind": "json", "source": file_path.name},
                )
            )
        return skills
