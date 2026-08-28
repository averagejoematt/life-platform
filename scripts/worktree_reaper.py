#!/usr/bin/env python3
"""scripts/worktree_reaper.py — inventory and safely retire git worktrees.

THE PROBLEM (measured 2026-08-27)
  85 live worktrees, ~3.8 GB, across EIGHT parent directories with eight naming
  conventions — including `/Users/<u>/documents/claude/...` alongside
  `/Users/<u>/Documents/Claude/...`, the macOS case-twin whose edit-leakage into the
  shared main tree is a documented incident class. `git worktree prune` reclaims zero of
  them, because every one still exists on disk. Almost all are for long-closed issues.

  This is not tidiness. Both failures below happened in a single session:

    * `tests/test_hevy_compiler_isolation.py` failed locally and passed in CI, because a
      stale in-repo worktree at `.worktrees/` is a full second checkout that the repo-wide
      sweep walked. #953 had already fixed this once, by name, for `.claude/worktrees/`.
    * `scripts/skill_lint.py` PASSED locally and failed in CI, because a skill pointed at
      `.claude/worktrees/`, which exists only on a machine carrying stale worktrees.

  Both are the same shape and it is the worse direction: the polluted developer machine
  is the one that looks clean.

SAFETY
  This removes work, so every check fails CLOSED and the default is a dry run. A worktree
  is only ever a candidate when ALL of these hold, and each is reported per row:
    * it is not the main checkout, and not the current working tree;
    * it has NO uncommitted changes (tracked or untracked);
    * its branch has NO commits absent from origin/main — nothing unpushed, nothing
      unmerged. A branch that is merely "merged by name" is not enough: the check is
      `git log origin/main..<branch>` being empty, so a rebase-merge or a squash-merge
      that left the tip unreachable still counts as unmerged and is KEPT.
  Anything failing a check is listed with the reason and never touched. `--apply` is
  required to remove; there is no flag that skips the checks.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _git(*args: str, cwd: Path | None = None) -> tuple[int, str]:
    r = subprocess.run(["git", *args], cwd=cwd or ROOT, capture_output=True, text=True, timeout=60)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def worktrees() -> list[dict]:
    """Parse `git worktree list --porcelain` into rows."""
    _, out = _git("worktree", "list", "--porcelain")
    rows, cur = [], {}
    for line in out.splitlines():
        if not line.strip():
            if cur:
                rows.append(cur)
                cur = {}
            continue
        key, _, val = line.partition(" ")
        if key == "worktree":
            cur = {"path": val, "branch": None, "detached": False, "bare": False}
        elif key == "branch":
            cur["branch"] = val.replace("refs/heads/", "")
        elif key == "detached":
            cur["detached"] = True
        elif key == "bare":
            cur["bare"] = True
    if cur:
        rows.append(cur)
    return rows


def _is_dirty(path: Path) -> bool:
    code, out = _git("status", "--porcelain", cwd=path)
    return code != 0 or bool(out.strip())


def _unmerged_commits(branch: str | None) -> int | None:
    """Commits on `branch` that origin/main does not already contain. None if unknowable."""
    if not branch:
        return None
    code, out = _git("log", "--oneline", f"origin/main..{branch}")
    if code != 0:
        return None
    return len([ln for ln in out.splitlines() if ln.strip()])


_PR_CACHE: dict[str, str | None] = {}


def _pr_state(branch: str | None) -> str | None:
    """GitHub's merge verdict for a branch, or None if it cannot be established.

    Fails CLOSED in every unknowable case (no gh, no network, no PR, ambiguous): the
    caller treats None as "keep". A reaper that guesses is a reaper that deletes work.
    """
    if not branch:
        return None
    if branch in _PR_CACHE:
        return _PR_CACHE[branch]
    try:
        r = subprocess.run(
            ["gh", "pr", "list", "--head", branch, "--state", "all", "--json", "state", "-q", ".[].state"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        states = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()] if r.returncode == 0 else []
        # Exactly one verdict, and it must be MERGED. Several PRs on one branch head is
        # ambiguous, so it is unknowable rather than a majority vote.
        _PR_CACHE[branch] = states[0] if len(states) == 1 else None
    except Exception:
        _PR_CACHE[branch] = None
    return _PR_CACHE[branch]


def classify(main_path: Path, cwd: Path) -> list[dict]:
    rows = []
    for wt in worktrees():
        p = Path(wt["path"])
        row = dict(wt, path_obj=p, reasons=[], reapable=False, in_repo=False, exists=p.exists())
        if p == main_path:
            row["reasons"].append("the main checkout")
        elif p == cwd:
            row["reasons"].append("the current working tree")
        if not p.exists():
            row["reasons"].append("directory is gone — `git worktree prune` clears this row")
        try:
            p.relative_to(main_path)
            row["in_repo"] = True
            row["reasons"].append("INSIDE the repo — repo-wide sweeps walk it (the #953 class)")
        except ValueError:
            pass
        if p != main_path and p.exists():
            if _is_dirty(p):
                row["reasons"].append("has uncommitted changes — KEEP")
            else:
                n = _unmerged_commits(wt["branch"])
                if wt["detached"]:
                    row["reasons"].append("detached HEAD — cannot prove it is merged, KEEP")
                elif n is None:
                    row["reasons"].append("branch state unknowable — KEEP")
                elif n > 0:
                    # A SQUASH merge (this repo's default) rewrites the work into one new
                    # commit, so the branch tip is never reachable from main and the
                    # ancestry test above says "unmerged" for every branch that ever
                    # shipped. Measured: it reported 0 of 93 reapable, which is a tool
                    # that cannot be used. GitHub's own merge verdict is the authority
                    # for that case; ancestry stays the authority when it says yes.
                    state = _pr_state(wt["branch"])
                    if state == "MERGED":
                        row["reapable"] = True
                        row["reasons"].append(f"squash-merged (PR MERGED); {n} unreachable commit(s) is expected")
                    elif state is None:
                        row["reasons"].append(f"{n} commit(s) not in origin/main, and no merge verdict available — KEEP")
                    else:
                        row["reasons"].append(f"{n} commit(s) not in origin/main, PR is {state} — KEEP")
                else:
                    row["reapable"] = True
                    row["reasons"].append("every commit already in origin/main")
        rows.append(row)
    return rows


def case_twins(rows: list[dict]) -> list[tuple[str, str]]:
    """Paths differing only by case — on macOS these are the SAME directory.

    The documented failure is edits made through one spelling leaking into the tree the
    other spelling names, which reads as the main checkout mutating itself.
    """
    seen: dict[str, str] = {}
    out = []
    for r in rows:
        k = str(r["path"]).lower()
        if k in seen and seen[k] != str(r["path"]):
            out.append((seen[k], str(r["path"])))
        else:
            seen[k] = str(r["path"])
    return out


def parents(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        counts[str(Path(r["path"]).parent)] = counts.get(str(Path(r["path"]).parent), 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def main() -> int:
    ap = argparse.ArgumentParser(description="Inventory and safely retire git worktrees.")
    ap.add_argument("--apply", action="store_true", help="actually remove the reapable ones (default: dry run)")
    ap.add_argument("--check", action="store_true", help="exit 1 if any worktree is INSIDE the repo")
    ap.add_argument("--quiet", action="store_true", help="summary only")
    args = ap.parse_args()

    main_path = ROOT.resolve()
    cwd = Path.cwd().resolve()
    _git("fetch", "origin", "main", "-q")
    rows = classify(main_path, cwd)

    reapable = [r for r in rows if r["reapable"]]
    kept = [r for r in rows if not r["reapable"]]
    in_repo = [r for r in rows if r["in_repo"] and r["path_obj"] != main_path]

    print(f"{len(rows)} worktrees across {len(parents(rows))} parent directories")
    for parent, n in parents(rows).items():
        print(f"  {n:3}  {parent}")

    twins = case_twins(rows)
    if twins:
        print("\n⚠️  CASE-TWIN paths (the same directory on a case-insensitive filesystem):")
        for a, b in twins:
            print(f"     {a}\n     {b}")

    if in_repo:
        print(f"\n⚠️  {len(in_repo)} worktree(s) INSIDE the repo — repo-wide sweeps walk them:")
        for r in in_repo:
            print(f"     {r['path']}")

    if not args.quiet:
        print(f"\nreapable ({len(reapable)}) — clean, and every commit already in origin/main:")
        for r in reapable:
            print(f"  {r['branch'] or '(detached)':55} {r['path']}")
        print(f"\nkept ({len(kept)}):")
        for r in kept:
            print(f"  {r['branch'] or '(detached)':55} {'; '.join(r['reasons']) or 'no reason recorded'}")

    if args.check:
        if in_repo:
            print(f"\n❌ {len(in_repo)} worktree(s) inside the repo.")
            return 1
        print("\n✅ no worktree inside the repo.")
        return 0

    if not args.apply:
        print(f"\nDRY RUN — nothing removed. {len(reapable)} would be. Re-run with --apply.")
        return 0

    removed = 0
    for r in reapable:
        code, out = _git("worktree", "remove", r["path"])
        if code == 0:
            removed += 1
            print(f"  removed {r['path']}")
        else:
            print(f"  FAILED  {r['path']}: {out.strip().splitlines()[-1] if out.strip() else code}")
    _git("worktree", "prune")
    print(f"\nremoved {removed} of {len(reapable)}; {len(kept)} kept untouched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
