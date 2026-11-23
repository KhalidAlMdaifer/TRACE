# Data

Every external dataset the app touches, its exact shape, and the traps.

## 1. Flight tracks: adsb.lol daily archives

- Repositories `github.com/adsblol/globe_history_YYYY` (2023 onward). One GitHub release per **UTC day** and per collector pod.
- Release tag: `vYYYY.MM.DD-<pod>`, default pod `planes-readsb-prod-0`. Other pods (`...-prod-1`, `...-staging-0`) are duplicates from other collectors; fall back to them if the default is missing for a day.
- Assets: a tar split into parts (`...tar.aa`, `...tar.ab`). About 4 GB per day, global.
- dopplertrack's `fetch_day(date, bbox)` finds the assets through the GitHub API (`api.github.com/repos/adsblol/globe_history_{year}/releases/tags/{tag}`), streams the parts in order, resumes with HTTP Range on dropped connections, and keeps only traces with a point inside the bbox. Nothing is written to disk. Unauthenticated GitHub API calls are rate-limited (60 per hour per IP), which is ample for one call per day fetched.
- Inside the tar: `traces/<xx>/trace_full_<icao>.json`, gzip-compressed JSON despite the extension, one file per aircraft.
- Licence: Open Database License 1.0. Attribute adsb.lol in the README and the report footer. If we publish a derived database (our regional extracts), it must be under ODbL too.

### Trace file format (verified on the sample in dopplertrack's tests and the readsb docs)

Top level: `icao`, `r` (registration), `t` (ICAO type designator, for example `SR20`), `desc`, `dbFlags`, `ownOp`, `year`, `version`, `timestamp` (unix seconds, start of the UTC day), `trace`.

Each `trace` row is a 14-element array:

| Index | Meaning |
|---|---|
| 0 | seconds after `timestamp` |
| 1, 2 | latitude, longitude |
| 3 | barometric altitude in feet, or the string `"ground"`, or null |
| 4 | ground speed, knots, or null |
| 5 | track, degrees (true heading when on the ground) |
| 6 | flags bitfield: 1 position stale, 2 start of a new leg, 4 vertical rate is geometric, 8 altitude is geometric |
| 7 | vertical rate, ft/min |
| 8 | aircraft object with extra fields, or null (present on roughly a quarter of rows) |
| 9 | position source: `adsb_icao`, `adsr_icao`, `tisb_icao`, `mlat`, `adsc`, `other`, ... |
| 10 | geometric altitude, feet (WGS-84 ellipsoid), or null |
| 11 | geometric vertical rate |
| 12 | indicated airspeed |
| 13 | roll angle |

The aircraft object, when present, carries `nic`, `rc` (radius of containment, metres), `nac_p`, `sil`, `category`, `flight`, `squawk` and more. In the sample, a healthy ADS-B aircraft reports `nic` 9 and `nac_p` 10.

`dbFlags`: 1 military, 2 interesting, 4 PIA, 8 LADD.

Sample statistics (one Cirrus SR20, one day): 1,038 rows over 5.3 hours, median 2.9 s between rows, 99.7% `adsb_icao`.

### What dopplertrack does with a trace

`parse_trace_bytes` keeps rows with a position, converts altitude to metres (index 10 if numeric, else index 3), ground speed to m/s, and marks ground rows. It ignores the source type and the integrity fields. `Trace.segments()` splits on gaps over 90 s and on ground/air transitions and keeps airborne stretches. `DayIndex.build` resamples each to 1 Hz.

### Integrity filter (ours, milestone 5)

GPS jamming and spoofing have been reported around the UAE and the Gulf in 2026, and ADS-B positions come from the aircraft's own GPS. A spoofed or jammed track gives a wrong modelled curve. dopplertrack does not filter for this, so we wrap its parser:

- Keep rows whose source (index 9) is `adsb_icao`. Drop `mlat`, `tisb_*`, `adsr_*`, `adsc`, `other`, and `adsb_icao_nt` (emitters without a transponder, such as ground vehicles).
- Carry the last seen `nic` / `nac_p` forward from the aircraft object; drop stretches where `nac_p < 8` or `rc` is above about 200 m.
- Drop rows flagged stale (flags bit 1).
- Drop points implying an impossible jump (speed between consecutive points far above the reported ground speed).
- Record per day how many rows were dropped and show it with the result ("12% of track points that day failed integrity checks").

Thresholds are starting values; tune them with the coverage probe.

## 2. Aircraft type table: ICAO Doc 8643

- `https://opensky-network.org/datasets/metadata/doc8643AircraftTypes.csv`, downloaded once to the cache by `AircraftTypes()`.
- dopplertrack reads the columns `Designator` and `EngineType`. A type is a propeller type if `EngineType` contains `Piston`, `Turboprop` or `Electric`. Unknown or missing designators are **kept** as possible props.
- Turboshaft helicopters share the `Turboprop/Turboshaft` engine class in this table, so helicopters pass the filter. Their rotor tones are a different problem from propeller tones (lower fundamental, slower flight, often outside `detect`'s 40 to 170 m/s scan). The coverage report counts them separately when the table has an `AircraftDescription` column; check that column exists when the file is first downloaded.

## 3. Elevation: AWS Terrain Tiles

- `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png`, Terrarium encoding, cached per zoom under the dopplertrack cache.
- `Terrain(zoom=12)` for a region the size of the UAE (zoom 9 is for continents). Elevations are clamped at zero in the lattice.
- Minor known simplification: geometric aircraft altitude is ellipsoidal, tile elevation is above mean sea level; the difference (tens of metres) is small against kilometre slant distances.

## 4. Air temperature (required input to the physics)

`c = 331.3 * sqrt(1 + T/273.15)`. A 25 C error moved a synthetic answer 7.7 km; within 5 C it held (see the evidence file). So every case needs a temperature.

- Order of preference: analyst override, then an automatic lookup of the hourly temperature for the region and time from a weather archive, then a monthly climate default for the pack.
- Use a layer-mean rather than the surface value: sound travels down from the aircraft through cooler air. Starting rule: `T_eff = T_surface - 3 C` (about 1 km of standard lapse, halved). Tune later.
- Candidate archive: Open-Meteo's historical API or airport METAR archives. Neither was checked during planning; confirm terms and availability before depending on one.
- Until a clip's time is known, the temperature at 03:00 and 15:00 can differ by 10 to 15 C in the UAE. When the time window is wide, run the search at two temperatures (window start and end) and keep the better-scoring one, and say so in the result.
- Store `temperature_c` and `temperature_source` with the case and print both in the report.

Wind also shifts the curves (one replication reported a real improvement from modelling it). Not in the MVP; listed in risks.

## 5. Time

- Archives are per UTC day. The UAE is UTC+4 all year (Gulf Standard Time, no daylight saving).
- A local calendar day spans two UTC days: local 2026-11-14 00:00 to 24:00 is 2026-11-13 20:00 to 2026-11-14 20:00 UTC. A case dated 14 Nov therefore needs the 13 Nov and 14 Nov archives. Add one hour of margin on each side for flights in progress and propagation.
- Build the per-case index from the traces of every UTC day the window touches (`DayIndex.build` takes any list of traces; the same aircraft simply appears as two traces).
- The analyst's time-of-day input is a list of local ranges, to allow "night" (21:00 to 06:00 is two ranges on one date). Store `[["12:00","17:00"]]`; convert to unix ranges for the case date.
- A row satisfies the time constraint when its implied clip start `t_heard1 - ev1.t_cpa - shift`, plus the clip duration, overlaps a range.
- New York pack: America/New_York, with daylight saving. Use `zoneinfo`, never fixed offsets, in pack-generic code.

## 6. Region packs

A pack is a directory `data/packs/<id>/`:

```
pack.json       { "id": "uae", "name": "United Arab Emirates", "timezone": "Asia/Dubai",
                  "bbox": [22.6, 26.1, 51.5, 56.4], "terrain_zoom": 12,
                  "climate_c": {"01": 19, ..., "07": 36, ...},   # monthly mean, fallback only
                  "demo_case": null }
regions.geojson FeatureCollection; properties: id, name, parent (for sub-areas)
grid.json       dot-map cells for the UI: [[lat, lon, region_id], ...] at a fixed pitch
```

- **UAE pack (built 2026-11-22, `backend/app/packs/uae`).** Seven emirates from geoBoundaries gbOpen ARE ADM1 (boundary year 2017, release `9469f09`, simplified geometry), whose source is OpenStreetMap; Abu Dhabi's three regions from OSM relations 13249272, 13249273 and 13249274 via Nominatim, cut to the emirate outline (they cover 99.8% of it). All of it is OpenStreetMap data under the Open Database License 1.0: attribute "OpenStreetMap contributors". `scripts/build_uae_pack.py` rebuilds it and names the exact URLs. Checked against nine city centres and the Hatta exclave (`test_uae_places_fall_in_their_emirates`). Original guidance: The emirates have exclaves (Hatta belongs to Dubai; Sharjah and Ajman have several), so always use polygon tests, never bounding boxes. Abu Dhabi is most of the country's land; add three sub-areas (Abu Dhabi region, Al Ain region, Al Dhafra region) so a search area can be smaller than the whole emirate.
- **New York demo pack.** bbox `40.4 41.3 -74.4 -72.6`, one region (the box), demo case Oyster Bay 2026-09-08. This is the only place we can show a verified end-to-end result.
- The polygons in `design/dot_map_prototype.py` and in the mockups are rough hand-drawn placeholders. Do not ship them.

## 7. Reference recordings

| Recording | Where | Use |
|---|---|---|
| Oyster Bay, 1 hour, 2026-09-08 | youtu.be/4CxVxuMVkMc | New York demo pack; dopplertrack's opt-in test expects `rec.npz` and `traces_ny.npz` in the directory named by `DOPPLERTRACK_OYSTER_BAY` |
| Eagle cam, 12 hours, 2024-12-28 | youtu.be/zs2o5Rhlp5w | second validation if time allows |

The audio is not in the dopplertrack repo. Getting it means downloading from YouTube, which is the user's call; ask before doing it. Without it, the synthetic generator in the smoke test is the fallback for demos and tests.

A UAE ground-truth clip does not exist yet. Recording one near a training airfield (after the coverage probe shows where and when props fly) is the only way to validate the UAE pack.

## 8. Storage estimates

| Item | Size |
|---|---|
| One day streamed | about 4 GB of transfer, nothing stored |
| UAE traces for one day (`--keep-jets`) | 54 MB for 1,492 aircraft (*ran*, 2026-11-19); the jet-inclusive day index is 823 MB, so build search indexes from propeller traces only |
| One day's stream on the user's connection | 3.6 GB in 10 minutes at 6.1 MB/s (*ran*) |
| Continental US index for one day | 6.2 GB (not needed for the UAE) |
| Spectrogram for one hour of audio | 840 bins x 14,400 frames float32, 48 MB as stored (`S.npy`, uncompressed so it can be memory-mapped) |
| Decoded audio for one hour | 58 MB in memory (4 kHz float32), about twice that at peak; not stored |
| Terrain tiles, UAE at zoom 12 | a few hundred small PNGs |

## 9. Step 0: the coverage probe

```
mkdir -p data/flights/uae data/coverage
uv run dopplertrack fetch 2026-11-14 data/flights/uae/2026-11-14.npz \
    --bbox 22.6 26.1 51.5 56.4 --keep-jets --traces data/flights/uae/2026-11-14-traces.npz
uv run python scripts/coverage_report.py data/flights/uae/2026-11-14-traces.npz --out data/coverage/2026-11-14
```

**Create the output folders first.** `dopplertrack fetch` writes its files only after the whole day has streamed and does not create missing folders, so a wrong path costs the entire download (*checked in the source: `save_traces` and `DayIndex.save` call numpy's save with no `mkdir`*). The date is a UTC day. `flights.ensure_day` in our code must create the folder before it starts and should save the traces before building anything from them.

Run it for three or four recent days, one of them a weekend day (Saturday or Sunday in the UAE). Read `sites.csv`: propeller passes within 6 km and below 3,000 m per site, and pairs of passes 1 to 30 minutes apart. Decision rule:

- A site with dozens of passes and several pairs a day: the method can work there for long recordings.
- A handful of passes: only long recordings at the right hours stand a chance.
- None: say so in the product for that area.

The report counts one closest approach per continuous airborne segment, so an aircraft circling a site is undercounted. It is a floor, not a census.
