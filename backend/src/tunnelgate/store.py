"""SQLite storage for the audit log and tunnel config snapshots."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("tunnelgate.audit")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    outcome TEXT NOT NULL,
    detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS config_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    tunnel_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    config TEXT NOT NULL,
    meta TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS sessions (
    sid TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    expires REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_tunnel ON config_snapshots (tunnel_id, id);
"""
_KEEP_SNAPSHOTS = 50


class Store:
    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "tunnelgate.db"
        old_umask = os.umask(0o077)
        try:
            self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        finally:
            os.umask(old_umask)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._lock = asyncio.Lock()

    def close(self) -> None:
        self._conn.close()

    async def _run(self, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        async with self._lock:
            return await asyncio.to_thread(lambda: self._conn.execute(sql, params).fetchall())

    async def audit(
        self, actor: str, action: str, target: str, outcome: str, **detail: Any
    ) -> None:
        log.info(
            "audit %s",
            json.dumps(
                {"actor": actor, "action": action, "target": target, "outcome": outcome, **detail},
                sort_keys=True,
                default=str,
            ),
        )
        await self._run(
            "INSERT INTO audit_log (ts, actor, action, target, outcome, detail) "
            "VALUES (?,?,?,?,?,?)",
            (time.time(), actor, action, target, outcome, json.dumps(detail, default=str)),
        )

    async def save_snapshot(
        self, tunnel_id: str, actor: str, reason: str, config: dict[str, Any]
    ) -> int:
        def work() -> int:
            cur = self._conn.execute(
                "INSERT INTO config_snapshots (ts, tunnel_id, actor, reason, config) "
                "VALUES (?,?,?,?,?)",
                (time.time(), tunnel_id, actor, reason, json.dumps(config)),
            )
            self._conn.execute(
                "DELETE FROM config_snapshots WHERE tunnel_id = ? AND id NOT IN "
                "(SELECT id FROM config_snapshots WHERE tunnel_id = ? ORDER BY id DESC LIMIT ?)",
                (tunnel_id, tunnel_id, _KEEP_SNAPSHOTS),
            )
            return int(cur.lastrowid or 0)

        async with self._lock:
            return await asyncio.to_thread(work)

    async def update_snapshot_meta(self, snapshot_id: int, meta: dict[str, Any]) -> None:
        await self._run(
            "UPDATE config_snapshots SET meta = ? WHERE id = ?", (json.dumps(meta), snapshot_id)
        )

    async def latest_snapshot(
        self, tunnel_id: str
    ) -> tuple[int, dict[str, Any], dict[str, Any]] | None:
        rows = await self._run(
            "SELECT id, config, meta FROM config_snapshots WHERE tunnel_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (tunnel_id,),
        )
        if not rows:
            return None
        return int(rows[0][0]), json.loads(rows[0][1]), json.loads(rows[0][2])

    async def delete_snapshot(self, snapshot_id: int) -> None:
        await self._run("DELETE FROM config_snapshots WHERE id = ?", (snapshot_id,))

    async def tunnels_with_snapshots(self) -> set[str]:
        rows = await self._run("SELECT DISTINCT tunnel_id FROM config_snapshots", ())
        return {str(r[0]) for r in rows}

    # --- server-side session registry (enables real logout) -----------------

    async def create_session(self, sid: str, username: str, expires: float) -> None:
        await self._run("DELETE FROM sessions WHERE expires <= ?", (time.time(),))
        await self._run(
            "INSERT INTO sessions (sid, username, expires) VALUES (?,?,?)", (sid, username, expires)
        )

    async def session_active(self, sid: str) -> bool:
        rows = await self._run(
            "SELECT 1 FROM sessions WHERE sid = ? AND expires > ?", (sid, time.time())
        )
        return bool(rows)

    async def delete_session(self, sid: str) -> None:
        await self._run("DELETE FROM sessions WHERE sid = ?", (sid,))
