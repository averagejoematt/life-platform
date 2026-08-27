"""tests/test_repo_scan_cache_3224.py — the shared repo-scan cache must actually
collapse duplicate spawns, and must NEVER collapse two scans that differ (#3224).

WHY THIS FILE IS NOT OPTIONAL. A cache that silently misses is invisible: every test
still passes, just as slowly as before, and the whole point of #3224 is lost with no
signal. A cache that over-shares is worse — it would hand a mutation proof somebody
else's answer and make a gate pass without running. Both directions are pinned here.

The suite-cost win this protects, measured 2026-08-27 at 10315b618:
`python3 scripts/check_doc_facts.py` costs 15.4s locally / ~27.5s on CI's
coverage-instrumented lane, and THREE tests asserted it against the identical
unmutated tree.
"""

import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(_REPO / "tests"))
import repo_scan_cache  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_cache():
    """Each test starts from an empty cache and leaves one behind, so this file can
    never depend on — or poison — another test's memoized scans."""
    repo_scan_cache.cache_clear()
    yield
    repo_scan_cache.cache_clear()


def _counting_run(counter):
    def _fake(argv, **kwargs):
        counter.append(argv)
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    return _fake


# ── it really does collapse N spawns into one (the non-vacuity half) ─────────
def test_a_repeated_identical_scan_spawns_exactly_once(monkeypatch):
    spawns: list = []
    monkeypatch.setattr(repo_scan_cache.subprocess, "run", _counting_run(spawns))

    first = repo_scan_cache.run_repo_scan("scripts/check_doc_facts.py")
    second = repo_scan_cache.run_repo_scan("scripts/check_doc_facts.py")
    third = repo_scan_cache.run_repo_scan("scripts/check_doc_facts.py")

    assert len(spawns) == 1, f"the cache missed — {len(spawns)} spawns for one identical scan"
    assert repo_scan_cache.cache_info().hits == 2
    assert first.returncode == second.returncode == third.returncode == 0
    assert first.stdout == second.stdout == third.stdout == "ok"


# ── …and never over-shares (the can-it-fail half, in three directions) ───────
def test_b_a_different_env_is_a_different_key(monkeypatch):
    """test_wiki_checkers.py::test_verified_advisory_is_warn_only runs the same script
    under CHECK_DOC_FACTS_TODAY=2036-01-01 and asserts DIFFERENT output. If the env
    were dropped from the key it would read the plain run's result and the advisory
    would be proved by nothing."""
    spawns: list = []
    monkeypatch.setattr(repo_scan_cache.subprocess, "run", _counting_run(spawns))

    repo_scan_cache.run_repo_scan("scripts/check_doc_facts.py")
    repo_scan_cache.run_repo_scan("scripts/check_doc_facts.py", env={"CHECK_DOC_FACTS_TODAY": "2036-01-01"})

    assert len(spawns) == 2, "an env override collided with the plain run — the cache key ignores env"


def test_c_different_args_are_a_different_key(monkeypatch):
    spawns: list = []
    monkeypatch.setattr(repo_scan_cache.subprocess, "run", _counting_run(spawns))

    repo_scan_cache.run_repo_scan("scripts/check_doc_facts.py")
    repo_scan_cache.run_repo_scan("scripts/check_doc_facts.py", "--strict")

    assert len(spawns) == 2, "a flag was dropped from the cache key"


def test_d_a_different_cwd_is_a_different_key(monkeypatch, tmp_path):
    spawns: list = []
    monkeypatch.setattr(repo_scan_cache.subprocess, "run", _counting_run(spawns))

    repo_scan_cache.run_repo_scan("scripts/check_doc_facts.py")
    repo_scan_cache.run_repo_scan("scripts/check_doc_facts.py", cwd=tmp_path)

    assert len(spawns) == 2, "cwd was dropped from the cache key"


def test_e_the_env_override_is_layered_over_the_real_environment(monkeypatch):
    """`env=` must EXTEND os.environ, not replace it — a scan launched with a
    two-key environment would fail for reasons that have nothing to do with the gate
    (no PATH, no HOME) and the failure would be attributed to the doc it scanned."""
    seen: dict = {}

    def _fake(argv, **kwargs):
        seen.update(kwargs.get("env") or {})
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(repo_scan_cache.subprocess, "run", _fake)
    monkeypatch.setenv("REPO_SCAN_CACHE_PROBE_3224", "present")

    repo_scan_cache.run_repo_scan("scripts/check_doc_facts.py", env={"CHECK_DOC_FACTS_TODAY": "2036-01-01"})

    assert seen.get("CHECK_DOC_FACTS_TODAY") == "2036-01-01"
    assert seen.get("REPO_SCAN_CACHE_PROBE_3224") == "present", "env= replaced the environment instead of layering over it"
    assert "PATH" in seen


def test_f_callers_get_their_own_object_and_cannot_corrupt_each_other(monkeypatch):
    spawns: list = []
    monkeypatch.setattr(repo_scan_cache.subprocess, "run", _counting_run(spawns))

    first = repo_scan_cache.run_repo_scan("scripts/check_doc_facts.py")
    first.returncode = 99
    first.stdout = "clobbered"
    second = repo_scan_cache.run_repo_scan("scripts/check_doc_facts.py")

    assert second.returncode == 0 and second.stdout == "ok", "one caller's mutation leaked into the next caller's result"


# ── the live path really spawns a real interpreter and returns real output ───
def test_g_a_real_scan_runs_and_is_reused():
    """End-to-end against a genuinely cheap real script (measured 0.40s), so this file
    proves the helper works without itself paying a 15s scan."""
    first = repo_scan_cache.run_repo_scan("scripts/check_doc_index.py")
    assert first.returncode == 0, first.stdout + first.stderr
    misses_after_first = repo_scan_cache.cache_info().misses

    second = repo_scan_cache.run_repo_scan("scripts/check_doc_index.py")

    assert second.stdout == first.stdout
    assert repo_scan_cache.cache_info().misses == misses_after_first, "the second real call re-spawned"


# ── the WIN is guarded structurally, not just demonstrated once (#3224) ──────
_SHARED_CALL_SITES = (
    "tests/test_doc_facts_ops_1957.py",
    "tests/test_doc_facts_ops_2003.py",
    "tests/test_wiki_checkers.py",
)


@pytest.mark.parametrize("rel", _SHARED_CALL_SITES)
def test_h_the_three_duplicate_call_sites_still_route_through_the_cache(rel):
    """Guard the SET, not the instance. Reverting any one of these to a bare
    `subprocess.run([... check_doc_facts.py ...])` silently restores a ~27.5s CI cost
    with every test still green — exactly the shape #3224 was filed about."""
    src = (_REPO / rel).read_text(encoding="utf-8")
    assert 'repo_scan_cache.run_repo_scan("scripts/check_doc_facts.py")' in src, (
        f"{rel} no longer runs the unmutated-tree doc-facts scan through tests/repo_scan_cache.py — "
        "the duplicate-spawn cost is back (#3224)"
    )


def test_i_the_advisory_run_is_deliberately_not_shared():
    """The one caller that must NOT share: it needs its own env and its own answer."""
    src = (_REPO / "tests" / "test_wiki_checkers.py").read_text(encoding="utf-8")
    advisory = src.split("def test_verified_advisory_is_warn_only")[1].split("\ndef ")[0]
    assert "CHECK_DOC_FACTS_TODAY" in advisory
    assert 'run_repo_scan("scripts/check_doc_facts.py")' not in advisory, (
        "the decade-stale-clock advisory run was routed onto the plain scan's cache key — it would then "
        "assert against output produced by a different clock"
    )


def test_j_cache_clear_actually_clears(monkeypatch):
    """The escape hatch has to work, or a future test that legitimately needs a fresh
    scan would get a stale one and pass without running."""
    spawns: list = []
    monkeypatch.setattr(repo_scan_cache.subprocess, "run", _counting_run(spawns))

    repo_scan_cache.run_repo_scan("scripts/check_doc_facts.py")
    repo_scan_cache.cache_clear()
    repo_scan_cache.run_repo_scan("scripts/check_doc_facts.py")

    assert len(spawns) == 2, "cache_clear() did not clear — a later test needing a fresh scan would silently get a stale one"
