"""
digest_utils.py — Shared utilities for digest Lambdas (v1.1.0)

Extracted from weekly_digest_lambda.py and monthly_digest_lambda.py to eliminate
duplication, fix bugs, and ensure consistent behaviour across all digest cadences.

Consumers:
  - weekly_digest_lambda.py
  - monthly_digest_lambda.py
  - fleet-wide since #970: d2f / safe_float / query_range / query_range_list are
    the one sanctioned implementations (the pre-#781 copy-paste family is gone —
    every bundle ships this module, so import it instead of redefining)

Contents:
  - Pure scalar helpers: d2f, avg, fmt, fmt_num, safe_float
  - DDB range queries: query_range, query_range_list (paginated, phase-scoped — #970)
  - get_food_delivery_streak_state (#2235 — the one read path for STREAK#current)
  - dedup_activities
  - _normalize_whoop_sleep
  - List-based extractors: ex_whoop_from_list, ex_whoop_sleep_from_list, ex_withings_from_list
  - Banister: compute_banister_from_list, compute_banister_from_dict
"""

import re
from datetime import datetime, timezone
from decimal import Decimal

from experiment.phase_filter import with_phase_filter  # ADR-058: default-deny pilot data
from ingestion.source_registry import stale_hours_overrides  # #2235: one staleness threshold, not three copies
from training import training_load  # shared TSS-like load model + Banister core (layer module, #490)

from common.pacific_time import pacific_now  # #2811: the Banister decay walks PACIFIC days

# ══════════════════════════════════════════════════════════════════════════════
# PURE SCALAR HELPERS
# ══════════════════════════════════════════════════════════════════════════════


def d2f(obj):
    """Recursively convert DynamoDB Decimal values to float."""
    if isinstance(obj, list):
        return [d2f(i) for i in obj]
    if isinstance(obj, dict):
        return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
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
# DDB RANGE QUERIES  (paginated, phase-scoped — the one sanctioned implementation, #970)
# ══════════════════════════════════════════════════════════════════════════════

# #3442: the one day-row predicate. Several partitions carry sub-records under the
# same DATE# prefix (whoop stores DATE#<d>#WORKOUT#<uuid> per workout, notion stores
# DATE#<d>#journal#<template>#<uuid> per entry). A date-keyed consumer that indexes
# such a partition by `date` lets the sub-record (sorted after the day row, carrying
# per-workout strain and none of the day fields) last-write-win over the day row —
# the 2026-W26 "20 nights of sleep in one week" incident, refound at 8 sites by the
# 2026-09-02 calculation-proof pass. Day-keyed consumers filter with these; list
# consumers whose sub-records ARE the data (hevy, journal) deliberately do not.
DAY_SK_RE = re.compile(r"^DATE#\d{4}-\d{2}-\d{2}$")


def is_day_row(item) -> bool:
    """True iff the record is a plain day row (sk == DATE#YYYY-MM-DD) — #3442.

    A record with NO sk at all is treated as a day row: the wire always carries
    sk (it is the table's range key), so sk-absence means a synthetic or
    field-stripped record, which cannot be identified as a sub-record and must
    not be silently dropped."""
    sk = item.get("sk")
    if sk is None:
        return True
    return bool(DAY_SK_RE.match(str(sk)))


def filter_day_rows(records: list) -> list:
    """Day rows only — drops DATE#<d>#<sub>… sub-records from a wire list (#3442)."""
    return [r for r in records if is_day_row(r)]


def query_range(table, source, start_date, end_date, user_id="matthew", include_pilot: bool = False):
    """Query all DATE# records for a source in a date range, as a {date: record} dict.

    Paginates via LastEvaluatedKey (a single query silently truncates at DynamoDB's
    1MB page) and applies the ADR-058 phase filter. Values are d2f-converted.
    Records sharing a `date` collapse to the last one — use query_range_list for
    per-workout schemas (Hevy) where duplicates are legitimate.

    Day rows ONLY since #3442: sub-records (DATE#<d>#WORKOUT#<uuid> and kin) are
    skipped, because "one record per date" is this function's contract and letting
    a sub-record last-write-win over the day row is the 8-site clobber class. A
    consumer that wants sub-records wants query_range_list.

    `include_pilot` (#2150) is a plain pass-through, default False — the pre-#2150
    behaviour every existing caller relies on. This was the ROOT ENABLER of the
    #2150 debt: no caller could opt into a cross-phase read at all. Callers with
    cross-cycle intent (a trailing Banister load window, a multi-cycle trend) should
    pass `include_pilot=experiment.phase_filter.source_reads_cross_phase(source)`,
    the same taxonomy-derived decision #2109 established for the compute layer's
    generic `fetch_range` readers.
    """
    pk = f"USER#{user_id}#SOURCE#{source}"
    records = {}
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {
            ":pk": pk,
            ":s": f"DATE#{start_date}",
            ":e": f"DATE#{end_date}",
        },
    }
    while True:
        resp = table.query(**with_phase_filter(kwargs, include_pilot=include_pilot))
        for item in resp.get("Items", []):
            if not is_day_row(item):  # #3442: sub-records never clobber the day row
                continue
            date_str = item.get("date") or item["sk"].replace("DATE#", "")
            records[date_str] = d2f(item)
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return records


def query_range_list(table, source, start_date, end_date, user_id="matthew", include_pilot: bool = False):
    """Query all DATE# records for a source in a date range, as a flat list.

    Preserves duplicates for per-workout schemas like Hevy (#485) where (a) multiple
    records can legitimately share the same `date` (two-a-days) — query_range's
    dict-by-date would silently collapse them, and (b) the sk carries a
    #WORKOUT#<id> suffix, so a record on the exact end_date sorts AFTER the plain
    "DATE#{end_date}" upper bound; the trailing "~" (0x7E, higher than any character
    sk uses) fixes that boundary and is harmless for exact-sk sources.

    Paginates via LastEvaluatedKey and applies the ADR-058 phase filter.

    `include_pilot` (#2150): same pass-through contract as query_range above,
    default False.
    """
    pk = f"USER#{user_id}#SOURCE#{source}"
    records: list[dict] = []
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {
            ":pk": pk,
            ":s": f"DATE#{start_date}",
            ":e": f"DATE#{end_date}~",
        },
    }
    while True:
        resp = table.query(**with_phase_filter(kwargs, include_pilot=include_pilot))
        records.extend(d2f(item) for item in resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return records


# ══════════════════════════════════════════════════════════════════════════════
# FOOD DELIVERY STREAK  (#2235 — ONE read path for STREAK#current)
# ══════════════════════════════════════════════════════════════════════════════


def get_food_delivery_streak_state(table, user_id="matthew", now=None):
    """The single sanctioned read of `USER#{user}#SOURCE#food_delivery` / `STREAK#current`.

    #2235 (ADR-104 honest numbers): `streak_days` / `last_order_date` are written ONCE,
    at ingestion time, by `ingestion.food_delivery_lambda.ingest_food_delivery_rows` —
    they are never recomputed relative to "today". Once the food_delivery source itself
    goes stale (no import for longer than its `stale_hours` threshold in
    `ingestion.source_registry`), the stored streak is a frozen snapshot from the last
    import, not a live counter — presenting it as today's number is a live-sounding
    claim about a source that is not live.

    Why WITHHOLD rather than recompute `streak_days = today - last_order_date` (option
    (a) in the issue): food_delivery is a MANUAL log — a hand-run CSV/statement import
    (`capture_channel: "mcp"` in source_registry), not a continuously polled API. A gap
    in imports does not mean "no orders happened"; it means "no import has run to tell
    us either way" — exactly the behavioural-absence semantics ADR-104 already applies
    to the character engine (absence of data is not evidence of absence of behavior).
    Recomputing the elapsed-days figure would assert a specific, growing abstinence
    streak this source has no way to back — the last import could be silent because
    nothing happened, or because the statement just hasn't been dropped in yet. So once
    the source is stale, every consumer gets None (no live-sounding number at all)
    rather than either a frozen count or a fabricated live one.

    ALL consumers — daily_brief, weekly_digest, character_sheet, and any future one —
    must call this function rather than reading STREAK#current directly, so the
    freshness check lives in exactly one place (tests/test_food_delivery_streak_freshness_2235.py
    derives and enforces that set; it does not hand-enumerate the three known today).

    Returns the raw DDB item (streak_days, last_order_date, last_order_merchant, ...)
    when the record exists AND its `updated_at` is within the food_delivery
    `stale_hours` threshold, else None. Non-fatal: returns None on any error (missing
    item, bad/missing `updated_at`, table failure), matching the historical fail-open
    behavior of the three read sites this replaces.
    """
    try:
        resp = table.get_item(Key={"pk": f"USER#{user_id}#SOURCE#food_delivery", "sk": "STREAK#current"})
        item = resp.get("Item")
        if not item:
            return None
        updated_at = item.get("updated_at")
        if not updated_at:
            return None
        updated_dt = datetime.fromisoformat(str(updated_at))
        if updated_dt.tzinfo is None:
            updated_dt = updated_dt.replace(tzinfo=timezone.utc)
        now = now or datetime.now(timezone.utc)
        stale_hours = stale_hours_overrides(["food_delivery"]).get("food_delivery")
        if stale_hours is not None:
            age_hours = (now - updated_dt).total_seconds() / 3600.0
            if age_hours > stale_hours:
                return None
        return item
    except Exception:
        return None


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
        # #1964: the canonical parser. Same None-on-failure contract as the inline
        # fork it replaces, plus the UTC backfill — which matters here because the
        # results are COMPARED below, and a naive/aware mix raises TypeError.
        from common.pacific_time import parse_iso_utc

        return parse_iso_utc(a.get("start_date_local") or a.get("start_date") or "")

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


def dedup_activities_multidevice(activities):
    """Remove duplicate activities from multi-device recording (WHOOP + Garmin).

    #2816 relocation (module-size ratchet, #1665): moved verbatim out of
    `content/output_writers.py` (a full baselined file, zero headroom) to make
    room for the Pacific-timezone import that PR needed. Distinct from
    `dedup_activities` above — same JOB, a DIFFERENT algorithm (device-priority
    + strava_id grouping vs. richness-score + sport-type grouping) — kept as a
    separate function rather than unified, since reconciling the two dedup
    strategies is an unrelated, unverified behavior change this move must not make.
    """
    if len(activities) <= 1:
        return activities

    def parse_start(a):
        try:
            return datetime.strptime(a.get("start_date", "")[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            return None

    def device_priority(a):
        dev = (a.get("device_name") or "").lower()
        if "garmin" in dev:
            return 3
        if "apple" in dev:
            return 2
        if "whoop" in dev:
            return 1
        return 0

    sorted_acts = sorted(activities, key=lambda a: a.get("start_date", ""))
    keep = []
    skip_ids = set()

    for i, a in enumerate(sorted_acts):
        aid = a.get("strava_id", str(i))
        if aid in skip_ids:
            continue
        start_a = parse_start(a)
        dur_a = float(a.get("moving_time_seconds") or 0)
        for j in range(i + 1, len(sorted_acts)):
            b = sorted_acts[j]
            bid = b.get("strava_id", str(j))
            if bid in skip_ids:
                continue
            start_b = parse_start(b)
            dur_b = float(b.get("moving_time_seconds") or 0)
            if not start_a or not start_b:
                continue
            gap = abs((start_b - start_a).total_seconds())
            if gap > 900:
                break
            if dur_a > 0 and dur_b > 0:
                ratio = min(dur_a, dur_b) / max(dur_a, dur_b)
                if ratio < 0.6:
                    continue
            if device_priority(a) >= device_priority(b):
                skip_ids.add(bid)
            else:
                skip_ids.add(aid)
                break
        if aid not in skip_ids:
            keep.append(a)

    return keep


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
            ("rem_sleep_hours", "rem_pct"),
            ("light_sleep_hours", "light_pct"),
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
    hrvs = [float(r["hrv"]) for r in recs if "hrv" in r]
    recov = [float(r["recovery_score"]) for r in recs if "recovery_score" in r]
    rhrs = [float(r["resting_heart_rate"]) for r in recs if "resting_heart_rate" in r]
    strs = [float(r["strain"]) for r in recs if "strain" in r]
    return {
        "hrv_avg": avg(hrvs),
        "hrv_min": min(hrvs, default=None),
        "hrv_max": max(hrvs, default=None),
        "recovery_avg": avg(recov),
        "rhr_avg": avg(rhrs),
        "strain_avg": avg(strs),
        "days": len(recs),
    }


def ex_whoop_sleep_from_list(recs):
    """Extract sleep metrics from a list of Whoop records (SOT for sleep duration/staging)."""
    if not recs:
        return None
    normed = [_normalize_whoop_sleep(r) for r in recs]
    scores = [float(r["sleep_score"]) for r in normed if "sleep_score" in r]
    durs = [float(r["sleep_duration_hours"]) for r in normed if "sleep_duration_hours" in r]
    effs = [float(r["sleep_efficiency_pct"]) for r in normed if "sleep_efficiency_pct" in r]
    deep_pcts = [float(r["deep_pct"]) for r in normed if "deep_pct" in r]
    rem_pcts = [float(r["rem_pct"]) for r in normed if "rem_pct" in r]
    return {
        "score_avg": avg(scores),
        "duration_avg_hrs": avg(durs),
        "efficiency_avg": avg(effs),
        "deep_pct": avg(deep_pcts),
        "rem_pct": avg(rem_pcts),
        "nights": len(recs),
    }


def ex_withings_from_list(recs):
    """Extract Withings body composition summary from a list of records."""
    if not recs:
        return None
    weights = [float(r["weight_lbs"]) for r in recs if "weight_lbs" in r]
    bodyfats = [float(r["body_fat_pct"]) for r in recs if "body_fat_pct" in r]
    sr = sorted(recs, key=lambda r: r.get("sk", ""), reverse=True)
    return {
        "weight_latest": float(sr[0]["weight_lbs"]) if sr and "weight_lbs" in sr[0] else None,
        "weight_avg": avg(weights),
        "weight_min": min(weights, default=None),
        "weight_max": max(weights, default=None),
        "body_fat_avg": avg(bodyfats),
        "measurements": len(recs),
    }


# ══════════════════════════════════════════════════════════════════════════════
# BANISTER TRAINING LOAD  (two input-format adapters, shared core)
# ══════════════════════════════════════════════════════════════════════════════


def compute_banister_from_list(strava_60d_list, today):
    """Compute Banister CTL/ATL/TSB from a list of Strava day records.

    Each record must have a 'date' key (YYYY-MM-DD) and optionally an
    'activities' list. Activities are deduped, then scored on the shared
    TSS-like scale (training_load, #490) so walks carry load and the digest
    numbers band the same way as computed_metrics.
    """
    load = {}
    for r in strava_60d_list:
        d = str(r.get("date", ""))
        if d:
            day_acts = dedup_activities(r.get("activities", []))
            load[d] = sum(training_load.activity_load(a)[0] for a in day_acts)
    return _banister_core(load, today)


def compute_banister_from_dict(strava_60d_dict):
    """Compute Banister CTL/ATL/TSB from a {date_str: record} dict of Strava records.

    Dict keys must be YYYY-MM-DD date strings. Activities are deduped, then
    scored on the shared TSS-like scale (training_load, #490).
    """
    # #2811 — the dict's keys ARE `DATE#` days (Pacific), and `_banister_core` walks
    # backwards from `today` over them. A UTC "today" after 17:00 PT started the decay
    # loop on a day with no row, silently reporting a zero-load day into CTL/ATL/TSB.
    today = pacific_now().date()
    load = {}
    for date_str, r in strava_60d_dict.items():
        day_acts = dedup_activities(r.get("activities", []))
        load[date_str] = sum(training_load.activity_load(a)[0] for a in day_acts)
    return _banister_core(load, today)


def _banister_core(load_by_date, today):
    """Shared Banister exponential decay loop (42-day CTL, 7-day ATL)."""
    ctl, atl, tsb = training_load.banister(load_by_date, today)
    return {"ctl": ctl, "atl": atl, "tsb": tsb}


# ═════════════════════════════════════════════════════════════════════════════
# BS-05: AI CONFIDENCE SCORING (IC-27)
# Henning Brandt directive: n<30 = LOW, no sig p-value = MEDIUM, n≥50+sig+effect = HIGH
# Raj: 3 rules cover 90% of cases. Ship that. Refine later.
# ═════════════════════════════════════════════════════════════════════════════


def compute_confidence(n=None, p_value=None, effect_size=None, sources=None, days_of_data=None, n_eff=None):
    """
    BS-05 / IC-27: Compute AI insight confidence level.
    Returns a dict with level (HIGH / MEDIUM / LOW) and a short reason string.

    Rules (Henning Brandt, Raj Srinivasan):
      LOW:    n < 30  OR  days_of_data < 14  OR  no data at all
      HIGH:   n >= 50  AND  (p_value is None OR p_value < 0.05)  AND  effect_size meets threshold
      MEDIUM: everything else

    Convenience helpers:
      sources  = list of source names that contributed data (to check source completeness)
      days_of_data = days of actual observations (for non-paired analyses)
      n_eff    = autocorrelation-corrected effective n (stats_core, #529/ADR-105);
                 when provided it is the gating sample size, not raw n — daily
                 series are not i.i.d., so raw n overstates the evidence.

    Returns:
      {"level": "HIGH" | "MEDIUM" | "LOW",
       "reason": str,
       "badge_html": str (inline HTML pill for email)}
    """
    # Determine effective n — a corrected n_eff takes precedence over raw n
    n_label = "n"
    effective_n = n
    if n_eff is not None:
        effective_n = n_eff
        n_label = "n_eff"
    if effective_n is None and days_of_data is not None:
        effective_n = days_of_data

    # LOW gates (Henning: n<30 = low confidence regardless of p-value)
    if effective_n is not None and effective_n < 14:
        reason = f"{n_label}={effective_n} (need ≥14 for any signal)"
        return {"level": "LOW", "reason": reason, "badge_html": _confidence_badge("LOW")}

    if effective_n is not None and effective_n < 30:
        reason = f"{n_label}={effective_n} (preliminary — need ≥30 for moderate confidence)"
        return {"level": "LOW", "reason": reason, "badge_html": _confidence_badge("LOW")}

    if days_of_data is not None and days_of_data < 14:
        reason = f"{days_of_data} days of data (need ≥14)"
        return {"level": "LOW", "reason": reason, "badge_html": _confidence_badge("LOW")}

    # Source completeness check
    if sources is not None and len(sources) == 0:
        return {"level": "LOW", "reason": "no data sources", "badge_html": _confidence_badge("LOW")}

    # HIGH gates (Raj: n≥50 + sig + meaningful effect)
    n_ok = effective_n is not None and effective_n >= 50
    p_ok = p_value is None or p_value < 0.05  # if no p_value given, assume it's not a correlation
    eff_ok = effect_size is None or abs(effect_size) >= 0.2  # Cohen's d ≥0.2 or r ≥0.2

    if n_ok and p_ok and eff_ok:
        parts = [f"{n_label}={effective_n}"]
        if p_value is not None:
            parts.append(f"p={p_value:.3f}")
        if effect_size is not None:
            parts.append(f"effect={abs(effect_size):.2f}")
        reason = ", ".join(parts)
        return {"level": "HIGH", "reason": reason, "badge_html": _confidence_badge("HIGH")}

    # MEDIUM: 30 ≤ n < 50, or p not significant, or effect too small
    parts = []
    if effective_n is not None:
        parts.append(f"{n_label}={effective_n}")
    if p_value is not None and p_value >= 0.05:
        parts.append(f"p={p_value:.3f} (not significant)")
    if not n_ok and effective_n is not None and effective_n >= 30:
        parts.append("need ≥50 for high confidence")
    reason = "; ".join(parts) if parts else "moderate data"
    return {"level": "MEDIUM", "reason": reason, "badge_html": _confidence_badge("MEDIUM")}


def _confidence_badge(level):
    """
    Ava Moreau: teal=HIGH, amber=MEDIUM, gray=LOW.
    Inline, small caps, fits in prose.
    """
    styles = {
        "HIGH": ("background:#0f3d30;color:#34d399;border:1px solid #065f46;", "HIGH CONFIDENCE"),
        "MEDIUM": ("background:#3d2a00;color:#f59e0b;border:1px solid #854d0e;", "MEDIUM CONFIDENCE"),
        "LOW": ("background:#1e2530;color:#64748b;border:1px solid #334155;", "LOW CONFIDENCE"),
    }
    style, label = styles.get(level, styles["LOW"])
    return (
        '<span style="' + style + "border-radius:4px;padding:1px 6px;"
        "font-size:9px;font-weight:700;letter-spacing:0.08em;"
        'font-family:-apple-system,sans-serif;white-space:nowrap;">' + label + "</span>"
    )


def coerce_int(value):
    """int(float(value)) or None — absence and garbage both read as absence.

    #2221: the daily brief's pre-computed read path used a bare `int(float(...))`
    on cells written by another Lambda, so one "—" placeholder raised ValueError
    out of lambda_handler and lost the whole morning email.
    """
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def rhr_trend_str(rhr_7d, rhr_30d):
    """Resting-heart-rate trend phrase, 7-day average against 30-day (#2221).

    RHR's polarity is the inverse of HRV's — a FALLING resting heart rate is the
    improvement — so this cannot reuse `hrv_trend_str`. Bands at +/-2%, matching it.
    Returns None (not a phrase) when either window is empty: `public_stats.json`
    publishes this field, and ADR-104 wants absence to read as absence rather than
    as the hard-coded "improving" that shipped here for the field's whole life.
    """
    if not rhr_7d or not rhr_30d or rhr_30d == 0:
        return None
    pct = round((rhr_7d / rhr_30d - 1) * 100)
    return "improving" if pct <= -2 else "stable" if pct < 2 else "worsening"
