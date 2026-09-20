"""tests/test_week_close_day_3761.py — the ONE week-close derivation (#3761).

Two callers need "when does this experiment week end": the weekly recap card
(`recap_card_lambda.py`, is *today* the close day?) and the progress-photo
protocol (`progress_capture.expected_capture_day`, what date IS the close day
for a photo taken any day this week?). Before this issue each answered the
question with its own inline `day_n % 7 == 0` arithmetic — fine until the next
experiment reset moves genesis to a different weekday, at which point a
hand-written weekday literal anywhere in that arithmetic would be silently
wrong. `pacific_time.week_close_day()` is now the one place either of them may
compute it.

This file pins three things:
  1. `week_close_day` itself, including the pre-genesis and mutation-control cases.
  2. That it reproduces the recap card's PRE-#3761 formula (`day_n and day_n % 7 == 0`)
     on the dates the card actually renders on, so the swap in `recap_card_lambda.py`
     changed no behavior.
  3. `progress_capture.expected_capture_day` / the Telegram reply's days-off phrase,
     built on top of the same derivation.
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from coach import progress_capture as pc  # noqa: E402
from common.pacific_time import pacific_day_n, week_close_day  # noqa: E402

GENESIS = "2026-09-06"  # cycle 17, a Sunday — day 7 lands on a Saturday


# ══════════════════════════════════════════════════════════════════════════════
# 1. week_close_day itself
# ══════════════════════════════════════════════════════════════════════════════
def test_genesis_day_closes_on_day_seven():
    """Day 1 (genesis itself) is in the week that closes on day 7."""
    assert week_close_day(GENESIS, GENESIS) == "2026-09-12"


def test_day_seven_is_its_own_close_day():
    assert week_close_day("2026-09-12", GENESIS) == "2026-09-12"


def test_day_eight_closes_on_day_fourteen():
    """Day 8 is the first day of week 2 — its close is a full week later."""
    assert week_close_day("2026-09-13", GENESIS) == "2026-09-19"


def test_a_date_before_genesis_has_no_close_day():
    """pacific_day_n clamps pre-genesis dates to 0 — a week has no close before day 1."""
    assert week_close_day("2026-08-01", GENESIS) is None


def test_an_unparseable_date_has_no_close_day():
    assert week_close_day("not-a-date", GENESIS) is None


def test_mutation_control_a_weekday_literal_would_diverge_on_a_tuesday_genesis():
    """The defect this guards against, made concrete.

    A synthetic genesis chosen to fall on a WEEKDAY OTHER than cycle 17's Sunday: if
    `week_close_day` (or any caller) hardcoded "Saturday"/"Sunday" instead of deriving
    from `day_n % 7`, this synthetic genesis would expose it immediately, because its
    close day is not a weekend day at all.
    """
    import datetime

    tuesday_genesis = "2026-09-01"
    assert datetime.date.fromisoformat(tuesday_genesis).strftime("%A") == "Tuesday"
    close = week_close_day(tuesday_genesis, tuesday_genesis)
    # Day 1 (Tue 09-01) + 6 days = day 7 = Mon 09-07 — NOT a Saturday or a Sunday, which
    # is exactly what a weekday-literal implementation would have hardcoded.
    assert close == "2026-09-07"
    assert datetime.date.fromisoformat(close).strftime("%A") == "Monday"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Equality with the recap card's pre-#3761 inline formula
# ══════════════════════════════════════════════════════════════════════════════
def _old_formula(date: str, genesis: str) -> bool:
    """The exact expression `recap_card_lambda.py` used before this issue."""
    day_n = pacific_day_n(genesis, date)
    return bool(day_n and day_n % 7 == 0)


def _new_formula(date: str, genesis: str) -> bool:
    """What it reads as after #3761's swap."""
    day_n = pacific_day_n(genesis, date)
    return bool(day_n and week_close_day(date, genesis) == date)


def test_new_formula_matches_old_on_genesis_day_and_close_day_and_a_mid_week_day():
    for date in (GENESIS, "2026-09-12", "2026-09-14"):
        assert _new_formula(date, GENESIS) == _old_formula(date, GENESIS), date
    # And the boundary values themselves, spelled out:
    assert _old_formula(GENESIS, GENESIS) is False  # day 1, not a close day
    assert _old_formula("2026-09-12", GENESIS) is True  # day 7, IS the close day
    assert _old_formula("2026-09-14", GENESIS) is False  # day 9, mid-week-2


# ══════════════════════════════════════════════════════════════════════════════
# 3. progress_capture.expected_capture_day + the days-off phrase
# ══════════════════════════════════════════════════════════════════════════════
def test_expected_capture_day_is_the_week_close_for_that_date():
    assert pc.expected_capture_day("2026-09-14", GENESIS) == "2026-09-19"
    assert pc.expected_capture_day("2026-09-19", GENESIS) == "2026-09-19"


def test_expected_capture_day_off_cycle_is_none():
    assert pc.expected_capture_day("2026-08-01", GENESIS) is None
    assert pc.expected_capture_day("2026-09-14", "") is None


def test_offset_phrase_on_the_protocol_day():
    assert pc._protocol_offset_phrase("2026-09-19", GENESIS) == "on the protocol day"


def test_offset_phrase_names_the_day_count():
    # 2026-09-14 is 5 days before its week's close (2026-09-19).
    assert pc._protocol_offset_phrase("2026-09-14", GENESIS) == "5 days off the protocol day"
    # Singular day.
    assert pc._protocol_offset_phrase("2026-09-18", GENESIS) == "1 day off the protocol day"


def test_offset_phrase_empty_off_cycle():
    assert pc._protocol_offset_phrase("2026-08-01", GENESIS) == ""
