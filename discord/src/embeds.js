// embeds.js — Discord message payloads. Pure: every function takes data that
// has already been fetched and returns {embeds, components} JSON, which is what
// lets the guard test check a reply without a network.
import { tcgUrl, tcgSetSearchUrl, amazonForSealed, calEventTitle, calEventSubtitle, scLocalTime12 } from "./site.generated.js";
import { FIN_PRINTING, RANGES, DEFAULT_RANGE, CAL_FILTERS, META_FALLBACK_DAYS } from "./data.js";
import { tileUrl } from "./tile.js";
import { INK_MARK, inkMarks, statsLineFor } from "./stats.js";
export { INK_MARK, inkMarks };

export const SITE = "https://packs.ink";
// One event on the site's calendar (its detail view: when, where, the map,
// and the organiser's own registration link). The calendar opens any id it
// holds, and fetches an RPH event ("ev:<id>") the reader doesn't follow.
export const eventPageUrl = (id) => (id == null || id === "" ? null
  : `${SITE}/calendar?ce=${encodeURIComponent(String(id))}`);
export const BRAND_COLOR = 0xe3b341;
const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const MONTH_NAMES = ["January","February","March","April","May","June","July","August","September","October","November","December"];

// ── formatting ───────────────────────────────────────────────────────────
export function money(v) {
  if (v == null || !Number.isFinite(Number(v))) return null;
  const n = Number(v);
  if (n >= 1000) return "$" + Math.round(n).toLocaleString("en-US");
  return "$" + n.toFixed(2);
}
// Past +1000% a percentage stops being readable; the price MULTIPLE is what a
// person means ("11x"), same rule as the stream ticker.
export function pct(p) {
  if (p == null || !Number.isFinite(p)) return null;
  if (p >= 1000) return (1 + p / 100).toFixed(p >= 9900 ? 0 : 1).replace(/\.0$/, "") + "x";
  const a = Math.abs(p);
  const s = a >= 100 ? a.toFixed(0) : a >= 10 ? a.toFixed(1) : a.toFixed(1);
  return (p > 0 ? "▲" : p < 0 ? "▼" : "") + s + "%";
}
export const shortDate = (ymd) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(ymd || ""));
  return m ? `${MONTHS[+m[2] - 1]} ${+m[3]}` + (new Date().getUTCFullYear() !== +m[1] ? `, ${m[1]}` : "") : "";
};
const clip = (s, n) => { s = String(s || ""); return s.length <= n ? s : s.slice(0, n - 1) + "…"; };
// "1,056 sales", never "1056 sales".
export const count = (n) => (Number.isFinite(Number(n)) ? Number(n).toLocaleString("en-US") : String(n ?? ""));
const sameTier = (row, g) => !!(row && g && row.grader === g.grader && String(row.grade) === String(g.grade));
const BASE_RARITY = new Set(["Common", "Uncommon", "Rare", "Super Rare", "Legendary"]);
// As many WHOLE lines as fit in `budget` characters, then "…and N more". Any
// text holding links goes through this, never clip(): a line cut mid-way is a
// broken markdown link, which Discord shows as raw brackets and a URL.
export function fitLines(lines, budget, more = (n) => `*…and ${n} more*`) {
  const out = [];
  let used = 0;
  for (const l of lines) {
    if (used + l.length + 1 > budget - 40) break;
    out.push(l);
    used += l.length + 1;
  }
  if (out.length < lines.length) out.push(more(lines.length - out.length));
  return out.join("\n");
}
const hex = (h) => { const n = parseInt(String(h || "").replace("#", ""), 16); return Number.isFinite(n) ? n : BRAND_COLOR; };
export const cardPageUrl = (cardId) => `${SITE}/cards?card=${encodeURIComponent(cardId)}`;

// Card art Discord can actually show, and nothing else: Discord will not
// display AVIF (Lorcast's only format) and REJECTS an embed whose image is a
// data: URI or a relative path — the reply then never arrives. In order: art
// the build baked for this Worker (/art/…, see tools/bake_art.mjs), a JPEG /
// PNG / WebP we host, TCGplayer's photo of the product. Otherwise no picture.
const SAFE_IMG = /^https:\/\/[^?#]+\.(?:jpe?g|png|webp|gif)(?:[?#].*)?$/i;
export function cardImage(printing, origin) {
  const img = printing.img || "";
  if (img.startsWith("/art/")) return origin ? origin + img : null;
  if (SAFE_IMG.test(img)) return img;
  const pid = (printing.f || []).map((f) => f[1]).find(Boolean);
  return pid ? `https://tcgplayer-cdn.tcgplayer.com/product/${pid}_in_1000x1000.jpg` : null;
}

// Every card name links to TCGplayer through the affiliate program: the
// product page when TCGplayer lists this printing, else a TCGplayer search for
// the name, so a card from a set TCGplayer hasn't listed yet still gets one.
export function buyUrl(name, pid, printing) {
  return pid ? tcgUrl(pid, printing) : tcgSetSearchUrl(name);
}
// The disclosure that goes with those links, in every footer that has them.
export const AFFILIATE_NOTE = "Links may earn packs.ink a commission";

// ── keys carried in components ───────────────────────────────────────────
// custom_id "r|<range>|<view>|<grade>|<key>". The key itself contains "|", so
// it is always the LAST field and everything after the fourth bar belongs to
// it. <grade> is "PSA10" / "BGS9.5" on a graded reply, "-" otherwise — a
// button has nowhere else to remember which slab you were looking at.
export const VIEWS = ["chart", "card", "graded"];
const gradeToken = (g) => (g && g.grader && g.grade ? `${g.grader}${g.grade}` : "-");
export function rangeId(range, view, key, grade) { return `r|${range}|${view}|${gradeToken(grade)}|${key}`; }
export function parseRangeId(id) {
  const m = /^r\|([a-z0-9]+)\|([a-z]+)\|([A-Z]{2,4}(?:10|[1-9](?:\.5)?)|-)\|(.+)$/.exec(String(id || ""));
  if (!m || !RANGES[m[1]] || !VIEWS.includes(m[2])) return null;
  const g = m[3] === "-" ? null : /^([A-Z]{2,4})(.+)$/.exec(m[3]);
  return { range: m[1], view: m[2], grade: g ? { grader: g[1], grade: g[2] } : null, key: m[4] };
}
export const pickId = (view, range) => `p|${view}|${range}`;
export function parsePickId(id) {
  const m = /^p\|([a-z]+)\|([a-z0-9]+)$/.exec(String(id || ""));
  if (!m || !VIEWS.includes(m[1]) || !RANGES[m[2]]) return null;
  return { view: m[1], range: m[2] };
}
// A menu that OPENS a card in a new private reply, where pickId replaces the
// message it sits on: a trade, a deck, a set's chase list or a movers board
// must stay where it is when someone looks at one of its cards.
// A second menu in one message needs its own custom_id, so a number may follow.
export const openId = (view, n = 0) => (n ? `o|${view}|${n}` : `o|${view}`);
export function parseOpenId(id) {
  const m = /^o\|([a-z]+)(?:\|\d)?$/.exec(String(id || ""));
  return m && VIEWS.includes(m[1]) ? { view: m[1] } : null;
}
// "Open a pack" / "Open a box": custom_id "k|<set index>|<packs>". A set
// message, a pack message and a booster box's price reply all carry one.
export const packId = (si, n) => `k|${si}|${n}`;
export function parsePackId(id) {
  const m = /^k\|(\d{1,3})\|(1|24)$/.exec(String(id || ""));
  return m ? { si: Number(m[1]), n: Number(m[2]) } : null;
}
// "Set at a glance" from a sealed reply: the /set overview, as a new message.
export const setId = (si) => `st|${si}`;
export function parseSetId(id) {
  const m = /^st\|(\d{1,3})$/.exec(String(id || ""));
  return m ? { si: Number(m[1]) } : null;
}

// ── one card ─────────────────────────────────────────────────────────────
// ctx: { R (resolver), res (resolve() result), price (priceSummary or null),
//        graded (rows for this printing), raw (raw eBay rollup row or null),
//        view, range, origin, chartDate, query, grade {grader, grade},
//        priceDate (the index's — dates the tile URL) }
export function cardMessage(ctx) {
  const { R, res, price, view = "chart", range = DEFAULT_RANGE, origin } = ctx;
  const c = res.card, p = res.printing, f = p.f[res.fi] || p.f[0];
  const set = R.sets[p.s] || {};
  const key = R.cardKey(p, res.fi);
  const fin = R.finishLabel(p, res.fi);
  const noListing = !!(f && f[6]);
  const pid = f && f[1];
  const printingStr = (f && f[2]) || FIN_PRINTING[f && f[0]] || "Normal";
  const lines = [];

  const lead = [];
  if (ctx.query && res.corrected) lead.push(`Closest match for “${clip(ctx.query, 40)}”.`);
  if (res.ambiguous && !res.exact) {
    lead.push(res.basis === "collector"
      ? "Showing the most-traded version — pick another below."
      : "Showing the most-played version — pick another below.");
  }
  for (const n of res.notes || []) lead.push(n);
  if (lead.length) lines.push("*" + lead.join(" ") + "*");

  lines.push([set.n, p.no ? "#" + p.no : null, p.r, p.var, fin && fin !== p.var ? fin : null].filter(Boolean).join(" · "));
  // What a player needs to place the card (its ink, cost, type) and how much
  // it is played — measured from recent tournament top cuts, the same number
  // that decides which version "mowgli" means.
  // /card is the PICTURE (Zaven, 2026-10-04: "people mostly want to see the
  // card, nothing else"): the ink / cost / type line and the rules text are
  // printed on the card itself, so the card view leaves them out and keeps
  // only the stats line. /price keeps the ink line; its rules text was moved
  // to /card on 2026-09-29 and is now in the picture alone.
  if (view !== "card") {
    const ident = gameplayLine(c);
    if (ident) lines.push(`*${ident}*`);
  } else {
    const stats = statsLine(c);
    if (stats) lines.push(stats);
  }
  const play = playLine(R, res.index, ctx.playSet);
  if (play) lines.push(play);

  // The card view shows the site's tile, and the tile already carries Low,
  // Market and the 1D/1W/1M changes — the same numbers printed above it were
  // the reply saying everything twice (Zaven, 2026-10-04). So the price lines
  // are left to the picture there; the chart view keeps them.
  const tile = view === "card" && !ctx.grade && !(ctx.raw && ctx.raw.last_sold_price != null)
    ? tileUrl(p, f && f[0], origin, ctx.priceDate) : null;
  if (!tile) lines.push("");

  const mkt = price ? price.market : (f ? f[5] : null);
  const low = price ? price.low : (f ? f[4] : null);
  // A promo TCGplayer can't price (the raw eBay watchlist) inverts the order,
  // as the site's card page does: eBay's last sale and average lead, and
  // TCGplayer's number — the fossil on exactly these cards — follows, plain.
  const rawLead = !!(ctx.raw && ctx.raw.last_sold_price != null);
  // A grade that was ASKED FOR leads the same way: "elsa psa 10" is a question
  // about the slab, and the answer used to sit fourth, in a grid of six tiers,
  // under the raw price and its changes. cardPayload puts that tier first.
  const gradeLead = ctx.grade && (ctx.graded || [])[0] && sameTier((ctx.graded || [])[0], ctx.grade) ? ctx.graded[0] : null;
  const tcgBits = () => [low != null ? `${money(low)} Low` : null, mkt != null ? `${money(mkt)} NM Market` : null].filter(Boolean);
  if (tile) {
    // nothing: the tile is the price
  } else if (rawLead) {
    const n = ctx.raw.last_5_count || 0;
    lines.push(`**${money(ctx.raw.last_sold_price)}** last sold on eBay (${shortDate(ctx.raw.last_sold_date)})` +
      (ctx.raw.avg_last_5 != null && n > 1 ? ` · avg of last ${n} ${money(ctx.raw.avg_last_5)}` : ""));
    lines.push(`${count(ctx.raw.sale_count)} raw sale${ctx.raw.sale_count === 1 ? "" : "s"} on record`);
    lines.push("TCGplayer: " + (noListing || !tcgBits().length ? "no price" : tcgBits().join(" · ")));
  } else if (gradeLead) {
    const g = gradeLead;
    lines.push(`**${money(g.last_sold_price)}** last ${g.grader} ${g.grade} sale` +
      (g.last_sold_date ? ` (${shortDate(g.last_sold_date)})` : "") +
      (g.avg_last_5 != null && g.sale_count > 1 ? ` · avg of last 5 ${money(g.avg_last_5)}` : ""));
    lines.push(`${count(g.sale_count)} ${g.grader} ${g.grade} sale${g.sale_count === 1 ? "" : "s"} on record · sold on eBay`);
    lines.push("Raw: " + (noListing || !tcgBits().length ? "no TCGplayer price" : tcgBits().join(" · ")));
  } else if (noListing) {
    lines.push("No TCGplayer listing of its own — TCGplayer files it with the regular printing.");
  } else if (mkt != null || low != null) {
    // Low leads, as it does on the site; NM Market follows.
    const lead = low ?? mkt;
    const bits = [];
    if (low != null) bits.push(`**${money(low)}** Low`);
    if (mkt != null) bits.push(low != null ? `${money(mkt)} NM Market` : `**${money(mkt)}** NM Market`);
    // A card that is PLAYED is bought four at a time.
    const playset = play && lead != null && BASE_RARITY.has(p.r) ? money(lead * 4) : null;
    if (playset) bits.push(`playset ${playset}`);
    lines.push(bits.join(" · "));
  } else {
    lines.push("No TCGplayer price yet.");
  }
  // The change line and the "Cheapest in 12 months" note are judgements ON
  // TCGplayer's price, so they are left off where that price isn't the market.
  if (price && !tile && !noListing && !rawLead && !gradeLead) {
    const d = price.low != null ? price.lowDelta : price.mktDelta;
    const ch = [["1d", "1D"], ["1w", "1W"], ["1m", "1M"], ["1y", "1Y"]]
      .map(([k, l]) => (d && d[k] != null ? `${l} ${pct(d[k])}` : null)).filter(Boolean);
    if (ch.length) lines.push(ch.join(" · "));
    if (price.standing) lines.push((price.standing.tone === "high" ? "↗ " : "↘ ") + price.standing.label);
  }
  // The card's OTHER finish, priced, on the same reply: "and the foil?" is the
  // one follow-up every price reply gets, and it cost a menu pick. Prices are
  // the index's (as of its price date), like the versions menu's.
  if (!tile && !rawLead && !gradeLead && !noListing) {
    const others = p.f.map((x, i) => ({ x, i })).filter(({ x, i }) => i !== res.fi && !x[6] && (x[4] ?? x[5]) != null)
      .map(({ x, i }) => `${R.finishLabel(p, i) || FIN_PRINTING[x[0]] || "Other"} **${money(x[4] ?? x[5])}**`);
    if (others.length) lines.push(others.join(" · "));
  }

  const fields = [];
  for (const g of ctx.graded || []) {
    if (g === gradeLead) continue;   // already the headline
    fields.push({
      name: `${g.grader} ${g.grade}`,
      value: [
        `Last **${money(g.last_sold_price)}**` + (g.last_sold_date ? ` · ${shortDate(g.last_sold_date)}` : ""),
        g.avg_last_5 != null ? `Avg 5 ${money(g.avg_last_5)}` : null,
        `${count(g.sale_count)} sale${g.sale_count === 1 ? "" : "s"}`,
      ].filter(Boolean).join("\n"),
      inline: true,
    });
  }

  const img = cardImage(p, origin);
  const buy = buyUrl(c.n, noListing ? null : pid, printingStr);
  const embed = {
    title: clip(c.n + (ctx.grade ? ` — ${ctx.grade.grader} ${ctx.grade.grade}` : ""), 256),
    url: buy,
    color: hex(c.i && c.i[0] && ctx.inkColors ? ctx.inkColors[c.i[0]] : null),
    description: clip(lines.join("\n"), 4000),
    fields: fields.slice(0, 12),
    footer: { text: footerText(ctx, price) },
  };
  const date = ctx.chartDate || (price && price.date) || "";
  const graded = view === "graded" && ctx.grade;
  const rt = rawLead && ctx.rawTarget ? ctx.rawTarget : null;
  const canChart = graded || (pid && !noListing) || !!rt;
  if (view === "card" || !canChart) {
    // The site's own card tile when one was drawn for this finish — the
    // picture the card page shows. Never on a graded reply (the tile carries
    // raw prices) or where eBay sales lead (the tile would lead with the
    // TCGplayer price the reply has just called secondary).
    if (tile || img) embed.image = { url: tile || img };
  } else {
    if (img) embed.thumbnail = { url: img };
    const rawQ = rt ? `r=${encodeURIComponent(rt.cardId)}&rb=${encodeURIComponent(rt.bucket || "")}&` : "";
    embed.image = { url: graded
      ? `${origin}/chart/g/${encodeURIComponent(ctx.gradedTarget.cardId)}/${encodeURIComponent(ctx.grade.grader)}/${encodeURIComponent(ctx.grade.grade)}/${range}.png?b=${encodeURIComponent(ctx.gradedTarget.bucket || "")}&d=${date}`
      : pid && !noListing
        ? `${origin}/chart/p/${pid}/${f[0]}/${range}.png?${rawQ}d=${date}`
        : `${origin}/chart/r/${encodeURIComponent(rt.cardId)}/${range}.png?rb=${encodeURIComponent(rt.bucket || "")}&d=${date}` };
  }

  const components = [];
  const row1 = [];
  if (canChart && view !== "card") {
    for (const r of ["1m", "3m", "1y", "all"]) {
      row1.push(button(RANGES[r].label, rangeId(r, view, key, ctx.grade), r === range ? 1 : 2, r === range));
    }
  }
  if (canChart) {
    row1.push(view === "card"
      ? button("Price chart", rangeId(range, ctx.grade ? "graded" : "chart", key, ctx.grade), 2)
      : button("Card image", rangeId(range, "card", key, ctx.grade), 2));
  }
  if (row1.length) components.push({ type: 1, components: row1 });

  const opts = versionOptions(R, res);
  if (opts.length > 1) {
    components.push({ type: 1, components: [{
      type: 3, custom_id: pickId(view === "card" ? "card" : "chart", range),
      placeholder: "Other printings and versions",
      options: opts.map((o) => ({ ...o, default: o.value === key })),
    }] });
  }
  components.push({ type: 1, components: [
    { type: 2, style: 5, label: pid && !noListing ? "Buy on TCGplayer" : "Find on TCGplayer", url: buy },
    { type: 2, style: 5, label: "packs.ink", url: cardPageUrl(p.id) },
  ] });
  return { embeds: [embed], components };
}

// ── a card's identity and play ───────────────────────────────────────────
// The six inks as Discord's coloured squares: the nearest colour Discord can
// draw inline, and they read at a glance in a list.

export function gameplayLine(c) {
  const bits = [];
  if (c.i && c.i.length) bits.push(`${inkMarks(c.i)} ${c.i.join("/")}`);
  if (c.cost != null) bits.push(`${c.cost} cost`);
  if (c.ik === 0) bits.push("uninkable");
  if (c.t) bits.push(c.t + (c.k && c.k.length ? " — " + c.k.slice(0, 4).join(", ") : ""));
  return bits.join(" · ");
}

// ── the card's own text ──────────────────────────────────────────────────
// Strength / willpower / lore (a Location's move cost instead of strength),
// only what the card has: an action or an item has none of them.
export function statsLine(c) {
  const [str, wil, lore, move] = c.st || [];
  const bits = [];
  if (str != null) bits.push(`**${str}** strength`);
  if (move != null) bits.push(`**${move}** to move`);
  if (wil != null) bits.push(`**${wil}** willpower`);
  if (lore != null) bits.push(`**${lore}** lore`);
  return bits.join(" · ");
}
// The rules text as Discord shows it: one quoted line per ability, the
// ability's NAME bold (the printed ALL-CAPS words), a keyword the card has
// bold with its number ("Shift 4"), reminder text in italics, and the card's
// symbols as words — Discord has no {I} glyph, and a word reads anywhere.
const RULE_SYMBOLS = { I: "ink", E: "exert", L: "lore", S: "strength", W: "willpower", IW: "inkwell" };
const escRule = (s) => String(s).replace(/[\\*_~`|>]/g, "\\$&");
export function rulesText(c) {
  if (!c || !c.x) return "";
  const keywords = (c.w || []).slice().sort((a, b) => b.length - a.length);
  return String(c.x).split(/\r?\n/).map((raw) => {
    let line = escRule(raw.trim()).replace(/\{([A-Z]{1,2})\}/g, (m, k) => RULE_SYMBOLS[k] || m);
    if (!line) return null;
    let head = "";
    // An ability name: the run of all-caps words that opens the line, three
    // capitals at least, so "A character with…" stays plain.
    const caps = /^((?:[A-Z0-9][A-Z0-9'’!?.,&-]*\s+)*[A-Z0-9][A-Z0-9'’!?.,&-]*)(?=\s+[A-Z]?[a-z(]|\s*$)/.exec(line);
    if (caps && (caps[1].match(/[A-Z]/g) || []).length >= 3 && !/[a-z]/.test(caps[1])) {
      head = `**${caps[1]}**`; line = line.slice(caps[1].length);
    } else {
      const kw = keywords.find((k) => line.toLowerCase().startsWith(k.toLowerCase()) && !/[a-z]/i.test(line.charAt(k.length) || ""));
      if (kw) {
        // "Shift 4 {I}": the number, and the ink it is paid in, belong to the keyword.
        const num = /^\s*[+-]?\d+(?:\s+ink\b)?/.exec(line.slice(kw.length));
        const len = kw.length + (num ? num[0].length : 0);
        head = `**${line.slice(0, len)}**`; line = line.slice(len);
      }
    }
    line = line.replace(/\(([^()]*)\)/g, (m, inner) => `*(${inner.trim()})*`);
    // An ability that costs exerting opens with it: "Exert, 1 ink — …".
    line = line.replace(/^(\s*)exert\b/, "$1Exert");
    return "> " + (head + line).trim();
  }).filter(Boolean).join("\n");
}

// How much a card is played in the CURRENT set's meta only (Zaven,
// 2026-10-04): `ps` counts the Core top-cut decks since the newest booster
// set released (index.playSet), and the line names that set. Until the set
// has PLAY_SET_MIN_DECKS decks on record there is no line at all — a share of
// three decks is noise, and the previous set's numbers would be a different
// meta presented as this one.
export const PLAY_SET_MIN_DECKS = 8;
const PLAY_RANK = new WeakMap();
export function playRankOf(R, i) {
  let m = PLAY_RANK.get(R);
  if (!m) {
    m = new Map();
    R.cards.map((c, k) => [k, c.ps || 0]).filter((x) => x[1] > 0).sort((a, b) => b[1] - a[1] || a[0] - b[0])
      .forEach(([k], pos) => m.set(k, pos + 1));
    PLAY_RANK.set(R, m);
  }
  return m.get(i) || null;
}
export function playLine(R, i, playSet) {
  const c = R.cards[i];
  if (!playSet || !playSet.n || !(playSet.decks >= PLAY_SET_MIN_DECKS)) return null;
  const rank = playRankOf(R, i);
  if (!rank || !(c.ps > 0)) return null;
  const share = c.ps / playSet.decks;
  if (share < 0.02 && rank > 100) return null;
  return `🏆 ${share >= 0.01 ? `In ${Math.round(share * 100)}%` : `In ${c.ps}`} of ${playSet.n} top-cut decks` +
    (rank <= 100 ? ` · #${rank} most played` : "");
}

function footerText(ctx, price) {
  const bits = [];
  if (price && price.date) bits.push(`TCGplayer prices as of ${shortDate(price.date)}`);
  if ((ctx.graded && ctx.graded.length) || ctx.raw) bits.push("Sales from eBay sold listings");
  bits.push(AFFILIATE_NOTE);
  return bits.join(" · ");
}

const button = (label, custom_id, style = 2, disabled = false) => ({ type: 2, style, label, custom_id, disabled });

// The card's own printings first (this set's foil, its Enchanted), then the
// same character's other versions, most-played first. ≤25, Discord's cap.
export function versionOptions(R, res) {
  const out = [];
  const seen = new Set();
  const push = (i, p, fi) => {
    const k = R.cardKey(p, fi);
    if (seen.has(k) || out.length >= 25) return;
    seen.add(k);
    const c = R.cards[i];
    const set = R.sets[p.s] || {};
    const fin = R.finishLabel(p, fi);
    const f = p.f[fi] || [];
    const px = money(f[4] ?? f[5]);
    out.push({
      label: clip(i === res.index ? [set.n, p.r, fin].filter(Boolean).join(" · ") : c.n, 100),
      // The card's own printings share its stats, which are on screen above;
      // another version gets its stats, then rarity and price (stats.js).
      description: (i === res.index
        ? clip([p.no ? "#" + p.no : null, p.var, px].filter(Boolean).join(" · "), 100)
        : statsLineFor(c, [p.r, fin, { k: "set", t: set.n }, px])) || undefined,
      value: k,
    });
  };
  const own = R.cards[res.index];
  for (const p of own.p) p.f.forEach((f, fi) => push(res.index, p, fi));
  for (const i of res.alts || []) {
    const { printing, fi } = R.pickPrinting(i);
    push(i, printing, fi);
  }
  return out;
}

// ── sealed ───────────────────────────────────────────────────────────────
export function sealedMessage(ctx) {
  const { R, res, price, view = "chart", range = DEFAULT_RANGE, origin } = ctx;
  if (!ctx.today) ctx = { ...ctx, today: new Date().toISOString().slice(0, 10) };
  const it = res.item;
  const key = R.sealedKey(it);
  const lines = [[it.ty, it.sn].filter(Boolean).join(" · "), ""];
  const mkt = price ? price.market : it.mkt, low = price ? price.low : it.low;
  const bits = [];
  if (low != null) bits.push(`**${money(low)}** Low`);
  if (mkt != null) bits.push(low != null ? `${money(mkt)} Market` : `**${money(mkt)}** Market`);
  lines.push(bits.length ? bits.join(" · ") : "No TCGplayer price yet.");
  if (price) {
    const d = price.low != null ? price.lowDelta : price.mktDelta;
    const ch = [["1d", "1D"], ["1w", "1W"], ["1m", "1M"], ["1y", "1Y"]]
      .map(([k, l]) => (d && d[k] != null ? `${l} ${pct(d[k])}` : null)).filter(Boolean);
    if (ch.length) lines.push(ch.join(" · "));
    if (price.standing) lines.push((price.standing.tone === "high" ? "↗ " : "↘ ") + price.standing.label);
  }
  // A booster box is the one product somebody asks the price of while deciding
  // whether to OPEN it, and the site's box EV is the answer — the same number
  // /set shows, computed in the daily build.
  const set = it.s != null ? R.sets[it.s] : null;
  const isBox = it.ty === "Booster Boxes";
  const ev = isBox && set && set.ev ? (set.ev.low ?? set.ev.mkt ?? null) : null;
  const boxPx = low ?? mkt;
  if (ev != null) {
    const ratio = boxPx ? ev / boxPx : null;
    lines.push(`Box EV **${money(ev)}** at ${set.ev.low != null ? "Low" : "NM Market"}` +
      (ratio != null ? ` — the cards inside are worth about **${Math.round(ratio * 100)}%** of the box${ratio >= 1 ? ", more than it costs" : ""}` : ""));
  }
  const embed = {
    title: clip(it.n, 256),
    url: tcgUrl(it.pid, "Normal"),
    color: BRAND_COLOR,
    description: lines.join("\n"),
    footer: { text: (price && price.date ? `TCGplayer prices as of ${shortDate(price.date)} · ` : "") +
      (ev != null ? "box EV as Analytics » Expected Value computes it · " : "") + AFFILIATE_NOTE },
  };
  const date = ctx.chartDate || (price && price.date) || "";
  if (view === "card") { if (it.img) embed.image = { url: it.img }; }
  else {
    if (it.img) embed.thumbnail = { url: it.img };
    embed.image = { url: `${origin}/chart/p/${it.pid}/N/${range}.png?s=1&d=${date}` };
  }
  const row1 = [];
  if (view !== "card") for (const r of ["1m", "3m", "1y", "all"]) row1.push(button(RANGES[r].label, rangeId(r, view, key), r === range ? 1 : 2, r === range));
  row1.push(view === "card" ? button("Price chart", rangeId(range, "chart", key), 2) : button("Product photo", rangeId(range, "card", key), 2));
  const components = [{ type: 1, components: row1 }];
  const alts = (res.alts || []).map((k) => R.sealed[k]).filter(Boolean);
  if (alts.length) {
    const opts = [it, ...alts].slice(0, 25).map((x) => ({
      label: clip(x.n, 100), value: R.sealedKey(x),
      description: clip([x.ty, money(x.low ?? x.mkt)].filter(Boolean).join(" · "), 100) || undefined,
      default: x.pid === it.pid,
    }));
    components.push({ type: 1, components: [{ type: 3, custom_id: pickId(view === "card" ? "card" : "chart", range), placeholder: "Other products", options: opts }] });
  }
  const links = [{ type: 2, style: 5, label: "TCGplayer", url: tcgUrl(it.pid, "Normal") }];
  const az = amazonForSealed({ name: it.n, product_type: it.ty, set_id: null }, it.sn);
  if (az && az.url) links.push({ type: 2, style: 5, label: az.exact ? "Amazon" : "Find on Amazon", url: az.url });
  // A box or a pack of a booster set that is OUT can be opened right here
  // (the site's simulator, at these prices); any set's overview is a click.
  if (set && set.main) {
    const out = !(set.rel && set.rel.lgs && set.rel.lgs > ctx.today);
    if (out && (isBox || it.ty === "Booster Packs")) links.push({ type: 2, style: 2, label: isBox ? "Open a box" : "Open a pack", custom_id: packId(it.s, isBox ? 24 : 1) });
    links.push({ type: 2, style: 2, label: "Set at a glance", custom_id: setId(it.s) });
  }
  components.push({ type: 1, components: links.slice(0, 5) });
  return { embeds: [embed], components };
}

// ── nothing found ────────────────────────────────────────────────────────
export function notFoundMessage(R, res, query, ids) {
  const sug = (res.suggestions || []).slice(0, 5);
  const lines = [res.dimsOnly
    ? `“${clip(query, 60)}” narrows it down but doesn't name a card — add the card's name, e.g. \`elsa ${clip(query, 30)}\`.`
    : `No card or product matched “${clip(query, 60)}”.`];
  // What someone probably meant when the words aren't a card at all.
  const q = String(query || "").trim();
  if (/^(?:\d{5}(?:-\d{4})?|[a-z]\d[a-z] ?\d[a-z]\d|[a-z]{1,2}\d[a-z\d]? ?\d[a-z]{2})$/i.test(q)) {
    lines.push(`Looks like a postal code — for events near there, try ${cmdMention(ids, "events")} \`${clip(q, 12)}\`.`);
  } else if (R.resolveSet && R.resolveSet(q) >= 0 && /\S/.test(q)) {
    lines.push(`For a whole set, try ${cmdMention(ids, "set")} \`${clip(q, 30)}\`.`);
  }
  if (!sug.length && lines.length === 1) lines.push(`Card names work best on their own — \`mowgli\`, \`elsa enchanted\`, \`azurite box\`. ${cmdMention(ids, "help")} shows everything it can do.`);
  const embed = { title: "No match", color: 0x6b6480, description: lines.join("\n") };
  const components = [];
  if (sug.length) {
    embed.description += "\n\nDid you mean one of these?";
    components.push({ type: 1, components: [{
      type: 3, custom_id: pickId("chart", DEFAULT_RANGE), placeholder: "Pick a card",
      // A card's stats go on the option's sub-line; its label says which printing.
      options: sug.map((s) => s.kind === "card"
        ? { label: clip(s.plain || s.label, 100), value: s.value, description: statsLineFor(R.cards[s.i]) || undefined }
        : { label: clip(s.label, 100), value: s.value }),
    }] });
  }
  return { embeds: [embed], components };
}

// ── events near a place ──────────────────────────────────────────────────
// Three sections, rarest first: Set Championships, prereleases, then the
// weekly play grouped BY STORE (one line a shop, its nights listed), because
// "every Monday at Pixel and Packs" is one fact, not four list rows.
// custom_id "e|<control>|<lat>|<lng>|<radius>|<kind>|<place label>" — the
// label is last because it is free text.
export const EVENT_RADII = [10, 25, 50, 100];
const EVENT_KIND_BUTTONS = [["all", "Everything"], ["sc", "Set Champs"], ["prerelease", "Prereleases"], ["other", "Weekly play"]];
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const FORMAT_SHORT = { "Core Constructed": "", "Infinity Constructed": "Infinity", "[Format Coconut]": "Coconut" };
export const eventsId = (ctl, s) => `e|${ctl}|${Number(s.lat).toFixed(3)}|${Number(s.lng).toFixed(3)}|${s.radius}|${s.kind}|${clip(s.label, 40)}`;
export function parseEventsId(id) {
  const m = /^e\|([kr])\|(-?\d{1,3}\.\d{1,3})\|(-?\d{1,3}\.\d{1,3})\|(\d{1,3})\|(all|sc|prerelease|other)\|(.*)$/.exec(String(id || ""));
  if (!m) return null;
  return { lat: Number(m[2]), lng: Number(m[3]), radius: Number(m[4]), kind: m[5], label: m[6] };
}

export function eventsMessage({ place, byKind, radius, kind = "all", query }) {
  const where = [place.city, place.state || place.country].filter(Boolean).join(", ") || clip(query, 40);
  const heading = { all: "Lorcana events", sc: "Set Championships", prerelease: "Prereleases", other: "Weekly Lorcana" }[kind] || "Lorcana events";
  const byTime = (a, b) => String(a.next_start).localeCompare(String(b.next_start));
  const fields = [];
  const within = `within ${radius} mi`;
  const oneOff = (s) => {
    const occ = (s.occurrences || [])[0] || {};
    const unix = Math.floor(Date.parse(occ.start_datetime || s.next_start) / 1000);
    const when = Number.isFinite(unix) ? `<t:${unix}:f>` : shortDate(s.next_start);
    const name = clip(s.store_name || s.name, 48);
    const page = eventPageUrl(occ.event_id != null ? "ev:" + occ.event_id : null) || occ.url;
    const store = page ? `[${name}](${page})` : name;
    const bits = [`**${when}**`, store, `${Math.round(s.distance_mi || 0)} mi`];
    const fmt = FORMAT_SHORT[s.gameplay_format] ?? s.gameplay_format;
    if (fmt && s.kind !== "sc") bits.push(fmt);
    if (occ.registered_user_count != null && occ.capacity) {
      bits.push(occ.registered_user_count >= occ.capacity ? `**full** (${occ.capacity})` : `${occ.registered_user_count}/${occ.capacity} signed up`);
    }
    else if (occ.registered_user_count) bits.push(`${occ.registered_user_count} signed up`);
    if (occ.cost_cents > 0) bits.push((occ.currency || "USD").toUpperCase() === "USD" ? money(occ.cost_cents / 100).replace(/\.00$/, "") : `${(occ.cost_cents / 100).toFixed(0)} ${occ.currency}`);
    return bits.join(" · ");
  };
  const listField = (title, rows, cap, empty) => {
    const lines = [];
    for (const s of rows.slice(0, cap)) {
      const line = oneOff(s);
      if (lines.join("\n").length + line.length + 1 > 1000) break;
      lines.push(line);
    }
    const rest = rows.length - lines.length;
    if (rest > 0) lines.push(`*…and ${rest} more ${within}*`);
    return { name: title + (rows.length ? ` · ${rows.length}` : ""), value: lines.length ? lines.join("\n") : empty };
  };
  if (kind === "all" || kind === "sc") {
    const rows = (byKind.sc || []).slice().sort(byTime);
    fields.push(listField("🏆 Set Championships", rows, kind === "sc" ? 12 : 5,
      byKind.sc == null ? "*Couldn't load these just now.*" : `None listed ${within} yet — stores post them a few weeks ahead.`));
  }
  // A set's prereleases all fall on one weekend, so the question is WHERE:
  // nearest first. Set Championships spread over months: soonest first.
  if (kind === "all" || kind === "prerelease") {
    const rows = (byKind.prerelease || []).slice().sort((a, b) => (a.distance_mi || 0) - (b.distance_mi || 0) || byTime(a, b));
    if (rows.length || kind === "prerelease") {
      fields.push(listField("✨ Prereleases", rows, kind === "prerelease" ? 12 : 5,
        byKind.prerelease == null ? "*Couldn't load these just now.*" : `None listed ${within} right now.`));
    }
  }
  if (kind === "all" || kind === "other") {
    const stores = new Map();
    for (const s of byKind.other || []) {
      const k = s.store_id != null ? "id:" + s.store_id : "n:" + (s.store_name || s.name);
      let g = stores.get(k);
      if (!g) { g = { name: s.store_name || s.name, mi: s.distance_mi || 0, url: null, first: s.next_start, slots: new Map() }; stores.set(k, g); }
      g.mi = Math.min(g.mi, s.distance_mi || 0);
      const occ = (s.occurrences || [])[0] || {};
      const page = eventPageUrl(occ.event_id != null ? "ev:" + occ.event_id : null) || occ.url;
      if (page && (!g.url || String(s.next_start) < String(g.first))) { g.url = page; g.first = s.next_start; }
      // One slot per night and time; a store running Core and Infinity at
      // the same hour is one night with two formats, not two nights.
      const fmt = FORMAT_SHORT[s.gameplay_format] ?? s.gameplay_format ?? "";
      const sk = `${s.dow}|${s.local_time}`;
      const slot = g.slots.get(sk) || { dow: s.dow, time: s.local_time, fmts: new Set() };
      slot.fmts.add(fmt);
      g.slots.set(sk, slot);
    }
    const list = [...stores.values()].sort((a, b) => a.mi - b.mi);
    const lines = [];
    for (const g of list) {
      const slots = [...g.slots.values()].sort((a, b) => ((a.dow + 6) % 7) - ((b.dow + 6) % 7) || String(a.time).localeCompare(String(b.time)))
        .slice(0, 4).map((x) => {
          const f = [...x.fmts];
          const label = f.length > 1 ? " (" + f.map((v) => v || "Core").join(" + ") + ")" : f[0] ? " " + f[0] : "";
          return `${DOW[x.dow] || ""} ${scLocalTime12(x.time)}${label}`.trim();
        });
      const name = clip(g.name, 40);
      const line = `${g.url ? `[${name}](${g.url})` : `**${name}**`} · ${Math.round(g.mi)} mi — ${slots.join(", ")}`;
      if (lines.join("\n").length + line.length + 1 > 1000 || lines.length >= (kind === "other" ? 12 : 6)) break;
      lines.push(line);
    }
    if (list.length > lines.length) lines.push(`*…and ${list.length - lines.length} more stores ${within}*`);
    fields.push({ name: `🗓️ Weekly play${list.length ? ` · ${list.length} store${list.length === 1 ? "" : "s"}` : ""}`,
      value: lines.length ? lines.join("\n") : (byKind.other == null ? "*Couldn't load these just now.*" : `No weekly events listed ${within}.`) });
  }
  const state = { lat: place.lat, lng: place.lng, radius, kind, label: where };
  const finder = new URL(SITE + "/");
  finder.searchParams.set("sczip", clip(query || where, 60));
  finder.searchParams.set("scdist", String(radius));
  if (kind !== "all") finder.searchParams.set("scmode", kind);
  return {
    embeds: [{
      title: clip(`${heading} near ${where}`, 256), color: BRAND_COLOR, fields,
      footer: { text: `Within ${radius} mi · dates in your time zone, weekly times in the store's · from Ravensburger Play · packs.ink` },
    }],
    components: [
      { type: 1, components: EVENT_KIND_BUTTONS.map(([k, l]) => ({ type: 2, style: k === kind ? 1 : 2, label: l, custom_id: eventsId("k", { ...state, kind: k }), disabled: k === kind })) },
      { type: 1, components: EVENT_RADII.map((r) => ({ type: 2, style: r === radius ? 1 : 2, label: `${r} mi`, custom_id: eventsId("r", { ...state, radius: r }), disabled: r === radius })) },
      { type: 1, components: [
        { type: 2, style: 5, label: "Open the event finder", url: finder.toString() },
        { type: 2, style: 5, label: "Lorcana calendar", url: `${SITE}/calendar` },
      ] },
    ],
  };
}

// ── the calendar ─────────────────────────────────────────────────────────
// Grouped by month, one line an event, marked by kind; buttons narrow the
// kind and a menu the region. custom_id "cl|<control>|<kind>|<region>".
const CAL_MARK = { set: "📦", product: "🎁", dlc: "🏆", ccq: "🎟️" };
const CAL_KIND_BUTTONS = [["all", "Everything"], ["release", "Releases"], ["dlc", "Challenges"], ["ccq", "Qualifiers"]];
export const calendarId = (ctl, s) => `cl|${ctl}|${s.kind}|${s.region}`;
export function parseCalendarId(id) {
  const m = /^cl\|([kr])\|(all|release|dlc|ccq)\|([a-z]{2,6})$/.exec(String(id || ""));
  return m ? { kind: m[2], region: m[3] } : null;
}
// "Charlie's Collectible Show · 3801 Sumner Blvd, Raleigh, NC 27616" -> the
// part a reader places an event by: the last "·" segment, its last two
// comma parts.
export function shortPlace(loc) {
  const seg = String(loc || "").split("·").pop().trim();
  const parts = seg.split(",").map((s) => s.trim()).filter(Boolean);
  return clip(parts.length > 2 ? parts.slice(-2).join(", ") : seg, 40);
}
export function calendarMessage({ events, kind = "all", region = "all", regions = [] }) {
  const months = new Map();
  (events || []).forEach((e, k) => {
    const m = /^(\d{4})-(\d{2})/.exec(String(e.starts_on || ""));
    const key = m ? `${MONTH_NAMES[+m[2] - 1]} ${m[1]}` : "Later";
    if (!months.has(key)) months.set(key, []);
    const t = Date.parse(String(e.starts_on) + "T12:00:00Z");
    const when = Number.isFinite(t) ? `<t:${Math.floor(t / 1000)}:D>` : shortDate(e.starts_on);
    // The countdown on the first entry only — "in 3 weeks" beside every line
    // is noise, beside the next thing it is the answer.
    const rel = k === 0 && Number.isFinite(t) ? ` (<t:${Math.floor(t / 1000)}:R>)` : "";
    const name = clip(calEventTitle(e), 60);
    const page = eventPageUrl(e.id) || (e.url && /^https:\/\//.test(e.url) && e.url.length <= 300 ? e.url : null);
    const title = page ? `[${name}](${page})` : `**${name}**`;
    const where = (e.kind === "dlc" || e.kind === "ccq") && e.location ? " · " + shortPlace(e.location) : "";
    months.get(key).push(`${CAL_MARK[e.kind] || "•"} ${title}${e.estimated ? " *(estimated)*" : ""}${where} — ${when}${rel}`);
  });
  const fields = [];
  for (const [name, lines] of months) {
    if (fields.length >= 12) break;
    // Whole lines only: a line clipped mid-way is a broken link or a raw
    // <t:…> tag on screen.
    const kept = [];
    let used = 0;
    for (const l of lines) {
      if (used + l.length + 1 > 990) break;
      kept.push(l);
      used += l.length + 1;
    }
    if (kept.length < lines.length) kept.push(`*…and ${lines.length - kept.length} more*`);
    fields.push({ name, value: kept.join("\n") });
  }
  const label = { all: "Coming up in Lorcana", release: "Set and product releases", dlc: "Disney Lorcana Challenges", ccq: "Challenge qualifiers" }[kind];
  const regionName = region !== "all" ? (regions.find((r) => r.key === region) || {}).label : null;
  const site = new URL(SITE + "/calendar");
  if (kind !== "all") site.searchParams.set("ck", (CAL_FILTERS[kind] || []).join(","));
  if (region !== "all") site.searchParams.set("cr", region);
  return {
    embeds: [{
      title: label + (regionName ? ` · ${regionName}` : ""), color: BRAND_COLOR, url: site.toString(),
      ...(fields.length ? { fields } : { description: "Nothing on the calendar for that — try Everything, or another region." }),
      footer: { text: "📦 release · 🎁 product · 🏆 Challenge · 🎟️ qualifier · dates in your time zone · packs.ink/calendar" },
    }],
    components: [
      { type: 1, components: CAL_KIND_BUTTONS.map(([k, l]) => ({ type: 2, style: k === kind ? 1 : 2, label: l, custom_id: calendarId("k", { kind: k, region }), disabled: k === kind })) },
      { type: 1, components: [{ type: 3, custom_id: calendarId("r", { kind, region }), placeholder: "Region",
        options: [{ key: "all", label: "Everywhere" }, ...regions].slice(0, 25).map((r) => ({ label: r.label, value: r.key, default: r.key === region })) }] },
      { type: 1, components: [{ type: 2, style: 5, label: "Full calendar", url: site.toString() }] },
    ],
  };
}

// ── help ─────────────────────────────────────────────────────────────────
// A command written as </name:id> is one a person can CLICK to start typing
// it. The ids come from registering the commands (tools/register_commands.mjs
// writes src/command-ids.json before each deploy); without them — a local
// run, a first deploy — it falls back to plain bold text.
export const cmdMention = (ids, name) => {
  const top = name.split(" ")[0];
  return ids && /^\d{5,25}$/.test(String(ids[top] || "")) ? `</${name}:${ids[top]}>` : `**/${name}**`;
};
export const helpTryId = (what) => `h|${what}`;
export function parseHelpTryId(id) {
  const m = /^h\|(card|open|set)$/.exec(String(id || ""));
  return m ? m[1] : null;
}
export function helpMessage(ids) {
  const c = (n) => cmdMention(ids, n);
  return {
    embeds: [{
      title: "packs.ink — Lorcana cards, prices and events", color: BRAND_COLOR, url: SITE,
      description: "Type names the way you'd say them: `mowgli`, `enchanted elsa`, `elsa psa 10`, `stich`, `azurite box`. " +
        "No subtitle? You get the version people actually play — switch versions from the menu under any card.",
      fields: [
        { name: "Look something up", value: [
          `${c("card")} \`mowgli\` — the card: picture, text, stats, price and how much it's played`,
          `${c("price")} \`mowgli foil\` — the price chart, recent changes, both finishes`,
          `${c("price")} \`elsa psa 10\` — a slab: last sale, average of the last 5, and a chart of its sales`,
          `${c("set")} \`azurite\` — box price vs box EV, chase cards, sealed prices`,
          `${c("new")} — the newest cards, as they're revealed`,
        ].join("\n") },
        { name: "Play", value: [
          `${c("events")} \`60614\` — Set Championships, prereleases and weekly play near you`,
          `${c("meta")} — which ink pairs win, the most-played cards, the latest big events`,
          `${c("calendar")} — set releases, Challenges and qualifiers coming up`,
        ].join("\n") },
        { name: "For fun", value: `${c("open")} — open a booster pack (or a box) at real prices` },
        { name: "Server managers", value: `${c("reports daily")} — the day's movers posted in a channel · ${c("reports send")} — post one now` },
      ],
      footer: { text: "Add private: True to a command to see the reply alone · prices from TCGplayer, sales from eBay · packs.ink" },
    }],
    components: [{ type: 1, components: [
      { type: 2, style: 1, label: "Try a card", custom_id: helpTryId("card") },
      { type: 2, style: 2, label: "Open a pack", custom_id: helpTryId("open") },
      { type: 2, style: 2, label: "A set at a glance", custom_id: helpTryId("set") },
      { type: 2, style: 5, label: "packs.ink", url: SITE },
    ] }],
  };
}

// ── the meta ─────────────────────────────────────────────────────────────
// What is being played (the index's recency-weighted top-cut appearances —
// the number that picks "the version people play") and who won lately.
const PLACE_MARK = { 1: "🥇", 2: "🥈", 3: "🥉" };
// Player and deck names are free text: escape what Discord would read as
// markdown, or "[OSA] Moluk" and a name with an underscore render wrong.
export const escMd = (s) => String(s || "").replace(/[\\*_~`|>[\]()]/g, "\\$&");
export function deckPageUrl(r) {
  const u = new URL(SITE + "/decks");
  u.searchParams.set("deck", r.deck_id);
  if (r.deck_visibility !== "public" && r.deck_share_token) u.searchParams.set("token", r.deck_share_token);
  return u.toString();
}
// Ten cells in a code span, so the column lines up in any font. Scaled to the
// LEADING pair, not to 100%: the top pair holds a quarter of the top 8s, so an
// absolute bar is two or three cells for everyone and two pairs showing the
// same "25%" came out a cell apart on rounding. Any pair at all gets a cell.
const metaBar = (n, lead) => {
  const k = lead > 0 ? Math.max(n > 0 ? 1 : 0, Math.min(10, Math.round((n / lead) * 10))) : 0;
  return "█".repeat(k) + "░".repeat(10 - k);
};
export function metaMessage({ R, index, meta }) {
  const m = meta || { breakdown: [], recent: [], events: 0, decks: 0 };
  const since = m.sinceSet ? `since ${m.sinceSet} (${shortDate(m.from)})` : `in the last ${META_FALLBACK_DAYS} days`;
  const lead = (m.breakdown && m.breakdown[0] && m.breakdown[0].n) || 0;
  const pairLines = (m.breakdown || []).slice(0, 8).map((p) => {
    const share = m.decks ? p.n / m.decks : 0;
    const pct = String(Math.round(share * 100)).padStart(2) + "%";
    const bits = [`${p.n} deck${p.n === 1 ? "" : "s"}`];
    if (p.t4) bits.push(`${p.t4} top 4`);
    if (p.wins) bits.push(`${p.wins} win${p.wins === 1 ? "" : "s"}`);
    return `${inkMarks(p.inks)} \`${metaBar(p.n, lead)} ${pct}\` **${p.inks.join("/")}** · ${bits.join(" · ")}`;
  });
  const decksEmbed = {
    title: "What's winning: ink pairs in top 8s", color: BRAND_COLOR, url: `${SITE}/decks?s=tournaments`,
    description: m.decks
      ? `${m.decks} top-8 decks from ${m.events} Core event${m.events === 1 ? "" : "s"} ${since}.\n\n` + fitLines(pairLines, 1600)
      : `No Core top 8s on record ${since}.`,
  };

  // The current set's meta only, the same count a /card play line reads.
  const ps = index.playSet && index.playSet.decks >= PLAY_SET_MIN_DECKS ? index.playSet : null;
  const ranked = ps ? R.cards.map((c, i) => ({ c, i })).filter((x) => x.c.ps > 0)
    .sort((a, b) => b.c.ps - a.c.ps || a.i - b.i).slice(0, 10) : [];
  const total = ps ? ps.decks : 0;
  const picks = [];
  const lines = ranked.map((x, k) => {
    const { printing, fi } = R.pickPrinting(x.i);
    const f = printing.f[fi] || printing.f[0] || [];
    const listed = !f[6];
    const px = listed ? (f[4] ?? f[5]) : null;
    const share = total > 0 ? ` · in ${Math.round((x.c.ps / total) * 100)}% of decks` : "";
    picks.push({ label: clip(x.c.n, 100), value: R.cardKey(printing, fi), description: statsLineFor(x.c, [`#${k + 1} most played`, px != null ? money(px) : null]) });
    return `\`${String(k + 1).padStart(2)}\` ${inkMarks(x.c.i)} [${clip(x.c.n, 44)}](${buyUrl(x.c.n, listed ? f[1] : null, f[2] || FIN_PRINTING[f[0]])})${share}${px != null ? ` · ${money(px)}` : ""}`;
  });
  const played = {
    title: ps ? `Most played in ${ps.n}` : "Most played cards", color: BRAND_COLOR, url: `${SITE}/decks?s=tournaments`,
    description: fitLines(lines, 2400) || "Not enough Core top cuts on record since the current set released yet.",
  };

  const fields = [];
  for (const t of m.recent || []) {
    const rows = t.top.slice(0, 4).map((r) => {
      const inks = (r.deck_inks || []).filter(Boolean);
      const deck = clip(r.deck_name || inks.join("/") || "Deck", 40);
      const link = r.deck_id ? `[${escMd(deck)}](${deckPageUrl(r)})` : escMd(deck);
      return `${PLACE_MARK[r.place_rank] || "▫️"} ${escMd(clip(r.player_name || "?", 28))} — ${inkMarks(inks)} ${link}${PLACE_MARK[r.place_rank] ? "" : ` *(${escMd(r.place || "top " + r.place_rank)})*`}`;
    });
    const bits = [shortDate(t.date), t.players ? `${t.players} players` : null, t.format && t.format !== "core" ? t.format[0].toUpperCase() + t.format.slice(1) : null];
    const meta_ = bits.filter(Boolean).join(" · ");
    fields.push({ name: clip(`${t.name}${meta_ ? " — " + meta_ : ""}`, 256), value: fitLines(rows, 1024) });
  }
  const results = {
    title: "Latest big events", color: BRAND_COLOR, url: `${SITE}/decks?s=tournaments`,
    ...(fields.length ? { fields } : { description: "No recent results on record." }),
    footer: { text: `Top 8s from events packs.ink tracks · ${ps ? `play share counts Core top cuts since ${ps.n} released` : "play share counts the current set's Core top cuts"} · TCGplayer Low as of ${shortDate(index.priceDate)} · ${AFFILIATE_NOTE}` },
  };
  const components = [];
  if (picks.length) components.push({ type: 1, components: [{ type: 3, custom_id: openId("card"), placeholder: "Look at a card", options: picks.slice(0, 25) }] });
  components.push({ type: 1, components: [{ type: 2, style: 5, label: "All tournament results", url: `${SITE}/decks?s=tournaments` }] });
  return { embeds: [decksEmbed, played, results], components };
}
