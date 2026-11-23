"""The synthetic case: invented flights over a point and the audio heard there.

Moved from scripts/smoke_dopplertrack.py (synth_case, add_decoys) and parameterised. It
lives in the app, not only in the tests, because the demo also needs a recording with a
known answer. Nothing here is real data."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

OBSERVER = (25.05, 55.25)                 # a point in Dubai; the frame origin and the truth
T0_UNIX = 1_794_650_000.0                 # 2026-11-14 09:53:20 UTC, 13:53:20 in Asia/Dubai
DATE_LOCAL = "2026-11-14"
UTC_DAY = "2026-11-14"
DURATION_S = 1800
SAMPLE_RATE = 4000

# Boxes an analyst would draw in the editor: about 100 s centred on each curve's bend, tall
# enough to enclose the curve over that time. (t_start, t_end, f_lo, f_hi), flights 1, 2, 3.
BEND_BOXES = [(258.0, 358.0, 92.0, 170.0), (1179.0, 1279.0, 104.0, 172.0), (717.0, 817.0, 79.0, 126.0)]
NARROW_BOX = (265.0, 355.0, 110.0, 140.0)  # snug on flight 1; too narrow for fit_event as given


def synth_case(c_true: float, n_flights: int = 3, seed: int = 1):
    """Up to three flights around the observer, and the audio heard there.

    Returns (traces, audio, sample_rate, truth). Flight 2 turns: two perfectly straight
    passes leave a mirror-image observer that scores the same. Flight 3 is a low pass
    between the other two in time."""
    from dopplertrack import doppler
    from dopplertrack.adsb import Trace
    from dopplertrack.geo import enu_to_lla, lla_to_enu

    lat0, lon0 = OBSERVER
    sr, T0, dur = SAMPLE_RATE, T0_UNIX, DURATION_S

    def trace(icao, t, enu, gs):
        lat, lon, alt = enu_to_lla(enu[:, 0], enu[:, 1], enu[:, 2], lat0, lon0)
        return Trace(icao, None, "SR22", "synthetic", t, lat, lon, alt, np.full_like(t, gs), np.zeros(len(t), bool))

    # flight 1: east-bound, 2.5 km north of the observer at 1500 m, CPA emitted at T0+300
    t1 = T0 + np.arange(0, 900, 5.0)
    e1 = np.stack([110.0 * (t1 - (T0 + 300)), np.full_like(t1, 2500.0), np.full_like(t1, 1500.0)], -1)
    # flight 2: north-bound with a gentle turn, about 3 km east at 1200 m, CPA near T0+1220
    t2 = T0 + np.arange(900, 1800, 5.0)
    tau = t2 - (T0 + 1220)
    e2 = np.stack([3000.0 + 0.1 * tau**2, 95.0 * tau, np.full_like(t2, 1200.0)], -1)
    # flight 3: a low pass to the south-west, 1.2 km away at 600 m, CPA near T0+760
    t3 = T0 + np.arange(500, 1050, 5.0)
    tau3 = t3 - (T0 + 760)
    e3 = np.stack([-900.0 + 60.0 * tau3, -800.0 - 45.0 * tau3 + 0.05 * tau3**2, np.full_like(t3, 600.0)], -1)
    flights = [("aaa001", t1, e1, 110.0, 120.0), ("aaa002", t2, e2, 95.0, 130.0), ("aaa003", t3, e3, 75.0, 98.0)][:n_flights]
    traces = [trace(i, t, e, v / 0.514444) for i, t, e, v, _ in flights]

    obs = np.zeros(3)
    tt = np.arange(0, dur, 1 / sr)
    x = 0.4 * np.random.default_rng(seed).standard_normal(len(tt)).astype(np.float32)
    truth = {"lat": lat0, "lon": lon0, "t0_unix": T0, "c_true": c_true, "events": []}
    for (icao, t, e, v, f0), tr in zip(flights, traces):
        # resample to 1 Hz in the same frame the index will use, exactly as the library does
        tq = np.arange(t[0], t[-1], 1.0)
        enu = lla_to_enu(np.interp(tq, t, tr.lat), np.interp(tq, t, tr.lon), np.interp(tq, t, tr.alt), lat0, lon0)
        to, ratio, r = doppler.curve_from_trajectory(tq, enu, obs, f0=1.0, c=c_true)
        finst = np.interp(tt + T0, to, ratio, left=np.nan, right=np.nan) * f0
        m = np.isfinite(finst)
        ph = 2 * np.pi * np.cumsum(np.nan_to_num(finst, nan=0.0)) / sr
        x[m] += 0.05 * np.sin(ph[m])
        k = int(np.argmin(r))
        truth["events"].append({"icao": icao, "f0": f0, "v": v, "d": float(r[k]), "t_cpa_heard_audio": float(to[k] - T0)})
    return traces, x, sr, truth


def add_decoys(traces, truth, n: int, seed: int = 7):
    """n wrong flight pairs for every pair of real flights: the pair's geometry rotated, moved
    30 to 150 km away and perturbed in speed, height and timing. They are not in the audio.
    Each is a hard wrong answer (a rotated copy predicts the same two curves), so together
    they give the verdict a realistic null whichever two flyovers the search pairs up. No
    decoy has a third flight, which is what lets a third flyover single out the truth.

    With two flights this is exactly the smoke script's add_decoys; a third flight adds
    decoys for the pairs (1, 3) and (2, 3), named e... and f..."""
    from itertools import combinations

    from dopplertrack.adsb import Trace
    from dopplertrack.geo import enu_to_lla, lla_to_enu

    lat0, lon0 = truth["lat"], truth["lon"]
    rng = np.random.default_rng(seed)
    real = traces[:3]
    out = []
    for prefix, pair in zip("def", combinations(range(len(real)), 2)):
        for k in range(n):
            th = rng.uniform(0, 2 * np.pi)
            rot = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
            dist, bearing = rng.uniform(30e3, 150e3), rng.uniform(0, 2 * np.pi)
            off = np.array([dist * np.sin(bearing), dist * np.cos(bearing)])
            tshift = rng.uniform(-150, 150)
            for j, i in enumerate(pair):
                tr = real[i]
                enu = lla_to_enu(tr.lat, tr.lon, tr.alt, lat0, lon0)
                sf = rng.uniform(0.88, 1.12)
                xy = enu[:, :2] @ rot.T
                ctr = xy.mean(0)
                xy = ctr + (xy - ctr) * sf + off
                lat, lon, alt = enu_to_lla(xy[:, 0], xy[:, 1], enu[:, 2] * rng.uniform(0.8, 1.25), lat0, lon0)
                lag = rng.uniform(-4, 4) if j == 1 else 0.0
                out.append(Trace(f"{prefix}{k:03d}{j}", None, "C172", "decoy", tr.t + tshift + lag, lat, lon, alt, tr.gs * sf, np.zeros(len(tr.t), bool)))
    return out


def write_wav(x: np.ndarray, sr: int, path) -> Path:
    """16-bit mono WAV. The audio is scaled down first so the noise does not clip; the
    spectrogram is whitened per bin, so the scale does not matter."""
    path = Path(path)
    pcm = np.clip(x * 0.2, -1.0, 1.0)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((pcm * 32767).astype("<i2").tobytes())
    return path


class SyntheticTypes:
    """Stand-in for dopplertrack's AircraftTypes that needs no download: the synthetic
    traces use two piston designators."""
    types = {"SR22": {"EngineType": "Piston"}, "C172": {"EngineType": "Piston"}, "A320": {"EngineType": "Jet"}}

    def is_prop(self, designator, unknown_ok=True):
        row = self.types.get(designator or "")
        return unknown_ok if row is None else row["EngineType"] != "Jet"


def write_case(out_dir, temp_c: float = 28.0, n_flights: int = 3, decoys: int = 25) -> dict:
    """Write a complete synthetic case into out_dir: the recording, the analyst's boxes and
    the flight day for the built-in `test` pack. Returns paths and the truth."""
    from dopplertrack.adsb import save_traces
    from dopplertrack.doppler import speed_of_sound

    out_dir = Path(out_dir)
    traces, x, sr, truth = synth_case(float(speed_of_sound(temp_c)), n_flights)
    if decoys:
        traces = traces + add_decoys(traces, truth, decoys)
    out_dir.mkdir(parents=True, exist_ok=True)
    wav = write_wav(x, sr, out_dir / "synthetic.wav")
    fdir = out_dir / "flights" / "test"
    fdir.mkdir(parents=True, exist_ok=True)
    save_traces(traces, fdir / f"{UTC_DAY}-traces.npz")
    boxes = [{"t_start": b[0], "t_end": b[1], "f_lo": b[2], "f_hi": b[3], "harmonics": 1} for b in BEND_BOXES[:n_flights]]
    import json
    (out_dir / "events.json").write_text(json.dumps(boxes, indent=1))
    return {"wav": wav, "events": out_dir / "events.json", "data_dir": out_dir, "truth": truth, "temp_c": temp_c}
