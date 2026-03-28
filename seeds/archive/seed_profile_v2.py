"""
seed_profile_v2.py — Profile v2.0 for Daily Brief v2 + Board of Directors coaching.

Overwrites PROFILE#v1 with expanded fields covering:
  - Lifestyle targets (wake, sleep, nutrition, movement)
  - Macro targets (board-recommended)
  - Training schedule
  - Day grade weights + MVP habits
  - Health context (family history, obstacles)
  - Coaching context (why, tone, social)

Run once, update as needed:
  python3 seed_profile_v2.py
"""

import boto3
from decimal import Decimal
from datetime import datetime

dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table    = dynamodb.Table("life-platform")

profile = {
    "pk": "USER#matthew",
    "sk": "PROFILE#v1",

    # ── Identity ──────────────────────────────────────────────────────────────
    "name":              "Matthew Walker",
    "date_of_birth":     "1989-02-07",
    "age":               Decimal("36"),
    "biological_sex":    "male",
    "height_inches":     Decimal("69"),       # 5'9"

    # ── Current Stats ─────────────────────────────────────────────────────────
    "current_weight_lbs":    Decimal("302"),   # Update as journey progresses
    "goal_weight_lbs":       Decimal("185"),
    "journey_start_date":    "2026-04-01",
    "journey_start_weight_lbs": Decimal("302"),

    # ── Weight Loss Phases (Board-approved, Matthew's aggressive targets) ─────
    # Phase auto-detected from current Withings weight.
    # Deficit target per phase overrides the global deficit_target_kcal.
    # Board caveat: protein MUST stay ≥180g at 3 lb/wk rate. Monitor RHR + HRV
    # trends during Phase 1 — persistent RHR rise or HRV drop = deficit too aggressive.
    "weight_loss_phases": [
        {"phase": 1, "name": "Ignition",  "start_lbs": Decimal("302"), "end_lbs": Decimal("250"),
         "weekly_target_lbs": Decimal("3.0"), "deficit_target_kcal": Decimal("1500"),
         "projected_end": "2026-06-21"},
        {"phase": 2, "name": "Push",      "start_lbs": Decimal("250"), "end_lbs": Decimal("220"),
         "weekly_target_lbs": Decimal("2.5"), "deficit_target_kcal": Decimal("1250"),
         "projected_end": "2026-09-13"},
        {"phase": 3, "name": "Grind",     "start_lbs": Decimal("220"), "end_lbs": Decimal("200"),
         "weekly_target_lbs": Decimal("2.0"), "deficit_target_kcal": Decimal("1000"),
         "projected_end": "2026-11-22"},
        {"phase": 4, "name": "Chisel",    "start_lbs": Decimal("200"), "end_lbs": Decimal("185"),
         "weekly_target_lbs": Decimal("1.0"), "deficit_target_kcal": Decimal("500"),
         "projected_end": "2027-03-07"},
    ],
    "projected_goal_date":   "2027-03-07",     # 302 → 185 in ~54 weeks

    # ── Lifestyle Targets ─────────────────────────────────────────────────────
    "wake_target":           "04:30",          # 4:15-4:45 window, 4:30 center
    "wake_window_earliest":  "04:15",
    "wake_window_latest":    "04:45",
    "sleep_target_hours_min": Decimal("7.0"),
    "sleep_target_hours_max": Decimal("9.0"),
    "sleep_target_hours_ideal": Decimal("7.5"),  # Board: 7.5h is sweet spot for recovery + deficit
    "bedtime_target":        "21:00",          # Derived: 4:30 AM - 7.5h = 9:00 PM

    # ── Nutrition Targets ─────────────────────────────────────────────────────
    "calorie_target":        Decimal("1800"),   # Will change — update here
    "calorie_tolerance_pct": Decimal("10"),     # ±10% = full marks on day grade
    "calorie_penalty_threshold_pct": Decimal("25"),  # >25% over = significant penalty
    "protein_target_g":      Decimal("190"),    # Board: 1g/lb goal weight
    "protein_floor_g":       Decimal("170"),    # Board: minimum acceptable
    "fat_target_g":          Decimal("60"),     # Board: 30% of cal, hormone protection
    "carb_target_g":         Decimal("125"),    # Board: 28% of cal, training fuel
    "deficit_target_kcal":   Decimal("1500"),   # Phase 1 (Ignition): 3 lbs/week — updates per phase

    # ── Eating Window ─────────────────────────────────────────────────────────
    "eating_window_start":   "11:30",          # 16:8 IF
    "eating_window_end":     "19:30",          # 7:30 PM

    # ── Caffeine ──────────────────────────────────────────────────────────────
    "caffeine_daily_cups":   Decimal("2"),
    "caffeine_first_cup":    "07:00",
    "caffeine_cutoff_base":  "12:00",          # Huberman: no later than noon, adjusted by HRV

    # ── Hydration ─────────────────────────────────────────────────────────────
    "water_target_oz":       Decimal("100"),    # ~3L
    "water_target_ml":       Decimal("2957"),   # 100 fl oz in mL

    # ── Movement ──────────────────────────────────────────────────────────────
    "step_target":           Decimal("7000"),   # ~3 miles at 5'9" / 302 lbs
    "zone2_weekly_target_min": Decimal("150"),  # WHO/Attia/Huberman consensus

    # ── Training ──────────────────────────────────────────────────────────────
    "training_split":        "push/pull/legs",
    "training_days_per_week": Decimal("5"),
    "training_time_window":  "05:00-07:00",    # Before work
    "training_style":        "morning lifter, evening walker",
    "primary_sports":        ["weightlifting", "walk", "hike"],

    # ── Sport Profile ─────────────────────────────────────────────────────────
    "sport_focus":           "body recomposition",  # Was "endurance" — updated for current goals
    "resting_heart_rate_baseline": Decimal("65"),
    "max_heart_rate":        Decimal("183"),
    "vo2max_estimate":       None,             # No validated measurement

    # ── Day Grade Configuration ───────────────────────────────────────────────
    "day_grade_weights": {
        "sleep_quality":     Decimal("0.20"),
        "recovery":          Decimal("0.15"),
        "nutrition":         Decimal("0.20"),
        "movement":          Decimal("0.15"),
        "habits_mvp":        Decimal("0.15"),
        "hydration":         Decimal("0.05"),
        "journal":           Decimal("0.05"),
        "glucose":           Decimal("0.05"),
    },
    "day_grade_algorithm_version": "1.0",

    # ── MVP Habits (streak-tracked) ──────────────────────────────────────────
    # These names must EXACTLY match Habitify habit names
    "mvp_habits": [
        "Out Of Bed Before 5am",
        "Primary Exercise",
        "Walk 5k",
        "Calorie Goal",
        "Intermittent Fast 16:8",
        "No alcohol",
        "No marijuana",
        "Morning Sunlight / Luminette Glasses",
        "Hydrate 3L",
    ],
    "mvp_habits_version": "1.0",   # Bump when list changes, for retrocompute

    # ── Health Context ────────────────────────────────────────────────────────
    "medications":           [],
    "supplements": [
        "creatine", "collagen", "probiotics", "electrolytes",
        "L-glutamine", "lions mane", "cordyceps", "reishi",
        "multivitamin", "green tea phytosome", "B complex",
        "omega 3", "zinc picolinate", "vitamin D", "NAC",
        "inositol", "theanine", "apigenin", "glycine",
        "L-threonate",
    ],
    "food_sensitivities":    [],
    "family_health_history": {
        "mother": "non-Hodgkins lymphoma (deceased)",
        "father": None,
        "notes":  "Lymphoma risk factor — board recommends regular CBC + inflammatory markers (CRP, ESR, LDH)",
    },
    "blood_pressure":        None,   # UNKNOWN — flag in quarterly brief
    "waist_circumference_in": None,  # UNKNOWN — flag in quarterly brief
    "body_fat_pct":          None,   # UNKNOWN — last DEXA outdated by ~100 lbs gain

    # ── Quarterly Reminders ───────────────────────────────────────────────────
    # Items the brief/quarterly report should nag about
    "quarterly_reminders": [
        "Measure blood pressure and update profile",
        "Measure waist circumference and update profile",
        "Schedule DEXA scan for updated body composition",
        "Review supplement stack with latest research",
        "Get blood work drawn (see get_next_lab_priorities)",
    ],

    # ── Work & Social Context ─────────────────────────────────────────────────
    "occupation":            "Senior Director, SaaS company",
    "work_schedule":         "remote, 8:00am-5:00pm PT",
    "social_context":        "partner (girlfriend), no kids",

    # ── Mental Health & Obstacles ─────────────────────────────────────────────
    "primary_obstacles": [
        "depression",
        "shame",
        "low confidence",
        "low self-esteem",
        "social anxiety",
    ],
    "coaching_context":      "Mental health is intertwined with physical transformation. "
                             "Every discipline win is evidence against negative self-narrative. "
                             "Coach should be direct and empathetic, not coddling. "
                             "Acknowledge hard days without enabling avoidance.",

    # ── Project40 Why ─────────────────────────────────────────────────────────
    "project40_why":         "To become present, happy, fulfilled, and fully alive — "
                             "using discipline as the bridge between where I am and "
                             "the life I want to feel again.",

    "coaching_tone":         "direct, empathetic, no-BS. Jocko's discipline meets "
                             "Attia's precision meets Brené Brown's vulnerability.",

    # ── Macro Targets (Board-Recommended) ─────────────────────────────────────
    "macro_targets": {
        "protein_g":  Decimal("190"),   # 42% of cal — lean mass protection
        "fat_g":      Decimal("60"),    # 30% of cal — hormone protection
        "carbs_g":    Decimal("125"),   # 28% of cal — training fuel, low-carb bias
        "notes":      "High protein, moderate fat, controlled carb. "
                      "Concentrate carbs around training window (pre/post workout). "
                      "Board: Attia + Patrick consensus for deficit + recomp.",
    },

    # ── Source-of-Truth Domains ───────────────────────────────────────────────
    "source_of_truth": {
        "cardio":             "strava",
        "strength":           "macrofactor",    # Updated: MacroFactor now tracks workouts
        "physiology":         "whoop",
        "nutrition":          "macrofactor",
        "sleep":              "eightsleep",
        "body":               "withings",
        "steps":              "apple_health",
        "tasks":              "todoist",
        "habits":             "habitify",
        "stress":             "garmin",
        "body_battery":       "garmin",
        "gait":               "apple_health",
        "energy_expenditure": "apple_health",
        "cgm":                "apple_health",
        "journal":            "notion",
        "water":              "apple_health",
    },

    # ── Metadata ──────────────────────────────────────────────────────────────
    "timezone":              "America/Los_Angeles",
    "units":                 "imperial",
    "profile_version":       "2.0",
    "last_updated":          datetime.now().strftime("%Y-%m-%d"),
}

# ── Clean None values (DynamoDB doesn't store them) ───────────────────────────
def clean(obj):
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [clean(i) for i in obj]
    return obj

profile_clean = clean(profile)

table.put_item(Item=profile_clean)
print("✅ Profile v2.0 written to DynamoDB")
print()
print("Key targets:")
print(f"   Wake:      {profile['wake_target']}")
print(f"   Bedtime:   {profile['bedtime_target']}")
print(f"   Calories:  {profile['calorie_target']} (±{profile['calorie_tolerance_pct']}% tolerance)")
print(f"   Protein:   {profile['protein_target_g']}g (floor: {profile['protein_floor_g']}g)")
print(f"   Macros:    P{profile['macro_targets']['protein_g']}g / F{profile['macro_targets']['fat_g']}g / C{profile['macro_targets']['carbs_g']}g")
print(f"   Deficit:   {profile['deficit_target_kcal']} kcal/day")
print(f"   Steps:     {profile['step_target']}")
print(f"   Water:     {profile['water_target_oz']} oz")
print(f"   MVP Habits: {len(profile['mvp_habits'])} tracked")
print(f"   Day Grade:  v{profile['day_grade_algorithm_version']}")
print()
print("Weight loss phases:")
for p in profile["weight_loss_phases"]:
    print(f"   Phase {p['phase']} ({p['name']}): {p['start_lbs']}→{p['end_lbs']} lbs @ {p['weekly_target_lbs']} lbs/wk → {p['projected_end']}")
print(f"   🎯 Goal: {profile['goal_weight_lbs']} lbs by {profile['projected_goal_date']}")
print()
print("⚠️  Quarterly reminders set:")
for r in profile["quarterly_reminders"]:
    print(f"   • {r}")
print()
print(f"🎯 Why: {profile['project40_why']}")
