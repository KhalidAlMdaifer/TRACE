"""The service through its HTTP API, in process: the worker's jobs run inline and editor
fits run in the request thread (FIT_INLINE). The end-to-end test with a real server and a
real worker is test_api_e2e.py."""
from __future__ import annotations

import base64
import secrets

import numpy as np
import pytest

from app.core import synth

from .conftest import WORKERS

CLIP_S = 420                       # long enough to hold flight 1's flyover and its box


@pytest.fixture(scope="module")
def short_wav(case3, tmp_path_factory):
    from app.core import media

    x, sr = media.decode_audio(case3.wav)             # already scaled by write_wav once; undo that before writing again
    return synth.write_wav(x[: CLIP_S * sr] / 0.2, sr, tmp_path_factory.mktemp("clip") / "clip.wav")


@pytest.fixture(scope="module")
def site(case3, tmp_path_factory):
    """An app on a fresh data folder holding the synthetic flight day, with one admin."""
    from fastapi.testclient import TestClient

    data = tmp_path_factory.mktemp("api-data")
    (data / "flights").symlink_to(case3.data_dir / "flights")
    creds = {"email": "analyst@trace.test", "password": secrets.token_urlsafe(12)}
    mp = pytest.MonkeyPatch()
    for k, v in {"DATA_DIR": str(data), "APP_SECRET": secrets.token_urlsafe(24), "ADMIN_EMAIL": creds["email"],
                 "ADMIN_PASSWORD": creds["password"], "FIT_INLINE": "1", "TRACE_SYNTHETIC_TYPES": "1", "DOPPLER_WORKERS": str(min(WORKERS, 4)),
                 "DEFAULT_PACK": "test", "RATE_UPLOADS_PER_HOUR": "50"}.items():
        mp.setenv(k, v)
    from app.api.main import create_app

    with TestClient(create_app()) as client:
        yield {"client": client, "creds": creds, "data": data}
    mp.undo()


@pytest.fixture(scope="module")
def api(site):
    c = site["client"]
    r = c.post("/api/auth/login", json=site["creds"])
    assert r.status_code == 200, r.text
    return c


def run_jobs(site):
    """Run every queued job in this process, as the worker's child would."""
    from app import db
    from app.jobs import runner

    with db.connect() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at")]
    for job_id in ids:
        runner.run(job_id)
    return ids


def audit_actions(case_id=None):
    from app import db

    with db.connect() as conn:
        q = "SELECT action, detail FROM audit_log" + (" WHERE case_id = ?" if case_id else "") + " ORDER BY id"
        return [(r["action"], r["detail"]) for r in conn.execute(q, (case_id,) if case_id else ())]


def err(r):
    return r.json()["error"]["code"]


# --- no anonymous endpoint ------------------------------------------------------------------

def test_everything_needs_a_sign_in(site):
    from fastapi.testclient import TestClient

    anon = TestClient(site["client"].app)
    for method, path in (("GET", "/api/auth/me"), ("GET", "/api/cases"), ("POST", "/api/cases"), ("GET", "/api/packs/test"), ("GET", "/api/config"),
                         ("GET", "/api/cases/x/stream"), ("GET", "/api/cases/x/result"), ("POST", "/api/cases/x/search"),
                         ("GET", "/api/flights/count?pack=test&date=2026-11-14"),
                         ("GET", "/api/packs/ny/latest"), ("POST", "/api/packs/ny/latest"), ("DELETE", "/api/cases/x")):
        r = anon.request(method, path)
        assert r.status_code == 401 and err(r) == "not_signed_in", path
    assert anon.get("/docs").status_code == 404 and anon.get("/openapi.json").status_code == 404


def test_login(site):
    from fastapi.testclient import TestClient

    c = TestClient(site["client"].app)
    r = c.post("/api/auth/login", json={"email": site["creds"]["email"], "password": "wrong-" + secrets.token_urlsafe(6)})
    assert r.status_code == 401 and err(r) == "bad_credentials"
    r = c.post("/api/auth/login", json=site["creds"])
    assert r.status_code == 200 and r.json()["user"]["email"] == site["creds"]["email"]
    assert "password" not in r.text and "httponly" in r.headers["set-cookie"].lower()
    assert c.get("/api/auth/me").json()["user"]["role"] == "admin"
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/auth/me").status_code == 401
    assert "login" in [a for a, _ in audit_actions()]


# --- packs ----------------------------------------------------------------------------------

def test_config_lists_the_packs(api):
    c = api.get("/api/config").json()
    assert c["default_pack"] == "test" and {"id": "test", "name": "Synthetic test pack"} in c["packs"] and c["max_duration_h"] == 6
    assert {"id": "uae", "name": "United Arab Emirates"} in c["packs"]
    # the street map under a located result: a tile host by default, none when the setting is empty
    assert "{z}/{x}/{y}" in c["map_tiles"]["url"] and "OpenStreetMap" in c["map_tiles"]["attribution"] and c["map_tiles"]["max_zoom"] == 19 and c["map_tiles"]["dark"] is True


def test_the_street_map_can_be_switched_off(api, monkeypatch):
    monkeypatch.setenv("MAP_TILES_URL", "")
    assert api.get("/api/config").json()["map_tiles"] is None
    monkeypatch.setenv("MAP_TILES_URL", "https://tiles.example.org/{z}/{x}/{y}.png")
    assert api.get("/api/config").json()["map_tiles"] == {"url": "https://tiles.example.org/{z}/{x}/{y}.png", "attribution": "", "max_zoom": 19, "dark": False}
    uae = api.get("/api/packs/uae").json()
    assert len(uae["regions"]["features"]) == 10 and set(uae["labels"]) == {"ajman", "umm_al_quwain", "ras_al_khaimah", "fujairah"}
    assert uae["short_name"] == "UAE" and len(uae["grid"]) > 1000


def test_pack_and_flight_count(api):
    p = api.get("/api/packs/test").json()
    assert 3000 < p["grid_pitch_m"] < 5000
    assert p["timezone"] == "Asia/Dubai" and len(p["regions"]["features"]) == 2 and len(p["grid"]) > 20
    assert api.get("/api/packs/nope").status_code == 404
    n = api.get("/api/flights/count", params={"pack": "test", "date": synth.DATE_LOCAL}).json()
    assert n["prop"] == 153 and n["days_ready"] is False
    n = api.get("/api/flights/count", params={"pack": "test", "date": synth.DATE_LOCAL, "ranges": "01:00-02:00"}).json()
    assert n["prop"] == 0
    days = api.get("/api/packs/test/days").json()
    assert {"utc_date": synth.UTC_DAY, "status": "ready"}.items() <= days[0].items()


# --- a case, from upload to the 409s ---------------------------------------------------------

@pytest.fixture(scope="module")
def case(api, site, short_wav):
    r = api.post("/api/cases", json={"pack_id": "test"})
    assert r.status_code == 200
    cid = r.json()["id"]
    assert api.get(f"/api/cases/{cid}/spectrogram").status_code == 404
    with open(short_wav, "rb") as fh:
        r = api.post(f"/api/cases/{cid}/media", files={"file": ("../../evil name.wav", fh, "audio/wav")})
    assert r.status_code == 200, r.text
    media = r.json()["media"]
    assert len(media["sha256"]) == 64 and abs(media["duration_s"] - CLIP_S) < 1 and media["filename"] == "evil name.wav"
    stored = list((site["data"] / "uploads" / cid).iterdir())
    assert [p.name for p in stored] == ["original.wav"]              # the path never comes from the client's name
    return cid


def test_upload_rules(api, case, tmp_path):
    junk = tmp_path / "notes.wav"
    junk.write_text("not audio at all")
    cid = api.post("/api/cases", json={}).json()["id"]
    with open(junk, "rb") as fh:
        r = api.post(f"/api/cases/{cid}/media", files={"file": ("notes.wav", fh, "audio/wav")})
    assert r.status_code == 422 and err(r) in ("not_media", "no_audio")
    assert api.get(f"/api/cases/{cid}").json()["media"] is None
    with open(junk, "rb") as fh:                                      # a second file on a case that has one
        r = api.post(f"/api/cases/{case}/media", files={"file": ("again.wav", fh, "audio/wav")})
    assert r.status_code == 409 and err(r) == "media_exists"


def test_case_fields_are_validated(api, case):
    assert api.patch(f"/api/cases/{case}", json={"date_local": "14/11/2026"}).status_code == 422
    assert api.patch(f"/api/cases/{case}", json={"region_ids": ["atlantis"]}).status_code == 422
    assert api.patch(f"/api/cases/{case}", json={"time_ranges": [["25:00", "26:00"]]}).status_code == 422
    assert api.patch(f"/api/cases/{case}", json={"temperature_c": 400}).status_code == 422
    r = api.patch(f"/api/cases/{case}", json={"date_local": synth.DATE_LOCAL, "time_ranges": [["12:00", "17:00"]],
                                             "region_ids": ["home"], "temperature_c": 28.0})
    assert r.status_code == 200 and r.json()["temperature_source"] == "analyst"
    assert r.json()["temperature_effective"] == {"c": 28.0, "source": "analyst"}
    fresh = api.post("/api/cases", json={}).json()["id"]
    api.patch(f"/api/cases/{fresh}", json={"date_local": synth.DATE_LOCAL})
    assert api.get(f"/api/cases/{fresh}").json()["temperature_effective"] == {"c": 28.0, "source": "climate_monthly"}
    assert api.get("/api/cases/does-not-exist").status_code == 404


def test_triage_writes_the_spectrogram_and_proposals(api, site, case):
    assert run_jobs(site)                                             # the triage job queued by the upload
    c = api.get(f"/api/cases/{case}").json()
    assert c["status"] == "triaged" and c["job"]["kind"] == "triage" and c["job"]["status"] == "done"
    s = api.get(f"/api/cases/{case}/spectrogram", params={"t0": 250, "t1": 370, "f_lo": 80, "f_hi": 180, "cols": 120, "rows": 50}).json()
    grid = np.frombuffer(base64.b64decode(s["data"]), np.uint8).reshape(s["rows"], s["cols"])
    assert grid.shape == (50, 120) and grid.max() > 100
    evs = api.get(f"/api/cases/{case}/events").json()
    assert evs and all(e["source"] == "detect" and e["status"] == "proposed" and len(e["curve"]) > 10 for e in evs)
    # proposals are shown as bend boxes, about 100 s, kept inside the recording
    assert all(20 <= e["t_end"] - e["t_start"] <= 100 and e["t_start"] >= 0 and e["t_end"] <= CLIP_S for e in evs)


def test_search_is_refused_until_the_case_is_ready(api, case):
    r = api.post(f"/api/cases/{case}/search")
    assert r.status_code == 409 and err(r) == "case_ref_required"
    api.patch(f"/api/cases/{case}", json={"case_ref": "CASE-2026-0042"})
    r = api.post(f"/api/cases/{case}/search")
    assert r.status_code == 409 and err(r) == "need_two_flyovers"      # proposals do not count: none is confirmed


def test_event_editor(api, case):
    b = synth.BEND_BOXES[0]
    r = api.post(f"/api/cases/{case}/events", json={"t_start": b[0], "t_end": b[1], "f_lo": b[2], "f_hi": b[3], "harmonics": 1})
    assert r.status_code == 200, r.text
    ev = r.json()
    assert ev["source"] == "analyst" and ev["status"] == "confirmed" and abs(ev["fit"]["f0"] - 120) < 3
    assert len(ev["curve"]) > 20 and ev["fit_temperature_c"] == 28.0
    # a snug box does not raise; a 1 Hz box is refused
    n = synth.NARROW_BOX
    r = api.post(f"/api/cases/{case}/events", json={"t_start": n[0], "t_end": n[1], "f_lo": n[2], "f_hi": n[3], "harmonics": 1})
    assert r.status_code == 200
    narrow = r.json()["id"]
    r = api.post(f"/api/cases/{case}/events", json={"t_start": 260, "t_end": 360, "f_lo": 120, "f_hi": 121, "harmonics": 1})
    assert r.status_code == 422 and err(r) == "box_too_small"
    assert api.post(f"/api/cases/{case}/events", json={"t_start": 260}).status_code == 422
    # moving a box refits it; rejecting it does not
    r = api.patch(f"/api/cases/{case}/events/{narrow}", json={"f_lo": 105.0, "f_hi": 150.0})
    assert r.status_code == 200 and r.json()["f_lo"] == 105.0 and r.json()["fit"] is not None
    assert api.patch(f"/api/cases/{case}/events/{narrow}", json={"status": "rejected"}).json()["status"] == "rejected"
    assert api.delete(f"/api/cases/{case}/events/{narrow}").status_code == 200
    # one confirmed flyover is still not enough
    r = api.post(f"/api/cases/{case}/search")
    assert r.status_code == 409 and err(r) == "need_two_flyovers"
    # confirming a proposal counts, and refits its box
    prop = [e for e in api.get(f"/api/cases/{case}/events").json() if e["status"] == "proposed"][0]
    r = api.patch(f"/api/cases/{case}/events/{prop['id']}", json={"status": "confirmed"})
    assert r.status_code == 200 and r.json()["status"] == "confirmed"


def test_search_runs_and_the_result_and_report_come_back(api, site, case):
    r = api.post(f"/api/cases/{case}/search")
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    r = api.post(f"/api/cases/{case}/search")
    assert r.status_code == 409 and err(r) == "search_running"
    assert api.get(f"/api/cases/{case}/result").status_code == 404
    assert run_jobs(site) == [job_id]
    c = api.get(f"/api/cases/{case}").json()
    assert c["status"] == "done" and c["result"]["state"] in ("candidates", "outside", "located", "not_locatable")
    res = api.get(f"/api/cases/{case}/result").json()
    assert res["state"] == c["result"]["state"] and res["inputs"]["temperature_c"] == 28.0
    assert res["inputs"]["file_sha256"] == c["media"]["sha256"]
    html = api.get(f"/api/cases/{case}/report")
    assert html.status_code == 200 and html.headers["content-type"].startswith("text/html")
    assert "CASE-2026-0042" in html.text and "adsb.lol" in html.text and "<script" not in html.text


def test_flight_days_are_fetched_only_on_request(api, site, monkeypatch):
    days = {d["utc_date"]: d for d in api.get("/api/packs/test/days").json()}
    assert days[synth.UTC_DAY]["status"] == "ready" and "2026-11-13" not in days
    counted = api.get("/api/flights/count", params={"pack": "test", "date": synth.DATE_LOCAL}).json()
    assert [(d["utc_date"], d["status"]) for d in counted["days"]] == [("2026-11-13", "missing"), ("2026-11-14", "ready")]
    for bad in ("tomorrow", "2099-01-01", "2019-06-01"):
        assert api.post("/api/packs/test/days", json={"utc_date": bad}).status_code == 422
    assert api.post("/api/packs/test/days", json={"utc_date": synth.UTC_DAY}).json()["status"] == "ready"      # already here: nothing queued

    r = api.post("/api/packs/test/days", json={"utc_date": "2026-11-13"})
    assert r.status_code == 200 and r.json()["status"] == "fetching" and r.json()["progress"] == "waiting to start"
    assert api.post("/api/packs/test/days", json={"utc_date": "2026-11-13"}).json()["status"] == "fetching"   # asked twice: one job
    counted = api.get("/api/flights/count", params={"pack": "test", "date": synth.DATE_LOCAL}).json()
    assert counted["days"][0]["status"] == "fetching"
    assert ("flights.fetch", ) == tuple({a for a, d in audit_actions() if a == "flights.fetch" and "2026-11-13" in (d or "")})

    # the job itself, with the archive stood in for: one that is not published, then one that is
    from app.core import flights

    def missing(pack, day, data_dir, progress=None, types=None):
        raise RuntimeError("404 Client Error: Not Found for url")

    monkeypatch.setattr(flights, "ensure_day", missing)
    run_jobs(site)
    day = {d["utc_date"]: d for d in api.get("/api/packs/test/days").json()}["2026-11-13"]
    assert day["status"] == "failed" and day["error"] == "No flight archive is published for that day."

    def fetched(pack, day, data_dir, progress=None, types=None):
        progress(4000, 250_000_000)
        path = flights.traces_path(data_dir, pack.id, day)
        path.write_bytes(flights.traces_path(data_dir, pack.id, synth.UTC_DAY).read_bytes())
        return path, {"n_traces": 153, "n_prop": 153, "source": "stand-in", "fetched_at": "2026-11-22T00:00:00Z",
                      "integrity": {"version": 1, "aircraft": 153, "rows": 1000, "dropped": {}, "rows_dropped": 40, "rows_dropped_pct": 4.0}}

    monkeypatch.setattr(flights, "ensure_day", fetched)
    assert api.post("/api/packs/test/days", json={"utc_date": "2026-11-13"}).json()["status"] == "fetching"   # a failed day can be asked for again
    run_jobs(site)
    day = {d["utc_date"]: d for d in api.get("/api/packs/test/days").json()}["2026-11-13"]
    assert day["status"] == "ready"
    counted = api.get("/api/flights/count", params={"pack": "test", "date": synth.DATE_LOCAL}).json()
    assert counted["days_ready"] is True and counted["prop"] == 153
    (site["data"] / "flights" / "test" / "2026-11-13-traces.npz").unlink()          # leave the shared flight folder as it was


def test_the_newest_flight_day_is_fetched_after_sign_in(api, site, monkeypatch):
    """The page asks for this once it is signed in: the newest published day is fetched in
    the background, and the header shows how far it has got."""
    import datetime as dt

    from app import db
    from app.core import flights

    today = dt.datetime.now(dt.timezone.utc).date()
    yesterday, older = (today - dt.timedelta(days=1)).isoformat(), (today - dt.timedelta(days=2)).isoformat()
    folder = site["data"] / "flights" / "ny"
    made = []

    def jobs():
        with db.connect() as conn:
            return [r["id"] for r in conn.execute("SELECT id FROM jobs WHERE kind = 'fetch' AND json_extract(params, '$.latest') = 1")]

    try:
        # the synthetic pack has invented flights: nothing to update, and nothing is queued
        assert api.get("/api/packs/test/latest").json()["status"] == "off"
        assert api.post("/api/packs/test/latest").json()["status"] == "off" and jobs() == []
        assert api.get("/api/packs/ny/latest").json() == {
            "pack_id": "ny", "pack_name": "New York area", "status": "idle", "utc_date": None, "newest_on_disk": None,
            "fraction": None, "bytes_total": None, "detail": None, "error": None, "checked_at": None}

        # asking queues one job, however often the page asks, and is logged
        r = api.post("/api/packs/ny/latest").json()
        assert r["status"] == "checking" and r["detail"] == "waiting to start"
        assert api.post("/api/packs/ny/latest").json()["status"] == "checking" and len(jobs()) == 1
        assert [d for a, d in audit_actions() if a == "flights.update"] == [f"pack=ny newest day job={jobs()[0]}"]

        # the archive cannot be reached: a failure that is not retried on every page load, only when asked
        def unreachable(today):
            raise OSError("no route to host")

        monkeypatch.setattr(flights, "latest_published", unreachable)
        run_jobs(site)
        r = api.get("/api/packs/ny/latest").json()
        assert r["status"] == "failed" and r["error"] == "The flight archive could not be reached."
        assert api.post("/api/packs/ny/latest").json()["status"] == "failed" and len(jobs()) == 1
        assert api.post("/api/packs/ny/latest", json={"force": True}).json()["status"] == "checking" and len(jobs()) == 2

        # yesterday is not published yet, the day before is: that one is fetched, with a known size
        seen = {}

        def fetched(pack, day, data_dir, progress=None, types=None):
            progress(4000, 900_000_000)
            seen.update(api.get("/api/packs/ny/latest").json())
            path = flights.traces_path(data_dir, pack.id, day)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(flights.traces_path(data_dir, "test", synth.UTC_DAY).read_bytes())
            made.append(path)
            return path, {"n_traces": 153, "n_prop": 153, "source": "stand-in", "fetched_at": "2026-11-22T00:00:00Z", "integrity": {}}

        monkeypatch.setattr(flights, "latest_published", lambda today: (older, 3_600_000_000))
        monkeypatch.setattr(flights, "ensure_day", fetched)
        run_jobs(site)
        assert {"status": "fetching", "utc_date": older, "fraction": 0.25, "bytes_total": 3_600_000_000}.items() <= seen.items()
        assert "0.90 of 3.60 GB" in seen["detail"]
        r = api.get("/api/packs/ny/latest").json()
        assert r["status"] == "current" and r["newest_on_disk"] == older and r["checked_at"] and r["error"] is None
        assert {d["utc_date"]: d["status"] for d in api.get("/api/packs/ny/days").json()} == {older: "ready"}
        assert api.post("/api/packs/ny/latest").json()["status"] == "current" and len(jobs()) == 2      # checked a moment ago

        # asked again: the newest published day is already here, so nothing is streamed
        def never(*a, **k):
            raise AssertionError("a day on disk was fetched again")

        monkeypatch.setattr(flights, "ensure_day", never)
        assert api.post("/api/packs/ny/latest", json={"force": True}).json()["status"] == "checking"
        run_jobs(site)
        assert api.get("/api/packs/ny/latest").json()["status"] == "current" and len(jobs()) == 3

        # with yesterday on disk nothing newer can exist: no job, even when forced
        made.append(folder / f"{yesterday}-traces.npz")
        made[-1].write_bytes(made[0].read_bytes())
        r = api.post("/api/packs/ny/latest", json={"force": True}).json()
        assert r["status"] == "current" and r["newest_on_disk"] == yesterday and len(jobs()) == 3

        # switched off: the page is told so and nothing is queued
        made.pop().unlink()
        monkeypatch.setenv("FLIGHTS_AUTO", "0")
        assert api.post("/api/packs/ny/latest", json={"force": True}).json()["status"] == "off" and len(jobs()) == 3
    finally:
        for f in made:                                 # leave the shared flight folder as it was
            f.unlink(missing_ok=True)
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()


def _case_with_recording(api, short_wav, name="clip.wav"):
    cid = api.post("/api/cases", json={"pack_id": "test"}).json()["id"]
    with open(short_wav, "rb") as fh:
        assert api.post(f"/api/cases/{cid}/media", files={"file": (name, fh, "audio/wav")}).status_code == 200
    return cid


def test_a_case_and_its_recording_can_be_deleted(api, site, short_wav):
    from fastapi.testclient import TestClient

    from app import db
    from app.api import auth

    cid = _case_with_recording(api, short_wav, "to-delete.wav")
    folder = site["data"] / "uploads" / cid
    sha = api.get(f"/api/cases/{cid}").json()["media"]["sha256"]
    assert (folder / "original.wav").exists()

    # someone else cannot delete it, or learn that it exists
    pw = secrets.token_urlsafe(12)
    with db.connect() as conn:
        if not db.one(conn, "SELECT id FROM users WHERE email = 'deleter@trace.test'"):
            auth.create_user(conn, "deleter@trace.test", pw, role="analyst")
        else:
            auth.set_password(conn, "deleter@trace.test", pw)
    other = TestClient(site["client"].app)
    assert other.post("/api/auth/login", json={"email": "deleter@trace.test", "password": pw}).status_code == 200
    assert other.delete(f"/api/cases/{cid}").status_code == 404 and folder.exists()

    # not while a job of the case is running: its process would write into a case that is gone
    with db.connect() as conn, conn:
        conn.execute("UPDATE jobs SET status = 'running' WHERE case_id = ? AND status = 'queued'", (cid,))
    r = api.delete(f"/api/cases/{cid}")
    assert r.status_code == 409 and err(r) == "case_busy" and folder.exists()
    with db.connect() as conn, conn:
        conn.execute("UPDATE jobs SET status = 'queued' WHERE case_id = ? AND status = 'running'", (cid,))

    # a job still waiting is dropped with the case
    assert api.delete(f"/api/cases/{cid}").json() == {"ok": True}
    assert not folder.exists() and api.get(f"/api/cases/{cid}").status_code == 404
    assert cid not in [c["id"] for c in api.get("/api/cases").json()]
    with db.connect() as conn:
        for table in ("media", "events", "jobs", "job_events", "results"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE case_id = ?", (cid,)).fetchone()[0] == 0, table
    # what was deleted stays on record
    assert [d for a, d in audit_actions(cid) if a == "case.delete"] == [f"file=to-delete.wav sha256={sha}"]
    assert api.delete(f"/api/cases/{cid}").status_code == 404


def test_old_cases_are_deleted_when_retention_is_set(api, site, short_wav, monkeypatch):
    from app import db, retention
    from app.worker import Worker

    old, busy, fresh = (_case_with_recording(api, short_wav) for _ in range(3))
    long_ago = "2026-01-01T00:00:00.000000Z"
    with db.connect() as conn, conn:                                   # the analysis jobs are not what is tested here
        conn.execute("UPDATE cases SET created_at = ? WHERE id IN (?, ?)", (long_ago, old, busy))
        conn.execute("UPDATE jobs SET status = 'done' WHERE case_id IN (?, ?)", (old, fresh))
        conn.execute("UPDATE jobs SET status = 'running' WHERE case_id = ?", (busy,))
    with db.connect() as conn:
        assert retention.expire(conn, 0) == []                         # 0: keep everything
    assert all((site["data"] / "uploads" / c).exists() for c in (old, busy, fresh))

    # the worker does the housekeeping, from RETENTION_DAYS
    monkeypatch.setenv("RETENTION_DAYS", "30")
    w = Worker()
    try:
        assert w.housekeep() == [old] and w.housekeep() == []          # the second call is within the hour: nothing to do
    finally:
        w.conn.close()
    assert not (site["data"] / "uploads" / old).exists() and (site["data"] / "uploads" / busy).exists() and (site["data"] / "uploads" / fresh).exists()
    assert api.get(f"/api/cases/{old}").status_code == 404 and api.get(f"/api/cases/{fresh}").status_code == 200
    assert [d for a, d in audit_actions(old) if a == "case.expired"][0].startswith("retention_days=30 created=2026-01-01")
    with db.connect() as conn, conn:
        conn.execute("UPDATE jobs SET status = 'done' WHERE case_id = ?", (busy,))
    for c in (busy, fresh):
        assert api.delete(f"/api/cases/{c}").status_code == 200


def test_sign_in_attempts_are_limited_per_address(site, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("LOGIN_FAILURES_MAX", "3")
    there = TestClient(site["client"].app, client=("203.0.113.7", 40000))
    for _ in range(3):
        r = there.post("/api/auth/login", json={"email": site["creds"]["email"], "password": "wrong-" + secrets.token_urlsafe(6)})
        assert r.status_code == 401
    # now even the right password is refused from that address, for a while
    r = there.post("/api/auth/login", json=site["creds"])
    assert r.status_code == 429 and err(r) == "too_many_attempts"
    # another address is not affected
    elsewhere = TestClient(site["client"].app, client=("203.0.113.8", 40000))
    assert elsewhere.post("/api/auth/login", json=site["creds"]).status_code == 200
    # and the block ends with the window
    from app import db

    with db.connect() as conn, conn:
        conn.execute("UPDATE audit_log SET ts = '2026-01-01T00:00:00.000000Z' WHERE action = 'login.failed' AND ip = '203.0.113.7'")
    assert there.post("/api/auth/login", json=site["creds"]).status_code == 200


def test_the_session_cookie_can_be_https_only(site, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api.main import create_app

    assert "secure" not in site["client"].post("/api/auth/login", json=site["creds"]).headers["set-cookie"].lower()
    monkeypatch.setenv("SESSION_SECURE", "1")
    with TestClient(create_app(), base_url="https://testserver") as c:
        assert "secure" in c.post("/api/auth/login", json=site["creds"]).headers["set-cookie"].lower()


def test_no_flyovers_ends_as_not_locatable(api, site, short_wav):
    cid = api.post("/api/cases", json={"pack_id": "test"}).json()["id"]
    r = api.post(f"/api/cases/{cid}/not-locatable")
    assert r.status_code == 409 and err(r) == "spectrogram_not_ready"
    with open(short_wav, "rb") as fh:
        assert api.post(f"/api/cases/{cid}/media", files={"file": ("quiet.wav", fh, "audio/wav")}).status_code == 200
    run_jobs(site)
    c = api.get(f"/api/cases/{cid}").json()
    assert c["stream_from"] < c["last_event_id"]                      # a page opening now would replay the triage job
    # no case reference, no date, nothing confirmed: still a recorded outcome
    r = api.post(f"/api/cases/{cid}/not-locatable")
    assert r.status_code == 200, r.text
    assert run_jobs(site) == [r.json()["job_id"]]
    res = api.get(f"/api/cases/{cid}/result").json()
    assert res["state"] == "not_locatable" and res["band"] == "None" and res["estimate"] is None
    assert res["not_locatable"]["reason"] == "fewer_than_two_flyovers" and res["not_locatable"]["advice"]
    assert "Not locatable" in api.get(f"/api/cases/{cid}/report").text
    assert "case.not_locatable" in [a for a, _ in audit_actions(cid)]


def test_not_locatable_is_refused_when_flyovers_are_confirmed(api, case):
    r = api.post(f"/api/cases/{case}/not-locatable")
    assert r.status_code == 409 and err(r) == "has_flyovers"


def test_every_state_change_is_audited(api, case):
    actions = audit_actions(case)
    names = [a for a, _ in actions]
    for expected in ("case.create", "media.upload", "case.update", "event.confirm", "event.update", "event.delete",
                     "search.start", "result.view", "report.export"):
        assert expected in names, expected
    sha = api.get(f"/api/cases/{case}").json()["media"]["sha256"]
    assert any(a == "media.upload" and sha in (d or "") for a, d in actions)


def test_cases_are_private_to_their_owner(api, site, case):
    from fastapi.testclient import TestClient

    from app import db
    from app.api import auth

    pw = secrets.token_urlsafe(12)
    with db.connect() as conn:
        auth.create_user(conn, "other@trace.test", pw, role="analyst")
    other = TestClient(site["client"].app)
    assert other.post("/api/auth/login", json={"email": "other@trace.test", "password": pw}).status_code == 200
    assert other.get(f"/api/cases/{case}").status_code == 404
    assert other.get(f"/api/cases/{case}/result").status_code == 404
    assert other.get("/api/cases").json() == []
    mine = [c for c in api.get("/api/cases").json() if c["id"] == case][0]
    assert mine["case_ref"] == "CASE-2026-0042" and mine["filename"] == "evil name.wav" and mine["date_local"] == synth.DATE_LOCAL
    assert mine["pack_id"] == "test" and mine["flyovers"] >= 2 and mine["state"] and abs(mine["duration_s"] - CLIP_S) < 1


def test_upload_rate_limit(api, site, short_wav, monkeypatch):
    monkeypatch.setenv("RATE_UPLOADS_PER_HOUR", "0")
    cid = api.post("/api/cases", json={}).json()["id"]
    with open(short_wav, "rb") as fh:
        r = api.post(f"/api/cases/{cid}/media", files={"file": ("clip.wav", fh, "audio/wav")})
    assert r.status_code == 429 and err(r) == "rate_limited"
