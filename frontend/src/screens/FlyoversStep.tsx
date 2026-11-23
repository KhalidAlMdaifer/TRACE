// The flyover editor: the spectrogram with proposals, and the boxes the analyst confirms.
// A box is what gets fitted and searched, so this is the screen that decides result quality
// (docs/08-design.md, section 4.4). Proposals are hints and are never treated as confirmed.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError, type Box, type Case, type FlyoverEvent } from "../api";
import { Arrow, Cross, Minus, Plus } from "../components/bits";
import { clock, km, maxHarmonics, minutes } from "../format";
import type { Step } from "../steps";
import type { TriageState } from "../useCaseStream";

const F_LO = 40, F_HI = 450;                 // the grid the spectrogram covers
const MIN_S = 20, MIN_HZ = 2;                // the smallest box the engine will fit
const BURST_FLAG = 0.15;                     // above this a proposal may be a vehicle
const PITCH = 5;                             // px between spectrogram dots
const C = { bg: "#0C0C0B", line: "#272725", dash: "#55524C", text: "#F4F1E8", text2: "#A8A39A", text3: "#8A857C", red: "#FF4D42",
            dot1: "#3A3A36", dot2: "#6B6862", dot3: "#C9C5BB" };
const MONO = '11px "DM Mono", ui-monospace, monospace';
const NO_CURVE = "No curve found in this box. Make it taller or longer.";

type Rect = Pick<Box, "t_start" | "t_end" | "f_lo" | "f_hi">;
interface Shown {
  key: string;                               // the event id, or a temporary one for a box not saved yet
  event: FlyoverEvent | null;
  box: Rect; harmonics: number;
  state: "proposed" | "confirmed" | "fitting" | "failed";
  message?: string;
  n: number | null;                          // 1, 2, 3 by time, for marked flyovers
}
interface Pending { box: Rect; harmonics: number; state: "fitting" | "failed"; message?: string }
type Grab = "move" | "l" | "r" | "t" | "b" | "tl" | "tr" | "bl" | "br";
interface Drag { kind: "draw" | "adjust" | "pan"; key: string | null; grab: Grab; t: number; f: number; x: number; y: number; start: Rect | null; moved: boolean; viewT0: number }
interface Tile { t0: number; t1: number; image: HTMLCanvasElement }

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
const round1 = (v: number) => Math.round(v * 10) / 10;

function normalise(b: Rect, duration: number): Rect {
  let t0 = Math.min(b.t_start, b.t_end), t1 = Math.max(b.t_start, b.t_end);
  let f0 = Math.min(b.f_lo, b.f_hi), f1 = Math.max(b.f_lo, b.f_hi);
  if (t1 - t0 < MIN_S) { const c = (t0 + t1) / 2; t0 = c - MIN_S / 2; t1 = c + MIN_S / 2; }      // snap up to the minimum
  if (f1 - f0 < MIN_HZ) { const c = (f0 + f1) / 2; f0 = c - MIN_HZ / 2; f1 = c + MIN_HZ / 2; }
  if (t0 < 0) { t1 -= t0; t0 = 0; }
  if (t1 > duration) { t0 = Math.max(0, t0 - (t1 - duration)); t1 = duration; }
  if (f0 < F_LO) { f1 += F_LO - f0; f0 = F_LO; }
  if (f1 > F_HI) { f0 = Math.max(F_LO, f0 - (f1 - F_HI)); f1 = F_HI; }
  return { t_start: round1(t0), t_end: round1(t1), f_lo: round1(f0), f_hi: round1(f1) };
}

/** A grid from the api as a dot-matrix image. */
function paint(data: string, cols: number, rows: number, w: number, h: number): HTMLCanvasElement {
  const bytes = Uint8Array.from(atob(data), (ch) => ch.charCodeAt(0));
  const cv = document.createElement("canvas");
  cv.width = Math.max(1, Math.round(w)); cv.height = Math.max(1, Math.round(h));
  const ctx = cv.getContext("2d")!;
  const cw = w / cols, chh = h / rows, d = Math.max(2, Math.min(cw, chh) * 0.62);
  // The noise floor of a grid depends on how much each cell averages: a wide view is dim, a
  // close one bright. Measure it (the 97th percentile cell: a flyover's curve covers about one
  // cell in a hundred) and draw only what rises above it, so noise is the same dim texture at
  // every zoom and tones stand out.
  const sorted = Array.from(bytes).sort((x, y) => x - y);
  const floor = (sorted[Math.floor(sorted.length * 0.97)] ?? 0) / 255, span = 0.4;
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const raw = bytes[r * cols + c] / 255;
      const v = raw <= floor ? 0.03 + 0.2 * Math.pow(raw / Math.max(floor, 1e-6), 3) : Math.min(1, 0.26 + 0.74 * ((raw - floor) / span));
      if (v < 0.035) continue;
      ctx.fillStyle = v > 0.72 ? C.text : v > 0.48 ? C.dot3 : v > 0.26 ? C.dot2 : C.dot1;
      ctx.globalAlpha = v < 0.12 ? 0.55 : 1;
      ctx.fillRect(c * cw + (cw - d) / 2, h - (r + 1) * chh + (chh - d) / 2, d, d);      // row 0 is the lowest frequency
    }
  }
  return cv;
}

function tickStep(span: number): number {
  for (const s of [5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600]) if (span / s <= 8) return s;
  return 7200;
}

interface Props { kase: Case; triage: TriageState; go: (s: Step) => void; finish: () => Promise<void>; header: ReactNode; nav: ReactNode }

export function FlyoversStep({ kase, triage, go, finish, header, nav }: Props) {
  const [finishing, setFinishing] = useState(false);
  const qc = useQueryClient();
  const caseId = kase.id;
  const duration = kase.media!.duration_s;
  const ready = kase.media!.spectrogram_ready;
  const eventsQ = useQuery({ queryKey: ["events", caseId], queryFn: () => api.events(caseId), enabled: ready });
  const [pending, setPending] = useState<Record<string, Pending>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [view, setView] = useState({ t0: 0, t1: Math.min(duration, 2400) });
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [tile, setTile] = useState<Tile | null>(null);
  const [strip, setStrip] = useState<HTMLCanvasElement | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [draft, setDraft] = useState<{ key: string | null; box: Rect } | null>(null);
  const [hover, setHover] = useState<{ t: number; f: number } | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const inflight = useRef<Record<string, AbortController>>({});
  const tempId = useRef(0);
  const nudge = useRef<ReturnType<typeof setTimeout> | null>(null);

  // --- what is shown: the server's events, with boxes being fitted laid over them
  const shown: Shown[] = useMemo(() => {
    const out: Shown[] = [];
    for (const e of eventsQ.data ?? []) {
      if (e.status === "rejected") continue;
      const p = pending[e.id];
      out.push({ key: e.id, event: e, box: p?.box ?? e, harmonics: p?.harmonics ?? e.harmonics, message: p?.message,
                 state: p ? p.state : e.status === "confirmed" ? "confirmed" : "proposed", n: null });
    }
    for (const [key, p] of Object.entries(pending)) if (key.startsWith("new-")) out.push({ key, event: null, box: p.box, harmonics: p.harmonics, state: p.state, message: p.message, n: null });
    const marked = out.filter((s) => s.state !== "proposed").sort((a, b) => a.box.t_start - b.box.t_start);
    marked.forEach((s, i) => (s.n = i + 1));
    // a suggestion under a box the analyst has marked has done its job: stop drawing it
    const covered = (s: Shown) => { const c = (s.box.t_start + s.box.t_end) / 2; return marked.some((m) => c >= m.box.t_start && c <= m.box.t_end); };
    return out.filter((s) => s.state !== "proposed" || !covered(s));
  }, [eventsQ.data, pending]);
  const marked = shown.filter((s) => s.n != null).sort((a, b) => a.n! - b.n!);
  const suggestions = shown.filter((s) => s.state === "proposed").sort((a, b) => a.box.t_start - b.box.t_start);
  const nConfirmed = shown.filter((s) => s.state === "confirmed").length;
  const nFitting = shown.filter((s) => s.state === "fitting").length;
  const sel = shown.find((s) => s.key === selected) ?? null;

  // --- geometry
  const px0 = 70, px1 = Math.max(px0 + 50, size.w - 30), py0 = 84, py1 = Math.max(py0 + 50, size.h - 196);
  const pw = px1 - px0, ph = py1 - py0;
  const sy0 = py1 + 52, sy1 = sy0 + 36;                                   // the overview strip
  const X = useCallback((t: number) => px0 + ((t - view.t0) / (view.t1 - view.t0)) * pw, [view, pw]);
  const Y = useCallback((f: number) => py1 - ((f - F_LO) / (F_HI - F_LO)) * ph, [py1, ph]);
  const T = (x: number) => view.t0 + ((x - px0) / pw) * (view.t1 - view.t0);
  const F = (y: number) => F_LO + ((py1 - y) / ph) * (F_HI - F_LO);
  const SX = (t: number) => px0 + (t / duration) * pw;

  useEffect(() => {
    const el = canvas.current!;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // --- the spectrogram for the visible window, fetched a moment after the view settles
  useEffect(() => {
    if (!ready || !size.w) return;
    const ctl = new AbortController();
    const cols = Math.max(20, Math.floor(pw / PITCH)), rows = Math.max(20, Math.floor(ph / PITCH));
    const timer = setTimeout(() => {
      api.spectrogram(caseId, { t0: view.t0, t1: view.t1, f_lo: F_LO, f_hi: F_HI, cols, rows }, ctl.signal)
        .then((g) => setTile({ t0: g.t0, t1: g.t1, image: paint(g.data, g.cols, g.rows, pw, ph) }))
        .catch(() => undefined);
    }, tile ? 90 : 0);
    return () => { clearTimeout(timer); ctl.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, caseId, view.t0, view.t1, pw, ph]);

  useEffect(() => {
    if (!ready || !size.w) return;
    const ctl = new AbortController();
    api.spectrogram(caseId, { t0: 0, t1: duration, f_lo: 60, f_hi: 300, cols: Math.max(20, Math.floor(pw / PITCH)), rows: 7 }, ctl.signal)
      .then((g) => setStrip(paint(g.data, g.cols, g.rows, pw, sy1 - sy0)))
      .catch(() => undefined);
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, caseId, duration, pw]);

  // --- fitting: every released box goes to the api, and a newer release cancels the one in flight
  const startFit = useCallback((key: string, box: Rect, harmonics: number, event: FlyoverEvent | null) => {
    inflight.current[key]?.abort();
    const ctl = (inflight.current[key] = new AbortController());
    setPending((p) => ({ ...p, [key]: { box, harmonics, state: "fitting" } }));
    const h = Math.min(harmonics, maxHarmonics(box.f_hi));
    const call = event
      ? api.patchEvent(caseId, event.id, { ...box, harmonics: h, ...(event.status !== "confirmed" ? { status: "confirmed" as const } : {}) }, ctl.signal)
      : api.createEvent(caseId, { ...box, harmonics: h }, ctl.signal);
    call.then((ev) => {
      qc.setQueryData<FlyoverEvent[]>(["events", caseId], (old) => [...(old ?? []).filter((e) => e.id !== ev.id), ev].sort((a, b) => a.t_start - b.t_start));
      setPending((p) => { const { [key]: _gone, ...rest } = p; return rest; });
      setSelected((s) => (s === key ? ev.id : s));
      qc.invalidateQueries({ queryKey: ["case", caseId] });
    }).catch((e) => {
      if (ctl.signal.aborted) return;
      const message = e instanceof ApiError && (e.code === "fit_failed" || e.code === "box_too_small") ? NO_CURVE
        : e instanceof ApiError ? e.message : "The fit could not be reached. Move the box to try again.";
      setPending((p) => ({ ...p, [key]: { box, harmonics, state: "failed", message } }));
    });
  }, [caseId, qc]);

  const remove = useCallback((s: Shown) => {
    inflight.current[s.key]?.abort();
    setPending((p) => { const { [s.key]: _gone, ...rest } = p; return rest; });
    setSelected((cur) => (cur === s.key ? null : cur));
    if (!s.event) return;
    const gone = s.event.id;
    // a proposal is dismissed, not deleted: detection must not propose it again
    const call = s.event.source === "detect" && s.event.status === "proposed" ? api.patchEvent(caseId, gone, { status: "rejected" }).then(() => undefined) : api.deleteEvent(caseId, gone).then(() => undefined);
    qc.setQueryData<FlyoverEvent[]>(["events", caseId], (old) => (old ?? []).filter((e) => e.id !== gone));
    call.finally(() => { qc.invalidateQueries({ queryKey: ["events", caseId] }); qc.invalidateQueries({ queryKey: ["case", caseId] }); });
  }, [caseId, qc]);

  // --- drawing
  useEffect(() => {
    const el = canvas.current!;
    const ctx = el.getContext("2d")!;
    const dpr = window.devicePixelRatio || 1;
    el.width = Math.round(size.w * dpr); el.height = Math.round(size.h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size.w, size.h);
    if (!size.w) return;
    const label = (text: string, x: number, y: number, color: string, align: CanvasTextAlign = "left") => {
      ctx.font = MONO; ctx.textAlign = align; ctx.lineJoin = "round";
      const spaced = text.toUpperCase().split("").join(" ");
      ctx.strokeStyle = C.bg; ctx.lineWidth = 4; ctx.strokeText(spaced, x, y);
      ctx.fillStyle = color; ctx.fillText(spaced, x, y);
    };

    // axes
    ctx.font = MONO; ctx.fillStyle = C.text3; ctx.textAlign = "center";
    const step = tickStep(view.t1 - view.t0);
    for (let t = Math.ceil(view.t0 / step) * step; t <= view.t1 + 1e-6; t += step) ctx.fillText(clock(t, true), X(t), py1 + 20);
    ctx.textAlign = "right";
    for (const f of [450, 400, 300, 200, 100, 40]) ctx.fillText(f === 450 ? "450 Hz" : String(f), px0 - 10, Y(f) + 4);

    // the spectrogram: the last tile, stretched to where its times now sit, until the next one lands
    ctx.save();
    ctx.beginPath(); ctx.rect(px0, py0, pw, ph); ctx.clip();
    if (tile) ctx.drawImage(tile.image, X(tile.t0), py0, X(tile.t1) - X(tile.t0), ph);

    // boxes: suggestions underneath, marked flyovers above, the selected one last
    const order = [...shown].sort((a, b) => Number(a.key === selected) - Number(b.key === selected) || Number(a.state !== "proposed") - Number(b.state !== "proposed"));
    for (const s of order) {
      const b = draft && draft.key === s.key ? draft.box : s.box;
      const x = X(b.t_start), y = Y(b.f_hi), w = X(b.t_end) - x, h = Y(b.f_lo) - y;
      const vehicle = s.state === "proposed" && (s.event?.burst ?? 0) > BURST_FLAG;
      ctx.setLineDash([]); ctx.globalAlpha = 1;
      if (s.state === "proposed") { ctx.setLineDash([4, 4]); ctx.lineWidth = 1.25; ctx.strokeStyle = vehicle ? C.text3 : "rgba(244,241,232,0.55)"; }
      else if (s.state === "fitting") { ctx.setLineDash([6, 4]); ctx.lineWidth = 1.5; ctx.strokeStyle = C.red; }
      else if (s.state === "failed") { ctx.lineWidth = 1.5; ctx.strokeStyle = C.red; }
      else { ctx.lineWidth = 1.5; ctx.strokeStyle = s.key === selected ? C.text : "rgba(244,241,232,0.8)"; }
      if (s.key === selected && s.state === "confirmed") { ctx.fillStyle = "rgba(244,241,232,0.04)"; ctx.fillRect(x, y, w, h); }
      ctx.strokeRect(x, y, w, h);
      ctx.setLineDash([]);
      // the fitted curve: red on a confirmed flyover, thin ivory on a suggestion
      const curve = s.event?.curve ?? [];
      if (curve.length > 1 && (s.state === "confirmed" || s.state === "proposed") && !(draft && draft.key === s.key)) {
        ctx.save(); ctx.beginPath(); ctx.rect(x, y, w, h); ctx.clip();
        ctx.beginPath();
        curve.forEach(([t, f], i) => (i ? ctx.lineTo(X(t), Y(f)) : ctx.moveTo(X(t), Y(f))));
        ctx.lineJoin = "round";
        if (s.state === "confirmed") { ctx.strokeStyle = C.red; ctx.lineWidth = 2; } else { ctx.strokeStyle = vehicle ? C.text3 : "rgba(244,241,232,0.55)"; ctx.lineWidth = 1; }
        ctx.stroke(); ctx.restore();
      }
      if (s.key === selected && s.state !== "proposed") {
        ctx.fillStyle = C.text; ctx.strokeStyle = C.bg; ctx.lineWidth = 1;
        for (const [hx, hy] of [[x, y], [x + w, y], [x, y + h], [x + w, y + h]]) { ctx.fillRect(hx - 4, hy - 4, 8, 8); ctx.strokeRect(hx - 4, hy - 4, 8, 8); }
      }
    }
    // a box being drawn
    if (draft && draft.key === null) {
      const b = draft.box, x = X(Math.min(b.t_start, b.t_end)), y = Y(Math.max(b.f_lo, b.f_hi));
      ctx.setLineDash([6, 4]); ctx.lineWidth = 1.5; ctx.strokeStyle = C.red;
      ctx.strokeRect(x, y, Math.abs(X(b.t_end) - X(b.t_start)), Math.abs(Y(b.f_lo) - Y(b.f_hi))); ctx.setLineDash([]);
    }
    // a ghost of the right shape on hover: about 100 s wide, centred on the bend
    if (hover && !drag && !shown.some((s) => inside(s.box, hover.t, hover.f))) {
      ctx.setLineDash([2, 4]); ctx.lineWidth = 1; ctx.strokeStyle = "rgba(244,241,232,0.3)";
      ctx.strokeRect(X(hover.t - 50), Y(hover.f + 30), X(hover.t + 50) - X(hover.t - 50), Y(hover.f - 30) - Y(hover.f + 30)); ctx.setLineDash([]);
    }
    ctx.restore();

    // labels sit above each box, outside the clip so they stay readable at the top edge
    for (const s of order) {
      const b = draft && draft.key === s.key ? draft.box : s.box;
      const x = X(b.t_start), y = Y(b.f_hi) - 8;
      if (x < px0 - 40 || x > px1) continue;
      const lx = clamp(x - 2, px0, px1 - 60), ly = Math.max(py0 - 6, y);
      if (s.state === "proposed") label((s.event?.burst ?? 0) > BURST_FLAG ? "Possible vehicle" : "Suggestion", lx, ly, C.text2);
      else if (s.state === "fitting") label(`${s.n} · Fitting`, lx, ly, C.red);
      else if (s.state === "failed") label(`${s.n} · No curve found`, lx, ly, C.red);
      else label(`${s.n} · ${clock(s.event?.fit?.t_cpa ?? (b.t_start + b.t_end) / 2, true)}`, lx, ly, C.text);
    }

    // the overview strip: the whole recording, the visible window, a mark per flyover, the part not checked yet
    label("Whole recording", px0, sy0 - 8, C.text3);
    if (strip) ctx.drawImage(strip, px0, sy0, pw, sy1 - sy0);
    for (const s of shown) {
      if (s.n == null) continue;
      ctx.fillStyle = s.state === "confirmed" ? C.red : C.text3;
      ctx.fillRect(SX((s.box.t_start + s.box.t_end) / 2) - 1.5, sy0 - 3, 3, sy1 - sy0 + 6);
    }
    if (triage.phase === "detecting" && triage.doneS < duration - 1) {
      label("Not yet checked", px1, sy0 - 8, C.text3, "right");
      ctx.fillStyle = "rgba(12,12,11,0.6)"; ctx.fillRect(SX(triage.doneS), sy0, px1 - SX(triage.doneS), sy1 - sy0);
      ctx.setLineDash([3, 3]); ctx.lineWidth = 1; ctx.strokeStyle = C.text3;
      ctx.strokeRect(SX(triage.doneS) + 0.5, sy0 + 0.5, px1 - SX(triage.doneS) - 1, sy1 - sy0 - 1); ctx.setLineDash([]);
    }
    ctx.lineWidth = 1.5; ctx.strokeStyle = C.text;
    ctx.strokeRect(SX(view.t0), sy0 - 1, Math.max(4, SX(view.t1) - SX(view.t0)), sy1 - sy0 + 2);
    ctx.font = MONO; ctx.fillStyle = C.text3; ctx.textAlign = "left"; ctx.fillText("0:00", px0, sy1 + 20);
    ctx.textAlign = "right"; ctx.fillText(clock(duration), px1, sy1 + 20);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [size, view, tile, strip, shown, selected, draft, hover, drag, triage.phase, triage.doneS, duration]);

  // --- pointer
  const inside = (b: Rect, t: number, f: number) => t >= b.t_start && t <= b.t_end && f >= b.f_lo && f <= b.f_hi;
  const at = (e: { clientX: number; clientY: number }) => { const r = canvas.current!.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
  const hit = (x: number, y: number): { s: Shown; grab: Grab } | null => {
    const near = 7;
    if (sel && sel.state !== "proposed") {                                    // the selected box's handles and edges first
      const b = sel.box, l = X(b.t_start), r = X(b.t_end), t = Y(b.f_hi), bt = Y(b.f_lo);
      if (x >= l - near && x <= r + near && y >= t - near && y <= bt + near) {
        const onL = Math.abs(x - l) <= near, onR = Math.abs(x - r) <= near, onT = Math.abs(y - t) <= near, onB = Math.abs(y - bt) <= near;
        const grab = ((onT ? "t" : onB ? "b" : "") + (onL ? "l" : onR ? "r" : "")) as Grab | "";
        return { s: sel, grab: grab || "move" };
      }
    }
    const t = T(x), f = F(y);
    const under = shown.filter((s) => inside(s.box, t, f)).sort((a, b) => Number(b.state !== "proposed") - Number(a.state !== "proposed") || (a.box.t_end - a.box.t_start) - (b.box.t_end - b.box.t_start));
    return under.length ? { s: under[0], grab: "move" } : null;
  };
  const panTo = (centre: number) => setView((v) => { const span = v.t1 - v.t0, t0 = clamp(centre - span / 2, 0, Math.max(0, duration - span)); return { t0, t1: t0 + span }; });
  const zoom = (factor: number, about?: number) => setView((v) => {
    const span = clamp((v.t1 - v.t0) * factor, Math.min(60, duration), duration), c = about ?? (v.t0 + v.t1) / 2;
    const t0 = clamp(c - ((c - v.t0) / (v.t1 - v.t0)) * span, 0, Math.max(0, duration - span));
    return { t0, t1: t0 + span };
  });

  const down = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!ready) return;
    const p = at(e);
    e.currentTarget.setPointerCapture(e.pointerId);
    e.currentTarget.focus();
    if (p.y >= sy0 - 6 && p.y <= sy1 + 6 && p.x >= px0 && p.x <= px1) {          // the strip is the scroll bar
      panTo((p.x - px0) / pw * duration);
      setDrag({ kind: "pan", key: null, grab: "move", t: 0, f: 0, x: p.x, y: p.y, start: null, moved: true, viewT0: view.t0 });
      return;
    }
    if (p.x < px0 || p.x > px1 || p.y < py0 || p.y > py1) return;
    const h = hit(p.x, p.y);
    const base = { t: T(p.x), f: F(p.y), x: p.x, y: p.y, moved: false, viewT0: view.t0 };
    // A suggestion is only a hint, and often sits where the real box belongs: a drag that starts
    // on one draws a new box; only a plain click confirms it.
    if (h && h.s.state !== "proposed") { setSelected(h.s.key); setDrag({ ...base, kind: "adjust", key: h.s.key, grab: h.grab, start: h.s.box }); }
    else { setSelected(null); setDrag({ ...base, kind: "draw", key: h ? h.s.key : null, grab: "br", start: null }); }
  };
  const move = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const p = at(e);
    const inPlot = p.x >= px0 && p.x <= px1 && p.y >= py0 && p.y <= py1;
    setHover(inPlot && !drag ? { t: T(p.x), f: F(p.y) } : null);
    if (!drag) {
      const h = inPlot ? hit(p.x, p.y) : null;
      const cur: Record<string, string> = { move: h?.s.state === "proposed" ? "pointer" : "move", l: "ew-resize", r: "ew-resize", t: "ns-resize", b: "ns-resize", tl: "nwse-resize", br: "nwse-resize", tr: "nesw-resize", bl: "nesw-resize" };
      e.currentTarget.style.cursor = h ? cur[h.grab] : inPlot ? "crosshair" : p.y >= sy0 - 6 && p.y <= sy1 + 6 ? "ew-resize" : "default";
      return;
    }
    if (drag.kind === "pan") { panTo((p.x - px0) / pw * duration); return; }
    const moved = drag.moved || Math.abs(p.x - drag.x) > 4 || Math.abs(p.y - drag.y) > 4;
    if (!moved) return;
    if (!drag.moved) setDrag({ ...drag, moved: true });
    const t = clamp(T(p.x), 0, duration), f = clamp(F(p.y), F_LO, F_HI);
    if (drag.kind === "draw") { setDraft({ key: null, box: { t_start: drag.t, t_end: t, f_lo: drag.f, f_hi: f } }); return; }
    const s = drag.start!, dt = t - drag.t, df = f - drag.f, g = drag.grab;
    const box = g === "move"
      ? { t_start: s.t_start + dt, t_end: s.t_end + dt, f_lo: s.f_lo + df, f_hi: s.f_hi + df }
      : { t_start: g.includes("l") ? Math.min(t, s.t_end - 1) : s.t_start, t_end: g.includes("r") ? Math.max(t, s.t_start + 1) : s.t_end,
          f_lo: g.includes("b") ? Math.min(f, s.f_hi - 0.5) : s.f_lo, f_hi: g.includes("t") ? Math.max(f, s.f_lo + 0.5) : s.f_hi };
    setDraft({ key: drag.key, box });
  };
  const up = () => {
    const d = drag, dr = draft;
    setDrag(null); setDraft(null);
    if (!d || d.kind === "pan") return;
    const s = d.key ? shown.find((x) => x.key === d.key) ?? null : null;
    if (d.kind === "draw") {
      if (!dr) {                                                               // a click, not a drag
        if (s && s.state === "proposed") { setSelected(s.key); startFit(s.key, normalise(s.box, duration), s.harmonics, s.event); }   // on a suggestion: confirm it
        return;
      }
      const key = `new-${++tempId.current}`;
      setSelected(key);
      startFit(key, normalise(dr.box, duration), 1, null);
    } else if (s && dr) {
      startFit(s.key, normalise(dr.box, duration), s.harmonics, s.event);      // moved or resized: fit it again
    }
  };

  // the wheel zooms about the pointer; with shift, or sideways, it pans
  useEffect(() => {
    const el = canvas.current!;
    const on = (e: WheelEvent) => {
      const p = at(e);
      if (p.x < px0 || p.x > px1 || p.y < py0 || p.y > sy1) return;
      e.preventDefault();
      if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) setView((v) => { const span = v.t1 - v.t0, t0 = clamp(v.t0 + ((e.deltaX || e.deltaY) / pw) * span, 0, Math.max(0, duration - span)); return { t0, t1: t0 + span }; });
      else zoom(Math.exp(e.deltaY * 0.0015), T(p.x));
    };
    el.addEventListener("wheel", on, { passive: false });
    return () => el.removeEventListener("wheel", on);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, pw, duration, sy1]);

  // The selected box moves with the arrow keys, and grows or shrinks with Alt held; Shift makes
  // bigger steps. The fit follows a moment after the last press. Works on the spectrogram and
  // on the box's row in the list, so the editor can be used without a pointer.
  const key = (e: React.KeyboardEvent, target: Shown | null = sel) => {
    const sel = target;
    if (!sel) return;
    if (e.key === "Delete" || (e.key === "Backspace" && e.currentTarget === canvas.current)) { e.preventDefault(); remove(sel); return; }
    if (e.key === "Enter" && sel.state === "proposed") { e.preventDefault(); startFit(sel.key, normalise(sel.box, duration), sel.harmonics, sel.event); return; }
    const k = e.shiftKey ? 5 : 1;
    const d = { ArrowLeft: [-k, 0], ArrowRight: [k, 0], ArrowUp: [0, k], ArrowDown: [0, -k] }[e.key];
    if (!d || sel.state === "proposed") return;
    e.preventDefault();
    setSelected(sel.key);
    const b0 = sel.box;
    const box = normalise(e.altKey
      ? { t_start: b0.t_start - d[0], t_end: b0.t_end + d[0], f_lo: b0.f_lo - d[1], f_hi: b0.f_hi + d[1] }       // wider or narrower, taller or shorter
      : { t_start: b0.t_start + d[0], t_end: b0.t_end + d[0], f_lo: b0.f_lo + d[1], f_hi: b0.f_hi + d[1] }, duration);
    inflight.current[sel.key]?.abort();
    setPending((p) => ({ ...p, [sel.key]: { box, harmonics: sel.harmonics, state: "fitting" } }));
    if (nudge.current) clearTimeout(nudge.current);
    nudge.current = setTimeout(() => startFit(sel.key, box, sel.harmonics, sel.event), 600);
  };

  // a box in the middle of what is on screen, for an analyst who cannot drag one
  const addHere = () => {
    const c = (view.t0 + view.t1) / 2, key = `new-${++tempId.current}`;
    setSelected(key);
    startFit(key, normalise({ t_start: c - 50, t_end: c + 50, f_lo: 90, f_hi: 170 }, duration), 1, null);
  };

  const pick = (s: Shown) => {
    setSelected(s.key);
    const c = (s.box.t_start + s.box.t_end) / 2;
    if (c < view.t0 || c > view.t1) panTo(c);
  };
  const setHarmonics = (s: Shown, h: number) => startFit(s.key, s.box, h, s.event);
  const hMax = sel ? maxHarmonics(sel.box.f_hi) : 1;
  const status = !ready ? (triage.phase === "failed" ? triage.message ?? "The recording could not be read." : "Reading audio")
    : triage.phase === "detecting" ? `Checking for flyovers · ${minutes(triage.doneS)} of ${minutes(duration)} min · ${triage.proposed} proposed`
    : `Checked · ${shown.filter((s) => s.state === "proposed").length} suggestions left`;
  const alt = `Dot-matrix spectrogram of the recording from ${clock(view.t0)} to ${clock(view.t1)}, ${F_LO} to ${F_HI} hertz. `
    + `${nConfirmed} confirmed flyover${nConfirmed === 1 ? "" : "s"}, ${nFitting} being fitted, ${shown.filter((s) => s.state === "proposed").length} suggestions. `
    + "The list beside it has every flyover.";

  return (
    <div className="app">
      <aside className="panel">
        {header}{nav}
        <div className="panel-body">
          <div className="stack gap10">
            <h1>Confirm the flyovers</h1>
            <p className="muted">Each S-shaped curve is an aircraft passing. Put a box around the bend of each real one. The suggestions are guesses.</p>
          </div>
          <section aria-label="Flyovers marked" className="stack gap10">
            <h2 className="mono11" style={{ margin: 0 }}>Flyovers marked</h2>
            {marked.length === 0 ? (
              <div className="card pad helper">None yet. Click a suggestion to confirm it, or drag on the spectrogram to box a flyover.</div>
            ) : (
              <ul className="card flylist">
                {marked.map((s) => {
                  const fit = s.event?.fit;
                  const mid = clock(fit && s.state === "confirmed" ? fit.t_cpa : (s.box.t_start + s.box.t_end) / 2, true);
                  return (
                    <li key={s.key} className={`${s.key === selected ? "selected " : ""}${s.state}`}>
                      <button type="button" className="pick" aria-pressed={s.key === selected} aria-describedby="box-keys" onClick={() => pick(s)} onKeyDown={(e) => key(e, s)}>
                        <span aria-hidden="true" className="num">{s.n}</span>
                        <span className="stack" style={{ minWidth: 0 }}>
                          <span className="t">Flyover {s.n} · {mid}</span>
                          <span className="s">{s.state === "fitting" ? "Finding the curve in your box" : s.state === "failed" ? s.message
                            : fit ? `${Math.round(fit.f0)} Hz · ${Math.round(fit.v)} m/s · ${km(fit.d)}` : ""}</span>
                        </span>
                      </button>
                      <span className={`mono11 ${s.state === "confirmed" ? "bright" : "red"}`} style={{ flex: "none" }}>
                        {s.state === "confirmed" ? "Confirmed" : s.state === "fitting" ? "Fitting" : "No curve"}
                      </span>
                      <button type="button" className="icon-btn" aria-label={`Remove flyover ${s.n}`} onClick={() => remove(s)}><Cross /></button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
          <p id="box-keys" className="sr-only">With a flyover focused: arrow keys move its box, Alt with arrow keys resizes it, Shift makes bigger steps, Delete removes it.</p>
          {ready && (
            <details className="card suggest">
              <summary><span className="mono11">Suggestions</span><span className="mono11 tnum">{suggestions.length}</span></summary>
              {suggestions.length === 0 ? <div className="helper" style={{ padding: "0 16px 14px" }}>None left. {triage.phase === "detecting" ? "The recording is still being checked." : ""}</div> : (
                <ul>
                  {suggestions.map((s) => (
                    <li key={s.key}>
                      <button type="button" className="where" onClick={() => panTo((s.box.t_start + s.box.t_end) / 2)} aria-label={`Show the suggestion at ${clock(s.event?.fit?.t_cpa ?? s.box.t_start)}`}>
                        <span className="tnum">{clock(s.event?.fit?.t_cpa ?? (s.box.t_start + s.box.t_end) / 2, true)}</span>
                        <span className="s">{Math.round(s.event?.fit?.f0 ?? s.box.f_lo)} Hz{(s.event?.burst ?? 0) > BURST_FLAG ? " · possible vehicle" : ""}</span>
                      </button>
                      <button type="button" className="link-btn" onClick={() => { setSelected(s.key); startFit(s.key, normalise(s.box, duration), s.harmonics, s.event); }}>Confirm</button>
                      <button type="button" className="link-btn" onClick={() => remove(s)}>Dismiss</button>
                    </li>
                  ))}
                </ul>
              )}
              <div style={{ padding: "0 16px 14px" }}><button type="button" className="link-btn" style={{ padding: "8px 0" }} onClick={addHere}>Add a box in the middle of the view</button></div>
            </details>
          )}
          {sel && sel.n != null && (
            <div className="card">
              <div className="card-row"><span className="mono11">Box {sel.n}</span>
                <span className="v tnum">{clock(sel.box.t_start, true)} to {clock(sel.box.t_end, true)} · {Math.round(sel.box.f_lo)} to {Math.round(sel.box.f_hi)} Hz</span></div>
              <div className="card-row" style={{ minHeight: 52, paddingRight: 6 }}><span className="mono11">Harmonics</span>
                <div role="group" aria-label={`Harmonics for flyover ${sel.n}`} className="stepper">
                  <button type="button" className="icon-btn" aria-label="Fewer harmonics" disabled={sel.harmonics <= 1 || sel.state === "fitting"} onClick={() => setHarmonics(sel, sel.harmonics - 1)}><Minus dim={sel.harmonics <= 1} /></button>
                  <span className="n" aria-live="polite">{sel.harmonics}</span>
                  <button type="button" className="icon-btn" aria-label="More harmonics" disabled={sel.harmonics >= hMax || sel.state === "fitting"} onClick={() => setHarmonics(sel, sel.harmonics + 1)}><Plus dim={sel.harmonics >= hMax} /></button>
                </div>
              </div>
            </div>
          )}
          <div role="status" className="card pad stack gap4">
            <div className="mono11 bright row" style={{ gap: 8 }}><span aria-hidden="true" className="sq" />
              <span>{nConfirmed} confirmed{nFitting ? ` · ${nFitting} fitting` : ""}</span></div>
            <div className="helper">Two make the recording searchable. A third lets a result be confirmed.</div>
          </div>
          {ready && nConfirmed < 2 && nFitting === 0 && (
            <div className="row between helper" style={{ gap: 12 }}>
              <span>{triage.phase === "detecting" ? "Still checking the recording. If there are fewer than two flyovers to mark:" : "Fewer than two flyovers to mark?"}</span>
              <button type="button" className="link-btn" style={{ padding: "12px 0" }} disabled={finishing}
                      onClick={async () => { setFinishing(true); try { await finish(); } catch { setFinishing(false); } }}>
                {finishing ? "Saving" : "Finish as not locatable"}
              </button>
            </div>
          )}
          <div className="actions">
            <button type="button" className="pill" onClick={() => go("where")}>Back</button>
            <button type="button" className="pill primary" disabled={nConfirmed < 2}
                    onClick={async () => { await qc.refetchQueries({ queryKey: ["case", caseId] }); go("review"); }}>
              <span>Continue</span><Arrow />
            </button>
          </div>
        </div>
      </aside>
      <main className="stage">
        <canvas ref={canvas} className="spectro" role="img" aria-label={alt} tabIndex={0}
                onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onPointerLeave={() => setHover(null)} onKeyDown={key} />
        <div role="status" className="chip tl mono11"><span aria-hidden="true" className="sq" /><span>{status}</span></div>
        <div className="chip col tr mono11">
          <div><span aria-hidden="true" className="swatch-box" /><span>Confirmed flyover</span></div>
          <div><span aria-hidden="true" className="swatch-line" style={{ background: "var(--red)" }} /><span>Fitted curve</span></div>
          <div><span aria-hidden="true" className="swatch-box" style={{ border: "1px dashed var(--text)" }} /><span>Suggestion</span></div>
          <div><span aria-hidden="true" className="swatch-box" style={{ border: "1px dashed var(--text-3)" }} /><span>Possible vehicle</span></div>
        </div>
        <div className="mono11 dim" style={{ position: "absolute", left: 20, bottom: 34 }}>
          {sel?.state === "failed" ? <span className="mono11 red">{sel.message}</span> : "Drag on the spectrogram to box a flyover"}
        </div>
        <div className="corner br">
          <button type="button" className="round" aria-label="Zoom out" disabled={view.t1 - view.t0 >= duration - 0.5} onClick={() => zoom(1.6)}><Minus /></button>
          <button type="button" className="round" aria-label="Zoom in" disabled={view.t1 - view.t0 <= 60.5} onClick={() => zoom(1 / 1.6)}><Plus /></button>
          <button type="button" className="pill small" onClick={() => setView({ t0: 0, t1: duration })}>Whole recording</button>
        </div>
      </main>
    </div>
  );
}
