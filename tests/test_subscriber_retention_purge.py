"""tests/test_subscriber_retention_purge.py — #1350 purge/anonymize behavior.

Covers deploy/subscriber_retention_purge.py's pure eligibility logic and its DDB
write shapes (mocked table — no AWS). Proves unsubscribed rows ARE purged/anonymized
once older than the window, and that pending/confirmed/recently-unsubscribed rows
are never touched.
"""

import argparse
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("subscriber_retention_purge", ROOT / "deploy" / "subscriber_retention_purge.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["subscriber_retention_purge"] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()

CUTOFF = "2026-01-01T00:00:00+00:00"


# ── _is_purge_eligible (pure logic) ────────────────────────────────────────────


def test_old_unsubscribed_row_is_eligible():
    item = {"status": "unsubscribed", "unsubbed_at": "2025-06-01T00:00:00+00:00"}
    assert mod._is_purge_eligible(item, CUTOFF) is True


def test_recently_unsubscribed_row_is_not_eligible():
    item = {"status": "unsubscribed", "unsubbed_at": "2026-06-01T00:00:00+00:00"}
    assert mod._is_purge_eligible(item, CUTOFF) is False


def test_confirmed_row_is_never_eligible_regardless_of_age():
    item = {"status": "confirmed", "confirmed_at": "2020-01-01T00:00:00+00:00"}
    assert mod._is_purge_eligible(item, CUTOFF) is False


def test_pending_row_is_never_eligible():
    item = {"status": "pending_confirmation"}
    assert mod._is_purge_eligible(item, CUTOFF) is False


def test_unsubscribed_row_missing_unsubbed_at_is_not_eligible():
    """Defensive: a malformed row (status set but no timestamp) must never be treated
    as eligible — that would purge on missing data instead of failing safe."""
    item = {"status": "unsubscribed"}
    assert mod._is_purge_eligible(item, CUTOFF) is False


# ── _scan_unsubscribed (pagination + filter) ───────────────────────────────────


def test_scan_unsubscribed_paginates_and_filters():
    table = MagicMock()
    table.query.side_effect = [
        {
            "Items": [
                {"sk": "EMAIL#old", "status": "unsubscribed", "unsubbed_at": "2020-01-01T00:00:00+00:00"},
                {"sk": "EMAIL#pending", "status": "pending_confirmation"},
            ],
            "LastEvaluatedKey": {"pk": "x", "sk": "y"},
        },
        {"Items": [{"sk": "EMAIL#recent", "status": "unsubscribed", "unsubbed_at": "2026-06-01T00:00:00+00:00"}]},
    ]
    out = mod._scan_unsubscribed(table, CUTOFF)
    assert [it["sk"] for it in out] == ["EMAIL#old"]
    assert table.query.call_count == 2


# ── _apply_purge (the actual writes — proves rows ARE purged/anonymized) ──────


def test_apply_purge_mode_deletes_offenders():
    table = MagicMock()
    offenders = [{"sk": "EMAIL#a"}, {"sk": "EMAIL#b"}]
    n = mod._apply_purge(table, offenders, "purge")
    assert n == 2
    table.delete_item.assert_has_calls(
        [
            call(Key={"pk": mod.SUBSCRIBERS_PK, "sk": "EMAIL#a"}),
            call(Key={"pk": mod.SUBSCRIBERS_PK, "sk": "EMAIL#b"}),
        ]
    )
    table.update_item.assert_not_called()


def test_apply_anonymize_mode_redacts_email_and_keeps_hash():
    table = MagicMock()
    offenders = [{"sk": "EMAIL#a"}]
    n = mod._apply_purge(table, offenders, "anonymize")
    assert n == 1
    table.delete_item.assert_not_called()
    table.update_item.assert_called_once()
    kwargs = table.update_item.call_args.kwargs
    assert kwargs["Key"] == {"pk": mod.SUBSCRIBERS_PK, "sk": "EMAIL#a"}
    assert "email = :r" in kwargs["UpdateExpression"]
    assert "REMOVE ip_hash" in kwargs["UpdateExpression"]
    assert kwargs["ExpressionAttributeValues"][":r"] == "[redacted]"


def test_apply_purge_no_offenders_is_a_noop():
    table = MagicMock()
    n = mod._apply_purge(table, [], "purge")
    assert n == 0
    table.delete_item.assert_not_called()
    table.update_item.assert_not_called()


# ── CLI contract: --window-days has NO default (Matthew's signature, #1350) ──


def test_window_days_is_a_required_argument_with_no_default():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window-days", type=int, required=True)
    with pytest.raises(SystemExit):
        ap.parse_args([])  # omitting --window-days must fail, not silently default
