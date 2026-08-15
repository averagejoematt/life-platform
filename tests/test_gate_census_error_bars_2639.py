"""#2639 — the gate census had a blind spot, which is the thing the gate census is for.

Two **real, enforcing** CI steps were invisible to `scripts/gate_census.py`, and both sit in
the exact job slice 2 was sampling:

    ci-lint.yml  Syntax check (py_compile)    ends `if [ "$FAILED" -gt 0 ]; then … exit 1; fi`
    ci-lint.yml  Check lambda_map coverage    ends `if [ $MISSING -gt 0 ]; then … exit 1; fi`

Neither matched `_GATE_VERB`, which recognises a gate by the TOOL it runs, so both were
counted in `steps_nongate` rather than in the inventory. The census reported 421 gates
against a true number of at least 423.

A census with a silent blind spot answers a different question than the one it appears to
answer — the exact defect class #2578 was opened to hunt, now found inside the instrument
built to hunt it.

WIDENED, NOT HAND-ADDED, because the issue is explicit that a hand-added row is the failure
this census exists to replace. `_GATE_ENFORCES` asks the direct question — does this step
DELIBERATELY EXIT NON-ZERO? — which is what "can fail the build" means, whatever tool it
uses or doesn't. Narrow on purpose: `exit 0` is a SWALLOW idiom, not a gate, and a bare
`exit` with no code is not one either.

THE ISSUE NAMED TWO. THE WIDENING FOUND TWENTY. `by_enforcement_only` — CI gates detected
ONLY by their explicit exit and by no tool verb — is 20, and `steps_nongate` fell from 53 to
38. That is the census's own false-negative rate for the verb-only detector, and it is now
computed on every run rather than discovered by hand a second time.

WHAT THIS DOES **NOT** CLOSE, and the report says so rather than implying otherwise. Boxes 2
and 3 also ask for the residual to be adjudicated — how many of the remaining non-gate steps
are really gates, and what the false-positive rate is on the two large unsampled flags. Both
are human judgment over specific steps, not something a detector can assert. So the report
prints the residual COUNT and `--json` carries every residual LABEL, which is what makes the
adjudication possible; and the false-positive line states plainly that two sampled hits are
not a precision estimate.
"""

from __future__ import annotations

import importlib
import json
import os
import pathlib
import sys
import textwrap

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

# `gate_census.discover_ci_gates` imports PyYAML lazily so the module stays importable
# without it — but this file builds the census at IMPORT time, which runs that path. The
# deploy-critical CI lane installs a minimal dependency set and has no yaml, so the whole
# module raised ModuleNotFoundError there and reddened a lane that had nothing to do with
# this change. Skipping is correct rather than a cop-out: the gate still runs in the full
# `test / Unit Tests` lane, where PyYAML IS installed — verified, because a guard that
# skips in every lane is the "cannot fail" pattern this very file exists to measure.
pytest.importorskip("yaml", reason="gate_census's CI-family walk needs PyYAML; the full Unit Tests lane has it")

gate_census = importlib.import_module("gate_census")

CENSUS = gate_census.build_census(pathlib.Path(_REPO))
CI_COUNTERS = (CENSUS.get("counters") or {}).get("ci") or {}
CI_GATES = [g for g in CENSUS["gates"] if g["family"] == "ci-step"]


# ── the two the issue named ──────────────────────────────────────────────────


@pytest.mark.parametrize("needle", ["Syntax check (py_compile)", "Check lambda_map coverage"])
def test_the_two_missed_enforcing_steps_are_now_in_the_inventory(needle):
    assert any(needle in g["name"] for g in CI_GATES), f"{needle!r} is still invisible to the census"


def test_they_are_detected_by_the_widened_derivation_not_a_hand_added_row():
    """Acceptance box 1. A literal step name in the source would be the failure this
    census exists to replace, so assert the source does not contain one."""
    src = (pathlib.Path(_REPO) / "scripts" / "gate_census.py").read_text()
    for needle in ("Syntax check (py_compile)", "Check lambda_map coverage"):
        assert f'"{needle}"' not in src and f"'{needle}'" not in src, f"{needle!r} is hand-listed"
    assert "_GATE_ENFORCES" in src


# ── the derivation itself, mutation-proven ───────────────────────────────────


ENFORCING_BUT_VERBLESS = textwrap.dedent("""
    name: synthetic
    on: [push]
    jobs:
      j:
        runs-on: ubuntu-latest
        steps:
          - name: Enforce a thing with no recognisable tool
            run: |
              COUNT=$(ls -1 | wc -l)
              if [ "$COUNT" -gt 9999 ]; then
                echo "::error::too many"
                exit 1
              fi
    """).strip()

NOT_A_GATE = textwrap.dedent("""
    name: synthetic
    on: [push]
    jobs:
      j:
        runs-on: ubuntu-latest
        steps:
          - name: Just print something
            run: echo "hello"
    """).strip()


def _sweep(tmp_path, workflow_yaml):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "synthetic.yml").write_text(workflow_yaml)
    return gate_census.discover_ci_gates(tmp_path)


def test_a_new_enforcing_step_with_an_unusual_verb_is_detected(tmp_path):
    """Acceptance box 5, as a MUTATION rather than a claim: plant a step that enforces
    something in plain shell with no tool this census has ever heard of, and it must be
    counted. This is the shape both real misses had."""
    gates, counters = _sweep(tmp_path, ENFORCING_BUT_VERBLESS)
    assert len(gates) == 1, f"the planted enforcing step was dropped: {counters}"
    assert counters["by_enforcement_only"] == 1
    assert counters["steps_nongate"] == 0


def test_a_step_that_cannot_fail_is_still_not_a_gate(tmp_path):
    """The control. A widening that swallows everything would inflate n and be worse than
    the undercount it replaced."""
    gates, counters = _sweep(tmp_path, NOT_A_GATE)
    assert gates == []
    assert counters["steps_nongate"] == 1
    assert counters["nongate_sample"] == ["synthetic.yml::j / Just print something"]


@pytest.mark.parametrize(
    "run,expected",
    [
        ("exit 1", True),
        ("exit 2", True),
        ("python3 -c 'import sys; sys.exit(1)'", True),
        ("python3 -c 'raise SystemExit(3)'", True),
        ("foo || exit", True),
        ("exit 0", False),
        ("echo 'exit code 0 means ok'", False),
        ("echo hello", False),
    ],
)
def test_the_enforcement_detector_is_narrow_on_purpose(run, expected):
    """`exit 0` is a SWALLOW idiom, not a gate — treating it as one would classify the
    very steps this census flags as dangerous as gates in good standing."""
    assert bool(gate_census._GATE_ENFORCES.search(run)) is expected


# ── the error bars the report now prints ─────────────────────────────────────


def test_the_widening_found_far_more_than_the_two_that_were_filed():
    """The measured false-negative rate of the verb-only detector."""
    assert CI_COUNTERS["by_enforcement_only"] >= 10, CI_COUNTERS
    assert CI_COUNTERS["by_verb_only"] > 0, "both detectors must be contributing, or one is dead"


def test_the_report_states_its_error_in_both_directions():
    """Acceptance box 4 — `n` must never read as exact."""
    report = gate_census.render_report(CENSUS)
    assert "n is a FLOOR" in report
    assert "FALSE NEGATIVES (measured)" in report
    assert "FALSE POSITIVES (unmeasured)" in report
    assert "UNADJUDICATED" in report


def test_the_report_quantifies_the_residual_rather_than_hand_waving_it():
    """ "we might be missing some" is not a measurement. The residual has a number."""
    report = gate_census.render_report(CENSUS)
    assert f"UNADJUDICATED: {CI_COUNTERS['steps_nongate']} workflow steps" in report
    assert f"{CI_COUNTERS['by_enforcement_only']} of" in report


def test_the_residual_labels_are_carried_so_the_adjudication_is_possible():
    """Boxes 2 and 3 need a human to read specific steps. The instrument's job is to hand
    over the list, which is what turns an unbounded worry into a finite queue."""
    sample = CI_COUNTERS.get("nongate_sample")
    assert isinstance(sample, list)
    assert len(sample) == CI_COUNTERS["steps_nongate"], "the sample must be the WHOLE residual, not a slice"
    assert all("::" in s and "/" in s for s in sample), sample[:3]


def test_the_json_output_carries_the_counters():
    """`--json` is the machine surface the residual is worked from."""
    blob = json.loads(json.dumps(CENSUS, default=str))
    assert blob["counters"]["ci"]["by_enforcement_only"] == CI_COUNTERS["by_enforcement_only"]
