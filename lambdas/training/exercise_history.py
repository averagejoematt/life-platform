"""
exercise_history.py — Recent-history facts for per-exercise notes (ADR-068).

One batched DDB load per routine generation, indexed by Hevy template_id.
Pure-Python rendering of factual cues — the LLM never participates here,
so the anti-hallucination guard is structural (no model = no invented
numbers).

Per-exercise note format (default): "Last: 60kg 8/8/7 (24 May)"
  - Weight: top-set weight from the last performed session, kg, no
    fractional precision beyond 0.5
  - Reps: per-set reps list "8/8/7" — preserves shape (drop-off detection)
  - Date: human-friendly short date — "24 May" / "3 Jun"

Lifts with 0 prior sessions → empty string (no note rendered).
Lifts with 1-2 prior sessions → bare history cue (no progression cue).
3+ sessions → history cue is shown.

Progression cues are DELIBERATELY NOT added by this module (see ADR-068):
the routine's prescribed sets remain bound by autoreg_add_load_enabled.
A future module may add advisory progression text gated on that SSM flag.

Data source: USER#matthew#SOURCE#hevy partition. Per-workout records
have exercises[].template_id + sets[].weight_kg + sets[].reps.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from common.pacific_time import pacific_today  # #2798: hevy DATE# keys name Pacific days

logger = logging.getLogger("exercise_history")

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
# #3708 — the window covers the whole logged corpus, not a recent slice.
# At 180 days, 489 of Matthew's 537 distinct logged movements were invisible
# (Deadlift, 80 sessions, rendered as "no history" and the planner guessed a
# starting load). Hevy history begins 2021-04-12; the partition holds ~900
# workout records, so one paginated Query over all of it is cheap — the cost
# is bounded by the partition, not by the window. Anything that narrows this
# below FLOOR_LOOKBACK_DAYS re-creates the defect, and
# tests/test_exercise_history_window_3708.py reds on it.
DEFAULT_LOOKBACK_DAYS = int(os.environ.get("EXERCISE_HISTORY_LOOKBACK_DAYS", "3650"))

# The regression floor. A cue for a lift last performed during the 2024-25 cut
# sits 500-730 days back; a window under two years cannot see it.
FLOOR_LOOKBACK_DAYS = 1095

# A bodyweight annotation is only honest if a real weigh-in sits near the
# session. Beyond this many days we omit it rather than interpolate (ADR-104).
BODYWEIGHT_TOLERANCE_DAYS = 7

# Below this age a cue reads as current capability and needs no bodyweight
# context; above it, the reader needs to know the set is historical. Six
# months is the floor because his bodyweight moves 30+ lb inside one, and a
# top set lifted 30 lb lighter is not the same evidence.
STALE_AFTER_DAYS = 180

# #3700 — the Whoop workout window for the HR-at-level join. Short on purpose: HR-at-level
# is only ever read as a recent trend, and the Whoop partition holds several rows per day.
WHOOP_JOIN_LOOKBACK_DAYS = int(os.environ.get("WHOOP_JOIN_LOOKBACK_DAYS", "180"))

_ddb_table = None


def _table():
    global _ddb_table
    if _ddb_table is None:
        _ddb_table = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-west-2")).Table(TABLE_NAME)
    return _ddb_table


def _to_float(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _to_int(v) -> int:
    if v is None:
        return 0
    if isinstance(v, Decimal):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def load_recent_history(
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    today: date | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """The weighted index alone — `load_history_indexes(...)[0]`.

    Kept as the public name every existing caller and test already uses, with an
    unchanged return shape ON PURPOSE (#3700): the cardio sessions live in a SEPARATE
    index, so the load-floor machinery (`routine_generator.band_matched_best`) can never
    start counting zero-weight cycling blocks among a movement's sessions.
    """
    return load_history_indexes(lookback_days=lookback_days, today=today)[0]


def load_history_indexes(
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    today: date | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    """ONE batched Query over the SOURCE#hevy partition → (weighted, cardio).

    **weighted** — keyed by Hevy template_id → session dicts ordered most-recent first,
    each {date, sets: [{weight_kg, reps}], top_weight_kg}. Unchanged since ADR-068.

    **cardio** (#3700) — keyed the same way, each {date, name, note, duration_sec,
    distance_m, session_start, session_end}. It exists because the weighted index
    structurally cannot hold a ride: it drops every set whose `reps` is not > 0, which is
    every cardio set, so a cycling block was not merely unrendered by the routine cue —
    it never reached the index at all.

    The per-exercise note is read from `exercises[].notes` — the live wire field, verified
    against DynamoDB 2026-09-19: `notes` PLURAL, on the EXERCISE, and not the
    workout-level `description`, which was empty on the very record this issue was filed
    against.

    Only the new per-workout schema (sk = DATE#YYYY-MM-DD#WORKOUT#<id>,
    item has `source_workout_id`) is consumed. Legacy daily aggregates are
    ignored on purpose — pre-write-loop history is preserved in DDB but
    not surfaced into routine notes.
    """
    # #2798 — THE PAIR. The window bounds `DATE#` keys in the SOURCE#hevy partition,
    # whose days are Pacific (`adherence_calc.pacific_date_of`), and it is co-consumed
    # with the `target_date` that `hevy_routine_cron`/`manage_hevy_routine` author.
    today = today or date.fromisoformat(pacific_today())
    start = (today - timedelta(days=lookback_days)).isoformat()
    pk = f"USER#{USER_ID}#SOURCE#hevy"
    index: dict[str, list[dict[str, Any]]] = {}
    cardio: dict[str, list[dict[str, Any]]] = {}

    last_key = None
    # ADR-058: training continuity — weight selection needs the most recent
    # performances regardless of experiment phase; filtering pilot workouts
    # would make the routine generator think every lift is brand-new (owner
    # decision 2026-06-06). include_pilot=True is a deliberate no-op annotation.
    from experiment.phase_filter import with_phase_filter

    while True:
        kwargs: dict[str, Any] = with_phase_filter(
            {
                "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").gte(f"DATE#{start}"),
            },
            include_pilot=True,
        )
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        resp = _table().query(**kwargs)
        for item in resp.get("Items", []):
            if not item.get("source_workout_id"):
                continue  # legacy aggregate — skip
            workout_date = item.get("date") or ""
            # #3700 — every duration-bearing block in this session, keyed by its position.
            # The HR join needs a block's SIBLINGS: a Whoop workout that matches two
            # blocks of the same length is attributable to neither.
            block_secs_by_pos = {
                i: sum(_to_float(s.get("duration_sec")) for s in (ex.get("sets") or [])) for i, ex in enumerate(item.get("exercises") or [])
            }
            for pos, ex in enumerate(item.get("exercises") or []):
                tid = ex.get("template_id")
                if not tid:
                    continue
                sets_raw = ex.get("sets") or []
                # #3700 — the cardio arm. A duration-bearing block is collected BEFORE
                # the reps filter below, which would otherwise discard it silently.
                block_seconds = block_secs_by_pos.get(pos, 0.0)
                if block_seconds > 0:
                    block_meters = sum(_to_float(s.get("distance_m")) for s in sets_raw)
                    cardio.setdefault(tid, []).append(
                        {
                            "date": workout_date,
                            "name": ex.get("name") or "",
                            # the live wire field is `notes`, plural, on the EXERCISE
                            "note": (ex.get("notes") or ex.get("note") or "") or "",
                            "duration_sec": block_seconds,
                            "distance_m": block_meters if block_meters > 0 else None,
                            "session_start": item.get("start_time"),
                            "session_end": item.get("end_time"),
                            "sibling_block_seconds": [v for k, v in block_secs_by_pos.items() if k != pos and v > 0],
                        }
                    )
                sets = [
                    {
                        "weight_kg": _to_float(s.get("weight_kg")),
                        "reps": _to_int(s.get("reps")),
                    }
                    for s in sets_raw
                    if _to_int(s.get("reps")) > 0
                ]
                if not sets:
                    continue
                top_weight = max((s["weight_kg"] for s in sets), default=0.0)
                index.setdefault(tid, []).append(
                    {
                        "date": workout_date,
                        "sets": sets,
                        "top_weight_kg": top_weight,
                    }
                )
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break

    for tid in index:
        index[tid].sort(key=lambda s: s["date"], reverse=True)
    for tid in cardio:
        cardio[tid].sort(key=lambda s: s["date"], reverse=True)
    return index, cardio


def load_bodyweight_index(
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    today: date | None = None,
) -> dict[str, float]:
    """Single batched Query over SOURCE#withings → {YYYY-MM-DD: weight_lbs}.

    #3708. A top set lifted years ago was lifted at a different bodyweight, so
    quoting it without that context invites reading old capability as current.
    One Query per routine generation, same shape as load_recent_history.

    Cross-phase on purpose: bodyweight history predates every experiment reset,
    and an annotation that vanished at each genesis would be worse than none.
    """
    today = today or date.fromisoformat(pacific_today())
    start = (today - timedelta(days=lookback_days)).isoformat()
    pk = f"USER#{USER_ID}#SOURCE#withings"
    out: dict[str, float] = {}
    last_key = None
    while True:
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").gte(f"DATE#{start}"),
            "ProjectionExpression": "sk, weight_lbs",
        }
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        resp = _table().query(**kwargs)
        for item in resp.get("Items", []):
            lbs = _to_float(item.get("weight_lbs"))
            if lbs <= 0:
                continue
            day = str(item.get("sk", ""))[5:15]
            if len(day) == 10:
                out[day] = lbs
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
    return out


def load_whoop_workout_index(
    lookback_days: int = WHOOP_JOIN_LOOKBACK_DAYS,
    today: date | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Whoop WORKOUT records → {YYYY-MM-DD: [{start_time, end_time, average_heart_rate, …}]}.

    #3700's HR arm. Only `DATE#...#WORKOUT#<id>` rows are kept — the day-level Whoop row
    carries a 24-hour average heart rate, which is a number about sleeping, not about a
    bike, and joining it to a ride would be the exact fabrication ADR-104 forbids.

    Deliberately a SHORTER window than the exercise history (#3708's 10-year floor): the
    weighted cue quotes a single historical top set, while HR-at-level is only ever read
    as a recent trend, and the Whoop partition holds several rows per day.
    """
    today = today or date.fromisoformat(pacific_today())
    start = (today - timedelta(days=lookback_days)).isoformat()
    pk = f"USER#{USER_ID}#SOURCE#whoop"
    out: dict[str, list[dict[str, Any]]] = {}
    last_key = None
    while True:
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").gte(f"DATE#{start}"),
            "ProjectionExpression": "sk, #d, workout_id, sport_name, start_time, end_time, average_heart_rate",
            "ExpressionAttributeNames": {"#d": "date"},
        }
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        resp = _table().query(**kwargs)
        for item in resp.get("Items", []):
            sk = str(item.get("sk") or "")
            if "#WORKOUT#" not in sk:
                continue  # the day-level row's average HR is a 24h figure, not a ride's
            day = (item.get("date") or sk[5:15])[:10]
            out.setdefault(str(day), []).append(
                {
                    "workout_id": item.get("workout_id"),
                    "sport_name": item.get("sport_name"),
                    "start_time": item.get("start_time"),
                    "end_time": item.get("end_time"),
                    "average_heart_rate": _to_float(item.get("average_heart_rate")) or None,
                }
            )
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
    return out


def nearest_bodyweight(
    iso_date: str,
    weight_index: dict[str, float] | None,
    tolerance_days: int = BODYWEIGHT_TOLERANCE_DAYS,
) -> float | None:
    """Weigh-in closest to `iso_date`, or None if none sits within tolerance.

    Never interpolates and never reaches for the nearest reading at any
    distance — an absent weigh-in is reported as absence (ADR-104). Ties
    resolve to the earlier date, which is deterministic rather than arbitrary.
    """
    if not weight_index or not iso_date:
        return None
    try:
        target = date.fromisoformat(iso_date[:10])
    except ValueError:
        return None
    best: tuple[int, str] | None = None
    for day in weight_index:
        try:
            delta = abs((date.fromisoformat(day) - target).days)
        except ValueError:
            continue
        if delta > tolerance_days:
            continue
        if best is None or (delta, day) < best:
            best = (delta, day)
    return weight_index[best[1]] if best else None


def history_facts(
    template_id: str | None,
    index: dict[str, list[dict[str, Any]]],
    cardio_index: dict[str, list[dict[str, Any]]] | None = None,
    whoop_index: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Return the facts the renderer can quote. `{"sessions_count": 0}` on no history.

    #3700 — the cardio arm. The top-weight-tier selection below is a concept a ride does
    not have, so when a template has no weighted sessions and `cardio_index` does hold
    one, the facts come from `cardio_progression.cardio_facts` instead and carry
    `modality == "cardio"`. Strength wins when both exist; nothing about the weighted
    path changed.
    """
    if not template_id:
        return {"sessions_count": 0}
    sessions = index.get(template_id) or []
    if not sessions:
        if cardio_index and (cardio_index.get(template_id) or []):
            from training.cardio_progression import cardio_facts

            return cardio_facts(template_id, cardio_index, whoop_index)
        return {"sessions_count": 0}
    last = sessions[0]
    # Take sets at the top-weight tier (drop warmup-style lighter sets so the
    # cue reflects working volume).
    top = last["top_weight_kg"]
    working_sets = [s for s in last["sets"] if s["weight_kg"] >= top * 0.95]
    if not working_sets:
        working_sets = last["sets"]
    return {
        "sessions_count": len(sessions),
        "last_date": last["date"],
        "last_top_weight_kg": top,
        "last_reps_list": [s["reps"] for s in working_sets],
    }


_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _short_date(iso: str, today: date | None = None) -> str:
    """ISO YYYY-MM-DD → 'D Mon' when recent, 'Mon YYYY' when historical (#3708).

    A bare '24 May' is ambiguous once the window spans years — it reads as this
    year's May. Sessions older than STALE_AFTER_DAYS render month + year so the
    age of the set is legible in the cue itself. Returns '' on bad input.
    """
    try:
        y, m, d = iso.split("-")
        month = _MONTHS[int(m) - 1]
    except (ValueError, IndexError):
        return ""
    ref = today or date.fromisoformat(pacific_today())
    # The year is carried whenever the session is not in the current calendar
    # year. Without it "4 Nov" on 2026-09-08 reads as a November that has not
    # happened yet — the ambiguity a widened window introduces (#3708).
    if y != str(ref.year):
        return f"{month} {y}"
    return f"{int(d)} {month}"


def _round_weight(kg: float) -> str:
    """Pretty-print kg with at most one decimal, dropping trailing .0."""
    if kg <= 0:
        return ""
    rounded = round(kg * 2) / 2  # nearest 0.5
    if abs(rounded - int(rounded)) < 0.05:
        return f"{int(rounded)}kg"
    return f"{rounded}kg"


def render_history_cue(
    facts: dict[str, Any],
    weight_index: dict[str, float] | None = None,
    today: date | None = None,
) -> str:
    """One-line factual cue. Returns '' if no usable history.

    Recent:     "Last: 60kg 8/8/7 (24 May)"
    Historical: "Last: 100kg 5/5/4 (Nov 2024, at 268 lb)"

    #3708. The bodyweight clause is added only for sets older than
    STALE_AFTER_DAYS and only when a real weigh-in sits within
    BODYWEIGHT_TOLERANCE_DAYS — otherwise it is omitted entirely. A missing
    weigh-in never becomes an interpolated one (ADR-104): the cue silently
    loses the clause rather than gaining a number nobody measured.
    """
    if facts.get("sessions_count", 0) == 0:
        return ""
    # #3700 — the cardio branch. A ride carries duration + distance and NEITHER a top-set
    # weight nor a reps list, so every cardio block fell out of the `if not weight or not
    # reps: return ""` below and the routine cue for cycling was empty by construction.
    if facts.get("modality") == "cardio":
        from training.cardio_progression import level_verdict, render_cardio_cue

        return render_cardio_cue(facts, level_verdict(facts.get("series"), facts.get("last_level")))
    weight = _round_weight(facts.get("last_top_weight_kg", 0))
    reps = facts.get("last_reps_list") or []
    if not weight or not reps:
        return ""
    reps_str = "/".join(str(r) for r in reps)
    last_date = facts.get("last_date", "") or ""
    date_str = _short_date(last_date, today=today)
    if not date_str:
        return f"Last: {weight} {reps_str}"

    context = date_str
    try:
        age = ((today or date.fromisoformat(pacific_today())) - date.fromisoformat(last_date[:10])).days
    except ValueError:
        age = 0
    if age > STALE_AFTER_DAYS:
        lbs = nearest_bodyweight(last_date, weight_index)
        if lbs:
            context = f"{date_str}, at {int(round(lbs))} lb"
    return f"Last: {weight} {reps_str} ({context})"


def pick_note(
    history_cue: str,
    ai_comment: str | None,
    mode: str = "one_best_line",
) -> str:
    """Combine the available cues per `mode`. ADR-068:
    - one_best_line (default): prefer the AI comment when present, else
      the history cue, else empty.
    - show_both: history cue then AI comment, separated by a space-dash-space.
    - off: empty string.

    The AI-comment input is currently always None — wiring is in place for
    a future coach-layer output, but no module emits one today.
    """
    if mode == "off":
        return ""
    history_cue = (history_cue or "").strip()
    ai_comment = (ai_comment or "").strip() if ai_comment else ""
    if mode == "show_both":
        parts = [p for p in (history_cue, ai_comment) if p]
        return " — ".join(parts)
    # one_best_line
    return ai_comment or history_cue


def _reset_for_tests() -> None:
    global _ddb_table
    _ddb_table = None
