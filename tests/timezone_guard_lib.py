"""tests/timezone_guard_lib.py — shared low-level AST primitives for the timezone/
day-frame SET guards (#4268).

WHY THIS EXISTS. Six guard files police the same defect FAMILY (a calendar day or
freshness age derived from the wrong clock frame) but grew six independent copies of
the same handful of AST primitives — path-skip markers, and a "walk this scope without
descending into a nested function/class" traversal every one of them needed to keep a
taint or anchor check from leaking across function boundaries. #4268's harness-audit
finding was that duplication, not the domain rules themselves: each guard's RULE (what
counts as a naive/UTC anchor, which exemption marker suppresses it, which synthetic
cases prove it fires) is deliberately kept in its OWN file — a shared walker is
infrastructure, not a merged rulebook, and merging the rulebooks is exactly the kind of
one-big-registry move `docs/PROPORTIONALITY.md` warns against for a family this varied
(reader-surface day rendering, ingestion source day-key frames, producer/gate day
defaults are three different shapes of "the wrong clock", not one).

WHAT MOVED HERE, AND WHY EACH PIECE IS SAFE TO SHARE
------------------------------------------------------
``SKIP_PATH_MARKERS`` — the literal tuple `("__pycache__", "_staging", "cdk.out",
"layer-build")` was defined independently, byte-identical, in
`test_pacific_today_guard_2414.py` (`_SKIP_PATH_MARKERS`) and
`test_pt_day_contract_sweep_2813.py` (`_SKIP_MARKERS`). One canonical value now; each
guard still applies it through its OWN traversal mechanism (2414's rglob-then-filter,
2813's os.walk-with-dirnames-pruning) — the MECHANISM is deliberately NOT unified here,
only the VALUE, because the two mechanisms are not provably equivalent on prune timing
and a forced merge would risk a scan-surface change neither guard's own tests pin.

``own_scope_nodes`` — the scope-limited AST walk (yield every node reachable from
``scope`` without crossing into a nested function/class) was independently
re-implemented in `test_pacific_today_guard_2414.py` (`_own_scope_nodes`, backing
`_clock_returning_functions`'s per-function taint) and
`test_day_key_frame_declaration_guard_3913.py` (`_own_body`, backing leg 2's
hand-anchored-age scan) — same algorithm, same purpose (stop a taint/anchor check from
attributing a nested function's body to its enclosing one — #3913's own docstring
names the exact bug this prevents: `site_api_status.status()`'s nested
`_comp_status` would otherwise be scanned as part of the 600-line outer handler).
Parameterized by ``boundary`` so each caller keeps its EXACT original node set: 2414
passes its historical boundary (FunctionDef/AsyncFunctionDef/ClassDef/Lambda, the
default here); 3913 passes its own narrower one (no ClassDef — 3913 never treated a
nested class as a scope boundary and its own tests pin that). Verified by running both
files' full test suites, including every mutation/control test, before and after the
swap — see PR #4268 for the byte-identical `hand_anchored_age_sites()`/
`naive_utc_today_sites()` output over the real tree that proves it.

``python_files_under`` — the rglob-then-filter idiom `[p for p in root.rglob("*.py")
if not any(m in str(p) for m in SKIP_PATH_MARKERS)]` appeared TWICE, verbatim, inside
`test_pacific_today_guard_2414.py::_surface_files` (once for `lambdas/web`, once per
entry in `_ADDITIONAL_SURFACE_DIRS`). Factored out in-place; the caller's derived
surface (`_surface_files()`'s own `test_surface_is_derived_and_nonempty` pin) is
unchanged because the filter predicate is unchanged.

WHAT DID NOT MOVE HERE, ON PURPOSE
-----------------------------------
`test_pt_date_anchor_guard_1937.py` is GONE, not moved: #4268 measured it a strict
subset of `test_pacific_today_guard_2414.py`'s scan (every synthetic case 1937 fired
on, 2414 fires on too, with an equal or larger finding count; both report zero
findings on the real tree today) — see PR #4268's pasted diff. Its one assertion 2414
did not already make (`site_api_vitals`'s instants stay UTC) now lives in 2414 itself
as `test_site_api_vitals_family_still_anchors_instants_in_utc`.

`test_timezone_discipline.py` (regex over `lambdas/ mcp/ deploy/ scripts/ remediation/`)
and `test_pt_day_pair_contracts_2798.py` (drives real production functions at one
frozen instant; its one AST call delegates to `test_utc_day_fleet_ratchet_2811.py`'s
own walker, outside this issue's six-file list) are untouched — neither duplicates the
scope-walk or skip-marker primitives above, so folding either in here would be motion
without a duplication to remove.

THE 40-FILE rglob/ast.parse -> repo_scan_cache MIGRATION IS A LATER SLICE, deliberately
not started here — see PR #4268's description for the current member list (re-run
`grep -rl 'ast.parse' tests/test_*.py | xargs grep -L repo_scan_cache`) and why it does
not belong in this module: `repo_scan_cache` shares ONE SUBPROCESS SPAWN of a
repo-scanning *script*, and none of the 40 files (nor the six guards here) spawn a
subprocess at all — they call `ast.parse` in-process, so migrating them means giving
each a `--check`-style script entry point first, a materially larger change this slice
does not make.
"""

from __future__ import annotations

import ast
import pathlib
from typing import Iterable, Iterator

# The byte-identical skip-marker tuple `test_pacific_today_guard_2414.py` and
# `test_pt_day_contract_sweep_2813.py` each defined on their own. Build-output /
# staging / bundling directories a source-text or AST scan of `lambdas/`+`mcp/` has no
# reason to enter.
SKIP_PATH_MARKERS: tuple[str, ...] = ("__pycache__", "_staging", "cdk.out", "layer-build")

# The default boundary for `own_scope_nodes` — `test_pacific_today_guard_2414.py`'s
# original `_own_scope_nodes` boundary, kept as the default because it is the more
# inclusive of the two calling guards' historical boundaries (it also stops at a
# nested class body, which `test_day_key_frame_declaration_guard_3913.py`'s original
# `_own_body` never did — 3913 passes its own narrower tuple explicitly).
_DEFAULT_BOUNDARY: tuple[type, ...] = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def own_scope_nodes(scope: ast.AST, boundary: Iterable[type] = _DEFAULT_BOUNDARY) -> Iterator[ast.AST]:
    """Every node reachable from `scope`'s own body, WITHOUT descending into a nested
    scope of a type in `boundary`.

    The boundary node itself is yielded (an `isinstance(node, ast.Assign)`-style
    predicate downstream never matches a bare `FunctionDef`/`ClassDef`/`Lambda` node,
    so callers that only test for `Assign`/`Call`/etc. see the identical verdict
    whether or not the boundary node is included) — only its OWN children are not
    walked into. This is what keeps a per-scope taint or anchor check from attributing
    a nested function's (or, with the default boundary, a nested class's) body to the
    scope that encloses it.
    """
    boundary_t = tuple(boundary)
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, boundary_t):
            continue
        stack.extend(ast.iter_child_nodes(node))


def python_files_under(root: pathlib.Path, skip_markers: tuple[str, ...] = SKIP_PATH_MARKERS) -> list[pathlib.Path]:
    """Every `*.py` file under `root`, skipping any whose path contains one of
    `skip_markers` as a substring — the rglob-then-filter idiom repeated inline (once
    per scanned directory) in `test_pacific_today_guard_2414.py::_surface_files`."""
    return [p for p in root.rglob("*.py") if not any(m in str(p) for m in skip_markers)]
