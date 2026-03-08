#!/usr/bin/env python3
"""
patch_daily_brief_hardening.py — Expert Review Group C: Daily Brief graceful degradation
Finding: F5.8 — Wrap sections in try/except so one crash doesn't kill the whole brief

This script patches daily_brief_lambda.py in-place with:
  1. Handler-level: wrap compute_day_grade, compute_readiness, compute_habit_streaks
  2. Handler-level: wrap build_html with fallback minimal email
  3. build_html: wrap each major section in try/except with error placeholder
  4. Bug fix: remove duplicate dedup_activities function definition
  5. Bug fix: remove duplicate dedup_activities call in handler

Run: python3 deploy/patch_daily_brief_hardening.py
"""

import os
import sys
import re
from datetime import datetime

LAMBDA_PATH = os.path.join(os.path.dirname(__file__), "..", "lambdas", "daily_brief_lambda.py")
LAMBDA_PATH = os.path.abspath(LAMBDA_PATH)

def patch(content: str) -> str:
    original = content
    changes = []

    # =========================================================================
    # 1. Add _section_error_html helper after existing helpers
    # =========================================================================
    helper_code = '''
def _section_error_html(section_name, error):
    """Render a graceful error placeholder when a section crashes."""
    print("[WARN] Section " + section_name + " failed: " + str(error))
    return ('<div style="background:#fef2f2;border-left:3px solid #fca5a5;'
            'border-radius:0 8px 8px 0;padding:8px 16px;margin:12px 16px 0;">'
            '<p style="font-size:11px;color:#991b1b;margin:0;">'
            '&#9888; ' + section_name + ' section unavailable</p></div>')

'''
    # Insert after the fmt_num function
    marker = "def fetch_date(source, date_str):"
    if marker in content:
        content = content.replace(marker, helper_code + marker, 1)
        changes.append("Added _section_error_html helper")

    # =========================================================================
    # 2. Fix duplicate dedup_activities function (keep first, remove second)
    # =========================================================================
    # Find second occurrence of the function
    first_idx = content.find("def dedup_activities(activities):")
    if first_idx >= 0:
        second_idx = content.find("def dedup_activities(activities):", first_idx + 10)
        if second_idx >= 0:
            # Find the end of the second function (next function def at same indent level)
            # Look for the next top-level def or class or section header
            after_second = content[second_idx:]
            # Find "# ==" section divider or "COMPONENT_SCORERS" which comes after
            end_marker = "# ==============================================================================\n# DAY GRADE"
            end_idx = after_second.find(end_marker)
            if end_idx > 0:
                content = content[:second_idx] + content[second_idx + end_idx:]
                changes.append("Removed duplicate dedup_activities function definition")

    # =========================================================================
    # 3. Fix duplicate dedup_activities call in handler
    # =========================================================================
    # The handler has the dedup block duplicated. Find and remove the second one.
    dedup_block = """    # Deduplicate multi-device Strava activities (v2.2.2)
    strava = data.get("strava")
    if strava and strava.get("activities"):
        orig_count = len(strava["activities"])
        strava["activities"] = dedup_activities(strava["activities"])
        deduped_count = len(strava["activities"])
        if deduped_count < orig_count:
            # Recompute aggregates from deduped list
            strava["activity_count"] = deduped_count
            strava["total_moving_time_seconds"] = sum(
                float(a.get("moving_time_seconds") or 0) for a in strava["activities"])
            print("[INFO] Dedup: " + str(orig_count) + " → " + str(deduped_count) + " activities")"""

    first_dedup = content.find(dedup_block)
    if first_dedup >= 0:
        second_dedup = content.find(dedup_block, first_dedup + len(dedup_block))
        if second_dedup >= 0:
            # Remove the second block plus surrounding whitespace
            content = content[:second_dedup] + content[second_dedup + len(dedup_block):]
            changes.append("Removed duplicate dedup_activities call in handler")

    # =========================================================================
    # 4. Wrap handler-level compute calls with try/except
    # =========================================================================

    # 4a. compute_day_grade
    old_grade = """    day_grade_score, grade, component_scores, component_details = compute_day_grade(data, profile)
    print("[INFO] Day Grade: " + str(day_grade_score) + " (" + grade + ")")"""

    new_grade = """    try:
        day_grade_score, grade, component_scores, component_details = compute_day_grade(data, profile)
        print("[INFO] Day Grade: " + str(day_grade_score) + " (" + grade + ")")
    except Exception as e:
        print("[WARN] compute_day_grade failed, using defaults: " + str(e))
        day_grade_score, grade, component_scores, component_details = None, "—", {}, {}"""

    if old_grade in content:
        content = content.replace(old_grade, new_grade, 1)
        changes.append("Wrapped compute_day_grade in try/except")

    # 4b. compute_readiness
    old_ready = "    readiness_score, readiness_colour = compute_readiness(data)"
    new_ready = """    try:
        readiness_score, readiness_colour = compute_readiness(data)
    except Exception as e:
        print("[WARN] compute_readiness failed: " + str(e))
        readiness_score, readiness_colour = None, "gray\""""

    if old_ready in content:
        content = content.replace(old_ready, new_ready, 1)
        changes.append("Wrapped compute_readiness in try/except")

    # 4c. compute_habit_streaks
    old_streak = """    streak_data = compute_habit_streaks(profile, yesterday)
    mvp_streak = streak_data.get("tier0_streak", 0)
    full_streak = streak_data.get("tier01_streak", 0)
    vice_streaks = streak_data.get("vice_streaks", {})"""

    new_streak = """    try:
        streak_data = compute_habit_streaks(profile, yesterday)
        mvp_streak = streak_data.get("tier0_streak", 0)
        full_streak = streak_data.get("tier01_streak", 0)
        vice_streaks = streak_data.get("vice_streaks", {})
    except Exception as e:
        print("[WARN] compute_habit_streaks failed: " + str(e))
        mvp_streak, full_streak, vice_streaks = 0, 0, {}"""

    if old_streak in content:
        content = content.replace(old_streak, new_streak, 1)
        changes.append("Wrapped compute_habit_streaks in try/except")

    # 4d. store_habit_scores
    old_store_hs = """    # Store tier-level habit scores for historical trending (v2.47.0)
    if not demo_mode:
        store_habit_scores(yesterday, component_details, component_scores, vice_streaks, profile)"""

    new_store_hs = """    # Store tier-level habit scores for historical trending (v2.47.0)
    if not demo_mode:
        try:
            store_habit_scores(yesterday, component_details, component_scores, vice_streaks, profile)
        except Exception as e:
            print("[WARN] store_habit_scores failed: " + str(e))"""

    if old_store_hs in content:
        content = content.replace(old_store_hs, new_store_hs, 1)
        changes.append("Wrapped store_habit_scores in try/except")

    # 4e. store_day_grade
    old_store_dg = """    if day_grade_score is not None and not demo_mode:
        store_day_grade(yesterday, day_grade_score, grade, component_scores,
                        profile.get("day_grade_weights", {}),
                        profile.get("day_grade_algorithm_version", "1.1"))"""

    new_store_dg = """    if day_grade_score is not None and not demo_mode:
        try:
            store_day_grade(yesterday, day_grade_score, grade, component_scores,
                            profile.get("day_grade_weights", {}),
                            profile.get("day_grade_algorithm_version", "1.1"))
        except Exception as e:
            print("[WARN] store_day_grade failed: " + str(e))"""

    if old_store_dg in content:
        content = content.replace(old_store_dg, new_store_dg, 1)
        changes.append("Wrapped store_day_grade in try/except")

    # =========================================================================
    # 5. Wrap build_html call with fallback minimal email
    # =========================================================================
    old_build = """    html = build_html(data, profile, day_grade_score, grade, component_scores, component_details,
                      readiness_score, readiness_colour, tldr_guidance, bod_insight,
                      training_nutrition, journal_coach_text, mvp_streak, full_streak, vice_streaks)"""

    new_build = """    try:
        html = build_html(data, profile, day_grade_score, grade, component_scores, component_details,
                          readiness_score, readiness_colour, tldr_guidance, bod_insight,
                          training_nutrition, journal_coach_text, mvp_streak, full_streak, vice_streaks)
    except Exception as e:
        print("[ERROR] build_html crashed, sending minimal brief: " + str(e))
        html = ('<!DOCTYPE html><html><body style="font-family:sans-serif;padding:20px;">'
                '<h2>⚠ Daily Brief — Partial Failure</h2>'
                '<p>The HTML builder crashed: <code>' + str(e) + '</code></p>'
                '<p>Day Grade: ' + str(day_grade_score) + ' (' + grade + ')</p>'
                '<p>Readiness: ' + str(readiness_score) + ' (' + readiness_colour + ')</p>'
                '<p>Check CloudWatch logs for details.</p>'
                '</body></html>')"""

    if old_build in content:
        content = content.replace(old_build, new_build, 1)
        changes.append("Wrapped build_html with fallback minimal email")

    # =========================================================================
    # 6. Wrap sections inside build_html with try/except
    #    Strategy: wrap each section block that modifies `html +=`
    # =========================================================================

    # 6a. Travel Banner
    old_travel = """    # -- Travel Banner (v2.40.0) -----------------------------------------------
    travel = data.get("travel_active")
    if travel:"""
    new_travel = """    # -- Travel Banner (v2.40.0) -----------------------------------------------
    try:
      travel = data.get("travel_active")
      if travel:"""

    # Find the closing of travel section and add except
    travel_end = "        html += '<!-- /S:travel -->'"
    travel_end_new = """        html += '<!-- /S:travel -->'
    except Exception as _e:
        html += _section_error_html("Travel", _e)"""

    if old_travel in content and travel_end in content:
        content = content.replace(old_travel, new_travel, 1)
        content = content.replace(travel_end, travel_end_new, 1)
        changes.append("Wrapped Travel Banner in try/except")

    # 6b. Scorecard
    old_sc = "    html += '<!-- S:scorecard -->'"
    new_sc = """    try:
      _sc_html = ''
      _sc_html += '<!-- S:scorecard -->'"""

    # This one is complex because it uses html += extensively.
    # Instead of refactoring, let's wrap the entire scorecard block.
    # Actually, a simpler approach: wrap the section with comment markers.

    # Let me use a different strategy for build_html sections:
    # Find blocks between <!-- S:name --> and <!-- /S:name --> markers
    # and wrap them.

    # Actually the issue is that the section markers are INSIDE the html string,
    # not in the Python code flow. The code structure is:
    #   html += '<!-- S:scorecard -->'
    #   ... lots of html += ...
    #   html += '<!-- /S:scorecard -->'

    # The cleanest approach: wrap the code blocks between these markers.
    # But the indentation and variable references make this complex.

    # Let me take a different approach: wrap the MOST CRASH-PRONE sections only.
    # These are the ones that do significant computation:

    # 6b. Training Report (complex activity parsing, MacroFactor workouts)
    old_training = """    # -- Training Report (v2.2: exercise-level detail) -------------------------
    strava = data.get("strava") or {}
    activities = strava.get("activities", [])
    mf_workouts = data.get("mf_workouts") or {}
    mf_workout_list = mf_workouts.get("workouts", [])
    training_comment = (training_nutrition or {}).get("training", "")

    if activities or mf_workout_list or training_comment:"""

    new_training = """    # -- Training Report (v2.2: exercise-level detail) -------------------------
    try:
      strava = data.get("strava") or {}
      activities = strava.get("activities", [])
      mf_workouts = data.get("mf_workouts") or {}
      mf_workout_list = mf_workouts.get("workouts", [])
      training_comment = (training_nutrition or {}).get("training", "")

      if activities or mf_workout_list or training_comment:"""

    training_end = """        html += '<!-- S:training -->' + tc + '<!-- /S:training -->'"""
    training_end_new = """        html += '<!-- S:training -->' + tc + '<!-- /S:training -->'
    except Exception as _e:
        html += _section_error_html("Training Report", _e)"""

    if old_training in content and training_end in content:
        content = content.replace(old_training, new_training, 1)
        content = content.replace(training_end, training_end_new, 1)
        changes.append("Wrapped Training Report in try/except")

    # 6c. Nutrition Report
    old_nutr = """    # -- Nutrition Report ------------------------------------------------------
    mf = data.get("macrofactor") or {}
    if mf.get("total_calories_kcal") is not None:"""

    new_nutr = """    # -- Nutrition Report ------------------------------------------------------
    try:
      mf = data.get("macrofactor") or {}
      if mf.get("total_calories_kcal") is not None:"""

    nutr_end = """        html += '<!-- S:nutrition -->' + nc + '<!-- /S:nutrition -->'"""
    nutr_end_new = """        html += '<!-- S:nutrition -->' + nc + '<!-- /S:nutrition -->'
    except Exception as _e:
        html += _section_error_html("Nutrition Report", _e)"""

    if old_nutr in content and nutr_end in content:
        content = content.replace(old_nutr, new_nutr, 1)
        content = content.replace(nutr_end, nutr_end_new, 1)
        changes.append("Wrapped Nutrition Report in try/except")

    # 6d. Habits Deep-Dive (most complex section — registry, tiers, vices, groups)
    old_habits = """    # -- Habits Deep-Dive (v2.47: tier-organized from habit_registry) ----------
    habitify = data.get("habitify") or {}
    habits_map = habitify.get("habits", {})
    registry = profile.get("habit_registry", {})
    by_group = habitify.get("by_group", {})
    hd_details = component_details.get("habits_mvp", {})
    tier_status = hd_details.get("tier_status", {})
    vice_stat = hd_details.get("vice_status", {})

    if habits_map and (registry or profile.get("mvp_habits")):"""

    new_habits = """    # -- Habits Deep-Dive (v2.47: tier-organized from habit_registry) ----------
    try:
      habitify = data.get("habitify") or {}
      habits_map = habitify.get("habits", {})
      registry = profile.get("habit_registry", {})
      by_group = habitify.get("by_group", {})
      hd_details = component_details.get("habits_mvp", {})
      tier_status = hd_details.get("tier_status", {})
      vice_stat = hd_details.get("vice_status", {})

      if habits_map and (registry or profile.get("mvp_habits")):"""

    habits_end = """        html += '<!-- S:habits -->' + hc + '<!-- /S:habits -->'"""
    habits_end_new = """        html += '<!-- S:habits -->' + hc + '<!-- /S:habits -->'
    except Exception as _e:
        html += _section_error_html("Habits Deep-Dive", _e)"""

    if old_habits in content and habits_end in content:
        content = content.replace(old_habits, new_habits, 1)
        content = content.replace(habits_end, habits_end_new, 1)
        changes.append("Wrapped Habits Deep-Dive in try/except")

    # 6e. CGM Spotlight
    old_cgm_start = """        # -- CGM Spotlight (v2.3: fasting proxy, hypo flag, 7-day trend) ----------
    apple = data.get("apple") or {}"""

    new_cgm_start = """        # -- CGM Spotlight (v2.3: fasting proxy, hypo flag, 7-day trend) ----------
    try:
      apple = data.get("apple") or {}"""

    cgm_end = """        html += '<!-- S:cgm -->' + gc2 + '<!-- /S:cgm -->'"""
    cgm_end_new = """        html += '<!-- S:cgm -->' + gc2 + '<!-- /S:cgm -->'
    except Exception as _e:
        html += _section_error_html("CGM Spotlight", _e)"""

    if old_cgm_start in content and cgm_end in content:
        content = content.replace(old_cgm_start, new_cgm_start, 1)
        content = content.replace(cgm_end, cgm_end_new, 1)
        changes.append("Wrapped CGM Spotlight in try/except")

    # 6f. Weight Phase Tracker
    old_weight = """        # -- Weight Phase Tracker (v2.2: weekly delta callout) ---------------------
    latest_weight = data.get("latest_weight")
    if latest_weight:"""

    new_weight = """        # -- Weight Phase Tracker (v2.2: weekly delta callout) ---------------------
    try:
      latest_weight = data.get("latest_weight")
      if latest_weight:"""

    weight_end = """            html += '<!-- /S:weight_phase -->'"""
    weight_end_new = """            html += '<!-- /S:weight_phase -->'
    except Exception as _e:
        html += _section_error_html("Weight Phase", _e)"""

    if old_weight in content and weight_end in content:
        content = content.replace(old_weight, new_weight, 1)
        content = content.replace(weight_end, weight_end_new, 1)
        changes.append("Wrapped Weight Phase in try/except")

    # 6g. Gait & Mobility
    old_gait = """    gait_speed = safe_float(apple, "walking_speed_mph")
    gait_step_len = safe_float(apple, "walking_step_length_in")
    gait_asym = safe_float(apple, "walking_asymmetry_pct")
    gait_dbl_support = safe_float(apple, "walking_double_support_pct")
    has_gait = any(v is not None and v > 0 for v in [gait_speed, gait_step_len])
    if has_gait:"""

    new_gait = """    try:
      gait_speed = safe_float(apple, "walking_speed_mph")
      gait_step_len = safe_float(apple, "walking_step_length_in")
      gait_asym = safe_float(apple, "walking_asymmetry_pct")
      gait_dbl_support = safe_float(apple, "walking_double_support_pct")
      has_gait = any(v is not None and v > 0 for v in [gait_speed, gait_step_len])
      if has_gait:"""

    gait_end = """        html += '<!-- S:gait -->' + gt + '<!-- /S:gait -->'"""
    gait_end_new = """        html += '<!-- S:gait -->' + gt + '<!-- /S:gait -->'
    except Exception as _e:
        html += _section_error_html("Gait & Mobility", _e)"""

    if old_gait in content and gait_end in content:
        content = content.replace(old_gait, new_gait, 1)
        content = content.replace(gait_end, gait_end_new, 1)
        changes.append("Wrapped Gait & Mobility in try/except")

    # 6h. Anomaly Alert
    old_anomaly = """    anomaly_data = data.get("anomaly", {})
    if anomaly_data.get("severity") in ("moderate", "high"):"""

    new_anomaly = """    try:
      anomaly_data = data.get("anomaly", {})
      if anomaly_data.get("severity") in ("moderate", "high"):"""

    anomaly_end = """        html += '</div>'

    # -- Footer """
    anomaly_end_new = """        html += '</div>'
    except Exception as _e:
        html += _section_error_html("Anomaly Alert", _e)

    # -- Footer """

    if old_anomaly in content and anomaly_end in content:
        content = content.replace(old_anomaly, new_anomaly, 1)
        content = content.replace(anomaly_end, anomaly_end_new, 1)
        changes.append("Wrapped Anomaly Alert in try/except")

    # =========================================================================
    # 7. Update version string in docstring
    # =========================================================================
    old_ver = "Daily Brief Lambda — v2.47.0"
    new_ver = "Daily Brief Lambda — v2.53.1"
    if old_ver in content:
        content = content.replace(old_ver, new_ver, 1)
        changes.append("Updated version to v2.53.1")

    # =========================================================================
    # Summary
    # =========================================================================
    print(f"\n{'='*60}")
    print(f"Daily Brief Hardening Patch — {len(changes)} changes applied")
    print(f"{'='*60}")
    for i, c in enumerate(changes, 1):
        print(f"  {i:2d}. {c}")
    print()

    if content == original:
        print("⚠  WARNING: No changes were made! Check if file was already patched.")
        return content

    return content


def main():
    if not os.path.exists(LAMBDA_PATH):
        print(f"ERROR: File not found: {LAMBDA_PATH}")
        sys.exit(1)

    # Backup
    backup_path = LAMBDA_PATH + f".backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    print(f"Reading:  {LAMBDA_PATH}")
    with open(LAMBDA_PATH, "r") as f:
        content = f.read()

    print(f"Backup:   {backup_path}")
    with open(backup_path, "w") as f:
        f.write(content)

    # Patch
    patched = patch(content)

    # Write
    print(f"Writing:  {LAMBDA_PATH}")
    with open(LAMBDA_PATH, "w") as f:
        f.write(patched)

    print(f"\nOriginal size: {len(content):,} bytes")
    print(f"Patched size:  {len(patched):,} bytes")
    print(f"Delta:         {len(patched) - len(content):+,} bytes")
    print(f"\nNext steps:")
    print(f"  1. Review the patched file")
    print(f"  2. cd lambdas && zip daily_brief_lambda.zip lambda_function.py")
    print(f"     (Remember: zip must contain lambda_function.py, not daily_brief_lambda.py)")
    print(f"  3. Deploy: aws lambda update-function-code \\")
    print(f"       --function-name daily-brief \\")
    print(f"       --zip-file fileb://daily_brief_lambda.zip")
    print(f"\nTo revert: cp {backup_path} {LAMBDA_PATH}")


if __name__ == "__main__":
    main()
