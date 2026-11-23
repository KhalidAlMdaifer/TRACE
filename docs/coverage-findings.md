# UAE coverage findings (M0 probe)

**One day only so far.** The user approved one day first (2026-11-21); the plan asks for
three or four including a weekend day. Treat everything here as one Thursday's picture.

## What was run

```
uv run dopplertrack fetch 2026-11-19 data/flights/uae/2026-11-19.npz \
    --bbox 22.6 26.1 51.5 56.4 --keep-jets --traces data/flights/uae/2026-11-19-traces.npz
uv run python scripts/coverage_report.py data/flights/uae/2026-11-19-traces.npz --out data/coverage/2026-11-19
```

- UTC day 2026-11-19 (a Thursday): 04:00 Thursday to 04:00 Friday local time.
- Stream: 3.6 GB in two parts, 598 s at 6.1 MB/s on the user's connection (10 min 17 s in all).
- Kept: 1,492 aircraft touching the box. Traces file 54 MB; the day index with jets is 823 MB (14,161 segments, 19.8 million 1 Hz points). A propeller-only index will be a small fraction of that.
- Report: 13 s. Counting rule: closest approach within 6 km slant and below 3,000 m, one per continuous airborne segment, so a circling aircraft is undercounted. A floor, not a census.
- Outputs kept in git: `docs/coverage/2026-11-19-*.csv` and `docs/coverage/2026-11-19-map.png`. The full set is under `data/coverage/` (not in git).

## Traffic in the box that day

| Class | Aircraft airborne | Below 3,000 m |
|---|---|---|
| Propeller class (piston, turboprop, turboshaft) | 71 | 70 |
| of which helicopters | 22 | |
| Jet | 1,226 | 988 |
| Unknown type (97 with no designator at all) | 103 | 80 |

Fixed-wing propeller aircraft: about 49. Main types: SR22 (15 aircraft), PC-21 (13), DA40 (7),
DA42 (3), DH8D (3), then singles (BE9L, DHC6, AT76, P180, C130, C172, C208, AP32).
Helicopters: A139 (8), B505 (6), A189 (4), EC30 (2), AS50, A169.

`dopplertrack`'s own propeller filter keeps unknown types, so those 103 would enter a search
as possible propeller aircraft unless we drop them. Decide in M1. What they really are was
not checked.

## Where a recorder could have heard propeller passes

Default sites (approximate city centres):

| Site | Prop passes | Pairs 1 to 30 min apart | Aircraft | Types | Verdict |
|---|---|---|---|---|---|
| Dubai South | 50 | 44 | 14 | SR22 x42, DA42 x8 | **workable**: fixed-wing piston training traffic all day |
| Dubai city | 33 | 29 | 6 | EC30 x15, AS50 x15, A139 x2, AP32 x1 | **helicopters only** (tour flights); not the propeller tones the method is validated on |
| Abu Dhabi city | 17 | 8 | 5 | DH8D x13, P180 x2, A189 x2 | marginal: a handful of turboprop airliner passes, long recordings only |
| Sharjah | 4 | 1 | 2 | A169 x3, AP32 x1 | almost nothing |
| Ajman | 3 | 0 | 2 | A169 x2, DH8D x1 | almost nothing |
| Fujairah | 2 | 1 | 1 | P180 x2 | almost nothing |
| Umm Al Quwain | 1 | 0 | 1 | DH8D | nothing usable |
| Al Ain (city centre) | 0 | 0 | 0 | | nothing at the centre; see the airport below |
| Ras Al Khaimah (city centre) | 0 | 0 | 0 | | nothing |

Extra sites at airfields and where the map shows dense tracks:

| Site | Prop passes | Pairs | Aircraft | Types |
|---|---|---|---|---|
| Training area south of Dubai South (24.70, 55.30) | 42 | 32 | 17 | SR22 x37, DA42 x5 |
| Between Abu Dhabi and Al Ain (24.35, 55.55) | 32 | 19 | 16 | PC-21 x21, SR22 x6, B505 x5 |
| Al Ain airport (24.26, 55.61) | 25 | 15 | 13 | PC-21 x19, SR22 x6 |
| RAK airport (25.61, 55.94) | 4 | 2 | 2 | SR22 x4 |
| Al Bateen airport, Abu Dhabi (24.43, 54.46) | 2 | 0 | 1 | P180 x2 |

Densest 0.1 degree cells (distinct propeller aircraft below 3,000 m): the block from
24.6 to 24.8 N, 55.0 to 55.4 E (17 to 19 aircraft each), and 24.3 N 55.5 E (18).

## When

Propeller aircraft below 3,000 m, by local hour: none from midnight to 06:00, 14 at 07:00,
then 27 to 42 per hour from 08:00 to 14:00, tapering to 5 or fewer after 19:00. Jets fly
around the clock (70 to 126 per hour). **A night recording has essentially no propeller
traffic to match.**

## What this means

1. **The answer is not "almost nowhere", but it is narrow.** One corridor carries the usable
   traffic: Al Maktoum (Dubai South) and the desert training area south-east of it, running
   down towards Al Ain airport. There, a recorder would have had 25 to 50 fixed-wing
   propeller passes and 15 to 44 usable pairs in the day, between 08:00 and 18:00.
2. **Most populated places are poor.** Sharjah, Ajman, Umm Al Quwain, Ras Al Khaimah and
   Fujairah had zero to four passes. Abu Dhabi city had 13 Dash 8 passes. A typical urban
   UAE clip will end as "not locatable", as risk 1 predicted.
3. **Dubai city is a trap.** Its 33 passes are almost all tour helicopters. They pass the
   propeller filter (risk 16) but rotor tones and helicopter speeds are outside what the
   method and `detect` were validated on. Count helicopters separately in the UI and do not
   promise anything for them.
4. **Al Ain's traffic is military trainers (PC-21).** They are in the public archive this
   day, which is worth knowing. If their paths are less straight than a transport's (not
   checked), that helps uniqueness and hurts the straight-pass fit.
5. **The verdict will be short of wrong pairs.** With about 49 fixed-wing propeller aircraft
   in the whole pack, the null distribution is thin (risk 14). Expect `insufficient` often
   unless the search runs over the whole pack with helicopters and unknowns included.

## Track integrity, measured on a second day (M5, 2026-11-22)

UTC day 2026-11-18, fetched through the app's own fetch job with the integrity filter
(`core/integrity.py`): 12 minutes, 1,527 aircraft touched the box, 1,414 kept, 175 of them
propeller-class or of unknown type.

| | Track points | Share |
|---|---|---|
| Positioned rows of those aircraft | 2,531,742 | |
| Dropped: position not from ADS-B (multilateration, TIS-B and the like) | 84,349 | 3.3% |
| Dropped: position flagged stale | 116,339 | 4.6% |
| Dropped: low accuracy (`nac_p` under 8, or containment radius over 200 m) | 81,548 | 3.2% |
| Dropped: impossible jump | 8,031 | 0.3% |
| **Dropped in all** | **290,267** | **11.5%** |

So about one track point in nine fails a check on an ordinary day, under the 20% that caps
the band. This is all aircraft, jets included; the share for propeller aircraft alone was not
split out. 113 aircraft lost every row. Whether any of it is jamming or spoofing, rather than
ordinary receiver gaps, was not examined.

A search of both days (local 19 November) saw 428 propeller-class flights in the pack.

## Places to record a first UAE test (2026-11-23)

Counted for the owner's planned field recording, from the two days on disk (UTC 18 and 19
November 2026, a Wednesday and a Thursday), with
`scripts/coverage_report.py --site NAME LAT LON --radius 2500`: fixed-wing propeller passes
within 2.5 km, per day.

| Place | 18 Nov | 19 Nov | Busiest local hours |
|---|---|---|---|
| 24.84 N, 55.19 E, desert north-west of Bab Al Shams | 63 | 62 | 08:00 to 13:00, then 14:00 to 16:00 |
| 24.816 N, 55.230 E, the Bab Al Shams end of Al Qudra Road | 43 | 31 | 08:00 to 13:00 |
| 24.8123 N, 55.1101 E, a spot the owner picked | 40 | 38 | 12:00 to 16:00 |
| 24.78 N, 55.17 E | 18 | 23 | |
| Al Qudra Lakes (24.835, 55.375), Love Lake, Expo City, Dubai Parks, Dubai Investment Park | 0 | 0 | |
| Al Maktoum airport itself (24.896, 55.161) | 0 | 1 | within 6 km it has 51 to 59: the traffic passes wide of it |

Nearly all are SR22s, with a few DA42s. The hot spot is small: three kilometres east of the
owner's spot the count falls to 11 to 13. The place names were put to the coordinates from
memory and what is on the ground there was not checked; weekends were not counted.

## Not answered by this probe

- **Integrity by cause.** The share of points failing checks is now measured (above), but not
  why they fail, nor for propeller aircraft alone.
- **Weekend against weekday**, and day-to-day variation. One Thursday only.
- **Whether the passes are audible in practice.** The report is geometry; no UAE recording
  with a known position exists yet (open question 6).

## Corrections this run made to the plan

- `04-data.md` expected "megabytes" for a UAE day's traces with jets: it is 54 MB, and the
  jet-inclusive index is 823 MB. Build search indexes from propeller traces only.
- The stream ran at 6.1 MB/s here, so a day costs about 10 minutes, not 2.5.
