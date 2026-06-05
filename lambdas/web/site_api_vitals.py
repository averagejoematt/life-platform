"""
lambdas/web/site_api_vitals.py — vitals, journey, character, achievements.

Extracted from lambdas/web/site_api_lambda.py (P1.1 Phase B step 5, 2026-05-26).

These are the highest-traffic public-facing endpoints — what averagejoematt.com
homepage and /live page render. Grouped together because they share a similar
shape (read from N data sources, aggregate, emit single dashboard payload).

Endpoints:
  /api/vitals           — weight, HRV, recovery, RHR, sleep (5-min cache)
  /api/journey          — weight trajectory + goal date
  /api/character        — pillar scores + level + recent events
  /api/weight_progress  — weight delta vs baseline
  /api/character_stats  — character_stats.json passthrough
  /api/journey_timeline — major life-event milestones
  /api/journey_waveform — daily weight waveform
  /api/achievements     — challenge completion + level-up history
  /api/snapshot         — single-call vitals+journey+character combo
  /api/timeline         — life events timeline
"""
import hashlib  # used by handle_achievements stable-event-key hash
import json
import re
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal  # noqa: F401

import boto3
from boto3.dynamodb.conditions import Key

from phase_filter import with_phase_filter  # ADR-058 — used by handle_timeline

from web.site_api_common import (
    logger,
    table,
    USER_ID, USER_PREFIX,
    EXPERIMENT_START, EXPERIMENT_BASELINE_WEIGHT_LBS,
    S3_REGION,
    CORS_HEADERS,
    _ok, _error,
    _query_source, _latest_item, _decimal_to_float,
    _experiment_date,
    _get_profile,
    _load_s3_json,
)


def handle_vitals() -> dict:
    """
    GET /api/vitals
    Returns: current weight, HRV, recovery, RHR, sleep hours, 30d trends.
    Cache: 300s (5 min) — feels real-time, Lambda fires ~12x/hour at 50k traffic.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    d7 = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

    # Whoop (recovery, HRV, RHR, sleep)
    whoop_7d = _query_source("whoop", d7, today)
    whoop_30d = _query_source("whoop", d30, today)

    # Latest reading
    latest = sorted(
        [w for w in whoop_7d if w.get("recovery_score") is not None],
        key=lambda x: x.get("sk", ""), reverse=True
    )
    latest = latest[0] if latest else {}

    # 30d averages + trends
    hrv_vals = sorted([float(w["hrv"]) for w in whoop_30d if w.get("hrv")], key=lambda _: 0)
    rhr_vals = sorted([float(w["resting_heart_rate"]) for w in whoop_30d if w.get("resting_heart_rate")], key=lambda _: 0)
    rec_vals = [float(w["recovery_score"]) for w in whoop_30d if w.get("recovery_score")]

    def trend(vals):
        if len(vals) < 6: return "insufficient_data"
        mid = len(vals) // 2
        first_avg = sum(vals[:mid]) / len(vals[:mid])
        second_avg = sum(vals[mid:]) / len(vals[mid:])
        if second_avg > first_avg * 1.03: return "improving"
        if second_avg < first_avg * 0.97: return "declining"
        return "stable"

    # G-3: Latest weight — check Withings first, fall back to Apple Health (HAE)
    withings_latest = _latest_item("withings")
    current_weight = None
    weight_as_of = None
    if withings_latest:
        wv = withings_latest.get("weight_lbs")
        if wv is not None:
            current_weight = float(wv)
            weight_as_of = (withings_latest.get("sk", "").replace("DATE#", "")
                            or withings_latest.get("date"))
    # v1.4.2: Check apple_health for more recent weight (HAE fallback)
    try:
        ah_latest = _latest_item("apple_health")
        if ah_latest and ah_latest.get("weight_lbs"):
            ah_date = ah_latest.get("sk", "").replace("DATE#", "")[:10]
            if not weight_as_of or ah_date > weight_as_of:
                current_weight = float(ah_latest["weight_lbs"])
                weight_as_of = ah_date
    except Exception:
        pass

    withings_30d = _query_source("withings", d30, today)
    weight_vals = [float(w["weight_lbs"]) for w in withings_30d if w.get("weight_lbs")]
    weight_delta_30d = round(weight_vals[-1] - weight_vals[0], 1) if len(weight_vals) >= 2 else None

    recovery_pct = float(latest.get("recovery_score", 0))
    recovery_status = "green" if recovery_pct >= 67 else ("yellow" if recovery_pct >= 34 else "red")

    # DPR-1.20: Page freshness for nav badges
    _today_iso = datetime.now(timezone.utc).isoformat()
    _as_of = latest.get("sk", "").replace("DATE#", "") if latest else today
    page_freshness = {
        "/live": _today_iso,
        "/character": _today_iso,
        "/sleep": _as_of + "T12:00:00Z" if _as_of else _today_iso,
        "/glucose": _today_iso,
        "/nutrition": _today_iso,
        "/training": _today_iso,
        "/physical": weight_as_of + "T12:00:00Z" if weight_as_of else _today_iso,
        "/habits": _today_iso,
        "/explorer": _today_iso,
    }

    return _ok({
        "vitals": {
            "weight_lbs":       round(current_weight) if current_weight is not None else None,
            "weight_as_of":     weight_as_of,
            "weight_delta_30d": weight_delta_30d,
            "hrv_ms":           round(float(latest.get("hrv", 0)), 1) if latest.get("hrv") else None,
            "hrv_30d_avg":      round(sum(hrv_vals) / len(hrv_vals), 1) if hrv_vals else None,
            "hrv_trend":        trend(hrv_vals),
            "rhr_bpm":          round(float(latest.get("resting_heart_rate", 0)), 0) if latest.get("resting_heart_rate") else None,
            "rhr_trend":        trend(list(reversed(rhr_vals))),  # lower is better
            "recovery_pct":     round(recovery_pct, 0),
            "recovery_status":  recovery_status,
            "sleep_hours":      round(float(latest.get("sleep_duration_hours", 0)), 1) if latest.get("sleep_duration_hours") else None,
            "as_of_date":       _as_of,
        },
        "page_freshness": page_freshness,
    }, cache_seconds=300)



def handle_journey() -> dict:
    """
    GET /api/journey
    Returns: weight trajectory, progress, milestones, projected goal date.
    Cache: 3600s (1 hr) — weight changes slowly.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d120 = max((datetime.now(timezone.utc) - timedelta(days=120)).strftime("%Y-%m-%d"), EXPERIMENT_START)

    withings_all = _query_source("withings", d120, today)
    weight_series = sorted(
        [(w["sk"].replace("DATE#", ""), float(w["weight_lbs"]))
         for w in withings_all if w.get("weight_lbs")],
        key=lambda x: x[0]
    )

    if not weight_series:
        # G-4: Fall back to last known weight — never return 503 for missing recent data.
        withings_latest = _latest_item("withings")
        if withings_latest and withings_latest.get("weight_lbs") is not None:
            last_date = (withings_latest.get("sk", "").replace("DATE#", "")
                         or withings_latest.get("date", today))
            weight_series = [(last_date, float(withings_latest["weight_lbs"]))]
        else:
            weight_series = [(EXPERIMENT_START, EXPERIMENT_BASELINE_WEIGHT_LBS)]  # ADR-058: genesis baseline; only used when no Withings data exists

    _p = _get_profile()
    start_weight = float(_p.get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS))
    goal_weight = float(_p.get("goal_weight_lbs", 185.0))
    current_weight = weight_series[-1][1]
    lost_lbs = round(start_weight - current_weight, 1)
    remaining = round(current_weight - goal_weight, 1)
    progress_pct = round(lost_lbs / (start_weight - goal_weight) * 100, 1) if start_weight != goal_weight else 0

    # Recent rate (last 28 days regression)
    recent = [(d, w) for d, w in weight_series
              if d >= (datetime.now(timezone.utc) - timedelta(days=28)).strftime("%Y-%m-%d")]
    weekly_rate = 0.0
    slope_per_day = 0.0
    if len(recent) >= 4:
        x = [(datetime.strptime(d, "%Y-%m-%d") - datetime.strptime(recent[0][0], "%Y-%m-%d")).days for d, _ in recent]
        y = [w for _, w in recent]
        n = len(x)
        sx, sy = sum(x), sum(y)
        sxy = sum(a * b for a, b in zip(x, y))
        sxx = sum(a * a for a in x)
        denom = n * sxx - sx * sx
        slope_per_day = (n * sxy - sx * sy) / denom if denom else 0
        weekly_rate = round(slope_per_day * 7, 2)

    # Projected goal date
    projected_goal_date = None
    days_to_goal = None
    if weekly_rate < 0 and current_weight > goal_weight:
        days = (current_weight - goal_weight) / abs(slope_per_day) if abs(slope_per_day) > 0 else 0
        projected_goal_date = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")
        days_to_goal = int(days)

    return _ok({
        "journey": {
            "start_weight_lbs":   start_weight,
            "goal_weight_lbs":    goal_weight,
            "current_weight_lbs": round(current_weight),
            "lost_lbs":           lost_lbs,
            "remaining_lbs":      remaining,
            "progress_pct":       progress_pct,
            "weekly_rate_lbs":    weekly_rate,
            "projected_goal_date": projected_goal_date,
            "days_to_goal":       days_to_goal,
            "started_date":       EXPERIMENT_START,
        }
    }, cache_seconds=3600)



def handle_character() -> dict:
    """
    GET /api/character
    Returns: character level, pillar scores, recent events.
    Cache: 900s (15 min) — computed nightly but visitors expect freshness.
    """
    # Character-sheet compute writes YESTERDAY's sheet daily ~16:30 UTC, so the freshest
    # record is routinely 1-2 days old. Take the latest available DATE# record (plus the
    # one before it, for day-over-day deltas) rather than a fixed today/yesterday window —
    # that window returned 503 for ~16h every day (00:00 UTC until the daily run landed),
    # degrading the Cockpit. `as_of_date` tells the reader how fresh it is.
    pk = f"{USER_PREFIX}character_sheet"
    _resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with("DATE#"),
        ScanIndexForward=False,
        Limit=2,
    )
    _recs = _decimal_to_float(_resp.get("Items", []))
    record = _recs[0] if _recs else None
    prior_record = _recs[1] if len(_recs) > 1 else None

    if not record:
        return _error(503, "Character sheet not yet computed")
    date_str = str(record["sk"]).replace("DATE#", "")[:10]

    PILLAR_ORDER = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
    PILLAR_EMOJI = {"sleep": "😴", "movement": "🏋️", "nutrition": "🥗", "metabolic": "📊",
                    "mind": "🧠", "relationships": "💬", "consistency": "🎯"}

    pillars = []
    for p in PILLAR_ORDER:
        pd = record.get(f"pillar_{p}", {})
        pillars.append({
            "name":      p,
            "emoji":     PILLAR_EMOJI.get(p, ""),
            "level":     float(pd.get("level", 1)),
            "raw_score": float(pd.get("raw_score", 0)),
            "tier":      pd.get("tier", "Foundation"),
            "xp_delta":  float(pd.get("xp_delta", 0)),
            "xp_earned": float(pd.get("xp_earned", 0)),
            "score_delta": None,  # day-over-day move; filled below when a prior day exists
        })

    # Pre-experiment: show zeroed character (experiment hasn't started)
    if date_str < EXPERIMENT_START:
        return _ok({
            "character": {
                "level": 1, "tier": "Foundation", "tier_emoji": "\ud83d\udd28",
                "xp_total": 0, "as_of_date": date_str,
                "pre_experiment": True,
            },
            "pillars": [{"name": p, "emoji": PILLAR_EMOJI.get(p, ""),
                         "level": 1, "raw_score": 0, "tier": "Foundation",
                         "xp_delta": 0} for p in PILLAR_ORDER],
        }, cache_seconds=900)

    # DPR-1.16 + Day-Grade Replay: deltas vs the PRIOR computed day (record-over-record,
    # robust to compute lag/gaps), not calendar yesterday.
    composite = sum(p["raw_score"] for p in pillars) / max(len(pillars), 1)
    composite_delta_1d = None
    if prior_record:
        _yd_scores = [float(prior_record.get(f"pillar_{p}", {}).get("raw_score", 0)) for p in PILLAR_ORDER]
        _yd_composite = sum(_yd_scores) / max(len(_yd_scores), 1)
        composite_delta_1d = round(composite - _yd_composite, 1)
        # per-pillar day-over-day score move (aligned by PILLAR_ORDER)
        for _pp, _yd_s in zip(pillars, _yd_scores):
            _pp["score_delta"] = round(_pp["raw_score"] - _yd_s, 1)

    return _ok({
        "character": {
            "level":      float(record.get("character_level", 1)),
            "tier":       record.get("character_tier", "Foundation"),
            "tier_emoji": record.get("character_tier_emoji", "🔨"),
            "xp_total":   float(record.get("character_xp", 0)),
            "as_of_date": date_str,
            "composite_score": round(composite, 1),
            "composite_delta_1d": composite_delta_1d,
        },
        "pillars": pillars,
    }, cache_seconds=900)



def handle_weight_progress() -> dict:
    """
    GET /api/weight_progress
    Returns: daily weight readings for last 180 days.
    Cache: 3600s (1 hr).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d180 = max((datetime.now(timezone.utc) - timedelta(days=180)).strftime("%Y-%m-%d"), EXPERIMENT_START)
    items = _query_source("withings", d180, today)

    readings = sorted(
        [
            {
                "date":       item["sk"].replace("DATE#", ""),
                "weight_lbs": round(float(item["weight_lbs"]), 1),
            }
            for item in items
            if item.get("weight_lbs")
        ],
        key=lambda x: x["date"],
    )

    return _ok({"weight_progress": readings}, cache_seconds=3600)



def handle_character_stats() -> dict:
    """
    GET /api/character_stats
    Returns: current character level, tier, and all 7 pillar scores.
    Cache: 3600s (1 hr) — computed nightly.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    pk = f"{USER_PREFIX}character_sheet"
    record = None
    for date_str in [today, yesterday]:
        resp = table.get_item(Key={"pk": pk, "sk": f"DATE#{date_str}"})
        record = _decimal_to_float(resp.get("Item"))
        if record:
            break
    if not record:
        # Pre-compute / data-not-yet-available is NOT a 5xx situation.
        # Return 200 with computed=false so:
        #   - WAF/CloudFront alarms don't fire on a normal "no data yet" state
        #   - Homepage gauge fallback chain works (cs.level falsy → vitals API)
        #   - Clients can branch on the flag without parsing magic strings
        # 5-min cache: short enough that the first compute lands quickly,
        # long enough that 50k visitors don't hammer DDB.
        return _ok({
            "character_stats": None,
            "pillars": None,
            "computed": False,
            "reason": "Character sheet not yet computed for today or yesterday",
        }, cache_seconds=300)

    PILLARS = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
    pillars = {}
    for p in PILLARS:
        pd = record.get(f"pillar_{p}", {})
        pillars[p] = {
            "level":     float(pd.get("level", 1)),
            "raw_score": float(pd.get("raw_score", 0)),
            "tier":      pd.get("tier", "Foundation"),
        }

    # Pre-experiment: zeroed character
    if date_str < EXPERIMENT_START:
        PILLARS_ZERO = {p: {"level": 1, "raw_score": 0, "tier": "Foundation"}
                        for p in PILLARS}
        return _ok({
            "character_stats": {
                "level": 1, "tier": "Foundation", "tier_emoji": "\ud83d\udd28",
                "xp_total": 0, "as_of_date": date_str, "pre_experiment": True,
            },
            "pillars": PILLARS_ZERO,
        }, cache_seconds=3600)

    return _ok({
        "character_stats": {
            "level":       float(record.get("character_level", 1)),
            "tier":        record.get("character_tier", "Foundation"),
            "tier_emoji":  record.get("character_tier_emoji", "🔨"),
            "xp_total":    float(record.get("character_xp", 0)),
            "as_of_date":  date_str,
        },
        "pillars": pillars,
    }, cache_seconds=3600)



def handle_timeline() -> dict:
    """
    GET /api/timeline
    Returns weight series + life events + experiments + level-ups
    for the interactive Transformation Timeline page.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = EXPERIMENT_START

    # Weight series (full journey)
    wt_items = _query_source("withings", start, today)
    weights = sorted(
        [{"date": i["sk"].replace("DATE#", ""), "lbs": round(float(i["weight_lbs"]), 1)}
         for i in wt_items if i.get("weight_lbs")],
        key=lambda x: x["date"]
    )

    # Life events (ADR-058: phase=pilot filtered)
    life_pk = f"USER#{USER_ID}#SOURCE#life_events"
    le_resp = table.query(**with_phase_filter({"KeyConditionExpression": Key("pk").eq(life_pk)}))
    life_events = [
        {"date": i.get("date", ""), "title": i.get("title", ""),
         "type": i.get("type", "other"), "weight": int(i.get("emotional_weight", 3))}
        for i in _decimal_to_float(le_resp.get("Items", []))
    ]

    # Experiments (ADR-058: phase=pilot filtered)
    exp_pk = f"USER#{USER_ID}#SOURCE#experiments"
    exp_resp = table.query(**with_phase_filter({"KeyConditionExpression": Key("pk").eq(exp_pk)}))
    experiments = [
        {"name": i.get("name", ""), "start": i.get("start_date", ""),
         "end": i.get("end_date"), "status": i.get("status", "active")}
        for i in _decimal_to_float(exp_resp.get("Items", []))
        if i.get("sk", "").startswith("EXP#")
    ]

    # Character level history (ADR-058: phase=pilot filtered)
    cs_pk = f"{USER_PREFIX}character_sheet"
    cs_resp = table.query(**with_phase_filter({
        "KeyConditionExpression": Key("pk").eq(cs_pk) & Key("sk").begins_with("DATE#"),
        "ScanIndexForward": True,
    }))
    level_events = []
    prev_level = 0
    for item in _decimal_to_float(cs_resp.get("Items", [])):
        lvl = int(float(item.get("character_level", 0)))
        if lvl > prev_level and prev_level > 0:
            level_events.append({
                "date": item.get("sk", "").replace("DATE#", ""),
                "level": lvl,
                "tier": item.get("character_tier", ""),
            })
        prev_level = lvl

    return _ok({
        "timeline": {
            "weights":      weights,
            "life_events":  sorted(life_events, key=lambda x: x["date"]),
            "experiments":  sorted(experiments, key=lambda x: x["start"]),
            "level_ups":    level_events,
            "journey_start": EXPERIMENT_START,
            "start_weight":  float(_get_profile().get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS)),
            "goal_weight":   float(_get_profile().get("goal_weight_lbs", 185.0)),
        }
    }, cache_seconds=3600)



def handle_journey_timeline() -> dict:
    """
    GET /api/journey_timeline
    Returns ordered timeline events for the Story page:
    - Weight milestones (first crossing of 5-lb thresholds)
    - Level-up events from character_sheet
    - Experiment start/completion events
    Cache: 3600s (1 hr).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_date = EXPERIMENT_START
    _p = _get_profile()
    start_weight = float(_p.get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS))
    goal_weight = float(_p.get("goal_weight_lbs", 185.0))

    events: list = []

    # ── 1. Day 1 anchor (ADR-058: copy rewritten in §8 with Elena voice) ─────
    events.append({
        "date":  start_date,
        "type":  "milestone",
        "title": "Day 1",
        "body":  f"Starting weight: {int(round(EXPERIMENT_BASELINE_WEIGHT_LBS))} lbs. Goal: 185.",
        "link":  "/story/",
    })

    # ── 2. Weight milestones (5-lb thresholds) ───────────────────────────────
    thresholds = list(range(295, int(goal_weight) - 1, -5))  # 295, 290, 285, …, 190, 185
    crossed: dict = {}  # threshold -> date string

    wk_pk = f"{USER_PREFIX}withings"
    try:
        wk_resp = table.query(
            KeyConditionExpression=Key("pk").eq(wk_pk) & Key("sk").between(
                f"DATE#{start_date}", f"DATE#{today}"
            ),
            ScanIndexForward=True,
        )
        for item in _decimal_to_float(wk_resp.get("Items", [])):
            wt = item.get("weight_lbs")
            if wt is None:
                continue
            wt = float(wt)
            date_str = item.get("date") or item.get("sk", "").replace("DATE#", "")
            for thr in thresholds:
                if thr not in crossed and wt <= thr:
                    crossed[thr] = date_str
    except Exception:
        pass

    for thr in sorted(crossed.keys(), reverse=True):  # highest first = earliest
        lbs_lost = start_weight - thr
        events.append({
            "date":  crossed[thr],
            "type":  "weight",
            "title": f"Crossed {thr} lbs — {int(lbs_lost)} lbs lost",
            "body":  f"Down {int(lbs_lost)} lbs from {int(round(start_weight))}. {round((lbs_lost / (start_weight - goal_weight)) * 100)}% of the way to goal.",
            "link":  "/live/",
        })

    # ── 3. Level-up events from character_sheet ──────────────────────────────
    cs_pk = f"{USER_PREFIX}character_sheet"
    try:
        cs_resp = table.query(
            KeyConditionExpression=Key("pk").eq(cs_pk) & Key("sk").between(
                f"DATE#{start_date}", f"DATE#{today}"
            ),
            ScanIndexForward=True,
        )
        seen_levels: set = set()
        _PILLAR_NAMES = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
        for item in _decimal_to_float(cs_resp.get("Items", [])):
            level = item.get("character_level")
            date_str = item.get("date") or item.get("sk", "").replace("DATE#", "")
            if level and level not in seen_levels:
                seen_levels.add(level)
                if level > 1:
                    # Enrich with top-scoring pillars that drove the level-up
                    top_pillars = []
                    for p in _PILLAR_NAMES:
                        pd = item.get(f"pillar_{p}", {})
                        if isinstance(pd, dict) and pd.get("raw_score"):
                            top_pillars.append((p.capitalize(), float(pd["raw_score"])))
                    top_pillars.sort(key=lambda x: -x[1])
                    drivers = ", ".join(f"{n} ({s:.0f})" for n, s in top_pillars[:3])
                    events.append({
                        "date":  date_str,
                        "type":  "level_up",
                        "title": f"Reached Character Level {int(level)}",
                        "body":  f"Driven by: {drivers}" if drivers else f"Level {int(level)} — {item.get('character_tier', '')}",
                        "link":  "/character/",
                    })
    except Exception:
        pass

    # ── 4. Experiment starts ─────────────────────────────────────────────────
    exp_pk = f"{USER_PREFIX}experiments"
    try:
        exp_resp = table.query(
            KeyConditionExpression=Key("pk").eq(exp_pk),
            ScanIndexForward=False,
            Limit=20,
        )
        for item in _decimal_to_float(exp_resp.get("Items", [])):
            if not item.get("sk", "").startswith("EXP#"):
                continue
            start = item.get("start_date", "")
            if not start or start < start_date:
                continue
            status = item.get("status", "")
            if status == "active":
                events.append({
                    "date":  start,
                    "type":  "experiment",
                    "title": f"Experiment: {item.get('name', 'Unnamed')}",
                    "body":  item.get("hypothesis", "")[:120] + ("…" if len(item.get("hypothesis", "")) > 120 else ""),
                    "link":  "/experiments/",
                })
            elif status == "completed":
                end = item.get("end_date", start)
                outcome = (item.get("outcome") or item.get("result_summary") or "")[:80]
                events.append({
                    "date":  end,
                    "type":  "discovery",
                    "title": f"Experiment Complete: {item.get('name', 'Unnamed')}",
                    "body":  outcome + ("…" if len(outcome) == 80 else ""),
                    "link":  "/discoveries/",
                })
    except Exception:
        pass

    # ── 5. FDR-significant correlation findings ────────────────────────
    corr_pk = f"{USER_PREFIX}weekly_correlations"
    try:
        corr_resp = table.query(
            KeyConditionExpression=Key("pk").eq(corr_pk),
            ScanIndexForward=True,
        )
        _METRIC_LABELS = {
            "hrv": "Heart Rate Variability", "recovery_score": "Recovery Score",
            "sleep_duration": "Sleep Duration", "sleep_score": "Sleep Score",
            "resting_hr": "Resting Heart Rate", "strain": "Strain",
            "tsb": "Training Stress Balance", "training_kj": "Training Load",
            "training_mins": "Training Minutes", "protein_g": "Protein",
            "calories": "Calories", "carbs_g": "Carbs", "steps": "Steps",
            "habit_pct": "Habit Completion", "day_grade": "Day Grade",
            "readiness": "Readiness", "tier0_streak": "Tier 0 Streak",
        }
        seen_findings: set = set()
        for item in _decimal_to_float(corr_resp.get("Items", [])):
            week = item.get("week", item.get("sk", "").replace("WEEK#", ""))
            end_d = item.get("end_date", "")
            corrs = item.get("correlations", {})
            if not isinstance(corrs, dict):
                continue
            for label, data in corrs.items():
                if not data.get("fdr_significant"):
                    continue
                if label in seen_findings:
                    continue  # only show first detection
                seen_findings.add(label)
                r_val = float(data.get("pearson_r", 0) or 0)
                n_val = int(data.get("n_days", 0) or 0)
                ma = data.get("metric_a", "")
                mb = data.get("metric_b", "")
                la = _METRIC_LABELS.get(ma, ma)
                lb = _METRIC_LABELS.get(mb, mb)
                direction = "higher" if r_val > 0 else "lower"
                is_ci = data.get("counterintuitive", False)
                evt_type = "counterintuitive" if is_ci else "finding"
                title_prefix = "⚠️ Surprise: " if is_ci else "AI Finding: "
                events.append({
                    "date":  end_d or week,
                    "type":  evt_type,
                    "title": f"{title_prefix}{la} → {direction} {lb}",
                    "body":  f"r={r_val:+.2f} over {n_val} days. Passed FDR significance testing (week {week}).",
                    "link":  "/explorer/",
                    "meta":  {"r": r_val, "n": n_val, "pair": label, "week": week},
                })
    except Exception as e:
        logger.warning("journey_timeline: correlation events failed (non-fatal): %s", e)

    # Exclude pre-experiment events and sort chronologically
    events = [e for e in events if e["date"] >= start_date]
    events.sort(key=lambda e: e["date"])
    seen_evt: set = set()
    deduped = []
    for e in events:
        key = (e["date"], e["title"])
        if key not in seen_evt:
            seen_evt.add(key)
            deduped.append(e)

    # ── 6. DISC-7: Merge behavioral response annotations ──────────────
    try:
        ann_pk = f"{USER_PREFIX}discovery_annotations"
        ann_resp = table.query(
            KeyConditionExpression=Key("pk").eq(ann_pk),
            ScanIndexForward=True,
        )
        ann_items = _decimal_to_float(ann_resp.get("Items", []))
        # Build lookup: event_key → annotation data
        ann_lookup: dict = {}
        for ai in ann_items:
            ek = ai.get("sk", "").replace("EVENT#", "")
            ann_lookup[ek] = {
                "annotation": ai.get("annotation", ""),
                "action_taken": ai.get("action_taken"),
                "outcome": ai.get("outcome"),
            }
        # Attach annotations to matching events
        if ann_lookup:
            for e in deduped:
                ek = hashlib.sha256(
                    f"{e['date']}|{e['type']}|{e['title']}".encode()
                ).hexdigest()[:16]
                if ek in ann_lookup:
                    e["annotation"] = ann_lookup[ek]
    except Exception as _ann_e:
        logger.warning("journey_timeline: annotation merge failed (non-fatal): %s", _ann_e)

    return _ok({
        "as_of_date": today,
        "events":     deduped,
        "total":      len(deduped),
    }, cache_seconds=3600)



def handle_journey_waveform() -> dict:
    """
    GET /api/journey_waveform
    Returns 42 days of daily pillar-sum scores for the Story page emotional waveform.
    Score = sum of 7 pillar level_scores (0–700 range).
    Color tiers: green (>=250), amber (>=150), red (<150), gray (no data).
    Cache: 3600s (1 hr).
    """
    today = datetime.now(timezone.utc).date()
    start_date = (today - timedelta(days=41)).isoformat()
    end_date = today.isoformat()

    PILLARS = [
        "pillar_sleep", "pillar_nutrition", "pillar_movement",
        "pillar_metabolic", "pillar_mind", "pillar_consistency", "pillar_relationships",
    ]

    cs_pk = f"{USER_PREFIX}character_sheet"
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(cs_pk) & Key("sk").between(
                f"DATE#{start_date}", f"DATE#{end_date}"
            ),
            ScanIndexForward=True,
        )
        items = resp.get("Items", [])
    except Exception:
        items = []

    # Index by date
    by_date: dict = {}
    for item in items:
        date_str = item.get("date") or item.get("sk", "").replace("DATE#", "")
        if not date_str:
            continue
        total = 0.0
        for pillar in PILLARS:
            pdata = item.get(pillar, {})
            # boto3 Table resource returns already-deserialized Python values
            if isinstance(pdata, dict):
                ls = pdata.get("level_score")
                if ls is not None:
                    try:
                        total += float(ls)
                    except (TypeError, ValueError):
                        pass
        by_date[date_str] = round(total, 1)

    # Build ordered 42-day series
    days = []
    for i in range(42):
        d = (today - timedelta(days=41 - i)).isoformat()
        score = by_date.get(d)
        if score is None:
            color = "gray"
        elif score >= 250:
            color = "green"
        elif score >= 150:
            color = "amber"
        else:
            color = "red"
        days.append({"date": d, "score": score, "color": color})

    max_score = max((d["score"] for d in days if d["score"] is not None), default=1)

    return _ok({
        "days":      days,
        "max_score": max_score,
        "window":    42,
    }, cache_seconds=3600)



def handle_achievements() -> dict:
    """
    GET /api/achievements
    Computes earned/locked achievement badges from DynamoDB.
    Sources: habit_scores (streaks), character_sheet (level), withings (weight milestones),
             experiments (first experiment), habits (days tracked).
    Cache: 3600s (1 hr) — achievements update nightly.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d365 = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")

    # ── Streak data
    habit_pk = f"{USER_PREFIX}habit_scores"
    habit_resp = table.query(
        KeyConditionExpression=Key("pk").eq(habit_pk),
        ScanIndexForward=False,
        Limit=1,
    )
    habit_items = _decimal_to_float(habit_resp.get("Items", []))
    latest_habit = habit_items[0] if habit_items else {}
    current_streak = int(latest_habit.get("t0_perfect_streak") or latest_habit.get("t0_aggregate_streak") or 0)

    # Days tracked = count of habit_score records in last 365 days
    all_habits_resp = table.query(
        KeyConditionExpression=Key("pk").eq(habit_pk) & Key("sk").between(
            f"DATE#{d365}", f"DATE#{today}"
        ),
    )
    days_tracked = len(all_habits_resp.get("Items", []))

    # ── Character level
    char_pk = f"{USER_PREFIX}character_sheet"
    char_resp = table.query(
        KeyConditionExpression=Key("pk").eq(char_pk),
        ScanIndexForward=False,
        Limit=1,
    )
    char_items = _decimal_to_float(char_resp.get("Items", []))
    current_level = int(float((char_items[0] if char_items else {}).get("character_level", 1)))

    # ── Weight milestones
    withings = _latest_item("withings")
    current_weight = float(withings.get("weight_lbs", 999)) if withings else 999.0
    start_weight = float(_get_profile().get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS))
    lost_lbs = round(start_weight - current_weight, 1) if current_weight < start_weight else 0

    # ── First experiment
    exp_pk = f"{USER_PREFIX}experiments"
    exp_resp = table.query(
        KeyConditionExpression=Key("pk").eq(exp_pk),
        ScanIndexForward=False,
        Limit=50,
    )
    all_exps = [
        i for i in _decimal_to_float(exp_resp.get("Items", []))
        if i.get("sk", "").startswith("EXP#")
    ]
    completed_exps = [i for i in all_exps if i.get("status") in ("completed", "confirmed")]

    # EL-21: Streak detection — last 3 finished experiments all completed (no abandoned/failed)
    _exp_has_3_streak = False
    finished = sorted(
        [i for i in all_exps if i.get("status") in ("completed", "confirmed", "abandoned")],
        key=lambda x: x.get("end_date") or x.get("start_date", ""), reverse=True,
    )
    if len(finished) >= 3:
        _exp_has_3_streak = all(e.get("status") in ("completed", "confirmed") for e in finished[:3])

    # EL-21: Pillar coverage — completed experiment in each of 7 pillars
    _ALL_PILLARS = {"sleep", "movement", "nutrition", "supplements", "mental", "social", "discipline"}
    _covered_pillars = set()
    for e in completed_exps:
        for tag in (e.get("tags") or []):
            tag_lower = tag.lower()
            for p in _ALL_PILLARS:
                if p in tag_lower:
                    _covered_pillars.add(p)
    _exp_all_pillars_covered = _covered_pillars >= _ALL_PILLARS

    # ── Challenge completion counts
    challenges_pk = f"USER#{USER_ID}#SOURCE#challenges"
    completed_challenges = 0
    perfect_challenges = 0
    try:
        ch_resp = table.query(
            KeyConditionExpression=Key("pk").eq(challenges_pk) & Key("sk").begins_with("CHALLENGE#"),
        )
        ch_items = _decimal_to_float(ch_resp.get("Items", []))
        for ch in ch_items:
            if ch.get("status") == "completed":
                completed_challenges += 1
                checkins = ch.get("daily_checkins", [])
                if checkins:
                    success = sum(1 for c in checkins if c.get("completed"))
                    if success == len(checkins):
                        perfect_challenges += 1
    except Exception as _ch_e:
        logger.warning("[achievements] Challenge query failed (non-fatal): %s", _ch_e)

    def badge(id_, label, category, desc, earned, earned_date=None, unlock_hint=None, icon=None):
        return {
            "id": id_, "label": label, "category": category, "description": desc,
            "earned": earned, "earned_date": earned_date, "icon": icon, "unlock_hint": unlock_hint,
        }

    achievements = [
        # ── Streak
        badge("week_warrior", "Week Warrior", "streak",
              "7-day Tier 0 habit streak",
              earned=current_streak >= 7,
              earned_date=today if current_streak >= 7 else None,
              unlock_hint=f"{max(0, 7 - current_streak)} days to unlock" if current_streak < 7 else None),
        badge("monthly_grind", "Monthly Grind", "streak",
              "30-day Tier 0 habit streak",
              earned=current_streak >= 30,
              earned_date=today if current_streak >= 30 else None,
              unlock_hint=f"{max(0, 30 - current_streak)} days to unlock" if current_streak < 30 else None),
        badge("quarterly", "Quarterly", "streak",
              "90-day Tier 0 habit streak",
              earned=current_streak >= 90,
              unlock_hint=f"{max(0, 90 - current_streak)} days to unlock" if current_streak < 90 else None),

        # ── Level
        badge("first_level_up", "First Level Up", "level",
              "Reached Character Level 2",
              earned=current_level >= 2,
              earned_date=today if current_level >= 2 else None),
        badge("apprentice", "Apprentice", "level",
              "Reached Character Level 5",
              earned=current_level >= 5,
              unlock_hint=f"Level {current_level} → Level 5 needed" if current_level < 5 else None),
        badge("journeyman", "Journeyman", "level",
              "Reached Character Level 10",
              earned=current_level >= 10,
              unlock_hint=f"Level {current_level} → Level 10 needed" if current_level < 10 else None),

        # ── Weight LOSS milestones (every 10 lbs)
        badge("lost_10", "Lost 10 lbs", "milestone",
              "Lost 10 lbs from starting weight",
              earned=lost_lbs >= 10, icon="\u2696\ufe0f",
              unlock_hint=f"{10 - lost_lbs:.0f} lbs to go" if lost_lbs < 10 else None),
        badge("lost_20", "Lost 20 lbs", "milestone",
              "Lost 20 lbs from starting weight",
              earned=lost_lbs >= 20, icon="\u2696\ufe0f",
              unlock_hint=f"{20 - lost_lbs:.0f} lbs to go" if lost_lbs < 20 else None),
        badge("lost_30", "Lost 30 lbs", "milestone",
              "Lost 30 lbs from starting weight",
              earned=lost_lbs >= 30, icon="\u2696\ufe0f",
              unlock_hint=f"{30 - lost_lbs:.0f} lbs to go" if lost_lbs < 30 else None),
        badge("lost_40", "Lost 40 lbs", "milestone",
              "Lost 40 lbs from starting weight",
              earned=lost_lbs >= 40, icon="\u2696\ufe0f",
              unlock_hint=f"{40 - lost_lbs:.0f} lbs to go" if lost_lbs < 40 else None),
        badge("lost_50", "Lost 50 lbs", "milestone",
              "Lost 50 lbs from starting weight",
              earned=lost_lbs >= 50, icon="\u2696\ufe0f",
              unlock_hint=f"{50 - lost_lbs:.0f} lbs to go" if lost_lbs < 50 else None),
        badge("lost_60", "Lost 60 lbs", "milestone",
              "Lost 60 lbs from starting weight",
              earned=lost_lbs >= 60, icon="\u2696\ufe0f",
              unlock_hint=f"{60 - lost_lbs:.0f} lbs to go" if lost_lbs < 60 else None),
        badge("lost_70", "Lost 70 lbs", "milestone",
              "Lost 70 lbs from starting weight",
              earned=lost_lbs >= 70, icon="\u2696\ufe0f",
              unlock_hint=f"{70 - lost_lbs:.0f} lbs to go" if lost_lbs < 70 else None),
        badge("lost_80", "Lost 80 lbs", "milestone",
              "Lost 80 lbs from starting weight",
              earned=lost_lbs >= 80, icon="\u2696\ufe0f",
              unlock_hint=f"{80 - lost_lbs:.0f} lbs to go" if lost_lbs < 80 else None),
        badge("lost_90", "Lost 90 lbs", "milestone",
              "Lost 90 lbs from starting weight",
              earned=lost_lbs >= 90, icon="\u2696\ufe0f",
              unlock_hint=f"{90 - lost_lbs:.0f} lbs to go" if lost_lbs < 90 else None),
        badge("lost_100", "Lost 100 lbs", "milestone",
              "Lost 100 lbs from starting weight",
              earned=lost_lbs >= 100, icon="\u2696\ufe0f",
              unlock_hint=f"{100 - lost_lbs:.0f} lbs to go" if lost_lbs < 100 else None),

        # ── Weight TARGET milestones
        badge("sub_280", "Sub-280", "milestone",
              "Weight under 280 lbs",
              earned=current_weight < 280, icon="\ud83c\udfaf",
              unlock_hint=f"{current_weight - 280:.0f} lbs to go" if current_weight >= 280 else None),
        badge("sub_250", "Sub-250", "milestone",
              "Weight under 250 lbs",
              earned=current_weight < 250, icon="\ud83c\udfaf",
              unlock_hint=f"{current_weight - 250:.0f} lbs to go" if current_weight >= 250 else None),
        badge("sub_220", "Sub-220", "milestone",
              "Weight under 220 lbs",
              earned=current_weight < 220, icon="\ud83c\udfaf",
              unlock_hint=f"{current_weight - 220:.0f} lbs to go" if current_weight >= 220 else None),
        badge("sub_200", "Sub-200", "milestone",
              "Weight under 200 lbs",
              earned=current_weight < 200, icon="\ud83c\udfaf",
              unlock_hint=f"{current_weight - 200:.0f} lbs to go" if current_weight >= 200 else None),

        # ── Data
        badge("100_days", "100 Days Tracked", "data",
              "100+ days of habit logging",
              earned=days_tracked >= 100,
              earned_date=today if days_tracked >= 100 else None,
              unlock_hint=f"{max(0, 100 - days_tracked)} days to unlock" if days_tracked < 100 else None),
        badge("365_days", "Year of Data", "data",
              "365 days of habit logging",
              earned=days_tracked >= 365,
              unlock_hint=f"{max(0, 365 - days_tracked)} days to unlock" if days_tracked < 365 else None),

        # ── Experiment
        badge("first_experiment", "First Experiment", "science",
              "Completed first N=1 experiment",
              earned=len(completed_exps) >= 1,
              earned_date=today if completed_exps else None),
        badge("hypothesis_confirmed", "Hypothesis Confirmed", "science",
              "N=1 result statistically validated",
              earned=False,  # requires manual confirmation
              unlock_hint="Complete a tracked experiment to unlock"),

        # EL-21: Experiment evolution badges
        badge("exp_3_completed", "Lab Rat", "science",
              "Completed 3 experiments",
              earned=len(completed_exps) >= 3,
              earned_date=today if len(completed_exps) >= 3 else None,
              unlock_hint=f"{max(0, 3 - len(completed_exps))} experiments to unlock" if len(completed_exps) < 3 else None),
        badge("exp_5_completed", "Research Fellow", "science",
              "Completed 5 experiments",
              earned=len(completed_exps) >= 5,
              earned_date=today if len(completed_exps) >= 5 else None,
              unlock_hint=f"{max(0, 5 - len(completed_exps))} experiments to unlock" if len(completed_exps) < 5 else None),
        badge("exp_10_completed", "Principal Investigator", "science",
              "Completed 10 experiments",
              earned=len(completed_exps) >= 10,
              unlock_hint=f"{max(0, 10 - len(completed_exps))} experiments to unlock" if len(completed_exps) < 10 else None),
        badge("exp_streak_3", "Hot Streak", "science",
              "3 consecutive completed experiments (no fails)",
              earned=_exp_has_3_streak,
              unlock_hint="Complete 3 experiments in a row without abandoning"),
        badge("exp_all_pillars", "Renaissance Man", "science",
              "Completed experiment in every pillar",
              earned=_exp_all_pillars_covered,
              unlock_hint="Complete at least one experiment in each of the 7 pillars"),

        # ── Challenges
        badge("first_challenge", "First Challenge", "challenge",
              "Completed first challenge",
              earned=completed_challenges >= 1,
              earned_date=today if completed_challenges >= 1 else None),
        badge("five_challenges", "Challenge Regular", "challenge",
              "Completed 5 challenges",
              earned=completed_challenges >= 5,
              unlock_hint=f"{max(0, 5 - completed_challenges)} challenges to unlock" if completed_challenges < 5 else None),
        badge("ten_challenges", "Challenge Veteran", "challenge",
              "Completed 10 challenges",
              earned=completed_challenges >= 10,
              unlock_hint=f"{max(0, 10 - completed_challenges)} challenges to unlock" if completed_challenges < 10 else None),
        badge("twenty_five_challenges", "Challenge Legend", "challenge",
              "Completed 25 challenges",
              earned=completed_challenges >= 25,
              unlock_hint=f"{max(0, 25 - completed_challenges)} challenges to unlock" if completed_challenges < 25 else None),
        badge("perfect_challenge", "Flawless", "challenge",
              "Completed a challenge with 100% success rate (7+ days)",
              earned=perfect_challenges >= 1,
              unlock_hint="Complete a 7+ day challenge without missing a single day"),
    ]

    earned_count = sum(1 for a in achievements if a["earned"])

    return _ok({
        "achievements": achievements,
        "summary": {
            "earned": earned_count,
            "total":  len(achievements),
            "current_streak": current_streak,
            "days_tracked":   days_tracked,
            "current_level":  current_level,
            "current_weight": round(current_weight),
            "completed_challenges": completed_challenges,
            "perfect_challenges": perfect_challenges,
        },
    }, cache_seconds=3600)



def handle_snapshot() -> dict:
    """
    GET /api/snapshot
    Combined response: vitals + journey + character in one call.
    Reduces client-side roundtrips for pages that need all three (e.g. /live/, homepage).
    On partial failure any sub-object is null; callers must handle gracefully.
    """
    vitals_result = journey_result = character_result = None
    try:
        vitals_result = handle_vitals()
        vitals_body = json.loads(vitals_result.get("body", "{}"))
    except Exception as _e:
        logger.warning("[snapshot] vitals failed: %s", _e)
        vitals_body = None

    try:
        journey_result = handle_journey()
        journey_body = json.loads(journey_result.get("body", "{}"))
    except Exception as _e:
        logger.warning("[snapshot] journey failed: %s", _e)
        journey_body = None

    try:
        character_result = handle_character()
        character_body = json.loads(character_result.get("body", "{}"))
    except Exception as _e:
        logger.warning("[snapshot] character failed: %s", _e)
        character_body = None

    payload = {
        "vitals":    vitals_body,
        "journey":   journey_body,
        "character": character_body,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return {
        "statusCode": 200,
        "headers":    {**CORS_HEADERS, "Cache-Control": "public, max-age=60"},
        "body":       json.dumps(payload, default=str),
    }


