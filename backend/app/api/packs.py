"""Region packs and the flight days on disk for them."""
from __future__ import annotations

import datetime as _dt
import re

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from .. import config, db
from ..core import geo
from .deps import ApiError, audit, current_user, get_conn, rate_limit

router = APIRouter(prefix="/api")
_grid_cache: dict[str, list] = {}


def load_pack(pack_id: str) -> geo.Pack:
    try:
        return geo.load_pack(pack_id)
    except geo.PackNotFound:
        raise ApiError(404, "pack_not_found", "No such region pack.") from None


def parse_ranges(text: str | None):
    """"12:00-17:00,21:00-06:00" -> [["12:00", "17:00"], ["21:00", "06:00"]]"""
    if not text:
        return None
    out = []
    for part in text.split(","):
        m = re.fullmatch(r"\s*(\d{2}:\d{2})-(\d{2}:\d{2})\s*", part)
        if not m or not all(valid_hhmm(x) for x in m.groups()):
            raise ApiError(422, "invalid_request", "ranges must look like 12:00-17:00,21:00-06:00")
        out.append([m.group(1), m.group(2)])
    return out


def valid_hhmm(s) -> bool:
    if not isinstance(s, str) or not re.fullmatch(r"\d{2}:\d{2}", s):
        return False
    h, m = int(s[:2]), int(s[3:])
    return (h < 24 and m < 60) or s == "24:00"


GRID_CELLS_ACROSS = 72          # the dot map draws one dot per cell; about this many along the pack's longer side


def grid_pitch_m(pack: geo.Pack) -> float:
    import math

    lat0, lat1, lon0, lon1 = pack.bbox
    height = (lat1 - lat0) * 111_320.0
    width = (lon1 - lon0) * 111_320.0 * math.cos(math.radians((lat0 + lat1) / 2))
    return max(width, height) / GRID_CELLS_ACROSS


@router.get("/config")
def get_config(user=Depends(current_user)):
    """What the UI needs before a case exists."""
    packs = []
    for d in geo.pack_dirs():
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if (p / "pack.json").exists() and p.name not in [x["id"] for x in packs]:
                    pack = geo.load_pack(p.name)
                    if pack.meta.get("dev_only") and not config.show_dev_packs() and pack.id != config.default_pack():
                        continue
                    packs.append({"id": pack.id, "name": pack.name})
    return {"app": "TRACE", "default_pack": config.default_pack(), "packs": packs,
            "max_upload_mb": config.max_upload_bytes() // (1024 * 1024), "max_duration_h": config.max_duration_s() / 3600,
            "map_tiles": config.map_tiles()}


@router.get("/packs/{pack_id}")
def get_pack(pack_id: str, user=Depends(current_user)):
    pack = load_pack(pack_id)
    if pack_id not in _grid_cache:
        _grid_cache[pack_id] = [list(c) for c in geo.dot_grid(pack, grid_pitch_m(pack))]
    return {"id": pack.id, "name": pack.name, "short_name": pack.short_name, "timezone": pack.timezone, "bbox": list(pack.bbox),
            "regions": pack.geojson, "grid": _grid_cache[pack_id], "grid_pitch_m": grid_pitch_m(pack),
            "labels": pack.meta.get("labels") or {}, "boundaries": pack.meta.get("boundaries"), "demo_case": pack.demo_case}


def day_rows(conn, pack: geo.Pack) -> dict[str, dict]:
    """Every flight day the pack knows of, by UTC date: on disk, being fetched, or failed."""
    from ..core import flights

    out: dict[str, dict] = {}
    folder = config.data_dir() / "flights" / pack.id
    if folder.is_dir():
        for f in folder.glob("*-traces.npz"):
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}-traces\.npz", f.name):
                d = f.name[:10]
                meta = flights.day_meta(config.data_dir(), pack.id, d) or {}
                out[d] = {"utc_date": d, "status": "ready", "n_traces": meta.get("n_traces"), "n_prop": meta.get("n_prop"),
                          "rows_dropped_pct": (meta.get("integrity") or {}).get("rows_dropped_pct"), "progress": None, "error": None}
    for r in db.rows(conn, "SELECT d.utc_date, d.status, d.error, j.status AS job_status, j.stage FROM flight_days d"
                           " LEFT JOIN jobs j ON j.id = d.job_id WHERE d.pack_id = ?", (pack.id,)):
        if r["utc_date"] in out:
            continue                               # the file is there, whatever the table says
        active = r["status"] == "fetching" and r["job_status"] in ("queued", "running")
        status = "fetching" if active else "failed" if r["status"] in ("failed", "fetching") else "missing"
        out[r["utc_date"]] = {"utc_date": r["utc_date"], "status": status, "n_traces": None, "n_prop": None, "rows_dropped_pct": None,
                              "progress": (r["stage"] or "waiting to start") if active else None,
                              "error": (r["error"] or "The fetch stopped before it finished.") if status == "failed" else None}
    return out


@router.get("/packs/{pack_id}/days")
def get_days(pack_id: str, user=Depends(current_user), conn=Depends(get_conn)):
    """Flight days for the pack, newest first. A day is fetched only when a user asks."""
    return sorted(day_rows(conn, load_pack(pack_id)).values(), key=lambda d: d["utc_date"], reverse=True)


class DayRequest(BaseModel):
    utc_date: str


@router.post("/packs/{pack_id}/days")
def fetch_day(pack_id: str, body: DayRequest, request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    """Queue the fetch of one UTC day: about a 4 GB stream from the public archive, several
    minutes. Only ever started by a signed-in user's request, and logged."""
    pack = load_pack(pack_id)
    try:
        day = _dt.date.fromisoformat(body.utc_date)
    except ValueError:
        raise ApiError(422, "invalid_request", "utc_date must be YYYY-MM-DD") from None
    today = _dt.datetime.now(_dt.timezone.utc).date()
    if day >= today or day < _dt.date(2023, 1, 1):
        raise ApiError(422, "day_not_available", "The archive has finished UTC days from 2023 onward. Today's is not published yet.")
    known = day_rows(conn, pack).get(day.isoformat())
    if known and known["status"] in ("ready", "fetching"):
        return known
    rate_limit(conn, user, "flights.fetch", "fetches")
    with conn:
        job_id = db.queue_job(conn, "fetch", None, {"pack_id": pack.id, "utc_date": day.isoformat()})
        conn.execute("INSERT INTO flight_days (pack_id, utc_date, status, job_id) VALUES (?, ?, 'fetching', ?)"
                     " ON CONFLICT (pack_id, utc_date) DO UPDATE SET status = 'fetching', job_id = excluded.job_id, error = NULL",
                     (pack.id, day.isoformat(), job_id))
    audit(conn, request, user, None, "flights.fetch", f"pack={pack.id} utc_date={day.isoformat()} job={job_id}")
    return day_rows(conn, pack)[day.isoformat()]


def latest_state(conn, pack: geo.Pack) -> dict:
    """Where the pack's flight data stands for the header's icon: off, idle, checking,
    fetching (with how far), current, or failed."""
    import json

    on_disk = sorted(d for d, row in day_rows(conn, pack).items() if row["status"] == "ready")
    out = {"pack_id": pack.id, "pack_name": pack.short_name, "status": "idle", "utc_date": None, "newest_on_disk": on_disk[-1] if on_disk else None,
           "fraction": None, "bytes_total": None, "detail": None, "error": None, "checked_at": None}
    if not config.flights_auto() or pack.meta.get("dev_only"):
        return {**out, "status": "off"}
    job = db.one(conn, "SELECT * FROM jobs WHERE kind = 'fetch' AND status IN ('queued', 'running')"
                       " AND json_extract(params, '$.pack_id') = ? ORDER BY created_at LIMIT 1", (pack.id,))
    if job:                                            # any fetch for the pack, asked for by the page or by an analyst
        p = json.loads(job["params"] or "{}")
        return {**out, "status": "fetching" if p.get("utc_date") and job["status"] == "running" else "checking",
                "utc_date": p.get("utc_date"), "fraction": job["progress"], "bytes_total": p.get("bytes_total"),
                "detail": (job["stage"] or "waiting to start") if job["status"] == "running" else "waiting to start"}
    last = last_auto_job(conn, pack)
    if last and last["status"] != "done" and out["newest_on_disk"] != yesterday_utc():
        code, _, message = (last["error"] or "").partition(": ")
        return {**out, "status": "failed", "error": message or code or "The update stopped before it finished.", "checked_at": last["finished_at"]}
    if last or out["newest_on_disk"] == yesterday_utc():
        return {**out, "status": "current", "checked_at": last["finished_at"] if last else None}
    return out


def yesterday_utc() -> str:
    return (_dt.datetime.now(_dt.timezone.utc).date() - _dt.timedelta(days=1)).isoformat()


def last_auto_job(conn, pack: geo.Pack) -> dict | None:
    return db.one(conn, "SELECT * FROM jobs WHERE kind = 'fetch' AND json_extract(params, '$.latest') = 1"
                        " AND json_extract(params, '$.pack_id') = ? ORDER BY created_at DESC, id DESC LIMIT 1", (pack.id,))


@router.get("/packs/{pack_id}/latest")
def get_latest(pack_id: str, user=Depends(current_user), conn=Depends(get_conn)):
    return latest_state(conn, load_pack(pack_id))


class LatestRequest(BaseModel):
    force: bool = False


@router.post("/packs/{pack_id}/latest")
def update_latest(pack_id: str, request: Request, body: LatestRequest | None = None, user=Depends(current_user), conn=Depends(get_conn)):
    """Bring the pack's flight data up to the newest published day, in the background. The
    page calls this once someone is signed in. It queues at most one job: nothing while a
    fetch is running, nothing when yesterday is already on disk, and otherwise one look at
    the archive per hour unless `force` (the icon's "Try again"). Logged."""
    pack = load_pack(pack_id)
    state = latest_state(conn, pack)
    force = bool(body and body.force)
    if state["status"] in ("off", "checking", "fetching") or state["newest_on_disk"] == yesterday_utc():
        return state
    last = last_auto_job(conn, pack)
    if last and not force:
        age = (_dt.datetime.now(_dt.timezone.utc) - _dt.datetime.fromisoformat(last["created_at"].replace("Z", "+00:00"))).total_seconds()
        if age < config.flights_auto_retry_s():
            return state
    if force:
        rate_limit(conn, user, "flights.fetch", "fetches")
    with conn:
        job_id = db.queue_job(conn, "fetch", None, {"pack_id": pack.id, "latest": True})
    audit(conn, request, user, None, "flights.fetch" if force else "flights.update", f"pack={pack.id} newest day job={job_id}")
    return latest_state(conn, pack)


@router.get("/flights/count")
async def flight_count(request: Request, pack: str, date: str, ranges: str | None = None, regions: str | None = None,
                       user=Depends(current_user), conn=Depends(get_conn)):
    """For the live counter: aircraft in the time window and area. Runs in the fit pool,
    because it loads a day of traces."""
    p = load_pack(pack)
    try:
        _dt.date.fromisoformat(date)
    except ValueError:
        raise ApiError(422, "invalid_request", "date must be YYYY-MM-DD") from None
    region_ids = [r for r in (regions or "").split(",") if r] or None
    if region_ids and not all(any(r.id == rid for r in p.regions) for rid in region_ids):
        raise ApiError(422, "invalid_request", "unknown region")
    out = await request.app.state.fitpool.count(p.id, date, parse_ranges(ranges), region_ids)
    known = day_rows(conn, p)                      # what the table adds: a day being fetched, or one that failed
    out["days"] = [{**d, **{k: known[d["utc_date"]][k] for k in ("status", "progress", "error")}} if d["utc_date"] in known
                   else {**d, "progress": None, "error": None} for d in out["days"]]
    return out
