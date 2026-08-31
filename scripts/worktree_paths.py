#!/usr/bin/env python3
"""scripts/worktree_paths.py — the ONE definition of where lane worktrees live.

WHY THIS EXISTS (2026-08-30)
  The repo moved (~/Documents/Claude/life-platform → ~/dev/life-platform) and the
  scattered worktrees were consolidated, in one session, from six parent directories
  down to `~/dev/worktrees/life-platform/<branch>`. That consolidation was manual, and
  nothing in the repo knew about it: `lane_worktree.py` still computed
  `repo.parent / "life-platform-worktrees"`, so the very next `lane_worktree.py new`
  would have created a SEVENTH parent and restarted the sprawl the cleanup just ended
  (the same class as the 93-worktrees-across-12-parents incident behind #3289).

  A convention that lives only in a person's head is one an agent re-fragments the next
  morning. So the canonical parent is defined here, once, and both consumers read it:

    * `lane_worktree.py`     — creates every lane UNDER it
    * `worktree_reaper.py`   — reports anything outside it and fails `--check`

  Same shape as `scripts/skill_registry.py` for the skill corpus: one registry, no
  second spelling to forget.

DERIVED, NOT HARD-CODED
  `canonical_parent()` is computed from the checkout's own location
  (`<repo>/../worktrees/<repo-name>`), never from a literal `~/dev`. The last move
  invalidated every hard-coded root in the tree; this one survives the next one.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# The directory, alongside the checkout, that holds every project's worktrees. The
# per-project subdirectory is the checkout's own name, so two clones never collide.
WORKTREE_ROOT_NAME = "worktrees"


def true_case(path: Path | str) -> Path:
    """The path as the filesystem actually spells it.

    macOS is case-insensitive but case-PRESERVING: `os.path.realpath` happily returns the
    case you asked with, so a twin spelling survives every normalization that is not an
    inode comparison. Walk the components and adopt the real directory entry's case, so a
    session invoked through `~/documents/claude/...` still lands in the canonical tree
    rather than creating a second one git and every sweep will treat as distinct.
    """
    p = Path(os.path.realpath(str(path)))
    out = Path(p.anchor)
    for part in p.relative_to(p.anchor).parts:
        try:
            match = next((e for e in os.listdir(out) if e.lower() == part.lower()), None)
        except OSError:
            match = None
        out = out / (match or part)
    return out


def canonical_parent(repo: Path | str) -> Path:
    """The one directory lane worktrees belong in: `<repo>/../worktrees/<repo-name>`.

    A sibling of the checkout, never inside it — an in-repo worktree is a full second
    checkout that every repo-wide sweep walks, and it has red-mained the suite twice
    (#953).
    """
    r = true_case(repo)
    return r.parent / WORKTREE_ROOT_NAME / r.name


def lane_dir(repo: Path | str, branch: str) -> Path:
    """Where the lane for `branch` goes. The leaf is the BRANCH name, not just its issue
    number, so `git worktree list` and the on-disk tree read the same and two lanes on the
    same issue cannot collide."""
    return canonical_parent(repo) / branch


# ── Ephemeral tooling worktrees ───────────────────────────────────────────────
# Some tools legitimately make a worktree in a temp directory and remove it minutes
# later: the merge-train builds one under $TMPDIR, and an agent scratchpad may hold
# one. Those are not parent sprawl — nothing accumulates, because the OS reclaims the
# root. Flagging them trains the reader to ignore the placement warning, which is how a
# gate stops being read at all.
#
# This is an ALLOW-LIST of temp roots, deliberately not a "looks temporary" heuristic:
# a stray worktree in a real directory must keep failing the check. Adding a root here
# is a decision; matching a name pattern would be an accident waiting to happen.
_EPHEMERAL_ROOTS = (
    tempfile.gettempdir(),  # $TMPDIR — /var/folders/... on macOS, /tmp on Linux
    "/tmp",
    "/private/tmp",
    "/var/folders",
    "/private/var/folders",
)


def is_ephemeral(path: Path | str) -> bool:
    """True if `path` sits under a temp root the OS reclaims on its own.

    Compared on realpath, because macOS resolves /tmp → /private/tmp and
    /var/folders → /private/var/folders; a string compare misses half the cases.
    """
    p = os.path.realpath(str(path))
    for root in _EPHEMERAL_ROOTS:
        r = os.path.realpath(root)
        if p == r or p.startswith(r.rstrip(os.sep) + os.sep):
            return True
    return False


def is_canonical(path: Path | str, repo: Path | str) -> bool:
    """True if `path` is a direct child of the canonical parent — inode-compared, so a
    case-twin spelling of the same directory counts as canonical rather than as a stray."""
    parent = canonical_parent(repo)
    try:
        return os.path.samefile(str(Path(path).parent), str(parent))
    except OSError:
        return os.path.realpath(str(Path(path).parent)) == os.path.realpath(str(parent))
