#!/bin/bash
# deploy_feature8_hr_recovery.sh — Deploy Feature #8: Heart Rate Recovery Tracking
# Two changes: Strava Lambda (HR stream fetch) + MCP server (get_hr_recovery_trend tool)
set -euo pipefail

echo "═══════════════════════════════════════════════════════════════"
echo "  Feature #8: Heart Rate Recovery Tracking"
echo "  Strava Lambda + MCP server update"
echo "═══════════════════════════════════════════════════════════════"

cd ~/Documents/Claude/life-platform

# ── Step 1: Backups ─────────────────────────────────────────────────────────
cp lambdas/strava_lambda.py lambdas/strava_lambda.py.bak.f8
cp mcp_server.py mcp_server.py.bak.f8
echo "✅ Backups created (.bak.f8)"

# ── Step 2: Patch Strava Lambda ─────────────────────────────────────────────
python3 << 'PYTHON_PATCH_STRAVA'
import sys

with open("lambdas/strava_lambda.py", "r") as f:
    content = f.read()

# ── 2a: Add fetch_activity_streams function after fetch_activity_zones ──
stream_func = '''

def fetch_activity_streams(strava_id: str, secret: dict) -> tuple:
    """
    Fetch HR + time streams for an activity. Computes HR recovery metrics.
    Returns (hr_recovery_dict, secret).
    """
    try:
        url = f"https://www.strava.com/api/v3/activities/{strava_id}/streams?keys=heartrate,time&key_type=time"
        data, secret = strava_get(url, secret)

        hr_data = None
        time_data = None
        for stream in data:
            if stream.get("type") == "heartrate":
                hr_data = stream.get("data", [])
            elif stream.get("type") == "time":
                time_data = stream.get("data", [])

        if not hr_data or not time_data or len(hr_data) < 60:
            return {}, secret

        # Rolling 30s average for peak detection
        rolling_avgs = []
        for i in range(len(hr_data)):
            start_idx = i
            while start_idx > 0 and time_data[i] - time_data[start_idx] < 30:
                start_idx -= 1
            window_vals = hr_data[start_idx:i+1]
            rolling_avgs.append(sum(window_vals) / len(window_vals) if window_vals else hr_data[i])

        peak_rolling = max(rolling_avgs)
        peak_rolling_idx = rolling_avgs.index(peak_rolling)
        peak_instant = max(hr_data)
        peak_time = time_data[peak_rolling_idx]
        total_time = time_data[-1]

        # Last 60s average
        last_60s_vals = [hr_data[i] for i in range(len(time_data))
                         if time_data[-1] - time_data[i] <= 60]
        end_60s = sum(last_60s_vals) / len(last_60s_vals) if last_60s_vals else None

        recovery_intra = round(peak_rolling - end_60s, 1) if end_60s else None
        has_cooldown = end_60s is not None and end_60s < peak_rolling * 0.85

        result = {
            "hr_peak": round(peak_rolling, 1),
            "hr_peak_instant": round(peak_instant, 1),
            "hr_end_60s": round(end_60s, 1) if end_60s else None,
            "hr_recovery_intra": recovery_intra,
            "has_cooldown": has_cooldown,
            "stream_duration_s": total_time,
            "stream_samples": len(hr_data),
        }

        remaining_time = total_time - peak_time
        if remaining_time >= 60:
            target_60 = peak_time + 60
            idx_60 = min(range(len(time_data)), key=lambda i: abs(time_data[i] - target_60))
            window_vals = [hr_data[j] for j in range(max(0, idx_60-5), min(len(hr_data), idx_60+5))]
            hr_at_60 = sum(window_vals) / len(window_vals) if window_vals else None
            if hr_at_60:
                result["hr_at_peak_plus_60s"] = round(hr_at_60, 1)
                result["hr_recovery_60s"] = round(peak_rolling - hr_at_60, 1)

        if remaining_time >= 120:
            target_120 = peak_time + 120
            idx_120 = min(range(len(time_data)), key=lambda i: abs(time_data[i] - target_120))
            window_vals = [hr_data[j] for j in range(max(0, idx_120-5), min(len(hr_data), idx_120+5))]
            hr_at_120 = sum(window_vals) / len(window_vals) if window_vals else None
            if hr_at_120:
                result["hr_at_peak_plus_120s"] = round(hr_at_120, 1)
                result["hr_recovery_120s"] = round(peak_rolling - hr_at_120, 1)

        print(f"  HR recovery: peak={result['hr_peak']}, end_60s={result.get('hr_end_60s')}, "
              f"recovery_intra={result.get('hr_recovery_intra')}, cooldown={has_cooldown}")
        return result, secret

    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"  No stream data for activity {strava_id}")
        elif e.code == 429:
            print(f"  Rate limited on stream fetch for {strava_id}")
        else:
            print(f"  Stream fetch error for {strava_id}: {e.code}")
        return {}, secret
    except Exception as e:
        print(f"  Stream fetch exception for {strava_id}: {e}")
        return {}, secret
'''

# Insert after fetch_activity_zones function
marker = "def fetch_activities("
idx = content.find(marker)
if idx == -1:
    print("ERROR: Could not find fetch_activities function")
    sys.exit(1)

content = content[:idx] + stream_func + "\n" + content[idx:]
print("Inserted fetch_activity_streams function")

# ── 2b: Update normalize_activity to accept hr_recovery param ──
old_sig = "def normalize_activity(activity, zone_data=None):"
new_sig = "def normalize_activity(activity, zone_data=None, hr_recovery=None):"
if old_sig in content:
    content = content.replace(old_sig, new_sig)
    print("Updated normalize_activity signature")
else:
    print("WARNING: normalize_activity signature already changed or not found")

# Add hr_recovery merge after zone_data merge
old_zone_merge = """    # Merge HR zone data if available (Phase 2 enhancement)
    if zone_data:
        result.update(zone_data)

    return result"""

new_zone_merge = """    # Merge HR zone data if available (Phase 2 enhancement)
    if zone_data:
        result.update(zone_data)

    # Merge HR recovery data if available (Feature #8)
    if hr_recovery:
        result["hr_recovery"] = hr_recovery

    return result"""

if old_zone_merge in content:
    content = content.replace(old_zone_merge, new_zone_merge)
    print("Added hr_recovery merge to normalize_activity")
else:
    print("WARNING: Could not find zone_data merge block")

# ── 2c: Update ingestion loop to call fetch_activity_streams ──
old_loop = """            zone_data, secret = fetch_activity_zones(str(a["id"]), secret)
            normalized.append(normalize_activity(a, zone_data))"""

new_loop = """            zone_data, secret = fetch_activity_zones(str(a["id"]), secret)
                # Fetch HR streams for recovery metrics (>= 10 min activities)
                hr_recovery = {}
                elapsed = a.get("elapsed_time") or 0
                if elapsed >= 600:
                    hr_recovery, secret = fetch_activity_streams(str(a["id"]), secret)
            normalized.append(normalize_activity(a, zone_data, hr_recovery))"""

# Fix for the case where normalize is on next line after zone fetch
old_loop_alt = """            if a.get("has_heartrate") and a.get("id"):
                zone_data, secret = fetch_activity_zones(str(a["id"]), secret)
            normalized.append(normalize_activity(a, zone_data))"""

new_loop_alt = """            if a.get("has_heartrate") and a.get("id"):
                zone_data, secret = fetch_activity_zones(str(a["id"]), secret)
                # Fetch HR streams for recovery metrics (>= 10 min activities)
                elapsed = a.get("elapsed_time") or 0
                if elapsed >= 600:
                    hr_recovery, secret = fetch_activity_streams(str(a["id"]), secret)
            normalized.append(normalize_activity(a, zone_data, hr_recovery if a.get("has_heartrate") else None))"""

if old_loop_alt in content:
    # Also need hr_recovery initialized before the if block
    old_init = """        for a in day_activities:
            # Fetch HR zones for activities with heart rate data (Phase 2)
            zone_data = {}"""
    new_init = """        for a in day_activities:
            # Fetch HR zones for activities with heart rate data (Phase 2)
            zone_data = {}
            hr_recovery = {}"""
    content = content.replace(old_init, new_init)
    content = content.replace(old_loop_alt, new_loop_alt)
    print("Updated ingestion loop with HR stream fetch")
elif old_loop in content:
    content = content.replace(old_loop, new_loop)
    print("Updated ingestion loop with HR stream fetch (alt)")
else:
    print("WARNING: Could not find ingestion loop pattern")

with open("lambdas/strava_lambda.py", "w") as f:
    f.write(content)

print("strava_lambda.py patched successfully")
PYTHON_PATCH_STRAVA

echo "✅ Strava Lambda patched"

# ── Step 3: Patch MCP Server ────────────────────────────────────────────────
python3 << 'PYTHON_PATCH_MCP'
import sys

with open("mcp_server.py", "r") as f:
    content = f.read()

# ── 3a: Insert tool function before TOOLS dict ──
tool_func = '''
def tool_get_hr_recovery_trend(args):
    """
    Heart rate recovery tracker — strongest exercise-derived mortality predictor.
    Extracts post-peak HR recovery from Strava activity streams, trends over time.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=180)).strftime("%Y-%m-%d"))
    sport_filter = (args.get("sport_type") or "").strip().lower()
    cooldown_only = args.get("cooldown_only", False)

    strava_items = query_source("strava", start_date, end_date)
    if not strava_items:
        return {"error": "No Strava data for range.", "start_date": start_date, "end_date": end_date}

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    profile = get_profile()
    max_hr = float(profile.get("max_heart_rate", 190))

    records = []
    for item in strava_items:
        date = item.get("date")
        for act in (item.get("activities") or []):
            hr_rec = act.get("hr_recovery")
            if not hr_rec or not isinstance(hr_rec, dict):
                continue
            sport = (act.get("sport_type") or act.get("type") or "").lower()
            if sport_filter and sport_filter not in sport.replace(" ", ""):
                continue
            has_cooldown = hr_rec.get("has_cooldown", False)
            if cooldown_only and not has_cooldown:
                continue
            peak = _sf(hr_rec.get("hr_peak"))
            recovery_intra = _sf(hr_rec.get("hr_recovery_intra"))
            recovery_60s = _sf(hr_rec.get("hr_recovery_60s"))
            recovery_120s = _sf(hr_rec.get("hr_recovery_120s"))
            best_recovery = recovery_60s or recovery_intra
            if peak is None or best_recovery is None:
                continue
            if best_recovery >= 25: classification = "excellent"
            elif best_recovery >= 18: classification = "good"
            elif best_recovery >= 12: classification = "average"
            else: classification = "below_average"
            records.append({
                "date": date,
                "sport_type": act.get("sport_type") or act.get("type"),
                "activity_name": act.get("name", ""),
                "duration_min": round((_sf(act.get("elapsed_time_seconds")) or 0) / 60, 1),
                "hr_peak": peak,
                "hr_peak_pct_max": round(peak / max_hr * 100, 1) if peak else None,
                "hr_end_60s": _sf(hr_rec.get("hr_end_60s")),
                "hr_recovery_intra": recovery_intra,
                "hr_recovery_60s": recovery_60s,
                "hr_recovery_120s": recovery_120s,
                "has_cooldown": has_cooldown,
                "best_recovery_bpm": best_recovery,
                "classification": classification,
            })

    if not records:
        return {
            "error": "No activities with HR recovery data found. HR recovery requires Strava ingestion v2.35.0+ with stream fetching.",
            "start_date": start_date, "end_date": end_date,
            "tip": "Activities need HR data and >= 10 min duration. Recovery metrics computed from HR streams during ingestion.",
        }

    records.sort(key=lambda r: r["date"])

    mid = len(records) // 2
    first_half = records[:mid] if mid > 0 else records
    second_half = records[mid:] if mid > 0 else records
    first_avg = _avg([r["best_recovery_bpm"] for r in first_half])
    second_avg = _avg([r["best_recovery_bpm"] for r in second_half])

    trend_direction = None
    trend_delta = None
    if first_avg is not None and second_avg is not None:
        trend_delta = round(second_avg - first_avg, 1)
        trend_direction = "improving" if trend_delta > 2 else ("declining" if trend_delta < -2 else "stable")

    date_ordinals = []
    recovery_vals = []
    base_date = datetime.strptime(records[0]["date"], "%Y-%m-%d")
    for r in records:
        d = (datetime.strptime(r["date"], "%Y-%m-%d") - base_date).days
        date_ordinals.append(d)
        recovery_vals.append(r["best_recovery_bpm"])
    r_val = pearson_r(date_ordinals, recovery_vals) if len(date_ordinals) >= 5 else None

    by_sport = {}
    for r in records:
        s = r["sport_type"] or "Unknown"
        if s not in by_sport:
            by_sport[s] = {"activities": 0, "avg_recovery": [], "avg_peak_hr": []}
        by_sport[s]["activities"] += 1
        by_sport[s]["avg_recovery"].append(r["best_recovery_bpm"])
        by_sport[s]["avg_peak_hr"].append(r["hr_peak"])
    sport_summary = {}
    for s, data in by_sport.items():
        sport_summary[s] = {
            "activities": data["activities"],
            "avg_recovery_bpm": _avg(data["avg_recovery"]),
            "avg_peak_hr": _avg(data["avg_peak_hr"]),
        }

    dist = {"excellent": 0, "good": 0, "average": 0, "below_average": 0}
    for r in records:
        dist[r["classification"]] += 1
    total = len(records)
    dist_pct = {k: round(v / total * 100, 1) for k, v in dist.items()}

    sorted_by_recovery = sorted(records, key=lambda r: r["best_recovery_bpm"], reverse=True)
    best_5 = sorted_by_recovery[:5]
    worst_5 = sorted_by_recovery[-5:]

    cooldown_records = [r for r in records if r["has_cooldown"]]
    no_cooldown = [r for r in records if not r["has_cooldown"]]

    overall_avg = _avg([r["best_recovery_bpm"] for r in records])
    if overall_avg and overall_avg >= 25:
        clinical = "Excellent autonomic function. Strong parasympathetic reactivation indicates high cardiovascular fitness."
    elif overall_avg and overall_avg >= 18:
        clinical = "Good HR recovery. Healthy autonomic balance. Continue current training approach."
    elif overall_avg and overall_avg >= 12:
        clinical = "Average HR recovery. Room for improvement — Zone 2 training and stress management will enhance parasympathetic tone."
    elif overall_avg:
        clinical = "Below average HR recovery (<12 bpm). Clinical flag per Cole et al. (NEJM). Discuss with physician."
    else:
        clinical = "Insufficient data for clinical assessment."

    bod = []
    if trend_direction == "improving":
        bod.append(f"Attia: HR recovery improving by {trend_delta} bpm — cardiovascular fitness trending in the right direction.")
    elif trend_direction == "declining":
        bod.append(f"Huberman: HR recovery declining by {abs(trend_delta)} bpm — consider overtraining, sleep debt, or chronic stress.")
    if cooldown_records and no_cooldown:
        bod.append(f"Galpin: {len(cooldown_records)} of {total} activities include cooldown. Adding 5-min easy cooldown improves recovery data reliability.")
    if dist["below_average"] > 0 and dist["below_average"] / total > 0.3:
        bod.append("Attia: >30% of sessions show below-average recovery. Consider reducing volume and prioritizing sleep.")

    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "total_activities_with_hr_recovery": total,
        "overall_avg_recovery_bpm": overall_avg,
        "clinical_assessment": clinical,
        "trend": {
            "direction": trend_direction, "delta_bpm": trend_delta,
            "first_half_avg": first_avg, "second_half_avg": second_avg,
            "pearson_r": r_val,
            "interpretation": (
                f"HR recovery {'improving' if trend_direction == 'improving' else 'declining' if trend_direction == 'declining' else 'stable'} "
                f"over the period ({'+' if (trend_delta or 0) > 0 else ''}{trend_delta} bpm)."
            ) if trend_delta is not None else None,
        },
        "classification_distribution": dist,
        "classification_distribution_pct": dist_pct,
        "by_sport_type": sport_summary,
        "cooldown_analysis": {
            "activities_with_cooldown": len(cooldown_records),
            "activities_without_cooldown": len(no_cooldown),
            "avg_recovery_with_cooldown": _avg([r["best_recovery_bpm"] for r in cooldown_records]),
            "avg_recovery_without_cooldown": _avg([r["best_recovery_bpm"] for r in no_cooldown]),
            "note": "Activities with cooldown give more reliable HR recovery measurements.",
        },
        "best_recoveries": [{k: v for k, v in r.items() if k != "classification"} for r in best_5],
        "worst_recoveries": [{k: v for k, v in r.items() if k != "classification"} for r in worst_5],
        "board_of_directors": bod,
        "methodology": (
            "HR recovery computed from Strava HR streams during ingestion. "
            "Peak HR = 30s rolling average max. Recovery = peak minus HR at peak+60s (preferred) "
            "or peak minus last-60s average (fallback). Clinical thresholds per Cole et al. (NEJM 1999): "
            ">25 excellent, 18-25 good, 12-18 average, <12 below average."
        ),
        "source": "strava (HR streams)",
    }

'''

insert_point = content.find("\nTOOLS = {")
if insert_point == -1:
    print("ERROR: Could not find TOOLS dict")
    sys.exit(1)
content = content[:insert_point] + "\n" + tool_func + content[insert_point:]
print("Inserted tool_get_hr_recovery_trend function")

# ── 3b: Add TOOLS entry ──
tools_entry = '''
    "get_hr_recovery_trend": {
        "fn": tool_get_hr_recovery_trend,
        "schema": {
            "name": "get_hr_recovery_trend",
            "description": (
                "Heart rate recovery tracker — the strongest exercise-derived mortality predictor (Cole et al., NEJM). "
                "Extracts post-peak HR recovery from Strava activity streams, trends over time, classifies against "
                "clinical thresholds (>25 excellent, 18-25 good, 12-18 average, <12 abnormal). Shows sport-type "
                "breakdown, cooldown vs no-cooldown comparison, best/worst sessions, and fitness trajectory. "
                "Board of Directors provides longevity assessment. "
                "Use for: 'HR recovery trend', 'heart rate recovery', 'am I getting fitter?', "
                "'cardiovascular fitness trajectory', 'autonomic function', 'post-exercise HR drop'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 180 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "sport_type": {"type": "string", "description": "Filter by sport type (e.g. 'Run', 'Ride'). Case-insensitive."},
                    "cooldown_only": {"type": "boolean", "description": "Only include activities with detected cooldown. Default: false."},
                },
                "required": [],
            },
        },
    },'''

# Insert before the closing } of TOOLS dict — find last entry
marker = '"get_health_trajectory":'
idx = content.find(marker)
if idx == -1:
    # Try get_training_recommendation if #7 was deployed first
    marker = '"get_training_recommendation":'
    idx = content.find(marker)
if idx == -1:
    print("ERROR: Could not find last TOOLS entry")
    sys.exit(1)

# Find closing brace of that entry
depth = 0
found_first = False
end_idx = idx
for i in range(idx, len(content)):
    if content[i] == '{':
        depth += 1
        found_first = True
    elif content[i] == '}':
        depth -= 1
        if found_first and depth == 0:
            end_idx = i + 1
            break

if content[end_idx:end_idx+1] == ',':
    insert_at = end_idx + 1
else:
    content = content[:end_idx] + ',' + content[end_idx:]
    insert_at = end_idx + 1

content = content[:insert_at] + tools_entry + content[insert_at:]
print("Inserted TOOLS entry for get_hr_recovery_trend")

with open("mcp_server.py", "w") as f:
    f.write(content)

print("mcp_server.py patched successfully")
PYTHON_PATCH_MCP

echo "✅ MCP server patched"

# ── Step 4: Package and deploy Strava Lambda ────────────────────────────────
cd lambdas
rm -f strava_lambda.zip
zip strava_lambda.zip strava_lambda.py
cd ..

aws lambda update-function-code \
  --function-name strava-data-ingestion \
  --zip-file fileb://lambdas/strava_lambda.zip \
  --region us-west-2

echo "✅ Deployed: life-platform-strava Lambda"

# ── Step 5: Package and deploy MCP Lambda ───────────────────────────────────
cp mcp_server.py lambdas/mcp_server.py
cd lambdas
rm -f mcp_server.zip
zip mcp_server.zip mcp_server.py
cd ..

aws lambda update-function-code \
  --function-name life-platform-mcp \
  --zip-file fileb://lambdas/mcp_server.zip \
  --region us-west-2

echo "✅ Deployed: life-platform-mcp Lambda"

# ── Step 6: Verify ──────────────────────────────────────────────────────────
echo ""
echo "Verifying..."
TOOL_COUNT=$(grep -c '"fn":' mcp_server.py)
echo "MCP tool count: $TOOL_COUNT"
grep -c "fetch_activity_streams" lambdas/strava_lambda.py && echo "✅ Strava stream fetch present" || echo "❌ Strava stream fetch missing"
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Feature #8 deployed!"
echo "  - Strava Lambda: fetch_activity_streams added"
echo "  - MCP tool: get_hr_recovery_trend"
echo "  NOTE: HR recovery data populates going forward as new"
echo "  activities are ingested. Existing activities won't have it."
echo "  Try: 'Show my HR recovery trend'"
echo "═══════════════════════════════════════════════════════════════"
