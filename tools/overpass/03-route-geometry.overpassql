// Way geometry for the route relations selected from query 02, clipped to
// the play area. {{IDS}} is substituted by fetch_osm.py with one relation
// per (network, ref) pair.
//
// A second request fetches the relations' member lists so stops can be
// attributed to routes:
//
//   [out:json][timeout:180];
//   relation(id:{{IDS}});
//   out body;
[out:json][timeout:180][maxsize:200000000];
relation(id:{{IDS}})->.r;
way(r.r)(37.815,-122.33,37.915,-122.21);
out geom;
