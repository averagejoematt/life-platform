"""#2754 — every *-no-invocations-* alarm treats MISSING data as BREACHING.

AWS/Lambda emits NO Invocations datapoint for a zero-invocation period, so a
`Sum < 1` alarm with missing→NOT_BREACHING can structurally never fire: the
exact silence it exists to catch reads as health. The gate census called both
daily-brief and daily-debrief liveness alarms "cannot fire" for this reason
while hae-webhook's (BREACHING since the ADR-116 audit) could.

Guards the SET, not the instances: every alarm whose name contains
"no-invocations" — created via the `_alarm` helper OR a direct
`cloudwatch.Alarm` — must carry the BREACHING treatment, and the derivation
must be non-vacuous (it knows about the three that exist today).
"""

import ast
import os
import re

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STACK = os.path.join(_REPO, "cdk", "stacks", "monitoring_stack.py")


def _no_invocation_alarm_calls():
    """{alarm_name: has_breaching} for every no-invocations alarm creation."""
    src = open(_STACK).read()
    tree = ast.parse(src)
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # collect every string literal among args/kwargs to find the alarm name
        strings = [a.value for a in ast.walk(node) if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        names = [x for x in strings if "no-invocations" in x]
        if not names:
            continue
        # direct calls only (the _alarm helper or cloudwatch.Alarm), not nested walks
        fname = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if fname not in ("_alarm", "Alarm"):
            continue
        seg = ast.get_source_segment(src, node) or ""
        found[names[0]] = bool(re.search(r"TreatMissingData\.BREACHING|treat_missing_data\s*=\s*BREACH", seg))
    return found


def test_derivation_is_non_vacuous():
    found = _no_invocation_alarm_calls()
    assert {"daily-brief-no-invocations-24h", "daily-debrief-no-invocations-24h", "hae-webhook-no-invocations-24h"} <= set(found), found


def test_every_no_invocation_alarm_breaches_on_missing():
    found = _no_invocation_alarm_calls()
    silent = sorted(n for n, ok in found.items() if not ok)
    assert not silent, (
        f"no-invocations alarm(s) treat missing data as NOT_BREACHING and can structurally never fire: {silent} "
        "(AWS/Lambda emits no datapoint for a zero-invocation period — #2754)"
    )
