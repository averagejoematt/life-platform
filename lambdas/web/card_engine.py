"""card_engine.py — #595 (ADR-114): ONE code-drawn renderer for every off-site card.

The OG card is most readers' first pixel — "ahead of the curve" is judged off-site
before anyone clicks. Historically each card surface drew its own Pillow chrome:
``og_image_lambda`` drew the 12 daily page cards, ``og_moments`` drew the permalinked
moment cards, and each new reach surface (character sheet #420, chronicle kit #405)
would have hand-rolled another. This module is the single place a 1200×630 brand card
is drawn — a small template kit (brand tokens + primitives) plus a card-type REGISTRY
that reach surfaces register into, mirroring the evidence registry pattern.

Design contract (ADR-114):
  - Brand tokens (palette, fonts, canvas, margins) live HERE, once. The daily
    ``og_image_lambda`` re-exports the same names so its cards stay byte-identical.
  - Primitives: base_canvas · draw_header · draw_metric · draw_footer · wrapped title ·
    fmt · wrap · an UNCERTAINTY stat (CI range + n) so a projected number on a card can
    never be a bare point estimate the site itself wouldn't show (#551).
  - A card type is a ``build(payload) -> PIL.Image`` fn registered via ``register_card``;
    ``render(card_type, payload)`` draws it. Fixtures drive a unit test per type.
  - SVG-native / self-hosted only: fonts are the repo-bundled TTFs; NO external fetch
    (strict CSP + no-external-HTTP is a hard repo rule).

Pillow-only; ships in the same package as ``og_image_lambda`` (pillow-layer, web/
+ operational/ stacks). It imports no shared-layer platform modules.
"""

import os

from PIL import Image, ImageDraw, ImageFont

# ── Brand tokens ─────────────────────────────────────────────────────────────
# NOTE: these values are the daily-card contract. og_image_lambda re-exports them,
# so changing a value here changes every card. Keep them identical to the historic
# og_image_lambda constants unless you intend to re-skin the whole card family.

BG = (8, 12, 10)  # #080c0a
TEXT = (232, 240, 232)  # #e8f0e8
MUTED = (138, 170, 144)  # #8aaa90
FAINT = (90, 117, 101)  # #5a7565
GREEN = (34, 197, 94)  # #22c55e
BORDER = (14, 26, 18)  # subtle line
AMBER = (240, 180, 41)  # #f0b429 — the "honest miss" accent (#405/#551)

# v5 brand type triad (tokens.css): Fraunces = display/human voice, IBM Plex Mono =
# machine & data. Retired the original Bebas Neue / Space Mono TTFs — those subsets
# shipped with NO basic-Latin glyphs (A–Z unmapped in the cmap), so every off-site
# card rendered as tofu boxes since HP-13. These woff2→ttf conversions of the exact
# fonts the live site serves fix the render AND align the cards with the v5 site.
FONT_DISPLAY = "fraunces-400.ttf"
FONT_MONO = "ibm-plex-mono-400.ttf"
FONT_MONO_BOLD = "ibm-plex-mono-500.ttf"

W, H = 1200, 630
MARGIN = 48  # safe left/right margin

# Fonts are bundled TTFs. og_image_lambda historically shipped them beside itself
# (web/fonts); the canonical source is lambdas/fonts. Probe both so the engine works
# whether it runs from the deployed package or the repo tree (tests).
_FONT_DIRS = [
    os.path.join(os.path.dirname(__file__), "fonts"),
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts"),
]
_font_cache = {}


def font(name, size):
    """Resolve a bundled TTF at a size, caching. Falls back to Pillow's default
    font when the TTF isn't present (e.g. a minimal CI env) so rendering never
    raises — the card is still a valid PNG, just in the default face."""
    key = (name, size)
    if key not in _font_cache:
        loaded = None
        for d in _FONT_DIRS:
            path = os.path.join(d, name)
            try:
                loaded = ImageFont.truetype(path, size)
                break
            except Exception:
                continue
        _font_cache[key] = loaded or ImageFont.load_default()
    return _font_cache[key]


# ── Primitives ───────────────────────────────────────────────────────────────


def base_canvas():
    """A fresh 1200×630 brand card: background + top accent line + bottom bar.
    Returns (img, draw)."""
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, W, 3], fill=GREEN)  # top accent
    draw.rectangle([0, H - 40, W, H], fill=(6, 10, 8))  # bottom bar
    return img, draw


def draw_header(draw, page_label):
    """The brand + page kicker, top-left."""
    draw.text((MARGIN, 28), "averagejoematt.com", fill=MUTED, font=font(FONT_MONO, 13))
    draw.text((MARGIN, 52), str(page_label).upper(), fill=GREEN, font=font(FONT_MONO, 11))


def draw_metric(draw, x, y, value, label, color=TEXT):
    """A big display number with a mono caption beneath — the stat-readout unit."""
    draw.text((x, y), str(value), fill=color, font=font(FONT_DISPLAY, 56))
    draw.text((x, y + 60), label, fill=MUTED, font=font(FONT_MONO, 11))


def draw_footer(draw, left_text="", right_text="updated daily by life-platform"):
    """The footer line: a left note (e.g. 'Day 42') and a right attribution."""
    if left_text:
        draw.text((MARGIN, H - 30), str(left_text), fill=FAINT, font=font(FONT_MONO, 11))
    if right_text:
        draw.text((W - MARGIN, H - 30), str(right_text), fill=FAINT, font=font(FONT_MONO, 11), anchor="ra")


def wrap(text, width=34, max_lines=4):
    """Greedy word-wrap to `width` chars, `max_lines` lines, ellipsizing overflow."""
    words = str(text).split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: width - 1] + "…"
    return lines


def draw_title(draw, text, y, x=MARGIN, size=58, width=30, max_lines=4, color=TEXT, leading=None):
    """Draw a wrapped display-face title starting at y. Returns the y AFTER the block."""
    step = leading if leading is not None else int(size * 1.14)
    f = font(FONT_DISPLAY, size)
    for line in wrap(text, width=width, max_lines=max_lines):
        draw.text((x, y), line.upper(), fill=color, font=f)
        y += step
    return y


def fmt(val, decimals=0, suffix=""):
    """Format a number for a card, em-dash for None."""
    if val is None:
        return "—"
    try:
        if decimals == 0:
            return f"{int(round(float(val)))}{suffix}"
        return f"{round(float(val), decimals)}{suffix}"
    except (TypeError, ValueError):
        return str(val)


def draw_uncertainty(draw, x, y, value, label, ci=None, n=None, decimals=0, suffix="", color=TEXT):
    """The uncertainty grammar on a card (#551/ADR-105): a projected number is
    NEVER a bare point estimate. Draws the value big, then a mono sub-line with the
    CI range and/or sample size when supplied — matching what the site itself shows.

    ci: (lo, hi) tuple in the same units as value; n: sample size (int).
    """
    draw.text((x, y), fmt(value, decimals, suffix), fill=color, font=font(FONT_DISPLAY, 56))
    draw.text((x, y + 60), str(label), fill=MUTED, font=font(FONT_MONO, 11))
    sub = ""
    if ci and ci[0] is not None and ci[1] is not None:
        sub = f"{fmt(ci[0], decimals)}–{fmt(ci[1], decimals)}{suffix} CI"
    if n is not None:
        sub = (sub + " · " if sub else "") + f"n={int(n)}"
    if sub:
        draw.text((x, y + 76), sub, fill=FAINT, font=font(FONT_MONO, 10))


# ── The card-type registry ───────────────────────────────────────────────────
# Reach surfaces register a builder keyed by card type. render() dispatches.

CARD_BUILDERS = {}


def register_card(card_type, builder):
    """Register a builder fn (payload -> PIL.Image) for a card type."""
    CARD_BUILDERS[card_type] = builder
    return builder


def render(card_type, payload):
    """Draw a registered card type from its payload. Raises KeyError if unknown."""
    if card_type not in CARD_BUILDERS:
        raise KeyError(f"card_engine: no builder registered for card type {card_type!r}")
    return CARD_BUILDERS[card_type](payload or {})


def registered_types():
    """The set of card types currently registered (used by the fixture test)."""
    return sorted(CARD_BUILDERS.keys())


# ── First-class reach cards (#420 character, #405 chronicle) ──────────────────
# Registered here so any importer of card_engine gets them; og_image_lambda and
# og_moments also draw the daily/moment cards through the primitives above.


def build_character_card(payload):
    """#420 — the character/RPG sheet as a shareable card, from COMPUTED stats only.

    payload = character_stats.json's shape: {"character": {...}, "pillars": [...]}.
    HONESTY/PRIVACY (ADR-104 + phenoage privacy): renders ONLY computed, privacy-safe
    fields — level, tier, XP, days active, per-pillar levels, streak. NEVER a narrated
    line, a sensitive derivation, or chronological age (there is no age field on this
    card by construction).
    """
    ch = (payload or {}).get("character", {}) or {}
    pillars = (payload or {}).get("pillars", []) or []

    img, draw = base_canvas()
    draw_header(draw, "Character Sheet")

    tier = str(ch.get("tier", "Foundation"))
    level = ch.get("level")
    draw.text((MARGIN, 96), "THE CHARACTER SHEET", fill=TEXT, font=font(FONT_DISPLAY, 66))
    draw.text(
        (MARGIN, 168),
        "A life scored nightly as an RPG character. Every stat is computed, not written.",
        fill=MUTED,
        font=font(FONT_MONO, 14),
    )

    # Headline row — the level + tier + XP + days, all computed.
    draw_metric(draw, MARGIN, 240, fmt(level, 0), f"LEVEL · {tier.upper()}", GREEN)
    draw_metric(draw, 360, 240, fmt(ch.get("xp_total"), 0), "TOTAL XP")
    draw_metric(draw, 640, 240, fmt(ch.get("days_active"), 0), "DAYS ACTIVE")
    draw_metric(draw, 900, 240, fmt(ch.get("level_events_count"), 0), "LEVEL EVENTS")

    # The seven pillars as a compact level strip (computed per-pillar levels only).
    y = 380
    draw.text((MARGIN, y), "THE SEVEN PILLARS", fill=MUTED, font=font(FONT_MONO, 11))
    y += 26
    col_w = (W - 2 * MARGIN) // 7
    for i, p in enumerate(pillars[:7]):
        px = MARGIN + i * col_w
        name = str(p.get("name", ""))[:3].upper()
        plv = fmt(p.get("level"), 0)
        draw.text((px, y), plv, fill=TEXT, font=font(FONT_DISPLAY, 40))
        draw.text((px, y + 44), name, fill=FAINT, font=font(FONT_MONO, 11))

    draw_footer(draw, left_text=f"Level {fmt(level, 0)} · {tier}", right_text="averagejoematt.com/data/character")
    return img


def build_chronicle_card(payload):
    """#405 — the per-chronicle share card. The HONEST-STATS line IS the creative:
    a week graded 57 with a broken streak is the point — never sanitized.

    payload = {"title": str, "label": "Week 05"|"Prologue · Part I", "stats_line":
    "Weight: 300.8 lbs | Week Grade: avg 57 | T0 Streak: 0 days", "date": "YYYY-MM-DD"}.
    Renders only values already published on the post (no new numbers/claims).
    """
    title = str((payload or {}).get("title", "The Measured Life"))
    label = str((payload or {}).get("label", "Chronicle"))
    stats_line = str((payload or {}).get("stats_line", "")).strip()
    date_str = str((payload or {}).get("date", "")).strip()

    img, draw = base_canvas()
    draw_header(draw, "The Measured Life")

    draw.text((MARGIN, 96), label.upper(), fill=AMBER, font=font(FONT_MONO, 13))
    y = draw_title(draw, title, 128, size=62, width=26, max_lines=3)

    # The honest stats line — split on the post's own " | " separators onto its own row.
    if stats_line:
        parts = [seg.strip() for seg in stats_line.split("|") if seg.strip()]
        row_y = max(y + 24, 400)
        col_w = (W - 2 * MARGIN) // max(1, min(len(parts), 3))
        for i, seg in enumerate(parts[:3]):
            # seg looks like "Week Grade: avg 57" — split the caption from the value.
            if ":" in seg:
                cap, _, val = seg.partition(":")
                cap, val = cap.strip(), val.strip()
            else:
                cap, val = "", seg
            px = MARGIN + i * col_w
            draw.text((px, row_y), val or "—", fill=TEXT, font=font(FONT_DISPLAY, 44))
            if cap:
                draw.text((px, row_y + 48), cap.upper(), fill=MUTED, font=font(FONT_MONO, 11))

    draw_footer(
        draw,
        left_text=(date_str or "every failure included"),
        right_text="averagejoematt.com/story/chronicle",
    )
    return img


register_card("character", build_character_card)
register_card("chronicle", build_chronicle_card)
