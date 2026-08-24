"""tests/cdk_alarm_pins.py — resolve a CDK log-token alarm's filter token from source.

WHY THIS EXISTS (#2977). Three test files pin a "twin" pair: a literal token a Lambda logs
when it swallows a failure, and the CloudWatch MetricFilter pattern the CDK scans for. If
they drift, the alarm watches a string nothing writes and the fail-soft path is silent
again — which is the incident each of those tests was written for (#2654 between-chronicle
scrub, #2763 expert-gate-infra-hold, #2977 recall-index-failed).

All three used to `open("cdk/stacks/monitoring_stack.py")` and regex it. Then #2977
extracted those alarms into the cohesive sibling `cdk/stacks/monitoring_silence_alarms.py`
(the #1665 size guard's extract-don't-raise rule) and every one of those pins broke —
loudly, which is the good outcome, but the shape they broke in is the one that usually
breaks quietly: a guard reading a named file that no longer holds the thing it guards
still runs, still passes on the half it can see, and proves nothing (#2703, "extract the
RIGHT real source"). Two properties fix that class, and this module is where they live
once instead of three times:

  * **Search the whole tree, name no file.** The pin follows the code through the next
    extraction without anyone remembering to update it.
  * **Fail when nothing is found.** `filter_tokens_for()` returning an empty set is what
    the callers assert against, so "the alarm disappeared entirely" is a red, not a green.

MECHANISM. Two-step variable trace per module, mirroring the one
`scripts/generate_platform_model.py` uses for SNS routing:

    <mf> = logs.MetricFilter(..., filter_pattern=logs.FilterPattern.literal('"TOKEN"'))
    <al> = cloudwatch.Alarm(alarm_name="the-alarm", metric=<mf>.metric(...))

so the pin is anchored to the alarm's own NAME rather than to a construct id or to
whatever text happens to sit near it in the file. A regex over the concatenated tree would
match across module boundaries; this cannot.
"""

from __future__ import annotations

import ast
import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STACKS_DIR = os.path.join(_REPO, "cdk", "stacks")


def _literal_token(node: ast.AST | None) -> str | None:
    """The TOKEN out of `logs.FilterPattern.literal('"TOKEN"')`, else None."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "literal"):
        return None
    if not (node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
        return None
    return node.args[0].value.strip('"')


def _alarm_tokens_in_module(tree: ast.AST) -> dict[str, str]:
    """`{alarm_name: token}` for every literal-token MetricFilter wired into an Alarm."""
    filters: dict[str, str] = {}  # variable name -> token
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
            continue
        call = node.value
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "MetricFilter"):
            continue
        token = _literal_token(next((kw.value for kw in call.keywords if kw.arg == "filter_pattern"), None))
        if token:
            filters[node.targets[0].id] = token

    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
            continue
        kwargs = {kw.arg: kw.value for kw in node.value.keywords if kw.arg}
        name_node, metric_node = kwargs.get("alarm_name"), kwargs.get("metric")
        if not (isinstance(name_node, ast.Constant) and isinstance(name_node.value, str)):
            continue
        # metric=<mf>.metric(...) — the filter variable is the attribute's base.
        if not (isinstance(metric_node, ast.Call) and isinstance(metric_node.func, ast.Attribute)):
            continue
        base = metric_node.func.value
        if isinstance(base, ast.Name) and base.id in filters:
            out[name_node.value] = filters[base.id]
    return out


def filter_tokens_for(alarm_name_fragment: str) -> set[str]:
    """Every literal MetricFilter token wired into an alarm whose name contains
    `alarm_name_fragment`, across all of cdk/stacks/*.py.

    Returns a SET (not a single value) on purpose: an alarm FAMILY shares one token across
    N alarms, so a caller asserting `== {LAMBDA_CONSTANT}` catches both drift AND a second,
    divergent token sneaking into the same family.
    """
    found: set[str] = set()
    for fname in sorted(os.listdir(STACKS_DIR)):
        if not fname.endswith(".py"):
            continue
        with open(os.path.join(STACKS_DIR, fname), encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=fname)
        for alarm_name, token in _alarm_tokens_in_module(tree).items():
            if alarm_name_fragment in alarm_name:
                found.add(token)
    return found
