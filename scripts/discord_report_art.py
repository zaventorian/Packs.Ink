"""
discord_report_art.py — the pictures in the weekly Discord report.

    market_chart(series, title, subtitle) -> PNG bytes | None
    card_strip(cards, key)                -> PNG bytes | None

Drawn with Pillow when the report runs (GitHub Actions) and attached to the
post. The bot's Worker can't do this: it has no way to decode card JPEGs
inside its CPU budget.

Every function returns None rather than raising. A picture is decoration on a
report whose words are the point, so a missing font, a TCGplayer art 404 or a
Pillow problem must cost the picture and never the post.

Sizing: Discord shows an embed image about 400px wide, so these are drawn
~1150px wide with type big enough to survive a ~0.35x scale. Fonts are
committed under scripts/fonts (SIL OFL) so the job never downloads them.
"""
from __future__ import annotations

import datetime as dt
import io
import os

import requests

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
BG, GOLD, TEXT, MUTED = (24, 19, 34), (227, 179, 65), (236, 232, 245), (150, 142, 172)
GREEN, RED, LINE, ZERO = (92, 196, 128), (232, 104, 104), (60, 52, 78), (78, 70, 98)
TEAL, CORAL = (86, 196, 206), (232, 118, 104)
SS = 2  # draw at 2x and downsample: Pillow has no anti-aliased lines otherwise


def art_url(pid):
    return f"https://tcgplayer-cdn.tcgplayer.com/product/{int(pid)}_in_1000x1000.jpg"


def _font(name, size):
    from PIL import ImageFont
    return ImageFont.truetype(os.path.join(FONT_DIR, name), int(round(size)))


def _fonts():
    return {
        "semi": lambda s: _font("NunitoSans-SemiBold.ttf", s),
        "bold": lambda s: _font("NunitoSans-Bold.ttf", s),
        "xbold": lambda s: _font("NunitoSans-ExtraBold.ttf", s),
        "title": lambda s: _font("Cinzel-Bold.ttf", s),
    }


def _png(im, w, h):
    from PIL import Image
    buf = io.BytesIO()
    im.resize((w, h), Image.LANCZOS).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def fmt_pct(p, digits=1):
    return ("+" if p > 0 else "−" if p < 0 else "") + f"{abs(p):.{digits}f}%"


def fmt_money(v, sign=False):
    s = ("+" if v > 0 else "−" if v < 0 else "") if sign else ""
    v = abs(v)
    return s + (f"${v:,.0f}" if v >= 1000 else f"${v:,.2f}")


# ── the market chart ─────────────────────────────────────────────────────────
def market_chart(series, title, subtitle):
    """series: [(label, [(date, pct_since_start)], color)] — already rebased."""
    try:
        return _market_chart(series, title, subtitle)
    except Exception as e:  # noqa: BLE001 — decoration never sinks the report
        print(f"  (market chart skipped: {e.__class__.__name__}: {e})")
        return None


def _market_chart(series, title, subtitle):
    from PIL import Image, ImageDraw
    series = [s for s in series if len(s[1]) >= 2]
    if len(series) < 2:
        return None
    F = _fonts()
    W, H, L, R, T, B = 1146, 600, 118, 40, 190, 70
    im = Image.new("RGB", (W * SS, H * SS), BG)
    d = ImageDraw.Draw(im)
    s = lambda v: int(round(v * SS))
    pts_all = [p for _, pts, _ in series for p in pts]
    d0, d1 = min(p[0] for p in pts_all), max(p[0] for p in pts_all)
    lo = min(min(p[1] for p in pts_all), -2) - 1
    hi = max(max(p[1] for p in pts_all), 2) + 1
    X = lambda day: L + (W - L - R) * (day - d0).days / max(1, (d1 - d0).days)
    Y = lambda v: T + (H - T - B) * (hi - v) / (hi - lo)
    d.text((s(34), s(26)), title, font=F["title"](s(34)), fill=GOLD)
    d.text((s(W - 34), s(34)), subtitle, font=F["semi"](s(26)), fill=MUTED, anchor="ra")
    step = next(k for k in (1, 2, 5, 10, 20, 25, 50, 100) if (hi - lo) / k <= 8)
    v = int(lo // step) * step
    while v <= hi:
        if v >= lo:
            y = Y(v)
            d.line([s(L), s(y), s(W - R), s(y)], fill=ZERO if v == 0 else LINE, width=s(2 if v == 0 else 1))
            d.text((s(L - 14), s(y)), fmt_pct(v, 0) if v else "0%", font=F["bold"](s(24)), fill=MUTED, anchor="rm")
        v += step
    mo = dt.date(d0.year, d0.month, 1)
    while mo <= d1:
        if mo > d0 and X(mo) < W - R - 20:
            d.text((s(X(mo)), s(H - B + 30)), f"{mo:%b}", font=F["bold"](s(24)), fill=MUTED, anchor="mm")
        mo = dt.date(mo.year + (mo.month == 12), mo.month % 12 + 1, 1)
    lx, ly = 34, 104
    for n, (label, pts, color) in enumerate(series):
        xy = [(s(X(day)), s(Y(val))) for day, val in pts]
        d.line(xy, fill=color, width=s(4), joint="curve")
        ex, ey = xy[-1]
        d.ellipse([ex - s(6), ey - s(6), ex + s(6), ey + s(6)], fill=color)
        txt = f"{label} {fmt_pct(pts[-1][1])}"
        if n == 2:
            lx, ly = 34, 146
        d.ellipse([s(lx), s(ly - 8), s(lx + 16), s(ly + 8)], fill=color)
        d.text((s(lx + 24), s(ly)), txt, font=F["bold"](s(24)), fill=TEXT, anchor="lm")
        lx += 24 + d.textlength(txt, font=F["bold"](s(24))) / SS + 34
    return _png(im, W, H)


# ── the card strip ───────────────────────────────────────────────────────────
def fetch_art(pid, session=requests, timeout=15):
    """The card's TCGplayer photo as a PIL image, or None."""
    from PIL import Image
    try:
        r = session.get(art_url(pid), timeout=timeout)
        if r.status_code != 200 or not r.content:
            return None
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception:  # noqa: BLE001
        return None


def card_strip(cards, key, session=requests):
    """cards: dicts with pid, name, version, price, pct, usd, spark [(date, v)].
    key: 'usd' puts the dollar move on the badge, 'pct' the percent."""
    try:
        return _card_strip(cards, key, session)
    except Exception as e:  # noqa: BLE001
        print(f"  (card strip skipped: {e.__class__.__name__}: {e})")
        return None


def _ellipsize(d, text, font, maxw):
    if d.textlength(text, font=font) <= maxw:
        return text
    while text and d.textlength(text + "…", font=font) > maxw:
        text = text[:-1]
    return text.rstrip() + "…"


def _rounded(img, w):
    from PIL import Image, ImageDraw
    h = round(w * img.height / img.width)
    img = img.resize((w, h), Image.LANCZOS)
    # TCGplayer photos fill the card's rounded corners with white; mask them.
    mask = Image.new("L", (w * 4, h * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w * 4 - 1, h * 4 - 1], radius=int(w * 4 * 0.05), fill=255)
    return img, mask.resize((w, h), Image.LANCZOS)


def _card_strip(cards, key, session):
    from PIL import Image, ImageDraw
    arts = []
    for c in cards[:4]:
        a = fetch_art(c["pid"], session=session)
        if a is not None:
            arts.append((c, a))
    if len(arts) < 2:
        return None
    F = _fonts()
    TW, ART, GAP, PAD, K = 250, 210, 26, 34, 1.3
    W = PAD * 2 + len(arts) * TW + (len(arts) - 1) * GAP
    art_h = round(ART * 1.395)
    H = 28 + art_h + round(150 * K) + 44
    im = Image.new("RGB", (W * SS, H * SS), BG)
    d = ImageDraw.Draw(im)
    s = lambda v: int(round(v * SS))
    k = lambda v: s(round(v * K))
    y = 28
    for i, (c, a) in enumerate(arts):
        x = PAD + i * (TW + GAP)
        ax = x + (TW - ART) // 2
        card, mask = _rounded(a, s(ART))
        im.paste(card, (s(ax), s(y)), mask)
        ah = card.height / SS
        move = c["usd"] if key == "usd" else c["pct"]
        col = GREEN if move > 0 else RED
        badge = fmt_money(c["usd"], sign=True) if key == "usd" else fmt_pct(c["pct"])
        bf = F["xbold"](k(27))
        bw = d.textlength(badge, font=bf) + s(26)
        bx, by = s(ax) + (s(ART) - bw) / 2, s(y + ah) - k(30)
        d.rounded_rectangle([bx, by, bx + bw, by + k(42)], radius=k(21), fill=col)
        d.text((bx + bw / 2, by + k(21)), badge, font=bf, fill=BG, anchor="mm")
        ty = s(y + ah + 22)
        d.text((s(x + TW / 2), ty), _ellipsize(d, c["name"], F["xbold"](k(21)), s(TW)),
               font=F["xbold"](k(21)), fill=TEXT, anchor="ma")
        sub = c.get("version") or c.get("set") or ""
        d.text((s(x + TW / 2), ty + k(28)), _ellipsize(d, sub, F["semi"](k(18)), s(TW)),
               font=F["semi"](k(18)), fill=MUTED, anchor="ma")
        d.text((s(x + 8), ty + k(60)), fmt_money(c["price"]), font=F["xbold"](k(24)), fill=TEXT)
        _spark(d, c.get("spark") or [], (s(x + TW - 70), ty + k(62), s(x + TW - 4), ty + k(88)), col)
    d.text((s(PAD), s(H - 34)), "NM Market · 30-day trend line on each card", font=F["semi"](s(17)), fill=MUTED)
    d.text((s(W - PAD), s(H - 34)), "packs.ink", font=F["xbold"](s(19)), fill=GOLD, anchor="ra")
    return _png(im, W, H)


def _spark(d, pts, box, color):
    x0, y0, x1, y1 = box
    if len(pts) < 3:
        return
    last = pts[-1][0]
    vs = [v for day, v in pts if day > last - dt.timedelta(days=30)]
    if len(vs) < 3:
        return
    lo, hi = min(vs), max(vs)
    rng = (hi - lo) or 1
    xy = [(x0 + (x1 - x0) * i / (len(vs) - 1), y1 - (y1 - y0) * (v - lo) / rng) for i, v in enumerate(vs)]
    d.line(xy, fill=color, width=SS * 3 // 2 + 1, joint="curve")
    d.ellipse([xy[-1][0] - 4, xy[-1][1] - 4, xy[-1][0] + 4, xy[-1][1] + 4], fill=color)
