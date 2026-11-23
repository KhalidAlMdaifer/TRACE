// The whole recording as a thin dot-matrix strip, with flyover boxes and their curves on it.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "../api";

export interface StripBox { id: string; t_start: number; t_end: number; f_lo: number; f_hi: number; curve: [number, number][] }

export function Strip({ caseId, duration, boxes, label, height = 80 }: { caseId: string; duration: number; boxes: StripBox[]; label: string; height?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const F0 = 60, F1 = 300, cols = 78, rows = Math.round(height / 4);
  const grid = useQuery({ queryKey: ["strip", caseId, rows], staleTime: Infinity, queryFn: () => api.spectrogram(caseId, { t0: 0, t1: duration, f_lo: F0, f_hi: F1, cols, rows }) });
  useEffect(() => {
    const el = ref.current!, w = el.clientWidth, h = el.clientHeight, dpr = window.devicePixelRatio || 1;
    el.width = w * dpr; el.height = h * dpr;
    const ctx = el.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (grid.data) {
      const bytes = Uint8Array.from(atob(grid.data.data), (c) => c.charCodeAt(0)), cw = w / cols, ch = h / rows;
      for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
        const v = bytes[r * cols + c] / 255;
        ctx.fillStyle = v > 0.6 ? "#C9C5BB" : v > 0.3 ? "#6B6862" : "#3A3A36";
        ctx.globalAlpha = v < 0.1 ? 0.5 : 1;
        ctx.fillRect(c * cw + cw / 2 - 1, h - (r + 1) * ch + ch / 2 - 1, 2, 2);
      }
      ctx.globalAlpha = 1;
    }
    const X = (t: number) => (t / duration) * w, Y = (f: number) => h - ((Math.max(F0, Math.min(F1, f)) - F0) / (F1 - F0)) * h;
    for (const b of boxes) {
      ctx.strokeStyle = "rgba(244,241,232,0.8)"; ctx.lineWidth = 1;
      const x = X(b.t_start), bw = Math.max(6, X(b.t_end) - x);
      ctx.strokeRect(x + 0.5, Y(b.f_hi) + 0.5, bw, Math.max(6, Y(b.f_lo) - Y(b.f_hi)));
      ctx.beginPath();
      b.curve.forEach(([t, f], i) => (i ? ctx.lineTo(X(t), Y(f)) : ctx.moveTo(X(t), Y(f))));
      ctx.strokeStyle = "#FF4D42"; ctx.lineWidth = 1.5; ctx.stroke();
    }
  }, [grid.data, boxes, duration]);
  return <canvas ref={ref} className="strip" style={{ height }} role="img" aria-label={label} />;
}
