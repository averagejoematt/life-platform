"""health/maintenance_week.py — planned maintenance weeks and the reverse diet (#5107, epic #5093).

The redlines' landing carried rehearsal maintenance weeks and a reverse diet in prose
(``owner_redlines.REDLINES["landing"]``) that nothing read. Owner ruling 2026-10-23: R3 YES — the
late-December trip is a planned maintenance week (eat at maintenance; pass when the weight after it is
within the charter's band of the weight before it); R4 NO — no second rehearsal at an intermediate
weight. The rule's values are the charter's ``nutrition.maintenance_weeks`` and
``nutrition.reverse_diet`` blocks; this module is their one reader, called by ``health.titration`` so
there is ONE weekly decision (no double rule beside the band).

THE PIECES (all pure; every input is a value the caller already read):

  windows      ``settings`` resolves each window's dates: its own ``start``/``end`` when both are set,
               else the named ``travel.windows`` entry's (one place for the trip's dates). A window
               with no dates is INERT — listed as unscheduled, it changes nothing (the dates are the
               owner's to set).
  the week     ``intercept`` — a week the window touches HOLDS the ordinary target (it carries forward
               unchanged, so the cut resumes at the pre-window number) and the record carries
               ``maintenance_kcal`` + ``maintenance_dates``; ``health.calorie_target.resolve`` serves
               the maintenance kcal on those dates. Maintenance is the expenditure reconciliation's
               best-matching model (the estimate the titration engine already reads), actionable only
               on a non-provisional loss-rate window — never a number written in the charter. No
               actionable estimate: the dates carry the base target with a warning, never a guess.
  the trend    a trend read whose window holds a maintenance date is not acted on (``maintenance_in_trend``):
               a week of maintenance food and water would read as a stall.
  the grade    ``grade`` — the start weight is the latest weigh-in in the reach before or on the first day;
               the end weight the earliest in the reach after the last day; pass inside the band.
  reverse diet from the ISO week holding ``reverse_diet.starts_on``: food steps UP each week by the
               titration's own step sizing (the miss above the settle line x kcal_per_lb_wk, inside
               min..max step) until the 14-day trend sits inside +/- the settle line; the cut band, the
               walking-first rule and the planned minimum do not govern there.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

CHARTER_PATH = "nutrition.maintenance_weeks"
REVERSE_PATH = "nutrition.reverse_diet"
TRAVEL_PATH = "travel.windows"

MAINTENANCE_WEEK = "maintenance_week"
MAINTENANCE_IN_TREND = "maintenance_in_trend"
REVERSE_STEP = "reverse_diet_step"
REVERSE_ENTRY = "reverse_diet_entry"
REVERSE_SETTLED = "reverse_diet_settled"
REVERSE_GAINING = "reverse_diet_gaining"
REVERSE_CODES = (REVERSE_STEP, REVERSE_ENTRY, REVERSE_SETTLED, REVERSE_GAINING)

PASS, FAIL, PENDING, UNKNOWN = "pass", "fail", "pending", "unknown"


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _d(s: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _iso(d: date) -> str:
    return d.isoformat()


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _window(w: Mapping[str, Any], travel: Sequence[Any]) -> Dict[str, Any]:
    own_lo, own_hi = _d(w.get("start")), _d(w.get("end"))
    basis = "the window's own dates"
    if not (own_lo and own_hi):
        tw = next((t for t in travel if isinstance(t, dict) and t.get("label") == w.get("travel_window")), None) or {}
        own_lo, own_hi = _d(tw.get("start")), _d(tw.get("end"))
        basis = f"travel window '{w.get('travel_window')}'"
    dated = bool(own_lo and own_hi and own_lo <= own_hi)
    return {
        "label": w.get("label"),
        "start": _iso(own_lo) if dated and own_lo else None,
        "end": _iso(own_hi) if dated and own_hi else None,
        "dated": dated,
        "dates_basis": basis if dated else "no dates set (owner-set): inert",
    }


def settings(read: Callable[[str], Any]) -> Dict[str, Any]:
    """The two charter blocks, resolved. An absent block is ``readable: False`` and changes nothing; an unreadable
    number is None (no fallback literal) and the branch that needs it holds or grades ``unknown``."""
    block = read(CHARTER_PATH)
    block = block if isinstance(block, dict) else {}
    travel = read(TRAVEL_PATH)
    travel = travel if isinstance(travel, list) else []
    rev = read(REVERSE_PATH)
    rev = rev if isinstance(rev, dict) else {}
    windows = [_window(w, travel) for w in block.get("windows") or [] if isinstance(w, dict)]
    starts = _d(rev.get("starts_on"))
    return {
        "readable": bool(block),
        "windows": windows,
        "pass_band_lb": _num(block.get("pass_band_lb")),
        "reach_days": _num(block.get("weigh_in_reach_days")),
        "reverse": {
            "readable": bool(rev),
            "starts_on": _iso(starts) if starts else None,
            "settle_lb_wk": _num(rev.get("settle_trend_lb_wk")),
            "entry_step_kcal": _num(rev.get("entry_step_kcal")),
        },
    }


def dated(cfg: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [w for w in ((cfg or {}).get("windows") or []) if w.get("dated")]


def dates_in(windows: Iterable[Mapping[str, Any]], lo: date, hi: date) -> List[Tuple[str, str]]:
    """(date, label) for every window date inside lo..hi, in date order."""
    out: List[Tuple[str, str]] = []
    for w in windows:
        a, b = _d(w.get("start")), _d(w.get("end"))
        if not (a and b):
            continue
        d = max(a, lo)
        while d <= min(b, hi):
            out.append((_iso(d), str(w.get("label"))))
            d += timedelta(days=1)
    return sorted(out)


def estimate(reconciliation: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Maintenance from the expenditure reconciliation (``health.expenditure_reconciler.reconcile``): the best-matching
    model's kcal, when its loss-rate window is not provisional. ``kcal`` None with a ``reason`` otherwise."""
    rec = dict(reconciliation or {})
    best = rec.get("best_match")
    kcal = _num(((rec.get("models") or {}).get(best) or {}).get("kcal")) if best else None
    scale = _num((rec.get("scale_implied") or {}).get("kcal"))
    if rec.get("read_failed"):
        return {"kcal": None, "reason": f"the expenditure reconciliation read failed ({str(rec['read_failed'])[:60]})"}
    if not best or kcal is None or kcal <= 0:
        return {"kcal": None, "reason": "no model estimate matched against the scale", "scale_implied_kcal": scale}
    if not rec.get("best_match_actionable"):
        return {"kcal": None, "reason": "provisional loss-rate window: the best match is reported, not argued from", "model": best}
    return {"kcal": int(round(kcal)), "model": best, "scale_implied_kcal": int(round(scale)) if scale else None}


def grade(
    window: Mapping[str, Any], weigh_ins: Iterable[Tuple[str, float]], run_day: str, cfg: Mapping[str, Any]
) -> Optional[Dict[str, Any]]:
    """The window's pass/fail once it has ended (None before its last day has passed). ``pending`` while the reach after
    the window is still open with no weigh-in; ``unknown`` when either weight is missing or a rule value is unread."""
    a, b, today = _d(window.get("start")), _d(window.get("end")), _d(run_day)
    if not (a and b and today) or today <= b:
        return None
    band, reach = cfg.get("pass_band_lb"), cfg.get("reach_days")
    out: Dict[str, Any] = {"label": window.get("label"), "start": _iso(a), "end": _iso(b), "pass_band_lb": band, "state": UNKNOWN}
    if band is None or reach is None:
        out["reason"] = "the charter's pass band or weigh-in reach is unreadable"
        return out
    pts = sorted((str(d)[:10], float(w)) for d, w in weigh_ins if _d(d) and _num(w))
    before = [p for p in pts if _iso(a - timedelta(days=int(reach))) <= p[0] <= _iso(a)]
    after = [p for p in pts if _iso(b + timedelta(days=1)) <= p[0] <= _iso(b + timedelta(days=int(reach)))]
    if before:
        out["start_date"], out["start_weight_lb"] = before[-1]
    if after:
        out["end_date"], out["end_weight_lb"] = after[0]
    if not before:
        out["reason"] = f"no weigh-in in the {int(reach)} days up to the window's first day"
        return out
    if not after:
        closes = b + timedelta(days=int(reach))
        out["state"] = PENDING if today <= closes else UNKNOWN
        out["reason"] = f"no weigh-in yet in the {int(reach)} days after the window's last day"
        return out
    change = round(out["end_weight_lb"] - out["start_weight_lb"], 1)
    out["change_lb"] = change
    out["state"] = PASS if abs(change) <= band else FAIL
    out["reason"] = f"{change:+.1f} lb across the window against the +/-{band:g} lb pass band"
    return out


def _maintenance_week(week: date, windows: List[Dict[str, Any]], c: Mapping[str, Any], est: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    hits = dates_in(windows, week, week + timedelta(days=6))
    if not hits:
        return None
    labels = sorted({lbl for _d_, lbl in hits})
    kcal = est.get("kcal")
    upd: Dict[str, Any] = {
        "reason_code": MAINTENANCE_WEEK,
        "maintenance_dates": [d for d, _l in hits],
        "maintenance_label": ", ".join(labels),
        "maintenance_kcal": kcal,
        "maintenance_basis": f"expenditure reconciliation best match {est.get('model')}" if kcal else None,
    }
    band, target = c.get("band_kcal"), c.get("target_kcal")
    if kcal and band and None not in band and target is not None:
        upd["maintenance_band_low"], upd["maintenance_band_high"] = int(band[0] + kcal - target), int(band[1] + kcal - target)
    if kcal:
        upd["reason"] = f"planned maintenance week ({upd['maintenance_label']}): eat at maintenance on its dates; the target holds"
        upd["detail"] = f"maintenance {kcal} kcal on {len(hits)} date(s), {upd['maintenance_basis']}"
    else:
        upd["reason"] = f"planned maintenance week ({upd['maintenance_label']}): no readable maintenance estimate, the target holds"
        upd["detail"] = str(est.get("reason"))
        upd["warning"] = "maintenance week with no actionable expenditure estimate: the base target serves its dates (never a guess)"
    return upd


def _reverse(
    week: date, c: Mapping[str, Any], prior: Sequence[Mapping[str, Any]], base: float, inp: Mapping[str, Any], step: Callable[[float], int]
) -> Optional[Dict[str, Any]]:
    rev = (c.get("maintenance") or {}).get("reverse") or {}
    start = _d(rev.get("starts_on"))
    if not start or week < _monday(start):
        return None
    settle, entry = rev.get("settle_lb_wk"), rev.get("entry_step_kcal")
    trend = inp.get("trend_lb_wk")
    if settle is None:
        return {"reason_code": "insufficient_data", "reason": "insufficient data: the reverse diet's settle line is unreadable"}
    if trend is None or inp.get("trend_provisional") is not False:
        return {"reason_code": "insufficient_data", "reason": "insufficient data: reverse diet, no measured 14-day trend this week"}
    logs, need = inp.get("complete_log_days"), c.get("min_complete_logs")
    if logs is None or need is None or logs < need:
        return {"reason_code": "insufficient_data", "reason": "insufficient data: reverse diet, too few complete food logs in the week"}
    detail = f"reverse diet from {rev['starts_on']}: trend {trend:+.2f} lb/wk against the settle line +/-{settle:g} lb/wk"
    started = any(r.get("reason_code") in REVERSE_CODES for r in prior)
    if entry and not started:
        return {
            "action": "up",
            "step_kcal": int(entry),
            "new_target_kcal": int(base + entry),
            "reason_code": REVERSE_ENTRY,
            "reason": f"+{int(entry)} kcal: the reverse diet's entry step",
            "detail": detail,
        }
    if abs(trend) <= settle:
        return {"reason_code": REVERSE_SETTLED, "reason": "reverse diet: the trend is inside the settle line, hold", "detail": detail}
    if trend < -settle:
        return {
            "reason_code": REVERSE_GAINING,
            "detail": detail,
            "warning": "gaining faster than the reverse diet's settle line",
            "reason": "WARNING: reverse diet, gaining past the settle line: the target holds (the redlines' landing overshoot rules govern)",
        }
    s = step(trend - settle)
    return {
        "action": "up",
        "step_kcal": s,
        "new_target_kcal": int(base + s),
        "reason_code": REVERSE_STEP,
        "reason": f"+{s} kcal: reverse diet, still losing past the settle line",
        "detail": detail,
    }


def intercept(
    *,
    week: str,
    base: float,
    cfg: Mapping[str, Any],
    prior: Sequence[Mapping[str, Any]],
    inputs: Mapping[str, Any],
    step: Callable[[float], int],
) -> Optional[Dict[str, Any]]:
    """The fields that replace the ordinary titration decision for ``week``, or None (the ordinary rule decides).
    Order: a maintenance week, a trend read across one, the reverse diet."""
    m = cfg.get("maintenance") or {}
    wk = _d(week)
    if not m or not wk:
        return None
    windows = dated(m)
    upd = _maintenance_week(wk, windows, cfg, inputs.get("maintenance_estimate") or {})
    if upd is None:
        tw = inputs.get("trend_window") or {}
        lo, hi = _d(tw.get("start")), _d(tw.get("end"))
        touched = dates_in(windows, lo, hi) if (lo and hi) else []
        if touched:
            upd = {
                "reason_code": MAINTENANCE_IN_TREND,
                "reason": "the trend window holds maintenance-week dates: the target holds until it clears them",
                "detail": f"{len(touched)} maintenance date(s) in the trend window {tw.get('start')}..{tw.get('end')}",
            }
    if upd is None:
        upd = _reverse(wk, cfg, prior, base, inputs, step)
    return upd


def resolve_day(record: Optional[Mapping[str, Any]], day: str) -> Optional[Dict[str, Any]]:
    """For ``calorie_target.resolve``: the maintenance serving of ``day`` from its week's titration record, or None.
    ``kcal`` None = a maintenance date with no readable estimate (the base serves, and says so)."""
    if not record or day not in [str(x)[:10] for x in record.get("maintenance_dates") or []]:
        return None
    kcal = _num(record.get("maintenance_kcal"))
    lo, hi = _num(record.get("maintenance_band_low")), _num(record.get("maintenance_band_high"))
    return {
        "kcal": kcal if kcal and kcal > 0 else None,
        "band": (int(lo), int(hi)) if lo is not None and hi is not None else None,
        "label": record.get("maintenance_label"),
        "basis": record.get("maintenance_basis"),
    }


def email_line(record: Optional[Mapping[str, Any]]) -> str:
    """One plain line for the owner's nutrition email: the maintenance dates and any window grades on the record."""
    rec = record or {}
    parts: List[str] = []
    if rec.get("maintenance_dates"):
        dates = rec["maintenance_dates"]
        kcal = rec.get("maintenance_kcal")
        what = f"maintenance {kcal} kcal" if kcal else "no maintenance estimate, base target"
        parts.append(f"Planned maintenance ({rec.get('maintenance_label')}): {dates[0]}..{dates[-1]}, {what}.")
    for g in rec.get("maintenance_grades") or []:
        parts.append(f"Maintenance week {g.get('label')}: {str(g.get('state')).upper()} — {g.get('reason')}.")
    return " ".join(parts)
