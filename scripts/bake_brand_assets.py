"""
bake_brand_assets.py — Ravensburger's official Lorcana brand bundle, reduced to
web assets the site can ship.

The bundle is ~890 files and 313 MB of print-resolution art (3600px ink icons,
4938px set logos, .eps/.dxf/.ai cutting files). None of that belongs in a git
repo that a phone has to download. This script is the bridge: an EXPLICIT
manifest of the handful of files we actually use, downscaled and recoloured into
`Logos/lorcana/`.

Explicit, not a directory sweep, for the same reason `build_dist.mjs` is an
include-list: Ravensburger renames things between drops ("Set6_Colour" one set,
"AzuriteSea-Color" the next), and a sweep would silently ship whatever it found
under whatever name it found it under. A manifest FAILS when a source moves, and
the failure names the file — which is exactly the report you want the day a new
bundle lands.

    python scripts/bake_brand_assets.py --bundle "<path to Complete Bundle>"
    python scripts/bake_brand_assets.py --bundle ... --contact     # LOOK AT IT
    python scripts/bake_brand_assets.py --bundle ... --check       # no writes

Three output kinds, and which one a piece of art gets is a real decision:

  SVG   for single-colour glyphs — the lore pip, inkable/uninkable, the promo
        stamps. These are 1-10 KB, and rewriting their one fill to
        `currentColor` makes them theme with the page for free. A PNG of a white
        glyph is invisible on Parchment; a PNG per theme is four files nobody
        remembers to regenerate.

  WebP  for the big airbrushed art — set logos and the card back. Their SVGs are
        300 KB - 1.8 MB each (Illustrator exports every gradient mesh as
        thousands of paths) and PNG is barely better: Whispers in the Well is
        233 KB as a 440px PNG and 73 KB as WebP. Measured across the 12 logos,
        WebP is the difference between 1.3 MB and 350 KB of repo and wire.

  PNG   for small multi-colour icons — the ink badges and the Challenge badge.
        Already 8-16 KB, so WebP would save single-digit KB, and PNG is what
        every other icon on the site already is.

⚠ These are NOT palette-quantized, unlike the collectible photos that
cut_collectible_bg.py writes. FASTOCTREE is the right call for a photograph of
one pin; on an airbrushed wordmark 256 colours bands the gradient visibly.

⚠ Set logos are WORDMARKS. They read at 100px and are a smudge at 13px, so they
are baked at 440px for headers and modals and must never be used as a list-row
icon. The one exception to the WebP rule is The First Chapter, which has no
colour logo in the bundle at all (black line art only, every variant) — see
SET_LOGO_SVGS for why it is copied verbatim rather than recoloured.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

from PIL import Image

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_ROOT = os.path.join(REPO, "Logos", "lorcana")

# Long-side px for each family. Rendered sizes are roughly a third of these, so
# the extra is retina headroom, not vanity: the ink shields draw at 14-30px and
# the set logos at 40-160px.
W_SET = 440
W_INK = 96
W_MARK = 128

# WebP quality for the airbrushed art. 88 rather than the usual 80 because these
# are logos on transparency, where the lossy ringing 80 leaves shows up as a
# halo along the die-cut edge rather than as texture noise inside a photo.
WEBP_Q = 88


# ── The manifest ────────────────────────────────────────────────────────────
# (source path inside the bundle, output path under Logos/lorcana, width)
#
# Set logos: one entry per mainline set, keyed by the SLUG of its
# SET_RELEASE_DATES name — `lorcanaSetArt()` in Index.html derives the filename
# from the set name, so a mismatch here shows up as a missing logo, never as the
# wrong one.
SET_LOGOS = [
    # The First Chapter is deliberately absent — see SET_LOGO_SVGS below.
    ("Set Logos/2. Rise Of The Floodborn/Floodborn_Color.png", "rise-of-the-floodborn"),
    ("Set Logos/3. Into The Inklands/Inklands-Color.png",      "into-the-inklands"),
    ("Set Logos/UrsulasReturn_Color.png",                      "ursulas-return"),
    ("Set Logos/5. Shimmering Skies/Shimmering-Color.png",     "shimmering-skies"),
    ("Set Logos/6. Azurite Sea/AzuriteSea-Color.png",          "azurite-sea"),
    ("Set Logos/7. Archazia_s Island/Archazia-Color.png",      "archazias-island"),
    ("Set Logos/8. Reign Of Jafar/Jafar-Color.png",            "reign-of-jafar"),
    ("Set Logos/9. Fabled/Fabled-Colour-01.png",               "fabled"),
    ("Set Logos/10. Whispers In The Well/Whispers-Color.png",  "whispers-in-the-well"),
    ("Set Logos/11. Winterspell/Winterspell_Full-Colour.png",  "winterspell"),
    ("Set Logos/12. Wilds Unknown/Wilds-Color.png",            "wilds-unknown"),
    ("Set Logos/13. Attack of the Vine/Full-Colour.png",       "attack-of-the-vine"),
]

# ⚠ The only set with no colour logo anywhere in the bundle — black line art in
# every variant. It ships as SVG so it can be recoloured for the dark themes.
#
# Copied VERBATIM, not through bake_svg_mono, and that is deliberate. This one is
# displayed in an <img>, and `currentColor` inside an <img>-loaded SVG does NOT
# inherit from the host page — it resolves against the SVG document's own
# `color`, whose initial value is UA-dependent and flips with the browser's dark
# preference. A currentColor set logo would therefore be black for some readers
# and white for others on the SAME theme. The file declares no fill at all, so
# verbatim means SVG's own initial `fill: black` — deterministic — and
# `.set-logo--mono` inverts it on the dark themes.
# (source svg, slug, sibling PNG of the SAME artwork used to tighten the viewBox)
SET_LOGO_SVGS = [
    ("Set Logos/1. The First Chapter/FirstChapter.svg", "the-first-chapter",
     "Set Logos/1. The First Chapter/FirstChapter.png"),
]

# ⚠ DUAL pairs only. The six single-ink shields already ship from this same
# bundle (Logos/inks/*.png, added long before this script) and are preloaded in
# the document head; re-baking them would change their box from 96x96 to 96x110
# and reflow every ink shield on the site to no end. The pairs are the actual
# gap — a dual-ink card renders two shields side by side today, or a flat slate
# pie slice, because nothing here knew an official pair icon existed.
INKS = ["Amber", "Amethyst", "Emerald", "Ruby", "Sapphire", "Steel"]

# Promo stamps, as actually printed on the cards. Slugs are the site's own promo
# SET names (see PROMO_STAMPS in Index.html), not the bundle's filenames, because
# the bundle files them by YEAR ("1stPromo", "Promo2023") and we file them by set.
#
# ⚠ Only stamps that map to a set the site tracks. The bundle also carries
# GenCon, Disney100, League, Cruise, Film, Publishing and Magical Places marks,
# and none of them is a set in SET_ORDER — baking them would ship five icons
# nothing can ever render. Add one the day its set exists, not before.
#
# The _White variants are the ones to take: they are single-fill, so bake_svg_mono
# turns them into currentColor and one file serves all seven themes. The gold and
# colour variants are locked to their own palette.
PROMO_STAMPS = [
    ("Promo Icons/1stPromo_White.svg",                   "promo-set-1"),
    ("Promo Icons/2ndPromo_White.svg",                   "promo-set-2"),
    ("Promo Icons/3rdPromo_White.svg",                   "promo-set-3"),
    ("Promo Icons/ChallengePromoFullVersion_White.svg",  "challenge"),   # LCP C1 + C2
    ("Promo Icons/D23Expo_White.svg",                    "d23"),         # D23 Collection
]

# Card-face glyphs. All single-colour, all recoloured to currentColor, so a
# strength icon is as legible on Parchment as on Black.
CARD_GLYPHS = [
    ("Card Parts/Lore.svg",                    "lore"),
    ("Card Parts/LoreBuff.svg",                "lore-buff"),
    ("Card Parts/Inkable_Icon.svg",            "inkable"),
    ("Card Parts/Uninkable_Icon.svg",          "uninkable"),
    ("Card Parts/Strength_BlackWhite.svg",     "strength"),
    ("Card Parts/WillPower_BlackWhite.svg",    "willpower"),
    ("Card Parts/LocationMove_BlackWhite.svg", "move-cost"),
    ("Card Parts/Exert.svg",                   "exert"),
]

# Full-colour marks that need to stay full-colour. (src, slug, width, ext)
#
# `challenge-badge` is the Disney Lorcana Challenge and `lorcana-hex` the
# Challenge Championship Qualifier — a SHIELD against a HEXAGON, which is the
# point. The obvious pairing (the filled badge against the bundle's outline
# version of the same badge) was baked first and thrown away twice over: two
# shields differing only by a gold frame is unreadable at 13px, which is the
# exact complaint this work exists to fix, AND the outline version is white on
# transparency, so it is invisible on all four light themes. The contact sheet
# is what caught the second one.
MARKS = [
    ("Challenge Logo/Badge_Complete_Colour.png", "challenge-badge", W_MARK, "png"),
    ("Lorcana Logo/Logo_Hex.png",                "lorcana-hex",     W_MARK, "png"),
    ("Card Back/CardBack.png",                   "card-back",       400,    "webp"),
]


# ── Image helpers ───────────────────────────────────────────────────────────
def trim_alpha(im: Image.Image) -> Image.Image:
    """Crop away fully-transparent margin.

    Every set logo in the bundle is delivered on a square canvas — The First
    Chapter is a wide wordmark on a 4167x4167 field — so without this a logo
    baked to 440px wide would render as a ~140px wordmark floating in 300px of
    nothing, and no amount of CSS could tell the difference between that and a
    small logo.
    """
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    box = im.getchannel("A").getbbox()
    return im.crop(box) if box else im


def bake_raster(src: str, dst: str, width: int, square: bool = False) -> tuple[int, int, int]:
    """Trim, fit to `width`, write as PNG or WebP (chosen by the dst extension).

    `square` letterboxes the result into a width x width box. The six ink
    shields already on the site are square canvases with a taller-than-wide hex
    inscribed, so a dual pair baked to its natural 96x110 would sit a head above
    every single shield beside it in the same row.
    """
    im = trim_alpha(Image.open(src))
    if im.width > width or im.height > width:
        im.thumbnail((width, width), Image.LANCZOS)
    if square:
        box = Image.new("RGBA", (width, width), (0, 0, 0, 0))
        box.paste(im, ((width - im.width) // 2, (width - im.height) // 2), im)
        im = box
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if dst.lower().endswith(".webp"):
        im.save(dst, "WEBP", quality=WEBP_Q, alpha_quality=100, method=6)
    else:
        im.save(dst, "PNG", optimize=True)
    return im.width, im.height, os.path.getsize(dst)


# ── SVG helpers ─────────────────────────────────────────────────────────────
_XML_DECL = re.compile(r"<\?xml[^>]*\?>\s*", re.I)
_COMMENT = re.compile(r"<!--.*?-->\s*", re.S)
_FILL_DECL = re.compile(r"(fill\s*:\s*)(#[0-9a-fA-F]{3,8}|white|black)", re.I)
_FILL_ATTR = re.compile(r'(fill\s*=\s*")(#[0-9a-fA-F]{3,8}|white|black)(")', re.I)
_WS = re.compile(r">\s+<")


def _read_svg(src: str) -> str:
    with open(src, "r", encoding="utf-8") as fh:
        s = fh.read()
    return _WS.sub("><", _COMMENT.sub("", _XML_DECL.sub("", s))).strip()


def _write(dst: str, s: str) -> int:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(s + "\n")
    return os.path.getsize(dst)


_VIEWBOX = re.compile(r'viewBox\s*=\s*"\s*([\d.+-]+)[ ,]+([\d.+-]+)[ ,]+([\d.+-]+)[ ,]+([\d.+-]+)\s*"')


def bake_svg_copy(src: str, dst: str, tighten_with: str | None = None) -> int:
    """Verbatim, minus the XML declaration and Illustrator's comment banner.

    For art displayed in an <img>, where currentColor is not usable — see the
    SET_LOGO_SVGS note.

    ⚠ `tighten_with` shrinks the viewBox to the art's real bounds, using the
    sibling PNG of the same artwork as the measuring stick. Ravensburger exports
    every set logo on a SQUARE canvas, so The First Chapter — a wide wordmark —
    occupies a 927x263 band inside a 1000x1000 box. Rendered into a 26px-tall
    slot next to twelve trimmed WebP logos it came out a third their size and
    read as broken. trim_alpha already does this for the rasters; an SVG has no
    alpha channel to trim, so the number has to come from somewhere, and the
    bundle ships the same art as a 4167px PNG. Verified against the browser's
    own getBBox(): 36.2/366.2/927.5/263.3 computed here vs 36.3/366.4/927.4/263.
    """
    s = _read_svg(src)
    if tighten_with and os.path.exists(tighten_with):
        m = _VIEWBOX.search(s)
        px = Image.open(tighten_with).convert("RGBA").getchannel("A").getbbox()
        if m and px:
            vx, vy, vw, vh = (float(g) for g in m.groups())
            iw, ih = Image.open(tighten_with).size
            box = (vx + px[0] * vw / iw, vy + px[1] * vh / ih,
                   (px[2] - px[0]) * vw / iw, (px[3] - px[1]) * vh / ih)
            s = s[:m.start()] + 'viewBox="%.2f %.2f %.2f %.2f"' % box + s[m.end():]
    return _write(dst, s)


def bake_svg_mono(src: str, dst: str) -> int:
    """Rewrite a single-colour Illustrator export to inherit `currentColor`.

    These exports declare their colour in one of two places — a `<style>` block
    (`.cls-1 { fill: #fff }`) or a `fill=` attribute — and some declare it
    nowhere at all, defaulting to SVG's own black. All three have to be handled
    or a glyph ships locked to one colour and is invisible on half the themes.

    These are rendered through a CSS `mask-image`, where only the alpha channel
    matters, so the colour is belt-and-braces rather than the mechanism — but it
    means the file is also correct if anyone ever inlines it.

    ⚠ `fill: none` is LEFT ALONE. It is how an Illustrator export marks a
    counter — the hole in the middle of the inkable hex — and rewriting it to
    currentColor fills that hole in solid.
    """
    s = _read_svg(src)
    s = _FILL_DECL.sub(r"\1currentColor", s)
    s = _FILL_ATTR.sub(r"\1currentColor\3", s)
    # The no-fill-declared case: put currentColor on the root so every path
    # inherits it. Harmless where a fill IS declared — the specific one wins.
    s = re.sub(r"<svg\b", '<svg fill="currentColor"', s, count=1)
    return _write(dst, s)


def ink_pairs() -> list[tuple[str, str]]:
    """The 15 unordered ink pairs, in the bundle's own A-Z filename order."""
    out = []
    for i, a in enumerate(INKS):
        for b in INKS[i + 1:]:
            out.append((a, b))
    return out


def plan(bundle: str) -> list[tuple[str, str, str, int, bool]]:
    """(kind, abs src, abs dst, width, square) for everything we bake."""
    jobs: list[tuple[str, str, str, int, bool]] = []

    def raster(rel, out, w, square=False):
        jobs.append(("raster", os.path.join(bundle, rel.replace("/", os.sep)),
                     os.path.join(OUT_ROOT, out.replace("/", os.sep)), w, square))

    def svg(rel, out, mono=True, tighten=None):
        jobs.append(("svg" if mono else "svgcopy", os.path.join(bundle, rel.replace("/", os.sep)),
                     os.path.join(OUT_ROOT, out.replace("/", os.sep)), 0,
                     os.path.join(bundle, tighten.replace("/", os.sep)) if tighten else False))

    for rel, slug in SET_LOGOS:
        raster(rel, f"sets/{slug}.webp", W_SET)
    for rel, slug, sibling in SET_LOGO_SVGS:
        svg(rel, f"sets/{slug}.svg", mono=False, tighten=sibling)

    for a, b in ink_pairs():
        raster(f"Ink Icons/{a}-{b}-Badge.png", f"inks/{a.lower()}-{b.lower()}.png", W_INK, square=True)

    for rel, slug in PROMO_STAMPS:
        if rel.lower().endswith(".svg"):
            svg(rel, f"promo/{slug}.svg")
        else:
            raster(rel, f"promo/{slug}.png", W_INK)

    for rel, slug in CARD_GLYPHS:
        svg(rel, f"card/{slug}.svg")

    for rel, slug, w, ext in MARKS:
        raster(rel, f"marks/{slug}.{ext}", w)

    return jobs


def contact_sheet(jobs, path: str) -> None:
    """One sheet of every baked asset over a split light/dark ground.

    The same reason cut_collectible_bg.py has one: these fail per-file and
    quietly. A logo whose alpha channel is empty trims to nothing and bakes to a
    1px file; a "white" glyph that was actually black comes out invisible on
    dark. Both look like a perfectly ordinary success in the log.
    """
    from PIL import ImageDraw, ImageFont
    pngs = [j for j in jobs if j[0] == "raster" and os.path.exists(j[2])]
    cell, pad, cols = 120, 14, 10
    rows = (len(pngs) + cols - 1) // cols
    W = cols * (cell + pad) + pad
    H = rows * (cell + pad + 14) + pad
    sheet = Image.new("RGB", (W, H * 2), (248, 246, 240))
    sheet.paste(Image.new("RGB", (W, H), (24, 20, 34)), (0, H))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 10)
    except Exception:
        font = ImageFont.load_default()
    for i, (_, _, dst, _, _) in enumerate(pngs):
        r, c = divmod(i, cols)
        x = pad + c * (cell + pad)
        y = pad + r * (cell + pad + 14)
        im = Image.open(dst).convert("RGBA")
        im.thumbnail((cell, cell), Image.LANCZOS)
        label = os.path.relpath(dst, OUT_ROOT).replace(os.sep, "/")
        for band, ink in ((0, (40, 36, 50)), (H, (226, 222, 235))):
            sheet.paste(im, (x + (cell - im.width) // 2, band + y + (cell - im.height) // 2), im)
            d.text((x, band + y + cell + 1), label[:22], fill=ink, font=font)
    sheet.save(path)
    print(f"contact sheet -> {path}  ({sheet.width}x{sheet.height})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle", required=True, help="path to the unzipped 'Complete Bundle' folder")
    ap.add_argument("--contact", nargs="?", const="brand-contact.png", default=None,
                    help="also write a light/dark contact sheet of every baked PNG")
    ap.add_argument("--check", action="store_true", help="verify every source exists; write nothing")
    args = ap.parse_args()

    bundle = os.path.abspath(args.bundle)
    if not os.path.isdir(bundle):
        print(f"error: no such bundle directory: {bundle}", file=sys.stderr)
        return 2

    jobs = plan(bundle)
    missing = [src for _, src, _, _, _ in jobs if not os.path.exists(src)]
    if missing:
        # A new bundle that renamed a file lands here, and this list IS the diff.
        print(f"error: {len(missing)} source file(s) missing from the bundle:", file=sys.stderr)
        for m in missing:
            print("  " + os.path.relpath(m, bundle), file=sys.stderr)
        print("\nThe bundle renames files between drops. Fix the manifest at the "
              "top of this script, then re-run.", file=sys.stderr)
        return 1

    if args.check:
        print(f"ok: all {len(jobs)} source files present in {bundle}")
        return 0

    total = 0
    for kind, src, dst, w, square in jobs:
        if kind == "raster":
            iw, ih, size = bake_raster(src, dst, w, square)
            note = f"{iw}x{ih}"
        elif kind == "svgcopy":
            size = bake_svg_copy(src, dst, square or None)
            note = "svg"
        else:
            size = bake_svg_mono(src, dst)
            note = "svg"
        total += size
        print(f"  {os.path.relpath(dst, REPO).replace(os.sep, '/'):48s} {note:>10s}  {size/1024:6.1f} KB")
    print(f"\n{len(jobs)} files, {total/1024:.0f} KB total -> "
          f"{os.path.relpath(OUT_ROOT, REPO).replace(os.sep, '/')}/")

    if args.contact:
        contact_sheet(jobs, os.path.abspath(args.contact))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
