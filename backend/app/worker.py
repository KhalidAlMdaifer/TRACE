"""The job loop: `python -m app.worker`.

Polls the jobs table and runs each job in a fresh child process (spawn). The child does the
work and writes its own progress; this loop only starts children, enforces the per-kind time
limits, and stops a child when the api asks (a cancelled search, or a triage job that a
search makes unnecessary)."""
from __future__ import annotations

import multiprocessing
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass

from . import config, db

POLL_S = 0.3


@dataclass
class Child:
    proc: multiprocessing.Process
    kind: str
    case_id: str | None
    started: float


def _kill(proc) -> None:
    """Stop the child and everything in its session (dopplertrack's forked pool)."""
    try:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except Exception:
            pass
    proc.join(10)


class Worker:
    def __init__(self):
        self.children: dict[str, Child] = {}
        self.ctx = multiprocessing.get_context("spawn")
        self.conn = db.connect()
        self._kept = 0.0

    def housekeep(self) -> list[str]:
        """Once an hour, delete the cases that have outlived RETENTION_DAYS."""
        from . import retention

        days = config.retention_days()
        if days <= 0 or time.time() - self._kept < 3600:
            return []
        self._kept = time.time()
        gone = retention.expire(self.conn, days)
        if gone:
            _say(f"TRACE worker: deleted {len(gone)} case(s) older than {days} days")
        return gone

    def recover(self) -> None:
        """Jobs left 'running' by a worker that died have no child any more."""
        for job in db.rows(self.conn, "SELECT id, case_id, kind FROM jobs WHERE status = 'running'"):
            db.emit(self.conn, job["id"], job["case_id"], "failed", {"job": job["kind"], "job_id": job["id"], "code": "worker_restarted",
                                                                    "message": "the worker restarted while this job was running"})
            db.finish_job(self.conn, job["id"], "failed", error="worker_restarted")
            self._case_after_stop(job)

    def _case_after_stop(self, job: dict) -> None:
        if job["kind"] == "search" and job["case_id"]:
            with self.conn:
                self.conn.execute("UPDATE cases SET status = 'triaged' WHERE id = ? AND status = 'searching'", (job["case_id"],))

    def _reap(self) -> None:
        for job_id, ch in list(self.children.items()):
            job = db.one(self.conn, "SELECT * FROM jobs WHERE id = ?", (job_id,))
            alive = ch.proc.is_alive()
            if job and job["status"] == "running" and job["cancel_requested"] and alive:
                _kill(ch.proc)
                if job["cancel_requested"] == "truncate":
                    n = self.conn.execute("SELECT COUNT(*) FROM events WHERE case_id = ? AND source = 'detect' AND status = 'proposed'",
                                          (job["case_id"],)).fetchone()[0]
                    db.emit(self.conn, job_id, job["case_id"], "triage", {"state": "done", "truncated": True, "events": n})
                    db.finish_job(self.conn, job_id, "done", stage="truncated")
                else:
                    db.emit(self.conn, job_id, job["case_id"], "cancelled", {"job": job["kind"], "job_id": job_id})
                    db.finish_job(self.conn, job_id, "cancelled")
                    self._case_after_stop(job)
            elif job and job["status"] == "running" and alive and time.time() - ch.started > config.job_timeout_s(ch.kind):
                _kill(ch.proc)
                db.emit(self.conn, job_id, job["case_id"], "failed", {"job": ch.kind, "job_id": job_id, "code": "timeout",
                                                                     "message": f"the {ch.kind} job ran past its time limit"})
                db.finish_job(self.conn, job_id, "failed", error="timeout")
                self._case_after_stop(job)
            elif not alive:
                ch.proc.join(1)
                if job and job["status"] == "running":      # the child died without saying how
                    db.emit(self.conn, job_id, job["case_id"], "failed", {"job": ch.kind, "job_id": job_id, "code": "crashed",
                                                                         "message": f"the job's process ended unexpectedly (exit code {ch.proc.exitcode})"})
                    db.finish_job(self.conn, job_id, "failed", error=f"crashed: exit code {ch.proc.exitcode}")
                    self._case_after_stop(job)
            else:
                continue
            del self.children[job_id]

    def _start(self) -> None:
        from .jobs import runner

        while True:
            # A fetch is a long download, not compute: it runs beside the compute jobs, one at
            # a time, so an upload's triage never waits ten minutes behind it.
            busy = sum(1 for c in self.children.values() if c.kind != "fetch")
            fetching = any(c.kind == "fetch" for c in self.children.values())
            job = db.next_job(self.conn, skip_fetch=fetching, only_fetch=busy >= config.max_parallel_jobs())
            if job is None or not db.claim_job(self.conn, job["id"]):
                return
            env = {k: v for k, v in os.environ.items() if k in ("DATA_DIR", "DOPPLERTRACK_CACHE") or k.startswith(("TRACE_", "DOPPLER_", "DETECT_"))}
            proc = self.ctx.Process(target=runner.child_main, args=(job["id"], env), name=f"trace-{job['kind']}-{job['id'][-6:]}")
            proc.start()
            self.children[job["id"]] = Child(proc, job["kind"], job["case_id"], time.time())

    def step(self) -> None:
        self._reap()
        self._start()
        self.housekeep()

    def run_forever(self, stop: threading.Event) -> None:
        self.recover()
        while not stop.is_set():
            self.step()
            stop.wait(POLL_S)
        for ch in self.children.values():        # shutting down: leave no orphans
            _kill(ch.proc)
        self.conn.close()


def _say(text: str) -> None:
    """A line for whoever is watching. The reader may be gone (a killed terminal or
    launcher): that must never stop the worker from doing what it was about to do."""
    try:
        print(text, flush=True)
    except (OSError, ValueError):
        # and nothing later should fail on it either, the flush at exit included
        sys.stdout = sys.stderr = open(os.devnull, "w")


def _stop_when_gone(pid: int, stop: threading.Event) -> None:
    """scripts/dev_backend.sh names itself in TRACE_EXIT_WITH_PID. If that script is killed
    without the chance to stop us, we stop anyway: a worker left behind would share the
    database with the next one started."""
    while not stop.wait(1.0):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            stop.set()                             # first: the line below can fail when nobody is left to read it
            _say(f"TRACE worker: the process that started it ({pid}) is gone; stopping")
        except PermissionError:                    # it exists, under another user
            pass


def main() -> int:
    config.load_dotenv()
    db.init()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    launcher = os.environ.get("TRACE_EXIT_WITH_PID", "")
    if launcher.isdigit():
        threading.Thread(target=_stop_when_gone, args=(int(launcher), stop), daemon=True, name="launcher-watch").start()
    print(f"TRACE worker: data in {config.data_dir().resolve()}, {config.max_parallel_jobs()} job at a time, "
          f"{config.doppler_workers()} dopplertrack workers", flush=True)
    Worker().run_forever(stop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
