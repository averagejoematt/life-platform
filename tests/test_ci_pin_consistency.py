"""tests/test_ci_pin_consistency.py — CQ-01: dev tooling pins must match the CI gate.

The enforced format/lint/visual-QA gates run in ci-cd.yml with hardcoded versions.
requirements-dev.txt must pin the SAME versions, or local `make format` / `pytest`
can pass while the build fails (or vice-versa) — the exact drift AUDIT CQ-01 found
(black 26.5.1 local vs 25.9.0 CI). This test is the single-source guard.
"""

import os
import re
import subprocess

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The enforced tool pins live across the orchestrator + the reusable lint/test
# workflows since #1655 split ci-cd.yml (black/ruff moved to ci-lint.yml). Read the
# whole CI gate surface so the drift-guard follows the literal wherever it lives.
_CI_FILES = [os.path.join(_REPO, ".github", "workflows", f) for f in ("ci-cd.yml", "ci-lint.yml", "ci-test.yml")]
_CI = _CI_FILES[0]  # kept for messages/back-compat
_REQ = os.path.join(_REPO, "requirements-dev.txt")


def _ci_gate_text():
    parts = []
    for p in _CI_FILES:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                parts.append(f.read())
    return "\n".join(parts)


# Tools whose versions are BOTH pinned in ci-cd.yml and installed for local dev.
_GATED_TOOLS = ("black", "ruff", "playwright")


def _versions(path, tool):
    """Every '<tool>==<version>' pin found in a file, as a set."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return set(re.findall(rf"\b{tool}==([0-9][0-9A-Za-z.\-]*)", text))


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
    mismatches = []
    ci_text = _ci_gate_text()
    for tool in _GATED_TOOLS:
        ci = set(re.findall(rf"\b{tool}==([0-9][0-9A-Za-z.\-]*)", ci_text))
        dev = _versions(_REQ, tool)
        assert ci, f"{tool} not pinned in the CI gate (ci-cd/ci-lint/ci-test.yml) — update this test's expectations"
        assert dev, f"{tool} not pinned in requirements-dev.txt"
        # Every dev pin must be a version CI actually installs (usually exactly one each).
        if not dev <= ci:
            mismatches.append(f"{tool}: requirements-dev={sorted(dev)} vs ci-cd.yml={sorted(ci)}")
    assert not mismatches, "dev tooling pins drifted from the enforced CI gate (CQ-01):\n" + "\n".join(mismatches)
