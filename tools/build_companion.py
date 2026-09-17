#!/usr/bin/env python3
"""Build the companion app, with both game-zone maps baked in.

The companion shows the same map as the standalone pages, so it reuses
`build_map.compute` rather than re-deriving the projection. Two things are
dropped to keep the file small enough to load once on a phone and then work
offline: the bus-route polylines (each stop still lists its routes when you
tap it) and the two half-zone outlines, which the combined zone already
covers.

    python3 tools/build_companion.py
"""

import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from build_map import compute  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TEMPLATE = ROOT / "tools" / "companion_template.html"
OUT = ROOT / "companion" / "index.html"

# The reference features the matching, measuring and tentacle questions ask
# about, as points. Parks, water and the shoreline are shapes instead, and are
# measured to their nearest edge further down.
POI_KEYS = ["airport", "museum", "library", "hospital", "cinema", "zoo",
            "aquarium", "theme_park", "golf", "consulate", "peak"]

# The Foreign Consulate card says to exclude honorary consulates.
def HONORARY(key, p):
    return key == "consulate" and "honorary" in (p[2] or "").lower()

# Layers the companion draws, in paint order. `cut` (the Highway 24 band)
# only means anything on the combined zone.
LAYERS = [
    "parks", "campus", "water", "residential", "tertiary", "secondary", "primary",
    "motorway", "rail", "cut", "bart", "amtrak", "zone", "oob",
]

ZONES = {
    "berkeley": {"label": "Berkeley", "drop": ["cut"]},
    "berkeley-north-oakland": {"label": "Berkeley + N. Oakland", "drop": []},
}


def project_poi(origin, lon, lat):
    R = 6378137.0
    x = R * math.radians(lon)
    y = R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return [round(x - origin[0]), round(origin[1] - y)]


def sample_latlon(rings):
    """Walk the shoreline dropping a point every COAST_STEP, so distance to
    the coast can be measured against points rather than guessed."""
    out = []
    for ring in rings:
        for i in range(len(ring) - 1):
            (x0, y0), (x1, y1) = ring[i], ring[i + 1]
            steps = max(1, int(math.hypot(x1 - x0, y1 - y0) / COAST_STEP))
            for k in range(steps):
                t = k / steps
                out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    return out


def outlines(rings):
    """Kept at full resolution. These are measured to their nearest edge, and
    simplifying collapsed the small ponds to a single point, which turned
    "how far to the nearest water" into a different question."""
    return [[[round(x, 5), round(y, 5)] for x, y in r] for r in rings if len(r) > 1]


def main():
    poi_src = json.loads((DATA / "poi.json").read_text())
    zones = json.loads((DATA / "zone.json").read_text())
    base = json.loads((DATA / "mapdata.json").read_text())
    from shapely.geometry import shape                            # noqa: E402
    
    maps = {}
    for name, cfg in ZONES.items():
        mode, layers, payload, meta = compute(name)
        keep = [k for k in LAYERS if k not in cfg["drop"]]
        maps[name] = {
            "label": cfg["label"],
            "vb": payload["VB"],
            "origin": meta["origin"],
            "layers": {k: layers[k] for k in keep if layers.get(k)},
            "stops": payload["stops"],
            "stations": payload["stations"],
            "places": payload["places"],
        }
        kb = len(json.dumps(maps[name], separators=(",", ":"))) // 1024
        print(f"  {name}: {len(payload['stops'])} stops, {kb} KB")

    # Reference points are shared by both zones, so they are stored once in
    # lon/lat and projected in the browser rather than baked in twice.
    poi = {k: [p for p in poi_src.get(k, []) if not HONORARY(k, p)] for k in POI_KEYS}

    # Outlines measured to their nearest edge, not to a label point: standing
    # in a park you are nought metres from it, which is what a player would say.
    shapes = {
        "coast": outlines(base["base"]["coast"]),
        "water": outlines(base["base"]["water"]),
        "park": outlines(base["base"]["park"]),
    }

    # Named areas a point falls inside. 1st administrative division is the
    # city; the 2nd is the council district, loaded if the file is there.
    def rings_of(geom):
        g = shape(geom) if isinstance(geom, dict) else geom
        parts = getattr(g, "geoms", [g])
        return [[[round(x, 5), round(y, 5)] for x, y in
                 p.exterior.simplify(0.00012).coords] for p in parts]

    # Oakland arrives as loose boundary ways, so they are stitched into a
    # polygon before anything can ask whether a point is inside it.
    from shapely.ops import linemerge, unary_union, polygonize          # noqa: E402
    from shapely.geometry import LineString as LS                       # noqa: E402
    oak = list(polygonize(unary_union(linemerge(
        [LS(r) for r in base["bnd"]["oakland"] if len(r) > 1]))))
    oak = max(oak, key=lambda g: g.area) if oak else None
    areas = {"city": [{"n": "Berkeley", "r": rings_of(zones["berk"])}]}
    if oak is not None:
        areas["city"].append({"n": "Oakland", "r": rings_of(oak)})
    dpath = DATA / "districts.json"
    if dpath.exists():
        areas["district"] = json.loads(dpath.read_text())
    print(f"  areas: " + ", ".join(f"{k} x{len(v)}" for k, v in areas.items()))

    npoi = sum(len(v) for v in poi.values())
    nshape = sum(len(v) for v in shapes.values())
    print(f"  reference points: {npoi}; outlines: {nshape}")

    blob = json.dumps({"zones": maps, "poi": poi, "shapes": shapes, "areas": areas},
                      separators=(",", ":"), ensure_ascii=False)
    html = TEMPLATE.read_text().replace("__MAPDATA__", blob)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html)
    print(f"{OUT.relative_to(ROOT)}: {len(html) // 1024} KB")


if __name__ == "__main__":
    main()
