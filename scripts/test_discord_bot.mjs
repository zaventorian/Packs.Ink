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
    for (const u of [e.url, e.image && e.image.url, e.thumbnail && e.thumbnail.url]) if (u) ok(/^https?:\/\//.test(u), `${label}: absolute URL ${u}`);
    // Discord shows no AVIF, and a data: URI or a relative path gets the whole
    // reply rejected — so a picture is an https JPEG / PNG / WebP / GIF or nothing.
    for (const u of [e.image && e.image.url, e.thumbnail && e.thumbnail.url]) {
      if (u) ok(DISCORD_IMG.test(u), `${label}: picture is in a format Discord shows (${String(u).slice(0, 90)})`);
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
// A modal Discord would refuse never opens — the command just fails.
function checkModal(m, label) {
  ok(m.custom_id && m.custom_id.length <= 100, `${label}: modal custom_id ≤100`);
  ok(m.title && m.title.length <= 45, `${label}: modal title ≤45`);
  ok(m.components.length >= 1 && m.components.length <= 5, `${label}: 1..5 modal rows`);
  for (const row of m.components) {
    const c = row.components ? row.components[0] : row.component;
    ok(c && c.type === 4 && c.custom_id && c.label && c.label.length <= 45, `${label}: text input with a label ≤45`);
    ok(!c.placeholder || c.placeholder.length <= 100, `${label}: placeholder ≤100`);
    ok(!c.value || c.value.length <= (c.max_length || 4000), `${label}: prefilled value within max_length`);
    ok(!c.max_length || c.max_length <= 4000, `${label}: max_length ≤4000`);
  }
}
const D = await mod("discord/src/data.js");
{
  checkModal(E.deckModal(true), "deck box");
  checkModal((await mod("discord/src/trade.js")).tradeModal(false, "x".repeat(3000), "2x mowgli"), "trade box");
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
    ok(h.includes("**/trade**"), "help: a command with no id is plain bold text, never a broken mention");
    eq(E.cmdMention({ card: "not-an-id" }, "card"), "**/card**", "cmdMention refuses an id that isn't a snowflake");
    for (const w of ["card", "trade", "open", "set", "movers"]) eq(E.parseHelpTryId(E.helpTryId(w)), w, `help "try" id round-trips: ${w}`);
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
  const movers = { latest: "2026-09-27", col: "mkt_pct_7d", todayCol: "market_today", priorCol: "market_7d",
    rows: index.cards.slice(0, 10).map((c) => ({ card_id: c.p[0].id, name: c.c, version: c.v, rarity: c.p[0].r, printing: "Normal", tcgplayer_product_id: c.p[0].f[0][1], market_today: 12, market_7d: 10, mkt_pct_7d: 20 })) };
  for (const win of ["1d", "1w", "6m", "1y"]) for (const dir of ["up", "down"]) {
    checkMessage(E.moversMessage({ result: movers, win, dir, group: "all", basis: "market", min: 5, R }), `movers ${win} ${dir}`);
  }
  checkMessage(E.moversMessage({ result: { latest: "2026-09-27", rows: [] }, win: "1d", dir: "up", group: "chase", basis: "low", min: 5, R }), "movers, nothing cleared");
  {
    const empty = E.moversMessage({ result: { latest: "2026-09-27", rows: [] }, win: "1d", dir: "up", group: "chase", basis: "low", min: 5, R });
    ok(empty.components.length >= 3, "movers: an empty board still has its controls — the way out of an empty board is on it");
    const st = { win: "3m", dir: "down", group: "rareleg", basis: "low", min: 12.5 };
    for (const ctl of ["w", "d", "b", "g"]) {
      const back = E.parseMoversId(E.moversId(ctl, st));
      ok(back && back.win === "3m" && back.dir === "down" && back.group === "rareleg" && back.basis === "low" && back.min === 12.5, `movers id round-trips (${ctl})`);
    }
    eq(E.parseMoversId("m|w|9y|up|all|market|5"), null, "movers id refuses an unknown window");
    // Sealed movers come from the index (the build ran computeSealedDeltas).
    const sm = D.sealedMovers(index, { win: "1y", dir: "up", basis: "market", min: 5, limit: 10 });
    ok(sm.rows.length > 0, `sealed movers: the fixture's sealed products carry moves (${sm.rows.length})`);
    ok(sm.rows.every((r, k) => k === 0 || sm.rows[k - 1].pct >= r.pct), "sealed movers: biggest gain first");
    ok(sm.rows.every((r) => r.pct > 0 && r.prior >= 5), "sealed movers: gains only, each started the window at ≥ $5");
    const smd = D.sealedMovers(index, { win: "1y", dir: "down", basis: "low", min: 0, limit: 10 });
    ok(smd.rows.every((r, k) => r.pct < 0 && (k === 0 || smd.rows[k - 1].pct <= r.pct)), "sealed movers: drops, biggest drop first");
    ok(D.sealedMovers(index, { win: "1y", dir: "up", min: 1e9 }).rows.length === 0, "sealed movers: the price floor applies");
    checkMessage(E.moversMessage({ result: sm, win: "1y", dir: "up", group: "sealed", basis: "market", min: 5, R }), "movers, sealed");
    const sealedMsg = JSON.stringify(E.moversMessage({ result: sm, win: "1y", dir: "up", group: "sealed", basis: "market", min: 5, R }));
    ok(sealedMsg.includes("screener?m=sealed"), "movers, sealed: the Screener link opens its Sealed mode");
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
  // price check: three compact embeds + a select
  const three = R.findInText("mowgli and enchanted elsa and stitch", 3);
  const pc = E.priceCheckMessage({ embeds: three.map((res) => E.compactCardEmbed({ R, res, price, inkColors: index.inkColors, origin: "https://bot.example" })),
    options: three.map((res) => ({ label: res.card.n.slice(0, 100), value: R.cardKey(res.printing, res.fi) })) });
  checkMessage(pc, "price check");
  eq(pc.embeds.filter((e) => e.footer).length, 1, "price check: the disclosure is said once, under the last card");
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

// ── decklists ────────────────────────────────────────────────────────────
{
  const { parseDeckList, looksLikeDeck, priceDeck } = await mod("discord/src/deck.js");
  const list = [
    "Characters (12)", "4 Mowgli - Man Cub", "4x Elsa - Spirit of Winter (1-42)", "2 × Stitch - Rock Star",
    "# a comment", "", "2 Be Prepared", "1 Mowgli - Man Cub", "3 Totally Not A Card",
  ].join("\n");
  const e = parseDeckList(list);
  eq(e.length, 6, "parseDeckList keeps card lines, drops headers, comments and blanks");
  ok(e.some((x) => x.name === "Elsa - Spirit of Winter" && x.qty === 4), "a (set-number) hint and 'x' are stripped");
  ok(looksLikeDeck(list), "a posted decklist is recognised as one");
  ok(!looksLikeDeck("anyone got a mowgli\n4 of them would be nice"), "a chat message is not a decklist");
  const r = priceDeck(R, e);
  const mow = r.rows.find((x) => x.card.c === "Mowgli");
  ok(mow && mow.qty === 5, "the same card on two lines is counted once, 4 + 1");
  eq(r.unmatched.length, 1, "an unknown card is reported, not guessed");
  eq(r.count, 16, "the card count includes what couldn't be priced");
  const want = r.rows.reduce((s2, x) => s2 + (x.mkt != null ? x.mkt * x.qty : 0), 0);
  ok(Math.abs(r.totalMarket - want) < 1e-9 && r.totalMarket > 0, "the total is the sum of qty × cheapest market price");
  for (const x of r.rows) {
    const all = x.card.p.flatMap((p) => p.f.filter((f) => !f[6]).map((f) => f[5])).filter((v) => v != null);
    if (all.length) ok(x.mkt === Math.min(...all), `${x.card.n}: priced at its cheapest printing`);
  }
  checkMessage(E.deckMessage({ result: r, priceDate: "2026-09-27" }), "deck price");

  // Misspelled lines: a full name one letter off, and a bare typo'd name.
  const typo = priceDeck(R, parseDeckList(`2 Be Prepard
4 Mowgli - Man Cub
4x mogli`));
  const bp = typo.rows.find((x) => x.card.n === "Be Prepared");
  ok(bp && bp.guessed && bp.qty === 2, "a full name with a typo in it is priced, marked as a guess");
  const mw = typo.rows.find((x) => x.card.c === "Mowgli");
  ok(mw && mw.qty === 8 && mw.guessed, "a typo'd line merges into the card it means, and the merged row says it holds a guess");
  eq(typo.unmatched.length, 0, "no typo'd line is dropped");

  // Near-miss tier: close to TWO cards means neither; the resolver is capped.
  const { MAX_GUESSES } = await mod("discord/src/deck.js");
  let calls = 0;
  const fakeR = {
    cards: [{ n: "Aaaaa Bbbbb - Cccccc", p: [] }, { n: "Aaaaa Bbbbb - Ccccce", p: [] }],
    resolve: () => { calls++; return { kind: "none" }; },
  };
  const tie = priceDeck(fakeR, parseDeckList("1 Aaaaa Bbbbb - Cccccd"));
  eq(tie.rows.length, 0, "a name one letter from two different cards is not guessed at");
  calls = 0;
  priceDeck(fakeR, parseDeckList(Array.from({ length: 30 }, (_, i) => `1 Nothing ${i}`).join(`
`)));
  eq(calls, MAX_GUESSES, `the slow resolver runs exactly ${MAX_GUESSES} times on a list of 30 unknown lines`);

  // More lines than the embed lists: the tail is summed, never described by a wrong bound.
  const many = { rows: Array.from({ length: 20 }, (_, i) => ({ qty: i % 3 + 1, mkt: 20 - i, low: 19 - i, card: { n: "Card " + i, p: [{ id: "c" + i }] }, mktAt: { p: { id: "c" + i } } })),
    unmatched: [], count: 60, totalMarket: 1, totalLow: 1, unpricedMarket: 0 };
  const mm = E.deckMessage({ result: many, priceDate: "2026-09-27" }).embeds[0].description;
  const restWant = many.rows.slice(15).reduce((s2, x) => s2 + x.mkt * x.qty, 0);
  ok(mm.includes(`worth $${restWant.toFixed(2)} together`), "the rows past the first 15 are summed in one line");
}

// ── 9. trades ────────────────────────────────────────────────────────────
{
  const T = await mod("discord/src/trade.js");
  // Reading a trade post: the markers people actually type.
  const p1 = T.parseTradePost("H: enchanted elsa, 2x tipo W: mickey blt, stitch rock star");
  ok(p1 && /enchanted elsa/.test(p1.has) && /tipo/.test(p1.has) && /mickey blt/.test(p1.wants) && !/mickey/.test(p1.has),
    `a one-line "H: … W: …" post splits into its two sides (${JSON.stringify(p1)})`);
  const p2 = T.parseTradePost("**Have:**\n- mowgli\n- be prepared\n**Want:**\n- enchanted stitch");
  ok(p2 && /mowgli/.test(p2.has) && /stitch/.test(p2.wants), "a multi-line, markdown-bold post is read");
  const p3 = T.parseTradePost("LF enchanted stitch\nFT 4 mowgli, $15");
  ok(p3 && /stitch/.test(p3.wants) && /mowgli/.test(p3.has), "bare LF / FT at the start of a line open a side");
  for (const t of ["I have 2 elsa and want a mowgli", "what do you guys want: mowgli or elsa?", "looking for a game tonight", "", "H: only one side here"]) {
    eq(T.parseTradePost(t), null, `not a trade post: ${JSON.stringify(t)}`);
  }
  // Items: commas split, EXCEPT inside a card name that holds one.
  const R0 = { cards: [{ n: "Fix-It Felix, Jr. - Niceland Steward", p: [] }, { n: "Wake Up, Alice!", p: [] }] };
  const items = T.splitItems(R0, "Fix-It Felix, Jr. - Niceland Steward, 2x Wake Up, Alice!, mowgli + $20; be prepared");
  eq(JSON.stringify(items), JSON.stringify(["Fix-It Felix, Jr. - Niceland Steward", "2x Wake Up, Alice!", "mowgli", "$20", "be prepared"]),
    "splitItems keeps a card name's own comma");
  const pi = (s) => JSON.stringify(T.parseItem(s));
  eq(pi("2x mowgli"), JSON.stringify({ qty: 2, name: "mowgli", whole: "2x mowgli" }), 'parseItem "2x mowgli"');
  eq(T.parseItem("mowgli x3").qty, 3, 'parseItem "mowgli x3"');
  eq(T.parseItem("elsa (2)").qty, 2, 'parseItem "elsa (2)"');
  for (const [s, v] of [["$20", 20], ["20$", 20], ["$12.50 cash", 12.5], ["+ $5", 5], ["30 paypal", 30]]) eq(T.parseItem(s).cash, v, `parseItem cash "${s}"`);
  eq(T.parseItem("20").cash, undefined, "a bare number is not cash");
  ok(T.parseItem("99 puppies").qty > 1, "parseItem alone reads a leading number as a count (capped at 20)…");
  // …which is why pricing checks the whole line as a card name first.
  const pup = index.cards.find((c) => c.n === "99 Puppies");
  if (pup) {
    const t = T.priceTrade(R, "99 Puppies", "mowgli");
    ok(t.give.lines[0] && t.give.lines[0].name === "99 Puppies" && t.give.lines[0].qty === 1, '"99 Puppies" is one card, not 99 of "Puppies"');
  }
  // Pricing: each card at the version the words name.
  const t = T.priceTrade(R, "enchanted elsa, 2x mowgli, $20", "stitch rock star foil, azurite sea box, asdfqwer");
  const ench = t.give.lines.find((l) => /Elsa/.test(l.name));
  ok(ench && ench.printing.r === "Enchanted", "a trade prices enchanted elsa AS the Enchanted");
  const mow = t.give.lines.find((l) => /Mowgli/.test(l.name));
  ok(mow && mow.qty === 2, "a quantity is kept");
  ok(t.give.cash === 20, "cash is added to its side");
  ok(t.get.lines.some((l) => l.kind === "sealed" && /Azurite Sea Booster Box/.test(l.name)), "sealed product is priced in a trade");
  ok(t.get.lines.some((l) => /Stitch/.test(l.name) && l.printing.f[l.fi][0] !== "N"), '"… foil" prices the foil');
  eq(t.get.unmatched.length, 1, "a line matching nothing is reported, not guessed");
  const want = (s) => s.lines.reduce((a, l) => a + (l.mkt != null ? l.mkt * l.qty : 0), 0) + s.cash;
  ok(Math.abs(t.give.totalMkt - want(t.give)) < 1e-9 && Math.abs(t.get.totalMkt - want(t.get)) < 1e-9, "each side's total is qty × price + cash");
  ok(Math.abs(t.diff - (t.get.totalMkt - t.give.totalMkt)) < 1e-9, "the difference is get − give");
  eq(T.verdict(100, 104).even, true, "within 5% is even");
  eq(T.verdict(100, 110).even, false, "10% apart is not");
  // The resolver is capped per trade: a fifty-card post costs a bounded amount.
  let calls = 0;
  const countR = { ...R, resolve: (q) => { calls++; return R.resolve(q); } };
  T.priceTrade(countR, Array.from({ length: 40 }, (_, i) => `nonsense${i}`).join(", "), Array.from({ length: 40 }, (_, i) => `garbage${i}`).join(", "));
  ok(calls <= T.TRADE_MAX_LOOKUPS, `a huge trade runs the resolver at most ${T.TRADE_MAX_LOOKUPS} times (${calls})`);
  // The site's Trade Compare opens it: its own inline ?trade= format.
  const url = T.tradeSiteUrl(R, t, ["You give", "You get"]);
  ok(url && url.startsWith("https://packs.ink/?trade="), "a trade links to the site's Trade Compare");
  const payload = JSON.parse(Buffer.from(url.split("=")[1].replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8"));
  ok(payload.a.some((e) => e[0] === ench.printing.id && e[2] === 1) && payload.a.some((e) => e[0] === mow.printing.id && e[1] === 2),
    `the Trade Compare link carries each card id with its non-foil / foil counts (${JSON.stringify(payload.a)})`);
  ok(!JSON.stringify(payload).includes("Azurite"), "sealed product is left out of the site link (Trade Compare holds cards)");
  // A Challenge Promo (C1) card's key names its printing, the site's tradeGroupKey.
  const c1 = R.sets.findIndex((s) => s.sp);
  const c1card = c1 >= 0 && index.cards.find((c) => c.p.some((p) => p.s === c1));
  if (c1card) {
    const p = c1card.p.find((x) => x.s === c1);
    const fi = p.f.findIndex((f) => f[0] !== "N");
    const u2 = T.tradeSiteUrl(R, { give: { lines: [{ kind: "card", printing: p, fi: Math.max(0, fi), qty: 1 }] }, get: { lines: [] } }, ["a", "b"]);
    const pl2 = JSON.parse(Buffer.from(u2.split("=")[1].replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8"));
    ok(pl2.a[0][0].startsWith(p.id + "::"), `a C1 card's key carries its printing (${pl2.a[0][0]})`);
  }
  for (const mode of ["you", "post"]) checkMessage(T.tradeMessage(t, { mode, priceDate: "2026-09-27", siteUrl: url }), `trade (${mode})`);
  const big = T.priceTrade(R, index.cards.slice(0, 30).map((c) => c.n).join("\n"), index.cards.slice(30, 60).map((c) => "2x " + c.n).join("\n"));
  checkMessage(T.tradeMessage(big, { mode: "you", priceDate: "2026-09-27", siteUrl: T.tradeSiteUrl(R, big, ["a", "b"]) }), "trade, 60 cards");
  const modal = T.tradeModal(true, "2x mowgli", "");
  ok(modal.custom_id === T.TRADE_MODAL_ID(true) && modal.components.length === 2 && modal.components[0].components[0].value === "2x mowgli",
    "the trade box keeps what was typed");
  ok(modal.components.every((r) => r.components[0].label.length <= 45), "trade box labels fit Discord's 45 characters");
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

// ── 10b. the meta, a card's play line, a deck's one cart ─────────────────
{
  const results = [{ id: "t1", name: "Big Event", event_date: "2026-09-12", num_players: 200, top: [
    { place: "1st", place_rank: 1, player_name: "[OSA] Moluk_x", deck_id: "d1", deck_name: null, deck_inks: ["Amber", "Emerald"], deck_visibility: "public", deck_share_token: "tok" },
    { place: "Top 4", place_rank: 4, player_name: "Some*one", deck_id: "d2", deck_name: "Rush", deck_inks: ["Ruby"], deck_visibility: "unlisted", deck_share_token: "abc" }] }];
  const mm = E.metaMessage({ R, index, results });
  checkMessage(mm, "meta");
  const mt = JSON.stringify(mm);
  ok(mt.includes("\\\\[OSA\\\\] Moluk\\\\_x") && mt.includes("Some\\\\*one"), "meta: player names are escaped, not read as markdown");
  ok(mt.includes("decks?deck=d1)") && mt.includes("deck=d2&token=abc"), "meta: a public deck links without its token, an unlisted one with it");
  checkMessage(E.metaMessage({ R, index, results: [] }), "meta, no results");
  const played = index.cards.map((c, i) => ({ c, i })).filter((x) => x.c.pl > 0).sort((a, b) => b.c.pl - a.c.pl)[0];
  if (played) {
    eq(E.playRankOf(R, played.i), 1, "the most-played card ranks #1");
    ok(/#1 most played/.test(E.playLine(R, played.i, index.playDecks || 0) || ""), "its play line says so");
  }
  const cold = index.cards.findIndex((c) => !c.pl);
  if (cold >= 0) eq(E.playLine(R, cold, index.playDecks || 0), null, "a card with no recent top-cut play gets no play line");
  const g = E.gameplayLine({ i: ["Amber", "Steel"], cost: 3, t: "Character", k: ["Storyborn", "Hero"] });
  ok(g.includes("🟨⬜ Amber/Steel") && g.includes("3 cost") && g.includes("Character — Storyborn, Hero"), `gameplay line (${g})`);
  // A deck's one-cart link: TCGplayer's own spelling where it differs.
  const { parseDeckList, priceDeck } = await mod("discord/src/deck.js");
  const dr = priceDeck(R, parseDeckList("4 Mowgli - Man Cub\n2 Be Prepared"));
  const pid = dr.rows.find((x) => x.card.c === "Mowgli").mktAt.f[1];
  const cart = E.deckCartUrl(dr, new Map([[Number(pid), "Mowgli - Man Cub (TCG spelling)"]]));
  const dest = decodeURIComponent(cart.slice(TCG_AFFILIATE.length));
  ok(cart.startsWith(TCG_AFFILIATE) && dest.startsWith("https://www.tcgplayer.com/massentry?productline=Lorcana TCG&c="), "deck: the cart is a TCGplayer mass entry, through the affiliate program");
  ok(decodeURIComponent(dest.split("&c=")[1]).includes("4 Mowgli - Man Cub (TCG spelling)||2 Be Prepared"), `deck: the cart spells cards TCGplayer's way (${dest.slice(0, 160)})`);
  // A long list of long names: every row is an affiliate link, and the list
  // must stop at a whole line rather than clip one.
  const longNames = index.cards.map((c) => c.n).sort((a, b) => b.length - a.length).slice(0, 22);
  const longDeck = priceDeck(R, parseDeckList(longNames.map((n) => `3 ${n}`).join("\n")));
  checkMessage(E.deckMessage({ result: longDeck, priceDate: "2026-09-27", tcgNames: null }), "deck of long names");
  ok(/more card/.test(E.deckMessage({ result: longDeck, priceDate: "2026-09-27", tcgNames: null }).embeds[0].description), "deck of long names: the rows that don't fit are summed");
  const dm = E.deckMessage({ result: dr, priceDate: "2026-09-27", tcgNames: null });
  ok(dm.embeds.length === 2 && /Buy the whole deck/.test(dm.embeds[1].description), "deck: the reply carries the one-cart link");
  checkMessage(dm, "deck with cart");
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
  const fakeDb = {
    hasService: false,
    async get(table, params) {
      if (table === "card_prices_latest") return [{ price_date: "2026-09-27" }];
      if (table === "graded_sales_rollup") return [];
      if (table === "raw_sales_rollup") return [];
      if (table === "price_movers") return [
        { card_id: "a", name: "Fresh", version: "One", rarity: "Rare", printing: "Normal", tcgplayer_product_id: 1, market_today: 20, market_7d: 10, mkt_pct_7d: 100 },
        { card_id: "b", name: "Stale", version: "Two", rarity: "Rare", printing: "Normal", tcgplayer_product_id: 2, market_today: 30, market_7d: 10, mkt_pct_7d: 200 },
      ];
      return [];
    },
    async all(table, params) {
      if (table === "prices_daily" && params.date === "eq.2026-09-27") return [
        { tcgplayer_product_id: 1, printing: "Normal", low_price: 18, market_price: 20 },
        { tcgplayer_product_id: 2, printing: "Normal", low_price: 12, market_price: 14 },   // "today" in the matview is not today
      ];
      if (table === "prices_daily") return Array.from({ length: 60 }, (_, i) => ({ date: new Date(Date.UTC(2026, 6, 1) + i * 86400000).toISOString().slice(0, 10), low_price: 2, market_price: 3 + i / 100 }));
      return [];
    },
    async rpc() { return []; },
  };
  const deps = {
    R, index, db: fakeDb, origin: "https://bot.example", appId: "123",
    fetch: async (url, init) => { patches.push({ url, body: JSON.parse(init.body) }); return new Response("{}"); },
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
  ok(body && body.embeds && body.embeds[0] && /\*\*\$3\.59\*\* NM Market/.test(body.embeds[0].description), `/price shows the live price (${body && body.embeds[0] && body.embeds[0].description.split("\n").join(" | ")})`);
  ok(body && body.allowed_mentions && Array.isArray(body.allowed_mentions.parse) && !body.allowed_mentions.parse.length, "replies never ping anyone");
  checkMessage(body, "live /price");

  // movers: the stale row is dropped
  patches.length = 0;
  await handleInteraction({ type: 2, token: "t2", application_id: "123", data: { type: 1, name: "movers", options: [{ type: 3, name: "window", value: "1w" }] } }, deps);
  await Promise.all(pending.splice(0));
  const mv = patches[0] && patches[0].body.embeds[0].description;
  ok(mv && mv.includes("Fresh") && !mv.includes("Stale"), `/movers drops a row whose "today" is not today (${mv && mv.split("\n").length} rows)`);

  // a range button edits the same message with the new range
  patches.length = 0;
  const key = R.cardKey(R.resolve("mowgli").printing, 0);
  const b = await handleInteraction({ type: 3, token: "t3", application_id: "123", data: { custom_id: E.rangeId("1y", "chart", key), component_type: 2 } }, deps);
  eq(b.type, 6, "a button defers an UPDATE, not a new message");
  await Promise.all(pending.splice(0));
  ok(patches[0] && /\/1y\.png/.test(patches[0].body.embeds[0].image.url), "the 1Y button redraws the chart at 1Y");

  // /deck opens a text box; submitting it prices the list at once
  const md = await handleInteraction({ type: 2, token: "t5", application_id: "123", data: { type: 1, name: "deck", options: [] } }, deps);
  ok(md.type === 9 && md.data.custom_id.length <= 100 && md.data.components[0].components[0].type === 4, "/deck answers with a text box");
  const sub = await handleInteraction({ type: 5, token: "t6", application_id: "123",
    data: { custom_id: md.data.custom_id, components: [{ type: 1, components: [{ type: 4, custom_id: "list", value: "4 Mowgli - Man Cub\n2 Be Prepared" }] }] } }, deps);
  ok(sub.type === 4 && /at NM Market/.test(sub.data.embeds[0].description), "submitting the box prices the deck");
  ok(sub.data.allowed_mentions && !sub.data.allowed_mentions.parse.length, "the deck reply pings nobody");
  const junk = await handleInteraction({ type: 5, token: "t7", application_id: "123",
    data: { custom_id: md.data.custom_id, components: [{ type: 1, components: [{ type: 4, custom_id: "list", value: "hello there" }] }] } }, deps);
  ok(junk.type === 4 && junk.data.flags === 64 && /doesn't look like a decklist/.test(junk.data.content), "a box without a decklist gets a private hint");

  // Price check on a posted decklist totals the deck instead of listing three cards
  patches.length = 0;
  const deckText = ["4 Mowgli - Man Cub", "4 Elsa - Spirit of Winter", "4 Stitch - Rock Star", "4 Be Prepared", "2 Mowgli - Man Cub"].join(`
`);
  const pc = await handleInteraction({ type: 2, token: "t8", application_id: "123",
    data: { type: 3, name: "Price check", target_id: "m1", resolved: { messages: { m1: { id: "m1", content: deckText } } } } }, deps);
  eq(pc.type, 5, "Price check defers");
  await Promise.all(pending.splice(0));
  ok(patches[0] && patches[0].body.embeds && patches[0].body.embeds[0].title === "Deck price", "Price check on a decklist prices the deck");

  // /trade: both sides inline answer at once; one side missing opens the box
  const tr = await handleInteraction({ type: 2, token: "t9", application_id: "123", data: { type: 1, name: "trade", options: [
    { type: 3, name: "give", value: "2x mowgli, $20" }, { type: 3, name: "get", value: "enchanted elsa" }] } }, deps);
  ok(tr.type === 4 && tr.data.embeds[0].fields.length === 2 && tr.data.allowed_mentions, "/trade with both sides answers at once, pinging nobody");
  checkMessage(tr.data, "live /trade");
  const trm = await handleInteraction({ type: 2, token: "t10", application_id: "123", data: { type: 1, name: "trade", options: [{ type: 3, name: "give", value: "2x mowgli" }] } }, deps);
  ok(trm.type === 9 && trm.data.custom_id.startsWith("trade|"), "/trade with a side missing opens the box");
  const trs = await handleInteraction({ type: 5, token: "t11", application_id: "123", data: { custom_id: trm.data.custom_id,
    components: [{ type: 1, components: [{ type: 4, custom_id: "give", value: "2x mowgli" }] }, { type: 1, components: [{ type: 4, custom_id: "get", value: "be prepared" }] }] } }, deps);
  ok(trs.type === 4 && /Mowgli/.test(JSON.stringify(trs.data.embeds[0].fields)), "submitting the trade box prices both sides");
  // Price check on a trade post compares the sides
  patches.length = 0;
  await handleInteraction({ type: 2, token: "t12", application_id: "123",
    data: { type: 3, name: "Price check", target_id: "m2", resolved: { messages: { m2: { id: "m2", content: "H: 2x mowgli, enchanted elsa\nW: stitch rock star, $10" } } } } }, deps);
  await Promise.all(pending.splice(0));
  ok(patches[0] && patches[0].body.embeds[0].title === "Trade check" && /Has/.test(patches[0].body.embeds[0].fields[0].name),
    "Price check on a trade post prices it as a trade (has / wants)");
  // "Look at a card" opens a NEW private reply, leaving the list where it is
  const look = await handleInteraction({ type: 3, token: "t13", application_id: "123", data: { custom_id: E.openId("card"), component_type: 3, values: [key] } }, deps);
  ok(look.type === 5 && look.data && look.data.flags === 64, "a card picked from a list opens as a new private reply");
  await Promise.all(pending.splice(0));
  // movers buttons redraw the board in place
  patches.length = 0;
  const mb = await handleInteraction({ type: 3, token: "t14", application_id: "123",
    data: { custom_id: E.moversId("g", { win: "1w", dir: "up", group: "all", basis: "market", min: 5 }), component_type: 3, values: ["sealed"] } }, deps);
  eq(mb.type, 6, "a movers control updates the board in place");
  await Promise.all(pending.splice(0));
  ok(patches[0] && /Sealed product/.test(patches[0].body.embeds[0].title), "picking Sealed product redraws the board as sealed movers");
  // /set, /open and the pack buttons answer from the index, at once
  const sr = await handleInteraction({ type: 2, token: "t15", application_id: "123", data: { type: 1, name: "set", options: [{ type: 3, name: "set", value: "azurite" }] } }, deps);
  ok(sr.type === 4 && /Azurite Sea/.test(sr.data.embeds[0].title), "/set azurite answers at once");
  const op = await handleInteraction({ type: 2, token: "t16", application_id: "123", member: { user: { username: "sim" } }, data: { type: 1, name: "open", options: [{ type: 3, name: "set", value: "azurite" }] } }, deps);
  ok(op.type === 4 && /opened an Azurite Sea booster pack/.test(op.data.embeds[0].title), `/open answers at once (${op.data.embeds[0].title})`);
  const again = op.data.components[1].components.find((c) => c.label === "Open another pack");
  const op2 = await handleInteraction({ type: 3, token: "t17", application_id: "123", message: { flags: 64 }, data: { custom_id: again.custom_id, component_type: 2 } }, deps);
  ok(op2.type === 4 && op2.data.flags === 64, "Open another pack posts a new message, private when the first one was");
  const ac2 = await handleInteraction({ type: 4, data: { name: "set", options: [{ type: 3, name: "set", value: "azur", focused: true }] } }, deps);
  ok(ac2.type === 8 && ac2.data.choices[0] && ac2.data.choices[0].value === "Azurite Sea", "a set option autocompletes set names");
  // /help's examples are private
  const ht = await handleInteraction({ type: 3, token: "t18", application_id: "123", data: { custom_id: E.helpTryId("trade"), component_type: 2 } }, deps);
  ok(ht.type === 4 && ht.data.flags === 64 && /Example/.test(ht.data.content), "help's Try a trade answers privately, saying it's an example");
  // Discord refusing a reply's shape (400) gets the same thing as plain text
  {
    const sent = [];
    const d400 = { ...deps, fetch: async (url, init) => { sent.push(JSON.parse(init.body)); return new Response("{}", { status: sent.length === 1 ? 400 : 200 }); } };
    await handleInteraction({ type: 2, token: "t19", application_id: "123", data: { type: 1, name: "price", options: [{ type: 3, name: "name", value: "mowgli" }] } }, d400);
    await Promise.all(pending.splice(0));
    ok(sent.length === 2 && sent[1].content && !sent[1].embeds.length && /Mowgli/.test(sent[1].content), "a reply Discord refuses is re-sent as plain text");
  }

  // reports refuses someone who can't manage the server
  patches.length = 0;
  await handleInteraction({ type: 2, token: "t4", application_id: "123", guild_id: "1", channel_id: "2", member: { permissions: "0", user: { id: "9" } },
    data: { type: 1, name: "reports", options: [{ type: 1, name: "daily", options: [] }] } }, deps);
  await Promise.all(pending.splice(0));
  ok(patches[0] && /manage this server/.test(patches[0].body.content), "/reports refuses a member without Manage Server");
}

console.log(`\n${passes} passed, ${fails} failed`);
process.exit(fails ? 1 : 0);
