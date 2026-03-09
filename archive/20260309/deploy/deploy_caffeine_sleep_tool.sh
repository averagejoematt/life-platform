#!/usr/bin/env bash
# deploy_caffeine_sleep_tool.sh — Add get_caffeine_sleep_correlation tool (v2.8.0)
#
# Patches mcp_server.py with:
#   1. New function: tool_get_caffeine_sleep_correlation (after tool_get_food_log)
#   2. New registry entry (after get_food_log in TOOL_REGISTRY)
#   3. Version bump to 2.8.0
# Then deploys to Lambda.
#
# Usage:
#   cd ~/Documents/Claude/life-platform
#   chmod +x deploy_caffeine_sleep_tool.sh
#   ./deploy_caffeine_sleep_tool.sh

set -euo pipefail

FUNCTION_NAME="life-platform-mcp"
REGION="us-west-2"
ZIP_FILE="mcp_server.zip"

info()  { echo "[INFO]  $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

cd "$(dirname "$0")"

# ── Safety check ──────────────────────────────────────────────────────────────
if grep -q "get_caffeine_sleep_correlation" mcp_server.py; then
    error "get_caffeine_sleep_correlation already exists in mcp_server.py. Aborting."
fi

info "Patching mcp_server.py with get_caffeine_sleep_correlation tool..."

# ── 1. Apply all patches via Python ───────────────────────────────────────────
python3 - << 'PYEOF'
import sys

with open("mcp_server.py", "r") as f:
    content = f.read()

# ── FUNCTION DEFINITION ──────────────────────────────────────────────────────
FUNCTION_CODE = r'''

# ── Tool: get_caffeine_sleep_correlation ─────────────────────────────────────

def tool_get_caffeine_sleep_correlation(args):
    """
    Personal caffeine cutoff finder. Scans MacroFactor food_log for caffeine-containing
    entries, finds the last caffeine intake time per day, then correlates with same-night
    Eight Sleep metrics. Splits days into time buckets to show where sleep degrades.
    Based on Huberman & Attia: caffeine timing is one of the highest-leverage sleep interventions.
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=89)).strftime("%Y-%m-%d"))

    mf_items = query_source("macrofactor", start_date, end_date)
    es_items = query_source("eightsleep",  start_date, end_date)

    if not mf_items:
        return {"error": "No MacroFactor data for range.", "start_date": start_date, "end_date": end_date}
    if not es_items:
        return {"error": "No Eight Sleep data for range.", "start_date": start_date, "end_date": end_date}

    # Index Eight Sleep by date
    sleep_by_date = {}
    for item in es_items:
        d = item.get("date")
        if d:
            sleep_by_date[d] = item

    def t2d(t):
        if not t:
            return None
        try:
            p = str(t).strip().split(":")
            return int(p[0]) + int(p[1]) / 60
        except Exception:
            return None

    def d2hm(d):
        if d is None:
            return None
        h = int(d) % 24
        m = int(round((d % 1) * 60))
        if m == 60:
            h += 1; m = 0
        return f"{h:02d}:{m:02d}"

    def _sf(v):
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    # ── Extract per-day caffeine timing + sleep metrics ──────────────────────
    daily_rows = []

    for mf_item in sorted(mf_items, key=lambda x: x.get("date", "")):
        date = mf_item.get("date")
        if not date:
            continue

        sleep = sleep_by_date.get(date)
        if not sleep:
            continue

        food_log = mf_item.get("food_log", [])
        total_caffeine = _sf(mf_item.get("total_caffeine_mg")) or 0

        # Find last caffeine intake time
        last_caffeine_time = None
        last_caffeine_food = None
        caffeine_entry_count = 0
        for entry in food_log:
            caf = _sf(entry.get("caffeine_mg"))
            if caf and caf > 0:
                td = t2d(entry.get("time"))
                if td is not None:
                    caffeine_entry_count += 1
                    if last_caffeine_time is None or td > last_caffeine_time:
                        last_caffeine_time = td
                        last_caffeine_food = entry.get("food_name", "Unknown")

        # Sleep metrics
        eff     = _sf(sleep.get("sleep_efficiency_pct"))
        deep    = _sf(sleep.get("deep_pct"))
        rem     = _sf(sleep.get("rem_pct"))
        score   = _sf(sleep.get("sleep_score"))
        dur     = _sf(sleep.get("sleep_duration_hours"))
        latency = _sf(sleep.get("time_to_sleep_min"))

        if eff is None and score is None and deep is None:
            continue

        # Categorize
        if total_caffeine < 1:
            bucket = "no_caffeine"
        elif last_caffeine_time is None:
            bucket = "unknown_time"
        elif last_caffeine_time < 12:
            bucket = "before_noon"
        elif last_caffeine_time < 14:
            bucket = "noon_to_2pm"
        elif last_caffeine_time < 16:
            bucket = "2pm_to_4pm"
        else:
            bucket = "after_4pm"

        daily_rows.append({
            "date": date,
            "total_caffeine_mg": round(total_caffeine, 1),
            "last_caffeine_time": last_caffeine_time,
            "last_caffeine_time_hm": d2hm(last_caffeine_time),
            "last_caffeine_food": last_caffeine_food,
            "caffeine_entries": caffeine_entry_count,
            "bucket": bucket,
            "sleep_efficiency_pct": eff,
            "deep_pct": deep,
            "rem_pct": rem,
            "sleep_score": score,
            "sleep_duration_hrs": dur,
            "time_to_sleep_min": latency,
        })

    if len(daily_rows) < 5:
        return {
            "error": f"Only {len(daily_rows)} days with both caffeine and sleep data. Need at least 5.",
            "hint": "Ensure MacroFactor food logging and Eight Sleep data overlap for the requested period.",
            "start_date": start_date, "end_date": end_date,
        }

    # ── Bucket analysis ──────────────────────────────────────────────────────
    SLEEP_METRICS = [
        ("sleep_efficiency_pct", "Sleep Efficiency %", "higher_is_better"),
        ("deep_pct",             "Deep Sleep %",       "higher_is_better"),
        ("rem_pct",              "REM %",              "higher_is_better"),
        ("sleep_score",          "Sleep Score",        "higher_is_better"),
        ("sleep_duration_hrs",   "Sleep Duration",     "higher_is_better"),
        ("time_to_sleep_min",    "Sleep Onset Latency","lower_is_better"),
    ]

    BUCKET_ORDER = ["no_caffeine", "before_noon", "noon_to_2pm", "2pm_to_4pm", "after_4pm"]
    BUCKET_LABELS = {
        "no_caffeine":  "No Caffeine",
        "before_noon":  "Last Caffeine Before Noon",
        "noon_to_2pm":  "Last Caffeine 12-2 PM",
        "2pm_to_4pm":   "Last Caffeine 2-4 PM",
        "after_4pm":    "Last Caffeine After 4 PM",
        "unknown_time": "Caffeine (time unknown)",
    }

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    bucket_data = {}
    for b in BUCKET_ORDER:
        b_rows = [r for r in daily_rows if r["bucket"] == b]
        if not b_rows:
            continue
        bucket_data[b] = {
            "label": BUCKET_LABELS[b],
            "days": len(b_rows),
            "avg_caffeine_mg": _avg([r["total_caffeine_mg"] for r in b_rows]),
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

    # ── Timing correlations (last caffeine time vs sleep) ────────────────────
    timed_rows = [r for r in daily_rows if r["last_caffeine_time"] is not None]

    timing_correlations = {}
    for field, label, direction in SLEEP_METRICS:
        xs = [r["last_caffeine_time"] for r in timed_rows if r[field] is not None]
        ys = [r[field]                for r in timed_rows if r[field] is not None]
        r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
        if r_val is not None:
            if direction == "higher_is_better":
                impact = "HARMFUL" if r_val < -0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            else:
                impact = "HARMFUL" if r_val > 0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            timing_correlations[field] = {
                "label": label, "pearson_r": r_val, "n": len(xs), "impact": impact,
                "interpretation": (
                    f"Later caffeine {'strongly ' if abs(r_val) > 0.4 else ''}correlates with "
                    f"{'worse' if impact == 'HARMFUL' else 'better' if impact == 'BENEFICIAL' else 'no significant change in'} "
                    f"{label.lower()}"
                ),
            }

    # ── Dose correlations (total caffeine mg vs sleep) ───────────────────────
    dose_correlations = {}
    caff_rows = [r for r in daily_rows if r["total_caffeine_mg"] > 0]
    for field, label, direction in SLEEP_METRICS:
        xs = [r["total_caffeine_mg"] for r in caff_rows if r[field] is not None]
        ys = [r[field]               for r in caff_rows if r[field] is not None]
        r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
        if r_val is not None:
            if direction == "higher_is_better":
                impact = "HARMFUL" if r_val < -0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            else:
                impact = "HARMFUL" if r_val > 0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            dose_correlations[field] = {"label": label, "pearson_r": r_val, "n": len(xs), "impact": impact}

    # ── Personal cutoff recommendation ───────────────────────────────────────
    recommendation = None
    cutoff_time = None
    if bucket_data:
        ref_buckets = ["no_caffeine", "before_noon"]
        ref_effs = []
        for b in ref_buckets:
            if b in bucket_data and "sleep_efficiency_pct" in bucket_data[b]["metrics"]:
                ref_effs.append(bucket_data[b]["metrics"]["sleep_efficiency_pct"]["avg"])
        ref_eff = max(ref_effs) if ref_effs else None

        if ref_eff is not None:
            degradation_threshold = 2.0
            for b in ["noon_to_2pm", "2pm_to_4pm", "after_4pm"]:
                if b in bucket_data and "sleep_efficiency_pct" in bucket_data[b]["metrics"]:
                    b_eff = bucket_data[b]["metrics"]["sleep_efficiency_pct"]["avg"]
                    if ref_eff - b_eff >= degradation_threshold:
                        cutoff_map = {"noon_to_2pm": "noon", "2pm_to_4pm": "2 PM", "after_4pm": "4 PM"}
                        cutoff_time = cutoff_map.get(b, b)
                        drop = round(ref_eff - b_eff, 1)
                        recommendation = (
                            f"Your sleep efficiency drops by {drop} percentage points when your last caffeine "
                            f"is after {cutoff_time}. Based on your data, your personal caffeine cutoff should be {cutoff_time}."
                        )
                        break

        if recommendation is None:
            eff_corr = timing_correlations.get("sleep_efficiency_pct")
            if eff_corr and eff_corr["impact"] == "HARMFUL":
                recommendation = (
                    f"No sharp cutoff detected in bucket analysis, but there is a continuous "
                    f"negative correlation (r={eff_corr['pearson_r']}) between later caffeine and sleep efficiency. "
                    f"Earlier is better for you -- aim for before 2 PM as a general guideline."
                )
                cutoff_time = "2 PM"
            else:
                recommendation = (
                    "Your data does not show a strong relationship between caffeine timing and sleep quality. "
                    "This could mean you metabolize caffeine efficiently, or there is not enough data yet. "
                    "Continue logging and re-check after 30+ days of data."
                )

    # ── Summary + alerts ─────────────────────────────────────────────────────
    all_caff_times = [r["last_caffeine_time"] for r in daily_rows if r["last_caffeine_time"] is not None]
    no_caff_days = sum(1 for r in daily_rows if r["bucket"] == "no_caffeine")

    summary = {
        "period": {"start_date": start_date, "end_date": end_date},
        "days_analyzed": len(daily_rows),
        "days_with_caffeine": len(all_caff_times),
        "days_without_caffeine": no_caff_days,
        "avg_last_caffeine_time": d2hm(sum(all_caff_times) / len(all_caff_times)) if all_caff_times else None,
        "avg_daily_caffeine_mg": _avg([r["total_caffeine_mg"] for r in daily_rows if r["total_caffeine_mg"] > 0]),
    }

    alerts = []
    if summary["avg_daily_caffeine_mg"] and summary["avg_daily_caffeine_mg"] > 400:
        alerts.append(
            f"Average daily caffeine is {summary['avg_daily_caffeine_mg']}mg -- exceeds the 400mg/day FDA safety threshold."
        )
    after_4_count = sum(1 for r in daily_rows if r["bucket"] == "after_4pm")
    if after_4_count > 0:
        pct = round(100 * after_4_count / len(daily_rows), 0)
        alerts.append(
            f"Caffeine consumed after 4 PM on {after_4_count} days ({pct:.0f}%). "
            "Caffeine has a half-life of 5-6 hours -- a 4 PM coffee means ~50% still circulating at 10 PM."
        )
    deep_corr = timing_correlations.get("deep_pct")
    if deep_corr and deep_corr["impact"] == "HARMFUL" and abs(deep_corr["pearson_r"]) > 0.25:
        alerts.append(
            f"Later caffeine correlates with reduced deep sleep (r={deep_corr['pearson_r']}). "
            "Deep/SWS is when growth hormone releases -- critical during weight loss to preserve lean mass."
        )

    return {
        "summary": summary,
        "recommendation": {
            "cutoff_time": cutoff_time,
            "text": recommendation,
            "evidence_basis": "bucket_comparison" if cutoff_time and "drops by" in (recommendation or "") else "correlation" if cutoff_time else "insufficient_data",
        },
        "bucket_comparison": bucket_data,
        "timing_correlations": timing_correlations,
        "dose_correlations": dose_correlations,
        "alerts": alerts,
        "daily_detail": [
            {
                "date": r["date"],
                "last_caffeine": r["last_caffeine_time_hm"],
                "last_caffeine_food": r["last_caffeine_food"],
                "caffeine_mg": r["total_caffeine_mg"],
                "sleep_eff": r["sleep_efficiency_pct"],
                "deep_pct": r["deep_pct"],
                "rem_pct": r["rem_pct"],
                "sleep_score": r["sleep_score"],
            }
            for r in daily_rows
        ],
    }
'''

# ── REGISTRY ENTRY ───────────────────────────────────────────────────────────
REGISTRY_ENTRY = '''    "get_caffeine_sleep_correlation": {
        "fn": tool_get_caffeine_sleep_correlation,
        "schema": {
            "name": "get_caffeine_sleep_correlation",
            "description": (
                "Personal caffeine cutoff finder. Scans MacroFactor food_log for caffeine-containing items, "
                "finds the last caffeine intake time per day, then correlates with same-night Eight Sleep "
                "data (efficiency, deep sleep %, REM %, sleep score, onset latency). "
                "Splits days into time buckets (no caffeine / before noon / noon-2pm / 2pm-4pm / after 4pm) "
                "and compares average sleep quality across buckets. Also runs Pearson correlations for "
                "both timing and dose effects. Generates a personal cutoff recommendation. "
                "Based on Huberman and Attia guidance that caffeine timing is one of the highest-leverage sleep interventions. "
                "Use for: 'what is my caffeine cutoff?', 'does caffeine affect my sleep?', "
                "'when should I stop drinking coffee?', 'how does caffeine timing affect my deep sleep?', "
                "'caffeine and sleep correlation'. Requires MacroFactor food log data + Eight Sleep data."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
'''

# ── PATCH 1: Insert function after tool_get_food_log ─────────────────────────
marker = "# ── Tool: get_habit_adherence"
if marker not in content:
    print(f"ERROR: Could not find marker: {marker}", file=sys.stderr)
    sys.exit(1)
content = content.replace(marker, FUNCTION_CODE + "\n" + marker)

# ── PATCH 2: Insert registry entry after get_food_log entry ──────────────────
registry_marker = '    # ── Habits / P40 tools'
if registry_marker not in content:
    print(f"ERROR: Could not find registry marker", file=sys.stderr)
    sys.exit(1)
content = content.replace(registry_marker, REGISTRY_ENTRY + registry_marker, 1)

# ── PATCH 3: Update version ──────────────────────────────────────────────────
content = content.replace('"version": "2.5.1"', '"version": "2.8.0"')

# ── PATCH 4: Update header comment ──────────────────────────────────────────
content = content.replace(
    'life-platform MCP Server v2.6.0',
    'life-platform MCP Server v2.8.0'
)

old_new_line = 'New in v2.6.0:'
new_block = """New in v2.8.0:
  - get_caffeine_sleep_correlation : personal caffeine cutoff finder -- MacroFactor food_log timing + Eight Sleep

New in v2.7.0:
  - Habitify integration: habitify added to SOURCES; Supplements added to P40_GROUPS;
    query_chronicling() SOT-aware; default SOT habits -> habitify

New in v2.6.0:"""
content = content.replace(old_new_line, new_block)

with open("mcp_server.py", "w") as f:
    f.write(content)

print("OK: mcp_server.py patched successfully")
PYEOF

# ── 2. Verify patch applied ──────────────────────────────────────────────────
if ! grep -q "get_caffeine_sleep_correlation" mcp_server.py; then
    error "Patch failed -- function not found in mcp_server.py"
fi

if ! grep -q '"version": "2.8.0"' mcp_server.py; then
    error "Patch failed -- version not updated to 2.8.0"
fi

TOOL_COUNT=$(grep -c '"fn":' mcp_server.py)
info "Tool count after patch: ${TOOL_COUNT} (was 44, expected 45)"

# ── 3. Package and deploy ────────────────────────────────────────────────────
info "Packaging Lambda..."
rm -f "${ZIP_FILE}"
zip -j "${ZIP_FILE}" mcp_server.py
info "Created ${ZIP_FILE}"

info "Deploying to Lambda..."
aws lambda update-function-code \
    --function-name "${FUNCTION_NAME}" \
    --zip-file "fileb://${ZIP_FILE}" \
    --region "${REGION}" > /dev/null

aws lambda wait function-updated \
    --function-name "${FUNCTION_NAME}" \
    --region "${REGION}"

aws lambda update-function-configuration \
    --function-name "${FUNCTION_NAME}" \
    --environment "Variables={DEPLOY_VERSION=2.8.0}" \
    --region "${REGION}" > /dev/null

aws lambda wait function-updated \
    --function-name "${FUNCTION_NAME}" \
    --region "${REGION}"

info "Lambda deployed: v2.8.0"

# ── 4. Verify deployment ─────────────────────────────────────────────────────
LAST_MODIFIED=$(aws lambda get-function-configuration \
    --function-name "${FUNCTION_NAME}" \
    --region "${REGION}" \
    --query "LastModified" --output text)
info "Lambda LastModified: ${LAST_MODIFIED}"

echo ""
echo "================================================================"
echo " v2.8.0 deployed -- get_caffeine_sleep_correlation"
echo "================================================================"
echo "  Tool count : ${TOOL_COUNT}"
echo "  Lambda     : ${FUNCTION_NAME}"
echo "  Modified   : ${LAST_MODIFIED}"
echo ""
echo "  Test in Claude Desktop:"
echo '    "What is my personal caffeine cutoff time?"'
echo ""
echo "  Note: Requires overlapping MacroFactor food log"
echo "  + Eight Sleep data. With only a few days of real"
echo "  MacroFactor data, results will be limited initially."
echo "  Re-test after 2+ weeks of consistent food logging."
echo ""
