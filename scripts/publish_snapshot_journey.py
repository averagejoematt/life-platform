#!/usr/bin/env python3
"""scripts/publish_snapshot_journey.py — the Journey's data file for the v9 build (#5579, epic #5577).

One mapper, kept beside scripts/publish_snapshot.py (which crossed the 1000-line module ceiling with it,
tests/test_module_size_guard.py): /api/journey as served — never recomputed — the weight forecasts and
their coverage from /api/forecast, the ten-pound rungs derived from the published weight series
(publish_snapshot_contract.journey_rungs, shared with the fixture), and the baseline-change marker.
Layers 2–3 (#5583) add the body beside the weight, each nullable on its own: the DEXA baseline from
/api/physical_overview (`composition`), its blood pressure and last tape session (`bp`, `tape_date`), and
PhenoAge from /api/phenoage (`phenoage` — the years, the as-of day and the nine drivers ONLY; never a
chronological age or any birth field, PhenoAge Option A). Absent (ctx.journey = None → the contract writes ABSENT_JOURNEY) when the API did not serve a complete
record; the page then says so and draws nothing in its place.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from typing import Any, Callable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from publish_snapshot_contract import ISO_DAY, journey_rungs, log  # noqa: E402

JOURNEY_METHOD_IDS = ("moving_block_bootstrap_ci", "ewma_forecast")  # the registry's names for the interval and the projection
_NUMBERS = (
    "start_weight_lbs",
    "goal_weight_lbs",
    "current_weight_lbs",
    "lost_lbs",
    "remaining_lbs",
    "progress_pct",
    "weighin_count",
    "weekly_rate_lbs",
    "weekly_rate_ci_low",
    "weekly_rate_ci_high",
    "weighin_span_days",
    "days_to_goal",
    "day_n",
    "projection_confidence",
)
_DAYS = (
    ("start_date", "started_date"),
    ("last_weighin_date", "last_weighin_date"),
    ("projected_goal_date", "projected_goal_date"),
    ("projected_goal_date_earliest", "projected_goal_date_earliest"),
    ("projected_goal_date_latest", "projected_goal_date_latest"),
)


def _num(v: Any) -> float | int | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


_COMPOSITION = (
    "total_mass_lb",
    "body_fat_pct",
    "lean_mass_lb",
    "fat_mass_lb",
    "visceral_fat_lb",
    "visceral_fat_g",
    "android_fat_pct",
    "gynoid_fat_pct",
    "ag_ratio",
)
_DRIVER_KEYS = ("name", "value", "unit", "direction", "derived")  # an allow-list: nothing else on a driver is copied


def _day(v: Any) -> str | None:
    s = str(v or "")
    return s if ISO_DAY.match(s) else None


def body_composition(po: Any, start_date: str | None) -> dict | None:
    """The last DEXA scan as served by /api/physical_overview, or None when no scan is served."""
    dexa = po.get("latest_dexa") if isinstance(po, dict) else None
    bc = dexa.get("body_composition") if isinstance(dexa, dict) else None
    scan = _day(dexa.get("scan_date")) if isinstance(dexa, dict) else None
    if not isinstance(bc, dict) or not scan or _num(bc.get("total_mass_lb")) is None:
        return None
    idx = dexa.get("indices") or {}
    targets = dexa.get("targets") or {}
    out: dict[str, Any] = {"scan_date": scan}
    out["days_before_start"] = (date.fromisoformat(start_date) - date.fromisoformat(scan)).days if start_date else None
    for k in _COMPOSITION:
        out[k] = _num(bc.get(k))
    out["almi_kg_m2"] = _num(idx.get("almi_kg_m2"))
    out["almi_percentile"] = _num(idx.get("almi_percentile"))
    out["visceral_target_lb"] = _num(targets.get("visceral_fat_lb"))
    out["next_recommended"] = _day(po.get("next_dexa_recommended"))
    out["days_since"] = _num(po.get("days_since_dexa"))
    return out


def phenoage(pa: Any) -> dict | None:
    """PhenoAge as served: the years, the as-of day and the drivers — an allow-list, so no age or birth field can ride along."""
    if not isinstance(pa, dict) or _num(pa.get("phenoage")) is None or not _day(pa.get("as_of")):
        return None
    drivers = [{k: d.get(k) for k in _DRIVER_KEYS} for d in (pa.get("drivers") or []) if isinstance(d, dict) and d.get("name")]
    return {"years": _num(pa.get("phenoage")), "as_of": _day(pa.get("as_of")), "drivers": drivers}


def blood_pressure(po: Any) -> dict | None:
    bp = po.get("blood_pressure") if isinstance(po, dict) else None
    if not isinstance(bp, dict) or _num(bp.get("systolic")) is None or _num(bp.get("diastolic")) is None or not _day(bp.get("date")):
        return None
    return {
        "systolic": _num(bp.get("systolic")),
        "diastolic": _num(bp.get("diastolic")),
        "date": _day(bp.get("date")),
        "status": bp.get("status") if isinstance(bp.get("status"), str) else None,
        "readings_count": _num(bp.get("readings_count")),
    }


def body_fields(fetched: dict, start_date: str | None) -> dict:
    """The layer-3 fields of journey.json from the fetched payloads; each is None when its endpoint did not serve it."""
    po = fetched.get("physical_overview") if isinstance(fetched.get("physical_overview"), dict) else {}
    tape = po.get("tape_measurements") if isinstance(po.get("tape_measurements"), dict) else {}
    return {
        "composition": body_composition(po, start_date),
        "phenoage": phenoage(fetched.get("phenoage")),
        "bp": blood_pressure(po),
        "tape_date": _day(tape.get("session_date")),
    }


def live_journey(ctx: Any, baseline_markers: Callable[[], list[dict]]) -> None:
    """Fill ctx.journey from the fetched payloads and ctx.series["weight_lbs"] (so it runs after the metrics)."""
    fetched_j = ctx.fetched.get("journey")
    raw = fetched_j.get("journey") if isinstance(fetched_j, dict) else None
    series = ctx.series.get("weight_lbs")
    if not isinstance(raw, dict) or not series or raw.get("pre_start"):
        ctx.journey = None
        return
    fc = ctx.fetched.get("forecast") if isinstance(ctx.fetched.get("forecast"), dict) else {}
    forecasts = [
        {k: f.get(k) for k in ("frame", "horizon_days", "point", "lo", "hi", "target_date")}
        for f in (fc.get("forecasts") or [])
        if f.get("metric") == "weight_lbs" and all(_num(f.get(k)) is not None for k in ("point", "lo", "hi"))
    ]
    cov = fc.get("coverage") or {}
    known_methods = {o["id"] for o in ctx.objs["method"]}
    last = str(raw.get("last_weighin_date") or "")
    silent = (
        (date.fromisoformat(ctx.as_of) - date.fromisoformat(last)).days if ISO_DAY.match(last) and ISO_DAY.match(str(ctx.as_of)) else None
    )
    j: dict[str, Any] = {
        "state": "ok" if silent is not None and silent <= 7 else "stale",
        "absent_text": None,
        "as_of": ctx.as_of,
        "data_through": last or None,
        "sample": False,
        "source": ["/api/journey", "/api/forecast", "/api/series"],
        "method_ids": [m for m in JOURNEY_METHOD_IDS if m in known_methods],
        "metric_id": "weight_lbs",
        "unit": "lb",
        "silent_days": silent if silent is not None else 0,
        "forecasts": forecasts,
        "forecast_model": fc.get("model"),
        "coverage": {k: cov.get(k) for k in ("coverage_pct", "n_covered", "n_resolved")} if cov else None,
        "markers": list(series.get("markers") or []) or baseline_markers(),
        "rate_provisional": bool(raw.get("rate_provisional")),
    }
    for k in _NUMBERS:
        j[k] = _num(raw.get(k))
    for k, src_key in _DAYS:
        v = str(raw.get(src_key) or "")
        j[k] = v if ISO_DAY.match(v) else None
    if any(j.get(k) is None for k in ("start_weight_lbs", "goal_weight_lbs", "current_weight_lbs", "start_date", "projected_goal_date")):
        log("  journey: the API served an incomplete record; the Journey is absent in this snapshot")
        ctx.journey = None
        return
    j["rungs"] = journey_rungs(series["days"], j["start_weight_lbs"], j["goal_weight_lbs"], j["start_date"])
    j.update(body_fields(ctx.fetched, j["start_date"]))
    j["source"] += [p for k, p in (("physical_overview", "/api/physical_overview"), ("phenoage", "/api/phenoage")) if ctx.fetched.get(k)]
    ctx.journey = j
