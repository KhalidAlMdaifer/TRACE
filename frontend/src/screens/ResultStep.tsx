// The outcome: Located, Candidates, a match outside the stated constraints, or Not locatable.
// Every one is a lead with its working shown (docs/06-confidence.md); never a bare pin.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { api, type Candidate, type Case, type Pack, type Result, type ResultEvent } from "../api";
import { Arrow } from "../components/bits";
import { boxAround, DotMap, Locator, type MapPath, type Ring } from "../components/DotMap";
import { LocationMap } from "../components/LocationMap";
import { Strip } from "../components/Strip";
import { clock, coords, distance, googleMapsUrl, localClock, metresBetween, pText, SOURCES, zoneName } from "../format";
import { failedSearchNote, type Step } from "../steps";
import { caseLine } from "./SearchingStep";

interface Props { kase: Case; pack: Pack | undefined; go: (s: Step) => void; newReport: () => void; header: ReactNode }

const NUMBER_WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six"];
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** A number that counts up to its value once, over about 0.7 s. Plain when motion is reduced. */
function useCountUp(value: number | null): number | null {
  const [shown, setShown] = useState<number | null>(value == null ? null : 0);
  useEffect(() => {
    if (value == null) { setShown(null); return; }
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { setShown(value); return; }
    const t0 = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - t0) / 700);
      setShown(Math.round(value * (1 - Math.pow(1 - t, 3))));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  return shown;
}

function Confidence({ r, located }: { r: Result; located: boolean }) {
  const counted = useCountUp(r.strength);
  const v = r.verdict, n = counted == null ? 0 : Math.round(counted / 5);
  const lead = v && v.gap != null && v.tail_width ? `${(v.gap / v.tail_width).toFixed(1)} tail widths` : null;
  const flyovers = r.events.filter((e) => e.matched).length || r.inputs.n_flyovers;
  const temp = r.inputs.temperature_c != null ? `${r.inputs.temperature_c} °C, ${SOURCES[r.inputs.temperature_source ?? ""] ?? r.inputs.temperature_source}` : "not known";
  return (
    <section aria-label="Confidence" className="card stack" style={{ gap: 14, padding: 16 }}>
      <div className="row between" style={{ alignItems: "flex-end" }}>
        <div className="stack gap4">
          <span className="mono11">Confidence</span>
          <span style={{ fontSize: 26, fontWeight: 500, lineHeight: 1.1, letterSpacing: "-0.02em", color: located && r.band === "High" ? "var(--red)" : undefined }}>
            {located && r.band === "Medium" ? "Medium" : r.band === "None" ? "None" : r.band}
          </span>
        </div>
        {r.strength != null
          ? <div className="tnum" aria-label={`${r.strength} out of 100`} style={{ fontSize: 40, fontWeight: 500, lineHeight: 1, letterSpacing: "-0.03em" }}>{counted}<span className="mono11" style={{ fontSize: 12 }}> / 100</span></div>
          : <div className="mono11" style={{ textAlign: "right", maxWidth: 150 }}>Match strength not shown</div>}
      </div>
      {r.strength != null && (
        <div role="img" aria-label={`Match strength ${r.strength} out of 100`} className="meter">
          {Array.from({ length: 20 }, (_, i) => <span key={i} className={i < n ? "on" : ""} />)}
        </div>
      )}
      <ul className="facts">
        {v && <li><span>Verdict against {v.n_null.toLocaleString()} wrong pairs</span><span>{v.label === "insufficient" ? "Too few to judge" : `${cap(v.label)}, ${pText(v.p)}`}</span></li>}
        {located && lead && <li><span>Lead over the best wrong pair</span><span className="tnum">{lead}</span></li>}
        <li><span>Flyovers used</span><span>{flyovers}{located ? ", on one clock" : ""}</span></li>
        {located && r.estimate && <li><span>Uncertainty radius</span><span className="tnum">{distance(r.estimate.radius_m)}</span></li>}
        <li><span>Air temperature</span><span>{temp}</span></li>
        {r.inputs.temperature_runs && <li><span>Searched at</span><span>{r.inputs.temperature_runs.map((t) => `${t.c} °C`).join(" and ")}</span></li>}
        {r.inputs.rows_dropped_pct != null && <li><span>Track points failing integrity checks</span><span className="tnum">{r.inputs.rows_dropped_pct}%</span></li>}
        {r.controls.placebo_days && r.controls.placebo_days.length > 0 && (
          <li><span>Other days as a control</span><span>beat {r.controls.placebo_days.length - (r.controls.placebo_beaten_by ?? 0)} of {r.controls.placebo_days.length}</span></li>
        )}
        {r.inputs.flight_days_missing.length > 0 && <li><span>Flight days not on file</span><span className="tnum">{r.inputs.flight_days_missing.join(", ")}</span></li>}
      </ul>
      {located && r.band === "Medium" && <p className="helper">Located, weak: about one in ten results at this strength is expected to be wrong.</p>}
      {r.caps.map((c) => <p key={c} className="helper">{cap(c.replace(/^[a-z]+: /, ""))}.</p>)}
    </section>
  );
}

function Actions({ kase, children }: { kase: Case; children: ReactNode }) {
  return <div className="stack gap12" style={{ marginTop: "auto" }}>{children}<span className="sr-only">Case {kase.case_ref}</span></div>;
}

const ExportReport = ({ kase, primary = false }: { kase: Case; primary?: boolean }) => (
  <a className={`pill${primary ? " primary" : ""}`} style={{ flex: "1 1 auto", padding: "0 16px" }} href={`/api/cases/${kase.id}/report`} target="_blank" rel="noreferrer">
    <span>Export report</span>{primary && <Arrow />}
  </a>
);

export function ResultStep({ kase, pack, go, newReport, header }: Props) {
  const q = useQuery({ queryKey: ["result", kase.id, kase.result?.id], queryFn: () => api.result(kase.id), enabled: !!kase.result });
  // a located result is drawn on street tiles when the server names a tile host
  const tiles = useQuery({ queryKey: ["config"], queryFn: api.config, staleTime: Infinity }).data?.map_tiles ?? null;
  const [picked, setPicked] = useState<number | null>(null);         // a candidate's rank
  const [showOutside, setShowOutside] = useState(false);
  const [alternates, setAlternates] = useState(false);
  const r = q.data;
  const zone = pack?.timezone ?? "UTC";
  const names = r?.inputs.region_names ?? {};
  const regionName = (ids: string[]) => { const top = ids.find((id) => pack?.regions.features.find((f) => f.properties.id === id && !f.properties.parent)) ?? ids[0]; return top ? names[top] ?? top : "Outside every listed area"; };
  const duration = kase.media?.duration_s ?? r?.inputs.duration_s ?? 0;

  if (!r || !pack) {
    return (
      <div className="app"><aside className="panel">{header}<div className="panel-body"><div className="topline mono11" aria-busy="true">{q.isError ? "The result could not be loaded. Reload the page." : "Opening the result"}</div></div></aside>
        <main className="stage"><DotMap pack={pack} selected={kase.region_ids ?? []} label="Map" /></main></div>
    );
  }

  const om = r.constraints.outside_match;
  const outsideConfirmed = !!om?.confirmed;
  // what the panel is about: the stated-constraints result, or the outside match when the analyst asks for it
  const viewingOutside = r.state === "outside" && !!om && (showOutside || r.estimate == null);
  const located = r.state === "located" || (viewingOutside && outsideConfirmed);
  const events: ResultEvent[] = viewingOutside ? om!.events : r.events;
  const point = viewingOutside ? om! : r.estimate;
  const clipStart = viewingOutside || r.clip_start_unix == null ? null : r.clip_start_unix;
  const banner = r.state === "outside" && om && r.estimate != null && (
    <div className="banner" role="status">
      <span style={{ fontSize: 14 }}>{showOutside ? "This match lies outside your area or time." : outsideConfirmed ? "A confirmed match lies outside your area" : "A stronger match lies outside your area"}</span>
      <button type="button" className="link-btn" style={{ padding: "12px 0 12px 12px" }} onClick={() => { setShowOutside(!showOutside); setPicked(null); }}>{showOutside ? "Back to your area" : "Show it"}</button>
    </div>
  );
  // the newest search failed: say so, so this earlier result is not taken for its answer
  const failedNote = failedSearchNote(kase);
  const stale = failedNote && (
    <div className="banner" role="alert">
      <span className="error-line" style={{ fontSize: 14 }}>{failedNote}</span>
      <button type="button" className="link-btn" style={{ padding: "12px 0 12px 12px", whiteSpace: "nowrap" }} onClick={() => go("review")}>Search again</button>
    </div>
  );
  const stripBoxes = events.map((e) => ({ id: e.id, t_start: e.box[0], t_end: e.box[1], f_lo: e.box[2], f_hi: e.box[3], curve: e.curve }));
  const paths = (list: ResultEvent[]): MapPath[] => list.filter((e) => e.path).map((e, i) => ({ ...e.path!, label: `Flight ${i + 1}` }));
  const areaChip = (kase.region_ids?.length || kase.custom_bbox) ? <div><span aria-hidden="true" className="sq" style={{ opacity: 0.6 }} /><span>Your selected area</span></div> : null;

  // ----------------------------------------------------------------------------------------- not locatable
  if (r.state === "not_locatable" && r.not_locatable) {
    const nl = r.not_locatable, n = r.inputs.n_flyovers;
    const why = nl.reason === "fewer_than_two_flyovers"
      ? (n === 0 ? "No aircraft flyover was found in this recording, so there is nothing to match against flight data."
                 : "Only one flyover was confirmed in this recording. A search needs two, heard on the same clock.")
      : nl.reason === "no_flights" ? "No propeller flights are on file for that date, so there is nothing to match the flyovers against."
      : "No place fits both flyovers on that date.";
    return (
      <div className="app">
        <aside className="panel">
          {header}
          <div className="panel-body">
            {stale}
            <div className="stack gap12 topline">
              <div className="mono11">{caseLine(kase)}</div>
              <h1>Not locatable</h1>
              <p className="muted">{why}</p>
            </div>
            <section aria-label="What we checked" className="stack gap10">
              <h2 className="mono11" style={{ margin: 0 }}>What we checked</h2>
              <div className="card">
                <div className="card-row"><span style={{ fontSize: 14 }}>Audio decoded</span><span className="mono11 tnum" style={{ fontSize: 12, textTransform: "none" }}>{clock(duration, true)}</span></div>
                <div className="card-row"><span style={{ fontSize: 14 }}>Steady hum removed</span><span className="mono11" style={{ fontSize: 12 }}>Done</span></div>
                <div className="card-row"><span style={{ fontSize: 14 }}>Suggestions from automatic detection</span><span className="mono11 tnum" style={{ fontSize: 12 }}>{kase.events.proposed + kase.events.confirmed}</span></div>
                <div className="card-row"><span style={{ fontSize: 14, fontWeight: 600 }}>Flyovers confirmed</span><span className="mono11 bright" style={{ fontSize: 12, fontWeight: 500 }}>{n === 0 ? "None" : n}</span></div>
                {nl.reason !== "fewer_than_two_flyovers" && (
                  <div className="card-row"><span style={{ fontSize: 14, fontWeight: 600 }}>{nl.reason === "no_flights" ? "Propeller flights on file" : "Places that fit both flyovers"}</span>
                    <span className="mono11 bright" style={{ fontSize: 12, fontWeight: 500 }}>{nl.reason === "no_flights" ? (r.inputs.flight_days.length ? "None" : "Day not loaded") : "None"}</span></div>
                )}
                <div className="stack" style={{ gap: 6, padding: "14px 16px" }}>
                  <Strip caseId={kase.id} duration={duration} boxes={stripBoxes} height={56}
                         label={n === 0 ? "Dot-matrix spectrogram of the recording with no flyover marked" : `Dot-matrix spectrogram of the recording with ${n} flyover marked`} />
                  <div className="ticks"><span>0:00</span><span>{clock(duration)}</span></div>
                </div>
              </div>
            </section>
            <section aria-label="What would help" className="stack gap12">
              <h2 className="mono11" style={{ margin: 0 }}>What would help</h2>
              <ul className="bullets top">{nl.advice.map((a) => <li key={a}><span aria-hidden="true" className="sq" /><span>{a}</span></li>)}</ul>
            </section>
            <Actions kase={kase}>
              <p className="mono11 dim">This result is saved to the case</p>
              <button type="button" className="pill primary" onClick={newReport}><span>Try another file</span><Arrow /></button>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                <button type="button" className="pill" style={{ flex: "1 1 auto", padding: "0 16px" }} onClick={() => go("flyovers")}>Mark flyovers by hand</button>
                <ExportReport kase={kase} />
              </div>
            </Actions>
          </div>
        </aside>
        <main className="stage">
          <DotMap pack={pack} selected={kase.region_ids ?? []} selectedTone="gray" customBBox={kase.custom_bbox}
                  label={`Dot-matrix map of ${pack.name} with the area you selected outlined and no estimate shown`} />
          <div className="chip col tr mono11">
            {(kase.region_ids?.length || kase.custom_bbox) && <div><span aria-hidden="true" className="sq" style={{ background: "var(--text-3)" }} /><span>Area you selected</span></div>}
            <div className="bright" style={{ color: "var(--text)" }}>No estimate for this recording</div>
          </div>
        </main>
      </div>
    );
  }

  // ----------------------------------------------------------------------------------------- located
  if (located && point) {
    const radius = point.radius_m;
    const others = r.candidates.filter((c) => (viewingOutside ? c.rank !== om!.rank : c.rank !== r.shown_rank));
    const cpas = paths(events).map((p) => metresBetween([point.lat, point.lon], p.cpa)).filter((d) => d < 4000);
    const half = Math.min(5000, Math.max(500, 2.5 * radius, 1.25 * Math.max(0, ...cpas)));
    const cells = viewingOutside ? om!.cells : r.estimate!.cells;
    return (
      <div className="app">
        <aside className="panel">
          {header}
          <div className="panel-body">
            {stale}
            <div className="stack topline" style={{ gap: 6 }}>
              <div className="mono11" style={{ marginBottom: 6 }}>{caseLine(kase)}</div>
              <div className="mono11 bright eyebrow"><span aria-hidden="true" className="sq" /><span>Estimated location</span></div>
              <h1 className="tnum" style={{ fontSize: 27, lineHeight: 1.2 }}>{coords(point.lat, point.lon)}</h1>
              <div className="row between">
                <span className="muted">{regionName(point.regions)}, within about {distance(radius)}</span>
                <a className="link-btn" style={{ whiteSpace: "nowrap" }} href={googleMapsUrl(point.lat, point.lon)} target="_blank" rel="noopener noreferrer" aria-label="Open in Google Maps, in a new tab">Google Maps<span aria-hidden="true"> ↗</span></a>
              </div>
              {clipStart != null && <div className="mono11">Recording started {localClock(clipStart, zone)} {zoneName(zone, r.inputs.date_local, "short")}</div>}
            </div>
            {banner}
            <Confidence r={r} located />
            <section aria-label="Fitted tones against the recording" className="card stack gap10" style={{ padding: 16 }}>
              <span className="mono11">Fitted tones against the recording</span>
              <Strip caseId={kase.id} duration={duration} boxes={stripBoxes} label={`Dot-matrix spectrogram. A red fitted curve runs through each of the ${events.length} recorded aircraft tones`} />
              <div className="mono11" style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
                <div className="row" style={{ gap: 8 }}><span aria-hidden="true" className="sq" style={{ background: "var(--text)" }} /><span>Recording</span></div>
                <div className="row" style={{ gap: 8 }}><span aria-hidden="true" className="swatch-line" style={{ background: "var(--red)" }} /><span>Curve fitted to each tone</span></div>
              </div>
            </section>
            <section aria-label="Matched flights" className="stack gap10">
              <h2 className="mono11" style={{ margin: 0 }}>Matched flights</h2>
              <div className="card flights">
                {events.map((e, i) => (
                  <div key={e.id}>
                    <div className="stack">
                      <span style={{ fontSize: 14, fontWeight: 500 }}>Flight {i + 1}{e.type ? `, ${e.type}` : ""}{e.icao ? ` · ${e.icao.toUpperCase()}` : ""}</span>
                      <span className="helper tnum">{e.matched && e.path ? `Closest at ${localClock(e.path.cpa_unix, zone)}` : "No flight matched this flyover"}</span>
                    </div>
                    <span className="tnum" style={{ flex: "none", font: "400 13px var(--font-mono)" }}>{e.matched && e.slant_m != null ? distance(e.slant_m) : ""}</span>
                  </div>
                ))}
              </div>
            </section>
            {alternates && others.length > 0 && (
              <section aria-label="Alternates" className="stack gap10">
                <h2 className="mono11" style={{ margin: 0 }}>Other places that scored, best first</h2>
                <div className="card cands">
                  {others.map((c) => (
                    <button key={c.rank} type="button" aria-pressed={false} onClick={() => undefined} style={{ cursor: "default" }}>
                      <span aria-hidden="true" className={`num${c.in_area && c.in_time ? "" : " outside"}`}>{c.rank}</span>
                      <span className="stack" style={{ flex: "1 1 auto", minWidth: 0 }}><span className="where">{coords(c.lat, c.lon)}</span>
                        <span className="sub">{[c.regions.length ? regionName(c.regions) : null, c.in_area ? null : "outside your area", c.in_time ? null : "outside your time"]
                          .filter(Boolean).join(" · ").replace(/^o/, "O") || "No listed area"}</span></span>
                      <span className="tnum" style={{ flex: "none", font: "400 13px var(--font-mono)" }}>{c.score.toFixed(1)}</span>
                    </button>
                  ))}
                </div>
              </section>
            )}
            <Actions kase={kase}>
              <ExportReport kase={kase} primary />
              <div style={{ display: "flex", gap: 12 }}>
                <button type="button" className="pill" style={{ flex: "1 1 auto", padding: "0 16px" }} disabled={!others.length} aria-expanded={alternates} onClick={() => setAlternates(!alternates)}>
                  {alternates ? "Hide alternates" : `Show ${others.length} alternate${others.length === 1 ? "" : "s"}`}
                </button>
                <button type="button" className="pill" style={{ flex: "1 1 auto", padding: "0 16px" }} onClick={newReport}>New report</button>
              </div>
            </Actions>
          </div>
        </aside>
        <main className="stage">
          {tiles ? (
            <LocationMap tiles={tiles} at={{ lat: point.lat, lon: point.lon, radius_m: radius }} wideM={half} cells={cells}
                         cellM={viewingOutside ? om!.cell_m : r.estimate!.cell_m} paths={paths(events)}
                         label={`Street map centred on the estimate. Red cells match the recording; a red circle marks the estimate and its ${distance(radius)} uncertainty, with the matched flight paths passing nearby. Arrow keys move the map; plus and minus zoom`} />
          ) : (
            <DotMap pack={pack} selected={kase.region_ids ?? []} customBBox={kase.custom_bbox} focus={boxAround(point.lat, point.lon, half)}
                    cells={cells} cellM={viewingOutside ? om!.cell_m : r.estimate!.cell_m} lattice paths={paths(events)}
                    estimate={{ lat: point.lat, lon: point.lon, radius_m: radius }} scaleBar
                    label={`Close-up dot-matrix map. Red cells match the recording; a red circle marks the estimate and its ${distance(radius)} uncertainty, with the matched flight paths passing nearby`} />
          )}
          <div className="chip col tr mono11">
            <div><span aria-hidden="true" className="swatch-ring" style={{ border: "1.5px solid var(--red)" }} /><span>Estimate and uncertainty</span></div>
            <div><span aria-hidden="true" className="ramp"><i style={{ opacity: 0.3 }} /><i style={{ opacity: 0.6 }} /><i /></span><span>Match strength, {Math.round(viewingOutside ? om!.cell_m : r.estimate!.cell_m)} m cells</span></div>
            <div><span aria-hidden="true" className="swatch-line" /><span>Matched flight paths</span></div>
          </div>
          <Locator pack={pack} at={[point.lat, point.lon]} />
        </main>
      </div>
    );
  }

  // ----------------------------------------------------------------------------------------- candidates (and an unconfirmed outside match)
  const list: Candidate[] = r.candidates;
  const sel = list.find((c) => c.rank === picked) ?? list.find((c) => c.rank === (viewingOutside ? om!.rank : r.shown_rank)) ?? list[0];
  const nFly = r.inputs.n_flyovers;
  const sub = r.sublabel ?? "unconfirmed";
  const title = sub === "weak" ? "Candidates, weak" : "Candidates, unconfirmed";
  const lede = sub === "weak" ? "The best match is no better than chance. None of these places is confirmed."
    : sub === "too_few_flights" ? "Too few other flights that day to judge these matches. None is confirmed."
    : sub === "needs_third_flyover" ? "These places fit both flyovers. A third flyover is needed to confirm one."
    : `${NUMBER_WORDS[nFly] ?? nFly} flyovers fit these places. None is confirmed.`;
  const rings: Ring[] = list.map((c) => ({ lat: c.lat, lon: c.lon, n: c.rank, kind: c.rank === sel?.rank ? "selected" : c.in_area && c.in_time ? "other" : "outside" }));
  const near = sel ? list.filter((c) => metresBetween([c.lat, c.lon], [sel.lat, sel.lon]) < 60_000) : [];
  const focus = sel ? ((): [number, number, number, number] => {
    const b = boxAround(sel.lat, sel.lon, 12_000);
    for (const c of near) { b[0] = Math.min(b[0], c.lat); b[1] = Math.max(b[1], c.lat); b[2] = Math.min(b[2], c.lon); b[3] = Math.max(b[3], c.lon); }
    return b;
  })() : null;
  return (
    <div className="app">
      <aside className="panel">
        {header}
        <div className="panel-body">
          {stale}
          <div className="stack gap8 topline">
            <div className="mono11" style={{ marginBottom: 4 }}>{caseLine(kase)}</div>
            <div className="mono11 bright eyebrow"><span aria-hidden="true" className="sq hollow" /><span>Result from {nFly} flyover{nFly === 1 ? "" : "s"}</span></div>
            <h1>{title}</h1>
            <div className="muted">{lede}</div>
          </div>
          {banner}
          <Confidence r={r} located={false} />
          <section aria-label="Candidate places" className="stack gap10">
            <div className="row between" style={{ alignItems: "baseline" }}><h2 className="mono11" style={{ margin: 0 }}>Candidate places, best first</h2><span className="mono11">Score</span></div>
            <div role="group" aria-label="Candidate places" className="card cands">
              {list.map((c) => {
                const outside = !c.in_area || !c.in_time;
                const types = c.types.filter(Boolean);
                return (
                  <button key={c.rank} type="button" aria-pressed={c.rank === sel?.rank} onClick={() => setPicked(c.rank)}>
                    <span aria-hidden="true" className={`num${outside ? " outside" : ""}`}>{c.rank}</span>
                    <span className="stack" style={{ flex: "1 1 auto", minWidth: 0 }}>
                      <span className="where">{coords(c.lat, c.lon)}</span>
                      <span className="sub" style={{ color: c.rank === sel?.rank ? "var(--dot-3)" : undefined }}>
                        {[c.regions.length ? regionName(c.regions) : null,
                          !c.in_area ? "outside your area" : !c.in_time ? "outside your time" : types.length === 2 ? `${types[0]} then ${types[1]}` : c.icao.join(" then ")]
                          .filter(Boolean).join(" · ").replace(/^o/, "O")}
                      </span>
                    </span>
                    <span className="tnum" style={{ flex: "none", font: "400 13px var(--font-mono)" }}>{c.score.toFixed(1)}</span>
                  </button>
                );
              })}
            </div>
          </section>
          <Actions kase={kase}>
            <p className="helper">{nFly >= 3 ? "Another flyover from the same recording may confirm one of these." : "A third flyover from the same recording can confirm one of these."}</p>
            <button type="button" className="pill primary" onClick={() => go("flyovers")}><span>{nFly >= 3 ? "Add another flyover" : "Add a third flyover"}</span><Arrow /></button>
            <div style={{ display: "flex", gap: 12 }}>
              <ExportReport kase={kase} />
              <button type="button" className="pill" style={{ flex: "1 1 auto", padding: "0 16px" }} onClick={newReport}>New report</button>
            </div>
          </Actions>
        </div>
      </aside>
      <main className="stage">
        <DotMap pack={pack} selected={kase.region_ids ?? []} customBBox={kase.custom_bbox} focus={focus} cells={r.cells} cellM={200} rings={rings}
                paths={sel ? sel.paths : []} scaleBar
                label={`Dot-matrix map with ${list.length} numbered candidate places. Candidate ${sel?.rank} is selected in red with the paths of its two flights`
                       + (list.some((c) => !c.in_area) ? ". Some candidates lie outside the selected area" : "")} />
        <div className="chip col tr mono11">
          <div><span aria-hidden="true" className="swatch-ring" style={{ border: "1.5px solid var(--red)" }} /><span>Selected candidate</span></div>
          <div><span aria-hidden="true" className="swatch-ring" /><span>Other candidates</span></div>
          {list.some((c) => !c.in_area || !c.in_time) && <div><span aria-hidden="true" className="swatch-ring" style={{ border: "1px dashed var(--text-2)" }} /><span>Outside your area or time</span></div>}
          <div><span aria-hidden="true" className="swatch-line" /><span>Flights for candidate {sel?.rank}</span></div>
          {areaChip}
        </div>
      </main>
    </div>
  );
}
