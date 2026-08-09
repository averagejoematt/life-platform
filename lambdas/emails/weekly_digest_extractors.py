"""weekly_digest_extractors.py — the Sunday Weekly Report's pure extractors.

Lifted verbatim out of `weekly_digest_lambda.py` (#1654's shape, done here because
#2221's honest-numbers fixes pushed that module past its size ratchet). Every function
below is a PURE transform of records the handler already fetched into the summary dicts
the renderer and the Board prompt consume: no DynamoDB, no SES, no clock. The handler
re-exports them, so `weekly_digest_lambda.ex_whoop` and every other call site — including
the behaviour suite's `wd.ex_*` — keeps working unchanged.

Deliberately NOT moved: `weight_projection` and `fetch_stale_insights` read
`datetime.now()`, and the behaviour suite freezes time by patching the handler module's
own `datetime` name. Moving them here would have left a fixture date being differenced
against the real clock — silently, and only on the days the arithmetic happened to agree.
"""

import statistics
from collections import defaultdict
from datetime import datetime

from common.digest_utils import (
    _normalize_whoop_sleep,
    avg,
    compute_banister_from_dict,  # #490: shared TSS-like Banister
    dedup_activities,
    safe_float,
)

# ══════════════════════════════════════════════════════════════════════════════
# EXTRACTORS — return summarized dicts from raw records
# ══════════════════════════════════════════════════════════════════════════════


def ex_day_grades(grades_dict):
    """Extract day grade summary from {date: record} dict."""
    if not grades_dict:
        return None
    days = []
    for date_str in sorted(grades_dict.keys()):
        rec = grades_dict[date_str]
        score = safe_float(rec, "total_score")
        grade = rec.get("letter_grade", "—")
        if score is not None:
            days.append({"date": date_str, "score": score, "grade": grade})
    if not days:
        return None
    scores = [d["score"] for d in days]
    grade_counts = defaultdict(int)
    for d in days:
        g = d["grade"]
        if g.startswith("A"):
            grade_counts["A"] += 1
        elif g.startswith("B"):
            grade_counts["B"] += 1
        elif g.startswith("C"):
            grade_counts["C"] += 1
        elif g == "D":
            grade_counts["D"] += 1
        elif g == "F":
            grade_counts["F"] += 1
    return {
        "days": days,
        "avg_score": avg(scores),
        "min_score": min(scores),
        "max_score": max(scores),
        "grade_counts": dict(grade_counts),
        "days_graded": len(days),
    }


def ex_whoop(recs_dict):
    recs = list(recs_dict.values()) if recs_dict else []
    if not recs:
        return None
    hrvs = [float(r["hrv"]) for r in recs if "hrv" in r]
    recoveries = [float(r["recovery_score"]) for r in recs if "recovery_score" in r]
    rhrs = [float(r["resting_heart_rate"]) for r in recs if "resting_heart_rate" in r]
    strains = [float(r["strain"]) for r in recs if "strain" in r]
    # ADR-105 (#2221): every average here has its OWN n — the strap can log recovery
    # on six days and HRV on two. This dict is serialised verbatim into the Board
    # prompt (call_haiku's data_json), so a lone `days` next to four averages told the
    # advisors one sample size for four different statistics. `days` keeps its honest
    # meaning (days with a Whoop record) and each average now carries its own n.
    return {
        "hrv_avg": avg(hrvs),
        "hrv_min": min(hrvs, default=None),
        "hrv_max": max(hrvs, default=None),
        "hrv_n": len(hrvs),
        "recovery_avg": avg(recoveries),
        "recovery_min": min(recoveries, default=None),
        "recovery_n": len(recoveries),
        "rhr_avg": avg(rhrs),
        "rhr_n": len(rhrs),
        "strain_avg": avg(strains),
        "strain_n": len(strains),
        "days": len(recs),
    }


# _normalize_whoop_sleep imported from digest_utils


def ex_whoop_sleep(recs_dict):
    """Extract sleep metrics from Whoop records (SOT for sleep duration/staging v2.55.0)."""
    recs = [_normalize_whoop_sleep(r) for r in (recs_dict.values() if recs_dict else [])]
    if not recs:
        return None
    scores = [float(r["sleep_score"]) for r in recs if "sleep_score" in r]
    durs = []
    for r in recs:
        d = safe_float(r, "sleep_duration_hours")
        if d is not None:
            durs.append(d)
    effs = [safe_float(r, "sleep_efficiency_pct") for r in recs]
    effs = [e for e in effs if e is not None]
    deep_pcts = [float(r["deep_pct"]) for r in recs if "deep_pct" in r]
    rem_pcts = [float(r["rem_pct"]) for r in recs if "rem_pct" in r]
    return {
        "score_avg": avg(scores),
        "score_min": min(scores, default=None),
        "duration_avg_hrs": avg(durs),
        "efficiency_avg": avg(effs),
        "deep_pct": avg(deep_pcts),
        "rem_pct": avg(rem_pcts),
        "nights": len(recs),
    }


def ex_withings(recs_dict):
    recs = list(recs_dict.values()) if recs_dict else []
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


def ex_strava(recs_dict, profile):
    recs = list(recs_dict.values()) if recs_dict else []
    if not recs:
        return None
    max_hr = profile.get("max_heart_rate", 186)
    z2_low = max_hr * 0.60
    z2_high = max_hr * 0.70
    acts = []
    zone2_mins = 0
    daily_loads = []
    for r in recs:
        day_kj = 0
        day_acts = r.get("activities", [])
        day_acts = dedup_activities(day_acts)
        for a in day_acts:
            hr = float(a.get("average_heartrate") or 0)
            secs = float(a.get("moving_time_seconds") or 0)
            kj = float(a.get("kilojoules") or 0)
            day_kj += kj
            obj = {
                "date": r.get("date", ""),
                "name": a.get("enriched_name") or a.get("name", ""),
                "sport": a.get("sport_type", ""),
                "miles": round(float(a.get("distance_miles") or 0), 1),
                "elev": round(float(a.get("total_elevation_gain_feet") or 0)),
                "hr": round(hr) if hr else None,
                "mins": round(secs / 60),
                "kj": kj,
            }
            acts.append(obj)
            if hr and z2_low <= hr <= z2_high:
                zone2_mins += obj["mins"]
        if day_kj > 0:
            daily_loads.append(day_kj)
    total_mins = sum(a["mins"] for a in acts)
    z2_pct = round(zone2_mins / total_mins * 100) if total_mins else 0
    mono = (
        round(statistics.mean(daily_loads) / statistics.stdev(daily_loads), 2)
        if len(daily_loads) >= 3 and statistics.stdev(daily_loads) > 0
        else None
    )
    return {
        "total_miles": round(sum(a["miles"] for a in acts), 1),
        "total_elevation_feet": round(sum(a["elev"] for a in acts)),
        "total_minutes": total_mins,
        "activity_count": len(acts),
        "zone2_minutes": round(zone2_mins),
        "zone2_pct": z2_pct,
        "zone2_target": 150,
        "zone2_hr_range": f"{round(z2_low)}-{round(z2_high)}",
        "training_monotony": mono,
        "activities": acts,
    }


def ex_macrofactor(recs_dict, profile):
    recs = list(recs_dict.values()) if recs_dict else []
    if not recs:
        return None
    cal_target = profile.get("calorie_target", 1800)
    prot_target = profile.get("protein_target_g", 190)
    cals = [float(r["total_calories_kcal"]) for r in recs if "total_calories_kcal" in r]
    prots = [float(r["total_protein_g"]) for r in recs if "total_protein_g" in r]
    fats = [float(r["total_fat_g"]) for r in recs if "total_fat_g" in r]
    carbs = [float(r["total_carbs_g"]) for r in recs if "total_carbs_g" in r]
    fibers = [float(r["total_fiber_g"]) for r in recs if "total_fiber_g" in r]
    return {
        "calories_avg": avg(cals),
        "protein_avg_g": avg(prots),
        "fat_avg_g": avg(fats),
        "carbs_avg_g": avg(carbs),
        "fiber_avg_g": avg(fibers),
        "days_logged": len(recs),
        "protein_hit_rate": round(sum(1 for p in prots if p >= prot_target) / len(prots) * 100) if prots else None,
        "calorie_hit_rate": round(sum(1 for c in cals if c <= cal_target * 1.10) / len(cals) * 100) if cals else None,
        # ADR-105 (#2221): each hit rate's own denominator, so the renderer can state it.
        # NOT re-based on the 7-day week: an unlogged day is absence, and dividing by the
        # week would publish it as a MISS — the ADR-104 error the sibling habitify fix in
        # this same tranche removes. State the n; do not invent the miss.
        "protein_hit_n": len(prots),
        "calorie_hit_n": len(cals),
        "protein_target": prot_target,
        "calorie_target": cal_target,
    }


def ex_hevy_workouts(recs):
    """Strength session summary sourced from Hevy per-workout records (#485 —
    macrofactor_workouts stopped ingesting ~4 months ago; Hevy is the live,
    hourly-ingested source per ADR-060).

    `recs` is a FLAT LIST of Hevy DDB records (one item per workout, fetched via
    query_range_list — NOT the {date: record} dict query_range produces, since
    Hevy can legitimately have more than one workout on a date). Each record
    already carries its own exercises/sets, so — unlike the old macrofactor
    daily-aggregate shape this replaces — there's no nested per-day "workouts"
    list to unpack; one Hevy record IS one workout.
    """
    if not recs:
        return None
    workouts = []
    total_vol = 0.0
    total_sets = 0
    for r in recs:
        exercises = r.get("exercises") or []
        vol_lbs = 0.0
        for ex in exercises:
            for s in ex.get("sets") or []:
                weight_kg = safe_float(s, "weight_kg")
                reps = s.get("reps")
                total_sets += 1
                if weight_kg is not None and reps is not None:
                    vol_lbs += (weight_kg / 0.45359237) * float(reps)
        workouts.append(
            {
                "date": r.get("date", ""),
                "name": r.get("title") or "Workout",
                "exercises": len(exercises),
                "volume_lbs": round(vol_lbs),
            }
        )
        total_vol += vol_lbs
    if not workouts:
        return None
    return {
        "workout_count": len(workouts),
        "workouts": workouts,
        "total_volume_lbs": round(total_vol),
        "total_sets": total_sets,
        "best_workout": max(workouts, key=lambda w: w["volume_lbs"], default=None),
    }


def ex_habitify(recs_dict, profile):
    recs = list(recs_dict.values()) if recs_dict else []
    if not recs:
        return None
    mvp_list = profile.get("mvp_habits", [])
    daily_mvp_pcts = []
    daily_overall_pcts = []
    mvp_completion = defaultdict(int)  # habit_name -> days completed
    mvp_offered = defaultdict(int)  # habit_name -> days Habitify actually returned it
    mvp_days_available = 0
    mvp_perfect_days = 0
    for r in recs:
        habits_map = r.get("habits", {})
        if not habits_map:
            continue
        mvp_days_available += 1
        mvp_done = 0
        # ADR-104 (#2221): a habit Habitify did not return for a day at all (archived,
        # paused, renamed, or an ingestion gap) is ABSENCE, not a recorded miss. It used
        # to read `habits_map.get(h, 0)`, so a rename rendered "0/7 (0%)" in red and
        # dragged the MVP average down with data that was never collected.
        offered = [h for h in mvp_list if h in habits_map]
        for h in offered:
            mvp_offered[h] += 1
            done = habits_map.get(h)
            if done is not None and float(done) >= 1:
                mvp_done += 1
                mvp_completion[h] += 1
        if offered:
            daily_mvp_pcts.append(mvp_done / len(offered) * 100)
            # #2221: the EXACT count of days on which every offered MVP habit was done.
            # The renderer used min(per-habit totals), which is only a lower bound —
            # two habits each done 5 of 7 days on disjoint days rendered 5 perfect days
            # where the true answer is 0. Overstated, never understated.
            if mvp_done == len(offered):
                mvp_perfect_days += 1
        comp = safe_float(r, "completion_pct")
        if comp is not None:
            daily_overall_pcts.append(comp * 100)
    return {
        "mvp_avg_pct": avg(daily_mvp_pcts),
        "overall_avg_pct": avg(daily_overall_pcts),
        "mvp_completion": dict(mvp_completion),
        "mvp_offered": dict(mvp_offered),
        "mvp_perfect_days": mvp_perfect_days,
        "mvp_total": len(mvp_list),
        "days_tracked": mvp_days_available,
    }


def ex_apple_health(recs_dict):
    recs = list(recs_dict.values()) if recs_dict else []
    if not recs:
        return None
    steps = [float(r["steps"]) for r in recs if "steps" in r]
    water = [float(r["water_intake_ml"]) for r in recs if "water_intake_ml" in r and float(r.get("water_intake_ml", 0)) >= 118]
    glucose_avgs = [float(r["blood_glucose_avg"]) for r in recs if "blood_glucose_avg" in r]
    tir_vals = [float(r["blood_glucose_time_in_range_pct"]) for r in recs if "blood_glucose_time_in_range_pct" in r]
    gait_speeds = [float(r["walking_speed_mph"]) for r in recs if "walking_speed_mph" in r]
    return {
        "steps_avg": avg(steps),
        "steps_total": round(sum(steps)) if steps else None,
        "water_avg_ml": avg(water),
        "water_days": len(water),
        "glucose_avg": avg(glucose_avgs),
        "glucose_tir_avg": avg(tir_vals),
        "glucose_days": len(glucose_avgs),
        "gait_speed_avg": avg(gait_speeds),
        "gait_days": len(gait_speeds),
        "days": len(recs),
    }


def ex_todoist(recs_dict):
    recs = list(recs_dict.values()) if recs_dict else []
    if not recs:
        return None
    # #2245: todoist_lambda writes `completed_count` (the #480/A-7 rename documented in
    # ingestion_validator.py) — reading the pre-rename `tasks_completed` matched nothing
    # and published a permanent measured zero. The OUTPUT key stays `tasks_completed`:
    # it is the renderer's and the Board prompt's contract, not the storage field.
    c = [int(r.get("completed_count", 0) or 0) for r in recs]
    return {"tasks_completed": sum(c), "avg_per_day": avg(c), "days": len(recs)}


def ex_journal(entries_by_date):
    """Extract journal signals from {date: [entries]} dict."""
    if not entries_by_date:
        return None
    mood_scores, energy_scores, stress_scores = [], [], []
    all_themes, all_emotions, all_avoidance, all_cognitive = [], [], [], []
    notable_quotes = []
    templates_count = {}
    daily_mood = {}
    total_entries = 0
    for date_str, entries in entries_by_date.items():
        for entry in entries:
            total_entries += 1
            template = str(entry.get("template", ""))
            templates_count[template] = templates_count.get(template, 0) + 1
            m = entry.get("enriched_mood")
            e = entry.get("enriched_energy")
            s = entry.get("enriched_stress")
            if m is not None:
                mood_scores.append(float(m))
                daily_mood.setdefault(date_str, []).append(float(m))
            if e is not None:
                energy_scores.append(float(e))
            if s is not None:
                stress_scores.append(float(s))
            if m is None:
                for field in ("morning_mood", "day_rating"):
                    val = entry.get(field)
                    if val is not None:
                        mood_scores.append(float(val))
                        daily_mood.setdefault(date_str, []).append(float(val))
                        break
            if e is None:
                for field in ("morning_energy", "energy_eod"):
                    val = entry.get(field)
                    if val is not None:
                        energy_scores.append(float(val))
                        break
            if s is None:
                val = entry.get("stress_level")
                if val is not None:
                    stress_scores.append(float(val))
            for t in entry.get("enriched_themes") or []:
                all_themes.append(str(t))
            for em in entry.get("enriched_emotions") or []:
                all_emotions.append(str(em))
            for av in entry.get("enriched_avoidance_flags") or []:
                all_avoidance.append(str(av))
            for cp in entry.get("enriched_cognitive_patterns") or []:
                all_cognitive.append(str(cp))
            q = entry.get("enriched_notable_quote")
            if q:
                notable_quotes.append({"date": date_str, "quote": str(q)})
    if total_entries == 0:
        return None
    theme_freq = defaultdict(int)
    for t in all_themes:
        theme_freq[t] += 1
    emotion_freq = defaultdict(int)
    for em in all_emotions:
        emotion_freq[em] += 1
    daily_mood_avg = {d: round(sum(v) / len(v), 1) for d, v in daily_mood.items() if v}
    best_day = max(daily_mood_avg.items(), key=lambda x: x[1], default=(None, None))
    worst_day = min(daily_mood_avg.items(), key=lambda x: x[1], default=(None, None))
    return {
        "mood_avg": avg(mood_scores),
        "energy_avg": avg(energy_scores),
        "stress_avg": avg(stress_scores),
        "entries": total_entries,
        "days_journaled": len(entries_by_date),
        "top_themes": sorted(theme_freq.items(), key=lambda x: -x[1])[:6],
        "top_emotions": sorted(emotion_freq.items(), key=lambda x: -x[1])[:6],
        "avoidance_flags": list(dict.fromkeys(all_avoidance))[:5],
        "cognitive_patterns": list(dict.fromkeys(all_cognitive))[:5],
        "notable_quotes": notable_quotes[:3],
        "best_mood_day": {"date": best_day[0], "score": best_day[1]} if best_day[0] else None,
        "worst_mood_day": {"date": worst_day[0], "score": worst_day[1]} if worst_day[0] else None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# CHARACTER SHEET EXTRACTION (v2.71.0)
# ══════════════════════════════════════════════════════════════════════════════


def ex_character_sheet(recs_dict):
    """Extract weekly character sheet summary from pre-computed records."""
    if not recs_dict:
        return None

    pillar_order = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
    tier_order = ["Foundation", "Momentum", "Discipline", "Mastery", "Elite"]
    dates = sorted(recs_dict.keys())
    latest = recs_dict[dates[-1]] if dates else {}
    earliest = recs_dict[dates[0]] if dates else {}

    levels = [recs_dict[d].get("character_level", 0) for d in dates]
    start_level = levels[0] if levels else 0
    end_level = levels[-1] if levels else 0

    all_events = []
    for d in dates:
        for ev in recs_dict[d].get("level_events", []):
            all_events.append({**ev, "date": d})

    pillar_summary = {}
    for p in pillar_order:
        start_pd = earliest.get(f"pillar_{p}") or {}
        end_pd = latest.get(f"pillar_{p}") or {}
        xp_earned = sum((recs_dict[d].get(f"pillar_{p}") or {}).get("xp_delta", 0) for d in dates)
        raw_scores = [(recs_dict[d].get(f"pillar_{p}") or {}).get("raw_score") for d in dates]
        raw_scores = [r for r in raw_scores if r is not None]
        avg_raw = round(sum(raw_scores) / len(raw_scores), 1) if raw_scores else None

        pillar_summary[p] = {
            "start_level": start_pd.get("level", 0),
            "end_level": end_pd.get("level", 0),
            "level_delta": end_pd.get("level", 0) - start_pd.get("level", 0),
            "tier": end_pd.get("tier", "Foundation"),
            "tier_emoji": end_pd.get("tier_emoji", "\U0001f528"),
            "xp_earned": xp_earned,
            "avg_raw": avg_raw,
        }

    # Closest to next tier transition
    closest_to_tier = None
    min_gap = 999
    for p in pillar_order:
        end_pd = latest.get(f"pillar_{p}") or {}
        level = end_pd.get("level", 0)
        tier = end_pd.get("tier", "Foundation")
        tier_idx = tier_order.index(tier) if tier in tier_order else 0
        if tier_idx < len(tier_order) - 1:
            next_min = [1, 21, 41, 61, 81][tier_idx + 1]
            gap = next_min - level
            if 0 < gap < min_gap:
                min_gap = gap
                closest_to_tier = {
                    "pillar": p,
                    "current_level": level,
                    "current_tier": tier,
                    "next_tier": tier_order[tier_idx + 1],
                    "levels_needed": gap,
                }

    return {
        "character_level_start": start_level,
        "character_level_end": end_level,
        "character_level_delta": end_level - start_level,
        "character_tier": latest.get("character_tier", "Foundation"),
        "character_tier_emoji": latest.get("character_tier_emoji", "\U0001f528"),
        "character_xp": latest.get("character_xp", 0),
        "pillar_summary": pillar_summary,
        "events": all_events,
        "closest_to_tier": closest_to_tier,
        "days_with_data": len(dates),
        "active_effects": latest.get("active_effects", []),
    }


# ══════════════════════════════════════════════════════════════════════════════
# TRAINING LOAD (Banister)
# ══════════════════════════════════════════════════════════════════════════════


def compute_banister(strava_60d):
    # #490: one Banister implementation — digest_utils scores activities on the shared
    # TSS-like scale (walks count), so the digest's form bands mean the same thing as
    # computed_metrics.
    return compute_banister_from_dict(strava_60d)


# ══════════════════════════════════════════════════════════════════════════════
# 4-WEEK TRENDS
# ══════════════════════════════════════════════════════════════════════════════


def compute_4week_trends(weekly_data):
    """Given 4 weeks of extracted data (newest first), compute trend arrows."""
    trends = {}
    for metric, source, field in [
        ("weight", "withings", "weight_avg"),
        ("hrv", "whoop", "hrv_avg"),
        ("recovery", "whoop", "recovery_avg"),
        ("sleep", "sleep", "score_avg"),
        ("rhr", "whoop", "rhr_avg"),
        ("day_grade", "day_grades", "avg_score"),
    ]:
        vals = []
        for wk in weekly_data.get(source, []):
            vals.append(wk.get(field) if wk else None)
        v = [x for x in vals if x is not None]
        if len(v) < 2:
            trends[metric] = "→"
        else:
            slope = v[0] - v[-1]
            trends[metric] = "→" if abs(slope) < 0.5 else ("↑" if slope > 0 else "↓")
    return trends


def ex_nutrition_last_log_absence(table, user_id, genesis, today, logger):
    """#2387 (ADR-104): what the digest may honestly say about an unlogged nutrition week.

    One descending query for the newest macrofactor ``DATE#`` record — the source's own
    data, not a hand-typed date. Three honest answers, in the #2382 vocabulary
    (``lambdas/ai/behavior_logs.py``: a stopped log and a never-logged window are
    different sentences):

      ``{"last_log": "YYYY-MM-DD", "days_ago": N}`` — he logged this cycle and stopped;
      ``{"last_log": None}`` — KNOWN never-logged-this-cycle: no record at all, or the
          newest one predates the cycle genesis. Deliberately day-count-free — a count
          measured against the cycle window would fabricate a transition that never
          happened (the six-coach-card defect, #2382/#2394);
      ``{}`` — the lookup itself failed. Unknown licenses nothing (#2056 semantics), so
          the renderer states only the week, never the cycle.
    """
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
            ExpressionAttributeValues={":pk": f"USER#{user_id}#SOURCE#macrofactor", ":pfx": "DATE#"},
            ScanIndexForward=False,
            Limit=1,
            ProjectionExpression="sk, #d",
            ExpressionAttributeNames={"#d": "date"},  # `date` is a DDB reserved word
        )
        items = resp.get("Items") or []
    except Exception as e:  # noqa: BLE001 — an absence line must never sink the digest
        logger.info(f"[#2387] nutrition last-log lookup unavailable: {e}")
        return {}
    if not items:
        return {"last_log": None}
    it = items[0]
    last = str(it.get("date") or str(it.get("sk", "")).replace("DATE#", ""))[:10]
    if not last or last < genesis:
        return {"last_log": None}
    try:
        days_ago = (today - datetime.strptime(last, "%Y-%m-%d").date()).days
    except ValueError:
        return {}
    return {"last_log": last, "days_ago": days_ago}
