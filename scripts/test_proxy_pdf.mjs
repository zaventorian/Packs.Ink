// test_proxy_pdf.mjs — guards the hand-written PDF writer behind "Print proxies".
//
//     node scripts/test_proxy_pdf.mjs
//
// Nothing here is checked by a type system or a library: buildProxyPdfBlob
// emits raw PDF syntax, and the two ways it can break are silent and total —
// a wrong byte offset in the xref table or a wrong /Length on a stream makes
// the file unopenable in every reader, with no clue as to why. Both are
// arithmetic over binary data, so they break the moment anyone edits what the
// writer emits (an extra newline in a dictionary is enough).
//
// This reads the real functions out of Index.html rather than restating them,
// so it cannot drift from what ships. Run it after touching any of
// pdfWriter / pdfNum / pdfText / buildProxyPdfBlob / proxySheetGeometry.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8");

function grab(startMarker, endMarker) {
  const a = src.indexOf(startMarker);
  if (a < 0) throw new Error("missing start marker: " + startMarker);
  const b = src.indexOf(endMarker, a);
  if (b < 0) throw new Error("missing end marker: " + endMarker);
  return src.slice(a, b + endMarker.length);
}

const code = [
  grab("const PDF_PT_PER_MM   =", 'a4:     {label: "A4",        w: 595.28, h: 841.89},\n};'),
  grab("const pdfNum = (n) => {", "\n};"),
  grab("const pdfText = (s) =>", '.replace(/([\\\\()])/g, "\\\\$1");'),
  grab("const pdfWriter = () => {", "\n};"),
  grab("const buildProxyPdfBlob = ({imgs", "\n};"),
  grab("const proxySheetGeometry = (paper) => {", "\n};"),
].join("\n");

const {
  buildProxyPdfBlob, proxySheetGeometry, pdfText, pdfNum,
  PROXY_PAPERS, PROXY_CARD_MM, PDF_PT_PER_MM, PROXY_PER_PAGE, PROXY_COLS, PROXY_ROWS,
} = new Function(
  code + "\nreturn {buildProxyPdfBlob, proxySheetGeometry, pdfText, pdfNum,"
       + " PROXY_PAPERS, PROXY_CARD_MM, PDF_PT_PER_MM, PROXY_PER_PAGE, PROXY_COLS, PROXY_ROWS};",
)();

let failures = 0;
const ok = (cond, label) => {
  if (cond) console.log("  ok   " + label);
  else { failures++; console.log("  FAIL " + label); }
};
const near = (a, b, eps = 0.01) => Math.abs(a - b) <= eps;

// ── Fixture ────────────────────────────────────────────────────────────────
// The writer treats image payloads as opaque bytes, so these stand in for
// JPEGs. They deliberately include 0x00, 0x0A, 0x0D and every high byte: if
// anything ever routes stream data through the latin-1 string path (or a
// text-mode transform mangles a CR), the round-trip check below catches it.
const payload = (seed, n) => {
  const u = new Uint8Array(n);
  for (let i = 0; i < n; i++) u[i] = (i * 31 + seed * 7) & 0xff;
  u[0] = 0xff; u[1] = 0xd8; u[n - 2] = 0xff; u[n - 1] = 0xd9;   // SOI / EOI
  return u;
};
const imgs = [
  { data: payload(1, 2048), w: 744, h: 1039 },
  { data: payload(2, 777),  w: 744, h: 1039 },
  { data: payload(3, 1531), w: 744, h: 1039 },
];

const geo = proxySheetGeometry("letter");
// 14 cards over 3 unique images → 2 pages, second one part-full.
const seq = [0,1,2,0,1,2,0,1,2, 0,1,2,0,1];
const pages = [];
for (let p = 0; p * PROXY_PER_PAGE < seq.length; p++) {
  const chunk = seq.slice(p * PROXY_PER_PAGE, (p + 1) * PROXY_PER_PAGE);
  pages.push({
    slots: chunk.map((img, i) => ({ img, ...geo.slotAt(i) })),
    guides: geo.guides,
    footer: "Ruby/Sapphire (v2) \\ midrange - packs.ink - page " + (p + 1),
    footerX: geo.footerX, footerY: geo.footerY,
  });
}
const blob = buildProxyPdfBlob({
  imgs, pages, pageW: geo.page.w, pageH: geo.page.h,
  title: "Ruby/Sapphire (v2) - proxies",
});
const bytes = new Uint8Array(await blob.arrayBuffer());
const latin1 = Buffer.from(bytes).toString("latin1");

// ── Structure ──────────────────────────────────────────────────────────────
console.log("\nfile structure");
ok(latin1.startsWith("%PDF-1.4\n"), "starts with a PDF header");
ok(latin1.endsWith("%%EOF\n"), "ends with %%EOF");
ok(blob.type === "application/pdf", "blob carries the application/pdf type");

// Objects: 4 fixed + 3 images + 2 pages x 2 = 11.
const expectObjs = 4 + imgs.length + pages.length * 2;
ok((latin1.match(/\n\d+ 0 obj\n/g) || []).length === expectObjs,
   `emits ${expectObjs} objects`);
ok(latin1.includes("/Count " + pages.length + " /Kids [" + (5 + imgs.length) + " 0 R "
   + (5 + imgs.length + 2) + " 0 R]"), "page tree lists every page kid");

// ── xref offsets ───────────────────────────────────────────────────────────
// The failure this catches: any change to the bytes emitted before an object
// shifts its true offset, and a reader that trusts the table lands mid-object.
console.log("\nxref table");
const xrefAt = latin1.lastIndexOf("\nxref\n");
const startxref = Number(/startxref\n(\d+)\n%%EOF/.exec(latin1)[1]);
ok(startxref === xrefAt + 1, "startxref points at the xref keyword");
const rows = latin1.slice(xrefAt).match(/^(\d{10}) 00000 n $/gm) || [];
ok(rows.length === expectObjs, "one xref row per object");
let offsetsGood = true;
rows.forEach((row, i) => {
  const off = Number(row.slice(0, 10));
  if (!latin1.startsWith(`${i + 1} 0 obj\n`, off)) offsetsGood = false;
});
ok(offsetsGood, "every xref offset lands exactly on its object header");
ok(latin1.includes(`/Size ${expectObjs + 1} /Root 1 0 R /Info 3 0 R`), "trailer is complete");

// ── Stream lengths + binary fidelity ───────────────────────────────────────
console.log("\nimage streams");
let lengthsGood = true, bytesGood = true, streamCount = 0;
const re = /\/Length (\d+) >>\nstream\n/g;
let m;
while ((m = re.exec(latin1))) {
  streamCount++;
  const declared = Number(m[1]);
  const start = m.index + m[0].length;
  if (!latin1.startsWith("\nendstream", start + declared)
      && !latin1.startsWith("endstream", start + declared)) lengthsGood = false;
}
ok(streamCount === imgs.length + pages.length, "every image and content stream is emitted");
ok(lengthsGood, "every declared /Length matches where its stream actually ends");

imgs.forEach((im, i) => {
  const hdr = `/Width ${im.w} /Height ${im.h} /ColorSpace /DeviceRGB /BitsPerComponent 8`
    + ` /Filter /DCTDecode /Length ${im.data.length} >>\nstream\n`;
  const at = latin1.indexOf(hdr);
  if (at < 0) { bytesGood = false; return; }
  const start = at + hdr.length;
  for (let k = 0; k < im.data.length; k++) {
    if (bytes[start + k] !== im.data[k]) { bytesGood = false; break; }
  }
});
ok(bytesGood, "JPEG payloads survive byte-for-byte (no latin-1 mangling)");

// ── Text escaping ──────────────────────────────────────────────────────────
// An unescaped ")" in a deck name closes the PDF string early and corrupts
// everything after it, so a deck called "Ruby/Sapphire (v2)" would ship a
// broken file.
console.log("\ntext escaping");
ok(pdfText("(v2) \\ x") === "\\(v2\\) \\\\ x", "parens and backslashes are escaped");
ok(pdfText("Bodyguard — “test”") === 'Bodyguard - "test"',
   "em dashes and smart quotes fold to latin-1");
ok(pdfText("カード Elsa") === " Elsa", "non-latin-1 characters are dropped, not emitted raw");
ok(latin1.includes("(Ruby/Sapphire \\(v2\\) \\\\ midrange - packs.ink - page 1) Tj"),
   "the footer string is escaped in the content stream");

// ── Geometry ───────────────────────────────────────────────────────────────
console.log("\nsheet geometry");
for (const paper of Object.keys(PROXY_PAPERS)) {
  const g = proxySheetGeometry(paper);
  const cw = PROXY_CARD_MM.w * PDF_PT_PER_MM, ch = PROXY_CARD_MM.h * PDF_PT_PER_MM;
  const slots = Array.from({ length: PROXY_PER_PAGE }, (_, i) => g.slotAt(i));
  ok(slots.every(s => near(s.w, cw) && near(s.h, ch)),
     `${paper}: every slot is exactly ${PROXY_CARD_MM.w}x${PROXY_CARD_MM.h}mm`);
  ok(slots.every(s => s.x >= -0.01 && s.y >= -0.01
        && s.x + s.w <= g.page.w + 0.01 && s.y + s.h <= g.page.h + 0.01),
     `${paper}: the whole ${PROXY_COLS}x${PROXY_ROWS} block fits inside the page`);
  // Top-left slot must be the first one — a flipped row order prints the
  // sheet upside down relative to the cut marks.
  ok(near(slots[0].y + slots[0].h, g.page.h - (g.page.h - ch * PROXY_ROWS) / 2),
     `${paper}: slot 0 is the top-left card`);
  let overlap = false;
  for (let i = 0; i < slots.length; i++) {
    for (let j = i + 1; j < slots.length; j++) {
      const a = slots[i], b = slots[j];
      if (a.x < b.x + b.w - 0.01 && b.x < a.x + a.w - 0.01
          && a.y < b.y + b.h - 0.01 && b.y < a.y + a.h - 0.01) overlap = true;
    }
  }
  ok(!overlap, `${paper}: no two cards overlap`);
  ok(g.guides.every(([x1, y1, x2, y2]) =>
       Math.min(x1, x2) >= -0.01 && Math.max(x1, x2) <= g.page.w + 0.01
       && Math.min(y1, y2) >= -0.01 && Math.max(y1, y2) <= g.page.h + 0.01),
     `${paper}: every cut mark stays on the page`);
  ok(g.footerY > 0 && g.footerY < g.page.h, `${paper}: the footer sits on the page`);
}

console.log("\nnumbers");
ok(pdfNum(178.58267716535434) === "178.583", "long floats are trimmed, not exponential");
ok(pdfNum(0) === "0" && pdfNum(-0) === "0", "negative zero is normalised");
ok(!/e/i.test(pdfNum(0.0000001)), "tiny values never render in exponent form");

console.log(failures ? `\n${failures} FAILED\n` : "\nall passed\n");
process.exit(failures ? 1 : 0);
