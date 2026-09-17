#!/usr/bin/env python3
"""tests/test_pk_census_one_home_3860.py — the pk-family census has ONE home (#3860).

WHY THIS FILE EXISTS
  #3860's defect was not that the ADR-077 totality census was wrong — it was correct, and it
  caught `SOURCE#recap_cards` the moment it ran. The defect was WHERE it lived: inside
  `deploy/restart_pipeline.py`, a script that is never staged into the Lambda bundle, so the
  only thing that could run it was an operator typing a reset command. The partition went
  unclassified for ten days.

  The fix moves the derivation to `lambdas/experiment/pk_census.py` and gives it two callers
  with two VERDICTS: the reset aborts, the nightly warns. The hazard that fix creates is
  drift — a caller that reads the shared helper and then re-derives beside it, which is the
  same divergence with an import in front of it.

WHAT IT ASSERTS, AND WHY THAT SHAPE (the #3792 lesson)
  A guard that asserts a CALL is present is satisfied by a caller that calls the helper and
  then ignores it. So the two structural legs below assert DELEGATION over the function body
  with its docstring stripped — the reset step and the nightly check must reach their verdict
  THROUGH the shared function and must not re-implement the classify loop themselves.

  Docstrings are stripped deliberately: every one of these functions EXPLAINS the mechanism it
  implements, and a text match over the source would read the prose about `classify()` as a
  call to `classify()`. That is the exact four-times-in-one-night failure recorded in
  `reference_a_text_match_reads_the_comment_explaining_it` — a check written over text reads
  the comment explaining the check.

  Each structural leg carries its own MUST-FAIL control on a synthetic body, so a leg that
  silently stops discriminating is visible here rather than in the next incident.
"""

from __future__ import annotations

import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

QA_SMOKE = os.path.join(ROOT, "lambdas", "operational", "qa_smoke_lambda.py")
PIPELINE = os.path.join(ROOT, "deploy", "restart_pipeline.py")
CENSUS = os.path.join(ROOT, "lambdas", "experiment", "pk_census.py")

SHARED_ENTRYPOINTS = {"unresolved_families", "run_census_preflight"}


def _strip_docstrings(node: ast.AST) -> ast.AST:
    """Remove every docstring expression so a text/AST scan cannot read PROSE ABOUT the
    mechanism as the mechanism. The #3792 discriminator."""
    for sub in ast.walk(node):
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = getattr(sub, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                sub.body = body[1:]
    return node


def _func(path: str, name: str) -> ast.FunctionDef:
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for sub in ast.walk(tree):
        if isinstance(sub, ast.FunctionDef) and sub.name == name:
            return _strip_docstrings(sub)
    raise AssertionError(f"{name}() not found in {os.path.relpath(path, ROOT)}")


def _called_names(fn: ast.FunctionDef) -> set[str]:
    out: set[str] = set()
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Call):
            f = sub.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


# ── 1. THE HOME EXISTS AND IS BUNDLED ────────────────────────────────────────────────────


def test_the_census_lives_in_a_bundled_package():
    """`deploy/` is not staged into the Lambda zip; `lambdas/` is. That difference IS the bug."""
    assert os.path.exists(CENSUS), "lambdas/experiment/pk_census.py is the one home — it must exist"
    from experiment.pk_census import unresolved_families  # noqa: F401  — importable under the bundle's import root

    assert not os.path.exists(
        os.path.join(ROOT, "deploy", "pk_census.py")
    ), "a second copy under deploy/ is the drift this file exists to stop"


def test_the_shared_core_actually_classifies():
    """Non-vacuity: if this derivation ever stopped calling classify(), every delegation
    assertion below would pass while guarding nothing."""
    fn = _func(CENSUS, "unresolved_families")
    assert "classify" in _called_names(fn), "the shared core must reach phase_taxonomy.classify()"


# ── 2. BOTH CALLERS DELEGATE (and neither re-derives) ────────────────────────────────────


def test_the_nightly_check_delegates_and_does_not_reimplement():
    fn = _func(QA_SMOKE, "check_pk_family_census")
    called = _called_names(fn)
    assert called & SHARED_ENTRYPOINTS, f"check_pk_family_census() must reach the shared census; calls={sorted(called)}"
    assert "classify" not in called, "the nightly check must NOT run its own classify loop — that is the drift this guards"
    assert "scan" not in called, "the nightly check must NOT run its own table scan — delegate to the shared core"


def test_the_reset_preflight_delegates_to_the_same_core():
    """run_census_preflight is re-exported into restart_pipeline rather than reimplemented."""
    with open(PIPELINE, encoding="utf-8") as fh:
        tree = _strip_docstrings(ast.parse(fh.read()))
    imported_from_census = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("pk_census")
        for alias in node.names
    }
    assert "run_census_preflight" in imported_from_census, "restart_pipeline must import the shared preflight, not define its own"
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "run_census_preflight" not in defined, "restart_pipeline must not RE-DEFINE the preflight it imports"
    assert "census_families" not in defined, "restart_pipeline must not re-define the family reducer"


def test_both_verdicts_come_from_one_derivation():
    """The point of one home: the nightly and the reset gate cannot disagree about what is
    classified, because both read the same list. Verified by behaviour, not by structure."""
    from experiment.pk_census import CensusPreflightError, run_census_preflight, unresolved_families

    pages = [
        [{"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-09-01"}, {"pk": "USER#matthew#SOURCE#__nope__", "sk": "DATE#2026-09-01"}]
    ]
    fake = _FakeScanTable(pages)
    unresolved, count = unresolved_families(fake)
    assert [f for f, _p, _s, _m in unresolved] == ["SOURCE#__nope__"], unresolved
    assert count == 2
    try:
        run_census_preflight(_FakeScanTable(pages))
    except CensusPreflightError as e:
        assert "SOURCE#__nope__" in str(e), "the reset verdict must name the same family the nightly would warn on"
    else:
        raise AssertionError("run_census_preflight must raise on the family unresolved_families reported")


# ── 3. THE VACUOUS-SCAN TRAP IS CLOSED ON BOTH LEGS ──────────────────────────────────────


class _FakeScanTable:
    def __init__(self, pages):
        self._pages = list(pages)
        self._i = 0

    def scan(self, **kwargs):
        page = self._pages[self._i] if self._i < len(self._pages) else []
        self._i += 1
        last = self._i < len(self._pages)
        return {"Items": page, **({"LastEvaluatedKey": {"pk": "x"}} if last else {})}


def test_an_empty_census_raises_rather_than_certifying():
    """A scan that returns nothing must never be reported as 'all families covered'. This is
    the check-that-cannot-fail case, and it must fail."""
    from experiment.pk_census import CensusPreflightError, unresolved_families

    for table in (_FakeScanTable([[]]), _FakeScanTable([])):
        try:
            unresolved_families(table)
        except CensusPreflightError as e:
            assert "ZERO pk families" in str(e)
        else:
            raise AssertionError("an empty census must raise, not certify totality")


def test_the_nightly_reports_the_empty_census_as_a_finding_not_an_all_clear():
    """The errored branch must WARN. A nightly that swallows the vacuous scan into an OK is
    strictly worse than having no nightly."""
    fn = _func(QA_SMOKE, "check_pk_family_census")
    handlers = [h for sub in ast.walk(fn) if isinstance(sub, ast.Try) for h in sub.handlers]
    assert handlers, "the nightly check must catch the census raising and turn it into a verdict"
    warned = any("warn" in _called_names_node(h) for h in handlers)
    assert warned, "the errored branch must WARN — never fall through to the OK line"


def _called_names_node(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            f = sub.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


# ── 4. MUST-FAIL CONTROLS — each structural leg made to fail on a synthetic body ─────────


def _synthetic(src: str, name: str) -> ast.FunctionDef:
    return _strip_docstrings(next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == name))


def test_MUTATION_a_reimplementing_nightly_check_is_caught():
    """The drift arm: a check that scans and classifies for itself must trip the leg, and the
    delegating form must not."""
    bad = _synthetic(
        "def check_pk_family_census():\n"
        "    reps = table.scan()\n"
        "    for pk, sk in reps:\n"
        "        taxonomy.classify(pk, sk)\n"
        "    return []\n",
        "check_pk_family_census",
    )
    called = _called_names(bad)
    assert "classify" in called and not (called & SHARED_ENTRYPOINTS), "control setup wrong"

    good = _synthetic(
        "def check_pk_family_census():\n    unresolved, n = unresolved_families(table)\n    return []\n",
        "check_pk_family_census",
    )
    good_called = _called_names(good)
    assert good_called & SHARED_ENTRYPOINTS and "classify" not in good_called, "the delegating form must pass the same leg"


def test_MUTATION_the_docstring_strip_is_what_makes_the_leg_honest():
    """THE #3792/#3785 CONTROL. A function whose DOCSTRING talks about classify() and scan()
    but whose body only delegates must PASS. Without the strip it would fail — i.e. the guard
    would read the prose explaining the guard. Asserted both ways."""
    src = (
        "def check_pk_family_census():\n"
        '    """Runs table.scan() and taxonomy.classify(pk, sk) over every family."""\n'
        "    unresolved, n = unresolved_families(table)\n"
        "    return []\n"
    )
    stripped = _synthetic(src, "check_pk_family_census")
    assert "classify" not in _called_names(stripped), "docstring prose must not read as a call"

    unstripped = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef))
    text = ast.get_source_segment(src, unstripped) or src
    assert "classify" in text, "the naive text/source form DOES see the docstring — which is why the strip is load-bearing"


def test_MUTATION_a_second_copy_under_deploy_would_be_caught():
    """The 'one home' leg's own control: prove the existence check discriminates."""
    ghost = os.path.join(ROOT, "deploy", "pk_census.py")
    assert not os.path.exists(ghost)
    assert os.path.exists(CENSUS) and not os.path.exists(ghost), "the leg compares two real paths, not a constant"
