// register_commands.mjs — publish the slash commands (and, optionally, point
// Discord at the Worker).
//
//   DISCORD_APPLICATION_ID=… DISCORD_BOT_TOKEN=… node tools/register_commands.mjs
//   … --ids src/command-ids.json  # also save {name: id}, which the Worker
//                                 # bundles so /help can show clickable commands
//   … --endpoint https://packs-ink-discord.<you>.workers.dev/interactions
//   … --endpoint-only <url>       # set the endpoint without re-registering
//   … --guild <server id>         # register to one server only (instant, for testing)
//   … --dry-run                   # print what would be sent
//
// The deploy workflow registers BEFORE it deploys (so the ids are in the
// bundle) and sets the endpoint AFTER (Discord pings the Worker before it will
// save the URL, so the Worker has to be live first).
//
// ⚠ The bot token is a password for the bot account. It is read from the
// environment only — never pass it on the command line (it lands in shell
// history) and never paste it into a chat.
import { writeFileSync } from "node:fs";
import { COMMANDS } from "./commands.js";

const API = "https://discord.com/api/v10";
const args = process.argv.slice(2);
const flag = (n) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : null; };
const dry = args.includes("--dry-run");
const appId = process.env.DISCORD_APPLICATION_ID;
const token = process.env.DISCORD_BOT_TOKEN;
const guild = flag("--guild");
const endpointOnly = flag("--endpoint-only");
const endpoint = endpointOnly || flag("--endpoint");
const idsOut = flag("--ids");

if (dry) {
  console.log(JSON.stringify(COMMANDS, null, 2));
  console.log(`\n${COMMANDS.length} commands.`);
  process.exit(0);
}
if (!appId || !token) {
  console.error("Set DISCORD_APPLICATION_ID and DISCORD_BOT_TOKEN in the environment.");
  process.exit(2);
}
const headers = { Authorization: "Bot " + token, "Content-Type": "application/json" };

if (!endpointOnly) {
  const path = guild ? `/applications/${appId}/guilds/${guild}/commands` : `/applications/${appId}/commands`;
  const r = await fetch(API + path, { method: "PUT", headers, body: JSON.stringify(COMMANDS) });
  const text = await r.text();
  if (!r.ok) {
    console.error(`Registering commands failed: HTTP ${r.status}\n${text.slice(0, 2000)}`);
    process.exit(1);
  }
  const got = JSON.parse(text);
  console.log(`Registered ${got.length} commands ${guild ? "in server " + guild : "globally"}: ${got.map((c) => c.name).join(", ")}`);
  if (idsOut) {
    // Slash commands only (type 1): a message command can't be mentioned.
    const ids = Object.fromEntries(got.filter((c) => c.type === 1 && c.id).map((c) => [c.name, String(c.id)]));
    writeFileSync(idsOut, JSON.stringify(ids, null, 2));
    console.log(`Wrote ${Object.keys(ids).length} command ids to ${idsOut}`);
  }
}

if (endpoint) {
  // Discord PINGs the URL with a signed request before it will save it, so
  // the Worker must already be deployed with DISCORD_PUBLIC_KEY set.
  const e = await fetch(API + "/applications/@me", {
    method: "PATCH", headers,
    body: JSON.stringify({ interactions_endpoint_url: endpoint }),
  });
  if (!e.ok) {
    console.error(`Setting the interactions endpoint failed: HTTP ${e.status}\n${(await e.text()).slice(0, 1000)}`);
    process.exit(1);
  }
  console.log("Interactions endpoint set to " + endpoint);
}
