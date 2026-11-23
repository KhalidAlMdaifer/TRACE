"""Region packs: a named area with a time zone, a bounding box and region polygons.

Polygon tests only, never bounding boxes: the emirates have exclaves. numpy only."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .. import config


class PackNotFound(LookupError):
    pass


def _ring_contains(ring: np.ndarray, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Even-odd ray casting for one closed ring of (lon, lat) vertices."""
    x, y = ring[:, 0], ring[:, 1]
    inside = np.zeros(lon.shape, bool)
    j = len(ring) - 1
    for i in range(len(ring)):
        if y[i] != y[j]:
            crosses = (y[i] > lat) != (y[j] > lat)
            xi = (x[j] - x[i]) * (lat - y[i]) / (y[j] - y[i]) + x[i]
            inside ^= crosses & (lon < xi)
        j = i
    return inside


def polygons_of(geometry: dict) -> list[list[np.ndarray]]:
    """A GeoJSON Polygon or MultiPolygon as a list of polygons, each a list of rings (the
    outer ring first, then holes)."""
    if geometry["type"] == "Polygon":
        polys = [geometry["coordinates"]]
    elif geometry["type"] == "MultiPolygon":
        polys = geometry["coordinates"]
    else:
        raise ValueError(f"unsupported geometry: {geometry['type']}")
    return [[np.asarray(r, float)[:, :2] for r in poly] for poly in polys]


@dataclass
class Region:
    id: str
    name: str
    parent: str | None
    polygons: list[list[np.ndarray]] = field(repr=False)

    def contains(self, lat, lon) -> np.ndarray:
        lat, lon = np.atleast_1d(np.asarray(lat, float)), np.atleast_1d(np.asarray(lon, float))
        out = np.zeros(lat.shape, bool)
        for rings in self.polygons:
            inside = _ring_contains(rings[0], lon, lat)
            for hole in rings[1:]:
                inside &= ~_ring_contains(hole, lon, lat)
            out |= inside
        return out


@dataclass
class Pack:
    id: str
    name: str
    timezone: str
    bbox: tuple[float, float, float, float]          # lat_min, lat_max, lon_min, lon_max (dopplertrack's order)
    terrain_zoom: int | None
    climate_c: dict[str, float]
    regions: list[Region]
    demo_case: dict | None = None
    geojson: dict | None = field(default=None, repr=False)
    meta: dict = field(default_factory=dict, repr=False)      # the rest of pack.json: short_name, labels, boundaries, dev_only

    @property
    def short_name(self) -> str:
        return self.meta.get("short_name") or self.name

    @property
    def centre(self) -> tuple[float, float]:
        return (self.bbox[0] + self.bbox[1]) / 2, (self.bbox[2] + self.bbox[3]) / 2

    def region(self, region_id: str) -> Region:
        for r in self.regions:
            if r.id == region_id:
                return r
        raise KeyError(region_id)


def pack_dirs() -> list[Path]:
    """Packs in the data folder win over the ones shipped with the code."""
    return [config.data_dir() / "packs", config.BUILTIN_PACKS]


def load_pack(pack_id: str, dirs: list[Path] | None = None) -> Pack:
    if not re.fullmatch(r"[a-z0-9_-]{1,40}", pack_id or ""):
        raise PackNotFound(pack_id)
    for d in dirs or pack_dirs():
        p = Path(d) / pack_id / "pack.json"
        if p.exists():
            meta = json.loads(p.read_text())
            gj = json.loads((p.parent / "regions.geojson").read_text())
            regions = [Region(f["properties"]["id"], f["properties"].get("name", f["properties"]["id"]),
                              f["properties"].get("parent"), polygons_of(f["geometry"])) for f in gj["features"]]
            return Pack(meta["id"], meta["name"], meta["timezone"], tuple(meta["bbox"]), meta.get("terrain_zoom"),
                        meta.get("climate_c") or {}, regions, meta.get("demo_case"), gj, meta)
    raise PackNotFound(pack_id)


def in_regions(pack: Pack, region_ids, lat, lon) -> np.ndarray:
    """True where a point lies in any of the named regions. No regions named means no area
    constraint: everything passes."""
    lat, lon = np.atleast_1d(np.asarray(lat, float)), np.atleast_1d(np.asarray(lon, float))
    if not region_ids:
        return np.ones(lat.shape, bool)
    out = np.zeros(lat.shape, bool)
    for rid in region_ids:
        out |= pack.region(rid).contains(lat, lon)
    return out


def in_bbox(bbox, lat, lon) -> np.ndarray:
    lat, lon = np.atleast_1d(np.asarray(lat, float)), np.atleast_1d(np.asarray(lon, float))
    return (lat >= bbox[0]) & (lat <= bbox[1]) & (lon >= bbox[2]) & (lon <= bbox[3])


def in_area(pack: Pack, region_ids, custom_bbox, lat, lon) -> np.ndarray:
    """The analyst's area: named regions, a drawn box, or both (either one passes)."""
    if not region_ids and not custom_bbox:
        return np.ones(np.atleast_1d(np.asarray(lat)).shape, bool)
    out = np.zeros(np.atleast_1d(np.asarray(lat)).shape, bool)
    if region_ids:
        out |= in_regions(pack, region_ids, lat, lon)
    if custom_bbox:
        out |= in_bbox(custom_bbox, lat, lon)
    return out


def regions_at(pack: Pack, lat: float, lon: float) -> list[str]:
    return [r.id for r in pack.regions if bool(r.contains(lat, lon)[0])]


def dot_grid(pack: Pack, pitch_m: float = 4000.0) -> list[tuple[float, float, str]]:
    """Cells for the UI's dot map: a regular lattice over the pack, kept where it falls in a
    region. Sub-areas (regions with a parent) win over their parent."""
    lat0, lat1, lon0, lon1 = pack.bbox
    dlat = pitch_m / 111320.0
    dlon = pitch_m / (111320.0 * np.cos(np.radians((lat0 + lat1) / 2)))
    la, lo = np.meshgrid(np.arange(lat0 + dlat / 2, lat1, dlat), np.arange(lon0 + dlon / 2, lon1, dlon), indexing="ij")
    la, lo = la.ravel(), lo.ravel()
    owner = np.full(la.shape, "", dtype=object)
    for r in sorted(pack.regions, key=lambda r: r.parent is not None):     # parents first, sub-areas overwrite
        owner[r.contains(la, lo)] = r.id
    keep = owner != ""
    return [(round(float(a), 5), round(float(b), 5), str(o)) for a, b, o in zip(la[keep], lo[keep], owner[keep])]
