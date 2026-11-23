// Small shared pieces: the mark, icons, the progress row, the file card.
import type { ReactNode } from "react";
import type { Case } from "../api";
import { clock, minutes } from "../format";
import { canEnter, MARKED, markStates, type Step } from "../steps";
import type { TriageState } from "../useCaseStream";

export const Mark = () => (
  <svg aria-hidden="true" width="24" height="24" viewBox="0 0 24 24">
    <path d="M2 4h4M10 4h4M18 4h4M2 12h4M18 12h4M2 20h4M10 20h4M18 20h4" fill="none" stroke="#F4F1E8" strokeWidth="4" />
    <path d="M9 12h6" fill="none" stroke="#FF4D42" strokeWidth="6" />
  </svg>
);

export const Arrow = () => (
  <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 8h10" /><path d="M9 4l4 4-4 4" />
  </svg>
);

export const Minus = ({ dim = false }: { dim?: boolean }) => (
  <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke={dim ? "#8A857C" : "#F4F1E8"} strokeWidth="1.75" strokeLinecap="round"><path d="M3 8h10" /></svg>
);

export const Plus = ({ dim = false }: { dim?: boolean }) => (
  <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke={dim ? "#8A857C" : "#F4F1E8"} strokeWidth="1.75" strokeLinecap="round"><path d="M3 8h10" /><path d="M8 3v10" /></svg>
);

export const Cross = () => (
  <svg aria-hidden="true" width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="#A8A39A" strokeWidth="1.5" strokeLinecap="round"><path d="M3 3l8 8" /><path d="M11 3l-8 8" /></svg>
);

/** The five progress markers. Done steps are links back; later ones are not reachable yet. */
export function StepsNav({ current, kase, go }: { current: Step; kase: Case | null; go: (s: Step) => void }) {
  const states = markStates(current);
  const locked = current === "searching";               // while a search runs, the inputs are not editable
  return (
    <nav aria-label="Progress" className="steps">
      {MARKED.map((m, i) => {
        const label = <><span aria-hidden="true" className="sq" /><span className="mono11">{m.label}</span></>;
        if (states[i] === "current") return <div key={m.id} className="current" aria-current="step">{label}</div>;
        if (!locked && m.id !== "upload" && canEnter(m.id, kase)) return <button key={m.id} type="button" className={states[i]} onClick={() => go(m.id)}>{label}</button>;
        return <div key={m.id} className={states[i]}>{label}</div>;
      })}
    </nav>
  );
}

/** What the file card says while the recording is read and checked (docs/08-design.md, section 7). */
export function triageText(t: TriageState, durationS: number): string {
  if (t.phase === "uploading") return `Uploading · ${Math.round(t.fraction * 100)}%`;
  if (t.phase === "queued" || t.phase === "decoding") return "Reading audio";
  if (t.phase === "failed") return t.message ?? "The recording could not be read.";
  if (t.phase === "detecting") return `${minutes(t.doneS)} of ${minutes(t.totalS || durationS)} min checked · ${t.proposed} proposed`;
  return t.proposed > 0 ? `${t.proposed} proposed` : "None proposed. You can still mark flyovers by hand.";
}

export function FileCard({ name, durationS, triage }: { name: string; durationS: number | null; triage: TriageState }) {
  const total = triage.totalS || durationS || 0;
  const pct = triage.phase === "uploading" ? triage.fraction * 100 : triage.phase === "detecting" && total ? (triage.doneS / total) * 100 : null;
  const text = triageText(triage, durationS ?? 0);
  return (
    <div className="card filecard">
      <span aria-hidden="true" className="play"><svg width="14" height="14" viewBox="0 0 14 14" fill="#F4F1E8"><path d="M4 2.5v9l7.5-4.5z" /></svg></span>
      <div className="stack" style={{ flex: "1 1 auto", minWidth: 0, gap: 6 }}>
        <div className="row between" style={{ gap: 8, fontSize: 14 }}>
          <span className="name">{name}</span>
          {durationS != null && <span className="tnum" style={{ font: "400 12px var(--font-mono)", color: "var(--text-2)" }}>{clock(durationS)}</span>}
        </div>
        {pct != null && (
          <div role="progressbar" aria-label={triage.phase === "uploading" ? "Uploading" : "Checking for flyovers"} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)} className="bar">
            <div style={{ width: `${pct}%` }} />
          </div>
        )}
        <div className={`mono11 row${triage.phase === "failed" ? " red" : pct == null ? " bright" : ""}`} style={{ gap: 8 }} role="status">
          {pct == null && triage.phase !== "failed" && triage.phase !== "done" && <span aria-hidden="true" className="sq" />}
          <span>{text}</span>
        </div>
      </div>
    </div>
  );
}

export const Field = ({ label, htmlFor, children, helper, error }: { label: string; htmlFor: string; children: ReactNode; helper?: string; error?: string | null }) => (
  <div className="stack gap8">
    <label htmlFor={htmlFor} className="mono11">{label}</label>
    {children}
    {(error || helper) && <div className={`helper${error ? " error" : ""}`} role={error ? "alert" : undefined}>{error || helper}</div>}
  </div>
);
