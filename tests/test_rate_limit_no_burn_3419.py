"""#3419 — a structurally rejected request must not burn the rate window.

THE DEFECT
----------
`check_rate_limit` charged with an unconditional DynamoDB `ADD`, then checked
`count <= limit`. A request whose cost could never fit (the 7-persona full-board
click: fan-out charge 1+6=7 against BOARD_RATE_LIMIT=5) was therefore rejected
AND still consumed the whole window — one doomed click locked the reader's
working 3-coach panel out for the rest of the hour. Live-verified 2026-09-01
(Session R probe, issue #3419).

THE FIX
-------
The charge is conditional: `ADD` only when prior count + cost <= limit
(ConditionExpression `attribute_not_exists(#c) OR #c <= :headroom`). A rejected
request consumes nothing; a cost that exceeds the LIMIT itself is rejected
before any write. Boundary semantics (the issue's acceptance):
  * cost == remaining        → allowed
  * cost == remaining + 1    → rejected, remaining NOT consumed
  * the exact 1+6>5 shape    → fan-out rejected, an immediately following
                               within-limit panel succeeds

Run:  python3 -m pytest tests/test_rate_limit_no_burn_3419.py -v
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from common import rate_limiter as rl  # noqa: E402


class _ConditionalCheckFailed(Exception):
    """botocore-shaped conditional failure — carries the .response dict
    `check_rate_limit` inspects, without importing botocore in the test."""

    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class _ConditionalFakeTable:
    """DDB stand-in that honors the conditional-ADD contract the fix relies on:
    when a ConditionExpression is present and the stored count exceeds
    :headroom, the write is refused (ConditionalCheckFailedException) and the
    counter is NOT incremented — exactly DynamoDB's behavior. Unlike
    test_rate_limiter._StatefulFakeTable (which increments unconditionally by
    1), this fake also applies the real `:inc` cost, so it exercises the
    fan-out arithmetic."""

    def __init__(self):
        self.counts: dict[tuple, int] = {}
        self.writes = 0  # every SUCCESSFUL (charging) update

    def update_item(self, Key, **kwargs):
        key = (Key["pk"], Key["sk"])
        vals = kwargs.get("ExpressionAttributeValues") or {}
        inc = int(vals.get(":inc", 1))
        cur = self.counts.get(key)
        if kwargs.get("ConditionExpression") is not None and cur is not None:
            headroom = int(vals[":headroom"])
            if cur > headroom:
                raise _ConditionalCheckFailed("The conditional request failed")
        self.counts[key] = (cur or 0) + inc
        self.writes += 1
        return {"Attributes": {"count": self.counts[key]}}

    def total(self) -> int:
        return sum(self.counts.values())


def test_cost_equal_to_remaining_passes():
    table = _ConditionalFakeTable()
    allowed, remaining, _ = rl.check_rate_limit(table, "board_ask", "ip", limit=5, cost=1)
    assert allowed and remaining == 4
    allowed, remaining, retry = rl.check_rate_limit(table, "board_ask", "ip", limit=5, cost=4)
    assert allowed is True, "cost == remaining must pass"
    assert remaining == 0
    assert retry == 0
    assert table.total() == 5


def test_cost_one_over_remaining_rejects_without_consuming():
    table = _ConditionalFakeTable()
    assert rl.check_rate_limit(table, "board_ask", "ip", limit=5, cost=1)[0]
    allowed, remaining, retry = rl.check_rate_limit(table, "board_ask", "ip", limit=5, cost=5)
    assert allowed is False, "cost == remaining + 1 must reject"
    assert 0 < retry <= 3600
    assert table.total() == 1, f"rejection must not consume the window (count went to {table.total()})"
    # the window is intact: the same cost-4 request that fit before still fits
    allowed, remaining, _ = rl.check_rate_limit(table, "board_ask", "ip", limit=5, cost=4)
    assert allowed is True and remaining == 0


def test_the_full_board_shape_1_plus_6_over_5():
    """The exact live shape from #3419: entry charge 1, fan-out charge 6 against
    limit 5 — the fan-out must reject WITHOUT locking out the reader, and the
    default 3-coach panel (1 + 2) must still succeed immediately after."""
    table = _ConditionalFakeTable()
    assert rl.check_rate_limit(table, "board_ask", "ip", limit=5, cost=1)[0]  # entry token
    allowed, _, _ = rl.check_rate_limit(table, "board_ask", "ip", limit=5, cost=6)
    assert allowed is False, "a 7-persona fan-out cannot fit a 5-token window"
    assert table.total() == 1, "the doomed fan-out must not burn the window"
    # the reader's next click: the default trio (entry 1 + fan-out 2)
    assert rl.check_rate_limit(table, "board_ask", "ip", limit=5, cost=1)[0]
    allowed, remaining, _ = rl.check_rate_limit(table, "board_ask", "ip", limit=5, cost=2)
    assert allowed is True, "the working panel must survive a prior doomed attempt"
    assert table.total() == 4


def test_cost_above_limit_never_writes_even_on_a_fresh_window():
    """cost > limit is structurally impossible in ANY window state — reject
    before any DDB write (a fresh window's attribute_not_exists would otherwise
    let the charge through and instantly exhaust it)."""
    table = _ConditionalFakeTable()
    allowed, _, retry = rl.check_rate_limit(table, "board_ask", "ip", limit=5, cost=7)
    assert allowed is False
    assert table.writes == 0, "a structurally impossible cost must not touch the table"
    # window untouched: a full-cost request still fits
    allowed, remaining, _ = rl.check_rate_limit(table, "board_ask", "ip", limit=5, cost=5)
    assert allowed is True and remaining == 0


def test_conditional_rejection_is_not_a_ddb_error():
    """A conditional-check failure is a VERDICT (over limit), never routed to
    the fail-open/fail-closed DDB-error path: fail_open=True must still reject."""
    table = _ConditionalFakeTable()
    assert rl.check_rate_limit(table, "board_ask", "ip", limit=5, cost=5)[0]
    allowed, _, retry = rl.check_rate_limit(table, "board_ask", "ip", limit=5, cost=1, fail_open=True)
    assert allowed is False, "fail_open must not turn an over-limit verdict into an allow"
    assert 0 < retry <= 3600
