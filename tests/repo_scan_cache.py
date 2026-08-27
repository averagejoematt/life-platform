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
The cache key is (argv, cwd, env-overrides). It does NOT include the state of the
tree. So:

  * **Never** use it for a scan of a tree the test mutates — a tmp-dir copy with a
    planted defect, a monkeypatched file, a `--apply` run. Those are exactly the
    mutation proofs this repo relies on, and a cached answer would make them pass
    without running. Call `subprocess.run` directly there; it is one scan, not N.
  * **Never** use it for a scan whose result depends on something outside argv/cwd/env
    (wall-clock, network, a global the test sets).
  * A run with a distinct env (e.g. `check_doc_facts.py` under
    `CHECK_DOC_FACTS_TODAY=2036-01-01`) is a DIFFERENT key and is cached separately —
    correct, and it means such a run shares nothing with the plain one.

`tests/test_repo_scan_cache_3224.py` pins all of that, including a non-vacuity proof
that the cache really does collapse N spawns into one (a cache that silently missed
would be invisible: every test would still pass, just as slowly as before).
"""

from __future__ import annotations

import functools
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def new_cache():
    """A FRESH, independent memo table.

    Exists so the cache's own tests can `monkeypatch.setattr(repo_scan_cache,
    "_run_once", repo_scan_cache.new_cache())` and exercise hit/miss behaviour in
    isolation, with monkeypatch restoring the shared table afterwards. THIS IS NOT
    COSMETIC — #3224's first CI run proved it. The test file used an autouse
    `cache_clear()` on the SHARED table; it sorts between `test_doc_facts_ops_*.py`
    and `test_wiki_checkers.py`, so it threw away a scan already paid for and
    `test_wiki_checkers.py::test_doc_facts_clean` re-spawned at 21.59s. Half the
    saving evaporated with all 12 of those tests still green — visible ONLY in the
    `--durations` block. Never clear the shared table to set up a test; swap.
    """

    @functools.lru_cache(maxsize=None)
    def _run(argv: tuple[str, ...], cwd: str, env_overrides: tuple[tuple[str, str], ...]) -> subprocess.CompletedProcess:
        env = None
        if env_overrides:
            env = dict(os.environ, **dict(env_overrides))
        return subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True, env=env)

    return _run


_run_once = new_cache()


def run_repo_scan(script: str, *args: str, cwd: Path | str | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run ``script`` (a repo-relative path) against the UNMUTATED repo tree, once.

    Returns a fresh :class:`subprocess.CompletedProcess` per call — the cached result
    is copied out, so one test cannot mutate another test's view of it.

    Read the module docstring before adding a call site: this is only sound for scans
    of the tree as committed.
    """
    argv = (sys.executable, str(ROOT / script), *args)
    cwd_s = str(cwd or ROOT)
    overrides = tuple(sorted((env or {}).items()))
    cached = _run_once(argv, cwd_s, overrides)
    return subprocess.CompletedProcess(cached.args, cached.returncode, cached.stdout, cached.stderr)


def cache_clear() -> None:
    """Drop every memoized scan on the CURRENT table.

    Do NOT call this to set up a test — see `new_cache()` for the incident that
    warning is made of. It exists for a caller that genuinely invalidated the tree
    and knows every other consumer wants the new answer.
    """
    _run_once.cache_clear()


def cache_info():
    """``functools`` cache statistics — the non-vacuity hook the cache's own tests use
    to prove a second call was a HIT and not a silent second spawn."""
    return _run_once.cache_info()
