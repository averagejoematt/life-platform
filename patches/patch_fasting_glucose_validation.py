#!/usr/bin/env python3
"""
patch_fasting_glucose_validation.py — Fasting Glucose Validation Tool

Adds get_fasting_glucose_validation MCP tool that:
  1. Computes proper overnight nadirs (midnight-6AM) from raw S3 CGM data
  2. Builds distribution stats across all CGM days
  3. Compares against lab venous fasting glucose draws
  4. Does direct same-day validation when CGM + lab overlap
  5. Does statistical validation (lab values vs CGM nadir distribution) when not

Board of Directors context:
  - Attia: CGM fasting proxy is the overnight nadir, not the daily minimum
  - Patrick: Dawn phenomenon raises glucose 4-7 AM, so 2-5 AM is the true nadir window
  - Huberman: Cortisol rise starts ~4 AM, confounds readings after that

Usage:
  python3 patch_fasting_glucose_validation.py
  (patches mcp_server.py in place)
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
# Patch 1: Tool function — insert before Lambda handler
# ─────────────────────────────────────────────

TOOL_FN = '''

# ── Tool: get_fasting_glucose_validation ──────────────────────────────────────

def tool_get_fasting_glucose_validation(args):
    """
    Validate CGM fasting glucose proxy against venous lab draws.

    Two modes:
      1. Direct validation: same-day CGM overnight nadir vs lab fasting glucose
      2. Statistical validation: CGM nadir distribution vs historical lab values

    Computes proper overnight nadir using 00:00-06:00 window (avoids dawn
    phenomenon cortisol rise per Attia/Huberman). Also computes the narrower
    02:00-05:00 "deep nadir" which excludes both late digestion and dawn effect.

    Returns: nadir distribution, lab comparisons, bias analysis, confidence.
    """
    import statistics

    # ── Parameters ────────────────────────────────────────────────────────
    nadir_start = float(args.get("nadir_start_hour", 0))      # midnight
    nadir_end   = float(args.get("nadir_end_hour", 6))        # 6 AM
    deep_start  = float(args.get("deep_nadir_start_hour", 2)) # 2 AM
    deep_end    = float(args.get("deep_nadir_end_hour", 5))   # 5 AM
    min_readings = int(args.get("min_overnight_readings", 6))  # need ~30 min coverage

    # ── Discover all CGM days from S3 ─────────────────────────────────────
    paginator = s3_client.get_paginator("list_objects_v2")
    cgm_days = []  # list of "YYYY-MM-DD"
    for prefix_year in ["2024/", "2025/", "2026/"]:
        try:
            for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=f"raw/cgm_readings/{prefix_year}"):
                for obj in page.get("Contents", []):
                    key = obj["Key"]  # raw/cgm_readings/2024/10/01.json
                    parts = key.replace("raw/cgm_readings/", "").replace(".json", "").split("/")
                    if len(parts) == 3:
                        y, m, d = parts
                        cgm_days.append(f"{y}-{m.zfill(2)}-{d.zfill(2)}")
        except Exception:
            continue
    cgm_days.sort()

    if not cgm_days:
        return {"error": "No CGM data found in S3."}

    # ── Compute overnight nadirs for each day ────────────────────────────
    nadir_results = []  # list of dicts per day
    for date_str in cgm_days:
        readings = _load_cgm_readings(date_str)
        if not readings:
            continue

        # Filter to overnight window (midnight to nadir_end)
        overnight = [(h, v) for h, v in readings if nadir_start <= h < nadir_end]
        deep_night = [(h, v) for h, v in readings if deep_start <= h < deep_end]

        if len(overnight) < min_readings:
            continue

        overnight_vals = [v for _, v in overnight]
        on_min = min(overnight_vals)
        on_avg = sum(overnight_vals) / len(overnight_vals)
        on_min_time = None
        for h, v in overnight:
            if v == on_min:
                hh = int(h)
                mm = int((h - hh) * 60)
                on_min_time = f"{hh:02d}:{mm:02d}"
                break

        deep_min = None
        deep_avg = None
        if len(deep_night) >= 4:
            deep_vals = [v for _, v in deep_night]
            deep_min = min(deep_vals)
            deep_avg = round(sum(deep_vals) / len(deep_vals), 1)

        # Full-day min for comparison (current proxy method)
        all_vals = [v for _, v in readings]
        daily_min = min(all_vals) if all_vals else None

        nadir_results.append({
            "date": date_str,
            "overnight_nadir": on_min,
            "overnight_avg": round(on_avg, 1),
            "overnight_nadir_time": on_min_time,
            "overnight_readings": len(overnight),
            "deep_nadir": deep_min,
            "deep_avg": deep_avg,
            "daily_min": daily_min,
            "daily_min_vs_overnight": round(daily_min - on_min, 1) if daily_min is not None else None,
        })

    if not nadir_results:
        return {"error": "Insufficient overnight CGM readings across all days."}

    # ── Distribution stats ───────────────────────────────────────────────
    on_nadirs = [r["overnight_nadir"] for r in nadir_results]
    deep_nadirs = [r["deep_nadir"] for r in nadir_results if r["deep_nadir"] is not None]
    daily_mins = [r["daily_min"] for r in nadir_results if r["daily_min"] is not None]

    def dist_stats(vals, label):
        if not vals:
            return None
        vals_sorted = sorted(vals)
        n = len(vals_sorted)
        return {
            "label": label,
            "n": n,
            "mean": round(statistics.mean(vals_sorted), 1),
            "median": round(statistics.median(vals_sorted), 1),
            "std_dev": round(statistics.stdev(vals_sorted), 1) if n > 1 else 0,
            "min": vals_sorted[0],
            "max": vals_sorted[-1],
            "p10": round(vals_sorted[int(n * 0.1)], 1),
            "p25": round(vals_sorted[int(n * 0.25)], 1),
            "p75": round(vals_sorted[int(n * 0.75)], 1),
            "p90": round(vals_sorted[int(n * 0.9)], 1),
        }

    distributions = {
        "overnight_nadir_00_06": dist_stats(on_nadirs, "Overnight nadir (00:00-06:00)"),
        "deep_nadir_02_05": dist_stats(deep_nadirs, "Deep nadir (02:00-05:00)"),
        "daily_minimum": dist_stats(daily_mins, "Daily minimum (current proxy)"),
    }

    # ── Load lab fasting glucose ─────────────────────────────────────────
    table = get_table()
    from boto3.dynamodb.conditions import Key
    lab_resp = table.query(
        KeyConditionExpression=Key("pk").eq("USER#matthew#SOURCE#labs") & Key("sk").begins_with("DATE#")
    )
    lab_draws = []
    for item in lab_resp.get("Items", []):
        glucose_bm = item.get("biomarkers", {}).get("glucose", {})
        val = glucose_bm.get("value_numeric")
        if val is not None:
            lab_draws.append({
                "draw_date": item.get("draw_date"),
                "fasting_glucose_mg_dl": float(val),
                "provider": item.get("lab_provider", "unknown"),
            })

    # ── Direct validation (same-day overlap) ─────────────────────────────
    nadir_by_date = {r["date"]: r for r in nadir_results}
    direct_validations = []
    for draw in lab_draws:
        dd = draw["draw_date"]
        if dd in nadir_by_date:
            nr = nadir_by_date[dd]
            diff_overnight = round(draw["fasting_glucose_mg_dl"] - nr["overnight_nadir"], 1)
            diff_deep = round(draw["fasting_glucose_mg_dl"] - nr["deep_nadir"], 1) if nr["deep_nadir"] else None
            direct_validations.append({
                "date": dd,
                "lab_fasting_glucose": draw["fasting_glucose_mg_dl"],
                "cgm_overnight_nadir": nr["overnight_nadir"],
                "cgm_deep_nadir": nr["deep_nadir"],
                "cgm_daily_min": nr["daily_min"],
                "lab_minus_cgm_overnight": diff_overnight,
                "lab_minus_cgm_deep": diff_deep,
                "provider": draw["provider"],
            })

    # ── Statistical validation (no overlap) ──────────────────────────────
    stat_validations = []
    on_stats = distributions["overnight_nadir_00_06"]
    deep_stats = distributions["deep_nadir_02_05"]

    for draw in lab_draws:
        lab_val = draw["fasting_glucose_mg_dl"]
        # Z-score vs overnight nadir distribution
        z_overnight = None
        if on_stats and on_stats["std_dev"] > 0:
            z_overnight = round((lab_val - on_stats["mean"]) / on_stats["std_dev"], 2)
        z_deep = None
        if deep_stats and deep_stats["std_dev"] > 0:
            z_deep = round((lab_val - deep_stats["mean"]) / deep_stats["std_dev"], 2)

        # Percentile estimate
        pct = None
        if on_nadirs:
            below = sum(1 for v in on_nadirs if v <= lab_val)
            pct = round(below / len(on_nadirs) * 100, 1)

        stat_validations.append({
            "draw_date": draw["draw_date"],
            "lab_fasting_glucose": lab_val,
            "vs_overnight_nadir": {
                "z_score": z_overnight,
                "percentile_of_nadir_dist": pct,
                "within_1sd": abs(z_overnight) <= 1 if z_overnight is not None else None,
                "within_2sd": abs(z_overnight) <= 2 if z_overnight is not None else None,
            },
            "vs_deep_nadir": {
                "z_score": z_deep,
                "within_1sd": abs(z_deep) <= 1 if z_deep is not None else None,
            } if z_deep is not None else None,
            "provider": draw["provider"],
        })

    # ── Bias analysis ────────────────────────────────────────────────────
    bias = {}
    if on_stats and lab_draws:
        lab_mean = sum(d["fasting_glucose_mg_dl"] for d in lab_draws) / len(lab_draws)
        bias["lab_mean_fasting"] = round(lab_mean, 1)
        bias["cgm_overnight_nadir_mean"] = on_stats["mean"]
        bias["cgm_daily_min_mean"] = distributions["daily_minimum"]["mean"] if distributions["daily_minimum"] else None
        bias["lab_minus_cgm_overnight"] = round(lab_mean - on_stats["mean"], 1)
        if distributions["daily_minimum"]:
            bias["lab_minus_cgm_daily_min"] = round(lab_mean - distributions["daily_minimum"]["mean"], 1)
        if deep_stats:
            bias["cgm_deep_nadir_mean"] = deep_stats["mean"]
            bias["lab_minus_cgm_deep"] = round(lab_mean - deep_stats["mean"], 1)

        # Interpretation
        diff = bias["lab_minus_cgm_overnight"]
        if abs(diff) <= 5:
            bias["interpretation"] = "Excellent agreement — CGM overnight nadir closely matches lab fasting glucose."
            bias["confidence"] = "high"
        elif abs(diff) <= 10:
            direction = "higher" if diff > 0 else "lower"
            bias["interpretation"] = f"Good agreement — lab reads ~{abs(diff)} mg/dL {direction} than CGM nadir. Within expected CGM accuracy range (±10-15 mg/dL for Stelo)."
            bias["confidence"] = "moderate"
        elif abs(diff) <= 20:
            direction = "higher" if diff > 0 else "lower"
            bias["interpretation"] = f"Moderate discrepancy — lab reads ~{abs(diff)} mg/dL {direction}. Dexcom Stelo has MARD ~9% which can produce this gap. Consider a same-day validation."
            bias["confidence"] = "low"
        else:
            bias["interpretation"] = f"Significant discrepancy ({abs(diff)} mg/dL). CGM interstitial glucose lags venous by design, but this gap warrants investigation. Could indicate sensor placement, calibration, or timing issues."
            bias["confidence"] = "very_low"

    # ── Insights ─────────────────────────────────────────────────────────
    insights = []

    # Daily min vs overnight nadir comparison
    if distributions["daily_minimum"] and on_stats:
        dm = distributions["daily_minimum"]["mean"]
        on = on_stats["mean"]
        diff = round(dm - on, 1)
        if abs(diff) > 3:
            insights.append(
                f"Daily minimum averages {dm} vs overnight nadir {on} ({diff:+.1f} mg/dL). "
                f"{'Daily min occurs outside overnight window — current proxy slightly underestimates true fasting.' if diff < 0 else 'Daily min typically IS the overnight nadir — current proxy is reasonable.'}"
            )
        else:
            insights.append(f"Daily minimum ({dm}) and overnight nadir ({on}) are very close — current fasting proxy is a good approximation.")

    # Deep nadir vs standard nadir
    if deep_stats and on_stats:
        diff = round(deep_stats["mean"] - on_stats["mean"], 1)
        if abs(diff) > 2:
            insights.append(
                f"Deep nadir (2-5 AM: {deep_stats['mean']}) differs from broad overnight (0-6 AM: {on_stats['mean']}) by {diff:+.1f} mg/dL. "
                f"Dawn phenomenon may be raising late-night readings."
            )

    # Variability
    if on_stats and on_stats["std_dev"] > 8:
        insights.append(f"High overnight nadir variability (SD {on_stats['std_dev']} mg/dL). Factors: meal timing, alcohol, sleep quality, stress.")
    elif on_stats and on_stats["std_dev"] < 4:
        insights.append(f"Very stable overnight nadirs (SD {on_stats['std_dev']} mg/dL) — strong metabolic consistency.")

    # Lab trend
    if len(lab_draws) >= 3:
        recent = lab_draws[-1]["fasting_glucose_mg_dl"]
        oldest = lab_draws[0]["fasting_glucose_mg_dl"]
        if recent > oldest + 5:
            insights.append(f"Lab fasting glucose trending up: {oldest} → {recent} mg/dL over {len(lab_draws)} draws. Monitor with CGM confirmation.")
        elif recent < oldest - 5:
            insights.append(f"Lab fasting glucose trending down: {oldest} → {recent} mg/dL — positive trajectory.")

    if not direct_validations:
        insights.append("No same-day CGM + lab data available. Schedule your next blood draw while wearing the Stelo for gold-standard validation.")

    return {
        "cgm_coverage": {
            "first_date": cgm_days[0],
            "last_date": cgm_days[-1],
            "total_cgm_days": len(cgm_days),
            "days_with_valid_overnight": len(nadir_results),
        },
        "distributions": distributions,
        "lab_draws": lab_draws,
        "direct_validations": direct_validations if direct_validations else "No same-day overlap between CGM and lab draws.",
        "statistical_validations": stat_validations,
        "bias_analysis": bias,
        "insights": insights,
        "methodology": {
            "overnight_window": f"{int(nadir_start):02d}:00 - {int(nadir_end):02d}:00",
            "deep_nadir_window": f"{int(deep_start):02d}:00 - {int(deep_end):02d}:00",
            "min_readings_required": min_readings,
            "cgm_device": "Dexcom Stelo (MARD ~9%)",
            "note": "Interstitial glucose (CGM) lags venous blood by 5-15 min and can differ by ±10-15 mg/dL. Lab draws are single-point; CGM captures continuous overnight minimum.",
        },
        "board_of_directors": {
            "Attia": "Fasting glucose <90 mg/dL is optimal. Overnight CGM nadir is more informative than a single lab draw — it captures the true metabolic baseline every night.",
            "Patrick": "Dawn phenomenon (4-7 AM cortisol rise) elevates glucose. The 2-5 AM deep nadir avoids this confounder and gives the cleanest fasting signal.",
            "Huberman": "Glucose regulation is a proxy for metabolic flexibility. Low overnight variability + clean nadirs indicate good insulin sensitivity and hepatic glucose control.",
        },
    }

'''

# ─────────────────────────────────────────────
# Patch 2: Tool registry entry
# ─────────────────────────────────────────────

REGISTRY_ENTRY = '''    "get_fasting_glucose_validation": {
        "fn": tool_get_fasting_glucose_validation,
        "schema": {
            "name": "get_fasting_glucose_validation",
            "description": "Validate CGM fasting glucose accuracy against venous lab draws. Computes proper overnight nadir (midnight-6AM) from raw CGM readings, builds distribution, and compares against 6 historical blood draws. Two modes: direct same-day validation when overlap exists, and statistical validation (z-scores, percentiles) when not. Shows bias analysis, confidence level, and Board of Directors interpretation. Use for: 'how accurate is my CGM fasting glucose?', 'validate CGM against labs', 'compare overnight nadir to blood work', 'is my fasting proxy trustworthy?'",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "nadir_start_hour": {"type": "number", "description": "Start of overnight window (decimal hours). Default 0 (midnight)."},
                    "nadir_end_hour": {"type": "number", "description": "End of overnight window (decimal hours). Default 6 (6 AM)."},
                    "deep_nadir_start_hour": {"type": "number", "description": "Start of deep nadir window. Default 2 (2 AM). Avoids late digestion."},
                    "deep_nadir_end_hour": {"type": "number", "description": "End of deep nadir window. Default 5 (5 AM). Avoids dawn phenomenon."},
                    "min_overnight_readings": {"type": "number", "description": "Minimum CGM readings in overnight window. Default 6 (~30 min coverage)."},
                },
                "required": [],
            },
        },
    },'''


def apply_patches():
    content = read_file(MCP_FILE)
    patches_applied = 0

    # ── Patch 1: Tool function before Lambda handler ──
    anchor = "# ── Lambda handler ─"
    if "def tool_get_fasting_glucose_validation(" not in content:
        if anchor in content:
            content = content.replace(anchor, TOOL_FN + "\n" + anchor)
            patches_applied += 1
            print("✅ Patch 1: tool_get_fasting_glucose_validation inserted")
        else:
            print("❌ Patch 1: Could not find anchor '# ── Lambda handler'")
    else:
        print("⏭️  Patch 1: tool already exists")

    # ── Patch 2: Registry entry after get_glucose_meal_response ──
    if '"get_fasting_glucose_validation"' not in content:
        registry_anchor = '"get_glucose_meal_response"'
        if registry_anchor in content:
            idx = content.find(registry_anchor)
            # Find the closing brace of this registry entry
            remaining = content[idx:]
            # Find the tool dict open brace
            brace_start = remaining.find("{")
            depth = 1
            i = brace_start + 1
            while i < len(remaining) and depth > 0:
                if remaining[i] == '{':
                    depth += 1
                elif remaining[i] == '}':
                    depth -= 1
                i += 1
            # i now points past the closing } of get_glucose_meal_response entry
            insert_pos = idx + i
            # Check what follows
            after = content[insert_pos:insert_pos+10].strip()
            if after.startswith(','):
                comma_pos = content.index(',', insert_pos)
                content = content[:comma_pos+1] + "\n" + REGISTRY_ENTRY + content[comma_pos+1:]
            else:
                content = content[:insert_pos] + ",\n" + REGISTRY_ENTRY + content[insert_pos:]
            patches_applied += 1
            print("✅ Patch 2: get_fasting_glucose_validation added to registry")
        else:
            print("❌ Patch 2: Could not find get_glucose_meal_response registry anchor")
    else:
        print("⏭️  Patch 2: registry entry already exists")

    write_file(MCP_FILE, content)
    print(f"\n{'='*50}")
    print(f"Patches applied: {patches_applied}")
    return patches_applied


if __name__ == "__main__":
    apply_patches()
