// The case's event stream (docs/05-architecture.md, section 8), as state the screens read.
// It starts after the events the case had when it was loaded, so nothing is replayed, and
// the browser's own Last-Event-ID resumes it after a dropped connection.
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { Case, Cell } from "./api";

export interface TriageState {
  phase: "uploading" | "queued" | "decoding" | "detecting" | "done" | "failed";
  fraction: number;          // upload progress, 0..1
  doneS: number; totalS: number; proposed: number;
  message?: string;
}
export interface StageInfo { state: "start" | "done"; detail: string | null }
export interface SearchState {
  jobId: string | null;
  active: boolean;
  stage: string | null;
  stages: Record<string, StageInfo>;
  progress: { stage: string; done: number; total: number } | null;
  cells: Cell[]; scored: boolean;
  error: string | null;
}

const idle: SearchState = { jobId: null, active: false, stage: null, stages: {}, progress: null, cells: [], scored: false, error: null };

/** What the case itself says about triage, before any stream event arrives. */
export function triageFromCase(c: Case | null): TriageState {
  const base = { fraction: 1, doneS: 0, totalS: c?.media?.duration_s ?? 0, proposed: c?.events.proposed ?? 0 };
  const j = c?.job;
  if (!c?.media) return { ...base, phase: "uploading", fraction: 0 };
  if (!c.media.spectrogram_ready) return { ...base, phase: j?.kind === "triage" && j.status === "failed" ? "failed" : "decoding", message: j?.error ?? undefined };
  if (j?.kind === "triage" && (j.status === "running" || j.status === "queued")) return { ...base, phase: "detecting", doneS: (j.progress ?? 0) * base.totalS };
  return { ...base, phase: "done", doneS: base.totalS };
}

export function useCaseStream(kase: Case | null): { triage: TriageState; search: SearchState; connected: boolean } {
  const qc = useQueryClient();
  const caseId = kase?.id ?? null;
  const [triage, setTriage] = useState<TriageState | null>(null);
  const [search, setSearch] = useState<SearchState>(idle);
  const [connected, setConnected] = useState(true);
  const [after] = useState<{ id: string | null; n: number }>({ id: null, n: 0 });

  // Where the stream starts for this case, fixed the first time we see it: the latest job's
  // first event. Its stages and progress are replayed, so a page opened mid-search is up to
  // date, and nothing older comes back.
  if (caseId && after.id !== caseId) { after.id = caseId; after.n = kase!.stream_from; }

  useEffect(() => {
    setTriage(null);
    setSearch(idle);
    if (!caseId) return;
    const es = new EventSource(`/api/cases/${caseId}/stream?after=${after.n}`);
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);          // the browser retries by itself, resuming from the last event
    const refresh = (...keys: string[]) => keys.forEach((k) => qc.invalidateQueries({ queryKey: [k, caseId] }));
    const on = (type: string, fn: (d: any) => void) => es.addEventListener(type, (e) => fn(JSON.parse((e as MessageEvent).data)));

    on("triage", (d) => {
      setTriage((prev) => ({
        phase: d.state === "spectrogram_ready" ? "detecting" : d.state, fraction: 1,
        doneS: d.state === "done" ? (d.total_s ?? prev?.totalS ?? 0) : (d.done_s ?? prev?.doneS ?? 0),
        totalS: d.total_s ?? prev?.totalS ?? 0, proposed: d.events ?? prev?.proposed ?? 0,
      }));
      if (d.state === "spectrogram_ready" || d.state === "done") refresh("case");
    });
    on("proposals", () => refresh("events"));
    // every search event names its job: a new job id means a new search of the same case
    const forJob = (s: SearchState, d: any): SearchState => (d.job_id && d.job_id !== s.jobId ? { ...idle, jobId: d.job_id, active: true } : s);
    on("stage", (d) => setSearch((prev) => {
      const s = forJob(prev, d);
      return { ...s, active: true, error: null, stage: d.state === "start" ? d.stage : s.stage,
               progress: d.state === "start" ? null : s.progress,
               stages: { ...s.stages, [d.stage]: { state: d.state, detail: d.detail ?? s.stages[d.stage]?.detail ?? null } } };
    }));
    on("progress", (d) => typeof d.done === "number" && setSearch((prev) => ({ ...forJob(prev, d), progress: { stage: d.stage, done: d.done, total: d.total } })));
    on("cells", (d) => setSearch((prev) => ({ ...forJob(prev, d), cells: d.points, scored: !!d.scored })));
    on("done", (d) => { setSearch((prev) => ({ ...forJob(prev, d), active: false })); refresh("case", "result"); });
    on("cancelled", () => { setSearch(idle); refresh("case"); });
    on("failed", (d) => {
      if (d.job === "search") setSearch((prev) => ({ ...forJob(prev, d), active: false, error: d.message ?? "The search stopped." }));
      else setTriage((prev) => ({ phase: "failed", fraction: 1, doneS: 0, totalS: prev?.totalS ?? 0, proposed: prev?.proposed ?? 0, message: d.message }));
      refresh("case");
    });
    return () => es.close();
  }, [caseId, qc, after]);

  return { triage: triage ?? triageFromCase(kase), search, connected };
}
