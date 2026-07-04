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

Per-activity model, first match wins:
  1. Real kilojoules present  → ``kJ / KJ_PER_TSS_POINT`` (~200 W FTP ⇒ 720 kJ/h
     at threshold ⇒ 100 TSS ⇒ 7.2 kJ per point).
  2. Walk-like sport          → ``WALK_TSS_PER_HOUR`` × moving hours (IF ≈ 0.5).
  3. Average HR present       → hrTSS-lite: ``hours × IF² × 100`` with
     ``IF = avg_hr / THRESHOLD_HR`` clamped to [0.4, 1.1].
  4. Otherwise                → ``DEFAULT_CARDIO_TSS_PER_HOUR`` × moving hours.

Hevy lifts use ``LIFT_TSS_PER_HOUR`` × session hours. Strava and Hevy loads are
**additive** on the same day (a walk and a lift both count), except a Strava
weight-training echo is skipped whenever Hevy has records for that day so the
same session is never counted twice.
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
# ~0.9 × max HR 184. hrTSS-lite anchor, not a lab LTHR.
THRESHOLD_HR = 165.0

# Strava sports scored at the walk rate.
_WALK_SPORTS = {"walk", "hike"}
# Strava sports that duplicate a Hevy session when one exists that day.
_LIFT_SPORTS = {"weighttraining"}

# Banister time constants (fitness 42 d, fatigue 7 d) over a 60-day window —
# identical to every implementation this module replaces.
CTL_DAYS = 42
ATL_DAYS = 7
WINDOW_DAYS = 60


def _sport(act):
    return str(act.get("sport_type") or act.get("type") or "").replace("_", "").lower()


def _day_key(rec):
    return str(rec.get("date") or "") or str(rec.get("sk") or "").replace("DATE#", "")


def activity_load(act):
    """TSS-like load for one Strava activity. Returns (points, basis) where basis
    is "kj" for power-backed load and "duration" for any proxy."""
    kj = float(act.get("kilojoules") or 0)
    if kj > 0:
        return kj / KJ_PER_TSS_POINT, "kj"
    hours = float(act.get("moving_time_seconds") or act.get("elapsed_time_seconds") or 0) / 3600.0
    if hours <= 0:
        return 0.0, "duration"
    sport = _sport(act)
    if sport in _WALK_SPORTS:
        return hours * WALK_TSS_PER_HOUR, "duration"
    if sport in _LIFT_SPORTS:
        return hours * LIFT_TSS_PER_HOUR, "duration"
    avg_hr = float(act.get("average_heartrate") or 0)
    if avg_hr > 0:
        intensity = min(max(avg_hr / THRESHOLD_HR, 0.4), 1.1)
        return hours * intensity * intensity * 100.0, "duration"
    return hours * DEFAULT_CARDIO_TSS_PER_HOUR, "duration"


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
    try:
        from digest_utils import dedup_activities
    except ImportError:  # pragma: no cover — digest_utils ships in the same layer

        def dedup_activities(acts):
            return acts

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
    duration_days = set()
    hevy_days = set()
    kj_load = proxy_load = 0.0
    for d in set(strava_by_day) | set(hevy_by_day):
        day_load = 0.0
        for act in strava_by_day.get(d, []):
            if _sport(act) in _LIFT_SPORTS and d in hevy_by_day:
                continue  # Hevy carries this session
            pts, basis = activity_load(act)
            if pts <= 0:
                continue
            day_load += pts
            if basis == "kj":
                kj_days.add(d)
                kj_load += pts
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

    total = kj_load + proxy_load
    if total <= 0:
        confidence = "none"
    elif proxy_load == 0:
        confidence = "power"
    elif kj_load == 0:
        confidence = "duration_proxy"
    else:
        confidence = "mixed"
    basis = {
        "unit": "tss_proxy",
        "strava_days": len(kj_days | duration_days),
        "strava_kj_days": len(kj_days),
        "strava_duration_days": len(duration_days),
        "hevy_fallback_days": len(hevy_days),
        "proxy_share": round(proxy_load / total, 3) if total > 0 else None,
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


def basis_note(basis):
    """Human-readable provenance suffix for anywhere TSB renders (M-3).

    Returns " (duration-proxy basis)" when at least half the window's load is
    duration-derived, "" when power-backed or when there is no basis to judge.
    """
    if not basis:
        return ""
    share = basis.get("proxy_share")
    try:
        share = float(share) if share is not None else None
    except (TypeError, ValueError):
        share = None
    if share is not None and share >= 0.5:
        return " (duration-proxy basis)"
    if share is None and basis.get("confidence") in ("duration_proxy", "hevy_fallback"):
        return " (duration-proxy basis)"
    return ""
