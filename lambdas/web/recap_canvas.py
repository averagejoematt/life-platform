"""recap_canvas.py — the portrait card the owner actually posts (#3744).

WHY A PORTRAIT FORMAT AT ALL

#1632 declined Instagram in July and its reasoning still stands, but it named the real
cost honestly: *"The 13 daily OG cards are 1200×630 link-unfurl previews, not social
posts… wrong aspect ratio (Instagram wants 1080×1080 or 1080×1350), wrong information
density… They would render letterboxed and thin."* That decline was about AUTO-POSTING —
Meta App Review, a Business account, a linked Page. This is not that: the card is
delivered privately to the owner's phone and he posts it by hand, which is exactly the
"human selection only" posture ADR-140 rule 5 already requires of any vitals-derived mark.

So the cost #1632 named is the work here: a real portrait format, in the same engine.

WHY IT SHARES card_engine RATHER THAN COPYING IT

An unfurl card read at thumbnail size next to a link and a card read full-bleed on a phone
want different type scales, but they must not want a different BRAND. Two engines drift:
the dial moves, the greens diverge, and a year later the grid and the site look like two
projects. So `card_engine` gained a `size=` argument on its three size-dependent
primitives (default unchanged, byte-identical) and everything portrait-specific lives
here — the scale, the composition, the day kicker.

THE COMPOSITION

  kicker    DAY 8 · SAT 13 SEP          small, mono, green — where you are in the story
  hero      2.3 lb                      the number, at display scale
  label     DOWN THIS WEEK              what it is, from classify_delta (never a static word)
  sub       7-day rate CI -3.0 to -1.5  the uncertainty, when there is one (#551)
  lines     319.7 lb today              the supporting detail
  [band]    a second template, if one earned the slot
  footer    averagejoematt.com          the mark, unmissable and not shouted

Self-contained on purpose: the account is dedicated to the experiment, so the card never
has to explain who he is, and the caption carries the words.
"""

from __future__ import annotations

from typing import Any

from web import card_engine as ce

#: Instagram portrait. 1080x1350 rather than 1080x1080 — the taller frame takes more of
#: the feed and gives the hero number room to breathe at phone scale.
PORTRAIT = (1080, 1350)
MARGIN_P = 72

# Type scale. Larger than the unfurl card's throughout: this is read at arm's length on a
# phone, not at 300px next to a link.
SIZE_KICKER = 26
SIZE_HERO = 150
SIZE_HERO_SMALL = 86  # a hero that is words rather than a number
SIZE_LABEL = 30
SIZE_SUB = 22
SIZE_LINE = 28
SIZE_BAND_LABEL = 22
SIZE_BAND_VALUE = 54


def portrait_canvas():
    """A fresh 1080×1350 card carrying the same brand chrome as every other card."""
    return ce.base_canvas(size=PORTRAIT, margin=MARGIN_P)


def _text(draw, xy, s, *, font_name, size, fill):
    draw.text(xy, str(s), fill=fill, font=ce.font(font_name, size))


def draw_day_kicker(draw, day_label: str, date_label: str, y: int = 120) -> int:
    """`DAY 8 · SAT 13 SEP` — where this frame sits in the story. Returns the next y."""
    parts = [p for p in (day_label, date_label) if p]
    _text(draw, (MARGIN_P, y), " · ".join(parts).upper(), font_name=ce.FONT_MONO_BOLD, size=SIZE_KICKER, fill=ce.GREEN)
    return y + SIZE_KICKER + 44


def draw_hero(draw, hero: str, label: str, *, y: int, direction: str | None = None, sub: str | None = None) -> int:
    """The number and what it is. Colour comes from `direction`, never from the caller.

    #3285 shipped a weight GAIN painted success-green under the caption "LOST": a static
    label and a static colour over a signed value. The fix there was `classify_delta`, and
    the reason the mapping lives HERE rather than at the call site is that a card renderer
    is exactly where someone would next hard-code a green.
    """
    hero_s = str(hero)
    size = SIZE_HERO if len(hero_s) <= 9 else SIZE_HERO_SMALL
    _text(draw, (MARGIN_P, y), hero_s, font_name=ce.FONT_DISPLAY, size=size, fill=ce.TEXT)
    y += int(size * 1.12)

    colour = ce.MUTED
    if direction == "down":
        colour = ce.GREEN  # losing weight is the goal; green is earned, not decorative
    elif direction == "up":
        colour = ce.AMBER  # the honest-miss accent (#405/#551), never red
    _text(draw, (MARGIN_P, y), str(label).upper(), font_name=ce.FONT_MONO_BOLD, size=SIZE_LABEL, fill=colour)
    y += SIZE_LABEL + 18

    if sub:
        _text(draw, (MARGIN_P, y), sub, font_name=ce.FONT_MONO, size=SIZE_SUB, fill=ce.FAINT)
        y += SIZE_SUB + 16
    return y + 10


def draw_lines(draw, lines: list[str], *, y: int) -> int:
    for line in lines or []:
        for wrapped in ce.wrap(str(line), width=34, max_lines=2):
            _text(draw, (MARGIN_P, y), wrapped, font_name=ce.FONT_MONO, size=SIZE_LINE, fill=ce.MUTED)
            y += SIZE_LINE + 12
    return y + 8


def draw_band(draw, copy: dict[str, Any], *, y: int) -> int:
    """The second template, as a band beneath the hero — present only when one earned it."""
    cw, _ch = PORTRAIT
    draw.rectangle([MARGIN_P, y, cw - MARGIN_P, y + 2], fill=ce.BORDER)
    y += 34
    _text(draw, (MARGIN_P, y), str(copy.get("label", "")).upper(), font_name=ce.FONT_MONO_BOLD, size=SIZE_BAND_LABEL, fill=ce.GREEN)
    y += SIZE_BAND_LABEL + 16
    if copy.get("hero"):
        _text(draw, (MARGIN_P, y), copy["hero"], font_name=ce.FONT_DISPLAY, size=SIZE_BAND_VALUE, fill=ce.TEXT)
        y += SIZE_BAND_VALUE + 16
    for line in copy.get("lines") or []:
        for wrapped in ce.wrap(str(line), width=38, max_lines=2):
            _text(draw, (MARGIN_P, y), wrapped, font_name=ce.FONT_MONO, size=SIZE_SUB, fill=ce.MUTED)
            y += SIZE_SUB + 10
    return y


def draw_portrait_footer(draw, left_text: str = "", right_text: str = "averagejoematt.com"):
    ce.draw_footer(draw, left_text=left_text, right_text=right_text, canvas=PORTRAIT, margin=MARGIN_P)


#: Where the content sits. Two zones rather than one centred block: a card with two
#: templates reads as headline + supporting beat, and a card with one reads as a single
#: statement. Centring both produced a top gap AND a bottom gap on the two-template case,
#: which on a phone looks like a broken layout rather than a quiet one.
HERO_TOP_TWO = 300
HERO_TOP_ONE = 470
BAND_TOP = 830


def render_card(copies: list[dict[str, Any]], *, day_label: str = "", date_label: str = "", footer_left: str = ""):
    """Compose one portrait card from 1-2 template copies. Returns a PIL Image.

    Draws exactly what it is given: the picker decided WHAT, the gate decided WHETHER, and
    the copy functions already raised on anything they could not say (`RecapNullFact`).
    """
    if not copies:
        raise ValueError("render_card called with no template copy — the picker should have returned no card")

    img, draw = portrait_canvas()
    draw_day_kicker(draw, day_label, date_label)

    two = len(copies) > 1
    head = copies[0]
    y = draw_hero(
        draw,
        head.get("hero") or "",
        head.get("label") or "",
        y=HERO_TOP_TWO if two else HERO_TOP_ONE,
        direction=head.get("direction"),
        sub=head.get("sub"),
    )
    y = draw_lines(draw, head.get("lines") or [], y=y)

    if two:
        # Never overlap the hero block, however tall it ran.
        draw_band(draw, copies[1], y=max(BAND_TOP, y + 48))

    draw_portrait_footer(draw, left_text=footer_left)
    return img


def to_png_bytes(img) -> bytes:
    """PNG bytes — the lossless copy. Telegram recompresses; the email attachment does not."""
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
