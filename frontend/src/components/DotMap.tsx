// The dot-matrix map: a canvas, one dot per cell (docs/08-design.md, section 6). Land cells
// come from the pack; search points, match strength, flight paths, candidate rings and the
// estimate are layers on top; the camera flies between framings.
import { useEffect, useMemo, useRef, useState } from "react";
import type { Cell, FlightPath, LatLon, Pack, RegionFeature } from "../api";
import { distance } from "../format";

const C = { bg: "#0C0C0B", panel: "#111110", line: "#272725", lineStrong: "#3A3A36", dash: "#55524C", text: "#F4F1E8", text2: "#A8A39A", text3: "#8A857C",
            red: "#FF4D42", dot1: "#3A3A36", dot2: "#6B6862", dot3: "#C9C5BB", grid: "#33332F" };
const MONO = '"DM Mono", ui-monospace, monospace';
const CAMERA_MS = 800;

type BBox = [number, number, number, number];            // lat_min, lat_max, lon_min, lon_max
export interface Ring { lat: number; lon: number; n?: number; kind: "selected" | "other" | "outside" | "lead" }
export interface MapPath extends FlightPath { label?: string }
interface Props {
  pack: Pack | undefined;
  selected?: string[];
  selectedTone?: "red" | "gray";                           // gray: the area is shown, but there is no match to colour
  onToggle?: (regionId: string) => void;
  customBBox?: BBox | null;
  drawing?: boolean;
  onDraw?: (bbox: BBox) => void;
  focus?: BBox | null;                                     // what to frame; null is the whole pack
  cells?: Cell[];                                          // search points; a null score is one not scored yet
  cellM?: number;                                          // ground size of a cell: 200, or 50 after the refine
  lattice?: boolean;                                       // close-up: draw the whole lattice in gray under the match cells
  paths?: MapPath[];
  rings?: Ring[];
  estimate?: { lat: number; lon: number; radius_m: number } | null;
  bestBox?: BBox | null;
  scaleBar?: boolean;
  label: string;                                           // the text alternative
}

/** A stable pseudo-random number in [0, 1) from a cell's coordinates, so the texture never flickers. */
function hash(lat: number, lon: number): number {
  let h = Math.imul(Math.round(lat * 1e4) ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul(Math.round(lon * 1e4), 0xc2b2ae35);
  h ^= h >>> 15; h = Math.imul(h, 0x2c1b3c6d); h ^= h >>> 12;
  return (h >>> 0) / 4294967296;
}

function rings(f: RegionFeature): number[][][] {
  return f.geometry.type === "Polygon" ? f.geometry.coordinates : f.geometry.coordinates.flat();
}

function polygons(f: RegionFeature): number[][][][] {
  return f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
}

function inRing(ring: number[][], lon: number, lat: number): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export function regionAt(pack: Pack, lat: number, lon: number): string | null {
  // sub-areas first, so a click inside one picks it and not its parent
  const feats = [...pack.regions.features].sort((a, b) => Number(!!b.properties.parent) - Number(!!a.properties.parent));
  for (const f of feats)
    for (const poly of polygons(f))
      if (inRing(poly[0], lon, lat) && !poly.slice(1).some((hole) => inRing(hole, lon, lat))) return f.properties.id;
  return null;
}

/** A box around a point, in metres each way. */
export function boxAround(lat: number, lon: number, halfM: number): BBox {
  const dla = halfM / 111_320, dlo = halfM / (111_320 * Math.cos((lat * Math.PI) / 180));
  return [lat - dla, lat + dla, lon - dlo, lon + dlo];
}

/** The camera: a centre and a scale. Equirectangular, scaled by cos(latitude of the pack centre). */
interface Cam { lat: number; lon: number; scale: number }
interface View extends Cam { x: (lon: number) => number; y: (lat: number) => number; lonAt: (x: number) => number; latAt: (y: number) => number }

function viewOf(cam: Cam, k: number, w: number, h: number): View {
  return { ...cam, x: (lon) => w / 2 + (lon - cam.lon) * k * cam.scale, y: (lat) => h / 2 - (lat - cam.lat) * cam.scale,
           lonAt: (x) => cam.lon + (x - w / 2) / (k * cam.scale), latAt: (y) => cam.lat - (y - h / 2) / cam.scale };
}

function frame(box: BBox, k: number, w: number, h: number, pad: number): Cam {
  const [la0, la1, lo0, lo1] = box;
  const scale = Math.min((w - 2 * pad) / Math.max((lo1 - lo0) * k, 1e-9), (h - 2 * pad) / Math.max(la1 - la0, 1e-9));
  return { lat: (la0 + la1) / 2, lon: (lo0 + lo1) / 2, scale };
}

function packBox(pack: Pack): BBox {
  let la0 = Infinity, la1 = -Infinity, lo0 = Infinity, lo1 = -Infinity;
  for (const [la, lo] of pack.grid) { la0 = Math.min(la0, la); la1 = Math.max(la1, la); lo0 = Math.min(lo0, lo); lo1 = Math.max(lo1, lo); }
  return isFinite(la0) ? [la0, la1, lo0, lo1] : pack.bbox;
}

const ease = (t: number) => 1 - Math.pow(1 - t, 3);

export function DotMap(p: Props) {
  const { pack, selected = [], selectedTone = "red", onToggle, customBBox, drawing = false, onDraw, focus = null, label } = p;
  const ref = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [drag, setDrag] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const cam = useRef<Cam | null>(null);
  const appear = useRef({ packId: "", start: 0 });
  const picked = useRef({ key: "", at: 0 });           // when the selection last changed, for the stagger
  const latest = useRef(p);
  latest.current = p;
  const k = useMemo(() => (pack ? Math.cos((((pack.bbox[0] + pack.bbox[1]) / 2) * Math.PI) / 180) : 1), [pack]);
  const focusKey = focus ? focus.map((v) => v.toFixed(5)).join(",") : "pack";

  useEffect(() => {
    const el = ref.current!;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // --- one frame
  const draw = (view: View, now: number) => {
    const el = ref.current;
    const q = latest.current;
    if (!el || !pack) return;
    const ctx = el.getContext("2d")!;
    const { w, h } = size;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const grown = reduce ? 1 : Math.min(1, (now - appear.current.start) / 700);
    const sel = new Set(q.selected ?? []);
    const lit = new Set(pack.regions.features.filter((f) => sel.has(f.properties.id) || (f.properties.parent && sel.has(f.properties.parent))).map((f) => f.properties.id));
    const areaColor = (q.selectedTone ?? "red") === "red" ? C.red : C.text3;
    const hasMatches = !!(q.cells && q.cells.length);
    const text = (s: string, x: number, y: number, color: string, align: CanvasTextAlign = "center", px = 12) => {
      ctx.font = `${px}px ${MONO}`; ctx.textAlign = align; ctx.lineJoin = "round";
      const spaced = s.toUpperCase().split("").join(" ");
      ctx.strokeStyle = C.bg; ctx.lineWidth = 4; ctx.strokeText(spaced, x, y);
      ctx.fillStyle = color; ctx.fillText(spaced, x, y);
    };
    const outline = (f: RegionFeature) => {
      ctx.beginPath();
      for (const ring of rings(f)) { ring.forEach(([lon, lat], i) => (i ? ctx.lineTo(view.x(lon), view.y(lat)) : ctx.moveTo(view.x(lon), view.y(lat)))); ctx.closePath(); }
    };

    ctx.clearRect(0, 0, w, h);
    const pitch = (pack.grid_pitch_m / 111_320) * view.scale;             // px between land dots
    const closeUp = pitch > 70;                                          // a few kilometres across: land dots no longer mean anything

    // graticule labels: whole degrees, while they are far enough apart to read and not too far to appear
    if (view.scale > 40 && view.scale < 2000) {
      ctx.font = `11px ${MONO}`; ctx.fillStyle = C.text3; ctx.textAlign = "center";
      for (let lon = Math.ceil(view.lonAt(60)); lon <= Math.floor(view.lonAt(w - 20)); lon++) ctx.fillText(`${Math.abs(lon)}°${lon < 0 ? "W" : "E"}`, view.x(lon), h - 10);
      ctx.textAlign = "left";
      for (let lat = Math.ceil(view.latAt(h - 30)); lat <= Math.floor(view.latAt(20)); lat++) ctx.fillText(`${Math.abs(lat)}°${lat < 0 ? "S" : "N"}`, 10, view.y(lat) + 4);
    }

    // land: region outlines, filled a shade above the sea
    for (const f of pack.regions.features) {
      if (f.properties.parent && !closeUp && !q.onToggle) continue;       // sub-area lines only matter while choosing
      outline(f);
      if (!f.properties.parent) { ctx.fillStyle = C.panel; ctx.fill("evenodd"); }
      ctx.lineWidth = 1; ctx.strokeStyle = sel.size ? C.lineStrong : C.line; ctx.stroke();
    }

    // one dot per land cell; rows fade in from the top on first load
    if (!closeUp) {
      const dot = Math.max(2, Math.min(6, Math.round(pitch * 0.36)));
      const top = view.y(pack.bbox[1]), span = Math.max(1, view.y(pack.bbox[0]) - top);
      const fade = Math.max(0, Math.min(1, (70 - pitch) / 25));
      for (const [lat, lon, rid] of pack.grid) {
        const x = view.x(lon), y = view.y(lat);
        if (x < -10 || x > w + 10 || y < -10 || y > h + 10) continue;
        const a = Math.max(0, Math.min(1, (grown * 1.35 - (y - top) / span) / 0.35)) * fade;
        if (a <= 0) continue;
        const r = hash(lat, lon);
        // a newly selected area turns red dot by dot over a quarter of a second
        const on = lit.has(rid) && (reduce || now - picked.current.at >= r * 250);
        ctx.globalAlpha = a * (on && hasMatches ? 0.45 : 1);              // with matches on the map, the area steps back
        ctx.fillStyle = on ? areaColor : r < 0.07 ? C.dot3 : r < 0.32 ? C.dot2 : C.dot1;
        ctx.fillRect(Math.round(x - dot / 2), Math.round(y - dot / 2), dot, dot);
      }
      ctx.globalAlpha = 1;
    }

    // the selected area's outline
    for (const f of pack.regions.features) {
      if (!sel.has(f.properties.id)) continue;
      outline(f);
      ctx.lineWidth = 1.5; ctx.strokeStyle = areaColor; ctx.lineJoin = "round"; ctx.stroke();
    }

    // search points and match strength
    if (q.cells && q.cells.length) {
      const cellPx = ((q.cellM ?? 200) / 111_320) * view.scale;
      const d = Math.max(3, Math.min(14, cellPx * 0.36));
      if (q.lattice && cellPx >= 12) {                                    // the whole lattice in gray, as far as the view goes
        const dla = (q.cellM ?? 50) / 111_320, dlo = dla / Math.cos((view.lat * Math.PI) / 180);
        const [la0, lo0] = [q.cells[0][0], q.cells[0][1]];
        ctx.fillStyle = C.grid;
        for (let i = Math.floor((view.latAt(h) - la0) / dla); i <= Math.ceil((view.latAt(0) - la0) / dla); i++)
          for (let j = Math.floor((view.lonAt(0) - lo0) / dlo); j <= Math.ceil((view.lonAt(w) - lo0) / dlo); j++)
            ctx.fillRect(view.x(lo0 + j * dlo) - d / 2, view.y(la0 + i * dla) - d / 2, d, d);
      }
      const scores = q.cells.map((c) => c[2]).filter((s): s is number => s != null);
      const lo = Math.min(...scores), hi = Math.max(...scores);
      for (let i = q.cells.length - 1; i >= 0; i--) {                     // best first in the data, so drawn last
        const [lat, lon, sc] = q.cells[i];
        const x = view.x(lon), y = view.y(lat);
        if (x < -20 || x > w + 20 || y < -20 || y > h + 20) continue;
        if (sc == null) { ctx.globalAlpha = 0.9; ctx.fillStyle = C.dot2; }
        else { const t = hi > lo ? (sc - lo) / (hi - lo) : 1; ctx.globalAlpha = t > 0.85 ? 1 : t > 0.6 ? 0.8 : t > 0.3 ? 0.5 : 0.25; ctx.fillStyle = C.red; }
        ctx.fillRect(x - d / 2, y - d / 2, d, d);
      }
      ctx.globalAlpha = 1;
    }

    // "best area so far"
    if (q.bestBox) {
      const [la0, la1, lo0, lo1] = q.bestBox;
      ctx.setLineDash([5, 5]); ctx.lineWidth = 1; ctx.strokeStyle = C.text;
      ctx.strokeRect(view.x(lo0), view.y(la1), view.x(lo1) - view.x(lo0), view.y(la0) - view.y(la1)); ctx.setLineDash([]);
      text("Best area so far", view.x(lo0), view.y(la1) - 8, C.text, "left", 11);
    }

    // flight paths, with a marker and a leader at each closest approach
    for (const path of q.paths ?? []) {
      ctx.beginPath();
      path.points.forEach(([lat, lon], i) => (i ? ctx.lineTo(view.x(lon), view.y(lat)) : ctx.moveTo(view.x(lon), view.y(lat))));
      ctx.strokeStyle = C.text; ctx.lineWidth = closeUp ? 2 : 1.5; ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.stroke();
    }
    if (q.estimate) {
      const ex = view.x(q.estimate.lon), ey = view.y(q.estimate.lat);
      for (const path of q.paths ?? []) {
        const cx = view.x(path.cpa[1]), cy = view.y(path.cpa[0]);
        ctx.beginPath(); ctx.moveTo(ex, ey); ctx.lineTo(cx, cy);
        ctx.setLineDash([4, 6]); ctx.strokeStyle = C.text2; ctx.lineWidth = 1.25; ctx.stroke(); ctx.setLineDash([]);
      }
    }
    for (const path of q.paths ?? []) {
      const cx = view.x(path.cpa[1]), cy = view.y(path.cpa[0]);
      if (!q.estimate && !path.label) continue;
      ctx.fillStyle = C.text; ctx.strokeStyle = C.bg; ctx.lineWidth = 2;
      ctx.fillRect(cx - 5, cy - 5, 10, 10); ctx.strokeRect(cx - 5, cy - 5, 10, 10);
      if (path.label) text(path.label, cx + 14, cy - 8, C.text, "left");
    }

    // the estimate: its uncertainty circle, and a ring on the best cell
    if (q.estimate) {
      const ex = view.x(q.estimate.lon), ey = view.y(q.estimate.lat);
      const r = Math.max(10, (q.estimate.radius_m / 111_320) * view.scale * Math.min(1, grown * 1.2));
      ctx.beginPath(); ctx.arc(ex, ey, r, 0, 2 * Math.PI);
      ctx.fillStyle = "rgba(255,77,66,0.06)"; ctx.fill(); ctx.strokeStyle = C.red; ctx.lineWidth = 2; ctx.stroke();
      ctx.beginPath(); ctx.arc(ex, ey, Math.min(16, Math.max(6, r * 0.5)), 0, 2 * Math.PI); ctx.strokeStyle = C.text; ctx.lineWidth = 1.5; ctx.stroke();
      text(`Estimate, within ${distance(q.estimate.radius_m)}`, ex, ey + r + 22, C.red);
    }

    // candidate rings, numbered
    for (const ring of q.rings ?? []) {
      const x = view.x(ring.lon), y = view.y(ring.lat), r = ring.kind === "lead" ? 9 : 13;
      ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI);
      ctx.setLineDash(ring.kind === "outside" ? [4, 4] : []);
      ctx.lineWidth = ring.kind === "selected" ? 2 : 1.25;
      ctx.strokeStyle = ring.kind === "selected" || ring.kind === "lead" ? C.red : ring.kind === "outside" ? C.text2 : C.text;
      if (ring.kind === "selected") { ctx.fillStyle = "rgba(255,77,66,0.14)"; ctx.fill(); }
      ctx.stroke(); ctx.setLineDash([]);
      if (ring.n != null) text(String(ring.n), x + r + 8, y + 4, ring.kind === "selected" ? C.red : ring.kind === "outside" ? C.text2 : C.text, "left");
    }

    // region names, when there is something to choose between. A small region's name sits in
    // the sea with a leader line (the pack says where); the others sit on their own land.
    if (pack.regions.features.length > 1 && (q.onToggle || sel.size || hasMatches) && !closeUp) {
      for (const f of pack.regions.features) {
        if (f.properties.parent) continue;
        const on = sel.has(f.properties.id) || pack.regions.features.some((g) => g.properties.parent === f.properties.id && sel.has(g.properties.id));
        const placed = pack.labels?.[f.properties.id];
        let lx: number, ly: number, align: CanvasTextAlign = "center";
        if (placed) {
          lx = view.x(placed.at[1]); ly = view.y(placed.at[0]); align = placed.anchor;
          ctx.beginPath(); ctx.moveTo(lx + (placed.anchor === "end" ? 6 : -6), ly - 4); ctx.lineTo(view.x(placed.to[1]), view.y(placed.to[0]));
          ctx.strokeStyle = C.dash; ctx.lineWidth = 1; ctx.stroke();
        } else {
          const big = polygons(f).map((poly) => poly[0]).sort((a, b) => b.length - a.length)[0];
          let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
          for (const [lon, lat] of big) { x0 = Math.min(x0, lon); x1 = Math.max(x1, lon); y0 = Math.min(y0, lat); y1 = Math.max(y1, lat); }
          lx = view.x((x0 + x1) / 2); ly = view.y((y0 + y1) / 2) + 4;
          if (polygons(f).length === 1 && big.length <= 5) ly = view.y(y0) + pitch + 14;       // a plain box: the name goes underneath
        }
        if (lx < -100 || lx > w + 100 || ly < 0 || ly > h) continue;
        text(f.properties.name, lx, ly, on ? C.text : C.dot3, align);
      }
    }

    // a custom area: the stored one, or the one being dragged
    const box = drag
      ? { x: Math.min(drag.x0, drag.x1), y: Math.min(drag.y0, drag.y1), w: Math.abs(drag.x1 - drag.x0), h: Math.abs(drag.y1 - drag.y0) }
      : q.customBBox ? { x: view.x(q.customBBox[2]), y: view.y(q.customBBox[1]), w: view.x(q.customBBox[3]) - view.x(q.customBBox[2]), h: view.y(q.customBBox[0]) - view.y(q.customBBox[1]) } : null;
    if (box) {
      ctx.setLineDash([6, 4]); ctx.lineWidth = 1.5; ctx.strokeStyle = areaColor; ctx.strokeRect(box.x, box.y, box.w, box.h); ctx.setLineDash([]);
      if (!hasMatches) { ctx.fillStyle = "rgba(255,77,66,0.08)"; ctx.fillRect(box.x, box.y, box.w, box.h); }
    }

    // a scale bar: a round length near 120 px
    if (q.scaleBar) {
      const mPerPx = 111_320 / view.scale;
      const nice = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10_000, 20_000, 50_000, 100_000].reduce((a, b) => (Math.abs(b / mPerPx - 120) < Math.abs(a / mPerPx - 120) ? b : a));
      const len = nice / mPerPx, x = 20, y = h - 20, bw = Math.max(len + 24, 84);
      ctx.fillStyle = C.panel; ctx.strokeStyle = C.line; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.roundRect(x, y - 52, bw, 52, 12); ctx.fill(); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(x + 12, y - 40); ctx.lineTo(x + 12, y - 34); ctx.lineTo(x + 12 + len, y - 34); ctx.lineTo(x + 12 + len, y - 40);
      ctx.strokeStyle = C.text2; ctx.lineWidth = 1.5; ctx.stroke();
      ctx.font = `11px ${MONO}`; ctx.textAlign = "left"; ctx.fillStyle = C.text2;
      ctx.fillText((nice >= 1000 ? `${nice / 1000} km` : `${nice} m`).toUpperCase().split("").join(" "), x + 12, y - 14);
    }
  };

  // --- the camera: fly from wherever it is to the framing asked for; redraw on anything else
  useEffect(() => {
    const el = ref.current!;
    const dpr = window.devicePixelRatio || 1;
    el.width = Math.round(size.w * dpr); el.height = Math.round(size.h * dpr);
    el.getContext("2d")!.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (!pack || !size.w) return;
    if (appear.current.packId !== pack.id) { appear.current = { packId: pack.id, start: performance.now() }; cam.current = null; }
    const selKey = selected.join(",");
    if (picked.current.key !== selKey) picked.current = { key: selKey, at: performance.now() };
    const target = focus ? frame(focus, k, size.w, size.h, Math.min(140, size.w * 0.14)) : frame(packBox(pack), k, size.w, size.h, Math.max(70, size.w * 0.1));
    const from = cam.current;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const moving = !!from && !reduce && (Math.abs(Math.log(from.scale / target.scale)) > 0.01 || Math.abs(from.lat - target.lat) * target.scale > 2 || Math.abs(from.lon - target.lon) * target.scale > 2);
    const t0 = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const t = moving ? Math.min(1, (now - t0) / CAMERA_MS) : 1, e = ease(t);
      const c: Cam = moving && from
        ? { lat: from.lat + (target.lat - from.lat) * e, lon: from.lon + (target.lon - from.lon) * e, scale: Math.exp(Math.log(from.scale) + (Math.log(target.scale) - Math.log(from.scale)) * e) }
        : target;
      cam.current = c;
      draw(viewOf(c, k, size.w, size.h), now);
      if (t < 1 || now - appear.current.start < 800 || now - picked.current.at < 320) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pack, size, focusKey, k, selected.join(","), selectedTone, customBBox, drag, !!onToggle, p.cells, p.cellM, p.lattice, p.paths, p.rings, p.estimate, p.bestBox, p.scaleBar]);

  const at = (e: React.PointerEvent) => { const r = ref.current!.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
  const view = () => (cam.current ? viewOf(cam.current, k, size.w, size.h) : null);

  return (
    <canvas
      ref={ref} role="img" aria-label={label}
      style={{ cursor: drawing ? "crosshair" : onToggle ? "pointer" : "default", touchAction: drawing ? "none" : undefined }}
      onPointerDown={(e) => {
        if (!drawing) return;
        const pt = at(e);
        e.currentTarget.setPointerCapture(e.pointerId);
        setDrag({ x0: pt.x, y0: pt.y, x1: pt.x, y1: pt.y });
      }}
      onPointerMove={(e) => { if (drag) { const pt = at(e); setDrag({ ...drag, x1: pt.x, y1: pt.y }); } }}
      onPointerUp={(e) => {
        const v = view();
        if (!v || !pack) return;
        const pt = at(e);
        if (drag) {
          setDrag(null);
          if (Math.abs(drag.x1 - drag.x0) > 8 && Math.abs(drag.y1 - drag.y0) > 8 && onDraw) {
            const la = [v.latAt(drag.y0), v.latAt(pt.y)], lo = [v.lonAt(drag.x0), v.lonAt(pt.x)];
            const r5 = (n: number) => Math.round(n * 1e5) / 1e5;
            onDraw([r5(Math.min(...la)), r5(Math.max(...la)), r5(Math.min(...lo)), r5(Math.max(...lo))]);
          }
          return;
        }
        if (onToggle) { const id = regionAt(pack, v.latAt(pt.y), v.lonAt(pt.x)); if (id) onToggle(id); }
      }}
    />
  );
}

/** Where a point is within the pack: the outline, small, with a red square on the place. */
export function Locator({ pack, at }: { pack: Pack; at: LatLon }) {
  const [la0, la1, lo0, lo1] = pack.bbox;
  const k = Math.cos((((la0 + la1) / 2) * Math.PI) / 180), W = 160, H = (W * (la1 - la0)) / ((lo1 - lo0) * k);
  const x = (lon: number) => ((lon - lo0) / (lo1 - lo0)) * W, y = (lat: number) => ((la1 - lat) / (la1 - la0)) * H;
  const d = useMemo(() => pack.regions.features.filter((f) => !f.properties.parent).map((f) =>
    // small islands are dropped and long outlines thinned: this is a thumbnail
    rings(f).filter((r, _, all) => all.length <= 3 || r.length > 12).map((r) => "M" + r.filter((_, i) => r.length < 40 || i % 3 === 0).map(([lon, lat]) => `${x(lon).toFixed(1)} ${y(lat).toFixed(1)}`).join("L") + "Z").join("")).join(""),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [pack.id]);
  return (
    <div className="chip br" style={{ padding: 8, width: 176, boxSizing: "border-box" }}>
      <svg role="img" aria-label={`Position of the estimate within ${pack.name}`} viewBox={`0 0 ${W} ${H}`} style={{ display: "block", width: "100%", height: "auto" }}>
        <path d={d} fill="#2A2A28" stroke={C.dash} strokeWidth="0.8" strokeLinejoin="round" />
        <rect x={x(at[1]) - 4} y={y(at[0]) - 4} width="8" height="8" fill={C.red} />
      </svg>
    </div>
  );
}
