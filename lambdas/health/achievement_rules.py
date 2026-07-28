"""
achievement_rules.py — the ONE place badge thresholds live (#1624).

Before this module, `handle_achievements()` in lambdas/web/site_api_vitals.py held
the badge catalog inline AND computed `earned_date=today if <condition> else None`
for every badge. That made the achievements surface a nightly threshold snapshot
masquerading as an earned-badge record:

  1. No first-earn was ever recorded — the site could say a badge is true *now*,
     never *when* it was first earned.
  2. Badges un-earned. A 2-3 lb hydration swing flips `lost_10` off and back on;
     a broken-and-rebuilt streak does the same. A badge that water weight can
     take away is not a badge.

The fix is a writer/reader split:

  * The WRITER (lambdas/compute/daily_metrics_compute_lambda.py, 9:40 AM PT — the
    last compute in the daily chain, so the character sheet written at 9:35 is
    already fresh) evaluates these rules and persists a durable first-earn record
    per badge, ONCE, on first crossing. It is never updated afterwards.
  * The READER (site_api_vitals.handle_achievements) evaluates the SAME rules for
    the "true right now" signal and merges in the stored first-earn dates. It
    writes nothing — /api/achievements is a core data query, and per CLAUDE.md
    core data queries must never write. There is deliberately no lazy-persist on
    the serving path.

Both sides import BADGE_RULES and evaluate() from here. If the threshold logic
lived in two places the writer and the reader would drift, which is a subtler
version of the very bug this module exists to fix.

Honesty contract (ADR-104)
--------------------------
`earned_date` is NEVER manufactured. A badge that is true right now but has no
stored first-earn record yet renders as **earned with a null date** — that is
correct and honest, not a gap to paper over with today's date. Likewise the
backfill derives a first-earn date from stored history only where the history
actually supports one; where it does not, the record is written earned-but-undated
(`earned_date=None`, `date_basis="undetermined"`).

Phase taxonomy (ADR-077)
------------------------
The first-earn partition is `SOURCE#achievements`, classified EXPERIMENT_SCOPED —
see the rationale in lambdas/phase_taxonomy.py. In short: every badge condition is
evaluated over phase-filtered, current-cycle data (streak, level, completed
experiments and challenges all reset with the run), so a badge is a progress
artifact of the run that produced it. A cross-phase first-earn would claim an
earn whose supporting evidence the same endpoint has tombstoned and hidden — the
mirror image of the dishonesty this module removes.

v1.0.0 — 2026-07-21 (#1624)
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable, NamedTuple

# ── The first-earn ledger's DDB coordinates ───────────────────────────────────
ACHIEVEMENTS_SOURCE = "achievements"
FIRST_EARN_SK_PREFIX = "BADGE#"

# The partition, spelled out. Callers pass a `user_prefix` so the module stays
# user-agnostic, but the canonical pk is named here in full so the orphan-read
# guard (tests/test_site_partition_orphans.py, #1218) can see statically that
# SOURCE#achievements — which lambdas/web/site_api_vitals.py reads — has a writer.
ACHIEVEMENTS_PK = "USER#matthew#SOURCE#achievements"

# `date_basis` values on a stored first-earn record.
BASIS_OBSERVED = "observed"  # the writer watched the crossing happen on this run
BASIS_DERIVED = "derived"  # reconstructed from a stored dated series (backfill)
BASIS_UNDETERMINED = "undetermined"  # earned, but no honest date is derivable


# ── Comparators ───────────────────────────────────────────────────────────────
# Named so the writer, the reader and the backfill all cross a threshold the same
# way. `never` is the escape hatch for a badge gated on something outside this
# engine (hypothesis_confirmed needs manual statistical confirmation).
def _gte(value: Any, threshold: Any) -> bool:
    return value is not None and value >= threshold


def _lt(value: Any, threshold: Any) -> bool:
    return value is not None and value < threshold


def _is_true(value: Any, threshold: Any) -> bool:
    return bool(value)


def _never(value: Any, threshold: Any) -> bool:
    return False


COMPARATORS: dict[str, Callable[[Any, Any], bool]] = {
    "gte": _gte,
    "lt": _lt,
    "is_true": _is_true,
    "never": _never,
}


class BadgeRule(NamedTuple):
    """One badge: its identity, its threshold, and how it renders when locked."""

    id: str
    label: str
    category: str
    description: str
    signal: str  # key into the signals dict
    comparator: str  # key into COMPARATORS
    threshold: Any = None
    icon: str | None = None
    hint_kind: str | None = None  # None = never show an unlock hint
    hint_text: str | None = None  # for hint_kind="static"


# ── The catalog ───────────────────────────────────────────────────────────────
# Order is the wire order of /api/achievements — preserved exactly as it was
# inline in site_api_vitals so this refactor is byte-identical on the response.
BADGE_RULES: tuple[BadgeRule, ...] = (
    # ── Streak
    BadgeRule("week_warrior", "Week Warrior", "streak", "7-day Tier 0 habit streak", "current_streak", "gte", 7, hint_kind="days"),
    # #1126: fortnight rung between the week and the month — the first "this is
    # a pattern, not a good week" mark.
    BadgeRule("fortnight", "Fortnight", "streak", "14-day Tier 0 habit streak", "current_streak", "gte", 14, hint_kind="days"),
    BadgeRule("monthly_grind", "Monthly Grind", "streak", "30-day Tier 0 habit streak", "current_streak", "gte", 30, hint_kind="days"),
    BadgeRule("quarterly", "Quarterly", "streak", "90-day Tier 0 habit streak", "current_streak", "gte", 90, hint_kind="days"),
    # #1126: the long hold — half a year without dropping the Tier 0 floor.
    BadgeRule("half_year_hold", "Half-Year Hold", "streak", "180-day Tier 0 habit streak", "current_streak", "gte", 180, hint_kind="days"),
    # ── Level
    BadgeRule("first_level_up", "First Level Up", "level", "Reached Character Level 2", "current_level", "gte", 2),
    BadgeRule("apprentice", "Apprentice", "level", "Reached Character Level 5", "current_level", "gte", 5, hint_kind="level"),
    BadgeRule("journeyman", "Journeyman", "level", "Reached Character Level 10", "current_level", "gte", 10, hint_kind="level"),
    # #1126: the ladder above Journeyman — the streak-gated engine makes these rare.
    BadgeRule("adept", "Adept", "level", "Reached Character Level 20", "current_level", "gte", 20, hint_kind="level"),
    BadgeRule(
        "master_of_the_craft", "Master of the Craft", "level", "Reached Character Level 40", "current_level", "gte", 40, hint_kind="level"
    ),
    # ── Weight LOSS milestones (every 10 lbs)
    # #1126: the first honest rung — 5 lbs is real motion, not noise, on this frame.
    BadgeRule("lost_5", "First Five", "milestone", "Lost 5 lbs from starting weight", "lost_lbs", "gte", 5, hint_kind="lbs_to_go"),
    BadgeRule("lost_10", "Lost 10 lbs", "milestone", "Lost 10 lbs from starting weight", "lost_lbs", "gte", 10, "⚖️", "lbs_to_go"),
    BadgeRule("lost_20", "Lost 20 lbs", "milestone", "Lost 20 lbs from starting weight", "lost_lbs", "gte", 20, "⚖️", "lbs_to_go"),
    BadgeRule("lost_30", "Lost 30 lbs", "milestone", "Lost 30 lbs from starting weight", "lost_lbs", "gte", 30, "⚖️", "lbs_to_go"),
    BadgeRule("lost_40", "Lost 40 lbs", "milestone", "Lost 40 lbs from starting weight", "lost_lbs", "gte", 40, "⚖️", "lbs_to_go"),
    BadgeRule("lost_50", "Lost 50 lbs", "milestone", "Lost 50 lbs from starting weight", "lost_lbs", "gte", 50, "⚖️", "lbs_to_go"),
    BadgeRule("lost_60", "Lost 60 lbs", "milestone", "Lost 60 lbs from starting weight", "lost_lbs", "gte", 60, "⚖️", "lbs_to_go"),
    BadgeRule("lost_70", "Lost 70 lbs", "milestone", "Lost 70 lbs from starting weight", "lost_lbs", "gte", 70, "⚖️", "lbs_to_go"),
    BadgeRule("lost_80", "Lost 80 lbs", "milestone", "Lost 80 lbs from starting weight", "lost_lbs", "gte", 80, "⚖️", "lbs_to_go"),
    BadgeRule("lost_90", "Lost 90 lbs", "milestone", "Lost 90 lbs from starting weight", "lost_lbs", "gte", 90, "⚖️", "lbs_to_go"),
    BadgeRule("lost_100", "Lost 100 lbs", "milestone", "Lost 100 lbs from starting weight", "lost_lbs", "gte", 100, "⚖️", "lbs_to_go"),
    # ── Weight TARGET milestones
    BadgeRule("sub_280", "Sub-280", "milestone", "Weight under 280 lbs", "current_weight", "lt", 280, "\U0001f3af", "lbs_under"),
    BadgeRule("sub_250", "Sub-250", "milestone", "Weight under 250 lbs", "current_weight", "lt", 250, "\U0001f3af", "lbs_under"),
    BadgeRule("sub_220", "Sub-220", "milestone", "Weight under 220 lbs", "current_weight", "lt", 220, "\U0001f3af", "lbs_under"),
    BadgeRule("sub_200", "Sub-200", "milestone", "Weight under 200 lbs", "current_weight", "lt", 200, "\U0001f3af", "lbs_under"),
    # ── Data
    # #1126: the first data-consistency rung under the existing 100/365 ladder.
    BadgeRule("30_days", "Month of Data", "data", "30+ days of habit logging", "days_tracked", "gte", 30, hint_kind="days"),
    BadgeRule("100_days", "100 Days Tracked", "data", "100+ days of habit logging", "days_tracked", "gte", 100, hint_kind="days"),
    BadgeRule("365_days", "Year of Data", "data", "365 days of habit logging", "days_tracked", "gte", 365, hint_kind="days"),
    # ── Experiment
    BadgeRule("first_experiment", "First Experiment", "science", "Completed first N=1 experiment", "completed_exps", "gte", 1),
    BadgeRule(
        "hypothesis_confirmed",
        "Hypothesis Confirmed",
        "science",
        "N=1 result statistically validated",
        "hypothesis_confirmed",
        "never",
        hint_kind="static",
        hint_text="Complete a tracked experiment to unlock",  # requires manual confirmation
    ),
    # EL-21: Experiment evolution badges
    BadgeRule("exp_3_completed", "Lab Rat", "science", "Completed 3 experiments", "completed_exps", "gte", 3, hint_kind="experiments"),
    BadgeRule(
        "exp_5_completed", "Research Fellow", "science", "Completed 5 experiments", "completed_exps", "gte", 5, hint_kind="experiments"
    ),
    BadgeRule(
        "exp_10_completed",
        "Principal Investigator",
        "science",
        "Completed 10 experiments",
        "completed_exps",
        "gte",
        10,
        hint_kind="experiments",
    ),
    BadgeRule(
        "exp_streak_3",
        "Hot Streak",
        "science",
        "3 consecutive completed experiments (no fails)",
        "exp_streak_3",
        "is_true",
        hint_kind="static",
        hint_text="Complete 3 experiments in a row without abandoning",
    ),
    BadgeRule(
        "exp_all_pillars",
        "Renaissance Man",
        "science",
        "Completed experiment in every pillar",
        "exp_all_pillars",
        "is_true",
        hint_kind="static",
        hint_text="Complete at least one experiment in each of the 7 pillars",
    ),
    # ── Challenges
    BadgeRule("first_challenge", "First Challenge", "challenge", "Completed first challenge", "completed_challenges", "gte", 1),
    BadgeRule(
        "five_challenges",
        "Challenge Regular",
        "challenge",
        "Completed 5 challenges",
        "completed_challenges",
        "gte",
        5,
        hint_kind="challenges",
    ),
    BadgeRule(
        "ten_challenges",
        "Challenge Veteran",
        "challenge",
        "Completed 10 challenges",
        "completed_challenges",
        "gte",
        10,
        hint_kind="challenges",
    ),
    BadgeRule(
        "twenty_five_challenges",
        "Challenge Legend",
        "challenge",
        "Completed 25 challenges",
        "completed_challenges",
        "gte",
        25,
        hint_kind="challenges",
    ),
    BadgeRule(
        "perfect_challenge",
        "Flawless",
        "challenge",
        "Completed a challenge with 100% success rate (7+ days)",
        "perfect_challenges",
        "gte",
        1,
        hint_kind="static",
        hint_text="Complete a 7+ day challenge without missing a single day",
    ),
)

BADGE_IDS: tuple[str, ...] = tuple(r.id for r in BADGE_RULES)
RULES_BY_ID: dict[str, BadgeRule] = {r.id: r for r in BADGE_RULES}

# Signals for which a dated history series can be reconstructed from stored data,
# and therefore for which a first-earn date is DERIVABLE at backfill time. Every
# other signal (the booleans, and the challenge counters whose records carry no
# reliable completion timestamp) yields an earned-but-undated record instead of
# an invented date.
DERIVABLE_SIGNALS = frozenset({"current_streak", "days_tracked", "current_level", "lost_lbs", "current_weight", "completed_exps"})


def evaluate(signals: dict) -> dict[str, bool]:
    """Is each badge's condition true RIGHT NOW, given the signals?

    This is the whole of the threshold logic. The writer calls it to detect a
    first crossing; the reader calls it for the live condition. Neither one
    re-implements a comparison.
    """
    return {rule.id: COMPARATORS[rule.comparator](signals.get(rule.signal), rule.threshold) for rule in BADGE_RULES}


def unlock_hint(rule: BadgeRule, signals: dict, earned: bool) -> str | None:
    """The locked-state nudge, rendered exactly as it was inline in site_api_vitals.

    `static` hints are unconditional by design — the four badges that use one show
    it whether or not the badge is earned, which is the pre-existing behaviour.
    """
    kind = rule.hint_kind
    if kind is None:
        return None
    if kind == "static":
        return rule.hint_text
    if earned:
        return None
    value = signals.get(rule.signal)
    if value is None:
        return None
    if kind == "days":
        return f"{max(0, rule.threshold - value)} days to unlock"
    if kind == "level":
        return f"Level {value} → Level {rule.threshold} needed"
    if kind == "lbs_to_go":
        return f"{rule.threshold - value:.0f} lbs to go"
    if kind == "lbs_under":
        return f"{value - rule.threshold:.0f} lbs to go"
    if kind == "experiments":
        return f"{max(0, rule.threshold - value)} experiments to unlock"
    if kind == "challenges":
        return f"{max(0, rule.threshold - value)} challenges to unlock"
    return None


def render(signals: dict, first_earns: dict[str, dict]) -> list[dict]:
    """Build the /api/achievements badge list.

    `first_earns` maps badge id -> the stored first-earn record (or is missing the
    key entirely if no record exists yet).

    The two rules that make a badge a badge:
      * **A stored first-earn wins.** `earned = bool(record) or condition_now` —
        once recorded, the badge cannot un-earn when the underlying metric dips
        back below the threshold. Water weight cannot take a badge away.
      * **The date is never manufactured.** `earned_date` comes from the record or
        is None. A badge true-now with no record yet is earned with a null date;
        a badge recorded as earned-but-undated stays undated forever (ADR-104).
    """
    now_true = evaluate(signals)
    out = []
    for rule in BADGE_RULES:
        record = first_earns.get(rule.id)
        earned = bool(record) or now_true[rule.id]
        out.append(
            {
                "id": rule.id,
                "label": rule.label,
                "category": rule.category,
                "description": rule.description,
                "earned": earned,
                "earned_date": (record or {}).get("earned_date"),
                "icon": rule.icon,
                "unlock_hint": unlock_hint(rule, signals, earned),
            }
        )
    return out


# ── The first-earn ledger ─────────────────────────────────────────────────────


def read_first_earns(table, user_prefix: str, phase_filter=None) -> dict[str, dict]:
    """Load the stored first-earn records, keyed by badge id.

    `phase_filter` is with_phase_filter (injected so this module stays importable
    without the lambda bundle on the path). A record whose badge id is no longer
    in the catalog is ignored rather than served.
    """
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :sk)",
        "ExpressionAttributeValues": {":pk": user_prefix + ACHIEVEMENTS_SOURCE, ":sk": FIRST_EARN_SK_PREFIX},
    }
    if phase_filter is not None:
        kwargs = phase_filter(kwargs)
    items = table.query(**kwargs).get("Items", [])
    out: dict[str, dict] = {}
    for item in items:
        badge_id = item.get("badge_id") or str(item.get("sk", "")).replace(FIRST_EARN_SK_PREFIX, "")
        if badge_id in RULES_BY_ID:
            out[badge_id] = {
                "earned_date": item.get("earned_date") or None,
                "date_basis": item.get("date_basis") or BASIS_UNDETERMINED,
            }
    return out


def _f(value, default=None):
    """Decimal/None-tolerant float coercion — DDB hands back Decimal."""
    if value is None:
        return default
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _date_of(item) -> str | None:
    sk = str(item.get("sk") or "")
    return sk.removeprefix("DATE#") if sk.startswith("DATE#") else None


def _query_all(table, phase_filter, **kwargs) -> list[dict]:
    """Paginated query with the phase filter applied (ADR-058)."""
    if phase_filter is not None:
        kwargs = phase_filter(kwargs)
    items: list[dict] = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            return items
        kwargs = dict(kwargs, ExclusiveStartKey=last)


def collect_inputs(table, user_prefix: str, phase_filter, start_weight_lbs: float, today: str, window_start: str) -> dict:
    """Fetch every partition the badge engine reads, ONCE.

    Both `signals_from()` (the live condition) and `histories_from()` (the backfill's
    dated series) derive from this single fetch, so the writer and the reader can
    never disagree about what the underlying data said.

    `window_start` is the 365-day lower bound for the days-tracked count, matching
    the pre-existing handle_achievements behaviour.
    """
    habits = _query_all(
        table,
        phase_filter,
        KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
        ExpressionAttributeValues={":pk": user_prefix + "habit_scores", ":s": f"DATE#{window_start}", ":e": f"DATE#{today}"},
    )
    chars = _query_all(
        table,
        phase_filter,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :sk)",
        ExpressionAttributeValues={":pk": user_prefix + "character_sheet", ":sk": "DATE#"},
    )
    weights = _query_all(
        table,
        phase_filter,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :sk)",
        ExpressionAttributeValues={":pk": user_prefix + "withings", ":sk": "DATE#"},
    )
    exps = _query_all(
        table,
        phase_filter,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :sk)",
        ExpressionAttributeValues={":pk": user_prefix + "experiments", ":sk": "EXP#"},
    )
    challenges = _query_all(
        table,
        phase_filter,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :sk)",
        ExpressionAttributeValues={":pk": user_prefix + "challenges", ":sk": "CHALLENGE#"},
    )
    return {
        "habits": sorted(habits, key=lambda i: str(i.get("sk") or "")),
        "chars": sorted(chars, key=lambda i: str(i.get("sk") or "")),
        "weights": sorted(weights, key=lambda i: str(i.get("sk") or "")),
        "experiments": exps,
        "challenges": challenges,
        "start_weight_lbs": float(start_weight_lbs),
    }


def _streak_of(item) -> int:
    return int(_f(item.get("t0_perfect_streak")) or _f(item.get("t0_aggregate_streak")) or 0)


def _completed_challenge_stats(challenges: list[dict]) -> tuple[int, int]:
    completed = 0
    perfect = 0
    for ch in challenges:
        if ch.get("status") != "completed":
            continue
        completed += 1
        checkins = ch.get("daily_checkins") or []
        if checkins and all(c.get("completed") for c in checkins):
            perfect += 1
    return completed, perfect


_ALL_PILLARS = frozenset({"sleep", "movement", "nutrition", "supplements", "mental", "social", "discipline"})


def signals_from(inputs: dict) -> dict:
    """The live signal values — exactly what handle_achievements used to compute inline."""
    habits = inputs["habits"]
    chars = inputs["chars"]
    weights = inputs["weights"]
    exps = inputs["experiments"]

    current_streak = _streak_of(habits[-1]) if habits else 0
    days_tracked = len(habits)
    current_level = int(_f((chars[-1] if chars else {}).get("character_level"), 1) or 1)
    current_weight = _f((weights[-1] if weights else {}).get("weight_lbs"), 999.0)
    start_weight = inputs["start_weight_lbs"]
    lost_lbs = round(start_weight - current_weight, 1) if current_weight < start_weight else 0

    completed = [e for e in exps if e.get("status") in ("completed", "confirmed")]
    finished = sorted(
        [e for e in exps if e.get("status") in ("completed", "confirmed", "abandoned")],
        key=lambda x: str(x.get("end_date") or x.get("start_date") or ""),
        reverse=True,
    )
    exp_streak_3 = len(finished) >= 3 and all(e.get("status") in ("completed", "confirmed") for e in finished[:3])

    covered: set[str] = set()
    for e in completed:
        for tag in e.get("tags") or []:
            for p in _ALL_PILLARS:
                if p in str(tag).lower():
                    covered.add(p)

    completed_challenges, perfect_challenges = _completed_challenge_stats(inputs["challenges"])
    return {
        "current_streak": current_streak,
        "days_tracked": days_tracked,
        "current_level": current_level,
        "current_weight": current_weight,
        "lost_lbs": lost_lbs,
        "completed_exps": len(completed),
        "exp_streak_3": exp_streak_3,
        "exp_all_pillars": covered >= set(_ALL_PILLARS),
        "completed_challenges": completed_challenges,
        "perfect_challenges": perfect_challenges,
        "hypothesis_confirmed": False,
    }


def histories_from(inputs: dict) -> dict[str, list[tuple[str, Any]]]:
    """Dated (date, value) series for the DERIVABLE signals — the backfill's evidence.

    Only signals in DERIVABLE_SIGNALS appear here, and only where the stored data
    actually carries a date. Everything else is deliberately absent so the backfill
    records earned-but-undated rather than inventing a crossing date:

      * `exp_streak_3` / `exp_all_pillars` — the value at a past date depends on the
        full ordering of a set-cover, which the stored records do not pin down.
      * `completed_challenges` / `perfect_challenges` — challenge records carry a
        `completed_at` that is written empty on creation and is not reliably
        populated on completion, so a count-crossing date cannot be honestly dated.
      * `hypothesis_confirmed` — never earned by this engine.
    """
    out: dict[str, list[tuple[str, Any]]] = {}

    streaks = [(_date_of(h), _streak_of(h)) for h in inputs["habits"]]
    out["current_streak"] = [(d, v) for d, v in streaks if d]

    # days_tracked is cumulative: the Nth habit record's date is when the count hit N.
    dated_habits = [d for d in (_date_of(h) for h in inputs["habits"]) if d]
    out["days_tracked"] = [(d, i + 1) for i, d in enumerate(dated_habits)]

    levels = [(_date_of(c), int(_f(c.get("character_level"), 1) or 1)) for c in inputs["chars"]]
    out["current_level"] = [(d, v) for d, v in levels if d]

    start_weight = inputs["start_weight_lbs"]
    weight_series: list[tuple[str, Any]] = []
    for w in inputs["weights"]:
        wd, wv = _date_of(w), _f(w.get("weight_lbs"))
        if wd and wv is not None:
            weight_series.append((wd, wv))
    out["current_weight"] = weight_series
    out["lost_lbs"] = [(d, round(start_weight - v, 1) if v < start_weight else 0) for d, v in weight_series]

    # Completed experiments, cumulative by end_date. An experiment with no end_date
    # cannot be placed in time, so it contributes to the count but not to the series.
    ends = sorted(
        str(e.get("end_date") or "") for e in inputs["experiments"] if e.get("status") in ("completed", "confirmed") and e.get("end_date")
    )
    out["completed_exps"] = [(d, i + 1) for i, d in enumerate(ends)]
    return out


def derive_first_earn_date(rule: BadgeRule, histories: dict[str, list[tuple[str, Any]]]) -> str | None:
    """The EARLIEST date on which this rule's threshold was met, from stored history.

    Returns None when no honest date is derivable — the caller must then record the
    badge as earned-but-undated rather than stamping it with today (ADR-104).
    """
    if rule.signal not in DERIVABLE_SIGNALS:
        return None
    series = histories.get(rule.signal) or []
    compare = COMPARATORS[rule.comparator]
    for date_str, value in sorted(series):
        if compare(value, rule.threshold):
            return date_str
    return None


def persist_first_earns(
    table, user_prefix: str, signals: dict, histories: dict, existing: dict[str, dict], today: str, stamp=None
) -> list[dict]:
    """Write a first-earn record for every badge that is earned and not yet recorded.

    Write-once WITHIN A CYCLE, by construction and by contract:
      * only badges absent from `existing` (a phase-filtered read) are considered, and
      * the put is conditional, so a concurrent or repeated run in the same cycle can
        never overwrite a first-earn that already landed.

    A live record is NEVER updated after it is written — that is the whole point. If
    the metric later dips back under the threshold the record stands, and the badge
    stays earned.

    The one deliberate exception is a TOMBSTONED record. The restart wipe tombstones
    in place (Interpretation B — UpdateItem adds tombstone=true on the SAME pk/sk; it
    does not move the item), so a bare `attribute_not_exists(sk)` would refuse to
    write for the rest of the platform's life after the first reset: the phase filter
    hides the archived record, so `existing` is empty and the badge looks unrecorded,
    but the key is occupied. Every badge would then serve earned-with-a-null-date
    forever. Hence `attribute_not_exists(sk) OR attribute_exists(tombstone)` — a live
    record is immutable, an archived one is superseded by the new cycle's.

    Superseding the archived record loses nothing irrecoverable: a first-earn is a
    DERIVED artifact, and its inputs (withings, habit_scores) are RAW_TIMESERIES,
    kept forever, so any prior cycle's crossing dates can be recomputed from source.

    Returns the records written (for logging/tests).
    """
    now_true = evaluate(signals)
    written = []
    for rule in BADGE_RULES:
        if rule.id in existing or not now_true[rule.id]:
            continue
        derived = derive_first_earn_date(rule, histories)
        earned_date = derived or None
        basis = BASIS_DERIVED if derived else BASIS_UNDETERMINED
        # A crossing the writer watches happen today is `observed`, not `derived` —
        # but only when the history genuinely shows it first became true today.
        if derived == today:
            basis = BASIS_OBSERVED
        item = {
            "sk": FIRST_EARN_SK_PREFIX + rule.id,
            "badge_id": rule.id,
            "label": rule.label,
            "category": rule.category,
            "earned_date": earned_date,
            "date_basis": basis,
            "recorded_at": today,
        }
        if stamp:
            item.update(stamp)
        try:
            # pk literal inline for the orphan gate (#1218): "…SOURCE#achievements".
            table.put_item(
                Item={"pk": user_prefix + "achievements", **item},
                ConditionExpression="attribute_not_exists(sk) OR attribute_exists(tombstone)",
            )
            written.append(dict(item, pk=user_prefix + "achievements"))
        except Exception as exc:  # noqa: BLE001 — ConditionalCheckFailed = already recorded, which is success
            if "ConditionalCheckFailed" not in type(exc).__name__ and "ConditionalCheckFailed" not in str(exc):
                raise
    return written
