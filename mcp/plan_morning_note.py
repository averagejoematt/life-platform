"""plan_morning_note.py — the owner's morning note on `plan_next_session`'s constraint block (#4189).

WHY THIS EXISTS
  Two coaches asked for four words before the number ("how do I feel before Whoop tells
  me?"). The note reached `/api/morning_note`, the coach packet and the coach input, but the
  readiness/constraint block `plan_next_session` stage 1 hands the planning chat did not read
  it — the one surface where "felt recovered" next to the recovery tier changes a session.

ONE DERIVATION
  The note is read through `coach.morning_note` — `read_notes` over the coach lookback
  (today, or the morning before) and `coach_fact` over the newest row — the SAME derivation
  the coach packet's `morning_note` field and `coach.coach_input_facts` serve. This module
  never queries the partition itself and never reshapes the words.
  `tests/test_plan_morning_note_4189.py` pins the block's note equal to the packet's.

ABSENCE (ADR-104)
  measured / absent / read_failed — a failed read is never "no note", and no note is never a
  default. The comparison with the recovery tier is computed only when BOTH sides are known
  and the tier is unambiguous (GREEN or RED); YELLOW or an unknown tier compares nothing.
"""

from __future__ import annotations

from typing import Any

#: tiers that make `felt_recovered` comparable — YELLOW is neither recovered nor not.
_TIER_SAYS_RECOVERED = {"GREEN": True, "RED": False}


def morning_note_fact(target_date: str, table=None) -> dict[str, Any]:
    """`coach.morning_note.coach_fact` for `target_date`'s morning (or the one before).
    A malformed stored row RAISES (public_view's contract) — the caller reports it read_failed."""
    from coach import morning_note as mn

    if table is None:
        import mcp.core as core

        table = core.table
    rows = mn.read_notes(table, target_date, mn.COACH_LOOKBACK_DAYS)
    if rows is None:
        return mn.coach_fact(None, read_ok=False)
    return mn.coach_fact(rows[0] if rows else None)


def felt_vs_recovery_tier(fact: dict[str, Any], recovery_tier: str | None) -> dict[str, Any] | None:
    """His `felt_recovered` against the block's recovery tier — `agrees` is a bool only when both
    are known and the tier is GREEN or RED. None when there is no measured note with words."""
    if (fact or {}).get("state") != "measured" or not isinstance(fact.get("felt_recovered"), bool):
        return None
    tier_says = _TIER_SAYS_RECOVERED.get(str(recovery_tier or "").upper())
    return {
        "felt_recovered": fact["felt_recovered"],
        "recovery_tier": recovery_tier,
        "agrees": None if tier_says is None else fact["felt_recovered"] == tier_says,
    }


def attach(block: dict[str, Any], target_date: str, recovery_tier: str | None, reader=None) -> None:
    """Stamp `block["morning_note"]` and its read state on `block["inputs"]["morning_note"]`."""
    from training.plan_engine import ABSENT, MEASURED, READ_FAILED, error_label, input_status

    try:
        fact = (reader or morning_note_fact)(target_date)
    except Exception as e:  # noqa: BLE001 — a malformed row or a raise is a FAILED read, never absence
        status = input_status(READ_FAILED, error=error_label(e))
        block["morning_note"] = {"state": READ_FAILED, "error": status["error"]}
        block.setdefault("inputs", {})["morning_note"] = status
        return
    state = fact.get("state")
    if state == MEASURED:
        status = input_status(MEASURED, f"the owner's note for {fact.get('date')}", source="morning_note")
    elif state == ABSENT:
        status = input_status(ABSENT, fact.get("note"), source="morning_note")
    else:
        status = input_status(READ_FAILED, error=f"ReadError: {fact.get('note') or 'the morning-note query failed'}")
    view = dict(fact)
    compared = felt_vs_recovery_tier(fact, recovery_tier)
    if compared is not None:
        view["felt_vs_recovery_tier"] = compared
    block["morning_note"] = view
    block.setdefault("inputs", {})["morning_note"] = status
