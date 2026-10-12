#!/usr/bin/env python3
"""The paper map: one sheet, US Letter, the way the show holds one up.

Only what you need in a moving car — the play boundary, the rail lines and
their stations, the main roads, the water, and every hiding station as a
dot. No parks, no labels for things nobody will ask about, nothing that
turns to mud in a home printer. Each sheet prints black-friendly: the ink
is dark grey on white, the boundary is the heaviest line on the page.

    python3 tools/build_print.py
"""
import json, math, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from build_map import compute                                   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "maps"
# US Letter landscape at 96dpi, less a 0.3in margin all round.
PAGE_W, PAGE_H = 11 * 96, 8.5 * 96
PAD = 0.3 * 96

ZONES = {
    "berkeley": ("Berkeley", "¼ mile hiding zone"),
    "berkeley-north-oakland": ("Berkeley + North Oakland", "¼ mile zone · ½ mile in large games"),
}


def scale_bar(units_per_px, y, x):
    """A bar of a round number of miles, in map units (Mercator metres)."""
    best = None
    for miles in (0.25, 0.5, 1, 2, 5):
        px = miles * 1609.34 / units_per_px
        if 90 <= px <= 260:
            best = (miles, px)
    if not best:
        best = (1, 1609.34 / units_per_px)
    miles, px = best
    label = f"{miles:g} mile" + ("s" if miles != 1 else "")
    return (f'<g transform="translate({x} {y})" fill="#15171B">'
            f'<rect x="0" y="0" width="{px:.1f}" height="5"/>'
            f'<rect x="0" y="0" width="{px/2:.1f}" height="5" fill="#fff" stroke="#15171B"/>'
            f'<text x="{px+8:.1f}" y="6" font-size="11">{label}</text></g>')


def main():
    for name, (title, sub) in ZONES.items():
        mode, layers, payload, meta = compute(name)
        stops = [s for s in payload["stops"] if s[3]]
        # Crop to the play area and its stations, not the whole basemap: the
        # bay took half the sheet and the hills fell off the edge.
        xs = [s[0] for s in stops] + [st["x"] for st in payload["stations"]]
        ys = [s[1] for s in stops] + [st["y"] for st in payload["stations"]]
        mx, my = (max(xs) - min(xs)) * 0.07, (max(ys) - min(ys)) * 0.07
        x0, y0 = min(xs) - mx, min(ys) - my
        w, h = (max(xs) - min(xs)) + 2 * mx, (max(ys) - min(ys)) + 2 * my
        iw, ih = PAGE_W - 2 * PAD, PAGE_H - 2 * PAD - 96
        k = min(iw / w, ih / h)
        if w / h < iw / ih:                      # centre it on the sheet
            x0 -= (iw / k - w) / 2; w = iw / k
        else:
            y0 -= (ih / k - h) / 2; h = ih / k
        upx = 1 / k

        def path(d, **a):
            # every width here is in printed pixels, not map units
            a.setdefault("vector-effect", "non-scaling-stroke")
            at = " ".join(f'{q}="{v}"' for q, v in a.items())
            return f'<path d="{d}" {at}/>'

        g = []
        if layers.get("water"):
            g.append(path(layers["water"], fill="#D8E4EC", stroke="none"))
        for key, col, wdt in (("motorway", "#A8A49A", 2.6), ("primary", "#BFBBB1", 1.5),
                              ("secondary", "#D0CCC2", 0.9)):
            if layers.get(key):
                g.append(path(layers[key], fill="none", stroke=col, **{"stroke-width": str(wdt),
                              "stroke-linejoin": "round", "stroke-linecap": "round"}))
        if layers.get("rail"):
            g.append(path(layers["rail"], fill="none", stroke="#B0ACA2",
                          **{"stroke-width": "1", "stroke-dasharray": "5 4"}))
        if layers.get("amtrak"):
            g.append(path(layers["amtrak"], fill="none", stroke="#1F3F8A", **{"stroke-width": "2.2"}))
        if layers.get("bart"):
            g.append(path(layers["bart"], fill="none", stroke="#E07A1F", **{"stroke-width": "3.2"}))
        if layers.get("zone"):
            g.append(path(layers["zone"], fill="none", stroke="#15171B",
                          **{"stroke-width": "3.6", "stroke-dasharray": "13 7",
                             "stroke-linejoin": "round"}))
        # every hiding station: a dark dot with a white halo so it reads on
        # top of a road
        dots = "".join(f'M{s[0]} {s[1]}h.01' for s in stops)
        g.append(path(dots, fill="none", stroke="#fff", **{"stroke-width": "5.6", "stroke-linecap": "round"}))
        g.append(path(dots, fill="none", stroke="#15171B", **{"stroke-width": "3.2", "stroke-linecap": "round"}))
        for st in payload["stations"]:
            sx, sy, r = st["x"], st["y"], 7 * upx
            if st["kind"] == "amtrak":
                g.append(f'<rect x="{sx-r:.0f}" y="{sy-r:.0f}" width="{2*r:.0f}" height="{2*r:.0f}" '
                         f'fill="#fff" stroke="#1F3F8A" stroke-width="2.6" vector-effect="non-scaling-stroke"/>')
            else:
                g.append(f'<circle cx="{sx}" cy="{sy}" r="{r:.0f}" fill="#fff" stroke="#15171B" '
                         f'stroke-width="2.6" vector-effect="non-scaling-stroke"/>'
                         f'<circle cx="{sx}" cy="{sy}" r="{r/2.6:.0f}" fill="#15171B"/>')
            g.append(f'<text x="{sx}" y="{sy-r-5*upx:.0f}" font-size="{11*upx:.0f}" text-anchor="middle" '
                     f'font-family="Barlow Condensed, Arial Narrow, sans-serif" font-weight="800" '
                     f'fill="#15171B" stroke="#fff" stroke-width="{3.4*upx:.1f}" paint-order="stroke">'
                     f'{st["n"].upper()}</text>')

        svg = (f'<svg class="map" viewBox="{x0} {y0} {w} {h}" width="{w*k:.0f}" height="{h*k:.0f}">'
               + "".join(g) + "</svg>")
        bar = scale_bar(upx, 14, 0)
        html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{title} — Hide + Seek paper map</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;800&family=Barlow:wght@400;500&display=swap">
<style>
  @page {{ size: letter landscape; margin: 0.3in; }}
  html,body{{margin:0;background:#fff;color:#15171B;font-family:'Barlow',system-ui,sans-serif}}
  .sheet{{width:{PAGE_W-2*PAD:.0f}px;margin:0 auto;padding:{PAD:.0f}px 0}}
  header{{display:flex;align-items:flex-end;gap:14px;border-bottom:2.5px solid #15171B;padding-bottom:6px}}
  h1{{font-family:'Barlow Condensed','Arial Narrow',sans-serif;font-weight:800;text-transform:uppercase;
     font-size:27px;line-height:1;margin:0}}
  .sub{{font-size:12px;color:#44474D;flex:1;max-width:230px}}
  .legend{{display:flex;gap:14px;font-size:11px;align-items:center;white-space:nowrap}}
  .k{{display:inline-block;width:22px;height:0;border-top:3px solid #15171B;margin-right:4px;vertical-align:middle}}
  .k.bart{{border-top-color:#E07A1F}} .k.amtrak{{border-top-color:#1F3F8A;border-top-width:2px}}
  .k.zone{{border-top:3px dashed #15171B}}
  .dot{{display:inline-block;width:7px;height:7px;border:2px solid #15171B;border-radius:50%;background:#fff;margin-right:4px;vertical-align:middle}}
  .map{{display:block;margin:6px auto 0}}
  footer{{display:flex;justify-content:space-between;align-items:flex-end;font-size:11px;color:#44474D;margin-top:4px;gap:16px}}
  footer .note{{text-align:right;line-height:1.5;font-size:10px}}
  .note{{font-size:11px;color:#44474D}}
  @media screen{{ body{{background:#E9E6DE;padding:18px 0}} .sheet{{background:#fff;box-shadow:0 2px 14px rgba(0,0,0,.18)}} }}
  @media print{{ .hint{{display:none}} }}
</style></head>
<body>
<p class="hint" style="max-width:{PAGE_W-2*PAD:.0f}px;margin:0 auto 10px;font-size:13px">
  Print this at US Letter, landscape, “fit to page” off. One sheet per car.</p>
<div class="sheet">
  <header>
    <h1>Hide + Seek<br>{title}</h1>
    <div class="sub">{sub}<br>{len(stops)} hiding stations</div>
    <div class="legend">
      <span><i class="k zone"></i>play boundary</span>
      <span><i class="k bart"></i>BART</span>
      <span><i class="k amtrak"></i>Amtrak</span>
      <span><i class="dot"></i>hiding station</span>
    </div>
  </header>
  {svg}
  <footer>
    <svg width="300" height="22">{bar}</svg>
    <span class="note">homejeopardy.github.io/jetlag-berkeley · map data © OpenStreetMap contributors<br>
      hider: ______________ · round: ______________</span>
  </footer>
</div>
</body></html>"""
        p = OUT / f"print-{name}.html"
        p.write_text(html)
        print(f"{p.relative_to(ROOT)}: {len(html)//1024} KB, {len(stops)} stations")


if __name__ == "__main__":
    main()
