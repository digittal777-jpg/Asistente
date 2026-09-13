#!/usr/bin/env python3
"""
Quick integrity check for the current Raphel codebase.

This script stays intentionally lightweight: it validates that the current
assistant stack imports correctly and that the most critical learning paths
still expose the expected APIs and safeguards.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))


def print_status(ok: bool, label: str, detail: str = "") -> None:
    prefix = "[OK]" if ok else "[FAIL]"
    suffix = f": {detail}" if detail else ""
    print(f"{prefix} {label}{suffix}")


def load_core_objects():
    from core.assistant import RaphelAssistant
    from core.learning_skill_engine import LearningSkillEngine

    return RaphelAssistant, LearningSkillEngine


def check_research_capture_fix(engine_cls) -> bool:
    print("\n" + "=" * 60)
    print("CHECK 1: Research Page Capture")
    print("=" * 60)
    try:
        source = inspect.getsource(engine_cls._capture_research_page_text)
    except Exception as exc:
        print_status(False, "Source inspection", str(exc))
        return False

    checks = {
        "Context capture first": "self._capture_context(refresh=True)" in source,
        "Modal detection": "_unexpected_modal_reason" in source,
        "File dialog detection": "file_dialog_detected" in source,
        "Modal detected flag": '"modal_detected"' in source,
    }
    all_good = True
    for label, passed in checks.items():
        print_status(passed, label)
        all_good = all_good and passed
    return all_good


def check_youtube_capture_integrity(engine_cls) -> bool:
    print("\n" + "=" * 60)
    print("CHECK 2: YouTube Capture Pipeline")
    print("=" * 60)
    methods_to_check = [
        ("_capture_youtube_learning_evidence", "Combined capture method"),
        ("_capture_youtube_transcript_text", "Transcript extraction"),
        ("_capture_youtube_page_text", "Visible text extraction"),
    ]
    all_good = True
    for method_name, description in methods_to_check:
        exists = hasattr(engine_cls, method_name) and callable(getattr(engine_cls, method_name))
        print_status(exists, description, method_name)
        all_good = all_good and exists
    return all_good


def check_project_entrypoints(assistant_cls, engine_cls) -> bool:
    print("\n" + "=" * 60)
    print("CHECK 3: Project Entry Points")
    print("=" * 60)
    checks = {
        "Assistant class": inspect.isclass(assistant_cls),
        "Learning engine class": inspect.isclass(engine_cls),
        "Root README present": (PROJECT_ROOT / "README.md").exists(),
        "Docs index present": (PROJECT_ROOT / "docs" / "README.md").exists(),
        "Pyproject present": (PROJECT_ROOT / "pyproject.toml").exists(),
    }
    all_good = True
    for label, passed in checks.items():
        print_status(passed, label)
        all_good = all_good and passed
    return all_good


def main() -> int:
    print("\n" + "=" * 60)
    print("RAPHEL QUICK VALIDATION CHECK")
    print("=" * 60)
    print(f"Project root: {PROJECT_ROOT}")

    try:
        assistant_cls, engine_cls = load_core_objects()
        print_status(True, "Core modules loaded successfully")
    except Exception as exc:
        print_status(False, "Core modules loaded successfully", str(exc))
        return 1

    results = [
        ("Research Page Capture", check_research_capture_fix(engine_cls)),
        ("YouTube Capture Pipeline", check_youtube_capture_integrity(engine_cls)),
        ("Project Entry Points", check_project_entrypoints(assistant_cls, engine_cls)),
    ]

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, result in results if result)
    total = len(results)
    for label, ok in results:
        print_status(ok, label)
    print(f"\nTotal: {passed}/{total} checks passed")

    if passed == total:
        print("\nAll quick integrity checks passed.")
        print("Next: run RUN_VALIDATION.bat if you want the manual live validation flow.")
        return 0

    print("\nOne or more checks failed. Review the details above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
