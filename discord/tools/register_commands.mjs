// register_commands.mjs — publish the slash commands (and, optionally, point
// Discord at the Worker).
//
//   DISCORD_APPLICATION_ID=… DISCORD_BOT_TOKEN=… node tools/register_commands.mjs
//   … --endpoint https://packs-ink-discord.<you>.workers.dev/interactions
//   … --guild <server id>     # register to one server only (instant, for testing)
//   … --dry-run               # print what would be sent
//
// ⚠ The bot token is a password for the bot account. It is read from the
// environment only — never pass it on the command line (it lands in shell
// history) and never paste it into a chat.
import { COMMANDS } from "./commands.js";

const API = "https://discord.com/api/v10";
const args = process.argv.slice(2);
const flag = (n) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : null; };
const dry = args.includes("--dry-run");
const appId = process.env.DISCORD_APPLICATION_ID;
const token = process.env.DISCORD_BOT_TOKEN;
const guild = flag("--guild");
const endpoint = flag("--endpoint");

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

const path = guild ? `/applications/${appId}/guilds/${guild}/commands` : `/applications/${appId}/commands`;
const r = await fetch(API + path, { method: "PUT", headers, body: JSON.stringify(COMMANDS) });
const text = await r.text();
if (!r.ok) {
  console.error(`Registering commands failed: HTTP ${r.status}\n${text.slice(0, 2000)}`);
  process.exit(1);
}
const got = JSON.parse(text);
console.log(`Registered ${got.length} commands ${guild ? "in server " + guild : "globally"}: ${got.map((c) => c.name).join(", ")}`);

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
