"""
digest_utils.py — Shared utilities for digest Lambdas (v1.0.0)

Extracted from weekly_digest_lambda.py and monthly_digest_lambda.py to eliminate
duplication, fix bugs, and ensure consistent behaviour across all digest cadences.

Consumers:
  - weekly_digest_lambda.py
  - monthly_digest_lambda.py

Contents:
  - Pure scalar helpers: d2f, avg, fmt, fmt_num, safe_float
  - dedup_activities
  - _normalize_whoop_sleep
  - List-based extractors: ex_whoop_from_list, ex_whoop_sleep_from_list, ex_withings_from_list
  - Banister: compute_banister_from_list, compute_banister_from_dict
"""

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal


# ══════════════════════════════════════════════════════════════════════════════
# PURE SCALAR HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def d2f(obj):
    """Recursively convert DynamoDB Decimal values to float."""
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def avg(vals):
    """Mean of a list, ignoring None values. Returns None for empty input."""
    v = [x for x in vals if x is not None]
    return round(sum(v) / len(v), 1) if v else None


def fmt(val, unit="", dec=1):
    """Format a number with optional unit; returns em-dash for None."""
    return "\u2014" if val is None else f"{round(val, dec)}{unit}"


def fmt_num(val):
    """Format a number with thousands separator; returns em-dash for None."""
    if val is None:
        return "\u2014"
    return "{:,}".format(round(val))


def safe_float(rec, field, default=None):
    """Safely extract a float from a dict record."""
    if rec and field in rec:
        try:
            return float(rec[field])
        except Exception:
            return default
    return default


# ══════════════════════════════════════════════════════════════════════════════
# ACTIVITY DEDUP  (Strava/Garmin duplicate removal)
# ══════════════════════════════════════════════════════════════════════════════

def dedup_activities(activities):
    """Remove duplicate activities within a 15-minute window.

    Keeps the richer record (higher richness score). Records without a parseable
    start_date_local are kept unconditionally. Handles Garmin->Strava auto-sync
    duplicates where the same session appears twice with different metadata.
    """
    if not activities or len(activities) <= 1:
        return activities

    def parse_start(a):
        s = a.get("start_date_local") or a.get("start_date") or ""
        try:
            return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def richness(a):
        score = 0
        if float(a.get("distance_meters") or 0) > 0:
            score += 1000
        score += float(a.get("moving_time_seconds") or 0)
        if a.get("summary_polyline"):
            score += 500
        return score

    indexed = [(i, a, parse_start(a)) for i, a in enumerate(activities)]
    indexed = [(i, a, t) for i, a, t in indexed if t is not None]
    indexed.sort(key=lambda x: x[2])

    remove = set()
    for j in range(len(indexed)):
        if j in remove:
            continue
        _, a_j, t_j = indexed[j]
        sport_j = (a_j.get("sport_type") or "").lower()
        for k in range(j + 1, len(indexed)):
            if k in remove:
                continue
            _, a_k, t_k = indexed[k]
            if (a_k.get("sport_type") or "").lower() != sport_j:
                continue
            if abs((t_k - t_j).total_seconds()) / 60 > 15:
                break
            if richness(a_j) >= richness(a_k):
                remove.add(k)
            else:
                remove.add(j)

    kept = [a for i, (_, a, _) in enumerate(indexed) if i not in remove]
    no_time = [a for a in activities if parse_start(a) is None]
    return kept + no_time


# ══════════════════════════════════════════════════════════════════════════════
# WHOOP SLEEP NORMALISATION  (SOT: v2.55.0)
# ══════════════════════════════════════════════════════════════════════════════

def _normalize_whoop_sleep(item):
    """Map Whoop DynamoDB field aliases to canonical sleep analysis fields.

    Handles legacy field renames from Sleep SOT Redesign (v2.55.0):
      sleep_quality_score         -> sleep_score
      sleep_efficiency_percentage -> sleep_efficiency_pct
      slow_wave_sleep_hours       -> deep_pct  (computed as % of duration)
      rem_sleep_hours             -> rem_pct   (computed)
      light_sleep_hours           -> light_pct (computed)
      time_awake_hours            -> waso_hours
      disturbance_count           -> toss_and_turns
    """
    out = dict(item)

    if "sleep_quality_score" in item and "sleep_score" not in item:
        out["sleep_score"] = item["sleep_quality_score"]
    if "sleep_efficiency_percentage" in item and "sleep_efficiency_pct" not in item:
        out["sleep_efficiency_pct"] = item["sleep_efficiency_percentage"]
    if "time_awake_hours" in item and "waso_hours" not in item:
        out["waso_hours"] = item["time_awake_hours"]
    if "disturbance_count" in item and "toss_and_turns" not in item:
        out["toss_and_turns"] = item["disturbance_count"]

    dur = None
    try:
        dur = float(item["sleep_duration_hours"]) if item.get("sleep_duration_hours") else None
    except (ValueError, TypeError):
        pass

    if dur and dur > 0:
        for src_field, pct_field in [
            ("slow_wave_sleep_hours", "deep_pct"),
            ("rem_sleep_hours",       "rem_pct"),
            ("light_sleep_hours",     "light_pct"),
        ]:
            val = item.get(src_field)
            if val is not None and pct_field not in item:
                try:
                    out[pct_field] = round(float(val) / dur * 100, 1)
                except (ValueError, TypeError, ZeroDivisionError):
                    pass

    return out


# ══════════════════════════════════════════════════════════════════════════════
# LIST-BASED EXTRACTORS  (accept a plain list of d2f-processed DDB records)
# ══════════════════════════════════════════════════════════════════════════════

def ex_whoop_from_list(recs):
    """Extract Whoop summary stats from a list of records."""
    if not recs:
        return None
    hrvs  = [float(r["hrv"])                for r in recs if "hrv"                in r]
    recov = [float(r["recovery_score"])     for r in recs if "recovery_score"     in r]
    rhrs  = [float(r["resting_heart_rate"]) for r in recs if "resting_heart_rate" in r]
    strs  = [float(r["strain"])             for r in recs if "strain"             in r]
    return {
        "hrv_avg":      avg(hrvs),
        "hrv_min":      min(hrvs, default=None),
        "hrv_max":      max(hrvs, default=None),
        "recovery_avg": avg(recov),
        "rhr_avg":      avg(rhrs),
        "strain_avg":   avg(strs),
        "days":         len(recs),
    }


def ex_whoop_sleep_from_list(recs):
    """Extract sleep metrics from a list of Whoop records (SOT for sleep duration/staging)."""
    if not recs:
        return None
    normed    = [_normalize_whoop_sleep(r) for r in recs]
    scores    = [float(r["sleep_score"])          for r in normed if "sleep_score"          in r]
    durs      = [float(r["sleep_duration_hours"])  for r in normed if "sleep_duration_hours"  in r]
    effs      = [float(r["sleep_efficiency_pct"])  for r in normed if "sleep_efficiency_pct"  in r]
    deep_pcts = [float(r["deep_pct"])              for r in normed if "deep_pct"              in r]
    rem_pcts  = [float(r["rem_pct"])               for r in normed if "rem_pct"               in r]
    return {
        "score_avg":        avg(scores),
        "duration_avg_hrs": avg(durs),
        "efficiency_avg":   avg(effs),
        "deep_pct":         avg(deep_pcts),
        "rem_pct":          avg(rem_pcts),
        "nights":           len(recs),
    }


def ex_withings_from_list(recs):
    """Extract Withings body composition summary from a list of records."""
    if not recs:
        return None
    weights  = [float(r["weight_lbs"])   for r in recs if "weight_lbs"   in r]
    bodyfats = [float(r["body_fat_pct"]) for r in recs if "body_fat_pct" in r]
    sr = sorted(recs, key=lambda r: r.get("sk", ""), reverse=True)
    return {
        "weight_latest": float(sr[0]["weight_lbs"]) if sr and "weight_lbs" in sr[0] else None,
        "weight_avg":    avg(weights),
        "weight_min":    min(weights, default=None),
        "weight_max":    max(weights, default=None),
        "body_fat_avg":  avg(bodyfats),
        "measurements":  len(recs),
    }


# ══════════════════════════════════════════════════════════════════════════════
# BANISTER TRAINING LOAD  (two input-format adapters, shared core)
# ══════════════════════════════════════════════════════════════════════════════

def compute_banister_from_list(strava_60d_list, today):
    """Compute Banister CTL/ATL/TSB from a list of Strava day records.

    Each record must have a 'date' key (YYYY-MM-DD) and optionally an
    'activities' list where each activity may have a 'kilojoules' field.
    Activities are deduped before summing kilojoules.
    """
    kj = {}
    for r in strava_60d_list:
        d = str(r.get("date", ""))
        if d:
            day_acts = dedup_activities(r.get("activities", []))
            kj[d] = sum(float(a.get("kilojoules") or 0) for a in day_acts)
    return _banister_core(kj, today)


def compute_banister_from_dict(strava_60d_dict):
    """Compute Banister CTL/ATL/TSB from a {date_str: record} dict of Strava records.

    Dict keys must be YYYY-MM-DD date strings. Each record may have an
    'activities' list with 'kilojoules' fields. Activities are deduped.
    """
    today = datetime.now(timezone.utc).date()
    kj = {}
    for date_str, r in strava_60d_dict.items():
        day_acts = dedup_activities(r.get("activities", []))
        kj[date_str] = sum(float(a.get("kilojoules") or 0) for a in day_acts)
    return _banister_core(kj, today)


def _banister_core(kj_by_date, today):
    """Shared Banister exponential decay loop (42-day CTL, 7-day ATL)."""
    ctl = atl = 0.0
    cd = math.exp(-1 / 42)
    ad = math.exp(-1 / 7)
    for i in range(59, -1, -1):
        day = (today - timedelta(days=i)).isoformat()
        load = kj_by_date.get(day, 0)
        ctl = ctl * cd + load * (1 - cd)
        atl = atl * ad + load * (1 - ad)
    return {"ctl": round(ctl, 1), "atl": round(atl, 1), "tsb": round(ctl - atl, 1)}
