// interactions.js — one Discord interaction in, one response out.
//
// Discord gives an interaction 3 seconds. Anything that touches the database
// is therefore DEFERRED: answer "thinking…" (type 5, or 6 for a button) at
// once, do the work in waitUntil, then PATCH the original message. Only the
// things that are pure and local — autocomplete, /help — answer directly.
import * as E from "./embeds.js";
import * as D from "./data.js";
import { parseDeckList, looksLikeDeck, priceDeck } from "./deck.js";

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
    case "help": return { type: R_.MESSAGE, data: { ...E.helpMessage(), flags: EPHEMERAL, allowed_mentions: QUIET } };
    // A decklist has line breaks, which a slash-command option cannot hold —
    // so /deck opens a text box instead.
    case "deck": return { type: R_.MODAL, data: E.deckModal(priv) };
    case "reports": return deferred(it, deps, true, () => reports(it, deps));
    default: return { type: R_.MESSAGE, data: { content: "Unknown command.", flags: EPHEMERAL } };
  }
}

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
    await patchOriginal(it, deps, payload);
  })());
  return { type: R_.DEFERRED_UPDATE };
}

async function patchOriginal(it, deps, payload) {
  const url = `${deps.discordApi || DISCORD_API}/webhooks/${deps.appId || it.application_id}/${it.token}/messages/@original`;
  const r = await deps.fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ allowed_mentions: QUIET, ...payload }),
  });
  if (!r.ok && deps.log) deps.log("patch failed", r.status, await r.text().catch(() => ""));
}

// ── /card and /price ─────────────────────────────────────────────────────
export async function lookup(query, view, range, deps) {
  const res = deps.R.resolve(query);
  if (res.kind === "none") return E.notFoundMessage(deps.R, res, query);
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
    origin: deps.origin, inkColors: deps.index.inkColors,
  });
}

async function sealedPayload(res, { view, range }, deps) {
  const price = await D.priceHistory(deps.db, res.item.pid, "Normal").then((rows) => D.priceSummary(rows, deps.index.priceDate), () => null);
  return E.sealedMessage({ R: deps.R, res, price, view, range, origin: deps.origin });
}

// ── "Price check" on a message ───────────────────────────────────────────
async function priceCheck(it, deps) {
  const msg = it.data.resolved && it.data.resolved.messages && it.data.resolved.messages[it.data.target_id];
  const text = [msg && msg.content, ...((msg && msg.embeds) || []).map((e) => [e.title, e.description].filter(Boolean).join(" "))]
    .filter(Boolean).join("\n");
  // A posted decklist is priced as a DECK, not as the first three names in it.
  if (looksLikeDeck(text)) {
    return E.deckMessage({ result: priceDeck(deps.R, parseDeckList(text)), priceDate: deps.index.priceDate });
  }
  const found = deps.R.findInText(text, 3).filter((r) => r.kind === "card" || r.kind === "sealed");
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
function modalSubmit(it, deps) {
  const m = /^deck\|([p-])$/.exec(it.data.custom_id || "");
  if (!m) return { type: R_.MESSAGE, data: { content: "That form has expired.", flags: EPHEMERAL } };
  // Rows come back as sent (action rows); a Label wrapper holds one `component`.
  const input = (it.data.components || []).flatMap((r) => r.components || (r.component ? [r.component] : [])).find((c) => c.custom_id === "list");
  const entries = parseDeckList(input ? input.value : "");
  if (!entries.length) {
    return { type: R_.MESSAGE, data: { flags: EPHEMERAL, allowed_mentions: QUIET,
      content: "That doesn't look like a decklist — one card per line with its count, like `4 Mowgli - Man Cub`." } };
  }
  const msg = E.deckMessage({ result: priceDeck(deps.R, entries), priceDate: deps.index.priceDate });
  return { type: R_.MESSAGE, data: { ...msg, allowed_mentions: QUIET, ...(m[1] === "p" ? { flags: EPHEMERAL } : {}) } };
}

// ── buttons + menus ──────────────────────────────────────────────────────
function component(it, deps) {
  const id = it.data.custom_id;
  const rg = E.parseRangeId(id);
  if (rg) return deferredUpdate(it, deps, () => byKey(rg.key, rg.view, rg.range, deps, rg.grade));
  const pk = E.parsePickId(id);
  if (pk) {
    const key = (it.data.values || [])[0];
    if (!key) return { type: R_.DEFERRED_UPDATE };
    return deferredUpdate(it, deps, () => byKey(key, pk.view === "graded" ? "chart" : pk.view, pk.range, deps));
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
  const win = String(optVal(o, "window", "1d"));
  const dir = String(optVal(o, "direction", "up"));
  const group = String(optVal(o, "rarity", "all"));
  const basis = String(optVal(o, "basis", "market"));
  const min = Math.max(0, Number(optVal(o, "min_price", 5)) || 0);
  const result = await D.fetchMovers(deps.db, { win, dir, group, basis, min, limit: 10 });
  return E.moversMessage({ result, win, dir, group, basis, min, R: deps.R });
}

// ── /events ──────────────────────────────────────────────────────────────
async function events(o, deps) {
  const near = String(optVal(o, "near", "")).trim();
  const radius = Math.min(250, Math.max(5, Number(optVal(o, "radius", 50)) || 50));
  const kind = String(optVal(o, "kind", "all"));
  const place = await D.resolvePlace(deps.db, near);
  if (!place) return { content: `Couldn't place “${near.slice(0, 60)}”. Try a postal code, or a town name.`, embeds: [], components: [] };
  const series = await D.nearbyEvents(deps.db, place, { radius, kind });
  return E.eventsMessage({ place, series, radius, kind });
}

// ── /calendar ────────────────────────────────────────────────────────────
async function calendar(deps) {
  const all = await D.calendarEvents(deps.db);
  return E.calendarMessage({ events: D.upcoming(all, 10) });
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
