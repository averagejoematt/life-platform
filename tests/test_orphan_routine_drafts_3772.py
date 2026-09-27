"""#3772 — orphaned routine drafts are listable and counted nightly; #4183 — a pre-genesis draft is history, not an orphan."""

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


def test_the_census_returns_only_old_drafts_oldest_first(monkeypatch):
    from training import routine_repo as rr

    rows = [
        _ir("orphan-a", "draft", "2026-09-08T22:59:16+00:00", "2026-09-09"),  # the live specimen
        _ir("fresh", "draft", "2026-09-19T01:00:00+00:00", "2026-09-20"),
        _ir("done", "active", "2026-09-01T00:00:00+00:00", "2026-09-02"),
        _ir("orphan-b", "draft", "2026-09-01T00:00:00+00:00", "2026-09-02"),
    ]
    seen = {}
    monkeypatch.setattr(rr, "list_by_date_range", lambda s, e, limit=100: seen.update(start=s, end=e) or rows)
    monkeypatch.setattr("common.constants.EXPERIMENT_START_DATE", "2026-09-06")
    out = rr.stale_draft_census(older_than_days=7, today="2026-09-20")
    # orphan-b targets 09-02 (before the 09-06 genesis) -> history; orphan-a targets 09-09 -> live; fresh/done never stale
    assert [r.routine_id for r in out["live"]] == ["orphan-a"] and [r.routine_id for r in out["pre_genesis"]] == ["orphan-b"]
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


# ── #4183: fixture = the wire. Four real VERSION#current rows read 2026-09-26 (read-only
# BatchGetItem over the routine_index window 2026-05-28..2026-10-03, 41 current-status drafts):
# the oldest pre-genesis orphan, the oldest live-cycle orphan, a fresh draft and a committed one.
WIRE_PRE_GENESIS = _ir("2af150189cdb413e97b3de585385abde", "draft", "2026-06-01T02:43:26+00:00", "2026-06-02")  # cron, aerobic
WIRE_LIVE_ORPHAN = _ir("96631989bf48c2526cf40cfe9c0bbada", "draft", "2026-09-11T02:56:20+00:00", "2026-09-11")  # cron, upper
WIRE_FRESH_DRAFT = _ir("ff7518cdab4a1197f8e03e17d6458370", "draft", "2026-09-27T02:00:38+00:00", "2026-09-27")  # tomorrow's pre-draft
WIRE_ACTIVE = _ir("8a7a56c6457fdd24", "active", "2026-09-08T22:59:16+00:00", "2026-09-09")  # #3772's specimen, since archived
GENESIS = "2026-09-06"
TODAY = "2026-09-26"  # PT day of the read; cutoff = 2026-09-19, so 09-11 is stale and 09-27 is not


def _wire(monkeypatch, rows):
    from training import routine_repo as rr

    seen = {}
    monkeypatch.setattr(rr, "list_by_date_range", lambda s, e, limit=100: seen.update(start=s, end=e) or list(rows))
    monkeypatch.setattr("common.pacific_time.pacific_today", lambda: TODAY)
    monkeypatch.setattr("common.constants.EXPERIMENT_START_DATE", GENESIS)
    return seen


def test_the_census_partitions_pre_genesis_history_from_live_orphans(monkeypatch):
    from training import routine_repo as rr

    seen = _wire(monkeypatch, [WIRE_FRESH_DRAFT, WIRE_LIVE_ORPHAN, WIRE_ACTIVE, WIRE_PRE_GENESIS])
    census = rr.stale_draft_census(older_than_days=7)
    assert [r.routine_id for r in census["live"]] == [WIRE_LIVE_ORPHAN.routine_id]
    assert [r.routine_id for r in census["pre_genesis"]] == [WIRE_PRE_GENESIS.routine_id]
    assert census["window"] == {"start": "2026-05-29", "end": "2026-10-03", "cutoff": "2026-09-19", "genesis": GENESIS, "today": TODAY}
    assert seen == {"start": "2026-05-29", "end": "2026-10-03"}, "the window the census NAMES must be the window it QUERIED"


def test_an_unresolved_genesis_widens_the_census_rather_than_narrowing_it(monkeypatch):
    """The conservative failure: with no genesis, NOTHING is history — every stale draft is live."""
    from training import routine_repo as rr

    _wire(monkeypatch, [WIRE_LIVE_ORPHAN, WIRE_PRE_GENESIS])
    monkeypatch.setattr(rr, "_live_genesis", lambda: None)
    census = rr.stale_draft_census(older_than_days=7)
    assert len(census["live"]) == 2 and census["pre_genesis"] == [] and census["window"]["genesis"] is None


def test_the_nightly_reports_only_live_orphans_and_names_its_window(monkeypatch):
    """Acceptance box 2 (#4183): a pre-genesis draft + a current-cycle draft -> exactly the
    current one is reported, and the detail names the census window and the excluded count.
    Mutation control (run by hand, recorded in the PR): with the genesis partition removed
    from `stale_draft_census`, this reports 2 and the assertions below fail."""
    from operational import qa_smoke_lambda as q

    _wire(monkeypatch, [WIRE_FRESH_DRAFT, WIRE_LIVE_ORPHAN, WIRE_ACTIVE, WIRE_PRE_GENESIS])
    (res,) = q.check_orphan_routine_drafts()
    assert res.passed is None, (res.passed, res.message)  # None = WARN (yellow): a live orphan still warns
    assert res.message.startswith("1 live-cycle routine draft(s)"), res.message
    assert "96631989" in res.message and "2af15018" not in res.message, res.message
    assert "census window 2026-05-29..2026-10-03" in res.message and f"genesis {GENESIS}" in res.message, res.message
    assert "1 pre-genesis draft(s) excluded as history" in res.message, res.message
    assert f"start_date={GENESIS}" in res.message, "the remediation hint must list only the live cycle"
    assert "#3772" in res.message and "#4183" in res.message


def test_the_nightly_is_ok_when_every_stale_draft_is_pre_genesis(monkeypatch):
    """The 2026-09-25 wire shape, minus the six live orphans: eighteen June drafts -> OK,
    the window and the excluded count still named on the green line."""
    from operational import qa_smoke_lambda as q

    _wire(monkeypatch, [WIRE_PRE_GENESIS, WIRE_FRESH_DRAFT, WIRE_ACTIVE])
    (res,) = q.check_orphan_routine_drafts()
    assert res.passed is True, (res.passed, res.message)
    assert "1 pre-genesis draft(s) excluded as history" in res.message and f"genesis {GENESIS}" in res.message, res.message
    assert any(name == "orphan_routine_drafts" for name, _fn in q.check_steps()), "the leg must be registered in the nightly"


def test_the_nightly_is_ok_at_zero_and_warns_on_a_census_error(monkeypatch):
    from operational import qa_smoke_lambda as q
    from training import routine_repo as rr

    _wire(monkeypatch, [])
    (res,) = q.check_orphan_routine_drafts()
    assert res.passed is True and "0 pre-genesis" in res.message, (res.passed, res.message)

    def boom(*a, **k):
        raise RuntimeError("index unreadable")

    monkeypatch.setattr(rr, "list_by_date_range", boom)
    (res,) = q.check_orphan_routine_drafts()
    assert res.passed is None and "no verdict was reached" in res.message, (res.passed, res.message)
