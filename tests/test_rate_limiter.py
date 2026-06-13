"""
tests/test_rate_limiter.py — Phase 2.1 DDB-backed rate limiter.

Covers:
  - bucket math truncates correctly
  - first request below limit → allowed
  - request after limit reached → blocked + retry_after positive
  - DDB error → fails open (allowed, full remaining, 0 retry)
  - PK/SK shape matches the leading-key allowlist in role_policies.site_api_ai

Run:  python3 -m pytest tests/test_rate_limiter.py -v
"""

import os
import sys
from unittest.mock import MagicMock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

import rate_limiter as rl  # noqa: E402


def _fake_table_with_count(count_returned):
    table = MagicMock()
    table.update_item.return_value = {"Attributes": {"count": count_returned}}
    return table


def test_bucket_truncates_to_window():
    now = 1_700_000_000  # arbitrary epoch
    assert rl._bucket_for_window(now, 3600) == (now // 3600) * 3600
    assert rl._bucket_for_window(now, 60) == (now // 60) * 60


def test_first_request_allowed():
    table = _fake_table_with_count(1)
    allowed, remaining, retry = rl.check_rate_limit(table, "ask", "abc123", limit=5, window_seconds=3600)
    assert allowed is True
    assert remaining == 4
    assert retry == 0


def test_at_limit_blocks_and_returns_retry():
    table = _fake_table_with_count(6)  # limit exceeded
    allowed, remaining, retry = rl.check_rate_limit(table, "ask", "abc123", limit=5, window_seconds=3600)
    assert allowed is False
    assert remaining == 0
    assert retry > 0
    assert retry <= 3600


def test_ddb_error_fails_open():
    table = MagicMock()
    table.update_item.side_effect = Exception("Throttle")
    allowed, remaining, retry = rl.check_rate_limit(table, "ask", "abc123", limit=5)
    assert allowed is True
    assert remaining == 5
    assert retry == 0


def test_ddb_error_fails_closed_when_requested():
    """AI endpoints pass fail_open=False so a DDB blip can't unmeter Bedrock spend."""
    table = MagicMock()
    table.update_item.side_effect = Exception("Throttle")
    allowed, remaining, retry = rl.check_rate_limit(table, "board_ask", "abc123", limit=5, fail_open=False)
    assert allowed is False
    assert remaining == 0
    assert 0 < retry <= 3600  # short retry — DDB blips are transient, not an hour-long block


def test_pk_starts_with_rate_prefix_for_iam_allowlist():
    """IAM scopes UpdateItem to dynamodb:LeadingKeys starting with RATE# — verify."""
    table = _fake_table_with_count(1)
    rl.check_rate_limit(table, "board_ask", "deadbeef", limit=5)
    call_kwargs = table.update_item.call_args.kwargs
    pk = call_kwargs["Key"]["pk"]
    sk = call_kwargs["Key"]["sk"]
    assert pk.startswith("RATE#"), f"PK {pk!r} must start with RATE# for IAM allowlist"
    assert pk == "RATE#board_ask#deadbeef"
    assert sk.startswith("HOUR#")


def test_ttl_set_only_on_first_write():
    """if_not_exists prevents resetting TTL on every increment."""
    table = _fake_table_with_count(2)
    rl.check_rate_limit(table, "ask", "h1", limit=5)
    expr = table.update_item.call_args.kwargs["UpdateExpression"]
    assert "if_not_exists" in expr
    assert "ADD" in expr
