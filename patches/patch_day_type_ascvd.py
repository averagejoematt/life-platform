#!/usr/bin/env python3
"""
patch_day_type_ascvd.py — Derived Metrics Phase 1f + 2c

Patches mcp_server.py with:
  1. classify_day_type() utility function (Phase 2c)
  2. tool_get_day_type_analysis — segmented analysis by day type
  3. ASCVD risk display in tool_get_health_risk_profile (Phase 1f)

Run after deploying patch_ascvd_risk.py (which stores ASCVD on labs records).
"""

import re

MCP_FILE = "mcp_server.py"

def read_file(path):
    with open(path, "r") as f:
        return f.read()

def write_file(path, content):
    with open(path, "w") as f:
        f.write(content)

# ─────────────────────────────────────────────
# Patch 1: classify_day_type utility function
# Insert before classify_exercise
# ─────────────────────────────────────────────

DAY_TYPE_UTILITY = '''

# ── Day Type Classification (Phase 2c) ───────────────────────────────────────

def classify_day_type(whoop_strain=None, strava_activities=None, daily_load=None):
    """
    Classify a day as rest/light/moderate/hard/race based on training signals.

    Priority:
      1. Strava activity type == 'Race' → 'race'
      2. Whoop strain or computed load → thresholds
      3. Strava activity count + distance as fallback

    Returns: 'rest', 'light', 'moderate', 'hard', or 'race'
    """
    # Check for race flag in Strava activities
    if strava_activities:
        for act in (strava_activities if isinstance(strava_activities, list) else [strava_activities]):
            if isinstance(act, dict):
                if act.get("workout_type") == "Race" or act.get("type", "").lower() == "race":
                    return "race"

    # Primary: Whoop strain (0-21 scale)
    if whoop_strain is not None:
        strain = float(whoop_strain)
        if strain < 4:
            return "rest"
        elif strain < 8:
            return "light"
        elif strain < 14:
            return "moderate"
        else:
            return "hard"

    # Secondary: computed load score (kJ or TRIMP)
    if daily_load is not None:
        load = float(daily_load)
        if load < 50:
            return "rest"
        elif load < 200:
            return "light"
        elif load < 500:
            return "moderate"
        else:
            return "hard"

    # Tertiary: Strava activity presence
    if strava_activities:
        acts = strava_activities if isinstance(strava_activities, list) else [strava_activities]
        if isinstance(acts[0], dict):
            total_dist = sum(float(a.get("total_distance_miles", 0) or 0) for a in acts)
            total_time = sum(float(a.get("total_moving_time_seconds", 0) or 0) for a in acts)
            if total_dist > 10 or total_time > 5400:
                return "hard"
            elif total_dist > 3 or total_time > 2700:
                return "moderate"
            elif total_dist > 0 or total_time > 0:
                return "light"

    return "rest"


DAY_TYPE_THRESHOLDS = {
    "whoop_strain": {"rest": 4, "light": 8, "moderate": 14, "hard": 21},
    "load_score":   {"rest": 50, "light": 200, "moderate": 500, "hard": float("inf")},
}

'''


# ─────────────────────────────────────────────
# Patch 2: tool_get_day_type_analysis
# New MCP tool for segmented analysis
# ─────────────────────────────────────────────

DAY_TYPE_TOOL = '''

# ── Tool: get_day_type_analysis (Phase 2c) ───────────────────────────────────

def tool_get_day_type_analysis(args):
    """
    Segment any metric by day type (rest/light/moderate/hard/race).

    Cross-references Whoop strain, Strava activities, and computed load
    to classify each day, then groups selected metrics by day type.

    Use cases:
      - 'How does my sleep differ on hard training days vs rest days?'
      - 'Do I eat more on training days?'
      - 'What\\'s my average HRV by day type?'
    """
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    days       = int(args.get("days", 90))
    start_date = args.get("start_date") or (
        datetime.utcnow() - timedelta(days=days)
    ).strftime("%Y-%m-%d")
    metrics    = args.get("metrics", ["sleep", "recovery", "nutrition"])
    if isinstance(metrics, str):
        metrics = [metrics]

    # Gather classification data
    whoop_data = {d["date"]: d for d in query_source("whoop", start_date, end_date, lean=True) if d.get("date")}
    strava_data = {d["date"]: d for d in query_source(get_sot("cardio"), start_date, end_date, lean=True) if d.get("date")}

    # Classify each day
    cur = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    classified = {}  # date -> day_type
    while cur <= end_dt:
        ds = cur.strftime("%Y-%m-%d")
        w = whoop_data.get(ds, {})
        s = strava_data.get(ds, {})
        strain = w.get("strain")
        load = compute_daily_load_score(s) if s else None
        classified[ds] = classify_day_type(
            whoop_strain=strain,
            strava_activities=s,
            daily_load=load,
        )
        cur += timedelta(days=1)

    # Count by type
    type_counts = {}
    for dt in classified.values():
        type_counts[dt] = type_counts.get(dt, 0) + 1

    # Gather metrics by day type
    type_metrics = {t: [] for t in ["rest", "light", "moderate", "hard", "race"]}

    # Batch fetch nutrition data if requested
    mf_data = {}
    if "nutrition" in metrics:
        pk_mf = "USER#matthew#SOURCE#macrofactor"
        table = get_table()
        try:
            mf_items = query_date_range(table, pk_mf, start_date, end_date)
            mf_data = {item["date"]: item for item in mf_items if item.get("date")}
        except Exception:
            pass

    for ds, day_type in classified.items():
        w = whoop_data.get(ds, {})
        entry = {"date": ds, "strain": w.get("strain")}

        if "sleep" in metrics or "recovery" in metrics:
            entry["recovery_score"] = w.get("recovery_score")
            entry["hrv"] = w.get("hrv")
            entry["resting_heart_rate"] = w.get("resting_heart_rate")
            entry["sleep_performance"] = w.get("sleep_performance")
            entry["total_sleep_hours"] = round(float(w["total_sleep_seconds"]) / 3600, 2) if w.get("total_sleep_seconds") else None

        if "nutrition" in metrics:
            mf = mf_data.get(ds, {})
            entry["calories_kcal"] = float(mf["total_calories_kcal"]) if mf.get("total_calories_kcal") else None
            entry["protein_g"] = float(mf["total_protein_g"]) if mf.get("total_protein_g") else None
            entry["carbs_g"] = float(mf["total_carbs_g"]) if mf.get("total_carbs_g") else None
            entry["fat_g"] = float(mf["total_fat_g"]) if mf.get("total_fat_g") else None

        type_metrics[day_type].append(entry)

    # Compute averages per type
    def avg_field(entries, field):
        vals = [float(e[field]) for e in entries if e.get(field) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    summary_fields = ["strain", "recovery_score", "hrv", "resting_heart_rate",
                      "sleep_performance", "total_sleep_hours",
                      "calories_kcal", "protein_g", "carbs_g", "fat_g"]
    summaries = {}
    for day_type, entries in type_metrics.items():
        if not entries:
            continue
        summaries[day_type] = {
            "count": len(entries),
            "averages": {f: avg_field(entries, f) for f in summary_fields},
        }

    # Key insights
    insights = []
    rest_hrv = summaries.get("rest", {}).get("averages", {}).get("hrv")
    hard_hrv = summaries.get("hard", {}).get("averages", {}).get("hrv")
    if rest_hrv and hard_hrv:
        diff = round(rest_hrv - hard_hrv, 1)
        if diff > 10:
            insights.append(f"HRV drops {diff} ms on hard vs rest days — significant recovery impact. Prioritize sleep after hard sessions.")
        elif diff > 5:
            insights.append(f"HRV drops {diff} ms on hard days — moderate recovery impact.")

    rest_cal = summaries.get("rest", {}).get("averages", {}).get("calories_kcal")
    hard_cal = summaries.get("hard", {}).get("averages", {}).get("calories_kcal")
    if rest_cal and hard_cal:
        diff = round(hard_cal - rest_cal)
        if diff > 300:
            insights.append(f"Eating {diff} kcal more on hard days vs rest — verify this aligns with your deficit goal.")
        elif diff < -200:
            insights.append(f"Eating {abs(diff)} kcal LESS on hard days — consider fueling better around training.")

    rest_sleep = summaries.get("rest", {}).get("averages", {}).get("total_sleep_hours")
    hard_sleep = summaries.get("hard", {}).get("averages", {}).get("total_sleep_hours")
    if rest_sleep and hard_sleep:
        diff = round(hard_sleep - rest_sleep, 2)
        if diff < -0.3:
            insights.append(f"Sleeping {abs(diff)} hrs LESS after hard days — your body needs MORE sleep for recovery, not less.")

    return {
        "period": {"start_date": start_date, "end_date": end_date, "total_days": len(classified)},
        "day_type_distribution": type_counts,
        "thresholds": DAY_TYPE_THRESHOLDS,
        "summaries": summaries,
        "insights": insights,
        "classification_source": "Whoop strain (primary) > computed load score > Strava distance/time",
    }

'''


# ─────────────────────────────────────────────
# Patch 3: ASCVD in health risk profile
# Read stored ASCVD from labs records
# ─────────────────────────────────────────────

ASCVD_IN_CV = '''
        # ASCVD 10-year risk (stored on labs records by patch_ascvd_risk.py)
        if draws:
            latest = draws[-1]
            ascvd_pct = latest.get("ascvd_risk_10yr_pct")
            if ascvd_pct is not None and isinstance(ascvd_pct, (int, float, Decimal)):
                ascvd_cat = latest.get("ascvd_risk_category", "unknown")
                ascvd_inputs = latest.get("ascvd_inputs", {})
                ascvd_caveats = latest.get("ascvd_caveats", [])
                cv["factors"].append({
                    "marker": "ASCVD 10yr Risk",
                    "value": float(ascvd_pct),
                    "unit": "%",
                    "risk": ascvd_cat,
                    "equation": "Pooled Cohort Equations (2013 ACC/AHA)",
                    "note": "Age-extrapolated — validated for 40-79" if any("extrapolated" in str(c) for c in ascvd_caveats) else "Within validated age range",
                    "inputs": {k: float(v) if isinstance(v, (Decimal, int, float)) else v for k, v in ascvd_inputs.items()},
                })
'''


# ─────────────────────────────────────────────
# Patch 4: Tool registry entry for day_type
# ─────────────────────────────────────────────

DAY_TYPE_REGISTRY = '''    "get_day_type_analysis": {
        "fn": tool_get_day_type_analysis,
        "schema": {
            "name": "get_day_type_analysis",
            "description": "Segment health metrics by training day type (rest/light/moderate/hard/race). Cross-references Whoop strain, Strava, and training load to classify each day, then compares averages for sleep, recovery, and nutrition across day types. Use for: 'how does my sleep differ on hard training days?', 'do I eat more on rest days?', 'what\\'s my HRV on hard vs easy days?', 'how does day type affect recovery?'",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 90 days ago."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                    "days":       {"type": "number", "description": "Lookback window in days. Default 90. Ignored if start_date provided."},
                    "metrics":    {"type": "array", "items": {"type": "string"}, "description": "Metric groups to analyze: 'sleep', 'recovery', 'nutrition'. Default: all three."},
                },
                "required": [],
            },
        },
    },'''


def apply_patches():
    content = read_file(MCP_FILE)
    patches_applied = 0

    # ── Patch 1: Day type utility before classify_exercise ──
    anchor = "def classify_exercise(name: str) -> dict:"
    if "def classify_day_type(" not in content:
        if anchor in content:
            content = content.replace(anchor, DAY_TYPE_UTILITY + anchor)
            patches_applied += 1
            print("✅ Patch 1: classify_day_type utility inserted")
        else:
            print("❌ Patch 1: Could not find anchor 'def classify_exercise'")
    else:
        print("⏭️  Patch 1: classify_day_type already exists")

    # ── Patch 2: Day type tool before lambda_handler ──
    anchor2 = "# ── Lambda handler ─"
    if "def tool_get_day_type_analysis(" not in content:
        if anchor2 in content:
            content = content.replace(anchor2, DAY_TYPE_TOOL + "\n" + anchor2)
            patches_applied += 1
            print("✅ Patch 2: tool_get_day_type_analysis inserted")
        else:
            print("❌ Patch 2: Could not find anchor '# ── Lambda handler'")
    else:
        print("⏭️  Patch 2: tool_get_day_type_analysis already exists")

    # ── Patch 3: ASCVD in health risk profile ──
    ascvd_anchor = '        elevated = sum(1 for f in cv["factors"] if f.get("risk") in ("elevated", "high", "low"))'
    if "ASCVD 10yr Risk" not in content:
        if ascvd_anchor in content:
            content = content.replace(ascvd_anchor, ASCVD_IN_CV + "\n" + ascvd_anchor)
            patches_applied += 1
            print("✅ Patch 3: ASCVD risk in health_risk_profile inserted")
        else:
            print("❌ Patch 3: Could not find ASCVD anchor in health_risk_profile")
    else:
        print("⏭️  Patch 3: ASCVD already in health_risk_profile")

    # ── Patch 4: Tool registry ──
    if '"get_day_type_analysis"' not in content:
        # Insert after get_health_risk_profile registry entry
        registry_anchor = '"get_health_risk_profile": {'
        if registry_anchor in content:
            idx = content.find(registry_anchor)
            remaining = content[idx + len(registry_anchor):]
            depth = 1
            i = 0
            while i < len(remaining) and depth > 0:
                if remaining[i] == '{':
                    depth += 1
                elif remaining[i] == '}':
                    depth -= 1
                i += 1
            insert_pos = idx + len(registry_anchor) + i
            after = content[insert_pos:insert_pos+10].strip()
            if after.startswith(','):
                comma_pos = content.index(',', insert_pos)
                content = content[:comma_pos+1] + "\n" + DAY_TYPE_REGISTRY + content[comma_pos+1:]
            else:
                content = content[:insert_pos] + ",\n" + DAY_TYPE_REGISTRY + content[insert_pos:]
            patches_applied += 1
            print("✅ Patch 4: get_day_type_analysis added to tool registry")
        else:
            print("❌ Patch 4: Could not find registry anchor")
    else:
        print("⏭️  Patch 4: get_day_type_analysis already in registry")

    write_file(MCP_FILE, content)
    print(f"\n{'='*50}")
    print(f"Patches applied: {patches_applied}")
    return patches_applied


if __name__ == "__main__":
    apply_patches()
