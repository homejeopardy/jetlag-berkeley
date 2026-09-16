// Everything the map draws underneath the game layer: the road hierarchy,
// the shoreline, water bodies, parks, the university campus and rail.
[out:json][timeout:180][maxsize:300000000];
(
  way["highway"~"^(motorway|motorway_link|trunk|primary|secondary|tertiary)$"](37.80,-122.34,37.92,-122.20);
  way["natural"="coastline"](37.80,-122.34,37.92,-122.20);
  way["natural"="water"](37.80,-122.34,37.92,-122.20);
  relation["natural"="water"](37.80,-122.34,37.92,-122.20);
  way["amenity"="university"]["name"~"University of California"](37.80,-122.34,37.92,-122.20);
  relation["amenity"="university"]["name"~"University of California"](37.80,-122.34,37.92,-122.20);
  way["leisure"="park"](37.80,-122.34,37.92,-122.20)(if: length() > 1500);
  relation["leisure"="park"](37.80,-122.34,37.92,-122.20);
  way["railway"~"^(rail|subway)$"](37.80,-122.34,37.92,-122.20);
);
out geom;
