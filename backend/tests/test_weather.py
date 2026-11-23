"""Automatic temperature: the archive is stood in for; no request leaves the machine."""
import dataclasses
from datetime import date

import pytest

from app.core import geo, weather

# a desert day: 20 C before dawn, 34 C mid-afternoon (UTC hours; Dubai is UTC+4)
DAY = [22, 21, 20, 21, 24, 27, 30, 32, 33, 34, 34, 33, 31, 29, 27, 26, 25, 24, 24, 23, 23, 22, 22, 22]


@pytest.fixture(autouse=True)
def forget_failures():
    weather._failed.clear()            # a failed lookup is not retried for ten minutes; tests must not inherit one
    yield
    weather._failed.clear()


@pytest.fixture
def pack():
    p = geo.load_pack("test")
    return dataclasses.replace(p, meta={**p.meta, "weather_point": [25.05, 55.25]})


@pytest.fixture
def archive():
    calls = []

    def fetch(lat, lon, day):
        calls.append((lat, lon, day))
        return [float(t) for t in DAY]

    fetch.calls = calls
    return fetch


def test_the_window_mean_less_the_layer_offset(pack, archive, tmp_path):
    # 12:00 to 17:00 in Dubai is 08:00 to 13:00 UTC: 33, 34, 34, 33, 31
    t, source = weather.for_case(pack, "2026-11-14", [["12:00", "17:00"]], None, data_dir=tmp_path, fetch=archive)
    assert (t, source) == (30.0, "auto")
    w = weather.window(pack, "2026-11-14", [["12:00", "17:00"]], tmp_path, archive)
    assert (w["mean_c"], w["min_c"], w["max_c"], w["hours"]) == (33.0, 31.0, 34.0, 5.0) and "Open-Meteo" in w["attribution"]
    assert archive.calls == [(25.05, 55.25, "2026-11-14")]                 # one request, then the cache on disk
    assert (tmp_path / "cache" / "weather" / "test" / "2026-11-14.json").exists()


def test_the_analysts_figure_always_wins(pack, archive, tmp_path):
    assert weather.for_case(pack, "2026-11-14", None, 41.5, data_dir=tmp_path, fetch=archive) == (41.5, "analyst")
    assert archive.calls == []


def test_a_whole_local_day_spans_two_utc_days(pack, archive, tmp_path):
    w = weather.window(pack, "2026-11-14", None, tmp_path, archive)
    assert w["hours"] == 24.0 and sorted(c[2] for c in archive.calls) == ["2026-11-13", "2026-11-14"]


def test_it_falls_back_to_the_monthly_figure(pack, tmp_path, monkeypatch):
    def down(lat, lon, day):
        raise OSError("network unreachable")

    assert weather.for_case(pack, "2026-11-14", None, None, data_dir=tmp_path, fetch=down) == (28.0, "climate_monthly")
    # a pack with no weather point never asks; nor does anything when the lookup is switched off
    assert weather.for_case(geo.load_pack("test"), "2026-11-14", None, None, data_dir=tmp_path) == (28.0, "climate_monthly")
    monkeypatch.setenv("WEATHER_AUTO", "0")
    assert weather.hourly_utc_day(pack, date(2026, 11, 10), tmp_path) is None
    # a day the archive has not finished is not cached as if it were whole
    assert weather.hourly_utc_day(pack, date(2026, 11, 11), tmp_path, lambda la, lo, d: [20.0] * 12 + [None] * 12) is None
    assert not (tmp_path / "cache" / "weather" / "test" / "2026-11-11.json").exists()


def test_a_long_varied_window_is_searched_at_both_ends(pack, archive, tmp_path):
    temps, source, w = weather.search_temperatures(pack, "2026-11-14", None, None, data_dir=tmp_path, fetch=archive)
    assert source == "auto" and temps == [17.0, 31.0]                       # 20 and 34 C at the surface, less 3
    # a short window, or an analyst's figure, is one temperature
    assert weather.search_temperatures(pack, "2026-11-14", [["12:00", "17:00"]], None, data_dir=tmp_path, fetch=archive)[0] == [30.0]
    assert weather.search_temperatures(pack, "2026-11-14", None, 28.0, data_dir=tmp_path, fetch=archive)[:2] == ([28.0], "analyst")
