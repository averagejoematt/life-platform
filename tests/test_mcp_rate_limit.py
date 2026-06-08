"""tests/test_mcp_rate_limit.py — rolling-window write-tool rate limit.

Regression guard for the per-container lifetime-counter bug: the limit must
trip on a runaway loop but self-heal as the window slides (no cold start /
new conversation), and must never penalize a human-paced multi-step flow.
"""

from __future__ import annotations

import os
from unittest.mock import patch

# mcp.config reads these at import; mcp.handler pulls the full registry.
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from mcp import handler as h  # noqa: E402


def setup_function(_fn):
    h._WRITE_TOOL_CALLS.clear()


def test_under_limit_allows():
    name = "manage_hevy_routine"
    with patch("mcp.handler.time.time", return_value=1000.0):
        for _ in range(h._WRITE_TOOL_RATE_LIMIT - 1):
            assert h._check_write_rate_limit(name) is None


def test_over_limit_blocks_then_window_slides():
    name = "manage_hevy_routine"
    t0 = 1000.0
    with patch("mcp.handler.time.time", return_value=t0):
        for _ in range(h._WRITE_TOOL_RATE_LIMIT):
            assert h._check_write_rate_limit(name) is None
        err = h._check_write_rate_limit(name)  # one over → blocked
        assert err and "exceeded" in err
    # advance past the window → allowed again WITHOUT a cold start (the fix)
    with patch("mcp.handler.time.time", return_value=t0 + h._WRITE_TOOL_RATE_WINDOW_SECS + 1):
        assert h._check_write_rate_limit(name) is None


def test_legit_multistep_flow_not_blocked():
    """draft → dry_run → commit + a few retries in a burst stays well under."""
    name = "manage_hevy_routine"
    with patch("mcp.handler.time.time", return_value=2000.0):
        for _ in range(8):
            assert h._check_write_rate_limit(name) is None


def test_non_rate_limited_tool_never_blocks():
    with patch("mcp.handler.time.time", return_value=5000.0):
        for _ in range(h._WRITE_TOOL_RATE_LIMIT * 3):
            assert h._check_write_rate_limit("get_sleep_analysis") is None
