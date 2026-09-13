from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def setup_logger(base_dir: Path) -> logging.Logger:
    logs_dir = base_dir / "logs"
    ensure_directory(logs_dir)

    logger = logging.getLogger("raphel")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = logging.FileHandler(logs_dir / "raphel.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger


class ActionHistory:
    def __init__(self, base_dir: Path) -> None:
        from core.data_paths import DataPaths

        self.paths = DataPaths.from_base_dir(base_dir)
        self.history_path = self.paths.action_history_path
        ensure_directory(self.history_path.parent)

    def record(self, action: str, payload: Dict[str, Any]) -> None:
        entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "action": action,
            "payload": payload,
        }
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
