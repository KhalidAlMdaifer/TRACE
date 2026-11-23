"""Settings from the environment (and a `.env` file in the working folder, if there is one).
Read at call time so tests can point at a temp folder."""
from __future__ import annotations

import os
import sys
from pathlib import Path

DOPPLERTRACK_COMMIT = "2d899bbfe1529e2b4351f328969bb37776d57cb4"
BUILTIN_PACKS = Path(__file__).parent / "packs"
MIGRATIONS = Path(__file__).parent / "migrations"
_dotenv_loaded = False


def load_dotenv() -> None:
    """Values already in the environment win over the file."""
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _dotenv_loaded = True
    p = Path(".env")
    if p.is_file():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _get(name: str, default: str | None = None) -> str | None:
    load_dotenv()
    return os.environ.get(name, default)


def _int(name: str, default: int) -> int:
    return int(_get(name) or default)


def exit_with_parent(kill_group: bool = False) -> None:
    """Call once in a helper process (a fit-pool worker, a job's child). If the process that
    started it goes away without stopping it (killed, crashed), a thread notices within a
    couple of seconds and ends this one too. Without it, every restart of the api left its
    pool's processes behind, idle and holding memory."""
    import multiprocessing
    import os
    import signal
    import threading
    import time
    from multiprocessing.connection import wait

    handle = multiprocessing.parent_process()      # set in any process multiprocessing started
    ppid = os.getppid()

    def watch():
        if handle is not None:
            wait([handle.sentinel])                # returns the moment the parent is gone, even if it already was
        else:
            while os.getppid() == ppid:
                time.sleep(2.0)
        if kill_group and hasattr(os, "killpg"):
            try:
                os.killpg(os.getpgrp(), signal.SIGKILL)      # a job's child leads its own group: its pool goes with it
            except OSError:
                pass
        os._exit(0)

    threading.Thread(target=watch, daemon=True, name="exit-with-parent").start()


def data_dir() -> Path:
    return Path(_get("DATA_DIR", "data"))


def db_path() -> Path:
    return data_dir() / "app.db"


def case_dir(case_id: str) -> Path:
    """Where a case's upload and spectrogram live. Built from the id, never from a client string."""
    return data_dir() / "uploads" / case_id


def results_dir(case_id: str) -> Path:
    return data_dir() / "results" / case_id


def doppler_workers() -> int:
    """Workers handed to dopplertrack. The library forks, so anything but Linux gets one."""
    v = _get("DOPPLER_WORKERS")
    if v:
        return max(1, int(v))
    return (os.cpu_count() or 1) if sys.platform.startswith("linux") else 1


def triage_workers() -> int:
    """Detection runs while the analyst is drawing boxes, so it leaves the fit pool its cores."""
    return max(1, doppler_workers() - fit_workers())


def use_dopplertrack_cache(root: Path | None = None) -> Path:
    """Point the library's cache (terrain tiles, type table) inside our data folder unless
    the environment already chose a place."""
    p = Path(os.environ.setdefault("DOPPLERTRACK_CACHE", str((root or data_dir()) / "cache" / "dopplertrack")))
    p.mkdir(parents=True, exist_ok=True)
    return p


def aircraft_types():
    """None means dopplertrack's own table (one small download, then cached). The synthetic
    case brings its own two designators so tests and the demo need no network."""
    if _get("TRACE_SYNTHETIC_TYPES") == "1":
        from .core import synth
        return synth.SyntheticTypes()
    return None


def app_secret() -> str:
    s = _get("APP_SECRET")
    if not s or len(s) < 16:
        raise RuntimeError("APP_SECRET is not set (or is under 16 characters). Copy .env.example to .env and set it.")
    return s


def admin_login() -> tuple[str | None, str | None]:
    return _get("ADMIN_EMAIL"), _get("ADMIN_PASSWORD")


def default_pack() -> str:
    return _get("DEFAULT_PACK", "uae")


def weather_auto() -> bool:
    """Look up the hourly temperature for a case's date and region from Open-Meteo's archive.
    Off means the analyst's figure or the pack's monthly one, and no request leaves."""
    return _get("WEATHER_AUTO", "0") == "1"


def placebo_days() -> int:
    """How many other flight days a search is repeated on as a control. 0: off."""
    return _int("PLACEBO_DAYS", 0)


MAP_TILES_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
MAP_TILES_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'


def map_tiles() -> dict | None:
    """Where the Located result's street map gets its tiles: the analyst's browser loads the
    ones around the estimate from this host. An empty MAP_TILES_URL switches the street map
    off; the result is then drawn on the dot map and no tile host is contacted. `dark` asks
    the page to invert a light map's colours to suit the theme: on for the default
    (OpenStreetMap's standard tiles), off for another host unless MAP_TILES_DARK=1."""
    url = (_get("MAP_TILES_URL", MAP_TILES_URL) or "").strip()
    if not url:
        return None
    default = url == MAP_TILES_URL
    return {"url": url, "attribution": _get("MAP_TILES_ATTRIBUTION") or (MAP_TILES_ATTRIBUTION if default else ""),
            "max_zoom": _int("MAP_TILES_MAX_ZOOM", 19), "dark": _get("MAP_TILES_DARK", "1" if default else "0") == "1"}


def flights_auto() -> bool:
    """Fetch the newest published flight day for the default region once someone is signed
    in (a stream of about 4 GB, in the background). Off means days are fetched only when an
    analyst asks for one."""
    return _get("FLIGHTS_AUTO", "1") == "1"


def flights_auto_retry_s() -> int:
    """The least time between two automatic looks at the archive for one region."""
    return _int("FLIGHTS_AUTO_RETRY_MIN", 60) * 60


def show_dev_packs() -> bool:
    """The synthetic test pack is offered only where this is switched on (development, demos)."""
    return _get("SHOW_DEV_PACKS", "0") == "1"


def max_parallel_jobs() -> int:
    return _int("MAX_PARALLEL_JOBS", 1)


def fit_workers() -> int:
    return _int("FIT_WORKERS", 3)          # one per grid phase of an editor fit


def fit_inline() -> bool:
    return _get("FIT_INLINE", "0") == "1"


def detect_preset() -> str:
    return _get("DETECT_PRESET", "fast")


def job_timeout_s(kind: str) -> int:
    return _int(f"JOB_TIMEOUT_{kind.upper()}_S", {"triage": 3600, "fetch": 3600, "search": 7200}[kind])


def max_upload_bytes() -> int:
    return _int("MAX_UPLOAD_MB", 2048) * 1024 * 1024


def max_duration_s() -> float:
    return float(_get("MAX_DURATION_H", "6")) * 3600.0


def rate_per_hour(what: str) -> int:
    return _int(f"RATE_{what.upper()}_PER_HOUR", {"uploads": 30, "searches": 60, "fetches": 8}[what])


def session_secure() -> bool:
    """Send the session cookie over HTTPS only. Set it wherever the app is reached through
    TLS; leave it off for plain http://localhost, where the cookie would never be sent back."""
    return _get("SESSION_SECURE", "0") == "1"


def login_failures_max() -> int:
    """Failed sign-ins allowed from one address within the window before it is refused."""
    return _int("LOGIN_FAILURES_MAX", 10)


def login_failures_window_s() -> int:
    return _int("LOGIN_FAILURES_WINDOW_MIN", 15) * 60


def retention_days() -> int:
    """Cases older than this many days are deleted by the worker, recording and all. 0, the
    default when it is not set, keeps everything."""
    return _int("RETENTION_DAYS", 0)


def session_max_age_s() -> int:
    return _int("SESSION_HOURS", 12) * 3600
