"""
tests/test_rate_limiter.py — Phase 2.1 DDB-backed rate limiter.

Covers:
  - bucket math truncates correctly
  - first request below limit → allowed
  - request after limit reached → blocked + retry_after positive
  - DDB error → fails open (allowed, full remaining, 0 retry)
  - PK/SK shape matches the leading-key allowlist in role_policies.site_api_ai
  - #1439: the real 429 threshold path across a sequence of stateful calls
    (not just a single call with a pre-set count), for a real configured
    production limit (board_ask, BOARD_RATE_LIMIT=5/hr)
  - #1439: TTL/window reset — a request in the NEXT window bucket is allowed
    again even though the previous window was exhausted
  - #1439: the fail-open fallback is re-verified against the code's ACTUAL
    designed behavior (see note below) rather than an assumed one

Run:  python3 -m pytest tests/test_rate_limiter.py -v
"""

import os
import sys
from unittest.mock import MagicMock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

import rate_limiter as rl  # noqa: E402
from web.site_api_ai_lambda import BOARD_RATE_LIMIT  # noqa: E402 — a REAL configured production limit (5/hr)


def _fake_table_with_count(count_returned):
    table = MagicMock()
    table.update_item.return_value = {"Attributes": {"count": count_returned}}
    return table


class _StatefulFakeTable:
    """A minimal in-process stand-in for the DDB `ADD` atomic-counter behavior
    that `check_rate_limit` relies on: each call to `update_item` on the same
    (pk, sk) increments a real counter and returns the new total, exactly like
    DynamoDB's `UpdateExpression="ADD #c :inc ..."` does. Unlike
    `_fake_table_with_count` (which pins a single pre-set count per call), this
    lets a test drive a real SEQUENCE of requests and observe the counter
    actually cross the limit — the #1439 gap: existing tests asserted the
    boundary math for one fixed count, not behavior across N calls.
    """

    def __init__(self):
        self._counts: dict[tuple, int] = {}

    def update_item(self, Key, **_kwargs):
        key = (Key["pk"], Key["sk"])
        self._counts[key] = self._counts.get(key, 0) + 1
        return {"Attributes": {"count": self._counts[key]}}


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


# ── #1439: the real 429 threshold path across a sequence of calls ──────────


def test_nplus1_request_denied_after_n_allowed_at_real_board_ask_limit():
    """Drive BOARD_RATE_LIMIT (the real, live board_ask config — 5/hr) through a
    stateful fake counter: the first N=5 requests in the same window must all
    be allowed, and the (N+1)th must be denied with a positive retry_after.
    This is the genuine 429-threshold behavior a single fixed-count mock can't
    exercise — it proves the atomic-counter accumulation itself, not just the
    `count <= limit` comparison in isolation."""
    table = _StatefulFakeTable()
    results = [
        rl.check_rate_limit(table, "board_ask", "same-ip", limit=BOARD_RATE_LIMIT, window_seconds=3600) for _ in range(BOARD_RATE_LIMIT)
    ]
    assert all(
        allowed for allowed, _remaining, _retry in results
    ), f"all {BOARD_RATE_LIMIT} in-window requests should be allowed: {results}"
    # remaining counts down to zero across the allowed sequence.
    assert [remaining for _allowed, remaining, _retry in results] == list(range(BOARD_RATE_LIMIT - 1, -1, -1))

    allowed_nplus1, remaining_nplus1, retry_nplus1 = rl.check_rate_limit(
        table, "board_ask", "same-ip", limit=BOARD_RATE_LIMIT, window_seconds=3600
    )
    assert allowed_nplus1 is False
    assert remaining_nplus1 == 0
    assert 0 < retry_nplus1 <= 3600


def test_different_ip_hash_gets_its_own_counter():
    """The atomic counter is keyed per (endpoint, ip_hash) — a different caller
    within the same window must not inherit another IP's exhausted count."""
    table = _StatefulFakeTable()
    for _ in range(BOARD_RATE_LIMIT):
        allowed, _remaining, _retry = rl.check_rate_limit(table, "board_ask", "ip-a", limit=BOARD_RATE_LIMIT, window_seconds=3600)
        assert allowed is True
    # ip-a is now exhausted...
    allowed_a, _, _ = rl.check_rate_limit(table, "board_ask", "ip-a", limit=BOARD_RATE_LIMIT, window_seconds=3600)
    assert allowed_a is False
    # ...but ip-b, first request of the window, is fine.
    allowed_b, remaining_b, retry_b = rl.check_rate_limit(table, "board_ask", "ip-b", limit=BOARD_RATE_LIMIT, window_seconds=3600)
    assert allowed_b is True
    assert remaining_b == BOARD_RATE_LIMIT - 1
    assert retry_b == 0


# ── #1439: TTL / window reset ───────────────────────────────────────────────


def test_request_allowed_again_in_next_window_bucket(monkeypatch):
    """A caller who exhausts the limit in one window bucket must be allowed
    again once the window rolls over — the DDB `sk = HOUR#{bucket_start}`
    scheme means the NEXT bucket is a fresh, unrelated counter (this is what
    the DDB TTL eventually reaps; here we simulate the rollover directly by
    advancing the clock, since the "reset" is really just addressing a new
    key, not an explicit clear)."""
    window = 3600
    limit = BOARD_RATE_LIMIT
    table = _StatefulFakeTable()

    now_holder = {"t": 1_700_000_000}  # arbitrary epoch, window-aligned start
    monkeypatch.setattr(rl.time, "time", lambda: now_holder["t"])

    # Exhaust the window.
    for _ in range(limit):
        allowed, _remaining, _retry = rl.check_rate_limit(table, "board_ask", "roller", limit=limit, window_seconds=window)
        assert allowed is True
    denied, remaining_denied, retry_denied = rl.check_rate_limit(table, "board_ask", "roller", limit=limit, window_seconds=window)
    assert denied is False
    assert remaining_denied == 0
    assert retry_denied > 0

    # Advance the clock past the window boundary — a brand-new bucket key.
    now_holder["t"] += window
    allowed_next_window, remaining_next_window, retry_next_window = rl.check_rate_limit(
        table, "board_ask", "roller", limit=limit, window_seconds=window
    )
    assert allowed_next_window is True, "a request in a fresh window bucket must be allowed even though the prior window was exhausted"
    assert remaining_next_window == limit - 1
    assert retry_next_window == 0


def test_bucket_key_changes_across_window_boundary(monkeypatch):
    """Directly verify the sk (HOUR#{bucket_start}) actually changes once the
    clock crosses a window boundary — the mechanism the reset above relies on."""
    table = _StatefulFakeTable()
    now_holder = {"t": 1_700_000_000}
    monkeypatch.setattr(rl.time, "time", lambda: now_holder["t"])

    rl.check_rate_limit(table, "ask", "clock-ip", limit=5, window_seconds=3600)
    first_sk = next(iter(table._counts.keys()))[1]

    now_holder["t"] += 3600
    rl.check_rate_limit(table, "ask", "clock-ip", limit=5, window_seconds=3600)
    second_sks = [sk for (_pk, sk) in table._counts.keys()]
    assert first_sk in second_sks
    assert len(second_sks) == 2, f"expected a second, distinct bucket key after the window rolled over: {second_sks}"


# ── #1439: fail-open fallback — verified against the code's ACTUAL behavior ─
#
# The issue's framing assumed the fail-open fallback works by "falling back
# to an in-memory path". Reading rate_limiter.py shows that is NOT what this
# module does: `check_rate_limit`'s fail-open path does not consult or
# maintain any in-memory counter at all — on a DDB exception with
# `fail_open=True` it unconditionally returns `(True, limit, 0)` (i.e. "treat
# this request as if it were the very first request of a fresh window"),
# with no counting of any kind. The DISTINCT in-memory dict fallback readers
# may be thinking of (`_ask_rate_store` / `_board_rate_store` in
# `web/site_api_ai_lambda.py`) lives one layer up, in the caller, and only
# triggers on a module ImportError (i.e. `rate_limiter` itself failed to
# load) — never on a DDB call failing. That caller-level fallback is already
# covered by tests/test_nudge_finding_rate_limit.py::
# test_nudge_in_memory_fallback_still_limits for site_api_social's nudge
# endpoint. The two tests below re-confirm rate_limiter.py's own (simpler,
# no-memory) fail-open/fail-closed contract, including that it holds even
# mid-sequence (not just as an isolated single call).


def test_fail_open_allows_unconditionally_with_no_counting_state():
    """Confirms fail-open does NOT fall back to counting via any local store —
    it just always allows, every single time, regardless of how many prior
    calls already "failed open" in the same window."""
    table = MagicMock()
    table.update_item.side_effect = Exception("ProvisionedThroughputExceededException")
    for _ in range(10):  # far more than any real limit — every one must pass
        allowed, remaining, retry = rl.check_rate_limit(table, "board_ask", "flaky-ddb", limit=BOARD_RATE_LIMIT, fail_open=True)
        assert allowed is True
        assert remaining == BOARD_RATE_LIMIT
        assert retry == 0


def test_fail_closed_denies_unconditionally_when_requested():
    """The mirror image: cost-bearing endpoints (ask/board_ask) call with
    fail_open=False, so a DDB outage fails CLOSED (short retry — DDB blips
    are transient) rather than silently unmetering Bedrock spend."""
    table = MagicMock()
    table.update_item.side_effect = Exception("ProvisionedThroughputExceededException")
    for _ in range(5):
        allowed, remaining, retry = rl.check_rate_limit(table, "board_ask", "flaky-ddb-2", limit=BOARD_RATE_LIMIT, fail_open=False)
        assert allowed is False
        assert remaining == 0
        assert retry == 60
