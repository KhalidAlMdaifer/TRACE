// When: the date (required) and a time-of-day window (optional).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, errorText, type Case, type CasePatch } from "../api";
import { Arrow, Field, FileCard } from "../components/bits";
import { PRESETS, presetOf, rangesText, todayISO, toHHMM, toMinutes, zoneName, type Range } from "../format";
import type { Step } from "../steps";
import type { TriageState } from "../useCaseStream";

interface Props { kase: Case; zone: string; triage: TriageState; patch: (p: CasePatch) => Promise<Case>; go: (s: Step) => void }

export function WhenStep({ kase, zone, triage, patch, go }: Props) {
  const [date, setDate] = useState(kase.date_local ?? "");
  const [ranges, setRanges] = useState<Range[] | null>(kase.time_ranges);
  const [error, setError] = useState<string | null>(null);
  const saved = useRef(JSON.stringify([kase.date_local, kase.time_ranges]));
  const dateOk = /^\d{4}-\d{2}-\d{2}$/.test(date) && date <= todayISO();

  // save as the analyst goes, a moment after the last change
  useEffect(() => {
    const key = JSON.stringify([dateOk ? date : kase.date_local, ranges]);
    if (key === saved.current) return;
    const t = setTimeout(() => {
      saved.current = key;
      patch({ ...(dateOk ? { date_local: date } : {}), time_ranges: ranges }).catch(() => setError("That could not be saved. Try again."));
    }, 250);
    return () => clearTimeout(t);
  }, [date, ranges, dateOk, kase.date_local, patch]);

  const preset = presetOf(ranges);
  const single = ranges && ranges.length === 1 && toMinutes(ranges[0][0]) < toMinutes(ranges[0][1]) ? ranges[0] : null;
  const count = useQuery({
    queryKey: ["count", kase.pack_id, date, ranges, null], enabled: dateOk, staleTime: 60_000,
    queryFn: ({ signal }) => api.flightCount(kase.pack_id, date, ranges, null, signal),
    // while a day is being fetched, look again every few seconds: the card shows its progress
    refetchInterval: (q) => (q.state.data?.days.some((d) => d.status === "fetching") ? 4000 : false),
  });
  const qc = useQueryClient();
  const [loadError, setLoadError] = useState<string | null>(null);
  const days = count.data?.days ?? [];
  const fetching = days.filter((d) => d.status === "fetching");
  const absent = days.filter((d) => d.status === "missing" || d.status === "failed");
  const load = async () => {
    setLoadError(null);
    try { for (const d of absent) await api.fetchDay(kase.pack_id, d.utc_date); }
    catch (e) { setLoadError(errorText(e)); }
    qc.invalidateQueries({ queryKey: ["count", kase.pack_id, date] });
  };
  const whole = useQuery({
    queryKey: ["count", kase.pack_id, date, null, null], enabled: dateOk, staleTime: 60_000,
    queryFn: ({ signal }) => api.flightCount(kase.pack_id, date, null, null, signal),
  });

  return (
    <div className="panel-body">
      <FileCard name={kase.media!.filename} durationS={kase.media!.duration_s} triage={triage} />
      <h1>When was it recorded?</h1>
      <Field label="Recording date" htmlFor="rec-date" helper="Required. It cannot be later than the upload date."
             error={date && !dateOk ? "Pick a date that is not in the future." : error}>
        <input id="rec-date" type="date" className={`input${date && !dateOk ? " invalid" : ""}`} value={date} max={todayISO()} required
               onChange={(e) => setDate(e.target.value)} />
      </Field>
      <fieldset style={{ margin: 0, padding: 0, border: 0, minWidth: 0 }}>
        <legend className="mono11" style={{ padding: 0, marginBottom: 10 }}>Time of day</legend>
        <div className="stack gap16">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {PRESETS.map((p) => (
              <button key={p.id} type="button" className="preset" aria-pressed={preset === p.id} onClick={() => setRanges(p.ranges)}>
                {preset === p.id && <span aria-hidden="true" className="sq" />}<span>{p.label}</span>
              </button>
            ))}
          </div>
          <div className="stack gap4">
            <div className="row between" style={{ alignItems: "baseline", gap: 8 }}>
              <span className="tnum" style={{ fontSize: 22, fontWeight: 500, letterSpacing: "-0.01em" }}>{rangesText(ranges)}</span>
              <span className="mono11">{zoneName(zone, date || null)}</span>
            </div>
            <TimeSlider ranges={ranges} single={single} onChange={(r) => setRanges([r])} />
            <div className="ticks"><span>00</span><span>06</span><span>12</span><span>18</span><span>24</span></div>
          </div>
        </div>
      </fieldset>
      <div className="card pad stack gap12" aria-live="polite">
        <div className="row between">
          {!dateOk ? (
            <div className="stack gap4"><span className="mono11">Flights in this window</span><span className="helper" style={{ color: "var(--text-3)" }}>Pick the date to count them</span></div>
          ) : count.data && count.data.flights === 0 && !count.data.days_ready ? (
            <div className="stack gap4"><span className="mono11 bright">Flight data for this date is not loaded</span>
              <span className="helper" style={{ color: "var(--text-3)" }}>A search on this date would find no flights.</span></div>
          ) : (
            <>
              <div className="stack gap4">
                <span className="mono11">Propeller flights in this window</span>
                <span className="helper" style={{ color: "var(--text-3)" }}>
                  {whole.data ? `of ${whole.data.flights} tracked that day` : "counting"}
                  {count.data && !count.data.days_ready ? ". Part of that day is not loaded." : ""}
                </span>
              </div>
              <span className="count">{count.data ? count.data.prop : "–"}</span>
            </>
          )}
        </div>
        {dateOk && fetching.length > 0 && (
          <div className="stack gap8">
            <div role="progressbar" aria-label="Loading flight data" className="bar busy"><div style={{ width: "100%" }} /></div>
            {fetching.map((d) => <div key={d.utc_date} className="mono11 tnum">{d.utc_date} · {d.progress ?? "loading"}</div>)}
            <div className="helper">Each day is about a 4 GB stream and takes several minutes. You can carry on; the count updates when it lands.</div>
          </div>
        )}
        {dateOk && fetching.length === 0 && absent.length > 0 && (
          <div className="stack gap8">
            {absent.filter((d) => d.error).map((d) => <div key={d.utc_date} className="error-line" role="alert">{d.utc_date}: {d.error}</div>)}
            {loadError && <div className="error-line" role="alert">{loadError}</div>}
            <button type="button" className="pill" style={{ minHeight: 44, fontSize: 14 }} onClick={load}>
              Load {absent.length === 1 ? "it" : `${absent.length} days`} (about {absent.length * 4} GB stream, several minutes)
            </button>
            <div className="helper">Not on file: {absent.map((d) => d.utc_date).join(", ")} (UTC days). The data comes from the public adsb.lol archive.</div>
          </div>
        )}
      </div>
      <div className="actions">
        <button type="button" className="pill" disabled title="A case has one recording. Start a new report for another file.">Back</button>
        <button type="button" className="pill primary" disabled={!dateOk}
                onClick={async () => { await patch({ date_local: date, time_ranges: ranges }); go("where"); }}>
          <span>Continue</span><Arrow />
        </button>
      </div>
    </div>
  );
}

/** A two-handle slider on a 24 hour track, in quarter hours. Ranges that wrap midnight (Night) show as two fills. */
function TimeSlider({ ranges, single, onChange }: { ranges: Range[] | null; single: Range | null; onChange: (r: Range) => void }) {
  const track = useRef<HTMLDivElement>(null);
  const [a, b] = single ? [toMinutes(single[0]), toMinutes(single[1])] : [0, 1440];
  const fills: [number, number][] = !ranges ? [[0, 1440]] : ranges.flatMap(([s, e]): [number, number][] => {
    const x = toMinutes(s), y = toMinutes(e);
    return y > x ? [[x, y]] : [[0, y], [x, 1440]];
  });
  const at = (clientX: number) => {
    const r = track.current!.getBoundingClientRect();
    return Math.round((Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * 1440) / 15) * 15;
  };
  const move = (which: 0 | 1, m: number) => {
    const lo = which === 0 ? Math.min(m, b - 15) : a, hi = which === 1 ? Math.max(m, a + 15) : b;
    onChange([toHHMM(lo), toHHMM(hi)]);
  };
  const handle = (which: 0 | 1, value: number, label: string) => (
    <button type="button" className="handle" style={{ left: `${(value / 1440) * 100}%` }}
            role="slider" aria-label={`${label}, ${toHHMM(value)}`} aria-valuemin={0} aria-valuemax={1440} aria-valuenow={value} aria-valuetext={toHHMM(value)}
            onPointerDown={(e) => e.currentTarget.setPointerCapture(e.pointerId)}
            onPointerMove={(e) => { if (e.currentTarget.hasPointerCapture(e.pointerId)) move(which, at(e.clientX)); }}
            onKeyDown={(e) => {
              const d = e.key === "ArrowLeft" || e.key === "ArrowDown" ? -15 : e.key === "ArrowRight" || e.key === "ArrowUp" ? 15 : e.key === "PageDown" ? -60 : e.key === "PageUp" ? 60 : 0;
              if (d) { e.preventDefault(); move(which, Math.max(0, Math.min(1440, value + d))); }
            }}>
      <span />
    </button>
  );
  return (
    <div className="slider" ref={track}>
      <div className="track" />
      {fills.map(([x, y], i) => <div key={i} className="fill" style={{ left: `${(x / 1440) * 100}%`, width: `${((y - x) / 1440) * 100}%` }} />)}
      {handle(0, a, "Start time")}
      {handle(1, b, "End time")}
    </div>
  );
}
