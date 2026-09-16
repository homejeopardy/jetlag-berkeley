// City boundaries for Berkeley and Oakland, plus the CA-24 motorway
// carriageways used to cut Oakland in half.
[out:json][timeout:120];
(
  relation["boundary"="administrative"]["admin_level"="8"]["name"="Berkeley"](37.8,-122.35,37.95,-122.2);
  relation["boundary"="administrative"]["admin_level"="8"]["name"="Oakland"](37.7,-122.35,37.9,-122.1);
  way["highway"="motorway"]["ref"~"CA 24"](37.82,-122.3,37.9,-122.15);
);
out geom;
