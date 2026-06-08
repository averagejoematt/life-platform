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

logger = logging.getLogger("exercise_history")

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
DEFAULT_LOOKBACK_DAYS = int(os.environ.get("EXERCISE_HISTORY_LOOKBACK_DAYS", "180"))

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
    """Single batched Query over the SOURCE#hevy partition. Returns a dict
    keyed by Hevy template_id → list of session dicts ordered most-recent
    first. Each session: {date, sets: [{weight_kg, reps}], top_weight_kg}.

    Only the new per-workout schema (sk = DATE#YYYY-MM-DD#WORKOUT#<id>,
    item has `source_workout_id`) is consumed. Legacy daily aggregates are
    ignored on purpose — pre-write-loop history is preserved in DDB but
    not surfaced into routine notes.
    """
    today = today or date.today()
    start = (today - timedelta(days=lookback_days)).isoformat()
    pk = f"USER#{USER_ID}#SOURCE#hevy"
    index: dict[str, list[dict[str, Any]]] = {}

    last_key = None
    # ADR-058: training continuity — weight selection needs the most recent
    # performances regardless of experiment phase; filtering pilot workouts
    # would make the routine generator think every lift is brand-new (owner
    # decision 2026-06-06). include_pilot=True is a deliberate no-op annotation.
    from phase_filter import with_phase_filter

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
            for ex in item.get("exercises") or []:
                tid = ex.get("template_id")
                if not tid:
                    continue
                sets_raw = ex.get("sets") or []
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
    return index


def history_facts(template_id: str | None, index: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Return the facts the renderer can quote. Empty dict on no history."""
    if not template_id:
        return {"sessions_count": 0}
    sessions = index.get(template_id) or []
    if not sessions:
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


def _short_date(iso: str) -> str:
    """ISO YYYY-MM-DD → 'D Mon'. Returns '' on bad input."""
    try:
        y, m, d = iso.split("-")
        return f"{int(d)} {_MONTHS[int(m) - 1]}"
    except (ValueError, IndexError):
        return ""


def _round_weight(kg: float) -> str:
    """Pretty-print kg with at most one decimal, dropping trailing .0."""
    if kg <= 0:
        return ""
    rounded = round(kg * 2) / 2  # nearest 0.5
    if abs(rounded - int(rounded)) < 0.05:
        return f"{int(rounded)}kg"
    return f"{rounded}kg"


def render_history_cue(facts: dict[str, Any]) -> str:
    """One-line factual cue. Returns '' if no usable history."""
    if facts.get("sessions_count", 0) == 0:
        return ""
    weight = _round_weight(facts.get("last_top_weight_kg", 0))
    reps = facts.get("last_reps_list") or []
    if not weight or not reps:
        return ""
    reps_str = "/".join(str(r) for r in reps)
    date_str = _short_date(facts.get("last_date", ""))
    if date_str:
        return f"Last: {weight} {reps_str} ({date_str})"
    return f"Last: {weight} {reps_str}"


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
