#!/usr/bin/env python3
"""
tests/test_hae_activity_failsafe.py — DI-1.6 Apple Health activity-integrity guard.

Covers the silent-413 blind spot: HAE keeps the apple_health partition fresh via
small automations (water/BP/CGM) while the oversized `steps` payload is dropped at
the gateway. The guard must fire on a steps-vs-partition lag and on sustained low
activity, stay quiet when healthy, and respect sick-day suppression.

Run: python3 -m pytest tests/test_hae_activity_failsafe.py -v
"""

import os
import sys
from datetime import datetime, timezone

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "emails"))

import freshness_checker_lambda as fc  # noqa: E402

NOW = datetime(2026, 6, 20, 17, 0, tzinfo=timezone.utc)


class FakeTable:
    """Returns canned DATE# items newest-first (matches ScanIndexForward=False)."""

    def __init__(self, rows):
        # rows: list of (date_str, steps_or_None, active_cal_or_None)
        self._items = [
            {
                "sk": f"DATE#{d}",
                **({"steps": s} if s is not None else {}),
                **({"active_calories": a} if a is not None else {}),
            }
            for d, s, a in sorted(rows, key=lambda r: r[0], reverse=True)
        ]

    def query(self, **kwargs):
        limit = kwargs.get("Limit", len(self._items))
        return {"Items": self._items[:limit]}


def _healthy_rows():
    # 6/13..6/19 complete days with normal steps, partition fresh through 6/20.
    return [
        ("2026-06-13", 8000, 300),
        ("2026-06-14", 7366, 428),
        ("2026-06-15", 9000, 350),
        ("2026-06-16", 8709, 502),
        ("2026-06-17", 10043, 752),
        ("2026-06-18", 6500, 379),
        ("2026-06-19", 11645, 892),
        ("2026-06-20", 2794, 154),  # today, partial
    ]


def test_healthy_no_alert():
    msg, m = fc.check_apple_health_activity(FakeTable(_healthy_rows()), NOW, sick_suppress=False)
    assert msg is None
    assert m["degraded"] == 0.0
    assert m["steps_lag_days"] == 0.0
    assert m["low_step_days"] == 0.0


def test_steps_stale_while_partition_fresh_alerts():
    # Water/BP keep landing through 6/20 (partition fresh) but steps stop after 6/16.
    rows = [
        ("2026-06-14", 7366, 428),
        ("2026-06-15", 9000, 350),
        ("2026-06-16", 8709, 502),
        ("2026-06-17", None, None),  # steps stream dropped
        ("2026-06-18", None, None),
        ("2026-06-19", None, None),
        ("2026-06-20", None, 154),  # partition fresh (non-steps automation)
    ]
    msg, m = fc.check_apple_health_activity(FakeTable(rows), NOW, sick_suppress=False)
    assert msg is not None
    assert "activity" in msg.lower()
    assert m["degraded"] == 1.0
    assert m["steps_lag_days"] >= fc.AH_STEPS_LAG_ALERT_DAYS


def test_no_steps_at_all_is_severe():
    rows = [(f"2026-06-1{d}", None, None) for d in range(4, 10)] + [("2026-06-20", None, 154)]
    msg, m = fc.check_apple_health_activity(FakeTable(rows), NOW, sick_suppress=False)
    assert msg is not None
    assert m["steps_lag_days"] >= fc.AH_STEPS_LAG_ALERT_DAYS


def test_sustained_low_activity_alerts():
    # Steps present every day but ≥4 of 7 are implausibly low (intermittent partial drops).
    rows = [
        ("2026-06-13", 200, 10),
        ("2026-06-14", 7366, 428),
        ("2026-06-15", 402, 22),
        ("2026-06-16", 500, 30),
        ("2026-06-17", 8000, 400),
        ("2026-06-18", 444, 18),
        ("2026-06-19", 9000, 500),
        ("2026-06-20", 2794, 154),
    ]
    msg, m = fc.check_apple_health_activity(FakeTable(rows), NOW, sick_suppress=False)
    assert m["low_step_days"] >= fc.AH_LOW_STEP_ALERT_COUNT
    assert msg is not None


def test_sick_day_suppresses_alert_but_still_flags_metric():
    rows = [
        ("2026-06-14", 7366, 428),
        ("2026-06-15", 9000, 350),
        ("2026-06-16", 8709, 502),
        ("2026-06-17", None, None),
        ("2026-06-18", None, None),
        ("2026-06-19", None, None),
        ("2026-06-20", None, 154),
    ]
    msg, m = fc.check_apple_health_activity(FakeTable(rows), NOW, sick_suppress=True)
    assert msg is None  # suppressed
    assert m["degraded"] == 1.0  # but the metric still records the degradation


def test_empty_partition_is_quiet():
    msg, m = fc.check_apple_health_activity(FakeTable([]), NOW, sick_suppress=False)
    assert msg is None
    assert m["degraded"] == 0.0


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
