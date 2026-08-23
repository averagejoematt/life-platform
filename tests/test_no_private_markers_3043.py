"""#3043 (DIL-001) — the no-PRIVATE-marker structural guard.

The repo is deliberately PUBLIC (since 2026-07-20). Five docs under
`docs/coaching/` carried an in-band owner-privacy marker (`**Status:** PRIVATE /
internal`, `**Privacy tier:** PRIVATE`) *while being world-readable* — the marker
documented an intent no control enforced. The 2026-08-23 diligence review (DIL-001)
graded that P0. The fix relocates the marked files to the S3 owner prefix
(`s3://matthew-life-platform/config/coaching/`); this guard makes the CLASS
structural: no tracked file may declare itself PRIVATE, because a tracked file in a
public repo cannot be private — the marker itself is the contradiction.

Guard choice mirrors tests/test_no_tool_attribution_3005.py: a TEST, not a hook —
it runs in every lane including the pre-merge full suite and mutation-proves at the
predicate level (CONVENTIONS §9).

Marker family (per the five real instances, all uppercase PRIVATE on a bolded
doc-status header line):
  > **Status:** PRIVATE / internal. ...
  > **Privacy tier:** PRIVATE. ...
plus the unbolded `Status: PRIVATE` header form at line start.

Deliberately NOT matched (verified benign forms in the tree):
  - `**Privacy:** PRIVATE — nothing in BENCH-1 may surface...` (DECISIONS.md ADR
    line describing a FEATURE's runtime posture, not marking the doc itself)
  - `**Status:** ✅ Active — ... (Phase 1; private)` (lowercase prose aside)
  - `lands in PRIVATE S3`, `PRIVATE cut-benchmarking` (prose mentions)
  - the diligence register's backticked evidence quote (table row, not a header)
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Files allowed to contain a matching line because they STATE the rule.
ALLOWLIST = {
    "tests/test_no_private_markers_3043.py",  # this guard's own fixtures
}

# Bolded doc-status header marking the file itself PRIVATE. PRIVATE is
# case-sensitive on purpose: every real marker is uppercase, and prose asides
# ("Phase 1; private") must not trip the guard. The value window is [^*\n]* —
# PRIVATE must sit in the header's OWN value, before any next bold segment, so an
# ADR line like `**Status:** Implemented ... **Privacy:** PRIVATE` (feature
# posture, not a doc marker) stays benign.
_BOLD_MARKER = re.compile(r"^\s*>?\s*\*\*(?:Status|Privacy tier)\s*:\*\*[^*\n]*\bPRIVATE\b", re.MULTILINE)
# Unbolded header form at line start (same family, plain-text docs).
_PLAIN_MARKER = re.compile(r"^\s*>?\s*(?:Status|Privacy tier)\s*:\s*PRIVATE\b", re.MULTILINE)

_TEXT_SUFFIXES = {".md", ".py", ".sh", ".yml", ".yaml", ".txt", ".json", ".toml", ".cfg", ".ini", ".js", ".css", ".html"}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout


def file_carries_private_marker(text: str) -> bool:
    """True when file content declares itself PRIVATE via the marker family."""
    return bool(_BOLD_MARKER.search(text) or _PLAIN_MARKER.search(text))


def test_predicates_fire_on_planted_positives():
    # Mutation proof (CONVENTIONS §9): the guard must be able to fail.
    assert file_carries_private_marker("# Doc\n\n> **Status:** PRIVATE / internal. Do not surface.\n")
    assert file_carries_private_marker("> **Privacy tier:** PRIVATE. Nothing here may surface.\n")
    assert file_carries_private_marker("Status: PRIVATE / internal\nbody\n")
    assert file_carries_private_marker("  Privacy tier: PRIVATE\n")


def test_predicates_pass_benign_content():
    # An ADR line describing a FEATURE's privacy posture is not a doc marker.
    assert not file_carries_private_marker("**Privacy:** PRIVATE — nothing in BENCH-1 may surface publicly.\n")
    # A Status header whose own value is benign, with a feature-posture PRIVATE
    # later on the same line (the real DECISIONS.md ADR-089 shape).
    assert not file_carries_private_marker(
        "**Status:** Implemented (shipped). **Related:** `x.py`. **Privacy:** PRIVATE — never surfaces.\n"
    )
    # Lowercase prose aside on a status line.
    assert not file_carries_private_marker("**Status:** ✅ Active — 2026-06-21 (Phase 1; private)\n")
    # Prose mentions of private surfaces.
    assert not file_carries_private_marker("the brief lands in PRIVATE S3 (`raw/matthew/interviews/`)\n")
    assert not file_carries_private_marker("PRIVATE cut-benchmarking & regain firewall\n")
    # The register's backticked evidence quote inside a table row.
    assert not file_carries_private_marker("| 001 | Public Tier-2 docs | 5 `Status: PRIVATE / internal` files under `docs/coaching/` |\n")


def test_no_tracked_file_carries_private_marker():
    try:
        tracked = _git("ls-files").splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("not a git checkout")
    offenders = []
    for rel in tracked:
        if rel in ALLOWLIST or Path(rel).suffix not in _TEXT_SUFFIXES:
            continue
        path = REPO_ROOT / rel
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if file_carries_private_marker(text):
            offenders.append(rel)
    assert not offenders, (
        f"tracked files declare themselves PRIVATE in a public repo: {offenders} — "
        "a tracked file cannot be private (DIL-001, #3043); owner-private material "
        "belongs at the S3 owner prefix s3://matthew-life-platform/config/coaching/ "
        "(see docs/coaching/README.md)"
    )
