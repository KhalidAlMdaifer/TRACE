# Design

The user approved this look on 21 November 2026 after two rounds of mockups: near-black,
dot-matrix, pill controls, small uppercase mono labels, red as the only accent. It takes
style cues from a reference the user liked (a dark site with a dot-grid graphic); the
layout, mark and copy are our own. Do not copy that site.

- Live mockups (private to the user): https://claude.ai/artifact/B3Ve8tz3zQM21556nhXDpD
- `design/mockups/*.dc.html`: the sources of the nine mocked screens. They only run inside Claude's design canvas, so they will not open standalone, but the markup and inline styles are exact. Copy values from them.
- `design/tokens.css`: the tokens below as CSS variables, ready to import.

Every number, name and coordinate in the mockups is sample data.

## 1. Tokens

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0C0C0B` | map area, page |
| `--panel` | `#111110` | side panel, map chips |
| `--card` | `#171716` | cards, inputs |
| `--raised` | `#1C1C1A` | secondary pills, badges |
| `--line` | `#272725` | hairlines, card borders |
| `--line-strong` | `#3A3A36` | control borders |
| `--line-dash` | `#55524C` | dashed borders, leader lines |
| `--text` | `#F4F1E8` | primary text, primary button fill |
| `--text-2` | `#A8A39A` | secondary text, mono labels |
| `--text-3` | `#8A857C` | muted text (still 4.5:1 on panel and card) |
| `--red` | `#FF4D42` | the accent |
| `--red-tint` | `rgba(255,77,66,0.14)` | selected control background |
| `--dot-1`, `--dot-2`, `--dot-3` | `#3A3A36`, `#6B6862`, `#C9C5BB` | dot brightness levels |

Color meaning, kept strict:

- **Red** is signal: the selected area, cells that match, the estimate, flyover tones, the active step, progress.
- **Ivory** is text, primary actions, flight paths, completed steps.
- **Gray** is context.
- Match strength is red at rising opacity (about 0.25, 0.5, 0.8, 1.0). Rings mark leading candidates.
- No green, no second accent, no gradients.

Type

- Text and headings: Instrument Sans 400, 500, 600 (fallback `system-ui`).
- Labels and data: DM Mono 400, 500 (fallback `ui-monospace`).
- Mono label: 11px, `letter-spacing: 0.08em`, uppercase, `--text-2`.
- h1 34px, weight 500, line-height 1.08, `letter-spacing: -0.02em`. Body 15px / 1.5. Helper 12px.
- Numbers that change or align use `font-variant-numeric: tabular-nums`.

Shape and size

- Pills (buttons, badges, presets) `border-radius: 999px`. Cards 16px, inputs and emirate buttons 12px, dropzone 20px.
- Buttons 48px tall; every hit target at least 44px.
- Primary button: ivory fill, dark text, trailing arrow. Secondary: `--raised` fill, 1px `--line-strong` border.
- The dot motif is a small square (6px in UI): step markers, bullets, status markers, legend swatches. Slider handles are 16px squares.

Tailwind: map the variables in the theme (`colors.bg = 'var(--bg)'` and so on, `fontFamily.sans`, `fontFamily.mono`, `borderRadius.pill = '999px'`).

## 2. Layout

One page. Left panel about 400px wide (`--panel`, 28px padding, 1px right border), map fills the rest. Below about 960px the panel stacks above the map (minimum map height 480px). Panel, top to bottom: header (mark, app name, analyst pill), step markers, content, actions pinned to the bottom.

Mark: a 3 x 3 grid of ivory squares with a red centre. App name: **TRACE** (the mockups still show the placeholder `[App name]`; render `TRACE`).

Step markers: Upload, When, Where, Flyovers, Review, as a wrapping flex row with `justify-content: space-between` (five equal grid columns are too narrow for "Flyovers" at 400px). Done steps get an ivory square, the current one a red square and ivory label, later ones a gray square.

## 3. Component states

| Component | Default | Hover | Focus | Selected / active | Disabled | Loading | Error |
|---|---|---|---|---|---|---|---|
| Primary pill | ivory | `#FFFFFF` | 2px `--red` outline, 2px offset | | 40% opacity | label swaps to a mono status, no spinner | |
| Secondary pill | `--raised` | border `--text-3` | same outline | | 40% opacity | | |
| Preset pill, emirate button | border `--line-strong` | border `--text-3` | same outline | border `--red`, `--red-tint`, filled red square, weight 600 | | | |
| Input | `--card`, border `--line-strong` | | border `--text` | | | | border `--red`, helper text in `--red` |
| Card | `--card`, border `--line` | | | | | skeleton rows in `--raised` | |
| Dropzone | dashed `--line-dash` | | | dragging over: border `--red`, `--red-tint` | | uploading: file card with thin red bar | unsupported file: red border, one line saying why |

Focus is always visible. Do not remove outlines.

## 4. Screens

Mocked in `design/mockups/`: nine artboards, each a self-contained source file (open them as text; do not try to run them). The user approved the look on the first seven. On 2026-11-21 those seven were corrected against the engine and two were added, Flyovers and Candidates, in the same style; the user has not reviewed that revision yet.

1. **Upload** (`Main`). Badge "New report", h1, dropzone, formats in mono, "Browse files", three bullets, logging note. Map: dim dot map with a legend.
2. **When.** File card with a thin red bar and "10 of 32 min checked · 2 proposed", date input, preset pills, time readout, two-handle slider on a 24-hour track, "Flights in this window" card with a red count. Map: flight paths as thin ivory lines.
3. **Where.** File card with detection progress. Two-column emirate buttons plus "Not sure, search all". Card with "Your area: Dubai" and "Search covers: All UAE flights that day". Map: selected emirate in red dots with a red outline, labels with leader lines for the small emirates, "Draw a custom area".
4. **Flyovers** (`Flyovers`, the event editor). The step between Where and Review, and the most important screen for result quality.
   - Main area: a dot-matrix spectrogram, time across (a zoomed window, 03:00 to 23:00 in the sample), 60 to 240 Hz up. Whitened brightness maps to dot brightness; steady hum rows show as faint lines. Underneath, an overview strip of the whole recording with the visible window, a mark per flyover and the part detection has not reached yet. In the app the plot covers 40 to 450 Hz and pans and zooms; the overview strip is the scroll bar.
   - Overlays: status "Checking for flyovers · 26 of 32 min · 5 proposed" top left, legend top right, zoom out, zoom in and "Whole recording" bottom right, hint "Drag on the spectrogram to box a flyover" bottom left.
   - Panel: "Flyovers marked" list (number chip, time, fitted f0 · speed · distance, state Confirmed or Fitting, a remove button), a card for the selected box (its time and frequency range, a harmonics stepper), a status card ("2 confirmed · 1 fitting" and "Two make the recording searchable. A third lets a result be confirmed."), Back and Continue.
   - The spectrogram is available about a second after decoding, long before detection finishes. The editor is usable from that moment: the analyst can draw boxes by hand while proposals are still arriving.
   - Proposals from `detect` appear as dashed ivory boxes with a thin ivory line, slice by slice as detection works through the recording (about 2 s per minute of audio). Proposals with `burst` over 0.15 are drawn gray and marked "possible vehicle".
   - Proposals are hints, and often several land on one aircraft: its long steady approach tone attracts them, while the real closest approach is where the curve bends. The mockup shows this: both suggestions sit on a real flyover's flat tail. Expect the analyst to move or redraw most of them. Never treat a proposal as confirmed.
   - The analyst clicks a proposal to confirm it, drags its edges to adjust it, or drags on empty spectrogram to draw a new box. The right box is about 100 s wide, centred on the bend, and tall enough to contain the curve over that time; show a ghost box of that shape on hover as a guide.
   - Releasing a box starts a fit. Box states: **fitting** (dashed red outline, mono "Fitting" tag, about 2 s), **confirmed** (solid outline, red curve drawn across the box; the selected one also gets corner handles), **failed** (red outline, one line: "No curve found in this box. Make it taller or longer."). Boxes under 20 s or 2 Hz snap back to that minimum. A newer drag on the same box cancels the fit in flight.
   - The harmonics stepper runs 1 to 3 and is capped so the top harmonic stays under 450 Hz.
   - Continue is enabled at two confirmed flyovers, whether or not detection has finished.
   - The curve shown here is a quick preview. The search refits each box more carefully, so the result screen's numbers can differ slightly. The result screen draws the search's own curves; the UI does not need to explain the difference.
5. **Review.** Summary rows with Edit links: File, Date, Time, Area, Temp ("28 °C, automatic"). Flyover card: "3 flyovers confirmed", badge "Searchable", a spectrogram strip with the three boxed tones, chips "1 · 05:08", "2 · 12:47", "3 · 20:29", the note "Three flyovers on one clock can confirm a location. Two give candidates only.", an Edit link back to Flyovers. Case reference, Back, "Submit report". With two flyovers the count and the note change; the badge stays "Searchable".
6. **Searching** (`Analyzing`). Case line, h1 "Searching the UAE", stage list (ivory square done, red square with halo and thin bar active, outline pending): Flyovers fitted, Flights loaded, Pairing flights, Laying search points, Scoring, Extra flyovers, Refining to 50 m. "Best match so far", "Cancel search". Map: dots by match strength, rings on the leading candidates, a dashed box labelled "Best area so far".
7. **Result, located** (`Result`). Coordinates, "within about N m" with an "Open in map" link, "Recording started 13:40:58 GST" (the clip's clock falls out of the search), confidence card (band, strength out of 100, 20-square meter, rows: verdict against N wrong pairs, lead over the best wrong pair in tail widths, flyovers used, uncertainty radius, air temperature), curve card with the three tones and the model line, three matched flights with closest-approach time and slant distance, export, alternates, new report. Map: close-up dot grid, red match cells, uncertainty circle, ivory ring on the best cell, three flight paths with closest-approach markers, scale bar, inset locator.
8. **Result, candidates** (`Candidates`). Eyebrow "Result from 2 flyovers", h1 "Candidates, unconfirmed", "Two flyovers fit these places. None is confirmed." Confidence card: band Low, strength, the verdict row ("Ambiguous, p 0.23"), flyovers used, air temperature. A ranked list of up to five places as toggle buttons: number chip, coordinates, emirate, the two aircraft types in order, score; a place outside the stated area is tagged "outside your area" with a dashed chip. Pressing one flies the map there. Primary action "Add a third flyover" (back to the editor) under the line "A third flyover from the same recording can confirm one of these.", then Export report and New report. Map: numbered rings, the selected candidate in red with its two flights, the others ivory, the outside one dashed. Use the sub-labels from `06-confidence.md` in place of "unconfirmed" when the verdict is `no match` or `insufficient`.
9. **Not locatable** (`NotLocatable`). Explanation, "What we checked" with an empty spectrogram strip, "What would help", "Try another file", "Mark flyovers by hand" (opens the editor), "Export report". Map: the selected area in brighter gray dots, no red.

Not mocked; build from the tokens and these notes:

10. **Sign in.** Centred card on the dot map: mark, email, password, primary pill. One line on intended use.
11. **Outside-match banner.** On either result screen when a stronger match lies outside the stated area or time: a bordered strip above the list, "A stronger match lies outside your area", with "Show it". If that match passes the located test, "A confirmed match lies outside your area" (`06-confidence.md`).
12. **Cases.** A table of the analyst's cases: reference, file, date, state, created. Row opens the case at its last step.
12a. **Header, on every page.** A back arrow left of the mark (the step before; "Cases" from a case's first step; "New report" from the
    cases list; none on Upload), and right of it a download arrow for the default region's flight data: dim when up to date, pulsing with a
    2 px bar under the whole header while a day is checked or streamed, a red dot when the update failed. A click opens a card with the day,
    "1.23 of 3.61 GB", the percentage, and "Try again" after a failure. Not in the mockups.
12b. **Located, on a street map.** The close-up is a real map in the dark style (streets and place names), with the same layers as the
    mockup: red match cells, white flight paths with a square at each closest point, the red uncertainty circle and "Estimate, within N m".
    It flies in from the wider view when the result opens. Zoom buttons top left, scale and map credit bottom left; the legend and the
    locator thumbnail stay where they were. Not in the mockups, which draw the close-up as dots.
13. **Data not loaded.** In the When step, when the date's flight data is missing: the flight counter card becomes "Flight data for this date is not loaded" with "Load it (about 4 GB stream, several minutes)" and a progress bar while it runs.

## 5. Where the mockups are still approximate

The mockups now follow the engine: five steps, a three-flyover Located sample with the real verdict rows, the search stages the library has, whole-pack search wording, temperature shown, proposals as guesses. What is still a stand-in:

| In the mockups | In the app |
|---|---|
| Every number, time, coordinate, aircraft type, file name and case reference | Samples chosen to be consistent with each other (a 32:10 recording, flyovers at 05:08, 12:47 and 20:29, clip start 13:40:58). Take real values from the API; never copy a sample into code or a fixture |
| Emirate outlines | Rough hand-drawn placeholders; use real boundaries (`04-data.md`, section 6) |
| Spectrograms, in the editor and in the strips | Invented dots from `design/spectrogram_prototype.py`. Draw the real grid from `GET /spectrogram` |
| The editor shows one zoom level and 60 to 240 Hz | Pan, zoom and the full 40 to 450 Hz |
| The Searching map is zoomed on the analyst's area | The search covers the whole pack. Frame wherever the leading candidates are, and keep the analyst's area outlined |
| No "Controls" stage in the Searching list | Add it after "Refining to 50 m" when placebo days are switched on |
| Result close-up has no streets | Fine for the MVP; the "Google Maps" link beside the radius opens the point there in a new tab (the mockups say "Open in map") |
| Candidates lists four places | Up to five |
| The file card says "10 of 32 min checked · 2 proposed"; the editor says "Checking for flyovers · 26 of 32 min · 5 proposed" | Intended: the card is narrow. Both count proposals, never confirmed flyovers |
| Sign in, outside-match banner, Cases, Data not loaded | Not drawn; notes in section 4 |

As built (M3 and M4), where the app differs from the mockups on purpose:

| Mockup | App | Why |
|---|---|---|
| "Modelled tone against the recording", "Model from flight data" | "Fitted tones against the recording", "Curve fitted to each tone" | the curves are fits of the audio; trajectory-modelled curves are not built yet |
| "Flight 1, single-engine piston" | "Flight 1, SR22 · AAA001" | the data has the type designator and the aircraft address, not a plain-language class |
| Flight paths on the When, Where and Review maps | none | no route serves a day's tracks yet; paths appear on the result maps |
| Result close-up frames about 400 m | frames the estimate and the nearest closest-approach points, 500 m to 5 km each way | the matched flights should be on screen |
| Step markers on every screen | none on Searching and the results | as in the result mockups |
| "Not sure, search all" only | plus "Finish as not locatable" in the editor | the shortest way to the designed Not locatable outcome |

## 6. Dot-matrix map

Each dot is a cell. In the app, draw dots on a canvas from data: land cells from the pack's `grid`, match cells from the search stream.

- Brightness texture: most land dots `--dot-1`, a random quarter `--dot-2`, a few `--dot-3`. Seed the randomness from the cell coordinates so it does not flicker between renders.
- Country view: dot pitch about 14px. Search and result views: one dot per lattice cell (200 m, then 50 m), pitch 24 to 40px.
- Selection recolors an emirate's dots red and strokes its outline in red.
- The mockups fake this in SVG: each row of dots is one horizontal line with `stroke-width` equal to the dot size and a `stroke-dasharray` of `size gap`. `design/dot_map_prototype.py` generated those rows.
- Small emirates are a few dots wide at country scale. Selection must work from the list, and their labels sit in the sea with leader lines.

## 7. Copy

Tone: plain, short, no jargon the analyst did not bring. Say what happened and what to do.

| Place | Text |
|---|---|
| Upload h1 / body | "Upload a recording" / "Video or audio. Analysis starts the moment the file lands, while you fill in the rest." |
| Upload bullets | "Recorded outdoors or by an open window" · "Uncut, and several minutes or longer" · "From a known date" |
| File card states | "Uploading · 62%" · "Reading audio" · "10 of 32 min checked · 2 proposed" · "6 proposed" · "None proposed. You can still mark flyovers by hand." |
| When | "When was it recorded?" · "Required. It cannot be later than the upload date." |
| Where | "Roughly where?" · "Pick one or more emirates, here or on the map. Matches outside them are flagged, not hidden." |
| Flyovers | "Confirm the flyovers" · "Each S-shaped curve is an aircraft passing. Put a box around the bend of each real one. The suggestions are guesses." |
| Flyovers status | "Checking for flyovers · 26 of 32 min · 5 proposed" · "2 confirmed · 1 fitting" · "Two make the recording searchable. A third lets a result be confirmed." |
| Flyover box | "Fitting" · "No curve found in this box. Make it taller or longer." · "Suggestion" · "Possible vehicle" |
| Review | "Review and submit" · "3 flyovers confirmed" · "Searchable" · "Three flyovers on one clock can confirm a location. Two give candidates only." · "Required. The search is logged against it." |
| Searching | "Searching the UAE" · "Your area, Dubai, ranks the matches. You can close this page; the report keeps running in your case list." |
| Located | "Estimated location" · "within about 150 m" · "Open in map" · "Recording started 13:40:58 GST" · "Verdict against 380 wrong pairs" · "Lead over the best wrong pair" |
| Candidates | "Result from 2 flyovers" · "Candidates, unconfirmed" · "Two flyovers fit these places. None is confirmed." · "A third flyover from the same recording can confirm one of these." · "Add a third flyover" |
| Not locatable | "Not locatable" · "No aircraft flyover was found in this recording, so there is nothing to match against flight data." · "Mark flyovers by hand" |
| Errors | "That file has no audio track." · "Flight data for this date could not be loaded. Try again." · "The search stopped: {reason}. Nothing was lost; start it again from Review." |

Never write "accuracy" or "probability" next to the strength number. Use "match strength".

## 8. Motion

- Durations: 120 ms hover and press, 200 ms content swap, 320 ms panel change, 800 ms map camera.
- One entrance curve, `cubic-bezier(0.2, 0, 0, 1)`. Springs only on draggable handles and boxes.
- Animate transform and opacity only.
- The file card morphs into the compact file chip; panels slide 12px and fade.
- No bare spinners: named stages, skeletons, live counters.
- Dots: land dots fade in row by row on first load; selected-area dots flip to red with a short stagger; during search, cells brighten as they are scored and the active marker pulses.
- Result reveal is the one long sequence, about 1.2 s: camera flies in, uncertainty circle draws, strength counts up, meter squares fill.
- Honor `prefers-reduced-motion` with plain fades.
- Every tap answers within 100 ms, even if only with a pressed state.
- Waits that cannot be removed, and what covers them (times measured on one core, `02-dopplertrack.md`): decoding and spectrogram, seconds, the file card's bar; detection, about 2 s per minute of audio, proposals appearing slice by slice while the analyst fills in When and Where; a box fit, about 2 s, the box's "Fitting" state; the search, tens of seconds to minutes, the stage list and the map filling in.

As built: hover and press at 120 ms, panel change at 320 ms with a 12 px slide, map camera at
800 ms, land dots fading in row by row, selected-area dots turning red with a quarter-second
stagger, the active search stage pulsing, and the result reveal (camera, circle, strength
counting up, meter filling). Not built: the file card morphing into a chip. All of it is
CSS transitions and canvas frames; `prefers-reduced-motion` gives plain states.

## 9. Accessibility

- Real `button`, `a`, `input` with `label`; `aria-pressed` on toggles; `aria-current="step"` on the active step; `role="progressbar"` with values; the stage list is an ordered list.
- Text contrast at least 4.5:1. State never relies on color alone: selected controls also get a filled square and heavier weight.
- The map and spectrogram canvases carry a text alternative, and everything they allow (selecting an emirate, confirming a flyover, picking a candidate) is also possible from the panel with the keyboard.
- The event editor's boxes are adjustable with arrow keys when focused.

As built: all of the above, with one gap: a custom area can only be drawn with a pointer.
Checked with the keyboard and by reading the markup; no screen reader was run. In the editor
a flyover's row takes the keys (arrows move the box, Alt with arrows resizes, Shift makes
bigger steps, Delete removes), and the Suggestions list in the panel has Confirm and Dismiss.

