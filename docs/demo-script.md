# Demo script (two minutes)

What to show, what to say, and what must be on screen. Every number below was measured on
the demo data; if you change the data, re-check them.

## Before you start

- The app running, signed in, with `DEFAULT_PACK=test` and `SHOW_DEV_PACKS=1` in `.env`.
- `python -m app.cli demo` run once, so `data/demo/synthetic.wav` and its flight day exist.
- **One case already finished** on the demo file with three flyovers, open in a second tab
  on its result. A search takes about a minute, which the live run fills with talk; the
  finished one is the fallback if anything stalls.
- Laptop plugged in and not in a power-saving mode: each flyover fit took 5 to 6 seconds
  on the build machine while it was throttled, and has not been timed unthrottled.
- Say plainly at least once that the demo recording is **simulated**: invented flights, a
  known answer. The real-recording result is the Oyster Bay line at the end.

## The script

| Time | On screen | Say |
|---|---|---|
| 0:00 | Upload screen, the dot map | "A video turns up in an investigation. Where was it filmed? If a propeller aircraft flew past, the recording already knows. TRACE reads it." |
| 0:10 | Choose "Synthetic test pack", drop `synthetic.wav` | "This is a simulated half-hour recording with a known answer. Analysis starts the moment it lands." |
| 0:20 | When: 14 Nov 2026, Afternoon. Where: Home square | "The analyst gives the date, and roughly when and where. The date picks the day's public flight tracks. The area ranks results; it never hides them." |
| 0:35 | Flyovers: point at the three S-curves | "Each falling tone is an aircraft passing. Its exact shape depends on where the microphone was. The dashed boxes are the machine's guesses, and some are wrong, so the analyst confirms each one." |
| 0:45 | Drag a box on each bend; the red curves appear | "A box around the bend, and the curve is fitted in a few seconds: frequency, speed, distance." |
| 1:05 | Review: case reference, Submit | "A case reference is required. Every upload, search and export is logged. This is an analyst's tool, not a public one." |
| 1:15 | Searching: stages ticking, dots appearing | "It pairs up every propeller flight that day that could have made these tones this far apart, and scores each place on the ground against the audio." |
| 1:30 | Switch to the finished result if the live one is still running | "Located. Within about fifty metres of the true point. But look at the card, not the pin: the verdict, the p value, three flyovers on one clock, the radius. A result is a lead." |
| 1:42 | Remove one flyover, resubmit, or show a saved Candidates result | "With only two flyovers it will not claim a location. It finds the right place and still says: candidates, unconfirmed. Two flyovers never prove it." |
| 1:50 | A Not locatable result | "And most clips have no flyover at all. It says so in seconds, and why." |
| 1:55 | Oyster Bay result, or the Evidence table in the README | "On a real one-hour recording from New York, with real flight data and the real temperature: ninety-six metres from where it was made." |

## If something goes wrong

- **A box shows "No curve found".** Make it taller or longer; the bend must be inside it.
- **The result is Candidates with three flyovers.** One box is off its bend. Use the finished
  case. Do not claim it located.
- **The search is slow.** Talk through the stages; switch to the finished case at 1:30.

## Things not to say

- Not "accuracy" or "probability" next to the strength number: it is a **match strength**.
- Not that it works on any video: it needs the date, uncut outdoor audio and two or more
  propeller flyovers, and in the UAE those are rare outside one corridor.
- Not that the UAE pack is proven: no UAE recording with a known position has been tested.
