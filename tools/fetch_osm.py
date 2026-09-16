#!/usr/bin/env python3
"""Fetch the OpenStreetMap data the maps are built from.

Runs the queries in tools/overpass/ against an Overpass API endpoint and
writes three files into data/:

    mapdata.json       boundaries, routes, stops, stations, basemap layers
    freeways.json      named freeway carriageways (for the boundary cut)
    routemembers.json  route ref -> list of stop node ids

The repository already ships these files, so you only need to run this to
refresh the data against current OSM. Overpass is a shared public service:
the script pauses between queries and retries on 429/504 rather than
hammering it.

    python3 tools/fetch_osm.py

Map data is © OpenStreetMap contributors, available under the ODbL.
"""

import argparse
import json
import math
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
QUERIES = ROOT / "tools" / "overpass"
DATA = ROOT / "data"

DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter"

# Networks kept as drawn routes. Everything else in the bounding box
# (Flixbus, hospital shuttles, WestCAT, Emery Go-Round) is dropped.
KEEP_NETWORKS = {"AC Transit", "BART"}
KEEP_REFS = {"Capitol Corridor"}

# Coordinate simplification. Douglas-Peucker tolerances are in degrees;
# 0.00003 deg is roughly 3 m, well under a screen pixel at full zoom.
TOL_LINE = 0.00003
TOL_AREA = 0.00008
TOL_BOUNDARY = 0.00005
PRECISION = 5


def overpass(query, endpoint, attempts=4):
    """POST a query to Overpass, retrying on the transient failures."""
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            endpoint,
            data=query.encode("utf-8"),
            headers={"User-Agent": "jetlag-berkeley/1.0 (OSM map builder)"},
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 504) and attempt < attempts:
                wait = 15 * attempt
                print(f"  Overpass returned {e.code}; waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except urllib.error.URLError:
            if attempt < attempts:
                time.sleep(10 * attempt)
                continue
            raise
    raise RuntimeError("Overpass did not answer")


def simplify(points, tol):
    """Iterative Douglas-Peucker. `points` is a list of (lon, lat)."""
    if len(points) < 3:
        return points

    def seg_dist_sq(a, b, p):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = dx * dx + dy * dy
        t = 0.0 if length == 0 else ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length
        t = max(0.0, min(1.0, t))
        ex, ey = a[0] + t * dx - p[0], a[1] + t * dy - p[1]
        return ex * ex + ey * ey

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        best, best_d = -1, 0.0
        for k in range(i + 1, j):
            d = seg_dist_sq(points[i], points[j], points[k])
            if d > best_d:
                best_d, best = d, k
        if best_d > tol * tol:
            keep[best] = True
            stack.append((i, best))
            stack.append((best, j))
    return [p for p, k in zip(points, keep) if k]


def geom(element, tol):
    pts = [(g["lon"], g["lat"]) for g in element.get("geometry") or [] if g]
    return [
        [round(x, PRECISION), round(y, PRECISION)] for x, y in simplify(pts, tol)
    ]


def member_geom(member, tol):
    pts = [(g["lon"], g["lat"]) for g in member.get("geometry") or [] if g]
    return [
        [round(x, PRECISION), round(y, PRECISION)] for x, y in simplify(pts, tol)
    ]


def read_query(name):
    return (QUERIES / name).read_text()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT,
                    help="Overpass API endpoint (default: %(default)s)")
    ap.add_argument("--pause", type=float, default=8.0,
                    help="seconds to wait between queries (default: %(default)s)")
    args = ap.parse_args()

    DATA.mkdir(exist_ok=True)

    # --- 01 boundaries and the CA-24 carriageways ------------------------
    print("1/5 boundaries and CA-24")
    d1 = overpass(read_query("01-boundaries.overpassql"), args.endpoint)
    bnd, hwy24 = {}, []
    for e in d1["elements"]:
        if e["type"] == "relation":
            bnd[e["tags"]["name"].lower()] = [
                member_geom(m, TOL_BOUNDARY)
                for m in e["members"]
                if m["type"] == "way" and m.get("role") == "outer" and m.get("geometry")
            ]
        elif e["type"] == "way":
            hwy24.append(geom(e, TOL_LINE))
    time.sleep(args.pause)

    # --- 02 stops, stations and route relations --------------------------
    print("2/5 stops, stations and routes")
    d2 = overpass(read_query("02-stops-and-routes.overpassql"), args.endpoint)

    stops = [
        {
            "id": e["id"],
            "n": e["tags"].get("name", ""),
            "lat": round(e["lat"], PRECISION),
            "lon": round(e["lon"], PRECISION),
            "op": e["tags"].get("operator") or e["tags"].get("network") or "",
            "r": e["tags"].get("route_ref", ""),
        }
        for e in d2["elements"]
        if e["type"] == "node" and e["tags"].get("highway") == "bus_stop"
    ]
    stations = [
        {
            "id": e["id"],
            "n": e["tags"].get("name", ""),
            "lat": round(e["lat"], PRECISION),
            "lon": round(e["lon"], PRECISION),
            "op": e["tags"].get("operator") or e["tags"].get("network") or "",
            "st": e["tags"].get("station") or e["tags"].get("railway") or "",
        }
        for e in d2["elements"]
        if e["type"] == "node"
        and (
            e["tags"].get("railway") == "station"
            or e["tags"].get("public_transport") == "station"
        )
    ]

    # One relation per (network, ref): OSM stores each direction, and often
    # each variant, as a separate relation.
    by_ref = {}
    for e in d2["elements"]:
        if e["type"] != "relation":
            continue
        tags = e["tags"]
        net, ref = tags.get("network"), tags.get("ref")
        if net not in KEEP_NETWORKS and ref not in KEEP_REFS:
            continue
        if not ref:
            continue
        by_ref.setdefault((net, ref), e)
    rels = list(by_ref.values())
    ids = [r["id"] for r in rels]
    print(f"    {len(stops)} stops, {len(stations)} stations, {len(rels)} routes")
    time.sleep(args.pause)

    # --- 03 route geometry and membership --------------------------------
    print("3/5 route geometry")
    id_list = ",".join(str(i) for i in ids)
    d3 = overpass(
        read_query("03-route-geometry.overpassql").replace("{{IDS}}", id_list),
        args.endpoint,
    )
    way_geom = {w["id"]: geom(w, TOL_LINE) for w in d3["elements"] if w["type"] == "way"}
    time.sleep(args.pause)

    print("4/5 route membership")
    d4 = overpass(
        f"[out:json][timeout:180];\nrelation(id:{id_list});\nout body;", args.endpoint
    )
    stop_ids = {s["id"] for s in stops}
    routes, members = [], {}
    for rel in d4["elements"]:
        tags = rel.get("tags", {})
        ref = tags.get("ref")
        routes.append(
            {
                "ref": ref,
                "network": tags.get("network"),
                "name": tags.get("name"),
                "colour": tags.get("colour"),
                "ways": [
                    way_geom[m["ref"]]
                    for m in rel.get("members", [])
                    if m["type"] == "way" and m["ref"] in way_geom
                ],
            }
        )
        members[ref] = [
            m["ref"]
            for m in rel.get("members", [])
            if m["type"] == "node" and m["ref"] in stop_ids
        ]
    time.sleep(args.pause)

    # --- 05 basemap -------------------------------------------------------
    print("5/5 basemap")
    d5 = overpass(read_query("04-basemap.overpassql"), args.endpoint)
    base = {k: [] for k in (
        "motorway", "trunk", "primary", "secondary", "tertiary",
        "coast", "water", "park", "campus", "rail", "subway", "names",
    )}

    def push(key, element, tol):
        if element["type"] == "way":
            base[key].append(geom(element, tol))
        else:
            for m in element.get("members", []):
                if m["type"] == "way" and m.get("geometry") and m.get("role") in ("outer", ""):
                    base[key].append(member_geom(m, tol))

    seen_names = set()
    for e in d5["elements"]:
        tags = e.get("tags", {})
        if "highway" in tags:
            hw = tags["highway"]
            if hw == "motorway_link":
                base["motorway"].append(geom(e, TOL_BOUNDARY))
            else:
                key = hw.replace("_link", "")
                if key in base:
                    push(key, e, 0.00004)
                    name = tags.get("name")
                    if name and key in ("primary", "secondary") and name not in seen_names:
                        seen_names.add(name)
                        mid = e["geometry"][len(e["geometry"]) // 2]
                        base["names"].append(
                            [name, round(mid["lon"], PRECISION), round(mid["lat"], PRECISION)]
                        )
        elif tags.get("natural") == "coastline":
            push("coast", e, TOL_BOUNDARY)
        elif tags.get("natural") == "water":
            push("water", e, TOL_AREA)
        elif tags.get("amenity") == "university":
            push("campus", e, TOL_AREA)
        elif tags.get("leisure") == "park":
            push("park", e, 0.0001)
        elif tags.get("railway") == "rail":
            push("rail", e, TOL_BOUNDARY)
        elif tags.get("railway") == "subway":
            push("subway", e, TOL_BOUNDARY)

    time.sleep(args.pause)

    # --- freeways ---------------------------------------------------------
    print("freeways")
    d6 = overpass(read_query("05-freeways.overpassql"), args.endpoint)
    freeways = [
        {
            "id": w["id"],
            "ref": w["tags"].get("ref"),
            "name": w["tags"].get("name", ""),
            "g": [
                [round(g["lon"], PRECISION), round(g["lat"], PRECISION)]
                for g in w["geometry"]
            ],
        }
        for w in d6["elements"]
        if w["type"] == "way"
    ]

    (DATA / "mapdata.json").write_text(json.dumps(
        {"bnd": bnd, "hwy24": hwy24, "routes": routes,
         "stops": stops, "stations": stations, "base": base},
        separators=(",", ":"),
    ))
    (DATA / "freeways.json").write_text(json.dumps(freeways, separators=(",", ":")))
    (DATA / "routemembers.json").write_text(json.dumps(members, separators=(",", ":")))
    print(f"\nWrote {DATA}/mapdata.json, freeways.json, routemembers.json")
    print("Now run: python3 tools/make_zone.py && python3 tools/build_map.py --all")


if __name__ == "__main__":
    main()
