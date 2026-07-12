"""tests/test_presence_endpoint.py — Phase 3: /api/presence fail-closed projection.

The public presence line must expose ONLY the allowlisted headline fields — the
stored record is never spread. Proves the projection is built field-by-field,
honest-nulls before the first compute, and surfaces a return.

#975 amendment: per-channel last-logged marks ARE now public (the cockpit's
"inputs" instrument-health row) via an explicit `channels` projection — registry-
driven set/labels, mark fields only, `quiet` derived from the registry stale
tolerance at read time. The RAW stored channel_detail key still never leaks.
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
    # ↓ the raw stored keys that must be dropped by the fail-closed projection
    #   (channel_detail's MARK fields re-emerge via the explicit #975 `channels`
    #   projection — but the raw key, and anything in it beyond the marks, never do)
    "channel_detail": {
        "macrofactor": {"label": "food", "last_log_date": "2026-06-26", "gap_days": 3, "dropout_streak_days": 3},
        "hevy": {"label": "training", "last_log_date": "2026-06-26", "gap_days": 3, "dropout_streak_days": 3},
    },
    "passive_read": {"rhr": 64, "recovery_trend": "red"},
}

_PRIVATE_KEYS = ("channel_detail", "passive_read", "last_manual_log_date", "channels_quiet")

# The explicit per-channel allowlist (#975) — anything else in a channel entry is a leak.
_CHANNEL_KEYS = {"id", "label", "last_log_date", "gap_days", "quiet", "primary"}


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
    # Exclude _meta: its generated_at microseconds can legitimately contain "64"
    # (flaked CI 2026-07-04 at generated_at=...07:55:12.464115).
    raw = json.dumps({k: v for k, v in body.items() if k != "_meta"})
    assert "recovery_trend" not in raw and "64" not in raw


def test_channels_projection(monkeypatch):
    """#975 — the per-channel marks: registry-driven set, explicit fields only,
    quiet from the registry stale tolerance, the primary (food) channel first."""
    monkeypatch.setattr(sad, "table", _FakeTable(_STORED))
    body = _body(sad.handle_presence())
    chans = body["channels"]
    by_id = {c["id"]: c for c in chans}
    # Registry-driven: every engagement channel appears, even ones absent from the
    # stored detail (honest null marks), and nothing outside the registry does.
    assert set(by_id) == set(sad._ENGAGEMENT_CHANNELS)
    for c in chans:
        assert set(c) == _CHANNEL_KEYS, f"unexpected channel fields on {c['id']}: {set(c) - _CHANNEL_KEYS}"
    # The primary (food) channel leads the row.
    assert chans[0]["id"] == "macrofactor" and chans[0]["primary"] is True
    # Marks come from the stored detail; labels from the registry.
    assert by_id["macrofactor"]["last_log_date"] == "2026-06-26"
    assert by_id["macrofactor"]["gap_days"] == 3
    assert by_id["macrofactor"]["label"] == "food"
    # quiet = gap > registry stale_days: food tolerates 2 (3 → quiet), training 4 (3 → fresh).
    assert by_id["macrofactor"]["quiet"] is True
    assert by_id["hevy"]["quiet"] is False
    # A channel with nothing in the stored window: honest nulls, quiet (nothing seen).
    assert by_id["notion"]["last_log_date"] is None
    assert by_id["notion"]["quiet"] is True


def test_honest_null_before_first_compute(monkeypatch):
    monkeypatch.setattr(sad, "table", _FakeTable(None))
    body = _body(sad.handle_presence())
    assert body["available"] is False
    assert body["presence_class"] == "present"
    assert body["in_lull"] is False
    # #975: before the first compute the channel set still exists (registry truth)
    # but every mark is an honest null and quiet is None — unknown, never a scold.
    for c in body["channels"]:
        assert c["last_log_date"] is None and c["gap_days"] is None and c["quiet"] is None


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
