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
    """Kept at full resolution. The shoreline is measured to itself, not to a
    label point, so simplifying it changes the answer."""
    return [[[round(x, 5), round(y, 5)] for x, y in r] for r in rings if len(r) > 1]


def icons(rings, names=None):
    """Parks and bodies of water are measured "from the map icon", per the
    cards, so each shape is reduced to the point a map would label it at."""
    out = []
    for r in rings:
        if len(r) < 4:
            continue
        g = Polygon(r)
        if not g.is_valid or g.area <= 0:
            continue
        p = g.representative_point()
        out.append([round(p.x, 5), round(p.y, 5), ""])
    return out


def main():
    poi_src = json.loads((DATA / "poi.json").read_text())
    zones = json.loads((DATA / "zone.json").read_text())
    base = json.loads((DATA / "mapdata.json").read_text())
    from shapely.geometry import shape, Point, Polygon                # noqa: E402
    from shapely.ops import linemerge, unary_union, polygonize        # noqa: E402
    from shapely.geometry import LineString as LS                     # noqa: E402
    globals()["Polygon"] = Polygon

    # The reference features a question can be about are whatever falls inside
    # the game map. The rulebook is explicit: "if locations are not within a
    # map's boundaries, players must operate as if they do not exist", and the
    # question comes back null. So each zone carries its own clipped sets.
    park_pts = icons(base["base"]["park"])
    water_pts = icons(base["base"]["water"])

    oak = list(polygonize(unary_union(linemerge(
        [LS(r) for r in base["bnd"]["oakland"] if len(r) > 1]))))
    oak = max(oak, key=lambda g: g.area) if oak else None
    berk = shape(zones["berk"])

    def rings_of(g):
        parts = [q for q in getattr(g, "geoms", [g])
                 if q.geom_type == "Polygon" and q.area > 1e-8]
        return [[[round(x, 5), round(y, 5)] for x, y in
                 p.exterior.simplify(0.00012).coords] for p in parts]

    maps = {}
    for name, cfg in ZONES.items():
        mode, layers, payload, meta = compute(name)
        keep = [k for k in LAYERS if k not in cfg["drop"]]
        area = shape(zones["berk" if name == "berkeley" else "zone"])

        def clip(pts):
            return [p for p in pts if area.contains(Point(p[0], p[1]))]

        poi = {k: clip([p for p in poi_src.get(k, []) if not HONORARY(k, p)])
               for k in POI_KEYS}
        poi["park"] = clip(park_pts)
        poi["water"] = clip(water_pts)

        # A city with no real area inside the map is not on the map.
        cities = []
        for nm, g in (("Berkeley", berk), ("Oakland", oak)):
            if g is None:
                continue
            r = rings_of(g.intersection(area))
            if r:
                cities.append({"n": nm, "r": r})
        areas = {"city": cities}
        for extra, path in (("county", DATA / "counties.json"),):
            if path.exists():
                got = [a for a in json.loads(path.read_text())
                       if shape({"type": "Polygon", "coordinates": [a["r"][0]]}).intersects(area)]
                if got:
                    areas[extra] = got

        maps[name] = {
            "label": cfg["label"],
            "vb": payload["VB"],
            "origin": meta["origin"],
            "layers": {k: layers[k] for k in keep if layers.get(k)},
            "stops": payload["stops"],
            "stations": payload["stations"],
            "places": payload["places"],
            "poi": poi,
            "areas": areas,
        }
        have = ", ".join(f"{k}:{len(v)}" for k, v in poi.items() if v)
        miss = ", ".join(k for k, v in poi.items() if not v)
        kb = len(json.dumps(maps[name], separators=(",", ":"))) // 1024
        print(f"  {name}: {len(payload['stops'])} stops, {kb} KB")
        print(f"      on the map: {have}")
        print(f"      null here:  {miss or 'none'}")
        print(f"      areas: " + ", ".join(f"{k} x{len(v)}" for k, v in areas.items()))

    # The shoreline is the one reference measured to the feature itself.
    shapes = {"coast": outlines(base["base"]["coast"])}

    blob = json.dumps({"zones": maps, "shapes": shapes},
                      separators=(",", ":"), ensure_ascii=False)
    html = TEMPLATE.read_text().replace("__MAPDATA__", blob)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html)
    print(f"{OUT.relative_to(ROOT)}: {len(html) // 1024} KB")


if __name__ == "__main__":
    main()
