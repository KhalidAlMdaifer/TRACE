"""The Oyster Bay reference recording through our own code. Skipped unless the reference data
is on disk (docs/03-method-and-evidence.md says how it was obtained):

    data/reference/oyster_bay/rec.npz         spectrogram of youtu.be/4CxVxuMVkMc
    data/reference/oyster_bay/traces_ny.npz   flights of 2026-09-08 in the New York box

The quick check mirrors dopplertrack's own opt-in test: our fits of the reference boxes, then
the true pair must survive the search filters at the known location. The full search (about
five minutes on eight workers) is marked `reference`: run it with `uv run pytest -m reference`.
"""
import os
from pathlib import Path

import numpy as np
import pytest
from dopplertrack.geo import haversine_m

from app import config
from app.core import events, flights, geo, search

REF = Path(os.environ.get("TRACE_OYSTER_BAY", config.data_dir() / "reference" / "oyster_bay"))
TRUTH = (40.876466, -73.524951)
PAIR = ["a1dfeb", "ace391"]                     # N22NY, then N93CQ
TEMP_C = 15.0                                   # the library default the author's run used; the real figure was not looked up

# The author's `fit --band LO HI` passes the band straight to fit_event, which searches the
# fundamental on [1.15 LO, 0.85 HI). Our boxes are that range, so the widening rule gives
# the author's band back: 95-200 Hz x2, 95-195 Hz, 70-105 Hz x2.
BOXES = [("ev1", 2090.0, 2200.0, 95 * 1.15, 200 * 0.85, 2), ("ev2", 3020.0, 3130.0, 95 * 1.15, 195 * 0.85, 1),
         ("faint", 1375.0, 1465.0, 70 * 1.15, 105 * 0.85, 2)]

pytestmark = pytest.mark.skipif(not ((REF / "rec.npz").exists() and (REF / "traces_ny.npz").exists()),
                                reason="Oyster Bay reference data not on disk")


@pytest.fixture(scope="module")
def recording(tmp_path_factory):
    from dopplertrack.audio import Spectrogram

    data = tmp_path_factory.mktemp("ny")
    (data / "flights" / "ny").mkdir(parents=True)
    (data / "flights" / "ny" / "2026-09-08-traces.npz").symlink_to((REF / "traces_ny.npz").resolve())
    config.use_dopplertrack_cache()
    return Spectrogram.load(REF / "rec.npz"), data


def test_true_pair_survives_at_the_known_point(recording):
    from dopplertrack.doppler import speed_of_sound
    from dopplertrack.search import run_search

    sp, data = recording
    c = float(speed_of_sound(TEMP_C))
    pack = geo.load_pack("ny")
    ev1, ev2 = (events.fit(sp, *b[1:5], harmonics=b[5], c=c) for b in BOXES[:2])
    assert abs(ev1.t_cpa - 2155.96) < 0.5 and abs(ev1.f0 - 112.62) < 0.5      # the author's reference fits
    assert abs(ev2.t_cpa - 3073.94) < 0.5 and abs(ev2.f0 - 132.41) < 0.5
    idx = flights.build_index(flights.load_window(pack, flights.utc_days_for("2026-09-08", pack.timezone), data), pack)
    res = run_search(sp, ev1, ev2, idx, harmonics=(2, 1), c=c, workers=1, log=lambda m: None,
                     points=([TRUTH[0]], [TRUTH[1]], np.array([0.0])))
    assert len(res) == 1 and [res.icao1[0], res.icao2[0]] == PAIR
    assert res.s2[0] > 10.0


@pytest.mark.reference
@pytest.mark.slow
def test_oyster_bay_is_located_through_our_orchestration(recording):
    sp, data = recording
    case = search.CaseInputs(pack=geo.load_pack("ny"), date_local="2026-09-08", duration_s=float(sp.t[-1]),
                             temperature_c=TEMP_C, temperature_source="analyst")
    boxes = [search.Box(id=b[0], t_start=b[1], t_end=b[2], f_lo=b[3], f_hi=b[4], harmonics=b[5]) for b in BOXES]
    out = search.run(case, sp, boxes, data_dir=data)
    assert out["state"] == "located" and out["verdict"]["p"] < 0.1
    assert [out["events"][0]["icao"], out["events"][1]["icao"]] == PAIR
    assert float(haversine_m(out["estimate"]["lat"], out["estimate"]["lon"], *TRUTH)) < 150
    assert out["clip_start_utc"].startswith("2026-09-08T20:17:")
    assert out["estimate"]["regions"] == ["ny"]
