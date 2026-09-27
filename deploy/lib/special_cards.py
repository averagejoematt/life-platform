"""special_cards.py — the card kit the Instagram SPECIALS are drawn with.

A "special" is a carousel that is not the daily and not the weekly: one topic, read
across a window, posted by hand. `build_nutrition_special_cards.py` is the reference
implementation and the first caller.

WHAT LIVES HERE AND WHAT DOES NOT

Here: the third ground and the arithmetic that chose it, the portrait canvas wired to
`recap_qa`'s recording proxy, the block-composition layout, the block vocabulary
(`b_*`), and `render_pack()` — which runs the privacy gate BEFORE any frame is rendered
and the render audit on every frame before it is written.

Not here: what the card SAYS. A topic module owns its own data load, its card functions
and its caption. The kit draws; it never decides what is true.

THE THIRD GROUND

`card_engine.base_canvas(ground=...)` exists so one card family can be told apart at
thumbnail without becoming a second brand (#3741). Two grounds were already spoken for —
the daily near-black (8, 12, 10) and the weekly navy (11, 20, 44) — and the rule the
weekly established governs the third:

    The ground carries the card TYPE, never a verdict on the card's contents.

So it comes from OUTSIDE the semantic vocabulary (GREEN = earned, AMBER = an honest miss,
red banned outright), and it is FIXED: identical on a good month and a bad one.

The separation is measured in CIELAB, not RGB. The first plum tried sat 24 RGB units from
the weekly navy and read as navy at 110px. The navy's own accepted separation from the
daily ground is dE 19.4, so that is the bar: this ground holds dE 22.5 from the navy and
35.8 from the daily, at hue 324 degrees — magenta-violet, nowhere near the banned red
(~20 degrees). `audit_ground()` prints the whole table.

LAYOUT

Cards compose from BLOCKS — `(height, render)` pairs — and `compose()` measures the stack
before drawing so the leftover height is spread between them. Every card hand-tuned
top-down left its bottom third dead, which is the same finding the recap panel made about
the dailies. Two rules that bite: a rule drawn as its own block gets orphaned by
`stretch_last` (bind it to its line with `b_closing`), and any text drawn beside a label
must be MEASURED against the room left (`anchored_note` does), or it lands in the gutter
and `recap_qa` reports it as a soft note.

COLOUR IS A CLAIM

`b_sufficiency_bars` colours by the platform's grade bands — right for a score, wrong for
a count, because a tall bar would then read as "earned". Counts use `b_neutral_bars`,
which has no semantic accent at all.
"""

from __future__ import annotations

import datetime as dt
import os
import pathlib
import sys
from typing import Any, Callable, Sequence

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "lambdas"))

from content import recap_gate  # noqa: E402
from web import (
    card_engine as ce,  # noqa: E402
    recap_charts as ch,  # noqa: E402
    recap_qa,  # noqa: E402
)

TABLE = "life-platform"
REGION = "us-west-2"
PORTRAIT = (1080, 1350)
M = 72
W_CONTENT = PORTRAIT[0] - 2 * M

#: The special-series ground. Fixed — see the module docstring, and `audit_ground()` for
#: the arithmetic. Changing it re-skins every special ever posted.
SPECIAL_GROUND = (44, 4, 50)

DIM = (112, 140, 124)

#: Where content sits, and where the one-line note at the foot of a card is anchored.
CONTENT_TOP = 236
CONTENT_FLOOR = 1210
NOTE_Y = 1236


# ── the arithmetic behind the ground ─────────────────────────────────────────
def _lum(c) -> float:
    def ch_(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (ch_(x) for x in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg, bg) -> float:
    a, b = _lum(fg), _lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _dist(a, b) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _lab(c) -> tuple[float, float, float]:
    """CIELAB. Two near-black grounds can sit 24 RGB units apart and still read identically
    in a grid; at this end of the range only a perceptual space answers the question."""

    def lin(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(x) for x in c)
    x = 0.4124 * r + 0.3576 * g + 0.1805 * b
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = 0.0193 * r + 0.1192 * g + 0.9505 * b
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116  # noqa: E731
    fx, fy, fz = f(x / 0.95047), f(y / 1.0), f(z / 1.08883)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e(a, b) -> float:
    return sum((x - y) ** 2 for x, y in zip(_lab(a), _lab(b))) ** 0.5


def hue_angle(c) -> float:
    import math

    _, a, b = _lab(c)
    return math.degrees(math.atan2(b, a)) % 360


def audit_ground(ground=SPECIAL_GROUND) -> dict[str, Any]:
    """The ground's own numbers, printed rather than asserted."""
    weekly = (11, 20, 44)
    out = {
        "ground": ground,
        "hue_angle_deg": round(hue_angle(ground)),
        "faint_text_contrast": round(contrast(ce.FAINT, ground), 2),
        "muted_text_contrast": round(contrast(ce.MUTED, ground), 2),
        "body_text_contrast": round(contrast(ce.TEXT, ground), 2),
        "daily_ground_faint_contrast": round(contrast(ce.FAINT, ce.BG), 2),
        "weekly_ground_faint_contrast": round(contrast(ce.FAINT, weekly), 2),
        "luminance_vs_daily": round(_lum(ground) / _lum(ce.BG), 2),
        "deltaE_to_daily_ground": round(delta_e(ground, ce.BG), 1),
        "deltaE_to_weekly_ground": round(delta_e(ground, weekly), 1),
        "deltaE_weekly_to_daily_the_bar": round(delta_e(weekly, ce.BG), 1),
        "rgb_distance_to_GREEN": round(_dist(ground, ce.GREEN), 1),
        "rgb_distance_to_AMBER": round(_dist(ground, ce.AMBER), 1),
    }
    out["nearer_a_ground_than_an_accent"] = _dist(ground, ce.BG) < min(out["rgb_distance_to_GREEN"], out["rgb_distance_to_AMBER"])
    out["separated_from_both_grounds"] = (
        min(out["deltaE_to_daily_ground"], out["deltaE_to_weekly_ground"]) >= out["deltaE_weekly_to_daily_the_bar"]
    )
    return out


# ── canvas + composition ─────────────────────────────────────────────────────
# ── drawing ──────────────────────────────────────────────────────────────────
# Cards are composed from BLOCKS — (height, render) pairs — rather than drawn top-down
# with hand-tuned y values. The recap panel's first finding on the dailies was that
# content stopped around y 1170 on a 1350 canvas and the bottom third sat dead; the same
# thing happened to the first draft of every card here. `compose()` measures the stack
# first and spreads the slack between the blocks, so a card fills its frame whatever the
# data made it say.
CONTENT_TOP = 236
CONTENT_FLOOR = 1210


def canvas():
    """A special-ground portrait whose draw RECORDS every string, so recap_qa can audit it."""
    img, draw = ce.base_canvas(size=PORTRAIT, margin=M, ground=SPECIAL_GROUND)
    rec = recap_qa.RecordingDraw(draw)
    img.info["recap_strings"] = rec.records
    return img, rec


def compose(blocks, *, top: int = CONTENT_TOP, floor: int = CONTENT_FLOOR, max_gap: int = 78, stretch_last: bool = False) -> int:
    """Draw a stack of blocks, spreading the leftover height between them.

    `max_gap` stops a two-block card from drifting into two lonely strips. When the cap
    leaves slack over, `stretch_last` hands the remainder to the final block — right when
    that block is a chart or a closing line that reads well sitting on the floor, wrong
    when it is one fact among several, which is why it is a per-card decision and not the
    default. `--debug-layout` prints where each card's stack actually ended.
    """
    blocks = [b for b in blocks if b]
    n = len(blocks)
    total = sum(h for h, _ in blocks)
    slack = max(0, floor - top - total)
    gap = min(max_gap, slack // max(n - 1, 1))
    extra = max(0, floor - top - total - gap * (n - 1)) if (stretch_last and n > 1) else 0
    y = top
    for i, (h, render) in enumerate(blocks):
        if i == n - 1:
            y += extra
        render(y)
        y += h + gap
    return y - gap


def header(draw, index: int, total: int, sub: str, *, title: str = "NUTRITION", series: str = "") -> None:
    """The serial every card in the set carries — the thing a grid visitor reads at 110px."""
    df = ce.font(ce.FONT_DISPLAY, 60)
    draw.text((M, 84), title.upper(), fill=ce.TEXT, font=df)
    try:
        w = draw.textlength(title.upper(), font=df)
    except Exception:  # noqa: BLE001
        w = 420
    draw.text((M + w + 22, 112), f"·  {series}", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 26))
    draw.text((M, 160), sub.upper(), fill=DIM, font=ce.font(ce.FONT_MONO, 22))
    draw.text((PORTRAIT[0] - M, 160), f"{index} / {total}", fill=DIM, font=ce.font(ce.FONT_MONO, 22), anchor="ra")


def b_section(draw, title: str, colour):
    def render(y):
        draw.rectangle([M, y + 6, M + 6, y + 40], fill=colour)
        draw.text((M + 22, y), title.upper(), fill=colour, font=ce.font(ce.FONT_MONO_BOLD, 34))

    return (48, render)


def b_hero(draw, text: str, *, size: int = 150, suffix: str = "", colour=None, suffix_size: int = 40, suffix_lines=None):
    font = ch.fit_text(draw, text, font_name=ce.FONT_DISPLAY, max_size=size, min_size=54, width=W_CONTENT - 300)

    def render(y):
        draw.text((M, y), text, fill=colour or ce.TEXT, font=font)
        tail = suffix_lines or ([suffix] if suffix else [])
        if not tail:
            return
        try:
            w = draw.textlength(text, font=font)
        except Exception:  # noqa: BLE001
            w = W_CONTENT * 0.5
        ty = y + int(font.size * 0.58)
        for line in tail:
            draw.text((M + w + 26, ty), line, fill=ce.MUTED, font=ce.font(ce.FONT_MONO, suffix_size))
            ty += suffix_size + 8

    return (int(font.size * 1.04), render)


def b_lines(draw, text: str, *, size: int = 27, colour=None, width: int = 46, gap: int = 12, max_lines: int = 4):
    wrapped = ce.wrap(text, width=width, max_lines=max_lines)

    def render(y):
        yy = y
        for line in wrapped:
            draw.text((M, yy), line, fill=colour or ce.MUTED, font=ce.font(ce.FONT_MONO, size))
            yy += size + gap

    return (len(wrapped) * (size + gap) - gap, render)


def b_fact(draw, label: str, value: str, *, colour=None, width: int = 44, size: int = 29):
    wrapped = ce.wrap(value, width=width, max_lines=3)

    def render(y):
        draw.text((M, y), label.upper(), fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 21))
        yy = y + 31
        for line in wrapped:
            draw.text((M, yy), line, fill=colour or ce.TEXT, font=ce.font(ce.FONT_MONO, size))
            yy += size + 9

    return (31 + len(wrapped) * (size + 9) - 9, render)


def b_rule(draw):
    return (2, lambda y: ch.draw_rule(draw, x=M, y=y, w=W_CONTENT))


def b_closing(draw, text: str, *, size: int = 27, width: int = 46):
    """A rule and the line beneath it as ONE block. Composed separately, `stretch_last`
    pushed the line to the floor and left the rule stranded 250px above it."""
    wrapped = ce.wrap(text, width=width, max_lines=3)

    def render(y):
        ch.draw_rule(draw, x=M, y=y, w=W_CONTENT)
        yy = y + 34
        for line in wrapped:
            draw.text((M, yy), line, fill=ce.MUTED, font=ce.font(ce.FONT_MONO, size))
            yy += size + 12

    return (34 + len(wrapped) * (size + 12) - 12, render)


def b_dots(draw, done: int, total: int):
    return (34, lambda y: ch.draw_dots(draw, done, total, x=M, y=y, size=26, gap=14, colour=ce.GREEN))


def b_sufficiency_bars(draw, items, *, row_h: int = 60):
    def render(y):
        ch.draw_component_bars(
            draw,
            items,
            x=M,
            y=y,
            w=W_CONTENT - 56,
            label_w=250,
            row_h=row_h,
            label_size=24,
            value_size=24,
            bar_h=22,
            track=ch.track_for(SPECIAL_GROUND),
        )

    return (row_h * len(items), render)


def b_neutral_bars(draw, items, *, maximum: float, label_w: int = 380, row_h: int = 58):
    """Frequency bars in the ground's own tone — NOT `draw_component_bars`.

    That helper colours by the platform's grade bands, which is right for a sufficiency
    score and wrong here: 18 days of jello is not 90% earned. A count is not a verdict, so
    these bars carry no semantic accent at all.
    """
    bar_x = M + label_w
    bar_w = W_CONTENT - label_w - 70

    def render(y):
        track = ch.track_for(SPECIAL_GROUND)
        yy = y
        for name, value in items:
            frac = max(0.0, min(1.0, value / maximum))
            draw.text((M, yy + 2), str(name).upper(), fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 22))
            draw.rounded_rectangle([bar_x, yy, bar_x + bar_w, yy + 22], radius=11, fill=track)
            draw.rounded_rectangle([bar_x, yy, bar_x + max(int(bar_w * frac), 22), yy + 22], radius=11, fill=DIM)
            draw.text((bar_x + bar_w + 16, yy), f"{value:g}", fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 22))
            yy += row_h

    return (row_h * len(items), render)


def b_spark(draw, values, *, h: int = 130, colour=None):
    return (h + 16, lambda y: ch.draw_sparkline(draw, values, x=M, y=y, w=W_CONTENT, h=h, colour=colour or ce.GREEN))


def b_plain_spark(draw, values, *, h: int = 130, colour=None, mean_line: bool = True):
    """A line with no value labels and an average rule — for a series whose FIRST point is
    its maximum. `draw_sparkline` labels both ends, and its first-value label has nowhere
    to go when the first point is the top of the chart: it lands inside the plot, on the
    line. The range is stated in this card's hero anyway, so the labels are noise here."""
    vals = [v for v in values if v is not None]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    n = max(len(values) - 1, 1)

    def render(y):
        pts = [(M + W_CONTENT * (i / n), y + h - h * ((v - lo) / span)) for i, v in enumerate(values) if v is not None]
        draw.line([(M, y + h), (M + W_CONTENT, y + h)], fill=ce.BORDER, width=2)
        if mean_line:
            avg = sum(vals) / len(vals)
            ay = y + h - h * ((avg - lo) / span)
            for seg in range(0, W_CONTENT, 24):
                draw.line([(M + seg, ay), (M + seg + 12, ay)], fill=DIM, width=2)
        draw.line(pts, fill=colour or ce.MUTED, width=4, joint="curve")

    return (h + 16, render)


def b_table(draw, rows, headers, *, cols=(0, 330, 530, 730, 936), row_h: int = 54):
    def render(y):
        for x, label in zip(cols[1:], headers):
            draw.text((M + x, y), label, fill=DIM, font=ce.font(ce.FONT_MONO_BOLD, 20), anchor="ra")
        yy = y + 42
        ch.draw_rule(draw, x=M, y=yy, w=W_CONTENT)
        yy += 26
        for row in rows:
            draw.text((M, yy), row[0], fill=ce.TEXT, font=ce.font(ce.FONT_MONO_BOLD, 28))
            for x, cell in zip(cols[1:], row[1:]):
                draw.text((M + x, yy), cell, fill=ce.TEXT, font=ce.font(ce.FONT_MONO, 28), anchor="ra")
            yy += row_h

    return (42 + 26 + row_h * len(rows), render)


def b_numbered(draw, items, *, width: int = 40, size: int = 28):
    wrapped = [(n, ce.wrap(t, width=width, max_lines=3)) for n, t in items]

    def render(y):
        yy = y
        for n, lines_ in wrapped:
            draw.text((M, yy), n, fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 30))
            ty = yy
            for line in lines_:
                draw.text((M + 76, ty), line, fill=ce.TEXT, font=ce.font(ce.FONT_MONO, size))
                ty += size + 12
            yy = ty + 26

    return (sum(len(l) * (size + 12) + 26 for _n, l in wrapped) - 26, render)


def b_quote(draw, line: str, attribution: str, *, size: int = 33, width: int = 36):
    """A coach's sentence, set in the display face. The attribution is not optional: a
    quote on a card the owner posts has to say who said it and when."""
    wrapped = ce.wrap(line, width=width, max_lines=4)

    def render(y):
        draw.rectangle([M, y + 4, M + 5, y + len(wrapped) * (size + 10) - 4], fill=ce.GREEN)
        yy = y
        for text in wrapped:
            draw.text((M + 26, yy), text, fill=ce.TEXT, font=ce.font(ce.FONT_DISPLAY, size))
            yy += size + 10
        draw.text((M + 26, yy + 8), attribution.upper(), fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 19))

    return (len(wrapped) * (size + 10) + 34, render)


def _day_label(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d.strftime('%b')} {d.day}".lower()


def anchored_note(draw, label: str, text: str, *, y: int = 1236) -> None:
    """The bottom line every card in the set ends on — the dailies' NEXT device, reused so
    the special composes to the same frame rather than trailing off.

    The size is MEASURED against the room left beside the label, not assumed: the first
    draft put four of these into the right-hand gutter, which recap_qa reports as a soft
    note precisely so it gets fixed rather than shipped."""
    x = M + 130
    font = ch.fit_text(draw, text, font_name=ce.FONT_MONO, max_size=25, min_size=17, width=PORTRAIT[0] - M - x, step=2)
    draw.text((M, y + 4), label.upper(), fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 22))
    draw.text((x, y), text, fill=ce.MUTED, font=font)


def footer(draw, left: str) -> None:
    ce.draw_footer(draw, left_text=left, right_text="averagejoematt.com", canvas=PORTRAIT, margin=M)


def _pct(v: float) -> str:
    """A sufficiency percentage. Under 10 it keeps its decimal: 1.5% and 2% are not the
    same claim, and the bar beside it already rounds."""
    return f"{v:.0f}%" if v >= 10 else f"{v:.1f}%"


# ── the run: gate, render, audit, write ──────────────────────────────────────
def prepare_out(out: pathlib.Path, force: bool) -> None:
    """Never destroy a pack in place — a folder the owner has been posting from is his."""
    if not out.exists() or not any(out.iterdir()):
        out.mkdir(parents=True, exist_ok=True)
        return
    if not force:
        sys.exit(f"refusing: {out} exists and is not empty. Pass --force to move it aside, or --out to a new path.")
    aside = out.with_name(f"{out.name}.bak-{dt.datetime.now():%Y%m%d-%H%M%S}")
    out.rename(aside)
    print(f"moved the existing pack aside -> {aside}")
    out.mkdir(parents=True)


def render_pack(
    cards: Sequence[Callable[[dict, int], Any]],
    data: dict,
    *,
    out: pathlib.Path,
    caption_text: str,
    gate_items: Sequence[tuple[str, str]] = (),
    gate_free_text: Sequence[str] = (),
    readme: str = "",
    force: bool = False,
    context: str = "special-card",
) -> int:
    """Gate, draw, audit, write. The order is the daily card's and is not negotiable.

    The privacy gate runs BEFORE the first frame — a blocked term costs CPU, never a
    public frame — and `recap_qa` audits every drawn frame before it reaches disk. Either
    one failing stops the run rather than writing a partial pack.
    """
    verdict = recap_gate.gate(
        [caption_text] + list(gate_free_text),
        items=list(gate_items),
        free_text=[caption_text] + list(gate_free_text),
        context=context,
    )
    if not verdict.may_send:
        sys.exit(f"held by the privacy gate: {verdict.reason}")
    print(f"privacy gate: {verdict.to_dict()}")

    prepare_out(out, force)
    total = len(cards)
    for i, build in enumerate(cards, start=1):
        img = build(data, i)
        result = recap_qa.audit_image(img, margin=M)
        if not result.may_store:
            sys.exit(f"card {i} held by render QA: {result.hard[:4]}")
        if result.soft:
            print(f"  card {i}: soft notes {result.soft[:3]}")
        path = out / f"card-{i}of{total}.png"
        img.save(path, format="PNG", optimize=True)
        print(f"  card {i}/{total} {path.name}  ({path.stat().st_size//1024} KB, {result.strings} strings, QA clean)")

    (out / "caption.txt").write_text(caption_text + "\n")
    if readme:
        (out / "README.md").write_text(readme)
    print(f"\n{total} cards + caption in {out}")
    return 0
