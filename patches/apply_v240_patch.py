#!/usr/bin/env python3
"""
apply_v240_patch.py — Patches mcp_server.py to v2.4.0 (adds get_readiness_score tool)

Run this from the life-platform project directory:
    python3 apply_v240_patch.py

Then deploy with:
    ./deploy_mcp.sh
"""
import re, sys, os, zipfile

SRC = os.path.join(os.path.dirname(__file__), "mcp_server.py")
ZIP = os.path.join(os.path.dirname(__file__), "mcp_server.zip")

# ── 1. Restore mcp_server.py from zip if current file is just a placeholder ──
with open(SRC) as f:
    current = f.read()

if len(current) < 5000:
    print("mcp_server.py appears to be a placeholder – restoring from mcp_server.zip...")
    with zipfile.ZipFile(ZIP) as z:
        with z.open("mcp_server.py") as zf:
            current = zf.read().decode()
    print(f"  Restored {len(current):,} chars from zip.")

# ── 2. Check already patched ──────────────────────────────────────────────────
if "get_readiness_score" in current:
    print("✅ Already patched to v2.4.0 — nothing to do.")
    sys.exit(0)

# ── 3. Inject new function before the tool registry ──────────────────────────
NEW_FUNCTION = '''
def tool_get_readiness_score(args):
    """
    Unified readiness score (0–100) synthesising Whoop recovery, Eight Sleep quality,
    HRV 7-day trend, and TSB training form into a single GREEN / YELLOW / RED signal
    with a 1-line actionable recommendation.

    Weights:
      Whoop recovery score  : 40%
      Eight Sleep score     : 30%
      HRV 7-day trend       : 20%
      TSB training form     : 10%

    If a component is unavailable, remaining weights are re-normalised so the
    score is still meaningful with partial data.
    """
    end_date   = args.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    d7_start   = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    d30_start  = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")

    def _clamp(v, lo=0.0, hi=100.0):
        return max(lo, min(hi, v))

    components = {}

    # ── 1. Whoop recovery score (40%) ─────────────────────────────────────────
    whoop_recent = query_source("whoop", d7_start, end_date)
    whoop_sorted = sorted(whoop_recent, key=lambda x: x.get("date", ""), reverse=True)
    whoop_today  = next((w for w in whoop_sorted if w.get("recovery_score") is not None), None)

    if whoop_today:
        rec_score = float(whoop_today["recovery_score"])
        components["whoop_recovery"] = {
            "score":   round(rec_score, 1),
            "weight":  0.40,
            "raw": {
                "date":           whoop_today.get("date"),
                "recovery_score": whoop_today.get("recovery_score"),
                "hrv_ms":         whoop_today.get("hrv"),
                "resting_hr":     whoop_today.get("resting_heart_rate"),
                "sleep_hours":    whoop_today.get("sleep_duration_hours"),
            },
        }

    # ── 2. Eight Sleep score (30%) ────────────────────────────────────────────
    sleep_recent = query_source("eightsleep", d7_start, end_date)
    sleep_sorted = sorted(sleep_recent, key=lambda x: x.get("date", ""), reverse=True)
    sleep_today  = next((s for s in sleep_sorted
                         if s.get("sleep_score") is not None or s.get("sleep_efficiency_pct") is not None), None)

    if sleep_today:
        if sleep_today.get("sleep_score") is not None:
            es_score  = float(sleep_today["sleep_score"])
            es_method = "sleep_score"
        else:
            eff       = float(sleep_today["sleep_efficiency_pct"])
            es_score  = _clamp(eff - 25.0)
            es_method = "derived_from_efficiency"

        components["eight_sleep"] = {
            "score":  round(es_score, 1),
            "weight": 0.30,
            "raw": {
                "date":                sleep_today.get("date"),
                "sleep_score":         sleep_today.get("sleep_score"),
                "sleep_efficiency_pct": sleep_today.get("sleep_efficiency_pct"),
                "sleep_duration_hours": sleep_today.get("sleep_duration_hours"),
                "rem_pct":             sleep_today.get("rem_pct"),
                "deep_pct":            sleep_today.get("deep_pct"),
                "scoring_method":      es_method,
            },
        }

    # ── 3. HRV 7-day trend vs 30-day baseline (20%) ───────────────────────────
    whoop_30d = query_source("whoop", d30_start, end_date)
    hrv_30d   = [float(w["hrv"]) for w in whoop_30d if w.get("hrv") is not None]
    hrv_7d    = [float(w["hrv"]) for w in whoop_recent if w.get("hrv") is not None]

    if len(hrv_30d) >= 7 and hrv_7d:
        baseline  = sum(hrv_30d) / len(hrv_30d)
        recent7   = sum(hrv_7d) / len(hrv_7d)
        ratio     = recent7 / baseline if baseline > 0 else 1.0
        trend_pct = round((ratio - 1.0) * 100, 1)
        hrv_score = _clamp(60.0 + (ratio - 1.0) * 200.0)

        components["hrv_trend"] = {
            "score":  round(hrv_score, 1),
            "weight": 0.20,
            "raw": {
                "hrv_7d_avg_ms":       round(recent7, 1),
                "hrv_30d_baseline_ms": round(baseline, 1),
                "trend_pct":           trend_pct,
                "trend_direction":     "above_baseline" if trend_pct > 3 else ("below_baseline" if trend_pct < -3 else "at_baseline"),
                "n_days_30d":          len(hrv_30d),
                "n_days_7d":           len(hrv_7d),
            },
        }

    # ── 4. TSB training form (10%) ────────────────────────────────────────────
    try:
        load_result = tool_get_training_load({"end_date": end_date})
        if "current_state" in load_result:
            cs  = load_result["current_state"]
            tsb = cs.get("tsb_form", 0.0)
            tsb_score = _clamp(70.0 + float(tsb) * 2.5)
            components["training_form"] = {
                "score":  round(tsb_score, 1),
                "weight": 0.10,
                "raw": {
                    "tsb_form":    cs.get("tsb_form"),
                    "ctl_fitness": cs.get("ctl_fitness"),
                    "atl_fatigue": cs.get("atl_fatigue"),
                    "acwr":        cs.get("acwr"),
                    "form_status": cs.get("form_status"),
                },
            }
    except Exception as e:
        logger.warning(f"get_readiness_score: TSB failed — {e}")

    # ── Weighted aggregate ────────────────────────────────────────────────────
    total_weight = sum(c["weight"] for c in components.values())

    if not components:
        return {"error": "No data available from any source for this date. Check ingestion pipeline."}

    raw_score       = sum(c["score"] * c["weight"] for c in components.values()) / total_weight
    readiness_score = round(raw_score, 1)

    if readiness_score >= 70:
        label = "GREEN"
    elif readiness_score >= 40:
        label = "YELLOW"
    else:
        label = "RED"

    # Recommendation
    rec_parts = []
    if label == "GREEN":
        rec_parts.append("You\'re primed — go ahead with your planned hard session.")
        if "training_form" in components and components["training_form"]["raw"].get("tsb_form", 0) > 8:
            rec_parts.append("TSB is notably positive — a good day for a PR attempt or race effort.")
    elif label == "YELLOW":
        rec_parts.append("Moderate readiness — a controlled effort is appropriate; skip high-intensity intervals.")
        if "whoop_recovery" in components and components["whoop_recovery"]["score"] < 50:
            rec_parts.append("Whoop recovery is low — prioritise aerobic work over heavy strength training today.")
        if "eight_sleep" in components and components["eight_sleep"]["score"] < 50:
            rec_parts.append("Sleep quality was below average — consider a shorter session and extra cool-down.")
    else:
        rec_parts.append("Recovery day. Hard training now will deepen fatigue without adding fitness.")
        if "hrv_trend" in components and components["hrv_trend"]["raw"]["trend_pct"] < -10:
            rec_parts.append("HRV is trending meaningfully below your baseline — your body is asking for rest.")

    missing = sorted({"whoop_recovery", "eight_sleep", "hrv_trend", "training_form"} - set(components.keys()))

    return {
        "date":              end_date,
        "readiness_score":   readiness_score,
        "label":             label,
        "recommendation":    " ".join(rec_parts),
        "components":        components,
        "data_completeness": "full" if total_weight >= 0.99 else f"partial ({round(total_weight*100)}% weight covered)",
        "missing_components": [k.replace("_", " ") for k in missing] or None,
        "scoring_note": (
            "Weights: Whoop recovery 40%, Eight Sleep 30%, HRV 7d trend 20%, TSB form 10%. "
            "Missing components are excluded and remaining weights re-normalised."
        ),
    }

'''

REGISTRY_ENTRY = '''    "get_readiness_score": {
        "fn": tool_get_readiness_score,
        "schema": {
            "name": "get_readiness_score",
            "description": (
                "Unified readiness score (0-100) synthesising Whoop recovery (40%), Eight Sleep score (30%), "
                "HRV 7-day trend vs 30-day baseline (20%), and TSB training form (10%) into a single "
                "GREEN / YELLOW / RED signal with a 1-line actionable recommendation. "
                "Reduces cognitive load: one number instead of 4 separate metrics. "
                "Use for: \'should I train hard today?\', \'what is my readiness score?\', "
                "\'am I ready for a key session?\', \'how am I feeling today?\', \'morning readiness check-in\'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
}
'''

# Apply function injection
REGISTRY_MARKER = "\n# ── Tool registry ─────────────────────────────────────────────────────────────"
if REGISTRY_MARKER not in current:
    print("ERROR: Could not find tool registry marker. Is this the right mcp_server.py?")
    sys.exit(1)

patched = current.replace(REGISTRY_MARKER, NEW_FUNCTION + REGISTRY_MARKER)

# Apply registry entry (replace closing brace of TOOLS dict)
LAST_TOOL_END = '''    "get_habit_dashboard": {
        "fn": tool_get_habit_dashboard,
        "schema": {
            "name": "get_habit_dashboard",
            "description": (
                "Current-state P40 briefing. Shows: latest day status, 7-day rolling scores vs 30-day baseline, "
                "best/worst groups, top active streaks, and alerts for declining areas. "
                "Use for: 'how are my habits?', 'P40 morning check-in', 'what habits need attention?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
}'''

LAST_TOOL_REPLACEMENT = '''    "get_habit_dashboard": {
        "fn": tool_get_habit_dashboard,
        "schema": {
            "name": "get_habit_dashboard",
            "description": (
                "Current-state P40 briefing. Shows: latest day status, 7-day rolling scores vs 30-day baseline, "
                "best/worst groups, top active streaks, and alerts for declining areas. "
                "Use for: 'how are my habits?', 'P40 morning check-in', 'what habits need attention?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
''' + REGISTRY_ENTRY

if LAST_TOOL_END not in patched:
    print("ERROR: Could not find the end of get_habit_dashboard in TOOLS dict.")
    print("Patch may need to be applied manually. New function has been injected but registry was NOT updated.")
    # Still write what we have
else:
    patched = patched.replace(LAST_TOOL_END, LAST_TOOL_REPLACEMENT)

# Version bump
patched = patched.replace('"version": "2.3.2"', '"version": "2.4.0"')
patched = patched.replace("life-platform MCP Server v2.3.2", "life-platform MCP Server v2.4.0")

# Write the patched file
with open(SRC, "w") as f:
    f.write(patched)

print(f"✅ Patched mcp_server.py to v2.4.0 ({len(patched):,} chars)")
print()
print("Next step — deploy to Lambda:")
print("  cd /Users/matthewwalker/Documents/Claude/life-platform")
print("  ./deploy_mcp.sh")
