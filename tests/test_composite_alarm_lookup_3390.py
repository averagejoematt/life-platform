"""tests/test_composite_alarm_lookup_3390.py — #3390 (cycle-16 Day-1 runlist finding).

WHAT WAS WRONG. `restart_verify.py`'s #2116 leg looked up the two token composites with

    describe_alarms(AlarmNames=[...]).get("CompositeAlarms", [])

`describe_alarms` returns ONLY metric alarms when `AlarmTypes` is omitted, so asking for
names that happen to be composite alarms yields an empty list — indistinguishable from
"not deployed yet". Measured live 2026-09-04: without `AlarmTypes` → **0** composites;
with `AlarmTypes=["CompositeAlarm"]` → **2**, both OK and correctly wired.

WHY IT MATTERED MORE THAN A WRONG LINE. The empty result took the deliberately tolerant
branch ("not deployed yet — needs cdk deploy, owner-gated"), which SKIPS the four real
assertions underneath it: that the raw alarm carries no SNS action of its own, and that
composite routing matches the genesis-window status. So from the moment #2116 actually
deployed, this leg reported a benign-looking line and verified nothing — the
absence-read-as-success class, inside the post-reset verifier whose whole job is catching
that class elsewhere.

A SECOND, SMALLER ONE IN THE SAME BLOCK. The passing check's detail branched on
`if raw_actions`, and the success condition IS an empty action list — so a correct
platform rendered as `raw alarm missing: [...]`. Truthiness of the thing whose emptiness
means success can never be the branch.

These tests are offline and shape-only: they pin the CALL, because the live behaviour is
an AWS API default no local fixture can enforce.
"""

from __future__ import annotations

import ast
import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VERIFY = os.path.join(_REPO, "deploy", "restart_verify.py")


def _source() -> str:
    with open(_VERIFY, encoding="utf-8") as fh:
        return fh.read()


def _describe_alarms_calls() -> list[ast.Call]:
    tree = ast.parse(_source())
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "describe_alarms":
            out.append(node)
    return out


def test_every_composite_lookup_passes_alarm_types():
    """The wire. A `describe_alarms` call that names composite alarms MUST ask for them:
    without `AlarmTypes` the API returns metric alarms only and the composites read as
    absent."""
    calls = _describe_alarms_calls()
    assert calls, "no describe_alarms call found in restart_verify.py — re-point this guard"

    checked = 0
    for call in calls:
        kwargs = {kw.arg: kw.value for kw in call.keywords}
        names_node = kwargs.get("AlarmNames")
        if not isinstance(names_node, ast.List):
            continue
        names = [e.value for e in names_node.elts if isinstance(e, ast.Constant)]
        if not any(n.endswith(("-urgent", "-genesis-window")) for n in names):
            continue  # a metric-alarm lookup: AlarmTypes is correctly absent
        checked += 1
        assert "AlarmTypes" in kwargs, (
            f"describe_alarms({names}) asks for COMPOSITE alarms without AlarmTypes — "
            "the API returns metric alarms only, so they read as 'not deployed' and the "
            "checks beneath are silently skipped (#3390)"
        )
        types_node = kwargs["AlarmTypes"]
        assert isinstance(types_node, ast.List)
        types = [e.value for e in types_node.elts if isinstance(e, ast.Constant)]
        assert "CompositeAlarm" in types, f"AlarmTypes={types} must include 'CompositeAlarm'"

    assert checked >= 1, "the composite lookup vanished from restart_verify.py — re-point this guard"


def test_the_raw_alarm_detail_does_not_branch_on_the_success_condition():
    """The success state is `AlarmActions == []`. Branching the detail message on
    `if raw_actions` therefore renders every PASS as 'raw alarm missing'."""
    src = _source()
    assert "raw alarm missing: {raw}" not in src, (
        "the #2116 raw-alarm detail still branches on the truthiness of an empty action "
        "list — a passing platform renders as 'raw alarm missing' (#3390)"
    )
    assert "raw alarm not found — cannot confirm its routing" in src, "the corrected absence message is gone — re-point this guard"
