#!/usr/bin/env python3
"""deploy/verify_doc_facts_derivable.py — #2578: a fact this job could not DERIVE is not
a fact it reconciled.

WHY THIS EXISTS, AND WHY IT IS NOT A DOC GATE
---------------------------------------------
#3234: `ci-cd.yml`'s reconcile job could not `import yaml`, so `gate_census_count` was
skipped — honestly, per #3156 — the generators then left the tree byte-identical, the job
printed "already match config truth" and went GREEN, and `test / Unit Tests` in the same
run failed on the drift it had declined to fix. Main went red twice on 2026-08-27 with a
green reconcile job above it. Installing the dep fixed that fact and gave the job no way
to notice the next one.

The obvious fix — run `sync_doc_metadata --check` in the reconcile job — is FORBIDDEN, and
correctly so. #1908 (three occurrences in three days: #1900, #1906, #1914) established
that a DOC GATE inside the deploy pipeline is a one-way trap: it fails on a code push, its
remediation is by definition a docs edit, `docs/**` is not in ci-cd.yml's `paths:` filter,
so the fix cannot re-run the workflow it fixed; `check_main_green.py` reads CI/CD only, so
main keeps reporting the stale failure until a manual `workflow_dispatch` — which also runs
Plan -> Deploy, charging a documentation fix a production approval (or stranding one,
#1901). `tests/test_docs_ci_owns_doc_gates.py` guards that, and it caught this. The gates'
single home is `docs-ci.yml`, which already runs `--check` as a blocking gate AND triggers
on both halves of the coupling (`docs/**` plus `lambdas/**`, `mcp/**`, `config/**`), so the
drift verdict is already where a docs-only fix can clear it. It is not moving.

THIS SCRIPT ASKS A DIFFERENT QUESTION. Not "does the committed tree match derived truth?"
(a statement about docs) but "could this job derive the facts it owns at all?" (a statement
about the job's own environment). It never reads a doc, never compares a literal, and never
looks at committed content. Its two failure modes are:

    an ImportError in this lane   ->  fix: install the dep in .github/workflows/ci-cd.yml
    a census family that skipped  ->  fix: scripts/ or tests/

Both fixes live under paths that ARE in ci-cd.yml's filter, so the failing push's own
remediation re-triggers the workflow and clears it. #1908's trap needs the remediation to
be a `docs/**` edit; here it structurally cannot be. That is the whole reason this is a
self-check and not a relocated doc gate.

WHY NOT PLAIN IDEMPOTENCE (`--apply` twice, assert no diff)
-----------------------------------------------------------
Because it does not catch #3234's class, and would have reported green through the actual
incident. With PyYAML absent, `sync_census_fact.apply()` SKIPS its rule entirely and leaves
the doc untouched — so the first `--apply` and the second produce the identical tree, and
idempotence is satisfied. The generator converges, on a consistent-but-stale value, because
it gave up. Idempotence cannot distinguish "converged" from "converged because I declined
to compute anything", and the skip is exactly the declining. That distinction is the defect,
so the check has to be on the DERIVATION, not on the output's stability.

STRUCTURAL, NOT PHRASE-MATCHED
------------------------------
A dependency failure is recognised by EXCEPTION TYPE (`ImportError`, of which
`ModuleNotFoundError` is a subclass), never by a substring of a message. Every
phrase-matched member of the #2959/#3003/#3199 demotion family has failed in the field.
That is also why this script calls `gate_census.build_census()` directly rather than
`sync_census_fact.discover_gate_census_count()`: the latter deliberately CATCHES the
exception and returns it as prose (correct for its caller, useless for a type check), so
the probe goes to the thing that actually raises.

THE PROBE SET IS DERIVED, NOT ENUMERATED
----------------------------------------
Every zero-argument `_auto_discover_*` / `_count_*` defined in `sync_doc_metadata` is a
probe, found by introspection. A sixteenth discoverer added tomorrow is probed the day it
lands, with nobody updating a list here — the same reason the census exists instead of a
hand-typed gate count.

WHAT THIS DOES NOT CATCH, STATED PLAINLY
----------------------------------------
A discoverer that returns `None` for a STRUCTURAL reason (unparseable source, a sanity
floor tripping) and falls back silently to the manual `PLATFORM_FACTS` value. Those are
REPORTED here and deliberately do not gate, because at least two of them (`_count_adrs`,
`_auto_discover_adr_max`) read `docs/DECISIONS.md` — gating on them would make a docs edit
able to red the deploy pipeline, which is #1908's trap rebuilt by hand. The residual is
real and is #2578 work; it is not this script's to close.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent


def _probe_functions(mod: Any) -> list[tuple[str, Callable[[], Any]]]:
    """Every zero-argument discoverer bound in `mod`'s namespace, by introspection.

    `co_argcount == 0` is the structural filter that keeps helpers like
    `_ast_literal_str_list_len(path, name)` out without naming them.

    Deliberately NOT filtered on `fn.__module__ == mod.__name__`. That filter was written
    first and measured wrong: `_auto_discover_alarm_count` lives in
    `deploy/alarm_discovery.py` (the #795/#934 extraction that paid for the module-size
    ceiling) and is re-exported here, so the filter silently dropped one of the sixteen
    facts — a probe set with a hole in it, which is the exact defect this whole file is
    about. Where a discoverer is DEFINED is an artifact of the size ratchet; what matters
    is that `sync_doc_metadata` calls it.
    """
    out = []
    for name, fn in sorted(vars(mod).items()):
        if not callable(fn) or not (name.startswith("_auto_discover_") or name.startswith("_count_")):
            continue
        code = getattr(fn, "__code__", None)
        if code is None or code.co_argcount != 0:
            continue
        out.append((name, fn))
    return out


def probe_all(root: Path | None = None) -> dict[str, Any]:
    """Run every probe. Returns a report; raises nothing.

    ``dependency_failures``  probes that failed with an ImportError — THE gate condition.
    ``families_skipped``     census families that could not run (an incomplete sweep is a
                             floor, not a count — measured 554 -> 450 on 2026-08-27).
    ``fallbacks``            probes that returned None without an ImportError — reported,
                             never gating (see the module docstring).
    ``derived``              probes that produced a value.
    """
    root = root or ROOT
    for sub in ("deploy", "scripts"):
        p = str(root / sub)
        if p not in sys.path:
            sys.path.insert(0, p)

    report: dict[str, Any] = {"dependency_failures": [], "families_skipped": [], "fallbacks": [], "derived": []}

    try:
        import sync_doc_metadata
    except ImportError as exc:
        report["dependency_failures"].append({"fact": "sync_doc_metadata (the module itself)", "error": f"{type(exc).__name__}: {exc}"})
        return report

    for name, fn in _probe_functions(sync_doc_metadata):
        try:
            value = fn()
        except ImportError as exc:
            report["dependency_failures"].append({"fact": name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        except Exception as exc:  # noqa: BLE001 — a probe must never take the job down by surprise
            report["fallbacks"].append({"fact": name, "why": f"raised {type(exc).__name__}: {exc}"})
            continue
        if value is None:
            report["fallbacks"].append({"fact": name, "why": "returned None — the manual PLATFORM_FACTS value stands"})
        else:
            report["derived"].append({"fact": name, "value": repr(value)[:60]})

    # The census, probed at the thing that actually raises rather than at the wrapper that
    # turns the exception into prose. This is the #3234 fact.
    try:
        import gate_census

        census = gate_census.build_census(root)
    except ImportError as exc:
        report["dependency_failures"].append({"fact": "gate_census_count", "error": f"{type(exc).__name__}: {exc}"})
    except Exception as exc:  # noqa: BLE001
        report["fallbacks"].append({"fact": "gate_census_count", "why": f"raised {type(exc).__name__}: {exc}"})
    else:
        skipped = census.get("families_skipped") or []
        report["families_skipped"] = list(skipped)
        report["derived"].append({"fact": "gate_census_count", "value": str(len(census.get("gates") or []))})

    return report


def verdict(report: dict[str, Any]) -> tuple[bool, str]:
    """Pure decision over a report. `(ok, message)`.

    Takes the report as an argument so the RULE can be mutation-proven against a synthetic
    one, never only against whatever today's environment happens to produce.
    """
    deps = report.get("dependency_failures") or []
    skipped = report.get("families_skipped") or []
    if not deps and not skipped:
        return True, f"every doc-sync fact this job owns was DERIVED here ({len(report.get('derived') or [])} probes)"

    lines = ["this job cannot derive a fact it is responsible for reconciling, so its 'success' would be a lie (#3234/#2578):"]
    for d in deps:
        lines.append(f"  MISSING DEPENDENCY  {d['fact']}: {d['error']}")
    for s in skipped:
        lines.append(f"  INCOMPLETE SWEEP    gate census family '{s['family']}' could not run: {s['reason']}")
    lines.append("")
    lines.append("A missing dependency is fixed in .github/workflows/ci-cd.yml (the shared setup-ci composite installs")
    lines.append("NO packages — add the pin the way the 'Install census dependency (PyYAML)' step does). An incomplete")
    lines.append("sweep is fixed under scripts/ or tests/. Both are inside this workflow's paths filter, so the fixing")
    lines.append("push re-runs this job and clears it — no docs edit, no manual dispatch, no production approval.")
    return False, "\n".join(lines)


def main() -> int:
    report = probe_all()
    for row in report["derived"]:
        print(f"  [derived] {row['fact']} = {row['value']}")
    for row in report["fallbacks"]:
        # Reported, never gating — the residual class named in the module docstring.
        print(f"  [fallback] {row['fact']}: {row['why']}")
    ok, message = verdict(report)
    if ok:
        print(f"\n✅ {message}")
        return 0
    print(f"\n::error::{message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
