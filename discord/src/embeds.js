// embeds.js — Discord message payloads. Pure: every function takes data that
// has already been fetched and returns {embeds, components} JSON, which is what
// lets the guard test check a reply without a network.
import { tcgUrl, tcgSetSearchUrl, amazonForSealed, calEventTitle, calEventSubtitle, scLocalTime12, tcgMassEntryParts, tcgMassName } from "./site.generated.js";
import { FIN_PRINTING, RANGES, DEFAULT_RANGE, MOVER_WINDOWS, MOVER_GROUPS, CAL_FILTERS } from "./data.js";

export const SITE = "https://packs.ink";
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
export const openId = (view) => `o|${view}`;
export function parseOpenId(id) {
  const m = /^o\|([a-z]+)$/.exec(String(id || ""));
  return m && VIEWS.includes(m[1]) ? { view: m[1] } : null;
}

// ── one card ─────────────────────────────────────────────────────────────
// ctx: { R (resolver), res (resolve() result), price (priceSummary or null),
//        graded (rows for this printing), raw (raw eBay rollup row or null),
//        view, range, origin, chartDate, query, grade {grader, grade} }
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
  const ident = gameplayLine(c);
  if (ident) lines.push(`*${ident}*`);
  const play = playLine(R, res.index, ctx.playDecks);
  if (play) lines.push(play);
  lines.push("");

  const mkt = price ? price.market : (f ? f[5] : null);
  const low = price ? price.low : (f ? f[4] : null);
  // A promo TCGplayer can't price (the raw eBay watchlist) inverts the order,
  // as the site's card page does: eBay's last sale and average lead, and
  // TCGplayer's number — the fossil on exactly these cards — follows, plain.
  const rawLead = !!(ctx.raw && ctx.raw.last_sold_price != null);
  if (rawLead) {
    const n = ctx.raw.last_5_count || 0;
    lines.push(`**${money(ctx.raw.last_sold_price)}** last sold on eBay (${shortDate(ctx.raw.last_sold_date)})` +
      (ctx.raw.avg_last_5 != null && n > 1 ? ` · avg of last ${n} ${money(ctx.raw.avg_last_5)}` : ""));
    lines.push(`${ctx.raw.sale_count} raw sale${ctx.raw.sale_count === 1 ? "" : "s"} on record`);
    const tcg = [mkt != null ? `${money(mkt)} NM Market` : null, low != null ? `${money(low)} Low` : null].filter(Boolean);
    lines.push("TCGplayer: " + (noListing || !tcg.length ? "no price" : tcg.join(" · ")));
  } else if (noListing) {
    lines.push("No TCGplayer listing of its own — TCGplayer files it with the regular printing.");
  } else if (mkt != null || low != null) {
    const bits = [];
    if (mkt != null) bits.push(`**${money(mkt)}** NM Market`);
    if (low != null) bits.push(`${money(low)} Low`);
    lines.push(bits.join(" · "));
  } else {
    lines.push("No TCGplayer price yet.");
  }
  // The change line and the "Cheapest in 12 months" note are judgements ON
  // TCGplayer's price, so they are left off where that price isn't the market.
  if (price && !noListing && !rawLead) {
    const d = price.market != null ? price.mktDelta : price.lowDelta;
    const ch = [["1d", "1D"], ["1w", "1W"], ["1m", "1M"], ["1y", "1Y"]]
      .map(([k, l]) => (d && d[k] != null ? `${l} ${pct(d[k])}` : null)).filter(Boolean);
    if (ch.length) lines.push(ch.join(" · "));
    if (price.standing) lines.push((price.standing.tone === "high" ? "↗ " : "↘ ") + price.standing.label);
  }

  const fields = [];
  for (const g of ctx.graded || []) {
    fields.push({
      name: `${g.grader} ${g.grade}`,
      value: [
        `Last **${money(g.last_sold_price)}**`,
        g.avg_last_5 != null ? `Avg 5 ${money(g.avg_last_5)}` : null,
        `${g.sale_count} sale${g.sale_count === 1 ? "" : "s"}`,
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
    if (img) embed.image = { url: img };
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
export const INK_MARK = { Amber: "🟨", Amethyst: "🟪", Emerald: "🟩", Ruby: "🟥", Sapphire: "🟦", Steel: "⬜" };
export const inkMarks = (inks) => (inks || []).map((k) => INK_MARK[k] || "").join("");

export function gameplayLine(c) {
  const bits = [];
  if (c.i && c.i.length) bits.push(`${inkMarks(c.i)} ${c.i.join("/")}`);
  if (c.cost != null) bits.push(`${c.cost} cost`);
  if (c.t) bits.push(c.t + (c.k && c.k.length ? " — " + c.k.slice(0, 4).join(", ") : ""));
  return bits.join(" · ");
}

// Rank among every card with a recent top-cut appearance, most played first.
const PLAY_RANK = new WeakMap();
export function playRankOf(R, i) {
  let m = PLAY_RANK.get(R);
  if (!m) {
    m = new Map();
    R.cards.map((c, k) => [k, c.pl || 0]).filter((x) => x[1] > 0).sort((a, b) => b[1] - a[1] || a[0] - b[0])
      .forEach(([k], pos) => m.set(k, pos + 1));
    PLAY_RANK.set(R, m);
  }
  return m.get(i) || null;
}
export function playLine(R, i, playDecks) {
  const c = R.cards[i];
  const rank = playRankOf(R, i);
  if (!rank || !(c.pl > 0)) return null;
  const share = playDecks > 0 ? c.pl / playDecks : null;
  if (share != null && share < 0.02 && rank > 100) return null;
  return `🏆 ${share != null && share >= 0.01 ? `In ${Math.round(share * 100)}% of recent tournament top-cut decks` : "Played in recent tournament top cuts"}` +
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
    const px = money(f[5] ?? f[4]);
    out.push({
      label: clip(i === res.index ? [set.n, p.r, fin].filter(Boolean).join(" · ") : c.n, 100),
      description: clip([i === res.index ? (p.no ? "#" + p.no : null) : set.n, i === res.index ? null : p.r,
        i === res.index ? p.var : fin, px].filter(Boolean).join(" · "), 100) || undefined,
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
  const it = res.item;
  const key = R.sealedKey(it);
  const lines = [[it.ty, it.sn].filter(Boolean).join(" · "), ""];
  const mkt = price ? price.market : it.mkt, low = price ? price.low : it.low;
  const bits = [];
  if (mkt != null) bits.push(`**${money(mkt)}** Market`);
  if (low != null) bits.push(`${money(low)} Low`);
  lines.push(bits.length ? bits.join(" · ") : "No TCGplayer price yet.");
  if (price) {
    const d = price.market != null ? price.mktDelta : price.lowDelta;
    const ch = [["1d", "1D"], ["1w", "1W"], ["1m", "1M"], ["1y", "1Y"]]
      .map(([k, l]) => (d && d[k] != null ? `${l} ${pct(d[k])}` : null)).filter(Boolean);
    if (ch.length) lines.push(ch.join(" · "));
    if (price.standing) lines.push((price.standing.tone === "high" ? "↗ " : "↘ ") + price.standing.label);
  }
  const embed = {
    title: clip(it.n, 256),
    url: tcgUrl(it.pid, "Normal"),
    color: BRAND_COLOR,
    description: lines.join("\n"),
    footer: { text: (price && price.date ? `TCGplayer prices as of ${shortDate(price.date)} · ` : "") + AFFILIATE_NOTE },
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
      description: clip([x.ty, money(x.mkt ?? x.low)].filter(Boolean).join(" · "), 100) || undefined,
      default: x.pid === it.pid,
    }));
    components.push({ type: 1, components: [{ type: 3, custom_id: pickId(view === "card" ? "card" : "chart", range), placeholder: "Other products", options: opts }] });
  }
  const links = [{ type: 2, style: 5, label: "TCGplayer", url: tcgUrl(it.pid, "Normal") }];
  const az = amazonForSealed({ name: it.n, product_type: it.ty, set_id: null }, it.sn);
  if (az && az.url) links.push({ type: 2, style: 5, label: az.exact ? "Amazon" : "Find on Amazon", url: az.url });
  components.push({ type: 1, components: links });
  return { embeds: [embed], components };
}

// ── nothing found ────────────────────────────────────────────────────────
export function notFoundMessage(R, res, query) {
  const sug = (res.suggestions || []).slice(0, 5);
  const lines = [res.dimsOnly
    ? `“${clip(query, 60)}” narrows it down but doesn't name a card — add the card's name, e.g. \`elsa ${clip(query, 30)}\`.`
    : `No card or product matched “${clip(query, 60)}”.`];
  const embed = { title: "No match", color: 0x6b6480, description: lines.join("\n") };
  const components = [];
  if (sug.length) {
    embed.description += "\n\nDid you mean one of these?";
    components.push({ type: 1, components: [{
      type: 3, custom_id: pickId("chart", DEFAULT_RANGE), placeholder: "Pick a card",
      options: sug.map((s) => ({ label: clip(s.label, 100), value: s.value })),
    }] });
  }
  return { embeds: [embed], components };
}

// ── several cards at once (the "Price check" message command) ──────────
export function compactCardEmbed(ctx) {
  const { R, res, price } = ctx;
  const c = res.card, p = res.printing, f = p.f[res.fi] || p.f[0];
  const set = R.sets[p.s] || {};
  const fin = R.finishLabel(p, res.fi);
  const mkt = price ? price.market : f && f[5], low = price ? price.low : f && f[4];
  const d = price ? (price.market != null ? price.mktDelta : price.lowDelta) : null;
  const lines = [
    [set.n, p.no ? "#" + p.no : null, p.r, p.var, fin && fin !== p.var ? fin : null].filter(Boolean).join(" · "),
    [mkt != null ? `**${money(mkt)}** NM Market` : null, low != null ? `${money(low)} Low` : null].filter(Boolean).join(" · ") || "No TCGplayer price yet.",
    d ? [["1w", "1W"], ["1m", "1M"]].map(([k, l]) => (d[k] != null ? `${l} ${pct(d[k])}` : null)).filter(Boolean).join(" · ") : "",
  ].filter(Boolean);
  const img = cardImage(p, ctx.origin);
  return {
    title: clip(c.n, 256), url: buyUrl(c.n, f && !f[6] ? f[1] : null, (f && f[2]) || FIN_PRINTING[f && f[0]] || "Normal"),
    color: hex(c.i && c.i[0] && ctx.inkColors ? ctx.inkColors[c.i[0]] : null),
    description: lines.join("\n"),
    ...(img ? { thumbnail: { url: img } } : {}),
  };
}

// "Price check" on a message: up to three compact embeds and a menu to open
// one properly. Each title is an affiliate link, so the disclosure goes under
// them, once (a sealed embed already carries it in its own footer).
export function priceCheckMessage({ embeds, options, range = DEFAULT_RANGE }) {
  const last = embeds[embeds.length - 1];
  if (last && !(last.footer && last.footer.text)) last.footer = { text: AFFILIATE_NOTE };
  return {
    embeds,
    components: options && options.length
      ? [{ type: 1, components: [{ type: 3, custom_id: pickId("chart", range), placeholder: "Open one with its price chart", options }] }]
      : [],
  };
}

// ── movers ───────────────────────────────────────────────────────────────
// The board is browsed, not re-typed: every control below redraws THIS
// message. The state rides in each control's custom_id —
//   m|<control>|<window>|<up|down>|<group>|<market|low>|<min>
// ⚠ The <control> letter is what keeps custom_ids unique: the highlighted
// window button, the highlighted direction and the highlighted basis all
// describe the CURRENT board, and Discord refuses a message in which two
// components share a custom_id.
const MOVER_BUTTON_WINDOWS = ["1d", "1w", "1m", "3m", "1y"];
export const moversId = (ctl, s) => `m|${ctl}|${s.win}|${s.dir}|${s.group}|${s.basis}|${s.min}`;
export function parseMoversId(id) {
  const m = /^m\|([wdbg])\|([a-z0-9]+)\|(up|down)\|([a-z]+)\|(market|low)\|(\d{1,5}(?:\.\d{1,2})?)$/.exec(String(id || ""));
  if (!m || !MOVER_WINDOWS[m[2]] || !MOVER_GROUPS[m[4]]) return null;
  return { win: m[2], dir: m[3], group: m[4], basis: m[5], min: Number(m[6]) };
}
const SEALED_SINGULAR = {
  "Booster Boxes": "Booster Box", "Illumineer's Troves": "Trove", "Gift Sets": "Gift Set",
  "Collector's Edition": "Collector's Edition", "Bundles": "Bundle", "Quests": "Quest",
};
const FIN_CODE = { "Normal": "N", "Cold Foil": "C", "Holofoil": "H", "Foil": "F" };

export function moversMessage({ result, win, dir, group, basis, min, R }) {
  const w = MOVER_WINDOWS[win] || MOVER_WINDOWS["1d"];
  const g = MOVER_GROUPS[group] || MOVER_GROUPS.all;
  const state = { win, dir, group, basis, min };
  const rows = result.rows || [];
  const title = `${dir === "down" ? "Biggest drops" : "Biggest gains"} · ${w.label} · ${g.sealed ? "Sealed product" : g.label}`;
  const picks = [];
  let topImg = null;
  const lines = rows.map((r, i) => {
    let name, url, what, was, now, change, key, img;
    if (result.sealed) {
      const s = r.s;
      name = s.n; url = tcgUrl(s.pid, "Normal");
      what = [SEALED_SINGULAR[s.ty] || s.ty, s.sn].filter(Boolean).join(" · ");
      was = money(r.prior); now = money(r.now); change = r.pct;
      key = R.sealedKey(s); img = s.img;
    } else {
      name = r.version ? `${r.name} - ${r.version}` : r.name;
      url = buyUrl(name, r.tcgplayer_product_id, r.printing);
      const fin = finishWord(R, r);
      what = r.rarity + (fin ? " · " + fin : "");
      was = money(r[result.priorCol]); now = money(r[result.todayCol]); change = Number(r[result.col]);
      key = R.byCardId.has(r.card_id) ? `c|${r.card_id}|${FIN_CODE[r.printing] || "N"}` : null;
      img = r.tcgplayer_product_id ? `https://tcgplayer-cdn.tcgplayer.com/product/${r.tcgplayer_product_id}_in_1000x1000.jpg` : null;
    }
    if (key && !picks.some((p) => p.value === key)) {
      picks.push({ label: clip(name, 100), value: key, description: clip(`${pct(change)} · ${what} · ${now}`, 100) });
    }
    if (i === 0) topImg = img;
    return `\`${String(i + 1).padStart(2)}\` **${pct(change)}** [${clip(name, 60)}](${url}) · ${what} · ${was} → **${now}**`;
  });
  const embed = {
    title, color: rows.length ? (dir === "down" ? 0xe86868 : 0x5cc480) : BRAND_COLOR,
    description: rows.length ? clip(lines.join("\n"), 4000)
      : "Nothing cleared the filters. Try a longer window or another group below" + (min > 0 ? `, or a lower price floor than ${money(min)} with \`/movers min_price\`.` : "."),
    footer: { text: [`TCGplayer ${basis === "low" ? "Low" : g.sealed ? "Market" : "NM Market"}`, `starting price ≥ ${money(min)}`,
      result.latest ? `prices as of ${shortDate(result.latest)}` : null, rows.length ? AFFILIATE_NOTE : null].filter(Boolean).join(" · ") },
  };
  if (topImg) embed.thumbnail = { url: topImg };

  const btn = (label, ctl, s, on) => ({ type: 2, style: on ? 1 : 2, label, custom_id: moversId(ctl, s), disabled: !!on });
  const wins = MOVER_BUTTON_WINDOWS.includes(win) ? MOVER_BUTTON_WINDOWS : MOVER_BUTTON_WINDOWS.map((k) => (k === "3m" ? win : k));
  const components = [
    { type: 1, components: wins.map((k) => btn(MOVER_WINDOWS[k].label, "w", { ...state, win: k }, k === win)) },
    { type: 1, components: [
      btn("▲ Gains", "d", { ...state, dir: "up" }, dir === "up"),
      btn("▼ Drops", "d", { ...state, dir: "down" }, dir === "down"),
      btn(g.sealed ? "Market" : "NM Market", "b", { ...state, basis: "market" }, basis === "market"),
      btn("Low", "b", { ...state, basis: "low" }, basis === "low"),
    ] },
    { type: 1, components: [{
      type: 3, custom_id: moversId("g", state), placeholder: "Which cards",
      options: Object.entries(MOVER_GROUPS).map(([k, v]) => ({ label: clip(v.label, 100), value: k, default: k === group })),
    }] },
  ];
  if (picks.length) components.push({ type: 1, components: [{ type: 3, custom_id: openId("chart"), placeholder: "Look at one of these", options: picks.slice(0, 25) }] });
  components.push({ type: 1, components: [{ type: 2, style: 5, label: "Open the Screener", url: `${SITE}/screener${g.sealed ? "?m=sealed" : ""}` }] });
  return { embeds: [embed], components };
}

// A finish word only when the card really has two printings — the site's
// printingBadge rule, read from the index the build stamped.
function finishWord(R, row) {
  const hit = R.byCardId.get(row.card_id);
  if (!hit) return null;
  const f = hit.p.f.find((x) => x[2] === row.printing);
  return f ? f[3] || (hit.p.f.length > 1 ? (f[0] === "N" ? "Non-foil" : "Foil") : null) : null;
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
    const store = occ.url ? `[${name}](${occ.url})` : name;
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
      if (occ.url && (!g.url || String(s.next_start) < String(g.first))) { g.url = occ.url; g.first = s.next_start; }
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
export function calendarMessage({ events, kind = "all", region = "all", regions = [] }) {
  const months = new Map();
  for (const e of events || []) {
    const m = /^(\d{4})-(\d{2})/.exec(String(e.starts_on || ""));
    const key = m ? `${MONTH_NAMES[+m[2] - 1]} ${m[1]}` : "Later";
    if (!months.has(key)) months.set(key, []);
    const t = Date.parse(String(e.starts_on) + "T12:00:00Z");
    const when = Number.isFinite(t) ? `<t:${Math.floor(t / 1000)}:D>` : shortDate(e.starts_on);
    const rel = Number.isFinite(t) ? ` (<t:${Math.floor(t / 1000)}:R>)` : "";
    const name = clip(calEventTitle(e), 70);
    const title = e.url && /^https:\/\//.test(e.url) ? `[${name}](${e.url})` : `**${name}**`;
    const where = e.kind === "dlc" || e.kind === "ccq" ? (e.location ? " · " + clip(e.location, 50) : "") : "";
    months.get(key).push(`${CAL_MARK[e.kind] || "•"} ${title}${e.estimated ? " *(estimated)*" : ""}${where} — ${when}${rel}`);
  }
  const fields = [];
  for (const [name, lines] of months) {
    if (fields.length >= 12) break;
    fields.push({ name, value: clip(lines.join("\n"), 1024) });
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
  const m = /^h\|(card|trade|open|set|movers)$/.exec(String(id || ""));
  return m ? m[1] : null;
}
export function helpMessage(ids) {
  const c = (n) => cmdMention(ids, n);
  return {
    embeds: [{
      title: "packs.ink — Lorcana prices, trades and events", color: BRAND_COLOR, url: SITE,
      description: "Type names the way you'd say them: `mowgli`, `enchanted elsa`, `elsa psa 10`, `stich`, `azurite box`. " +
        "No subtitle? You get the version people actually play — switch versions from the menu under any card.",
      fields: [
        { name: "Look something up", value: [
          `${c("card")} \`mowgli\` — the card and what it's worth`,
          `${c("price")} \`elsa psa 10\` — price chart, graded and eBay sales`,
          `${c("set")} \`azurite\` — box price vs box EV, chase cards`,
        ].join("\n") },
        { name: "Trading", value: [
          `${c("trade")} — is a trade fair? Both sides priced, cash too`,
          `${c("deck")} — paste a decklist, see what it costs to build`,
          "Right-click a message → **Apps → Price check** — prices a trade post (H: / W:), a decklist, or any cards it mentions",
        ].join("\n") },
        { name: "Market", value: `${c("movers")} — biggest gains and drops, cards or sealed; flip windows with the buttons` },
        { name: "Play", value: [
          `${c("events")} \`60614\` — Set Championships, prereleases and weekly play near you`,
          `${c("meta")} — the most-played cards and the latest tournament winners`,
          `${c("calendar")} — set releases, Challenges and qualifiers coming up`,
        ].join("\n") },
        { name: "For fun", value: `${c("open")} — open a booster pack (or a box) at real prices` },
        { name: "Server managers", value: `${c("reports daily")} — the day's movers posted in a channel` },
      ],
      footer: { text: "Add private: True to a command to see the reply alone · prices from TCGplayer, sales from eBay · packs.ink" },
    }],
    components: [{ type: 1, components: [
      { type: 2, style: 1, label: "Try a card", custom_id: helpTryId("card") },
      { type: 2, style: 2, label: "Try a trade", custom_id: helpTryId("trade") },
      { type: 2, style: 2, label: "Open a pack", custom_id: helpTryId("open") },
      { type: 2, style: 2, label: "Today's movers", custom_id: helpTryId("movers") },
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
export function metaMessage({ R, index, results }) {
  const ranked = R.cards.map((c, i) => ({ c, i })).filter((x) => x.c.pl > 0)
    .sort((a, b) => b.c.pl - a.c.pl || a.i - b.i).slice(0, 12);
  const total = index.playDecks || 0;
  const picks = [];
  const lines = ranked.map((x, k) => {
    const { printing, fi } = R.pickPrinting(x.i);
    const f = printing.f[fi] || printing.f[0] || [];
    const listed = !f[6];
    const px = listed ? (f[5] ?? f[4]) : null;
    const share = total > 0 ? ` · in ${Math.round((x.c.pl / total) * 100)}% of decks` : "";
    picks.push({ label: clip(x.c.n, 100), value: R.cardKey(printing, fi), description: clip(`#${k + 1} most played${px != null ? " · " + money(px) : ""}`, 100) });
    return `\`${String(k + 1).padStart(2)}\` ${inkMarks(x.c.i)} [${clip(x.c.n, 44)}](${buyUrl(x.c.n, listed ? f[1] : null, f[2] || FIN_PRINTING[f[0]])})${share}${px != null ? ` · ${money(px)}` : ""}`;
  });
  const played = {
    title: "Most played in recent tournaments", color: BRAND_COLOR, url: `${SITE}/decks?s=tournaments`,
    description: clip(lines.join("\n"), 4000) || "No tournament decks on record yet.",
  };
  const fields = [];
  for (const t of results || []) {
    if (!t.top || !t.top.length) continue;
    const rows = t.top.map((r) => {
      const inks = (r.deck_inks || []).filter(Boolean);
      const deck = clip(r.deck_name || inks.join("/") || "Deck", 40);
      const link = r.deck_id ? `[${escMd(deck)}](${deckPageUrl(r)})` : escMd(deck);
      return `${PLACE_MARK[r.place_rank] || "▫️"} ${escMd(clip(r.player_name || "?", 28))} — ${inkMarks(inks)} ${link}${PLACE_MARK[r.place_rank] ? "" : ` *(${escMd(r.place || "top " + r.place_rank)})*`}`;
    });
    const meta = [shortDate(t.event_date), t.num_players ? `${t.num_players} players` : null].filter(Boolean).join(" · ");
    fields.push({ name: clip(`${t.name}${meta ? " — " + meta : ""}`, 256), value: clip(rows.join("\n"), 1024) });
  }
  const results_ = {
    title: "Latest results", color: BRAND_COLOR, url: `${SITE}/decks?s=tournaments`,
    ...(fields.length ? { fields } : { description: "No recent results on record." }),
    footer: { text: `Play share is recency-weighted across recent top-cut decks · TCGplayer NM Market as of ${shortDate(index.priceDate)} · ${AFFILIATE_NOTE}` },
  };
  const components = [];
  if (picks.length) components.push({ type: 1, components: [{ type: 3, custom_id: openId("card"), placeholder: "Look at a card", options: picks.slice(0, 25) }] });
  components.push({ type: 1, components: [{ type: 2, style: 5, label: "All tournament results", url: `${SITE}/decks?s=tournaments` }] });
  return { embeds: [played, results_], components };
}

// ── a whole decklist ─────────────────────────────────────────────────────
export function deckMessage({ result, priceDate, tcgNames }) {
  const r = result;
  const lines = [
    `**${money(r.totalMarket) || "$0.00"}** at NM Market · ${money(r.totalLow) || "$0.00"} at Low`,
    `*${r.count} cards, each at its cheapest printing.*`,
  ];
  if (r.count !== 60) lines.push(`Note: that's ${r.count} cards — a Lorcana deck is 60.`);
  lines.push("");
  const shown = r.rows.slice(0, 15);
  for (const x of shown) {
    // The link buys the printing the price came from — the cheapest one.
    const f = x.mktAt ? x.mktAt.f : null;
    const url = buyUrl(x.card.n, f && !f[6] ? f[1] : null, f ? f[2] || FIN_PRINTING[f[0]] : "Normal");
    const each = x.mkt != null ? money(x.mkt) : "no price";
    const tot = x.mkt != null ? ` · **${money(x.mkt * x.qty)}**` : "";
    lines.push(`\`${String(x.qty).padStart(2)}×\` [${clip(x.card.n, 48)}](${url}) — ${each} ea${tot}${x.guessed ? " *(closest match)*" : ""}`);
  }
  if (r.rows.length > shown.length) {
    const rest = r.rows.slice(shown.length);
    const restTotal = rest.reduce((s, x) => s + (x.mkt != null ? x.mkt * x.qty : 0), 0);
    const restCount = rest.reduce((s, x) => s + x.qty, 0);
    lines.push(`…and ${restCount} more card${restCount === 1 ? "" : "s"} (${rest.length} line${rest.length === 1 ? "" : "s"}) worth ${money(restTotal) || "$0.00"} together.`);
  }
  if (r.unmatched.length) {
    lines.push("", "Couldn't find: " + r.unmatched.slice(0, 8).map((e) => `“${clip(e.name, 40)}”`).join(", ") +
      (r.unmatched.length > 8 ? ` and ${r.unmatched.length - 8} more` : "") + " — not counted.");
  }
  if (r.unpricedMarket) lines.push(`${r.unpricedMarket} card${r.unpricedMarket === 1 ? " has" : "s have"} no NM Market price and count as $0.`);
  const embeds = [{
    title: "Deck price", color: BRAND_COLOR, description: clip(lines.join("\n"), 4000),
    footer: { text: `TCGplayer prices as of ${shortDate(priceDate)} · cheapest printing of each card · ${AFFILIATE_NOTE}` },
  }];
  // The whole list as ONE TCGplayer cart (mass entry), each card spelled the
  // way TCGplayer spells it — the site's own builder. A 60-card list is always
  // one cart. Its own embed: the cart URL runs to a couple of thousand
  // characters, and the list above already uses most of its 4,096.
  const cart = deckCartUrl(r, tcgNames);
  if (cart) {
    embeds.push({ color: BRAND_COLOR,
      description: `🛒 [**Buy the whole deck on TCGplayer** — one cart, ${r.rows.reduce((s, x) => s + x.qty, 0)} cards](${cart})\n*Each card by name at its base printing; pick foils in the cart.*` });
  }
  return { embeds, components: [] };
}

const MASS_NAMES = new WeakMap();
export function tcgNameMap(obj) {
  if (!obj) return null;
  let m = MASS_NAMES.get(obj);
  if (!m) { m = new Map(Object.entries(obj).map(([k, v]) => [Number(k), v])); MASS_NAMES.set(obj, m); }
  return m;
}
export function deckCartUrl(r, tcgNames) {
  const byName = new Map();
  for (const x of r.rows || []) {
    const f = x.mktAt ? x.mktAt.f : null;
    const name = tcgMassName(tcgNames, f && !f[6] ? f[1] : null, x.card.n);
    if (name) byName.set(name, (byName.get(name) || 0) + x.qty);
  }
  if (!byName.size) return null;
  const parts = tcgMassEntryParts([...byName].map(([name, qty]) => `${qty} ${name}`));
  const url = parts[0] && parts[0].url;
  return url && url.length <= 3800 ? url : null;
}

export const DECK_MODAL_ID = (priv) => `deck|${priv ? "p" : "-"}`;
export function deckModal(priv) {
  return {
    custom_id: DECK_MODAL_ID(priv), title: "Price a decklist",
    components: [{ type: 1, components: [{
      type: 4, custom_id: "list", style: 2, label: "Paste the decklist", required: true,
      min_length: 3, max_length: 4000,
      placeholder: "4 Mowgli - Man Cub\n4 Elsa - Spirit of Winter\n2 Be Prepared\n…",
    }] }],
  };
}
