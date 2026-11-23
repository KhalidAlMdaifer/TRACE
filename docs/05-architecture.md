# Architecture

Design for the MVP. Function signatures are a contract between modules; adjust them when
the code teaches you something, and record the change in `09-risks-and-open-questions.md`.

## 1. Processes

```
browser  <--HTTP/SSE-->  api (FastAPI, uvicorn)  <--->  SQLite (data/app.db) + files (data/)
                                                           ^
                         worker (python -m app.worker) ----+
                             spawns one child process per job
```

- **api** serves HTTP, auth, uploads, and the event stream. Its own process never imports dopplertrack and never does more than a few milliseconds of numpy work per request. It owns one small process pool, the **fit pool** (below).
- **worker** polls the `jobs` table, and runs each job in a **fresh child process** (`multiprocessing.get_context("spawn")`). The child sets the BLAS thread variables to 1 before importing numpy, does the work, writes progress rows to `job_events`, and exits.
- Why a child per job: dopplertrack keeps search state in a module global and forks its pool from it, so two searches must never share a process, and a crash or a cancel must not take the worker down.
- **Fit pool.** The flyover editor needs a fitted curve about two seconds after the analyst releases a box. That must not queue behind a triage or search job that runs for minutes, and it is too slow for the event loop. The api keeps a `ProcessPoolExecutor(FIT_WORKERS, mp_context=spawn)` (default 2) whose workers import dopplertrack once and stay warm; `POST` and `PATCH` on events `await loop.run_in_executor(pool, core.events.preview_from_disk, ...)`. A fit touches no module-global state, so reusing those processes is safe. On `BrokenProcessPool`, rebuild the pool and return 503. `FIT_INLINE=1` runs previews in-process for tests. Set the four BLAS thread variables to 1 in the api's own environment at startup so the pool's processes inherit them.
- **Two kinds of fit.** The editor shows the quick preview (about 2 s). The search job refits every confirmed box with the full `fit_event` (5 to 19 s each) at the temperature the search uses, and searches with those. So an editor fit is never what gets searched, a late temperature change needs no special handling, and the result screen draws the search's own fits.
- Job kinds and limits: `triage` (decode, spectrogram, detection), `fetch` (a flight day), `search`. `MAX_PARALLEL_JOBS` (default 1) children at once; each kind has a wall-clock limit (`JOB_TIMEOUT_TRIAGE_S` 3600, `JOB_TIMEOUT_FETCH_S` 3600, `JOB_TIMEOUT_SEARCH_S` 7200) after which the worker kills the child and marks the job failed. The queue is ordered search, then fetch, then triage, oldest first within a kind. `POST /search` first cancels a triage job still detecting on the same case (the analyst has confirmed their boxes, so the remaining proposals are not needed) and marks it done with `"truncated": true`; otherwise, with one job at a time, the search would sit behind it for minutes. A running job of another case is never pre-empted.
- `DOPPLER_WORKERS` is passed to dopplertrack as `workers`: default 1 on macOS and Windows, cores on Linux. Triage detection uses `DOPPLER_WORKERS - FIT_WORKERS` (at least 1) and every job child runs at `nice 10`, so an editor fit never waits for a core behind a job. Each child is its own session, and the worker stops it with `killpg` so dopplertrack's forked pool goes with it.
- The api streams progress by tailing `job_events` (poll every 300 ms). No in-memory queue, so a restart of either process loses nothing.
- Docker Compose: `api`, `worker`, `frontend`. Linux containers also solve the fork limitation on Windows.

## 2. Repository layout

```
pyproject.toml            uv project at the root, package `app` in backend/
backend/app/
  config.py               settings from environment
  db.py                   SQLite connection, migrations (plain SQL files)
  models.py               dataclasses / pydantic schemas
  core/                   pure functions, no web, no DB: the testable heart
    media.py  spectro.py  events.py  flights.py  geo.py  weather.py
    search.py  confidence.py  report.py
  jobs/                   triage.py  fetch.py  search.py  runner.py
  api/                    auth.py  cases.py  media.py  events.py  fitpool.py  search.py  packs.py  stream.py
  worker.py               job loop
  cli.py                  run the whole pipeline on a file from the terminal
backend/tests/            test_<module>.py, fixtures/synth.py
frontend/                 Vite + React + TypeScript
scripts/                  smoke_dopplertrack.py  coverage_report.py
data/                     gitignored: app.db, uploads/, flights/, packs/, cache/, results/
docs/  design/
```

`core/` must be usable without the web layer: milestone 1 ends with `python -m app.cli run ...` producing a result JSON for a file.

## 3. Core modules

```python
# media.py
def probe(path) -> MediaInfo                       # ffprobe: duration, has_audio, codec, sample_rate
def sha256_file(path) -> str
def decode_audio(path, timeout_s=600) -> tuple[np.ndarray, int]   # the ffmpeg command of dopplertrack.audio.load_audio (mono, 4 kHz, f32le), run here with a timeout

# spectro.py
def build(x, sr, case_dir) -> Spectrogram          # audio.compute_spectrogram; writes S.npy (float32), t.npy, f.npy, burst.npy (tracks.burst_mask on the whole recording)
def load(case_dir, t0=None, t1=None) -> Spectrogram      # np.load(S.npy, mmap_mode="r"); only the columns asked for
def load_burst(case_dir) -> tuple[mask, t]         # for events.fit / preview / propose
def matrix(case_dir, t0, t1, f_lo, f_hi, cols, rows) -> dict   # downsampled uint8 grid for the UI, dB clipped to 0..12; numpy only
def steady_tones(sp, top=5) -> list[float]         # brightest stationary bins before whitening, shown to the analyst (not built yet)

# events.py
def propose(sp, c, band=(60, 300), preset="fast", workers=1, slice_s=600, overlap_s=120,
            on_slice=None, burst=None) -> list[EventFit]   # detect_events per slice; on_slice(done_s, total_s, added, removed)
def proposal_box(ev: EventFit, c, sp) -> tuple[float, float, float, float]  # t_cpa - 50 .. t_cpa + 50, and the range of ideal_curve over that span padded 5%, clipped to the grid
def fit(sp, t_start, t_end, box_lo, box_hi, harmonics, c, burst=None) -> EventFit       # full: fit_event(box_lo / 1.15, box_hi / 0.85, objective="brightness"); what the search uses
def preview(sp, t_start, t_end, box_lo, box_hi, harmonics, c, burst=None) -> EventFit   # quick: coarse grid_search, then fit_event(init=seed); what the editor draws
def preview_from_disk(case_dir, t_start, t_end, box_lo, box_hi, harmonics, c) -> dict   # load(t_start - 60, t_end + 60) then preview; runs in the fit pool; returns {fit, burst, harmonics, curve}
def curve_points(ev: EventFit, c, n=200) -> list[tuple[float, float]]       # doppler.ideal_curve, for the overlay
def effective_harmonics(sp, box_hi, harmonics) -> int                       # the cap floor(450 / box_hi)
def pick_pair(events) -> tuple                                              # two best by score, earlier first; rest are extras. Takes and returns FittedEvent (box id, box, harmonics, fit)
# errors: BoxTooSmall (code box_too_small), FitFailed (code fit_failed); `burst` is spectro.load_burst(case_dir)

# flights.py
def utc_days_for(date_local, tz, margin_h=1) -> list[date]
def local_ranges_unix(date_local, tz, ranges) -> list[tuple[float, float]]   # time-of-day ranges as unix; None is the whole local day
def ensure_day(pack, utc_date, data_dir, progress) -> Path   # mkdir first; fetch_day(bbox=pack.bbox) incl. jets, save_traces. Integrity filter: M5. Only called when the caller opts in
def load_window(pack, utc_days, data_dir, prop_only=True, types=None) -> list[Trace]   # ready days only; unknown types kept
def count(pack, date_local, ranges, region_ids, data_dir) -> dict   # {flights, prop, days_ready} for the live counter
def build_index(traces, pack) -> DayIndex                    # frame at the pack centre

# geo.py
def load_pack(pack_id) -> Pack
def in_regions(pack, region_ids, lat, lon) -> np.ndarray        # polygon test, vectorised
def dot_grid(pack, pitch_m) -> list[tuple[float, float, str]]   # cells for the UI map

# weather.py
def temperature(pack, t_unix_range) -> tuple[float, str]        # (T_eff in C, source)

# search.py
def compute(case: CaseInputs, sp, boxes, data_dir, types, workers, burst, progress, fetch_missing=False) -> Raw   # steps 1 to 7: no constraints
def conclude(case: CaseInputs, sp, raw) -> dict                # steps 8 to 11: constraints, assessment, refine, the result JSON of section 7
def run(case, sp, boxes, ...) -> dict                          # compute, then conclude. progress(kind, payload) with kind "stage" or "progress"

# confidence.py
def assess(pairs, verdict, n_confirmed, bursts, rows_dropped_pct, cut_suspected, reason) -> Assessment   # see 06-confidence.md; pairs carry in_area, in_time, n_events

# report.py
def render_html(case, result) -> str                            # self-contained, printable
```

### Rules for `spectro` and `events` that come from measurements

See `02-dopplertrack.md`, behaviours 2 and 11 to 15; `scripts/smoke_dopplertrack.py --editor` reproduces them.

- **Spectrogram on disk as plain arrays.** `S.npy` is float32, 840 rows by 4 columns per second of audio (48 MB per hour). Memory-mapped, a fit or a UI tile reads only its columns in milliseconds; loading the library's compressed `.npz` would cost seconds per request on a long recording. Build a dopplertrack `Spectrogram(t, f, S)` from the slice when the library needs one.
- **`events.fit` and `events.preview` widen the box.** The stored box is what the analyst drew. The library needs `f_hi > 1.353 * f_lo` or it raises; passing `box_lo / 1.15` and `box_hi / 0.85` makes its fundamental grid span exactly the box. Reject boxes under 20 s or 2 Hz with a clear error, clip to the 40 to 450 Hz grid, and cap `harmonics` at `floor(450 / box_hi)`. Copy `fit_box` and `fit_preview` from `scripts/smoke_dopplertrack.py`; both are tested there.
- **Burst flag on analyst boxes.** `fit_event` returns `burst = 0.0`; only detection fills it. `fit` and `preview` set `ev.burst = tracks.burst_fraction(burst.npy, t, ev.t_cpa)` so the cap in `06-confidence.md` can apply to hand-drawn flyovers.
- **Boxes sit on the bend.** About 100 s centred on closest approach, tall enough to enclose the curve over that time. `proposal_box` makes proposals that shape, and the editor's hint text asks the analyst for the same.
- **`events.propose` is sliced and fast.** The `fast` preset is `detect_events(refine=False, f0_step=3.0, t0_step=3.0, n_curve=60, min_sep_s=30.0, top=8)` on consecutive 10 minute slices that overlap by 2 minutes (`sp.crop` keeps absolute times). About 2 s per minute of audio on one worker, against 10 s with library defaults. After each slice, merge with what is already found (two proposals within 30 s: keep the higher score), set nothing to confirmed, and call `on_slice`. Merging may only delete rows that are still `source = detect, status = proposed`; anything the analyst has touched stays, and a new proposal within 30 s of an analyst's box is dropped. The `full` preset uses the library's grid with `refine=False`. Neither preset's fits are searched; they only place boxes for the analyst.

## 4. Data model (SQLite)

```sql
CREATE TABLE users (
  id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'analyst', created_at TEXT NOT NULL);

CREATE TABLE cases (
  id TEXT PRIMARY KEY,                 -- ULID
  case_ref TEXT, created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
  status TEXT NOT NULL,                -- draft | triaged | ready | searching | done | failed
  pack_id TEXT NOT NULL DEFAULT 'uae',
  date_local TEXT,                     -- YYYY-MM-DD
  time_ranges TEXT,                    -- JSON [["12:00","17:00"]], null = whole day
  region_ids TEXT,                     -- JSON ["dubai"], null = whole pack
  custom_bbox TEXT,                    -- JSON [lat_min, lat_max, lon_min, lon_max] or null
  temperature_c REAL, temperature_source TEXT);

CREATE TABLE media (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id),
  filename TEXT NOT NULL, sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL,
  duration_s REAL, path TEXT NOT NULL, spectrogram_path TEXT, created_at TEXT NOT NULL);

CREATE TABLE events (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id),
  source TEXT NOT NULL,                -- detect | analyst
  status TEXT NOT NULL,                -- proposed | confirmed | rejected
  t_start REAL NOT NULL, t_end REAL NOT NULL, f_lo REAL NOT NULL, f_hi REAL NOT NULL,   -- the box as drawn; fit() widens it
  harmonics INTEGER NOT NULL DEFAULT 1,
  fit TEXT,                            -- JSON of EventFit.to_dict(): detect's coarse fit, then the editor preview; display only
  fit_temperature_c REAL,              -- the temperature that fit used
  score REAL, burst REAL, created_at TEXT NOT NULL);

CREATE TABLE jobs (
  id TEXT PRIMARY KEY, case_id TEXT REFERENCES cases(id),
  kind TEXT NOT NULL,                  -- triage | fetch | search
  status TEXT NOT NULL,                -- queued | running | done | failed | cancelled
  stage TEXT, progress REAL, params TEXT, error TEXT, pid INTEGER,
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT);

CREATE TABLE job_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id),
  ts TEXT NOT NULL, type TEXT NOT NULL, payload TEXT NOT NULL);

CREATE TABLE results (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id), job_id TEXT NOT NULL,
  state TEXT NOT NULL,                 -- located | candidates | outside | not_locatable
  verdict TEXT, p REAL, strength INTEGER, band TEXT,
  lat REAL, lon REAL, radius_m REAL,
  payload TEXT NOT NULL,               -- full result JSON (section 7)
  created_at TEXT NOT NULL);

CREATE TABLE flight_days (
  pack_id TEXT NOT NULL, utc_date TEXT NOT NULL, status TEXT NOT NULL,   -- missing | fetching | ready | failed
  n_traces INTEGER, n_prop INTEGER, rows_dropped_pct REAL, traces_path TEXT, source_tag TEXT, fetched_at TEXT,
  PRIMARY KEY (pack_id, utc_date));

CREATE TABLE audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, user_id INTEGER, case_id TEXT,
  action TEXT NOT NULL, detail TEXT, ip TEXT);
```

Open SQLite in WAL mode; the api and the worker both write.

As built in M2 (`backend/app/migrations/001_init.sql`), three additions to the schema above:
`events.curve` (the fitted curve as JSON, so the api can draw a flyover without loading
dopplertrack), `jobs.cancel_requested` (`cancel` or `truncate`; the worker acts on it), and
`job_events.case_id` (the stream is per case). Case statuses in use: `draft`, `triaged`,
`searching`, `done`, `failed`.

Files:

```
data/uploads/<case_id>/original.<ext>   S.npy  t.npy  f.npy  burst.npy
data/flights/<pack>/<utc-date>-traces.npz
data/packs/<pack>/pack.json  regions.geojson  grid.json
data/results/<case_id>/<result_id>.json  report.html
data/cache/dopplertrack/                 terrain tiles, type table
```

## 5. HTTP API

JSON everywhere, session cookie auth, all routes under `/api`. Errors are `{ "error": { "code": "...", "message": "..." } }` with a 4xx or 5xx status.

```
POST   /api/auth/login            {email, password} -> {user}
POST   /api/auth/logout
GET    /api/auth/me

GET    /api/packs/{pack}          -> {id, name, timezone, bbox, regions: GeoJSON, grid: [[lat, lon, region_id], ...]}
GET    /api/packs/{pack}/days     ?from&to -> [{utc_date, status, n_prop}]
GET    /api/flights/count         ?pack&date&ranges&regions -> {flights, prop, days_ready: bool}

GET    /api/cases                 -> [{id, case_ref, created_at, status, filename, state}]
POST   /api/cases                 {pack_id?} -> {id}
GET    /api/cases/{id}            -> case with media, events, latest job and result summary
PATCH  /api/cases/{id}            {date_local?, time_ranges?, region_ids?, custom_bbox?, temperature_c?, case_ref?}
POST   /api/cases/{id}/media      multipart file -> {media}; queues a triage job
GET    /api/cases/{id}/spectrogram?t0&t1&f_lo&f_hi&cols&rows -> {t0, t1, f_lo, f_hi, cols, rows, data: base64 uint8}   404 until triage has written it
GET    /api/cases/{id}/events     -> [{id, source, status, t_start, t_end, f_lo, f_hi, harmonics, fit, score, burst, curve: [[t, f], ...]}]
POST   /api/cases/{id}/events     {t_start, t_end, f_lo, f_hi, harmonics} -> event, status confirmed. Runs the quick preview in the fit pool and answers when it is done, about 2 s.
PATCH  /api/cases/{id}/events/{eid}   {status?, t_start?, t_end?, f_lo?, f_hi?, harmonics?} -> event. Runs the preview again if the box or harmonics changed, and when a proposal is first confirmed.
                                  Fit errors: 422 box_too_small | fit_failed, 503 fit_unavailable, 504 fit_timeout (30 s)
DELETE /api/cases/{id}/events/{eid}
POST   /api/cases/{id}/search     -> {job_id}   409 unless case_ref set, date set, spectrogram ready and 2+ confirmed events; stops a triage job still detecting on this case
DELETE /api/cases/{id}/search     cancels the running job
GET    /api/cases/{id}/stream     text/event-stream (section 8)
GET    /api/cases/{id}/result     -> result JSON (section 7)
GET    /api/cases/{id}/report     -> text/html, self-contained
```

As built in M2: one recording per case (a second upload is 409 `media_exists`); `POST /search` refusals are 409 with code `case_ref_required`, `date_required`, `spectrogram_not_ready`, `need_two_flyovers` or `search_running`; uploads and searches are rate-limited per user per hour (429 `rate_limited`, counted from the audit log); the interactive API docs are switched off, since they would be an anonymous endpoint; editing a proposal's box makes it the analyst's (`source = analyst`); `/flights/count` and editor fits run in the fit pool; `/packs/{pack}/days` lists the days on disk. No route starts a fetch job yet (M5).

Upload rules: stream to disk while hashing; reject over `MAX_UPLOAD_MB` (default 2048); after upload run ffprobe and reject files with no audio stream or longer than `MAX_DURATION_H` (default 6). Never trust the client filename for the path. ffmpeg and ffprobe run with a timeout: `media.decode_audio` runs the same ffmpeg command as `dopplertrack.audio.load_audio` itself, because the library call has no timeout.

Why 6 hours: decoding holds about 115 MB per hour of audio at peak and the spectrogram another 48 MB per hour plus working copies while it is whitened, and fast detection takes about 2 minutes per hour on one worker. Raise the limit once memory has been measured on a real long file.

The speed of sound is inside every fit, so a preview made before the temperature was known or changed is slightly off. That is harmless: the search job refits every confirmed box at its own temperature (section 6, step 2). Previews use the case temperature if set, else the pack's monthly figure.

## 6. Search orchestration (`core/search.py`)

```
inputs: case, spectrogram sp = spectro.load(case_dir), confirmed boxes (2+), progress callback

 1. T_eff, source = case.temperature or weather.temperature(pack, window); c = speed_of_sound(T_eff)
 2. for each confirmed box: ev = events.fit(sp, box, harmonics, c)   # full fit at this temperature; stage "fits"
    ev1, ev2, extras = events.pick_pair(those fits)          # earlier of the two best first
 3. days = flights.utc_days_for(case.date_local, pack.timezone)
    for each day not ready: flights.ensure_day(...)          # minutes per day; progress stage "flights"
 4. traces = flights.load_window(pack, days, prop_only=True)
    idx = flights.build_index(traces)                       # DayIndex.build(traces, lat0, lon0) with the pack centre: an empty day otherwise gets a NaN origin
    if idx has no segments -> not_locatable("no propeller flights in the archive for that day and area")
 5. silence = 6000.0 if the two events are under 20 min apart and no confirmed event lies between them else None
 6. res = run_search(sp, ev1, ev2, idx, harmonics, c=c, elevation=Terrain(pack.terrain_zoom).elevation,
                     silence_d_m=silence, workers=W, log=to_progress)      # whole pack, no bbox
    if res is empty -> not_locatable("no place fits both flyovers")
 7. if extras: res = rescore_with_extra(sp, ev1, extras, idx, res, c=c, workers=W)
 8. per pair (pipeline.best_per_pair): clip_start = t_heard1 - ev1.t_cpa - shift
    in_area = geo.in_regions(...);  in_time = clip window overlaps case.time_ranges
 9. assessment = confidence.assess(...)                      # state, verdict, p, strength, band
10. for the top pair (and the top constrained pair if different):
       fine = pipeline.refine(sp, ev1, ev2, idx, row, spacing_m=50, half_m=600, extra=extras, c=c, elevation=...)
       point = fine.iloc[0];  radius_m = sharpness(fine)
11. curves for display: for each event and its matched flight, score.modelled_curve(seg, obs, c) mapped to audio time
12. optional controls (06-confidence.md), then persist the result JSON
```

Details:

- Search the **whole pack** and apply the area and time as constraints afterwards. A narrow search leaves too few wrong pairs for the verdict.
- If the time window is wider than six hours and the temperature is automatic, run steps 2 to 10 at the temperatures of the window's start and end and keep the higher-scoring run; record both.
- `to_progress` turns dopplertrack's log lines into events. Prefer calling the stages yourself (`pair_join`, `lens_candidates`, `score_candidates` each take a `progress` callback) once the simple version works; that also yields the candidate points early for the map.
- `sharpness(fine)`: the largest distance from the peak among fine-grid cells scoring at least 95% of the peak, floored at 50 m. Starting rule.
- For the overlay, the f0 scale the scorer chose is not returned; recompute it with `EventWindow.sweep_scores` at the chosen shift.
- Cancel: the worker terminates the child and marks the job cancelled.

## 7. Result JSON

```json
{
  "state": "located",
  "verdict": {"label": "located", "p": 0.004, "gap": 6.9, "tail_width": 0.75, "n_pairs": 412, "n_null": 380},
  "strength": 80, "band": "High",
  "estimate": {"lat": 25.1412, "lon": 55.2268, "radius_m": 150, "elev_m": 12, "regions": ["dubai"]},
  "clip_start_utc": "2026-11-14T09:40:58Z",
  "events": [
    {"id": "...", "role": "pair", "t_cpa": 72.1, "f0": 112.6, "icao": "896123", "type": "SR22",
     "cpa_time_utc": "2026-11-14T09:42:10Z", "slant_m": 640, "speed_mps": 62, "score": 15.8,
     "curve": [[t_audio, hz], ...]}
  ],
  "candidates": [ {"rank": 1, "lat": 0, "lon": 0, "score": 35.4, "icao": ["...", "..."], "in_area": true, "in_time": true} ],
  "cells": [[lat, lon, score], ...],
  "constraints": {"regions": ["dubai"], "time_ranges": [["12:00", "17:00"]], "outside_match": null},
  "controls": {"placebo_days": null},
  "inputs": {"file_sha256": "...", "date_local": "2026-11-14", "temperature_c": 28.0, "temperature_source": "auto",
             "dopplertrack": "2d899bb", "flight_days": ["2026-11-13", "2026-11-14"], "rows_dropped_pct": 3.1,
             "params": {"silence_d_m": 6000, "v_tol": 0.35, "d_tol": [0.4, 2.5]}},
  "not_locatable": null
}
```

For `not_locatable`: `{"reason": "fewer_than_two_flyovers" | "no_flights" | "no_candidates", "checked": [...], "advice": [...]}`. For `candidates`, add `"sublabel": "unconfirmed" | "weak" | "too_few_flights" | "needs_third_flyover"`.

The numbers above are illustrative of shape only.

## 8. Event stream

`GET /api/cases/{id}/stream` sends server-sent events; `id:` is the `job_events.id`, so the browser's `Last-Event-ID` resumes after a reconnect.

| `event:` | `data:` |
|---|---|
| `stage` | `{"job": "search", "stage": "fits" \| "flights" \| "join" \| "lattice" \| "scoring" \| "extras" \| "refine" \| "controls", "state": "start" \| "done", "detail": "38 flights in window"}` |
| `progress` | `{"stage": "scoring", "done": 5200, "total": 8400}` |
| `cells` | `{"points": [[lat, lon, score_or_null], ...]}` at most 2,000 per event |
| `triage` | `{"state": "decoding" \| "spectrogram_ready" \| "detecting" \| "done", "done_s": 600, "total_s": 1800, "events": 2}` |
| `proposals` | `{"events": [event, ...], "removed": [event_id, ...]}` the proposals found in the slice just finished, in the shape of `GET /events`; `removed` lists earlier proposals that a stronger one within 30 s replaced |
| `done` | `{"result_id": "...", "state": "located"}` |
| `failed` | `{"code": "...", "message": "..."}` |

Triage stages map to the file card's progress bar; search stages map to the Searching screen.

As built in M2:

- `proposals` also carries `done_s` and `total_s`. `stage` events carry `"job": "search"`.
- A further event, `cancelled` `{"job": "search", "job_id": "..."}`, when a search is cancelled.
- A triage job cut short by a search ends with `triage` `{"state": "done", "truncated": true}`.
- `failed` carries `job`, `job_id`, `code`, `message`. Codes from the worker itself: `timeout`, `crashed`, `worker_restarted`.
- With no `Last-Event-ID` (or `?after=N`) the stream replays the case's events from the start; `GET /api/cases/{id}` returns `last_event_id` for a client that only wants what comes next.
- A comment line (`: keep-alive`) is sent every 15 s.

Triage timeline for a 30 minute file on one worker (measured parts marked): upload ends; decode (seconds); spectrogram (0.9 s, measured) and `spectrogram_ready`, from which the flyover editor can show the recording and take hand-drawn boxes; then one `proposals` event per 10 minute slice, about 17 s apart (measured); `done` after about a minute. An analyst who reaches the editor before detection ends sees the proposals arrive and never has to wait for them.

## 9. Configuration (`.env`)

```
APP_SECRET=...                 session signing key
ADMIN_EMAIL=...  ADMIN_PASSWORD=...     first user, created at startup if missing
DATA_DIR=./data
DOPPLERTRACK_CACHE=./data/cache/dopplertrack
DOPPLER_WORKERS=1
MAX_PARALLEL_JOBS=1
FIT_WORKERS=2
FIT_INLINE=0
DETECT_PRESET=fast             fast | full
JOB_TIMEOUT_TRIAGE_S=3600
JOB_TIMEOUT_FETCH_S=3600
JOB_TIMEOUT_SEARCH_S=7200
MAX_UPLOAD_MB=2048
MAX_DURATION_H=6
RETENTION_DAYS=30
DEFAULT_PACK=uae
```

Commit a `.env.example`; never commit `.env`.

## 10. Security and audit

- Passwords hashed with argon2 or bcrypt. Session cookie HTTP-only, SameSite=Lax. JSON-only API.
- Every state-changing route writes an `audit_log` row: `login`, `case.create`, `media.upload` (with sha256), `event.confirm`, `search.start`, `result.view`, `report.export`.
- Per-user rate limit on uploads and searches.
- ffmpeg runs on untrusted files: fixed argument list, no shell, timeout, output size cap.
- Path handling: every file path is built from ids, never from client strings.

## 11. Frontend

- Vite, React, TypeScript, Tailwind with the tokens in `design/tokens.css`, Motion for transitions, TanStack Query for data, native `EventSource` for the stream.
- One route with a step state machine: `upload -> when -> where -> flyovers -> review -> searching -> result`. Keep the state in the URL hash (`#when`) so reload returns to the step; the case id is in the path.
- **DotMap** is a canvas component, not a tile map. It draws squares from `grid` (the pack's land cells), recolors them by state, draws `cells` from the stream as match strength, flight paths as lines, and animates a camera (pan and zoom) with `requestAnimationFrame`. Projection: equirectangular scaled by cos(latitude of the pack centre). No tile provider is needed for the MVP; the result links out with `https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=17/{lat}/{lon}`.
- **Spectrogram** is also a dot-matrix canvas drawn from the `/spectrogram` grid, with the fitted curve as a line and draggable boxes for the event editor. Fetch it in tiles as the analyst pans and zooms (for example 600 columns by 140 rows per request) and cache them; never ask for the whole recording at full resolution. A fit request is sent on pointer release, not while dragging; a newer request for the same box aborts the older one (`AbortController`), and the box shows a "Fitting" state until the answer arrives.
- Uploads use `XMLHttpRequest` for progress. Resumable upload is a later addition.
- Poll nothing that the stream already delivers.

As built in M3 (`frontend/`):

- Vite 8, React 19, TypeScript, TanStack Query, native `EventSource`. **Plain CSS** with the tokens (`src/styles.css`), not Tailwind: the mockups are exact inline styles, and class rules copied from them are shorter than a utility translation. **No Motion library yet**: CSS transitions on transform and opacity; the motion pass is M6. Fonts are bundled (`@fontsource`), so the app calls no font host.
- `src/steps.ts` is the step machine (pure, tested): the step is the URL hash, the case id the path (`/cases/<id>#flyovers`); a case opens where it was left; a step whose inputs are missing falls back to the nearest earlier one.
- `src/useCaseStream.ts` opens the stream with `?after=<last_event_id>` from the case, so nothing is replayed; `proposals` events only invalidate the events query.
- `GET /api/config` (default pack, pack list, upload limits) and `temperature_effective` on the case were added for the UI. The pack's `grid` pitch is chosen so its longer side has about 72 cells.
- `/spectrogram` grids average over time, then take the maximum over frequency: a plain maximum lifted the noise floor to two thirds of the scale at wide zoom.
- The editor asks for one grid per view (5 px dots), debounced, and stretches the last one while the next loads. A drag that starts on a suggestion draws a new box; only a plain click confirms a suggestion. A suggestion under a marked box is hidden. Removing a suggestion marks it `rejected` so detection cannot bring it back.
- Not built yet: the Cases list, frequency zoom in the editor, curves modelled from real trajectories.

As built in M4:

- `DotMap` has layers (land cells, search points and match strength, a dashed "best area", flight paths with closest-approach markers and leaders, the estimate's uncertainty circle, numbered candidate rings, a scale bar) and a camera that flies between framings in 800 ms. `Locator` is the inset.
- `SearchingStep` reads stages, their details, progress and cells from the stream; `ResultStep` renders Located, Candidates, the outside-match banner ("Show it" swaps the panel to that match) and Not locatable from `GET /result`.
- Result JSON additions to section 7: `shown_rank`; `estimate.cells`, `estimate.cell_m`, `estimate.lattice`, `estimate.refined`; per event `path` (`points`, `cpa`, `cpa_alt_m`, `cpa_unix`), `matched`, `box`, `curve_kind`; per candidate `regions`, `types`, `n_events`, `paths`; `inputs.region_names`, `inputs.n_flyovers`, `inputs.flight_days_missing`; `constraints.outside_match` with its own `events`, `cells` and `confirmed`.
- Stream additions to section 8: `cells` carries `scored` (false for lattice points not yet scored); `stage` done events carry a short `detail` ("3 of 3", "153 propeller", "360 pairs", "37,366 points"); search events carry `job_id`.
- `POST /api/cases/{id}/not-locatable` (see the decision log). The report is the same route as before, printable from the browser.

As built in M5:

- `core/integrity.py` filters raw trace rows; `flights.ensure_day` swaps it in front of the library's parser for the length of one fetch and writes `<utc-date>-traces.meta.json` (counts, the filter's tally, source, time) beside the traces. `flights.dropped_pct` feeds `inputs.rows_dropped_pct`.
- `GET /api/packs/{pack}/days` lists days on disk, being fetched (with a progress line) or failed; `POST` on the same path queues a fetch job; `/flights/count` carries the same per-day status for the date asked about. Migration `002` adds `job_id`, `stats`, `error` to `flight_days`.
- The worker gives fetch jobs their own slot (one at a time) beside the `MAX_PARALLEL_JOBS` compute jobs.
- `core/weather.py`: `for_case` (analyst, then archive, then monthly), `window`, `search_temperatures`; cache under `data/cache/weather/<pack>/`. `core/search.run` may call `compute` twice and runs `placebo` when `PLACEBO_DAYS` is set; the stream then has a `controls` stage. Result additions: `inputs.temperature_runs`, `inputs.temperature_window`, `controls.placebo_days`, `controls.placebo_beaten_by`.
- When step: the count card shows "Flight data for this date is not loaded", a "Load it (about N GB stream, several minutes)" button, and the fetch's progress while it runs.

After the review of 2026-11-22, six fixes:

- `app/retention.py` removes a case: its two folders first, then its rows, child tables first. `DELETE /api/cases/{id}` uses it
  (409 `case_busy` while a job of the case is running; audited as `case.delete` with the recording's name and hash) and so does the
  worker's hourly `housekeep()`, which applies `RETENTION_DAYS` (audited as `case.expired`, no user). 0 or unset keeps everything.
- Accounts are made with `python -m app.cli user add | passwd | list`; passwords come from a prompt or standard input and need ten
  characters. Audited as `user.create` and `user.password`. Sessions are signed cookies and are not revoked by a password change.
- `POST /api/auth/login` answers 429 `too_many_attempts` once `LOGIN_FAILURES_MAX` (10) failures from one address fall inside
  `LOGIN_FAILURES_WINDOW_MIN` (15), counted from the `login.failed` rows of the audit log. `SESSION_SECURE=1` marks the cookie HTTPS-only.
- Under Compose the api runs with `FORWARDED_ALLOW_IPS=*` and nginx sets `X-Forwarded-For` to the address it sees, replacing
  anything the visitor sent, so the audit log and the sign-in limit use the visitor's address. The api's port is not published,
  so only the proxy can reach it. nginx also sends `frontend/trace-headers.conf`: no sniffing, no framing, a referrer policy, and a
  content policy (scripts and requests from the app only; images also from https hosts, for map tiles; inline styles allowed).
- `core/media.py` passes `-protocol_whitelist file` to ffprobe and ffmpeg and refuses playlist formats (HLS, concat and the like) at the probe.
- The worker stops when the pid in `TRACE_EXIT_WITH_PID` disappears; `scripts/dev_backend.sh` sets it to itself.

After M6 (2026-11-22), the newest flight day and three interface changes:

- `POST /api/packs/{pack}/latest` queues a `fetch` job with `latest: true` in its params; `GET` returns the state for the header's icon
  (`off`, `idle`, `checking`, `fetching` with `fraction` and `bytes_total`, `current`, `failed`). The page posts once when it opens signed in
  and hourly after. The server queues at most one job: none while a fetch for the pack is queued or running, none when yesterday (UTC) is on
  disk, and otherwise one look at the archive per `FLIGHTS_AUTO_RETRY_MIN` (60) unless `force` (the icon's "Try again", counted against the
  fetch rate limit). Audited as `flights.update`, or `flights.fetch` when forced. `FLIGHTS_AUTO=0` and `dev_only` packs answer `off`.
- The job resolves the day itself: `core/flights.latest_published` asks the GitHub release list for yesterday, then up to three days
  further back, and takes the first with a tar; `archive_bytes` is the sum of the tar parts' sizes, which is what makes a percentage
  possible (`jobs.progress`). The resolved day and size are written back into the job's params. A day already on disk ends the job without a stream.
- Interface: `components/FlightsStatus.tsx` (the icon, the bar under the header, the popover), `components/Select.tsx` (the region chooser as
  a listbox in the app's colours, replacing a native `<select>`), a back arrow in `Header` driven by `steps.backOf`, and the result's map
  link goes to Google Maps (`format.googleMapsUrl`).

- The Located result (and a confirmed outside match) is drawn by `components/LocationMap.tsx`: Leaflet 1.9 with raster tiles from
  `config.map_tiles` (`MAP_TILES_URL`, default OpenStreetMap's standard tiles, colours inverted by a CSS filter when `dark`; empty switches it off and the dot map's close-up is used as before).
  Layers: match cells as rectangles at their ground size, the matched flight paths with their closest points, the estimate's circle.
  It opens on the dot map's old framing and flies in to `max(300 m, 3 x radius)` each way; pan, wheel, pinch, the zoom buttons and the
  keyboard work from there. The tiles are fetched by the analyst's browser, not by the server. Candidates and the Searching screen stay on the dot map.

As built in M6: `Dockerfile` (the api and the worker, one image), `frontend/Dockerfile` and
`frontend/nginx.conf` (static files, `/api` passed to the api with buffering off for the
stream), `docker-compose.yml` (`./data` mounted at `/data`, containers run as the host's
user, so `./data` must exist before the first start). The interface gained `/cases` and an error boundary. Helper processes exit with their
parent (`config.exit_with_parent`).

## 12. Testing

- `backend/tests/fixtures/synth.py`: the synthetic flights and audio from `scripts/smoke_dopplertrack.py`, parameterised (number of flights, temperature, decoy flights).
- Unit tests per core module; one end-to-end test that runs `core.search.run` on the synthetic case and expects the truth within 600 m, and the same case at the wrong temperature to miss.
- `events.fit`: the three bend boxes in the smoke script (`BEND_BOXES`) return f0 within 2 Hz, speed within 25 m/s and closest approach within 6 s of the truth; a narrow box (110 to 140 Hz) does not raise; a 10 s box and a 1 Hz box are rejected with `box_too_small`; a fit from `spectro.load` on a slice equals a fit on the whole spectrogram.
- `events.preview`: on the same boxes its score is within 0.5 of the full fit's and it returns in under 5 s.
- `events.propose`: on the synthetic case at least two of the three flyovers have a proposal within 25 s; `on_slice` is called once per slice with rising `done_s`. Mark it slow (about a minute).
- API tests with a temporary data directory and the worker run inline.
- The opt-in Oyster Bay test, enabled when the reference data is present.
- Frontend: type-check and a smoke test of the step machine; visual checks by hand against the mockups.
