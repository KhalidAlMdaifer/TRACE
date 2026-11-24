# TRACE

**T**racking **R**ecordings via **A**ircraft **C**urve **E**stimation.

Locate where a recording was made from the aircraft it accidentally captured.

Propeller aircraft leave a faint tone in outdoor recordings. As an aircraft passes, the tone
falls in pitch, and the exact shape of that fall depends on where the microphone was. With
public flight tracks for the day, each candidate place predicts a different curve; the
recording picks the one that fits. TRACE wraps that method in a tool for analysts: upload a
recording, give its date and a rough area, confirm the flyovers on a spectrogram, and get
ranked location leads with a verdict, or a clear "not locatable".

New to the project? [HANDOFF.md](HANDOFF.md) explains all of it in one file: the method, every
feature, the structure, the decisions and what is unfinished.

It is a hackathon MVP built on the open-source
[dopplertrack](https://github.com/mjshiggins/dopplertrack) library, which does the search.

## What it can and cannot do

- It needs the **recording date**, **unedited audio**, and at least **two propeller flyovers**.
  Three or more on one clock can confirm a location; two give candidates only.
- **Most short clips are not locatable.** The app says so in seconds and explains why.
- A result is a **lead to corroborate, not proof**. Every result shows its verdict, p value,
  uncertainty radius and the number of flyovers behind it; never a bare pin.
- It works only where and when propeller aircraft fly and appear in the public archive. In
  the UAE that is mainly the corridor from Dubai South to Al Ain, in daytime
  ([docs/coverage-findings.md](docs/coverage-findings.md)).

## Intended use

Built for cybercrime investigation and footage verification by accountable users. Every
route needs a sign-in; a case reference is required before a search; every upload, search
and export is written to an audit log; uploads and searches are rate-limited. It is not a
public service and must not be used to locate private individuals. The same method that
verifies footage can find where a person lives.

## Accounts, deletion and running it for others

There is no sign-up page. The first account comes from `ADMIN_EMAIL` and `ADMIN_PASSWORD`
when the app first starts; changing them in `.env` later does nothing. Give each analyst
their own account, so the audit log says who did what:

```bash
uv run python -m app.cli user add analyst@example.org     # asks for the password; --role admin sees every case
uv run python -m app.cli user passwd analyst@example.org
uv run python -m app.cli user list
```

With Docker, put `docker compose exec api` in front in place of `uv run`. A changed password
does not end sessions that are already open; they last `SESSION_HOURS`.

- **Deleting.** "Delete" on the Cases page removes a case with its recording, spectrogram,
  flyovers and results. The audit log keeps its lines, with the recording's name and hash.
  `RETENTION_DAYS=30` makes the worker delete cases older than that; unset or 0 keeps them.
- **Sign-in.** Ten failed sign-ins from one address in fifteen minutes block that address
  until the window passes.
- **Beyond localhost.** The Docker setup serves plain HTTP on port 8080. To let anyone else
  reach it, put it behind a proxy that adds HTTPS and set `SESSION_SECURE=1`. This is not
  done for you.

## Quick start with Docker

Needs Docker with Compose, and about 2 GB of disk for the images.

```bash
git clone <this repository> trace && cd trace
cp .env.example .env
```

Edit `.env`: set `APP_SECRET` to a long random string, and `ADMIN_EMAIL` and
`ADMIN_PASSWORD` to the sign-in you want. To try the built-in demo, also set
`DEFAULT_PACK=test` and `SHOW_DEV_PACKS=1`. Then make the data folder yourself, so that it
belongs to you and not to root, and start the stack:

```bash
mkdir -p data
docker compose up --build
```

In another terminal, install the demo recording (a simulated 30 minute recording with three
flyovers and a known answer, plus its invented flight day):

```bash
docker compose exec api python -m app.cli demo
```

Open http://localhost:8080 and sign in. Then follow "The demo" below. Data lives in
`./data` on your machine.

On a Mac, Docker is also the fast way to run it: the containers are Linux, so a search uses
every core (measured: 41 s in Docker against about 4 minutes natively). OrbStack works
(`brew install --cask orbstack`). On a Mac, or on Linux if your user id is not 1000, start it with
`TRACE_UID=$(id -u) TRACE_GID=$(id -g) docker compose up --build` so the files in `./data`
are yours.

## Quick start without Docker

Needs Python 3.12 or newer with [uv](https://docs.astral.sh/uv/), Node 20 or newer, and
`ffmpeg` and `ffprobe` on the path. Linux gives multi-core searches; macOS runs one worker.

```bash
git clone <this repository> trace && cd trace
uv sync
npm --prefix frontend ci
cp .env.example .env
```

Edit `.env` as above (for the demo: `DEFAULT_PACK=test` and `SHOW_DEV_PACKS=1`). Then:

```bash
uv run python -m app.cli demo
scripts/dev_backend.sh
```

That last command runs the api on port 8000 and the job worker. In a second terminal:

```bash
npm --prefix frontend run dev
```

Open http://localhost:5173.

## The demo

1. **Upload.** Choose the region "Synthetic test pack" at the bottom left of the map, then
   drop `data/demo/synthetic.wav`. Analysis starts at once.
2. **When.** Date `14 Nov 2026`. Pick "Afternoon".
3. **Where.** Pick "Home square".
4. **Flyovers.** The spectrogram shows three falling S-shaped tones near 05:00, 12:45 and
   20:30. Drag a box about 100 seconds wide around the bend of each. Each turns solid with a
   red fitted curve. The dashed boxes are automatic suggestions; they are hints, and several
   sit on the wrong part of a tone.
5. **Review.** Type any case reference and submit.
6. **Result.** About a minute later: **Located**, within about 50 to 100 m of
   25.0500° N, 55.2500° E, the point the recording was simulated at.

To see the other outcomes: remove one flyover and submit again for **Candidates** (two
flyovers never confirm a place); upload any recording with no aircraft and choose "Finish as
not locatable" for **Not locatable**.

`scripts/curl_walkthrough.sh` does the same from the command line. A two-minute spoken
version is in [docs/demo-script.md](docs/demo-script.md).

### A real recording

The method's reference case is a one-hour recording made at Oyster Bay, New York, on
8 September 2026 (the `ny` pack). It needs the recording, which is on YouTube and not in
this repository, and that day's flights (a 4 GB stream). With both in place TRACE located it
96 m from the true position. The steps and numbers are in
[docs/03-method-and-evidence.md](docs/03-method-and-evidence.md).

## Flight data

Flight tracks are not shipped. For a real region, pick the recording date in the When step;
if that day is not on disk the app offers "Load it (about 4 GB stream, several minutes)".

The newest day is kept up to date for you. When someone signs in, the app looks for the
newest day the archive has published for the default region (usually yesterday, UTC) and, if
it is not on disk, streams it in the background. The download arrow in the header shows it:
a bar runs under the header while the day comes in, and a click gives the day, the size and
how far it has got. It checks at most once an hour and never fetches a day twice. Set
`FLIGHTS_AUTO=0` to switch this off; then nothing is fetched unless an analyst asks. The
synthetic test pack is never updated.

Each day goes through an integrity filter
(ADS-B positions only, not stale, accurate, no impossible jumps) and the share of track
points it removed is shown with every result.

## How it works

1. **Triage.** The upload is hashed, decoded and turned into a spectrogram of 40 to 450 Hz
   in seconds. Automatic detection then proposes flyovers in the background.
2. **Flyovers.** The analyst boxes the bend of each real flyover. Each box is fitted to an
   ideal Doppler curve (fundamental, speed, closest distance, time).
3. **Search.** dopplertrack joins every pair of that day's propeller flights that could have
   produced two of the flyovers that far apart, lays ground points where both could be
   heard, models the curve each point would hear from the real trajectories, and scores it
   against the recording. Further flyovers are matched on the same clock.
4. **Verdict.** The best pair is judged against the crowd of wrong pairs, not against the
   runner-up alone. TRACE adds rules on top: three flyovers and a `located` verdict for
   **Located**; otherwise **Candidates**; matches outside the stated area or time are
   flagged, not hidden.

The recording's start time is not an input. It falls out of the search.

## Evidence

Measured during this build; details and method in
[docs/03-method-and-evidence.md](docs/03-method-and-evidence.md).

| Case | Outcome |
|---|---|
| Oyster Bay, real recording, real flights, real temperature | Located, p 0.037, 96 m from the true position |
| Same, at the library's default temperature | Located, p 0.002, 32 m |
| Synthetic, three hand-drawn flyovers | Located, p 0.043, about 1 m |
| Synthetic, two flyovers | Candidates; the true place ranked first but unconfirmed |
| Synthetic audio against real UAE flights (no possible match) | "No match", p 0.75: no location claimed |
| UAE track integrity, one day | 11.5% of track points failed a check |

## Limits

- **Two flyovers never prove a location**, even when they find it.
- **A verdict of `located` at p under 0.1 is a weak claim.** The library's author saw two of
  twenty searches with no right answer called located. TRACE shows "Located, weak" between
  p 0.01 and 0.1.
- **Air temperature matters.** A 25 °C error moved one synthetic answer 7.7 km. The p value
  also changes with temperature, so compare results only at the same temperature.
- **The fit of a flyover is the weak link.** A box a second or a hertz different can fit a
  different curve. The search fits each box three ways and keeps the best, which fixed the
  case found; real recordings were only checked on Oyster Bay.
- **Wind is not modelled.** Jets and helicopters are not valid sound sources for this method;
  helicopters pass the propeller filter and are common over Dubai city.
- **No UAE recording with a known position exists yet**, so the UAE pack is untested end to
  end. The placebo-day control is built but unvalidated and off by default.
- Edited or re-encoded audio with cuts puts flyovers on different clocks and will mislead.

## Configuration

Everything is set in `.env`; [.env.example](.env.example) lists each option. The ones that
reach outside your machine:

| What | Effect |
|---|---|
| A user presses "Load it" | streams one UTC day of flight tracks from adsb.lol's public archive on GitHub |
| Someone signs in, with `FLIGHTS_AUTO=1` (the default) | asks GitHub which day is the newest published, and streams it (about 4 GB) for the default region if it is not on disk |
| An analyst opens a **Located** result, with `MAP_TILES_URL` set (the default) | the browser loads street-map tiles around the estimate from the tile host (OpenStreetMap's by default), which shows that host roughly where the result is. Set `MAP_TILES_URL=` (empty) to keep the dot map and send nothing |
| An analyst presses "Google Maps" on a result | opens Google Maps in a new tab at the result's coordinates, which sends them to Google |
| `WEATHER_AUTO=1` | looks up the hourly temperature from Open-Meteo, sending a region's weather point and a date |
| A search on a pack with `terrain_zoom` | downloads elevation tiles from AWS Terrain Tiles |
| First use | downloads the ICAO aircraft type table from the OpenSky Network |

## Development

```bash
uv run pytest                           # about 13 minutes: fits, searches and the service end to end on the synthetic case
uv run pytest -m "not slow"             # skips the detection and real-process tests
npm --prefix frontend test              # the step machine and formatting
npm --prefix frontend run build         # type-check and production build
```

`CLAUDE.md` has the rules of the project and where things are; `docs/` has the product,
engine reference, evidence, architecture, confidence rules, design and decision log.

```
backend/app/core/     media, spectrogram, flyover fits, flights, integrity, packs, weather, search, confidence, report
backend/app/jobs/     triage, search and fetch jobs, each run in its own process
backend/app/api/      the HTTP API, sign-in, the fit pool, the event stream
backend/app/packs/    region packs: uae, ny, test
frontend/src/         the interface: one page, a panel and a dot-matrix map or spectrogram
scripts/              engine smoke test, coverage report, pack builder, curl walk-through
```

## Built on

- [dopplertrack](https://github.com/mjshiggins/dopplertrack) by MacCallister Higgins, MIT licence. The search engine, pinned at commit `2d899bb`. Its notice is below.
- Flight tracks from [adsb.lol](https://www.adsb.lol/), Open Database License 1.0.
- Emirate and region boundaries © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, Open Database License 1.0, the emirates via [geoBoundaries](https://www.geoboundaries.org/).
- Air temperature, when looked up automatically: weather data by [Open-Meteo.com](https://open-meteo.com/), CC BY 4.0. Free for non-commercial use.
- Aircraft types from ICAO Doc 8643 via the OpenSky Network.
- Elevation from AWS Terrain Tiles.
- The result's street map: [Leaflet](https://leafletjs.com/) (BSD 2-Clause), with map tiles © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, from OpenStreetMap's own tile server. That server is for light use: a busy deployment should point `MAP_TILES_URL` at its own or a paid tile host.
- Typefaces: Instrument Sans and DM Mono, SIL Open Font License.
- The technique was first shown in colsto's video "I discovered a sound that leaks your exact location".

### dopplertrack licence notice

```
MIT License

Copyright (c) 2026 MacCallister Higgins

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Licence

TRACE's own code is under the MIT licence: see [LICENSE](LICENSE). The data it uses keeps its
own terms, listed under "Built on": in particular, flight-track and boundary extracts are
under the Open Database License, and must stay so if published.
