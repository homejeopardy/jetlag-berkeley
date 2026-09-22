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
import build_extras as bx      # noqa: E402

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
    raw = bx.load_raw()
    cty_a, cty_c, cty_line = bx.county(raw)
    met = bx.metro(base)

    oak = list(polygonize(unary_union(linemerge(
        [LS(r) for r in base["bnd"]["oakland"] if len(r) > 1]))))
    oak = max(oak, key=lambda g: g.area) if oak else None
    berk = shape(zones["berk"])

    def rings_of(g):
        parts = [q for q in getattr(g, "geoms", [g])
                 if q.geom_type == "Polygon" and q.area > 1e-8]
        return [[[round(x, 5), round(y, 5)] for x, y in
                 p.exterior.simplify(0.00002).coords] for p in parts]

    def load_districts():
        # Delta-encoded integer degrees x 1e5, one district per line.
        out = []
        path = DATA / "districts.enc"
        if not path.exists():
            return out
        for line in path.read_text().strip().split("\n"):
            nm, body = line.split("|")
            rings = []
            for part in body.split(";"):
                v = [int(t) for t in part.split(",")]
                x = y = 0
                ring = []
                for i in range(0, len(v), 2):
                    x += v[i]; y += v[i + 1]
                    ring.append([x / 1e5, y / 1e5])
                rings.append(ring)
            out.append({"n": nm, "r": rings})
        return out

    maps = {}
    for name, cfg in ZONES.items():
        mode, layers, payload, meta = compute(name)
        keep = [k for k in LAYERS if k not in cfg["drop"]]
        area = shape(zones["berk" if name == "berkeley" else "zone"])

        def clip(pts):
            return [p for p in pts if area.contains(Point(p[0], p[1]))]

        # The source clipped names at 40 characters; say so rather than
        # showing a word cut in half as if it were the name.
        def full(p):
            return [p[0], p[1], p[2] + "…" if len(p[2] or "") == 40 else p[2]]
        poi = {k: clip([full(p) for p in poi_src.get(k, []) if not HONORARY(k, p)])
               for k in POI_KEYS}
        # Named parks only: an unnamed patch of green is not "a park" anyone
        # could name as their nearest. Measured from the labelled point.
        poi["park"] = bx.parks(raw, area)
        # Rail stations are hiding stations too, and carry the lines that
        # stop at them for the Transit line question.
        stops = [list(s) for s in payload["stops"]]
        for st in payload["stations"]:
            ll = next(s for s in base["stations"] if s["n"] == st["n"])
            lines = bx.station_lines((ll["lon"], ll["lat"]), st["kind"], met)
            stops.append([st["x"], st["y"], st["n"], ";".join(lines),
                          "BART" if st["kind"] == "bart" else "Amtrak", st["kind"]])

        # A city with no real area inside the map is not on the map.
        cities = []
        for nm, g in (("Berkeley", berk), ("Oakland", oak)):
            if g is None:
                continue
            r = rings_of(g.intersection(area))
            if r:
                cities.append({"n": nm, "r": r})
        # A county counts as on the map only with real ground inside it: the
        # Contra Costa line runs along the map's own edge in the hills, and
        # what pokes over it is survey slop of a few thousand square feet.
        m2 = 111320 * 111320 * math.cos(math.radians(37.87))
        counties = [c for c in (cty_a, cty_c)
                    if Polygon(c["r"][0]).intersection(area).area * m2 > 1e5]
        areas = {"city": cities, "county": counties}
        # Council districts: Berkeley's 2022 plan and Oakland's current
        # districts, clipped only to a box well beyond the map, so no
        # artificial edge ever falls within reach of a hiding zone.
        dists = []
        for d in load_districts():
            g = shape({"type": "MultiPolygon", "coordinates": [[r] for r in d["r"]]})
            if g.buffer(0).intersection(area).area * 111320 * 111320 * math.cos(math.radians(37.87)) > 1e5:
                dists.append(d)
        if dists:
            areas["district"] = dists
        maps[name] = {
            "label": cfg["label"],
            "vb": payload["VB"],
            "origin": meta["origin"],
            "layers": {k: layers[k] for k in keep if layers.get(k)},
            "stops": stops,
            "water": bx.water(raw, area),
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
        print(f"      water: " + ", ".join(w["n"] for w in maps[name]["water"]))
        print(f"      rail stops: " + "; ".join(f"{s[2]}={s[3]}" for s in stops if len(s) > 5))
        print(f"      areas: " + ", ".join(f"{k} x{len(v)}" for k, v in areas.items()))

    # Shapes measured to the feature itself: the Bay's shoreline (the Bay is
    # a named body of water) and the county line.
    shapes = {"coast": outlines(base["base"]["coast"]), "countyline": [cty_line]}
    # Streets and paths for everywhere a hiding zone or a seeker can be.
    ents = bx.streets(raw, (-12238600, 3781100, -12219700, 3792000))
    print(f"  streets: {len(ents)} streets and paths")
    blob = json.dumps({"zones": maps, "shapes": shapes, "streets": bx.streets_blob(ents),
                       "terrain": bx.terrain(raw), "metro": met},
                      separators=(",", ":"), ensure_ascii=False)
    html = TEMPLATE.read_text().replace("__MAPDATA__", blob)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html)
    print(f"{OUT.relative_to(ROOT)}: {len(html) // 1024} KB")


if __name__ == "__main__":
    main()
