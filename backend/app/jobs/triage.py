"""Triage: decode, spectrogram, then flyover proposals in slices.

The spectrogram comes first and is announced at once, so the analyst can start drawing
boxes; proposals follow slice by slice. Detection is a hint, never a confirmation."""
from __future__ import annotations

import json

from .. import config, db
from ..core import events, geo, media, spectro, weather
from ..models import event_public
from .runner import JobError


def run(conn, job: dict) -> None:
    case_id, job_id = job["case_id"], job["id"]
    case = db.one(conn, "SELECT * FROM cases WHERE id = ?", (case_id,))
    m = db.one(conn, "SELECT * FROM media WHERE case_id = ?", (case_id,))
    if not case or not m:
        raise JobError("no_media", "the case has no recording")
    case_dir = config.case_dir(case_id)

    def emit(type_, payload):
        db.emit(conn, job_id, case_id, type_, payload)

    db.set_stage(conn, job_id, "decoding")
    emit("triage", {"state": "decoding"})
    try:
        x, sr = media.decode_audio(m["path"])
    except media.MediaError as e:
        raise JobError(e.code, str(e)) from e
    sp = spectro.build(x, sr, case_dir)
    del x
    total = float(sp.t[-1]) if len(sp.t) else 0.0
    with conn:
        conn.execute("UPDATE media SET spectrogram_path = ? WHERE id = ?", (str(case_dir), m["id"]))
        conn.execute("UPDATE cases SET status = 'triaged' WHERE id = ? AND status = 'draft'", (case_id,))
    db.set_stage(conn, job_id, "detecting", 0.0)
    emit("triage", {"state": "spectrogram_ready", "total_s": total})

    pack = geo.load_pack(case["pack_id"])
    temp, _ = weather.for_case(pack, case["date_local"], json.loads(case["time_ranges"]) if case["time_ranges"] else None,
                               case["temperature_c"], case["temperature_source"])
    c = weather.speed_of_sound(temp)
    ids: dict[int, str] = {}                      # id(EventFit) -> events.id, for the ones this job inserted

    def on_slice(done_s, total_s, added, removed):
        sent, gone = [], []
        with conn:
            for ev in removed:
                eid = ids.pop(id(ev), None)
                # only rows nobody has touched may go
                if eid and conn.execute("DELETE FROM events WHERE id = ? AND source = 'detect' AND status = 'proposed'", (eid,)).rowcount:
                    gone.append(eid)
            touched = [r["fit"] for r in conn.execute(
                "SELECT fit FROM events WHERE case_id = ? AND NOT (source = 'detect' AND status = 'proposed')", (case_id,))]
            taken = [json.loads(f)["t_cpa"] for f in touched if f]
            for ev in added:
                if any(abs(ev.t_cpa - t) < events.MERGE_S for t in taken):
                    continue                       # the analyst already has a box here
                t0, t1, lo, hi = events.proposal_box(ev, c, sp)
                if t1 - t0 < events.MIN_BOX_S or hi - lo < events.MIN_BOX_HZ:
                    continue                       # too close to the end of the recording to fit
                eid = db.ulid()
                ids[id(ev)] = eid
                conn.execute(
                    "INSERT INTO events (id, case_id, source, status, t_start, t_end, f_lo, f_hi, harmonics, fit, curve, fit_temperature_c, score, burst, created_at)"
                    " VALUES (?, ?, 'detect', 'proposed', ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)",
                    (eid, case_id, t0, t1, lo, hi, json.dumps(ev.to_dict()), json.dumps(events.curve_points(ev, c, t0=t0, t1=t1)),
                     temp, float(ev.score), float(ev.burst), db.now()))
                sent.append(eid)
        rows = [event_public(db.one(conn, "SELECT * FROM events WHERE id = ?", (e,))) for e in sent]
        n = conn.execute("SELECT COUNT(*) FROM events WHERE case_id = ? AND source = 'detect' AND status = 'proposed'", (case_id,)).fetchone()[0]
        db.set_stage(conn, job_id, "detecting", done_s / total_s if total_s else 1.0)
        emit("proposals", {"events": rows, "removed": gone, "done_s": done_s, "total_s": total_s})
        emit("triage", {"state": "detecting", "done_s": done_s, "total_s": total_s, "events": n})

    events.propose(sp, c, preset=config.detect_preset(), workers=config.triage_workers(),
                   burst=spectro.load_burst(case_dir), on_slice=on_slice)
    n = conn.execute("SELECT COUNT(*) FROM events WHERE case_id = ? AND source = 'detect' AND status = 'proposed'", (case_id,)).fetchone()[0]
    emit("triage", {"state": "done", "done_s": total, "total_s": total, "events": n})
