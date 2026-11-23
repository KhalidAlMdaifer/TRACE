"""The helper processes must not outlive whatever started them."""
import os
import signal
import subprocess
import sys
import time

PARENT = """
import multiprocessing, os, sys, time
from app import config

def child():
    config.exit_with_parent()
    time.sleep(60)

if __name__ == "__main__":
    p = multiprocessing.get_context("spawn").Process(target=child)
    p.start()
    print(p.pid, flush=True)
    time.sleep(60)
"""


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # a zombie is not alive. Linux has /proc; macOS does not, so ask ps there
    if os.path.exists(f"/proc/{pid}/stat"):
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().split(")")[-1].split()[0] != "Z"
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith("Z")


def test_a_helper_process_ends_when_its_parent_is_killed(tmp_path):
    script = tmp_path / "parent.py"
    script.write_text(PARENT)
    parent = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True)
    child = int(parent.stdout.readline())
    assert alive(child)
    parent.send_signal(signal.SIGKILL)                  # no chance to clean up
    parent.wait(5)
    deadline = time.time() + 8
    while alive(child) and time.time() < deadline:
        time.sleep(0.2)
    assert not alive(child)


def test_the_queue_runs_fetches_beside_compute_jobs(tmp_path, monkeypatch):
    from app import db

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db.init()
    conn = db.connect()
    with conn:
        conn.execute("INSERT INTO users (email, password_hash, role, created_at) VALUES ('a@b', 'x', 'admin', 'now')")
        conn.execute("INSERT INTO cases (id, created_by, created_at, status, pack_id) VALUES ('c1', 1, 'now', 'draft', 'test')")
        triage = db.queue_job(conn, "triage", "c1")
        fetch = db.queue_job(conn, "fetch", None, {"pack_id": "test", "utc_date": "2026-11-13"})
        search = db.queue_job(conn, "search", "c1")
    assert db.next_job(conn)["id"] == search                                  # search, then fetch, then triage
    assert db.next_job(conn, only_fetch=True)["id"] == fetch                  # the compute slot is busy: only a download may start
    assert db.next_job(conn, skip_fetch=True)["id"] == search                 # a download is running: no second one
    assert db.claim_job(conn, search) and not db.claim_job(conn, search)      # a job is taken once
    assert db.next_job(conn, skip_fetch=True)["id"] == triage
    assert db.next_job(conn, skip_fetch=True, only_fetch=True) is None
    conn.close()


def test_the_worker_ends_when_the_script_that_started_it_is_gone(tmp_path):
    """scripts/dev_backend.sh starts the worker beside the api. If the script is killed, the
    worker must not stay behind: a second one would then share the database with the next.
    Whoever was reading the worker's output is gone by then too, as when a terminal or a
    preview pane is closed."""
    import secrets
    import socket

    launcher = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    env = {**os.environ, "DATA_DIR": str(tmp_path), "APP_SECRET": secrets.token_urlsafe(24), "TRACE_EXIT_WITH_PID": str(launcher.pid)}
    reader, writer = socket.socketpair()
    worker = subprocess.Popen([sys.executable, "-m", "app.worker"], env=env, stdout=writer, stderr=writer)
    writer.close()
    try:
        time.sleep(3.0)
        assert worker.poll() is None                         # the launcher lives: so does the worker
        assert b"TRACE worker" in reader.recv(4096)
        reader.close()                                       # nobody reads its output any more
        launcher.kill()
        launcher.wait()
        assert worker.wait(timeout=10) == 0                  # gone within seconds, and cleanly
    finally:
        for p in (launcher, worker):
            if p.poll() is None:
                p.kill()


def test_the_worker_stops_on_request_with_nobody_reading_its_output(tmp_path):
    import secrets
    import socket

    env = {**os.environ, "DATA_DIR": str(tmp_path), "APP_SECRET": secrets.token_urlsafe(24)}
    env.pop("TRACE_EXIT_WITH_PID", None)
    reader, writer = socket.socketpair()
    worker = subprocess.Popen([sys.executable, "-m", "app.worker"], env=env, stdout=writer, stderr=writer)
    writer.close()
    try:
        assert b"TRACE worker" in reader.recv(4096)
        reader.close()
        worker.send_signal(signal.SIGTERM)
        assert worker.wait(timeout=10) == 0
    finally:
        if worker.poll() is None:
            worker.kill()
