"""#2746 — a CI step that enforces something must be ABLE to fail.

`golden-brief-eval.yml`'s step was literally named "Deterministic verdict (gating,
free)" and could not fail: it ran both harnesses through `| tee`, and GitHub's default
shell is `bash -e {0}` where `-e` does NOT imply `pipefail`. The pipeline exited with
tee's status, and the step's last command was a `head`, discarding even that.

Measured before the fix:

    bash -e -c 'python3 -c "sys.exit(1)" | tee /tmp/g.txt; head -1 /tmp/g.txt'
    step-exit=0            <- green on a failing harness

This is the SET version of that fix (never the instance): every gate-ish step in every
workflow, now and later. It is the same defect `ci-test.yml` already fixed and documents
beside its coverage gate — which is precisely why guarding one file would not have been
enough.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

yaml = pytest.importorskip("yaml")  # PyYAML is absent from the deploy-critical lane (#2732)

import gate_census as gc  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
# A real pipe. `||` is a logical-or and must not match — that false positive made a
# first pass report the deploy path as broken when its smoke steps are fine.
_REAL_PIPE = re.compile(r"^(?!\s*#).*(?<!\|)\|(?!\|)\s*(tee|tail|head|grep|sed|awk|cat)\b", re.M)
# An explicit `set +e` is a DELIBERATE opt-out, not an accident: `ci-cd.yml`'s CDK-diff
# step does it on purpose because `cdk diff` returns non-zero merely when differences
# exist, and it captures the code itself. Intent that is stated is not this bug.
_DELIBERATE = re.compile(r"^\s*set \+e\b", re.M)


def _gateish_steps():
    for wf in sorted((_ROOT / ".github" / "workflows").glob("*.yml")):
        doc = yaml.safe_load(wf.read_text()) or {}
        wf_shell = ((doc.get("defaults") or {}).get("run") or {}).get("shell") or ""
        for job_name, job in (doc.get("jobs") or {}).items():
            job_shell = ((job.get("defaults") or {}).get("run") or {}).get("shell") or ""
            for step in job.get("steps") or []:
                run = step.get("run") or ""
                if not run or step.get("continue-on-error"):
                    continue  # advisory by declaration — allowed to be soft
                if not (gc._GATE_VERB.search(run) or gc._GATE_ENFORCES.search(run)):
                    continue
                yield (f"{wf.name}::{job_name} / {step.get('name')}", run, f"{wf_shell} {job_shell}")


def test_no_enforcing_step_swallows_its_own_exit_status():
    """The dangerous shape is narrow, and being precise about it matters: a step where
    the TOOL'S OWN exit status is the whole gate, and that status is piped away.

    A step carrying an explicit `exit N` (`_GATE_ENFORCES`) is fine no matter how many
    pipes it contains — `ci-test.yml`'s Deprecated-secrets scan pipes inside `$(...)`
    for display and then enforces with an unpiped `if [ "$FAILED" -gt 0 ]; then exit 1`.
    A first draft of this guard flagged it, which would have taught the next reader to
    ignore the guard (#1985).
    """
    offenders = []
    for label, run, shells in _gateish_steps():
        if not _REAL_PIPE.search(run):
            continue
        if gc._GATE_ENFORCES.search(run):
            continue  # enforces explicitly; the pipeline's status is not the gate
        if "pipefail" in run or "pipefail" in shells or _DELIBERATE.search(run):
            continue
        offenders.append(label)
    assert not offenders, "enforcing step(s) whose exit status is swallowed by a pipe — add `set -o pipefail`:\n  " + "\n  ".join(offenders)


def test_the_golden_brief_gating_step_is_the_regression():
    """Named explicitly: this is the step #2746 was filed for."""
    wf = yaml.safe_load((_ROOT / ".github" / "workflows" / "golden-brief-eval.yml").read_text())
    steps = wf["jobs"]["golden-brief"]["steps"]
    verdict = [s for s in steps if "Deterministic verdict" in (s.get("name") or "")]
    assert verdict, "the gating step was renamed — re-point this test rather than deleting it"
    assert "pipefail" in verdict[0]["run"], "the step that calls itself 'gating' must be able to fail"


def test_the_guard_would_catch_the_bug_it_was_written_for():
    """A guard that cannot fail is the thing this file exists to prevent, so prove it
    fires on the exact shipped-before shape rather than trusting it."""
    shipped_before = 'echo "::group::x"\npython3 tests/golden_brief_eval.py | tee /tmp/golden.txt\nhead -1 /tmp/golden.txt\n'
    assert gc._GATE_VERB.search(shipped_before), "fixture must look like a gate to the census"
    assert _REAL_PIPE.search(shipped_before), "fixture must contain a real pipe"
    assert "pipefail" not in shipped_before and not _DELIBERATE.search(shipped_before)


def test_a_logical_or_is_not_a_pipe():
    """`python3 -m json.tool x || cat x` is not a swallowed pipeline. Getting this wrong
    reported ci-cd.yml's smoke and canary steps as broken when both end on an unpiped
    `smoke_oracle_decision.py`."""
    assert not _REAL_PIPE.search("python3 -m json.tool /tmp/smoke.json 2>/dev/null || cat /tmp/smoke.json")
