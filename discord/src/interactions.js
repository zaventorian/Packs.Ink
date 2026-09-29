// interactions.js — one Discord interaction in, one response out.
//
// Discord gives an interaction 3 seconds. Anything that touches the database
// is therefore DEFERRED: answer "thinking…" (type 5, or 6 for a button) at
// once, do the work in waitUntil, then PATCH the original message. Only the
// things that are pure and local — autocomplete, /help — answer directly.
import * as E from "./embeds.js";
import * as D from "./data.js";
import { parseDeckList, looksLikeDeck, priceDeck } from "./deck.js";
import { parseTradePost, priceTrade, tradeMessage, tradeModal, tradeSiteUrl } from "./trade.js";
import { setOverview, setMessage, openPacks, packMessage, parsePackId, newCards, newCardsMessage, freshRevealRows } from "./set.js";
import { CALENDAR_REGIONS } from "./site.generated.js";
import { chartResponse } from "./charts.js";

export const T = { PING: 1, COMMAND: 2, COMPONENT: 3, AUTOCOMPLETE: 4, MODAL_SUBMIT: 5 };
export const R_ = { PONG: 1, MESSAGE: 4, DEFERRED: 5, DEFERRED_UPDATE: 6, AUTOCOMPLETE: 8, MODAL: 9 };
const EPHEMERAL = 64;
const MANAGE_GUILD = 1n << 5n;
export const DISCORD_API = "https://discord.com/api/v10";
// Nothing the bot says may ping anyone — the "closest match for …" line
// echoes what a user typed, and that could be "@everyone".
const QUIET = { parse: [] };

const opt = (options, name) => (options || []).find((o) => o.name === name);
const optVal = (options, name, dflt) => { const o = opt(options, name); return o ? o.value : dflt; };

export async function handleInteraction(it, deps) {
  if (it.type === T.PING) return { type: R_.PONG };
  if (it.type === T.AUTOCOMPLETE) return autocomplete(it, deps);
  if (it.type === T.COMMAND) return command(it, deps);
  if (it.type === T.COMPONENT) return component(it, deps);
  if (it.type === T.MODAL_SUBMIT) return modalSubmit(it, deps);
  return { type: R_.MESSAGE, data: { content: "Unsupported interaction.", flags: EPHEMERAL } };
}

// ── autocomplete ─────────────────────────────────────────────────────────
function autocomplete(it, { R }) {
  const focused = (it.data.options || []).find((o) => o.focused)
    || (it.data.options || []).flatMap((o) => o.options || []).find((o) => o.focused);
  const q = focused ? String(focused.value || "") : "";
  if (focused && focused.name === "set") {
    const choices = R.suggestSets(q, 25).map((si) => ({ name: setChoiceLabel(R.sets[si]).slice(0, 100), value: R.sets[si].n.slice(0, 100) }));
    return { type: R_.AUTOCOMPLETE, data: { choices } };
  }
  const choices = R.suggest(q, 25).map((s) => ({ name: s.label.slice(0, 100), value: s.value.slice(0, 100) }));
  return { type: R_.AUTOCOMPLETE, data: { choices } };
}

// ── commands ─────────────────────────────────────────────────────────────
function command(it, deps) {
  const d = it.data;
  if (d.type === 3) return deferred(it, deps, false, () => priceCheck(it, deps));
  const o = d.options || [];
  const priv = !!optVal(o, "private", false);
  switch (d.name) {
    case "card": return deferred(it, deps, priv, () => lookup(String(optVal(o, "name", "")), "card", D.DEFAULT_RANGE, deps));
    case "price": return deferred(it, deps, priv, () => lookup(String(optVal(o, "name", "")), "chart", String(optVal(o, "range", D.DEFAULT_RANGE)), deps));
    case "movers": return deferred(it, deps, priv, () => movers(o, deps));
    case "events": return deferred(it, deps, priv, () => events(o, deps));
    case "calendar": return deferred(it, deps, priv, () => calendar(deps));
    case "meta": return deferred(it, deps, priv, () => meta(deps));
    case "new": return deferred(it, deps, priv, () => newReply(deps));
    case "help": return { type: R_.MESSAGE, data: { ...E.helpMessage(deps.commandIds), flags: EPHEMERAL, allowed_mentions: QUIET } };
    // A decklist has line breaks, which a slash-command option cannot hold —
    // so /deck opens a text box instead.
    case "deck": return { type: R_.MODAL, data: E.deckModal(priv) };
    // Both sides typed inline ("give: 2 mowgli, $20") answer at once; anything
    // less opens the box, holding whatever was typed. Prices come from the
    // index, so there is nothing to wait for.
    case "trade": {
      const give = String(optVal(o, "give", "")).trim(), get = String(optVal(o, "get", "")).trim();
      if (!give || !get) return { type: R_.MODAL, data: tradeModal(priv, give, get) };
      return { type: R_.MESSAGE, data: { ...tradeReply(give, get, "you", deps), allowed_mentions: QUIET, ...(priv ? { flags: EPHEMERAL } : {}) } };
    }
    case "reports": return deferred(it, deps, true, () => reports(it, deps));
    // Both answer from the index alone, so at once.
    case "set": return instant(setReply(String(optVal(o, "set", "")), deps), priv);
    case "open": return instant(packReply(String(optVal(o, "set", "")), optVal(o, "box", false) ? 24 : 1, it, deps), priv);
    default: return { type: R_.MESSAGE, data: { content: "Unknown command.", flags: EPHEMERAL } };
  }
}

const instant = (payload, ephemeral) => ({ type: R_.MESSAGE, data: { ...payload, allowed_mentions: QUIET, ...(ephemeral ? { flags: EPHEMERAL } : {}) } });

// Answer "thinking…" now; build the real message after.
function deferred(it, deps, ephemeral, build) {
  deps.waitUntil((async () => {
    let payload;
    try { payload = await build(); }
    catch (e) {
      deps.log && deps.log("interaction failed", e && e.stack || e);
      payload = { content: "Something went wrong looking that up — try again in a moment.", embeds: [], components: [] };
    }
    await patchOriginal(it, deps, payload);
  })());
  return { type: R_.DEFERRED, data: ephemeral ? { flags: EPHEMERAL } : {} };
}

function deferredUpdate(it, deps, build) {
  deps.waitUntil((async () => {
    let payload;
    try { payload = await build(); }
    catch (e) {
      deps.log && deps.log("component failed", e && e.stack || e);
      return;   // leave the message as it was rather than replace it with an error
    }
    await patchOriginal(it, deps, payload, { update: true });
  })());
  return { type: R_.DEFERRED_UPDATE };
}

const webhookUrl = (it, deps) => `${deps.discordApi || DISCORD_API}/webhooks/${deps.appId || it.application_id}/${it.token}`;

async function patchOriginal(it, deps, payload, { update = false } = {}) {
  const send = (method, url, body, files) => {
    const json = JSON.stringify({ allowed_mentions: QUIET, ...body });
    if (!files || !files.length) return deps.fetch(url, { method, headers: { "Content-Type": "application/json" }, body: json });
    const form = new FormData();
    form.append("payload_json", json);
    files.forEach((f, i) => form.append(`files[${i}]`, new Blob([f.data], { type: f.type }), f.name));
    return deps.fetch(url, { method, body: form });
  };
  const orig = webhookUrl(it, deps) + "/messages/@original";
  // `attachments: []` on every plain edit: a card reply that switches from
  // its uploaded picture to the chart would otherwise keep the old file,
  // shown loose under the embed. A payload's own list wins.
  const plainBody = { attachments: [], ...payload };
  const up = await withUploads(payload, deps).catch((e) => { deps.log && deps.log("upload prep failed", e && e.message); return null; });
  let r = await send("PATCH", orig, up ? up.body : plainBody, up && up.files);
  if (r.ok) return;
  if (deps.log) deps.log("patch failed", r.status, (await r.text().catch(() => "")).slice(0, 800));
  // The upload is the new risk, so if it was refused for any reason the reply
  // goes again exactly as it was before uploads existed: the picture as a link.
  if (up) {
    r = await send("PATCH", orig, plainBody);
    if (r.ok) return;
    if (deps.log) deps.log("patch without upload failed", r.status);
  }
  // ⚠ A 400 is Discord refusing the SHAPE of the reply (a limit, a field it
  // won't take). Left there, the person who asked sees "thinking…" forever —
  // the worst answer the bot can give. So the same content goes again as
  // plain text, which has one limit (2000 characters) and nothing to refuse.
  // A button's update that fails leaves the old message standing; the plain
  // version then goes to the clicker alone, as a private follow-up.
  if (r.status !== 400) return;
  const plain = plainFallback(payload);
  const r2 = update
    ? await send("POST", webhookUrl(it, deps), { ...plain, flags: EPHEMERAL })
    : await send("PATCH", orig, { attachments: [], ...plain });
  if (!r2.ok && deps.log) deps.log("fallback failed", r2.status);
}

// ── pictures this Worker hosts go WITH the reply ─────────────────────────
// ⚠ Discord dropped the site tile from the FIRST edit of a "thinking…" reply
// and kept it on every later edit of the same message: the Broken Pod /card of
// 2026-09-29 was stored with no image at all, while pressing any button (an
// ordinary edit carrying the same URL) brought it back. Pictures from
// TCGplayer's and Supabase's CDNs in the same spot were fine (Rivera Family
// Photo, 9/28). So a picture that is one of our OWN files — the tile, or baked
// art — is read from the asset store and uploaded with the edit, and the embed
// points at the attachment. Discord then has the bytes before the message
// exists and never has to fetch anything.
//
// ⚠ CHARTS TOO (2026-09-29): linked, the price chart went missing the same way
// after the Price chart button, until a few more clicks brought it back. The
// chart is drawn here, by the very route Discord would have fetched
// (chartResponse, ~5 ms), and uploaded. It also stops Discord downloading
// every chart three times, each one a fresh database read and redraw.
export const OWN_FILE = /^\/(?:tile|art)\/[a-z0-9_.-]+\.(webp|png|jpe?g|gif)$/i;
const CHART_PATH = /^\/chart\/[pgr]\/[^?#]+\.png$/;
const MIME = { webp: "image/webp", png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", gif: "image/gif" };
const ourPath = (url, origin) => (url && origin && String(url).startsWith(origin + "/") ? String(url).slice(origin.length) : null);
export function ownFilePath(url, origin) {
  const p = ourPath(url, origin);
  if (!p) return null;
  const path = p.split(/[?#]/)[0];
  return OWN_FILE.test(path) && !path.includes("..") ? path : null;
}
// The chart's full URL (its query carries the date and any eBay overlay), or null.
export function ownChartUrl(url, origin) {
  const p = ourPath(url, origin);
  return p && CHART_PATH.test(p.split(/[?#]/)[0]) ? new URL(String(url)) : null;
}

// {body, files} for a multipart edit, or null when there is nothing to upload.
// Anything that can't be produced here (a file the asset store lacks, a chart
// whose database read fails) keeps its link, which is how it worked before.
export async function withUploads(payload, deps) {
  if (!deps.origin || !payload || !Array.isArray(payload.embeds)) return null;
  const refs = [];
  payload.embeds.forEach((e, ei) => {
    for (const slot of ["image", "thumbnail"]) {
      const url = e && e[slot] && e[slot].url;
      if (refs.length >= 10) break;
      const path = deps.assets ? ownFilePath(url, deps.origin) : null;
      if (path) { refs.push({ ei, slot, path }); continue; }
      const chart = deps.db ? ownChartUrl(url, deps.origin) : null;
      if (chart) refs.push({ ei, slot, chart });
    }
  });
  if (!refs.length) return null;
  const got = await Promise.all(refs.map(async (ref) => {
    if (ref.chart) {
      const r = await chartResponse(ref.chart, deps.db).catch((e) => { deps.log && deps.log("chart upload failed", e && e.message); return null; });
      if (!r || !r.ok) return null;
      return { ...ref, data: await r.arrayBuffer(), type: "image/png", ext: "png" };
    }
    const r = await deps.assets.fetch(new Request(deps.origin + ref.path)).catch(() => null);
    if (!r || !r.ok) return null;
    const ext = ref.path.split(".").pop().toLowerCase();
    return { ...ref, data: await r.arrayBuffer(), type: MIME[ext] || "application/octet-stream", ext };
  }));
  const files = [];
  const embeds = payload.embeds.map((e) => ({ ...e }));
  for (const g of got) {
    if (!g) continue;
    const name = `packs-ink-${files.length}.${g.ext}`;
    files.push({ name, type: g.type, data: g.data });
    embeds[g.ei][g.slot] = { url: "attachment://" + name };
  }
  if (!files.length) return null;
  return { body: { ...payload, embeds, attachments: files.map((f, i) => ({ id: i, filename: f.name })) }, files };
}

// A reply reduced to text: every embed's title, lines and fields, no
// components. Markdown links survive (message content takes them too).
export function plainFallback(payload) {
  const out = [];
  if (payload && payload.content) out.push(String(payload.content));
  for (const e of (payload && payload.embeds) || []) {
    if (e.title) out.push("**" + e.title + "**" + (e.url && /^https:\/\//.test(e.url) ? ` — <${e.url}>` : ""));
    if (e.description) out.push(e.description);
    for (const f of e.fields || []) out.push(`**${f.name}** ${String(f.value).replace(/\n/g, " · ")}`);
    if (e.footer && e.footer.text) out.push("-# " + e.footer.text);
  }
  let text = out.join("\n").trim() || "Here's what I found, but Discord wouldn't show it — try again in a moment.";
  if (text.length > 2000) text = text.slice(0, 1990).replace(/\n[^\n]*$/, "") + "\n…";
  return { content: text, embeds: [], components: [] };
}

// ── /card and /price ─────────────────────────────────────────────────────
export async function lookup(query, view, range, deps) {
  const res = deps.R.resolve(query);
  if (res.kind === "none") return E.notFoundMessage(deps.R, res, query, deps.commandIds);
  if (!D.RANGES[range]) range = D.DEFAULT_RANGE;
  return res.kind === "sealed"
    ? sealedPayload(res, { view, range }, deps)
    : cardPayload(res, { view, range, query }, deps);
}

export async function cardPayload(res, { view, range, query }, deps) {
  const { R, db } = deps;
  const c = res.card, p = res.printing, f = p.f[res.fi] || p.f[0];
  const pid = f && f[1];
  const printingStr = (f && f[2]) || D.FIN_PRINTING[f && f[0]] || "Normal";
  const gt = D.gradedTarget(p, f && f[0]);
  const wantGrade = res.dims && res.dims.grade ? res.dims.grade : null;
  const settle = (pr) => pr.then((v) => v, (e) => { deps.log && deps.log("fetch failed", e && e.message); return null; });
  const [price, gradedAll, rawRows] = await Promise.all([
    pid && !(f && f[6]) ? settle(D.priceHistory(db, pid, printingStr).then((rows) => D.priceSummary(rows, deps.index.priceDate))) : null,
    (c.gs > 0 || p.g > 0 || wantGrade) ? settle(D.gradedRollup(db, gt.cardId)) : null,
    p.raw ? settle(D.rawRollup(db, gt.cardId)) : null,
  ]);
  const single = (gradedAll || []).some((r) => !r.printing);
  const rawSingle = (rawRows || []).some((r) => !r.printing);
  const forPrinting = D.gradedRowsFor(gradedAll || [], gt.bucket);
  let graded = D.topGradedTiers(forPrinting, 6);
  let grade = null;
  if (wantGrade) {
    const hit = forPrinting.find((r) => r.grader === wantGrade.grader && String(r.grade) === String(wantGrade.grade));
    if (hit) {
      grade = { grader: hit.grader, grade: String(hit.grade) };
      graded = [hit, ...graded.filter((r) => r !== hit)].slice(0, 6);
    } else {
      res.notes = [...(res.notes || []), `No ${wantGrade.grader} ${wantGrade.grade} sales on record for this printing.`];
    }
  }
  return E.cardMessage({
    R, res, price, graded, view: grade && view === "chart" ? "graded" : view, range, query,
    raw: D.rawRowFor(rawRows || [], printingStr),
    rawTarget: { cardId: gt.cardId, bucket: rawSingle ? "" : gt.bucket },
    grade, gradedTarget: { cardId: gt.cardId, bucket: single ? "" : gt.bucket },
    origin: deps.origin, inkColors: deps.index.inkColors, playDecks: deps.index.playDecks,
    priceDate: deps.index.priceDate,
  });
}

async function sealedPayload(res, { view, range }, deps) {
  const price = await D.priceHistory(deps.db, res.item.pid, "Normal").then((rows) => D.priceSummary(rows, deps.index.priceDate), () => null);
  return E.sealedMessage({ R: deps.R, res, price, view, range, origin: deps.origin });
}

// ── /trade ───────────────────────────────────────────────────────────────
export function tradeReply(give, get, mode, deps) {
  const t = priceTrade(deps.R, give, get);
  const names = mode === "post" ? ["Has", "Wants"] : ["You give", "You get"];
  return tradeMessage(t, { mode, priceDate: deps.index.priceDate, siteUrl: tradeSiteUrl(deps.R, t, names) });
}

// ── "Price check" on a message ───────────────────────────────────────────
// Searching free text for card names is read only this far: every window of
// it is a candidate name, and the free plan gives a request 10 ms of CPU. A
// trade post or a decklist is parsed line by line under its own caps, so it
// gets the whole message.
const PRICE_CHECK_MAX_CHARS = 1200;
async function priceCheck(it, deps) {
  const msg = it.data.resolved && it.data.resolved.messages && it.data.resolved.messages[it.data.target_id];
  const text = [msg && msg.content, ...((msg && msg.embeds) || []).map((e) => [e.title, e.description].filter(Boolean).join(" "))]
    .filter(Boolean).join("\n").slice(0, 6000);
  // A trade post ("H: … W: …") is priced as a TRADE: both sides, compared.
  const post = parseTradePost(text);
  if (post) {
    const m = tradeReply(post.has, post.wants, "post", deps);
    if (m.embeds[0].fields.every((f) => !/\*nothing I recognised\*/.test(f.value))) return m;
  }
  // A posted decklist is priced as a DECK, not as the first three names in it.
  if (looksLikeDeck(text)) {
    return E.deckMessage({ result: priceDeck(deps.R, parseDeckList(text)), priceDate: deps.index.priceDate, tcgNames: E.tcgNameMap(deps.index.tcgNames) });
  }
  const found = deps.R.findInText(text.slice(0, PRICE_CHECK_MAX_CHARS), 3).filter((r) => r.kind === "card" || r.kind === "sealed");
  if (!found.length) {
    return { content: "No Lorcana cards in that message that I can recognise. Try `/price` with the name.", embeds: [], components: [] };
  }
  const embeds = [];
  for (const res of found) {
    if (res.kind === "sealed") {
      const m = await sealedPayload(res, { view: "card", range: D.DEFAULT_RANGE }, deps);
      embeds.push({ ...m.embeds[0], image: undefined, ...(res.item.img ? { thumbnail: { url: res.item.img } } : {}) });
      continue;
    }
    const f = res.printing.f[res.fi] || res.printing.f[0];
    const price = f && f[1] && !f[6]
      ? await D.priceHistory(deps.db, f[1], f[2] || "Normal").then((rows) => D.priceSummary(rows, deps.index.priceDate), () => null) : null;
    embeds.push(E.compactCardEmbed({ R: deps.R, res, price, inkColors: deps.index.inkColors, origin: deps.origin }));
  }
  const options = found.map((res) => res.kind === "sealed"
    ? { label: res.item.n.slice(0, 100), value: deps.R.sealedKey(res.item) }
    : { label: res.card.n.slice(0, 100), value: deps.R.cardKey(res.printing, res.fi) });
  return E.priceCheckMessage({ embeds, options, range: D.DEFAULT_RANGE });
}

// ── /deck's text box ─────────────────────────────────────────────────────
// Everything it needs is in the card index, so it answers at once.
// Rows come back as sent (action rows); a Label wrapper holds one `component`.
const modalValue = (it, id) => {
  const c = (it.data.components || []).flatMap((r) => r.components || (r.component ? [r.component] : [])).find((x) => x.custom_id === id);
  return c && c.value != null ? String(c.value) : "";
};
function modalSubmit(it, deps) {
  const tr = /^trade\|([p-])$/.exec(it.data.custom_id || "");
  if (tr) {
    const msg = tradeReply(modalValue(it, "give"), modalValue(it, "get"), "you", deps);
    return { type: R_.MESSAGE, data: { ...msg, allowed_mentions: QUIET, ...(tr[1] === "p" ? { flags: EPHEMERAL } : {}) } };
  }
  const m = /^deck\|([p-])$/.exec(it.data.custom_id || "");
  if (!m) return { type: R_.MESSAGE, data: { content: "That form has expired.", flags: EPHEMERAL } };
  const entries = parseDeckList(modalValue(it, "list"));
  if (!entries.length) {
    return { type: R_.MESSAGE, data: { flags: EPHEMERAL, allowed_mentions: QUIET,
      content: "That doesn't look like a decklist — one card per line with its count, like `4 Mowgli - Man Cub`." } };
  }
  const msg = E.deckMessage({ result: priceDeck(deps.R, entries), priceDate: deps.index.priceDate, tcgNames: E.tcgNameMap(deps.index.tcgNames) });
  return { type: R_.MESSAGE, data: { ...msg, allowed_mentions: QUIET, ...(m[1] === "p" ? { flags: EPHEMERAL } : {}) } };
}

// ── buttons + menus ──────────────────────────────────────────────────────
function component(it, deps) {
  const id = it.data.custom_id;
  const mv = E.parseMoversId(id);
  if (mv) {
    if (id.startsWith("m|g|")) {
      const g = (it.data.values || [])[0];
      if (!D.MOVER_GROUPS[g]) return { type: R_.DEFERRED_UPDATE };
      mv.group = g;
    }
    return deferredUpdate(it, deps, () => moversBoard(mv, deps));
  }
  // /help's "Try it" buttons: the real reply, shown only to whoever asked.
  const tryWhat = E.parseHelpTryId(id);
  if (tryWhat) return helpTry(tryWhat, it, deps);
  // "Open another pack" / "Open a box": a NEW message each time, so every
  // opening stands — private when the one it came from was.
  const pk2 = parsePackId(id);
  if (pk2) {
    const eph = it.message && (Number(it.message.flags) & EPHEMERAL);
    const set = deps.R.sets[pk2.si];
    if (!set) return { type: R_.MESSAGE, data: { content: "That set is gone from the catalog.", flags: EPHEMERAL } };
    return instant(packReply(set.n, pk2.n, it, deps), eph);
  }
  const cal = E.parseCalendarId(id);
  if (cal) {
    if (id.startsWith("cl|r|")) {
      const r = (it.data.values || [])[0];
      if (!(r === "all" || CALENDAR_REGIONS.some((x) => x.key === r))) return { type: R_.DEFERRED_UPDATE };
      cal.region = r;
    }
    return deferredUpdate(it, deps, () => calendar(deps, cal.kind, cal.region));
  }
  const ev = E.parseEventsId(id);
  if (ev) {
    const place = { lat: ev.lat, lng: ev.lng, city: ev.label };
    return deferredUpdate(it, deps, () => eventsBoard({ place, radius: ev.radius, kind: ev.kind, query: ev.label }, deps));
  }
  const rg = E.parseRangeId(id);
  if (rg) return deferredUpdate(it, deps, () => byKey(rg.key, rg.view, rg.range, deps, rg.grade));
  const pk = E.parsePickId(id);
  if (pk) {
    const key = (it.data.values || [])[0];
    if (!key) return { type: R_.DEFERRED_UPDATE };
    return deferredUpdate(it, deps, () => byKey(key, pk.view === "graded" ? "chart" : pk.view, pk.range, deps));
  }
  // "Look at a card" from a trade, deck, set or movers list: a NEW reply that
  // only the person who asked sees, so the list stays put for everyone else.
  const op = E.parseOpenId(id);
  if (op) {
    const key = (it.data.values || [])[0];
    if (!key) return { type: R_.DEFERRED_UPDATE };
    return deferred(it, deps, true, () => byKey(key, op.view, D.DEFAULT_RANGE, deps));
  }
  return { type: R_.MESSAGE, data: { content: "That button has expired.", flags: EPHEMERAL } };
}

async function byKey(key, view, range, deps, grade) {
  const res = deps.R.resolve(key);
  if (res.kind === "none") return E.notFoundMessage(deps.R, res, key);
  if (res.kind === "sealed") return sealedPayload(res, { view: view === "graded" ? "chart" : view, range }, deps);
  // A graded reply's buttons carry the grade in their custom_id; put it back
  // where cardPayload looks for a grade the user asked for.
  if (grade) res.dims = { ...(res.dims || {}), grade };
  return cardPayload(res, { view: view === "graded" ? "chart" : view, range }, deps);
}

// ── /movers ──────────────────────────────────────────────────────────────
async function movers(o, deps) {
  return moversBoard({
    win: String(optVal(o, "window", "1d")),
    dir: String(optVal(o, "direction", "up")),
    group: String(optVal(o, "rarity", "all")),
    basis: String(optVal(o, "basis", "market")),
    min: Math.round(Math.min(10000, Math.max(0, Number(optVal(o, "min_price", 5)) || 0)) * 100) / 100,
  }, deps);
}
// One board for the command and every button on it.
async function moversBoard(s, deps) {
  if (!D.MOVER_WINDOWS[s.win]) s.win = "1d";
  if (!D.MOVER_GROUPS[s.group]) s.group = "all";
  const result = D.MOVER_GROUPS[s.group].sealed
    ? D.sealedMovers(deps.index, { ...s, limit: 10 })
    : await D.fetchMovers(deps.db, { win: s.win, dir: s.dir, group: s.group, basis: s.basis, min: s.min, limit: 10 });
  return E.moversMessage({ result, ...s, R: deps.R });
}

// ── /events ──────────────────────────────────────────────────────────────
async function events(o, deps) {
  const near = String(optVal(o, "near", "")).trim();
  const radius = Math.min(250, Math.max(5, Number(optVal(o, "radius", 50)) || 50));
  const kind = D.EVENT_KINDS.includes(String(optVal(o, "kind", "all"))) ? String(optVal(o, "kind", "all")) : "all";
  const place = await D.resolvePlace(deps.db, near);
  if (!place) return { content: `Couldn't place “${near.slice(0, 60)}”. Try a postal code, or a town name.`, embeds: [], components: [] };
  return eventsBoard({ place, radius, kind, query: near }, deps);
}
async function eventsBoard({ place, radius, kind, query }, deps) {
  const byKind = await D.nearbyByKind(deps.db, place, { radius, kind });
  return E.eventsMessage({ place, byKind, radius, kind, query });
}

// ── /new ─────────────────────────────────────────────────────────────────
// The reel from the index plus whatever reached the catalog since it was
// built. If that read fails the reply comes from the index alone — a day
// behind at worst, never nothing.
async function newReply(deps) {
  const now = Date.now();
  const fresh = await freshRevealRows(deps.db, deps.R, deps.index, now)
    .catch((e) => { deps.log && deps.log("new: fresh reveals failed", e && e.message); return []; });
  return newCardsMessage(deps.R, deps.index, newCards(deps.R, deps.index, now, fresh), { origin: deps.origin, now });
}

// ── /meta ────────────────────────────────────────────────────────────────
async function meta(deps) {
  const results = await D.recentResults(deps.db, { events: 3, places: 4 }).catch((e) => { deps.log && deps.log("results failed", e && e.message); return []; });
  return E.metaMessage({ R: deps.R, index: deps.index, results });
}

// ── /calendar ────────────────────────────────────────────────────────────
async function calendar(deps, kind = "all", region = "all") {
  const all = await D.calendarEvents(deps.db);
  return E.calendarMessage({ events: D.upcomingFiltered(all, { kind, region, n: 12 }), kind, region, regions: CALENDAR_REGIONS });
}

// ── /reports (server managers) ───────────────────────────────────────────
// The report itself is the daily digest (scripts/discord_digest.py's layout):
// NM Market moves, cards priced $5+, led by "fell AND at a multi-month low".
// The Worker only records WHERE to post it; scripts/discord_reports.py posts.
const CADENCE = {
  daily: "every day once the day's prices are in (about 4:20 PM US Central)",
  weekly: "every Monday once the day's prices are in",
};
async function reports(it, deps) {
  if (!it.guild_id) return { content: "Reports post into a server channel — run this in a server.", embeds: [], components: [] };
  const perms = BigInt(it.member && it.member.permissions ? it.member.permissions : "0");
  if (!(perms & MANAGE_GUILD)) return { content: "Only people who can manage this server can set up reports.", embeds: [], components: [] };
  if (!deps.db.hasService) return { content: "Reports aren't switched on for this bot yet.", embeds: [], components: [] };
  const sub = (it.data.options || [])[0] || {};
  const channel = String(optVal(sub.options, "channel", it.channel_id));
  const table = "discord_report_subscriptions";
  if (sub.name === "status") {
    const rows = await deps.db.getService(table, { select: "channel_id,cadence,last_posted_on,last_error", guild_id: "eq." + it.guild_id, order: "channel_id.asc,cadence.asc" });
    return { content: rows.length
      ? rows.map((r) => `<#${r.channel_id}> — ${r.cadence}` +
          (r.last_posted_on ? `, last posted ${E.shortDate(r.last_posted_on)}` : ", nothing posted yet") +
          (r.last_error ? ` — ⚠ ${String(r.last_error).slice(0, 120)}` : "")).join("\n")
      : "No reports set up in this server.", embeds: [], components: [] };
  }
  if (sub.name === "off") {
    const gone = await deps.db.del(table, { guild_id: "eq." + it.guild_id, channel_id: "eq." + channel });
    return { content: gone && gone.length ? `Stopped the reports in <#${channel}>.` : `There were no reports in <#${channel}>.`, embeds: [], components: [] };
  }
  if (!CADENCE[sub.name]) return { content: "Pick daily, weekly, off or status.", embeds: [], components: [] };
  await deps.db.upsert(table, [{
    guild_id: String(it.guild_id), channel_id: channel, cadence: sub.name,
    created_by: String((it.member && it.member.user && it.member.user.id) || ""),
    updated_at: new Date().toISOString(), last_error: null,
  }], "guild_id,channel_id,cadence");
  return { content: `Done — a ${sub.name} movers report will post in <#${channel}> ${CADENCE[sub.name]}. ` +
    "The bot needs to be in this server with permission to send messages and embed links in that channel.", embeds: [], components: [] };
}

// ── /set and /open ───────────────────────────────────────────────────────
const setChoiceLabel = (s) => [s.n, s.main ? `Set ${s.main}` : null, s.rel && s.rel.lgs ? E.shortDate(s.rel.lgs) : null].filter(Boolean).join(" · ");
// No name: the newest booster set — for /open the newest one that is OUT, since
// a pack from a set with no prices yet is worth "$0.00" and says nothing.
function pickSet(R, index, name, { released = false } = {}) {
  if (name) return R.resolveSet(name);
  const today = new Date().toISOString().slice(0, 10);
  const mains = R.sets.map((s, i) => i).filter((i) => R.sets[i].main).sort((a, b) => R.sets[b].main - R.sets[a].main);
  return (released ? mains.find((i) => !(R.sets[i].rel && R.sets[i].rel.lgs > today)) : mains[0]) ?? -1;
}
const noSet = (name) => ({ content: `No set called “${String(name).slice(0, 60)}”. Try a name or a number — \`hyperia city\`, \`azurite\`, \`set 5\`.`, embeds: [], components: [] });

export function setReply(name, deps) {
  const si = pickSet(deps.R, deps.index, name);
  if (si < 0) return noSet(name);
  return setMessage(setOverview(deps.R, deps.index, si), { origin: deps.origin });
}

export function packReply(name, n, it, deps) {
  const si = pickSet(deps.R, deps.index, name, { released: true });
  if (si < 0) return noSet(name);
  const set = deps.R.sets[si];
  if (!set.main) return { content: `${set.n} isn't sold in booster packs — try a main set, like \`${deps.index.newestMain}\`.`, embeds: [], components: [] };
  const u = (it && ((it.member && it.member.user) || it.user)) || {};
  const who = String(u.global_name || u.username || "").slice(0, 32).replace(/[*_~`|>\\]/g, "\\$&");
  return packMessage(deps.R, deps.index, si, openPacks(deps.R, si, n), { origin: deps.origin, who });
}

// ── /help's examples ─────────────────────────────────────────────────────
const TRY_TRADE = { give: "4 mowgli, 2 be prepared, $10", get: "elsa spirit of winter foil" };
function helpTry(what, it, deps) {
  const note = (text, m) => ({ ...m, content: text });
  if (what === "card") return deferred(it, deps, true, async () => note("Example: `/card mowgli`", await lookup("mowgli", "card", D.DEFAULT_RANGE, deps)));
  if (what === "movers") return deferred(it, deps, true, async () => note("Example: `/movers` — the buttons change the window and the cards", await moversBoard({ win: "1d", dir: "up", group: "all", basis: "market", min: 5 }, deps)));
  if (what === "trade") return instant(note(`Example: \`/trade give: ${TRY_TRADE.give} get: ${TRY_TRADE.get}\``, tradeReply(TRY_TRADE.give, TRY_TRADE.get, "you", deps)), true);
  if (what === "open") return instant(note("Example: `/open` — add `box: True` for a whole box", packReply("", 1, it, deps)), true);
  return instant(note("Example: `/set`", setReply("", deps)), true);
}
