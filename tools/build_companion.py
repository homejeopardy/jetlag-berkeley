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
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from build_map import compute  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "tools" / "companion_template.html"
OUT = ROOT / "companion" / "index.html"

# Layers the companion draws, in paint order. `cut` (the Highway 24 band)
# only means anything on the combined zone.
LAYERS = [
    "parks", "campus", "water", "tertiary", "secondary", "primary",
    "motorway", "rail", "cut", "bart", "amtrak", "zone", "oob",
]

ZONES = {
    "berkeley": {"label": "Berkeley", "drop": ["cut"]},
    "berkeley-north-oakland": {"label": "Berkeley + N. Oakland", "drop": []},
}


def main():
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

    blob = json.dumps(maps, separators=(",", ":"), ensure_ascii=False)
    html = TEMPLATE.read_text().replace("__MAPDATA__", blob)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html)
    print(f"{OUT.relative_to(ROOT)}: {len(html) // 1024} KB")


if __name__ == "__main__":
    main()
