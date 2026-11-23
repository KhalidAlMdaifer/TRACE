// One page: a panel that changes with the step, and a stage (the map, or the spectrogram).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, errorText, type Case, type CasePatch, type Pack, type User } from "./api";
import { Mark, StepsNav } from "./components/bits";
import { Select } from "./components/Select";
import { DotMap } from "./components/DotMap";
import { FlightsStatus, useFlightsAutoUpdate } from "./components/FlightsStatus";
import { CasesScreen } from "./screens/CasesScreen";
import { FlyoversStep } from "./screens/FlyoversStep";
import { ReviewStep } from "./screens/ReviewStep";
import { ResultStep } from "./screens/ResultStep";
import { SearchingStep } from "./screens/SearchingStep";
import { SignIn } from "./screens/SignIn";
import { UploadStep } from "./screens/UploadStep";
import { WhenStep } from "./screens/WhenStep";
import { WhereStep } from "./screens/WhereStep";
import { backOf, caseUrl, parseLocation, resolveStep, STEP_TITLES, type Step } from "./steps";
import { useCaseStream, type TriageState } from "./useCaseStream";

function useLocation() {
  const read = () => parseLocation(window.location.pathname, window.location.hash);
  const [loc, setLoc] = useState(read);
  useEffect(() => {
    const on = () => setLoc(read());
    window.addEventListener("popstate", on);
    window.addEventListener("hashchange", on);
    return () => { window.removeEventListener("popstate", on); window.removeEventListener("hashchange", on); };
  }, []);
  const navigate = useCallback((url: string, replace = false) => {
    window.history[replace ? "replaceState" : "pushState"](null, "", url);
    setLoc(read());
  }, []);
  return { ...loc, navigate };
}

export function App() {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  // any request answered 401 means the session has ended: go back to sign-in
  useEffect(() => {
    const on = () => qc.invalidateQueries({ queryKey: ["me"] });
    window.addEventListener("trace:signed-out", on);
    return () => window.removeEventListener("trace:signed-out", on);
  }, [qc]);
  if (me.isPending) return <div className="app" aria-busy="true" />;
  if (me.isError || !me.data) return <SignIn onDone={() => qc.invalidateQueries({ queryKey: ["me"] })} />;
  return <Workspace user={me.data.user} onSignedOut={() => { qc.clear(); qc.invalidateQueries({ queryKey: ["me"] }); }} />;
}

function Workspace({ user, onSignedOut }: { user: User; onSignedOut: () => void }) {
  const qc = useQueryClient();
  const { caseId, step: wanted, list, navigate } = useLocation();
  const config = useQuery({ queryKey: ["config"], queryFn: api.config, staleTime: Infinity });
  const caseQ = useQuery({ queryKey: ["case", caseId], queryFn: () => api.getCase(caseId!), enabled: !!caseId });
  const kase: Case | null = caseId ? caseQ.data ?? null : null;
  const [chosenPack, setChosenPack] = useState<string | null>(null);      // for the next upload; a case keeps its own
  const packId = kase?.pack_id ?? chosenPack ?? config.data?.default_pack;
  const pack = useQuery({ queryKey: ["pack", packId], queryFn: () => api.pack(packId!), enabled: !!packId, staleTime: Infinity }).data;
  const { triage, search, connected } = useCaseStream(kase);
  // signed in: bring the default region's flight data up to the newest published day, in the background
  useFlightsAutoUpdate(config.data?.default_pack);
  const [upload, setUpload] = useState<{ name: string; fraction: number } | null>(null);
  const [drawing, setDrawing] = useState(false);

  const missing = !!caseId && caseQ.isError && (caseQ.error as ApiError).status === 404;
  const loadingCase = !!caseId && caseQ.isPending;
  const step: Step = loadingCase ? "upload" : resolveStep(wanted, kase);

  // keep the address in step with what is shown
  useEffect(() => {
    if (missing) navigate("/", true);
    else if (caseId && kase && wanted !== step) navigate(caseUrl(caseId, step), true);
  }, [missing, caseId, kase, wanted, step, navigate]);
  useEffect(() => { if (step !== "where") setDrawing(false); }, [step]);
  // each step is a new page to a screen reader: name it in the title and move focus to its heading
  const shown = list ? "Cases" : STEP_TITLES[step];
  useEffect(() => {
    document.title = `${shown} · TRACE`;
    const h = document.querySelector<HTMLElement>(".panel h1");
    if (h && document.activeElement !== h) { h.tabIndex = -1; h.focus({ preventScroll: true }); }
  }, [shown, caseId]);

  const go = (s: Step) => caseId && navigate(caseUrl(caseId, s));
  const patch = async (p: CasePatch) => {
    const updated = await api.patchCase(caseId!, p);
    qc.setQueryData(["case", caseId], updated);
    return updated;
  };
  const signOut = async () => { try { await api.logout(); } finally { onSignedOut(); } };

  const shownTriage: TriageState = upload ? { phase: "uploading", fraction: upload.fraction, doneS: 0, totalS: 0, proposed: 0 } : triage;
  const zone = pack?.timezone ?? "UTC";
  const selected = kase?.region_ids ?? [];
  const mapLabel = pack ? `Dot-matrix map of ${pack.name}` + (selected.length ? `, with ${selected.join(", ")} selected in red` : "") : "Map";

  let panel = null;
  const failed = !!caseId && caseQ.isError && !missing;
  if (failed) {
    panel = (
      <div className="panel-body">
        <div className="stack gap12 topline"><h1>The case could not be opened</h1><p className="muted" role="alert">{errorText(caseQ.error)}</p></div>
        <div className="actions"><button type="button" className="pill" onClick={() => navigate("/cases")}>Cases</button>
          <button type="button" className="pill primary" onClick={() => caseQ.refetch()}>Try again</button></div>
      </div>
    );
  } else if (loadingCase) panel = <div className="panel-body" aria-busy="true"><div className="mono11">Opening the case</div></div>;
  else if (step === "upload" || !kase) {
    panel = <UploadStep config={config.data} packId={packId} upload={upload} onProgress={setUpload}
                        onUploaded={(id) => { qc.invalidateQueries({ queryKey: ["case", id] }); navigate(caseUrl(id, "when")); setUpload(null); }} />;
  } else if (step === "when") panel = <WhenStep kase={kase} zone={zone} triage={shownTriage} patch={patch} go={go} />;
  else if (step === "where") panel = <WhereStep kase={kase} pack={pack} triage={shownTriage} patch={patch} go={go} drawing={drawing} setDrawing={setDrawing} />;
  else if (step === "review") panel = <ReviewStep kase={kase} pack={pack} zone={zone} patch={patch} go={go} refresh={() => qc.refetchQueries({ queryKey: ["case", caseId] })} />;

  // one back arrow on every page: the step before, the cases list from a case's first step, a new report from the list
  const before = list || !caseId ? null : failed || loadingCase || !kase ? "cases" : backOf(step, kase);
  const back = list ? { label: "New report", go: () => navigate("/") }
    : before === "cases" ? { label: "Cases", go: () => navigate("/cases") }
    : before ? { label: STEP_TITLES[before], go: () => go(before) } : null;
  const header = <Header user={user} back={back} flightsPack={config.data?.default_pack} signOut={signOut} home={() => navigate("/")} cases={() => navigate("/cases")} onCases={list} />;
  if (list) return <CasesScreen header={header} open={(id) => navigate(`/cases/${id}`)} newReport={() => navigate("/")} />;
  if (failed) return <div className="app"><aside className="panel">{header}{panel}</aside><main className="stage"><DotMap pack={pack} label="Map" /></main></div>;
  if (step === "searching" && kase && !loadingCase) return <SearchingStep kase={kase} pack={pack} search={search} connected={connected} go={go} header={header} />;
  if (step === "result" && kase && !loadingCase) return <ResultStep kase={kase} pack={pack} go={go} newReport={() => navigate("/")} header={header} />;
  if (step === "flyovers" && kase && !loadingCase) {
    return (
      <FlyoversStep kase={kase} triage={shownTriage} go={go}
                    finish={async () => { await api.notLocatable(kase.id); await qc.refetchQueries({ queryKey: ["case", caseId] }); go("searching"); }}
                    header={header}
                    nav={<StepsNav current={step} kase={kase} go={go} />} />
    );
  }

  return (
    <div className="app">
      <aside className="panel">
        {header}
        <StepsNav current={step} kase={kase} go={go} />
        {panel}
      </aside>
      <main className="stage">
        <DotMap pack={pack} selected={step === "upload" ? [] : selected} label={mapLabel}
                onToggle={step === "where" && !drawing ? (id) => toggleRegion(kase, pack, id, patch) : undefined}
                customBBox={step === "upload" ? null : kase?.custom_bbox} drawing={drawing}
                onDraw={(bbox) => { setDrawing(false); patch({ custom_bbox: bbox }); }} />
        {step === "upload" && (
          <div className="chip col tr mono11">
            <div><span aria-hidden="true" className="sq" style={{ background: "var(--dot-2)" }} /><span>Search cell</span></div>
            <div><span aria-hidden="true" className="sq" /><span>Cell that matches</span></div>
          </div>
        )}
        {step !== "upload" && (selected.length > 0 || kase?.custom_bbox) && (
          <div className="chip tr mono11"><span aria-hidden="true" className="sq" /><span>Your selected area</span></div>
        )}
        {step === "where" && kase && (
          <div className="corner br">
            {kase.custom_bbox && !drawing && <button type="button" className="pill small" onClick={() => patch({ custom_bbox: null })}>Clear custom area</button>}
            <button type="button" className="pill small" aria-pressed={drawing} onClick={() => setDrawing(!drawing)}>
              <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#A8A39A" strokeWidth="1.5" strokeDasharray="3 2"><rect x="2" y="3" width="12" height="10" /></svg>
              <span>{drawing ? "Drag on the map, or cancel" : "Draw a custom area"}</span>
            </button>
          </div>
        )}
        {step === "upload" && pack && ((config.data?.packs.length ?? 0) > 1 ? (
          <Select className="chip bl" label="Region" value={packId} options={config.data!.packs} disabled={!!upload} onChange={setChosenPack} />
        ) : <div className="mono11 dim" style={{ position: "absolute", left: 20, bottom: 30 }}>{pack.name}</div>)}
      </main>
    </div>
  );
}

/** Add or remove a region from the case's area. Choosing a parent drops its sub-areas, and the reverse. */
export function toggleRegion(kase: Case | null, pack: Pack | undefined, id: string, patch: (p: CasePatch) => Promise<Case>) {
  if (!kase) return;
  const cur = kase.region_ids ?? [];
  const parentOf = (r: string) => pack?.regions.features.find((f) => f.properties.id === r)?.properties.parent ?? null;
  const next = cur.includes(id)
    ? cur.filter((r) => r !== id)
    : [...cur.filter((r) => parentOf(r) !== id && r !== parentOf(id)), id];      // a whole region or its parts, not both
  patch({ region_ids: next.length ? next : null });
}

interface HeaderProps { user: User; back?: { label: string; go: () => void } | null; flightsPack?: string; signOut: () => void; home: () => void; cases: () => void; onCases?: boolean }

export function Header({ user, back = null, flightsPack, signOut, home, cases, onCases = false }: HeaderProps) {
  return (
    <header className="header">
      <div className="row" style={{ gap: 8, minWidth: 0 }}>
        {back && (
          <button type="button" className="back-btn" onClick={back.go} aria-label={`Back to ${back.label}`} title={`Back to ${back.label}`}>
            <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><path d="M13 8H3" /><path d="M7 4L3 8l4 4" /></svg>
          </button>
        )}
        <a className="brand" href="/" onClick={(e) => { e.preventDefault(); home(); }} aria-label="TRACE, new report"><Mark /><span>TRACE</span></a>
      </div>
      <nav aria-label="Account" className="row">
        <FlightsStatus packId={flightsPack} />
        <a className="who mono11" href="/cases" aria-current={onCases ? "page" : undefined} onClick={(e) => { e.preventDefault(); cases(); }}>Cases</a>
        <button type="button" className="who mono11" onClick={signOut} title={`Signed in as ${user.email}`} aria-label={`Sign out ${user.email}`}>Sign out</button>
      </nav>
    </header>
  );
}
