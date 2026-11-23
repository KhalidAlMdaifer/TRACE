"""The flyover fits the editor and the search rely on (docs/02-dopplertrack.md, behaviours 11 to 15)."""
import time

import pytest
from dopplertrack import tracks
from dopplertrack.doppler import speed_of_sound
from dopplertrack.geo import haversine_m

from app.core import events, spectro, synth

from .conftest import WORKERS


def test_fit_recovers_truth(raw3, case3):
    # the search's own full fits of the three bend boxes
    for fe, tr in zip(raw3.fits, case3.truth["events"]):
        ev = fe.fit
        assert abs(ev.f0 - tr["f0"]) < 2.0
        assert abs(ev.v - tr["v"]) < 25.0
        assert abs(ev.t_cpa - tr["t_cpa_heard_audio"]) < 6.0


def test_narrow_box_does_not_raise(case3):
    box = synth.NARROW_BOX
    with pytest.raises(ValueError):                    # the library as given: an empty f0 grid
        tracks.fit_event(case3.sp, *box, c=case3.c, objective="brightness")
    ev = events.fit(case3.sp, *box, harmonics=1, c=case3.c)
    tr = case3.truth["events"][0]
    assert abs(ev.f0 - tr["f0"]) < 2.0 and abs(ev.t_cpa - tr["t_cpa_heard_audio"]) < 6.0


def test_tiny_box_rejected(case3):
    for box in ((300.0, 310.0, 100.0, 140.0), (260.0, 360.0, 120.0, 121.0)):   # 10 s long; 1 Hz tall
        for fn in (events.fit, events.preview):
            with pytest.raises(events.BoxTooSmall) as e:
                fn(case3.sp, *box, harmonics=1, c=case3.c)
            assert e.value.code == "box_too_small"


def test_slice_fit_equals_full_fit(case3):
    box = synth.NARROW_BOX
    full = events.fit(case3.sp, *box, harmonics=1, c=case3.c)
    part = events.fit(spectro.load(case3.case_dir, box[0] - 60, box[1] + 60), *box, harmonics=1, c=case3.c)
    assert abs(part.t_cpa - full.t_cpa) < 1e-6 and abs(part.f0 - full.f0) < 1e-6


def test_search_fit_does_not_depend_on_where_the_box_edge_falls(case3):
    # a box an analyst drew by hand for flight 2, a hertz and a second off the planning box. A
    # single fit of it lands on a weaker curve (f0 139 Hz, score 8.2); the search's fit must not.
    box = (1176.7, 1278.2, 105.1, 173.9)
    tr = case3.truth["events"][1]
    ev, = events.fit_many(case3.sp, [(*box, 1)], case3.c, workers=WORKERS)
    assert abs(ev.f0 - tr["f0"]) < 2.0 and abs(ev.v - tr["v"]) < 25.0 and abs(ev.t_cpa - tr["t_cpa_heard_audio"]) < 6.0
    assert ev.score > 12.0 and (ev.t_start, ev.t_end) == (box[0], box[1])
    with pytest.raises(events.BoxTooSmall):
        events.fit_many(case3.sp, [(*box, 1), (300.0, 310.0, 100.0, 140.0, 1)], case3.c, workers=WORKERS)


def test_preview_close_to_full(raw3, case3):
    # the editor asks for the quick fit at each grid phase and draws the brightest; that one
    # must be as good as the search's own fit of the same box
    for box, fe in zip(synth.BEND_BOXES, raw3.fits):
        outs = []
        for phase in events.PHASES_HZ:
            t = time.time()
            outs.append(events.preview_from_disk(case3.case_dir, *box, harmonics=1, c=case3.c, phase_hz=phase))
            assert time.time() - t < 5.0
        out = max(outs, key=lambda o: o["fit"]["score"])
        assert out["fit"]["score"] > fe.fit.score - 0.5
        assert abs(out["fit"]["f0"] - fe.fit.f0) < 1.0
        assert len(out["curve"]) > 20 and all(box[0] <= p[0] <= box[1] for p in out["curve"])


def test_harmonics_are_capped_to_the_grid(case3):
    assert events.effective_harmonics(case3.sp, 170.0, 5) == 2      # 3 x 170 Hz is past 450 Hz
    assert events.effective_harmonics(case3.sp, 100.0, 2) == 2
    assert events.effective_harmonics(case3.sp, 300.0, 0) == 1


def test_fit_sets_burst_from_the_whole_recording(case3):
    burst = spectro.load_burst(case3.case_dir)
    ev = events.fit(spectro.load(case3.case_dir, 205.0, 415.0), *synth.NARROW_BOX, harmonics=1, c=case3.c, burst=burst)
    assert 0.0 <= ev.burst < 0.15                                    # clean synthetic audio


def test_proposal_box_sits_on_the_bend(raw3, case3):
    ev = raw3.fits[0].fit
    t0, t1, lo, hi = events.proposal_box(ev, case3.c, case3.sp)
    assert abs((t0 + t1) / 2 - ev.t_cpa) < 1e-6 and t1 - t0 == 100.0
    inside = [f for t, f in events.curve_points(ev, case3.c, t0=t0, t1=t1)]
    assert lo <= min(inside) and hi >= max(inside)
    assert lo >= case3.sp.f[0] and hi <= case3.sp.f[-1] and hi - lo < 120


def test_pick_pair_takes_the_two_best_earlier_first(raw3):
    a, b, rest = events.pick_pair(raw3.fits)
    assert a.t_cpa < b.t_cpa and len(rest) == 1
    assert min(a.score, b.score) >= rest[0].score


@pytest.mark.slow
def test_propose_finds_flyovers(case3):
    calls = []
    props = events.propose(case3.sp, case3.c, workers=min(WORKERS, 4), burst=spectro.load_burst(case3.case_dir),
                           on_slice=lambda done_s, total_s, added, removed: calls.append((done_s, total_s, len(added))))
    heard = [e["t_cpa_heard_audio"] for e in case3.truth["events"]]
    found = sum(any(abs(p.t_cpa - h) < 25 for p in props) for h in heard)
    assert found >= 2
    n_slices = len(events.slices(float(case3.sp.t[-1])))
    assert len(calls) == n_slices and [c[0] for c in calls] == sorted({c[0] for c in calls})
    assert calls[-1][0] == pytest.approx(calls[-1][1])
    # proposals are merged: no two within 30 s of each other
    ts = sorted(p.t_cpa for p in props)
    assert all(b - a >= 30 for a, b in zip(ts, ts[1:]))


def test_search_refits_at_search_temperature(raw3, out3, case3):
    # an editor preview made at the library's 15 C is not what gets searched
    prev = events.preview(case3.sp, *synth.BEND_BOXES[2], harmonics=1, c=float(speed_of_sound(15.0)))
    searched = raw3.fits[2].fit
    assert raw3.c == pytest.approx(float(speed_of_sound(28.0)))
    assert abs(prev.v - searched.v) > 1e-3             # a different speed of sound gives a different fit
    assert out3["inputs"]["temperature_c"] == 28.0
    est = out3["estimate"]
    assert float(haversine_m(est["lat"], est["lon"], case3.truth["lat"], case3.truth["lon"])) < 100
