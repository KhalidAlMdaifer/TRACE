"""Fetch one UTC day of flight data for a pack: a 4 GB stream, minutes long.

Queued by `POST /api/packs/{pack}/days` (the analyst asks for a day) and by
`POST /api/packs/{pack}/latest` (the page asks for the newest published day once someone is
signed in; `latest` in the params, and the job finds which day that is). The search never
fetches on its own."""
from __future__ import annotations

import json

from .. import config, db
from ..core import flights, geo
from .runner import JobError


def run(conn, job: dict) -> None:
    p = json.loads(job["params"] or "{}")
    if not p.get("pack_id") or not (p.get("utc_date") or p.get("latest")):
        raise JobError("bad_params", "a fetch job needs pack_id and utc_date")
    pack = geo.load_pack(p["pack_id"])
    total = None
    if p.get("latest"):
        # which day is the newest one published, and how big: a small request, no stream yet
        import datetime as _dt

        db.set_stage(conn, job["id"], "checking the archive")
        try:
            found = flights.latest_published(_dt.datetime.now(_dt.timezone.utc).date())
        except Exception as e:
            raise JobError("archive_unreachable", "The flight archive could not be reached.") from e
        if not found:
            raise JobError("not_published", "The flight archive has no day from the last four.")
        p["utc_date"], total = found
        p["bytes_total"] = total
        with conn:                                     # the api reads the day and the size from here
            conn.execute("UPDATE jobs SET params = ? WHERE id = ?", (json.dumps(p), job["id"]))
        if flights.traces_path(config.data_dir(), pack.id, p["utc_date"]).exists():
            db.set_stage(conn, job["id"], f"up to date: {p['utc_date']} is the newest day published")
            return
    day = p["utc_date"]

    def mark(status, **cols):
        sets = ", ".join(f"{k} = ?" for k in ("status", *cols))
        with conn:
            conn.execute("INSERT OR IGNORE INTO flight_days (pack_id, utc_date, status) VALUES (?, ?, ?)", (pack.id, day, status))
            conn.execute(f"UPDATE flight_days SET {sets} WHERE pack_id = ? AND utc_date = ?", (status, *cols.values(), pack.id, day))

    def progress(n_files, n_bytes):
        if total:
            db.set_stage(conn, job["id"], f"{n_bytes / 1e9:.2f} of {total / 1e9:.2f} GB read, {n_files:,} aircraft files",
                         progress=round(min(1.0, n_bytes / total), 4))
        else:
            db.set_stage(conn, job["id"], f"{n_bytes / 1e9:.2f} GB read, {n_files:,} aircraft files")

    mark("fetching", job_id=job["id"], error=None)
    db.set_stage(conn, job["id"], "starting the stream")
    try:
        path, meta = flights.ensure_day(pack, day, config.data_dir(), progress=progress, types=config.aircraft_types())
    except Exception as e:
        text = str(e)
        # the commonest failure: the day's archive is not published (yet)
        message = "No flight archive is published for that day." if "404" in text else f"The flight archive could not be read: {text[:200]}"
        mark("failed", error=message)
        raise JobError("fetch_failed", message) from e
    meta = meta or {}
    integ = meta.get("integrity") or {}
    mark("ready", n_traces=meta.get("n_traces"), n_prop=meta.get("n_prop"), rows_dropped_pct=integ.get("rows_dropped_pct"),
         traces_path=str(path), source_tag=meta.get("source"), fetched_at=meta.get("fetched_at"), stats=json.dumps(integ) if integ else None)
    db.emit(conn, job["id"], job["case_id"], "done", {"job": "fetch", "job_id": job["id"], "pack_id": pack.id, "utc_date": day})
