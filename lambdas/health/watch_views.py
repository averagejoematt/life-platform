"""health/watch_views.py — the Apple Watch views on three EXISTING MCP tools (#4979; no new tool).

  * `get_daily_metrics(view="watch")`        -> `watch_daily_view`: the watch's signals per day, both
    wrists labelled where they measure the same metric, the owner-only watch fields field-selectively.
  * `get_readiness_score` (key `watch_overnight`) -> `overnight`: the scored night's dual-wear readout.
  * `get_training(view="cardio_fitness")`    -> `cardio_fitness_view`: the VO2 max arc (each point's
    instrument), cardio recovery, exercise minutes and walking gait.

The assembly is `health.watch_signals` (the one module every consumer reads) and the blend rule is the
resolver's (`common.metric_truth.dual_wear`): both instruments kept and labelled, a blend only where the
owner has ruled one after #4974, HRV never blended. This is the OWNER's MCP surface, so the owner-only
watch fields are returned here (field-selectively, named from field_tiers) — and nowhere else.

Every function takes the caller's day-row reader `read(source, start, end)`: the MCP tools pass their own
module's `query_source`, so the seam their tests patch stays the one that runs. No I/O here; it lives
beside `watch_signals` rather than in `mcp/` so the views add no MCP module.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from common.numeric import decimals_to_float as decimal_to_float
from common.pacific_time import pacific_today

from health import watch_signals as ws

APPLE_RHR_FIELD = "resting_heart_rate_apple"  # health_auto_export_lambda tier-2 field (Apple Watch only)
DEFAULT_DAYS = 14
MAX_DAYS = 120


def _window(args: dict, default_days: int = DEFAULT_DAYS) -> tuple[str, str] | dict:
    end = args.get("end_date") or pacific_today()
    try:
        end_dt = datetime.strptime(str(end), "%Y-%m-%d")
        start = args.get("start_date") or (end_dt - timedelta(days=default_days - 1)).strftime("%Y-%m-%d")
        start_dt = datetime.strptime(str(start), "%Y-%m-%d")
    except ValueError:
        return {"error": f"Could not parse start_date/end_date ({args.get('start_date')!r}, {end!r}) — expected YYYY-MM-DD."}
    if start_dt > end_dt or (end_dt - start_dt).days >= MAX_DAYS:
        return {"error": f"start_date must be on or before end_date and the window at most {MAX_DAYS} days."}
    return str(start), str(end)


def watch_daily_view(args: dict, read) -> dict[str, Any]:
    """get_daily_metrics view="watch": the owner's labelled watch read over the window (default 14 days)."""
    win = _window(args)
    if isinstance(win, dict):
        return win
    start, end = win
    apple = read(ws.APPLE, start, end)
    whoop = read(ws.WHOOP, start, end)
    out = ws.owner_view(apple, whoop, start, end)
    if not out["days_with_watch_data"]:
        out["note"] = "No Apple Watch rows in this window — the watch's fields are absent, not zero."
    return decimal_to_float(out)


def overnight(night: str, read) -> dict[str, Any]:
    """get_readiness_score's `watch_overnight`: each dual-wear metric for the newest night on or before
    `night` (within a week), both instruments labelled, with the resolver's blend verdict. Never raises."""
    try:
        start = (datetime.strptime(night, "%Y-%m-%d") - timedelta(days=ws.WINDOW_DAYS - 1)).strftime("%Y-%m-%d")
        rows = {ws.WHOOP: read(ws.WHOOP, start, night), ws.APPLE: read(ws.APPLE, start, night)}
        nights = ws.dual_wear_nights(rows, night, audience=ws.OWNER_TOOL)
    except Exception as e:  # noqa: BLE001 — readiness never fails on its cross-device readout
        return {"status": "unavailable", "reason": f"watch readout failed: {type(e).__name__}"}
    if not nights:
        return {"status": "unavailable", "reason": f"no Whoop or Apple Watch reading for the week ending {night}"}
    return decimal_to_float(
        {
            "status": "available",
            "metrics": nights,
            "note": "Both wrists labelled. A blend appears only where the owner ruled one after #4974; HRV is never blended.",
        }
    )


def cardio_fitness_view(args: dict, read) -> dict[str, Any]:
    """get_training view="cardio_fitness": VO2 max arc + the watch's training signals (default 30 days)."""
    win = _window(args, ws.ARC_DAYS)
    if isinstance(win, dict):
        return win
    start, end = win
    days = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days + 1
    apple = read(ws.APPLE, start, end)
    arc = ws.vo2_arc({ws.APPLE: apple, "garmin": read("garmin", start, end)}, end, days=days)
    signals = [ws.summarize(s, ws.day_rows(apple), end, days=days) for s in ws.SIGNALS if "training" in s.domains]
    return decimal_to_float(
        {
            "start_date": start,
            "end_date": end,
            "vo2_max": arc,
            "signals": [s for s in signals if s],
            "note": (
                "Each value names its instrument and the date it is from. VO2 max is a device estimate; when the arc spans "
                "two devices (Apple Watch, Garmin's history) the change is not one instrument's."
            ),
        }
    )


# ── get_readiness_score's device_agreement (moved verbatim from tools_health, #4979) ──


def whoop_vs_apple_agreement(whoop_component, end_date, start_date, read):
    """#4976: Whoop vs Apple Watch resting HR on the SAME night. HRV is never compared
    (Whoop RMSSD vs Apple SDNN). Always a shaped dict with a reason (#492/M-7)."""
    hrv_note = "HRV not compared: Whoop reports RMSSD and Apple reports SDNN — two different statistics."
    if not whoop_component:
        return {"status": "unavailable", "reason": "no whoop recovery record to cross-check against", "hrv_note": hrv_note}
    whoop_raw = whoop_component["raw"]
    night = whoop_raw.get("date")
    apple_rows = read("apple_health", start_date, end_date)
    apple_night = next((a for a in apple_rows if a.get("date") == night and a.get(APPLE_RHR_FIELD) is not None), None)
    whoop_rhr = ws._num(whoop_raw.get("resting_hr"))
    if apple_night is None or whoop_rhr is None:
        return {
            "status": "unavailable",
            "reason": f"no Apple Watch resting heart rate for the Whoop night ({night}) — nothing to cross-check",
            "hrv_note": hrv_note,
        }
    apple_rhr = float(apple_night[APPLE_RHR_FIELD])
    delta = whoop_rhr - apple_rhr
    status = "agree" if abs(delta) <= 3 else ("minor_variance" if abs(delta) <= 6 else "flag")
    return {
        "status": "available",
        "devices": ["whoop", "apple_watch"],
        "confidence": {"agree": "high", "minor_variance": "moderate", "flag": "low"}[status],
        "checks": {
            "rhr": {
                "date": night,
                "whoop_bpm": round(whoop_rhr, 1),
                "apple_bpm": round(apple_rhr, 1),
                "delta_bpm": round(delta, 1),
                "status": status,
            }
        },
        "hrv_note": hrv_note,
        "note": "RHR Δ ≤ 3 bpm agree · ≤ 6 minor · else flag; a flagged night means the score may be less reliable",
    }
