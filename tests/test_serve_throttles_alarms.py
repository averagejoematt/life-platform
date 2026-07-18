"""tests/test_serve_throttles_alarms.py — #1328: the public serving path's
saturation is an alarmed condition.

Replays the SDLC-review finding: the site-api reserved-concurrency cap of 5
bound daily (ConcurrentExecutions Max = 5.0 every day 07-10..07-17), readers ate
627 synchronous 429s in 30 days, and ZERO Throttles alarms existed for any
Lambda — monitoring showed green throughout.

Static-analysis tests (no CDK install / no AWS): AST-parse serve_stack.py and
assert (a) every Lambda the stack defines is covered by the Throttles-alarm
tuple and a Throttles metric+alarm loop actually exists, and (b) the site-api
reserved-concurrency cap is sized above the measured saturation point, not at
it. Mirrors tests/test_budget_tier_alarms.py's approach. Both tests FAIL on the
pre-#1328 tree (no Throttles alarms anywhere; cap == 5).
"""

import ast
import os

SERVE = os.path.join(os.path.dirname(__file__), "..", "cdk", "stacks", "serve_stack.py")

# The measured saturation point: the old cap of 5 was hit daily. Anything at or
# below it re-creates the daily-429 regime; the chosen value (20) is 4× measured
# peak. The floor here is deliberately the invariant (above saturation), the
# exact value is policy.
MEASURED_SATURATION = 5


def _tree():
    with open(SERVE) as f:
        return ast.parse(f.read())


def _kw(call, name):
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def test_every_serve_lambda_has_a_throttles_alarm():
    tree = _tree()

    # (a) every function this stack defines...
    defined = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "create_platform_lambda":
            fn = _kw(node, "function_name")
            if isinstance(fn, ast.Constant):
                defined.add(fn.value)
    assert defined, "no create_platform_lambda calls found — parser broke, investigate"

    # (b) ...appears in the THROTTLE_ALARMED_FUNCTIONS tuple...
    alarmed = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "THROTTLE_ALARMED_FUNCTIONS" for t in node.targets):
            alarmed = {pair[0] for pair in ast.literal_eval(node.value)}
    assert alarmed is not None, "THROTTLE_ALARMED_FUNCTIONS tuple missing from serve_stack.py (#1328)"
    missing = defined - alarmed
    assert not missing, f"serve-stack Lambdas without a Throttles alarm: {sorted(missing)}"

    # (c) ...and a real Throttles metric feeds an Alarm construct.
    throttles_metrics = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", "") == "Metric"
        and isinstance(_kw(node, "metric_name"), ast.Constant)
        and _kw(node, "metric_name").value == "Throttles"
    ]
    assert throttles_metrics, "no AWS/Lambda Throttles metric is declared in serve_stack.py"


def test_site_api_concurrency_cap_sized_above_measured_saturation():
    tree = _tree()
    caps = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "attr", "") == "add_property_override"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "ReservedConcurrentExecutions"
            and isinstance(node.args[1], ast.Constant)
        ):
            caps.append(node.args[1].value)
    assert caps, "no ReservedConcurrentExecutions overrides found in serve_stack.py"
    # site-api holds the larger cap; it must clear the measured saturation point.
    assert max(caps) > MEASURED_SATURATION, (
        f"site-api reserved concurrency ({max(caps)}) is at/below the measured "
        f"saturation point ({MEASURED_SATURATION}) — the daily-429 regime returns"
    )
