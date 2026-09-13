from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from core.data_paths import DataPaths


@dataclass
class DoctorCheck:
    name: str
    status: str
    detail: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DoctorReport:
    generated_at: str
    project_root: str
    overall_status: str
    checks: List[DoctorCheck]
    warnings: List[str] = field(default_factory=list)
    next_actions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["checks"] = [check.to_dict() for check in self.checks]
        return payload


class RaphelDoctor:
    REQUIRED_MODULES = (
        "mss",
        "PIL",
        "cv2",
        "numpy",
        "pytesseract",
        "pyautogui",
        "pyperclip",
        "keyboard",
        "mouse",
        "customtkinter",
        "pygetwindow",
        "pycaw",
        "comtypes",
        "rapidfuzz",
    )

    RUNTIME_IGNORE_DIRS = {".pytest_cache", "__pycache__", ".venv", "venv"}

    def __init__(self, base_dir: Path, config: Optional[Any] = None) -> None:
        self.base_dir = Path(base_dir)
        self.paths = DataPaths.from_base_dir(self.base_dir)
        self.config = config

    def run(self) -> DoctorReport:
        checks = [
            self._check_python(),
            self._check_required_modules(),
            self._check_tesseract(),
            self._check_config_files(),
            self._check_application_paths(),
            self._check_runtime_data(),
            self._check_project_hygiene(),
            self._check_remote_console_secret_surface(),
        ]
        warnings = self._warnings(checks)
        next_actions = self._next_actions(checks)
        overall = self._overall_status(checks)
        return DoctorReport(
            generated_at=datetime.now().isoformat(timespec="seconds"),
            project_root=str(self.base_dir),
            overall_status=overall,
            checks=checks,
            warnings=warnings,
            next_actions=next_actions,
        )

    def write_report(self, report: DoctorReport, output_path: Optional[Path] = None) -> Path:
        path = output_path or self.base_dir / "logs" / "doctor_report.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def format_report(self, report: DoctorReport, output_path: Optional[Path] = None) -> str:
        lines = [
            "Raphel Doctor",
            f"- Estado general: {report.overall_status}",
            f"- Proyecto: {report.project_root}",
        ]
        if output_path:
            lines.append(f"- Reporte JSON: {output_path}")
        lines.append("")
        lines.append("Checks:")
        for check in report.checks:
            marker = "[OK]" if check.status == "ok" else "[WARN]" if check.status == "warning" else "[FAIL]"
            detail = f" :: {check.detail}" if check.detail else ""
            lines.append(f"{marker} {check.name}{detail}")
        if report.next_actions:
            lines.append("")
            lines.append("Siguientes acciones:")
            for action in report.next_actions:
                lines.append(f"- {action}")
        return "\n".join(lines)

    def _check_python(self) -> DoctorCheck:
        version = sys.version_info
        status = "ok" if version >= (3, 11) else "warning"
        detail = f"Python {version.major}.{version.minor}.{version.micro}"
        return DoctorCheck("python", status, detail, {"executable": sys.executable})

    def _check_required_modules(self) -> DoctorCheck:
        missing = [
            module_name
            for module_name in self.REQUIRED_MODULES
            if importlib.util.find_spec(module_name) is None
        ]
        status = "ok" if not missing else "fail"
        detail = "todas las dependencias importables" if not missing else "faltan: " + ", ".join(missing)
        return DoctorCheck("python_dependencies", status, detail, {"missing": missing})

    def _check_tesseract(self) -> DoctorCheck:
        executable = shutil.which("tesseract")
        if executable:
            return DoctorCheck("tesseract", "ok", executable, {"path": executable})
        return DoctorCheck(
            "tesseract",
            "fail",
            "no se encontro tesseract en PATH; OCR real puede fallar",
        )

    def _check_config_files(self) -> DoctorCheck:
        required = [
            self.base_dir / "pyproject.toml",
            self.base_dir / "requirements.txt",
            self.base_dir / "README.md",
            self.base_dir / "config" / "settings.json",
        ]
        missing = [str(path.relative_to(self.base_dir)) for path in required if not path.exists()]
        status = "ok" if not missing else "fail"
        detail = "archivos base presentes" if not missing else "faltan: " + ", ".join(missing)
        return DoctorCheck("project_files", status, detail, {"missing": missing})

    def _check_application_paths(self) -> DoctorCheck:
        config = self._config_payload()
        browser_paths = dict(config.get("browser_paths", {}) or {})
        apps = dict(config.get("applications", {}) or {})
        targets: Dict[str, Iterable[str]] = {
            "brave": browser_paths.get("brave", []),
            "chrome": browser_paths.get("chrome", []),
            "edge": browser_paths.get("edge", []),
            "word": self._app_candidates(apps.get("word", {})),
            "vscode": self._app_candidates(apps.get("visual studio code", {})),
        }
        resolved: Dict[str, str] = {}
        missing: List[str] = []
        for name, candidates in targets.items():
            found = self._first_existing_executable(candidates)
            if found:
                resolved[name] = found
            else:
                missing.append(name)
        status = "ok" if not missing else "warning"
        detail = "apps criticas detectadas" if not missing else "no detectadas: " + ", ".join(missing)
        return DoctorCheck("desktop_applications", status, detail, {"resolved": resolved, "missing": missing})

    def _check_runtime_data(self) -> DoctorCheck:
        data_dir = self.paths.data_dir
        total_files, total_bytes = self._measure_files(data_dir)
        archive_files, archive_bytes = self._measure_files(self.paths.archive_dir)
        db_bytes = self.paths.raphel_memory_db_path.stat().st_size if self.paths.raphel_memory_db_path.exists() else 0
        status = "ok"
        detail = f"{total_files} archivo(s), {self._fmt_mb(total_bytes)} MB"
        if total_bytes > 1024 * 1024 * 1024:
            status = "warning"
            detail += " | data grande para iterar"
        return DoctorCheck(
            "runtime_data",
            status,
            detail,
            {
                "file_count": total_files,
                "total_mb": round(total_bytes / 1024 / 1024, 2),
                "archive_file_count": archive_files,
                "archive_mb": round(archive_bytes / 1024 / 1024, 2),
                "raphel_memory_db_mb": round(db_bytes / 1024 / 1024, 2),
            },
        )

    def _check_project_hygiene(self) -> DoctorCheck:
        git_dir = self.base_dir / ".git"
        gitignore = self.base_dir / ".gitignore"
        gitignore_text = gitignore.read_text(encoding="utf-8", errors="ignore") if gitignore.exists() else ""
        ignores_data = any(
            line.strip().rstrip("/") == "data"
            for line in gitignore_text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
        generated_dirs = [
            str(path.relative_to(self.base_dir))
            for path in self.base_dir.rglob("*")
            if path.is_dir() and path.name in self.RUNTIME_IGNORE_DIRS
        ]
        issues = []
        if not git_dir.exists():
            issues.append("sin .git")
        if not ignores_data:
            issues.append("data no ignorado")
        status = "ok" if not issues else "warning"
        detail = "higiene base correcta" if not issues else ", ".join(issues)
        return DoctorCheck(
            "project_hygiene",
            status,
            detail,
            {"git_initialized": git_dir.exists(), "data_ignored": ignores_data, "generated_dirs": generated_dirs[:20]},
        )

    def _check_remote_console_secret_surface(self) -> DoctorCheck:
        history_path = self.paths.action_history_path
        token_url_hits = 0
        if history_path.exists():
            try:
                with history_path.open("r", encoding="utf-8", errors="ignore") as handle:
                    for line in handle:
                        if "?token=" in line or "Authorization" in line:
                            token_url_hits += 1
            except Exception:
                return DoctorCheck("remote_console_history", "warning", "no se pudo inspeccionar historial")
        status = "ok" if token_url_hits == 0 else "warning"
        detail = "sin tokens obvios en historial" if token_url_hits == 0 else f"{token_url_hits} linea(s) con posible token"
        return DoctorCheck("remote_console_history", status, detail, {"possible_secret_lines": token_url_hits})

    def _config_payload(self) -> Dict[str, Any]:
        if self.config is not None:
            try:
                if hasattr(self.config, "data"):
                    return dict(getattr(self.config, "data") or {})
                if hasattr(self.config, "get"):
                    return {
                        "browser_paths": self.config.get("browser_paths", {}),
                        "applications": self.config.get("applications", {}),
                    }
            except Exception:
                pass
        path = self.base_dir / "config" / "settings.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return {}

    @staticmethod
    def _app_candidates(entry: Any) -> List[str]:
        if isinstance(entry, dict):
            candidates = [str(entry.get("command", ""))]
            candidates.extend(str(path) for path in entry.get("paths", []) or [])
            return [candidate for candidate in candidates if candidate]
        if entry:
            return [str(entry)]
        return []

    @staticmethod
    def _first_existing_executable(candidates: Iterable[str]) -> str:
        for candidate in candidates:
            expanded = os.path.expandvars(str(candidate))
            if Path(expanded).exists():
                return str(Path(expanded))
            located = shutil.which(expanded)
            if located:
                return located
        return ""

    @staticmethod
    def _measure_files(path: Path) -> tuple[int, int]:
        if not path.exists():
            return 0, 0
        count = 0
        total = 0
        for item in path.rglob("*"):
            if item.is_file():
                count += 1
                try:
                    total += item.stat().st_size
                except OSError:
                    continue
        return count, total

    @staticmethod
    def _fmt_mb(byte_count: int) -> str:
        return f"{byte_count / 1024 / 1024:.2f}"

    @staticmethod
    def _overall_status(checks: List[DoctorCheck]) -> str:
        if any(check.status == "fail" for check in checks):
            return "fail"
        if any(check.status == "warning" for check in checks):
            return "warning"
        return "ok"

    @staticmethod
    def _warnings(checks: List[DoctorCheck]) -> List[str]:
        return [f"{check.name}: {check.detail}" for check in checks if check.status == "warning"]

    @staticmethod
    def _next_actions(checks: List[DoctorCheck]) -> List[str]:
        by_name = {check.name: check for check in checks}
        actions: List[str] = []
        if by_name.get("python_dependencies", DoctorCheck("", "ok")).status == "fail":
            actions.append("Instalar dependencias con: py -m pip install -r requirements.txt")
        if by_name.get("tesseract", DoctorCheck("", "ok")).status == "fail":
            actions.append("Instalar Tesseract OCR y agregar tesseract.exe al PATH")
        hygiene = by_name.get("project_hygiene")
        if hygiene and not hygiene.data.get("git_initialized", True):
            actions.append("Inicializar Git antes de cambios grandes: git init")
        if hygiene and not hygiene.data.get("data_ignored", True):
            actions.append("Ignorar data/ o mover runtime fuera del repo antes de versionar")
        runtime = by_name.get("runtime_data")
        if runtime and runtime.status == "warning":
            actions.append("Compactar o archivar fuera del proyecto data/archive y bases SQLite grandes")
        secrets = by_name.get("remote_console_history")
        if secrets and secrets.status == "warning":
            actions.append("Redactar tokens del historial antes de compartir respaldos o inicializar Git")
        return actions
