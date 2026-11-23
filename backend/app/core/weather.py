"""Air temperature for the speed of sound. Every fit and search needs one: a 25 C error
moved a synthetic answer 7.7 km.

Order of preference: the analyst's figure; an automatic lookup of the hourly temperature for
the region and time (Open-Meteo's historical archive, when switched on); the pack's monthly
figure. The lookup sends the pack's weather point and a date to the archive and nothing else."""
from __future__ import annotations

import json
import time as _time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# Sound travels down from the aircraft through cooler air, so use a layer mean rather than
# the surface value: about 1 km of standard lapse, halved. A starting rule.
LAYER_OFFSET_C = -3.0
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"
# Within about 5 C the result holds (docs/03-method-and-evidence.md). A window whose hours
# differ by more than this, and that is longer than six hours, is searched at both ends.
SPREAD_C, WIDE_WINDOW_H = 5.0, 6.0
_failed: dict[str, float] = {}             # day key -> when the lookup last failed, so a dead network is not asked on every request
RETRY_S = 600.0


def speed_of_sound(temp_c: float) -> float:
    """m/s in dry air; the same formula as dopplertrack.doppler.speed_of_sound, repeated
    here so the api process can use it without loading the library."""
    return 331.3 * (1.0 + float(temp_c) / 273.15) ** 0.5


def temperature(pack, t_unix_range: tuple[float, float]) -> tuple[float, str]:
    """The last fallback: (effective temperature in C, source) from the pack's monthly figure."""
    mid = (t_unix_range[0] + t_unix_range[1]) / 2
    month = datetime.fromtimestamp(mid, ZoneInfo(pack.timezone)).strftime("%m")
    if month not in pack.climate_c:
        raise LookupError(f"pack {pack.id} has no climate figure for month {month}; give a temperature")
    return float(pack.climate_c[month]) + LAYER_OFFSET_C, "climate_monthly"


def _http_hourly(lat: float, lon: float, day: str) -> list[float]:
    import requests

    r = requests.get(ARCHIVE_URL, timeout=8, params={"latitude": lat, "longitude": lon, "start_date": day, "end_date": day,
                                                     "hourly": "temperature_2m", "timezone": "GMT"})
    r.raise_for_status()
    return r.json()["hourly"]["temperature_2m"]


def hourly_utc_day(pack, day: date, data_dir=None, fetch=None) -> list[float] | None:
    """The 24 hourly surface temperatures of one UTC day at the pack's weather point, from the
    cache or the archive. None when the pack has no point, the lookup is off or it fails."""
    from .. import config

    point = pack.meta.get("weather_point")
    if not point:
        return None
    cache = Path(data_dir or config.data_dir()) / "cache" / "weather" / pack.id / f"{day.isoformat()}.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text())["temperature_2m"]
        except (OSError, ValueError, KeyError):
            pass
    if fetch is None:
        if not config.weather_auto():
            return None
        fetch = _http_hourly
    key = f"{pack.id}/{day.isoformat()}"
    if _time.time() - _failed.get(key, 0.0) < RETRY_S or day >= datetime.now(timezone.utc).date():
        return None
    try:
        temps = fetch(float(point[0]), float(point[1]), day.isoformat())
        if len(temps) != 24 or any(t is None for t in temps):       # the archive has not caught up with this day yet
            raise ValueError("incomplete day")
    except Exception:
        _failed[key] = _time.time()
        return None
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"point": point, "utc_date": day.isoformat(), "temperature_2m": temps, "source": ATTRIBUTION}))
    return temps


def window(pack, date_local, time_ranges, data_dir=None, fetch=None) -> dict | None:
    """The surface temperatures over the case's time window: mean, min, max and how long the
    window is. None when they cannot be had."""
    from . import flights

    ranges = flights.local_ranges_unix(date_local, pack.timezone, time_ranges)
    temps: list[float] = []
    cache: dict[date, list[float] | None] = {}
    for a, b in ranges:
        h = int(a // 3600) * 3600
        while h < b:
            d = datetime.fromtimestamp(h, timezone.utc)
            if d.date() not in cache:
                cache[d.date()] = hourly_utc_day(pack, d.date(), data_dir, fetch)
            day = cache[d.date()]
            if day is None:
                return None
            temps.append(float(day[d.hour]))
            h += 3600
    if not temps:
        return None
    return {"mean_c": round(sum(temps) / len(temps), 1), "min_c": min(temps), "max_c": max(temps),
            "hours": sum(b - a for a, b in ranges) / 3600.0, "point": pack.meta.get("weather_point"), "attribution": ATTRIBUTION}


def for_case(pack, date_local, time_ranges, temperature_c, temperature_source=None, data_dir=None, fetch=None) -> tuple[float, str]:
    """The temperature a case uses: the analyst's if given; else the archive's mean over the
    case's date and time window, less the layer offset; else the pack's monthly figure
    (today's month while the date is still unknown)."""
    from . import flights

    if temperature_c is not None:
        return float(temperature_c), temperature_source or "analyst"
    if date_local:
        w = window(pack, date_local, time_ranges, data_dir, fetch)
        if w is not None:
            return round(w["mean_c"] + LAYER_OFFSET_C, 1), "auto"
        win = flights.local_ranges_unix(date_local, pack.timezone, time_ranges)
        return temperature(pack, (win[0][0], win[-1][1]))
    return temperature(pack, (_time.time(), _time.time()))


def search_temperatures(pack, date_local, time_ranges, temperature_c, temperature_source=None, data_dir=None, fetch=None) -> tuple[list[float], str, dict | None]:
    """The temperatures a search runs at: one, or two when the temperature is automatic and the
    time window is both long and varied (its coolest and warmest hours, less the layer offset).
    Returns (temperatures, source, the window's figures)."""
    t, source = for_case(pack, date_local, time_ranges, temperature_c, temperature_source, data_dir, fetch)
    if source != "auto":
        return [t], source, None
    w = window(pack, date_local, time_ranges, data_dir, fetch)
    if w and w["hours"] > WIDE_WINDOW_H and w["max_c"] - w["min_c"] > SPREAD_C:
        return [round(w["min_c"] + LAYER_OFFSET_C, 1), round(w["max_c"] + LAYER_OFFSET_C, 1)], source, w
    return [t], source, w
