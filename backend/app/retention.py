"""Removing a case and everything kept for it: by the analyst (`DELETE /api/cases/{id}`) or
by age (`RETENTION_DAYS`, applied by the worker). The audit log keeps its lines about the
case, with the recording's name and hash, so what was removed stays on record."""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone

from . import config, db


def busy(conn, case_id: str) -> bool:
    """A job of the case is running: its process would write into a case that is gone."""
    return conn.execute("SELECT COUNT(*) FROM jobs WHERE case_id = ? AND status = 'running'", (case_id,)).fetchone()[0] > 0


def describe(conn, case_id: str) -> str:
    m = db.one(conn, "SELECT filename, sha256 FROM media WHERE case_id = ?", (case_id,))
    return f"file={m['filename']} sha256={m['sha256']}" if m else "no recording"


def delete_case(conn, case_id: str) -> None:
    """The files first: if they cannot be removed the rows stay, and it can be tried again."""
    for folder in (config.case_dir(case_id), config.results_dir(case_id)):
        if folder.exists():
            shutil.rmtree(folder)
    with conn:
        conn.execute("DELETE FROM job_events WHERE case_id = ? OR job_id IN (SELECT id FROM jobs WHERE case_id = ?)", (case_id, case_id))
        for table in ("results", "jobs", "events", "media"):
            conn.execute(f"DELETE FROM {table} WHERE case_id = ?", (case_id,))
        conn.execute("DELETE FROM cases WHERE id = ?", (case_id,))


def expire(conn, days: int, now: datetime | None = None) -> list[str]:
    """Delete every case created more than `days` days ago, except one with a job running
    (it goes at the next pass). 0 keeps everything. Returns the ids removed."""
    if days <= 0:
        return []
    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    gone = []
    for case in db.rows(conn, "SELECT id, created_at FROM cases WHERE created_at < ? ORDER BY created_at", (cutoff,)):
        if busy(conn, case["id"]):
            continue
        what = describe(conn, case["id"])
        delete_case(conn, case["id"])
        db.audit(conn, None, case["id"], "case.expired", f"retention_days={days} created={case['created_at'][:10]} {what}")
        gone.append(case["id"])
    return gone
