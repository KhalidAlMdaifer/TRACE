# Demo script (three minutes, then questions)

What to show, what to say, and what must be on screen. Every number below was measured on the
demo data on the presenting Mac (2026-11-24); if you change the data, re-check them. The pitch
slot is short and fixed: plan for one minute to state the problem and the solution, two minutes
of demo, then questions. A one-minute version for the submission video is the first six rows of
the table, tightened.

## Before you start

- `docker compose up -d`, then http://localhost:8080, signed in, language English. In Docker a
  search takes about 40 seconds on this Mac (41 s measured); natively on macOS it takes about
  four minutes, so do not demo from the native setup.
- `DEFAULT_PACK=test` and `SHOW_DEV_PACKS=1` in `.env`, and `python -m app.cli demo` run once.
- Three finished cases in the Cases list: one Located (three flyovers), one Candidates (two
  flyovers), one Not locatable. Open the Located one and check it shows no "latest search
  stopped" note.
- Laptop plugged in, lid open. A closed lid stalls a search.
- Say plainly at least once that the demo recording is **simulated**: invented flights, a known
  answer. The real-recording result is the Oyster Bay line at the end.
- The When step says "Part of that day is not loaded" on the demo. That is true and expected:
  the demo installs one UTC day and the local day touches two.

## The script

| Time | On screen | Say |
|---|---|---|
| 0:00 | Slide: the problem | "A recording turns up in an investigation. Where was it made? The metadata is gone and the picture can be staged. The sound is harder to fake." |
| 0:25 | Slide: the idea | "A propeller aircraft passing overhead leaves a falling tone. The shape of that fall depends on where the microphone was. With that day's public flight tracks, TRACE finds the place that fits." |
| 0:50 | The app: Cases, open the Located case, Flyovers step | "This is a simulated half-hour recording with a known answer. Each S-shaped curve is an aircraft. The dashed boxes are the machine's guesses and some are wrong, so the analyst confirms each one." |
| 1:15 | Review, then Submit (a live search, about 40 s) | "A case reference is required. Every upload, search and export is logged. This is an analyst's tool, not a public one." |
| 1:25 | Searching: stages ticking, dots appearing | "It pairs every propeller flight that day that could have made these tones this far apart, and scores each place on the ground against the audio." |
| 2:05 | The result | "Located. But look at the card, not the pin: p 0.03 against 146 wrong pairs, three flyovers on one clock, within about 71 metres. A result is a lead." |
| 2:25 | The report button | "And a printable report for the case file: the file's hash, the inputs, the matched aircraft." |
| 2:35 | The Candidates case | "With two flyovers it will not claim a location. Here the right place is not even in its top five, and it says: no match, unconfirmed. Two flyovers never prove it." |
| 2:45 | The Not locatable case | "Most clips have no flyover at all. It says so in seconds, and why." |
| 2:52 | Slide: what has been measured | "On a real one-hour recording from New York: 96 metres from where it was made. No UAE recording with a known position has been tested yet. That is the first step of a pilot." |

## If something goes wrong

- **The search is slow or stalls.** Do not wait. Open the finished Located case from Cases.
- **A box shows "No curve found".** Make it taller or longer; the bend must be inside it.
- **The result is Candidates with three flyovers.** One box is off its bend. Use the finished
  case. Do not claim it located.
- **The network is down.** A Located result still shows every number; only the street tiles
  under the map are missing.

## Questions to expect

- **How is this protecting people from cybercrime?** It answers one investigative question:
  where a recording was made. Say plainly that it does not detect fraudulent links or sites.
- **Could it locate anyone's home?** Yes, which is why every route needs a sign-in, a case
  reference is required, and everything is logged.
- **How often does it work?** Not measured for the UAE. It needs the date, uncut outdoor audio
  and two or more propeller flyovers; in the UAE those are mostly between Dubai South and
  Al Ain, in daytime. Most short clips end at "not locatable".
- **Is the 71 m the error?** No: it is the uncertainty radius the tool reports. On the simulated
  recording the true point lies inside it. The measured error on a real recording is 96 m.

## Things not to say

- Not "accuracy" or "probability" next to the strength number: it is a **match strength**.
- Not that it works on any video.
- Not that the UAE pack is proven: no UAE recording with a known position has been tested.
- Not that two flyovers "find the right place": in this demo they do not.
