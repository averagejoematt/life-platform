"""tests/test_story_ledger_4533.py — #4533: the season ledger is ONE cycle's memory, written on publish and read by both writers.

The contract under test, end to end on one fake table with the real functions on every side:

  WRITER  chronicle-approve `_commit_ledger` turns the row's `desk_ledger_json` into `LEDGER#{date}` on publish
          (the chronicle lambda's `_attach_desk_artifacts` put it there);
  READERS `story_pipeline.live_week` reads it back through `story_ledger.latest_visible` and hands the SAME ledger to
          the chronicle writer and to the Panel episode writer (the Panel renders that episode, #4536).

A tombstoned row or a row a previous cycle left behind must be invisible to both readers — mutation controls show the
reader really does depend on each filter (drop either condition in `story_ledger.row_visible` and a test here goes red).
"""

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal

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
from common.constants import EXPERIMENT_START_DATE  # noqa: E402
from content import story_desk, story_dossier, story_ledger, story_pipeline, story_writers  # noqa: E402
from emails import chronicle_approve_lambda as approve  # noqa: E402
from web.site_api_data import CYCLE_GENESES  # noqa: E402

PK = "USER#matthew#SOURCE#chronicle"
THIS_CYCLE = str(max(int(n) for n, g in CYCLE_GENESES.items() if str(g)[:10] == EXPERIMENT_START_DATE))
PREV_CYCLE = str(int(THIS_CYCLE) - 1)


class _Table:
    """update_item / get_item / put_item / query over a dict, honouring the pk + sk-range key condition."""

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
        self.rows[(Item["pk"], Item["sk"])] = dict(Item)

    def query(self, KeyConditionExpression, ScanIndexForward=True, **_):
        pk_cond, sk_cond = KeyConditionExpression.get_expression()["values"]
        pk = pk_cond.get_expression()["values"][1]
        _key, lo, hi = sk_cond.get_expression()["values"]
        items = [dict(r) for (p, s), r in self.rows.items() if p == pk and lo <= s <= hi]
        items.sort(key=lambda r: r["sk"], reverse=not ScanIndexForward)
        return {"Items": items}


def _season_ledger(week, date, bet_claim):
    """What a published week leaves: one open thread and one open bet."""
    led = story_ledger.apply_budget(
        story_ledger.empty_ledger(),
        {
            "lead": {"thread_id": "the_streak", "angle": "the streak"},
            "thread_actions": [{"thread_id": "the_streak", "action": "open", "title": "the training streak", "note": ""}],
            "bet_scored": {"result": "none"},
            "bet": {"claim": bet_claim, "metric": "recovery", "rule": ">=70 on 4 of 7"},
            "featured_coaches": ["sleep_coach"],
            "beats_used": ["first weigh-in"],
            "arc_updates": [{"who": "elena", "line": "stopped hedging"}],
        },
        week=week,
        date=date,
        title=f"Week {week}",
    )
    return led


def _publish(t, week, date, bet_claim):
    """The real writer path: the chronicle attaches the desk ledger, approve commits it on publish."""
    led = _season_ledger(week, date, bet_claim)
    chron._attach_desk_artifacts(date, {"budget": {}, "episode": {}, "ledger": led, "findings": {}})
    approve._commit_ledger(t.get_item(Key={"pk": PK, "sk": f"DATE#{date}"})["Item"])
    return led


def _wire(monkeypatch):
    t = _Table()
    for mod in (chron, approve):
        monkeypatch.setattr(mod, "table", t)
    return t


def _readers_see(monkeypatch, t, date_str="2026-09-29"):
    """Run the live week through the desk with every model call stubbed; return the ledger each writer was handed."""
    seen = {}
    monkeypatch.setattr(story_dossier, "week_dossier", lambda table, wk: ({"roster": [{"coach_id": "sleep_coach", "name": "S"}]}, []))
    monkeypatch.setattr(
        story_desk, "run_desk", lambda dossier, ledger, week, log=None: {"lead": {"thread_id": "x"}, "featured_coaches": ["sleep_coach"]}
    )

    def write_chronicle(dossier, budget, ledger, week, previous=None, **_):
        seen["chronicle"] = ledger
        return '"Title"\n\nBody.', "end_turn"

    def write_episode(dossier, budget, ledger, week, **_):
        seen["panel"] = ledger
        return {"turns": []}, "end_turn"

    monkeypatch.setattr(story_writers, "write_chronicle", write_chronicle)
    monkeypatch.setattr(story_writers, "write_episode", write_episode)
    for gate in ("post", "episode", "dek"):
        monkeypatch.setattr(story_pipeline._Gates, gate, lambda self, *a, **k: [])
    out = story_pipeline.live_week(t, date_str, chronicle_pk=PK, log=lambda m: None)
    assert out is not None, "2026-09-29 must be a season week end"
    return seen


# ── the cycle the ledger belongs to ──────────────────────────────────────────


def test_current_cycle_is_the_cycle_whose_genesis_is_the_experiment_start():
    assert story_ledger.current_cycle() == THIS_CYCLE


def test_a_number_cycle_and_a_string_cycle_are_the_same_season():
    """The publish path writes "17"; the write-time stamp overwrites it with N 17 (Decimal on read). Both are visible."""
    for raw in (THIS_CYCLE, int(THIS_CYCLE), Decimal(THIS_CYCLE)):
        assert story_ledger.row_visible({"phase": "experiment", "cycle": raw}, THIS_CYCLE), raw


# ── acceptance 1: contract — ledger writer ↔ chronicle and panel readers ─────


def test_the_published_ledger_is_what_both_writers_read_next_week(monkeypatch):
    t = _wire(monkeypatch)
    _publish(t, 3, "2026-09-22", "recovery >= 70 on 4 of 7 days")
    row = t.rows[(PK, "LEDGER#2026-09-22")]
    assert row["record_type"] == "story_ledger" and row["phase"] == "experiment"
    assert story_ledger.row_visible(row, THIS_CYCLE), "the writer's own row must pass the reader's filter"
    seen = _readers_see(monkeypatch, t)
    for who in ("chronicle", "panel"):
        led = seen[who]
        assert led["week"] == 3 and led["date"] == "2026-09-22", who
        assert [x["id"] for x in story_ledger.open_threads(led)] == ["the_streak"], who
        assert story_ledger.last_open_bet(led)["claim"] == "recovery >= 70 on 4 of 7 days", who  # the bet the Panel scores
        assert led["arcs"] == {"elena": "stopped hedging"}, who
    assert seen["chronicle"] == seen["panel"]  # one memory, not two


def test_a_draft_that_never_published_leaves_no_ledger(monkeypatch):
    """Written on publish only: an attached-but-unapproved week is not memory."""
    t = _wire(monkeypatch)
    chron._attach_desk_artifacts(
        "2026-09-22", {"budget": {}, "episode": {}, "ledger": _season_ledger(3, "2026-09-22", "b"), "findings": {}}
    )
    assert not [s for (_p, s) in t.rows if s.startswith("LEDGER#")]
    assert _readers_see(monkeypatch, t)["chronicle"]["week"] is None


# ── acceptance 2: a tombstoned or previous-cycle row is invisible to both ────


def test_a_tombstoned_ledger_row_is_invisible_to_both_writers(monkeypatch):
    t = _wire(monkeypatch)
    _publish(t, 2, "2026-09-15", "the older bet")
    _publish(t, 3, "2026-09-22", "the wiped bet")
    t.rows[(PK, "LEDGER#2026-09-22")]["tombstone"] = True
    seen = _readers_see(monkeypatch, t)
    for who in ("chronicle", "panel"):
        assert seen[who]["date"] == "2026-09-15", who  # skips the tombstone, falls back to the visible row
        assert story_ledger.last_open_bet(seen[who])["claim"] == "the older bet", who
    t.rows[(PK, "LEDGER#2026-09-22")].pop("tombstone")  # mutation control: un-tombstoned, it is the memory again
    assert _readers_see(monkeypatch, t)["panel"]["date"] == "2026-09-22"


def test_a_previous_cycle_ledger_row_is_invisible_to_both_writers(monkeypatch):
    """The #4536 failure shape: a row an earlier cycle left behind, NOT tombstoned and still phase=experiment (the
    wipe missed it, or it was re-tagged), must not become this season's threads and bets."""
    t = _wire(monkeypatch)
    _publish(t, 3, "2026-09-22", "a bet from another season")
    t.rows[(PK, "LEDGER#2026-09-22")]["cycle"] = PREV_CYCLE
    seen = _readers_see(monkeypatch, t)
    for who in ("chronicle", "panel"):
        assert seen[who]["week"] is None and story_ledger.last_open_bet(seen[who]) is None, who
    t.rows[(PK, "LEDGER#2026-09-22")]["cycle"] = Decimal(THIS_CYCLE)  # mutation control: this cycle's, it is visible
    assert story_ledger.last_open_bet(_readers_see(monkeypatch, t)["panel"])["claim"] == "a bet from another season"


def test_a_ledger_row_with_no_cycle_cannot_claim_this_season():
    row = {"pk": PK, "sk": "LEDGER#2026-09-22", "phase": "experiment", "ledger_json": "{}"}
    assert not story_ledger.row_visible(row, THIS_CYCLE)
    assert story_ledger.row_visible(row, None)  # registry unreadable: the phase/tombstone filter alone decides


def test_every_ledger_reader_goes_through_the_one_filtered_door():
    """Both writers' ledger comes from `latest_visible` (live_week), and so does the Monday questions send; none
    re-implements the LEDGER# read. A new reader that bypasses the door would bypass both filters."""
    readers = {
        "lambdas/content/story_pipeline.py": "story_ledger.latest_visible(",
        "lambdas/emails/wednesday_chronicle_lambda.py": "story_ledger.latest_visible(",
    }
    for rel, door in readers.items():
        src = open(os.path.join(_REPO, rel), encoding="utf-8").read()
        assert door in src, rel
        assert '"LEDGER#' not in src and "'LEDGER#" not in src, f"{rel} reads LEDGER# rows directly"


# ── acceptance 3: continuity — every open thread is picked up next installment ─


def test_next_weeks_budget_must_account_for_every_open_thread_and_the_open_bet(monkeypatch):
    t = _wire(monkeypatch)
    _publish(t, 3, "2026-09-22", "recovery >= 70 on 4 of 7 days")
    prev = story_ledger.latest_visible(t, PK, "2026-09-29")
    silent = {"lead": {"thread_id": "new"}, "thread_actions": [], "bet_scored": {"result": "none"}}
    findings = story_ledger.continuity_findings(prev, silent, 4)
    assert any("the_streak" in f and "not accounted for" in f for f in findings)
    assert any("bet" in f and "does not score" in f for f in findings)
    for act in ("advance", "resolve", "retire"):
        ok = {**silent, "thread_actions": [{"thread_id": "the_streak", "action": act}], "bet_scored": {"result": "right"}}
        assert story_ledger.continuity_findings(prev, ok, 4) == [], act


def test_a_thread_unmoved_for_three_installments_must_be_resolved_or_retired(monkeypatch):
    t = _wire(monkeypatch)
    _publish(t, 1, "2026-09-08", "b")  # the_streak opened week 1
    prev = story_ledger.latest_visible(t, PK, "2026-09-29")
    held = {
        "lead": {"thread_id": "x"},
        "thread_actions": [{"thread_id": "the_streak", "action": "hold"}],
        "bet_scored": {"result": "right"},
        "bets_scored": [{"bet_week": 1, "result": "right"}],
    }
    assert story_ledger.continuity_findings(prev, held, 3) == []  # two installments unmoved: a hold is still allowed
    assert any("stale thread 'the_streak'" in f for f in story_ledger.continuity_findings(prev, held, 4))
    retired = {**held, "thread_actions": [{"thread_id": "the_streak", "action": "retire"}]}
    assert story_ledger.continuity_findings(prev, retired, 4) == []
    led = story_ledger.apply_budget(prev, retired, week=4, date="2026-09-29", title="t")
    assert [x["status"] for x in led["threads"]] == ["retired"] and story_ledger.open_threads(led) == []


def test_the_publish_path_stores_the_ledger_round_trip_exactly(monkeypatch):
    t = _wire(monkeypatch)
    led = _publish(t, 3, "2026-09-22", "b")
    assert json.loads(t.rows[(PK, "LEDGER#2026-09-22")]["ledger_json"]) == json.loads(json.dumps(led))
