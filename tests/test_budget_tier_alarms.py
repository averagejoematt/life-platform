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


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
