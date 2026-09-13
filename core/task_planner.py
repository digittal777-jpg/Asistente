from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from core.command_parser import CommandAction, CommandInterpretation
from core.skills import normalize_text


@dataclass
class TaskStep:
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    requires_confirmation: bool = False


@dataclass
class TaskPlan:
    original_command: str
    intent: str
    goal: str
    topic: str = ""
    document_app: str = ""
    browser: str = ""
    result_count: int = 5
    autonomous: bool = False
    steps: List[TaskStep] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TaskPlanner:
    """Planificador simple para tareas complejas y multi-paso."""

    RESEARCH_VERBS = (
        "investiga",
        "investigar",
        "averigua",
        "busca informacion sobre",
        "busca info sobre",
        "informate sobre",
    )

    DOCUMENT_HINTS = ("documento", "word", "libreoffice", "writer", "resumen")

    def __init__(self, config: Any, memory_store: Any) -> None:
        self.config = config
        self.memory_store = memory_store

    def should_plan(self, command: str, interpretation: Optional[CommandInterpretation] = None) -> bool:
        if interpretation and any(
            step.action in {"learn_skill", "practice_skill", "evaluate_skill", "use_skill", "skill_status"}
            for step in interpretation.steps
        ):
            return False
        if interpretation and any(step.action == "execute_complex_task" for step in interpretation.steps):
            return True
        normalized = normalize_text(command)
        if any(verb in normalized for verb in self.RESEARCH_VERBS):
            return True
        return False

    def build_plan(
        self,
        command: str,
        interpretation: Optional[CommandInterpretation] = None,
        vision_context: Optional[Any] = None,
    ) -> TaskPlan:
        if interpretation:
            for step in interpretation.steps:
                if step.action == "execute_complex_task":
                    return self._build_complex_task_plan(command, step.params, vision_context)

        normalized = normalize_text(command)
        if any(verb in normalized for verb in self.RESEARCH_VERBS):
            params = self._extract_research_params(command)
            return self._build_complex_task_plan(command, params, vision_context)

        steps = []
        if interpretation:
            for step in interpretation.steps:
                steps.append(
                    TaskStep(
                        action=step.action,
                        params=step.params,
                        summary=step.summary,
                        requires_confirmation=step.requires_confirmation,
                    )
                )
        return TaskPlan(
            original_command=command,
            intent="sequence",
            goal="Ejecutar secuencia detectada",
            steps=steps,
            notes=["Plan derivado directamente del parser."],
        )

    def summarize_plan(self, plan: TaskPlan) -> str:
        if not plan.steps:
            return "Plan vacio."
        chain = " -> ".join(
            f"{index}. {step.summary or step.action}"
            for index, step in enumerate(plan.steps, start=1)
        )
        return f"Plan ({plan.intent}): {chain}"

    def summarize_text(self, text: str, max_sentences: int = 5) -> str:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        if not cleaned:
            return ""

        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        if len(sentences) <= max_sentences:
            return "\n".join(f"- {sentence.strip()}" for sentence in sentences if sentence.strip())

        stop_words = {
            "de",
            "la",
            "el",
            "y",
            "que",
            "en",
            "a",
            "los",
            "las",
            "por",
            "un",
            "una",
            "to",
            "the",
            "and",
            "of",
            "for",
            "in",
            "is",
            "on",
            "with",
        }

        word_scores: Dict[str, int] = {}
        for token in re.findall(r"[a-zA-ZáéíóúÁÉÍÓÚñÑ0-9]{3,}", cleaned.lower()):
            if token in stop_words:
                continue
            word_scores[token] = word_scores.get(token, 0) + 1

        scored_sentences: List[tuple[int, str]] = []
        for sentence in sentences:
            tokens = re.findall(r"[a-zA-ZáéíóúÁÉÍÓÚñÑ0-9]{3,}", sentence.lower())
            score = sum(word_scores.get(token, 0) for token in tokens)
            if score > 0:
                scored_sentences.append((score, sentence.strip()))

        top_sentences = [
            sentence
            for _score, sentence in sorted(scored_sentences, key=lambda item: item[0], reverse=True)[
                :max_sentences
            ]
        ]
        if not top_sentences:
            top_sentences = [sentence.strip() for sentence in sentences[:max_sentences] if sentence.strip()]
        return "\n".join(f"- {sentence}" for sentence in top_sentences)

    def _build_complex_task_plan(
        self,
        command: str,
        params: Dict[str, Any],
        vision_context: Optional[Any],
    ) -> TaskPlan:
        topic = params.get("topic") or self._extract_research_params(command).get("topic", "")
        document_app = params.get("document_app") or self._preferred_document_app()
        browser = params.get("browser") or self._preferred_browser(vision_context)

        notes = [
            "Raphel intentara reutilizar navegador/ventana existentes antes de abrir otra.",
            "La investigacion usa navegador + captura local del contenido visible.",
        ]

        steps = [
            TaskStep(
                action="ensure_browser",
                params={"browser": browser, "site": "google"},
                summary=f"Preparar navegador {browser} y dejar Google listo",
            ),
            TaskStep(
                action="smart_site_search",
                params={
                    "destination": "google",
                    "query": topic,
                    "browser": browser,
                    "autonomous": True,
                },
                summary=f"Buscar informacion sobre {topic}",
            ),
            TaskStep(
                action="capture_research_summary",
                params={"topic": topic},
                summary="Capturar texto visible y crear un resumen local",
            ),
            TaskStep(
                action="create_document",
                params={
                    "application": document_app,
                    "title": f"Resumen - {topic}",
                    "filename": self._build_filename(topic),
                    "use_last_summary": True,
                },
                summary=f"Crear documento en {document_app} con el resumen",
            ),
        ]

        return TaskPlan(
            original_command=command,
            intent="research_document",
            goal=f"Investigar y documentar: {topic}",
            topic=topic,
            document_app=document_app,
            browser=browser,
            result_count=int(params.get("result_count", 5)),
            autonomous=bool(params.get("autonomous", True)),
            steps=steps,
            notes=notes,
        )

    def _extract_research_params(self, command: str) -> Dict[str, Any]:
        original = command.strip()
        normalized = normalize_text(original)

        document_app = "word"
        if "libreoffice" in normalized or "writer" in normalized:
            document_app = "libreoffice writer"
        elif "notepad" in normalized or "bloc de notas" in normalized:
            document_app = "notepad"

        topic = original
        topic = re.sub(
            r"(?i)\b(?:investiga|investigar|averigua|busca informacion sobre|busca info sobre|informate sobre)\b",
            "",
            topic,
        )
        topic = re.sub(r"(?i)^\s*sobre\s+", "", topic)
        topic = re.sub(
            r"(?i)\b(?:y\s+hazme\s+un\s+documento(?:\s+en\s+\w+)?|y\s+hazme\s+un\s+resumen(?:\s+en\s+\w+)?|y\s+resumelo(?:\s+en\s+\w+)?)\b.*$",
            "",
            topic,
        ).strip(" ,.;:")
        topic = topic or original

        return {
            "topic": topic,
            "document_app": document_app,
            "browser": self.memory_store.get_preference("preferred_browser", "brave"),
            "result_count": 5,
            "autonomous": True,
        }

    def _preferred_browser(self, vision_context: Optional[Any]) -> str:
        if vision_context and getattr(vision_context, "active_app", None) in {"brave", "chrome", "edge", "firefox"}:
            return str(vision_context.active_app)
        return str(self.memory_store.get_preference("preferred_browser", "brave"))

    def _preferred_document_app(self) -> str:
        return str(self.memory_store.get_preference("preferred_document_app", "word"))

    @staticmethod
    def _build_filename(topic: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", normalize_text(topic)).strip("_")
        slug = slug or "documento_raphel"
        return f"{slug}.txt"
