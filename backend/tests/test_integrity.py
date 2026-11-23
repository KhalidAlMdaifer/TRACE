"""The integrity filter on raw track rows, and the parser it wraps around the library's."""
import gzip
import json

from dopplertrack.adsb import parse_trace_bytes

from app.core import integrity


def row(t, lat, lon, gs=120, flags=0, obj=None, source="adsb_icao", alt=3000):
    return [t, lat, lon, alt, gs, 90.0, flags, 0, obj, source, alt + 50, 0, None, None]


def healthy(n=20, lat=25.0, lon=55.0):
    # 120 kt eastwards, a row every 5 s: about 0.003 degrees of longitude per row
    return [row(5.0 * i, lat, lon + 0.00307 * i, obj={"nic": 9, "rc": 75, "nac_p": 10} if i % 4 == 0 else None) for i in range(n)]


def test_a_healthy_track_passes_untouched():
    st = integrity.Stats()
    rows = healthy()
    assert integrity.filter_rows(rows, st) == rows
    assert st.rows == 20 and st.n_dropped == 0 and st.dropped_pct == 0.0


def test_rows_from_other_sources_are_dropped():
    st = integrity.Stats()
    rows = healthy(12)
    for i, src in zip((2, 5, 7, 9), ("mlat", "tisb_icao", "adsr_icao", "adsb_icao_nt")):
        rows[i][9] = src
    out = integrity.filter_rows(rows, st)
    assert len(out) == 8 and st.dropped["source"] == 4 and all(r[9] == "adsb_icao" for r in out)


def test_stale_positions_are_dropped():
    st = integrity.Stats()
    rows = healthy(10)
    rows[3][6] = 1
    rows[4][6] = 8 | 1                      # geometric altitude, and stale
    rows[5][6] = 8                          # geometric altitude only: fine
    assert len(integrity.filter_rows(rows, st)) == 8 and st.dropped["stale"] == 2


def test_low_accuracy_stretches_are_dropped_until_accuracy_returns():
    st = integrity.Stats()
    rows = [row(5.0 * i, 25.0, 55.0 + 0.00307 * i) for i in range(16)]
    rows[0][8] = {"nic": 9, "rc": 75, "nac_p": 10}
    rows[4][8] = {"nic": 0, "rc": 0, "nac_p": 5}          # jamming: accuracy collapses, and stays so
    rows[8][8] = {"nic": 6, "rc": 1100, "nac_p": 9}       # accuracy back, but containment radius too wide
    rows[12][8] = {"nic": 9, "rc": 75, "nac_p": 10}       # healthy again
    out = integrity.filter_rows(rows, st)
    assert [r[0] for r in out] == [0.0, 5.0, 10.0, 15.0, 60.0, 65.0, 70.0, 75.0]
    assert st.dropped["accuracy"] == 8 and st.dropped_pct == 50.0


def test_an_impossible_jump_is_dropped_but_the_track_goes_on():
    st = integrity.Stats()
    rows = healthy(10)
    rows[5][1] += 0.5                       # 55 km sideways in 5 s
    out = integrity.filter_rows(rows, st)
    assert len(out) == 9 and st.dropped["jump"] == 1 and rows[5] not in out and rows[6] in out
    # a jet at 480 kt covering 1.2 km in 5 s is not a jump
    fast = [row(5.0 * i, 25.0, 55.0 + 0.0123 * i, gs=480) for i in range(8)]
    assert len(integrity.filter_rows(fast, integrity.Stats())) == 8


def test_rows_without_a_position_are_left_for_the_library():
    st = integrity.Stats()
    rows = healthy(4) + [[25.0, None, None, None, None, None, 0, None, None, None, None, None, None, None]]
    assert len(integrity.filter_rows(rows, st)) == 5 and st.rows == 4


def test_old_rows_without_a_source_field_are_kept():
    short = [[5.0 * i, 25.0, 55.0 + 0.00307 * i, 3000, 120] for i in range(5)]
    st = integrity.Stats()
    assert len(integrity.filter_rows(short, st)) == 5 and st.n_dropped == 0


def doc(rows, icao="896001"):
    return {"icao": icao, "r": "A6-TST", "t": "SR22", "desc": "CIRRUS SR-22", "timestamp": 1_795_000_000.0, "trace": rows}


def test_the_wrapped_parser_filters_counts_and_skips_aircraft_outside_the_box():
    st = integrity.Stats()
    parser = integrity.filtering_parser((24.0, 26.0, 54.0, 56.0), st, parse_trace_bytes)
    rows = healthy(20)
    for i in (3, 4, 5):
        rows[i][9] = "mlat"
    tr = parser(gzip.compress(json.dumps(doc(rows)).encode()), "896001")       # archives hold gzipped JSON
    assert tr.icao == "896001" and tr.typ == "SR22" and len(tr.t) == 17
    assert st.to_dict() == {"version": 1, "aircraft": 1, "rows": 20, "dropped": {"source": 3, "stale": 0, "accuracy": 0, "jump": 0},
                            "rows_dropped": 3, "rows_dropped_pct": 15.0}
    # an aircraft that never enters the box is not parsed and not counted
    far = [row(5.0 * i, 40.0, -73.0 + 0.003 * i) for i in range(10)]
    assert parser(json.dumps(doc(far, "a00001")).encode(), "a00001") is None and st.aircraft == 1 and st.rows == 20
    # one whose every row fails still counts, and comes back empty
    bad = [row(5.0 * i, 25.0, 55.0 + 0.003 * i, source="mlat") for i in range(6)]
    assert parser(json.dumps(doc(bad, "896002")).encode(), "896002") is None
    assert st.aircraft == 2 and st.rows == 26 and st.dropped["source"] == 9
    assert parser(b"[1, 2, 3]", "x") is None
