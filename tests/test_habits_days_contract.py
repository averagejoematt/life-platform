"""tests/test_habits_days_contract.py — #1107: /api/habits per-habit days[] contract.

Exercises handle_habits against a faked DynamoDB, pinning the 30-day dot-strip contract:
  * every per_habit entry carries days[] — one {date, status} per day of the window,
    ascending, ending today;
  * the window is GENESIS-CLAMPED (ADR-077 / #1133 doctrine): pre-genesis dates are
    clamped OUT entirely — on genesis day the honest strip is 1 day, never padded with
    unlabeled prior-cycle days;
  * statuses: done (scheduled+completed) / missed (scheduled, not completed) /
    off (not scheduled that day) / absent (no data captured that day — ADR-104
    honest absence, the default);
  * days_window {start, end, n_days} is served top-level so the front-end can say WHY
    a strip is short instead of guessing.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from fakes import FakeDdbTable  # noqa: E402
from web import site_api_data as data  # noqa: E402


def _day(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _cond_strings(cond, out):
    """Collect string leaves from a boto3 condition tree (Key('pk').eq(...) & ...)."""
    for v in getattr(cond, "_values", ()) or ():
        if isinstance(v, str):
            out.append(v)
        else:
            _cond_strings(v, out)
    return out


def _fake_table(rows):
    def hook(table, **kwargs):
        strings = _cond_strings(kwargs.get("KeyConditionExpression"), [])
        pk = next((s for s in strings if s.startswith("USER#")), None)
        return {"Items": [r for r in rows if r.get("pk") == pk]}

    return FakeDdbTable(query_hook=hook)


def _habitify_row(date_str, statuses):
    return {
        "pk": "USER#matthew#SOURCE#habitify",
        "sk": f"DATE#{date_str}",
        "date": date_str,
        "habit_statuses": statuses,
    }


def _rows():
    return [
        # Pre-genesis record (3 days ago) — must be clamped OUT of every days[] strip.
        _habitify_row(
            _day(3),
            {"Protein Target": {"status": "completed", "group": "Nutrition", "scheduled_today": True}},
        ),
        # Yesterday (in-cycle): one kept, one missed, one not scheduled.
        _habitify_row(
            _day(1),
            {
                "Protein Target": {"status": "completed", "group": "Nutrition", "scheduled_today": True},
                "Meditate": {"status": "failed", "group": "Growth", "scheduled_today": True},
                "Stretch": {"status": "none", "group": "Recovery", "scheduled_today": False},
            },
        ),
        # Today: NO habitify record at all — every habit's today cell must read "absent".
        # habit_scores row so history/aggregates have something to chew on (not under test).
        {
            "pk": "USER#matthew#SOURCE#habit_scores",
            "sk": f"DATE#{_day(1)}",
            "date": _day(1),
            "tier0_done": Decimal("2"),
            "tier0_total": Decimal("3"),
        },
    ]


def _fake_experiment_date(genesis):
    """Mirror site_api_common._experiment_date with a pinned genesis: max(today-N, genesis),
    clamped to today — deterministic regardless of the repo's live EXPERIMENT_START."""

    def _fn(days_back=30):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        raw = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        return min(max(raw, genesis), today)

    return _fn


def _call(monkeypatch, genesis):
    monkeypatch.setattr(data, "table", _fake_table(_rows()))
    monkeypatch.setattr(data, "_experiment_date", _fake_experiment_date(genesis))
    resp = data.handle_habits()
    assert resp["statusCode"] == 200
    return json.loads(resp["body"])


def _by_name(body):
    return {h["name"]: h for h in body["per_habit"]}


def test_days_present_ascending_and_genesis_clamped(monkeypatch):
    # Genesis = yesterday → the honest window is exactly [yesterday, today], NOT 30 days.
    body = _call(monkeypatch, genesis=_day(1))
    for h in body["per_habit"]:
        dates = [d["date"] for d in h["days"]]
        assert dates == [_day(1), _day(0)], f"{h['name']}: window must clamp to genesis, ascending"
        assert _day(3) not in dates  # pre-genesis day clamped OUT — never unlabeled prior-cycle history
    assert body["days_window"] == {"start": _day(1), "end": _day(0), "n_days": 2}


def test_status_taxonomy_done_missed_off_absent(monkeypatch):
    body = _call(monkeypatch, genesis=_day(1))
    by = _by_name(body)
    strip = {h: {d["date"]: d["status"] for d in by[h]["days"]} for h in by}
    assert strip["Protein Target"][_day(1)] == "done"
    assert strip["Meditate"][_day(1)] == "missed"
    assert strip["Stretch"][_day(1)] == "off"  # not scheduled ≠ missed
    # Today has no habitify record — honest absence for everyone, never inferred (ADR-104).
    for h in strip:
        assert strip[h][_day(0)] == "absent"


def test_full_window_caps_at_30_days(monkeypatch):
    # Genesis far in the past → the strip is the full 30-day window ending today.
    body = _call(monkeypatch, genesis="2000-01-01")
    h = _by_name(body)["Protein Target"]
    dates = [d["date"] for d in h["days"]]
    assert len(dates) == 30
    assert dates[0] == _day(29)
    assert dates[-1] == _day(0)
    assert body["days_window"]["n_days"] == 30


def test_every_day_has_a_valid_status(monkeypatch):
    body = _call(monkeypatch, genesis="2000-01-01")
    valid = {"done", "missed", "off", "absent"}
    for h in body["per_habit"]:
        for d in h["days"]:
            assert set(d.keys()) == {"date", "status"}
            assert d["status"] in valid
