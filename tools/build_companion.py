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
# about. Point-like only: a centroid stands in badly for a park or a lake, and
# a wrong distance would eliminate somewhere the hider might really be.
POI_KEYS = ["airport", "museum", "library", "hospital", "cinema", "zoo",
            "aquarium", "theme_park", "golf", "consulate", "peak"]

# How finely the shoreline is sampled, in degrees (~110 m).
COAST_STEP = 0.001
# A stop this close to the Berkeley/Oakland line is never eliminated by a
# question about which city you are in.
CITY_EDGE_M = 500

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


def main():
    poi_src = json.loads((DATA / "poi.json").read_text())
    zones = json.loads((DATA / "zone.json").read_text())
    from shapely.geometry import shape, Point           # noqa: E402
    berk = shape(zones["berk"])
    city_edge = berk.boundary

    maps = {}
    for name, cfg in ZONES.items():
        mode, layers, payload, meta = compute(name)
        keep = [k for k in LAYERS if k not in cfg["drop"]]
        origin = meta["origin"]

        # Which city each stop sits in, and whether it is close enough to the
        # line that a city question must not rule it out.
        R = 6378137.0
        def unproject(x, y):
            lon = math.degrees((x + origin[0]) / R)
            lat = math.degrees(2 * math.atan(math.exp((origin[1] - y) / R)) - math.pi / 2)
            return lon, lat
        cities, edges = [], []
        for st in payload["stops"]:
            lon, lat = unproject(st[0], st[1])
            pt = Point(lon, lat)
            cities.append(0 if berk.contains(pt) else 1)
            edges.append(1 if city_edge.distance(pt) * 111000 * 0.79 < CITY_EDGE_M else 0)

        maps[name] = {
            "label": cfg["label"],
            "vb": payload["VB"],
            "origin": origin,
            "city": cities,
            "cityEdge": edges,
            "layers": {k: layers[k] for k in keep if layers.get(k)},
            "stops": payload["stops"],
            "stations": payload["stations"],
            "places": payload["places"],
        }
        kb = len(json.dumps(maps[name], separators=(",", ":"))) // 1024
        print(f"  {name}: {len(payload['stops'])} stops, {kb} KB")

    # Reference points are shared by both zones, so they are stored once in
    # lon/lat and projected in the browser rather than baked in twice.
    poi = {k: poi_src.get(k, []) for k in POI_KEYS}
    poi["coast"] = [[round(x, 5), round(y, 5)] for x, y in
                    sample_latlon(json.loads((DATA / "mapdata.json").read_text())["base"]["coast"])]
    npoi = sum(len(v) for v in poi.values())
    print(f"  reference points: {npoi} (shared)")

    blob = json.dumps({"zones": maps, "poi": poi}, separators=(",", ":"), ensure_ascii=False)
    html = TEMPLATE.read_text().replace("__MAPDATA__", blob)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html)
    print(f"{OUT.relative_to(ROOT)}: {len(html) // 1024} KB")


if __name__ == "__main__":
    main()
