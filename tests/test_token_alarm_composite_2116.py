"""tests/test_token_alarm_composite_2116.py — #2116: the composite-alarm half
of #1961's fix (completes PR #2114's flagged residual gap).

#2114 fixed the AUTOMATED remediation-triage escalation path (Lambda-side,
`lambdas/common/token_alarm_window.py`) but left the raw CloudWatch
`ai-tokens-platform-daily-total` alarm's own SNS action — routed straight to
the urgent topic, which also carries a direct human EmailSubscription
(`operational_stack.py`) — with no genesis-window awareness at all.

Static-analysis test (no CDK install / no AWS, mirrors
tests/test_budget_tier_alarms.py's / tests/test_urgent_alarm_routing.py's
approach): source-parses `cdk/stacks/monitoring_stack.py` to pin the shape of
the fix —
  1. the raw threshold alarm (`ai_tokens_platform_alarm`) carries NO
     `.add_alarm_action(...)` call of its own — only the two composites below
     route anywhere;
  2. the window-gauge sub-alarm reads `LifePlatform/AI::TokenAlarmGenesisWindowActive`
     on cost_governor's 8h cadence (period=28800s, matching
     `tests/test_budget_tier_alarms.py`'s pin on the sustained-tier alarm) and
     fails safe (`NB`/NOT_BREACHING) on missing data;
  3. `ai-tokens-platform-daily-total-urgent` composites the breach AND NOT
     in-window, routed to the urgent topic;
  4. `ai-tokens-platform-daily-total-genesis-window` composites the breach AND
     in-window, routed to the digest topic — the "digest path still records
     the breach" acceptance criterion.

A local `cdk synth` (`aws_cdk.assertions.Template`) was run once by hand while
authoring this fix to confirm the composite `AlarmRule` strings and
`AlarmActions` are exactly as pinned here — that isn't repeated on every test
run (no CDK bootstrap available in the unit-test environment), so this file is
the durable regression guard.
"""

import os

MONITORING = os.path.join(os.path.dirname(__file__), "..", "cdk", "stacks", "monitoring_stack.py")

with open(MONITORING) as _f:
    _SRC = _f.read()


def _block(start_marker: str, end_marker: str) -> str:
    """The source slice between two literal markers — good enough for a
    single-writer file where the block under test doesn't recur elsewhere."""
    start = _SRC.index(start_marker)
    end = _SRC.index(end_marker, start)
    return _SRC[start:end]


# The whole #2116 block, from the raw metric alarm through the second composite.
_BLOCK = _block("ai_tokens_platform_metric = cloudwatch.Metric(", "# G2: daily AI-spend ceiling")


def test_raw_alarm_carries_no_sns_action_of_its_own():
    """The raw threshold alarm must NOT itself call add_alarm_action — only the
    composites route anywhere. A regression here would double-page (raw alarm
    fires urgent directly again, defeating the whole suppression)."""
    assert "ai_tokens_platform_alarm.add_alarm_action" not in _BLOCK


def test_raw_alarm_threshold_and_metric_unchanged():
    assert 'alarm_name="ai-tokens-platform-daily-total"' in _BLOCK
    assert 'metric_name="AnthropicOutputTokens"' in _BLOCK
    assert "threshold=150000" in _BLOCK


def test_window_gauge_alarm_matches_cost_governor_cadence():
    """cost_governor_lambda runs every 8h (cron(0 0/8 * * ? *)) — the gauge
    alarm's period must match, same reasoning as
    test_budget_tier_alarms.py::test_sustained_alarm_requires_an_unbroken_week
    pins for the sibling BudgetTier gauge."""
    assert 'metric_name="TokenAlarmGenesisWindowActive"' in _BLOCK
    assert "period=Duration.seconds(28800)" in _BLOCK
    gauge_alarm = _block("genesis_window_alarm = cloudwatch.Alarm(", "_token_platform_breach =")
    assert 'alarm_name="token-alarm-genesis-window-active"' in gauge_alarm
    assert "threshold=1" in gauge_alarm
    assert "treat_missing_data=NB" in gauge_alarm, "a missing/stale gauge must fail safe to 'not in window' (still pages)"


def test_urgent_composite_requires_breach_and_not_in_window():
    urgent = _block("ai_tokens_platform_urgent = cloudwatch.CompositeAlarm(", "ai_tokens_platform_in_window = cloudwatch.CompositeAlarm(")
    assert 'composite_alarm_name="ai-tokens-platform-daily-total-urgent"' in urgent
    assert "AlarmRule.not_(_in_genesis_window)" in urgent, "urgent composite must exclude the in-window case"
    assert "cw_actions.SnsAction(topic)" in urgent, "urgent composite must route to the URGENT topic"


def test_in_window_composite_requires_breach_and_in_window_routes_digest():
    in_window = _block("ai_tokens_platform_in_window = cloudwatch.CompositeAlarm(", "# G2: daily AI-spend ceiling")
    assert 'composite_alarm_name="ai-tokens-platform-daily-total-genesis-window"' in in_window
    assert "AlarmRule.not_" not in in_window, "the in-window composite must NOT negate the gauge — it fires WHEN in window"
    assert "cw_actions.SnsAction(digest)" in in_window, "the in-window breach must record to DIGEST, not urgent (never silently dropped)"


def test_both_composites_gate_on_the_same_underlying_breach_and_gauge():
    """Both composites must reference the SAME two sub-alarms — a regression
    where one composite is built from a different metric/gauge instance would
    silently desync urgent vs digest routing."""
    assert _BLOCK.count("cloudwatch.AlarmRule.from_alarm(ai_tokens_platform_alarm, cloudwatch.AlarmState.ALARM)") == 1
    assert _BLOCK.count("cloudwatch.AlarmRule.from_alarm(genesis_window_alarm, cloudwatch.AlarmState.ALARM)") == 1
    assert _BLOCK.count("_token_platform_breach") >= 3  # defined once, used by both composites
    assert _BLOCK.count("_in_genesis_window") >= 3  # defined once, used by both composites (one negated)


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
