"""Shared fixtures. The synthetic case is built once per session: its fits and searches are
the slow part of the suite, so the tests share them."""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from app.core import synth

os.environ["WEATHER_AUTO"] = "0"           # no test may call the weather archive; test_weather stands in for it
os.environ["PLACEBO_DAYS"] = "0"

TEMP_C = 28.0
WORKERS = min(os.cpu_count() or 1, 8)


def _build_case(tmp, n_flights):
    from dopplertrack.doppler import speed_of_sound

    from app.core import media, spectro

    info = synth.write_case(tmp, temp_c=TEMP_C, n_flights=n_flights, decoys=25)
    x, sr = media.decode_audio(info["wav"])            # through ffmpeg, as an upload would be
    case_dir = tmp / "case"
    sp = spectro.build(x, sr, case_dir)
    return SimpleNamespace(dir=tmp, wav=info["wav"], data_dir=info["data_dir"], case_dir=case_dir, sp=sp,
                           truth=info["truth"], c=float(speed_of_sound(TEMP_C)), n_flights=n_flights)


@pytest.fixture(scope="session")
def case3(tmp_path_factory):
    """Three flyovers at 28 C, with 25 decoy flight pairs in the flight day."""
    return _build_case(tmp_path_factory.mktemp("synth3"), 3)


@pytest.fixture(scope="session")
def case2(tmp_path_factory):
    """Two flyovers only (no flight between them), with 25 decoy pairs."""
    return _build_case(tmp_path_factory.mktemp("synth2"), 2)


@pytest.fixture(scope="session")
def types():
    return synth.SyntheticTypes()


def make_inputs(**over):
    from app.core import geo, search

    base = dict(pack=geo.load_pack("test"), date_local=synth.DATE_LOCAL, duration_s=float(synth.DURATION_S),
                temperature_c=TEMP_C, temperature_source="analyst")
    base.update(over)
    return search.CaseInputs(**base)


def boxes_for(n):
    from app.core import search

    return [search.Box(id=f"box{i + 1}", t_start=b[0], t_end=b[1], f_lo=b[2], f_hi=b[3], harmonics=1)
            for i, b in enumerate(synth.BEND_BOXES[:n])]


@pytest.fixture(scope="session")
def raw3(case3, types):
    """The heavy part of a three-flyover search, shared by several tests."""
    from app.core import search, spectro

    return search.compute(make_inputs(), case3.sp, boxes_for(3), data_dir=case3.data_dir, types=types,
                          workers=WORKERS, burst=spectro.load_burst(case3.case_dir))


@pytest.fixture(scope="session")
def out3(case3, raw3):
    from app.core import search

    return search.conclude(make_inputs(), case3.sp, raw3)
