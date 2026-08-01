"""
tests/test_budget_tier_alarms.py — SS-03 budget-tier hard-stop alarm.

The cost governor degrades AI features by writing a tier 0-3 to SSM and emitting
LifePlatform/Budget::BudgetTier. Tier >= 2 (website AI paused) is already routed to
the daily DIGEST by `life-platform-budget-tier-escalation`. The genuine gap was
tier 3 — ALL Bedrock paused, so the daily brief itself goes data-only — which the
≥2 digest alarm conflates with the milder tier 2. `budget-tier-hardstop` escalates
tier 3 specifically to the URGENT topic so a kill-switch pages promptly (the
"hands-off 6-month" failure mode is "AI dies, nobody notices for weeks").

This is a static-analysis test (no CDK install / no AWS): it AST-parses
monitoring_stack.py and asserts the hard-stop alarm is declared on the right metric,
threshold, and routing (urgent), and sits strictly above the existing ≥2 digest
alarm. Mirrors the approach in test_role_policies.py.

Run:  python3 -m pytest tests/test_budget_tier_alarms.py -v
"""

import ast
import os

MONITORING = os.path.join(os.path.dirname(__file__), "..", "cdk", "stacks", "monitoring_stack.py")

# Positional parameter order of the in-stack `_alarm(...)` helper.
_PARAMS = [
    "alarm_id",
    "alarm_name",
    "namespace",
    "metric_name",
    "period_sec",
    "statistic",
    "threshold",
    "operator",
    "dims",
    "ext_stat",
    "to_digest",
    "evaluation_periods",
]


def _literal(node):
    """Best-effort constant extraction; returns the raw node name for identifiers."""
    try:
        return ast.literal_eval(node)
    except Exception:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None


def _alarm_calls():
    """All `_alarm(...)` calls in monitoring_stack.py as {param: value} dicts."""
    with open(MONITORING) as f:
        tree = ast.parse(f.read())
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_alarm":
            kw = {a: None for a in _PARAMS}
            for i, arg in enumerate(node.args):
                if i < len(_PARAMS):
                    kw[_PARAMS[i]] = _literal(arg)
            for k in node.keywords:
                if k.arg in kw:
                    kw[k.arg] = _literal(k.value)
            calls.append(kw)
    return calls


def _by_name(name):
    for c in _alarm_calls():
        if c["alarm_name"] == name:
            return c
    return None


def test_hardstop_alarm_present_and_urgent():
    a = _by_name("budget-tier-hardstop")
    assert a is not None, "budget-tier-hardstop alarm missing"
    assert a["namespace"] == "LifePlatform/Budget"
    assert a["metric_name"] == "BudgetTier"
    assert a["threshold"] == 3
    assert a["statistic"] == "Maximum"
    # Tier 3 = all Bedrock off, daily brief data-only → urgent topic, not digest.
    assert a["to_digest"] in (None, False)


def test_existing_escalation_digest_still_present():
    """The ≥2 → digest alarm (website AI paused) must remain — the hard-stop alarm
    complements it, it does not replace it."""
    a = _by_name("life-platform-budget-tier-escalation")
    assert a is not None, "the existing ≥2 budget-tier digest alarm went missing"
    assert a["threshold"] == 2
    assert a["to_digest"] is True


def test_hardstop_is_strictly_above_escalation():
    """Hard-stop must require a strictly higher tier than the ≥2 digest alarm, else
    the urgent page would fire for the milder (auto-reverting) tier-2 degradation."""
    escalation = _by_name("life-platform-budget-tier-escalation")
    hardstop = _by_name("budget-tier-hardstop")
    assert escalation["threshold"] < hardstop["threshold"]


# ---------------------------------------------------------------------------
# #1927 — a pause that never lifts is a different fact from a pause
# ---------------------------------------------------------------------------
# Between 2026-07-06 and 2026-08-01 the tier sat at >= 1 for 26 CONSECUTIVE days.
# Nothing alarmed on that: the two alarms above start at tier 2, and #1440's
# QAPausedByBudget is per-day, so it fired 26 times and read as background. The
# whole cutoff-1 band was off for the month — including reader_truth_qa and
# visual_ai_qa, two CI gates that report green when paused.


def test_sustained_tier_alarm_present_and_covers_tier_1():
    a = _by_name("budget-tier-sustained-7d")
    assert a is not None, "budget-tier-sustained-7d missing — nothing watches a tier-1 band that never lifts (#1927)"
    assert a["namespace"] == "LifePlatform/Budget"
    assert a["metric_name"] == "BudgetTier"
    assert a["threshold"] == 1, "must cover tier 1 — the existing alarms both start at 2"
    assert a["to_digest"] is True, "routine-but-important: digest, not an urgent page"


def test_sustained_alarm_requires_an_unbroken_week():
    """Minimum + every datapoint means one tier-0 reading anywhere clears it.

    With Statistic=Maximum, or datapoints_to_alarm < evaluation_periods, this would
    fire during ordinary end-of-month pressure and become the same background noise
    it exists to replace.
    """
    a = _by_name("budget-tier-sustained-7d")
    assert a["statistic"] == "Minimum", "Maximum would fire on a single spike, not on a sustained condition"
    assert a["evaluation_periods"] == 21
    assert a["period_sec"] == 28800, "cost_governor emits BudgetTier every 8h"


def test_sustained_alarm_window_is_within_the_cloudwatch_ceiling():
    """EvaluationPeriods x Period must be <= 604800s or CloudFormation rejects it."""
    a = _by_name("budget-tier-sustained-7d")
    window = a["period_sec"] * a["evaluation_periods"]
    assert window <= 604800, f"alarm window {window}s exceeds CloudWatch's 604800s cap"
    assert window == 604800, "the window is meant to be exactly 7 days"


def test_sustained_alarm_is_distinct_from_the_tier2_escalation():
    """It must add tier-1 duration coverage, not restate the tier-2 level alarm."""
    sustained = _by_name("budget-tier-sustained-7d")
    escalation = _by_name("life-platform-budget-tier-escalation")
    assert sustained["threshold"] < escalation["threshold"]
    assert sustained["evaluation_periods"] > (escalation["evaluation_periods"] or 1)


def test_alarm_helper_defaults_to_a_single_period():
    """The new parameter must not silently widen every other alarm's window."""
    for c in _alarm_calls():
        if c["alarm_name"] == "budget-tier-sustained-7d":
            continue
        assert c["evaluation_periods"] is None, f"{c['alarm_name']} unexpectedly sets evaluation_periods"


def test_single_period_alarms_do_not_emit_datapoints_to_alarm():
    """Adding the parameter must not churn ~30 untouched deployed alarms.

    Passing datapoints_to_alarm unconditionally is semantically identical at 1-of-1
    (CloudFormation already defaults it to EvaluationPeriods) but it emits the
    property on EVERY alarm — the first cut of this change produced
    `[+] DatapointsToAlarm 1` against ~30 resources nobody had touched. A no-op
    change to that many deployed alarms is noise in every future cdk diff and
    buries the one line that matters.
    """
    with open(MONITORING) as f:
        src = f.read()
    assert (
        "datapoints_to_alarm=evaluation_periods if evaluation_periods > 1 else None" in src
    ), "the _alarm helper must only set datapoints_to_alarm for a multi-period alarm"


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
