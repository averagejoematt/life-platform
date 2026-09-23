"""One TSS-like training-load scale for every Banister consumer (#490 / C-5, C-6, M-3).

Before this module, daily loads were raw Strava kilojoules with a 25 kJ/min Hevy
duration stand-in — ~1,500 kJ/h — while every form band downstream (readiness
``60 + tsb*2``, character ``_in_range_score(-10, 25)``, MCP ``70 + tsb*2.5``) assumed
the classic TSS scale. The TSB component sat permanently saturated and eight rest
days read as maximal fatigue. Walks contributed zero load because Strava only
populates ``kilojoules`` for power-device activities (C-6).

The unit here is a **TSS-like point: 100 ≈ one hour at functional threshold.**
Everything is a proxy — there is no power meter or lab FTP — and the basis dict
says so (``unit``, ``confidence``, ``proxy_share``); surfaces that render TSB are
expected to surface that provenance (M-3).

Per-activity model, first match wins (#4075 moved HR ahead of every duration proxy):
  1. Real kilojoules present  → ``kJ / KJ_PER_TSS_POINT`` (~200 W FTP ⇒ 720 kJ/h
     at threshold ⇒ 100 TSS ⇒ 7.2 kJ per point).                 basis "kj"
  2. Average HR present       → Banister TRIMP measured ABOVE the owner's Zone-1
     ceiling, normalised so 1 h at ``THRESHOLD_HR`` = 100 (see ``hr_load``).
     Any sport — a walk with HR is scored by its HR, not by its sport. basis "hr"
  3. Walk-like sport, no HR   → ``WALK_TSS_PER_HOUR`` × moving hours.   basis "duration"
  4. Otherwise, no HR         → ``DEFAULT_CARDIO_TSS_PER_HOUR`` × moving hours. basis "duration"

**Why HR first (#4075).** Before #4075 the walk branch ran BEFORE the HR branch, so a
walk carrying a measured average HR of 113 bpm still scored the flat 25 points/h, and
the HR branch clamped intensity at IF ≥ 0.4, so no HR-bearing activity could ever
score below 16 points/h. Zone-1 walking — which the owner's programme prescribes
every day as recovery locomotion — read as training stress, and TSB sat at −75 over a
fortnight of easy walks and lifting. Recovery-intensity work now contributes ~0.

Hevy lifts use ``LIFT_TSS_PER_HOUR`` × session hours (a duration proxy — Hevy sessions
carry no HR; #4075 left this term as it was). Strava and Hevy loads are **additive**
on the same day (a walk and a lift both count), except a Strava echo of the Hevy
session is skipped whenever Hevy has records for that day so the same session is
never counted twice. An echo is a weight-training sport OR any activity whose
``device_name`` is Hevy — #4075 found Hevy's conditioning ("Engine") sessions arrive
in Strava as ``sport_type: Workout`` from device "Hevy" with no HR, and were charged
the 50 points/h default cardio rate ON TOP of the Hevy term.
"""

import math
from datetime import timedelta

# ~200 W FTP → 720 kJ/h at threshold = 100 TSS-like points.
KJ_PER_TSS_POINT = 7.2
# Low-intensity locomotion (IF ≈ 0.5 → 25 points/h). The walk fallback that fixes C-6.
WALK_TSS_PER_HOUR = 25.0
# Unknown-intensity aerobic work without HR (IF ≈ 0.7).
DEFAULT_CARDIO_TSS_PER_HOUR = 50.0
# Resistance-session proxy (replaces the saturating 25 kJ/min ≈ 1,500 kJ/h stand-in).
LIFT_TSS_PER_HOUR = 50.0
# ~0.9 × max HR. The normalisation anchor (1 h here = 100 points), not a lab LTHR.
THRESHOLD_HR = 165.0

# ── HR model (#4075) ──────────────────────────────────────────────────────────
# The owner's MEASURED max HR: `USER#matthew / PROFILE#v1 .max_heart_rate` = 183
# (read 2026-09-23). The load model is pure and has no profile access, so the value is
# carried here and cited, not invented; if the profile moves, move this with it.
MAX_HR = 183.0
# Zone 1's upper bound as a fraction of max HR — the platform's ONE zone table
# (`mcp/helpers.HR_ZONE_BOUNDS`, #2221; mirrored by `web/site_api_autonomic._ZONE_BOUNDS`).
# `tests/test_training_load.py` asserts the three agree, so this cannot drift silently.
Z1_CEILING_FRACTION_OF_MAX = 0.60
# 0.60 × 183 = 109.8 bpm. At or below this average HR an activity contributes 0.
# The programme's own walking cap (`owner_redlines.REDLINES["walking_floor_hr_wk"]
# ["hr_ceiling_bpm"]` = 105) sits under it, so a redline-compliant walk scores exactly 0.
Z1_CEILING_HR = round(MAX_HR * Z1_CEILING_FRACTION_OF_MAX, 1)
# Banister's TRIMP weighting (Banister 1991, "Modeling elite athletic performance",
# in MacDougall, Wenger & Green (eds.), Physiological Testing of the High-Performance
# Athlete, 2nd ed.; Morton, Fitz-Clarke & Banister 1990,
# J Appl Physiol 69:1171): TRIMP = minutes × HRr × 0.64·e^(1.92·HRr), male coefficients.
TRIMP_A = 0.64
TRIMP_B = 1.92
# The label every stored basis carries, so a TSB computed before #4075 is tellable
# from one computed after it.
HR_MODEL = "banister_trimp_above_z1_ceiling_v1"

# Strava sports scored at the walk rate.
_WALK_SPORTS = {"walk", "hike"}
# Strava sports that duplicate a Hevy session when one exists that day.
_LIFT_SPORTS = {"weighttraining"}
# Strava `device_name` of an activity Hevy itself pushed to Strava (#4075).
_HEVY_DEVICE = "hevy"

# Banister time constants (fitness 42 d, fatigue 7 d) over a 60-day window —
# identical to every implementation this module replaces.
CTL_DAYS = 42
ATL_DAYS = 7
WINDOW_DAYS = 60


def _sport(act):
    return str(act.get("sport_type") or act.get("type") or "").replace("_", "").lower()


def day_key(rec):
    """The YYYY-MM-DD day a Strava/Hevy record belongs to (``date``, else its ``sk``)."""
    return str(rec.get("date") or "") or str(rec.get("sk") or "").replace("DATE#", "")[:10]


_day_key = day_key  # historical private name


def _trimp_weight(hrr):
    """Banister's per-minute TRIMP weight for a fractional HR reserve."""
    return hrr * TRIMP_A * math.exp(TRIMP_B * hrr)


def _hrr_above_z1(avg_hr):
    """Fraction of the Z1-ceiling→max range an average HR sits at, in [0, 1]."""
    span = MAX_HR - Z1_CEILING_HR
    if span <= 0:
        return 0.0
    return min(max((float(avg_hr) - Z1_CEILING_HR) / span, 0.0), 1.0)


def hr_load(hours, avg_hr):
    """TSS-like points from duration and average HR (#4075).

    Banister's TRIMP (``minutes × HRr × 0.64·e^(1.92·HRr)``) with ONE stated deviation:
    the HR reserve is measured above the owner's Zone-1 ceiling (``Z1_CEILING_HR``)
    instead of above resting HR, so recovery-intensity work contributes 0 — the
    #4075 acceptance. The result is normalised the way hrTSS normalises TRIMP: one
    hour at ``THRESHOLD_HR`` = 100 points, which keeps every downstream TSB band on
    the scale it already assumes.
    """
    if hours <= 0 or not avg_hr or avg_hr <= 0:
        return 0.0
    ref = _trimp_weight(_hrr_above_z1(THRESHOLD_HR))
    if ref <= 0:
        return 0.0
    return hours * _trimp_weight(_hrr_above_z1(avg_hr)) / ref * 100.0


def activity_load(act):
    """TSS-like load for one Strava activity. Returns (points, basis) where basis
    is "kj" for power-backed load, "hr" for heart-rate load, and "duration" for a
    duration-only proxy (no power, no HR)."""
    kj = float(act.get("kilojoules") or 0)
    if kj > 0:
        return kj / KJ_PER_TSS_POINT, "kj"
    hours = float(act.get("moving_time_seconds") or act.get("elapsed_time_seconds") or 0) / 3600.0
    if hours <= 0:
        return 0.0, "duration"
    avg_hr = float(act.get("average_heartrate") or 0)
    if avg_hr > 0:
        return hr_load(hours, avg_hr), "hr"
    sport = _sport(act)
    if sport in _WALK_SPORTS:
        return hours * WALK_TSS_PER_HOUR, "duration"
    if sport in _LIFT_SPORTS:
        return hours * LIFT_TSS_PER_HOUR, "duration"
    return hours * DEFAULT_CARDIO_TSS_PER_HOUR, "duration"


def is_hevy_echo(act):
    """True when this Strava activity is Hevy's own copy of a Hevy session."""
    if _sport(act) in _LIFT_SPORTS:
        return True
    return str(act.get("device_name") or "").strip().lower() == _HEVY_DEVICE


def hevy_day_load(hevy_records):
    """TSS-like load for one day's Hevy records (duration proxy)."""
    hours = sum(float(r.get("duration_sec") or 0) for r in hevy_records) / 3600.0
    return hours * LIFT_TSS_PER_HOUR


def daily_training_load(strava_60d, hevy_60d, today=None):
    """Per-day TSS-like load for the Banister window, plus a provenance summary.

    Strava and Hevy are additive per day; a Strava weight-training activity is
    skipped when Hevy has records for that day (same session, richer record).
    Returns (load_by_day, basis).
    """
    # Multi-device duplicates were harmless on the kJ scale (walks carried 0 kJ);
    # under the duration proxy they would double-count, so dedup here for every
    # caller. Lazy import: digest_utils imports this module at top level.
    from common.digest_utils import dedup_activities

    strava_by_day = {}
    for r in strava_60d or []:
        d = _day_key(r)
        if d:
            strava_by_day.setdefault(d, []).extend(r.get("activities") or [])
    for d in strava_by_day:
        strava_by_day[d] = dedup_activities(strava_by_day[d])
    hevy_by_day = {}
    for r in hevy_60d or []:
        d = _day_key(r)
        if d:
            hevy_by_day.setdefault(d, []).append(r)

    load_by_day = {}
    kj_days = set()
    hr_days = set()
    duration_days = set()
    hevy_days = set()
    kj_load = hr_load_total = proxy_load = 0.0
    for d in set(strava_by_day) | set(hevy_by_day):
        day_load = 0.0
        for act in strava_by_day.get(d, []):
            if d in hevy_by_day and is_hevy_echo(act):
                continue  # Hevy carries this session
            pts, basis = activity_load(act)
            if basis == "hr":
                # An HR-scored activity is MEASURED even when it scores ~0 (a Zone-1
                # walk) — count the day so the basis can say so.
                hr_days.add(d)
            if pts <= 0:
                continue
            day_load += pts
            if basis == "kj":
                kj_days.add(d)
                kj_load += pts
            elif basis == "hr":
                hr_load_total += pts
            else:
                duration_days.add(d)
                proxy_load += pts
        if d in hevy_by_day:
            pts = hevy_day_load(hevy_by_day[d])
            if pts > 0:
                day_load += pts
                hevy_days.add(d)
                proxy_load += pts
        if day_load > 0:
            load_by_day[d] = round(day_load, 1)

    total = kj_load + hr_load_total + proxy_load
    present = [name for name, v in (("power", kj_load), ("hr", hr_load_total), ("duration_proxy", proxy_load)) if v > 0]
    if total <= 0:
        confidence = "none"
    elif len(present) == 1:
        confidence = present[0]
    else:
        confidence = "mixed"
    basis = {
        "unit": "tss_proxy",
        "model": HR_MODEL,
        "z1_ceiling_bpm": Z1_CEILING_HR,
        "strava_days": len(kj_days | hr_days | duration_days),
        "strava_kj_days": len(kj_days),
        "strava_hr_days": len(hr_days),
        "strava_duration_days": len(duration_days),
        "hevy_fallback_days": len(hevy_days),
        # proxy_share = the DURATION-ONLY share (no power, no HR) — HR load is measured.
        "proxy_share": round(proxy_load / total, 3) if total > 0 else None,
        "hr_share": round(hr_load_total / total, 3) if total > 0 else None,
        "confidence": confidence,
    }
    return load_by_day, basis


def banister(load_by_day, today):
    """CTL (42 d fitness), ATL (7 d fatigue), TSB = CTL − ATL over the 60-day window.

    CTL/ATL are exponentially-weighted loads and mathematically non-negative —
    clamped so a degenerate input can never surface a negative fitness/fatigue.
    """
    ctl = atl = 0.0
    cd = math.exp(-1 / CTL_DAYS)
    ad = math.exp(-1 / ATL_DAYS)
    for i in range(WINDOW_DAYS - 1, -1, -1):
        day = (today - timedelta(days=i)).isoformat()
        load = load_by_day.get(day, 0)
        ctl = ctl * cd + load * (1 - cd)
        atl = atl * ad + load * (1 - ad)
    ctl = max(0.0, round(ctl, 1))
    atl = max(0.0, round(atl, 1))
    return ctl, atl, round(ctl - atl, 1)


def compute_ctl_atl_tsb(strava_60d, today, hevy_60d=None):
    """CTL/ATL/TSB straight from day records — the one call sites should use."""
    load_by_day, _ = daily_training_load(strava_60d, hevy_60d, today)
    return banister(load_by_day, today)


def is_duration_proxy(basis):
    """True when at least half the window's load is duration-derived (no power, no HR).

    The ONE predicate every surface uses to decide whether its TSB carries a
    "duration-proxy" label (#4075: an HR-scored window is measured, not proxied, so
    ``confidence != "power"`` is no longer the right test). A pre-#490 stored basis
    without ``proxy_share`` falls back to its confidence string.
    """
    if not basis:
        return False
    share = basis.get("proxy_share")
    try:
        share = float(share) if share is not None else None
    except (TypeError, ValueError):
        share = None
    if share is not None:
        return share >= 0.5
    return basis.get("confidence") in ("duration_proxy", "hevy_fallback")


def basis_note(basis):
    """Human-readable provenance suffix for anywhere TSB renders (M-3).

    Returns " (duration-proxy basis)" when at least half the window's load is
    duration-derived, "" when power/HR-backed or when there is no basis to judge.
    """
    return " (duration-proxy basis)" if is_duration_proxy(basis) else ""
