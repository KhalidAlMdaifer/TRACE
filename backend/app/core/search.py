"""The search orchestration (docs/05-architecture.md, section 6): confirmed boxes in, a
result with a state and a verdict out.

`compute` is the heavy part (full fits, the index, dopplertrack's search) and knows nothing
about the analyst's area or time. `conclude` applies those constraints, the confidence rules
and the fine refine. So a change of constraints never repeats the search, and the verdict is
always judged against the whole pack.

One search per OS process: dopplertrack keeps search state in a module global."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .. import config
from . import confidence, events, flights, geo, weather

MAX_CANDIDATES = 5
MAX_CELLS = 2000
SILENCE_M = 6000.0
SILENCE_MAX_GAP_S = 20 * 60.0
REFINE_SPACING_M, REFINE_HALF_M = 50.0, 600.0
LATTICE_M = 200.0

ADVICE = {
    "fewer_than_two_flyovers": (
        ["Flyovers confirmed by the analyst"],
        ["Mark at least two propeller flyovers: look for a tone that falls in pitch over a minute or two.",
         "A longer, uncut recording gives more flyovers; three or more can confirm a place."]),
    "no_flights": (
        ["Flyovers confirmed by the analyst", "Flight archive for the recording date"],
        ["No propeller flights are on file for that date and area. Check the date.",
         "The flight day may not be loaded yet, or the area may have no propeller traffic in the public archive."]),
    "no_candidates": (
        ["Flyovers confirmed by the analyst", "Flight archive for the recording date", "Every flight pair that day against the two strongest flyovers"],
        ["No place fits both flyovers. Check the date and the air temperature.",
         "Redraw each box around the bend of its curve; a vehicle or a steady tone can look like a flyover.",
         "A cut between the flyovers puts them on different clocks: use the uncut original."]),
}


@dataclass
class Box:
    """A confirmed flyover as the analyst drew it: seconds and Hz."""
    id: str
    t_start: float
    t_end: float
    f_lo: float
    f_hi: float
    harmonics: int = 1


@dataclass
class CaseInputs:
    pack: geo.Pack
    date_local: str
    duration_s: float
    time_ranges: list | None = None          # [["12:00", "17:00"]] local; None is the whole day
    region_ids: list | None = None           # None is the whole pack
    custom_bbox: list | None = None          # [lat_min, lat_max, lon_min, lon_max]
    temperature_c: float | None = None       # None: the pack's monthly figure
    temperature_source: str | None = None
    file_sha256: str | None = None
    rows_dropped_pct: float | None = None


@dataclass
class Raw:
    """Everything `compute` found, before the analyst's constraints are applied."""
    n_confirmed: int
    temperature_c: float | None = None
    temperature_source: str | None = None
    c: float | None = None
    fits: list = field(default_factory=list)          # FittedEvent per box, in box order
    ev1: events.FittedEvent | None = None
    ev2: events.FittedEvent | None = None
    extras: list = field(default_factory=list)
    idx: object = None
    types_by_icao: dict = field(default_factory=dict)
    res: object = None                                # dopplertrack's result rows, best first
    days: list = field(default_factory=list)
    days_missing: list = field(default_factory=list)
    n_flights: int = 0
    silence_d_m: float | None = None
    rows_dropped_pct: float | None = None             # by the integrity filter, over the days searched; None: not measured
    temperature_runs: list = field(default_factory=list)   # when searched at two temperatures: [{c, score, pair}]
    temperature_window: dict | None = None            # the archive's figures over the time window, when automatic
    placebo: list | None = None                       # the control: [{utc_date, best_score, n_pairs}], or None when not run
    elevation: object = None
    reason: str | None = None                         # set when there is nothing to conclude from
    progress_log: list = field(default_factory=list)


def _iso(t_unix: float) -> str:
    return datetime.fromtimestamp(float(t_unix), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log_to_progress(emit, cand_cache=None):
    """dopplertrack reports through log lines; turn the ones that mark a stage into events.
    Once the lattice is laid the library saves it to `cand_cache`; on the next line we read it
    back and send the points, so the map can show where the search is looking while it scores."""
    state = {"stage": None, "sent_points": False}

    def start(stage, detail=None):
        if state["stage"] and state["stage"] != stage:
            emit("stage", {"stage": state["stage"], "state": "done"})
        if state["stage"] != stage:
            state["stage"] = stage
            emit("stage", {"stage": stage, "state": "start", **({"detail": detail} if detail else {})})

    def send_points():
        if state["sent_points"] or not cand_cache or not Path(cand_cache).exists():
            return
        state["sent_points"] = True
        try:
            z = np.load(cand_cache, allow_pickle=False)
            lat, lon = z["lat"], z["lon"]
        except Exception:
            return
        step = max(1, len(lat) // MAX_CELLS)
        emit("cells", {"scored": False, "points": [[round(float(a), 5), round(float(b), 5), None] for a, b in zip(lat[::step], lon[::step])]})

    def log(msg: str):
        m = msg.strip()
        if m.startswith("join:"):
            start("join")
        elif "flight pairs pass the join" in m:
            start("join"); emit("stage", {"stage": "join", "state": "done", "detail": f"{int(m.split()[0]):,} pairs"}); state["stage"] = None
        elif m.startswith("lens:"):
            start("lattice")
        elif "candidate (point, flight) rows" in m:
            start("lattice"); emit("stage", {"stage": "lattice", "state": "done", "detail": f"{int(m.split()[0]):,} points"}); state["stage"] = None
            start("scoring")
        elif m.startswith("scored") and "/" in m.split()[1]:
            send_points()
            done, total = m.split()[1].split("/")
            start("scoring"); emit("progress", {"stage": "scoring", "done": int(done), "total": int(total)})
        elif m.startswith("scored"):
            send_points()
            start("scoring"); emit("stage", {"stage": "scoring", "state": "done", "detail": f"{int(m.split()[1]):,} points"}); state["stage"] = None

    return log


def compute(case: CaseInputs, sp, boxes: list[Box], data_dir=None, types=None, workers: int | None = None,
            burst=None, progress=None, fetch_missing: bool = False, temperature: tuple[float, str] | None = None) -> Raw:
    """Steps 1 to 7: temperature, full fits, flight days, index, search, extras. `temperature`
    (C, source) overrides the case's own, for the second run of a two-temperature search."""
    from dopplertrack.doppler import speed_of_sound
    from dopplertrack.search import rescore_with_extra, run_search

    data_dir = Path(data_dir) if data_dir is not None else config.data_dir()
    workers = workers or config.doppler_workers()
    raw = Raw(n_confirmed=len(boxes))

    def emit(kind, payload):
        raw.progress_log.append((kind, payload))
        if progress:
            progress(kind, payload)

    if len(boxes) < 2:
        raw.reason = "fewer_than_two_flyovers"
        return raw

    # 1. temperature: the analyst's, else the archive's for that date and window, else the pack's monthly figure
    raw.temperature_c, raw.temperature_source = temperature or weather.for_case(
        case.pack, case.date_local, case.time_ranges, case.temperature_c, case.temperature_source, data_dir)
    raw.c = c = float(speed_of_sound(raw.temperature_c))

    # flight days first, quietly: with no flights there is nothing to fit for
    days = flights.utc_days_for(case.date_local, case.pack.timezone)
    if fetch_missing:
        for d in days:
            flights.ensure_day(case.pack, d, data_dir, types=types)
    ready = flights.days_ready(data_dir, case.pack.id, days)
    raw.days = [d.isoformat() for d in ready]
    raw.days_missing = [d.isoformat() for d in days if d not in ready]
    raw.rows_dropped_pct = flights.dropped_pct(data_dir, case.pack.id, ready)
    traces = flights.load_window(case.pack, days, data_dir, prop_only=True, types=types)
    raw.n_flights = len(traces)
    if not traces:
        raw.reason = "no_flights"
        return raw

    # 2. the full fit of every confirmed box at this temperature; the editor's previews are not used
    emit("stage", {"stage": "fits", "state": "start", "detail": f"{len(boxes)} flyovers"})
    fitted = events.fit_many(sp, [(b.t_start, b.t_end, b.f_lo, b.f_hi, b.harmonics) for b in boxes], c, burst=burst, workers=workers,
                             on_done=lambda n, total: emit("progress", {"stage": "fits", "done": n, "total": total}))
    for b, ev in zip(boxes, fitted):
        h = events.effective_harmonics(sp, min(b.f_hi, float(sp.f[-1])), b.harmonics)
        raw.fits.append(events.FittedEvent(b.id, (b.t_start, b.t_end, b.f_lo, b.f_hi), h, ev))
    raw.ev1, raw.ev2, raw.extras = events.pick_pair(raw.fits)
    emit("stage", {"stage": "fits", "state": "done", "detail": f"{len(boxes)} of {len(boxes)}"})

    # 3, 4. the index, in a frame at the pack centre
    emit("stage", {"stage": "flights", "state": "start"})
    raw.idx = idx = flights.build_index(traces, case.pack)
    raw.types_by_icao = {t.icao: t.typ for t in traces}
    emit("stage", {"stage": "flights", "state": "done", "detail": f"{len(traces):,} propeller"})
    if not len(idx):
        raw.reason = "no_flights"
        return raw

    # 5. the silence filter can veto the truth when an unmarked pass sits between the two
    # events, so use it only when they are close together and nothing confirmed lies between
    t1, t2 = raw.ev1.t_cpa, raw.ev2.t_cpa
    between = any(t1 < e.t_cpa < t2 for e in raw.extras)
    raw.silence_d_m = SILENCE_M if (t2 - t1) < SILENCE_MAX_GAP_S and not between else None

    # 6. the whole pack, no bbox: a narrow search leaves too few wrong pairs for the verdict
    if case.pack.terrain_zoom:
        from dopplertrack.terrain import Terrain
        config.use_dopplertrack_cache(data_dir)
        raw.elevation = Terrain(zoom=int(case.pack.terrain_zoom)).elevation
    import tempfile

    with tempfile.TemporaryDirectory(prefix="trace-cands-") as tmp:
        cache = str(Path(tmp) / "cands.npz")
        res = run_search(sp, raw.ev1.fit, raw.ev2.fit, idx, harmonics=(raw.ev1.harmonics, raw.ev2.harmonics), c=c,
                         elevation=raw.elevation, silence_d_m=raw.silence_d_m, workers=workers, cand_cache=cache,
                         log=_log_to_progress(emit, cache))
    if not len(res):
        emit("stage", {"stage": "scoring", "state": "done", "detail": "no place fits"})
        raw.reason = "no_candidates"
        return raw
    top = res.sort_values("score", ascending=False).head(MAX_CELLS)
    emit("cells", {"scored": True, "points": [[round(float(a), 5), round(float(b), 5), round(float(sc), 2)] for a, b, sc in zip(top.lat, top.lon, top.score)]})

    # 7. further flyovers, each on the same clock as the pair
    if raw.extras:
        emit("stage", {"stage": "extras", "state": "start", "detail": f"{len(raw.extras)} further flyover{'s' if len(raw.extras) != 1 else ''}"})
        res = rescore_with_extra(sp, raw.ev1.fit, [e.fit for e in raw.extras], idx, res, extra_harmonics=[e.harmonics for e in raw.extras],
                                 c=c, workers=workers, log=lambda m: None)
        emit("stage", {"stage": "extras", "state": "done", "detail": f"{len(raw.extras)} flyover{'s' if len(raw.extras) != 1 else ''}"})
    raw.res = res
    return raw


def _sharpness(fine, floor_m: float = 50.0) -> float:
    """The largest distance from the peak among fine-grid cells scoring at least 95% of the
    peak. A starting rule for the uncertainty radius."""
    from dopplertrack.geo import haversine_m

    peak = fine.iloc[0]
    near = fine[fine.score >= 0.95 * float(peak.score)]
    d = haversine_m(near.lat.to_numpy(), near.lon.to_numpy(), float(peak.lat), float(peak.lon))
    return float(max(floor_m, np.max(d))) if len(near) else floor_m


PATH_HALF_S, PATH_STEP_S = 180.0, 3          # how much of a matched flight's track the map gets


def _path(raw: Raw, seg, lat: float, lon: float, elev: float, t_about: float | None) -> dict | None:
    """A matched flight's track around its closest approach to a point, for the map."""
    from dopplertrack.geo import enu_to_lla, lla_to_enu

    if seg is None or not len(seg.t):
        return None
    obs = lla_to_enu(lat, lon, elev, raw.idx.lat0, raw.idx.lon0)
    d = np.linalg.norm(seg.enu - obs, axis=1)
    if t_about is not None:                          # the pass nearest in time, not another visit of the same aircraft
        near = np.abs(seg.t - t_about) <= 600.0
        d = np.where(near, d, np.inf) if near.any() else d
    j = int(np.argmin(d))
    m = np.abs(seg.t - seg.t[j]) <= PATH_HALF_S
    enu = seg.enu[m][::PATH_STEP_S]
    la, lo, _ = enu_to_lla(enu[:, 0], enu[:, 1], enu[:, 2], raw.idx.lat0, raw.idx.lon0)
    cla, clo, calt = enu_to_lla(seg.enu[j, 0], seg.enu[j, 1], seg.enu[j, 2], raw.idx.lat0, raw.idx.lon0)
    return {"points": [[round(float(a), 5), round(float(b), 5)] for a, b in zip(la, lo)], "cpa": [round(float(cla), 5), round(float(clo), 5)],
            "cpa_alt_m": round(float(calt)), "cpa_unix": float(seg.t[j])}


def _segment_for(raw: Raw, icao: str, lat: float, lon: float, t_about: float):
    """The airborne stretch of an aircraft that is closest to a point around a time."""
    from dopplertrack.geo import lla_to_enu

    obs = lla_to_enu(lat, lon, 0.0, raw.idx.lat0, raw.idx.lon0)
    best, best_d = None, np.inf
    for seg in raw.idx.segs:
        if seg.icao != icao:
            continue
        near = np.abs(seg.t - t_about) <= 600.0
        if near.any():
            d = float(np.min(np.linalg.norm(seg.enu[near] - obs, axis=1)))
            if d < best_d:
                best, best_d = seg, d
    return best


def _extra_matches(row, n_extras: int) -> list[str]:
    """The flight matched to each extra flyover at this row's point; "" where none was."""
    return [str(row.get(f"x_icao{k + 1}", "") or "") for k in range(n_extras)]


def _refine(case, sp, raw: Raw, row) -> dict:
    """The 50 m grid around one pair's best lattice point, with the extras that matched."""
    from dopplertrack import pipeline

    lattice = {"lat": float(row.lat), "lon": float(row.lon)}
    matched = [e for e, icao in zip(raw.extras, _extra_matches(row, len(raw.extras))) if icao]
    try:
        fine = pipeline.refine(sp, raw.ev1.fit, raw.ev2.fit, raw.idx, row, spacing_m=REFINE_SPACING_M, half_m=REFINE_HALF_M,
                               harmonics=(raw.ev1.harmonics, raw.ev2.harmonics), elevation=raw.elevation, c=raw.c,
                               extra=[e.fit for e in matched], extra_harmonics=[e.harmonics for e in matched], log=lambda m: None)
        best = fine.iloc[0]
        strong = fine[fine.score >= 0.6 * float(best.score)].head(800)
        point = {"lat": float(best.lat), "lon": float(best.lon), "radius_m": round(_sharpness(fine)), "refined": True,
                 "score": round(float(best.score), 2), "cell_m": REFINE_SPACING_M,
                 "cells": [[round(float(a), 5), round(float(b), 5), round(float(sc), 2)] for a, b, sc in zip(strong.lat, strong.lon, strong.score)]}
    except ValueError:                       # no flight near the point for an extra after all: keep the lattice point
        point = {**lattice, "radius_m": LATTICE_M, "refined": False, "score": round(float(row.score), 2), "cell_m": LATTICE_M, "cells": []}
    el = float(raw.elevation(np.array([point["lat"]]), np.array([point["lon"]]))[0]) if raw.elevation else None
    return {**point, "elev_m": None if el is None else round(max(el, 0.0)), "lattice": lattice,
            "regions": geo.regions_at(case.pack, point["lat"], point["lon"])}


def _event_rows(raw: Raw, row, clip_start: float, at: tuple[float, float] | None = None) -> list[dict]:
    """What each flyover matched at this pair's best point, with the search's own fit. `at` is
    the point the flight paths are drawn against (the refined estimate, when there is one)."""
    out = []
    plat, plon = at if at else (float(row.lat), float(row.lon))
    segs = raw.idx.segs
    matches = _extra_matches(row, len(raw.extras))
    pair = [(raw.ev1, "pair", str(row.icao1), float(row.d1), float(row.v1), float(row.s1)),
            (raw.ev2, "pair", str(row.icao2), float(row.d2), float(row.v2), float(row.s2))]
    extras = [(e, "extra", icao or None, None, None, float(row.get(f"s{k + 3}", 0.0))) for k, (e, icao) in enumerate(zip(raw.extras, matches))]
    for k, (fe, role, icao, slant, speed, score) in enumerate(pair + extras):
        ev = fe.fit
        t_about = clip_start + ev.t_cpa
        seg = segs[int(row.seg1)] if k == 0 else segs[int(row.seg2)] if k == 1 else (_segment_for(raw, icao, plat, plon, t_about) if icao else None)
        out.append({
            "path": _path(raw, seg, plat, plon, 0.0, t_about),
            "id": fe.box_id, "role": role, "matched": icao is not None, "icao": icao, "type": raw.types_by_icao.get(icao) if icao else None,
            "t_cpa": round(ev.t_cpa, 2), "f0": round(ev.f0, 2), "harmonics": fe.harmonics, "burst": round(float(ev.burst), 3),
            "cpa_time_utc": _iso(clip_start + ev.t_cpa),
            "slant_m": round(slant if slant is not None else ev.d), "speed_mps": round(speed if speed is not None else ev.v, 1),
            "score": round(score, 2), "fit": {"v": round(ev.v, 1), "d": round(ev.d), "score": round(ev.score, 2)},
            "box": list(fe.box), "curve": events.curve_points(ev, raw.c), "curve_kind": "fit",
        })
    return out


def _dropped(case: CaseInputs, raw: Raw) -> float | None:
    return case.rows_dropped_pct if case.rows_dropped_pct is not None else raw.rows_dropped_pct


def _inputs(case: CaseInputs, raw: Raw) -> dict:
    return {"file_sha256": case.file_sha256, "pack": case.pack.id, "date_local": str(case.date_local) if case.date_local else None, "duration_s": case.duration_s,
            "region_names": {r.id: r.name for r in case.pack.regions},
            "temperature_c": raw.temperature_c, "temperature_source": raw.temperature_source,
            "dopplertrack": config.DOPPLERTRACK_COMMIT[:7], "flight_days": raw.days, "flight_days_missing": raw.days_missing,
            "n_flights": raw.n_flights, "rows_dropped_pct": _dropped(case, raw), "n_flyovers": raw.n_confirmed,
            "temperature_runs": raw.temperature_runs or None, "temperature_window": raw.temperature_window,
            "params": {"silence_d_m": raw.silence_d_m, "v_tol": 0.35, "d_tol": [0.4, 2.5], "lattice_m": LATTICE_M,
                       "refine_m": REFINE_SPACING_M}}


def conclude(case: CaseInputs, sp, raw: Raw) -> dict:
    """Steps 8 to 11: constraints per pair, the assessment, the refine, and the result JSON
    (docs/05-architecture.md, section 7)."""
    from dopplertrack.verdict import best_per_pair, verdict

    out = {"state": None, "sublabel": None, "verdict": None, "strength": None, "band": None, "caps": [], "estimate": None,
           "clip_start_utc": None, "clip_start_unix": None, "events": [], "candidates": [], "cells": [],
           "constraints": {"regions": case.region_ids, "custom_bbox": case.custom_bbox, "time_ranges": case.time_ranges, "outside_match": None},
           "controls": {"placebo_days": None}, "inputs": _inputs(case, raw), "not_locatable": None}

    if raw.reason or raw.res is None:
        a = confidence.assess(None, None, raw.n_confirmed, reason=raw.reason)
        checked, advice = ADVICE[a.reason]
        out.update(state=a.state, band=a.band, not_locatable={"reason": a.reason, "checked": checked, "advice": advice})
        return out

    # 8. one row per flight pair, with the clip start it implies and the constraint flags
    pairs = best_per_pair(raw.res)
    ev1 = raw.ev1.fit
    pairs["clip_start"] = pairs.t_heard1 - ev1.t_cpa - pairs["shift"]
    pairs["in_area"] = geo.in_area(case.pack, case.region_ids, case.custom_bbox, pairs.lat.to_numpy(), pairs.lon.to_numpy())
    windows = flights.local_ranges_unix(case.date_local, case.pack.timezone, case.time_ranges)
    start, end = pairs.clip_start.to_numpy(), pairs.clip_start.to_numpy() + case.duration_s
    pairs["in_time"] = np.any([(start < b) & (end > a) for a, b in windows], axis=0)
    n_x = len(raw.extras)
    pairs["n_events"] = [2 + sum(bool(m) for m in _extra_matches(r, n_x)) for _, r in pairs.iterrows()]

    # 9. the verdict is judged on the whole pack; our rules sit on top of it
    v = verdict(raw.res)
    top_score = float(pairs.score.iloc[0])
    beaten_by = [p for p in (raw.placebo or []) if p["best_score"] >= top_score]
    disagree = len(raw.temperature_runs) == 2 and raw.temperature_runs[0]["pair"] != raw.temperature_runs[1]["pair"]
    a = confidence.assess(pairs, v, raw.n_confirmed, bursts=[f.fit.burst for f in raw.fits], rows_dropped_pct=_dropped(case, raw),
                          temperature_disagree=disagree, placebo_beaten=len(beaten_by) if raw.placebo else None)
    if raw.placebo is not None:
        out["controls"]["placebo_days"] = raw.placebo
        out["controls"]["placebo_beaten_by"] = len(beaten_by)
    nan = lambda x: None if x != x else round(float(x), 4)
    out.update(state=a.state, sublabel=a.sublabel, strength=a.strength, band=a.band, caps=a.caps,
               verdict={"label": v.verdict, "p": nan(v.p), "gap": nan(v.gap), "tail_width": nan(v.tail_width),
                        "n_pairs": int(v.n_pairs), "n_null": int(v.n_null)})

    def candidate(i: int, rank: int) -> dict:
        r = pairs.iloc[i]
        t1, t2 = float(r.clip_start) + raw.ev1.t_cpa, float(r.clip_start) + raw.ev2.t_cpa
        return {"rank": rank, "lat": float(r.lat), "lon": float(r.lon), "score": round(float(r.score), 2),
                "icao": [str(r.icao1), str(r.icao2)], "types": [raw.types_by_icao.get(str(r.icao1)), raw.types_by_icao.get(str(r.icao2))],
                "in_area": bool(r.in_area), "in_time": bool(r.in_time), "n_events": int(r.n_events),
                "regions": geo.regions_at(case.pack, float(r.lat), float(r.lon)),
                "clip_start_utc": _iso(r.clip_start), "radius_m": LATTICE_M,
                "paths": [p for p in (_path(raw, raw.idx.segs[int(r.seg1)], float(r.lat), float(r.lon), 0.0, t1),
                                      _path(raw, raw.idx.segs[int(r.seg2)], float(r.lat), float(r.lon), 0.0, t2)) if p]}

    # 10. refine the pair the result is about (the best one inside the constraints, if any)
    shown = a.top_in if a.top_in is not None else None
    if shown is not None:
        row = pairs.iloc[shown]
        out["estimate"] = _refine(case, sp, raw, row)
        out["clip_start_unix"] = float(row.clip_start)
        out["clip_start_utc"] = _iso(row.clip_start)
        out["events"] = _event_rows(raw, row, float(row.clip_start), (out["estimate"]["lat"], out["estimate"]["lon"]))
    else:                                    # nothing inside the constraints: describe the flyovers without a match
        out["events"] = [{"id": f.box_id, "role": "unmatched", "matched": False, "icao": None, "t_cpa": round(f.fit.t_cpa, 2),
                          "f0": round(f.fit.f0, 2), "harmonics": f.harmonics, "burst": round(float(f.fit.burst), 3), "box": list(f.box),
                          "curve": events.curve_points(f.fit, raw.c), "curve_kind": "fit"} for f in raw.fits]

    # up to five places, best first, whatever the constraints say: one outside the stated area
    # or time is flagged, not hidden. The one the estimate was refined for carries the refined point.
    out["candidates"] = [candidate(i, i + 1) for i in range(min(len(pairs), MAX_CANDIDATES))]
    if shown is not None and shown < len(out["candidates"]):
        out["candidates"][shown].update(lat=out["estimate"]["lat"], lon=out["estimate"]["lon"], radius_m=out["estimate"]["radius_m"],
                                        lattice=out["estimate"]["lattice"], refined=out["estimate"]["refined"])
    out["shown_rank"] = None if shown is None else shown + 1

    if a.state == "outside":
        top = pairs.iloc[a.top]
        est = _refine(case, sp, raw, top)
        out["constraints"]["outside_match"] = {
            **candidate(a.top, 1), "lat": est["lat"], "lon": est["lon"], "radius_m": est["radius_m"], "regions": est["regions"],
            "confirmed": a.outside_confirmed,
            "band": ("High" if (v.p == v.p and v.p <= 0.01) else "Medium") if a.outside_confirmed else "Low",
            "events": _event_rows(raw, top, float(top.clip_start), (est["lat"], est["lon"])), "cells": est["cells"], "cell_m": est["cell_m"]}

    cells = raw.res.head(MAX_CELLS)
    out["cells"] = [[round(float(la), 5), round(float(lo), 5), round(float(s), 2)] for la, lo, s in zip(cells.lat, cells.lon, cells.score)]
    return out


def placebo(case: CaseInputs, sp, raw: Raw, data_dir=None, types=None, workers: int | None = None, n_days: int = 3, progress=None) -> list:
    """The placebo-day control (docs/06-confidence.md): the same audio and fits searched against
    the same pack on other days. No pair on those days can be right, so each day's best score
    is a direct sample of "the best wrong answer for this recording here". Proposed, not yet
    validated on a recording with a known answer."""
    from datetime import date

    from dopplertrack.search import rescore_with_extra, run_search

    data_dir = Path(data_dir) if data_dir is not None else config.data_dir()
    workers = workers or config.doppler_workers()
    folder = data_dir / "flights" / case.pack.id
    used = set(raw.days) | set(raw.days_missing)
    others = sorted(f.name[:10] for f in folder.glob("????-??-??-traces.npz") if f.name[:10] not in used) if folder.is_dir() else []
    centre = date.fromisoformat(str(case.date_local))
    others = sorted(others, key=lambda d: abs((date.fromisoformat(d) - centre).days))[:n_days]
    out = []
    for i, day in enumerate(others):
        traces = flights.load_window(case.pack, [day], data_dir, prop_only=True, types=types)
        idx = flights.build_index(traces, case.pack)
        best, n_pairs = 0.0, 0
        if len(idx):
            res = run_search(sp, raw.ev1.fit, raw.ev2.fit, idx, harmonics=(raw.ev1.harmonics, raw.ev2.harmonics), c=raw.c,
                             elevation=raw.elevation, silence_d_m=raw.silence_d_m, workers=workers, log=lambda m: None)
            if len(res) and raw.extras:
                res = rescore_with_extra(sp, raw.ev1.fit, [e.fit for e in raw.extras], idx, res, extra_harmonics=[e.harmonics for e in raw.extras],
                                         c=raw.c, workers=workers, log=lambda m: None)
            if len(res):
                best, n_pairs = float(res.score.max()), int(res.drop_duplicates(["icao1", "icao2"]).shape[0])
        out.append({"utc_date": day, "best_score": round(best, 2), "n_pairs": n_pairs, "n_flights": len(traces)})
        if progress:
            progress("progress", {"stage": "controls", "done": i + 1, "total": len(others)})
    return out


def run(case: CaseInputs, sp, boxes: list[Box], data_dir=None, types=None, workers: int | None = None, burst=None,
        progress=None, fetch_missing: bool = False, placebo_days: int | None = None) -> dict:
    """The whole orchestration: `compute` (twice when an automatic temperature spans a long,
    varied window), the placebo-day control when it is switched on, then `conclude`."""
    kw = dict(data_dir=data_dir, types=types, workers=workers, burst=burst, progress=progress, fetch_missing=fetch_missing)
    temps, source, win = ([None], None, None)
    if len(boxes) >= 2 and case.date_local:
        temps, source, win = weather.search_temperatures(case.pack, case.date_local, case.time_ranges, case.temperature_c,
                                                         case.temperature_source, data_dir if data_dir is not None else config.data_dir())
    raws = [compute(case, sp, boxes, temperature=(t, source) if t is not None else None, **kw) for t in temps]
    scored = [r for r in raws if r.res is not None]
    raw = max(scored, key=lambda r: float(r.res.score.max())) if scored else raws[0]
    raw.temperature_window = win
    if len(raws) == 2:
        # Both runs go on record and the brighter one is the result. The score does not say
        # which temperature is right (measured: the true one scored lowest of three), so what
        # matters is whether both runs name the same flights. "pair" is every flight matched at
        # the winning place, sorted: which two of them formed the search pair can differ.
        def matched(r):
            if r.res is None:
                return None
            top = r.res.iloc[0]
            return sorted({str(top.icao1), str(top.icao2), *(m for m in _extra_matches(top, len(r.extras)) if m)})
        raw.temperature_runs = [{"c": r.temperature_c, "score": None if r.res is None else round(float(r.res.score.max()), 2),
                                 "pair": matched(r)} for r in raws]
    n_placebo = config.placebo_days() if placebo_days is None else placebo_days
    if n_placebo and raw.res is not None:
        if progress:
            progress("stage", {"stage": "controls", "state": "start"})
        raw.placebo = placebo(case, sp, raw, data_dir=data_dir, types=types, workers=workers, n_days=n_placebo, progress=progress)
        if progress:
            progress("stage", {"stage": "controls", "state": "done", "detail": f"{len(raw.placebo)} other day{'s' if len(raw.placebo) != 1 else ''}"})
    if progress and raw.res is not None:
        progress("stage", {"stage": "refine", "state": "start"})
    out = conclude(case, sp, raw)
    if progress and raw.res is not None:
        progress("stage", {"stage": "refine", "state": "done"})
    return out
