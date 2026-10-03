// Read the card catalog out of one locale of the official Disney Lorcana gallery.
//
//   node scripts/intl_gallery_data.mjs <locale> <out.json> [saved.html]
//
// cards.disneylorcana.com/<locale>/ embeds the WHOLE catalog (every set, every
// promo, ~3,500 cards) as a single TanStack-Router dehydration script: a
// seroval `$R[n]=` object graph, i.e. JavaScript, not JSON. Regexing fields out
// of it is how the old importer ended up reading one card's stats off its
// neighbour, so this evaluates the script and walks the resulting object.
//
// Evaluated in a null-prototype vm context whose stubs are created INSIDE the
// context, so nothing in it can reach this realm's Function constructor (and
// from there `process`). The caller (intl_cards.py) also runs this with an empty
// environment, so even an escape would find no secrets. It is a data script
// from Ravensburger's own site; this is belt and braces, not paranoia.
//
// Locales that exist: en-US, de-DE, fr-FR, it-IT (any other 307s to en-US).
import fs from "fs";
import vm from "vm";

const [locale, out, saved] = process.argv.slice(2);
if (!locale || !out) {
  console.error("usage: node intl_gallery_data.mjs <locale> <out.json> [saved.html]");
  process.exit(2);
}

let html;
if (saved) {
  html = fs.readFileSync(saved, "utf8");
} else {
  const res = await fetch(`https://cards.disneylorcana.com/${locale}/`, {
    headers: { "User-Agent": "Mozilla/5.0 (packs.ink card sync)" },
    redirect: "manual",
  });
  if (res.status !== 200) {
    console.error(`gallery ${locale}: HTTP ${res.status} (a 307 means the locale does not exist)`);
    process.exit(1);
  }
  html = await res.text();
}

const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const data = scripts.find(s => s.includes("cardsData"));
if (!data) {
  console.error("no cardsData script on the page - the gallery changed shape");
  process.exit(1);
}

// A NULL-PROTOTYPE sandbox: `vm.createContext({})` makes the context's global
// from THIS realm's Object, so `this.constructor.constructor("return process")()`
// inside the page script walks straight back out to `process` (the guard test
// tries exactly that). With no prototype there is no `constructor` to walk.
const ctx = vm.createContext(Object.create(null));
vm.runInContext("var self = this; var window = this; var document = { currentScript: { remove: function () {} } };", ctx);
vm.runInContext(data, ctx, { timeout: 20000 });
const json = vm.runInContext(`(function () {
  var ms = (self.$_TSR && self.$_TSR.router && self.$_TSR.router.matches) || [];
  for (var i = 0; i < ms.length; i++) {
    var l = ms[i] && ms[i].l;
    if (l && l.cardsData && l.cardsData.cards) {
      return JSON.stringify({ locale: l.locale, cards: l.cardsData.cards, setNames: l.cardsData.setNames || null });
    }
  }
  return null;
})()`, ctx);
if (!json) {
  console.error("cardsData not found in the router state - the gallery changed shape");
  process.exit(1);
}
fs.writeFileSync(out, json);
const n = JSON.parse(json).cards.length;
console.error(`gallery ${locale}: ${n} cards`);
if (n < 1000) process.exit(1);
