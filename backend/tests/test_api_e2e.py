"""Upload to result over real HTTP: a uvicorn process, a worker process, and nothing else.

These are the M2 acceptance tests that need the real processes: fits answering while triage
runs, a search started before detection ends, the event stream, a cancelled search leaving
the worker alive, and the stream resuming after the api is killed and restarted."""
from __future__ import annotations

import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time

import httpx
import pytest
from dopplertrack.geo import haversine_m

from app.core import synth

pytestmark = pytest.mark.slow


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Site:
    def __init__(self, data, flights_from):
        self.data = data
        (data / "flights").symlink_to(flights_from)
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.creds = {"email": "analyst@trace.test", "password": secrets.token_urlsafe(12)}
        self.env = {**os.environ, "DATA_DIR": str(data), "APP_SECRET": secrets.token_urlsafe(24), "ADMIN_EMAIL": self.creds["email"],
                    "ADMIN_PASSWORD": self.creds["password"], "TRACE_SYNTHETIC_TYPES": "1", "DOPPLER_WORKERS": "5", "FIT_WORKERS": "3",
                    "FIT_INLINE": "0", "DEFAULT_PACK": "test", "PYTHONUNBUFFERED": "1", "WEATHER_AUTO": "0", "PLACEBO_DAYS": "0"}
        self.api = self.worker = None

    def start_api(self):
        self.api = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.api.main:app", "--host", "127.0.0.1", "--port", str(self.port),
                                     "--log-level", "warning"], env=self.env)
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                if httpx.get(self.base + "/api/auth/me", timeout=2).status_code == 401:
                    return
            except httpx.HTTPError:
                time.sleep(0.2)
        raise RuntimeError("the api did not come up")

    def start_worker(self):
        self.worker = subprocess.Popen([sys.executable, "-m", "app.worker"], env=self.env)

    def kill_api(self):
        self.api.send_signal(signal.SIGKILL)
        self.api.wait(10)

    def stop(self):
        for p in (self.api, self.worker):
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()


@pytest.fixture(scope="module")
def site(case3, tmp_path_factory):
    s = Site(tmp_path_factory.mktemp("e2e-data"), case3.data_dir / "flights")
    s.start_api()
    s.start_worker()
    yield s
    s.stop()


@pytest.fixture(scope="module")
def http(site):
    c = httpx.Client(base_url=site.base, timeout=60)
    assert c.post("/api/auth/login", json=site.creds).status_code == 200
    yield c
    c.close()


def sse(http, case_id, until, last_id=None, timeout=420):
    """Read the case's stream until `until(event, data)` is true. Returns [(id, event, data)]."""
    out, deadline = [], time.time() + timeout
    headers = {"Last-Event-ID": str(last_id)} if last_id is not None else {}
    with http.stream("GET", f"/api/cases/{case_id}/stream", headers=headers, timeout=httpx.Timeout(60, read=60)) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        cur = {}
        for line in r.iter_lines():
            assert time.time() < deadline, f"stream timed out; last events: {out[-5:]}"
            if line.startswith(":"):
                continue
            if line == "":
                if "event" in cur:
                    item = (int(cur["id"]), cur["event"], json.loads(cur["data"]))
                    out.append(item)
                    if until(item[1], item[2]):
                        return out
                cur = {}
                continue
            k, _, v = line.partition(": ")
            cur[k] = v
    raise AssertionError(f"stream ended early; last events: {out[-5:]}")


def new_case(http, case3, **fields):
    cid = http.post("/api/cases", json={"pack_id": "test"}).json()["id"]
    with open(case3.wav, "rb") as fh:
        r = http.post(f"/api/cases/{cid}/media", files={"file": ("synthetic.wav", fh, "audio/wav")})
    assert r.status_code == 200, r.text
    if fields:
        assert http.patch(f"/api/cases/{cid}", json=fields).status_code == 200
    return cid


def post_box(http, cid, box):
    return http.post(f"/api/cases/{cid}/events", json={"t_start": box[0], "t_end": box[1], "f_lo": box[2], "f_hi": box[3], "harmonics": 1})


def test_upload_to_result_over_http(site, http, case3):
    # what the largest of these fits costs on this machine with nothing else running
    from app.core import events

    t = time.time()
    events.preview_from_disk(case3.case_dir, *synth.BEND_BOXES[0], harmonics=1, c=case3.c)
    idle_s = time.time() - t

    cid = new_case(http, case3, date_local=synth.DATE_LOCAL, temperature_c=28.0, case_ref="E2E-0001")
    sse(http, cid, lambda ev, d: ev == "triage" and d["state"] == "spectrogram_ready", timeout=60)

    # The editor answers while triage is still detecting: under 5 s, as the plan asks. Each
    # answer is three quick fits side by side (one per grid phase). On a machine throttled so
    # far that one fit alone takes over 2 s (a laptop in power-saver), the bound is two and a
    # half times that instead: what is being tested is that a fit does not queue behind a job
    # that runs for minutes.
    budget = max(5.0, 2.5 * idle_s)
    took = []
    for box in synth.BEND_BOXES:
        t = time.time()
        r = post_box(http, cid, box)
        took.append(time.time() - t)
        assert r.status_code == 200, r.text
        assert len(r.json()["curve"]) > 20
    print(f"editor fits while triage runs: {[round(x, 1) for x in took]} s; the same fit idle: {idle_s:.1f} s")
    assert max(took) < budget, f"fits took {took} s against a budget of {budget:.1f} s"
    narrow = post_box(http, cid, synth.NARROW_BOX)
    assert narrow.status_code == 200
    r = post_box(http, cid, (260, 360, 120, 121))
    assert r.status_code == 422 and r.json()["error"]["code"] == "box_too_small"
    assert http.delete(f"/api/cases/{cid}/events/{narrow.json()['id']}").status_code == 200
    assert http.get(f"/api/cases/{cid}").json()["events"]["confirmed"] == 3

    # start the search without waiting for detection: the triage job is cut short
    job = http.get(f"/api/cases/{cid}").json()["job"]
    assert job["kind"] == "triage" and job["status"] == "running"
    r = http.post(f"/api/cases/{cid}/search")
    assert r.status_code == 200, r.text
    events = sse(http, cid, lambda ev, d: ev in ("done", "failed"))
    assert events[-1][1] == "done", events[-1]
    kinds = [(ev, d.get("state"), d.get("stage")) for _, ev, d in events]
    assert ("triage", "done", None) in kinds and any(d.get("truncated") for _, ev, d in events if ev == "triage")
    stages = [d["stage"] for _, ev, d in events if ev == "stage" and d["state"] == "start"]
    assert stages[:2] == ["fits", "flights"] and {"scoring", "extras", "refine"} <= set(stages)
    assert any(ev == "cells" for _, ev, _ in events)
    assert [i for i, _, _ in events] == sorted({i for i, _, _ in events})         # ids rise, no repeats

    res = http.get(f"/api/cases/{cid}/result").json()
    assert res["state"] == "located" and res["band"] in ("High", "Medium")
    assert float(haversine_m(res["estimate"]["lat"], res["estimate"]["lon"], *synth.OBSERVER)) < 100
    assert events[-1][2]["result_id"] == http.get(f"/api/cases/{cid}").json()["result"]["id"] and events[-1][2]["state"] == "located"
    scored = [d["scored"] for _, ev, d in events if ev == "cells"]
    assert scored == [False, True]                                    # search points first, then their scores
    assert site.worker.poll() is None


def test_stream_carries_proposals_per_slice(site, http, case3):
    cid = new_case(http, case3, date_local=synth.DATE_LOCAL, temperature_c=28.0)
    events = sse(http, cid, lambda ev, d: ev == "triage" and d["state"] == "done")
    states = [d["state"] for _, ev, d in events if ev == "triage"]
    assert states[0] == "decoding" and "spectrogram_ready" in states and states[-1] == "done"
    props = [d for _, ev, d in events if ev == "proposals"]
    assert len(props) == 4                                                         # four ten-minute slices of a 30 minute file
    done = [d["done_s"] for d in props]
    assert done == sorted(done) and len(set(done)) == 4 and abs(done[-1] - synth.DURATION_S) < 2
    listed = http.get(f"/api/cases/{cid}/events").json()
    shown = {e["id"] for d in props for e in d["events"]} - {i for d in props for i in d["removed"]}
    assert shown == {e["id"] for e in listed} and all(e["status"] == "proposed" for e in listed)
    heard = [e["t_cpa_heard_audio"] for e in case3.truth["events"]]
    assert sum(any(abs(e["fit"]["t_cpa"] - h) < 25 for e in listed) for h in heard) >= 2


@pytest.fixture(scope="module")
def ready_case(http, case3):
    """A triaged case with the three boxes confirmed, for the search tests below."""
    cid = new_case(http, case3, date_local=synth.DATE_LOCAL, temperature_c=28.0, case_ref="E2E-0002")
    sse(http, cid, lambda ev, d: ev == "triage" and d["state"] == "spectrogram_ready", timeout=60)
    for box in synth.BEND_BOXES:
        assert post_box(http, cid, box).status_code == 200
    return cid


def test_cancelled_search_leaves_the_worker_alive(site, http, ready_case):
    cid = ready_case
    job_id = http.post(f"/api/cases/{cid}/search").json()["job_id"]
    seen = sse(http, cid, lambda ev, d: ev == "stage" and d.get("stage") == "fits" and d["state"] == "start")
    assert http.delete(f"/api/cases/{cid}/search").status_code == 200
    tail = sse(http, cid, lambda ev, d: ev == "cancelled", last_id=seen[-1][0], timeout=30)
    assert tail[-1][2]["job_id"] == job_id
    c = http.get(f"/api/cases/{cid}").json()
    assert c["job"]["status"] == "cancelled" and c["status"] != "searching"
    assert http.get(f"/api/cases/{cid}/result").status_code == 404
    assert site.worker.poll() is None                                             # and it takes the next job


def test_stream_resumes_after_the_api_restarts(site, http, ready_case):
    cid = ready_case
    assert http.post(f"/api/cases/{cid}/search").status_code == 200
    last = http.get(f"/api/cases/{cid}").json()["last_event_id"]
    first = sse(http, cid, lambda ev, d: ev == "stage" and d.get("stage") == "fits" and d["state"] == "start", last_id=last)
    site.kill_api()
    with pytest.raises(httpx.HTTPError):
        http.get("/api/auth/me", timeout=2)
    site.start_api()
    assert http.get("/api/auth/me").status_code == 200                            # the session cookie outlives the restart
    rest = sse(http, cid, lambda ev, d: ev in ("done", "failed"), last_id=first[-1][0])
    assert rest[-1][1] == "done" and rest[0][0] > first[-1][0]                     # nothing replayed, nothing lost
    stages = [d["stage"] for _, ev, d in first + rest if ev == "stage" and d["state"] == "start"]
    assert stages[:2] == ["fits", "flights"] and "refine" in stages
    assert http.get(f"/api/cases/{cid}/result").json()["state"] == "located"
