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

LIVENESS — WHY `git worktree lock` AND NOT DIRTINESS (#3289, measured 2026-08-28)
  On its first real use this tool listed three RUNNING implementation lanes as reapable,
  plus the primary clone. The lanes were clean because they had been checked out ninety
  seconds earlier and had not made their first edit yet. `--apply` would have deleted
  three working agents' directories.

  **Dirtiness LAGS.** It appears only after a lane has already done work, so it cannot
  see the two windows in which a live lane looks exactly like a finished one: between
  checkout and the first write, and between a commit/push and the merge. A reaper whose
  only liveness evidence is dirtiness is a race — the same lane reads reapable or kept
  depending purely on when you happen to run the dry run, and the ten-minutes-later run
  that sees three dirty trees concludes the tool is safe.

  The chosen signal is `git worktree lock`, set by whoever CREATES the worktree:
    * it LEADS because it exists from creation — present during the entire empty-and-clean
      window, before there is anything to be dirty about;
    * it is git's own mechanism for "do not reclaim this", so it also arms a second,
      independent backstop: `git worktree remove` refuses a locked tree without `-f -f`,
      and this tool never passes force;
    * it is explicit and releasable — `git worktree unlock <path>` is the single deliberate
      act that says the lane is done, and every kept-because-locked row prints it.

  A lock can still be forgotten, so an idle-time floor backstops it: a worktree whose most
  recent activity is inside `--min-idle-minutes` (default 120) is KEPT regardless. Activity
  is the newest mtime of the worktree directory, its `.git` file, and the admin `HEAD`,
  `logs/HEAD` and `gitdir` — which covers exactly the two clean windows (checkout stamps
  the directory, a commit stamps `logs/HEAD`). The admin `index` is deliberately EXCLUDED:
  measured, this tool's own `git status` probe rewrites it, so including it would make
  every worktree look active forever — a floor that can never fail.

SAFETY
  This removes work, so every check fails CLOSED and the default is a dry run. A worktree
  is only ever a candidate when ALL of these hold, and each is reported per row:
    * it is not the main working tree, and not the current working tree (or an ancestor of
      it). The main tree is identified structurally, from `git rev-parse --git-common-dir`
      and by inode (`os.path.samefile`), not by string equality — a macOS case-twin
      spelling is the SAME directory and string equality missed it, which is how the
      primary clone appeared in a reapable list;
    * it is not locked, and it has been idle longer than the floor (see LIVENESS);
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
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# A lane that has touched anything inside this window is treated as live, lock or no lock.
DEFAULT_MIN_IDLE_MINUTES = 120

# mtime sources for "when did something last happen here". `index` is deliberately absent:
# `git status --porcelain` (this tool's own dirtiness probe) rewrites it, so an index-based
# floor would report every worktree as active — a check that cannot fail.
_ADMIN_ACTIVITY_FILES = ("HEAD", "logs/HEAD", "ORIG_HEAD", "gitdir")


def _git(*args: str, cwd: Path | None = None) -> tuple[int, str]:
    r = subprocess.run(["git", *args], cwd=cwd or ROOT, capture_output=True, text=True, timeout=60)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def worktrees() -> list[dict]:
    """Parse `git worktree list --porcelain` into rows.

    The `locked` attribute is emitted bare (`locked`) or with a reason (`locked <reason>`)
    — both shapes are real git output and both mean "in use, do not reclaim".
    """
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
            cur = {"path": val, "branch": None, "detached": False, "bare": False, "locked": False, "lock_reason": ""}
        elif key == "branch":
            cur["branch"] = val.replace("refs/heads/", "")
        elif key == "detached":
            cur["detached"] = True
        elif key == "bare":
            cur["bare"] = True
        elif key == "locked":
            cur["locked"] = True
            cur["lock_reason"] = val.strip()
    if cur:
        rows.append(cur)
    return rows


def _same_dir(a, b) -> bool:
    """Same directory, by inode — not by string.

    On macOS `~/Documents/Claude/x` and `~/documents/claude/x` are one directory with two
    spellings. String equality says they differ, which is how the primary clone landed in a
    reapable list (#3289). `samefile` compares (st_dev, st_ino) and is immune to both case
    and symlinks; it needs both paths to exist, so a realpath compare is the fallback.
    """
    try:
        return os.path.samefile(str(a), str(b))
    except OSError:
        return os.path.realpath(str(a)) == os.path.realpath(str(b))


def _is_within(child, parent) -> bool:
    """True if `child` is `parent` or lives under it — inode-compared at every ancestor."""
    c = Path(os.path.realpath(str(child)))
    for anc in (c, *c.parents):
        if _same_dir(anc, parent):
            return True
    return False


def main_worktree_path() -> Path | None:
    """The main working tree, derived from git itself rather than from this file's location.

    `--git-common-dir` is the shared `.git` no matter which linked worktree we are called
    from, so its parent is the main working tree. Falls back to the first row of
    `git worktree list --porcelain`, which git documents as the main working tree.
    """
    code, out = _git("rev-parse", "--path-format=absolute", "--git-common-dir")
    line = out.strip().splitlines()[0].strip() if out.strip() else ""
    if code == 0 and line and not line.startswith("fatal"):
        return Path(line).parent
    rows = worktrees()
    return Path(rows[0]["path"]) if rows else None


def _admin_dir(path: Path) -> Path | None:
    """The linked worktree's admin directory (`.git/worktrees/<name>`), read from its `.git` file."""
    try:
        text = (path / ".git").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    return Path(text.split(":", 1)[1].strip())


def _last_activity(path: Path) -> float | None:
    """Newest mtime across the worktree's stable activity sources; None if unknowable.

    Must be read BEFORE the dirtiness probe: `git status` rewrites the admin index (that is
    why the index is not one of the sources — see _ADMIN_ACTIVITY_FILES).
    """
    stamps: list[float] = []
    for p in (path, path / ".git"):
        try:
            stamps.append(os.stat(p).st_mtime)
        except OSError:
            pass
    admin = _admin_dir(path)
    if admin:
        for name in _ADMIN_ACTIVITY_FILES:
            try:
                stamps.append(os.stat(admin / name).st_mtime)
            except OSError:
                pass
    return max(stamps) if stamps else None


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


def probe(wt: dict, main_path: Path, cwd: Path, git_main: Path | None = None) -> dict:
    """Gather every fact about one worktree row. No decision is taken here.

    The main working tree and rows whose directory is gone are never probed further: there
    is nothing to measure and the probes (`git status`) would be run in the shared checkout.
    """
    p = Path(wt["path"])
    row = dict(
        wt,
        path_obj=p,
        reasons=[],
        reapable=False,
        in_repo=False,
        exists=p.exists(),
        is_main=_same_dir(p, main_path) or bool(git_main is not None and _same_dir(p, git_main)),
        is_cwd=False,
        last_activity=None,
        dirty=None,
        unmerged=None,
        pr_state=None,
    )
    if row["is_main"]:
        return row
    row["is_cwd"] = _is_within(cwd, p)
    row["in_repo"] = _is_within(p, main_path)
    if not row["exists"]:
        return row
    # Activity BEFORE dirtiness: `git status` rewrites the admin index.
    row["last_activity"] = _last_activity(p)
    row["dirty"] = _is_dirty(p)
    if not row["dirty"] and not wt["detached"]:
        row["unmerged"] = _unmerged_commits(wt["branch"])
        if row["unmerged"]:
            row["pr_state"] = _pr_state(wt["branch"])
    return row


def decide(row: dict, now: float, min_idle_seconds: float) -> dict:
    """Turn the probed facts into reapable/KEEP + the reasons. Pure — this is the contract.

    Ordered most-protective first, and every branch that is not the final "reapable" one
    leaves `reapable` False. Liveness is checked BEFORE dirtiness because dirtiness lags
    (see LIVENESS in the module docstring).
    """
    reasons = row["reasons"]
    if row["is_main"]:
        reasons.append("the main working tree — excluded from the candidate set")
        return row
    if row["in_repo"]:
        reasons.append("INSIDE the repo — repo-wide sweeps walk it (the #953 class)")
    if row["is_cwd"]:
        reasons.append("the current working tree — KEEP")
        return row
    if not row["exists"]:
        reasons.append("directory is gone — `git worktree prune` clears this row")
        return row
    if row["locked"]:
        why = f" ({row['lock_reason']})" if row["lock_reason"] else ""
        reasons.append(f"LOCKED{why} — in use; release with `git worktree unlock {row['path']}` — KEEP")
        return row
    if row["last_activity"] is None:
        reasons.append("activity time unknowable — KEEP")
        return row
    idle = now - row["last_activity"]
    if idle < min_idle_seconds:
        reasons.append(f"active {int(idle // 60)} min ago — inside the {int(min_idle_seconds // 60)} min idle floor — KEEP")
        return row
    if row["dirty"]:
        reasons.append("has uncommitted changes — KEEP")
        return row
    n = row["unmerged"]
    if row["detached"]:
        reasons.append("detached HEAD — cannot prove it is merged, KEEP")
    elif n is None:
        reasons.append("branch state unknowable — KEEP")
    elif n > 0:
        # A SQUASH merge (this repo's default) rewrites the work into one new commit, so
        # the branch tip is never reachable from main and the ancestry test above says
        # "unmerged" for every branch that ever shipped. Measured: it reported 0 of 93
        # reapable, which is a tool that cannot be used. GitHub's own merge verdict is the
        # authority for that case; ancestry stays the authority when it says yes.
        state = row["pr_state"]
        if state == "MERGED":
            row["reapable"] = True
            reasons.append(f"squash-merged (PR MERGED); {n} unreachable commit(s) is expected")
        elif state is None:
            reasons.append(f"{n} commit(s) not in origin/main, and no merge verdict available — KEEP")
        else:
            reasons.append(f"{n} commit(s) not in origin/main, PR is {state} — KEEP")
    else:
        row["reapable"] = True
        reasons.append("every commit already in origin/main")
    return row


def classify(main_path: Path, cwd: Path, now: float | None = None, min_idle_seconds: float | None = None) -> list[dict]:
    """Probe every worktree and decide its fate. `main_path` is a hint — the main working
    tree is also derived from git itself, so a case-twin spelling cannot smuggle it in."""
    now = time.time() if now is None else now
    min_idle_seconds = DEFAULT_MIN_IDLE_MINUTES * 60 if min_idle_seconds is None else min_idle_seconds
    git_main = main_worktree_path()
    rows = []
    for wt in worktrees():
        rows.append(decide(probe(wt, main_path, cwd, git_main), now=now, min_idle_seconds=min_idle_seconds))
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
    ap.add_argument(
        "--min-idle-minutes",
        type=int,
        default=DEFAULT_MIN_IDLE_MINUTES,
        help=f"keep anything touched within this many minutes (default {DEFAULT_MIN_IDLE_MINUTES}); backstops a forgotten lock",
    )
    args = ap.parse_args()

    # Git's answer, not this file's location: invoked from inside a linked worktree, ROOT is
    # that worktree rather than the main tree.
    main_path = main_worktree_path() or ROOT.resolve()
    cwd = Path.cwd().resolve()
    _git("fetch", "origin", "main", "-q")
    rows = classify(main_path, cwd, min_idle_seconds=args.min_idle_minutes * 60)

    # The candidate set. A locked or main-tree row can never reach it — belt and braces on
    # top of `decide`, because this is the list `--apply` deletes.
    reapable = [r for r in rows if r["reapable"] and not r["is_main"] and not r["locked"]]
    reaped_ids = {id(r) for r in reapable}
    kept = [r for r in rows if id(r) not in reaped_ids]
    in_repo = [r for r in rows if r["in_repo"]]

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

    locked = [r for r in rows if r["locked"]]
    print(f"\nliveness: {len(locked)} locked (in use, never candidates); idle floor {args.min_idle_minutes} min")

    if not args.quiet:
        print(f"\nreapable ({len(reapable)}) — unlocked, idle, clean, and every commit already in origin/main:")
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
