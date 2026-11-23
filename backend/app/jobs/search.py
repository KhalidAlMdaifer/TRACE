"""The search job: refit every confirmed box in full, search the whole pack, store the result."""
from __future__ import annotations

import json

from .. import config, db
from ..core import geo, search, spectro
from .runner import JobError


def run(conn, job: dict) -> None:
    case_id, job_id = job["case_id"], job["id"]
    case = db.one(conn, "SELECT * FROM cases WHERE id = ?", (case_id,))
    m = db.one(conn, "SELECT * FROM media WHERE case_id = ?", (case_id,))
    case_dir = config.case_dir(case_id)
    if not case or not m or not spectro.exists(case_dir):
        raise JobError("spectrogram_not_ready", "the recording has not been analysed yet")
    with conn:
        conn.execute("UPDATE cases SET status = 'searching' WHERE id = ?", (case_id,))

    def emit(type_, payload):
        db.emit(conn, job_id, case_id, type_, payload)

    def progress(kind, payload):
        # job_id on every event: the page replays the latest job's events when it opens, and
        # must be able to tell one search of a case from the next
        if kind == "stage":
            if payload["state"] == "start":
                db.set_stage(conn, job_id, payload["stage"])
            emit("stage", {"job": "search", "job_id": job_id, **payload})
        elif kind in ("progress", "cells"):
            emit(kind, {"job_id": job_id, **payload})

    js = lambda v: json.loads(v) if v else None
    inputs = search.CaseInputs(
        pack=geo.load_pack(case["pack_id"]), date_local=case["date_local"], duration_s=float(m["duration_s"] or spectro.duration_s(case_dir)),
        time_ranges=js(case["time_ranges"]), region_ids=js(case["region_ids"]), custom_bbox=js(case["custom_bbox"]),
        temperature_c=case["temperature_c"], temperature_source=case["temperature_source"], file_sha256=m["sha256"])
    boxes = [search.Box(id=r["id"], t_start=r["t_start"], t_end=r["t_end"], f_lo=r["f_lo"], f_hi=r["f_hi"], harmonics=r["harmonics"])
             for r in db.rows(conn, "SELECT * FROM events WHERE case_id = ? AND status = 'confirmed' ORDER BY t_start", (case_id,))]
    sp = spectro.load(case_dir)
    try:
        result = search.run(inputs, sp, boxes, data_dir=config.data_dir(), types=config.aircraft_types(),
                            workers=config.doppler_workers(), burst=spectro.load_burst(case_dir), progress=progress)
    except ValueError as e:                      # a box the library cannot fit
        raise JobError(getattr(e, "code", "fit_failed"), str(e)) from e
    result["case"] = {"id": case_id, "case_ref": case["case_ref"], "filename": m["filename"]}

    result_id = db.ulid()
    rdir = config.results_dir(case_id)
    rdir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(result)
    (rdir / f"{result_id}.json").write_text(text)
    est, v = result.get("estimate") or {}, result.get("verdict") or {}
    with conn:
        conn.execute(
            "INSERT INTO results (id, case_id, job_id, state, verdict, p, strength, band, lat, lon, radius_m, payload, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (result_id, case_id, job_id, result["state"], v.get("label"), v.get("p"), result.get("strength"), result.get("band"),
             est.get("lat"), est.get("lon"), est.get("radius_m"), text, db.now()))
        conn.execute("UPDATE cases SET status = 'done' WHERE id = ?", (case_id,))
    emit("done", {"job_id": job_id, "result_id": result_id, "state": result["state"]})
