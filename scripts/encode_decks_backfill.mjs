// One-off backfill: obfuscate existing decklists in Supabase so a raw DB
// audit can't read what anyone's deck is. Encrypts, in place:
//   decks.name, decks.description        (user decks only, user_id NOT NULL)
//   deck_cards.card_id                   (deterministic — PK stays valid)
// quantity is left as a plain int (a count next to a ciphertext card_id
// reveals no list). Tournament / ownerless decks (user_id IS NULL) are left
// plaintext — they're admin-authored and public.
//
// The codec MUST match Index.html's exactly (same key, same AES-GCM scheme).
//
// Usage:
//   node scripts/encode_decks_backfill.mjs            # DRY RUN (reads only, reports)
//   node scripts/encode_decks_backfill.mjs --commit   # writes changes (backup first)
//   node scripts/encode_decks_backfill.mjs --verify   # re-read a sample, decode, confirm
//
// Requires SUPABASE_URL + SUPABASE_SERVICE_KEY (service_role bypasses RLS so
// ALL users' decks are reachable). Read from env, else parsed from ./.env.

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dir = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dir, "..");

// ── credentials ────────────────────────────────────────────────────────────
function loadEnv(){
  const out = {
    SUPABASE_URL: process.env.SUPABASE_URL,
    SUPABASE_SERVICE_KEY: process.env.SUPABASE_SERVICE_KEY,
  };
  if(out.SUPABASE_URL && out.SUPABASE_SERVICE_KEY) return out;
  try {
    const txt = readFileSync(join(ROOT, ".env"), "utf8");
    for(const line of txt.split(/\r?\n/)){
      const m = line.match(/^\s*([A-Z_]+)\s*=\s*(.*)\s*$/);
      if(!m) continue;
      const k = m[1]; let v = m[2];
      if((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1,-1);
      if(k === "SUPABASE_URL" && !out.SUPABASE_URL) out.SUPABASE_URL = v;
      if(k === "SUPABASE_SERVICE_KEY" && !out.SUPABASE_SERVICE_KEY) out.SUPABASE_SERVICE_KEY = v;
    }
  } catch {}
  return out;
}
const { SUPABASE_URL, SUPABASE_SERVICE_KEY } = loadEnv();
if(!SUPABASE_URL || !SUPABASE_SERVICE_KEY){
  console.error("Missing SUPABASE_URL / SUPABASE_SERVICE_KEY (env or .env)"); process.exit(1);
}
const REST = SUPABASE_URL.replace(/\/$/,"") + "/rest/v1";
const H = {
  apikey: SUPABASE_SERVICE_KEY,
  Authorization: "Bearer " + SUPABASE_SERVICE_KEY,
  "Content-Type": "application/json",
};

// ── codec (must match Index.html) ────────────────────────────────────────────
const DECK_ENC_KEY_B64 = "TFS-sPPVpi6lHP4MDDD1_VMS5csp0eggEnIIgqcCVYo";
const DECK_ENC_PREFIX = "e1:";
let _aes = null, _mac = null;
function b64e(bytes){ let s=""; for(const b of bytes) s+=String.fromCharCode(b); return btoa(s).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,""); }
function b64d(str){ str=String(str).replace(/-/g,"+").replace(/_/g,"/"); while(str.length%4) str+="="; const bin=atob(str); const out=new Uint8Array(bin.length); for(let i=0;i<bin.length;i++) out[i]=bin.charCodeAt(i); return out; }
async function keys(){ if(_aes) return; const raw=b64d(DECK_ENC_KEY_B64); _aes=await crypto.subtle.importKey("raw",raw,{name:"AES-GCM"},false,["encrypt","decrypt"]); _mac=await crypto.subtle.importKey("raw",raw,{name:"HMAC",hash:"SHA-256"},false,["sign"]); }
const TE=new TextEncoder(), TD=new TextDecoder();
async function encRnd(plain){ if(plain==null) return plain; await keys(); const iv=crypto.getRandomValues(new Uint8Array(12)); const ct=new Uint8Array(await crypto.subtle.encrypt({name:"AES-GCM",iv},_aes,TE.encode(String(plain)))); const buf=new Uint8Array(12+ct.length); buf.set(iv,0); buf.set(ct,12); return DECK_ENC_PREFIX+b64e(buf); }
async function encDet(plain){ if(plain==null) return plain; await keys(); const sig=new Uint8Array(await crypto.subtle.sign("HMAC",_mac,TE.encode("iv:"+String(plain)))); const iv=sig.slice(0,12); const ct=new Uint8Array(await crypto.subtle.encrypt({name:"AES-GCM",iv},_aes,TE.encode(String(plain)))); const buf=new Uint8Array(12+ct.length); buf.set(iv,0); buf.set(ct,12); return DECK_ENC_PREFIX+b64e(buf); }
async function dec(token){ if(typeof token!=="string"||!token.startsWith(DECK_ENC_PREFIX)) return token; try{ await keys(); const buf=b64d(token.slice(DECK_ENC_PREFIX.length)); const iv=buf.slice(0,12), ct=buf.slice(12); return TD.decode(await crypto.subtle.decrypt({name:"AES-GCM",iv},_aes,ct)); }catch{ return token; } }
const isEnc = (v) => typeof v === "string" && v.startsWith(DECK_ENC_PREFIX);

// ── PostgREST helpers (service_role) ─────────────────────────────────────────
async function selectAll(path, select){
  const rows = [];
  const PAGE = 1000;
  for(let from=0; ; from+=PAGE){
    const url = `${REST}/${path}?select=${encodeURIComponent(select)}`;
    const r = await fetch(url, { headers: { ...H, Range: `${from}-${from+PAGE-1}`, "Range-Unit":"items", Prefer:"count=exact" } });
    if(!r.ok && r.status!==206) throw new Error(`${path} ${r.status}: ${await r.text()}`);
    const batch = await r.json();
    rows.push(...batch);
    if(batch.length < PAGE) break;
  }
  return rows;
}
async function patch(path, filters, body){
  const qs = Object.entries(filters).map(([k,v]) => `${k}=eq.${encodeURIComponent(v)}`).join("&");
  const r = await fetch(`${REST}/${path}?${qs}`, { method:"PATCH", headers:{...H, Prefer:"return=minimal"}, body: JSON.stringify(body) });
  if(!r.ok) throw new Error(`PATCH ${path} ${r.status}: ${await r.text()}`);
}

// ── main ─────────────────────────────────────────────────────────────────────
const COMMIT = process.argv.includes("--commit");
const VERIFY = process.argv.includes("--verify");

async function verify(){
  const decks = await selectAll("decks", "id,user_id,name,description");
  const cards = await selectAll("deck_cards", "deck_id,card_id,printing,quantity");
  const userDecks = decks.filter(d => d.user_id);
  const encNames = userDecks.filter(d => isEnc(d.name)).length;
  const encCards = cards.filter(c => isEnc(c.card_id)).length;
  console.log(`user decks: ${userDecks.length} (${encNames} encrypted names)`);
  console.log(`deck_cards: ${cards.length} (${encCards} encrypted card_ids)`);
  // Round-trip a sample.
  let bad = 0;
  for(const d of userDecks.slice(0,5)){
    const n = await dec(d.name);
    console.log(`  deck ${d.id.slice(0,8)}  name → "${n}"`);
    if(isEnc(n)) bad++;
  }
  for(const c of cards.filter(c=>isEnc(c.card_id)).slice(0,5)){
    const cid = await dec(c.card_id);
    console.log(`  card ${c.deck_id.slice(0,8)}  card_id → "${cid}"  qty ${c.quantity}`);
    if(isEnc(cid)) bad++;
  }
  console.log(bad ? `\n⚠ ${bad} sample(s) failed to decode` : "\n✓ all sampled rows decode cleanly");
  process.exit(bad ? 1 : 0);
}

async function main(){
  if(VERIFY) return verify();

  console.log(`Mode: ${COMMIT ? "COMMIT (writes)" : "DRY RUN (reads only)"}\n`);
  const decks = await selectAll("decks", "id,user_id,name,description");
  const cards = await selectAll("deck_cards", "deck_id,card_id,printing,quantity");
  console.log(`Fetched ${decks.length} decks, ${cards.length} deck_cards rows.`);

  // Backup EVERYTHING first (even in dry-run — cheap insurance).
  const stamp = new Date().toISOString().replace(/[:.]/g,"-");
  const bdir = join(ROOT, "scripts", "backups");
  mkdirSync(bdir, { recursive: true });
  writeFileSync(join(bdir, `decks_${stamp}.json`), JSON.stringify(decks, null, 0));
  writeFileSync(join(bdir, `deck_cards_${stamp}.json`), JSON.stringify(cards, null, 0));
  console.log(`Backups written to scripts/backups/*_${stamp}.json`);

  const userDecks = decks.filter(d => d.user_id); // skip tournament/ownerless
  const userDeckIds = new Set(userDecks.map(d => d.id));

  // Plan deck header updates.
  let nameN = 0, descN = 0, alreadyDeck = 0;
  const deckPatches = [];
  for(const d of userDecks){
    const body = {};
    if(d.name != null && !isEnc(d.name)) { body.name = await encRnd(d.name); nameN++; }
    if(d.description != null && !isEnc(d.description)) { body.description = await encRnd(d.description); descN++; }
    if(Object.keys(body).length) deckPatches.push({ id: d.id, body });
    else alreadyDeck++;
  }

  // Plan card_id updates (user decks only).
  let cardN = 0, alreadyCard = 0, skipTourn = 0;
  const cardPatches = [];
  for(const c of cards){
    if(!userDeckIds.has(c.deck_id)) { skipTourn++; continue; }
    if(isEnc(c.card_id)) { alreadyCard++; continue; }
    cardPatches.push({
      match: { deck_id: c.deck_id, card_id: c.card_id, printing: c.printing },
      body: { card_id: await encDet(c.card_id) },
    });
    cardN++;
  }

  console.log(`\nPlanned changes:`);
  console.log(`  deck names to encrypt:        ${nameN}`);
  console.log(`  deck descriptions to encrypt: ${descN}`);
  console.log(`  deck_cards card_ids:          ${cardN}`);
  console.log(`  already-encrypted decks:      ${alreadyDeck}  cards: ${alreadyCard}`);
  console.log(`  tournament/ownerless cards left plaintext: ${skipTourn}`);

  if(!COMMIT){
    console.log(`\nDRY RUN — nothing written. Re-run with --commit to apply.`);
    return;
  }

  console.log(`\nApplying deck header patches…`);
  let done = 0;
  for(const p of deckPatches){ await patch("decks", { id: p.id }, p.body); if(++done % 25 === 0) console.log(`  ${done}/${deckPatches.length}`); }
  console.log(`  ${deckPatches.length} deck rows updated.`);

  console.log(`Applying card_id patches…`);
  done = 0;
  for(const p of cardPatches){ await patch("deck_cards", p.match, p.body); if(++done % 100 === 0) console.log(`  ${done}/${cardPatches.length}`); }
  console.log(`  ${cardPatches.length} deck_cards rows updated.`);

  console.log(`\n✓ Backfill complete. Run with --verify to confirm round-trips.`);
}

main().catch(e => { console.error("\nFAILED:", e.message); process.exit(1); });
