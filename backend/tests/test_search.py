"""End to end on the synthetic case: boxes in, a result with a state and a verdict out."""
import json

import pytest
from dopplertrack.geo import haversine_m

from app.core import search, spectro

from .conftest import WORKERS, boxes_for, make_inputs


TRUE = {"aaa001", "aaa002", "aaa003"}


def dist(case, p):
    return float(haversine_m(p["lat"], p["lon"], case.truth["lat"], case.truth["lon"]))


def test_search_finds_observer(out3, case3):
    # every flyover is matched to its own flight, whichever two the search paired up
    by_box = {e["id"]: e["icao"] for e in out3["events"]}
    assert by_box == {"box1": "aaa001", "box2": "aaa002", "box3": "aaa003"}
    assert [e["role"] for e in out3["events"]] == ["pair", "pair", "extra"]
    assert out3["events"][0]["t_cpa"] < out3["events"][1]["t_cpa"]
    assert dist(case3, out3["estimate"]["lattice"]) < 600          # the 200 m lattice
    assert dist(case3, out3["estimate"]) < 100                     # the 50 m refine with the third flyover
    assert out3["estimate"]["radius_m"] >= 50
    # the recording's clock falls out of the search
    assert abs(out3["clip_start_unix"] - case3.truth["t0_unix"]) < 3.0
    assert out3["clip_start_utc"].startswith("2026-11-14T09:53:")


def test_three_events_located(out3):
    assert out3["state"] == "located"
    assert out3["verdict"]["label"] == "located" and out3["verdict"]["p"] < 0.1
    assert out3["band"] in ("High", "Medium") and out3["strength"] >= 33
    assert out3["verdict"]["n_null"] >= 20
    third = [e for e in out3["events"] if e["role"] == "extra"]
    assert len(third) == 1 and third[0]["matched"] and third[0]["icao"] in TRUE and third[0]["type"] == "SR22"
    assert out3["estimate"]["regions"] == ["home"]
    assert out3["inputs"]["flight_days"] == ["2026-11-14"] and out3["inputs"]["flight_days_missing"] == ["2026-11-13"]
    json.dumps(out3)                                               # the whole result is plain JSON


def test_result_carries_what_the_ui_draws(out3):
    for e in out3["events"]:
        assert len(e["curve"]) > 20 and e["cpa_time_utc"].endswith("Z") and e["slant_m"] > 100
    assert 1 <= len(out3["candidates"]) <= 5 and out3["candidates"][0]["rank"] == 1 and out3["shown_rank"] == 1
    assert 0 < len(out3["cells"]) <= 2000 and len(out3["cells"][0]) == 3
    # the map: each matched flight's track past the estimate, its closest point, and the 50 m cells
    for e in out3["events"]:
        pts, cpa = e["path"]["points"], e["path"]["cpa"]
        assert len(pts) > 30 and float(haversine_m(cpa[0], cpa[1], out3["estimate"]["lat"], out3["estimate"]["lon"])) < e["slant_m"] + 200
    est = out3["estimate"]
    assert est["cell_m"] == 50.0 and 0 < len(est["cells"]) <= 800 and est["cells"][0][:2] == [round(est["lat"], 5), round(est["lon"], 5)]
    top = out3["candidates"][0]
    assert top["regions"] == ["home"] and len(top["paths"]) == 2 and top["refined"] is True
    assert out3["not_locatable"] is None


def test_two_events_are_candidates(case2, types):
    out = search.run(make_inputs(), case2.sp, boxes_for(2), data_dir=case2.data_dir, types=types, workers=WORKERS,
                     burst=spectro.load_burst(case2.case_dir))
    assert out["state"] == "candidates" and out["band"] == "Low"
    assert out["sublabel"] in ("unconfirmed", "weak", "needs_third_flyover", "too_few_flights")
    assert out["inputs"]["params"]["silence_d_m"] == 6000.0        # 15 minutes apart, nothing confirmed between
    truth_rank = [c["rank"] for c in out["candidates"] if c["icao"] == ["aaa001", "aaa002"]]
    assert truth_rank and truth_rank[0] <= 5
    assert dist(case2, [c for c in out["candidates"] if c["rank"] == truth_rank[0]][0]) < 600


def test_no_events_not_locatable(case3, types):
    out = search.run(make_inputs(), case3.sp, boxes_for(1), data_dir=case3.data_dir, types=types, workers=1)
    assert out["state"] == "not_locatable" and out["band"] == "None"
    assert out["not_locatable"]["reason"] == "fewer_than_two_flyovers"
    assert out["not_locatable"]["checked"] and out["not_locatable"]["advice"]
    assert out["estimate"] is None and out["candidates"] == []


def test_no_flights_not_locatable(case3, types, tmp_path):
    out = search.run(make_inputs(), case3.sp, boxes_for(2), data_dir=tmp_path, types=types, workers=1)
    assert out["state"] == "not_locatable" and out["not_locatable"]["reason"] == "no_flights"


def test_outside_constraints(case3, raw3):
    # the analyst says "away", the truth is in "home"
    out = search.conclude(make_inputs(region_ids=["away"]), case3.sp, raw3)
    assert out["state"] == "outside" and out["band"] == "Low"
    om = out["constraints"]["outside_match"]
    assert set(om["icao"]) <= TRUE and dist(case3, om) < 600
    assert om["confirmed"] is True                                 # three flyovers and a located verdict
    # the list still starts with the best place overall, flagged as outside, not hidden
    assert out["candidates"][0]["icao"] == om["icao"] and out["candidates"][0]["in_area"] is False
    assert out["shown_rank"] is None or out["candidates"][out["shown_rank"] - 1]["in_area"]
    # a time window that excludes the recording does the same
    out = search.conclude(make_inputs(time_ranges=[["01:00", "03:00"]]), case3.sp, raw3)
    assert out["state"] == "outside" and set(out["constraints"]["outside_match"]["icao"]) <= TRUE
    # and a window that holds it does not
    out = search.conclude(make_inputs(time_ranges=[["12:00", "17:00"]], region_ids=["home"]), case3.sp, raw3)
    assert out["state"] == "located"


def test_wrong_temperature_misses(case3, types):
    # 28 C audio searched at 3 C: a 25 C error
    cold = make_inputs(temperature_c=3.0)
    out = search.run(cold, case3.sp, boxes_for(3), data_dir=case3.data_dir, types=types, workers=WORKERS)
    assert out["inputs"]["temperature_c"] == 3.0
    missed = out["estimate"] is None or dist(case3, out["estimate"]) > 2000
    assert missed or out["band"] != "High"


def test_stage_events_cover_the_search(raw3):
    names = [p["stage"] for k, p in raw3.progress_log if k == "stage" and p["state"] == "start"]
    assert names[:2] == ["fits", "flights"] and "scoring" in names and "extras" in names
    details = {p["stage"]: p.get("detail") for k, p in raw3.progress_log if k == "stage" and p["state"] == "done"}
    assert details["fits"] == "3 of 3" and details["flights"] == "153 propeller" and details["join"].endswith("pairs")
    assert details["lattice"].endswith("points") and details["extras"] == "1 flyover"
    # the map gets the search points before they are scored, then again with scores
    cells = [p for k, p in raw3.progress_log if k == "cells"]
    assert [c["scored"] for c in cells] == [False, True]
    assert all(pt[2] is None for pt in cells[0]["points"]) and cells[1]["points"][0][2] >= cells[1]["points"][-1][2]
    assert 0 < len(cells[0]["points"]) <= 2100 and 0 < len(cells[1]["points"]) <= 2000


def _shifted_day(case, traces, days: int, utc_day: str):
    """The same flights one or more days later: a flight day for the test pack."""
    import dataclasses

    from dopplertrack.adsb import save_traces

    from app.core import flights

    path = flights.traces_path(case.data_dir, "test", utc_day)
    save_traces([dataclasses.replace(t, t=t.t + 86400.0 * days) for t in traces], path)
    return path


def test_placebo_days_are_a_control(case3, raw3, types):
    from app.core import flights

    pack = make_inputs().pack
    day = flights.load_window(pack, ["2026-11-14"], case3.data_dir, types=types)
    decoys = [t for t in day if not t.icao.startswith("aaa")]
    made = [_shifted_day(case3, decoys, 1, "2026-11-15"), _shifted_day(case3, decoys[::2], 2, "2026-11-16")]
    try:
        # two other days that hold only wrong flights: the real day beats them both
        runs = search.placebo(make_inputs(), case3.sp, raw3, data_dir=case3.data_dir, types=types, workers=WORKERS, n_days=3)
        assert [r["utc_date"] for r in runs] == ["2026-11-15", "2026-11-16"] and runs[0]["n_flights"] == 150
        top = float(raw3.res.score.max())
        assert all(0 <= r["best_score"] < top for r in runs)
        raw3.placebo = runs
        out = search.conclude(make_inputs(), case3.sp, raw3)
        assert out["controls"]["placebo_days"] == runs and out["controls"]["placebo_beaten_by"] == 0
        assert out["state"] == "located" and not any("placebo" in c for c in out["caps"])
        # a day that happens to score as high takes High away, and says why
        raw3.placebo = runs + [{"utc_date": "2026-11-17", "best_score": top + 1.0, "n_pairs": 9, "n_flights": 20}]
        capped = search.conclude(make_inputs(), case3.sp, raw3)
        assert capped["controls"]["placebo_beaten_by"] == 1 and capped["band"] != "High" and any("placebo" in c for c in capped["caps"])
    finally:
        raw3.placebo = None
        for p in made:
            p.unlink()


def test_a_long_automatic_window_is_searched_at_two_temperatures(case2, types, monkeypatch):
    from app.core import weather

    # the archive says 23 to 31 C over the day; the audio was made at 28 C
    monkeypatch.setattr(weather, "search_temperatures", lambda *a, **k: ([20.0, 28.0], "auto", {"mean_c": 27.0, "min_c": 23.0, "max_c": 31.0, "hours": 24.0}))
    out = search.run(make_inputs(temperature_c=None), case2.sp, boxes_for(2), data_dir=case2.data_dir, types=types, workers=WORKERS)
    runs = out["inputs"]["temperature_runs"]
    assert [r["c"] for r in runs] == [20.0, 28.0] and all(r["score"] > 0 for r in runs)
    # 8 C either way, both runs name the same flights, so nothing is capped ...
    assert runs[0]["pair"] == runs[1]["pair"] == ["aaa001", "aaa002"] and not any("temperature" in c for c in out["caps"])
    # ... and the result is the brighter run, whichever that is. It is not the true temperature
    # here: the score does not measure temperature (docs/03-method-and-evidence.md).
    best = max(runs, key=lambda r: r["score"])
    assert out["inputs"]["temperature_c"] == best["c"] and out["inputs"]["temperature_source"] == "auto"
    assert out["inputs"]["temperature_window"]["max_c"] == 31.0
    assert out["candidates"][0]["icao"] == ["aaa001", "aaa002"]
