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
import re as _re  # #1240: genetic-biomarker strip regexes (handle_labs)
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal  # noqa: F401
from typing import Any

import achievement_rules  # #1624: the ONE place badge thresholds live (shared with daily-metrics-compute)
import boto3  # #1240: S3/DDB clients used by handle_labs / handle_glucose / handle_genome_risks
import weight_trend  # shared weekly-rate + projection (layer module)
from boto3.dynamodb.conditions import Key
from phase_filter import with_phase_filter  # ADR-058 — used by handle_timeline

from web import vitals_resolver  # #1369: the ONE current-vitals truth
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
    _experiment_date,
    _get_profile,
    _latest_item,
    _latest_item_asof,
    _ok,
    _query_source,
    logger,
    pre_start_meta,
    table,
)

# #1084 / ADR-105: a "30d average" fabricated from one or two readings is not an
# average. Below this floor the avg field reads None (its n is surfaced alongside)
# and front-ends self-hide on null.
_MIN_AVG_N = 3


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
    if not ip:
        # #1084 / ADR-077 "clamped, not hidden": LIVE trailing windows never reach
        # across genesis into prior-cycle rows — at a reset the window shrinks
        # honestly instead. (The phase filter hides *tagged* pilot rows, but rows
        # ingested between reset-tagging and genesis carry no tag; the date clamp
        # is deterministic either way.) Time-travel (?date=) keeps the full reach —
        # include_pilot=True is the deliberate ADR-058 contract there. A staged
        # FUTURE genesis makes start > end, which _query_source treats as "no data
        # yet" ([]), so this can never 500.
        d30 = max(d30, EXPERIMENT_START)
        d7 = max(d7, EXPERIMENT_START)

    # Whoop (recovery, HRV, RHR, sleep)
    whoop_7d = _query_source("whoop", d7, today, include_pilot=ip)
    whoop_30d = _query_source("whoop", d30, today, include_pilot=ip)

    # Latest reading — LIVE reads come from the ONE canonical resolver (#1369),
    # so /api/vitals, /api/snapshot, /api/pulse and the public_stats writers can
    # never disagree about the same morning's numbers. Time-travel (?date=) keeps
    # the as-of-anchor window semantics, with the same honest-null shape.
    if date:
        _lt = sorted([w for w in whoop_7d if w.get("recovery_score") is not None], key=lambda x: x.get("sk", ""), reverse=True)
        _lt = _lt[0] if _lt else {}
        _lt_sk = _lt.get("sk", "").replace("DATE#", "")[:10] or None
        _vr = {
            "recovery_pct": float(_lt["recovery_score"]) if _lt.get("recovery_score") else None,
            "hrv_ms": float(_lt["hrv"]) if _lt.get("hrv") else None,
            "rhr_bpm": float(_lt["resting_heart_rate"]) if _lt.get("resting_heart_rate") else None,
            "sleep_hours": float(_lt["sleep_duration_hours"]) if _lt.get("sleep_duration_hours") else None,
            "recovery_as_of": _lt_sk,
            "sleep_as_of": _lt_sk,
        }
        _vr["recovery_status"] = vitals_resolver.recovery_status(_vr["recovery_pct"])
    else:
        _vr = vitals_resolver.resolve_vitals(table, USER_PREFIX)

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
        if not ip:
            _ah_start = max(_ah_start, EXPERIMENT_START)  # #1084: same live genesis clamp as d7/d30
        _ah_7d = _query_source("apple_health", _ah_start, today, include_pilot=ip)
    except Exception:
        _ah_7d = []
    _lw = weight_trend.latest_weight([withings_latest] if withings_latest else [], _ah_7d)
    current_weight = _lw["weight_lbs"]
    weight_as_of = _lw["as_of"]

    withings_30d = _query_source("withings", d30, today, include_pilot=ip)
    weight_vals = [float(w["weight_lbs"]) for w in withings_30d if w.get("weight_lbs")]
    weight_delta_30d = round(weight_vals[-1] - weight_vals[0], 1) if len(weight_vals) >= 2 else None

    # DPR-1.20: Page freshness for nav badges
    _today_iso = datetime.now(timezone.utc).isoformat()
    _as_of = _vr.get("recovery_as_of") or _vr.get("sleep_as_of") or today
    # Temporal frame: sleep/recovery/HRV/RHR are wake-date-keyed (stored under the
    # morning they set up). The reading came from the night BEFORE that morning, so
    # night_of = as_of - 1 day. Surfacing this lets the front-end say "the night of
    # <night_of>" precisely, even when the latest record lags a day or two. (Weight,
    # by contrast, is same-day "today" — see weight_as_of.)
    _night_of = None
    try:
        _night_of = (datetime.strptime(_as_of[:10], "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")  # type: ignore[index]  # _as_of is a str date in practice; the float branch of its inferred union never occurs and is guarded by this try/except
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
                "hrv_ms": round(_vr["hrv_ms"], 1) if _vr["hrv_ms"] is not None else None,
                # #1084 / ADR-105: the claim carries its n — below _MIN_AVG_N the
                # "30d avg" is None (a 1-2 reading mean isn't an average), and
                # hrv_30d_n says how much data backs the number when it shows.
                "hrv_30d_avg": round(sum(hrv_vals) / len(hrv_vals), 1) if len(hrv_vals) >= _MIN_AVG_N else None,
                "hrv_30d_n": len(hrv_vals),
                "hrv_trend": trend(hrv_vals),
                "rhr_bpm": round(_vr["rhr_bpm"], 0) if _vr["rhr_bpm"] is not None else None,
                "rhr_trend": trend(list(reversed(rhr_vals))),  # lower is better
                # #1369 honest absence: no reading ⇒ null % AND null status —
                # never the old 0.0/"red" fabrication on an empty window.
                "recovery_pct": round(_vr["recovery_pct"], 0) if _vr["recovery_pct"] is not None else None,
                "recovery_status": _vr["recovery_status"],
                "sleep_hours": round(_vr["sleep_hours"], 1) if _vr["sleep_hours"] is not None else None,
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
    # #1225 display policy: the reader sees weights rounded to ONE decimal, and every
    # delta is derived from those SAME displayed values — so displayed_now − displayed_start
    # == displayed_delta exactly. The old code rounded the displayed weight to an int (316)
    # while computing lost_lbs off the raw 315.6, so the hero stat row failed mental
    # arithmetic ("316 at last weigh-in · start 314 · 1.6 up" — 316 − 314 = 2 ≠ 1.6).
    current_weight_disp = round(current_weight, 1)
    start_weight_disp = round(start_weight, 1)
    goal_weight_disp = round(goal_weight, 1)
    lost_lbs = round(start_weight_disp - current_weight_disp, 1)
    remaining = round(current_weight_disp - goal_weight_disp, 1)
    progress_pct = round(lost_lbs / (start_weight_disp - goal_weight_disp) * 100, 1) if start_weight_disp != goal_weight_disp else 0

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
        "start_weight_lbs": start_weight_disp,
        "goal_weight_lbs": goal_weight_disp,
        "current_weight_lbs": current_weight_disp,
        "lost_lbs": lost_lbs,
        "remaining_lbs": remaining,
        "progress_pct": progress_pct,
        # #1225: the weigh-in count so the front-end can gate any "in N days" TREND copy
        # on >= 2 weigh-ins (a single Day-1 reading is not a multi-day trend — ADR-105).
        "weighin_count": len(weight_series),
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
                # #1411 (ADR-105): the fit badge rides along — fitted (n_eff + CI)
                # or "authored prior — not yet confirmed". Pre-#1411 records carry
                # no fit fields; the honest default is the authored prior.
                "active_effects": [
                    {
                        "name": e.get("name"),
                        "emoji": e.get("emoji", ""),
                        "condition": e.get("condition", ""),
                        "targets": e.get("targets", {}),
                        "fit_status": e.get("fit_status", "authored-prior"),
                        "fit_n_eff": e.get("fit_n_eff"),
                        "fit_ci_95": e.get("fit_ci_95"),
                        "fit_badge": e.get("fit_badge") or "authored prior — not yet confirmed (n_eff=0)",
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

    # #1412 (ADR-105 rule 4): serve the EFFECTIVE targets — personal-variance
    # derived where the floor cleared, authored + "population prior, n<30"
    # labeled where not — with per-target provenance {method, window, n}.
    try:
        import personal_baselines as _pb

        cfg = _pb.effective_character_config(cfg, table, USER_PREFIX)
    except Exception as e:
        logger.warning("character_config: baselines overlay failed (authored config served): %s", e)

    def _scalars(o: dict) -> dict:
        return {k: v for k, v in (o or {}).items() if isinstance(v, (int, float, str, bool))}

    def _component_out(cv: dict) -> dict:
        out = _scalars(cv)
        if isinstance((cv or {}).get("target_provenance"), dict):
            out["target_provenance"] = cv["target_provenance"]
        return out

    pillars_out = {}
    for name, p in (cfg.get("pillars") or {}).items():
        pillars_out[name] = {
            "weight": p.get("weight"),
            "ema_lambda": p.get("ema_lambda"),
            "components": {cn: _component_out(cv) for cn, cv in (p.get("components") or {}).items()},
        }
    leveling = {k: v for k, v in (cfg.get("leveling") or {}).items() if k in _CHAR_CONFIG_LEVELING_KEYS}
    tiers = [{"name": t.get("name"), "min_level": t.get("min_level"), "max_level": t.get("max_level")} for t in cfg.get("tiers") or []]
    # #1411 (ADR-105): merge the latest quarterly effect fit so the sheet's
    # mechanics panel wears the earned badge — fitted (n_eff + CI) or "authored
    # prior — not yet confirmed". Fail-open to the declared authored default
    # (the merge itself can never invent "fitted": that only comes from a
    # stored fit record). Keys stay explicitly whitelisted.
    try:
        import effect_fitter

        effect_fitter.merge_fit_into_config(cfg, effect_fitter.load_latest_fit(table, USER_ID))
    except Exception as e:
        logger.warning("character_config: effect fit merge failed: %s", e)
    effects = [
        {
            "name": e.get("name"),
            "condition": e.get("condition"),
            "targets": e.get("targets"),
            "fit_status": e.get("fit_status", "authored-prior"),
            "fit_n_eff": e.get("fit_n_eff"),
            "fit_ci_95": e.get("fit_ci_95"),
            "fit_r": e.get("fit_r"),
            "fit_badge": e.get("fit_badge") or "authored prior — not yet confirmed (n_eff=0)",
            "fitted_at": e.get("fitted_at"),
        }
        for e in cfg.get("cross_pillar_effects") or []
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


def handle_character_receipt(date: str | None = None, verify: bool = False) -> dict:
    """
    GET /api/character_receipt[?date=YYYY-MM-DD][&verify=1]
    The audit-grade progression receipt for a compute day (#1373): contributing
    input-row KEYS, engine formula version, config hash, per-pillar transition
    inputs/outputs, and the deterministic replay digest. Read-only.

    verify=1 replays the stored inputs server-side through the LIVE engine +
    config (the same bundled character_engine the nightly compute runs) and
    returns the provenance-labeled verdict — digest_match / config_drift /
    engine_drift / field-level mismatches.

    ADR-104: a date with no stored receipt answers available=false — receipts
    are never fabricated for changes that predate the receipt system. Dated
    reads include archived (prior-cycle) receipts deliberately, like
    /api/character?date= — history is cross-cycle and the receipt's own
    phase/cycle stamps ride along as provenance.
    Cache: 900s latest / 86400s dated (the past is immutable).
    """
    if date and not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return _error(400, "date must be YYYY-MM-DD")
    pk = f"{USER_PREFIX}character_receipt"
    if date:
        resp = table.get_item(Key={"pk": pk, "sk": f"DATE#{date}"})
        item = resp.get("Item")
    else:
        resp = table.query(
            **with_phase_filter(
                {  # latest CURRENT-cycle receipt (ADR-058 — archived ones need ?date=)
                    "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("DATE#"),
                    "ScanIndexForward": False,
                    "Limit": 1,
                }
            )
        )
        items = resp.get("Items", [])
        item = items[0] if items else None
    cache_s = 86400 if date else 900
    if not item:
        return _ok(
            {
                "available": False,
                "date": date,
                "reason": "no progression receipt recorded for this date — receipts began with #1373; earlier changes have no recorded inputs and are never back-fabricated (ADR-104)",
            },
            cache_seconds=cache_s,
        )

    receipt = _decimal_to_float({k: v for k, v in item.items() if k not in ("pk", "sk")})
    body = {"available": True, "receipt": receipt, "replay": None}
    if verify:
        try:
            import boto3 as _boto3
            import character_engine as _ce
            import progression_receipts as _pr

            bucket = os.environ.get("S3_BUCKET", "matthew-life-platform")
            s3 = _boto3.client("s3", region_name=S3_REGION)
            cfg = json.loads(s3.get_object(Bucket=bucket, Key=f"config/{USER_ID}/character_sheet.json")["Body"].read())
            # #1412: verify against the SAME effective config the compute hashed
            # into the receipt (personal-variance targets overlaid).
            import personal_baselines as _pb

            cfg = _pb.effective_character_config(cfg, table, USER_PREFIX)
            body["replay"] = _pr.replay(item, cfg, engine=_ce)
        except Exception as e:  # verify is best-effort; the receipt itself still serves
            logger.warning("character_receipt: replay failed: %s", e)
            body["replay"] = {"available": False, "reason": "replay unavailable (config load or engine error)"}
        cache_s = 900  # a verify verdict is against the LIVE config — never cache it a day
    return _ok(body, cache_seconds=cache_s)


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


def _persisted_level_up_drivers(item: dict, level) -> list:
    """#1125: drivers persisted at event-fire time by the character engine
    (engine >= 1.6.1 — the character_level_up entry in level_events carries a
    'drivers' list of {pillar, raw_score}). Returns [(Name, score), ...] for
    the matching level-up, or [] when the record predates persistence — the
    caller then falls back to the read-time enrichment (honest absence, never
    a fabricated "fired-with" attribution)."""
    for ev in item.get("level_events") or []:
        if not isinstance(ev, dict) or ev.get("type") != "character_level_up":
            continue
        try:
            if int(float(ev.get("new_level", 0) or 0)) != int(float(level)):
                continue
        except (TypeError, ValueError):
            continue
        return [
            (str(d.get("pillar") or "").capitalize(), float(d["raw_score"]))
            for d in ev.get("drivers") or []
            if isinstance(d, dict) and d.get("raw_score") is not None
        ]
    return []


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
    # #1021: anchor at the TRUE genesis, never the clamped query bound. Pre-genesis
    # the clamp is today, which stamped launch eve ("2026-07-11 · Day 1") while the
    # hero counted down to tomorrow — the page contradicted itself. start_date stays
    # clamped ONLY for the sk.between(lower <= upper) query bounds below; once
    # genesis <= today the two are equal and nothing changes.
    events.append(
        {
            "date": EXPERIMENT_START,
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
                "body": (
                    f"Down {int(lbs_lost)} lbs from {int(round(start_weight))}. "
                    f"{round((lbs_lost / (start_weight - goal_weight)) * 100)}% of the way to goal."
                ),
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
                    # #1125: prefer the attribution the engine persisted at event
                    # fire time; the read-time reconstruction below stays as the
                    # fallback for records written before drivers were persisted.
                    top_pillars = _persisted_level_up_drivers(item, level)
                    if not top_pillars:
                        # Enrich with top-scoring pillars that drove the level-up
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

    # Exclude pre-experiment events and sort chronologically. #1021: the bar is the
    # TRUE genesis (pre-genesis the clamped start_date is today, which would admit
    # wiped-cycle events stamped launch eve); equal to start_date once genesis <= today.
    events = [evt for evt in events if evt["date"] >= EXPERIMENT_START]
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
    Serves earned/locked achievement badges.

    #1624: this used to compute a nightly threshold snapshot and present it as an
    earned-badge record — `earned_date=today if <condition> else None` for every
    badge, so no first-earn was ever recorded and a badge un-earned the moment a
    metric dipped back under its threshold (a 2-3 lb water swing was enough).

    The threshold logic now lives ONCE, in lambdas/achievement_rules.py, shared with
    daily-metrics-compute, which persists the durable first-earn record. This handler
    is READ-ONLY by design — /api/achievements is a core data query and per CLAUDE.md
    core data queries must never write, so there is deliberately no lazy-persist here.
    A badge that is true right now but not yet recorded serves earned with a NULL
    date; the date is never manufactured (ADR-104).

    Sources: habit_scores (streaks, days tracked), character_sheet (level),
             withings (weight milestones), experiments, challenges,
             achievements (BADGE#<id> — the first-earn ledger).
    Cache: 3600s (1 hr) — achievements update nightly.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d365 = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")

    start_weight = float(_get_profile().get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS))
    inputs = achievement_rules.collect_inputs(
        table, USER_PREFIX, with_phase_filter, start_weight_lbs=start_weight, today=today, window_start=d365
    )
    signals = achievement_rules.signals_from(_decimal_to_float(inputs))

    try:
        first_earns = achievement_rules.read_first_earns(table, USER_PREFIX, with_phase_filter)
    except Exception as _fe:  # noqa: BLE001 — a missing ledger must not 500 the surface
        logger.warning("[achievements] First-earn ledger read failed (serving live conditions only): %s", _fe)
        first_earns = {}

    achievements = achievement_rules.render(signals, first_earns)
    earned_count = sum(1 for a in achievements if a["earned"])

    return _ok(
        {
            "achievements": achievements,
            "summary": {
                "earned": earned_count,
                "total": len(achievements),
                "current_streak": signals["current_streak"],
                "days_tracked": signals["days_tracked"],
                "current_level": signals["current_level"],
                "current_weight": round(signals["current_weight"]),
                "completed_challenges": signals["completed_challenges"],
                "perfect_challenges": signals["perfect_challenges"],
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


# ════════════════════════════════════════════════════════════════════════
# #1240: vitals-adjacent domain handlers — moved verbatim from site_api_data.py
# (glucose / sleep / circadian / phenoage / labs / genome). Behavior-identical;
# the router (site_api_lambda.py) now imports these from here.
# ════════════════════════════════════════════════════════════════════════


def handle_genome_risks() -> dict:
    """
    GET /api/genome_risks
    Returns genome SNPs grouped by category with risk levels.
    No raw genotypes exposed. Cache: 86400s (24h).
    """
    pk = f"{USER_PREFIX}genome"
    resp = table.query(KeyConditionExpression=Key("pk").eq(pk))
    items = _decimal_to_float(resp.get("Items", []))

    if not items:
        # No genome uploaded yet — shaped-empty 200 so the page shows "not yet published".
        return _ok(
            {"genome": {"total_snps": 0, "risk_summary": {"unfavorable": 0, "mixed": 0, "neutral": 0, "favorable": 0}, "categories": {}}},
            cache_seconds=3600,
        )

    categories: dict[str, list[dict[str, Any]]] = {}
    risk_summary = {"unfavorable": 0, "mixed": 0, "neutral": 0, "favorable": 0}

    for snp in items:
        cat = snp.get("category", "other")
        risk = snp.get("risk_level", "neutral")
        risk_summary[risk] = risk_summary.get(risk, 0) + 1

        if cat not in categories:
            categories[cat] = []
        categories[cat].append(
            {
                "gene": snp.get("gene", ""),
                "rsid": snp.get("rsid", snp.get("sk", "").replace("SNP#", "")),
                "risk_level": risk,
                "summary": snp.get("summary", ""),
                "implications": snp.get("implications", ""),
                "interventions": snp.get("interventions", []),
                "evidence": snp.get("evidence_strength", "moderate"),
            }
        )

    for cat in categories:
        categories[cat].sort(key=lambda x: {"unfavorable": 0, "mixed": 1, "neutral": 2, "favorable": 3}.get(x["risk_level"], 2))

    return _ok(
        {
            "genome": {
                "total_snps": len(items),
                "risk_summary": risk_summary,
                "categories": categories,
            }
        },
        cache_seconds=86400,
    )


def handle_glucose() -> dict:
    """
    GET /api/glucose
    Returns: 30-day CGM stats — time-in-range, variability, daily trend.
    Source: apple_health DynamoDB records.
    Cache: 3600s (1h).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)

    records = _query_source("apple_health", d30, today)
    cgm_days = [r for r in records if r.get("blood_glucose_avg") is not None and r.get("sk", "").replace("DATE#", "") >= EXPERIMENT_START]
    cgm_days.sort(key=lambda x: x.get("sk", ""))

    if not cgm_days:
        return _ok({"glucose": None, "glucose_trend": []}, cache_seconds=3600)

    latest = cgm_days[-1]

    # 30-day averages
    avg_vals = [float(r["blood_glucose_avg"]) for r in cgm_days if r.get("blood_glucose_avg")]
    tir_vals = [float(r["blood_glucose_time_in_range_pct"]) for r in cgm_days if r.get("blood_glucose_time_in_range_pct")]
    opt_vals = [float(r["blood_glucose_time_in_optimal_pct"]) for r in cgm_days if r.get("blood_glucose_time_in_optimal_pct")]
    std_vals = [float(r["blood_glucose_std_dev"]) for r in cgm_days if r.get("blood_glucose_std_dev")]

    def avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    # Daily trend array for chart
    trend = [
        {
            "date": r.get("sk", "").replace("DATE#", ""),
            "avg": round(float(r["blood_glucose_avg"]), 1) if r.get("blood_glucose_avg") else None,
            "tir": round(float(r["blood_glucose_time_in_range_pct"]), 1) if r.get("blood_glucose_time_in_range_pct") else None,
            "std": round(float(r["blood_glucose_std_dev"]), 1) if r.get("blood_glucose_std_dev") else None,
        }
        for r in cgm_days
    ]

    tir_today = float(latest.get("blood_glucose_time_in_range_pct", 0))
    tir_status = "excellent" if tir_today >= 90 else ("good" if tir_today >= 70 else "needs_attention")
    std_today = float(latest.get("blood_glucose_std_dev", 99))
    variability_status = "low" if std_today < 15 else ("moderate" if std_today < 25 else "high")

    # Best/worst day by TIR (or avg glucose if all 100% TIR)
    best_day = None
    worst_day = None
    if len(cgm_days) >= 2:
        sorted_by_tir = sorted(
            cgm_days, key=lambda r: (float(r.get("blood_glucose_time_in_range_pct", 0)), -float(r.get("blood_glucose_std_dev", 99)))
        )
        worst_r = sorted_by_tir[0]
        best_r = sorted_by_tir[-1]
        worst_day = {
            "date": worst_r.get("sk", "").replace("DATE#", ""),
            "avg": round(float(worst_r.get("blood_glucose_avg", 0)), 1),
            "tir": round(float(worst_r.get("blood_glucose_time_in_range_pct", 0)), 1),
        }
        best_day = {
            "date": best_r.get("sk", "").replace("DATE#", ""),
            "avg": round(float(best_r.get("blood_glucose_avg", 0)), 1),
            "tir": round(float(best_r.get("blood_glucose_time_in_range_pct", 0)), 1),
        }

    return _ok(
        {
            "glucose": {
                "avg_mg_dl": round(float(latest.get("blood_glucose_avg", 0)), 1) if latest.get("blood_glucose_avg") else None,
                "std_dev": round(float(latest.get("blood_glucose_std_dev", 0)), 1) if latest.get("blood_glucose_std_dev") else None,
                "time_in_range_pct": round(tir_today, 1),
                "time_in_optimal_pct": (
                    round(float(latest.get("blood_glucose_time_in_optimal_pct", 0)), 1)
                    if latest.get("blood_glucose_time_in_optimal_pct")
                    else None
                ),
                "time_above_140_pct": (
                    round(float(latest.get("blood_glucose_time_above_140_pct", 0)), 1)
                    if latest.get("blood_glucose_time_above_140_pct")
                    else None
                ),
                "cgm_source": latest.get("cgm_source", "unknown"),
                "tir_status": tir_status,
                "variability_status": variability_status,
                "30d_avg_mg_dl": avg(avg_vals),
                "30d_avg_tir": avg(tir_vals),
                "30d_avg_optimal": avg(opt_vals),
                "30d_avg_std": avg(std_vals),
                "days_tracked": len(cgm_days),
                "as_of_date": latest.get("sk", "").replace("DATE#", ""),
                "best_day": best_day,
                "worst_day": worst_day,
            },
            "glucose_trend": trend,
        },
        cache_seconds=3600,
    )


def _sane_sleep_score(raw, hours, whoop_quality):
    """Gate an implausible nightly sleep score. A score <40 next to >=6h slept AND/OR a healthy
    Whoop quality (>=70) is a scoring/attribution glitch (the live '12' next to 8.2h + 84%
    quality), not a real terrible night — fall back to Whoop quality so one bad number doesn't
    make the whole sleep page look broken. Returns a rounded score or None."""
    if raw is None:
        return None
    try:
        raw = round(float(raw), 0)
    except (TypeError, ValueError):
        return None
    hrs = float(hours) if hours else 0
    wq = float(whoop_quality) if whoop_quality else 0
    if raw < 40 and (hrs >= 6 or wq >= 70):
        return round(wq, 0) if wq else None
    return raw


# ── Cross-source correlation board (sleep §8, Phase 2) ───────────────────────
# Self-policing: every card carries n + overlap_weeks + a confidence tag. The Pearson
# coefficient is computed ONLY at >=14 overlapping days (>=2 weeks); below that it's
# direction-only ("watching — too early"). Sleep-vs-weight (C1) is hard-WITHHELD through
# the water-weight phase. Powered by the same raw sources the platform tools read; the
# Pearson + day-lag logic is replicated compactly here (site-api can't import mcp/).
_CORR_MIN_COEF_DAYS = 14  # >=2 weeks of overlap before any coefficient

_CORR_MIN_DIR_DAYS = 4  # below this, not even a direction


def _shift_date(d, lag):
    try:
        return (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=lag)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _corr_card(cid, label, predictor, outcome, pred_series, outc_series, lag=0, withhold=False, note=""):
    """Build one self-policing correlation card from two {date: value} maps."""
    xs, ys = [], []
    for d, x in (pred_series or {}).items():
        d2 = _shift_date(d, lag)
        if d2 and d2 in (outc_series or {}) and x is not None and outc_series[d2] is not None:
            xs.append(float(x))
            ys.append(float(outc_series[d2]))
    n = len(xs)
    card = {
        "id": cid,
        "label": label,
        "predictor": predictor,
        "outcome": outcome,
        "n": n,
        "overlap_weeks": round(n / 7, 1),
        "lag_days": lag,
        "direction": "insufficient",
        "coefficient": None,
        "withheld": bool(withhold),
        "confidence": "watching — too early",
        "noise": False,
        "note": note,
    }
    if n >= _CORR_MIN_DIR_DAYS:
        mx, my = sum(xs) / n, sum(ys) / n
        cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
        card["direction"] = "moves together" if cov > 0 else ("moves opposite" if cov < 0 else "flat")
        card["noise"] = n < 7  # thin pairs are likely noise
    if withhold:
        card["confidence"] = "withheld — water-weight phase"
        card["coefficient"] = None
    elif n >= _CORR_MIN_COEF_DAYS:
        mx, my = sum(xs) / n, sum(ys) / n
        cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
        sx = sum((a - mx) ** 2 for a in xs) ** 0.5
        sy = sum((b - my) ** 2 for b in ys) ** 0.5
        card["coefficient"] = round(cov / (sx * sy), 2) if sx > 0 and sy > 0 else None
        card["confidence"] = "low confidence" if n < 30 else "moderate"
    return card


def _whoop_daily(d30, today):
    """Whoop daily metrics keyed by date: recovery, strain, deep hours, sleep hours."""
    out = {}
    for w in _query_source("whoop", d30, today):
        if "#WORKOUT#" in w.get("sk", ""):
            continue
        dt = w.get("sk", "").replace("DATE#", "")[:10]
        if not dt:
            continue
        out[dt] = {
            "recovery": _f(w.get("recovery_score")),
            "strain": _f(w.get("strain")),
            "deep": _f(w.get("slow_wave_sleep_hours")),
            "hours": _f(w.get("sleep_duration_hours")),
            "hrv": _f(w.get("hrv")),
        }
    return out


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def handle_sleep_correlations() -> dict:
    """
    GET /api/sleep_correlations
    The self-policing cross-source signal board. Each card: n + overlap-weeks + confidence;
    direction-only under 2 weeks (no coefficient); Pearson only at >=2 weeks. Sleep-vs-weight
    withheld through the water-weight phase. Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)
    wd = _whoop_daily(d30, today)
    recovery = {d: v["recovery"] for d, v in wd.items() if v["recovery"] is not None}
    strain = {d: v["strain"] for d, v in wd.items() if v["strain"] is not None}

    cards = []
    # A1 (LEAD) — last night's recovery → today's training capacity (same-day; the only
    # arrow that changes tomorrow morning). Outcome proxy: the day's Whoop strain.
    cards.append(
        _corr_card(
            "A1",
            "Last night's recovery → today's training capacity",
            "sleep recovery",
            "day strain",
            recovery,
            strain,
            lag=0,
            note="The only arrow that changes tomorrow morning — high recovery should let the day carry more strain.",
        )
    )
    # A2 — day strain → next-night deep sleep (day-lagged: "did I earn it?").
    deep = {d: v["deep"] for d, v in wd.items() if v["deep"] is not None}
    cards.append(
        _corr_card(
            "A2",
            "Day strain → next-night deep sleep",
            "day strain",
            "deep sleep",
            strain,
            deep,
            lag=1,
            note="Did I earn it? — yesterday's training load against tonight's deep sleep.",
        )
    )
    # Eight Sleep nightly sleep-score series (feeds the A4 last-meal card).
    # NB: the former "A3 — bed temp → deep sleep" card was retired (ADR-118,
    # #489) — the Eight Sleep temperature pipeline is dead (dead /v2/intervals
    # endpoint, no bed_temp_f for 4+ months), so the card only ever rendered empty.
    eight = {}
    for e in _query_source("eightsleep", d30, today):
        dt = e.get("sk", "").replace("DATE#", "")[:10]
        if dt:
            eight[dt] = {"score": _f(e.get("sleep_score"))}
    sleep_score = {d: v["score"] for d, v in eight.items() if v["score"] is not None}
    # A4 — last meal time → sleep score. MacroFactor food_log latest time per day.
    last_meal = {}
    for m in _query_source("macrofactor", d30, today):
        dt = m.get("date") or m.get("sk", "").replace("DATE#", "")[:10]
        times = []
        for ent in m.get("food_log") or []:
            try:
                p = str(ent.get("time")).split(":")
                times.append(int(p[0]) * 60 + int(p[1]))
            except (ValueError, IndexError, AttributeError):
                pass
        if times and dt:
            last_meal[dt] = max(times)
    cards.append(
        _corr_card(
            "A4",
            "Last meal time → sleep score",
            "last meal",
            "sleep score",
            last_meal,
            sleep_score,
            lag=0,
            note="Eating late can blunt the night — last-meal minutes against how the night scored.",
        )
    )
    # B1 — decision fatigue (Todoist completed-task load) → sleep score. No app tracks this.
    todoist = {}
    for t in _query_source("todoist", d30, today):
        dt = t.get("date") or t.get("sk", "").replace("DATE#", "")[:10]
        v = _f(t.get("completed_count") or t.get("tasks_completed") or t.get("completed") or t.get("completed_today"))
        if v is not None and dt:
            todoist[dt] = v
    cards.append(
        _corr_card(
            "B1",
            "Decision load (Todoist) → sleep score",
            "Todoist load",
            "sleep score",
            todoist,
            sleep_score,
            lag=0,
            note="A heavy decision day against how the night scored — the cross-source signal no sleep app has.",
        )
    )
    # B2 — mood/journal → sleep (bidirectional). State-of-Mind valence as the mood proxy;
    # empty (n=0 → watching) when mood/journal logging is stale.
    mood = {}
    # SoM daily valence lands on the apple_health partition as som_avg_valence
    # (there is no separate state_of_mind partition).
    for sm in _query_source("apple_health", d30, today):
        dt = sm.get("date") or sm.get("sk", "").replace("DATE#", "")[:10]
        v = _f(sm.get("som_avg_valence"))
        if v is not None and dt:
            mood[dt] = v
    cards.append(
        _corr_card(
            "B2",
            "Mood → sleep score",
            "mood / valence",
            "sleep score",
            mood,
            sleep_score,
            lag=0,
            note="Mood and sleep move together both ways — gated on active mood/journal logging; empty until entries accrue.",
        )
    )
    # B3 — day-of-week best duration. Not a Pearson pair; n=1/day at week one = noise.
    durations = {d: v["hours"] for d, v in wd.items() if v["hours"] is not None}
    dow: dict[int, list[float]] = {}
    for d, h in durations.items():
        try:
            dow.setdefault(datetime.strptime(d, "%Y-%m-%d").weekday(), []).append(h)
        except ValueError:
            pass
    _wk = round(len(durations) / 7, 1)
    b3 = {
        "id": "B3",
        "label": "Day-of-week → best sleep duration",
        "predictor": "day of week",
        "outcome": "sleep duration",
        "n": len(durations),
        "overlap_weeks": _wk,
        "lag_days": 0,
        "coefficient": None,
        "withheld": False,
        "direction": "fills in ~4 weeks",
        "confidence": "watching — needs ~4 weeks",
        "noise": True,
        "note": "Which weekday sleeps best needs ~4 weeks — one Tuesday is not a pattern.",
    }
    if _wk >= 4 and dow:
        _best = max(dow, key=lambda k: sum(dow[k]) / len(dow[k]))
        _names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        b3.update(
            {
                "direction": f"best on {_names[_best]} ({round(sum(dow[_best]) / len(dow[_best]), 1)}h avg)",
                "confidence": "low confidence",
                "noise": False,
            }
        )
    cards.append(b3)
    # C1 (shown LAST, labelled loudest) — sleep vs weight. HIGHEST false-positive risk in a
    # water-weight cut; the coefficient is HARD-WITHHELD until well past the early water phase
    # AND explicit sign-off (the STOP-AND-ASK gate). Direction is still shown honestly.
    weight = {}
    for w in _query_source("withings", d30, today):
        dt = w.get("date") or w.get("sk", "").replace("DATE#", "")[:10]
        v = _f(w.get("weight_lbs"))
        if v is not None and dt:
            weight[dt] = v
    cards.append(
        _corr_card(
            "C1",
            "Sleep → weight",
            "sleep score",
            "weight",
            sleep_score,
            weight,
            lag=0,
            withhold=True,
            note="Highest false-positive risk in a water-weight cut — the coefficient stays withheld until well past the early water phase.",
        )
    )

    return _ok({"cards": cards, "min_coef_days": _CORR_MIN_COEF_DAYS, "as_of": today}, cache_seconds=3600)


def handle_sleep_detail() -> dict:
    """
    GET /api/sleep_detail
    Returns: 30-day sleep stats from Eight Sleep + Whoop cross-referenced.
    Shows sleep score, efficiency, quality, and daily trend.
    Cache: 3600s (1h).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)

    eight_days = _query_source("eightsleep", d30, today)
    whoop_days = _query_source("whoop", d30, today)

    # Index whoop by date for cross-referencing
    whoop_by_date = {r.get("sk", "").replace("DATE#", ""): r for r in whoop_days if r.get("sk")}

    eight_days.sort(key=lambda x: x.get("sk", ""))
    # Filter to experiment window — EXPERIMENT_QUERY_START fetches 1 day early for sleep lookback,
    # but we only display data from EXPERIMENT_START onwards
    eight_with_data = [
        r for r in eight_days if r.get("sleep_score") is not None and r.get("sk", "").replace("DATE#", "") >= EXPERIMENT_START
    ]

    if not eight_with_data:
        return _ok({"sleep_detail": None, "sleep_trend": []}, cache_seconds=3600)

    latest = eight_with_data[-1]
    latest_date = latest.get("sk", "").replace("DATE#", "")
    whoop_latest = whoop_by_date.get(latest_date, {})
    # #495/M-9: if the latest Eight Sleep night has no matching Whoop recovery,
    # borrow the most recent night that has one — but ONLY the recovery block
    # (recovery/HRV/RHR), and SAY SO via recovery_night_of. The old code swapped
    # the whole Whoop record, so night-A hours/stages + night-B recovery rendered
    # under one dated header with no per-field date.
    whoop_recovery_rec = whoop_latest
    recovery_night_of = None
    if not whoop_latest.get("recovery_score"):
        for r in reversed(eight_with_data):
            _rd = r.get("sk", "").replace("DATE#", "")
            _wm = whoop_by_date.get(_rd, {})
            if _wm.get("recovery_score"):
                whoop_recovery_rec = _wm
                if _rd != latest_date:
                    recovery_night_of = _rd
                break

    # 30-day averages (actual field names: sleep_efficiency_pct, sleep_duration_hours)
    score_vals = [float(r["sleep_score"]) for r in eight_with_data if r.get("sleep_score")]
    eff_vals = [float(r["sleep_efficiency_pct"]) for r in eight_with_data if r.get("sleep_efficiency_pct")]
    # Bed-temperature surfaces retired (ADR-118, #489) — the Eight Sleep temp
    # pipeline is dead (dead /v2/intervals endpoint, no bed_temp_f for 4+ months).

    def avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    # Daily trend — filter to experiment start (EXPERIMENT_QUERY_START is 1 day early for sleep lookback)
    trend = []
    for r in eight_with_data:
        date = r.get("sk", "").replace("DATE#", "")
        if date < EXPERIMENT_START:
            continue  # Don't include pre-experiment days in trend output
        w = whoop_by_date.get(date, {})
        trend.append(
            {
                "date": date,
                "sleep_score": _sane_sleep_score(r.get("sleep_score"), w.get("sleep_duration_hours"), w.get("sleep_quality_score")),
                "efficiency": round(float(r["sleep_efficiency_pct"]), 1) if r.get("sleep_efficiency_pct") else None,
                "hours": round(float(w["sleep_duration_hours"]), 1) if w.get("sleep_duration_hours") else None,
                "whoop_quality": round(float(w["sleep_quality_score"]), 0) if w.get("sleep_quality_score") else None,
                "deep_sleep_hours": round(float(w["slow_wave_sleep_hours"]), 2) if w.get("slow_wave_sleep_hours") else None,
                "rem_sleep_hours": round(float(w["rem_sleep_hours"]), 2) if w.get("rem_sleep_hours") else None,
                "deep_pct": round(float(r["deep_pct"]), 1) if r.get("deep_pct") else None,
                "rem_pct": round(float(r["rem_pct"]), 1) if r.get("rem_pct") else None,
                "light_pct": round(float(r["light_pct"]), 1) if r.get("light_pct") else None,
                "recovery_score": round(float(w["recovery_score"]), 0) if w.get("recovery_score") else None,
                "hrv": round(float(w["hrv"]), 1) if w.get("hrv") else None,
                "rhr": round(float(w["resting_heart_rate"]), 0) if w.get("resting_heart_rate") else None,
                "sleep_start": w.get("sleep_start"),
            }
        )

    # Use the gated latest trend score so a glitch score (the '12') doesn't drive the headline.
    score_today = float(trend[-1]["sleep_score"]) if trend and trend[-1].get("sleep_score") else float(latest.get("sleep_score", 0) or 0)
    score_status = "excellent" if score_today >= 85 else ("good" if score_today >= 70 else "needs_attention")

    # Compute bed time / wake time averages and social jet lag from Whoop sleep_start/end
    bed_times_weekday = []
    bed_times_weekend = []
    wake_times = []
    for w in whoop_days:
        ss = w.get("sleep_start")
        se = w.get("sleep_end")
        if not ss or "#WORKOUT#" in w.get("sk", ""):
            continue
        try:
            start_dt = datetime.fromisoformat(ss.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(se.replace("Z", "+00:00"))
            start_pt = start_dt.astimezone(PT)
            end_pt = end_dt.astimezone(PT)
            # Normalize bed hour: treat times after 6 PM as evening (18-30), before 6 AM as late night (24-30)
            bed_hour = start_pt.hour + start_pt.minute / 60
            if bed_hour < 6:
                bed_hour += 24  # 1 AM → 25, so avg with 11 PM (23) works correctly
            wake_hour = end_pt.hour + end_pt.minute / 60
            wake_times.append(wake_hour)
            if start_pt.weekday() in (4, 5):  # Fri/Sat night = weekend sleep
                bed_times_weekend.append(bed_hour)
            else:
                bed_times_weekday.append(bed_hour)
        except Exception:
            continue

    def _fmt_hour(h):
        """Convert decimal hour to HH:MM AM/PM."""
        h = h % 24
        hr = int(h)
        mn = int((h - hr) * 60)
        ampm = "AM" if hr < 12 else "PM"
        hr12 = hr % 12 or 12
        return f"{hr12}:{mn:02d} {ampm}"

    all_bed = bed_times_weekday + bed_times_weekend
    avg_bed = round(sum(all_bed) / len(all_bed), 2) if all_bed else None
    avg_bed_wd = round(sum(bed_times_weekday) / len(bed_times_weekday), 2) if bed_times_weekday else None
    avg_bed_we = round(sum(bed_times_weekend) / len(bed_times_weekend), 2) if bed_times_weekend else None
    avg_wake = round(sum(wake_times) / len(wake_times), 2) if wake_times else None
    social_jet_lag_hrs = round(abs((avg_bed_wd or 0) - (avg_bed_we or 0)), 1) if avg_bed_wd is not None and avg_bed_we is not None else None

    return _ok(
        {
            "sleep_detail": {
                "sleep_score": round(score_today, 0),
                "sleep_efficiency": round(float(latest.get("sleep_efficiency_pct", 0)), 1) if latest.get("sleep_efficiency_pct") else None,
                "total_sleep_hours": round(float(latest.get("sleep_duration_hours", 0)), 1) if latest.get("sleep_duration_hours") else None,
                "whoop_quality": (
                    round(float(whoop_latest.get("sleep_quality_score", 0)), 0) if whoop_latest.get("sleep_quality_score") else None
                ),
                "whoop_hours": (
                    round(float(whoop_latest.get("sleep_duration_hours", 0)), 1) if whoop_latest.get("sleep_duration_hours") else None
                ),
                "deep_sleep_hours": (
                    round(float(whoop_latest.get("slow_wave_sleep_hours", 0)), 2) if whoop_latest.get("slow_wave_sleep_hours") else None
                ),
                "rem_sleep_hours": round(float(whoop_latest.get("rem_sleep_hours", 0)), 2) if whoop_latest.get("rem_sleep_hours") else None,
                "recovery_score": (
                    round(float(whoop_recovery_rec.get("recovery_score", 0)), 0) if whoop_recovery_rec.get("recovery_score") else None
                ),
                # #495/M-9: when the recovery/HRV/RHR trio above comes from a different
                # night than the Eight Sleep record, this carries that night's date (else null).
                "recovery_night_of": recovery_night_of,
                "hrv": round(float(whoop_recovery_rec.get("hrv", 0)), 1) if whoop_recovery_rec.get("hrv") else None,
                "rhr": (
                    round(float(whoop_recovery_rec.get("resting_heart_rate", 0)), 0)
                    if whoop_recovery_rec.get("resting_heart_rate")
                    else None
                ),
                "score_status": score_status,
                "deep_pct": round(float(latest.get("deep_pct", 0)), 1) if latest.get("deep_pct") else None,
                "rem_pct": round(float(latest.get("rem_pct", 0)), 1) if latest.get("rem_pct") else None,
                "light_pct": round(float(latest.get("light_pct", 0)), 1) if latest.get("light_pct") else None,
                "30d_avg_recovery": (
                    avg(
                        [
                            float(whoop_by_date.get(r.get("sk", "").replace("DATE#", ""), {}).get("recovery_score", 0))
                            for r in eight_with_data
                            if whoop_by_date.get(r.get("sk", "").replace("DATE#", ""), {}).get("recovery_score")
                        ]
                    )
                    if whoop_by_date
                    else None
                ),
                "30d_avg_score": avg(score_vals),
                "30d_avg_efficiency": avg(eff_vals),
                "days_tracked": len(eight_with_data),
                "as_of_date": latest_date,
                "avg_bedtime": _fmt_hour(avg_bed) if avg_bed is not None else None,
                "avg_bedtime_weekday": _fmt_hour(avg_bed_wd) if avg_bed_wd is not None else None,
                "avg_bedtime_weekend": _fmt_hour(avg_bed_we) if avg_bed_we is not None else None,
                "avg_waketime": _fmt_hour(avg_wake) if avg_wake is not None else None,
                "social_jet_lag_hrs": social_jet_lag_hrs,
            },
            "sleep_trend": trend,
        },
        cache_seconds=3600,
    )


def handle_circadian() -> dict:
    """
    GET /api/circadian
    Today's circadian-compliance score — computed daily by
    circadian_compliance_lambda and stored at SOURCE#circadian | DATE#<today>,
    but (until now) never surfaced. A *predictive* 0–100 behavioral score across
    four anchors (wake light, meal timing, screen wind-down, sleep consistency):
    it estimates what tonight's sleep will look like based on today's behaviors.
    Cache: 900s — recomputed once daily; refreshing faster gains nothing.
    """
    item = _latest_item("circadian")
    if not item:
        return _ok({"available": False}, cache_seconds=900)

    comps = item.get("components", {}) or {}
    components = {
        name: {
            "score": c.get("score"),
            "max": c.get("max"),
            "note": c.get("note"),
            # Staleness honesty (truth audit 2026-07-10): False = the lambda had no
            # real signal for this anchor — render "unknown", never a scored default.
            # Legacy records predate the flag; absent means measured (old behavior).
            "measured": c.get("measured", True),
        }
        for name, c in comps.items()
    }
    return _ok(
        {
            "available": True,
            "date": item.get("date"),
            # Temporal frame (additive): this is a forward-looking forecast of how
            # tonight's sleep will turn out given today's behaviours — not a measurement.
            "frame": "tonight",
            "score": item.get("score"),
            "category": item.get("category"),
            "prescription": item.get("prescription"),
            "weakest_component": item.get("weakest_component"),
            "measured_count": item.get("measured_count"),
            "components": components,
        },
        cache_seconds=900,
    )


# ── PhenoAge (Levine et al. 2018) — transparent biological age (P1.5) ──────────────
# Replaces the DEXA black-box "biological age" with a published formula over 9 standard blood
# markers + chronological age. PRIVACY (owner decision, Option A): chronological age is used
# ONLY to compute — it is NEVER returned, and neither is the chrono−pheno gap, so the page
# can't be used to back out the owner's real age. (Residual: the 9 markers are public on the
# labs page, so a determined reader applying this formula could approximate age from a precise
# phenotypic number — flagged for review.) Population-level, correlative, NOT the DNAm clock.
_PHENOAGE_COEF = {  # (coefficient, reference value in formula units) — ref = healthy midpoint
    "albumin_gL": (-0.0336, 45.0),
    "creatinine_umolL": (0.0095, 80.0),
    "glucose_mmolL": (0.1953, 5.0),
    "lncrp": (0.0954, None),  # ln(CRP mg/dL); handled separately
    "lymphocyte_pct": (-0.0120, 32.0),
    "mcv_fL": (0.0268, 90.0),
    "rdw_pct": (0.3306, 13.0),
    "alp_UL": (0.00188, 65.0),
    "wbc_1000": (0.0554, 6.0),
}

_PHENOAGE_LABELS = {
    "albumin_gL": "Albumin",
    "creatinine_umolL": "Creatinine",
    "glucose_mmolL": "Glucose",
    "lncrp": "hs-CRP",
    "lymphocyte_pct": "Lymphocyte %",
    "mcv_fL": "MCV",
    "rdw_pct": "RDW",
    "alp_UL": "Alkaline phosphatase",
    "wbc_1000": "WBC",
}


def _compute_phenoage(vals: dict, age_years: float):
    """Levine Phenotypic Age from the 9 converted markers (formula units) + chronological age.
    Returns the exact phenotypic age in years, or None on bad inputs. Age is an INPUT only."""
    import math

    try:
        g = 0.0076927
        xb = (
            -19.9067
            - 0.0336 * vals["albumin_gL"]
            + 0.0095 * vals["creatinine_umolL"]
            + 0.1953 * vals["glucose_mmolL"]
            + 0.0954 * math.log(max(0.01, vals["crp_mgdL"]))
            - 0.0120 * vals["lymphocyte_pct"]
            + 0.0268 * vals["mcv_fL"]
            + 0.3306 * vals["rdw_pct"]
            + 0.00188 * vals["alp_UL"]
            + 0.0554 * vals["wbc_1000"]
            + 0.0804 * age_years
        )
        mort = 1.0 - math.exp(-math.exp(xb) * (math.exp(120.0 * g) - 1.0) / g)
        if mort <= 0 or mort >= 1:
            return None
        pheno = 141.50225 + math.log(-0.00553 * math.log(1.0 - mort)) / 0.090165
        return pheno
    except (ValueError, KeyError, ZeroDivisionError, OverflowError):
        return None


def handle_phenoage() -> dict:
    """GET /api/phenoage — transparent Levine Phenotypic Age. Option A privacy: returns the
    phenotypic age + the 9 driver markers ONLY; never chronological age or the gap."""
    try:
        S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
        s3 = boto3.client("s3", region_name=S3_REGION)
        resp = s3.get_object(Bucket=S3_BUCKET, Key=f"dashboard/{USER_ID}/clinical.json")
        data = json.loads(resp["Body"].read())
        labs = data.get("labs", {})
        markers = labs.get("biomarkers", []) or []
        by = {}
        for m in markers:
            nm = str(m.get("name", "")).strip().lower()
            if nm and nm not in by:
                by[nm] = m

        def _num(name):
            m = by.get(name)
            if not m:
                return None
            try:
                return float(str(m.get("value")).replace("<", "").replace(">", "").strip())
            except (TypeError, ValueError):
                return None

        raw = {
            "albumin": _num("albumin"),
            "creatinine": _num("creatinine"),
            "glucose": _num("glucose"),
            "crp": _num("crp hs"),
            "mcv": _num("mcv"),
            "rdw": _num("rdw"),
            "alp": _num("alkaline phosphatase"),
            "wbc": _num("wbc"),
            "abs_lymph": _num("absolute lymphocytes"),
        }
        # Lymphocyte % derived from absolute lymphocytes ÷ WBC (2a — exact, labeled).
        lymph_pct = None
        lymph_derived = False
        if raw["abs_lymph"] is not None and raw["wbc"]:
            lymph_pct = round(raw["abs_lymph"] / (raw["wbc"] * 1000.0) * 100.0, 1)
            lymph_derived = True

        required = {
            "Albumin": raw["albumin"],
            "Creatinine": raw["creatinine"],
            "Glucose": raw["glucose"],
            "hs-CRP": raw["crp"],
            "Lymphocyte %": lymph_pct,
            "MCV": raw["mcv"],
            "RDW": raw["rdw"],
            "Alkaline phosphatase": raw["alp"],
            "WBC": raw["wbc"],
        }
        missing = [k for k, v in required.items() if v is None]
        # Chronological age (compute-only; never returned). From profile DOB.
        prof = _get_profile() or {}
        dob = prof.get("date_of_birth")
        age_years = None
        if dob:
            try:
                d = datetime.strptime(str(dob)[:10], "%Y-%m-%d")
                age_years = (datetime.now(timezone.utc).replace(tzinfo=None) - d).days / 365.25
            except (ValueError, TypeError):
                age_years = None

        if missing or age_years is None:
            return _ok(
                {
                    "phenoage": None,
                    "missing": missing or (["chronological age (profile)"] if age_years is None else []),
                    "as_of": labs.get("latest_draw_date"),
                    "lymphocyte_derived": lymph_derived,
                },
                cache_seconds=3600,
            )

        # Convert to formula units.
        vals = {
            "albumin_gL": raw["albumin"] * 10.0,  # g/dL → g/L
            "creatinine_umolL": raw["creatinine"] * 88.42,  # mg/dL → µmol/L
            "glucose_mmolL": raw["glucose"] / 18.0182,  # mg/dL → mmol/L
            "crp_mgdL": raw["crp"] / 10.0,  # mg/L → mg/dL
            "lymphocyte_pct": lymph_pct,
            "mcv_fL": raw["mcv"],
            "rdw_pct": raw["rdw"],
            "alp_UL": raw["alp"],
            "wbc_1000": raw["wbc"],
        }
        pheno = _compute_phenoage(vals, age_years)
        if pheno is None:
            return _ok({"phenoage": None, "missing": ["computation failed"], "as_of": labs.get("latest_draw_date")}, cache_seconds=3600)

        # Per-marker driver direction (younger/older) vs healthy reference — transparent, but
        # NOT the raw contribution (keeps the published surface from adding inversion precision).
        import math

        drivers = []
        for key, (coef, ref) in _PHENOAGE_COEF.items():
            if key == "lncrp":
                val_f = math.log(max(0.01, vals["crp_mgdL"]))
                ref_f = math.log(0.1)
                disp_val, disp_unit = raw["crp"], "mg/L"
            else:
                val_f = vals[key]
                ref_f = ref
                disp_val, disp_unit = {
                    "albumin_gL": (raw["albumin"], "g/dL"),
                    "creatinine_umolL": (raw["creatinine"], "mg/dL"),
                    "glucose_mmolL": (raw["glucose"], "mg/dL"),
                    "lymphocyte_pct": (lymph_pct, "%"),
                    "mcv_fL": (raw["mcv"], "fL"),
                    "rdw_pct": (raw["rdw"], "%"),
                    "alp_UL": (raw["alp"], "U/L"),
                    "wbc_1000": (raw["wbc"], "K/µL"),
                }[key]
            push = coef * (val_f - ref_f)  # >0 raises pheno (older), <0 lowers (younger)
            direction = "older" if push > 0.02 else ("younger" if push < -0.02 else "neutral")
            drivers.append(
                {
                    "name": _PHENOAGE_LABELS[key],
                    "value": disp_val,
                    "unit": disp_unit,
                    "direction": direction,
                    "derived": (key == "lymphocyte_pct" and lymph_derived),
                }
            )

        # Round to the nearest year for display; chronological age and the gap are NOT returned.
        return _ok(
            {
                "phenoage": round(pheno),
                "as_of": labs.get("latest_draw_date"),
                "drivers": drivers,
                "lymphocyte_derived": lymph_derived,
                "missing": [],
            },
            cache_seconds=3600,
        )
    except Exception as e:
        logger.warning(f"[phenoage] failed: {e}")
        return _error(503, "Phenotypic age temporarily unavailable.")


# Privacy absolute (PRE-13 pending): named genes / genotypes must NEVER reach the
# public labs payload. Matched case-insensitively against category + name/notes/range/value.
_GENETIC_CATEGORY_RE = _re.compile(r"pharmacogenomic|genetic|genomic", _re.IGNORECASE)

_GENETIC_TEXT_RE = _re.compile(r"genotype|\bgene\b|\brs\d+\b|variant|allele|\bsnp\b", _re.IGNORECASE)


def _strip_genetic_biomarkers(labs: dict) -> dict:
    """Drop any biomarker that is genetic (pharmacogenomics category, or genotype/gene/rsID/variant
    language in its fields) and recompute served counts so the page header stays consistent."""
    kept = []
    for b in labs.get("biomarkers") or []:
        if _GENETIC_CATEGORY_RE.search(str(b.get("category") or "")):
            continue
        text = " ".join(str(b.get(k) or "") for k in ("name", "notes", "range", "value"))
        if _GENETIC_TEXT_RE.search(text):
            continue
        kept.append(b)
    sanitized = dict(labs)
    sanitized["biomarkers"] = kept
    # Same flag semantics as the front-end (evidence_body.js): truthy and not the string "null".
    sanitized["flagged_count"] = sum(1 for b in kept if b.get("flag") and str(b.get("flag")).lower() != "null")
    for count_key in ("biomarker_count", "total_biomarkers"):
        if count_key in sanitized:
            sanitized[count_key] = len(kept)
    return sanitized


def handle_labs() -> dict:
    """GET /api/labs — Returns lab biomarkers from clinical.json in S3 (genetic entries stripped)."""
    try:
        S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
        s3 = boto3.client("s3", region_name=S3_REGION)
        resp = s3.get_object(Bucket=S3_BUCKET, Key=f"dashboard/{USER_ID}/clinical.json")
        data = json.loads(resp["Body"].read())
        labs = data.get("labs", {})
        if not labs or not labs.get("biomarkers"):
            return _error(404, "No lab data available.")
        labs = _strip_genetic_biomarkers(labs)
        if not labs.get("biomarkers"):
            return _error(404, "No lab data available.")
        return _ok({"labs": labs}, cache_seconds=3600)
    except Exception as e:
        logger.warning(f"[labs] Failed to load clinical.json: {e}")
        return _error(503, "Lab data temporarily unavailable.")
