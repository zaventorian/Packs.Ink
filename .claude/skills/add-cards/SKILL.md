---
name: add-cards
description: Add newly revealed Lorcana cards to packs.ink from photos/screenshots Zaven sends (any language — translate to English). Use when he sends card images and says "add these", "more <set> cards", "new cards", or similar — including from a cloud session on his phone.
---

# Photos of revealed cards → cards on packs.ink

Zaven sends pictures of newly revealed cards (reveal streams, social posts, foreign-language
spoilers). You read each card, translate it to English, crop the card out of the picture, and
prestage it into the `cards` table. **No code change, no commit, no deploy** — a row in `cards`
shows on the site on its own (the catalog renders price-less cards).

**When he sends photos, run Stages 0→5 end to end without asking**, then report the table from
Stage 5. Only stop if Stage 0 fails.

Source precedence (never break it): **Lorcast > the official gallery > these photos.** A photo
is a placeholder; `import_pasted_cards.py` already refuses a card Lorcast or the gallery has,
and the higher source later overwrites our row IN PLACE (same id `crd_prestage_<tag>_<cn>`,
same art path), so collection/deck marks survive. Don't change the tag or id scheme.

## Stage 0 — Can this session reach the database?

```bash
pip install -q requests python-dotenv pillow 2>/dev/null
cd scripts && python -c "from dotenv import load_dotenv;load_dotenv('.env');from supabase_client import Supabase;print(len(Supabase().select('sets',columns='id',filters={'name':'ilike.*'})),'sets')"
```

Credentials come from `scripts/.env` locally. In a cloud session they come from the cloud
environment: `SUPABASE_URL` as an environment variable, and the service key as an **API
credential** on the Supabase host (headers `Authorization: Bearer <key>` and `apikey: <key>`),
with `SUPABASE_SERVICE_KEY=proxy-injected` as a placeholder env var. `supabase_client` sends no
auth of its own when it sees that placeholder, and the agent proxy adds the real key — the
session never sees it. If this check fails in the cloud, tell Zaven which piece is missing and
stop. (`cards.disneylorcana.com` must be in the environment's allowed domains for the gallery
guard; without it the import still runs but says it could not read the gallery.)

## Stage 1 — Find the image files

Each attached image arrives with a `[Image: source: <path>]` note. Those paths are the files the
script reads. **If there is no path** (the image exists only in the conversation), you cannot
crop it — say so, and ask Zaven to put the photos in a Google Drive folder instead, then pull
them with the Drive connector into the scratchpad.

## Stage 2 — Which set, and what's already there

The set is the number after the language code on the card's bottom-left line
(`91/204 • IT • 14` → set 14). Look up the set id by name and list what exists:

```bash
cd scripts && python -c "
from dotenv import load_dotenv;load_dotenv('.env')
from supabase_client import Supabase;sb=Supabase()
s=sb.select('sets',columns='id,name',filters={'name':'ilike.*<name>*'});print(s)
for r in sb.select('cards',columns='collector_number,name,version',filters={'set_id':'eq.'+s[0]['id']}): print(r)"
```

Known: set 14 Hyperia City = `set_hyperia_city`, tag `set14`, gallery slug `set14`. Skip any
collector number already present unless the photo shows it's a different printing.

## Stage 3 — Read each card (the part that can go wrong)

A wrong cost or stat is worse than a missing one — the site states it with total confidence. If a
field is unreadable, **leave it out** (null) rather than guess.

- **collector_number** — mandatory (retire_prestaged keys on it). No number → don't add the card.
- **Ink** — frame colour. Cross-check: a 204-card mainline set is six blocks of 34 in the order
  Amber 1–34, Amethyst 35–68, Emerald 69–102, Ruby 103–136, Sapphire 137–170, Steel 171–204.
  Numbers above 204 (Enchanted/Epic/Iconic) keep the ink of the base card. The script warns on
  disagreement — resolve every warning.
- **Inkable** — ornate swirl ring around the cost = inkable; plain hexagon = uninkable.
- **Lore** — count the ◇ pips down the right edge of the text box.
- **Rarity** — the icon at the bottom centre:
  | icon | rarity |
  |---|---|
  | grey/white circle | Common |
  | open-book / shield shape | Uncommon |
  | bronze-orange triangle | Rare |
  | silver fan-in-a-diamond | Super Rare |
  | gold fan-in-a-pentagon | Legendary |
  | multicolour gem (full-art foil) | Enchanted |
  Epic/Iconic/Promo: compare against `Logos/rarity/*.svg` (open one in the browser pane to see it).
- **card_type** — `Character`, `Action`, `Action - Song`, `Item`, `Location` (exact strings the
  catalog already uses). Items/actions have no strength/willpower/lore/classifications.
- **illustrators** — the name after the brush icon, bottom-left. Several → list.

### Translating (IT / FR / DE / JA / ZH …)

Translate faithfully into English and use **the wording the site's existing cards use**. Before
writing text, pull a few English cards from the same set (`select name,text` on the set) and
copy their phrasing. Conventions:
- Symbols: `{I}` ink, `{E}` exert, `{S}` strength, `{L}` lore, `{W}` willpower.
- Named abilities in CAPS, then the rule: `KAIJU IMPACT When you play this character, …`
- Keyword lines with their standard reminder text, e.g.
  `Shift 4 {I} (You may pay 4 {I} to play this on top of one of your characters named X.)`,
  `Evasive (Only characters with Evasive can challenge this character.)`,
  `Support (Whenever this character quests, you may add their {S} to another chosen character's {S} this turn.)`,
  `Resist +1 (Damage dealt to this character is reduced by 1.)`,
  `Bodyguard (This character may enter play exerted. An opposing character who challenges one of your characters must choose one with Bodyguard if able.)`,
  `Singer 5 (This character counts as cost 5 to sing songs.)`,
  songs: `(A character with cost N or more can {E} to sing this song for free.)`,
  ink drops: `get 1 ink drop. (Each ink drop may be removed to pay 1 {I}.)`.
- Glossary: JA 変身 Shift · 回避 Evasive · 支援 Support · 耐久 Resist · 護衛 Bodyguard ·
  突進 Rush · 歌声 Singer · 守り Ward · エグザート exerted · インクウェル inkwell · ロア lore ·
  捨て札 discard · 追放 banish. IT Classico / FR Storyborn / DE Sagengestalt / JA
  ストーリーボーン = **Storyborn**; ドリームボーン / Onirico = **Dreamborn**; Eroe/Héros/Held/
  ヒーロー Hero; Alleato/Allié/Verbündeter/仲間 Ally; ヴィランズ Villain; 探偵 Detective;
  発明家 Inventor; プリンセス Princess.
- Character names are the known English Disney names; the subtitle (version), ability names and
  flavor text are your translation. Use a song's English title when the copyright line names it.
- **Tell Zaven which names are your translations** — they're provisional until the official
  English card appears (which then overwrites ours automatically).

## Stage 4 — Manifest, dry run, look, commit

Write `<scratchpad>/cards.json` — a list of objects with `image` (file name), `crop`
`[x, y, w, h]` in the source's pixels (omit if the image is already just the card),
`collector_number`, `name`, `version`, `rarity`, `inks`, `cost`, `inkable`, `card_type`,
`classifications`, `strength`, `willpower`, `lore`, `text`, `flavor_text`, `illustrators`.
Check `PIL.Image.open(f).size` for each file before choosing crops; a card is 5:7 portrait.

```bash
cd scripts && PYTHONIOENCODING=utf-8 python import_pasted_cards.py \
  --manifest <scratchpad>/cards.json --images <dir with the images> \
  --set-id <set_id> --tag set<N> --slug set<N> --setnum <N> \
  --contact <scratchpad>/sheet.jpg
```

**Read the contact sheet image.** Every tile must show the whole card, corner to corner — a
crop that cuts off the bottom lines or the cost is the most common miss. Fix crops (open the
source image to find the real card edges) and re-run until the sheet is clean and there are no
ink warnings. Then add `--commit`. It uploads the art, upserts the rows and refreshes the price
matview. "only Npx wide" warnings are fine — small source photos are expected.

## Stage 5 — Report

Reply with a table: `# | Card | Rarity | Source language`, then a short list of anything
uncertain (translated names, a field left blank, a crop you had to guess). Send the contact
sheet with SendUserFile so he can eyeball it from his phone.
