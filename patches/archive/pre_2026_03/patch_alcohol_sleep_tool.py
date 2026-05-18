"""
patch_alcohol_sleep_tool.py — Add get_alcohol_sleep_correlation tool (v2.14.0)

Patches mcp_server.py with:
  1. New function: tool_get_alcohol_sleep_correlation (after get_zone2_breakdown)
  2. New registry entry (after get_zone2_breakdown in TOOL_REGISTRY)
  3. Version bump 2.13.0 → 2.14.0
  4. Header update

Idempotent: aborts if tool already exists.

Usage:
    cd ~/Documents/Claude/life-platform
    python3 patch_alcohol_sleep_tool.py
"""

import sys

with open("mcp_server.py", "r") as f:
    content = f.read()

# ── Safety check ──────────────────────────────────────────────────────────────
if "get_alcohol_sleep_correlation" in content:
    print("SKIP: get_alcohol_sleep_correlation already exists in mcp_server.py")
    sys.exit(0)

# ── FUNCTION DEFINITION ──────────────────────────────────────────────────────
FUNCTION_CODE = r'''

# ── Tool: get_alcohol_sleep_correlation ──────────────────────────────────────

def tool_get_alcohol_sleep_correlation(args):
    """
    Personal alcohol impact analyzer. Correlates MacroFactor alcohol intake with
    same-night Eight Sleep data AND next-day Whoop recovery. Splits days into
    dose buckets (none / light / moderate / heavy), runs Pearson correlations for
    both dose and timing effects, and generates a personal impact assessment.

    One standard drink = ~14g pure alcohol (12oz beer, 5oz wine, 1.5oz spirits).
    Based on Huberman, Attia, and Walker: even moderate alcohol suppresses REM and
    deep sleep, raises resting HR, and impairs next-day HRV recovery.
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=89)).strftime("%Y-%m-%d"))

    mf_items = query_source("macrofactor", start_date, end_date)
    es_items = query_source("eightsleep",  start_date, end_date)
    wh_items = query_source("whoop",       start_date, end_date)

    if not mf_items:
        return {"error": "No MacroFactor data for range.", "start_date": start_date, "end_date": end_date}
    if not es_items:
        return {"error": "No Eight Sleep data for range.", "start_date": start_date, "end_date": end_date}

    # Index by date
    sleep_by_date = {}
    for item in es_items:
        d = item.get("date")
        if d:
            sleep_by_date[d] = item

    whoop_by_date = {}
    for item in (wh_items or []):
        d = item.get("date")
        if d:
            whoop_by_date[d] = item

    def _sf(v):
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def _t2d(t):
        """Time string HH:MM to decimal hours."""
        if not t:
            return None
        try:
            p = str(t).strip().split(":")
            return int(p[0]) + int(p[1]) / 60
        except Exception:
            return None

    def _d2hm(d):
        if d is None:
            return None
        h = int(d) % 24
        m = int(round((d % 1) * 60))
        if m == 60:
            h += 1; m = 0
        return f"{h:02d}:{m:02d}"

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    def _next_date(date_str):
        """Return the next day as YYYY-MM-DD."""
        d = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
        return d.strftime("%Y-%m-%d")

    # ── One standard drink = 14g pure alcohol ────────────────────────────────
    GRAMS_PER_DRINK = 14.0

    def _classify_dose(alcohol_g):
        if alcohol_g < 1:
            return "none"
        drinks = alcohol_g / GRAMS_PER_DRINK
        if drinks <= 1.0:
            return "light"       # ≤1 drink
        elif drinks <= 2.5:
            return "moderate"    # 1-2.5 drinks
        else:
            return "heavy"       # 3+ drinks

    # ── Extract per-day alcohol + sleep + next-day recovery ──────────────────
    daily_rows = []

    for mf_item in sorted(mf_items, key=lambda x: x.get("date", "")):
        date = mf_item.get("date")
        if not date:
            continue

        # Same-night sleep
        sleep = sleep_by_date.get(date)
        if not sleep:
            continue

        # Alcohol from day totals
        total_alcohol_g = _sf(mf_item.get("total_alcohol_g")) or 0

        # Alcohol timing from food_log
        food_log = mf_item.get("food_log", [])
        last_drink_time = None
        last_drink_food = None
        drink_entries = 0
        for entry in food_log:
            alc = _sf(entry.get("alcohol_g"))
            if alc and alc > 0:
                td = _t2d(entry.get("time"))
                if td is not None:
                    drink_entries += 1
                    if last_drink_time is None or td > last_drink_time:
                        last_drink_time = td
                        last_drink_food = entry.get("food_name", "Unknown")

        # Sleep metrics (same night)
        eff     = _sf(sleep.get("sleep_efficiency_pct"))
        deep    = _sf(sleep.get("deep_pct"))
        rem     = _sf(sleep.get("rem_pct"))
        score   = _sf(sleep.get("sleep_score"))
        dur     = _sf(sleep.get("sleep_duration_hours"))
        latency = _sf(sleep.get("time_to_sleep_min"))
        es_hrv  = _sf(sleep.get("hrv_avg"))

        if eff is None and score is None and deep is None:
            continue

        # Next-day Whoop recovery
        next_day = _next_date(date)
        whoop_next = whoop_by_date.get(next_day)
        next_recovery  = _sf(whoop_next.get("recovery_score")) if whoop_next else None
        next_hrv       = _sf(whoop_next.get("hrv")) if whoop_next else None
        next_rhr       = _sf(whoop_next.get("resting_heart_rate")) if whoop_next else None

        drinks = round(total_alcohol_g / GRAMS_PER_DRINK, 1) if total_alcohol_g > 0 else 0
        bucket = _classify_dose(total_alcohol_g)

        daily_rows.append({
            "date": date,
            "total_alcohol_g": round(total_alcohol_g, 1),
            "standard_drinks": drinks,
            "last_drink_time": last_drink_time,
            "last_drink_time_hm": _d2hm(last_drink_time),
            "last_drink_food": last_drink_food,
            "drink_entries": drink_entries,
            "bucket": bucket,
            # Same-night sleep
            "sleep_efficiency_pct": eff,
            "deep_pct": deep,
            "rem_pct": rem,
            "sleep_score": score,
            "sleep_duration_hrs": dur,
            "time_to_sleep_min": latency,
            "es_hrv": es_hrv,
            # Next-day recovery
            "next_recovery_score": next_recovery,
            "next_hrv": next_hrv,
            "next_rhr": next_rhr,
        })

    if len(daily_rows) < 5:
        return {
            "error": f"Only {len(daily_rows)} days with both nutrition and sleep data. Need at least 5.",
            "hint": "Ensure MacroFactor food logging and Eight Sleep data overlap. Re-check after 2+ weeks of consistent logging.",
            "start_date": start_date, "end_date": end_date,
        }

    # ── Metric definitions ───────────────────────────────────────────────────
    SLEEP_METRICS = [
        ("sleep_efficiency_pct", "Sleep Efficiency %",  "higher_is_better"),
        ("deep_pct",             "Deep Sleep %",        "higher_is_better"),
        ("rem_pct",              "REM %",               "higher_is_better"),
        ("sleep_score",          "Sleep Score",         "higher_is_better"),
        ("sleep_duration_hrs",   "Sleep Duration",      "higher_is_better"),
        ("time_to_sleep_min",    "Sleep Onset Latency", "lower_is_better"),
        ("es_hrv",               "Sleep HRV",           "higher_is_better"),
    ]

    RECOVERY_METRICS = [
        ("next_recovery_score",  "Next-Day Recovery",   "higher_is_better"),
        ("next_hrv",             "Next-Day HRV",        "higher_is_better"),
        ("next_rhr",             "Next-Day RHR",        "lower_is_better"),
    ]

    ALL_METRICS = SLEEP_METRICS + RECOVERY_METRICS

    # ── Bucket analysis ──────────────────────────────────────────────────────
    BUCKET_ORDER = ["none", "light", "moderate", "heavy"]
    BUCKET_LABELS = {
        "none":     "No Alcohol",
        "light":    "Light (≤1 drink / ≤14g)",
        "moderate": "Moderate (1-2.5 drinks / 14-35g)",
        "heavy":    "Heavy (3+ drinks / 35g+)",
    }

    bucket_data = {}
    for b in BUCKET_ORDER:
        b_rows = [r for r in daily_rows if r["bucket"] == b]
        if not b_rows:
            continue
        bucket_data[b] = {
            "label": BUCKET_LABELS[b],
            "days": len(b_rows),
            "avg_alcohol_g": _avg([r["total_alcohol_g"] for r in b_rows if r["total_alcohol_g"] > 0]),
            "avg_drinks": _avg([r["standard_drinks"] for r in b_rows if r["standard_drinks"] > 0]),
            "metrics": {},
        }
        for field, label, _ in ALL_METRICS:
            vals = [r[field] for r in b_rows if r[field] is not None]
            if vals:
                bucket_data[b]["metrics"][field] = {
                    "label": label,
                    "avg": round(sum(vals) / len(vals), 2),
                    "n": len(vals),
                }

    # ── Dose correlations (total alcohol g vs metrics) ───────────────────────
    dose_correlations = {}
    for field, label, direction in ALL_METRICS:
        xs = [r["total_alcohol_g"] for r in daily_rows if r[field] is not None]
        ys = [r[field]             for r in daily_rows if r[field] is not None]
        r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
        if r_val is not None:
            if direction == "higher_is_better":
                impact = "HARMFUL" if r_val < -0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            else:
                impact = "HARMFUL" if r_val > 0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            dose_correlations[field] = {
                "label": label, "pearson_r": r_val, "n": len(xs), "impact": impact,
            }

    # ── Timing correlations (last drink time vs sleep, drinking days only) ───
    timing_correlations = {}
    timed_rows = [r for r in daily_rows if r["last_drink_time"] is not None]
    for field, label, direction in SLEEP_METRICS:
        xs = [r["last_drink_time"] for r in timed_rows if r[field] is not None]
        ys = [r[field]             for r in timed_rows if r[field] is not None]
        r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
        if r_val is not None:
            if direction == "higher_is_better":
                impact = "HARMFUL" if r_val < -0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            else:
                impact = "HARMFUL" if r_val > 0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            timing_correlations[field] = {
                "label": label, "pearson_r": r_val, "n": len(xs), "impact": impact,
                "interpretation": (
                    f"Later drinking {'strongly ' if abs(r_val) > 0.4 else ''}correlates with "
                    f"{'worse' if impact == 'HARMFUL' else 'better' if impact == 'BENEFICIAL' else 'no significant change in'} "
                    f"{label.lower()}"
                ),
            }

    # ── Drinking vs sober comparison ─────────────────────────────────────────
    drinking_days = [r for r in daily_rows if r["bucket"] != "none"]
    sober_days    = [r for r in daily_rows if r["bucket"] == "none"]

    drinking_vs_sober = {}
    if drinking_days and sober_days:
        for field, label, direction in ALL_METRICS:
            dr_vals = [r[field] for r in drinking_days if r[field] is not None]
            so_vals = [r[field] for r in sober_days if r[field] is not None]
            if dr_vals and so_vals:
                dr_avg = round(sum(dr_vals) / len(dr_vals), 2)
                so_avg = round(sum(so_vals) / len(so_vals), 2)
                delta = round(dr_avg - so_avg, 2)
                if direction == "lower_is_better":
                    verdict = "BETTER" if delta < -1 else "WORSE" if delta > 1 else "SIMILAR"
                else:
                    verdict = "BETTER" if delta > 1 else "WORSE" if delta < -1 else "SIMILAR"
                drinking_vs_sober[field] = {
                    "label": label,
                    "drinking_avg": dr_avg,
                    "sober_avg": so_avg,
                    "delta": delta,
                    "verdict": verdict,
                    "drinking_n": len(dr_vals),
                    "sober_n": len(so_vals),
                }

    # ── Personal impact assessment ───────────────────────────────────────────
    assessment = None
    severity = None

    # Compare sober vs drinking bucket metrics
    if "none" in bucket_data and len(bucket_data) > 1:
        sober_eff = None
        if "sleep_efficiency_pct" in bucket_data["none"]["metrics"]:
            sober_eff = bucket_data["none"]["metrics"]["sleep_efficiency_pct"]["avg"]

        worst_bucket = None
        worst_drop = 0
        for b in ["light", "moderate", "heavy"]:
            if b in bucket_data and "sleep_efficiency_pct" in bucket_data[b]["metrics"]:
                b_eff = bucket_data[b]["metrics"]["sleep_efficiency_pct"]["avg"]
                if sober_eff is not None:
                    drop = sober_eff - b_eff
                    if drop > worst_drop:
                        worst_drop = drop
                        worst_bucket = b

        # Check REM impact (alcohol's most documented effect)
        sober_rem = None
        if "rem_pct" in bucket_data["none"]["metrics"]:
            sober_rem = bucket_data["none"]["metrics"]["rem_pct"]["avg"]

        rem_drops = {}
        for b in ["light", "moderate", "heavy"]:
            if b in bucket_data and "rem_pct" in bucket_data[b]["metrics"] and sober_rem:
                rem_drops[b] = round(sober_rem - bucket_data[b]["metrics"]["rem_pct"]["avg"], 1)

        # Check next-day recovery impact
        sober_rec = None
        rec_drops = {}
        if "next_recovery_score" in bucket_data["none"]["metrics"]:
            sober_rec = bucket_data["none"]["metrics"]["next_recovery_score"]["avg"]
        for b in ["light", "moderate", "heavy"]:
            if b in bucket_data and "next_recovery_score" in bucket_data[b]["metrics"] and sober_rec:
                rec_drops[b] = round(sober_rec - bucket_data[b]["metrics"]["next_recovery_score"]["avg"], 1)

        # Build assessment
        impacts = []
        if worst_drop >= 5:
            impacts.append(f"sleep efficiency drops {worst_drop:.1f} pts with {worst_bucket} drinking")
            severity = "HIGH"
        elif worst_drop >= 2:
            impacts.append(f"sleep efficiency drops {worst_drop:.1f} pts with {worst_bucket} drinking")
            severity = "MODERATE"

        for b, drop in rem_drops.items():
            if drop >= 3:
                impacts.append(f"REM drops {drop} pts with {b} drinking")
                if severity != "HIGH":
                    severity = "HIGH" if drop >= 5 else "MODERATE"

        for b, drop in rec_drops.items():
            if drop >= 5:
                impacts.append(f"next-day recovery drops {drop} pts with {b} drinking")
                severity = "HIGH"

        if impacts:
            assessment = "Alcohol is measurably affecting your recovery: " + "; ".join(impacts) + "."
        else:
            assessment = (
                "Your data does not yet show a strong alcohol impact on sleep or recovery. "
                "This could mean you metabolize alcohol well, drink infrequently, or there isn't enough data yet. "
                "Continue logging and re-check after 30+ days."
            )
            severity = "LOW"
    else:
        assessment = (
            "Not enough data to compare drinking vs sober nights. "
            "Continue logging food intake in MacroFactor for at least 2-3 weeks."
        )
        severity = "INSUFFICIENT_DATA"

    # ── Summary + alerts ─────────────────────────────────────────────────────
    drinking_count = len(drinking_days)
    sober_count = len(sober_days)
    all_drink_amounts = [r["total_alcohol_g"] for r in drinking_days if r["total_alcohol_g"] > 0]

    summary = {
        "period": {"start_date": start_date, "end_date": end_date},
        "days_analyzed": len(daily_rows),
        "drinking_days": drinking_count,
        "sober_days": sober_count,
        "drinking_frequency_pct": round(100 * drinking_count / len(daily_rows), 0) if daily_rows else 0,
        "avg_alcohol_g_on_drinking_days": _avg(all_drink_amounts),
        "avg_drinks_on_drinking_days": _avg([g / GRAMS_PER_DRINK for g in all_drink_amounts]) if all_drink_amounts else None,
        "avg_last_drink_time": _d2hm(
            sum(r["last_drink_time"] for r in timed_rows) / len(timed_rows)
        ) if timed_rows else None,
    }

    alerts = []

    # High frequency alert
    if summary["drinking_frequency_pct"] and summary["drinking_frequency_pct"] > 50:
        alerts.append(
            f"Alcohol consumed on {summary['drinking_frequency_pct']:.0f}% of days. "
            "Huberman and Attia recommend at minimum 3-4 alcohol-free days per week "
            "for liver recovery and hormonal regulation."
        )

    # REM suppression alert
    rem_corr = dose_correlations.get("rem_pct")
    if rem_corr and rem_corr["impact"] == "HARMFUL" and abs(rem_corr["pearson_r"]) > 0.2:
        alerts.append(
            f"Alcohol dose correlates with REM suppression (r={rem_corr['pearson_r']}). "
            "REM sleep is critical for emotional regulation, memory consolidation, and creativity. "
            "Even 1-2 drinks can reduce REM by 20-30% (Walker, 'Why We Sleep')."
        )

    # Deep sleep pseudo-enhancement warning
    deep_corr = dose_correlations.get("deep_pct")
    if deep_corr and deep_corr["impact"] == "BENEFICIAL":
        alerts.append(
            "Alcohol appears to increase deep sleep % -- but this is misleading. "
            "Alcohol-induced 'deep sleep' is actually sedation, not restorative SWS. "
            "It lacks the memory-consolidating neural oscillations of natural deep sleep."
        )

    # Next-day HRV impact
    hrv_corr = dose_correlations.get("next_hrv")
    if hrv_corr and hrv_corr["impact"] == "HARMFUL" and abs(hrv_corr["pearson_r"]) > 0.2:
        alerts.append(
            f"Higher alcohol intake correlates with lower next-day HRV (r={hrv_corr['pearson_r']}). "
            "Alcohol impairs parasympathetic recovery -- your autonomic nervous system is still stressed "
            "the morning after, even if you feel fine."
        )

    # Late drinking alert
    late_drinks = [r for r in timed_rows if r["last_drink_time"] and r["last_drink_time"] >= 21]
    if late_drinks:
        pct = round(100 * len(late_drinks) / len(timed_rows), 0) if timed_rows else 0
        alerts.append(
            f"Last drink after 9 PM on {len(late_drinks)} drinking days ({pct:.0f}%). "
            "Alcohol takes ~1 hour per standard drink to metabolize. Late drinking means "
            "active alcohol metabolism during early sleep cycles when deep sleep should peak."
        )

    return {
        "summary": summary,
        "assessment": {
            "text": assessment,
            "severity": severity,
        },
        "bucket_comparison": bucket_data,
        "drinking_vs_sober": drinking_vs_sober,
        "dose_correlations": dose_correlations,
        "timing_correlations": timing_correlations,
        "alerts": alerts,
        "daily_detail": [
            {
                "date": r["date"],
                "alcohol_g": r["total_alcohol_g"],
                "drinks": r["standard_drinks"],
                "last_drink": r["last_drink_time_hm"],
                "last_drink_food": r["last_drink_food"],
                "sleep_eff": r["sleep_efficiency_pct"],
                "deep_pct": r["deep_pct"],
                "rem_pct": r["rem_pct"],
                "sleep_score": r["sleep_score"],
                "next_recovery": r["next_recovery_score"],
                "next_hrv": r["next_hrv"],
            }
            for r in daily_rows
        ],
    }
'''

# ── REGISTRY ENTRY ───────────────────────────────────────────────────────────
REGISTRY_ENTRY = '''    "get_alcohol_sleep_correlation": {
        "fn": tool_get_alcohol_sleep_correlation,
        "schema": {
            "name": "get_alcohol_sleep_correlation",
            "description": (
                "Personal alcohol impact analyzer. Correlates MacroFactor alcohol intake (grams, standard drinks) "
                "with same-night Eight Sleep data (efficiency, deep %, REM %, sleep score, onset latency, HRV) "
                "AND next-day Whoop recovery (recovery score, HRV, resting HR). "
                "Splits days into dose buckets (none / light ≤1 drink / moderate 1-2.5 drinks / heavy 3+ drinks) "
                "and compares sleep + recovery quality across buckets. Also runs Pearson correlations for "
                "dose effects, timing effects (last drink time), and drinking-vs-sober comparison. "
                "Generates a personal impact severity assessment. One standard drink = 14g pure alcohol. "
                "Based on Huberman, Attia, and Walker: alcohol suppresses REM, raises resting HR, and impairs HRV recovery. "
                "Use for: 'is alcohol affecting my sleep?', 'how does drinking affect my recovery?', "
                "'alcohol and sleep correlation', 'should I drink less?', 'drinking vs sober sleep comparison', "
                "'how does alcohol affect my HRV?'. Requires MacroFactor food log + Eight Sleep data. "
                "Whoop data enhances next-day recovery analysis but is not required."
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

# ── PATCH 1: Insert function after get_zone2_breakdown ───────────────────────
marker = "# ── Tool: get_habit_adherence"
if marker not in content:
    print(f"ERROR: Could not find marker: {marker}", file=sys.stderr)
    sys.exit(1)
content = content.replace(marker, FUNCTION_CODE + "\n" + marker)

# ── PATCH 2: Insert registry entry after get_zone2_breakdown ─────────────────
registry_marker = '    # ── Habits / P40 tools'
if registry_marker not in content:
    print(f"ERROR: Could not find registry marker", file=sys.stderr)
    sys.exit(1)
content = content.replace(registry_marker, REGISTRY_ENTRY + registry_marker, 1)

# ── PATCH 3: Update version ──────────────────────────────────────────────────
content = content.replace('"version": "2.13.0"', '"version": "2.14.0"')

# ── PATCH 4: Update header comment ──────────────────────────────────────────
old_header = 'life-platform MCP Server v2.13.0\nNew in v2.13.0:'
new_header = '''life-platform MCP Server v2.14.0
New in v2.14.0:
  - get_alcohol_sleep_correlation : personal alcohol impact analyzer -- MacroFactor alcohol + Eight Sleep + next-day Whoop recovery

New in v2.13.0:'''
content = content.replace(old_header, new_header)

with open("mcp_server.py", "w") as f:
    f.write(content)

print("OK: mcp_server.py patched with get_alcohol_sleep_correlation (v2.14.0)")
