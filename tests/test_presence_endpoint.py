"""tests/test_presence_endpoint.py — Phase 3: /api/presence fail-closed projection.

The public presence line must expose ONLY the allowlisted headline fields — never
the stored record's private per-channel detail. Proves the projection is built
field-by-field, honest-nulls before the first compute, and surfaces a return.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from web import site_api_data as sad  # noqa: E402


class _FakeTable:
    def __init__(self, item):
        self._item = item

    def get_item(self, Key=None):
        return {"Item": self._item} if self._item is not None else {}


def _body(resp):
    return json.loads(resp["body"]) if isinstance(resp.get("body"), str) else resp["body"]


# The full stored record — includes fields that must NOT reach the public surface.
_STORED = {
    "pk": "USER#matthew#SOURCE#engagement_state",
    "sk": "STATE#current",
    "date": "2026-06-30",
    "presence_class": "quiet",
    "gap_days": 3,
    "last_food_log_date": "2026-06-26",
    "last_manual_log_date": "2026-06-26",
    "channels_quiet": ["food", "training", "habits"],
    "channels_quiet_count": 3,
    "passive_still_flowing": True,
    "planned_pause": False,
    "planned_pause_reason": "",
    "returned": False,
    # ↓ private internals that must be dropped by the fail-closed projection
    "channel_detail": {"macrofactor": {"last_log_date": "2026-06-26", "gap_days": 3}},
    "passive_read": {"rhr": 64, "recovery_trend": "red"},
}

_PRIVATE_KEYS = ("channel_detail", "passive_read", "last_manual_log_date", "channels_quiet")


def test_projection_is_fail_closed(monkeypatch):
    monkeypatch.setattr(sad, "table", _FakeTable(_STORED))
    body = _body(sad.handle_presence())
    assert body["presence_class"] == "quiet"
    assert body["gap_days"] == 3
    assert body["in_lull"] is True
    assert body["channels_quiet_count"] == 3
    assert body["passive_still_flowing"] is True
    # None of the private internals leak — the projection is an explicit allowlist.
    for k in _PRIVATE_KEYS:
        assert k not in body, f"private field {k!r} leaked to /api/presence"
    raw = json.dumps(body)
    assert "recovery_trend" not in raw and "64" not in raw


def test_honest_null_before_first_compute(monkeypatch):
    monkeypatch.setattr(sad, "table", _FakeTable(None))
    body = _body(sad.handle_presence())
    assert body["available"] is False
    assert body["presence_class"] == "present"
    assert body["in_lull"] is False


def test_surfaces_return(monkeypatch):
    rec = dict(_STORED, presence_class="present", returned=True, resumed_after_days=5, weight_delta_over_gap=3.2)
    monkeypatch.setattr(sad, "table", _FakeTable(rec))
    body = _body(sad.handle_presence())
    assert body["returned"] is True
    assert body["resumed_after_days"] == 5
    assert body["weight_delta_over_gap_lbs"] == 3.2
    # present + returned → not "in a lull", but the return is still news
    assert body["in_lull"] is False


def test_read_error_is_shaped(monkeypatch):
    class _Boom:
        def get_item(self, Key=None):
            raise RuntimeError("ddb down")

    monkeypatch.setattr(sad, "table", _Boom())
    body = _body(sad.handle_presence())
    assert body["available"] is False
    assert body["presence_class"] == "present"
