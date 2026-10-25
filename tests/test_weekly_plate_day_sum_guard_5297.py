"""tests/test_weekly_plate_day_sum_guard_5297.py — the per-day meal-sum guard (#5297 follow-up).

#5299 exempted labelled meal/snack figures from the low-calorie check; the accepted trade-off was that
a day of small labelled meals could SUM under the floor and pass. The guard sums per day heading and
blocks under the charter's planned minimum x margin. Fallback when grouping fails: pass with a recorded
warning (the real edition is cards, not a day plan; blocking it re-opens the 5-edition false block).
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
os.environ.setdefault("AI_VALIDATOR_AUTOLOAD", "off")

from ai import ai_output_validator as v  # noqa: E402
from ai.ai_output_validator import AIOutputType, validate_ai_output  # noqa: E402
from training import training_charter as tc  # noqa: E402

FIXTURE = _REPO / "tests" / "fixtures" / "weekly_plate_5297" / "blocked_edition_shape_2026-10-24.html"


@pytest.fixture(autouse=True)
def _offline_charter(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def _day(name, figures):
    labels = ["Breakfast", "Lunch", "Snack", "Dinner", "Snack"]
    rows = "".join(f"<p>{labels[i % 5]} — {f} cal · 20g P</p>" for i, f in enumerate(figures))
    return f"<h3>{name}</h3>{rows}"


def _minimum():
    return tc.public_view()["nutrition"]["calories"]["planned_minimum_any_weight_kcal"]


def test_a_day_whose_meals_sum_under_the_floor_is_blocked_naming_day_and_total():
    html = _day("Monday", [150, 180, 220, 300])  # 850 total
    r = validate_ai_output(html, AIOutputType.NUTRITION_COACH, {})
    assert r.blocked
    assert "Monday" in r.block_reason and "850" in r.block_reason
    assert r.day_sums["Monday"]["total_kcal"] == 850 and r.day_sums["Monday"]["blocked"] is True
    assert f"{_minimum():,} kcal/day" in r.safe_fallback


def test_a_day_whose_meals_sum_above_the_floor_passes_and_is_recorded():
    html = _day("Monday", [400, 450, 150, 500]) + _day("Tuesday", [350, 450, 200, 450])
    r = validate_ai_output(html, AIOutputType.NUTRITION_COACH, {})
    assert not r.blocked, r.block_reason
    assert r.day_sums["Monday"]["total_kcal"] == 1500 and r.day_sums["Monday"]["judged"] is True


def test_the_second_day_is_judged_on_its_own_total():
    html = _day("Monday", [400, 450, 150, 500]) + _day("Tuesday", [150, 180, 120, 200])
    r = validate_ai_output(html, AIOutputType.NUTRITION_COACH, {})
    assert r.blocked and "Tuesday" in r.block_reason and "650" in r.block_reason


def test_the_margin_is_applied_to_the_charter_value(monkeypatch):
    floor = int(_minimum() * v._DAY_SUM_MARGIN)
    just_under, just_over = floor - 1, floor + 1
    for total, blocked in ((just_under, True), (just_over, False)):
        html = _day("Friday", [total - 400, 150, 250])  # 3 meals
        assert validate_ai_output(html, AIOutputType.NUTRITION_COACH, {}).blocked is blocked, total


def test_missing_day_headings_pass_with_a_recorded_warning_never_silently():
    html = "<p>Snack — 150 cal</p><p>Lunch — 180 cal</p><p>Dinner — 220 cal</p><p>Snack — 120 cal</p>"
    r = validate_ai_output(html, AIOutputType.NUTRITION_COACH, {})
    assert not r.blocked
    assert any("no day heading" in w for w in r.warnings)
    assert r.day_sums == {"_ungrouped": {"judged": False}}


def test_the_real_edition_shape_still_passes_and_records_the_ungrouped_warning():
    r = validate_ai_output(FIXTURE.read_text(), AIOutputType.NUTRITION_COACH, {})
    assert not r.blocked, r.block_reason
    assert any("day-sum guard" in w for w in r.warnings)


def test_a_partial_day_is_recorded_not_judged():
    r = validate_ai_output(_day("Monday", [465]), AIOutputType.NUTRITION_COACH, {})
    assert not r.blocked
    assert r.day_sums["Monday"]["judged"] is False
    assert any("partial day" in w for w in r.warnings)


def test_an_unreadable_charter_records_that_the_day_was_not_judged(monkeypatch):
    monkeypatch.setattr(tc, "public_view", lambda: {})
    r = validate_ai_output(_day("Monday", [150, 180, 220, 300]), AIOutputType.NUTRITION_COACH, {})
    assert not r.blocked
    assert any("charter minimum unreadable" in w for w in r.warnings)


def test_a_labelled_figure_outside_a_day_is_still_exempt():
    r = validate_ai_output("<p>Snack — 150 cal · 25g P</p>", AIOutputType.NUTRITION_COACH, {})
    assert not r.blocked
    assert any("no day heading" in w for w in r.warnings)


def test_other_output_types_are_untouched():
    r = validate_ai_output(_day("Monday", [150, 180, 220, 300]), AIOutputType.CHRONICLE, {})
    assert not r.blocked and r.day_sums == {}


def test_the_validator_stays_free_of_a_kcal_literal_for_the_floor():
    src = (_REPO / "lambdas" / "ai" / "ai_output_validator.py").read_text()
    assert "1,200" not in src and "1200" not in src


def test_the_qa_record_carries_the_verdict_for_the_stored_edition():
    sys.path.insert(0, str(_REPO / "lambdas" / "emails"))
    os.environ.setdefault("EMAIL_RECIPIENT", "reader@example.invalid")
    os.environ.setdefault("EMAIL_SENDER", "plate@example.invalid")
    os.environ.setdefault("S3_BUCKET", "test-bucket")
    import importlib

    try:
        wp = importlib.import_module("emails.weekly_plate_lambda")
    except Exception:
        wp = importlib.import_module("weekly_plate_lambda")
    blocked = wp.plate_qa_record(validate_ai_output(_day("Monday", [150, 180, 220, 300]), AIOutputType.NUTRITION_COACH, {}))
    assert blocked["validator"] == "blocked" and "Monday" in blocked["blocked_reason"]
    assert blocked["day_sums"]["Monday"] == {
        "total_kcal": 850,
        "meals": 4,
        "judged": True,
        "floor_kcal": int(_minimum() * 0.9),
        "blocked": True,
    }
    ok = wp.plate_qa_record(validate_ai_output(_day("Monday", [400, 450, 150, 500]), AIOutputType.NUTRITION_COACH, {}))
    assert ok["validator"] == "passed" and ok["blocked_reason"] == ""
