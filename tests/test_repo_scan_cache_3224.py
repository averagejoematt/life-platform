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

#3731 added the disk-backed cross-process layer (tests below `test_l_`) — the
in-memory layer above stays pinned exactly as before, now proved NOT to leak into
or out of the disk layer (`disk_dir=None` isolation, `test_l`/`test_m`/`test_n`).
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(_REPO / "tests"))
import repo_scan_cache  # noqa: E402

# #3731: test_n / test_o write to the REAL docs/PROPORTIONALITY.md (reverted in a
# `finally`) to prove `_tree_fingerprint()` reacts to a genuine edit — a tmp_path copy
# would prove nothing, since the fingerprint walks ROOT, not an argument. That races
# every other test's rglob sweep under `pytest -n auto --dist loadfile` (#3025);
# registered in tests/test_suite_parallel_safety_3025.py's IN_TREE_WRITERS, whole-file
# per that registry's own convention (`--dist loadfile` schedules by file anyway).
pytestmark = pytest.mark.serial


@pytest.fixture(autouse=True)
def _private_cache(monkeypatch):
    """Each test gets its OWN empty memo table, and monkeypatch restores the shared
    one afterwards.

    The first version of this fixture called `repo_scan_cache.cache_clear()` on the
    SHARED table instead — a live defect, caught by PR #3231's own CI `--durations`
    block and by nothing else. This file sorts between `test_doc_facts_ops_*.py` and
    `test_wiki_checkers.py`, so clearing here threw away a scan already paid for:
    `test_wiki_checkers.py::test_doc_facts_clean` re-spawned at 21.59s and half of
    #3224's saving silently evaporated while all 12 tests below stayed green. Swap,
    never clear.

    `disk_dir=None` (#3731): this fixture's private table must NOT read or write the
    real `.pytest_cache/repo_scan_cache/` disk layer — see `new_cache()`'s own
    docstring for why a disk hit would silently corrupt these tests' exact-spawn-count
    assertions. Tests that specifically exercise the disk layer build their own
    `new_cache(disk_dir=tmp_path / "disk")` instead of relying on this fixture's table.
    """
    monkeypatch.setattr(repo_scan_cache, "_run_once", repo_scan_cache.new_cache(disk_dir=None))


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


def test_k_this_files_own_fixture_must_never_clear_the_SHARED_cache():
    """The regression guard for the defect this file itself shipped on #3231's first
    CI run. An autouse `cache_clear()` here is invisible — every test still passes and
    the only symptom is a ~21.6s scan reappearing in a `--durations` block nobody
    reads. Structural, because that is the only layer at which it is visible at all."""
    src = (_REPO / "tests" / "test_repo_scan_cache_3224.py").read_text(encoding="utf-8")
    fn = next(
        (n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "_private_cache"),
        None,
    )
    assert fn is not None, "the autouse fixture `_private_cache` is gone (#3224)"
    # AST, not a substring sweep — this file's own docstrings quote `cache_clear()`
    # while explaining the incident, and a text match would flag the explanation.
    called = {node.func.attr for node in ast.walk(fn) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "new_cache" in called, "the autouse fixture no longer swaps in a private memo table (#3224)"
    assert "cache_clear" not in called, (
        "the autouse fixture clears the SHARED cache — it runs between "
        "tests/test_doc_facts_ops_*.py and tests/test_wiki_checkers.py and will silently "
        "re-spawn a whole-repo scan the suite already paid for (#3224)"
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


# ── the disk-backed layer (#3731): cross-process sharing, and it cannot go stale ──
#
# Everything below builds its OWN table via `new_cache(disk_dir=...)` rather than
# using the autouse `_private_cache` fixture (that fixture is disk_dir=None on
# purpose — see its docstring), because these tests exist specifically to prove the
# disk path.


def test_l_a_second_TABLE_reads_the_first_tables_disk_write(monkeypatch, tmp_path):
    """The whole point: two SEPARATE in-memory tables (standing in for two xdist
    WORKER PROCESSES, which cannot share a Python object) sharing one disk
    directory collapse to a single real spawn, not one each."""
    disk = tmp_path / "disk"
    spawns: list = []
    monkeypatch.setattr(repo_scan_cache.subprocess, "run", _counting_run(spawns))

    worker_a = repo_scan_cache.new_cache(disk_dir=disk)
    worker_b = repo_scan_cache.new_cache(disk_dir=disk)
    tree_fp = repo_scan_cache._tree_fingerprint()
    argv = (sys.executable, str(_REPO / "scripts" / "check_doc_facts.py"))

    first = worker_a(argv, str(_REPO), (), tree_fp)
    second = worker_b(argv, str(_REPO), (), tree_fp)  # a FRESH table — no shared Python object

    assert len(spawns) == 1, f"two independent tables sharing one disk dir still spawned {len(spawns)} times"
    assert second.returncode == first.returncode and second.stdout == first.stdout


def test_m_the_disk_layer_never_leaks_into_the_isolated_low_level_tests(tmp_path):
    """`disk_dir=None` really does turn the disk layer off — a table built that way
    must not create anything on disk, or a stray file could later masquerade as a
    real cached scan for some other key that happens to collide."""
    disk = tmp_path / "disk"
    table = repo_scan_cache.new_cache(disk_dir=None)
    argv = (sys.executable, str(_REPO / "scripts" / "check_doc_index.py"))
    table(argv, str(_REPO), (), "irrelevant-fixed-fp")
    assert not disk.exists(), "a disk_dir=None table wrote to disk anyway"


def test_n_tree_fingerprint_changes_when_an_already_dirty_file_is_edited_again(tmp_path):
    """The reason `_tree_fingerprint` stat()s the whole tree instead of trusting a
    `git status --porcelain` STRING: porcelain's one-line-per-path output is
    identical before and after a SECOND edit to a file that was already dirty (both
    times it just reads "M path"). A porcelain-string-only fingerprint would collide
    on these two edits and a disk cache primed after the first would still look
    current after the second — served STALE to whichever worker asks next."""
    target = _REPO / "docs" / "PROPORTIONALITY.md"
    original = target.read_text(encoding="utf-8")
    try:
        target.write_text(original + "\n<!-- repo_scan_cache_3731 probe A -->\n", encoding="utf-8")
        fp_after_first_edit = repo_scan_cache._tree_fingerprint()
        target.write_text(original + "\n<!-- repo_scan_cache_3731 probe B -->\n", encoding="utf-8")
        fp_after_second_edit = repo_scan_cache._tree_fingerprint()
        assert fp_after_first_edit != fp_after_second_edit, (
            "editing an already-dirty file produced the SAME tree fingerprint — "
            "a disk cache entry from before the second edit would be served as if it were current"
        )
    finally:
        target.write_text(original, encoding="utf-8")


def test_o_a_real_edit_between_two_real_run_repo_scan_calls_is_never_served_stale(monkeypatch):
    """THE MUST-FAIL CONTROL (#3731 box 5): this calls the real, un-monkeypatched
    `run_repo_scan` -> `_run_once` -> `_tree_fingerprint` production path (only
    `subprocess.run` itself is faked, to keep this fast) and edits a REAL file the
    doc-facts family actually scans in between two calls with otherwise-identical
    argv/cwd/env.

    If `_tree_fingerprint` regressed to a constant (or to a `git status --porcelain`
    STRING with no stat() term — see `test_n`), the cache key would not change
    across the edit, the second call would be a HIT, and `spawns` would be `[argv]`
    (length 1) instead of `[argv, argv]` (length 2). Verified failing: patching
    `repo_scan_cache._tree_fingerprint` to `lambda root=None: "CONSTANT"` before
    running this test reds it with `len(spawns) == 1` — exactly the staleness this
    module exists to prevent, now visible as a failing assertion instead of a
    silently-wrong gate.
    """
    spawns: list = []
    monkeypatch.setattr(repo_scan_cache.subprocess, "run", _counting_run(spawns))

    target = _REPO / "docs" / "PROPORTIONALITY.md"
    original = target.read_text(encoding="utf-8")
    try:
        repo_scan_cache.run_repo_scan("scripts/check_doc_index.py")

        target.write_text(original + "\n<!-- repo_scan_cache_3731 test_o probe -->\n", encoding="utf-8")

        repo_scan_cache.run_repo_scan("scripts/check_doc_index.py")

        assert len(spawns) == 2, (
            f"a real edit to a real scanned file between two calls was served from cache ({len(spawns)} spawn(s), "
            "expected 2) — the tree-state term of the cache key did not change with the edit"
        )
    finally:
        target.write_text(original, encoding="utf-8")
