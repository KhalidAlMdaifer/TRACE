# Method and evidence

What the technique is, what has been shown to work, and what that allows us to promise.

Sources are graded: **repo** = read in dopplertrack's own docs and result tables at the
pinned commit; **ran** = executed during planning; **press** = reported by third parties,
not checked by us.

## The physics in five lines

1. A propeller aircraft emits a steady tone: the blade-pass frequency and its harmonics, roughly 60 to 400 Hz. It is usually inaudible but shows in a high-resolution spectrogram.
2. A stationary listener hears `f_obs(t) = f0 * c / (c + v_r(t_e))`, where `v_r` is the range rate at the **emission** time `t_e` and `t = t_e + r(t_e)/c`. Using the range rate at observation time gives a visibly wrong curve.
3. For a straight, constant-speed pass the curve is fixed by four numbers: `f0`, speed `v`, closest-approach slant distance `d`, closest-approach time. `v` sets the size of the frequency drop; `d` sets how fast it happens.
4. Real aircraft turn, climb and change speed. Those deviations are what make one ground point's predicted curve different from its neighbours'.
5. Low passes to the side pin a location. High, nearly overhead passes do not, because moving the listener a kilometre barely changes the slant distance.

## How the search works (dopplertrack 0.3)

1. **Join.** Two events heard dt apart at fitted distances d1 and d2 mean the two aircraft were within d1 + d2 of each other, dt apart in emission time. A KD-tree join over the day's flights leaves tens of thousands of flight pairs out of hundreds of millions.
2. **Lens.** For each pair, ground points are laid only where both could have been heard: a 1 km lattice, then 200 m where it passes. Each point gets its exact closest approach to both real trajectories. Points must hear an event-1-like pass, then exactly dt later an event-2-like pass, with no other propeller flight within 6 km in between.
3. **Score.** The curve each surviving point would hear is modelled from the real trajectory and laid over the spectrogram. Event 1 is swept over small time shifts and f0 scales; event 2 is placed with the same shift, locked to the geometry. Score is brightness under both curves.
4. **More events.** For the best pairs, each further flyover is matched to a flight at the pair's best point and scored on the same clock.
5. **Verdict.** At most one scored pair is right; the rest are the null distribution for this recording. The winner's lead over the best wrong pair is tested against the spread of wrong pairs: `located` (p < 0.1), `ambiguous` (p < 0.5), `no match`, or `insufficient` when there are fewer than about 20 wrong pairs.

The recording's start time is not an input. It falls out of the search.

## What has been validated (repo)

All three searched against every propeller flight over the continental US that day, no region given.

| | Oyster Bay, NY | Eagle cam, FL | Railcam, Atlanta |
|---|---|---|---|
| Recording | 1 hour, made for the demo | 12 hours, public stream | 11.9 hours, public stream, 49 kbps audio |
| Date | 2026-09-08 | 2024-12-28 | 2026-05-28 |
| Source | youtu.be/4CxVxuMVkMc | youtu.be/zs2o5Rhlp5w | YouTube `OH5baHg7pIw` |
| True position | 40.876466, -73.524951 | 26.702359, -81.847766 | known to about 100 m |
| Flights that day | 35,427 | 13,046 | |
| Pairs scored | 9,669 | 13,298 | 36,260 (best case) |
| True pair rank, two events | 1 | 15 | 6 |
| True pair rank with extra flyovers | 1 | 1 | worse (wrong clock, non-aircraft extras) |
| Best point from truth | 32 m | 627 m | 361 m, but it did not win |
| Verdict, two events | ambiguous (p 0.23) | ambiguous (p 0.48), wrong pair on top | 2 of 20 no-answer searches said "located" |
| Verdict with extras | located (p 0.001 or lower) | located (p 0.064) | |
| Wall time, 16 threads | 18 min | 6 min | about 15 min per search |

Lessons the author draws, which we adopt:

- **Two events never prove a location, even when they find it.** Extras turn a right answer into a provable one.
- **A margin is not a confidence.** The same audio searched in a box 150 km from the answer still returned a winner; only the verdict (p 0.88, no match) flagged it.
- **`located` at p < 0.1 is a weak claim.** Two of twenty searches with no right answer among the pairs were called located.
- **Extras help only when they are real aircraft on the same clock.** A 107 s dropout in an archived stream, and detections that were locomotives, buried the true pair.
- **The fit of an ideal curve is the weak link.** On a faint, non-straight pass it was wrong by a factor of ten in distance. Gates seeded from it must be loose.
- **One faint flyover with a known time** located the Oyster Bay recording to about 2 km in a 100 x 150 km box.
- Detection on the railcam: of 42 propeller passes within 15 km, 6 of the top 40 detections were real; three of the top four were not aircraft.

Reference fits for the Oyster Bay clip are in the dopplertrack repo under `docs/results/` (`oyster_bay_ev1.json`, `oyster_bay_ev2.json`, `oyster_bay_ev_faint.json`), made with:

```
dopplertrack fit rec.npz --window 2090 2200 --band 95 200 --harmonics 2 --out ev1.json
dopplertrack fit rec.npz --window 3020 3130 --band 95 195 --out ev2.json
dopplertrack fit rec.npz --window 1375 1465 --band 70 105 --harmonics 2 --out ev_faint.json
```

The true pair is `a1dfeb` (N22NY, Pilatus PC-12) then `ace391` (N93CQ, King Air 350); the clip starts at 20:17:30 UTC.

### Oyster Bay reproduced on the user's machine (*ran*, 2026-11-21)

The user approved the download. Audio: YouTube format 140 (AAC 129 kbit/s, 3600.2 s, 58 MB,
sha256 `4fee89ad...537cd`), kept at `data/reference/oyster_bay/` (not in git) with `rec.npz`
and `traces_ny.npz`, the layout dopplertrack's opt-in test expects. Flight day: 2026-09-08,
bbox `40.4 41.3 -74.4 -72.6`, jets dropped: 1,016 aircraft, 4,071 segments.

```
D=data/reference/oyster_bay
uv run dopplertrack spectrogram $D/oyster_bay_4CxVxuMVkMc.m4a $D/rec.npz
uv run dopplertrack fit $D/rec.npz --window 2090 2200 --band 95 200 --harmonics 2 --out $D/ev1.json
uv run dopplertrack fit $D/rec.npz --window 3020 3130 --band 95 195 --out $D/ev2.json
uv run dopplertrack fit $D/rec.npz --window 1375 1465 --band 70 105 --harmonics 2 --out $D/ev_faint.json
uv run dopplertrack fetch 2026-09-08 data/flights/ny/2026-09-08.npz --bbox 40.4 41.3 -74.4 -72.6 --traces $D/traces_ny.npz
uv run dopplertrack search $D/rec.npz --events $D/ev1.json $D/ev2.json --day data/flights/ny/2026-09-08.npz \
    --harmonics 2 1 --extra $D/ev_faint.json --extra-harmonics 2 --out $D/out/results.csv --out-extra $D/out/results_extra.csv
```

| | Result |
|---|---|
| Fits against the author's reference JSON | ev1: t_cpa +0.01 s, f0 +0.01 Hz, d -3 m. ev2: t_cpa +0.07 s, f0 -0.04 Hz, d +36 m. Faint: t_cpa +0.09 s, d -6 m |
| Join and lens | 5,548 flight pairs pass the join; 192,696 candidate rows on 999 pairs |
| Two events | true pair `a1dfeb`/`ace391` first of 913 scored pairs, score 28.17; **ambiguous (p 0.33)** |
| Plus the faint flyover | true pair first, score 35.37, 8.03 above the next; **located (p 0.002)** |
| Best 200 m point | 40.876339, -73.524613: **32 m** from the truth |
| 50 m refine with the extra | 40.875890, -73.524613, score 36.66: 70 m from the truth (higher score, slightly farther) |
| Implied clip start | 2026-09-08 20:17:30 UTC, as the author states |
| Time | spectrogram 16 s; fits 3 to 34 s; search 4 min 40 s wall on 8 workers (29 CPU-minutes, 222 s of it scoring); refine 12 s |

All at the library's default 15 C, as the author ran it; the real temperature that afternoon
was not looked up. The fits differ slightly from the reference JSON (ev2 by 0.07 s and
36 m), more than the upstream test's tolerances of 0.05 s and 5 m; the likely cause, not
checked, is that the author decoded a different audio format. Our own Oyster Bay test in M1
should assert the outcome (pair, distance, verdict), not those tolerances.

This is the regional version of the author's continental search, so the null is smaller
(913 pairs against 9,669) and the p values are not comparable one to one.

## Other replications (press)

- The original video (colsto, 2 Nov 2026): two curves 920 s apart, about 70,000 candidate points cut to 15,000 by the timing and silence filters, curves measured by hand, paid or scraped flight data, no code. He says a one-minute clip needs the exact recording time.
- doppler-locate: reproduced the demo; reported that wind and temperature from a weather model cut one aircraft's residual from 0.55 Hz to 0.21 Hz, and that steady hums at 107, 160 and 241 Hz had to be removed first.
- colsto-leak-and-mask: fully automatic detection misread one tone by about 5% and the answer moved 137 km; blind webcam tests located nothing; one apparent hit survived a 30-minute audio shift, so it reflected where flights usually fly.
- geodoppler: 2 good answers on 22 public recordings.

## Our own checks (ran)

`scripts/smoke_dopplertrack.py` invents three flights over a point, synthesises the audio and runs the real library on it.

| Run | Best 200 m point | After 50 m refine with the third flyover |
|---|---|---|
| Audio and search both at 15 C | 111 m from truth | 1 m |
| Audio at 40 C, search at 40 C | 98 m | 48 m |
| Audio at 40 C, search at the 15 C default | **7,749 m** | 7,813 m |

Sweep of the search temperature against 40 C audio (same case):

| Temperature error | 0 C | 2 C | 5 C | 10 C | 15 C | 25 C |
|---|---|---|---|---|---|---|
| Best point from truth | 98 m | 181 m | 102 m | 181 m | 426 m | 7,749 m |
| Refined, with third flyover | 48 m | 72 m | 52 m | 214 m | 157 m | 7,813 m |
| Refined score | 35.5 | 35.1 | 32.9 | 27.3 | 25.8 | 20.3 |

One synthetic geometry, so treat the numbers as an indication: within about 5 C the result holds, at 10 to 15 C it degrades, at 25 C it fails outright. A UAE summer afternoon is 25 to 30 C above the library default.

The verdict experiment (`--decoys 25`) adds 25 wrong flight pairs: the true geometry rotated, moved 30 to 150 km away, and perturbed in speed, height and timing.

| | Winner | True pair rank | Verdict |
|---|---|---|---|
| Two flyovers | a decoy, 103 km from truth | 2 of 52 | no match (p 0.67) |
| Plus the third flyover | the true pair, 98 m from truth | 1 of 52 | located (p 0.043) |

That is the repo's finding reproduced in miniature: two flyovers can put the truth near the top without proving it, and a real third flyover settles it. The search scored 20,557 candidate rows in about a minute on one worker (3 ms per row).

The flyover-editor experiment (`--editor`) runs on the app's own spectrogram settings, 30 minutes of audio, one core:

| Check | Result |
|---|---|
| A box 110 to 140 Hz tall passed straight to `fit_event` | raises `ValueError` (the fundamental grid is empty) |
| The same box with the widening rule | fit within 0.1 Hz, 0.1 m/s and 4 m of the truth, 3 s |
| 100 s boxes around each curve's bend, full fit | within 2 Hz, 10 m/s and 1.5 s of the truth; 5 to 11 s each |
| Quick preview on those boxes | same answers, 1.7 to 1.8 s each |
| Search from those fits | true pair first, 111 m; 1 m after refine with the third flyover |
| Automatic detection, fast settings | 60 s; the three real flyovers at ranks 6, 4 and 3 of 10 proposals |
| Automatic detection, library defaults | 306 s; two of the three real flyovers in the top five |

### Through our own pipeline (*ran*, M1, 2026-11-21)

`python -m app.cli` on the synthetic case: 28 C audio, app spectrogram settings, the three
bend boxes, 25 decoy pairs for each pair of real flights. The search pairs the two
best-fitted flyovers, which here are flights 3 and 2 (flight 3 is the low pass, 1.3 km away).

| Run | Pair searched | Verdict | State and band | Best 200 m point | After 50 m refine |
|---|---|---|---|---|---|
| Three flyovers, 28 C | 3 and 2, extra 1 | located, p 0.0004, 89 wrong pairs | Located, High | 1 m | 50 m, radius 112 m |
| Two flyovers (a two-flight recording), 28 C | 1 and 2 | no match, p 0.93, 37 wrong pairs | Candidates, weak; truth ranked first | 111 m | 1 m |
| Three flyovers, searched at 3 C (25 C wrong) | 1 and 3, extra 2 | located, p 0.026 | Located, Medium | 462 m | 182 m, radius 390 m |

Two things to take from this:

- **Which two flyovers form the pair matters.** With the low pass in the pair, three
  flyovers gave p 0.0004 where planning's fixed pair of flights 1 and 2 gave p 0.043.
- **A wrong temperature does not always miss by kilometres.** With the low pass in the pair
  a 25 C error cost 182 m, not 7.7 km, and the result still read "located" (Medium, not
  High). The damage depends on the geometry: distant passes are the sensitive ones. So a
  temperature error can produce a confident-looking result a few hundred metres off, and
  the uncertainty radius (390 m here against 112 m) is the only visible sign. Rule 6 stands.

One synthetic geometry again; an indication, not a calibration.

The Oyster Bay recording through the same orchestration (`uv run pytest -m reference`,
5 min 12 s on 8 workers, 15 C as the author ran it): state Located, the true pair
`a1dfeb`/`ace391`, the refined estimate within the test's 150 m bound of the true position,
clip start in the minute of 20:17 UTC. The exact p and distance were not printed by that run.

### Through the browser (*ran*, M3, 2026-11-22)

The synthetic recording uploaded and worked through the UI, with three boxes drawn by hand
on the spectrogram (each within 3 s and 2 Hz of the planning boxes), area "Home square",
time 12:00 to 17:00.

| Search fit | Verdict | State | Refined estimate |
|---|---|---|---|
| One fit per box (M1 and M2 behaviour) | ambiguous, p 0.30, 86 wrong pairs | Candidates, unconfirmed | 112 m from truth |
| Three grid phases per box, best kept (M3) | located, p 0.043 | Located, Medium | 1 m from truth, radius 50 m |

The difference is one flyover's fit (`02-dopplertrack.md`, behaviour 16). The planning result
of p 0.0004 came from boxes that happened to sit on the fit's grid; p 0.043 from hand-drawn
boxes is the more honest figure for this case.

### Oyster Bay through the service, at the real temperature (*ran*, M5, 2026-11-22)

Uploaded through the API to the `ny` pack, time window 15:00 to 18:00 local, temperature
looked up automatically (Open-Meteo: 26.1 to 26.5 C at the surface, 23.4 C after the layer
offset), three boxes equal to the author's fit windows.

| | Result |
|---|---|
| State and band | Located, Medium (strength 48) |
| Verdict | located, p 0.037, against 187 wrong pairs |
| Flights | `a1dfeb` (PC-12) and `ace391` (King Air 350), extra `aa61d2` (PA-30) |
| Refined estimate | 96 m from the true position, radius 320 m (200 m lattice point: 172 m) |
| Clip start | 2026-09-08 20:17:30 UTC |
| Time | about 7 min 30 s with 6 workers, while a flight day was being fetched |

At the library's default 15 C the same search gave p 0.002 and 32 m. The real temperature is
8 C warmer, and the answer is the same place with a weaker verdict: the pattern in the table
below. The 15 C figures are the ones the author published; neither run says which is closer
to the truth of the air that day.

The same service searched the synthetic (invented) recording against two real UAE days
(428 propeller-class flights): "Candidates, weak", no match, p 0.75. That is the right answer
for audio that contains no real UAE aircraft, and the only UAE search possible until a UAE
recording with a known position exists.

### Temperature against score (*ran*, M5, 2026-11-22)

The synthetic recording made at 28 C, bend boxes, searched at three temperatures:

| | 20 C | 28 C (true) | 36 C |
|---|---|---|---|
| Three flyovers: winner's score | 31.98 | 31.16 | 32.37 |
| Three flyovers: verdict | located, p 0.028 | located, p 0.031 | located, p 0.0002 |
| Two flyovers: winner's score | 25.05 | 21.76 | 25.01 |
| Two flyovers: verdict | ambiguous, p 0.11 | no match, p 0.92 | ambiguous, p 0.43 |

The true flights won every run, so 8 C either way did not change the answer. But the true
temperature gave the **lowest** score in both rows, and p moved by two orders of magnitude.
So the score cannot be used to choose a temperature, and p from one temperature should not
be compared with p from another. The two-temperature rule therefore relies on agreement
between the runs, not on which is brighter.

The top two proposals in the fast run were not flyovers at all: they sat on one aircraft's steady approach tone, about one and two minutes before it actually passed. Detection is a pointer to where the analyst should look, and nothing more.

## What this lets us promise

- **Long recordings with three or more flyovers**, known date, unedited audio, temperature known to about 5 C, aircraft present in the archive: a location to tens or hundreds of metres with a defensible verdict.
- **Two flyovers:** a short ranked list of candidate places. Useful as leads, never presented as the answer.
- **One flyover:** nothing, unless its exact time is known (a livestream or a timestamped clip), and then an area, not a point.
- **No flyover**, edited audio, music over the top, indoor recordings with no low-frequency leak: not locatable. This will be the most common outcome for short social-media clips.

So the product's first job is triage, its main output is a ranked set of leads with a verdict, and it must say "not locatable" quickly and plainly.
