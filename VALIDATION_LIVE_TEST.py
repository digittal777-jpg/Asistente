#!/usr/bin/env python3
"""
Guided live validation runner for the current Raphel project.

This is intentionally honest: it does not claim to automate every desktop
interaction by itself. Instead, it validates the current runtime entrypoints,
captures the latest skill-readiness snapshots, and writes a report the user can
review while performing manual desktop checks.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.assistant import RaphelAssistant


def print_status(ok: bool, label: str, detail: str = "") -> None:
    prefix = "[OK]" if ok else "[FAIL]"
    suffix = f": {detail}" if detail else ""
    print(f"{prefix} {label}{suffix}")


def main() -> int:
    print("\n" + "=" * 60)
    print("RAPHEL GUIDED LIVE VALIDATION")
    print("=" * 60)
    print(f"Project root: {PROJECT_ROOT}")

    assistant = None
    try:
        assistant = RaphelAssistant()
        learning_status = assistant.handle_command("learning-status")
        research_status = assistant.handle_command("skill-status investigar")
        youtube_status = assistant.handle_command("skill-status youtube")
        validation_time = datetime.now().isoformat()

        report = {
            "generated_at": validation_time,
            "project_root": str(PROJECT_ROOT),
            "mode": "guided_live_validation",
            "checks": {
                "docs_index_present": (PROJECT_ROOT / "docs" / "README.md").exists(),
                "quick_check_present": (PROJECT_ROOT / "QUICK_VALIDATION_CHECK.py").exists(),
                "run_validation_bat_present": (PROJECT_ROOT / "RUN_VALIDATION.bat").exists(),
            },
            "snapshots": {
                "learning_status": learning_status,
                "research_status": research_status,
                "youtube_status": youtube_status,
            },
            "manual_checklist": [
                "Abrir Brave o Chrome y confirmar que la busqueda real sigue saliendo de Google a una fuente valida.",
                "Abrir YouTube y confirmar que transcript o texto visible se pueden capturar sin caer en Ctrl+A ciego.",
                "Abrir Word o el editor objetivo y verificar foco correcto antes de escribir o releer.",
            ],
        }

        output_path = PROJECT_ROOT / "logs" / "validation_results.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

        print_status(True, "Assistant runtime", "loaded successfully")
        print_status(True, "Learning snapshot", "captured")
        print_status(True, "Research status", "captured")
        print_status(True, "YouTube status", "captured")
        print_status(True, "Validation report", str(output_path))

        print("\n" + "=" * 60)
        print("MANUAL CHECKLIST")
        print("=" * 60)
        for item in report["manual_checklist"]:
            print(f"- {item}")

        print("\nSaved guided validation report to:")
        print(output_path)
        print("\nThis runner verifies readiness and current status surfaces.")
        print("Use it together with the manual checklist above for true live validation.")
        return 0
    except Exception as exc:
        print_status(False, "Guided live validation", str(exc))
        return 1
    finally:
        if assistant is not None:
            try:
                assistant.shutdown()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
