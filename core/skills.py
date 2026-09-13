from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    compact = re.sub(r"\s+", " ", without_accents).strip().lower()
    return compact


@dataclass
class Skill:
    name: str
    description: str
    triggers: List[str] = field(default_factory=list)
    handler: Optional[Callable[..., str]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def execute(self, assistant: Any, **kwargs: Any) -> str:
        if not self.handler:
            raise RuntimeError(f"La skill '{self.name}' no tiene handler configurado.")
        return str(self.handler(assistant, **kwargs))

    def match_score(self, phrase: str) -> float:
        command = normalize_text(phrase)
        best_score = 0.0
        for trigger in self.triggers:
            if not trigger:
                continue
            trigger_score = self._score_trigger(command, trigger)
            if trigger_score > best_score:
                best_score = trigger_score
        return best_score

    def matches(self, phrase: str, threshold: float = 0.72) -> bool:
        return self.match_score(phrase) >= threshold

    def _score_trigger(self, command: str, trigger: str) -> float:
        normalized_trigger = normalize_text(trigger)

        if normalized_trigger.startswith("re:"):
            pattern = normalized_trigger[3:]
            return 1.0 if re.search(pattern, command, flags=re.IGNORECASE) else 0.0

        if command == normalized_trigger:
            return 1.0

        if normalized_trigger and normalized_trigger in command:
            return 0.9

        trigger_words = [word for word in normalized_trigger.split() if len(word) > 2]
        if trigger_words and all(word in command for word in trigger_words):
            return 0.75

        return 0.0


@dataclass
class JsonSkill(Skill):
    steps: List[Dict[str, Any]] = field(default_factory=list)

    def execute(self, assistant: Any, **kwargs: Any) -> str:
        if not self.steps:
            return f"La skill '{self.name}' no tiene pasos."

        messages = []
        for index, step in enumerate(self.steps, start=1):
            action = step.get("action")
            if not action:
                raise ValueError(f"Paso {index} sin 'action' en la skill {self.name}.")
            result = assistant.execute_action(action, step)
            messages.append(f"{index}. {action}: {result}")
        return "\n".join(messages)
