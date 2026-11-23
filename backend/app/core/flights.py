"""Flight days: which UTC archives a local date needs, where they live on disk, and the index
a search runs on.

Archives are per UTC day; a local calendar day spans two of them. Layout:
`<data>/flights/<pack>/<utc-date>-traces.npz`, written by `dopplertrack fetch --traces` or by
`ensure_day`."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from . import geo


def _as_date(d) -> date:
    return d if isinstance(d, date) else date.fromisoformat(str(d))


def local_day_unix(date_local, tz: str) -> tuple[float, float]:
    """Unix start and end of a local calendar day (23, 24 or 25 hours long)."""
    d, z = _as_date(date_local), ZoneInfo(tz)
    start = datetime.combine(d, time(0), z)
    end = datetime.combine(d + timedelta(days=1), time(0), z)
    return start.timestamp(), end.timestamp()


def utc_days_for(date_local, tz: str, margin_h: float = 1.0) -> list[date]:
    """The UTC days whose archives a local date touches, with a margin on each side for
    flights in progress and propagation."""
    a, b = local_day_unix(date_local, tz)
    a, b = a - margin_h * 3600, b + margin_h * 3600
    first = datetime.fromtimestamp(a, timezone.utc).date()
    last = datetime.fromtimestamp(b - 1e-3, timezone.utc).date()      # an end exactly at midnight belongs to the day before
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def local_ranges_unix(date_local, tz: str, ranges) -> list[tuple[float, float]]:
    """The analyst's time-of-day ranges on a date as unix ranges. None means the whole day.
    A range that wraps midnight ("21:00" to "06:00") is two ranges on the same date."""
    d, z = _as_date(date_local), ZoneInfo(tz)
    if not ranges:
        return [local_day_unix(d, tz)]

    def at(hhmm: str) -> float:
        if hhmm == "24:00":
            return datetime.combine(d + timedelta(days=1), time(0), z).timestamp()
        h, m = hhmm.split(":")
        return datetime.combine(d, time(int(h), int(m)), z).timestamp()

    out = []
    for lo, hi in ranges:
        a, b = at(lo), at(hi)
        if b > a:
            out.append((a, b))
        else:
            out += [(at("00:00"), b), (a, at("24:00"))]
    return sorted((a, b) for a, b in out if b > a)


def traces_path(data_dir, pack_id: str, utc_date) -> Path:
    return Path(data_dir) / "flights" / pack_id / f"{_as_date(utc_date).isoformat()}-traces.npz"


def days_ready(data_dir, pack_id: str, utc_days) -> list[date]:
    return [_as_date(d) for d in utc_days if traces_path(data_dir, pack_id, d).exists()]


def meta_path(data_dir, pack_id: str, utc_date) -> Path:
    return Path(data_dir) / "flights" / pack_id / f"{_as_date(utc_date).isoformat()}-traces.meta.json"


def day_meta(data_dir, pack_id: str, utc_date) -> dict | None:
    """What was recorded when the day was fetched: counts and the integrity filter's tally.
    None for a day that was put on disk some other way (`dopplertrack fetch --traces`)."""
    import json

    p = meta_path(data_dir, pack_id, utc_date)
    try:
        return json.loads(p.read_text()) if p.exists() else None
    except (OSError, ValueError):
        return None


def dropped_pct(data_dir, pack_id: str, utc_days) -> float | None:
    """The share of track points the integrity filter removed over these days, weighted by
    rows. None when no day has a tally, which is not the same as nothing dropped."""
    rows = dropped = 0
    for d in utc_days:
        integ = (day_meta(data_dir, pack_id, d) or {}).get("integrity")
        if integ and integ.get("rows"):
            rows += integ["rows"]; dropped += integ["rows_dropped"]
    return round(100.0 * dropped / rows, 2) if rows else None


ARCHIVE_POD = "planes-readsb-prod-0"


def archive_bytes(utc_date) -> int | None:
    """The size of one UTC day's archive in the public release list, or None when that day
    is not published (yet). One small request, nothing streamed. Raises when the list cannot
    be read."""
    import requests
    from dopplertrack import fetch as dfetch

    y, m, d = _as_date(utc_date).isoformat().split("-")
    r = requests.get(dfetch.API.format(year=y, tag=f"v{y}.{m}.{d}-{ARCHIVE_POD}"), timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return sum(int(a.get("size") or 0) for a in r.json().get("assets", []) if ".tar" in a.get("name", "")) or None


def latest_published(today_utc, back: int = 4) -> tuple[str, int] | None:
    """The newest finished UTC day the archive has, and its size: yesterday, or a day or two
    earlier while yesterday's is still being published. None when none of the last `back`
    days is there."""
    from datetime import timedelta

    for k in range(1, back + 1):
        day = _as_date(today_utc) - timedelta(days=k)
        size = archive_bytes(day)
        if size:
            return day.isoformat(), size
    return None


def ensure_day(pack: geo.Pack, utc_date, data_dir, progress=None, types=None) -> tuple[Path, dict | None]:
    """Fetch one UTC day for the pack if it is not on disk. Streams about 4 GB and takes
    minutes: callers must have the user's go-ahead. The folder is made first, because the
    stream is only written at the end. Every aircraft that touches the pack goes through the
    integrity filter before the library parses it. Returns (traces path, meta)."""
    import json
    from datetime import datetime, timezone

    from dopplertrack import fetch as dfetch
    from dopplertrack.adsb import save_traces

    from . import integrity

    path = traces_path(data_dir, pack.id, utc_date)
    if path.exists():
        return path, day_meta(data_dir, pack.id, utc_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    day = _as_date(utc_date).isoformat()
    stats = integrity.Stats()
    original = dfetch.parse_trace_bytes
    filtered = integrity.filtering_parser(pack.bbox, stats, original)

    def safe(raw, icao=""):                       # one unreadable document must not end a 4 GB stream
        try:
            return filtered(raw, icao)
        except Exception:
            return None

    # the library's streaming loop calls its module-level parser; swap ours in for this fetch.
    # A fetch runs in its own process, so nothing else sees the swap.
    dfetch.parse_trace_bytes = safe
    # The library reports progress per aircraft file, but an archive opens with about a
    # gigabyte of other files. Keep hold of the stream so the bytes read can be reported
    # every few seconds from the start.
    import threading

    stream_class, streams, seen, stop = dfetch._ChainedHTTP, [], [0], threading.Event()

    def opened(urls):
        streams.append(stream_class(urls))
        return streams[-1]

    def file_progress(n_files, n_bytes):
        seen[0] = n_files
        progress(n_files, n_bytes)

    def tick():
        while not stop.wait(3.0):
            if streams:
                progress(seen[0], getattr(streams[-1], "total", 0))

    if progress:
        dfetch._ChainedHTTP = opened
        threading.Thread(target=tick, daemon=True, name="fetch-progress").start()
    try:
        traces = dfetch.fetch_day(day, pack.bbox, progress=file_progress if progress else None)     # jets included; filtered by type on load
    finally:
        stop.set()
        dfetch.parse_trace_bytes, dfetch._ChainedHTTP = original, stream_class
    tmp = path.parent / (path.name + ".part.npz")
    save_traces(traces, tmp)
    tmp.replace(path)
    try:
        kinds = _types(types)
        n_prop = sum(1 for t in traces if kinds.is_prop(t.typ))
    except Exception:                             # the type table could not be had: the count can wait
        n_prop = None
    meta = {"pack": pack.id, "utc_date": day, "n_traces": len(traces), "n_prop": n_prop, "integrity": stats.to_dict(),
            "source": f"adsb.lol globe_history v{day.replace('-', '.')}-planes-readsb-prod-0",
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    meta_path(data_dir, pack.id, utc_date).write_text(json.dumps(meta, indent=1))
    _load_day.cache_clear()
    return path, meta


@lru_cache(maxsize=8)
def _load_day(path: str, mtime: float):
    from dopplertrack.adsb import load_traces

    return load_traces(path)


def _types(types):
    if types is not None:
        return types
    from dopplertrack.adsb import AircraftTypes

    from .. import config
    config.use_dopplertrack_cache()
    return AircraftTypes()


def load_window(pack: geo.Pack, utc_days, data_dir, prop_only: bool = True, types=None) -> list:
    """Traces of every ready UTC day, propeller types only by default. As in the library,
    unknown types are kept as possible propeller aircraft; helicopters pass too. The same
    aircraft on two days is simply two traces."""
    out = []
    for d in days_ready(data_dir, pack.id, utc_days):
        p = traces_path(data_dir, pack.id, d)
        out += _load_day(str(p), p.stat().st_mtime)
    if prop_only and out:
        types = _types(types)
        out = [t for t in out if types.is_prop(t.typ)]
    return out


def build_index(traces, pack: geo.Pack):
    """The index a search runs on, in a frame at the pack centre. Giving the origin matters:
    left to itself the library takes the mean of the traces, which is NaN for an empty day."""
    from dopplertrack.search import DayIndex

    lat0, lon0 = pack.centre
    return DayIndex.build(list(traces), lat0, lon0)


def count(pack: geo.Pack, date_local, ranges, region_ids, data_dir, types=None, custom_bbox=None) -> dict:
    """For the live counter in the When and Where steps: aircraft with an airborne point
    inside the time ranges and the area. `prop` counts propeller-class aircraft."""
    days = utc_days_for(date_local, pack.timezone)
    ready = days_ready(data_dir, pack.id, days)
    windows = local_ranges_unix(date_local, pack.timezone, ranges)
    alltr = load_window(pack, days, data_dir, prop_only=False)
    types = _types(types) if alltr else None
    seen, props = set(), set()
    for tr in alltr:
        m = np.zeros(len(tr.t), bool)
        for a, b in windows:
            m |= (tr.t >= a) & (tr.t <= b)
        m &= ~tr.on_ground
        if not m.any():
            continue
        if (region_ids or custom_bbox) and not geo.in_area(pack, region_ids, custom_bbox, tr.lat[m], tr.lon[m]).any():
            continue
        seen.add(tr.icao)
        if types.is_prop(tr.typ):
            props.add(tr.icao)
    return {"flights": len(seen), "prop": len(props), "days_ready": len(ready) == len(days),
            "days": [{"utc_date": d.isoformat(), "status": "ready" if d in ready else "missing"} for d in days]}
