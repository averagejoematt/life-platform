#!/bin/bash
# PULSE-A: Sprint 1 deployment — API + Data Pipeline
# Run from: ~/Documents/Claude/life-platform/
# 
# This script applies 3 changes:
#   1. Adds write_pulse_json() to site_writer.py (PULSE-A1/A2/A3)
#   2. Adds handle_pulse() to site_api_lambda.py + ROUTES entry (PULSE-A4)
#   3. Adds write_pulse_json call to daily_brief_lambda.py (PULSE-A1 integration)
#
# After running: deploy both Lambdas
#   bash deploy/deploy_lambda.sh life-platform-daily-brief lambdas/daily_brief_lambda.py
#   (wait 10s)
#   bash deploy/deploy_lambda.sh life-platform-site-api lambdas/site_api_lambda.py

set -e
cd "$(dirname "$0")/.."
echo "Working in: $(pwd)"

echo ""
echo "=== PULSE-A: Applying Sprint 1 changes ==="
echo ""

# ─── 1. Add PULSE_KEY constant and write_pulse_json to site_writer.py ───────
echo "[1/3] Patching site_writer.py..."

# Add PULSE_KEY constant after CHARACTER_STATS_KEY
if ! grep -q "PULSE_KEY" lambdas/site_writer.py; then
    sed -i '' '/^CHARACTER_STATS_KEY/a\
PULSE_KEY = "site/pulse.json"
' lambdas/site_writer.py
    echo "  ✓ Added PULSE_KEY constant"
else
    echo "  ⊘ PULSE_KEY already exists"
fi

# The write_pulse_json function is too large for sed — append to end of file
if ! grep -q "def write_pulse_json" lambdas/site_writer.py; then
    cat >> lambdas/site_writer.py << 'PULSE_WRITER_EOF'


# ─── PULSE-A1/A2/A3: Pulse computation and storage ──────────────────────────

def _glyph_state(green_test, amber_test, has_data):
    """Return 'green', 'amber', 'red', or 'gray' based on signal thresholds."""
    if not has_data:
        return "gray"
    if green_test:
        return "green"
    if amber_test:
        return "amber"
    return "red"


def _compute_pulse(vitals: dict, journey: dict, training: dict,
                   journal_data: dict = None, mood_data: dict = None,
                   trends: dict = None, brief_excerpt: str = None) -> dict:
    """Compute the full pulse object from daily brief data."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        from datetime import date as _date
        started = _date.fromisoformat(JOURNEY_START_DATE)
        day_number = max(0, (_date.today() - started).days)
    except Exception:
        day_number = 0

    glyphs = {}

    # ── 1. SCALE ──
    weight = vitals.get("weight_lbs")
    weight_daily = (trends or {}).get("weight_daily", [])
    day_delta = None
    direction = None
    if weight_daily and len(weight_daily) >= 2:
        prev = weight_daily[-2].get("lbs")
        curr = weight_daily[-1].get("lbs")
        if prev and curr:
            day_delta = round(curr - prev, 1)
            direction = "down" if day_delta < 0 else ("up" if day_delta > 0 else "flat")

    glyphs["scale"] = {
        "state": _glyph_state(
            green_test=(day_delta is not None and day_delta <= 0),
            amber_test=(day_delta is not None and day_delta <= 0.5),
            has_data=(weight is not None),
        ),
        "direction": direction,
        "value": round(weight, 1) if weight else None,
        "delta": day_delta,
        "delta_label": f"{day_delta:+.1f} from yesterday" if day_delta is not None else None,
        "journey_summary": (
            f"{round(JOURNEY_START_WEIGHT - weight, 1)} lbs lost "
            f"({round((JOURNEY_START_WEIGHT - weight) / (JOURNEY_START_WEIGHT - GOAL_WEIGHT) * 100, 1)}%)"
            if weight and weight < JOURNEY_START_WEIGHT else None
        ),
        "sparkline_7d": [d.get("lbs") for d in weight_daily[-7:]] if weight_daily else [],
        "as_of": vitals.get("weight_as_of") or today,
    }

    # ── 2. WATER (not yet tracked — gray until source added) ──
    glyphs["water"] = {"state": "gray", "liters": None, "target": 3.0, "label": None, "sparkline_7d": [], "as_of": today}

    # ── 3. MOVEMENT ──
    z2_week = training.get("zone2_this_week_min", 0) or 0
    activity_type = training.get("today_activity")
    has_movement = z2_week > 0 or activity_type
    glyphs["movement"] = {
        "state": _glyph_state(green_test=bool(activity_type or z2_week > 60), amber_test=(z2_week > 0), has_data=has_movement),
        "steps": None, "zone2_week_min": round(z2_week), "zone2_target": 150,
        "activity_type": activity_type, "sparkline_7d": [], "as_of": today,
    }

    # ── 4. LIFT ──
    trained_today = bool(activity_type)
    glyphs["lift"] = {
        "state": _glyph_state(green_test=trained_today, amber_test=True, has_data=True),
        "trained_today": trained_today, "workout_type": activity_type or "Rest",
        "strain": training.get("today_strain"), "sessions_this_week": 0, "rest_day_streak": 0, "as_of": today,
    }

    # ── 5. RECOVERY ──
    recovery_pct = vitals.get("recovery_pct")
    recovery_trend = (trends or {}).get("recovery_daily", [])
    glyphs["recovery"] = {
        "state": _glyph_state(green_test=(recovery_pct and recovery_pct >= 67), amber_test=(recovery_pct and recovery_pct >= 33), has_data=(recovery_pct is not None)),
        "recovery_pct": round(recovery_pct) if recovery_pct else None,
        "status_label": ("Optimal" if (recovery_pct or 0) >= 67 else ("Moderate" if (recovery_pct or 0) >= 33 else "Needs rest")) if recovery_pct else None,
        "hrv_ms": vitals.get("hrv_ms"), "rhr_bpm": vitals.get("rhr_bpm"),
        "sparkline_7d": [d.get("pct") for d in recovery_trend[-7:]] if recovery_trend else [],
        "as_of": today,
    }

    # ── 6. SLEEP ──
    sleep_hours = vitals.get("sleep_hours")
    sleep_trend = (trends or {}).get("sleep_daily", [])
    glyphs["sleep"] = {
        "state": _glyph_state(green_test=(sleep_hours and sleep_hours >= 7), amber_test=(sleep_hours and sleep_hours >= 6), has_data=(sleep_hours is not None)),
        "hours": round(sleep_hours, 1) if sleep_hours else None, "score": vitals.get("sleep_score"),
        "sparkline_7d": [d.get("hrs") for d in sleep_trend[-7:]] if sleep_trend else [],
        "as_of": today,
    }

    # ── 7. JOURNAL ──
    journal = journal_data or {}
    written_today = bool(journal.get("entries") and journal["entries"] > 0)
    glyphs["journal"] = {
        "state": "green" if written_today else "gray",
        "written_today": written_today, "streak_days": journal.get("streak_days", 0),
        "themes": (journal.get("themes") or [])[:3], "binary_14d": [], "as_of": today,
    }

    # ── 8. MIND ──
    mood = mood_data or {}
    mood_score = mood.get("score") or mood.get("mood_avg")
    has_mood = mood_score is not None
    glyphs["mind"] = {
        "state": _glyph_state(green_test=(mood_score and float(mood_score) >= 4), amber_test=(mood_score and float(mood_score) >= 3), has_data=has_mood),
        "score": round(float(mood_score)) if mood_score else None, "max_score": 5,
        "label": {1:"Low",2:"Below avg",3:"Average",4:"Good",5:"Excellent"}.get(round(float(mood_score))) if mood_score else None,
        "sparkline_7d": [], "as_of": today,
    }

    # ── PULSE STATUS ──
    glyph_states = [g["state"] for g in glyphs.values()]
    green_count = glyph_states.count("green")
    reporting_count = len([s for s in glyph_states if s != "gray"])
    has_red = "red" in glyph_states

    if reporting_count <= 2:
        status, status_color = "quiet", "#3a5a48"
    elif green_count >= 6 and not has_red:
        status, status_color = "strong", "#00e5a0"
    else:
        status, status_color = "mixed", "#f5a623"

    # ── NARRATIVE ──
    narrative = brief_excerpt
    if not narrative:
        if status == "quiet":
            narrative = f"{reporting_count} signal{'s' if reporting_count != 1 else ''} reporting. The rest is silence — and that's data too."
        elif status == "strong":
            parts = []
            if day_delta is not None and day_delta < 0:
                parts.append(f"Weight dropped {abs(day_delta)} lbs")
            if sleep_hours and sleep_hours >= 7:
                parts.append(f"Sleep at {round(sleep_hours, 1)}h")
            if recovery_pct and recovery_pct >= 67:
                parts.append(f"Recovery {round(recovery_pct)}%")
            narrative = ". ".join(parts[:3]) + ". The system is humming." if parts else "All signals green."
        else:
            amber_red = [n for n, g in glyphs.items() if g["state"] in ("amber", "red")]
            narrative = f"{', '.join(amber_red[:2]).title()} flagged. Mixed signals today."

    return {
        "pulse": {
            "day_number": day_number, "date": today,
            "status": status, "status_color": status_color,
            "narrative": narrative,
            "signals_reporting": reporting_count, "signals_total": 8,
            "glyphs": glyphs,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    }


def write_pulse_json(s3_client, vitals: dict, journey: dict, training: dict,
                     journal_data: dict = None, mood_data: dict = None,
                     trends: dict = None, brief_excerpt: str = None,
                     table_client=None, user_id: str = "matthew") -> bool:
    """PULSE-A2/A3: Write pulse.json to S3 + DynamoDB for /api/pulse."""
    try:
        pulse = _compute_pulse(vitals=vitals, journey=journey, training=training,
                               journal_data=journal_data, mood_data=mood_data,
                               trends=trends, brief_excerpt=brief_excerpt)
        s3_client.put_object(Bucket=S3_BUCKET, Key=PULSE_KEY,
                             Body=json.dumps(pulse, indent=2, default=str),
                             ContentType="application/json", CacheControl="max-age=300")
        logger.info("[site_writer] pulse.json written to S3")

        if table_client is not None:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            try:
                pulse_json = json.dumps(pulse["pulse"], default=str)
                pulse_item = json.loads(pulse_json, parse_float=lambda x: int(float(x)) if float(x) == int(float(x)) else float(x))
                table_client.put_item(Item={"pk": "PULSE", "sk": f"DATE#{today}", "date": today, **{k: v for k, v in pulse_item.items() if v is not None}})
                logger.info(f"[site_writer] Pulse DynamoDB: {today}")
            except Exception as ddb_e:
                logger.warning(f"[site_writer] Pulse DDB write failed: {ddb_e}")
        return True
    except Exception as e:
        logger.warning(f"[site_writer] pulse.json failed: {e}")
        return False
PULSE_WRITER_EOF
    echo "  ✓ Added write_pulse_json() and _compute_pulse()"
else
    echo "  ⊘ write_pulse_json already exists"
fi

# ─── 2. Add handle_pulse() to site_api_lambda.py + ROUTES entry ─────────────
echo "[2/3] Patching site_api_lambda.py..."

if ! grep -q "handle_pulse" lambdas/site_api_lambda.py; then
    # Insert handle_pulse function before "def handle_protocols"
    python3 -c "
import re
with open('lambdas/site_api_lambda.py', 'r') as f:
    content = f.read()

pulse_handler = '''
# ── PULSE-A4: Pulse endpoint ─────────────────────────────────────────────────

def handle_pulse() -> dict:
    \"\"\"
    GET /api/pulse
    Returns the Pulse daily state: 8 glyph signals, status word, narrative.
    Today: reads from S3 pulse.json (pre-computed by daily brief).
    Cache: 300s (5 min).
    \"\"\"
    S3_BUCKET = os.environ.get(\"S3_BUCKET\", \"matthew-life-platform\")
    try:
        s3_client = boto3.client(\"s3\", region_name=S3_REGION)
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key=\"site/pulse.json\")
        pulse_data = json.loads(resp[\"Body\"].read())
        logger.info(\"[pulse] Loaded pulse.json from S3\")
        return _ok(pulse_data, cache_seconds=300)
    except Exception as e:
        if \"NoSuchKey\" in str(e):
            logger.warning(\"[pulse] pulse.json not found — not yet generated\")
            return _ok({
                \"pulse\": {
                    \"day_number\": 0,
                    \"date\": datetime.now(timezone.utc).strftime(\"%Y-%m-%d\"),
                    \"status\": \"quiet\",
                    \"status_color\": \"#3a5a48\",
                    \"narrative\": \"Today's pulse generates at 11 AM PT.\",
                    \"signals_reporting\": 0,
                    \"signals_total\": 8,
                    \"glyphs\": {},
                    \"generated_at\": None,
                }
            }, cache_seconds=60)
        logger.error(f\"[pulse] Failed: {e}\")
        return _error(503, \"Pulse data not available\")


'''

# Insert before handle_protocols
content = content.replace('def handle_protocols', pulse_handler + 'def handle_protocols')

# Add route to ROUTES dict — insert after /api/habit_registry line
content = content.replace(
    '    \"/api/habit_registry\":     handle_habit_registry,',
    '    \"/api/habit_registry\":     handle_habit_registry,\n    # PULSE-A4: Daily pulse endpoint\n    \"/api/pulse\":              handle_pulse,'
)

with open('lambdas/site_api_lambda.py', 'w') as f:
    f.write(content)
"
    echo "  ✓ Added handle_pulse() + /api/pulse route"
else
    echo "  ⊘ handle_pulse already exists"
fi

# ─── 3. Add write_pulse_json call to daily_brief_lambda.py ──────────────────
echo "[3/3] Patching daily_brief_lambda.py..."

if ! grep -q "write_pulse_json" lambdas/daily_brief_lambda.py; then
    # Insert the pulse writer call right after the write_public_stats call
    python3 -c "
with open('lambdas/daily_brief_lambda.py', 'r') as f:
    content = f.read()

pulse_call = '''
            # PULSE-A1: Write pulse.json to S3 + DynamoDB for /api/pulse endpoint
            try:
                from site_writer import write_pulse_json
                _journal_pulse = {
                    \"entries\": len(data.get(\"journal_entries\") or []),
                    \"themes\": (data.get(\"journal\") or {}).get(\"themes\", []),
                    \"streak_days\": 0,  # TODO: compute from journal history
                }
                _mood_pulse = {
                    \"mood_avg\": (data.get(\"journal\") or {}).get(\"mood_avg\"),
                }
                write_pulse_json(
                    s3_client=s3,
                    vitals={
                        \"weight_lbs\": round(_curr_wt, 1) if _curr_wt else None,
                        \"weight_as_of\": _weight_as_of,
                        \"weight_delta_30d\": round(_curr_wt - float(_week_ago), 1) if _week_ago and _curr_wt else None,
                        \"hrv_ms\": round(float(_hrv.get(\"hrv_yesterday\") or _hrv.get(\"hrv_7d\") or 0), 1) or None,
                        \"rhr_bpm\": safe_float(_w, \"resting_heart_rate\"),
                        \"recovery_pct\": round(_rec, 0) if _rec else None,
                        \"recovery_status\": _rec_status,
                        \"sleep_hours\": safe_float(data.get(\"sleep\"), \"sleep_duration_hours\"),
                    },
                    journey={
                        \"current_weight_lbs\": _curr_wt,
                        \"lost_lbs\": _lost,
                        \"progress_pct\": _prog_pct,
                    },
                    training={
                        \"zone2_this_week_min\": round(_z2_this_week),
                        \"today_activity\": None,  # yesterday's activity
                    },
                    journal_data=_journal_pulse,
                    mood_data=_mood_pulse,
                    trends=_trends,
                    brief_excerpt=_brief_excerpt,
                    table_client=table,
                    user_id=USER_ID,
                )
                print(\"[INFO] PULSE-A: pulse.json written\")
            except Exception as _pulse_e:
                print(f\"[WARN] PULSE-A: pulse write failed (non-fatal): {_pulse_e}\")
'''

# Insert after the line that says 'site_writer: public_stats.json written with baseline'
marker = 'print(\"[INFO] site_writer: public_stats.json written with baseline\")'
content = content.replace(marker, marker + pulse_call)

with open('lambdas/daily_brief_lambda.py', 'w') as f:
    f.write(content)
"
    echo "  ✓ Added write_pulse_json call to daily_brief_lambda"
else
    echo "  ⊘ write_pulse_json call already exists"
fi

echo ""
echo "=== PULSE-A: All patches applied ==="
echo ""
echo "Next steps:"
echo "  1. Review changes:  git diff lambdas/"
echo "  2. Run tests:       python3 -m pytest tests/ -v"
echo "  3. Deploy daily brief:"
echo "     bash deploy/deploy_lambda.sh life-platform-daily-brief lambdas/daily_brief_lambda.py"
echo "  4. Wait 10s, then deploy site-api:"
echo "     bash deploy/deploy_lambda.sh life-platform-site-api lambdas/site_api_lambda.py"
echo "  5. Test: curl https://averagejoematt.com/api/pulse"
echo "     (Will return quiet/empty state until next daily brief run)"
echo "  6. Force test: Invoke daily brief Lambda manually to generate first pulse.json"
echo ""
