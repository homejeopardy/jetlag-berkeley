# Jet Lag: Hide + Seek — Berkeley

Maps and a phone companion for playing [Jet Lag: The Game](https://jetlagthegame.com/)'s
Hide + Seek in Berkeley and North Oakland, built from OpenStreetMap data.

There are two maps and one companion app. The maps show every bus stop and
rail station inside the game zone, drawn in the show's visual language —
dashed boundary, hatched out-of-bounds, one colour per bus line. The
companion is what the players actually hold during a round: seekers send
questions through it, the hider answers, and everything syncs across
phones. Neither tool works out where the hider is. That part is the game.

![The Berkeley map](screenshots/berkeley.png)

## The maps

`maps/berkeley.html` is the Berkeley city limits, shoreline to the Tilden
ridge: 585 bus stops, four rail stations, fifteen AC Transit lines. It fits
a small game — a 30-minute hiding period and a quarter-mile hiding zone.

`maps/berkeley-north-oakland.html` adds Oakland north of Highway 24: 714
stops, six stations. Bigger, and it brings Rockridge and MacArthur BART
into play.

With GitHub Pages turned on they are live at
`https://homejeopardy.github.io/jetlag-berkeley/`, which is the easy way
to open one on a phone mid-game.

Both are single self-contained HTML files. Open one in a browser and it
works offline from then on, which matters when you are on a platform with
one bar of signal. Drag to pan, pinch or scroll to zoom, hover or tap a
stop for its name and routes, and tap a route chip in the legend to
highlight just that line and the stops it serves.

### Where the boundary comes from

Berkeley's zone is the city limits, trimmed at the shoreline — the legal
boundary runs out into the bay, and a line drawn across open water is a
line nobody can walk.

"Oakland north of Highway 24" needed more care, because that is not a line
OpenStreetMap hands you. CA-24 is mapped as one way per carriageway with
gaps at every interchange, so the pieces get unioned and buffered into a
single ribbon before they can cut anything. The bigger problem is that
CA-24 ends at the I-580/I-980 interchange, about a mile short of the
Oakland city line: cut there and the boundary leaks, and the "northern"
piece comes back as the entire city. The cut therefore continues west along
I-580 to the Emeryville line, with a short connector closing the gap at the
interchange. That whole line is drawn on the map as a faint band under the
boundary so you can see what the rule actually means on the ground.

Rockridge and MacArthur BART sit in the freeway median right on that
boundary. They are drawn and marked `(edge)` rather than quietly included
or excluded — whether they count is a house rule, not something a map
should decide for you.

## The companion

`companion/index.html` is a phone app for running a round. Everyone opens
it, picks a name and a role, and creates or joins a game with a four-letter
code.

Seekers pick from the real question deck — Matching, Measuring, Radar,
Thermometer, Photo, and Tentacles in medium and large games — and send a
question. It lands in the hider's inbox with the draw-and-keep count for
that category. The hider taps Yes/No, Closer/Further, Hotter/Colder, takes
a photo straight from the camera, or vetoes. The answer flows back to a
shared feed on every phone. The hider also logs kept cards (seekers see the
count, not the cards) and can send curses and notes. The status card runs
the hiding-period countdown and the hider's clock, and finished rounds land
on a scoreboard.

Question text, category draw counts, hiding periods, zone radii and photo
time limits follow the published Hide + Seek rules; the size of the game
switches which cards are available.

The companion needs a shared datastore to relay between phones, which it
gets from the claude.ai artifact runtime (`claude.use("db")`). Served as a
plain static file it degrades to an explanation of that, so if you want to
run it elsewhere, swap the `db` and `assets` calls for whatever backend you
like — the data model is three collections: `games/{code}`, its
`questions`, and its `messages`.

## Building

The repository ships the OSM extract it was built from, so a build needs no
network:

```
pip install shapely
python3 tools/make_zone.py      # boundary polygons -> data/zone.json
python3 tools/build_map.py --all
```

To refresh against current OpenStreetMap data:

```
python3 tools/fetch_osm.py      # re-runs the Overpass queries
```

Overpass is a shared public service; the fetch script pauses between
queries and backs off on rate limits. The queries themselves are in
`tools/overpass/`, readable on their own if you want to adapt this to
another city.

### Putting it online

The maps are static files, so GitHub Pages serves them as-is: in the
repository settings, under Pages, deploy from the `main` branch at the
repository root. The landing page is then at
`https://homejeopardy.github.io/jetlag-berkeley/` and the maps under
`/maps/`. The companion is not served from there — it needs a datastore.

```
index.html     landing page, for GitHub Pages
maps/          the two built map pages
companion/     the phone app
tools/         fetch, zone and build scripts, plus the page template
  overpass/    the OSM queries, one file each
data/          the OSM extract and the computed zone polygons
screenshots/   images used by this README
```

`build_map.py` projects to Web Mercator with the origin at the zone
centroid, writes each layer as one SVG path using relative `lineto`
commands, and simplifies geometry to roughly three metres — together that
gets a whole city's street network, 700-odd stops and thirty bus routes
into a 300 KB file that pans smoothly on a phone.

Adapting this to another city is mostly a matter of the bounding boxes in
`tools/overpass/`, the city names in query 01, and the route colours and
hand-placed labels at the top of `tools/build_map.py`. The zone logic in
`make_zone.py` is specific to cutting a city along a freeway; if your zone
is just a city limit, you can delete most of it.

## Credits and licence

Map data © OpenStreetMap contributors, available under the
[Open Database License](https://www.openstreetmap.org/copyright). Transit
data is whatever OSM has for AC Transit, BART and Amtrak, which is good but
not authoritative — check a stop against AC Transit before betting a round
on it.

Hide + Seek is a game by [Jet Lag: The Game](https://jetlagthegame.com/).
This is an unofficial fan-made tool, not affiliated with or endorsed by
them; buy the home game from them, it's good.

The code here is MIT licensed. See [LICENSE](LICENSE).
