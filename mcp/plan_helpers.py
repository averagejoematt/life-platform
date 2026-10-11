"""Small pure helpers split out of `mcp/tools_plan.py` to keep it under the 1000-line
module-size ceiling (tests/test_module_size_guard.py) after #4104 + #4105 landed together.
`tools_plan` re-imports every name, so callers and behaviour are unchanged."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def _safe(fn, *a, **kw):
    """Call a tool defensively — a reader that fails yields None, never a default. (Moved from tools_plan, #4161.)"""
    try:
        return fn(*a, **kw)
    except Exception:  # noqa: BLE001
        return None


def _union_evidence_rows(performed: list[dict[str, Any]], draft: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Performed movements UNION the draft's, keyed by template id (#4051).

    The draft row wins where it has something to say — it carries the anchor-lift trend the
    performed set does not compute — but it never overwrites a performed value with an
    absent one, which is how a dark per-movement read (`pain_flag_any: None`) used to erase
    a flag the batch read found.
    """
    out: dict[str, dict[str, Any]] = {}
    for r in performed or []:
        out[str(r.get("template_id") or r.get("label") or "")] = dict(r)
    for r in draft or []:
        key = str(r.get("template_id") or r.get("label") or "")
        merged = dict(out.get(key) or {})
        for k, v in r.items():
            if v not in (None, [], "", {}) or k not in merged:
                merged[k] = v
        out[key] = merged
    return list(out.values())


def _catalog_and_ceiling() -> tuple[dict[str, Any] | None, int]:
    """(movement catalog `movements` dict or None, the week grid's skill ceiling) — #4064."""
    try:
        from training.program_seam import resolve_week_grid
        from training.routine_generator import _load_json

        catalog = (_load_json("movement_catalog.json") or {}).get("movements")
        ceiling = int(resolve_week_grid(_load_json).week.get("skill_ceiling", 2))
        return (catalog if isinstance(catalog, dict) else None), ceiling
    except Exception as e:  # noqa: BLE001 — a missing catalog degrades the session to patterns, never fails the plan
        logger.warning(f"movement catalog unreadable for plan_next_session: {e}")
        return None, 2


def _resolver():
    from mcp.tools_hevy_routine import _make_resolver

    return _make_resolver()


def _minus_days(date_str: str, days: int) -> str:
    """#3751: day-key arithmetic belongs to the Pacific frame, not to this module.

    Was a local `date.fromisoformat(...) - timedelta(...)`, which is the idiom #3609's
    registry exists to inventory. `shift_day_key` is that operation, named once, with
    the same return-it-unchanged fallback this function already had.
    """
    from common.pacific_time import shift_day_key

    return shift_day_key(date_str, -days)


def _days_between(a: str | None, b: str) -> int | None:
    """Whole days from `a` to `b` (YYYY-MM-DD); None when `a` is absent or unparseable.
    Moved from mcp/tools_plan.py under the #1665 size ratchet (#4149); re-exported there."""
    try:
        return (datetime.strptime(b, "%Y-%m-%d") - datetime.strptime(str(a)[:10], "%Y-%m-%d")).days
    except (TypeError, ValueError):
        return None


# ── #4189: the owner's morning note on the readiness/constraint block ────────────────────────
# Two coaches asked for four words before the number ("how do I feel before Whoop tells me?").
# The note reached /api/morning_note, the coach packet and the coach input, but the block
# `plan_next_session` stage 1 hands the planning chat did not read it. It is read here through
# `coach.morning_note` — `read_notes` over the coach lookback (today, or the morning before) and
# `coach_fact` over the newest row: the SAME derivation the coach packet's `morning_note` field
# and `coach.coach_input_facts` serve; nothing here queries the partition or reshapes the words
# (pinned equal to the packet's by tests/test_plan_morning_note_4189.py). Three read states,
# measured / absent / read_failed (ADR-104): a failed read is never "no note".

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


def attach_morning_note(block: dict[str, Any], target_date: str, recovery_tier: str | None, reader=None) -> None:
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
