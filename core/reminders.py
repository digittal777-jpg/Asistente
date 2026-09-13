from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List

from core.logging_utils import ensure_directory


class ReminderManager:
    def __init__(self, base_dir: Path, notifier: Callable[[str], None]) -> None:
        self.base_dir = base_dir
        self.notifier = notifier
        self.path = base_dir / "data" / "reminders.json"
        ensure_directory(self.path.parent)
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _load(self) -> List[Dict]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _save(self, reminders: List[Dict]) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(reminders, handle, indent=2, ensure_ascii=False)

    def add_in_seconds(self, message: str, seconds: int) -> Dict:
        due_at = datetime.now() + timedelta(seconds=seconds)
        reminder = {
            "message": message,
            "due_at": due_at.isoformat(timespec="seconds"),
            "done": False,
        }
        with self._lock:
            reminders = self._load()
            reminders.append(reminder)
            self._save(reminders)
        return reminder

    def list_reminders(self) -> List[Dict]:
        with self._lock:
            return self._load()

    def stop(self) -> None:
        self._running = False
        self._thread.join(timeout=1.0)

    def _loop(self) -> None:
        while self._running:
            try:
                with self._lock:
                    reminders = self._load()
                    updated = False
                    now = datetime.now()
                    for reminder in reminders:
                        if reminder.get("done"):
                            continue
                        due_at = datetime.fromisoformat(reminder["due_at"])
                        if due_at <= now:
                            reminder["done"] = True
                            updated = True
                            self.notifier(
                                f"[RECORDATORIO] {reminder['message']} | vencio a las {reminder['due_at']}"
                            )
                    if updated:
                        self._save(reminders)
            except Exception:
                pass
            time.sleep(1.0)
