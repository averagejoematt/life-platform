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

One hero, one supporting structure, a footer of facts. Density comes from MARKS, never from
more blocks of text (Mara Chen's line, and she is right about the thumb-stop).
"""

from __future__ import annotations

from typing import Any

from web import card_engine as ce, recap_charts as ch

PORTRAIT = (1080, 1350)
M = 72  # margin
W_CONTENT = PORTRAIT[0] - 2 * M

ATTEMPT_NUMBER = 17  # cycle 17 — see CYCLE_GENESES; the serial marker's second half
TAGLINE = "proof, not promises"


# ── shared chrome ─────────────────────────────────────────────────────────────
def _canvas():
    return ce.base_canvas(size=PORTRAIT, margin=M)


def _serial(draw, facts, date_label: str) -> int:
    """`DAY 8 · ATTEMPT #17` over a quiet second line. On every card, without exception."""
    day = f"DAY {facts.day_n}" if facts.day_n else "DAY —"
    draw.text((M, 104), f"{day}  ·  ATTEMPT #{ATTEMPT_NUMBER}", fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 30))
    draw.text((M, 148), date_label.upper(), fill=ce.FAINT, font=ce.font(ce.FONT_MONO, 22))
    return 210


def _goal_bar(draw, facts, *, y: int) -> int:
    """baseline → now → goal. The arc, on every card, because the arc is the story."""
    frac = facts.pct_to_goal
    if frac is None:
        return y
    ch.draw_progress(draw, frac, x=M, y=y, w=W_CONTENT, h=16)
    y += 30
    left = f"{facts.baseline_weight_lb:.0f} lb  day one"
    right = f"goal  {facts.goal_weight_lb:.0f} lb"
    draw.text((M, y), left, fill=ce.FAINT, font=ce.font(ce.FONT_MONO, 21))
    draw.text((M + W_CONTENT, y), right, fill=ce.FAINT, font=ce.font(ce.FONT_MONO, 21), anchor="ra")
    mid = f"{frac * 100:.1f}% of the way"
    try:
        tw = draw.textlength(mid, font=ce.font(ce.FONT_MONO, 21))
    except Exception:  # noqa: BLE001
        tw = 200
    draw.text((M + (W_CONTENT - tw) / 2, y), mid, fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 21))
    return y + 44


def _footer(draw, right: str = "averagejoematt.com"):
    ce.draw_footer(draw, left_text=TAGLINE, right_text=right, canvas=PORTRAIT, margin=M)


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


def _session_label(title: str) -> str:
    parts = [p.strip() for p in str(title or "").split(" - ")]
    if len(parts) >= 2 and parts[1]:
        return f"{parts[1]} day".title() if len(parts[1]) <= 12 else parts[1]
    return str(title or "Training")


_COMPONENT_NAMES = {
    "habits_mvp": "habits",
    "sleep_quality": "sleep",
    "movement": "movement",
    "nutrition": "nutrition",
    "recovery": "recovery",
    "hydration": "hydration",
    "journal": "journal",
}


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
def scorecard(facts, *, date_label: str):
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
        y = ch.draw_component_bars(draw, comps, x=M, y=y, w=W_CONTENT, label_w=230, row_h=48)

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
        draw.text(
            (M, y),
            f"{n_meas} weigh-ins across {len(series)} days"
            + ("  ·  dots, not a line — the days between were not measured" if n_meas < 4 else ""),
            fill=ce.FAINT,
            font=ce.font(ce.FONT_MONO, 20),
        )
        y += 44
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
        y += 46
        cell = W_CONTENT // max(len(grades), 1)
        for i, g in enumerate(grades):
            cx = M + i * cell
            colour = ch.grade_colour(g) if g else (30, 42, 34)
            draw.rounded_rectangle([cx, y, cx + cell - 12, y + 74], radius=10, outline=colour, width=4)
            if g:
                gf = ce.font(ce.FONT_DISPLAY, 38)
                try:
                    tw = draw.textlength(g, font=gf)
                except Exception:  # noqa: BLE001
                    tw = 30
                draw.text((cx + (cell - 12 - tw) / 2, y + 12), g, fill=colour, font=gf)
        y += 96

    # No sparkline here. The grade strip above already IS the week, and a two-dot line
    # under it said nothing the strip had not said better while colliding with it. One
    # visual per idea.
    y = draw_stakes(draw, y=max(y + 30, 668))
    y = _coach_line(draw, facts, y=y + 18)
    y = _goal_bar(draw, facts, y=max(y + 22, 996))

    y += 26
    for label, key, suffix in (("sessions", "sessions", ""), ("sets", "sets", ""), ("habits", "habit_pct", "%")):
        if totals.get(key) is not None:
            y = _fact_row(draw, label, f"{totals[key]:g}{suffix}", y=y, size=27)
    if totals.get("misses"):
        y = _fact_row(draw, "biggest miss", str(totals["misses"]), y=y, colour=ce.AMBER, size=25)
    if facts.lb_to_goal is not None:
        y = _fact_row(draw, "to goal", f"{facts.lb_to_goal:.0f} lb", y=y, size=27)

    _footer(draw)
    return img


LAYOUTS = {"scorecard": scorecard, "trajectory": trajectory, "session": session, "reckoning": reckoning}


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


def gate_strings(facts, caption: str = "") -> list[str]:
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
    return out


def render_beat(layout: str, facts, *, date_label: str, weight_series=None, grade_series=None, week_n=None, totals=None):
    """Render one beat. Raises if the layout cannot be honestly drawn for this day."""
    if layout == "trajectory":
        return trajectory(facts, date_label=date_label, weight_series=weight_series, grade_series=grade_series)
    if layout == "session":
        return session(facts, date_label=date_label)
    if layout == "reckoning":
        return reckoning(
            facts, week_n=week_n or 1, date_label=date_label, weight_series=weight_series, grade_series=grade_series, totals=totals
        )
    return scorecard(facts, date_label=date_label)


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
    head = f"{day_label} · attempt #{ATTEMPT_NUMBER}"
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
