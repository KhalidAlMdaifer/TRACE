"""Step 0, stage 2: how much usable propeller traffic did a region have on one day?

Stage 1 needs the network (it streams about 4 GB and stores only the result). Include jets
so this report can compare them:

    mkdir -p data/flights/uae data/coverage     # fetch saves at the very end and does not create folders
    uv run dopplertrack fetch 2026-11-14 data/flights/uae/2026-11-14.npz \
        --bbox 22.6 26.1 51.5 56.4 --keep-jets --traces data/flights/uae/2026-11-14-traces.npz

Stage 2 is this script, offline apart from one small download the first time (the ICAO
Doc 8643 type table, cached by dopplertrack; pass --types-csv to use a local copy):

    uv run python scripts/coverage_report.py data/flights/uae/2026-11-14-traces.npz --out data/coverage/2026-11-14

It writes summary.json, by_type.csv, by_hour.csv, sites.csv, grid.csv and, if matplotlib is
installed, map.png. The number that matters most is in sites.csv: how many propeller
passes a recorder at each site could have heard that day (closest approach within
--radius metres, below --ceiling metres), and how many pairs of passes fall 1 to 30
minutes apart, since the search needs at least two.

    uv run python scripts/coverage_report.py --self-test      # no data needed

--src PATH prepends a dopplertrack checkout's src/ directory to sys.path.
Times are reported in local time using --utc-offset hours (default 4, Gulf Standard Time).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np

UAE_BBOX = (22.6, 26.1, 51.5, 56.4)          # lat_min, lat_max, lon_min, lon_max (dopplertrack's order)
UAE_SITES = [                                  # approximate city-centre points, for a first look only
    ("Abu Dhabi city", 24.4539, 54.3773), ("Al Ain", 24.2075, 55.7447), ("Dubai city", 25.2048, 55.2708),
    ("Dubai South", 24.8960, 55.1614), ("Sharjah", 25.3463, 55.4209), ("Ajman", 25.4052, 55.5136),
    ("Umm Al Quwain", 25.5647, 55.5552), ("Ras Al Khaimah", 25.7895, 55.9432), ("Fujairah", 25.1288, 56.3265),
]
CLASSES = ("prop", "jet", "unknown")


def classify(typ, types) -> tuple[str, str, bool]:
    """(class, engine label, is_helicopter) for an ICAO type designator.

    class is 'prop' for Piston / Turboprop / Turboshaft / Electric, 'jet' for Jet, 'unknown'
    when the designator is missing or not in the table. dopplertrack's own prop filter keeps
    unknown types; this report counts them separately so the difference is visible."""
    if types is None or not typ:
        return "unknown", "unknown", False
    row = types.types.get(typ)
    if row is None:
        return "unknown", "unknown", False
    eng = row.get("EngineType") or "unknown"
    heli = "helicopter" in (row.get("AircraftDescription") or "").lower()
    if any(k in eng for k in ("Piston", "Turboprop", "Turboshaft", "Electric")):
        return "prop", eng, heli
    if "Jet" in eng:
        return "jet", eng, heli
    return "unknown", eng, heli


def passes_for_site(traces, classes, lat, lon, radius_m, ceiling_m):
    """Closest approach of every airborne segment to one ground point.

    Returns a list of (class, icao, typ, t_cpa_unix, slant_m, alt_m) for approaches within
    radius_m whose altitude at the closest point is at or below ceiling_m. A segment whose
    closest sample is its first or last is skipped: the real closest approach lies outside
    the data, the same rule dopplertrack applies."""
    out = []
    obs = np.zeros(3)
    for tr, cls in zip(traces, classes):
        for sl in tr.segments():
            if sl.stop - sl.start < 3:
                continue
            la, lo = tr.lat[sl], tr.lon[sl]
            # cheap reject: nothing within about radius of the site in degrees
            dlat = radius_m / 111320.0 * 1.5
            dlon = dlat / max(np.cos(np.radians(lat)), 0.2)
            if not ((np.abs(la - lat) < dlat) & (np.abs(lo - lon) < dlon)).any():
                continue
            t, enu = tr.enu(sl, lat, lon, 1.0)
            if len(t) < 3 or not np.all(np.isfinite(enu)):
                continue
            d = np.linalg.norm(enu - obs, axis=1)
            j = int(np.argmin(d))
            if j == 0 or j == len(t) - 1:
                continue
            alt = float(np.interp(t[j], tr.t[sl], tr.alt[sl]))
            if d[j] <= radius_m and alt <= ceiling_m:
                out.append((cls, tr.icao, tr.typ or "", float(t[j]), float(d[j]), alt))
    return sorted(out, key=lambda p: p[3])


def usable_pairs(times, lo_s=60.0, hi_s=1800.0) -> int:
    """Pairs of consecutive passes whose gap is between lo_s and hi_s."""
    t = np.sort(np.asarray(times, float))
    gaps = np.diff(t)
    return int(((gaps >= lo_s) & (gaps <= hi_s)).sum())


def build_report(traces, types, bbox, sites, radius_m, ceiling_m, utc_offset_h) -> dict:
    lat0, lat1, lon0, lon1 = bbox
    cls_info = [classify(tr.typ, types) for tr in traces]
    classes = [c for c, _, _ in cls_info]
    by_type = Counter(); by_engine = Counter(); helis = 0
    by_hour = {c: defaultdict(set) for c in CLASSES}
    grid = defaultdict(set)
    airborne = {c: 0 for c in CLASSES}; low = {c: 0 for c in CLASSES}
    for tr, (cls, eng, heli) in zip(traces, cls_info):
        segs = tr.segments()
        if not segs:
            continue
        m = np.zeros(len(tr.t), bool)
        for sl in segs:
            m[sl] = True
        m &= (tr.lat >= lat0) & (tr.lat <= lat1) & (tr.lon >= lon0) & (tr.lon <= lon1)
        if not m.any():
            continue
        airborne[cls] += 1
        by_type[(cls, tr.typ or "?")] += 1
        by_engine[eng] += 1
        helis += int(heli)
        ml = m & (tr.alt <= ceiling_m)
        if not ml.any():
            continue
        low[cls] += 1
        hours = np.unique(((tr.t[ml] + utc_offset_h * 3600.0) // 3600 % 24).astype(int))
        for h in hours:
            by_hour[cls][int(h)].add(tr.icao)
        if cls == "prop":
            cells = {(round(float(a), 1), round(float(o), 1)) for a, o in zip(np.floor(tr.lat[ml] * 10) / 10, np.floor(tr.lon[ml] * 10) / 10)}
            for cell in cells:
                grid[cell].add(tr.icao)
    site_rows = []
    for name, la, lo in sites:
        ps = passes_for_site(traces, classes, la, lo, radius_m, ceiling_m)
        row = {"site": name, "lat": la, "lon": lo}
        for c in CLASSES:
            row[f"{c}_passes"] = sum(1 for p in ps if p[0] == c)
        prop_t = [p[3] for p in ps if p[0] == "prop"]
        row["prop_pairs_1_to_30_min"] = usable_pairs(prop_t)
        row["prop_aircraft"] = len({p[1] for p in ps if p[0] == "prop"})
        row["prop_types"] = " ".join(f"{k}:{v}" for k, v in Counter(p[2] or "?" for p in ps if p[0] == "prop").most_common(6))
        hrs = Counter(int((t + utc_offset_h * 3600.0) // 3600 % 24) for t in prop_t)
        row["prop_passes_by_local_hour"] = " ".join(f"{h:02d}:{hrs[h]}" for h in sorted(hrs))
        site_rows.append(row)
    return {
        "summary": {
            "traces_in_file": len(traces), "bbox": list(bbox), "ceiling_m": ceiling_m, "radius_m": radius_m, "utc_offset_h": utc_offset_h,
            "aircraft_airborne_in_bbox": airborne, "aircraft_below_ceiling_in_bbox": low,
            "engine_types": dict(by_engine), "helicopters": helis, "types_table_loaded": types is not None,
        },
        "by_type": [{"class": c, "type": t, "aircraft": n} for (c, t), n in by_type.most_common()],
        "by_hour": [{"local_hour": h, **{c: len(by_hour[c].get(h, ())) for c in CLASSES}} for h in range(24)],
        "sites": site_rows,
        "grid": [{"lat": la, "lon": lo, "prop_aircraft": len(s)} for (la, lo), s in sorted(grid.items())],
    }


def write_report(rep: dict, out_dir: Path, traces=None, bbox=None, ceiling_m=3000.0, classes=None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(rep["summary"], indent=1))
    for name in ("by_type", "by_hour", "sites", "grid"):
        rows = rep[name]
        with open(out_dir / f"{name}.csv", "w", newline="") as fh:
            if rows:
                w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                w.writeheader(); w.writerows(rows)
    if traces is None:
        return
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    fig, ax = plt.subplots(figsize=(9, 7), facecolor="#0C0C0B")
    ax.set_facecolor("#0C0C0B")
    for tr, cls in zip(traces, classes):
        if cls == "unknown":
            continue
        m = tr.alt <= ceiling_m
        if m.any():
            ax.plot(tr.lon[m], tr.lat[m], ".", ms=1.2, color="#FF4D42" if cls == "prop" else "#3A3A36", zorder=3 if cls == "prop" else 1)
    for row in rep["sites"]:
        ax.plot(row["lon"], row["lat"], "s", ms=5, mfc="none", mec="#F4F1E8", zorder=4)
        ax.annotate(f'{row["site"]} ({row["prop_passes"]})', (row["lon"], row["lat"]), color="#F4F1E8", fontsize=7, xytext=(4, 4), textcoords="offset points")
    ax.set_xlim(bbox[2], bbox[3]); ax.set_ylim(bbox[0], bbox[1])
    ax.set_aspect(1 / np.cos(np.radians((bbox[0] + bbox[1]) / 2)))
    ax.tick_params(colors="#A8A39A", labelsize=7)
    for s in ax.spines.values():
        s.set_color("#272725")
    ax.set_title(f"Track points below {ceiling_m:.0f} m: propeller in red, jet in grey. Site labels show audible propeller passes.", color="#F4F1E8", fontsize=8)
    fig.savefig(out_dir / "map.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def self_test() -> int:
    """Three invented flights around one site, with known answers."""
    from dopplertrack.adsb import Trace
    from dopplertrack.geo import enu_to_lla

    lat0, lon0 = 25.0, 55.0
    T0 = 1_794_650_400.0                        # 2026-11-14 10:00:00 UTC, 14:00 local at UTC+4

    def tr(icao, typ, t, e, n, u):
        lat, lon, alt = enu_to_lla(e, n, u, lat0, lon0)
        return Trace(icao, None, typ, "synthetic", t, lat, lon, alt, np.full_like(t, 60.0), np.zeros(len(t), bool))

    t = T0 + np.arange(0, 600, 5.0)
    x = 80.0 * (t - (T0 + 300))
    a = tr("p00001", "C172", t, x, np.full_like(t, 2000.0), np.full_like(t, 900.0))                # prop, 2 km north, 900 m: audible
    b = tr("p00002", "PC12", t + 600, x, np.full_like(t, -3000.0), np.full_like(t, 1500.0))        # prop, 10 min later: a usable pair
    c = tr("j00001", "A320", t + 100, x * 2.5, np.full_like(t, 1000.0), np.full_like(t, 9000.0))   # jet, overhead at 9 km: above ceiling
    d = tr("p00003", "SR22", t + 200, x, np.full_like(t, 40000.0), np.full_like(t, 900.0))         # prop, 40 km away: out of range

    class FakeTypes:
        types = {"C172": {"EngineType": "Piston", "AircraftDescription": "LandPlane"}, "PC12": {"EngineType": "Turboprop/Turboshaft", "AircraftDescription": "LandPlane"},
                 "SR22": {"EngineType": "Piston", "AircraftDescription": "LandPlane"}, "A320": {"EngineType": "Jet", "AircraftDescription": "LandPlane"}}

    rep = build_report([a, b, c, d], FakeTypes(), (24.0, 26.0, 54.0, 56.0), [("site", lat0, lon0)], 6000.0, 3000.0, 4.0)
    s = rep["summary"]; site = rep["sites"][0]
    checks = {
        "airborne counts": s["aircraft_airborne_in_bbox"] == {"prop": 3, "jet": 1, "unknown": 0},
        "below ceiling": s["aircraft_below_ceiling_in_bbox"] == {"prop": 3, "jet": 0, "unknown": 0},
        "site prop passes": site["prop_passes"] == 2,
        "site jet passes": site["jet_passes"] == 0,
        "usable pairs": site["prop_pairs_1_to_30_min"] == 1,
        "local hour": [r for r in rep["by_hour"] if r["prop"]][0]["local_hour"] == 14,
        "classify unknown": classify("ZZZZ", FakeTypes()) == ("unknown", "unknown", False) and classify(None, None)[0] == "unknown",
    }
    for k, ok in checks.items():
        print(("ok   " if ok else "FAIL ") + k)
    print("SELF-TEST", "PASSED" if all(checks.values()) else "FAILED")
    return 0 if all(checks.values()) else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Coverage report for one day's traces (see the module docstring).")
    ap.add_argument("traces", nargs="?", help="traces .npz written by `dopplertrack fetch ... --traces`")
    ap.add_argument("--out", default="coverage", help="output directory")
    ap.add_argument("--bbox", nargs=4, type=float, default=UAE_BBOX, metavar=("LATMIN", "LATMAX", "LONMIN", "LONMAX"))
    ap.add_argument("--site", nargs=3, action="append", metavar=("NAME", "LAT", "LON"), help="repeatable; replaces the default UAE sites")
    ap.add_argument("--radius", type=float, default=6000.0, help="audible slant distance, m")
    ap.add_argument("--ceiling", type=float, default=3000.0, help="highest altitude counted as audible, m")
    ap.add_argument("--utc-offset", type=float, default=4.0)
    ap.add_argument("--types-csv", help="local copy of doc8643AircraftTypes.csv")
    ap.add_argument("--src", help="path to a dopplertrack checkout's src/ directory")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.src:
        sys.path.insert(0, a.src)
    if a.self_test:
        return self_test()
    if not a.traces:
        ap.error("give a traces .npz, or --self-test")
    from dopplertrack.adsb import AircraftTypes, load_traces

    traces = load_traces(a.traces)
    try:
        types = AircraftTypes(a.types_csv)
    except Exception as e:                       # no network and no cached table: report everything as unknown
        print(f"warning: aircraft type table unavailable ({e}); every aircraft will be 'unknown'", file=sys.stderr)
        types = None
    sites = [(n, float(la), float(lo)) for n, la, lo in a.site] if a.site else UAE_SITES
    rep = build_report(traces, types, tuple(a.bbox), sites, a.radius, a.ceiling, a.utc_offset)
    classes = [classify(tr.typ, types)[0] for tr in traces]
    write_report(rep, Path(a.out), traces, tuple(a.bbox), a.ceiling, classes)
    print(json.dumps(rep["summary"], indent=1))
    for row in rep["sites"]:
        print(f'{row["site"]:<16} prop passes {row["prop_passes"]:>4}   pairs 1-30 min {row["prop_pairs_1_to_30_min"]:>4}   jets {row["jet_passes"]:>5}')
    print(f"wrote {a.out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
