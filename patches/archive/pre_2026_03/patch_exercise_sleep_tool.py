"""
patch_exercise_sleep_tool.py — Add get_exercise_sleep_correlation tool (v2.12.0)

Patches mcp_server.py with:
  1. New function: tool_get_exercise_sleep_correlation (after get_caffeine_sleep_correlation)
  2. New registry entry (after get_caffeine_sleep_correlation in TOOL_REGISTRY)
  3. Version bump 2.11.0 → 2.12.0
  4. Header update

Idempotent: aborts if tool already exists.

Usage:
    cd ~/Documents/Claude/life-platform
    python3 patch_exercise_sleep_tool.py
"""

import sys

with open("mcp_server.py", "r") as f:
    content = f.read()

# ── Safety check ──────────────────────────────────────────────────────────────
if "get_exercise_sleep_correlation" in content:
    print("SKIP: get_exercise_sleep_correlation already exists in mcp_server.py")
    sys.exit(0)

# ── FUNCTION DEFINITION ──────────────────────────────────────────────────────
FUNCTION_CODE = r'''

# ── Tool: get_exercise_sleep_correlation ─────────────────────────────────────

def tool_get_exercise_sleep_correlation(args):
    """
    Personal exercise timing cutoff finder. Extracts the last exercise end time
    per day from Strava (start_date_local + elapsed_time_seconds), then correlates
    with same-night Eight Sleep metrics. Splits days into time-of-day buckets to
    show where late exercise degrades (or improves) sleep quality.
    Also analyzes exercise intensity (avg HR) as a separate dimension.
    Based on Huberman, Galpin, and Attia: exercise timing is a modifiable lever
    for sleep quality, but the effect is highly individual.
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=179)).strftime("%Y-%m-%d"))
    min_duration_min = int(args.get("min_duration_minutes", 15))
    exclude_types = [t.strip().lower() for t in (args.get("exclude_sport_types") or "").split(",") if t.strip()]

    strava_items = query_source("strava", start_date, end_date)
    es_items     = query_source("eightsleep", start_date, end_date)

    if not strava_items:
        return {"error": "No Strava data for range.", "start_date": start_date, "end_date": end_date}
    if not es_items:
        return {"error": "No Eight Sleep data for range.", "start_date": start_date, "end_date": end_date}

    # Index Eight Sleep by date
    sleep_by_date = {}
    for item in es_items:
        d = item.get("date")
        if d:
            sleep_by_date[d] = item

    # Get user profile for HR zones
    profile = get_profile()
    max_hr = float(profile.get("max_heart_rate", 190))

    def _sf(v):
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def _parse_local_time(dt_str):
        """Extract decimal hour from ISO local datetime string like '2026-02-15T12:55:30Z'."""
        if not dt_str:
            return None
        try:
            # Handle both 'T' separated and other formats
            time_part = dt_str.split("T")[1] if "T" in dt_str else None
            if not time_part:
                return None
            parts = time_part.replace("Z", "").split(":")
            return int(parts[0]) + int(parts[1]) / 60 + (int(parts[2].split(".")[0]) / 3600 if len(parts) > 2 else 0)
        except Exception:
            return None

    def _d2hm(d):
        """Decimal hours → HH:MM string."""
        if d is None:
            return None
        h = int(d) % 24
        m = int(round((d % 1) * 60))
        if m == 60:
            h += 1; m = 0
        return f"{h:02d}:{m:02d}"

    def _classify_intensity(avg_hr):
        """Classify exercise intensity based on % of max HR."""
        if avg_hr is None:
            return "unknown"
        pct = avg_hr / max_hr * 100
        if pct >= 80:
            return "high"
        elif pct >= 65:
            return "moderate"
        else:
            return "low"

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    # ── Extract per-day exercise timing + sleep metrics ──────────────────────
    # All dates with Eight Sleep data form the universe; days without Strava = rest days
    all_dates = sorted(sleep_by_date.keys())
    strava_by_date = {}
    for item in strava_items:
        d = item.get("date")
        if d:
            strava_by_date[d] = item

    daily_rows = []

    for date in all_dates:
        if date < start_date or date > end_date:
            continue

        sleep = sleep_by_date[date]

        # Sleep metrics
        eff     = _sf(sleep.get("sleep_efficiency_pct"))
        deep    = _sf(sleep.get("deep_pct"))
        rem     = _sf(sleep.get("rem_pct"))
        score   = _sf(sleep.get("sleep_score"))
        dur     = _sf(sleep.get("sleep_duration_hours"))
        latency = _sf(sleep.get("time_to_sleep_min"))
        hrv     = _sf(sleep.get("hrv_avg"))

        if eff is None and score is None and deep is None:
            continue

        strava_day = strava_by_date.get(date)
        activities = strava_day.get("activities", []) if strava_day else []

        # Filter activities by duration and excluded types
        valid_acts = []
        for act in activities:
            elapsed = _sf(act.get("elapsed_time_seconds")) or 0
            if elapsed < min_duration_min * 60:
                continue
            sport = (act.get("sport_type") or act.get("type") or "").lower()
            if sport in exclude_types:
                continue
            valid_acts.append(act)

        # Find last exercise end time and aggregate intensity
        last_end_time = None
        last_sport = None
        last_end_hm = None
        total_exercise_min = 0
        avg_hr_weighted = None
        total_hr_time = 0
        weighted_hr_sum = 0
        activity_count = len(valid_acts)
        sport_types = []

        for act in valid_acts:
            start_local = act.get("start_date_local", "")
            elapsed = _sf(act.get("elapsed_time_seconds")) or 0
            moving  = _sf(act.get("moving_time_seconds")) or elapsed
            avg_hr  = _sf(act.get("average_heartrate"))
            sport   = act.get("sport_type") or act.get("type") or "Unknown"

            start_decimal = _parse_local_time(start_local)
            if start_decimal is not None:
                end_decimal = start_decimal + elapsed / 3600
                if last_end_time is None or end_decimal > last_end_time:
                    last_end_time = end_decimal
                    last_sport = sport
                    last_end_hm = _d2hm(end_decimal)

            total_exercise_min += moving / 60
            if avg_hr is not None and moving > 0:
                weighted_hr_sum += avg_hr * moving
                total_hr_time += moving
            if sport not in sport_types:
                sport_types.append(sport)

        if total_hr_time > 0:
            avg_hr_weighted = round(weighted_hr_sum / total_hr_time, 1)

        # Bucket by last exercise end time
        if activity_count == 0:
            bucket = "rest_day"
        elif last_end_time is None:
            bucket = "unknown_time"
        elif last_end_time < 12:
            bucket = "before_noon"
        elif last_end_time < 15:
            bucket = "noon_to_3pm"
        elif last_end_time < 18:
            bucket = "3pm_to_6pm"
        elif last_end_time < 20:
            bucket = "6pm_to_8pm"
        else:
            bucket = "after_8pm"

        intensity = _classify_intensity(avg_hr_weighted)

        daily_rows.append({
            "date": date,
            "activity_count": activity_count,
            "total_exercise_min": round(total_exercise_min, 1),
            "last_end_time": last_end_time,
            "last_end_time_hm": last_end_hm,
            "last_sport": last_sport,
            "sport_types": sport_types,
            "avg_hr": avg_hr_weighted,
            "intensity": intensity,
            "bucket": bucket,
            "sleep_efficiency_pct": eff,
            "deep_pct": deep,
            "rem_pct": rem,
            "sleep_score": score,
            "sleep_duration_hrs": dur,
            "time_to_sleep_min": latency,
            "hrv_avg": hrv,
        })

    if len(daily_rows) < 10:
        return {
            "error": f"Only {len(daily_rows)} days with sleep data. Need at least 10.",
            "start_date": start_date, "end_date": end_date,
        }

    exercise_days = [r for r in daily_rows if r["bucket"] != "rest_day"]
    rest_days = [r for r in daily_rows if r["bucket"] == "rest_day"]

    # ── Bucket analysis ──────────────────────────────────────────────────────
    SLEEP_METRICS = [
        ("sleep_efficiency_pct", "Sleep Efficiency %", "higher_is_better"),
        ("deep_pct",             "Deep Sleep %",       "higher_is_better"),
        ("rem_pct",              "REM %",              "higher_is_better"),
        ("sleep_score",          "Sleep Score",        "higher_is_better"),
        ("sleep_duration_hrs",   "Sleep Duration",     "higher_is_better"),
        ("time_to_sleep_min",    "Sleep Onset Latency","lower_is_better"),
        ("hrv_avg",              "HRV",                "higher_is_better"),
    ]

    BUCKET_ORDER = ["rest_day", "before_noon", "noon_to_3pm", "3pm_to_6pm", "6pm_to_8pm", "after_8pm"]
    BUCKET_LABELS = {
        "rest_day":     "Rest Day (No Exercise)",
        "before_noon":  "Exercise Ends Before Noon",
        "noon_to_3pm":  "Exercise Ends 12–3 PM",
        "3pm_to_6pm":   "Exercise Ends 3–6 PM",
        "6pm_to_8pm":   "Exercise Ends 6–8 PM",
        "after_8pm":    "Exercise Ends After 8 PM",
        "unknown_time": "Exercise (time unknown)",
    }

    bucket_data = {}
    for b in BUCKET_ORDER:
        b_rows = [r for r in daily_rows if r["bucket"] == b]
        if not b_rows:
            continue
        bucket_data[b] = {
            "label": BUCKET_LABELS[b],
            "days": len(b_rows),
            "avg_exercise_min": _avg([r["total_exercise_min"] for r in b_rows if r["total_exercise_min"] > 0]),
            "avg_hr": _avg([r["avg_hr"] for r in b_rows]),
            "metrics": {},
        }
        for field, label, _ in SLEEP_METRICS:
            vals = [r[field] for r in b_rows if r[field] is not None]
            if vals:
                bucket_data[b]["metrics"][field] = {
                    "label": label,
                    "avg": round(sum(vals) / len(vals), 2),
                    "n": len(vals),
                }

    # ── Timing correlations (last exercise end time vs sleep) ────────────────
    timed_rows = [r for r in exercise_days if r["last_end_time"] is not None]

    timing_correlations = {}
    for field, label, direction in SLEEP_METRICS:
        xs = [r["last_end_time"] for r in timed_rows if r[field] is not None]
        ys = [r[field]           for r in timed_rows if r[field] is not None]
        r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
        if r_val is not None:
            if direction == "higher_is_better":
                impact = "HARMFUL" if r_val < -0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            else:
                impact = "HARMFUL" if r_val > 0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            timing_correlations[field] = {
                "label": label, "pearson_r": r_val, "n": len(xs), "impact": impact,
                "interpretation": (
                    f"Later exercise {'strongly ' if abs(r_val) > 0.4 else ''}correlates with "
                    f"{'worse' if impact == 'HARMFUL' else 'better' if impact == 'BENEFICIAL' else 'no significant change in'} "
                    f"{label.lower()}"
                ),
            }

    # ── Intensity correlations (avg HR vs sleep, exercise days only) ─────────
    intensity_correlations = {}
    hr_rows = [r for r in exercise_days if r["avg_hr"] is not None]
    for field, label, direction in SLEEP_METRICS:
        xs = [r["avg_hr"] for r in hr_rows if r[field] is not None]
        ys = [r[field]     for r in hr_rows if r[field] is not None]
        r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
        if r_val is not None:
            if direction == "higher_is_better":
                impact = "HARMFUL" if r_val < -0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            else:
                impact = "HARMFUL" if r_val > 0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            intensity_correlations[field] = {"label": label, "pearson_r": r_val, "n": len(xs), "impact": impact}

    # ── Intensity x Timing interaction (high intensity + late = worst combo?) ─
    intensity_timing = {}
    for intensity_level in ["low", "moderate", "high"]:
        i_rows = [r for r in exercise_days if r["intensity"] == intensity_level and r["last_end_time"] is not None]
        if len(i_rows) < 3:
            continue
        late_rows = [r for r in i_rows if r["last_end_time"] >= 18]  # after 6pm
        early_rows = [r for r in i_rows if r["last_end_time"] < 18]
        if late_rows and early_rows:
            intensity_timing[intensity_level] = {
                "early_days": len(early_rows),
                "late_days": len(late_rows),
                "early_avg_efficiency": _avg([r["sleep_efficiency_pct"] for r in early_rows]),
                "late_avg_efficiency": _avg([r["sleep_efficiency_pct"] for r in late_rows]),
                "early_avg_deep": _avg([r["deep_pct"] for r in early_rows]),
                "late_avg_deep": _avg([r["deep_pct"] for r in late_rows]),
                "early_avg_hrv": _avg([r["hrv_avg"] for r in early_rows]),
                "late_avg_hrv": _avg([r["hrv_avg"] for r in late_rows]),
            }
            ee = intensity_timing[intensity_level]["early_avg_efficiency"]
            le = intensity_timing[intensity_level]["late_avg_efficiency"]
            if ee is not None and le is not None:
                intensity_timing[intensity_level]["efficiency_delta"] = round(le - ee, 2)

    # ── Exercise vs rest day comparison ──────────────────────────────────────
    exercise_vs_rest = {}
    if rest_days and exercise_days:
        for field, label, direction in SLEEP_METRICS:
            ex_vals = [r[field] for r in exercise_days if r[field] is not None]
            rest_vals = [r[field] for r in rest_days if r[field] is not None]
            if ex_vals and rest_vals:
                ex_avg = round(sum(ex_vals) / len(ex_vals), 2)
                rest_avg = round(sum(rest_vals) / len(rest_vals), 2)
                delta = round(ex_avg - rest_avg, 2)
                if direction == "lower_is_better":
                    verdict = "BETTER" if delta < -1 else "WORSE" if delta > 1 else "SIMILAR"
                else:
                    verdict = "BETTER" if delta > 1 else "WORSE" if delta < -1 else "SIMILAR"
                exercise_vs_rest[field] = {
                    "label": label,
                    "exercise_avg": ex_avg,
                    "rest_avg": rest_avg,
                    "delta": delta,
                    "verdict": verdict,
                    "exercise_n": len(ex_vals),
                    "rest_n": len(rest_vals),
                }

    # ── Personal cutoff recommendation ───────────────────────────────────────
    recommendation = None
    cutoff_time = None

    if bucket_data:
        # Use rest days + morning exercise as reference baseline
        ref_buckets = ["rest_day", "before_noon", "noon_to_3pm"]
        ref_effs = []
        for b in ref_buckets:
            if b in bucket_data and "sleep_efficiency_pct" in bucket_data[b]["metrics"]:
                ref_effs.append(bucket_data[b]["metrics"]["sleep_efficiency_pct"]["avg"])
        ref_eff = max(ref_effs) if ref_effs else None

        if ref_eff is not None:
            degradation_threshold = 3.0  # Higher threshold than caffeine -- exercise has noise
            for b in ["3pm_to_6pm", "6pm_to_8pm", "after_8pm"]:
                if b in bucket_data and "sleep_efficiency_pct" in bucket_data[b]["metrics"]:
                    b_eff = bucket_data[b]["metrics"]["sleep_efficiency_pct"]["avg"]
                    if ref_eff - b_eff >= degradation_threshold:
                        cutoff_map = {"3pm_to_6pm": "3 PM", "6pm_to_8pm": "6 PM", "after_8pm": "8 PM"}
                        cutoff_time = cutoff_map.get(b, b)
                        drop = round(ref_eff - b_eff, 1)
                        recommendation = (
                            f"Your sleep efficiency drops by {drop} percentage points when exercise "
                            f"ends after {cutoff_time}. Based on your data, aim to finish workouts by {cutoff_time}."
                        )
                        # Check if it's intensity-dependent
                        if "high" in intensity_timing:
                            hi = intensity_timing["high"]
                            if hi.get("efficiency_delta") is not None and hi["efficiency_delta"] < -3:
                                recommendation += (
                                    f" This effect is amplified for high-intensity exercise "
                                    f"(efficiency delta: {hi['efficiency_delta']} pts late vs early)."
                                )
                        break

        if recommendation is None:
            eff_corr = timing_correlations.get("sleep_efficiency_pct")
            if eff_corr and eff_corr["impact"] == "HARMFUL":
                recommendation = (
                    f"No sharp cutoff detected in bucket analysis, but there is a continuous "
                    f"negative correlation (r={eff_corr['pearson_r']}) between later exercise and sleep efficiency. "
                    f"Earlier is generally better for you."
                )
                cutoff_time = "6 PM (suggested)"
            elif eff_corr and eff_corr["impact"] == "BENEFICIAL":
                recommendation = (
                    f"Your data suggests later exercise actually correlates with BETTER sleep (r={eff_corr['pearson_r']}). "
                    f"This is not uncommon -- some people sleep better after evening exercise due to temperature "
                    f"drop rebound. No cutoff needed; exercise when it fits your schedule."
                )
            else:
                recommendation = (
                    "Your data does not show a strong relationship between exercise timing and sleep quality. "
                    "This is actually good news -- it means you can exercise when convenient without worrying "
                    "about sleep impact. Continue tracking to confirm with more data."
                )

    # ── Summary + alerts ─────────────────────────────────────────────────────
    all_end_times = [r["last_end_time"] for r in exercise_days if r["last_end_time"] is not None]

    summary = {
        "period": {"start_date": start_date, "end_date": end_date},
        "days_analyzed": len(daily_rows),
        "exercise_days": len(exercise_days),
        "rest_days": len(rest_days),
        "avg_last_exercise_end": _d2hm(sum(all_end_times) / len(all_end_times)) if all_end_times else None,
        "avg_exercise_min_on_active_days": _avg([r["total_exercise_min"] for r in exercise_days if r["total_exercise_min"] > 0]),
        "avg_hr_on_active_days": _avg([r["avg_hr"] for r in exercise_days]),
        "intensity_distribution": {
            level: sum(1 for r in exercise_days if r["intensity"] == level)
            for level in ["low", "moderate", "high", "unknown"]
        },
    }

    alerts = []
    # Late high-intensity warning
    late_intense = [r for r in exercise_days if r["last_end_time"] and r["last_end_time"] >= 20 and r["intensity"] == "high"]
    if late_intense:
        pct = round(100 * len(late_intense) / len(exercise_days), 0)
        alerts.append(
            f"High-intensity exercise ending after 8 PM on {len(late_intense)} days ({pct:.0f}%). "
            "Intense late workouts elevate core temperature and cortisol, both of which delay sleep onset. "
            "Consider shifting these to earlier or replacing with low-intensity evening sessions."
        )
    # Exercise vs rest insight
    evr_eff = exercise_vs_rest.get("sleep_efficiency_pct")
    if evr_eff and evr_eff["verdict"] == "BETTER":
        alerts.append(
            f"You sleep better on exercise days: {evr_eff['exercise_avg']}% vs {evr_eff['rest_avg']}% "
            f"efficiency (+{evr_eff['delta']} pts). Exercise is a net positive for your sleep."
        )
    elif evr_eff and evr_eff["verdict"] == "WORSE":
        alerts.append(
            f"You sleep worse on exercise days: {evr_eff['exercise_avg']}% vs {evr_eff['rest_avg']}% "
            f"efficiency ({evr_eff['delta']} pts). This is unusual -- check timing and intensity patterns."
        )
    # Deep sleep impact
    deep_corr = timing_correlations.get("deep_pct")
    if deep_corr and deep_corr["impact"] == "HARMFUL" and abs(deep_corr["pearson_r"]) > 0.25:
        alerts.append(
            f"Later exercise correlates with reduced deep sleep (r={deep_corr['pearson_r']}). "
            "Deep/SWS drives growth hormone release -- critical during body recomposition."
        )

    return {
        "summary": summary,
        "recommendation": {
            "cutoff_time": cutoff_time,
            "text": recommendation,
            "evidence_basis": ("bucket_comparison" if cutoff_time and "drops by" in (recommendation or "")
                              else "correlation" if cutoff_time
                              else "beneficial" if "BETTER" in (recommendation or "")
                              else "insufficient_data"),
        },
        "bucket_comparison": bucket_data,
        "exercise_vs_rest": exercise_vs_rest,
        "timing_correlations": timing_correlations,
        "intensity_correlations": intensity_correlations,
        "intensity_x_timing": intensity_timing,
        "alerts": alerts,
        "daily_detail": [
            {
                "date": r["date"],
                "last_exercise_end": r["last_end_time_hm"],
                "last_sport": r["last_sport"],
                "exercise_min": r["total_exercise_min"],
                "avg_hr": r["avg_hr"],
                "intensity": r["intensity"],
                "sleep_eff": r["sleep_efficiency_pct"],
                "deep_pct": r["deep_pct"],
                "rem_pct": r["rem_pct"],
                "sleep_score": r["sleep_score"],
                "hrv": r["hrv_avg"],
            }
            for r in daily_rows
        ],
    }
'''

# ── REGISTRY ENTRY ───────────────────────────────────────────────────────────
REGISTRY_ENTRY = '''    "get_exercise_sleep_correlation": {
        "fn": tool_get_exercise_sleep_correlation,
        "schema": {
            "name": "get_exercise_sleep_correlation",
            "description": (
                "Personal exercise timing cutoff finder. Extracts the last exercise end time per day from "
                "Strava (start_date_local + elapsed_time_seconds), then correlates with same-night Eight Sleep "
                "data (efficiency, deep sleep %, REM %, sleep score, onset latency, HRV). "
                "Splits days into time-of-day buckets (rest day / before noon / noon-3pm / 3-6pm / 6-8pm / after 8pm) "
                "and compares average sleep quality across buckets. Also analyzes exercise intensity via average HR "
                "and the interaction of intensity x timing (does a hard evening workout hurt more than an easy one?). "
                "Includes rest-day vs exercise-day comparison, Pearson correlations for timing and intensity effects, "
                "and a personal recommendation on exercise cutoff time. "
                "Based on Huberman, Galpin, and Attia guidance that exercise timing is a modifiable sleep lever. "
                "Use for: 'do late workouts hurt my sleep?', 'exercise timing and sleep quality', "
                "'when should I stop exercising before bed?', 'does evening exercise affect my deep sleep?', "
                "'exercise vs rest day sleep comparison'. Requires Strava + Eight Sleep data."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date":            {"type": "string", "description": "Start date YYYY-MM-DD (default: 180 days ago)."},
                    "end_date":              {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "min_duration_minutes":  {"type": "integer", "description": "Minimum activity duration in minutes to include (default: 15). Filters out very short activities."},
                    "exclude_sport_types":   {"type": "string", "description": "Comma-separated sport types to exclude (e.g. 'Walk,Yoga'). Case-insensitive."},
                },
                "required": [],
            },
        },
    },
'''

# ── PATCH 1: Insert function after tool_get_caffeine_sleep_correlation ───────
marker = "# ── Tool: get_habit_adherence"
if marker not in content:
    print(f"ERROR: Could not find marker: {marker}", file=sys.stderr)
    sys.exit(1)
content = content.replace(marker, FUNCTION_CODE + "\n" + marker)

# ── PATCH 2: Insert registry entry after get_caffeine_sleep_correlation ──────
registry_marker = '    # ── Habits / P40 tools'
if registry_marker not in content:
    print(f"ERROR: Could not find registry marker", file=sys.stderr)
    sys.exit(1)
content = content.replace(registry_marker, REGISTRY_ENTRY + registry_marker, 1)

# ── PATCH 3: Update version ──────────────────────────────────────────────────
content = content.replace('"version": "2.11.0"', '"version": "2.12.0"')

# ── PATCH 4: Update header comment ──────────────────────────────────────────
old_header = 'life-platform MCP Server v2.8.0\nNew in v2.8.0:'
new_header = '''life-platform MCP Server v2.12.0
New in v2.12.0:
  - get_exercise_sleep_correlation : personal exercise timing cutoff finder -- Strava end times + Eight Sleep

New in v2.8.0:'''
content = content.replace(old_header, new_header)

with open("mcp_server.py", "w") as f:
    f.write(content)

print("OK: mcp_server.py patched with get_exercise_sleep_correlation (v2.12.0)")
