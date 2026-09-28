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
    description: "Show a Lorcana card with its price",
    options: [nameOpt, privOpt],
  },
  {
    name: "price", type: 1, ...EVERYWHERE,
    description: "A card or sealed product's price, recent changes and price chart",
    options: [nameOpt, { type: 3, name: "range", description: "Chart range (default 3 months)", choices: rangeChoices }, privOpt],
  },
  {
    name: "trade", type: 1, ...EVERYWHERE,
    description: "Is this trade fair? Both sides priced and compared",
    options: [
      { type: 3, name: "give", max_length: 1000, description: "What you give — 2x mowgli, enchanted elsa, $20 (or leave empty for a box)" },
      { type: 3, name: "get", max_length: 1000, description: "What you get — stitch rock star foil, azurite sea box" },
      privOpt,
    ],
  },
  {
    name: "deck", type: 1, ...EVERYWHERE,
    description: "Price a decklist — paste it into the box that opens",
    options: [privOpt],
  },
  {
    name: "movers", type: 1, ...EVERYWHERE,
    description: "Biggest price gains or drops",
    options: [
      { type: 3, name: "window", description: "Over how long (default 1 day)", choices: [
        { name: "1 day", value: "1d" }, { name: "1 week", value: "1w" }, { name: "1 month", value: "1m" },
        { name: "3 months", value: "3m" }, { name: "6 months", value: "6m" }, { name: "1 year", value: "1y" }] },
      { type: 3, name: "direction", description: "Gains or drops (default gains)", choices: [
        { name: "Gains", value: "up" }, { name: "Drops", value: "down" }] },
      { type: 3, name: "rarity", description: "Which cards (default all)", choices: [
        { name: "Chase (Enchanted / Epic / Iconic)", value: "chase" }, { name: "Rare to Legendary", value: "rareleg" },
        { name: "Promos", value: "promo" }, { name: "All", value: "all" },
        { name: "Sealed product (boxes, troves, gift sets)", value: "sealed" }] },
      { type: 3, name: "basis", description: "Which price (default NM Market)", choices: [
        { name: "NM Market", value: "market" }, { name: "Low", value: "low" }] },
      { type: 10, name: "min_price", description: "Only cards that started at or above this price (default $5)", min_value: 0, max_value: 10000 },
      privOpt,
    ],
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
    description: "What's being played: the most-played cards and the latest tournament winners",
    options: [privOpt],
  },
  {
    name: "calendar", type: 1, ...EVERYWHERE,
    description: "Set releases, Challenges and qualifiers coming up",
    options: [privOpt],
  },
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
      { type: 1, name: "weekly", description: "Post the week's movers every Monday", options: reportOpts() },
      { type: 1, name: "off", description: "Stop the reports in a channel", options: [channelOpt()] },
      { type: 1, name: "status", description: "Which channels get reports" },
    ],
  },
  { name: "Price check", type: 3, ...EVERYWHERE },
];

function channelOpt() {
  return { type: 7, name: "channel", description: "Channel (default: this one)", channel_types: [0, 5] };
}
function reportOpts() {
  return [channelOpt()];
}
