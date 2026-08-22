"""tests/test_cost_drift_alarm_2883.py — #2883 box 3: the AI-cost drift ratio ALARMS.

`LifePlatform/Budget::CostMetricDriftRatio` (cost_governor `_emit_metrics`) measures
how much the platform's self-emitted per-caller AI attribution under-counts the
authoritative AWS/Bedrock-derived estimate. #357's regression (3x → 2.44x, closed,
never re-read) sat unnoticed for weeks because the governor PUBLISHED the ratio and
nothing was obligated to read it. `cost-metric-drift-sustained` is the obligation:
a ratio at/above the 1.15 acceptance bar sustained for a full week goes to the
daily digest.

The alarm lives in operational_stack.py beside the governor Lambda it watches
(the permanence-heartbeat precedent: monitoring_stack.py sits at its recorded
size ceiling, and each stack owns the alarms for the Lambdas it defines).

Static-analysis tests (no CDK install / no AWS — `aws_cdk` is NOT installed in
the CI unit-test jobs and importing it aborts collection): AST-parse
operational_stack.py for the `cloudwatch.Alarm(...)` declaration and
cost_governor_lambda.py for DRIFT_RATIO_BAR, mirroring
tests/test_budget_tier_alarms.py's approach.

Run:  python3 -m pytest tests/test_cost_drift_alarm_2883.py -v
"""

import ast
import json
import os

HERE = os.path.dirname(__file__)
OPERATIONAL = os.path.join(HERE, "..", "cdk", "stacks", "operational_stack.py")
GOVERNOR = os.path.join(HERE, "..", "lambdas", "operational", "cost_governor_lambda.py")
CITATIONS = os.path.join(HERE, "..", "docs", "alarm_citations.json")

ALARM_NAME = "cost-metric-drift-sustained"


def _tree(path):
    with open(path) as f:
        return ast.parse(f.read())


def _kw(call, name):
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def _attr_name(node):
    """`cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD` → the leaf attr."""
    return node.attr if isinstance(node, ast.Attribute) else None


def _alarm_call():
    """The cloudwatch.Alarm(...) call whose alarm_name is ALARM_NAME, or None."""
    for node in ast.walk(_tree(OPERATIONAL)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "Alarm":
            name_node = _kw(node, "alarm_name")
            if isinstance(name_node, ast.Constant) and name_node.value == ALARM_NAME:
                return node
    return None


def _metric_call(alarm):
    m = _kw(alarm, "metric")
    assert isinstance(m, ast.Call), "alarm metric must be an inline cloudwatch.Metric(...) call"
    return m


def _governor_bar():
    """cost_governor_lambda.DRIFT_RATIO_BAR by AST — no import (module-level boto3
    clients; and the bar is a literal, so AST is the honest comparison anyway)."""
    for node in ast.walk(_tree(GOVERNOR)):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Name) and t.id == "DRIFT_RATIO_BAR":
                return ast.literal_eval(node.value)
    return None


def test_drift_alarm_exists_on_the_governor_metric():
    a = _alarm_call()
    assert (
        a is not None
    ), f"{ALARM_NAME} alarm missing from operational_stack.py — a drift regression would again sit unnoticed (#2883/#357)"
    m = _metric_call(a)
    assert ast.literal_eval(_kw(m, "namespace")) == "LifePlatform/Budget"
    assert ast.literal_eval(_kw(m, "metric_name")) == "CostMetricDriftRatio"


def test_drift_alarm_threshold_is_the_governor_acceptance_bar():
    """One bar, two files: the alarm's threshold and the governor's own
    DRIFT_RATIO_BAR (its log-warning threshold) must be the same number, or the
    governor's log and the CloudWatch alarm disagree about what a breach is."""
    bar = _governor_bar()
    assert bar is not None, "cost_governor_lambda.DRIFT_RATIO_BAR missing"
    a = _alarm_call()
    threshold = ast.literal_eval(_kw(a, "threshold"))
    assert threshold == bar, f"alarm threshold {threshold} != cost_governor DRIFT_RATIO_BAR {bar} — the two literals drifted"
    assert bar == 1.15, "the #2883 acceptance bar is < 1.15; a silent bar change must be a deliberate, reviewed edit here"
    assert (
        _attr_name(_kw(a, "comparison_operator")) == "GREATER_THAN_OR_EQUAL_TO_THRESHOLD"
    ), "acceptance is '< 1.15 passes', so the breach condition is >= 1.15"


def test_drift_alarm_requires_an_unbroken_week():
    """Mirrors budget-tier-sustained-7d (monitoring_stack.py): Minimum +
    all-datapoints means a single below-bar reading clears it, so month-start
    noise (tiny MTD sums on both sides of the division) cannot fire it alone; a
    genuine sustained regression fires within 7 days — the same window as #2883
    box 2's own 'sustained over 7 days' acceptance language."""
    a = _alarm_call()
    m = _metric_call(a)
    assert ast.literal_eval(_kw(m, "statistic")) == "Minimum", "Maximum would fire on one noisy datapoint, not a sustained regression"
    period = _kw(m, "period")
    assert isinstance(period, ast.Call) and ast.literal_eval(period.args[0]) == 28800, "cost_governor emits CostMetricDriftRatio every 8h"
    assert ast.literal_eval(_kw(a, "evaluation_periods")) == 21
    assert ast.literal_eval(_kw(a, "datapoints_to_alarm")) == 21, "all 21 must breach, or one noisy day fires it"
    # 28800 x 21 == 604800 — exactly the CloudWatch evaluation-window ceiling.
    assert 28800 * 21 == 604800


def test_drift_alarm_missing_data_is_not_breaching():
    """The governor deliberately skips emission while self-reported MTD is 0
    (month start / no EMF datapoints yet). An absent datapoint must read as
    not-breaching or every month would open in ALARM. Governor death is a
    different fact covered by cost-governor-heartbeat and the governor's DLQ."""
    a = _alarm_call()
    assert _attr_name(_kw(a, "treat_missing_data")) == "NOT_BREACHING"


def test_drift_alarm_routes_to_digest_not_urgent():
    """Sustained attribution drift is a trust problem, not an outage — digest.
    Assert the SnsAction wiring targets the local_digest_topic handle AND that
    the handle really is built from DIGEST_TOPIC_ARN (name alone proves nothing)."""
    tree = _tree(OPERATIONAL)
    # Which variable holds this alarm? cost_drift_alarm = cloudwatch.Alarm(... ALARM_NAME ...)
    var = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Attribute) and call.func.attr == "Alarm":
                name_node = _kw(call, "alarm_name")
                if isinstance(name_node, ast.Constant) and name_node.value == ALARM_NAME and isinstance(node.targets[0], ast.Name):
                    var = node.targets[0].id
    assert var, f"{ALARM_NAME} must be assigned to a variable so its actions are wireable"

    # <var>.add_alarm_action(cw_actions.SnsAction(<topic-var>))
    topic_vars = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_alarm_action"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == var
            and node.args
            and isinstance(node.args[0], ast.Call)
            and node.args[0].args
            and isinstance(node.args[0].args[0], ast.Name)
        ):
            topic_vars.add(node.args[0].args[0].id)
    assert topic_vars, f"{ALARM_NAME} has no add_alarm_action — it would evaluate and notify nobody"

    # Resolve each topic var to the ARN constant it was built from.
    var_to_arn = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "from_topic_arn"
            and len(node.value.args) >= 3
            and isinstance(node.value.args[2], ast.Name)
            and isinstance(node.targets[0], ast.Name)
        ):
            var_to_arn[node.targets[0].id] = node.value.args[2].id
    routed = {var_to_arn.get(v) for v in topic_vars}
    assert routed == {"DIGEST_TOPIC_ARN"}, f"{ALARM_NAME} must route to the digest topic only, got {routed}"


def test_drift_alarm_has_an_expected_red_citation():
    """The alarm deploys RED-bound (live ratio ~1.37 since 2026-08-19 vs the 1.15
    bar, #2883 box 2 still open), so the /wrap alarm-citation gate (#1959) needs
    an entry naming the issue — otherwise the first week ends with an uncited
    long-red flag instead of a documented, expected state."""
    with open(CITATIONS) as f:
        data = json.load(f)
    entry = data.get(ALARM_NAME)
    assert entry, f"docs/alarm_citations.json entry for {ALARM_NAME} missing"
    assert "#2883" in entry.get("citation", "")


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
