"""#3260 — an alarm cannot watch a dimension set nothing emits.

THE DEFECT
----------
``slo-ai-coaching-success`` (cdk/stacks/monitoring_stack.py) is built with no ``dims=``,
so it watches the **dimensionless** ``LifePlatform/AI::AnthropicAPIFailure`` series. All
seven emitters attached ``{LambdaFunction: ...}``. CloudWatch does not roll a custom
metric up across dimension sets, so the alarm read a series nothing wrote:

* dimensionless ``AnthropicAPIFailure`` over 180d: **0 datapoints**
* ``{LambdaFunction=daily-brief}`` over the same window: 18 days, **329 failures**
* 2026-05-26 alone: **191 failures across five Lambdas**, against ``Sum >= 3`` per day
* alarm ``StateUpdatedTimestamp`` 2026-03-08, ``StateReason`` "no datapoints were received"

``life-platform-ddb-item-size-warning`` had the identical shape on
``LifePlatform/DynamoDB::ItemSizeBytes`` — dimensionless alarm, sole emitter attaching
``{Source: ...}``, and unlike the ``auth_breaker`` twin below nothing in the source ever
claimed that was deliberate.

THE RULING (pinned by ``test_fleet_alarms_stay_dimensionless``)
--------------------------------------------------------------
Both alarms keep their **fleet-wide** semantic and both stay **dimensionless**:

* ``slo-ai-coaching-success`` means "3 Bedrock transport failures ANYWHERE on the
  platform in a day pages". Splitting it into five per-function alarms would silently
  re-read ``Sum >= 3`` as a PER-FUNCTION threshold — five Lambdas failing twice each is
  10 real failures and no page — and would hand-list a Lambda roster in CDK, which is
  the guard-the-SET failure one level up.
* ``life-platform-ddb-item-size-warning`` means "the largest item ANY source wrote is
  approaching the 400 KB DynamoDB limit". ``Maximum`` over the fleet is the whole point.

So the fix is at the EMITTERS: each one now writes the dimensionless datapoint alongside
its dimensioned one, in the same ``put_metric_data`` call. That is not a new pattern —
``lambdas/ai/bedrock_client.py::_emit_usage_metrics`` already does it for
``AnthropicOutputTokens``/``EstimatedCostUSD``, and ``lambdas/common/auth_breaker.py::
auth_health_metric_data`` does it for ``IngestAuthHealthy`` *and says why in the source*.
``tests/test_oauth_alarm_coverage.py::test_aggregate_alarm_still_reads_the_dimensionless_stream``
is the inverse rule for that third case; this module is deliberately consistent with it
(the fleet aggregate stays dimensionless; what changes is that the series now exists).

SCOPE — deliberately NOT a fleet-wide derivation guard
------------------------------------------------------
A general "every CDK alarm's (namespace, metric, dimension-key set) matches a real
``PutMetricData`` site" guard was measured at ~1:21 signal-to-noise as naively specified
and is out of scope here (#3260 comment thread). What IS guarded is the SET that produced
this defect: **every emitter of these two metric names**, discovered by sweeping
``lambdas/`` rather than hand-listed — an eighth emitter that forgets the twin reds this.
"""

import ast
import os
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_LAMBDAS = _REPO / "lambdas"
_MONITORING = _REPO / "cdk" / "stacks" / "monitoring_stack.py"

# The two dimensionless fleet alarms and the metric each reads. The pair is the
# #3260 finding, not a licence to add a third without re-deriving it.
FLEET_ALARMS = {
    "slo-ai-coaching-success": "AnthropicAPIFailure",
    "life-platform-ddb-item-size-warning": "ItemSizeBytes",
}

# Floors, not rosters: a sweep that silently stops finding emitters looks exactly like a
# passing check (the vacuous-negative-control class). Measured at the time of the fix:
# 7 AnthropicAPIFailure emitters, 1 ItemSizeBytes emitter.
EMITTER_FLOOR = {"AnthropicAPIFailure": 7, "ItemSizeBytes": 1}


# ─────────────────────────────────────────────────────────────────────────────
# The rule, as a pure function over source text — so the must-fail case is provable
# against a synthetic string and can never be vacuous.
# ─────────────────────────────────────────────────────────────────────────────
def _metric_name_matches(node, target, fn_defaults):
    """Does this ``MetricName`` value node resolve to ``target``?

    Handles the two live shapes: a string constant, and a parameter name whose enclosing
    function default is the target (``ai_transport._emit_failure_metric(metric_name=...)``).
    """
    if isinstance(node, ast.Constant):
        return node.value == target
    if isinstance(node, ast.Name):
        return fn_defaults.get(node.id) == target
    return False


def _param_defaults(tree):
    """{param_name: default_constant} for every function in the module."""
    out = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = fn.args
        positional = args.posonlyargs + args.args
        for arg, default in zip(positional[len(positional) - len(args.defaults) :], args.defaults):
            if isinstance(default, ast.Constant):
                out[arg.arg] = default.value
        for arg, default in zip(args.kwonlyargs, args.kw_defaults):
            if isinstance(default, ast.Constant):
                out[arg.arg] = default.value
    return out


def dimensionless_emission_hits(source_text, target, label="<source>"):
    """Every ``put_metric_data`` call in ``source_text`` that writes ``target`` WITHOUT
    also writing a dimensionless datapoint for it. Returns a list of human-readable hits.

    Pure and text-driven on purpose: the regression test below plants a dimensioned-only
    emission in a synthetic string and proves this reports it (#1189's non-vacuous-scan
    lesson), and the same call reports zero on the real tree.
    """
    tree = ast.parse(source_text)
    defaults = _param_defaults(tree)
    hits = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if not (isinstance(func, ast.Attribute) and func.attr == "put_metric_data"):
            continue
        md = next((kw.value for kw in call.keywords if kw.arg == "MetricData"), None)
        if not isinstance(md, ast.List):
            continue
        writes_target = False
        has_dimensionless = False
        for point in md.elts:
            if not isinstance(point, ast.Dict):
                continue
            keys = {k.value for k in point.keys if isinstance(k, ast.Constant)}
            name_node = next((v for k, v in zip(point.keys, point.values) if isinstance(k, ast.Constant) and k.value == "MetricName"), None)
            if name_node is None or not _metric_name_matches(name_node, target, defaults):
                continue
            writes_target = True
            if "Dimensions" not in keys:
                has_dimensionless = True
        if writes_target and not has_dimensionless:
            hits.append(
                f"{label}:{call.lineno}: put_metric_data writes {target} with a dimension set on EVERY datapoint. "
                f"The fleet alarm reads the DIMENSIONLESS series and CloudWatch does not roll custom metrics up "
                f"across dimension sets — add {{'MetricName': '{target}', 'Value': ..., 'Unit': ...}} to the same "
                f"MetricData list (#3260; the bedrock_client / auth_breaker twin shape)."
            )
    return hits


def _emitter_files(target):
    """Every first-party module under lambdas/ that emits ``target`` — discovered, not
    hand-listed, so a new emitter enters the guard by existing."""
    found = []
    for root, dirs, files in os.walk(_LAMBDAS):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "node_modules")]
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            p = Path(root) / f
            text = p.read_text(encoding="utf-8")
            if f'"{target}"' in text and "put_metric_data" in text:
                found.append((p.relative_to(_REPO), text))
    return found


# ─────────────────────────────────────────────────────────────────────────────
# The gate
# ─────────────────────────────────────────────────────────────────────────────
def test_every_emitter_writes_the_dimensionless_series():
    """The defect, inverted: an emitter of a fleet-alarmed metric must write the
    dimensionless datapoint the alarm actually reads."""
    problems = []
    for metric in sorted(set(FLEET_ALARMS.values())):
        files = _emitter_files(metric)
        assert len(files) >= EMITTER_FLOOR[metric], (
            f"only {len(files)} emitters of {metric} found under lambdas/ (floor {EMITTER_FLOOR[metric]}). "
            "A sweep that stops finding its subject passes for the wrong reason — fix the sweep, "
            "or lower the floor in the SAME commit that removed the emitters."
        )
        for rel, text in files:
            problems += dimensionless_emission_hits(text, metric, label=str(rel))
    assert not problems, "\n".join(problems)


def test_the_rule_reports_a_dimensioned_only_emission():
    """POSITIVE CONTROL. Without this the test above is indistinguishable from a scan
    that matched nothing at all (the vacuous-negative-control class, #3212)."""
    planted = (
        "def _emit():\n"
        "    cw.put_metric_data(\n"
        '        Namespace="LifePlatform/AI",\n'
        '        MetricData=[{"MetricName": "AnthropicAPIFailure",\n'
        '                     "Dimensions": [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}],\n'
        '                     "Value": 1, "Unit": "Count"}],\n'
        "    )\n"
    )
    hits = dimensionless_emission_hits(planted, "AnthropicAPIFailure", label="planted.py")
    assert len(hits) == 1, hits
    assert "DIMENSIONLESS" in hits[0]


def test_the_rule_accepts_the_twin_shape():
    """NEGATIVE CONTROL: the shipped shape must be clean, or the rule is a tautology."""
    fixed = (
        "def _emit():\n"
        "    cw.put_metric_data(\n"
        '        Namespace="LifePlatform/AI",\n'
        '        MetricData=[{"MetricName": "AnthropicAPIFailure",\n'
        '                     "Dimensions": [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}],\n'
        '                     "Value": 1, "Unit": "Count"},\n'
        '                    {"MetricName": "AnthropicAPIFailure", "Value": 1, "Unit": "Count"}],\n'
        "    )\n"
    )
    assert dimensionless_emission_hits(fixed, "AnthropicAPIFailure", label="fixed.py") == []


def test_the_rule_resolves_a_parameterised_metric_name():
    """``ai_transport._emit_failure_metric(metric_name="AnthropicAPIFailure")`` writes the
    name through a PARAMETER (#2668 gave the IC-3 truncation its own series). A rule that
    only understood string constants would skip that emitter silently — which is exactly
    the shape of the bug being fixed."""
    planted = (
        'def _emit_failure_metric(metric_name: str = "AnthropicAPIFailure"):\n'
        "    cw.put_metric_data(\n"
        '        Namespace="LifePlatform/AI",\n'
        '        MetricData=[{"MetricName": metric_name,\n'
        '                     "Dimensions": [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}],\n'
        '                     "Value": 1, "Unit": "Count"}],\n'
        "    )\n"
    )
    assert len(dimensionless_emission_hits(planted, "AnthropicAPIFailure", label="planted.py")) == 1


def test_fleet_alarms_stay_dimensionless():
    """THE RULING, pinned. Both alarms are fleet aggregates; a ``dims=`` here would turn
    ``Sum >= 3`` into a per-function threshold (and ``Maximum`` into a per-source one)
    without anything else noticing. Mirrors — and does not contradict —
    test_oauth_alarm_coverage.test_aggregate_alarm_still_reads_the_dimensionless_stream,
    whose ``ingest-auth-unhealthy-24h`` is the same deliberate shape."""
    tree = ast.parse(_MONITORING.read_text(encoding="utf-8"))
    seen = set()
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        args = [a for a in call.args if isinstance(a, ast.Constant)]
        names = {a.value for a in args if isinstance(a.value, str)}
        for alarm_name, metric in FLEET_ALARMS.items():
            if alarm_name not in names or metric not in names:
                continue
            seen.add(alarm_name)
            dims = next((kw for kw in call.keywords if kw.arg == "dims"), None)
            assert dims is None, (
                f"{alarm_name} grew a dims= argument. It is a FLEET aggregate (#3260): with a "
                "dimension its threshold silently becomes per-function/per-source. If the semantic "
                "really changed, change it deliberately and rewrite this test's docstring."
            )
    assert seen == set(FLEET_ALARMS), f"alarm(s) not found in monitoring_stack.py: {sorted(set(FLEET_ALARMS) - seen)}"


def test_slo_doc_describes_the_alarm_as_deployed():
    """docs/SLOs.md described a threshold ("exceeds 2") and an emitter ("ai_calls.py")
    that were both wrong, and said nothing about the dimension that made the alarm dark
    for 180 days. A doc that describes intent rather than deployment is how this survived."""
    text = (_REPO / "docs" / "SLOs.md").read_text(encoding="utf-8")
    assert "### SLO-4" in text, "SLO-4 section vanished from docs/SLOs.md"
    block = text.split("### SLO-4")[1].split("\n### ")[0]
    assert "dimensionless" in block.lower(), "SLOs.md SLO-4 must state that the alarm reads the DIMENSIONLESS series (#3260)"
    assert "#3260" in block, "SLOs.md SLO-4 must cite #3260 so the 180-day dark window is findable"
    assert "exceeds 2" not in block, "SLOs.md SLO-4 still states the old threshold prose; the alarm is Sum >= 3 (#3260)"

    mon = (_REPO / "docs" / "MONITORING.md").read_text(encoding="utf-8")
    intro = mon.split("<!-- BEGIN GENERATED: alarm-inventory")[0]
    assert "#3260" in intro, (
        "MONITORING.md's Active-alarms prose must record the dimensionless-fleet-aggregate contract — "
        "it listed both alarm names while describing neither's dimension semantics (#3260)"
    )
