// The HTTP API (docs/05-architecture.md, section 5). JSON everywhere; the session cookie is
// same-origin through the dev proxy.

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

export interface User { id: number; email: string; role: string }
/** Where the result's street map gets its tiles; null when the map is switched off. */
export interface MapTiles { url: string; attribution: string; max_zoom: number; dark: boolean }
export interface Config { app: string; default_pack: string; packs: { id: string; name: string }[]; max_upload_mb: number; max_duration_h: number; map_tiles: MapTiles | null }
export interface RegionFeature {
  type: "Feature";
  properties: { id: string; name: string; parent: string | null };
  geometry: { type: "Polygon"; coordinates: number[][][] } | { type: "MultiPolygon"; coordinates: number[][][][] };
}
export interface Pack {
  id: string; name: string; timezone: string;
  bbox: [number, number, number, number]; // lat_min, lat_max, lon_min, lon_max
  regions: { type: "FeatureCollection"; features: RegionFeature[] };
  grid: [number, number, string][]; grid_pitch_m: number;
  short_name: string;
  /** Where a small region's name sits (in the sea) and the point on land its leader line runs to. */
  labels: Record<string, { at: [number, number]; to: [number, number]; anchor: "start" | "end" }>;
}
export interface Media { id: string; filename: string; sha256: string; size_bytes: number; duration_s: number; spectrogram_ready: boolean }
export interface Job { id: string; kind: "triage" | "search" | "fetch"; status: "queued" | "running" | "done" | "failed" | "cancelled"; stage: string | null; progress: number | null; error: string | null }
export interface ResultSummary { id: string; state: string; band: string | null; strength: number | null; verdict: string | null; p: number | null }
export interface Case {
  id: string; case_ref: string | null; created_at: string; status: string; pack_id: string;
  date_local: string | null; time_ranges: [string, string][] | null; region_ids: string[] | null;
  custom_bbox: [number, number, number, number] | null;
  temperature_c: number | null; temperature_source: string | null;
  temperature_effective: { c: number; source: string } | null;
  media: Media | null; events: { proposed: number; confirmed: number; rejected: number };
  job: Job | null; result: ResultSummary | null; last_event_id: number; stream_from: number;
}
export interface Fit { t_cpa: number; t_cpa_emit: number; f0: number; v: number; d: number; score: number }
export interface FlyoverEvent {
  id: string; source: "detect" | "analyst"; status: "proposed" | "confirmed" | "rejected";
  t_start: number; t_end: number; f_lo: number; f_hi: number; harmonics: number;
  fit: Fit | null; score: number | null; burst: number | null; curve: [number, number][];
}
export interface Box { t_start: number; t_end: number; f_lo: number; f_hi: number; harmonics: number }
export interface SpectrogramGrid { t0: number; t1: number; f_lo: number; f_hi: number; cols: number; rows: number; duration_s: number; db_max: number; data: string }
export interface FlightDay { utc_date: string; status: "ready" | "missing" | "fetching" | "failed"; progress: string | null; error: string | null }
/** Where a region's flight data stands against the newest published day (the header's icon). */
export interface FlightsLatest {
  pack_id: string; pack_name: string; status: "off" | "idle" | "checking" | "fetching" | "current" | "failed";
  utc_date: string | null; newest_on_disk: string | null; fraction: number | null; bytes_total: number | null;
  detail: string | null; error: string | null; checked_at: string | null;
}
export interface FlightCount { flights: number; prop: number; days_ready: boolean; days: FlightDay[] }
export type LatLon = [number, number];
export type Cell = [number, number, number | null];           // lat, lon, score (null: not scored yet)
export interface FlightPath { points: LatLon[]; cpa: LatLon; cpa_alt_m: number; cpa_unix: number }
export interface ResultEvent {
  id: string; role: "pair" | "extra" | "unmatched"; matched: boolean; icao: string | null; type?: string | null;
  t_cpa: number; f0: number; harmonics: number; burst: number; box: [number, number, number, number];
  cpa_time_utc?: string; slant_m?: number; speed_mps?: number; score?: number;
  curve: [number, number][]; curve_kind: string; path?: FlightPath | null;
}
export interface Candidate {
  rank: number; lat: number; lon: number; score: number; icao: [string, string]; types: [string | null, string | null];
  in_area: boolean; in_time: boolean; n_events: number; regions: string[]; radius_m: number; paths: FlightPath[]; refined?: boolean;
}
export interface Estimate { lat: number; lon: number; radius_m: number; refined: boolean; elev_m: number | null; regions: string[]; cell_m: number; cells: Cell[]; lattice: { lat: number; lon: number } }
export interface OutsideMatch extends Candidate { confirmed: boolean; band: string; events: ResultEvent[]; cells: Cell[]; cell_m: number }
export interface Result {
  id: string; created_at: string;
  state: "located" | "candidates" | "outside" | "not_locatable";
  sublabel: "unconfirmed" | "weak" | "too_few_flights" | "needs_third_flyover" | null;
  verdict: { label: string; p: number | null; gap: number | null; tail_width: number | null; n_pairs: number; n_null: number } | null;
  strength: number | null; band: "High" | "Medium" | "Low" | "None"; caps: string[];
  estimate: Estimate | null; clip_start_utc: string | null; clip_start_unix: number | null;
  events: ResultEvent[]; candidates: Candidate[]; shown_rank: number | null; cells: Cell[];
  constraints: { regions: string[] | null; custom_bbox: number[] | null; time_ranges: [string, string][] | null; outside_match: OutsideMatch | null };
  inputs: { file_sha256: string | null; pack: string; date_local: string | null; duration_s: number; temperature_c: number | null; temperature_source: string | null;
            flight_days: string[]; flight_days_missing: string[]; n_flights: number; n_flyovers: number; region_names: Record<string, string>;
            rows_dropped_pct: number | null; temperature_runs: { c: number; score: number | null; pair: string[] | null }[] | null;
            temperature_window: { mean_c: number; min_c: number; max_c: number; hours: number } | null };
  controls: { placebo_days: { utc_date: string; best_score: number; n_pairs: number; n_flights: number }[] | null; placebo_beaten_by?: number };
  not_locatable: { reason: "fewer_than_two_flyovers" | "no_flights" | "no_candidates"; checked: string[]; advice: string[] } | null;
}
export interface CaseRow { id: string; case_ref: string | null; created_at: string; status: string; pack_id: string; date_local: string | null;
  filename: string | null; duration_s: number | null; flyovers: number; state: string | null; band: string | null }
export type CasePatch = Partial<Pick<Case, "date_local" | "time_ranges" | "region_ids" | "custom_bbox" | "temperature_c" | "case_ref">>;

async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const r = await fetch(path, {
    method, signal, credentials: "same-origin",
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    let code = "error", message = r.statusText;
    try {
      const j = await r.json();
      code = j.error?.code ?? code;
      message = j.error?.message ?? message;
    } catch { /* not JSON */ }
    if (r.status === 401 && !path.startsWith("/api/auth/")) window.dispatchEvent(new Event("trace:signed-out"));
    throw new ApiError(r.status, code, message);
  }
  return r.json() as Promise<T>;
}

const q = (params: Record<string, string | number | undefined | null>) => {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") s.set(k, String(v));
  return s.toString();
};

export const api = {
  me: () => request<{ user: User }>("GET", "/api/auth/me"),
  login: (email: string, password: string) => request<{ user: User }>("POST", "/api/auth/login", { email, password }),
  logout: () => request<{ ok: boolean }>("POST", "/api/auth/logout"),
  config: () => request<Config>("GET", "/api/config"),
  pack: (id: string) => request<Pack>("GET", `/api/packs/${id}`),
  flightCount: (pack: string, date: string, ranges: [string, string][] | null, regions: string[] | null, signal?: AbortSignal) =>
    request<FlightCount>("GET", `/api/flights/count?${q({ pack, date, ranges: ranges?.map((r) => r.join("-")).join(","), regions: regions?.join(",") })}`, undefined, signal),
  fetchDay: (pack: string, utc_date: string) => request<FlightDay>("POST", `/api/packs/${pack}/days`, { utc_date }),
  latest: (pack: string) => request<FlightsLatest>("GET", `/api/packs/${pack}/latest`),
  updateLatest: (pack: string, force = false) => request<FlightsLatest>("POST", `/api/packs/${pack}/latest`, { force }),
  cases: () => request<CaseRow[]>("GET", "/api/cases"),
  createCase: (pack_id?: string) => request<{ id: string }>("POST", "/api/cases", pack_id ? { pack_id } : {}),
  getCase: (id: string) => request<Case>("GET", `/api/cases/${id}`),
  deleteCase: (id: string) => request<{ ok: boolean }>("DELETE", `/api/cases/${id}`),
  patchCase: (id: string, patch: CasePatch) => request<Case>("PATCH", `/api/cases/${id}`, patch),
  events: (id: string) => request<FlyoverEvent[]>("GET", `/api/cases/${id}/events`),
  createEvent: (id: string, box: Box, signal?: AbortSignal) => request<FlyoverEvent>("POST", `/api/cases/${id}/events`, box, signal),
  patchEvent: (id: string, eid: string, patch: Partial<Box> & { status?: FlyoverEvent["status"] }, signal?: AbortSignal) =>
    request<FlyoverEvent>("PATCH", `/api/cases/${id}/events/${eid}`, patch, signal),
  deleteEvent: (id: string, eid: string) => request<{ ok: boolean }>("DELETE", `/api/cases/${id}/events/${eid}`),
  spectrogram: (id: string, w: { t0: number; t1: number; f_lo: number; f_hi: number; cols: number; rows: number }, signal?: AbortSignal) =>
    request<SpectrogramGrid>("GET", `/api/cases/${id}/spectrogram?${q(w)}`, undefined, signal),
  startSearch: (id: string) => request<{ job_id: string }>("POST", `/api/cases/${id}/search`),
  cancelSearch: (id: string) => request<{ ok: boolean }>("DELETE", `/api/cases/${id}/search`),
  notLocatable: (id: string) => request<{ job_id: string }>("POST", `/api/cases/${id}/not-locatable`),
  result: (id: string) => request<Result>("GET", `/api/cases/${id}/result`),
};

/** Upload with progress. XMLHttpRequest, because fetch cannot report upload progress. */
export function uploadMedia(caseId: string, file: File, onProgress: (fraction: number) => void): Promise<{ media: Media }> {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", `/api/cases/${caseId}/media`);
    x.withCredentials = true;
    x.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    x.onerror = () => reject(new ApiError(0, "network", "The upload was interrupted. Check the connection and try again."));
    x.onload = () => {
      let j: any = null;
      try { j = JSON.parse(x.responseText); } catch { /* not JSON */ }
      if (x.status >= 200 && x.status < 300 && j) resolve(j);
      else reject(new ApiError(x.status, j?.error?.code ?? "error", j?.error?.message ?? "The upload failed."));
    };
    const form = new FormData();
    form.append("file", file);
    x.send(form);
  });
}

/** What to say for an error. The server's message is already written for the analyst. */
export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === "no_audio") return "That file has no audio track.";
    if (e.code === "not_media") return "That file is not audio or video we can read.";
    return e.message;
  }
  return "Something went wrong. Try again.";
}
