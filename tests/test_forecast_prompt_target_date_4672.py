"""tests/test_forecast_prompt_target_date_4672.py — the coach prompt's forecast line names
the day the forecast is for (#4672).

A coach handed "recovery_pct tomorrow: the model expects 52.9%" on 2026-09-11 wrote
"52.9% tomorrow (2026-09-10)" — the day was invented, because the line never carried the
row's `target_date`. The #4618 grader then read the call as a statement about a day already
past. The fixture is the shape of a live `SOURCE#forecast` summary item, read 2026-10-09.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from ai.forecast_prompt import forecast_prompt_lines  # noqa: E402

# The live item's keys and types, as boto3's resource layer returns them (numbers as Decimal).
LIVE_ITEM = {
    "target_date": "2026-10-10",
    "point": Decimal("78.6"),
    "horizon_days": Decimal("1"),
    "lo": Decimal("55.9"),
    "frame": "tomorrow",
    "unit": "%",
    "metric": "recovery_pct",
    "hi": Decimal("100"),
}


def test_the_line_names_the_day_the_forecast_is_for():
    assert forecast_prompt_lines([LIVE_ITEM]) == ["  - recovery_pct tomorrow (2026-10-10): the model expects 78.6% (80% interval 55.9-100)"]


def test_MUST_FAIL_without_the_day_a_coach_has_to_invent_one():
    # The pre-#4672 line had no date in it at all; this is the regression the test exists for.
    line = forecast_prompt_lines([LIVE_ITEM])[0]
    assert "2026-10-10" in line


def test_an_item_with_no_target_date_still_prints_without_inventing_one():
    item = {k: v for k, v in LIVE_ITEM.items() if k != "target_date"}
    assert forecast_prompt_lines([item]) == ["  - recovery_pct tomorrow: the model expects 78.6% (80% interval 55.9-100)"]


def test_an_item_missing_a_number_is_left_out_as_before():
    assert forecast_prompt_lines([{**LIVE_ITEM, "hi": None}]) == []
    assert forecast_prompt_lines([{**LIVE_ITEM, "lo": True}]) == [], "a boolean is not a number"
    assert forecast_prompt_lines(None) == []
