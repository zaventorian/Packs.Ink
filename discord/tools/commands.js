// commands.js — the slash commands, as Discord's API wants them.
// Registered by tools/register_commands.mjs (a PUT replaces the whole set, so
// a command removed here disappears from Discord on the next run).

// Installable to a server AND to a person's own account; usable in servers,
// DMs with the bot, and group DMs / other people's DMs when user-installed.
const EVERYWHERE = { integration_types: [0, 1], contexts: [0, 1, 2] };

const nameOpt = {
  type: 3, name: "name", required: true, autocomplete: true, max_length: 100,
  description: "Say it how you say it: mowgli, enchanted elsa, elsa psa 10, azurite sea box",
};
const privOpt = { type: 5, name: "private", description: "Only you see the reply" };
const rangeChoices = [
  { name: "1 month", value: "1m" }, { name: "3 months", value: "3m" },
  { name: "1 year", value: "1y" }, { name: "Everything", value: "all" },
];

export const COMMANDS = [
  {
    name: "card", type: 1, ...EVERYWHERE,
    description: "A Lorcana card: its picture, text, stats, price and how much it's played",
    options: [nameOpt, privOpt],
  },
  {
    name: "price", type: 1, ...EVERYWHERE,
    description: "The price chart and recent changes of a card, a graded slab or sealed product",
    options: [nameOpt, { type: 3, name: "range", description: "Chart range (default 3 months)", choices: rangeChoices }, privOpt],
  },
  {
    name: "events", type: 1, ...EVERYWHERE,
    description: "Upcoming Lorcana events near a postal code or town",
    options: [
      { type: 3, name: "near", required: true, max_length: 60, description: "Postal code or town — 60614, M5V 3L9, Elgin IL" },
      { type: 4, name: "radius", description: "Miles (default 50)", choices: [
        { name: "10 mi", value: 10 }, { name: "25 mi", value: 25 }, { name: "50 mi", value: 50 }, { name: "100 mi", value: 100 }] },
      { type: 3, name: "kind", description: "Which events (default all)", choices: [
        { name: "All events", value: "all" }, { name: "Set Championships", value: "sc" }, { name: "Prereleases", value: "prerelease" },
        { name: "Weekly play (league nights, locals)", value: "other" }] },
      privOpt,
    ],
  },
  {
    name: "meta", type: 1, ...EVERYWHERE,
    description: "What's winning: ink pairs in recent top cuts, the most-played cards, the latest big events",
    options: [privOpt],
  },
  {
    name: "calendar", type: 1, ...EVERYWHERE,
    description: "Set releases, Challenges and qualifiers coming up",
    options: [privOpt],
  },
  { name: "kaylee", type: 1, ...EVERYWHERE, description: "Kaylee's pack stats. Totally normal.", options: [privOpt] },
  { name: "help", type: 1, ...EVERYWHERE, description: "What this bot can do" },
  {
    name: "new", type: 1, ...EVERYWHERE,
    description: "The newest cards — everything revealed in the last four days",
    options: [privOpt],
  },
  {
    name: "set", type: 1, ...EVERYWHERE,
    description: "A set at a glance: release dates, box price vs box EV, chase cards, sealed",
    options: [{ type: 3, name: "set", autocomplete: true, max_length: 60, description: "Which set — hyperia city, azurite, set 5 (default: the newest)" }, privOpt],
  },
  {
    name: "open", type: 1, ...EVERYWHERE,
    description: "Open a booster pack (or a whole box) with real odds and real prices",
    options: [
      { type: 3, name: "set", autocomplete: true, max_length: 60, description: "Which set (default: the newest one out)" },
      { type: 5, name: "box", description: "Open a whole box — 24 packs" },
      privOpt,
    ],
  },
  {
    name: "reports", type: 1, integration_types: [0], contexts: [0],
    description: "A daily or weekly price movers report in a channel",
    // Manage Server. Discord hides the command from everyone else; the handler
    // checks the permission again anyway.
    default_member_permissions: "32",
    options: [
      { type: 1, name: "daily", description: "Post the movers every day", options: reportOpts() },
      { type: 1, name: "weekly", description: "Post the week's movers every Monday at 9 AM Central", options: reportOpts() },
      { type: 1, name: "send", description: "Post the latest report here, now", options: [
        { type: 3, name: "report", description: "Which report (default: daily)", choices: [
          { name: "Daily movers", value: "daily" }, { name: "Last weekly report", value: "weekly" }] }] },
      { type: 1, name: "off", description: "Stop the reports in a channel", options: [channelOpt()] },
      { type: 1, name: "status", description: "Which channels get reports" },
    ],
  },
];

function channelOpt() {
  return { type: 7, name: "channel", description: "Channel (default: this one)", channel_types: [0, 5] };
}
function reportOpts() {
  return [channelOpt()];
}
