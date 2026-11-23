"""Flyovers: proposals from automatic detection, and fits of the boxes an analyst draws.

The rules here come from measurements (docs/02-dopplertrack.md, behaviours 2 and 11 to 15):
detection only proposes; the analyst's box is what gets fitted; a box is widened before the
library sees it; the editor draws a quick preview and the search refits in full."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from dopplertrack import doppler, tracks
from dopplertrack.audio import Spectrogram
from dopplertrack.tracks import EventFit

# fit_event searches the fundamental on [1.15 * f_lo, 0.85 * f_hi) in 1 Hz steps, so a band
# with f_hi <= 1.353 * f_lo has an empty grid and raises. Widening the analyst's box by the
# same factors makes that grid span exactly the box.
F0_TRIM_LO, F0_TRIM_HI = 1.15, 0.85
MIN_BOX_S, MIN_BOX_HZ = 20.0, 2.0
PRESETS = {
    "fast": dict(refine=False, f0_step=3.0, t0_step=3.0, n_curve=60, min_sep_s=30.0, top=8),
    "full": dict(refine=False, top=8),
}
MERGE_S = 30.0           # two proposals this close are one flyover: keep the stronger
BURST_FLAG = 0.15        # share of the surrounding three minutes that is broadband-loud


class BoxTooSmall(ValueError):
    code = "box_too_small"

    def __init__(self):
        super().__init__(f"box too small: need at least {MIN_BOX_HZ:.0f} Hz and {MIN_BOX_S:.0f} s inside the recording")


class FitFailed(ValueError):
    code = "fit_failed"


def effective_harmonics(sp: Spectrogram, box_hi: float, harmonics: int) -> int:
    """Harmonics past the top of the grid count as zero and drag the score down, so cap the
    count at floor(450 / box_hi)."""
    top = float(sp.f[-1])
    return max(1, min(int(harmonics or 1), int(top // max(float(box_hi), 1.0))))


def _band(sp: Spectrogram, t_start: float, t_end: float, box_lo: float, box_hi: float, harmonics: int):
    """Clip the box to the grid, check its size, and widen it for the library."""
    if not len(sp.t):
        raise BoxTooSmall()
    lo, hi = max(float(box_lo), float(sp.f[0])), min(float(box_hi), float(sp.f[-1]))
    t0, t1 = max(float(t_start), float(sp.t[0])), min(float(t_end), float(sp.t[-1]))
    if hi - lo < MIN_BOX_HZ or t1 - t0 < MIN_BOX_S:
        raise BoxTooSmall()
    return t0, t1, lo / F0_TRIM_LO, hi / F0_TRIM_HI, effective_harmonics(sp, hi, harmonics)


def _finish(ev: EventFit, burst) -> EventFit:
    """fit_event leaves `burst` at 0.0; fill it from the whole recording's mask."""
    if burst is not None:
        mask, t = burst
        ev.burst = tracks.burst_fraction(mask, t, ev.t_cpa)
    return ev


def fit(sp: Spectrogram, t_start: float, t_end: float, box_lo: float, box_hi: float, harmonics: int, c: float,
        burst=None) -> EventFit:
    """The full fit of an analyst's box (seconds, Hz): what the search uses. 5 to 19 s.
    `burst` is `spectro.load_burst(case_dir)`; `sp` may be a slice around the box."""
    t0, t1, f_lo, f_hi, h = _band(sp, t_start, t_end, box_lo, box_hi, harmonics)
    try:
        ev = tracks.fit_event(sp, t0, t1, f_lo, f_hi, c=c, harmonics=h, objective="brightness")
    except ValueError as e:
        raise FitFailed(str(e)) from e
    return _finish(ev, burst)


# fit_event lays its fundamental grid in 1 Hz steps from the bottom of the box and scores
# plain brightness on it. On a narrow tone the winner of that grid can change with where the
# grid happens to fall: measured on the synthetic turning flyover, moving a box by a third of
# a hertz gave scores of 8.2, 9.1 and 13.5, and only the last was the true curve. So the fit
# the search uses is run at three grid phases and the brightest wins.
PHASES_HZ = (0.0, 1.0 / 3.0, 2.0 / 3.0)
_POOL: dict = {}


def _phase_fit(job):
    """One box at one grid phase. Runs in a forked worker, which sees the spectrogram through `_POOL`."""
    i, t0, t1, lo, hi, harmonics, c, df = job
    try:
        return i, fit(_POOL["sp"], t0, t1, lo + df, hi + df, harmonics, c), None
    except ValueError as e:
        return i, None, str(e)


def fit_many(sp: Spectrogram, boxes: list[tuple[float, float, float, float, int]], c: float, burst=None, workers: int = 1,
             phases=PHASES_HZ, on_done=None) -> list[EventFit]:
    """The search's fit of every confirmed box (t_start, t_end, box_lo, box_hi, harmonics): the
    full fit at each grid phase, the best score kept. With workers > 1 on Linux the fits run
    side by side in forked processes; elsewhere one after another. on_done(n_done, n_boxes)."""
    import multiprocessing
    import sys

    for b in boxes:                                 # a box that is too small is refused before any work
        _band(sp, *b)
    jobs = [(i, b[0], b[1], b[2], b[3], b[4], c, df) for i, b in enumerate(boxes) for df in phases]
    best: list[EventFit | None] = [None] * len(boxes)
    errors: list[str | None] = [None] * len(boxes)
    left = [len(phases)] * len(boxes)
    done = 0

    def take(result):
        nonlocal done
        i, ev, err = result
        if ev is not None and (best[i] is None or ev.score > best[i].score):
            best[i] = ev
        errors[i] = err or errors[i]
        left[i] -= 1
        if left[i] == 0:
            done += 1
            if on_done:
                on_done(done, len(boxes))

    _POOL["sp"] = sp
    try:
        if workers > 1 and len(jobs) > 1 and sys.platform.startswith("linux"):
            with multiprocessing.get_context("fork").Pool(min(workers, len(jobs))) as pool:
                for result in pool.imap_unordered(_phase_fit, jobs):
                    take(result)
        else:
            for job in jobs:
                take(_phase_fit(job))
    finally:
        _POOL.clear()
    out = []
    for i, (b, ev) in enumerate(zip(boxes, best)):
        if ev is None:
            raise FitFailed(errors[i] or "no curve found in the box")
        ev.t_start, ev.t_end = max(float(b[0]), float(sp.t[0])), min(float(b[1]), float(sp.t[-1]))
        out.append(_finish(ev, burst))
    return out


def preview(sp: Spectrogram, t_start: float, t_end: float, box_lo: float, box_hi: float, harmonics: int, c: float,
            burst=None, phase_hz: float = 0.0) -> EventFit:
    """A quick fit for the editor overlay: a coarse grid search (3 Hz, 3 s), then fit_event's
    own fine search and polish around that seed. About 2 s. It usually lands on the full
    fit's answer but can settle on a weaker one nearby, so it is drawn, never searched.
    `phase_hz` moves the fundamental grid (see PHASES_HZ): the editor asks for all three
    phases side by side and draws the brightest."""
    _band(sp, t_start, t_end, box_lo, box_hi, harmonics)          # the size check is on the box as drawn
    t0, t1, f_lo, f_hi, h = _band(sp, t_start, t_end, box_lo + phase_hz, box_hi + phase_hz, harmonics)
    try:
        pad = 0.3 * (f_hi - f_lo)                  # the same crop and whitening fit_event applies
        win = tracks.local_whiten(sp.crop(t0 - 30, t1 + 30, max(f_lo - pad, sp.f[0]), min(f_hi * h + pad, sp.f[-1])))
        _, seed = tracks.grid_search(win, t0, t1, f_lo, f_hi, c, h, f0_step=3.0, t0_step=3.0, n_curve=60,
                                     objective="brightness")
        ev = tracks.fit_event(sp, t0, t1, f_lo, f_hi, c=c, harmonics=h, init=seed, objective="brightness")
    except ValueError as e:
        raise FitFailed(str(e)) from e
    return _finish(ev, burst)


def preview_from_disk(case_dir, t_start: float, t_end: float, box_lo: float, box_hi: float, harmonics: int, c: float,
                      phase_hz: float = 0.0) -> dict:
    """The editor's request, self-contained so it can run in the fit pool: read only the
    columns around the box, fit, and return plain data."""
    from . import spectro

    sp = spectro.load(case_dir, t_start - 60.0, t_end + 60.0)
    ev = preview(sp, t_start, t_end, box_lo, box_hi, harmonics, c, burst=spectro.load_burst(case_dir), phase_hz=phase_hz)
    return {"fit": ev.to_dict(), "burst": ev.burst, "harmonics": effective_harmonics(sp, min(box_hi, float(sp.f[-1])), harmonics),
            "curve": curve_points(ev, c)}


def curve_points(ev: EventFit, c: float, n: int = 200, t0: float | None = None, t1: float | None = None) -> list[tuple[float, float]]:
    """(audio time, Hz) along the fitted ideal curve, for the overlay. `ideal_curve` takes
    the emission time of closest approach."""
    t = np.linspace(ev.t_start if t0 is None else t0, ev.t_end if t1 is None else t1, n)
    f = doppler.ideal_curve(t, ev.f0, ev.v, ev.d, ev.t_cpa_emit, c=c)
    ok = np.isfinite(f)
    return [(round(float(a), 2), round(float(b), 2)) for a, b in zip(t[ok], f[ok])]


def proposal_box(ev: EventFit, c: float, sp: Spectrogram, half_s: float = 50.0) -> tuple[float, float, float, float]:
    """The box a proposal is shown with: about 100 s centred on the bend, tall enough to
    hold the ideal curve over that time plus 5%, clipped to the grid and to the recording."""
    t0, t1 = ev.t_cpa - half_s, ev.t_cpa + half_s
    if len(sp.t):                                # a flyover near either end: keep the box inside the recording
        t0, t1 = max(t0, float(sp.t[0])), min(t1, float(sp.t[-1]))
    f = np.array([p[1] for p in curve_points(ev, c, 100, t0, t1)] or [ev.f0])
    lo, hi = float(f.min()) * 0.95, float(f.max()) * 1.05
    return t0, t1, max(lo, float(sp.f[0])), min(hi, float(sp.f[-1]))


def slices(total_s: float, slice_s: float = 600.0, overlap_s: float = 120.0) -> list[tuple[float, float]]:
    """Consecutive windows that overlap, covering 0..total_s."""
    out, a, step = [], 0.0, slice_s - overlap_s
    while True:
        b = min(a + slice_s, total_s)
        out.append((a, b))
        if b >= total_s:
            return out
        a += step


def merge_proposals(found: list[EventFit], new: list[EventFit]) -> tuple[list[EventFit], list[EventFit], list[EventFit]]:
    """Fold a slice's proposals into what is already found. Returns (all, added, removed):
    within MERGE_S of each other the higher score wins."""
    out, added, removed = list(found), [], []
    for ev in sorted(new, key=lambda e: -e.score):
        near = [o for o in out if abs(o.t_cpa - ev.t_cpa) < MERGE_S]
        if any(o.score >= ev.score for o in near):
            continue
        for o in near:
            out[:] = [x for x in out if x is not o]
            if any(o is x for x in added):
                added[:] = [x for x in added if x is not o]     # proposed and replaced in the same slice: never shown
            else:
                removed.append(o)
        out.append(ev)
        added.append(ev)
    return sorted(out, key=lambda e: -e.score), added, removed


def propose(sp: Spectrogram, c: float, band: tuple[float, float] = (60.0, 300.0), preset: str = "fast", workers: int = 1,
            slice_s: float = 600.0, overlap_s: float = 120.0, on_slice=None, burst=None) -> list[EventFit]:
    """Automatic detection in slices, so proposals can be shown as they come. They are hints
    for where the analyst should look, nothing more: never searched, never auto-confirmed.
    on_slice(done_s, total_s, added, removed) is called once per slice."""
    opts = PRESETS[preset]
    total = float(sp.t[-1]) if len(sp.t) else 0.0
    found: list[EventFit] = []
    for a, b in slices(total, slice_s, overlap_s):
        part = sp.crop(a, b)
        new = tracks.detect_events(part, band[0], band[1], c=c, workers=workers, **opts) if len(part.t) > 8 else []
        for ev in new:
            _finish(ev, burst)
        found, added, removed = merge_proposals(found, new)
        if on_slice:
            on_slice(b, total, added, removed)
    return found


@dataclass
class FittedEvent:
    """A confirmed box with the full fit the search made of it."""
    box_id: str
    box: tuple[float, float, float, float]
    harmonics: int
    fit: EventFit

    @property
    def score(self) -> float:
        return self.fit.score

    @property
    def t_cpa(self) -> float:
        return self.fit.t_cpa


def pick_pair(events: list) -> tuple:
    """The two best by fit score, the earlier one first; the rest are extras, best first.
    Works on anything with `.score` and `.t_cpa`."""
    ranked = sorted(events, key=lambda e: -e.score)
    a, b = sorted(ranked[:2], key=lambda e: e.t_cpa)
    return a, b, ranked[2:]
