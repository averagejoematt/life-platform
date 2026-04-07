# flake8: noqa — paste-in helper, not a standalone module
# ==============================================================================
# BUDDY ACCOUNTABILITY PAGE — DATA GENERATOR (v2.56.0)
# ==============================================================================
# Paste this function into daily_brief_lambda.py (before the HANDLER section).
# Then add this call to lambda_handler, after write_dashboard_json / write_clinical_json:
#
#     write_buddy_json(data, profile, yesterday)
#
# Generates buddy/data.json for buddy.averagejoematt.com
# Uses existing helpers: fetch_range, safe_float, d2f, S3_BUCKET, s3
# ==============================================================================

BUDDY_LOOKBACK_DAYS = 7


def _buddy_days_since(date_str, ref_date):
    """Days between a YYYY-MM-DD string and a date object."""
    if not date_str:
        return 99
    try:
        from datetime import datetime as _dt
        d = _dt.strptime(date_str, "%Y-%m-%d").date() if isinstance(date_str, str) else date_str
        return (ref_date - d).days
    except Exception:
        return 99


def _buddy_friendly_date(date_str):
    """Convert YYYY-MM-DD to 'Mon Feb 27' style."""
    try:
        from datetime import datetime as _dt
        d = _dt.strptime(date_str, "%Y-%m-%d")
        return d.strftime("%a %b %-d")
    except Exception:
        return date_str or ""


def _buddy_friendly_name(name, sport_type):
    """Make activity names more readable."""
    friendly = {
        "Walk": "Walk", "Run": "Run", "Ride": "Bike Ride",
        "VirtualRide": "Indoor Ride", "WeightTraining": "Weight Training",
        "Hike": "Hike", "Yoga": "Yoga", "Swim": "Swim",
    }
    if name == sport_type or not name:
        return friendly.get(sport_type, sport_type)
    return name


def _dedup_activities(activities):
    """
    Remove duplicate activities from multi-device recording.
    WHOOP and Garmin both push to Strava, so the same session appears twice.
    Strategy: if two activities overlap in time (start within 15 min, duration
    within 40%), keep the one with more data (Garmin > WHOOP).
    """
    if len(activities) <= 1:
        return activities

    from datetime import datetime as _dt

    def parse_start(a):
        try:
            return _dt.strptime(a.get("start_date", "")[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            return None

    def device_priority(a):
        """Higher = better data source."""
        dev = (a.get("device_name") or "").lower()
        if "garmin" in dev:
            return 3
        if "apple" in dev:
            return 2
        if "whoop" in dev:
            return 1
        return 0

    # Sort by start time
    sorted_acts = sorted(activities, key=lambda a: a.get("start_date", ""))
    keep = []
    skip_ids = set()

    for i, a in enumerate(sorted_acts):
        aid = a.get("strava_id", str(i))
        if aid in skip_ids:
            continue

        start_a = parse_start(a)
        dur_a = float(a.get("moving_time_seconds") or 0)

        # Check for overlapping activities
        for j in range(i + 1, len(sorted_acts)):
            b = sorted_acts[j]
            bid = b.get("strava_id", str(j))
            if bid in skip_ids:
                continue

            start_b = parse_start(b)
            dur_b = float(b.get("moving_time_seconds") or 0)

            if not start_a or not start_b:
                continue

            # Check time proximity (within 15 min)
            gap = abs((start_b - start_a).total_seconds())
            if gap > 900:  # 15 minutes
                break  # sorted, so no more overlaps

            # Check duration similarity (within 40%)
            if dur_a > 0 and dur_b > 0:
                ratio = min(dur_a, dur_b) / max(dur_a, dur_b)
                if ratio < 0.6:
                    continue  # too different in length

            # Duplicate found — keep higher priority device
            if device_priority(a) >= device_priority(b):
                skip_ids.add(bid)
            else:
                skip_ids.add(aid)
                break  # a is being removed, stop checking

        if aid not in skip_ids:
            keep.append(a)

    return keep


def write_buddy_json(data, profile, yesterday):
    """Generate buddy/data.json for accountability partner page."""
    try:
        today_dt = datetime.now(timezone.utc).date()
        lookback_start = (today_dt - timedelta(days=BUDDY_LOOKBACK_DAYS)).isoformat()
        lookback_end = today_dt.isoformat()

        # ── Gather 7-day data using existing fetch_range helper ──
        mf_days = fetch_range("macrofactor", lookback_start, lookback_end)
        strava_days = fetch_range("strava", lookback_start, lookback_end)
        habit_days = fetch_range("habitify", lookback_start, lookback_end)
        weight_days = fetch_range("withings", lookback_start, lookback_end)

        # ── Food Logging Signal ──
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

        days_since_food = _buddy_days_since(latest_mf_date, today_dt)
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

        # Food snapshot
        food_snapshot = ""
        if total_cals:
            avg_cals = int(sum(total_cals) / len(total_cals))
            if total_protein:
                avg_prot = int(sum(total_protein) / len(total_protein))
                food_snapshot = f"Averaging about {avg_cals:,} calories per day this week with {avg_prot}g protein."
            else:
                food_snapshot = f"Averaging about {avg_cals:,} calories per day this week."

        # ── Exercise Signal ──
        # "This week" = Monday–today, resets every Monday
        monday = today_dt - timedelta(days=today_dt.weekday())  # Mon=0
        monday_str = monday.isoformat()
        day_of_week = today_dt.strftime("%A")  # e.g. "Tuesday"

        activities = []       # all 7-day activities (for highlights)
        week_activities = []  # Monday–today only (for count/status)
        latest_activity_date = None

        for item in strava_days:
            date_str = (item.get("sk") or "").replace("DATE#", "")
            raw_acts = item.get("activities", [])
            # Dedup multi-device recordings (WHOOP + Garmin → Strava)
            acts = _dedup_activities(raw_acts) if isinstance(raw_acts, list) else []
            if isinstance(acts, list):
                for a in acts:
                    sport = a.get("sport_type") or a.get("type", "Activity")
                    name = a.get("name", sport)
                    dist = safe_float(a, "distance_miles")
                    moving_sec = safe_float(a, "moving_time_seconds")
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
        days_since_exercise = _buddy_days_since(latest_activity_date, today_dt)
        days_into_week = today_dt.weekday() + 1  # Mon=1, Tue=2, ..., Sun=7

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
            # Monday or Tuesday with no sessions yet — not alarming
            exercise_status = "yellow"
            exercise_text = f"No sessions yet this week ({day_of_week})"
        else:
            exercise_status = "red"
            exercise_text = f"No exercise this week — last session {days_since_exercise} days ago"

        # Sort newest first, keep top 4
        activities.sort(key=lambda x: x.get("sort_date", ""), reverse=True)
        activity_highlights = [
            {"name": a["name"], "detail": a["detail"], "date": a["date"]}
            for a in activities[:4]
        ]

        # ── Routine Signal (Habits) ──
        latest_habit_date = None
        habit_logged_count = 0

        for item in habit_days:
            date_str = (item.get("sk") or "").replace("DATE#", "")
            completed = safe_float(item, "completed_count") or safe_float(item, "total_completed")
            if completed and completed > 0:
                habit_logged_count += 1
                if not latest_habit_date or date_str > latest_habit_date:
                    latest_habit_date = date_str

        days_since_habits = _buddy_days_since(latest_habit_date, today_dt)

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

        # ── Weight Signal ──
        weights = []
        for item in weight_days:
            date_str = (item.get("sk") or "").replace("DATE#", "")
            w = safe_float(item, "weight_lbs")
            if w and w > 100:
                weights.append((date_str, w))

        weights.sort(key=lambda x: x[0])
        latest_weight_date = weights[-1][0] if weights else None
        days_since_weigh = _buddy_days_since(latest_weight_date, today_dt)

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

        # ── Compute Beacon ──
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

        # ── Journey Stats ──
        journey_start = profile.get("journey_start_date", "2026-04-01")
        goal_weight = safe_float(profile, "goal_weight_lbs") or 185
        start_weight = safe_float(profile, "start_weight_lbs") or 307

        try:
            journey_days = (today_dt - datetime.strptime(journey_start, "%Y-%m-%d").date()).days
        except Exception:
            journey_days = 0

        current_weight = weights[-1][1] if weights else start_weight
        lost_lbs = round(start_weight - current_weight, 1)
        total_to_lose = start_weight - goal_weight
        pct_complete = round((lost_lbs / total_to_lose) * 100, 0) if total_to_lose > 0 else 0

        # ── Friendly timestamp ──
        try:
            now_pt = datetime.now(timezone.utc) - timedelta(hours=8)
            day_name = now_pt.strftime("%A")
            tod = "morning" if now_pt.hour < 12 else "afternoon" if now_pt.hour < 17 else "evening"
            month_day = now_pt.strftime("%B %-d")
            time_pt = now_pt.strftime("%-I:%M %p").lower().replace(" ", "")  # "9:15am"
            friendly_time = f"{day_name} {tod}, {month_day} at {time_pt} PT"
        except Exception:
            friendly_time = yesterday

        # ── Assemble & Write ──
        buddy_data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
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
        }

        s3.put_object(
            Bucket=S3_BUCKET,
            Key="buddy/data.json",
            Body=json.dumps(buddy_data, default=str),
            ContentType="application/json",
            CacheControl="max-age=300",
        )
        print("[INFO] Buddy JSON written to s3://" + S3_BUCKET + "/buddy/data.json")

    except Exception as e:
        print("[WARN] Buddy JSON write failed: " + str(e))
