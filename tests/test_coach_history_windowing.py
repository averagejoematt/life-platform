"""tests/test_coach_history_windowing.py — bounded compression input (#410).

Replays the historical silent-truncation failure: a coach at 52 open threads /
39 active predictions poured everything into one compression prompt, the
summary truncated mid-JSON, and the coach served a degraded context for weeks
(the max_tokens 1500→4000 bump was the band-aid). These tests pin the
supersession: the prompt carries a bounded, recency-ranked window of each
class plus an HONEST rollup of what was omitted, the whole message respects a
deterministic char budget, and nothing is archived or deleted.

All offline — pure function calls on synthetic state.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "coach"))

import coach_history_summarizer as chs  # noqa: E402


def _thread(i, last_ref):
    return {
        "sk": f"THREAD#thread-{i:03d}",
        "status": "open",
        "summary": f"Observation {i} about recovery-vs-training interplay over several weeks",
        "type": "observation",
        "reference_count": i % 7,
        "last_referenced": last_ref,
    }


def _prediction(i):
    return {
        "sk": f"PREDICTION#pred_2026{i + 100:04d}_claim_{i:03d}",
        "prediction_id": f"pred_{i:03d}",
        "claim_natural": f"If pattern {i} holds, the metric moves within two weeks",
        "status": "pending",
        "confidence": 0.6,
        "subdomain": "recovery",
    }


def _failure_case_state():
    """The real 2026-06-29 shape: 52 open threads, 39 active predictions."""
    threads = [_thread(i, f"2026-06-{(i % 28) + 1:02d}") for i in range(52)]
    threads.sort(key=lambda t: str(t.get("last_referenced", "")), reverse=True)
    return {
        "outputs": [
            {
                "sk": f"OUTPUT#2026-06-{d:02d}",
                "themes": ["recovery", "consistency"],
                "content": "A weekly read on the data. " * 20,
                "word_count": 480,
            }
            for d in range(1, 21)
        ],
        "open_threads": threads[: chs.MAX_OPEN_THREADS_IN_PROMPT],
        "open_threads_total": 52,
        "active_predictions": [_prediction(i) for i in range(39)][: chs.MAX_ACTIVE_PREDICTIONS_IN_PROMPT],
        "active_predictions_total": 39,
        "confidence_records": [{"subdomain": f"sub{i}", "mean_confidence": 0.5, "sample_size": i} for i in range(6)],
        "relationship_state": {"pk": "x", "sk": "y", "weeks_coaching": 12},
        "voice_state": {"recent_openings": ["The data says"], "overused_patterns": []},
    }


def test_failure_case_fits_the_input_budget():
    msg = chs._build_bounded_compression_message("training_coach", _failure_case_state())
    assert len(msg) <= chs.MAX_COMPRESSION_INPUT_CHARS


def test_rollup_lines_keep_omitted_counts_honest():
    msg = chs._build_bounded_compression_message("training_coach", _failure_case_state())
    assert f"showing the {chs.MAX_OPEN_THREADS_IN_PROMPT} most-recently-referenced of 52 open" in msg
    assert "omitted from this compression" in msg
    assert f"showing the {chs.MAX_ACTIVE_PREDICTIONS_IN_PROMPT} newest of 39 active" in msg
    assert "the evaluator still grades them" in msg


def test_windows_do_not_fire_below_the_caps():
    """A young coach (fewer records than the caps) sees no rollup wording."""
    state = _failure_case_state()
    state["open_threads"] = state["open_threads"][:3]
    state["open_threads_total"] = 3
    state["active_predictions"] = state["active_predictions"][:2]
    state["active_predictions_total"] = 2
    msg = chs._build_bounded_compression_message("training_coach", state)
    assert "omitted from this compression" not in msg
    assert "## Open Threads (3)" in msg
    assert "## Active Predictions (2)" in msg


def test_budget_guard_shrinks_windows_deterministically():
    """Pathologically fat records force the guard to halve the windows (never
    below the floor) instead of sending an over-budget prompt."""
    state = _failure_case_state()
    for t in state["open_threads"]:
        t["summary"] = "x" * 3000
    for p in state["active_predictions"]:
        p["claim_natural"] = "y" * 3000
    msg = chs._build_bounded_compression_message("training_coach", state)
    # Guard terminated (either under budget or at the floor with the warning path).
    floor_len = chs.MIN_WINDOW_FLOOR
    assert msg.count("[pending]") <= chs.MAX_ACTIVE_PREDICTIONS_IN_PROMPT
    # With 3000-char items, budget can only hold near-floor windows.
    assert msg.count("[observation]") <= max(floor_len, chs.MAX_OPEN_THREADS_IN_PROMPT // 2)


def test_prediction_scan_is_bounded_and_newest_first():
    """The partition read itself is bounded: newest-first with a hard limit,
    so decided history ages out of the scan while remaining stored."""
    calls = {}

    def _fake_query(pk, sk_prefix, scan_forward=True, limit=None, include_pilot=False, max_pages=None):
        calls[sk_prefix] = {"scan_forward": scan_forward, "limit": limit}
        return []

    orig = chs._query_begins_with
    chs._query_begins_with = _fake_query
    try:
        chs._gather_coach_state("training_coach")
    finally:
        chs._query_begins_with = orig
    assert calls["PREDICTION#"]["scan_forward"] is False
    assert calls["PREDICTION#"]["limit"] == chs.MAX_PREDICTION_SCAN
    assert calls["OUTPUT#"]["limit"] == chs.MAX_OUTPUT_RECORDS


def test_open_thread_window_is_recency_ranked():
    """The most-recently-referenced threads survive the window — the ones a
    coach would actually reference next — not arbitrary slug order."""
    threads = [_thread(i, f"2026-06-{(i % 28) + 1:02d}") for i in range(52)]

    def _fake_query(pk, sk_prefix, scan_forward=True, limit=None, include_pilot=False, max_pages=None):
        if sk_prefix == "THREAD#":
            return list(threads)
        return []

    orig = chs._query_begins_with
    chs._query_begins_with = _fake_query
    orig_get = chs._get_item
    chs._get_item = lambda pk, sk: None
    try:
        state = chs._gather_coach_state("training_coach")
    finally:
        chs._query_begins_with = orig
        chs._get_item = orig_get
    assert state["open_threads_total"] == 52
    assert len(state["open_threads"]) == chs.MAX_OPEN_THREADS_IN_PROMPT
    refs = [t["last_referenced"] for t in state["open_threads"]]
    assert refs == sorted(refs, reverse=True)
    assert refs[0] == "2026-06-28"  # the newest reference made the window


def test_nothing_is_deleted_by_the_windowing():
    """Source-level: the summarizer gained no delete path — windowing is read-
    side only; archived truth stays in DynamoDB per the issue's guardrail."""
    src = open(os.path.join(_REPO, "lambdas/coach/coach_history_summarizer.py")).read()
    assert "delete_item" not in src
