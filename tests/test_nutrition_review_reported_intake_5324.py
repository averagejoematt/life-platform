"""#5324 — the Nutrition Review truncated at 4096 tokens and was BLOCKED on reported intake figures.

2026-10-24T17:01Z: the edition hit max_tokens=4096, then AI-3 Check 5 blocked it on two identical
small figures that were the subject's LOGGED intake for a past day, reported back. The text was
never stored and the repo is public, so the fixture is built from the shape (a reported-intake
sentence in a coach card) with a synthetic figure, not a real one.
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
os.environ.setdefault("AI_VALIDATOR_AUTOLOAD", "off")

from ai.ai_output_validator import AIOutputType, validate_ai_output  # noqa: E402

_CARD = '<div style="border-left:3px solid #10b981"><p>{}</p></div>'


def _check(sentence):
    return validate_ai_output(_CARD.format(sentence), AIOutputType.NUTRITION_COACH, max_length=40_000)


@pytest.mark.parametrize(
    "sentence",
    [
        "On Sunday you logged 612 kcal, well short of the plan, and protein was the miss.",
        "Sunday intake was 612 kcal; that is a reporting gap worth a look. Daily totals matter here.",
        "Your logged 612 kcal on one day sits far under the week's average of the other six days.",
        "He actually ate 612 calories that day and 612 kcal was the lowest logged day.",
    ],
)
def test_reported_logged_intake_is_not_a_prescription(sentence):
    assert not _check(sentence).blocked


@pytest.mark.parametrize(
    "sentence",
    [
        "Eat only 612 kcal a day to speed this up.",
        "You should aim for 612 kcal tomorrow.",
        "Cut to 612 kcal per day, daily, starting Monday.",
        "Stay under 612 kcal. You logged a lot last week, so no more than 612 cal.",
        "Eat 612 kcal a day.",
    ],
)
def test_prescriptions_still_block(sentence):
    assert _check(sentence).blocked


def test_output_cap_clears_the_prompt_and_timeout_covers_it():
    from emails import nutrition_review_lambda as m

    assert m.MAX_OUTPUT_TOKENS >= 8192
    assert m.CALL_TIMEOUT_SECONDS * 87 >= m.MAX_OUTPUT_TOKENS  # slowest observed tok/s
    assert m.CALL_TIMEOUT_SECONDS < 300  # the Lambda's timeout
