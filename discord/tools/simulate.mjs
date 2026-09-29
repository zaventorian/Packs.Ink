// simulate.mjs — drive the real Worker (in `wrangler dev`) with signed fake
// interactions, and catch the follow-up messages it would send to Discord.
//
//   node tools/simulate.mjs                       # runs the whole script below
//   node tools/simulate.mjs "/price mowgli"        # one command
//
// It generates a throwaway Ed25519 key pair, starts `wrangler dev` with that
// public key and DISCORD_API_BASE pointed at a local capture server, then
// signs each request exactly the way Discord does. Nothing reaches Discord.
import { spawn, spawnSync } from "node:child_process";
import http from "node:http";
import { webcrypto as crypto } from "node:crypto";
import { writeFileSync, mkdirSync } from "node:fs";

// A fresh port each run: a worker left over from an earlier run, still holding
// an old test key, would otherwise answer on the same port and refuse every
// signature.
const PORT = Number(process.env.SIM_PORT || 8800 + Math.floor(Math.random() * 800) * 2);
const CAPTURE_PORT = PORT + 1;
const OUT = new URL("../.wrangler/sim/", import.meta.url);
mkdirSync(OUT, { recursive: true });

const kp = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
const pubHex = Buffer.from(await crypto.subtle.exportKey("raw", kp.publicKey)).toString("hex");

// ── capture server: stands in for discord.com/api ────────────────────────
const captured = [];
const waiters = [];
// A reply that uploads a picture (the tile, baked art) arrives as multipart:
// the JSON is the payload_json part, and each file is noted by name and size.
const cap = http.createServer((req, res) => {
  const chunks = [];
  req.on("data", (c) => chunks.push(c));
  req.on("end", async () => {
    const buf = Buffer.concat(chunks);
    const ctype = req.headers["content-type"] || "";
    let parsed = null, files = [];
    try {
      if (/^multipart\/form-data/i.test(ctype)) {
        const form = await new Response(buf, { headers: { "content-type": ctype } }).formData();
        parsed = JSON.parse(form.get("payload_json"));
        for (const [k, v] of form.entries()) if (k.startsWith("files[")) files.push({ field: k, name: v.name, type: v.type, size: v.size });
      } else parsed = JSON.parse(buf.toString("utf8"));
    } catch {}
    captured.push({ method: req.method, url: req.url, body: parsed, files });
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end("{}");
    while (waiters.length) waiters.shift()();
  });
});
await new Promise((r) => cap.listen(CAPTURE_PORT, r));

// ── the Worker ───────────────────────────────────────────────────────────
const wrArgs = ["wrangler", "dev", "--port", String(PORT),
  "--var", `DISCORD_PUBLIC_KEY:${pubHex}`,
  "--var", "DISCORD_APPLICATION_ID:1234567890",
  "--var", `DISCORD_API_BASE:http://127.0.0.1:${CAPTURE_PORT}`];
const WIN = process.platform === "win32";
const wr = WIN
  ? spawn("npx.cmd " + wrArgs.join(" "), { cwd: new URL("..", import.meta.url), shell: true })
  : spawn("npx", wrArgs, { cwd: new URL("..", import.meta.url), detached: true });
// Kill the whole tree: on Windows wr is a shell, and killing it leaves
// wrangler — and its workerd — running. SYNCHRONOUS, because it also runs from
// the exit handler, where an async spawn never gets to start.
let stopped = false;
const stopWorker = () => {
  if (stopped) return;
  stopped = true;
  try {
    if (WIN) spawnSync("taskkill", ["/pid", String(wr.pid), "/T", "/F"], { stdio: "ignore" });
    else process.kill(-wr.pid, "SIGTERM");
  } catch {}
};
process.on("exit", stopWorker);
process.on("uncaughtException", (e) => { console.error(e); stopWorker(); process.exit(1); });
process.on("unhandledRejection", (e) => { console.error(e); stopWorker(); process.exit(1); });
let log = "";
wr.stdout.on("data", (d) => (log += d));
wr.stderr.on("data", (d) => (log += d));
const base = `http://127.0.0.1:${PORT}`;
for (let i = 0; i < 120; i++) {
  try { const r = await fetch(base + "/"); if (r.ok) break; } catch {}
  await new Promise((r) => setTimeout(r, 500));
  if (i === 119) { console.error(log); process.exit(1); }
}
console.log("worker up:", await (await fetch(base + "/")).text());

async function send(interaction) {
  const body = JSON.stringify(interaction);
  const ts = String(Math.floor(Date.now() / 1000));
  const sig = Buffer.from(await crypto.subtle.sign("Ed25519", kp.privateKey, new TextEncoder().encode(ts + body))).toString("hex");
  const r = await fetch(base + "/interactions", {
    method: "POST", body,
    headers: { "Content-Type": "application/json", "X-Signature-Ed25519": sig, "X-Signature-Timestamp": ts },
  });
  return { status: r.status, json: await r.json().catch(() => null) };
}
const waitFollowUp = (n) => new Promise((resolve) => {
  const check = () => (captured.length >= n ? resolve(captured[n - 1]) : waiters.push(check));
  check();
  setTimeout(() => resolve(null), 20000);
});

let seq = 0;
const base_ = () => ({ id: "sim" + (++seq), application_id: "1234567890", token: "tok" + seq, version: 1,
  guild_id: "1", channel_id: "2", member: { user: { id: "9", username: "sim" }, permissions: "0" } });
const cmd = (name, options = []) => ({ ...base_(), type: 2, data: { id: "c", name, type: 1, options } });

function parseLine(line) {
  // Git Bash rewrites a leading "/help" into "C:/Program Files/Git/help"; undo it.
  line = line.trim().replace(/^[A-Za-z]:[\\/].*?[\\/]Git[\\/](?=\w)/, "/");
  const m = /^\/(\w+)\s*(.*)$/.exec(line);
  if (!m) throw new Error("say it like: /price mowgli");
  const [, name, rest] = m;
  if (name === "price" || name === "card") return cmd(name, [{ type: 3, name: "name", value: rest }]);
  if (name === "events") return cmd(name, [{ type: 3, name: "near", value: rest || "60614" }]);
  if (name === "movers") {
    const [window = "1d", direction = "up", rarity = "all"] = rest.split(/\s+/).filter(Boolean);
    return cmd(name, [{ type: 3, name: "window", value: window }, { type: 3, name: "direction", value: direction }, { type: 3, name: "rarity", value: rarity }]);
  }
  // /trade 2x mowgli, $20 vs enchanted elsa   ("vs": Git Bash rewrites "//")
  if (name === "trade") {
    const [give = "", get = ""] = rest.split(/\s+vs\s+/i).map((s) => s.trim());
    return cmd(name, [give && { type: 3, name: "give", value: give }, get && { type: 3, name: "get", value: get }].filter(Boolean));
  }
  if (name === "set" || name === "open") return cmd(name, rest ? [{ type: 3, name: "set", value: rest }] : []);
  return cmd(name, []);
}

const script = process.argv.slice(2).length ? process.argv.slice(2) : [
  "/price mowgli", "/card enchanted elsa", "/price elsa psa 10", "/price azurite sea box",
  "/price asdfgh", "/movers 1w up chase", "/movers 1d down all", "/movers 1m up sealed", "/events 60614", "/calendar", "/help",
  "/trade 2x mowgli, enchanted elsa, $20 vs stitch rock star foil, azurite sea box", "/set azurite", "/set", "/open fabled", "/new",
];

const bad = await (async () => {
  const r = await fetch(base + "/interactions", { method: "POST", body: "{}", headers: { "X-Signature-Ed25519": "00".repeat(64), "X-Signature-Timestamp": String(Math.floor(Date.now() / 1000)) } });
  return r.status;
})();
console.log("bad signature ->", bad, bad === 401 ? "(correct)" : "(WRONG)");
console.log("ping ->", JSON.stringify((await send({ ...base_(), type: 1 })).json));
const ac = await send({ ...base_(), type: 4, data: { name: "price", type: 1, options: [{ type: 3, name: "name", value: "mogli", focused: true }] } });
console.log("autocomplete 'mogli' ->", ac.json && ac.json.data ? (ac.json.data.choices || []).slice(0, 3).map((c) => c.name) : "HTTP " + ac.status);

for (const line of script) {
  const before = captured.length;
  const r = await send(parseLine(line));
  // An immediate reply (type 4) carries its message in .data, like a follow-up's body.
  let out = r.json && r.json.type === 4 ? r.json.data : r.json;
  let uploaded = [];
  if (r.json && (r.json.type === 5 || r.json.type === 6)) {
    const fu = await waitFollowUp(before + 1);
    out = fu ? fu.body : { error: "no follow-up within 20s" };
    uploaded = (fu && fu.files) || [];
  }
  const file = new URL(`${String(seq).padStart(2, "0")}-${line.replace(/[^a-z0-9]+/gi, "_").slice(0, 40)}.json`, OUT);
  writeFileSync(file, JSON.stringify(out, null, 2));
  const e = out && out.embeds && out.embeds[0];
  console.log(`\n${line}  [initial type ${r.json && r.json.type}]`);
  if (out && out.content) console.log("  content:", out.content);
  if (e) {
    console.log("  title:", e.title);
    console.log("  " + String(e.description || "").split("\n").join("\n  "));
    for (const f of e.fields || []) console.log(`  [${f.name}] ${f.value.replace(/\n/g, " | ")}`);
    if (e.image) console.log("  image:", e.image.url);
    if (e.thumbnail) console.log("  thumb:", e.thumbnail.url);
    for (const f of uploaded) console.log(`  uploaded: ${f.field} ${f.name} (${f.type}, ${f.size} bytes)`);
  }
  if (out && out.components) console.log("  components:", out.components.map((row) => row.components.map((c) => c.label || c.placeholder).join(" / ")).join("  ||  "));
}

// ── components, the message menu, and a chart fetched from the Worker ────
if (!process.argv.slice(2).length) {
  const first = captured.find((c) => c.body && c.body.embeds && /Mowgli/.test(c.body.embeds[0]?.title || ""));
  const btn = first && first.body.components[0].components.find((c) => c.label === "1Y");
  const sel = first && first.body.components.find((r) => r.components[0].type === 3);
  const click = async (data, what) => {
    const before = captured.length;
    const r = await send({ ...base_(), type: 3, message: { id: "m0" }, data });
    const fu = await waitFollowUp(before + 1);
    const e = fu && fu.body.embeds && fu.body.embeds[0];
    console.log(`\n${what}  [initial type ${r.json && r.json.type}]`);
    if (e) console.log("  title:", e.title, "\n  image:", e.image && e.image.url);
  };
  if (btn) await click({ custom_id: btn.custom_id, component_type: 2 }, "click 1Y on /price mowgli");
  if (sel) {
    const other = sel.components[0].options.find((o) => !o.default);
    if (other) await click({ custom_id: sel.components[0].custom_id, component_type: 3, values: [other.value] }, `pick "${other.label}" from the versions menu`);
  }
  const before = captured.length;
  const pc = await send({ ...base_(), type: 2, data: { id: "c", type: 3, name: "Price check", target_id: "m1",
    resolved: { messages: { m1: { id: "m1", content: "anyone got an enchanted elsa or a mowgli for trade? also lf stich" } } } } });
  const fu = await waitFollowUp(before + 1);
  console.log(`\nPrice check on a chat message  [initial type ${pc.json && pc.json.type}]`);
  for (const e of (fu && fu.body.embeds) || []) console.log("  -", e.title, "|", String(e.description).split("\n").join(" | "));

  // /deck: the text box, then what submitting it returns
  const dm = await send(cmd("deck", []));
  console.log(`\n/deck  [initial type ${dm.json && dm.json.type}] -> "${dm.json && dm.json.data && dm.json.data.title}"`);
  const deckList = `4 Mowgli - Man Cub
4x mogli
4 Elsa - Spirit of Winter
2 Be Prepard
3 Tinker Bel - Giant Fairy
2 Totally Not A Card`;
  const ds = await send({ ...base_(), type: 5, data: { custom_id: dm.json.data.custom_id,
    components: [{ type: 1, components: [{ type: 4, custom_id: "list", value: deckList }] }] } });
  const de = ds.json && ds.json.data && ds.json.data.embeds && ds.json.data.embeds[0];
  console.log(`submit the box  [initial type ${ds.json && ds.json.type}]`);
  if (de) console.log("  " + de.title + "\n  " + String(de.description).split("\n").join("\n  ") + "\n  " + de.footer.text);
  writeFileSync(new URL("deck.json", OUT), JSON.stringify(ds.json, null, 2));

  const img = first && first.body.embeds[0].image && first.body.embeds[0].image.url;
  if (img) {
    const t = Date.now();
    const r = await fetch(img);
    const buf = Buffer.from(await r.arrayBuffer());
    writeFileSync(new URL("chart.png", OUT), buf);
    console.log(`\nchart from the Worker: HTTP ${r.status} ${r.headers.get("content-type")} ${buf.length} bytes in ${Date.now() - t} ms -> .wrangler/sim/chart.png`);
  }
}

cap.close();
stopWorker();
setTimeout(() => process.exit(0), 1500);
