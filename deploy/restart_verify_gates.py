#!/usr/bin/env python3
"""deploy/restart_verify_gates.py — #3477: the reset runs the gates CI will run.

WHY THIS EXISTS
  `restart_pipeline.py` ran exactly ONE doc gate at its tail (`sync_doc_metadata.py
  --apply`, folded in by #1287). Docs CI runs twelve. So the pipeline could — and on the
  2026-09-03 cycle-16 re-anchor did — exit 0 having produced a commit that reds main by
  construction: `docs/SCHEMA.md`'s genesis anchor, three `test_wiki_checkers` cases, the
  MCP tool catalog, and (outside Docs CI) six genesis-anchored JS fixtures.

  ADR-058's claim is that the reset is ONE command. A command that reliably leaves main
  red is one command plus undocumented cleanup the next cycle rediscovers.

THE DERIVATION GUARD (charter primitive, and the reason this is not a hand-typed list)
  The gate list is PARSED OUT OF `.github/workflows/docs-ci.yml`, not restated here. A
  hand-copied list is drift-in-waiting: CI adds a thirteenth gate, this file keeps
  checking twelve, and the reset goes back to exiting 0 over it — the same rot that let
  the original one-gate tail survive. `docs_ci_gate_commands()` raises rather than
  returning a short list, so "found nothing" can never read as "nothing to run".

  The JS suite is the one deliberate ADDITION beyond Docs CI: the genesis-anchored
  instants live in the v4 site gate, not Docs CI, and they are broken BY the reset every
  single time (`tests/js/genesis_pt_2941.test.mjs`'s own first assertion is the drift
  detector, and the file says regenerate them, don't loosen). It runs that gate's whole
  `node --test`, not a chosen file — see JS_SUITE_CMD for why a subset was not enough.

POSTURE
  Read-only and side-effect free — every command is a `--check`/verify form. It reports
  ALL failures together (the #3007 batch shape) rather than dying on the first, because
  a reset operator wants the whole list in one pass.

  Exit 0 = the tree this reset produced will not red Docs CI. Exit 1 = it will, and the
  failing gates are named. Exit 2 = the gate list itself could not be derived, which is
  NOT a pass (absence-read-as-success is the class this whole file is about).
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "docs-ci.yml"

# A single-line `run:` step invoking a python checker. Multi-line (`run: |`) steps are
# deliberately NOT matched: they are shell blocks (the deprecated-secret sweep), not the
# doc checkers this mirrors, and running them here would be a different contract.
_RUN_LINE = re.compile(r"^\s*run:\s*(python3\s+\S+.*?)\s*$")

# The JS suite is NOT in Docs CI — it is the v4 site gate's `node --test` step — and the
# reset breaks it every cycle through the genesis-anchored instants. Run the WHOLE suite,
# exactly as that workflow does.
#
# #3479: this was scoped to `genesis_pt_2941.test.mjs` alone, on the reasoning that only the
# genesis fixtures are reset-sensitive. That reasoning was wrong in a way worth recording:
# on the 2026-09-05 re-anchor the sweep passed, and the v4 site gate then redded on
# `coach_asof.test.mjs` — a hardcoded stamp that had silently aged out of an 8-day cadence
# window. Not reset-caused at all, but squarely inside what the reset commit was about to be
# blamed for. A sweep that runs a SUBSET of a gate cannot promise anything about that gate.
JS_SUITE_CMD = ["node", "--test"]


def docs_ci_gate_commands() -> list[list[str]]:
    """Every `run: python3 …` gate in docs-ci.yml, in workflow order.

    Raises when the workflow cannot be read or yields no gates — a derived list that
    silently comes back empty would turn this whole check into a no-op.
    """
    if not WORKFLOW.is_file():
        raise RuntimeError(f"cannot read {WORKFLOW} — the gate list is derived from it, never hand-typed")
    cmds: list[list[str]] = []
    for line in WORKFLOW.read_text(encoding="utf-8").splitlines():
        m = _RUN_LINE.match(line)
        if m:
            cmds.append(m.group(1).split())
    if not cmds:
        raise RuntimeError(f"derived ZERO gates from {WORKFLOW} — the workflow shape changed; fix the parser, do not pass")
    return cmds


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-js", action="store_true", help="skip the JS suite (node unavailable)")
    args = ap.parse_args()

    try:
        gates = docs_ci_gate_commands()
    except RuntimeError as exc:
        print(f"✗ UNEVALUABLE (not a pass): {exc}")
        return 2

    print(f"── reset doc-gate sweep (#3477) — {len(gates)} gate(s) derived from docs-ci.yml ──")
    failures: list[tuple[str, str]] = []
    for cmd in gates:
        rc, out = _run(cmd)
        label = " ".join(cmd[1:])
        print(f"  {'✓' if rc == 0 else '✗'} {rc:<3} {label}")
        if rc != 0:
            failures.append((label, out[-1200:]))

    if not args.skip_js:
        if shutil.which("node") is None:
            print("  ⚠ node unavailable — the JS suite was SKIPPED (loudly, not silently)")
        else:
            rc, out = _run(JS_SUITE_CMD)
            label = " ".join(JS_SUITE_CMD)
            print(f"  {'✓' if rc == 0 else '✗'} {rc:<3} {label}  (the v4 site gate's step)")
            if rc != 0:
                failures.append((label, out[-1800:]))

    if failures:
        print(f"\n❌ {len(failures)} gate(s) will red on the commit of these reset artifacts:")
        for label, out in failures:
            print(f"\n── {label} ──\n{out.strip()[-800:]}")
        print(
            "\nFix them BEFORE committing the reset. The two that recur every cycle:\n"
            "  · the genesis literal — `python3 deploy/sync_doc_metadata.py --apply` now converges it (#3477);\n"
            "    if it is still stale the freshness-hold narrowing regressed.\n"
            "  · docs/engines/CHARACTER.md — the reset rewrites config/character_sheet.json, so its\n"
            "    `Verified:` stamp must be RE-DERIVED (not date-bumped): confirm the config diff is\n"
            "    confined to _meta + baseline, the line count is unchanged (no citation shifts), and\n"
            "    character_engine.py / character_sheet_lambda.py took zero commits since the last verify.\n"
            "  · the JS instants are REGENERATED for the new genesis, never loosened — the file says so."
        )
        return 1

    print("\n✅ every derived doc gate passes — this reset's tree will not red Docs CI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
