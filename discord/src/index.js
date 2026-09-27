// index.js — the packs-ink-discord Worker.
//
//   POST /interactions   Discord's interactions endpoint (signed)
//   GET  /chart/...      price and sales charts, drawn on request (charts.js)
//   GET  /invite         redirect to "add this bot to a server"
//   GET  /               health: which card index this deploy carries
//
// The card index is imported as TEXT and parsed here, at module scope. That
// work runs once when the isolate starts, under Cloudflare's separate startup
// allowance, not inside any request's CPU budget — so a /price call pays only
// for the lookup itself.
import indexText from "./card-index.json";
import { createResolver } from "./resolver.js";
import { handleInteraction } from "./interactions.js";
import { verifyDiscordRequest } from "./verify.js";
import { makeDb } from "./db.js";
import { chartResponse } from "./charts.js";

const INDEX = typeof indexText === "string" ? JSON.parse(indexText) : indexText;
const R = createResolver(INDEX);

// View Channel + Send Messages + Embed Links: what posting a report needs.
// Replies to commands need no permissions at all.
const INVITE_PERMISSIONS = 1024 + 2048 + 16384;

const json = (obj, status = 200) => new Response(JSON.stringify(obj), {
  status, headers: { "Content-Type": "application/json" },
});

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    try {
      if (url.pathname === "/interactions") {
        if (request.method !== "POST") return new Response("method not allowed", { status: 405 });
        const { ok, body } = await verifyDiscordRequest(request, env.DISCORD_PUBLIC_KEY);
        if (!ok) return new Response("invalid request signature", { status: 401 });
        const interaction = JSON.parse(body);
        const out = await handleInteraction(interaction, {
          R, index: INDEX, db: makeDb(env), origin: url.origin,
          appId: env.DISCORD_APPLICATION_ID, discordApi: env.DISCORD_API_BASE,
          fetch: (...a) => fetch(...a),
          waitUntil: (p) => ctx.waitUntil(p),
          log: (...a) => console.log(...a),
        });
        return json(out);
      }
      if (request.method === "GET" && url.pathname.startsWith("/chart/")) {
        return await chartResponse(url, makeDb(env));
      }
      if (request.method === "GET" && url.pathname === "/invite") {
        if (!env.DISCORD_APPLICATION_ID) return new Response("not configured", { status: 503 });
        const u = new URL("https://discord.com/oauth2/authorize");
        u.searchParams.set("client_id", env.DISCORD_APPLICATION_ID);
        u.searchParams.set("scope", "bot applications.commands");
        u.searchParams.set("permissions", String(INVITE_PERMISSIONS));
        return Response.redirect(u.toString(), 302);
      }
      if (request.method === "GET" && url.pathname === "/") {
        return json({ ok: true, name: "packs-ink-discord", built: INDEX.built, priceDate: INDEX.priceDate,
          cards: INDEX.cards.length, sealed: INDEX.sealed.length });
      }
      return new Response("not found", { status: 404 });
    } catch (e) {
      console.log("worker error", e && e.stack || e);
      return new Response("error", { status: 500 });
    }
  },
};
