"""tests/test_silent_failure_heartbeats.py — REL-01: the watchdogs have watchdogs.

Each daily silent-failure DETECTOR (ingest-liveness, strava-reconciliation,
interior-gap, coherence) has a "≥1 problem" alarm with treat_missing_data=NB — which
is blind to the detector *itself* going dark (producer stops being invoked → no
metric → alarm stays OK forever). REL-01 pairs each with a BREACHING heartbeat alarm.

Static analysis (no CDK install), mirroring test_budget_tier_alarms.py.
"""

import ast
import glob
import os
import re

STACKS_DIR = os.path.join(os.path.dirname(__file__), "..", "cdk", "stacks")
MONITORING = os.path.join(STACKS_DIR, "monitoring_stack.py")

# The silent-failure detectors: (problem-alarm name, heartbeat-alarm name, metric).
#
# #3473: the two COMPUTE pairs were missing from this ledger, and that absence — not the
# missing alarm — is why the gap survived. `compute-pipeline-stale` shipped with NO
# heartbeat at all (a dark emitter read as a permanently healthy pipeline) and nothing
# here asked about it; `compute-outputs-missing` HAD both halves since #1455 and was
# equally unasserted, so the ledger would not have noticed if its heartbeat were deleted
# tomorrow. Guard the SET, not the instance: a pair that is not named here is not
# covered, so every daily compute/ingest detector belongs in this list.
_DETECTORS = [
    ("ingest-liveness-unhealthy", "ingest-liveness-heartbeat", "UnhealthySourceCount"),
    ("ingest-reconciliation-strava", "ingest-reconciliation-strava-heartbeat", "MissingActivityCount"),
    ("ingest-reconciliation-whoop", "ingest-reconciliation-whoop-heartbeat", "MissingActivityCount"),
    ("freshness-interior-gap", "freshness-interior-gap-heartbeat", "InteriorGapCount"),
    ("coherence-overall", "coherence-heartbeat", "OverallAlarm"),
    ("compute-pipeline-stale", "compute-pipeline-stale-heartbeat", "ComputePipelineStaleness"),
    ("compute-outputs-missing", "compute-outputs-heartbeat", "ComputeOutputsMissing"),
]


def _src():
    """monitoring_stack.py alone — for the helper-shape assertion, which is about THAT
    module's nested `_heartbeat_alarm` closure."""
    with open(MONITORING, encoding="utf-8") as f:
        return f.read()


def _all_stacks_src():
    """Every cdk/stacks/*.py concatenated. An alarm is not less declared for living in a
    cohesive sibling — reading one file by name is how a guard silently stops covering
    what it names (the #2977 cdk_alarm_pins.py fix, same shape)."""
    out = []
    for path in sorted(glob.glob(os.path.join(STACKS_DIR, "*.py"))):
        with open(path, encoding="utf-8") as f:
            out.append(f.read())
    return "\n".join(out)


def test_heartbeat_helper_is_breaching_silence_detector():
    """The _heartbeat_alarm helper must alarm on ABSENCE (BREACHING + SampleCount<1
    over N consecutive full days) — not on a value threshold."""
    src = _src()
    m = re.search(r"def _heartbeat_alarm\(.*?\n(?=\s{8}#|\s{8}def |\s{8}[A-Za-z])", src, re.DOTALL)
    assert m, "_heartbeat_alarm helper not found"
    body = m.group(0)
    assert "TreatMissingData.BREACHING" in body, "heartbeat must treat missing data as BREACHING (absence = failure)"
    assert 'statistic="SampleCount"' in body, "heartbeat must count datapoints (did it emit at all?)"
    assert "datapoints_to_alarm=days" in body and "evaluation_periods=days" in body, "must require N consecutive silent days"
    assert "comparison_operator=LT" in body, "SampleCount < 1 = no emission"


def test_every_detector_has_both_a_problem_alarm_and_a_heartbeat():
    """The pairing is the whole point: each detector keeps its ≥1 problem alarm AND
    gains an absence heartbeat. Neither alone closes the gap."""
    src = _all_stacks_src()
    for problem_name, heartbeat_name, metric in _DETECTORS:
        assert f'"{problem_name}"' in src, f"missing problem-detection alarm {problem_name}"
        assert f'"{heartbeat_name}"' in src, f"missing REL-01 heartbeat alarm {heartbeat_name}"
        assert metric in src, f"detector metric {metric} not referenced"


def test_heartbeats_are_declared_via_the_helper():
    """Each heartbeat must go through _heartbeat_alarm (so it inherits the BREACHING
    config), not a hand-rolled _alarm that could silently be NB."""
    tree = ast.parse(_all_stacks_src())
    heartbeat_calls = [
        n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_heartbeat_alarm"
    ]
    names = {a.value for c in heartbeat_calls for a in c.args if isinstance(a, ast.Constant) and isinstance(a.value, str)}
    for _, heartbeat_name, _ in _DETECTORS:
        assert heartbeat_name in names, f"{heartbeat_name} not created via _heartbeat_alarm()"
