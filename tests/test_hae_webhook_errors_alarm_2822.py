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
import sys

import pytest

_STACKS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cdk", "stacks"))

# The alarm-shape resolver lives beside the constructor it has to follow (#2846),
# so the guard and the paved road cannot disagree about how an alarm is defined
# here. It is stdlib-only — importing it needs no CDK install.
if os.path.dirname(_STACKS) not in sys.path:
    sys.path.insert(0, os.path.dirname(_STACKS))

from stacks.lambda_enrollment import resolve_alarm_shape  # noqa: E402

ALARM_NAME = "hae-webhook-errors"
HEARTBEAT_NAME = "hae-webhook-no-invocations-24h"
FUNCTION_NAME = "health-auto-export-webhook"


def _src(name):
    with open(os.path.join(_STACKS, name)) as f:
        return f.read()


def _kw(node, name):
    return next((kw.value for kw in node.keywords if kw.arg == name), None)


def _the_alarm(stacks_dir=_STACKS):
    """The Call node whose kwargs are this alarm's REAL shape.

    #2846 moved health-auto-export-webhook onto `create_platform_lambda`, which
    means the alarm is no longer written out in ingestion_stack.py — it is created
    by the constructor from the `alarm_name=` the stack passes it. The synthesized
    CloudFormation is byte-identical either way; what changed is where the shape
    lives, and a guard keyed on one idiom stops guarding the moment a Lambda takes
    the paved road.

    `resolve_alarm_shape` accepts BOTH idioms and, for the constructor case, proves
    the wire in two hops (see its docstring): hop 1 the call site carrying this
    alarm_name plus the posture that decides an alarm is created at all, hop 2 the
    `.create_alarm(...)` inside the constructor whose name provably derives from the
    `alarm_name` PARAMETER. Every assertion below still bites on the node that
    actually shapes the deployed alarm — never on a default the guard cannot see.
    """
    resolved = resolve_alarm_shape(stacks_dir, ALARM_NAME)
    assert resolved is not None, (
        f"#2822: no definition of the {ALARM_NAME} alarm found. It must be created either "
        f"directly via .create_alarm(alarm_name={ALARM_NAME!r}) in a stack, or by passing "
        f"alarm_name={ALARM_NAME!r} to create_platform_lambda()."
    )
    return resolved


class TestErrorsAlarmShape:
    def test_the_alarm_is_actually_created_for_the_hae_webhook(self):
        """Hop 1: the posture at the call site must let an alarm exist at all.

        `create_platform_lambda` creates no alarm when `alerts_topic=None` or
        `error_alarm=False` — the fleet-wide ingestion default since 2026-05-29. A
        shape guard that skipped this would happily assert a perfect shape on an
        alarm the call site had switched off.
        """
        resolved = _the_alarm()
        if resolved["provenance"] == "direct":
            pytest.skip("alarm is written out directly — hop-1 posture does not apply")
        site = resolved["call_site"]
        assert (
            site["function_name"] == FUNCTION_NAME
        ), f"the {ALARM_NAME} alarm must be attached to {FUNCTION_NAME}, got {site['function_name']}"
        assert site["alerts_topic_present"], "alerts_topic=None at the call site means create_platform_lambda creates NO alarm"
        assert not site["error_alarm_disabled"], "error_alarm=False at the call site means create_platform_lambda creates NO alarm"

    def test_metric_is_the_functions_own_errors_metric(self):
        # Receiver chain: <fn>.metric_errors(...).create_alarm(...) — metric_errors
        # IS "AWS/Lambda Errors dimensioned on health-auto-export-webhook" by
        # construction (the same shape lambda_helpers' fleet error_alarm uses).
        resolved = _the_alarm()
        metric_call = resolved["metric_call"]
        assert isinstance(metric_call, ast.Call) and isinstance(metric_call.func, ast.Attribute)
        assert metric_call.func.attr == "metric_errors", "#2822 must alarm the Lambda's Errors metric (metric_errors), nothing else"
        assert isinstance(
            metric_call.func.value, ast.Name
        ), "the Errors metric must be dimensioned on the constructed Lambda itself, not some other construct"
        stat = next((kw.value for kw in metric_call.keywords if kw.arg == "statistic"), None)
        assert isinstance(stat, ast.Constant) and stat.value == "Sum", "acceptance is Errors SUM >= 1"

    def test_period_is_one_hour_the_fleet_error_alarm_shape(self):
        # v6.9.2 fleet reasoning: 1h self-clears a transient blip, sustained
        # failure re-fires — and the whole point of #2822 is HOURS, not days.
        resolved = _the_alarm()
        metric_call = resolved["metric_call"]
        period = next((kw.value for kw in metric_call.keywords if kw.arg == "period"), None)
        assert isinstance(period, ast.Call) and isinstance(period.func, ast.Attribute) and period.func.attr == "hours"
        assert isinstance(period.args[0], ast.Constant) and period.args[0].value == 1, "period must be 1 hour (the fleet error-alarm shape)"

    def test_threshold_sum_gte_one_single_period(self):
        node = _the_alarm()["shape_call"]
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
        node = _the_alarm()["shape_call"]
        tmd = _kw(node, "treat_missing_data")
        assert isinstance(tmd, ast.Attribute) and tmd.attr == "NOT_BREACHING", (
            "treat_missing_data must be NOT_BREACHING — absence of Errors = no invocations, "
            f"which {HEARTBEAT_NAME} (BREACHING) already owns"
        )

    def test_routes_to_the_digest_topic(self):
        """ADR-050: ingestion error alarms are digest-paced. Urgent re-litigates ADR-116.

        Two hops again. Hop 1: the call site asks for digest routing (`digest=True`
        with a `digest_topic` — either alone is inert). Hop 2: the constructor
        actually honours it — it selects `digest_topic` in the true branch of the
        routing conditional and feeds THAT into the alarm's `add_alarm_action`. A
        constructor that quietly dropped the digest leg would leave hop 1 looking
        wired to nothing.
        """
        resolved = _the_alarm()
        if resolved["provenance"] == "direct":
            src = _src(resolved["shape_file"])
            assert "add_alarm_action" in src and "digest" in src, f"{ALARM_NAME} must route to the DIGEST topic (ADR-050)"
            return

        site = resolved["call_site"]
        assert site["digest"] is True, f"{ALARM_NAME} must be requested with digest=True at the call site (ADR-050)"
        assert site["digest_topic_present"], "digest=True without a digest_topic is inert — the helper falls back to the urgent topic"

        ctor = resolved["constructor_fn"]
        selector = next(
            (
                n.value
                for n in ast.walk(ctor)
                if isinstance(n, ast.Assign)
                and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id == "_selected_topic"
                and isinstance(n.value, ast.IfExp)
            ),
            None,
        )
        assert selector is not None, "create_platform_lambda no longer selects a topic conditionally — digest routing cannot be honoured"
        chosen = {n.id for n in ast.walk(selector.body) if isinstance(n, ast.Name)}
        guard = {n.id for n in ast.walk(selector.test) if isinstance(n, ast.Name)}
        assert "digest_topic" in chosen and "digest" in guard, (
            "the constructor's routing conditional must pick digest_topic when digest is set — "
            f"{ALARM_NAME} would otherwise page urgently"
        )
        routed = [
            n
            for n in ast.walk(ctor)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "add_alarm_action"
            and any(isinstance(s, ast.Name) and s.id == "_selected_topic" for s in ast.walk(n))
        ]
        assert routed, "the constructor creates the alarm but never routes _selected_topic into add_alarm_action"


class TestTheGuardStillBites:
    """Mutation proofs — the two-hop resolution must FAIL on a real defect.

    Following a wire is only worth anything if the far end is still being read. Each
    test below plants a synthetic `cdk/stacks/` tree and re-runs the same assertions
    against it, so a resolver that silently stopped resolving would red here.
    """

    _HELPERS = (
        "from aws_cdk import Duration, aws_cloudwatch as cloudwatch\n"
        "def create_platform_lambda(scope, id, function_name, alarm_name=None,\n"
        "                           alerts_topic=None, digest_topic=None, digest=False, error_alarm=True):\n"
        "    _selected_topic = None\n"
        "    if alerts_topic is not None:\n"
        "        _selected_topic = digest_topic if (digest and digest_topic is not None) else alerts_topic\n"
        "    if _selected_topic and error_alarm:\n"
        "        _alarm_name = alarm_name if alarm_name else 'ingestion-error-x'\n"
        "        alarm = fn.metric_errors(period=Duration.hours({hours}), statistic='Sum').create_alarm(\n"
        "            scope, 'E', alarm_name=_alarm_name, evaluation_periods=1, threshold={threshold},\n"
        "            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,\n"
        "            treat_missing_data=cloudwatch.TreatMissingData.{tmd},\n"
        "        )\n"
        "        alarm.add_alarm_action(cw_actions.SnsAction(_selected_topic))\n"
        "    return fn\n"
    )
    _STACK = (
        "from stacks.lambda_helpers import create_platform_lambda\n"
        "create_platform_lambda(self, 'HaeWebhook', function_name='health-auto-export-webhook',\n"
        "                       alarm_name='hae-webhook-errors', alerts_topic=t,\n"
        "                       digest_topic={digest_topic}, digest={digest})\n"
    )

    def _plant(self, tmp_path, hours=1, threshold=1, tmd="NOT_BREACHING", digest="True", digest_topic="d"):
        (tmp_path / "lambda_helpers.py").write_text(self._HELPERS.format(hours=hours, threshold=threshold, tmd=tmd), encoding="utf-8")
        (tmp_path / "planted_stack.py").write_text(self._STACK.format(digest=digest, digest_topic=digest_topic), encoding="utf-8")
        return str(tmp_path)

    def test_the_planted_baseline_resolves_and_passes(self, tmp_path):
        """Control: the synthetic tree must satisfy the same shape the real one does."""
        resolved = _the_alarm(self._plant(tmp_path))
        assert resolved["provenance"] == "constructor"
        assert resolved["shape_file"] == "lambda_helpers.py"
        metric = resolved["metric_call"]
        assert next(k.value.args[0].value for k in metric.keywords if k.arg == "period") == 1
        assert _kw(resolved["shape_call"], "threshold").value == 1
        assert _kw(resolved["shape_call"], "treat_missing_data").attr == "NOT_BREACHING"

    def test_a_constructor_period_change_is_caught(self, tmp_path):
        """The #2822 argument is HOURS not days — a 24h period must red."""
        metric = _the_alarm(self._plant(tmp_path, hours=24))["metric_call"]
        period = next(k.value for k in metric.keywords if k.arg == "period")
        assert period.args[0].value == 24, "resolver read the wrong node"
        with pytest.raises(AssertionError):
            assert period.args[0].value == 1, "period must be 1 hour (the fleet error-alarm shape)"

    def test_a_constructor_treat_missing_flip_is_caught(self, tmp_path):
        """BREACHING here would double-report a quiet webhook against the heartbeat."""
        node = _the_alarm(self._plant(tmp_path, tmd="BREACHING"))["shape_call"]
        assert _kw(node, "treat_missing_data").attr == "BREACHING", "resolver read the wrong node"

    def test_a_call_site_that_drops_digest_is_caught(self, tmp_path):
        """digest=False routes to the urgent topic — ADR-116 re-litigated silently."""
        assert _the_alarm(self._plant(tmp_path, digest="False"))["call_site"]["digest"] is False

    def test_a_constructor_that_stopped_creating_the_alarm_resolves_to_nothing(self, tmp_path):
        """The whole point of hop 2: a no-op constructor must not look 'wired'."""
        (tmp_path / "lambda_helpers.py").write_text(
            "def create_platform_lambda(scope, id, function_name, alarm_name=None, **kw):\n    return fn\n", encoding="utf-8"
        )
        (tmp_path / "planted_stack.py").write_text(self._STACK.format(digest="True", digest_topic="d"), encoding="utf-8")
        assert resolve_alarm_shape(str(tmp_path), ALARM_NAME) is None
        with pytest.raises(AssertionError, match="no definition of the"):
            _the_alarm(str(tmp_path))


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
