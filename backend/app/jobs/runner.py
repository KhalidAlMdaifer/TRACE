"""What a job's child process runs. One job, one fresh process: dopplertrack keeps search
state in a module global and forks its pool from it, so two searches must never share a
process, and a crash or a cancel must not take the worker down."""
from __future__ import annotations

import os
import traceback

from .. import config, db


class JobError(Exception):
    """A failure with a code the UI can show."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def run(job_id: str) -> str:
    """Run one job to the end in this process and record how it went. Returns the final
    status. The worker calls this in a child; tests call it inline."""
    from . import fetch, search, triage

    conn = db.connect()
    try:
        job = db.one(conn, "SELECT * FROM jobs WHERE id = ?", (job_id,))
        if job is None:
            return "missing"
        if job["status"] == "queued":
            db.claim_job(conn, job_id)
        with conn:
            conn.execute("UPDATE jobs SET pid = ? WHERE id = ?", (os.getpid(), job_id))
        handler = {"triage": triage.run, "search": search.run, "fetch": fetch.run}[job["kind"]]
        try:
            handler(conn, job)
            db.finish_job(conn, job_id, "done")
            return "done"
        except JobError as e:
            code, message = e.code, str(e)
        except Exception as e:                     # anything else: a bug or a broken file; say so plainly
            traceback.print_exc()
            code, message = "internal_error", f"{type(e).__name__}: {e}"
        db.emit(conn, job_id, job["case_id"], "failed", {"job": job["kind"], "job_id": job_id, "code": code, "message": message})
        db.finish_job(conn, job_id, "failed", error=f"{code}: {message}")
        if job["case_id"] and job["kind"] == "search":
            with conn:
                conn.execute("UPDATE cases SET status = 'failed' WHERE id = ?", (job["case_id"],))
        return "failed"
    finally:
        conn.close()


def child_main(job_id: str, env: dict) -> None:
    """Entry point of the spawned child. Its own session, so the worker can stop it together
    with any pool processes dopplertrack forked from it."""
    os.environ.update(env)
    for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ.setdefault(v, "1")
    if hasattr(os, "setsid"):
        try:
            os.setsid()
        except OSError:
            pass
    config.exit_with_parent(kill_group=True)      # if the worker dies, so does this job: it will be marked failed anyway
    if hasattr(os, "nice"):
        try:
            os.nice(10)                 # jobs are background work: an editor fit must never wait for a core behind one
        except OSError:
            pass
    config.use_dopplertrack_cache()
    run(job_id)
