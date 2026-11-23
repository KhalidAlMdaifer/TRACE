# dopplertrack: verified reference

Everything here was read from the source of `github.com/mjshiggins/dopplertrack` at commit
`2d899bbfe1529e2b4351f328969bb37776d57cb4` (4 Nov 2026, version 0.3.0 plus unreleased
changes) and, where marked *ran*, executed by `scripts/smoke_dopplertrack.py`. If you
upgrade the pin, re-run the smoke test and re-read this file against the new source.

The library is the engine. We wrap it; we do not re-derive its physics.

## Install and platform

- MIT licence, copyright 2026 MacCallister Higgins. Keep the notice in our README.
- `requires-python >= 3.12`. Dependencies and the minimums its `pyproject.toml` declares: numpy 2.5.4, scipy 1.18.1, pandas 3.1.0, pillow 13.0.0, requests 2.34.2, matplotlib 3.11.2, soundfile 0.14.0 (declared but not imported by the code read). Build backend `uv_build`. Installs a `dopplertrack` command. Needs `ffmpeg` on PATH.
- Everything marked *ran* in these docs was run from a source checkout on Python 3.13 with numpy 2.5.3, scipy 1.18.1 and pandas 3.0.5, slightly older than those minimums, because packages could not be installed where the planning was done. That is the reason the smoke test is the first task on a new machine.
- It may not be on PyPI. Install from git, pinned:
  `uv add "dopplertrack @ git+https://github.com/mjshiggins/dopplertrack@2d899bbfe1529e2b4351f328969bb37776d57cb4"`
  (check `uv add --help` if that form is rejected).
- **Process pools use `fork`.** `search._pool_map` calls `multiprocessing.get_context("fork")`. Consequences:
  - Linux: default `workers` is every core. Works.
  - macOS: default `workers` is 1 because forking after BLAS use is unsafe. Slower, still correct.
  - Windows: there is no `fork`. Anything above `workers=1` fails. Always pass `workers=1`, or run the worker in Docker or WSL.
- `tracks.detect_events` uses `ProcessPoolExecutor(workers)` with the platform default start method. Inside our worker pass `workers=1` unless on Linux.
- **Module-global state.** `search._G` holds the index and windows for pool workers. Never run two searches in one Python process at the same time. One search per OS process.
- The CLI sets `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, `VECLIB_MAXIMUM_THREADS` to 1 before importing numpy. Do the same at the top of our worker entry point.
- Network calls the library makes on its own: GitHub API and release downloads (`fetch`), `s3.amazonaws.com/elevation-tiles-prod` (terrain tiles), `opensky-network.org/datasets/metadata/doc8643AircraftTypes.csv` (type table, first use). Caches live under `DOPPLERTRACK_CACHE` (default `~/.cache/dopplertrack`). Set it to `data/cache/dopplertrack`.

## CLI (six commands)

```
dopplertrack spectrogram AUDIO OUT.npz [--hop 0.25] [--fmin 40] [--fmax 450]
dopplertrack detect SPEC.npz --band FLO FHI [--harmonics 1] [--top 20] [--window 240] [--max-burst X] [--out detected.json]
dopplertrack fit SPEC.npz --window T0 T1 --band FLO FHI [--harmonics 1] [--objective brightness|contrast] [--out ev.json]
dopplertrack fetch YYYY-MM-DD DAY.npz [--bbox LATMIN LATMAX LONMIN LONMAX] [--archive DIR] [--keep-jets]
                  [--pod planes-readsb-prod-0] [--origin LAT0 LON0] [--traces TRACES.npz]
dopplertrack search SPEC.npz --events EV1.json EV2.json --day DAY.npz --out RES.csv
                  [--utc TIME] [--bbox ...] [--point LAT LON] [--cands CACHE.npz] [--harmonics H1 H2]
                  [--tol S] [--v-tol 0.35] [--d-tol 0.4 2.5] [--max-range 12000] [--spacing 200] [--coarse 1000]
                  [--no-silence] [--no-dem] [--dem-zoom 9] [--workers N] [--score brightness|ridge] [--top 20]
                  [--extra EV3.json ...] [--extra-harmonics ...] [--top-pairs 200] [--out-extra CSV]
dopplertrack refine SPEC.npz RES.csv --events EV1.json EV2.json --day DAY.npz --out FINE.csv
                  [--rank 1] [--spacing 50] [--half 600] [--harmonics H1 H2] [--extra ...] [--no-dem] [--score ...]
```

Notes:

- `--bbox` order is **lat min, lat max, lon min, lon max**. UAE: `22.6 26.1 51.5 56.4`.
- `fetch` takes a **UTC** day, streams about 4 GB from GitHub, stores nothing but the result, drops known jets unless `--keep-jets`, and writes the day index. `--traces` also saves the raw traces, which our coverage report and per-case indexes need. **It writes only at the end and does not create folders:** a missing output folder raises `FileNotFoundError` after the whole download. `mkdir -p` first.
- `search` with one event requires `--utc` (the heard closest-approach time). Two events need only the day.
- `--extra` rescoring is what turns a two-event candidate into a located result (see `03-method-and-evidence.md`).
- The older commands `extract-region`, `fetch-day`, `index-day`, `search-wide`, `search-single` no longer exist. Any text that mentions them is out of date.

## Python API we will call

```python
from dopplertrack import audio, pipeline, search, tracks, doppler
from dopplertrack.adsb import AircraftTypes, Trace, load_traces, save_traces, parse_trace_bytes
from dopplertrack.fetch import fetch_day, release_asset_urls
from dopplertrack.search import DayIndex, run_search, rescore_with_extra
from dopplertrack.terrain import Terrain
from dopplertrack.tracks import EventFit, detect_events, fit_event
from dopplertrack.verdict import verdict
```

| Call | Returns | Notes |
|---|---|---|
| `audio.load_audio(path, sr=4000)` | `(float32 array, sr)` | ffmpeg to mono 4 kHz, whole file in memory: 58 MB per hour of audio, twice that at peak. No timeout of its own |
| `audio.compute_spectrogram(x, sr, nperseg=8192, hop_s=0.25, fmin=40, fmax=450, whiten_window_s=600)` | `Spectrogram` | 2.05 s window, 0.488 Hz bins; `S` is float32 dB above the per-bin running median, 840 rows by 4 columns per second: 48 MB per hour of audio (*ran*: 0.9 s for 30 min) |
| `pipeline.make_spectrogram(audio_path, out_path, hop_s=0.25, fmin=40, fmax=450)` | `Spectrogram` | the two above plus `save` |
| `Spectrogram(t, f, S)`, `.load(path)`, `.save(path)`, `.crop(t0, t1, f0, f1)`, `.sample(t, f)` | | a plain dataclass: fields `t (T,)`, `f (F,)`, `S (F, T)`; `crop` keeps absolute times; `sample` returns 0 outside the grid |
| `tracks.detect_events(sp, f_lo, f_hi, c=None, harmonics=1, window_s=240, step_s=120, f0_step=2.0, t0_step=2.0, n_curve=80, top=20, per_window=3, min_sep_s=60.0, refine=True, workers=None, progress=None)` | `list[EventFit]` sorted by score | sets `burst` on each; proposals only; `progress(done_windows, total_windows)`; with `refine=False` the fits are coarse and `t_start`, `t_end` are closest approach plus or minus 120 s. Slow: see Performance |
| `tracks.grid_search(win, t_start, t_end, f_lo, f_hi, c, harmonics=1, f0_step=1.0, t0_step=1.0, n_curve=120, objective="contrast")` | `(score, (f0, v, d, t0_emit))` | the coarse stage of `fit_event`; `win` is a cropped, `tracks.local_whiten`-ed spectrogram. Used by our quick preview |
| `tracks.fit_event(sp, t_start, t_end, f_lo, f_hi, c=None, harmonics=1, init=None, objective="contrast")` | `EventFit` | pass `objective="brightness"` for an analyst-drawn window, as the CLI `fit` does. **Raises `ValueError` when `f_hi <= 1.353 * f_lo`** (behaviour 11). 5 to 19 s; a 2 s preview is possible (behaviour 12) |
| `doppler.speed_of_sound(temp_c=15.0)` | m/s | `331.3 * sqrt(1 + T/273.15)` |
| `doppler.ideal_curve(t_obs, f0, v, d_cpa, t_cpa, c=None)` | Hz per time | for drawing a fitted curve over the spectrogram; `t_cpa` here is the **emission** time, so pass `EventFit.t_cpa_emit` |
| `fetch_day(date, bbox, pod="planes-readsb-prod-0", progress=None)` | `list[Trace]` | streams the day; `progress(n_files, n_bytes)` |
| `load_traces(path)`, `save_traces(traces, path)` | | `.npz`, no pickle |
| `AircraftTypes().is_prop(designator, unknown_ok=True)` | bool | Piston, Turboprop, Electric count as prop; **unknown types are kept** |
| `DayIndex.build(traces, lat0=None, lon0=None, bucket_s=10.0)` | `DayIndex` | 1 Hz ENU segments in one frame; `.save`, `DayIndex.load` |
| `Terrain(zoom=12).elevation(lat, lon)` | metres | downloads and caches tiles; CLI `search` uses zoom 9 |
| `run_search(sp, ev1, ev2, idx, harmonics=(1,1), tol_s=None, v_tol=0.35, d_tol=(0.4,2.5), silence_d_m=6000.0, max_range_m=12000.0, spacing_m=200.0, coarse_m=1000.0, elevation=None, c=None, score_mode="brightness", workers=None, cand_cache=None, bbox=None, points=None, t_heard_unix=None, log=...)` | `DataFrame` | best first; see columns below |
| `rescore_with_extra(sp, ev1, extra, idx, res, extra_harmonics=None, top_pairs=200, c=None, workers=None)` | `DataFrame` | adds `score12`, `s3..`, `x_icao1..`; re-ranks |
| `pipeline.best_per_pair(res)` | `DataFrame` | one row per flight pair |
| `pipeline.refine(sp, ev1, ev2, idx, res_row, spacing_m=50.0, half_m=400.0, harmonics=(1,1), elevation=None, c=None, extra=None, extra_harmonics=None)` | `DataFrame` | fine grid; `.attrs["extra_icao"]` |
| `verdict(res)` | `Verdict` | fields `verdict`, `p`, `gap`, `tail_width`, `threshold`, `k`, `n_pairs`, `n_null`, `winner` |

`EventFit` fields: `t_cpa` (heard closest-approach time in the recording, s), `t_cpa_emit`, `f0` (Hz), `v` (m/s), `d` (m), `t_start`, `t_end`, `score`, `f_pre`, `f_post`, `burst`. `to_dict()` gives the JSON the CLI reads.

`Trace` fields: `icao`, `reg`, `typ` (ICAO designator), `desc`, arrays `t` (unix s), `lat`, `lon`, `alt` (metres; geometric when the row has it, else barometric), `gs` (m/s), `on_ground`. `segments(max_gap_s=90)` gives airborne slices; `enu(slice, lat0, lon0, dt=1.0)` gives 1 Hz positions.

Search result columns (*ran*): `gidx, lat, lon, elev, seg1, seg2, icao1, icao2, t_heard1, d1, v1, d2, v2, score, s1, s2, shift, lat0, lon0`.

- `t_heard1` is the unix time the event-1 closest approach is heard at that point.
- The recording's clock falls out of the search. Clip start in unix time is `t_heard1 - ev1.t_cpa - shift`, good to a second or two (*ran*: 0.1 to 0.5 s error on the synthetic case; 55 s when the temperature was 25 C wrong).
- `score = s1 + s2`, mean whitened dB under each modelled curve over the fit window.

## Minimal working sequence (*ran*, see the smoke test)

```python
c = float(doppler.speed_of_sound(air_temp_c))            # never leave this at the default in the UAE
sp = pipeline.make_spectrogram("clip.mp4", "spec.npz")
proposals = detect_events(sp, 60, 300, c=c, top=12, workers=1, refine=False,
                          f0_step=3.0, t0_step=3.0, n_curve=60, min_sep_s=30.0)     # fast settings; hints only
ev1 = fit_event(sp, t0, t1, box_lo / 1.15, box_hi / 0.85, c=c, harmonics=1,
                objective="brightness")                                         # analyst's box, widened (behaviour 11)
ev2 = fit_event(sp, ...)                                  # later event second
idx = DayIndex.build(load_traces("data/flights/uae/2026-11-14-traces.npz"))
res = run_search(sp, ev1, ev2, idx, c=c, elevation=Terrain(zoom=12).elevation, workers=1)
res = rescore_with_extra(sp, ev1, [ev3], idx, res, c=c, workers=1)        # when a third flyover exists
v = verdict(res)
fine = pipeline.refine(sp, ev1, ev2, idx, pipeline.best_per_pair(res).iloc[0], extra=[ev3], c=c)
```

## Defaults worth knowing

| Thing | Default | Meaning |
|---|---|---|
| Heard-gap tolerance `tol_s` | 6 s (30 s for one event) | how far the measured gap between events may be from the geometry |
| Speed gate `v_tol` | 0.35 | plus or minus 35% of each fitted speed |
| Distance gate `d_tol` | 0.4 to 2.5 | multiples of each fitted closest-approach distance |
| `max_range_m` | 12,000 | no flight farther than this is considered audible |
| Lattice | 1,000 m coarse, 200 m fine | `refine` then uses 50 m |
| Silence filter | 6,000 m, 40 s margin | no other prop flight may pass that close between the two events |
| Score sweep | time shift plus or minus 8 s, f0 scale 0.95 to 1.05 | absorbs measurement error on event 1 |
| `detect` scan | 240 s windows, 120 s step, speeds 40 to 170 m/s, distances 400 to 9,000 m | slower aircraft and helicopters fall partly outside |
| Verdict thresholds | located `p < 0.1`, ambiguous `p < 0.5` | needs at least 20 wrong pairs, else `insufficient` |

## Behaviour that shapes our design

1. **`detect` finds flyovers but its fits are not good enough to search with.** On the reference clip its event 2 had f0 11% high and the gap 10 s short, so the true pair was rejected. The fits that work come from `fit` on a hand-chosen window. So the analyst must be able to draw or adjust the time and frequency window of each flyover, and we search with `fit_event(..., objective="brightness")` on that window.
2. **Bursts.** A train or truck passing the microphone sweeps like a low flyover. `EventFit.burst` is the share of the surrounding 3 minutes that is broadband-loud; hide or flag proposals above about 0.15. **Only `detect_events` sets it; `fit_event` leaves it at 0.0.** For an analyst's box, set it ourselves: `ev.burst = tracks.burst_fraction(mask, sp.t, ev.t_cpa)` with `mask = tracks.burst_mask(sp)` computed once on the whole recording (the mask is relative to the recording's own median, so it cannot be computed on a slice).
3. **Two events are never enough for "located".** In every saved result the two-event verdict is `ambiguous`; extra flyovers made both validated recordings `located`. See the evidence file.
4. **Extras must be real aircraft on the same clock.** Non-aircraft extras pushed the true pair from rank 16 to 116 on the railcam. A stream that dropped 107 s put later events on a different clock. Only analyst-confirmed events may be used as extras, and a recording with cuts must be split.
5. **The silence filter can veto the truth** when an undetected pass sits between the two events. Use it only when the two events are close together; turn it off (`silence_d_m=None`) for long, busy recordings.
6. **`bbox` restricts flight 1, not the ground points.** For an emirate, search the whole pack and filter result rows by polygon afterwards.
7. **There is no time-window argument.** Restrict by time by building the index from traces cut to the window, or by filtering rows on the implied clip start.
8. **`verdict` on a single-event search always returns `insufficient`** (it excludes pairs sharing `icao2`, and single-event rows all have an empty `icao2`). Single-event results need their own null if we ever ship them.
9. **Speed of sound defaults to 15 C.** See the hot-day experiment in the evidence file.
10. **Track glitches hurt.** Radial velocity comes from differentiated positions; a gap or jump in a track puts a kink in the modelled curve. The author lists smoothing as future work.
11. **A narrow frequency band crashes the fit** (*ran*). `fit_event` searches the fundamental on `[1.15 * f_lo, 0.85 * f_hi)` in 1 Hz steps. If `f_hi <= 1.353 * f_lo` that grid is empty and numpy raises `ValueError: attempt to get argmax of an empty sequence`. A slow aircraft's whole curve is narrower than that (45 m/s spans a ratio of 1.30), so an analyst's box will hit it. Rule: treat the analyst's box as the range the fundamental may lie in and call `fit_event(sp, t0, t1, box_lo / 1.15, box_hi / 0.85, ...)`. `fit_box()` in `scripts/smoke_dopplertrack.py` is the reference; `--editor` tests it.
12. **Box the bend, not the tails** (*ran*). Whitening dims a steady tone, so the long flat approach and departure add little but noise. Boxes about 100 s long centred on the bend, tall enough to enclose the curve over that time, gave fits within 2 Hz, 10 m/s and 1.5 s of the synthetic truth, and the search from those fits found the observer (111 m on the 200 m lattice, 1 m after refine). The author's own reference windows are 90 and 110 s. Fit cost grows with box length times box height: 5 to 11 s for those boxes with the widened band, 18 to 19 s for boxes of 160 to 170 s by 80 Hz.
    - **Quick preview.** A coarse `tracks.grid_search(..., f0_step=3, t0_step=3, n_curve=60)` on the same cropped, locally whitened window, passed to `fit_event(init=...)`, takes 1.7 to 2.4 s and returned the same fit as the full call in eight of nine comparisons; in the ninth (a 170 s box) it settled on a weaker nearby optimum (score 8.2 against 8.5). `fit_preview()` in the smoke script is the reference. Draw with the preview; search with the full fit.
    - Seeding `init=` from a rough guess that was 3 Hz and 8 s off also landed on that weaker optimum, so never seed a searched fit from a `detect` proposal.
13. **Harmonics beyond the spectrogram count as zero.** `sample` returns 0 outside the 40 to 450 Hz grid, so a harmonic count that pushes `harmonics * f_hi` past 450 Hz drags the score down instead of failing. Cap the harmonics control accordingly.
14. **`detect` proposes pieces of one aircraft.** A propeller aircraft approaching for minutes makes a long steady tone at its upper asymptote. *Ran:* the top two proposals for a 30 minute synthetic recording sat on one flight's approach tone, 52 and 134 s before its real closest approach, at 174 and 183 Hz for a 130 Hz aircraft; the proposal nearest the real bend was 23 s late and 16 Hz low. With the default `min_sep_s=60`, in one slice the real one was suppressed by a stronger neighbour 53 s away. Proposals mark regions worth looking at; the analyst finds the bend.
15. **A fit needs only its own columns.** `fit_event` crops to the window plus 30 s and whitens locally, so a fit on `sp.crop(t0 - 60, t1 + 60)` equals a fit on the whole spectrogram (*ran*: identical). The app can memory-map the spectrogram and hand a fit just its slice.

16. **A fit can change with a third of a hertz in the box** (*ran*, M3, 2026-11-22). `fit_event` lays its fundamental grid in 1 Hz steps from the bottom of the band and, with `objective="brightness"`, scores it unfiltered. On the synthetic turning flyover (true f0 130 Hz, 95 m/s, 3.2 km), a box drawn by hand in the UI, `1176.7 to 1278.2 s, 105.1 to 173.9 Hz`, fitted to 139 Hz, 140 m/s, 5.3 km (score 8.2). The same box moved by 0.33 Hz gave score 9.1, and by 0.67 Hz gave the true curve (130.0 Hz, 99 m/s, 3.3 km, score 13.5). The planning boxes had integer edges and the synthetic tones integer fundamentals, so they sat on the grid by luck. With the bad fit the search still found the place (112 m) but the verdict was `ambiguous` (p 0.30); with the good one it was `located` (p 0.043, 1 m). Rule: the search fits every box at three grid phases (0, 1/3, 2/3 Hz) and keeps the brightest (`core/events.fit_many`), in parallel on Linux. The editor's quick preview does the same: the api asks the fit pool for all three phases side by side and draws the brightest (`FIT_WORKERS` is 3 for that), so the curve the analyst sees is the one the search will find. Two cheaper ideas were tried and dropped: scanning the seed curve for the best sub-hertz offset before the fine fit did not help and made one case worse. Synthetic tones are narrower than real ones, so this is probably milder on real audio; not checked.

## Performance (author's numbers, 16 threads, continental US)

| Stage | Time |
|---|---|
| `fetch`, streamed | 2.5 min at 20 MB/s |
| Index, 35,427 flights, 6.2 GB | 30 s |
| Pair join | 10 s for 66,637 pairs |
| Lens lattices | 71 s for 2.5 million points |
| Locked scoring | 16 min |
| One extra flyover on the top 200 pairs | 1 s |

### Measured during planning (*ran*)

One worker on a two-core 2.1 GHz cloud machine, a 30 minute synthetic recording with three flyovers, the app's spectrogram settings. Reproduce with `scripts/smoke_dopplertrack.py --editor`.

| Step | Time | Note |
|---|---|---|
| Spectrogram | 0.9 s | 840 by 7,192, 24 MB |
| `fit_event`, 100 s boxes around the bend, widened band | 5.3 to 11 s | within 2 Hz and 1.5 s of truth |
| quick preview on the same boxes | 1.7 to 1.8 s | same answer as the full fit |
| `fit_event`, 170 s by 80 Hz box | 8.5 to 9.8 s as given, 18 to 19 s widened | |
| `detect_events`, defaults, band 60 to 300 Hz | 306 s (10 s per minute of audio) | top five held two of the three real flyovers |
| same, `refine=False` | 220 s (7.3 s per minute) | real flyovers at ranks 5, 1, 2 |
| same, `refine=False`, `workers=2` | 135 s | |
| same, fast settings (`refine=False, f0_step=3, t0_step=3, n_curve=60, min_sep_s=30`) | 60 s (2.0 s per minute) | ranks 6, 4, 3 of 10 |
| fast settings on one 10 minute slice | 17 s; 5 s with the band cut to 60 to 160 Hz | time scales with band width |
| Search, 500 candidate rows, plus refine | about 25 s for the whole baseline run | |
| Search, 20,557 rows (25 decoy pairs) | 62 s (3.0 ms per row) | |

### Measured on the user's machine in M0 (2026-11-21, *ran*)

Installed with `uv add` from git at the pinned commit: Python 3.12.16, numpy 2.5.5, scipy 1.18.1, pandas 3.1.1, pillow 13.0.0 (all at or above the declared minimums). Linux, Intel Core Ultra 7 258V (8 cores), 30 GB RAM, one worker, **on battery in the `power-saver` profile**. Same command, `--hot --decoys 25 --editor`: `SMOKE TEST PASSED` in 6 min 59 s against about 5 min during planning. Every accuracy figure matched the planning run exactly (111 m then 1 m; 7,749 m uncorrected; 98 m then 48 m corrected; decoys "no match" p 0.673 then "located" p 0.043; detection ranks 6, 4, 3).

| Step | Planning machine | This machine (power-saver) | Ratio |
|---|---|---|---|
| Spectrogram, 30 min | 0.9 s | 0.9 s | 1.0 |
| `fit_box`, narrow 110 to 140 Hz box, widened | 3 s | 4.9 s | 1.6 |
| `fit_event`, 100 s bend boxes, widened band | 5.3 to 11 s | 9.1 to 18.0 s | 1.7 |
| quick preview on the same boxes | 1.7 to 1.8 s | 3.1 to 3.4 s | 1.9 |
| `fit_event`, 170 s by 80 Hz box as given | 8.5 to 9.8 s | 15.6 s | 1.7 |
| `detect_events`, fast settings | 60 s (2.0 s per minute) | 100 s (3.3 s per minute) | 1.7 |
| Baseline run (spectrogram, three fits, search, refine) | about 25 s | 38.3 s | 1.5 |
| Search, 20,557 rows | 62 s (3.0 ms per row) | 74.6 s (3.6 ms per row) | 1.2 |

So in power-saver this machine is about 1.2 to 1.9 times slower per core than the planning machine. The editor preview misses its 2 s target here (3.1 to 3.4 s) but stays under the 5 s limits in the M1 and M2 tests. Re-measure plugged in with the `performance` or `balanced` profile before M2; the machine has 8 cores and is on Linux, so detection and search can use more than one worker.

### Measured on the presenting Mac (2026-11-24, *ran*)

Apple M4 (10 cores), 16 GB, macOS, Python 3.12 from uv 0.13.9, ffmpeg 9.1, one worker (rule 7). Same command, `--hot --decoys 25 --editor`: `SMOKE TEST PASSED` in **5 min 22 s**. Every accuracy figure matched the runs above exactly (111 m then 1 m; 7,749 m uncorrected; 98 m then 48 m; decoys "no match" p 0.673 then "located" p 0.043). The plain run took 64 s end to end, 32 s of it in the baseline.

| Step | Planning machine | Linux laptop (power-saver) | This Mac |
|---|---|---|---|
| `fit_box`, narrow 110 to 140 Hz box, widened | 3 s | 4.9 s | 4.2 s |
| `fit_event`, 100 s bend boxes, widened band | 5.3 to 11 s | 9.1 to 18.0 s | 9.4 to 15.9 s |
| quick preview on the same boxes | 1.7 to 1.8 s | 3.1 to 3.4 s | 2.6 to 3.4 s |
| `fit_event`, 170 s by 80 Hz box as given | 8.5 to 9.8 s | 15.6 s | 13.1 s |
| `detect_events`, fast settings | 60 s | 100 s | 72 s (2.4 s per minute) |
| Baseline run | about 25 s | 38.3 s | 32.1 s |

So one worker here is a little faster than the Linux laptop in power-saver and slower than the planning machine. The editor preview still misses its 2 s target. macOS cannot use more than one worker for the engine.

Source check in M0: every signature in the API table above matches the installed source. One naming nit: the fifth parameter of `doppler.ideal_curve` is named `t_cpa` (documented in the source as the *emission* time of closest approach), not `t_cpa_emit`; pass `EventFit.t_cpa_emit` to it positionally or as `t_cpa=`.

So detection is the slow step, not the search: with library defaults an hour of audio takes about ten minutes on one worker. Our triage uses the fast settings in slices and streams proposals as they come (`05-architecture.md`). A UAE day has far fewer propeller flights than the continental US, so one worker should be enough for the search; measure it in milestone 1.

## What we add on top

Service and UI, analyst-confirmed events, temperature from weather data, region packs and polygon filtering, time-window handling across UTC days, a confidence band built on `verdict`, placebo-day controls, an integrity filter on traces, reports and audit.
