"""scripts/gate_census_sentinel.py — Family 6, the drift-sentinel per-check registry
(#3129).

Split from `gate_census.py` by the module-size ratchet (#1665's 1200-line hard
ceiling, #2610's extraction-not-baseline policy: `scripts/gate_census.py` was never
baselined — it sat under the ceiling before this family landed — so the fix is
extraction, never a new BASELINE entry and never the top-of-file exemption, which is
reserved for generated/registry files and this is neither). `gate_census` imports and
registers `discover_sentinel_gates` so `build_census()` and `--family sentinel` stay
identical — same public entrypoint, only the implementation moved.

WHY THIS FAMILY EXISTS
-----------------------
deploy/drift_sentinel.py's run_sweep() builds a `checks = {...}` dict whose entries are
exactly what remediation/drift_report.py's as_signal() reads to decide needs-human
triage (`flagging = {k: v for k, v in checks.items() if v.get("status") == "drift"}`) —
each check_* function behind those entries is a real, armed gate. None of the other
five families walked deploy/ for this shape, so a can-it-fail proof for e.g.
check_codeql_alerts (#3112, the #2578 autopsy) had no registerable home and this whole
family was invisible to the census.

HOW IT'S DERIVED
----------------
The SAME two ways `discover_qa_smoke_gates` (Family 4, in gate_census.py) already
proves out for an almost-identical shape: the check_* NAMING CONVENTION finds the
candidate population, and "registered" means the name is referenced somewhere beyond
its own definition/import line — i.e. actually wired into drift_sentinel.py's own
registration surface, the same file whose run_sweep() dict drives the sweep. A check_*
function that exists but was never wired in gets Family 4's exact shape
(`unreferenced-entrypoint`): flagged, never dropped from the count.

The module-size ratchet (#1665) separately forced drift_sentinel.py to extract four
siblings of its own — sentinel_github.py, sentinel_quota.py, sentinel_replication.py,
sentinel_cadence.py — each re-imported by name
(`from sentinel_github import (..., check_github_config, ...)`) so run_sweep() and
every existing caller/test keep the `ds.check_*` names. A walker that only looked at
drift_sentinel.py's own function defs would miss every check_* defined in those four
modules entirely — this walks BOTH: local defs, and check_* names pulled in via
`from <sibling> import (...)`, resolved back to the sibling's own file+line so the
source points at the real definition, not the re-export site.

session_postflight.py (the "POSTFLIGHT REUSE" item in drift_sentinel's own module
docstring) is deliberately OUT of scope here — it is REUSED, not one of the
#1665-extracted siblings, and its three sub-checks are folded into drift_sentinel's own
`check_postflight` gate, which this walker already finds as a local def.

NO CIRCULAR IMPORT
-------------------
`gate_census.py` needs `discover_sentinel_gates`; this module needs `gate_census.py`'s
`Gate` dataclass, `_read`, and `_static_source_flags` to build/screen gates the same
way every other family does. Importing gate_census FROM here (mirroring how
gate_census_precision.py is a one-way, no-back-dependency split) would create a real
cycle — and unlike a module import, `python3 scripts/gate_census.py` run directly hits
it too (the file gets executed twice under two different module names, `__main__` and
`gate_census`, and the second execution's own `from gate_census_sentinel import ...`
finds a still-empty, mid-import `gate_census_sentinel` module). So this module takes
`gate_census`'s pieces as PARAMETERS instead — `discover_sentinel_gates(root, gate_cls,
read_fn, static_flags_fn, log_fn)` — and `gate_census.py` wraps the call in a thin
same-signature `discover_sentinel_gates(root)` so every existing caller (`build_census`,
`tests/test_gate_census_2578.py`'s `gc.discover_sentinel_gates(root)`) is unaffected.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Callable

# check_* names pulled from a `from <module> import (...)` in drift_sentinel.py are only
# in scope when <module> is one of these #1665-shaped extracted siblings — see the module
# docstring above for why session_postflight.py is deliberately excluded.
# sentinel_events joined 2026-08-29 (#3279).
_SENTINEL_SIBLINGS = ("sentinel_github", "sentinel_quota", "sentinel_replication", "sentinel_cadence", "sentinel_events")


def _sentinel_check_defs(text: str) -> dict[str, tuple[int, str]]:
    """Module-level `check_*` function defs in one file: name -> (lineno, source segment)."""
    out: dict[str, tuple[int, str]] = {}
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("check_"):
            out[node.name] = (node.lineno, ast.get_source_segment(text, node) or "")
    return out


def discover_sentinel_gates(
    root: Path,
    gate_cls: Callable[..., Any],
    read_fn: Callable[[Path], str],
    static_flags_fn: Callable[[str], list[str]],
    log_fn: Callable[[str], None],
) -> tuple[list[Any], dict[str, int]]:
    """`gate_cls`/`read_fn`/`static_flags_fn`/`log_fn` are gate_census.py's own
    `Gate`/`_read`/`_static_source_flags`/`log` — injected rather than imported (see the
    module docstring's NO CIRCULAR IMPORT section) so this module has zero dependency on
    gate_census.py and cannot deadlock however either module is invoked."""
    gates: list[Any] = []
    counters = {"local_check_functions": 0, "sibling_check_functions": 0, "unregistered": 0}
    deploy_dir = root / "deploy"
    main_rel = "deploy/drift_sentinel.py"
    main_text = read_fn(deploy_dir / "drift_sentinel.py")
    if not main_text:
        # #2578: `skipped_reason` travels in the counters so `build_census()` can report
        # an INCOMPLETE sweep rather than a gate list that is silently short by this
        # family's n — see gate_census_structural.py for the measured instance.
        log_fn("deploy/drift_sentinel.py unreadable — sentinel family SKIPPED (n unknown)")
        return [], {"importable": 0, "skipped_reason": "deploy/drift_sentinel.py unreadable"}
    try:
        main_tree = ast.parse(main_text)
    except SyntaxError as exc:
        log_fn("deploy/drift_sentinel.py did not parse — sentinel family SKIPPED (n unknown)")
        return [], {"importable": 0, "skipped_reason": f"deploy/drift_sentinel.py did not parse (SyntaxError: {exc})"}

    def _registered(name: str) -> bool:
        # "Registered" = referenced somewhere beyond its own def/import line in
        # drift_sentinel.py — the file whose run_sweep() checks dict is what
        # remediation/drift_report.py actually reads. Same idiom as Family 4's
        # `registry_text.count(node.name) <= 1`.
        return main_text.count(name) > 1

    # Local check_* functions, defined directly in drift_sentinel.py.
    for name, (lineno, body) in sorted(_sentinel_check_defs(main_text).items()):
        counters["local_check_functions"] += 1
        flags: list[str] = [] if _registered(name) else ["unreferenced-entrypoint"]
        if "unreferenced-entrypoint" in flags:
            counters["unregistered"] += 1
        flags += static_flags_fn(body)
        gates.append(
            gate_cls(
                id=f"sentinel::{main_rel}::{name}",
                family="sentinel-check",
                name=name,
                source=f"{main_rel}:{lineno}",
                screened=True,
                risk_flags=sorted(set(flags)),
            )
        )

    # check_* names pulled in from the #1665-extracted siblings — resolved to their
    # OWN file+line, never the drift_sentinel.py re-export line.
    for node in main_tree.body:
        if not (isinstance(node, ast.ImportFrom) and node.module in _SENTINEL_SIBLINGS):
            continue
        sib_rel = f"deploy/{node.module}.py"
        sib_text = read_fn(root / sib_rel)
        sib_defs = _sentinel_check_defs(sib_text) if sib_text else {}
        for alias in node.names:
            name = alias.name
            if not name.startswith("check_"):
                continue
            counters["sibling_check_functions"] += 1
            flags = [] if _registered(name) else ["unreferenced-entrypoint"]
            if "unreferenced-entrypoint" in flags:
                counters["unregistered"] += 1
            lineno, body = sib_defs.get(name, (None, ""))
            flags += static_flags_fn(body)
            gates.append(
                gate_cls(
                    id=f"sentinel::{sib_rel}::{name}",
                    family="sentinel-check",
                    name=name,
                    source=f"{sib_rel}:{lineno}" if lineno else sib_rel,
                    screened=bool(sib_text),
                    unscreened_reason="" if sib_text else f"{sib_rel} unreadable — imported name could not be resolved to a definition",
                    risk_flags=sorted(set(flags)),
                )
            )
    return gates, counters
