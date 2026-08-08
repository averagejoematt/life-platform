"""tests/test_ci_pin_consistency.py — CQ-01: dev tooling pins must match the CI gate.

The enforced format/lint/test gates run across ci-cd.yml/ci-lint.yml/ci-test.yml with
hardcoded versions. requirements-dev.txt must pin the SAME versions, or local
`make format` / `pytest` can pass while the build fails (or vice-versa) — the exact
drift AUDIT CQ-01 found (black 26.5.1 local vs 25.9.0 CI). This test is the
single-source guard.

Extended #1963: the original guard only covered black/ruff/playwright — mypy,
hypothesis, pytest, pytest-cov, boto3, and botocore had all drifted (mypy 2.1.0 CI
vs 2.3.0 dev; hypothesis 6.161.2 vs 6.163.0; pytest/pytest-cov/boto3/botocore
entirely unpinned in ci-test.yml/ci-cd.yml) with nothing to catch it. Both the
literal drift and the guard's blind spot are fixed here.

Extended #2058: pr-checks.yml (advisory pre-merge lane) and fresh-eyes.yml
(scheduled discovery workflow) pin hypothesis/boto3 too but sat outside
_CI_FILES, so they could drift indefinitely with no signal — the exact
"outside the guard's scope, not beyond its capability" shape #1963 named.
Folding them in also forced a strictness fix: the old subset check (every dev
pin must appear SOMEWHERE in the combined CI text) would have stayed green
even with pr-checks.yml/fresh-eyes.yml's stale pins in the mix, because
ci-cd.yml/ci-test.yml already carry the correct version — a stale pin can hide
behind a correct one from another file. The check is now exact-set equality
per tool across the whole _CI_FILES surface.
"""

import os
import re
import subprocess

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The enforced tool pins live across the orchestrator + the reusable lint/test
# workflows since #1655 split ci-cd.yml (black/ruff moved to ci-lint.yml), plus the
# two advisory/scheduled workflows that install the same tools independently
# (#2058: pr-checks.yml, fresh-eyes.yml — previously outside this guard's scope).
# Read the whole surface so the drift-guard follows the literal wherever it lives.
_CI_FILES = [
    os.path.join(_REPO, ".github", "workflows", f) for f in ("ci-cd.yml", "ci-lint.yml", "ci-test.yml", "pr-checks.yml", "fresh-eyes.yml")
]
_CI = _CI_FILES[0]  # kept for messages/back-compat
_REQ = os.path.join(_REPO, "requirements-dev.txt")


def _ci_gate_text():
    parts = []
    for p in _CI_FILES:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                parts.append(f.read())
    return "\n".join(parts)


# Tools whose versions are BOTH pinned in the CI gate (ci-cd/ci-lint/ci-test.yml) and
# installed for local dev. Extended #1963 to add mypy/hypothesis/pytest/pytest-cov/
# boto3/botocore. Kept as a literal tuple for readability, but
# test_gated_tools_matches_requirements_dev_pins below DERIVES the expected
# membership from requirements-dev.txt itself, so a future Dependabot-managed pin
# can't silently land outside this guard's coverage again (guard the SET, not the
# instance).
_GATED_TOOLS = ("black", "ruff", "mypy", "playwright", "hypothesis", "pytest", "pytest-cov", "boto3", "botocore", "pyyaml")

# requirements-dev.txt pins deliberately OUTSIDE this guard's coverage, each with why:
_UNGATED_DEV_PINS = {
    # ci-lint.yml installs flake8 unpinned ("pip install flake8") — a pre-existing
    # gap #1963 did not scope in; tracked separately from this guard.
    "flake8",
    # The CDK toolchain is pinned bidirectionally by its OWN convention
    # (cdk/requirements.txt <-> ci-cd.yml's `npm install -g aws-cdk@X`, #814,
    # R22-MOD-01) — a CLI-install shape, not this guard's `pip install tool==`
    # pattern, so it doesn't fit _pin_mismatches below.
    "aws-cdk-lib",
    "constructs",
}


def _versions(path, tool):
    """Every '<tool>==<version>' pin found in a file, as a set."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return set(re.findall(rf"\b{tool}==([0-9][0-9A-Za-z.\-]*)", text))


def _pin_mismatches(ci_text, tools):
    """Every tool in `tools` whose requirements-dev.txt pin isn't among the
    versions `ci_text` installs. Factored out of test_dev_pins_match_ci_gate so a
    synthetic ci_text can prove the guard actually fires (see the prove-red test
    below) without editing real workflow files."""
    mismatches = []
    for tool in tools:
        ci = set(re.findall(rf"\b{tool}==([0-9][0-9A-Za-z.\-]*)", ci_text))
        dev = _versions(_REQ, tool)
        assert ci, f"{tool} not pinned in the CI gate ({', '.join(os.path.basename(p) for p in _CI_FILES)})"
        assert dev, f"{tool} not pinned in requirements-dev.txt"
        # Exact equality, not just "every dev pin appears somewhere in ci" (#2058):
        # a subset check lets a stale pin in one file hide behind a correct pin in
        # another — the exact gap that would have let pr-checks.yml's stale
        # hypothesis==6.161.2 and fresh-eyes.yml's stale boto3==1.43.41 stay
        # invisible even after folding those files into _CI_FILES, since
        # ci-cd.yml/ci-test.yml already carry the right version.
        if dev != ci:
            mismatches.append(f"{tool}: requirements-dev={sorted(dev)} vs ci-gate={sorted(ci)}")
    return mismatches


def _requirements_dev_pinned_tools():
    """Every top-level `name==version` pin in requirements-dev.txt, as tool names."""
    with open(_REQ, encoding="utf-8") as f:
        text = f.read()
    return set(re.findall(r"^([A-Za-z][A-Za-z0-9_.\-]*)==[0-9]", text, re.MULTILINE))


def test_gated_tools_matches_requirements_dev_pins():
    """Guard the SET, not the instance (#1963): every requirements-dev.txt pin not
    on the documented _UNGATED_DEV_PINS exception list must be covered by
    _GATED_TOOLS — a tool Dependabot bumps in requirements-dev.txt can't silently
    sit outside this guard's coverage the way mypy/hypothesis/pytest did."""
    expected = _requirements_dev_pinned_tools() - _UNGATED_DEV_PINS
    actual = set(_GATED_TOOLS)
    assert expected == actual, (
        "requirements-dev.txt pins and _GATED_TOOLS have diverged — add the new tool to "
        "_GATED_TOOLS, or to _UNGATED_DEV_PINS with a rationale if it's deliberately out of "
        f"scope: missing from _GATED_TOOLS={sorted(expected - actual)}, "
        f"stale in _GATED_TOOLS={sorted(actual - expected)}"
    )


def test_guard_fires_on_synthetic_divergence_for_a_newly_covered_tool():
    """Prove-red (#1963 acceptance): the extended guard must actually FIRE on a
    version mismatch for one of the newly-covered tools, not just the original
    black/ruff/playwright set. Reproduces the exact #1963 drift class — CI pinned
    to a stale mypy version while requirements-dev.txt moved on — via synthetic CI
    text, so this stays true even after the real files are reconciled."""
    assert "mypy" in _GATED_TOOLS, "mypy must be a newly-covered tool for this regression proof to be meaningful"
    real_mypy_pin = _versions(_REQ, "mypy")
    assert real_mypy_pin, "requirements-dev.txt must pin mypy for this test to be meaningful"
    synthetic_ci_text = "pip install mypy==0.0.1-synthetic-stale-pin"
    mismatches = _pin_mismatches(synthetic_ci_text, ("mypy",))
    assert mismatches, "the pin-parity guard failed to fire on a synthetic mypy divergence — regression"
    assert mismatches[0].startswith("mypy:")


# --- Doc-command truth (#2006) -------------------------------------------------
# CONVENTIONS §4 tells the operator to DISCOVER the pins by running a grep rather
# than trusting a quoted number. #1655 moved the lint pins from ci-cd.yml to
# ci-lint.yml without updating that command, so the doc's grep silently showed only
# the requirements-dev.txt half — the exact half the doc says not to trust. These
# tests extract the grep commands verbatim from the doc and run them, so the doc
# and the file layout can't drift apart again without a red.

_DOC = os.path.join(_REPO, "docs", "CONVENTIONS.md")


def _doc_pin_commands():
    """Every backticked `grep -E '…=…' <files>` pin-discovery command in CONVENTIONS.md.

    Derived from the doc, not enumerated here (guard the set, not the instance):
    returns [(pattern, full_command), ...] with wrapped lines re-joined.
    """
    with open(_DOC, encoding="utf-8") as f:
        text = f.read()
    cmds = []
    for m in re.finditer(r"`(grep -E '([^']*==[^']*)'[^`]*)`", text):
        cmd = " ".join(m.group(1).split())  # doc wraps long commands across lines
        cmds.append((m.group(2), cmd))
    return cmds


def test_doc_pin_discovery_commands_are_extractable():
    cmds = _doc_pin_commands()
    patterns = [p for p, _ in cmds]
    assert any("mypy==" in p for p in patterns), "CONVENTIONS.md §4 lost its black/ruff/mypy pin-discovery grep"
    assert any("aws-cdk" in p for p in patterns), "CONVENTIONS.md §4 lost its CDK pin-discovery grep"


def test_doc_pin_discovery_commands_surface_every_promised_pin():
    """Each documented grep must run clean AND surface every alternation it promises."""
    for pattern, cmd in _doc_pin_commands():
        proc = subprocess.run(cmd, shell=True, cwd=_REPO, capture_output=True, text=True)  # noqa: S602 repo-authored doc command
        assert proc.returncode == 0, f"documented pin-discovery command failed (rc={proc.returncode}): {cmd}\n{proc.stderr}"
        for token in pattern.split("|"):
            assert token in proc.stdout, f"documented command no longer surfaces '{token}': {cmd}"


def test_doc_lint_pin_grep_surfaces_the_ci_side():
    """The #2006 blindness class: the lint-tool grep must show the pins from a
    workflow file, not just requirements-dev.txt — 'read the CI pin' must be
    executable, not archaeology."""
    lint_cmds = [(p, c) for p, c in _doc_pin_commands() if "mypy==" in p]
    assert lint_cmds, "no black/ruff/mypy pin-discovery command found in CONVENTIONS.md"
    for pattern, cmd in lint_cmds:
        proc = subprocess.run(cmd, shell=True, cwd=_REPO, capture_output=True, text=True)  # noqa: S602 repo-authored doc command
        assert proc.returncode == 0, f"documented pin-discovery command failed: {cmd}\n{proc.stderr}"
        workflow_lines = [ln for ln in proc.stdout.splitlines() if ".github/workflows/" in ln]
        for tool in ("black==", "ruff==", "mypy=="):
            assert any(tool in ln for ln in workflow_lines), (
                f"'{tool[:-2]}' CI pin not surfaced from .github/workflows/ by the documented command — "
                f"the doc's grep is blinded again (#2006 regression): {cmd}"
            )


def test_dev_pins_match_ci_gate():
    mismatches = _pin_mismatches(_ci_gate_text(), _GATED_TOOLS)
    assert not mismatches, "dev tooling pins drifted from the enforced CI gate (CQ-01):\n" + "\n".join(mismatches)
