#!/bin/bash
# deploy_feature9_supplement_log.sh — Feature #9: Supplement & Medication Log
# 3 new MCP tools. MCP-only change — no Lambda pipeline changes.
set -euo pipefail

echo "═══════════════════════════════════════════════════════════════"
echo "  Feature #9: Supplement & Medication Log"
echo "  3 MCP tools: log_supplement, get_supplement_log,"
echo "               get_supplement_correlation"
echo "═══════════════════════════════════════════════════════════════"

cd ~/Documents/Claude/life-platform

# ── Backup ──────────────────────────────────────────────────────────────────
cp mcp_server.py mcp_server.py.bak.f9
echo "✅ Backup: mcp_server.py.bak.f9"

# ── Patch ───────────────────────────────────────────────────────────────────
python3 << 'PYTHON_PATCH'
import sys

with open("mcp_server.py", "r") as f:
    content = f.read()

# ── Insert 3 tool functions before TOOLS dict ──
tool_funcs = '''

# ══════════════════════════════════════════════════════════════════════════════
# Feature #9: Supplement & Medication Log
# ══════════════════════════════════════════════════════════════════════════════

def tool_log_supplement(args):
    """
    Log a supplement or medication entry. Writes to DynamoDB supplements partition.
    Supports multiple entries per day (appends to existing list).
    """
    date = args.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    name = args.get("name", "").strip()
    if not name:
        return {"error": "Supplement name is required."}

    dose = args.get("dose")
    unit = args.get("unit", "")
    timing = args.get("timing", "")  # morning, with_meal, before_bed, etc.
    notes = args.get("notes", "")
    category = args.get("category", "supplement")  # supplement, medication, vitamin, mineral

    entry = {
        "name": name,
        "dose": Decimal(str(dose)) if dose is not None else None,
        "unit": unit,
        "timing": timing,
        "category": category,
        "notes": notes,
        "logged_at": datetime.utcnow().isoformat(),
    }
    # Remove None values
    entry = {k: v for k, v in entry.items() if v is not None and v != ""}

    table = boto3.resource("dynamodb", region_name="us-west-2").Table("life-platform")

    # Try to append to existing record, or create new
    try:
        table.update_item(
            Key={"pk": "USER#matthew#SOURCE#supplements", "sk": f"DATE#{date}"},
            UpdateExpression="SET #s = list_append(if_not_exists(#s, :empty), :entry), #d = :date, #src = :src, #ua = :ua",
            ExpressionAttributeNames={"#s": "supplements", "#d": "date", "#src": "source", "#ua": "updated_at"},
            ExpressionAttributeValues={
                ":entry": [entry],
                ":empty": [],
                ":date": date,
                ":src": "supplements",
                ":ua": datetime.utcnow().isoformat(),
            },
        )
    except Exception as e:
        return {"error": f"Failed to log supplement: {e}"}

    dose_str = f" {dose}{unit}" if dose else ""
    timing_str = f" ({timing})" if timing else ""
    return {
        "status": "logged",
        "date": date,
        "entry": f"{name}{dose_str}{timing_str}",
        "message": f"Logged {name}{dose_str}{timing_str} for {date}.",
    }


def tool_get_supplement_log(args):
    """
    Retrieve supplement/medication log for a date range.
    Shows what was taken, dosage, timing, and adherence patterns.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"))
    name_filter = (args.get("name") or "").strip().lower()

    items = query_source("supplements", start_date, end_date)
    if not items:
        return {"error": "No supplement data for range.", "start_date": start_date, "end_date": end_date,
                "tip": "Use log_supplement to start tracking. Example: log 500mg magnesium glycinate before bed."}

    all_entries = []
    by_supplement = {}
    by_date = {}

    for item in items:
        date = item.get("date")
        entries = item.get("supplements") or []
        day_entries = []
        for entry in entries:
            ename = entry.get("name", "")
            if name_filter and name_filter not in ename.lower():
                continue
            entry["date"] = date
            all_entries.append(entry)
            day_entries.append(entry)

            # Aggregate by supplement name
            key = ename.lower()
            if key not in by_supplement:
                by_supplement[key] = {"name": ename, "days_taken": 0, "entries": [], "doses": [], "timings": set()}
            by_supplement[key]["days_taken"] += 1
            by_supplement[key]["entries"].append(entry)
            if entry.get("dose") is not None:
                by_supplement[key]["doses"].append(float(entry["dose"]))
            if entry.get("timing"):
                by_supplement[key]["timings"].add(entry["timing"])

        if day_entries:
            by_date[date] = day_entries

    if not all_entries:
        return {"error": f"No entries found{' for ' + name_filter if name_filter else ''}.",
                "start_date": start_date, "end_date": end_date}

    # Total days in range
    d_start = datetime.strptime(start_date, "%Y-%m-%d")
    d_end = datetime.strptime(end_date, "%Y-%m-%d")
    total_days = (d_end - d_start).days + 1
    days_logged = len(by_date)

    # Summary per supplement
    supplement_summary = []
    for key, data in sorted(by_supplement.items(), key=lambda x: x[1]["days_taken"], reverse=True):
        avg_dose = round(sum(data["doses"]) / len(data["doses"]), 1) if data["doses"] else None
        adherence_pct = round(data["days_taken"] / total_days * 100, 1)
        supplement_summary.append({
            "name": data["name"],
            "days_taken": data["days_taken"],
            "adherence_pct": adherence_pct,
            "avg_dose": avg_dose,
            "unit": data["entries"][0].get("unit", "") if data["entries"] else "",
            "typical_timings": sorted(data["timings"]),
            "category": data["entries"][0].get("category", "supplement") if data["entries"] else "",
        })

    # Recent log (last 7 days)
    recent = {}
    for date in sorted(by_date.keys(), reverse=True)[:7]:
        recent[date] = [{"name": e.get("name"), "dose": float(e["dose"]) if e.get("dose") else None,
                         "unit": e.get("unit", ""), "timing": e.get("timing", "")} for e in by_date[date]]

    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "total_days_in_range": total_days,
        "days_with_entries": days_logged,
        "total_entries": len(all_entries),
        "unique_supplements": len(by_supplement),
        "supplement_summary": supplement_summary,
        "recent_log": recent,
        "source": "supplements (manual log via log_supplement)",
    }


def tool_get_supplement_correlation(args):
    """
    Cross-reference supplement intake with health outcomes.
    Compares days taking a supplement vs days without across sleep, recovery, glucose, HRV.
    Enhances N=1 experiments with supplement-specific analysis.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))
    supplement_name = (args.get("name") or "").strip().lower()

    if not supplement_name:
        return {"error": "Supplement name required. Specify which supplement to analyze."}

    supp_items = query_source("supplements", start_date, end_date)
    if not supp_items:
        return {"error": "No supplement data for range.", "start_date": start_date, "end_date": end_date}

    # Find days with and without this supplement
    days_with = set()
    for item in supp_items:
        for entry in (item.get("supplements") or []):
            if supplement_name in (entry.get("name") or "").lower():
                days_with.add(item.get("date"))

    if not days_with:
        return {"error": f"No entries found for '{supplement_name}'.", "start_date": start_date, "end_date": end_date}

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    # Fetch health data
    sources = {"whoop": None, "eightsleep": None, "garmin": None, "apple_health": None}
    for src in sources:
        try:
            sources[src] = query_source(src, start_date, end_date)
        except Exception:
            pass

    # Build day-level metrics
    METRICS = [
        ("whoop", "recovery_score", "Whoop Recovery", "higher_is_better"),
        ("whoop", "hrv", "HRV", "higher_is_better"),
        ("whoop", "resting_heart_rate", "Resting HR", "lower_is_better"),
        ("eightsleep", "sleep_score", "Sleep Score", "higher_is_better"),
        ("eightsleep", "sleep_efficiency_pct", "Sleep Efficiency", "higher_is_better"),
        ("eightsleep", "deep_pct", "Deep Sleep %", "higher_is_better"),
        ("eightsleep", "rem_pct", "REM %", "higher_is_better"),
        ("eightsleep", "time_to_sleep_min", "Sleep Onset", "lower_is_better"),
        ("garmin", "body_battery_high", "Body Battery", "higher_is_better"),
        ("garmin", "avg_stress", "Garmin Stress", "lower_is_better"),
        ("apple_health", "blood_glucose_avg", "Glucose Avg", "lower_is_better"),
    ]

    # Index source data by date
    by_date = {}
    for src, items in sources.items():
        if not items:
            continue
        for item in items:
            d = item.get("date")
            if d not in by_date:
                by_date[d] = {}
            by_date[d][src] = item

    # All dates in range
    all_dates = set(by_date.keys())
    days_without = all_dates - days_with

    # Compare metrics
    comparisons = []
    for src, field, label, direction in METRICS:
        with_vals = []
        without_vals = []
        for d in days_with:
            if d in by_date and src in by_date[d]:
                v = _sf(by_date[d][src].get(field))
                if v is not None:
                    with_vals.append(v)
        for d in days_without:
            if d in by_date and src in by_date[d]:
                v = _sf(by_date[d][src].get(field))
                if v is not None:
                    without_vals.append(v)

        if len(with_vals) >= 3 and len(without_vals) >= 3:
            avg_with = _avg(with_vals)
            avg_without = _avg(without_vals)
            delta = round(avg_with - avg_without, 2)

            if direction == "higher_is_better":
                effect = "positive" if delta > 0 else ("negative" if delta < 0 else "neutral")
            else:
                effect = "positive" if delta < 0 else ("negative" if delta > 0 else "neutral")

            comparisons.append({
                "metric": label,
                "avg_with_supplement": avg_with,
                "avg_without_supplement": avg_without,
                "delta": delta,
                "effect": effect,
                "n_with": len(with_vals),
                "n_without": len(without_vals),
            })

    # Board of Directors
    bod = []
    positive_effects = [c for c in comparisons if c["effect"] == "positive"]
    negative_effects = [c for c in comparisons if c["effect"] == "negative"]

    if positive_effects:
        metrics = ", ".join([c["metric"] for c in positive_effects[:3]])
        bod.append(f"Attia: {supplement_name.title()} shows positive association with {metrics}. Correlation ≠ causation — consider running a formal N=1 experiment with create_experiment.")
    if negative_effects:
        metrics = ", ".join([c["metric"] for c in negative_effects[:3]])
        bod.append(f"Huberman: Possible negative association with {metrics}. Check timing and dosage — many supplements are timing-dependent.")
    if len(days_with) < 14:
        bod.append(f"Attia: Only {len(days_with)} days of data. Minimum 14 days recommended for meaningful N=1 analysis.")
    if not comparisons:
        bod.append("Insufficient overlapping data between supplement log and health metrics for comparison.")

    return {
        "supplement": supplement_name,
        "period": {"start_date": start_date, "end_date": end_date},
        "days_with_supplement": len(days_with),
        "days_without_supplement": len(days_without),
        "comparisons": comparisons,
        "board_of_directors": bod,
        "methodology": (
            "Compares average health metrics on days taking the supplement vs days without. "
            "Effect direction accounts for whether higher or lower is better for each metric. "
            "Requires >= 3 data points in each group. Correlation only — use N=1 experiments for causal inference."
        ),
        "source": "supplements + whoop + eightsleep + garmin + apple_health",
    }

'''

insert_point = content.find("\nTOOLS = {")
if insert_point == -1:
    print("ERROR: Could not find TOOLS dict")
    sys.exit(1)
content = content[:insert_point] + tool_funcs + content[insert_point:]
print("Inserted 3 supplement tool functions")

# ── Add TOOLS entries ──
tools_entries = '''
    "log_supplement": {
        "fn": tool_log_supplement,
        "schema": {
            "name": "log_supplement",
            "description": (
                "Log a supplement or medication. Writes to the supplements partition in DynamoDB. "
                "Supports name, dose, unit, timing (morning, with_meal, before_bed, post_workout), "
                "category (supplement, medication, vitamin, mineral), and notes. Multiple entries per day. "
                "Use for: 'log 500mg magnesium before bed', 'track my creatine', 'I took vitamin D this morning', "
                "'log my medication', 'supplement log entry'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Supplement or medication name (required)."},
                    "dose": {"type": "number", "description": "Dosage amount (e.g. 500 for 500mg)."},
                    "unit": {"type": "string", "description": "Unit: mg, mcg, g, IU, ml, capsule, tablet."},
                    "timing": {"type": "string", "description": "When taken: morning, with_meal, before_bed, post_workout, evening, afternoon."},
                    "category": {"type": "string", "description": "Category: supplement, medication, vitamin, mineral. Default: supplement."},
                    "notes": {"type": "string", "description": "Optional notes."},
                    "date": {"type": "string", "description": "Date YYYY-MM-DD (default: today)."},
                },
                "required": ["name"],
            },
        },
    },
    "get_supplement_log": {
        "fn": tool_get_supplement_log,
        "schema": {
            "name": "get_supplement_log",
            "description": (
                "Retrieve supplement/medication log. Shows what was taken, dosage, timing, adherence patterns, "
                "and per-supplement summary with adherence percentage. Filter by supplement name. "
                "Use for: 'show my supplement log', 'what supplements am I taking?', 'supplement adherence', "
                "'am I consistent with creatine?', 'medication history'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 30 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "name": {"type": "string", "description": "Filter by supplement name (partial match, case-insensitive)."},
                },
                "required": [],
            },
        },
    },
    "get_supplement_correlation": {
        "fn": tool_get_supplement_correlation,
        "schema": {
            "name": "get_supplement_correlation",
            "description": (
                "Cross-reference a specific supplement with health outcomes. Compares days taking the supplement "
                "vs days without across recovery, sleep, HRV, glucose, stress. Enhances N=1 experiments. "
                "Use for: 'is magnesium helping my sleep?', 'creatine impact on recovery', "
                "'does vitamin D affect my HRV?', 'supplement effectiveness', 'is this supplement working?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Supplement name to analyze (required). Partial match, case-insensitive."},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": ["name"],
            },
        },
    },'''

# Find last TOOLS entry
for marker in ['"get_sleep_environment_analysis":', '"get_hr_recovery_trend":', '"get_training_recommendation":', '"get_health_trajectory":']:
    idx = content.find(marker)
    if idx != -1:
        break
if idx == -1:
    print("ERROR: Could not find any TOOLS entry to insert after")
    sys.exit(1)

depth = 0
found_first = False
end_idx = idx
for i in range(idx, len(content)):
    if content[i] == '{': depth += 1; found_first = True
    elif content[i] == '}':
        depth -= 1
        if found_first and depth == 0: end_idx = i + 1; break

if content[end_idx:end_idx+1] == ',':
    insert_at = end_idx + 1
else:
    content = content[:end_idx] + ',' + content[end_idx:]
    insert_at = end_idx + 1

content = content[:insert_at] + tools_entries + content[insert_at:]
print("Inserted 3 TOOLS entries")

with open("mcp_server.py", "w") as f:
    f.write(content)
print("mcp_server.py patched successfully")
PYTHON_PATCH

echo "✅ MCP server patched"

# ── Package and deploy ──────────────────────────────────────────────────────
cp mcp_server.py lambdas/mcp_server.py
cd lambdas && rm -f mcp_server.zip && zip mcp_server.zip mcp_server.py && cd ..

aws lambda update-function-code \
  --function-name life-platform-mcp \
  --zip-file fileb://lambdas/mcp_server.zip \
  --region us-west-2

# ── Verify ──────────────────────────────────────────────────────────────────
TOOL_COUNT=$(grep -c '"fn":' mcp_server.py)
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Feature #9 deployed! Tools: log_supplement,"
echo "  get_supplement_log, get_supplement_correlation"
echo "  MCP tool count: $TOOL_COUNT"
echo "  Schema: PK USER#matthew#SOURCE#supplements, SK DATE#YYYY-MM-DD"
echo "  Try: 'Log 500mg magnesium glycinate before bed'"
echo "═══════════════════════════════════════════════════════════════"
