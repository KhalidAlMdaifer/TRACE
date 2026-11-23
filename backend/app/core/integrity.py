"""The integrity filter on flight tracks (docs/04-data.md, section 1).

ADS-B positions come from each aircraft's own GPS, and GPS jamming and spoofing have been
reported around the Gulf. A bad track gives a wrong modelled curve, and dopplertrack does not
filter for it: its parser ignores the position source and the integrity fields. So a day's
archive goes through this filter before the library parses it, and the share of track points
it removed is kept with the day and shown with every result.

The filter works on a readsb `trace_full` document's rows (14-element arrays):
  0 seconds after the document's timestamp   1, 2 latitude, longitude   4 ground speed, knots
  6 flags (bit 1: position stale)   8 aircraft object or null (nic, rc, nac_p, ...)
  9 position source ("adsb_icao", "mlat", "tisb_icao", ...)

Thresholds are starting values."""
from __future__ import annotations

import gzip
import json
import math
from dataclasses import dataclass, field

GOOD_SOURCES = {"adsb_icao"}       # not mlat, tisb_*, adsr_*, adsc, other, or adsb_icao_nt (no transponder)
MIN_NAC_P = 8                      # navigation accuracy category for position: 8 is under 93 m
MAX_RC_M = 200.0                   # radius of containment
KT = 0.514444
JUMP_FACTOR, JUMP_SLACK_MPS, JUMP_ABS_MPS = 2.5, 60.0, 450.0
REASONS = ("source", "stale", "accuracy", "jump")
VERSION = 1


@dataclass
class Stats:
    aircraft: int = 0
    rows: int = 0                                  # positioned rows of aircraft that touch the box
    dropped: dict = field(default_factory=lambda: {r: 0 for r in REASONS})

    @property
    def n_dropped(self) -> int:
        return sum(self.dropped.values())

    @property
    def dropped_pct(self) -> float | None:
        return round(100.0 * self.n_dropped / self.rows, 2) if self.rows else None

    def to_dict(self) -> dict:
        return {"version": VERSION, "aircraft": self.aircraft, "rows": self.rows, "dropped": dict(self.dropped),
                "rows_dropped": self.n_dropped, "rows_dropped_pct": self.dropped_pct}


def _metres(lat1, lon1, lat2, lon2) -> float:
    k = math.cos(math.radians((lat1 + lat2) / 2))
    return 111_320.0 * math.hypot(lat2 - lat1, (lon2 - lon1) * k)


def filter_rows(rows: list, stats: Stats | None = None) -> list:
    """The rows that pass, in order. Rows with no position are passed through untouched (the
    library skips them itself) and are not counted."""
    stats = stats if stats is not None else Stats()
    out = []
    nac_p = rc = None                              # carried forward from the last aircraft object seen
    last = None                                    # the last kept positioned row: (t, lat, lon)
    for r in rows:
        if len(r) < 3 or r[1] is None or r[2] is None:
            out.append(r)
            continue
        stats.rows += 1
        obj = r[8] if len(r) > 8 and isinstance(r[8], dict) else None
        if obj:
            nac_p = obj.get("nac_p", nac_p)
            rc = obj.get("rc", rc)
        source = r[9] if len(r) > 9 else None
        flags = r[6] if len(r) > 6 and isinstance(r[6], int) else 0
        if source is not None and source not in GOOD_SOURCES:
            stats.dropped["source"] += 1
            continue
        if flags & 1:
            stats.dropped["stale"] += 1
            continue
        if (isinstance(nac_p, (int, float)) and nac_p < MIN_NAC_P) or (isinstance(rc, (int, float)) and rc > MAX_RC_M):
            stats.dropped["accuracy"] += 1
            continue
        if last is not None:
            dt = r[0] - last[0]
            dist = _metres(last[1], last[2], r[1], r[2])
            gs = r[4] * KT if len(r) > 4 and isinstance(r[4], (int, float)) else None
            limit = JUMP_FACTOR * gs + JUMP_SLACK_MPS if gs is not None else JUMP_ABS_MPS
            # an impossible jump: far faster than the aircraft says it is going. Very short
            # steps are exempt, where a few metres of noise already look like any speed.
            if dt > 0 and dist > 500.0 and dist / dt > max(limit, 120.0):
                stats.dropped["jump"] += 1
                continue
        out.append(r)
        last = (r[0], r[1], r[2])
    return out


def filtering_parser(bbox, stats: Stats, parse):
    """A stand-in for dopplertrack's `parse_trace_bytes(raw, fallback_icao)` that filters first.

    Most of a day's 70,000 aircraft never touch the region, so the box is checked on the raw
    rows before anything else; only the ones inside are filtered and handed to the library's
    own parser (`parse`). Counting is over those aircraft only."""
    lat0, lat1, lon0, lon1 = bbox

    def parser(raw: bytes, fallback_icao: str = ""):
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        doc = json.loads(raw)
        if not isinstance(doc, dict):
            return None
        rows = doc.get("trace") or []
        if not any(len(r) > 2 and r[1] is not None and r[2] is not None and lat0 <= r[1] <= lat1 and lon0 <= r[2] <= lon1 for r in rows):
            return None
        stats.aircraft += 1
        doc["trace"] = filter_rows(rows, stats)
        return parse(json.dumps(doc).encode(), fallback_icao)

    return parser
