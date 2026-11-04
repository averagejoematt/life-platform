"""tests/test_habits_endpoint_causality.py — #422: /api/habits serves causality + cross-page.

Exercises handle_habits against a faked DynamoDB across all four partitions it reads
(habit_scores, habitify, habit_causality, computed_metrics), pinning:
  * EVR-01: a captured Habitify-note trigger renders on per_habit[].causality, verbatim.
  * EVR-02: a why-missed reason (either channel) attaches; a habit with no capture has NO
    causality key at all — honestly empty, no inferred causes (ADR-104).
  * EVR-03: cross-page component signals fill only group-days the tracker left empty,
    tagged groups_cross_page; a tracker-scored group-day is never touched.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from common import activity_publication as AP  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from web import site_api_data as data  # noqa: E402

# Owner ruling 2026-11-03 (fail closed): a habit is published only when classified — these
# synthetic habits borrow classified-public ids (opaque; the names are the fixture's own).
_ID = dict(zip(("Protein Target", "Meditate", "Stretch"), sorted(AP.PUBLIC_HABIT_IDS)))


def _yesterday():
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


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


def _rows():
    d = _yesterday()
    return [
        # habit tracker day record (habit_scores) — tracker owns Nutrition that day
        {
            "pk": "USER#matthew#SOURCE#habit_scores",
            "sk": f"DATE#{d}",
            "date": d,
            "tier0_done": Decimal("3"),
            "tier0_total": Decimal("4"),
            "group_Nutrition": Decimal("75"),
        },
        # habitify record — a completed habit with a trigger: note, a missed one without
        {
            "pk": "USER#matthew#SOURCE#habitify",
            "sk": f"DATE#{d}",
            "date": d,
            "habit_statuses": {
                "Protein Target": {
                    "status": "completed",
                    "group": "Nutrition",
                    "scheduled_today": True,
                    "habit_id": _ID["Protein Target"],
                    "notes": ["trigger: post-workout shake", "reward: felt full all morning"],
                    "note_channel": "habitify_note",
                },
                "Meditate": {"status": "failed", "group": "Growth", "scheduled_today": True, "habit_id": _ID["Meditate"]},
                "Stretch": {"status": "failed", "group": "Recovery", "scheduled_today": True, "habit_id": _ID["Stretch"]},
            },
        },
        # Claude-reflection record: the why for the missed Meditate day (Stretch stays empty)
        {
            "pk": "USER#matthew#SOURCE#habit_causality",
            "sk": f"HABITDAY#{d}#meditate",
            "date": d,
            "habit": "Meditate",
            "slug": "meditate",
            "channel": "claude_reflection",
            "why_missed": "was traveling, red-eye flight",
        },
        # computed_metrics — movement component clears the floor → cross-page Performance;
        # nutrition also clears it, but the tracker already scored Nutrition that day.
        {
            "pk": "USER#matthew#SOURCE#computed_metrics",
            "sk": f"DATE#{d}",
            "date": d,
            "component_scores": {"movement": Decimal("82"), "nutrition": Decimal("90")},
        },
    ]


def _call(monkeypatch):
    monkeypatch.setattr(data, "table", _fake_table(_rows()))
    resp = data.handle_habits()
    assert resp["statusCode"] == 200
    return json.loads(resp["body"])


# Owner confirmation 2026-11-03: "Public classification ... doesn't automatically authorize publishing
# associated free-text responses or private notes." The in-app notes and the reflection layer are free
# text — private by default (common.activity_publication.HABIT_STATUS_FIELDS) — so the #422 causality
# capture is no longer served publicly. These tests were its render contract; they now pin the hold.


def test_in_app_note_text_is_not_served_even_on_a_public_habit(monkeypatch):
    body = _call(monkeypatch)
    by_name = {h["name"]: h for h in body["per_habit"]}
    assert set(by_name) == {"Protein Target", "Meditate", "Stretch"}  # the habits themselves stay public
    assert "causality" not in by_name["Protein Target"]
    raw = json.dumps(body)
    assert "post-workout shake" not in raw and "felt full all morning" not in raw


def test_the_reflection_layer_is_not_served(monkeypatch):
    body = _call(monkeypatch)
    by_name = {h["name"]: h for h in body["per_habit"]}
    assert "causality" not in by_name["Meditate"]
    assert "red-eye" not in json.dumps(body)
    assert body["causality_captured"] == 0


def test_uncaptured_habit_stays_honestly_empty(monkeypatch):
    # Stretch was missed with NO note and NO reflection — no causality key, no guessed cause.
    body = _call(monkeypatch)
    by_name = {h["name"]: h for h in body["per_habit"]}
    assert "causality" not in by_name["Stretch"]


def test_cross_page_fills_gap_but_never_double_counts(monkeypatch):
    body = _call(monkeypatch)
    day = next(h for h in body["history"] if h["date"] == _yesterday())
    # The tracker's own Nutrition share (its PUBLIC habits: Protein Target completed) is untouched —
    # the nutrition component 90 must NOT replace it.
    assert day["groups"]["Nutrition"] == 100
    # Movement page signal fills the empty Performance group-day, tagged as borrowed.
    assert day["groups"]["Performance"] == 82
    assert day["groups_cross_page"] == {"Performance": 82}
    assert body["cross_page_days"] == 1
    # The wiring registry itself is served for transparency: one signal per PUBLIC page (the journal's
    # Mind signal is private activity, owner ruling 2026-11-03).
    assert body["cross_page_signals"] == {p: s["group"] for p, s in data.habit_causality.public_cross_page_signals().items()}
    assert "mind" not in body["cross_page_signals"]
