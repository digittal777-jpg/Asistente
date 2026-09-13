from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core.logging_utils import ensure_directory
from core.skills import normalize_text

try:
    from rapidfuzz import fuzz, process

    RAPIDFUZZ_AVAILABLE = True
except ImportError:  # pragma: no cover - fallback local
    from difflib import SequenceMatcher

    RAPIDFUZZ_AVAILABLE = False


@dataclass
class DesktopMoveOperation:
    source: str
    destination: str
    category: str
    kind: str


@dataclass
class DesktopOrganizationPreview:
    desktop_path: str
    root_folder: str
    operations: List[DesktopMoveOperation] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "desktop_path": self.desktop_path,
            "root_folder": self.root_folder,
            "operations": [asdict(item) for item in self.operations],
            "skipped": list(self.skipped),
        }

    def summary(self) -> str:
        if not self.operations:
            return "No hay elementos pendientes por mover."
        return (
            f"Se moveran {len(self.operations)} elemento(s) del escritorio hacia "
            f"{Path(self.root_folder).name}."
        )


class DesktopTrainer:
    """Aprende iconos del escritorio y organiza archivos con seguridad."""

    DOCUMENT_EXTENSIONS = {
        ".txt",
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".csv",
        ".ppt",
        ".pptx",
        ".md",
        ".rtf",
    }
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico"}
    VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm"}
    AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"}
    ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z", ".tar", ".gz"}
    CODE_EXTENSIONS = {
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".html",
        ".css",
        ".json",
        ".yml",
        ".yaml",
        ".ps1",
        ".bat",
        ".cmd",
        ".java",
        ".cs",
        ".cpp",
        ".c",
        ".go",
        ".rs",
        ".php",
    }
    INSTALLER_EXTENSIONS = {".exe", ".msi"}
    SHORTCUT_EXTENSIONS = {".lnk", ".url"}
    DEFAULT_CAPTURE_SIZE = (180, 140)

    def __init__(
        self,
        base_dir: Path,
        config: Any,
        vision: Any,
        mouse_controller: Any,
        automation: Any,
        logger: Optional[Any] = None,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.config = config
        self.vision = vision
        self.mouse_controller = mouse_controller
        self.automation = automation
        self.logger = logger
        self.progress_callback = progress_callback
        self.registry_path = self.base_dir / "data" / "desktop_icons.json"
        ensure_directory(self.registry_path.parent)
        self.registry = self._load_registry()

    def learn_icon(
        self,
        name: str,
        aliases: Optional[Sequence[str]] = None,
        capture_size: Optional[Tuple[int, int]] = None,
        capture_delay_seconds: Optional[float] = None,
    ) -> str:
        display_name = name.strip()
        if not display_name:
            raise ValueError("Debes indicar un nombre para el icono del escritorio.")

        wait_seconds = float(
            capture_delay_seconds
            if capture_delay_seconds is not None
            else self.config.get("desktop_training", {}).get("capture_delay_seconds", 3)
        )
        if wait_seconds > 0:
            self._emit(
                f"Coloca el mouse sobre el icono '{display_name}'. Capturando en {wait_seconds:.0f} segundo(s)...",
                "info",
            )
            time.sleep(wait_seconds)

        x, y = self.automation.get_mouse_position()
        capture = capture_size or tuple(
            self.config.get("desktop_training", {}).get("capture_size", list(self.DEFAULT_CAPTURE_SIZE))
        )
        template_name = normalize_text(display_name)
        path = self.vision.calibrate_template_from_point(
            name=template_name,
            center_x=x,
            center_y=y,
            app="desktop",
            size=(int(capture[0]), int(capture[1])),
        )

        alias_list = self._normalize_aliases(display_name, aliases)
        self.registry.setdefault("icons", {})[template_name] = {
            "name": display_name,
            "template_name": template_name,
            "aliases": alias_list,
            "path": path,
            "capture_size": [int(capture[0]), int(capture[1])],
            "learned_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._save_registry()
        self._emit(f"Icono del escritorio aprendido: {display_name}", "info")
        return f"Icono aprendido como '{display_name}' y guardado en {path}."

    def list_icons(self) -> List[Dict[str, Any]]:
        entries = list(self.registry.get("icons", {}).values())
        return sorted(entries, key=lambda item: normalize_text(item.get("name", "")))

    def list_icons_text(self) -> str:
        entries = self.list_icons()
        if not entries:
            return "No hay iconos del escritorio aprendidos todavia."
        lines = ["Iconos del escritorio aprendidos:"]
        for entry in entries:
            aliases = ", ".join(entry.get("aliases", [])[:4]) or "sin aliases"
            lines.append(f"- {entry['name']} | aliases: {aliases}")
        return "\n".join(lines)

    def arrange_icons(self, sort_by: str = "name") -> str:
        """Ordena iconos visibles sin mover archivos del escritorio."""
        sort_key = normalize_text(sort_by or "name")
        if sort_key not in {"name", "nombre"}:
            raise ValueError("Por ahora solo puedo ordenar iconos por nombre.")

        self._emit("Mostrando escritorio para ordenar iconos...", "info")
        self.automation.minimize_all_windows()
        time.sleep(0.35)

        x, y = self._desktop_context_point()
        self._emit(f"Abriendo menu del escritorio en ({x}, {y})...", "info")
        self.automation.move_mouse(x, y, duration=0.25)
        time.sleep(0.08)
        self.automation.click(x, y, button="right", duration=0.06)
        time.sleep(0.25)

        # Menu clasico del escritorio: Ver, Ordenar por, Actualizar...
        # Con dos flechas baja a "Ordenar por", derecha abre el submenu y Enter elige "Nombre".
        self.automation.press_keys(["down", "down", "right", "enter"])
        time.sleep(0.25)
        self.automation.press_keys(["f5"])
        return (
            "Secuencia visible enviada para ordenar iconos del escritorio por nombre. "
            "No movi archivos ni cree carpetas."
        )

    def click_icon(
        self,
        name: str,
        open_icon: bool = False,
        timeout: Optional[float] = None,
        confidence: Optional[float] = None,
        show_desktop_first: Optional[bool] = None,
    ) -> str:
        entry = self._resolve_icon(name)
        if not entry:
            raise FileNotFoundError(
                f"No conozco un icono del escritorio llamado '{name}'. Usa primero 'aprende este icono como ...'."
            )

        confidence_value = float(
            confidence
            if confidence is not None
            else self.config.get("desktop_training", {}).get("match_confidence", 0.8)
        )
        timeout_value = float(timeout if timeout is not None else 8)
        should_show_desktop = (
            bool(show_desktop_first)
            if show_desktop_first is not None
            else bool(self.config.get("desktop_organizer", {}).get("show_desktop_before_click", True))
        )

        if should_show_desktop:
            self._emit("Mostrando el escritorio para localizar el icono...", "info")
            self.automation.minimize_all_windows()
            time.sleep(0.35)

        clicks = 2 if open_icon else 1
        self._emit(f"Buscando icono aprendido: {entry['name']}", "info")
        return self.mouse_controller.locate_and_click(
            image_template=entry["template_name"],
            confidence=confidence_value,
            timeout=timeout_value,
            button="left",
            clicks=clicks,
            app="desktop",
        )

    def _desktop_context_point(self) -> Tuple[int, int]:
        try:
            bounds = self.vision._screen_bounds()
            if bounds:
                left, top, width, height = bounds
                return int(left + width * 0.82), int(top + height * 0.52)
        except Exception:
            pass
        return 960, 520

    def preview_organization(
        self,
        root_name: Optional[str] = None,
        move_shortcuts: Optional[bool] = None,
        move_folders: Optional[bool] = None,
    ) -> DesktopOrganizationPreview:
        settings = self.config.get("desktop_organizer", {})
        desktop_path = self._desktop_path()
        root_folder_name = root_name or settings.get("root_folder_name", "_Raphel_Ordenado")
        root_folder = desktop_path / root_folder_name
        allow_shortcuts = settings.get("move_shortcuts", False) if move_shortcuts is None else move_shortcuts
        allow_folders = settings.get("move_folders", False) if move_folders is None else move_folders
        skip_names = {
            normalize_text(item)
            for item in settings.get("skip_names", ["desktop.ini", root_folder_name])
        }
        skip_names.add(normalize_text(root_folder_name))

        operations: List[DesktopMoveOperation] = []
        skipped: List[str] = []
        for item in desktop_path.iterdir():
            if normalize_text(item.name) in skip_names:
                skipped.append(item.name)
                continue
            category = self._categorize_item(item, allow_shortcuts=allow_shortcuts, allow_folders=allow_folders)
            if not category:
                skipped.append(item.name)
                continue
            destination_dir = root_folder / category
            destination = self._dedupe_destination(destination_dir / item.name)
            operations.append(
                DesktopMoveOperation(
                    source=str(item),
                    destination=str(destination),
                    category=category,
                    kind="folder" if item.is_dir() else "file",
                )
            )

        return DesktopOrganizationPreview(
            desktop_path=str(desktop_path),
            root_folder=str(root_folder),
            operations=operations,
            skipped=skipped,
        )

    def organize_desktop(
        self,
        root_name: Optional[str] = None,
        move_shortcuts: Optional[bool] = None,
        move_folders: Optional[bool] = None,
    ) -> str:
        preview = self.preview_organization(
            root_name=root_name,
            move_shortcuts=move_shortcuts,
            move_folders=move_folders,
        )
        if not preview.operations:
            return "El escritorio ya esta limpio o no hay elementos configurados para mover."

        moved = 0
        for operation in preview.operations:
            source = Path(operation.source)
            destination = Path(operation.destination)
            ensure_directory(destination.parent)
            self._emit(f"Moviendo {source.name} -> {destination.parent.name}", "info")
            shutil.move(str(source), str(destination))
            moved += 1

        summary = preview.summary()
        return f"{summary} Movidos: {moved} elemento(s). Carpeta raiz: {preview.root_folder}"

    def build_confirmation_prompt(
        self,
        preview: DesktopOrganizationPreview,
    ) -> str:
        if not preview.operations:
            return "No hay movimientos pendientes."
        categories: Dict[str, int] = {}
        for operation in preview.operations:
            categories[operation.category] = categories.get(operation.category, 0) + 1
        category_preview = ", ".join(f"{name}: {count}" for name, count in sorted(categories.items()))
        return (
            f"Se moveran {len(preview.operations)} elemento(s) del escritorio a '{Path(preview.root_folder).name}' "
            f"({category_preview}). Continuar?"
        )

    def _desktop_path(self) -> Path:
        folders = self.config.get("frequent_folders", {})
        desktop_raw = folders.get("desktop") or folders.get("escritorio") or str(Path.home() / "Desktop")
        desktop_path = Path(desktop_raw).expanduser()
        if not desktop_path.exists():
            raise FileNotFoundError(f"No se encontro el escritorio en: {desktop_path}")
        return desktop_path

    def _categorize_item(
        self,
        item: Path,
        allow_shortcuts: bool,
        allow_folders: bool,
    ) -> Optional[str]:
        if item.is_dir():
            return "Carpetas" if allow_folders else None

        suffix = item.suffix.lower()
        if suffix in self.SHORTCUT_EXTENSIONS:
            return "Atajos" if allow_shortcuts else None
        if suffix in self.DOCUMENT_EXTENSIONS:
            return "Documentos"
        if suffix in self.IMAGE_EXTENSIONS:
            return "Imagenes"
        if suffix in self.VIDEO_EXTENSIONS:
            return "Videos"
        if suffix in self.AUDIO_EXTENSIONS:
            return "Audio"
        if suffix in self.ARCHIVE_EXTENSIONS:
            return "Comprimidos"
        if suffix in self.CODE_EXTENSIONS:
            return "Codigo"
        if suffix in self.INSTALLER_EXTENSIONS:
            return "Instaladores"
        return "Otros"

    def _resolve_icon(self, query: str) -> Optional[Dict[str, Any]]:
        icons = self.registry.get("icons", {})
        if not icons:
            return None

        normalized_query = normalize_text(query)
        for key, entry in icons.items():
            aliases = [key, *entry.get("aliases", []), entry.get("name", "")]
            if any(normalized_query == normalize_text(alias) for alias in aliases if alias):
                return entry

        for key, entry in icons.items():
            aliases = [key, *entry.get("aliases", []), entry.get("name", "")]
            if any(
                normalized_query and (
                    normalized_query in normalize_text(alias) or normalize_text(alias) in normalized_query
                )
                for alias in aliases
                if alias
            ):
                return entry

        alias_lookup: Dict[str, Dict[str, Any]] = {}
        for key, entry in icons.items():
            for alias in [key, *entry.get("aliases", []), entry.get("name", "")]:
                if alias:
                    alias_lookup[str(alias)] = entry
        best_alias, score = self._fuzzy_best_match(query, list(alias_lookup.keys()), score_cutoff=72.0)
        if not best_alias:
            return None
        self._emit(f"Icono resuelto por similitud {score:.1f}: {best_alias}", "info")
        return alias_lookup[best_alias]

    @staticmethod
    def _dedupe_destination(path: Path) -> Path:
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        counter = 2
        while True:
            candidate = path.with_name(f"{stem}_{counter}{suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    @staticmethod
    def _normalize_aliases(name: str, aliases: Optional[Sequence[str]]) -> List[str]:
        values = [name, *(aliases or [])]
        deduped: List[str] = []
        seen = set()
        for value in values:
            cleaned = str(value).strip()
            if not cleaned:
                continue
            key = normalize_text(cleaned)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(cleaned)
        return deduped

    def _load_registry(self) -> Dict[str, Any]:
        if not self.registry_path.exists():
            return {"icons": {}}
        try:
            with self.registry_path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:
            return {"icons": {}}

    def _save_registry(self) -> None:
        with self.registry_path.open("w", encoding="utf-8") as handle:
            json.dump(self.registry, handle, indent=2, ensure_ascii=False)

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

    def _emit(self, message: str, level: str = "info") -> None:
        if self.logger:
            log_method = getattr(self.logger, level if hasattr(self.logger, level) else "info")
            log_method(message)
        if self.progress_callback:
            self.progress_callback(message, level)
