// Searching: named stages from the stream, and the map filling in as the search narrows.
import { useMemo, useState, type ReactNode } from "react";
import { api, type Case, type Pack } from "../api";
import { boxAround, DotMap, type Ring } from "../components/DotMap";
import { coords, dateText, metresBetween } from "../format";
import type { Step } from "../steps";
import type { SearchState } from "../useCaseStream";

const STAGES: [string, string][] = [["fits", "Flyovers fitted"], ["flights", "Flights loaded"], ["join", "Pairing flights"], ["lattice", "Laying search points"],
  ["scoring", "Scoring"], ["extras", "Extra flyovers"], ["refine", "Refining to 50 m"]];

export const caseLine = (kase: Case) => [kase.case_ref, kase.media?.filename, kase.date_local ? dateText(kase.date_local) : null].filter(Boolean).join(" · ");

interface Props { kase: Case; pack: Pack | undefined; search: SearchState; connected: boolean; go: (s: Step) => void; header: ReactNode }

export function SearchingStep({ kase, pack, search, connected, go, header }: Props) {
  const [cancelling, setCancelling] = useState(false);
  // the stream only says what happened since the page opened its replay; the job row says where the search is now
  const now = STAGES.findIndex(([id]) => id === (search.stage ?? kase.job?.stage));
  const regions = pack?.regions.features ?? [];
  const area = (kase.region_ids ?? []).map((id) => regions.find((f) => f.properties.id === id)?.properties.name ?? id).join(", ");

  // the leading candidates: the best scored points, each at least 2 km from a better one
  const leads = useMemo(() => {
    if (!search.scored) return [];
    const out: [number, number, number][] = [];
    for (const c of search.cells) {
      if (c[2] == null) continue;
      if (out.every((o) => metresBetween([o[0], o[1]], [c[0], c[1]]) > 2000)) out.push([c[0], c[1], c[2]]);
      if (out.length === 3) break;
    }
    return out;
  }, [search.cells, search.scored]);
  const best = leads[0];
  const bestBox = best ? boxAround(best[0], best[1], 2500) : null;
  const rings: Ring[] = leads.map(([lat, lon]) => ({ lat, lon, kind: "lead" }));
  const label = pack ? `Dot-matrix map of ${pack.name}. Each dot is a search point; brighter red means a better match, and rings mark the leading candidates` : "Map";

  return (
    <div className="app">
      <aside className="panel">
        {header}
        <div className="panel-body">
          <div className="stack gap12 topline">
            <div className="mono11">{caseLine(kase)}</div>
            <h1>Searching {pack ? (pack.short_name === pack.name ? pack.name : `the ${pack.short_name}`) : ""}</h1>
            <p className="muted">{area ? `Your area, ${area}, ranks the matches. ` : ""}You can close this page; the report keeps running in your case.</p>
          </div>
          <ol aria-label="Search stages" className="stages">
            {[...STAGES, ...(search.stages.controls ? [["controls", "Other days as a control"] as [string, string]] : [])].map(([id, text], i) => {
              const info = search.stages[id];
              const done = info?.state === "done" || (now >= 0 && i < now);
              const active = !done && (info?.state === "start" || i === now);
              const pr = active && search.progress?.stage === id ? search.progress : null;
              const pct = pr && pr.total ? Math.round((pr.done / pr.total) * 100) : null;
              if (active) return (
                <li key={id} className="active" aria-current="step">
                  <div className="row" style={{ gap: 14 }}>
                    <span aria-hidden="true" className="sq halo" /><span style={{ flex: "1 1 auto", fontWeight: 600 }}>{text}</span>
                    <span className="val red tnum">{pct != null ? `${pct}%` : pr ? `${pr.done} of ${pr.total}` : "Working"}</span>
                  </div>
                  <div role="progressbar" aria-label={`${text} progress`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct ?? undefined} className={`bar${pct == null ? " busy" : ""}`}>
                    <div style={{ width: `${pct ?? 100}%` }} />
                  </div>
                </li>
              );
              return (
                <li key={id} className={done ? "done" : "waiting"}>
                  <span aria-hidden="true" className="sq" /><span style={{ flex: "1 1 auto" }}>{text}</span>
                  <span className="val tnum">{done ? info?.detail ?? "Done" : "Waiting"}</span>
                </li>
              );
            })}
          </ol>
          <div className="card best" aria-live="polite">
            <div className="stack" style={{ gap: 2 }}>
              <span style={{ fontWeight: 600 }}>Best match so far</span>
              <span className="helper tnum">{best ? `${coords(best[0], best[1])} · score ${best[2].toFixed(1)}` : "Updates as the search narrows"}</span>
            </div>
          </div>
          {!connected && !search.error && <div className="helper" role="status">The connection dropped. Reconnecting; the search carries on meanwhile.</div>}
          {search.error && <div className="error-line" role="alert">The search stopped: {search.error} Nothing was lost; start it again from Review.</div>}
          <div className="actions">
            {search.error ? (
              <button type="button" className="pill" style={{ flex: "1 1 auto" }} onClick={() => go("review")}>Back to Review</button>
            ) : (
              <button type="button" className="pill" style={{ flex: "1 1 auto" }} disabled={cancelling}
                      onClick={async () => { setCancelling(true); try { await api.cancelSearch(kase.id); } finally { go("review"); } }}>
                {cancelling ? "Cancelling" : "Cancel search"}
              </button>
            )}
          </div>
        </div>
      </aside>
      <main className="stage">
        <DotMap pack={pack} selected={kase.region_ids ?? []} customBBox={kase.custom_bbox} label={label}
                cells={search.cells} cellM={200} rings={rings} bestBox={bestBox} focus={best ? boxAround(best[0], best[1], 30_000) : null} />
        <div className="chip col tr mono11">
          <div><span aria-hidden="true" className="ramp"><i style={{ opacity: 0.3 }} /><i style={{ opacity: 0.6 }} /><i /></span><span>Match strength, low to high</span></div>
          <div><span aria-hidden="true" className="swatch-ring" style={{ borderColor: "var(--red)" }} /><span>Leading candidates</span></div>
          <div><span aria-hidden="true" className="swatch-box" style={{ border: "1px dashed var(--text)" }} /><span>Best area so far</span></div>
          {(kase.region_ids?.length || kase.custom_bbox) && <div><span aria-hidden="true" className="sq" style={{ opacity: 0.6 }} /><span>Your selected area</span></div>}
        </div>
      </main>
    </div>
  );
}
