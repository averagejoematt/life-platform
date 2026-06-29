"""SS-01 — the chronicle auto-publish sweep: a daily fail-safe so a draft never stays
dark if the approve link isn't clicked. Tests stale-draft detection + that the sweep
reuses the approve publish path (and respects dry-run)."""

import importlib.util
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


def test_find_stale_drafts_filters_by_status_and_age(mod):
    items = [
        {"sk": "DATE#2026-06-10", "date": "2026-06-10", "status": "draft", "generated_at": _iso(72), "week_number": 1},  # stale draft ✓
        {"sk": "DATE#2026-06-17", "date": "2026-06-17", "status": "draft", "generated_at": _iso(3), "week_number": 2},  # fresh draft ✗
        {"sk": "DATE#2026-06-03", "date": "2026-06-03", "status": "published", "generated_at": _iso(200), "week_number": 0},  # published ✗
    ]
    with mock.patch.object(mod.table, "query", return_value={"Items": items}):
        stale = mod._find_stale_drafts(48)
    assert [s["date"] for s in stale] == ["2026-06-10"]


def test_missing_timestamp_is_treated_stale(mod):
    items = [{"sk": "DATE#2026-06-10", "date": "2026-06-10", "status": "draft", "week_number": 1}]  # no generated_at
    with mock.patch.object(mod.table, "query", return_value={"Items": items}):
        stale = mod._find_stale_drafts(48)
    assert len(stale) == 1


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
