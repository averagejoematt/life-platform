"""tests/test_hevy_resolution_and_timeout_3763_3765.py — the cliff, the index, the deadline.

THE MEASUREMENT (2026-09-13, local, real S3 config + real Hevy GETs, persist stubbed)

  20 exact Hevy titles                     resolution 0.01 s
   7 titles, 1 non-exact                              8.35 s   (that ONE title: 8.34 s)
  20 titles, 3 non-exact                             27.46 s   ≈ the 30 s soft timeout
   7 titles, 4 index-misses that exist live           10.9 s   (1–4 s each = page position)

  The owner had carried an operational note for months — "draft_custom times out above ~7
  exercises" — and designed around it. No such cap exists anywhere in the code or the docs
  (#3771). The real cost model is per NON-EXACT TITLE: `_resolve_movement_key` ran the live
  Hevy walk (828 templates = 9 pages at the client's 1 req/s throttle) at step 4, ahead of
  the free in-memory curated match at step 5, once per exercise, with no memo across the
  draft. 'Leg Curl (Machine)' walked all nine pages and THEN matched the curated catalog.

  Three fixes, pinned here:
    #3763  every free step before the paid one; one shared walk per draft; index memoized
    #3764  the index gets a producer (it was hand-built once, 789 vs 828 live 3.5 months on)
    #3765  the soft timeout returns AT the deadline instead of after the tool finishes
"""

from __future__ import annotations

import concurrent.futures
import os
import pathlib
import sys
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import hevy_template_index as hti  # noqa: E402

import mcp.hevy_resolution as res  # noqa: E402
import mcp.tools_hevy_routine as thr  # noqa: E402

# Captured before the autouse fixture patches the name, so the memo test can exercise the
# real loader rather than the stub.
_REAL_TEMPLATE_INDEX = res._template_index

# A miniature index in the live shape: normalized title -> {id, title}.
_INDEX = {
    "squat (barbell)": {"id": "D04AC939", "title": "Squat (Barbell)"},
    "bench press (barbell)": {"id": "79D0BB3A", "title": "Bench Press (Barbell)"},
    "seated leg curl (machine)": {"id": "11A123F3", "title": "Seated Leg Curl (Machine)"},
    "lying leg curl (machine)": {"id": "22B234F4", "title": "Lying Leg Curl (Machine)"},
    "leg extension (machine)": {"id": "75A4F6C4", "title": "Leg Extension (Machine)"},
}


class _Lister:
    """Counts how many times the live catalogue is paged."""

    def __init__(self, titles=(), page_size=100):
        self.calls = 0
        self.pages_served = 0
        self._titles = list(titles)
        self._page_size = page_size

    def __call__(self, page=1, page_size=100):
        self.calls += 1
        self.pages_served += 1
        start = (page - 1) * self._page_size
        chunk = self._titles[start : start + self._page_size]
        return {"exercise_templates": [{"id": f"LIVE{i}", "title": t} for i, t in enumerate(chunk, start)]}


@pytest.fixture(autouse=True)
def _fresh_index(monkeypatch):
    res._reset_index_cache_for_tests()
    monkeypatch.setattr(res, "_template_index", lambda *a, **k: _INDEX)
    monkeypatch.setattr(thr, "_template_index", lambda *a, **k: _INDEX)
    yield
    res._reset_index_cache_for_tests()


def _ex(title):
    return {"title": title, "sets": [{"weight_lbs": 100, "reps": 10}]}


# ── #3763: the free steps come first, and the walk happens at most once ───────
def test_exact_index_titles_never_touch_the_live_catalogue():
    """20 exact titles used to cost 0.01s already — this pins that they still do."""
    lister = _Lister()
    walk = res._LiveWalk(lister)
    catalog = {}
    for title in [v["title"] for v in _INDEX.values()] * 4:
        assert thr._resolve_movement_key(_ex(title), catalog, walk) is not None
    assert lister.calls == 0, f"an exact index hit walked the live catalogue {lister.calls} time(s)"


def test_a_near_miss_title_resolves_from_the_index_without_a_walk():
    """'Leg Curl (Machine)' is not a Hevy title; 'Seated Leg Curl (Machine)' is.

    That one-word gap cost a full 9-page walk before #3763 — and then resolved from the
    curated loose match anyway. Here it must resolve for free... but only when it is
    UNAMBIGUOUS, which this index deliberately makes it not (seated AND lying both match),
    so the correct answer is that the token-subset step declines and the walk decides.
    """
    assert res._index_fuzzy("Leg Curl (Machine)") is None, "an ambiguous token match must not guess"
    # With only one candidate it resolves, still for free:
    assert res._index_fuzzy("Leg Extension") == "75A4F6C4"
    assert res._index_fuzzy("Squat Barbell") == "D04AC939"


def test_fuzzy_match_never_invents_a_movement():
    """NEGATIVE CONTROL — tokens absent from every title resolve to nothing."""
    assert res._index_fuzzy("Zercher Carry") is None
    assert res._index_fuzzy("") is None


def test_one_walk_serves_every_unresolved_title_in_a_draft():
    """Three unknown titles used to mean three full walks from page 1 (~27s)."""
    lister = _Lister(titles=[f"Made Up {i}" for i in range(250)])
    walk = res._LiveWalk(lister)
    for i in range(3):
        walk.id_for(f"Made Up {i}")
    assert lister.pages_served == 3, f"expected one 3-page walk shared by all three titles, got {lister.pages_served} page fetches"
    # And a fourth title costs nothing more.
    before = lister.pages_served
    walk.id_for("Made Up 200")
    assert lister.pages_served == before


def test_a_failed_walk_is_not_retried_per_title():
    """A 429 mid-walk used to be paid again by every remaining title."""

    def _boom(page=1, page_size=100):
        raise RuntimeError("Hevy 429")

    calls = {"n": 0}

    def _counting(page=1, page_size=100):
        calls["n"] += 1
        return _boom(page=page, page_size=page_size)

    walk = res._LiveWalk(_counting)
    assert walk.id_for("A") is None
    assert walk.id_for("B") is None
    assert calls["n"] == 1


def test_the_walk_is_lazy():
    """A draft where everything resolves for free must not open the catalogue at all."""
    lister = _Lister(titles=["Whatever"])
    walk = res._LiveWalk(lister)
    thr._resolve_movement_key(_ex("Squat (Barbell)"), {}, walk)
    assert lister.calls == 0


def test_the_index_is_memoized(monkeypatch):
    """It was re-read from S3 once per exercise — 20 GETs of the same 98 KB object per draft."""
    loads = {"n": 0}

    def _fake_load(name):
        loads["n"] += 1
        return {"templates": _INDEX}

    monkeypatch.setattr("training.routine_generator._load_json", _fake_load)
    res._reset_index_cache_for_tests()
    for _ in range(5):
        assert _REAL_TEMPLATE_INDEX() == _INDEX
    assert loads["n"] == 1, f"the index was loaded {loads['n']} times for 5 lookups"

    # NEGATIVE CONTROL: the cache is a TTL, not a one-way latch — a forced read re-loads.
    assert _REAL_TEMPLATE_INDEX(force=True) == _INDEX
    assert loads["n"] == 2


# ── #3764: the index has a producer, and it refuses a partial walk ────────────
def test_rebuild_writes_the_shape_the_resolver_reads():
    written = {}
    lister = _Lister(titles=["Squat (Barbell)", "Cable Pallof Press"])
    out = hti.rebuild(lister, lambda k, p: written.update({k: p}), lambda k: {"count": 1})

    assert out["written"] is True and out["count"] == 2
    payload = written[hti.INDEX_KEY]
    assert payload["templates"]["cable pallof press"]["title"] == "Cable Pallof Press"
    assert payload["_sha256"] and payload["_built_at"] and payload["count"] == 2


def test_the_writer_and_the_reader_normalize_titles_identically():
    """Two normalizers that disagree means every lookup misses. Assert, don't assume."""
    for raw in ("  Seated   Leg Curl (Machine) ", "BENCH Press (Barbell)", "Farmers Carry"):
        assert hti.normalize_title(raw) == res._normalize_title(raw)


def test_rebuild_refuses_to_shrink_the_index():
    """A 429 mid-pagination would otherwise publish a truncated catalogue silently."""
    written = {}
    lister = _Lister(titles=["Squat (Barbell)"])
    out = hti.rebuild(lister, lambda k, p: written.update({k: p}), lambda k: {"count": 828})

    assert out["written"] is False and "shrink" in out["reason"]
    assert written == {}, "a partial walk was published"


def test_rebuild_shrink_can_be_overridden_deliberately():
    """NEGATIVE CONTROL — the guard is a refusal, not a wall."""
    written = {}
    lister = _Lister(titles=["Squat (Barbell)"])
    out = hti.rebuild(lister, lambda k, p: written.update({k: p}), lambda k: {"count": 828}, allow_shrink=True)
    assert out["written"] is True and written


def test_rebuild_is_reachable_from_an_invoke():
    import ast

    src = (REPO / "lambdas" / "ingestion" / "hevy_backfill_lambda.py").read_text()
    tree = ast.parse(src)
    handler = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "lambda_handler")
    assert "rebuild_template_index" in (ast.get_source_segment(src, handler) or "")


# ── #3765: the deadline is real ───────────────────────────────────────────────
def test_the_soft_timeout_returns_at_the_deadline_not_after_the_tool_finishes():
    """The defect, reproduced as a unit: `with ThreadPoolExecutor(...)` calls
    shutdown(wait=True) on exit, so the `return` inside the block waited for the tool.
    Measured before the fix: a 3s task with timeout=1 returned after 3.01s."""

    def _slow():
        time.sleep(2.0)
        return "done"

    t0 = time.time()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(_slow)
    try:
        fut.result(timeout=0.3)
        raise AssertionError("the fixture did not time out")
    except concurrent.futures.TimeoutError:
        pool.shutdown(wait=False)
    elapsed = time.time() - t0

    assert elapsed < 1.0, f"shutdown(wait=False) still blocked for {elapsed:.2f}s"


def test_the_handler_uses_a_non_blocking_shutdown_on_timeout():
    """Pin the SHAPE in the handler, since driving the real 30s path in a unit test
    would cost 30 seconds of CI on every run."""
    import ast

    src = (REPO / "mcp" / "handler.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "handle_tools_call")
    seg = ast.get_source_segment(src, fn) or ""
    assert "ThreadPoolExecutor" in seg
    assert "with concurrent.futures.ThreadPoolExecutor" not in seg, (
        "the executor is used as a context manager again — its __exit__ calls shutdown(wait=True), "
        "which is exactly the #3765 defect: the client waits the tool's full duration and is then told it timed out"
    )
    assert "shutdown(wait=False)" in seg


def test_a_timed_out_write_tool_is_not_told_to_narrow_its_date_range():
    """'The query is likely scanning too much data' is false for a write, and it hides
    the only question that matters: did it land?"""
    src = (REPO / "mcp" / "handler.py").read_text()
    assert "WRITE_IN_FLIGHT" in src
    assert "may still be" in src and "do NOT retry blindly" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
