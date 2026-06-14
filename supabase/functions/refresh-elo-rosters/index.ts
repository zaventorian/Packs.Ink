// refresh-elo-rosters — Supabase Edge Function (Deno)
//
// Powers the admin "run scraper" button on the Packs.Ink ELO section. It scrapes
// the signed-up rosters for every tracked upcoming Set Championship from the RPH
// registrations endpoint (which is PUBLIC but CORS-blocked, so it can only be
// fetched server-side) and writes them into elo_event_roster +
// elo_event_roster_members. The gated get_event_roster() RPC then joins those to
// current ELO. This mirrors scripts/elo/scrape_rosters.py (the cron safety net) —
// keep the two in sync if the scrape logic changes.
//
// Deploy:  supabase functions deploy refresh-elo-rosters
// Invoke:  POST <project>/functions/v1/refresh-elo-rosters
//          with the caller's Authorization: Bearer <user jwt> header.
//
// Auth model: the caller's JWT must pass can_view_store_report() (admins +
// elo_report_viewers). All DB writes use the service-role key (server-only).

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

// ── CORS (packs.ink + localhost dev) ────────────────────────────────────────
const ALLOWED_ORIGINS = new Set([
  "https://packs.ink",
  "https://www.packs.ink",
  "http://localhost:8766",
]);

function corsHeaders(origin: string | null): Record<string, string> {
  const allow = origin && ALLOWED_ORIGINS.has(origin) ? origin : "https://packs.ink";
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Vary": "Origin",
  };
}

const REG_API = (eventId: number) =>
  `https://api.ravensburgerplay.com/api/v2/events/${eventId}/registrations/?page_size=100`;
const RPH_HEADERS = { "User-Agent": "Mozilla/5.0", "Accept": "application/json" };

// GET + parse JSON with retry on transient errors / 5xx / 429.
async function httpJson(url: string, retries = 5): Promise<any> {
  let last: unknown;
  for (let i = 0; i < retries; i++) {
    try {
      const r = await fetch(url, { headers: RPH_HEADERS });
      if (r.ok) return await r.json();
      // 4xx (other than 429) is terminal — e.g. a deleted event 404s.
      if (r.status !== 429 && !(r.status >= 500 && r.status < 600)) {
        throw new Error(`HTTP ${r.status} for ${url}`);
      }
      last = new Error(`HTTP ${r.status}`);
    } catch (e) {
      last = e;
    }
    await new Promise((res) => setTimeout(res, 800 * (i + 1)));
  }
  throw last;
}

// Page through every registration for one event via the `next` envelope.
async function fetchRegistrations(eventId: number): Promise<any[]> {
  const out: any[] = [];
  let url: string | null = REG_API(eventId);
  while (url) {
    const d = await httpJson(url);
    out.push(...((d.results ?? []) as any[]));
    url = d.next ?? null;
    if (url) await new Promise((res) => setTimeout(res, 120));
  }
  return out;
}

// COMPLETE registrations -> roster member rows, deduped on best_identifier
// (the (event_id, best_identifier) PK).
function memberRows(eventId: number, regs: any[]): any[] {
  const seen = new Map<string, any>();
  for (const reg of regs) {
    if (String(reg.registration_status ?? "").toUpperCase() !== "COMPLETE") continue;
    const ident = reg.best_identifier;
    if (!ident) continue;
    const user = reg.user && typeof reg.user === "object" ? reg.user : {};
    seen.set(ident, {
      event_id: eventId,
      rph_user_id: user.id ?? null,
      best_identifier: ident,
      account_name: user.best_identifier ?? null,
      registration_status: reg.registration_status ?? null,
    });
  }
  return [...seen.values()];
}

Deno.serve(async (req: Request) => {
  const origin = req.headers.get("origin");
  const cors = corsHeaders(origin);

  // Preflight
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: cors });
  }
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ ok: false, error: "method not allowed" }), {
      status: 405,
      headers: { ...cors, "Content-Type": "application/json" },
    });
  }

  const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
  const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
  const ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY") ?? "";

  // (a) Verify the caller with THEIR jwt: a client carrying the request's
  // Authorization header, then can_view_store_report() (admins + viewers).
  const authHeader = req.headers.get("Authorization") ?? "";
  const userClient = createClient(SUPABASE_URL, ANON_KEY, {
    global: { headers: { Authorization: authHeader } },
  });
  const { data: allowed, error: authErr } = await userClient.rpc("can_view_store_report");
  if (authErr || allowed !== true) {
    return new Response(JSON.stringify({ ok: false, error: "not authorized" }), {
      status: 403,
      headers: { ...cors, "Content-Type": "application/json" },
    });
  }

  // (b) Service-role client for all reads/writes (bypasses RLS, server-only).
  const db = createClient(SUPABASE_URL, SERVICE_KEY);

  // Tracked upcoming SCs (elo_upcoming_scs = set_championships ⋈ tracked stores),
  // today or later.
  const today = new Date().toISOString().slice(0, 10);
  const { data: events, error: evErr } = await db
    .from("elo_upcoming_scs")
    .select("event_id,name,capacity,registered_user_count,start_datetime")
    .gte("start_datetime", today)
    .order("start_datetime", { ascending: true });

  if (evErr) {
    return new Response(JSON.stringify({ ok: false, error: evErr.message }), {
      status: 500,
      headers: { ...cors, "Content-Type": "application/json" },
    });
  }

  let okCount = 0;
  let totalMembers = 0;
  const failed: Array<{ event_id: number; error: string }> = [];

  for (const ev of events ?? []) {
    const eid = ev.event_id as number;
    try {
      // (c) fetch + filter COMPLETE
      const regs = await fetchRegistrations(eid);
      const members = memberRows(eid, regs);

      // (d) upsert header, then REPLACE members (delete-then-insert).
      const { error: hErr } = await db
        .from("elo_event_roster")
        .upsert(
          {
            event_id: eid,
            registered_count: members.length,
            capacity: ev.capacity ?? null,
            scraped_at: new Date().toISOString(),
          },
          { onConflict: "event_id" },
        );
      if (hErr) throw new Error(hErr.message);

      const { error: dErr } = await db
        .from("elo_event_roster_members")
        .delete()
        .eq("event_id", eid);
      if (dErr) throw new Error(dErr.message);

      if (members.length) {
        const { error: mErr } = await db
          .from("elo_event_roster_members")
          .upsert(members, { onConflict: "event_id,best_identifier" });
        if (mErr) throw new Error(mErr.message);
      }

      okCount++;
      totalMembers += members.length;
    } catch (e) {
      // Fail SOFT per event so one bad event doesn't sink the whole refresh.
      failed.push({ event_id: eid, error: String((e as Error)?.message ?? e) });
    }
  }

  // (e) summary
  return new Response(
    JSON.stringify({
      ok: true,
      events: okCount,
      players: totalMembers,
      failed: failed.length ? failed : undefined,
    }),
    { status: 200, headers: { ...cors, "Content-Type": "application/json" } },
  );
});
