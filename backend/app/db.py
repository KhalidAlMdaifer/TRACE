"""SQLite: one file, WAL mode, plain SQL migrations. The api and the worker both write, and
every job runs in its own process, so nothing is shared but this file."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone

from . import config

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
JOB_PRIORITY = {"search": 0, "fetch": 1, "triage": 2}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def ulid() -> str:
    """26 characters, sortable by creation time: 48 bits of milliseconds, 80 random bits."""
    n = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    return "".join(_CROCKFORD[(n >> (5 * i)) & 31] for i in range(25, -1, -1))


def connect() -> sqlite3.Connection:
    """A new connection. Use `with connect() as conn:` for a transaction; close it when done."""
    path = config.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init() -> None:
    """Apply the migrations that have not run yet."""
    conn = connect()
    try:
        with conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        done = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations")}
        for f in sorted(config.MIGRATIONS.glob("*.sql")):
            if f.name in done:
                continue
            try:
                conn.executescript("BEGIN IMMEDIATE;\n" + f.read_text() + f"\nINSERT INTO schema_migrations VALUES ('{f.name}', '{now()}');\nCOMMIT;")
            except sqlite3.Error:
                conn.execute("ROLLBACK") if conn.in_transaction else None
                # another process may have applied it between our check and our BEGIN
                if not conn.execute("SELECT 1 FROM schema_migrations WHERE name = ?", (f.name,)).fetchone():
                    raise
    finally:
        conn.close()


def one(conn, sql: str, args=()) -> dict | None:
    r = conn.execute(sql, args).fetchone()
    return dict(r) if r else None


def rows(conn, sql: str, args=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, args)]


# --- jobs ---------------------------------------------------------------------------------

def queue_job(conn, kind: str, case_id: str | None, params: dict | None = None) -> str:
    job_id = ulid()
    conn.execute("INSERT INTO jobs (id, case_id, kind, status, params, created_at) VALUES (?, ?, ?, 'queued', ?, ?)",
                 (job_id, case_id, kind, json.dumps(params or {}), now()))
    return job_id


def next_job(conn, skip_fetch: bool = False, only_fetch: bool = False) -> dict | None:
    """The queue order: search, then fetch, then triage; oldest first within a kind."""
    queued = rows(conn, "SELECT * FROM jobs WHERE status = 'queued' AND cancel_requested IS NULL")
    queued = [j for j in queued if not (skip_fetch and j["kind"] == "fetch") and not (only_fetch and j["kind"] != "fetch")]
    queued.sort(key=lambda j: (JOB_PRIORITY.get(j["kind"], 9), j["created_at"], j["id"]))
    return queued[0] if queued else None


def claim_job(conn, job_id: str) -> bool:
    """queued -> running, once: two workers can never both take a job."""
    with conn:
        cur = conn.execute("UPDATE jobs SET status = 'running', started_at = ? WHERE id = ? AND status = 'queued'", (now(), job_id))
    return cur.rowcount == 1


def emit(conn, job_id: str, case_id: str | None, type_: str, payload: dict) -> int:
    """One row of the event stream. The api tails this table, so a restart loses nothing."""
    with conn:
        cur = conn.execute("INSERT INTO job_events (job_id, case_id, ts, type, payload) VALUES (?, ?, ?, ?, ?)",
                           (job_id, case_id, now(), type_, json.dumps(payload)))
    return cur.lastrowid


def finish_job(conn, job_id: str, status: str, error: str | None = None, stage: str | None = None) -> None:
    with conn:
        conn.execute("UPDATE jobs SET status = ?, error = ?, stage = COALESCE(?, stage), finished_at = ?, pid = NULL WHERE id = ?",
                     (status, error, stage, now(), job_id))


def set_stage(conn, job_id: str, stage: str, progress: float | None = None) -> None:
    with conn:
        conn.execute("UPDATE jobs SET stage = ?, progress = ? WHERE id = ?", (stage, progress, job_id))


def audit(conn, user_id, case_id, action: str, detail: str | None = None, ip: str | None = None) -> None:
    with conn:
        conn.execute("INSERT INTO audit_log (ts, user_id, case_id, action, detail, ip) VALUES (?, ?, ?, ?, ?, ?)",
                     (now(), user_id, case_id, action, detail, ip))
