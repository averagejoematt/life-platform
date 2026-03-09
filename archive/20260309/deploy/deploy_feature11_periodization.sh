#!/bin/bash
# deploy_feature11_periodization.sh — Feature #11: Training Periodization Planner
# 1 new MCP tool. MCP-only change.
set -euo pipefail

echo "═══════════════════════════════════════════════════════════════"
echo "  Feature #11: Training Periodization Planner"
echo "  1 MCP tool: get_training_periodization"
echo "═══════════════════════════════════════════════════════════════"

cd ~/Documents/Claude/life-platform

# ── Backup ──────────────────────────────────────────────────────────────────
cp mcp_server.py mcp_server.py.bak.f11
echo "✅ Backup: mcp_server.py.bak.f11"

# ── Patch ───────────────────────────────────────────────────────────────────
python3 << 'PYTHON_PATCH'
import sys

with open("mcp_server.py", "r") as f:
    content = f.read()

tool_func = '''

# ══════════════════════════════════════════════════════════════════════════════
# Feature #11: Training Periodization Planner
# ══════════════════════════════════════════════════════════════════════════════

def tool_get_training_periodization(args):
    """
    Training periodization analysis. Detects mesocycle phases, deload needs,
    progressive overload tracking, and training polarization.

    Galpin framework: Base → Build → Peak → Deload (3:1 or 4:1 ratio).
    Attia: Training is the most potent longevity drug — but only with periodization.
    Seiler: 80/20 polarized model — 80% easy, 20% hard for optimal adaptation.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    weeks_back = int(args.get("weeks", 12))
    start_date = args.get("start_date",
        (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(weeks=weeks_back)).strftime("%Y-%m-%d"))

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    profile = get_profile()
    max_hr = float(profile.get("max_heart_rate", 190))

    # ── 1. Fetch training data ───────────────────────────────────────────────
    strava_items = query_source("strava", start_date, end_date)
    mf_workout_items = query_source("macrofactor_workouts", start_date, end_date)

    if not strava_items and not mf_workout_items:
        return {"error": "No training data for range.", "start_date": start_date, "end_date": end_date}

    # ── 2. Build weekly training profile ─────────────────────────────────────
    from collections import defaultdict

    def _week_key(date_str):
        d = datetime.strptime(date_str, "%Y-%m-%d")
        # ISO week: Monday start
        return d.strftime("%G-W%V")

    weeks = defaultdict(lambda: {
        "cardio_minutes": 0, "strength_minutes": 0, "total_minutes": 0,
        "zone2_minutes": 0, "hard_minutes": 0, "easy_minutes": 0,
        "sessions": 0, "strength_sessions": 0, "cardio_sessions": 0,
        "total_volume_lbs": 0, "rest_days": 0, "dates": set(),
        "activities": [],
    })

    cardio_types = {"run", "ride", "swim", "hike", "walk", "rowing", "elliptical",
                    "virtualrun", "virtualride", "trailrun"}
    strength_types = {"weighttraining", "crossfit", "workout"}

    # Process Strava activities
    for item in strava_items:
        date = item.get("date")
        if not date:
            continue
        wk = _week_key(date)
        weeks[wk]["dates"].add(date)
        for act in (item.get("activities") or []):
            sport = (act.get("sport_type") or act.get("type") or "").lower().replace(" ", "")
            elapsed = _sf(act.get("elapsed_time_seconds")) or 0
            if elapsed < 600:
                continue
            duration_min = elapsed / 60
            avg_hr = _sf(act.get("average_heartrate"))

            weeks[wk]["sessions"] += 1
            weeks[wk]["total_minutes"] += duration_min

            is_cardio = sport in cardio_types
            is_strength = sport in strength_types

            if is_cardio:
                weeks[wk]["cardio_sessions"] += 1
                weeks[wk]["cardio_minutes"] += duration_min

                if avg_hr:
                    hr_pct = avg_hr / max_hr * 100
                    if hr_pct <= 70:
                        weeks[wk]["zone2_minutes"] += duration_min
                        weeks[wk]["easy_minutes"] += duration_min
                    elif hr_pct >= 80:
                        weeks[wk]["hard_minutes"] += duration_min
                    else:
                        weeks[wk]["easy_minutes"] += duration_min  # Zone 3 counted as moderate

            elif is_strength:
                weeks[wk]["strength_sessions"] += 1
                weeks[wk]["strength_minutes"] += duration_min

            weeks[wk]["activities"].append({
                "date": date, "sport": sport,
                "duration_min": round(duration_min, 1),
                "avg_hr": avg_hr,
            })

    # Process MacroFactor workouts for volume tracking
    for item in mf_workout_items:
        date = item.get("date")
        if not date:
            continue
        wk = _week_key(date)
        vol = _sf(item.get("total_volume_lbs")) or 0
        weeks[wk]["total_volume_lbs"] += vol

    # Calculate rest days per week
    for wk, data in weeks.items():
        data["rest_days"] = 7 - len(data["dates"])
        data["dates"] = sorted(data["dates"])  # Convert set to sorted list

    # ── 3. Weekly progression analysis ───────────────────────────────────────
    sorted_weeks = sorted(weeks.keys())
    weekly_summary = []
    for wk in sorted_weeks:
        w = weeks[wk]
        total_min = w["total_minutes"]
        easy_pct = round(w["easy_minutes"] / total_min * 100, 1) if total_min > 0 else 0
        hard_pct = round(w["hard_minutes"] / total_min * 100, 1) if total_min > 0 else 0

        # Classify week phase
        if total_min < 60:
            phase = "deload"
        elif w["sessions"] <= 2:
            phase = "deload"
        else:
            if w["hard_minutes"] > total_min * 0.3:
                phase = "build"
            elif total_min > 300:
                phase = "peak"
            else:
                phase = "base"

        weekly_summary.append({
            "week": wk,
            "phase": phase,
            "sessions": w["sessions"],
            "total_minutes": round(total_min, 1),
            "cardio_minutes": round(w["cardio_minutes"], 1),
            "strength_minutes": round(w["strength_minutes"], 1),
            "zone2_minutes": round(w["zone2_minutes"], 1),
            "hard_minutes": round(w["hard_minutes"], 1),
            "easy_pct": easy_pct,
            "hard_pct": hard_pct,
            "volume_lbs": round(w["total_volume_lbs"], 1),
            "rest_days": w["rest_days"],
            "cardio_sessions": w["cardio_sessions"],
            "strength_sessions": w["strength_sessions"],
        })

    # ── 4. Deload detection ──────────────────────────────────────────────────
    deload_analysis = {
        "weeks_since_last_deload": 0,
        "deload_recommended": False,
        "reason": None,
    }

    # Count consecutive non-deload weeks from end
    consecutive = 0
    for ws in reversed(weekly_summary):
        if ws["phase"] == "deload":
            break
        consecutive += 1
    deload_analysis["weeks_since_last_deload"] = consecutive

    if consecutive >= 4:
        deload_analysis["deload_recommended"] = True
        deload_analysis["reason"] = f"{consecutive} consecutive training weeks without deload. Galpin recommends 3:1 or 4:1 loading-to-deload ratio."
    elif consecutive >= 3:
        # Check if volume is trending up
        recent_3 = weekly_summary[-3:] if len(weekly_summary) >= 3 else weekly_summary
        if len(recent_3) >= 3:
            vols = [w["total_minutes"] for w in recent_3]
            if all(vols[i] >= vols[i-1] for i in range(1, len(vols))):
                deload_analysis["deload_recommended"] = True
                deload_analysis["reason"] = "3 consecutive weeks of increasing volume. Progressive overload is good, but a deload preserves adaptation."

    # ── 5. Training polarization check (Seiler) ─────────────────────────────
    total_easy = sum(w["easy_minutes"] for wk, w in weeks.items())
    total_hard = sum(w["hard_minutes"] for wk, w in weeks.items())
    total_all = total_easy + total_hard
    polarization = None

    if total_all > 0:
        easy_ratio = round(total_easy / total_all * 100, 1)
        hard_ratio = round(total_hard / total_all * 100, 1)
        mid_ratio = round(100 - easy_ratio - hard_ratio, 1)

        if easy_ratio >= 75:
            pol_status = "well_polarized"
        elif easy_ratio >= 60:
            pol_status = "moderately_polarized"
        else:
            pol_status = "too_much_intensity"

        polarization = {
            "easy_pct": easy_ratio,
            "hard_pct": hard_ratio,
            "middle_zone_pct": mid_ratio,
            "status": pol_status,
            "seiler_target": "80% easy / 20% hard — the polarized model maximizes adaptation while minimizing overtraining risk.",
        }

    # ── 6. Progressive overload tracking (strength) ──────────────────────────
    overload = None
    vol_weeks = [(ws["week"], ws["volume_lbs"]) for ws in weekly_summary if ws["volume_lbs"] > 0]
    if len(vol_weeks) >= 4:
        mid = len(vol_weeks) // 2
        first_half_vol = _avg([v for _, v in vol_weeks[:mid]])
        second_half_vol = _avg([v for _, v in vol_weeks[mid:]])
        if first_half_vol and second_half_vol:
            delta_pct = round((second_half_vol - first_half_vol) / first_half_vol * 100, 1)
            overload = {
                "first_half_avg_volume_lbs": first_half_vol,
                "second_half_avg_volume_lbs": second_half_vol,
                "delta_pct": delta_pct,
                "trend": "increasing" if delta_pct > 5 else ("decreasing" if delta_pct < -5 else "stable"),
                "note": "Progressive overload detected." if delta_pct > 5 else (
                    "Volume declining — ensure this is intentional (deload/cut)." if delta_pct < -5
                    else "Volume stable — consider adding progressive overload."
                ),
            }

    # ── 7. Training consistency ──────────────────────────────────────────────
    sessions_per_week = [ws["sessions"] for ws in weekly_summary]
    avg_sessions = _avg(sessions_per_week)
    consistency_pct = round(
        sum(1 for s in sessions_per_week if s >= 3) / len(sessions_per_week) * 100, 1
    ) if sessions_per_week else 0

    consistency = {
        "avg_sessions_per_week": avg_sessions,
        "weeks_with_3plus_sessions_pct": consistency_pct,
        "total_weeks_analyzed": len(weekly_summary),
        "assessment": "excellent" if consistency_pct >= 85 else (
            "good" if consistency_pct >= 70 else (
                "needs_improvement" if consistency_pct >= 50 else "inconsistent"
            )
        ),
    }

    # ── 8. Zone 2 target tracking ────────────────────────────────────────────
    z2_weekly = [ws["zone2_minutes"] for ws in weekly_summary]
    z2_target = 150
    z2_hit_rate = round(sum(1 for z in z2_weekly if z >= z2_target) / len(z2_weekly) * 100, 1) if z2_weekly else 0

    zone2_status = {
        "avg_weekly_minutes": _avg(z2_weekly),
        "target_minutes": z2_target,
        "weeks_hitting_target_pct": z2_hit_rate,
        "current_week": round(z2_weekly[-1], 1) if z2_weekly else 0,
    }

    # ── 9. Board of Directors ────────────────────────────────────────────────
    bod = []

    if deload_analysis["deload_recommended"]:
        bod.append(f"Galpin: {deload_analysis['reason']} Reduce volume by 40-60% this week. Maintain intensity on key lifts but cut sets in half.")

    if polarization:
        if polarization["status"] == "too_much_intensity":
            bod.append(f"Seiler: Only {polarization['easy_pct']}% of your training is easy. The 80/20 model says you need more Zone 2 and fewer moderate sessions. 'No man's land' (Zone 3) generates fatigue without proportional adaptation.")
        elif polarization["status"] == "well_polarized":
            bod.append("Seiler: Training well polarized — strong easy/hard split. This is the highest-evidence approach for long-term development.")

    if overload and overload["trend"] == "increasing":
        bod.append(f"Galpin: Progressive overload confirmed (+{overload['delta_pct']}% volume). This is the fundamental driver of hypertrophy and strength adaptation.")
    elif overload and overload["trend"] == "decreasing":
        bod.append(f"Galpin: Volume declining by {abs(overload['delta_pct'])}%. If not intentional (cut/deload), this represents a missed adaptation opportunity.")

    if zone2_status["weeks_hitting_target_pct"] < 50:
        bod.append(f"Attia: Only hitting Zone 2 target {zone2_status['weeks_hitting_target_pct']}% of weeks. Zone 2 is the highest-ROI longevity training modality — aim for 150 min/week.")

    if consistency["assessment"] in ("needs_improvement", "inconsistent"):
        bod.append(f"Attia: Consistency ({consistency['avg_sessions_per_week']} sessions/week avg) matters more than intensity. The best program is the one you actually do.")

    return {
        "period": {"start_date": start_date, "end_date": end_date, "weeks": len(weekly_summary)},
        "weekly_breakdown": weekly_summary,
        "deload_analysis": deload_analysis,
        "polarization": polarization,
        "progressive_overload": overload,
        "training_consistency": consistency,
        "zone2_status": zone2_status,
        "board_of_directors": bod,
        "methodology": (
            "Weekly training classified into phases: base (moderate consistent), build (>30% high intensity), "
            "peak (>300 min/week), deload (<60 min or <=2 sessions). Polarization per Seiler (80/20 model). "
            "Progressive overload = first-half vs second-half average weekly volume. "
            "Deload trigger: 4+ consecutive loading weeks or 3 weeks of rising volume. "
            "Zone 2 threshold: avg HR <= 70% max HR (Attia/WHO 150 min/week target)."
        ),
        "source": "strava + macrofactor_workouts",
    }

'''

insert_point = content.find("\nTOOLS = {")
if insert_point == -1:
    print("ERROR: Could not find TOOLS dict")
    sys.exit(1)
content = content[:insert_point] + tool_func + content[insert_point:]
print("Inserted training periodization tool function")

# ── Add TOOLS entry ──
tools_entry = '''
    "get_training_periodization": {
        "fn": tool_get_training_periodization,
        "schema": {
            "name": "get_training_periodization",
            "description": (
                "Training periodization planner. Analyzes weekly training patterns to detect mesocycle phases "
                "(base/build/peak/deload), deload needs (Galpin 3:1 or 4:1 ratio), progressive overload "
                "tracking (strength volume trends), training polarization (Seiler 80/20 model), Zone 2 "
                "target adherence (Attia 150 min/week), and training consistency. "
                "Use for: 'do I need a deload?', 'training periodization', 'am I overtraining?', "
                "'progressive overload trend', 'training polarization check', 'weekly training summary', "
                "'mesocycle analysis', 'should I take a rest week?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 12 weeks ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "weeks": {"type": "integer", "description": "Number of weeks to analyze (default: 12). Ignored if start_date provided."},
                },
                "required": [],
            },
        },
    },'''

# Find last TOOLS entry
for marker in ['"get_weather_correlation":', '"get_supplement_correlation":', '"get_sleep_environment_analysis":', '"get_health_trajectory":']:
    idx = content.find(marker)
    if idx != -1:
        break
if idx == -1:
    print("ERROR: Could not find TOOLS entry to insert after")
    sys.exit(1)

depth = 0; found_first = False; end_idx = idx
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

content = content[:insert_at] + tools_entry + content[insert_at:]
print("Inserted TOOLS entry for get_training_periodization")

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
echo "  Feature #11 deployed! Tool: get_training_periodization"
echo "  MCP tool count: $TOOL_COUNT"
echo "  Try: 'Do I need a deload week?'"
echo "═══════════════════════════════════════════════════════════════"
