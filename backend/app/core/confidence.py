"""How a search result becomes a state, a band and a number (docs/06-confidence.md).

dopplertrack's verdict is the core; these are the rules around it. The number is a match
strength mapped from the tested verdict, not a calibrated probability of being right."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

BURST_FLAG = 0.15
DROPPED_PCT_CAP = 20.0
ORDER = ["None", "Low", "Medium", "High"]
SUBLABELS = {"ambiguous": "unconfirmed", "no match": "weak", "insufficient": "too_few_flights", "located": "needs_third_flyover"}


@dataclass
class Assessment:
    state: str                       # located | candidates | outside | not_locatable
    band: str                        # High | Medium | Low | None
    sublabel: str | None = None      # for candidates: unconfirmed | weak | too_few_flights | needs_third_flyover
    strength: int | None = None      # 0..100 from the verdict's p; None when there is no p
    reason: str | None = None        # for not_locatable
    top: int | None = None           # row of the best pair overall
    top_in: int | None = None        # row of the best pair inside the stated area and time
    outside_confirmed: bool = False  # the outside match passes the located test on its own
    caps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def strength(p) -> int | None:
    """round(100 * clamp(-log10(p) / 3, 0, 1)): p 0.001 or smaller is 100, 0.01 is 67, 0.1 is 33."""
    if p is None or p != p:
        return None
    if p <= 0:
        return 100
    return round(100 * min(max(-math.log10(p) / 3, 0.0), 1.0))


def _cap(band: str, at: str) -> str:
    return band if ORDER.index(band) <= ORDER.index(at) else at


def assess(pairs, verdict, n_confirmed: int, bursts=(), rows_dropped_pct: float | None = None,
           cut_suspected: bool = False, reason: str | None = None, temperature_disagree: bool = False,
           placebo_beaten: int | None = None) -> Assessment:
    """pairs: one row per flight pair, best first, with `in_area`, `in_time` and `n_events`
    (the pair plus the extra flyovers that matched a flight at its best point).
    verdict: dopplertrack's Verdict for the whole table. n_confirmed: flyovers the analyst
    confirmed. bursts: the burst share of each confirmed flyover."""
    if n_confirmed < 2:
        return Assessment("not_locatable", "None", reason="fewer_than_two_flyovers")
    if reason:
        return Assessment("not_locatable", "None", reason=reason)
    if pairs is None or not len(pairs):
        return Assessment("not_locatable", "None", reason="no_candidates")

    inside = [i for i in range(len(pairs)) if bool(pairs.in_area.iloc[i]) and bool(pairs.in_time.iloc[i])]
    top, top_in = 0, (inside[0] if inside else None)
    label = verdict.verdict if verdict is not None else "insufficient"
    p = None if verdict is None or label == "insufficient" else float(verdict.p)
    located = label == "located" and int(pairs.n_events.iloc[top]) >= 3

    a = Assessment("candidates", "Low", strength=strength(p), top=top, top_in=top_in)
    if top_in != top:
        a.state, a.outside_confirmed = "outside", located
    elif located:
        a.state = "located"
        a.band = "High" if p <= 0.01 else "Medium"
    else:
        a.sublabel = SUBLABELS[label]

    # caps, applied after the rule above
    if any(b is not None and b > BURST_FLAG for b in bursts):
        a.caps.append("burst: a confirmed flyover sits in a broadband-loud stretch, possibly a vehicle")
        a.band = _cap(a.band, "Medium")
    if rows_dropped_pct is not None and rows_dropped_pct > DROPPED_PCT_CAP:
        a.caps.append(f"integrity: {rows_dropped_pct:.0f}% of track points that day failed integrity checks")
        a.band = _cap(a.band, "Medium")
    if temperature_disagree:
        a.caps.append("temperature: the search was run at the coolest and warmest hours of the time window, and they point to different flights")
        a.band = _cap(a.band, "Medium")
    if placebo_beaten:
        # the control: a day that cannot hold the answer scored as well as this one did
        a.caps.append(f"placebo: {placebo_beaten} other day{'s' if placebo_beaten != 1 else ''} with no possible match scored at least as high")
        a.band = _cap(a.band, "Medium")
    if cut_suspected:
        a.caps.append("cut: the recording may be cut between the flyovers used")
        a.band = _cap(a.band, "Low")
    return a
