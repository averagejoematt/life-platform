"""deload_word.py — the deload is OWNER-GATED (#5070, owner ruling 2026-10-18).

The charter's `deload` block (`config/training_charter.json`) says `scheduled: false`,
`automatic: false`, `owner_gated: true`: nothing in the engine enters a deload on a calendar
or on a signal. A fatigue signal becomes a RECOMMENDATION (this module builds it); a deload
APPLIES only when the owner's recorded word covers the day. The charter's three triggers all feed
it: RPE drift and recovery (`critics_fatigue`), and since #5146 the event signals (`event_signals`:
a sick day logged in the last 7 days, the deficit tool's WARNING/CRITICAL band, a charter travel
window) — each a reason on the recommendation, never a cut.

The owner's word is a DDB record, mirroring the pain-flag dismissal (`training_context_registry`,
#4036): `USER#matthew#SOURCE#training_constraints / DELOAD#<start_date>` with `days`, `sets_pct`
and `words` VERBATIM — Tier 2 owner-only, CROSS_PHASE, written from chat through
`get_exercise_notes(action='deload')`. This module is pure: the rule and the record shape live
here; the read and the write live in `mcp/tools_training_notes.py`.
"""

from __future__ import annotations

import logging
from typing import Any

from common.pacific_time import parse_day_key, shift_day_key

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


# The charter triggers a producer exists for. `event_signals` (#5146) is the issue's three event sources: the sick-day
# store (`manage_sick_days`, SOURCE#sick_days), the deficit tool's own deload line (`get_deficit_sustainability`, the
# WARNING/CRITICAL band) and the charter `travel` windows. Each becomes a REASON on the recommendation, never a cut; a
# copy built without the reads says so on `event_signals.read` rather than implying they were watched.
TRIGGERS_WIRED = ("rpe_drift", "recovery", "event_signals")
EVENT_ISSUE = "#5146"
SICK_DAY_LOOKBACK_DAYS = 7
"""A sick day logged in the 7 days through the plan day argues for a deload (the window the plan reads)."""
DEFICIT_DELOAD_BANDS = ("WARNING", "CRITICAL")
"""The deficit tool's severities whose recommendation reaches the training load (WARNING says 'scheduling a deload')."""
# The read states `training.plan_engine` uses (#4072) — literal here, because plan_engine imports this module.
_MEASURED, _ABSENT, _READ_FAILED, _NOT_READ = "measured", "absent", "read_failed", "not_read"


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


def _source_state(stated: Any, value: Any) -> dict[str, Any]:
    """The caller's stated read status for one event source, else inferred: None is `not_read`, empty is `absent`."""
    if isinstance(stated, dict) and stated.get("state"):
        return dict(stated)
    if value is None:
        return {"state": _NOT_READ, "detail": "the caller did not read this source"}
    return {"state": _MEASURED if value else _ABSENT}


def _sick_day_signal(day: str, rows: list[dict[str, Any]] | None, stated: Any) -> tuple[list[str], dict[str, Any]]:
    """The sick days logged in `[day - SICK_DAY_LOOKBACK_DAYS, day]`. A cleared (tombstoned, #4378) row is not a sick day.
    The row's free-text `reason` is NOT echoed: it can carry clinical detail, and this block rides the coach packet."""
    lo = shift_day_key(day, -SICK_DAY_LOOKBACK_DAYS)
    dates = sorted(
        {
            str(r.get("date") or str(r.get("sk") or "").replace("DATE#", ""))[:10]
            for r in rows or []
            if isinstance(r, dict) and not r.get("cleared_at")
        }
    )
    dates = [d for d in dates if _is_iso_date(d) and lo <= d <= day]
    reasons = (
        [
            f"sick day{'s' if len(dates) > 1 else ''} logged {', '.join(dates)} — inside the {SICK_DAY_LOOKBACK_DAYS} days through {day} (manage_sick_days)"
        ]
        if dates
        else []
    )
    return reasons, {**_source_state(stated, rows), "window": {"start": lo, "end": day}, "dates": dates}


def _deficit_signal(deficit: dict[str, Any] | None, stated: Any) -> tuple[list[str], dict[str, Any]]:
    """The deficit tool's severity; WARNING/CRITICAL quotes the tool's own recommendation line verbatim."""
    d = deficit if isinstance(deficit, dict) else None
    sev = str((d or {}).get("severity") or "") or None
    period = (d or {}).get("period") or {}
    reasons: list[str] = []
    if d is not None and sev in DEFICIT_DELOAD_BANDS:
        n = len(d.get("channels") or [])
        reasons.append(
            f"deficit sustainability {sev} ({d.get('degraded_count')} of {n} channels degrading, "
            f"{period.get('start_date')}..{period.get('end_date')}): {d.get('recommendation')} (get_deficit_sustainability)"
        )
    block = {**_source_state(stated, d), "severity": sev, "bands_that_recommend": list(DEFICIT_DELOAD_BANDS), "period": period or None}
    return reasons, block


def event_signals(
    day: str,
    *,
    sick_days: list[dict[str, Any]] | None = None,
    deficit: dict[str, Any] | None = None,
    status: dict[str, dict[str, Any]] | None = None,
    travel_windows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The charter's `event_signals` trigger (#5146): `{read, reasons, sources, unread}`. Pure.

    `sick_days` are SOURCE#sick_days rows, `deficit` is `get_deficit_sustainability`'s return, `status` the caller's
    read state per source (`sick_days`, `deficit`, #4072). The travel windows are the charter's (bundled), judged by the
    SAME rule the disruption offer uses (`disruption.offer`: a dated window covering the day or starting within its
    lead days; a window with null dates is pending the owner, listed, never a reason)."""
    from training import disruption

    day = str(day)[:10]
    st = status or {}
    sick_reasons, sick = _sick_day_signal(day, sick_days, st.get("sick_days"))
    deficit_reasons, deficit_block = _deficit_signal(deficit, st.get("deficit"))
    offer = disruption.offer(day, block_workouts=None, windows=travel_windows)
    travel_reasons = [f"{r} — the charter travel window (#5088)" for r in offer["reasons"]]
    sources = {
        "sick_days": sick,
        "deficit": deficit_block,
        "travel": {"state": _MEASURED, "pending_windows": offer["pending_windows"], "via": "the charter travel.windows"},
    }
    return {
        "read": True,
        "reasons": sick_reasons + deficit_reasons + travel_reasons,
        "sources": sources,
        # #4072: a source that failed or was not read cannot rule its event out — named, never read as "no event"
        "unread": [k for k, v in sources.items() if v.get("state") in (_READ_FAILED, _NOT_READ)],
        "issue": EVENT_ISSUE,
    }


_EVENTS_NOT_READ = {
    "read": False,
    "detail": "this copy was built without the event reads — plan_next_session stage 1 reads the sick days, the deficit band and the travel windows (#5146)",
}


def recommendation(
    *,
    day: str,
    records: list[dict[str, Any]] | None,
    fatigue: dict[str, Any] | None = None,
    readiness_low_streak_days: int | None = None,
    readiness_floor_days: int = 2,
    pain_note_sites: list[str] | None = None,
    extra_reasons: list[str] | None = None,
    events: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`deload_recommendation` for the plan packet: the signals that argue for a deload, the response
    that WOULD apply, and whether the owner's word applies it today. Never an applied cut by itself.

    `fatigue` is `critics_fatigue.assess`'s output (performance drop, readiness, consecutive soreness);
    `events` is `event_signals`'s (#5146) — its reasons join the list, its sources ride as `event_signals`."""
    reasons: list[str] = []
    if fatigue and fatigue.get("triggered"):
        reasons.extend(str(r) for r in fatigue.get("reasons") or [])
    elif readiness_low_streak_days is not None and readiness_low_streak_days >= readiness_floor_days:
        reasons.append(f"readiness below the floor on {readiness_low_streak_days} consecutive days (>= {readiness_floor_days})")
    for site in pain_note_sites or []:
        reasons.append(f"pain/soreness note on a drafted lift: {site}")
    reasons.extend(extra_reasons or [])
    reasons.extend(str(r) for r in (events or {}).get("reasons") or [])
    rec = active_record(records, day)
    pol = policy()
    wired = [t for t in pol["recommendation_triggers"] if t in TRIGGERS_WIRED]
    return {
        "active": bool(reasons),
        "triggers_wired": wired,
        "triggers_unwired": [t for t in pol["recommendation_triggers"] if t not in wired],
        "reasons": reasons,
        "event_signals": dict(events) if events else dict(_EVENTS_NOT_READ),
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


def for_plan(
    session: dict[str, Any],
    date: str,
    deload_records: list[dict[str, Any]] | None,
    fatigue: dict[str, Any] | None,
    readiness_low_streak_days: int | None,
    tripwires: list[dict[str, Any]],
    states: dict[str, Any] | None,
    event_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`constraint_block.deload_recommendation` (#5070; moved here from `plan_engine` for its module ceiling, #5146): the
    signals that argue for a deload and whether the owner's recorded word applies one today. NEVER an applied set cut by
    itself. Pain notes count only while the flag is tripped (a dismissed site is the owner's word that it is resolved).
    `event_inputs` is `{sick_days, deficit, status}` for `event_signals` — the travel windows are read on every call. An
    unreadable record store is stated."""
    pain = next((t for t in tripwires if t["id"] == "pain_flag_named_site" and t["state"] == "tripped"), None)
    rec = recommendation(
        day=date,
        records=deload_records,
        fatigue=fatigue,
        readiness_low_streak_days=readiness_low_streak_days,
        pain_note_sites=[str(x) for x in ((pain or {}).get("observed") or [])],
        events=event_signals(date, **(event_inputs or {})),
    )
    rec["records_state"] = ((states or {}).get("deload_records") or {}).get("state")
    session["deload_recommendation"] = rec  # also stamped on the served session
    return rec
