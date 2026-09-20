"""recap_charts.py — the small marks a recap card is built from (#3744).

WHY THIS EXISTS

The first cards shipped a single huge number and three lines of mono text, and the owner's
verdict was exact: *"not posts i would be excited to post each day… more creative, more
data, more detail, more throughline, more nod to the experiment."* He was right, and the
measurable form of being right is that the platform had 53 fields on the day and the card
drew four of them. The day's own GRADE, its six component scores, the readiness arc, the
cumulative loss since Day 1, the distance to goal — all present, none drawn.

Text cannot carry that much without becoming a spreadsheet. Marks can. These are the marks.

RULES THEY ALL FOLLOW
  - a value the card does not have is NOT DRAWN — no zero-height bar standing in for a
    missing score, no flat sparkline standing in for an unweighed week (#3527's class, on
    a surface that outlives its correction);
  - colour carries meaning and is derived, never chosen at the call site: green is earned,
    amber is the honest miss (#405/#551), and no mark paints a direction it was handed;
  - everything is drawn with Pillow primitives at the card's own scale — no chart library,
    no second renderer, the same discipline as `card_engine`.
"""

from __future__ import annotations

from typing import Any, Sequence

from web import card_engine as ce

#: The unfilled track behind a bar. It is the GROUND, lifted — not a fixed near-black —
#: because the weekly reckoning is drawn on its own ground (#3741) and a track pinned to
#: the daily's green-black reads as a foreign strip laid across it. `track_for(ce.BG)`
#: returns the historic (18, 26, 20) exactly, so every daily card is unchanged.
_TRACK_LIFT = (10, 14, 10)


def track_for(ground=None):
    """The track tone for a card drawn on `ground`. Defaults to the daily ground."""
    import web.card_engine as _ce

    g = tuple(ground) if ground else _ce.BG
    return tuple(min(255, c + d) for c, d in zip(g, _TRACK_LIFT))


#: The worst band's colour. Amber, deeper — never red (see draw_component_bars).
AMBER_DEEP = (176, 116, 36)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def draw_sparkline(
    draw,
    values: Sequence[float | None],
    *,
    x: int,
    y: int,
    w: int,
    h: int,
    colour=None,
    dot_last: bool = True,
    baseline: bool = True,
    dot_r: int = 6,
) -> bool:
    """A trend, at a glance. Gaps in the series are GAPS — the line breaks.

    A weigh-in he did not take is not a value between the ones he did. Interpolating
    across it would draw a smooth descent through days that never happened, which is the
    prettiest way to lie on a chart.
    """
    pts = [(i, v) for i, v in enumerate(values or []) if v is not None]
    if len(pts) < 2:
        return False
    lo = min(v for _i, v in pts)
    hi = max(v for _i, v in pts)
    span = (hi - lo) or 1.0
    n = max(len(values) - 1, 1)
    colour = colour or ce.MUTED

    def _xy(i, v):
        return (x + w * (i / n), y + h - h * ((v - lo) / span))

    if baseline:
        draw.line([(x, y + h), (x + w, y + h)], fill=ce.BORDER, width=2)

    # Runs of ADJACENT days become line segments; an isolated measurement becomes a dot.
    # He has one weigh-in in week 1, so days 1 and 7 are never adjacent — connecting them
    # would draw a smooth descent through five days that were never measured. But refusing
    # to draw anything at all was also wrong: two dots, one high and one low, tell the
    # story honestly and are still a chart. Line where the data is continuous, dots where
    # it is not.
    run: list[tuple[float, float]] = []
    last_i = None
    drew = False

    def _flush(points):
        nonlocal drew
        if len(points) > 1:
            draw.line(points, fill=colour, width=4, joint="curve")
            drew = True
        elif len(points) == 1:
            cx, cy = points[0]
            draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=colour)
            drew = True

    for i, v in pts:
        if last_i is not None and i != last_i + 1:
            _flush(run)
            run = []
        run.append(_xy(i, v))
        last_i = i
    _flush(run)

    if dot_last and pts:
        cx, cy = _xy(*pts[-1])
        r = dot_r + 3
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour)
        # The newest reading gets its value, so a two-dot chart is still readable.
        ly = cy - 46 if cy - 46 >= y else cy + 20
        # The newest reading is at the right edge by construction; a centred label there
        # runs into the gutter. Right-anchor it to the chart's own edge instead.
        draw.text((min(cx - 12, x + w - 30), ly), f"{pts[-1][1]:.1f}", fill=colour, font=ce.font(ce.FONT_MONO, 20), anchor="ra")
    if pts and len(pts) > 1:
        fx, fy = _xy(*pts[0])
        fly = fy - 46 if fy - 46 >= y else fy + 20
        draw.text((fx, fly), f"{pts[0][1]:.1f}", fill=(112, 140, 124), font=ce.font(ce.FONT_MONO, 20))
    return drew


def draw_day_ruler(draw, values: Sequence[float | None], *, x: int, y: int, w: int, size: int = 10) -> None:
    """One tick per day under a sparkline: filled = measured, hollow = not.

    The rule "dots, not a line — the days between were not measured" DRAWN, so the
    honesty is visible before it is read.
    """
    n = len(values or [])
    if n < 2:
        return
    step = w / (n - 1)
    for i, v in enumerate(values):
        cx = x + i * step
        box = [cx - size / 2, y, cx + size / 2, y + size]
        if v is not None:
            draw.ellipse(box, fill=ce.GREEN)
        else:
            draw.ellipse(box, outline=(40, 56, 44), width=2)


def draw_progress(
    draw,
    fraction: float,
    *,
    x: int,
    y: int,
    w: int,
    h: int = 18,
    colour=None,
    track=None,
) -> None:
    """How far along a long road is. Clamped, never over-filled, never negative."""
    frac = max(0.0, min(1.0, float(fraction)))
    draw.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=track or track_for())
    if frac > 0:
        filled = max(int(w * frac), h)  # a sliver still reads as a sliver, not as nothing
        draw.rounded_rectangle([x, y, x + filled, y + h], radius=h // 2, fill=colour or ce.GREEN)


def draw_component_bars(
    draw,
    items: Sequence[tuple[str, float | None]],
    *,
    x: int,
    y: int,
    w: int,
    label_w: int = 250,
    row_h: int = 46,
    label_size: int = 24,
    value_size: int = 24,
    bar_h: int = 20,
    track=None,
) -> int:
    """The day's components, each a labelled 0-100 bar. Returns the y it ended at.

    Sorted worst-first on purpose. The interesting thing about a C- day is which part
    earned it, and burying a 29 under a 84 is how a scorecard becomes decoration.
    """
    rows = [(k, v) for k, v in items if v is not None]
    if not rows:
        return y
    rows.sort(key=lambda kv: kv[1])
    bar_x = x + label_w
    bar_w = w - label_w
    for name, score in rows:
        frac = max(0.0, min(1.0, float(score) / 100.0))
        # Derived, not chosen: the platform's own grade bands, so a bar and a letter can
        # never disagree about whether a number was good. Two hues only — green earned,
        # amber missed, deeper amber for the worst band. Never red (#405/#551; the panel
        # review found terracotta bars reading as a report card).
        colour = ce.GREEN if score >= 70 else (ce.AMBER if score >= 35 else AMBER_DEEP)
        draw.text((x, y + 4), str(name).upper(), fill=ce.MUTED, font=ce.font(ce.FONT_MONO, label_size))
        r = bar_h // 2
        draw.rounded_rectangle([bar_x, y + 4, bar_x + bar_w, y + 4 + bar_h], radius=r, fill=track or track_for())
        if frac > 0:
            draw.rounded_rectangle([bar_x, y + 4, bar_x + max(int(bar_w * frac), bar_h), y + 4 + bar_h], radius=r, fill=colour)
        draw.text((bar_x + bar_w + 16, y + 4), f"{int(round(score))}", fill=ce.MUTED, font=ce.font(ce.FONT_MONO, value_size))
        y += row_h
    return y


def draw_dots(
    draw,
    done: int,
    total: int,
    *,
    x: int,
    y: int,
    size: int = 26,
    gap: int = 14,
    colour=None,
) -> int:
    """`done` of `total` as filled dots — a count you can read without reading.

    Returns the x it ended at.
    """
    colour = colour or ce.GREEN
    for i in range(int(total)):
        cx = x + i * (size + gap)
        if i < int(done):
            draw.ellipse([cx, y, cx + size, y + size], fill=colour)
        else:
            draw.ellipse([cx, y, cx + size, y + size], outline=(40, 56, 44), width=3)
    return x + int(total) * (size + gap)


def draw_grade_badge(draw, letter: str, *, x: int, y: int, size: int = 118) -> None:
    """The day's letter grade, in a ring whose colour is the grade's own band."""
    bands = {"A": ce.GREEN, "B": ce.GREEN, "C": ce.AMBER, "D": AMBER_DEEP, "F": AMBER_DEEP}
    colour = bands.get(str(letter or "")[:1].upper(), ce.MUTED)
    draw.ellipse([x, y, x + size, y + size], outline=colour, width=5)
    font = ce.font(ce.FONT_DISPLAY, int(size * 0.52))
    try:
        tw = draw.textlength(str(letter), font=font)
    except Exception:  # noqa: BLE001
        tw = size * 0.4
    draw.text((x + (size - tw) / 2, y + size * 0.20), str(letter), fill=colour, font=font)


def draw_rule(draw, *, x: int, y: int, w: int) -> int:
    draw.rectangle([x, y, x + w, y + 2], fill=ce.BORDER)
    return y + 2


def draw_kv_row(draw, label: str, value: str, *, x: int, y: int, label_size: int = 22, value_size: int = 30, colour=None) -> int:
    """A small labelled fact. The label is quiet; the value is not."""
    draw.text((x, y), str(label).upper(), fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, label_size))
    draw.text((x, y + label_size + 10), str(value), fill=colour or ce.TEXT, font=ce.font(ce.FONT_MONO, value_size))
    return y + label_size + value_size + 24


def grade_colour(letter: str | None):
    return {"A": ce.GREEN, "B": ce.GREEN, "C": ce.AMBER, "D": AMBER_DEEP, "F": AMBER_DEEP}.get(str(letter or "")[:1].upper(), ce.MUTED)


def fit_text(draw, text: str, *, font_name: str, max_size: int, min_size: int, width: int, step: int = 4) -> Any:
    """The largest font at which `text` fits `width`. Measured, never estimated.

    The first card sized its hero from `len(text)` and "Foundation - Pull - 2 - 6" ran off
    the frame: character count is not width, and a proportional display face makes the gap
    worse.
    """
    for size in range(max_size, min_size - 1, -step):
        f = ce.font(font_name, size)
        try:
            if draw.textlength(text, font=f) <= width:
                return f
        except Exception:  # noqa: BLE001
            return ce.font(font_name, min_size)
    return ce.font(font_name, min_size)
