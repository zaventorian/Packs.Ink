"""
intl_cards.py - the pure half of the localized-card pipeline: parse each
official source, and match every foreign printing to OUR card row.

Sources (checked 2026-10-03; see docs/claude/i18n.md for the full survey):

  de / fr / it  cards.disneylorcana.com/<locale>/  - Ravensburger's own gallery.
                One page embeds the whole catalog; every card carries a
                `culture_invariant_id` that is THE SAME across languages, so a
                German card is tied to its English twin by id, never by name.
                Art: ravensburger.cloud/ci/<key>/card (800x1116 AVIF, ACAO:*).
  ja            takaratomy.co.jp/products/disneylorcana/ - Takara Tomy, the
                Japanese publisher. A CSRF-token POST API, 100 cards a page.
                Art: .../cardlist/img/card/<card_file>.png (760x1062 PNG). The
                file name embeds the English set + name slug
                (`184_DLCS3_UTC_MrSmee_BumblingMate_JA`), which is the second,
                independent check on every Japanese match.

  Lorcast and duels.ink, the other two sources the site already reads, are
  English-only (Lorcast's `lang` field only ever says en; duels serves en art).

The matching rule, both families: find the printing by SET + COLLECTOR NUMBER,
then CONFIRM it by name. A number match whose name disagrees is refused rather
than trusted - a wrong picture on a card page is worse than an English one.

Every function here is pure (no network, no database) so
scripts/test_intl_cards.py can pin it offline. The network + upload half is
sync_intl_cards.py.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

LANGS = ("ja", "de", "fr", "it")
GALLERY_LOCALES = {"en": "en-US", "de": "de-DE", "fr": "fr-FR", "it": "it-IT"}

# Gallery card_identifier set token -> our sets.code. A bare total ("204") means
# the mainline set named by the trailing number; these are the promo families.
GALLERY_CODE = {
    "P1": "P1", "P2": "P2", "P3": "P3", "P4": "P4",
    "C1": "cp", "C2": "C2", "D23": "D23", "DIS": "DIS", "PD1": "PD1",
    "CC1": "CC1", "CC2": "CC2", "RPH": "RPH",
}
# Gallery quest numbers -> our sets.code. Q1 (Deep Trouble) and Q2 (Palace
# Heist) are Extras & Oddities rows with no `sets` row of their own, so they
# fall through to the name match.
GALLERY_QUEST = {"Q3": "Q3"}


def compact(s: str | None) -> str:
    """Letters and digits only, lowercased, accents folded: the form two
    spellings of one English card name agree on ('Te Ka' / 'Te Kā',
    'Putting It All Together' / 'PuttingitAllTogether')."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", s.lower())


def name_key(name: str | None, version: str | None) -> str:
    return compact(name) + compact(version)


def similar(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------- our catalog

class Catalog:
    """Our `cards` rows, indexed the ways the matchers need."""

    def __init__(self, cards: list[dict], sets: list[dict]):
        self.cards = cards
        self.by_id = {c["id"]: c for c in cards}
        code_of = {s["id"]: (s.get("code") or "") for s in sets}
        self.code_of_card = {c["id"]: code_of.get(c["set_id"], "") for c in cards}
        self.by_set_cn: dict[tuple[str, str], list[dict]] = {}
        self.by_set: dict[str, list[dict]] = {}
        self.by_key: dict[str, list[dict]] = {}
        for c in cards:
            code = self.code_of_card[c["id"]]
            cn = str(c.get("collector_number") or "").strip().lower()
            self.by_set_cn.setdefault((code, cn), []).append(c)
            self.by_set.setdefault(code, []).append(c)
            self.by_key.setdefault(name_key(c.get("name"), c.get("version")), []).append(c)

    def key(self, c: dict) -> str:
        return name_key(c.get("name"), c.get("version"))


# ---------------------------------------------------------- official gallery

_IDENT = re.compile(r"^(\S+)/(\S+) ([A-Z]{2}) (\S+)$")


def parse_identifier(ident: str) -> dict | None:
    """'27/204 DE 14' -> {cn:'27', code:'14', lang:'de'}; '12/P4 EN 13' ->
    {cn:'12', code:'P4', ...}; '5/204 EN Q3' -> code 'Q3'. Returns None for the
    handful of irregular ones ('1TFC EN 1/P1'), which take the name match."""
    m = _IDENT.match((ident or "").strip())
    if not m:
        return None
    cn, tot, lang, tail = m.groups()
    if tot in GALLERY_CODE:
        code = GALLERY_CODE[tot]
    elif tail in GALLERY_QUEST:
        code = GALLERY_QUEST[tail]
    elif tot.isdigit() and tail.isdigit():
        code = tail
    else:
        return None
    return {"cn": cn.lower(), "code": code, "lang": lang.lower()}


def gallery_image(card: dict) -> str | None:
    """The Regular variant's art key (detail_image_url), or the first one."""
    vs = card.get("variants") or []
    reg = next((v for v in vs if v.get("variant_id") == "Regular"), None) or (vs[0] if vs else None)
    return (reg or {}).get("detail_image_url") or None


def gallery_image_lang(card: dict) -> str | None:
    """Which language the ART is printed in, read off the CDN key
    (lorcana_de_set14_27_...). A foreign gallery still lists ~100-500 cards
    that were never printed in that language (Challenge promos, D23, most of
    Italian set 1-2), and shows them in English - those must not become a
    'German' card."""
    m = re.search(r"/ci/lorcana_([a-z]{2})_", gallery_image(card) or "")
    return m.group(1) if m else None


def gallery_name_key(card: dict) -> str:
    return name_key(card.get("name"), card.get("subtitle"))


def match_gallery_en(en_cards: list[dict], cat: Catalog) -> dict[int, dict]:
    """culture_invariant_id -> {card_id, how} for every English gallery card we
    can tie to one of our rows.

    how = 'number'  set + collector number, name confirmed
          'name'    unique name+version inside the same set (renumbered promos)
          'global'  unique name+version across the whole catalog
    """
    out: dict[int, dict] = {}
    for g in en_cards:
        cid = g.get("culture_invariant_id")
        if cid is None:
            continue
        gk = gallery_name_key(g)
        p = parse_identifier(g.get("card_identifier", ""))
        hit, how = None, None
        if p:
            cands = cat.by_set_cn.get((p["code"], p["cn"]), [])
            best = max(cands, key=lambda c: similar(cat.key(c), gk), default=None)
            if best is not None and similar(cat.key(best), gk) >= 0.85:
                hit, how = best, "number"
            else:
                same = [c for c in cat.by_set.get(p["code"], []) if cat.key(c) == gk]
                if len(same) == 1:
                    hit, how = same[0], "name"
        if hit is None:
            glob = cat.by_key.get(gk, [])
            if len(glob) == 1:
                hit, how = glob[0], "global"
        if hit is not None:
            out[cid] = {"card_id": hit["id"], "how": how}
    return out


def clean_gallery_text(raw: str | None) -> str | None:
    """Gallery markup -> plain text: \\\\Name\\\\ ability names become the name
    in caps, '%' paragraph breaks become newlines, {I}/{E}/{L}... are kept as the
    site's own symbol tokens."""
    if not raw:
        return None
    t = re.sub(r"\\\\(.+?)\\\\", lambda m: m.group(1).upper(), raw)
    t = t.replace("\\", "").replace("<", "").replace(">", "").replace("#%", "\u0000")
    t = t.replace("%", "\n").replace("\u0000", "%")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{2,}", "\n", t)
    return t.strip() or None


def gallery_rows(lang: str, loc_cards: list[dict], en_map: dict[int, dict]) -> tuple[list[dict], dict]:
    """card_localizations rows for one gallery language. Only cards whose ART
    is in `lang` become rows; stats counts what was skipped and why."""
    rows, stats = [], {"listed": len(loc_cards), "not_printed": 0, "unmatched": 0, "duplicate": 0, "rows": 0}
    seen: set[str] = set()
    for g in loc_cards:
        if gallery_image_lang(g) != lang:
            stats["not_printed"] += 1
            continue
        m = en_map.get(g.get("culture_invariant_id"))
        if not m:
            stats["unmatched"] += 1
            continue
        # Two gallery entries can resolve to one row (Moana 26/P2 is listed
        # twice). First wins, so a re-run cannot flip which art a card shows.
        if m["card_id"] in seen:
            stats["duplicate"] += 1
            continue
        seen.add(m["card_id"])
        img = gallery_image(g)
        rows.append({
            "card_id": m["card_id"], "lang": lang,
            "name": (g.get("name") or "").strip() or None,
            "version": (g.get("subtitle") or "").strip() or None,
            "text": clean_gallery_text(g.get("rules_text")),
            "flavor_text": clean_gallery_text(g.get("flavor_text")),
            "classifications": [s for s in (g.get("subtypes") or []) if s] or None,
            "image_url": None,
            "image_thumb_url": None,
            "_src_image": (img + "card") if img else None,
            "_store_key": f"{lang}/{g.get('culture_invariant_id')}",
            "_ver": img,
            "source": "ravensburger-gallery",
            "source_id": str(g.get("culture_invariant_id")),
            "source_ref": g.get("card_identifier"),
            "match_how": m["how"],
        })
    stats["rows"] = len(rows)
    return rows, stats


# --------------------------------------------------------------- Takara Tomy

TT_BASE = "https://www.takaratomy.co.jp/products/disneylorcana"
TT_IMG = TT_BASE + "/cardlist/img/card/{file}.png"
_TT_FILE = re.compile(r"^(\d+)([a-z]?)_DLC([SP])(\d+)_(.+)_([A-Z]{2})$")


def parse_tt_file(card_file: str) -> dict | None:
    """'184_DLCS3_UTC_MrSmee_BumblingMate_JA' -> {code:'3', idx:'184',
    slug:'utcmrsmeebumblingmate', lang:'ja'}. DLCS<n> is mainline set n,
    DLCP<n> is Promo Set n. The slug still carries Takara's own leading
    product-code tokens (UTC, RMC, RCEX...), so it is compared by SUFFIX."""
    m = _TT_FILE.match(card_file or "")
    if not m:
        return None
    idx, sub, kind, n, rest, lang = m.groups()
    code = n if kind == "S" else f"P{n}"
    return {"code": code, "idx": str(int(idx)) + sub, "slug": compact(rest.replace("_", "")), "lang": lang.lower()}


def slug_score(slug: str, ours: str) -> float:
    """How well Takara's file slug (codes + English name + version) names our
    card: our compact key against the same-length tail of the slug."""
    if not slug or not ours:
        return 0.0
    if slug.endswith(ours):
        return 1.0
    return similar(slug[-len(ours):], ours)


def tt_text(raw: str | None) -> str | None:
    """Takara's rules text: \\ABILITY\\ names (kept, no case to change in
    Japanese), '%' paragraph breaks."""
    if not raw or raw == "-":
        return None
    t = raw.replace("\\", "").replace("%", "\n")
    t = re.sub(r"[ \t　]+\n", "\n", t)
    return t.strip() or None


TT_RARITY = {
    "コモン": "Common", "アンコモン": "Uncommon", "レア": "Rare", "スーパーレア": "Super Rare",
    "レジェンダリー": "Legendary", "エピック": "Epic", "エンチャンテッド": "Enchanted",
    "アイコニック": "Iconic", "プロモ": "Promo",
}


def _tt_pick(j: dict, p: dict, cat: Catalog) -> tuple[dict | None, str | None]:
    cn = str(j.get("collector_number") or "").strip().lower()
    cands = cat.by_set_cn.get((p["code"], cn), []) + cat.by_set_cn.get((p["code"], p["idx"]), [])
    best = max(cands, key=lambda c: slug_score(p["slug"], cat.key(c)), default=None)
    if best is not None and slug_score(p["slug"], cat.key(best)) >= 0.8:
        return best, "number"
    pool = cat.by_set.get(p["code"], [])
    scored = sorted(((slug_score(p["slug"], cat.key(c)), c) for c in pool), key=lambda t: -t[0])
    if scored and scored[0][0] >= 0.9 and (len(scored) == 1 or scored[1][0] < scored[0][0]):
        return scored[0][1], "slug"
    return None, None


def match_tt(jp_cards: list[dict], cat: Catalog) -> tuple[list[dict], dict]:
    """card_localizations rows for Japanese. A card matches on set + printed
    collector number when the file slug agrees with our name (>= 0.8), else on
    the best slug inside the set (>= 0.9, which catches Takara's renumbered
    Into the Inklands run).

    Last, 'character': Takara sometimes names a FILE after a working title the
    English card never printed under (212_DLCS12_DonaldDuck_ObliviousTraveler
    is our 'Donald Duck - Distracted Traveler', #212 Epic). The number is then
    accepted only when the rarity agrees AND the Japanese character name is one
    a strong match has already tied to the same English character."""
    rows, stats = [], {"listed": len(jp_cards), "unparsed": 0, "unmatched": 0,
                       "by_number": 0, "by_slug": 0, "by_character": 0}
    unmatched = []
    seen: set[str] = set()
    picked: list[tuple[dict, dict | None, str | None]] = []
    jp_to_en: dict[str, set[str]] = {}
    for j in jp_cards:
        p = parse_tt_file(j.get("card_file", ""))
        hit, how = _tt_pick(j, p, cat) if p else (None, None)
        picked.append((j, hit, how))
        if hit is not None:
            jp_to_en.setdefault((j.get("card_name") or "").strip(), set()).add(compact(hit.get("name")))
    for j, hit, how in picked:
        p = parse_tt_file(j.get("card_file", ""))
        if not p:
            stats["unparsed"] += 1
            unmatched.append(j.get("card_file"))
            continue
        if hit is None:
            cn = str(j.get("collector_number") or "").strip().lower()
            want = TT_RARITY.get(j.get("rarity"))
            ens = jp_to_en.get((j.get("card_name") or "").strip(), set())
            cands = [c for c in cat.by_set_cn.get((p["code"], cn), [])
                     if compact(c.get("name")) in ens and (want is None or c.get("rarity") == want)]
            if len(cands) == 1:
                hit, how = cands[0], "character"
        if hit is None or hit["id"] in seen:
            stats["unmatched"] += 1
            unmatched.append(j.get("card_file"))
            continue
        seen.add(hit["id"])
        stats["by_" + how] += 1
        classes = j.get("classifications")
        if isinstance(classes, list):
            classes = [c.get("classification") for c in classes if isinstance(c, dict) and c.get("classification")]
        elif isinstance(classes, str) and classes not in ("", "-"):
            classes = classes.split("・")
        else:
            classes = None
        version = j.get("version")
        rows.append({
            "card_id": hit["id"], "lang": "ja",
            "name": (j.get("card_name") or "").strip() or None,
            "version": None if version in (None, "", "-") else version.strip(),
            "text": tt_text(j.get("rules_text")),
            "flavor_text": tt_text(j.get("flavor_text")),
            "classifications": classes or None,
            "image_url": None,
            "image_thumb_url": None,
            "_src_image": TT_IMG.format(file=j["card_file"]),
            "_store_key": "ja/" + re.sub(r"[^A-Za-z0-9_-]", "", j["card_file"]),
            "_ver": f"{j['card_file']}|{j.get('modified')}",
            "source": "takaratomy",
            "source_id": str(j.get("id")),
            "source_ref": j.get("card_file"),
            "match_how": how,
        })
    stats["rows"] = len(rows)
    stats["unmatched_files"] = unmatched
    return rows, stats


def text_only_rows(lang: str, rows: list[dict], cat: Catalog) -> list[dict]:
    """A NAME is shared by every printing of a card - the Enchanted, the promo,
    the reprint - even where only one of them was printed in `lang`. So once
    any printing of 'Elsa - Snow Queen' has a German name, every other printing
    of it may borrow the name (and rules text) for search and display, but
    NEVER the picture: that would show one printing's art for another.

    Returns extra rows (image_url None, match_how 'name') for our cards that
    have no row of their own in `lang`."""
    have = {r["card_id"] for r in rows}
    by_key: dict[str, dict] = {}
    for r in rows:
        c = cat.by_id.get(r["card_id"])
        if c:
            by_key.setdefault(cat.key(c), r)
    extra = []
    for c in cat.cards:
        if c["id"] in have:
            continue
        r = by_key.get(cat.key(c))
        if not r:
            continue
        extra.append({**r, "card_id": c["id"], "image_url": None, "image_thumb_url": None,
                      "_src_image": None, "_store_key": None, "_ver": None,
                      "match_how": "name", "source_ref": r.get("source_ref")})
    return extra


# ------------------------------------------------------------------- glossary

OFFICIAL_TERMS = {
    # Takara Tomy's own search form (env.js formDefault) for ja; Ravensburger's
    # gallery message catalog (Paraglide, ink_colors.* / rarity.* / type.*)
    # for de / fr / it. "Super Rare" is the one the catalog splits ("Super"
    # + a separate word), so it is written out here.
    "ink": {
        "ja": {"Amber": "アンバー", "Amethyst": "アメジスト", "Emerald": "エメラルド", "Ruby": "ルビー", "Sapphire": "サファイア", "Steel": "スティール"},
        "de": {"Amber": "Bernstein", "Amethyst": "Amethyst", "Emerald": "Smaragd", "Ruby": "Rubin", "Sapphire": "Saphir", "Steel": "Stahl"},
        "fr": {"Amber": "Ambre", "Amethyst": "Améthyste", "Emerald": "Émeraude", "Ruby": "Rubis", "Sapphire": "Saphir", "Steel": "Acier"},
        "it": {"Amber": "Ambra", "Amethyst": "Ametista", "Emerald": "Smeraldo", "Ruby": "Rubino", "Sapphire": "Zaffiro", "Steel": "Acciaio"},
    },
    "rarity": {
        "ja": {"Common": "コモン", "Uncommon": "アンコモン", "Rare": "レア", "Super Rare": "スーパーレア", "Legendary": "レジェンダリー",
               "Epic": "エピック", "Enchanted": "エンチャンテッド", "Iconic": "アイコニック", "Promo": "プロモ"},
        "de": {"Common": "Gewöhnlich", "Uncommon": "Ungewöhnlich", "Rare": "Selten", "Super Rare": "Super selten", "Legendary": "Legendär",
               "Epic": "Episch", "Enchanted": "Verzaubert", "Iconic": "Ikonisch", "Promo": "Promo"},
        "fr": {"Common": "Commune", "Uncommon": "Inhabituelle", "Rare": "Rare", "Super Rare": "Super rare", "Legendary": "Légendaire",
               "Epic": "Épique", "Enchanted": "Enchantée", "Iconic": "Iconique", "Promo": "Promo"},
        "it": {"Common": "Comune", "Uncommon": "Non comune", "Rare": "Rara", "Super Rare": "Super rara", "Legendary": "Leggendaria",
               "Epic": "Epica", "Enchanted": "Incantata", "Iconic": "Iconica", "Promo": "Promo"},
    },
    "type": {
        "ja": {"Character": "キャラクター", "Action": "アクション", "Item": "アイテム", "Location": "ロケーション", "Song": "ソング"},
        "de": {"Character": "Charakter", "Action": "Aktion", "Item": "Gegenstand", "Location": "Ort", "Song": "Lied"},
        "fr": {"Character": "Personnage", "Action": "Action", "Item": "Objet", "Location": "Lieu", "Song": "Chanson"},
        "it": {"Character": "Personaggio", "Action": "Azione", "Item": "Oggetto", "Location": "Luogo", "Song": "Canzone"},
    },
}

# Gallery set ids -> our sets.code (for localized set names).
_GALLERY_SET = {f"set{n}": str(n) for n in range(1, 40)}
_GALLERY_SET.update({"quest3": "Q3"})


def tt_set_title(s: str) -> str | None:
    """'ＴＨＥ　ＦＩＲＳＴ　ＣＨＡＰＴＥＲ　物語のはじまり' -> '物語のはじまり': Japanese
    sets are printed with the English title in full-width capitals, then the
    Japanese one. Only the Japanese half is the set's Japanese NAME."""
    if not s or s == "-":
        return None
    s = unicodedata.normalize("NFKC", s).strip()
    m = re.match(r"^[A-Z0-9 !'’.&\-:]+\s+(.+)$", s)
    return m.group(1).strip() if m else None


def derive_terms(lang: str, rows: list[dict], cat: Catalog, sets: list[dict],
                 gallery_cards: list[dict] | None = None, gallery_set_names: dict | None = None,
                 tt_cards: list[dict] | None = None) -> dict:
    """The glossary for one language: official ink/rarity/type words, plus the
    two things only the card data can tell us -

      * classifications: each localized card lists its subtypes in the SAME
        order the English card does (Storyborn, Hero, Toy = ストーリーボーン,
        ヒーロー, トイ), so position-aligned pairs are counted and the most
        common translation of each English word wins. A word seen fewer than
        twice is left out rather than guessed.
      * set names: from the gallery's own per-locale set list (de/fr/it), or
        the Japanese half of Takara's set title (ja).
    """
    votes: dict[str, dict[str, int]] = {}
    for r in rows:
        if r.get("match_how") == "name":
            continue
        ours = (cat.by_id.get(r["card_id"]) or {}).get("classifications") or []
        loc = r.get("classifications") or []
        loc = [x for x in loc if x and x not in ("Song", "Lied", "Chanson", "Canzone", "ソング")]
        ours = [x for x in ours if x]
        if not ours or len(ours) != len(loc):
            continue
        for e, l in zip(ours, loc):
            votes.setdefault(e, {}).setdefault(l, 0)
            votes[e][l] += 1
    classes = {}
    for e, d in votes.items():
        best, n = max(d.items(), key=lambda kv: kv[1])
        if n >= 2 and best != e:
            classes[e] = best
    set_names: dict[str, str] = {}
    name_by_code = {(s.get("code") or ""): s["name"] for s in sets}
    if gallery_set_names:
        for gid, v in gallery_set_names.items():
            code = _GALLERY_SET.get(gid)
            en = name_by_code.get(code) if code else None
            nm = (v or {}).get("name") if isinstance(v, dict) else v
            if en and nm and nm != en:
                set_names[en] = nm
    if tt_cards:
        for j in tt_cards:
            p = parse_tt_file(j.get("card_file", ""))
            if not p or not p["code"].isdigit():
                continue
            for st in (j.get("sets_array") or [j.get("sets")]):
                t = tt_set_title(st)
                en = name_by_code.get(p["code"])
                # A starter deck or promo pack is a different product; only the
                # title of the card's own booster set names the set.
                if t and en and "スタートデッキ" not in st and "プロモーション" not in st and "キュレーター" not in st:
                    set_names.setdefault(en, t)
    out = {k: dict(OFFICIAL_TERMS[k].get(lang, {})) for k in ("ink", "rarity", "type")}
    out["class"] = dict(sorted(classes.items()))
    out["set"] = dict(sorted(set_names.items()))
    return out
