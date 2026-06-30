"""tests/test_reading_recall.py — spaced-retrieval scheduling + retention (Phase D)."""

from __future__ import annotations

import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

from reading import reading_recall as rc  # noqa: E402


def test_next_due_uses_intervals():
    assert rc.next_due(0, from_date="2026-06-01") == "2026-06-04"  # +3
    assert rc.next_due(1, from_date="2026-06-01") == "2026-06-08"  # +7
    assert rc.next_due(99, from_date="2026-06-01") == "2026-11-28"  # clamped to last (180)


def test_advance_ratchets_on_gist():
    assert rc.advance(1, 0.9) == 2  # strong → up
    assert rc.advance(2, 0.2) == 1  # weak → down (not to zero)
    assert rc.advance(0, 0.1) == 0  # weak at floor → stays 0
    assert rc.advance(3, 0.55) == 3  # middling → hold


def test_retention_is_n_gated():
    hist1 = [{"gistScore": 0.8}, {"gistScore": 0.7}]
    assert rc.retention_score(hist1) is None  # < 3 scored probes → no score
    hist2 = [{"gistScore": 0.6}, {"gistScore": 0.7}, {"gistScore": 0.9}]
    score = rc.retention_score(hist2)
    assert score is not None and 0.6 <= score <= 0.9
    # recency-weighted → closer to the recent 0.9 than a flat mean (0.733)
    assert score > 0.73


def test_retention_ignores_unscored_probes():
    hist = [{"gistScore": None}, {"gistScore": 0.8}, {"gistScore": 0.9}]
    assert rc.retention_score(hist) is None  # only 2 scored → still gated


def test_score_gist_happy_and_failsoft():
    import json

    def caller(_b):
        return {"content": [{"type": "text", "text": json.dumps({"gist": 0.85, "note": "reconstructed the argument"})}]}

    out = rc.score_gist("what stuck?", "He argued that...", caller=caller)
    assert out["scored"] is True and out["gist"] == 0.85

    out_empty = rc.score_gist("p", "", caller=caller)
    assert out_empty["scored"] is False and out_empty["gist"] is None

    def boom(_b):
        raise RuntimeError("down")

    out_fail = rc.score_gist("p", "an answer", caller=boom)
    assert out_fail["scored"] is False and out_fail["gist"] is None


def test_record_answer_advances_and_scores():
    import json

    def caller(_b):
        return {"content": [{"type": "text", "text": json.dumps({"gist": 0.8, "note": "solid"})}]}

    recall = {"prompt": "what stuck from X?", "intervalIndex": 1, "performanceHistory": []}
    out = rc.record_answer(recall, "I remember the core argument and it changed how I think about Y.", asked_at="2026-06-10", caller=caller)
    assert out["intervalIndex"] == 2  # advanced on strong gist
    assert out["nextDue"] == "2026-06-26"  # 2026-06-10 + 16 days
    assert len(out["performanceHistory"]) == 1
    assert out["retentionScore"] is None  # only 1 probe → n-gated
    assert out["lastProbeAt"] == "2026-06-10"


def test_first_probe():
    fp = rc.first_probe(from_date="2026-06-01")
    assert fp["intervalIndex"] == 0 and fp["nextDue"] == "2026-06-04" and fp["performanceHistory"] == []
