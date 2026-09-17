#!/usr/bin/env python3
"""Build the self-contained map pages.

Projects the OSM data to Web Mercator, turns every layer into a single SVG
path, works out which stops fall inside the game zone, and writes the result
into tools/map_template.html.

    python3 tools/build_map.py --all
    python3 tools/build_map.py berkeley

Each page ends up around 300 KB with no external requests beyond the web
font, so it works offline once loaded — which matters when you are standing
on a platform with one bar of signal.
"""

import argparse
import json
import math
import pathlib
import re

from shapely.geometry import LineString, Point, Polygon, box, shape
from shapely.ops import linemerge, polygonize, unary_union
from shapely.strtree import STRtree

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TEMPLATE = ROOT / "tools" / "map_template.html"
OUT = ROOT / "maps"

# AC Transit routes that run inside the zone get their own colour. Anything
# else AC Transit runs here is a Transbay or All-Nighter line, drawn thin
# and grey because it is a commuter run, not a way to move around the zone.
LOCAL_COLOURS = {
    "6": "#E4572E", "7": "#2A9D8F", "12": "#3A86FF", "18": "#8338EC",
    "22": "#FF006E", "27": "#FB8500", "36": "#06A77D", "51A": "#9D0208",
    "51B": "#C1121F", "52": "#7CB518", "57": "#BC6C25", "65": "#0077B6",
    "67": "#6A4C93", "71": "#4CC9F0", "72": "#D62828", "72M": "#D62828",
    "72L": "#D62828", "88": "#118AB2",
}
NIGHT_REFS = {"800", "802", "851"}
TRANSBAY_COLOUR = "#5B6770"
NIGHT_COLOUR = "#8A8F98"

# Labels, placed by hand: OSM's place nodes sit in the wrong spots for a
# map at this scale, and half of these neighbourhoods have no node at all.
PLACES = [
    ("UC Berkeley", -122.2535, 37.8745, "campus"),
    ("Southside", -122.2565, 37.8655, "hood"),
    ("Elmwood", -122.2525, 37.8585, "hood"),
    ("Claremont", -122.2415, 37.8595, "hood"),
    ("Rockridge", -122.2445, 37.8515, "hood"),
    ("Bushrod", -122.2665, 37.8425, "hood"),
    ("Golden Gate", -122.2805, 37.8395, "hood"),
    ("Lorin", -122.2745, 37.8495, "hood"),
    ("West Berkeley", -122.2985, 37.8665, "hood"),
    ("Northbrae", -122.2735, 37.8875, "hood"),
    ("Thousand Oaks", -122.2825, 37.8925, "hood"),
    ("Berkeley Hills", -122.2505, 37.8905, "hood"),
    ("Tilden Park", -122.2415, 37.9035, "park"),
    ("Berkeley Marina", -122.3155, 37.8655, "park"),
    ("Aquatic Park", -122.3015, 37.8585, "park"),
    ("Claremont Canyon", -122.2305, 37.8635, "park"),
    ("San Francisco Bay", -122.328, 37.845, "water"),
    ("Hwy 24", -122.235, 37.8565, "road"),
    ("I-80", -122.3055, 37.878, "road"),
    ("I-580", -122.277, 37.8285, "road"),
    ("Piedmont (out of bounds)", -122.245, 37.825, "oob"),
    ("Temescal (out of bounds)", -122.251, 37.834, "oob"),
    ("Emeryville (out of bounds)", -122.297, 37.8355, "oob"),
    ("Albany (out of bounds)", -122.302, 37.889, "oob"),
    ("Kensington (out of bounds)", -122.283, 37.907, "oob"),
    ("Orinda (out of bounds)", -122.203, 37.878, "oob"),
]

MODES = {
    "berkeley-north-oakland": {
        "zone_key": "zone",
        "view": (-122.335, 37.805, -122.19, 37.915),
        "title": "Berkeley Hide + Seek",
        "heading": "Berkeley &amp; North Oakland",
        "blurb": (
            "Game zone: all of Berkeley plus Oakland north of Highway 24 "
            "(and I-580 west of the 24 junction). Everything hatched is "
            "out of bounds."
        ),
        "drop_labels": set(),
        "add_labels": [],
    },
    "berkeley": {
        "zone_key": "berk",
        "view": (-122.33, 37.835, -122.215, 37.915),
        "title": "Berkeley Proper Hide + Seek",
        "heading": "Berkeley",
        "blurb": (
            "Game zone: the Berkeley city limits, shoreline to ridge. "
            "Oakland, Emeryville, Albany and Kensington are all out of "
            "bounds (hatched)."
        ),
        "drop_labels": {
            "Rockridge", "Bushrod", "Golden Gate", "Claremont", "Hwy 24",
            "I-580", "Piedmont (out of bounds)", "Temescal (out of bounds)",
            "Emeryville (out of bounds)", "Orinda (out of bounds)",
        },
        "add_labels": [
            ("Oakland (out of bounds)", -122.262, 37.841, "oob"),
            ("Emeryville (out of bounds)", -122.296, 37.842, "oob"),
            ("Oakland (out of bounds)", -122.236, 37.853, "oob"),
        ],
    },
}

EARTH_R = 6378137.0


def compute(mode_name):
    """Project one mode's geometry.

    Returns (mode, layers, payload): `layers` maps a layer name to one SVG
    path string, `payload` carries the viewBox, stops, stations, routes and
    labels. Split out from `build` so the companion app can reuse the same
    projection rather than re-deriving it.
    """
    mode = MODES[mode_name]
    data = json.loads((DATA / "mapdata.json").read_text())
    zones = json.loads((DATA / "zone.json").read_text())
    members = json.loads((DATA / "routemembers.json").read_text())

    zone = shape(zones[mode["zone_key"]])
    berkeley = shape(zones["berk"])
    oakland_north = shape(zones["oakN"])
    cut = shape(zones["cut"])

    # --- projection --------------------------------------------------------
    # Web Mercator, with the origin at the zone's centroid so the SVG
    # coordinates stay small, and y flipped to screen order.
    def mercator(lon, lat):
        return (
            EARTH_R * math.radians(lon),
            EARTH_R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)),
        )

    ox, oy = mercator(zone.centroid.x, zone.centroid.y)

    def project(lon, lat):
        x, y = mercator(lon, lat)
        return round(x - ox), round(oy - y)

    def path(coords, close=False):
        """One SVG path, written as relative lineto commands: about half the
        bytes of absolute coordinates across tens of thousands of points."""
        out, px, py = [], None, None
        for i, (lon, lat) in enumerate(coords):
            x, y = project(lon, lat)
            if i == 0:
                out.append(f"M{x} {y}")
            else:
                if (x, y) == (px, py):
                    continue
                out.append(f"l{x - px} {y - py}")
            px, py = x, y
        if close:
            out.append("Z")
        return "".join(out)

    def poly_path(geometry):
        parts = []
        for g in getattr(geometry, "geoms", [geometry]):
            if g.is_empty:
                continue
            parts.append(path(g.exterior.coords, True))
            for ring in g.interiors:
                parts.append(path(ring.coords, True))
        return "".join(parts)

    def lines_path(lines, clip=None):
        out = []
        for line in lines:
            if len(line) < 2:
                continue
            ls = LineString(line)
            if clip is None:
                out.append(path(line))
                continue
            clipped = ls.intersection(clip)
            if clipped.is_empty:
                continue
            for g in getattr(clipped, "geoms", [clipped]):
                if g.geom_type == "LineString" and len(g.coords) > 1:
                    out.append(path(g.coords))
        return "".join(out)

    vx0, vy0, vx1, vy1 = mode["view"]
    view = box(vx0, vy0, vx1, vy1)
    x0, y0 = project(vx0, vy1)
    x1, y1 = project(vx1, vy0)
    viewbox = (x0, y0, x1 - x0, y1 - y0)

    base = data["base"]

    # --- water -------------------------------------------------------------
    # OSM maps the bay as a coastline, which is a line, not an area. Cutting
    # the view box with it leaves several pieces; the wet ones are simply
    # those with no bus stop inside them.
    water_polys = []
    for ring in base["water"]:
        if len(ring) >= 4:
            try:
                pg = Polygon(ring)
                if pg.is_valid and pg.area > 2e-7:
                    water_polys.append(pg)
            except Exception:
                pass

    coast_lines = [LineString(c) for c in base["coast"] if len(c) > 1]
    merged = linemerge(unary_union(coast_lines))
    coast_parts = list(getattr(merged, "geoms", [merged]))
    pieces = list(polygonize(unary_union([view.exterior] + coast_parts)))
    tree = STRtree([Point(s["lon"], s["lat"]) for s in data["stops"]])
    bay_pieces = [
        p for p in pieces
        if p.area > 1e-5 and len(tree.query(p, predicate="contains")) == 0
    ]
    bay = unary_union(bay_pieces) if bay_pieces else Polygon()
    water = unary_union([bay] + water_polys)

    # Trim the zone at the shoreline: the city limits run out into the bay,
    # and a boundary drawn across open water is a boundary nobody can walk.
    zone = zone.difference(bay.buffer(0.00005))
    if hasattr(zone, "geoms"):
        zone = max(zone.geoms, key=lambda g: g.area)
    berkeley = berkeley.difference(bay.buffer(0.00005))

    parks = [Polygon(r) for r in base["park"] if len(r) >= 4]
    parks = [p for p in parks if p.is_valid and p.area > 3e-6]
    campus = [Polygon(r) for r in base["campus"] if len(r) >= 4]
    campus = [p for p in campus if p.is_valid]

    layers = {
        "water": poly_path(water),
        "parks": poly_path(unary_union(parks)) if parks else "",
        "campus": poly_path(unary_union(campus)) if campus else "",
        "residential": lines_path(base.get("residential", []), view),
        "tertiary": lines_path(base["tertiary"], view),
        "secondary": lines_path(base["secondary"], view),
        "primary": lines_path(base["primary"], view),
        "motorway": lines_path(base["motorway"], view),
        "rail": lines_path(base["rail"], view),
        "cut": lines_path(
            [list(g.coords) for g in getattr(cut, "geoms", [cut])], view
        ),
        "zone": poly_path(zone),
        "berk": poly_path(berkeley),
        "oakN": poly_path(oakland_north),
    }
    # Out-of-bounds hatching: the view box with the zone punched out of it,
    # filled with the even-odd rule.
    layers["oob"] = path(view.exterior.coords, True) + poly_path(zone)

    # --- bus routes --------------------------------------------------------
    routes = []
    for r in data["routes"]:
        if r["network"] != "AC Transit":
            continue
        ref = r["ref"]
        if ref in LOCAL_COLOURS:
            kind, colour = "local", LOCAL_COLOURS[ref]
        elif ref in NIGHT_REFS:
            kind, colour = "night", NIGHT_COLOUR
        else:
            kind, colour = "transbay", TRANSBAY_COLOUR
        d = lines_path(r["ways"], view)
        if not d:
            continue
        routes.append({"ref": ref, "kind": kind, "colour": colour,
                       "name": r["name"], "d": d})

    bart_ways, amtrak_ways = [], []
    for r in data["routes"]:
        if r["network"] == "BART":
            bart_ways += r["ways"]
        elif r["ref"] == "Capitol Corridor":
            amtrak_ways += r["ways"]
    layers["bart"] = lines_path(bart_ways, view)
    layers["amtrak"] = lines_path(amtrak_ways, view)

    # --- stops -------------------------------------------------------------
    # Two sources of route attribution, unioned: the stop's own route_ref
    # tag, which many stops carry, and the relations that list the stop as a
    # member, which covers the ones that don't.
    by_stop = {}
    for ref, ids in members.items():
        for node_id in ids:
            by_stop.setdefault(node_id, set()).add(ref)

    def ref_sort_key(ref):
        digits = re.sub(r"\D", "", ref)
        return (len(digits) if digits else 9, ref)

    stops = []
    for s in data["stops"]:
        if not zone.contains(Point(s["lon"], s["lat"])):
            continue
        refs = {x.strip() for x in s["r"].split(";") if x.strip()}
        refs |= by_stop.get(s["id"], set())
        x, y = project(s["lon"], s["lat"])
        stops.append([x, y, s["n"], ";".join(sorted(refs, key=ref_sort_key)), s["op"]])

    # Keep only routes that actually stop in the zone, so the legend is a
    # list of lines you can ride rather than lines that pass through.
    served = set()
    for s in stops:
        served |= {r for r in s[3].split(";") if r}
    routes = [r for r in routes if r["ref"] in served]
    order = {"transbay": 0, "night": 1, "local": 2}
    routes.sort(key=lambda r: (order[r["kind"]], ref_sort_key(r["ref"])))

    # Stations just outside the line are still worth drawing: Rockridge and
    # MacArthur sit in the freeway median right on the boundary, and whether
    # they count is a house rule, not something the map should decide.
    stations = []
    for s in data["stations"]:
        p = Point(s["lon"], s["lat"])
        if zone.distance(p) * 111000 > 120 or "Redwood" in s["n"]:
            continue
        x, y = project(s["lon"], s["lat"])
        stations.append({
            "n": s["n"],
            "x": x, "y": y,
            "kind": "bart" if "Rapid Transit" in s["op"] else "amtrak",
            "edge": not zone.contains(p),
        })

    places = [p for p in PLACES if p[0] not in mode["drop_labels"]]
    places += mode["add_labels"]
    places_out = []
    for name, lon, lat, kind in places:
        x, y = project(lon, lat)
        places_out.append({"n": name, "x": x, "y": y, "k": kind})

    payload = {
        "VB": viewbox,
        "stops": stops,
        "stations": stations,
        "routes": [
            {"ref": r["ref"], "kind": r["kind"], "color": r["colour"],
             "name": r["name"], "d": r["d"]}
            for r in routes
        ],
        "places": places_out,
    }
    # The projection origin, so a client that only has projected coordinates
    # (the companion) can place a live GPS fix on the same canvas.
    meta = {"origin": [round(ox, 2), round(oy, 2)]}
    return mode, layers, payload, meta


def build(mode_name, verbose=True):
    mode, layers, payload, _meta = compute(mode_name)

    html = TEMPLATE.read_text()
    html = (html
            .replace("__TITLE__", mode["title"])
            .replace("__HEADING__", mode["heading"])
            .replace("__BLURB__", mode["blurb"])
            .replace("__LAYERS__", json.dumps(layers, separators=(",", ":")))
            .replace("__DATA__", json.dumps(payload, separators=(",", ":"),
                                            ensure_ascii=False)))

    OUT.mkdir(exist_ok=True)
    out_path = OUT / f"{mode_name}.html"
    out_path.write_text(html)

    if verbose:
        local = sum(1 for r in payload["routes"] if r["kind"] == "local")
        print(f"{out_path.relative_to(ROOT)}: {len(payload['stops'])} stops, "
              f"{len(payload['stations'])} stations, {local} local routes, "
              f"{len(html) // 1024} KB")
    return out_path


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", nargs="?", choices=sorted(MODES),
                    help="which map to build")
    ap.add_argument("--all", action="store_true", help="build every map")
    args = ap.parse_args()
    if args.all or not args.mode:
        for name in sorted(MODES):
            build(name)
    else:
        build(args.mode)


if __name__ == "__main__":
    main()
