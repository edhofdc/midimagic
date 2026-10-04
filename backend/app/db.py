"""SQLite storage for jobs and shares. Additive by design: nothing is overwritten."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from typing import Any, Optional

from . import config

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,
    status       TEXT NOT NULL DEFAULT 'queued',   -- queued|running|done|error
    stage        TEXT NOT NULL DEFAULT 'queued',
    progress     REAL NOT NULL DEFAULT 0,
    message      TEXT NOT NULL DEFAULT '',
    source_type  TEXT NOT NULL DEFAULT 'upload',   -- upload|youtube
    source_ref   TEXT NOT NULL DEFAULT '',
    title        TEXT NOT NULL DEFAULT '',
    options      TEXT NOT NULL DEFAULT '{}',
    audio_path   TEXT,
    midi_path    TEXT,
    stems        TEXT NOT NULL DEFAULT '{}',
    note_count   INTEGER NOT NULL DEFAULT 0,
    duration     REAL NOT NULL DEFAULT 0,
    error        TEXT NOT NULL DEFAULT '',
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS shares (
    slug       TEXT PRIMARY KEY,
    job_id     TEXT,
    title      TEXT NOT NULL DEFAULT '',
    midi_path  TEXT NOT NULL,
    note_count INTEGER NOT NULL DEFAULT 0,
    duration   REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    hits       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id  TEXT NOT NULL,
    ts      REAL NOT NULL,
    stage   TEXT NOT NULL,
    message TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
"""

# Additive migrations — never drop or rewrite existing rows.
MIGRATIONS: list[tuple[str, str, str]] = [
    ("jobs", "pedal", "ALTER TABLE jobs ADD COLUMN pedal TEXT NOT NULL DEFAULT '{}'"),
    ("jobs", "accuracy", "ALTER TABLE jobs ADD COLUMN accuracy TEXT NOT NULL DEFAULT ''"),
]


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init() -> None:
    with _lock, _conn() as c:
        c.executescript(SCHEMA)
        for table, column, ddl in MIGRATIONS:
            existing = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                c.execute(ddl)


def new_id(prefix: str = "job") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------- jobs

def create_job(
    source_type: str,
    source_ref: str,
    options: dict[str, Any],
    title: str = "",
) -> str:
    jid = new_id("job")
    now = time.time()
    with _lock, _conn() as c:
        c.execute(
            """INSERT INTO jobs (id, status, stage, progress, message, source_type,
                                 source_ref, title, options, created_at, updated_at)
               VALUES (?, 'queued', 'queued', 0, '', ?, ?, ?, ?, ?, ?)""",
            (jid, source_type, source_ref, title, json.dumps(options), now, now),
        )
    return jid


def update_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    if "options" in fields and isinstance(fields["options"], dict):
        fields["options"] = json.dumps(fields["options"])
    if "stems" in fields and isinstance(fields["stems"], dict):
        fields["stems"] = json.dumps(fields["stems"])
    if "pedal" in fields and isinstance(fields["pedal"], dict):
        fields["pedal"] = json.dumps(fields["pedal"])
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with _lock, _conn() as c:
        c.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))


def log_event(job_id: str, stage: str, message: str) -> None:
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO events (job_id, ts, stage, message) VALUES (?, ?, ?, ?)",
            (job_id, time.time(), stage, message),
        )


def _row_to_job(row: sqlite3.Row, with_events: bool = False) -> dict[str, Any]:
    d = dict(row)
    d["options"] = json.loads(d.get("options") or "{}")
    d["stems"] = json.loads(d.get("stems") or "{}")
    if "pedal" in d:
        try:
            d["pedal"] = json.loads(d.get("pedal") or "{}")
        except (TypeError, ValueError):
            d["pedal"] = {}
    if with_events:
        with _lock, _conn() as c:
            ev = c.execute(
                "SELECT ts, stage, message FROM events WHERE job_id = ? ORDER BY ts ASC LIMIT 200",
                (d["id"],),
            ).fetchall()
        d["events"] = [dict(e) for e in ev]
    return d


def get_job(job_id: str, with_events: bool = False) -> Optional[dict[str, Any]]:
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row, with_events) if row else None


def list_jobs(limit: int = 30) -> list[dict[str, Any]]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def stats() -> dict[str, Any]:
    with _lock, _conn() as c:
        total = c.execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"]
        done = c.execute("SELECT COUNT(*) n FROM jobs WHERE status='done'").fetchone()["n"]
        failed = c.execute("SELECT COUNT(*) n FROM jobs WHERE status='error'").fetchone()["n"]
        active = c.execute(
            "SELECT COUNT(*) n FROM jobs WHERE status IN ('queued','running')"
        ).fetchone()["n"]
        notes = c.execute("SELECT COALESCE(SUM(note_count),0) n FROM jobs").fetchone()["n"]
        shares = c.execute("SELECT COUNT(*) n FROM shares").fetchone()["n"]
    return {
        "total": total,
        "done": done,
        "failed": failed,
        "active": active,
        "notes": notes,
        "shares": shares,
    }


# ---------------------------------------------------------------- shares

def create_share(job_id: str, title: str, midi_path: str,
                 note_count: int = 0, duration: float = 0.0) -> str:
    slug = uuid.uuid4().hex[:10]
    with _lock, _conn() as c:
        c.execute(
            """INSERT INTO shares (slug, job_id, title, midi_path, note_count,
                                   duration, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (slug, job_id, title, midi_path, note_count, duration, time.time()),
        )
    return slug


def get_share(slug: str, count_hit: bool = False) -> Optional[dict[str, Any]]:
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM shares WHERE slug = ?", (slug,)).fetchone()
        if row and count_hit:
            c.execute("UPDATE shares SET hits = hits + 1 WHERE slug = ?", (slug,))
    return dict(row) if row else None


def list_shares(limit: int = 30) -> list[dict[str, Any]]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM shares ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
