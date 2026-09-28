// verify.js — Discord signs every interaction with Ed25519; an endpoint that
// skips the check is one anyone can drive, and Discord itself probes the
// endpoint with a bad signature and refuses to save it unless we answer 401.
const enc = new TextEncoder();
let cachedHex = null, cachedKey = null;

export function hexToBytes(hex) {
  const s = String(hex || "");
  if (!/^[0-9a-f]*$/i.test(s) || s.length % 2) return null;
  const out = new Uint8Array(s.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(s.substr(i * 2, 2), 16);
  return out;
}

async function importKey(hex) {
  if (cachedHex === hex && cachedKey) return cachedKey;
  const raw = hexToBytes(hex);
  if (!raw || raw.length !== 32) throw new Error("DISCORD_PUBLIC_KEY is not a 32-byte hex key");
  let key;
  try {
    key = await crypto.subtle.importKey("raw", raw, { name: "Ed25519" }, false, ["verify"]);
  } catch {
    // Older Workers runtimes only know the pre-standard name.
    key = await crypto.subtle.importKey("raw", raw, { name: "NODE-ED25519", namedCurve: "NODE-ED25519" }, false, ["verify"]);
  }
  cachedHex = hex; cachedKey = key;
  return key;
}

// Returns {ok, body}. A timestamp more than 5 minutes off is refused too, so a
// captured request cannot be replayed later.
export async function verifyDiscordRequest(request, publicKeyHex, nowMs = Date.now()) {
  const sig = request.headers.get("x-signature-ed25519");
  const ts = request.headers.get("x-signature-timestamp");
  const body = await request.text();
  if (!publicKeyHex || !sig || !ts) return { ok: false, body };
  const sigBytes = hexToBytes(sig);
  if (!sigBytes || sigBytes.length !== 64) return { ok: false, body };
  const tsn = Number(ts);
  if (!Number.isFinite(tsn) || Math.abs(nowMs / 1000 - tsn) > 300) return { ok: false, body };
  try {
    const key = await importKey(publicKeyHex);
    const alg = key.algorithm && key.algorithm.name === "NODE-ED25519" ? { name: "NODE-ED25519" } : { name: "Ed25519" };
    const ok = await crypto.subtle.verify(alg, key, sigBytes, enc.encode(ts + body));
    return { ok, body };
  } catch {
    return { ok: false, body };
  }
}
