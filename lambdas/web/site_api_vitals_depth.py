"""
lambdas/web/site_api_vitals_depth.py — the vitals-DEPTH endpoint (#421 / VIT-02/03/04, PHY-06).

One read-only endpoint, `/api/vitals_depth`, that deepens the daily vitals surface with the
slow-moving, long-horizon reads the daily aggregates can't show:

  • VO2max trend        — actually-recorded Garmin estimates, the multi-year aerobic arc.
  • Walking heart rate  — the average HR of real Strava `Walk` activities (a genuine
                          walking-HR capture source), a recent trend with gaps as gaps.
  • Fitness age         — a complementary age estimate MAPPED from VO2max against male
                          population reference standards. Follows the established bio-age
                          privacy pattern (Option A): chronological age is NEVER an input
                          or an output, and no age-gap is ever derivable.

The platform rule (ADR-104/105): a panel ships ONLY when its data genuinely exists; anything
without data is DEFERRED with a receipt in `deferred`, never faked. Two of the four VIT-0x
ideas are deferred here for exactly that reason (see `_DEFERRED` below):

  • Hourly habit-completion glyphs — Habitify exposes no per-completion timestamp; the stored
    `completed_at` is the hourly poller's OBSERVATION time, not a true hour-of-day, so a
    "versus your average by this hour" benchmark cannot be computed honestly.
  • Vascular age — no validated vascular-age formula exists in-repo, and the only vascular-age
    datum (Withings measurement type 155) is a provider scrape, which stays gated on explicit
    sign-off per the privacy line; BP capture coverage is also not yet confirmed.

Data provenance (verified against live DDB, 2026-07-08):
  • Garmin `vo2_max` — 287 real records, 2022-04 → 2026-05 (source USER#matthew#SOURCE#garmin).
  • Strava `Walk` activities with `average_heartrate` — 775 real activities, 2020-11 → 2026-07.
  Both partitions are RAW_TIMESERIES (cross-phase, kept across resets — lambdas/phase_taxonomy.py),
  and the records carry phase=pilot, so these arcs are read with include_pilot=True — the
  sanctioned backward-looking path (phase_filter.py) for genuine long-horizon physiology.
"""

import json
from datetime import datetime, timedelta, timezone

from web.site_api_common import (
    _error,
    _ok,
    _query_source,
    logger,
)

# ── Windows ────────────────────────────────────────────────────────────────────────────────
_ARC_EARLIEST = "2010-01-01"  # far enough back to sweep the full recorded history

# #1091 — cross-phase provenance, made data-driven. These panels are built on RAW_TIMESERIES
# partitions (ADR-077): real multi-year records deliberately KEPT across experiment resets.
# Pre-start / week-one they could read as this-cycle data that shouldn't exist yet, so every
# available panel declares scope="multi_year" and the renderer labels it ("multi-year history ·
# not reset with the experiment"). Labeling only — the history is real and nothing is blanked.
_SCOPE_MULTI_YEAR = "multi_year"
_WALK_WINDOW_DAYS = 182  # the rendered walking-HR trend is the last ~6 months (recent read)
_FITNESS_BASIS_DAYS = 180  # VO2max readings feeding the fitness-age estimate (recent aerobic state)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


# ── Fitness age (Option A privacy) ───────────────────────────────────────────────────────────
# Male population VO2max reference standards (approx. 50th-percentile, ml/kg/min), monotonic-
# decreasing with age. Source: population cardiorespiratory-fitness reference standards for men
# (Cooper Institute / ACSM percentile norms; consistent with the FRIEND registry — Kaminsky LA
# et al., Mayo Clin Proc 2015). Used ONLY to map a measured VO2max to the age at which it is the
# male-population median — the "fitness age." Chronological age is neither an input nor an output
# of this computation, so no true age is served or derivable (mirrors handle_phenoage / Option A).
_VO2MAX_MALE_MEDIAN = [
    (20, 48.0),
    (25, 46.0),
    (30, 45.0),
    (35, 43.0),
    (40, 41.0),
    (45, 39.0),
    (50, 36.0),
    (55, 34.0),
    (60, 31.0),
    (65, 29.0),
    (70, 26.0),
    (75, 24.0),
    (80, 22.0),
]
_FITNESS_AGE_METHOD = (
    "Fitness age maps your measured VO2max to the age at which it is the median for men "
    "(population reference standards; Cooper Institute / ACSM, consistent with the FRIEND "
    "registry). Your real age is never used or shown — only VO2max drives this number."
)
_FITNESS_AGE_CITATION = "Male VO2max age-percentile reference standards (Cooper Institute / ACSM; FRIEND registry, Kaminsky et al. 2015)"


def _fitness_age_for_vo2max(vo2):
    """Map a VO2max (ml/kg/min) to a male-population fitness age via linear interpolation of the
    reference table. Returns a float age, clamped to the table's [20, 80] domain. None if no VO2max."""
    if vo2 is None:
        return None
    try:
        v = float(vo2)
    except (TypeError, ValueError):
        return None
    table = _VO2MAX_MALE_MEDIAN
    if v >= table[0][1]:  # fitter than the youngest median → clamp to youngest age
        return float(table[0][0])
    if v <= table[-1][1]:  # below the oldest median → clamp to oldest age
        return float(table[-1][0])
    for (a0, v0), (a1, v1) in zip(table, table[1:]):
        # table decreases in VO2max as age rises: v0 > v1. Find the bracket containing v.
        if v1 <= v <= v0:
            frac = (v0 - v) / (v0 - v1) if v0 != v1 else 0.0
            return a0 + frac * (a1 - a0)
    return None


def _fitness_age_estimate(vo2_series):
    """Compute a fitness-age estimate + uncertainty band from recent VO2max readings.

    ADR-105: the band is anchored to Matthew's OWN VO2max variance (SD of the recent readings
    mapped through the reference table), floored at ±3 years so a single reading never claims
    false precision. Returns a dict or None. Never touches chronological age."""
    if not vo2_series:
        return None
    recent = [r for r in vo2_series if r["date"] >= _days_ago(_FITNESS_BASIS_DAYS)]
    if len(recent) < 3:
        recent = vo2_series[-5:]  # fall back to the most-recent handful when the window is thin
    vals = [r["value"] for r in recent if r.get("value") is not None]
    if not vals:
        return None
    n = len(vals)
    mean = sum(vals) / n
    if n >= 2:
        var = sum((x - mean) ** 2 for x in vals) / (n - 1)
        sd = var**0.5
    else:
        sd = 0.0
    point = _fitness_age_for_vo2max(mean)
    if point is None:
        return None
    # Higher VO2max → younger age (lower number), so mean+sd is the LOW bound of the age band.
    lo = _fitness_age_for_vo2max(mean + sd)
    hi = _fitness_age_for_vo2max(mean - sd)
    if lo is None:
        lo = point
    if hi is None:
        hi = point
    lo, hi = min(lo, hi), max(lo, hi)
    # Floor the band at ±3 years around the point (honest minimum uncertainty for a mapped age).
    lo = min(lo, point - 3.0)
    hi = max(hi, point + 3.0)
    as_of = max(r["date"] for r in recent)
    return {
        "scope": _SCOPE_MULTI_YEAR,  # #1091 — basis readings come from the cross-cycle VO2max record
        "estimate": round(point),
        "range_low": round(lo),
        "range_high": round(hi),
        "basis_vo2max": round(mean, 1),
        "n": n,
        "as_of": as_of,
        "method": _FITNESS_AGE_METHOD,
        "citation": _FITNESS_AGE_CITATION,
    }


# ── VO2max arc ───────────────────────────────────────────────────────────────────────────────
def _vo2max_arc():
    """The recorded VO2max arc from Garmin (real estimates only; gaps stay gaps)."""
    rows = _query_source("garmin", _ARC_EARLIEST, _today(), include_pilot=True)
    series = []
    for r in rows:
        v = r.get("vo2_max")
        d = r.get("date") or (r.get("sk", "").replace("DATE#", "") or None)
        if v is None or not d:
            continue
        try:
            series.append({"date": d, "value": round(float(v), 1)})
        except (TypeError, ValueError):
            continue
    series.sort(key=lambda x: x["date"])
    if not series:
        return {"available": False, "reason": "No recorded VO2max estimates yet."}
    values = [p["value"] for p in series]
    current = series[-1]
    # Direction over the recorded arc: first-vs-last, honest and coarse (an arc metric, not a daily line).
    first_v, last_v = values[0], values[-1]
    delta = round(last_v - first_v, 1)
    if abs(delta) < 0.5:
        trend = "stable"
    elif delta > 0:
        trend = "improving"
    else:
        trend = "declining"
    return {
        "available": True,
        "scope": _SCOPE_MULTI_YEAR,  # #1091 — Garmin arc spans cycles; kept across resets
        "source": "Garmin",
        "unit": "ml/kg/min",
        "series": series,
        "n": len(series),
        "current": current["value"],
        "as_of": current["date"],
        "peak": max(values),
        "low": min(values),
        "first": first_v,
        "delta": delta,
        "trend": trend,
    }


# ── Walking heart rate ───────────────────────────────────────────────────────────────────────
def _walking_hr():
    """Average HR of real Strava `Walk` activities — a genuine walking-HR capture source.

    Points are per-walk (multiple walks in a day are kept — that's real), positioned by date so a
    sparse cadence renders as real gaps. The rendered series is the recent window; n_total reports
    the full recorded depth."""
    rows = _query_source("strava", _ARC_EARLIEST, _today(), include_pilot=True)
    walks = []
    for r in rows:
        for a in r.get("activities") or []:
            atype = a.get("type") or a.get("sport_type") or ""
            if "alk" not in str(atype):  # matches "Walk"
                continue
            hr = a.get("average_heartrate")
            if hr is None:
                continue
            d = r.get("date") or (r.get("sk", "").replace("DATE#", "") or None)
            if not d:
                continue
            try:
                walks.append(
                    {
                        "date": d,
                        "value": round(float(hr), 1),
                        "max_hr": (round(float(a["max_heartrate"]), 0) if a.get("max_heartrate") is not None else None),
                        "name": a.get("enriched_name") or a.get("name") or "Walk",
                    }
                )
            except (TypeError, ValueError):
                continue
    walks.sort(key=lambda x: x["date"])
    if not walks:
        return {"available": False, "reason": "No walking-HR captures yet."}
    n_total = len(walks)
    cutoff = _days_ago(_WALK_WINDOW_DAYS)
    window = [w for w in walks if w["date"] >= cutoff]
    if len(window) < 4:  # thin recent window → show the most-recent stretch so the trend still reads
        window = walks[-30:]
    vals = [w["value"] for w in window]
    return {
        "available": True,
        "scope": _SCOPE_MULTI_YEAR,  # #1091 — Strava walk record spans cycles; kept across resets
        "source": "Strava (Walk activities)",
        "unit": "bpm",
        "series": window,
        "n": len(window),
        "n_total": n_total,
        "window_days": _WALK_WINDOW_DAYS,
        "current": window[-1]["value"],
        "as_of": window[-1]["date"],
        "avg": round(sum(vals) / len(vals), 1),
    }


# ── Deferred panels (honest receipts, never faked) ───────────────────────────────────────────
_DEFERRED = [
    {
        "panel": "hourly_habit_glyphs",
        "reason": (
            "Habitify exposes no per-completion timestamp; the stored completed_at is the hourly "
            "poller's observation time, not a true hour-of-day, so a 'versus your average by this "
            "hour' benchmark can't be computed from real logged timestamps."
        ),
        "source": "habitify",
    },
    {
        "panel": "vascular_age",
        "reason": (
            "No validated vascular-age formula exists in-repo; the only vascular-age datum "
            "(Withings measurement type 155) is a provider scrape, gated on explicit sign-off per "
            "the bio-age privacy line, and BP capture coverage is not yet confirmed."
        ),
        "source": "withings (provider-scrape, gated)",
    },
]


def handle_vitals_depth() -> dict:
    """GET /api/vitals_depth — VO2max arc + walking HR + fitness age, with deferred receipts.

    Read-only. Privacy: chronological age is never served or derivable (fitness age is a pure
    VO2max→age map; no DOB is read). Cached 1h — these are slow-moving arc metrics."""
    try:
        vo2max = _vo2max_arc()
        walking_hr = _walking_hr()
        fitness_age = None
        if vo2max.get("available"):
            fa = _fitness_age_estimate(vo2max["series"])
            if fa:
                fitness_age = {"available": True, **fa}
        if fitness_age is None:
            fitness_age = {"available": False, "reason": "No VO2max readings to map a fitness age from."}
        payload = {
            "vo2max": vo2max,
            "walking_hr": walking_hr,
            "fitness_age": fitness_age,
            "deferred": _DEFERRED,
        }
        return _ok(payload, cache_seconds=3600)
    except Exception as e:  # noqa: BLE001 — surface a clean 500, log the detail
        logger.error(f"[vitals_depth] failed: {e}")
        return _error(500, "vitals_depth failed")


# Local self-check (not run in Lambda): python3 lambdas/web/site_api_vitals_depth.py
if __name__ == "__main__":  # pragma: no cover
    for vo2 in (48, 45, 40, 33.3, 31, 25, 20):
        print(vo2, "->", _fitness_age_for_vo2max(vo2))
    print(json.dumps(_fitness_age_estimate([{"date": "2026-05-19", "value": 33.3}, {"date": "2026-04-02", "value": 30.8}]), indent=2))
