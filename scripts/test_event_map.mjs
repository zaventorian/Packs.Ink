// test_event_map.mjs — guards the multi-pin map's geometry.
//
//     node scripts/test_event_map.mjs
//
// Extracts the real functions out of Index.html, house pattern, so they cannot
// drift from what ships.
//
// Every case below is a SILENT failure. A map with a bad centre or zoom still
// renders a perfectly good picture of the wrong part of the world, and a pin
// whose index has drifted opens the wrong event while looking entirely normal.
// None of it throws, and none of it is visible in a screenshot unless you
// already know where the events were supposed to be.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8");
const NL = String.fromCharCode(10);
const grab = (a, b) => {
  const i = src.indexOf(a);
  if (i < 0) throw new Error("missing marker: " + a);
  const j = src.indexOf(b, i);
  if (j < 0) throw new Error("missing end: " + b);
  return src.slice(i, j + b.length);
};
const grabLine = (p) => {
  const l = src.split(/\r?\n/).find((x) => x.startsWith(p));
  if (!l) throw new Error("missing line: " + p);
  return l;
};

const mod = await import("data:text/javascript," + encodeURIComponent([
  grabLine("const OSM_TILE_PX = "),
  grabLine("const OSM_LAT_MAX = "),
  grab("const osmWorldFrac = (lat, lng) => {", NL + "};"),
  grabLine("const osmFracLat = "),
  grab("const osmTileLayout = (lat, lng, zoom, w, h) => {", NL + "};"),
  grabLine("const OSM_FIT_PAD = "),
  grab("const osmFitLayout = (points, w, h, opts) => {", NL + "};"),
  grabLine("const SC_PIN_MERGE_PX = "),
  grab("const scMergePins = (pins) => {", NL + "};"),
  "export {osmWorldFrac, osmFracLat, osmTileLayout, osmFitLayout, OSM_FIT_PAD,"
  + " scMergePins, SC_PIN_MERGE_PX};",
].join(NL)));

const { osmWorldFrac, osmFracLat, osmTileLayout, osmFitLayout, OSM_FIT_PAD,
        scMergePins, SC_PIN_MERGE_PX } = mod;

let pass = 0, fail = 0;
const ok = (cond, msg) => { if (cond) { pass++; } else { fail++; console.log("  FAIL: " + msg); } };
const near = (a, b, eps, msg) => ok(Math.abs(a - b) <= eps, msg + " (got " + a + ", want ~" + b + ")");
const section = (s) => console.log("\n" + s);

const W = 600, H = 360;
const P = (lat, lng) => ({ lat, lng });

// 1. The projection itself
section("1. osmWorldFrac / osmFracLat");
{
  const nullIsland = osmWorldFrac(0, 0);
  near(nullIsland.fx, 0.5, 1e-12, "lng 0 is half way across the world");
  near(nullIsland.fy, 0.5, 1e-12, "lat 0 is half way down the world");
  near(osmWorldFrac(0, -180).fx, 0, 1e-12, "lng -180 is the west edge");
  near(osmWorldFrac(0, 180).fx, 1, 1e-12, "lng 180 is the east edge");
  ok(osmWorldFrac(85, 0).fy < osmWorldFrac(-85, 0).fy, "north is above south");
  // The clamp is what stops a pole becoming Infinity and taking the whole map
  // with it — Mercator has no north pole.
  ok(isFinite(osmWorldFrac(90, 0).fy), "lat 90 is clamped, not Infinity");
  ok(isFinite(osmWorldFrac(-90, 0).fy), "lat -90 is clamped, not Infinity");
  // Round trip: the fit turns a projected centre back into a latitude.
  for (const lat of [-72, -33.9, 0, 21.3, 51.5, 78]) {
    near(osmFracLat(osmWorldFrac(lat, 0).fy), lat, 1e-9, "round trip lat " + lat);
  }
}

// 2. osmTileLayout still behaves as it always did
section("2. osmTileLayout (regression — it was refactored onto osmWorldFrac)");
{
  const l = osmTileLayout(41.88, -87.63, 11, W, H);
  ok(l !== null, "Chicago at z11 produces a layout");
  ok(l.pinLeft === W / 2 && l.pinTop === H / 2, "the single pin is the box centre");
  ok(l.zoom === 11, "zoom is honoured");
  ok(l.tiles.length > 0, "tiles cover the box");
  ok(typeof l.originX === "number" && typeof l.originY === "number",
     "originX/originY are exposed for callers placing their own pins");
  // Every tile index must be a real tile at that zoom, or the CDN 404s and the
  // map renders as holes.
  const n = Math.pow(2, l.zoom);
  ok(l.tiles.every((t) => t.x >= 0 && t.x < n && t.y >= 0 && t.y < n),
     "every tile index is inside the world");
  ok(osmTileLayout(NaN, 0, 11, W, H) === null, "NaN latitude is refused");
  ok(osmTileLayout(0, undefined, 11, W, H) === null, "missing longitude is refused");
  // x WRAPS at the antimeridian; y is clamped (there is no tile above the pole).
  const edge = osmTileLayout(0, 179.99, 6, W, H);
  ok(edge.tiles.every((t) => t.x >= 0 && t.x < Math.pow(2, 6)),
     "a box straddling the antimeridian still asks for real tile indices");
  const pole = osmTileLayout(85, 0, 3, W, H);
  ok(pole.tiles.every((t) => t.y >= 0 && t.y < Math.pow(2, 3)),
     "a box at the pole does not ask for a tile above the world");
}

// 3. The fit's core promise: every pin is actually on the map
section("3. osmFitLayout — every pin lands inside the box");
{
  const chicagoland = [
    P(41.88, -87.63), P(42.05, -87.68), P(41.52, -88.08),
    P(41.76, -88.32), P(42.34, -87.95), P(41.30, -87.85),
  ];
  const l = osmFitLayout(chicagoland, W, H);
  ok(l !== null, "a real cluster produces a layout");
  ok(l.pins.length === chicagoland.length, "one pin per point");
  ok(l.pins.every((p) => p.left >= 0 && p.left <= W && p.top >= 0 && p.top <= H),
     "every pin is inside the box");
  // Stronger: inside the PADDED box, so no pin is half-clipped by the edge.
  ok(l.pins.every((p) =>
       p.left >= OSM_FIT_PAD - 1 && p.left <= W - OSM_FIT_PAD + 1 &&
       p.top >= OSM_FIT_PAD - 1 && p.top <= H - OSM_FIT_PAD + 1),
     "every pin clears the padding, so none is clipped by the edge");
}

// 4. The centre is the BOUNDING BOX's, not the mean
section("4. one outlier is not averaged away");
{
  // Twenty events in one town and a single one far north. A mean centre sits
  // almost on top of the cluster and pushes the outlier off the map — and the
  // outlier is usually the whole reason someone opened a map.
  const pts = [];
  for (let i = 0; i < 20; i++) pts.push(P(41.88 + i * 0.001, -87.63 + i * 0.001));
  pts.push(P(45.5, -87.0));
  const l = osmFitLayout(pts, W, H);
  ok(l.pins.every((p) => p.top >= 0 && p.top <= H), "the outlier is still on the map");
  ok(Math.abs(l.center.lat - (41.88 + 45.5) / 2) < 0.6,
     "centre is between the extremes, not on the cluster (got " + l.center.lat.toFixed(2) + ")");
}

// 5. Latitude is centred in PROJECTED space, not degrees
section("5. Mercator is nonlinear in latitude");
{
  // Two points, same longitude, far apart in latitude. Centred correctly they
  // are equidistant from the box's middle. Centred on the degree mean they are
  // not, and the error grows the further from the equator you look.
  const l = osmFitLayout([P(60, 10), P(0, 10)], W, H);
  const [a, b] = l.pins;
  near(Math.abs(a.top - H / 2), Math.abs(b.top - H / 2), 1.5,
       "both pins sit the same distance from the vertical centre");
  // The degree mean would be 30; the projected centre is ~35.3.
  ok(Math.abs(l.center.lat - 30) > 3,
     "centre latitude is not the degree mean (got " + l.center.lat.toFixed(2) + ")");
  near(l.center.lat, 35.28, 0.1, "centre latitude is the projected midpoint");
}

// 6. Longitude is a circle
section("6. the antimeridian");
{
  // Tokyo, Auckland, Honolulu span ~30 degrees of longitude ACROSS the Pacific.
  // Averaging their degrees puts the centre near Arabia and forces a zoom that
  // shows the whole planet in order to "fit" three neighbours.
  const pac = [P(35.68, 139.65), P(-36.85, 174.76), P(21.31, -157.86)];
  const l = osmFitLayout(pac, W, H);
  ok(l.pins.every((p) => p.left >= 0 && p.left <= W && p.top >= 0 && p.top <= H),
     "all three Pacific pins are on the map");
  const lng = ((l.center.lng + 540) % 360) - 180;
  ok(Math.abs(lng) > 150, "centre is in the Pacific, not Arabia (got " + lng.toFixed(1) + ")");
  ok(l.zoom >= 2, "zoom is a Pacific view, not the whole planet (got " + l.zoom + ")");

  // The same shape moved so it does NOT cross the antimeridian must behave the
  // same — otherwise the wrap handling is doing something only it understands.
  const noCross = [P(35.68, 9.65), P(-36.85, 44.76), P(21.31, 22.0)];
  const l2 = osmFitLayout(noCross, W, H);
  ok(l2.pins.every((p) => p.left >= 0 && p.left <= W && p.top >= 0 && p.top <= H),
     "a non-crossing set of the same shape also fits");
  ok(l2.zoom === l.zoom, "and fits at the same zoom (got " + l2.zoom + " vs " + l.zoom + ")");
}

// 7. Degenerate spans
section("7. one point, and several at one address");
{
  const one = osmFitLayout([P(41.88, -87.63)], W, H, { fallbackZoom: 12 });
  ok(one.pins.length === 1, "a single point produces a single pin");
  ok(one.zoom === 12, "a zero-size box falls back rather than dividing by zero");
  near(one.pins[0].left, W / 2, 1, "the lone pin is centred horizontally");
  near(one.pins[0].top, H / 2, 1, "the lone pin is centred vertically");

  // Three events at one shop is the COMMON case here, not an edge case.
  const same = osmFitLayout([P(41.88, -87.63), P(41.88, -87.63), P(41.88, -87.63)], W, H,
                            { fallbackZoom: 13 });
  ok(same.zoom === 13, "identical points fall back too");
  ok(same.pins.every((p) => Math.abs(p.left - W / 2) <= 1 && Math.abs(p.top - H / 2) <= 1),
     "identical points stack at the centre");
}

// 8. Zoom clamps
section("8. zoom stays in range");
{
  // Two events a few metres apart would otherwise compute an absurd zoom, and
  // OSM has no tiles past 19.
  const tight = osmFitLayout([P(41.88, -87.63), P(41.8801, -87.6301)], W, H, { maxZoom: 15 });
  ok(tight.zoom <= 15, "maxZoom is honoured (got " + tight.zoom + ")");
  const world = osmFitLayout([P(-40, -170), P(60, 170)], W, H, { minZoom: 1 });
  ok(world.zoom >= 0 && world.zoom <= 19, "a world-spanning set stays in range (got " + world.zoom + ")");
  ok(world.pins.every((p) => p.left >= 0 && p.left <= W && p.top >= 0 && p.top <= H),
     "a world-spanning set still fits its pins");
}

// 9. Bad input, and the index that maps a pin back to its event
section("9. invalid points, and pin -> event identity");
{
  ok(osmFitLayout([], W, H) === null, "no points is null, not a crash");
  ok(osmFitLayout(null, W, H) === null, "null input is null");
  ok(osmFitLayout([P(NaN, 1), P(2, NaN), {}, null], W, H) === null,
     "all-invalid is null rather than a map of nowhere");

  // The worst silent failure available here: a pin whose index has drifted
  // opens a different event than the one it is drawn on. An event with no
  // coordinates must be skipped WITHOUT renumbering the ones around it.
  const mixed = [P(41.88, -87.63), P(NaN, -87.0), P(42.05, -87.68), null, P(41.52, -88.08)];
  const l = osmFitLayout(mixed, W, H);
  ok(l.pins.length === 3, "the two unplaceable events are dropped");
  ok(l.pins.map((p) => p.i).join(",") === "0,2,4",
     "each pin keeps its ORIGINAL index (got " + l.pins.map((p) => p.i).join(",") + ")");
  ok(l.pins.every((p) => p.lat === mixed[p.i].lat && p.lng === mixed[p.i].lng),
     "each pin's coordinates match the event it points at");
  // Out-of-range coordinates are data errors, not places.
  ok(osmFitLayout([P(41.88, -87.63), P(91, 0), P(0, 181)], W, H).pins.length === 1,
     "impossible coordinates are dropped");

  // Null Island. This is the shape the DATABASE hands us — lorcana_events
  // .latitude is nullable and a curated calendar row is legitimately
  // ungeocoded — and Number(null) is 0, not NaN. Unguarded, every event we
  // cannot place is drawn in the Atlantic off Ghana as an ordinary pin.
  const nulls = osmFitLayout([P(41.88, -87.63), { lat: null, lng: null },
                              { lat: 42.05, lng: null }, { lng: -87.68 }], W, H);
  ok(nulls.pins.length === 1, "null coordinates are dropped, not read as zero");
  ok(nulls.pins[0].i === 0, "and the survivor keeps its index");
  ok(osmFitLayout([{ lat: null, lng: null }], W, H) === null,
     "a set with only null coordinates is null, never a map of Null Island");
  // Empty strings arrive the same way out of a form or a CSV, and coerce to 0 too.
  ok(osmFitLayout([{ lat: "", lng: "" }], W, H) === null, "empty strings are not zero");
  // But a numeric STRING is a real coordinate — PostgREST hands back numerics
  // as strings often enough that rejecting them would empty the map.
  const strs = osmFitLayout([{ lat: "41.88", lng: "-87.63" }, { lat: "42.05", lng: "-87.68" }], W, H);
  ok(strs !== null && strs.pins.length === 2, "numeric strings are real coordinates");
}

// 10. Merging overlapping pins must never lose an event
section("10. scMergePins");
{
  const pin = (i, left, top) => ({ i, left, top });
  // Two shops a few hundred metres apart land on the same pixel at city zoom.
  // The merge is the only reason the second one is reachable at all — so the
  // invariant is total: every input pin is in exactly one output group.
  const pins = [pin(0, 100, 100), pin(1, 103, 102), pin(2, 300, 200),
                pin(3, 100, 100), pin(4, 305, 205), pin(5, 500, 50)];
  const groups = scMergePins(pins);
  const seen = groups.flatMap((g) => g.items.map((p) => p.i)).sort((a, b) => a - b);
  ok(seen.join(",") === "0,1,2,3,4,5", "every pin survives the merge exactly once");
  ok(groups.length < pins.length, "co-located pins actually merged");
  ok(groups.every((g) => g.items.length > 0), "no empty group");
  // A group's position must be one of its own members', not an average that
  // could drift the marker off the shops it stands for.
  ok(groups.every((g) => g.items.some((p) => p.left === g.left && p.top === g.top)),
     "each group sits on one of its own pins");

  // Nothing within the threshold is left separate, and nothing beyond it is
  // swallowed: a merge that is too eager hides events under a pin that is not
  // where they are.
  const far = scMergePins([pin(0, 0, 0), pin(1, SC_PIN_MERGE_PX + 4, 0)]);
  ok(far.length === 2, "pins beyond the threshold stay separate");
  const close = scMergePins([pin(0, 0, 0), pin(1, SC_PIN_MERGE_PX - 1, 0)]);
  ok(close.length === 1, "pins inside the threshold merge");

  ok(scMergePins([]).length === 0, "no pins is no groups");

  // End to end: a real cluster's groups still account for every placed event.
  const l = osmFitLayout([P(41.88, -87.63), P(41.881, -87.631), P(42.34, -87.95)], W, H);
  const g2 = scMergePins(l.pins);
  ok(g2.reduce((n, g) => n + g.items.length, 0) === l.pins.length,
     "grouped pin count equals placed pin count");
}

console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
