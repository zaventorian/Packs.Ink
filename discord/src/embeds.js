// embeds.js — Discord message payloads. Pure: every function takes data that
// has already been fetched and returns {embeds, components} JSON, which is what
// lets the guard test check a reply without a network.
import { tcgUrl, amazonForSealed, calEventTitle, calEventSubtitle, scLocalTime12 } from "./site.generated.js";
import { FIN_PRINTING, RANGES, DEFAULT_RANGE, MOVER_WINDOWS, MOVER_GROUPS } from "./data.js";

export const SITE = "https://packs.ink";
export const BRAND_COLOR = 0xe3b341;
const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

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

// Card art Discord can actually show: TCGplayer's JPEG photo of the product
// when there is a TCGplayer product (Discord's AVIF support is not something to
// bet a whole feature on), else the art the index stored, else Lorcast.
export function cardImage(printing) {
  const pid = (printing.f || []).map((f) => f[1]).find(Boolean);
  if (printing.img) return printing.img;
  if (pid) return `https://tcgplayer-cdn.tcgplayer.com/product/${pid}_in_1000x1000.jpg`;
  if (/^crd_[0-9a-f]{32}$/.test(printing.id)) return `https://cards.lorcast.io/card/digital/large/${printing.id}.avif`;
  return null;
}

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

  const img = cardImage(p);
  const embed = {
    title: clip(c.n + (ctx.grade ? ` — ${ctx.grade.grader} ${ctx.grade.grade}` : ""), 256),
    url: cardPageUrl(p.id),
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
  const links = [{ type: 2, style: 5, label: "packs.ink", url: cardPageUrl(p.id) }];
  if (pid && !noListing) links.push({ type: 2, style: 5, label: "TCGplayer", url: tcgUrl(pid, printingStr) });
  components.push({ type: 1, components: links });
  return { embeds: [embed], components };
}

function footerText(ctx, price) {
  const bits = [];
  if (price && price.date) bits.push(`TCGplayer prices as of ${shortDate(price.date)}`);
  if ((ctx.graded && ctx.graded.length) || ctx.raw) bits.push("Sales from eBay sold listings");
  bits.push("packs.ink");
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
    footer: { text: (price && price.date ? `TCGplayer prices as of ${shortDate(price.date)} · ` : "") + "packs.ink" },
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
  const img = cardImage(p);
  return {
    title: clip(c.n, 256), url: cardPageUrl(p.id),
    color: hex(c.i && c.i[0] && ctx.inkColors ? ctx.inkColors[c.i[0]] : null),
    description: lines.join("\n"),
    ...(img ? { thumbnail: { url: img } } : {}),
  };
}

// ── movers ───────────────────────────────────────────────────────────────
export function moversMessage({ result, win, dir, group, basis, min, R }) {
  const w = MOVER_WINDOWS[win] || MOVER_WINDOWS["1d"];
  const g = MOVER_GROUPS[group] || MOVER_GROUPS.all;
  const rows = result.rows || [];
  const title = `${dir === "down" ? "Biggest drops" : "Biggest gains"} · ${w.label} · ${g.label}`;
  if (!rows.length) {
    return { embeds: [{ title, color: BRAND_COLOR,
      description: "Nothing cleared the filters today. Try a longer window, another rarity group, or a lower price floor.",
      footer: { text: "packs.ink" } }] };
  }
  const lines = rows.map((r, i) => {
    const name = r.version ? `${r.name} - ${r.version}` : r.name;
    const fin = finishWord(R, r);
    const was = money(r[result.priorCol]), now = money(r[result.todayCol]);
    return `\`${String(i + 1).padStart(2)}\` **${pct(Number(r[result.col]))}** [${clip(name, 60)}](${cardPageUrl(r.card_id)}) · ${r.rarity}${fin ? " · " + fin : ""} · ${was} → **${now}**`;
  });
  const top = rows[0];
  const embed = {
    title, color: dir === "down" ? 0xe86868 : 0x5cc480,
    description: clip(lines.join("\n"), 4000),
    footer: { text: `TCGplayer ${basis === "low" ? "Low" : "NM Market"} · starting price ≥ ${money(min)} · prices as of ${shortDate(result.latest)} · packs.ink` },
  };
  if (top && top.tcgplayer_product_id) embed.thumbnail = { url: `https://tcgplayer-cdn.tcgplayer.com/product/${top.tcgplayer_product_id}_in_1000x1000.jpg` };
  return { embeds: [embed], components: [{ type: 1, components: [{ type: 2, style: 5, label: "Open the Screener", url: `${SITE}/screener` }] }] };
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
const KIND_LABEL = { sc: "Set Championship", prerelease: "Prerelease", other: "Store event" };
export function eventsMessage({ place, series, radius, kind }) {
  const where = [place.city, place.state || place.country].filter(Boolean).join(", ");
  const title = `${kind === "sc" ? "Set Championships" : kind === "prerelease" ? "Prereleases" : "Lorcana events"} near ${where}`;
  const list = (series || []).slice().sort((a, b) => String(a.next_start).localeCompare(String(b.next_start))).slice(0, 12);
  if (!list.length) {
    return { embeds: [{ title, color: BRAND_COLOR,
      description: `Nothing listed within ${radius} miles yet. Try a wider radius, or check back — stores post events a few weeks out.`,
      footer: { text: "From Ravensburger Play · packs.ink" } }] };
  }
  const lines = list.map((s) => {
    const occ = (s.occurrences || [])[0] || {};
    const unix = Math.floor(Date.parse(s.next_start) / 1000);
    const when = Number.isFinite(unix) ? `<t:${unix}:f>` : shortDate(s.next_start);
    const more = s.occurrence_count > 1 ? ` · every ${["Sun","Mon","Tue","Wed","Thu","Fri","Sat"][s.dow] || ""} ${scLocalTime12(s.local_time)}`.replace(/\s+$/, "") : "";
    const store = occ.url ? `[${clip(s.store_name || s.name, 60)}](${occ.url})` : clip(s.store_name || s.name, 60);
    return `**${when}** · ${store} · ${(s.distance_mi || 0).toFixed(0)} mi · ${KIND_LABEL[s.kind] || "Event"}${more}`;
  });
  return { embeds: [{
    title, color: BRAND_COLOR, description: clip(lines.join("\n"), 4000),
    footer: { text: `Within ${radius} mi · times in your time zone · from Ravensburger Play · packs.ink` },
  }], components: [{ type: 1, components: [{ type: 2, style: 5, label: "Open the event finder", url: `${SITE}/calendar` }] }] };
}

// ── the calendar ─────────────────────────────────────────────────────────
export function calendarMessage({ events }) {
  const lines = (events || []).map((e) => {
    const t = Date.parse(String(e.starts_on) + "T12:00:00Z");
    const when = Number.isFinite(t) ? `<t:${Math.floor(t / 1000)}:D> (<t:${Math.floor(t / 1000)}:R>)` : shortDate(e.starts_on);
    const sub = calEventSubtitle(e);
    return `**${clip(calEventTitle(e), 70)}**${e.estimated ? " *(estimated)*" : ""}${sub ? " · " + clip(sub, 60) : ""}${e.location ? " · " + clip(e.location, 50) : ""}\n${when}`;
  });
  return { embeds: [{
    title: "Coming up in Lorcana", color: BRAND_COLOR,
    description: clip(lines.join("\n") || "Nothing on the calendar right now.", 4000),
    footer: { text: "Set releases, Challenges and qualifiers · packs.ink/calendar" },
  }], components: [{ type: 1, components: [{ type: 2, style: 5, label: "Full calendar", url: `${SITE}/calendar` }] }] };
}

// ── help ─────────────────────────────────────────────────────────────────
export function helpMessage() {
  return { embeds: [{
    title: "Packs.Ink bot", color: BRAND_COLOR,
    description: [
      "**/card** `name` — the card, big, with its price.",
      "**/price** `name` — prices, changes and a price chart.",
      "Type it however you say it: `mowgli`, `enchanted elsa`, `elsa psa 10`, `stich`, `azurite sea box`. With no subtitle you get the version people actually play; pick another from the menu under the reply.",
      "",
      "**/deck** — paste a decklist and see what it costs to build.",
      "**/movers** — today's biggest gains and drops.",
      "**/events** `zip or town` — Lorcana events near you.",
      "**/calendar** — set releases, Challenges and qualifiers coming up.",
      "Right-click any message → **Apps → Price check** to price every card it mentions, or a whole posted decklist.",
      "",
      "**/reports** (server managers) — a daily or weekly movers report in a channel.",
    ].join("\n"),
    footer: { text: "Prices from TCGplayer, graded and raw sales from eBay · packs.ink" },
  }] };
}

// ── a whole decklist ─────────────────────────────────────────────────────
export function deckMessage({ result, priceDate }) {
  const r = result;
  const lines = [
    `**${money(r.totalMarket) || "$0.00"}** at NM Market · ${money(r.totalLow) || "$0.00"} at Low`,
    `*${r.count} cards, each at its cheapest printing.*`,
  ];
  if (r.count !== 60) lines.push(`Note: that's ${r.count} cards — a Lorcana deck is 60.`);
  lines.push("");
  const shown = r.rows.slice(0, 15);
  for (const x of shown) {
    const id = x.mktAt ? x.mktAt.p.id : x.card.p[0].id;
    const each = x.mkt != null ? money(x.mkt) : "no price";
    const tot = x.mkt != null ? ` · **${money(x.mkt * x.qty)}**` : "";
    lines.push(`\`${String(x.qty).padStart(2)}×\` [${clip(x.card.n, 48)}](${cardPageUrl(id)}) — ${each} ea${tot}${x.guessed ? " *(closest match)*" : ""}`);
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
  return { embeds: [{
    title: "Deck price", color: BRAND_COLOR, description: clip(lines.join("\n"), 4000),
    footer: { text: `TCGplayer prices as of ${shortDate(priceDate)} · cheapest printing of each card · packs.ink` },
  }], components: [] };
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
