#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.doctor import RaphelDoctor


def main() -> int:
    doctor = RaphelDoctor(PROJECT_ROOT)
    report = doctor.run()
    output_path = doctor.write_report(report)
    print(doctor.format_report(report, output_path))
    return 1 if report.overall_status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
