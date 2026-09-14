"""recap_templates.py — six things a day can be about, and which one it was (#3745).

THE BRIEF, VERBATIM

The owner asked for a daily card he can post, and then: *"so it's not just rinse and
repeat… any sort of new, unique, interesting things that would captivate me would
captivate my readers about the story."*

A fixed layout is a dashboard screenshot by day three. So the deck holds six templates and
each day the one or two with the most SIGNAL are drawn. Signal is not "did we have the
data" — it is "did something happen here that a reader would notice": a big move against
his own trailing baseline, a first-in-N-days event, a streak boundary.

TWO RULES THAT OUTRANK VARIETY

1. A template with nothing true to say draws NOTHING. `signal()` returns None and the
   template is not a candidate. This platform has shipped a card asserting "Real CGM data.
   Updated daily." over a null endpoint (#3527), a card painting a weight GAIN in success
   green under the caption "LOST" (#3285), and cards publishing fabricated tool counts
   (#3261). Those were pages, correctable in minutes. This is a public Instagram grid,
   where a wrong frame lives in someone's screenshot forever.

2. A direction word comes from `journey_direction.classify_delta`, never from the sign of
   a number formatted somewhere else. That is the one ruling #3285 produced and it is a
   function call, not a convention.

`render()` raising `RecapNullFact` rather than drawing an em-dash is deliberate: on the
site a "—" honestly says "not measured", but on a card with no surrounding context it
reads as a design flourish or an error. The picker is supposed to have prevented this, so
reaching a missing field here means the picker is wrong — which is a bug, not a dash.
"""

from __future__ import annotations

from typing import Any, Callable

# Ordered. Ties break toward the top — a weight move is more of a story than a journal tick.
PRIORITY = ["weight_trend", "workout", "consistency_comeback", "habits", "nutrition", "journal"]

#: A second card only earns its slot with real signal of its own.
SECOND_SLOT_FLOOR = 0.4

ALGO_VERSION = "recap-picker@1.0.0"


class RecapNullFact(Exception):
    """A template tried to draw a fact it does not have — the picker let it through."""


def _has(*values) -> bool:
    return all(v is not None for v in values)


def _require(name: str, value):
    if value is None:
        raise RecapNullFact(f"{name} is absent — this template should not have been picked")
    return value


# ── signals ───────────────────────────────────────────────────────────────────
def _weight_signal(facts, trailing) -> float | None:
    """A real, settled weekly move. Provisional rates and unknown directions decline."""
    from web.journey_direction import UNKNOWN, classify_delta

    if not _has(facts.weight_lb, facts.week_ago_weight_lb, facts.weekly_rate_lb):
        return None
    if facts.rate_provisional:
        # ADR-105: a projected number does not go on a public card as fact.
        return None
    direction, magnitude = classify_delta(facts.week_ago_weight_lb - facts.weight_lb, decimals=1)
    if direction == UNKNOWN or magnitude is None:
        return None

    lo, hi = facts.rate_ci or (None, None)
    ci_known = lo is not None and hi is not None
    ci_excludes_zero = ci_known and ((lo > 0 and hi > 0) or (lo < 0 and hi < 0))

    # ADR-105, found by rendering real data: on 2026-09-09 this scored 0.9 and headlined
    # "2.7 lb UP THIS WEEK" while its own interval ran -0.5 to +3.4 — a direction the
    # measurement does not establish, stated as the single largest thing on a permanent
    # public frame. The blueprint says the same in words ("early-cut drops are water, don't
    # read week-1 rate as tissue"), and a straddling interval is that sentence in numbers.
    #
    # It is NOT suppressed — a stated weight is honest and the card may still carry it as
    # the supporting beat. It just stops being the headline, which is what a score above
    # the second-slot floor buys.
    if ci_known and not ci_excludes_zero:
        return round(min(SECOND_SLOT_FLOOR - 0.05, 0.2 + abs(magnitude) / 20.0), 3)

    score = min(1.0, abs(magnitude) / 3.0)
    if ci_excludes_zero:
        # An interval clear of zero is a stronger claim than a point estimate.
        score += 0.3
    return round(min(score, 1.0), 3)


def _workout_signal(facts, trailing) -> float | None:
    if not facts.workouts:
        return None
    sets = sum(w.n_sets for w in facts.workouts)
    if sets <= 0:
        return None
    score = min(1.0, sets / 25.0)
    prior_best = max((sum(w.n_sets for w in d.workouts) for d in trailing[:-1] if d.workouts), default=0)
    if prior_best and sets > prior_best:
        score += 0.3
    return round(min(score, 1.0), 3)


def _habits_signal(facts, trailing) -> float | None:
    if not _has(facts.tier0_total, facts.tier0_pct) or not facts.tier0_total:
        return None
    score = float(facts.tier0_pct)
    if score > 1.0:  # a percentage, not a fraction
        score = score / 100.0
    if facts.tier0_streak and facts.tier0_streak >= 3:
        score += 0.2
    return round(min(score, 1.0), 3)


def _nutrition_signal(facts, trailing) -> float | None:
    if facts.protein_g is None:
        return None
    if facts.protein_target_g:
        return round(min(1.0, float(facts.protein_g) / float(facts.protein_target_g)), 3)
    return 0.3


def _journal_signal(facts, trailing) -> float | None:
    """A tie-breaker. Real, but rarely the headline."""
    if not facts.journal_templates:
        return None
    return round(min(1.0, 0.35 + 0.1 * len(facts.journal_templates)), 3)


def _comeback_signal(facts, trailing) -> float | None:
    """First good day after a bad one, or a streak worth naming.

    The owner asked for "what habits I've improved on that I didn't do recently" — the
    shape of a comeback, not a level. Needs at least three days of baseline to say either.
    """
    # The baseline is every day BEFORE this one. Callers differ on whether their trailing
    # window includes today, so today is excluded by DATE rather than by position — an
    # off-by-one here would compare him against himself and never fire.
    series = [d.tier0_pct for d in (trailing or []) if d.tier0_pct is not None and d.date != facts.date]
    if len(series) < 2 or facts.tier0_pct is None:
        return None
    today = facts.tier0_pct / 100.0 if facts.tier0_pct > 1 else facts.tier0_pct
    prior = [p / 100.0 if p > 1 else p for p in series]
    if prior and prior[-1] < 0.5 and today >= 0.9:
        return 0.9
    run = 0
    for p in reversed(prior + [today]):
        if p >= 0.9:
            run += 1
        else:
            break
    if run >= 3:
        return round(min(1.0, 0.6 + 0.05 * run), 3)
    return None


# ── copy (the strings a renderer draws; drawing itself is #3744) ──────────────
def _session_label(title: str) -> str:
    """A human name for a session, from Hevy's filing convention.

    The compiler auto-names every routine `Phase - Type - N - Y` ("Foundation - Pull - 2 -
    6"). That is exactly right in a workout app, where it sorts and dedupes, and exactly
    wrong as the largest words on a card a stranger sees — it reads like a build number.
    Take the type, keep the rest for the caption if anyone wants it.
    """
    parts = [p.strip() for p in str(title or "").split(" - ")]
    if len(parts) >= 2 and parts[1]:
        return f"{parts[1]} day".title() if len(parts[1]) <= 12 else parts[1]
    return str(title or "Training")


def _weight_copy(facts) -> dict[str, Any]:
    from web.journey_direction import DOWN, EVEN, UP, classify_delta

    lost = _require("week_ago_weight_lb", facts.week_ago_weight_lb) - _require("weight_lb", facts.weight_lb)
    direction, magnitude = classify_delta(lost, decimals=1)
    label = {DOWN: "DOWN", UP: "UP", EVEN: "HELD"}.get(direction, "NET CHANGE")
    sub = None
    if facts.rate_ci and facts.rate_ci[0] is not None and facts.rate_ci[1] is not None:
        sub = f"7-day rate CI {facts.rate_ci[0]:+.1f} to {facts.rate_ci[1]:+.1f} lb/wk"
    return {
        "hero": f"{abs(magnitude):.1f} lb" if magnitude is not None else None,
        "label": f"{label} THIS WEEK",
        "direction": direction,
        "sub": sub,
        "lines": [f"{facts.weight_lb:.1f} lb today"],
    }


def _workout_copy(facts) -> dict[str, Any]:
    if not facts.workouts:
        raise RecapNullFact("no workouts — this template should not have been picked")
    sets = sum(w.n_sets for w in facts.workouts)
    vol = sum(w.volume_lbs for w in facts.workouts)
    titles = ", ".join(_session_label(w.title) for w in facts.workouts)
    lines = [f"{sets} working sets", f"{vol:,.0f} lb moved"]
    top = next((w.top_exercise for w in facts.workouts if w.top_exercise), None)
    if top:
        lines.append(f"most volume: {top}")
    return {"hero": titles, "label": "TRAINED", "lines": lines}


def _habits_copy(facts) -> dict[str, Any]:
    # DynamoDB returns Decimals, which format as "6.0/7.0". A count of habits is an
    # integer everywhere a human says it out loud, and the card is read by humans.
    done = int(_require("tier0_done", facts.tier0_done))
    total = int(_require("tier0_total", facts.tier0_total))
    lines = []
    if facts.tier0_streak:
        lines.append(f"{int(facts.tier0_streak)}-day streak")
    return {"hero": f"{done}/{total}", "label": "TIER-0 HABITS", "lines": lines}


def _nutrition_copy(facts) -> dict[str, Any]:
    protein = _require("protein_g", facts.protein_g)
    lines = []
    if facts.protein_target_g:
        lines.append(f"target {facts.protein_target_g:.0f} g")
    if facts.calories:
        lines.append(f"{facts.calories:,.0f} kcal")
    return {"hero": f"{protein:.0f} g", "label": "PROTEIN", "lines": lines}


def _journal_copy(facts) -> dict[str, Any]:
    if not facts.journal_templates:
        raise RecapNullFact("no journal entries — this template should not have been picked")
    return {"hero": "Wrote it down", "label": "JOURNAL", "lines": [", ".join(sorted(set(facts.journal_templates)))]}


def _comeback_copy(facts) -> dict[str, Any]:
    pct = float(_require("tier0_pct", facts.tier0_pct))
    pct = pct / 100.0 if pct > 1 else pct
    return {"hero": f"{pct * 100:.0f}%", "label": "BACK ON IT", "lines": ["habits, after a miss"]}


Template = tuple[str, Callable[..., float | None], Callable[..., dict]]

TEMPLATES: dict[str, Template] = {
    "weight_trend": ("weight_trend", _weight_signal, _weight_copy),
    "workout": ("workout", _workout_signal, _workout_copy),
    "habits": ("habits", _habits_signal, _habits_copy),
    "nutrition": ("nutrition", _nutrition_signal, _nutrition_copy),
    "journal": ("journal", _journal_signal, _journal_copy),
    "consistency_comeback": ("consistency_comeback", _comeback_signal, _comeback_copy),
}


def score_all(facts, trailing) -> dict[str, float | None]:
    """Every template's signal for this day — the row that makes 'different' provable."""
    out: dict[str, float | None] = {}
    for name in PRIORITY:
        _, signal, _copy = TEMPLATES[name]
        try:
            out[name] = signal(facts, trailing or [])
        except Exception:  # noqa: BLE001 — a broken signal is not a candidate, never a crash
            out[name] = None
    return out


def pick(facts, trailing, *, k: int = 2, exclude: list[str] | None = None) -> list[str]:
    """The 1-2 templates with the most signal. Deterministic: same inputs, same choice."""
    excluded = set(exclude or [])
    scores = score_all(facts, trailing)
    ranked = sorted(
        ((name, s) for name, s in scores.items() if s is not None and name not in excluded),
        key=lambda kv: (-kv[1], PRIORITY.index(kv[0])),
    )
    if not ranked:
        return []
    chosen = [ranked[0][0]]
    if k > 1 and len(ranked) > 1 and ranked[1][1] >= SECOND_SLOT_FLOOR:
        chosen.append(ranked[1][0])
    return chosen


def copy_for(name: str, facts) -> dict[str, Any]:
    """The strings for one template. Raises RecapNullFact rather than drawing a dash."""
    _, _signal, copy_fn = TEMPLATES[name]
    return copy_fn(facts)


def all_strings(copies: list[dict[str, Any]], caption: str = "") -> list[str]:
    """Everything that will be drawn, flattened — what the privacy gate screens."""
    out: list[str] = []
    for c in copies:
        for key in ("hero", "label", "sub"):
            if c.get(key):
                out.append(str(c[key]))
        out.extend(str(x) for x in c.get("lines") or [])
    if caption:
        out.append(caption)
    return out
