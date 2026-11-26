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
LOGO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Logos", "packs-ink-logo-sm.png")
# The house style of the site's promo graphics (promo/graphics_src, the DLC
# London and Cyber Weekend posts): deep purple, a gold kicker, Cinzel titles.
BG, GOLD, TEXT, MUTED = (22, 12, 34), (200, 168, 70), (236, 230, 246), (169, 159, 196)
TITLE, PANEL, PANEL_EDGE = (246, 240, 224), (34, 24, 48), (52, 40, 70)
GREEN, RED, LINE, ZERO = (95, 191, 127), (217, 107, 107), (52, 42, 68), (78, 66, 98)
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
    d.text((s(PAD), s(H - 34)), "TCGplayer Low · 30-day trend line on each card", font=F["semi"](s(17)), fill=MUTED)
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


# ── house-style pieces ───────────────────────────────────────────────────────
# The bundled fonts carry no ▲ ▼ →, so those are drawn as shapes.
PAD = 56
RULE = (84, 66, 47)            # the gold rule, at about a third of its strength
LINE_LIGHT = (196, 186, 220)   # a price line before its move


def _mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _spaced(d, xy, text, font, fill, spacing):
    """Letter-spaced text (Pillow has none): the gold kicker, the stat labels."""
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + spacing
    return x


def _triangle(d, cx, cy, r, up, fill):
    if up:
        d.polygon([(cx - r, cy + r * 0.7), (cx + r, cy + r * 0.7), (cx, cy - r)], fill=fill)
    else:
        d.polygon([(cx - r, cy - r * 0.7), (cx + r, cy - r * 0.7), (cx, cy + r)], fill=fill)


def _arrow(d, x, cy, length, fill, width):
    d.line([x, cy, x + length - width * 2, cy], fill=fill, width=width)
    d.polygon([(x + length, cy), (x + length - width * 3.2, cy - width * 2.2),
               (x + length - width * 3.2, cy + width * 2.2)], fill=fill)


def _header(im, d, s, F, W, kicker, parts):
    """The gold kicker, a Cinzel title in [(text, color)] parts, the logo and
    name on the right, the rule under it. Returns the y below the rule."""
    from PIL import Image
    _spaced(d, (s(PAD), s(44)), kicker.upper(), F["xbold"](s(15)), GOLD, s(4.5))
    x, tf = s(PAD), F["title"](s(50))
    for text, col in parts:
        d.text((x, s(72)), text, font=tf, fill=col)
        x += d.textlength(text, font=tf)
    bf = F["title"](s(24))
    d.text((s(W - PAD), s(86)), "PACKS.INK", font=bf, fill=TITLE, anchor="rm")
    try:
        logo = Image.open(LOGO).convert("RGBA")
        lh = s(58)
        lw = round(logo.width * lh / logo.height)
        logo = logo.resize((lw, lh), Image.LANCZOS)
        im.paste(logo, (int(s(W - PAD) - d.textlength("PACKS.INK", font=bf) - s(14) - lw), s(57)), logo)
    except Exception:  # noqa: BLE001 — no logo is still a picture
        pass
    d.line([s(PAD), s(146), s(W - PAD), s(146)], fill=RULE, width=s(1))
    return 146


def _stats(d, s, F, W, y, stats):
    """A row of big numbers: [(big, label, color, sub or None)], columns
    split by thin lines, as on the promo graphics. Returns the y below."""
    colw = (W - 2 * PAD) / len(stats)
    tall = any(st[3] for st in stats)
    for i, (big, label, col, sub) in enumerate(stats):
        x = PAD + i * colw + (30 if i else 0)
        if i:
            d.line([s(PAD + i * colw), s(y + 4), s(PAD + i * colw), s(y + (104 if tall else 80))], fill=LINE, width=s(1))
        d.text((s(x), s(y)), big, font=F["xbold"](s(44)), fill=col)
        _spaced(d, (s(x), s(y + 58)), label.upper(), F["xbold"](s(13)), MUTED, s(2))
        if sub:
            d.text((s(x), s(y + 82)), sub, font=F["semi"](s(17)), fill=MUTED)
    return y + (112 if tall else 88)


def _signed(p):
    return GREEN if p >= 0.3 else RED if p <= -0.3 else TITLE


# ── the daily board ──────────────────────────────────────────────────────────
DAILY_ROWS = 6


def daily_board(cards, date_label, pulse=None, session=requests):
    """The daily's picture: one panel per confirmed move — the card, its
    percent, was -> now, and its Low over three weeks with the two windows
    those numbers were measured on shaded. cards: dicts from
    discord_reports.board_card. None when there is nothing to draw."""
    try:
        return _daily_board(cards, date_label, pulse, session)
    except Exception as e:  # noqa: BLE001
        print(f"  (daily board skipped: {e.__class__.__name__}: {e})")
        return None


def _daily_board(cards, date_label, pulse, session):
    from PIL import Image, ImageDraw
    cards = [c for c in cards if c.get("pid")][:DAILY_ROWS]
    if not cards:
        return None
    F = _fonts()
    W, ROW, GAP = 1200, 236, 18
    stats = []
    if pulse:
        for label, key in (("Whole market today", "all"), ("Chase cards", "chase"), ("Sealed", "sealed")):
            p = (pulse.get(key) or (None,))[0]
            if p is not None:
                stats.append((fmt_pct(p), label, _signed(p), None))
    top = 146 + 34
    y0 = top + (118 if stats else 0)
    H = y0 + len(cards) * (ROW + GAP) - GAP + 92
    im = Image.new("RGB", (W * SS, H * SS), BG)
    d = ImageDraw.Draw(im)
    s = lambda v: int(round(v * SS))
    n = len(cards)
    _header(im, d, s, F, W, f"Lorcana daily movers · {date_label}",
            [(f"{n} ", GOLD), (f"price move{'' if n == 1 else 's'} that held", TITLE)])
    if stats:
        _stats(d, s, F, W, top, stats)
    y = y0
    for c in cards:
        _board_row(im, d, s, F, c, PAD, y, W - 2 * PAD, ROW, session)
        y += ROW + GAP
    d.text((s(PAD), s(H - 58)), "TCGplayer Low. A move counts once the new price holds on two of the last three days",
           font=F["semi"](s(17)), fill=MUTED)
    d.text((s(PAD), s(H - 34)), "and TCGplayer's Market moves the same way. Shaded: the days each price is measured on.",
           font=F["semi"](s(17)), fill=MUTED)
    return _png(im, W, H)


def _board_row(im, d, s, F, c, x, y, w, h, session):
    up = c["pct"] > 0
    col = GREEN if up else RED
    d.rounded_rectangle([s(x), s(y), s(x + w), s(y + h)], radius=s(18), fill=PANEL, outline=PANEL_EDGE, width=s(1))
    AW = 140
    a = fetch_art(c["pid"], session=session)
    if a is not None:
        card, mask = _rounded(a, s(AW))
        im.paste(card, (s(x + 22), int(s(y) + (s(h) - card.height) / 2)), mask)
    tx = x + 22 + AW + 28
    CW = 380
    cx0 = x + w - 26 - CW
    tw = cx0 - 30 - tx
    nf, vf, kf = F["xbold"](s(30)), F["semi"](s(22)), F["xbold"](s(12))
    d.text((s(tx), s(y + 26)), _ellipsize(d, c["name"], nf, s(tw)), font=nf, fill=TITLE)
    if c.get("version"):
        d.text((s(tx), s(y + 66)), _ellipsize(d, c["version"], vf, s(tw)), font=vf, fill=TEXT)
    sub = (c.get("sub") or "").upper()
    while sub and _spaced_len(d, sub, kf, s(1.6)) > s(tw):
        sub = sub[:-2].rstrip() + "…"
    if sub:
        _spaced(d, (s(tx), s(y + 102)), sub, kf, MUTED, s(1.6))
    # the percent pill, then was -> now
    pf = F["xbold"](s(30))
    pct = fmt_pct(c["pct"])
    px, py, ph = s(tx), s(y + 146), s(54)
    pw = d.textlength(pct, font=pf) + s(70)
    d.rounded_rectangle([px, py, px + pw, py + ph], radius=ph / 2, fill=col)
    _triangle(d, px + s(27), py + ph / 2, s(10), up, BG)
    d.text((px + s(44), py + ph / 2), pct, font=pf, fill=BG, anchor="lm")
    lf, mf = F["semi"](s(22)), F["xbold"](s(28))
    qx, cy = px + pw + s(20), py + ph / 2
    was = fmt_money(c["was"])
    d.text((qx, cy), was, font=lf, fill=MUTED, anchor="lm")
    qx += d.textlength(was, font=lf) + s(10)
    _arrow(d, qx, cy + s(1), s(26), MUTED, s(2.5))
    qx += s(36)
    d.text((qx, cy), fmt_money(c["price"]), font=mf, fill=TITLE, anchor="lm")
    _level_chart(d, s, F, c, (cx0, y + 22, cx0 + CW, y + h - 22), col)


def _spaced_len(d, text, font, spacing):
    return sum(d.textlength(ch, font=font) for ch in text) + spacing * max(0, len(text) - 1)


def _level_chart(d, s, F, c, box, col):
    """The card's Low, with the 'was' and 'now' windows shaded and each
    window's level drawn across it."""
    x0, y0, x1, y1 = box
    pts = c.get("series") or []
    if c.get("ebay") or len(pts) < 4:
        msg = "eBay: average of the last 5 sales" if c.get("ebay") else ""
        if msg:
            d.text((s((x0 + x1) / 2), s((y0 + y1) / 2)), msg, font=F["semi"](s(18)), fill=MUTED, anchor="mm")
        return
    cy1 = y1 - 26
    vals = [v for _, v in pts] + [c["was"], c["price"]]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.18 or hi * 0.05
    lo, hi = lo - pad, hi + pad
    step = (x1 - x0) / (len(pts) - 1)
    X = lambda i: x0 + step * i
    Y = lambda v: y0 + (cy1 - y0) * (hi - v) / (hi - lo)
    dates = [p[0] for p in pts]

    def span(first, last):
        idx = [i for i, dd in enumerate(dates) if (first is None or dd >= first) and (last is None or dd < last)]
        return (idx[0], idx[-1]) if idx else None

    was_i = span(c.get("was_from"), c.get("now_from")) if c.get("was_from") else None
    now_i = span(c.get("now_from"), None) if c.get("now_from") else None
    lf = F["xbold"](s(11))
    for rng, fill, label, level, lcol in ((was_i, _mix(PANEL, MUTED, 0.10), "WAS", c["was"], MUTED),
                                          (now_i, _mix(PANEL, col, 0.16), "NOW", c["price"], col)):
        if not rng:
            continue
        bx0, bx1 = max(x0, X(rng[0]) - step / 2), min(x1, X(rng[1]) + step / 2)
        d.rectangle([s(bx0), s(y0), s(bx1), s(cy1)], fill=fill)
        ly = Y(level)
        xx = bx0
        while xx < bx1:                       # dashed level line
            d.line([s(xx), s(ly), s(min(bx1, xx + 7)), s(ly)], fill=lcol, width=s(2))
            xx += 12
        _spaced(d, (s(bx0 + 4), s(cy1 + 8)), label, lf, lcol, s(1.5))
    xy = [(s(X(i)), s(Y(v))) for i, (_, v) in enumerate(pts)]
    d.line(xy, fill=LINE_LIGHT, width=s(3), joint="curve")
    if now_i:
        seg = xy[max(0, now_i[0] - 1):]
        if len(seg) >= 2:
            d.line(seg, fill=col, width=s(4), joint="curve")
    ex, ey = xy[-1]
    d.ellipse([ex - s(6), ey - s(6), ex + s(6), ey + s(6)], fill=col)


# ── the weekly poster ────────────────────────────────────────────────────────
def week_poster(pulse, chart, week_label):
    """The weekly's lead picture: the week in big numbers (whole market,
    chase, sealed, with the month under each), every booster set's week as a
    bar, and the market chart under them. chart: (title, subtitle, series)
    from discord_reports.market_chart_series, or None."""
    try:
        return _week_poster(pulse, chart, week_label)
    except Exception as e:  # noqa: BLE001
        print(f"  (week poster skipped: {e.__class__.__name__}: {e})")
        return None


def _week_poster(pulse, chart, week_label):
    from PIL import Image, ImageDraw
    if not pulse or pulse["all"][0] is None:
        return market_chart(chart[2], chart[0], chart[1]) if chart else None
    F = _fonts()
    W = 1200
    stats = []
    for label, key in (("Whole market", "all"), ("Chase cards", "chase"), ("Sealed", "sealed")):
        wk, mo = pulse.get(key) or (None, None)
        if wk is not None:
            stats.append((fmt_pct(wk), label + " this week", _signed(wk),
                          f"{fmt_pct(mo)} this month" if mo is not None else None))
    sets = pulse.get("sets") or []
    chart_png = market_chart(chart[2], chart[0], chart[1]) if chart else None
    chart_im = Image.open(io.BytesIO(chart_png)) if chart_png else None
    top = 146 + 34
    sy = top + 132
    BAR_ROW = 38
    H = sy + (44 + len(sets) * BAR_ROW + 24 if len(sets) >= 2 else 0)
    cy = H
    if chart_im:
        H += chart_im.height + 10
    H += 56
    im = Image.new("RGB", (W * SS, H * SS), BG)
    d = ImageDraw.Draw(im)
    s = lambda v: int(round(v * SS))
    a = pulse["all"][0]
    _header(im, d, s, F, W, f"Lorcana week in review · {week_label}",
            [("The market ", TITLE), (fmt_pct(a), _signed(a) if abs(a) >= 0.3 else GOLD)])
    _stats(d, s, F, W, top, stats)
    if len(sets) >= 2:
        _spaced(d, (s(PAD), s(sy)), "EVERY BOOSTER SET THIS WEEK", F["xbold"](s(14)), GOLD, s(3.5))
        span = max(abs(t[1]) for t in sets) or 1
        nx1 = PAD + 330
        mid = nx1 + 30 + (W - PAD - 110 - nx1 - 30) / 2
        half = (W - PAD - 110 - nx1 - 30) / 2
        y = sy + 44
        d.line([s(mid), s(y - 6), s(mid), s(y + len(sets) * BAR_ROW - 10)], fill=ZERO, width=s(2))
        for name, wk, _mo, _key in sets:
            nf = F["bold"](s(20))
            d.text((s(nx1), s(y + 14)), _ellipsize(d, name, nf, s(320)), font=nf, fill=TEXT, anchor="rm")
            bw = half * abs(wk) / span
            col = GREEN if wk >= 0 else RED
            bx0, bx1 = (mid, mid + bw) if wk >= 0 else (mid - bw, mid)
            if bw >= 1:
                d.rounded_rectangle([s(bx0), s(y + 4), s(bx1), s(y + 24)], radius=s(5), fill=col)
            d.text((s(W - PAD), s(y + 14)), fmt_pct(wk), font=F["xbold"](s(20)), fill=col, anchor="rm")
            y += BAR_ROW
    if chart_im:
        im.paste(chart_im.resize((chart_im.width * SS, chart_im.height * SS)), (s((W - chart_im.width) / 2), s(cy)))
    d.text((s(PAD), s(H - 40)), "The packs.ink market index: TCGplayer Market prices, every card weighted equally.",
           font=F["semi"](s(17)), fill=MUTED)
    return _png(im, W, H)
