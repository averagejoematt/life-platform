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
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal  # noqa: F401

import weight_trend  # shared weekly-rate + projection (layer module)
from boto3.dynamodb.conditions import Key
from phase_filter import with_phase_filter  # ADR-058 — used by handle_timeline

from web.site_api_common import (
    CORS_HEADERS,
    EXPERIMENT_BASELINE_WEIGHT_LBS,
    EXPERIMENT_START,
    PT,
    S3_REGION,
    USER_ID,
    USER_PREFIX,
    _clamp_today,
    _decimal_to_float,
    _error,
    _get_profile,
    _latest_item,
    _latest_item_asof,
    _ok,
    _query_source,
    logger,
    pre_start_meta,
    table,
)


def handle_vitals(date: str | None = None) -> dict:
    """
    GET /api/vitals[?date=YYYY-MM-DD]
    Returns: current weight, HRV, recovery, RHR, sleep hours, 30d trends.
    Cache: 300s (5 min) — feels real-time, Lambda fires ~12x/hour at 50k traffic.
    With ?date= (Phase 4 historical window): the cockpit AS OF that date — latest
    readings on-or-before it, 30d trends ending there, pilot/prior-cycle records
    included, a future date clamps to today, cached a day (the past is immutable).
    """
    import re as _re

    if date and not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return _error(400, "date must be YYYY-MM-DD")
    ip = bool(date)  # ADR-058: include pilot/prior-cycle records only when time-travelling
    _now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    anchor = min(date, _now) if date else _now  # clamp a future scrub to today
    _anchor_dt = datetime.strptime(anchor, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    today = anchor
    d30 = (_anchor_dt - timedelta(days=30)).strftime("%Y-%m-%d")
    d7 = (_anchor_dt - timedelta(days=7)).strftime("%Y-%m-%d")

    # Whoop (recovery, HRV, RHR, sleep)
    whoop_7d = _query_source("whoop", d7, today, include_pilot=ip)
    whoop_30d = _query_source("whoop", d30, today, include_pilot=ip)

    # Latest reading
    latest = sorted([w for w in whoop_7d if w.get("recovery_score") is not None], key=lambda x: x.get("sk", ""), reverse=True)
    latest = latest[0] if latest else {}

    # 30d averages + trends. Order by date (oldest→newest) explicitly so the
    # half-vs-half trend is chronological by construction, not dependent on query
    # return order (the prior constant-key sort was a no-op that only worked because
    # the query happened to return ascending sk). See AUDIT BUG-04. rhr_trend below
    # passes reversed values — that's the deliberate "lower is better" inversion.
    whoop_30d_sorted = sorted(whoop_30d, key=lambda w: w.get("sk", ""))
    hrv_vals = [float(w["hrv"]) for w in whoop_30d_sorted if w.get("hrv")]
    rhr_vals = [float(w["resting_heart_rate"]) for w in whoop_30d_sorted if w.get("resting_heart_rate")]

    def trend(vals):
        if len(vals) < 6:
            return "insufficient_data"
        mid = len(vals) // 2
        first_avg = sum(vals[:mid]) / len(vals[:mid])
        second_avg = sum(vals[mid:]) / len(vals[mid:])
        if second_avg > first_avg * 1.03:
            return "improving"
        if second_avg < first_avg * 0.97:
            return "declining"
        return "stable"

    # G-3 → #491/M-6: latest weight via the ONE shared resolution
    # (weight_trend.latest_weight): Withings backscan + a 7-day apple_health
    # window. The old code inspected only the single latest apple_health item —
    # usually a steps record — so the Apple fallback engaged same-day only.
    # Time-travel: the latest weigh-in on-or-before the anchor (else the live latest).
    withings_latest = _latest_item_asof("withings", today, ip) if date else _latest_item("withings")
    try:
        _ah_start = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
        _ah_7d = _query_source("apple_health", _ah_start, today, include_pilot=ip)
    except Exception:
        _ah_7d = []
    _lw = weight_trend.latest_weight([withings_latest] if withings_latest else [], _ah_7d)
    current_weight = _lw["weight_lbs"]
    weight_as_of = _lw["as_of"]

    withings_30d = _query_source("withings", d30, today, include_pilot=ip)
    weight_vals = [float(w["weight_lbs"]) for w in withings_30d if w.get("weight_lbs")]
    weight_delta_30d = round(weight_vals[-1] - weight_vals[0], 1) if len(weight_vals) >= 2 else None

    recovery_pct = float(latest.get("recovery_score", 0))
    recovery_status = "green" if recovery_pct >= 67 else ("yellow" if recovery_pct >= 34 else "red")

    # DPR-1.20: Page freshness for nav badges
    _today_iso = datetime.now(timezone.utc).isoformat()
    _as_of = latest.get("sk", "").replace("DATE#", "") if latest else today
    # Temporal frame: sleep/recovery/HRV/RHR are wake-date-keyed (stored under the
    # morning they set up). The reading came from the night BEFORE that morning, so
    # night_of = as_of - 1 day. Surfacing this lets the front-end say "the night of
    # <night_of>" precisely, even when the latest record lags a day or two. (Weight,
    # by contrast, is same-day "today" — see weight_as_of.)
    _night_of = None
    try:
        _night_of = (datetime.strptime(_as_of[:10], "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    except Exception:
        _night_of = None
    # Nutrition is a manual end-of-day upload — structurally ~24h behind. Its freshness
    # is the latest COMPLETE day (normally yesterday), NOT today. Hardcoding _today_iso
    # here (the old behavior) made the nutrition page read "as of now" when today's
    # intake simply hasn't been uploaded yet. Mirror /physical's weight_as_of pattern.
    _nutrition_as_of = None
    try:
        _mf = _query_source("macrofactor", (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d"), today)
        _mf_dates = [(m.get("date") or m.get("sk", "").replace("DATE#", "")) for m in _mf]
        _nutrition_as_of = max([d for d in _mf_dates if d], default=None)
    except Exception:
        _nutrition_as_of = None
    page_freshness = {
        "/live": _today_iso,
        "/character": _today_iso,
        "/sleep": _as_of + "T12:00:00Z" if _as_of else _today_iso,
        "/glucose": _today_iso,
        "/nutrition": _nutrition_as_of + "T12:00:00Z" if _nutrition_as_of else _today_iso,
        "/training": _today_iso,
        "/physical": weight_as_of + "T12:00:00Z" if weight_as_of else _today_iso,
        "/habits": _today_iso,
        "/explorer": _today_iso,
    }

    return _ok(
        {
            "vitals": {
                "weight_lbs": round(current_weight) if current_weight is not None else None,
                "weight_as_of": weight_as_of,
                "weight_delta_30d": weight_delta_30d,
                "hrv_ms": round(float(latest.get("hrv", 0)), 1) if latest.get("hrv") else None,
                "hrv_30d_avg": round(sum(hrv_vals) / len(hrv_vals), 1) if hrv_vals else None,
                "hrv_trend": trend(hrv_vals),
                "rhr_bpm": round(float(latest.get("resting_heart_rate", 0)), 0) if latest.get("resting_heart_rate") else None,
                "rhr_trend": trend(list(reversed(rhr_vals))),  # lower is better
                "recovery_pct": round(recovery_pct, 0),
                "recovery_status": recovery_status,
                "sleep_hours": round(float(latest.get("sleep_duration_hours", 0)), 1) if latest.get("sleep_duration_hours") else None,
                "as_of_date": _as_of,
                # Temporal frame (additive): recovery/sleep/hrv/rhr are about last
                # night and set up the as_of_date morning; weight (weight_as_of) is
                # same-day. night_of is the evening those readings came from.
                "frame": "last_night",
                "night_of": _night_of,
                "time_travel": ip,
            },
            "page_freshness": page_freshness,
        },
        cache_seconds=86400 if ip else 300,  # the past is immutable
    )


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
        [(w["sk"].replace("DATE#", ""), float(w["weight_lbs"])) for w in withings_all if w.get("weight_lbs")], key=lambda x: x[0]
    )

    if not weight_series:
        # G-4: Fall back to last known weight — never return 503 for missing recent data.
        withings_latest = _latest_item("withings")
        if withings_latest and withings_latest.get("weight_lbs") is not None:
            last_date = withings_latest.get("sk", "").replace("DATE#", "") or withings_latest.get("date", today)
            weight_series = [(last_date, float(withings_latest["weight_lbs"]))]
        else:
            weight_series = [
                (EXPERIMENT_START, EXPERIMENT_BASELINE_WEIGHT_LBS)
            ]  # ADR-058: genesis baseline; only used when no Withings data exists

    _p = _get_profile()
    start_weight = float(_p.get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS))
    goal_weight = float(_p.get("goal_weight_lbs", 185.0))
    current_weight = weight_series[-1][1]
    last_weighin_date = weight_series[-1][0]
    # #491/M-6: the shared resolution can find a NEWER Apple Health weigh-in
    # (travel scale) than the Withings series — same helper as vitals/character.
    try:
        _ah_start = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        _lw = weight_trend.latest_weight([], _query_source("apple_health", _ah_start, today))
        if _lw["as_of"] and _lw["as_of"] > last_weighin_date:
            current_weight = _lw["weight_lbs"]
            last_weighin_date = _lw["as_of"]
    except Exception:
        pass
    lost_lbs = round(start_weight - current_weight, 1)
    remaining = round(current_weight - goal_weight, 1)
    progress_pct = round(lost_lbs / (start_weight - goal_weight) * 100, 1) if start_weight != goal_weight else 0

    # Recent rate + projection via the ONE shared computation (weight_trend) — the same
    # call the daily brief / public_stats uses, so the rate is identical everywhere.
    # Projection stays suppressed until the weigh-in record spans >=21 days (early-cut
    # water weight would otherwise project an impossible finish line).
    _traj = weight_trend.weight_trajectory(weight_series, current_weight, goal_weight)
    weekly_rate = _traj["weekly_rate_lbs"]
    weighin_span_days = _traj["weighin_span_days"]
    rate_provisional = _traj["rate_provisional"]
    projected_goal_date = _traj["projected_goal_date"]
    days_to_goal = _traj["days_to_goal"]

    # Day-of-experiment counter (1-indexed, experiment TZ) — the home/cockpit
    # "what day are we on" number. Single source so labels stay in sync.
    _day_n = max((datetime.now(PT).date() - date.fromisoformat(EXPERIMENT_START)).days + 1, 0)

    journey = {
        "start_weight_lbs": start_weight,
        "goal_weight_lbs": goal_weight,
        "current_weight_lbs": round(current_weight),
        "lost_lbs": lost_lbs,
        "remaining_lbs": remaining,
        "progress_pct": progress_pct,
        "weekly_rate_lbs": weekly_rate,
        # #535: every claim carries its uncertainty. The rate is an interval and
        # the goal date is a range (earliest..latest), not a false-precision point.
        "weekly_rate_ci_low": _traj.get("weekly_rate_ci_low"),
        "weekly_rate_ci_high": _traj.get("weekly_rate_ci_high"),
        "projection_confidence": _traj.get("projection_confidence"),
        "rate_provisional": rate_provisional,
        "weighin_span_days": weighin_span_days,
        "projected_goal_date": projected_goal_date,
        "projected_goal_date_earliest": _traj.get("projected_goal_date_earliest"),
        "projected_goal_date_latest": _traj.get("projected_goal_date_latest"),
        "days_to_goal": days_to_goal,
        "started_date": EXPERIMENT_START,
        # The date behind current_weight_lbs/lost_lbs — the front-end pairs the
        # (possibly days-stale) weight with a live day counter, so it needs the
        # as-of anchor to stay honest during a weigh-in gap.
        "last_weighin_date": last_weighin_date,
        "day_n": _day_n,
        "week_n": (max(_day_n - 1, 0) // 7) + 1,
        # Height (profile, authoritative) so the page can show a de-emphasized BMI
        # without deriving height from DEXA indices (which disagree ~1.5 in). Not
        # sensitive — already used in the waist-height ratio. P0.7.
        "height_inches": _p.get("height_inches"),
    }

    # PRE-START (#931): a staged FUTURE genesis means there is no baseline yet —
    # Day 1's weigh-in creates it. The countdown fields go ON and every delta /
    # progress / projection claim comes OFF (ADR-104: "down X lbs" against a
    # baseline that doesn't exist yet is an invented number). day_n already reads
    # 0 above. Inert (pre_start=False, nothing else changes) once genesis <= today.
    _pre = pre_start_meta()
    journey["pre_start"] = bool(_pre)
    if _pre:
        journey.update(_pre)
        for _k in (
            # #948: the weight + its as-of anchor travel TOGETHER (the in-code
            # contract above) — keeping a stale prior-cycle weigh-in while nulling
            # last_weighin_date served an unattributable ghost weight during the
            # countdown, and contradicted /api/vitals (which nulls weight_lbs).
            "current_weight_lbs",
            "lost_lbs",
            "remaining_lbs",
            "progress_pct",
            "weekly_rate_lbs",
            "weekly_rate_ci_low",
            "weekly_rate_ci_high",
            "projection_confidence",
            "rate_provisional",
            "weighin_span_days",
            "projected_goal_date",
            "projected_goal_date_earliest",
            "projected_goal_date_latest",
            "days_to_goal",
            "last_weighin_date",
        ):
            journey[_k] = None

    return _ok({"journey": journey}, cache_seconds=3600)


def handle_character(date: str | None = None) -> dict:
    """
    GET /api/character[?date=YYYY-MM-DD]
    Returns: character level, pillar scores, recent events.
    Cache: 900s (15 min) — computed nightly but visitors expect freshness.
    With ?date= (the time scrubber, 2026-06-13): the sheet as of that morning —
    latest record at-or-before the date, pilot/prior-cycle records included
    (history is explicitly cross-cycle), cached a day since the past is immutable.
    """
    import re as _re

    if date and not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return _error(400, "date must be YYYY-MM-DD")
    # Character-sheet compute writes YESTERDAY's sheet daily ~16:30 UTC, so the freshest
    # record is routinely 1-2 days old. Take the latest available DATE# record (plus the
    # one before it, for day-over-day deltas) rather than a fixed today/yesterday window —
    # that window returned 503 for ~16h every day (00:00 UTC until the daily run landed),
    # degrading the Cockpit. `as_of_date` tells the reader how fresh it is.
    PILLAR_ORDER = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
    PILLAR_EMOJI = {
        "sleep": "😴",
        "movement": "🏋️",
        "nutrition": "🥗",
        "metabolic": "📊",
        "mind": "🧠",
        "relationships": "💬",
        "consistency": "🎯",
    }

    def _zeroed_pre_experiment(as_of: str) -> dict:
        # The zeroed "experiment hasn't started" state. Used both when the experiment
        # hasn't begun AND — critically — when the phase filter (ADR-058) hides every
        # pilot/pre-genesis sheet right after a reset: the first experiment-phase sheet
        # isn't computed until the morning after genesis, and a 503 in that window
        # degraded the Cockpit. Show zeroed, never a 503.
        # #948: never stamp a FUTURE as_of — a staged genesis put "as of <tomorrow>"
        # in the cockpit footer and character hero, a freshness claim about a date
        # that hasn't happened. Clamp to today (PT); the countdown fields ride along
        # pre-start. Inert (no clamp, pre_start=False) once genesis <= today.
        _pre = pre_start_meta()
        return _ok(
            {
                "character": {
                    "level": 1,
                    "tier": "Foundation",
                    "tier_emoji": "🔨",
                    "xp_total": 0,
                    "as_of_date": min(as_of, datetime.now(PT).date().isoformat()),
                    "pre_experiment": True,
                },
                "pillars": [
                    {"name": p, "emoji": PILLAR_EMOJI.get(p, ""), "level": 1, "raw_score": 0, "tier": "Foundation", "xp_delta": 0}
                    for p in PILLAR_ORDER
                ],
                **(_pre or {"pre_start": False}),
            },
            cache_seconds=900,
        )

    pk = f"{USER_PREFIX}character_sheet"
    _key_cond = Key("pk").eq(pk) & (Key("sk").between("DATE#0000-00-00", f"DATE#{date}") if date else Key("sk").begins_with("DATE#"))
    _resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot character sheets (unless time-travelling)
                "KeyConditionExpression": _key_cond,
                "ScanIndexForward": False,
                "Limit": 2,
            },
            include_pilot=bool(date),
        )
    )
    _recs = _decimal_to_float(_resp.get("Items", []))
    record = _recs[0] if _recs else None
    prior_record = _recs[1] if len(_recs) > 1 else None

    # No experiment-phase sheet yet (incl. the post-reset window where all sheets are
    # pilot and filtered out) → zeroed state, not a 503.
    if not record:
        return _zeroed_pre_experiment(EXPERIMENT_START)
    date_str = str(record["sk"]).replace("DATE#", "")[:10]

    pillars = []
    for p in PILLAR_ORDER:
        pd = record.get(f"pillar_{p}", {})
        _drivers = pd.get("drivers") or {}
        pillars.append(
            {
                "name": p,
                "emoji": PILLAR_EMOJI.get(p, ""),
                "level": float(pd.get("level", 1)),
                "raw_score": float(pd.get("raw_score", 0)),
                "tier": pd.get("tier", "Foundation"),
                "xp_delta": float(pd.get("xp_delta", 0)),
                "xp_earned": float(pd.get("xp_earned", 0)),
                "score_delta": None,  # day-over-day move; filled below when a prior day exists
                # ADR-104 provenance — computed by the engine, never narrated:
                # how much real data backs the score, which behaviors didn't
                # happen, what's lifting/dragging, and whether levels are frozen
                # because the day carried no signal.
                "data_coverage": (float(pd["data_coverage"]) if pd.get("data_coverage") is not None else None),
                "coverage_hold": bool(pd.get("coverage_hold", False)),
                # #747: engine-computed, deterministic (ADR-105) — True only when
                # every weighted component had zero data today. Distinct from
                # coverage_hold (a real pillar having a thin day): this means the
                # pillar has no data source feeding it at all. Front end renders
                # a labeled "not yet instrumented" state instead of the bare
                # neutral raw_score; clears itself the day a component gets a
                # real value, no front-end change required.
                "not_instrumented": bool(pd.get("not_instrumented", False)),
                "not_instrumented_note": pd.get("not_instrumented_note"),
                "absent_behaviors": [str(b) for b in (pd.get("absent_behaviors") or [])],
                # #913 neglect honesty — the visible XP bleed (owed below the
                # 0-floor) and today's presence-driven atrophy on this pillar
                # (None when engaged / planned pause / not behavioral-heavy).
                # Absent on pre-v1.3.0 records → honest 0/None defaults.
                "xp_debt": float(pd.get("xp_debt", 0) or 0),
                "neglect_decay": (
                    {
                        "applied": True,
                        "multiplier": float(pd["neglect_decay"].get("multiplier", 1)),
                        "gap_days": float(pd["neglect_decay"].get("gap_days", 0)),
                    }
                    if isinstance(pd.get("neglect_decay"), dict)
                    else None
                ),
                "drivers": {
                    "top": [str(x) for x in (_drivers.get("top") or [])],
                    "dragging": [str(x) for x in (_drivers.get("dragging") or [])],
                    "absent": [str(x) for x in (_drivers.get("absent") or [])],
                    "no_data": [str(x) for x in (_drivers.get("no_data") or [])],
                },
            }
        )

    # Pre-experiment: show zeroed character (experiment hasn't started)
    if date_str < EXPERIMENT_START:
        return _zeroed_pre_experiment(date_str)

    # DPR-1.16 + Day-Grade Replay: deltas vs the PRIOR computed day (record-over-record,
    # robust to compute lag/gaps), not calendar yesterday.
    # #747: a not-yet-instrumented pillar's placeholder neutral score must not quietly
    # drag the whole-life composite toward 50 — exclude it, same as an absent reading.
    _composite_scores = [p["raw_score"] for p in pillars if not p.get("not_instrumented")]
    composite = (
        sum(_composite_scores) / len(_composite_scores)
        if _composite_scores
        else sum(p["raw_score"] for p in pillars) / max(len(pillars), 1)
    )
    composite_delta_1d = None
    if prior_record:
        _yd_scores = [float(prior_record.get(f"pillar_{p}", {}).get("raw_score", 0)) for p in PILLAR_ORDER]
        _yd_composite_scores = [
            float(prior_record.get(f"pillar_{p}", {}).get("raw_score", 0))
            for p in PILLAR_ORDER
            if not prior_record.get(f"pillar_{p}", {}).get("not_instrumented")
        ]
        _yd_composite = (
            sum(_yd_composite_scores) / len(_yd_composite_scores) if _yd_composite_scores else sum(_yd_scores) / max(len(_yd_scores), 1)
        )
        composite_delta_1d = round(composite - _yd_composite, 1)
        # per-pillar day-over-day score move (aligned by PILLAR_ORDER)
        for _pp, _yd_s in zip(pillars, _yd_scores):
            _pp["score_delta"] = round(_pp["raw_score"] - _yd_s, 1)

    return _ok(
        {
            "character": {
                "level": float(record.get("character_level", 1)),
                "tier": record.get("character_tier", "Foundation"),
                "tier_emoji": record.get("character_tier_emoji", "🔨"),
                "xp_total": float(record.get("character_xp", 0)),
                # #913: the visible bleed + the deterministic mood (engine-
                # computed, ADR-105). Absent on pre-v1.3.0 records → 0 / None.
                "xp_debt": float(record.get("character_xp_debt", 0) or 0),
                "character_mood": record.get("character_mood"),
                "character_mood_inputs": (
                    record.get("character_mood_inputs") if isinstance(record.get("character_mood_inputs"), dict) else None
                ),
                "as_of_date": date_str,
                "composite_score": round(composite, 1),
                "composite_delta_1d": composite_delta_1d,
                "time_travel": bool(date),
                # #590: the engine's designed cross-pillar couplings that are ACTIVE
                # right now (rare gameplay thresholds — e.g. Sleep Drag). The home
                # constellation lights these as directional overlay edges. Additive.
                "active_effects": [
                    {
                        "name": e.get("name"),
                        "emoji": e.get("emoji", ""),
                        "condition": e.get("condition", ""),
                        "targets": e.get("targets", {}),
                    }
                    for e in (record.get("active_effects") or [])
                    if isinstance(e, dict)
                ],
            },
            "pillars": pillars,
        },
        cache_seconds=86400 if date else 900,  # the past is immutable
    )


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
                "date": item["sk"].replace("DATE#", ""),
                "weight_lbs": round(float(item["weight_lbs"]), 1),
            }
            for item in items
            if item.get("weight_lbs")
        ],
        key=lambda x: x["date"],
    )

    return _ok({"weight_progress": readings}, cache_seconds=3600)


# /api/character_config — the public "how the engine works" contract (character
# sheet P1.2). A WHITELISTED subset of config/{user}/character_sheet.json (the
# MCP-editable engine config), served live so the sheet's mechanics panels can
# never drift from what the engine actually runs. Never spread the config.
# Excluded BY DESIGN:
#   * pillar `owner`   — the config names a real public figure; the public site
#     fictionalizes real names (fail-closed until owners migrate to registered
#     personas)
#   * `baseline`       — /api/journey serves the public weight numbers
#   * `avatar`, `protocols`, `_meta` internals — private/prescriptive
_CHAR_CONFIG_LEVELING_KEYS = (
    "ema_lambda",
    "ema_window_days",
    "level_up_streak_days",
    "level_down_streak_days",
    "tier_up_streak_days",
    "tier_down_streak_days",
    "level_step_threshold",
    "level_step_bands",  # ADR-104: graduated step sizes by target gap
    "level_change_min_coverage",  # ADR-104: no-signal days can't move levels
    "xp_per_level",
    "daily_xp_decay",
    "xp_buffer_threshold",
    "xp_debt_cap",  # #913: the visible-bleed cap
    "neglect_decay",  # #913: atrophy knobs (n_grace_days/rate/floor/min_behavioral_share)
    "tier_streak_overrides",
)


def handle_character_config() -> dict:
    """
    GET /api/character_config
    Returns: pillar weights + component weights/targets, leveling mechanics
    (streak gates incl. per-tier overrides, XP economy), xp_bands, tier bands,
    and cross-pillar effects (emoji stripped — §8, renderers draw icons).
    Cache: 3600s — the config changes rarely (MCP edits take effect next compute).
    """
    import boto3 as _boto3

    bucket = os.environ.get("S3_BUCKET", "matthew-life-platform")
    try:
        s3 = _boto3.client("s3", region_name=S3_REGION)
        raw = s3.get_object(Bucket=bucket, Key=f"config/{USER_ID}/character_sheet.json")["Body"].read()
        cfg = json.loads(raw)
    except Exception as e:
        logger.warning("character_config: config load failed: %s", e)
        return _ok({"config": None, "available": False}, cache_seconds=300)

    def _scalars(o: dict) -> dict:
        return {k: v for k, v in (o or {}).items() if isinstance(v, (int, float, str, bool))}

    pillars_out = {}
    for name, p in (cfg.get("pillars") or {}).items():
        pillars_out[name] = {
            "weight": p.get("weight"),
            "ema_lambda": p.get("ema_lambda"),
            "components": {cn: _scalars(cv) for cn, cv in (p.get("components") or {}).items()},
        }
    leveling = {k: v for k, v in (cfg.get("leveling") or {}).items() if k in _CHAR_CONFIG_LEVELING_KEYS}
    tiers = [{"name": t.get("name"), "min_level": t.get("min_level"), "max_level": t.get("max_level")} for t in cfg.get("tiers") or []]
    effects = [
        {"name": e.get("name"), "condition": e.get("condition"), "targets": e.get("targets")} for e in cfg.get("cross_pillar_effects") or []
    ]
    return _ok(
        {
            "available": True,
            "pillars": pillars_out,
            "leveling": leveling,
            "xp_bands": cfg.get("xp_bands") or [],
            "tiers": tiers,
            "cross_pillar_effects": effects,
            "updated_at": (cfg.get("_meta") or {}).get("last_updated"),
        },
        cache_seconds=3600,
    )


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
        return _ok(
            {
                "character_stats": None,
                "pillars": None,
                "computed": False,
                "reason": "Character sheet not yet computed for today or yesterday",
            },
            cache_seconds=300,
        )

    PILLARS = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
    pillars = {}
    for p in PILLARS:
        pd = record.get(f"pillar_{p}", {})
        pillars[p] = {
            "level": float(pd.get("level", 1)),
            "raw_score": float(pd.get("raw_score", 0)),
            "tier": pd.get("tier", "Foundation"),
        }

    # Pre-experiment: zeroed character
    if date_str < EXPERIMENT_START:
        PILLARS_ZERO = {p: {"level": 1, "raw_score": 0, "tier": "Foundation"} for p in PILLARS}
        # #948: align the stamp with /api/character's zeroed state \u2014 the honest
        # "as of" for a not-yet-started sheet is today (clamped so a staged future
        # genesis never stamps tomorrow), not the stale prior-cycle record's date;
        # the two character endpoints disagreed (2026-07-10 vs 2026-07-12).
        _pre = pre_start_meta()
        return _ok(
            {
                "character_stats": {
                    "level": 1,
                    "tier": "Foundation",
                    "tier_emoji": "\ud83d\udd28",
                    "xp_total": 0,
                    "as_of_date": min(EXPERIMENT_START, datetime.now(PT).date().isoformat()),
                    "pre_experiment": True,
                },
                "pillars": PILLARS_ZERO,
                **(_pre or {"pre_start": False}),
            },
            cache_seconds=3600,
        )

    return _ok(
        {
            "character_stats": {
                "level": float(record.get("character_level", 1)),
                "tier": record.get("character_tier", "Foundation"),
                "tier_emoji": record.get("character_tier_emoji", "🔨"),
                "xp_total": float(record.get("character_xp", 0)),
                "as_of_date": date_str,
            },
            "pillars": pillars,
        },
        cache_seconds=3600,
    )


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
        [{"date": i["sk"].replace("DATE#", ""), "lbs": round(float(i["weight_lbs"]), 1)} for i in wt_items if i.get("weight_lbs")],
        key=lambda x: x["date"],
    )

    # Life events (ADR-058: phase=pilot filtered)
    life_pk = f"USER#{USER_ID}#SOURCE#life_events"
    le_resp = table.query(**with_phase_filter({"KeyConditionExpression": Key("pk").eq(life_pk)}))
    life_events = [
        {
            "date": i.get("date", ""),
            "title": i.get("title", ""),
            "type": i.get("type", "other"),
            "weight": int(i.get("emotional_weight", 3)),
        }
        for i in _decimal_to_float(le_resp.get("Items", []))
    ]

    # Experiments (ADR-058: phase=pilot filtered)
    exp_pk = f"USER#{USER_ID}#SOURCE#experiments"
    exp_resp = table.query(**with_phase_filter({"KeyConditionExpression": Key("pk").eq(exp_pk)}))
    experiments = [
        {"name": i.get("name", ""), "start": i.get("start_date", ""), "end": i.get("end_date"), "status": i.get("status", "active")}
        for i in _decimal_to_float(exp_resp.get("Items", []))
        if i.get("sk", "").startswith("EXP#")
    ]

    # Character level history (ADR-058: phase=pilot filtered)
    cs_pk = f"{USER_PREFIX}character_sheet"
    cs_resp = table.query(
        **with_phase_filter(
            {
                "KeyConditionExpression": Key("pk").eq(cs_pk) & Key("sk").begins_with("DATE#"),
                "ScanIndexForward": True,
            }
        )
    )
    level_events = []
    prev_level = 0
    for item in _decimal_to_float(cs_resp.get("Items", [])):
        lvl = int(float(item.get("character_level", 0)))
        if lvl > prev_level and prev_level > 0:
            level_events.append(
                {
                    "date": item.get("sk", "").replace("DATE#", ""),
                    "level": lvl,
                    "tier": item.get("character_tier", ""),
                }
            )
        prev_level = lvl

    return _ok(
        {
            "timeline": {
                "weights": weights,
                "life_events": sorted(life_events, key=lambda x: x["date"]),
                "experiments": sorted(experiments, key=lambda x: x["start"]),
                "level_ups": level_events,
                "journey_start": EXPERIMENT_START,
                "start_weight": float(_get_profile().get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS)),
                "goal_weight": float(_get_profile().get("goal_weight_lbs", 185.0)),
            }
        },
        cache_seconds=3600,
    )


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
    start_date = _clamp_today(EXPERIMENT_START)  # future-genesis guard: keep sk.between(lower<=upper) valid
    _p = _get_profile()
    start_weight = float(_p.get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS))
    goal_weight = float(_p.get("goal_weight_lbs", 185.0))

    events: list = []

    # ── 1. Day 1 anchor (ADR-058: copy rewritten in §8 with Elena voice) ─────
    events.append(
        {
            "date": start_date,
            "type": "milestone",
            "title": "Day 1",
            "body": f"Starting weight: {int(round(EXPERIMENT_BASELINE_WEIGHT_LBS))} lbs. Goal: 185.",
            "link": "/story/",
        }
    )

    # ── 2. Weight milestones (5-lb thresholds) ───────────────────────────────
    thresholds = list(range(295, int(goal_weight) - 1, -5))  # 295, 290, 285, …, 190, 185
    crossed: dict = {}  # threshold -> date string

    wk_pk = f"{USER_PREFIX}withings"
    try:
        wk_resp = table.query(
            KeyConditionExpression=Key("pk").eq(wk_pk) & Key("sk").between(f"DATE#{start_date}", f"DATE#{today}"),
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
        events.append(
            {
                "date": crossed[thr],
                "type": "weight",
                "title": f"Crossed {thr} lbs — {int(lbs_lost)} lbs lost",
                "body": f"Down {int(lbs_lost)} lbs from {int(round(start_weight))}. {round((lbs_lost / (start_weight - goal_weight)) * 100)}% of the way to goal.",
                "link": "/live/",
            }
        )

    # ── 3. Level-up events from character_sheet ──────────────────────────────
    cs_pk = f"{USER_PREFIX}character_sheet"
    try:
        cs_resp = table.query(
            KeyConditionExpression=Key("pk").eq(cs_pk) & Key("sk").between(f"DATE#{start_date}", f"DATE#{today}"),
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
                            top_pillars.append(((p or "").capitalize(), float(pd["raw_score"])))
                    top_pillars.sort(key=lambda x: -x[1])
                    drivers = ", ".join(f"{n} ({s:.0f})" for n, s in top_pillars[:3])
                    events.append(
                        {
                            "date": date_str,
                            "type": "level_up",
                            "title": f"Reached Character Level {int(level)}",
                            "body": f"Driven by: {drivers}" if drivers else f"Level {int(level)} — {item.get('character_tier', '')}",
                            "link": "/character/",
                        }
                    )
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
                events.append(
                    {
                        "date": start,
                        "type": "experiment",
                        "title": f"Experiment: {item.get('name', 'Unnamed')}",
                        "body": item.get("hypothesis", "")[:120] + ("…" if len(item.get("hypothesis", "")) > 120 else ""),
                        "link": "/experiments/",
                    }
                )
            elif status == "completed":
                end = item.get("end_date", start)
                outcome = (item.get("outcome") or item.get("result_summary") or "")[:80]
                events.append(
                    {
                        "date": end,
                        "type": "discovery",
                        "title": f"Experiment Complete: {item.get('name', 'Unnamed')}",
                        "body": outcome + ("…" if len(outcome) == 80 else ""),
                        "link": "/discoveries/",
                    }
                )
    except Exception:
        pass

    # ── 5. FDR-significant correlation findings ────────────────────────
    corr_pk = f"{USER_PREFIX}weekly_correlations"
    try:
        corr_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot correlations
                    "KeyConditionExpression": Key("pk").eq(corr_pk),
                    "ScanIndexForward": True,
                }
            )
        )
        _METRIC_LABELS = {
            "hrv": "Heart Rate Variability",
            "recovery_score": "Recovery Score",
            "sleep_duration": "Sleep Duration",
            "sleep_score": "Sleep Score",
            "resting_hr": "Resting Heart Rate",
            "strain": "Strain",
            "tsb": "Training Stress Balance",
            "training_kj": "Training Load",
            "training_mins": "Training Minutes",
            "protein_g": "Protein",
            "calories": "Calories",
            "carbs_g": "Carbs",
            "steps": "Steps",
            "habit_pct": "Habit Completion",
            "day_grade": "Day Grade",
            "readiness": "Readiness",
            "tier0_streak": "Tier 0 Streak",
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
                events.append(
                    {
                        "date": end_d or week,
                        "type": evt_type,
                        "title": f"{title_prefix}{la} → {direction} {lb}",
                        "body": f"r={r_val:+.2f} over {n_val} days. Passed FDR significance testing (week {week}).",
                        "link": "/explorer/",
                        "meta": {"r": r_val, "n": n_val, "pair": label, "week": week},
                    }
                )
    except Exception as e:
        logger.warning("journey_timeline: correlation events failed (non-fatal): %s", e)

    # Exclude pre-experiment events and sort chronologically
    events = [evt for evt in events if evt["date"] >= start_date]
    events.sort(key=lambda evt: evt["date"])
    seen_evt: set = set()
    deduped = []
    for evt in events:
        key = (evt["date"], evt["title"])
        if key not in seen_evt:
            seen_evt.add(key)
            deduped.append(evt)

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
            for evt in deduped:
                ek = hashlib.sha256(f"{evt['date']}|{evt['type']}|{evt['title']}".encode()).hexdigest()[:16]
                if ek in ann_lookup:
                    evt["annotation"] = ann_lookup[ek]
    except Exception as _ann_e:
        logger.warning("journey_timeline: annotation merge failed (non-fatal): %s", _ann_e)

    return _ok(
        {
            "as_of_date": today,
            "events": deduped,
            "total": len(deduped),
        },
        cache_seconds=3600,
    )


def handle_journey_waveform() -> dict:
    """
    GET /api/journey_waveform
    Returns the daily pillar-sum scores for the Story/Home emotional waveform.
    Window = the experiment so far (genesis → today, in experiment TZ), so the
    "shape of it" matches the day-counter instead of a fixed 42-day box that
    bleeds into pre-genesis/empty days. Capped at 365 days for older cycles.
    Score = sum of 7 pillar level_scores (0–700 range).
    Color tiers: green (>=250), amber (>=150), red (<150), gray (no data).
    Cache: 3600s (1 hr).
    """
    today = datetime.now(PT).date()
    genesis = date.fromisoformat(EXPERIMENT_START)

    # PRE-START (#948): day_n clamps to 0 — matching handle_journey — so the
    # front-end #931 gates ("day 1 of the experiment", "1 day · the shape of it")
    # stay quiet until genesis instead of painting a Day-1 figure over an empty
    # strip at T−1. No fabricated single-day series. Inert once genesis <= today.
    _pre = pre_start_meta()
    if _pre:
        return _ok(
            {"days": [], "max_score": 1, "window": 0, "day_n": 0, "week_n": 0, "genesis": EXPERIMENT_START, **_pre},
            cache_seconds=3600,
        )

    day_count = max((today - genesis).days + 1, 1)  # 1-indexed Day-N
    window = min(day_count, 365)
    start = today - timedelta(days=window - 1)
    start_date = start.isoformat()
    end_date = today.isoformat()

    PILLARS = [
        "pillar_sleep",
        "pillar_nutrition",
        "pillar_movement",
        "pillar_metabolic",
        "pillar_mind",
        "pillar_consistency",
        "pillar_relationships",
    ]

    cs_pk = f"{USER_PREFIX}character_sheet"
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(cs_pk) & Key("sk").between(f"DATE#{start_date}", f"DATE#{end_date}"),
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

    # Build ordered genesis→today series (one point per experiment day)
    days = []
    for i in range(window):
        d = (today - timedelta(days=window - 1 - i)).isoformat()
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

    return _ok(
        {
            "days": days,
            "max_score": max_score,
            "window": window,
            "day_n": day_count,
            "week_n": ((day_count - 1) // 7) + 1,
            "genesis": EXPERIMENT_START,
            "pre_start": False,
        },
        cache_seconds=3600,
    )


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
        **with_phase_filter(
            {  # ADR-058: hide pilot habit scores
                "KeyConditionExpression": Key("pk").eq(habit_pk),
                "ScanIndexForward": False,
                "Limit": 1,
            }
        )
    )
    habit_items = _decimal_to_float(habit_resp.get("Items", []))
    latest_habit = habit_items[0] if habit_items else {}
    current_streak = int(latest_habit.get("t0_perfect_streak") or latest_habit.get("t0_aggregate_streak") or 0)

    # Days tracked = count of habit_score records in last 365 days
    all_habits_resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot habit scores
                "KeyConditionExpression": Key("pk").eq(habit_pk) & Key("sk").between(f"DATE#{d365}", f"DATE#{today}"),
            }
        )
    )
    days_tracked = len(all_habits_resp.get("Items", []))

    # ── Character level
    char_pk = f"{USER_PREFIX}character_sheet"
    char_resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot character sheets
                "KeyConditionExpression": Key("pk").eq(char_pk),
                "ScanIndexForward": False,
                "Limit": 1,
            }
        )
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
        **with_phase_filter(
            {  # ADR-058: hide pilot experiments
                "KeyConditionExpression": Key("pk").eq(exp_pk),
                "ScanIndexForward": False,
                "Limit": 50,
            }
        )
    )
    all_exps = [i for i in _decimal_to_float(exp_resp.get("Items", [])) if i.get("sk", "").startswith("EXP#")]
    completed_exps = [i for i in all_exps if i.get("status") in ("completed", "confirmed")]

    # EL-21: Streak detection — last 3 finished experiments all completed (no abandoned/failed)
    _exp_has_3_streak = False
    finished = sorted(
        [i for i in all_exps if i.get("status") in ("completed", "confirmed", "abandoned")],
        key=lambda x: x.get("end_date") or x.get("start_date", ""),
        reverse=True,
    )
    if len(finished) >= 3:
        _exp_has_3_streak = all(e.get("status") in ("completed", "confirmed") for e in finished[:3])

    # EL-21: Pillar coverage — completed experiment in each of 7 pillars
    _ALL_PILLARS = {"sleep", "movement", "nutrition", "supplements", "mental", "social", "discipline"}
    _covered_pillars = set()
    for e in completed_exps:
        for tag in e.get("tags") or []:
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
            **with_phase_filter(
                {  # ADR-058: hide pilot challenges
                    "KeyConditionExpression": Key("pk").eq(challenges_pk) & Key("sk").begins_with("CHALLENGE#"),
                }
            )
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
            "id": id_,
            "label": label,
            "category": category,
            "description": desc,
            "earned": earned,
            "earned_date": earned_date,
            "icon": icon,
            "unlock_hint": unlock_hint,
        }

    achievements = [
        # ── Streak
        badge(
            "week_warrior",
            "Week Warrior",
            "streak",
            "7-day Tier 0 habit streak",
            earned=current_streak >= 7,
            earned_date=today if current_streak >= 7 else None,
            unlock_hint=f"{max(0, 7 - current_streak)} days to unlock" if current_streak < 7 else None,
        ),
        badge(
            "monthly_grind",
            "Monthly Grind",
            "streak",
            "30-day Tier 0 habit streak",
            earned=current_streak >= 30,
            earned_date=today if current_streak >= 30 else None,
            unlock_hint=f"{max(0, 30 - current_streak)} days to unlock" if current_streak < 30 else None,
        ),
        badge(
            "quarterly",
            "Quarterly",
            "streak",
            "90-day Tier 0 habit streak",
            earned=current_streak >= 90,
            unlock_hint=f"{max(0, 90 - current_streak)} days to unlock" if current_streak < 90 else None,
        ),
        # ── Level
        badge(
            "first_level_up",
            "First Level Up",
            "level",
            "Reached Character Level 2",
            earned=current_level >= 2,
            earned_date=today if current_level >= 2 else None,
        ),
        badge(
            "apprentice",
            "Apprentice",
            "level",
            "Reached Character Level 5",
            earned=current_level >= 5,
            unlock_hint=f"Level {current_level} → Level 5 needed" if current_level < 5 else None,
        ),
        badge(
            "journeyman",
            "Journeyman",
            "level",
            "Reached Character Level 10",
            earned=current_level >= 10,
            unlock_hint=f"Level {current_level} → Level 10 needed" if current_level < 10 else None,
        ),
        # ── Weight LOSS milestones (every 10 lbs)
        badge(
            "lost_10",
            "Lost 10 lbs",
            "milestone",
            "Lost 10 lbs from starting weight",
            earned=lost_lbs >= 10,
            icon="\u2696\ufe0f",
            unlock_hint=f"{10 - lost_lbs:.0f} lbs to go" if lost_lbs < 10 else None,
        ),
        badge(
            "lost_20",
            "Lost 20 lbs",
            "milestone",
            "Lost 20 lbs from starting weight",
            earned=lost_lbs >= 20,
            icon="\u2696\ufe0f",
            unlock_hint=f"{20 - lost_lbs:.0f} lbs to go" if lost_lbs < 20 else None,
        ),
        badge(
            "lost_30",
            "Lost 30 lbs",
            "milestone",
            "Lost 30 lbs from starting weight",
            earned=lost_lbs >= 30,
            icon="\u2696\ufe0f",
            unlock_hint=f"{30 - lost_lbs:.0f} lbs to go" if lost_lbs < 30 else None,
        ),
        badge(
            "lost_40",
            "Lost 40 lbs",
            "milestone",
            "Lost 40 lbs from starting weight",
            earned=lost_lbs >= 40,
            icon="\u2696\ufe0f",
            unlock_hint=f"{40 - lost_lbs:.0f} lbs to go" if lost_lbs < 40 else None,
        ),
        badge(
            "lost_50",
            "Lost 50 lbs",
            "milestone",
            "Lost 50 lbs from starting weight",
            earned=lost_lbs >= 50,
            icon="\u2696\ufe0f",
            unlock_hint=f"{50 - lost_lbs:.0f} lbs to go" if lost_lbs < 50 else None,
        ),
        badge(
            "lost_60",
            "Lost 60 lbs",
            "milestone",
            "Lost 60 lbs from starting weight",
            earned=lost_lbs >= 60,
            icon="\u2696\ufe0f",
            unlock_hint=f"{60 - lost_lbs:.0f} lbs to go" if lost_lbs < 60 else None,
        ),
        badge(
            "lost_70",
            "Lost 70 lbs",
            "milestone",
            "Lost 70 lbs from starting weight",
            earned=lost_lbs >= 70,
            icon="\u2696\ufe0f",
            unlock_hint=f"{70 - lost_lbs:.0f} lbs to go" if lost_lbs < 70 else None,
        ),
        badge(
            "lost_80",
            "Lost 80 lbs",
            "milestone",
            "Lost 80 lbs from starting weight",
            earned=lost_lbs >= 80,
            icon="\u2696\ufe0f",
            unlock_hint=f"{80 - lost_lbs:.0f} lbs to go" if lost_lbs < 80 else None,
        ),
        badge(
            "lost_90",
            "Lost 90 lbs",
            "milestone",
            "Lost 90 lbs from starting weight",
            earned=lost_lbs >= 90,
            icon="\u2696\ufe0f",
            unlock_hint=f"{90 - lost_lbs:.0f} lbs to go" if lost_lbs < 90 else None,
        ),
        badge(
            "lost_100",
            "Lost 100 lbs",
            "milestone",
            "Lost 100 lbs from starting weight",
            earned=lost_lbs >= 100,
            icon="\u2696\ufe0f",
            unlock_hint=f"{100 - lost_lbs:.0f} lbs to go" if lost_lbs < 100 else None,
        ),
        # ── Weight TARGET milestones
        badge(
            "sub_280",
            "Sub-280",
            "milestone",
            "Weight under 280 lbs",
            earned=current_weight < 280,
            icon="\ud83c\udfaf",
            unlock_hint=f"{current_weight - 280:.0f} lbs to go" if current_weight >= 280 else None,
        ),
        badge(
            "sub_250",
            "Sub-250",
            "milestone",
            "Weight under 250 lbs",
            earned=current_weight < 250,
            icon="\ud83c\udfaf",
            unlock_hint=f"{current_weight - 250:.0f} lbs to go" if current_weight >= 250 else None,
        ),
        badge(
            "sub_220",
            "Sub-220",
            "milestone",
            "Weight under 220 lbs",
            earned=current_weight < 220,
            icon="\ud83c\udfaf",
            unlock_hint=f"{current_weight - 220:.0f} lbs to go" if current_weight >= 220 else None,
        ),
        badge(
            "sub_200",
            "Sub-200",
            "milestone",
            "Weight under 200 lbs",
            earned=current_weight < 200,
            icon="\ud83c\udfaf",
            unlock_hint=f"{current_weight - 200:.0f} lbs to go" if current_weight >= 200 else None,
        ),
        # ── Data
        badge(
            "100_days",
            "100 Days Tracked",
            "data",
            "100+ days of habit logging",
            earned=days_tracked >= 100,
            earned_date=today if days_tracked >= 100 else None,
            unlock_hint=f"{max(0, 100 - days_tracked)} days to unlock" if days_tracked < 100 else None,
        ),
        badge(
            "365_days",
            "Year of Data",
            "data",
            "365 days of habit logging",
            earned=days_tracked >= 365,
            unlock_hint=f"{max(0, 365 - days_tracked)} days to unlock" if days_tracked < 365 else None,
        ),
        # ── Experiment
        badge(
            "first_experiment",
            "First Experiment",
            "science",
            "Completed first N=1 experiment",
            earned=len(completed_exps) >= 1,
            earned_date=today if completed_exps else None,
        ),
        badge(
            "hypothesis_confirmed",
            "Hypothesis Confirmed",
            "science",
            "N=1 result statistically validated",
            earned=False,  # requires manual confirmation
            unlock_hint="Complete a tracked experiment to unlock",
        ),
        # EL-21: Experiment evolution badges
        badge(
            "exp_3_completed",
            "Lab Rat",
            "science",
            "Completed 3 experiments",
            earned=len(completed_exps) >= 3,
            earned_date=today if len(completed_exps) >= 3 else None,
            unlock_hint=f"{max(0, 3 - len(completed_exps))} experiments to unlock" if len(completed_exps) < 3 else None,
        ),
        badge(
            "exp_5_completed",
            "Research Fellow",
            "science",
            "Completed 5 experiments",
            earned=len(completed_exps) >= 5,
            earned_date=today if len(completed_exps) >= 5 else None,
            unlock_hint=f"{max(0, 5 - len(completed_exps))} experiments to unlock" if len(completed_exps) < 5 else None,
        ),
        badge(
            "exp_10_completed",
            "Principal Investigator",
            "science",
            "Completed 10 experiments",
            earned=len(completed_exps) >= 10,
            unlock_hint=f"{max(0, 10 - len(completed_exps))} experiments to unlock" if len(completed_exps) < 10 else None,
        ),
        badge(
            "exp_streak_3",
            "Hot Streak",
            "science",
            "3 consecutive completed experiments (no fails)",
            earned=_exp_has_3_streak,
            unlock_hint="Complete 3 experiments in a row without abandoning",
        ),
        badge(
            "exp_all_pillars",
            "Renaissance Man",
            "science",
            "Completed experiment in every pillar",
            earned=_exp_all_pillars_covered,
            unlock_hint="Complete at least one experiment in each of the 7 pillars",
        ),
        # ── Challenges
        badge(
            "first_challenge",
            "First Challenge",
            "challenge",
            "Completed first challenge",
            earned=completed_challenges >= 1,
            earned_date=today if completed_challenges >= 1 else None,
        ),
        badge(
            "five_challenges",
            "Challenge Regular",
            "challenge",
            "Completed 5 challenges",
            earned=completed_challenges >= 5,
            unlock_hint=f"{max(0, 5 - completed_challenges)} challenges to unlock" if completed_challenges < 5 else None,
        ),
        badge(
            "ten_challenges",
            "Challenge Veteran",
            "challenge",
            "Completed 10 challenges",
            earned=completed_challenges >= 10,
            unlock_hint=f"{max(0, 10 - completed_challenges)} challenges to unlock" if completed_challenges < 10 else None,
        ),
        badge(
            "twenty_five_challenges",
            "Challenge Legend",
            "challenge",
            "Completed 25 challenges",
            earned=completed_challenges >= 25,
            unlock_hint=f"{max(0, 25 - completed_challenges)} challenges to unlock" if completed_challenges < 25 else None,
        ),
        badge(
            "perfect_challenge",
            "Flawless",
            "challenge",
            "Completed a challenge with 100% success rate (7+ days)",
            earned=perfect_challenges >= 1,
            unlock_hint="Complete a 7+ day challenge without missing a single day",
        ),
    ]

    earned_count = sum(1 for a in achievements if a["earned"])

    return _ok(
        {
            "achievements": achievements,
            "summary": {
                "earned": earned_count,
                "total": len(achievements),
                "current_streak": current_streak,
                "days_tracked": days_tracked,
                "current_level": current_level,
                "current_weight": round(current_weight),
                "completed_challenges": completed_challenges,
                "perfect_challenges": perfect_challenges,
            },
        },
        cache_seconds=3600,
    )


def _latest_readiness() -> dict | None:
    """RQA-04 — the pre-computed readiness score + component breakdown from computed_metrics
    (written by daily-metrics-compute). Surfaced read-only so the Cockpit shows the STORED
    score + its components, not just a band re-derived from raw vitals. None if not computed."""
    rec = _latest_item("computed_metrics")
    if not rec or rec.get("readiness_score") is None:
        return None
    # #492/M-4: serve the score's ACTUAL inputs (stored as readiness_components
    # by daily-metrics-compute). The old fallback borrowed the day-grade
    # component set — a different model — so when the breakdown is absent
    # (pre-#492 records) we serve none rather than the wrong ones.
    # #490/M-3: the TSB component names its provenance — the load behind it is a
    # duration proxy unless the basis says power-backed.
    _tsb_conf = str((rec.get("tsb_load_basis") or {}).get("confidence") or "")
    _tsb_label = "training balance" + (" (duration-proxy)" if _tsb_conf and _tsb_conf != "power" else "")
    label_map = {"recovery": "recovery", "sleep": "sleep", "hrv_trend": "HRV trend", "tsb": _tsb_label}
    components = [
        {"key": c.get("key"), "label": label_map.get(c.get("key"), c.get("key")), "score": round(float(c["score"]), 1)}
        for c in (rec.get("readiness_components") or [])
        if c.get("score") is not None
    ]
    return {
        "score": round(float(rec["readiness_score"]), 1),
        "band": rec.get("readiness_colour"),  # green / yellow / red
        "components": components,
        "tsb_basis": _tsb_conf or None,
        "as_of": (rec.get("sk", "") or "").replace("DATE#", "") or rec.get("date"),
    }


def handle_snapshot() -> dict:
    """
    GET /api/snapshot
    Combined response: vitals + journey + character (+ readiness) in one call.
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

    try:
        readiness_body = _latest_readiness()
    except Exception as _e:
        logger.warning("[snapshot] readiness failed: %s", _e)
        readiness_body = None

    payload = {
        "vitals": vitals_body,
        "journey": journey_body,
        "character": character_body,
        "readiness": readiness_body,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    # PRE-START (#931): the countdown contract at the snapshot's top level too, so
    # the cockpit doesn't have to dig through a possibly-failed journey sub-object.
    _pre = pre_start_meta()
    payload["pre_start"] = bool(_pre)
    if _pre:
        payload.update(_pre)
    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "public, max-age=60"},
        "body": json.dumps(payload, default=str),
    }
