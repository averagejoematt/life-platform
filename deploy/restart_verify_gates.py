#!/usr/bin/env python3
"""deploy/restart_verify_gates.py — #3477/#3529/#3534: the reset runs the gates CI will run.

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

  This module is the ONE derivation for the whole repo. `scripts/wrap_gates.py` builds
  its doc leg from `docs_ci_gate_commands()` too (#3531) rather than hand-listing four of
  the twelve, which is how the wrap battery came to report green over eight gates CI
  fails on.

  #3534: a `run: |` BLOCK invoking python3 would previously have been invisible to the
  line parser — derived silently as "not a gate". `undeclared_multiline_python_steps()`
  makes that state loud: any such step must be named in `MULTILINE_RUN_EXEMPT` with a
  written reason, or the sweep exits 2 (UNEVALUABLE), never 0.

THE THREE LEGS BEYOND DOCS CI, EACH DECLARED
  1. THE JS SUITE. The genesis-anchored instants live in the v4 site gate, not Docs CI,
     and they are broken BY the reset every single time (`tests/js/genesis_pt_2941.test.mjs`'s
     own first assertion is the drift detector, and the file says regenerate them, don't
     loosen). It runs that gate's whole `node --test`, not a chosen file — see
     JS_SUITE_CMD for why a subset was not enough.
  2. THE PYTEST LEG (#3529). Docs CI's twelve gates do not read `deploy/generated/**`, so
     the reset shipped past every python test that does — and both resets in the window
     red-mained on exactly those: 13 tests on 2026-08-31 (fa52f5ad8) across
     test_plan_literal_reconciliation / test_prereg_hash_stamp / test_prereg_seal_1980,
     then `test_sealed_prereg_agrees_with_the_plan_root` on 5 consecutive runs on
     2026-09-04. The file set is DERIVED (see `reset_artifact_test_files()`), never
     hand-listed, and it is a NAMED SELECTION, not the suite: see the block comment there
     for exactly what it covers and what it deliberately does not.
  3. THE MUTATING GATE, LAST. `skill_lint.py --self-test` is a mutation proof that edits a
     TRACKED file in place and restores it. It is Docs CI's gate, so the sweep runs it —
     but last, and with the tree verified restored afterwards (`MUTATING_GATES`).

POSTURE — READ-ONLY BY EFFECT, NOT BY PHRASE (#3534)
  Every command is a `--check`/verify form. That used to be asserted by grepping the argv
  for `--apply`, which is a phrase test: `skill_lint.py --self-test` carries no `--apply`
  and mutates a tracked file anyway. So the sweep now MEASURES it: `git status --porcelain`
  is snapshotted before the run and compared after every gate. A gate outside
  `MUTATING_GATES` that moves the tree is a FAILURE, named — because this sweep runs
  inside a reset, after the writes, and a second undeclared writer there has no ordering
  contract with the first.

  It reports ALL failures together (the #3007 batch shape) rather than dying on the first,
  because a reset operator wants the whole list in one pass.

  Exit 0 = the tree this reset produced will not red Docs CI, the v4 site gate, or the
  python tests that read its regenerated artifacts. Exit 1 = it will, and the failing
  gates are named. Exit 2 = the gate list itself could not be derived, which is NOT a
  pass (absence-read-as-success is the class this whole file is about).
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

# A single-line `run:` step invoking a python checker.
_RUN_LINE = re.compile(r"^\s*run:\s*(python3\s+\S+.*?)\s*$")

# A block scalar (`run: |`) — captured separately so it can never be silently ignored.
_BLOCK_RUN = re.compile(r"^(\s*)run:\s*[|>][-+]?\s*$")
_STEP_NAME = re.compile(r"^\s*-\s*name:\s*(.+?)\s*$")

# #3534. A `run: |` block whose body invokes python3 is, to the line parser above, simply
# absent — the exact "derived silently as nothing" shape #3477 was filed about, one level
# down. Every such block must be named here with a reason, or the sweep refuses to run.
# `tests/test_restart_verify_gates_3477.py` asserts each key still exists as a step name
# in the live workflow, so a rename cannot leave a stale exemption quietly covering a
# real gate.
MULTILINE_RUN_EXEMPT = {
    "Install census dependency (PyYAML)": (
        "a dependency bootstrap, not a gate: it runs `scripts/ci_pins.py` only to print the "
        "pin for `pip install`. Executing it here would mutate the interpreter's site-packages "
        "— the opposite of this sweep's read-only contract — and it asserts nothing about the tree."
    ),
}

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

# #3534: gates that Docs CI runs and that WRITE, keyed by the argv tail this module labels
# them with. Each one is run LAST and the tree is asserted restored afterwards. This set is
# the declared exception to the read-only-by-effect measurement below — declared, named and
# reasoned, so "the sweep mutated something" is never a shrug.
MUTATING_GATES = {
    "scripts/skill_lint.py --self-test": (
        "the skill-corpus mutation proof: it plants a defect in a TRACKED SKILL.md, asserts "
        "skill_lint reports it, and restores the file in a `finally` from an on-disk backup. "
        "docs-ci.yml says so in its own comment ('Kept out of pytest because it mutates a "
        "tracked file in place')."
    ),
}

# ── the pytest leg (#3529) ───────────────────────────────────────────────────────────
#
# THE DERIVATION, in three hops, none of them a list of test files:
#
#   1. GENERATED_DIR_REL — `deploy/generated/`, the directory the reset regenerates its
#      committed artifacts into (the frozen pre-registration, its SHA-256 stamp, the
#      channel-divergence prereg). This one root is DECLARED, because it is the subject:
#      it is what #3529 is about and what both red-mains read.
#   2. reset_artifact_writers() — every `deploy/*.py` whose SOURCE constructs a path under
#      that directory. Derived, so a new generator joins the moment it is written.
#   3. reset_artifact_test_files() — every `tests/test_*.py` whose SOURCE names the root or
#      any writer from (2). Derived, so a new test over those artifacts joins the moment it
#      is written. Both hops raise on an empty result rather than returning [].
#
# WHAT THIS SELECTION IS, AND IS NOT — say it plainly, because a silent partial that reads
# as full coverage is the defect this file exists to fix:
#   IS      the python tests that read the artifacts THIS RESET REGENERATES.
#   IS NOT  the suite (~25 min). It is not the site tests, not the lambda behaviour suite,
#           not the ratchets. The reset's other surfaces are covered by the twelve derived
#           doc gates (docs/**, CLAUDE.md, the model, the catalogs) and by the JS leg
#           (the genesis-anchored site instants). What remains uncovered by construction is
#           any python test that reads a reset-rewritten file OUTSIDE deploy/generated/ —
#           `config/character_sheet.json`, `lambdas/common/constants.py` — and that is the
#           honest bound of this leg, stated rather than implied.
# Measured 2026-09-05 on the derived set: 88 tests, 2.1s wall clock. It is affordable
# inside a reset precisely because it is a selection.
GENERATED_DIR_REL = "deploy/generated"
_WRITES_GENERATED = re.compile(r'"generated"|deploy/generated')
PYTEST_LEG_FLAGS = ["-q", "--no-header", "-p", "no:cacheprovider"]


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


def multiline_python_steps() -> list[tuple[str, str]]:
    """[(step name, block body)] for every `run: |` block whose body invokes python3.

    The line parser above cannot see these. Enumerating them is how the sweep proves it
    knows what it is NOT running, instead of reporting a clean derivation over a workflow
    that grew a gate it is blind to.
    """
    if not WORKFLOW.is_file():
        raise RuntimeError(f"cannot read {WORKFLOW} — the gate list is derived from it, never hand-typed")
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    found: list[tuple[str, str]] = []
    name = "<unnamed step>"
    i = 0
    while i < len(lines):
        nm = _STEP_NAME.match(lines[i])
        if nm:
            name = nm.group(1).strip().strip("\"'")
        blk = _BLOCK_RUN.match(lines[i])
        if blk:
            indent = len(blk.group(1))
            body: list[str] = []
            i += 1
            while i < len(lines):
                cur = lines[i]
                if cur.strip() and (len(cur) - len(cur.lstrip())) <= indent:
                    break
                body.append(cur)
                i += 1
            text = "\n".join(body)
            if re.search(r"(?<![\w./-])python3(?![\w-])", text):
                found.append((name, text))
            continue
        i += 1
    return found


def undeclared_multiline_python_steps() -> list[tuple[str, str]]:
    """The subset of `multiline_python_steps()` with no written exemption. Must be empty."""
    return [(n, b) for n, b in multiline_python_steps() if n not in MULTILINE_RUN_EXEMPT]


def reset_artifact_writers(root: Path | None = None) -> list[str]:
    """Every `deploy/*.py` that constructs a path under `deploy/generated/`.

    Derived from source text, so a new generator for the reset's committed artifacts is
    covered the day it lands. Raises on an empty result: zero writers of a directory that
    demonstrably has writers means the detector went blind, and a blind detector that
    returns [] would take the pytest leg silently to zero files.
    """
    repo = root or REPO_ROOT
    out = []
    for p in sorted((repo / "deploy").glob("*.py")):
        if p.name == Path(__file__).name:
            continue
        if _WRITES_GENERATED.search(p.read_text(encoding="utf-8", errors="replace")):
            out.append(f"deploy/{p.name}")
    if not out:
        raise RuntimeError(f"derived ZERO writers of {GENERATED_DIR_REL}/ — the detector went blind; fix it, do not pass")
    return out


def reset_artifact_test_files(root: Path | None = None) -> list[str]:
    """Every `tests/test_*.py` naming `deploy/generated/` or one of its writers.

    Raises on an empty result for the same reason as above — this is the whole pytest leg,
    and an empty leg reporting "0 tests, all passed" is the #3477 defect wearing a costume.
    """
    repo = root or REPO_ROOT
    needles = [f"{GENERATED_DIR_REL}/"] + reset_artifact_writers(repo)
    out = []
    for p in sorted((repo / "tests").glob("test_*.py")):
        src = p.read_text(encoding="utf-8", errors="replace")
        if any(n in src for n in needles):
            out.append(f"tests/{p.name}")
    if not out:
        raise RuntimeError(f"derived ZERO tests over {GENERATED_DIR_REL}/ — the detector went blind; fix it, do not pass")
    return out


def pytest_leg_command(root: Path | None = None) -> list[str]:
    """The argv for the pytest leg — the derived file set, run by THIS interpreter."""
    return [sys.executable, "-m", "pytest", *reset_artifact_test_files(root), *PYTEST_LEG_FLAGS]


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def porcelain() -> str:
    """`git status --porcelain` for REPO_ROOT — the read-only-by-EFFECT measurement.

    Returns a sentinel string (never "") when git cannot answer, so an unreadable tree
    compares equal to itself and no gate is falsely accused, while a real change is a real
    string difference. Caches nothing: the whole point is to re-measure after each gate.
    """
    proc = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        return "<git status unavailable>"
    return proc.stdout


def _pytest_available() -> bool:
    return subprocess.run([sys.executable, "-c", "import pytest"], capture_output=True).returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-js", action="store_true", help="skip the JS suite (node unavailable)")
    ap.add_argument("--skip-pytest", action="store_true", help="skip the derived artifact-reader pytest leg")
    ap.add_argument("--list", action="store_true", help="print every leg this sweep would run, and exit")
    args = ap.parse_args()

    if args.list:
        try:
            return _print_list()
        except RuntimeError as exc:
            print(f"✗ UNEVALUABLE (not a pass): {exc}")
            return 2

    try:
        gates = docs_ci_gate_commands()
        dark = undeclared_multiline_python_steps()
    except RuntimeError as exc:
        print(f"✗ UNEVALUABLE (not a pass): {exc}")
        return 2

    if dark:
        print("✗ UNEVALUABLE (not a pass): docs-ci.yml has `run: |` step(s) invoking python3 that this sweep cannot derive:")
        for name, body in dark:
            print(f"    · {name}\n      {body.strip().splitlines()[0][:110]}")
        print("  Either give the step a single-line `run: python3 …` form, or declare it in MULTILINE_RUN_EXEMPT with a reason.")
        return 2

    readonly = [c for c in gates if " ".join(c[1:]) not in MUTATING_GATES]
    mutating = [c for c in gates if " ".join(c[1:]) in MUTATING_GATES]

    print(f"── reset gate sweep (#3477/#3529) — {len(gates)} doc gate(s) derived from docs-ci.yml ──")
    baseline = porcelain()
    failures: list[tuple[str, str]] = []

    def record(label: str, rc: int, out: str, suffix: str = "") -> None:
        print(f"  {'✓' if rc == 0 else '✗'} {rc:<3} {label}{suffix}")
        if rc != 0:
            failures.append((label, out[-1800:]))

    for cmd in readonly:
        rc, out = _run(cmd)
        label = " ".join(cmd[1:])
        record(label, rc, out)
        after = porcelain()
        if after != baseline:
            failures.append(
                (
                    f"{label} (READ-ONLY VIOLATION)",
                    "this gate changed the working tree. The sweep runs inside a reset, AFTER the writes:\n"
                    "a second, undeclared writer here has no ordering contract with the first.\n"
                    f"--- git status --porcelain before ---\n{baseline}\n--- after ---\n{after}",
                )
            )
            print(f"    ⚠ {label} MUTATED the working tree — declare it in MUTATING_GATES or make it read-only")
            baseline = after

    # #3529: the python tests that read the artifacts this reset just regenerated.
    if args.skip_pytest:
        print("  ⚠ the derived pytest leg was SKIPPED by --skip-pytest (loudly, not silently)")
    elif not _pytest_available():
        print(f"  ⚠ pytest not importable by {sys.executable} — the artifact-reader leg was SKIPPED (loudly, not silently)")
    else:
        try:
            cmd = pytest_leg_command()
        except RuntimeError as exc:
            print(f"✗ UNEVALUABLE (not a pass): {exc}")
            return 2
        files = [c for c in cmd if c.startswith("tests/")]
        rc, out = _run(cmd)
        record("pytest (derived artifact readers)", rc, out, f"  ({len(files)} file(s): {', '.join(Path(f).name for f in files)})")

    if not args.skip_js:
        if shutil.which("node") is None:
            print("  ⚠ node unavailable — the JS suite was SKIPPED (loudly, not silently)")
        else:
            rc, out = _run(JS_SUITE_CMD)
            record(" ".join(JS_SUITE_CMD), rc, out, "  (the v4 site gate's step)")

    # LAST, and only after everything that must observe an unmutated tree has run.
    for cmd in mutating:
        label = " ".join(cmd[1:])
        rc, out = _run(cmd)
        record(label, rc, out, f"  (declared mutating: {MUTATING_GATES[label].split(':')[0]})")
        after = porcelain()
        if after != baseline:
            failures.append(
                (
                    f"{label} (DID NOT RESTORE THE TREE)",
                    "this gate mutates a tracked file and is contracted to restore it. It did not.\n"
                    f"--- git status --porcelain before ---\n{baseline}\n--- after ---\n{after}",
                )
            )
            print(f"    ⚠ {label} left the working tree changed — restore it BEFORE committing the reset")
            baseline = after

    if failures:
        print(f"\n❌ {len(failures)} gate(s) will red on the commit of these reset artifacts:")
        for label, out in failures:
            print(f"\n── {label} ──\n{out.strip()[-900:]}")
        print(
            "\nFix them BEFORE committing the reset. The ones that recur every cycle:\n"
            "  · the genesis literal — `python3 deploy/sync_doc_metadata.py --apply` now converges it (#3477);\n"
            "    if it is still stale the freshness-hold narrowing regressed.\n"
            "  · docs/engines/CHARACTER.md — the reset rewrites config/character_sheet.json, so its\n"
            "    `Verified:` stamp must be RE-DERIVED (not date-bumped): confirm the config diff is\n"
            "    confined to _meta + baseline, the line count is unchanged (no citation shifts), and\n"
            "    character_engine.py / character_sheet_lambda.py took zero commits since the last verify.\n"
            "    (#3534: check_doc_index now SEES that uncommitted rewrite, so this reds here rather\n"
            "    than surviving to CI as a hand-remembered step.)\n"
            "  · the JS instants are REGENERATED for the new genesis, never loosened — the file says so.\n"
            "  · the prereg artifacts under deploy/generated/ — re-seed/re-stamp, never edit the test (#3529)."
        )
        return 1

    print("\n✅ every derived gate passes — this reset's tree will not red Docs CI, the v4 site gate, or its artifact readers.")
    return 0


def _print_list() -> int:
    for cmd in docs_ci_gate_commands():
        tail = " ".join(cmd[1:])
        kind = "docs-ci (mutating, run last)" if tail in MUTATING_GATES else "docs-ci"
        print(f"{kind:30} {' '.join(cmd)}")
    print(f"{'pytest (derived)':30} {' '.join(pytest_leg_command())}")
    print(f"{'v4 site gate':30} {' '.join(JS_SUITE_CMD)}")
    for name, reason in MULTILINE_RUN_EXEMPT.items():
        print(f"{'NOT run (declared)':30} {name} — {reason.split(':')[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
