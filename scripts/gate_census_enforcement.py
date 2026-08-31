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
     the row and has to discover by hand that nothing in it can fail. (#3329 makes
     that discovery a recorded `not-applicable` verdict with a reason, rather than
     a fact each reader has to re-derive.)
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

THE TEN, ADJUDICATED (#2578, 2026-08-27)
----------------------------------------
#3220 removed ten libraries that had entered the ratcheted inventory on a filename
substring alone (560 -> 551) and deliberately re-admitted none of them, leaving the
per-file ruling open. Open is not a state a denominator can stay in, so each was
ruled. This block is the REASONING, kept beside the rule it applies; it is read by
nobody and consumed by nothing — `classify_candidate` below does not consult it, and
must never be given a list like it. The operative artifact for a re-admitted file is
the `# gate-entrypoint:` line IN that file, where a reviewer of that file sees it.

Two questions, in order:

  Q1  Does a blocking consumer obey this file's verdict? A file that computes no
      verdict — a params provider, a payload builder, a threshold table — is not a
      gate at any tier, whatever its name says.
  Q2  If yes: is that same verdict already what some OTHER census row's own failure
      reports? If it is, this file is the library of an already-counted gate, and
      admitting it counts one verdict twice — its can-fail proof would be
      indistinguishable from the covering row's, because it IS the covering row's.

IN (4) — verdict computed here, blocking consumer elsewhere, no covering row:

  lambdas/coach/coach_quality_gate.py     ADR-108. `ai_calls._enforce_quality_gate`
                                          regenerates once then holds the coach.
  lambdas/intelligence/grounding_guard.py SS-10. field-notes HOLDS on the hit list;
                                          ai_expert_analyzer block-and-regens.
  lambdas/privacy/memoir_gate.py          #553. A memoir failing twice is dropped.
  tests/pair_seam_guard_lib.py            #2847. Its two test modules are invisible
                                          to the structural-test family (that family
                                          enumerates tree-sweeping tests; this one
                                          derives from the #2845 model), so nothing
                                          else counts the seam ratchet at all.

OUT (6) — and each for a stated reason, not by omission. This block is the ADMISSION
ruling (Q1/Q2: why the file is not in the can-fail population). Since #3329 the same
six also carry an executable one-line REASON in `NOT_APPLICABLE_REASONS` below —
that dict is the operative artifact the census prints; this is the reasoning behind
it. Two homes, two different questions, and the code only ever reads the dict:

  lambdas/ai/grounding_gate_params.py   Q1 no. Returns kwargs. The verdict is
                                        `grounded_generation.grounding_findings`'s,
                                        and the wiring is already gated by the census
                                        row `test_grounding_wiring_1967.py`.
  lambdas/ai/quality_gate_contract.py   Q1 no. Owns the event PAYLOAD the coach
                                        pipeline sends; decides nothing.
  lambdas/common/item_size_guard.py     Q1 no. `safe_put_item` truncates and writes on
                                        every path — "never raises" is in its
                                        docstring and true of every branch. A
                                        mitigation, not a gate.
  lambdas/experiment/experiment_gates.py Q1 no. A threshold registry; each engine makes
                                        its own arming decision from these numbers, and
                                        `correlation_gates()` et al. return the
                                        thresholds plus the caller's own n.
  tests/conformance_guard_lib.py        Q1 yes, Q2 COVERED — `test_conformance_guard_2844.py`
                                        is already a structural-test row and its failure
                                        IS this library's verdict.
  tests/truth_baseline_audit.py         Q1 yes, Q2 COVERED — `gate_finding` decides what
                                        the reader-truth sweep fails on, and that sweep
                                        is the census row `visual-qa / Run visual +
                                        AI-vision QA sweep`, which is PROVEN can-fail.

The asymmetry between the two `*_guard_lib.py` peers is the point, not an oversight:
one has a covering row and one does not, and Q2 is the only thing that separates them.

UNPROVEN vs NOT-APPLICABLE — the distinction #2578's denominator needs
----------------------------------------------------------------------
  unproven        the gate CAN fail; nobody has watched it fail on purpose yet.
                  Real #2578 work, and the honest default for nearly everything.
  not-applicable  there is nothing to fail, and the REASON is recorded. Never
                  #2578 proof work, and it must never sit in that epic's unproven
                  column pretending to be a task.

A name-only candidate is reported in its own state ("name-matched, no enforcement
path"), with its path. It is REPORTED, not dropped: a guard that LOSES its
enforcement path — someone deletes the `sys.exit` and the gate goes dark — must
show up here rather than silently vanishing from a count nobody was watching. That
is the same shape as the six dark gates this whole census exists to find, so making
it invisible would be the census committing its own subject.

#3329, owner decision 2026-08-31 (option B) — COUNTED, NOT EXCLUDED. Until now a
name-only candidate was held OUT of the total entirely, which made the census's
denominator a number with a silent asterisk ("570 gates, plus six we do not
count"). The three-verdict vocabulary epic #2578 itself names is proven /
unproven / not-applicable, so these entries now enter the inventory as an explicit
`not-applicable` verdict, INSIDE n, each carrying a one-line reason for why nothing
in it can fail. The invariant #3220 actually bought is untouched and now enforced by
type rather than by omission: a name-only match still never lands in the UNPROVEN
column, so it can never inflate the pile of real proof work.

The rent is one line: a NEW not-applicable entry must arrive with its reason.
`audit_verdicts()` below reds an entry that has none — "excluded for reasons nobody
wrote down" is the shape this whole census exists to end.

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
VERDICT_NOT_APPLICABLE = "not-applicable"
# Kept as an ALIAS, not a second string (#1901: a vocabulary retyped per consumer
# drifts). #3329 renamed the verdict to the epic's own third term and put it inside
# the total; every existing reference keeps resolving, to the same one value.
VERDICT_UNPROVABLE = VERDICT_NOT_APPLICABLE

VERDICT_PROVEN = "can-fail (proven)"
VERDICT_ATTEMPTED = "attempted-unproven"
VERDICT_UNPROVEN = "unproven"
# The whole verdict vocabulary, in report order. `audit_verdicts` partitions against
# exactly this tuple, so a verdict string invented anywhere else surfaces as
# `unrecognised` instead of quietly falling out of the sum.
VERDICTS = (VERDICT_PROVEN, VERDICT_ATTEMPTED, VERDICT_UNPROVEN, VERDICT_NOT_APPLICABLE)

# ── the recorded reasons (#3329) ─────────────────────────────────────────────
# One line per not-applicable row, written from that file's own source, saying what
# it does INSTEAD of failing. Two rules keep this from decaying into the hand-list
# the census replaces: (1) it is only ever consulted for a candidate the STRUCTURAL
# classifier has already ruled name-only — it can never re-admit or exclude anything
# by itself; (2) a candidate with no entry here still enters the census as
# `not-applicable` with an EMPTY reason, and `audit_verdicts()` reds on it. So the
# registry cannot silently omit a file; it can only fail loudly to explain one.
#
# The name deliberately matches none of `gate_census._REGISTRY_NAME`'s patterns —
# a dict called `*_RULES`/`*_CHECKS`/`GATE_*` here would be expanded entry-by-entry
# into phantom gates by the family-3 walk, and this module would inject six of them
# into the census it is cleaning up.
NOT_APPLICABLE_REASONS: dict[str, str] = {
    "lambdas/ai/grounding_gate_params.py": (
        "Returns kwargs, decides nothing: `cycle_gate_params()` builds the three cycle anchors and its only "
        "failure branch is `except Exception: return {}` (fail-soft by contract — a grounding gate must never "
        "take a narrative surface down). The arming verdict is `grounded_generation.grounding_findings()`'s, and "
        "the wiring that would otherwise drift is the census row `structural::test_grounding_wiring_1967.py`."
    ),
    "lambdas/ai/quality_gate_contract.py": (
        "Owns the wire PAYLOAD, not the verdict: every function here returns a dict/tuple describing the event the "
        "coach pipeline sends to the `coach-quality-gate` Lambda, and the pass/hold decision is that remote gate's "
        "(ADR-108). Nothing raises or exits; the drift it exists to prevent is caught by "
        "`tests/test_judge_calibration_1374.py`, which diffs the live call site against it key-by-key."
    ),
    "lambdas/common/item_size_guard.py": (
        "A mitigation, not a gate: `safe_put_item` writes on EVERY path — under 300KB it puts, at 300KB it puts and "
        "emits a metric, at 380KB it truncates the largest list field and then puts. 'Never raises — truncation is "
        "lossy but keeps the pipeline running' is its documented contract and true of every branch, so there is no "
        "input for which it refuses anything."
    ),
    "lambdas/experiment/experiment_gates.py": (
        "A threshold REGISTRY: `correlation_gates()` / `hypothesis_gates()` / `felt_calibration_gates()` return the "
        "numbers plus the caller's own n, and each engine makes its own arming decision from them (#1371). The one "
        "thing that can fail about it — an engine re-hardcoding a literal instead of importing the constant — is "
        "`tests/test_experiment_gates.py`'s assertion, not this file's."
    ),
    "tests/conformance_guard_lib.py": (
        "The library half of the kernel conformance sweep (#2844): `sweep()` returns {vocab: [site keys]} and no "
        "function here raises, exits or answers yes/no. Q2 COVERED — the census row "
        "`structural::test_conformance_guard_2844.py` asserts both directions against the shrink-only ledger, and "
        "its failure IS this library's verdict, so proving both would count one verdict twice."
    ),
    "tests/truth_baseline_audit.py": (
        "`gate_finding()` returns a STRING classification ('new' / 'baselined' / 'advisory') and nothing here "
        "raises or exits; the reader-truth sweep is what turns a 'new' into a red. Q2 COVERED — that sweep is the "
        "census row `visual-qa / Run visual + AI-vision QA sweep`, which is itself PROVEN can-fail, so this "
        "module's verdict is already reported by a row that was watched failing."
    ),
}

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
      verdict   str   — VERDICT_NOT_APPLICABLE when it does not; "" otherwise, so
                        the caller's normal `unproven` default stands
      reason    str   — the recorded one-liner for why nothing here can fail, "" when
                        nobody has written one yet (which `audit_verdicts` reds on)
    """
    evidence = enforcement_evidence(text)
    if evidence:
        return {"path": rel, "enforces": True, "evidence": evidence, "state": "", "verdict": "", "reason": ""}
    return {
        "path": rel,
        "enforces": False,
        "evidence": [],
        "state": NAME_ONLY_STATE,
        "verdict": VERDICT_NOT_APPLICABLE,
        "reason": NOT_APPLICABLE_REASONS.get(rel, ""),
        "note": (
            "matched the guard-name pattern but no nonzero-exit, escaping raise, assert, "
            "bool verdict API or `# gate-entrypoint:` marker was found — nothing here can "
            "fail, so this is NOT-APPLICABLE, not unproven (#3220/#3329). It is counted "
            "inside the total and carries a recorded reason. If it IS a real gate whose "
            "caller does the blocking, say so in the file: add `# gate-entrypoint: <why>` "
            "in its first 40 lines and it re-enters the inventory as a real gate."
        ),
    }


def not_applicable_gate_fields(candidate: dict[str, Any]) -> dict[str, Any]:
    """The `Gate(...)` kwargs a name-only candidate enters the census with (#3329).

    Kept here rather than at the call site so the verdict, the reason and the note
    travel together — `scripts/gate_census.py` sits under the module-size ceiling and
    a three-field literal inlined there is the shape that drifts from this module's
    vocabulary the first time one field is renamed.
    """
    return {
        "verdict": candidate.get("verdict") or VERDICT_NOT_APPLICABLE,
        "evidence": candidate.get("reason", ""),
        "detail": {"reason": candidate.get("reason", ""), "state": candidate.get("state", ""), "note": candidate.get("note", "")},
    }


def gate_reason(gate: dict[str, Any]) -> str:
    """The recorded reason on a census gate dict, from either field it may travel in."""
    return (gate.get("detail") or {}).get("reason") or gate.get("evidence") or ""


def verdict_partition(gates: list[dict[str, Any]]) -> dict[str, int]:
    """Counts per verdict, plus `unrecognised`. Pure — takes gate dicts, reads no repo.

    Every gate lands in exactly one bucket, so `sum(partition.values()) == len(gates)`
    by construction: a partition that can silently drop a verdict is how "570 gates,
    plus six we do not count" survived for a week.
    """
    out: dict[str, int] = {v: 0 for v in VERDICTS}
    out["unrecognised"] = 0
    for g in gates:
        v = g.get("verdict", "")
        out[v if v in out else "unrecognised"] += 1
    return out


def audit_verdicts(gates: list[dict[str, Any]]) -> list[str]:
    """Violations of the verdict contract, as human lines. Empty list == clean. Pure.

    Two rules, both of which have a real failure behind them:
      * the partition must account for every gate (no silent exclusion, #3329);
      * a `not-applicable` row must carry a non-empty reason — "nothing to fail" with
        nobody's reasoning attached is an exemption, and an unexplained exemption is
        the exact artifact this census was built to count.
    """
    violations: list[str] = []
    part = verdict_partition(gates)
    if part["unrecognised"]:
        unknown = sorted({g.get("verdict", "") for g in gates if g.get("verdict", "") not in VERDICTS})
        violations.append(f"{part['unrecognised']} gate(s) carry a verdict outside the vocabulary {list(VERDICTS)}: {unknown}")
    if sum(part.values()) != len(gates):  # pragma: no cover — structurally impossible, asserted anyway
        violations.append(f"the verdict partition sums to {sum(part.values())} but there are {len(gates)} gates")
    for g in gates:
        if g.get("verdict") == VERDICT_NOT_APPLICABLE and not gate_reason(g).strip():
            violations.append(
                f"{g.get('id', '<no id>')}: verdict `{VERDICT_NOT_APPLICABLE}` with no recorded reason — say in one line "
                f"why nothing in it can fail (scripts/gate_census_enforcement.py::NOT_APPLICABLE_REASONS), or add a "
                f"`# gate-entrypoint:` marker so it re-enters as a real gate (#3329)"
            )
    return violations
