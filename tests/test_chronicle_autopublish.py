"""SS-01 — the chronicle auto-publish sweep: a daily fail-safe so a draft never stays
dark if the approve link isn't clicked. Tests stale-draft detection + that the sweep
reuses the approve publish path (and respects dry-run)."""

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

_MOD_PATH = Path(__file__).resolve().parents[1] / "lambdas" / "emails" / "chronicle_approve_lambda.py"


@pytest.fixture
def mod(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "matthew-life-platform")
    monkeypatch.setenv("CHRONICLE_AUTOPUBLISH_HOURS", "48")
    spec = importlib.util.spec_from_file_location("chronicle_approve_lambda", _MOD_PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _iso(hours_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def test_find_stale_drafts_window(mod):
    items = [
        {"sk": "DATE#a", "date": "a", "status": "draft", "generated_at": _iso(72), "week_number": 1},  # in window ✓ (3d old)
        {"sk": "DATE#b", "date": "b", "status": "draft", "generated_at": _iso(3), "week_number": 2},  # too fresh ✗ (<48h)
        {"sk": "DATE#c", "date": "c", "status": "draft", "generated_at": _iso(24 * 20), "week_number": 3},  # too old ✗ (>10d)
        {"sk": "DATE#d", "date": "d", "status": "published", "generated_at": _iso(72), "week_number": 0},  # published ✗
    ]
    with mock.patch.object(mod.table, "query", return_value={"Items": items}):
        stale = mod._find_stale_drafts(48, 10)
    assert [s["date"] for s in stale] == ["a"]


def test_missing_or_old_timestamp_is_skipped(mod):
    items = [
        {"sk": "DATE#x", "date": "x", "status": "draft", "week_number": 1},  # no generated_at → skip
        {"sk": "DATE#y", "date": "y", "status": "draft", "generated_at": _iso(24 * 30), "week_number": 2},  # 30d old → skip
    ]
    with mock.patch.object(mod.table, "query", return_value={"Items": items}):
        stale = mod._find_stale_drafts(48, 10)
    assert stale == []


def test_sweep_publishes_via_approve_path(mod):
    draft = {"sk": "DATE#2026-06-10", "date": "2026-06-10", "status": "draft", "generated_at": _iso(72), "week_number": 1}
    with (
        mock.patch.object(mod, "_find_stale_drafts", return_value=[draft]),
        mock.patch.object(mod, "_publish_to_s3", return_value=["/journal/posts.json"]) as pub,
        mock.patch.object(mod, "_invalidate_cloudfront") as inval,
        mock.patch.object(mod, "_mark_published") as markp,
        mock.patch.object(mod, "_invoke_email_sender") as sender,
    ):
        out = mod._sweep_stale_drafts(48)
    pub.assert_called_once_with(draft)
    inval.assert_called_once()
    markp.assert_called_once_with("2026-06-10")
    sender.assert_called_once()  # one delivery trigger for the batch
    assert out == [{"date": "2026-06-10", "week": 1}]


def test_sweep_dry_run_publishes_nothing(mod):
    draft = {"sk": "DATE#2026-06-10", "date": "2026-06-10", "status": "draft", "generated_at": _iso(72), "week_number": 1}
    with (
        mock.patch.object(mod, "_find_stale_drafts", return_value=[draft]),
        mock.patch.object(mod, "_publish_to_s3") as pub,
        mock.patch.object(mod, "_mark_published") as markp,
        mock.patch.object(mod, "_invoke_email_sender") as sender,
    ):
        out = mod._sweep_stale_drafts(48, dry_run=True)
    pub.assert_not_called()
    markp.assert_not_called()
    sender.assert_not_called()
    assert out == [{"date": "2026-06-10", "week": 1, "dry_run": True}]


def test_handler_routes_scheduled_event_to_sweep(mod):
    with mock.patch.object(mod, "_sweep_stale_drafts", return_value=[]) as sweep:
        resp = mod.lambda_handler({"source": "aws.events", "detail-type": "Scheduled Event"}, None)
    sweep.assert_called_once()
    assert resp["statusCode"] == 200 and "swept" in resp


# ── #3485: the sweep, the publish path and the recap honour the wipe's tombstone ──


def _archived(sk, hours_ago, **extra):
    """A cycle-15 draft exactly as the 2026-09-03 reset left it: status still draft,
    but tombstoned + re-phased. The 2026-09-04 18:00Z sweep published this row."""
    row = {"sk": sk, "date": sk.replace("DATE#", ""), "status": "draft", "generated_at": _iso(hours_ago), "week_number": 1}
    row.update({"tombstone": True, "tombstoned_at": "2026-09-04T03:42:05+00:00", "phase": "pilot", "cycle": 15})
    row.update(extra)
    return row


def test_sweep_skips_a_tombstoned_draft_inside_the_window(mod):
    """The 2026-09-04 specimen: in-window by age, draft by status, ARCHIVED by the reset."""
    items = [_archived("DATE#2026-09-01", 72)]
    with mock.patch.object(mod.table, "query", return_value={"Items": items}):
        assert mod._find_stale_drafts(48, 10) == []


def test_sweep_still_selects_the_same_draft_when_it_is_not_archived(mod):
    """Negative control on the guard itself: strip the archive marks and the row is the
    ordinary 'forgot to click' case the sweep exists for."""
    row = _archived("DATE#2026-09-01", 72)
    for k in ("tombstone", "tombstoned_at", "phase", "cycle"):
        row.pop(k)
    with mock.patch.object(mod.table, "query", return_value={"Items": [row]}):
        assert [s["date"] for s in mod._find_stale_drafts(48, 10)] == ["2026-09-01"]


def test_a_non_current_phase_alone_is_enough_to_skip(mod):
    """phase=pilot with no tombstone attribute is still archived (singleton_visible's
    reader semantics, #946) — the writer must agree with the reader."""
    row = _archived("DATE#2026-09-01", 72)
    row.pop("tombstone")
    row.pop("tombstoned_at")
    with mock.patch.object(mod.table, "query", return_value={"Items": [row]}):
        assert mod._find_stale_drafts(48, 10) == []


def test_publish_to_s3_refuses_an_archived_row_on_any_path(mod):
    """Defence in depth: the approve-link path shares _publish_to_s3, so a human click on
    a stale approval email cannot resurrect an archived draft either."""
    row = _archived("DATE#2026-09-01", 72, draft_journal_posts_json="{}")
    with mock.patch.object(mod.s3, "put_object") as put, pytest.raises(ValueError, match="3485"):
        mod._publish_to_s3(row)
    put.assert_not_called()


def test_publish_to_s3_writes_a_current_row(mod):
    row = {"sk": "DATE#2026-09-12", "date": "2026-09-12", "status": "draft", "draft_journal_posts_json": "{}"}
    with mock.patch.object(mod.s3, "put_object") as put:
        paths = mod._publish_to_s3(row)
    assert paths == ["/journal/posts.json"]
    put.assert_called_once()


def test_sweep_reports_the_refusal_and_publishes_nothing_else_for_that_row(mod):
    """The sweep's own try/except turns the refusal into a logged skip, never a crash —
    and none of the downstream writers (recap, mark-published, Elena) fire for it."""
    row = _archived("DATE#2026-09-01", 72, draft_journal_posts_json="{}")
    with (
        mock.patch.object(mod, "_find_stale_drafts", return_value=[row]),
        mock.patch.object(mod.s3, "put_object"),
        mock.patch.object(mod, "_commit_recap") as recap,
        mock.patch.object(mod, "_mark_published") as markp,
        mock.patch.object(mod, "_invoke_elena_state_updater") as elena,
        mock.patch.object(mod, "_invoke_email_sender") as sender,
    ):
        out = mod._sweep_stale_drafts(48)
    assert out == []
    recap.assert_not_called()
    markp.assert_not_called()
    elena.assert_not_called()
    sender.assert_not_called()


def test_commit_recap_carries_the_provenance_stamp(mod):
    """ADR-077: RECAP#latest is EXPERIMENT_SCOPED — it must carry phase (+ cycle when SSM
    answers) at write time, so /api/recap's phase guard can see a stale recap by itself."""
    item = {
        "sk": "DATE#2026-09-12",
        "date": "2026-09-12",
        "phase": "experiment",
        "cycle": 16,
        "draft_recap_json": json.dumps({"story_so_far": "x"}),
    }
    writes = []
    with mock.patch.object(mod.table, "put_item", side_effect=lambda Item: writes.append(Item)):
        mod._commit_recap(item)
    assert {w["sk"] for w in writes} == {"RECAP#2026-09-12", "RECAP#latest"}
    for w in writes:
        assert w["phase"] == "experiment" and w["cycle"] == 16


def test_commit_recap_defaults_the_phase_when_the_installment_carries_none(mod):
    """An un-stamped installment still yields a phase-bearing recap (current phase),
    never a phase-less record the reader guard cannot classify (the 09-04 shape)."""
    item = {"sk": "DATE#2026-09-12", "date": "2026-09-12", "draft_recap_json": json.dumps({"story_so_far": "x"})}
    writes = []
    with mock.patch.object(mod.table, "put_item", side_effect=lambda Item: writes.append(Item)):
        mod._commit_recap(item)
    assert all(w["phase"] == mod.EXPERIMENT_PHASE_CURRENT for w in writes)
    assert all("cycle" not in w for w in writes)
