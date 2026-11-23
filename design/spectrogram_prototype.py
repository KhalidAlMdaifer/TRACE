"""How the sample spectrogram in design/mockups/Flyovers.dc.html was generated.

Reference only. It prints the SVG path data for a dot-matrix spectrogram of an invented
recording: three flyovers as ideal Doppler curves (the same emission-time formula as
docs/03-method-and-evidence.md), a vehicle passing as a broadband burst, random speckle,
and the boxes, fitted lines and overview marks drawn over them. Each dot is a 5 px stroke
segment; whole rows are one line with a dash pattern, the same trick as the dot map.

The app does not use this. It draws its spectrogram on a canvas from the grid that
GET /api/cases/{id}/spectrogram returns (docs/05-architecture.md).

    python design/spectrogram_prototype.py
"""
import math, random
random.seed(11)
C = 348.0
X0, COLS, PITCH, DOT = 70, 90, 10, 5
Y0, ROWS = 70, 44
T0, T1 = 180.0, 1380.0            # visible time range, s
FHI, FLO = 240.0, 60.0
spc = (T1 - T0) / COLS             # seconds per column
hz = (FHI - FLO) / (ROWS - 1)
def col_of(t): return (t - T0) / spc
def x_of(t): return X0 + col_of(t) * PITCH
def row_of(f): return (FHI - f) / hz
def y_of(f): return Y0 + row_of(f) * PITCH
def curve(f0, v, d, t_cpa):
    te0 = t_cpa - d / C
    pts = []
    for i in range(-6000, 6001):
        te = i * 0.1
        x = v * te; r = math.hypot(x, d); vr = v * x / r
        pts.append((te0 + te + r / C, f0 * C / (C + vr)))
    return pts
def f_at(pts, t):
    lo, hi = 0, len(pts) - 1
    if t <= pts[0][0] or t >= pts[-1][0]: return None
    while hi - lo > 1:
        m = (lo + hi) // 2
        if pts[m][0] <= t: lo = m
        else: hi = m
    (ta, fa), (tb, fb) = pts[lo], pts[hi]
    return fa + (fb - fa) * (t - ta) / (tb - ta)
FLY = [(113.0, 62.0, 640.0, 308.0), (98.0, 71.0, 910.0, 767.0), (132.0, 58.0, 780.0, 1229.0)]
cur = [curve(*f) for f in FLY]
dot = lambda c, r: f"M{X0 + c * PITCH} {Y0 + r * PITCH}h{DOT}"
used = set(); bright, dim = [], []
for pts, (f0, v, d, tc) in zip(cur, FLY):
    for c in range(COLS):
        t = T0 + (c + 0.5) * spc
        if abs(t - tc) > 250: continue
        f = f_at(pts, t)
        if f is None: continue
        r = round(row_of(f))
        if not (0 <= r < ROWS): continue
        if abs(t - tc) > 60 and random.random() < 0.28: continue      # tails fade in and out
        (bright if abs(t - tc) <= 60 else dim).append(dot(c, r)); used.add((c, r))
burst = []
for c in range(54, 58):
    for r in range(14, ROWS):
        if random.random() < (0.62 if c in (55, 56) else 0.35) and (c, r) not in used:
            burst.append(dot(c, r)); used.add((c, r))
veh = []                                      # a vehicle's engine tone sweeping through the burst
for c in range(51, 61):
    r = round(30 + (c - 51) * 0.9)
    if (c, r) not in used: veh.append(dot(c, r)); used.add((c, r))
noise = []
while len(noise) < 70:
    c, r = random.randrange(COLS), random.randrange(ROWS)
    if (c, r) in used: continue
    noise.append(dot(c, r)); used.add((c, r))
rows = "".join(f"M{X0} {Y0 + r * PITCH}H{X0 + COLS * PITCH}" for r in range(ROWS))
hum = "".join(f"M{X0} {Y0 + round(row_of(f)) * PITCH}H{X0 + COLS * PITCH}" for f in (100, 150, 200))
def box(tc, pts, half=50.0, pad=0.05):
    fs = [f_at(pts, tc + k) for k in range(-int(half), int(half) + 1)]
    lo, hi = min(fs) * (1 - pad), max(fs) * (1 + pad)
    x = x_of(tc - half); w = x_of(tc + half) - x
    y = y_of(hi); h = y_of(lo) - y
    return round(x, 1), round(y, 1), round(w, 1), round(h, 1), lo, hi
def line(pts, tc, half=50.0, step=4.0):
    out = []
    k = -half
    while k <= half + 1e-9:
        f = f_at(pts, tc + k); out.append(f"{x_of(tc + k):.1f},{y_of(f) :.1f}"); k += step
    return " ".join(out)
print("ROWS", rows); print("HUM", hum)
print("NOISE", "".join(noise)); print("DIM", "".join(dim)); print("BRIGHT", "".join(bright))
print("BURST", "".join(burst)); print("VEH", "".join(veh))
for i, (pts, f) in enumerate(zip(cur, FLY), 1):
    b = box(f[3], pts)
    print(f"BOX{i} x={b[0]} y={b[1]} w={b[2]} h={b[3]}  band {b[4]:.0f}-{b[5]:.0f} Hz  asym {f[0]*C/(C+f[1]):.1f}-{f[0]*C/(C-f[1]):.1f}")
    print(f"LINE{i}", line(pts, f[3]))
# suggestions: on flyover 3's approach tone and flyover 1's departure tone
for name, i, tc in (("SUG_A", 2, 1095.0), ("SUG_B", 0, 450.0)):
    pts = cur[i]; f = f_at(pts, tc)
    x = x_of(tc - 50); w = x_of(tc + 50) - x
    print(name, f"x={x:.1f} y={y_of(f + 14):.1f} w={w:.1f} h={y_of(f - 14) - y_of(f + 14):.1f}", "line", f"{x + 4:.1f},{y_of(f_at(pts, tc - 45)) + 2.5:.1f} {x + w - 4:.1f},{y_of(f_at(pts, tc + 45)) + 2.5:.1f}")
print("VEHBOX", f"x={x_of(930 - 50):.1f} w={x_of(980) - x_of(880):.1f}")
print("TICKS", [(lab, round(x_of(s), 1)) for lab, s in (("04:00", 240), ("08:00", 480), ("12:00", 720), ("16:00", 960), ("20:00", 1200))])
print("FTICKS", [(f, round(y_of(f) + 2.5 + 4, 1)) for f in (240, 200, 150, 100, 60)])
OV = 900 / 1930.0
print("OVERVIEW marks", [round(70 + t * OV, 1) for t in (308, 767, 1229)], "window", round(70 + 180 * OV, 1), round(70 + 1380 * OV, 1), "scanned to", round(70 + 1560 * OV, 1))
print("counts", len(noise), len(dim), len(bright), len(burst), len(veh))
