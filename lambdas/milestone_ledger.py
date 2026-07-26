"""
milestone_ledger.py — the durable MILESTONE# event ledger (#1626).

The governing rule: **a rung crossed is a rung consumed, forever.** No un-fire,
no re-fire. This module is the ONE writer of `SOURCE#milestones`; every consumer
(the private digest first, #1628) reads the ledger and never re-derives "a
milestone happened" from a live threshold comparison — that memoryless pattern
is the `handle_achievements` bug story this ledger exists to end (contrast
lambdas/web/site_api_vitals.py:handle_achievements, which recomputes a nightly
snapshot with no memory of when anything first became true).

The item class
--------------
  pk  USER#matthew#SOURCE#milestones
  sk  MILESTONE#<milestone_id>          — one item per rung, forever
  sk  LEDGER#genesis                    — the one-time ledger-genesis marker

Every write is a conditional put (`attribute_not_exists(sk)`), so re-evaluation
is idempotent by construction: an existing entry can never be mutated or
deleted by this module — there is deliberately NO update path and NO delete
path. Unlike the #1624 badge ledger there is no tombstone escape hatch either:
the partition is CROSS_PHASE (see phase_taxonomy.py), the restart wipe never
touches it, so a bare attribute_not_exists is exactly the immutability wanted.

Semantics (the acceptance criteria, in order)
---------------------------------------------
1. **Write-once on first crossing.** A rung fires at most once in the life of
   the platform. Recorded entries are immutable.
2. **Weight rungs fire on the trailing 7-day mean** (never a single weigh-in),
   and only when the window holds >= 3 weigh-ins. The stored event carries the
   window, the n, and the mean, so any consumer can render the claim with its
   uncertainty (ADR-105 rule 1).
3. **Global cooldown across ALL categories combined** (GLOBAL_COOLDOWN_DAYS,
   set inside the issue's 10-14 day band): after ANY announced event, nothing
   else announces until the cooldown expires. A rung that trips during the
   cooldown is deferred, not consumed — it announces on a later evaluation,
   provided its condition still holds then (an event must never assert
   something that is no longer true on its own event_date).
4. **Permanent hysteresis.** Once recorded, driving the metric back and forth
   across the threshold can never produce a second event — enforced by the
   existing-entry check AND the conditional put.
5. **Reset behaviour is deliberate**: SOURCE#milestones is CROSS_PHASE
   (registered in lambdas/phase_taxonomy.py with the reasoning). An event is a
   dated past FACT, not a present-state claim; it survives every experiment
   reset, which is precisely what keeps a rung from re-announcing in cycle N+1.
   Ledger reads therefore take NO phase filter.

Ledger genesis (honesty at bootstrap, ADR-104)
----------------------------------------------
On the first-ever run the ledger records every rung that is ALREADY satisfied
as a `baseline` entry: announce=False, event_date=None. Those crossings
happened before the ledger existed, so no honest event date exists — and
drip-announcing years-old history as fresh news would be exactly the kind of
claim this platform refuses to make. Baseline entries still consume their
rungs permanently. The `LEDGER#genesis` marker makes the bootstrap a one-time
state, not an inference from emptiness (an empty ledger after genesis means
"nothing satisfied yet", which must not re-trigger a baseline sweep later).

Ladder subsumption
------------------
If two rungs of the SAME ladder are first satisfied together (e.g. a data gap
ends with the trailing mean already below both 250 and 240), the deepest rung
is the announced event and the shallower ones are written announce=False with
`subsumed_by` — consumed forever, but never announced AFTER a greater rung,
which would read as the instrument retracting its own arithmetic.

The writer runs from daily-metrics-compute (the existing daily compute chain,
after the achievements sweep) — no new Lambda, no new IAM surface.

v1.0.0 — 2026-07-25 (#1626)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, NamedTuple

# ── DDB coordinates ───────────────────────────────────────────────────────────
MILESTONES_SOURCE = "milestones"
EVENT_SK_PREFIX = "MILESTONE#"
GENESIS_SK = "LEDGER#genesis"

# The partition, spelled out in full (single-writer / orphan-guard visibility,
# same convention as achievement_rules.ACHIEVEMENTS_PK).
MILESTONES_PK = "USER#matthew#SOURCE#milestones"

# ── Tunables (the ACs pin the bands; the exact values live ONLY here) ─────────
# Global announcement cooldown across ALL categories combined. The issue bands
# it at 10-14 days ("anything that fires weekly is not a milestone"); 12 is the
# midpoint. One announced event, then silence until this many days have passed.
GLOBAL_COOLDOWN_DAYS = 12

# Weight rungs fire on the trailing mean over this many calendar days (ending
# on the evaluation date, inclusive), and only when the window holds at least
# WEIGHT_MIN_WEIGHINS actual weigh-ins — a single scale reading can never fire
# a milestone, however far below the threshold it lands.
WEIGHT_WINDOW_DAYS = 7
WEIGHT_MIN_WEIGHINS = 3

# `origin` values on a stored entry.
ORIGIN_CROSSING = "crossing"  # the writer watched the rung cross while the ledger was live
ORIGIN_BASELINE = "baseline"  # already true at ledger genesis — consumed, never announced

# Rule kinds.
KIND_WEIGHT_MEAN_UNDER = "weight_mean_under"  # trailing WEIGHT_WINDOW_DAYS-day mean < threshold
KIND_COUNT_GTE = "count_gte"  # integer signal >= threshold


class MilestoneRule(NamedTuple):
    """One rung: identity, category ladder, condition, and ladder depth."""

    id: str
    label: str
    category: str
    description: str
    kind: str
    signal: str  # key into the signals dict (count rules) / "weight_series" (weight rules)
    threshold: int
    depth: int  # position in its ladder; higher = deeper (more significant)


def _weight_rules() -> tuple[MilestoneRule, ...]:
    # Absolute rungs, every 10 lbs. Deliberately NOT "lost X from starting
    # weight": the starting weight is re-anchored at every experiment reset,
    # so a relative rung is not a lifetime fact — an absolute one is.
    rungs = tuple(range(340, 170, -10))  # 340, 330, …, 180
    return tuple(
        MilestoneRule(
            id=f"weight_sub_{t}",
            label=f"Sub-{t}",
            category="weight",
            description=f"Trailing {WEIGHT_WINDOW_DAYS}-day mean weight under {t} lbs",
            kind=KIND_WEIGHT_MEAN_UNDER,
            signal="weight_series",
            threshold=t,
            depth=depth,
        )
        for depth, t in enumerate(rungs)
    )


def _count_ladder(category: str, signal: str, rungs: tuple[int, ...], label_fmt: str, desc_fmt: str) -> tuple[MilestoneRule, ...]:
    return tuple(
        MilestoneRule(
            id=f"{category}_{t}",
            label=label_fmt.format(t),
            category=category,
            description=desc_fmt.format(t),
            kind=KIND_COUNT_GTE,
            signal=signal,
            threshold=t,
            depth=depth,
        )
        for depth, t in enumerate(rungs)
    )


MILESTONE_RULES: tuple[MilestoneRule, ...] = (
    _weight_rules()
    + _count_ladder("streak", "tier0_streak", (7, 14, 30, 90, 180, 365), "{}-Day Streak", "Tier 0 habit streak reached {} days")
    # days_tracked is counted over a 365-day window (matching the achievements
    # engine) — no rung above 365 can ever fire, so none is defined.
    + _count_ladder("days_tracked", "days_tracked", (30, 100, 365), "{} Days Tracked", "{} days of habit logging")
    + _count_ladder("level", "character_level", (2, 5, 10, 20, 40), "Level {}", "Reached character level {}")
)

MILESTONE_IDS: tuple[str, ...] = tuple(r.id for r in MILESTONE_RULES)
RULES_BY_ID: dict[str, MilestoneRule] = {r.id: r for r in MILESTONE_RULES}

# When rungs from several categories are eligible on the same run, exactly one
# announces — chosen by this order. Weight first: it is the platform's flagship
# public metric; the others are supporting ladders.
CATEGORY_PRIORITY: tuple[str, ...] = ("weight", "streak", "days_tracked", "level")


# ── Condition evaluation ──────────────────────────────────────────────────────


def trailing_weight_mean(weight_series: list[tuple[str, float]], today: str) -> dict | None:
    """Mean of weigh-ins in the trailing WEIGHT_WINDOW_DAYS-day window ending `today`.

    Returns {window_start, window_end, window_days, n, mean_lbs} or None when the
    window holds fewer than WEIGHT_MIN_WEIGHINS weigh-ins — under-sampled windows
    make no claims (ADR-105).
    """
    end = datetime.strptime(today, "%Y-%m-%d")
    start = (end - timedelta(days=WEIGHT_WINDOW_DAYS - 1)).strftime("%Y-%m-%d")
    vals = [float(v) for d, v in weight_series if v is not None and start <= d <= today]
    if len(vals) < WEIGHT_MIN_WEIGHINS:
        return None
    return {
        "window_start": start,
        "window_end": today,
        "window_days": WEIGHT_WINDOW_DAYS,
        "n": len(vals),
        "mean_lbs": round(sum(vals) / len(vals), 1),
    }


def _satisfied(rule: MilestoneRule, signals: dict, today: str) -> tuple[bool, dict | None]:
    """Is the rung's condition met right now — and on what evidence?

    The measurement dict is stored verbatim on the event so a consumer can render
    the claim with its uncertainty (window + n + mean for weight; value for counts).
    """
    if rule.kind == KIND_WEIGHT_MEAN_UNDER:
        window = trailing_weight_mean(signals.get("weight_series") or [], today)
        if window is None:
            return False, None
        meas = dict(window, threshold_lbs=rule.threshold)
        return window["mean_lbs"] < rule.threshold, meas
    value = signals.get(rule.signal)
    if value is None:
        return False, None
    return int(value) >= rule.threshold, {"value": int(value), "threshold": rule.threshold}


def _days_between(earlier: str, later: str) -> int:
    return (datetime.strptime(later, "%Y-%m-%d") - datetime.strptime(earlier, "%Y-%m-%d")).days


def _entry(rule: MilestoneRule, measurement: dict, today: str, *, announce: bool, origin: str, subsumed_by: str | None = None) -> dict:
    entry = {
        "sk": EVENT_SK_PREFIX + rule.id,
        "milestone_id": rule.id,
        "label": rule.label,
        "category": rule.category,
        "description": rule.description,
        # ADR-104: event_date is the evaluation date the crossing was CONFIRMED on
        # (the measurement window ends that day). A baseline entry has no honest
        # event date — the crossing predates the ledger — so it carries None.
        "event_date": today if origin == ORIGIN_CROSSING else None,
        "announce": announce,
        "origin": origin,
        "measurement": measurement,
        "recorded_at": today,
    }
    if subsumed_by:
        entry["subsumed_by"] = subsumed_by
    return entry


def evaluate(signals: dict, existing_ids: set[str], last_event_date: str | None, today: str) -> dict:
    """Pure decision function: what (if anything) does this run write?

    Returns {"to_write": [entry, …], "cooldown_active": bool, "deferred": [id, …]}.
    to_write holds at most ONE announced entry (plus same-ladder subsumed
    siblings); deferred lists satisfied-but-not-written rungs (cooldown, or a
    lower-priority category this run) — they stay unconsumed and re-evaluate later.
    """
    satisfied: list[tuple[MilestoneRule, dict]] = []
    for rule in MILESTONE_RULES:
        if rule.id in existing_ids:
            continue  # a rung crossed is a rung consumed, forever
        ok, meas = _satisfied(rule, signals, today)
        if ok:
            satisfied.append((rule, meas))

    cooldown_active = last_event_date is not None and _days_between(last_event_date, today) < GLOBAL_COOLDOWN_DAYS
    if cooldown_active or not satisfied:
        return {"to_write": [], "cooldown_active": cooldown_active, "deferred": [r.id for r, _ in satisfied]}

    by_category: dict[str, list[tuple[MilestoneRule, dict]]] = {}
    for rule, meas in satisfied:
        by_category.setdefault(rule.category, []).append((rule, meas))

    category = next(c for c in CATEGORY_PRIORITY if c in by_category)
    ladder = sorted(by_category[category], key=lambda rm: rm[0].depth, reverse=True)
    champion, champion_meas = ladder[0]
    to_write = [_entry(champion, champion_meas, today, announce=True, origin=ORIGIN_CROSSING)]
    for rule, meas in ladder[1:]:
        # Same-ladder siblings crossed by the same motion: consumed with the same
        # event, never announced after their greater rung.
        to_write.append(_entry(rule, meas, today, announce=False, origin=ORIGIN_CROSSING, subsumed_by=champion.id))
    deferred = [r.id for r, _ in satisfied if r.category != category]
    return {"to_write": to_write, "cooldown_active": False, "deferred": deferred}


# ── DDB I/O ───────────────────────────────────────────────────────────────────


def _dec(obj):
    """Decimal-safe deep copy — boto3 rejects Python floats."""
    if isinstance(obj, list):
        return [_dec(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _dec(v) for k, v in obj.items()}
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return Decimal(str(obj))
    return obj


def read_ledger(table, user_prefix: str) -> dict:
    """The whole partition, in one paginated pk-only query.

    Deliberately NO phase filter: SOURCE#milestones is CROSS_PHASE (never
    tagged, never tombstoned, never phase-filtered) — a lifetime ledger read
    through a cycle filter would hide consumed rungs and re-fire them.

    Returns {"existing_ids": set, "last_event_date": str|None, "has_genesis": bool,
    "events": [item, …]}.
    """
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": "pk = :pk",
        "ExpressionAttributeValues": {":pk": user_prefix + MILESTONES_SOURCE},
    }
    items: list[dict] = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs = dict(kwargs, ExclusiveStartKey=last)

    events = [i for i in items if str(i.get("sk", "")).startswith(EVENT_SK_PREFIX)]
    existing_ids = {i.get("milestone_id") or str(i.get("sk", ""))[len(EVENT_SK_PREFIX) :] for i in events}
    announced_dates = [str(i["event_date"]) for i in events if i.get("announce") and i.get("event_date")]
    return {
        "existing_ids": existing_ids,
        "last_event_date": max(announced_dates) if announced_dates else None,
        "has_genesis": any(str(i.get("sk", "")) == GENESIS_SK for i in items),
        "events": events,
    }


def read_announced_events(table, user_prefix: str) -> list[dict]:
    """The consumer surface (#1628): announced events only, oldest first.

    Baseline and subsumed entries are consumed rungs, not announcements — a
    consumer must never surface them as news.
    """
    events = [e for e in read_ledger(table, user_prefix)["events"] if e.get("announce") and e.get("event_date")]
    return sorted(events, key=lambda e: str(e["event_date"]))


def _put_once(table, user_prefix: str, entry: dict, stamp: dict | None) -> bool:
    """Conditional write-once put. Returns False when the key already exists.

    No tombstone escape hatch, unlike the #1624 badge ledger: this partition is
    CROSS_PHASE — the restart wipe never tombstones it — so an occupied key
    always means a genuinely consumed rung.
    """
    item = _dec(dict(entry))
    if stamp:
        item.update(stamp)
    try:
        # pk literal inline for the single-writer/orphan gates: "…SOURCE#milestones".
        table.put_item(
            Item={"pk": user_prefix + "milestones", **item},
            ConditionExpression="attribute_not_exists(sk)",
        )
        return True
    except Exception as exc:  # noqa: BLE001 — ConditionalCheckFailed = already consumed, which is success
        if "ConditionalCheckFailed" in type(exc).__name__ or "ConditionalCheckFailed" in str(exc):
            return False
        raise


def collect_signals(table, user_prefix: str, phase_filter, today: str) -> dict:
    """Fetch the signal inputs from DDB.

    These reads DO take the phase filter — they are current-cycle metric reads
    (the same data every other compute reads); only the LEDGER read is unfiltered.
    """

    def _query_all(**kwargs) -> list[dict]:
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

    end = datetime.strptime(today, "%Y-%m-%d")
    weight_start = (end - timedelta(days=WEIGHT_WINDOW_DAYS - 1)).strftime("%Y-%m-%d")
    habit_start = (end - timedelta(days=364)).strftime("%Y-%m-%d")

    weights = _query_all(
        KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
        ExpressionAttributeValues={":pk": user_prefix + "withings", ":s": f"DATE#{weight_start}", ":e": f"DATE#{today}"},
    )
    habits = _query_all(
        KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
        ExpressionAttributeValues={":pk": user_prefix + "habit_scores", ":s": f"DATE#{habit_start}", ":e": f"DATE#{today}"},
    )
    chars = _query_all(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :sk)",
        ExpressionAttributeValues={":pk": user_prefix + "character_sheet", ":sk": "DATE#"},
    )

    def _f(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    weight_series = []
    for w in sorted(weights, key=lambda i: str(i.get("sk") or "")):
        sk = str(w.get("sk") or "")
        val = _f(w.get("weight_lbs"))
        if sk.startswith("DATE#") and val is not None:
            weight_series.append((sk.removeprefix("DATE#"), val))

    habits_sorted = sorted(habits, key=lambda i: str(i.get("sk") or ""))
    latest_habit = habits_sorted[-1] if habits_sorted else {}
    tier0_streak = int(_f(latest_habit.get("t0_perfect_streak")) or _f(latest_habit.get("t0_aggregate_streak")) or 0)

    chars_sorted = sorted(chars, key=lambda i: str(i.get("sk") or ""))
    character_level = int(_f((chars_sorted[-1] if chars_sorted else {}).get("character_level")) or 1)

    return {
        "weight_series": weight_series,
        "tier0_streak": tier0_streak,
        "days_tracked": len(habits_sorted),
        "character_level": character_level,
    }


def sweep(table, user_prefix: str, phase_filter, today: str, stamp: dict | None = None, signals: dict | None = None) -> dict:
    """One writer pass. Idempotent; never mutates or deletes an existing entry.

    Returns {"written": [entry, …], "announced": [entry, …], "genesis": bool,
    "cooldown_active": bool, "deferred": [id, …]}.
    """
    ledger = read_ledger(table, user_prefix)
    if signals is None:
        signals = collect_signals(table, user_prefix, phase_filter, today)

    if not ledger["has_genesis"]:
        # First-ever run: consume everything already satisfied, announce nothing
        # (no honest event date exists for a crossing that predates the ledger).
        written = []
        for rule in MILESTONE_RULES:
            ok, meas = _satisfied(rule, signals, today)
            if ok and rule.id not in ledger["existing_ids"]:
                entry = _entry(rule, meas, today, announce=False, origin=ORIGIN_BASELINE)
                if _put_once(table, user_prefix, entry, stamp):
                    written.append(entry)
        _put_once(table, user_prefix, {"sk": GENESIS_SK, "genesis_date": today, "recorded_at": today}, stamp)
        return {"written": written, "announced": [], "genesis": True, "cooldown_active": False, "deferred": []}

    result = evaluate(signals, ledger["existing_ids"], ledger["last_event_date"], today)
    written = [e for e in result["to_write"] if _put_once(table, user_prefix, e, stamp)]
    return {
        "written": written,
        "announced": [e for e in written if e["announce"]],
        "genesis": False,
        "cooldown_active": result["cooldown_active"],
        "deferred": result["deferred"],
    }
