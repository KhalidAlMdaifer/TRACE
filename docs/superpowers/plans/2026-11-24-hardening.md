# Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TRACE runs, passes its tests and survives the failure paths a judge could trigger, on the presenting Mac.

**Architecture:** No new features. Stand the existing app up on macOS, let real failures set the fix list, fix each with a test first, and record what this machine showed.

**Tech Stack:** Python 3.12+ with uv, FastAPI, SQLite, dopplertrack at `2d899bb`; Vite, React, TypeScript; ffmpeg; Homebrew.

**Spec:** `docs/superpowers/specs/2026-11-24-hardening-design.md`

## Global Constraints

- The ten rules in `CLAUDE.md` hold. In particular: no flight-data stream or recording download without the owner's yes (rule 10); every result shows verdict, p value, radius and flyovers (rule 2); `workers=1` off Linux (rule 7).
- Never weaken a test to make it pass. A failure is debugged to its cause (superpowers:systematic-debugging) before a fix.
- Local `.env`: `FLIGHTS_AUTO=0`, `RETENTION_DAYS=0`, `DEFAULT_PACK=test`, `SHOW_DEV_PACKS=1`, `WEATHER_AUTO=0`. Code defaults are not changed.
- Commits are small, on `main`, message names `hardening`, ending with the attribution line from the session.
- Each fix adds a dated line to `docs/09-risks-and-open-questions.md`.
- Time box: about 12 hours; Tasks 1 to 5 first.

## Review Focus

1. **macOS process handling:** `os.setsid`, `os.killpg`, `nice` and spawn on Darwin. Cancelling a search must stop the child and anything it forked, with no orphan process left (`pgrep -f trace-search` empty afterwards). Owned by Task 5.
2. **`.env.example` ships `RETENTION_DAYS=30`** while the code default is 0. Someone copying it gets automatic deletion. Expected: the example says 0. Owned by Task 1.
3. **Venue network down:** a Located result must still render. Expected: the street map falls back or shows blank tiles, and the verdict, p value, radius and flyovers are still visible. Owned by Task 5.
4. **Reload or second tab mid-search:** the Searching screen must resume from the stream without starting a second search. Owned by Task 5.
5. **First run with an empty `data/`:** the api and the worker create what they need; the demo installs with one command. Owned by Task 1.

---

### Task 1: Baseline

**Files:**
- Create: `.env` (not in git), `data/` (not in git)
- Modify: `.env.example` (`RETENTION_DAYS=30` → `RETENTION_DAYS=0`, with its comment unchanged)

- [ ] **Step 1:** `git init -b main`, `git add -A`, commit "Archive as received". Check `.env`, `data/` and `node_modules/` are ignored (`git status --ignored`).
- [ ] **Step 2:** `brew install uv ffmpeg`. Expected: `uv --version`, `ffmpeg -version`, `ffprobe -version` all print.
- [ ] **Step 3:** `uv sync` and `npm --prefix frontend ci`. Expected: both exit 0; dopplertrack resolved at commit `2d899bb` (`uv pip show dopplertrack`).
- [ ] **Step 4:** Write `.env` from `.env.example` with a generated `APP_SECRET` (`secrets.token_urlsafe(32)`), `ADMIN_EMAIL=admin@trace.test`, a generated `ADMIN_PASSWORD` of at least 10 characters, and the Global Constraints values. Do not repeat the password in chat; tell the owner it is in `.env`.
- [ ] **Step 5:** Fix `.env.example`'s `RETENTION_DAYS` to 0. `mkdir -p data`. `uv run python -m app.cli demo`. Expected: it writes `data/demo/synthetic.wav` and a flight day under `data/flights/test/`.
- [ ] **Step 6:** Commit `.env.example`: "hardening: .env.example keeps cases by default, as the code does".

### Task 2: Engine check

- [ ] **Step 1:** `uv run python scripts/coverage_report.py --self-test`. Expected: passes.
- [ ] **Step 2:** `uv run python scripts/smoke_dopplertrack.py`. Expected: `SMOKE TEST PASSED` in about 30 s on Linux.
- [ ] **Step 3:** In the background, `uv run python scripts/smoke_dopplertrack.py --hot --decoys 25 --editor`. Expected: `SMOKE TEST PASSED`; hot run kilometres off; decoy run `located` only with the third flyover; editor block `ok: true`.
- [ ] **Step 4:** Add this machine's timings beside the Linux ones in `docs/02-dopplertrack.md`. Commit.

### Task 3: Suites

- [ ] **Step 1:** `npm --prefix frontend run typecheck`, `npm --prefix frontend test`, `npm --prefix frontend run build`. Expected: 16 tests pass; build exits 0.
- [ ] **Step 2:** In the background, `uv run pytest -m "not slow" -x -q`, then `uv run pytest -m slow -q`. Expected: all pass except the skipped `reference` test.
- [ ] **Step 3:** For each failure: reproduce it alone, find its cause, write or adjust the narrowest test that shows the macOS case, fix, re-run that test, then the file. One commit per fix: "hardening: <what> on macOS".
- [ ] **Step 4:** Full `uv run pytest` green. Record the wall time.

### Task 4: End to end in the browser

- [ ] **Step 1:** `preview_start` for `backend` and `frontend` (`.claude/launch.json`). Sign in at http://localhost:5173.
- [ ] **Step 2:** Upload `data/demo/synthetic.wav` on the `test` pack, use the date and boxes in `README.md`, "The demo", and go to Located. Record the search time. Expected: Located with verdict, p value, radius, three flyovers.
- [ ] **Step 3:** Same recording, two boxes: Candidates. A clip with no tones (any 30 s of `anullsrc` from ffmpeg): Not locatable from the editor in seconds.
- [ ] **Step 4:** Open the printable report for each. Check the browser console and `preview_logs` for errors. Fix what is broken, test first, one commit each.

### Task 5: Failure paths

For each row: try it, compare with the expected behaviour, and fix only on a mismatch, with a test first in `backend/tests/test_api.py`, `test_api_e2e.py` or `frontend/src/*.test.ts`.

| Input | Expected |
|---|---|
| A `.txt` renamed `.wav` | 4xx with a plain message; case stays usable |
| A file over `MAX_DURATION_H` (set it to 0.01 for the check) | refused with a plain message |
| Wrong password 11 times | 401 ten times, then 429 |
| Cancel mid-search | job `cancelled`, case back to triaged, `pgrep -f trace-search` empty |
| Reload, and a second tab, mid-search | both show the same search's stages; one job in `jobs` |
| Kill the api mid-search, restart | stream resumes; result arrives |
| Kill the worker mid-search, restart | job `failed` with `worker_restarted`; the search can be started again |
| Network off, open a Located case | result and its numbers visible; no hang |

- [ ] Run each row. Commit each fix separately.

### Task 6: Search speed

- [ ] **Step 1:** If the Task 4 search took over about 3 minutes, ask the owner whether to install OrbStack or Docker Desktop. Otherwise skip to Step 3.
- [ ] **Step 2:** From an empty clone (`git clone . /tmp/trace-clone`), follow the README's Docker quick start exactly. Expected: sign-in and the synthetic case to Located at http://localhost:8080, faster than native. Stop the native backend first (never two workers on one data folder).
- [ ] **Step 3:** Record which setup the demo will use and its timing.

### Task 7: Record

- [ ] Dated lines in `docs/09-risks-and-open-questions.md` for every fix and finding. Correct `HANDOFF.md` (status, environment, section 10), `README.md` and `CLAUDE.md` where this machine showed them wrong. Commit: "hardening: record what the presenting Mac showed".
