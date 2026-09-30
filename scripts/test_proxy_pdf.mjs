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

// Index.html has mixed line endings (some regions were written CRLF by
// Windows sessions); the "\n};" end markers below assume LF, so normalize
// before extracting. Runtime behavior of the extracted code is unaffected.
const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8").replace(/\r\n/g, "\n");

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

// ── No-art face: the blank-art template ────────────────────────────────────
// The "No art" face paints proxy-blank.png over the real card. Everything that
// can go wrong with it is silent: a tile order that drifts from the bake
// script blanks a character with a location's window, and a template that
// reaches the cost hex or the name bar erases the very text a proxy is for.
// So the sprite itself is decoded and probed at the places that must survive.
console.log("\nno-art template");
import { inflateSync } from "node:zlib";
const blankCode = [
  grab("const PROXY_BLANK_SRC =", ";\n"),
  grab("const PROXY_BLANK_TILES =", ";\n"),
  grab("const PROXY_BLANK_TW =", ";\n"),
  grab("const proxyBlankTileOf = (card) => {", "\n};"),
  grab("const drawProxyBlankTile = (", "\n};"),
].join("\n");
const { PROXY_BLANK_SRC, PROXY_BLANK_TILES, PROXY_BLANK_TW, PROXY_BLANK_TH, proxyBlankTileOf, drawProxyBlankTile } =
  new Function(blankCode + "\nreturn {PROXY_BLANK_SRC, PROXY_BLANK_TILES, PROXY_BLANK_TW, PROXY_BLANK_TH, proxyBlankTileOf, drawProxyBlankTile};")();

const bake = readFileSync(new URL("./bake_proxy_blank_mask.py", import.meta.url), "utf8");
const pyTiles = JSON.parse(bake.match(/^TILES = (\[.*\])$/m)[1].replace(/'/g, '"'));
ok(JSON.stringify(pyTiles) === JSON.stringify(PROXY_BLANK_TILES),
   "the client's tile order is the bake script's tile order");
ok(bake.includes(`W, H = ${PROXY_BLANK_TW}, ${PROXY_BLANK_TH}`), "tile size matches the bake script");

const tileName = (card) => PROXY_BLANK_TILES[proxyBlankTileOf(card)];
ok(tileName({cardType: "Character", inkable: true}) === "char_ink", "an inkable character takes char_ink");
ok(tileName({cardType: "Character", inkable: false}) === "char_unk", "an uninkable character takes char_unk");
ok(tileName({cardType: "Action - Song", inkable: true}) === "other_ink", "a song is an 'other' layout");
ok(tileName({cardType: "Item", inkable: null}) === "other_ink", "unknown inkability falls back to the inkable tile");
ok(tileName({cardType: "Location", inkable: false}) === "loc_unk", "an uninkable location takes loc_unk");

// The tile must land where drawImageCover put the card: same crop, as fractions.
const calls = [];
const fakeCtx = {drawImage: (...a) => calls.push(a)};
drawProxyBlankTile(fakeCtx, {naturalWidth: 674, naturalHeight: 940}, "S", 2, 744, 1039);
const [, sx, sy, sw, sh, dx, dy, dw, dh] = calls[0];
ok(sx >= 2 * PROXY_BLANK_TW && sx + sw <= 3 * PROXY_BLANK_TW + 1e-6 && sy >= 0 && sy + sh <= PROXY_BLANK_TH + 1e-6,
   "the source rect stays inside its own tile");
ok(Math.abs(sw / sh - 744 / 1039) < 1e-6 && dx === 0 && dy === 0 && dw === 744 && dh === 1039,
   "the tile is cover-cropped to the card's aspect and fills the canvas");

// Decode the sprite (8-bit RGBA PNG) without a dependency.
const pngPath = new URL("../" + PROXY_BLANK_SRC.replace(/^\//, "").replace(/\?.*$/, ""), import.meta.url);
const png = readFileSync(pngPath);
let pos = 8, pw = 0, ph = 0, ctype = 0;
const idat = [];
while (pos < png.length) {
  const len = png.readUInt32BE(pos), type = png.toString("latin1", pos + 4, pos + 8);
  const body = png.subarray(pos + 8, pos + 8 + len);
  if (type === "IHDR") { pw = body.readUInt32BE(0); ph = body.readUInt32BE(4); ctype = body[9]; ok(body[8] === 8, "the sprite is 8 bits per channel"); }
  if (type === "IDAT") idat.push(body);
  pos += 12 + len;
}
ok(ctype === 6, "the sprite is RGBA");
ok(pw === PROXY_BLANK_TW * PROXY_BLANK_TILES.length && ph === PROXY_BLANK_TH,
   `the sprite is ${PROXY_BLANK_TILES.length} tiles of ${PROXY_BLANK_TW}x${PROXY_BLANK_TH}`);
const raw = inflateSync(Buffer.concat(idat));
const px = Buffer.alloc(pw * ph * 4);
const stride = pw * 4;
for (let y = 0; y < ph; y++) {
  const f = raw[y * (stride + 1)], line = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
  for (let i = 0; i < stride; i++) {
    const left = i >= 4 ? px[y * stride + i - 4] : 0, up = y ? px[(y - 1) * stride + i] : 0;
    const ul = y && i >= 4 ? px[(y - 1) * stride + i - 4] : 0;
    const pa = Math.abs(up - ul), pb = Math.abs(left - ul), pc = Math.abs(left + up - 2 * ul);
    const pred = f === 1 ? left : f === 2 ? up : f === 3 ? (left + up) >> 1
      : f === 4 ? (pa <= pb && pa <= pc ? left : pb <= pc ? up : ul) : 0;
    px[y * stride + i] = (line[i] + pred) & 255;
  }
}
const at = (t, x, y) => { const o = (y * pw + t * PROXY_BLANK_TW + x) * 4; return [px[o], px[o + 1], px[o + 2], px[o + 3]]; };
PROXY_BLANK_TILES.forEach((name, t) => {
  const loc = name.startsWith("loc");
  const win = loc ? [170, 470] : [337, 250];
  const w = at(t, ...win);
  ok(w[3] === 255 && w[0] === 255 && w[1] === 255 && w[2] === 255, `${name}: the middle of the art window is painted white`);
  ok(at(t, 66, 72)[3] === 0, `${name}: the cost hex is left alone`);
  ok(at(t, 0, 0)[3] === 0 && at(t, 673, 939)[3] === 0, `${name}: the card's outer corners are left alone`);
  const keep = loc ? [[380, 470], [520, 470], [380, 60]] : [[120, 540], [337, 750], [560, 540]];
  ok(keep.every(([x, y]) => at(t, x, y)[3] === 0),
     `${name}: the name bar, stats and rules text are left alone`);
  let band = 0;
  for (let y = 0; y < PROXY_BLANK_TH; y += 3) for (let x = 0; x < PROXY_BLANK_TW; x += 3) {
    const c = at(t, x, y);
    if (c[3] === 255 && c[0] + c[1] + c[2] < 180) band++;
  }
  ok(band > 500, `${name}: carries a frame-coloured border band for the standard-frame check`);
});
ok(!/(?<!saved.)face === "text"|drawProxyTextFace|parseProxyRules/.test(src),
   "the hand-drawn text face is gone (a stored \"text\" pref maps to no-art)");

console.log(failures ? `\n${failures} FAILED\n` : "\nall passed\n");
process.exit(failures ? 1 : 0);
