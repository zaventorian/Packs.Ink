// Repair deck_cards rows left pointing at a retired crd_prestage_* stand-in.
//
// retire_prestaged.py re-pointed decks by PLAINTEXT card_id, but deck_cards.card_id
// is stored encrypted ("e1:..."), so no deck row ever matched and every deck holding
// a stand-in showed "(unknown)" once the stand-in was deleted (2026-10-02, Hyperia City).
// This decrypts every deck card id, finds the ones with no cards row, maps
// crd_prestage_set<N>_<cn> -> the real card in set code N with that collector number,
// and re-points the (re-encrypted) row, merging quantity when the target exists.
//
//   node scripts/repair_orphan_deck_cards.mjs            # dry run
//   node scripts/repair_orphan_deck_cards.mjs --commit   # writes (backup JSON first)
import fs from "fs"; import crypto from "crypto";
const COMMIT = process.argv.includes("--commit");
const env = Object.fromEntries(fs.readFileSync(new URL("../.env", import.meta.url),"utf8").split(/\r?\n/).filter(l=>l.includes("=")).map(l=>[l.slice(0,l.indexOf("=")), l.slice(l.indexOf("=")+1).trim()]));
const U = env.SUPABASE_URL, K = env.SUPABASE_SERVICE_KEY;
const H = {apikey:K, Authorization:`Bearer ${K}`, "Content-Type":"application/json"};
const KEY = Buffer.from("TFS-sPPVpi6lHP4MDDD1_VMS5csp0eggEnIIgqcCVYo".replace(/-/g,"+").replace(/_/g,"/")+"=", "base64");
const b64u = b => b.toString("base64").replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,"");
const unb64u = s => Buffer.from(s.replace(/-/g,"+").replace(/_/g,"/"), "base64");
function dec(t){ if(typeof t!=="string"||!t.startsWith("e1:")) return t;
  const b=unb64u(t.slice(3)); const d=crypto.createDecipheriv("aes-256-gcm",KEY,b.subarray(0,12));
  d.setAuthTag(b.subarray(b.length-16)); return Buffer.concat([d.update(b.subarray(12,b.length-16)),d.final()]).toString("utf8"); }
function encDet(plain){ const iv=crypto.createHmac("sha256",KEY).update("iv:"+plain).digest().subarray(0,12);
  const c=crypto.createCipheriv("aes-256-gcm",KEY,iv); const ct=Buffer.concat([c.update(Buffer.from(plain,"utf8")),c.final()]);
  return "e1:"+b64u(Buffer.concat([iv,ct,c.getAuthTag()])); }
async function all(path){ let out=[],from=0; for(;;){ const r=await fetch(`${U}/rest/v1/${path}`,{headers:{...H,Range:`${from}-${from+999}`,"Range-Unit":"items"}}); const j=await r.json(); if(!Array.isArray(j)) throw new Error(JSON.stringify(j)); out.push(...j); if(j.length<1000)break; from+=1000;} return out; }
async function must(r){ if(!r.ok) throw new Error(r.status+" "+await r.text()); }

const cards = await all("cards?select=id,set_id,collector_number&order=id");
const ids = new Set(cards.map(c=>c.id));
const sets = await all("sets?select=id,code&order=id");
const setByCode = new Map(sets.map(s=>[String(s.code), s.id]));
// Legacy client-only ids that were later given a real cards row.
const ALIAS = {"extras:544487":"crd_custom_544487_piglet_pooh"};
const byKey = new Map(cards.filter(c=>!c.id.startsWith("crd_prestage_")).map(c=>[c.set_id+"|"+String(c.collector_number).split("/")[0].replace(/^0+/,""), c.id]));
const dc = await all("deck_cards?select=deck_id,card_id,printing,quantity&order=deck_id,card_id,printing");

// Self-check: our encryption must reproduce a stored token byte for byte.
const probe = dc.find(r=>typeof r.card_id==="string"&&r.card_id.startsWith("e1:"));
if(probe && encDet(dec(probe.card_id))!==probe.card_id) throw new Error("encDet does not match the stored ciphertext; refusing to write");

const plan=[], skipped=new Map();
for(const r of dc){
  const id=dec(r.card_id); if(ids.has(id)) continue;
  const m=/^crd_prestage_set(\d+)_(\d+)$/.exec(id);
  const real = ALIAS[id] || (m && byKey.get(setByCode.get(m[1])+"|"+m[2]));
  if(real) plan.push({...r, old:id, real}); else skipped.set(id,(skipped.get(id)||0)+1);
}
console.log(`${dc.length} deck rows; ${plan.length} repairable, ${skipped.size} unrepairable id(s):`, [...skipped.keys()].join(", ")||"none");
for(const p of plan) console.log(`  deck ${p.deck_id.slice(0,8)} ${p.old} -> ${p.real} x${p.quantity} (${p.printing})`);
if(!COMMIT) console.log("Dry run. Re-run with --commit.");

if(COMMIT) fs.writeFileSync(new URL(`./repair_orphan_deck_cards_backup_${Date.now()}.json`, import.meta.url), JSON.stringify(plan,null,1));
const have = new Map(dc.map(r=>[r.deck_id+"|"+r.card_id+"|"+r.printing, r]));
const rowUrl=(deck,cid,pr)=>`${U}/rest/v1/deck_cards?deck_id=eq.${deck}&card_id=eq.${encodeURIComponent(cid)}&printing=eq.${encodeURIComponent(pr)}`;
for(const p of COMMIT?plan:[]){
  const newEnc=encDet(p.real), tgt=have.get(p.deck_id+"|"+newEnc+"|"+p.printing);
  if(tgt){
    const q=Math.min(99,(tgt.quantity||0)+(p.quantity||0));
    await must(await fetch(rowUrl(p.deck_id,newEnc,p.printing),{method:"PATCH",headers:H,body:JSON.stringify({quantity:q})}));
    await must(await fetch(rowUrl(p.deck_id,p.card_id,p.printing),{method:"DELETE",headers:H}));
  } else {
    await must(await fetch(rowUrl(p.deck_id,p.card_id,p.printing),{method:"PATCH",headers:H,body:JSON.stringify({card_id:newEnc})}));
  }
}
if(COMMIT) console.log("Repaired", plan.length, "row(s).");

// ---- deck_versions: the same ids live inside each snapshot's jsonb `cards` array ----
const vers = await all("deck_versions?select=deck_id,version,cards&order=deck_id,version");
const vplan=[];
for(const v of vers){
  let changed=false; const cardsOut=[];
  for(const c of v.cards||[]){
    const id=dec(c.card_id); let nid=id;
    if(!ids.has(id)){ if(ALIAS[id]){nid=ALIAS[id];changed=true;} else { const m=/^crd_prestage_set(\d+)_(\d+)$/.exec(id); const real=m&&byKey.get(setByCode.get(m[1])+"|"+m[2]); if(real){nid=real;changed=true;} } }
    cardsOut.push(nid===id?c:{...c,card_id:encDet(nid)});
  }
  if(changed) vplan.push({deck_id:v.deck_id,version:v.version,before:v.cards,after:cardsOut});
}
console.log(`${vers.length} versions; ${vplan.length} need repair`);
if(COMMIT && vplan.length){
  fs.writeFileSync(new URL(`./repair_orphan_deck_versions_backup_${Date.now()}.json`, import.meta.url), JSON.stringify(vplan.map(({deck_id,version,before})=>({deck_id,version,cards:before})),null,1));
  for(const v of vplan) await must(await fetch(`${U}/rest/v1/deck_versions?deck_id=eq.${v.deck_id}&version=eq.${v.version}`,{method:"PATCH",headers:H,body:JSON.stringify({cards:v.after})}));
  console.log("Repaired", vplan.length, "version snapshot(s).");
}
