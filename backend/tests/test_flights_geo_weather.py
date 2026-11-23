from datetime import date

import numpy as np
import pytest

from app.core import flights, geo, synth, weather


# --- time ---------------------------------------------------------------------------------

def test_utc_days():
    d = date.fromisoformat
    # the UAE is UTC+4 all year: a local day starts at 20:00 UTC the day before
    assert flights.utc_days_for("2026-11-14", "Asia/Dubai") == [d("2026-11-13"), d("2026-11-14")]
    # New York in summer (UTC-4): 04:00 UTC to 04:00 UTC the next day
    assert flights.utc_days_for("2026-09-08", "America/New_York") == [d("2026-09-08"), d("2026-09-09")]
    # daylight saving ends on 2026-11-01: a 25 hour local day, 04:00 UTC to 05:00 UTC
    assert flights.utc_days_for("2026-11-01", "America/New_York") == [d("2026-11-01"), d("2026-11-02")]
    # with no margin the UTC day itself is enough for a UTC pack
    assert flights.utc_days_for("2026-11-14", "UTC", margin_h=0) == [d("2026-11-14")]
    assert flights.utc_days_for("2026-11-14", "UTC") == [d("2026-11-13"), d("2026-11-14"), d("2026-11-15")]


def test_local_ranges_follow_daylight_saving():
    whole = flights.local_ranges_unix("2026-11-01", "America/New_York", None)
    assert whole[0][1] - whole[0][0] == 25 * 3600
    night = flights.local_ranges_unix("2026-11-14", "Asia/Dubai", [["21:00", "06:00"]])
    # 21:00 to 06:00 on one date is two ranges: 00:00 to 06:00 and 21:00 to 24:00
    assert len(night) == 2 and sum(b - a for a, b in night) == 9 * 3600
    noon = flights.local_ranges_unix("2026-11-14", "Asia/Dubai", [["12:00", "17:00"]])
    assert noon == [(1794643200.0, 1794661200.0)]      # 08:00 to 13:00 UTC


# --- flight days ---------------------------------------------------------------------------

def test_load_window_reads_ready_days_and_drops_jets(case3, types, tmp_path):
    import dataclasses

    from dopplertrack.adsb import save_traces

    pack = geo.load_pack("test")
    days = flights.utc_days_for(synth.DATE_LOCAL, pack.timezone)
    assert flights.days_ready(case3.data_dir, pack.id, days) == [date.fromisoformat(synth.UTC_DAY)]
    traces = flights.load_window(pack, days, case3.data_dir, types=types)
    assert len(traces) == 3 + 150                      # three flights and 25 decoy pairs for each pair of them
    idx = flights.build_index(traces, pack)
    assert len(idx) == len(traces) and idx.lat0 == pytest.approx(25.1) and idx.lon0 == pytest.approx(55.3)
    # a day with a jet and an aircraft of unknown type: the jet goes, the unknown stays
    extra = [traces[0], dataclasses.replace(traces[1], icao="jet001", typ="A320"), dataclasses.replace(traces[2], icao="unk001", typ=None)]
    path = flights.traces_path(tmp_path, pack.id, "2026-11-13")
    path.parent.mkdir(parents=True)
    save_traces(extra, path)
    assert [t.icao for t in flights.load_window(pack, days, tmp_path, types=types)] == ["aaa001", "unk001"]
    assert len(flights.load_window(pack, days, tmp_path, prop_only=False)) == 3


def test_the_newest_published_day_is_found_without_streaming(monkeypatch):
    """One small request per day to the archive's release list: is it there, and how big."""
    import requests

    asked = []

    class Reply:
        def __init__(self, status, assets=()):
            self.status_code, self._assets = status, list(assets)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(f"{self.status_code} Server Error")

        def json(self):
            return {"assets": self._assets}

    tar = lambda name, size: {"name": name, "size": size}
    releases = {"v2026.11.20-planes-readsb-prod-0": Reply(200, [tar("x.tar.aa", 2_000_000_000), tar("x.tar.ab", 1_600_000_000), tar("notes.txt", 10)]),
                "v2026.11.21-planes-readsb-prod-0": Reply(200, []),            # the release exists, its archive is not uploaded yet
                "v2026.11.19-planes-readsb-prod-0": Reply(500)}

    def get(url, timeout=None):
        asked.append(url)
        return releases.get(url.rsplit("/", 1)[1], Reply(404))

    monkeypatch.setattr(requests, "get", get)
    assert flights.archive_bytes("2026-11-20") == 3_600_000_000 and "globe_history_2026/releases/tags/v2026.11.20" in asked[0]
    assert flights.archive_bytes("2026-11-21") is None and flights.archive_bytes("2026-11-22") is None
    with pytest.raises(requests.HTTPError):
        flights.archive_bytes("2026-11-19")
    # today is never asked for; yesterday first, then back
    del asked[:]
    assert flights.latest_published(date(2026, 11, 23)) == ("2026-11-20", 3_600_000_000)
    assert [u.rsplit("/v", 1)[1][:10] for u in asked] == ["2026.11.22", "2026.11.21", "2026.11.20"]
    assert flights.latest_published(date(2026, 11, 27), back=3) is None


def test_ensure_day_streams_through_the_integrity_filter(tmp_path, monkeypatch, types):
    """A day's archive is a tar of one JSON document per aircraft. Stand in for the network
    with a small tar, and let the library's own streaming loop and our filter do the rest."""
    import gzip
    import io
    import json
    import tarfile

    from dopplertrack import fetch as dfetch

    def row(t, lat, lon, source="adsb_icao"):
        return [t, lat, lon, 3000, 120, 90.0, 0, 0, None, source, 3050, 0, None, None]

    def doc(icao, typ, rows):
        return {"icao": icao, "r": None, "t": typ, "desc": "", "timestamp": 1_794_614_400.0, "trace": rows}

    inside = [row(5.0 * i, 25.05, 55.0 + 0.003 * i) for i in range(40)]
    spoofed = [row(5.0 * i, 25.10, 55.0 + 0.003 * i, "mlat" if 10 <= i < 20 else "adsb_icao") for i in range(40)]
    outside = [row(5.0 * i, 40.0, -73.0 + 0.003 * i) for i in range(40)]
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for icao, typ, rows in (("aaa111", "SR22", inside), ("bbb222", "C172", spoofed), ("ccc333", "A320", outside)):
            raw = gzip.compress(json.dumps(doc(icao, typ, rows)).encode())
            info = tarfile.TarInfo(f"traces/{icao[-2:]}/trace_full_{icao}.json"); info.size = len(raw)
            tf.addfile(info, io.BytesIO(raw))
        junk = b"not json at all"
        info = tarfile.TarInfo("traces/zz/trace_full_dddzzz.json"); info.size = len(junk)
        tf.addfile(info, io.BytesIO(junk))

    class FakeStream(io.BytesIO):
        total = 0

    asked = []
    monkeypatch.setattr(dfetch, "release_asset_urls", lambda date, pod="x": asked.append(date) or ["https://example.invalid/day.tar"])
    monkeypatch.setattr(dfetch, "_ChainedHTTP", lambda urls: FakeStream(buf.getvalue()))
    pack = geo.load_pack("test")
    original = dfetch.parse_trace_bytes
    fake_stream = dfetch._ChainedHTTP
    path, meta = flights.ensure_day(pack, "2026-11-13", tmp_path, types=types, progress=lambda n_files, n_bytes: None)
    assert asked == ["2026-11-13"] and dfetch.parse_trace_bytes is original           # the library's parser is put back
    assert dfetch._ChainedHTTP is fake_stream                                         # and so is its stream class
    assert path == flights.traces_path(tmp_path, "test", "2026-11-13") and path.exists()
    assert meta["n_traces"] == 2 and meta["n_prop"] == 2 and "adsb.lol" in meta["source"]
    assert meta["integrity"] == {"version": 1, "aircraft": 2, "rows": 80, "dropped": {"source": 10, "stale": 0, "accuracy": 0, "jump": 0},
                                 "rows_dropped": 10, "rows_dropped_pct": 12.5}
    traces = flights.load_window(pack, ["2026-11-13"], tmp_path, types=types)
    assert sorted((t.icao, len(t.t)) for t in traces) == [("aaa111", 40), ("bbb222", 30)]
    assert flights.day_meta(tmp_path, "test", "2026-11-13") == meta and flights.dropped_pct(tmp_path, "test", ["2026-11-13"]) == 12.5
    assert flights.dropped_pct(tmp_path, "test", ["2026-11-12"]) is None                 # not measured is not zero
    # a second call does not fetch again
    assert flights.ensure_day(pack, "2026-11-13", tmp_path, types=types)[0] == path and asked == ["2026-11-13"]
    c = flights.count(pack, "2026-11-14", None, None, tmp_path, types=types)
    assert c["days"] == [{"utc_date": "2026-11-13", "status": "ready"}, {"utc_date": "2026-11-14", "status": "missing"}]


def test_build_index_survives_an_empty_day():
    idx = flights.build_index([], geo.load_pack("test"))
    assert len(idx) == 0 and np.isfinite(idx.lat0)


def test_count_flights_in_window(case3, types):
    pack = geo.load_pack("test")
    whole = flights.count(pack, synth.DATE_LOCAL, None, None, case3.data_dir, types=types)
    assert (whole["flights"], whole["prop"], whole["days_ready"]) == (153, 153, False)      # the day before is not on disk
    assert whole["days"] == [{"utc_date": "2026-11-13", "status": "missing"}, {"utc_date": "2026-11-14", "status": "ready"}]
    home = flights.count(pack, synth.DATE_LOCAL, [["13:00", "15:00"]], ["home"], case3.data_dir, types=types)
    assert 3 <= home["prop"] < 153
    assert flights.count(pack, synth.DATE_LOCAL, [["01:00", "02:00"]], None, case3.data_dir, types=types)["prop"] == 0


# --- packs ---------------------------------------------------------------------------------

def test_pack_loads_with_two_square_regions():
    pack = geo.load_pack("test")
    assert pack.timezone == "Asia/Dubai" and [r.id for r in pack.regions] == ["home", "away"]
    with pytest.raises(geo.PackNotFound):
        geo.load_pack("../etc")


def test_in_regions_is_a_polygon_test():
    pack = geo.load_pack("test")
    lat = np.array([25.05, 25.05, 25.05, 26.0])
    lon = np.array([55.25, 55.65, 55.45, 55.25])
    assert geo.in_regions(pack, ["home"], lat, lon).tolist() == [True, False, False, False]
    assert geo.in_regions(pack, ["home", "away"], lat, lon).tolist() == [True, True, False, False]
    assert geo.in_regions(pack, None, lat, lon).all()             # no area given: no constraint
    assert geo.regions_at(pack, 25.05, 55.65) == ["away"]


def test_polygon_holes_and_multipolygons():
    outer = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    hole = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]
    island = [[[20, 20], [21, 20], [21, 21], [20, 21], [20, 20]]]
    region = geo.Region("r", "r", None, geo.polygons_of({"type": "MultiPolygon", "coordinates": [[outer, hole], island]}))
    lon = np.array([1.0, 5.0, 20.5, 15.0])
    lat = np.array([1.0, 5.0, 20.5, 15.0])
    assert region.contains(lat, lon).tolist() == [True, False, True, False]


def test_custom_bbox_constraint():
    assert geo.in_bbox([24.9, 25.2, 55.1, 55.4], np.array([25.05, 25.3]), np.array([55.25, 55.25])).tolist() == [True, False]


def test_dot_grid_cells_lie_in_regions():
    pack = geo.load_pack("test")
    cells = geo.dot_grid(pack, pitch_m=5000)
    assert len(cells) > 20 and {c[2] for c in cells} == {"home", "away"}
    lat = np.array([c[0] for c in cells]); lon = np.array([c[1] for c in cells])
    assert geo.in_regions(pack, ["home", "away"], lat, lon).all()


# --- the UAE pack: real boundaries (OpenStreetMap via geoBoundaries, ODbL) -------------------

UAE_PLACES = [                       # approximate city centres, as scripts/coverage_report.py uses them
    ("abu_dhabi", 24.4539, 54.3773), ("abu_dhabi", 24.2075, 55.7447), ("dubai", 25.2048, 55.2708), ("dubai", 24.8960, 55.1614),
    ("sharjah", 25.3463, 55.4209), ("ajman", 25.4052, 55.5136), ("umm_al_quwain", 25.5647, 55.5552),
    ("ras_al_khaimah", 25.7895, 55.9432), ("fujairah", 25.1288, 56.3265),
]


def test_uae_pack_has_the_seven_emirates_and_three_abu_dhabi_regions():
    pack = geo.load_pack("uae")
    tops = [r.id for r in pack.regions if r.parent is None]
    assert tops == ["abu_dhabi", "dubai", "sharjah", "ajman", "umm_al_quwain", "ras_al_khaimah", "fujairah"]
    assert [r.id for r in pack.regions if r.parent == "abu_dhabi"] == ["abu_dhabi_region", "al_ain_region", "al_dhafra_region"]
    assert pack.timezone == "Asia/Dubai" and pack.bbox == (22.6, 26.1, 51.5, 56.4) and pack.short_name == "UAE"
    assert "OpenStreetMap" in pack.meta["boundaries"]["source"] and "Open Database License" in pack.meta["boundaries"]["licence"]


def test_uae_places_fall_in_their_emirates():
    pack = geo.load_pack("uae")
    for emirate, lat, lon in UAE_PLACES:
        tops = [r for r in geo.regions_at(pack, lat, lon) if pack.region(r).parent is None]
        assert tops == [emirate], (emirate, lat, lon, tops)
    # exclaves need polygons, not boxes: Hatta is Dubai's, though it lies east of Sharjah's and Ajman's land
    assert "dubai" in geo.regions_at(pack, 24.80, 56.125)
    # the open sea, and a point across the border, belong to no emirate
    assert geo.regions_at(pack, 25.6, 54.5) == [] and geo.regions_at(pack, 23.6, 58.4) == []
    # Abu Dhabi's sub-areas: the city, Al Ain, and Madinat Zayed in Al Dhafra
    assert "abu_dhabi_region" in geo.regions_at(pack, 24.4539, 54.3773)
    assert "al_ain_region" in geo.regions_at(pack, 24.2075, 55.7447)
    assert "al_dhafra_region" in geo.regions_at(pack, 23.68, 53.70)
    # a sub-area never reaches outside its emirate
    assert geo.in_regions(pack, ["al_dhafra_region"], np.array([24.9]), np.array([52.6])).tolist() == [False]


def test_uae_dot_grid_and_month_fallback():
    pack = geo.load_pack("uae")
    cells = geo.dot_grid(pack, pitch_m=7000)
    owners = {c[2] for c in cells}
    assert 1200 < len(cells) < 2600
    assert {"dubai", "sharjah", "fujairah", "ras_al_khaimah", "abu_dhabi_region", "al_ain_region", "al_dhafra_region"} <= owners
    t, source = weather.temperature(pack, (synth.T0_UNIX, synth.T0_UNIX + 1800))     # November
    assert t == pytest.approx(22.0) and source == "climate_monthly"


# --- temperature ---------------------------------------------------------------------------

def test_weather_falls_back_to_the_monthly_figure():
    pack = geo.load_pack("test")
    t, source = weather.temperature(pack, (synth.T0_UNIX, synth.T0_UNIX + 1800))
    assert t == pytest.approx(28.0) and source == "climate_monthly"      # 31 C at the surface, less 3 C


def test_speed_of_sound_matches_the_library():
    from dopplertrack.doppler import speed_of_sound

    for t in (-10.0, 15.0, 28.0, 45.0):
        assert weather.speed_of_sound(t) == pytest.approx(float(speed_of_sound(t)), rel=1e-12)
