#!/usr/bin/env python3
"""deploy/direct_push_gate.py — #3528: ONE landing path for code.

WHY THIS EXISTS
----------------
The 2026-09-05 forensic RCA (`docs/reviews/FORENSIC_RCA_2026-09-05.md`, root-cause class 1,
"the ungated landing path") measured it: 302 of 613 commits since 08-22 were direct pushes
to main that met only a formatter, and 26 of 29 red Unit-Test runs on main were direct
pushes. The ADR-148 ruleset's only bypass actor is the owner's account (`bypass_mode:
always`), so an owner-authenticated push skips the required fast-lane checks server-side
and nothing on the client stood in for them.

The originally filed fix was a ~155 s pytest pre-push hook. #3528 was AMENDED on
2026-09-05 to "refuse, don't test": the PR lane already runs the full suite for free, and a
second copy of that gate on the path that skips it is hook-skippable duplication. So
this module is what `deploy/agent_commit.sh --push` runs when the current branch is
`main`, and it does exactly three things:

  1. CODE is REFUSED, by path. Any path in the push outside `DOCS_CLASS` lands through a
     PR, where `pr-checks.yml`'s premerge lane already runs. Exit 1, every code path named.
  2. DOCS pass through the Docs-CI stand-in: every gate `ci_gate_commands(docs-ci.yml)`
     derives — never a hand copy — run in parallel, the declared mutating gate last.
  3. THE RESET (`RESTART_PIPELINE=1`) is the one sanctioned code pusher. It runs the same
     Docs-CI stand-in PLUS the derived artifact-reader pytest leg
     (`restart_verify_gates.pytest_leg_command()`, #3529) and the v4 site gate's JS suite.
     An EMPTY derivation RAISES and the push is refused as UNEVALUABLE (exit 2) — the
     #3477 dead-man shape: "found no tests" is never "nothing to test".

WHAT "DOCS-CLASS" MEANS, AND WHY IT IS A DECLARED SET
------------------------------------------------------
There is no workflow file that states "these paths are not code" — CI/CD runs on every
push to main by design (#3378), and Docs CI's own path filter deliberately includes the
code half (lambdas/**, tests/**, …) because code can stale a doc (#1908). So the docs
class is a POLICY, declared once below with a reason per entry, and cross-checked against
the workflow it depends on: `tests/test_ci_stand_ins_derive.py` asserts every
`DOCS_CLASS` glob is covered by docs-ci.yml's `on.push.paths`, so the stand-in that runs
here is exactly the gate set CI runs for that path. A docs-class glob Docs CI does not
gate would make this stand-in a subset of nothing, and reds.

THE HONEST BOUND. The Docs-CI stand-in is a superset of Docs CI, NOT of CI/CD's Unit
Tests, which also run on a docs-only push. A doc edit that breaks a pytest assertion over
that doc (the Session M/N `CLAUDE.md` shape) still passes this gate and reds Unit Tests.
That residue is the amended issue's stated scope ("docs-only pushes run the derived
Docs-CI set in seconds"), recorded here rather than implied.

WHAT IT GRADES. The gates read the WORKING TREE. A pushed path that also carries unstaged
edits would be graded as a version that is not the one being pushed, so that is refused
(exit 1) with the paths named; unrelated dirt elsewhere in the tree is reported, not
refused.

USAGE
  python3 deploy/direct_push_gate.py [--staged] [--base REF] [--list]
    --staged   also count the index (agent_commit.sh runs this BEFORE committing)
    --base     the ref the push is measured against (default: $AGENT_COMMIT_BASE_REF or
               origin/main — the same default agent_commit.sh's restore block uses)
    --list     classify and print what would run; run nothing
  Exit 0 = pushable · 1 = refused (code path, a failing gate, a dirty pushed path) ·
  2 = UNEVALUABLE (no base ref, an empty/undeclared derivation) — never a pass.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "deploy"))

import restart_verify_gates as rvg  # noqa: E402  (the MUTATING_GATES / pytest-leg / JS-leg owner)
from ci_gate_commands import DOCS_CI_WORKFLOW, ci_gate_commands, glob_matches  # noqa: E402

PROTECTED_BRANCH = "main"
RESTART_ENV = "RESTART_PIPELINE"

# The docs class — a direct push to main containing ONLY these may land without a PR.
# Every glob must be covered by docs-ci.yml's `on.push.paths` (tests/test_ci_stand_ins_derive.py).
DOCS_CLASS: dict[str, str] = {
    "docs/**": "the wiki: prose + its JSON sidecars; all twelve Docs-CI gates read it",
    "README.md": "prose; dead-link/tombstone/fact gates",
    "CLAUDE.md": "prose; the literal-drift and fact gates own its numbers",
    ".claude/README.md": "prose; a sync_doc_metadata literal file",
    ".claude/skills/**": "the skill corpus; skill_lint --offline and its --self-test mutation proof gate it",
    ".claude/agents/**": "the agent corpus; skill_lint gates it alongside the skills",
    "lambdas/web/platform_counts.py": (
        "GENERATED counters (#3101): its only writer is `sync_doc_metadata.py --apply`, run by the "
        "reconcile bot with the doc literals it regenerates alongside; Docs CI's `sync_doc_metadata "
        "--check` is exactly its gate, so the reconcile push is docs-class by construction"
    ),
}


def classify(paths: list[str]) -> tuple[list[str], list[str]]:
    """(docs-class paths, code paths) — every path lands in exactly one."""
    docs, code = [], []
    for p in paths:
        (docs if any(glob_matches(g, p) for g in DOCS_CLASS) else code).append(p)
    return docs, code


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)


def pushed_paths(base: str, staged: bool) -> list[str]:
    """Every path any commit in `base..HEAD` touches (+ the index when `staged`).

    Per-commit, not the net diff: a code edit made and reverted inside the range still
    rode a commit onto main, and the premerge lane is where that belongs.
    """
    if _git("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}").returncode != 0:
        raise RuntimeError(f"cannot resolve base ref {base!r} — cannot know what this push carries")
    out = _git("log", "--name-only", "--format=", f"{base}..HEAD").stdout.splitlines()
    if staged:
        out += _git("diff", "--cached", "--name-only").stdout.splitlines()
    return sorted({p.strip() for p in out if p.strip()})


def unstaged_paths() -> set[str]:
    return {p.strip() for p in _git("diff", "--name-only").stdout.splitlines() if p.strip()}


def stand_in_commands(restart: bool) -> tuple[list[list[str]], list[list[str]]]:
    """(parallel read-only gates, sequential mutating tail) — the derived stand-in.

    Raises RuntimeError on an empty derivation (docs gates or, under restart, the
    artifact-reader pytest leg) and on an undeclared multi-line python step.
    """
    gates = ci_gate_commands(DOCS_CI_WORKFLOW)
    dark = rvg.undeclared_multiline_python_steps()
    if dark:
        names = ", ".join(n for n, _ in dark)
        raise RuntimeError(f"docs-ci.yml has undeclared `run: |` python step(s) this stand-in cannot derive: {names}")
    readonly = [c for c in gates if " ".join(c[1:]) not in rvg.MUTATING_GATES]
    tail = [c for c in gates if " ".join(c[1:]) in rvg.MUTATING_GATES]
    if restart:
        # #3529's derived set — reset_artifact_test_files() RAISES on empty; let it.
        readonly.append(rvg.pytest_leg_command())
        if shutil.which("node") is not None:
            readonly.append(list(rvg.JS_SUITE_CMD))
    return readonly, tail


def _run(cmd: list[str]) -> tuple[list[str], int, str, float]:
    t0 = time.monotonic()
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    return cmd, proc.returncode, (proc.stdout or "") + (proc.stderr or ""), time.monotonic() - t0


def _label(cmd: list[str]) -> str:
    if cmd[:3] == [sys.executable, "-m", "pytest"]:
        n = sum(1 for a in cmd if a.startswith("tests/"))
        return f"pytest (derived artifact readers, {n} file(s))"
    return " ".join(cmd[1:]) if cmd and cmd[0] == "python3" else " ".join(cmd)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--staged", action="store_true", help="also count the index (pre-commit use)")
    ap.add_argument("--base", default=os.environ.get("AGENT_COMMIT_BASE_REF", "origin/main"))
    ap.add_argument("--list", action="store_true", help="classify + print what would run; run nothing")
    args = ap.parse_args(argv)
    restart = os.environ.get(RESTART_ENV) == "1"
    tag = "[direct-push-gate]"

    try:
        paths = pushed_paths(args.base, args.staged)
    except RuntimeError as exc:
        print(f"{tag} ✗ UNEVALUABLE (not a pass): {exc}", file=sys.stderr)
        return 2
    docs, code = classify(paths)
    print(f"{tag} push to {PROTECTED_BRANCH} vs {args.base}: {len(paths)} path(s) — {len(docs)} docs-class, {len(code)} code")

    if code and not restart:
        print(f"{tag} ✗ REFUSED — a direct push to {PROTECTED_BRANCH} may carry docs only (#3528). Code path(s):", file=sys.stderr)
        for p in code:
            print(f"{tag}      {p}", file=sys.stderr)
        print(
            f"{tag}    Code lands through a PR, where pr-checks.yml's premerge lane already runs the suite.\n"
            f"{tag}    Move the work to a branch and open one:\n"
            f"{tag}      git switch -c issue-<N>-<slug>   # carries these commits with it\n"
            f'{tag}      bash deploy/agent_commit.sh --push "<msg>" <paths>   # on the branch this pushes it\n'
            f"{tag}      gh pr create …\n"
            f"{tag}    (then reset local {PROTECTED_BRANCH} to origin/{PROTECTED_BRANCH} once the branch is pushed.)\n"
            f"{tag}    The reset pipeline alone may push code here: {RESTART_ENV}=1 runs the derived artifact-reader\n"
            f"{tag}    pytest leg on top of the Docs-CI gates.",
            file=sys.stderr,
        )
        return 1
    if code:
        print(f"{tag} ⚠ {RESTART_ENV}=1 — the reset pipeline's code push, {len(code)} code path(s) under the derived reset stand-in:")
        for p in code:
            print(f"{tag}      {p}")

    if not paths:
        print(f"{tag} ✓ nothing beyond {args.base} to grade")
        return 0

    dirty = unstaged_paths()
    dirty_pushed = sorted(set(paths) & dirty)
    if dirty - set(paths):
        print(f"{tag} ⚠ {len(dirty - set(paths))} unpushed path(s) carry unstaged edits the gates will also read (reported, not refused)")
    if dirty_pushed:
        print(
            f"{tag} ✗ REFUSED — pushed path(s) also carry UNSTAGED edits; the gates would grade a version you are not pushing:",
            file=sys.stderr,
        )
        for p in dirty_pushed:
            print(f"{tag}      {p}", file=sys.stderr)
        return 1

    try:
        readonly, tail = stand_in_commands(restart)
    except RuntimeError as exc:
        print(f"{tag} ✗ UNEVALUABLE (not a pass): {exc}", file=sys.stderr)
        return 2

    if args.list:
        for c in readonly:
            print(f"{tag}   parallel   {' '.join(c)}")
        for c in tail:
            print(f"{tag}   last       {' '.join(c)}")
        return 0

    t0 = time.monotonic()
    before = rvg.porcelain()
    with ThreadPoolExecutor(max_workers=max(1, len(readonly))) as pool:
        results = list(pool.map(_run, readonly))
    results += [_run(c) for c in tail]  # the declared mutating gate: last, alone
    after = rvg.porcelain()
    wall = time.monotonic() - t0

    failures = [(c, rc, out) for c, rc, out, _ in results if rc != 0]
    for c, rc, _, secs in results:
        print(f"{tag}   {'✓' if rc == 0 else '✗'} {rc:<3} {secs:5.1f}s  {_label(c)}")
    if after != before:
        failures.append((["<tree>"], 1, f"the stand-in changed the working tree:\n--- before ---\n{before}\n--- after ---\n{after}"))
    if failures:
        print(f"{tag} ✗ REFUSED — {len(failures)} derived gate(s) red; this push would red CI ({wall:.1f}s):", file=sys.stderr)
        for c, _, out in failures:
            print(f"\n── {_label(c)} ──\n{out.strip()[-1500:]}", file=sys.stderr)
        return 1
    print(f"{tag} ✓ {len(results)} derived gate(s) green in {wall:.1f}s — pushable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
