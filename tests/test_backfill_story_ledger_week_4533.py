"""tests/test_backfill_story_ledger_week_4533.py — the legacy-installment ledger backfill (#4533, #4914).

A wk5 ledger row + a legacy wk6 installment in a fake table. The derived row carries every wk5 thread with a status, scores
the open HRV bet only from what the text states, flags what it could not derive, applies idempotently and writes nothing on
a dry run.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import backfill_story_ledger_week as bf  # noqa: E402
from content import story_ledger  # noqa: E402

PK = bf.PK
CYCLE = "17"
ROSTER = [{"coach_id": "nutrition_coach", "name": "Marcus Webb"}, {"coach_id": "sleep_coach", "name": "Lisa Park"}]

TEXT = """"The Quiet Accumulation"

The waypoint ladder is a math problem now.

The HRV promise from last week is now scoreable. The 7-day rolling average through Tuesday sits at 55.8 milliseconds, against 55.0.

> Marcus Webb, when I reached him this week, said protein has to lead.
"""


def _thread(tid, status="advanced", last=5):
    return {"id": tid, "title": tid.replace("_", " ").title(), "opened_week": 0, "status": status, "last_week": last}


def _wk5(bet_metric="hrv_mean_ms"):
    return {
        "week": 5,
        "date": "2026-10-06",
        "threads": [_thread("alpha"), _thread("beta", last=4), _thread("gamma", "resolved", 3)],
        "bets": [
            {
                "claim": "HRV",
                "metric": bet_metric,
                "rule": "7-day mean HRV for the window ending 2026-10-13 >= 50 ms",
                "week": 5,
                "result": "open",
            }
        ],
        "featured": [{"week": 5, "coach_id": "sleep_coach"}],
        "leads": [{"week": 5, "thread_id": "alpha", "angle": "a"}],
        "beats": [{"week": 5, "beat": "b"}],
        "arcs": {"sleep_coach": "x"},
        "titles": [{"week": 5, "date": "2026-10-06", "title": "Park's Blind Spot"}],
        "asks": [{"coach_id": "nutrition_coach", "ask": "Log dinner five nights", "week": 5, "status": "open", "id": "ask-deadbeef"}],
        "spine": {"season_question": "q"},
    }


class _Client:
    class exceptions:
        pass


class _Cond(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class _Table:
    def __init__(self, ledger=None, text=TEXT, status="published"):
        self.rows = {
            (PK, "DATE#2026-10-13"): {
                "pk": PK,
                "sk": "DATE#2026-10-13",
                "status": status,
                "week_number": 6,
                "title": "The Quiet Accumulation",
                "content_markdown": text,
            }
        }
        if ledger is not None:
            self.rows[(PK, "LEDGER#2026-10-06")] = story_ledger.ledger_row(PK, ledger, cycle=CYCLE) | {"phase": "experiment"}
        self.puts = 0

    def get_item(self, Key):
        r = self.rows.get((Key["pk"], Key["sk"]))
        return {"Item": r} if r else {}

    def query(self, KeyConditionExpression, ScanIndexForward=True):
        sks = sorted((k[1] for k in self.rows if k[1].startswith("LEDGER#")), reverse=True)
        return {"Items": [self.rows[(PK, s)] for s in sks]}

    def put_item(self, Item, ConditionExpression=None):
        if ConditionExpression and (Item["pk"], Item["sk"]) in self.rows:
            raise _Cond()
        self.puts += 1
        self.rows[(Item["pk"], Item["sk"])] = Item


@pytest.fixture(autouse=True)
def _roster(monkeypatch):
    from content import story_dossier

    monkeypatch.setattr(story_dossier, "roster", lambda: ROSTER)
    from experiment import phase_taxonomy

    monkeypatch.setattr(phase_taxonomy, "experiment_stamp_for", lambda pk, sk="", **k: {"phase": "experiment", "cycle": 17})


def test_every_wk5_open_thread_is_accounted_for_with_a_status():
    led, _row = bf.build(_Table(_wk5()), 6, "2026-10-13", cycle=CYCLE)
    by = {t["id"]: t for t in led["threads"]}
    assert set(by) == {"alpha", "beta", "gamma"}
    for tid in ("alpha", "beta"):
        assert by[tid]["status"] == "advanced" and by[tid]["wk6_accounting"]["backfilled"] is True
        assert by[tid]["wk6_accounting"]["source"] == "legacy-installment"
    assert by["alpha"]["last_week"] == 5 and by["beta"]["last_week"] == 4  # held, never claimed advanced
    assert by["gamma"]["status"] == "resolved" and "wk6_accounting" not in by["gamma"]
    assert by["alpha"]["wk6_accounting"]["mentioned_in_text"] is False


def test_the_derived_row_passes_the_desks_own_continuity_check_and_the_row_shape():
    prev = _wk5()
    led, row = bf.build(_Table(prev), 6, "2026-10-13", cycle=CYCLE)
    assert row["sk"] == "LEDGER#2026-10-13" and row["record_type"] == "story_ledger" and row["cycle"] == CYCLE
    assert json.loads(row["ledger_json"])["week"] == 6
    assert led["titles"][-1] == {"week": 6, "date": "2026-10-13", "title": "The Quiet Accumulation"}
    assert led["asks"] == prev["asks"]  # carried unchanged — no carried_weeks increment
    assert led["leads"][-1]["thread_id"] is None and led["leads"][-1]["backfilled"] is True
    assert led["backfill"]["backfilled"] is True and "lead.thread_id" in led["backfill"]["underived"]


def test_the_open_hrv_bet_is_scored_from_the_stated_average_and_featured_from_the_blockquote():
    led, _ = bf.build(_Table(_wk5()), 6, "2026-10-13", cycle=CYCLE)
    bet = led["bets"][0]
    assert bet["result"] == "right" and bet["scored_week"] == 6 and bet["backfilled"] is True and "55.8" in bet["verdict_note"]
    assert [f["coach_id"] for f in led["featured"] if f["week"] == 6] == ["nutrition_coach"]


def test_a_bet_the_text_does_not_state_stays_open_and_is_flagged():
    led, _ = bf.build(_Table(_wk5(), text=TEXT.replace("7-day rolling average", "weekly figure")), 6, "2026-10-13", cycle=CYCLE)
    assert led["bets"][0]["result"] == "open"
    assert any("stays open" in u for u in led["backfill"]["underived"])
    led2, _ = bf.build(_Table(_wk5(bet_metric="recovery")), 6, "2026-10-13", cycle=CYCLE)
    assert led2["bets"][0]["result"] == "open"


def test_a_failed_bound_scores_wrong():
    led, _ = bf.build(_Table(_wk5(), text=TEXT.replace("55.8", "44.1")), 6, "2026-10-13", cycle=CYCLE)
    assert led["bets"][0]["result"] == "wrong"


def test_apply_is_idempotent():
    t = _Table(_wk5())
    _led, row = bf.build(t, 6, "2026-10-13", cycle=CYCLE)
    assert bf.write(t, row) is True
    assert bf.write(t, row) is False  # attribute_not_exists: the second apply is a no-op
    assert t.puts == 1
    assert story_ledger.latest_visible(t, PK, "2026-10-20", cycle=CYCLE)["week"] == 6  # the writers' own read door sees it


def test_dry_run_writes_nothing(monkeypatch, capsys):
    t = _Table(_wk5())

    class _Res:
        def Table(self, _):
            return t

    import boto3

    monkeypatch.setattr(boto3, "resource", lambda *a, **k: _Res())
    monkeypatch.setattr(story_ledger, "current_cycle", lambda: CYCLE)
    assert bf.main(["--week", "6", "--date", "2026-10-13", "--dry-run"]) == 0
    assert t.puts == 0 and "DRY RUN" in capsys.readouterr().out
    assert bf.main(["--week", "6", "--date", "2026-10-13", "--apply"]) == 0 and t.puts == 1
    assert bf.main(["--week", "6", "--date", "2026-10-13", "--apply"]) == 0 and t.puts == 1  # existing row short-circuits


@pytest.mark.parametrize(
    "table",
    [_Table(None), _Table(_wk5(), status="draft"), _Table({**_wk5(), "week": 3})],
    ids=["no-prev-row", "unpublished", "chain-gap"],
)
def test_preconditions_refuse(table):
    with pytest.raises(bf.BackfillError):
        bf.build(table, 6, "2026-10-13", cycle=CYCLE)
