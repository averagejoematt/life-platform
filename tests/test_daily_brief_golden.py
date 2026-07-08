"""tests/test_daily_brief_golden.py — golden-snapshot harness for the daily brief HTML.

Purpose: html_builder.build_html renders the platform's flagship email. This pins
its FULL rendered HTML for frozen, synthetic-but-realistic data packets against
checked-in golden files. Time-dependent fragments (anything derived from "now")
are normalized out before comparison, so the snapshots are stable across days.

Two scenarios are covered:
  - "standard": a quiet day, brief_mode=standard, optional sections absent. This
    is the original golden.
  - "rich": everything-on — flourishing mode, character sheet, all V2 coaches,
    vacation fund, triggered rewards, a Sunday weekly-habit-review, plus CGM /
    blood-pressure / weather / task-load / anomaly data. This guards the
    param-conditional sections the "standard" scenario never exercises (the gap
    the build_html decomposition, #18, had to verify with a throwaway harness).

To intentionally change the brief's output:
    GOLDEN_UPDATE=1 python3 -m pytest tests/test_daily_brief_golden.py
then review the golden diff in the PR like any other code change.
"""

import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

FIXTURES = Path(__file__).parent / "fixtures"

PROFILE = {
    "calorie_target": 1500,
    "protein_target_g": 190,
    "protein_floor_g": 170,
    "fat_target_g": 60,
    "carb_target_g": 125,
    "goal_weight_lbs": 185,
    # Far past on purpose: html_builder's BoD confidence badge computes days_of_data
    # from wall-clock *now* minus this date, so a recent date makes the golden
    # time-dependent (it flipped LOW->MEDIUM when the real experiment crossed n=30).
    # ~2 years back keeps the badge pinned at HIGH forever -> deterministic snapshot.
    "journey_start_date": "2024-06-08",
    "journey_start_weight_lbs": 311.62,
    "day_grade_weights": {
        "sleep_quality": 0.2,
        "recovery": 0.1,
        "nutrition": 0.25,
        "movement": 0.2,
        "habits_mvp": 0.15,
        "hydration": 0.05,
        "journal": 0.05,
        "glucose": 0.0,
    },
}

DATA = {
    "date": "2026-06-10",
    "whoop": {
        "recovery_score": 68,
        "hrv": 41.2,
        "resting_heart_rate": 58,
        "sleep_duration_hours": 8.1,
        "sleep_quality_score": 82,
    },
    "sleep": {"sleep_efficiency_pct": 89.0, "rem_pct": 24.0, "deep_pct": 19.0},
    "macrofactor": {"calories": 1480, "protein_g": 185, "fat_g": 55, "carbs_g": 120},
    "habitify": {"habits": {"Walk": 1, "Log food": 1, "Meditate": 0}},
    "apple": {"steps": 9200, "water_oz": 80},
    "strava": {"activities": [{"type": "Walk", "moving_time": 2400, "distance": 3200}]},
    "withings": {"weight_lbs": 306.9},
}

COMPONENT_SCORES = {
    "sleep_quality": 84,
    "recovery": 68,
    "nutrition": 91,
    "movement": 77,
    "habits_mvp": 67,
    "hydration": 80,
    "journal": None,
    "glucose": None,
}

KWARGS = dict(
    data=DATA,
    profile=PROFILE,
    day_grade_score=79,
    grade="B+",
    component_scores=COMPONENT_SCORES,
    component_details={},
    readiness_score=72,
    readiness_colour="#059669",
    tldr_guidance={"tldr": "Solid recovery day — keep the deficit honest and walk after dinner."},
    bod_insight="Dr. Kai Nakamura: protect the 9 PM wind-down; the streak follows the bedtime.",
    training_nutrition={
        "training": "Zone-2 walk planned — keep it conversational pace.",
        "nutrition": "Protein on target; hold the line after 8 PM.",
    },
    journal_coach_text=None,
    mvp_streak=3,
    full_streak=1,
    vice_streaks={"streaks": []},
    character_sheet=None,
    brief_mode="standard",
)

# ── Rich "everything-on" scenario ──────────────────────────────────────────
# Exercises the optional/param-driven sections absent from the standard golden.
_COACHES = dict(
    sleep_coach_v2_text="Sleep: wind down by 9.",
    nutrition_coach_v2_text="Nutrition: protein first.",
    training_coach_v2_text="Training: easy aerobic.",
    mind_coach_v2_text="Mind: 5 min breathing.",
    physical_coach_v2_text="Physical: hips mobility.",
    glucose_coach_v2_text="Glucose: walk post-meal.",
    labs_coach_v2_text="Labs: ferritin trending up.",
    explorer_coach_v2_text="Explorer: try a new trail.",
)
_CHARACTER = {
    "level": 7,
    "xp": 4200,
    "xp_to_next": 800,
    "tier": "Operator",
    "attributes": {"vitality": 72, "discipline": 81, "resilience": 65},
}
_VACATION = {"balance_usd": 128, "total_earned_usd": 412, "this_week_usd": 14, "miles_this_week": 14}
RICH_DATA = {
    **DATA,
    "date": "2026-06-14",  # a Sunday → weekly-habit-review section renders
    "cgm": {"mean_glucose": 98, "time_in_range_pct": 88, "readings": 240},
    "blood_pressure": {"systolic": 118, "diastolic": 76, "readings": 2},
    "weather": {"temp_high_f": 72, "temp_low_f": 54, "condition": "Clear"},
    "todoist": {"due_today": 5, "completed_today": 3, "overdue": 1},
    "anomalies": [{"metric": "hrv", "msg": "HRV 2.1σ below 30-day mean"}],
}
RICH_KWARGS = {
    **KWARGS,
    **_COACHES,
    "data": RICH_DATA,
    "brief_mode": "flourishing",
    "character_sheet": _CHARACTER,
    "vacation_fund": _VACATION,
    "vice_streaks": {"streaks": [{"name": "No alcohol", "days": 12}]},
    "weekly_habit_review": {"habits": [{"name": "Walk", "rate": 0.86}], "summary": "Strong week."},
    "triggered_rewards": [{"name": "Movie night", "reason": "7-day streak"}],
    "protocol_recs": [{"title": "Magnesium", "detail": "200mg pre-bed"}],
    "engagement_score": 91,
}

SCENARIOS = {
    "standard": (KWARGS, "daily_brief_golden.html"),
    "rich": (RICH_KWARGS, "daily_brief_golden_rich.html"),
}

# Volatile fragments derived from "now" at render time → normalize before compare.
_NORMALIZERS = [
    (re.compile(r"n=\d+"), "n=N"),
    (re.compile(r"Day \d+ of"), "Day N of"),
]


def _normalize(html: str) -> str:
    for pat, repl in _NORMALIZERS:
        html = pat.sub(repl, html)
    return html


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_daily_brief_golden_snapshot(scenario):
    from html_builder import build_html

    kwargs, golden_name = SCENARIOS[scenario]
    html = build_html(**kwargs)

    # Structural floor: these must exist regardless of styling churn.
    assert "<html" in html.lower() and len(html) > 5000, f"{scenario}: brief rendered suspiciously small"
    # No section may silently fall back to its error placeholder.
    assert "section unavailable" not in html, f"{scenario}: a section crashed into _section_error_html"

    norm = _normalize(html)
    golden = FIXTURES / golden_name
    if os.environ.get("GOLDEN_UPDATE") or not golden.exists():
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(norm)
        if not os.environ.get("GOLDEN_UPDATE"):
            raise AssertionError(f"{scenario}: golden file created — commit it and re-run")
        return
    expected = golden.read_text()
    assert norm == expected, (
        f"{scenario}: daily brief HTML changed vs golden snapshot.\n"
        "If intentional: GOLDEN_UPDATE=1 python3 -m pytest tests/test_daily_brief_golden.py "
        "and review the golden diff in the PR.\n"
        f"(rendered {len(norm)} bytes vs golden {len(expected)} bytes)"
    )
