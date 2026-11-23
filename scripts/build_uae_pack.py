"""Build the UAE region pack (backend/app/packs/uae) from open boundary data.

Run once; the output is committed. Needs shapely, which the app itself does not:

    uv run --with shapely python scripts/build_uae_pack.py data/reference/boundaries

Inputs, both OpenStreetMap data under the Open Database License 1.0 (attribution:
"(c) OpenStreetMap contributors"):

  geoBoundaries-ARE-ADM1_simplified.geojson
      the seven emirates, from geoBoundaries (gbOpen ARE ADM1, release 9469f09, boundary
      year 2017, source "OpenStreetMap, Wambacher"):
      https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/ARE/ADM1/geoBoundaries-ARE-ADM1_simplified.geojson
  osm-abudhabi-regions.json
      Abu Dhabi's three regions, OSM relations 13249272 (Al Ain), 13249273 (Abu Dhabi) and
      13249274 (Al Dhafrah), from Nominatim:
      https://nominatim.openstreetmap.org/lookup?osm_ids=R13249272,R13249273,R13249274&format=jsonv2&polygon_geojson=1&polygon_threshold=0.002

The OSM regions reach out to sea, so each is cut to the emirate's own outline. Emirate
outlines are kept as published (exclaves included), with coordinates rounded to five places.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.ops import unary_union
from shapely.validation import make_valid

OUT = Path(__file__).resolve().parent.parent / "backend" / "app" / "packs" / "uae"
# geoBoundaries shapeName -> (id, display name), in the order the Where screen lists them
EMIRATES = {"Abu Dhabi": ("abu_dhabi", "Abu Dhabi"), "Dubai": ("dubai", "Dubai"), "Sharjah": ("sharjah", "Sharjah"), "Ajman": ("ajman", "Ajman"),
            "Umm al-Quwain": ("umm_al_quwain", "Umm Al Quwain"), "Ras al-Khaimah": ("ras_al_khaimah", "Ras Al Khaimah"), "Fujairah": ("fujairah", "Fujairah")}
SUBAREAS = {13249273: ("abu_dhabi_region", "Abu Dhabi region"), 13249272: ("al_ain_region", "Al Ain region"), 13249274: ("al_dhafra_region", "Al Dhafra region")}
MIN_PIECE_KM2 = 2.0                # slivers left by cutting a coarse outline against a fine one
KM2_PER_DEG2 = 111.32 * 111.32 * 0.91      # near 24.5 N; only used for the sliver threshold and the report


def rounded(geom) -> dict:
    def r(x):
        return [r(v) for v in x] if isinstance(x[0], (list, tuple)) else [round(x[0], 5), round(x[1], 5)]
    m = mapping(geom)
    return {"type": m["type"], "coordinates": r(m["coordinates"])}


def polygons_only(geom):
    """The polygon parts of a geometry, as one (Multi)Polygon."""
    parts = [g for g in getattr(geom, "geoms", [geom]) if g.geom_type in ("Polygon", "MultiPolygon")]
    return unary_union(parts)


def main(src: Path) -> int:
    adm1 = json.loads((src / "geoBoundaries-ARE-ADM1_simplified.geojson").read_text())
    by_name = {f["properties"]["shapeName"]: make_valid(shape(f["geometry"])) for f in adm1["features"]}
    missing = set(EMIRATES) - set(by_name)
    if missing:
        raise SystemExit(f"emirates missing from the boundary file: {sorted(missing)}")

    features = []
    for name, (rid, label) in EMIRATES.items():
        g = polygons_only(by_name[name])
        features.append({"type": "Feature", "properties": {"id": rid, "name": label, "parent": None}, "geometry": rounded(g)})
        print(f"{label:<16} {len(getattr(g, 'geoms', [g])):>3} polygons  {g.area * KM2_PER_DEG2:>9,.0f} km2")

    emirate = polygons_only(by_name["Abu Dhabi"])
    osm = {int(r["osm_id"]): make_valid(shape(r["geojson"])) for r in json.loads((src / "osm-abudhabi-regions.json").read_text())}
    covered = []
    for osm_id, (rid, label) in SUBAREAS.items():
        cut = polygons_only(osm[osm_id].intersection(emirate))
        parts = [p for p in getattr(cut, "geoms", [cut]) if p.area * KM2_PER_DEG2 >= MIN_PIECE_KM2]
        g = unary_union(parts)
        covered.append(g)
        features.append({"type": "Feature", "properties": {"id": rid, "name": label, "parent": "abu_dhabi"}, "geometry": rounded(g)})
        print(f"  {label:<18} {len(parts):>3} polygons  {g.area * KM2_PER_DEG2:>9,.0f} km2")
    share = unary_union(covered).area / emirate.area
    print(f"the three regions cover {share:.1%} of the emirate's outline")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "regions.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":")))
    pack = {
        "id": "uae", "name": "United Arab Emirates", "short_name": "UAE", "timezone": "Asia/Dubai",
        "bbox": [22.6, 26.1, 51.5, 56.4], "terrain_zoom": 12,
        "climate_c": {"01": 19, "02": 20, "03": 23, "04": 27, "05": 31, "06": 33, "07": 35, "08": 35, "09": 33, "10": 29, "11": 25, "12": 21},
        "climate_note": "Approximate monthly mean air temperatures for the UAE coast, from memory, not from a cited source. "
                        "Fallback only, used when the analyst gives no temperature; replace with a weather archive in M5.",
        "weather_point": [24.9, 55.2],
        "weather_note": "Where the automatic temperature is looked up: one point for the whole pack.",
        # where the names of the small emirates sit on the dot map: in the sea, with a line to the land
        "labels": {"ajman": {"at": [25.50, 55.16], "to": [25.41, 55.47], "anchor": "end"},
                   "umm_al_quwain": {"at": [25.68, 55.30], "to": [25.56, 55.57], "anchor": "end"},
                   "ras_al_khaimah": {"at": [25.97, 55.62], "to": [25.80, 55.95], "anchor": "end"},
                   "fujairah": {"at": [25.33, 56.50], "to": [25.25, 56.34], "anchor": "start"}},
        "boundaries": {"source": "OpenStreetMap contributors: emirates via geoBoundaries (gbOpen ARE ADM1, 2017, release 9469f09); "
                                 "Abu Dhabi regions from OSM relations 13249272, 13249273, 13249274, cut to the emirate outline",
                       "licence": "Open Database License 1.0", "built_by": "scripts/build_uae_pack.py"},
        "demo_case": None,
    }
    (OUT / "pack.json").write_text(json.dumps(pack, indent=1) + "\n")
    print(f"wrote {OUT}/pack.json and regions.geojson ({(OUT / 'regions.geojson').stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.exit(main(Path(sys.argv[1])))
