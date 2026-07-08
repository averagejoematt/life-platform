"""tests/test_fulfillment_ritual_aggregate.py — #769 (ADR-124): the aggregate-only
publish surface for the evening-ritual C floor (GET /api/fulfillment_ritual,
lambdas/web/site_api_data.py::handle_fulfillment_ritual).

Covers the ADR-124 publication posture directly:
  * a dark day renders as honest absence (null), never a fabricated neutral (ADR-104)
  * the aggregate always returns a shaped 200, even with zero history (a bad-week /
    no-history channel must never look like an error)
  * check-in count + streak are derived correctly, including that a dark day breaks
    a streak (nothing is backfilled or assumed)
  * the response never carries anything beyond the sanctioned aggregate shape
    (individual daily records are not a public surface)
"""

import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import site_api_data as data  # noqa: E402


class _FakeTable:
    def __init__(self, items):
        self._items = items

    def query(self, **_kw):
        return {"Items": self._items}


def _today():
    return datetime.now(data.PT).strftime("%Y-%m-%d")


def _days_ago(n):
    return (datetime.now(data.PT) - timedelta(days=n)).strftime("%Y-%m-%d")


def _item(date_str, connection=None, mood_valence=None):
    it = {"pk": f"{data.USER_PREFIX}evening_ritual", "sk": f"DATE#{date_str}", "date": date_str}
    if connection is not None:
        it["connection"] = connection
    if mood_valence is not None:
        it["mood_valence"] = mood_valence
    return it


def _body(monkeypatch, items):
    monkeypatch.setattr(data, "table", _FakeTable(items))
    r = data.handle_fulfillment_ritual()
    assert r["statusCode"] == 200
    return json.loads(r["body"])


# ── shaped-empty state ───────────────────────────────────────────────────────


def test_no_history_returns_shaped_200_not_an_error(monkeypatch):
    body = _body(monkeypatch, [])
    assert body["check_in_count"] == 0
    assert body["streak_days"] == 0
    assert len(body["trend_7d"]) == 7
    assert all(day["connection"] is None and day["mood_valence"] is None for day in body["trend_7d"])


# ── honest absence (ADR-104) ─────────────────────────────────────────────────


def test_dark_day_in_trend_is_null_not_zero(monkeypatch):
    items = [_item(_today(), connection=3, mood_valence=2), _item(_days_ago(2), connection=1, mood_valence=1)]
    body = _body(monkeypatch, items)
    by_date = {d["date"]: d for d in body["trend_7d"]}
    dark_day = _days_ago(1)  # no record for yesterday
    assert by_date[dark_day]["connection"] is None
    assert by_date[dark_day]["mood_valence"] is None
    assert by_date[_today()]["connection"] == 3
    assert by_date[_today()]["mood_valence"] == 2


def test_partial_day_only_nulls_the_unlogged_metric(monkeypatch):
    items = [_item(_today(), connection=3)]  # mood_valence not logged today
    body = _body(monkeypatch, items)
    today_row = next(d for d in body["trend_7d"] if d["date"] == _today())
    assert today_row["connection"] == 3
    assert today_row["mood_valence"] is None


def test_trend_covers_exactly_the_last_seven_calendar_days(monkeypatch):
    body = _body(monkeypatch, [])
    dates = [d["date"] for d in body["trend_7d"]]
    expected = [_days_ago(n) for n in range(6, -1, -1)]
    assert dates == expected


# ── check-in count ────────────────────────────────────────────────────────────


def test_check_in_count_counts_any_day_with_at_least_one_scalar(monkeypatch):
    items = [_item(_days_ago(1), connection=2), _item(_days_ago(3), mood_valence=1)]  # partial logs still count
    body = _body(monkeypatch, items)
    assert body["check_in_count"] == 2


def test_check_in_count_ignores_a_record_with_neither_scalar(monkeypatch):
    # a stray record with no scalars at all (shouldn't happen, but must not miscount)
    items = [{"pk": f"{data.USER_PREFIX}evening_ritual", "sk": f"DATE#{_days_ago(1)}", "date": _days_ago(1)}]
    body = _body(monkeypatch, items)
    assert body["check_in_count"] == 0


# ── streak ────────────────────────────────────────────────────────────────────


def test_streak_breaks_on_a_dark_day(monkeypatch):
    items = [_item(_today(), connection=3), _item(_days_ago(1), connection=2), _item(_days_ago(3), connection=1)]  # gap at day 2
    body = _body(monkeypatch, items)
    assert body["streak_days"] == 2  # today + yesterday only


def test_streak_counts_from_most_recent_log_when_today_not_yet_logged(monkeypatch):
    # today itself isn't logged yet (the nudge fires in the evening); the streak
    # should still reflect the unbroken run ending yesterday, not reset to 0.
    items = [_item(_days_ago(1), connection=3), _item(_days_ago(2), connection=2)]
    body = _body(monkeypatch, items)
    assert body["streak_days"] == 2


def test_streak_zero_when_no_history(monkeypatch):
    body = _body(monkeypatch, [])
    assert body["streak_days"] == 0


# ── aggregate-only shape (no per-day notes/free-text leak) ─────────────────────


def test_response_shape_is_aggregate_only(monkeypatch):
    items = [_item(_today(), connection=3, mood_valence=2)]
    body = _body(monkeypatch, items)
    allowed_top_level = {"trend_7d", "check_in_count", "streak_days", "as_of_date", "_meta"}
    assert set(body.keys()) <= allowed_top_level
    for day in body["trend_7d"]:
        assert set(day.keys()) == {"date", "connection", "mood_valence"}
