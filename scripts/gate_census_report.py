#!/usr/bin/env python3
"""scripts/gate_census_report.py — the human-readable rendering of the gate census.

Extracted from `scripts/gate_census.py` (#3220) under the module-size ratchet
(#1665/#2610: extraction on a real seam, NEVER a baseline raise). The seam is a
clean one — the renderer already took nothing but the census dict, so this is a
move, not a redesign. Two substitutions were needed and both make the coupling
honester rather than looser: the module-level `SHAPES` and `ATTEMPTED_UNPROVEN`
reads become `census["shapes"]` / `census["attempted_unproven"]`, which is where
`build_census` already publishes them and what the `--json` consumer already sees.

`gate_census.render_report` re-exports this, so every existing call site and test
keeps its address.
"""

from __future__ import annotations

from typing import Any

from gate_census_precision import _render_error_bars


def _wrap(text: str, width: int = 88, indent: str = " " * 16) -> str:
    """Soft-wrap a proof field so a long `observed` stays readable in a terminal."""
    words, out, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        out.append(cur)
    return f"\n{indent}".join(out)


def render_report(census: dict[str, Any]) -> str:
    gates = census["gates"]
    n = len(gates)
    screened = [g for g in gates if g["screened"]]
    unscreened = [g for g in gates if not g["screened"]]
    flagged = [g for g in screened if g["risk_flags"]]
    proven = [g for g in gates if g["verdict"] == "can-fail (proven)"]
    attempted = [g for g in gates if g["verdict"] == "attempted-unproven"]
    orphan_proofs = census.get("orphan_proofs") or []
    unattached = census.get("unattached_attempts") or []
    name_only = census.get("name_only_candidates") or []

    lines: list[str] = []
    add = lines.append
    add("=" * 78)
    add("GATE CENSUS — #2578 (slice 1 inventory + static screen; slice 2 mutation verdicts)")
    add("=" * 78)
    add("")
    add(f"gates found                  n = {n}")
    add(f"  statically screened        n = {len(screened)}  ({len(screened) / n:.0%})" if n else "  (none)")
    add(f"  could NOT be screened      n = {len(unscreened)}")
    add(f"  carrying >=1 risk flag     n = {len(flagged)}")
    add(f"  verdict proven can-fail    n = {len(proven)}   <- each cites the mutation that produced it")
    add(f"  attempted, NOT proved      n = {len(attempted)}   <- recorded with the reason, never skipped")
    add(f"  UNPROVEN (can fail, proof not written)   n = {n - len(proven) - len(attempted)}   <- real #2578 work")
    add(f"  UNPROVABLE (nothing to fail, excluded)   n = {len(name_only)}   <- NOT #2578 work, NOT in the total above")
    add("")
    # #2999 box 1/box 4: the number that matters is a FRACTION with an n, printed every
    # run, next to the reading it has to beat. A count of proofs with no denominator is
    # how "7 proven" read as progress for four months.
    if n:
        add(
            f"VERDICT FRACTION             {len(proven)}/{n} proven ({len(proven) / n:.1%}) "
            f"+ {len(attempted)} attempted-not-proved = {(len(proven) + len(attempted)) / n:.1%} adjudicated"
        )
        add("  reference points             7/490 (1.4%) when #2999 was filed 2026-08-22; 25/561 (4.5%) on main 2026-08-27")
    add("")

    # #3220: the name-only report. These matched `_GUARD_NAME` and have no
    # structural way to fail, so they are OUT of the count — named here because a
    # guard that LOSES its enforcement path must surface, not vanish.
    add("-- NAME-MATCHED, NO ENFORCEMENT PATH (excluded from the total, #3220) " + "-" * 8)
    if not name_only:
        add("  (none — every name-matched candidate has structural evidence it can fail)")
    for c in name_only:
        add(f"  {c['path']}")
    if name_only:
        add("  Each matched the guard-NAME pattern only. If one of these IS a gate whose")
        add("  caller does the blocking, add `# gate-entrypoint: <why>` in its first 40")
        add("  lines — that re-admits it, in the file, reviewably. Do NOT bump the census")
        add("  ceiling to absorb one of these: that trains the next author to bump on noise.")
    add("")
    add(_render_error_bars(census))
    add("")

    add("-- VERDICTS: proven able to fail (mutation introduced, failure watched) " + "-" * 6)
    if not proven:
        add("  (none recorded — PROVEN_CAN_FAIL is empty)")
    for g in sorted(proven, key=lambda x: x["id"]):
        p = g["detail"].get("proof") or {}
        add(f"  {g['id']}")
        add(f"      gate      {g['name']}  [{g['source']}]")
        add(f"      command   {p.get('command', '')}")
        add(f"      mutation  {_wrap(p.get('mutation', ''))}")
        add(f"      observed  {_wrap(p.get('observed', ''))}")
        add(f"      scope     {_wrap(p.get('scope') or 'none found — the gate fires for the whole class it names')}")
        add(f"      proved    {p.get('proved_on', '')}")
    add("")

    add("-- ATTEMPTED and NOT proved (a first-class result, not an omission) " + "-" * 10)
    if not attempted:
        add("  (none)")
    for g in sorted(attempted, key=lambda x: x["id"]):
        add(f"  {g['id']}")
        add(f"      {_wrap(g['evidence'], indent=' ' * 6)}")
    for gid in unattached:
        add(f"  {gid}   [no gate matches this id in the current sweep]")
        add(f"      {_wrap((census.get("attempted_unproven") or {}).get(gid, ""), indent=' ' * 6)}")
    add("")

    if orphan_proofs:
        add("-- !! STALE PROOFS: recorded verdict no longer matches the gate at that id " + "-" * 3)
        add("   A CI-step id is positional. These verdicts are REFUSED, not re-attached.")
        for o in orphan_proofs:
            add(f"  {o['id']}")
            add(f"      recorded gate: {o['recorded_name']}")
            add(f"      gate now here: {o['current_name']}")
        add("")

    add("-- by family " + "-" * 64)
    fam: dict[str, list[dict]] = {}
    for g in gates:
        fam.setdefault(g["family"], []).append(g)
    for name in sorted(fam):
        items = fam[name]
        fs = sum(1 for g in items if g["screened"])
        add(f"  {name:<18} n = {len(items):>4}   screened {fs:>4}   unscreened {len(items) - fs:>4}")
    add("")

    add("-- risk flags (leads for adjudication, NOT defects) " + "-" * 26)
    # Every DETECTABLE shape is printed, zeros included. A shape that simply vanishes
    # from the report when it finds nothing is indistinguishable from a shape whose
    # detector died — the exact confusion this census exists to end. The zeros are only
    # meaningful because each detector has a planted-positive proof in
    # tests/test_gate_census_2578.py.
    hist: dict[str, int] = {k: 0 for k, v in census["shapes"].items() if v["detectable"] != "no"}
    for g in screened:
        for f in g["risk_flags"]:
            hist[f] = hist.get(f, 0) + 1
    for f, c in sorted(hist.items(), key=lambda kv: (-kv[1], kv[0])):
        suffix = "   (detector proven live by a planted positive; zero here is a real result)" if c == 0 else ""
        add(f"  {f:<28} n = {c}{suffix}")
    add("")

    add("-- why gates could not be screened " + "-" * 43)
    reasons: dict[str, int] = {}
    for g in unscreened:
        reasons[g["unscreened_reason"]] = reasons.get(g["unscreened_reason"], 0) + 1
    for r, c in sorted(reasons.items(), key=lambda kv: -kv[1]):
        add(f"  n = {c:<5} {r}")
    if not reasons:
        add("  (none)")
    add("")

    add("-- failure shapes this census CANNOT see " + "-" * 37)
    for name, spec in (census["shapes"] or {}).items():
        if spec["detectable"] == "no":
            add(f"  {name:<28} ({spec['seed']}) — needs a semantic probe, not a syntactic one")
        elif spec["detectable"] == "partial":
            add(f"  {name:<28} ({spec['seed']}) — PARTIAL: syntactic proxy only, both-way error")
    add("")

    exp = census.get("annassign_exposure") or {}
    if exp:
        add("-- AnnAssign exposure (taxonomy instance 5, measured) " + "-" * 24)
        add(f"  source files whose AST walk sees `X = ...` but not `X: T = ...`   n = {exp['n_blind_walkers']}")
        add(f"  module-level CONSTANTS currently bound with an annotation         n = {exp['n_annotated_module_constants']}")
        add("  Every constant in the second set is invisible to every walker in the first.")
        for w in exp["blind_walkers"][:15]:
            add(f"    blind walker: {w}")
        if len(exp["blind_walkers"]) > 15:
            add(f"    ... and {len(exp['blind_walkers']) - 15} more (see --json; nothing is dropped from the count)")
        add("")

    add("-- raw discovery counters (what the sweep walked) " + "-" * 28)
    for family, c in census["counters"].items():
        add(f"  {family}: " + ", ".join(f"{k}={v}" for k, v in c.items()))
    if census["families_dropped"]:
        add(f"  DROPPED FAMILIES (bounded run): {census['families_dropped']}")
    add("")
    return "\n".join(lines)
