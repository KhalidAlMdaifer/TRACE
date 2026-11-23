"""The spectrogram on disk, as plain arrays.

`S.npy` is float32, 840 rows by four columns per second of audio (48 MB per hour), stored
uncompressed so it can be memory-mapped: a fit or a UI tile reads only its own columns."""
from __future__ import annotations

from pathlib import Path

import numpy as np

# dopplertrack is imported inside the functions that need it: the api process serves
# `matrix` from this module and must never load the library.

DB_MAX = 12.0            # the UI grid clips whitened dB to 0..DB_MAX
MIN_AVG_COLS = 8         # two seconds: the least time a displayed cell is averaged over


def build(x: np.ndarray, sr: int, case_dir):
    """Whitened 40 to 450 Hz spectrogram with the library's defaults, written as S.npy,
    t.npy, f.npy and burst.npy (the broadband-loud mask, which is relative to the whole
    recording's median and so cannot be computed on a slice later)."""
    from dopplertrack import audio, tracks
    from dopplertrack.audio import Spectrogram

    case_dir = Path(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)
    sp = audio.compute_spectrogram(x, sr)
    sp = Spectrogram(np.asarray(sp.t, np.float64), np.asarray(sp.f, np.float64), np.ascontiguousarray(sp.S, np.float32))
    np.save(case_dir / "S.npy", sp.S)
    np.save(case_dir / "t.npy", sp.t)
    np.save(case_dir / "f.npy", sp.f)
    np.save(case_dir / "burst.npy", tracks.burst_mask(sp))
    return sp


def exists(case_dir) -> bool:
    return all((Path(case_dir) / n).exists() for n in ("S.npy", "t.npy", "f.npy", "burst.npy"))


def _columns(t: np.ndarray, t0, t1) -> slice:
    a = 0 if t0 is None else int(np.searchsorted(t, t0, "left"))
    b = len(t) if t1 is None else int(np.searchsorted(t, t1, "right"))
    return slice(a, max(b, a))


def load(case_dir, t0: float | None = None, t1: float | None = None):
    """The spectrogram, or only the columns with t0 <= t <= t1 (absolute times are kept, as
    `Spectrogram.crop` does)."""
    from dopplertrack.audio import Spectrogram

    case_dir = Path(case_dir)
    t = np.load(case_dir / "t.npy")
    f = np.load(case_dir / "f.npy")
    if t0 is None and t1 is None:
        return Spectrogram(t, f, np.load(case_dir / "S.npy"))
    S = np.load(case_dir / "S.npy", mmap_mode="r")
    sl = _columns(t, t0, t1)
    return Spectrogram(t[sl], f, np.array(S[:, sl]))


def load_burst(case_dir) -> tuple[np.ndarray, np.ndarray]:
    """(mask, t) for the whole recording: what `events.fit` needs to fill `EventFit.burst`."""
    case_dir = Path(case_dir)
    return np.load(case_dir / "burst.npy"), np.load(case_dir / "t.npy")


def _pool(a: np.ndarray, n_out: int, axis: int, how: str) -> np.ndarray:
    """Reduce or stretch one axis to n_out cells: the mean or the maximum of each group when
    shrinking, the nearest cell when stretching."""
    n = a.shape[axis]
    if n == 0:
        shape = list(a.shape); shape[axis] = n_out
        return np.zeros(shape, a.dtype)
    if n >= n_out:
        edges = np.floor(np.linspace(0, n, n_out, endpoint=False)).astype(int)
        if how == "max":
            return np.maximum.reduceat(a, edges, axis=axis)
        counts = np.diff(np.r_[edges, n]).astype(np.float32)
        shape = [1] * a.ndim; shape[axis] = n_out
        return np.add.reduceat(a, edges, axis=axis, dtype=np.float32) / counts.reshape(shape)
    return np.take(a, np.floor(np.linspace(0, n, n_out, endpoint=False)).astype(int), axis=axis)


def matrix(case_dir, t0: float, t1: float, f_lo: float, f_hi: float, cols: int, rows: int) -> dict:
    """A small uint8 grid of one window for the UI: `rows` by `cols`, row 0 the lowest
    frequency, whitened dB clipped to 0..12 and scaled to 0..255. numpy only.

    Columns are averaged over time first, then rows take the maximum over frequency. A tone
    stays in one bin for the few seconds a cell spans, so the mean keeps it and flattens the
    noise; a plain maximum over the whole cell would lift the noise floor to two thirds of
    the scale at wide zoom. The maximum over frequency then keeps the thin ridge visible."""
    case_dir = Path(case_dir)
    cols, rows = max(1, min(int(cols), 4096)), max(1, min(int(rows), 1024))
    t = np.load(case_dir / "t.npy")
    f = np.load(case_dir / "f.npy")
    S = np.load(case_dir / "S.npy", mmap_mode="r")
    sl = _columns(t, t0, t1)
    fm = slice(int(np.searchsorted(f, f_lo, "left")), int(np.searchsorted(f, f_hi, "right")))
    win = np.asarray(S[fm, sl])
    # Zoomed in, a cell spans only a column or two and the mean no longer tames the noise.
    # Average over at least two seconds of time first, as a moving window, so the picture
    # keeps the same contrast at every zoom. A flyover's tone moves a few bins in that time,
    # which the maximum over frequency absorbs.
    n = win.shape[1]
    if 0 < n < cols * MIN_AVG_COLS and n > MIN_AVG_COLS:
        c = np.cumsum(np.pad(win, ((0, 0), (1, 0))), axis=1, dtype=np.float64)
        lo = np.clip(np.arange(n) - MIN_AVG_COLS // 2, 0, n)
        hi = np.clip(lo + MIN_AVG_COLS, 0, n)
        lo = np.maximum(hi - MIN_AVG_COLS, 0)
        win = ((c[:, hi] - c[:, lo]) / (hi - lo)).astype(np.float32)
    grid = _pool(_pool(win, cols, axis=1, how="mean"), rows, axis=0, how="max")
    out = np.clip(grid / DB_MAX, 0.0, 1.0) * 255.0
    return {"t0": float(t0), "t1": float(t1), "f_lo": float(f_lo), "f_hi": float(f_hi), "cols": cols, "rows": rows,
            "db_max": DB_MAX, "data": out.astype(np.uint8).tobytes()}


def duration_s(case_dir) -> float:
    t = np.load(Path(case_dir) / "t.npy", mmap_mode="r")
    return float(t[-1]) if len(t) else 0.0
