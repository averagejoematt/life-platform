"""tests/test_qa_reader_truth_midnight_5358.py — the reader-truth judge reads each page's OWN PT day.

#3030 pinned one clock at sweep start. The mirror case stayed open: a sweep that starts before
Pacific midnight renders its later pages after it, and those pages correctly show Day N+1 while the
judge was told Day N (run 40170579285 flagged /story/theme-river/ and /coaching/qa/ "Day 50" against
"Day 49"). visual_qa.capture_page now stamps each prose capture with the PT day it rendered on, and
visual_ai_qa.assess_reader_truth judges each page against that day — first pass AND the #3102
confirm re-judge.

Offline: no Playwright, no Bedrock. The clock is FIXED (#4848): the two instants straddle the
2026-10-25 Pacific midnight (07:00Z, PDT), and every expected day is derived from
EXPERIMENT_START_DATE, never pinned through a live clock.
"""

import os
import sys
import types
from datetime import date, datetime, timedelta, timezone
from unittest import mock

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import truth_baseline_audit as tba  # noqa: E402
import visual_ai_qa  # noqa: E402
import visual_qa  # noqa: E402
from common import pacific_time  # noqa: E402  (lambdas/ on sys.path via conftest)
from common.constants import EXPERIMENT_START_DATE  # noqa: E402

BEFORE = datetime(2026, 10, 25, 6, 59, tzinfo=timezone.utc)  # 23:59 PDT on 10-24
AFTER = datetime(2026, 10, 25, 7, 1, tzinfo=timezone.utc)  # 00:01 PDT on 10-25

# Day N and Day N+1 of the live cycle, derived — never a literal day number.
DAY_N = (date.fromisoformat(EXPERIMENT_START_DATE) + timedelta(days=48)).isoformat()
DAY_N1 = (date.fromisoformat(EXPERIMENT_START_DATE) + timedelta(days=49)).isoformat()


def _pt(instant):
    return lambda: instant.astimezone(pacific_time.PACIFIC)


def test_render_day_is_read_at_render_time_across_pacific_midnight():
    with mock.patch.object(pacific_time, "pacific_now", _pt(BEFORE)):
        before = visual_qa.render_day_pt()
    with mock.patch.object(pacific_time, "pacific_now", _pt(AFTER)):
        after = visual_qa.render_day_pt()
    assert (before, after) == ("2026-10-24", "2026-10-25")


def _result(path, today_pt=None):
    shot = {"kind": "prose", "path": __file__}
    if today_pt:
        shot["today_pt"] = today_pt
    return {"page": path, "path": path, "status": "PASS", "screenshots": [shot]}


def _run(results, sweep_day, first_pass_findings=(), second_pass=()):
    calls = []  # (pages, today_iso)

    def _assess_prose(surfaces, invoke, today_iso=None):
        pages = [s["path"] for s in surfaces]
        calls.append((pages, today_iso))
        if len(calls) <= len({r["screenshots"][0].get("today_pt") or sweep_day for r in results}):
            return [f for f in first_pass_findings if f["page"] in pages], []
        return [f for f in second_pass if f["page"] in pages], []

    rubric = types.SimpleNamespace(
        BUDGET_FEATURE="reader_truth_qa",
        DEFAULT_BATCH_SIZE=5,
        emit_budget_pause_metric=lambda *a, **k: None,
        assess_prose=_assess_prose,
        phase_context=lambda *a, **k: {"pre_start": False, "day_n": 49},
    )
    budget = types.SimpleNamespace(allow=lambda *a: True, current_tier=lambda: 0)
    with (
        mock.patch.object(visual_ai_qa, "_import_bedrock", return_value=types.SimpleNamespace(invoke=None)),
        mock.patch.dict(
            sys.modules,
            {
                "operational.reader_truth_qa": rubric,
                "operational": types.SimpleNamespace(reader_truth_qa=rubric),
                "ai": types.SimpleNamespace(budget_guard=budget),
                "ai.budget_guard": budget,
            },
        ),
        mock.patch.object(tba, "load_baseline", return_value={"_meta": {}, "pages": {}}),
    ):
        visual_ai_qa.assess_reader_truth(results, today_iso=sweep_day)
    return calls


def test_a_page_rendered_after_midnight_is_judged_against_its_own_day():
    results = [_result("/story/theme-river/", DAY_N), _result("/coaching/qa/", DAY_N1)]
    calls = _run(results, sweep_day=DAY_N)
    judged = {p: day for pages, day in calls for p in pages}
    assert judged == {"/story/theme-river/": DAY_N, "/coaching/qa/": DAY_N1}, calls


def test_the_confirm_rejudge_uses_the_pages_render_day_too():
    f = {"page": "/coaching/qa/", "category": "temporal_contradiction", "severity": "high", "note": "Day mismatch"}
    results = [_result("/story/theme-river/", DAY_N), _result("/coaching/qa/", DAY_N1)]
    calls = _run(results, sweep_day=DAY_N, first_pass_findings=[f], second_pass=[f])
    assert calls[-1] == (["/coaching/qa/"], DAY_N1), calls
    assert results[1]["status"] == "FAIL", "a finding that reproduces against the page's own day still gates"


def test_an_unstamped_sweep_keeps_one_clock_and_one_pass():
    results = [_result("/a/"), _result("/b/")]
    calls = _run(results, sweep_day=DAY_N)
    assert calls == [(["/a/", "/b/"], DAY_N)]
