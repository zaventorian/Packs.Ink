"""Selection-policy A/B over the box cache: does adding the boxes directly
BELOW the tallest (name) box — the version-subtitle band — fix the version
coin-flips without character regressions?

OLD policy (shipped worker): 6 tallest letter-boxes.
NEW policy: tallest box's below-adjacent boxes are FORCED into the set
(subtitle band), then fill by height to a cap of 9.

Both policies run through rankNames_py (calibrated matcher mirror) + the
body-text version tiebreak (mirror of scanner.js rankVersionsByBody incl. the
foreign-line filter) and score against the image-verified truth table.
"""
import os, sys, json, re
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ocr_match_validate import rankNames_py, prep_card

BENCH = os.path.join(HERE, "data", "bench")
cache = json.load(open(os.path.join(BENCH, "_boxcache.json"), encoding="utf-8"))
cards = json.load(open(os.path.join(HERE, "..", "..", "scanner", "text.json"), encoding="utf-8"))
for c in cards: prep_card(c)

# ---- body tiebreak mirror (scanner.js rankVersionsByBody, b281 semantics) ----
def canon(s):
    s = (s or "").lower()
    s = re.sub(r"['’`._]", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = s.replace("rn", "m").replace("vv", "w")
    return re.sub(r"\s+", "", s)

def tris(s): return {s[i:i+3] for i in range(len(s)-2)} if len(s) >= 3 else set()

by_char = {}
char_canons = set()
for c in cards:
    nm = (c.get("n") or "").lower()
    by_char.setdefault(nm, []).append(c)
    cn = canon(c.get("n") or "")
    if len(cn) >= 5: char_canons.add(cn)

def rank_versions_by_body(char_name, lines):
    group = by_char.get(char_name.lower(), [])
    if len(group) < 2: return None
    own = canon(char_name)
    use = []
    for l in lines:
        lc = canon(l)
        foreign = any(o in lc for o in char_canons
                      if o != own and own not in o and o not in own)
        if not foreign: use.append(l)
    if not use: use = lines
    q = canon(" ".join(use))
    if own: q = q.replace(own, "", 1)
    Q = tris(q)
    if len(Q) < 12: return None
    byv = {}
    for c in group:
        v = c.get("v") or ""
        sc = len(Q & tris(canon(c.get("b") or ""))) / len(Q)
        if v not in byv or sc > byv[v]: byv[v] = sc
    order = sorted(byv.items(), key=lambda x: -x[1])
    if len(order) < 2: return None
    (v1, s1), (_, s2) = order[0], order[1]
    if s1 >= 0.22 and (s1 - s2) >= 0.12: return v1
    return None

# ---- flavor-attribution hijack rescue ---------------------------------------
# A card quoting character X ("—Monterey Jack") hijacks the name match when the
# real card's NAME doesn't OCR but its rules/flavor DO. Detector: the lines'
# body evidence points overwhelmingly at a card that QUOTES X while X's own
# cards have ~no body support. Quote-index: char name -> cards whose b contains
# that name (excluding the char's own cards).
quote_index = {}
for c in cards:
    bc = canon(c.get("b") or "")
    for nm in by_char:
        if nm == (c.get("n") or "").lower(): continue
        nc = canon(nm)
        if len(nc) >= 5 and nc in bc:
            quote_index.setdefault(nm, []).append(c)

def hijack_rescue(top_char, lines):
    """returns a rescue card dict or None.

    MARGIN-DOMINANT rule (recalibrated 2026-07-19 on the full 315-row field
    corpus): the old own<=0.15 gate blocked every real hijack — generic
    rules-text trigrams inflate the top char's own-body score (id 265: quoter
    0.798 vs own 0.333). Fire when the quoter's containment DOMINATES:
    best>=0.35, own<=0.45, margin>=0.30, >=25 query trigrams. On the field
    corpus this fires on exactly the 2 verified hijacks (161 Merlin->Develop
    Your Brain, 265 Monterey Jack->Dale RFHS) and on ZERO verified-correct
    rows; own-dominant rows (a real Monterey Jack scan, own 0.76) never fire.
    """
    quoters = quote_index.get(top_char.lower())
    if not quoters: return None
    q = canon(" ".join(lines))
    Q = tris(q)
    if len(Q) < 25: return None
    own_best = 0.0
    for c in by_char.get(top_char.lower(), []):
        sc = len(Q & tris(canon(c.get("b") or ""))) / len(Q)
        if sc > own_best: own_best = sc
    best, best_sc = None, 0.0
    for c in quoters:
        sc = len(Q & tris(canon(c.get("b") or ""))) / len(Q)
        if sc > best_sc: best_sc, best = sc, c
    if best is not None and best_sc >= 0.35 and own_best <= 0.45 and (best_sc - own_best) >= 0.30:
        return best
    return None

# ---- selection policies -----------------------------------------------------
def has_letter(t): return re.search(r"[A-Za-z]", t) is not None

def sel_old(boxes):
    cand = [b for b in boxes if len(b["t"].strip()) >= 2 and has_letter(b["t"])]
    cand.sort(key=lambda b: -b["bh"])
    return [b["t"] for b in cand[:6]]

def sel_new(boxes):
    cand = [b for b in boxes if len(b["t"].strip()) >= 2 and has_letter(b["t"])]
    if not cand: return []
    by_h = sorted(cand, key=lambda b: -b["bh"])
    name = by_h[0]
    nh = name["y1"] - name["y0"]
    nw = name["x1"] - name["x0"]
    sub = [b for b in cand if b is not name
           and name["y1"] - 0.3 * nh <= b["y0"] <= name["y1"] + 2.6 * nh
           and b["x0"] < name["x0"] + nw and b["x1"] > name["x0"] - 0.5 * nw]
    sub.sort(key=lambda b: b["y0"])
    keep = [name] + sub[:3]
    for b in by_h[1:]:
        if len(keep) >= 9: break
        if b not in keep: keep.append(b)
    return [b["t"] for b in keep]

# ---- truth table (image-verified this week; version-level) ------------------
TRUTH = {
  # batch 2 (ids 154-180)
  157:("Mickey Mouse","Expedition Leader"),159:("Dale","Ready for His Shot"),160:("Basil","Undercover Detective"),
  163:("Dale","Ready for His Shot"),165:("Little John","Camp Cook"),166:("Go Go Tomago","Darting Dynamo"),
  169:("Lady","Family Dog"),170:("Tramp","Dapper Rascal"),172:("Lady","Elegant Spaniel"),
  176:("Mulan","Resourceful Recruit"),177:("Mickey Mouse","Amber Champion"),178:("Rajah","Devoted Protector"),
  # batch 4 (213-234)
  214:("Rhino","One-Sixteenth Wolf"),216:("Mowgli","Man Cub"),218:("Mickey Mouse","Amber Champion"),
  220:("Mowgli","Man Cub"),221:("Mowgli","Man Cub"),222:("Rhino","One-Sixteenth Wolf"),
  223:("Chief Powhatan","Protective Leader"),224:("Rapunzel","Gifted with Healing"),
  225:("Rapunzel","Gifted with Healing"),226:("Rapunzel","Gifted with Healing"),
  227:("Chief Powhatan","Protective Leader"),228:("Rapunzel","Gifted with Healing"),
  229:("Rapunzel","Gifted with Healing"),230:("Mulan","Resourceful Recruit"),
  231:("Mulan","Resourceful Recruit"),232:("Mulan","Resourceful Recruit"),233:("Mulan","Resourceful Recruit"),
  # batch 5 (236-303)
  239:("Little John","Camp Cook"),240:("Mulan","Resourceful Recruit"),241:("Mulan","Resourceful Recruit"),
  242:("Mulan","Resourceful Recruit"),243:("Mulan","Resourceful Recruit"),244:("Rapunzel","Gifted with Healing"),
  246:("Rhino","One-Sixteenth Wolf"),250:("Mickey Mouse","Amber Champion"),254:("Rhino","One-Sixteenth Wolf"),
  257:("Nala","Mischievous Cub"),261:("Dale","Ready for His Shot"),265:("Dale","Ready for His Shot"),
  281:("Rajah","Devoted Protector"),289:("Dale","Ready for His Shot"),293:("Mickey Mouse","Expedition Leader"),
  296:("Rhino","One-Sixteenth Wolf"),300:("Rajah","Devoted Protector"),
}


# batch 6 (ids 305-407, binder/toploader/enchanted session on v10) — every photo
# eyeballed 2026-07-19 (Workflow fan-out ids 305-311/326-374 + self-read the rest)
TRUTH.update({
  305:('Henry J. Waternoose III','Chief Executive Officer'),
  306:('Randall Boggs','Envious Coworker'),
  307:('Roz','Always Watching'),
  308:('Dash Parr','Dodgeball Dynamo'),
  309:('Hundred Acre Wood','Hunny Campsite'),
  310:('Jasmine','Vine Expert'),
  311:('Meilin Lee','Losing Control'),
  312:('Winnie the Pooh','Hunny Archmage'),
  313:('Mother Gothel','Evil as Ever'),
  314:('Kevin','Flightless Bird'),
  315:('Heihei','Created by the Vine'),
  317:('Mulan','Created by the Vine'),
  318:('Mulan','Created by the Vine'),
  319:('Megavolt','Electrical Menace'),
  320:('Kronk','Meat Hut Cook'),
  321:('Merida','Wisp Conjurer'),
  322:('The Horned King','Merciless Master'),
  323:('Dash Parr & Violet Parr','Super Siblings'),
  324:('Mickey Mouse & Minnie Mouse','Adventuring Duo'),
  325:('Pocahontas & Meeko','Adventurous Friends'),
  326:('Woody & Buzz Lightyear','Best Buddies'),
  327:('Tinker Bell','Giant Fairy'),
  328:('Look at This Family',''),
  329:('Ariel','Sonic Warrior'),
  330:('Spooky Sight',''),
  331:('Mickey Mouse','Detective'),
  332:('Mickey Mouse','Detective'),
  333:('Magic Broom','Bucket Brigade'),
  334:('Maleficent','Biding Her Time'),
  335:('Snow White','Unexpected Houseguest'),
  336:('Cruella De Vil','Fashionable Cruiser'),
  337:('Weight Set',''),
  338:('Namaari','Morning Mist'),
  339:('Alice','Growing Girl'),
  340:('Cinderella','Ballroom Sensation'),
  341:('Beast','Relentless'),
  342:('Elsa','Spirit of Winter'),
  343:('Mulan','Enemy of Entanglement'),
  344:("Antonio's Jaguar",'Faithful Companion'),
  345:('Magica De Spell','Shadow Form'),
  346:('Royal Guard','Octopus Soldier'),
  347:('Into the Unknown',''),
  348:('Jafar','High Sultan of Lorcana'),
  349:('Pull the Lever!',''),
  352:('Flynn Rider','Breaking and Entering'),
  353:('Ursula','Power Hungry'),
  354:('Merlin','Goat'),
  355:('Aladdin','Heroic Outlaw'),
  356:('Sudden Scare',''),
  357:('Wreck-It Ralph','Ham Hands'),
  358:('Belle','Accomplished Mystic'),
  359:('Tamatoa','Happy as a Clam'),
  360:('Dumbo','Ninth Wonder of the Universe'),
  361:('Infra-Pink Ultra Scan Specs',''),
  362:('Omnidroid','V.8'),
  363:('Windstorm',''),
  364:('Rafiki','Mystical Fighter'),
  365:('Merida','Formidable Archer'),
  366:('Morph','Little Imitator'),
  367:('You Broke My Smolder',''),
  368:('Three Arrows',''),
  369:('Three Arrows',''),
  370:('Syndrome','Out for Revenge'),
  371:('Merida','Formidable Archer'),
  372:('Omnidroid','Scanning for Threats'),
  373:('Omnidroid','V.8'),
  374:('Three Arrows',''),
  375:('Infra-Pink Ultra Scan Specs',''),
  376:('Junior Woodchuck Guidebook',''),
  377:('Hades','Looking for a Deal'),
  378:('Omnidroid','Ultimate Iteration'),
  379:('Hades','Looking for a Deal'),
  380:('Omnidroid','V.10'),
  381:('Omnidroid','V.8'),
  382:('Morph','Little Imitator'),
  383:('Omnidroid','V.10'),
  384:('Rafiki','Mystical Fighter'),
  385:('Incrediboy','Buddy Pine'),
  386:('Morph','Little Imitator'),
  387:('Junior Woodchuck Guidebook',''),
  388:('Incrediboy','Buddy Pine'),
  389:('Omnidroid','Ultimate Iteration'),
  390:('Syndrome','Out for Revenge'),
  391:('Omnidroid','V.8'),
  392:('Rafiki','Mystical Fighter'),
  393:('Omnidroid','Scanning for Threats'),
  394:('He Hurled His Thunderbolt',''),
  395:('Three Arrows',''),
  396:('Syndrome','Out for Revenge'),
  397:('He Hurled His Thunderbolt',''),
  398:('You Broke My Smolder',''),
  399:('Omnidroid','Scanning for Threats'),
  400:('He Hurled His Thunderbolt',''),
  401:('Lexington','Small in Stature'),
  402:('Hades','Looking for a Deal'),
  403:('Lexington','Small in Stature'),
  404:('Rafiki','Mystical Fighter'),
  405:('Hades','Looking for a Deal'),
  407:('Hudson','Determined Reader'),
})

def keyid(fname):
    m = re.match(r"(?:h|b4|b5|b6)_(\d+)_?", fname)
    return int(m.group(1)) if m else None

RUN_EVAL = (__name__ == "__main__")
POLICIES = (("old", sel_old, False), ("new", sel_new, False), ("new+rescue", sel_new, True))
stats = {p[0]: [0,0,0,0] for p in POLICIES}   # charOK+verOK, charOK+verWRONG, charWRONG, no-answer
detail = []
rescues = []
for fname, entry in (sorted(cache.items()) if RUN_EVAL else []):
    rid = keyid(fname)
    if rid not in TRUTH or "boxes" not in entry: continue
    t_char, t_ver = TRUTH[rid]
    for pol, sel, use_rescue in POLICIES:
        lines = sel(entry["boxes"])
        r = rankNames_py(lines, cards, 6)
        top = r["top"][0] if r["top"] else None
        if not top:
            stats[pol][3] += 1; continue
        g_char, g_ver = top.get("n") or top.get("name") or "", top.get("v") or top.get("version") or ""
        if use_rescue:
            rz = hijack_rescue(g_char, lines)
            if rz is not None:
                rescues.append(f"  rescue {rid}: {g_char} → {rz.get('n')}-{rz.get('v')} (truth {t_char}-{t_ver})")
                g_char, g_ver = rz.get("n") or "", rz.get("v") or ""
        bv = rank_versions_by_body(g_char, lines)
        if bv is not None: g_ver = bv
        if g_char.lower() != t_char.lower():
            stats[pol][2] += 1
            if pol == "new+rescue": detail.append(f"  charWRONG {rid}: {g_char} (truth {t_char})")
        elif g_ver == t_ver:
            stats[pol][0] += 1
        else:
            stats[pol][1] += 1
            if pol == "new+rescue": detail.append(f"  verWRONG {rid}: {g_char}-{g_ver} (truth {t_ver}) bodyDecided={bv is not None}")

for pol, _, _ in (POLICIES if RUN_EVAL else []):
    ok, vw, cw, ab = stats[pol]
    print(f"{pol:11s}: char+ver RIGHT {ok} | right-char wrong-ver {vw} | char WRONG {cw} | no-answer {ab}")
print("\nrescues fired:"); print("\n".join(rescues) if rescues else "  none")
print("\nfinal-policy misses:"); print("\n".join(detail) if detail else "  none")
