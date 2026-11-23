"""Smoke test for the dopplertrack library API this project builds on.

No network and no real data: it invents three flights over a point, synthesises the audio
an observer there would record, then runs the same library calls the backend will use
(spectrogram -> fit -> day index -> search -> verdict -> refine) and prints what came back.

Run it first on a new machine. If it passes, the library, numpy/scipy and the API
assumptions in docs/02-dopplertrack.md all hold.

    uv run python scripts/smoke_dopplertrack.py               # baseline, about half a minute
    uv run python scripts/smoke_dopplertrack.py --hot         # also the hot-day experiment
    uv run python scripts/smoke_dopplertrack.py --decoys 25   # also the verdict experiment
    uv run python scripts/smoke_dopplertrack.py --editor      # also the flyover-editor checks

--hot repeats the run with audio synthesised at 40 C and searched at the library default of
15 C, then at the right temperature, to show what an uncorrected speed of sound costs.
--decoys N adds N wrong flight pairs and reports the verdict with two flyovers and with
three. With 25 it showed, during planning, a wrong pair winning on two flyovers (verdict
"no match") and the true pair winning with the third (verdict "located", p 0.04).
--editor checks what the flyover editor depends on, on the app's own spectrogram settings:
a box that is too narrow in frequency makes fit_event raise, the widening rule in fit_box()
fixes that and recovers the true curve, a fit on a slice of the spectrogram equals a fit on
all of it, the quick two-stage fit_preview() agrees with the full fit, boxes drawn around
each curve's bend lead the search to the observer, and automatic detection (fast settings)
is timed and scored against the three known flyovers.
--src PATH prepends a dopplertrack checkout's src/ directory to sys.path (for running
against a clone instead of an installed package).

Verified on dopplertrack commit 2d899bb (2026-11-04) run from a source checkout: Python 3.13,
numpy 2.5.3, scipy 1.18.1, pandas 3.0.5, workers=1, two-core 2.1 GHz machine. All four modes
together took about five minutes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")          # as dopplertrack's own CLI does, before numpy loads

import numpy as np


def synth_case(c_true: float, seed: int = 1):
    """Three flights around an observer at the frame origin, and the audio heard there.

    Returns (traces, audio, sample_rate, truth) where truth lists what a correct pipeline
    should recover. Flight 2 turns: two perfectly straight passes leave a mirror-image
    observer that scores the same (see dopplertrack's own synthetic test)."""
    from dopplertrack import doppler
    from dopplertrack.adsb import Trace
    from dopplertrack.geo import enu_to_lla, lla_to_enu

    lat0, lon0 = 25.05, 55.25              # a point in Dubai; only used as the frame origin
    sr = 4000
    T0 = 1_794_650_000.0                   # unix time the recording starts (a day in Nov 2026)
    dur = 1800

    def trace(icao, t, enu, gs):
        lat, lon, alt = enu_to_lla(enu[:, 0], enu[:, 1], enu[:, 2], lat0, lon0)
        return Trace(icao, None, "SR22", "synthetic", t, lat, lon, alt, np.full_like(t, gs), np.zeros(len(t), bool))

    # flight 1: east-bound, 2.5 km north of the observer at 1500 m, CPA emitted at T0+300
    t1 = T0 + np.arange(0, 900, 5.0)
    e1 = np.stack([110.0 * (t1 - (T0 + 300)), np.full_like(t1, 2500.0), np.full_like(t1, 1500.0)], -1)
    # flight 2: north-bound with a gentle turn, about 3 km east at 1200 m, CPA near T0+1220
    t2 = T0 + np.arange(900, 1800, 5.0)
    tau = t2 - (T0 + 1220)
    e2 = np.stack([3000.0 + 0.1 * tau**2, 95.0 * tau, np.full_like(t2, 1200.0)], -1)
    # flight 3: a low pass to the south-west, 1.2 km away at 600 m, CPA near T0+760 (the "extra" event)
    t3 = T0 + np.arange(500, 1050, 5.0)
    tau3 = t3 - (T0 + 760)
    e3 = np.stack([-900.0 + 60.0 * tau3, -800.0 - 45.0 * tau3 + 0.05 * tau3**2, np.full_like(t3, 600.0)], -1)
    flights = [("aaa001", t1, e1, 110.0, 120.0), ("aaa002", t2, e2, 95.0, 130.0), ("aaa003", t3, e3, 75.0, 98.0)]
    traces = [trace(i, t, e, v / 0.514444) for i, t, e, v, _ in flights]

    obs = np.zeros(3)
    tt = np.arange(0, dur, 1 / sr)
    x = 0.4 * np.random.default_rng(seed).standard_normal(len(tt)).astype(np.float32)
    truth = {"lat": lat0, "lon": lon0, "t0_unix": T0, "c_true": c_true, "events": []}
    for (icao, t, e, v, f0), tr in zip(flights, traces):
        # resample to 1 Hz in the same frame the index will use, exactly as the library does
        tq = np.arange(t[0], t[-1], 1.0)
        enu = lla_to_enu(np.interp(tq, t, tr.lat), np.interp(tq, t, tr.lon), np.interp(tq, t, tr.alt), lat0, lon0)
        to, ratio, r = doppler.curve_from_trajectory(tq, enu, obs, f0=1.0, c=c_true)
        finst = np.interp(tt + T0, to, ratio, left=np.nan, right=np.nan) * f0
        m = np.isfinite(finst)
        ph = 2 * np.pi * np.cumsum(np.nan_to_num(finst, nan=0.0)) / sr
        x[m] += 0.05 * np.sin(ph[m])
        k = int(np.argmin(r))
        truth["events"].append({"icao": icao, "f0": f0, "v": v, "d": float(r[k]), "t_cpa_heard_audio": float(to[k] - T0)})
    return traces, x, sr, truth


def add_decoys(traces, truth, n: int, seed: int = 7):
    """n wrong flight pairs: the true two-flight geometry rotated, moved 30 to 150 km away and
    perturbed in speed, height and timing. They are not in the audio. Each is a hard wrong
    answer (a rotated copy predicts the same curves), so together they give the verdict a
    realistic null to judge the winner against."""
    from dopplertrack.adsb import Trace
    from dopplertrack.geo import enu_to_lla, lla_to_enu

    lat0, lon0 = truth["lat"], truth["lon"]
    rng = np.random.default_rng(seed)
    out = []
    for k in range(n):
        th = rng.uniform(0, 2 * np.pi)
        rot = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
        dist, bearing = rng.uniform(30e3, 150e3), rng.uniform(0, 2 * np.pi)
        off = np.array([dist * np.sin(bearing), dist * np.cos(bearing)])
        tshift = rng.uniform(-150, 150)
        for j, tr in enumerate(traces[:2]):
            enu = lla_to_enu(tr.lat, tr.lon, tr.alt, lat0, lon0)
            sf = rng.uniform(0.88, 1.12)
            xy = enu[:, :2] @ rot.T
            ctr = xy.mean(0)
            xy = ctr + (xy - ctr) * sf + off
            lat, lon, alt = enu_to_lla(xy[:, 0], xy[:, 1], enu[:, 2] * rng.uniform(0.8, 1.25), lat0, lon0)
            lag = rng.uniform(-4, 4) if j == 1 else 0.0
            out.append(Trace(f"d{k:03d}{j}", None, "C172", "decoy", tr.t + tshift + lag, lat, lon, alt, tr.gs * sf, np.zeros(len(tr.t), bool)))
    return out


def run_decoy_case(n: int, temp_c: float = 28.0) -> dict:
    """Two flyovers against a crowd of wrong pairs, then the same with the third flyover."""
    from dopplertrack import audio, pipeline, search, tracks
    from dopplertrack.doppler import speed_of_sound
    from dopplertrack.geo import haversine_m
    from dopplertrack.verdict import verdict

    c = float(speed_of_sound(temp_c))
    traces, x, sr, truth = synth_case(c)
    sp = audio.compute_spectrogram(x, sr, nperseg=8192, hop_s=0.5, fmin=60, fmax=300, whiten_window_s=None)
    idx = search.DayIndex.build(traces + add_decoys(traces, truth, n), truth["lat"], truth["lon"])
    ev1 = tracks.fit_event(sp, 230, 400, 90, 170, c=c, objective="brightness")
    ev2 = tracks.fit_event(sp, 1150, 1310, 100, 180, c=c, objective="brightness")
    ev3 = tracks.fit_event(sp, 700, 840, 75, 130, c=c, objective="brightness")
    t0 = time.time()
    res = search.run_search(sp, ev1, ev2, idx, c=c, workers=1, silence_d_m=None, log=lambda m: None)
    secs = time.time() - t0
    out = {"label": f"{n} decoy pairs", "segments": len(idx), "rows": int(len(res)), "search_seconds": round(secs, 1),
           "ms_per_row": round(1000 * secs / max(len(res), 1), 1)}
    for name, table in (("two_events", res), ("with_third_flyover", search.rescore_with_extra(sp, ev1, [ev3], idx, res, c=c, workers=1, log=lambda m: None))):
        b = pipeline.best_per_pair(table)
        v = verdict(table)
        rank = int(np.flatnonzero((b.icao1 == "aaa001") & (b.icao2 == "aaa002"))[0]) + 1
        out[name] = {"pairs": int(len(b)), "winner": [b.icao1[0], b.icao2[0]], "true_pair_rank": rank,
                     "winner_error_m": round(float(haversine_m(b.lat[0], b.lon[0], truth["lat"], truth["lon"]))),
                     "verdict": v.verdict, "p": None if v.p != v.p else round(float(v.p), 3), "n_null": v.n_null}
    return out


# fit_event searches the fundamental f0 on [1.15 * f_lo, 0.85 * f_hi) in 1 Hz steps, so a band
# with f_hi <= 1.353 * f_lo has an empty grid and raises ValueError. A slow aircraft's whole
# curve can be narrower than that. Widening the analyst's box by the same factors makes the
# grid span exactly the box. The backend's core/events.fit should do the same.
F0_TRIM_LO, F0_TRIM_HI = 1.15, 0.85
FAST_DETECT = dict(refine=False, f0_step=3.0, t0_step=3.0, n_curve=60, min_sep_s=30.0)


def fit_box(sp, t0: float, t1: float, box_lo: float, box_hi: float, c: float, harmonics: int = 1):
    """Fit the flyover inside an analyst-drawn box (seconds, Hz). The box should enclose the
    visible curve; f0 is searched across the whole box."""
    from dopplertrack import tracks

    if box_hi - box_lo < 2.0 or t1 - t0 < 20.0:
        raise ValueError("box too small: need at least 2 Hz and 20 s")
    return tracks.fit_event(sp, t0, t1, box_lo / F0_TRIM_LO, box_hi / F0_TRIM_HI, c=c,
                            harmonics=harmonics, objective="brightness")


def fit_preview(sp, t0: float, t1: float, box_lo: float, box_hi: float, c: float, harmonics: int = 1):
    """A quick fit for the editor overlay: a coarse grid search (3 Hz, 3 s), then fit_event's
    own fine search and polish around that seed. About 2 s where the full fit takes 6 to 19 s.
    It usually lands on the same answer as fit_box but can settle on a nearby weaker optimum,
    so search with fit_box and draw with this."""
    from dopplertrack import tracks

    if box_hi - box_lo < 2.0 or t1 - t0 < 20.0:
        raise ValueError("box too small: need at least 2 Hz and 20 s")
    f_lo, f_hi = box_lo / F0_TRIM_LO, box_hi / F0_TRIM_HI
    pad = 0.3 * (f_hi - f_lo)                      # the same crop and whitening fit_event applies
    win = tracks.local_whiten(sp.crop(t0 - 30, t1 + 30, max(f_lo - pad, sp.f[0]), min(f_hi * harmonics + pad, sp.f[-1])))
    _, seed = tracks.grid_search(win, t0, t1, f_lo, f_hi, c, harmonics, f0_step=3.0, t0_step=3.0, n_curve=60,
                                 objective="brightness")
    return tracks.fit_event(sp, t0, t1, f_lo, f_hi, c=c, harmonics=harmonics, init=seed, objective="brightness")


# boxes an analyst would draw in the editor: about 100 s centred on each curve's bend, tall
# enough to enclose the curve over that time. Order: flight 1, flight 2, flight 3.
BEND_BOXES = [(258.0, 358.0, 92.0, 170.0), (1179.0, 1279.0, 104.0, 172.0), (717.0, 817.0, 79.0, 126.0)]


def run_editor_case(temp_c: float = 28.0) -> dict:
    """What the flyover editor relies on, measured on the spectrogram settings the app uses."""
    from dopplertrack import audio, pipeline, search, tracks
    from dopplertrack.doppler import speed_of_sound
    from dopplertrack.geo import haversine_m

    c = float(speed_of_sound(temp_c))
    traces, x, sr, truth = synth_case(c)
    t = time.time()
    sp = audio.compute_spectrogram(x, sr)                     # defaults: 0.25 s hop, 40 to 450 Hz, whitened
    out = {"label": "flyover editor checks", "audio_minutes": round(len(x) / sr / 60, 1),
           "spectrogram": {"seconds": round(time.time() - t, 1), "shape": list(sp.S.shape), "dtype": str(sp.S.dtype),
                           "megabytes": round(sp.S.nbytes / 1e6, 1)}}

    # 1. a snug box around flight 1's curve near closest approach is too narrow for the library as is
    box = (265.0, 355.0, 110.0, 140.0)
    try:
        tracks.fit_event(sp, *box, c=c, objective="brightness")
        out["narrow_box_raises"] = False
    except ValueError:
        out["narrow_box_raises"] = True

    # 2. the widening rule fixes it and recovers the truth
    t = time.time()
    ev = fit_box(sp, *box, c=c)
    tr = truth["events"][0]
    out["fit_box"] = {"seconds": round(time.time() - t, 1), "t_cpa": round(ev.t_cpa, 1), "f0": round(ev.f0, 1),
                      "v": round(ev.v, 1), "d": round(ev.d), "score": round(ev.score, 1),
                      "truth": {"t_cpa": round(tr["t_cpa_heard_audio"], 1), "f0": tr["f0"], "v": tr["v"], "d": round(tr["d"])}}
    fit_ok = abs(ev.f0 - tr["f0"]) < 2 and abs(ev.v - tr["v"]) < 25 and abs(ev.t_cpa - tr["t_cpa_heard_audio"]) < 6

    # 3. a fit needs only the columns around its window (lets the app memory-map the spectrogram)
    ev_slice = fit_box(sp.crop(box[0] - 60, box[1] + 60), *box, c=c)
    out["slice_fit_matches"] = bool(abs(ev_slice.t_cpa - ev.t_cpa) < 1e-6 and abs(ev_slice.f0 - ev.f0) < 1e-6)

    # 4. a wide, long box costs more: time grows with box length times band width
    t = time.time()
    tracks.fit_event(sp, 230, 400, 90, 170, c=c, objective="brightness")
    out["wide_box_fit_seconds"] = round(time.time() - t, 1)

    # 5. the editor path end to end: bend boxes -> quick preview and full fit -> search
    fits, previews, rows = [], [], []
    for bx, tr in zip(BEND_BOXES, truth["events"]):
        t = time.time(); full = fit_box(sp, *bx, c=c); t_full = time.time() - t
        t = time.time(); prev = fit_preview(sp, *bx, c=c); t_prev = time.time() - t
        fits.append(full); previews.append(prev)
        rows.append({"box": list(bx), "full_seconds": round(t_full, 1), "preview_seconds": round(t_prev, 1),
                     "full": {"t_cpa": round(full.t_cpa, 1), "f0": round(full.f0, 1), "v": round(full.v, 1), "d": round(full.d), "score": round(full.score, 2)},
                     "preview_score": round(prev.score, 2),
                     "truth": {"t_cpa": round(tr["t_cpa_heard_audio"], 1), "f0": tr["f0"], "v": tr["v"], "d": round(tr["d"])}})
    out["bend_boxes"] = rows
    preview_ok = all(p.score > f.score - 0.5 for p, f in zip(previews, fits))
    idx = search.DayIndex.build(traces, truth["lat"], truth["lon"])
    ev1, ev2, ev3 = fits
    res = search.run_search(sp, ev1, ev2, idx, c=c, workers=1, silence_d_m=None, log=lambda m: None)
    search_ok = False
    if len(res):
        best = res.iloc[0]
        fine = pipeline.refine(sp, ev1, ev2, idx, best, spacing_m=50.0, half_m=600.0, extra=[ev3], c=c, log=lambda m: None)
        out["search_from_bend_boxes"] = {"pair": [best.icao1, best.icao2],
                                         "error_m": round(float(haversine_m(best.lat, best.lon, truth["lat"], truth["lon"]))),
                                         "refined_error_m": round(float(haversine_m(fine.lat[0], fine.lon[0], truth["lat"], truth["lon"])))}
        search_ok = best.icao1 == "aaa001" and best.icao2 == "aaa002" and out["search_from_bend_boxes"]["error_m"] < 600

    # 6. automatic detection, fast settings: proposals only
    t = time.time()
    props = tracks.detect_events(sp, 60, 300, c=c, top=12, workers=1, **FAST_DETECT)
    secs = time.time() - t
    heard = [e["t_cpa_heard_audio"] for e in truth["events"]]
    ranks = [next((i + 1 for i, p in enumerate(props) if abs(p.t_cpa - h) < 25), None) for h in heard]
    out["detect_fast"] = {"seconds": round(secs, 1), "seconds_per_audio_minute": round(secs / (len(x) / sr / 60), 1),
                          "proposals": [{"t_cpa": round(p.t_cpa), "f0": round(p.f0), "score": round(p.score, 1), "burst": round(p.burst, 2)} for p in props],
                          "true_flyover_ranks": ranks, "true_flyovers_heard_at": [round(h) for h in heard]}
    out["ok"] = bool(out["narrow_box_raises"] and fit_ok and out["slice_fit_matches"] and preview_ok and search_ok
                     and sum(r is not None for r in ranks) >= 2)
    return out


def run_case(c_true: float, c_search: float, label: str) -> dict:
    from dopplertrack import audio, pipeline, search, tracks
    from dopplertrack.geo import haversine_m
    from dopplertrack.verdict import verdict

    t_start = time.time()
    traces, x, sr, truth = synth_case(c_true)
    sp = audio.compute_spectrogram(x, sr, nperseg=8192, hop_s=0.5, fmin=60, fmax=300, whiten_window_s=None)
    idx = search.DayIndex.build(traces, truth["lat"], truth["lon"])

    # windows an analyst would draw around each flyover: (t0, t1, f_lo, f_hi)
    ev1 = tracks.fit_event(sp, 230, 400, 90, 170, c=c_search, objective="brightness")
    ev2 = tracks.fit_event(sp, 1150, 1310, 100, 180, c=c_search, objective="brightness")
    ev3 = tracks.fit_event(sp, 700, 840, 75, 130, c=c_search, objective="brightness")

    res = search.run_search(sp, ev1, ev2, idx, c=c_search, workers=1, silence_d_m=None, log=lambda m: None)
    out = {"label": label, "c_true": round(c_true, 1), "c_search": round(c_search, 1),
           "spectrogram": {"bins": int(sp.S.shape[0]), "frames": int(sp.S.shape[1]), "df_hz": round(sp.df, 3), "dt_s": round(sp.dt, 3)},
           "index": idx.fingerprint(),
           "fits": [{"t_cpa": round(e.t_cpa, 1), "f0": round(e.f0, 1), "v": round(e.v, 1), "d": round(e.d), "score": round(e.score, 1)} for e in (ev1, ev2, ev3)],
           "truth_events": [{k: (round(v, 1) if isinstance(v, float) else v) for k, v in e.items()} for e in truth["events"]],
           "result_rows": int(len(res)), "result_columns": list(res.columns)}
    if len(res):
        best = res.iloc[0]
        out["best"] = {"icao1": best.icao1, "icao2": best.icao2, "score": round(float(best.score), 2),
                       "shift_s": float(best["shift"]),
                       "error_m": round(float(haversine_m(best.lat, best.lon, truth["lat"], truth["lon"])))}
        # the recording's clock falls out of the search: clip start = t_heard1 - ev1.t_cpa - shift
        clip_start = float(best.t_heard1) - ev1.t_cpa - float(best["shift"])
        out["best"]["clip_start_error_s"] = round(clip_start - truth["t0_unix"], 1)
        fine = pipeline.refine(sp, ev1, ev2, idx, best, spacing_m=50.0, half_m=600.0, extra=[ev3], c=c_search, log=lambda m: None)
        out["refined"] = {"error_m": round(float(haversine_m(fine.lat[0], fine.lon[0], truth["lat"], truth["lon"]))),
                          "score": round(float(fine.score[0]), 2), "extra_icao": fine.attrs["extra_icao"]}
    v = verdict(res) if len(res) else None
    out["verdict"] = None if v is None else {"verdict": v.verdict, "n_pairs": v.n_pairs, "n_null": v.n_null}
    out["seconds"] = round(time.time() - t_start, 1)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", help="path to a dopplertrack checkout's src/ directory")
    ap.add_argument("--hot", action="store_true", help="also run the 40 C experiment")
    ap.add_argument("--decoys", type=int, default=0, metavar="N", help="also run the verdict experiment with N wrong flight pairs (25 takes about 90 s)")
    ap.add_argument("--editor", action="store_true", help="also run the flyover-editor checks (about 2.5 minutes)")
    a = ap.parse_args(argv)
    if a.src:
        sys.path.insert(0, a.src)
    from dopplertrack.doppler import speed_of_sound

    c15, c40 = float(speed_of_sound(15.0)), float(speed_of_sound(40.0))
    runs = [run_case(c15, c15, "baseline: 15 C audio, 15 C search")]
    if a.hot:
        runs.append(run_case(c40, c15, "hot day, uncorrected: 40 C audio, 15 C search"))
        runs.append(run_case(c40, c40, "hot day, corrected: 40 C audio, 40 C search"))
    decoy = run_decoy_case(a.decoys) if a.decoys else None
    editor = run_editor_case() if a.editor else None
    runs += [r for r in (decoy, editor) if r]
    print(json.dumps(runs, indent=1))

    b = runs[0]
    ok = (b["result_rows"] > 0 and b["best"]["icao1"] == "aaa001" and b["best"]["icao2"] == "aaa002"
          and b["best"]["error_m"] < 600 and b["refined"]["extra_icao"] == ["aaa003"]
          and b["verdict"]["verdict"] == "insufficient")
    if decoy and a.decoys >= 25:      # the third flyover must put the true pair first and earn a verdict
        d = decoy["with_third_flyover"]
        ok = ok and d["true_pair_rank"] == 1 and d["verdict"] in ("located", "ambiguous")
    if editor:
        ok = ok and editor["ok"]
    print("SMOKE TEST", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
