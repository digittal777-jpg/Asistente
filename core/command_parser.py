from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.data_paths import DataPaths
from core.logging_utils import ensure_directory
from core.skills import normalize_text

try:
    from rapidfuzz import fuzz, process

    RAPIDFUZZ_AVAILABLE = True
except ImportError:  # pragma: no cover - fallback local
    from difflib import SequenceMatcher

    RAPIDFUZZ_AVAILABLE = False


@dataclass
class CommandAction:
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    requires_confirmation: bool = False
    intent: str = ""


@dataclass
class CommandInterpretation:
    original: str
    steps: List[CommandAction] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    matched_feedback: bool = False


@dataclass
class EntityMatch:
    canonical: str
    alias: str
    score: float
    url: Optional[str] = None


@dataclass
class ParserContext:
    active_browser: Optional[str] = None
    active_app: Optional[str] = None
    active_site: Optional[str] = None
    active_window: Optional[str] = None
    browser_private: bool = False


_DEFAULT_PARSER: Optional["CommandParser"] = None


class CommandParser:
    """Interprete avanzado y tolerante a lenguaje natural para Raphel."""

    ACTION_BOUNDARY_HINTS = (
        "abre",
        "abreme",
        "abrir",
        "organiza",
        "ordena",
        "aprende",
        "entrena",
        "ensena",
        "haz",
        "entra",
        "ve",
        "ir",
        "anda",
        "d[eé]jame",
        "b(?:usca(?:me)?|[uú]scame)",
        "pon",
        "ponme",
        "reproduce",
        "quiero",
        "investiga",
        "averigua",
        "escribe",
        "cierra",
        "minimiza",
        "maximiza",
        "sube",
        "baja",
    )

    DEFAULT_SITE_ALIASES: Dict[str, str] = {
        "youtube": "https://www.youtube.com",
        "gmail": "https://mail.google.com",
        "google": "https://www.google.com",
        "github": "https://github.com",
        "spotify": "https://open.spotify.com",
        "netflix": "https://www.netflix.com",
        "twitch": "https://www.twitch.tv",
        "word": "https://www.office.com/launch/word",
    }

    BROWSER_NAMES = {"brave", "chrome", "edge", "firefox"}
    COMPLEX_TASK_HINTS = ("investiga", "investigar", "averigua", "resumen", "documento")

    def __init__(self, base_dir: Path, config: Any, skill_manager: Any) -> None:
        self.base_dir = base_dir
        self.paths = DataPaths.from_base_dir(base_dir)
        self.config = config
        self.skill_manager = skill_manager
        self.feedback_path = self.paths.command_feedback_path
        ensure_directory(self.feedback_path.parent)

    def interpret_command(
        self,
        command: str,
        vision_context: Optional[Any] = None,
    ) -> CommandInterpretation:
        original = command.strip()
        interpretation = CommandInterpretation(original=original)
        if not original:
            interpretation.notes.append("Comando vacio.")
            return interpretation

        if learned := self._match_feedback_pattern(original):
            interpretation.steps = learned[0]
            interpretation.notes.append(learned[1])
            interpretation.matched_feedback = True
            return interpretation

        context = self._seed_context_from_vision(vision_context)
        input_training_action = self._parse_input_training_loop_intent(original)
        if input_training_action:
            interpretation.steps.append(input_training_action)
            return interpretation
        learning_action = self._parse_learning_skill_intent(original, context)
        if learning_action:
            interpretation.steps.append(learning_action)
            return interpretation
        complex_action = self._parse_complex_task(original, context)
        if complex_action:
            interpretation.steps.append(complex_action)
            return interpretation

        clauses = self._split_into_clauses(original)
        for clause in clauses:
            actions = self._parse_clause(clause, context)
            if actions:
                interpretation.steps.extend(actions)

        if not interpretation.steps:
            skill_match = self.skill_manager.find_skill_by_trigger(original)
            if skill_match:
                skill, score = skill_match
                interpretation.steps.append(
                    CommandAction(
                        action="run_skill",
                        params={"name": skill.name},
                        summary=f"Ejecutar skill '{skill.name}'",
                        intent="skill",
                    )
                )
                interpretation.notes.append(f"Skill activada por trigger con score {score:.2f}.")

        if not interpretation.steps:
            interpretation.notes.append("No se detectaron intenciones accionables.")
        return interpretation

    def learn_from_feedback(
        self,
        user_command: str,
        correct_actions: Sequence[Dict[str, Any] | CommandAction],
    ) -> Path:
        patterns = self._load_feedback_patterns()
        normalized = normalize_text(user_command)
        serialized = [self._serialize_action(item) for item in correct_actions]
        patterns[normalized] = {
            "user_command": user_command,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "actions": serialized,
        }
        with self.feedback_path.open("w", encoding="utf-8") as handle:
            json.dump(patterns, handle, indent=2, ensure_ascii=False)
        return self.feedback_path

    def summarize_interpretation(self, interpretation: CommandInterpretation) -> str:
        if not interpretation.steps:
            note = interpretation.notes[0] if interpretation.notes else "Sin plan."
            return f"Sin plan claro. {note}"

        parts = []
        for index, step in enumerate(interpretation.steps, start=1):
            parts.append(f"{index}. {step.summary or step.action}")
        return "Plan detectado: " + " -> ".join(parts)

    @staticmethod
    def supported_examples() -> List[str]:
        return [
            "Abre YouTube y búscame ponk",
            "Abre Brave, entra a YouTube y busca 'That Time I Got Reincarnated as a Slime'",
            "Abre Spotify y pon música de anime",
            "Abre Visual Studio Code y abre el proyecto de Raphel",
            "Abre Chrome en incógnito y ve a gmail",
            "Búscame ponk en YouTube",
            "Pon música relajante de anime en Spotify",
            "Abre Brave y déjame YouTube",
            "Abre Firefox y busca noticias de tecnología",
            "Abre Edge, entra a GitHub y escribe en la pestaña actual: repo Raphel",
            "Escribe en la pestaña actual: hola maestro",
            "Cierra la ventana actual y abre Chrome en incógnito",
            "Minimiza todas las ventanas y abre Brave",
            "Sube el volumen al 80%",
            "Investiga sobre Rimuru Tempest y hazme un documento en Word",
            "Aprende a usar el teclado",
            "Aprende a usar YouTube",
            "Practica investigar 10 minutos",
            "Evalua uso de YouTube",
            "Usa investigar para averiguar Rimuru Tempest",
            "Ordena mi escritorio",
            "Practica el mouse en el escritorio",
            "Aprende este icono como Brave",
            "Haz click en el icono de Brave",
            "Abre el icono de Spotify",
        ]

    def _parse_clause(self, clause: str, context: ParserContext) -> List[CommandAction]:
        original = clause.strip(" ,;")
        normalized = normalize_text(original)
        if not original:
            return []

        if self._is_minimize_all(normalized):
            return [self._action("minimize_all_windows", {}, "Minimizar todas las ventanas", "window")]

        if self._is_maximize_current(normalized):
            return [self._action("maximize_current_window", {}, "Maximizar la ventana actual", "window")]

        if self._is_close_current(normalized):
            return [
                self._action(
                    "close_current_window",
                    {},
                    "Cerrar la ventana actual",
                    "window",
                    requires_confirmation=True,
                )
            ]

        if volume := self._parse_volume_clause(original, normalized):
            return volume

        if desktop_actions := self._parse_desktop_clause(original, normalized):
            return desktop_actions

        if match := re.match(
            r"^(?:abre|abreme|abrir)\s+(?:la\s+)?carpeta(?:\s+de)?\s+(.+)$",
            original,
            flags=re.IGNORECASE,
        ):
            target = match.group(1).strip()
            return [self._action("open_folder", {"target": target}, f"Abrir carpeta {target}", "folder")]

        if match := re.match(
            r"^(?:abre|abreme|abrir)\s+(?:el\s+)?proyecto(?:\s+de)?\s+(.+)$",
            original,
            flags=re.IGNORECASE,
        ):
            project_name = self._strip_quotes(match.group(1).strip())
            application = context.active_app if context.active_app else "visual studio code"
            context.active_app = application
            context.active_window = application
            return [
                self._action(
                    "open_project",
                    {"name": project_name, "application": application},
                    f"Abrir proyecto {project_name} en {application}",
                    "project",
                )
            ]

        if match := re.match(
            r"^(?:cambia|ve|ir|cambiar)\s+(?:a\s+)?la ventana(?:\s+de)?\s+(.+)$",
            original,
            flags=re.IGNORECASE,
        ):
            window_title = self._strip_quotes(match.group(1).strip())
            context.active_window = window_title
            return [self._action("focus_window", {"title": window_title}, f"Activar ventana {window_title}", "window")]

        for parser in (
            self._parse_navigation_clause,
            self._parse_open_clause,
            self._parse_search_clause,
            self._parse_write_clause,
            self._parse_tab_clause,
        ):
            actions = parser(original, context)
            if actions:
                return actions

        skill_match = self.skill_manager.find_skill_by_trigger(original)
        if skill_match:
            skill, _score = skill_match
            return [self._action("run_skill", {"name": skill.name}, f"Ejecutar skill {skill.name}", "skill")]

        return []

    def _parse_learning_skill_intent(
        self,
        command: str,
        context: ParserContext,
    ) -> Optional[CommandAction]:
        original = command.strip()
        normalized = normalize_text(original)
        if not original:
            return None
        if (
            any(token in normalized for token in ("continuo", "infinito", "infinitamente", "loop", "bucle", "input", "entrenamiento"))
            and (self._is_start_input_training_loop(normalized) or self._is_stop_input_training_loop(normalized))
        ):
            return None
        if any(token in normalized for token in ("reevalua", "revalua", "reevalua")) and "nivel" in normalized:
            return self._action(
                "reevaluate_skill_levels",
                {},
                "Reevaluar niveles exponenciales 0-6",
                "learning_skill",
            )
        autonomous_match = re.match(
            r"^(?:aprende|aprender|entrena|entrenar)\s+(?:autonomamente|autonomo|autonomamente a)?\s*(.+)$",
            original,
            flags=re.IGNORECASE,
        )
        if autonomous_match and any(token in normalized for token in ("autonom", "curriculum", "plan de aprendizaje")):
            objective = self._strip_quotes(autonomous_match.group(1).strip())
            if objective:
                objective = re.sub(r"(?i)\b(?:con\s+curriculum|autonomamente|de\s+forma\s+autonoma)\b", "", objective).strip(" ,.;:")
                return self._action(
                    "autonomous_learn",
                    {"objective": objective, "use_research": True},
                    f"Aprendizaje autonomo: {objective}",
                    "learning_skill",
                    requires_confirmation=True,
                )
        if "icono" in normalized or "escritorio" in normalized:
            return None
        if (
            self._is_practice_mouse_movement(normalized)
            or self._is_practice_mouse_click(normalized)
            or self._is_practice_mouse_double_click(normalized)
            or self._is_practice_mouse_right_click(normalized)
            or self._is_practice_mouse_detection(normalized)
            or self._is_practice_mouse_selection(normalized)
            or self._is_practice_mouse_workflow(normalized)
        ):
            return None

        learn_match = re.match(
            r"^(?:aprende|aprender|aprendeme|ensename|ensena(?:me)?|entrena(?:me)?)\s+(?:a\s+)?(.+)$",
            original,
            flags=re.IGNORECASE,
        )
        if learn_match:
            skill_text = self._clean_skill_phrase(learn_match.group(1).strip())
            if skill_text:
                if self._should_route_learn_to_autonomous(skill_text):
                    return self._action(
                        "autonomous_learn",
                        {"objective": skill_text, "use_research": True},
                        f"Aprendizaje autonomo: {skill_text}",
                        "learning_skill",
                    )
                create_document = self._wants_document(original)
                return self._action(
                    "learn_skill",
                    {
                        "skill": skill_text,
                        "goal": None,
                        "create_document": create_document,
                    },
                    f"Aprender habilidad: {skill_text}",
                    "learning_skill",
                )

        practice_match = re.match(
            r"^(?:practica|practicar|entrena|entrenar)\s+(.+)$",
            original,
            flags=re.IGNORECASE,
        )
        if practice_match:
            skill_text = practice_match.group(1).strip()
            if not self._looks_like_skill_practice(skill_text):
                return None
            return self._action(
                "practice_skill",
                {
                    "skill": self._clean_skill_phrase(skill_text),
                    "attempts": self._parse_attempt_count(normalized),
                    "minutes": self._parse_minute_count(normalized),
                },
                f"Practicar habilidad: {self._clean_skill_phrase(skill_text)}",
                "learning_skill",
            )

        evaluate_match = re.match(
            r"^(?:evalua|evaluar|mide)\s+(?:el\s+)?(?:uso\s+de\s+)?(.+)$",
            original,
            flags=re.IGNORECASE,
        )
        if evaluate_match:
            skill_text = self._clean_skill_phrase(evaluate_match.group(1).strip())
            if skill_text:
                return self._action(
                    "evaluate_skill",
                    {"skill": skill_text},
                    f"Evaluar habilidad: {skill_text}",
                    "learning_skill",
                )

        use_match = re.match(
            r"^(?:usa|usar)\s+(.+?)\s+para\s+(?:averiguar|investigar|buscar|encontrar|resolver|hacer)\s+(.+)$",
            original,
            flags=re.IGNORECASE,
        )
        if use_match:
            skill_text = self._clean_skill_phrase(use_match.group(1).strip())
            goal_text = self._strip_quotes(use_match.group(2).strip())
            if skill_text and goal_text:
                return self._action(
                    "use_skill",
                    {
                        "skill": skill_text,
                        "goal": goal_text,
                        "create_document": self._wants_document(original),
                    },
                    f"Usar habilidad {skill_text} para: {goal_text}",
                    "learning_skill",
                )

        return None

    def _parse_input_training_loop_intent(self, command: str) -> Optional[CommandAction]:
        normalized = normalize_text(command)
        if not normalized:
            return None
        mentions_training = any(
            token in normalized
            for token in ("entrenamiento", "entrena", "entrenar", "practica", "practicar", "flujo")
        )
        mentions_input = (
            any(token in normalized for token in ("mouse", "raton"))
            and any(token in normalized for token in ("teclado", "keyboard"))
        )
        mentions_loop = mentions_input or any(
            token in normalized for token in ("continuo", "infinito", "infinitamente", "loop", "bucle", "input")
        )
        if mentions_training and mentions_loop and self._is_start_input_training_loop(normalized):
            attempts = self._parse_attempt_count(normalized)
            return self._action(
                "start_input_training_loop",
                {
                    "mouse_attempts": attempts,
                    "keyboard_attempts": attempts,
                    "pause_seconds": 2.0,
                },
                "Iniciar entrenamiento continuo autonomo",
                "learning_skill",
                requires_confirmation=True,
            )
        if mentions_training and mentions_loop and self._is_stop_input_training_loop(normalized):
            return self._action(
                "stop_input_training_loop",
                {},
                "Detener entrenamiento continuo de mouse y teclado",
                "learning_skill",
            )
        if mentions_training and mentions_loop and self._is_input_training_status(normalized):
            return self._action(
                "input_training_status",
                {},
                "Consultar entrenamiento continuo de mouse y teclado",
                "learning_skill",
            )
        return None

    def _resolve_supported_skill(self, text: str) -> Optional[str]:
        normalized = normalize_text(text)
        aliases = {
            "teclado": ("teclado", "usar teclado", "uso de teclado", "keyboard"),
            "youtube": ("youtube", "usar youtube", "uso de youtube"),
            "mouse": ("mouse", "raton", "usar mouse", "usar raton"),
            "visualizacion": ("visualizacion", "visualización", "vision", "ver contexto", "contexto visual"),
            "window_management": (
                "acomodo de ventanas",
                "acomodar ventanas",
                "organizar ventanas",
                "ventanas",
                "window management",
            ),
            "juego": ("jugar", "juego", "partida", "terraria", "terarria", "minecraft"),
            "investigar": ("investigar", "investigacion", "investigación", "research"),
        }
        for skill_id, options in aliases.items():
            if any(normalize_text(option) in normalized or normalized in normalize_text(option) for option in options):
                return skill_id
        for app_name, data in (self.config.get("applications", {}) or {}).items():
            app_aliases = [app_name]
            if isinstance(data, dict):
                app_aliases.extend(str(item) for item in data.get("aliases", []))
            if any(normalize_text(alias) == normalized or normalize_text(alias) in normalized for alias in app_aliases):
                return str(app_name)
        for site_name in (self.config.get("url_aliases", {}) or {}).keys():
            alias = normalize_text(str(site_name))
            if alias == normalized or alias in normalized:
                return str(site_name)
        return None

    def _looks_like_skill_practice(self, text: str) -> bool:
        normalized = normalize_text(text)
        if self._resolve_supported_skill(normalized):
            return True
        return any(
            token in normalized
            for token in (
                "habilidad",
                "teclado",
                "mouse",
                "raton",
                "youtube",
                "investig",
                "word",
                "brave",
                "google",
                "explorer",
                "jugar",
                "juego",
                "terraria",
                "terarria",
                "minecraft",
            )
        )

    def _should_route_learn_to_autonomous(self, skill_text: str) -> bool:
        normalized = normalize_text(skill_text)
        supported = self._resolve_supported_skill(normalized)
        if supported == "juego":
            return True
        if supported:
            return False
        return bool(normalized)

    def _clean_skill_phrase(self, text: str) -> str:
        cleaned = self._strip_quotes(text)
        cleaned = re.sub(r"\b\d{1,3}\s*min(?:uto)?s?\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b\d{1,3}\s*(?:veces|intentos?)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(?:a\s+usar|usar|uso\s+de|a\s+)", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^(?:el|la|los|las)\s+", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\b(?:en|durante)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;:")
        return cleaned

    @staticmethod
    def _parse_minute_count(normalized: str) -> Optional[int]:
        match = re.search(r"\b(\d{1,3})\s*min(?:uto)?s?\b", normalized)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _wants_document(text: str) -> bool:
        return bool(re.search(r"\b(?:word|documento|docx)\b", text, flags=re.IGNORECASE))

    def _parse_complex_task(self, command: str, context: ParserContext) -> Optional[CommandAction]:
        normalized = normalize_text(command)
        if not any(token in normalized for token in self.COMPLEX_TASK_HINTS):
            return None
        if not any(token in normalized for token in ("investiga", "investigar", "averigua")):
            return None

        document_app = "word"
        if "libreoffice" in normalized or "writer" in normalized:
            document_app = "libreoffice writer"
        elif "notepad" in normalized or "bloc de notas" in normalized:
            document_app = "notepad"

        topic = re.sub(
            r"(?i)\b(?:investiga|investigar|averigua|informate sobre|busca informacion sobre|busca info sobre)\b",
            "",
            command,
        )
        topic = re.sub(r"(?i)^\s*sobre\s+", "", topic)
        topic = re.sub(
            r"(?i)\b(?:y\s+hazme\s+un\s+documento(?:\s+en\s+[\w\s]+)?|y\s+hazme\s+un\s+resumen(?:\s+en\s+[\w\s]+)?|y\s+resumelo(?:\s+en\s+[\w\s]+)?)\b.*$",
            "",
            topic,
        ).strip(" ,.;:")
        topic = re.sub(
            r"(?i)\b(?:y\s+)?(?:haz(?:me)?|crea(?:me)?|genera(?:me)?|prepara(?:me)?)\s+"
            r"(?:un\s+|una\s+)?(?:documento|reporte|resumen|word|docx)"
            r"(?:\s+en\s+[\w\s]+)?(?:\s+con\s+eso)?\b.*$",
            "",
            topic,
        ).strip(" ,.;:")
        topic = re.sub(r"(?i)\b(?:con\s+eso|de\s+eso)\b", "", topic).strip(" ,.;:")
        topic = topic or command

        browser = context.active_browser or self.config.get("default_browser", "brave")
        return self._action(
            "execute_complex_task",
            {
                "command": command,
                "task_type": "research_document",
                "topic": topic,
                "document_app": document_app,
                "browser": browser,
                "result_count": 5,
                "autonomous": True,
            },
            f"Investigar {topic} y crear documento en {document_app}",
            "planner",
        )

    def _parse_open_clause(self, clause: str, context: ParserContext) -> List[CommandAction]:
        match = re.match(r"^(?:abre|abreme|abrir)\s+(.+)$", clause, flags=re.IGNORECASE)
        if not match:
            return []

        raw_target = match.group(1).strip()
        private = self._detect_private_mode(raw_target)
        target = self._strip_browser_modifiers(raw_target)

        if target_in_browser := re.match(r"^(.+?)\s+en\s+(.+)$", target, flags=re.IGNORECASE):
            left_target = self._strip_quotes(target_in_browser.group(1).strip())
            right_target = self._strip_quotes(target_in_browser.group(2).strip())
            browser_match = self._match_browser(right_target)
            site_match = self._match_site(left_target)
            if browser_match and site_match:
                context.active_browser = browser_match.canonical
                context.active_app = browser_match.canonical
                context.active_site = site_match.canonical
                context.active_window = site_match.canonical
                context.browser_private = private
                return [
                    self._action(
                        "ensure_site",
                        {
                            "site": site_match.canonical,
                            "browser": browser_match.canonical,
                            "private": private,
                        },
                        f"Abrir {site_match.canonical} en {browser_match.canonical}",
                        "browser",
                    )
                ]

        browser_match = self._match_browser(target)
        app_match = self._match_application(target)
        site_match = self._match_site(target)

        browser_score = browser_match.score if browser_match else 0.0
        app_score = app_match.score if app_match else 0.0
        site_score = site_match.score if site_match else 0.0

        if browser_match and (browser_score >= site_score + 4 or browser_score >= app_score + 4):
            context.active_browser = browser_match.canonical
            context.active_app = browser_match.canonical
            context.active_window = browser_match.canonical
            context.browser_private = private
            return [
                self._action(
                    "ensure_browser",
                    {"browser": browser_match.canonical, "private": private},
                    f"Abrir {browser_match.canonical}" + (" en modo privado" if private else ""),
                    "browser",
                )
            ]

        if app_match and app_score >= site_score:
            context.active_app = app_match.canonical
            context.active_window = app_match.canonical
            if app_match.canonical in self.BROWSER_NAMES:
                context.active_browser = app_match.canonical
                context.browser_private = private
                return [
                    self._action(
                        "ensure_browser",
                        {"browser": app_match.canonical, "private": private},
                        f"Abrir {app_match.canonical}" + (" en modo privado" if private else ""),
                        "browser",
                    )
                ]
            if app_match.canonical == "spotify":
                context.active_site = "spotify"
            else:
                context.active_site = None
            return [
                self._action(
                    "open_application",
                    {"target": app_match.canonical},
                    f"Abrir aplicación {app_match.canonical}",
                    "application",
                )
            ]

        if site_match:
            context.active_site = site_match.canonical
            context.active_window = site_match.canonical
            return [
                self._action(
                    "ensure_site",
                    {
                        "site": site_match.canonical,
                        "browser": context.active_browser,
                        "private": context.browser_private,
                    },
                    f"Abrir sitio {site_match.canonical}",
                    "navigation",
                )
            ]

        return [
            self._action(
                "open_application",
                {"target": self._strip_quotes(target)},
                f"Abrir aplicación {self._strip_quotes(target)}",
                "application",
            )
        ]

    def _parse_navigation_clause(self, clause: str, context: ParserContext) -> List[CommandAction]:
        match = re.match(
            r"^(?:entra(?:\s+a)?|ve(?:\s+a)?|ir(?:\s+a)?|anda(?:\s+a)?|navega(?:\s+a)?|visita|d[eé]jame(?:\s+en)?)\s+(.+)$",
            clause,
            flags=re.IGNORECASE,
        )
        if not match:
            return []

        target = self._strip_quotes(match.group(1).strip())
        site_match = self._match_site(target)
        if not site_match:
            return []

        context.active_site = site_match.canonical
        context.active_window = site_match.canonical
        return [
            self._action(
                "ensure_site",
                {
                    "site": site_match.canonical,
                    "browser": context.active_browser,
                    "private": context.browser_private,
                },
                f"Ir a {site_match.canonical}",
                "navigation",
            )
        ]

    def _parse_search_clause(self, clause: str, context: ParserContext) -> List[CommandAction]:
        service_query = re.match(
            r"^(?:busca(?:me)?|b[úu]sca(?:me)?|b[úu]scame)\s+(?:en\s+)?(.+?)\s*:\s*(.+)$",
            clause,
            flags=re.IGNORECASE,
        )
        if service_query:
            service_token = service_query.group(1).strip()
            query = self._strip_quotes(service_query.group(2).strip())
            destination = self._resolve_service_destination(service_token, context)
            return self._build_search_actions(query, destination, context)

        trailing_destination = re.match(
            r"^(?:busca(?:me)?|b[úu]sca(?:me)?|b[úu]scame|quiero ver|quiero escuchar|pon(?:me)?|reproduce)\s+(.+?)\s+en\s+(.+)$",
            clause,
            flags=re.IGNORECASE,
        )
        if trailing_destination:
            query = self._strip_quotes(trailing_destination.group(1).strip())
            service_token = trailing_destination.group(2).strip()
            destination = self._resolve_service_destination(service_token, context)
            return self._build_search_actions(query, destination, context)

        generic_search = re.match(
            r"^(?:busca(?:me)?|b[úu]sca(?:me)?|b[úu]scame|quiero ver|quiero escuchar|pon(?:me)?|reproduce)\s+(.+)$",
            clause,
            flags=re.IGNORECASE,
        )
        if not generic_search:
            return []

        query = self._strip_quotes(generic_search.group(1).strip())
        site_match = self._match_site(query)
        if site_match and len(query.split()) <= 2:
            context.active_site = site_match.canonical
            return [
                self._action(
                    "ensure_site",
                    {
                        "site": site_match.canonical,
                        "browser": context.active_browser,
                        "private": context.browser_private,
                    },
                    f"Ir a {site_match.canonical}",
                    "navigation",
                )
            ]

        destination = self._infer_search_destination(clause, context)
        return self._build_search_actions(query, destination, context)

    def _parse_write_clause(self, clause: str, context: ParserContext) -> List[CommandAction]:
        normalized_clause = normalize_text(clause)
        active_match = re.match(
            r"^escribe\s+en\s+(?:la\s+)?pestaña\s+actual\s*:\s*(.+)$",
            clause,
            flags=re.IGNORECASE,
        )
        if active_match or normalized_clause.startswith("escribe en la pestana actual:"):
            if active_match:
                text = self._strip_quotes(active_match.group(1).strip())
            else:
                text = self._strip_quotes(clause.split(":", 1)[1].strip()) if ":" in clause else ""
            return [
                self._action(
                    "write_active_context",
                    {"text": text},
                    f"Escribir en el contexto activo: {text}",
                    "write",
                )
            ]

        match = re.match(r"^escribe\s+en\s+(.+?)\s*:\s*(.+)$", clause, flags=re.IGNORECASE)
        if not match:
            return []

        target = self._strip_quotes(match.group(1).strip())
        text = self._strip_quotes(match.group(2).strip())
        destination = self._resolve_service_destination(target, context)
        if destination in {"youtube", "google"}:
            return self._build_search_actions(text, destination, context)
        if destination == "spotify":
            return self._build_search_actions(text, "spotify", context)
        return [
            self._action(
                "write_text_to_window",
                {"window_title": target, "text": text},
                f"Escribir en {target}",
                "write",
            )
        ]

    def _parse_tab_clause(self, clause: str, context: ParserContext) -> List[CommandAction]:
        normalized = normalize_text(clause)
        if "nueva pestana" in normalized:
            return [self._action("browser_tab", {"mode": "new"}, "Abrir nueva pestaña", "browser")]
        if "cierra la pestana" in normalized or "cerrar pestana" in normalized:
            return [self._action("browser_tab", {"mode": "close"}, "Cerrar pestaña actual", "browser")]
        return []

    def _parse_volume_clause(self, original: str, normalized: str) -> Optional[List[CommandAction]]:
        if match := re.search(r"\b(?:sube|pon|ajusta)\s+el\s+volumen\s+(?:al|a)?\s*(\d{1,3})%?", normalized):
            percent = max(0, min(100, int(match.group(1))))
            return [
                self._action(
                    "set_volume_percent",
                    {"percent": percent},
                    f"Ajustar volumen al {percent}%",
                    "media",
                )
            ]
        if "sube el volumen" in normalized:
            return [self._action("set_volume", {"direction": "up", "steps": 5}, "Subir volumen", "media")]
        if "baja el volumen" in normalized:
            return [self._action("set_volume", {"direction": "down", "steps": 5}, "Bajar volumen", "media")]
        return None

    def _parse_desktop_clause(self, original: str, normalized: str) -> List[CommandAction]:
        attempts = self._parse_attempt_count(normalized)
        if self._is_practice_mouse_movement(normalized):
            return [
                self._action(
                    "practice_mouse_movement",
                    {"attempts": attempts},
                    "Practicar movimiento basico del mouse",
                    "desktop",
                    requires_confirmation=True,
                )
            ]

        if self._is_practice_mouse_right_click(normalized):
            return [
                self._action(
                    "practice_mouse_right_click",
                    {"attempts": attempts},
                    "Practicar click derecho del mouse",
                    "desktop",
                    requires_confirmation=True,
                )
            ]

        if self._is_practice_mouse_double_click(normalized):
            return [
                self._action(
                    "practice_mouse_double_click",
                    {"attempts": attempts},
                    "Practicar doble click del mouse",
                    "desktop",
                    requires_confirmation=True,
                )
            ]

        if self._is_practice_mouse_click(normalized):
            return [
                self._action(
                    "practice_mouse_click",
                    {"attempts": attempts},
                    "Practicar click simple del mouse",
                    "desktop",
                    requires_confirmation=True,
                )
            ]

        if self._is_practice_mouse_selection(normalized):
            return [
                self._action(
                    "practice_mouse_selection",
                    {"attempts": attempts},
                    "Practicar seleccion visual del mouse",
                    "desktop",
                    requires_confirmation=True,
                )
            ]

        if self._is_practice_mouse_detection(normalized):
            return [
                self._action(
                    "practice_mouse_detection",
                    {"attempts": attempts},
                    "Practicar deteccion visual reutilizable del mouse",
                    "desktop",
                    requires_confirmation=True,
                )
            ]

        if self._is_practice_mouse_workflow(normalized):
            return [
                self._action(
                    "practice_mouse_workflow",
                    {"attempts": attempts},
                    "Practicar flujo completo seguro del mouse",
                    "desktop",
                    requires_confirmation=True,
                )
            ]

        if self._is_practice_desktop_mouse(normalized):
            return [
                self._action(
                    "practice_desktop_mouse",
                    {"attempts": attempts},
                    "Practicar mouse con archivos temporales seguros",
                    "desktop",
                    requires_confirmation=True,
                )
            ]

        if (
            "escritorio" in normalized
            and any(token in normalized for token in ("deshacer", "revierte", "revertir", "restaura"))
            and any(token in normalized for token in ("ordenado", "organizado", "orden"))
        ):
            return [
                self._action(
                    "desktop_undo_last",
                    {},
                    "Deshacer la ultima sesion visible de ordenado del escritorio",
                    "desktop",
                    requires_confirmation=True,
                )
            ]

        if self._is_arrange_desktop_icons(normalized):
            return [
                self._action(
                    "arrange_desktop_icons",
                    {"sort_by": "name"},
                    "Ordenar visualmente los iconos del escritorio por nombre",
                    "desktop",
                    requires_confirmation=True,
                )
            ]

        if self._is_organize_desktop(normalized):
            execution_mode = "ui_learning"
            summary = "Ordenar el escritorio en carpetas por categoria con aprendizaje visible"
            if any(token in normalized for token in ("rapido", "rapida", "fast")):
                execution_mode = "legacy_filesystem"
                summary = "Ordenar el escritorio rapido por filesystem"
            elif any(token in normalized for token in ("aprendiendo", "visible", "mouse", "teclado")):
                execution_mode = "ui_learning"
            return [
                self._action(
                    "organize_desktop",
                    {"execution_mode": execution_mode},
                    summary,
                    "desktop",
                    requires_confirmation=True,
                )
            ]

        if re.match(
            r"^(?:lista|muestrame|ensename)\s+(?:los\s+)?iconos(?:\s+del\s+escritorio)?(?:\s+aprendidos)?$",
            normalized,
            flags=re.IGNORECASE,
        ):
            return [
                self._action(
                    "list_desktop_icons",
                    {},
                    "Listar iconos aprendidos del escritorio",
                    "desktop",
                )
            ]

        learn_match = re.match(
            r"^(?:aprende|entrena|ensena|ensename)\s+(?:este\s+)?icono(?:\s+del\s+escritorio)?(?:\s+como|\s+con\s+el\s+nombre\s+de)\s+(.+)$",
            original,
            flags=re.IGNORECASE,
        )
        if learn_match:
            icon_name = self._strip_quotes(learn_match.group(1).strip())
            return [
                self._action(
                    "train_desktop_icon",
                    {"name": icon_name},
                    f"Aprender icono del escritorio como {icon_name}",
                    "desktop",
                )
            ]

        click_match = re.match(
            r"^(?:(?:haz\s+)?(?:click|clic)|selecciona)\s+(?:en\s+)?(?:el\s+)?icono(?:\s+del\s+escritorio)?(?:\s+de)?\s+(.+)$",
            original,
            flags=re.IGNORECASE,
        )
        if click_match:
            icon_name = self._strip_quotes(click_match.group(1).strip())
            return [
                self._action(
                    "click_desktop_icon",
                    {"name": icon_name, "open_icon": False},
                    f"Hacer click en el icono del escritorio {icon_name}",
                    "desktop",
                )
            ]

        open_match = re.match(
            r"^(?:abre|abreme)\s+(?:el\s+)?icono(?:\s+del\s+escritorio)?(?:\s+de)?\s+(.+)$",
            original,
            flags=re.IGNORECASE,
        )
        if open_match:
            icon_name = self._strip_quotes(open_match.group(1).strip())
            return [
                self._action(
                    "click_desktop_icon",
                    {"name": icon_name, "open_icon": True},
                    f"Abrir el icono del escritorio {icon_name}",
                    "desktop",
                )
            ]

        return []

    def _build_search_actions(
        self,
        query: str,
        destination: str,
        context: ParserContext,
    ) -> List[CommandAction]:
        if destination == "youtube":
            context.active_site = "youtube"
            context.active_window = "youtube"
            return [
                self._action(
                    "smart_site_search",
                    {
                        "destination": "youtube",
                        "query": query,
                        "browser": context.active_browser,
                        "private": context.browser_private,
                        "autonomous": True,
                    },
                    f"Buscar en YouTube: {query}",
                    "search",
                )
            ]

        if destination == "spotify":
            context.active_app = "spotify"
            context.active_site = "spotify"
            context.active_window = "spotify"
            return [
                self._action(
                    "smart_spotify_play",
                    {"query": query, "autonomous": True},
                    f"Buscar o reproducir en Spotify: {query}",
                    "search",
                )
            ]

        context.active_site = "google"
        return [
            self._action(
                "smart_site_search",
                {
                    "destination": "google",
                    "query": query,
                    "browser": context.active_browser,
                    "private": context.browser_private,
                    "autonomous": True,
                },
                f"Buscar en Google: {query}",
                "search",
            )
        ]

    def _infer_search_destination(self, clause: str, context: ParserContext) -> str:
        normalized = normalize_text(clause)
        if "spotify" in normalized:
            return "spotify"
        if "youtube" in normalized:
            return "youtube"
        if context.active_site == "youtube":
            return "youtube"
        if context.active_site == "spotify":
            return "spotify"
        if context.active_app == "spotify":
            return "spotify"
        if "quiero ver" in normalized:
            return "youtube"
        if any(token in normalized for token in ("pon ", "ponme", "reproduce", "quiero escuchar")):
            return "spotify" if context.active_app == "spotify" else "google"
        return "google"

    def _resolve_service_destination(self, token: str, context: ParserContext) -> str:
        match = self._match_site(token)
        if match:
            return match.canonical
        app_match = self._match_application(token)
        if app_match and app_match.canonical == "spotify":
            return "spotify"
        if context.active_site:
            return context.active_site
        if context.active_app == "spotify":
            return "spotify"
        return "google"

    def _split_into_clauses(self, command: str) -> List[str]:
        protected_command, replacements = self._protect_quoted_text(command)
        parts: List[str] = []
        for segment in re.split(r"\s*[,;]\s*", protected_command):
            if not segment.strip():
                continue
            parts.extend(
                re.split(
                    r"\s+(?:y luego|luego|despues|después|entonces)\s+",
                    segment,
                    flags=re.IGNORECASE,
                )
            )

        final_parts: List[str] = []
        boundary_pattern = r"\s+y\s+(?=(?:%s)\b)" % "|".join(self.ACTION_BOUNDARY_HINTS)
        for segment in parts:
            split_segment = re.split(boundary_pattern, segment, flags=re.IGNORECASE)
            for item in split_segment:
                restored = self._restore_quoted_text(item.strip(), replacements)
                if restored:
                    final_parts.append(restored)
        return final_parts

    def _match_browser(self, text: str) -> Optional[EntityMatch]:
        browser_catalog = {
            name: data
            for name, data in self.config.get("applications", {}).items()
            if name in self.BROWSER_NAMES
        }
        return self._match_catalog(text, browser_catalog)

    def _match_application(self, text: str) -> Optional[EntityMatch]:
        return self._match_catalog(text, self.config.get("applications", {}))

    def _match_site(self, text: str) -> Optional[EntityMatch]:
        cleaned = text.strip()
        if re.match(r"^https?://", cleaned, flags=re.IGNORECASE):
            return EntityMatch(canonical=cleaned, alias=cleaned, score=100.0, url=cleaned)
        if "." in cleaned and " " not in cleaned:
            safe = cleaned if cleaned.startswith("http") else f"https://{cleaned}"
            return EntityMatch(canonical=cleaned, alias=cleaned, score=96.0, url=safe)

        catalog = {**self.DEFAULT_SITE_ALIASES, **self.config.get("url_aliases", {})}
        match = self._match_catalog(text, catalog)
        if match:
            match.url = catalog.get(match.canonical)
        return match

    def _match_catalog(self, text: str, catalog: Dict[str, Any]) -> Optional[EntityMatch]:
        alias_lookup: Dict[str, str] = {}
        for canonical, value in catalog.items():
            alias_lookup[str(canonical)] = str(canonical)
            if isinstance(value, dict):
                for alias in value.get("aliases", []):
                    alias_lookup[str(alias)] = str(canonical)

        if not alias_lookup:
            return None

        normalized_query = normalize_text(text)
        for alias, canonical in alias_lookup.items():
            if normalize_text(alias) == normalized_query:
                return EntityMatch(canonical=canonical, alias=alias, score=100.0)

        for alias, canonical in alias_lookup.items():
            normalized_alias = normalize_text(alias)
            if normalized_alias and (
                normalized_alias in normalized_query or normalized_query in normalized_alias
            ):
                score = 94.0 if normalized_alias in normalized_query else 88.0
                return EntityMatch(canonical=canonical, alias=alias, score=score)

        best_alias, score = self._fuzzy_best_match(text, alias_lookup.keys(), score_cutoff=72.0)
        if not best_alias:
            return None
        return EntityMatch(canonical=alias_lookup[best_alias], alias=best_alias, score=score)

    def _fuzzy_best_match(
        self,
        query: str,
        choices: Sequence[str],
        score_cutoff: float = 72.0,
    ) -> Tuple[Optional[str], float]:
        if not choices:
            return None, 0.0

        if RAPIDFUZZ_AVAILABLE:
            result = process.extractOne(
                query,
                list(choices),
                scorer=fuzz.WRatio,
                processor=normalize_text,
                score_cutoff=score_cutoff,
            )
            if result:
                return str(result[0]), float(result[1])
            return None, 0.0

        best_choice: Optional[str] = None
        best_score = 0.0
        normalized_query = normalize_text(query)
        for choice in choices:
            score = SequenceMatcher(None, normalized_query, normalize_text(choice)).ratio() * 100
            if score > best_score:
                best_choice = str(choice)
                best_score = float(score)
        if best_score >= score_cutoff:
            return best_choice, best_score
        return None, 0.0

    def _match_feedback_pattern(self, command: str) -> Optional[Tuple[List[CommandAction], str]]:
        patterns = self._load_feedback_patterns()
        if not patterns:
            return None

        normalized_command = normalize_text(command)
        if normalized_command in patterns:
            payload = patterns[normalized_command]
            actions = [CommandAction(**item) for item in payload.get("actions", [])]
            return actions, "Comando resuelto usando un patrón aprendido exacto."

        best_key, score = self._fuzzy_best_match(
            normalized_command,
            list(patterns.keys()),
            score_cutoff=86.0,
        )
        if not best_key:
            return None
        payload = patterns[best_key]
        actions = [CommandAction(**item) for item in payload.get("actions", [])]
        return actions, f"Comando resuelto usando feedback aprendido con similitud {score:.1f}."

    def _load_feedback_patterns(self) -> Dict[str, Any]:
        if not self.feedback_path.exists():
            return {}
        with self.feedback_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _serialize_action(item: Dict[str, Any] | CommandAction) -> Dict[str, Any]:
        if isinstance(item, CommandAction):
            return asdict(item)
        return {
            "action": item["action"],
            "params": item.get("params", {}),
            "summary": item.get("summary", ""),
            "requires_confirmation": bool(item.get("requires_confirmation", False)),
            "intent": item.get("intent", ""),
        }

    @staticmethod
    def _action(
        action: str,
        params: Dict[str, Any],
        summary: str,
        intent: str,
        requires_confirmation: bool = False,
    ) -> CommandAction:
        return CommandAction(
            action=action,
            params=params,
            summary=summary,
            requires_confirmation=requires_confirmation,
            intent=intent,
        )

    @staticmethod
    def _detect_private_mode(text: str) -> bool:
        return bool(
            re.search(
                r"\b(?:inc[oó]gnito|modo\s+inc[oó]gnito|privado|private|inprivate)\b",
                text,
                flags=re.IGNORECASE,
            )
        )

    @staticmethod
    def _strip_browser_modifiers(text: str) -> str:
        cleaned = re.sub(
            r"\b(?:en\s+)?(?:modo\s+)?(?:inc[oó]gnito|privado|private|inprivate)\b",
            "",
            text,
            flags=re.IGNORECASE,
        )
        return cleaned.strip(" ,")

    @staticmethod
    def _protect_quoted_text(text: str) -> Tuple[str, Dict[str, str]]:
        replacements: Dict[str, str] = {}

        def replacer(match: re.Match[str]) -> str:
            token = f"__QUOTE_{len(replacements)}__"
            replacements[token] = match.group(0)
            return token

        protected = re.sub(r"(['\"])(.*?)(\1)", replacer, text)
        return protected, replacements

    @staticmethod
    def _restore_quoted_text(text: str, replacements: Dict[str, str]) -> str:
        restored = text
        for token, value in replacements.items():
            restored = restored.replace(token, value)
        return restored

    @staticmethod
    def _strip_quotes(text: str) -> str:
        stripped = text.strip()
        if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
            return stripped[1:-1].strip()
        return stripped

    @staticmethod
    def _is_close_current(normalized: str) -> bool:
        return normalized in {
            "cierra la ventana actual",
            "cerrar la ventana actual",
            "cierra ventana actual",
        }

    @staticmethod
    def _is_minimize_all(normalized: str) -> bool:
        return normalized in {
            "minimiza todas las ventanas",
            "minimizar todas las ventanas",
            "minimiza todo",
        }

    @staticmethod
    def _is_maximize_current(normalized: str) -> bool:
        return normalized in {
            "maximiza la ventana actual",
            "maximizar la ventana actual",
            "maximiza la ventana",
        }

    @staticmethod
    def _is_start_input_training_loop(normalized: str) -> bool:
        return (
            any(
                token in normalized
                for token in (
                    "infinito",
                    "infinitamente",
                    "continuo",
                    "continuamente",
                    "sin parar",
                    "hasta que pare",
                    "hasta que te diga que pare",
                    "hasta que diga que pare",
                )
            )
            and (
                re.search(r"\b(?:entrena|entrenar|practica|practicar)\b", normalized) is not None
                or "flujo completo" in normalized
            )
        )

    @staticmethod
    def _is_stop_input_training_loop(normalized: str) -> bool:
        return re.search(
            r"\b(?:para|pare|parar|pausa|pausar|deten|detener|detente|stop|termina|terminar)\b",
            normalized,
        ) is not None

    @staticmethod
    def _is_input_training_status(normalized: str) -> bool:
        return any(token in normalized for token in ("estado", "status", "como va", "sigue"))

    @staticmethod
    def _is_practice_mouse_movement(normalized: str) -> bool:
        return (
            any(token in normalized for token in ("mouse", "raton"))
            and any(token in normalized for token in ("mover", "movimiento", "muevete", "mueve"))
            and any(
                token in normalized
                for token in (
                    "practica",
                    "practicar",
                    "entrena",
                    "entrenar",
                    "aprende",
                    "aprender",
                )
            )
        )

    @staticmethod
    def _is_practice_mouse_click(normalized: str) -> bool:
        return (
            any(token in normalized for token in ("click", "clic"))
            and not any(token in normalized for token in ("doble", "derecho"))
            and any(
                token in normalized
                for token in (
                    "practica",
                    "practicar",
                    "entrena",
                    "entrenar",
                    "aprende",
                    "aprender",
                )
            )
        )

    @staticmethod
    def _is_practice_mouse_double_click(normalized: str) -> bool:
        return (
            any(token in normalized for token in ("doble click", "doble clic"))
            and any(
                token in normalized
                for token in (
                    "practica",
                    "practicar",
                    "entrena",
                    "entrenar",
                    "aprende",
                    "aprender",
                )
            )
        )

    @staticmethod
    def _is_practice_mouse_right_click(normalized: str) -> bool:
        return (
            any(token in normalized for token in ("click derecho", "clic derecho"))
            and any(
                token in normalized
                for token in (
                    "practica",
                    "practicar",
                    "entrena",
                    "entrenar",
                    "aprende",
                    "aprender",
                )
            )
        )

    @staticmethod
    def _is_practice_mouse_selection(normalized: str) -> bool:
        return (
            any(token in normalized for token in ("seleccion", "seleccionar"))
            and any(
                token in normalized
                for token in (
                    "visual",
                    "mouse",
                    "raton",
                    "archivo",
                    "explorer",
                    "escritorio",
                )
            )
            and any(
                token in normalized
                for token in (
                    "practica",
                    "practicar",
                    "entrena",
                    "entrenar",
                    "aprende",
                    "aprender",
                )
            )
        )

    @staticmethod
    def _is_practice_mouse_detection(normalized: str) -> bool:
        return (
            any(token in normalized for token in ("deteccion", "detectar", "localizar", "reencontrar"))
            and any(
                token in normalized
                for token in (
                    "visual",
                    "archivo",
                    "explorer",
                    "escritorio",
                    "mouse",
                    "raton",
                    "busqueda",
                    "buscar",
                )
            )
            and any(
                token in normalized
                for token in (
                    "practica",
                    "practicar",
                    "entrena",
                    "entrenar",
                    "aprende",
                    "aprender",
                )
            )
        )

    @staticmethod
    def _is_practice_mouse_workflow(normalized: str) -> bool:
        return (
            any(token in normalized for token in ("flujo", "completo", "secuencia"))
            and any(token in normalized for token in ("mouse", "raton", "seguro"))
            and any(
                token in normalized
                for token in (
                    "practica",
                    "practicar",
                    "entrena",
                    "entrenar",
                    "aprende",
                    "aprender",
                )
            )
        )

    @staticmethod
    def _is_practice_desktop_mouse(normalized: str) -> bool:
        return (
            any(token in normalized for token in ("mouse", "raton"))
            and any(
                token in normalized
                for token in (
                    "practica",
                    "practicar",
                    "entrena",
                    "entrenar",
                    "aprende",
                    "aprender",
                )
            )
        )

    @staticmethod
    def _parse_attempt_count(normalized: str) -> Optional[int]:
        match = re.search(r"\b(\d{1,3})\s*(?:veces|intentos?)\b", normalized)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _is_arrange_desktop_icons(normalized: str) -> bool:
        return (
            "escritorio" in normalized
            and any(token in normalized for token in ("icono", "iconos"))
            and any(
                token in normalized
                for token in (
                    "ordena",
                    "organiza",
                    "ordename",
                    "organizame",
                    "acomoda",
                    "acomodame",
                )
            )
        )

    @staticmethod
    def _is_organize_desktop(normalized: str) -> bool:
        if any(token in normalized for token in ("icono", "iconos")):
            return False
        return "escritorio" in normalized and any(
            token in normalized
            for token in (
                "ordena",
                "organiza",
                "ordename",
                "organizame",
                "limpia",
            )
        )

    def _seed_context_from_vision(self, vision_context: Optional[Any]) -> ParserContext:
        context = ParserContext()
        if not vision_context:
            return context
        active_app = getattr(vision_context, "active_app", None)
        active_site = getattr(vision_context, "active_site", None)
        active_window = getattr(vision_context, "active_window", None)
        context.active_app = active_app
        context.active_site = active_site
        context.active_window = active_window
        if active_app in self.BROWSER_NAMES:
            context.active_browser = active_app
        return context


def set_default_parser(parser: CommandParser) -> None:
    global _DEFAULT_PARSER
    _DEFAULT_PARSER = parser


def interpret_command(command: str) -> CommandInterpretation:
    if _DEFAULT_PARSER is None:
        raise RuntimeError("No hay un parser por defecto configurado.")
    return _DEFAULT_PARSER.interpret_command(command)
