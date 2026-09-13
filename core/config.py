from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from core.logging_utils import ensure_directory


DEFAULT_CONFIG: Dict[str, Any] = {
    "frequent_folders": {
        "desktop": str(Path.home() / "Desktop"),
        "escritorio": str(Path.home() / "Desktop"),
        "downloads": str(Path.home() / "Downloads"),
        "descargas": str(Path.home() / "Downloads"),
        "documents": str(Path.home() / "Documents"),
        "documentos": str(Path.home() / "Documents"),
        "pictures": str(Path.home() / "Pictures"),
        "imagenes": str(Path.home() / "Pictures"),
    },
    "applications": {
        "notepad": {
            "command": "notepad.exe",
            "aliases": ["notepad", "bloc de notas", "bloc"],
        },
        "calculator": {
            "command": "calc.exe",
            "aliases": ["calculator", "calculadora", "calc"],
        },
        "explorer": {
            "command": "explorer.exe",
            "aliases": ["explorer", "explorador", "explorador de archivos", "file explorer"],
        },
        "paint": {
            "command": "mspaint.exe",
            "aliases": ["paint", "mspaint"],
        },
        "visual studio code": {
            "command": "Code.exe",
            "aliases": ["visual studio code", "vs code", "vscode", "code"],
            "paths": [
                "%LocalAppData%\\Programs\\Microsoft VS Code\\Code.exe",
                "%ProgramFiles%\\Microsoft VS Code\\Code.exe",
                "%ProgramFiles(x86)%\\Microsoft VS Code\\Code.exe"
            ],
        },
        "spotify": {
            "command": "spotify.exe",
            "aliases": ["spotify"],
            "paths": [
                "%AppData%\\Spotify\\Spotify.exe",
                "%LocalAppData%\\Microsoft\\WindowsApps\\Spotify.exe"
            ],
        },
        "word": {
            "command": "WINWORD.EXE",
            "aliases": ["word", "microsoft word"],
            "paths": [
                "%ProgramFiles%\\Microsoft Office\\root\\Office16\\WINWORD.EXE",
                "%ProgramFiles(x86)%\\Microsoft Office\\root\\Office16\\WINWORD.EXE"
            ],
        },
        "libreoffice writer": {
            "command": "soffice.exe",
            "aliases": ["libreoffice writer", "writer", "libreoffice"],
            "paths": [
                "%ProgramFiles%\\LibreOffice\\program\\soffice.exe",
                "%ProgramFiles(x86)%\\LibreOffice\\program\\soffice.exe"
            ],
        },
        "brave": {
            "command": "brave.exe",
            "aliases": ["brave", "brave browser"],
        },
        "chrome": {
            "command": "chrome.exe",
            "aliases": ["chrome", "google chrome"],
        },
        "edge": {
            "command": "msedge.exe",
            "aliases": ["edge", "microsoft edge"],
        },
        "firefox": {
            "command": "firefox.exe",
            "aliases": ["firefox", "mozilla firefox"],
        },
    },
    "browser_paths": {
        "brave": [
            "brave.exe",
            "%ProgramFiles%\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
            "%ProgramFiles(x86)%\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
            "%LocalAppData%\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
        ],
        "chrome": [
            "chrome.exe",
            "%ProgramFiles%\\Google\\Chrome\\Application\\chrome.exe",
            "%ProgramFiles(x86)%\\Google\\Chrome\\Application\\chrome.exe",
            "%LocalAppData%\\Google\\Chrome\\Application\\chrome.exe",
        ],
        "edge": [
            "msedge.exe",
            "%ProgramFiles(x86)%\\Microsoft\\Edge\\Application\\msedge.exe",
            "%ProgramFiles%\\Microsoft\\Edge\\Application\\msedge.exe",
            "%LocalAppData%\\Microsoft\\Edge\\Application\\msedge.exe",
        ],
        "firefox": [
            "firefox.exe",
            "%ProgramFiles%\\Mozilla Firefox\\firefox.exe",
            "%ProgramFiles(x86)%\\Mozilla Firefox\\firefox.exe",
        ],
    },
    "url_aliases": {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "gmail": "https://mail.google.com",
        "github": "https://github.com",
        "spotify": "https://open.spotify.com",
    },
    "window_aliases": {
        "youtube": "YouTube",
        "spotify": "Spotify",
        "visual studio code": "Visual Studio Code",
        "vscode": "Visual Studio Code",
        "code": "Visual Studio Code",
        "word": "Word",
        "libreoffice writer": "LibreOffice Writer",
    },
    "project_aliases": {},
    "google_url": "https://www.google.com/search?q={query}",
    "youtube_search_url": "https://www.youtube.com/results?search_query={query}",
    "spotify_search_url": "https://open.spotify.com/search/{query}",
    "document_output_dir": str(Path.home() / "Documents" / "Raphel"),
    "default_browser": "brave",
    "research_automation": {
        "prefer_direct_typing_for_search": True,
        "search_direct_typing_interval": 0.01,
        "document_direct_typing_max_chars": 1800,
        "document_direct_typing_interval": 0.006,
    },
    "learning_skills": {
        "verification_mode": "strict_real",
        "max_cycles_per_session": 3,
        "max_attempts_per_cycle": 20,
        "max_minutes_per_cycle": 10,
        "blocked_after_failed_sessions": 3,
        "gates": {
            "1_to_2": {
                "success_rate": 0.85,
                "verified_count": 20,
            },
            "2_to_3": {
                "success_rate": 0.75,
                "workflow_successes": 10,
            },
        },
        "keyboard": {
            "default_attempts_level_1": 8,
            "default_workflows_level_2": 3,
            "default_workflows_level_3": 2,
            "sample_texts": [
                "raphel aprende rapido",
                "teclado con precision visible",
                "rimuru analiza y verifica",
                "youtube investigacion segura",
            ],
        },
        "youtube": {
            "default_attempts_level_1": 6,
            "default_workflows_level_2": 3,
            "default_workflows_level_3": 2,
            "sample_queries": [
                "rimuru tempest resumen",
                "tutorial teclado rapido",
                "investigacion visible raphel",
            ],
            "result_tab_strategies": [3, 5, 7],
            "prefer_transcript_first": True,
            "minimum_transcript_capture_chars": 220,
            "minimum_visible_capture_chars": 180,
            "max_transcript_capture_passes": 1,
        },
        "research": {
            "default_attempts_level_1": 4,
            "default_workflows_level_2": 2,
            "default_workflows_level_3": 1,
            "default_result_count": 3,
            "minimum_query_capture_chars": 500,
            "minimum_summary_capture_chars": 260,
            "result_open_timeout_seconds": 1.6,
            "result_back_timeout_seconds": 1.0,
            "query_variants": [
                "{topic}",
                "{topic} guia",
                "{topic} overview",
                "{topic} explicacion",
            ],
        },
        "visualization": {
            "default_attempts_level_1": 2,
            "default_attempts_level_2": 2,
            "default_attempts_level_3": 2,
            "default_attempts_level_4": 2,
            "default_attempts_level_5": 2,
            "observation_pause_seconds": 0.12,
            "confidence_threshold": 0.70,
            "reacquire_delta_pixels": 24,
        },
        "browser_app": {
            "default_attempts_level_1": 3,
        },
        "document_editor": {
            "default_attempts_level_1": 3,
        },
        "site_workflow": {
            "default_attempts_level_1": 3,
        },
        "window_management": {
            "default_attempts_level_1": 1,
            "workflow_attempts_per_run": 3,
        },
    },
    "desktop_training": {
        "capture_size": [180, 140],
        "capture_delay_seconds": 3,
        "match_confidence": 0.8,
    },
    "desktop_organizer": {
        "root_folder_name": "_Raphel_Ordenado",
        "execution_mode": "ui_learning",
        "ui_move_gesture": "mixed_gradual",
        "max_batch_size": 50,
        "auto_continue_batches": True,
        "require_confirmation": True,
        "allow_legacy_filesystem_fallback": False,
        "close_temporary_explorer_windows": True,
        "max_temporary_explorer_windows": 2,
        "reuse_explorer_windows_per_session": True,
        "restore_previous_window_after_session": True,
        "require_mouse_practice_for_real_drag": True,
        "desktop_surface_source_first": True,
        "mouse_practice_root_name": "_Raphel_Practica_Mouse",
        "mouse_practice_attempts": 4,
        "mouse_practice_distractor_count_min": 6,
        "mouse_practice_distractor_count_max": 12,
        "mouse_movement_practice_attempts": 12,
        "mouse_click_practice_attempts": 20,
        "mouse_double_click_practice_attempts": 20,
        "mouse_right_click_practice_attempts": 20,
        "mouse_selection_practice_attempts": 20,
        "mouse_workflow_practice_attempts": 5,
        "mouse_practice_max_attempts": 100,
        "mouse_move_tolerance_pixels": 12,
        "mouse_practice_required_success_rate": 0.7,
        "mouse_practice_min_successes": 3,
        "move_shortcuts": False,
        "move_folders": False,
        "show_desktop_before_click": True,
        "skip_names": [
            "desktop.ini",
            "_Raphel_Ordenado",
        ],
    },
    "dangerous_keywords": [
        "delete",
        "remove",
        "format",
        "shutdown",
        "taskkill",
        "del ",
        "erase ",
    ],
    "gui": {
        "always_on_top": True,
        "alpha": 0.96,
    },
    "vision": {
        "enabled": True,
        "interval_seconds": 1.5,
        "light_ocr": True,
    },
}


def merge_defaults(defaults: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for key, default_value in defaults.items():
        current_value = current.get(key)
        if isinstance(default_value, dict) and isinstance(current_value, dict):
            merged[key] = merge_defaults(default_value, current_value)
        elif key in current:
            merged[key] = current_value
        else:
            merged[key] = default_value

    for key, value in current.items():
        if key not in merged:
            merged[key] = value
    return merged


class ConfigManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.config_path = base_dir / "config" / "settings.json"
        ensure_directory(self.config_path.parent)
        self.data = self._load_or_create()

    def _load_or_create(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            self.save(DEFAULT_CONFIG)
            return DEFAULT_CONFIG.copy()

        with self.config_path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)

        merged = merge_defaults(DEFAULT_CONFIG, loaded)
        if merged != loaded:
            self.save(merged)
        return merged

    def save(self, data: Dict[str, Any]) -> None:
        with self.config_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save(self.data)
