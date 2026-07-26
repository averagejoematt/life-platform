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

Window-validated process milestones + weight demoted (#1628)
------------------------------------------------------------
The process/composition milestones (return_after_gap, sustained_sessions,
strength_in_deficit, zone2, rhr_hrv_trend, waist) are PURE WINDOW FUNCTIONS in
lambdas/process_milestones.py — this module evaluates their candidates inside
the same sweep, so they inherit write-once, the global cooldown, and genesis
baselining. Two structural rules land with them:

- **Weight never emits alone.** Weight is LAST in LADDER_PRIORITY, and a weight
  rung is only ever written as a companion (`companion_to`) of a process or
  composition milestone announced on the same run. A run where only weight
  rungs are satisfied writes NOTHING — the rungs stay deferred (unconsumed)
  until a milestone that gives the number meaning co-fires.
- **The spiral circuit breaker (#1627) gates every announcement.** When the
  breaker is not explicitly clear, the sweep defers instead of announcing
  (rungs stay unconsumed; fails closed) — during a suspected downturn the
  platform checks in, it does not congratulate.

v1.0.0 — 2026-07-25 (#1626)
v1.1.0 — 2026-07-26 (#1628): window-validated process milestones, weight
         demoted to companion-only, spiral-breaker gate on announcements
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, NamedTuple

import process_milestones  # #1628: the pure window functions (no I/O — this module remains the ONE writer)

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
    ladder: str = ""  # subsumption group; defaults to category (the pre-#1628 rungs)


def _ladder_of(rule) -> str:
    """Subsumption/priority group for a rung or window candidate."""
    return getattr(rule, "ladder", "") or rule.category


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

# When rungs from several ladders are eligible on the same run, one ladder's
# champion announces — chosen by this order. #1628 demoted weight to LAST:
# the milestones that predict a cycle holding are process behaviours (the
# restart above all), and a weight number only means something next to them.
LADDER_PRIORITY: tuple[str, ...] = (
    "return_after_gap",  # THE highest-value one: restarting is the behaviour the experiment turns on
    "sustained_sessions",
    "strength_in_deficit",
    "zone2",
    "rhr_hrv_trend",
    "waist",
    "streak",
    "days_tracked",
    "level",
    "weight",  # never alone — companion-only, see WEIGHT_COMPANION_CATEGORIES
)

# The categories whose milestones give a weight number meaning (#1628): a weight
# rung may only be written alongside a champion from one of these categories.
# Streak/days/level deliberately do NOT qualify — the issue names composition
# and process milestones as the companions that make weight mean something.
WEIGHT_COMPANION_CATEGORIES: tuple[str, ...] = (
    process_milestones.CATEGORY_PROCESS,
    process_milestones.CATEGORY_COMPOSITION,
)

# Category-level view of the same ordering (kept for consumers/tests that think
# in categories; champion selection itself runs on LADDER_PRIORITY).
CATEGORY_PRIORITY: tuple[str, ...] = ("process", "composition", "streak", "days_tracked", "level", "weight")


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
    mean = sum(vals) / len(vals)
    sd = (sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5  # n >= 3 guaranteed above
    return {
        "window_start": start,
        "window_end": today,
        "window_days": WEIGHT_WINDOW_DAYS,
        "n": len(vals),
        "mean_lbs": round(mean, 1),
        "sd_lbs": round(sd, 2),  # ADR-105: the claim carries its spread, not just its mean
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


def _entry(
    rule, measurement: dict, today: str, *, announce: bool, origin: str, subsumed_by: str | None = None, companion_to: str | None = None
) -> dict:
    entry = {
        "sk": EVENT_SK_PREFIX + rule.id,
        "milestone_id": rule.id,
        "label": rule.label,
        "category": rule.category,
        "ladder": _ladder_of(rule),
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
    if companion_to:
        # #1628: a weight rung written alongside the process/composition milestone
        # that gives the number meaning — never written without one.
        entry["companion_to"] = companion_to
    return entry


def _all_satisfied(signals: dict, existing_ids: set[str], today: str) -> list[tuple[Any, dict]]:
    """Every unconsumed rung/window-candidate whose condition holds right now."""
    satisfied: list[tuple[Any, dict]] = []
    for rule in MILESTONE_RULES:
        if rule.id in existing_ids:
            continue  # a rung crossed is a rung consumed, forever
        ok, meas = _satisfied(rule, signals, today)
        if ok:
            satisfied.append((rule, meas))
    for cand, meas in process_milestones.candidates(signals, today):
        if cand.id not in existing_ids:
            satisfied.append((cand, meas))
    return satisfied


def evaluate(signals: dict, existing_ids: set[str], last_event_date: str | None, today: str, suppressed: bool = False) -> dict:
    """Pure decision function: what (if anything) does this run write?

    Returns {"to_write": [entry, …], "cooldown_active": bool, "suppressed": bool,
    "deferred": [id, …]}. to_write holds at most ONE announced champion (plus a
    weight companion when the champion is process/composition, plus same-ladder
    subsumed siblings); deferred lists satisfied-but-not-written rungs (cooldown,
    breaker suppression, weight-alone, or a lower-priority ladder this run) —
    they stay unconsumed and re-evaluate later.

    Structural rule (#1628): weight rungs never emit alone. When only weight is
    satisfied, NOTHING is written; a weight rung reaches the ledger only as a
    companion of a same-run process/composition champion.
    """
    satisfied = _all_satisfied(signals, existing_ids, today)
    cooldown_active = last_event_date is not None and _days_between(last_event_date, today) < GLOBAL_COOLDOWN_DAYS
    if cooldown_active or suppressed or not satisfied:
        return {
            "to_write": [],
            "cooldown_active": cooldown_active,
            "suppressed": suppressed,
            "deferred": [r.id for r, _ in satisfied],
        }

    non_weight = [(r, m) for r, m in satisfied if _ladder_of(r) != "weight"]
    weight_sat = sorted(((r, m) for r, m in satisfied if _ladder_of(r) == "weight"), key=lambda rm: rm[0].depth, reverse=True)

    if not non_weight:
        # #1628 structural rule: a weight milestone never appears alone. The rungs
        # stay deferred (unconsumed) until a process/composition milestone co-fires.
        return {"to_write": [], "cooldown_active": False, "suppressed": False, "deferred": [r.id for r, _ in satisfied]}

    by_ladder: dict[str, list[tuple[Any, dict]]] = {}
    for rule, meas in non_weight:
        by_ladder.setdefault(_ladder_of(rule), []).append((rule, meas))

    champ_ladder = next((ld for ld in LADDER_PRIORITY if ld in by_ladder), sorted(by_ladder)[0])
    ladder_entries = sorted(by_ladder[champ_ladder], key=lambda rm: rm[0].depth, reverse=True)
    champion, champion_meas = ladder_entries[0]
    to_write = [_entry(champion, champion_meas, today, announce=True, origin=ORIGIN_CROSSING)]
    for rule, meas in ladder_entries[1:]:
        # Same-ladder siblings crossed by the same motion: consumed with the same
        # event, never announced after their greater rung.
        to_write.append(_entry(rule, meas, today, announce=False, origin=ORIGIN_CROSSING, subsumed_by=champion.id))

    if weight_sat and champion.category in WEIGHT_COMPANION_CATEGORIES:
        # The deepest satisfied weight rung rides along as the companion; its
        # shallower siblings are consumed by the same motion (ladder subsumption).
        w_champion, w_meas = weight_sat[0]
        to_write.append(_entry(w_champion, w_meas, today, announce=True, origin=ORIGIN_CROSSING, companion_to=champion.id))
        for rule, meas in weight_sat[1:]:
            to_write.append(_entry(rule, meas, today, announce=False, origin=ORIGIN_CROSSING, subsumed_by=w_champion.id))

    written_ids = {e["milestone_id"] for e in to_write}
    deferred = [r.id for r, _ in satisfied if r.id not in written_ids]
    return {"to_write": to_write, "cooldown_active": False, "suppressed": False, "deferred": deferred}


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

    def _range(source: str, start: str, include_subrecords: bool = False) -> list[dict]:
        # `~` sorts after any `#`-suffixed sub-record key, so an inclusive end of
        # DATE#{today}~ also captures DATE#{today}#WORKOUT#… items.
        end_key = f"DATE#{today}~" if include_subrecords else f"DATE#{today}"
        return _query_all(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={":pk": user_prefix + source, ":s": f"DATE#{start}", ":e": end_key},
        )

    end = datetime.strptime(today, "%Y-%m-%d")

    def _back(days: int) -> str:
        return (end - timedelta(days=days)).strftime("%Y-%m-%d")

    weights = _range("withings", _back(WEIGHT_WINDOW_DAYS - 1))
    habits = _range("habit_scores", _back(364))
    chars = _query_all(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :sk)",
        ExpressionAttributeValues={":pk": user_prefix + "character_sheet", ":sk": "DATE#"},
    )

    # #1628 window-milestone inputs. The training lookback covers the deepest
    # sustained_sessions rung; the others use their own definition windows.
    training_lookback = max(process_milestones.SUSTAIN_RUNG_WEEKS) * 7
    hevy = _range("hevy", _back(training_lookback), include_subrecords=True)
    strava = _range("strava", _back(training_lookback))
    garmin = _range("garmin", _back(process_milestones.ZONE2_WINDOW_DAYS - 1))
    whoop = _range("whoop", _back(2 * process_milestones.TREND_WINDOW_DAYS - 1), include_subrecords=True)
    macro = _range("macrofactor", _back(process_milestones.STRENGTH_WINDOW_DAYS - 1))
    measurements = _range("measurements", _back(process_milestones.WAIST_WINDOW_DAYS - 1))

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

    # Training days + strength volume: hevy workout sub-records (DATE#d#WORKOUT#id)
    # union strava activity days (the spiral_breaker convention).
    training_days: set[str] = set()
    strength_volume_by_day: dict[str, float] = {}
    for item in hevy:
        sk = str(item.get("sk") or "")
        if sk.startswith("DATE#") and "#WORKOUT#" in sk:
            day = sk[5:15]
            training_days.add(day)
            vol = _f(item.get("total_volume_kg"))
            if vol is not None:
                strength_volume_by_day[day] = strength_volume_by_day.get(day, 0.0) + vol

    # Zone 2 minutes: garmin daily zone2_minutes + strava total_zone2_seconds.
    zone2_by_day: dict[str, float] = {}
    for item in garmin:
        sk = str(item.get("sk") or "")
        z2 = _f(item.get("zone2_minutes")) or _f(item.get("time_in_zone_2_minutes"))
        if sk.startswith("DATE#") and len(sk) == 15 and z2 is not None:
            zone2_by_day[sk[5:15]] = zone2_by_day.get(sk[5:15], 0.0) + z2
    for item in strava:
        sk = str(item.get("sk") or "")
        if not sk.startswith("DATE#"):
            continue
        day = sk[5:15]
        training_days.add(day)
        z2s = _f(item.get("total_zone2_seconds"))
        if z2s is not None:
            zone2_by_day[day] = zone2_by_day.get(day, 0.0) + z2s / 60.0

    # RHR / HRV: whoop daily records (skip interleaved #WORKOUT# sub-records).
    rhr_by_day: dict[str, float] = {}
    hrv_by_day: dict[str, float] = {}
    for item in whoop:
        sk = str(item.get("sk") or "")
        if not sk.startswith("DATE#") or "#WORKOUT#" in sk:
            continue
        rhr = _f(item.get("resting_heart_rate"))
        hrv = _f(item.get("hrv"))
        if rhr is not None:
            rhr_by_day[sk[5:15]] = rhr
        if hrv is not None:
            hrv_by_day[sk[5:15]] = hrv

    # Intake / expenditure: MacroFactor daily records.
    calories_by_day: dict[str, float] = {}
    expenditure_by_day: dict[str, float] = {}
    for item in macro:
        sk = str(item.get("sk") or "")
        if not sk.startswith("DATE#") or len(sk) != 15:
            continue
        cal = _f(item.get("total_calories_kcal"))
        exp = _f(item.get("expenditure_kcal")) or _f(item.get("tdee_kcal"))
        if cal is not None:
            calories_by_day[sk[5:15]] = cal
        if exp is not None:
            expenditure_by_day[sk[5:15]] = exp

    # Waist: navel tape measurements.
    waist_by_day: dict[str, float] = {}
    for item in measurements:
        sk = str(item.get("sk") or "")
        waist = _f(item.get("waist_navel_in"))
        if sk.startswith("DATE#") and len(sk) == 15 and waist is not None:
            waist_by_day[sk[5:15]] = waist

    return {
        "weight_series": weight_series,
        "tier0_streak": tier0_streak,
        "days_tracked": len(habits_sorted),
        "character_level": character_level,
        # #1628 window-milestone signal families (pure inputs to process_milestones)
        "training_dates": sorted(training_days),
        "strength_volume_by_day": strength_volume_by_day,
        "zone2_minutes_by_day": zone2_by_day,
        "rhr_by_day": rhr_by_day,
        "hrv_by_day": hrv_by_day,
        "calories_by_day": calories_by_day,
        "expenditure_by_day": expenditure_by_day,
        "waist_by_day": waist_by_day,
    }


def _celebration_suppressed(table, today: str) -> bool:
    """The spiral circuit breaker gate (#1627): may the ledger announce today?

    Fails closed — if the breaker (or its data) is unavailable, we defer rather
    than celebrate. Deferral costs nothing here: a suppressed rung stays
    UNCONSUMED and simply re-evaluates on a later sweep, provided its window
    condition still holds then.
    """
    try:
        import spiral_breaker

        allowed, _verdict = spiral_breaker.check_celebration_allowed("milestone_announcements", now=today, table=table)
        return not allowed
    except Exception:  # noqa: BLE001 — any breaker failure means "not explicitly clear" -> suppress
        return True


def sweep(
    table,
    user_prefix: str,
    phase_filter,
    today: str,
    stamp: dict | None = None,
    signals: dict | None = None,
    suppressed: bool | None = None,
) -> dict:
    """One writer pass. Idempotent; never mutates or deletes an existing entry.

    `suppressed=None` (the production default) consults the spiral circuit
    breaker (#1627) live; pass an explicit bool to inject the verdict (tests,
    or a caller that already ran the breaker this invocation).

    Returns {"written": [entry, …], "announced": [entry, …], "genesis": bool,
    "cooldown_active": bool, "suppressed": bool, "deferred": [id, …]}.
    """
    ledger = read_ledger(table, user_prefix)
    if signals is None:
        signals = collect_signals(table, user_prefix, phase_filter, today)

    if not ledger["has_genesis"]:
        # First-ever run: consume everything already satisfied, announce nothing
        # (no honest event date exists for a crossing that predates the ledger).
        # Baseline consumption is not celebratory, so the breaker is not consulted.
        written = []
        for rule, meas in _all_satisfied(signals, ledger["existing_ids"], today):
            entry = _entry(rule, meas, today, announce=False, origin=ORIGIN_BASELINE)
            if _put_once(table, user_prefix, entry, stamp):
                written.append(entry)
        _put_once(table, user_prefix, {"sk": GENESIS_SK, "genesis_date": today, "recorded_at": today}, stamp)
        return {"written": written, "announced": [], "genesis": True, "cooldown_active": False, "suppressed": False, "deferred": []}

    if suppressed is None:
        suppressed = _celebration_suppressed(table, today)

    result = evaluate(signals, ledger["existing_ids"], ledger["last_event_date"], today, suppressed=suppressed)
    written = [e for e in result["to_write"] if _put_once(table, user_prefix, e, stamp)]
    return {
        "written": written,
        "announced": [e for e in written if e["announce"]],
        "genesis": False,
        "cooldown_active": result["cooldown_active"],
        "suppressed": result["suppressed"],
        "deferred": result["deferred"],
    }
