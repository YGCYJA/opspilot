from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path


def redact(value: str) -> str:
    value = re.sub(r"(?i)bearer\s+[^\s\"',;]+", "Bearer [REDACTED]", value)
    return re.sub(r"\bsk-[A-Za-z0-9_-]{6,}", "[REDACTED]", value)


def redact_value(value, secrets: tuple[str, ...] = ()):
    """Redact structured results without modifying their JSON structure."""
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return redact(value)
    if isinstance(value, list):
        return [redact_value(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: redact_value(item, secrets) for key, item in value.items()}
    return value


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, session TEXT, created TEXT, body TEXT)")
            db.execute("CREATE INDEX IF NOT EXISTS runs_session ON runs(session, created)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def save(self, result: dict) -> None:
        body = json.dumps(redact_value(result), ensure_ascii=False)
        with self.connect() as db:
            db.execute("INSERT INTO runs VALUES (?, ?, ?, ?)",
                       (result["run_id"], result["session_id"], result["created_at"], body))

    def get(self, run_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT body FROM runs WHERE id = ?", (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def previous(self, session_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT body FROM runs WHERE session = ? ORDER BY created DESC, rowid DESC LIMIT 1",
                             (session_id,)).fetchone()
        return json.loads(row[0]) if row else None
