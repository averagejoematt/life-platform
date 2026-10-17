"""
lambdas/web/site_api_autonomic.py — two computed-view endpoints for the data door
(RQA-06 / RQA-07, epic #348).

Both views already existed in the PRIVATE MCP tool layer (mcp.tools_health.
tool_get_autonomic_balance and mcp.tools_correlation.tool_get_zone2_breakdown) but
were never served to the public site. The MCP tier is a different runtime package
than the web tier (web/ + bundled lambdas/ modules, no mcp/ on the path), so the computation is
PORTED here — same model, same references — rather than imported. Kept as pure
functions (`_compute_*`) so the math is unit-testable without DynamoDB.

Endpoints (read-only, phase-aware via _query_source):
  /api/autonomic_balance — the 4-quadrant nervous-system model (Flow / Stress /
      Recovery / Burnout) from HRV, resting HR, respiratory rate, sleep efficiency,
      Z-scored against personal baselines. Distinct from the vitals hero (which draws
      the raw strain-vs-recovery 2×2); this is the computed autonomic view.
  /api/zone2 — weekly Zone-2 minutes against the 150-min/week reference (Attia /
      Huberman / WHO), plus the full 5-zone distribution and sport breakdown.

ADR-104 honesty: thin data reads as thin. Below the day threshold each endpoint
returns {"available": False, "reason": ...} — never a fabricated quadrant or a
zero-that-looks-like-a-real-zero. Captions frame patterns as observation, not cause.
"""

import math
from datetime import datetime, timedelta

from training import zone2_minutes as z2m  # #4627: THE Zone 2 computation

from web.site_api_common import (
    PT,
    _error,
    _ok,
    _query_source,
    logger,
)

# ── Autonomic balance (RQA-06) ────────────────────────────────────────────────

AUTONOMIC_MIN_DAYS = 7  # baseline is meaningless below a week of readings
AUTONOMIC_WINDOW_DAYS = 30

_QUADRANT_META = {
    "FLOW": {
        "label": "Flow",
        "blurb": "High vagal tone with good recovery signals — the system has energy and it's using it well.",
    },
    "STRESS": {
        "label": "Stress",
        "blurb": "Energy is available but the recovery signals are poor — sympathetic activation running ahead of repair.",
    },
    "RECOVERY": {
        "label": "Recovery",
        "blurb": "Lower energy on a positive recovery trajectory — the body rebuilding, a state that tends to precede Flow.",
    },
    "BURNOUT": {
        "label": "Burnout",
        "blurb": "Low HRV with poor recovery and elevated resting signals — the run-down corner; sustained days here erode adaptations.",
    },
}


def _sf(v):
    """Best-effort float; None when it can't be one (never fabricates a 0)."""
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _compute_autonomic_balance(whoop_items, min_days=AUTONOMIC_MIN_DAYS):
    """Pure port of tool_get_autonomic_balance, trimmed to the public payload.

    `whoop_items` is a list of normalized Whoop day records (from _query_source).
    Returns a dict; if fewer than `min_days` usable days, returns
    {"available": False, "reason": ...} so the caller can render an honest empty
    state rather than a guessed quadrant.
    """
    items = sorted(
        [i for i in (whoop_items or []) if i.get("recovery_score") is not None or i.get("hrv") is not None],
        key=lambda x: (x.get("date") or x.get("sk", "")),
    )
    if len(items) < min_days:
        return {
            "available": False,
            "reason": f"Need at least {min_days} days of recovery data to place the nervous system on the quadrant — {len(items)} so far.",
            "days_with_data": len(items),
            "min_days": min_days,
        }

    def _date_of(item):
        return (item.get("date") or item.get("sk", "").replace("DATE#", ""))[:10]

    def safe_list(field):
        out = []
        for i in items:
            v = _sf(i.get(field))
            if v is not None:
                out.append(v)
        return out

    def _eff(item):
        # Whoop stores efficiency as `sleep_efficiency_percentage`; fall back to the
        # legacy `sleep_efficiency` key. Read the real field so the valence axis is
        # honest (the private tool read a key that isn't populated).
        v = item.get("sleep_efficiency_percentage")
        if v is None:
            v = item.get("sleep_efficiency")
        return _sf(v)

    hrv_all = safe_list("hrv")
    rhr_all = safe_list("resting_heart_rate")
    rr_all = safe_list("respiratory_rate")
    eff_all = [e for e in (_eff(i) for i in items) if e is not None]

    def avg(vals):
        return round(sum(vals) / len(vals), 1) if vals else None

    def std(vals):
        if len(vals) < 2:
            return 0
        m = sum(vals) / len(vals)
        return round(math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1)), 2)

    baselines = {
        "hrv": {"mean": avg(hrv_all), "sd": std(hrv_all)},
        "rhr": {"mean": avg(rhr_all), "sd": std(rhr_all)},
        "rr": {"mean": avg(rr_all), "sd": std(rr_all)},
        "eff": {"mean": avg(eff_all), "sd": std(eff_all)},
    }

    def z_score(value, baseline):
        if value is None or baseline["mean"] is None or baseline["sd"] == 0:
            return 0
        return round((value - baseline["mean"]) / baseline["sd"], 2)

    def classify(hrv_z, rhr_z, eff_z, rr_z):
        energy = hrv_z  # positive = high vagal tone = energy available
        valence = (-rhr_z + eff_z - rr_z) / 3  # positive = good recovery signals
        if energy >= 0 and valence >= 0:
            q = "FLOW"
        elif energy >= 0 and valence < 0:
            q = "STRESS"
        elif energy < 0 and valence >= 0:
            q = "RECOVERY"
        else:
            q = "BURNOUT"
        return q, energy, valence

    daily = []
    for item in items:
        hrv_z = z_score(_sf(item.get("hrv")), baselines["hrv"])
        rhr_z = z_score(_sf(item.get("resting_heart_rate")), baselines["rhr"])
        rr_z = z_score(_sf(item.get("respiratory_rate")), baselines["rr"])
        eff_z = z_score(_eff(item), baselines["eff"])
        quadrant, energy, valence = classify(hrv_z, rhr_z, eff_z, rr_z)
        raw_score = 50 + (energy + valence) * 12.5  # centre 50; flow up, burnout down
        balance = max(0, min(100, round(raw_score)))
        daily.append(
            {
                "date": _date_of(item),
                "quadrant": quadrant,
                "balance_score": balance,
                "energy_axis": round(energy, 2),
                "valence_axis": round(valence, 2),
            }
        )

    current = daily[-1]

    # 7-day rolling distribution + dominant state
    recent_7 = daily[-7:]
    dist = {}
    for ds in recent_7:
        dist[ds["quadrant"]] = dist.get(ds["quadrant"], 0) + 1
    dominant = max(dist, key=dist.get) if dist else None
    avg_score_7d = avg([ds["balance_score"] for ds in recent_7])

    # consecutive days in the current quadrant
    streak = 1
    for i in range(len(daily) - 2, -1, -1):
        if daily[i]["quadrant"] == current["quadrant"]:
            streak += 1
        else:
            break

    transitions = []
    for i in range(1, len(daily)):
        if daily[i]["quadrant"] != daily[i - 1]["quadrant"]:
            transitions.append({"date": daily[i]["date"], "from": daily[i - 1]["quadrant"], "to": daily[i]["quadrant"]})

    return {
        "available": True,
        "period": {
            "start_date": daily[0]["date"],
            "end_date": daily[-1]["date"],
            "days_with_data": len(daily),
        },
        "current_state": {
            "date": current["date"],
            "quadrant": current["quadrant"],
            "label": _QUADRANT_META[current["quadrant"]]["label"],
            "blurb": _QUADRANT_META[current["quadrant"]]["blurb"],
            "balance_score": current["balance_score"],
            "energy_axis": current["energy_axis"],
            "valence_axis": current["valence_axis"],
            "days_in_state": streak,
        },
        "seven_day_trend": {
            "dominant_state": dominant,
            "avg_balance_score": avg_score_7d,
            "state_distribution": dist,
        },
        "daily_states": daily,
        "transitions": transitions[-8:],
        "quadrants": _QUADRANT_META,
        "methodology": (
            "4-quadrant model, Z-scored against personal baselines over the window. Energy axis = HRV Z-score (vagal tone); "
            "valence axis = mean of inverted resting-HR Z, sleep-efficiency Z, and inverted respiratory-rate Z. Balance score "
            "0–100 maps both axes. An observation of where the nervous system has sat, not a diagnosis."
        ),
    }


def handle_autonomic_balance() -> dict:
    """GET /api/autonomic_balance — the computed 4-quadrant nervous-system view.

    Read-only. Reads the trailing 30 days of Whoop, Z-scores against the window's own
    baseline, and places each day in Flow / Stress / Recovery / Burnout. Honest empty
    state below 7 days of data. Cache 900s (recovery lands ~once a day)."""
    try:
        today = datetime.now(PT).strftime("%Y-%m-%d")
        start = (datetime.now(PT) - timedelta(days=AUTONOMIC_WINDOW_DAYS - 1)).strftime("%Y-%m-%d")
        whoop = _query_source("whoop", start, today)
        return _ok(_compute_autonomic_balance(whoop), cache_seconds=900)
    except Exception as e:
        logger.error(f"[site_api] /api/autonomic_balance failed: {e}")
        return _error(500, "autonomic balance unavailable")


# ── Zone-2 breakdown (RQA-07) ─────────────────────────────────────────────────

ZONE2_WINDOW_DAYS = 90
ZONE2_WEEKLY_TARGET_MIN = z2m.WEEKLY_TARGET_MIN  # Attia / Huberman / WHO moderate-intensity reference

_ZONE_LABELS = {
    "below_zone_1": "Below Zone 1",
    "zone_1": "Zone 1 · Recovery",
    "zone_2": "Zone 2 · Aerobic",
    "zone_3": "Zone 3 · Tempo",
    "zone_4": "Zone 4 · Threshold",
    "zone_5": "Zone 5 · VO₂ Max",
}
#: #4627: the band is each recording device's own — no maximum heart rate is assumed.
ZONE2_BAND_TEXT = "each recording device's own Zone 2 band (Whoop, Strava)"


def _week_start(date_str):
    d = datetime.strptime(date_str[:10], "%Y-%m-%d")
    return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")


def _week_end(week_start):
    """The Sunday closing the Monday-anchored week — the other half of the date range
    a reader needs to know WHICH week a tally belongs to (#3286)."""
    d = datetime.strptime(week_start[:10], "%Y-%m-%d")
    return (d + timedelta(days=6)).strftime("%Y-%m-%d")


def _zero_week(week_start, weekly_target_min):
    """An explicit, dated zero for a calendar week with no session (#3286).

    NOT a fabricated value and not the ADR-104 "absent ⇒ null" case: the 90-day query covers
    this week in full and zero sessions landed in it. `activity_count: 0` +
    `no_activity_recorded` let a consumer tell "measured zero" from "we have nothing", and
    `source_last_activity` names the last day anything was recorded."""
    return {
        "week_start": week_start,
        "week_end": _week_end(week_start),
        "zone_2_minutes": 0.0,
        "target_pct": 0 if weekly_target_min > 0 else None,  # same shape as an active week
        "target_met": False,
        "total_exercise_min": 0.0,
        "activity_count": 0,
        "no_activity_recorded": True,
    }


def _public_week(w):
    return {
        "week_start": w["week_start"],
        "week_end": w["week_end"],
        "zone_2_minutes": w["zone_2_minutes"],
        "target_pct": w["target_pct"],
        "target_met": bool(w["target_met"]),
        "total_exercise_min": w["session_minutes"],
        "measured_minutes": w["measured_minutes"],
        "hevy_cardio_minutes": w["hevy_cardio_minutes"],
        "activity_count": w["activity_count"],
    }


def _compute_zone2_breakdown(
    strava_items, whoop_items=None, hevy_items=None, weekly_target_min=ZONE2_WEEKLY_TARGET_MIN, today=None, start_date=None
):
    """/api/zone2's payload from THE Zone 2 computation (`training.zone2_minutes`, #4627).

    Zone 2 minutes are minutes actually in each recording device's own Zone 2 band, from the
    stored time-in-zone rows (Whoop workout sub-rows, Strava `zone{n}_seconds`), each session
    counted once across sources; Hevy cardio blocks are `hevy_cardio_minutes`, never Zone 2.
    Before #4627 this classified a whole Strava activity by its AVERAGE heart rate against
    60–70% of the profile maximum, with a 10-minute floor — that method, the floor and the
    maximum are gone. `trailing_7d` is the 7 dates [today − 6, today] through the same
    `zone2_window` `/api/training_overview` and the MCP tool read, so the three agree.

    #3286 — `current_week` MEANS the current Pacific calendar week (an explicit dated zero
    when nothing was recorded) and `latest_active_week` is the last week that had a session.
    `today` is injectable so the calendar boundary can be pinned in tests."""
    pt_today = today or datetime.now(PT).strftime("%Y-%m-%d")
    sessions = [s for s in z2m.counted_sessions(strava_items, whoop_items) if s["date"] >= (start_date or "") and s["date"] <= pt_today]
    if not sessions:
        return {
            "available": False,
            "reason": "No recorded session in the window yet — Zone-2 time fills in as sessions with heart-rate zones land.",
            "weekly_target_min": weekly_target_min,
        }
    weeks = [_public_week(w) for w in z2m.weekly(sessions, None, weekly_target_min) if w["activity_count"]]
    hevy_by_week = {w["week_start"]: w["hevy_cardio_minutes"] for w in z2m.weekly([], hevy_items)}
    for w in weeks:
        w["hevy_cardio_minutes"] = round(hevy_by_week.get(w["week_start"], 0.0), 1)
    n_weeks = len(weeks)
    z2_vals = [w["zone_2_minutes"] for w in weeks]
    weeks_meeting = sum(1 for w in weeks if w["target_met"])

    # Direction-only trend (no coefficient claimed at this n — first vs second half)
    trend = None
    if n_weeks >= 3:
        half = n_weeks // 2
        first = sum(z2_vals[:half]) / max(half, 1)
        second = sum(z2_vals[half:]) / max(n_weeks - half, 1)
        direction = "increasing" if second > first + 5 else "decreasing" if second < first - 5 else "steady"
        trend = {"direction": direction, "first_half_avg_min": round(first, 1), "second_half_avg_min": round(second, 1)}

    current_week_start = _week_start(pt_today)
    by_week_start = {w["week_start"]: w for w in weeks}
    last_activity_date = sessions[-1]["date"]
    try:
        days_since_activity = (datetime.strptime(pt_today, "%Y-%m-%d") - datetime.strptime(last_activity_date, "%Y-%m-%d")).days
    except ValueError:
        days_since_activity = None
    current_week = {
        **(by_week_start.get(current_week_start) or _zero_week(current_week_start, weekly_target_min)),
        "is_current_calendar_week": True,
        "source_last_activity": last_activity_date,
        "days_since_activity": days_since_activity,
    }
    t_start, t_end = z2m.trailing_window(pt_today)
    t7 = z2m.zone2_window(strava_items, whoop_items, hevy_items, t_start, t_end, sessions=sessions)
    dist = z2m.zone_distribution(sessions)
    return {
        "available": True,
        "period": {"start_date": sessions[0]["date"], "end_date": last_activity_date, "weeks_analyzed": n_weeks},
        "weekly_target_min": weekly_target_min,
        "pacific_today": pt_today,  # #3286: the frame the week boundary was drawn in, stated
        "current_week": current_week,
        "latest_active_week": weeks[-1] if weeks else None,
        "weeks": weeks,
        "trailing_7d": {k: t7[k] for k in ("start_date", "end_date", "dates", "zone_2_minutes", "by_source", "hevy_cardio_minutes")},
        "zone_distribution": [{**z, "label": _ZONE_LABELS[z["zone"]], "hr_range": "device's own band"} for z in dist],
        "sport_breakdown": z2m.sport_breakdown(sessions),
        "trend": trend,
        "summary": {
            "weeks_analyzed": n_weeks,
            "total_activities": len(sessions),
            "avg_weekly_zone_2_min": round(sum(z2_vals) / n_weeks, 1) if n_weeks else 0,
            "weeks_meeting_target": weeks_meeting,
            "target_hit_rate_pct": round(100 * weeks_meeting / n_weeks) if n_weeks else 0,
            "total_zone_2_min": round(sum(s["zone_2_minutes"] or 0 for s in sessions if s["source"]), 1),
            "unmeasured_sessions": sum(1 for s in sessions if not s["source"]),
            "max_hr_used": None,  # #4627: no maximum is assumed — each device's own band
            "zone_2_hr_range": ZONE2_BAND_TEXT,
            "definition": z2m.DEFINITION,
        },
    }


def handle_zone2_breakdown() -> dict:
    """GET /api/zone2 — weekly Zone-2 minutes against the 150-min reference.

    Read-only. Reads the trailing 90 days of Strava, Whoop (workout sub-rows; one extra day at the
    end, as Whoop keys are UTC days) and Hevy, and serves THE Zone 2 computation
    (`training.zone2_minutes`, #4627). Honest empty state when no session exists. Cache 1800s.

    #3286: the envelope declares `content_as_of` — the last day anything was recorded — so a
    held read never wears a fresher date than its content; `_meta.served_at` carries the
    request time."""
    try:
        today = datetime.now(PT).strftime("%Y-%m-%d")
        start = (datetime.now(PT) - timedelta(days=ZONE2_WINDOW_DAYS - 1)).strftime("%Y-%m-%d")
        strava = _query_source("strava", start, today)
        whoop = _query_source("whoop", start, _shift(today, 1))  # a Pacific evening workout is keyed the next UTC day
        hevy = _query_source("hevy", start, today)
        payload = _compute_zone2_breakdown(strava, whoop, hevy, today=today, start_date=start)
        _last = (payload.get("current_week") or {}).get("source_last_activity")
        return _ok(payload, cache_seconds=1800, content_as_of=_last)
    except Exception as e:
        logger.error(f"[site_api] /api/zone2 failed: {e}")
        return _error(500, "zone 2 breakdown unavailable")


def _shift(d, days):
    return (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")
