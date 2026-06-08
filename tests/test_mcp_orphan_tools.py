"""
tests/test_mcp_orphan_tools.py — Phase 4.8 (2026-05-16): enforce MCP registry
wiring discipline.

Every `def tool_*` function in `mcp/tools_*.py` must be either:
  (a) Registered in `mcp/registry.py` (the canonical wire), OR
  (b) Explicitly listed in `KNOWN_ORPHANS` below with a TODO action

Audit at time of writing: 186 tool_ defined, 116 registered → 70 orphans.
Most look like work-in-progress (real tools written but never wired).

The KNOWN_ORPHANS allowlist preserves them without losing visibility — the
test passes today, but adding a NEW orphan will fail CI. As each item is
either registered or deleted, remove it from KNOWN_ORPHANS.

Run:  python3 -m pytest tests/test_mcp_orphan_tools.py -v
"""

import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MCP_DIR = os.path.join(ROOT, "mcp")


def _defined_tools():
    """Find every `def tool_*` across all tools_*.py modules."""
    found = set()
    for f in os.listdir(MCP_DIR):
        if not f.startswith("tools_") or not f.endswith(".py"):
            continue
        with open(os.path.join(MCP_DIR, f), encoding="utf-8") as fh:
            for m in re.finditer(r"^def (tool_[a-z_]+)", fh.read(), re.MULTILINE):
                found.add(m.group(1))
    return found


def _registered_tools():
    """Find every tool registered in registry.py via `"some_name": tool_some_name`."""
    found = set()
    path = os.path.join(MCP_DIR, "registry.py")
    if not os.path.exists(path):
        return found
    with open(path, encoding="utf-8") as fh:
        for m in re.finditer(r"tool_[a-z_]+", fh.read()):
            found.add(m.group(0))
    return found


# Tools known to be defined but not registered. Each entry is technical debt:
# either register the tool in registry.py or delete the function from tools_*.py.
# Updating this list is fine — but adding NEW entries should be rare (means
# the test detected a new orphan that the contributor didn't intend).
KNOWN_ORPHANS = {
    # Sick days (4 orphans)
    "tool_clear_sick_day",
    "tool_get_sick_days",
    "tool_log_sick_day",
    # CGM / glucose (4 orphans)
    "tool_get_cgm_dashboard",
    "tool_get_fasting_glucose_validation",
    "tool_get_glucose_exercise_correlation",
    "tool_get_glucose_sleep_correlation",
    # Character / level (4 orphans)
    "tool_get_character_sheet",
    "tool_get_level_history",
    "tool_get_non_scale_victories",
    "tool_get_pillar_detail",
    # Habits (7 orphans — tier_report registered)
    "tool_get_habit_adherence",
    "tool_get_habit_dashboard",
    "tool_get_habit_health_correlations",
    "tool_get_habit_stacks",
    "tool_get_habit_streaks",
    "tool_get_keystone_habits",
    "tool_get_group_trends",
    # Health dashboards + correlations (10 orphans)
    "tool_get_aggregated_summary",
    "tool_get_alcohol_sleep_correlation",
    "tool_get_blood_pressure_correlation",
    "tool_get_body_composition_snapshot",
    "tool_get_caffeine_sleep_correlation",
    "tool_get_exercise_sleep_correlation",
    "tool_get_exposure_correlation",
    "tool_get_health_dashboard",
    "tool_get_health_risk_profile",
    "tool_get_health_trajectory",
    # Labs (4 orphans)
    "tool_get_lab_results",
    "tool_get_lab_trends",
    "tool_get_out_of_range_history",
    "tool_get_next_lab_priorities",
    # Nutrition (5 orphans)
    "tool_get_hydration_score",
    "tool_get_macro_targets",
    "tool_get_meal_timing",
    "tool_get_micronutrient_report",
    "tool_get_nutrition_biometrics_correlation",
    # Strength + training (4 orphans)
    "tool_get_personal_records",
    "tool_get_training_load",
    "tool_get_training_periodization",
    "tool_get_training_recommendation",
    "tool_get_exercise_variety",
    # Movement + lifestyle (7 orphans; tool_get_calendar_events removed V2 P4.1)
    "tool_get_daily_summary",
    "tool_get_day_type_analysis",
    "tool_get_energy_balance",
    "tool_get_energy_expenditure",
    "tool_get_movement_score",
    "tool_get_ruck_log",
    "tool_get_exposure_log",
    # Mind / social (7 orphans)
    "tool_get_gait_analysis",
    "tool_get_journal_correlations",
    "tool_get_meditation_correlation",
    "tool_get_mood_trend",
    "tool_get_seasonal_patterns",
    "tool_get_social_isolation_risk",
    "tool_get_state_of_mind_trend",
    # Misc (8 orphans)
    "tool_get_latest",
    "tool_get_nutrition_summary",
    "tool_get_supplement_correlation",  # tool_get_schedule_load removed V2 P4.1
    "tool_get_weather_correlation",
    "tool_log_exposure",
    "tool_log_ruck",
    "tool_remove_board_member",
    "tool_update_board_member",
}


def test_no_unexpected_orphans():
    """Every tool_ function must be registered OR in KNOWN_ORPHANS."""
    defined = _defined_tools()
    registered = _registered_tools()
    orphans = defined - registered
    new_orphans = orphans - KNOWN_ORPHANS

    assert not new_orphans, (
        f"Found {len(new_orphans)} NEW orphan tool(s):\n"
        + "\n".join(f"  - {t}" for t in sorted(new_orphans))
        + "\n\nFix: either register in mcp/registry.py or add to KNOWN_ORPHANS "
        "in this test (with a plan to register or delete)."
    )


def test_known_orphans_still_orphans():
    """KNOWN_ORPHANS shouldn't drift — if one gets registered or deleted,
    remove it from the list to keep the allowlist tight."""
    defined = _defined_tools()
    registered = _registered_tools()
    current_orphans = defined - registered

    stale = KNOWN_ORPHANS - current_orphans
    assert not stale, (
        f"KNOWN_ORPHANS has {len(stale)} entry(ies) that are no longer orphans "
        "(either registered or deleted). Remove these from the list:\n" + "\n".join(f"  - {t}" for t in sorted(stale))
    )


def test_orphan_count_doesnt_grow():
    """Catch accidental regression — total orphan count shouldn't increase."""
    defined = _defined_tools()
    registered = _registered_tools()
    orphans = defined - registered
    AUDITED_AT = 64  # 2026-05-17 — V2 P4.1: tools_calendar.py deleted (ADR-030 retired Google Calendar), 2 entries removed
    assert len(orphans) <= AUDITED_AT, (
        f"Orphan count is {len(orphans)} (was {AUDITED_AT} at audit). "
        "Each new orphan is tech debt — either register it or delete the function."
    )
