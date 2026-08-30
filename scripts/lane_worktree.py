#!/usr/bin/env python3
"""scripts/lane_worktree.py — create (and release) a lane worktree with its liveness signal.

WHY THIS EXISTS (#3289)
  `scripts/worktree_reaper.py` protects live lanes by refusing to reap a worktree that is
  `git worktree lock`ed. That protection is only worth anything if the lock is ALWAYS there,
  and a lock that each agent has to remember is a lock that is sometimes missing — the lane
  it is missing on is the one that gets deleted mid-task.

  So creation and locking are one command. There is no supported path that makes a lane
  worktree without the lock, and the two other rules the repo has paid for are enforced here
  rather than restated in prose:

    * OUTSIDE the repo. An in-repo worktree is a full second checkout that every repo-wide
      sweep walks — it has red-mained the suite twice (#953) and makes local runs disagree
      with CI in both directions. This refuses to create one.
    * ONE canonical parent, defined ONCE. The parent comes from `scripts/worktree_paths.py`
      (`<repo>/../worktrees/<repo-name>`), the same registry `worktree_reaper.py` asserts
      against — so a lane cannot land in a seventh parent directory and restart the sprawl
      that #3289 and the 2026-08-30 consolidation each had to clean up by hand.
    * ONE canonical spelling. On macOS `~/Documents/Claude` and `~/documents/claude` are the
      same directory, and edits through one leak into the tree the other names. The parent is
      resolved to its true on-disk case before anything is created, so a session invoked
      through the twin spelling still lands in the canonical tree.

USAGE
    python3 scripts/lane_worktree.py new 3289 reaper-liveness      # create + lock
    python3 scripts/lane_worktree.py release <path>                # unlock when the lane is done

  Release is the deliberate act that says "this lane is finished" — until it happens the
  reaper keeps the worktree, by design. The reaper prints the exact release command on every
  kept-because-locked row.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from worktree_paths import canonical_parent, true_case as _true_case  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

LOCK_REASON_PREFIX = "lane in use"


def _git(args: list[str], cwd: Path) -> tuple[int, str]:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=120)
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def lane_parent(repo: Path) -> Path:
    """The canonical parent, read from the ONE registry (`scripts/worktree_paths.py`).

    Kept as a module-level name because `new_lane` looks it up as a global — that is the
    seam the in-repo-refusal test monkeypatches to prove the guard fires.
    """
    return canonical_parent(repo)


def new_lane(issue: int | str, slug: str, repo: Path = ROOT, base: str = "origin/main") -> Path:
    """Create the lane worktree off up-to-date `base` and LOCK it. Returns its path."""
    repo = _true_case(repo)
    branch = f"issue-{issue}-{slug}"
    path = lane_parent(repo) / branch

    # Fails closed on the one placement that has red-mained main twice.
    if _is_within(path, repo):
        raise SystemExit(f"refusing to create a worktree INSIDE the repo: {path}")
    if path.exists():
        raise SystemExit(f"{path} already exists — release and remove it, or pick another lane")

    path.parent.mkdir(parents=True, exist_ok=True)
    code, out = _git(["fetch", "origin", "--quiet"], cwd=repo)
    if code != 0:
        raise SystemExit(f"git fetch origin failed: {out}")
    code, out = _git(["worktree", "add", "-b", branch, str(path), base], cwd=repo)
    if code != 0:
        raise SystemExit(f"git worktree add failed: {out}")

    # The liveness signal, set at creation — before the lane has made a single edit, which
    # is exactly the window in which a clean tree is indistinguishable from a finished one.
    code, out = _git(["worktree", "lock", str(path), "--reason", f"{LOCK_REASON_PREFIX}: {branch}"], cwd=repo)
    if code != 0:
        # An unlocked lane is reapable-while-live. Do not leave one behind.
        _git(["worktree", "remove", "--force", str(path)], cwd=repo)
        raise SystemExit(f"git worktree lock failed, lane removed rather than left unprotected: {out}")
    return path


def release_lane(path: Path, repo: Path = ROOT) -> None:
    """Unlock a lane — the deliberate 'this is finished' act that makes it reapable."""
    code, out = _git(["worktree", "unlock", str(path)], cwd=_true_case(repo))
    if code != 0:
        raise SystemExit(f"git worktree unlock failed: {out}")


def _is_within(child: Path, parent: Path) -> bool:
    c = Path(os.path.realpath(str(child)))
    p = Path(os.path.realpath(str(parent)))
    return str(c).lower() == str(p).lower() or str(c).lower().startswith(str(p).lower().rstrip(os.sep) + os.sep)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Create a lane worktree with its liveness lock, or release one.")
    sub = ap.add_subparsers(dest="mode", required=True)
    n = sub.add_parser("new", help="create + lock a lane worktree")
    n.add_argument("issue", help="issue number, e.g. 3289")
    n.add_argument("slug", help="short kebab slug, e.g. reaper-liveness")
    n.add_argument("--base", default="origin/main")
    rel = sub.add_parser("release", help="unlock a finished lane so the reaper may retire it")
    rel.add_argument("path")
    args = ap.parse_args(argv)

    if args.mode == "new":
        path = new_lane(args.issue, args.slug, base=args.base)
        print(f"created + LOCKED {path}")
        print(f"branch issue-{args.issue}-{args.slug} off {args.base}")
        print(f"release when done:  python3 scripts/lane_worktree.py release {path}")
        return 0
    release_lane(Path(args.path))
    print(f"released {args.path} — the reaper may now retire it once it is clean, merged and idle")
    return 0


if __name__ == "__main__":
    sys.exit(main())
