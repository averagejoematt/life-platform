"""Tests for the HRV wrong-unit guard in ai_output_validator (Check 13)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import ai_output_validator as v  # noqa: E402

_LONG = " and the recovery trend held steady through the week with no concerning signals at all."


def _warns(text):
    r = v.validate_ai_output(text + _LONG, v.AIOutputType.CHRONICLE, min_length=10)
    return [w for w in r.warnings if "HRV" in w and "bpm" in w]


def test_hrv_in_bpm_warns():
    assert _warns("HRV improved to 44.7 bpm this week")
    assert _warns("HRV was 40.2 bpm")


def test_hrv_in_ms_is_clean():
    assert not _warns("HRV improved to 44.7 ms this week")
    assert not _warns("HRV held at 51 ms")


def test_resting_hr_in_bpm_is_fine():
    # bpm IS correct for heart rate — must not false-positive off a nearby HRV mention.
    assert not _warns("Resting heart rate was 58 bpm")
