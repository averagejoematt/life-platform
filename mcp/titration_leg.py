"""titration_leg.py — the weekly calorie titration run, a fail-soft leg on the nightly pre-draft (#5096).

HOST: `nightly_predraft.lambda_entry` (EventBridge 02:00Z daily on `life-platform-mcp-warmer`, the
pre-draft's own dead-man covers the schedule). The leg DECIDES only on a Pacific Friday, Saturday or
Sunday (`DECIDE_WEEKDAYS`), for the coming ISO week (`titration.target_week`), and writes the record
once — a conditional put, so Friday's decision stands and the weekend runs are `exists` retries that
only matter when Friday's run failed. Every other night it returns `not_decision_day`.

THE READS (the sanctioned ones, each failure named and turned into `insufficient_data`, never a guess):
  trend      `mcp.shared_quantities.loss_rate_lb_wk` — the shared 14-day least-squares rate over the
             completed days (the window ends yesterday), its newest weigh-in is the band's bodyweight; the
             charter's `trend_days` must equal its window, or the trend is withheld (`trend_window_mismatch`);
  guidance   `training.rate_band.guidance_cap_for` — the clinical record's bare cap (it outranks the band);
  steps      `training.steps_resolver.steps_range` over the charter's steps window, measured counts only;
  logs       complete MacroFactor days (a calorie total at or above the redlines' dark-day line) in the
             last 7 completed days, and in the redlines' first-step window;
  model      `tools_nutrition.expenditure_reconciliation` — which burn model matches the scale (context);
  history    the titration records of the last eight weeks (`titration.read_history`).

DRY RUN (the post-deploy proof, no write): from a checkout with read-only AWS credentials,
  python3 -c "import sys; sys.path[:0]=['lambdas','.']; import json; from mcp import titration_leg as t; print(json.dumps(t.run(dry_run=True), indent=1, default=str))"
prints the decision the coming week would get, whatever the weekday. Logs keys, actions and codes only.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from common.pacific_time import parse_day_key, shift_day_key

logger = logging.getLogger(__name__)

DECIDE_WEEKDAYS = (4, 5, 6)  # Friday, Saturday, Sunday (Pacific): Friday decides, the weekend retries
LOG_WINDOW_DAYS = 7


def _read(fn, *args, **kw) -> Tuple[Any, Optional[str]]:
    try:
        return fn(*args, **kw), None
    except Exception as e:  # noqa: BLE001 — every read failure is named on the decision's inputs
        logger.warning("[titration] read failed (%s)", type(e).__name__)
        return None, type(e).__name__


def _steps_fetch(source: str, start: str, end: str) -> list:
    from mcp import core

    return list(core.query_source_range(source, start, end) or [])


def complete_days(rows: Optional[list], min_kcal: Optional[float], value) -> Optional[set]:
    """The day keys whose logged calories are at or above `min_kcal` (the redlines' dark-day line: a day under it is
    dark, not complete). None when the rows or the line are unreadable."""
    if rows is None or min_kcal is None:
        return None
    per: Dict[str, float] = {}
    for r in rows:
        day = str(r.get("date") or r.get("sk") or "")[-10:]
        per[day] = max(per.get(day, 0.0), float(value(r, "calories") or 0))
    return {d for d, kcal in per.items() if kcal >= min_kcal}


def _count(days: Optional[set], end: str, window: int) -> Optional[int]:
    return None if days is None else sum(1 for d in days if shift_day_key(end, -(window - 1)) <= d <= end)


def gather(today: str) -> Dict[str, Any]:
    """Every input `titration.decide` takes, read for a run on `today`. Never raises."""
    from common.constants import EXPERIMENT_START_DATE
    from common.macrofactor_fields import macro_value
    from health import titration
    from training import rate_band
    from training.steps_resolver import steps_range

    from mcp import core, shared_quantities, tools_nutrition

    week = titration.target_week(today)
    errors: Dict[str, str] = {}
    lr, err = _read(shared_quantities.loss_rate_lb_wk, today, today=today)
    if err:
        errors["trend"] = err
    lr = lr or {}
    end = (lr.get("window") or {}).get("end") or shift_day_key(today, -1)
    weighins = (lr.get("validation") or {}).get("weigh_ins") or []
    weight = weighins[-1].get("weight_lbs") if weighins else None
    cap, err = _read(rate_band.guidance_cap_for, core.table)
    band = None
    if err:
        errors["guidance"] = err
    else:
        band = titration.band_for(float(weight) if weight else None, cap)
    cfg = titration.settings()
    if cfg.get("trend_days") is not None and int(cfg["trend_days"]) != shared_quantities.LOSS_RATE_WINDOW_DAYS:
        errors["trend"], lr = "trend_window_mismatch", {}  # the charter and the shared window disagree: no trend, a hold
    sw, srange = cfg.get("steps_window_days"), None
    if sw:  # an unreadable window reads nothing; decide holds on the missing rule value
        srange, err = _read(steps_range, shift_day_key(end, -(int(sw) - 1)), end, fetch=_steps_fetch, derived=False)
        if err:
            errors["steps"] = err
    first = int(cfg.get("first_step_complete_days") or 0)
    mf, err = _read(core.query_source, "macrofactor", shift_day_key(end, -(max(LOG_WINDOW_DAYS, first) - 1)), end)
    if err:
        errors["logs"] = err
    days = complete_days(mf, cfg.get("complete_log_kcal"), macro_value)
    rec, err = _read(tools_nutrition.expenditure_reconciliation, end)
    if err:
        errors["expenditure"] = err
    history, err = _read(titration.read_history, core.table, week)
    if err:
        errors["history"] = err
    start, wk = parse_day_key(EXPERIMENT_START_DATE), parse_day_key(week)
    return {
        "week": week,
        "trend_lb_wk": lr.get("value"),
        "trend_provisional": lr.get("provisional") if lr else None,
        "weight_lb": float(weight) if weight else None,
        "band": band,
        "steps_avg": ((srange or {}).get("summary") or {}).get("mean_steps"),
        "complete_log_days": _count(days, end, LOG_WINDOW_DAYS),
        "complete_days_trailing": _count(days, end, first) if first else None,
        "history": history or [],
        "expenditure_best_match": (rec or {}).get("best_match") if (rec or {}).get("best_match_actionable") else None,
        "experiment_day": (wk - start).days + 1 if (start and wk) else None,
        "read_errors": errors,
        "cfg": cfg,
    }


def run(today: Optional[str] = None, *, dry_run: bool = False) -> Dict[str, Any]:
    """Decide (and, unless `dry_run`, write) the coming week's titration record. `dry_run` decides on any weekday."""
    from common.pacific_time import pacific_today
    from health import titration

    from mcp import core

    today = today or pacific_today()
    d = parse_day_key(today)
    if not dry_run and (d is None or d.weekday() not in DECIDE_WEEKDAYS):
        return {"outcome": "not_decision_day", "today": today}
    if history_has(core.table, titration.target_week(today)) and not dry_run:
        return {"outcome": "exists", "week": titration.target_week(today)}
    decision = titration.decide(**gather(today))
    out = {
        "week": decision["week"],
        "action": decision["action"],
        "step_kcal": decision["step_kcal"],
        "reason_code": decision["reason_code"],
    }
    if dry_run:
        return {"outcome": "dry_run", **out, "decision": decision}
    out["outcome"] = titration.write_decision(core.table, decision, today)
    logger.info(
        "%s week=%s action=%s step=%s code=%s",
        titration.DECISION_LOG_MARK,
        out["week"],
        out["action"],
        out["step_kcal"],
        out["reason_code"],
    )
    return out


def history_has(table: Any, week: str) -> bool:
    from health import titration

    return titration.read_record(table, week) is not None


def nightly_leg(today: Optional[str] = None) -> Dict[str, Any]:
    """The fail-soft leg the nightly pre-draft calls. Never raises; never changes the pre-draft's outcome."""
    try:
        return run(today)
    except Exception as e:  # noqa: BLE001 — named on the run result; the dead-man row alerts a week with no record
        logger.warning("[titration] nightly leg failed (%s)", type(e).__name__)
        return {"outcome": "failed", "error": type(e).__name__}
