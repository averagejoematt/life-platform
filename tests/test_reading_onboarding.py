"""tests/test_reading_onboarding.py — taste-archaeology synthesis (calibration §8).

Bedrock faked. Asserts the question bank, answer formatting, domain validation,
the always-low confidence, and fail-soft.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

from reading import reading_onboarding as ob  # noqa: E402


def _resp(payload):
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


def test_question_bank_present():
    assert len(ob.QUESTION_BANK) >= 6
    assert all("?" in q for q in ob.QUESTION_BANK)


def test_synthesis_happy_path():
    def caller(_b):
        return _resp(
            {
                "affinities": ["quiet interiority", "ordinary lives made luminous"],
                "aversions": ["dense jargon", "self-help"],
                "starting_domains": ["Fiction", "Memoir", "not-a-domain"],
                "on_ramp_note": "Start with a propulsive novel he can finish in a week.",
                "confidence": "low",
                "rationale": "He named a film about an ordinary life that wrecked him.",
            }
        )

    out = ob.synthesize_taste({"What film wrecked you?": "Stoner-esque drama"}, caller=caller)
    assert out["synthesized"] is True
    assert out["confidence"] == "low"  # always low
    assert out["starting_domains"] == ["fiction", "memoir"]  # invalid domain dropped, lowercased
    assert "self-help" in out["aversions"]
    assert out["on_ramp_note"]


def test_accepts_list_of_qa():
    def caller(_b):
        return _resp({"affinities": ["x"], "aversions": [], "starting_domains": ["fiction"], "on_ramp_note": "n", "rationale": "r"})

    out = ob.synthesize_taste([{"question": "Q1", "answer": "A1"}, {"question": "Q2", "answer": "A2"}], caller=caller)
    assert out["synthesized"] is True


def test_no_answers_is_empty():
    out = ob.synthesize_taste({}, caller=lambda b: _resp({}))
    assert out["synthesized"] is False and out["error"] == "no answers"


def test_fail_soft_on_exception():
    def caller(_b):
        raise RuntimeError("bedrock down")

    out = ob.synthesize_taste({"q": "a"}, caller=caller)
    assert out["synthesized"] is False and out["error"] == "RuntimeError"
    assert out["confidence"] == "low"


def test_fail_soft_on_bad_json():
    out = ob.synthesize_taste({"q": "a"}, caller=lambda b: {"content": [{"type": "text", "text": "nope"}]})
    assert out["synthesized"] is False
