"""tests/test_ci_pin_consistency.py — CQ-01: dev tooling pins must match the CI gate.

The enforced format/lint/visual-QA gates run in ci-cd.yml with hardcoded versions.
requirements-dev.txt must pin the SAME versions, or local `make format` / `pytest`
can pass while the build fails (or vice-versa) — the exact drift AUDIT CQ-01 found
(black 26.5.1 local vs 25.9.0 CI). This test is the single-source guard.
"""

import os
import re

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CI = os.path.join(_REPO, ".github", "workflows", "ci-cd.yml")
_REQ = os.path.join(_REPO, "requirements-dev.txt")

# Tools whose versions are BOTH pinned in ci-cd.yml and installed for local dev.
_GATED_TOOLS = ("black", "ruff", "playwright")


def _versions(path, tool):
    """Every '<tool>==<version>' pin found in a file, as a set."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return set(re.findall(rf"\b{tool}==([0-9][0-9A-Za-z.\-]*)", text))


def test_dev_pins_match_ci_gate():
    mismatches = []
    for tool in _GATED_TOOLS:
        ci = _versions(_CI, tool)
        dev = _versions(_REQ, tool)
        assert ci, f"{tool} not pinned in ci-cd.yml — update this test's expectations"
        assert dev, f"{tool} not pinned in requirements-dev.txt"
        # Every dev pin must be a version CI actually installs (usually exactly one each).
        if not dev <= ci:
            mismatches.append(f"{tool}: requirements-dev={sorted(dev)} vs ci-cd.yml={sorted(ci)}")
    assert not mismatches, "dev tooling pins drifted from the enforced CI gate (CQ-01):\n" + "\n".join(mismatches)
