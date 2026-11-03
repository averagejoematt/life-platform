"""#5615 (owner integrity items 5 and 6, 2026-11-02): the blended forecasting score is never the coaches' accuracy, and
the coaches' calibration is shown only to the resolution the data supports.

* The base-rate sentence on /api/predictions and the ledger record carries the skill verdict the edition already
  uses; it said "too few calls are checked to make it yet" at any N (211 checked calls on 2026-11-03).
* Start labels the coaches' record as the cycle it counts, never "this week".
* /method/calibration/ leads each card with the coaches' own stratum, names the platform card as a blend that is not
  the coaches' record, and never prints a calibration label for a coach whose every call carries one stated confidence.
"""

from __future__ import annotations

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lambdas"))

from web import site_api_coach_ledger as L  # noqa: E402


def _rows(right: int, wrong: int, conf: float = 0.5) -> list[dict]:
    return [{"status": "confirmed", "confidence": conf}] * right + [{"status": "refuted", "confidence": conf}] * wrong


def test_the_base_rate_sentence_carries_the_skill_verdict():
    text = L._record_extras(_rows(83, 128), 83, 211)["baseline"]["text"]
    assert "too few calls are checked" not in text
    assert text == "A guess that every call has a 39% chance of coming true does about as well."


def test_the_sentence_says_too_few_only_when_no_skill_can_be_computed():
    assert L._beats_simple_guess([]) is None


def _read(*parts: str) -> str:
    return open(os.path.join(REPO, *parts), encoding="utf-8").read()


def test_start_never_calls_the_cycle_record_this_week():
    src = _read("www", "src", "pages", "index.astro")
    assert "The coaches, this week" not in src
    assert "The coaches' record" in src


def test_the_calibration_page_names_the_blend_and_withholds_one_confidence_labels():
    js = _read("site", "assets", "js", "evidence_intelligence.js")
    assert "the coaches' record" in js and "<em>not</em> the coaches' record" in js
    assert "strata.coaches" in js, "each card leads with the coaches' own stratum"
    assert "one stated confidence — not measurable" in js
    assert '"Reliability curve — this season' not in js, "the pooled table is not presented as the coaches' curve"
