# Product

## One sentence

An analyst workbench that turns a recording, its date and a rough area into a ranked set of
location leads with a verdict, and says quickly and plainly when a recording cannot be located.

## Who it is for

Cybercrime and digital-forensics analysts, trust-and-safety teams, and journalists verifying
footage. They are comfortable with tools, work case by case, and need to defend what they
report. It is not a consumer app and has no anonymous mode.

## What it does not do

- It does not locate any video. See "What a recording needs" below.
- It does not identify people. It estimates where a microphone was.
- It does not replace corroboration. Every output is a lead.

## What a recording needs

| Need | Why |
|---|---|
| A known recording date | flights are matched per day; the date selects the archive |
| Unedited, continuous audio | cuts put flyovers on different clocks; a 107 s dropout broke one validated case |
| Outdoor or semi-open recording | the 60 to 400 Hz tones must reach the microphone |
| Two or more propeller flyovers, ideally three or more | two give candidates; a third on the same clock can confirm one |
| Length | a flyover lasts one to four minutes; several minutes is the practical minimum, an hour is good |
| The aircraft in the public archive | no track, no match |
| Air temperature to about 5 C | it sets the speed of sound |

## Inputs and what each one does in the engine

| Input | Required | Effect |
|---|---|---|
| File | yes | decoded to mono 4 kHz, hashed, spectrogram of 40 to 450 Hz |
| Recording date (local) | yes | selects the UTC day archives (two for a local day) |
| Time-of-day ranges (local) | no | a constraint on the implied clip start; with "not sure" the whole day is allowed |
| Area: emirates, sub-areas or a drawn box | no | a constraint on where the answer may lie; the search itself runs over the whole pack so the verdict has enough wrong pairs to judge against |
| Flyovers | yes, 2+ | proposed by `detect`, confirmed or redrawn by the analyst as a box around each curve's bend; the confirmed boxes are what get fitted and searched |
| Air temperature | auto, editable | passed as the speed of sound to every fit and search |
| Case reference | yes | audit trail |

## User requirements

1. Upload a video or audio file; the original is kept untouched and hashed.
2. Give the recording date, optional time-of-day ranges and an optional area on a UAE map.
3. See the spectrogram with proposed flyovers; confirm, reject, or draw and adjust the time and frequency window of each.
4. Know before any heavy compute whether the recording is searchable (two or more confirmed flyovers) and how strong a result it can support.
5. Watch the search progress with named stages.
6. See the outcome as one of four states (below), with the verdict, p value, uncertainty radius, matched flights and the modelled curves over the recording.
7. See alternates, including any stronger match that lies outside the stated area or time.
8. Export a reproducible report.
9. Sign in; every upload, search and export is logged against a case reference.
10. The flow is fast and smooth: no dead waits, every tap answers within 100 ms. Where the engine needs time, the wait is filled with real progress (targets below).

## Speed targets

Set from measurements on one core (`02-dopplertrack.md`, Performance). Treat them as budgets to test against, and re-measure on the user's machine in M1.

| Moment | Target | Basis |
|---|---|---|
| Spectrogram visible after upload ends | under 10 s for a 30 minute file | spectrogram 0.9 s measured; decode not measured |
| First flyover proposals | within 30 s of the spectrogram | 17 s per 10 minute slice measured |
| All proposals | about 2 s per minute of audio | 60 s for 30 minutes measured; library defaults take five times longer |
| Curve drawn after the analyst releases a box | about 2 s | quick preview 1.7 to 2.4 s measured |
| Search, synthetic case | under a minute | 25 s measured for the whole baseline run: spectrogram, three fits, search, refine |
| Search, real day | unknown | 3 ms per candidate row measured; row counts for a UAE day are not known until the coverage probe |
| "Not locatable: no flyovers" | as soon as detection ends and the analyst has confirmed nothing | |

## Result states

| State | When | What the analyst sees |
|---|---|---|
| **Located** | verdict `located`, three or more flyovers on one clock, inside the stated constraints | one estimate with uncertainty circle, band High or Medium |
| **Candidates** | two flyovers, or a verdict of `ambiguous`, `no match` or `insufficient` | a ranked list of up to five places, each with its flights and score; band Low; labelled "unconfirmed" or "weak" |
| **Outside your constraints** | the best pair overall falls outside the stated area or time | the constrained best as a candidate, plus the outside match flagged |
| **Not locatable** | fewer than two confirmed flyovers, no propeller flights in the archive, or no place fits both flyovers | what was checked, why, and what would help |

Band and score rules are in `06-confidence.md`.

## Flow

One page with a persistent map and one panel that changes. Screens marked * are in the mockups (`design/mockups/`).

1. **Sign in.** Email and password. (Not mocked.)
2. **Upload*.** Drop a file. Upload and triage start immediately: decoding and the spectrogram take seconds, then flyover proposals arrive in the background at about 2 s per minute of audio (one core).
3. **When*.** Date, time-of-day ranges with presets, live count of flights in the window.
4. **Where*.** Emirate multi-select on the dot map or the list; sub-areas for Abu Dhabi; optional custom box; "not sure".
5. **Flyovers*.** The event editor: spectrogram of the recording with proposals; the analyst confirms, rejects, or drags a box around the bend of a flyover and sees the fitted curve drawn over it about two seconds later. It works before detection has finished. This step is required: see `02-dopplertrack.md`, behaviour 1.
6. **Review*.** Summary, air temperature used (editable), case reference, submit.
7. **Searching*.** Stages: flyovers refitted, flights loaded, join, lattice, scoring, extras, refine, controls.
8. **Result*** as Located, **Candidates*** or **Not locatable***.
9. **Cases.** A list of the analyst's cases to reopen. (Not mocked.)

Presets for time of day (local): morning 06:00 to 12:00, afternoon 12:00 to 17:00, evening 17:00 to 21:00, night 21:00 to 06:00 (two ranges on the chosen date), not sure (whole day).

## Safeguards

The same method can find where a private person lives. The product is built so that casual misuse is hard and all use is attributable.

- Accounts only; no public or anonymous endpoint; rate limits per account.
- A case reference is required before a search can start.
- Audit log: who uploaded what (by hash), searched what, exported what, and when.
- Uploads encrypted at rest where the host allows, and deleted after a retention period (config, default 30 days).
- The README states intended use and limits. A "check my own recording" mode, which only reports whether a clip contains locatable flyovers, is a later addition.

## Out of scope for the MVP

Unknown recording date; single-flyover search; jets and helicopters as sound sources; wind correction; automatic splitting of edited recordings; batch upload; mobile layout polish; a tile basemap (the result links out to a map site instead).
