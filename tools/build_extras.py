"""Reference data the questions need beyond the drawn map.

Everything here comes from data/fetched_2026-09.json (OpenStreetMap via
Overpass, plus AWS terrain tiles) and data/sidewalks_2026-09.json, and is
reduced to exactly what the companion measures against:

  streets   every street or path, as the rulebook defines one: a named
            street runs for as long as its name does (pieces of one name
            within STREET_GAP of each other are one street — Berkeley's
            traffic diverters break the mapped line every few blocks);
            an unnamed one ends at every intersection. Sidewalks, crossings,
            driveways and parking aisles are part of the street beside
            them, not streets of their own.
  terrain   elevation grid for Sea level (AWS terrain tiles, USGS 3DEP).
  water     named bodies of water on the map (pools and fountains excluded),
            with San Francisco Bay as its shoreline.
  parks     named parks on the map, as the point a map labels them at.
  county    the Alameda / Contra Costa line, and the two sides of it.
  metro     BART line geometry, for the Metro lines tentacle.
"""
import json, math, pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STREET_GAP_M = 1000
K_LON = math.cos(math.radians(37.87)) * 111320 / 1e5   # metres per 1e-5 deg lon
K_LAT = 111320 / 1e5


def load_raw():
    return json.loads((DATA / "fetched_2026-09.json").read_text())


def decode_parts(body):
    out = []
    for part in body.split(";"):
        v = [int(t) for t in part.split(",")]
        x = y = 0
        pts = []
        for i in range(0, len(v), 2):
            x += v[i]; y += v[i + 1]
            pts.append((x, y))
        out.append((part, pts))
    return out


def encode(pts):
    f = [pts[0][0], pts[0][1]]
    for a, b in zip(pts, pts[1:]):
        f += [b[0] - a[0], b[1] - a[1]]
    return ",".join(map(str, f))


class UF:
    def __init__(s): s.p = {}
    def f(s, a):
        s.p.setdefault(a, a)
        while s.p[a] != a:
            s.p[a] = s.p[s.p[a]]; a = s.p[a]
        return a
    def u(s, a, b): s.p[s.f(a)] = s.f(b)


def streets(raw, bbox):
    """-> list of (name, kind, [polyline]) entities, clipped to bbox (1e-5 ints)."""
    swl = json.loads((DATA / "sidewalks_2026-09.json").read_text())["sw"].split("\n")
    side = {l.split("|")[1] for l in swl}
    ways = []
    for line in raw["streets"].split("\n"):
        nm, body = line.split("|")
        for enc, pts in decode_parts(body):
            if enc in side or len(pts) < 2:
                continue
            ways.append((nm, pts))
    x0, y0, x1, y1 = bbox
    ways = [w for w in ways if any(x0 <= x <= x1 and y0 <= y <= y1 for x, y in w[1])]

    # How many segments meet at each vertex, across every way.
    deg = defaultdict(int)
    for _, pts in ways:
        for a, b in zip(pts, pts[1:]):
            deg[a] += 1; deg[b] += 1

    ents = []
    # Named: one street per name, joined across small gaps.
    byname = defaultdict(list)
    for i, (nm, pts) in enumerate(ways):
        if nm[0] != "~":
            byname[nm].append(i)
    for nm, ids in byname.items():
        uf = UF()
        at = {}
        for i in ids:
            uf.f(i)
            for p in ways[i][1]:
                if p in at: uf.u(i, at[p])
                else: at[p] = i
        groups = defaultdict(list)
        for i in ids: groups[uf.f(i)].append(i)
        gl = list(groups.values())
        # single-link merge of components closer than STREET_GAP_M
        uf2 = UF()
        samp = [[p for i in g for p in ways[i][1]] for g in gl]
        for a in range(len(gl)):
            uf2.f(a)
            for b in range(a + 1, len(gl)):
                best = 1e18
                for p in samp[a]:
                    for q in samp[b]:
                        d = (p[0] - q[0]) ** 2 * K_LON ** 2 + (p[1] - q[1]) ** 2 * K_LAT ** 2
                        if d < best: best = d
                if best <= STREET_GAP_M ** 2:
                    uf2.u(a, b)
        merged = defaultdict(list)
        for a in range(len(gl)): merged[uf2.f(a)] += gl[a]
        for g in merged.values():
            ents.append((nm, "", [ways[i][1] for i in g]))

    # Unnamed: chains of unnamed segments, cut at every vertex where three or
    # more segments meet (an intersection with anything, named or not).
    segs = []
    for i, (nm, pts) in enumerate(ways):
        if nm[0] == "~":
            for a, b in zip(pts, pts[1:]):
                if a != b: segs.append((a, b, nm[1:]))
    uf = UF()
    ends = defaultdict(list)
    for k, (a, b, t) in enumerate(segs):
        uf.f(k); ends[a].append(k); ends[b].append(k)
    for v, ks in ends.items():
        if deg[v] == 2 and len(ks) == 2:
            uf.u(ks[0], ks[1])
    groups = defaultdict(list)
    for k in range(len(segs)): groups[uf.f(k)].append(k)
    for ks in groups.values():
        # stitch the chain back into polylines
        lines = [[segs[k][0], segs[k][1]] for k in ks]
        kinds = defaultdict(int)
        for k in ks: kinds[segs[k][2]] += 1
        kind = max(kinds, key=kinds.get)
        ents.append(("", kind, stitch(lines)))
    return ents


def stitch(lines):
    """Join 2-point segments end to end where they meet."""
    adj = defaultdict(list)
    for i, (a, b) in enumerate(lines):
        adj[a].append(i); adj[b].append(i)
    used = [False] * len(lines)
    out = []
    for i in range(len(lines)):
        if used[i]: continue
        used[i] = True
        a, b = lines[i]
        path = [a, b]
        for end in (1, 0):
            while True:
                tip = path[-1] if end else path[0]
                nxt = [j for j in adj[tip] if not used[j]]
                if len(nxt) != 1 or len(adj[tip]) != 2: break
                j = nxt[0]; used[j] = True
                p, q = lines[j]
                other = q if p == tip else p
                if end: path.append(other)
                else: path.insert(0, other)
        out.append(path)
    return out


def streets_blob(ents):
    lines = []
    for nm, kind, polys in ents:
        lines.append(nm.replace("|", "/") + "|" + kind + "|" + ";".join(encode(p) for p in polys))
    return "\n".join(lines)


def terrain(raw):
    """The grid covering the whole map with a mile or more to spare
    (data/terrain_2026-09.json); the first fetch stopped short of the hills."""
    d = json.loads((DATA / "terrain_2026-09.json").read_text())["dem"]
    d = json.loads(d) if isinstance(d, str) else d
    return crop_terrain(d, -122.392, 37.808, -122.190, 37.924)


def crop_terrain(d, lon0, lat0, lon1, lat1):
    """Only the posts within reach of the map: the zone plus well over a
    mile, which is further than any hiding zone or seeker can be."""
    import base64, struct
    nx, ny = d["nx"], d["ny"]
    v = struct.unpack("<%dh" % (nx * ny), base64.b64decode(d["b64"]))
    i0 = max(0, int((lon0 - d["x0"]) / d["dx"])); i1 = min(nx - 1, int((lon1 - d["x0"]) / d["dx"]) + 1)
    j0 = max(0, int((lat0 - d["y0"]) / d["dy"])); j1 = min(ny - 1, int((lat1 - d["y0"]) / d["dy"]) + 1)
    out = []
    for j in range(j0, j1 + 1):
        out.extend(v[j * nx + i0: j * nx + i1 + 1])
    return dict(d, x0=round(d["x0"] + i0 * d["dx"], 6), y0=round(d["y0"] + j0 * d["dy"], 6),
                nx=i1 - i0 + 1, ny=j1 - j0 + 1,
                b64=base64.b64encode(struct.pack("<%dh" % len(out), *out)).decode())


EXCLUDE_WATER = ("Pool", "Fountain")   # the card excludes pools; a fountain is not a body of water


def water(raw, area):
    from shapely.geometry import Polygon
    out = []
    for p in raw["pw"]:
        if p["k"] not in ("water", "bay") or not p.get("n"):
            continue
        if any(w in p["n"] for w in EXCLUDE_WATER):
            continue
        rings = [pt["g"] for pt in p["parts"] if len(pt["g"]) > 3]
        polys = [Polygon(pt["g"]) for pt in p["parts"] if pt["r"] == "outer" and len(pt["g"]) > 3]
        if any(q.is_valid and q.intersects(area) for q in polys):
            out.append({"n": p["n"], "r": [[[round(x, 5), round(y, 5)] for x, y in r] for r in rings]})
    return out


def parks(raw, area):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    out = []
    for p in raw["pw"]:
        if p["k"] != "park" or not p.get("n"):
            continue
        outer = [Polygon(pt["g"]).buffer(0) for pt in p["parts"] if pt["r"] == "outer" and len(pt["g"]) > 3]
        if not outer: continue
        g = unary_union(outer)
        if g.is_empty or not g.intersects(area): continue
        c = g.centroid
        if not g.contains(c): c = g.representative_point()
        out.append([round(c.x, 5), round(c.y, 5), p["n"]])
    return out


def county(raw):
    from shapely.geometry import LineString, box, Point
    from shapely.ops import unary_union, polygonize, linemerge
    m = linemerge(unary_union([LineString(l) for l in raw["county"]]))
    coords = list(m.coords)
    if coords[0][0] > coords[-1][0]: coords.reverse()
    # Extend the western end out across open water so the line splits the
    # frame; nothing is anywhere near that stretch of bay.
    ext = [(-122.45, coords[0][1])] + coords
    B = box(-122.44, 37.78, -122.18, 37.95)
    faces = list(polygonize(unary_union([LineString(ext), B.exterior])))
    ala = [f for f in faces if f.contains(Point(-122.268, 37.870))]
    cc = [f for f in faces if f.contains(Point(-122.2504, 37.8962))]
    assert len(ala) == 1 and len(cc) == 1 and ala[0] != cc[0]
    assert len(faces) == 2, len(faces)
    ring = lambda f: [[round(x, 5), round(y, 5)] for x, y in f.exterior.coords]
    return ({"n": "Alameda County", "r": [ring(ala[0])]},
            {"n": "Contra Costa County", "r": [ring(cc[0])]},
            [[round(x, 5), round(y, 5)] for x, y in coords])


def metro(base):
    out = {}
    for r in base["routes"]:
        if r.get("ref") in ("Yellow", "Orange", "Red"):
            ways = [w for w in r["ways"] if len(w) > 1 and w[0] != w[-1]]
            out[r["ref"]] = [[[round(x, 5), round(y, 5)] for x, y in w] for w in ways]
    return out


def seg_dist_m(p, a, b):
    ax, ay = (a[0] - p[0]) * K_LON * 1e5, (a[1] - p[1]) * K_LAT * 1e5
    bx, by = (b[0] - p[0]) * K_LON * 1e5, (b[1] - p[1]) * K_LAT * 1e5
    vx, vy = bx - ax, by - ay
    L = vx * vx + vy * vy
    t = 0 if not L else max(0, min(1, -(ax * vx + ay * vy) / L))
    return math.hypot(ax + t * vx, ay + t * vy)


def station_lines(st_lonlat, kind, met):
    """Which lines stop at a rail station: BART lines whose track passes
    within 150 m of it; Amtrak stations are Capitol Corridor."""
    if kind == "amtrak":
        return ["Capitol Corridor"]
    got = []
    for ref in ("Yellow", "Orange", "Red"):
        d = min(seg_dist_m(st_lonlat, a, b) for w in met.get(ref, []) for a, b in zip(w, w[1:]))
        if d < 150: got.append(ref)
    return got
