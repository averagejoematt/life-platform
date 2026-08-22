"""tests/test_hae_webhook_errors_alarm_2822.py — #2822: hae-webhook Errors alarm.

health-auto-export-webhook's only dedicated watch was the no-invocations
heartbeat (AWS/Lambda Invocations < 1/24h in monitoring_stack): a 100%-ERROR
state (bad payload class, secret rotation, schema change) keeps invocations
FLOWING and that heartbeat green while near-real-time CGM/BP/water/State-of-
Mind readings drop, until the freshness checker's per-datatype staleness pages
2-3 days later. #2822 adds an AWS/Lambda Errors Sum >= 1 digest alarm beside
the function it watches (IngestionStack — where the fleet's per-Lambda
ingestion-error-* alarms have always been defined, via lambda_helpers'
error_alarm block; monitoring_stack sits at its size-ratchet ceiling and takes
no new alarms, per its own #2610 baseline note).

Static-analysis guards (no CDK install / no AWS), mirroring
tests/test_paging_alarms_1333.py: AST-parse the stack sources — never import
aws_cdk (it is absent from the Deploy-critical/Unit Test CI envs and fails at
collection). Against pre-#2822 HEAD the alarm call does not exist, so these
fail honestly — a real regression guard, not a vacuous one.
"""

import ast
import os
import re

_STACKS = os.path.join(os.path.dirname(__file__), "..", "cdk", "stacks")

ALARM_NAME = "hae-webhook-errors"
HEARTBEAT_NAME = "hae-webhook-no-invocations-24h"


def _src(name):
    with open(os.path.join(_STACKS, name)) as f:
        return f.read()


def _create_alarm_call(tree, alarm_name):
    """The .create_alarm(...) Call node carrying this alarm_name literal, or None."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "create_alarm":
            for kw in node.keywords:
                if kw.arg == "alarm_name" and isinstance(kw.value, ast.Constant) and kw.value.value == alarm_name:
                    return node
    return None


def _kw(node, name):
    return next((kw.value for kw in node.keywords if kw.arg == name), None)


def _the_alarm():
    node = _create_alarm_call(ast.parse(_src("ingestion_stack.py")), ALARM_NAME)
    assert node is not None, f"#2822: ingestion_stack.py must define the {ALARM_NAME} alarm via .create_alarm(...)"
    return node


class TestErrorsAlarmShape:
    def test_metric_is_the_functions_own_errors_metric(self):
        # Receiver chain: hae.metric_errors(...).create_alarm(...) — metric_errors
        # IS "AWS/Lambda Errors dimensioned on health-auto-export-webhook" by
        # construction (the same shape lambda_helpers' fleet error_alarm uses).
        node = _the_alarm()
        metric_call = node.func.value
        assert isinstance(metric_call, ast.Call) and isinstance(metric_call.func, ast.Attribute)
        assert metric_call.func.attr == "metric_errors", "#2822 must alarm the Lambda's Errors metric (metric_errors), nothing else"
        assert isinstance(metric_call.func.value, ast.Name) and metric_call.func.value.id == "hae", (
            "the Errors metric must be dimensioned on the HAE webhook function (`hae`), " "not some other construct"
        )
        stat = next((kw.value for kw in metric_call.keywords if kw.arg == "statistic"), None)
        assert isinstance(stat, ast.Constant) and stat.value == "Sum", "acceptance is Errors SUM >= 1"

    def test_period_is_one_hour_the_fleet_error_alarm_shape(self):
        # v6.9.2 fleet reasoning: 1h self-clears a transient blip, sustained
        # failure re-fires — and the whole point of #2822 is HOURS, not days.
        node = _the_alarm()
        metric_call = node.func.value
        period = next((kw.value for kw in metric_call.keywords if kw.arg == "period"), None)
        assert isinstance(period, ast.Call) and isinstance(period.func, ast.Attribute) and period.func.attr == "hours"
        assert isinstance(period.args[0], ast.Constant) and period.args[0].value == 1, "period must be 1 hour (the fleet error-alarm shape)"

    def test_threshold_sum_gte_one_single_period(self):
        node = _the_alarm()
        threshold = _kw(node, "threshold")
        assert isinstance(threshold, ast.Constant) and threshold.value == 1, "acceptance: Errors Sum >= 1"
        evals = _kw(node, "evaluation_periods")
        assert isinstance(evals, ast.Constant) and evals.value == 1, "one erroring hour is already dropped readings — no multi-period grace"
        op = _kw(node, "comparison_operator")
        assert isinstance(op, ast.Attribute) and op.attr == "GREATER_THAN_OR_EQUAL_TO_THRESHOLD"

    def test_treat_missing_not_breaching_absence_has_exactly_one_owner(self):
        # Errors is ABSENT only when there are no invocations at all — and that
        # state is owned by the no-invocations heartbeat (BREACHING). This alarm
        # breaching on missing data would double-report a quiet webhook.
        node = _the_alarm()
        tmd = _kw(node, "treat_missing_data")
        assert isinstance(tmd, ast.Attribute) and tmd.attr == "NOT_BREACHING", (
            "treat_missing_data must be NOT_BREACHING — absence of Errors = no invocations, "
            f"which {HEARTBEAT_NAME} (BREACHING) already owns"
        )

    def test_routes_to_the_digest_topic(self):
        # ADR-050: ingestion error alarms are digest-paced, and the issue's
        # acceptance names a digest alarm. Urgent would re-litigate ADR-116.
        src = _src("ingestion_stack.py")
        assert re.search(
            r"hae_errors\.add_alarm_action\(cw_actions\.SnsAction\(local_digest_topic\)\)", src
        ), "hae-webhook-errors must route to the DIGEST topic (ADR-050)"


class TestComplementaryPairStaysIntact:
    def test_heartbeat_still_exists_and_still_breaches_on_absence(self):
        # The NOT_BREACHING reasoning above only holds while the heartbeat leg
        # exists and breaches on absence — guard the pair, not one instance.
        tree = ast.parse(_src("monitoring_stack.py"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "Alarm":
                aname = _kw(node, "alarm_name")
                if isinstance(aname, ast.Constant) and aname.value == HEARTBEAT_NAME:
                    tmd = _kw(node, "treat_missing_data")
                    assert (
                        isinstance(tmd, ast.Attribute) and tmd.attr == "BREACHING"
                    ), f"{HEARTBEAT_NAME} must keep treat_missing_data=BREACHING — it owns the absence signal"
                    return
        raise AssertionError(f"{HEARTBEAT_NAME} vanished from monitoring_stack.py — the #2822 pair reasoning no longer holds")

    def test_adr116_posture_comment_names_the_carve_out(self):
        # Acceptance box 3: the ADR-116 "sustained failure is caught downstream"
        # posture note must record the near-real-time exception this alarm carves
        # out, so the next reader of that comment doesn't re-delete the alarm as
        # redundant with the freshness checker.
        src = _src("monitoring_stack.py")
        assert ALARM_NAME in src, "monitoring_stack.py's ADR-116 posture comment must name the hae-webhook-errors carve-out (#2822)"
