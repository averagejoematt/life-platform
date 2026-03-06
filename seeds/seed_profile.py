"""
seed_profile.py — Write Matthew's user profile to DynamoDB.

The profile record is used by the MCP server for:
  - Age at personal record calculations
  - TRIMP heart rate zone calibration (resting HR, max HR)
  - Weight loss journey tracking (start weight, goal weight, journey start date)
  - VO2 max estimation (future)
  - Age-adjusted population norm comparisons

Run once, update as needed:
  python3 seed_profile.py
"""

import boto3
from decimal import Decimal

dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table    = dynamodb.Table("life-platform")

profile = {
    "pk": "USER#matthew",
    "sk": "PROFILE#v1",

    # ── Identity ──────────────────────────────────────────────────────────────
    "name":              "Matthew Walker",
    "date_of_birth":     "1989-02-07",   # UPDATE if incorrect — drives age-at-record calcs
    "biological_sex":    "male",
    "height_inches":     Decimal("69"),  # 5'9" — update if needed

    # ── Sport profile ─────────────────────────────────────────────────────────
    "primary_sports":    ["run", "hike", "ride", "walk", "cycle", "soccer", "boxing"],
    "sport_focus":       "endurance",

    # ── Physiological baselines (used for TRIMP calculation) ──────────────────
    # Update from your Whoop resting state — use a calm morning average, not a stressed day
    "resting_heart_rate_baseline": Decimal("65"),   # bpm — your typical resting HR
    "max_heart_rate":              Decimal("183"),   # bpm — use highest ever seen on Whoop during hard effort
    "vo2max_estimate":             None,             # ml/kg/min — update if you have a test result

    # ── Weight loss journey ───────────────────────────────────────────────────
    # These three fields power get_weight_loss_dashboard. Set them accurately.
    # journey_start_date: the date you began intentional weight loss (not just when data starts)
    # journey_start_weight_lbs: your weight on that date (check Withings history)
    # goal_weight_lbs: your target — can update as you progress
    "journey_start_date":        "2026-02-22",   # UPDATE: the date you're starting this journey
    "journey_start_weight_lbs":  302,            # UPDATE: e.g. Decimal("285") — check Withings for exact value
    "goal_weight_lbs":           185,            # UPDATE: e.g. Decimal("185") — your target weight

    # ── General goals (for future 'am I on track?' queries) ──────────────────
    "target_weekly_miles": 10,   # e.g. Decimal("30") — build toward this over time
    "next_event":          None,   # e.g. "2026-09-15 5K"

    # ── Source-of-truth overrides ────────────────────────────────────────────
    # Only set these if you want to override the defaults in mcp_server.py.
    # Uncomment and update when a new source takes ownership of a domain.
    # e.g. if Garmin replaces Strava for cardio: "cardio": "garmin"
    "source_of_truth": {
        "cardio":     "strava",
        "strength":   "hevy",
        "physiology": "whoop",
        "nutrition":  "macrofactor",
        "sleep":      "eightsleep",
        "body":       "withings",
        "steps":      "apple_health",
        "tasks":      "todoist",
        "habits":     "chronicling",
    },

    # ── Metadata ──────────────────────────────────────────────────────────────
    "timezone":        "America/Los_Angeles",
    "units":           "imperial",
    "profile_version": "1.1",
    "last_updated":    "2026-02-22",
}

# DynamoDB won't store None values — strip them out
profile_clean = {k: v for k, v in profile.items() if v is not None}

table.put_item(Item=profile_clean)
print("✅ Profile written to DynamoDB:")
for k, v in sorted(profile_clean.items()):
    print(f"   {k}: {v}")
print()
print("⚠️  Remember to set these fields before using get_weight_loss_dashboard:")
missing = []
for field in ["journey_start_weight_lbs", "goal_weight_lbs"]:
    if field not in profile_clean:
        missing.append(f"   - {field}")
if missing:
    for m in missing:
        print(m)
else:
    print("   All weight loss fields are set ✅")
