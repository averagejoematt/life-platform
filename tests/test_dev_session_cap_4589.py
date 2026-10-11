"""tests/test_dev_session_cap_4589.py — the spend cap on laptop AI calls (#4589).

What is held: a dev session outside a Lambda container is refused BEFORE a send once it
has spent its per-run or its trailing-day limit; a Lambda container, CI, the remediation
agent and the scheduled platform are never refused by it; an explicit dollar override is
the only way past the default; a failed day read leaves the per-run limit in force; the
refusal is a budget stop, so the retry policy does not back off against it.

The cap is off under pytest unless a test opts in (`DEV_AI_CAP_UNDER_TEST`), so every
integration test here sets that and clears the CI markers the suite runs under.

Run:  python3 -m pytest tests/test_dev_session_cap_4589.py -v
"""

from __future__ import annotations

import io
import json
import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from ai import (  # noqa: E402
    bedrock_client as bc,  # noqa: E402
    budget_guard,
    dev_session_cap as cap,
)

LAPTOP = {}
# One Sonnet call of 1M input tokens is $3.00 at the listed price.
ONE_CALL_USAGE = {"input_tokens": 1_000_000, "output_tokens": 0}
SONNET = "us.anthropic.claude-sonnet-4-6"


# ── the pure parts ───────────────────────────────────────────────────────────
def test_the_cap_applies_only_to_a_dev_session_outside_a_lambda_container():
    assert cap.applies("dev-session", LAPTOP)
    assert not cap.applies(
        "dev-session", {"AWS_LAMBDA_FUNCTION_NAME": "life-platform-mcp"}
    ), "the MCP Lambda declares a dev context and is production traffic"
    for other in ("prod-cron", "ci", "remediation"):
        assert not cap.applies(other, LAPTOP), other


def test_the_cap_is_off_under_pytest_unless_a_test_opts_in():
    assert not cap.applies("dev-session", {"PYTEST_CURRENT_TEST": "x"})
    assert cap.applies("dev-session", {"PYTEST_CURRENT_TEST": "x", "DEV_AI_CAP_UNDER_TEST": "1"})


def test_decide_refuses_at_the_run_limit_and_at_the_day_limit():
    assert cap.decide(0.0, 0.0, None) is None
    assert cap.decide(cap.PER_RUN_USD - 0.01, 0.0, None) is None
    assert "per-run limit is $5.00" in cap.decide(cap.PER_RUN_USD, 0.0, None)
    assert cap.decide(1.0, cap.PER_DAY_USD - 1.01, None) is None
    said = cap.decide(1.0, cap.PER_DAY_USD - 1.0, None)
    assert "in the last 24 hours" in said and "the limit is $10.00" in said


def test_an_override_is_this_runs_cap_and_replaces_the_day_check():
    assert cap.decide(30.0, 500.0, 40.0) is None, "a named number is consent for this run"
    assert "set by DEV_AI_BUDGET_USD" in cap.decide(40.0, 0.0, 40.0)


@pytest.mark.parametrize("raw, expected", [("40", 40.0), (" 7.5 ", 7.5), ("", None), ("0", None), ("-3", None), ("lots", None)])
def test_an_override_must_be_a_positive_number_or_the_default_applies(raw, expected):
    assert cap.run_override({cap.OVERRIDE_ENV: raw}) == expected


def test_the_day_read_sums_the_trailing_window_of_the_dev_session_series():
    cw = MagicMock()
    cw.get_metric_statistics.return_value = {"Datapoints": [{"Sum": 2.5}, {"Sum": 4.0}, {"Sum": None}]}
    now = datetime(2026, 10, 2, 3, 0, tzinfo=timezone.utc)
    assert cap.read_day_spend(cw, now) == 6.5
    kwargs = cw.get_metric_statistics.call_args.kwargs
    assert kwargs["Dimensions"] == [{"Name": "CallerClass", "Value": "dev-session"}]
    assert (
        kwargs["EndTime"] - kwargs["StartTime"]
    ).total_seconds() == cap.DAY_WINDOW_HOURS * 3600, "a trailing window, so a spike across midnight UTC is one day"


# ── through the chokepoint ───────────────────────────────────────────────────
@pytest.fixture
def laptop(monkeypatch):
    """A laptop dev session with the cap live, a fake Bedrock that bills $3 a call, and a
    fake CloudWatch whose trailing-day figure the test sets."""
    for var in ("AWS_LAMBDA_FUNCTION_NAME", "GITHUB_ACTIONS", "CI", "INVOCATION_CONTEXT", "BEDROCK_SHADOW_MODE", cap.OVERRIDE_ENV):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DEV_AI_CAP_UNDER_TEST", "1")
    cap._reset_for_tests()
    bedrock = MagicMock()
    bedrock.invoke_model.side_effect = lambda **_k: {
        "body": io.BytesIO(
            json.dumps({"content": [{"type": "text", "text": "ok"}], "usage": ONE_CALL_USAGE, "stop_reason": "end_turn"}).encode()
        )
    }
    cloudwatch = MagicMock()
    cloudwatch.get_metric_statistics.return_value = {"Datapoints": []}
    monkeypatch.setattr(bc, "_client", lambda: bedrock)
    monkeypatch.setattr(bc, "_cw", lambda: cloudwatch)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    assert bc.caller_class() == "dev-session"
    yield type("Laptop", (), {"bedrock": bedrock, "cloudwatch": cloudwatch})
    cap._reset_for_tests()


def _call():
    return bc.invoke({"messages": [{"role": "user", "content": "x"}], "max_tokens": 8}, model_name=SONNET)


def test_a_run_is_refused_before_the_send_once_it_has_spent_its_limit(laptop, capsys):
    _call()  # $3
    _call()  # $6 — past the limit only after this one is billed
    with pytest.raises(cap.DevSessionBudgetExceeded) as stop:
        _call()
    assert laptop.bedrock.invoke_model.call_count == 2, "the refused call was never sent"
    assert "per-run limit is $5.00" in str(stop.value) and cap.OVERRIDE_ENV in str(stop.value)
    with pytest.raises(cap.DevSessionBudgetExceeded):
        _call()
    assert capsys.readouterr().err.count("[dev-session cap] AI call refused") == 1, "said once, loudly, not once per call"


def test_spend_from_earlier_runs_today_counts_against_the_day_limit(laptop):
    laptop.cloudwatch.get_metric_statistics.return_value = {"Datapoints": [{"Sum": 8.0}]}
    _call()  # day: 8 + 3 = 11
    with pytest.raises(cap.DevSessionBudgetExceeded) as stop:
        _call()
    assert "in the last 24 hours" in str(stop.value)
    assert laptop.bedrock.invoke_model.call_count == 1
    assert laptop.cloudwatch.get_metric_statistics.call_count == 1, "the day is read once per run"


def test_a_day_already_over_its_limit_refuses_the_first_call(laptop):
    laptop.cloudwatch.get_metric_statistics.return_value = {"Datapoints": [{"Sum": 12.0}]}
    with pytest.raises(cap.DevSessionBudgetExceeded):
        _call()
    assert laptop.bedrock.invoke_model.call_count == 0


def test_a_named_number_lets_the_run_go_that_far_and_no_further(laptop, monkeypatch):
    laptop.cloudwatch.get_metric_statistics.return_value = {"Datapoints": [{"Sum": 50.0}]}
    monkeypatch.setenv(cap.OVERRIDE_ENV, "9")
    for _ in range(3):  # $9
        _call()
    with pytest.raises(cap.DevSessionBudgetExceeded) as stop:
        _call()
    assert "set by DEV_AI_BUDGET_USD" in str(stop.value)
    assert laptop.bedrock.invoke_model.call_count == 3


def test_a_failed_day_read_leaves_the_run_limit_in_force(laptop, capsys):
    laptop.cloudwatch.get_metric_statistics.side_effect = RuntimeError("no credentials")
    _call()
    _call()
    with pytest.raises(cap.DevSessionBudgetExceeded):
        _call()
    assert "only the $5.00 per-run limit applies" in capsys.readouterr().err


def test_a_lambda_container_is_never_refused_even_when_it_declares_a_dev_context(laptop, monkeypatch):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "life-platform-mcp")
    monkeypatch.setenv("INVOCATION_CONTEXT", "dev")
    assert bc.caller_class() == "dev-session"
    for _ in range(6):  # $18
        _call()
    assert laptop.bedrock.invoke_model.call_count == 6
    assert laptop.cloudwatch.get_metric_statistics.call_count == 0


def test_ci_is_never_refused(laptop, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    for _ in range(6):
        _call()
    assert laptop.bedrock.invoke_model.call_count == 6


def test_the_refusal_is_a_budget_stop_so_the_retry_policy_does_not_back_off(laptop, monkeypatch):
    assert issubclass(cap.DevSessionBudgetExceeded, bc.budget_stop_cls())
    slept = []
    monkeypatch.setattr(bc.time, "sleep", slept.append)
    laptop.cloudwatch.get_metric_statistics.return_value = {"Datapoints": [{"Sum": 99.0}]}
    with pytest.raises(cap.DevSessionBudgetExceeded):
        bc.invoke_with_retry({"messages": [{"role": "user", "content": "x"}], "max_tokens": 8}, model_name=SONNET)
    assert slept == [] and laptop.bedrock.invoke_model.call_count == 0


def test_mutation_control_with_the_cap_not_applying_nothing_is_refused(laptop, monkeypatch):
    monkeypatch.setattr(cap, "applies", lambda *_a, **_k: False)
    for _ in range(6):
        _call()
    assert laptop.bedrock.invoke_model.call_count == 6
