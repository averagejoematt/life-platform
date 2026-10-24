#!/usr/bin/env python3
"""scripts/repo_walk.py — the ONE place a repo scanner learns what is NOT the repo (#5273).

THE CLASS THIS EXISTS FOR
  A checkout on a working machine carries directories that look like the repo and are
  not: an Agent-tool lane worktree at `.claude/worktrees/agent-<id>/` (a full second
  checkout, gitignored), a hand-made `.worktrees/` lane, and untracked build output —
  `cdk/cdk.out/asset.*` and `cdk/_*_staging/` hold byte copies of `lambdas/`. A scanner
  that `os.walk`s or `rglob`s from the repo root, `.claude/` or `cdk/` reads every one of
  those copies. CI checks out clean and never sees them, so the reds are LOCAL-ONLY: Session
  CD (2026-10-23, ten lanes live) lost a tip triage per wave to
  `test_no_verify_set_guard_3642` (16 "unregistered" hits, all under one agent worktree) and
  `test_tdee_worked_set_3931_behavior` (hits in `cdk/cdk.out/asset.*` and
  `cdk/_bundle_staging`). #953 and the `.worktrees/` repeat in
  `tests/test_hevy_compiler_isolation.py` were the same class, fixed one scanner at a time.

WHAT IS EXCLUDED — two rules, both needed
  1. STRUCTURAL: any directory below the scan root that holds its own `.git` entry is
     somebody else's checkout, whatever it is called and wherever it sits (the lesson of
     `test_hevy_compiler_isolation`: a name list is an instance guard, `.worktrees/`
     reproduced #953 past the `.claude/worktrees` skip).
  2. NAMED: the untracked build/lane directories in `EXCLUDED_PREFIXES` /
     `EXCLUDED_GLOBS` / `EXCLUDED_NAMES`. Build output carries no `.git`, so rule 1 cannot see it; and a
     lane directory is skipped by path even before its `.git` file exists.

  Untracked files OUTSIDE those directories are still walked on purpose: a lane's new,
  not-yet-committed file is exactly what a local guard run should catch. That is why this
  is a pruned walk and not `git ls-files` (a tracked-only list would make a guard blind to
  the file being written right now).

USE
    from repo_walk import iter_files, is_excluded
    for path in iter_files(REPO / "scripts", repo=REPO): ...
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Iterable, Iterator

REPO = Path(__file__).resolve().parent.parent

# Repo-relative POSIX directory paths that are never part of the repo population.
EXCLUDED_PREFIXES: tuple[str, ...] = (
    ".claude/worktrees",  # Agent-tool isolation worktrees (#5273)
    ".worktrees",  # hand-made in-repo lanes (#953 repeat)
    "cdk/cdk.out",  # CDK synth output — asset.* dirs are byte copies of lambdas/
)
# Same, as fnmatch patterns over the repo-relative directory path.
EXCLUDED_GLOBS: tuple[str, ...] = ("cdk/_*_staging",)  # deploy bundle staging copies of lambdas/
# Directory NAMES excluded at any depth: CDK writes `cdk.out` wherever `cdk synth` ran.
EXCLUDED_NAMES: frozenset[str] = frozenset({"cdk.out"})


def is_excluded(rel: str | Path) -> bool:
    """True if repo-relative `rel` (file or directory) sits inside an excluded directory."""
    parts = Path(str(rel).replace(os.sep, "/")).as_posix().strip("/").split("/")
    for i in range(1, len(parts) + 1):
        head = "/".join(parts[:i])
        if parts[i - 1] in EXCLUDED_NAMES or head in EXCLUDED_PREFIXES or any(fnmatch.fnmatchcase(head, g) for g in EXCLUDED_GLOBS):
            return True
    return False


def is_nested_checkout(path: Path | str) -> bool:
    """True if directory `path` holds its own `.git` entry (file or dir) — another checkout."""
    return os.path.lexists(os.path.join(path, ".git"))


def skip_dir(path: Path | str, repo: Path | str = REPO) -> bool:
    """True if a scanner must not descend into directory `path`: excluded by name/path, or a
    nested checkout. For hand-rolled walks that cannot use `iter_files` directly."""
    p = Path(path)
    if p.name in EXCLUDED_NAMES or is_nested_checkout(p):
        return True
    try:
        rel = p.relative_to(Path(repo))
    except ValueError:
        return False
    return is_excluded(rel)


def iter_files(root: Path | str, repo: Path | str = REPO, skip_dirs: Iterable[str] = ()) -> Iterator[Path]:
    """Every file under `root`, sorted, minus excluded directories and nested checkouts.

    `skip_dirs` is an extra set of directory NAMES the caller already skipped at any depth
    (`__pycache__`, `node_modules`) — kept so a migrated scanner keeps its own policy.
    `root` itself is walked even if it is a checkout (it usually IS the repo).
    """
    root_p, repo_p = Path(root), Path(repo)
    names = frozenset(skip_dirs) | EXCLUDED_NAMES
    if not root_p.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root_p):
        here = Path(dirpath)
        kept = []
        for d in sorted(dirnames):
            sub = here / d
            if d in names or is_nested_checkout(sub):
                continue
            try:
                rel = sub.relative_to(repo_p)
            except ValueError:
                rel = None
            if rel is not None and is_excluded(rel):
                continue
            kept.append(d)
        dirnames[:] = kept
        for f in sorted(filenames):
            yield here / f


def rglob(root: Path | str, pattern: str = "*", repo: Path | str = REPO, skip_dirs: Iterable[str] = ()) -> Iterator[Path]:
    """`Path.rglob(pattern)` over files only, with the exclusions applied — a drop-in for
    the `root.rglob("*.py")` scanners. `pattern` matches the file NAME."""
    for p in iter_files(root, repo=repo, skip_dirs=skip_dirs):
        if fnmatch.fnmatchcase(p.name, pattern):
            yield p
