# TRACE: handoff guide

Read this file first. It explains the whole project in one place: what it does, how it is
built, every feature, the decisions behind it, what has been proven and what has not. It is
written for someone (or an AI assistant) picking the project up cold. Everything here was
true on 2026-11-23, at the commit that added this file (the one after `3eafa9e`).

TRACE stands for **T**racking **R**ecordings via **A**ircraft **C**urve **E**stimation.

## 1. What it is, in one paragraph

A web app for cybercrime analysts. The analyst uploads a recording, gives its date, a
time-of-day window and a rough area, confirms the aircraft flyovers found in the audio, and
gets back ranked location leads with a verdict, or a clear "not locatable". It works because
a propeller aircraft leaves a tone in an outdoor recording, the tone falls in pitch as the
aircraft passes (the Doppler effect), and the exact shape of that fall depends on where the
microphone was. With public flight tracks for the day, each candidate place predicts a
different curve, and the recording picks the one that fits. The search itself is done by the
open-source [dopplertrack](https://github.com/mjshiggins/dopplertrack) library; TRACE is the
tool built around it. It is a hackathon MVP made by one person in about two days.

**Status:** all six planned milestones (M0 to M6) are done and committed, followed by two
rounds of additions, a review-and-fix pass, and a hardening pass on the presenting Mac
(2026-11-24). The backend has 107 tests (one of them needs a reference recording and is
skipped by default) and the frontend 16. It runs with or without Docker, and natively on
macOS with one engine worker. It has been proven on one real recording (New York); it has **not** yet been tested
on a real recording from the UAE, which is the region it is aimed at.

## 2. How to read this repository

Read in this order. Each file is the authority for its subject; this guide summarises them.

| Order | File | What it is |
|---|---|---|
| 1 | `HANDOFF.md` | this guide |
| 2 | `CLAUDE.md` | the project's standing rules, commands and status, written for an AI coding assistant. The ten "rules that do not bend" are binding |
| 3 | `README.md` | the reader-facing description: quick starts, the demo, evidence, limits, configuration |
| 4 | `docs/00-START-HERE.md` | orientation written before any code existed |
| 5 | `docs/01-product.md` | what is being built and the result states |
| 6 | `docs/02-dopplertrack.md` | the engine's real CLI and API, its defaults, sixteen measured behaviours and traps. Trust it over memory; where it disagrees with the library's source, the source wins |
| 7 | `docs/03-method-and-evidence.md` | the physics, and every result measured during the build |
| 8 | `docs/04-data.md` | flight data, the trace format, time zones, region packs, temperature |
| 9 | `docs/05-architecture.md` | processes, modules, database schema, HTTP API, result JSON, event stream. The "As built in M2 ... M6" and "After ..." sections at the end of each part say what was actually built |
| 10 | `docs/06-confidence.md` | how a search becomes a verdict, a band and a number |
| 11 | `docs/07-build-plan.md` | the milestones and their acceptance tests |
| 12 | `docs/08-design.md` | look, screens, copy, motion; plus `design/mockups/` (nine screens as HTML) and `design/tokens.css` |
| 13 | `docs/09-risks-and-open-questions.md` | **the decision log.** Every decision made, dated, with its reason; the risk register; open questions |
| 14 | `docs/coverage-findings.md` | where and when the UAE has propeller traffic, measured |
| 15 | `docs/demo-script.md` | a two-minute spoken demo |

`PROMPT.md` is the original opening prompt the project was started from. The docs numbered
00 to 09 were written as the plan before the build and then corrected as it went, so a
statement in an early section can be superseded by an "As built" section further down the
same file.

## 3. What is in this archive, and what is not

The archive holds every file tracked in git: source, tests, docs, design, Docker files,
lock files. It deliberately leaves out:

| Left out | Why | How to get it |
|---|---|---|
| `.env` | holds the sign-in and the session secret | `cp .env.example .env` and fill it in (section 12) |
| `data/` | the database, uploaded recordings, results, the audit log | created on first run |
| `data/flights/` | flight tracks, about 50 MB per UAE day | the app fetches a day when asked (about a 4 GB stream each) |
| `data/demo/` | the synthetic demo recording | `uv run python -m app.cli demo` |
| `data/reference/oyster_bay/` | the real reference recording (from YouTube) and its flight day | steps in `docs/03-method-and-evidence.md` |
| `.venv/`, `node_modules/`, `frontend/dist/` | installed and built files | `uv sync`, `npm --prefix frontend ci`, `npm --prefix frontend run build` |
| `.git/` | history | the commit list is in section 14 |

## 4. The method, briefly

1. A propeller aircraft's tone, heard from the ground, follows an S-shaped falling curve as
   it passes. Four numbers describe one pass: the tone's true frequency, the aircraft's
   speed, its closest distance, and the time of closest approach.
2. One pass says little about where the listener is. Two passes by two known aircraft, a
   known time apart, are only consistent with a few places on the ground. A third pass on
   the same clock confirms one of them.
3. Public ADS-B archives ([adsb.lol](https://www.adsb.lol/)) record where every broadcasting
   aircraft was, second by second. So for every pair of that day's propeller flights that
   could have produced two of the passes that far apart, the engine lays a lattice of
   ground points, predicts the curve each point would hear, and scores it against the audio.
4. The winner is judged against the crowd of wrong pairs, not against the runner-up. That
   gives a p value: the chance a wrong winner would lead by that much.

The recording's start time is not an input; it falls out of the search. The recording's
**date** is an input and must be right.

## 5. Features

### The analyst's flow (seven steps, one page)

| Step | What happens |
|---|---|
| Sign in | accounts only; there is no sign-up page |
| Upload | drop a video or audio file (up to 2 GB, 6 hours). It is hashed (SHA-256), decoded, and a spectrogram of 40 to 450 Hz is ready in seconds. Automatic flyover detection then runs in the background |
| When | the recording date (required) and a time-of-day window (optional; presets or a slider). A live count shows how many aircraft flew in that window. If the day's flight data is not on disk, a "Load it" button fetches it |
| Where | pick regions on a dot-matrix map (in the UAE pack: the seven emirates and Abu Dhabi's three regions), or draw a custom box. The area **ranks** results; it never hides them |
| Flyovers | the spectrogram editor. Dashed boxes are automatic suggestions. The analyst drags a box about 100 seconds wide around the bend of each real flyover; it is fitted in a few seconds and shown as a red curve. Boxes can be moved and resized with the keyboard |
| Review | a summary, and a required case reference. Submit starts the search |
| Searching | live stages (fits, flights, join, lattice, scoring, extras, refine) streamed from the server, with search points appearing on the map. Can be cancelled |
| Result | one of four states, below, with a printable report |

Every page has a back arrow, a Cases link and Sign out in the header. The Cases page lists
every case with its state and can delete one.

### The four result states

| State | When | What is shown |
|---|---|---|
| **Located** | three or more flyovers on one clock and a `located` verdict (p under 0.1) | coordinates, an uncertainty radius, a confidence band and match strength, on an interactive street map that flies in to the estimate |
| **Candidates** | anything less: two flyovers, or a weak or untestable verdict | up to five ranked places on the dot map, explicitly unconfirmed |
| **Outside** | the best match lies outside the stated area or time | the best match inside, with a banner offering the stronger one outside |
| **Not locatable** | fewer than two flyovers, no flights that day, or no candidates | why, what was checked, and what would help |

Every result shows the verdict, the p value, the number of wrong pairs it was judged
against, the number of flyovers, the uncertainty radius, the air temperature used and the
share of track points the integrity filter dropped. Never a bare pin.

**Confidence bands** (`docs/06-confidence.md`): match strength is
`round(100 * clamp(-log10(p) / 3, 0, 1))`. High needs `located`, p at most 0.01 and three
flyovers; Medium and Low below that. Caps pull the band down: bursty audio, more than 20% of
track points dropped, two temperature runs disagreeing, a placebo day scoring as well, or a
suspected cut in the audio.

### Flight data

- Days are fetched from adsb.lol's daily archives on GitHub, one UTC day at a time, as a
  stream of about 4 GB that is filtered to the region and never stored whole.
- **Integrity filter:** only ADS-B positions, not stale, accurate (`nac_p` at least 8,
  containment radius at most 200 m), no impossible jumps. On an ordinary UAE day it dropped
  11.5% of track points.
- **Automatic update:** when someone signs in, the app looks for the newest published day
  for the default region and fetches it in the background if it is not on disk. A download
  arrow in the header shows the state; a bar runs under the header with a percentage while
  it downloads. At most one job, one look at the archive per hour, never a day twice.
  `FLIGHTS_AUTO=0` switches it off.
- **Air temperature** sets the speed of sound, which the fit depends on. It comes from the
  analyst, or from Open-Meteo's archive (`WEATHER_AUTO=1`), or from a monthly figure in the
  region pack.

### Region packs

`backend/app/packs/<id>/` holds `pack.json` and `regions.geojson`. Three ship: `uae` (real
emirate boundaries from OpenStreetMap), `ny` (a box around the reference recording) and
`test` (two squares, with invented flights, marked `dev_only`). A folder in `data/packs/`
overrides one of the same name.

### Accounts, security and audit

- Every route needs a sign-in. A case reference is required before a search.
- An audit log records every sign-in, failed sign-in, upload (with hash), search, export,
  flight-data fetch, deletion and account change, with the address it came from.
- An analyst sees only their own cases; an admin sees all.
- Accounts are made from the command line (`python -m app.cli user add | passwd | list`).
- Ten failed sign-ins from one address in fifteen minutes block that address.
- Uploads, searches and fetches are rate-limited per user.
- A case can be deleted with its recording and results; `RETENTION_DAYS` deletes old cases
  automatically. The audit log keeps a line naming what was removed.
- ffmpeg runs on untrusted uploads with a fixed argument list, a timeout, local files only,
  and playlist formats refused.
- Under Docker, nginx sends security headers including a content security policy.

### Other

- A self-contained printable HTML report per case (no scripts).
- A "Google Maps" link on a located result.
- A command line that runs the whole pipeline without the web app (`python -m app.cli run`).

## 6. Architecture

Two processes share one data folder; a third serves the interface.

```
browser ──> frontend (Vite dev server, or nginx in Docker)
               └─ /api ──> api (FastAPI + uvicorn) ──┐
                              │  fit pool: 3 processes for editor fits and counts
                              ▼                      ▼
                         data/app.db (SQLite, WAL)   data/uploads, results, flights
                              ▲
            worker (python -m app.worker) ── one child process per job (triage, search, fetch)
```

- **The api never imports dopplertrack in its own process.** Anything that needs the
  library runs in the fit pool or in a job's child process. This keeps the api responsive
  and respects the library's use of fork and module-global state.
- **One search per OS process.** The worker spawns a fresh child for each job, in its own
  session so it can be killed with everything it forked.
- **Progress is a database table.** Jobs write rows to `job_events`; the api tails that
  table and streams it to the browser as server-sent events. A restart loses nothing.

**Stack:** Python 3.12, uv, FastAPI, SQLite, argon2, Starlette signed-cookie sessions;
Vite, React 19, TypeScript, TanStack Query, plain CSS with design tokens, Leaflet for the
street map; fonts bundled. Docker Compose with one backend image and an nginx image.

### Directory map

```
backend/app/
  config.py        every setting, read from the environment at call time (.env is loaded once)
  db.py            SQLite connection, migrations, job queue, event and audit helpers
  retention.py     deleting a case, by hand or by age
  worker.py        the job loop: starts, times out, cancels and reaps job processes; hourly housekeeping
  cli.py           run / synth / demo / user commands
  core/            the pipeline; no web code
    media.py         ffprobe and ffmpeg on untrusted files
    spectro.py       build and slice the spectrogram
    events.py        flyover fits (three grid phases), the editor preview, automatic proposals
    flights.py       UTC days for a local date, fetching a day, loading a window, the archive lookup
    integrity.py     the track-point filter
    geo.py           region packs, point-in-region, the dot grid
    weather.py       speed of sound, temperature from the archive or the pack
    search.py        the orchestration: fit, load flights, search, extras, refine, conclude; the result JSON
    confidence.py    verdict to state, band, strength and caps
    report.py        the printable HTML report
    synth.py         the synthetic recording with a known answer, and decoy flights
  jobs/            triage.py, search.py, fetch.py (one job each), runner.py (the child's entry point)
  api/             main.py (app), auth.py, cases.py, packs.py, stream.py (SSE), fitpool.py, deps.py
  migrations/      plain SQL, applied in order
  packs/           uae, ny, test
backend/tests/     pytest; test_api.py runs the api in process, test_api_e2e.py starts a real api and worker
frontend/src/
  App.tsx          the shell: which step is shown, the header, the map stage
  steps.ts         the step machine (which step a case may enter, where "back" leads)
  api.ts           the typed HTTP client       format.ts   text formatting
  useCaseStream.ts the event stream
  components/      DotMap (canvas dot-matrix map), LocationMap (Leaflet), FlightsStatus, Select, Strip, bits
  screens/         SignIn, UploadStep, WhenStep, WhereStep, FlyoversStep, ReviewStep, SearchingStep, ResultStep, CasesScreen
scripts/           smoke_dopplertrack.py (engine check), coverage_report.py, build_uae_pack.py, curl_walkthrough.sh, dev_backend.sh
design/            nine mockup screens as HTML, tokens.css, two prototypes
docs/              the plan and the record (section 2)
Dockerfile, frontend/Dockerfile, frontend/nginx.conf, frontend/trace-headers.conf, docker-compose.yml
```

### HTTP API

All under `/api`, all needing a session except sign-in.

| Route | Purpose |
|---|---|
| `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | session |
| `GET /config` | default pack, packs offered, upload limits, the map tile host |
| `GET /packs/{id}` | regions, dot grid, labels |
| `GET /packs/{id}/days`, `POST /packs/{id}/days` | flight days on disk; fetch one UTC day |
| `GET /packs/{id}/latest`, `POST /packs/{id}/latest` | state of the automatic newest-day update; trigger it |
| `GET /flights/count` | aircraft in a date, time window and area |
| `GET /cases`, `POST /cases` | list; create |
| `GET`, `PATCH`, `DELETE /cases/{id}` | read; set date, window, area, temperature, reference; delete |
| `POST /cases/{id}/media` | upload the recording (one per case) |
| `GET /cases/{id}/spectrogram` | a grid of the spectrogram for a view |
| `GET`, `POST /cases/{id}/events`; `PATCH`, `DELETE /cases/{id}/events/{eid}` | flyover boxes; a new or moved box is fitted and returned with its curve |
| `POST /cases/{id}/search`, `DELETE /cases/{id}/search` | start; cancel |
| `POST /cases/{id}/not-locatable` | finish a case with fewer than two flyovers |
| `GET /cases/{id}/stream` | server-sent events for triage and search progress |
| `GET /cases/{id}/result`, `GET /cases/{id}/report` | result JSON; printable HTML |

The database schema, the result JSON and the event types are in `docs/05-architecture.md`.

## 7. The rules that do not bend

From `CLAUDE.md`. They are the project's constraints, not suggestions.

1. Build on dopplertrack; do not reimplement it. Pinned at commit `2d899bbfe1529e2b4351f328969bb37776d57cb4`.
2. A result is a lead. Always show verdict, p value, radius and number of flyovers.
3. Two flyovers give candidates, not a location.
4. "Not locatable" and "candidates" are designed outcomes, not errors.
5. The analyst confirms every flyover. Never fit the raw box: widen it first
   (`fit_event(sp, t0, t1, f_lo / 1.15, f_hi / 0.85, objective="brightness")`).
6. Pass the real air temperature to every fit and search.
7. One search per OS process; one library worker unless on Linux.
8. Gated tool: sign-in, case reference, audit log, no anonymous endpoint. The same method
   can locate a private person's home.
9. No invented data. Measure or mark unknown.
10. Ask before large or outward actions: streaming flight data, downloading recordings,
    pushing to a remote.

## 8. Key decisions and why

The full, dated log is `docs/09-risks-and-open-questions.md`. The ones that shaped the build:

| Decision | Why |
|---|---|
| Fit every flyover box at three grid phases (0, 1/3, 2/3 Hz) and keep the best | the engine's fit steps the tone's frequency in 1 Hz steps, so a hand-drawn box a hertz off could fit a different curve. This turned a hand-drawn case from "ambiguous" into "located" |
| Decoy flights in the synthetic test for every pair of real flights | the verdict needs about twenty wrong pairs to judge against; without them it says "insufficient" |
| The api never loads the engine; jobs run in child processes | responsiveness, and the engine's fork and global state |
| Job children run at low priority | an editor fit must never wait behind a search |
| Spectrogram grids averaged over at least two seconds, drawn above each grid's own noise floor | a noise-only clip otherwise fills the screen with bright dots |
| The area ranks results and never hides them; a stronger match outside is offered | hiding it would bury the true answer when the analyst's guess is wrong |
| The report says "Estimate" only for a located result | rule 3 |
| Plain CSS with tokens, no Tailwind, no animation library | the mockups are exact inline styles |
| Flight days are streamed and filtered, never stored whole | a day is 4 GB |
| Every fetched day goes through the integrity filter | spoofed or poor positions would mislead the search |
| A search runs at two temperatures only when the window is long and the hours differ by more than 5 C | the p value changes with temperature, so runs are compared by which flights they matched |
| The placebo-day control is built but off by default | it is unvalidated |
| The newest flight day is fetched automatically after sign-in | asked for by the owner; default region only, at most hourly, auditable, one setting turns it off |
| Located results use real street tiles (OpenStreetMap's own, colours inverted); candidates stay on the dot map | a street map invites reading two-flyover candidates as a location. CARTO's dark tiles were tried first and came back stamped "API key required" |
| `RETENTION_DAYS` defaults to 0 in code | a default of 30 would delete cases on machines that never asked for it |
| MIT licence for TRACE's own code | chosen by the owner; matches the engine. Flight and boundary data stay under the ODbL |

## 9. Evidence

Measured during the build; method in `docs/03-method-and-evidence.md`.

| Case | Outcome |
|---|---|
| Oyster Bay, New York: a real one-hour recording, real flights, real temperature (23.4 C) | Located, p 0.037, **96 m** from the true position, in about 7.5 minutes |
| The same through the library alone at its default 15 C | Located, p 0.002, 32 m |
| Synthetic, three hand-drawn flyovers | Located, p 0.043, about 1 m |
| Synthetic through the whole service (the repeatable demo) | Located, p 0.031, within about 71 m, in about 1 min 45 s |
| Synthetic, two flyovers | Candidates; the true place ranked first, unconfirmed |
| Synthetic audio against real UAE flight days (no possible match) | "No match", p 0.75: no location claimed |
| UAE track integrity, one day | 11.5% of track points failed a check |

## 10. Limits and open work

**Of the method**

- Only one real recording has been verified. No UAE recording with a known position exists.
- A `located` verdict with p between 0.01 and 0.1 is weak: the library's author saw two of
  twenty searches with no right answer called located. The app labels these "Located, weak".
- The fit of a flyover is the weak link; three grid phases fixed the one failure found.
- Wind is not modelled. A wrong temperature moves the answer by kilometres.
- Helicopters pass the propeller filter but are outside what the method was validated on.
- Only aircraft in the public archive count. In the UAE that is mainly light training
  aircraft in one corridor (Dubai South towards Al Ain), in daytime.
- The exact date must be known, and the audio must be uncut.

**Of the data handling**

- The automatic update fetches only the newest day for one region; a local day needs two
  UTC days. Fetches cannot be resumed or cancelled. Flight days are never pruned.
- A result records its inputs but not the engine or app version.
- One search at a time, one machine, SQLite, no backups.
- OpenStreetMap's tile server is for light use, and it sees roughly where each located
  result is. `MAP_TILES_URL=` (empty) avoids it.

**Of the interface**

- No phone layout. A screen reader was never run. Drawing a custom area needs a pointer.
- Candidates and Searching use the dot map; the printed report has no map.
- Automatic flyover suggestions are often on the wrong part of a tone.
- The audit log can only be read from the database.

**Of the engineering**

- No CI. The backend suite takes about 13 minutes on eight Linux cores and about 27 on the
  presenting Mac (one engine worker). Frontend tests cover only pure functions.
- On the Mac a synthetic Located search takes about 4 to 4.5 minutes, against 1 min 45 s on
  Linux; macOS gives the engine one worker (rule 7).
- Docker was built and run once by hand, never from an empty clone. The last Docker changes
  (forwarded address, security headers) were checked outside Docker only.
- HTTPS is not provided; a deployment's own proxy must add it and set `SESSION_SECURE=1`.
- A password change does not end sessions that are already open.
- No demo video. Nothing has been pushed to a remote.

## 11. The next step: a first UAE field test

The owner plans to make a recording in the UAE at a known position, to give the project its
first local evidence. What was worked out for it:

- **The clip must hold three or more passes in one continuous recording.** A one or two
  minute clip cannot work: one pass alone takes about 100 seconds. Expect 20 to 60 minutes.
- **Place and time**, counted from the two flight days on disk (18 and 19 November 2026,
  both weekdays), as light-aircraft passes within 2.5 km per day:

  | Place | Passes | Busiest hours (local) |
  |---|---|---|
  | 24.84 N, 55.19 E (desert north-west of Bab Al Shams) | 60 to 70 | 08:00 to 13:00 |
  | 24.82 N, 55.23 E (Bab Al Shams end of Al Qudra Road) | 31 to 43 | 08:00 to 13:00 |
  | 24.8123 N, 55.1101 E (a spot the owner chose) | 38 to 40 | 12:00 to 16:00 |
  | Al Qudra Lakes, Expo City, Dubai Parks, Al Maktoum airport itself | 0 to 3 | |

  Nearly all are Cirrus SR22 training aircraft. The counts come from
  `scripts/coverage_report.py --site NAME LAT LON --radius 2500`. What is on the ground at
  those coordinates was not checked.
- Record outdoors, phone still and shielded from wind, voice-enhancement off, original file
  not trimmed or re-sent through a messaging app. Note the exact position, date and
  temperature. Upload a day later, when the flight archive has that day.
- A correct match may still come out as Candidates: the UAE has so few propeller aircraft
  that the verdict is often short of wrong pairs to judge against.

## 12. Running it

Needs Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node 20+, and `ffmpeg` and
`ffprobe` on the path. Linux gives multi-core searches.

```bash
uv sync
npm --prefix frontend ci
cp .env.example .env            # set APP_SECRET, ADMIN_EMAIL, ADMIN_PASSWORD; for the demo also DEFAULT_PACK=test and SHOW_DEV_PACKS=1
uv run python -m app.cli demo   # installs the synthetic recording and its invented flight day
scripts/dev_backend.sh          # the api on port 8000 and the worker
npm --prefix frontend run dev   # in a second terminal: http://localhost:5173
```

With Docker: `mkdir -p data && docker compose up --build`, then http://localhost:8080. The
demo walk-through (which region, date and boxes) is in `README.md`, "The demo".

**Tests**

```bash
uv run pytest                       # about 13 minutes
uv run pytest -m "not slow"         # skips the detection test
npm --prefix frontend test          # 16 tests
npm --prefix frontend run build     # type-check and production build
```

**Settings** (`.env`; every one is described in `.env.example`)

| Setting | Default | Meaning |
|---|---|---|
| `APP_SECRET`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` | none | session signing key; the first account, created once |
| `DATA_DIR` | `data` | where everything is kept |
| `DEFAULT_PACK` | `uae` | the region offered first, and the one kept up to date |
| `SHOW_DEV_PACKS` | 0 | offer the synthetic test pack |
| `FLIGHTS_AUTO` | 1 | fetch the newest flight day after sign-in |
| `WEATHER_AUTO` | 0 | look up the temperature from Open-Meteo |
| `MAP_TILES_URL` | OpenStreetMap | tile host for the located map; empty switches it off |
| `PLACEBO_DAYS` | 0 | repeat each search on other days as a control |
| `RETENTION_DAYS` | 0 | delete cases older than this; 0 keeps everything |
| `SESSION_HOURS`, `SESSION_SECURE` | 12, 0 | session length; HTTPS-only cookie |
| `LOGIN_FAILURES_MAX`, `LOGIN_FAILURES_WINDOW_MIN` | 10, 15 | sign-in limit per address |
| `DOPPLER_WORKERS` | all cores on Linux, 1 elsewhere | workers handed to the engine |
| `MAX_PARALLEL_JOBS`, `FIT_WORKERS` | 1, 3 | compute jobs at once; editor fit processes |
| `MAX_UPLOAD_MB`, `MAX_DURATION_H` | 2048, 6 | upload limits |
| `RATE_UPLOADS_PER_HOUR`, `RATE_SEARCHES_PER_HOUR`, `RATE_FETCHES_PER_HOUR` | 30, 60, 8 | per-user limits |
| `JOB_TIMEOUT_TRIAGE_S`, `JOB_TIMEOUT_FETCH_S`, `JOB_TIMEOUT_SEARCH_S` | 3600, 3600, 7200 | time limits per job |

What reaches outside the machine: flight data from GitHub, the aircraft type table from
OpenSky, terrain tiles from AWS, temperature from Open-Meteo (only if switched on), map
tiles from OpenStreetMap (from the analyst's browser), and Google Maps when its link is
pressed. The table is in `README.md`, "Configuration".

## 13. Working on it

Conventions the project has kept, which a new contributor should keep too:

- Write the test first; keep `uv run pytest` green before moving on.
- When a decision is made or a plan changes, add a dated line to
  `docs/09-risks-and-open-questions.md` and fix the doc that is now wrong.
- Report what was measured and what was not. Docs say "not checked" where that is the case.
- Commit small, with the milestone or the subject in the message.

Traps that cost time during the build:

- **A fit depends on how the box is aligned** to the engine's 1 Hz frequency grid
  (`docs/02-dopplertrack.md`, behaviour 16). Use `events.fit_many`, never a single fit.
- **Never run two workers on one data folder.** Stop the Docker stack before starting
  `scripts/dev_backend.sh`, and the reverse.
- **Tests must not reach the network.** Flight, weather and archive lookups are stood in
  for; `conftest.py` sets `WEATHER_AUTO=0` and `PLACEBO_DAYS=0`.
- **A flight-day fetch does not create its folders** when run through the library's own
  command line, and fails only after the whole download.
- **Docker creates a missing `./data` as root**, and the containers run as the host user,
  so make the folder first.
- **CSS class names are global.** A new `.flights` class once collided with the result
  page's flight list.
- **The true temperature does not give the highest score.** Compare temperature runs by
  which flights they matched, not by score.

## 14. History

Oldest first.

| Commit | What |
|---|---|
| `5734db0` | M0: project setup, dopplertrack pinned, smoke test and coverage self-test pass |
| `7c0c2bc` | M0: UAE coverage probe for 2026-11-19, findings and decisions |
| `ef95518` | M0: Oyster Bay reference fetched and reproduced |
| `3c2f8d6` | M1: core pipeline, no web |
| `f9cf2ae` | M1: note the Oyster Bay run through our orchestration |
| `88f5464` | M2: service: database, worker, jobs, API, event stream, sign-in, audit |
| `e8040b4` | M3: report flow UI, and a search fit that does not depend on box alignment |
| `0748732` | UAE pack with real boundaries; region chooser and sea labels in the UI |
| `b3ec820` | M4: Searching and result screens, map layers and camera, printable report |
| `48ad221` | M5: flight days on request with an integrity filter, automatic temperature, controls |
| `4e2e8bb` | M6 (part): Cases list, error states, motion and keyboard pass, Docker, README, demo script |
| `b4d5786` | M6: docs for the polish pass |
| `b09369a` | Add the MIT licence for TRACE's own code |
| `26f911f` | M6: Docker Compose stack built and run; tick the milestone |
| `983e7fa` | Newest flight day after sign-in, street map for Located results, back arrow, themed region menu |
| `3eafa9e` | Review fixes: case deletion and retention, accounts, sign-in limit, real client address, ffmpeg guard, worker watchdog |

## 15. Credits and licences

- TRACE's own code: MIT (`LICENSE`).
- [dopplertrack](https://github.com/mjshiggins/dopplertrack) by MacCallister Higgins: MIT. The search engine.
- Flight tracks from adsb.lol and boundaries from OpenStreetMap contributors: Open Database
  License 1.0. Extracts must stay under it if published.
- Temperature from Open-Meteo: CC BY 4.0, free for non-commercial use.
- Aircraft types from ICAO Doc 8643 via the OpenSky Network; elevation from AWS Terrain Tiles.
- Leaflet: BSD 2-Clause. Typefaces Instrument Sans and DM Mono: SIL Open Font License.
- The technique was first shown in colsto's video "I discovered a sound that leaks your exact location".

**Intended use.** Built for cybercrime investigation and footage verification by accountable
users. It is not a public service and must not be used to locate private individuals.
