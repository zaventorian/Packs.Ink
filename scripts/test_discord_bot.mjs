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
  for (const row of rows) {
    ok(row.type === 1 && row.components.length >= 1 && row.components.length <= 5, `${label}: row holds 1..5 components`);
    const selects = row.components.filter((c) => c.type === 3);
    ok(!selects.length || row.components.length === 1, `${label}: a select menu sits alone in its row`);
    for (const c of row.components) {
      if (c.type === 2) {
        ok(!c.label || c.label.length <= 80, `${label}: button label ≤80`);
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
  checkMessage(E.calendarMessage({ events: [{ id: "x", kind: "dlc", title: "DLC Test", subtitle: "Disney Lorcana Challenge", starts_on: "2026-11-20", location: "Somewhere" }] }), "calendar");
  const movers = { latest: "2026-09-27", col: "mkt_pct_7d", todayCol: "market_today", priorCol: "market_7d",
    rows: index.cards.slice(0, 10).map((c) => ({ card_id: c.p[0].id, name: c.c, version: c.v, rarity: c.p[0].r, printing: "Normal", tcgplayer_product_id: c.p[0].f[0][1], market_today: 12, market_7d: 10, mkt_pct_7d: 20 })) };
  checkMessage(E.moversMessage({ result: movers, win: "1w", dir: "up", group: "all", basis: "market", min: 5, R }), "movers");
  checkMessage(E.eventsMessage({ place: { city: "Chicago", state: "IL" }, radius: 50, kind: "all", series: [{ next_start: "2026-10-04T17:00:00Z", store_name: "A Shop", name: "Weekly", kind: "other", distance_mi: 3.2, dow: 6, local_time: "12:00", occurrence_count: 4, occurrences: [{ url: "https://tcg.ravensburgerplay.com/events/1" }] }] }), "events");
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

  // reports refuses someone who can't manage the server
  patches.length = 0;
  await handleInteraction({ type: 2, token: "t4", application_id: "123", guild_id: "1", channel_id: "2", member: { permissions: "0", user: { id: "9" } },
    data: { type: 1, name: "reports", options: [{ type: 1, name: "daily", options: [] }] } }, deps);
  await Promise.all(pending.splice(0));
  ok(patches[0] && /manage this server/.test(patches[0].body.content), "/reports refuses a member without Manage Server");
}

console.log(`\n${passes} passed, ${fails} failed`);
process.exit(fails ? 1 : 0);
