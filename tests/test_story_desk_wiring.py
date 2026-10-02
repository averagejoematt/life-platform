"""tests/test_story_desk_wiring.py — #4535/#4536/#4533: the live Story Desk's must-agree pair on the chronicle row.

wednesday-chronicle WRITES desk_episode_json + desk_ledger_json onto DATE#<week end>; coach-panel-podcast READS the
episode (and renders it instead of writing its own); chronicle-approve READS the ledger on publish and commits
LEDGER#<date>. One fake table, the real functions on both sides, the real row shape — and mutation controls showing
each reader actually depends on what the writer wrote.
"""

from __future__ import annotations

import json
import os
import sys

for k, v in {
    "TABLE_NAME": "life-platform",
    "S3_BUCKET": "matthew-life-platform",
    "USER_ID": "matthew",
    "AWS_REGION": "us-west-2",
    "AWS_DEFAULT_REGION": "us-west-2",
    "EMAIL_RECIPIENT": "test@example.com",
    "EMAIL_SENDER": "noreply@example.com",
}.items():
    os.environ.setdefault(k, v)

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import wednesday_chronicle_lambda as chron  # noqa: E402
from emails import (
    chronicle_approve_lambda as approve,  # noqa: E402
    coach_panel_podcast_lambda as panel,  # noqa: E402
)


class _Table:
    def __init__(self):
        self.rows = {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ExpressionAttributeNames=None, **_):
        import re

        row = self.rows.setdefault((Key["pk"], Key["sk"]), dict(Key))
        names = ExpressionAttributeNames or {}
        for name, val in re.findall(r"(#?\w+)\s*=\s*(if_not_exists\([^)]*\)|:\w+)", UpdateExpression):
            name = names.get(name, name)
            if val.startswith("if_not_exists"):
                row.setdefault(name, ExpressionAttributeValues[val.split(",")[1].strip(" )")])
            else:
                row[name] = ExpressionAttributeValues[val]

    def get_item(self, Key):
        return {"Item": self.rows.get((Key["pk"], Key["sk"]))} if (Key["pk"], Key["sk"]) in self.rows else {}

    def put_item(self, Item):
        self.rows[(Item["pk"], Item["sk"])] = Item


DESK = {
    "budget": {"lead": {"thread_id": "the_streak"}},
    "episode": {
        "title": "The Body Answers Back",
        "excerpt": "x",
        "turns": [{"speaker": "elena", "line": "Day 24."}, {"speaker": "coach", "line": "I was wrong nine times."}],
        "guest": {"name": "Marcus Webb", "coach_id": "nutrition_coach", "persona_id": "marcus_webb"},
        "bet": {"claim": "recovery below 60 on Thursday"},
    },
    "ledger": {"week": 4, "date": "2026-09-29", "threads": [], "bets": [], "titles": []},
    "findings": {"post": [], "episode": []},
}


def _wire(monkeypatch):
    t = _Table()
    for mod in (chron, panel, approve):
        monkeypatch.setattr(mod, "table", t)
    return t


def test_the_panel_renders_what_the_chronicle_attached(monkeypatch):
    t = _wire(monkeypatch)
    chron._attach_desk_artifacts("2026-09-29", DESK)
    ep = panel._desk_episode({"date": "2026-09-29"})
    assert ep and ep["turns"][1]["line"] == "I was wrong nine times." and ep["guest"]["coach_id"] == "nutrition_coach"
    assert t.rows[("USER#matthew#SOURCE#chronicle", "DATE#2026-09-29")]["phase"] == "experiment"  # renderers filter on phase
    assert panel._desk_episode({"date": "2026-09-22"}) is None  # mutation control: no attachment → legacy writer


def test_the_approve_path_commits_the_ledger_the_chronicle_attached(monkeypatch):
    t = _wire(monkeypatch)
    chron._attach_desk_artifacts("2026-09-29", DESK)
    row = t.get_item(Key={"pk": "USER#matthew#SOURCE#chronicle", "sk": "DATE#2026-09-29"})["Item"]
    approve._commit_ledger(row)
    led = t.rows[("USER#matthew#SOURCE#chronicle", "LEDGER#2026-09-29")]
    assert json.loads(led["ledger_json"])["week"] == 4
    approve._commit_ledger({"date": "2026-09-22"})  # mutation control: a legacy week commits nothing
    assert ("USER#matthew#SOURCE#chronicle", "LEDGER#2026-09-22") not in t.rows


def test_an_unsafe_desk_line_is_held_not_voiced(monkeypatch):
    _wire(monkeypatch)
    ep = dict(DESK["episode"], turns=[{"speaker": "elena", "line": "He weighed 312 pounds and that led to the drop."}])
    out = panel._publish_desk_episode(4, {"date": "2026-09-29"}, ep, dry_run=True)
    assert "HOLD" in json.dumps(out)
