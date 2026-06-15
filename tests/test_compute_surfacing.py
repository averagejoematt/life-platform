"""tests/test_compute_surfacing.py — elite review (2026-06-15) surfacing PR.

Two compute outputs were stored daily but never exposed via the site API:
  * circadian-compliance score  (SOURCE#circadian | DATE#)
  * unified sleep reconciliation (SOURCE#sleep_unified | DATE#)

These tests exercise the new read-only handlers against a faked DynamoDB,
covering: the populated shape, the empty/no-data path, source_map decoding,
and internal-key stripping. ER-02 contract spirit — the endpoints' public shape
is now pinned.
"""

import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import (
    site_api_common as common,  # noqa: E402
    site_api_data as data,  # noqa: E402
)


class _FakeTable:
    """Returns a fixed item list for query(); _latest_item asks for newest-1."""

    def __init__(self, items):
        self._items = items

    def query(self, **_kw):
        return {"Items": self._items}


# ── circadian ────────────────────────────────────────────────────────────────


def test_circadian_populated_shape(monkeypatch):
    item = {
        "pk": "USER#matthew#SOURCE#circadian",
        "sk": "DATE#2026-06-15",
        "date": "2026-06-15",
        "score": Decimal("78"),
        "category": "good",
        "prescription": "Get morning light before 9am.",
        "weakest_component": "screen_wind_down",
        "components": {
            "wake_light": {"score": Decimal("25"), "max": Decimal("25"), "note": "Logged AM sun"},
            "screen_wind_down": {"score": Decimal("3"), "max": Decimal("25"), "note": "Late screens"},
        },
        "run_id": "abc123",
    }
    monkeypatch.setattr(common, "table", _FakeTable([item]))

    resp = data.handle_circadian()
    assert resp["statusCode"] == 200
    body = __import__("json").loads(resp["body"])
    assert body["available"] is True
    assert body["date"] == "2026-06-15"
    assert body["score"] == 78
    assert body["category"] == "good"
    assert body["weakest_component"] == "screen_wind_down"
    assert body["components"]["wake_light"]["score"] == 25
    assert body["components"]["screen_wind_down"]["note"] == "Late screens"
    # internal keys must not leak
    assert "pk" not in body and "sk" not in body and "run_id" not in body


def test_circadian_no_data(monkeypatch):
    monkeypatch.setattr(common, "table", _FakeTable([]))
    resp = data.handle_circadian()
    assert resp["statusCode"] == 200
    body = __import__("json").loads(resp["body"])
    assert body["available"] is False
    assert "score" not in body


# ── unified sleep reconciliation ──────────────────────────────────────────────


def test_sleep_reconciliation_decodes_source_map_and_strips_internals(monkeypatch):
    item = {
        "pk": "USER#matthew#SOURCE#sleep_unified",
        "sk": "DATE#2026-06-15",
        "date": "2026-06-15",
        "total_duration_hours": Decimal("7.4"),
        "hrv_ms": Decimal("61"),
        "recovery_score": Decimal("66"),
        "sources_present": ["whoop", "eightsleep"],
        "source_map": '{"hrv_ms": "whoop", "room_temp_c": "eightsleep"}',
        "reconciled_at": "2026-06-15T16:00:00+00:00",
        "run_id": "xyz789",
        "computed_at": "2026-06-15T16:00:00+00:00",
    }
    monkeypatch.setattr(common, "table", _FakeTable([item]))

    resp = data.handle_sleep_reconciliation()
    assert resp["statusCode"] == 200
    body = __import__("json").loads(resp["body"])
    assert body["available"] is True
    assert body["total_duration_hours"] == 7.4
    assert body["sources_present"] == ["whoop", "eightsleep"]
    # source_map decoded from JSON string → dict
    assert body["source_map"] == {"hrv_ms": "whoop", "room_temp_c": "eightsleep"}
    # internal keys stripped
    for k in ("pk", "sk", "run_id", "computed_at"):
        assert k not in body


def test_sleep_reconciliation_no_data(monkeypatch):
    monkeypatch.setattr(common, "table", _FakeTable([]))
    resp = data.handle_sleep_reconciliation()
    assert resp["statusCode"] == 200
    body = __import__("json").loads(resp["body"])
    assert body["available"] is False
    assert "total_duration_hours" not in body
