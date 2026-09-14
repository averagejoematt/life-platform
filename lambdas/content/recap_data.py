"""recap_data.py — one PT day, assembled, with absence kept absent (#3744/#3745).

WHAT THIS IS FOR

The daily recap card needs a whole day in one shape: weight, the workout, habits,
nutrition, whether he journaled, how far he walked. Six partitions, one date.

WHY A NEW MODULE AND NOT THE BRIEF'S READERS

`lambdas/emails/daily_brief_lambda.py` already does this superbly — `fetch_date`,
`fetch_range`, `fetch_hevy_workouts` — but they are module-local to a handler that builds
boto3 clients, resolves SES identities and reads a profile at import. A card renderer that
imports an email Lambda to borrow three DDB queries has taken on that whole surface. The
genuinely shared pieces are `common.digest_utils` and `experiment.phase_filter`, and those
are imported here directly; the three query wrappers are six lines each.

THE ONE RULE

Every field is Optional and absence is recorded, never defaulted. A card that draws "0
workouts" when the Hevy poll simply had not run yet is publishing a false statement about
his day to a public grid — the #3527 class, on a surface that cannot be corrected after
someone screenshots it. So: `None` means "we did not see it", `absent` lists what was
missing, and the template layer refuses to render a field it does not have (#3745).

WHAT IS DELIBERATELY NOT READ

Food ITEM names (macrofactor is TIER_OWNER_ONLY; only rollup numbers cross this boundary)
and journal BODY text (the template labels are enough to say "he journaled"). Both are
enforced by the compensating control in `tests/test_recap_gate_3746.py`, because the
cheapest place to stop a leak is before the value is ever loaded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from common.digest_utils import d2f
from common.pacific_time import pacific_day_n
from experiment.phase_filter import with_phase_filter

USER_PREFIX = "USER#matthew"


# ── the three query wrappers ──────────────────────────────────────────────────
def _get_day(table, source: str, date: str) -> dict[str, Any] | None:
    """One row for one PT day, or None. A query error is None — never {}."""
    try:
        resp = table.get_item(Key={"pk": f"{USER_PREFIX}#SOURCE#{source}", "sk": f"DATE#{date}"})
    except Exception:  # noqa: BLE001
        return None
    item = resp.get("Item")
    return d2f(item) if item else None


def _query_prefix(table, source: str, sk_prefix: str) -> list[dict[str, Any]]:
    """Every row under a sort-key prefix (hevy workouts, journal entries)."""
    from boto3.dynamodb.conditions import Key

    try:
        kwargs = with_phase_filter(
            {"KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}#SOURCE#{source}") & Key("sk").begins_with(sk_prefix)}
        )
        resp = table.query(**kwargs)
    except Exception:  # noqa: BLE001
        return []
    return [d2f(i) for i in resp.get("Items", [])]


def _query_range(table, source: str, start: str, end: str) -> list[dict[str, Any]]:
    from boto3.dynamodb.conditions import Key

    try:
        kwargs = with_phase_filter(
            {"KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}#SOURCE#{source}") & Key("sk").between(f"DATE#{start}", f"DATE#{end}~")}
        )
        resp = table.query(**kwargs)
    except Exception:  # noqa: BLE001
        return []
    return [d2f(i) for i in resp.get("Items", [])]


@dataclass
class WorkoutFact:
    """A lift session, reduced to what a card can draw. Titles only, never notes."""

    title: str
    n_exercises: int
    n_sets: int
    volume_lbs: float
    top_exercise: str | None = None
    exercises: list[str] = field(default_factory=list)


@dataclass
class DayFacts:
    """One PT day. Every measurement Optional; `absent` says what was not seen."""

    date: str
    day_n: int | None = None
    # weight
    weight_lb: float | None = None
    week_ago_weight_lb: float | None = None
    weekly_rate_lb: float | None = None
    rate_ci: tuple[float, float] | None = None
    rate_provisional: bool = True
    # training
    workouts: list[WorkoutFact] = field(default_factory=list)
    walk_miles: float | None = None
    # habits — counts only, never habit NAMES on a public card
    tier0_done: int | None = None
    tier0_total: int | None = None
    tier0_pct: float | None = None
    tier0_streak: int | None = None
    # nutrition — rollups only, never item names (macrofactor is TIER_OWNER_ONLY)
    calories: float | None = None
    protein_g: float | None = None
    protein_target_g: float | None = None
    # mind
    journal_templates: list[str] = field(default_factory=list)
    # the platform's OWN verdict on the day — 53 fields were available and the first
    # cards drew four. These are the ones a reader would actually want (#3741 rework).
    grade_letter: str | None = None
    grade_score: float | None = None
    component_scores: dict[str, float] = field(default_factory=dict)
    readiness: float | None = None
    readiness_colour: str | None = None
    acwr: float | None = None
    acwr_zone: str | None = None
    sleep_debt_hrs: float | None = None
    hrv_ms: float | None = None
    # habit + vice DETAIL. These carry NAMES, so they travel through item_labels() and the
    # privacy gate — "which habit" is the interesting half and also the risky half.
    missed_tier0: list[str] = field(default_factory=list)
    vice_streaks: dict[str, float] = field(default_factory=dict)
    # the throughline: where he started, where he is, where he is going
    baseline_weight_lb: float | None = None
    goal_weight_lb: float | None = None
    # the cycle so far, for the sparkline. Gaps stay gaps.
    weight_series: list[float | None] = field(default_factory=list)
    grade_series: list[str | None] = field(default_factory=list)
    # provenance
    absent: list[str] = field(default_factory=list)

    @property
    def journaled(self) -> bool | None:
        """None when the journal partition could not be read at all."""
        if "notion" in self.absent:
            return None
        return bool(self.journal_templates)

    @property
    def total_lost_lb(self) -> float | None:
        """Cumulative loss since Day 1 — the single most postable number of a cycle.

        The first seven cards did not carry it once. He lost 7.66 lb in week one and no
        card said so, because every template was scoped to a single day.
        """
        if self.weight_lb is None or self.baseline_weight_lb is None:
            return None
        return round(self.baseline_weight_lb - self.weight_lb, 1)

    @property
    def pct_to_goal(self) -> float | None:
        """Fraction of the baseline→goal distance covered. None when either end is absent."""
        if self.weight_lb is None or self.baseline_weight_lb is None or self.goal_weight_lb is None:
            return None
        span = self.baseline_weight_lb - self.goal_weight_lb
        if span <= 0:
            return None
        return max(0.0, min(1.0, (self.baseline_weight_lb - self.weight_lb) / span))

    @property
    def lb_to_goal(self) -> float | None:
        if self.weight_lb is None or self.goal_weight_lb is None:
            return None
        return round(self.weight_lb - self.goal_weight_lb, 1)

    def item_labels(self) -> list[tuple[str, str]]:
        """(template, label) pairs the privacy gate screens — every name a card could draw.

        Habit and vice NAMES are here for a reason: "which habit did he miss" and "what is
        he holding a streak on" are the interesting half of that data AND the risky half.
        One of his live vice streaks is a blocked-category name; the gate is what keeps it
        off a public grid, and the gate can only screen what this list hands it.
        """
        out: list[tuple[str, str]] = []
        for w in self.workouts:
            if w.title:
                out.append(("workout", w.title))
            if w.top_exercise:
                out.append(("workout", w.top_exercise))
            for ex in w.exercises:
                out.append(("training", ex))
        for name in self.missed_tier0:
            out.append(("habits", name))
        for name in self.vice_streaks:
            out.append(("streaks", name))
        return out


def _workout_facts(rows: list[dict[str, Any]]) -> list[WorkoutFact]:
    out: list[WorkoutFact] = []
    for r in rows:
        exercises = r.get("exercises") or []
        sets = 0
        volume = 0.0
        best = (0.0, None)
        for ex in exercises:
            ex_vol = 0.0
            for s in ex.get("sets") or []:
                reps = s.get("reps") or 0
                kg = s.get("weight_kg")
                lbs = s.get("weight_lbs")
                if lbs is None and kg is not None:
                    lbs = float(kg) * 2.20462
                try:
                    ex_vol += float(lbs or 0) * int(reps or 0)
                except (TypeError, ValueError):
                    continue
                sets += 1
            volume += ex_vol
            name = ex.get("name") or ex.get("title")
            if name and ex_vol > best[0]:
                best = (ex_vol, name)
        out.append(
            WorkoutFact(
                title=(r.get("workout_name") or r.get("title") or "Training"),
                n_exercises=len(exercises),
                n_sets=sets,
                volume_lbs=round(volume, 1),
                top_exercise=best[1],
                exercises=[e.get("name") or e.get("title") for e in exercises if (e.get("name") or e.get("title"))],
            )
        )
    return out


def day_facts(table, date: str, *, experiment_start: str | None = None) -> DayFacts:
    """Assemble one PT day. Reads six partitions; records what it could not see."""
    facts = DayFacts(date=date)
    if experiment_start:
        n = pacific_day_n(experiment_start, date)
        facts.day_n = n or None

    computed = _get_day(table, "computed_metrics", date)
    if computed is None:
        facts.absent.append("computed_metrics")
    else:
        facts.weight_lb = computed.get("latest_weight")
        facts.week_ago_weight_lb = computed.get("week_ago_weight")
        facts.weekly_rate_lb = computed.get("weekly_rate_lbs")
        lo, hi = computed.get("weekly_rate_ci_low"), computed.get("weekly_rate_ci_high")
        facts.rate_ci = (lo, hi) if lo is not None and hi is not None else None
        # Absent provisionality is treated as PROVISIONAL, not as settled. A projected
        # rate drawn as fact is the #551 / ADR-105 failure, and this card is public.
        facts.rate_provisional = bool(computed.get("rate_provisional", True))
        facts.protein_g = computed.get("protein_g_avg")
        facts.protein_target_g = computed.get("protein_g_target")
        facts.tier0_streak = computed.get("tier0_streak")
        # The platform's own verdict on the day, and what earned it. 53 fields were sitting
        # here while the first cards drew four (#3741 rework).
        facts.grade_letter = computed.get("day_grade_letter")
        facts.grade_score = computed.get("day_grade_score")
        facts.component_scores = {k: v for k, v in (computed.get("component_scores") or {}).items() if v is not None}
        facts.readiness = computed.get("readiness_score")
        facts.readiness_colour = computed.get("readiness_colour")
        facts.acwr = computed.get("acwr")
        facts.acwr_zone = computed.get("acwr_zone")
        facts.sleep_debt_hrs = computed.get("sleep_debt_7d_hrs")
        facts.hrv_ms = computed.get("hrv_ms")
        facts.vice_streaks = {k: v for k, v in (computed.get("vice_streaks") or {}).items() if v}

    habits = _get_day(table, "habit_scores", date)
    if habits is None:
        facts.absent.append("habit_scores")
    else:
        facts.tier0_done = habits.get("tier0_done")
        facts.tier0_total = habits.get("tier0_total")
        pct = habits.get("tier0_pct")
        facts.tier0_pct = float(pct) if pct is not None else None
        # WHICH habits were missed is the interesting half — "5/7" says nothing a reader
        # can hold on to, "missed the 5k walk" is a person having a day.
        facts.missed_tier0 = [m for m in (habits.get("missed_tier0") or []) if isinstance(m, str)]
        if not facts.vice_streaks:
            facts.vice_streaks = {k: v for k, v in (habits.get("vice_streaks") or {}).items() if v}

    hevy_rows = _query_prefix(table, "hevy", f"DATE#{date}")
    if not hevy_rows:
        # An empty query cannot distinguish "rest day" from "the poll has not run".
        # The freshness of the hevy partition answers that, and the card templates ask
        # for it — here we only record that nothing was returned.
        facts.absent.append("hevy")
    facts.workouts = _workout_facts(hevy_rows)

    strava = _get_day(table, "strava", date)
    if strava is None:
        facts.absent.append("strava")
    else:
        miles = 0.0
        for a in strava.get("activities") or []:
            if (a.get("type") or a.get("sport_type") or "").lower() in ("walk", "hike"):
                try:
                    miles += float(a.get("distance_miles") or 0)
                except (TypeError, ValueError):
                    continue
        facts.walk_miles = round(miles, 2)

    mf = _get_day(table, "macrofactor", date)
    if mf is None:
        facts.absent.append("macrofactor")
    else:
        facts.calories = mf.get("total_calories_kcal")
        if facts.protein_g is None:
            facts.protein_g = mf.get("total_protein_g") or mf.get("protein_g")

    # The throughline. Where he started, where he is going — the two numbers that make a
    # single card legible to someone who has never seen another one.
    try:
        from common.constants import EXPERIMENT_BASELINE_WEIGHT_LBS, EXPERIMENT_GOAL_WEIGHT_LBS

        facts.baseline_weight_lb = float(EXPERIMENT_BASELINE_WEIGHT_LBS)
        facts.goal_weight_lb = float(EXPERIMENT_GOAL_WEIGHT_LBS)
    except Exception:  # noqa: BLE001
        pass

    journal = _query_prefix(table, "notion", f"DATE#{date}#journal#")
    if not journal:
        facts.absent.append("notion")
    # Template LABELS only. The body is the entry; a public card says that he wrote, never
    # what he wrote.
    facts.journal_templates = [t for t in (j.get("template") for j in journal) if t]

    return facts


def cycle_series(table, start: str, end: str) -> tuple[list[float | None], list[str | None]]:
    """(weights, grades) for every PT day from `start` to `end`, gaps as None.

    A missing day stays None all the way to the renderer, which breaks the sparkline
    rather than drawing through it. He has ONE weigh-in in week 1; a smooth seven-point
    descent through a single measurement would be the prettiest possible lie.
    """
    rows = {r.get("date"): r for r in _query_range(table, "computed_metrics", start, end) if r.get("date")}
    weights: list[float | None] = []
    grades: list[str | None] = []
    last_seen = None
    for day in _day_range(start, end):
        row = rows.get(day) or {}
        w = row.get("latest_weight")
        # computed_metrics carries the LAST KNOWN weight forward, so an unchanged value is
        # not a new measurement. Only a CHANGE is a data point; the rest are repeats of it.
        if w is not None and w != last_seen:
            weights.append(float(w))
            last_seen = w
        else:
            weights.append(None)
        grades.append(row.get("day_grade_letter"))
    return weights, grades


def _day_range(start: str, end: str) -> list[str]:
    from datetime import timedelta

    from common.pacific_time import parse_day_key

    d0, d1 = parse_day_key(start), parse_day_key(end)
    if d0 is None or d1 is None:
        return []
    return [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def trailing(table, end_date: str, days: int = 7, *, experiment_start: str | None = None) -> list[DayFacts]:
    """The `days` PT days ending at `end_date`, oldest first — the picker's baseline.

    CLAMPED AT THE EXPERIMENT START, and the clamp is the whole point. An unclamped window
    reaches into the PREVIOUS cycle, and comparing across a genesis boundary is how the
    first cards headlined "2.7 lb UP THIS WEEK" on Day 4 — a week-ago weight belonging to a
    different attempt, rendered as a gain. It recurred the moment beat-selection began
    reading this same window: Day 1 chose the "new weigh-in" beat off a weight from before
    the cycle began.

    Twice is a class, not a coincidence. Any window that does not know where the experiment
    starts will eventually be asked a question that spans the boundary, so the boundary
    lives here, once, instead of in each caller's head.
    """
    from datetime import timedelta

    from common.pacific_time import parse_day_key

    end = parse_day_key(end_date)
    if end is None:
        return []
    # An unparseable genesis leaves the window UNCLAMPED rather than empty — the same
    # shape as `experiment_start=None`. That is deliberate: a bad genesis string must
    # degrade to "no boundary known", never to "no data", or the card silently stops
    # rendering on a typo instead of telling anyone.
    floor = parse_day_key(experiment_start) if experiment_start else None
    out = []
    for i in range(days - 1, -1, -1):
        d = end - timedelta(days=i)
        if floor and d < floor:
            continue
        out.append(day_facts(table, d.isoformat(), experiment_start=experiment_start))
    return out
