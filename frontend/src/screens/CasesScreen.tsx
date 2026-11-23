// The analyst's cases: reference, file, date, state, created. A row opens the case where it was left.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { api, errorText, type CaseRow } from "../api";
import { Arrow } from "../components/bits";
import { clock, dateText } from "../format";

const OUTCOMES: Record<string, string> = { located: "Located", candidates: "Candidates", outside: "Match outside the area", not_locatable: "Not locatable" };

function stateText(c: CaseRow): string {
  if (c.status === "searching") return "Searching";
  if (c.state) return OUTCOMES[c.state] + (c.state === "located" && c.band ? `, ${c.band.toLowerCase()}` : "");
  if (c.status === "failed") return "Search stopped";
  if (!c.filename) return "No recording";
  if (!c.date_local) return "Needs a date";
  return c.flyovers >= 2 ? "Ready to review" : `${c.flyovers} of 2 flyovers`;
}

export function CasesScreen({ header, open, newReport }: { header: ReactNode; open: (id: string) => void; newReport: () => void }) {
  const q = useQuery({ queryKey: ["cases"], queryFn: api.cases, refetchInterval: 15_000 });
  const rows = q.data ?? [];
  const qc = useQueryClient();
  const [asking, setAsking] = useState<string | null>(null);        // the case whose deletion is being confirmed
  const [failed, setFailed] = useState<{ id: string; text: string } | null>(null);
  const remove = async (id: string) => {
    setFailed(null);
    try { await api.deleteCase(id); setAsking(null); qc.removeQueries({ queryKey: ["case", id] }); await qc.invalidateQueries({ queryKey: ["cases"] }); }
    catch (e) { setFailed({ id, text: errorText(e) }); }
  };
  return (
    <div className="app">
      <aside className="panel">
        {header}
        <div className="panel-body">
          <div className="stack gap12 topline">
            <h1 tabIndex={-1}>Cases</h1>
            <p className="muted">Every recording you have uploaded, newest first. A search keeps running after you close its page.</p>
          </div>
          <div className="card">
            <div className="card-row"><span className="mono11">Cases</span><span className="v tnum">{q.isPending ? "…" : rows.length}</span></div>
            <div className="card-row"><span className="mono11">Searching now</span><span className="v tnum">{rows.filter((c) => c.status === "searching").length}</span></div>
            <div className="card-row"><span className="mono11">Located</span><span className="v tnum">{rows.filter((c) => c.state === "located").length}</span></div>
          </div>
          <div className="actions">
            <button type="button" className="pill primary" onClick={newReport}><span>New report</span><Arrow /></button>
          </div>
        </div>
      </aside>
      <main className="stage scroll">
        {q.isError ? (
          <div className="notice" role="alert"><p>{errorText(q.error)}</p><button type="button" className="pill" onClick={() => q.refetch()}>Try again</button></div>
        ) : q.isPending ? (
          <div className="notice mono11" aria-busy="true">Loading your cases</div>
        ) : rows.length === 0 ? (
          <div className="notice"><p className="muted">No cases yet. Upload a recording to start one.</p><button type="button" className="pill" onClick={newReport}>New report</button></div>
        ) : (
          <table className="cases">
            <caption className="sr-only">Your cases, newest first</caption>
            <thead><tr><th scope="col">Reference</th><th scope="col">File</th><th scope="col">Recorded</th><th scope="col">State</th><th scope="col">Created</th><th scope="col"><span className="sr-only">Delete</span></th></tr></thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id}>
                  <th scope="row">
                    <a href={`/cases/${c.id}`} onClick={(e) => { e.preventDefault(); open(c.id); }}>{c.case_ref || "No reference yet"}</a>
                  </th>
                  <td>{c.filename ? <>{c.filename}{c.duration_s != null && <span className="dim"> · {clock(c.duration_s)}</span>}</> : <span className="dim">none</span>}</td>
                  <td className="tnum">{c.date_local ? dateText(c.date_local) : <span className="dim">not set</span>}</td>
                  <td><span className={`state${c.state === "located" ? " hit" : ""}`}><span aria-hidden="true" className="sq" />{stateText(c)}</span></td>
                  <td className="tnum dim">{dateText(c.created_at.slice(0, 10))}</td>
                  <td className="row-actions">
                    {asking === c.id ? (
                      <span role="group" aria-label={`Delete ${c.case_ref || c.filename || "this case"}?`}>
                        <span className={failed?.id === c.id ? "error-line" : "dim"} role={failed?.id === c.id ? "alert" : undefined}>
                          {failed?.id === c.id ? failed.text : "Delete with its recording?"}
                        </span>
                        <button type="button" className="link-btn danger" onClick={() => remove(c.id)}>Delete</button>
                        <button type="button" className="link-btn" autoFocus onClick={() => { setAsking(null); setFailed(null); }}>Keep</button>
                      </span>
                    ) : (
                      <button type="button" className="link-btn" onClick={() => { setAsking(c.id); setFailed(null); }}
                              aria-label={`Delete ${c.case_ref || c.filename || "this case"}`}>Delete</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </main>
    </div>
  );
}
