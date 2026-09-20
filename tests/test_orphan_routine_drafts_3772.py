"""#3772 — orphaned routine drafts are listable and counted nightly."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

for _k, _v in (
    ("TABLE_NAME", "life-platform"),
    ("AWS_REGION", "us-west-2"),
    ("S3_BUCKET", "matthew-life-platform"),
    ("SITE_BASE_URL", "https://averagejoematt.com"),
    ("EMAIL_RECIPIENT", "qa@example.invalid"),
    ("EMAIL_SENDER", "qa@example.invalid"),
):
    os.environ.setdefault(_k, _v)


def _ir(rid, status, created, target):
    return SimpleNamespace(
        routine_id=rid,
        status=status,
        created_at=created,
        target_date=target,
        archetype="legs",
        variant=None,
        hevy_routine_id=None,
        version=1,
    )


def test_list_stale_drafts_returns_only_old_drafts_oldest_first(monkeypatch):
    from training import routine_repo as rr

    rows = [
        _ir("orphan-a", "draft", "2026-09-08T22:59:16+00:00", "2026-09-09"),  # the live specimen
        _ir("fresh", "draft", "2026-09-19T01:00:00+00:00", "2026-09-20"),
        _ir("done", "active", "2026-09-01T00:00:00+00:00", "2026-09-02"),
        _ir("orphan-b", "draft", "2026-09-01T00:00:00+00:00", "2026-09-02"),
    ]
    seen = {}
    monkeypatch.setattr(rr, "list_by_date_range", lambda s, e, limit=100: seen.update(start=s, end=e) or rows)
    out = rr.list_stale_drafts(older_than_days=7, today="2026-09-20")
    assert [r.routine_id for r in out] == ["orphan-b", "orphan-a"]
    assert seen["start"] == "2026-05-23" and seen["end"] == "2026-09-27", seen


def test_the_list_action_filters_by_status_and_age(monkeypatch):
    from mcp import tools_hevy_routine as t

    rows = [
        _ir("orphan-a", "draft", "2026-09-08T22:59:16+00:00", "2026-09-09"),
        _ir("fresh", "draft", "2026-09-19T01:00:00+00:00", "2026-09-20"),
        _ir("done", "active", "2026-09-01T00:00:00+00:00", "2026-09-02"),
    ]
    monkeypatch.setattr("training.routine_repo.list_by_date_range", lambda s, e, limit=100: rows)
    monkeypatch.setattr("common.pacific_time.pacific_today", lambda: "2026-09-20")
    out = t._action_list({"start_date": "2026-09-01", "end_date": "2026-09-20", "status": "draft", "older_than_days": 7})
    assert [r["routine_id"] for r in out["routines"]] == ["orphan-a"]
    assert out["filters"] == {"status": "draft", "older_than_days": 7}
    assert out["routines"][0]["created_at"].startswith("2026-09-08")
    unfiltered = t._action_list({"start_date": "2026-09-01", "end_date": "2026-09-20"})
    assert unfiltered["count"] == 3 and unfiltered["filters"] == {}


def test_the_nightly_warns_by_name_and_is_ok_at_zero(monkeypatch):
    from operational import qa_smoke_lambda as q
    from training import routine_repo as rr

    monkeypatch.setattr(
        rr, "list_stale_drafts", lambda older_than_days=7: [_ir("8a7a56c6457fdd24", "draft", "2026-09-08T22:59:16+00:00", "2026-09-09")]
    )
    (res,) = q.check_orphan_routine_drafts()
    assert res.passed is None and "8a7a56c6" in res.message and "#3772" in res.message, (res.passed, res.message)  # None = WARN (yellow)
    monkeypatch.setattr(rr, "list_stale_drafts", lambda older_than_days=7: [])
    (res,) = q.check_orphan_routine_drafts()
    assert res.passed is True, (res.passed, res.message)
    assert any(name == "orphan_routine_drafts" for name, _fn in q.check_steps()), "the leg must be registered in the nightly"
