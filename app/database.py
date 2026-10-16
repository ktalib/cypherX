import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.config import DB_PATH

logger = logging.getLogger("CyberOps.Database")

class Database:
    _instance = None

    @classmethod
    def get_instance(cls) -> "Database":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Settings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Operation History table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS operation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    operation_type TEXT NOT NULL,
                    target_path TEXT,
                    action TEXT NOT NULL,
                    result TEXT NOT NULL,
                    can_undo INTEGER DEFAULT 0,
                    undo_data TEXT,
                    error_msg TEXT
                )
            """)

            # Notes and Tasks table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    category TEXT DEFAULT 'General',
                    due_date TEXT,
                    completed INTEGER DEFAULT 0,
                    priority TEXT DEFAULT 'Medium',
                    created_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Application Launcher shortcuts
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS launcher_shortcuts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    category TEXT DEFAULT 'Utility',
                    icon_hint TEXT,
                    launch_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)

            # Automation rules
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS automations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    schedule TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    last_run TEXT
                )
            """)

            conn.commit()

    # Settings API
    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                try:
                    return json.loads(row["value"])
                except Exception:
                    return row["value"]
            return default

    def set_setting(self, key: str, value: Any) -> None:
        val_str = json.dumps(value)
        now_str = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """, (key, val_str, now_str))
            conn.commit()

    # Operation History API
    def log_operation(self, operation_type: str, action: str, result: str,
                      target_path: Optional[str] = None, can_undo: bool = False,
                      undo_data: Optional[Dict] = None, error_msg: Optional[str] = None) -> int:
        undo_str = json.dumps(undo_data) if undo_data else None
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO operation_history (timestamp, operation_type, target_path, action, result, can_undo, undo_data, error_msg)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (now_str, operation_type, target_path, action, result, 1 if can_undo else 0, undo_str, error_msg))
            conn.commit()
            return cursor.lastrowid

    def get_operations(self, limit: int = 100, filter_type: Optional[str] = None) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if filter_type:
                cursor.execute("""
                    SELECT * FROM operation_history 
                    WHERE operation_type = ? 
                    ORDER BY id DESC LIMIT ?
                """, (filter_type, limit))
            else:
                cursor.execute("SELECT * FROM operation_history ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def mark_operation_undone(self, op_id: int) -> None:
        with self._get_connection() as conn:
            conn.cursor().execute(
                "UPDATE operation_history SET can_undo = 0, result = result || ' (undone)' WHERE id = ?", (op_id,))
            conn.commit()

    def clear_operation_history(self) -> None:
        with self._get_connection() as conn:
            conn.cursor().execute("DELETE FROM operation_history")
            conn.commit()

    # Tasks API
    def get_tasks(self, include_completed: bool = True) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if include_completed:
                cursor.execute("SELECT * FROM tasks ORDER BY completed ASC, id DESC")
            else:
                cursor.execute("SELECT * FROM tasks WHERE completed = 0 ORDER BY id DESC")
            return [dict(row) for row in cursor.fetchall()]

    def add_task(self, title: str, category: str = "General", due_date: Optional[str] = None, priority: str = "Medium") -> int:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tasks (title, category, due_date, priority, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (title, category, due_date, priority, now_str))
            conn.commit()
            return cursor.lastrowid

    def update_task_status(self, task_id: int, completed: bool) -> None:
        with self._get_connection() as conn:
            conn.cursor().execute("UPDATE tasks SET completed = ? WHERE id = ?", (1 if completed else 0, task_id))
            conn.commit()

    def delete_task(self, task_id: int) -> None:
        with self._get_connection() as conn:
            conn.cursor().execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
