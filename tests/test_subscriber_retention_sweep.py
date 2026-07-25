"""tests/test_subscriber_retention_sweep.py — #1350 signed retention-window guard.

The [gate:owner] decision is 18 months, anonymize (docs/DATA_GOVERNANCE.md). This
guard asserts:
  1. the signed window constant IS 18 months (548 days), mode anonymize, in the ONE
     source of truth (lambdas/subscriber_retention.py);
  2. the governance doc's signed row names that same day-count (doc ↔ constant, no drift);
  3. the pure eligibility/redaction logic anonymizes every eligible row and preserves
     the rest (count + confirmation state survive) — no eligible row survives
     un-anonymized;
  4. the scheduled sweep handler (delete_user_data_lambda's subscriber_retention_sweep
     event) is dry-run by default, anonymizes only eligible rows on apply, is
     idempotent, and never touches active subscribers or the subscriber count.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

import subscriber_retention as sr  # noqa: E402

DOC = ROOT / "docs" / "DATA_GOVERNANCE.md"


# ── 1. The signed window constant IS 18 months ──────────────────────────────────


def test_window_constant_is_18_months():
    assert sr.RETENTION_WINDOW_MONTHS == 18
    assert sr.RETENTION_WINDOW_DAYS == 548  # 18 × 30.4375 ≈ 548
    assert sr.RETENTION_MODE == "anonymize"


# ── 2. Doc ↔ constant: the signed row names the same day-count ──────────────────


def test_governance_doc_names_the_signed_day_count():
    text = DOC.read_text(encoding="utf-8")
    row = [ln for ln in text.splitlines() if "Subscriber emails" in ln and "|" in ln]
    assert row, "no 'Subscriber emails' retention row found in DATA_GOVERNANCE.md"
    line = row[0]
    assert "UNSIGNED" not in line, "row is still UNSIGNED — the owner decision must be signed in"
    assert f"{sr.RETENTION_WINDOW_DAYS} days" in line, f"signed row must name the {sr.RETENTION_WINDOW_DAYS}-day window"
    assert "18 month" in line and "anonymize" in line.lower()


# ── 3. Pure logic: eligible rows anonymized, the rest preserved ─────────────────

CUTOFF = "2026-01-01T00:00:00+00:00"


def test_old_unsubscribed_row_is_eligible():
    assert sr.is_retention_eligible({"status": "unsubscribed", "unsubbed_at": "2024-01-01T00:00:00+00:00"}, CUTOFF)


def test_recent_unsubscribed_row_is_not_eligible():
    assert not sr.is_retention_eligible({"status": "unsubscribed", "unsubbed_at": "2026-06-01T00:00:00+00:00"}, CUTOFF)


def test_confirmed_active_row_is_never_eligible():
    # An active subscriber who confirmed long ago is retained — deliverability basis.
    assert not sr.is_retention_eligible({"status": "confirmed", "confirmed_at": "2019-01-01T00:00:00+00:00"}, CUTOFF)


def test_pending_row_is_never_eligible():
    assert not sr.is_retention_eligible({"status": "pending_confirmation"}, CUTOFF)


def test_unsubscribed_missing_timestamp_fails_safe():
    assert not sr.is_retention_eligible({"status": "unsubscribed"}, CUTOFF)


def test_anonymized_item_scrubs_pii_keeps_aggregate_fields():
    item = {
        "pk": "USER#matthew#SOURCE#subscribers",
        "sk": "EMAIL#abc123",
        "email": "person@example.com",
        "email_hash": "abc123",
        "status": "unsubscribed",
        "created_at": "2023-01-01T00:00:00+00:00",
        "unsubbed_at": "2023-06-01T00:00:00+00:00",
        "ip_hash": "deadbeef",
    }
    out = sr.anonymized_item(item, now_iso="2026-07-25T00:00:00+00:00")
    assert out["email"] == "[redacted]"
    assert "ip_hash" not in out
    assert out["anonymized_at"] == "2026-07-25T00:00:00+00:00"
    # Aggregate/count fields preserved:
    assert out["sk"] == "EMAIL#abc123"
    assert out["status"] == "unsubscribed"
    assert out["email_hash"] == "abc123"
    assert out["unsubbed_at"] == "2023-06-01T00:00:00+00:00"


def test_needs_anonymization_is_idempotent():
    old = {"status": "unsubscribed", "unsubbed_at": "2023-01-01T00:00:00+00:00"}
    assert sr.needs_anonymization(old, CUTOFF)
    # Once anonymized, no longer a target — a second sweep is a no-op.
    assert not sr.needs_anonymization(sr.anonymized_item(old), CUTOFF)


def test_cutoff_is_the_signed_window_before_now():
    now = datetime(2026, 7, 25, tzinfo=timezone.utc)
    expected = (now - timedelta(days=sr.RETENTION_WINDOW_DAYS)).isoformat()
    assert sr.retention_cutoff_iso(now) == expected


# ── 4. The scheduled sweep handler (delete_user_data_lambda) ────────────────────


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setenv("TABLE_NAME", "test-table")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("USER_ID", "matthew")


def _import(env):
    sys.modules.pop("delete_user_data_lambda", None)
    with patch("boto3.resource") as mr, patch("boto3.client") as mc:
        mr.return_value = MagicMock()
        mc.return_value = MagicMock()
        import delete_user_data_lambda as m
    return m


def _fixture_rows():
    """A mix that exercises every branch: one long-ago unsubscribed (eligible), one
    recently unsubscribed (too new), one active confirmed (never), one already
    anonymized (idempotent)."""
    old_iso = (datetime.now(timezone.utc) - timedelta(days=800)).isoformat()
    recent_iso = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    return [
        {"sk": "EMAIL#old", "status": "unsubscribed", "unsubbed_at": old_iso, "email": "old@example.com", "ip_hash": "x"},
        {"sk": "EMAIL#recent", "status": "unsubscribed", "unsubbed_at": recent_iso, "email": "recent@example.com"},
        {"sk": "EMAIL#active", "status": "confirmed", "confirmed_at": old_iso, "email": "active@example.com"},
        {"sk": "EMAIL#done", "status": "unsubscribed", "unsubbed_at": old_iso, "email": "[redacted]", "anonymized_at": old_iso},
    ]


def test_sweep_dry_run_changes_nothing(env):
    m = _import(env)
    with patch.object(m, "_scan_subscribers", return_value=_fixture_rows()):
        resp = m.lambda_handler({"subscriber_retention_sweep": True}, None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["plan"]["apply"] is False
    assert body["plan"]["eligible"] == 1  # only EMAIL#old
    assert body["plan"]["window_days"] == sr.RETENTION_WINDOW_DAYS
    m.table.put_item.assert_not_called()
    m.table.delete_item.assert_not_called()


def test_sweep_apply_anonymizes_only_eligible_and_preserves_count(env):
    m = _import(env)
    with patch.object(m, "_scan_subscribers", return_value=_fixture_rows()):
        with patch.object(m, "_write_audit_record") as audit:
            resp = m.lambda_handler({"subscriber_retention_sweep": True, "apply": True}, None)
    body = json.loads(resp["body"])
    assert body["acted"] == 1
    # Exactly one PutItem — the eligible row, rebuilt with email redacted. No row deleted
    # (anonymize mode) → the subscriber COUNT is unchanged.
    m.table.delete_item.assert_not_called()
    m.table.put_item.assert_called_once()
    put = m.table.put_item.call_args.kwargs["Item"]
    assert put["sk"] == "EMAIL#old"
    assert put["email"] == "[redacted]"
    assert "ip_hash" not in put
    assert put["status"] == "unsubscribed"  # confirmation/status preserved
    assert audit.call_args.args[0] == "subscriber_retention_sweep"


def test_sweep_is_idempotent_second_run_noop(env):
    m = _import(env)
    # After a sweep, every eligible row is already anonymized → nothing to do.
    already_done = [
        {
            "sk": "EMAIL#old",
            "status": "unsubscribed",
            "unsubbed_at": "2020-01-01T00:00:00+00:00",
            "email": "[redacted]",
            "anonymized_at": "2026-01-01T00:00:00+00:00",
        },
    ]
    with patch.object(m, "_scan_subscribers", return_value=already_done):
        with patch.object(m, "_write_audit_record"):
            resp = m.lambda_handler({"subscriber_retention_sweep": True, "apply": True}, None)
    assert json.loads(resp["body"])["acted"] == 0
    m.table.put_item.assert_not_called()
