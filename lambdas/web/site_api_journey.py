"""lambdas/web/site_api_journey.py — the progress record over time.

Split out of ``site_api_vitals.py`` (#1654 — god-module breakup). One seam: **the
chronological story of the experiment** — `/api/journey` (weight trajectory +
projected goal date), `/api/timeline` and `/api/journey_timeline` (life events and
the level-up record, with their persisted drivers), `/api/journey_waveform` (the
daily weight waveform), and `/api/achievements` (badges earned, thresholds owned
by ``health.achievement_rules``).

The routed handler entrypoints stay in the ``site_api_vitals`` facade as thin
delegators; the logic lives here. Handlers receive the facade's ``globals()`` as
``_g`` and read the monkeypatched/injectable state (``table``, ``_query_source``,
``_latest_item``, ``_get_profile``, ``EXPERIMENT_START``, ``pre_start_meta``,
``datetime``) via ``_g["<name>"]`` — the surface
``test_journey_timeline_drivers_1125`` / ``test_achievements_badges_1126`` /
``test_genesis_blind_digest_and_readers_2150`` patch on the facade.

This module does NOT import the facade; no import cycle. Every other shared helper
comes straight from ``site_api_common`` (identical binding semantics to the
pre-split module).
"""

import hashlib  # stable-event-key hash for the achievements feed
from datetime import date, timedelta

from boto3.dynamodb.conditions import Key
from common.pacific_time import pacific_day_n  # #1955 — THE one PT day-index formula
from experiment.phase_filter import source_reads_cross_phase, with_phase_filter  # ADR-058
from health import (
    achievement_rules,  # #1624: the ONE place badge thresholds live
    weight_trend,  # shared weekly-rate + projection
)

from web.site_api_common import (
    EXPERIMENT_BASELINE_WEIGHT_LBS,
    PT,
    USER_ID,
    USER_PREFIX,
    _clamp_today,
    _decimal_to_float,
    _is_blocked_vice,
    _ok,
    logger,
)

# #948/#3478 — the weight, its as-of anchor and the weigh-in COUNT travel together.
# Nulling any subset of these serves an unattributable ghost: a weight with no
# measurement date, or a count of measurements with no dates behind it. Two callers
# need the same suppression (the pre-start countdown and the Day-1 synthetic
# baseline), so the set lives here once rather than being restated per branch.
_WEIGHT_ABSENT_FIELDS = (
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
)


def _null_weight_block(journey: dict) -> None:
    """Report the absence of a weigh-in as an absence (ADR-104), as ONE set."""
    journey["weighin_count"] = 0
    for _k in _WEIGHT_ABSENT_FIELDS:
        journey[_k] = None


def journey(*, _g) -> dict:
    """
    GET /api/journey
    Returns: weight trajectory, progress, milestones, projected goal date.
    Cache: 3600s (1 hr) — weight changes slowly.
    """
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    _get_profile = _g["_get_profile"]
    _latest_item = _g["_latest_item"]
    _query_source = _g["_query_source"]
    datetime = _g["datetime"]
    pre_start_meta = _g["pre_start_meta"]

    today = datetime.now(PT).strftime("%Y-%m-%d")
    d120 = max((datetime.now(PT) - timedelta(days=120)).strftime("%Y-%m-%d"), EXPERIMENT_START)

    withings_all = _query_source("withings", d120, today)
    weight_series = sorted(
        [(w["sk"].replace("DATE#", ""), float(w["weight_lbs"])) for w in withings_all if w.get("weight_lbs")], key=lambda x: x[0]
    )

    # #3478: the genesis baseline below is a CONSTANT, not a reading. Downstream it is
    # indistinguishable from a weigh-in (it fills last_weighin_date and counts toward
    # weighin_count), so the branch that mints it flags itself here.
    weighin_synthetic = False

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
            weighin_synthetic = True

    _p = _get_profile()
    start_weight = float(_p.get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS))
    goal_weight = float(_p.get("goal_weight_lbs", 185.0))
    current_weight = weight_series[-1][1]
    last_weighin_date = weight_series[-1][0]
    # #491/M-6: the shared resolution can find a NEWER Apple Health weigh-in
    # (travel scale) than the Withings series — same helper as vitals/character.
    try:
        _ah_start = (datetime.now(PT) - timedelta(days=7)).strftime("%Y-%m-%d")
        _lw = weight_trend.latest_weight([], _query_source("apple_health", _ah_start, today))
        # #3478: against a SYNTHETIC anchor the `>` test is wrong twice over — the
        # anchor is the genesis date, so a real Day-1 weigh-in dated ON genesis
        # compares equal and loses to a constant. Any in-cycle reading supersedes it.
        if _lw["as_of"] and (_lw["as_of"] >= EXPERIMENT_START if weighin_synthetic else _lw["as_of"] > last_weighin_date):
            current_weight = _lw["weight_lbs"]
            last_weighin_date = _lw["as_of"]
            if weighin_synthetic:
                weight_series = [(_lw["as_of"], _lw["weight_lbs"])]
                weighin_synthetic = False
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
    # "what day are we on" number. Single source so labels stay in sync (#1955:
    # the shared common.pacific_time helper, also used by scripts/v4_proof.py).
    _day_n = pacific_day_n(EXPERIMENT_START)

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

    # #3478 — DAY 1, before the first weigh-in lands. The window above starts AT
    # genesis (one day wide, empty) and the G-4 fallback cannot see the pre-genesis
    # row (the reset re-phases it to `pilot`, hidden by ADR-058), so the synthetic
    # baseline is served as though it were measured: last_weighin_date == the genesis
    # date, weighin_count == 1. That is the same ghost #948 removed from the
    # countdown one day earlier, and ADR-104 gives it the same answer — an absence is
    # reported as absent. Self-heals the moment a real weigh-in lands, which is why
    # it survived every prior cycle: it is reachable exactly once, always unattended.
    if weighin_synthetic:
        _null_weight_block(journey)

    # PRE-START (#931): a staged FUTURE genesis means there is no baseline yet —
    # Day 1's weigh-in creates it. The countdown fields go ON and every delta /
    # progress / projection claim comes OFF (ADR-104: "down X lbs" against a
    # baseline that doesn't exist yet is an invented number). day_n already reads
    # 0 above. Inert (pre_start=False, nothing else changes) once genesis <= today.
    _pre = pre_start_meta()
    journey["pre_start"] = bool(_pre)
    if _pre:
        journey.update(_pre)
        # #948: the weight + its as-of anchor travel TOGETHER — keeping a stale
        # prior-cycle weigh-in while nulling last_weighin_date served an
        # unattributable ghost weight during the countdown, and contradicted
        # /api/vitals (which nulls weight_lbs).
        _null_weight_block(journey)

    return _ok({"journey": journey}, cache_seconds=3600)


def timeline(*, _g) -> dict:
    """
    GET /api/timeline
    Returns weight series + life events + experiments + level-ups
    for the interactive Transformation Timeline page.
    Cache: 3600s.
    """
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    _get_profile = _g["_get_profile"]
    _query_source = _g["_query_source"]
    datetime = _g["datetime"]
    table = _g["table"]

    today = datetime.now(PT).strftime("%Y-%m-%d")
    start = EXPERIMENT_START

    # Weight series (full journey)
    wt_items = _query_source("withings", start, today)
    weights = sorted(
        [{"date": i["sk"].replace("DATE#", ""), "lbs": round(float(i["weight_lbs"]), 1)} for i in wt_items if i.get("weight_lbs")],
        key=lambda x: x["date"],
    )

    # Life events (#2150: RAW_TIMESERIES — read cross-phase so pre-genesis captions
    # survive a reset; the weight series above is already genesis-anchored via
    # `start = EXPERIMENT_START`, so only the narrative annotations were truncating)
    life_pk = f"USER#{USER_ID}#SOURCE#life_events"
    le_resp = table.query(
        **with_phase_filter({"KeyConditionExpression": Key("pk").eq(life_pk)}, include_pilot=source_reads_cross_phase("life_events"))
    )
    life_events = [
        {
            "date": i.get("date", ""),
            "title": i.get("title", ""),
            "type": i.get("type", "other"),
            "weight": int(i.get("emotional_weight", 3)),
        }
        for i in _decimal_to_float(le_resp.get("Items", []))
    ]

    # Experiments (#2150: EXPERIMENT_SCOPED — stays current-cycle; source_reads_cross_phase
    # resolves False here, so behaviour is unchanged, but the call is now derived rather
    # than hard-coded blind, matching the taxonomy contract explicitly)
    exp_pk = f"USER#{USER_ID}#SOURCE#experiments"
    exp_resp = table.query(
        **with_phase_filter({"KeyConditionExpression": Key("pk").eq(exp_pk)}, include_pilot=source_reads_cross_phase("experiments"))
    )
    # #2240: the timeline publishes experiment NAMES — same never-public-vocabulary
    # screen the challenge routes apply, on name AND id (ER-06).
    experiments = [
        {"name": i.get("name", ""), "start": i.get("start_date", ""), "end": i.get("end_date"), "status": i.get("status", "active")}
        for i in _decimal_to_float(exp_resp.get("Items", []))
        if i.get("sk", "").startswith("EXP#")
        if not (_is_blocked_vice(i.get("name", "") or "") or _is_blocked_vice(i.get("sk", "").replace("EXP#", "")))
    ]

    # Character level history (#2150: EXPERIMENT_SCOPED — stays current-cycle;
    # source_reads_cross_phase resolves False here too, so behaviour is unchanged)
    cs_pk = f"{USER_PREFIX}character_sheet"
    cs_resp = table.query(
        **with_phase_filter(
            {
                "KeyConditionExpression": Key("pk").eq(cs_pk) & Key("sk").begins_with("DATE#"),
                "ScanIndexForward": True,
            },
            include_pilot=source_reads_cross_phase("character_sheet"),
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


def journey_timeline(*, _g) -> dict:
    """
    GET /api/journey_timeline
    Returns ordered timeline events for the Story page:
    - Weight milestones (first crossing of 5-lb thresholds)
    - Level-up events from character_sheet
    - Experiment start/completion events
    Cache: 3600s (1 hr).
    """
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    _get_profile = _g["_get_profile"]
    datetime = _g["datetime"]
    table = _g["table"]

    today = datetime.now(PT).strftime("%Y-%m-%d")
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
            # #2240: event titles embed the experiment name — screen name AND id.
            if _is_blocked_vice(item.get("name", "") or "") or _is_blocked_vice(item.get("sk", "").replace("EXP#", "")):
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


def journey_waveform(*, _g) -> dict:
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
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    datetime = _g["datetime"]
    pre_start_meta = _g["pre_start_meta"]
    table = _g["table"]

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


def achievements(*, _g) -> dict:
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
    _get_profile = _g["_get_profile"]
    datetime = _g["datetime"]
    table = _g["table"]

    today = datetime.now(PT).strftime("%Y-%m-%d")
    d365 = (datetime.now(PT) - timedelta(days=365)).strftime("%Y-%m-%d")

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
