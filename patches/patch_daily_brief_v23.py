#!/usr/bin/env python3
"""
Patcher: Daily Brief v2.3 — CGM Enhancement + Gait Section
- Enhances CGM Spotlight: fasting proxy (overnight low), hypo flag, 7-day trend arrow
- Adds Gait & Mobility section: walking speed, step length, asymmetry, double support
- Adds 7-day apple_health fetch for CGM trend context
- Updates data_summary and AI prompt with gait + fasting data
- Bumps section count 14 → 15
"""
import re

import os
# Support both filenames: lambda_function.py (in Lambda zip) and daily_brief_lambda.py (local)
if os.path.exists("lambda_function.py"):
    LAMBDA_FILE = "lambda_function.py"
else:
    LAMBDA_FILE = "daily_brief_lambda.py"

with open(LAMBDA_FILE, "r") as f:
    code = f.read()

# =============================================================================
# 1. Update docstring: section count 14 → 15, add gait section
# =============================================================================
code = code.replace(
    '''Sections (14):
  1.  Day Grade + TL;DR (NEW: AI one-liner)
  2.  Yesterday's Scorecard (UPDATED: sleep architecture detail)
  3.  Readiness Signal
  4.  Training Report (UPDATED: exercise-level detail from MacroFactor workouts)
  5.  Nutrition Report (UPDATED: meal timing in AI prompt)
  6.  Habits Deep-Dive
  7.  CGM Spotlight
  8.  Habit Streaks
  9.  Weight Phase Tracker (UPDATED: weekly delta callout)
  10. Today's Guidance (REWRITTEN: AI-generated smart guidance)
  11. Journal Pulse
  12. Journal Coach
  13. Board of Directors Insight
  14. Anomaly Alert''',
    '''Sections (15):
  1.  Day Grade + TL;DR (AI one-liner)
  2.  Yesterday's Scorecard (sleep architecture detail)
  3.  Readiness Signal
  4.  Training Report (exercise-level detail from MacroFactor workouts)
  5.  Nutrition Report (meal timing in AI prompt)
  6.  Habits Deep-Dive
  7.  CGM Spotlight (UPDATED: fasting proxy, hypo flag, 7-day trend)
  8.  Gait & Mobility (NEW: walking speed, step length, asymmetry, double support)
  9.  Habit Streaks
  10. Weight Phase Tracker (weekly delta callout)
  11. Today's Guidance (AI-generated smart guidance)
  12. Journal Pulse
  13. Journal Coach
  14. Board of Directors Insight
  15. Anomaly Alert'''
)

# =============================================================================
# 2. gather_daily_data: add apple_7d fetch for CGM trend
# =============================================================================
code = code.replace(
    '''    # Cumulative sleep debt (last 7 days) for smart guidance
    sleep_7d = fetch_range("eightsleep", (today - timedelta(days=7)).isoformat(), yesterday)''',
    '''    # 7-day Apple Health for CGM trend context
    apple_7d = fetch_range("apple_health", (today - timedelta(days=7)).isoformat(), yesterday)

    # Cumulative sleep debt (last 7 days) for smart guidance
    sleep_7d = fetch_range("eightsleep", (today - timedelta(days=7)).isoformat(), yesterday)'''
)

# Add apple_7d to the return dict
code = code.replace(
    '''        "anomaly": anomaly,''',
    '''        "apple_7d": apple_7d,
        "anomaly": anomaly,'''
)

# =============================================================================
# 3. build_data_summary: add gait + fasting proxy fields
# =============================================================================
code = code.replace(
    '''        "glucose_avg": safe_float(apple, "blood_glucose_avg"),
        "glucose_tir": safe_float(apple, "blood_glucose_time_in_range_pct"),
        "glucose_std_dev": safe_float(apple, "blood_glucose_std_dev"),''',
    '''        "glucose_avg": safe_float(apple, "blood_glucose_avg"),
        "glucose_tir": safe_float(apple, "blood_glucose_time_in_range_pct"),
        "glucose_std_dev": safe_float(apple, "blood_glucose_std_dev"),
        "glucose_min": safe_float(apple, "blood_glucose_min"),
        "walking_speed_mph": safe_float(apple, "walking_speed_mph"),
        "walking_step_length_in": safe_float(apple, "walking_step_length_in"),
        "walking_asymmetry_pct": safe_float(apple, "walking_asymmetry_pct"),'''
)

# =============================================================================
# 4. Enhanced CGM Spotlight — add fasting proxy, hypo flag, 7-day trend
# =============================================================================
code = code.replace(
    '''    # -- CGM Spotlight ---------------------------------------------------------
    apple = data.get("apple") or {}
    cgm_avg = safe_float(apple, "blood_glucose_avg")
    cgm_tir = safe_float(apple, "blood_glucose_time_in_range_pct")
    cgm_std = safe_float(apple, "blood_glucose_std_dev")
    cgm_min = safe_float(apple, "blood_glucose_min")
    cgm_max = safe_float(apple, "blood_glucose_max")
    cgm_above140 = safe_float(apple, "blood_glucose_time_above_140_pct")
    cgm_readings = safe_float(apple, "blood_glucose_readings_count")
    if cgm_avg is not None or cgm_tir is not None:
        gc2 = '<div style="border-left:3px solid #0ea5e9;background:#f0f9ff;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        gc2 += '<p style="font-size:11px;font-weight:700;color:#0369a1;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.5px;">&#128200; CGM Spotlight</p>'
        gc2 += '<table style="width:100%;border-collapse:collapse;"><tr>'
        if cgm_avg is not None:
            avg_color = "#059669" if cgm_avg < 100 else "#d97706" if cgm_avg < 120 else "#dc2626"
            gc2 += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + avg_color + ';">' + str(round(cgm_avg)) + '</div><div style="font-size:9px;color:#6b7280;">Avg mg/dL</div></td>'
        if cgm_tir is not None:
            tir_color = "#059669" if cgm_tir >= 90 else "#d97706" if cgm_tir >= 70 else "#dc2626"
            gc2 += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + tir_color + ';">' + str(round(cgm_tir)) + '%</div><div style="font-size:9px;color:#6b7280;">Time in Range</div></td>'
        if cgm_std is not None:
            std_color = "#059669" if cgm_std < 20 else "#d97706" if cgm_std < 30 else "#dc2626"
            gc2 += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + std_color + ';">' + str(round(cgm_std, 1)) + '</div><div style="font-size:9px;color:#6b7280;">Variability</div></td>'
        gc2 += '</tr></table>'
        extras = []
        if cgm_min is not None and cgm_max is not None:
            extras.append("Range: " + str(round(cgm_min)) + "-" + str(round(cgm_max)) + " mg/dL")
        if cgm_above140 is not None and cgm_above140 > 0:
            extras.append("Time >140: " + str(round(cgm_above140)) + "%")
        if cgm_readings is not None:
            extras.append(str(round(cgm_readings)) + " readings")
        if extras:
            gc2 += '<p style="font-size:10px;color:#6b7280;margin:6px 0 0;">' + ' &middot; '.join(extras) + '</p>'
        gc2 += '</div>'
        html += '<!-- S:cgm -->' + gc2 + '<!-- /S:cgm -->\'''',
    r'''    # -- CGM Spotlight (v2.3: fasting proxy, hypo flag, 7-day trend) ----------
    apple = data.get("apple") or {}
    cgm_avg = safe_float(apple, "blood_glucose_avg")
    cgm_tir = safe_float(apple, "blood_glucose_time_in_range_pct")
    cgm_std = safe_float(apple, "blood_glucose_std_dev")
    cgm_min = safe_float(apple, "blood_glucose_min")
    cgm_max = safe_float(apple, "blood_glucose_max")
    cgm_above140 = safe_float(apple, "blood_glucose_time_above_140_pct")
    cgm_below70 = safe_float(apple, "blood_glucose_time_below_70_pct")
    cgm_readings = safe_float(apple, "blood_glucose_readings_count")
    # 7-day CGM trend
    apple_7d = data.get("apple_7d") or []
    cgm_7d_avgs = [safe_float(d, "blood_glucose_avg") for d in apple_7d if safe_float(d, "blood_glucose_avg") is not None]
    cgm_7d_avg = round(sum(cgm_7d_avgs) / len(cgm_7d_avgs), 1) if cgm_7d_avgs else None
    if cgm_avg is not None or cgm_tir is not None:
        gc2 = '<div style="border-left:3px solid #0ea5e9;background:#f0f9ff;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        gc2 += '<p style="font-size:11px;font-weight:700;color:#0369a1;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.5px;">&#128200; CGM Spotlight</p>'
        gc2 += '<table style="width:100%;border-collapse:collapse;"><tr>'
        if cgm_avg is not None:
            avg_color = "#059669" if cgm_avg < 100 else "#d97706" if cgm_avg < 120 else "#dc2626"
            trend_arrow = ""
            if cgm_7d_avg is not None and cgm_avg is not None:
                delta = cgm_avg - cgm_7d_avg
                if delta > 5: trend_arrow = ' <span style="color:#dc2626;font-size:10px;">&#9650;</span>'
                elif delta < -5: trend_arrow = ' <span style="color:#059669;font-size:10px;">&#9660;</span>'
                else: trend_arrow = ' <span style="color:#9ca3af;font-size:10px;">&#9644;</span>'
            gc2 += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + avg_color + ';">' + str(round(cgm_avg)) + trend_arrow + '</div><div style="font-size:9px;color:#6b7280;">Avg mg/dL</div></td>'
        if cgm_tir is not None:
            tir_color = "#059669" if cgm_tir >= 90 else "#d97706" if cgm_tir >= 70 else "#dc2626"
            gc2 += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + tir_color + ';">' + str(round(cgm_tir)) + '%</div><div style="font-size:9px;color:#6b7280;">Time in Range</div></td>'
        if cgm_std is not None:
            std_color = "#059669" if cgm_std < 20 else "#d97706" if cgm_std < 30 else "#dc2626"
            gc2 += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + std_color + ';">' + str(round(cgm_std, 1)) + '</div><div style="font-size:9px;color:#6b7280;">Variability</div></td>'
        if cgm_min is not None:
            fasting_color = "#059669" if cgm_min < 90 else "#d97706" if cgm_min < 100 else "#dc2626"
            gc2 += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + fasting_color + ';">' + str(round(cgm_min)) + '</div><div style="font-size:9px;color:#6b7280;">Overnight Low</div></td>'
        gc2 += '</tr></table>'
        extras = []
        if cgm_min is not None and cgm_max is not None:
            extras.append("Range: " + str(round(cgm_min)) + "-" + str(round(cgm_max)) + " mg/dL")
        if cgm_above140 is not None and cgm_above140 > 0:
            extras.append("Time >140: " + str(round(cgm_above140)) + "%")
        if cgm_below70 is not None and cgm_below70 > 0:
            extras.append('<span style="color:#dc2626;font-weight:700;">&#9888; Hypo: ' + str(round(cgm_below70)) + '% below 70</span>')
        if cgm_readings is not None:
            extras.append(str(round(cgm_readings)) + " readings")
        if cgm_7d_avg is not None:
            extras.append("7d avg: " + str(round(cgm_7d_avg)) + " mg/dL")
        if extras:
            gc2 += '<p style="font-size:10px;color:#6b7280;margin:6px 0 0;">' + ' &middot; '.join(extras) + '</p>'
        gc2 += '</div>'
        html += '<!-- S:cgm -->' + gc2 + '<!-- /S:cgm -->''' + "'"
)

# =============================================================================
# 5. NEW: Gait & Mobility section — insert after CGM Spotlight
# =============================================================================
GAIT_SECTION = r'''

    # -- Gait & Mobility (v2.3) ------------------------------------------------
    gait_speed = safe_float(apple, "walking_speed_mph")
    gait_step_len = safe_float(apple, "walking_step_length_in")
    gait_asym = safe_float(apple, "walking_asymmetry_pct")
    gait_dbl_support = safe_float(apple, "walking_double_support_pct")
    has_gait = any(v is not None and v > 0 for v in [gait_speed, gait_step_len])
    if has_gait:
        gt = '<div style="border-left:3px solid #10b981;background:#f0fdf4;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        gt += '<p style="font-size:11px;font-weight:700;color:#065f46;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.5px;">&#129406; Gait &amp; Mobility</p>'
        gt += '<table style="width:100%;border-collapse:collapse;"><tr>'
        if gait_speed is not None and gait_speed > 0:
            # Walking speed: strongest all-cause mortality predictor
            # <2.24 mph clinical flag, <3.0 suboptimal, >=3.0 good
            sp_color = "#dc2626" if gait_speed < 2.24 else "#d97706" if gait_speed < 3.0 else "#059669"
            gt += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + sp_color + ';">' + str(round(gait_speed, 2)) + '</div><div style="font-size:9px;color:#6b7280;">Speed (mph)</div></td>'
        if gait_step_len is not None and gait_step_len > 0:
            # Step length: normal ~26-30 inches for adult male
            sl_color = "#dc2626" if gait_step_len < 22 else "#d97706" if gait_step_len < 26 else "#059669"
            gt += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + sl_color + ';">' + str(round(gait_step_len, 1)) + '</div><div style="font-size:9px;color:#6b7280;">Step (in)</div></td>'
        if gait_asym is not None and gait_asym > 0:
            # Asymmetry: >3% injury flag, >5% significant
            as_color = "#059669" if gait_asym < 3 else "#d97706" if gait_asym < 5 else "#dc2626"
            gt += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + as_color + ';">' + str(round(gait_asym, 1)) + '%</div><div style="font-size:9px;color:#6b7280;">Asymmetry</div></td>'
        if gait_dbl_support is not None and gait_dbl_support > 0:
            # Double support: <28% good, >30% flag (fall risk)
            # Apple Health reports as decimal (0.35 = 35%)
            dbl_pct = gait_dbl_support * 100 if gait_dbl_support < 1 else gait_dbl_support
            ds_color = "#059669" if dbl_pct < 28 else "#d97706" if dbl_pct < 32 else "#dc2626"
            gt += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + ds_color + ';">' + str(round(dbl_pct, 1)) + '%</div><div style="font-size:9px;color:#6b7280;">Dbl Support</div></td>'
        gt += '</tr></table>'
        gait_notes = []
        if gait_speed is not None and gait_speed < 2.24:
            gait_notes.append('<span style="color:#dc2626;font-weight:700;">&#9888; Walking speed below clinical threshold (2.24 mph)</span>')
        if gait_asym is not None and gait_asym >= 5:
            gait_notes.append('<span style="color:#dc2626;font-weight:700;">&#9888; Significant asymmetry — possible injury compensation</span>')
        elif gait_asym is not None and gait_asym >= 3:
            gait_notes.append('<span style="color:#d97706;">Mild asymmetry — monitor for change</span>')
        if gait_notes:
            gt += '<p style="font-size:10px;margin:6px 0 0;">' + ' &middot; '.join(gait_notes) + '</p>'
        gt += '</div>'
        html += '<!-- S:gait -->' + gt + '<!-- /S:gait -->'
'''

code = code.replace(
    "        html += '<!-- S:cgm -->' + gc2 + '<!-- /S:cgm -->'\n\n    # -- Habit Streaks",
    "        html += '<!-- S:cgm -->' + gc2 + '<!-- /S:cgm -->'" + GAIT_SECTION + "\n    # -- Habit Streaks"
)

# =============================================================================
# 6. AI prompt: add gait + fasting glucose data
# =============================================================================
code = code.replace(
    '''- Glucose: avg """ + str(data_summary.get("glucose_avg")) + ", TIR " + str(data_summary.get("glucose_tir")) + """%''',
    '''- Glucose: avg """ + str(data_summary.get("glucose_avg")) + " mg/dL, TIR " + str(data_summary.get("glucose_tir")) + """%, overnight low """ + str(data_summary.get("glucose_min")) + """ mg/dL
- Gait: walking speed """ + str(data_summary.get("walking_speed_mph")) + " mph, step length " + str(data_summary.get("walking_step_length_in")) + " in, asymmetry " + str(data_summary.get("walking_asymmetry_pct")) + """%'''
)

# =============================================================================
# 7. Version bump in docstring
# =============================================================================
code = code.replace(
    'Daily Brief Lambda — v2.2.3 (+ Demo Mode)',
    'Daily Brief Lambda — v2.3.0 (CGM enhance + Gait section)'
)

# =============================================================================
# WRITE
# =============================================================================
with open(LAMBDA_FILE, "w") as f:
    f.write(code)

print("✅ Patched daily_brief_lambda.py → v2.3.0")
print("   - CGM Spotlight: fasting proxy, hypo flag, 7-day trend arrow")
print("   - New section: Gait & Mobility (walking speed, step length, asymmetry, double support)")
print("   - Data summary: +gait fields, +glucose_min")
print("   - AI prompt: +gait data, +overnight low")
print("   - Sections: 14 → 15")
