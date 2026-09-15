#!/usr/bin/env python3
"""tests/test_suite_parallel_safety_3025.py — the pre-merge full suite runs in parallel,
and stays able to (#3025's duration class, 8th instance and first structural answer).

WHY THIS EXISTS. The full-suite duration budget has been breached and answered seven
times — #1349, #1966, #2152, #3025, #3106, #3224, #3265 — and every answer raised the
number or de-duplicated a whole-repo scan. The suite itself never stopped being one
process. Measured 2026-09-15 on this checkout, 1,134 files / ~26k tests:

    serial               ~1,590s   (33% at 525s, extrapolated; CI's 4 vCPU reads 2,500-2,850s)
    -n auto --dist loadfile  411s   (12 workers, WHILE the serial baseline was competing for CPU)

`--dist loadfile` is what makes this cheap: a file's tests all land on one worker, so
every intra-file ordering assumption in the suite is preserved for free. Only CROSS-file
shared state can race.

THE ONE CROSS-FILE HAZARD, AND THE RULE IT BOUGHT. The suite has exactly one kind of
genuinely shared mutable state: **the checkout itself**. Dozens of tests walk `lambdas/`
or the repo tree with `rglob`, so a test that plants a file in that tree — even inside a
`TemporaryDirectory` — makes every one of those sweeps racy. It fired on the first
parallel run:

    FileNotFoundError: .../lambdas/tmp5hs17jmd/probe_handler.py
      tests/test_gradability_liveness_cross_phase_2023.py::test_every_raw_source_phase_filtered_read_is_classified
      tests/test_doc_facts_budget_2899.py::test_live_tree_states_no_retired_ceiling_after_the_window_reverts

Both pass serially. The writer was `test_rate_limit_identity_1221.py`'s must-fail probe,
planting a handler inside `lambdas/` to prove its own AST walk could see one. It is
fixed at the source (the walk takes a `tree_root`; the probe points it at a private temp
dir) rather than by serialising the two readers — a reader-side fix would have left the
next probe free to reintroduce it.

So the rule this file ratchets: **no test plants a file inside the checkout.** That is
the property, and it is checked against source, not against a memory of the incident.
"""

import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PR_CHECKS = os.path.join(REPO, ".github", "workflows", "pr-checks.yml")

# Idioms that place a temp file or directory at a CALLER-CHOSEN location. `dir=` is the
# whole tell: `TemporaryDirectory()` with no `dir=` lands in the OS temp area, which no
# sweep in this suite walks.
_PLANTS_IN_A_CHOSEN_DIR = re.compile(r"\b(?:TemporaryDirectory|NamedTemporaryFile|mkdtemp|mkstemp)\(\s*[^)]*\bdir\s*=")
# A `dir=` argument is only a hazard when it resolves INSIDE the checkout. These are the
# names this suite uses for the checkout root; `tmp_path` and friends are pytest's own
# per-test directories and are outside it.
_REPO_ROOTED = re.compile(r"\b(_REPO|REPO|REPO_ROOT|ROOT|_ROOT|PROJECT_ROOT|HERE|_HERE)\b")

# Sanctioned exceptions. Empty, deliberately: a test that must mutate the checkout has
# to justify itself here AND be given a way to not race, which is a design conversation,
# not a default. Adding a name to this set without both is the thing this file exists to
# make visible.
_SANCTIONED_IN_TREE_WRITERS: set = set()


def _in_tree_planters():
    """(file, line, source) for every test that plants a path inside the checkout."""
    hits = []
    for name in sorted(os.listdir(HERE)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(HERE, name), encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if _PLANTS_IN_A_CHOSEN_DIR.search(line) and _REPO_ROOTED.search(line):
                    hits.append((name, lineno, line.strip()))
    return hits


def test_no_test_plants_a_file_inside_the_checkout():
    """The property. Every whole-tree sweep in this suite races against a violation."""
    offenders = [h for h in _in_tree_planters() if h[0] not in _SANCTIONED_IN_TREE_WRITERS]
    assert (
        not offenders
    ), "these plant a path inside the checkout, which races every rglob sweep under " "`pytest -n auto` (#3025):\n  " + "\n  ".join(
        f"{f}:{n}: {src}" for f, n, src in offenders
    )


def test_the_scan_can_actually_fail():
    """A guard that cannot fail is not a guard. The detector must flag the exact line
    that caused the 2026-09-15 incident, reconstructed verbatim."""
    # Assembled, not written literally: the detector scans THIS file too (no
    # self-exemption, so a planter added here would still be caught), and a verbatim
    # copy of the culprit would make the guard flag its own proof.
    kw = "dir"
    culprit = f'    with tempfile.TemporaryDirectory({kw}=os.path.join(_REPO, "lambdas")) as d:'
    assert _PLANTS_IN_A_CHOSEN_DIR.search(culprit) and _REPO_ROOTED.search(culprit)
    # ...and must NOT flag the shapes that are fine.
    for safe in (
        "    with tempfile.TemporaryDirectory() as d:",
        "    p = tmp_path / 'deploy' / 'writer.py'",
        "    with tempfile.NamedTemporaryFile(suffix='.json') as fh:",
    ):
        assert not (_PLANTS_IN_A_CHOSEN_DIR.search(safe) and _REPO_ROOTED.search(safe)), safe


def _full_suite_pytest_line():
    with open(PR_CHECKS, encoding="utf-8") as fh:
        src = fh.read()
    block = src[src.index("  full-suite:") :]
    m = re.search(r"run:\s*(python3 -m pytest[^\n]*)", block)
    assert m, "pr-checks.yml full-suite job no longer runs a single-line pytest command"
    return m.group(1)


def test_the_full_suite_still_runs_in_parallel():
    """The parallelism is the answer to the duration class; losing it silently would
    put the suite back to one process with the budget already raised to fit it."""
    line = _full_suite_pytest_line()
    assert "-n auto" in line, f"the pre-merge full suite is no longer parallel: {line}"
    assert "--dist loadfile" in line, (
        "`--dist loadfile` is load-bearing, not decoration: it is what keeps a file's "
        f"tests on one worker, so intra-file ordering assumptions stay true. {line}"
    )


def test_xdist_is_pinned_and_installed_by_the_lane_that_uses_it():
    """A `-n auto` that silently degrades because the plugin is absent is a suite that
    got slower with no signal — pytest simply rejects the flag, so the JOB fails, which
    is the honest direction. The pin and the install must still be asserted together."""
    with open(os.path.join(REPO, "requirements-dev.txt"), encoding="utf-8") as fh:
        assert re.search(r"^pytest-xdist==\d+\.\d+\.\d+$", fh.read(), re.M), "pytest-xdist is not pinned in requirements-dev.txt"
    with open(PR_CHECKS, encoding="utf-8") as fh:
        block = fh.read()
    block = block[block.index("  full-suite:") :]
    m = re.search(r"ci_pins\.py ([^\)\n]+)", block)
    assert m and "pytest-xdist" in m.group(1).split(), "the full-suite lane does not install pytest-xdist"
