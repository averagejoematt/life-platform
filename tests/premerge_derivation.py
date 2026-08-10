"""tests/premerge_derivation.py — #2372: mechanically find tree-sweeping test files.

`_PREMERGE_EXTRA_FILES` (tests/conftest.py) is the pre-merge lane's structural-gate
list — "test files that sweep the source tree (git ls-files / os.walk) and are not
the behaviour suite," per #2345's commit message, which is exactly how that list's
initial 23 names were found: a human ran the grep once, by hand, and the result was
encoded nowhere. Hours later #2339 red-mained main on a tree-sweeping guard the hand
survey had missed. The 24th would have done the same.

This module is that grep, made permanent and importable. `discover_tree_sweeping_
test_files()` returns the basenames of every non-behaviour `tests/test_*.py` file
whose source text sweeps a directory tree: `os.walk(`, `Path.rglob(`, or a
`git ls-files` shell-out — the two idioms #2345 named plus `rglob`, which every
dated SET guard added since (`test_time_invariant_helpers_1964`,
`test_wallclock_globals_2223`, `test_coach_roster_set_guard_2334`, ...) uses as the
Path-based equivalent of `os.walk`.

This is a SYNTACTIC signal, not a semantic one. Matching it means "this file's
population of covered files can change size without anyone editing this file" — a
structural ratchet's defining property — not "this file belongs in the pre-merge
lane." A file can match and still be a behaviour suite in substance (the exact
reasoning #2345 gave, in prose, for leaving `test_output_writers.py` and
`test_diary_publish_1845.py` out). `tests/conftest.py`'s `_PREMERGE_TREE_SWEEP_
EXCLUDED` makes that a maintained, checked dict instead of a comment nobody re-reads.

`tests/test_premerge_extra_files_derivation_2372.py` is the guard: every name this
function returns must appear in `_PREMERGE_EXTRA_FILES` (runs pre-merge) or
`_PREMERGE_TREE_SWEEP_EXCLUDED` (deliberately does not, with a reason) — never in
neither. It enforces CLASSIFICATION, not lane membership, so it cannot force any
particular file into the fast lane; it can only force someone to decide, in the
same PR that adds the file, instead of after main goes red.
"""

from __future__ import annotations

import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

# The behaviour suite has its own derivation (tests/conftest.py's
# _PREMERGE_FILENAME_SUFFIX) and is already fully pre-merge — it is excluded here
# so the two derivations partition the tree instead of overlapping.
_BEHAVIOR_SUFFIX = "_behavior.py"

# The three idioms: os.walk(...), <Path>.rglob(...), and a `git ls-files` shell-out
# (matched on the literal flag text, which survives however the subprocess call is
# spelled — list, string, with/without extra args).
_SWEEP_PATTERN = re.compile(r"os\.walk\(|\.rglob\(|ls-files")


def discover_tree_sweeping_test_files(root: Path | None = None) -> set[str]:
    """Return the basenames of every `test_*.py` file under `root` (default: this
    directory) that sweeps a directory tree, excluding the `*_behavior.py` suite.

    `root` is overridable so the derivation itself can be tested against a
    synthetic, isolated directory rather than only ever running against the real
    tree — see tests/test_premerge_extra_files_derivation_2372.py's mutation proof.
    """
    scan_root = root if root is not None else TESTS_DIR
    found: set[str] = set()
    for path in sorted(scan_root.glob("test_*.py")):
        if path.name.endswith(_BEHAVIOR_SUFFIX):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if _SWEEP_PATTERN.search(text):
            found.add(path.name)
    return found
