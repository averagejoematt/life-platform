"""
tests/test_daily_brief_golden.py — golden-snapshot harness for the daily brief HTML.

Purpose: html_builder.build_html is ~1,500 lines with no output-level test —
any refactor of it (or of the daily-brief pipeline that feeds it) currently has
no safety net beyond eyeballing a diff of the platform's flagship email.

This pins the FULL rendered HTML for a frozen, synthetic-but-realistic data
packet against a checked-in golden file. Time-dependent fragments (anything
derived from "now") are normalized out before comparison, so the snapshot is
stable across days.

To intentionally change the brief's output:
    GOLDEN_UPDATE=1 python3 -m pytest tests/test_daily_brief_golden.py
then review the golden diff in the PR like any other code change.

This is the prerequisite for decomposing build_html (and lambda_handler):
extract a section, re-run, byte-identical golden ⇒ the refactor changed nothing.
"""

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

GOLDEN = Path(__file__).parent / "fixtures" / "daily_brief_golden.html"

PROFILE = {
    "calorie_target": 1500,
    "protein_target_g": 190,
    "protein_floor_g": 170,
    "fat_target_g": 60,
    "carb_target_g": 125,
    "goal_weight_lbs": 185,
    "journey_start_date": "2026-06-08",
    "journey_start_weight_lbs": 311.62,
    "day_grade_weights": {
        "sleep_quality": 0.2, "recovery": 0.1, "nutrition": 0.25, "movement": 0.2,
        "habits_mvp": 0.15, "hydration": 0.05, "journal": 0.05, "glucose": 0.0,
    },
}

DATA = {
    "date": "2026-06-10",
    "whoop": {
        "recovery_score": 68, "hrv": 41.2, "resting_heart_rate": 58,
        "sleep_duration_hours": 8.1, "sleep_quality_score": 82,
    },
    "sleep": {"sleep_efficiency_pct": 89.0, "rem_pct": 24.0, "deep_pct": 19.0},
    "macrofactor": {"calories": 1480, "protein_g": 185, "fat_g": 55, "carbs_g": 120},
    "habitify": {"habits": {"Walk": 1, "Log food": 1, "Meditate": 0}},
    "apple": {"steps": 9200, "water_oz": 80},
    "strava": {"activities": [{"type": "Walk", "moving_time": 2400, "distance": 3200}]},
    "withings": {"weight_lbs": 306.9},
}

COMPONENT_SCORES = {
    "sleep_quality": 84, "recovery": 68, "nutrition": 91, "movement": 77,
    "habits_mvp": 67, "hydration": 80, "journal": None, "glucose": None,
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

# Volatile fragments derived from "now" at render time → normalize before compare.
_NORMALIZERS = [
    (re.compile(r"n=\d+"), "n=N"),
    (re.compile(r"Day \d+ of"), "Day N of"),
]


def _normalize(html: str) -> str:
    for pat, repl in _NORMALIZERS:
        html = pat.sub(repl, html)
    return html


def _render() -> str:
    from html_builder import build_html

    return build_html(**KWARGS)


def test_daily_brief_golden_snapshot():
    html = _render()
    # Structural floor: these must exist regardless of styling churn.
    assert "<html" in html.lower() and len(html) > 5000, "brief rendered suspiciously small"
    norm = _normalize(html)
    if os.environ.get("GOLDEN_UPDATE") or not GOLDEN.exists():
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(norm)
        if not os.environ.get("GOLDEN_UPDATE"):
            raise AssertionError("golden file created — commit it and re-run")
        return
    golden = GOLDEN.read_text()
    assert norm == golden, (
        "daily brief HTML changed vs golden snapshot.\n"
        "If intentional: GOLDEN_UPDATE=1 python3 -m pytest tests/test_daily_brief_golden.py "
        "and review the golden diff in the PR.\n"
        f"(rendered {len(norm)} bytes vs golden {len(golden)} bytes)"
    )
