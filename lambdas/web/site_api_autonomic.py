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
from datetime import datetime, timedelta, timezone

from web.site_api_common import (
    _error,
    _get_profile,
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
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start = (datetime.now(timezone.utc) - timedelta(days=AUTONOMIC_WINDOW_DAYS - 1)).strftime("%Y-%m-%d")
        whoop = _query_source("whoop", start, today)
        return _ok(_compute_autonomic_balance(whoop), cache_seconds=900)
    except Exception as e:
        logger.error(f"[site_api] /api/autonomic_balance failed: {e}")
        return _error(500, "autonomic balance unavailable")


# ── Zone-2 breakdown (RQA-07) ─────────────────────────────────────────────────

ZONE2_WINDOW_DAYS = 90
ZONE2_WEEKLY_TARGET_MIN = 150  # Attia / Huberman / WHO moderate-intensity reference
ZONE2_MIN_DURATION_MIN = 10

# 5 zones by % of max HR (standard model)
_ZONE_BOUNDS = [
    ("zone_1", "Zone 1 · Recovery", 0.50, 0.60),
    ("zone_2", "Zone 2 · Aerobic", 0.60, 0.70),
    ("zone_3", "Zone 3 · Tempo", 0.70, 0.80),
    ("zone_4", "Zone 4 · Threshold", 0.80, 0.90),
    ("zone_5", "Zone 5 · VO₂ Max", 0.90, 1.00),
]


def _week_start(date_str):
    d = datetime.strptime(date_str[:10], "%Y-%m-%d")
    return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")


def _compute_zone2_breakdown(strava_items, profile, weekly_target_min=ZONE2_WEEKLY_TARGET_MIN, min_duration_min=ZONE2_MIN_DURATION_MIN):
    """Pure port of tool_get_zone2_breakdown, trimmed to the public payload.

    Classifies each qualifying Strava activity into an HR zone by average HR as a
    percentage of max HR (from profile), aggregates weekly Zone-2 minutes against the
    150-min reference, and rolls up the full 5-zone distribution + a Zone-2 sport
    breakdown. Returns {"available": False, ...} when there is no qualifying activity
    (never a fabricated zero week)."""
    max_hr = _sf((profile or {}).get("max_heart_rate")) or 190.0

    zone_hr_ranges = {}
    for key, label, lo, hi in _ZONE_BOUNDS:
        zone_hr_ranges[key] = {"label": label, "hr_low": round(max_hr * lo), "hr_high": round(max_hr * hi)}

    def classify(avg_hr):
        if avg_hr is None:
            return "no_hr"
        pct = avg_hr / max_hr
        if pct < 0.50:
            return "below_zone_1"
        if pct < 0.60:
            return "zone_1"
        if pct < 0.70:
            return "zone_2"
        if pct < 0.80:
            return "zone_3"
        if pct < 0.90:
            return "zone_4"
        return "zone_5"

    activities = []
    for day in sorted(strava_items or [], key=lambda x: (x.get("date") or x.get("sk", ""))):
        date = (day.get("date") or day.get("sk", "").replace("DATE#", ""))[:10]
        for act in day.get("activities", []) or []:
            moving = _sf(act.get("moving_time_seconds")) or 0
            if moving < min_duration_min * 60:
                continue
            avg_hr = _sf(act.get("average_heartrate"))
            activities.append(
                {
                    "date": date,
                    "name": act.get("enriched_name") or act.get("name") or "Unnamed",
                    "sport_type": act.get("sport_type") or act.get("type") or "Unknown",
                    "moving_time_min": round(moving / 60, 1),
                    "avg_hr": avg_hr,
                    "zone": classify(avg_hr),
                }
            )

    if not activities:
        return {
            "available": False,
            "reason": "No qualifying cardio activity in the window yet — Zone-2 time fills in as sessions with heart-rate land.",
            "weekly_target_min": weekly_target_min,
        }

    # ── Weekly aggregation ──
    weekly = {}
    for act in activities:
        wk = _week_start(act["date"])
        w = weekly.setdefault(
            wk,
            {
                "zone_1": 0.0,
                "zone_2": 0.0,
                "zone_3": 0.0,
                "zone_4": 0.0,
                "zone_5": 0.0,
                "below_zone_1": 0.0,
                "no_hr": 0.0,
                "total": 0.0,
                "count": 0,
            },
        )
        w[act["zone"]] += act["moving_time_min"]
        w["total"] += act["moving_time_min"]
        w["count"] += 1

    weeks = []
    for wk in sorted(weekly.keys()):
        w = weekly[wk]
        z2 = w["zone_2"]
        weeks.append(
            {
                "week_start": wk,
                "zone_2_minutes": round(z2, 1),
                "target_pct": round(100 * z2 / weekly_target_min) if weekly_target_min > 0 else None,
                "target_met": z2 >= weekly_target_min,
                "total_exercise_min": round(w["total"], 1),
                "activity_count": w["count"],
            }
        )

    # ── Full-period zone distribution ──
    totals = {k: 0.0 for k, *_ in _ZONE_BOUNDS}
    counts = {k: 0 for k, *_ in _ZONE_BOUNDS}
    grand_total = 0.0
    for act in activities:
        z = act["zone"]
        grand_total += act["moving_time_min"]
        if z in totals:
            totals[z] += act["moving_time_min"]
            counts[z] += 1
    zone_distribution = []
    for key, label, _, _ in _ZONE_BOUNDS:
        mins = round(totals[key], 1)
        zone_distribution.append(
            {
                "zone": key,
                "label": label,
                "total_minutes": mins,
                "activity_count": counts[key],
                "pct_of_training": round(100 * mins / grand_total, 1) if grand_total > 0 else 0,
                "hr_range": f"{zone_hr_ranges[key]['hr_low']:.0f}–{zone_hr_ranges[key]['hr_high']:.0f} bpm",
            }
        )

    # ── Zone-2 sport breakdown ──
    by_sport = {}
    for act in activities:
        if act["zone"] == "zone_2":
            s = by_sport.setdefault(act["sport_type"], {"minutes": 0.0, "count": 0})
            s["minutes"] += act["moving_time_min"]
            s["count"] += 1
    sport_breakdown = [
        {"sport_type": sport, "zone_2_minutes": round(d["minutes"], 1), "activity_count": d["count"]}
        for sport, d in sorted(by_sport.items(), key=lambda x: -x[1]["minutes"])
    ]

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

    return {
        "available": True,
        "period": {"start_date": activities[0]["date"], "end_date": activities[-1]["date"], "weeks_analyzed": n_weeks},
        "weekly_target_min": weekly_target_min,
        "current_week": weeks[-1] if weeks else None,
        "weeks": weeks,
        "zone_distribution": zone_distribution,
        "sport_breakdown": sport_breakdown,
        "trend": trend,
        "summary": {
            "weeks_analyzed": n_weeks,
            "total_activities": len(activities),
            "avg_weekly_zone_2_min": round(sum(z2_vals) / n_weeks, 1) if n_weeks else 0,
            "weeks_meeting_target": weeks_meeting,
            "target_hit_rate_pct": round(100 * weeks_meeting / n_weeks) if n_weeks else 0,
            "total_zone_2_min": round(totals["zone_2"], 1),
            "max_hr_used": max_hr,
            "zone_2_hr_range": f"{zone_hr_ranges['zone_2']['hr_low']:.0f}–{zone_hr_ranges['zone_2']['hr_high']:.0f} bpm",
        },
    }


def handle_zone2_breakdown() -> dict:
    """GET /api/zone2 — weekly Zone-2 minutes against the 150-min reference.

    Read-only. Reads the trailing 90 days of Strava, classifies each session by HR
    zone, and rolls up the weekly Zone-2 tally + the 5-zone distribution. Honest empty
    state when no qualifying activity exists. Cache 1800s."""
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start = (datetime.now(timezone.utc) - timedelta(days=ZONE2_WINDOW_DAYS - 1)).strftime("%Y-%m-%d")
        strava = _query_source("strava", start, today)
        return _ok(_compute_zone2_breakdown(strava, _get_profile()), cache_seconds=1800)
    except Exception as e:
        logger.error(f"[site_api] /api/zone2 failed: {e}")
        return _error(500, "zone 2 breakdown unavailable")
