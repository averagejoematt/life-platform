"""recap_layouts.py — four ways to tell one day, as a serial (#3741 rework).

THE BRIEF THAT CHANGED THE ARTEFACT

> *"imagine you want these posts to get engagement, snowballed engagement… these captivate
> audiences who follow it day after day, my story and post, its a social media campaign, and
> so this data and story narrative is to be told through these daily posts."*

A recap answers "what happened yesterday". A campaign post has to earn the next one. The
difference shows up in three places, and every layout here honours all three:

1. **The serial marker on every card.** `DAY 8 · ATTEMPT #17`. Day one has zero followers,
   so each card must be legible to a stranger who sees exactly one of them, mid-scroll, with
   no context. It is also what makes card 40 readable to someone who never saw 1–39.
2. **The arc on every card.** baseline → now → goal, as a bar that visibly fills over months.
   A follower tracks the ARC; the day is just today's evidence of it.
3. **The bad days are content.** A C- with nutrition at 29 is a better post than a bland good
   day, because the account's whole promise is that the down weeks are shown. The north star
   says it outright — *proof, not promises · honesty is the moat* — and the campaign framing
   monetises that rather than straining against it.

THE SPINE

Sixteen loss episodes since 2012. Zero held. Losing has never been the problem; holding has
never once been solved. That is the hook, it is true, and it is the reason a stranger would
follow an attempt rather than scroll past another transformation. It is also why these cards
must never overstate: the jeopardy IS the draw, and a card that oversells forfeits it.

WHAT VARIES

The layout serves the day's narrative BEAT, not its largest number:

    scorecard   — the day, graded, with what earned it
    trajectory  — the arc: cumulative loss, the line, the distance left
    session     — the training, in detail
    reckoning   — the weekly close
    detail      — the SECOND card of every day: trained / ate / the rest, as one split
    dayzero     — the starting line, rendered once for the eve of genesis

WHEN THE DAY IS MISSING A PIECE

Ingestion is not a promise. Hevy may not have polled, MacroFactor lands a day late, the
journal may be empty. The owner's rule (2026-09-19): *"plans for each daily card when
certain ingestion wasn't available… rotating visuals that show graphs, insights, coach
points, basically filler."* So `FILLERS` is a small registry of blocks that are TRUE ON
ANY DAY — the arc so far, the last seven grades, the stakes, the coach's note, the road
ahead — and a card with an empty slot draws one of them instead, rotated by day number so
consecutive gaps do not show the same block twice. Every filler is labelled by what it IS
and carries a faint note naming what it stands in for ("no training logged"), because a
block that hides an absence is the #3527 class and a block that names it is just the card
the day earned.

One hero, one supporting structure, a footer of facts. Density comes from MARKS, never from
more blocks of text (Mara Chen's line, and she is right about the thumb-stop).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from web import card_engine as ce, recap_charts as ch

PORTRAIT = (1080, 1350)
M = 72  # margin
W_CONTENT = PORTRAIT[0] - 2 * M

ATTEMPT_NUMBER = 17  # cycle 17 — see CYCLE_GENESES; the serial marker's second half
TAGLINE = "proof, not promises"
#: The spine, as a footer line. Sixteen loss episodes since 2012, zero held (PROVEN_BLUEPRINT).
STAKES_LINE = "16 lost · 0 kept"

#: The small-text token. `card_engine.FAINT` is 3.9:1 on the card ground — fine for a
#: 1200×630 unfurl read on a desktop, below WCAG AA on a phone at feed scale. The panel
#: review (2026-09-19) measured it: a line may be faint OR small, never both. DIM is the
#: colour every line under ~28 px uses on these cards.
DIM = (112, 140, 124)
#: The miss band, deeper. Never red: red on a scorecard is the report card he got as a
#: kid, and the constraint is "amber is the honest miss, no failure-shaming".
AMBER_DEEP = (176, 116, 36)
#: Where the anchored bottom of every daily card sits: the goal bar, then the NEXT line.
#: Pinned to one y on every card type so the one cross-card rhythm element never wanders.
BAR_Y = 1084
NEXT_Y = 1168
#: Nothing above the anchored bottom may draw below this.
CONTENT_FLOOR = 1030


# ── shared chrome ─────────────────────────────────────────────────────────────
def _canvas():
    """A portrait canvas whose draw RECORDS every string, so `recap_qa` can audit the frame.

    The records ride on `img.info["recap_strings"]` — the image carries its own evidence
    to the gate, and a layout cannot opt out by forgetting to return something extra.
    """
    from web import recap_qa

    img, draw = ce.base_canvas(size=PORTRAIT, margin=M)
    rec = recap_qa.RecordingDraw(draw)
    img.info["recap_strings"] = rec.records
    return img, rec


def _serial(draw, facts, date_label: str) -> int:
    """`DAY 8` at display size, `· ATTEMPT #17` beside it, the date under. On every card.

    The day number is the only thing that changes card to card and the one thing a
    profile-grid visitor should be able to read at thumbnail: ninety tiles reading 1→90.
    """
    day = f"DAY {facts.day_n}" if facts.day_n is not None else "DAY —"
    df = ce.font(ce.FONT_DISPLAY, 60)
    draw.text((M, 84), day, fill=ce.TEXT, font=df)
    try:
        dw = draw.textlength(day, font=df)
    except Exception:  # noqa: BLE001
        dw = 200
    draw.text((M + dw + 22, 112), f"·  ATTEMPT #{ATTEMPT_NUMBER}", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 26))
    draw.text((M, 160), date_label.upper(), fill=DIM, font=ce.font(ce.FONT_MONO, 24))
    return 216


def _grade_corner(draw, facts) -> None:
    """The day's grade in a ring, same corner on every daily card — the recurring device.

    The one element the week-01 tile row proved: a wall of C, B-, B-, C- is "bad days
    included" made visual, and nobody else posts a report card. Absent when the day was
    not graded, and the absence is the card's statement about that day.
    """
    if not facts.grade_letter:
        return
    ch.draw_grade_badge(draw, facts.grade_letter, x=PORTRAIT[0] - M - 116, y=96, size=116)
    draw.text((PORTRAIT[0] - M, 224), "TODAY'S GRADE", fill=DIM, font=ce.font(ce.FONT_MONO, 18), anchor="ra")


def _milestone(draw, facts, *, y: int) -> int:
    """An amber stripe under the serial when the day crossed a line worth marking."""
    m = getattr(facts, "milestone", None)
    if not m:
        return y
    draw.rectangle([M, y + 4, M + 6, y + 34], fill=ce.AMBER)
    draw.text((M + 22, y), f"MILESTONE  ·  {m.upper()}", fill=ce.AMBER, font=ce.font(ce.FONT_MONO_BOLD, 26))
    return y + 52


def next_line(facts) -> str | None:
    """The forward hook — tomorrow's day number and when the week closes. Platform facts only.

    Every seat on the panel asked for a reason to come back. The honest one the platform
    holds for certain is the calendar: the serial continues tomorrow and the week's
    reckoning lands on a known day. A planned session would be better and is a follow-up
    (the plan engine's routine is not yet readable from here).
    """
    n = facts.day_n
    if not n:
        return None
    to_close = 7 - (n % 7) if n % 7 else 7
    week = n // 7 + 1
    close = "closes tomorrow" if to_close == 1 else f"closes in {to_close} days"
    return f"Day {n + 1} tomorrow  ·  week {week} {close}"


def _fact_rows_above_bar(draw, rows: list[tuple], *, y_min: int) -> None:
    """Fact rows sitting ON the anchored bar, drawn bottom-up, in the order given.

    (label, value, colour, size) tuples. The block hugs the bar so the card composes as
    two zones — the story above, the facts and the arc below — instead of leaving the
    middle third dead on a sparse day. Rows that would climb above `y_min` are dropped
    from the END of the list (the least important is last).
    """
    y = BAR_Y - 56
    kept = []
    for row in rows:
        if y - 44 < y_min:
            break
        kept.append(row)
        y -= 44
    for label, value, colour, size in kept:
        _fact_row(draw, label, value, y=y, colour=colour, size=size)
        y += 44


def _bottom(draw, facts, *, frac: float | None = None) -> None:
    """The anchored bottom of every daily card: the goal bar at BAR_Y, the NEXT line, the footer.

    The panel's first finding was the same on every card: content stops at ~y 1170 on a
    1350 canvas and the bottom third is dead. Anchoring the arc and the hook to the
    bottom edge composes to the full height whatever the day held above.
    """
    f = facts.pct_to_goal if frac is None else frac
    if f is not None and facts.baseline_weight_lb is not None and facts.goal_weight_lb is not None:
        _goal_bar_at(draw, f, facts.baseline_weight_lb, facts.goal_weight_lb, y=BAR_Y, facts=facts)
    nxt = next_line(facts)
    if nxt:
        draw.text((M, NEXT_Y), "NEXT", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 22))
        draw.text((M + 110, NEXT_Y - 4), nxt, fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 27))
    _footer(draw)


def _goal_bar(draw, facts, *, y: int) -> int:
    """baseline → now → goal. The arc, on every card, because the arc is the story."""
    frac = facts.pct_to_goal
    if frac is None:
        return y
    return _goal_bar_at(draw, frac, facts.baseline_weight_lb, facts.goal_weight_lb, y=y, facts=facts)


def _goal_bar_at(draw, frac: float, baseline: float, goal: float, *, y: int, facts=None) -> int:
    ch.draw_progress(draw, frac, x=M, y=y, w=W_CONTENT, h=16)
    y += 30
    left = f"{baseline:.0f} lb  day one"
    right = f"goal  {goal:.0f} lb"
    f = ce.font(ce.FONT_MONO, 22)
    draw.text((M, y), left, fill=DIM, font=f)
    draw.text((M + W_CONTENT, y), right, fill=DIM, font=f, anchor="ra")
    # "0.0% of the way" claims a measurement that has not happened. Until the arc has
    # moved, the honest centre label is the distance — and when today's number is not
    # today's, it says when it was.
    if frac < 0.005:
        mid = f"{baseline - goal:.0f} lb to go"
    else:
        mid = f"{frac * 100:.1f}% of the way"
    if facts is not None and facts.weight_lb is not None and not getattr(facts, "weighed_today", True):
        last = getattr(facts, "last_weigh_label", None)
        mid += f"  ·  last weighed {last}" if last else "  ·  not weighed today"
    try:
        tw = draw.textlength(mid, font=f)
    except Exception:  # noqa: BLE001
        tw = 200
    draw.text((M + (W_CONTENT - tw) / 2, y), mid, fill=ce.MUTED, font=f)
    return y + 44


#: Where the footer band draws. `card_engine.draw_footer` is sized for a 1200×630 unfurl
#: (an 11 px face); at 1080×1350 read on a phone that is a hairline, so the portrait card
#: draws its own footer at its own scale, on the same baseline the QA floor knows about.
FOOTER_Y = 1296


def _footer(draw, right: str = "averagejoematt.com"):
    f = ce.font(ce.FONT_MONO, 20)
    draw.text((M, FOOTER_Y), f"{TAGLINE}  ·  {STAKES_LINE}", fill=DIM, font=f)
    draw.text((PORTRAIT[0] - M, FOOTER_Y), right, fill=DIM, font=f, anchor="ra")


#: Nothing draws below this — the footer band starts here.
FLOOR_Y = 1262


def _fact_row(draw, label: str, value: str, *, y: int, colour=None, size: int = 27, floor: int = FLOOR_Y) -> int:
    """A labelled fact on one line — the footer register, quiet and dense.

    Silently DROPS itself below the floor rather than overprinting the footer. A fact that
    does not fit is worth less than a card that looks broken, and the layouts feed these in
    priority order so what falls off is the least important line.
    """
    if y + 36 > floor:
        return y
    draw.text((M, y), label.upper(), fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 20))
    draw.text((M + 190, y - 3), value, fill=colour or ce.MUTED, font=ce.font(ce.FONT_MONO, size))
    return y + 44


def _vice_summary(facts) -> str | None:
    """Vice streaks as a COUNT. Never a name, on any public surface.

    The first render of this layout put "7d no alcohol" on the card. The blocked-category
    vocabulary did not catch it — and it was right not to, because that list is about one
    specific category. The rule that DOES cover it is the north star's privacy absolute:

        "Never name substances/vices (the channel-listed blocked categories, alcohol, etc.)"

    So the vocabulary is narrower than the rule, and a card that names any vice is one
    vocabulary gap away from a disclosure he cannot take back. The count carries the real
    signal — he is holding most of them — and carries no name at all. Structurally safe
    rather than safe-by-list.

    The blocked-category screen still runs over the assembled strings as the backstop; this
    is the layer that makes sure it never has anything to catch.
    """
    held = sum(1 for _n, d in facts.vice_streaks.items() if d and float(d) >= 1)
    # The scorer's tracked count, never len(): the dict holds only the streaks currently
    # alive, so "5 of 5" one day and "7 of 7" the next looked like moving goalposts.
    total = int(getattr(facts, "vices_total", None) or 0) or len(facts.vice_streaks)
    if not total:
        return None
    best = max((float(d) for d in facts.vice_streaks.values() if d), default=0)
    tail = f" · longest {int(best)}d" if best >= 2 else ""
    return f"{held} of {total} holding{tail}"


#: Where a coach line sits and how much room it gets. Two mono lines at the card's content
#: width; a third would push the fact footer off every layout that has one.
COACH_LINE_WRAP = 50
COACH_LINE_MAX_LINES = 2


def _coach_line(draw, facts, *, y: int, floor: int = FLOOR_Y) -> int:
    """The one sentence on the card a coach actually said. Absent when there is none.

    Returns `y` unchanged when there is no line, which is the whole absence contract: a
    day with no coach output draws no quote block, no empty rule and no "—" placeholder.
    A gap where a quote would be is a lie about the day being quiet; nothing there at all
    is just the card the day earned.

    Drops itself below FLOOR_Y for the same reason `_fact_row` does. The quote is the
    lowest-priority block on every layout that carries it — it is the colour, not the
    evidence — so if a dense day has pushed the card down this far, the numbers win.
    """
    if not getattr(facts, "coach_line", None) or y > floor - 110:
        return y
    lines = ce.wrap(facts.coach_line, width=COACH_LINE_WRAP, max_lines=COACH_LINE_MAX_LINES)
    if not lines:
        return y
    draw.rectangle([M, y, M + 3, y + 32 * len(lines) + 6], fill=ce.GREEN)
    for i, line in enumerate(lines):
        draw.text((M + 22, y + i * 32), line, fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 24))
    who = getattr(facts, "coach_label", None)
    y += 32 * len(lines) + 6
    if who:
        draw.text((M + 22, y), f"— {who}", fill=DIM, font=ce.font(ce.FONT_MONO, 20))
        y += 26
    return y + 16


def clean_title(text: str) -> str:
    """A Hevy title with the glyphs the card's fonts cannot draw removed.

    Day 5 of cycle 17 rendered `Morning workout □ · 4 sets` — the □ was a ☀️ the owner
    typed into the Hevy app, which neither Fraunces nor Plex Mono carries, so Pillow drew
    the notdef box. The design system says no emoji on any surface anyway; this is the
    layer that makes a title someone typed on their phone obey it. Symbols (So), modifier
    symbols (Sk), format characters like the variation selector (Cf), combining marks (Mn)
    and everything outside the BMP go; letters, digits and punctuation stay.
    """
    kept = [c for c in str(text or "") if ord(c) <= 0xFFFF and unicodedata.category(c) not in ("So", "Sk", "Cf", "Mn", "Cn")]
    return " ".join("".join(kept).split())


_PAREN = re.compile(r"\s*\([^)]*\)")


def short_exercise(name: str) -> str:
    """`Lat Pulldown (Cable)` → `Lat Pulldown`. The equipment tag buys nothing at phone scale."""
    return _PAREN.sub("", clean_title(name)).strip() or clean_title(name)


def _sets_word(n: int) -> str:
    return f"{n} set" if n == 1 else f"{n} sets"


def _session_line(w) -> str:
    """`22 sets · 16,710 lb moved · 2h 24m` — or, for a session that moved no load, the
    time. "0 lb moved" on a cardio day is a null drawn as a zero (ADR-104) and reads as
    nothing happened."""
    bits = [_sets_word(w.n_sets)]
    if w.volume_lbs and w.volume_lbs > 0:
        bits.append(f"{w.volume_lbs:,.0f} lb moved")
    mins = _fmt_minutes(getattr(w, "duration_min", None))
    if mins:
        bits.append(mins)
    return "  ·  ".join(bits)


def _session_label(title: str) -> str:
    title = clean_title(title)
    parts = [p.strip() for p in title.split(" - ")]
    if len(parts) >= 2 and parts[1]:
        return f"{parts[1]} day".title() if len(parts[1]) <= 12 else parts[1]
    return title or "Training"


_COMPONENT_NAMES = {
    "habits_mvp": "habits",
    "sleep_quality": "sleep",
    "movement": "movement",
    "nutrition": "nutrition",
    "recovery": "recovery",
    "hydration": "hydration",
    "journal": "journal",
}


def _grade_strip(draw, grades: list, *, y: int, h: int = 74, weekdays=None) -> int:
    """Up to seven letter grades in a row, each ringed in its own band's colour."""
    cell = W_CONTENT // max(len(grades), 1)
    for i, g in enumerate(grades):
        cx = M + i * cell
        colour = ch.grade_colour(g) if g else (30, 42, 34)
        draw.rounded_rectangle([cx, y, cx + cell - 12, y + h], radius=10, outline=colour, width=4)
        if g:
            gf = ce.font(ce.FONT_DISPLAY, int(h * 0.51))
            try:
                tw = draw.textlength(g, font=gf)
            except Exception:  # noqa: BLE001
                tw = 30
            draw.text((cx + (cell - 12 - tw) / 2, y + int(h * 0.16)), g, fill=colour, font=gf)
        if weekdays and i < len(weekdays):
            draw.text((cx + (cell - 12) / 2, y + h + 8), str(weekdays[i]).upper(), fill=DIM, font=ce.font(ce.FONT_MONO, 20), anchor="ma")
    return y + h + (36 if weekdays else 22)


def draw_stakes(draw, *, y: int) -> int:
    """The spine, stated plainly. The reason a stranger follows an attempt.

    From his own mined history (PROVEN_BLUEPRINT): sixteen loss episodes of 15 lb or more
    since 2012, and zero that held — "held" meaning he regained less than a third within
    six months. Losing has never been the problem. Holding has never once been solved.

    That is the most compelling true thing about this account and it belongs on a WEEKLY
    card, not a daily one: at a daily cadence it would read as self-flagellation, and at a
    weekly cadence it reads as what it is — the stake the experiment is played for.

    Deliberately flat in register. The jeopardy does the work; adjectives would cheapen it.
    """
    draw.rectangle([M, y, M + W_CONTENT, y + 2], fill=ce.BORDER)
    y += 34
    draw.text((M, y), "16", fill=ce.AMBER, font=ce.font(ce.FONT_DISPLAY, 78))
    draw.text((M + 118, y + 22), "times the weight came off since 2012", fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 27))
    y += 92
    draw.text((M, y), "0", fill=ce.AMBER, font=ce.font(ce.FONT_DISPLAY, 78))
    draw.text((M + 118, y + 22), "times it stayed off", fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 27))
    y += 100
    draw.text(
        (M, y),
        "attempt seventeen · instrumented · graded daily, bad days included",
        fill=DIM,
        font=ce.font(ce.FONT_MONO, 21),
    )
    return y + 44


# ── A. SCORECARD — the day, graded, with what earned it ───────────────────────
def scorecard(facts, *, date_label: str, weight_series=None, grade_series=None):
    img, draw = _canvas()
    y = _serial(draw, facts, date_label)
    _grade_corner(draw, facts)
    y = _milestone(draw, facts, y=y + 10)

    comps = [(_COMPONENT_NAMES.get(k, k), v) for k, v in facts.component_scores.items()]
    if facts.weight_lb is not None and getattr(facts, "weighed_today", True):
        # A weigh-in today: the number a follower actually tracks.
        hero = f"{facts.weight_lb:.1f}"
        hf = ce.font(ce.FONT_DISPLAY, 132)
        draw.text((M, y), hero, fill=ce.TEXT, font=hf)
        try:
            hw = draw.textlength(hero, font=hf)
        except Exception:  # noqa: BLE001
            hw = 320
        draw.text((M + hw + 18, y + 66), "lb", fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 38))
        y += 152
        if facts.total_lost_lb is not None and facts.total_lost_lb > 0:
            draw.text((M, y), f"−{facts.total_lost_lb:.1f} lb since day one", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 34))
            y += 56
    elif comps:
        # No weigh-in today. Three cards in a row headlining the same stale weight read as
        # "nothing happened" — and as if it were measured today. The day's weakest mark
        # is the hero instead: the C- with its cause exposed is the account's promise.
        worst = min(comps, key=lambda kv: kv[1])
        hf = ce.font(ce.FONT_DISPLAY, 110)
        draw.text((M, y), worst[0], fill=ce.TEXT, font=hf)
        y += 128
        draw.text((M, y), f"{worst[1]:.0f}/100  ·  the day's weakest mark", fill=ce.AMBER, font=ce.font(ce.FONT_MONO_BOLD, 30))
        y += 54
    else:
        draw.text((M, y), "the day, graded", fill=ce.TEXT, font=ce.font(ce.FONT_DISPLAY, 96))
        y += 130

    if comps:
        y += 28
        draw.text((M, y), "WHAT EARNED IT", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 22))
        y += 42
        y = ch.draw_component_bars(draw, comps, x=M, y=y, w=W_CONTENT - 60, label_w=230, row_h=44, bar_h=22)
    else:
        ctx = {"weight_series": weight_series or [], "grade_series": grade_series or []}
        for name in pick_fillers(facts, ctx, 1, exclude=("coach",)):
            y = draw_filler(draw, name, facts, ctx, y=y + 28, note="the day was not graded")

    y = _coach_line(draw, facts, y=y + 26, floor=CONTENT_FLOOR)

    rows = []
    if facts.workouts:
        w = facts.workouts[0]
        rows.append(("trained", f"{_session_label(w.title)} · {_session_line(w)}", None, 25))
    if facts.missed_tier0:
        rows.append(("not checked in", " · ".join(facts.missed_tier0[:2]), ce.AMBER, 25))
    vices = _vice_summary(facts)
    if vices:
        rows.append(("vice streaks", vices, None, 25))
    _fact_rows_above_bar(draw, rows, y_min=y + 10)

    _bottom(draw, facts)
    return img


# ── B. TRAJECTORY — the arc, and how far is left ──────────────────────────────
def trajectory(facts, *, date_label: str, weight_series=None, grade_series=None):
    img, draw = _canvas()
    y = _serial(draw, facts, date_label)
    _grade_corner(draw, facts)
    y = _milestone(draw, facts, y=y + 10)

    lost = facts.total_lost_lb
    if lost is not None and lost > 0:
        hero = f"−{lost:.1f}"
        hf = ce.font(ce.FONT_DISPLAY, 168)
        draw.text((M, y), hero, fill=ce.GREEN, font=hf)
        try:
            hw = draw.textlength(hero, font=hf)
        except Exception:  # noqa: BLE001
            hw = 360
        draw.text((M + hw + 20, y + 92), "lb", fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 42))
        y += 198
        draw.text((M, y), f"since day one  ·  {facts.weight_lb:.1f} lb today", fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 30))
        y += 62
    elif facts.weight_lb is not None:
        draw.text((M, y), f"{facts.weight_lb:.1f}", fill=ce.TEXT, font=ce.font(ce.FONT_DISPLAY, 150))
        y += 180

    # The line. Gaps stay gaps — a smooth descent through days that were never measured
    # would be the prettiest possible lie (Henning's line). The day ruler under the chart
    # DRAWS the rule: a filled tick is a weigh-in, a hollow one is a day without.
    series = [v for v in (weight_series or [])]
    n_meas = len([v for v in series if v is not None])
    if n_meas >= 2:
        y += 30
        ch.draw_sparkline(draw, series, x=M, y=y, w=W_CONTENT, h=140, colour=ce.GREEN, dot_r=8)
        y += 176
        ch.draw_day_ruler(draw, series, x=M, y=y, w=W_CONTENT)
        y += 34
        line = f"{n_meas} weigh-ins across {len(series)} days"
        if n_meas < len(series):
            line += "  ·  dots, not a line — the days between were not measured"
        for wrapped in ce.wrap(line, width=62, max_lines=2):
            draw.text((M, y), wrapped, fill=DIM, font=ce.font(ce.FONT_MONO, 22))
            y += 30
        y += 8
    elif series:
        y += 16
        n = len([v for v in series if v is not None])
        draw.text(
            (M, y), f"{n} weigh-in{'s' if n != 1 else ''} this cycle — not enough for a line yet", fill=DIM, font=ce.font(ce.FONT_MONO, 24)
        )
        y += 52

    y = _coach_line(draw, facts, y=y + 20, floor=CONTENT_FLOOR)

    rows = []
    if facts.lb_to_goal is not None:
        rows.append(("to goal", f"{facts.lb_to_goal:.0f} lb", None, 30))
    if facts.weekly_rate_lb is not None and not facts.rate_provisional:
        lo, hi = facts.rate_ci or (None, None)
        rate = f"{facts.weekly_rate_lb:+.1f} lb/wk"
        if lo is not None and hi is not None:
            rate += f"   CI {lo:+.1f} to {hi:+.1f}"
        # Named, because a reader will divide 130 by it: this is the platform's 28-day
        # regression rate, not the slope of the dots above.
        rows.append(("rate · 28d", rate, None, 25))
    _fact_rows_above_bar(draw, rows, y_min=y + 10)

    _bottom(draw, facts)
    return img


# ── C. SESSION — the training, in detail ──────────────────────────────────────
#: Lifts named on card 1. The full list is card 2's job; three is a story, eight is a receipt.
SESSION_TOP_LIFTS = 3


def session(facts, *, date_label: str):
    img, draw = _canvas()
    y = _serial(draw, facts, date_label)
    _grade_corner(draw, facts)
    y = _milestone(draw, facts, y=y + 10)

    if not facts.workouts:
        raise ValueError("session layout needs a workout")
    w = facts.workouts[0]

    # The load moved is the stopper; the split name is the label. Fraunces for the
    # number, the day beneath — unless the session moved no load, when the time is.
    if w.volume_lbs and w.volume_lbs > 0:
        hero = f"{w.volume_lbs:,.0f}"
        hf = ce.font(ce.FONT_DISPLAY, 150)
        draw.text((M, y), hero, fill=ce.TEXT, font=hf)
        try:
            hw = draw.textlength(hero, font=hf)
        except Exception:  # noqa: BLE001
            hw = 480
        draw.text((M + hw + 18, y + 80), "lb moved", fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 34))
        y += 176
    else:
        mins = _fmt_minutes(getattr(w, "duration_min", None)) or _sets_word(w.n_sets)
        draw.text((M, y), mins, fill=ce.TEXT, font=ce.font(ce.FONT_DISPLAY, 150))
        y += 176
    title = _session_label(w.title)
    draw.text((M, y), f"{title}  ·  {_sets_word(w.n_sets)}", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 32))
    y += 66

    detail = [d for d in getattr(w, "detail", []) if d.top_weight_lb]
    detail.sort(key=lambda d: -(d.top_weight_lb or 0))
    if detail:
        y += 10
        draw.text((M, y), "HEAVIEST", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 22))
        y += 44
        f_row = ce.font(ce.FONT_MONO, 27)
        for d in detail[:SESSION_TOP_LIFTS]:
            right = (
                f"{d.n_sets} × {d.reps}  ·  {d.top_weight_lb:,.0f} lb"
                if d.reps
                else f"{_sets_word(d.n_sets)}  ·  {d.top_weight_lb:,.0f} lb"
            )
            draw.text((M, y), short_exercise(d.name), fill=ce.MUTED, font=f_row)
            draw.text((M + W_CONTENT, y), right, fill=ce.TEXT, font=f_row, anchor="ra")
            y += 42
        rest = len(w.exercises) - min(len(detail), SESSION_TOP_LIFTS)
        if rest > 0:
            draw.text((M, y), f"+{rest} more on card 2", fill=DIM, font=ce.font(ce.FONT_MONO, 22))
            y += 40
    elif w.exercises:
        y += 10
        draw.text((M, y), "THE WORK", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 22))
        y += 44
        for name in w.exercises[:4]:
            draw.text((M, y), short_exercise(str(name)), fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 27))
            y += 42

    y = _coach_line(draw, facts, y=y + 22, floor=CONTENT_FLOOR)

    rows = []
    if facts.acwr is not None:
        # 1.29 "safe" against a 1.3 ceiling reads as spin. The band is the honest label.
        rows.append(("load", f"ACWR {facts.acwr:.2f} · range 0.8–1.3", None, 25))
    if facts.readiness is not None:
        rows.append(("readiness", f"{facts.readiness:.0f}/100", None, 26))
    _fact_rows_above_bar(draw, rows, y_min=y + 10)

    _bottom(draw, facts)
    return img


# ── D. RECKONING — the weekly close ───────────────────────────────────────────
def reckoning(
    facts, *, week_n: int, date_label: str, weight_series=None, grade_series=None, totals: dict[str, Any] | None = None, weekdays=None
):
    img, draw = _canvas()
    df = ce.font(ce.FONT_DISPLAY, 60)
    wk = f"WEEK {week_n}"
    draw.text((M, 84), wk, fill=ce.TEXT, font=df)
    try:
        dw = draw.textlength(wk, font=df)
    except Exception:  # noqa: BLE001
        dw = 240
    draw.text((M + dw + 22, 112), f"·  ATTEMPT #{ATTEMPT_NUMBER}", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 26))
    draw.text((M, 160), date_label.upper(), fill=DIM, font=ce.font(ce.FONT_MONO, 24))
    y = 230

    totals = totals or {}
    delta = totals.get("weight_delta")
    if delta is not None:
        colour = ce.GREEN if delta < 0 else ce.AMBER
        hero = f"{'−' if delta < 0 else '+'}{abs(delta):.1f}"
        hf = ce.font(ce.FONT_DISPLAY, 158)
        draw.text((M, y), hero, fill=colour, font=hf)
        try:
            hw = draw.textlength(hero, font=hf)
        except Exception:  # noqa: BLE001
            hw = 330
        draw.text((M + hw + 20, y + 86), "lb", fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 42))
        y += 188
        draw.text(
            (M, y),
            "this week, scale to scale" if delta < 0 else "up this week, scale to scale",
            fill=colour,
            font=ce.font(ce.FONT_MONO_BOLD, 32),
        )
        y += 60

    grades = [g for g in (grade_series or [])]
    if grades:
        y += 16
        draw.text((M, y), "THE WEEK, GRADED", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 22))
        y = _grade_strip(draw, grades, y=y + 44, weekdays=weekdays)

    # The stakes, compact: the weekly close is one of the three places they are spent.
    y += 14
    draw.rectangle([M, y, M + W_CONTENT, y + 2], fill=ce.BORDER)
    y = _filler_stakes(draw, facts, {}, y=y + 26)

    # The week's facts on ONE row, then the miss, then the quote — in that order, so the
    # miss (the content) never gives way to the quote (the colour).
    bits = []
    if totals.get("sessions") is not None:
        bits.append(f"{totals['sessions']:g} sessions")
    if totals.get("sets") is not None:
        bits.append(f"{totals['sets']:g} sets")
    if totals.get("habit_pct") is not None:
        bits.append(f"habits {totals['habit_pct']:g}%")
    if bits:
        y = _fact_row(draw, "the week", "  ·  ".join(bits), y=y, size=26, floor=CONTENT_FLOOR)
    if totals.get("misses"):
        y = _fact_row(draw, "biggest miss", str(totals["misses"]), y=y, colour=ce.AMBER, size=25, floor=CONTENT_FLOOR)
    _coach_line(draw, facts, y=y + 6, floor=CONTENT_FLOOR)

    _bottom(draw, facts)
    return img


# ── fillers — blocks that are true on any day ────────────────────────────────
def _filler_arc_ok(facts, ctx) -> bool:
    return len([v for v in ctx.get("weight_series") or [] if v is not None]) >= 2


def _filler_arc(draw, facts, ctx, *, y: int) -> int:
    series = ctx.get("weight_series") or []
    ch.draw_sparkline(draw, series, x=M, y=y, w=W_CONTENT, h=120, colour=ce.GREEN)
    y += 156
    n = len([v for v in series if v is not None])
    line = f"{n} weigh-ins across {len(series)} days"
    if facts.total_lost_lb is not None and facts.total_lost_lb > 0:
        line += f"  ·  {facts.total_lost_lb:.1f} lb down since day one"
    draw.text((M, y), line, fill=DIM, font=ce.font(ce.FONT_MONO, 22))
    return y + 36


def _filler_graded_ok(facts, ctx) -> bool:
    return len([g for g in ctx.get("grade_series") or [] if g]) >= 2


def _filler_graded(draw, facts, ctx, *, y: int) -> int:
    grades = [g for g in (ctx.get("grade_series") or [])][-7:]
    return _grade_strip(draw, grades, y=y, h=64)


def _filler_stakes(draw, facts, ctx, *, y: int) -> int:
    draw.text((M, y), "16", fill=ce.AMBER, font=ce.font(ce.FONT_DISPLAY, 60))
    draw.text((M + 96, y + 18), "times the weight came off since 2012", fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 24))
    y += 70
    draw.text((M, y), "0", fill=ce.AMBER, font=ce.font(ce.FONT_DISPLAY, 60))
    draw.text((M + 96, y + 18), "times it stayed off", fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 24))
    return y + 80


def _filler_coach_ok(facts, ctx) -> bool:
    return bool(getattr(facts, "coach_line", None))


def _filler_coach(draw, facts, ctx, *, y: int) -> int:
    lines = ce.wrap(facts.coach_line, width=46, max_lines=3)
    draw.rectangle([M, y, M + 3, y + 34 * len(lines) + 6], fill=ce.GREEN)
    for i, line in enumerate(lines):
        draw.text((M + 22, y + i * 34), line, fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 24))
    return y + 34 * len(lines) + 20


def _filler_road_ok(facts, ctx) -> bool:
    return facts.lb_to_goal is not None


def _filler_road(draw, facts, ctx, *, y: int) -> int:
    y = _fact_row(draw, "to goal", f"{facts.lb_to_goal:.0f} lb", y=y, size=30)
    if facts.weekly_rate_lb is not None and not facts.rate_provisional:
        lo, hi = facts.rate_ci or (None, None)
        rate = f"{facts.weekly_rate_lb:+.1f} lb/wk"
        if lo is not None and hi is not None:
            rate += f"   CI {lo:+.1f} to {hi:+.1f}"
        y = _fact_row(draw, "rate", rate, y=y, size=25)
    if facts.total_lost_lb is not None and facts.total_lost_lb > 0:
        y = _fact_row(draw, "so far", f"−{facts.total_lost_lb:.1f} lb", y=y, colour=ce.GREEN, size=27)
    return y


#: name → (label, can_draw(facts, ctx), draw(draw, facts, ctx, y) -> y). Ordered; the
#: rotation starts at `day_n % len` so two consecutive gaps lead with different blocks.
FILLERS: dict[str, tuple[str, Any, Any]] = {
    "arc": ("the arc so far", _filler_arc_ok, _filler_arc),
    "graded": ("the last days, graded", _filler_graded_ok, _filler_graded),
    "coach": ("coach's note", _filler_coach_ok, _filler_coach),
    "road": ("the road", _filler_road_ok, _filler_road),
    "stakes": ("the stakes", lambda facts, ctx: True, _filler_stakes),
}


def pick_fillers(facts, ctx: dict, n: int, *, exclude: tuple[str, ...] = ()) -> list[str]:
    """Up to `n` filler names that can draw today, rotated by day number. Deterministic."""
    # The stakes are rationed — Day 0, the reckonings, and the last resort here — so the
    # best line in the set is not spent as wallpaper. Everything else rotates.
    names = [n for n in FILLERS if n != "stakes"]
    start = (facts.day_n or 0) % len(names)
    order = names[start:] + names[:start] + ["stakes"]
    out: list[str] = []
    for name in order:
        if name in exclude or len(out) >= n:
            continue
        _label, ok, _draw = FILLERS[name]
        try:
            if ok(facts, ctx):
                out.append(name)
        except Exception:  # noqa: BLE001 — a filler that cannot decide is not a candidate
            continue
    return out


def draw_filler(draw, name: str, facts, ctx: dict, *, y: int, note: str | None = None) -> int:
    """One filler block with its header — and the absence it stands in for, named LOUDLY.

    The panel's honesty seat: the gap day is the campaign, not the failure. A visible
    "not logged" is the proof "bad days included" promises, so it is amber and at value
    size, not a faint aside that makes the card look broken.
    """
    label, _ok, fn = FILLERS[name]
    draw.text((M, y), label.upper(), fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 22))
    if note:
        draw.text((M + W_CONTENT, y - 2), note, fill=ce.AMBER, font=ce.font(ce.FONT_MONO_BOLD, 24), anchor="ra")
    return fn(draw, facts, ctx, y=y + 40)


# ── F. DAY ZERO — the starting line ───────────────────────────────────────────
def dayzero(facts, *, date_label: str):
    """The card for the eve of genesis: where attempt seventeen starts from.

    No day data is drawn — the day before Day 1 belongs to the previous cycle and its
    numbers are not this attempt's. What IS true on the eve: the stakes, the baseline
    weigh-in the cycle is anchored to, the goal, the distance, and what the platform
    will grade every day from here. Stakes first: 16 / 0 is the hook a stranger reads.
    """
    if facts.baseline_weight_lb is None or facts.goal_weight_lb is None:
        raise ValueError("dayzero layout needs the cycle's baseline and goal")
    img, draw = _canvas()
    y = _serial(draw, facts, date_label)

    y += 10
    draw.text((M, y), "16", fill=ce.AMBER, font=ce.font(ce.FONT_DISPLAY, 150))
    draw.text((M + 230, y + 52), "times the weight came off", fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 30))
    draw.text((M + 230, y + 94), "since 2012", fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 30))
    y += 176
    draw.text((M, y), "0", fill=ce.AMBER, font=ce.font(ce.FONT_DISPLAY, 150))
    draw.text((M + 230, y + 52), "times it stayed off", fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 30))
    y += 196

    draw.rectangle([M, y, M + W_CONTENT, y + 2], fill=ce.BORDER)
    y += 34
    hero = f"{facts.baseline_weight_lb:.1f}"
    hf = ce.font(ce.FONT_DISPLAY, 120)
    draw.text((M, y), hero, fill=ce.TEXT, font=hf)
    try:
        hw = draw.textlength(hero, font=hf)
    except Exception:  # noqa: BLE001
        hw = 300
    draw.text((M + hw + 18, y + 62), "lb  ·  the starting line", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 30))
    y += 144
    y = _fact_row(
        draw,
        "goal",
        f"{facts.goal_weight_lb:.0f} lb  ·  {facts.baseline_weight_lb - facts.goal_weight_lb:.0f} lb to lose",
        y=y,
        size=30,
        floor=CONTENT_FLOOR,
    )
    names = [v for k, v in _COMPONENT_NAMES.items() if k != "journal"]
    y += 8
    draw.text((M, y), "GRADED EVERY DAY ON", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 20))
    y += 34
    for line in ce.wrap(" · ".join(names), width=58, max_lines=2):
        draw.text((M, y), line, fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 24))
        y += 34
    draw.text((M, y + 6), "bad days included.", fill=ce.MUTED, font=ce.font(ce.FONT_MONO_BOLD, 26))

    _bottom(draw, facts, frac=0.0)
    return img


def dayzero_caption(facts) -> str:
    head = f"Day 0 · attempt #{ATTEMPT_NUMBER}"
    body = (
        f"The starting line: {facts.baseline_weight_lb:.1f} lb. Goal {facts.goal_weight_lb:.0f} lb, "
        f"{facts.baseline_weight_lb - facts.goal_weight_lb:.0f} lb to lose. "
        "Sixteen times the weight came off since 2012. Zero times it stayed off. "
        "This one is instrumented, public, and graded every day — bad days included."
    )
    return cap_caption(head + "\n" + body + "\n" + f"Day 1 tomorrow\n{SITE_LINE}\n{HASHTAGS}")


# ── E. DETAIL — the second card: trained / ate / the rest ─────────────────────
#: A real band draws only when the day has it; an empty slot takes a filler. Two blocks
#: make a card, one does not (#3741, the owner's brief: "a dual or three part split").
DETAIL_MIN_BANDS = 2
DETAIL_SLOTS = 3
#: Exercise rows the TRAINED band may list when all three slots share the frame.
DETAIL_EXERCISE_ROWS = {3: 4, 2: 8}
#: What a filler in each slot is standing in for — drawn on the filler's header line.
DETAIL_ABSENCE_NOTES = {"trained": "no training logged", "ate": "no food logged", "rest": "no sleep or habit data"}


def detail_bands(facts) -> list[str]:
    """Which of the three bands this day can honestly draw, in frame order."""
    bands: list[str] = []
    if facts.workouts or (facts.walk_miles is not None and facts.walk_miles >= 0.5):
        bands.append("trained")
    if facts.calories is not None or facts.protein_g is not None:
        bands.append("ate")
    if any(v is not None for v in (facts.sleep_hrs, facts.recovery_pct, facts.tier0_done, facts.steps, facts.water_oz)):
        bands.append("rest")
    return bands


def _band_header(draw, label: str, *, y: int, summary: str | None = None) -> int:
    """`TRAINED` left, the band's one number right — so the three-band rhythm reads at a glance."""
    draw.text((M, y), label.upper(), fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 22))
    if summary:
        draw.text((M + W_CONTENT, y - 2), summary, fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 24), anchor="ra")
    return y + 40


def _fmt_minutes(mins: int | None) -> str | None:
    if not mins:
        return None
    return f"{mins // 60}h {mins % 60:02d}m" if mins >= 60 else f"{mins}m"


def _band_trained(draw, facts, *, y: int, rows: int) -> int:
    w = facts.workouts[0] if facts.workouts else None
    summary = _sets_word(w.n_sets) if w else (f"{facts.walk_miles:.1f} mi walked" if facts.walk_miles else None)
    y = _band_header(draw, "trained", y=y, summary=summary)
    if w:
        title = _session_label(w.title)
        f = ch.fit_text(draw, title, font_name=ce.FONT_DISPLAY, max_size=72, min_size=40, width=W_CONTENT)
        draw.text((M, y), title, fill=ce.TEXT, font=f)
        y += 86
        draw.text((M, y), _session_line(w), fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 26))
        y += 46
        shown = w.detail[:rows]
        f_name = ce.font(ce.FONT_MONO, 26)
        for ex in shown:
            if y > FLOOR_Y - 40:
                break
            name = short_exercise(ex.name)
            right = f"{ex.n_sets} × {ex.reps}" if ex.reps else _sets_word(ex.n_sets)
            if ex.top_weight_lb:
                right += f"  ·  {ex.top_weight_lb:,.0f} lb"
            try:
                rw = draw.textlength(right, font=f_name)
            except Exception:  # noqa: BLE001
                rw = 220
            name_w = W_CONTENT - rw - 30
            try:
                while draw.textlength(name, font=f_name) > name_w and len(name) > 6:
                    name = name[:-2].rstrip() + "…"
            except Exception:  # noqa: BLE001
                pass
            draw.text((M, y), name, fill=ce.MUTED, font=f_name)
            draw.text((M + W_CONTENT, y), right, fill=ce.TEXT, font=f_name, anchor="ra")
            y += 38
        if len(w.detail) > len(shown):
            draw.text((M, y), f"+{len(w.detail) - len(shown)} more", fill=DIM, font=ce.font(ce.FONT_MONO, 22))
            y += 36
    if facts.walk_miles is not None and facts.walk_miles >= 0.5:
        draw.text((M, y), f"walked {facts.walk_miles:.1f} mi", fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 26))
        y += 38
    return y


def _band_ate(draw, facts, *, y: int) -> int:
    y = _band_header(draw, "ate", y=y, summary=f"{facts.calories:,.0f} kcal" if facts.calories is not None else None)
    if facts.calories is not None:
        hero = f"{facts.calories:,.0f}"
        hf = ce.font(ce.FONT_DISPLAY, 72)
        draw.text((M, y), hero, fill=ce.TEXT, font=hf)
        try:
            hw = draw.textlength(hero, font=hf)
        except Exception:  # noqa: BLE001
            hw = 200
        tail = "kcal" + (f"  ·  target {facts.cal_target:,.0f}" if facts.cal_target else "")
        over = facts.cal_target is not None and float(facts.calories) > float(facts.cal_target)
        draw.text((M + hw + 16, y + 36), tail, fill=ce.AMBER if over else ce.MUTED, font=ce.font(ce.FONT_MONO, 26))
        y += 92
    # The macro row: four quiet columns. Protein carries its target because protein is the
    # one macro the protocol sets a floor on; the others are what they were.
    cols = [
        ("protein", f"{facts.protein_g:.0f} g" if facts.protein_g is not None else None),
        ("carbs", f"{facts.carbs_g:.0f} g" if facts.carbs_g is not None else None),
        ("fat", f"{facts.fat_g:.0f} g" if facts.fat_g is not None else None),
        ("fiber", f"{facts.fiber_g:.0f} g" if facts.fiber_g is not None else None),
    ]
    cols = [(k, v) for k, v in cols if v]
    if cols:
        cw = W_CONTENT // 4
        for i, (label, value) in enumerate(cols):
            x = M + i * cw
            draw.text((x, y), label.upper(), fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 20))
            draw.text((x, y + 28), value, fill=ce.TEXT, font=ce.font(ce.FONT_MONO, 32))
        y += 76
    if facts.protein_g is not None and facts.protein_target_g:
        frac = float(facts.protein_g) / float(facts.protein_target_g)
        ch.draw_progress(draw, min(frac, 1.0), x=M, y=y, w=W_CONTENT, h=12, colour=ce.GREEN if frac >= 1 else ce.AMBER)
        y += 24
        draw.text(
            (M, y), f"protein {frac * 100:.0f}% of the {facts.protein_target_g:.0f} g target", fill=DIM, font=ce.font(ce.FONT_MONO, 20)
        )
        y += 34
    if facts.meals is not None:
        logged = f"{int(facts.meals)} meal{'s' if int(facts.meals) != 1 else ''}"
        if facts.snacks:
            logged += f" · {int(facts.snacks)} snack{'s' if int(facts.snacks) != 1 else ''}"
        draw.text((M, y), f"{logged} logged", fill=DIM, font=ce.font(ce.FONT_MONO, 20))
        y += 34
    return y


def _rest_tiles(facts) -> list[tuple[str, str, str | None]]:
    """(label, value, note) for the REST band, in priority order. Absent stays absent."""
    tiles: list[tuple[str, str, str | None]] = []
    if facts.sleep_hrs is not None:
        tiles.append(("sleep", f"{facts.sleep_hrs:.1f} h", f"score {facts.sleep_score:.0f}" if facts.sleep_score is not None else None))
    if facts.recovery_pct is not None:
        hrv = None
        if facts.hrv_ms is not None:
            base = getattr(facts, "hrv_30d", None)
            hrv = f"HRV {facts.hrv_ms:.0f} ms" + (f" · 30d {base:.0f}" if base else "")
        tiles.append(("recovery", f"{facts.recovery_pct:.0f}%", hrv))
    if facts.tier0_done is not None and facts.tier0_total:
        tiles.append(("habits", f"{int(facts.tier0_done)}/{int(facts.tier0_total)}", None))
    if facts.steps is not None:
        tiles.append(("steps", f"{facts.steps:,.0f}", None))
    if facts.water_oz is not None:
        tiles.append(("water", f"{facts.water_oz:.0f} oz", f"of {facts.water_target_oz:.0f}" if facts.water_target_oz else None))
    if facts.readiness is not None:
        tiles.append(("readiness", f"{facts.readiness:.0f}/100", None))
    return tiles[:6]


def _band_rest(draw, facts, *, y: int) -> int:
    summary = f"slept {facts.sleep_hrs:.1f} h" if facts.sleep_hrs is not None else None
    y = _band_header(draw, "the rest", y=y, summary=summary)
    tiles = _rest_tiles(facts)
    if tiles:
        cw = W_CONTENT // 3
        row_h = 104
        # A second row of tiles only if it clears the floor; the first three are the ones
        # that matter (sleep, recovery, habits) and the rest go to the caption.
        if y + 2 * row_h > FLOOR_Y - 20:
            tiles = tiles[:3]
        for i, (label, value, note) in enumerate(tiles):
            x = M + (i % 3) * cw
            ty = y + (i // 3) * row_h
            draw.text((x, ty), label.upper(), fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 20))
            draw.text((x, ty + 28), value, fill=ce.TEXT, font=ce.font(ce.FONT_MONO, 34))
            if note:
                # Under the value, at a size a phone can read — never a 13 px aside.
                draw.text((x, ty + 72), note, fill=DIM, font=ce.font(ce.FONT_MONO, 22))
        y += row_h * ((len(tiles) + 2) // 3) + 4
    if facts.missed_tier0:
        y = _fact_row(draw, "not checked in", " · ".join(facts.missed_tier0[:2]), y=y, colour=ce.AMBER, size=24)
    if facts.journaled:
        y = _fact_row(draw, "journal", "wrote it down", y=y, size=24)
    return y


def detail_plan(facts, weight_series=None, grade_series=None) -> list[tuple[str, str | None]]:
    """The slots card 2 will draw: (block, absence_note). Real bands first, fillers after.

    A day with all three bands has no fillers. A day missing one takes one filler in its
    place, labelled with what it replaces. A day with nothing real still gets a card if
    two fillers can draw — the arc and the stakes are true on a day nothing was logged —
    and the notes on both say so.
    """
    real = detail_bands(facts)
    plan: list[tuple[str, str | None]] = [(b, None) for b in real]
    missing = [b for b in ("trained", "ate", "rest") if b not in real]
    ctx = {"weight_series": weight_series or [], "grade_series": grade_series or []}
    for name, slot in zip(pick_fillers(facts, ctx, DETAIL_SLOTS - len(real)), missing):
        plan.append((name, DETAIL_ABSENCE_NOTES[slot]))
    return plan


def detail(facts, *, date_label: str, weight_series=None, grade_series=None):
    """The second card of the day. Raises when fewer than two blocks can be drawn."""
    plan = detail_plan(facts, weight_series, grade_series)
    if len(plan) < DETAIL_MIN_BANDS:
        raise ValueError(f"detail layout needs {DETAIL_MIN_BANDS} blocks; this day has {plan}")
    ctx = {"weight_series": weight_series or [], "grade_series": grade_series or []}
    img, draw = _canvas()
    y = _serial(draw, facts, date_label)
    draw.text((M + W_CONTENT, 148), "2 OF 2  ·  THE DETAIL", fill=DIM, font=ce.font(ce.FONT_MONO, 22), anchor="ra")
    rows = DETAIL_EXERCISE_ROWS.get(len(plan), 5)
    for i, (block, note) in enumerate(plan):
        if i:
            draw.rectangle([M, y, M + W_CONTENT, y + 2], fill=ce.BORDER)
            y += 30
        if block == "trained":
            y = _band_trained(draw, facts, y=y, rows=rows)
        elif block == "ate":
            y = _band_ate(draw, facts, y=y)
        elif block == "rest":
            y = _band_rest(draw, facts, y=y)
        else:
            y = draw_filler(draw, block, facts, ctx, y=y, note=note)
        y += 14
    _footer(draw)
    return img


def detail_caption(facts, *, day_label: str) -> str:
    """The words beside the second card — the same rule as the first: assembled, never generated."""
    head = " · ".join(x for x in (day_label, f"attempt #{ATTEMPT_NUMBER}", "the detail") if x)
    bits: list[str] = []
    if facts.workouts:
        w = facts.workouts[0]
        bit = f"Trained: {_session_label(w.title)}, {w.n_sets} sets"
        if w.volume_lbs and w.volume_lbs > 0:
            bit += f", {w.volume_lbs:,.0f} lb moved"
        bits.append(bit + ".")
    if facts.calories is not None:
        bit = f"Ate: {facts.calories:,.0f} kcal"
        if facts.protein_g is not None:
            bit += f", {facts.protein_g:.0f} g protein"
        bits.append(bit + ".")
    rest: list[str] = []
    if facts.sleep_hrs is not None:
        rest.append(f"slept {facts.sleep_hrs:.1f} h")
    if facts.recovery_pct is not None:
        rest.append(f"recovery {facts.recovery_pct:.0f}%")
    if facts.tier0_done is not None and facts.tier0_total:
        rest.append(f"habits {int(facts.tier0_done)}/{int(facts.tier0_total)}")
    if rest:
        bits.append((", ".join(rest) + ".").capitalize())
    return cap_caption((head + "\n" + " ".join(bits) + "\n" + _caption_tail(facts)).strip())


LAYOUTS = {
    "scorecard": scorecard,
    "trajectory": trajectory,
    "session": session,
    "reckoning": reckoning,
    "detail": detail,
    "dayzero": dayzero,
}


# ── beat selection ────────────────────────────────────────────────────────────
#: Sets that make a day a training STORY rather than a training fact.
HEAVY_SETS = 20


#: Trajectory may not fire three days running unless the arc moved this much since the
#: last trajectory card. With sparse weigh-ins rule 1 was rare; with daily weigh-ins —
#: the behaviour we want — it would make every card `−N.N lb` and the other beats would
#: never fire again (the PM seat's finding). Variety is a property, not a coincidence.
TRAJECTORY_REPEAT_LB = 1.0


def pick_beat(facts, trailing=None, recent_beats=None) -> tuple[str, str]:
    """Which layout this day's story wants, and why. Returns (layout, reason).

    Ava Moreau's correction, and the reason the first cards felt interchangeable: the
    original picker chose by DATA MAGNITUDE — largest number wins — which is not how a
    serial works. A campaign picks a BEAT. The same 27-set session is a different post on
    the day he also weighed in than on the day he did not.

    Deterministic and ordered, so the same day always produces the same beat and "a
    different card every day" is a property rather than a hope.
    """
    trailing = trailing or []
    recent = list(recent_beats or [])  # [(date, beat)] for the days before this one, oldest first

    # 0. A milestone picks the beat that carries it.
    m = getattr(facts, "milestone", None)
    if m and facts.workouts and "moved" in m:
        return "session", f"milestone — {m}"
    if m and facts.weight_lb is not None and "lb" in m:
        return "trajectory", f"milestone — {m}"

    # 1. A new weigh-in is the arc moving. It is the rarest event and the most postable —
    #    unless it has been the beat two days running and the arc barely moved since.
    prev = next((d.weight_lb for d in reversed(trailing) if d.date != facts.date and d.weight_lb is not None), None)
    if facts.weight_lb is not None and prev is not None and abs(facts.weight_lb - prev) > 0.05:
        last_two = [b for _d, b in recent[-2:]]
        if last_two == ["trajectory", "trajectory"]:
            last_traj_date = next((d for d, b in reversed(recent) if b == "trajectory"), None)
            at_last = next((d.weight_lb for d in trailing if d.date == last_traj_date and d.weight_lb is not None), None)
            if at_last is None or abs(facts.weight_lb - at_last) < TRAJECTORY_REPEAT_LB:
                pass  # fall through — the arc is not a new story yet
            else:
                return "trajectory", "new weigh-in — the arc moved"
        else:
            return "trajectory", "new weigh-in — the arc moved"

    # 2. A heavy session is its own story, with the movements named.
    sets = sum(w.n_working_sets or w.n_sets for w in facts.workouts)
    if sets >= HEAVY_SETS:
        return "session", f"{sets} working sets — a session worth showing"

    # 3. Everything else is the day, graded. The default is not a fallback: a C- with its
    #    components exposed is the format that carries the account's whole promise.
    return "scorecard", "the day, graded"


#: Item classes that NO layout draws by name. `item_labels()` is the complete risk-surface
#: registry — every name that could ever reach a card converges there, deliberately — but
#: the whole-card text screen must run over what will ACTUALLY be drawn. Vice streaks are
#: rendered as a count and never as a name (see `_vice_summary`), so including their names
#: in the text screen held every single card on a blocked-category streak the card was
#: never going to print. The per-ITEM screen still sees them, via `items=item_labels()`.
NEVER_DRAWN_BY_NAME = {"streaks"}


def gate_strings(facts, caption: str = "", extra: tuple[str, ...] = ()) -> list[str]:
    """Everything a layout could put on a card that did not come from a number.

    Screens the INPUT rather than the drawn output. Layouts render names (workout titles,
    exercises, missed habits), formatted numbers, and fixed labels — the numbers and labels
    are ours, so the names are the whole risk surface, and `item_labels()` is where every
    name already converges for exactly that reason. Screening inputs also cannot drift the
    way a parallel list of "strings this layout draws" would the first time a layout changed.

    The one exclusion is `NEVER_DRAWN_BY_NAME`, and it is load-bearing in both directions:
    without it the gate held all seven cards over a name none of them print; and if a future
    layout ever DOES print a vice name, it must remove that class from this set, which is a
    deliberate, reviewable act rather than an accident.
    """
    out = [label for template, label in facts.item_labels() if template not in NEVER_DRAWN_BY_NAME]
    # The coach line is drawn verbatim, so it is screened verbatim — by the deterministic
    # text layer here AND by the semantic step the same change added (`recap_gate` step 4,
    # fed separately from `facts.free_text()`). Both, not either: the vocabulary layer is
    # what catches a blocked term inside a sentence, and the semantic layer is what exists
    # for everything a vocabulary cannot enumerate.
    out.extend(facts.free_text())
    if caption:
        out.append(caption)
    # The second card's caption is screened in the SAME call as the first — one gate
    # verdict per day, never a second card that slipped through on its own.
    out.extend(x for x in extra if x)
    return out


def render_beat(layout: str, facts, *, date_label: str, weight_series=None, grade_series=None, week_n=None, totals=None):
    """Render one beat. Raises if the layout cannot be honestly drawn for this day."""
    if layout == "trajectory":
        return trajectory(facts, date_label=date_label, weight_series=weight_series, grade_series=grade_series)
    if layout == "session":
        return session(facts, date_label=date_label)
    if layout == "detail":
        return detail(facts, date_label=date_label, weight_series=weight_series, grade_series=grade_series)
    if layout == "dayzero":
        return dayzero(facts, date_label=date_label)
    if layout == "reckoning":
        return reckoning(
            facts, week_n=week_n or 1, date_label=date_label, weight_series=weight_series, grade_series=grade_series, totals=totals
        )
    return scorecard(facts, date_label=date_label, weight_series=weight_series, grade_series=grade_series)


#: Instagram takes far more than this; the limit is editorial, not technical. A caption
#: that has to be expanded to be read is a caption most of the feed never reads (#3749).
CAPTION_MAX_CHARS = 480
#: Fixed, never generated. The account's own tags.
HASHTAGS = "#attempt17 #proofnotpromises #quantifiedself #weightlossjourney #buildinpublic"
SITE_LINE = "averagejoematt.com"


def cap_caption(text: str) -> str:
    """Hard-cap a caption at `CAPTION_MAX_CHARS`, on a word boundary.

    The belt to `caption_for_beat`'s brace. That function drops the quote when it would
    not fit, which handles the only variable-length part it adds — but the stats bits are
    assembled from names (`Missed: …`) that have no length bound of their own, so the cap
    is enforced here over the finished string rather than assumed upstream.
    """
    if len(text) <= CAPTION_MAX_CHARS:
        return text
    clipped = text[: CAPTION_MAX_CHARS - 1].rsplit(" ", 1)[0].rstrip(' ,;:—-"')
    return (clipped + "…") if clipped else text[: CAPTION_MAX_CHARS - 1] + "…"


def caption_for_beat(layout: str, facts, *, day_label: str, date_label: str) -> str:
    """The words beside the image — assembled from the card's own facts, never generated.

    A caption is published in the same breath as the image and is screened with it, so it
    says what the card says. The hook line differs by beat because a serial that opens the
    same way every day teaches people to scroll past it.

    "Never generated" survived #3749 intact, but the reasoning under it widened. Until the
    coach line, the claim was trivially true because every part of a caption was a number
    this module formatted itself. Now one part is a sentence a language model wrote — and
    it is still not generated HERE, because this function selects it rather than asking
    for it. That distinction is the only thing standing between a caption and a fresh AI
    flourish per card, which is exactly what #3749 was filed to prevent, so it is worth
    stating rather than leaving as an inference from the code.
    """
    head = " · ".join(x for x in (day_label, f"attempt #{ATTEMPT_NUMBER}") if x)
    bits: list[str] = []
    if layout == "trajectory" and facts.total_lost_lb:
        bits.append(f"{facts.total_lost_lb:.1f} lb down since day one. {facts.weight_lb:.1f} lb today.")
        if facts.lb_to_goal:
            bits.append(f"{facts.lb_to_goal:.0f} lb to go.")
    elif layout == "session" and facts.workouts:
        w = facts.workouts[0]
        bits.append(f"{_session_label(w.title)}. {w.n_sets} working sets, {w.volume_lbs:,.0f} lb moved.")
    else:
        if facts.grade_letter:
            bits.append(f"Today graded {facts.grade_letter}.")
        worst = min(facts.component_scores.items(), key=lambda kv: kv[1], default=None)
        if worst:
            bits.append(f"Worst component: {_COMPONENT_NAMES.get(worst[0], worst[0])} at {worst[1]:.0f}/100.")
    if facts.missed_tier0:
        bits.append("Not checked in: " + ", ".join(facts.missed_tier0[:2]) + ".")
    body = " ".join(bits)
    tail = _caption_tail(facts)
    # The coach line is the first thing dropped. The stats are the card's claim; the
    # quote is its voice, and a caption that truncates mid-number reads as broken in a
    # way a caption that simply has no quote does not (#3749).
    line = getattr(facts, "coach_line", None)
    if line:
        who = getattr(facts, "coach_label", None)
        candidate = f'{body}\n"{line}"' + (f" — {who}" if who else "")
        if len(head) + 1 + len(candidate) + 1 + len(tail) <= CAPTION_MAX_CHARS:
            body = candidate
    return cap_caption((head + "\n" + body + "\n" + tail).strip())


def _caption_tail(facts) -> str:
    """NEXT line, the site, the tags — the same close on every caption, all platform facts."""
    parts = []
    nxt = next_line(facts)
    if nxt:
        parts.append(nxt.replace("  ·  ", " · "))
    parts.append(SITE_LINE)
    parts.append(HASHTAGS)
    return "\n".join(parts)
