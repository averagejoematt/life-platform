"""tests/test_panel_body_number_one_detector_4993.py — the Panel renderer and the story desk read ONE body-number detector.

PR #5014 fixed the desk's regex so "2.64 pounds per week" (a pace) is not a weigh-in; the Panel kept a twin that still
held the same line at render. Both now read ``content.body_numbers.BODY_NUM_RE``. The safety class is unchanged: every
spoken weigh-in figure still holds.

Run:  python3 -m pytest tests/test_panel_body_number_one_detector_4993.py -v
"""

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "emails"))

from content import body_numbers, story_writers  # noqa: E402
from emails import coach_panel_podcast_lambda as panel  # noqa: E402


@pytest.fixture(autouse=True)
def _no_vice_terms(monkeypatch):
    monkeypatch.setattr(panel, "_blocked_vice_terms", lambda: [])


def test_panel_and_desk_share_one_object():
    assert story_writers._BODY_NUM_RE is body_numbers.BODY_NUM_RE
    assert not hasattr(panel, "_BODY_NUM_RE"), "a local copy of the detector is back in the Panel lambda"
    assert panel.body_numbers.BODY_NUM_RE is body_numbers.BODY_NUM_RE


@pytest.mark.parametrize(
    "line",
    [
        "the pace this window is 2.64 pounds per week, which is steady.",
        "he is losing 1.5 lbs/week on average",
        "about 2 pounds a week",
    ],
)
def test_panel_clears_rate_shapes(line):
    assert "body-number" not in panel._safety_gate(line)


@pytest.mark.parametrize(
    "line", ["he weighed 318.9 pounds that morning", "down to 46 pounds", "a 199.8 pounds reading", "312 lbs", "145 kg"]
)
def test_panel_still_holds_weigh_ins(line):
    assert "body-number" in panel._safety_gate(line)
