// png.js — RGB buffer -> PNG bytes, with a deflate of our own.
//
// Why not CompressionStream: zlib's CPU time counts against the Worker's
// per-request budget, and a chart is ~700 KB of raw pixels. A chart is also
// the easiest image there is to compress — flat background, runs of one
// colour, rows that repeat the row above — so a tiny LZ77 that only ever looks
// one pixel left and one row up, packed with deflate's FIXED Huffman codes,
// gets most of the win for a fraction of the work. It is also deterministic,
// which is what lets the guard test decode the output and check the pixels.

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

export function crc32(bytes, start = 0, end = bytes.length) {
  let c = 0xffffffff;
  for (let i = start; i < end; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function adler32(bytes) {
  let a = 1, b = 0;
  const n = bytes.length;
  for (let i = 0; i < n;) {
    // 5552 is the largest block that cannot overflow before the modulo.
    const end = Math.min(n, i + 5552);
    for (; i < end; i++) { a += bytes[i]; b += a; }
    a %= 65521; b %= 65521;
  }
  return ((b << 16) | a) >>> 0;
}

// ── deflate, fixed Huffman ───────────────────────────────────────────────
const rev = (code, len) => {
  let r = 0;
  for (let i = 0; i < len; i++) { r = (r << 1) | (code & 1); code >>>= 1; }
  return r;
};
// Literal/length alphabet (RFC 1951 §3.2.6), stored bit-reversed because
// Huffman codes are packed most-significant-bit first into an LSB-first stream.
const LIT_CODE = new Uint16Array(288), LIT_LEN = new Uint8Array(288);
for (let v = 0; v < 288; v++) {
  let code, len;
  if (v < 144) { code = 0x30 + v; len = 8; }
  else if (v < 256) { code = 0x190 + v - 144; len = 9; }
  else if (v < 280) { code = v - 256; len = 7; }
  else { code = 0xc0 + v - 280; len = 8; }
  LIT_CODE[v] = rev(code, len); LIT_LEN[v] = len;
}
const LEN_BASE = [3,4,5,6,7,8,9,10,11,13,15,17,19,23,27,31,35,43,51,59,67,83,99,115,131,163,195,227,258];
const LEN_EXTRA = [0,0,0,0,0,0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,0];
const DIST_BASE = [1,2,3,4,5,7,9,13,17,25,33,49,65,97,129,193,257,385,513,769,1025,1537,2049,3073,4097,6145,8193,12289,16385,24577];
const DIST_EXTRA = [0,0,0,0,1,1,2,2,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11,12,12,13,13];
// length 3..258 -> index into LEN_BASE
const LEN_SYM = new Uint8Array(259);
for (let s = 0; s < 29; s++) {
  const hi = s === 28 ? 258 : LEN_BASE[s] + (1 << LEN_EXTRA[s]) - 1;
  for (let l = LEN_BASE[s]; l <= hi && l <= 258; l++) LEN_SYM[l] = s;
}
const distSym = (d) => { let s = 0; while (s < 29 && DIST_BASE[s + 1] <= d) s++; return s; };

export function deflateFixed(data, stride) {
  const n = data.length;
  const out = new Uint8Array(Math.ceil(n * 1.13) + 64);
  let pos = 0, acc = 0, nbits = 0;
  const put = (v, len) => {
    acc |= v << nbits; nbits += len;
    while (nbits >= 8) { out[pos++] = acc & 0xff; acc >>>= 8; nbits -= 8; }
  };
  const lit = (v) => put(LIT_CODE[v], LIT_LEN[v]);
  // Only two distances are ever tried — the row above (stride) and the pixel
  // to the left (3) — so both codes are worked out once, up front.
  const dA = stride > 0 && stride <= 32768 ? stride : 0;
  const sA = dA ? distSym(dA) : 0, cA = rev(sA, 5), xA = DIST_EXTRA[sA], vA = dA - DIST_BASE[sA];
  const sB = distSym(3), cB = rev(sB, 5), xB = DIST_EXTRA[sB], vB = 3 - DIST_BASE[sB];
  put(1, 1); put(1, 2); // BFINAL, BTYPE=01 (fixed Huffman)
  let i = 0;
  while (i < n) {
    const max = n - i < 258 ? n - i : 258;
    let la = 0, lb = 0;
    if (dA && i >= dA) { const j = i - dA; while (la < max && data[i + la] === data[j + la]) la++; }
    if (la < max && i >= 3) { const j = i - 3; while (lb < max && data[i + lb] === data[j + lb]) lb++; }
    const best = la >= lb ? la : lb;
    if (best >= 3) {
      const s = LEN_SYM[best];
      lit(257 + s);
      if (LEN_EXTRA[s]) put(best - LEN_BASE[s], LEN_EXTRA[s]);
      if (la >= lb) { put(cA, 5); if (xA) put(vA, xA); }
      else { put(cB, 5); if (xB) put(vB, xB); }
      i += best;
    } else {
      lit(data[i]);
      i++;
    }
  }
  lit(256);
  if (nbits > 0) out[pos++] = acc & 0xff;
  return out.subarray(0, pos);
}

function chunk(type, data) {
  const b = new Uint8Array(12 + data.length);
  const dv = new DataView(b.buffer);
  dv.setUint32(0, data.length);
  for (let i = 0; i < 4; i++) b[4 + i] = type.charCodeAt(i);
  b.set(data, 8);
  dv.setUint32(8 + data.length, crc32(b, 4, 8 + data.length));
  return b;
}

// rgb: Uint8Array(w*h*3), row-major.
export function encodePNG(rgb, w, h) {
  const stride = w * 3 + 1;
  const raw = new Uint8Array(stride * h);
  for (let y = 0; y < h; y++) {
    raw[y * stride] = 0; // filter: None
    raw.set(rgb.subarray(y * w * 3, (y + 1) * w * 3), y * stride + 1);
  }
  const def = deflateFixed(raw, stride);
  const z = new Uint8Array(def.length + 6);
  z[0] = 0x78; z[1] = 0x01;
  z.set(def, 2);
  const ad = adler32(raw);
  z[z.length - 4] = ad >>> 24; z[z.length - 3] = (ad >>> 16) & 0xff;
  z[z.length - 2] = (ad >>> 8) & 0xff; z[z.length - 1] = ad & 0xff;
  const ihdr = new Uint8Array(13);
  const dv = new DataView(ihdr.buffer);
  dv.setUint32(0, w); dv.setUint32(4, h);
  ihdr[8] = 8; ihdr[9] = 2; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  const parts = [
    new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", ihdr), chunk("IDAT", z), chunk("IEND", new Uint8Array(0)),
  ];
  const total = parts.reduce((s, p) => s + p.length, 0);
  const png = new Uint8Array(total);
  let o = 0;
  for (const p of parts) { png.set(p, o); o += p.length; }
  return png;
}
