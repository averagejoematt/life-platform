#!/bin/bash
# deploy_feature6_sleep_env.sh — Deploy Feature #6: Sleep Environment Optimization
# Two changes: Eight Sleep Lambda (temp data fetch) + MCP server (get_sleep_environment_analysis tool)
set -euo pipefail

echo "═══════════════════════════════════════════════════════════════"
echo "  Feature #6: Sleep Environment Optimization"
echo "  Eight Sleep Lambda + MCP server update"
echo "═══════════════════════════════════════════════════════════════"

cd ~/Documents/Claude/life-platform

# ── Step 1: Backups ─────────────────────────────────────────────────────────
cp lambdas/eightsleep_lambda.py lambdas/eightsleep_lambda.py.bak.f6
cp mcp_server.py mcp_server.py.bak.f6
echo "✅ Backups created (.bak.f6)"

# ── Step 2: Patch Eight Sleep Lambda ────────────────────────────────────────
python3 << 'PYTHON_PATCH_ES'
import sys

with open("lambdas/eightsleep_lambda.py", "r") as f:
    content = f.read()

# ── 2a: Add fetch_temperature_data function after compute_derived_fields ──
temp_funcs = '''

def fetch_temperature_data(user_id: str, access_token: str, wake_date: str, tz: str) -> dict:
    """
    Fetch bed temperature data from Eight Sleep intervals endpoint.
    Returns dict of temperature fields, or empty dict if unavailable.
    Always safe — never raises exceptions that would block normal ingestion.
    """
    from_date = (datetime.strptime(wake_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        data = api_get(
            f"/v2/users/{user_id}/intervals",
            access_token,
            params={"from": from_date, "to": wake_date, "tz": tz},
        )

        intervals = data.get("intervals") or data.get("data") or []
        if not intervals:
            print(f"No intervals data returned for {wake_date}")
            return {}

        target = None
        for interval in intervals:
            int_date = interval.get("day") or interval.get("date") or ""
            if int_date == wake_date:
                target = interval
                break
        if target is None and len(intervals) == 1:
            target = intervals[0]
        if target is None:
            print(f"No interval matching {wake_date}")
            return {}

        result = {}

        # Method 1: Top-level temperature fields
        if target.get("tempBedC") is not None:
            result["bed_temp_c"] = round(float(target["tempBedC"]), 1)
            result["bed_temp_f"] = round(float(target["tempBedC"]) * 9/5 + 32, 1)
        if target.get("tempRoomC") is not None:
            result["room_temp_c"] = round(float(target["tempRoomC"]), 1)
            result["room_temp_f"] = round(float(target["tempRoomC"]) * 9/5 + 32, 1)

        # Method 2: Timeseries temperature data
        ts = target.get("timeseries") or {}
        bed_temps = ts.get("tempBedC") or ts.get("tempBed") or []
        room_temps = ts.get("tempRoomC") or ts.get("tempRoom") or []

        if bed_temps and not result.get("bed_temp_c"):
            vals = []
            for point in bed_temps:
                if isinstance(point, (list, tuple)) and len(point) >= 2:
                    try: vals.append(float(point[1]))
                    except (ValueError, TypeError): pass
                elif isinstance(point, (int, float)):
                    vals.append(float(point))
            if vals:
                result["bed_temp_c"] = round(sum(vals) / len(vals), 1)
                result["bed_temp_f"] = round(result["bed_temp_c"] * 9/5 + 32, 1)
                result["bed_temp_min_c"] = round(min(vals), 1)
                result["bed_temp_max_c"] = round(max(vals), 1)

        if room_temps and not result.get("room_temp_c"):
            vals = []
            for point in room_temps:
                if isinstance(point, (list, tuple)) and len(point) >= 2:
                    try: vals.append(float(point[1]))
                    except (ValueError, TypeError): pass
                elif isinstance(point, (int, float)):
                    vals.append(float(point))
            if vals:
                result["room_temp_c"] = round(sum(vals) / len(vals), 1)
                result["room_temp_f"] = round(result["room_temp_c"] * 9/5 + 32, 1)

        # Method 3: Per-stage temperature settings (heating/cooling level)
        stages = target.get("stages") or []
        temp_levels = []
        for stage in stages:
            temp_info = stage.get("temp") or stage.get("temperature") or {}
            level = temp_info.get("level")
            if level is not None:
                try: temp_levels.append(float(level))
                except (ValueError, TypeError): pass
            stage_bed = temp_info.get("bedC") or temp_info.get("bed_temp_c")
            if stage_bed is not None and "bed_temp_c" not in result:
                try:
                    result["bed_temp_c"] = round(float(stage_bed), 1)
                    result["bed_temp_f"] = round(float(stage_bed) * 9/5 + 32, 1)
                except (ValueError, TypeError):
                    pass

        if temp_levels:
            result["temp_level_avg"] = round(sum(temp_levels) / len(temp_levels), 1)
            result["temp_level_min"] = round(min(temp_levels), 1)
            result["temp_level_max"] = round(max(temp_levels), 1)

        # Method 4: sleepQualityScore temperature hint
        sq = target.get("sleepQualityScore") or {}
        for key in ["temperature", "tempBedC", "bedTemp"]:
            val = sq.get(key)
            if isinstance(val, dict) and val.get("current") is not None and "bed_temp_c" not in result:
                try:
                    result["bed_temp_c"] = round(float(val["current"]), 1)
                    result["bed_temp_f"] = round(result["bed_temp_c"] * 9/5 + 32, 1)
                except (ValueError, TypeError):
                    pass

        if result:
            print(f"Temperature data found: {list(result.keys())}")
        else:
            print(f"No temperature data found in intervals response")
            print(f"  Interval keys: {list(target.keys())[:15]}")

        return result

    except urllib.error.HTTPError as e:
        print(f"Intervals endpoint error: HTTP {e.code}")
        return {}
    except Exception as e:
        print(f"Temperature fetch exception: {e}")
        return {}
'''

# Insert before parse_trends_for_date
marker = "def parse_trends_for_date("
idx = content.find(marker)
if idx == -1:
    print("ERROR: Could not find parse_trends_for_date")
    sys.exit(1)

content = content[:idx] + temp_funcs + "\n\n" + content[idx:]
print("Inserted fetch_temperature_data function")

# ── 2b: Modify ingest_day to call fetch_temperature_data and merge into db_item ──

# Add temp fetch after the trends API call and parse
old_parsed = """    parsed = parse_trends_for_date(trends, wake_date, bed_side, tz_offset=tz_offset)

    if parsed is None:
        print(f"No sleep data found for wake_date={wake_date}")
        return {}"""

new_parsed = """    parsed = parse_trends_for_date(trends, wake_date, bed_side, tz_offset=tz_offset)

    if parsed is None:
        print(f"No sleep data found for wake_date={wake_date}")
        return {}

    # ── Fetch temperature data (Feature #6: Sleep Environment) ────────────
    temp_data = fetch_temperature_data(user_id, token, wake_date, tz)"""

if old_parsed in content:
    content = content.replace(old_parsed, new_parsed)
    print("Added fetch_temperature_data call to ingest_day")
else:
    print("WARNING: Could not find parsed block in ingest_day")

# Merge temp_data into db_item — update the **parsed line
old_db = """        "ingested_at": datetime.now(timezone.utc).isoformat(),
        **parsed,
    }
    table.put_item(Item=floats_to_decimal(db_item))"""

new_db = """        "ingested_at": datetime.now(timezone.utc).isoformat(),
        **parsed,
        **(floats_to_decimal(temp_data) if temp_data else {}),
    }
    table.put_item(Item=floats_to_decimal(db_item))"""

if old_db in content:
    content = content.replace(old_db, new_db)
    print("Merged temp_data into DynamoDB write")
else:
    print("WARNING: Could not find db_item block — trying alternate pattern")
    # Try without the specific spacing
    if "**parsed," in content and "table.put_item(Item=floats_to_decimal(db_item))" in content:
        content = content.replace(
            "**parsed,\n    }\n    table.put_item",
            '**parsed,\n        **(floats_to_decimal(temp_data) if temp_data else {}),\n    }\n    table.put_item'
        )
        print("Merged temp_data into DynamoDB write (alternate)")

with open("lambdas/eightsleep_lambda.py", "w") as f:
    f.write(content)

print("eightsleep_lambda.py patched successfully")
PYTHON_PATCH_ES

echo "✅ Eight Sleep Lambda patched"

# ── Step 3: Patch MCP Server ────────────────────────────────────────────────
python3 << 'PYTHON_PATCH_MCP'
import sys

with open("mcp_server.py", "r") as f:
    content = f.read()

# ── 3a: Insert tool function before TOOLS dict ──
tool_func = '''
def tool_get_sleep_environment_analysis(args):
    """
    Sleep environment optimization. Correlates Eight Sleep bed temperature
    with sleep outcomes. Huberman: core body temp drop is #1 sleep trigger.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=180)).strftime("%Y-%m-%d"))

    es_items = query_source("eightsleep", start_date, end_date)
    if not es_items:
        return {"error": "No Eight Sleep data for range.", "start_date": start_date, "end_date": end_date}

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    SLEEP_METRICS = [
        ("sleep_efficiency_pct", "Sleep Efficiency %", "higher_is_better"),
        ("deep_pct",             "Deep Sleep %",       "higher_is_better"),
        ("rem_pct",              "REM %",              "higher_is_better"),
        ("sleep_score",          "Sleep Score",        "higher_is_better"),
        ("sleep_duration_hours", "Sleep Duration",     "higher_is_better"),
        ("time_to_sleep_min",    "Sleep Onset Latency","lower_is_better"),
        ("hrv_avg",              "HRV",                "higher_is_better"),
    ]

    records = []
    no_temp_count = 0

    for item in es_items:
        date = item.get("date")
        bed_temp_c = _sf(item.get("bed_temp_c"))
        bed_temp_f = _sf(item.get("bed_temp_f"))
        temp_level = _sf(item.get("temp_level_avg"))
        room_temp_c = _sf(item.get("room_temp_c"))
        room_temp_f = _sf(item.get("room_temp_f"))

        if bed_temp_c is not None and bed_temp_f is None:
            bed_temp_f = round(bed_temp_c * 9/5 + 32, 1)
        if bed_temp_f is not None and bed_temp_c is None:
            bed_temp_c = round((bed_temp_f - 32) * 5/9, 1)

        has_temp = bed_temp_f is not None or temp_level is not None
        if not has_temp:
            no_temp_count += 1
            continue

        eff = _sf(item.get("sleep_efficiency_pct"))
        score = _sf(item.get("sleep_score"))
        if eff is None and score is None:
            continue

        records.append({
            "date": date,
            "bed_temp_f": bed_temp_f, "bed_temp_c": bed_temp_c,
            "room_temp_f": room_temp_f, "room_temp_c": _sf(item.get("room_temp_c")),
            "temp_level": temp_level,
            "temp_level_min": _sf(item.get("temp_level_min")),
            "temp_level_max": _sf(item.get("temp_level_max")),
            "sleep_efficiency_pct": eff,
            "deep_pct": _sf(item.get("deep_pct")),
            "rem_pct": _sf(item.get("rem_pct")),
            "sleep_score": score,
            "sleep_duration_hours": _sf(item.get("sleep_duration_hours")),
            "time_to_sleep_min": _sf(item.get("time_to_sleep_min")),
            "hrv_avg": _sf(item.get("hrv_avg")),
        })

    if not records:
        return {
            "error": f"No nights with temperature data found. {no_temp_count} nights checked.",
            "start_date": start_date, "end_date": end_date,
            "tip": "Temperature data requires Eight Sleep ingestion v2.35.0+ (intervals API). Deploy and wait for new nights.",
        }

    has_bed_temp = sum(1 for r in records if r["bed_temp_f"] is not None)
    has_temp_level = sum(1 for r in records if r["temp_level"] is not None)
    use_bed_temp = has_bed_temp >= len(records) * 0.5
    use_temp_level = has_temp_level >= len(records) * 0.5

    # Bucket analysis by bed temperature (°F)
    bucket_data = {}
    if use_bed_temp:
        TEMP_BUCKETS = [
            ("below_64F", "Below 64°F (< 18°C)", lambda t: t < 64),
            ("64_66F",    "64-66°F (18-19°C)",    lambda t: 64 <= t < 66),
            ("66_68F",    "66-68°F (19-20°C)",    lambda t: 66 <= t < 68),
            ("68_70F",    "68-70°F (20-21°C)",    lambda t: 68 <= t < 70),
            ("70_72F",    "70-72°F (21-22°C)",    lambda t: 70 <= t < 72),
            ("above_72F", "Above 72°F (> 22°C)",  lambda t: t >= 72),
        ]
        for bucket_key, label, condition in TEMP_BUCKETS:
            b_records = [r for r in records if r["bed_temp_f"] is not None and condition(r["bed_temp_f"])]
            if not b_records:
                continue
            bucket_data[bucket_key] = {
                "label": label, "nights": len(b_records),
                "avg_bed_temp_f": _avg([r["bed_temp_f"] for r in b_records]),
                "metrics": {},
            }
            for field, mlabel, _ in SLEEP_METRICS:
                vals = [r[field] for r in b_records if r[field] is not None]
                if vals:
                    bucket_data[bucket_key]["metrics"][field] = {"label": mlabel, "avg": round(sum(vals)/len(vals), 2), "n": len(vals)}

    # Bucket analysis by temp level (-10 to +10)
    level_bucket_data = {}
    if use_temp_level:
        LEVEL_BUCKETS = [
            ("very_cool",  "Very Cool (-10 to -6)", lambda l: l <= -6),
            ("cool",       "Cool (-5 to -2)",       lambda l: -5 <= l <= -2),
            ("neutral",    "Neutral (-1 to +1)",    lambda l: -1 <= l <= 1),
            ("warm",       "Warm (+2 to +5)",       lambda l: 2 <= l <= 5),
            ("very_warm",  "Very Warm (+6 to +10)", lambda l: l >= 6),
        ]
        for bucket_key, label, condition in LEVEL_BUCKETS:
            b_records = [r for r in records if r["temp_level"] is not None and condition(r["temp_level"])]
            if not b_records:
                continue
            level_bucket_data[bucket_key] = {
                "label": label, "nights": len(b_records),
                "avg_level": _avg([r["temp_level"] for r in b_records]),
                "metrics": {},
            }
            for field, mlabel, _ in SLEEP_METRICS:
                vals = [r[field] for r in b_records if r[field] is not None]
                if vals:
                    level_bucket_data[bucket_key]["metrics"][field] = {"label": mlabel, "avg": round(sum(vals)/len(vals), 2), "n": len(vals)}

    # Pearson correlations
    temp_correlations = {}
    if use_bed_temp:
        temp_rows = [r for r in records if r["bed_temp_f"] is not None]
        for field, label, direction in SLEEP_METRICS:
            xs = [r["bed_temp_f"] for r in temp_rows if r[field] is not None]
            ys = [r[field] for r in temp_rows if r[field] is not None]
            r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
            if r_val is not None:
                if direction == "higher_is_better":
                    impact = "cooler_is_better" if r_val < -0.15 else ("warmer_is_better" if r_val > 0.15 else "no_significant_effect")
                else:
                    impact = "cooler_is_better" if r_val > 0.15 else ("warmer_is_better" if r_val < -0.15 else "no_significant_effect")
                temp_correlations[field] = {"label": label, "pearson_r": r_val, "n": len(xs), "impact": impact}

    level_correlations = {}
    if use_temp_level:
        level_rows = [r for r in records if r["temp_level"] is not None]
        for field, label, direction in SLEEP_METRICS:
            xs = [r["temp_level"] for r in level_rows if r[field] is not None]
            ys = [r[field] for r in level_rows if r[field] is not None]
            r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
            if r_val is not None:
                if direction == "higher_is_better":
                    impact = "cooler_is_better" if r_val < -0.15 else ("warmer_is_better" if r_val > 0.15 else "no_significant_effect")
                else:
                    impact = "cooler_is_better" if r_val > 0.15 else ("warmer_is_better" if r_val < -0.15 else "no_significant_effect")
                level_correlations[field] = {"label": label, "pearson_r": r_val, "n": len(xs), "impact": impact}

    # Find optimal temperature
    optimal = {}
    if bucket_data:
        best_bucket = None
        best_eff = 0
        for bk, bv in bucket_data.items():
            eff = (bv.get("metrics", {}).get("sleep_efficiency_pct", {}) or {}).get("avg", 0)
            if eff > best_eff and bv["nights"] >= 3:
                best_eff = eff
                best_bucket = bk
        if best_bucket:
            optimal["by_efficiency"] = {"bucket": bucket_data[best_bucket]["label"], "avg_efficiency": best_eff, "nights": bucket_data[best_bucket]["nights"]}

        best_deep_bucket = None
        best_deep = 0
        for bk, bv in bucket_data.items():
            deep = (bv.get("metrics", {}).get("deep_pct", {}) or {}).get("avg", 0)
            if deep > best_deep and bv["nights"] >= 3:
                best_deep = deep
                best_deep_bucket = bk
        if best_deep_bucket:
            optimal["by_deep_sleep"] = {"bucket": bucket_data[best_deep_bucket]["label"], "avg_deep_pct": best_deep, "nights": bucket_data[best_deep_bucket]["nights"]}

    # Room temperature analysis
    room_analysis = None
    room_records = [r for r in records if r.get("room_temp_f") is not None]
    if room_records:
        room_temps = [r["room_temp_f"] for r in room_records]
        room_analysis = {"avg_room_temp_f": _avg(room_temps), "min_room_temp_f": round(min(room_temps), 1), "max_room_temp_f": round(max(room_temps), 1), "nights_measured": len(room_records)}

    # Board of Directors
    bod = []
    bod.append("Huberman: The single most important environmental factor for sleep is temperature. A 2-3°F core body temperature drop initiates the sleep cascade. Cool the bedroom to 65-68°F.")
    cool_benefit = temp_correlations.get("sleep_efficiency_pct", {}).get("impact")
    if cool_benefit == "cooler_is_better":
        r_val = temp_correlations["sleep_efficiency_pct"]["pearson_r"]
        bod.append(f"Your data confirms: cooler bed temperatures correlate with better sleep efficiency (r={r_val}).")
    elif cool_benefit == "warmer_is_better":
        bod.append("Your data shows warmer temperatures correlating with better sleep — your baseline room may already be quite cool, or you run cold at night.")
    deep_impact = temp_correlations.get("deep_pct", {}).get("impact")
    if deep_impact == "cooler_is_better":
        bod.append("Walker: Deep sleep is most sensitive to temperature. Your data confirms cooler bed temps increase deep sleep %.")
    if optimal.get("by_efficiency"):
        bod.append(f"Attia: Your optimal temperature zone for sleep efficiency is {optimal['by_efficiency']['bucket']} based on {optimal['by_efficiency']['nights']} nights.")

    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "total_nights_with_temp_data": len(records),
        "nights_without_temp_data": no_temp_count,
        "temperature_summary": {
            "avg_bed_temp_f": _avg([r["bed_temp_f"] for r in records if r["bed_temp_f"]]),
            "avg_bed_temp_c": _avg([r["bed_temp_c"] for r in records if r["bed_temp_c"]]),
            "avg_temp_level": _avg([r["temp_level"] for r in records if r["temp_level"]]),
            "avg_room_temp_f": _avg([r["room_temp_f"] for r in records if r.get("room_temp_f")]),
        },
        "optimal_temperature": optimal,
        "bucket_analysis_bed_temp": bucket_data if bucket_data else None,
        "bucket_analysis_temp_level": level_bucket_data if level_bucket_data else None,
        "correlations_bed_temp": temp_correlations if temp_correlations else None,
        "correlations_temp_level": level_correlations if level_correlations else None,
        "room_temperature": room_analysis,
        "board_of_directors": bod,
        "methodology": (
            "Bed temperature from Eight Sleep intervals API. Sleep metrics from Eight Sleep trends. "
            "Bucket analysis splits nights by temperature range and compares average sleep outcomes. "
            "Pearson correlations quantify linear relationship between temperature and sleep quality. "
            "Optimal temperature = bucket with highest sleep efficiency among buckets with >= 3 nights. "
            "Clinical reference: Huberman/Walker recommend 65-68°F (18-20°C)."
        ),
        "source": "eightsleep (intervals + trends)",
    }

'''

insert_point = content.find("\nTOOLS = {")
if insert_point == -1:
    print("ERROR: Could not find TOOLS dict")
    sys.exit(1)
content = content[:insert_point] + "\n" + tool_func + content[insert_point:]
print("Inserted tool_get_sleep_environment_analysis function")

# ── 3b: Add TOOLS entry ──
tools_entry = '''
    "get_sleep_environment_analysis": {
        "fn": tool_get_sleep_environment_analysis,
        "schema": {
            "name": "get_sleep_environment_analysis",
            "description": (
                "Sleep environment optimization. Correlates Eight Sleep bed temperature settings "
                "(heating/cooling level, bed temp F/C) with sleep outcomes (efficiency, deep %, "
                "REM %, score, onset latency, HRV). Splits nights into temperature buckets, "
                "computes Pearson correlations, and identifies your optimal thermal sleep profile. "
                "Huberman: core body temperature is the #1 physiological sleep trigger. "
                "Walker: sleeping too warm is the most common modifiable sleep disruptor. "
                "Use for: 'optimal bed temperature', 'does temperature affect my sleep?', "
                "'Eight Sleep temperature correlation', 'sleep environment', 'bed cooling analysis', "
                "'what temperature should I set my Eight Sleep?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 180 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },'''

# Find the last TOOLS entry to insert after
# Try hr_recovery first (if #8 deployed before #6), then health_trajectory, then training_rec
for search_marker in ['"get_hr_recovery_trend":', '"get_training_recommendation":', '"get_health_trajectory":']:
    idx = content.find(search_marker)
    if idx != -1:
        break

if idx == -1:
    print("ERROR: Could not find any known last TOOLS entry")
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
print("Inserted TOOLS entry for get_sleep_environment_analysis")

with open("mcp_server.py", "w") as f:
    f.write(content)

print("mcp_server.py patched successfully")
PYTHON_PATCH_MCP

echo "✅ MCP server patched"

# ── Step 4: Package and deploy Eight Sleep Lambda ───────────────────────────
cd lambdas
rm -f eightsleep_lambda.zip
zip eightsleep_lambda.zip eightsleep_lambda.py
cd ..

aws lambda update-function-code \
  --function-name eightsleep-data-ingestion \
  --zip-file fileb://lambdas/eightsleep_lambda.zip \
  --region us-west-2

echo "✅ Deployed: life-platform-eightsleep Lambda"

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
grep -c "fetch_temperature_data" lambdas/eightsleep_lambda.py && echo "✅ Eight Sleep temp fetch present" || echo "❌ Eight Sleep temp fetch missing"
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Feature #6 deployed!"
echo "  - Eight Sleep Lambda: fetch_temperature_data added"
echo "  - MCP tool: get_sleep_environment_analysis"
echo "  NOTE: Temperature data populates going forward as new nights"
echo "  are ingested. Existing nights won't have temp data."
echo "  Try: 'What's my optimal bed temperature for sleep?'"
echo "═══════════════════════════════════════════════════════════════"
