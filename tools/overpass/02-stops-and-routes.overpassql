// Every bus stop and rail station in the play area, plus the route
// relations that serve them. `out tags center` keeps the response small:
// relation geometry is fetched separately by query 03.
[out:json][timeout:180];
(
  node["highway"="bus_stop"](37.815,-122.33,37.915,-122.21);
  node["public_transport"="platform"]["bus"="yes"](37.815,-122.33,37.915,-122.21);
  node["railway"="station"](37.815,-122.33,37.915,-122.21);
  node["public_transport"="station"](37.815,-122.33,37.915,-122.21);
  relation["route"="bus"](37.815,-122.33,37.915,-122.21);
  relation["route"~"^(subway|light_rail|train)$"](37.815,-122.33,37.915,-122.21);
);
out tags center;
