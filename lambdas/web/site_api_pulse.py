"""lambdas/web/site_api_pulse.py — the daily pulse (/api/pulse, /api/pulse_history).

Split out of ``site_api_intelligence.py`` (#1654 — god-module breakup). One seam:
**what changed today, and the same reading for every prior day of the cycle.**
`/api/pulse` assembles the day's signals across sources into the derived
day-over-day readout the cockpit opens on; `/api/pulse_history` walks that same
shape from EXPERIMENT_START to today.

The routed handler entrypoints stay in the ``site_api_intelligence`` facade as
thin delegators; the logic lives here. Handlers receive the facade's ``globals()``
as ``_g`` and read the monkeypatched/injectable state (``table``,
``_query_source``, ``_latest_item``, ``_get_profile``, ``EXPERIMENT_START``,
``resolve_vitals``, ``pre_start_meta``) via ``_g["<name>"]`` — the exact surface
``test_pulse_since_yesterday_1813`` / ``test_pre_start_countdown`` /
``test_vitals_truth_spine`` patch on the facade. This module does NOT import the
facade; no import cycle. Every other shared helper comes straight from
``site_api_common``.
"""

from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key

from web.site_api_common import (
    EXPERIMENT_BASELINE_WEIGHT_LBS,
    PT,
    USER_PREFIX,
    _decimal_to_float,
    _ok,
    night_of_for,
)


def pulse(*, _g) -> dict:
    """
    GET /api/pulse
    Returns live Pulse daily state computed from DynamoDB.
    Reads latest records from each source for real-time glyphs.
    Cache: 300s (5 min).
    """
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    _get_profile = _g["_get_profile"]
    _latest_item = _g["_latest_item"]
    pre_start_meta = _g["pre_start_meta"]
    resolve_vitals = _g["resolve_vitals"]
    table = _g["table"]

    today_pt = datetime.now(PT).strftime("%Y-%m-%d")
    # utc-exempt(#2414): NOT a reader "today" — widens the DDB query range below so
    # UTC-keyed boundary records are caught; the displayed day (_pulse_day) is PT.
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday_pt = (datetime.now(PT) - timedelta(days=1)).strftime("%Y-%m-%d")
    # Display day number in PT; query DynamoDB covering both PT and UTC dates
    _pulse_day = (
        max(1, (datetime.now(PT).date() - datetime.strptime(EXPERIMENT_START, "%Y-%m-%d").date()).days + 1)
        if today_pt >= EXPERIMENT_START
        else 0
    )
    # Query range covers yesterday(PT) through today(UTC) to catch timezone boundary records
    q_start = min(yesterday_pt, today_pt)
    q_end = max(today_pt, today_utc)

    # Read latest data from each source
    # #1369 Truth Spine: recovery/hrv/rhr/sleep/steps come from the ONE canonical
    # resolver — /api/vitals (→ /api/snapshot) and the public_stats writers read
    # the same module, so two surfaces can't disagree about the same morning.
    _vr = resolve_vitals(table, USER_PREFIX)
    withings = _latest_item("withings") or {}
    ah = None
    try:
        ah_resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}apple_health") & Key("sk").between(f"DATE#{q_start}", f"DATE#{q_end}"),
            ScanIndexForward=False,
            Limit=1,
        )
        ah = _decimal_to_float(ah_resp.get("Items", [{}])[0]) if ah_resp.get("Items") else {}
    except Exception:
        ah = {}
    habitify = _latest_item("habit_scores") or {}

    # Check for journal entry today + streak (single query for last 30 days)
    journal_today = False
    journal_streak = 0
    journal_gap_days = None  # staleness honesty: days since the LAST entry, for the narrative
    try:
        d30_ago = (datetime.now(PT) - timedelta(days=30)).strftime("%Y-%m-%d")
        j_resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}notion") & Key("sk").between(f"DATE#{d30_ago}", f"DATE#{q_end}~"),
            ProjectionExpression="sk",
        )
        j_dates = set()
        for item in j_resp.get("Items", []):
            j_dates.add(item["sk"][:15])  # "DATE#YYYY-MM-DD"
        # Check both PT and UTC dates for today's journal (entry may be stored under either)
        journal_today = f"DATE#{today_pt}" in j_dates or f"DATE#{today_utc}" in j_dates
        if journal_today:
            journal_streak = 1
            for days_back in range(1, 31):
                check_sk = f"DATE#{(datetime.now(PT) - timedelta(days=days_back)).strftime('%Y-%m-%d')}"
                if check_sk in j_dates:
                    journal_streak += 1
                else:
                    break
        elif j_dates:
            _last_j = max(d[5:] for d in j_dates)
            journal_gap_days = max(0, (datetime.strptime(today_pt, "%Y-%m-%d").date() - datetime.strptime(_last_j, "%Y-%m-%d").date()).days)
    except Exception:
        pass

    # Also check apple_health for weight fallback
    w_val = float(withings.get("weight_lbs", 0)) if withings.get("weight_lbs") else None
    ah_wt = float(ah.get("weight_lbs", 0)) if ah and ah.get("weight_lbs") else None
    w_date = withings.get("sk", "").replace("DATE#", "")[:10] if withings else None
    ah_date = ah.get("sk", "").replace("DATE#", "")[:10] if ah else None
    w_eff_date = w_date  # the date the served weight actually belongs to (staleness honesty)
    if ah_wt and (not w_val or (ah_date and w_date and ah_date > w_date)):
        w_val = ah_wt
        w_eff_date = ah_date

    _p = _get_profile()
    start_weight = float(_p.get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS))

    # #1369: the canonical resolver already applied the finalized-recovery,
    # sleep-finalizes-separately, and garmin-then-apple-steps policies.
    recovery = _vr["recovery_pct"]
    sleep_hrs = _vr["sleep_hours"]
    steps = _vr["steps"]
    # Water: get the PT-date record specifically (user logs water throughout the day in their timezone)
    water_ml = float(ah.get("water_intake_ml", 0)) if ah and ah.get("water_intake_ml") else None
    water_l = round(water_ml / 1000, 2) if water_ml else None
    t0_pct = float(habitify.get("tier0_pct", 0)) if habitify.get("tier0_pct") else None

    # --- Lift glyph: check for a strength session today (Hevy or Strava) ---
    trained_today = False
    workout_type = None
    try:
        _hevy_today = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}hevy") & Key("sk").between(f"DATE#{today_pt}", f"DATE#{today_pt}~"),
            Limit=1,
        )
        _hevy_items = _hevy_today.get("Items", [])
        if _hevy_items:
            trained_today = True
            workout_type = _hevy_items[0].get("routine_name") or _hevy_items[0].get("workout_name") or "Strength"
    except Exception:
        pass
    # Staleness honesty (truth audit 2026-07-10): "Rest day" on day 15 of a training
    # blackout is fiction. Days since the last logged strength session (Hevy is the
    # strength log of record) drives the honest label below.
    days_since_workout = None
    try:
        _hevy_last = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}hevy") & Key("sk").begins_with("DATE#"),
            ScanIndexForward=False,
            Limit=1,
            ProjectionExpression="sk",
        )
        _hl_items = _hevy_last.get("Items", [])
        if _hl_items:
            _last_lift_date = _hl_items[0].get("sk", "")[5:15]
            days_since_workout = max(
                0, (datetime.strptime(today_pt, "%Y-%m-%d").date() - datetime.strptime(_last_lift_date, "%Y-%m-%d").date()).days
            )
    except Exception:
        pass
    if not trained_today:
        try:
            _strava_today = table.query(
                KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}strava") & Key("sk").between(f"DATE#{today_pt}", f"DATE#{today_pt}~"),
                Limit=1,
            )
            _strava_items = _strava_today.get("Items", [])
            if _strava_items:
                # Only count strength-type activities for the lift glyph — not walks/runs/rides
                _LIFT_TYPES = {"WeightTraining", "Crossfit", "Workout", "HIIT", "Yoga", "RockClimbing"}
                for _act in _strava_items[0].get("activities", []):
                    _act_m = _act.get("M", _act) if isinstance(_act, dict) else _act
                    _atype = (
                        _act_m.get("sport_type", {}).get("S", "")
                        if isinstance(_act_m.get("sport_type"), dict)
                        else str(_act_m.get("sport_type", ""))
                    )
                    if _atype in _LIFT_TYPES:
                        trained_today = True
                        _aname = (
                            _act_m.get("name", {}).get("S", "") if isinstance(_act_m.get("name"), dict) else str(_act_m.get("name", ""))
                        )
                        workout_type = _aname or _atype or "Strength"
                        break
        except Exception:
            pass

    # --- Mind glyph: State of Mind valence score ---
    mind_score = None
    try:
        _som_resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}state_of_mind") & Key("sk").between(f"DATE#{today_pt}", f"DATE#{today_pt}~"),
            ScanIndexForward=False,
            Limit=1,
        )
        _som_items = _som_resp.get("Items", [])
        if _som_items:
            mind_score = float(_som_items[0].get("som_avg_valence", 0)) or None
        if not mind_score:
            # Fallback: apple_health partition
            _ah_som = table.query(
                KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}apple_health")
                & Key("sk").between(f"DATE#{today_pt}", f"DATE#{today_pt}~"),
                ScanIndexForward=False,
                Limit=1,
            )
            for _a in _ah_som.get("Items", []):
                _sv = _a.get("som_avg_valence")
                if _sv:
                    mind_score = float(_sv)
                    break
    except Exception:
        pass

    # --- N2: Nutrition logging check (last 7 days) ---
    nutrition_logged_7d = 0
    try:
        _d7 = (datetime.now(PT) - timedelta(days=7)).strftime("%Y-%m-%d")
        _mf_resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}macrofactor") & Key("sk").between(f"DATE#{_d7}", f"DATE#{today_pt}~"),
        )
        nutrition_logged_7d = sum(
            1 for i in _mf_resp.get("Items", []) if i.get("total_calories_kcal") and float(str(i["total_calories_kcal"])) > 0
        )
    except Exception:
        pass

    # --- Glyph state classification (DPR-1.02) ---
    # RULE: gray = genuinely no data (value is None/null/absent).
    # If a value exists, it MUST be green, amber, or red — never gray.
    def _scale_state():
        if w_val is None:
            return "gray"
        # Staleness honesty (truth audit 2026-07-10): a lit glyph reads as "today's
        # weigh-in". When the latest reading belongs to an older day the glyph goes
        # gray — value/delta stay in the payload for context, dated by as_of.
        if w_eff_date and w_eff_date != today_pt:
            return "gray"
        delta = w_val - start_weight
        if delta <= 0:
            return "green"
        return "amber" if delta <= 2 else "red"

    def _water_state():
        if water_l is None:
            return "gray"
        pct = water_l / 3.0
        if pct >= 0.8:
            return "green"
        return "amber" if pct >= 0.3 else "red"

    def _movement_state():
        if steps is None:
            return "gray"
        if steps >= 8000:
            return "green"
        return "amber" if steps >= 4000 else "red"

    def _recovery_state():
        if recovery is None:
            return "gray"
        if recovery >= 67:
            return "green"
        return "amber" if recovery >= 34 else "red"

    def _sleep_state():
        if sleep_hrs is None:
            return "gray"
        if sleep_hrs >= 7:
            return "green"
        return "amber" if sleep_hrs >= 6 else "red"

    def _mind_state():
        if mind_score is None or mind_score == 0:
            return "gray"
        if mind_score >= 4:
            return "green"
        return "amber" if mind_score >= 2 else "red"

    glyphs = {
        "scale": {
            "state": _scale_state(),
            "value": round(w_val, 1) if w_val else None,
            "direction": "down" if w_val and w_val < start_weight else "up",
            "delta": round(w_val - start_weight, 1) if w_val else None,
            "delta_label": f"{round(w_val - start_weight, 1):+.1f} lbs" if w_val else None,
            "as_of": w_eff_date or today_pt,
        },
        "water": {
            "state": _water_state(),
            "liters": water_l,
            "target": 3.0,
            "label": f"{water_l}L" if water_l else None,
            "as_of": today_pt,
        },
        "movement": {
            "state": _movement_state(),
            "value": int(steps) if steps else None,
            "target": 8000,
            "label": f"{int(steps):,} steps" if steps else None,
            "source": _vr["steps_source"],
            "as_of": _vr["steps_as_of"],
        },
        "recovery": {
            "state": _recovery_state(),
            "value": round(recovery) if recovery else None,
            "recovery_pct": round(recovery) if recovery else None,
            "hrv_ms": round(_vr["hrv_ms"], 1) if _vr["hrv_ms"] is not None else None,
            "rhr_bpm": round(_vr["rhr_bpm"], 1) if _vr["rhr_bpm"] is not None else None,
            "label": f"{round(recovery)}%" if recovery else None,
            "as_of": _vr["recovery_as_of"],
            # #1968: recovery/HRV/RHR are wake-date-keyed, so `as_of` is the MORNING.
            # Name the night too (via the one #1923 helper) — a glyph that publishes a
            # figure with only a morning on it is what let two surfaces disagree about
            # the same night in public.
            "night_of": night_of_for(_vr["recovery_as_of"]),
        },
        "sleep": {
            "state": _sleep_state(),
            "value": round(sleep_hrs, 1) if sleep_hrs else None,
            "hours": round(sleep_hrs, 1) if sleep_hrs else None,
            "label": f"{round(sleep_hrs, 1)}h" if sleep_hrs else None,
            "as_of": _vr["sleep_as_of"],
            "night_of": night_of_for(_vr["sleep_as_of"]),  # #1968, same frame
        },
        "journal": {
            "state": "green" if journal_today else "gray",
            "written_today": journal_today,
            "streak_days": journal_streak,
            "gap_days": journal_gap_days,
            "label": (
                "Journaled"
                if journal_today
                else (f"No entry in {journal_gap_days} days" if journal_gap_days is not None and journal_gap_days >= 2 else "No entry yet")
            ),
        },
        "lift": {
            "state": "green" if trained_today else "gray",
            "trained_today": trained_today,
            "workout_type": workout_type,
            "days_since_last": days_since_workout,
            # "Rest day" is only honest for a beat or two after a session; past that it's
            # a layoff and the glyph says how long. No hevy record at all reads unlogged.
            "label": workout_type
            or (
                "Trained"
                if trained_today
                else (
                    "Rest day"
                    if days_since_workout is not None and days_since_workout <= 3
                    else (f"No training logged — {days_since_workout} days" if days_since_workout is not None else "No training logged")
                )
            ),
        },
        "mind": {
            "state": _mind_state(),
            "score": mind_score,
            "label": f"{mind_score:.1f}/5" if mind_score else None,
        },
    }

    signals_reporting = sum(1 for g in glyphs.values() if g.get("state") != "gray")
    amber_or_red = sum(1 for g in glyphs.values() if g.get("state") in ("amber", "red"))
    if signals_reporting == 0:
        status = "quiet"
    elif amber_or_red >= 2 or any(
        g.get("state") == "red" and g.get("recovery_pct") is not None and g["recovery_pct"] < 40 for g in glyphs.values()
    ):
        status = "mixed"
    elif t0_pct and t0_pct >= 80 and recovery and recovery > 50:
        status = "strong"
    else:
        status = "green" if signals_reporting >= 4 else "mixed"

    # --- DPR-1.01: Narrative generator ---
    # Build a natural-language daily brief headline from available signals.
    narrative_parts = []
    if w_val is not None:
        delta_from_start = round(w_val - start_weight, 1)
        dir_word = "down" if delta_from_start < 0 else "up" if delta_from_start > 0 else "flat"
        # Staleness honesty: a days-old weigh-in narrated without a date reads as
        # today's number \u2014 stale-qualify it with the day it actually belongs to.
        _w_stale_note = ""
        if w_eff_date and w_eff_date != today_pt:
            try:
                _lw_dt = datetime.strptime(w_eff_date, "%Y-%m-%d")
                _w_stale_note = f" (last weighed {_lw_dt.strftime('%b')} {_lw_dt.day})"
            except ValueError:
                _w_stale_note = f" (last weighed {w_eff_date})"
        narrative_parts.append(
            f"Day {_pulse_day}. {round(w_val, 1)} lbs \u2014 {dir_word} {abs(delta_from_start):.1f} from start{_w_stale_note}."
        )
    elif _pulse_day:
        narrative_parts.append(f"Day {_pulse_day}.")
    if sleep_hrs is not None:
        s_part = f"Sleep: {round(sleep_hrs, 1)}h"
        if sleep_hrs < 6:
            s_part += " \u2014 short night"
        elif sleep_hrs >= 7.5:
            s_part += " \u2014 solid rest"
        narrative_parts.append(s_part + ".")
    if recovery is not None:
        r_val = round(recovery)
        if r_val < 34:
            narrative_parts.append(f"Recovery low at {r_val}% \u2014 rest day suggested.")
        elif r_val < 50:
            narrative_parts.append(f"Recovery at {r_val}% \u2014 consider a lighter day.")
        elif r_val >= 67:
            narrative_parts.append(f"Recovery strong at {r_val}%.")
        else:
            narrative_parts.append(f"Recovery at {r_val}%.")
    if journal_today:
        narrative_parts.append("Journal logged.")
    elif journal_gap_days is not None and journal_gap_days >= 2:
        # "yet" implies today is the exception — past the threshold, the gap is the fact.
        narrative_parts.append(f"No journal entry in {journal_gap_days} days.")
    else:
        narrative_parts.append("No journal entry yet.")
    if nutrition_logged_7d > 0:
        narrative_parts.append(f"Nutrition: {nutrition_logged_7d}/7 days logged.")
    if not narrative_parts or signals_reporting == 0:
        narrative = "No data reported today. Signals populate as wearables sync."
    else:
        narrative = " ".join(narrative_parts)

    # --- DPR-1.14: Since yesterday deltas ---
    since_yesterday = []
    try:
        _yd_whoop = None
        for _w_item in _decimal_to_float(
            table.query(
                KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}whoop")
                & Key("sk").between(f"DATE#{yesterday_pt}", f"DATE#{yesterday_pt}~"),
                Limit=5,
            ).get("Items", [])
        ):
            if "#WORKOUT#" not in _w_item.get("sk", "") and _w_item.get("recovery_score") is not None:
                _yd_whoop = _w_item
                break
        _yd_wt = None
        _yd_wi = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}withings")
            & Key("sk").between(f"DATE#{yesterday_pt}", f"DATE#{yesterday_pt}~"),
            Limit=1,
        ).get("Items", [])
        if _yd_wi and _yd_wi[0].get("weight_lbs"):
            _yd_wt = float(_yd_wi[0]["weight_lbs"])
        if not _yd_wt:
            _yd_ah = table.query(
                KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}apple_health")
                & Key("sk").between(f"DATE#{yesterday_pt}", f"DATE#{yesterday_pt}~"),
                Limit=1,
            ).get("Items", [])
            if _yd_ah and _yd_ah[0].get("weight_lbs"):
                _yd_wt = float(_yd_ah[0]["weight_lbs"])
        # #1813: the "current" value for each signal is the latest FINALIZED record
        # (resolve_vitals/w_eff_date), which can be one or more days stale \u2014 the
        # normal state during a sync lag or genesis week. When that record's date IS
        # yesterday_pt, the query above for "yesterday" returns the SAME record the
        # current value came from: the delta is structurally 0, a claimed measurement
        # that never happened (ADR-104). Suppress the delta in that case instead of
        # publishing a fabricated "no change."
        if w_val and _yd_wt and w_eff_date != yesterday_pt:
            d = round(w_val - _yd_wt, 1)
            arrow = "\u2191" if d > 0 else "\u2193" if d < 0 else "\u2192"
            since_yesterday.append({"signal": "weight", "text": f"Weight {arrow}{abs(d):.1f} lbs", "delta": d})
            glyphs["scale"]["delta_1d"] = d
        if recovery and _yd_whoop and _yd_whoop.get("recovery_score") and _vr.get("recovery_as_of") != yesterday_pt:
            d = round(recovery - float(_yd_whoop["recovery_score"]))
            arrow = "\u2191" if d > 0 else "\u2193" if d < 0 else "\u2192"
            since_yesterday.append({"signal": "recovery", "text": f"Recovery {arrow}{abs(d)}%", "delta": d})
            glyphs["recovery"]["delta_1d"] = d
        if sleep_hrs and _yd_whoop and _yd_whoop.get("sleep_duration_hours") and _vr.get("sleep_as_of") != yesterday_pt:
            d = round(sleep_hrs - float(_yd_whoop["sleep_duration_hours"]), 1)
            arrow = "\u2191" if d > 0 else "\u2193" if d < 0 else "\u2192"
            since_yesterday.append({"signal": "sleep", "text": f"Sleep {arrow}{abs(d):.1f}h", "delta": d})
            glyphs["sleep"]["delta_1d"] = d
    except Exception:
        pass

    # --- DPR-1.15: Notable signals ---
    notable_signals = []
    if recovery is not None and recovery < 40:
        notable_signals.append(
            {
                "signal": "recovery",
                "message": f"Recovery is low at {round(recovery)}%. Consider a rest day or light movement only.",
                "severity": "warning",
            }
        )
    if sleep_hrs is not None and sleep_hrs < 6:
        notable_signals.append(
            {
                "signal": "sleep",
                "message": f"Sleep was {round(sleep_hrs, 1)}h \u2014 below the 7h minimum. Prioritize an early bedtime tonight.",
                "severity": "warning",
            }
        )
    if w_val and since_yesterday:
        _wt_d = next((s["delta"] for s in since_yesterday if s["signal"] == "weight"), None)
        if _wt_d and _wt_d > 3:
            notable_signals.append(
                {
                    "signal": "weight",
                    "message": f"Weight up {_wt_d:.1f} lbs from yesterday. Likely water retention \u2014 check sodium and hydration.",
                    "severity": "info",
                }
            )

    # PRE-START (#931): between a staged reset and its FUTURE genesis the pulse is a
    # countdown, not a broken Day 0 — deterministic copy (no LLM), and no from-start
    # weight delta (there is no baseline until Day 1's weigh-in creates one). Inert
    # once genesis <= today (pre_start_meta returns None and nothing here changes).
    _pre = pre_start_meta()
    if _pre:
        _n = _pre["days_until_start"]
        _start_dt = datetime.strptime(EXPERIMENT_START, "%Y-%m-%d")
        narrative = (
            f"T−{_n} day{'s' if _n != 1 else ''}. The instruments are on; the experiment begins "
            f"{_start_dt.strftime('%A, %B')} {_start_dt.day}. First baseline: that morning's weigh-in."
        )
        glyphs["scale"]["delta"] = None
        glyphs["scale"]["delta_label"] = None
        # #1813: the #931 contract already nulls the journey delta/scale glyph above —
        # it missed these two. Both are computed from whatever the LAST cycle's data
        # happens to be (a prior-cycle whoop reading can score "low recovery" and get
        # surfaced as a live coaching warning inside a pre-start countdown payload).
        # Neither belongs in front of a reader being told the experiment hasn't begun.
        since_yesterday = []
        notable_signals = []

    return _ok(
        {
            "pulse": {
                **(_pre or {"pre_start": False}),
                "day_number": _pulse_day,
                "date": today_pt,
                "status": status,
                "status_color": {"strong": "#22c55e", "green": "#22c55e", "mixed": "#f5a623", "quiet": "#3a5a48"}.get(status, "#3a5a48"),
                "signals_reporting": signals_reporting,
                "signals_total": 8,
                "narrative": narrative,
                "since_yesterday": since_yesterday,
                "notable_signals": notable_signals,
                "glyphs": glyphs,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        },
        cache_seconds=300,
    )


def pulse_history(*, _g) -> dict:
    """
    GET /api/pulse_history
    Returns daily pulse summaries from EXPERIMENT_START to today.
    One item per day with weight, recovery, sleep, steps.
    Cache: 3600s (1 hr) — historical data doesn't change.
    """
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    _get_profile = _g["_get_profile"]
    _query_source = _g["_query_source"]

    today = datetime.now(PT).strftime("%Y-%m-%d")
    whoop_items = _query_source("whoop", EXPERIMENT_START, today)
    withings_items = _query_source("withings", EXPERIMENT_START, today)
    garmin_items = _query_source("garmin", EXPERIMENT_START, today)
    ah_items = _query_source("apple_health", EXPERIMENT_START, today)  # real steps (Garmin is dead/phantom)

    # Index by date
    whoop_by_date = {}
    for w in whoop_items:
        d = w.get("sk", "").replace("DATE#", "")[:10]
        if d and w.get("recovery_score") is not None:
            whoop_by_date[d] = w
    withings_by_date = {}
    for w in withings_items:
        d = w.get("sk", "").replace("DATE#", "")[:10]
        if d and w.get("weight_lbs"):
            withings_by_date[d] = w
    # Steps: Apple Health first; Garmin only if AH-absent AND plausible (>=1000) — drops the
    # phantom ~298 Garmin record that left steps null on 7/8 days (Vitals + Mirror depend on this).
    steps_by_date: dict[str, int] = {}
    for h in ah_items:
        d = h.get("sk", "").replace("DATE#", "")[:10]
        if d and h.get("steps") and float(h["steps"]) > 0:
            steps_by_date[d] = max(steps_by_date.get(d, 0), int(float(h["steps"])))
    for g in garmin_items:
        d = g.get("sk", "").replace("DATE#", "")[:10]
        if d and g.get("steps") and float(g["steps"]) >= 1000 and d not in steps_by_date:
            steps_by_date[d] = int(float(g["steps"]))

    # Build daily summaries
    days = []
    current = datetime.strptime(EXPERIMENT_START, "%Y-%m-%d")
    end = datetime.strptime(today, "%Y-%m-%d")
    _p = _get_profile()
    start_weight = float(_p.get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS))
    day_num = 1

    while current <= end:
        d = current.strftime("%Y-%m-%d")
        w = whoop_by_date.get(d, {})
        wi = withings_by_date.get(d, {})

        weight = float(wi["weight_lbs"]) if wi.get("weight_lbs") else None
        recovery = float(w["recovery_score"]) if w.get("recovery_score") else None
        sleep_hrs = float(w["sleep_duration_hours"]) if w.get("sleep_duration_hours") else None
        hrv = float(w["hrv"]) if w.get("hrv") else None
        rhr = float(w["resting_heart_rate"]) if w.get("resting_heart_rate") else None  # falls during a cut = body responding
        strain = float(w["strain"]) if w.get("strain") else None
        steps = steps_by_date.get(d)

        headline_parts = []
        if weight:
            delta = round(weight - start_weight, 1)
            headline_parts.append(f"{round(weight)} lbs ({delta:+.1f})")
        if recovery is not None:
            headline_parts.append(f"Recovery {round(recovery)}%")
        if sleep_hrs:
            headline_parts.append(f"Sleep {round(sleep_hrs, 1)}h")

        days.append(
            {
                "date": d,
                "day_number": day_num,
                "weight_lbs": round(weight, 1) if weight else None,
                "weight_delta": round(weight - start_weight, 1) if weight else None,
                "recovery_pct": round(recovery) if recovery is not None else None,
                "sleep_hours": round(sleep_hrs, 1) if sleep_hrs else None,
                "hrv_ms": round(hrv, 1) if hrv else None,
                "rhr_bpm": round(rhr) if rhr is not None else None,
                "strain": round(strain, 1) if strain is not None else None,
                "steps": steps,
                "headline": " · ".join(headline_parts) if headline_parts else "No data recorded",
            }
        )
        current += timedelta(days=1)
        day_num += 1

    return _ok({"pulse_history": days}, cache_seconds=3600)
