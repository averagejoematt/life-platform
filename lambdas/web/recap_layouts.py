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

import unicodedata
from typing import Any

from web import card_engine as ce, recap_charts as ch

PORTRAIT = (1080, 1350)
M = 72  # margin
W_CONTENT = PORTRAIT[0] - 2 * M

ATTEMPT_NUMBER = 17  # cycle 17 — see CYCLE_GENESES; the serial marker's second half
TAGLINE = "proof, not promises"


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
    """`DAY 8 · ATTEMPT #17` over a quiet second line. On every card, without exception."""
    day = f"DAY {facts.day_n}" if facts.day_n is not None else "DAY —"
    draw.text((M, 104), f"{day}  ·  ATTEMPT #{ATTEMPT_NUMBER}", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 30))
    draw.text((M, 148), date_label.upper(), fill=ce.FAINT, font=ce.font(ce.FONT_MONO, 22))
    return 210


def _goal_bar(draw, facts, *, y: int) -> int:
    """baseline → now → goal. The arc, on every card, because the arc is the story."""
    frac = facts.pct_to_goal
    if frac is None:
        return y
    return _goal_bar_at(draw, frac, facts.baseline_weight_lb, facts.goal_weight_lb, y=y)


def _goal_bar_at(draw, frac: float, baseline: float, goal: float, *, y: int) -> int:
    ch.draw_progress(draw, frac, x=M, y=y, w=W_CONTENT, h=16)
    y += 30
    left = f"{baseline:.0f} lb  day one"
    right = f"goal  {goal:.0f} lb"
    draw.text((M, y), left, fill=ce.FAINT, font=ce.font(ce.FONT_MONO, 21))
    draw.text((M + W_CONTENT, y), right, fill=ce.FAINT, font=ce.font(ce.FONT_MONO, 21), anchor="ra")
    mid = f"{frac * 100:.1f}% of the way"
    try:
        tw = draw.textlength(mid, font=ce.font(ce.FONT_MONO, 21))
    except Exception:  # noqa: BLE001
        tw = 200
    draw.text((M + (W_CONTENT - tw) / 2, y), mid, fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 21))
    return y + 44


#: Where the footer band draws. `card_engine.draw_footer` is sized for a 1200×630 unfurl
#: (an 11 px face); at 1080×1350 read on a phone that is a hairline, so the portrait card
#: draws its own footer at its own scale, on the same baseline the QA floor knows about.
FOOTER_Y = 1296


def _footer(draw, right: str = "averagejoematt.com"):
    f = ce.font(ce.FONT_MONO, 20)
    draw.text((M, FOOTER_Y), TAGLINE, fill=ce.FAINT, font=f)
    draw.text((PORTRAIT[0] - M, FOOTER_Y), right, fill=ce.FAINT, font=f, anchor="ra")


#: Nothing draws below this — the footer band starts here.
FLOOR_Y = 1262


def _fact_row(draw, label: str, value: str, *, y: int, colour=None, size: int = 27) -> int:
    """A labelled fact on one line — the footer register, quiet and dense.

    Silently DROPS itself below the floor rather than overprinting the footer. A fact that
    does not fit is worth less than a card that looks broken, and the layouts feed these in
    priority order so what falls off is the least important line.
    """
    if y > FLOOR_Y:
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
    total = len(facts.vice_streaks)
    if not total:
        return None
    best = max((float(d) for d in facts.vice_streaks.values() if d), default=0)
    tail = f" · longest {int(best)}d" if best >= 2 else ""
    return f"{held} of {total} holding{tail}"


#: Where a coach line sits and how much room it gets. Two mono lines at the card's content
#: width; a third would push the fact footer off every layout that has one.
COACH_LINE_WRAP = 54
COACH_LINE_MAX_LINES = 2


def _coach_line(draw, facts, *, y: int) -> int:
    """The one sentence on the card a coach actually said. Absent when there is none.

    Returns `y` unchanged when there is no line, which is the whole absence contract: a
    day with no coach output draws no quote block, no empty rule and no "—" placeholder.
    A gap where a quote would be is a lie about the day being quiet; nothing there at all
    is just the card the day earned.

    Drops itself below FLOOR_Y for the same reason `_fact_row` does. The quote is the
    lowest-priority block on every layout that carries it — it is the colour, not the
    evidence — so if a dense day has pushed the card down this far, the numbers win.
    """
    if not getattr(facts, "coach_line", None) or y > FLOOR_Y - 96:
        return y
    lines = ce.wrap(facts.coach_line, width=COACH_LINE_WRAP, max_lines=COACH_LINE_MAX_LINES)
    if not lines:
        return y
    draw.rectangle([M, y, M + 3, y + 30 * len(lines) + 6], fill=ce.GREEN)
    for i, line in enumerate(lines):
        draw.text((M + 22, y + i * 30), line, fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 22))
    return y + 30 * len(lines) + 20


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


def _grade_strip(draw, grades: list, *, y: int, h: int = 74) -> int:
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
    return y + h + 22


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
        fill=ce.FAINT,
        font=ce.font(ce.FONT_MONO, 21),
    )
    return y + 44


# ── A. SCORECARD — the day, graded, with what earned it ───────────────────────
def scorecard(facts, *, date_label: str, weight_series=None, grade_series=None):
    img, draw = _canvas()
    y = _serial(draw, facts, date_label)

    # Hero: the weight, and the only number a follower actually tracks.
    if facts.weight_lb is not None:
        hero = f"{facts.weight_lb:.1f}"
        hf = ce.font(ce.FONT_DISPLAY, 132)
        draw.text((M, y), hero, fill=ce.TEXT, font=hf)
        # Measured, not offset by a guess — "319.7" and "99.8" are not the same width.
        try:
            hw = draw.textlength(hero, font=hf)
        except Exception:  # noqa: BLE001
            hw = 320
        draw.text((M + hw + 18, y + 66), "lb", fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 38))
        y += 152
    if facts.total_lost_lb is not None and facts.total_lost_lb > 0:
        draw.text((M, y), f"−{facts.total_lost_lb:.1f} lb since day one", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 34))
        y += 56

    # The grade badge sits opposite the hero — the platform's own verdict, not a mood.
    if facts.grade_letter:
        ch.draw_grade_badge(draw, facts.grade_letter, x=PORTRAIT[0] - M - 130, y=225, size=130)
        draw.text((PORTRAIT[0] - M, 368), "TODAY'S GRADE", fill=ce.FAINT, font=ce.font(ce.FONT_MONO, 19), anchor="ra")

    y = _goal_bar(draw, facts, y=max(y + 24, 470))

    # What earned it — worst first, because that is the interesting half.
    comps = [(_COMPONENT_NAMES.get(k, k), v) for k, v in facts.component_scores.items()]
    if comps:
        y += 34
        draw.text((M, y), "WHAT EARNED IT", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 22))
        y += 42
        # 60 px short of the content width so the score column lands INSIDE the margin —
        # the render QA read six scores in the gutter on every scorecard until it did.
        y = ch.draw_component_bars(draw, comps, x=M, y=y, w=W_CONTENT - 60, label_w=230, row_h=48)
    else:
        # The compute cron did not score this day. The slot the components own is filled
        # by something true on any day — labelled as what it is, noting what it stands for.
        ctx = {"weight_series": weight_series or [], "grade_series": grade_series or []}
        for name in pick_fillers(facts, ctx, 1, exclude=("coach",)):
            y = draw_filler(draw, name, facts, ctx, y=y + 34, note="the day was not graded")

    y = _coach_line(draw, facts, y=y + 30)

    # The fact footer: today's specifics, named.
    y = max(y + 40, 1010)
    if facts.workouts:
        w = facts.workouts[0]
        y = _fact_row(draw, "trained", f"{_session_label(w.title)} · {w.n_sets} sets · {w.volume_lbs:,.0f} lb", y=y)
    if facts.missed_tier0:
        y = _fact_row(draw, "missed", " · ".join(facts.missed_tier0[:2]), y=y, colour=ce.AMBER, size=25)
    vices = _vice_summary(facts)
    if vices:
        y = _fact_row(draw, "vice streaks", vices, y=y, size=25)

    _footer(draw)
    return img


# ── B. TRAJECTORY — the arc, and how far is left ──────────────────────────────
def trajectory(facts, *, date_label: str, weight_series=None, grade_series=None):
    img, draw = _canvas()
    y = _serial(draw, facts, date_label)

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

    # The line. Gaps stay gaps — he has one weigh-in this week and a smooth descent through
    # a single measurement would be the prettiest possible lie (Henning's line).
    series = [v for v in (weight_series or [])]
    n_meas = len([v for v in series if v is not None])
    if n_meas >= 2:
        y += 46
        ch.draw_sparkline(draw, series, x=M, y=y, w=W_CONTENT, h=150, colour=ce.GREEN)
        y += 186
        draw.text((M, y), f"{n_meas} weigh-ins across {len(series)} days", fill=ce.FAINT, font=ce.font(ce.FONT_MONO, 20))
        y += 30
        if n_meas < 4:
            draw.text((M, y), "dots, not a line — the days between were not measured", fill=ce.FAINT, font=ce.font(ce.FONT_MONO, 20))
            y += 30
        y += 14
    elif series:
        y += 16
        n = len([v for v in series if v is not None])
        draw.text(
            (M, y),
            f"{n} weigh-in{'s' if n != 1 else ''} this cycle — not enough for a line yet",
            fill=ce.FAINT,
            font=ce.font(ce.FONT_MONO, 22),
        )
        y += 52

    y = _coach_line(draw, facts, y=y + 26)
    y = _goal_bar(draw, facts, y=max(y + 20, 880))

    y += 40
    if facts.lb_to_goal is not None:
        y = _fact_row(draw, "to goal", f"{facts.lb_to_goal:.0f} lb", y=y, size=30)
    if facts.weekly_rate_lb is not None and not facts.rate_provisional:
        lo, hi = facts.rate_ci or (None, None)
        rate = f"{facts.weekly_rate_lb:+.1f} lb/wk"
        if lo is not None and hi is not None:
            rate += f"   CI {lo:+.1f} to {hi:+.1f}"
        y = _fact_row(draw, "rate", rate, y=y, size=25)
    if facts.grade_letter:
        y = _fact_row(draw, "today", f"grade {facts.grade_letter}", y=y, colour=ch.grade_colour(facts.grade_letter), size=27)

    _footer(draw)
    return img


# ── C. SESSION — the training, in detail ──────────────────────────────────────
def session(facts, *, date_label: str):
    img, draw = _canvas()
    y = _serial(draw, facts, date_label)

    if not facts.workouts:
        raise ValueError("session layout needs a workout")
    w = facts.workouts[0]

    title = _session_label(w.title)
    f = ch.fit_text(draw, title, font_name=ce.FONT_DISPLAY, max_size=126, min_size=58, width=W_CONTENT)
    draw.text((M, y), title, fill=ce.TEXT, font=f)
    y += 158

    draw.text((M, y), f"{w.n_sets} working sets   ·   {w.volume_lbs:,.0f} lb moved", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 32))
    y += 66

    # The movements, named. "27 sets" is a number; the exercise list is a workout.
    if w.exercises:
        y += 14
        draw.text((M, y), "THE WORK", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 22))
        y += 44
        for name in w.exercises[:8]:
            draw.text((M, y), "—", fill=ce.FAINT, font=ce.font(ce.FONT_MONO, 26))
            draw.text((M + 40, y), str(name), fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 26))
            y += 42
        if len(w.exercises) > 8:
            draw.text((M + 40, y), f"+{len(w.exercises) - 8} more", fill=ce.FAINT, font=ce.font(ce.FONT_MONO, 24))
            y += 42

    y = _coach_line(draw, facts, y=y + 26)
    y = _goal_bar(draw, facts, y=max(y + 30, 1000))

    y += 34
    if facts.acwr is not None:
        zone = (facts.acwr_zone or "").upper()
        colour = ce.GREEN if zone == "SAFE" else ce.AMBER
        y = _fact_row(draw, "load", f"ACWR {facts.acwr:.2f} · {zone.lower() or '—'}", y=y, colour=colour, size=26)
    if facts.readiness is not None:
        y = _fact_row(draw, "readiness", f"{facts.readiness:.0f}/100", y=y, size=26)

    _footer(draw)
    return img


# ── D. RECKONING — the weekly close ───────────────────────────────────────────
def reckoning(facts, *, week_n: int, date_label: str, weight_series=None, grade_series=None, totals: dict[str, Any] | None = None):
    img, draw = _canvas()
    draw.text((M, 104), f"WEEK {week_n}  ·  ATTEMPT #{ATTEMPT_NUMBER}", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 30))
    draw.text((M, 148), date_label.upper(), fill=ce.FAINT, font=ce.font(ce.FONT_MONO, 22))
    y = 224

    totals = totals or {}
    delta = totals.get("weight_delta")
    if delta is not None:
        colour = ce.GREEN if delta < 0 else ce.AMBER
        hero = f"{abs(delta):.1f}"
        hf = ce.font(ce.FONT_DISPLAY, 158)
        draw.text((M, y), hero, fill=ce.TEXT, font=hf)
        try:
            hw = draw.textlength(hero, font=hf)
        except Exception:  # noqa: BLE001
            hw = 330
        draw.text((M + hw + 20, y + 86), "lb", fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 42))
        y += 188
        draw.text((M, y), "down this week" if delta < 0 else "up this week", fill=colour, font=ce.font(ce.FONT_MONO_BOLD, 34))
        y += 62

    # The week's grades as a strip — seven verdicts, one row. The arc at a glance.
    grades = [g for g in (grade_series or [])]
    if grades:
        y += 18
        draw.text((M, y), "THE WEEK, GRADED", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 22))
        y = _grade_strip(draw, grades, y=y + 46)

    # No sparkline here. The grade strip above already IS the week, and a two-dot line
    # under it said nothing the strip had not said better while colliding with it. One
    # visual per idea.
    y = draw_stakes(draw, y=max(y + 30, 668))
    y = _goal_bar(draw, facts, y=max(y + 22, 930))

    # The week's facts BEFORE the coach line. The first weekly card with a quote on it
    # drew the quote where "biggest miss — recovery 24/100" had been and pushed that row
    # (and "to goal") under the floor. On the weekly close the miss is the content and the
    # quote is the colour, so the quote is what gives way.
    y += 26
    for label, key, suffix in (("sessions", "sessions", ""), ("sets", "sets", ""), ("habits", "habit_pct", "%")):
        if totals.get(key) is not None:
            y = _fact_row(draw, label, f"{totals[key]:g}{suffix}", y=y, size=27)
    if totals.get("misses"):
        y = _fact_row(draw, "biggest miss", str(totals["misses"]), y=y, colour=ce.AMBER, size=25)
    if facts.lb_to_goal is not None:
        y = _fact_row(draw, "to goal", f"{facts.lb_to_goal:.0f} lb", y=y, size=27)
    _coach_line(draw, facts, y=y + 10)

    _footer(draw)
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
    draw.text((M, y), line, fill=ce.FAINT, font=ce.font(ce.FONT_MONO, 20))
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
    names = list(FILLERS)
    start = (facts.day_n or 0) % len(names)
    order = names[start:] + names[:start]
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
    """One filler block with its header — and the absence it stands in for, named."""
    label, _ok, fn = FILLERS[name]
    draw.text((M, y), label.upper(), fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 22))
    if note:
        draw.text((M + W_CONTENT, y + 2), note, fill=ce.FAINT, font=ce.font(ce.FONT_MONO, 19), anchor="ra")
    return fn(draw, facts, ctx, y=y + 40)


# ── F. DAY ZERO — the starting line ───────────────────────────────────────────
def dayzero(facts, *, date_label: str):
    """The card for the eve of genesis: where attempt seventeen starts from.

    No day data is drawn — the day before Day 1 belongs to the previous cycle and its
    numbers are not this attempt's. What IS true on the eve: the baseline weigh-in the
    cycle is anchored to, the goal, the distance between them, the stakes, and what the
    platform will grade every day from here. Rendered once, by hand, for the top of the grid.
    """
    if facts.baseline_weight_lb is None or facts.goal_weight_lb is None:
        raise ValueError("dayzero layout needs the cycle's baseline and goal")
    img, draw = _canvas()
    y = _serial(draw, facts, date_label)

    hero = f"{facts.baseline_weight_lb:.1f}"
    hf = ce.font(ce.FONT_DISPLAY, 150)
    draw.text((M, y), hero, fill=ce.TEXT, font=hf)
    try:
        hw = draw.textlength(hero, font=hf)
    except Exception:  # noqa: BLE001
        hw = 340
    draw.text((M + hw + 18, y + 78), "lb", fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 40))
    y += 176
    draw.text((M, y), "the starting line", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 34))
    y += 70

    y = _goal_bar_at(draw, 0.0, facts.baseline_weight_lb, facts.goal_weight_lb, y=y)
    y += 20
    y = _fact_row(draw, "goal", f"{facts.goal_weight_lb:.0f} lb", y=y, size=30)
    y = _fact_row(draw, "to lose", f"{facts.baseline_weight_lb - facts.goal_weight_lb:.0f} lb", y=y, size=30)

    y = draw_stakes(draw, y=y + 26)

    y += 10
    draw.text((M, y), "GRADED EVERY DAY ON", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 22))
    y += 40
    names = [v for k, v in _COMPONENT_NAMES.items() if k != "journal"]
    for line in ce.wrap("  ·  ".join(names), width=54, max_lines=2):
        draw.text((M, y), line, fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 24))
        y += 36
    y += 8
    draw.text((M, y), "the first card lands tomorrow morning. bad days included.", fill=ce.FAINT, font=ce.font(ce.FONT_MONO, 22))

    _footer(draw)
    return img


def dayzero_caption(facts) -> str:
    head = f"Day 0 · attempt #{ATTEMPT_NUMBER}"
    body = (
        f"The starting line: {facts.baseline_weight_lb:.1f} lb. Goal {facts.goal_weight_lb:.0f} lb, "
        f"{facts.baseline_weight_lb - facts.goal_weight_lb:.0f} lb to lose. "
        "Sixteen times the weight came off since 2012. Zero times it stayed off. "
        "This one is instrumented, public, and graded every day — bad days included."
    )
    return cap_caption(head + "\n" + body)


# ── E. DETAIL — the second card: trained / ate / the rest ─────────────────────
#: A real band draws only when the day has it; an empty slot takes a filler. Two blocks
#: make a card, one does not (#3741, the owner's brief: "a dual or three part split").
DETAIL_MIN_BANDS = 2
DETAIL_SLOTS = 3
#: Exercise rows the TRAINED band may list when all three slots share the frame.
DETAIL_EXERCISE_ROWS = {3: 5, 2: 8}
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


def _band_header(draw, label: str, *, y: int) -> int:
    draw.text((M, y), label.upper(), fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 22))
    return y + 40


def _fmt_minutes(mins: int | None) -> str | None:
    if not mins:
        return None
    return f"{mins // 60}h {mins % 60:02d}m" if mins >= 60 else f"{mins}m"


def _band_trained(draw, facts, *, y: int, rows: int) -> int:
    y = _band_header(draw, "trained", y=y)
    if facts.workouts:
        w = facts.workouts[0]
        title = _session_label(w.title)
        f = ch.fit_text(draw, title, font_name=ce.FONT_DISPLAY, max_size=72, min_size=40, width=W_CONTENT)
        draw.text((M, y), title, fill=ce.TEXT, font=f)
        y += 86
        bits = [f"{w.n_sets} sets"]
        if w.volume_lbs and w.volume_lbs > 0:
            bits.append(f"{w.volume_lbs:,.0f} lb moved")
        if _fmt_minutes(w.duration_min):
            bits.append(_fmt_minutes(w.duration_min) or "")
        draw.text((M, y), "  ·  ".join(bits), fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 26))
        y += 46
        shown = w.detail[:rows]
        for ex in shown:
            if y > FLOOR_Y - 40:
                break
            name = clean_title(ex.name)
            f_name = ce.font(ce.FONT_MONO, 23)
            right = f"{ex.n_sets} × {ex.reps}" if ex.reps else f"{ex.n_sets} sets"
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
            draw.text((M + W_CONTENT, y), right, fill=ce.FAINT, font=f_name, anchor="ra")
            y += 36
        if len(w.detail) > len(shown):
            draw.text((M, y), f"+{len(w.detail) - len(shown)} more", fill=ce.FAINT, font=ce.font(ce.FONT_MONO, 22))
            y += 36
    if facts.walk_miles is not None and facts.walk_miles >= 0.5:
        draw.text((M, y), f"walked {facts.walk_miles:.1f} mi", fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 23))
        y += 36
    return y


def _band_ate(draw, facts, *, y: int) -> int:
    y = _band_header(draw, "ate", y=y)
    if facts.calories is not None:
        hero = f"{facts.calories:,.0f}"
        hf = ce.font(ce.FONT_DISPLAY, 72)
        draw.text((M, y), hero, fill=ce.TEXT, font=hf)
        try:
            hw = draw.textlength(hero, font=hf)
        except Exception:  # noqa: BLE001
            hw = 200
        tail = "kcal" + (f"  ·  target {facts.cal_target:,.0f}" if facts.cal_target else "")
        draw.text((M + hw + 16, y + 36), tail, fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 26))
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
            (M, y), f"protein {frac * 100:.0f}% of the {facts.protein_target_g:.0f} g target", fill=ce.FAINT, font=ce.font(ce.FONT_MONO, 20)
        )
        y += 34
    if facts.meals is not None:
        logged = f"{int(facts.meals)} meal{'s' if int(facts.meals) != 1 else ''}"
        if facts.snacks:
            logged += f" · {int(facts.snacks)} snack{'s' if int(facts.snacks) != 1 else ''}"
        draw.text((M, y), f"{logged} logged", fill=ce.FAINT, font=ce.font(ce.FONT_MONO, 20))
        y += 34
    return y


def _rest_tiles(facts) -> list[tuple[str, str, str | None]]:
    """(label, value, note) for the REST band, in priority order. Absent stays absent."""
    tiles: list[tuple[str, str, str | None]] = []
    if facts.sleep_hrs is not None:
        tiles.append(("sleep", f"{facts.sleep_hrs:.1f} h", f"score {facts.sleep_score:.0f}" if facts.sleep_score is not None else None))
    if facts.recovery_pct is not None:
        tiles.append(("recovery", f"{facts.recovery_pct:.0f}%", f"HRV {facts.hrv_ms:.0f} ms" if facts.hrv_ms is not None else None))
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
    y = _band_header(draw, "the rest", y=y)
    tiles = _rest_tiles(facts)
    if tiles:
        cw = W_CONTENT // 3
        for i, (label, value, note) in enumerate(tiles):
            x = M + (i % 3) * cw
            ty = y + (i // 3) * 84
            draw.text((x, ty), label.upper(), fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 20))
            draw.text((x, ty + 28), value, fill=ce.TEXT, font=ce.font(ce.FONT_MONO, 34))
            if note:
                try:
                    vw = draw.textlength(value, font=ce.font(ce.FONT_MONO, 34))
                except Exception:  # noqa: BLE001
                    vw = 120
                draw.text((x + vw + 12, ty + 40), note, fill=ce.FAINT, font=ce.font(ce.FONT_MONO, 19))
        y += 84 * ((len(tiles) + 2) // 3) + 8
    if facts.missed_tier0:
        y = _fact_row(draw, "missed", " · ".join(facts.missed_tier0[:2]), y=y, colour=ce.AMBER, size=24)
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
    draw.text((M + W_CONTENT, 148), "2 OF 2  ·  THE DETAIL", fill=ce.FAINT, font=ce.font(ce.FONT_MONO, 22), anchor="ra")
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
    return cap_caption((head + "\n" + " ".join(bits)).strip())


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


def pick_beat(facts, trailing=None) -> tuple[str, str]:
    """Which layout this day's story wants, and why. Returns (layout, reason).

    Ava Moreau's correction, and the reason the first cards felt interchangeable: the
    original picker chose by DATA MAGNITUDE — largest number wins — which is not how a
    serial works. A campaign picks a BEAT. The same 27-set session is a different post on
    the day he also weighed in than on the day he did not.

    Deterministic and ordered, so the same day always produces the same beat and "a
    different card every day" is a property rather than a hope.
    """
    trailing = trailing or []

    # 1. A new weigh-in is the arc moving. It is the rarest event and the most postable —
    #    and on this cycle it is genuinely rare: one in the whole first week.
    prev = next((d.weight_lb for d in reversed(trailing) if d.date != facts.date and d.weight_lb is not None), None)
    if facts.weight_lb is not None and prev is not None and abs(facts.weight_lb - prev) > 0.05:
        return "trajectory", "new weigh-in — the arc moved"

    # 2. A heavy session is its own story, with the movements named.
    sets = sum(w.n_sets for w in facts.workouts)
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
CAPTION_MAX_CHARS = 300


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
        bits.append("Missed: " + ", ".join(facts.missed_tier0[:2]) + ".")
    body = " ".join(bits)
    # The coach line goes last and is the first thing dropped. The stats are the card's
    # claim; the quote is its voice, and a caption that truncates mid-number reads as
    # broken in a way a caption that simply has no quote does not (#3749).
    line = getattr(facts, "coach_line", None)
    if line:
        candidate = f'{body} — "{line}"'.strip()
        body = candidate if len(head) + 1 + len(candidate) <= CAPTION_MAX_CHARS else body
    return cap_caption((head + "\n" + body).strip())
