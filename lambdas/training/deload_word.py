"""deload_word.py — the deload is OWNER-GATED (#5070, owner ruling 2026-10-18).

The charter's `deload` block (`config/training_charter.json`) says `scheduled: false`,
`automatic: false`, `owner_gated: true`: nothing in the engine enters a deload on a calendar
or on a signal. A fatigue signal becomes a RECOMMENDATION (this module builds it); a deload
APPLIES only when the owner's recorded word covers the day.

The owner's word is a DDB record, mirroring the pain-flag dismissal (`training_context_registry`,
#4036): `USER#matthew#SOURCE#training_constraints / DELOAD#<start_date>` with `days`, `sets_pct`
and `words` VERBATIM — Tier 2 owner-only, CROSS_PHASE, written from chat through
`get_exercise_notes(action='deload')`. This module is pure: the rule and the record shape live
here; the read and the write live in `mcp/tools_training_notes.py`.
"""

from __future__ import annotations

import logging
from typing import Any

from common.pacific_time import parse_day_key

logger = logging.getLogger(__name__)
ISSUE = "#5070"
DELOAD_SOURCE = "training_constraints"
DELOAD_PK = f"USER#matthew#SOURCE#{DELOAD_SOURCE}"
DELOAD_SK_PREFIX = "DELOAD#"
DELOAD_STORE = f"{DELOAD_PK} / {DELOAD_SK_PREFIX}<YYYY-MM-DD> — CROSS_PHASE (ADR-077), Tier 2 owner-only"


def _is_iso_date(s: Any) -> bool:
    return isinstance(s, str) and len(s) >= 10 and parse_day_key(s[:10]) is not None


def deload_sk(start_date: str) -> str:
    return f"{DELOAD_SK_PREFIX}{str(start_date)[:10]}"


# The charter triggers a producer exists for today. `event_signals` has none yet (carrier: #5146), and the packet says so
# rather than implying an event signal is being watched.
TRIGGERS_WIRED = ("rpe_drift", "recovery")


def policy() -> dict[str, Any]:
    """The charter's deload block plus the proposed response (the cut a recorded word applies as written)."""
    from training import owner_redlines
    from training.training_charter import charter_value

    block = dict(charter_value("deload", {}) or {})
    cut = owner_redlines.REDLINES["lifting_sessions_per_wk"]["deload"]
    return {
        "scheduled": bool(block.get("scheduled", False)),
        "automatic": bool(block.get("automatic", False)),
        "owner_gated": bool(block.get("owner_gated", True)),
        "applied_only_on": block.get("applied_only_on") or "the owner's recorded word",
        "recommendation_triggers": list(block.get("recommendation_triggers") or []),
        "proposed_response": {"sets_pct": int(cut["sets_pct"]), "days": int(cut["days"]), "loads": cut["loads"]},
    }


def build_deload_record(
    *, start_date: str, words: str, recorded_at: str, days: int | None = None, sets_pct: int | None = None
) -> dict[str, Any]:
    """Validate the owner's word and return the DDB item body (strings and ints only — Decimal-safe).

    Raises ValueError. `words` is VERBATIM: the override is his statement, not a paraphrase."""
    words = str(words or "").strip()
    if not words:
        raise ValueError("words is required and must be VERBATIM — a deload applies only on the owner's recorded word")
    if not _is_iso_date(start_date):
        raise ValueError("start_date must be YYYY-MM-DD — the first day the deload covers")
    pol = policy()["proposed_response"]
    n_days = int(days if days is not None else pol["days"])
    pct = int(sets_pct if sets_pct is not None else pol["sets_pct"])
    if not 1 <= n_days <= 14:
        raise ValueError("days must be 1-14")
    if not -60 <= pct <= -10:
        raise ValueError("sets_pct must be a cut between -10 and -60 (negative)")
    return {
        "sk": deload_sk(start_date),
        "start_date": str(start_date)[:10],
        "days": n_days,
        "sets_pct": pct,
        "loads": pol["loads"],
        "words": words,
        "recorded_at": str(recorded_at),
        "recorded_via": "chat",
        "issue": ISSUE,
    }


def active_record(records: list[dict[str, Any]] | None, day: str) -> dict[str, Any] | None:
    """The record whose window `[start_date, start_date + days)` covers `day`, else None."""
    d = parse_day_key(str(day)[:10])
    if d is None:
        return None
    for r in sorted(records or [], key=lambda x: str(x.get("start_date")), reverse=True):
        s = parse_day_key(str(r.get("start_date"))[:10])
        if s is None:
            continue
        if 0 <= (d - s).days < int(r.get("days") or 0):
            return r
    return None


def load_records() -> list[dict[str, Any]]:
    """Every recorded deload word, newest first (the generator path's own DDB read; MCP reads through its sanctioned
    helper in `mcp/tools_training_notes.py`). Raises on a failed read."""
    from boto3.dynamodb.conditions import Key

    from training import exercise_history

    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": Key("pk").eq(DELOAD_PK) & Key("sk").begins_with(DELOAD_SK_PREFIX),
        "ScanIndexForward": False,
    }
    while True:
        resp = exercise_history._table().query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def load_records_failsoft() -> list[dict[str, Any]]:
    """`load_records`, or [] when the read fails — SAFE for an applier: no recorded word means no cut, so an unreadable
    store can never cut a session (the plan packet, not this, states `records_state`)."""
    try:
        return load_records()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"deload_word: the recorded-word read failed ({type(e).__name__}: {e}) — no deload applied")
        return []


def recommendation(
    *,
    day: str,
    records: list[dict[str, Any]] | None,
    fatigue: dict[str, Any] | None = None,
    readiness_low_streak_days: int | None = None,
    readiness_floor_days: int = 2,
    pain_note_sites: list[str] | None = None,
    extra_reasons: list[str] | None = None,
) -> dict[str, Any]:
    """`deload_recommendation` for the plan packet: the signals that argue for a deload, the response
    that WOULD apply, and whether the owner's word applies it today. Never an applied cut by itself.

    `fatigue` is `critics_fatigue.assess`'s output (performance drop, readiness, consecutive soreness)."""
    reasons: list[str] = []
    if fatigue and fatigue.get("triggered"):
        reasons.extend(str(r) for r in fatigue.get("reasons") or [])
    elif readiness_low_streak_days is not None and readiness_low_streak_days >= readiness_floor_days:
        reasons.append(f"readiness below the floor on {readiness_low_streak_days} consecutive days (>= {readiness_floor_days})")
    for site in pain_note_sites or []:
        reasons.append(f"pain/soreness note on a drafted lift: {site}")
    reasons.extend(extra_reasons or [])
    rec = active_record(records, day)
    pol = policy()
    wired = [t for t in pol["recommendation_triggers"] if t in TRIGGERS_WIRED or (t == "event_signals" and extra_reasons is not None)]
    return {
        "active": bool(reasons),
        "triggers_wired": wired,
        "triggers_unwired": [t for t in pol["recommendation_triggers"] if t not in wired],
        "reasons": reasons,
        "proposed_response": pol["proposed_response"],
        "applied": rec is not None,
        "applied_on": (
            {"start_date": rec["start_date"], "days": rec.get("days"), "sets_pct": rec.get("sets_pct"), "words": rec.get("words")}
            if rec
            else None
        ),
        "rule": (
            "the deload is the owner's call: signals recommend, only his recorded word applies "
            f"(get_exercise_notes action='deload'; {DELOAD_STORE}) — {ISSUE}"
        ),
        "records_read": records is not None,
    }
