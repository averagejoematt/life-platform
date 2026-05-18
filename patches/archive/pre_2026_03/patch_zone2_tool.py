"""
patch_zone2_tool.py — Add get_zone2_breakdown tool (v2.13.0)

Patches mcp_server.py with:
  1. New function: tool_get_zone2_breakdown (after get_exercise_sleep_correlation)
  2. New registry entry (after get_exercise_sleep_correlation in TOOL_REGISTRY)
  3. Version bump 2.12.0 → 2.13.0
  4. Header update

Idempotent: aborts if tool already exists.

Usage:
    cd ~/Documents/Claude/life-platform
    python3 patch_zone2_tool.py
"""

import sys

with open("mcp_server.py", "r") as f:
    content = f.read()

# ── Safety check ──────────────────────────────────────────────────────────────
if "get_zone2_breakdown" in content:
    print("SKIP: get_zone2_breakdown already exists in mcp_server.py")
    sys.exit(0)

# ── FUNCTION DEFINITION ──────────────────────────────────────────────────────
FUNCTION_CODE = r'''

# ── Tool: get_zone2_breakdown ────────────────────────────────────────────────

def tool_get_zone2_breakdown(args):
    """
    Zone 2 training tracker. Classifies each Strava activity into HR zones based on
    average heartrate as a percentage of max HR (from profile). Aggregates weekly Zone 2
    minutes, compares to the 150 min/week target (Attia, Huberman, WHO guidelines for
    moderate-intensity aerobic activity), and shows full 5-zone distribution.

    Zone 2 is the highest-evidence longevity training modality — it builds mitochondrial
    density, fat oxidation capacity, and cardiovascular base. Most people drastically
    undertrain Zone 2 relative to higher intensities.
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=89)).strftime("%Y-%m-%d"))
    weekly_target_min = int(args.get("weekly_target_minutes", 150))
    min_duration_min  = int(args.get("min_duration_minutes", 10))

    # HR zone thresholds from profile
    profile = get_profile()
    max_hr  = float(profile.get("max_heart_rate", 190))
    rhr     = float(profile.get("resting_heart_rate_baseline", 60))

    # 5 zones by % of max HR (standard model)
    # Zone 1: 50-60%  (warm-up / recovery)
    # Zone 2: 60-70%  (aerobic base / fat burn — the longevity zone)
    # Zone 3: 70-80%  (tempo / aerobic capacity)
    # Zone 4: 80-90%  (threshold / lactate)
    # Zone 5: 90-100% (VO2 max / anaerobic)
    ZONE_BOUNDS = [
        ("zone_1", "Zone 1 (Recovery)",   0.50, 0.60),
        ("zone_2", "Zone 2 (Aerobic)",    0.60, 0.70),
        ("zone_3", "Zone 3 (Tempo)",      0.70, 0.80),
        ("zone_4", "Zone 4 (Threshold)",  0.80, 0.90),
        ("zone_5", "Zone 5 (VO2 Max)",    0.90, 1.00),
    ]

    zone_hr_ranges = {}
    for key, label, lo_pct, hi_pct in ZONE_BOUNDS:
        zone_hr_ranges[key] = {
            "label": label,
            "hr_low": round(max_hr * lo_pct, 0),
            "hr_high": round(max_hr * hi_pct, 0),
        }

    def _sf(v):
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def classify_zone(avg_hr):
        """Classify activity into HR zone by avg HR."""
        if avg_hr is None:
            return "no_hr"
        pct = avg_hr / max_hr
        if pct < 0.50:
            return "below_zone_1"
        elif pct < 0.60:
            return "zone_1"
        elif pct < 0.70:
            return "zone_2"
        elif pct < 0.80:
            return "zone_3"
        elif pct < 0.90:
            return "zone_4"
        else:
            return "zone_5"

    # ── Query Strava activities ──────────────────────────────────────────────
    strava_items = query_source("strava", start_date, end_date)
    if not strava_items:
        return {"error": "No Strava data for range.", "start_date": start_date, "end_date": end_date}

    # Flatten all activities
    all_activities = []
    for day in sorted(strava_items, key=lambda x: x.get("date", "")):
        date = day.get("date", "")
        for act in day.get("activities", []):
            moving = _sf(act.get("moving_time_seconds")) or 0
            if moving < min_duration_min * 60:
                continue
            avg_hr = _sf(act.get("average_heartrate"))
            zone = classify_zone(avg_hr)
            sport = act.get("sport_type") or act.get("type") or "Unknown"
            all_activities.append({
                "date": date,
                "name": act.get("enriched_name") or act.get("name") or "Unnamed",
                "sport_type": sport,
                "moving_time_min": round(moving / 60, 1),
                "avg_hr": avg_hr,
                "max_hr": _sf(act.get("max_heartrate")),
                "zone": zone,
                "distance_miles": _sf(act.get("distance_miles")),
            })

    if not all_activities:
        return {"error": "No qualifying activities found.", "start_date": start_date, "end_date": end_date}

    # ── Weekly aggregation ───────────────────────────────────────────────────
    from collections import defaultdict

    def iso_week(date_str):
        """Return ISO year-week string like '2025-W48'."""
        from datetime import datetime as dt
        d = dt.strptime(date_str, "%Y-%m-%d")
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"

    def week_start(date_str):
        """Return Monday of the week for a given date."""
        from datetime import datetime as dt
        d = dt.strptime(date_str, "%Y-%m-%d")
        monday = d - timedelta(days=d.weekday())
        return monday.strftime("%Y-%m-%d")

    weekly = defaultdict(lambda: {
        "zone_1_min": 0, "zone_2_min": 0, "zone_3_min": 0,
        "zone_4_min": 0, "zone_5_min": 0, "below_zone_1_min": 0,
        "no_hr_min": 0, "total_exercise_min": 0, "activity_count": 0,
        "zone_2_activities": [],
    })

    for act in all_activities:
        wk = week_start(act["date"])
        z = act["zone"]
        mins = act["moving_time_min"]
        weekly[wk]["total_exercise_min"] += mins
        weekly[wk]["activity_count"] += 1
        if z in ("zone_1", "zone_2", "zone_3", "zone_4", "zone_5"):
            weekly[wk][f"{z}_min"] += mins
        elif z == "below_zone_1":
            weekly[wk]["below_zone_1_min"] += mins
        else:
            weekly[wk]["no_hr_min"] += mins
        if z == "zone_2":
            weekly[wk]["zone_2_activities"].append({
                "date": act["date"],
                "name": act["name"],
                "sport": act["sport_type"],
                "minutes": mins,
                "avg_hr": act["avg_hr"],
            })

    weekly_sorted = []
    for wk in sorted(weekly.keys()):
        w = weekly[wk]
        z2 = w["zone_2_min"]
        pct_target = round(100 * z2 / weekly_target_min, 0) if weekly_target_min > 0 else None
        weekly_sorted.append({
            "week_start": wk,
            "zone_2_minutes": round(z2, 1),
            "target_pct": pct_target,
            "target_met": z2 >= weekly_target_min,
            "zone_1_min": round(w["zone_1_min"], 1),
            "zone_3_min": round(w["zone_3_min"], 1),
            "zone_4_min": round(w["zone_4_min"], 1),
            "zone_5_min": round(w["zone_5_min"], 1),
            "total_exercise_min": round(w["total_exercise_min"], 1),
            "activity_count": w["activity_count"],
            "zone_2_activities": w["zone_2_activities"],
        })

    # ── Zone distribution (full period) ──────────────────────────────────────
    zone_totals = {"zone_1": 0, "zone_2": 0, "zone_3": 0, "zone_4": 0, "zone_5": 0, "below_zone_1": 0, "no_hr": 0}
    zone_counts = {"zone_1": 0, "zone_2": 0, "zone_3": 0, "zone_4": 0, "zone_5": 0, "below_zone_1": 0, "no_hr": 0}
    for act in all_activities:
        z = act["zone"]
        zone_totals[z] = zone_totals.get(z, 0) + act["moving_time_min"]
        zone_counts[z] = zone_counts.get(z, 0) + 1

    total_min = sum(zone_totals.values())
    zone_distribution = {}
    for key, label, _, _ in ZONE_BOUNDS:
        mins = round(zone_totals.get(key, 0), 1)
        zone_distribution[key] = {
            "label": label,
            "total_minutes": mins,
            "activity_count": zone_counts.get(key, 0),
            "pct_of_training": round(100 * mins / total_min, 1) if total_min > 0 else 0,
            "hr_range": f"{zone_hr_ranges[key]['hr_low']:.0f}-{zone_hr_ranges[key]['hr_high']:.0f} bpm",
        }

    # ── Sport type breakdown for Zone 2 ──────────────────────────────────────
    z2_by_sport = defaultdict(lambda: {"minutes": 0, "count": 0})
    for act in all_activities:
        if act["zone"] == "zone_2":
            z2_by_sport[act["sport_type"]]["minutes"] += act["moving_time_min"]
            z2_by_sport[act["sport_type"]]["count"] += 1

    sport_breakdown = []
    for sport, data in sorted(z2_by_sport.items(), key=lambda x: -x[1]["minutes"]):
        sport_breakdown.append({
            "sport_type": sport,
            "zone_2_minutes": round(data["minutes"], 1),
            "activity_count": data["count"],
        })

    # ── Trend analysis ───────────────────────────────────────────────────────
    z2_weekly_vals = [w["zone_2_minutes"] for w in weekly_sorted]
    trend = None
    if len(z2_weekly_vals) >= 3:
        xs = list(range(len(z2_weekly_vals)))
        slope_r = pearson_r(xs, z2_weekly_vals) if len(xs) >= 3 else None
        avg_first_half = sum(z2_weekly_vals[:len(z2_weekly_vals)//2]) / max(len(z2_weekly_vals)//2, 1)
        avg_second_half = sum(z2_weekly_vals[len(z2_weekly_vals)//2:]) / max(len(z2_weekly_vals) - len(z2_weekly_vals)//2, 1)
        trend = {
            "direction": "INCREASING" if avg_second_half > avg_first_half + 5 else "DECREASING" if avg_second_half < avg_first_half - 5 else "STABLE",
            "first_half_avg_min": round(avg_first_half, 1),
            "second_half_avg_min": round(avg_second_half, 1),
            "correlation_r": slope_r,
        }

    # ── Summary ──────────────────────────────────────────────────────────────
    n_weeks = len(weekly_sorted)
    avg_z2_weekly = round(sum(z2_weekly_vals) / n_weeks, 1) if n_weeks > 0 else 0
    weeks_meeting_target = sum(1 for w in weekly_sorted if w["target_met"])

    summary = {
        "period": {"start_date": start_date, "end_date": end_date},
        "weeks_analyzed": n_weeks,
        "total_activities": len(all_activities),
        "zone_2_activities": zone_counts.get("zone_2", 0),
        "avg_weekly_zone_2_min": avg_z2_weekly,
        "weekly_target_min": weekly_target_min,
        "weeks_meeting_target": weeks_meeting_target,
        "target_hit_rate_pct": round(100 * weeks_meeting_target / n_weeks, 0) if n_weeks > 0 else 0,
        "total_zone_2_min": round(zone_totals.get("zone_2", 0), 1),
        "max_hr_used": max_hr,
        "zone_2_hr_range": f"{zone_hr_ranges['zone_2']['hr_low']:.0f}-{zone_hr_ranges['zone_2']['hr_high']:.0f} bpm",
    }

    # ── Alerts + recommendations ─────────────────────────────────────────────
    alerts = []

    if avg_z2_weekly < weekly_target_min * 0.5:
        deficit = round(weekly_target_min - avg_z2_weekly, 0)
        alerts.append(
            f"Zone 2 deficit: averaging {avg_z2_weekly} min/week vs {weekly_target_min} min target "
            f"({deficit:.0f} min shortfall). Zone 2 is the foundation of cardiovascular longevity -- "
            "consider adding 2-3 sessions of easy cardio (walking, cycling, easy jogging) per week "
            f"where HR stays in {zone_hr_ranges['zone_2']['hr_low']:.0f}-{zone_hr_ranges['zone_2']['hr_high']:.0f} bpm."
        )
    elif avg_z2_weekly < weekly_target_min:
        deficit = round(weekly_target_min - avg_z2_weekly, 0)
        alerts.append(
            f"Close to target: averaging {avg_z2_weekly} min/week vs {weekly_target_min} min target "
            f"({deficit:.0f} min shortfall). One additional Zone 2 session per week would close the gap."
        )

    # Polarization check: too much Zone 3 relative to Zone 2
    z3_total = zone_totals.get("zone_3", 0)
    z2_total = zone_totals.get("zone_2", 0)
    if z3_total > z2_total and z3_total > 30:
        alerts.append(
            f"Training polarization issue: more time in Zone 3 ({round(z3_total, 0)} min) than Zone 2 "
            f"({round(z2_total, 0)} min). Per Seiler's polarized training model, ~80% of endurance "
            "volume should be easy (Zone 1-2) with ~20% hard (Zone 4-5). Zone 3 is 'no man's land' -- "
            "too hard to build aerobic base, too easy for VO2 max gains."
        )

    # Zone 5 volume check
    z5_total = zone_totals.get("zone_5", 0)
    if z5_total > z2_total and z5_total > 20:
        alerts.append(
            f"High-intensity dominant: more Zone 5 ({round(z5_total, 0)} min) than Zone 2 ({round(z2_total, 0)} min). "
            "This pattern correlates with overtraining risk. Prioritize Zone 2 base building."
        )

    # No HR data warning
    no_hr_count = zone_counts.get("no_hr", 0)
    if no_hr_count > len(all_activities) * 0.3:
        alerts.append(
            f"{no_hr_count} of {len(all_activities)} activities ({round(100*no_hr_count/len(all_activities))}%) "
            "lack HR data. Zone classification requires heart rate -- ensure your HR monitor is connected during workouts."
        )

    return {
        "summary": summary,
        "zone_distribution": zone_distribution,
        "zone_hr_thresholds": zone_hr_ranges,
        "weekly_breakdown": weekly_sorted,
        "sport_type_zone2": sport_breakdown,
        "trend": trend,
        "alerts": alerts,
        "methodology": (
            f"Activities classified by average HR as percentage of max HR ({max_hr:.0f} bpm from profile). "
            f"Zone 2 = 60-70% max = {zone_hr_ranges['zone_2']['hr_low']:.0f}-{zone_hr_ranges['zone_2']['hr_high']:.0f} bpm. "
            "Full activity moving time is attributed to the classified zone. This is an approximation -- "
            "average HR doesn't capture intra-activity zone transitions. Activities without HR data are excluded "
            "from zone classification."
        ),
    }
'''

# ── REGISTRY ENTRY ───────────────────────────────────────────────────────────
REGISTRY_ENTRY = '''    "get_zone2_breakdown": {
        "fn": tool_get_zone2_breakdown,
        "schema": {
            "name": "get_zone2_breakdown",
            "description": (
                "Zone 2 training tracker and weekly breakdown. Classifies Strava activities into 5 HR zones "
                "based on average heartrate as a percentage of max HR (from profile). Aggregates weekly Zone 2 "
                "minutes and compares to the 150 min/week target (Attia, Huberman, WHO moderate-intensity guidelines). "
                "Shows full 5-zone training distribution, sport type breakdown for Zone 2, weekly trend analysis, "
                "and training polarization alerts (Zone 3 'no man\\'s land' warning per Seiler). "
                "Zone 2 (60-70% max HR) is the highest-evidence longevity training modality — builds mitochondrial "
                "density, fat oxidation capacity, and cardiovascular base. "
                "Use for: 'how much Zone 2 am I doing?', 'am I hitting my Zone 2 target?', "
                "'show my training zone distribution', 'weekly Zone 2 minutes', 'zone 2 trend', "
                "'am I doing enough easy cardio?', 'training polarization check'. Requires Strava data with HR."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date":             {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date":               {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "weekly_target_minutes":   {"type": "integer", "description": "Weekly Zone 2 target in minutes (default: 150, per Attia/WHO guidelines)."},
                    "min_duration_minutes":    {"type": "integer", "description": "Minimum activity duration in minutes to include (default: 10)."},
                },
                "required": [],
            },
        },
    },
'''

# ── PATCH 1: Insert function after get_exercise_sleep_correlation ────────────
marker = "# ── Tool: get_habit_adherence"
if marker not in content:
    print(f"ERROR: Could not find marker: {marker}", file=sys.stderr)
    sys.exit(1)
content = content.replace(marker, FUNCTION_CODE + "\n" + marker)

# ── PATCH 2: Insert registry entry after get_exercise_sleep_correlation ──────
registry_marker = '    # ── Habits / P40 tools'
if registry_marker not in content:
    print(f"ERROR: Could not find registry marker", file=sys.stderr)
    sys.exit(1)
content = content.replace(registry_marker, REGISTRY_ENTRY + registry_marker, 1)

# ── PATCH 3: Update version ──────────────────────────────────────────────────
content = content.replace('"version": "2.12.0"', '"version": "2.13.0"')

# ── PATCH 4: Update header comment ──────────────────────────────────────────
old_header = 'life-platform MCP Server v2.12.0\nNew in v2.12.0:'
new_header = '''life-platform MCP Server v2.13.0
New in v2.13.0:
  - get_zone2_breakdown : Zone 2 training tracker -- weekly minutes, 5-zone distribution, target comparison, polarization alerts

New in v2.12.0:'''
content = content.replace(old_header, new_header)

with open("mcp_server.py", "w") as f:
    f.write(content)

print("OK: mcp_server.py patched with get_zone2_breakdown (v2.13.0)")
