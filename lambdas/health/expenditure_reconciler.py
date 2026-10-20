"""lambdas/health/expenditure_reconciler.py — which burn estimate matches the scale (#5097).

The platform carries THREE estimates of daily energy expenditure, and before this module
nothing set them against each other:

  * ``macrofactor_adaptive`` — MacroFactor's own adaptive expenditure, the vendor field
    ``expenditure_kcal`` on the macrofactor DATE# rows. Only the daily-summary export
    carries it (``ingestion/macrofactor_lambda.py``), so it can be weeks old; its
    freshness is the ``field_feeds`` facet of ``macrofactor`` in
    ``ingestion/source_registry.py`` and is reported on every read.
  * ``platform_measured`` — ``health.tdee.METHOD``: Mifflin-St Jeor BMR + the measured
    worked-set exercise term (ADR-152). The caller supplies it (it needs the exercise
    reads), so this module never recomputes it.
  * ``platform_flat`` — ``health.process_milestones.mifflin_tdee_estimate``: the body-
    weight-only Mifflin x 1.55 estimate the strength-in-deficit milestone falls back to.

THE REFERENCE is the scale: mean logged intake over the window + 3500 kcal per lb of the
SHARED loss rate (``mcp.shared_quantities.loss_rate_lb_wk`` — the 14-day least-squares
rate, water weeks excluded; this module takes it as an input and never fits its own),
back-solved by ``health.tdee.tdee_from_trend``. Each model's signed error is
``model - scale``; ``best_match`` is the smallest absolute error; ``disagreement`` is the
spread between the models above the charter's ``nutrition.expenditure.
disagreement_threshold_kcal``.

Capture-all (owner rule 2026-10-04): the ingestion writers store every vendor field and
pick nothing; THIS is the read side where the comparison lives. It decides nothing
either — the calorie resolver (#5095) and the titration engine (#5096) read the verdict.

Pure: readers are injected, no boto3, no clock reads (``today`` is an argument). The two
charter values are read through ``training_charter.charter_value``; an unreadable charter
leaves ``threshold_kcal`` None and ``disagreement`` None — never a default number.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Optional

from common.pacific_time import parse_day_key  # THE calendar-day parse (#3741)

from health import tdee as tdee_core

METHOD = "expenditure_reconciliation_vs_scale_trend"

MODEL_MACROFACTOR = "macrofactor_adaptive"
MODEL_MEASURED = "platform_measured"
MODEL_FLAT = "platform_flat"
MODELS = (MODEL_MACROFACTOR, MODEL_MEASURED, MODEL_FLAT)

#: The vendor field the macrofactor ingester writes the adaptive expenditure to.
MF_EXPENDITURE_FIELD = "expenditure_kcal"
#: The `field_feeds` key of the macrofactor registry entry.
FEED_KEY = "adaptive_expenditure"

CHARTER_THRESHOLD = "nutrition.expenditure.disagreement_threshold_kcal"
CHARTER_MIN_DAYS = "nutrition.expenditure.min_logged_days"


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN is absent


def _day(row: Mapping[str, Any]) -> str:
    return str(row.get("date") or str(row.get("sk") or "").replace("DATE#", ""))[:10]


def _live(rows: Optional[Iterable[Mapping[str, Any]]]) -> list:
    return [r for r in rows or () if not r.get("tombstone") and len(_day(r)) == 10]


def settings(charter_value: Optional[Callable[[str, Any], Any]] = None) -> dict:
    """The two charter tunables. ``None`` for any the charter cannot supply."""
    read: Callable[[str, Any], Any]
    if charter_value is not None:
        read = charter_value
    else:
        try:
            from training.training_charter import charter_value as read  # lazy: a config read, not data I/O
        except Exception:  # noqa: BLE001 — an unloadable charter is an absent one
            return {"threshold_kcal": None, "min_logged_days": None, "charter_version": None}
    try:
        from training.training_charter import charter_version

        version = charter_version()
    except Exception:  # noqa: BLE001
        version = None
    return {
        "threshold_kcal": _num(read(CHARTER_THRESHOLD, None)),
        "min_logged_days": _num(read(CHARTER_MIN_DAYS, None)),
        "charter_version": version,
    }


def feed_freshness(mf_rows: Optional[Iterable[Mapping[str, Any]]], today: str, lookback_start: str) -> dict:
    """The adaptive-expenditure feed's last-seen day over the rows read, judged by the
    registry's ``field_feeds`` row. ``last_seen`` None means not seen since
    ``lookback_start`` — reported as a floor, never a fabricated age (ADR-104)."""
    from ingestion.source_registry import field_feed_thresholds

    feed: dict[str, Any] = next((f for f in field_feed_thresholds("macrofactor") if f.get("key") == FEED_KEY), {})
    fields = feed.get("fields") or [MF_EXPENDITURE_FIELD]
    seen = sorted(_day(r) for r in _live(mf_rows) if any((_num(r.get(f)) or 0) > 0 for f in fields))
    last = seen[-1] if seen else None
    stale_days = feed.get("stale_days")
    out = {"key": FEED_KEY, "fields": fields, "stale_days": stale_days, "last_seen": last, "age_days": None}
    t, other = parse_day_key(today), parse_day_key(last or lookback_start)
    if t and other:
        out["age_days" if last else "age_floor_days"] = (t - other).days
    age = out["age_days"] if last else out.get("age_floor_days")
    out["stale"] = None if (age is None or stale_days is None) else bool(age > stale_days)
    return out


def scale_implied(
    mf_rows: Optional[Iterable[Mapping[str, Any]]], loss_rate: Optional[Mapping[str, Any]], min_logged_days: Optional[float]
) -> dict:
    """Expenditure implied by the scale over the loss rate's own window:
    ``tdee.tdee_from_trend(mean intake, -rate, span)``. ``kcal`` None with a ``reason``
    whenever an input is missing or too thin."""
    lr = dict(loss_rate or {})
    win = lr.get("window") or {}
    start, end = win.get("start"), win.get("end")
    rate = _num(lr.get("value"))
    out: dict = {
        "kcal": None,
        "loss_rate_lb_wk": rate,
        "loss_rate_method": lr.get("method"),
        "provisional": bool(lr.get("provisional", True)),
        "window": {"start": start, "end": end},
        "intake_days": 0,
        "intake_avg_kcal": None,
    }
    if not (start and end):
        out["reason"] = "no loss-rate window"
        return out
    intake = [_num(r.get("total_calories_kcal")) for r in _live(mf_rows) if start <= _day(r) <= end]
    intake = [v for v in intake if v is not None]
    out["intake_days"] = len(intake)
    if intake:
        out["intake_avg_kcal"] = round(sum(intake) / len(intake))
    if rate is None:
        out["reason"] = lr.get("reason") or "no loss rate for the window"
        return out
    if min_logged_days is None:
        out["reason"] = "charter minimum logged days unreadable"
        return out
    if len(intake) < min_logged_days:
        out["reason"] = f"{len(intake)} logged intake day(s) in {start}..{end}, under the {int(min_logged_days)} the read needs"
        return out
    back = tdee_core.tdee_from_trend(sum(intake) / len(intake), -rate, lr.get("span_days"))
    if back:
        out["kcal"] = back["tdee"]
        out["method"] = back["method"]
        out["basis"] = back["basis"]
    return out


def macrofactor_window(mf_rows: Optional[Iterable[Mapping[str, Any]]], start: Optional[str], end: Optional[str]) -> dict:
    """Mean of the vendor's adaptive expenditure over the window's days that carry it."""
    vals: list[tuple[str, float]] = []
    for r in _live(mf_rows) if (start and end) else ():
        v = _num(r.get(MF_EXPENDITURE_FIELD))
        if v is not None and v > 0 and start <= _day(r) <= end:
            vals.append((_day(r), v))
    vals.sort()
    out: dict = {"kcal": None, "days": len(vals), "method": f"mean of macrofactor.{MF_EXPENDITURE_FIELD} over the window"}
    if vals:
        out["kcal"] = round(sum(v for _, v in vals) / len(vals))
        out["latest"] = {"date": vals[-1][0], "kcal": round(vals[-1][1])}
    else:
        out["reason"] = "no MacroFactor expenditure in the window (only the daily-summary export carries it)"
    return out


def reconcile(
    *,
    mf_rows: Optional[Iterable[Mapping[str, Any]]],
    loss_rate: Optional[Mapping[str, Any]],
    model_measured_kcal: Any,
    model_flat_kcal: Any,
    today: str,
    lookback_start: Optional[str] = None,
    cfg: Optional[Mapping[str, Any]] = None,
) -> dict:
    """THE verdict. Every input is a value; see the module docstring for each one."""
    cfg = dict(cfg if cfg is not None else settings())
    rows = list(mf_rows or ())
    scale = scale_implied(rows, loss_rate, cfg.get("min_logged_days"))
    win = scale["window"]
    mf = macrofactor_window(rows, win["start"], win["end"])
    models: dict = {
        MODEL_MACROFACTOR: mf,
        MODEL_MEASURED: {"kcal": _rnd(model_measured_kcal), "method": tdee_core.METHOD},
        MODEL_FLAT: {
            "kcal": _rnd(model_flat_kcal),
            "method": "process_milestones.mifflin_tdee_estimate (Mifflin x 1.55, body weight only)",
        },
    }
    ref = scale["kcal"]
    for m in models.values():
        m["error_kcal"] = (m["kcal"] - ref) if (m["kcal"] is not None and ref is not None) else None
    have = {k: m["kcal"] for k, m in models.items() if m["kcal"] is not None}
    spread = (max(have.values()) - min(have.values())) if len(have) >= 2 else None
    threshold = cfg.get("threshold_kcal")
    disagreement = None if (spread is None or threshold is None) else bool(spread > threshold)
    errs = {k: abs(m["error_kcal"]) for k, m in models.items() if m["error_kcal"] is not None}
    best = min(errs, key=lambda k: (errs[k], MODELS.index(k))) if errs else None
    out = {
        "method": METHOD,
        "charter_version": cfg.get("charter_version"),
        "window": win,
        "scale_implied": scale,
        "models": models,
        "spread_kcal": spread,
        "threshold_kcal": int(threshold) if threshold is not None else None,
        "disagreement": disagreement,
        "best_match": best,
        # The shared loss rate's own honesty rule: a provisional window is reported, never argued from.
        "best_match_actionable": bool(best and not scale["provisional"]),
        "feed": feed_freshness(rows, today, lookback_start or win["start"] or today),
    }
    out["verdict"] = _verdict(out)
    return out


def _rnd(v: Any) -> Optional[int]:
    f = _num(v)
    return int(round(f)) if f is not None and f > 0 else None


def _verdict(out: Mapping[str, Any]) -> str:
    best, models, scale = out["best_match"], out["models"], out["scale_implied"]
    if scale["kcal"] is None:
        return f"no scale reference: {scale.get('reason')}"
    if best is None:
        return "no model estimate to compare"
    line = f"scale implies {scale['kcal']} kcal/day; closest is {best} ({models[best]['kcal']}, error {models[best]['error_kcal']:+d})"
    if out["disagreement"]:
        line = f"models disagree by {out['spread_kcal']} kcal (> {out['threshold_kcal']}): " + line
    if not out["best_match_actionable"]:
        line += " — provisional loss-rate window, reported not argued from"
    return line


def reconcile_window(
    day: str,
    *,
    read_loss_rate: Callable[[str], Mapping[str, Any]],
    read_macrofactor: Callable[[str, str], list],
    model_measured_kcal: Any,
    model_flat: Optional[Callable[[Any], Any]] = None,
    lookback_days: int = 28,
    cfg: Optional[Mapping[str, Any]] = None,
) -> dict:
    """The read for `day`: the shared loss rate (`read_loss_rate(day)`), the macrofactor
    rows from `lookback_days` before the window end (`read_macrofactor(start, end)` — the
    longer lookback is for the feed's last-seen day), the platform-flat estimate at the
    window's latest weigh-in. Every reader is injected; nothing here touches AWS."""
    from common.pacific_time import shift_day_key

    lr = dict(read_loss_rate(day) or {})
    end = (lr.get("window") or {}).get("end") or day
    start = shift_day_key(end, -(lookback_days - 1))
    rows = read_macrofactor(start, end) or []
    weighins = ((lr.get("validation") or {}).get("weigh_ins")) or []
    weight = weighins[-1].get("weight_lbs") if weighins else None
    flat_fn: Callable[[Any], Any]
    if model_flat is not None:
        flat_fn = model_flat
    else:
        from health.process_milestones import mifflin_tdee_estimate as flat_fn
    flat = flat_fn(weight) if weight is not None else None
    return reconcile(
        mf_rows=rows,
        loss_rate=lr,
        model_measured_kcal=model_measured_kcal,
        model_flat_kcal=flat,
        today=end,
        lookback_start=start,
        cfg=cfg,
    )
