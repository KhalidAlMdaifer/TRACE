// Review: what will be searched, the case reference, and submit.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, errorText, type Case, type CasePatch, type Pack } from "../api";
import { Arrow, Field } from "../components/bits";
import { Strip } from "../components/Strip";
import { clock, dateText, rangesText, SOURCES, zoneName } from "../format";
import type { Step } from "../steps";

interface Props { kase: Case; pack: Pack | undefined; zone: string; patch: (p: CasePatch) => Promise<Case>; go: (s: Step) => void; refresh: () => Promise<unknown> }


export function ReviewStep({ kase, pack, zone, patch, go, refresh }: Props) {
  const events = useQuery({ queryKey: ["events", kase.id], queryFn: () => api.events(kase.id) });
  const confirmed = (events.data ?? []).filter((e) => e.status === "confirmed").sort((a, b) => a.t_start - b.t_start);
  const [ref, setRef] = useState(kase.case_ref ?? "");
  const [editTemp, setEditTemp] = useState(false);
  const [temp, setTemp] = useState(kase.temperature_c != null ? String(kase.temperature_c) : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const duration = kase.media!.duration_s;
  const n = confirmed.length;
  const regions = pack?.regions.features ?? [];
  const area = [...(kase.region_ids ?? []).map((id) => regions.find((f) => f.properties.id === id)?.properties.name ?? id),
                ...(kase.custom_bbox ? ["Custom area"] : [])].join(", ") || "Not sure, all areas";
  const eff = kase.temperature_effective;
  const tempOk = temp.trim() === "" || (Number.isFinite(Number(temp)) && Number(temp) >= -60 && Number(temp) <= 60);

  const saveTemp = async () => {
    if (!tempOk) return;
    await patch({ temperature_c: temp.trim() === "" ? null : Number(temp) });
    setEditTemp(false);
  };
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await patch({ case_ref: ref.trim() });
      await api.startSearch(kase.id);
      await refresh();                 // the case must show the running search before its screen can open
      go("searching");
    } catch (e) { setError(errorText(e)); setBusy(false); }
  };

  return (
    <div className="panel-body">
      <h1>Review and submit</h1>
      <dl className="card summary">
        <div><dt className="mono11">File</dt><dd title={kase.media!.filename}>{kase.media!.filename}, {clock(duration)}</dd></div>
        <div><dt className="mono11">Date</dt><dd>{dateText(kase.date_local)}</dd><button type="button" className="link-btn" onClick={() => go("when")}>Edit<span className="sr-only"> date</span></button></div>
        <div><dt className="mono11">Time</dt><dd>{rangesText(kase.time_ranges)}{kase.time_ranges ? ` ${zoneName(zone, kase.date_local, "short")}` : ""}</dd><button type="button" className="link-btn" onClick={() => go("when")}>Edit<span className="sr-only"> time</span></button></div>
        <div><dt className="mono11">Area</dt><dd title={area}>{area}</dd><button type="button" className="link-btn" onClick={() => go("where")}>Edit<span className="sr-only"> area</span></button></div>
        <div>
          <dt className="mono11">Temp</dt>
          {editTemp ? (
            <dd style={{ display: "flex", alignItems: "center", gap: 8, overflow: "visible" }}>
              <input className={`input${tempOk ? "" : " invalid"}`} style={{ height: 36, width: 96 }} type="number" step="0.5" inputMode="decimal" aria-label="Air temperature in degrees Celsius"
                     placeholder={eff ? String(eff.c) : ""} value={temp} autoFocus onChange={(e) => setTemp(e.target.value)}
                     onKeyDown={(e) => { if (e.key === "Enter") saveTemp(); if (e.key === "Escape") setEditTemp(false); }} />
              <span>°C</span>
            </dd>
          ) : (
            <dd>{eff ? `${eff.c} °C, ${SOURCES[eff.source] ?? eff.source}` : "Not known: set it"}</dd>
          )}
          <button type="button" className="link-btn" onClick={() => (editTemp ? saveTemp() : setEditTemp(true))}>{editTemp ? "Save" : "Edit"}<span className="sr-only"> temperature</span></button>
        </div>
      </dl>
      <section aria-label="Flyover check" className="card stack gap12" style={{ padding: 16 }}>
        <div className="row between" style={{ gap: 8 }}>
          <span style={{ fontWeight: 600 }}>{n} flyover{n === 1 ? "" : "s"} confirmed</span>
          <span className="tag mono11 bright"><span aria-hidden="true" className="sq" /><span>{n >= 2 ? "Searchable" : "Not searchable"}</span></span>
        </div>
        <Strip caseId={kase.id} duration={duration} boxes={confirmed}
               label={`Dot-matrix spectrogram of the recording with ${n} confirmed flyovers boxed, each a falling tone in red`} />
        <div className="ticks" style={{ marginTop: -6 }}><span>0:00</span><span>{clock(duration)}</span></div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {confirmed.map((e, i) => <span key={e.id} className="tag mono11 bright tnum">{i + 1} · {clock(e.fit?.t_cpa ?? (e.t_start + e.t_end) / 2, true)}</span>)}
        </div>
        <div className="row between">
          <span className="helper">{n >= 3 ? "Three flyovers on one clock can confirm a location. Two give candidates only."
            : "Two flyovers give candidates only. A third on the same clock can confirm a location."}</span>
          <button type="button" className="link-btn" onClick={() => go("flyovers")}>Edit<span className="sr-only"> flyovers</span></button>
        </div>
      </section>
      <Field label="Case reference" htmlFor="case-ref" helper="Required. The search is logged against it." error={error}>
        <input id="case-ref" type="text" className="input" value={ref} maxLength={120} autoComplete="off" onChange={(e) => setRef(e.target.value)} />
      </Field>
      <div className="actions">
        <button type="button" className="pill" onClick={() => go("flyovers")}>Back</button>
        <button type="button" className={`pill primary${busy ? " busy" : ""}`} disabled={busy || n < 2 || !ref.trim() || !eff} onClick={submit}>
          {busy ? "Starting the search" : <><span>Submit report</span><Arrow /></>}
        </button>
      </div>
    </div>
  );
}
