"""Cases: the recording, its flyovers, the search and its result."""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import json
import math
import re
import shutil
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .. import config, db
from ..core import media as media_core
from ..core import report, spectro, weather
from ..models import event_public
from .deps import ApiError, audit, current_user, get_case, get_conn, rate_limit
from .packs import load_pack, valid_hhmm

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


# --- shapes --------------------------------------------------------------------------------

class CaseCreate(BaseModel):
    pack_id: str | None = None


class CasePatch(BaseModel):
    date_local: str | None = None
    time_ranges: list[list[str]] | None = None
    region_ids: list[str] | None = None
    custom_bbox: list[float] | None = None
    temperature_c: float | None = None
    case_ref: str | None = None


class EventCreate(BaseModel):
    t_start: float
    t_end: float
    f_lo: float
    f_hi: float
    harmonics: int = 1


class EventPatch(BaseModel):
    status: str | None = None
    t_start: float | None = None
    t_end: float | None = None
    f_lo: float | None = None
    f_hi: float | None = None
    harmonics: int | None = None


def _js(v):
    return json.loads(v) if v else None


def case_public(conn, case: dict) -> dict:
    m = db.one(conn, "SELECT id, filename, sha256, size_bytes, duration_s, created_at FROM media WHERE case_id = ?", (case["id"],))
    job = db.one(conn, "SELECT id, kind, status, stage, progress, error, created_at, started_at, finished_at FROM jobs"
                       " WHERE case_id = ? ORDER BY created_at DESC, id DESC LIMIT 1", (case["id"],))
    res = db.one(conn, "SELECT id, state, verdict, p, strength, band, lat, lon, radius_m, created_at FROM results"
                       " WHERE case_id = ? ORDER BY created_at DESC, id DESC LIMIT 1", (case["id"],))
    n = {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) AS n FROM events WHERE case_id = ? GROUP BY status", (case["id"],))}
    last = conn.execute("SELECT COALESCE(MAX(id), 0) FROM job_events WHERE case_id = ?", (case["id"],)).fetchone()[0]
    # where a page that has just opened should start the stream: the latest job's first event,
    # so its stages and progress are replayed and nothing older is
    first = conn.execute("SELECT MIN(id) FROM job_events WHERE job_id = ?", (job["id"],)).fetchone()[0] if job else None
    try:                                       # what a fit or search would use right now: the analyst's, else the pack's monthly figure
        temp, source = weather.for_case(load_pack(case["pack_id"]), case["date_local"], _js(case["time_ranges"]),
                                        case["temperature_c"], case["temperature_source"])
        effective = {"c": temp, "source": source}
    except LookupError:
        effective = None
    return {"temperature_effective": effective,
            "id": case["id"], "case_ref": case["case_ref"], "created_at": case["created_at"], "status": case["status"],
            "pack_id": case["pack_id"], "date_local": case["date_local"], "time_ranges": _js(case["time_ranges"]),
            "region_ids": _js(case["region_ids"]), "custom_bbox": _js(case["custom_bbox"]),
            "temperature_c": case["temperature_c"], "temperature_source": case["temperature_source"],
            "media": ({**m, "spectrogram_ready": spectro.exists(config.case_dir(case["id"]))} if m else None),
            "events": {"proposed": n.get("proposed", 0), "confirmed": n.get("confirmed", 0), "rejected": n.get("rejected", 0)},
            "job": job, "result": res, "last_event_id": last, "stream_from": (first - 1) if first else last}


def _finite(*xs) -> bool:
    return all(isinstance(x, (int, float)) and math.isfinite(x) for x in xs)


# --- cases ---------------------------------------------------------------------------------

@router.get("/cases")
def list_cases(user=Depends(current_user), conn=Depends(get_conn)):
    where, args = ("", ()) if user["role"] == "admin" else ("WHERE c.created_by = ?", (user["id"],))
    return db.rows(conn, f"""
        SELECT c.id, c.case_ref, c.created_at, c.status, c.pack_id, c.date_local, m.filename, m.duration_s,
               (SELECT COUNT(*) FROM events e WHERE e.case_id = c.id AND e.status = 'confirmed') AS flyovers,
               (SELECT state FROM results r WHERE r.case_id = c.id ORDER BY r.created_at DESC, r.id DESC LIMIT 1) AS state,
               (SELECT band FROM results r WHERE r.case_id = c.id ORDER BY r.created_at DESC, r.id DESC LIMIT 1) AS band
        FROM cases c LEFT JOIN media m ON m.case_id = c.id {where} ORDER BY c.created_at DESC""", args)


@router.post("/cases")
def create_case(request: Request, body: CaseCreate | None = None, user=Depends(current_user), conn=Depends(get_conn)):
    pack = load_pack((body.pack_id if body and body.pack_id else None) or config.default_pack())
    case_id = db.ulid()
    with conn:
        conn.execute("INSERT INTO cases (id, created_by, created_at, status, pack_id) VALUES (?, ?, ?, 'draft', ?)",
                     (case_id, user["id"], db.now(), pack.id))
    audit(conn, request, user, case_id, "case.create", f"pack={pack.id}")
    return {"id": case_id}


@router.get("/cases/{case_id}")
def read_case(case_id: str, user=Depends(current_user), conn=Depends(get_conn)):
    return case_public(conn, get_case(conn, user, case_id))


@router.delete("/cases/{case_id}")
def delete_case(case_id: str, request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    """Remove the case with its recording, spectrogram, flyovers and results. Its lines in
    the audit log stay, and one is added naming the recording and its hash."""
    from .. import retention

    get_case(conn, user, case_id)
    if retention.busy(conn, case_id):
        raise ApiError(409, "case_busy", "This case is still being analysed or searched. Stop the search or wait for it to finish, then delete it.")
    what = retention.describe(conn, case_id)
    retention.delete_case(conn, case_id)
    audit(conn, request, user, case_id, "case.delete", what)
    return {"ok": True}


@router.patch("/cases/{case_id}")
def update_case(case_id: str, body: CasePatch, request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    case = get_case(conn, user, case_id)
    pack = load_pack(case["pack_id"])
    bad = lambda msg: ApiError(422, "invalid_request", msg)
    sets: dict[str, object] = {}
    given = body.model_fields_set
    if "date_local" in given:
        if body.date_local is not None:
            try:
                _dt.date.fromisoformat(body.date_local)
            except ValueError:
                raise bad("date_local must be YYYY-MM-DD") from None
        sets["date_local"] = body.date_local
    if "time_ranges" in given:
        tr = body.time_ranges or None
        if tr and not all(len(r) == 2 and valid_hhmm(r[0]) and valid_hhmm(r[1]) and r[0] != r[1] for r in tr):
            raise bad('time_ranges must be pairs like ["12:00", "17:00"]')
        sets["time_ranges"] = json.dumps(tr) if tr else None
    if "region_ids" in given:
        ids = body.region_ids or None
        if ids and not all(any(r.id == i for r in pack.regions) for i in ids):
            raise bad("unknown region")
        sets["region_ids"] = json.dumps(ids) if ids else None
    if "custom_bbox" in given:
        bb = body.custom_bbox
        if bb is not None and not (len(bb) == 4 and _finite(*bb) and bb[0] < bb[1] and bb[2] < bb[3]):
            raise bad("custom_bbox must be [lat_min, lat_max, lon_min, lon_max]")
        sets["custom_bbox"] = json.dumps(bb) if bb is not None else None
    if "temperature_c" in given:
        t = body.temperature_c
        if t is not None and not (_finite(t) and -60.0 <= t <= 60.0):
            raise bad("temperature_c must be between -60 and 60")
        sets["temperature_c"], sets["temperature_source"] = t, ("analyst" if t is not None else None)
    if "case_ref" in given:
        ref = (body.case_ref or "").strip()
        if len(ref) > 120:
            raise bad("case_ref is too long")
        sets["case_ref"] = ref or None
    if sets:
        with conn:
            conn.execute(f"UPDATE cases SET {', '.join(k + ' = ?' for k in sets)} WHERE id = ?", (*sets.values(), case_id))
        audit(conn, request, user, case_id, "case.update", ", ".join(sorted(sets)))
    return case_public(conn, get_case(conn, user, case_id))


# --- the recording --------------------------------------------------------------------------

@router.post("/cases/{case_id}/media")
def upload(case_id: str, request: Request, file: UploadFile = File(...), user=Depends(current_user), conn=Depends(get_conn)):
    """The original is kept untouched and hashed; triage is queued at once."""
    get_case(conn, user, case_id)
    if db.one(conn, "SELECT id FROM media WHERE case_id = ?", (case_id,)):
        raise ApiError(409, "media_exists", "This case already has a recording. Start a new case for another file.")
    rate_limit(conn, user, "media.upload", "uploads")
    limit = config.max_upload_bytes()
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit + 1_000_000:
        raise ApiError(413, "too_large", f"The file is over the {limit // (1024 * 1024)} MB limit.")
    # the stored path comes from the case id; only a short, safe extension is taken from the client's name
    name = PurePosixPath((file.filename or "recording").replace("\\", "/")).name[:200] or "recording"
    ext = PurePosixPath(name).suffix.lower()
    ext = ext if re.fullmatch(r"\.[a-z0-9]{1,5}", ext) else ".bin"
    folder = config.case_dir(case_id)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"original{ext}"
    h, size = hashlib.sha256(), 0
    try:
        with open(dest, "wb") as out:
            while block := file.file.read(1 << 20):
                size += len(block)
                if size > limit:
                    raise ApiError(413, "too_large", f"The file is over the {limit // (1024 * 1024)} MB limit.")
                h.update(block)
                out.write(block)
        if size == 0:
            raise ApiError(422, "empty_file", "The file is empty.")
        try:
            info = media_core.probe(dest)
        except media_core.MediaError as e:
            raise ApiError(422, e.code, str(e)) from None
        if info.duration_s > config.max_duration_s():
            raise ApiError(422, "too_long", f"The recording is longer than {config.max_duration_s() / 3600:g} hours.")
    except ApiError:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    media_id = db.ulid()
    with conn:
        conn.execute("INSERT INTO media (id, case_id, filename, sha256, size_bytes, duration_s, path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (media_id, case_id, name, h.hexdigest(), size, info.duration_s, str(dest), db.now()))
        job_id = db.queue_job(conn, "triage", case_id)
    audit(conn, request, user, case_id, "media.upload", f"sha256={h.hexdigest()} bytes={size} file={name}")
    return {"media": {"id": media_id, "filename": name, "sha256": h.hexdigest(), "size_bytes": size, "duration_s": info.duration_s,
                      "codec": info.codec}, "job_id": job_id}


@router.get("/cases/{case_id}/spectrogram")
def spectrogram(case_id: str, t0: float | None = None, t1: float | None = None, f_lo: float = 40.0, f_hi: float = 450.0,
                cols: int = 600, rows: int = 140, user=Depends(current_user), conn=Depends(get_conn)):
    """One window of the spectrogram as a small grid: uint8, base64, row 0 the lowest frequency."""
    get_case(conn, user, case_id)
    folder = config.case_dir(case_id)
    if not spectro.exists(folder):
        raise ApiError(404, "spectrogram_not_ready", "The recording is still being analysed.")
    total = spectro.duration_s(folder)
    t0, t1 = (0.0 if t0 is None else t0), (total if t1 is None else t1)
    if not (_finite(t0, t1, f_lo, f_hi) and t1 > t0 and f_hi > f_lo and 1 <= cols <= 4096 and 1 <= rows <= 1024):
        raise ApiError(422, "invalid_request", "bad spectrogram window")
    m = spectro.matrix(folder, t0, t1, f_lo, f_hi, cols, rows)
    return {**{k: v for k, v in m.items() if k != "data"}, "duration_s": total, "data": base64.b64encode(m["data"]).decode()}


# --- flyovers -------------------------------------------------------------------------------

def _case_c(case: dict) -> tuple[float, float]:
    """(temperature, speed of sound) for an editor preview: the case's, else the pack's
    monthly figure. The search refits at its own temperature, so a stale preview is harmless."""
    temp, _ = weather.for_case(load_pack(case["pack_id"]), case["date_local"], _js(case["time_ranges"]), case["temperature_c"],
                               case["temperature_source"])
    return temp, weather.speed_of_sound(temp)


def _check_box(t_start, t_end, f_lo, f_hi, harmonics) -> None:
    if not (_finite(t_start, t_end, f_lo, f_hi) and t_end > t_start and f_hi > f_lo and t_start >= -1 and f_lo > 0 and 1 <= harmonics <= 5):
        raise ApiError(422, "invalid_request", "a box needs t_start < t_end, f_lo < f_hi and 1 to 5 harmonics")


def _ready_dir(case_id: str):
    folder = config.case_dir(case_id)
    if not spectro.exists(folder):
        raise ApiError(409, "spectrogram_not_ready", "The recording is still being analysed.")
    return folder


@router.get("/cases/{case_id}/events")
def list_events(case_id: str, user=Depends(current_user), conn=Depends(get_conn)):
    get_case(conn, user, case_id)
    return [event_public(r) for r in db.rows(conn, "SELECT * FROM events WHERE case_id = ? ORDER BY t_start, id", (case_id,))]


@router.post("/cases/{case_id}/events")
async def create_event(case_id: str, body: EventCreate, request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    """A box the analyst drew around a flyover's bend. Answers with the quick preview fit,
    about two seconds; the search later refits it in full."""
    case = get_case(conn, user, case_id)
    _check_box(body.t_start, body.t_end, body.f_lo, body.f_hi, body.harmonics)
    folder = _ready_dir(case_id)
    temp, c = _case_c(case)
    out = await request.app.state.fitpool.preview(folder, body.t_start, body.t_end, body.f_lo, body.f_hi, body.harmonics, c)
    eid = db.ulid()
    with conn:
        conn.execute(
            "INSERT INTO events (id, case_id, source, status, t_start, t_end, f_lo, f_hi, harmonics, fit, curve, fit_temperature_c, score, burst, created_at)"
            " VALUES (?, ?, 'analyst', 'confirmed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (eid, case_id, body.t_start, body.t_end, body.f_lo, body.f_hi, body.harmonics, json.dumps(out["fit"]), json.dumps(out["curve"]),
             temp, out["fit"]["score"], out["burst"], db.now()))
    audit(conn, request, user, case_id, "event.confirm", f"event={eid} box={body.t_start:g}-{body.t_end:g}s {body.f_lo:g}-{body.f_hi:g}Hz")
    return event_public(db.one(conn, "SELECT * FROM events WHERE id = ?", (eid,)))


@router.patch("/cases/{case_id}/events/{event_id}")
async def update_event(case_id: str, event_id: str, body: EventPatch, request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    case = get_case(conn, user, case_id)
    ev = db.one(conn, "SELECT * FROM events WHERE id = ? AND case_id = ?", (event_id, case_id))
    if not ev:
        raise ApiError(404, "event_not_found", "No such flyover.")
    given = body.model_fields_set
    if "status" in given and body.status not in ("proposed", "confirmed", "rejected"):
        raise ApiError(422, "invalid_request", "status must be proposed, confirmed or rejected")
    new = {k: getattr(body, k) for k in ("t_start", "t_end", "f_lo", "f_hi", "harmonics") if k in given and getattr(body, k) is not None}
    box_changed = any(new[k] != ev[k] for k in new)
    status = body.status if "status" in given else ev["status"]
    first_confirm = status == "confirmed" and ev["status"] == "proposed" and ev["source"] == "detect"
    merged = {**ev, **new, "status": status}
    if box_changed or first_confirm:
        # a proposal's own fit is too rough to show as confirmed: fit the box
        _check_box(merged["t_start"], merged["t_end"], merged["f_lo"], merged["f_hi"], merged["harmonics"])
        temp, c = _case_c(case)
        out = await request.app.state.fitpool.preview(_ready_dir(case_id), merged["t_start"], merged["t_end"], merged["f_lo"], merged["f_hi"],
                                                      merged["harmonics"], c)
        merged.update(fit=json.dumps(out["fit"]), curve=json.dumps(out["curve"]), fit_temperature_c=temp, score=out["fit"]["score"],
                      burst=out["burst"])
    if box_changed:
        merged["source"] = "analyst"            # the analyst has touched it: detection may no longer replace it
    with conn:
        conn.execute("UPDATE events SET source = ?, status = ?, t_start = ?, t_end = ?, f_lo = ?, f_hi = ?, harmonics = ?, fit = ?, curve = ?,"
                     " fit_temperature_c = ?, score = ?, burst = ? WHERE id = ?",
                     (merged["source"], merged["status"], merged["t_start"], merged["t_end"], merged["f_lo"], merged["f_hi"], merged["harmonics"],
                      merged["fit"], merged["curve"], merged["fit_temperature_c"], merged["score"], merged["burst"], event_id))
    became_confirmed = status == "confirmed" and ev["status"] != "confirmed"
    audit(conn, request, user, case_id, "event.confirm" if became_confirmed else "event.update",
          f"event={event_id} status={status}" + (" box changed" if box_changed else ""))
    return event_public(db.one(conn, "SELECT * FROM events WHERE id = ?", (event_id,)))


@router.delete("/cases/{case_id}/events/{event_id}")
def delete_event(case_id: str, event_id: str, request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    get_case(conn, user, case_id)
    with conn:
        n = conn.execute("DELETE FROM events WHERE id = ? AND case_id = ?", (event_id, case_id)).rowcount
    if not n:
        raise ApiError(404, "event_not_found", "No such flyover.")
    audit(conn, request, user, case_id, "event.delete", f"event={event_id}")
    return {"ok": True}


# --- the search -----------------------------------------------------------------------------

@router.post("/cases/{case_id}/search")
def start_search(case_id: str, request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    case = get_case(conn, user, case_id)
    if not case["case_ref"]:
        raise ApiError(409, "case_ref_required", "Give a case reference before searching.")
    if not case["date_local"]:
        raise ApiError(409, "date_required", "Give the recording date before searching.")
    if not spectro.exists(config.case_dir(case_id)):
        raise ApiError(409, "spectrogram_not_ready", "The recording is still being analysed.")
    n = conn.execute("SELECT COUNT(*) FROM events WHERE case_id = ? AND status = 'confirmed'", (case_id,)).fetchone()[0]
    if n < 2:
        raise ApiError(409, "need_two_flyovers", "Confirm at least two flyovers before searching.")
    if db.one(conn, "SELECT id FROM jobs WHERE case_id = ? AND kind = 'search' AND status IN ('queued', 'running')", (case_id,)):
        raise ApiError(409, "search_running", "A search is already running for this case.")
    rate_limit(conn, user, "search.start", "searches")
    with conn:
        # the analyst has confirmed their boxes, so the proposals still to come are not needed:
        # stop a triage job that is only detecting, or the search would wait behind it
        conn.execute("UPDATE jobs SET cancel_requested = 'truncate' WHERE case_id = ? AND kind = 'triage' AND status = 'running'", (case_id,))
        job_id = db.queue_job(conn, "search", case_id, {"flyovers": n})
        conn.execute("UPDATE cases SET status = 'searching' WHERE id = ?", (case_id,))
    audit(conn, request, user, case_id, "search.start", f"job={job_id} flyovers={n} case_ref={case['case_ref']}")
    return {"job_id": job_id}


@router.post("/cases/{case_id}/not-locatable")
def close_not_locatable(case_id: str, request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    """The analyst has looked and there are fewer than two flyovers to confirm: record that as
    the case's result, with what was checked and what would help. Nothing is searched, so no
    case reference or date is needed, but it is logged like any other outcome."""
    get_case(conn, user, case_id)
    if not spectro.exists(config.case_dir(case_id)):
        raise ApiError(409, "spectrogram_not_ready", "The recording is still being analysed.")
    n = conn.execute("SELECT COUNT(*) FROM events WHERE case_id = ? AND status = 'confirmed'", (case_id,)).fetchone()[0]
    if n >= 2:
        raise ApiError(409, "has_flyovers", "Two or more flyovers are confirmed: search instead.")
    if db.one(conn, "SELECT id FROM jobs WHERE case_id = ? AND kind = 'search' AND status IN ('queued', 'running')", (case_id,)):
        raise ApiError(409, "search_running", "A search is already running for this case.")
    with conn:
        conn.execute("UPDATE jobs SET cancel_requested = 'truncate' WHERE case_id = ? AND kind = 'triage' AND status = 'running'", (case_id,))
        job_id = db.queue_job(conn, "search", case_id, {"flyovers": n, "not_locatable": True})
        conn.execute("UPDATE cases SET status = 'searching' WHERE id = ?", (case_id,))
    audit(conn, request, user, case_id, "case.not_locatable", f"job={job_id} flyovers={n}")
    return {"job_id": job_id}


@router.delete("/cases/{case_id}/search")
def cancel_search(case_id: str, request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    get_case(conn, user, case_id)
    job = db.one(conn, "SELECT id, status FROM jobs WHERE case_id = ? AND kind = 'search' AND status IN ('queued', 'running')"
                       " ORDER BY created_at DESC LIMIT 1", (case_id,))
    if not job:
        raise ApiError(404, "no_search", "No search is running for this case.")
    with conn:
        was_queued = conn.execute("UPDATE jobs SET status = 'cancelled', finished_at = ? WHERE id = ? AND status = 'queued'",
                                  (db.now(), job["id"])).rowcount == 1
        if not was_queued:                       # running: the worker stops the child and records it
            conn.execute("UPDATE jobs SET cancel_requested = 'cancel' WHERE id = ?", (job["id"],))
        else:
            conn.execute("UPDATE cases SET status = 'triaged' WHERE id = ? AND status = 'searching'", (case_id,))
    if was_queued:
        db.emit(conn, job["id"], case_id, "cancelled", {"job": "search", "job_id": job["id"]})
    audit(conn, request, user, case_id, "search.cancel", f"job={job['id']}")
    return {"ok": True, "job_id": job["id"]}


def _latest_result(conn, case_id: str) -> dict:
    r = db.one(conn, "SELECT id, payload, created_at FROM results WHERE case_id = ? ORDER BY created_at DESC, id DESC LIMIT 1", (case_id,))
    if not r:
        raise ApiError(404, "no_result", "This case has no result yet.")
    return r


@router.get("/cases/{case_id}/result")
def result(case_id: str, request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    get_case(conn, user, case_id)
    r = _latest_result(conn, case_id)
    audit(conn, request, user, case_id, "result.view", f"result={r['id']}")
    return {"id": r["id"], "created_at": r["created_at"], **json.loads(r["payload"])}


@router.get("/cases/{case_id}/report", response_class=HTMLResponse)
def export_report(case_id: str, request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    """The self-contained, printable report."""
    case = get_case(conn, user, case_id)
    r = _latest_result(conn, case_id)
    m = db.one(conn, "SELECT filename FROM media WHERE case_id = ?", (case_id,)) or {}
    audit(conn, request, user, case_id, "report.export", f"result={r['id']}")
    html = report.render_html({"id": case_id, "case_ref": case["case_ref"], "filename": m.get("filename"), "created_at": case["created_at"]},
                              {**json.loads(r["payload"]), "created_at": r["created_at"]})
    return HTMLResponse(html, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})
