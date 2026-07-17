"""Bake og-image.png (1200x630) for social share cards.

Layout: the booster-pack logo centered on the site's dark PWA background
(#0f0d20) with a soft gold glow behind it and a one-line tagline underneath.
Idempotent — re-run after a logo change, then bump the ?v= on the og:image /
twitter:image URLs in Index.html so scrapers re-fetch.
"""
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGO = os.path.join(ROOT, "Logos", "packs-ink-logo.png")
OUT = os.path.join(ROOT, "og-image.png")

W, H = 1200, 630
BG = (15, 13, 32)          # #0f0d20 — matches theme-color / PWA icons
GLOW = (240, 199, 94)      # warm gold, matches the logo burst
TAGLINE = "Price tracking · Daily movement · Collection · Search · Deckbuilding"
TAG_COLOR = (232, 200, 119)

img = Image.new("RGB", (W, H), BG)

# Soft radial glow behind the pack art. Drawn small, blurred hard, scaled up —
# cheap smooth gradient without numpy.
glow = Image.new("L", (300, 300), 0)
gd = ImageDraw.Draw(glow)
for r, a in ((130, 26), (100, 48), (70, 76), (45, 110)):
    gd.ellipse((150 - r, 150 - r, 150 + r, 150 + r), fill=a)
glow = glow.filter(ImageFilter.GaussianBlur(28)).resize((900, 900))
img.paste(Image.new("RGB", glow.size, GLOW), (600 - 450, 285 - 450), glow)

logo = Image.open(LOGO).convert("RGBA")
lh = 470
lw = round(logo.width * lh / logo.height)
logo = logo.resize((lw, lh), Image.LANCZOS)
img.paste(logo, (600 - lw // 2, 285 - lh // 2), logo)

def load_font(size):
    for name in ("seguisb.ttf", "segoeuib.ttf", "segoeui.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name), size)
        except OSError:
            continue
    return ImageFont.load_default()

d = ImageDraw.Draw(img)
# Auto-shrink the tagline so it never overruns the image width (the segment
# list can grow); start at 32 and step down until it fits with a side margin.
size = 32
while size > 20:
    font = load_font(size)
    tw = d.textlength(TAGLINE, font=font)
    if tw <= W - 80:
        break
    size -= 1
d.text(((W - tw) / 2, 556), TAGLINE, font=font, fill=TAG_COLOR)

img.save(OUT, "PNG", optimize=True)
print(f"wrote {OUT} ({os.path.getsize(OUT) // 1024} KB)")
