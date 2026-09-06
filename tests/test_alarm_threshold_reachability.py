"""tests/test_alarm_threshold_reachability.py — #3500: an Errors alarm must be able to
FIRE for the surface it guards.

THE DEFECT (measured, 2026-09-05 `/review full`, finding CTO-2)
  `site-api-ai-errors` was declared as `Errors Sum >= 3` over an hour with the comment
  "Threshold >=3/hr like slo-mcp-availability". That threshold was correct on
  slo-mcp-availability — a surface with a median of 5 invocations an hour — and
  unreachable on this one: across the 34h launch outage (2026-08-31T12Z→09-01T22Z) the
  function emitted 2 Errors in TOTAL, max 1.0 in any hour; 14-day daily Errors <= 1; the
  30-day max hourly Errors is 5, once. The failing sub-surface (`/api/board_ask`) saw
  about 8 gate attempts in 7 days. A 100% failure of it could not reach 3 in an hour, so
  the alarm was structurally incapable of firing for the outage class it exists to catch,
  and the #3413 P1 was found by the quality canary instead. `telegram-worker-errors`
  carried the same copied 3/hr against a surface with 30 ACTIVE hours in 14 days, median
  1 invocation/hr.

  This is the #3413 postmortem's own lesson — "a cap sized from a COMMENT never
  succeeds" — applied to the client cap and not to the alarm guarding the same surface.

THE RULE, over the SET rather than the two specimens
  Every AWS/Lambda `Errors` alarm in `cdk/stacks/**` must carry threshold <= 1, UNLESS
  its name appears in `MEASURED_TRAFFIC_WAIVERS` below with the measurement that makes
  a higher threshold reachable (the value, the date, and how it was read). An exemption
  without a measurement is a comment; that is what this test exists to stop.

  Threshold 1 is the honest default for this metric BECAUSE of what the metric is: one
  Errors datapoint is one failed invocation, and every one of these alarms is
  digest-routed (a line in the 8AM email, never a page — asserted below), so the cost of
  a transient blip is one line and the cost of an unreachable threshold is a silent
  outage.

Static analysis only — no CDK install, no AWS. Same discipline as
tests/test_urgent_alarm_routing.py and tests/test_token_alarm_composite_2116.py: the
sweep names no file, carries a population FLOOR so it cannot pass by matching nothing,
and proves itself against a planted positive control.
"""

from __future__ import annotations

import ast
import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STACKS_DIR = os.path.join(_REPO, "cdk", "stacks")

# The default this rule enforces: one failed invocation is one datapoint.
ERRORS_THRESHOLD_CEILING = 1

# name -> the measurement that makes a higher threshold reachable on THAT surface.
# Every entry must state the number, the window and the read — a dated measurement, not
# a comparison to another alarm (which is the exact mistake #3500 was filed for).
MEASURED_TRAFFIC_WAIVERS = {
    "slo-mcp-availability": (
        "measured 2026-09-05: AWS/Lambda Invocations on the MCP function, 30-day hourly "
        "median 5/hr (get-metric-statistics, period 3600) — a 100%-failure hour reaches 5 "
        "and clears the threshold of 3, so this alarm is reachable at its own surface's "
        "median. It is also an SLO alarm rather than an outage detector: a single "
        "transient error on the tool path is not an availability breach."
    ),
}

# The population floor. Measured 2026-09-05: 12 AWS/Lambda Errors alarms are declared
# with an explicit threshold across cdk/stacks/**, plus the per-Lambda alarms
# create_platform_lambda mints. A sweep that stops finding its subject looks exactly
# like a clean board, so this floor is what says so out loud.
ERRORS_ALARM_FLOOR = 10


def _stack_sources():
    out = []
    for entry in sorted(os.listdir(STACKS_DIR)):
        if entry.endswith(".py"):
            with open(os.path.join(STACKS_DIR, entry), encoding="utf-8") as fh:
                out.append((entry, fh.read()))
    return out


def _kw(call, name):
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def _const(node):
    return node.value if isinstance(node, ast.Constant) else None


def lambda_errors_alarms(source: str) -> list:
    """[(alarm_name, threshold)] for every AWS/Lambda `Errors` alarm in `source`.

    Pure over source text so the rule is provable against a synthetic module. The three
    construction shapes this repo uses:

      * `cloudwatch.Alarm(metric=cloudwatch.Metric(namespace="AWS/Lambda",
        metric_name="Errors", ...))` — the explicit form (serve_stack, mcp_stack);
      * `_alarm(id, name, "AWS/Lambda", "Errors", period, stat, threshold, op, ...)` —
        monitoring_stack's positional factory;
      * `fn.metric_errors(...).create_alarm(...)` — the per-Lambda alarm
        create_platform_lambda mints; `metric_errors` IS the AWS/Lambda Errors metric,
        which is why it is matched on the method name rather than on a namespace string.
    """
    tree = ast.parse(source)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # shape 2: the positional factory
        if isinstance(node.func, ast.Name) and node.func.id.endswith("_alarm") and len(node.args) >= 8:
            if _const(node.args[2]) == "AWS/Lambda" and _const(node.args[3]) == "Errors":
                found.append((_const(node.args[1]), _const(node.args[6])))
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr in ("Alarm", "create_alarm")):
            continue
        name = _const(_kw(node, "alarm_name"))
        threshold = _const(_kw(node, "threshold"))
        # shape 3: metric_errors(...).create_alarm(...)
        if node.func.attr == "create_alarm":
            receiver = node.func.value
            if isinstance(receiver, ast.Call) and isinstance(receiver.func, ast.Attribute) and receiver.func.attr == "metric_errors":
                found.append((name, threshold))
            continue
        # shape 1: an explicit Metric(...)
        metric = _kw(node, "metric")
        if isinstance(metric, ast.Call):
            if _const(_kw(metric, "namespace")) == "AWS/Lambda" and _const(_kw(metric, "metric_name")) == "Errors":
                found.append((name, threshold))
    return found


def unreachable_errors_alarms(source: str, exemptions=None) -> list:
    """[(alarm_name, threshold)] for every AWS/Lambda Errors alarm above the ceiling with
    no measured-traffic exemption."""
    exemptions = MEASURED_TRAFFIC_WAIVERS if exemptions is None else exemptions
    return [
        (name, threshold)
        for name, threshold in lambda_errors_alarms(source)
        if isinstance(threshold, (int, float)) and threshold > ERRORS_THRESHOLD_CEILING and name not in exemptions
    ]


def test_no_lambda_errors_alarm_carries_an_unreachable_threshold():
    """THE RULE. #3500's two specimens are fixed in the same commit; this is what stops
    the third being copied in from a fourth surface's comment."""
    offenders = []
    for module, source in _stack_sources():
        offenders += [f"{module}::{name} threshold={threshold}" for name, threshold in unreachable_errors_alarms(source)]
    assert not offenders, (
        "AWS/Lambda Errors alarm(s) with threshold > "
        f"{ERRORS_THRESHOLD_CEILING} and no measured-traffic exemption: {offenders}\n"
        "Either re-derive the threshold from THAT surface's own measured hourly traffic, or add an entry to "
        "MEASURED_TRAFFIC_WAIVERS in this file stating the measurement (value, window, how it was read)."
    )


def test_the_sweep_has_a_population():
    """FLOOR. Without this, an extractor that matched nothing would report a clean board
    — the vacuous-negative-control class the whole rule is about."""
    total = sum(len(lambda_errors_alarms(source)) for _module, source in _stack_sources())
    assert total >= ERRORS_ALARM_FLOOR, (
        f"only {total} AWS/Lambda Errors alarms found across cdk/stacks (floor {ERRORS_ALARM_FLOOR}) — "
        "the extractor went blind, or the alarms were removed and this floor must be lowered in the same commit"
    )


def test_the_two_repaired_specimens_are_at_threshold_one():
    """The #3500 fix itself, pinned by name so a revert is loud. Both were 3/hr."""
    found = {}
    for _module, source in _stack_sources():
        found.update(dict(lambda_errors_alarms(source)))
    assert found.get("site-api-ai-errors") == 1, "site-api-ai-errors must be reachable at 1 error/hr (#3500)"
    assert found.get("telegram-worker-errors") == 1, "telegram-worker-errors must be reachable at 1 error/hr (#3500)"


def test_every_exemption_states_its_measurement():
    """An exemption without a measurement is the comment that caused this defect."""
    for name, reason in MEASURED_TRAFFIC_WAIVERS.items():
        assert "measured" in reason.lower(), f"{name}'s exemption does not state a measurement"
        assert any(ch.isdigit() for ch in reason), f"{name}'s exemption states no number"


def test_every_exemption_names_a_real_alarm():
    """A rename must red here rather than leave an entry silently exempting nothing."""
    declared = {name for _module, source in _stack_sources() for name, _threshold in lambda_errors_alarms(source)}
    orphans = sorted(set(MEASURED_TRAFFIC_WAIVERS) - declared)
    assert not orphans, f"MEASURED_TRAFFIC_WAIVERS names alarm(s) no stack declares: {orphans}"


def test_the_rule_reds_on_a_planted_unreachable_alarm():
    """POSITIVE CONTROL, all three construction shapes."""
    planted_explicit = (
        "a = cloudwatch.Alarm(\n"
        "    self,\n"
        '    "Planted",\n'
        '    alarm_name="planted-errors",\n'
        '    metric=cloudwatch.Metric(namespace="AWS/Lambda", metric_name="Errors", period=Duration.seconds(3600), statistic="Sum"),\n'
        "    threshold=3,\n"
        ")\n"
    )
    planted_helper = '_alarm("Planted", "planted-helper-errors", "AWS/Lambda", "Errors", 3600, "Sum", 5, GTE)\n'
    planted_per_lambda = (
        "alarm = fn.metric_errors(period=Duration.hours(1), statistic='Sum').create_alarm(\n"
        "    scope, f'{id}ErrorAlarm', alarm_name='planted-per-lambda-errors', evaluation_periods=1, threshold=4,\n"
        ")\n"
    )
    assert unreachable_errors_alarms(planted_explicit, exemptions={}) == [("planted-errors", 3)]
    assert unreachable_errors_alarms(planted_helper, exemptions={}) == [("planted-helper-errors", 5)]
    assert unreachable_errors_alarms(planted_per_lambda, exemptions={}) == [("planted-per-lambda-errors", 4)]
    # NEGATIVE CONTROLS: at the ceiling, and exempted-with-a-measurement.
    assert unreachable_errors_alarms(planted_explicit.replace("threshold=3", "threshold=1"), exemptions={}) == []
    assert unreachable_errors_alarms(planted_explicit, exemptions={"planted-errors": "measured 2026-09-05: 40/hr median"}) == []
    # NEGATIVE CONTROL: a non-Errors Lambda alarm (Throttles) is out of scope.
    assert unreachable_errors_alarms(planted_explicit.replace('"Errors"', '"Throttles"'), exemptions={}) == []


def test_the_repaired_specimens_are_digest_routed_not_paging():
    """The threshold drop is only cheap because these alarms cost a digest LINE. If one
    were ever routed to the urgent/paging topic, 1/hr would page on a transient blip and
    the trade this test enshrines would no longer hold."""
    with open(os.path.join(STACKS_DIR, "serve_stack.py"), encoding="utf-8") as fh:
        serve = fh.read()
    for var in ("site_api_ai_errors", "_telegram_worker_errors"):
        assert f"{var}.add_alarm_action(cw_actions.SnsAction(local_digest_topic))" in serve, (
            f"{var} is no longer digest-routed — re-derive the threshold before routing an Errors alarm at 1/hr "
            "to a topic that pages (#3500)"
        )
