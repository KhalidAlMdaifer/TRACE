// Where: one or more regions of the pack, or a drawn box. A constraint on the results, never on the search.
import type { Case, CasePatch, Pack } from "../api";
import { toggleRegion } from "../App";
import { Arrow, FileCard } from "../components/bits";
import type { Step } from "../steps";
import type { TriageState } from "../useCaseStream";

interface Props {
  kase: Case; pack: Pack | undefined; triage: TriageState;
  patch: (p: CasePatch) => Promise<Case>; go: (s: Step) => void;
  drawing: boolean; setDrawing: (d: boolean) => void;
}

export function WhereStep({ kase, pack, triage, patch, go }: Props) {
  const regions = pack?.regions.features ?? [];
  const tops = regions.filter((f) => !f.properties.parent);
  const selected = kase.region_ids ?? [];
  const unsure = selected.length === 0 && !kase.custom_bbox;
  const name = (id: string) => regions.find((f) => f.properties.id === id)?.properties.name ?? id;
  const area = [...selected.map(name), ...(kase.custom_bbox ? ["Custom area"] : [])].join(", ") || "Not sure";
  const kind = pack?.id === "uae" ? "emirates" : tops.length > 1 ? "areas" : "area";

  return (
    <div className="panel-body">
      <FileCard name={kase.media!.filename} durationS={kase.media!.duration_s} triage={triage} />
      <div className="stack gap10">
        <h1>Roughly where?</h1>
        <p className="muted">Pick one or more {kind}, here or on the map. Matches outside them are flagged, not hidden.</p>
      </div>
      <div role="group" aria-label="Areas" className="region-grid">
        {tops.map((f) => {
          const subs = regions.filter((g) => g.properties.parent === f.properties.id);
          return [
            <button key={f.properties.id} type="button" className="region" aria-pressed={selected.includes(f.properties.id)} onClick={() => toggleRegion(kase, pack, f.properties.id, patch)}>
              <span aria-hidden="true" className="box8" /><span>{f.properties.name}</span>
            </button>,
            ...subs.map((g) => (
              <button key={g.properties.id} type="button" className="region sub" aria-pressed={selected.includes(g.properties.id)} onClick={() => toggleRegion(kase, pack, g.properties.id, patch)}>
                <span aria-hidden="true" className="box8" /><span>{g.properties.name}</span>
              </button>
            )),
          ];
        })}
        <button type="button" className="region unsure" aria-pressed={unsure} onClick={() => patch({ region_ids: null, custom_bbox: null })}>
          <span>Not sure, search all</span>
        </button>
      </div>
      <div className="card">
        <div className="card-row"><span className="mono11">Your area</span><span className="v">{area}</span></div>
        <div className="card-row"><span className="mono11">Search covers</span><span className="v">{pack ? `All ${pack.short_name} flights that day` : ""}</span></div>
      </div>
      <div className="actions">
        <button type="button" className="pill" onClick={() => go("when")}>Back</button>
        <button type="button" className="pill primary" onClick={() => go("flyovers")}><span>Continue</span><Arrow /></button>
      </div>
    </div>
  );
}
