"""tests/repo_scan_cache.py — ONE whole-repo scan per suite process, not N (#3224).

THE CLASS THIS EXISTS FOR
-------------------------
Several tests assert "the whole gate still exits 0 on the real tree" by shelling out
to a repo-scanning script. Each of those `subprocess.run(...)` calls pays the FULL
cost every time: interpreter start, module import, a walk of every tracked doc and
source file, and — since #3126/#3156 put `gate_census.build_census()` on
`sync_doc_metadata`'s auto-discovery path — a complete gate census on top.

Measured 2026-08-27 on this repo (the #3224 attribution):

  * `python3 scripts/check_doc_facts.py` costs **15.4s** at 10315b618, of which
    **8.1s** is the census (`cProfile`: `sync_census_fact.discover_gate_census_count`
    → `gate_census.build_census`, 1,189,573 `re.Pattern.search` calls).
  * The SAME command costs **7.3s** at 9331995b — the sha whose CI run filed #3106
    at 1507s. The script did not get 2.1x more careful; it acquired one more
    whole-repo scan, and every caller pays it.
  * THREE tests ran that byte-identical command against the unmutated tree:
    `test_doc_facts_ops_1957.py::test_gate_passes_on_the_repo`,
    `test_doc_facts_ops_2003.py::test_gate_passes_on_the_repo`, and
    `test_wiki_checkers.py::test_doc_facts_clean` — 27.95s / 27.54s / 27.14s on the
    coverage-instrumented CI lane (run 33030125667, the 1994s run in #3224's title).

That is the growth engine the four prior budget raises (#1349, #1966, #2152, #3106)
each answered with a bigger number: **cost = (number of tests that shell out) x (cost
of one whole-repo scan)**, and BOTH factors grow with the repo. Adding one check to a
shared scanner multiplies into CI by the size of its caller set, which is why the
trend line between instances kept outrunning the raises.

WHAT THIS MODULE DOES
---------------------
Memoizes, for the lifetime of ONE pytest process, the result of running a repo-scan
script against the **unmutated** tree. Same argv + same cwd + same env overrides ==
same answer, so the second and third callers read the first caller's result.

WHEN YOU MAY NOT USE IT (read this before adding a call site)
------------------------------------------------------------
The cache key is (argv, cwd, env-overrides, tree-state — see #3731 below). It does
NOT include anything else about the world. So:

  * **Never** use it for a scan of a tree the test mutates in a way this module
    cannot see — a tmp-dir copy with a planted defect, a monkeypatched file, a
    `--apply` run against a COPY of the tree. Those are exactly the mutation proofs
    this repo relies on, and a cached answer would make them pass without running.
    Call `subprocess.run` directly there; it is one scan, not N. (A mutation made
    directly to the REAL checkout, in-place, IS covered — see #3731 below — but
    that is not how this repo's mutation proofs are written, and should not become
    how they are written just because it would now be safe.)
  * **Never** use it for a scan whose result depends on something outside
    argv/cwd/env/tree-state (wall-clock, network, a global the test sets).
  * A run with a distinct env (e.g. `check_doc_facts.py` under
    `CHECK_DOC_FACTS_TODAY=2036-01-01`) is a DIFFERENT key and is cached separately —
    correct, and it means such a run shares nothing with the plain one.

`tests/test_repo_scan_cache_3224.py` pins all of that, including a non-vacuity proof
that the cache really does collapse N spawns into one (a cache that silently missed
would be invisible: every test would still pass, just as slowly as before).

CROSS-PROCESS SHARING (#3731)
------------------------------
The per-process `functools`-style table above only ever collapses spawns WITHIN one
pytest worker. Since #3797/#3835 put the post-merge suite's parallel pass on
`pytest -n auto --dist loadfile`, a test FILE — not the whole session — is the unit
xdist hands to a worker, so `test_doc_facts_ops_1957.py`, `test_doc_facts_ops_2003.py`
and `test_wiki_checkers.py` (three call sites of the SAME byte-identical
`check_doc_facts.py` scan) routinely land on three DIFFERENT worker processes. Each
worker's table is its own empty one, so #3224's fix — real under the OLD serial job
— was silently re-fragmented back into (up to) four spawns by the job that
parallelised everything else. Measured 2026-09-19, one file per isolated process
(the worst case a `--dist loadfile` worker sees): `test_doc_facts_ops_1957.py` 50.2s,
`test_doc_facts_ops_2003.py` 49.6s, `test_wiki_checkers.py`'s two callers 49.8s/49.9s
— four full re-spawns of one ~15s-class scan, ~200s that a shared answer collapses
into one.

The fix adds a SECOND layer, not a second mechanism: `run_repo_scan` now checks a
tiny on-disk JSON file (under `.pytest_cache/repo_scan_cache/`, already
`.gitignore`d, and naturally per-worktree since a linked worktree's cache dir lives
under ITS OWN checkout directory) before spawning, and writes one after a real
spawn. Any worker — same run, or a later local run — that asks for the identical
(argv, cwd, env, TREE STATE) reads that file instead of paying the scan again.

**Tree state is part of the key, or this is a staleness bug, not a cache.** A plain
(argv, cwd, env) key would happily hand a scan against yesterday's tree to a test
that edited a doc five minutes ago — the exact "cached answer masks a mutation"
failure mode the section above already warns the table about, now durable across
process boundaries where it would otherwise survive indefinitely. `_tree_fingerprint()`
hashes the (relpath, size, mtime) of every file under the repo (skipping build/venv/
cache directories, including its OWN `.pytest_cache/repo_scan_cache/` write target)
— deliberately NOT `git rev-parse HEAD` + `git status --porcelain`: that pair shares
`subprocess.run` with the scan spawn itself, and this module's own tests fake that
symbol to count spawns exactly, so a git-based fingerprint would corrupt every one
of those counts; a porcelain STRING also has a gap a stat()-based walk does not —
editing a file that was ALREADY dirty leaves porcelain's one-line-per-path output
unchanged. Any edit anywhere in the tree, tracked or not, moves some file's mtime
and therefore invalidates every disk entry from before it; the next reader
recomputes and re-writes, once, and everyone downstream of that edit sees the fresh
answer.

`tests/test_repo_scan_cache_3224.py` pins the invalidation, the non-collision
between the pure in-memory table (`new_cache(disk_dir=None)`, what the low-level
hit/miss tests use for isolation) and the disk-backed shared table, and — the
must-fail control — that breaking the tree-state term back to a constant serves a
stale disk answer after a real edit.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Where the disk-backed layer lives. `.pytest_cache/` is already `.gitignore`d
# (line 57 of the repo's `.gitignore`) and is a plain directory under THIS
# checkout's cwd — for a linked worktree that resolves inside the worktree, never
# the shared `.git` object store, so two lanes on two worktrees never read or write
# each other's cache (`git help worktree` — only `refs/*` and the object database
# are shared; a working-tree-local directory like this one is not one of them).
_DISK_CACHE_DIR = ROOT / ".pytest_cache" / "repo_scan_cache"

# Directory NAMES the fingerprint walk never descends into, at any depth: build
# output / dependency / cache directories that are either irrelevant to what a
# doc/wiki/fixture scan reads, or — `.pytest_cache` specifically — THIS cache's own
# write target, which would otherwise invalidate itself the instant it wrote an
# entry (every fingerprint call after the first write would see a changed mtime
# under its own directory and never hit again).
_FINGERPRINT_SKIP_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        ".venv",
        "cdk.out",
        ".mypy_cache",
        ".ruff_cache",
        "htmlcov",
        ".tox",
    }
)


def _tree_fingerprint(root: Path = ROOT) -> str:
    """A cheap fingerprint of the working tree, used to key the disk cache.

    Deliberately NOT `git`-based (rev-parse HEAD + status), for two reasons:

    1. **It must never go through `subprocess.run`.** This module's own tests fake
       `repo_scan_cache.subprocess.run` to count SCAN spawns exactly — and
       `subprocess` is one shared module object, so faking `.run` for the scan
       would silently fake it for a git-based fingerprint too, corrupting the
       exact-spawn-count assertions that predate this cache's disk layer.
    2. **A `git status --porcelain` STRING has a gap.** Its one-line-per-path output
       is identical before and after a SECOND edit to a file that was already
       dirty ("M path" both times) — a disk entry primed after the first edit
       would still look current after the second. A raw mtime+size walk has no
       such gap: every edit, tracked or not, changes SOME file's stat().

    Measured 2026-09-19 on this repo: a full `os.walk` + `stat()` over ~3,800 files
    (the skip-list above excluding heavy build/cache dirs) costs ~40ms — negligible
    next to the 7-15s scans this cache exists to share, and paid on every
    `run_repo_scan` call (not memoized itself) precisely so a mutation mid-process
    is never masked by a stale fingerprint.
    """
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _FINGERPRINT_SKIP_DIRS)
        for name in sorted(filenames):
            p = Path(dirpath) / name
            try:
                st = p.stat()
            except OSError:
                continue
            rel = p.relative_to(root).as_posix()
            h.update(f"{rel}:{st.st_size}:{st.st_mtime_ns}\n".encode("utf-8", errors="surrogateescape"))
    return h.hexdigest()


def _disk_key(argv: tuple[str, ...], cwd: str, env_overrides: tuple[tuple[str, str], ...], tree_fp: str) -> str:
    blob = repr((argv, cwd, env_overrides, tree_fp)).encode()
    return hashlib.sha256(blob).hexdigest()


def _disk_read(disk_dir: Path, key: str) -> subprocess.CompletedProcess | None:
    path = disk_dir / f"{key}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return subprocess.CompletedProcess(data.get("argv"), data["returncode"], data["stdout"], data["stderr"])


def _disk_write(disk_dir: Path, key: str, result: subprocess.CompletedProcess) -> None:
    disk_dir.mkdir(parents=True, exist_ok=True)
    payload = {"argv": list(result.args), "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    # Atomic: write to a private temp file in the SAME directory (same filesystem,
    # so os.replace is a rename, not a copy) then swap it in. Two workers racing on
    # an identical key both compute the identical answer (the scan is deterministic
    # against a fixed tree) and either write wins; a reader never observes a
    # partially-written file.
    fd, tmp_name = tempfile.mkstemp(dir=disk_dir, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp_name, disk_dir / f"{key}.json")
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass


class _CacheInfo:
    __slots__ = ("hits", "misses")

    def __init__(self) -> None:
        self.hits = 0
        self.misses = 0

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"_CacheInfo(hits={self.hits}, misses={self.misses})"


def new_cache(disk_dir: Path | None = _DISK_CACHE_DIR):
    """A FRESH, independent memo table — in-memory always; disk-backed only when
    `disk_dir` is given (the module-level shared table's default).

    Exists so the cache's own tests can `monkeypatch.setattr(repo_scan_cache,
    "_run_once", repo_scan_cache.new_cache(disk_dir=None))` and exercise hit/miss
    behaviour in isolation, with monkeypatch restoring the shared table afterwards.
    `disk_dir=None` there is NOT cosmetic: those tests fake `subprocess.run` and
    assert an EXACT spawn count for a given key — if the real disk cache already
    held an answer for that same key from an earlier real run in the same tree
    state (fully possible: the low-level tests use the SAME real
    `check_doc_facts.py` argv the real call sites do), a disk hit would silently
    return 0 fake spawns instead of 1 and the test would fail for the wrong reason.
    Passing `disk_dir=None` keeps those tests exactly as fast and exactly as
    isolated as they were before this file grew a disk layer.

    THIS IS NOT COSMETIC in the in-memory direction either — #3224's first CI run
    proved it. The test file used an autouse `cache_clear()` on the SHARED table
    instead — a live defect, caught by PR #3231's own CI `--durations` block and by
    nothing else. This file sorts between `test_doc_facts_ops_*.py` and
    `test_wiki_checkers.py`, so it threw away a scan already paid for and
    `test_wiki_checkers.py::test_doc_facts_clean` re-spawned at 21.59s. Half the
    saving evaporated with all 12 of those tests still green — visible ONLY in the
    `--durations` block. Never clear the shared table to set up a test; swap.
    """
    mem: dict = {}
    info = _CacheInfo()

    def _run(argv: tuple[str, ...], cwd: str, env_overrides: tuple[tuple[str, str], ...], tree_fp: str) -> subprocess.CompletedProcess:
        key = (argv, cwd, env_overrides, tree_fp)
        hit = mem.get(key)
        if hit is not None:
            info.hits += 1
            return hit
        if disk_dir is not None:
            disk_hit = _disk_read(disk_dir, _disk_key(argv, cwd, env_overrides, tree_fp))
            if disk_hit is not None:
                mem[key] = disk_hit
                info.hits += 1
                return disk_hit
        info.misses += 1
        env = None
        if env_overrides:
            env = dict(os.environ, **dict(env_overrides))
        result = subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True, env=env)
        mem[key] = result
        if disk_dir is not None:
            _disk_write(disk_dir, _disk_key(argv, cwd, env_overrides, tree_fp), result)
        return result

    def _cache_clear() -> None:
        mem.clear()
        info.hits = 0
        info.misses = 0

    def _cache_info() -> _CacheInfo:
        return info

    _run.cache_clear = _cache_clear  # type: ignore[attr-defined]
    _run.cache_info = _cache_info  # type: ignore[attr-defined]
    return _run


_run_once = new_cache()


def run_repo_scan(script: str, *args: str, cwd: Path | str | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run ``script`` (a repo-relative path) against the UNMUTATED repo tree, once
    per (argv, cwd, env, tree-state) — shared across every worker PROCESS in this
    job via the disk layer, not just within one.

    Returns a fresh :class:`subprocess.CompletedProcess` per call — the cached result
    is copied out, so one test cannot mutate another test's view of it.

    Read the module docstring before adding a call site: this is only sound for scans
    of the tree as committed.
    """
    argv = (sys.executable, str(ROOT / script), *args)
    cwd_s = str(cwd or ROOT)
    overrides = tuple(sorted((env or {}).items()))
    tree_fp = _tree_fingerprint(ROOT)
    cached = _run_once(argv, cwd_s, overrides, tree_fp)
    return subprocess.CompletedProcess(cached.args, cached.returncode, cached.stdout, cached.stderr)


def cache_clear() -> None:
    """Drop every memoized scan on the CURRENT table (in-memory only — the disk
    layer is left alone; a genuinely invalidated tree already gets a fresh disk key
    via `_tree_fingerprint`, and reaching into a sibling worker process's files to
    delete them would be the cross-process version of the exact mistake this
    function's docstring already warns about in-process).

    Do NOT call this to set up a test — see `new_cache()` for the incident that
    warning is made of. It exists for a caller that genuinely invalidated the tree
    and knows every other consumer wants the new answer.
    """
    _run_once.cache_clear()


def cache_info() -> _CacheInfo:
    """Cache statistics (`.hits` / `.misses`) — the non-vacuity hook the cache's own
    tests use to prove a second call was a HIT and not a silent second spawn."""
    return _run_once.cache_info()
