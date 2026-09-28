// sitecode.mjs — run pieces of the SITE's own code (Index.html) in Node.
//
// The bot must name, label and price cards exactly the way the site does, and
// the site's rules for that live in one giant inline <script>: the catalog
// transform alone encodes the Holofoil-mislabel rule, connecting foils, the C2
// ghost rows, promo single-printing collapse, regional exclusives and a dozen
// more fixes, each of which shipped wrong at least once. Re-implementing them
// here would fork every one of those decisions. So instead this parses the
// script with acorn, takes the TRANSITIVE CLOSURE of the top-level
// declarations a function needs, and evaluates exactly that in a sandbox.
//
// transformSupabaseData's closure is ~44 declarations / ~66 KB, not the whole
// app, because the transform is written against plain constants.
//
// ⚠ Browser globals are STUBBED, not emulated. The closure only needs `window`
// at definition time (IS_NATIVE_APP / SITE_ORIGIN); anything that tries to use
// the DOM for real would throw here, which is the right failure — it means a
// UI dependency crept into the data path.
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const acorn = require("acorn");
const walk = require("acorn-walk");

export const INDEX_HTML = new URL("../../Index.html", import.meta.url);

// The app script is the largest inline <script> (no src). Everything else in
// the file is a few-line boot shim.
export function appScript(html = readFileSync(INDEX_HTML, "utf8")) {
  let best = "";
  for (const m of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) {
    if (m[1].length > best.length) best = m[1];
  }
  if (best.length < 1_000_000) throw new Error("could not find the app <script> in Index.html");
  return best;
}

let _parsed = null;
export function parseApp() {
  if (_parsed) return _parsed;
  const code = appScript();
  const ast = acorn.parse(code, { ecmaVersion: "latest", sourceType: "script", allowReturnOutsideFunction: true });
  const decls = new Map();
  for (const st of ast.body) {
    if (st.type === "VariableDeclaration") {
      for (const d of st.declarations) if (d.id.type === "Identifier") decls.set(d.id.name, st);
    } else if ((st.type === "FunctionDeclaration" || st.type === "ClassDeclaration") && st.id) {
      decls.set(st.id.name, st);
    }
  }
  _parsed = { code, ast, decls };
  return _parsed;
}

const refsOf = (node) => {
  const out = new Set();
  walk.full(node, (n) => { if (n.type === "Identifier") out.add(n.name); });
  return out;
};

// Source for `names` plus everything they reference, in file order.
// `stop` names are left OUT of the closure (the caller provides them).
export function closureSource(names, { stop = [] } = {}) {
  const { code, decls } = parseApp();
  const stopSet = new Set(stop);
  const inc = new Set();
  const queue = [...names];
  while (queue.length) {
    const n = queue.pop();
    if (inc.has(n) || stopSet.has(n)) continue;
    const st = decls.get(n);
    if (!st) {
      if (names.includes(n)) throw new Error("Index.html has no top-level declaration named " + n);
      continue;
    }
    inc.add(n);
    for (const r of refsOf(st)) if (decls.has(r) && !inc.has(r) && !stopSet.has(r)) queue.push(r);
  }
  const stmts = [...new Set([...inc].map((n) => decls.get(n)))].sort((a, b) => a.start - b.start);
  return { names: [...inc], stmts: stmts.map((s) => code.slice(s.start, s.end)) };
}

// Evaluate the closure and hand back the named exports.
export function loadSite(names, { stop = [], globals = {} } = {}) {
  const { stmts } = closureSource(names, { stop });
  const sandbox = {
    console,
    window: { location: { origin: "https://packs.ink", protocol: "https:", search: "" }, Capacitor: undefined },
    location: { origin: "https://packs.ink", protocol: "https:", search: "" },
    navigator: { userAgent: "node", language: "en-US" },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: undefined,
    Intl, Date, Math, JSON, Map, Set, Array, Object, String, Number, RegExp, Error, Promise,
    parseInt, parseFloat, isNaN, isFinite, encodeURIComponent, decodeURIComponent,
    ...globals,
  };
  const body = stmts.join("\n") + "\nreturn {" + names.join(",") + "};";
  return vm.runInNewContext("(function(){\n" + body + "\n})()", sandbox, { filename: "Index.html(closure)" });
}
