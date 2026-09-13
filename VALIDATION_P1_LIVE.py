#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.p1_validation import P1LiveValidator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validacion P1 honesta para Raphel.")
    parser.add_argument(
        "--execute-live",
        action="store_true",
        help="Ejecuta intentos reales minimos; movera ventanas/mouse si el flujo lo requiere.",
    )
    parser.add_argument(
        "--supervised",
        action="store_true",
        help="Ejecuta entrenamientos supervisados cortos y guarda el motivo exacto del fallo.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    validator = P1LiveValidator(PROJECT_ROOT)
    report = validator.run(execute_live=args.execute_live, supervised=args.supervised)
    output_path = validator.write_report(report)
    print(validator.format_report(report, output_path))
    return 1 if report.overall_status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
