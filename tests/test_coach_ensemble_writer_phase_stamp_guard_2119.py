"""tests/test_coach_ensemble_writer_phase_stamp_guard_2119.py — writer guard (#2119).

The #1970/#2119 class: COACH#*/ENSEMBLE#* is a tagger-blind partition —
`restart_phase_tag.py` (the reset-time tagger) only reaches `USER#matthew#SOURCE#*`
pks, and `PHASE_FILTER_EXPRESSION` (phase_filter.py) admits
`attribute_not_exists(phase)` forever — so a NEW row landed on this partition
without `experiment_stamp()` (phase_taxonomy.py, #1233) survives every read
filter and leaks into the next reset cycle looking freshly current. #1970 fixed
the genesis-prereg seeder; #2119 found a second writer
(`coach_narrative_orchestrator._cache_brief`) that the same class had leaked
through — the issue explicitly asked for a SET guard, not another one-off
instance fix, because "the third member of this class in two days" is exactly
the failure mode a per-instance test can't catch.

This file is that SET guard. It statically (AST) scans the producer directories
(lambdas/, mcp/, deploy/, scripts/) for every `table.put_item(...)` call site
that targets a `COACH#`/`ENSEMBLE#` partition — either directly, or via a
private module-level helper the call delegates to (the `_put_item`/`_stamped`
pattern used throughout `lambdas/coach/`) — and asserts the write path calls
`experiment_stamp()` somewhere between the pk being built and the row landing.

Distinct from `tests/test_qa_smoke_phase_stamp_coverage_1970.py`: that file
audits live DynamoDB DATA at runtime (did an actual row land unstamped) — this
file audits CODE statically (could a writer land an unstamped row at all). They
are complementary, not redundant: the qa-smoke check catches a violation that
already happened in production; this guard catches the writer before it ships.

Scope decision — `put_item` only, not `update_item`: every `update_item` call
found on these partitions during #2119's investigation
(`coach_state_updater._update_referenced_threads`,
`coach_prediction_evaluator._update_commitment_status`/`_update_prediction_status`)
is a partial field bump (`UpdateExpression=SET ...`) against a row the caller
already fetched by query/key lookup — i.e. it updates a row that was already
stamped when it was CREATED. The #1970/#2119 bug class is specifically about a
brand-new row entering the partition with no stamp at all; `put_item` (a full
item replace/create) is the actual entry point for that, matching every fixed
precedent (`_put_item`, `_stamped`, `coach_computation_engine._write_results`).

`deploy/archive/` is excluded: it holds retired one-shot historical scripts no
longer executed (mirrors the `REFERENCE_ONLY` exclusion in
`tests/test_site_partition_orphans.py` — dead code carries no live-write risk).

Non-vacuity (`reference_guard_the_set_not_the_instance.md`): this file does NOT
just assert real functions pass — `test_scan_functions_flags_a_synthetic_unstamped_writer`
constructs a synthetic unstamped `put_item` call via a source-string AST fixture
and proves the SAME scanning function used against the real tree flags it, and
`test_scan_functions_does_not_flag_a_synthetic_stamped_writer` proves a stamped
sibling does not. Between them they prove the guard can both fire and stay
quiet — it is not a check that could never fail.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRODUCER_DIRS = [ROOT / "lambdas", ROOT / "mcp", ROOT / "deploy", ROOT / "scripts"]

# Retired one-shot historical scripts, no longer executed — see module docstring.
EXCLUDED_DIRS = [ROOT / "deploy" / "archive"]

_PK_RE = re.compile(r"^(COACH#|ENSEMBLE#)")

# SYSTEM_STATE per lambdas/experiment/phase_taxonomy.py's _PK_RULES — static
# config, never phase-stamped by design (mirrors the _ENSEMBLE_PKS exclusion
# comment in deploy/backfill_coach_ensemble_phase_stamps.py).
SYSTEM_STATE_PKS = {"ENSEMBLE#influence_graph"}

# Recorded exceptions: a genuine put_item writer to a tagger-blind pk that is
# deliberately unstamped, with a reason. Empty as of #2119 — every writer found
# during this issue's investigation was fixed, not allowlisted. Adding an entry
# here is a recorded decision; test_allowlist_stays_honest prunes stale ones.
ALLOWLIST_UNSTAMPED: dict[str, str] = {}


def _under_excluded_dir(path: Path) -> bool:
    return any(excl in path.parents for excl in EXCLUDED_DIRS)


def _pk_tokens(node: ast.AST) -> set[str]:
    """COACH#/ENSEMBLE# pk tokens appearing anywhere in node's subtree: exact
    string literals (e.g. "COACH#computation") and f-strings whose first chunk
    starts with COACH#/ENSEMBLE# (e.g. f"COACH#{coach_id}")."""
    found: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and _PK_RE.match(n.value):
            found.add(n.value)
        if isinstance(n, ast.JoinedStr) and n.values:
            first = n.values[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str) and _PK_RE.match(first.value):
                found.add(first.value.split("{")[0] + "...")
    return found - SYSTEM_STATE_PKS


def _put_item_calls(node: ast.AST):
    """Call nodes anywhere in node's subtree that are `<expr>.put_item(...)`."""
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "put_item":
            yield n


def _private_delegate_calls(node: ast.AST):
    """Call nodes anywhere in node's subtree of the form `_helper(...)` — a
    module-private function call, the shape of the repo's `_put_item`/`_stamped`
    delegation pattern."""
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id.startswith("_"):
            yield n


def _parse(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return None


def _module_functions(tree: ast.AST) -> dict[str, ast.AST]:
    """name -> FunctionDef/AsyncFunctionDef for every function defined anywhere
    in this module (module-level or nested) — private helpers here are
    module-scoped by convention, so a name-based lookup within the same file
    resolves the repo's actual `_put_item`/`_stamped` call sites."""
    out: dict[str, ast.AST] = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[n.name] = n
    return out


def _stamps_directly(node: ast.AST) -> bool:
    """True iff an `experiment_stamp(...)` call appears anywhere in node's
    subtree. AST-based (not a source-text substring search) so a docstring or
    comment that merely MENTIONS experiment_stamp() can't produce a false
    "stamped" verdict — only an actual Call node counts."""
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id == "experiment_stamp":
                return True
            if isinstance(f, ast.Attribute) and f.attr == "experiment_stamp":
                return True
    return False


def find_unstamped_coach_ensemble_writers() -> list[str]:
    """Returns a sorted list of "path::function (pk_token, ...)" violation
    strings: every producer-dir writer that lands a COACH#/ENSEMBLE# pk via
    `put_item` (directly, or via a `_private_helper(...)` delegate) without
    `experiment_stamp()` reachable in one hop, and not on ALLOWLIST_UNSTAMPED.
    """
    violations: list[str] = []
    seen: set[Path] = set()
    for base in PRODUCER_DIRS:
        for path in base.rglob("*.py"):
            if path in seen or _under_excluded_dir(path):
                continue
            seen.add(path)
            tree = _parse(path)
            if tree is None:
                continue
            functions = _module_functions(tree)

            for fn in functions.values():
                # Direct writer: this function itself calls `<expr>.put_item(...)`
                # and a COACH#/ENSEMBLE# pk appears anywhere in its own body.
                if list(_put_item_calls(fn)):
                    pks = _pk_tokens(fn)
                    if pks and not _stamps_directly(fn):
                        rel = f"{path.relative_to(ROOT)}::{fn.name}"
                        if rel not in ALLOWLIST_UNSTAMPED:
                            violations.append(f"{rel} ({', '.join(sorted(pks))})")

                # Delegate writer: this function calls a `_helper(...)` whose
                # ARGUMENTS (at the call site) carry a COACH#/ENSEMBLE# pk —
                # the callee (resolved by name, same module) must itself be a
                # put_item writer that stamps. A callee with NO put_item call at
                # all (e.g. a getter like _get_item/_query_begins_with) is not a
                # writer and is skipped, not flagged.
                for call in _private_delegate_calls(fn):
                    pks = _pk_tokens(call)
                    if not pks:
                        continue
                    callee = functions.get(call.func.id)
                    if callee is None:
                        # Unresolved (imported from elsewhere, or dynamic) — not
                        # this guard's business; a same-module private helper
                        # covers every case seen in this codebase (#2119).
                        continue
                    if not list(_put_item_calls(callee)):
                        continue  # not a writer (e.g. a same-named getter)
                    if not _stamps_directly(callee):
                        rel = f"{path.relative_to(ROOT)}::{fn.name}->{call.func.id}"
                        if rel not in ALLOWLIST_UNSTAMPED:
                            violations.append(f"{rel} ({', '.join(sorted(pks))})")

    return sorted(set(violations))


def test_no_unstamped_coach_ensemble_writers():
    violations = find_unstamped_coach_ensemble_writers()
    assert not violations, (
        "producer code writes a NEW row to a tagger-blind COACH#/ENSEMBLE# partition "
        "(put_item) without experiment_stamp() reachable in one hop: "
        f"{violations} — stamp it inline (see coach_narrative_orchestrator._cache_brief, "
        "#2119) or delegate to a helper that already stamps (coach_state_updater._put_item), "
        "or if it's a deliberate SYSTEM_STATE exception add it to ALLOWLIST_UNSTAMPED with a reason"
    )


def test_allowlist_stays_honest():
    """An ALLOWLIST_UNSTAMPED entry must still be a real, currently-unstamped
    writer — otherwise it's stale and should be pruned. (Currently empty; this
    keeps the honesty check ready without asserting anything vacuous today.)"""
    if not ALLOWLIST_UNSTAMPED:
        return
    unstamped_now = set()
    seen: set[Path] = set()
    for base in PRODUCER_DIRS:
        for path in base.rglob("*.py"):
            if path in seen or _under_excluded_dir(path):
                continue
            seen.add(path)
            tree = _parse(path)
            if tree is None:
                continue
            for fn in _module_functions(tree).values():
                if list(_put_item_calls(fn)):
                    pks = _pk_tokens(fn)
                    if pks and not _stamps_directly(fn):
                        unstamped_now.add(f"{path.relative_to(ROOT)}::{fn.name}")
    for name, reason in ALLOWLIST_UNSTAMPED.items():
        assert name in unstamped_now, f"ALLOWLIST_UNSTAMPED has a stale entry {name!r} ({reason}) — it now stamps; prune it"


# ── Non-vacuity: prove the scanner can actually fire ────────────────────────

_SYNTHETIC_UNSTAMPED = '''
def _write_synthetic_row(coach_id, table):
    """A fake writer with no experiment_stamp() call — must be flagged."""
    item = {
        "pk": f"COACH#{coach_id}",
        "sk": "SYNTHETIC#today",
        "value": 1,
    }
    table.put_item(Item=item)
'''

_SYNTHETIC_STAMPED = '''
def _write_synthetic_row_stamped(coach_id, table):
    """A fake writer that DOES stamp — must NOT be flagged."""
    from experiment.phase_taxonomy import experiment_stamp

    item = {
        **experiment_stamp(),
        "pk": f"COACH#{coach_id}",
        "sk": "SYNTHETIC#today",
        "value": 1,
    }
    table.put_item(Item=item)
'''


def _scan_source_for_direct_violations(src: str) -> list[str]:
    """The same direct-writer scan find_unstamped_coach_ensemble_writers() runs
    per-file, applied to an in-memory source string instead of a repo file —
    the reusable core of the non-vacuity fixtures below."""
    tree = ast.parse(src)
    out = []
    for fn in _module_functions(tree).values():
        if list(_put_item_calls(fn)):
            pks = _pk_tokens(fn)
            if pks and not _stamps_directly(fn):
                out.append(fn.name)
    return out


def test_scan_functions_flags_a_synthetic_unstamped_writer():
    """Non-vacuity: a synthetic put_item writer with no experiment_stamp() call
    IS flagged — proves the guard can fire, not just stay green by construction."""
    assert _scan_source_for_direct_violations(_SYNTHETIC_UNSTAMPED) == ["_write_synthetic_row"]


def test_scan_functions_does_not_flag_a_synthetic_stamped_writer():
    """The stamped sibling of the same fixture is NOT flagged — proves the
    guard doesn't just flag every put_item call indiscriminately."""
    assert _scan_source_for_direct_violations(_SYNTHETIC_STAMPED) == []


def test_cache_brief_is_a_real_fixed_instance_of_this_class():
    """#2119's own fix stays covered by the SET guard, not just a one-off: the
    real _cache_brief function (as shipped) must scan as stamped."""
    tree = _parse(ROOT / "lambdas" / "coach" / "coach_narrative_orchestrator.py")
    assert tree is not None
    fn = _module_functions(tree).get("_cache_brief")
    assert fn is not None, "_cache_brief was renamed or removed — update this test"
    assert list(_put_item_calls(fn)), "_cache_brief no longer calls put_item — update this test"
    assert any(t.startswith("COACH#") for t in _pk_tokens(fn))
    assert _stamps_directly(fn), "_cache_brief regressed to unstamped — this is the #2119 bug re-appearing"
