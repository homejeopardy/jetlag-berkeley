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
    from shapely.geometry import shape, Point, Polygon, box as shapely_box  # noqa: E402
    from shapely.ops import linemerge, unary_union, polygonize        # noqa: E402
    from shapely.geometry import LineString as LS                     # noqa: E402
    globals()["Polygon"] = Polygon
    globals()["shapely_box"] = shapely_box

    # The reference features a question can be about are whatever falls inside
    # the game map: "if locations are not within a map's boundaries, players
    # must operate as if they do not exist". The map here is the whole drawn
    # map, not the dashed play boundary — a peak you can see on screen counts,
    # which is the reading the people playing expect.
    places = json.loads((DATA / "places_2026-10.json").read_text())
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
        play = shape(zones["berk" if name == "berkeley" else "zone"])
        # Everything the map draws, in lon/lat: the rectangle the basemap
        # covers, which is what a player sees and therefore what exists.
        x0, y0, w, h = payload["VB"]
        o = meta["origin"]
        sw = bx.unproject(o, x0, y0 + h)
        ne = bx.unproject(o, x0 + w, y0)
        area = shapely_box(sw[0], sw[1], ne[0], ne[1])

        def clip(pts):
            return [p for p in pts if area.contains(Point(p[0], p[1]))]

        poi = {k: clip([list(p) for p in poi_src.get(k, []) if not HONORARY(k, p)])
               for k in POI_KEYS}
        # Fresh places across the whole drawn map, with their full names —
        # the older set was clipped to the play boundary and cut names at 40
        # characters, which is how "Lawrence Hall of Science 3D Theater"
        # ended up being somebody's nearest movie theatre with no way to see
        # it coming.
        for key, tag in (("museum", "museum"), ("cinema", "cinema"), ("library", "library"),
                         ("hospital", "hospital"), ("peak", "peak"), ("zoo", "zoo"),
                         ("aquarium", "aquarium"), ("theme_park", "theme_park"),
                         ("golf", "golf_course"), ("airport", "aerodrome")):
            fresh = [[p[1], p[2], p[3]] for p in places["poi"] if p[0] == tag]
            if fresh:
                poi[key] = clip(fresh)
        # Named parks only: an unnamed patch of green is not "a park" anyone
        # could name as their nearest. Measured from the labelled point.
        poi["park"] = bx.parks(raw, area)
        # Rail stations are hiding stations too, and carry the lines that
        # stop at them for the Transit line question.
        # A stop whose routes nobody recorded cannot answer a Transit line
        # question, and pretending it is served by nothing ruled out real
        # hiding places. They are campus shuttle stops in the main; they come
        # out of the game.
        stops = [list(s) for s in payload["stops"] if s[3]]
        dropped = len(payload["stops"]) - len(stops)
        for st in payload["stations"]:
            ll = next(s for s in base["stations"] if s["n"] == st["n"])
            lines = bx.station_lines((ll["lon"], ll["lat"]), st["kind"], met)
            stops.append([st["x"], st["y"], st["n"], ";".join(lines),
                          "BART" if st["kind"] == "bart" else "Amtrak", st["kind"]])

        # Every city with real ground on the drawn map, not just the two the
        # play area sits in: the hider can be nearest to Albany or Emeryville
        # and the question has to be answerable.
        cities = []
        for c in places["cities"]:
            g = bx.city_shape(c)
            if g is None or g.is_empty:
                continue
            r = rings_of(g.intersection(area))
            if r and g.intersection(area).area * 111320 * 111320 * math.cos(math.radians(37.87)) > 1e5:
                cities.append({"n": c["n"], "r": r})
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
        print(f"      dropped {dropped} stops with no route data")
        have = ", ".join(f"{k}:{len(v)}" for k, v in poi.items() if v)
        miss = ", ".join(k for k, v in poi.items() if not v)
        kb = len(json.dumps(maps[name], separators=(",", ":"))) // 1024
        print(f"  {name}: {len(stops)} stations, {kb} KB")
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
    qr = (ROOT / "tools" / "vendor-qrcode.js").read_text()
    html = (TEMPLATE.read_text().replace("__MAPDATA__", blob)
            .replace("/*__QRCODE__*/", qr))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html)
    print(f"{OUT.relative_to(ROOT)}: {len(html) // 1024} KB")


if __name__ == "__main__":
    main()
