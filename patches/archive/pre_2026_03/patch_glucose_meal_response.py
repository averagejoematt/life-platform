"""
patch_glucose_meal_response.py — Add glucose meal response tool to MCP server

Adds:
  1. S3 client initialization (s3_client + S3_BUCKET constant)
  2. _load_cgm_readings() helper — loads 5-min CGM readings from S3
  3. tool_get_glucose_meal_response() — Levels-style postprandial spike analysis
  4. Tool registration in TOOL_REGISTRY

Data flow:
  MacroFactor food_log (DynamoDB) — meals with HH:MM timestamps
  × CGM 5-min readings (S3: raw/cgm_readings/YYYY/MM/DD.json)
  = Per-meal glucose response: baseline, peak, spike, time-to-peak, score

Scoring (based on Levels/Attia/Huberman guidance):
  A: spike <15 mg/dL (minimal response)
  B: spike 15-30 (moderate, acceptable)
  C: spike 30-40 (elevated)
  D: spike 40-50 (high)
  F: spike >50 (alarm — insulin spike + inflammation)

Run from: ~/Documents/Claude/life-platform/
"""

INPUT  = "mcp_server.py"
OUTPUT = "mcp_server.py"


def patch():
    with open(INPUT, "r") as f:
        code = f.read()

    # ── 1. Add S3 client + bucket constant after existing AWS clients ─────
    old_clients = '''secrets  = boto3.client("secretsmanager", region_name="us-west-2")

USER_PREFIX     = "USER#matthew#SOURCE#"'''

    new_clients = '''secrets  = boto3.client("secretsmanager", region_name="us-west-2")
s3_client = boto3.client("s3", region_name="us-west-2")
S3_BUCKET = "matthew-life-platform"

USER_PREFIX     = "USER#matthew#SOURCE#"'''

    if old_clients not in code:
        raise RuntimeError("Could not find AWS clients section")
    code = code.replace(old_clients, new_clients)

    # ── 2. Add _load_cgm_readings helper + tool function before lambda_handler ──
    old_handler_section = '''# ── Lambda handler ────────────────────────────────────────────────────────────
def lambda_handler(event, context):'''

    meal_response_code = '''# ── Helper: load CGM readings from S3 ─────────────────────────────────────────

def _load_cgm_readings(date_str):
    """
    Load 5-minute CGM readings from S3 for a given date.
    Returns list of (hour_decimal, value_mg_dl) tuples sorted by time.
    """
    try:
        y, m, d = date_str.split("-")
        key = f"raw/cgm_readings/{y}/{m}/{d}.json"
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
        readings = json.loads(resp["Body"].read())
        result = []
        for r in readings:
            val = r.get("value")
            time_str = r.get("time", "")
            if val is None or not time_str:
                continue
            # Parse "2024-10-15 11:04:29 -0800" format
            try:
                parts = time_str.strip().split(" ")
                hms = parts[1].split(":")
                hour_dec = int(hms[0]) + int(hms[1]) / 60 + int(hms[2]) / 3600
                result.append((hour_dec, float(val)))
            except (IndexError, ValueError):
                continue
        return sorted(result, key=lambda x: x[0])
    except s3_client.exceptions.NoSuchKey:
        return []
    except Exception as e:
        logger.warning(f"CGM read failed for {date_str}: {e}")
        return []


# ── Tool: get_glucose_meal_response ───────────────────────────────────────────

def tool_get_glucose_meal_response(args):
    """
    Levels-style postprandial glucose response analysis.

    For each meal logged in MacroFactor, matches 5-min CGM readings from S3
    to compute: pre-meal baseline, peak glucose, spike magnitude, time-to-peak,
    time to return to baseline, and a letter grade.

    Aggregates: best/worst meals, macro correlations (carbs/fiber/protein vs spike),
    personal food scores across multiple days.

    Based on Attia, Huberman, Lustig: postprandial spikes >30 mg/dL drive insulin
    resistance, inflammation, and accelerated glycation. Fiber, protein, and fat
    blunt the spike; refined carbs and sugar amplify it.
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"))
    meal_gap_minutes = args.get("meal_gap_minutes", 30)
    baseline_window_min = 30  # minutes before meal for baseline
    postprandial_window_min = 120  # 2-hour response window

    def _sf(v):
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def t2d(t):
        """Convert HH:MM string to decimal hours."""
        if not t:
            return None
        try:
            p = str(t).strip().split(":")
            return int(p[0]) + int(p[1]) / 60
        except Exception:
            return None

    def d2hm(d):
        """Convert decimal hours to HH:MM string."""
        if d is None:
            return None
        h = int(d) % 24
        m = int(round((d % 1) * 60))
        if m == 60:
            h += 1
            m = 0
        return f"{h:02d}:{m:02d}"

    def score_spike(spike):
        """Grade a glucose spike magnitude."""
        if spike is None:
            return None
        if spike < 15:
            return "A"
        elif spike < 30:
            return "B"
        elif spike < 40:
            return "C"
        elif spike < 50:
            return "D"
        else:
            return "F"

    # ── Load MacroFactor food logs ────────────────────────────────────────
    mf_items = query_source("macrofactor", start_date, end_date)
    if not mf_items:
        return {"error": "No MacroFactor data for range.", "start_date": start_date, "end_date": end_date}

    all_meals = []
    food_scores = defaultdict(list)  # food_name -> list of spike values
    days_with_data = 0
    days_without_cgm = 0

    for mf_item in sorted(mf_items, key=lambda x: x.get("date", "")):
        date = mf_item.get("date")
        if not date:
            continue
        food_log = mf_item.get("food_log", [])
        if not food_log:
            continue

        # Load CGM readings for this day
        readings = _load_cgm_readings(date)
        if len(readings) < 20:  # need reasonable CGM coverage
            days_without_cgm += 1
            continue
        days_with_data += 1

        # ── Group food items into meals by timestamp proximity ────────
        entries_with_time = []
        for entry in food_log:
            td = t2d(entry.get("time"))
            if td is not None:
                entries_with_time.append((td, entry))
        entries_with_time.sort(key=lambda x: x[0])

        meals = []
        current_meal = []
        current_meal_start = None
        for td, entry in entries_with_time:
            if current_meal_start is None or (td - current_meal_start) * 60 > meal_gap_minutes:
                if current_meal:
                    meals.append(current_meal)
                current_meal = [(td, entry)]
                current_meal_start = td
            else:
                current_meal.append((td, entry))
        if current_meal:
            meals.append(current_meal)

        # ── Analyze each meal ─────────────────────────────────────────
        for meal_entries in meals:
            meal_time_dec = meal_entries[0][0]  # earliest item time
            meal_time_str = d2hm(meal_time_dec)

            # Meal macros
            meal_cals = sum(_sf(e.get("calories_kcal")) or 0 for _, e in meal_entries)
            meal_carbs = sum(_sf(e.get("carbs_g")) or 0 for _, e in meal_entries)
            meal_protein = sum(_sf(e.get("protein_g")) or 0 for _, e in meal_entries)
            meal_fat = sum(_sf(e.get("fat_g")) or 0 for _, e in meal_entries)
            meal_fiber = sum(_sf(e.get("fiber_g")) or 0 for _, e in meal_entries)
            meal_sugar = sum(_sf(e.get("sugars_g")) or 0 for _, e in meal_entries)
            food_names = [e.get("food_name", "Unknown") for _, e in meal_entries]

            # Pre-meal baseline: avg glucose in 30 min before meal
            baseline_start = meal_time_dec - baseline_window_min / 60
            baseline_readings = [v for t, v in readings if baseline_start <= t < meal_time_dec]
            if len(baseline_readings) < 2:
                # Try wider window (45 min)
                baseline_start = meal_time_dec - 45 / 60
                baseline_readings = [v for t, v in readings if baseline_start <= t < meal_time_dec]
            if len(baseline_readings) < 2:
                continue  # can't compute without baseline

            baseline = sum(baseline_readings) / len(baseline_readings)

            # Postprandial window: 2 hours after meal start
            post_start = meal_time_dec
            post_end = meal_time_dec + postprandial_window_min / 60
            post_readings = [(t, v) for t, v in readings if post_start <= t <= post_end]
            if len(post_readings) < 4:
                continue  # insufficient coverage

            # Peak and timing
            peak_time, peak_value = max(post_readings, key=lambda x: x[1])
            spike = round(peak_value - baseline, 1)
            time_to_peak_min = round((peak_time - meal_time_dec) * 60, 0)

            # Time to return to baseline (within 2hr window)
            returned_at = None
            if spike > 5:  # only track return if meaningful spike
                for t, v in post_readings:
                    if t > peak_time and v <= baseline + 5:
                        returned_at = round((t - meal_time_dec) * 60, 0)
                        break

            # AUC above baseline (trapezoidal, in mg/dL-minutes)
            auc = 0.0
            sorted_post = sorted(post_readings, key=lambda x: x[0])
            for i in range(1, len(sorted_post)):
                t0, v0 = sorted_post[i - 1]
                t1, v1 = sorted_post[i]
                dt_min = (t1 - t0) * 60
                excess0 = max(0, v0 - baseline)
                excess1 = max(0, v1 - baseline)
                auc += (excess0 + excess1) / 2 * dt_min

            grade = score_spike(spike)

            meal_record = {
                "date": date,
                "meal_time": meal_time_str,
                "foods": food_names[:8],  # cap at 8 for readability
                "item_count": len(food_names),
                "calories": round(meal_cals),
                "carbs_g": round(meal_carbs, 1),
                "protein_g": round(meal_protein, 1),
                "fat_g": round(meal_fat, 1),
                "fiber_g": round(meal_fiber, 1),
                "sugar_g": round(meal_sugar, 1),
                "baseline_mg_dl": round(baseline, 1),
                "peak_mg_dl": round(peak_value, 1),
                "spike_mg_dl": spike,
                "time_to_peak_min": int(time_to_peak_min),
                "return_to_baseline_min": int(returned_at) if returned_at else None,
                "auc_above_baseline": round(auc, 1),
                "grade": grade,
            }
            all_meals.append(meal_record)

            # Track per-food scores
            for _, entry in meal_entries:
                fn = entry.get("food_name", "Unknown")
                food_scores[fn].append(spike)

    if not all_meals:
        return {
            "error": "No meals with matching CGM data found.",
            "days_checked": len(mf_items),
            "days_without_cgm": days_without_cgm,
            "hint": "Need overlapping MacroFactor food logs + CGM readings on the same days.",
        }

    # ── Aggregate analysis ────────────────────────────────────────────────
    spikes = [m["spike_mg_dl"] for m in all_meals]
    grades = [m["grade"] for m in all_meals]
    avg_spike = round(sum(spikes) / len(spikes), 1)

    # Grade distribution
    grade_dist = {}
    for g in ["A", "B", "C", "D", "F"]:
        ct = grades.count(g)
        if ct > 0:
            grade_dist[g] = ct

    # Best and worst meals
    sorted_by_spike = sorted(all_meals, key=lambda x: x["spike_mg_dl"])
    best_meals = sorted_by_spike[:5]
    worst_meals = sorted_by_spike[-5:][::-1]

    # Food scores (foods appearing 2+ times)
    food_summary = []
    for fn, spikes_list in sorted(food_scores.items()):
        if len(spikes_list) >= 2:
            avg_s = round(sum(spikes_list) / len(spikes_list), 1)
            food_summary.append({
                "food": fn,
                "appearances": len(spikes_list),
                "avg_spike": avg_s,
                "grade": score_spike(avg_s),
            })
    food_summary.sort(key=lambda x: x["avg_spike"])

    # Macro correlations (carbs, fiber, protein, sugar vs spike)
    correlations = {}
    for macro_field, label in [
        ("carbs_g", "carbs"), ("fiber_g", "fiber"),
        ("protein_g", "protein"), ("fat_g", "fat"),
        ("sugar_g", "sugar"), ("calories", "calories"),
    ]:
        xs = [m[macro_field] for m in all_meals if m.get(macro_field) is not None]
        ys = [m["spike_mg_dl"] for m in all_meals if m.get(macro_field) is not None]
        if len(xs) >= 7:
            r_val = pearson_r(xs, ys)
            if r_val is not None:
                correlations[f"{label}_vs_spike"] = round(r_val, 3)

    # Fiber-to-carb ratio analysis
    high_fiber_meals = [m for m in all_meals if m["carbs_g"] > 10 and m["fiber_g"] / max(m["carbs_g"], 1) > 0.15]
    low_fiber_meals = [m for m in all_meals if m["carbs_g"] > 10 and m["fiber_g"] / max(m["carbs_g"], 1) <= 0.15]
    fiber_ratio_impact = None
    if len(high_fiber_meals) >= 3 and len(low_fiber_meals) >= 3:
        hf_avg = round(sum(m["spike_mg_dl"] for m in high_fiber_meals) / len(high_fiber_meals), 1)
        lf_avg = round(sum(m["spike_mg_dl"] for m in low_fiber_meals) / len(low_fiber_meals), 1)
        fiber_ratio_impact = {
            "high_fiber_ratio_meals": len(high_fiber_meals),
            "high_fiber_avg_spike": hf_avg,
            "low_fiber_ratio_meals": len(low_fiber_meals),
            "low_fiber_avg_spike": lf_avg,
            "fiber_benefit_mg_dl": round(lf_avg - hf_avg, 1),
        }

    # Personal recommendation
    rec = []
    if avg_spike > 40:
        rec.append("Average spike is HIGH (>40 mg/dL). Prioritize reducing refined carbs and adding fiber/protein to meals.")
    elif avg_spike > 30:
        rec.append("Average spike is ELEVATED (30-40 mg/dL). Good opportunity to optimize meal composition.")
    elif avg_spike > 15:
        rec.append("Average spike is MODERATE (15-30 mg/dL). Solid metabolic health — fine-tune worst offenders.")
    else:
        rec.append("Average spike is EXCELLENT (<15 mg/dL). Outstanding glucose control.")

    if correlations.get("fiber_vs_spike") and correlations["fiber_vs_spike"] < -0.15:
        rec.append(f"Fiber is protective (r={correlations['fiber_vs_spike']}). Keep prioritizing high-fiber meals.")
    if correlations.get("sugar_vs_spike") and correlations["sugar_vs_spike"] > 0.2:
        rec.append(f"Sugar drives spikes (r={correlations['sugar_vs_spike']}). Reduce added sugars.")

    return {
        "period": {"start": start_date, "end": end_date},
        "data_coverage": {
            "days_with_food_log": len(mf_items),
            "days_with_cgm": days_with_data,
            "days_without_cgm": days_without_cgm,
            "total_meals_analyzed": len(all_meals),
        },
        "summary": {
            "avg_spike_mg_dl": avg_spike,
            "avg_grade": score_spike(avg_spike),
            "grade_distribution": grade_dist,
            "avg_time_to_peak_min": round(sum(m["time_to_peak_min"] for m in all_meals) / len(all_meals)),
        },
        "best_meals": best_meals,
        "worst_meals": worst_meals,
        "food_scores": food_summary[:20] if food_summary else None,
        "macro_correlations": correlations if correlations else None,
        "fiber_ratio_impact": fiber_ratio_impact,
        "recommendation": rec,
        "meals": all_meals[-30:],  # last 30 meals for detail
        "note": "Scoring: A (<15 spike), B (15-30), C (30-40), D (40-50), F (>50 mg/dL). "
                "Based on Attia/Huberman: spikes >30 drive insulin resistance. "
                "Fiber, protein, fat blunt spikes; refined carbs and sugar amplify them.",
    }


''' + old_handler_section

    if old_handler_section not in code:
        raise RuntimeError("Could not find Lambda handler section")
    code = code.replace(old_handler_section, meal_response_code)

    # ── 3. Add tool registration ──────────────────────────────────────────
    old_glucose_exercise_reg = '''    "get_glucose_exercise_correlation": {
        "fn": tool_get_glucose_exercise_correlation,
        "schema": {
            "name": "get_glucose_exercise_correlation",'''

    new_glucose_exercise_reg = '''    "get_glucose_meal_response": {
        "fn": tool_get_glucose_meal_response,
        "schema": {
            "name": "get_glucose_meal_response",
            "description": (
                "Levels-style postprandial glucose response analysis. For each meal logged in MacroFactor, "
                "matches 5-minute CGM readings to compute: pre-meal baseline, peak glucose, spike magnitude, "
                "time-to-peak, AUC, and a letter grade (A-F). Aggregates best/worst meals, per-food scores "
                "across days, and macro correlations (carbs/fiber/protein/sugar vs spike). "
                "Based on Attia, Huberman, Lustig: spikes >30 mg/dL drive insulin resistance and inflammation. "
                "Use for: 'which foods spike my glucose?', 'meal glucose response', 'food scoring', "
                "'postprandial analysis', 'best and worst meals for blood sugar', 'does fiber help my glucose?'. "
                "Requires MacroFactor food log + CGM data (Dexcom Stelo via Apple Health webhook)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date":        {"type": "string", "description": "Start date YYYY-MM-DD (default: 30 days ago)."},
                    "end_date":          {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "meal_gap_minutes":  {"type": "integer", "description": "Minutes gap to consider separate meals (default: 30)."},
                },
                "required": [],
            },
        },
    },
    "get_glucose_exercise_correlation": {
        "fn": tool_get_glucose_exercise_correlation,
        "schema": {
            "name": "get_glucose_exercise_correlation",'''

    if old_glucose_exercise_reg not in code:
        raise RuntimeError("Could not find get_glucose_exercise_correlation registration")
    code = code.replace(old_glucose_exercise_reg, new_glucose_exercise_reg)

    # ── 4. Update version in docstring ────────────────────────────────────
    code = code.replace(
        'life-platform MCP Server v2.16.0',
        'life-platform MCP Server v2.26.0'
    )

    # Update serverInfo version
    code = code.replace(
        '"version": "2.16.0"',
        '"version": "2.26.0"'
    )

    # Add new version note at top
    old_version_note = 'New in v2.14.0:'
    new_version_note = '''New in v2.26.0:
  - get_glucose_meal_response : Levels-style postprandial spike analysis -- MacroFactor food_log x S3 CGM readings
  - S3 client added for CGM 5-min reading access

New in v2.14.0:'''
    code = code.replace(old_version_note, new_version_note)

    with open(OUTPUT, "w") as f:
        f.write(code)

    print(f"✅ Patched {OUTPUT}")
    print("   - Added S3 client + S3_BUCKET constant")
    print("   - Added _load_cgm_readings() helper")
    print("   - Added tool_get_glucose_meal_response() (~200 lines)")
    print("   - Added tool registration with schema")
    print("   - Version bumped to v2.26.0")
    print(f"\nNext: deploy with deploy_glucose_meal_response.sh")


if __name__ == "__main__":
    patch()
