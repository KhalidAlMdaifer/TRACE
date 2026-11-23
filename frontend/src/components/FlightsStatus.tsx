// The header's flight-data icon. Once someone is signed in the page asks the server to bring
// the default region up to the newest published day; this shows the download as it runs.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { api, errorText, type FlightsLatest } from "../api";
import { flightsText } from "../format";

const key = (packId: string | undefined) => ["flights-latest", packId];
const active = (s: FlightsLatest | undefined) => s?.status === "checking" || s?.status === "fetching";

/** Ask once when the page opens signed in, and hourly while it stays open. The server
 *  decides whether anything is fetched: at most one job, and none when the newest day is here. */
export function useFlightsAutoUpdate(packId: string | undefined) {
  const qc = useQueryClient();
  useEffect(() => {
    if (!packId) return;
    const ask = () => api.updateLatest(packId).then((s) => qc.setQueryData(key(packId), s)).catch(() => { /* the icon's own query reports trouble */ });
    ask();
    const t = setInterval(ask, 60 * 60 * 1000);
    return () => clearInterval(t);
  }, [packId, qc]);
}

export function FlightsStatus({ packId }: { packId: string | undefined }) {
  const qc = useQueryClient();
  const id = useId();
  const box = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  const q = useQuery({
    queryKey: key(packId), queryFn: () => api.latest(packId!), enabled: !!packId,
    refetchInterval: (query) => (active(query.state.data) ? 2000 : 30_000),
  });
  const s = q.data;

  // a day that has just landed changes the counts on the When step
  const was = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (was.current === "fetching" && s?.status === "current") qc.invalidateQueries({ queryKey: ["count"] });
    was.current = s?.status;
  }, [s?.status, qc]);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", esc); };
  }, [open]);

  if (!s || s.status === "off") return null;
  const text = flightsText(s);
  const pct = s.fraction == null ? null : Math.round(s.fraction * 100);
  const retry = async () => {
    setRetryError(null);
    try { qc.setQueryData(key(packId), await api.updateLatest(packId!, true)); }
    catch (e) { setRetryError(errorText(e)); }
  };

  return (
    <div className="fdata" ref={box}>
      <button type="button" className={`who fdata-btn ${s.status}`} aria-expanded={open} aria-controls={id}
              aria-label={`${text.title}${pct != null && s.status === "fetching" ? `, ${pct}%` : ""}`} title={text.title}
              onClick={() => setOpen(!open)}>
        <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M8 2.5v7.5" /><path d="M4.75 7l3.25 3.25L11.25 7" /><path d="M3 13.5h10" />
        </svg>
        {s.status === "failed" && <span aria-hidden="true" className="sq" />}
      </button>
      {/* the download bar: a line under the whole header, so it is seen from any step */}
      {active(s) && (
        <span aria-hidden="true" className={`fdata-bar line${pct == null ? " unknown" : ""}`}><span style={pct == null ? undefined : { width: `${Math.max(pct, 2)}%` }} /></span>
      )}
      {/* says when a download starts, ends or fails; not every percent */}
      <span className="sr-only" role="status">{text.title}</span>
      {open && (
        <div id={id} className="fdata-pop card pad">
          <div className="mono11">Flight data · {s.pack_name}</div>
          <div className="row between" style={{ alignItems: "baseline" }}>
            <span style={{ fontSize: 14, fontWeight: 500 }}>{text.title}</span>
            {s.status === "fetching" && pct != null && <span className="mono11 bright tnum">{pct}%</span>}
          </div>
          {active(s) && (
            <div className={`fdata-bar wide${pct == null ? " unknown" : ""}`} role="progressbar" aria-label="Flight data download"
                 aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct ?? undefined}>
              <span style={pct == null ? undefined : { width: `${Math.max(pct, 2)}%` }} />
            </div>
          )}
          {text.lines.map((line) => <div key={line} className="helper">{line}</div>)}
          {retryError && <div className="helper error" role="alert">{retryError}</div>}
          {(s.status === "failed" || s.status === "idle") && <button type="button" className="pill small" onClick={retry}>{s.status === "failed" ? "Try again" : "Check now"}</button>}
        </div>
      )}
    </div>
  );
}
