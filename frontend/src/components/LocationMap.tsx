// The located result on a real map: street tiles under the same layers the dot map draws
// (match cells, matched flight paths, the estimate and its uncertainty). It opens on the
// wider framing and flies in to the estimate; the analyst can pan and zoom from there.
// Viewing it asks the tile host for the tiles around the estimate (README, Configuration).
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";
import type { Cell, MapTiles } from "../api";
import { distance } from "../format";
import { boxAround, type MapPath } from "./DotMap";

const RED = "#FF4D42", TEXT = "#F4F1E8", TEXT2 = "#A8A39A";

interface Props {
  tiles: MapTiles;
  at: { lat: number; lon: number; radius_m: number };
  wideM: number;                 // half-width of the opening framing: the estimate with its flights' closest points
  cells: Cell[];
  cellM: number;
  paths: MapPath[];
  label: string;                 // the text alternative
}

const boundsAround = (lat: number, lon: number, halfM: number) => {
  const [la0, la1, lo0, lo1] = boxAround(lat, lon, halfM);
  return L.latLngBounds([la0, lo0], [la1, lo1]);
};

/** How far in the map ends up: the uncertainty circle with room around it, never closer than a few streets. */
export const closeHalfM = (radiusM: number) => Math.max(300, 3 * radiusM);

export function LocationMap({ tiles, at, wideM, cells, cellM, paths, label }: Props) {
  const el = useRef<HTMLDivElement>(null);
  // rebuild only when what is shown changes, not on every render of the result screen
  const key = JSON.stringify([tiles.url, tiles.dark, at, wideM, cellM, cells.length, cells[0], paths.map((p) => [p.label, p.cpa])]);

  useEffect(() => {
    const node = el.current!;
    const map = L.map(node, { preferCanvas: true, zoomControl: false, attributionControl: false, minZoom: 4, maxZoom: tiles.max_zoom, worldCopyJump: true });
    // a light map is inverted to suit the theme (styles.css); the layers above it keep their own colours
    L.tileLayer(tiles.url, { attribution: tiles.attribution, maxZoom: tiles.max_zoom, className: tiles.dark ? "tiles-dark" : "" }).addTo(map);
    L.control.zoom({ position: "topleft", zoomInTitle: "Zoom in", zoomOutTitle: "Zoom out" }).addTo(map);
    L.control.scale({ imperial: false, position: "bottomleft", maxWidth: 140 }).addTo(map);
    L.control.attribution({ prefix: false, position: "bottomleft" }).addTo(map);

    // match strength: each cell at its true ground size, the best ones drawn last
    const scores = cells.map((c) => c[2]).filter((s): s is number => s != null);
    const lo = Math.min(...scores), hi = Math.max(...scores);
    for (let i = cells.length - 1; i >= 0; i--) {
      const [lat, lon, sc] = cells[i];
      if (sc == null) continue;
      const t = hi > lo ? (sc - lo) / (hi - lo) : 1;
      L.rectangle(boundsAround(lat, lon, cellM / 2), { stroke: false, fillColor: RED, fillOpacity: t > 0.85 ? 0.5 : t > 0.6 ? 0.34 : t > 0.3 ? 0.2 : 0.1, interactive: false }).addTo(map);
    }

    // the matched flights: the path, its closest point, and a dashed line from there to the estimate
    for (const p of paths) {
      L.polyline(p.points, { color: TEXT, weight: 2, opacity: 0.9, interactive: false }).addTo(map);
      L.polyline([p.cpa, [at.lat, at.lon]], { color: TEXT2, weight: 1, dashArray: "4 5", interactive: false }).addTo(map);
      const m = L.marker(p.cpa, { icon: L.divIcon({ className: "map-cpa", iconSize: [9, 9] }), interactive: false, keyboard: false }).addTo(map);
      if (p.label) m.bindTooltip(p.label, { permanent: true, direction: "right", offset: [9, 0], className: "map-label" });
    }

    L.circle([at.lat, at.lon], { radius: at.radius_m, color: RED, weight: 1.5, fillColor: RED, fillOpacity: 0.06, interactive: false }).addTo(map);
    L.circleMarker([at.lat, at.lon], { radius: 4, stroke: false, fillColor: RED, fillOpacity: 1, interactive: false }).addTo(map);
    // the label hangs from the bottom of the circle, so it clears it at every zoom
    L.marker([at.lat - at.radius_m / 111_320, at.lon], { icon: L.divIcon({ className: "", iconSize: [0, 0] }), interactive: false, keyboard: false }).addTo(map)
      .bindTooltip(`Estimate, within ${distance(at.radius_m)}`, { permanent: true, direction: "bottom", offset: [0, 6], className: "map-label red" });

    // open on the wider framing, then fly in to the estimate
    const close = boundsAround(at.lat, at.lon, closeHalfM(at.radius_m));
    let timer: number | undefined;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) map.fitBounds(close);
    else {
      map.fitBounds(boundsAround(at.lat, at.lon, wideM));
      timer = window.setTimeout(() => map.flyToBounds(close, { duration: 1.8 }), 900);
    }
    const resized = new ResizeObserver(() => map.invalidateSize());
    resized.observe(node);
    return () => { window.clearTimeout(timer); resized.disconnect(); map.remove(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return <div ref={el} className="tilemap" role="application" aria-label={label} />;
}
