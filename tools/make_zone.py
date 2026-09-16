#!/usr/bin/env python3
"""Compute the game zone polygons.

Berkeley's zone is simply the city limits. The combined zone is Berkeley
plus the part of Oakland north of Highway 24 — which takes a little work,
because "north of Highway 24" is not a line OSM hands you:

  * CA-24 is mapped as separate carriageways per direction, with gaps at
    interchanges, so the pieces are unioned and buffered into one ribbon
    before they can cut anything.
  * CA-24 ends at the I-580/I-980 interchange, roughly a mile short of the
    Oakland city line. Left there, the cut leaks and the "northern" piece
    is the whole city. The cut therefore continues west along I-580 to the
    Emeryville line, and a short connector closes the gap between the two
    freeways at the interchange.

Writes data/zone.json with the zone, the two halves, and the cut line
(drawn on the map as a faint band under the boundary).

    python3 tools/make_zone.py
"""

import json
import pathlib

from shapely.geometry import LineString, mapping
from shapely.ops import linemerge, nearest_points, polygonize, unary_union

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Buffer half-width for the freeway ribbon, in degrees (~33 m). Wide enough
# to bridge the gaps between mapped carriageways, narrow enough not to eat
# the blocks either side.
RIBBON = 0.0003

# The I-580 carriageways that form the western half of the cut: west of the
# CA-24 interchange and north of the Oakland/San Leandro end of the freeway.
I580_WEST_OF = -122.23
I580_NORTH_OF = 37.815

# A fragment of Oakland counts as "north" if it touches Berkeley and sits
# above this latitude, which excludes the slivers left behind inside the
# interchange itself.
NORTH_OF = 37.84


def rings_to_polygon(rings):
    """Build a polygon from a boundary relation's outer ways."""
    lines = [LineString(r) for r in rings if len(r) > 1]
    merged = linemerge(unary_union(lines))
    return max(polygonize(merged), key=lambda p: p.area)


def main():
    data = json.loads((DATA / "mapdata.json").read_text())
    freeways = json.loads((DATA / "freeways.json").read_text())

    berkeley = rings_to_polygon(data["bnd"]["berkeley"])
    oakland = rings_to_polygon(data["bnd"]["oakland"])

    ca24 = [LineString(w["g"]) for w in freeways if w["ref"] == "CA 24"]
    i580 = [
        LineString(w["g"])
        for w in freeways
        if w["ref"] in ("I 580", "I 80;I 580")
        and LineString(w["g"]).centroid.x < I580_WEST_OF
        and LineString(w["g"]).centroid.y > I580_NORTH_OF
    ]
    if not ca24 or not i580:
        raise SystemExit("Freeway data is missing CA-24 or I-580 carriageways")

    # Close the interchange gap so the ribbon is one connected cut.
    a, b = nearest_points(unary_union(ca24), unary_union(i580))
    connector = LineString([a, b])
    cut = unary_union(ca24 + i580 + [connector])

    pieces = sorted(oakland.difference(cut.buffer(RIBBON)).geoms,
                    key=lambda p: -p.area)
    north = [
        p for p in pieces
        if p.intersects(berkeley.buffer(0.001)) and p.centroid.y > NORTH_OF
    ]
    if not north:
        raise SystemExit("No Oakland fragment north of the cut — check the cut geometry")
    oakland_north = unary_union(north)

    # The tiny buffer in/out welds Berkeley to North Oakland across the
    # shared boundary, which the two polygons only touch along.
    zone = (
        unary_union([berkeley, oakland_north])
        .buffer(0.00002)
        .buffer(-0.00001)
        .simplify(0.00002)
    )

    (DATA / "zone.json").write_text(json.dumps({
        "zone": mapping(zone),
        "berk": mapping(berkeley),
        "oakN": mapping(oakland_north),
        "cut": mapping(cut),
    }))
    km2 = zone.area * (111.0 ** 2) * 0.79  # rough, at this latitude
    print(f"Wrote {DATA}/zone.json")
    print(f"  Berkeley + North Oakland: about {km2:.0f} km2")


if __name__ == "__main__":
    main()
