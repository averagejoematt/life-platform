"""
tests/test_email_render_goldens.py — golden-snapshot net for the weekly/monthly
email render functions (companion to tests/test_daily_brief_golden.py).

The daily brief had a golden; the other emails did not. Each of these render
functions is a pure (inputs → HTML string) builder, so we pin the full output
for a frozen fixture. Any future refactor (e.g. the deferred build_html split,
or shared-layer changes) that alters an email's output shows up as a golden
diff in the PR instead of going unnoticed until it's in someone's inbox.

To intentionally change an email's output:
    GOLDEN_UPDATE=1 python3 -m pytest tests/test_email_render_goldens.py
then review the golden diff.

Covers the three flat-signature renderers (nutrition_review, weekly_plate,
monday_compass) plus the two nested-packet digests (weekly_digest,
monthly_digest). The digests' headline packets are produced by the real ex_*
extractors fed a frozen synthetic dataset, so the fixture shape can never drift
from production; the few small derived packets (training_load, trends,
projection, goals, windows) are hand-built from stable keys.
"""

import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "lambdas" / "emails"))

# Module-level boto3 clients are constructed at import — give them a region so
# import succeeds offline (no network call happens at construction).
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "email_goldens"

_AI = (
    '<div style="color:#cbd5e1;font-size:14px;line-height:1.6;">'
    "<p>Synthetic AI body for the golden — protein held, deficit honest, recovery climbing.</p></div>"
)
_TABLE = '<table style="width:100%;"><tr><td>Calories</td><td>1480 / 1500</td></tr><tr><td>Protein</td><td>185 g</td></tr></table>'


def _render_nutrition_review():
    import nutrition_review_lambda as m

    return m.build_email_html(
        _TABLE,
        _AI,
        {"this_start": "2026-06-01", "this_end": "2026-06-07"},
        {"latest_weight_lbs": 306.9, "change_30d_lbs": -4.7},
    )


def _render_weekly_plate():
    import weekly_plate_lambda as m

    return m.build_email_html(
        _AI,
        {"end": "2026-06-07"},
        {"latest_weight_lbs": 306.9, "change_7d_lbs": -1.8},
    )


def _render_monday_compass():
    import monday_compass_lambda as m

    return m.build_email_html(
        _AI,
        {"char_level": 4, "char_tier": "Foundation", "recovery": 68, "week_num": 2},
        "2026-06-08",
    )


# ── Nested-packet digests ──────────────────────────────────────────────────
# Both build_html() functions read packets produced by the ex_* extractors. We
# feed those SAME extractors a frozen synthetic dataset so the fixture shape is
# guaranteed to match production. Weekly extractors take {date: record} dicts;
# monthly extractors take lists of records (via digest_utils).

_DIGEST_PROFILE = {
    "sleep_target_hours_ideal": 7.5,
    "goal_weight_lbs": 265,
    "height_inches": 73,
    "journey_start_weight_lbs": 331.0,
    "journey_start_date": "2026-04-01",
}
_WEEK_DAYS = [f"2026-06-{d:02d}" for d in range(1, 8)]
_MONTH_DAYS = [f"2026-05-{d:02d}" for d in range(1, 29)]


def _wd_whoop_dict(days, recovery_base):
    return {
        d: {
            "recovery_score": recovery_base + (i % 5) * 3,
            "hrv": 55 + (i % 4) * 2,
            "resting_heart_rate": 52 - (i % 3),
            "strain": 12.0 + (i % 4) * 0.5,
            "sleep_score": 80 + (i % 5),
            "deep_pct": 18 + (i % 4),
            "rem_pct": 22 + (i % 3),
        }
        for i, d in enumerate(days)
    }


def _wd_withings_dict(days, offset):
    return {d: {"weight_lbs": 307.0 - i * 0.3 - offset, "body_fat_pct": 31.5 - i * 0.05, "sk": f"DATE#{d}"} for i, d in enumerate(days)}


def _wd_grades_dict(days, letters):
    return {d: {"total_score": 72 + (i % 6) * 3, "letter_grade": letters[i % len(letters)]} for i, d in enumerate(days)}


_DIGEST_COMMENTARY = (
    "💡 Insight of the Week\n"
    "Protein held steady and the deficit stayed honest; recovery is climbing.\n"
    "🏋️ Training\nLoad trended up without torching recovery.\n"
    "😴 Sleep\nDebt is shrinking week over week.\n"
    "🥗 Nutrition\nProtein landed on target most days."
)


def _render_weekly_digest():
    import weekly_digest_lambda as m

    def pack(whoop, grades, withings):
        return {
            "day_grades": m.ex_day_grades(grades),
            "whoop": m.ex_whoop(whoop),
            "sleep": m.ex_whoop_sleep(whoop),
            "strava": m.ex_strava({}, _DIGEST_PROFILE),
            "apple": m.ex_apple_health({}),
            "macrofactor": m.ex_macrofactor({}, _DIGEST_PROFILE),
            "mf_workouts": m.ex_hevy_workouts([]),
            "withings": m.ex_withings(withings),
            "habitify": m.ex_habitify({}, _DIGEST_PROFILE),
            "todoist": m.ex_todoist({}),
            "journal": m.ex_journal({}),
        }

    this = pack(_wd_whoop_dict(_WEEK_DAYS, 62), _wd_grades_dict(_WEEK_DAYS, ["A", "A-", "B+", "B"]), _wd_withings_dict(_WEEK_DAYS, 0))
    prior = pack(_wd_whoop_dict(_WEEK_DAYS, 56), _wd_grades_dict(_WEEK_DAYS, ["B", "B+", "B-", "C+"]), _wd_withings_dict(_WEEK_DAYS, 1.8))
    data = {
        "this": this,
        "prior": prior,
        "training_load": {"atl": 42.0, "ctl": 48.0, "tsb": 6.0},
        "trends": {"day_grade": "→", "sleep": "↑", "weight": "↓"},
        "sleep_debt": {"debt_hrs": 3.2},
        "projection": {"eta": "2027-02-01", "rate_per_week": -1.2, "weeks": 40, "status": "on_track"},
        "dates": {"this_start": "2026-06-01", "this_end": "2026-06-07"},
    }
    return m.build_html(data, _DIGEST_COMMENTARY, _DIGEST_PROFILE)


def _render_monthly_digest():
    import monthly_digest_lambda as m

    def whoop_list(days, base):
        return [
            {
                "recovery_score": base + (i % 5) * 3,
                "hrv": 55 + (i % 4) * 2,
                "resting_heart_rate": 52 - (i % 3),
                "strain": 12.0 + (i % 4) * 0.5,
            }
            for i, d in enumerate(days)
        ]

    def withings_list(days, offset):
        return [{"weight_lbs": 310.0 - i * 0.2 - offset, "body_fat_pct": 31.0 - i * 0.03, "sk": f"DATE#{d}"} for i, d in enumerate(days)]

    def macro_list(days):
        return [
            {
                "total_calories_kcal": 1820 + (i % 4) * 40,
                "total_protein_g": 188 + (i % 3) * 6,
                "calorie_target": 1900,
                "protein_target_g": 185,
            }
            for i, d in enumerate(days)
        ]

    def chronicling_list(days):
        return [{"total_score": 74 + (i % 6) * 3, "group_scores": {"body": 78, "mind": 71, "craft": 69}} for i, d in enumerate(days)]

    def hevy_list(days):
        return [{"workouts": [{"title": "Push A", "total_volume_lbs": 14200 + i * 50}]} for i, d in enumerate(days[:8])]

    def strava_list(days):
        return [
            {
                "total_distance_miles": 4.0 + (i % 3),
                "total_moving_time_seconds": 2400 + (i % 3) * 300,
                "total_elevation_gain_feet": 120 + (i % 4) * 30,
                "activities": [
                    {
                        "enriched_name": "Easy Zone 2",
                        "name": "Run",
                        "sport_type": "Run",
                        "distance_miles": 4.0 + (i % 3),
                        "moving_time_seconds": 2400 + (i % 3) * 300,
                        "average_heartrate": 138 + (i % 5),
                        "max_heart_rate": 158 + (i % 5),
                    }
                ],
            }
            for i, d in enumerate(days[:10])
        ]

    def pack(base, off):
        return {
            "whoop": m.ex_whoop(whoop_list(_MONTH_DAYS, base)),
            "withings": m.ex_withings(withings_list(_MONTH_DAYS, off)),
            "strava": m.ex_strava(strava_list(_MONTH_DAYS), _DIGEST_PROFILE),
            "hevy": m.ex_hevy(hevy_list(_MONTH_DAYS)),
            "macrofactor": m.ex_macrofactor(macro_list(_MONTH_DAYS), _DIGEST_PROFILE),
            "chronicling": m.ex_chronicling(chronicling_list(_MONTH_DAYS)),
        }

    data = {
        "cur": pack(62, 0.0),
        "prior": pack(56, 1.6),
        "training_load": {"atl": 40.0, "ctl": 45.0, "tsb": 5.0},
        "profile": _DIGEST_PROFILE,
    }
    goals = {
        "weight": {
            "current_lbs": 306.0,
            "goal_lbs": 265.0,
            "lost_lbs": 25.0,
            "to_go_lbs": 41.0,
            "pct_complete": 38,
            "journey_start_weight": 331.0,
        },
        "year_pct_elapsed": 45,
    }
    windows = {"month_label": "May 2026", "prior_label": "April 2026"}
    return m.build_html(data, goals, _DIGEST_COMMENTARY, windows)


RENDERERS = {
    "nutrition_review": _render_nutrition_review,
    "weekly_plate": _render_weekly_plate,
    "monday_compass": _render_monday_compass,
    "weekly_digest": _render_weekly_digest,
    "monthly_digest": _render_monthly_digest,
}

# Strip fragments derived from the current date/run so the snapshot is stable.
_NORMALIZERS = [(re.compile(r"\b\d{4}-\d{2}-\d{2}T[\d:.+-]+"), "<TS>")]


def _normalize(html: str) -> str:
    for pat, repl in _NORMALIZERS:
        html = pat.sub(repl, html)
    return html


@pytest.mark.parametrize("name", sorted(RENDERERS))
def test_email_render_golden(name):
    html = _normalize(RENDERERS[name]())
    # Structural floor — must hold regardless of golden churn.
    assert len(html) > 1000, f"{name} rendered suspiciously small"
    for leak in ("None", "{ai_content}", "{summary_table}", "[object", "undefined"):
        assert leak not in html, f"{name}: template/None leakage: {leak!r}"

    golden = GOLDEN_DIR / f"{name}.html"
    if os.environ.get("GOLDEN_UPDATE") or not golden.exists():
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(html)
        if not os.environ.get("GOLDEN_UPDATE"):
            raise AssertionError(f"{name}: golden created — commit it and re-run")
        return
    assert html == golden.read_text(), (
        f"{name} email HTML changed vs golden. If intentional: "
        f"GOLDEN_UPDATE=1 python3 -m pytest tests/test_email_render_goldens.py — then review the diff."
    )
