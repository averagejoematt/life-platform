"""
Dashboard Refresh Lambda — Lightweight intraday data updater.

Runs at 2 PM and 6 PM PT (in addition to the 10 AM Daily Brief).
Re-queries ONLY intraday-changing sources and merges into the existing
dashboard/data.json. Preserves AI-computed fields (day_grade TL;DR, BoD insight,
character sheet) from the morning brief.

Also re-computes buddy/data.json with fresh signals.

v1.0.0 — 2026-03-03
"""
import json
import os
import boto3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# -- Configuration --
_REGION    = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET  = os.environ["S3_BUCKET"]
USER_ID    = os.environ["USER_ID"]

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
BUDDY_LOOKBACK_DAYS = 7

# -- AWS clients --
dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)
s3       = boto3.client("s3", region_name=_REGION)


# ==============================================================================
# HELPERS (shared with daily_brief_lambda.py)
# ==============================================================================

def d2f(obj):
    """Convert DynamoDB Decimals to floats."""
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def safe_float(rec, field, default=None):
    if rec and field in rec:
        try: return float(rec[field])
        except Exception: return default
    return default


def fetch_date(source, date_str):
    try:
        r = table.get_item(Key={"pk": USER_PREFIX + source, "sk": "DATE#" + date_str})
        return d2f(r.get("Item"))
    except Exception:
        return None


def fetch_range(source, start, end):
    try:
        r = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": USER_PREFIX + source,
                ":s": "DATE#" + start,
                ":e": "DATE#" + end,
            })
        return [d2f(i) for i in r.get("Items", [])]
    except Exception:
        return []


def _normalize_whoop_sleep(item):
    """Map Whoop sleep field names to common schema."""
    if not item:
        return item
    out = dict(item)
    if "sleep_quality_score" in out and "sleep_score" not in out:
        out["sleep_score"] = out["sleep_quality_score"]
    if "sleep_efficiency_percentage" in out and "sleep_efficiency_pct" not in out:
        out["sleep_efficiency_pct"] = out["sleep_efficiency_percentage"]
    total = safe_float(out, "sleep_duration_hours") or 0
    if total > 0:
        for stage, field in [("deep_hours", "deep_pct"), ("rem_hours", "rem_pct"),
                             ("light_hours", "light_pct"), ("awake_hours", "awake_pct")]:
            if stage in out and field not in out:
                out[field] = round(float(out[stage]) / total * 100, 1)
    return out


def get_current_phase(profile, current_weight_lbs):
    phases = profile.get("weight_loss_phases", [])
    for p in phases:
        if current_weight_lbs >= p.get("end_lbs", 0):
            return p
    return phases[-1] if phases else None


def _dedup_activities(activities):
    """Remove WHOOP+Garmin duplicates from Strava activities."""
    if len(activities) <= 1:
        return activities

    def parse_start(a):
        try:
            s = a.get("start_date") or a.get("start_date_local", "")
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    def dur_sec(a):
        return safe_float(a, "moving_time_seconds") or safe_float(a, "elapsed_time_seconds") or 0

    def richness(a):
        score = 0
        if a.get("average_heartrate"): score += 1
        if a.get("max_heartrate"): score += 1
        if a.get("calories"): score += 1
        if a.get("average_speed"): score += 1
        if a.get("total_elevation_gain"): score += 1
        if a.get("average_cadence"): score += 1
        return score

    kept = []
    used = set()
    sorted_acts = sorted(activities, key=lambda a: richness(a), reverse=True)
    for i, a in enumerate(sorted_acts):
        if i in used:
            continue
        start_a = parse_start(a)
        dur_a = dur_sec(a)
        for j in range(i + 1, len(sorted_acts)):
            if j in used:
                continue
            start_b = parse_start(sorted_acts[j])
            dur_b = dur_sec(sorted_acts[j])
            if start_a and start_b and abs((start_a - start_b).total_seconds()) < 900:
                if dur_a > 0 and dur_b > 0:
                    ratio = min(dur_a, dur_b) / max(dur_a, dur_b)
                    if ratio > 0.4:
                        used.add(j)
        kept.append(a)
    return kept


def _buddy_days_since(date_str, ref_date):
    if not date_str:
        return 99
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date() if isinstance(date_str, str) else date_str
        return (ref_date - d).days
    except Exception:
        return 99


def _buddy_friendly_date(date_str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return d.strftime("%a %b %-d")
    except Exception:
        return date_str or ""


def _buddy_friendly_name(name, sport_type):
    friendly = {
        "Walk": "Walk", "Run": "Run", "Ride": "Bike Ride",
        "VirtualRide": "Indoor Ride", "WeightTraining": "Weight Training",
        "Hike": "Hike", "Yoga": "Yoga", "Swim": "Swim",
    }
    if name == sport_type or not name:
        return friendly.get(sport_type, sport_type)
    return name


def _build_avatar_data(character_sheet, profile, current_weight=None):
    """Build avatar display state from character sheet + weight data."""
    if not character_sheet:
        return None

    tier = (character_sheet.get("character_tier") or "Foundation").lower().replace(" ", "_")
    pillar_names = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]

    start_w = profile.get("journey_start_weight_lbs", 302)
    goal_w = profile.get("goal_weight_lbs", 185)
    cw = current_weight or start_w
    if start_w != goal_w:
        composition_score = max(0, min(100, ((start_w - cw) / (start_w - goal_w)) * 100))
    else:
        composition_score = 100
    if composition_score >= 75:
        body_frame = 3
    elif composition_score >= 36:
        body_frame = 2
    else:
        body_frame = 1

    badges = {}
    for pn in pillar_names:
        pd = character_sheet.get(f"pillar_{pn}", {})
        lvl = pd.get("level", 1) if pd else 1
        if lvl >= 61:
            badges[pn] = "bright"
        elif lvl >= 41:
            badges[pn] = "dim"
        else:
            badges[pn] = "hidden"

    raw_effects = character_sheet.get("active_effects", [])
    effect_names = [e.get("name", "").lower().replace(" ", "_") for e in raw_effects if e.get("name")]

    sleep_lvl = (character_sheet.get("pillar_sleep") or {}).get("level", 1)
    move_lvl = (character_sheet.get("pillar_movement") or {}).get("level", 1)
    meta_lvl = (character_sheet.get("pillar_metabolic") or {}).get("level", 1)
    cons_lvl = (character_sheet.get("pillar_consistency") or {}).get("level", 1)
    expressions = {
        "eyes": "bright" if sleep_lvl >= 61 else ("dim" if sleep_lvl < 35 else "normal"),
        "posture": "forward" if move_lvl >= 61 else "normal",
        "skin_tone": "warm" if meta_lvl >= 61 else ("cool" if meta_lvl < 35 else "normal"),
        "ground": "solid" if cons_lvl >= 61 else ("faded" if cons_lvl < 35 else "normal"),
    }

    char_lvl = character_sheet.get("character_level", 1)
    all_discipline = all(badges[p] != "hidden" for p in pillar_names)
    elite_crown = char_lvl >= 81
    alignment_ring = all_discipline and all(badges[p] == "bright" for p in pillar_names)

    return {
        "tier": tier, "body_frame": body_frame,
        "composition_score": round(composition_score, 1),
        "badges": badges, "effects": effect_names,
        "expressions": expressions,
        "elite_crown": elite_crown, "alignment_ring": alignment_ring,
    }


def load_profile():
    """Load profile from S3."""
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key="config/profile.json")
        return json.loads(resp["Body"].read().decode("utf-8"))
    except Exception as e:
        print(f"[WARN] Failed to load profile: {e}")
        return {}


def read_existing_json(key):
    """Read existing JSON from S3."""
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key=key)
        return json.loads(resp["Body"].read().decode("utf-8"))
    except Exception:
        return None


# ==============================================================================
# DASHBOARD REFRESH
# ==============================================================================

def refresh_dashboard(profile, yesterday, today):
    """Re-query intraday sources and merge into existing dashboard JSON."""
    existing = read_existing_json("dashboard/data.json")
    if not existing:
        print("[WARN] No existing dashboard/data.json — skipping dashboard refresh")
        return

    # --- Re-query intraday-changing sources ---

    # Weight (may have weighed in later in the day)
    withings_recent = fetch_range("withings", (today - timedelta(days=7)).isoformat(), today.isoformat())
    latest_weight = None
    for w in reversed(withings_recent):
        wt = safe_float(w, "weight_lbs")
        if wt:
            latest_weight = wt
            break

    withings_14d = fetch_range("withings", (today - timedelta(days=14)).isoformat(), today.isoformat())
    week_ago_weight = None
    target_date = (today - timedelta(days=7)).isoformat()
    for w in withings_14d:
        d = w.get("sk", "").replace("DATE#", "")
        if d <= target_date:
            wt = safe_float(w, "weight_lbs")
            if wt:
                week_ago_weight = wt

    if latest_weight:
        weekly_delta = round(latest_weight - week_ago_weight, 1) if week_ago_weight else None
        phase = get_current_phase(profile, latest_weight)
        phase_name = phase.get("name", "") if phase else ""
        journey_start = profile.get("journey_start_weight_lbs", 302)
        goal_weight = profile.get("goal_weight_lbs", 185)
        total_to_lose = journey_start - goal_weight
        journey_pct = round((journey_start - latest_weight) / total_to_lose * 100) if total_to_lose > 0 else 0

        weight_sparkline = []
        weight_by_date = {}
        for w in withings_14d:
            d = w.get("sk", "").replace("DATE#", "")
            wt = safe_float(w, "weight_lbs")
            if wt:
                weight_by_date[d] = wt
        last_w = None
        for i in range(6, -1, -1):
            d = (today - timedelta(days=i + 1)).isoformat()
            if d in weight_by_date:
                last_w = weight_by_date[d]
            if last_w is not None:
                weight_sparkline.append(round(last_w, 1))

        existing["weight"] = {
            "current": latest_weight,
            "weekly_delta": weekly_delta,
            "phase": phase_name,
            "journey_pct": journey_pct,
            "sparkline": weight_sparkline,
        }

    # Glucose (CGM data accumulates throughout day)
    apple = fetch_date("apple_health", yesterday)
    apple_today = fetch_date("apple_health", today.isoformat())
    # Use today's data if available (more current), else yesterday's
    glucose_src = apple_today or apple
    if glucose_src:
        glucose_avg = safe_float(glucose_src, "blood_glucose_avg")
        glucose_tir = safe_float(glucose_src, "time_in_range_pct")
        glucose_std = safe_float(glucose_src, "blood_glucose_std")
        glucose_min = safe_float(glucose_src, "blood_glucose_min")
        if glucose_avg:
            existing["glucose"]["avg"] = glucose_avg
        if glucose_tir:
            existing["glucose"]["tir_pct"] = glucose_tir
        if glucose_std:
            existing["glucose"]["variability"] = glucose_std
        if glucose_min:
            existing["glucose"]["fasting_proxy"] = glucose_min

    # Zone 2 (may have done an afternoon workout)
    try:
        week_start = today - timedelta(days=today.weekday())
        strava_week = fetch_range("strava", week_start.isoformat(), today.isoformat())
        max_hr = profile.get("max_heart_rate", 184)
        z2_lo = max_hr * 0.60
        z2_hi = max_hr * 0.70
        z2_total = 0.0
        for day_rec in strava_week:
            for act in (day_rec.get("activities") or []):
                avg_hr = safe_float(act, "average_heartrate")
                dur_s = safe_float(act, "moving_time_seconds") or 0
                if avg_hr and z2_lo <= avg_hr <= z2_hi:
                    z2_total += dur_s / 60
        existing["zone2_min"] = round(z2_total)
    except Exception:
        pass

    # TSB (training stress balance — may have logged a workout)
    try:
        strava_60d = fetch_range("strava", (today - timedelta(days=60)).isoformat(), today.isoformat())
        if strava_60d:
            day_loads = {}
            for day_rec in strava_60d:
                date_str = day_rec.get("sk", "").replace("DATE#", "")
                daily_load = 0
                for act in (day_rec.get("activities") or []):
                    dur_min = (safe_float(act, "moving_time_seconds") or 0) / 60
                    avg_hr = safe_float(act, "average_heartrate") or 0
                    if dur_min > 0 and avg_hr > 0:
                        daily_load += dur_min * (avg_hr / 180)
                    elif dur_min > 0:
                        daily_load += dur_min * 0.5
                if date_str:
                    day_loads[date_str] = daily_load

            atl = 0
            ctl = 0
            for i in range(60, 0, -1):
                d = (today - timedelta(days=i)).isoformat()
                load = day_loads.get(d, 0)
                atl = atl + (load - atl) * (2 / 8)
                ctl = ctl + (load - ctl) * (2 / 43)
            existing["tsb"] = round(ctl - atl, 1)
    except Exception:
        pass

    # Source count refresh
    source_data = {
        "whoop": fetch_date("whoop", yesterday),
        "macrofactor": fetch_date("macrofactor", yesterday),
        "habitify": fetch_date("habitify", yesterday),
        "apple": apple,
        "strava": fetch_date("strava", yesterday),
        "garmin": fetch_date("garmin", yesterday),
    }
    sources_active = sum(1 for v in source_data.values() if v)
    existing["sources_active"] = sources_active

    # Update timestamp
    existing["generated_at"] = datetime.now(timezone.utc).isoformat()
    existing["refreshed_at"] = datetime.now(timezone.utc).isoformat()
    existing["refresh_type"] = "intraday"

    # Write to S3
    s3.put_object(
        Bucket=S3_BUCKET,
        Key="dashboard/data.json",
        Body=json.dumps(existing, default=str),
        ContentType="application/json",
        CacheControl="max-age=300",
    )
    print("[INFO] Dashboard JSON refreshed at " + existing["refreshed_at"])


# ==============================================================================
# BUDDY REFRESH (full recompute — no AI, cheap)
# ==============================================================================

def refresh_buddy(profile, yesterday, today):
    """Re-compute buddy/data.json with fresh signal data."""
    try:
        lookback_start = (today - timedelta(days=BUDDY_LOOKBACK_DAYS)).isoformat()
        lookback_end = today.isoformat()

        mf_days = fetch_range("macrofactor", lookback_start, lookback_end)
        strava_days = fetch_range("strava", lookback_start, lookback_end)
        habit_days = fetch_range("habitify", lookback_start, lookback_end)
        weight_days = fetch_range("withings", lookback_start, lookback_end)

        # --- Food Logging Signal ---
        mf_logged_dates = set()
        latest_mf_date = None
        total_cals = []
        total_protein = []
        for item in mf_days:
            date_str = (item.get("sk") or "").replace("DATE#", "")
            cals = safe_float(item, "total_calories_kcal") or safe_float(item, "calories") or safe_float(item, "energy_kcal")
            prot = safe_float(item, "total_protein_g") or safe_float(item, "protein_g") or safe_float(item, "protein")
            if cals and cals > 200:
                mf_logged_dates.add(date_str)
                total_cals.append(cals)
                if prot:
                    total_protein.append(prot)
                if not latest_mf_date or date_str > latest_mf_date:
                    latest_mf_date = date_str

        days_since_food = _buddy_days_since(latest_mf_date, today)
        food_logged_count = len(mf_logged_dates)
        if days_since_food <= 1 and food_logged_count >= 5:
            food_status = "green"
            food_text = f"Consistent — logged meals {food_logged_count} of last {BUDDY_LOOKBACK_DAYS} days"
        elif days_since_food <= 2 and food_logged_count >= 3:
            food_status = "green"
            food_text = f"Logging food — {food_logged_count} of last {BUDDY_LOOKBACK_DAYS} days tracked"
        elif days_since_food <= 3:
            food_status = "yellow"
            food_text = f"Last food log was {days_since_food} days ago"
        else:
            food_status = "red"
            food_text = f"No food logged in {days_since_food} days — might be off track"

        food_snapshot = ""
        if total_cals:
            avg_cals = int(sum(total_cals) / len(total_cals))
            if total_protein:
                avg_prot = int(sum(total_protein) / len(total_protein))
                food_snapshot = f"Averaging about {avg_cals:,} calories per day this week with {avg_prot}g protein."
            else:
                food_snapshot = f"Averaging about {avg_cals:,} calories per day this week."

        # --- Exercise Signal ---
        monday = today - timedelta(days=today.weekday())
        monday_str = monday.isoformat()
        day_of_week = today.strftime("%A")

        activities = []
        week_activities = []
        latest_activity_date = None
        for item in strava_days:
            date_str = (item.get("sk") or "").replace("DATE#", "")
            raw_acts = item.get("activities", [])
            acts = _dedup_activities(raw_acts) if isinstance(raw_acts, list) else []
            if isinstance(acts, list):
                for a in acts:
                    sport = a.get("sport_type") or a.get("type", "Activity")
                    name = a.get("name", sport)
                    dist = safe_float(a, "distance_miles")
                    moving_sec = safe_float(a, "moving_time_seconds") or 0
                    dur_min = int(moving_sec / 60) if moving_sec else None
                    detail_parts = []
                    if dist and dist > 0.1:
                        detail_parts.append(f"{dist:.1f} mi")
                    if dur_min:
                        detail_parts.append(f"{dur_min} min")
                    entry = {
                        "name": _buddy_friendly_name(name, sport),
                        "detail": ", ".join(detail_parts) if detail_parts else sport,
                        "date": _buddy_friendly_date(date_str),
                        "sort_date": date_str,
                    }
                    activities.append(entry)
                    if date_str >= monday_str:
                        week_activities.append(entry)
                    if not latest_activity_date or date_str > latest_activity_date:
                        latest_activity_date = date_str

        week_count = len(week_activities)
        days_since_exercise = _buddy_days_since(latest_activity_date, today)
        days_into_week = today.weekday() + 1

        if week_count >= 3:
            exercise_status = "green"
            exercise_text = f"Active — {week_count} sessions this week"
        elif week_count >= 1 and days_since_exercise <= 2:
            exercise_status = "green"
            exercise_text = f"{week_count} session{'s' if week_count != 1 else ''} so far this week"
        elif week_count >= 1:
            exercise_status = "yellow"
            exercise_text = f"{week_count} session{'s' if week_count != 1 else ''} this week, last was {days_since_exercise} days ago"
        elif days_into_week <= 2:
            exercise_status = "yellow"
            exercise_text = f"No sessions yet this week ({day_of_week})"
        else:
            exercise_status = "red"
            exercise_text = f"No exercise this week — last session {days_since_exercise} days ago"

        activities.sort(key=lambda x: x.get("sort_date", ""), reverse=True)
        activity_highlights = [
            {"name": a["name"], "detail": a["detail"], "date": a["date"]}
            for a in activities[:4]
        ]

        # --- Routine Signal ---
        latest_habit_date = None
        habit_logged_count = 0
        for item in habit_days:
            date_str = (item.get("sk") or "").replace("DATE#", "")
            completed = safe_float(item, "completed_count") or safe_float(item, "total_completed")
            if completed and completed > 0:
                habit_logged_count += 1
                if not latest_habit_date or date_str > latest_habit_date:
                    latest_habit_date = date_str

        days_since_habits = _buddy_days_since(latest_habit_date, today)
        if days_since_habits <= 1 and habit_logged_count >= 4:
            routine_status = "green"
            routine_text = "In his routine — habits tracked consistently"
        elif days_since_habits <= 2:
            routine_status = "green"
            routine_text = "Routine is holding, habits being logged"
        elif days_since_habits <= 3:
            routine_status = "yellow"
            routine_text = f"Habit tracking quiet for {days_since_habits} days"
        else:
            routine_status = "red"
            routine_text = f"No habit data in {days_since_habits} days — routine may have slipped"

        # --- Weight Signal ---
        weights = []
        for item in weight_days:
            date_str = (item.get("sk") or "").replace("DATE#", "")
            w = safe_float(item, "weight_lbs")
            if w and w > 100:
                weights.append((date_str, w))
        weights.sort(key=lambda x: x[0])
        latest_weight_date = weights[-1][0] if weights else None
        days_since_weigh = _buddy_days_since(latest_weight_date, today)

        if len(weights) >= 2:
            delta = weights[-1][1] - weights[0][1]
            if delta < -0.5:
                weight_status = "green"
                weight_text = "Heading in the right direction"
            elif delta < 0.5:
                weight_status = "green"
                weight_text = "Weight holding steady"
            else:
                weight_status = "yellow"
                weight_text = "Weight ticked up slightly this week"
        elif len(weights) == 1:
            weight_status = "green" if days_since_weigh <= 3 else "yellow"
            weight_text = "Weighed in" + (f" {days_since_weigh} days ago" if days_since_weigh > 1 else " recently")
        else:
            weight_status = "yellow" if days_since_weigh <= 7 else "red"
            weight_text = f"No weigh-in in {days_since_weigh}+ days"

        # --- Beacon ---
        statuses = [food_status, exercise_status, routine_status, weight_status]
        red_count = statuses.count("red")
        yellow_count = statuses.count("yellow")
        if red_count >= 2:
            beacon = "red"
            beacon_label = "Check in on him"
            beacon_summary = "Multiple signals have gone quiet. He might be in a rough stretch."
            prompt = "Time to reach out. Don\u2019t make it about health data \u2014 just ask how he\u2019s really doing. Be direct but kind."
        elif red_count >= 1 or yellow_count >= 2:
            beacon = "yellow"
            beacon_label = "Might be a quiet stretch"
            beacon_summary = "A couple of things have dropped off. Probably fine, but worth a nudge."
            prompt = "A casual check-in would be good. Don\u2019t lead with the health stuff \u2014 just ask how his week\u2019s going."
        else:
            beacon = "green"
            beacon_label = "Matt's doing his thing"
            beacon_summary = "He's logging food, exercising, and sticking to his routine. All good."
            prompt = "No action needed. If you reach out, just be a mate \u2014 talk about life, not health."

        # --- Journey Stats ---
        journey_start = profile.get("journey_start_date", "2026-02-22")
        goal_weight = safe_float(profile, "goal_weight_lbs") or 185
        start_weight = safe_float(profile, "start_weight_lbs") or 302
        try:
            journey_days = (today - datetime.strptime(journey_start, "%Y-%m-%d").date()).days
        except Exception:
            journey_days = 0
        current_weight = weights[-1][1] if weights else start_weight
        lost_lbs = round(start_weight - current_weight, 1)
        total_to_lose = start_weight - goal_weight
        pct_complete = round((lost_lbs / total_to_lose) * 100, 0) if total_to_lose > 0 else 0

        # --- Character sheet (read pre-computed) ---
        character_sheet = fetch_date("character_sheet", yesterday)

        # --- Friendly timestamp ---
        try:
            now_pt = datetime.now(timezone.utc) - timedelta(hours=8)
            day_name = now_pt.strftime("%A")
            tod = "morning" if now_pt.hour < 12 else "afternoon" if now_pt.hour < 17 else "evening"
            month_day = now_pt.strftime("%B %-d")
            time_pt = now_pt.strftime("%-I:%M %p").lower().replace(" ", "")
            friendly_time = f"{day_name} {tod}, {month_day} at {time_pt} PT"
        except Exception:
            friendly_time = yesterday

        buddy_data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "date": yesterday,
            "beacon": beacon,
            "beacon_label": beacon_label,
            "beacon_summary": beacon_summary,
            "prompt_for_tom": prompt,
            "status_lines": [
                {"area": "Food Logging", "status": food_status, "text": food_text},
                {"area": "Exercise", "status": exercise_status, "text": exercise_text},
                {"area": "Routine", "status": routine_status, "text": routine_text},
                {"area": "Weight", "status": weight_status, "text": weight_text},
            ],
            "activity_highlights": activity_highlights,
            "food_snapshot": food_snapshot,
            "journey": {
                "days": journey_days,
                "lost_lbs": lost_lbs,
                "pct_complete": int(pct_complete),
                "goal_lbs": int(goal_weight),
            },
            "last_updated_friendly": friendly_time,
            "character_sheet": {
                "level": character_sheet.get("character_level", 1),
                "tier": character_sheet.get("character_tier"),
                "tier_emoji": character_sheet.get("character_tier_emoji"),
                "events": character_sheet.get("level_events", []),
            } if character_sheet else None,
            "avatar": _build_avatar_data(character_sheet, profile, current_weight),
        }

        s3.put_object(
            Bucket=S3_BUCKET,
            Key="buddy/data.json",
            Body=json.dumps(buddy_data, default=str),
            ContentType="application/json",
            CacheControl="max-age=300",
        )
        print("[INFO] Buddy JSON refreshed")

    except Exception as e:
        print(f"[WARN] Buddy refresh failed: {e}")


# ==============================================================================
# HANDLER
# ==============================================================================

def lambda_handler(event, context):
    """
    Main entry point. Runs as lightweight intraday refresh.
    No AI calls, no email — just data refresh for dashboard + buddy.
    """
    print("[INFO] Dashboard refresh starting")

    profile = load_profile()
    today = datetime.now(timezone.utc).date()
    yesterday = (today - timedelta(days=1)).isoformat()

    refresh_dashboard(profile, yesterday, today)
    refresh_buddy(profile, yesterday, today)

    print("[INFO] Dashboard refresh complete")
    return {"statusCode": 200, "body": "Dashboard refreshed"}
