// test_discord_bot.mjs — guard for the Discord bot (discord/).
//
//   node scripts/test_discord_bot.mjs
//
// Offline and dependency-free, like every guard: it runs the bot's real
// modules against discord/test/fixture-index.json (a slice of the real card
// index) with a fake database and a fake Discord. What it pins, and why each
// failure would otherwise be silent:
//
//   1. The site code copied into discord/src/site.generated.js still matches
//      Index.html statement for statement — a stale copy would quietly price
//      or label a card differently from the site.
//   2. The resolver's plain-English contract: no subtitle -> the version that
//      is played; misspellings; rarity/finish/grade words; sealed; nothing
//      matching says so instead of guessing.
//   3. Every id Discord hands back fits Discord's 100-char limits and round-
//      trips to the same card.
//   4. The PNG encoder's output decodes to the exact pixels it was given.
//   5. Replies stay inside Discord's embed and component limits — a reply
//      that breaks one is REJECTED by Discord, and the user just sees
//      "thinking…" forever.
//   6. Signature verification refuses what it must refuse.
//   7. The stale-mover guard drops a row whose "today" is not today.
//   8. Every picture is one Discord shows (no AVIF, no data: URI, no relative
//      path — the last two get the whole reply rejected), and every TCGplayer
//      link is the affiliate link, with the disclosure beside it.
//   9. A picture the Worker makes itself (the tile, baked art, a chart) is
//      UPLOADED with the reply — Discord dropped it from the first edit of
//      a deferred reply when it was only linked — and a refused upload falls
//      back to the link.
import { readFileSync } from "node:fs";
import { inflateSync } from "node:zlib";
import { webcrypto } from "node:crypto";

const ROOT = new URL("../", import.meta.url);
const mod = (p) => import(new URL(p, ROOT).href);
let fails = 0, passes = 0;
const ok = (cond, msg) => { if (cond) passes++; else { fails++; console.log("FAIL " + msg); } };
const eq = (a, b, msg) => ok(a === b, `${msg} — expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`);

// ── 1. copied site code is still the site's code ─────────────────────────
{
  // Line endings are folded first: a Windows checkout has CRLF in both files,
  // CI has LF in both, and neither is a difference in the code.
  const lf = (s) => s.replace(/\r\n/g, "\n");
  const html = lf(readFileSync(new URL("Index.html", ROOT), "utf8"));
  const gen = lf(readFileSync(new URL("discord/src/site.generated.js", ROOT), "utf8"));
  const chunks = gen.split("// ---- site ----\n").slice(1).map((c) => c.replace(/\n+export \{[\s\S]*$/, "").trimEnd());
  ok(chunks.length >= 40, `site.generated.js holds the copied statements (${chunks.length})`);
  const stale = chunks.filter((c) => !html.includes(c));
  ok(!stale.length, `site.generated.js matches Index.html — ${stale.length} stale statement(s), first: ` +
    JSON.stringify((stale[0] || "").slice(0, 120)) + "\n     re-run: node discord/tools/extract_site.mjs");
}

const { createResolver } = await mod("discord/src/resolver.js");
const index = JSON.parse(readFileSync(new URL("discord/test/fixture-index.json", ROOT), "utf8"));
// A fixture built before the play line went per-set (2026-10-04) carries no
// current-set counts: give it some, from its own recency-weighted ones.
if (!index.playSet) {
  index.playSet = { n: "Attack of the Vine!", since: "2026-07-17", decks: 200 };
  for (const c of index.cards) if (c.pl > 0) c.ps = Math.max(1, Math.round(c.pl * 4));
}
const R = createResolver(index);

// ── 2. the resolver ──────────────────────────────────────────────────────
const card = (q) => { const r = R.resolve(q); return r.kind === "card" ? r : null; };
const nameOf = (q) => { const r = R.resolve(q); return r.kind === "card" ? r.card.n : r.kind === "sealed" ? "[sealed] " + r.item.n : null; };
{
  const mowgli = index.cards.find((c) => c.c === "Mowgli");
  ok(!!mowgli, "fixture carries a Mowgli");
  if (mowgli) {
    // "mowgli" with no subtitle: the most-played Mowgli, every spelling.
    const played = index.cards.filter((c) => c.c === "Mowgli").sort((a, b) => (b.pl || 0) - (a.pl || 0))[0].n;
    for (const q of ["mowgli", "Mowgli", "mogli", "mowgi", "moglie", "how much is mowgli", "what's mowgli worth"]) {
      eq(nameOf(q), played, `"${q}"`);
    }
  }
  const ench = card("enchanted elsa");
  ok(ench && ench.printing.r === "Enchanted", `"enchanted elsa" is an Enchanted (${ench && ench.printing.r})`);
  const ench2 = card("elsa enchanted");
  ok(ench2 && ench2.printing.r === "Enchanted", `"elsa enchanted" is an Enchanted`);
  ok(card("elsa psa 10") && card("elsa psa 10").dims.grade && card("elsa psa 10").dims.grade.grader === "PSA",
    `"elsa psa 10" carries the grade`);
  const foil = card("elsa spirit of winter foil");
  ok(foil && foil.printing.f[foil.fi][0] !== "N", `"… foil" lands on a foil finish`);
  eq(nameOf("te ka"), "Te Kā - Heartless", `"te ka" folds the macron`);
  eq(nameOf("peter pan text error"), "Peter Pan - Pirate's Bane", `"peter pan text error"`);
  const te = card("peter pan text error");
  ok(te && /variant/.test(te.printing.id), `"peter pan text error" picks the Text Error printing (${te && te.printing.id})`);
  ok(/^\[sealed\] Azurite Sea Booster Box$/.test(nameOf("azurite sea box") || ""), `"azurite sea box" is the sealed box (${nameOf("azurite sea box")})`);
  ok(/^\[sealed\]/.test(nameOf("stitch gift set") || ""), `"stitch gift set" is sealed`);
  eq(R.resolve("asdfgh").kind, "none", `gibberish is "none", not a guess`);
  eq(R.resolve("the").kind, "none", `a lone stop word is "none"`);
  eq(R.resolve("enchanted").kind, "none", `a lone rarity word is "none"`);
  ok(R.resolve("enchanted").dimsOnly, `…and says it only narrowed things down`);

  // findInText: a sentence mentioning two cards finds both, and no English.
  const found = R.findInText("anyone know what mowgli goes for? trading my enchanted elsa", 3);
  ok(found.length >= 2, `findInText finds both cards in a sentence (${found.map((f) => f.card && f.card.n)})`);
  // Ordinary chat must not turn into a card: short words a letter away from a
  // card word ("good"/Food, "deck"/Duck), a rarity word, a card name's lone
  // middle word. Each of these produced a card before it was pinned here.
  for (const t of ["see you at the shop on friday", "whats a good deck for the championship this weekend guys",
    "gg that was a great game", "lol that deck is broken", "pulled 2 enchanteds today!", "need help building an amber steel deck"]) {
    eq(R.findInText(t, 3).length, 0, `findInText finds nothing in "${t}"`);
  }
  ok((R.findInText("moglie?", 3)[0] || {}).card && R.findInText("moglie?", 3)[0].card.c === "Mowgli", `a short typo'd message still finds its card ("moglie?")`);
}

// ── 3. keys and custom ids ───────────────────────────────────────────────
const E = await mod("discord/src/embeds.js");
{
  let checked = 0, bad = 0;
  for (const c of index.cards) for (const p of c.p) p.f.forEach((f, fi) => {
    const key = R.cardKey(p, fi);
    const back = R.resolve(key);
    if (!(back.kind === "card" && back.printing.id === p.id && back.printing.f[back.fi][0] === f[0])) bad++;
    const id = E.rangeId("all", "graded", key, { grader: "BGS", grade: "9.5" });
    if (id.length > 100 || !E.parseRangeId(id) || E.parseRangeId(id).key !== key) bad++;
    checked++;
  });
  ok(checked > 200 && bad === 0, `${checked} card keys round-trip and fit 100 chars (${bad} bad)`);
  for (const it of index.sealed) {
    const back = R.resolve(R.sealedKey(it));
    ok(back.kind === "sealed" && back.item.pid === it.pid, `sealed key round-trips: ${it.n}`);
  }
  const s = R.suggest("mog", 25);
  ok(s.length > 0 && s.length <= 25, "autocomplete returns 1..25 choices");
  ok(s.every((x) => x.label.length <= 100 && x.value.length <= 100), "autocomplete labels and values fit 100 chars");
  ok(R.suggest("", 25).length > 0, "autocomplete with nothing typed offers the most-played cards");
}

// ── 4. PNG ───────────────────────────────────────────────────────────────
const { encodePNG, crc32 } = await mod("discord/src/png.js");
{
  const w = 37, h = 11, rgb = new Uint8Array(w * h * 3);
  for (let i = 0; i < rgb.length; i++) rgb[i] = (i * 7 + (i >> 5) * 13) & 0xff;
  rgb.fill(40, 0, w * 3 * 4);     // flat rows, to exercise the long matches
  const png = encodePNG(rgb, w, h);
  eq([...png.slice(0, 8)].join(","), "137,80,78,71,13,10,26,10", "PNG signature");
  const dv = new DataView(png.buffer, png.byteOffset);
  let o = 8, idat = [], crcOk = true, ihdr = null;
  while (o < png.length) {
    const len = dv.getUint32(o), type = String.fromCharCode(...png.slice(o + 4, o + 8));
    if (crc32(png, o + 4, o + 8 + len) !== dv.getUint32(o + 8 + len)) crcOk = false;
    if (type === "IHDR") ihdr = { w: dv.getUint32(o + 8), h: dv.getUint32(o + 12), depth: png[o + 16], color: png[o + 17] };
    if (type === "IDAT") idat.push(png.slice(o + 8, o + 8 + len));
    o += 12 + len;
  }
  ok(crcOk, "every PNG chunk CRC checks");
  ok(ihdr && ihdr.w === w && ihdr.h === h && ihdr.depth === 8 && ihdr.color === 2, "IHDR says 8-bit RGB at the right size");
  const raw = inflateSync(Buffer.concat(idat));
  let same = raw.length === (w * 3 + 1) * h;
  for (let y = 0; same && y < h; y++) {
    if (raw[y * (w * 3 + 1)] !== 0) same = false;
    for (let x = 0; same && x < w * 3; x++) if (raw[y * (w * 3 + 1) + 1 + x] !== rgb[y * w * 3 + x]) same = false;
  }
  ok(same, "the PNG inflates (with zlib) to exactly the pixels it was given");
}

// ── chart ────────────────────────────────────────────────────────────────
const { renderChart, fmtAxisMoney, THEME } = await mod("discord/src/chart.js");
{
  const t0 = Date.UTC(2026, 0, 1), DAY = 86400000;
  const pts = Array.from({ length: 120 }, (_, i) => [t0 + i * DAY, 10 + Math.sin(i / 9) * 2]);
  const png = renderChart({ lines: [{ pts, color: THEME.gold, fill: true, endDot: true }], legend: [{ label: "NM Market", color: THEME.gold, value: "$10.00" }], corner: "3M" });
  ok(png.length > 2000 && png[1] === 80, "renderChart returns a PNG");
  const empty = renderChart({ lines: [], legend: [] });
  ok(empty.length > 500, "an empty chart still renders");
  const cases = [[7000, 1000, "$7k"], [12500, 2500, "$12.5k"], [10000, 5000, "$10k"], [1250, 250, "$1.25k"], [950, 50, "$950"], [2.5, 0.5, "$2.50"], [0.25, 0.05, "$0.25"]];
  for (const [v, s, want] of cases) eq(fmtAxisMoney(v, s), want, `axis label ${v}/${s}`);
}

// ── 5. replies stay inside Discord's limits ──────────────────────────────
const DISCORD_IMG = /^https:\/\/[^?#]+\.(?:jpe?g|png|webp|gif)(?:[?#].*)?$/i;
const TCG_AFFILIATE = "https://partner.tcgplayer.com/c/7285926/1780961/21018?u=";
function checkMessage(m, label) {
  const embeds = m.embeds || [];
  ok(embeds.length <= 10, `${label}: ≤10 embeds`);
  let total = 0;
  for (const e of embeds) {
    ok(!e.title || e.title.length <= 256, `${label}: title ≤256`);
    ok(!e.description || e.description.length <= 4096, `${label}: description ≤4096`);
    ok((e.fields || []).length <= 25, `${label}: ≤25 fields`);
    for (const f of e.fields || []) {
      ok(f.name.length <= 256 && f.value.length <= 1024 && f.value.length > 0, `${label}: field ${f.name} within limits`);
      total += f.name.length + f.value.length;
    }
    total += (e.title || "").length + (e.description || "").length + ((e.footer && e.footer.text) || "").length;
    // An uploaded picture is "attachment://<name>", and the name must be one
    // the message declares, or Discord shows nothing (section 9).
    const declared = new Set((m.attachments || []).map((a) => a.filename));
    const isAtt = (u) => /^attachment:\/\//.test(String(u));
    for (const u of [e.url, e.image && e.image.url, e.thumbnail && e.thumbnail.url]) if (u && !isAtt(u)) ok(/^https?:\/\//.test(u), `${label}: absolute URL ${u}`);
    // Discord shows no AVIF, and a data: URI or a relative path gets the whole
    // reply rejected — so a picture is an https JPEG / PNG / WebP / GIF or nothing.
    for (const u of [e.image && e.image.url, e.thumbnail && e.thumbnail.url]) {
      if (u && isAtt(u)) ok(/^attachment:\/\/[A-Za-z0-9_.-]+\.(?:png|webp|jpe?g|gif)$/.test(u) && declared.has(u.slice(13)), `${label}: uploaded picture ${u} is declared in attachments`);
      else if (u) ok(DISCORD_IMG.test(u), `${label}: picture is in a format Discord shows (${String(u).slice(0, 90)})`);
    }
  }
  ok(total <= 6000, `${label}: embeds total ≤6000 chars (${total})`);
  // A text clipped mid-way leaves a markdown link or a <t:…> timestamp open,
  // and Discord shows the raw syntax. Every link must close; every tag too.
  for (const e of embeds) {
    for (const t of [e.description, ...(e.fields || []).map((f) => f.value)].filter(Boolean)) {
      const s = String(t);
      let at = s.indexOf("](");
      let broken = null;
      while (at >= 0 && !broken) {
        if (!/^\]\(https?:\/\/[^\s)]+\)/.test(s.slice(at))) broken = s.slice(at, at + 60);
        at = s.indexOf("](", at + 2);
      }
      ok(!broken, `${label}: no markdown link is cut off (${broken})`);
      ok(!/<t:\d*(?::[a-zA-Z])?(?:[^>\d:a-zA-Z]|$)/.test(s), `${label}: no <t:…> timestamp is cut off`);
    }
  }
  // Every TCGplayer link earns through the affiliate program, and a message
  // carrying one says so (the FTC wants the disclosure near the links).
  const links = [];
  for (const e of embeds) {
    if (e.url) links.push(e.url);
    for (const t of [e.description, ...(e.fields || []).map((f) => f.value)]) {
      for (const mm of String(t || "").matchAll(/\]\((https?:\/\/[^)\s]+)\)/g)) links.push(mm[1]);
    }
  }
  for (const row of m.components || []) for (const c of row.components) if (c.type === 2 && c.url) links.push(c.url);
  const tcg = links.filter((u) => /tcgplayer\.com/.test(u) && !/^https:\/\/tcgplayer-cdn\./.test(u));
  for (const u of tcg) ok(u.startsWith(TCG_AFFILIATE), `${label}: TCGplayer link goes through the affiliate program (${u.slice(0, 80)})`);
  if (tcg.length) {
    ok(embeds.some((e) => e.footer && String(e.footer.text).includes(E.AFFILIATE_NOTE)), `${label}: carries the affiliate disclosure`);
  }
  const rows = m.components || [];
  ok(rows.length <= 5, `${label}: ≤5 component rows`);
  // Discord refuses a message in which two components share a custom_id —
  // and a refused reply is "thinking…" forever. The movers and events boards
  // highlight the CURRENT state on three controls at once, which is exactly
  // how two ids come out the same.
  const ids = rows.flatMap((row) => row.components).map((c) => c.custom_id).filter(Boolean);
  ok(new Set(ids).size === ids.length, `${label}: component custom_ids are unique (${ids.filter((x, i) => ids.indexOf(x) !== i).join(", ")})`);
  for (const row of rows) {
    ok(row.type === 1 && row.components.length >= 1 && row.components.length <= 5, `${label}: row holds 1..5 components`);
    const selects = row.components.filter((c) => c.type === 3);
    ok(!selects.length || row.components.length === 1, `${label}: a select menu sits alone in its row`);
    for (const c of row.components) {
      if (c.type === 2) {
        ok(!c.label || c.label.length <= 80, `${label}: button label ≤80`);
        ok(!c.url || c.url.length <= 512, `${label}: link button URL ≤512 characters (${c.url && c.url.length})`);
        ok(c.style === 5 ? /^https:\/\//.test(c.url) && !c.custom_id : c.custom_id && c.custom_id.length <= 100, `${label}: button ${c.label} is a link or has a custom_id ≤100`);
      }
      if (c.type === 3) {
        ok(c.custom_id.length <= 100 && c.options.length >= 1 && c.options.length <= 25, `${label}: select has 1..25 options`);
        ok(c.options.every((o) => o.label.length <= 100 && o.value.length <= 100 && (!o.description || o.description.length <= 100)), `${label}: select options fit 100 chars`);
        ok(c.options.filter((o) => o.default).length <= 1, `${label}: at most one default option`);
        ok(new Set(c.options.map((o) => o.value)).size === c.options.length, `${label}: select option values are unique`);
      }
    }
  }
}
const D = await mod("discord/src/data.js");
{
  const DAY = 86400000;
  const hist = Array.from({ length: 400 }, (_, i) => ({ date: new Date(Date.UTC(2025, 7, 1) + i * DAY).toISOString().slice(0, 10), low_price: 4 + i / 200, market_price: 5 + i / 150 }));
  const price = D.priceSummary(hist);
  ok(price.market != null && price.mktDelta["1w"] != null, "priceSummary gives a price and a 1W change");
  // Migration 172's rule, as the site's card page applies it: a printing whose
  // last price is 100 days older than the index's price date keeps showing that
  // price, but reports no move for a window that doesn't contain it, and gets no
  // "Cheapest in 12 months" for a price nobody can buy today.
  {
    const asOf = hist[hist.length - 1].date;
    const stale = D.priceSummary(hist.slice(0, 300), asOf);
    ok(stale.market != null, "a stale printing still shows its last price");
    ok(["1d", "1w", "1m", "3m"].every((k) => stale.mktDelta[k] == null && stale.lowDelta[k] == null),
      `a stale printing reports no 1D/1W/1M/3M move (${JSON.stringify(stale.mktDelta)})`);
    eq(stale.standing, null, "a stale printing gets no price-standing note");
    const fresh = D.priceSummary(hist, asOf);
    ok(fresh.mktDelta["1d"] != null && fresh.mktDelta["1w"] != null, "a printing priced today keeps its changes");
  }
  for (const q of ["mowgli", "enchanted elsa", "elsa psa 10", "peter pan text error", "stitch"]) {
    const res = R.resolve(q);
    if (res.kind !== "card") { ok(false, `"${q}" should be a card`); continue; }
    for (const view of ["chart", "card", "graded"]) {
      const m = E.cardMessage({ R, res, price, graded: [{ grader: "PSA", grade: "10", last_sold_price: 100, avg_last_5: 90, sale_count: 12, printing: "" }],
        raw: null, view, range: "3m", origin: "https://bot.example", query: q, grade: view === "graded" ? { grader: "PSA", grade: "10" } : null,
        gradedTarget: { cardId: res.printing.id, bucket: "" }, inkColors: index.inkColors });
      checkMessage(m, `card "${q}" ${view}`);
    }
  }
  // A raw-watchlist promo: eBay leads, TCGplayer follows plain, no change line
  // or standing (they judge TCGplayer's price), and the chart overlays sales.
  {
    const res = R.resolve("mowgli");
    const raw = { last_sold_price: 1950, last_sold_date: "2026-09-26", avg_last_5: 1204, last_5_count: 5, sale_count: 109, printing: "" };
    const m = E.cardMessage({ R, res, price: { ...price, standing: { tone: "low", label: "Cheapest in 12 months" } }, graded: [], raw,
      rawTarget: { cardId: "crd_x", bucket: "" }, view: "chart", range: "all", origin: "https://bot.example", inkColors: index.inkColors,
      gradedTarget: { cardId: "crd_x", bucket: "" } });
    const d = m.embeds[0].description;
    ok(/\*\*\$1,950\*\* last sold on eBay/.test(d) && d.indexOf("eBay") < d.indexOf("TCGplayer"), "raw card: eBay's last sale leads");
    ok(!/Cheapest in 12 months/.test(d) && !/1W /.test(d), "raw card: no TCGplayer change line or standing");
    ok(/[?&]r=crd_x&rb=&/.test(m.embeds[0].image.url), `raw card: chart overlays the eBay sales (${m.embeds[0].image.url})`);
    checkMessage(m, "raw card");
  }
  const sealed = R.resolve("azurite sea box");
  checkMessage(E.sealedMessage({ R, res: sealed, price, view: "chart", range: "1y", origin: "https://bot.example" }), "sealed");
  checkMessage(E.notFoundMessage(R, R.resolve("mogl elza"), "mogl elza"), "not found");
  checkMessage(E.helpMessage(), "help");
  checkMessage(E.helpMessage({ card: "1234567890123", price: "2234567890123", reports: "3234567890123" }), "help with command ids");
  {
    const h = JSON.stringify(E.helpMessage({ card: "1234567890123", reports: "3234567890123" }));
    ok(h.includes("</card:1234567890123>") && h.includes("</reports daily:3234567890123>"), "help: a registered command is a clickable mention (a subcommand too)");
    ok(h.includes("**/meta**"), "help: a command with no id is plain bold text, never a broken mention");
    ok(!/\/(?:trade|deck|movers)\b/.test(h) && !/Price check/.test(h), "help: no retired command is mentioned");
    ok(h.includes("reports send"), "help: tells server managers about /reports send");
    eq(E.cmdMention({ card: "not-an-id" }, "card"), "**/card**", "cmdMention refuses an id that isn't a snowflake");
    for (const w of ["card", "open", "set"]) eq(E.parseHelpTryId(E.helpTryId(w)), w, `help "try" id round-trips: ${w}`);
    eq(E.parseHelpTryId("h|trade"), null, "a retired help example id is refused");
  }
  const calEvents = [
    { id: "x", kind: "dlc", title: "DLC Test", subtitle: "Disney Lorcana Challenge", starts_on: "2026-11-20", location: "Somewhere", country: "US", url: "https://example.com/dlc" },
    { id: "y", kind: "set", title: "Hyperia City", subtitle: "LGS release", starts_on: "2026-10-16" },
    { id: "z", kind: "ccq", title: "CCQ Test", starts_on: "2026-12-05", location: "Paris", country: "FR" },
  ];
  checkMessage(E.calendarMessage({ events: calEvents, kind: "all", region: "all", regions: [{ key: "na", label: "North America" }, { key: "eu", label: "Europe" }] }), "calendar");
  checkMessage(E.calendarMessage({ events: [], kind: "ccq", region: "eu", regions: [{ key: "eu", label: "Europe" }] }), "calendar, nothing matches");
  // A crowded month: long titles, long registration links, venue + street
  // addresses — the shape that clipped a field mid-timestamp in testing.
  const crowd = Array.from({ length: 12 }, (_, k) => ({ id: "c" + k, kind: k % 2 ? "ccq" : "dlc", title: `A Very Long Challenge Championship Qualifier Name Number ${k}`,
    starts_on: `2026-10-${String(k + 1).padStart(2, "0")}`, url: "https://example.com/register/" + "x".repeat(200) + k,
    location: `Some Convention Center Hall ${k} · 1234 Long Street Name Boulevard, Springfield, IL 62701`, country: "US" }));
  checkMessage(E.calendarMessage({ events: crowd, kind: "all", region: "all", regions: [] }), "calendar, a crowded month");
  eq(E.shortPlace("Charlie's Collectible Show · 3801 Sumner Blvd, Raleigh, NC 27616"), "Raleigh, NC 27616", "shortPlace keeps the city and region");
  eq(E.shortPlace("Schloss Freyenthurn, Austria"), "Schloss Freyenthurn, Austria", "shortPlace leaves a short place alone");
  {
    for (const k of ["all", "release", "dlc", "ccq"]) for (const r of ["all", "eu", "latam"]) {
      const back = E.parseCalendarId(E.calendarId("k", { kind: k, region: r }));
      ok(back && back.kind === k && back.region === r, `calendar id round-trips: ${k}/${r}`);
    }
    // ⚠ A release comes out everywhere: a region filter narrows Challenges
    // and qualifiers, never drops a set release.
    const far = [...calEvents.map((e) => ({ ...e, starts_on: "2099-01-01" }))];
    const eu = D.upcomingFiltered(far, { kind: "all", region: "eu", n: 12 });
    ok(eu.some((e) => e.kind === "set") && eu.some((e) => e.kind === "ccq") && !eu.some((e) => e.kind === "dlc"),
      `calendar region filter keeps releases, keeps Europe's qualifier, drops the US Challenge (${eu.map((e) => e.kind)})`);
    eq(D.upcomingFiltered(far, { kind: "release", n: 12 }).map((e) => e.kind).join(), "set", "calendar Releases keeps only releases");
  }
  const byKind = {
    sc: [{ next_start: "2026-11-04T17:00:00Z", store_name: "SC Shop", name: "Set Championship", kind: "sc", distance_mi: 12, dow: 6, local_time: "12:00", occurrence_count: 1, gameplay_format: "Core Constructed",
      occurrences: [{ url: "https://tcg.ravensburgerplay.com/events/9", start_datetime: "2026-11-04T17:00:00Z", registered_user_count: 32, capacity: 32, cost_cents: 2500, currency: "USD" }] }],
    prerelease: [
      { next_start: "2026-10-17T17:00:00Z", store_name: "Far Shop", kind: "prerelease", distance_mi: 40, gameplay_format: "Sealed", occurrences: [{ url: "https://tcg.ravensburgerplay.com/events/5", registered_user_count: 3, capacity: 16 }] },
      { next_start: "2026-10-18T17:00:00Z", store_name: "Near Shop", kind: "prerelease", distance_mi: 2, gameplay_format: "Sealed", occurrences: [{ url: "https://tcg.ravensburgerplay.com/events/6" }] }],
    other: [
      { next_start: "2026-10-04T17:00:00Z", store_id: 7, store_name: "A Shop", name: "Weekly", kind: "other", distance_mi: 3.2, dow: 6, local_time: "18:00", gameplay_format: "Core Constructed", occurrences: [{ url: "https://tcg.ravensburgerplay.com/events/1" }] },
      { next_start: "2026-10-04T17:00:00Z", store_id: 7, store_name: "A Shop", name: "Weekly Infinity", kind: "other", distance_mi: 3.2, dow: 6, local_time: "18:00", gameplay_format: "Infinity Constructed", occurrences: [{ url: "https://tcg.ravensburgerplay.com/events/2" }] },
      { next_start: "2026-10-01T17:00:00Z", store_id: 7, store_name: "A Shop", name: "Draft", kind: "other", distance_mi: 3.2, dow: 3, local_time: "19:00", gameplay_format: "Draft", occurrences: [{ url: "https://tcg.ravensburgerplay.com/events/3" }] }],
  };
  const place = { city: "Chicago", state: "IL", lat: 41.8781, lng: -87.6298 };
  for (const k of ["all", "sc", "prerelease", "other"]) {
    checkMessage(E.eventsMessage({ place, byKind, radius: 50, kind: k, query: "60614" }), `events ${k}`);
  }
  checkMessage(E.eventsMessage({ place, byKind: { sc: [], prerelease: [], other: [] }, radius: 10, kind: "all", query: "60614" }), "events, nothing near");
  checkMessage(E.eventsMessage({ place, byKind: { sc: null, prerelease: null, other: null }, radius: 10, kind: "all", query: "60614" }), "events, every query failed");
  {
    const m = E.eventsMessage({ place, byKind, radius: 50, kind: "all", query: "60614" });
    const f = Object.fromEntries(m.embeds[0].fields.map((x) => [x.name.split(" · ")[0], x.value]));
    ok(/\*\*full\*\*/.test(f["🏆 Set Championships"] || ""), "events: a Set Championship at capacity says full");
    ok((f["✨ Prereleases"] || "").indexOf("Near Shop") < (f["✨ Prereleases"] || "").indexOf("Far Shop"), "events: prereleases nearest first (they share a weekend)");
    const weekly = f["🗓️ Weekly play"] || "";
    ok(/Wed 7:00 PM Draft/.test(weekly) && /Sat 6:00 PM \(Core \+ Infinity\)/.test(weekly) && (weekly.match(/A Shop/g) || []).length === 1,
      `events: one line per store, a shared night lists both formats (${weekly})`);
    const st = { lat: 41.8781, lng: -87.6298, radius: 25, kind: "sc", label: "Chicago, IL" };
    const back = E.parseEventsId(E.eventsId("r", st));
    ok(back && back.lat === 41.878 && back.lng === -87.63 && back.radius === 25 && back.kind === "sc" && back.label === "Chicago, IL", `events id round-trips (${JSON.stringify(back)})`);
    ok(E.eventsId("k", { ...st, label: "x".repeat(200) }).length <= 100, "events id stays within 100 characters, whatever the place is called");
  }
}

// ── 8. card art Discord can show, and links that earn ────────────────────
{
  const O = "https://bot.example";
  const pr = (img, pid) => ({ id: "crd_x", img, f: [["N", pid || null, "Normal"]] });
  eq(E.cardImage(pr("/art/crd_x.webp?v=ab12cd34"), O), O + "/art/crd_x.webp?v=ab12cd34", "baked art is served from the Worker's own origin");
  eq(E.cardImage(pr("/art/crd_x.webp?v=ab12cd34"), null), null, "baked art needs the Worker's origin to be a URL");
  eq(E.cardImage(pr("https://cards.lorcast.io/card/digital/large/crd_x.avif")), null, "an AVIF is never sent — Discord doesn't show it");
  eq(E.cardImage(pr("data:image/jpeg;base64,AAAA")), null, "a data: URI is never sent — Discord rejects the whole reply");
  eq(E.cardImage(pr("Logos/cards/x.jpg")), null, "a relative path is never sent");
  eq(E.cardImage(pr("https://cards.lorcast.io/card/digital/large/crd_x.avif", 123)), "https://tcgplayer-cdn.tcgplayer.com/product/123_in_1000x1000.jpg",
    "a listed printing falls back to TCGplayer's photo");
  eq(E.cardImage(pr("https://packs.ink/Logos/cards/x.jpg", 123)), "https://packs.ink/Logos/cards/x.jpg", "a JPEG we host is used as it is");
  eq(E.cardImage(pr(null)), null, "nothing to show is nothing, not a broken picture");

  const dest = (u) => decodeURIComponent(u.slice(TCG_AFFILIATE.length));
  const prod = E.buyUrl("Mowgli - Man Cub", 659761, "Cold Foil");
  ok(prod.startsWith(TCG_AFFILIATE) && /\/product\/659761\//.test(dest(prod)) && /Printing=Cold%20Foil/.test(dest(prod)),
    `a listed printing links to its own TCGplayer page, through the affiliate program (${prod})`);
  const search = E.buyUrl("Mickey Mouse - Best in Town", null, "Normal");
  ok(search.startsWith(TCG_AFFILIATE) && /\/search\/lorcana\//.test(dest(search)) && dest(search).includes("q=Mickey%20Mouse%20-%20Best%20in%20Town"),
    `a card TCGplayer hasn't listed links to a TCGplayer search for it, through the affiliate program (${search})`);

  // The fixture is a slice of a real build: every printing in it has a picture
  // Discord can show. A null here means the build stopped baking art, or a new
  // image shape reached the index.
  const blind = [];
  for (const c of index.cards) for (const p of c.p) if (!E.cardImage(p, O)) blind.push(`${c.n} (${p.id})`);
  ok(!blind.length, `every fixture printing has a picture — ${blind.length} without, first: ${blind.slice(0, 3).join("; ")}\n     refresh the fixture with: node discord/tools/build_index.mjs --fixture`);
  ok(index.cards.some((c) => c.p.some((p) => String(p.img || "").startsWith("/art/"))), "the fixture carries baked art, so the replies above exercised it");
}

// ── 8b. the card tile /card shows ────────────────────────────────────────
// The site's own card tile, drawn per finish at deploy time (bake_tiles.mjs)
// and served from the Worker's origin. The reply may only point at a tile the
// build says it drew, never on a graded reply or where eBay sales lead.
{
  const { tileFile, tileUrl } = await mod("discord/src/tile.js");
  const { tileJobs, needsLonger, tileMeta, tileDate } = await mod("discord/tools/tile_rules.mjs");
  const O = "https://bot.example";
  eq(tileFile("crd_ABC123", "C"), "crd_abc123-c.webp", "a tile file is the card id and the finish, lower case");
  eq(tileFile("extras:647652", "N"), "extras-647652-n.webp", "a colon in a card id never reaches a path");
  eq(tileFile("crd_x::variant::text-error", "H"), "crd_x-variant-text-error-h.webp", "a variant clone gets its own tile file");
  eq(tileUrl({ id: "crd_x", tl: "NC" }, "C", O, "2026-09-28"), O + "/tile/crd_x-c.webp?d=2026-09-28", "a drawn tile is a URL on the Worker, dated so Discord re-fetches it");
  eq(tileUrl({ id: "crd_x", tl: "N" }, "C", O, "2026-09-28"), null, "no tile for a finish the build didn't draw");
  eq(tileUrl({ id: "crd_x" }, "N", O, "2026-09-28"), null, "no tile at all when the build drew none");
  eq(tileUrl({ id: "crd_x", tl: "N" }, "N", null, "2026-09-28"), null, "a tile needs the Worker's origin to be a URL");
  eq(tileMeta("Super Rare", null), "Super Rare", "tile meta: rarity alone when there's no finish to name");
  eq(tileMeta("Promo", "Top Prize"), "Promo · Top Prize", "tile meta: the site's badge after the rarity");
  eq(tileDate("2026-09-28"), "Sep 28, 2026", "tile date is the site's en-US date");

  // Which finishes get a tile.
  const ids = [{ n: "A", c: "A", p: [
    { id: "p1", f: [["N", 1, "Normal", null, 1, 2, 0], ["C", 2, "Cold Foil", "Foil", null, null, 0]] },
    { id: "p2", raw: 1, f: [["N", 3, "Normal", null, 5, 6, 0]] },
    { id: "p3", f: [["H", 4, "Holofoil", null, 7, 8, 1]] },
    { id: "p4", f: [["N", null, "Normal", null, 1, 1, 0]] },
    { id: "p5", tl: "N", f: [["N", 5, "Normal", null, 1, null, 0]] },
  ] }];
  const jobs = tileJobs(ids);
  eq(jobs.map((j) => `${j.p.id}${j.code}`).join(","), "p1N,p5N",
    "tiles: priced listed finishes only — no unpriced foil, no raw-eBay promo, no named variant without a SKU, no pid-less row");
  ok(!("tl" in ids[0].p[4]), "a rebuild clears the old tile marks before drawing");

  // Enough history for the 1M change: a daily month is enough, a hole is not.
  const days = (from, n) => Array.from({ length: n }, (_, i) => new Date(Date.parse(from + "T00:00:00Z") + i * 86400000).toISOString().slice(0, 10));
  const daily = days("2026-08-14", 46).map((d) => ({ date: d, low_price: 1, market_price: 2 }));
  eq(needsLonger(daily, "2026-09-28", [1, 2]), false, "a daily series over 45 days answers 1M without more history");
  eq(needsLonger(daily.slice(20), "2026-09-28", [1, 2]), true, "a series starting inside the month needs a longer fetch");
  const lowGap = daily.map((r, i) => (i < 40 ? { ...r, low_price: null } : r));
  eq(needsLonger(lowGap, "2026-09-28", [1, 2]), true, "a Low that was blank for weeks needs its older reference");
  eq(needsLonger(lowGap, "2026-09-28", [null, 2]), false, "a side with no catalog price asks for nothing");
  eq(needsLonger([], "2026-09-28", [null, 2]), true, "no history at all for a priced card fetches more");

  // The reply: card view shows the tile; graded, raw-led and chart views don't.
  const withTile = index.cards.flatMap((c) => c.p.filter((p) => p.tl && !p.raw).map((p) => ({ c, p })));
  ok(withTile.length > 20, `the fixture carries drawn tiles (${withTile.length} printings) — refresh it with: node discord/tools/build_index.mjs --fixture`);
  const pick = withTile.find(({ p }) => p.f.some((f) => f[0] === p.tl[0] && f[1]));
  if (pick) {
    const fi = pick.p.f.findIndex((f) => f[0] === pick.p.tl[0]);
    const res = { kind: "card", card: pick.c, index: index.cards.indexOf(pick.c), printing: pick.p, fi, dims: {}, notes: [], score: 1, exact: true, alts: [] };
    const base = { R, res, price: null, graded: [], raw: null, range: "3m", origin: O, inkColors: index.inkColors,
      gradedTarget: { cardId: pick.p.id, bucket: "" }, priceDate: "2026-09-28" };
    const want = O + "/tile/" + tileFile(pick.p.id, pick.p.tl[0]) + "?d=2026-09-28";
    const card = E.cardMessage({ ...base, view: "card" });
    eq(card.embeds[0].image && card.embeds[0].image.url, want, `/card shows the site's tile (${pick.c.n})`);
    checkMessage(card, "card with tile");
    const g = E.cardMessage({ ...base, view: "card", grade: { grader: "PSA", grade: "10" } });
    ok(!/\/tile\//.test(JSON.stringify(g.embeds[0])), "a graded reply never shows the raw-price tile");
    const rawLed = E.cardMessage({ ...base, view: "card", raw: { last_sold_price: 100, last_sold_date: "2026-09-20", avg_last_5: 90, last_5_count: 5, sale_count: 9, printing: "" },
      rawTarget: { cardId: pick.p.id, bucket: "" } });
    ok(!/\/tile\//.test(JSON.stringify(rawLed.embeds[0])), "where eBay sales lead, the TCGplayer tile is not shown");
    const chart = E.cardMessage({ ...base, view: "chart" });
    ok(!/\/tile\//.test(JSON.stringify(chart.embeds[0])), "the chart view keeps the plain thumbnail");
  }
}

// ── 10. sets and packs ───────────────────────────────────────────────────
{
  const S = await mod("discord/src/set.js");
  const name = (si) => (si >= 0 ? R.sets[si].n : null);
  const azurite = R.sets.findIndex((s) => s.n === "Azurite Sea");
  for (const [q, want] of [["azurite", "Azurite Sea"], ["Azurite Sea", "Azurite Sea"], ["set 6", "Azurite Sea"], ["azurit", "Azurite Sea"],
    ["the first chapter", "The First Chapter"], ["set hyperia", "Hyperia City"], ["xyzzy", null]]) {
    eq(name(R.resolveSet(q)), want, `resolveSet("${q}")`);
  }
  ok(R.suggestSets("", 25).length > 0 && R.sets[R.suggestSets("", 25)[0]].main === Math.max(...R.sets.map((s) => s.main || 0)),
    "set autocomplete with nothing typed starts at the newest booster set");
  for (const si of [azurite, R.resolveSet("hyperia city"), R.resolveSet("promo set 1"), R.resolveSet("the first chapter")].filter((x) => x >= 0)) {
    const o = S.setOverview(R, index, si);
    checkMessage(S.setMessage(o, { origin: "https://bot.example" }), `set ${R.sets[si].n}`);
  }
  {
    const o = S.setOverview(R, index, azurite);
    const m = S.setMessage(o, { origin: "https://bot.example" });
    const f = Object.fromEntries(m.embeds[0].fields.map((x) => [x.name, x.value]));
    ok(R.sets[azurite].ev && f["Box EV"] && f["Box EV"].includes("$" + R.sets[azurite].ev.mkt.toFixed(2)), `set: Box EV is the build's number (${f["Box EV"]})`);
    ok(/worth about \*\*\d+%\*\*/.test(f["Open or hold?"] || ""), "set: the open-or-hold verdict is a percentage of the box");
    ok(o.chase.every((x, k) => k === 0 || o.chase[k - 1].v >= x.v), "set: chase cards most expensive first");
    const desc = (m.embeds[1] || {}).description || "";
    ok(desc.split("\n").every((l) => (l.match(/\[/g) || []).length === (l.match(/\]\(/g) || []).length), "set: no chase link is clipped mid-way");
  }
  const up = S.setOverview(R, index, R.resolveSet("hyperia city"), { now: Date.parse("2026-09-28T00:00:00Z") });
  ok(up.upcoming, "a set whose LGS date is ahead is upcoming");
  ok(!JSON.stringify(S.setMessage(up, {})).includes("Box EV"), "an upcoming set shows no box EV (pre-sale prices)");
  // Packs: the site's simPack over pools built from the index, repeatable
  // with a seeded random.
  let seed = 7;
  const rnd = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
  const a1 = S.openPacks(R, azurite, 1, rnd);
  seed = 7;
  const a2 = S.openPacks(R, azurite, 1, rnd);
  ok(a1.pulls.length > 0 && JSON.stringify(a1.pulls.map((e) => e.p.id)) === JSON.stringify(a2.pulls.map((e) => e.p.id)), "a seeded pack is repeatable");
  ok(Math.abs(a1.total - a1.pulls.reduce((s, e) => s + (e.price || 0), 0)) < 1e-9, "a pack's total is the sum of its pulls");
  const pools = S.packPools(R, azurite);
  ok(pools.byInk && pools.enc && pools.rar, "pack pools have the site's shape");
  ok(Object.values(pools).flatMap((v) => (Array.isArray(v) ? v : Object.values(v).flat())).every((e) => R.cards[e.i].p.includes(e.p) && e.p.s === azurite),
    "every pack pull comes from the set being opened");
  const box = S.openPacks(R, azurite, 24, rnd);
  ok(box.n === 24 && new Set(box.pulls.map((e) => e.pack)).size === 24, "a box is 24 packs");
  checkMessage(S.packMessage(R, index, azurite, a1, { origin: "https://bot.example", who: "Test" }), "open a pack");
  checkMessage(S.packMessage(R, index, azurite, box, { origin: "https://bot.example" }), "open a box");
  const pm = S.packMessage(R, index, azurite, a1, { origin: "https://bot.example" });
  ok(pm.embeds.length <= 4 && pm.embeds.slice(1).every((e) => e.url === pm.embeds[0].url && e.image), "pack pictures share one url — Discord's image gallery");
  for (const n of [1, 24]) { const b = S.parsePackId(S.packId(azurite, n)); ok(b && b.si === azurite && b.n === n, `pack id round-trips (${n})`); }
  eq(S.parsePackId("k|3|7"), null, "a pack id only opens 1 or 24");
}

// ── 10c. /new — the site's reveal reel, worked out when asked ────────────
// The build stores the reel's INPUTS and the Worker runs the site's own
// revealRotation over them, plus any card added since. Pinned: the stored
// inputs give the site's reel at the build moment AND later (cards and names
// ageing out on the site's schedule); a card added after the build shows up,
// judged by the site's catalog rules; a reprint never does, and if that cannot
// be checked nothing fresh is shown; the reply's shape.
{
  const S = await mod("discord/src/set.js");
  const G = await mod("discord/src/site.generated.js");
  const now = Date.parse("2026-09-28T12:00:00Z");
  const H = 3600 * 1000;
  const iso = (ms) => new Date(ms).toISOString();
  eq(S.REVEAL_WINDOW_MS, G.REVEAL_WINDOW_HOURS * H, "/new's window is the site's REVEAL_WINDOW_HOURS");

  // (a) An index built before first-seen times were stored ({id, t} alone)
  // still works: the window is kept; an aged-out, a future and an unknown card
  // are dropped.
  const ids = index.cards.slice(0, 45).map((c) => c.p[0].id);
  const batch = [1, 20, 40];
  const legacy = [
    ...ids.slice(0, 36).map((id, k) => ({ id, t: now - batch[Math.floor(k / 12)] * H })),
    { id: ids[36], t: now - 97 * H },
    { id: ids[37], t: now + 5 * H },
    { id: "crd_not_in_this_index", t: now - H },
  ];
  const got = S.newCards(R, { ...index, reveals: legacy }, now);
  eq(got.length, 36, "/new keeps the 96-hour window and drops an aged-out, a future and an unknown card");
  ok(got.every((c, k) => k === 0 || got[k - 1].t >= c.t), "/new lists the newest first");
  eq(S.newCards(R, { ...index, reveals: undefined }, now).length, 0, "/new on an index with no reveals shows nothing, not an error");

  // (b) Storing inputs instead of the answer is only safe if they give the
  // site's reel at every later moment too. Random catalogs: names shared across
  // cards, printings, Extras rows, missing art, missing and future stamps.
  {
    let seed = 11;
    const rnd = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
    const noR = { byCardId: new Map(), cards: [], sets: [] };
    let bad = 0, checks = 0, full = 0;
    for (let trial = 0; trial < 80; trial++) {
      const rows = [];
      const names = 5 + Math.floor(rnd() * 25);
      for (let c = 0; c < 45; c++) {
        const name = "Card " + Math.floor(rnd() * names);
        const at = rnd() < 0.05 ? null : iso(now - rnd() * 9 * 24 * H + (rnd() < 0.06 ? 30 * H : 0));
        const set = rnd() < 0.08 ? G.EXTRAS_SET_NAME : (rnd() < 0.5 ? "Hyperia City" : "Promo Set 3");
        const no = String(1 + Math.floor(rnd() * 200));
        const n = rnd() < 0.3 ? 2 : 1;
        for (let k = 0; k < n; k++) {
          rows.push({ card_id: "c" + c, "Product Name": name, Set: k && rnd() < 0.3 ? G.EXTRAS_SET_NAME : set,
            added_at: at, img_normal: rnd() < 0.12 ? null : "art.jpg", Number: no });
        }
      }
      const inputs = S.revealInputs(rows, { now });
      for (const h of [0, 1, 7, 23, 49, 95, 97, 150]) {
        const want = G.revealRotation(rows, now + h * H).map((c) => c.card_id).join();
        const have = G.revealRotation(S.indexRevealRows(noR, { reveals: inputs }), now + h * H).map((c) => c.card_id).join();
        checks++;
        if (want) full++;
        if (want !== have) bad++;
      }
    }
    eq(bad, 0, `the stored reveal inputs give the site's reel now and later (${checks} checks, ${full} non-empty)`);
  }

  // (c) Cards added after the build: read from the database, put through the
  // site's catalog rules, reprints left out.
  const known = index.cards[0].p[0];
  const extrasOnly = Object.keys(G.EXTRAS_MAP).find((pid) => G.EXTRAS_MAP[pid].excludeFromBaseSet);
  const row = (id, extra) => ({ id, name: "Brand New", version: id, set_id: "set_x", rarity: "Common", ink: "Ruby", inks: null,
    collector_number: "7", image_small: null, image_normal: "https://img.example/" + id + ".jpg", image_large: null,
    tcgplayer_product_id: null, inserted_at: iso(now - 2 * H), sets: { name: "Hyperia City" }, ...extra });
  const freshRows = [
    row("first-look", { rarity: "Super_rare", inks: ["Ruby", "Amber"] }),
    row("avif-only", { rarity: "Enchanted", image_normal: "https://cards.lorcast.io/card/x.avif", inserted_at: iso(now - 3 * H) }),
    row("listed", { name: "Listed Promo", version: "Fresh", rarity: "Rare", tcgplayer_product_id: 999001,
      image_normal: "https://cards.lorcast.io/card/p.avif", sets: { name: "Promo Set 3" }, inserted_at: iso(now - 4 * H) }),
    row("renamed-set", { name: "Renamed", sets: { name: "Challenge Promo" } }),
    row("unheard-set", { name: "Far Future", sets: { name: "A Set Nobody Has Seen" } }),
    row("quoted", { name: 'Wake Up, "Alice"', version: "Back\\Slash", inserted_at: iso(now - 5 * H) }),
    row("reprint", { name: "Old Friend", version: "Again" }),
    row(known.id, { name: "Known" }),
    row([...G.SUPPRESSED_CARD_IDS][0], { name: "Suppressed" }),
    row("no-set", { name: "Nowhere", sets: null }),
    row("no-art", { name: "Blank", image_normal: null }),
    row("future", { name: "Tomorrow", inserted_at: iso(now + 5 * H) }),
    row("companion", { name: "Companion", tcgplayer_product_id: Object.values(G.CONNECTING_FOILS)[0] }),
    ...(extrasOnly ? [row("extras-only", { name: "Extras Only", tcgplayer_product_id: Number(extrasOnly) })] : []),
  ];
  const calls = [];
  const stub = {
    async get(table, params) {
      calls.push({ table, params });
      if (params.inserted_at) return freshRows;
      return [{ id: "crd_old_friend", name: "Old Friend", version: "Again" }];
    },
  };
  const ix = { ...index, reveals: legacy.slice(24, 29), catalogAt: iso(now - 10 * H) };
  const fresh = await S.freshRevealRows(stub, R, ix, now);
  eq(calls[0] && calls[0].params.inserted_at, "gt." + iso(now - 12 * H), "/new asks for cards added since the index read the catalog (with 2h of overlap)");
  ok(calls[0] && /sets\(name\)/.test(calls[0].params.select), "the fresh read brings each card's set name with it");
  const inList = calls[1] && calls[1].params.name;
  ok(inList && inList.includes('"Wake Up, \\"Alice\\""') && inList.includes('"Brand New"'), `names in the reprint check are quoted for PostgREST (${inList})`);
  ok(calls[1] && calls[1].params.or === `(inserted_at.lt."${iso(now - S.REVEAL_WINDOW_MS)}",inserted_at.is.null)`, "the reprint check asks for rows older than the window, or never stamped");
  const cards = S.newCards(R, ix, now, fresh);
  const fr = cards.filter((c) => c.fresh);
  eq(fr.map((c) => c.name).sort().join(" | "), ["Brand New - first-look", "Brand New - avif-only", "Listed Promo - Fresh",
    "Renamed - renamed-set", "Far Future - unheard-set", 'Wake Up, "Alice" - Back\\Slash'].sort().join(" | "),
    "/new shows a just-added card, and not a reprint, a known, suppressed, setless, artless, future or companion card, nor one that lives only in Extras");
  ok(cards[0].fresh && cards[0].name === "Brand New - first-look", "the newest just-added card heads the list");
  const rarity = Object.fromEntries(fr.map((c) => [c.name, c.fresh.rarity]));
  eq(rarity["Brand New - first-look"], "Super Rare", "a just-added card's rarity is normalised the site's way");
  eq(rarity["Listed Promo - Fresh"], "Promo", "a just-added promo-set card reads Promo, as on the site");
  eq(rarity["Far Future - unheard-set"], "Promo", "a card of a set the site doesn't order yet reads Promo, as on the site");
  eq(fr.find((c) => c.name === "Renamed - renamed-set").set, "Lorcana Challenge Promo (C1)", "a just-added card's set gets the site's display name");
  const nm = S.newCardsMessage(R, ix, cards, { origin: "https://bot.example", now });
  checkMessage(nm, "new cards, with just-added ones");
  const nd = nm.embeds[0].description;
  const lineOf = (name) => nd.split("\n").find((l) => l.includes(name));
  ok(lineOf("Brand New - first-look") && !lineOf("Brand New - first-look").includes("](") && lineOf("Brand New - first-look").startsWith("🟥🟨"),
    `a just-added card with no listing is unlinked and shows its inks (${lineOf("Brand New - first-look")})`);
  ok(lineOf("Listed Promo") && lineOf("Listed Promo").includes("](https://partner.tcgplayer.com/"), "a just-added card with a listing links to it through the affiliate");
  const fm = S.newCardsMessage(R, ix, fr, { origin: "https://bot.example", now });
  checkMessage(fm, "new cards, only just-added ones");
  const pics = fm.embeds.map((e) => e.image && e.image.url).filter(Boolean);
  ok(pics.includes("https://img.example/first-look.jpg") && pics.includes("https://tcgplayer-cdn.tcgplayer.com/product/999001_in_1000x1000.jpg")
    && !pics.some((u) => /\.avif/.test(u)), `just-added art is used only where Discord can show it (${pics.join(", ")})`);
  ok(!fm.components.some((r) => r.components[0].type === 3), "a reel of only just-added cards has no menu");
  const opts = nm.components.filter((r) => r.components[0].type === 3).flatMap((r) => r.components[0].options);
  ok(opts.length > 0 && opts.every((o) => { const h = R.resolve(o.value); return h && h.kind === "card"; }), "every /new menu entry opens a card the bot knows");
  ok(!opts.some((o) => fr.some((c) => c.name === o.label)), "just-added cards stay out of the menus");
  ok(/open from the menu after the daily update/.test(nm.embeds[0].footer.text), "the footer says when just-added cards join the menus");
  // Failures. The fresh read failing leaves the index; the reprint check
  // failing shows nothing fresh rather than risk calling an old card new.
  const downReprint = { async get(t, p) { if (p.inserted_at) return freshRows; throw new Error("down"); } };
  let threw = false;
  try { await S.freshRevealRows(downReprint, R, ix, now); } catch { threw = true; }
  ok(threw, "if the reprint check cannot be asked, no just-added card is shown");
  const late = [];
  await S.freshRevealRows({ async get(t, p) { late.push(p); return []; } }, R, { ...ix, catalogAt: iso(now - 200 * H) }, now);
  eq(late[0] && late[0].inserted_at, "gt." + iso(now - S.REVEAL_WINDOW_MS), "a stale index asks for the whole window, never further back");
  eq(late.length, 1, "no fresh cards, no reprint check");

  // (d) The reply. Headings are days back from the moment of asking; the set
  // named is the one that dominates the reel; 36 cards read as the newest 36.
  const reveals = [
    ...ids.slice(0, 20).map((id, k) => ({ id, t: now - (k < 10 ? 1 : 20) * H, n: "Card " + k, s: "Hyperia City", no: String(k) })),
    ...ids.slice(20, 30).map((id, k) => ({ id, t: now - 40 * H, n: "Card " + (20 + k), s: "Promo Set 3", no: String(k) })),
    ...ids.slice(30, 36).map((id, k) => ({ id, t: now - 80 * H, n: "Card " + (30 + k), s: "Hyperia City", no: String(k) })),
  ];
  const ixd = { ...index, reveals };
  const cd = S.newCards(R, ixd, now);
  eq(cd.length, 36, "/new holds the site's 36");
  const m = S.newCardsMessage(R, ixd, cd, { origin: "https://bot.example", now });
  checkMessage(m, "new cards");
  const d = m.embeds[0].description;
  eq(m.embeds[0].title, "Just revealed: Hyperia City", "/new names the set that dominates the reel");
  ok(/^The \*\*36\*\* newest cards/.test(d), "/new at the reel's cap says these are the newest, not all of them");
  const heads = (d.match(/^\*\*Added [^*]+\*\*$/gm) || []).join(" | ");
  eq(heads, "**Added in the last 24 hours** | **Added 1–2 days ago** | **Added 3–4 days ago**", "/new heads each day once, newest first");
  const shown = d.split("\n").filter((l) => l && !l.startsWith("**") && !l.startsWith("The ") && !l.startsWith("*…")).length;
  const more = Number((/\*…and (\d+) more\*/.exec(d) || [0, 0])[1]);
  eq(shown + more, 36, `/new accounts for every card, shown or counted (${shown} + ${more})`);
  ok(m.embeds.length <= 4 && m.embeds.slice(1).every((e) => e.url === m.embeds[0].url && e.image), "/new pictures are one gallery");
  const menus = m.components.filter((r) => r.components[0].type === 3).map((r) => r.components[0]);
  eq(menus.map((x) => x.options.length).join("+"), "25+11", "/new puts all 36 cards in two menus");
  ok(menus.every((x) => E.parseOpenId(x.custom_id) && E.parseOpenId(x.custom_id).view === "card"), "both /new menus open a card");
  ok(!/open from the menu after/.test(m.embeds[0].footer.text), "no just-added note when nothing was just added");
  // No set dominating: no set in the title. A card of another set says which;
  // a card with no listing is not linked.
  const unlisted = index.cards.flatMap((c) => c.p).find((p) => (p.f[0] || [])[6]);
  const two = S.newCards(R, { ...index, reveals: [{ id: ids[0], t: now - H }, { id: ids[1], t: now - H }, { id: unlisted.id, t: now - H }] }, now);
  const tm = S.newCardsMessage(R, index, two, { origin: "https://bot.example", now });
  checkMessage(tm, "new cards, mixed");
  const sets3 = new Set(two.map((c) => c.set));
  if (sets3.size === 3) eq(tm.embeds[0].title, "Just revealed", "with no set over half the reel, the title names none");
  const tl = tm.embeds[0].description.split("\n");
  ok(two.every((c) => c.set === revealLabel(two) || tl.some((l) => l.endsWith(" · " + c.set))), "/new names the set of a card from another set");
  const ul = tl.find((l) => l.includes(R.cards[R.byCardId.get(unlisted.id).i].n));
  ok(ul && !ul.includes("]("), `/new leaves a card with no listing unlinked (${ul})`);
  const none = S.newCardsMessage(R, index, [], { now });
  checkMessage(none, "new cards, none");
  ok(/Nothing new/.test(none.embeds[0].title) && none.components.flatMap((r) => r.components).every((c) => c.style === 5),
    "/new says so when nothing was revealed, with only a link to the calendar");
  function revealLabel(cs) { return G.revealSetLabel(cs); }
}

// ── 10b. the meta, a card's play line, a card's rules text ──────────────
{
  const today = "2026-09-29";
  const sets = [{ n: "Old Set", main: 12, date: "2026-05-08" }, { n: "Newest Out", main: 13, date: "2026-07-17" }, { n: "Not Out Yet", main: 14, date: "2026-10-16" }];
  eq(D.metaSet(sets, today).n, "Newest Out", "meta: the window opens at the newest set already on shelves, not an announced one");
  eq(D.metaSince(sets, today), "2026-07-17", "meta: one read reaches back to the set's release");
  eq(D.metaSince([{ n: "Fresh", main: 14, date: "2026-09-25" }], today), "2026-08-15", "meta: a set out for days still reads the last 45 days");
  let n = 0;
  const row = (t, date, rank, inks, extra = {}) => ({ tournament_id: t, tournament_name: "Event " + t, event_date: date, tournament_format: "core",
    num_players: 64, place: rank === 1 ? "1st" : "Top " + (rank <= 4 ? 4 : 8), place_rank: rank, player_name: "P" + (++n), deck_id: "d" + n,
    deck_name: null, deck_inks: inks, deck_visibility: "public", deck_share_token: null, ...extra });
  const rows = [];
  const event = (t, date, pairs, extra = {}) => pairs.forEach((inks, k) => rows.push(row(t, date, k + 1, inks, extra)));
  const AE = ["Emerald", "Amber"], AA = ["Amber", "Amethyst"], ES = ["Emerald", "Steel"];
  event("e1", "2026-09-26", [AE, AA, ES, AE, AA, AE, ES, AA], { num_players: 128 });
  event("e2", "2026-09-20", [AA, AE, AE, ES], { num_players: 300 });
  event("e3", "2026-09-12", [AE, ES, AA, AA, AE, AE, AE, ES], { num_players: 64 });
  event("e4", "2026-09-10", [ES], { num_players: 900 });                                   // winner only: a stub
  event("e5", "2026-09-05", [AA, AA, AE, ES], { num_players: 500, tournament_format: "infinity" });
  event("e6", "2026-06-01", [ES, ES, ES, ES], { num_players: 1000 });                       // before the set
  event("e7", "2026-09-15", [AA, AA, AA, AA], { num_players: 32, tournament_format: "infinity" }); // recent, but the smallest
  const m = D.buildMeta(rows, { sets, today });
  eq(m.sinceSet, "Newest Out", "meta: counted since the set");
  eq(m.events, 4, "meta: Core events since the set only (Infinity and older events are left out)");
  eq(m.decks, 21, "meta: every top-8 deck of those events");
  eq(m.breakdown[0].key, "Amber/Emerald", "meta: an ink pair is named in ink order, whatever order the deck listed it");
  eq(m.breakdown[0].n, 9, "meta: the most-played pair leads");
  ok(m.breakdown.every((p, k) => k === 0 || m.breakdown[k - 1].n >= p.n), "meta: pairs by top-8 count, most first");
  eq(m.breakdown.find((p) => p.key === "Amber/Amethyst").wins, 1, "meta: a win counts once");
  eq(m.breakdown.find((p) => p.key === "Emerald/Steel").t4, 4, "meta: top 4s counted (a winner-only event's winner too)");
  eq(m.recent.map((e) => e.id).join(), "e1,e2,e3", "meta: the three biggest events of the last three weeks with a real top cut, newest first (the smallest and a winner-only stub are skipped)");
  eq(D.buildMeta(rows.filter((r) => r.tournament_id !== "e1" && r.tournament_id !== "e2"), { sets, today }).recent.map((e) => e.id).join(), "e7,e3,e5",
    "meta: under three in three weeks, it reaches back further for the biggest");
  const thin = D.buildMeta(rows.filter((r) => r.tournament_id === "e1" || r.tournament_id === "e6"), { sets, today });
  ok(!thin.sinceSet && thin.from === "2026-08-15", "meta: under three events since the set, it widens to the last 45 days and says so");

  const mm = E.metaMessage({ R, index, meta: m });
  checkMessage(mm, "meta");
  const d0 = mm.embeds[0].description;
  ok(/21 top-8 decks from 4 Core events since Newest Out/.test(d0), `meta: the breakdown says what it counted (${d0.split("\n")[0]})`);
  ok(/🟨🟩 `█{10} 43%` \*\*Amber\/Emerald\*\* · 9 decks/.test(d0), `meta: a pair's line carries its marks, a bar and its share (${d0.split("\n")[2]})`);
  ok(/🟨🟪 `█{7}░{3} 29%` \*\*Amber\/Amethyst\*\*/.test(d0), `meta: bars are scaled to the leading pair (${d0.split("\n")[3]})`);
  eq(mm.embeds.map((e) => e.title).join(" | "), "What's winning: ink pairs in top 8s | Most played in Attack of the Vine! | Latest big events", "meta: breakdown first, then the cards, then the events");
  const withNames = { ...m, recent: [{ id: "t1", name: "Big Event", date: "2026-09-12", players: 200, format: "infinity", top: [
    { place: "1st", place_rank: 1, player_name: "[OSA] Moluk_x", deck_id: "d1", deck_name: null, deck_inks: ["Amber", "Emerald"], deck_visibility: "public", deck_share_token: "tok" },
    { place: "Top 4", place_rank: 4, player_name: "Some*one", deck_id: "d2", deck_name: "Rush", deck_inks: ["Ruby"], deck_visibility: "unlisted", deck_share_token: "abc" }] }] };
  const mt = JSON.stringify(E.metaMessage({ R, index, meta: withNames }));
  ok(mt.includes("\\\\[OSA\\\\] Moluk\\\\_x") && mt.includes("Some\\\\*one"), "meta: player names are escaped, not read as markdown");
  ok(mt.includes("decks?deck=d1)") && mt.includes("deck=d2&token=abc"), "meta: a public deck links without its token, an unlisted one with it");
  ok(mt.includes("200 players · Infinity"), "meta: an Infinity event says so");
  checkMessage(E.metaMessage({ R, index, meta: D.buildMeta([], { sets, today }) }), "meta, nothing on record");
  checkMessage(E.metaMessage({ R, index, meta: null }), "meta, read failed");
  const played = index.cards.map((c, i) => ({ c, i })).filter((x) => x.c.ps > 0).sort((a, b) => b.c.ps - a.c.ps || a.i - b.i)[0];
  if (played) {
    eq(E.playRankOf(R, played.i), 1, "the most-played card ranks #1");
    const pline = E.playLine(R, played.i, index.playSet) || "";
    ok(/#1 most played/.test(pline), "its play line says so");
    ok(pline.includes(`of ${index.playSet.n} top-cut decks`), `the play line names the current set (${pline})`);
    eq(E.playLine(R, played.i, { ...index.playSet, decks: E.PLAY_SET_MIN_DECKS - 1 }), null, "too few decks in the current set: no play line");
    eq(E.playLine(R, played.i, null), null, "no current set on record: no play line");
  }
  const cold = index.cards.findIndex((c) => !c.ps);
  if (cold >= 0) eq(E.playLine(R, cold, index.playSet), null, "a card not played in the current set gets no play line");
  const mmPlay = JSON.stringify(E.metaMessage({ R, index, meta: null }));
  ok(mmPlay.includes(`Most played in ${index.playSet.n}`), "/meta's card list is the current set's");
  const g = E.gameplayLine({ i: ["Amber", "Steel"], cost: 3, t: "Character", k: ["Storyborn", "Hero"] });
  ok(g.includes("🟨⬜ Amber/Steel") && g.includes("3 cost") && g.includes("Character — Storyborn, Hero"), `gameplay line (${g})`);

  // A card's rules text, as printed: ability names bold, keywords bold,
  // reminder text italic, the symbols in words.
  const rt = E.rulesText({ x: "Shift 5 {I} (You may pay 5 {I} to play this on top of one of your characters named Elsa.)\nEvasive\nDEEP FREEZE When you play this character, exert chosen opposing character.", w: ["Shift", "Evasive"] });
  ok(rt.startsWith("> **Shift 5 ink**"), `rules: a keyword and its cost are bold (${rt.split("\n")[0]})`);
  ok(/\*\(You may pay 5 ink to play this/.test(rt), "rules: reminder text is italic, its symbols spelled out");
  ok(/> \*\*Evasive\*\*/.test(rt) && /> \*\*DEEP FREEZE\*\* When you play/.test(rt), `rules: a bare keyword and an ability name are bold (${rt})`);
  ok(rt.split("\n").every((l) => l.startsWith("> ")), "rules: every line is quoted, so the text reads as the card's");
  eq(E.rulesText({ x: "" }), "", "rules: a card with no text gets no rules block");
  eq(E.rulesText({ x: "Deal 2 damage to chosen character_with *stars*." }), "> Deal 2 damage to chosen character\\_with \\*stars\\*.", "rules: markdown in card text is escaped");
  const sl = E.statsLine({ st: [3, 5, 2, null] });
  ok(/\*\*3\*\* strength/.test(sl) && /\*\*5\*\* willpower/.test(sl) && /\*\*2\*\* lore/.test(sl) && !/move/.test(sl), `stats line (${sl})`);
  eq(E.statsLine({ st: [null, null, null, null] }), "", "an action has no stats line");
  ok(/uninkable/.test(E.gameplayLine({ i: ["Amber"], cost: 2, t: "Action", ik: 0 })), "an uninkable card says so");
  // The fixture's cards carry their text, and a /card reply shows it.
  const withText = index.cards.find((c) => c.x && c.w && c.w.length);
  ok(withText, "the fixture carries card text");
  if (withText) {
    const res = R.resolve(withText.n);
    const cm = E.cardMessage({ R, res, price: D.priceSummary([]), graded: [], raw: null, view: "card", range: "3m", origin: "https://bot.example", inkColors: index.inkColors });
    ok(!/\n> /.test(cm.embeds[0].description), `a /card reply leaves the rules text to the card picture (${withText.n})`);
    checkMessage(cm, "card with rules text");
  }
  // Every card's text fits: the longest one still leaves the reply inside Discord's limits.
  const longest = index.cards.filter((c) => c.x).sort((a, b) => b.x.length - a.x.length)[0];
  if (longest) {
    const cm = E.cardMessage({ R, res: R.resolve(longest.n), price: D.priceSummary([]), graded: [], raw: null, view: "card", range: "3m", origin: "https://bot.example", inkColors: index.inkColors });
    checkMessage(cm, `card with the longest text (${longest.n})`);
  }
  // The stats a picker shows (Zaven: "amethyst 6c inkable 5/6 2lore and any
  // keywords"): words on a menu's sub-line, the same on a suggestion's line.
  {
    const S = await mod("discord/src/stats.js");
    const demona = { n: "Demona - Scourge of the Wyvern Clan", i: ["Amethyst"], cost: 6, t: "Character", w: [], st: [5, 6, 2, null], ik: 1, x: "AD SAXUM COMMUTATE When you play…" };
    eq(S.statsLineFor(demona), "Amethyst · 6c · inkable · 5/6 · 2⟡", "stats: a character in words");
    const elsa = { i: ["Amethyst"], cost: 8, t: "Character", w: ["Shift", "Evasive"], st: [4, 6, 3, null], ik: 0,
      x: "Evasive (Only characters with Evasive can challenge this character.)\nShift 6 {I} (You may pay 6 {I} to play this…)" };
    eq(S.keywordTags(elsa).join(", "), "Evasive, Shift 6", "stats: keywords in printed order, with their numbers");
    eq(S.statsLineFor(elsa), "Amethyst · 8c · uninkable · 4/6 · 3⟡ · Evasive · Shift 6", "stats: uninkable and keywords");
    eq(S.statsLineFor({ i: ["Ruby"], cost: 3, t: "Location", st: [null, 5, 2, 1], ik: 1 }), "Ruby · 3c · inkable · Location · move 1 · 5 willpower · 2⟡", "stats: a location's move and willpower");
    eq(S.statsLineFor({ i: ["Ruby"], cost: 7, t: "Action - Song", st: [null, null, null, null], ik: 0 }), "Ruby · 7c · uninkable · Song", "stats: a song says so");
    eq(S.keywordTags({ w: ["Resist", "Singer"], x: "Resist +1 (Damage dealt…)\nSinger 5 (This character counts as cost 5 to sing songs.)" }).join(", "), "Resist +1, Singer 5", "stats: Resist +1, Singer 5");
    eq(S.keywordTags({ w: ["Shift"], x: "Universal Shift 4" }).join(), "Shift", "stats: a keyword's number is read only from its own line");
    const long = S.statsLineFor(elsa, ["Legendary", "#1 most played", "$123,456.00", "x".repeat(40)]);
    ok(long.length <= 100 && long.startsWith("Amethyst · 8c"), `stats: a sub-line never passes 100 characters, and keeps the stats first (${long})`);
    // Every suggestion line over the fixture: ≤100, the stats in it, and the
    // price left out (the reply has the numbers).
    let seen = 0, priced = 0;
    R.cards.forEach((c) => c.p.forEach((p) => p.f.forEach((f, fi) => {
      const l = R.suggestLabel(c, p, fi);
      seen++;
      ok(l.length <= 100, `suggestion ≤100 characters (${l})`);
      ok(l.startsWith(c.n + " — "), `suggestion starts with the card's name (${l})`);
      const px = f[5] ?? f[4];
      if (px != null) { priced++; ok(!/\$\d/.test(l.slice(c.n.length)), `suggestion leaves the price out (${l})`); }
      ok(!/Non-foil/.test(l) && (f[3] || !/Foil/.test(l)), `suggestion doesn't name a plain finish (${l})`);
      ok(!/ \dc\b/.test(l.slice(c.n.length)), `suggestion leaves the cost out (${l})`);
      ok(!/\blore\b/.test(l.slice(c.n.length)), `suggestion writes lore as the symbol (${l})`);
      const set = R.sets[p.s] || {};
      if (set.main && !/…/.test(l)) ok(l.includes(`S${set.main}`), `suggestion names the set's number (${l})`);
    })));
    for (const q of ["elsa", "ursula", "mickey", "stitch"]) {
      const lines = R.suggest(q, 25).filter((x) => x.kind === "card").map((x) => x.label);
      ok(new Set(lines).size === lines.length, `suggestions for "${q}" have no repeated lines`);
    }
    ok(seen > 200 && priced > 100, `every fixture printing checked (${seen}, ${priced} priced)`);
    const sug = R.suggest("elsa spirit", 5).find((s) => s.kind === "card");
    ok(sug && /🟪/.test(sug.label) && /S\d+\)?$/.test(sug.label) && / \| /.test(sug.label), `a /card suggestion carries the stats on its line (${sug && sug.label})`);
    const nf = E.notFoundMessage(R, { kind: "none", query: "elsa?", suggestions: R.suggest("elsa", 5) }, "elsa?");
    const opts = (nf.components[0] || { components: [{ options: [] }] }).components[0].options;
    ok(opts.length && opts.every((o) => !/ \| /.test(o.label)) && opts.filter((o) => o.description).every((o) => /\d+c/.test(o.description)),
      `"did you mean": the label names the printing, the sub-line gives the stats (${opts[0] && opts[0].description})`);
    const st = R.resolve("stitch");
    const vo = E.versionOptions(R, st);
    const own = vo.filter((o) => o.label.includes(" · ")), alt = vo.filter((o) => /^Stitch - /.test(o.label));
    ok(alt.length && alt.every((o) => /^\w+(?:\/\w+)? · \d+c · /.test(o.description || "")), `versions menu: another version's sub-line leads with its stats (${alt[0] && alt[0].description})`);
    ok(own.every((o) => !/\dc · /.test(o.description || "")), "versions menu: the card's own printings don't repeat the stats shown above");
    ok(vo.every((o) => !o.description || o.description.length <= 100), "versions menu: every sub-line within 100");
  }
  // An event links to ITS page on packs.ink, which links on to the organiser.
  eq(E.eventPageUrl("ev:123"), "https://packs.ink/calendar?ce=ev%3A123", "an RPH event links to its page on the calendar");
  eq(E.eventPageUrl(null), null, "no id, no page");
}

// ── 11. the resolver's shortcut is exact ─────────────────────────────────
// expand() skips a candidate whose letters differ by more than two per edit
// allowed — only sound if one edit can never change more than two. Checked on
// real vocabulary pairs: whenever dl() says ≤ k, the letter test must pass.
{
  const { letterMask, popcount } = await mod("discord/src/resolver.js");
  const { dl, tokens } = await mod("discord/src/text.js");
  const vocab = [...new Set(index.cards.flatMap((c) => tokens(c.n)))].filter((t) => t.length >= 4);
  let pairs = 0, bad = 0, s = 11;
  const rnd = () => ((s = (s * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
  const mut = (w) => {   // one to two random edits, so near misses are common
    let x = w;
    for (let k = 0; k < 1 + Math.floor(rnd() * 2); k++) {
      const i = Math.floor(rnd() * x.length), op = Math.floor(rnd() * 4), ch = String.fromCharCode(97 + Math.floor(rnd() * 26));
      x = op === 0 ? x.slice(0, i) + ch + x.slice(i) : op === 1 ? x.slice(0, i) + x.slice(i + 1) : op === 2 ? x.slice(0, i) + ch + x.slice(i + 1)
        : i + 1 < x.length ? x.slice(0, i) + x[i + 1] + x[i] + x.slice(i + 2) : x;
    }
    return x;
  };
  for (const w of vocab) {
    const v = mut(w);
    for (const k of [1, 2]) {
      const d = dl(w, v, k);
      if (d > k) continue;
      pairs++;
      const [a1, b1] = letterMask(w), [a2, b2] = letterMask(v);
      if (popcount(a1 ^ a2) + popcount(b1 ^ b2) > 2 * k) bad++;
    }
  }
  ok(pairs > 200 && bad === 0, `the letter test never rejects a pair within the edit distance (${pairs} pairs, ${bad} wrongly rejected)`);
  eq(popcount(0), 0, "popcount(0)");
  eq(popcount(0xffffffff | 0), 32, "popcount of all bits");
}

// ── 12. a reply Discord refuses still reaches the person ────────────────
{
  const { plainFallback } = await mod("discord/src/interactions.js");
  const big = { embeds: [{ title: "T", url: "https://x.example/", description: "line\n".repeat(900), fields: [{ name: "F", value: "a\nb" }], footer: { text: "foot" } }], components: [{ type: 1, components: [] }] };
  const pf = plainFallback(big);
  ok(pf.content.length <= 2000 && pf.embeds.length === 0 && pf.components.length === 0, "the plain fallback is text only, within 2,000 characters");
  ok(pf.content.startsWith("**T**"), "the plain fallback keeps the title");
}

// ── 13. what a reply LEADS with (2026-09-30) ─────────────────────────────
// /price is asked about a number and /card about the card; a grade asked for
// is the headline; the other finish is on the reply; a played card prices
// its playset; a booster box says whether it is worth opening.
{
  const price = D.priceSummary(Array.from({ length: 60 }, (_, i) => ({ date: new Date(Date.UTC(2026, 6, 1) + i * 86400000).toISOString().slice(0, 10), low_price: 2, market_price: 3 })), "2026-08-29");
  const res = R.resolve("mowgli");
  const base = { R, res, price, graded: [], raw: null, range: "3m", origin: "https://bot.example", inkColors: index.inkColors, playSet: index.playSet, gradedTarget: { cardId: res.printing.id, bucket: "" } };
  const chart = E.cardMessage({ ...base, view: "chart" }).embeds[0].description;
  const card = E.cardMessage({ ...base, view: "card" }).embeds[0].description;
  ok(!/^> /m.test(card) && /strength/.test(card), "/card carries the stats, not the rules text");
  ok(!/Character —|\d cost/.test(card), "/card leaves the ink / cost / type line to the card picture");
  ok(!/^> /m.test(chart) && !/strength/.test(chart), "/price leaves the rules text and stats to /card");
  ok(/Amber/.test(chart) && /\*\*\$2\.00\*\* Low · \$3\.00 NM Market/.test(chart), "/price keeps the card's ink line and its price, Low first");
  // Mowgli's fixture printing has two priced finishes; the other one is quoted at its Low.
  const mf = res.printing.f.find((f, i) => i !== res.fi);
  ok(new RegExp(`\\bFoil \\*\\*\\$${(mf[4] ?? mf[5]).toFixed(2).replace(".", "\\.")}\\*\\*`).test(chart), `the other finish's Low is on the reply (${chart.split("\n").pop()})`);
  // /card shows the site's tile, which carries the prices: they are not repeated in text.
  const withTile = E.cardMessage({ ...base, view: "card", priceDate: "2026-08-29" });
  if (withTile.embeds[0].image && /\/tile\//.test(withTile.embeds[0].image.url)) {
    const td = withTile.embeds[0].description;
    ok(!/NM Market|\bLow\b|1D |playset|Foil \*\*/.test(td), `/card with a tile leaves the prices to the tile (${td.split("\n").slice(-2).join(" | ")})`);
  } else ok(false, "the fixture's Mowgli has a drawn tile");
  const foilRes = { ...res, fi: res.printing.f.findIndex((f) => f[0] !== "N") };
  const foil = E.cardMessage({ ...base, res: foilRes, view: "chart" }).embeds[0].description;
  const nfFin = res.printing.f[res.fi];
  ok(new RegExp(`Non-foil \\*\\*\\$${(nfFin[4] ?? nfFin[5]).toFixed(2).replace(".", "\\.")}\\*\\*`).test(foil), "…and the non-foil's on the foil's reply");
  ok(/playset \$8\.00/.test(chart), `a played base-rarity card prices its playset at Low (${chart.split("\n").find((l) => /NM Market/.test(l))})`);
  const chase = R.resolve("enchanted elsa");
  const chaseTxt = E.cardMessage({ ...base, res: chase, view: "chart", gradedTarget: { cardId: chase.printing.id, bucket: "" } }).embeds[0].description;
  ok(!/playset/.test(chaseTxt), "a chase card gets no playset price");

  // A grade asked for leads, with its date; raw follows plain; the tier is not
  // repeated as a field; the change line (a judgement on the raw price) is off.
  const tiers = [
    { grader: "PSA", grade: "10", last_sold_price: 3000, avg_last_5: 3095, sale_count: 1056, last_sold_date: "2026-09-12", printing: "" },
    { grader: "PSA", grade: "9", last_sold_price: 799, avg_last_5: 905, sale_count: 330, last_sold_date: "2026-09-01", printing: "" },
  ];
  const g = E.cardMessage({ ...base, res: chase, view: "graded", grade: { grader: "PSA", grade: "10" }, graded: tiers, gradedTarget: { cardId: chase.printing.id, bucket: "" } });
  const gd = g.embeds[0].description;
  ok(/\*\*\$3,000\*\* last PSA 10 sale \(Sep 12\) · avg of last 5 \$3,095/.test(gd), `a graded ask leads with that grade's last sale (${gd.split("\n").find((l) => /last PSA/.test(l))})`);
  ok(gd.indexOf("last PSA 10 sale") < gd.indexOf("NM Market") && /^Raw: \$2\.00 Low · \$3\.00 NM Market/m.test(gd), "the raw price follows, plain");
  ok(/1,056 PSA 10 sales on record/.test(gd), "sale counts carry a thousands separator");
  ok(!/1D /.test(gd), "no raw change line under a graded headline");
  ok(g.embeds[0].fields.length === 1 && g.embeds[0].fields[0].name === "PSA 9", "the headline tier is not repeated as a field");
  ok(/Sep 1$/m.test(g.embeds[0].fields[0].value.split("\n")[0]), `a graded tier says when it last sold (${g.embeds[0].fields[0].value.split("\n")[0]})`);
  // The same tiers with no grade asked: all fields, raw leads as before.
  const plain = E.cardMessage({ ...base, res: chase, view: "chart", graded: tiers, gradedTarget: { cardId: chase.printing.id, bucket: "" } });
  ok(plain.embeds[0].fields.length === 2 && /^\*\*\$2\.00\*\* Low/m.test(plain.embeds[0].description), "with no grade asked, the raw price leads and every tier is a field");
  checkMessage(g, "graded-led card");

  // A booster box: box EV, and the way to open one or see its set.
  const box = R.resolve("azurite sea box");
  const sm = E.sealedMessage({ R, res: box, price, view: "chart", range: "3m", origin: "https://bot.example", today: "2026-09-30" });
  const sd = sm.embeds[0].description;
  ok(/Box EV \*\*\$[\d,.]+\*\* at Low — the cards inside are worth about \*\*\d+%\*\* of the box/.test(sd), `a box reply carries the set's box EV (${sd.split("\n").pop()})`);
  const labels = sm.components.flatMap((r) => r.components).map((c) => c.label);
  ok(labels.includes("Open a box") && labels.includes("Set at a glance"), `a box reply offers Open a box + Set at a glance (${labels.join(", ")})`);
  const stBtn = sm.components.flatMap((r) => r.components).find((c) => c.label === "Set at a glance");
  eq(E.parseSetId(stBtn.custom_id) && E.parseSetId(stBtn.custom_id).si, box.item.s, "Set at a glance round-trips to the box's set");
  eq(E.parsePackId(sm.components.flatMap((r) => r.components).find((c) => c.label === "Open a box").custom_id).n, 24, "Open a box opens 24 packs of that set");
  checkMessage(sm, "box with EV");
  // A set not out yet can't be opened; a non-box product carries no EV.
  const hcBox = index.sealed.find((s) => s.ty === "Booster Boxes" && index.sets[s.s] && index.sets[s.s].rel && index.sets[s.s].rel.lgs > "2026-09-30");
  if (hcBox) {
    const um = E.sealedMessage({ R, res: { kind: "sealed", item: hcBox, alts: [] }, price: null, view: "chart", range: "3m", origin: "https://bot.example", today: "2026-09-30" });
    const ul = um.components.flatMap((r) => r.components).map((c) => c.label);
    ok(!ul.includes("Open a box") && ul.includes("Set at a glance"), `an unreleased set's box can't be opened yet (${ul.join(", ")})`);
    ok(!/Box EV/.test(um.embeds[0].description), "an unreleased set's box shows no EV (its prices are pre-sale)");
  }
  const trove = index.sealed.find((s) => s.ty !== "Booster Boxes" && s.ty !== "Booster Packs" && s.s === box.item.s);
  if (trove) {
    const tm = E.sealedMessage({ R, res: { kind: "sealed", item: trove, alts: [] }, price: null, view: "chart", range: "3m", origin: "https://bot.example", today: "2026-09-30" });
    ok(!/Box EV/.test(tm.embeds[0].description) && !tm.components.flatMap((r) => r.components).some((c) => /^Open a/.test(c.label)), `a ${trove.ty} reply carries no box EV and no opener`);
  }
  // No match, nothing to suggest: the reply says how to ask.
  const nf = E.notFoundMessage(R, R.resolve("asdfgh"), "asdfgh", { help: "5234567890123" });
  ok(/<\/help:5234567890123>/.test(nf.embeds[0].description), "a dead-end no-match points at /help");
  const helpTxt = JSON.stringify(E.helpMessage());
  ok(/the card: picture, text, stats/.test(helpTxt) && /price chart, recent changes/.test(helpTxt), "help tells /card and /price apart");
}

// ── commands ─────────────────────────────────────────────────────────────
{
  const { COMMANDS } = await mod("discord/tools/commands.js");
  for (const c of COMMANDS) {
    if (c.type === 1) ok(/^[a-z0-9_-]{1,32}$/.test(c.name) && c.description.length >= 1 && c.description.length <= 100, `command /${c.name} name + description valid`);
    else ok(c.name.length <= 32 && !c.description, `context command ${c.name} valid`);
    const walk = (opts, where) => {
      ok((opts || []).length <= 25, `${where}: ≤25 options`);
      let optional = false;
      for (const o of opts || []) {
        ok(/^[a-z0-9_-]{1,32}$/.test(o.name) && o.description && o.description.length <= 100, `${where} option ${o.name} valid`);
        if (o.type !== 1) { if (o.required && optional) ok(false, `${where}: required option ${o.name} after an optional one`); if (!o.required) optional = true; }
        ok(!o.choices || (o.choices.length <= 25 && o.choices.every((ch) => ch.name.length <= 100)), `${where} option ${o.name} choices valid`);
        ok(!(o.choices && o.autocomplete), `${where} option ${o.name}: choices and autocomplete are exclusive`);
        if (o.options) walk(o.options, `${where} ${o.name}`);
      }
    };
    walk(c.options, c.name);
  }
}

// ── Kaylee (joke command): every pack she opens holds an Enchanted ───────
{
  const K = await mod("discord/src/kaylee.js");
  const st = K.kayleeStats();
  ok(/100\*\* packs opened/.test(st.embeds[0].description) && /12\*\* Enchanteds/.test(st.embeds[0].description), "kaylee stats: 100 packs, 12 enchanteds");
  ok(st.components[0].components[0].custom_id === K.KAYLEE_ID && K.isKayleeId(K.KAYLEE_ID), "kaylee button id round-trips");
  let bad = 0, empty = 0;
  for (let i = 0; i < 200; i++) {
    const m = K.kayleePack(R, index, "https://example.test");
    if (!m.embeds || !m.embeds.length) { empty++; continue; }
    if (!/Enchanted!/.test(m.embeds[0].description)) bad++;
    if (!/Kaylee opened/.test(m.embeds[0].title)) bad++;
    const ids = m.components.flatMap((r) => r.components).filter((c) => c.type === 2 && c.custom_id).map((c) => c.custom_id);
    if (ids.some((id) => id !== K.KAYLEE_ID)) bad++;
  }
  const named = K.kayleePack(R, index, "https://example.test", "Zaven *x*");
  ok(named.content === "Zaven \\*x\\* opened Kaylee's pack:", "kaylee pack names (and escapes) whoever pressed the button");
  ok(empty === 0 && bad === 0, `200 kaylee packs: all Enchanted, all hers (${empty} empty, ${bad} bad)`);
}

// ── 6. signatures ────────────────────────────────────────────────────────
{
  const { verifyDiscordRequest } = await mod("discord/src/verify.js");
  const kp = await webcrypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
  const pubHex = Buffer.from(await webcrypto.subtle.exportKey("raw", kp.publicKey)).toString("hex");
  const now = Date.now();
  const make = async (body, ts, tamper) => {
    const sig = Buffer.from(await webcrypto.subtle.sign("Ed25519", kp.privateKey, new TextEncoder().encode(ts + body))).toString("hex");
    return new Request("https://bot.example/interactions", { method: "POST", body: tamper ? body + " " : body,
      headers: { "x-signature-ed25519": sig, "x-signature-timestamp": ts } });
  };
  const ts = String(Math.floor(now / 1000));
  eq((await verifyDiscordRequest(await make('{"type":1}', ts), pubHex, now)).ok, true, "a correctly signed request verifies");
  eq((await verifyDiscordRequest(await make('{"type":1}', ts, true), pubHex, now)).ok, false, "a tampered body is refused");
  eq((await verifyDiscordRequest(await make('{"type":1}', String(Math.floor(now / 1000) - 3600)), pubHex, now)).ok, false, "an hour-old timestamp is refused");
  eq((await verifyDiscordRequest(new Request("https://x/", { method: "POST", body: "{}" }), pubHex, now)).ok, false, "an unsigned request is refused");
}

// ── interactions, end to end with a fake Discord + database ─────────────
{
  const { handleInteraction } = await mod("discord/src/interactions.js");
  const patches = [];
  const pending = [];
  const dbCalls = [];
  // A reply that uploads a picture is multipart; its JSON is payload_json.
  const bodyOf = (init) => (init.body instanceof FormData ? JSON.parse(init.body.get("payload_json")) : JSON.parse(init.body));
  const fakeDb = {
    hasService: false,
    async get(table, params) {
      if (table === "card_prices_latest") return [{ price_date: "2026-09-27" }];
      if (table === "graded_sales_rollup") return [];
      if (table === "raw_sales_rollup") return [];
      return [];
    },
    async all(table, params) {
      dbCalls.push({ table, params });
      if (table === "tournament_results_v") return [
        { tournament_id: "t1", tournament_name: "Live Event", event_date: "2026-09-26", tournament_format: "core", num_players: 64, place: "1st", place_rank: 1, player_name: "A", deck_id: "d1", deck_inks: ["Amber", "Emerald"], deck_visibility: "public" },
        { tournament_id: "t1", tournament_name: "Live Event", event_date: "2026-09-26", tournament_format: "core", num_players: 64, place: "2nd", place_rank: 2, player_name: "B", deck_id: "d2", deck_inks: ["Amber", "Amethyst"], deck_visibility: "public" },
      ];
      if (table === "prices_daily") return Array.from({ length: 60 }, (_, i) => ({ date: new Date(Date.UTC(2026, 6, 1) + i * 86400000).toISOString().slice(0, 10), low_price: 2, market_price: 3 + i / 100 }));
      return [];
    },
    async rpc() { return []; },
  };
  const deps = {
    R, index, db: fakeDb, origin: "https://bot.example", appId: "123",
    fetch: async (url, init) => { patches.push({ url, body: bodyOf(init), multipart: init.body instanceof FormData }); return new Response("{}"); },
    waitUntil: (p) => pending.push(p), log: () => {},
  };
  eq((await handleInteraction({ type: 1 }, deps)).type, 1, "PING -> PONG");
  const ac = await handleInteraction({ type: 4, data: { name: "price", options: [{ type: 3, name: "name", value: "mogli", focused: true }] } }, deps);
  ok(ac.type === 8 && ac.data.choices.length > 0 && ac.data.choices.length <= 25, "autocomplete answers with 1..25 choices");
  const r = await handleInteraction({ type: 2, token: "tok", application_id: "123", data: { type: 1, name: "price", options: [{ type: 3, name: "name", value: "mowgli" }] } }, deps);
  eq(r.type, 5, "/price defers");
  await Promise.all(pending.splice(0));
  ok(patches.length === 1 && /\/webhooks\/123\/tok\/messages\/@original$/.test(patches[0].url), "/price edits the deferred reply");
  const body = patches[0] && patches[0].body;
  ok(body && body.embeds && body.embeds[0] && /\*\*\$2\.00\*\* Low · \$3\.59 NM Market/.test(body.embeds[0].description), `/price shows the live price (${body && body.embeds[0] && body.embeds[0].description.split("\n").join(" | ")})`);
  ok(body && body.allowed_mentions && Array.isArray(body.allowed_mentions.parse) && !body.allowed_mentions.parse.length, "replies never ping anyone");
  checkMessage(body, "live /price");

  // a range button edits the same message with the new range
  patches.length = 0;
  dbCalls.length = 0;
  const key = R.cardKey(R.resolve("mowgli").printing, 0);
  const b = await handleInteraction({ type: 3, token: "t3", application_id: "123", data: { custom_id: E.rangeId("1y", "chart", key), component_type: 2 } }, deps);
  eq(b.type, 6, "a button defers an UPDATE, not a new message");
  await Promise.all(pending.splice(0));
  // The chart is drawn here and uploaded, so the range shows up as the window
  // of the history read that drew it, not in a URL.
  const yearAgo = Date.now() - 365 * 86400000;
  ok(patches[0] && patches[0].multipart && /^attachment:\/\/.+\.png$/.test(patches[0].body.embeds[0].image.url), "the 1Y button uploads the redrawn chart");
  ok(dbCalls.some((c) => c.table === "prices_daily" && /^gte\./.test(String(c.params.date)) && Math.abs(Date.parse(c.params.date.slice(4) + "T00:00:00Z") - yearAgo) < 2 * 86400000),
    "the 1Y button redraws the chart over one year of history");

  // "Look at a card" opens a NEW private reply, leaving the list where it is
  const look = await handleInteraction({ type: 3, token: "t13", application_id: "123", data: { custom_id: E.openId("card"), component_type: 3, values: [key] } }, deps);
  ok(look.type === 5 && look.data && look.data.flags === 64, "a card picked from a list opens as a new private reply");
  await Promise.all(pending.splice(0));
  // /set, /open and the pack buttons answer from the index, at once
  const sr = await handleInteraction({ type: 2, token: "t15", application_id: "123", data: { type: 1, name: "set", options: [{ type: 3, name: "set", value: "azurite" }] } }, deps);
  ok(sr.type === 4 && /Azurite Sea/.test(sr.data.embeds[0].title), "/set azurite answers at once");
  const op = await handleInteraction({ type: 2, token: "t16", application_id: "123", member: { user: { username: "sim" } }, data: { type: 1, name: "open", options: [{ type: 3, name: "set", value: "azurite" }] } }, deps);
  ok(op.type === 4 && /opened an Azurite Sea booster pack/.test(op.data.embeds[0].title), `/open answers at once (${op.data.embeds[0].title})`);
  const again = op.data.components[1].components.find((c) => c.label === "Open another pack");
  const op2 = await handleInteraction({ type: 3, token: "t17", application_id: "123", message: { flags: 64 }, data: { custom_id: again.custom_id, component_type: 2 } }, deps);
  ok(op2.type === 4 && op2.data.flags === 64, "Open another pack posts a new message, private when the first one was");
  // A booster box's price reply: "Set at a glance" answers from the index at
  // once, as a new message; "Open a box" opens 24 packs of THAT set.
  patches.length = 0;
  const bx = await handleInteraction({ type: 2, token: "t18", application_id: "123", data: { type: 1, name: "price", options: [{ type: 3, name: "name", value: "azurite sea box" }] } }, deps);
  eq(bx.type, 5, "/price of a box defers");
  await Promise.all(pending.splice(0));
  const boxRow = patches[0] && patches[0].body.components.flatMap((r) => r.components);
  const stBtn = boxRow && boxRow.find((c) => c.label === "Set at a glance");
  const obBtn = boxRow && boxRow.find((c) => c.label === "Open a box");
  ok(stBtn && obBtn, "a box reply carries Set at a glance + Open a box");
  const st = stBtn && await handleInteraction({ type: 3, token: "t19", application_id: "123", message: { flags: 0 }, data: { custom_id: stBtn.custom_id, component_type: 2 } }, deps);
  ok(st && st.type === 4 && /Azurite Sea/.test(st.data.embeds[0].title) && !st.data.flags, `Set at a glance answers at once with the set (${st && st.data.embeds[0].title})`);
  const ob = obBtn && await handleInteraction({ type: 3, token: "t19b", application_id: "123", message: { flags: 0 }, data: { custom_id: obBtn.custom_id, component_type: 2 } }, deps);
  ok(ob && ob.type === 4 && /opened an Azurite Sea booster box/i.test(ob.data.embeds[0].title), `Open a box opens a box of that set (${ob && ob.data.embeds[0].title})`);
  // /new asks the database for cards added since the index was built, so it
  // defers; if that read fails the reply still comes, from the index alone.
  patches.length = 0;
  const nw = await handleInteraction({ type: 2, token: "t20", application_id: "123", data: { type: 1, name: "new", options: [{ type: 5, name: "private", value: true }] } }, deps);
  ok(nw.type === 5 && nw.data.flags === 64, "/new defers, privately when asked");
  await Promise.all(pending.splice(0));
  ok(patches[0] && patches[0].body.embeds && patches[0].body.embeds[0].title, `/new edits in the reel (${patches[0] && patches[0].body.embeds && patches[0].body.embeds[0].title})`);
  patches.length = 0;
  const dbDown = { ...deps, db: { ...fakeDb, async get() { throw new Error("database down"); } } };
  await handleInteraction({ type: 2, token: "t21", application_id: "123", data: { type: 1, name: "new", options: [] } }, dbDown);
  await Promise.all(pending.splice(0));
  ok(patches[0] && patches[0].body.embeds && patches[0].body.embeds[0].title && !patches[0].body.content,
    "/new with the database down still answers, from the index");
  const ac2 = await handleInteraction({ type: 4, data: { name: "set", options: [{ type: 3, name: "set", value: "azur", focused: true }] } }, deps);
  ok(ac2.type === 8 && ac2.data.choices[0] && ac2.data.choices[0].value === "Azurite Sea", "a set option autocompletes set names");
  // /help's examples are private
  const ht = await handleInteraction({ type: 3, token: "t18", application_id: "123", data: { custom_id: E.helpTryId("set"), component_type: 2 } }, deps);
  ok(ht.type === 4 && ht.data.flags === 64 && /Example/.test(ht.data.content), "help's A set at a glance answers privately, saying it's an example");
  // Discord refusing a reply's shape (400) gets the same thing as plain text
  {
    const sent = [];
    // Discord refuses every shape that carries embeds (the upload, then the
    // same reply with the chart as a link); the plain text still arrives.
    const d400 = { ...deps, fetch: async (url, init) => { const bd = bodyOf(init); sent.push(bd); return new Response("{}", { status: bd.embeds && bd.embeds.length ? 400 : 200 }); } };
    await handleInteraction({ type: 2, token: "t19", application_id: "123", data: { type: 1, name: "price", options: [{ type: 3, name: "name", value: "mowgli" }] } }, d400);
    await Promise.all(pending.splice(0));
    const last = sent[sent.length - 1];
    ok(sent.length === 3 && last.content && !last.embeds.length && /Mowgli/.test(last.content), "a reply Discord refuses is re-sent as plain text");
  }
  // A rate limit, an outage or a dropped connection gets ONE more try; without
  // it the asker is left on "thinking…". Discord's own verdicts are not retried.
  {
    const runWith = async (token, fetchImpl) => {
      const waits = [];
      const d = { ...deps, fetch: fetchImpl, sleep: async (ms) => { waits.push(ms); } };
      await handleInteraction({ type: 2, token, application_id: "123", data: { type: 1, name: "set", options: [] } }, d);
      await handleInteraction({ type: 2, token, application_id: "123", data: { type: 1, name: "meta", options: [] } }, d);
      await Promise.all(pending.splice(0));
      return waits;
    };
    let n = 0;
    let waits = await runWith("t30", async () => (++n === 1
      ? new Response(JSON.stringify({ retry_after: 0.4 }), { status: 429 })
      : new Response("{}", { status: 200 })));
    ok(n === 2 && waits.length === 1 && waits[0] === 400, `a 429 is retried once, after Discord's retry_after (${n} sends, waited ${waits})`);
    n = 0;
    waits = await runWith("t31", async () => (++n === 1
      ? new Response(JSON.stringify({ retry_after: 600 }), { status: 429 })
      : new Response("{}", { status: 200 })));
    ok(waits[0] <= 2500, `a long retry_after is capped so the Worker is not held open (${waits[0]})`);
    n = 0;
    await runWith("t32", async () => { if (++n === 1) throw new Error("socket closed"); return new Response("{}", { status: 200 }); });
    ok(n === 2, `a thrown fetch is caught and retried, not left unhandled (${n})`);
    n = 0;
    waits = await runWith("t33", async () => { n++; return new Response("{}", { status: 403 }); });
    ok(waits.length === 0, "a 403 is Discord's answer and is not retried");
    n = 0;
    await runWith("t34", async () => { n++; return new Response("{}", { status: 503 }); });
    ok(n <= 4, `an outage that outlasts the retry stops instead of looping (${n} sends)`);
  }

  // /meta reads the top cuts once and leads with the ink pairs
  patches.length = 0;
  dbCalls.length = 0;
  const mr = await handleInteraction({ type: 2, token: "t22", application_id: "123", data: { type: 1, name: "meta", options: [] } }, deps);
  eq(mr.type, 5, "/meta defers");
  await Promise.all(pending.splice(0));
  const mread = dbCalls.find((c) => c.table === "tournament_results_v");
  ok(mread && mread.params.place_rank === "lte.8" && /^gte\.\d{4}-\d\d-\d\d$/.test(mread.params.event_date), "/meta reads every top-8 deck in its window, in one read");
  ok(patches[0] && patches[0].body.embeds && /ink pairs/.test(patches[0].body.embeds[0].title), "/meta leads with the ink-pair breakdown");
  checkMessage(patches[0].body, "live /meta");

  // /reports send: the stored report, posted where it was asked for
  {
    const stored = { cadence: "weekly", price_date: "2026-09-28", embeds: [
      { title: "Weekly movers", description: "x", image: { url: "https://umwqowkiatjjltologrd.supabase.co/storage/v1/object/public/discord-reports/weekly/2026-09-28/market.png" } },
      { author: { name: "CHASE" }, description: "y", thumbnail: { url: "https://tcgplayer-cdn.tcgplayer.com/product/1_in_1000x1000.jpg" }, footer: { text: "packs.ink · " + E.AFFILIATE_NOTE } }] };
    const asked = [];
    const svcDb = { ...fakeDb, hasService: true, async getService(table, params) { asked.push({ table, params }); return table === "discord_report_latest" && params.cadence === "eq.weekly" ? [stored] : []; } };
    const sendDeps = { ...deps, db: svcDb, fetch: async (url, init) => {
      if (/supabase\.co\/storage/.test(String(url))) return new Response(new Uint8Array([137, 80, 78, 71]), { status: 200 });
      patches.push({ url, body: bodyOf(init), multipart: init.body instanceof FormData, form: init.body instanceof FormData ? init.body : null });
      return new Response("{}");
    } };
    const manager = { guild_id: "1", channel_id: "2", member: { permissions: String(1 << 5), user: { id: "9" } } };
    patches.length = 0;
    const sr1 = await handleInteraction({ type: 2, token: "t23", application_id: "123", ...manager,
      data: { type: 1, name: "reports", options: [{ type: 1, name: "send", options: [{ type: 3, name: "report", value: "weekly" }] }] } }, sendDeps);
    ok(sr1.type === 5 && !(sr1.data && sr1.data.flags), "/reports send defers a PUBLIC reply — the report is the post");
    await Promise.all(pending.splice(0));
    ok(asked[0] && asked[0].table === "discord_report_latest" && asked[0].params.cadence === "eq.weekly", "/reports send reads the stored weekly report");
    const sp = patches[0];
    ok(sp && sp.multipart && sp.body.embeds[0].image.url === "attachment://packs-ink-0.png", "/reports send uploads the stored picture with the reply");
    ok(sp && sp.body.embeds[1].thumbnail.url.startsWith("https://tcgplayer-cdn"), "a TCGplayer thumbnail stays a link");
    checkMessage(sp.body, "live /reports send");
    patches.length = 0;
    await handleInteraction({ type: 2, token: "t24", application_id: "123", ...manager,
      data: { type: 1, name: "reports", options: [{ type: 1, name: "send", options: [] }] } }, sendDeps);
    await Promise.all(pending.splice(0));
    ok(patches[0] && /no daily report yet/.test(patches[0].body.content), "/reports send with nothing stored says when one will be");
    const missing = { ...sendDeps, db: { ...svcDb, async getService() { const e = new Error("gone"); e.status = 404; e.code = "PGRST205"; throw e; } } };
    patches.length = 0;
    await handleInteraction({ type: 2, token: "t25", application_id: "123", ...manager,
      data: { type: 1, name: "reports", options: [{ type: 1, name: "send", options: [] }] } }, missing);
    await Promise.all(pending.splice(0));
    ok(patches[0] && /isn't switched on/.test(patches[0].body.content), "/reports send before migration 175 says it isn't switched on");
    const nope = await handleInteraction({ type: 2, token: "t26", application_id: "123", guild_id: "1", channel_id: "2", member: { permissions: "0", user: { id: "9" } },
      data: { type: 1, name: "reports", options: [{ type: 1, name: "send", options: [] }] } }, sendDeps);
    ok(nope.type === 4 && nope.data.flags === 64 && /manage this server/.test(nope.data.content), "/reports send refuses a non-manager privately, at once");
    const retired = await handleInteraction({ type: 2, token: "t27", application_id: "123", data: { type: 1, name: "trade", options: [] } }, deps);
    ok(retired.type === 4 && /Unknown command/.test(retired.data.content), "a retired command answers, rather than hanging");
  }

  // reports refuses someone who can't manage the server
  patches.length = 0;
  await handleInteraction({ type: 2, token: "t4", application_id: "123", guild_id: "1", channel_id: "2", member: { permissions: "0", user: { id: "9" } },
    data: { type: 1, name: "reports", options: [{ type: 1, name: "daily", options: [] }] } }, deps);
  await Promise.all(pending.splice(0));
  ok(patches[0] && /manage this server/.test(patches[0].body.content), "/reports refuses a member without Manage Server");
}

// ── 9. our own pictures go WITH the reply, uploaded — not linked ─────────
// Discord dropped the site tile from the FIRST edit of a deferred /card reply
// (2026-09-29, Broken Pod) and showed it on every later edit. A picture that is
// one of the Worker's own files is therefore read from the asset store and
// uploaded with the edit. Silent both ways: a link that should have been an
// upload is a card with no picture, and an upload that is refused must still
// leave the person a reply.
{
  const I = await mod("discord/src/interactions.js");
  const E = await mod("discord/src/embeds.js");
  const { tileFile } = await mod("discord/src/tile.js");
  const O = "https://bot.example";

  eq(I.ownFilePath(O + "/tile/crd_abc-n.webp?d=2026-09-29", O), "/tile/crd_abc-n.webp", "a tile URL is one of our files");
  eq(I.ownFilePath(O + "/art/crd_abc.webp?v=1a2b3c4d", O), "/art/crd_abc.webp", "baked art is one of our files");
  eq(I.ownFilePath(O + "/chart/p/1/N/3m.png?d=2026-09-29", O), null, "a chart stays a link (drawn on request)");
  eq(I.ownFilePath("https://tcgplayer-cdn.tcgplayer.com/product/1_in_1000x1000.jpg", O), null, "TCGplayer's photo stays a link");
  eq(I.ownFilePath("https://evil.example/tile/x.webp", O), null, "another host's /tile/ is not ours");
  eq(I.ownFilePath(O + "/tile/../x.webp", O), null, "a dot-segment is refused");
  eq(I.ownFilePath(O + "/tile/a/b.webp", O), null, "a nested path is refused");
  eq(String(I.ownChartUrl(O + "/chart/p/1/N/3m.png?d=2026-09-29&r=x", O)), O + "/chart/p/1/N/3m.png?d=2026-09-29&r=x", "a chart URL is ours to draw, query and all");
  eq(I.ownChartUrl(O + "/tile/crd_abc-n.webp", O), null, "a tile is not a chart");
  eq(I.ownChartUrl("https://evil.example/chart/p/1/N/3m.png", O), null, "another host's /chart/ is not ours");

  const withTile = index.cards.flatMap((c) => c.p.filter((p) => p.tl && !p.raw).map((p) => ({ c, p })));
  const pick = withTile.find(({ p }) => p.f.some((f) => f[0] === p.tl[0] && f[1] && !f[6]));
  ok(!!pick, "the fixture has a priced printing with a drawn tile");
  if (pick) {
    const fi = pick.p.f.findIndex((f) => f[0] === pick.p.tl[0]);
    const key = R.cardKey(pick.p, fi);
    const tilePath = "/tile/" + tileFile(pick.p.id, pick.p.tl[0]);
    const nullDb = { hasService: false, async get() { return []; }, async all() { return []; }, async rpc() { return []; } };
    const decode = async (init) => {
      if (init.body instanceof FormData) {
        const files = [];
        for (const [k, v] of init.body.entries()) if (k.startsWith("files[")) files.push({ field: k, name: v.name, type: v.type, size: v.size });
        return { multipart: true, body: JSON.parse(init.body.get("payload_json")), files, ctype: init.headers && init.headers["Content-Type"] };
      }
      return { multipart: false, body: JSON.parse(init.body), files: [] };
    };
    const run = async (it, { status = () => 200, assets } = {}) => {
      const sent = [], pending = [], asked = [];
      const deps = {
        R, index, db: nullDb, origin: O, appId: "123",
        assets: assets === undefined ? { fetch: async (req) => { asked.push(new URL(req.url).pathname); return new Response(new Uint8Array([82, 73, 70, 70]), { headers: { "content-type": "image/webp" } }); } } : assets,
        fetch: async (url, init) => { const d = await decode(init); sent.push({ url, method: init.method, ...d }); return new Response("{}", { status: status(sent.length, d) }); },
        waitUntil: (p) => pending.push(p), log: () => {},
      };
      const r = await I.handleInteraction(it, deps);
      await Promise.all(pending.splice(0));
      return { r, sent, asked };
    };
    const cardCmd = { type: 2, token: "tk", application_id: "123", data: { type: 1, name: "card", options: [{ type: 3, name: "name", value: key }] } };

    // The first reply to /card: the tile goes up with the edit.
    const a = await run(cardCmd);
    eq(a.r.type, 5, "/card defers");
    const s0 = a.sent[0] || {};
    ok(a.sent.length === 1 && s0.multipart && s0.method === "PATCH" && /\/messages\/@original$/.test(s0.url), "/card's first reply is ONE multipart edit of the deferred message");
    ok(!s0.ctype, "a multipart edit leaves Content-Type to the runtime (it carries the boundary)");
    eq(a.asked[0], tilePath, "the Worker reads the tile from its own asset store");
    const e0 = s0.body && s0.body.embeds && s0.body.embeds[0];
    eq(e0 && e0.image && e0.image.url, "attachment://packs-ink-0.webp", "the embed points at the uploaded file, not a URL Discord would have to fetch");
    ok(s0.files && s0.files.length === 1 && s0.files[0].name === "packs-ink-0.webp" && s0.files[0].type === "image/webp" && s0.files[0].size === 4 && s0.files[0].field === "files[0]",
      "the file rides along as files[0], named as the embed references it");
    eq(JSON.stringify(s0.body && s0.body.attachments), JSON.stringify([{ id: 0, filename: "packs-ink-0.webp" }]), "attachments declares exactly the uploaded file");
    ok(s0.body && s0.body.allowed_mentions && !s0.body.allowed_mentions.parse.length, "an upload still never pings anyone");
    ok(s0.body && Array.isArray(s0.body.components) && s0.body.components.length > 0, "an upload keeps the reply's buttons");

    // Switching to the chart uploads the CHART, drawn here by the chart route,
    // and its attachments list names only it, so the tile is dropped.
    const b = await run({ type: 3, token: "tk2", application_id: "123", data: { custom_id: E.rangeId("3m", "chart", key), component_type: 2 } });
    const s1 = b.sent[0] || {};
    ok(b.sent.length === 1 && s1.multipart, "the chart view is one multipart edit");
    eq(s1.body && s1.body.embeds[0].image && s1.body.embeds[0].image.url, "attachment://packs-ink-0.png", "the chart is uploaded, not linked");
    ok(s1.files && s1.files.length === 1 && s1.files[0].type === "image/png" && s1.files[0].size > 1000, "the uploaded chart is a real PNG");
    eq(JSON.stringify(s1.body && s1.body.attachments), JSON.stringify([{ id: 0, filename: "packs-ink-0.png" }]), "the chart edit's attachments name only the chart, which drops the tile");
    ok(!b.asked.length, "the chart is drawn, not read from the asset store");

    // The chart's database read fails: the chart keeps its link, the reply still goes.
    const failDb = { hasService: false, async get() { return []; }, async all() { throw new Error("57014 statement timeout"); }, async rpc() { return []; } };
    const cf = await (async () => {
      const sent = [], pending = [];
      const deps = { R, index, db: failDb, origin: O, appId: "123", assets: null,
        fetch: async (url, init) => { sent.push(await decode(init)); return new Response("{}"); },
        waitUntil: (p) => pending.push(p), log: () => {} };
      await I.handleInteraction({ type: 3, token: "tk4", application_id: "123", data: { custom_id: E.rangeId("3m", "chart", key), component_type: 2 } }, deps);
      await Promise.all(pending.splice(0));
      return sent;
    })();
    ok(cf.length === 1 && !cf[0].multipart && /\/chart\/p\//.test(cf[0].body.embeds[0].image.url), "a chart that can't be drawn here keeps its link, and the reply still goes");

    // Back to the card image: uploaded again.
    const c = await run({ type: 3, token: "tk3", application_id: "123", data: { custom_id: E.rangeId("3m", "card", key), component_type: 2 } });
    ok(c.sent[0] && c.sent[0].multipart && c.sent[0].body.embeds[0].image.url === "attachment://packs-ink-0.webp", "the Card image button uploads the tile again");

    // Discord refuses the upload: the reply goes again as it used to, with the link.
    const d = await run(cardCmd, { status: (n, dd) => (dd.multipart ? 400 : 200) });
    ok(d.sent.length === 2 && d.sent[0].multipart && !d.sent[1].multipart, "a refused upload is retried once without it");
    ok(d.sent[1] && d.sent[1].body.embeds[0].image.url.startsWith(O + tilePath + "?"), "the retry carries the tile as a link, as before uploads existed");
    ok(d.sent[1] && d.sent[1].body.embeds.length === 1 && !d.sent[1].body.content, "the retry is the full card, not the plain-text fallback");

    // Even a non-400 refusal of the upload gets the linked retry.
    const d5 = await run(cardCmd, { status: (n, dd) => (dd.multipart ? 413 : 200) });
    ok(d5.sent.length === 2 && !d5.sent[1].multipart, "an upload refused as too large is retried as a link");

    // Upload refused AND the linked reply refused: the plain-text fallback still comes.
    const f = await run(cardCmd, { status: (n) => (n < 3 ? 400 : 200) });
    ok(f.sent.length === 3 && f.sent[2].body.content && !f.sent[2].body.embeds.length, "when both are refused, the plain-text fallback still answers");

    // The asset store can't produce the file: nothing to upload, the link stands.
    const g = await run(cardCmd, { assets: { fetch: async () => new Response("nope", { status: 404 }) } });
    ok(g.sent.length === 1 && !g.sent[0].multipart && g.sent[0].body.embeds[0].image.url.startsWith(O + tilePath), "a tile missing from the asset store falls back to the link");
    const g2 = await run(cardCmd, { assets: { fetch: async () => { throw new Error("boom"); } } });
    ok(g2.sent.length === 1 && !g2.sent[0].multipart, "an asset store that throws falls back to the link");

    // No binding at all (an older deploy config): exactly the old behaviour.
    const h = await run(cardCmd, { assets: null });
    ok(h.sent.length === 1 && !h.sent[0].multipart && h.sent[0].body.embeds[0].image.url.startsWith(O + tilePath), "without an asset binding the tile is linked, as before");
  }

  // withUploads directly: thumbnails too, several embeds, a cap of ten files.
  const assets = { fetch: async () => new Response(new Uint8Array([1]), { headers: { "content-type": "image/webp" } }) };
  const many = { embeds: Array.from({ length: 12 }, (_, i) => ({ title: "x" + i, image: { url: `${O}/art/c${i}.webp?v=1` } })) };
  const up = await I.withUploads(many, { assets, origin: O });
  eq(up && up.files.length, 10, "at most ten files ride along (Discord's limit)");
  ok(up && up.body.embeds[10].image.url.startsWith(O + "/art/"), "a picture past the tenth stays a link");
  const mixed = await I.withUploads({ embeds: [{ thumbnail: { url: O + "/art/a.webp?v=1" }, image: { url: O + "/chart/p/1/N/3m.png?d=x" } }] }, { assets, origin: O });
  ok(mixed && mixed.body.embeds[0].thumbnail.url === "attachment://packs-ink-0.webp" && /\/chart\//.test(mixed.body.embeds[0].image.url), "without a database, a chart beside an uploaded thumbnail stays a link");
  const rowsDb = { async all() { return Array.from({ length: 30 }, (_, i) => ({ date: new Date(Date.UTC(2026, 7, 1) + i * 864e5).toISOString().slice(0, 10), low_price: 1, market_price: 2 + i / 50 })); }, async get() { return []; } };
  const both = await I.withUploads({ embeds: [{ thumbnail: { url: O + "/art/a.webp?v=1" }, image: { url: O + "/chart/p/1/N/3m.png?d=x" } }] }, { assets, db: rowsDb, origin: O });
  ok(both && both.files.length === 2 && both.body.embeds[0].image.url === "attachment://packs-ink-0.png" && both.files[0].type === "image/png" && both.body.embeds[0].thumbnail.url === "attachment://packs-ink-1.webp", "with a database, the chart is drawn and uploaded beside the thumbnail");
  eq(await I.withUploads({ embeds: [{ image: { url: "https://tcgplayer-cdn.tcgplayer.com/product/1_in_1000x1000.jpg" } }] }, { assets, origin: O }), null, "nothing of ours in the reply → no upload");
  eq(await I.withUploads({ content: "hi" }, { assets, origin: O }), null, "a reply with no embeds uploads nothing");
  ok(many.embeds[0].image.url.startsWith(O), "withUploads never mutates the payload it was handed");
}

console.log(`\n${passes} passed, ${fails} failed`);
process.exit(fails ? 1 : 0);
