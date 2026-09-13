from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from core.data_paths import DataPaths
from core.logging_utils import ensure_directory
from core.skills import normalize_text


class MemoryStore:
    """Memoria persistente de Raphel.

    Guarda:
    - interacciones y resultados
    - planes/tareas complejas
    - snapshots ligeros de vision
    - preferencias inferidas del uso
    """

    def __init__(self, base_dir: Path, db_name: str = "raphel_memory.db") -> None:
        self.base_dir = Path(base_dir)
        self.paths = DataPaths.from_base_dir(self.base_dir)
        self.db_path = self.paths.raphel_memory_db_path
        if db_name != "raphel_memory.db":
            self.db_path = self.paths.data_dir / db_name
        ensure_directory(self.db_path.parent)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    user_command TEXT NOT NULL,
                    normalized_command TEXT NOT NULL,
                    actions_json TEXT NOT NULL,
                    result TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    context_json TEXT
                );

                CREATE TABLE IF NOT EXISTS task_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    original_command TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    status TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    result_summary TEXT
                );

                CREATE TABLE IF NOT EXISTS vision_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    active_window TEXT,
                    active_app TEXT,
                    active_site TEXT,
                    confidence REAL NOT NULL,
                    snapshot_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS preferences (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS step_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    task_intent TEXT NOT NULL,
                    step_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS document_outputs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    path TEXT NOT NULL,
                    application TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS desktop_learning_sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    desktop_path TEXT NOT NULL,
                    root_folder TEXT NOT NULL,
                    manifest_path TEXT NOT NULL,
                    summary_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS desktop_learning_moves (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    category TEXT NOT NULL,
                    gesture TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    verified INTEGER NOT NULL,
                    details_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_interactions_normalized
                    ON interactions(normalized_command);
                CREATE INDEX IF NOT EXISTS idx_interactions_created_at
                    ON interactions(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_vision_created_at
                    ON vision_snapshots(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_step_logs_created_at
                    ON step_logs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_desktop_learning_moves_session
                    ON desktop_learning_moves(session_id);
                """
            )

    def learn_from_interaction(
        self,
        user_command: str,
        actions_taken: Iterable[Dict[str, Any]],
        result: str,
        context: Optional[Dict[str, Any]] = None,
        success: Optional[bool] = None,
    ) -> int:
        created_at = datetime.now().isoformat(timespec="seconds")
        normalized = normalize_text(user_command)
        serialized_actions = json.dumps(list(actions_taken), ensure_ascii=False)
        serialized_context = json.dumps(context or {}, ensure_ascii=False)
        resolved_success = success if success is not None else not str(result).lower().startswith("error")

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO interactions (
                    created_at,
                    user_command,
                    normalized_command,
                    actions_json,
                    result,
                    success,
                    context_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    user_command,
                    normalized,
                    serialized_actions,
                    str(result),
                    int(bool(resolved_success)),
                    serialized_context,
                ),
            )
            interaction_id = int(cursor.lastrowid)

        self._learn_preferences_from_actions(actions_taken, bool(resolved_success))
        return interaction_id

    def record_task_plan(self, original_command: str, intent: str, plan: Dict[str, Any]) -> int:
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO task_runs (
                    created_at,
                    original_command,
                    intent,
                    status,
                    plan_json,
                    result_summary
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    original_command,
                    intent,
                    "planned",
                    json.dumps(plan, ensure_ascii=False),
                    "",
                ),
            )
            return int(cursor.lastrowid)

    def update_task_run(self, task_id: int, status: str, result_summary: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE task_runs
                SET status = ?, result_summary = ?
                WHERE id = ?
                """,
                (status, result_summary, task_id),
            )

    def save_vision_snapshot(self, snapshot: Any) -> None:
        payload = self._serialize(snapshot)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO vision_snapshots (
                    created_at,
                    active_window,
                    active_app,
                    active_site,
                    confidence,
                    snapshot_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.get("captured_at", datetime.now().isoformat(timespec="seconds")),
                    payload.get("active_window"),
                    payload.get("active_app"),
                    payload.get("active_site"),
                    float(payload.get("confidence", 0.0)),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )

    def record_step_log(
        self,
        task_intent: str,
        step_name: str,
        status: str,
        detail: str,
    ) -> None:
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO step_logs (created_at, task_intent, step_name, status, detail)
                VALUES (?, ?, ?, ?, ?)
                """,
                (created_at, task_intent, step_name, status, detail),
            )

    def record_document_output(
        self,
        path: str,
        application: str,
        status: str,
        title: str,
    ) -> None:
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO document_outputs (created_at, path, application, status, title)
                VALUES (?, ?, ?, ?, ?)
                """,
                (created_at, path, application, status, title),
            )

    def record_desktop_learning_session(
        self,
        session_id: str,
        mode: str,
        desktop_path: str,
        root_folder: str,
        manifest_path: str,
        summary: Dict[str, Any],
    ) -> None:
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO desktop_learning_sessions (
                    session_id,
                    created_at,
                    mode,
                    desktop_path,
                    root_folder,
                    manifest_path,
                    summary_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    mode = excluded.mode,
                    desktop_path = excluded.desktop_path,
                    root_folder = excluded.root_folder,
                    manifest_path = excluded.manifest_path,
                    summary_json = excluded.summary_json
                """,
                (
                    session_id,
                    created_at,
                    mode,
                    desktop_path,
                    root_folder,
                    manifest_path,
                    json.dumps(summary, ensure_ascii=False),
                ),
            )

    def record_desktop_learning_move(
        self,
        session_id: str,
        source: str,
        destination: str,
        category: str,
        gesture: str,
        status: str,
        error: str,
        duration_seconds: float,
        verified: bool,
        details: Dict[str, Any],
    ) -> None:
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO desktop_learning_moves (
                    created_at,
                    session_id,
                    source,
                    destination,
                    category,
                    gesture,
                    status,
                    error,
                    duration_seconds,
                    verified,
                    details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    session_id,
                    source,
                    destination,
                    category,
                    gesture,
                    status,
                    error,
                    float(duration_seconds),
                    int(bool(verified)),
                    json.dumps(details, ensure_ascii=False),
                ),
            )

    def get_recent_interactions(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT created_at, user_command, actions_json, result, success, context_json
                FROM interactions
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_interaction(row) for row in rows]

    def get_recent_task_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, created_at, original_command, intent, status, plan_json, result_summary
                FROM task_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        results: List[Dict[str, Any]] = []
        for row in rows:
            results.append(
                {
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "original_command": row["original_command"],
                    "intent": row["intent"],
                    "status": row["status"],
                    "plan": json.loads(row["plan_json"] or "{}"),
                    "result_summary": row["result_summary"] or "",
                }
            )
        return results

    def get_recent_step_logs(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT created_at, task_intent, step_name, status, detail
                FROM step_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "created_at": row["created_at"],
                "task_intent": row["task_intent"],
                "step_name": row["step_name"],
                "status": row["status"],
                "detail": row["detail"],
            }
            for row in rows
        ]

    def get_recent_vision_context(self) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT snapshot_json
                FROM vision_snapshots
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        if not row:
            return None
        return json.loads(row["snapshot_json"] or "{}")

    def get_preference(self, key: str, default: Any = None) -> Any:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM preferences WHERE key = ?",
                (key,),
            ).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value_json"])
        except json.JSONDecodeError:
            return default

    def set_preference(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        updated_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO preferences (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (key, payload, updated_at),
            )

    def summarize_recent_memory(self, limit: int = 5) -> str:
        interactions = self.get_recent_interactions(limit=limit)
        if not interactions:
            return "Memoria reciente vacia."
        lines = []
        for item in interactions:
            state = "ok" if item["success"] else "error"
            lines.append(f"- [{item['created_at']}] {state}: {item['user_command']}")
        return "\n".join(lines)

    def _learn_preferences_from_actions(
        self,
        actions_taken: Iterable[Dict[str, Any]],
        success: bool,
    ) -> None:
        if not success:
            return

        browser: Optional[str] = None
        document_app: Optional[str] = None
        for action in actions_taken:
            params = action.get("params", {})
            browser = browser or params.get("browser")
            if action.get("action") in {"open_browser", "ensure_browser"} and params.get("browser"):
                browser = str(params["browser"])
            if action.get("action") in {"create_document", "execute_complex_task"}:
                document_app = params.get("application") or params.get("document_app") or document_app

        if browser:
            self.set_preference("preferred_browser", browser)
        if document_app:
            self.set_preference("preferred_document_app", document_app)

    @staticmethod
    def _serialize(value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, dict):
            return value
        if hasattr(value, "__dict__"):
            return dict(value.__dict__)
        return {"value": str(value)}

    @staticmethod
    def _row_to_interaction(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "created_at": row["created_at"],
            "user_command": row["user_command"],
            "actions": json.loads(row["actions_json"] or "[]"),
            "result": row["result"],
            "success": bool(row["success"]),
            "context": json.loads(row["context_json"] or "{}"),
        }
