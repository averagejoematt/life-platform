"""deploy/sync_gate_census_fact.py — the gate_census_count doc-sync fact (#3000).

Split out of `deploy/sync_doc_metadata.py` (module-size ceiling —
`tests/test_module_size_guard.py`): that script is at its recorded baseline, and the
guard's rule is to pay for new lines out of an extracted sibling rather than raise the
number — the same shape as #2649's `deploy/doc_alarm_inventory.py`.

Owns the auto-discovery of the total gate count from `scripts/gate_census.py`'s
`build_census()`, AND the registration of the RULES entry that rewrites
`docs/PROPORTIONALITY.md`'s gate-census row (the "425 declared gates" that had drifted
13% behind #2639's widened CI-step derivation with nothing to notice) — `apply()` below
appends it to the caller's live `RULES` list rather than sync_doc_metadata.py carrying a
second line for it, purely to fit under the module-size ceiling; idempotent, so a second
call in the same process (a test exercising `main()` twice) does not double-register it.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The (doc, pattern, replacement-template) tuple sync_doc_metadata.py's RULES list needs.
# Narrow pattern deliberately: only the leading count, not the fixed "with measured error
# bars" suffix that follows it in docs/PROPORTIONALITY.md — re.sub only touches the match.
_RULE = ("docs/PROPORTIONALITY.md", r"\d+ declared gates", "{gate_census_count} declared gates")


def discover_gate_census_count(root: Path | None = None) -> int | None:
    """Total gates found by scripts/gate_census.py's build_census() (#3000, epic #2578).

    The ONE auto-discoverer that costs real wall-clock (~7s measured 2026-08-24, all 5
    families over the full tree) rather than a regex/AST scan — the census walks
    .github/workflows/**, the gate registries (lambdas/tests/scripts/deploy/mcp) and the
    qa-smoke + structural-test families. A failure here is an ImportError/exception this
    function swallows to None (the same fallback contract as every sync_doc_metadata.py
    `_auto_discover_*`), never a silent wrong number.
    """
    root = root or ROOT
    scripts_dir = root / "scripts"
    if not scripts_dir.exists():
        return None
    try:
        scripts_path = str(scripts_dir)
        if scripts_path not in sys.path:
            sys.path.insert(0, scripts_path)
        import gate_census  # local import: scripts/ is a lazy sys.path addition, not a package

        census = gate_census.build_census(root)
        gates = census.get("gates")
        return len(gates) if gates else None
    except Exception:
        return None


# The fallback default lives here, not in sync_doc_metadata.py's PLATFORM_FACTS (module-
# size ceiling) — `apply()` seeds it before discovery can override it, so the dict always
# ends up with a value either way, matching every other fact's fallback contract.
_FALLBACK_COUNT = 531  # measured 2026-08-24 (post-merge); was hand-typed "425" and drifted 13% (#2639)


def apply(facts: dict, rules: list, root: Path | None = None) -> None:
    """Sync_doc_metadata.py's `_apply_auto_discovered` call site — one line at the
    parent, all the print-on-change + rules-registration logic here (module-size
    ceiling): registers `_RULE` into the live `rules` list and sets the fact."""
    if _RULE not in rules:
        rules.append(_RULE)
    facts.setdefault("gate_census_count", _FALLBACK_COUNT)
    count = discover_gate_census_count(root)
    if count is None:
        return
    if facts.get("gate_census_count") != count:
        print(f"  [auto] gate_census_count: {facts.get('gate_census_count')} → {count} (#3000)")
    facts["gate_census_count"] = count
