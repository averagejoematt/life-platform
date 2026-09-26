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
