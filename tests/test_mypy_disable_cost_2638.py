"""#2638 — the mypy disable list is retained with its cost measured, not implied-absent.

`mypy.ini` globally disables four error codes: `assignment`, `arg-type`, `return-value`,
`operator`. #2578's verdict slice mutation-proved the gate CAN fail — on `name-defined` and
`attr-defined` — and that a function returning the wrong type (`return-value`) passes it
**silently** across the clean set. So "mypy passed" means a narrower thing than it reads as.

The tracker said otherwise. **#1656 — "mypy strict-clean globally (empty the disable list)"
— is CLOSED, with the list non-empty**, while `tests/mypy_clean_set.py` still described that
work as "the OTHER #1656 axis, still open". The code knew; the tracker did not. That is the
#2578 defect class at tracker level: a thing that reads as done and is not.

WHAT WAS MISSING TO UN-STICK IT WAS A NUMBER, and the issue says so — "measure before
deciding; `return-value` alone across 435 files may be small or enormous, and that number is
the decision." Measured over the set the gate ACTUALLY RUNS (436 clean-set files, not the
whole tree that `mypy.ini`'s pre-existing counts describe):

    return-value    32 errors in  11 files   <- cheapest tranche, and the proven-silent one
    operator        38 errors in  14 files
    arg-type        60 errors in  41 files
    assignment     285 errors in 144 files
    TOTAL          415

415 is a tranche, not a flag flip — which is exactly what the measurement was for. So this
change does the part that can be done honestly tonight: it measures, records the numbers
where the decision gets made, moves the residual to an owner that is open, and says plainly
that the gate's name overclaims. **Boxes 2 and 3 — enable tier by tier, mutation-prove each
newly-enabled code — are deliberately NOT done here**, because `mypy.ini`'s own comment is
right that fixing `operator`/`return-value` means correcting latent-Optional signatures on
the scoring path, and that is behaviour-adjacent surgery belonging in its own reviewable PR.

THE MEASUREMENT TRAP, pinned below because it produced a confident wrong answer first.
Passing 436 filenames on the command line overflows the shell's argument limit, mypy aborts
with "File name too long", and a naive `grep -c '[code]'` over that output returns **0** —
a clean, plausible "this code costs nothing to enable". All four codes measured as zero
before the response file went in. `measure()` now raises when mypy gives no summary line,
so a count that cannot be justified is an error rather than a zero.
"""

from __future__ import annotations

import importlib
import os
import pathlib
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "scripts"), os.path.join(_REPO, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

cost = importlib.import_module("mypy_disable_cost")

MYPY_INI = (pathlib.Path(_REPO) / "mypy.ini").read_text()
CLEAN_SET_DOC = (pathlib.Path(_REPO) / "tests" / "mypy_clean_set.py").read_text()


# ── the residual has an owner that is actually open ──────────────────────────


def test_the_scope_note_points_at_an_open_issue_not_a_closed_one():
    """Acceptance box 4. A reader seeing a closed 'empty the disable list' issue reasonably
    concludes the list is empty."""
    note = CLEAN_SET_DOC.split("Scope note")[1][:900]
    assert "#2638" in note, "the scope note still has no open owner"
    assert "the OTHER #1656 axis, still open" not in CLEAN_SET_DOC, "the closed-issue pointer survives"


def test_mypy_ini_records_the_owner_too():
    assert "#2638" in MYPY_INI


# ── the cost is recorded where the decision is made ──────────────────────────


# The four codes mypy.ini disabled when #2638 was filed. `return-value` was ENABLED on
# 2026-08-15 (32 sites fixed, all annotation-only), so the live set is a SUBSET of this.
# Kept as a ratchet ceiling, never as the expected membership: pinning the membership is
# what made this test fail the moment the issue it guards made progress.
_ORIGINAL_DISABLED = {"assignment", "arg-type", "return-value", "operator"}


@pytest.mark.parametrize("code", sorted(cost.disabled_codes()))
def test_every_retained_code_carries_a_measured_count(code):
    """Acceptance box 1: retained WITH a written reason and a count of what enabling it
    would surface today. A retained code with no number is an unpriced decision.

    Derived from the live disable list, not a literal — a code enabled by a tranche must
    stop being required to justify itself as "retained"."""
    block = MYPY_INI.split("RETAINED, WITH THE COST MEASURED")[1][:1600]
    assert code in block, f"{code} has no recorded clean-set count"


def test_the_recorded_counts_are_over_the_clean_set_not_the_whole_tree():
    """The distinction that makes the numbers decision-relevant: the gate only ever runs
    the clean set, so whole-tree counts describe a run CI never performs."""
    block = MYPY_INI.split("RETAINED, WITH THE COST MEASURED")[1][:1600]
    assert "436 clean-set files" in block or "clean-set" in block
    assert "scripts/mypy_disable_cost.py" in block, "the number must be recomputable, not a snapshot"


def test_the_disable_list_and_the_recorded_codes_are_the_same_set():
    """Guard the SET: a fifth code added to mypy.ini without a recorded cost is exactly the
    unpriced decision this issue is about."""
    declared = set(cost.disabled_codes())
    block = MYPY_INI.split("RETAINED, WITH THE COST MEASURED")[1][:1600]
    # A RATCHET, not a membership pin. The invariant is "no disabled code is unpriced",
    # and it must survive a tranche landing — the old `== {four literals}` reddened main
    # the moment #2638 enabled `return-value`, i.e. it failed on the progress it existed
    # to encourage. A NEW code still fails here, via the subset check and the loop.
    assert declared <= _ORIGINAL_DISABLED, f"a new code was disabled without a recorded cost: {declared - _ORIGINAL_DISABLED}"
    assert declared, "an empty disable list means this guard has nothing left to check — retire it deliberately"
    for code in declared:
        assert code in block, f"{code} is disabled but its cost is not recorded"


def test_the_ratchet_mirror_still_matches_the_config():
    """The existing up-only guard (D4, #1665) must stay in lockstep, or emptying a code in
    one place and not the other silently weakens the gate."""
    from test_mypy_clean_modules import GLOBAL_DISABLE_BASELINE

    assert set(cost.disabled_codes()) == GLOBAL_DISABLE_BASELINE


# ── the measurement instrument itself ────────────────────────────────────────


def test_the_codes_are_read_from_the_config_not_restated():
    """A hand-listed set would let a newly-disabled code cost nothing to hide."""
    assert cost.disabled_codes(os.path.join(_REPO, "mypy.ini"))
    assert "disable_error_code" in cost._DISABLE_RE.pattern


def test_a_run_with_no_summary_line_raises_rather_than_reporting_zero(monkeypatch):
    """THE TRAP THIS FILE EXISTS FOR. An aborted mypy run ("File name too long") produced a
    confident zero for all four codes. A count that cannot be justified must be an error."""

    class _Proc:
        stdout = "mcp/warmer.py': File name too long\n"
        stderr = ""

    monkeypatch.setattr(cost.subprocess, "run", lambda *a, **k: _Proc())
    with pytest.raises(RuntimeError, match="no summary line"):
        cost.measure("return-value", ["a.py"])


def test_a_genuinely_clean_run_reports_zero(monkeypatch):
    """The control — the guard above must not turn a real zero into an exception."""

    class _Proc:
        stdout = "Success: no issues found in 3 source files\n"
        stderr = ""

    monkeypatch.setattr(cost.subprocess, "run", lambda *a, **k: _Proc())
    assert cost.measure("return-value", ["a.py"]) == {"code": "return-value", "errors": 0, "files": 0}


def test_the_summary_line_is_parsed_into_counts(monkeypatch):
    class _Proc:
        stdout = "x.py:1: error: bad  [return-value]\nFound 32 errors in 11 files (checked 436 source files)\n"
        stderr = ""

    monkeypatch.setattr(cost.subprocess, "run", lambda *a, **k: _Proc())
    assert cost.measure("return-value", ["a.py"]) == {"code": "return-value", "errors": 32, "files": 11}


# ── the overclaim (box 5) ────────────────────────────────────────────────────


def test_the_config_says_what_mypy_passed_actually_means():
    """Acceptance box 5. ADR-107's "mypy tier-2" names a FILE-SCOPE ratchet — which modules
    are checked — not an error-code one. Both are partial and neither implies the other."""
    assert "overclaims" in MYPY_INI or "narrower" in MYPY_INI.lower()
    assert "tier-2" in MYPY_INI, "the specific phrase that overclaims should be named"
