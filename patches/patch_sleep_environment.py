"""
Feature #6: Sleep Environment Optimization
Two parts:
  A) Eight Sleep Lambda enhancement — fetch bed temperature data from intervals endpoint
  B) MCP tool — get_sleep_environment_analysis

Eight Sleep API temperature data sources:
  1. /v1/users/{user_id}/trends — may include tempBedC in sleepQualityScore (unparsed)
  2. /v2/users/{user_id}/intervals — detailed per-interval data with temp levels
  
The Lambda modification is ADDITIVE — if temp data isn't available, existing
ingestion continues normally with no changes.
"""

# ══════════════════════════════════════════════════════════════════════════════
# PART A — Add to eightsleep_lambda.py
# ══════════════════════════════════════════════════════════════════════════════

# 1. Add this function after compute_derived_fields (~line 280)
EIGHTSLEEP_TEMP_FETCH = '''

def fetch_temperature_data(user_id: str, access_token: str, wake_date: str, tz: str) -> dict:
    """
    Fetch bed temperature data from Eight Sleep intervals endpoint.
    
    The /v2/users/{user_id}/intervals endpoint returns per-interval sleep data
    including bed temperature (tempBedC), room temperature (tempRoomC), and
    the heating/cooling level setting (-10 to +10 scale).
    
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
        
        # Find the interval matching our wake date
        target = None
        for interval in intervals:
            # Intervals may have different date fields
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
            # Timeseries format: [[timestamp, value], ...]
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
            
            # Also try for bed/room temp from stage
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
        
        # Method 4: Check top-level score breakdown for temp hints
        sq = target.get("sleepQualityScore") or {}
        temp_sq = sq.get("temperature") or sq.get("tempBedC") or {}
        if isinstance(temp_sq, dict) and temp_sq.get("current") is not None:
            if "bed_temp_c" not in result:
                try:
                    result["bed_temp_c"] = round(float(temp_sq["current"]), 1)
                    result["bed_temp_f"] = round(result["bed_temp_c"] * 9/5 + 32, 1)
                except (ValueError, TypeError):
                    pass
        
        if result:
            print(f"Temperature data found: {list(result.keys())}")
        else:
            print(f"No temperature data found in intervals response")
            # Log available keys for debugging
            print(f"  Interval keys: {list(target.keys())[:15]}")
            if ts:
                print(f"  Timeseries keys: {list(ts.keys())[:10]}")
        
        return result
        
    except urllib.error.HTTPError as e:
        print(f"Intervals endpoint error: HTTP {e.code}")
        if e.code == 404:
            print("  Intervals endpoint not available for this account.")
        return {}
    except Exception as e:
        print(f"Temperature fetch exception: {e}")
        return {}


def extract_trends_temperature(trends_data: dict, wake_date: str) -> dict:
    """
    Check if the trends API response contains any temperature data we're not parsing.
    This is a secondary source — some Eight Sleep firmware versions include temp in trends.
    """
    days = trends_data.get("days") or []
    target = next((d for d in days if d.get("day") == wake_date), None)
    if target is None and len(days) == 1:
        target = days[0]
    if target is None:
        return {}
    
    result = {}
    
    # Check for direct temp fields
    for key in ["tempBedC", "bedTemperature", "bed_temp", "roomTemperature", "tempRoomC"]:
        val = target.get(key)
        if val is not None:
            try:
                fval = float(val)
                if "bed" in key.lower() or "Bed" in key:
                    result["bed_temp_c"] = round(fval, 1)
                    result["bed_temp_f"] = round(fval * 9/5 + 32, 1)
                else:
                    result["room_temp_c"] = round(fval, 1)
                    result["room_temp_f"] = round(fval * 9/5 + 32, 1)
            except (ValueError, TypeError):
                pass
    
    # Check nested in sleepQualityScore
    sq = target.get("sleepQualityScore") or {}
    for key in ["temperature", "tempBedC", "bedTemp"]:
        val = sq.get(key)
        if isinstance(val, dict) and val.get("current") is not None:
            try:
                result["bed_temp_c"] = round(float(val["current"]), 1)
                result["bed_temp_f"] = round(result["bed_temp_c"] * 9/5 + 32, 1)
            except (ValueError, TypeError):
                pass
    
    return result
'''

# 2. Integration in ingest_day() — add AFTER trends fetch, BEFORE parse_trends_for_date
#    (around line 430 in the original)
EIGHTSLEEP_INTEGRATION = '''
    # ── Fetch temperature data ────────────────────────────────────────────────
    temp_data = {}
    
    # Try trends response first (may contain temp we're not parsing)
    temp_data.update(extract_trends_temperature(trends, wake_date))
    
    # Try intervals endpoint for more detailed temp data
    intervals_temp = fetch_temperature_data(user_id, token, wake_date, tz)
    temp_data.update(intervals_temp)  # intervals data overrides trends data
'''

# 3. In the DynamoDB write section, merge temp_data into db_item:
#    After `**parsed,` add: `**floats_to_decimal(temp_data),`
EIGHTSLEEP_DB_MERGE = '''
    # Merge temperature data into the record
    if temp_data:
        db_item.update(floats_to_decimal(temp_data))
        print(f"Temperature data merged: {list(temp_data.keys())}")
'''


# ══════════════════════════════════════════════════════════════════════════════
# PART B — MCP tool: get_sleep_environment_analysis
# Add to mcp_server.py BEFORE TOOLS dict
# ══════════════════════════════════════════════════════════════════════════════

SLEEP_ENV_MCP_CODE = '''
def tool_get_sleep_environment_analysis(args):
    """
    Sleep environment optimization. Correlates Eight Sleep bed temperature settings
    with sleep outcomes (efficiency, deep %, REM %, score, onset latency, HRV).
    
    Huberman: Core body temperature drop is the #1 physiological trigger for sleep
    onset. The optimal sleeping environment is 65-68°F (18-20°C).
    
    Walker: A 2-3°F drop in core body temperature initiates sleep. Sleeping too
    warm is the most common modifiable environmental sleep disruptor.
    
    Splits nights into temperature buckets and compares sleep quality across them.
    Also computes Pearson correlations for temperature effects.
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
    
    # ── Extract records with temperature data ────────────────────────────────
    records = []
    no_temp_count = 0
    
    for item in es_items:
        date = item.get("date")
        
        # Get temperature data — try multiple fields
        bed_temp_c = _sf(item.get("bed_temp_c"))
        bed_temp_f = _sf(item.get("bed_temp_f"))
        temp_level = _sf(item.get("temp_level_avg"))
        room_temp_c = _sf(item.get("room_temp_c"))
        room_temp_f = _sf(item.get("room_temp_f"))
        
        # Convert C to F if needed
        if bed_temp_c is not None and bed_temp_f is None:
            bed_temp_f = round(bed_temp_c * 9/5 + 32, 1)
        if bed_temp_f is not None and bed_temp_c is None:
            bed_temp_c = round((bed_temp_f - 32) * 5/9, 1)
        
        has_temp = bed_temp_f is not None or temp_level is not None
        
        if not has_temp:
            no_temp_count += 1
            continue
        
        # Sleep metrics
        eff = _sf(item.get("sleep_efficiency_pct"))
        deep = _sf(item.get("deep_pct"))
        rem = _sf(item.get("rem_pct"))
        score = _sf(item.get("sleep_score"))
        duration = _sf(item.get("sleep_duration_hours"))
        latency = _sf(item.get("time_to_sleep_min"))
        hrv = _sf(item.get("hrv_avg"))
        
        if eff is None and score is None:
            continue
        
        records.append({
            "date": date,
            "bed_temp_f": bed_temp_f,
            "bed_temp_c": bed_temp_c,
            "room_temp_f": room_temp_f,
            "room_temp_c": _sf(item.get("room_temp_c")),
            "temp_level": temp_level,
            "temp_level_min": _sf(item.get("temp_level_min")),
            "temp_level_max": _sf(item.get("temp_level_max")),
            "sleep_efficiency_pct": eff,
            "deep_pct": deep,
            "rem_pct": rem,
            "sleep_score": score,
            "sleep_duration_hours": duration,
            "time_to_sleep_min": latency,
            "hrv_avg": hrv,
        })
    
    if not records:
        return {
            "error": f"No nights with temperature data found. {no_temp_count} nights checked but none had bed temperature data.",
            "start_date": start_date, "end_date": end_date,
            "tip": "Temperature data requires Eight Sleep ingestion v2.35.0+ which fetches from the intervals API. Run the deploy script and wait for new nights to accumulate.",
        }
    
    # ── Determine which temperature metric to use ────────────────────────────
    # Prefer bed_temp_f for buckets, fall back to temp_level
    has_bed_temp = sum(1 for r in records if r["bed_temp_f"] is not None)
    has_temp_level = sum(1 for r in records if r["temp_level"] is not None)
    
    use_bed_temp = has_bed_temp >= len(records) * 0.5
    use_temp_level = has_temp_level >= len(records) * 0.5
    
    # ── Bucket analysis by bed temperature (°F) ─────────────────────────────
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
                "label": label,
                "nights": len(b_records),
                "avg_bed_temp_f": _avg([r["bed_temp_f"] for r in b_records]),
                "metrics": {},
            }
            for field, mlabel, _ in SLEEP_METRICS:
                vals = [r[field] for r in b_records if r[field] is not None]
                if vals:
                    bucket_data[bucket_key]["metrics"][field] = {
                        "label": mlabel,
                        "avg": round(sum(vals) / len(vals), 2),
                        "n": len(vals),
                    }
    
    # ── Bucket analysis by Eight Sleep temp level (-10 to +10) ───────────────
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
                "label": label,
                "nights": len(b_records),
                "avg_level": _avg([r["temp_level"] for r in b_records]),
                "metrics": {},
            }
            for field, mlabel, _ in SLEEP_METRICS:
                vals = [r[field] for r in b_records if r[field] is not None]
                if vals:
                    level_bucket_data[bucket_key]["metrics"][field] = {
                        "label": mlabel,
                        "avg": round(sum(vals) / len(vals), 2),
                        "n": len(vals),
                    }
    
    # ── Pearson correlations ─────────────────────────────────────────────────
    temp_correlations = {}
    
    # Bed temp vs sleep metrics
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
                temp_correlations[field] = {
                    "label": label, "pearson_r": r_val, "n": len(xs), "impact": impact,
                }
    
    # Temp level vs sleep metrics
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
                level_correlations[field] = {
                    "label": label, "pearson_r": r_val, "n": len(xs), "impact": impact,
                }
    
    # ── Find optimal temperature ─────────────────────────────────────────────
    optimal = {}
    if bucket_data:
        # Find bucket with highest sleep efficiency
        best_bucket = None
        best_eff = 0
        for bk, bv in bucket_data.items():
            eff = (bv.get("metrics", {}).get("sleep_efficiency_pct", {}) or {}).get("avg", 0)
            if eff > best_eff and bv["nights"] >= 3:
                best_eff = eff
                best_bucket = bk
        if best_bucket:
            optimal["by_efficiency"] = {
                "bucket": bucket_data[best_bucket]["label"],
                "avg_efficiency": best_eff,
                "nights": bucket_data[best_bucket]["nights"],
            }
        
        # Find bucket with highest deep sleep
        best_deep_bucket = None
        best_deep = 0
        for bk, bv in bucket_data.items():
            deep = (bv.get("metrics", {}).get("deep_pct", {}) or {}).get("avg", 0)
            if deep > best_deep and bv["nights"] >= 3:
                best_deep = deep
                best_deep_bucket = bk
        if best_deep_bucket:
            optimal["by_deep_sleep"] = {
                "bucket": bucket_data[best_deep_bucket]["label"],
                "avg_deep_pct": best_deep,
                "nights": bucket_data[best_deep_bucket]["nights"],
            }
    
    # ── Room temperature analysis ────────────────────────────────────────────
    room_analysis = None
    room_records = [r for r in records if r.get("room_temp_f") is not None]
    if room_records:
        room_temps = [r["room_temp_f"] for r in room_records]
        room_analysis = {
            "avg_room_temp_f": _avg(room_temps),
            "min_room_temp_f": round(min(room_temps), 1),
            "max_room_temp_f": round(max(room_temps), 1),
            "nights_measured": len(room_records),
        }
    
    # ── Board of Directors ───────────────────────────────────────────────────
    bod = []
    
    # General temperature guidance
    bod.append("Huberman: The single most important environmental factor for sleep is temperature. "
               "A 2-3°F core body temperature drop initiates the sleep cascade. Cool the bedroom to 65-68°F.")
    
    # Specific insights from data
    cool_benefit = temp_correlations.get("sleep_efficiency_pct", {}).get("impact")
    if cool_benefit == "cooler_is_better":
        r_val = temp_correlations["sleep_efficiency_pct"]["pearson_r"]
        bod.append(f"Your data confirms: cooler bed temperatures correlate with better sleep efficiency "
                   f"(r={r_val}). This aligns with the core body temperature literature.")
    elif cool_benefit == "warmer_is_better":
        bod.append("Interesting: your data shows warmer temperatures correlating with better sleep. "
                   "This may indicate your baseline room temperature is already quite cool, "
                   "or you run cold at night. Individual thermoregulation varies.")
    
    deep_impact = temp_correlations.get("deep_pct", {}).get("impact")
    if deep_impact == "cooler_is_better":
        bod.append("Walker: Deep sleep (slow-wave sleep) is most sensitive to temperature. "
                   "Your data confirms that cooler bed temperatures increase deep sleep percentage.")
    
    if optimal.get("by_efficiency"):
        bod.append(f"Attia: Your optimal temperature zone for sleep efficiency is "
                   f"{optimal['by_efficiency']['bucket']} based on {optimal['by_efficiency']['nights']} nights of data.")
    
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
            "Pearson correlations quantify the linear relationship between temperature and sleep quality. "
            "Optimal temperature = bucket with highest sleep efficiency among buckets with >= 3 nights. "
            "Clinical reference: Huberman/Walker recommend bedroom temperature 65-68°F (18-20°C)."
        ),
        "source": "eightsleep (intervals + trends)",
    }
'''

SLEEP_ENV_TOOLS_ENTRY = '''
    "get_sleep_environment_analysis": {
        "fn": tool_get_sleep_environment_analysis,
        "schema": {
            "name": "get_sleep_environment_analysis",
            "description": (
                "Sleep environment optimization. Correlates Eight Sleep bed temperature settings "
                "(heating/cooling level, bed temp °F/°C) with sleep outcomes (efficiency, deep %, "
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

print("Feature #6 patch ready.")
print(f"Eight Sleep Lambda temp code: {len(EIGHTSLEEP_TEMP_FETCH.splitlines())} lines")
print(f"MCP tool code: {len(SLEEP_ENV_MCP_CODE.splitlines())} lines")
