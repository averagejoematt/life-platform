"""tests/test_chronicle_card_fit_6193.py — the chronicle share card's stats values stay inside the card (#6193).

Week 10's card ran "292.6 lbs (-5.2 this week)" past its column and off the right edge. Each value now steps its size
down until it fits its column; the words are never cut. Synthetic values."""

import os
import sys

import pytest

pytest.importorskip("PIL")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from web import card_engine  # noqa: E402


def _ink_right_edge(img, y0, y1):
    """The rightmost column, in rows y0..y1, that is not the card's background."""
    bg = img.getpixel((img.width - 2, y0))
    for x in range(img.width - 1, -1, -1):
        if any(img.getpixel((x, y)) != bg for y in range(y0, y1, 2)):
            return x
    return -1


def test_a_long_stats_value_stays_inside_the_card():
    long = "Weight: 292.6 lbs (-5.2 this week) on the synthetic Monday weigh-in, a long single value for a test"
    img = card_engine.render("chronicle", {"title": "A Title", "label": "Week 1", "stats_line": long, "date": "2026-11-10"})
    assert _ink_right_edge(img, 400, 470) < img.width - card_engine.MARGIN  # inside the right margin


def test_the_card_is_redrawn_once_with_the_new_template():
    src = open(os.path.join(ROOT, "lambdas", "web", "og_moments.py"), encoding="utf-8").read()
    assert '"chronicle-card/2"' in src  # the plan digest carries the template version
