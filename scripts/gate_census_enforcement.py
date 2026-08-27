#!/usr/bin/env python3
"""scripts/gate_census_enforcement.py — #3220: does this candidate actually enforce
anything, or does it just have "gate" in its filename?

WHY THIS MODULE EXISTS
----------------------
`gate_census.discover_guard_scripts` classified a file as a guard by FILENAME regex
alone (`_GUARD_NAME`). Measured 2026-08-26 while landing #3202: a new module
`lambdas/ai/coach_gate_retention.py` — the extracted body of
`_retain_coach_brief_flag`, which persists a fired quality-gate verdict as eval data
— pushed the census 560 -> 561 and red `tests/test_gate_census_lane_3000.py`, whose
assertion instructs the author to bump `BASELINE_TOTAL_GATES`.

It is not a gate. It enforces nothing, blocks nothing, and is deliberately fail-soft
(`except Exception: pass`, documented "retention is never load-bearing"). It matched
`_GUARD_NAME`'s `.*_gate[a-z0-9_]*\\.py$` alternative on the substring "gate" in
`coach_gate_retention.py`.

Two kinds of damage, and the second is the worse one:

  1. It inflates #2578's unproven column with a row whose can-fail proof is
     IMPOSSIBLE BY CONSTRUCTION. Whoever works that epic down eventually reaches
     the row and has to discover by hand that it is unprovable, not unproven.
  2. It invites a CEILING BUMP ON NOISE. The ratchet's remediation text says to
     bump `BASELINE_TOTAL_GATES` in the same PR — correct for real inventory
     growth, wrong here. Bumping to absorb a misfire trains the next author to
     bump on noise and quietly corrupts the ratchet.

That instance was resolved by RENAMING the module. That is the right fix for that
PR and the wrong fix for the class: renaming makes the symptom go away while the
matcher stays wrong, and the next `*_gate*.py` library hits it again.

THE RULE
--------
Filename stays a CANDIDATE filter. It is no longer SUFFICIENT. A candidate enters
the ratcheted inventory only with structural evidence that it can enforce something:

  nonzero-exit      a `sys.exit(<non-zero>)` / `SystemExit(<non-zero>)` / `exit(1)`
                    path — the shape a CI step fails on.
  escaping-raise    a `raise` that is not swallowed by an enclosing broad
                    `except`/`except Exception` in the same function. The
                    "escaping" qualifier is load-bearing: `try: ... except
                    Exception: pass` around a raise is the fail-soft shape this
                    module exists to exclude, and counting the raise inside it
                    would readmit exactly the false positive.
  assert-statement  a raised assertion (`tests/*_lib.py` guards enforce this way).
  bool-verdict-api  a function annotated `-> bool`, or returning a boolean
                    literal — it answers the yes/no question a caller gates on.
                    `lambdas/ai/budget_guard.py` is why this kind exists: the AI
                    path's budget chokepoint never raises and never exits, it
                    answers `allow(feature) -> bool`. Excluding it would trade one
                    census lie for another. NOTE this is a shape, not a name: an
                    earlier draft keyed on enforcement-verb function NAMES and was
                    thrown out on measurement — it missed `allow`, `hard_stopped`,
                    `sweep` and `safe_put_item`, i.e. it reproduced in miniature
                    the name-matching defect this whole module exists to remove.
  declared-entrypoint
                    an explicit top-of-file `# gate-entrypoint: <reason>` marker.
                    The reviewable escape hatch for a real gate whose enforcement
                    the AST cannot see — a computation module whose caller does
                    the blocking, say. Deliberately NOT inferrable: a marker
                    someone had to type, in the file being claimed, is evidence;
                    a pattern that guesses at intent is not. Re-admitting a
                    candidate is therefore a one-line reviewable edit rather than
                    a hand-list in the census, which is the thing the census is
                    for not being.

UNPROVEN vs UNPROVABLE — the distinction #2578's denominator needs
-----------------------------------------------------------------
  unproven    the gate CAN fail; nobody has watched it fail on purpose yet. Real
              #2578 work, and the honest default for nearly everything.
  unprovable  there is nothing to fail. Not #2578 work, and it must not sit in
              that epic's denominator pretending to be a task.

A name-only candidate is reported in its own state ("name-matched, no enforcement
path"), with its path, and does NOT enter the ratcheted total. It is REPORTED, not
dropped: a guard that LOSES its enforcement path — someone deletes the `sys.exit`
and the gate goes dark — must show up here rather than silently vanishing from a
count nobody was watching. That is the same shape as the six dark gates this whole
census exists to find, so making it invisible would be the census committing its
own subject.

FAIL TOWARD INCLUSION, ALWAYS
-----------------------------
A file this module cannot parse keeps its place in the inventory with an
`unparseable` evidence kind. Over-counting one library is a rounding error;
silently dropping a real gate is the failure class #2578 is named after.
"""

from __future__ import annotations

import ast
import re
from typing import Any

# ── evidence kinds ───────────────────────────────────────────────────────────
# Plain module constants, NOT a dict/list named `*_CHECKS`/`*_RULES`/`GATE_*` —
# `gate_census._REGISTRY_NAME` would expand such a binding entry-by-entry and this
# module would inject phantom gates into the census it is trying to clean up. The
# irony would be perfect and the count would be wrong.
EVIDENCE_NONZERO_EXIT = "nonzero-exit"
EVIDENCE_ESCAPING_RAISE = "escaping-raise"
EVIDENCE_ASSERT = "assert-statement"
EVIDENCE_BOOL_VERDICT = "bool-verdict-api"
EVIDENCE_DECLARED = "declared-entrypoint"
EVIDENCE_UNPARSEABLE = "unparseable"

# The state a name-only candidate is reported in. One string, shared by the census,
# the report and the tests (the #1901 lesson: a vocabulary retyped per consumer
# drifts).
NAME_ONLY_STATE = "name-matched, no enforcement path"
VERDICT_UNPROVABLE = "unprovable"

_NONZERO_EXIT = re.compile(r"sys\.exit\(\s*(?!0\s*\))|SystemExit\(\s*(?!0)|exit\(1\)")
_DECLARED_MARKER = re.compile(r"#\s*gate-entrypoint:\s*(\S.+)")
_DECLARED_SCAN_LINES = 40

# Handlers broad enough that a `raise` inside their `try:` body cannot escape.
_BROAD_EXC = {"Exception", "BaseException"}


def _handler_swallows(handler: ast.ExceptHandler) -> bool:
    """True iff this handler is broad AND does not re-raise or exit.

    Narrow handlers (`except ValueError`) are deliberately NOT treated as
    swallowing: they only catch one class, so a `raise` in the guarded body may
    still escape. Assuming otherwise would drop real gates, and the whole posture
    here is to fail toward inclusion.
    """
    exc = handler.type
    broad = exc is None or (isinstance(exc, ast.Name) and exc.id in _BROAD_EXC)
    if not broad:
        return False
    for node in ast.walk(handler):
        if isinstance(node, ast.Raise):
            return False
        if isinstance(node, ast.Call) and _NONZERO_EXIT.search(ast.unparse(node) if hasattr(ast, "unparse") else ""):
            return False
    return True


def _try_swallows(node: ast.Try) -> bool:
    return any(_handler_swallows(h) for h in node.handlers)


def _escaping_failures(node: ast.AST, swallowed: bool, found: set[str]) -> None:
    """Walk, tracking whether we are inside a `try:` body a broad handler covers.

    A `raise`/`assert` under a swallowing `try:` body is NOT evidence — that is
    precisely the fail-soft library shape. A `raise` inside the HANDLER itself is
    evidence (it re-raises out of the function), so handlers recurse with the
    OUTER `swallowed` value, not the inner one.
    """
    if isinstance(node, ast.Try):
        inner = swallowed or _try_swallows(node)
        for stmt in node.body:
            _escaping_failures(stmt, inner, found)
        for stmt in node.orelse:
            _escaping_failures(stmt, inner, found)
        for handler in node.handlers:
            for stmt in handler.body:
                _escaping_failures(stmt, swallowed, found)
        for stmt in node.finalbody:
            _escaping_failures(stmt, swallowed, found)
        return
    if not swallowed:
        if isinstance(node, ast.Raise):
            found.add(EVIDENCE_ESCAPING_RAISE)
        elif isinstance(node, ast.Assert):
            found.add(EVIDENCE_ASSERT)
    for child in ast.iter_child_nodes(node):
        _escaping_failures(child, swallowed, found)


def _has_bool_verdict_api(tree: ast.Module) -> bool:
    """A function that answers a yes/no question: annotated `-> bool`, or with a
    `return True` / `return False` in its body.

    `lambdas/ai/budget_guard.py` is why this kind exists: the platform's budget
    chokepoint neither raises nor exits — `allow(feature) -> bool` is a decision
    its callers gate on. A rule that only counted raise/exit would have deleted
    the most load-bearing gate in the AI path from the inventory, which is a worse
    census lie than the one #3220 is fixing.

    Shape, not name — see the module docstring for why the name-keyed draft was
    measured and discarded.
    """
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(node.returns, ast.Name) and node.returns.id == "bool":
            return True
        for sub in ast.walk(node):
            if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Constant) and isinstance(sub.value.value, bool):
                return True
    return False


def enforcement_evidence(text: str) -> list[str]:
    """Every structural reason to believe this file can enforce something.

    Empty list == name-only. Pure: takes source text, returns sorted evidence
    kinds, touches nothing.
    """
    found: set[str] = set()

    head = "\n".join(text.splitlines()[:_DECLARED_SCAN_LINES])
    if _DECLARED_MARKER.search(head):
        found.add(EVIDENCE_DECLARED)
    if _NONZERO_EXIT.search(text):
        found.add(EVIDENCE_NONZERO_EXIT)

    try:
        tree = ast.parse(text)
    except SyntaxError:
        # Fail toward inclusion — see the module docstring. An unparseable file is
        # a screening failure, never a licence to drop a possible gate.
        found.add(EVIDENCE_UNPARSEABLE)
        return sorted(found)

    _escaping_failures(tree, False, found)
    if _has_bool_verdict_api(tree):
        found.add(EVIDENCE_BOOL_VERDICT)
    return sorted(found)


def classify_candidate(rel: str, text: str) -> dict[str, Any]:
    """The whole #3220 decision for one name-matched candidate.

    Returns:
      enforces  bool  — does it enter the ratcheted inventory?
      evidence  list  — why (empty means name-only)
      state     str   — NAME_ONLY_STATE when it does not
      verdict   str   — VERDICT_UNPROVABLE when it does not; "" otherwise, so the
                        caller's normal `unproven` default stands
    """
    evidence = enforcement_evidence(text)
    if evidence:
        return {"path": rel, "enforces": True, "evidence": evidence, "state": "", "verdict": ""}
    return {
        "path": rel,
        "enforces": False,
        "evidence": [],
        "state": NAME_ONLY_STATE,
        "verdict": VERDICT_UNPROVABLE,
        "note": (
            "matched the guard-name pattern but no nonzero-exit, escaping raise, assert, "
            "bool verdict API or `# gate-entrypoint:` marker was found — nothing here can "
            "fail, so this is UNPROVABLE, not unproven (#3220). If it IS a real gate whose "
            "caller does the blocking, say so in the file: add `# gate-entrypoint: <why>` "
            "in its first 40 lines and it re-enters the inventory."
        ),
    }
