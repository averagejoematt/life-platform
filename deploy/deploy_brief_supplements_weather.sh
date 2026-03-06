#!/bin/bash
# deploy_brief_supplements_weather.sh — Add supplements + weather sections to Daily Brief
# Patches daily_brief_lambda.py to:
#   1. Fetch supplement data in gather_daily_data()
#   2. Fetch weather data in gather_daily_data()
#   3. Add 💊 Supplements section (after habits, before CGM)
#   4. Add 🌤 Weather Context line in guidance section
set -euo pipefail

echo "═══════════════════════════════════════════════════════════════"
echo "  Daily Brief: Add Supplements + Weather Sections"
echo "  Adds 2 new sections to the 15-section brief → 17 sections"
echo "═══════════════════════════════════════════════════════════════"

cd ~/Documents/Claude/life-platform

cp lambdas/daily_brief_lambda.py lambdas/daily_brief_lambda.py.bak.sw
echo "✅ Backup: daily_brief_lambda.py.bak.sw"

python3 << 'PYTHON_PATCH'
import sys

with open("lambdas/daily_brief_lambda.py", "r") as f:
    content = f.read()

errors = []

# ═══════════════════════════════════════════════════════════════════
# 1. Add supplement + weather fetches to gather_daily_data()
# ═══════════════════════════════════════════════════════════════════

# Insert after anomaly fetch
ANCHOR1 = '    anomaly = fetch_anomaly_record(yesterday)'
NEW_FETCHES = '''    anomaly = fetch_anomaly_record(yesterday)

    # Supplements — last 7 days for adherence context
    supplements_today = fetch_date("supplements", yesterday)
    supplements_7d = fetch_range("supplements", (today - timedelta(days=7)).isoformat(), yesterday)

    # Weather — yesterday + today (pre-populated by weather-data-ingestion Lambda)
    weather_yesterday = fetch_date("weather", yesterday)
    weather_today = fetch_date("weather", today.isoformat())'''

if ANCHOR1 in content:
    content = content.replace(ANCHOR1, NEW_FETCHES)
    print("✅ Added supplement + weather fetches to gather_daily_data()")
else:
    errors.append("Could not find anomaly fetch anchor in gather_daily_data()")

# Add new keys to the return dict
OLD_RETURN_TAIL = '        "sleep_debt_7d_hrs": round(sleep_debt_hrs, 1),\n    }'
NEW_RETURN_TAIL = '''        "sleep_debt_7d_hrs": round(sleep_debt_hrs, 1),
        "supplements_today": supplements_today,
        "supplements_7d": supplements_7d,
        "weather_yesterday": weather_yesterday,
        "weather_today": weather_today,
    }'''

if OLD_RETURN_TAIL in content:
    content = content.replace(OLD_RETURN_TAIL, NEW_RETURN_TAIL)
    print("✅ Added supplement + weather keys to data dict")
else:
    errors.append("Could not find return dict tail in gather_daily_data()")

# ═══════════════════════════════════════════════════════════════════
# 2. Add 💊 Supplements section (after habits, before CGM)
# ═══════════════════════════════════════════════════════════════════

# Find the CGM section start
CGM_ANCHOR = "    # -- CGM Spotlight"
SUPPLEMENTS_SECTION = '''    # -- Supplements (v2.36: reads from supplement log) --------------------------
    supp_today = data.get("supplements_today") or {}
    supp_7d = data.get("supplements_7d") or []
    supp_entries = supp_today.get("supplements", [])
    if supp_entries:
        html += '<!-- S:supplements -->'
        html += '<div style="background:#fdf4ff;border-left:3px solid #a855f7;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        html += '<p style="font-size:11px;font-weight:700;color:#7e22ce;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.5px;">&#128138; Supplements</p>'
        for entry in supp_entries:
            s_name = entry.get("name", "?")
            s_dose = entry.get("dose")
            s_unit = entry.get("unit", "")
            s_timing = entry.get("timing", "")
            dose_str = " " + str(s_dose) + s_unit if s_dose else ""
            timing_str = " (" + s_timing.replace("_", " ") + ")" if s_timing else ""
            html += '<p style="font-size:12px;color:#581c87;margin:2px 0;">&#9745; ' + s_name + dose_str + timing_str + '</p>'
        # 7-day adherence: which supplements were taken on how many of last 7 days
        if supp_7d:
            by_name = {}
            days_with_data = set()
            for day_rec in supp_7d:
                d = day_rec.get("date", "")
                days_with_data.add(d)
                for e in (day_rec.get("supplements") or []):
                    n = e.get("name", "").lower()
                    if n not in by_name:
                        by_name[n] = {"name": e.get("name", "?"), "days": 0}
                    by_name[n]["days"] += 1
            if by_name:
                top_supps = sorted(by_name.values(), key=lambda x: x["days"], reverse=True)[:5]
                adherence_chips = ""
                for s in top_supps:
                    pct = round(s["days"] / 7 * 100)
                    col = "#059669" if pct >= 80 else "#d97706" if pct >= 50 else "#dc2626"
                    adherence_chips += '<span style="display:inline-block;background:#fff;border:1px solid ' + col + ';border-radius:12px;padding:2px 8px;font-size:9px;color:' + col + ';font-weight:600;margin:2px 3px 2px 0;">' + s["name"] + ' ' + str(s["days"]) + '/7d</span>'
                html += '<p style="font-size:9px;color:#9ca3af;margin:6px 0 2px;">7-day adherence:</p>'
                html += '<div>' + adherence_chips + '</div>'
        html += '</div>'
        html += '<!-- /S:supplements -->'

    ''' + CGM_ANCHOR

if CGM_ANCHOR in content:
    content = content.replace(CGM_ANCHOR, SUPPLEMENTS_SECTION)
    print("✅ Added Supplements section to build_html()")
else:
    errors.append("Could not find CGM Spotlight anchor for supplement section insertion")

# ═══════════════════════════════════════════════════════════════════
# 3. Add 🌤 Weather Context section (after gait, before weight_phase)
# ═══════════════════════════════════════════════════════════════════

# Find the weight_phase section start
WEIGHT_ANCHOR = "    # -- Weight Phase Tracker"
WEATHER_SECTION = '''    # -- Weather Context (v2.36: from weather-data-ingestion Lambda) -----------
    weather = data.get("weather_yesterday") or data.get("weather_today") or {}
    w_temp = safe_float(weather, "temp_avg_f")
    w_daylight = safe_float(weather, "daylight_hours")
    w_precip = safe_float(weather, "precipitation_mm")
    w_pressure = safe_float(weather, "pressure_hpa")
    if w_temp is not None:
        html += '<!-- S:weather -->'
        html += '<div style="background:#f0fdfa;border-left:3px solid #14b8a6;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        html += '<p style="font-size:11px;font-weight:700;color:#0f766e;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.5px;">&#127780; Weather &amp; Environment</p>'
        html += '<table style="width:100%;border-collapse:collapse;"><tr>'
        # Temp
        html += '<td style="text-align:center;padding:4px 6px;"><div style="font-size:16px;font-weight:700;color:#0f766e;">' + str(round(w_temp)) + '&deg;F</div>'
        html += '<div style="font-size:9px;color:#9ca3af;">Avg Temp</div></td>'
        # Daylight
        if w_daylight:
            dl_col = "#059669" if w_daylight >= 12 else "#d97706" if w_daylight >= 10 else "#dc2626"
            html += '<td style="text-align:center;padding:4px 6px;"><div style="font-size:16px;font-weight:700;color:' + dl_col + ';">' + str(round(w_daylight, 1)) + 'h</div>'
            html += '<div style="font-size:9px;color:#9ca3af;">Daylight</div></td>'
        # Precipitation
        if w_precip is not None:
            p_icon = "&#127783;" if w_precip > 0.5 else "&#9728;"
            html += '<td style="text-align:center;padding:4px 6px;"><div style="font-size:16px;">' + p_icon + '</div>'
            html += '<div style="font-size:9px;color:#9ca3af;">' + (str(round(w_precip, 1)) + "mm" if w_precip > 0 else "Dry") + '</div></td>'
        # Pressure
        if w_pressure:
            p_label = "Low" if w_pressure < 1010 else "Normal" if w_pressure < 1020 else "High"
            html += '<td style="text-align:center;padding:4px 6px;"><div style="font-size:13px;font-weight:700;color:#6b7280;">' + p_label + '</div>'
            html += '<div style="font-size:9px;color:#9ca3af;">' + str(round(w_pressure)) + ' hPa</div></td>'
        html += '</tr></table>'
        # Daylight coaching nudge
        if w_daylight and w_daylight < 10:
            html += '<p style="font-size:10px;color:#0f766e;margin:6px 0 0;font-style:italic;">&#128161; Short daylight — prioritize morning outdoor light within 30 min of waking (Huberman).</p>'
        if w_pressure and w_pressure < 1008:
            html += '<p style="font-size:10px;color:#0f766e;margin:4px 0 0;font-style:italic;">&#9888; Low pressure system — may affect joint inflammation and recovery.</p>'
        html += '</div>'
        html += '<!-- /S:weather -->'

    ''' + WEIGHT_ANCHOR

if WEIGHT_ANCHOR in content:
    content = content.replace(WEIGHT_ANCHOR, WEATHER_SECTION)
    print("✅ Added Weather Context section to build_html()")
else:
    errors.append("Could not find Weight Phase anchor for weather section insertion")

# ═══════════════════════════════════════════════════════════════════
# 4. Update footer source list
# ═══════════════════════════════════════════════════════════════════
OLD_FOOTER_SOURCES = '''    for name, key in [("Whoop", "whoop"), ("Eight Sleep", "sleep"), ("Strava", "strava"),
                       ("MacroFactor", "macrofactor"), ("Apple Health", "apple"), ("Habitify", "habitify"),
                       ("MF Workouts", "mf_workouts")]:'''
NEW_FOOTER_SOURCES = '''    for name, key in [("Whoop", "whoop"), ("Eight Sleep", "sleep"), ("Strava", "strava"),
                       ("MacroFactor", "macrofactor"), ("Apple Health", "apple"), ("Habitify", "habitify"),
                       ("MF Workouts", "mf_workouts"), ("Supplements", "supplements_today"),
                       ("Weather", "weather_yesterday")]:'''

if OLD_FOOTER_SOURCES in content:
    content = content.replace(OLD_FOOTER_SOURCES, NEW_FOOTER_SOURCES)
    print("✅ Updated footer source list")
else:
    errors.append("Could not find footer source list")

# ═══════════════════════════════════════════════════════════════════
# 5. Update version string
# ═══════════════════════════════════════════════════════════════════
OLD_VERSION = "Life Platform v2.2"
NEW_VERSION = "Life Platform v2.36"
if OLD_VERSION in content:
    content = content.replace(OLD_VERSION, NEW_VERSION)
    print("✅ Updated version string in footer")

OLD_HEADER = "Daily Brief Lambda — v2.3.0"
NEW_HEADER = "Daily Brief Lambda — v2.4.0 (supplements + weather sections)"
if OLD_HEADER in content:
    content = content.replace(OLD_HEADER, NEW_HEADER)
    print("✅ Updated header docstring")

# ═══════════════════════════════════════════════════════════════════
# 6. Add supplements + weather to demo_mode hide_sections support
# ═══════════════════════════════════════════════════════════════════
# (No change needed — the hide_sections regex already handles any section name)

# ── Write ──
if errors:
    print("\n⚠️  ERRORS:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)

with open("lambdas/daily_brief_lambda.py", "w") as f:
    f.write(content)
print("\n✅ daily_brief_lambda.py patched successfully")
PYTHON_PATCH

echo "✅ Patched daily_brief_lambda.py"

# ── Package and deploy ──────────────────────────────────────────────────────
cd lambdas
rm -f daily_brief_lambda.zip
zip daily_brief_lambda.zip daily_brief_lambda.py
cd ..

aws lambda update-function-code \
  --function-name daily-brief \
  --zip-file fileb://lambdas/daily_brief_lambda.zip \
  --region us-west-2

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Daily Brief patched! Now 17 sections:"
echo "  + 💊 Supplements (after habits, before CGM)"
echo "  + 🌤 Weather Context (after gait, before weight phase)"
echo "  Sections are conditional — show only when data exists"
echo "═══════════════════════════════════════════════════════════════"
