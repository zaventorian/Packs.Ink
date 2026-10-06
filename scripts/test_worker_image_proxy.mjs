// test_worker_image_proxy.mjs — what the /img-proxy and /tcg-img-proxy routes let through.
//
//     node scripts/test_worker_image_proxy.mjs
//
// Imports the real worker and stubs the upstream fetch. Whatever these routes
// return is served under the packs.ink origin, where the sign-in session lives,
// so anything that can run script must never come back through them (review,
// 2026-10-06): an SVG (it carries script when opened directly), a response
// with no type, or a redirect that left the CDN. The proxy also refused
// protocol-relative paths before this; that is pinned too.
import worker from "../worker/index.js";

let failed = 0;
const check = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failed++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) console.log(`        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`);
};

let upstream = null, asked = [];
globalThis.fetch = async (url) => {
  asked.push(String(url));
  const {type, finalUrl, status = 200} = upstream;
  // Bytes, not a string: a string body makes Response add text/plain by itself.
  const res = new Response(new Uint8Array([1, 2, 3]), {status, headers: type == null ? {} : {"Content-Type": type}});
  Object.defineProperty(res, "url", {value: finalUrl || String(url)});
  return res;
};
const get = async (path, up) => {
  upstream = up; asked = [];
  const res = await worker.fetch(new Request("https://packs.ink" + path), {});
  return res;
};

const LORCAST = "/img-proxy/card/digital/normal/crd_x.avif?1";
const TCG = "/tcg-img-proxy/product/123_in_1000x1000.jpg";

for (const t of ["image/avif", "image/jpeg", "image/png", "image/webp", "application/octet-stream"]) {
  check(`${t} passes`, (await get(LORCAST, {type: t})).status, 200);
}
check("a JPEG with a charset passes", (await get(TCG, {type: "image/jpeg; charset=binary"})).status, 200);
check("SVG is refused (it runs script on packs.ink when opened)", (await get(LORCAST, {type: "image/svg+xml"})).status, 502);
check("HTML is refused", (await get(LORCAST, {type: "text/html"})).status, 502);
check("a response with NO type is refused (it used to pass)", (await get(LORCAST, {type: null})).status, 502);
check("image/jpegfoo is not image/jpeg", (await get(LORCAST, {type: "image/jpegfoo"})).status, 502);
check("a redirect that left the CDN is refused",
  (await get(LORCAST, {type: "image/png", finalUrl: "https://evil.example/x.png"})).status, 502);
check("a redirect that stayed on the CDN is fine",
  (await get(LORCAST, {type: "image/png", finalUrl: "https://cards.lorcast.io/other.png"})).status, 200);

const ok = await get(LORCAST, {type: "image/avif"});
check("served with a sandboxing CSP", ok.headers.get("Content-Security-Policy"), "default-src 'none'; sandbox");
check("...nosniff", ok.headers.get("X-Content-Type-Options"), "nosniff");
check("...and ACAO * (canvas exports, native builds)", ok.headers.get("Access-Control-Allow-Origin"), "*");
check("the upstream asked is the intended CDN", asked[0].startsWith("https://cards.lorcast.io/card/digital/normal/crd_x.avif"), true);

const pr = await get("/img-proxy//evil.example/x.png", {type: "image/png"});
check("a protocol-relative path never leaves the CDN", pr.status === 400 || asked.every(u => u.startsWith("https://cards.lorcast.io/")), true);
check("an upstream error is passed on, not cached as art", (await get(LORCAST, {type: "image/avif", status: 404})).status, 404);

console.log(failed ? `\n${failed} FAILED` : "\nall passed");
process.exit(failed ? 1 : 0);
