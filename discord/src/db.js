// db.js — the few Supabase reads (and one write) the bot needs, over plain
// PostgREST. The anon key is the site's publishable key: everything the bot
// READS is already public on packs.ink. The service key is used for exactly
// one thing, the report subscriptions table, which has no public policy.
//
// ⚠ No custom User-Agent. The edge in front of PostgREST answers 401 to one
// (measured: bare request 200, same request + a UA string 401, valid key both
// times) — the same trap scripts/watch_calendar_sources.py documents.

export const DEFAULT_SUPABASE_URL = "https://umwqowkiatjjltologrd.supabase.co";
export const DEFAULT_ANON_KEY = "sb_publishable_B2qq0Dsfij-7X2CZSxl2uQ_7PWc6Ob0";

export class DbError extends Error {
  constructor(message, status, code) { super(message); this.status = status; this.code = code; }
}

export function makeDb(env = {}, fetchImpl = (...a) => fetch(...a)) {
  const base = String(env.SUPABASE_URL || DEFAULT_SUPABASE_URL).replace(/\/+$/, "");
  const anon = env.SUPABASE_ANON_KEY || DEFAULT_ANON_KEY;
  const service = env.SUPABASE_SERVICE_KEY || null;

  async function call(path, { key = anon, method = "GET", body, headers = {}, timeout = 6000 } = {}) {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), timeout);
    try {
      const r = await fetchImpl(base + path, {
        method,
        headers: {
          apikey: key, Authorization: "Bearer " + key, Accept: "application/json",
          ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
          ...headers,
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: ctl.signal,
      });
      const text = await r.text();
      let data = null;
      try { data = text ? JSON.parse(text) : null; } catch { data = text; }
      if (!r.ok) {
        const code = data && data.code;
        throw new DbError(`${method} ${path.split("?")[0]} -> ${r.status}${code ? " " + code : ""}`, r.status, code);
      }
      return data;
    } finally {
      clearTimeout(t);
    }
  }
  const qs = (params) => {
    const u = new URLSearchParams();
    for (const [k, v] of Object.entries(params || {})) if (v !== undefined && v !== null) u.append(k, String(v));
    return u.toString();
  };

  // Every page of a read. PostgREST caps a response at 1000 rows, and a card's
  // whole price history is already close to that; `order` is required or the
  // pages overlap (the sbFetchAll rule).
  async function all(table, params, { key, pageSize = 1000, maxRows = 20000 } = {}) {
    const out = [];
    for (let from = 0; from < maxRows; from += pageSize) {
      const rows = await call(`/rest/v1/${table}?${qs(params)}`, {
        key, headers: { Range: `${from}-${from + pageSize - 1}`, "Range-Unit": "items" },
      });
      if (!Array.isArray(rows)) break;
      out.push(...rows);
      if (rows.length < pageSize) break;
    }
    return out;
  }
  const get = (table, params, opts) => call(`/rest/v1/${table}?${qs(params)}`, opts);
  const rpc = (fn, body, opts) => call(`/rest/v1/rpc/${fn}`, { method: "POST", body, ...opts });

  const needService = () => {
    if (!service) throw new DbError("SUPABASE_SERVICE_KEY is not set", 500, "no_service_key");
    return service;
  };
  const upsert = (table, rows, onConflict) => call(`/rest/v1/${table}?${qs({ on_conflict: onConflict })}`, {
    key: needService(), method: "POST", body: rows,
    headers: { Prefer: "resolution=merge-duplicates,return=representation" },
  });
  const del = (table, params) => call(`/rest/v1/${table}?${qs(params)}`, {
    key: needService(), method: "DELETE", headers: { Prefer: "return=representation" },
  });
  const getService = (table, params) => call(`/rest/v1/${table}?${qs(params)}`, { key: needService() });

  return { get, all, rpc, upsert, del, getService, hasService: !!service };
}
