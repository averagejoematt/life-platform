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

  PLACEMENT IS ALSO CHECKED (2026-08-30). The parent directories are where the sprawl
  starts, so this reports — and `--check` fails on — any worktree outside the canonical
  parent from `scripts/worktree_paths.py`, the same registry `lane_worktree.py` creates
  into. Placement is reported, never reaped: where a worktree sits says nothing about
  whether its work is finished.

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

WIRED, AND FAST (#4259, measured 2026-09-27)
  The tool existed and nothing called it: 348 worktrees, 97 still locked, because no step
  ever released a lane. Two changes close that loop:
    * `--release-locks-older-than-days N` — a lock carrying `lane_worktree.py`'s own reason
      whose lane has been idle N days is treated as a forgotten release: the row is judged
      on every OTHER check above, and only if it passes is it unlocked and removed (and
      re-locked if the removal fails). A dirty stale lane is printed by name and never
      touched. A bare or hand-set lock is always honoured.
    * `scripts/wrap_gates.py` runs `--apply --quiet --release-locks-older-than-days 7
      --budget-seconds …` as the `worktree-reap` gate, so every wrap reaps what its session
      merged and released.
  The dry run took 140 s over 348 trees (one `git log` + one `gh pr list` per tree, in
  series). Now: probes run in parallel, ancestry is one `git branch --merged`, squash-merge
  detection is first a LOCAL `git merge-tree` content check (merging the branch into
  origin/main would change nothing) and only then ONE batched `gh pr list`, and
  `--budget-seconds` keeps whatever it did not reach.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lane_worktree import LOCK_REASON_PREFIX  # noqa: E402  (the ONE lane-lock reason, set at creation)
from worktree_paths import canonical_parent, is_canonical, is_ephemeral  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# A lane that has touched anything inside this window is treated as live, lock or no lock.
DEFAULT_MIN_IDLE_MINUTES = 120

# mtime sources for "when did something last happen here". `index` is deliberately absent:
# `git status --porcelain` (this tool's own dirtiness probe) rewrites it, so an index-based
# floor would report every worktree as active — a check that cannot fail.
_ADMIN_ACTIVITY_FILES = ("HEAD", "logs/HEAD", "ORIG_HEAD", "gitdir")

# Parallel probes (#4259): each row is a handful of independent git subprocesses, so the
# probe phase is subprocess-latency-bound, not CPU-bound.
PROBE_WORKERS = 8


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


def _merged_by_ancestry() -> set[str]:
    """Every local branch whose tip origin/main already contains — ONE git call (#4259).

    The per-tree `git log origin/main..<branch>` this replaces was one subprocess per
    worktree; at 340 worktrees the dry run took minutes. A failure returns the empty set,
    which only sends every branch down the slower per-branch count — never a false "merged".
    """
    code, out = _git("branch", "--merged", "origin/main", "--format=%(refname:short)")
    if code != 0:
        return set()
    return {ln.strip() for ln in out.splitlines() if ln.strip()}


def _unmerged_commits(branch: str | None, merged: set[str] | None = None) -> int | None:
    """Commits on `branch` that origin/main does not already contain. None if unknowable."""
    if not branch:
        return None
    if merged is not None and branch in merged:
        return 0
    code, out = _git("rev-list", "--count", f"origin/main..{branch}")
    if code != 0:
        return None
    try:
        return int(out.strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


def _main_tree() -> str | None:
    code, out = _git("rev-parse", "origin/main^{tree}")
    line = out.strip().splitlines()[0].strip() if out.strip() else ""
    return line if code == 0 and len(line) >= 40 else None


def _content_merged(branch: str | None, main_tree: str | None) -> bool:
    """True iff merging `branch` into origin/main would change NOTHING — gh-free (#4259).

    A squash merge leaves the branch tip unreachable, so ancestry says "unmerged" for every
    branch that ever shipped. `git merge-tree --write-tree` answers the question that
    actually matters for a deletion — is any of this branch's content absent from main? —
    with no network: if the three-way merge of the branch into origin/main produces
    origin/main's own tree, every change the branch makes is already there. A conflict
    (main has since moved the same lines again), an error, or a different tree is False,
    and the row falls through to GitHub's verdict — so this can only ADD certainty.
    """
    if not branch or not main_tree:
        return False
    code, out = _git("merge-tree", "--write-tree", "origin/main", branch)
    if code != 0:
        return False
    first = out.strip().splitlines()[0].strip() if out.strip() else ""
    return first == main_tree


_PR_CACHE: dict[str, str | None] = {}

# One `gh pr list` returns every PR's head + state; a branch whose PR is older than this
# window simply has no verdict and is KEPT (fail closed), never guessed.
_PR_BATCH_LIMIT = 5000


def _prime_pr_states(branches) -> None:
    """GitHub's verdict for every branch that still needs one, in ONE call (#4259).

    Replaces one `gh pr list --head <b>` per branch (~1 s each, ~250 of them). The
    semantics are _pr_state's exactly: one PR on the head -> its state; zero or several ->
    None. If the batch call fails, every requested branch is cached None — fail closed, and
    no per-branch retry storm against a network that just failed.
    """
    need = sorted({b for b in branches if b and b not in _PR_CACHE})
    if not need:
        return
    data = None
    try:
        res = subprocess.run(
            ["gh", "pr", "list", "--state", "all", "--limit", str(_PR_BATCH_LIMIT), "--json", "headRefName,state"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        data = json.loads(res.stdout) if res.returncode == 0 else None
    except Exception:
        data = None
    by_head: dict[str, list[str]] = {}
    if isinstance(data, list):
        for pr in data:
            if isinstance(pr, dict) and pr.get("headRefName"):
                by_head.setdefault(pr["headRefName"], []).append(str(pr.get("state") or ""))
    for b in need:
        states = by_head.get(b, [])
        _PR_CACHE[b] = states[0] if len(states) == 1 and states[0] else None


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


def _stale_lane_lock(wt: dict, last_activity: float | None, now: float, stale_lock_seconds: float | None) -> bool:
    """A lock `lane_worktree.py new` set, on a lane idle past the stale-lock floor (#4259).

    Only a lock carrying lane_worktree's own reason prefix is ever eligible: a bare lock, or
    one a human set with any other reason, is a deliberate "keep" this tool does not second-
    guess. Eligibility is not reaping — the row still has to pass every check an unlocked
    row passes (clean, merged, not the main/current tree).
    """
    if stale_lock_seconds is None or not wt.get("locked") or last_activity is None:
        return False
    if not str(wt.get("lock_reason") or "").startswith(LOCK_REASON_PREFIX):
        return False
    return now - last_activity >= stale_lock_seconds


def probe(
    wt: dict,
    main_path: Path,
    cwd: Path,
    git_main: Path | None = None,
    *,
    now: float | None = None,
    merged: set[str] | None = None,
    main_tree: str | None = None,
    stale_lock_seconds: float | None = None,
    deadline: float | None = None,
) -> dict:
    """Gather every fact about one worktree row. No decision is taken here.

    The main working tree and rows whose directory is gone are never probed further: there
    is nothing to measure and the probes (`git status`) would be run in the shared checkout.
    A live-locked row stops after its activity time — nothing will be done to it, so its
    status is not worth a subprocess. A row reached after `deadline` is marked `unprobed`
    and kept.
    """
    now = time.time() if now is None else now
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
        off_canonical=False,
        last_activity=None,
        dirty=None,
        unmerged=None,
        content_merged=False,
        pr_state=None,
        stale_lock=False,
        release_lock=False,
        unprobed=False,
    )
    if row["is_main"]:
        return row
    # Placement, not liveness: a lane outside the canonical parent is reported, never
    # reaped for it. Where a worktree sits says nothing about whether its work is done.
    # Temp-root worktrees (merge-train, scratchpads) are exempt — they are reclaimed by
    # the OS, so they are not sprawl. The exemption is by explicit root, never by a
    # "looks temporary" name test: a stray in a real directory still fails.
    row["ephemeral"] = is_ephemeral(p)
    row["off_canonical"] = not row["ephemeral"] and not is_canonical(p, main_path)
    row["is_cwd"] = _is_within(cwd, p)
    row["in_repo"] = _is_within(p, main_path)
    if not row["exists"]:
        return row
    if deadline is not None and time.monotonic() > deadline:
        row["unprobed"] = True
        return row
    # Activity BEFORE dirtiness: `git status` rewrites the admin index.
    row["last_activity"] = _last_activity(p)
    row["stale_lock"] = _stale_lane_lock(wt, row["last_activity"], now, stale_lock_seconds)
    if wt.get("locked") and not row["stale_lock"]:
        return row
    row["dirty"] = _is_dirty(p)
    if not row["dirty"] and not wt["detached"]:
        row["unmerged"] = _unmerged_commits(wt["branch"], merged)
        if row["unmerged"]:
            row["content_merged"] = _content_merged(wt["branch"], main_tree)
    return row


def decide(row: dict, now: float, min_idle_seconds: float, stale_lock_seconds: float | None = None) -> dict:
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
    if row.get("unprobed"):
        reasons.append("not probed — the run's time budget was spent first — KEEP")
        return row
    if row["locked"]:
        why = f" ({row['lock_reason']})" if row["lock_reason"] else ""
        if not row.get("stale_lock"):
            reasons.append(f"LOCKED{why} — in use; release with `git worktree unlock {row['path']}` — KEEP")
            return row
        days = (now - row["last_activity"]) / 86400 if row["last_activity"] else 0
        floor = f" ≥ the {stale_lock_seconds / 86400:g} d stale-lock floor" if stale_lock_seconds else ""
        reasons.append(f"LOCKED{why} but idle {days:.0f} d{floor} — a forgotten release; judged on the checks below")
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
        # reapable, which is a tool that cannot be used. Two authorities settle that case:
        # merge-tree content containment (local, #4259), then GitHub's own merge verdict.
        state = row["pr_state"]
        if row.get("content_merged"):
            row["reapable"] = True
            reasons.append(f"content already in origin/main (merging it would change nothing); {n} unreachable commit(s) is expected")
        elif state == "MERGED":
            row["reapable"] = True
            reasons.append(f"squash-merged (PR MERGED); {n} unreachable commit(s) is expected")
        elif state is None:
            reasons.append(f"{n} commit(s) not in origin/main, and no merge verdict available — KEEP")
        else:
            reasons.append(f"{n} commit(s) not in origin/main, PR is {state} — KEEP")
    else:
        row["reapable"] = True
        reasons.append("every commit already in origin/main")
    if row["reapable"] and row["locked"]:
        row["release_lock"] = True
        reasons.append("unlock + remove")
    return row


def classify(
    main_path: Path,
    cwd: Path,
    now: float | None = None,
    min_idle_seconds: float | None = None,
    stale_lock_seconds: float | None = None,
    budget_seconds: float | None = None,
    workers: int = PROBE_WORKERS,
) -> list[dict]:
    """Probe every worktree and decide its fate. `main_path` is a hint — the main working
    tree is also derived from git itself, so a case-twin spelling cannot smuggle it in.

    #4259: the per-row probes run in parallel, the ancestry and PR-verdict lookups are
    batched (one git call, one gh call), and an optional `budget_seconds` bounds the probe
    phase — any row not reached in time is kept with that reason.
    """
    now = time.time() if now is None else now
    min_idle_seconds = DEFAULT_MIN_IDLE_MINUTES * 60 if min_idle_seconds is None else min_idle_seconds
    deadline = None if budget_seconds is None else time.monotonic() + budget_seconds
    git_main = main_worktree_path()
    merged = _merged_by_ancestry()
    main_tree = _main_tree()

    def one(wt: dict) -> dict:
        return probe(
            wt,
            main_path,
            cwd,
            git_main,
            now=now,
            merged=merged,
            main_tree=main_tree,
            stale_lock_seconds=stale_lock_seconds,
            deadline=deadline,
        )

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        probed = list(pool.map(one, worktrees()))

    need = [x for x in probed if x.get("unmerged") and not x.get("content_merged")]
    if need and (deadline is None or time.monotonic() < deadline):
        _prime_pr_states([x["branch"] for x in need])
        for x in need:
            x["pr_state"] = _pr_state(x["branch"])
    return [decide(x, now=now, min_idle_seconds=min_idle_seconds, stale_lock_seconds=stale_lock_seconds) for x in probed]


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


def main(argv: list[str] | None = None) -> int:
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
    ap.add_argument(
        "--release-locks-older-than-days",
        type=float,
        default=None,
        help="also unlock + reap a lane whose `lane_worktree.py` lock is older (idle) than this many days — "
        "only if it passes every other check (clean, merged). Default: never (a lock is always honoured).",
    )
    ap.add_argument(
        "--budget-seconds",
        type=float,
        default=None,
        help="wall-clock budget for the whole run; rows not probed and removals not reached in time are kept",
    )
    args = ap.parse_args(argv)
    started = time.monotonic()
    deadline = None if args.budget_seconds is None else started + args.budget_seconds
    stale_lock_seconds = None if args.release_locks_older_than_days is None else args.release_locks_older_than_days * 86400

    # Git's answer, not this file's location: invoked from inside a linked worktree, ROOT is
    # that worktree rather than the main tree.
    main_path = main_worktree_path() or ROOT.resolve()
    cwd = Path.cwd().resolve()
    _git("fetch", "origin", "main", "-q")
    rows = classify(
        main_path,
        cwd,
        min_idle_seconds=args.min_idle_minutes * 60,
        stale_lock_seconds=stale_lock_seconds,
        budget_seconds=None if deadline is None else max(0.0, deadline - time.monotonic()),
    )

    # The candidate set. A main-tree row can never reach it, and a locked row only when
    # `decide` judged it a stale lane lock that passed every other check — belt and braces
    # on top of `decide`, because this is the list `--apply` deletes.
    reapable = [r for r in rows if r["reapable"] and not r["is_main"] and (not r["locked"] or r.get("release_lock"))]
    reaped_ids = {id(r) for r in reapable}
    kept = [r for r in rows if id(r) not in reaped_ids]
    in_repo = [r for r in rows if r["in_repo"]]
    off_canonical = [r for r in rows if r.get("off_canonical")]
    ephemeral = [r for r in rows if r.get("ephemeral")]

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

    if off_canonical:
        print(f"\n⚠️  {len(off_canonical)} worktree(s) OUTSIDE the canonical parent {canonical_parent(main_path)}:")
        for r in off_canonical:
            print(f"     {r['path']}")
        print("     Parent sprawl is how 93 worktrees ended up across 12 directories (#3289).")
        print("     Create lanes with: python3 scripts/lane_worktree.py new <issue-N> <slug>")

    if ephemeral:
        print(f"\n   {len(ephemeral)} ephemeral worktree(s) under a temp root — exempt from the placement check:")
        for r in ephemeral:
            print(f"     {r['path']}")

    locked = [r for r in rows if r["locked"]]
    stale_note = (
        f"; lane locks idle ≥ {args.release_locks_older_than_days:g} d are released when clean + merged"
        if args.release_locks_older_than_days is not None
        else " (never candidates)"
    )
    print(f"\nliveness: {len(locked)} locked{stale_note}; idle floor {args.min_idle_minutes} min")

    # #4259: every dirty tree by NAME, in every mode (including --quiet, which is how the
    # wrap gate runs). A dirty tree is never touched; this list is the human's to act on.
    dirty = [r for r in rows if r.get("dirty") and not r["is_main"]]
    if dirty:
        print(f"\n{len(dirty)} dirty worktree(s) — uncommitted work, reported by name and NEVER touched:")
        for r in dirty:
            tag = " [LOCKED]" if r["locked"] else ""
            print(f"  {r['branch'] or '(detached)':55} {r['path']}{tag}")
    unprobed = [r for r in rows if r.get("unprobed")]
    if unprobed:
        print(f"\n{len(unprobed)} worktree(s) not probed inside the {args.budget_seconds:g}s budget — kept; the next run reaches them")

    if not args.quiet:
        print(f"\nreapable ({len(reapable)}) — unlocked (or a stale lane lock), idle, clean, and every change already in origin/main:")
        for r in reapable:
            print(f"  {r['branch'] or '(detached)':55} {r['path']}")
        print(f"\nkept ({len(kept)}):")
        for r in kept:
            print(f"  {r['branch'] or '(detached)':55} {'; '.join(r['reasons']) or 'no reason recorded'}")

    if args.check:
        if in_repo:
            print(f"\n❌ {len(in_repo)} worktree(s) inside the repo.")
            return 1
        if off_canonical:
            print(f"\n❌ {len(off_canonical)} worktree(s) outside the canonical parent.")
            return 1
        print("\n✅ no worktree inside the repo; every lane in the canonical parent.")
        return 0

    def summary(removed: int, released: int, deferred: int) -> str:
        return (
            f"REAPER-SUMMARY worktrees={len(rows)} reapable={len(reapable)} removed={removed} released={released} "
            f"deferred={deferred} dirty={len(dirty)} unprobed={len(unprobed)} elapsed={time.monotonic() - started:.1f}s"
        )

    if not args.apply:
        print(f"\nDRY RUN — nothing removed. {len(reapable)} would be. Re-run with --apply.")
        print(summary(0, 0, 0))
        return 0

    removed = released = deferred = 0
    for r in reapable:
        if deadline is not None and time.monotonic() > deadline:
            deferred += 1
            continue
        if r.get("release_lock"):
            code, out = _git("worktree", "unlock", r["path"])
            if code != 0:
                print(f"  FAILED  unlock {r['path']}: {out.strip().splitlines()[-1] if out.strip() else code}")
                continue
            released += 1
        code, out = _git("worktree", "remove", r["path"])
        if code == 0:
            removed += 1
            print(f"  removed {r['path']}")
        else:
            print(f"  FAILED  {r['path']}: {out.strip().splitlines()[-1] if out.strip() else code}")
            if r.get("release_lock"):
                # Leave it exactly as found: a lane we could not remove keeps its lock.
                _git("worktree", "lock", r["path"], "--reason", r["lock_reason"] or LOCK_REASON_PREFIX)
    _git("worktree", "prune")
    if deferred:
        print(f"\n{deferred} removal(s) deferred — the {args.budget_seconds:g}s budget ran out; the next run reaches them")
    print(f"\nremoved {removed} of {len(reapable)}; {len(kept)} kept untouched.")
    print(summary(removed, released, deferred))
    return 0


if __name__ == "__main__":
    sys.exit(main())
