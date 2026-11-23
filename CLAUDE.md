# TRACE: Doppler video geolocation (hackathon MVP)

TRACE stands for Tracking Recordings via Aircraft Curve Estimation.

A web app for cybercrime analysts. The analyst uploads a recording, gives its date, a
time-of-day window and a rough area (UAE emirates), confirms the aircraft flyovers found in
the audio, and gets back ranked location leads with a verdict, or a clear "not locatable".
It works by matching the Doppler curves of propeller aircraft in the audio against
historical flight tracks, using the open-source `dopplertrack` library as the engine.

**Status: M0 to M6 done.** The UI (`frontend/`) covers the whole flow: sign-in, Upload, When,
Where, the flyover editor, Review, Searching, and the Located, Candidates and Not locatable
results with a printable report. Flight days are fetched on request, and the newest published day
automatically after sign-in (`FLIGHTS_AUTO`), through an integrity
filter, and the temperature is looked up automatically. The Docker Compose stack was built and run on 2026-11-22; what is left is recording the
demo video. The core pipeline is in `backend/app/core` and runs
from the terminal (`python -m app.cli`); the service (`backend/app/api`, `worker.py`,
`jobs/`) takes a case from upload to result over HTTP. The reference
implementations from `scripts/smoke_dopplertrack.py` now live in `core/events.py` (`fit`,
`preview`) and `core/synth.py` (`synth_case`, `add_decoys`). Start with
`docs/00-START-HERE.md`.

## Rules that do not bend

1. **Build on dopplertrack; do not reimplement it.** Pin commit `2d899bbfe1529e2b4351f328969bb37776d57cb4`. Its real CLI and API are in `docs/02-dopplertrack.md`; trust that file over memory.
2. **A result is a lead.** Always show the verdict, p value, uncertainty radius and number of flyovers. Never a bare pin.
3. **Two flyovers give candidates, not a location.** "Located" needs three or more flyovers on one clock and a `located` verdict. Evidence in `docs/03-method-and-evidence.md`.
4. **"Not locatable" and "candidates" are designed outcomes**, not errors. Most recordings will end there; get there fast and say why.
5. **The analyst confirms every flyover.** Automatic detection proposes, slowly and imperfectly; the analyst's box around each curve's bend is what gets fitted and searched. Never call `fit_event` with the raw box: use the widening rule (`docs/02-dopplertrack.md`, behaviour 11).
6. **Pass the real air temperature** as `c=speed_of_sound(T)` to every fit and search. The library default is 15 C; a 25 C error moved a synthetic answer 7.7 km.
7. **One search per OS process**, and `workers=1` unless on Linux. The library forks and keeps module-global state.
8. **Gated tool.** Sign-in, a required case reference, an audit log on every upload, search and export. No anonymous endpoint. The same method can locate a private person's home.
9. **No invented data.** Values in the mockups are samples. Measure or mark unknown.
10. **Ask before large or outward actions:** streaming flight data (about 4 GB per day), downloading the reference recording, pushing to GitHub.

## Environment

- Python 3.12 or newer, managed with `uv`. `ffmpeg` and `ffprobe` on PATH. Node 20 or newer for the frontend.
- Linux, or Docker or WSL, for multi-core search. macOS runs one worker (measured on an M4 on 2026-11-24: a synthetic Located search in about 4 to 4.5 min, the backend suite in about 27 min). Windows must pass `workers=1` or use Docker.
- The tests set `TRACE_DOTENV=0`, so a local `.env` never reaches them.
- Network is needed for: flight data (GitHub: when a user asks for a day, and the newest day after sign-in unless `FLIGHTS_AUTO=0`), terrain tiles (AWS), the aircraft type table (OpenSky), the weather archive (Open-Meteo, only with `WEATHER_AUTO=1`), and, from the analyst's browser, map tiles for a Located result (OpenStreetMap, unless `MAP_TILES_URL` is empty). Fonts are bundled. `DOPPLERTRACK_CACHE` defaults to `data/cache/dopplertrack`.

## Commands

```
uv run python scripts/smoke_dopplertrack.py --hot --decoys 25 --editor   # engine check, about 5 minutes; plain run is 30 s
uv run python scripts/coverage_report.py --self-test             # report logic check
mkdir -p data/flights/uae data/coverage                          # fetch does not create folders; it fails after the whole download
uv run dopplertrack fetch YYYY-MM-DD data/flights/uae/YYYY-MM-DD.npz \
    --bbox 22.6 26.1 51.5 56.4 --keep-jets --traces data/flights/uae/YYYY-MM-DD-traces.npz
uv run python scripts/coverage_report.py data/flights/uae/YYYY-MM-DD-traces.npz --out data/coverage/YYYY-MM-DD
uv run pytest                                                    # about 13 minutes: fits, searches and the service end to end on the synthetic case
uv run pytest -m "not slow"                                      # skips the detection test
uv run pytest -m reference                                       # the full Oyster Bay search through our code, about 5 minutes; needs data/reference/oyster_bay
uv run python -m app.cli synth /tmp/trace-demo                   # write a synthetic recording with a known answer; prints the run command
uv run python -m app.cli user add someone@example.org            # an account for each analyst; also `user passwd`, `user list`
uv run python -m app.cli run FILE --date 2026-11-14 --pack test --events events.json --temperature 28   # result JSON on stdout
```

The service is two processes on one data folder (settings in `.env`, see `.env.example`):

```
uv run uvicorn app.api.main:app --port 8000      # the api; needs APP_SECRET, ADMIN_EMAIL, ADMIN_PASSWORD
uv run python -m app.worker                      # the job loop: one child process per triage or search job
scripts/curl_walkthrough.sh /tmp/trace-demo      # a case from upload to result with curl, on the synthetic recording
```

The frontend is Vite, React and TypeScript in `frontend/`; its dev server proxies `/api` to port 8000:

```
scripts/dev_backend.sh                           # the api and the worker together, settings from .env
npm --prefix frontend run dev                    # http://localhost:5173
npm --prefix frontend run typecheck              # tsc
npm --prefix frontend test                       # vitest: the step machine and formatting
npm --prefix frontend run build                  # type-check, then a production build in frontend/dist
```

With Docker: `mkdir -p data && docker compose up --build`, then http://localhost:8080 (see `README.md`). `uv run python -m app.cli demo` installs the synthetic demo case into the data folder.

For a local run: `.env` (not in git) holds the sign-in; `SHOW_DEV_PACKS=1` adds the synthetic test pack to the region chooser on Upload;
`data/demo/synthetic.wav` is a recording with a known answer, and its flight day is in `data/flights/test/`.

The package is `app` in `backend/` (installed editable by uv); tests are in `backend/tests/`.
`test_api.py` runs the api in process; `test_api_e2e.py` starts a real api and worker.

## How to work here

- One milestone at a time, in the order of `docs/07-build-plan.md`. Each has acceptance tests; write the test first.
- Keep `uv run pytest` green before moving on.
- When a decision is made or a plan changes, add a dated line to `docs/09-risks-and-open-questions.md`, and fix the doc that is now wrong.
- When something in these docs disagrees with the dopplertrack source, the source wins; update the doc.
- Commit small, with the milestone in the message.

## Where things are

| Need | Read |
|---|---|
| The whole project in one file, for someone new | `HANDOFF.md` |
| Orientation, setup, first steps | `docs/00-START-HERE.md` |
| What we are building and the result states | `docs/01-product.md` |
| The engine's CLI, API, defaults, traps, measured timings | `docs/02-dopplertrack.md` |
| Physics, evidence, what we can promise | `docs/03-method-and-evidence.md` |
| Flight data, trace format, time zones, packs, temperature | `docs/04-data.md` |
| Processes, fit pool, modules, schema, API, stream, triage and search orchestration | `docs/05-architecture.md` |
| Verdict, bands, controls | `docs/06-confidence.md` |
| Milestones and acceptance tests | `docs/07-build-plan.md` |
| Look, screens, copy, motion, what the mockups leave out | `docs/08-design.md`, `design/mockups/` (nine screens), `design/tokens.css` |
| Risks, decisions, open questions | `docs/09-risks-and-open-questions.md` |
| Where and when the UAE has propeller traffic | `docs/coverage-findings.md` |
| Rebuilding the UAE pack from boundary data | `scripts/build_uae_pack.py` |
| Running it, the demo, evidence and limits for a reader | `README.md`, `docs/demo-script.md` |

## Status

- [x] M0 environment, scripts, UAE coverage probe (one day, 2026-11-19; findings in `docs/coverage-findings.md`; Oyster Bay reference fetched and verified, see `docs/03-method-and-evidence.md`)
- [x] M1 core pipeline, no web (`backend/app/core`, `python -m app.cli`; notes in `docs/09`, decisions of 2026-11-21)
- [x] M2 service: database, jobs, API, stream, auth, audit (`backend/app/api`, `worker.py`, `jobs/`; 64 tests; `scripts/curl_walkthrough.sh`)
- [x] M3 report flow UI, including the flyover editor (`frontend/`; checked in the browser at 1440 px on the `test` pack; Searching and Result are a stand-in until M4)
- [x] M4 searching and results UI (Searching, Located, Candidates, outside-match banner, Not locatable, printable report; checked in the browser on the synthetic case)
- [x] M5 real regions, data operations, integrity filter, temperature, controls (UAE and New York packs; fetch job with the integrity filter; automatic temperature from Open-Meteo; placebo-day control off by default; the New York demo runs end to end)
- [x] M6 polish, README, Docker, demo (the README's non-Docker quick start verified from a clean clone; `docker compose up --build` run on 2026-11-22 from the working tree with the existing `./data`: sign-in and a synthetic case to Located through the containers. Not done: the Docker quick start from an empty clone, a demo video, a screen-reader run)
