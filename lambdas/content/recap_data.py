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

THE ONE FREE-TEXT FIELD, AND WHY IT IS THE ONLY ONE (#3749)

`coach_line` is the single exception, and it is an exception by SELECTION, not by
generation. Nothing here asks a model for a sentence about the day. The line is the
opening sentence of a coach's `public_summary` — a field that was written by the coach's
own run, passed the ADR-104 grounding gate there, and was stamped reader-safe by
`coach/audience_guard.reader_safe` at write time. Reading it here adds no new AI surface
and therefore no new grounding obligation; what it adds is a semantic risk that numbers
never carried, which is why `recap_gate` grew its fourth step in the same change.

The read seam is `audience_guard.public_blurb`, and the choice of seam is load-bearing.
`coach_derived_prose.served_summary()` looks like the right helper and is not: its
preference list is `key_recommendation, observatory_summary` with a fallback to the
coach's full `content`, all three of which are the OWNER's register — second person,
written to him. Falling back to any of them on a public card is the exact defect #2972
exists to prevent. `public_blurb` reads `public_summary` and nothing else, guards the
FULL text before truncating (order matters — truncation can delete the pronoun that makes
a text an address), and returns "" when there is no reader-safe line. A held or missing
condensation therefore means no line, never a substitute from a different audience.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from common.digest_utils import d2f
from common.pacific_time import pacific_day_n
from experiment.phase_filter import with_phase_filter

logger = logging.getLogger(__name__)

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
class ExerciseFact:
    """One movement as the detail card names it: sets × reps at the heaviest working weight.

    `reps` is the reps AT the top weight, not a total — "4 × 10 · 140 lb" is a sentence a
    lifter reads at a glance; "40 reps" is not. A bodyweight or timed movement has no
    weight, and the card says so by omitting it, never by printing "0 lb".
    """

    name: str
    n_sets: int
    top_weight_lb: float | None = None
    reps: int | None = None


@dataclass
class WorkoutFact:
    """A lift session, reduced to what a card can draw. Titles only, never notes."""

    title: str
    n_exercises: int
    n_sets: int
    volume_lbs: float
    top_exercise: str | None = None
    exercises: list[str] = field(default_factory=list)
    duration_min: int | None = None
    detail: list[ExerciseFact] = field(default_factory=list)
    #: Sets that carried a load or counted reps. Walking and stretching entries are sets
    #: in Hevy's model and are not "working sets" in anyone else's.
    n_working_sets: int = 0


@dataclass
class DayFacts:
    """One PT day. Every measurement Optional; `absent` says what was not seen."""

    date: str
    day_n: int | None = None
    # weight
    weight_lb: float | None = None
    #: `weight_lb` is `latest_weight` carried forward by the compute cron. Whether the
    #: scale was actually stepped on THIS day is a separate fact, and a card that
    #: headlines a carried-forward number as today's reading is the ADR-104 failure
    #: three panel seats caught on Days 1/3/5.
    weighed_today: bool = False
    last_weigh_label: str | None = None
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
    # nutrition — rollups only, never item names (macrofactor is TIER_OWNER_ONLY). The
    # macros are the published projection the site's own nutrition page serves; the
    # food_log stays where it is.
    calories: float | None = None
    cal_target: float | None = None
    protein_g: float | None = None
    protein_target_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    fiber_g: float | None = None
    meals: int | None = None
    snacks: int | None = None
    # the night and the body, as the compute cron scored them — read from
    # computed_metrics.component_details, so the detail card and the day's grade are
    # built from the same numbers and cannot disagree.
    sleep_hrs: float | None = None
    sleep_score: float | None = None
    recovery_pct: float | None = None
    rhr_bpm: float | None = None
    steps: float | None = None
    water_oz: float | None = None
    water_target_oz: float | None = None
    # mind
    journal_templates: list[str] = field(default_factory=list)
    # the one free-text field on the card — SELECTED from a coach's public_summary,
    # never minted for the card. `coach_line_source` is the OUTPUT# record it came from,
    # so any line on any card can be traced back to the run that wrote it (#3749).
    coach_line: str | None = None
    coach_line_source: str | None = None
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
    hrv_30d: float | None = None
    #: How many vices are tracked, from the scorer — never `len(vice_streaks)`, which
    #: counts only the ones currently held and made the denominator move day to day.
    vices_total: int | None = None
    #: A line the day crossed, set by the lambda (`recap_card_lambda._milestone`). None
    #: on an ordinary day; a short fixed phrase ("first 10 lb") when not.
    milestone: str | None = None
    #: Who the coach line is from, for attribution on the card ("physical coach").
    coach_label: str | None = None
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

    def free_text(self) -> list[str]:
        """Every string on the card that is PROSE rather than a number or a fixed label.

        Deliberately separate from `item_labels()`. That list is names from partitions with
        category rules, screened term-by-term against the blocked vocabulary; this one is
        sentences, which a vocabulary match is the wrong instrument for. `recap_gate` runs
        the semantic sensitivity layer over exactly this list and nothing else, so the day
        the card grows a second prose field, adding it here is what puts it under that gate.
        """
        return [t for t in (self.coach_line,) if t]

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
        working = 0
        volume = 0.0
        best = (0.0, None)
        detail: list[ExerciseFact] = []
        for ex in exercises:
            ex_vol = 0.0
            ex_sets = 0
            top: tuple[float, int] | None = None  # (weight_lb, reps at that weight)
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
                ex_sets += 1
                if (lbs and float(lbs) > 0) or (reps and int(reps) > 0):
                    working += 1
                if lbs is not None and float(lbs) > 0 and (top is None or float(lbs) > top[0]):
                    top = (float(lbs), int(reps or 0))
            volume += ex_vol
            name = ex.get("name") or ex.get("title")
            if name and ex_vol > best[0]:
                best = (ex_vol, name)
            if name and ex_sets:
                detail.append(
                    ExerciseFact(
                        name=str(name),
                        n_sets=ex_sets,
                        top_weight_lb=round(top[0]) if top else None,
                        reps=top[1] if top and top[1] else None,
                    )
                )
        duration = r.get("duration_sec")
        try:
            duration_min = int(round(float(duration) / 60)) if duration else None
        except (TypeError, ValueError):
            duration_min = None
        out.append(
            WorkoutFact(
                title=(r.get("workout_name") or r.get("title") or "Training"),
                n_exercises=len(exercises),
                n_sets=sets,
                volume_lbs=round(volume, 1),
                top_exercise=best[1],
                exercises=[e.get("name") or e.get("title") for e in exercises if (e.get("name") or e.get("title"))],
                duration_min=duration_min,
                detail=detail,
                n_working_sets=working,
            )
        )
    return out


def cycle_volume_max(table, start: str, end_exclusive: str) -> tuple[float, int]:
    """(heaviest session in lb moved, sessions counted) between genesis and the day BEFORE
    `end_exclusive`.

    For the session-volume milestone: a day is a personal best for this attempt when its
    volume beats every earlier session of the cycle. Read from the same hevy rows the
    cards draw from, never a hand-typed record. The count is what stops the third session
    of an attempt from being a "best".
    """
    days = _day_range(start, end_exclusive)[:-1]
    best, n = 0.0, 0
    for d in days:
        for w in _workout_facts(_query_prefix(table, "hevy", f"DATE#{d}")):
            if w.volume_lbs and float(w.volume_lbs) > 0:
                n += 1
                best = max(best, float(w.volume_lbs))
    return best, n


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
        facts.hrv_30d = computed.get("hrv_30d")
        facts.vice_streaks = {k: v for k, v in (computed.get("vice_streaks") or {}).items() if v}
        # The detail card (#3741, two cards a day): what the grade was scored FROM.
        details = computed.get("component_details") or {}
        nut = details.get("nutrition") or {}
        facts.calories = nut.get("calories")
        facts.cal_target = nut.get("cal_target")
        facts.carbs_g = nut.get("carbs_g")
        facts.fat_g = nut.get("fat_g")
        slp = details.get("sleep_quality") or {}
        facts.sleep_hrs = slp.get("duration_hrs")
        facts.sleep_score = slp.get("sleep_score")
        facts.recovery_pct = computed.get("recovery_pct")
        if facts.recovery_pct is None:
            facts.recovery_pct = (details.get("recovery") or {}).get("recovery_score")
        facts.rhr_bpm = computed.get("rhr_bpm")
        facts.steps = (details.get("movement") or {}).get("steps")
        hyd = details.get("hydration") or {}
        facts.water_oz = hyd.get("water_oz")
        facts.water_target_oz = hyd.get("target_oz")

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
        vt = habits.get("vices_total")
        facts.vices_total = int(vt) if vt is not None else None

    # Was the scale stepped on today? The withings row for the date is the fact; the
    # compute cron's `latest_weight` is a carry-forward and says nothing about the day.
    wrow = _get_day(table, "withings", date) or {}
    facts.weighed_today = wrow.get("weight_lbs") is not None or wrow.get("weight_kg") is not None

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
        # The source row outranks the compute cron's copy of it when both exist.
        if mf.get("total_calories_kcal") is not None:
            facts.calories = mf.get("total_calories_kcal")
        if facts.protein_g is None:
            facts.protein_g = mf.get("total_protein_g") or mf.get("protein_g")
        if facts.carbs_g is None:
            facts.carbs_g = mf.get("total_carbs_g")
        if facts.fat_g is None:
            facts.fat_g = mf.get("total_fat_g")
        facts.fiber_g = mf.get("total_fiber_g")
        facts.meals = mf.get("total_meals")
        facts.snacks = mf.get("total_snacks")

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


# ── the coach line: selected, never generated (#3749) ─────────────────────────
#: Which coach gets FIRST refusal on which beat. A serial whose voice never changes
#: reads as one voice with a template — the same complaint that produced `pick_beat`.
#:
#: This is a PREFERENCE, not a roster, and the distinction is the whole reason it is
#: shaped this way. The first draft here hand-typed all five or six ids per beat, and
#: `tests/test_coach_roster_set_guard_2334.py` was right to red it: the copy was already
#: wrong on the day it was written. It named `training_coach`, which is not an
#: operational coach and has never written an OUTPUT# row, and it omitted `glucose_coach`
#: and `explorer_coach`, which are. A hand-typed roster does not drift eventually; it
#: starts drifted and nobody looks.
#:
#: So the roster comes from `persona_registry.OPERATIONAL_COACH_IDS` and only the HEAD is
#: named here — one or two ids per beat, well under the guard's overlap threshold because
#: it is genuinely not a roster. A coach added to the platform tomorrow joins the card's
#: fallback order with no edit here.
#: ONE id per beat, and that is a rule rather than a coincidence: the conformance guard
#: (#2844) treats a two-string literal as an enumeration of registry vocabulary and a
#: one-string literal as a reference, which is exactly the right line here. The head is
#: "who this beat most wants to hear from"; everyone else is fallback in registry order.
CARD_COACH_HEAD: dict[str, str] = {
    "session": "physical_coach",
    "trajectory": "physical_coach",
    "scorecard": "mind_coach",
    "reckoning": "physical_coach",
}


def card_coach_order(beat: str = "") -> tuple:
    """The beat's head, then every other operational coach in registry order.

    Deterministic: `OPERATIONAL_COACH_IDS` is an ordered constant, so the same day and
    beat always resolve to the same coach, which is what makes "a different card every
    day" a property rather than a hope.
    """
    from coach import persona_registry

    lead = CARD_COACH_HEAD.get(beat)
    head = (lead,) if lead else ()
    return head + tuple(c for c in persona_registry.OPERATIONAL_COACH_IDS if c != lead)


#: The longest a drawn line may be. Three wrapped lines of mono at the card's content
#: width; past that the quote stops being a line and becomes a paragraph, which is the
#: one thing every layout note in `recap_layouts` says a card must not grow.
COACH_LINE_MAX_CHARS = 150

_SENTENCE_END = (". ", "! ", "? ")


def first_sentence(text: str, limit: int = COACH_LINE_MAX_CHARS) -> str:
    """The opening sentence of `text`, verbatim, or "" if there isn't a usable one.

    A `public_summary` is 120-180 words — a paragraph written for a web page, not a line
    for a card. Taking its first sentence keeps the operation SELECTION: the result is a
    contiguous prefix of something a coach actually wrote, with nothing added and nothing
    reordered. That distinction is the whole acceptance of #3749, so it is enforced by a
    test asserting the return value is a prefix of the input rather than by this comment.

    A first sentence longer than `limit` is cut at a word boundary with an ellipsis. It is
    still the coach's words; it is no longer the coach's whole thought, and the ellipsis is
    what says so on the card.
    """
    text = " ".join(str(text or "").split())
    if not text:
        return ""
    cut = len(text)
    for mark in _SENTENCE_END:
        i = text.find(mark)
        if i != -1 and i + 1 < cut:
            cut = i + 1
    sentence = text[:cut].strip()
    if len(sentence) <= limit:
        return sentence
    clipped = sentence[:limit].rsplit(" ", 1)[0].rstrip(" ,;:—-")
    return (clipped + "…") if clipped else ""


#: A sentence with any of these does not go on a card. Dates: the card already carries
#: one, and a quote opening "On the night of 2026-09-08" reads as a lab report and, worse,
#: is usually about a DIFFERENT day than the card's (coach summaries lag ingestion, and
#: the panel caught a Day 8 line contradicting Day 8's own detail card). Instruments and
#: ops words: a follower does not know what an EWMA is, and "the Garmin pause has created
#: a data blind spot" is a platform note leaking to an audience. Absence claims: they are
#: the ones most likely to be stale against the card's own blocks.
_SENTENCE_REJECT = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b"
    r"|\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(?:st|nd|rd|th)?\b"
    r"|\b(?:hrv|ewma|garmin|whoop|bpm|ms|acwr|z-score|sensor|sensors|data|journal|log|logged|ingest|pipeline|blind spot)\b"
    r"|\d+/10",
    re.IGNORECASE,
)
#: A sentence that opens by pointing back at the one before it ("That gap is…", "It's the
#: difference…", "Strip that meal…") is not a line, it is half of one. On a card there is
#: no sentence before it.
_SENTENCE_ANAPHORA = re.compile(
    r"^(?:that|this|these|those|it|it's|its|which|so|and|but|once|strip|more|less|the same|either|both|neither|also)\b"
    r"|\b(?:also|something else|as well|too)\b",
    re.IGNORECASE,
)
#: Two mono lines at the card's wrap width, uncut. A cut sentence is a broken render.
CARD_SENTENCE_MAX_CHARS = 100


def card_sentence(text: str, limit: int = CARD_SENTENCE_MAX_CHARS) -> str:
    """The first COMPLETE sentence of `text` that fits a card and passes the reject list.

    Still selection, never generation: the result is a verbatim sentence of something a
    coach wrote — contiguous, unedited, in its original order. What changed from
    `first_sentence` is only WHICH sentence: one that ends, fits two lines uncut, and
    says nothing a card cannot carry. Returns "" when no sentence qualifies, and the card
    draws no quote — nothing at all is just the card the day earned.
    """
    text = " ".join(str(text or "").split())
    if not text:
        return ""
    # Split only at a terminator followed by whitespace: a decimal point ("ratio of
    # 0.754") or an abbreviation is not the end of a thought, and the first cut of this
    # selector shipped "ratio of 0." as a quote.
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        sentence = sentence.strip()
        if not sentence or sentence[-1] not in ".!?" or len(sentence) > limit:
            continue
        if _SENTENCE_REJECT.search(sentence) or _SENTENCE_ANAPHORA.search(sentence):
            continue
        if len(sentence.split()) < 4:
            continue
        return sentence
    return ""


#: What `coach_line` is reporting when it hands back no line. Three outcomes that look
#: identical on the card and must never look identical in the record (#3768's lesson,
#: applied before it can bite rather than after): the platform genuinely had nothing to
#: quote, versus the read itself failed.
LINE_OK = "ok"
LINE_ABSENT = "absent"
LINE_UNREADABLE = "unreadable"


def coach_line(table, date: str, beat: str = "", *, coach_order=None) -> tuple:
    """(line, source_record_id, status) for one PT day — the first reader-safe line.

    `status` is the part worth explaining, and it exists because of #3768. There, a
    missing IAM grant made `bedrock:InvokeModel` raise, the caller caught it, wrote the
    deterministic fallback and reported success — for the entire life of the feature.
    Nothing distinguished "the model had nothing to add" from "the model was never
    reached", so a dark feature and a quiet day were the same observation.

    This function is one scope-tightening away from that. It queries `COACH#*`, which the
    recap role can read today only because its DynamoDB grant carries no `LeadingKeys`
    condition (verified against the DEPLOYED role, 2026-09-14, not the CDK source). The
    day someone scopes that read the way the WRITE is already scoped, every query here
    raises AccessDenied, this returns no line, and the card renders — correctly, quietly,
    and permanently without a coach voice.

    So the three outcomes are named and the picker record stores which one happened:

      * `ok`         — a line was found
      * `absent`     — every coach read cleanly and none had a reader-safe line. A real
                       day: the coach did not run, the ADR-104 grounding gate HELD the
                       condensation, or `audience_guard` rejected it at write time.
      * `unreadable` — at least one query raised. The card still renders without a quote,
                       because a missing quote is a smaller wrong than a missing card —
                       but it renders saying so.
    """
    from coach import audience_guard

    order = coach_order if coach_order is not None else card_coach_order(beat)
    failed = False
    for coach_id in order:
        rows, ok = _coach_outputs(table, coach_id, date)
        failed = failed or not ok
        for item in rows:
            blurb = audience_guard.public_blurb(item, limit=COACH_LINE_MAX_CHARS * 4)
            line = card_sentence(blurb)
            if line:
                return line, f"COACH#{coach_id}|{item.get('sk')}", LINE_OK
    return None, None, (LINE_UNREADABLE if failed else LINE_ABSENT)


def _coach_outputs(table, coach_id: str, date: str) -> tuple:
    """(rows, ok) — one coach's OUTPUT# rows for one date, and whether the read worked."""
    from boto3.dynamodb.conditions import Key

    try:
        # Through the phase filter like every other read here. An OUTPUT# row carries
        # `phase` and `cycle`, so a tombstoned row from a previous attempt can sit at
        # this very date; quoting it would put a previous cycle's coach on this cycle's
        # card — the cross-genesis mistake `trailing()` above exists to prevent, in a
        # second partition.
        kwargs = with_phase_filter({"KeyConditionExpression": Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with(f"OUTPUT#{date}#")})
        resp = table.query(**kwargs)
    except Exception as e:  # noqa: BLE001
        # The CLASS and message, never the row. #3768 spent months undiagnosable because
        # the swallowed exception was never logged at all — an AccessDenied, a throttle
        # and a healthy empty day were one observation.
        logger.warning("recap coach-line read failed for %s on %s: %s: %s", coach_id, date, type(e).__name__, e)
        return [], False
    return [d2f(i) for i in resp.get("Items", [])], True


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
