// Named freeway carriageways, used to build the boundary cut. CA-24 stops
// at the I-580/I-980 interchange, so the cut continues west along I-580 to
// reach the Emeryville city line.
[out:json][timeout:120];
way["highway"="motorway"]["ref"~"I 580|I 980|I 80|CA 13|CA 24"](37.80,-122.34,37.92,-122.20);
out geom;
