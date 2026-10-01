"""Append-only SQLite audit log. Every engine/simulator record change is appended here."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    epoch INTEGER NOT NULL,
    state_version INTEGER NOT NULL,
    sim_time TEXT NOT NULL,
    actor TEXT NOT NULL,
    kind TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_run ON audit(run_id, epoch, seq);
"""


class AuditLog:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def append(self, run_id: str, epoch: int, state_version: int, sim_time: datetime,
               actor: str, kind: str, ref_id: str, body: Any) -> None:
        payload = json.dumps(body, default=str, ensure_ascii=False, sort_keys=True)
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit(run_id, epoch, state_version, sim_time, actor, kind, ref_id, body)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (run_id, epoch, state_version, sim_time.isoformat(), actor, kind, ref_id, payload),
            )
            self._conn.commit()

    def query(self, run_id: str, epoch: int, after_seq: int = 0, limit: int = 500) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, state_version, sim_time, actor, kind, ref_id, body FROM audit"
                " WHERE run_id=? AND epoch=? AND seq>? ORDER BY seq LIMIT ?",
                (run_id, epoch, after_seq, limit),
            ).fetchall()
        return [
            {"seq": r[0], "state_version": r[1], "sim_time": r[2], "actor": r[3],
             "kind": r[4], "ref_id": r[5], "body": json.loads(r[6])}
            for r in rows
        ]
