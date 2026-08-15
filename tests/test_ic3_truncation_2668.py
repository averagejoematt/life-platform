"""#2668 — a truncated IC-3 response is a failure, not an empty result.

The daily brief's IC-3 chain-of-thought pass ran with `max_tokens=600` while the
model wanted well over that. MEASURED from the `daily-brief` log group — 13
consecutive failures, every one `Unterminated string`, i.e. cut mid-value:

    08-04 char 1986   08-07 char 2103   08-10 char 2123
    08-05 char 2083   08-08 char 2277   08-11 char 2168
    08-06 char 2270   08-09 char 2041   08-12 char 2085

The parse then raised, was caught, logged at **WARN**, and returned `None`. The
function's `Errors` metric stayed at **0.0**. Downstream, `_format_analysis(None)`
returns `""`, so Pass 2 silently loses its entire analysis block — the brief ships
looking healthy with the reasoning pass dead inside it. Ten of twelve days.

Note the code comment already recorded a 200 → 600 bump for this SAME class in
2026-05. A cap chosen as "the next round number" rots the moment the prompt grows;
this one is sized against the observed ceiling, and this test pins the two things
that let it rot silently — the WARN and the missing metric.
"""

from __future__ import annotations

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402
from ai import ai_calls  # noqa: E402

# A real IC-3 payload cut mid-string, exactly as the model returns it at the cap.
TRUNCATED = (
    '{"key_patterns": ["sleep debt accumulated across four nights", '
    '"protein intake fell on the two lowest-recovery days"], '
    '"likely_connection": "lower protein correlates with lower next-day recovery — '
    'a pattern, not proven causation", "challenge": "This could be con'
)

WELL_FORMED = '{"key_patterns": ["a"], "likely_connection": "b", "challenge": "c", ' '"priority": "d", "tone": "support"}'


@pytest.fixture
def captured(monkeypatch):
    """Capture the metric emissions and the printed lines."""
    seen = {"metrics": [], "lines": []}
    monkeypatch.setattr(ai_calls, "_emit_failure_metric", lambda name="AnthropicAPIFailure": seen["metrics"].append(name))
    monkeypatch.setattr("builtins.print", lambda *a, **k: seen["lines"].append(" ".join(str(x) for x in a)))
    return seen


def _run(monkeypatch, response: str):
    monkeypatch.setattr(ai_calls, "call_anthropic", lambda *a, **k: response)
    return ai_calls._run_analysis_pass({"sleep": 60}, "", "", "FAKE-KEY")


def test_a_truncated_response_returns_none_not_a_partial_dict(monkeypatch, captured):
    """It must not be salvaged into a half-object that reads as real analysis."""
    assert _run(monkeypatch, TRUNCATED) is None


def test_a_truncated_response_emits_its_own_failure_metric(monkeypatch, captured):
    """The signal an alarm can key on. Its absence is why this ran dead for 10 of
    12 days with the function's Errors metric flat at 0.0."""
    _run(monkeypatch, TRUNCATED)
    assert captured["metrics"] == ["IC3AnalysisFailure"], captured["metrics"]


def test_the_failure_is_logged_at_error_not_warn(monkeypatch, captured):
    """WARN is what let this hide. A log scan for [ERROR] must surface it."""
    _run(monkeypatch, TRUNCATED)
    joined = " ".join(captured["lines"])
    assert "[ERROR] IC-3 analysis pass failed" in joined, captured["lines"]
    assert "[WARN] IC-3" not in joined, captured["lines"]


def test_the_ic3_failure_does_not_pollute_the_api_failure_slo(monkeypatch, captured):
    """`slo-ai-coaching-success` keys on AnthropicAPIFailure. The IC-3 call returned
    200 — it is a response-shape failure, not an API failure — so folding it in
    there would corrupt the metric that alarm depends on."""
    _run(monkeypatch, TRUNCATED)
    assert "AnthropicAPIFailure" not in captured["metrics"], captured["metrics"]


def test_a_well_formed_response_still_parses_and_emits_nothing(monkeypatch, captured):
    """The control. Without it, 'fail on everything' would satisfy the tests above."""
    out = _run(monkeypatch, WELL_FORMED)
    assert out == {
        "key_patterns": ["a"],
        "likely_connection": "b",
        "challenge": "c",
        "priority": "d",
        "tone": "support",
    }
    assert captured["metrics"] == []


def test_the_token_cap_clears_the_measured_truncation_ceiling():
    """Pins the SIZING, not just the error handling — the 2026-05 bump to 600 was
    also 'ample headroom' at the time and rotted. 1 token ≈ 4 chars, and the longest
    observed cut was 2277 chars, so the cap must buy comfortably more than that."""
    import inspect

    src = inspect.getsource(ai_calls._run_analysis_pass)
    import re

    m = re.search(r"max_tokens=(\d+)", src)
    assert m, "max_tokens literal not found in _run_analysis_pass"
    cap = int(m.group(1))
    assert cap * 4 > 2277 * 2, f"max_tokens={cap} leaves under 2x the longest measured truncation (2277 chars)"
