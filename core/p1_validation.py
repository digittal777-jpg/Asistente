from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.doctor import RaphelDoctor


@dataclass
class P1ValidationStep:
    name: str
    status: str
    detail: str
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class P1ValidationReport:
    generated_at: str
    project_root: str
    mode: str
    overall_status: str
    steps: List[P1ValidationStep]
    snapshots: Dict[str, str] = field(default_factory=dict)
    manual_checklist: List[str] = field(default_factory=list)
    next_actions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        if self.mode == "supervised_p1":
            payload["steps"] = {step.name: step.to_dict() for step in self.steps}
        else:
            payload["steps"] = [step.to_dict() for step in self.steps]
        return payload


class P1LiveValidator:
    TARGET_COMMANDS = {
        "research": "skill-practice investigar 1 intento",
        "youtube": "skill-practice youtube 1 intento",
        "word": "skill-practice word 1 intento",
        "keyboard": "skill-practice teclado 1 intento",
        "desktop_organize": "desktop-organize",
        "mouse_workflow": "desktop-practice-mouse-workflow 1",
    }

    MANUAL_CHECKLIST = [
        "Confirmar que Google abre una fuente real, no solo resultados.",
        "Confirmar que YouTube captura transcript o texto visible util.",
        "Confirmar que Word/editor tiene foco correcto antes de escribir.",
        "Confirmar que el teclado deja evidencia visible de escritura y foco.",
        "Confirmar que ordenar el escritorio produce cambios reales y no solo una simulacion.",
        "Confirmar que desktop-practice-mouse-workflow mueve solo archivos temporales.",
        "Confirmar que modales o dialogos no cuentan como exito.",
    ]

    def __init__(
        self,
        base_dir: Path,
        assistant_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.assistant_factory = assistant_factory

    def run(self, execute_live: bool = False, supervised: bool = False) -> P1ValidationReport:
        assistant = None
        assistant_owned = self.assistant_factory is None
        steps: List[P1ValidationStep] = []
        snapshots: Dict[str, str] = {}
        try:
            assistant = self._create_assistant()
            doctor = RaphelDoctor(self.base_dir, config=getattr(assistant, "config", None))
            doctor_report = doctor.run()
            steps.append(
                P1ValidationStep(
                    name="doctor",
                    status=doctor_report.overall_status,
                    detail=f"doctor={doctor_report.overall_status}",
                    evidence={"warnings": doctor_report.warnings, "next_actions": doctor_report.next_actions},
                )
            )

            for command_name, command in (
                ("learning_status", "learning-status"),
                ("research_status", "skill-status investigar"),
                ("youtube_status", "skill-status youtube"),
                ("word_status", "skill-status word"),
                ("mouse_status", "skill-status mouse"),
                ("input_training_status", "input-training-status"),
            ):
                snapshots[command_name] = self._capture_command(assistant, command)

            steps.extend(self._snapshot_steps(snapshots))
            steps.append(self._session_freshness_step())

            if supervised:
                steps.extend(self._run_supervised_training(assistant))
            elif execute_live:
                steps.extend(self._execute_live_attempts(assistant))
            else:
                steps.append(
                    P1ValidationStep(
                        name="live_attempts",
                        status="manual_required",
                        detail="usa --execute-live para correr intentos reales minimos",
                        evidence={"commands": dict(self.TARGET_COMMANDS)},
                    )
                )
        except Exception as exc:
            steps.append(P1ValidationStep("p1_runner", "fail", str(exc)))
        finally:
            if assistant is not None and assistant_owned:
                try:
                    assistant.shutdown()
                except Exception:
                    pass

        overall = self._overall_status(steps)
        next_actions = self._next_actions(steps, snapshots, execute_live)
        report = P1ValidationReport(
            generated_at=datetime.now().isoformat(timespec="seconds"),
            project_root=str(self.base_dir),
            mode="supervised_p1" if supervised else ("execute_live" if execute_live else "guided_snapshot"),
            overall_status=overall,
            steps=steps,
            snapshots=snapshots,
            manual_checklist=list(self.MANUAL_CHECKLIST),
            next_actions=next_actions,
        )
        if supervised:
            self.write_report(report, self.base_dir / "logs" / "p1_supervised_training.json")
        return report

    def write_report(self, report: P1ValidationReport, output_path: Optional[Path] = None) -> Path:
        path = output_path or self.base_dir / "logs" / "p1_validation_results.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @staticmethod
    def format_report(report: P1ValidationReport, output_path: Optional[Path] = None) -> str:
        lines = [
            "Raphel P1 Validation",
            f"- Estado general: {report.overall_status}",
            f"- Modo: {report.mode}",
        ]
        if output_path:
            lines.append(f"- Reporte JSON: {output_path}")
        lines.append("")
        for step in report.steps:
            marker = "[OK]" if step.status == "ok" else "[FAIL]" if step.status == "fail" else "[WARN]"
            lines.append(f"{marker} {step.name}: {step.detail}")
        if report.next_actions:
            lines.append("")
            lines.append("Siguientes acciones:")
            for action in report.next_actions:
                lines.append(f"- {action}")
        return "\n".join(lines)

    def _create_assistant(self) -> Any:
        if self.assistant_factory:
            return self.assistant_factory()
        from core.assistant import RaphelAssistant

        return RaphelAssistant()

    @staticmethod
    def _capture_command(assistant: Any, command: str) -> str:
        try:
            return str(assistant.handle_command(command))
        except Exception as exc:
            return f"ERROR: {exc}"

    def _snapshot_steps(self, snapshots: Dict[str, str]) -> List[P1ValidationStep]:
        steps: List[P1ValidationStep] = []
        for name, text in snapshots.items():
            status = "fail" if text.startswith("ERROR:") else "ok"
            if name.endswith("_status") and self._looks_stale(text):
                status = "warning"
            steps.append(
                P1ValidationStep(
                    name=name,
                    status=status,
                    detail=self._first_line(text),
                    evidence=self._status_evidence(text),
                )
            )
        return steps

    def _session_freshness_step(self) -> P1ValidationStep:
        session_dirs = [
            self.base_dir / "data" / "learning_skill_sessions",
            self.base_dir / "data" / "desktop_organizer_sessions",
        ]
        latest: Dict[str, str] = {}
        newest_ts = 0.0
        for directory in session_dirs:
            if not directory.exists():
                continue
            files = [item for item in directory.glob("*") if item.is_file()]
            if not files:
                continue
            newest = max(files, key=lambda item: item.stat().st_mtime)
            newest_ts = max(newest_ts, newest.stat().st_mtime)
            latest[directory.name] = newest.name
        if newest_ts <= 0:
            return P1ValidationStep("session_freshness", "warning", "sin sesiones previas detectadas", latest)
        age_days = max(0.0, (datetime.now().timestamp() - newest_ts) / 86400.0)
        status = "ok" if age_days <= 7 else "warning"
        return P1ValidationStep(
            "session_freshness",
            status,
            f"ultima evidencia hace {age_days:.1f} dia(s)",
            {"latest_files": latest, "age_days": round(age_days, 2)},
        )

    def _run_supervised_training(self, assistant: Any) -> List[P1ValidationStep]:
        steps: List[P1ValidationStep] = []
        previous = getattr(assistant, "_confirmation_provider", None)
        try:
            if hasattr(assistant, "set_confirmation_provider"):
                assistant.set_confirmation_provider(lambda _prompt: True)
            for name, command in self.TARGET_COMMANDS.items():
                result = self._capture_command(assistant, command)
                status = self._result_status(result)
                steps.append(
                    P1ValidationStep(
                        name=name,
                        status=status,
                        detail=self._first_line(result),
                        evidence={
                            "command": command,
                            "result_preview": result[:1200],
                            "failure_reason": self._extract_failure_reason(result),
                        },
                    )
                )
        finally:
            if hasattr(assistant, "set_confirmation_provider"):
                assistant.set_confirmation_provider(previous)
        return steps

    def _execute_live_attempts(self, assistant: Any) -> List[P1ValidationStep]:
        steps: List[P1ValidationStep] = []
        previous = getattr(assistant, "_confirmation_provider", None)
        try:
            if hasattr(assistant, "set_confirmation_provider"):
                assistant.set_confirmation_provider(lambda _prompt: True)
            for name, command in self.TARGET_COMMANDS.items():
                result = self._capture_command(assistant, command)
                status = self._result_status(result)
                steps.append(
                    P1ValidationStep(
                        name=f"live_{name}",
                        status=status,
                        detail=self._first_line(result),
                        evidence={"command": command, "result_preview": result[:1200]},
                    )
                )
        finally:
            if hasattr(assistant, "set_confirmation_provider"):
                assistant.set_confirmation_provider(previous)
        return steps

    @staticmethod
    def _extract_failure_reason(text: str) -> str:
        normalized = str(text or "").strip()
        if not normalized:
            return "sin detalle"
        for pattern in (r"reason=([^\s]+)", r"failure_reason=([^\s]+)", r"detail=([^\s]+)"):
            match = re.search(pattern, normalized, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        lower = normalized.lower()
        if any(token in lower for token in ("error", "fallo", "blocked", "bloquead")):
            return normalized.splitlines()[0][:220]
        return "sin detalle"

    @staticmethod
    def _result_status(text: str) -> str:
        normalized = text.lower()
        if text.startswith("ERROR:") or any(token in normalized for token in ("error:", "fallo", "blocked", "bloquead")):
            return "fail"
        if any(token in normalized for token in ("manual", "cancelad", "no se pudo", "readiness=no")):
            return "warning"
        return "ok"

    @staticmethod
    def _looks_stale(text: str) -> bool:
        normalized = text.lower()
        return any(
            token in normalized
            for token in (
                "sin verificacion",
                "readiness=no",
                "uso real listo: no",
                "estado: blocked",
                "estado: bloqueado",
            )
        )

    @staticmethod
    def _first_line(text: str) -> str:
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        return lines[0][:220] if lines else "sin salida"

    @staticmethod
    def _status_evidence(text: str) -> Dict[str, Any]:
        evidence: Dict[str, Any] = {"preview": str(text or "")[:1200]}
        status_match = re.search(r"- Estado:\s*(.+)", text)
        readiness_match = re.search(r"- Uso real listo:\s*(.+)", text)
        gate_match = re.search(r"- Gate siguiente:\s*(.+)", text)
        if status_match:
            evidence["status"] = status_match.group(1).strip()
        if readiness_match:
            evidence["real_usage_ready"] = readiness_match.group(1).strip()
        if gate_match:
            evidence["next_gate"] = gate_match.group(1).strip()
        return evidence

    @staticmethod
    def _overall_status(steps: List[P1ValidationStep]) -> str:
        if any(step.status == "fail" for step in steps):
            return "fail"
        if any(step.status in {"warning", "manual_required"} for step in steps):
            return "warning"
        return "ok"

    @staticmethod
    def _next_actions(
        steps: List[P1ValidationStep],
        snapshots: Dict[str, str],
        execute_live: bool,
    ) -> List[str]:
        actions: List[str] = []
        if not execute_live:
            actions.append("Correr VALIDATION_P1_LIVE.py --execute-live cuando el escritorio este preparado")
        for step in steps:
            if step.status == "fail":
                actions.append(f"Corregir fallo P1 en {step.name}: {step.detail}")
        research = snapshots.get("research_status", "")
        if "readiness=no" in research.lower() or "estancado" in research.lower():
            actions.append("Priorizar investigacion: abrir fuente real y medir texto util fuera de Google")
        word = snapshots.get("word_status", "")
        if "readiness=no" in word.lower() or "capture_selected_text" in word.lower():
            actions.append("Priorizar Word/editor: confirmar foco y releer texto en la misma sesion")
        return actions
