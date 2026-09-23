"""mcp/nutrition_critics_inputs.py — the MCP-layer resolver for `health.nutrition_critics` (#3754 boxes 3+4).

The critic module is pure and takes a plain dict. This is the ONE place that dict is
assembled from the platform's readers, so both owner-facing surfaces —
`get_deficit_sustainability` and `plan_next_session` — carry the SAME block built the
same way:

  * intake / protein by day        — the MacroFactor partition, 14 days ending `end_date`
  * lifting-day flags              — the Hevy partition (a day with a non-cardio exercise)
  * weight + the 14-day loss rate  — the Withings partition through THE loss-rate definition,
                                     `mcp.shared_quantities.loss_rate_from_rows` (#4068: 14 days,
                                     water weeks 1–2 excluded, least-squares) — the same number
                                     `rate_advocate` reads off `get_benchmark`
  * weekly loss rates              — that definition over each trailing 7-day week
  * walking hr this week / last    — `mcp.shared_quantities.weekly_walking_hours` (Strava UNION
                                     Hevy, de-duplicated in time, 7 completed days), called twice
  * IC-29 adaptation severity      — `mcp.tools_nutrition._get_metabolic_adaptation`
  * already-logged decisions       — `get_decisions` rows, trailing 14 days, source
                                     `nutrition_critics`, for box 4's dedup

A reader that raises yields None for its inputs — the critic names them in `unknown`
(ADR-104: an unreadable input is not a measurement of zero). Nothing here writes.
"""

from __future__ import annotations

from typing import Any, Callable

from common.constants import day_n
from common.pacific_time import shift_day_key
from health import nutrition_critics, weight_trend
from training import walking_volume

from mcp import shared_quantities
from mcp.core import query_source

SERIES_DAYS = 14
DECISIONS_LOOKBACK_DAYS = 14


def _safe(fn: Callable[..., Any], *a: Any, **kw: Any) -> Any:
    try:
        return fn(*a, **kw)
    except Exception:  # noqa: BLE001 — an unreadable input is reported as unknown by the critic, never raised past it
        return None


def _num(v: Any) -> float | None:
    if v in (None, "") or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def day_keys(end_date: str, n: int = SERIES_DAYS) -> list[str]:
    """The `n` Pacific day keys ending at `end_date`, oldest first."""
    return [shift_day_key(end_date, -(n - 1 - i)) for i in range(n)]


def macrofactor_series(rows: list[dict[str, Any]] | None, keys: list[str]) -> tuple[list[float | None] | None, list[float | None] | None]:
    """(intake kcal by day, protein g by day) over `keys`; None per unlogged day; (None, None)
    when the partition could not be read at all."""
    if rows is None:
        return None, None
    by_day: dict[str, dict[str, Any]] = {}
    for r in rows:
        d = str(r.get("date") or str(r.get("sk") or "").replace("DATE#", ""))[:10]
        if d:
            by_day[d] = r
    intake = [_num((by_day.get(k) or {}).get("total_calories_kcal")) for k in keys]
    protein = [_num((by_day.get(k) or {}).get("total_protein_g")) for k in keys]
    return intake, protein


def lifting_day_flags(workouts: list[dict[str, Any]] | None, keys: list[str]) -> list[bool] | None:
    """True on a day with at least one Hevy exercise that is NOT a cardio modality and carries
    a set — the same modality lexicon `training.walking_volume` uses, so a treadmill-only
    session is not a lifting day. None when the partition could not be read."""
    if workouts is None:
        return None
    lifted: set[str] = set()
    for w in workouts:
        day = str(w.get("date") or str(w.get("sk") or "").replace("DATE#", ""))[:10]
        for ex in w.get("exercises") or []:
            name = (ex.get("name") or ex.get("exercise_name") or "").strip()
            if walking_volume._modality_for_hevy(name) is not None:
                continue
            if any((_num(s.get("reps")) or 0) > 0 or _num(s.get("weight_kg")) is not None for s in ex.get("sets") or []):
                lifted.add(day)
                break
    return [k in lifted for k in keys]


def withings_trend(rows: list[dict[str, Any]] | None, keys: list[str]) -> dict[str, Any]:
    """Latest weight, the signed 14-day trend (negative = losing) with its n/span/provisional
    flag, and the loss rate over each trailing 7-day week — all from THE loss-rate definition
    (`mcp.shared_quantities`, #4068). It was `health.tdee.weight_trend_lb_per_wk`'s
    first-vs-last endpoint over the whole window, water weeks included: 2.99 lb/wk on 09-22
    beside `rate_advocate`'s 4.52 for the same body on the same day."""
    out: dict[str, Any] = {
        "weight_lb": None,
        "weight_trend_lb_wk": None,
        "weighin_count": None,
        "weighin_span_days": None,
        "rate_provisional": None,
        "weekly_loss_rates_lb_wk": None,
    }
    if rows is None:
        return out
    usable = [r for r in rows if (_num(r.get("weight_lbs")) or 0) > 0]
    out["weight_lb"] = weight_trend.latest_weight(usable).get("weight_lbs")
    end = shared_quantities.completed_end(keys[-1])
    rate = shared_quantities.loss_rate_from_rows(usable, end)
    out["weighin_count"] = rate["n_weighins"]
    out["weighin_span_days"] = rate["span_days"]
    if rate["rate_lb_wk"] is not None:
        out["weight_trend_lb_wk"] = round(-rate["rate_lb_wk"], 2)  # SIGNED, negative = losing — the critic's contract
        out["rate_provisional"] = rate["provisional"]
    out["loss_rate"] = rate
    out["weekly_loss_rates_lb_wk"] = shared_quantities.weekly_loss_rates_from_rows(usable, end)
    return out


def _walking_hours(end_date: str) -> float | None:
    """THE weekly walking hours for the 7 completed days ending `end_date` (#4068)."""
    return _num(_safe(shared_quantities.weekly_walking_hours, end_date))


def _metabolic_severity(end_date: str) -> str | None:
    from mcp.tools_nutrition import _get_metabolic_adaptation

    ma = _safe(_get_metabolic_adaptation, {"end_date": end_date})
    if not isinstance(ma, dict) or ma.get("error"):
        return None
    return (ma.get("metabolic_adaptation") or {}).get("severity")


def _above_prescription_weeks(end_date: str) -> tuple[int | None, bool]:
    """(the self_added_volume run length, whether the read RAISED) — #4081.

    The SAME evaluation plan_engine's tripwire row reads (`training.self_added_volume` over the
    per-movement set counts `health.adherence_calc` stored on each Hevy row), so the critic and
    the engine cannot disagree. The run is None when the read raised or the verdict is
    `unknown` (no session, or no assessable week) — the critic names None as unknown.
    """
    from training import owner_redlines, self_added_volume

    start = self_added_volume.window_start(end_date)
    rows = _safe(query_source, "hevy", start, end_date) if start else None
    if rows is None:
        return None, bool(start)
    t = next(t for t in owner_redlines.TRIPWIRES if t["id"] == "self_added_volume")
    ev = self_added_volume.evaluate(rows, end_date, int(t["threshold_weeks"]))
    return (ev.get("run_weeks") if ev.get("state") in ("tripped", "clear") else None), False


def already_logged(days: int = DECISIONS_LOOKBACK_DAYS) -> list[dict[str, Any]] | None:
    from mcp.tools_decisions import tool_get_decisions

    res = _safe(tool_get_decisions, {"days": days})
    if not isinstance(res, dict) or "decisions" not in res:
        return None
    return [d for d in res["decisions"] if isinstance(d, dict) and d.get("source") == nutrition_critics.DECISION_SOURCE]


def resolve(
    end_date: str,
    *,
    deficit_severity: str | None = None,
    degraded_count: int | None = None,
    estimated_maintenance_kcal: float | None = None,
    include_metabolic: bool = True,
) -> dict[str, Any]:
    """The critic inputs for the 14 days ending `end_date`, plus `unresolved` — the readers
    that raised, by name."""
    keys = day_keys(end_date)
    start = keys[0]
    unresolved: dict[str, str] = {}
    mf = _safe(query_source, "macrofactor", start, end_date)
    hevy = _safe(query_source, "hevy", start, end_date)
    wt = _safe(query_source, "withings", start, end_date)
    for name, rows in (("macrofactor", mf), ("hevy", hevy), ("withings", wt)):
        if rows is None:
            unresolved[name] = "partition read raised"
    intake, protein = macrofactor_series(mf, keys)
    trend = withings_trend(wt, keys)
    dn = day_n(end_date)
    walk_end = shared_quantities.completed_end(end_date)  # the week the plan reads, never a day in progress
    this_wk = _walking_hours(walk_end)
    last_wk = _walking_hours(shift_day_key(walk_end, -7))
    if this_wk is None or last_wk is None:
        unresolved["walking_volume"] = "the walking-volume layer could not be built for one or both weeks"
    sev = _metabolic_severity(end_date) if include_metabolic else None
    if include_metabolic and sev is None:
        unresolved["metabolic_adaptation"] = "IC-29 returned an error or could not be read (thin data reads the same as an outage here)"
    above_weeks, above_raised = _above_prescription_weeks(end_date)
    if above_raised:
        unresolved["self_added_volume"] = "the Hevy prescription-window read raised"
    inputs: dict[str, Any] = {
        "window_end": end_date,
        "intake_kcal_by_day": intake,
        "protein_g_by_day": protein,
        "lifting_day_flags": lifting_day_flags(hevy, keys),
        **trend,
        "weeks_since_genesis": ((dn - 1) // 7) if dn else 0,
        "walking_hr_this_wk": this_wk,
        "walking_hr_last_wk": last_wk,
        "deficit_severity": deficit_severity,
        "degraded_count": degraded_count,
        "metabolic_adaptation_severity": sev,
        "metabolic_adaptation_flag": (sev in nutrition_critics.IC29_FLAG_SEVERITIES) if sev is not None else None,
        # #4081: the run of complete weeks above the committed routine's sets (None → the critic names it unknown)
        "training_above_prescription_weeks": above_weeks,
        "estimated_maintenance_kcal": estimated_maintenance_kcal,
    }
    return {"inputs": inputs, "unresolved": unresolved}


def block(end_date: str, **kw: Any) -> dict[str, Any]:
    """The owner-facing block both surfaces embed: verdicts + decisions_offered + what could
    not be read. Never raises — a resolver failure is reported in the block."""
    try:
        resolved = resolve(end_date, **kw)
        logged = already_logged()
        out = nutrition_critics.block(resolved["inputs"], already_logged=logged or [])
        out["window_end"] = end_date
        out["inputs_unresolved"] = resolved["unresolved"]
        if logged is None:
            out["inputs_unresolved"]["decisions"] = "get_decisions could not be read — dedup against prior decisions did not run"
        return out
    except Exception as e:  # noqa: BLE001 — the surface still ships; the block says why it is empty
        return {
            "engine": nutrition_critics.CRITICS_VERSION,
            "error": f"{type(e).__name__}: {e}"[:200],
            "verdicts": [],
            "decisions_offered": [],
        }
