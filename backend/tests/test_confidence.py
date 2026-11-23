"""The rules in docs/06-confidence.md, on hand-made tables (fast)."""
import pandas as pd
from dopplertrack.verdict import Verdict

from app.core import confidence


def pairs(*rows):
    """rows: (score, in_area, in_time, n_events)"""
    return pd.DataFrame([{"icao1": f"a{i}", "icao2": f"b{i}", "score": r[0], "in_area": r[1], "in_time": r[2], "n_events": r[3]}
                         for i, r in enumerate(rows)])


def v(label, p):
    return Verdict(label, p, 5.0, 1.0, 20.0, 15, 60, 55, {})


def test_strength_scale():
    assert [confidence.strength(p) for p in (0.0005, 0.001, 0.01, 0.1, 0.5, 1.0)] == [100, 100, 67, 33, 10, 0]
    assert confidence.strength(float("nan")) is None


def test_located_needs_three_flyovers_and_a_located_verdict():
    a = confidence.assess(pairs((35, True, True, 3), (27, True, True, 3)), v("located", 0.004), n_confirmed=3)
    assert (a.state, a.band, a.strength) == ("located", "High", 80)
    a = confidence.assess(pairs((35, True, True, 3)), v("located", 0.043), n_confirmed=3)
    assert (a.state, a.band) == ("located", "Medium")
    # the same verdict on two flyovers is only a candidate
    a = confidence.assess(pairs((35, True, True, 2)), v("located", 0.004), n_confirmed=2)
    assert (a.state, a.band, a.sublabel) == ("candidates", "Low", "needs_third_flyover")
    # three confirmed, but the third matched no flight at the winner
    a = confidence.assess(pairs((35, True, True, 2)), v("located", 0.004), n_confirmed=3)
    assert a.state == "candidates"


def test_candidate_sublabels_follow_the_verdict():
    for label, p, sub in (("ambiguous", 0.3, "unconfirmed"), ("no match", 0.7, "weak")):
        a = confidence.assess(pairs((30, True, True, 3)), v(label, p), n_confirmed=3)
        assert (a.state, a.band, a.sublabel) == ("candidates", "Low", sub)
    a = confidence.assess(pairs((30, True, True, 3)), Verdict("insufficient", float("nan"), float("nan"), float("nan"), float("nan"), 15, 3, 2, {}), n_confirmed=3)
    assert (a.state, a.band, a.sublabel, a.strength) == ("candidates", "Low", "too_few_flights", None)


def test_not_locatable_reasons():
    assert confidence.assess(None, None, n_confirmed=1).reason == "fewer_than_two_flyovers"
    assert confidence.assess(None, None, n_confirmed=0).state == "not_locatable"
    a = confidence.assess(None, None, n_confirmed=2, reason="no_flights")
    assert (a.state, a.band, a.reason) == ("not_locatable", "None", "no_flights")
    assert confidence.assess(pairs(), None, n_confirmed=2).reason == "no_candidates"


def test_outside_when_the_best_pair_breaks_a_constraint():
    # the best pair is outside the area; a weaker one is inside
    a = confidence.assess(pairs((35, False, True, 3), (27, True, True, 3)), v("located", 0.004), n_confirmed=3)
    assert (a.state, a.band, a.top, a.top_in, a.outside_confirmed) == ("outside", "Low", 0, 1, True)
    # nothing at all inside the constraints
    a = confidence.assess(pairs((35, True, False, 2), (27, False, True, 2)), v("ambiguous", 0.3), n_confirmed=2)
    assert (a.state, a.top, a.top_in, a.outside_confirmed) == ("outside", 0, None, False)


def test_caps():
    table = pairs((35, True, True, 3))
    a = confidence.assess(table, v("located", 0.004), n_confirmed=3, bursts=[0.0, 0.3, 0.0])
    assert a.band == "Medium" and any("burst" in c for c in a.caps)
    a = confidence.assess(table, v("located", 0.004), n_confirmed=3, rows_dropped_pct=35.0)
    assert a.band == "Medium" and any("integrity" in c for c in a.caps)
    a = confidence.assess(table, v("located", 0.004), n_confirmed=3, cut_suspected=True)
    assert a.band == "Low"
    a = confidence.assess(table, v("located", 0.004), n_confirmed=3, temperature_disagree=True)
    assert a.band == "Medium" and any("temperature" in c for c in a.caps)
    a = confidence.assess(table, v("located", 0.004), n_confirmed=3, placebo_beaten=1)
    assert a.band == "Medium" and any("placebo" in c for c in a.caps)
    assert confidence.assess(table, v("located", 0.004), n_confirmed=3, placebo_beaten=0).band == "High"
