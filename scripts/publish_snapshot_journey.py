#!/usr/bin/env python3
"""scripts/publish_snapshot_journey.py — the Journey's data file for the v9 build (#5579, epic #5577).

One mapper, kept beside scripts/publish_snapshot.py (which crossed the 1000-line module ceiling with it,
tests/test_module_size_guard.py): /api/journey as served — never recomputed — the weight forecasts and
their coverage from /api/forecast, the ten-pound rungs derived from the published weight series
(publish_snapshot_contract.journey_rungs, shared with the fixture), and the baseline-change marker.
Absent (ctx.journey = None → the contract writes ABSENT_JOURNEY) when the API did not serve a complete
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
    ctx.journey = j
