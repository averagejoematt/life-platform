"""tests/test_premerge_extra_files_derivation_2372.py — #2372: the hand-list of
tree-sweeping structural gates becomes a derivation, not a hand count.

#2345 widened `_PREMERGE_EXTRA_FILES` 5 -> 23 by hand-deriving "test files that
sweep the source tree (git ls-files / os.walk) and are not the behaviour suite" —
a one-time grep a human ran and encoded nowhere. #2339, the file that triggered
that widening in the first place, is the demonstrated failure mode: a NEW
tree-sweeping guard lands, nobody remembers to add it, and it runs post-merge-only
until it reds main. Hardcoding a count (23, or any other number, at any point in
time) reproduces the exact defect this file exists to close — the real set drifts
and the number silently stops matching it. This file guards the SET.

Measured against the repo as it stood on #2372's own implementation day: the
`_PREMERGE_EXTRA_FILES` frozenset already held 26 names (not 23 — three more
landed the same day this issue was filed), and the derivation below found 36
non-behaviour files that sweep the source tree, only 17 of which were already
named. Every one of the other 19 is classified in this same PR: 18 into
`_PREMERGE_EXTRA_FILES` (they measure as cheap, deterministic, repo-shape
ratchets) and one, `test_diary_publish_1845.py`, into `_PREMERGE_TREE_SWEEP_
EXCLUDED` (a behaviour suite in substance — #2345 already made that exact call in
prose; this makes it a checked fact).
"""

from __future__ import annotations

import tests.conftest as conftest
from tests.premerge_derivation import TESTS_DIR, discover_tree_sweeping_test_files


def test_every_tree_sweeping_file_is_classified():
    """Every non-behaviour test_*.py file that sweeps the source tree must be named
    in `_PREMERGE_EXTRA_FILES` (runs pre-merge) or `_PREMERGE_TREE_SWEEP_EXCLUDED`
    (deliberately does not, with a reason). A file in neither is the #2339 failure
    mode happening again: nobody decided, and it silently ran post-merge-only."""
    derived = discover_tree_sweeping_test_files()
    classified = conftest._PREMERGE_EXTRA_FILES | set(conftest._PREMERGE_TREE_SWEEP_EXCLUDED)
    unclassified = sorted(derived - classified)
    assert not unclassified, (
        f"{unclassified} sweep the source tree (os.walk/.rglob/git ls-files) but are named in "
        "neither tests/conftest.py's _PREMERGE_EXTRA_FILES nor _PREMERGE_TREE_SWEEP_EXCLUDED. "
        "Add each to _PREMERGE_EXTRA_FILES (it belongs in the pre-merge lane) or to "
        "_PREMERGE_TREE_SWEEP_EXCLUDED with a one-line reason (a behaviour suite in substance, "
        "not a repo-shape ratchet) — #2372."
    )


def test_the_exclusion_set_does_not_overlap_the_premerge_set():
    """A file cannot be simultaneously 'runs pre-merge' and 'deliberately does
    not' — that would just be silent dead configuration in one of the two sets."""
    overlap = sorted(set(conftest._PREMERGE_TREE_SWEEP_EXCLUDED) & conftest._PREMERGE_EXTRA_FILES)
    assert not overlap, f"{overlap} is in both _PREMERGE_EXTRA_FILES and _PREMERGE_TREE_SWEEP_EXCLUDED — pick one"


def test_every_exclusion_carries_a_real_reason():
    empty = sorted(name for name, reason in conftest._PREMERGE_TREE_SWEEP_EXCLUDED.items() if not reason or not reason.strip())
    assert not empty, f"{empty} is excluded from the pre-merge lane with no stated reason"


def test_exclusion_set_only_names_files_that_exist():
    missing = sorted(name for name in conftest._PREMERGE_TREE_SWEEP_EXCLUDED if not (TESTS_DIR / name).is_file())
    assert not missing, f"_PREMERGE_TREE_SWEEP_EXCLUDED names file(s) that do not exist: {missing} — repoint or drop the entry"


# ══════════════════════════════════════════════════════════════════════════════
# Mutation proof — the derivation itself must actually detect a real sweep, not
# just replay a fixed list under a new name (#2372's acceptance criterion).
# ══════════════════════════════════════════════════════════════════════════════


def test_a_synthetic_tree_sweeping_file_is_flagged(tmp_path):
    """Write a file that DOES sweep a tree and one that does NOT into an isolated
    directory, and confirm the derivation catches only the former, and excludes
    the behaviour suite even when it sweeps. Proves this is a real detector, not
    decoration."""
    sweeper = tmp_path / "test_synthetic_sweep_2372.py"
    sweeper.write_text(
        "import os\n\n" "def test_walks_lambdas():\n" "    for _root, _dirs, _files in os.walk('lambdas'):\n" "        pass\n",
        encoding="utf-8",
    )
    non_sweeper = tmp_path / "test_synthetic_plain_2372.py"
    non_sweeper.write_text("def test_arithmetic():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    behaviour = tmp_path / "test_synthetic_2372_behavior.py"
    behaviour.write_text(
        "import os\n\n" "def test_walks_lambdas():\n" "    for _root, _dirs, _files in os.walk('lambdas'):\n" "        pass\n",
        encoding="utf-8",
    )

    derived = discover_tree_sweeping_test_files(root=tmp_path)

    assert sweeper.name in derived, "the derivation missed a plain os.walk( sweep — it cannot be trusted to catch the next #2339"
    assert non_sweeper.name not in derived, "the derivation flagged a file with no tree sweep at all"
    assert behaviour.name not in derived, "the derivation must exclude the *_behavior.py suite — that is covered by the OTHER marker"


def test_an_unregistered_synthetic_sweeper_would_fail_the_classification_gate():
    """End-to-end mutation proof: simulate the #2339 shape — a new tree-sweeping
    file lands, unregistered — against the REAL classified sets, and confirm it
    would red test_every_tree_sweeping_file_is_classified above. This is #2372's
    'adding a synthetic tree-sweeping test file without registering it reds the
    derivation test' acceptance criterion, made executable rather than asserted."""
    real = discover_tree_sweeping_test_files()
    classified = conftest._PREMERGE_EXTRA_FILES | set(conftest._PREMERGE_TREE_SWEEP_EXCLUDED)
    synthetic_name = "test_synthetic_unregistered_sweep_2372.py"
    assert synthetic_name not in classified, "the synthetic name collided with a real entry — pick a different one"

    simulated = real | {synthetic_name}
    unclassified = sorted(simulated - classified)
    assert unclassified == [synthetic_name], (
        "adding one unregistered tree-sweeping filename to the derived set should red the "
        "classification gate on exactly, and only, that filename"
    )
