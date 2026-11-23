# Hardening before the hackathon: design

Date: 2026-11-24. Status: awaiting the owner's approval.

## Intent

TRACE will be presented at a hackathon within about 36 hours of 2026-11-23. The owner chose
to harden the codebase first and decide the presentation afterwards. "Hardened" here means:
the app runs on the presenting machine, its tests pass there, and nothing a presenter or a
judge is likely to do makes it fail, hang or reach for the network unexpectedly.

## Where it stands (measured 2026-11-24 on the presenting machine)

- Apple M4, 10 cores, 16 GB, macOS. Node 22 and Homebrew are installed.
- `uv`, `ffmpeg`, `ffprobe` and Docker are missing. No `.venv`, `node_modules`, `.env` or `data/`.
- Not a git repository: the folder is the archive of tracked files only.
- Nothing has been run here. Every timing and test result in the docs comes from an 8-core
  Linux laptop. On macOS the engine gets one worker (rule 7).
- Read so far: `worker.py`, `db.py`, `jobs/runner.py`, `api/main.py`, `deps.py`, `auth.py`,
  `fitpool.py`, `config.py`. No defect found by reading. The code is written for Linux first
  (process groups, `nice`, spawn); macOS behaviour is unverified, not known to be broken.

## Goals

1. The backend suite and the frontend suite pass on this Mac, or every failure is understood
   and either fixed or recorded as a known macOS limit.
2. The synthetic case goes from upload to Located through the real UI on this Mac, with the
   time measured.
3. The demo cannot be derailed by the network: no automatic 4 GB fetch, caches warm, a
   Located result that still renders with no connection.
4. Failure paths a judge can trigger behave: bad file, wrong password, cancel mid-search,
   reload mid-search, api or worker restarted mid-search.
5. The work is in git from the first minute.

## Non-goals

- New features, the presentation itself, a UAE field recording.
- HTTPS, deployment, CI, multi-user scale, a phone layout.
- Changing the method, the engine or any of the ten rules in `CLAUDE.md`.

## Anti-goals

- Making tests pass by weakening them.
- Any fix that invents data or shows a result without verdict, p value, radius and flyovers.
- Starting a flight-data stream or a recording download without the owner's yes (rule 10).

## Approaches considered

- **A. Run it, then fix what breaks (chosen).** Stand the app up on this Mac, run both
  suites and the end-to-end flow, and let real failures set the fix list; then a short,
  targeted read of the paths a demo exercises. Cheapest way to find what is actually wrong.
- **B. Audit by reading first.** A full review of all 10,400 lines before running anything.
  Dropped: the code has already had a review-and-fix pass, and reading has not found a
  defect; the unknown is this machine, which only running reveals.
- **C. Move the demo to Linux in Docker and harden only that.** Gives all ten cores to a
  search. Kept as step 6, not as the base: it adds an install and a second environment, and
  the native path must work anyway as the fallback.

## The work, in order

1. **Baseline.** `git init` and a first commit of the archive as received. Install `uv` and
   `ffmpeg` with Homebrew. `uv sync`, `npm --prefix frontend ci`. Write `.env` from
   `.env.example` with a generated secret, a local sign-in, `DEFAULT_PACK=test`,
   `SHOW_DEV_PACKS=1` and `FLIGHTS_AUTO=0`.
2. **Engine check.** The smoke test (plain, then `--hot --decoys 25 --editor`) and the
   coverage self-test. Record the timings next to the Linux ones in `docs/02-dopplertrack.md`.
3. **Suites.** `uv run pytest` (in the background, about 13 minutes on Linux, expected
   longer here), `npm --prefix frontend test`, `npm --prefix frontend run build`. Each
   failure is debugged to its cause before any fix.
4. **End to end in the browser.** `app.cli demo`, start the api, worker and frontend, and
   walk the synthetic case to Located, Candidates (two boxes) and Not locatable. Measure
   the search time on one worker.
5. **Failure paths.** A non-media file, an over-long file, a wrong password, cancel
   mid-search, reload mid-search, kill and restart the api and the worker mid-search, two
   browser tabs on one case, network off on a Located result. Fix what misbehaves, test first.
6. **Search speed.** If the one-worker search is too slow to show, try the Docker stack
   (OrbStack or Docker Desktop, the owner's choice) for a multi-core search, and verify the
   quick start from an empty clone, which the docs list as never done.
7. **Record.** Dated lines in `docs/09-risks-and-open-questions.md`; correct `HANDOFF.md`,
   `README.md` and `CLAUDE.md` where this machine showed them wrong.

Time box: about 12 hours of the 36, steps 1 to 5 first. Steps 6 and 7 give way if the
presentation needs the time.

## Calls made by the builder, for the owner to correct

- `FLIGHTS_AUTO=0` in the local `.env`. Its default of 1 starts a 4 GB download at sign-in,
  which on a venue network could stall the demo. The code default is left alone.
- Homebrew for `uv` and `ffmpeg`, not the `uv` install script.
- Fixes go straight onto `main` in small commits; no branches or worktrees for a solo,
  time-boxed pass.
- The slow detection test and the Oyster Bay reference test are not required for "hardened".

## Left to the builder

The order of fixes within a step, and whether a failure is fixed or recorded as a limit,
judged by whether a presenter or judge could hit it.
