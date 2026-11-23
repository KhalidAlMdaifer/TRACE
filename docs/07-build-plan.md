# Build plan

Seven milestones. Each ends with something that runs and a test that proves it. Do them in
order; do not start UI work before milestone 1 passes.

Conventions: tests live in `backend/tests/`; "synthetic case" means the three-flight scenario
in `scripts/smoke_dopplertrack.py`, moved into `backend/tests/fixtures/synth.py` and
parameterised.

## M0. Ground truth about the environment and the data

Tasks

1. `git init`; create the uv project at the repo root (Python 3.12); add dopplertrack pinned to commit `2d899bb...` (see `02-dopplertrack.md`); add pytest.
2. Confirm `ffmpeg -version` and `ffprobe -version` work.
3. Run `uv run python scripts/smoke_dopplertrack.py --hot --decoys 25 --editor`. Expect `SMOKE TEST PASSED` after about five minutes on one worker, the hot uncorrected run kilometres off, the decoy run `located` only with the third flyover, and the editor block's `ok: true`. Note the timings it prints next to the ones in `02-dopplertrack.md`; if this machine is much slower, say so before M2.
4. Run `uv run python scripts/coverage_report.py --self-test`.
5. Coverage probe for the UAE: create `data/flights/uae` and `data/coverage`, then fetch three or four recent days with `--keep-jets --traces` and run the report on each (`04-data.md`, section 9). **Ask the user before starting**: each day streams about 4 GB, and the fetch fails at the very end if the output folder is missing.
6. Write the findings into `docs/coverage-findings.md`: passes per site per day, hours, aircraft types, share of points with low integrity if visible.
7. Ask the user whether to obtain the Oyster Bay recording for the New York demo pack.

Done when: both scripts pass on the user's machine, and the coverage findings say where and when a UAE recording has a chance. If the answer is "almost nowhere", stop and tell the user before building further; the New York pack and the synthetic demo still stand.

## M1. Core pipeline, no web

Tasks

1. `core/media.py`, `core/spectro.py`, `core/events.py` with tests on synthetic audio (a WAV written by the fixture and decoded through ffmpeg). `events.fit` and `events.preview` start as copies of `fit_box` and `fit_preview` from the smoke script; `events.propose` is the sliced fast detection in `05-architecture.md`, section 3; `spectro` stores plain `.npy` arrays and loads slices memory-mapped.
2. `core/flights.py`: `utc_days_for`, trace cache layout, `load_window`, `build_index`, `count`. Test the local-day to UTC-days mapping for Asia/Dubai and America/New_York (including a daylight-saving date).
3. `core/geo.py` with a tiny test pack (two square regions) and polygon tests; `core/weather.py` with the monthly fallback only.
4. `core/search.py` orchestration and `core/confidence.py` (`06-confidence.md`), tested on the synthetic case with decoy flights added so the verdict has a null.
5. `app/cli.py`: `python -m app.cli run FILE --date 2026-11-14 --pack test --events events.json --temperature 28` prints the result JSON.

Acceptance tests

- `test_fit_recovers_truth`: on the smoke script's `BEND_BOXES`, f0 within 2 Hz, speed within 25 m/s, heard time within 6 s.
- `test_narrow_box_does_not_raise` (110 to 140 Hz), `test_tiny_box_rejected`, `test_slice_fit_equals_full_fit`, `test_preview_close_to_full` (score within 0.5, under 5 s).
- `test_propose_finds_flyovers` (slow): at least two of the three synthetic flyovers have a proposal within 25 s; `on_slice` fires once per slice.
- `test_search_refits_at_search_temperature`: previews made at 15 C, search at 28 C on 28 C audio still finds the observer.
- `test_search_finds_observer`: truth within 600 m on the 200 m lattice, within 100 m after refine with the third flyover.
- `test_wrong_temperature_misses`: 25 C error, estimate more than 2 km off or band not High.
- `test_two_events_are_candidates`, `test_three_events_located` (with 25 decoy pairs per pair of real flights from `core/synth.add_decoys`; M1 measured "no match, p 0.93" with the truth ranked first, and "located, p 0.0004"), `test_no_events_not_locatable`, `test_outside_constraints`.
- `test_utc_days`.
- If the reference data is present: dopplertrack's Oyster Bay check passes through our orchestration.

Done when: `uv run pytest` is green and the CLI produces a result for the synthetic file.

## M2. Service

Tasks: `db.py` with the schema in `05-architecture.md`; `worker.py` with one child process per job and per-kind time limits; the triage job (decode, spectrogram, sliced detection emitting `proposals`) and the search job (refit, then search); the api's fit pool for editor previews; `api/` routes; the event stream; login and the audit log; `.env.example`.

Acceptance tests

- Upload a synthetic file through the API, wait for `spectrogram_ready`, post the three bend boxes as events, start a search without waiting for detection to finish, read the stream to `done`, fetch the result. All through HTTP in one test.
- The stream carries one `proposals` event per slice with rising `done_s`, then `triage` `done`.
- `POST /events` answers in under 5 s with a fitted curve while a triage job is running; a 110 to 140 Hz box returns 200, a 1 Hz box returns 422 `box_too_small`.
- `POST /search` returns 409 without a case reference or with fewer than two confirmed events.
- A cancelled search leaves the job `cancelled` and the worker alive.
- Every state-changing call appears in `audit_log`.
- Killing the api mid-search and restarting it, the stream resumes from `Last-Event-ID`.

Done when: a case can go from upload to result with `curl` alone.

## M3. Report flow UI

Tasks: Vite app, tokens, `AppShell`, `DotMap` (land cells and selection only), `Dropzone`, `WhenStep`, `WhereStep`, the flyover editor (tiled spectrogram canvas, proposals arriving from the stream, draggable boxes with fitting, confirmed and failed states, fitted curve overlay), `ReviewStep`.

Done when: a user can sign in, upload, set date, time and area, confirm or draw two flyovers (before or after detection finishes) and press submit, and each screen matches its mockup at 1440 px wide, including the flyover editor (`design/mockups/Flyovers.dc.html`, with the behaviour notes in `08-design.md`, section 4).

## M4. Searching and results UI

Tasks: `ProgressTimeline` on the stream; `DotMap` match-strength cells, flight paths, camera; `ResultCard` (located), `CandidatesCard`, outside-match banner, `NotLocatableCard`; report page.

Done when: the synthetic case shows Located with three flyovers and Candidates with two; a file with no flyovers shows Not locatable; the report prints to PDF from the browser.

## M5. Real regions and data operations

Tasks: UAE pack with real boundaries and Abu Dhabi sub-areas; New York demo pack; `flight_days` management with a fetch job and the "data for this date is not loaded yet" state in the When step; integrity filter; automatic temperature; placebo-day control behind a setting.

Done when: the New York demo runs end to end from the UI (if the recording was obtained), and a UAE date can be fetched and searched.

## M6. Polish and submission

Tasks: motion pass against `08-design.md`; keyboard and screen-reader pass; empty, loading and error states; Docker Compose; README with what it is, how to run it, evidence, limits, intended use, data attributions and the dopplertrack licence notice; a two-minute demo script and video.

Done when: a clean clone runs with `docker compose up` and the README's quick start works as written.

## If time is short

| Time left | Ship |
|---|---|
| A day | M0, M1, and a single-page UI that uploads, shows the spectrogram, lets the analyst mark two or three flyovers and shows the result for the synthetic and New York cases. Skip auth polish, packs UI, controls. |
| Three days | M0 to M4 on the synthetic and New York cases; UAE pack with the coverage findings shown plainly. |
| A week or more | Everything. |

In every case the demo should show three things: a located result on a recording with a known answer, a candidates result, and a not-locatable result reached quickly.

## Working rhythm for each task

1. Read the relevant doc section. 2. Write or update the test. 3. Implement. 4. Run `uv run pytest` (and the frontend type-check once it exists). 5. Tick the milestone in `CLAUDE.md`, note any decision in `09-risks-and-open-questions.md`. 6. Commit with a message that names the milestone.
