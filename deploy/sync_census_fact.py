"""deploy/sync_census_fact.py — the gate_census_count doc-sync fact (#3000).

Split out of `deploy/sync_doc_metadata.py` (module-size ceiling —
`tests/test_module_size_guard.py`): that script is at its recorded baseline, and the
guard's rule is to pay for new lines out of an extracted sibling rather than raise the
number — the same shape as #2649's `deploy/doc_alarm_inventory.py`.

NAMED WITHOUT "gate" ON PURPOSE. An earlier name, `sync_gate_census_fact.py`, matched
`scripts/gate_census.py`'s own `_GUARD_NAME` regex (any `_gate` substring before `.py`)
purely as a filename coincidence — the census then classified this data-glue module as
a guard script it can never prove `can-fail`, and its own row went stale by the width of
that one spurious gate the next time anything ran `--apply`. Found live, fixed by renaming.

Owns the auto-discovery of the total gate count from `scripts/gate_census.py`'s
`build_census()`, AND the registration of the RULES entry that rewrites
`docs/PROPORTIONALITY.md`'s gate-census row (the "425 declared gates" that had drifted
13% behind #2639's widened CI-step derivation with nothing to notice) — `apply()` below
appends it to the caller's live `RULES` list rather than sync_doc_metadata.py carrying a
second line for it, purely to fit under the module-size ceiling; idempotent, so a second
call in the same process (a test exercising `main()` twice) does not double-register it.

#3156 — LOUD-FAILURE REWRITE. The Docs CI job (`docs-ci.yml`) installs no packages, so
every `--check` run there hit `discover_ci_gates()`'s local `import yaml` (needed to
parse `.github/workflows/**`), raised `ModuleNotFoundError`, and this module swallowed it
to `None` the way the docstring above always documented — but the caller then substituted
`_FALLBACK_COUNT = 531` (frozen 2026-08-24) as if it were a measurement. `--check` compared
docs/PROPORTIONALITY.md against that frozen constant forever, while a branch whose local
pre-commit hook DOES have PyYAML installed keeps deriving the true live count (538 by
2026-08-25) and re-stamping it — the #1957 "credentialed --apply vs. credential-free
--check fight forever" class, verbatim. Confirmed live via a bare venv with no packages
installed: `ModuleNotFoundError: No module named 'yaml'` at `gate_census.py`'s
`discover_ci_gates()`, `import yaml` line — not guessed.

Fixed two ways: (1) `docs-ci.yml` now installs PyYAML (already pinned in
requirements-dev.txt for `apply_branch_protection.py`'s identical need) before running the
gates, so the Docs CI job can actually measure; (2) defense in depth for every OTHER
environment that still lacks the dep — `discover_gate_census_count()` now returns the
FAILURE REASON alongside `None` instead of throwing it away, and `apply()` uses it: under
`--check` (detected the same way `sync_doc_metadata.main()` itself does, via `sys.argv` —
apply() stays a two-argument function so no caller-side plumbing is needed) an underivable
census fails the build LOUDLY (`sys.exit(1)`, message names the reason); outside `--check`
the rule is explicitly SKIPPED with a printed reason and the doc is left untouched — never
a silent fallback comparison against a frozen number either way. `_FALLBACK_COUNT` is gone;
nothing compares against it anymore.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The (doc, pattern, replacement-template) tuple sync_doc_metadata.py's RULES list needs.
# Narrow pattern deliberately: only the leading count, not the fixed "with measured error
# bars" suffix that follows it in docs/PROPORTIONALITY.md — re.sub only touches the match.
_RULE = ("docs/PROPORTIONALITY.md", r"\d+ declared gates", "{gate_census_count} declared gates")


def discover_gate_census_count(root: Path | None = None) -> tuple[int | None, str | None]:
    """Total gates found by scripts/gate_census.py's build_census() (#3000, epic #2578).

    The ONE auto-discoverer that costs real wall-clock (~7s measured 2026-08-24, all 5
    families over the full tree) rather than a regex/AST scan — the census walks
    .github/workflows/**, the gate registries (lambdas/tests/scripts/deploy/mcp) and the
    qa-smoke + structural-test families.

    Returns ``(count, error)``: on success ``(int, None)``; on failure ``(None, reason)``
    where `reason` is a short human-readable string (#3156 — the exception used to be
    swallowed with no trace at all, which is how a frozen fallback could pass for a
    measurement one layer up in `apply()`). `error` is None-only-on-success, so a caller
    can tell "underivable" from "zero gates found" without inspecting both fields blindly.

    #2578 — THE SECOND WAY THIS FACT CAN BE WRONG, and it does not raise. #3156 closed
    the case where the census cannot run AT ALL (a missing dep at import). It left open
    the case where the census runs and one FAMILY cannot: `build_census()` used to return
    a gate list short by that family's n, with only a log line to say so, and this
    function reported it as a measurement. Measured 2026-08-27 by blocking
    `tests/premerge_derivation.py`'s import: 554 -> 450, `error` None, and an `--apply`
    run in that lane would have stamped 450 into docs/PROPORTIONALITY.md as the honest
    live number. A partial sweep is now refused exactly like an absent one.
    """
    root = root or ROOT
    scripts_dir = root / "scripts"
    if not scripts_dir.exists():
        return None, f"{scripts_dir} does not exist"
    try:
        scripts_path = str(scripts_dir)
        if scripts_path not in sys.path:
            sys.path.insert(0, scripts_path)
        import gate_census  # local import: scripts/ is a lazy sys.path addition, not a package

        census = gate_census.build_census(root)
        gates = census.get("gates")
        if not gates:
            return None, "build_census() returned zero gates"
        skipped = census.get("families_skipped") or []
        if skipped:
            detail = "; ".join(f"{s['family']} — {s['reason']}" for s in skipped)
            return None, (
                f"incomplete sweep: {len(skipped)} gate family/families could not run, so "
                f"the {len(gates)} gates found are a floor, not a count ({detail})"
            )
        return len(gates), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def apply(facts: dict, rules: list, root: Path | None = None) -> None:
    """Sync_doc_metadata.py's `_apply_auto_discovered` call site — one line at the
    parent, all the print-on-change + rules-registration logic here (module-size
    ceiling): registers `_RULE` into the live `rules` list and sets the fact.

    #3156: an underivable count is NEVER silently compared against a frozen number.
    `is_check` is read from `sys.argv` (the same technique `sync_doc_metadata.main()`
    itself already uses for the identical question) rather than threaded through as a
    parameter, so this call site never has to change and every existing caller/monkeypatch
    of `_apply_auto_discovered` stays untouched.
    """
    count, error = discover_gate_census_count(root)
    if count is None:
        if "--check" in sys.argv:
            print(f"  ❌ CHECK FAILED — census underivable: {error}")
            print("     (scripts/gate_census.py could not run — install its deps or fix the import)")
            sys.exit(1)
        print(f"  [skip] gate_census_count underivable ({error}) — docs/PROPORTIONALITY.md's gate-census row left unchanged (#3156)")
        return
    if _RULE not in rules:
        rules.append(_RULE)
    if facts.get("gate_census_count") != count:
        print(f"  [auto] gate_census_count: {facts.get('gate_census_count')} → {count} (#3000)")
    facts["gate_census_count"] = count
