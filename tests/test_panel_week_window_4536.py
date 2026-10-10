"""tests/test_panel_week_window_4536.py — #4536: the Panel writes episode N from week N, and only from this cycle.

Three contracts, each with a mutation control:

  1. A tombstoned, other-phase or pre-genesis state row is never read — the series state (`_state_read`), the
     show memory (`SHOW#memory`) and Elena's host state (`STANCE#latest` + `THREAD#`).
  2. `{"week": N, "dry_run": true}` selects the post by week number; coach reads and presence are bounded to the
     week's last day; an earlier week never advances the series state, memory or bet ledger; the feed is ordered
     by date; a named-week run notifies no one.
  3. A desk bet is registered only with a gradable rule, and the next episode scores it from the season ledger
     (`LEDGER#{date}`), never from the writer's own say-so.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta

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

from boto3.dynamodb.conditions import ConditionExpressionBuilder  # noqa: E402
from common.constants import EXPERIMENT_START_DATE  # noqa: E402
from emails import (
    coach_panel_podcast_lambda as panel,  # noqa: E402
    podcast_script_v2 as psv2,  # noqa: E402
)

desk = panel._panel_desk()

GENESIS = date.fromisoformat(EXPERIMENT_START_DATE)
PRE_GENESIS = (GENESIS - timedelta(days=60)).isoformat()
WK = {n: (GENESIS + timedelta(days=7 * n - 4)).isoformat() for n in range(1, 6)}  # a week-end date per week, all post-genesis
TOMB = {"tombstone": True, "phase": "pilot"}


def _key_values(cond) -> list:
    """The literal values a boto3 key condition carries (pk, then the sk bound(s))."""
    built = ConditionExpressionBuilder().build_expression(cond, is_key_condition=True)
    return list(built.attribute_value_placeholders.values())


class _Table:
    """A fake table: get_item by key, query honouring the key condition's begins_with/between sk bounds."""

    def __init__(self, rows=None):
        self.rows = {(r["pk"], r["sk"]): r for r in (rows or [])}
        self.gets, self.queries, self.puts = [], [], []

    def get_item(self, Key=None, **_):
        self.gets.append(Key)
        it = self.rows.get((Key["pk"], Key["sk"]))
        return {"Item": it} if it is not None else {}

    def query(self, **kw):
        self.queries.append(kw)
        vals = _key_values(kw["KeyConditionExpression"])
        pk, bounds = vals[0], vals[1:]
        items = [r for (p, s), r in self.rows.items() if p == pk]
        if len(bounds) == 2:
            items = [r for r in items if bounds[0] <= r["sk"] <= bounds[1]]
        elif len(bounds) == 1:
            items = [r for r in items if r["sk"].startswith(bounds[0])]
        items.sort(key=lambda r: r["sk"], reverse=kw.get("ScanIndexForward", True) is False)
        return {"Items": items[: kw.get("Limit", len(items))]}

    def put_item(self, Item=None, **_):
        self.puts.append(Item)
        self.rows[(Item["pk"], Item["sk"])] = Item


class _S3:
    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.puts = []

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)
        body = self.objects[Key]

        class _B:
            def read(self_inner):
                return body.encode("utf-8") if isinstance(body, str) else body

        return {"Body": _B()}

    def put_object(self, Bucket, Key, Body, **_):
        self.puts.append(Key)
        self.objects[Key] = Body


def _state_row(state: dict, **extra) -> dict:
    return {"pk": panel.PANEL_STATE_PK, "sk": panel.PANEL_STATE_SK, "state_json": json.dumps(state), **extra}


# ── 1. tombstone-, phase- and cycle-filtered state reads ─────────────────────────────────────────────────


def test_state_read_never_returns_a_tombstoned_other_phase_or_pre_genesis_row(monkeypatch):
    live = {"open_bet": "this cycle's bet", "last_episode": {"week": 3}}
    for hidden in (
        _state_row({"open_bet": "a July bet"}, **TOMB),
        _state_row({"open_bet": "a July bet"}, phase="cycle5"),
        _state_row({"open_bet": "a July bet"}, phase="experiment", updated=PRE_GENESIS),  # a previous cycle the reset never tagged
    ):
        monkeypatch.setattr(panel, "table", _Table([hidden]))
        assert panel._state_read() == {}, hidden
    # mutation control: the same row, written this cycle, is read
    monkeypatch.setattr(panel, "table", _Table([_state_row(live, phase="experiment", updated=WK[3])]))
    assert panel._state_read() == live


def test_show_memory_ignores_a_wiped_or_previous_cycle_row():
    def mem(**extra):
        return _Table(
            [
                {
                    "pk": "USER#matthew#SOURCE#panelcast",
                    "sk": psv2.SHOW_MEMORY_SK,
                    "callbacks": [{"week": 9, "title": "a cycle-5 episode"}],
                    "guest_history": [{"week": 9, "coach_id": "sleep_coach"}],
                    **extra,
                }
            ]
        )

    log = panel.logger
    assert psv2.load_show_memory(mem(**TOMB), "matthew", log) == {"callbacks": [], "guest_history": []}
    assert psv2.load_show_memory(mem(phase="experiment", updated_at=f"{PRE_GENESIS}T00:00:00Z"), "matthew", log)["callbacks"] == []
    live = psv2.load_show_memory(mem(phase="experiment", updated_at=f"{WK[2]}T00:00:00Z"), "matthew", log)
    assert live["callbacks"][0]["title"] == "a cycle-5 episode"  # mutation control


def test_show_memory_write_carries_the_cycle_stamp():
    t = _Table()
    psv2.write_show_memory(t, "matthew", panel.logger, 3, "EP3", "q", "sleep_coach", "Lisa Park", "")
    assert t.puts and t.puts[0].get("phase") == "experiment", "an unstamped SHOW#memory row is invisible to the reset's wipe"


def test_elena_host_state_skips_a_tombstoned_stance_and_threads(monkeypatch):
    stance = {"pk": "PERSONA#elena", "sk": "STANCE#latest", "headline_stance": "the wiped cycle's read"}
    thread = {"pk": "PERSONA#elena", "sk": "THREAD#2026-07-01#old", "status": "open", "summary": "the wiped cycle's thread"}
    monkeypatch.setattr(panel, "table", _Table([{**stance, **TOMB}, {**thread, **TOMB}]))
    assert panel._elena_host_state() == ""
    monkeypatch.setattr(panel, "table", _Table([{**stance, "phase": "experiment"}, {**thread, "phase": "experiment"}]))
    out = panel._elena_host_state()
    assert "the wiped cycle's read" in out and "the wiped cycle's thread" in out  # mutation control


# ── 2. the week-window mode ──────────────────────────────────────────────────────────────────────────────


def _posts():
    return [
        {"week": 3, "date": PRE_GENESIS, "title": "a previous cycle's week 3"},
        {"week": 2, "date": WK[2], "title": "Week 2"},
        {"week": 3, "date": WK[3], "title": "Week 3"},
        {"week": 4, "date": WK[4], "title": "Week 4"},
    ]


DESK_EP = {
    "title": "The Strap Said Seventy",
    "excerpt": "x",
    "turns": [{"speaker": "elena", "line": "Day 10."}, {"speaker": "coach", "line": "Sleep held."}],
    "guest": {"name": "Lisa Park", "coach_id": "sleep_coach", "persona_id": "sleep_coach"},
    "bet": {"claim": "recovery at or above 70 on Tuesday", "metric": "whoop.recovery_score", "rule": ">= 70", "window_days": 7},
}


def _wire_week_run(monkeypatch, state):
    rows = [
        _state_row(state, phase="experiment", updated=WK[4]),
        {"pk": "USER#matthew#SOURCE#chronicle", "sk": f"DATE#{WK[3]}", "desk_episode_json": json.dumps(DESK_EP), "phase": "experiment"},
    ]
    t = _Table(rows)
    monkeypatch.setattr(panel, "table", t)
    monkeypatch.setattr(panel, "_published_posts", _posts)
    monkeypatch.setattr(panel, "_episode_exists", lambda week: None)
    import ai.budget_guard as bg

    monkeypatch.setattr(bg, "current_tier", lambda: 0)
    return t


def test_week_dry_run_selects_the_post_by_number_and_neither_advances_nor_notifies(monkeypatch):
    t = _wire_week_run(monkeypatch, {"last_episode": {"week": 4}, "bet_ledger": []})
    body = json.loads(panel.lambda_handler({"week": 3, "dry_run": True}, None)["body"])
    assert body["week"] == 3 and body["would"] == "PUBLISH" and body["date"] == WK[3], body  # this cycle's wk3, not the old one
    assert body["advance_state"] is False, "an earlier week must not advance the state/bets/memory past week 4"
    assert body["notify"] is False, "a named-week run notifies no one"
    assert t.puts == [], "a dry run writes nothing"
    # mutation control: with no later episode on record, the same week advances; the scheduled run still notifies
    _wire_week_run(monkeypatch, {"last_episode": {"week": 2}, "bet_ledger": []})
    assert json.loads(panel.lambda_handler({"week": 3, "dry_run": True}, None)["body"])["advance_state"] is True
    monkeypatch.setattr(panel, "_published_posts", lambda: [p for p in _posts() if p["week"] == 3])
    assert json.loads(panel.lambda_handler({"dry_run": True}, None)["body"])["notify"] is True


def test_week_for_a_number_with_no_current_cycle_post_fails_loudly(monkeypatch):
    _wire_week_run(monkeypatch, {})
    out = panel.lambda_handler({"week": 9, "dry_run": True}, None)
    assert out["statusCode"] == 500 and "week 9" in out["body"]


def test_coach_reads_and_presence_stop_at_the_weeks_last_day(monkeypatch):
    cid = panel.persona_registry.OPERATIONAL_COACH_IDS[0]
    later = (date.fromisoformat(WK[3]) + timedelta(days=3)).isoformat()
    rows = [
        {"pk": f"COACH#{cid}", "sk": f"OUTPUT#{WK[3]}#daily", "summary": "in-week read", "phase": "experiment"},
        {"pk": f"COACH#{cid}", "sk": f"OUTPUT#{later}#daily", "summary": "a read from after the week ended", "phase": "experiment"},
        {"pk": "USER#matthew#SOURCE#engagement_state", "sk": f"DATE#{WK[3]}", "presence_class": "light", "phase": "experiment"},
    ]
    t = _Table(rows)
    monkeypatch.setattr(panel, "table", t)
    monkeypatch.setattr(panel, "_chronicle_md", lambda d: "")
    monkeypatch.setattr(panel.coach_derived_prose, "served_summary", lambda it: it.get("summary"))
    beats = panel._gather_week({"week": 3, "date": WK[3], "title": "Week 3"}, {})
    summaries = [c["summary"] for c in beats["coach_reads"] if c["id"] == cid]
    assert summaries == ["in-week read"], summaries
    assert {"pk": "USER#matthew#SOURCE#engagement_state", "sk": f"DATE#{WK[3]}"} in t.gets, "presence must be read as of the week end"
    assert not any(k.get("sk") == "STATE#current" for k in t.gets if "engagement_state" in k.get("pk", ""))
    # mutation control: reviewing the later week sees the later read
    later_beats = panel._gather_week({"week": 4, "date": later, "title": "Week 4"}, {})
    assert [c["summary"] for c in later_beats["coach_reads"] if c["id"] == cid] == ["a read from after the week ended"]


def test_the_feed_is_ordered_by_air_date(monkeypatch):
    s3 = _S3()
    monkeypatch.setattr(panel, "s3", s3)
    monkeypatch.setattr(panel, "_invalidate_cdn", lambda: None)
    eps = [
        {"week": 9, "date": PRE_GENESIS, "title": "EP9 · old cycle", "url": "/panelcast/wk9.mp3"},
        {"week": 2, "date": WK[2], "title": "EP2", "url": "/panelcast/wk2.mp3"},
        {"week": 3, "date": WK[3], "title": "EP3", "url": "/panelcast/wk3.mp3"},
    ]
    panel._write_indexes(eps)
    order = [e["week"] for e in json.loads(s3.objects["generated/panelcast/episodes.json"])["episodes"]]
    assert order == [3, 2, 9], order
    feed = s3.objects["generated/panelcast/feed.xml"]
    assert feed.index("wk3") < feed.index("wk2") < feed.index("wk9")


class _Log:
    def info(self, *a, **k):
        pass

    warning = info


def _desk_g(table, state, calls):
    s3 = _S3({"generated/panelcast/episodes.json": json.dumps({"episodes": [{"week": 4, "date": WK[4], "title": "EP4"}]})})
    return {
        "table": table,
        "USER_ID": "matthew",
        "logger": _Log(),
        "ELENA": "elena_voss",
        "persona_registry": panel.persona_registry,
        "_safety_gate": lambda line: [],
        "_dry": panel._dry,
        "_hold_and_alert": lambda *a, **k: calls.append("hold"),
        "_gemini_voice": lambda pid: "Kore",
        "WEEKLY_STYLE": "",
        "_publish_episode_audio": lambda week, audio: {"url": f"/panelcast/wk{week}.mp3", "bytes": 1, "duration_sec": 1},
        "s3": s3,
        "S3_BUCKET": "b",
        "PREFIX": "generated/panelcast",
        "_state_read": lambda: state,
        "_state_write": lambda st: calls.append(("state", st)),
        "_write_indexes": lambda eps: calls.append(("index", [e["week"] for e in eps])),
        "_write_show_memory": lambda *a: calls.append(("memory", a)),
        "_emit_published_metric": lambda: None,
        "_emit_outcome": lambda r: None,
        "_notify_new_episode": lambda rec: calls.append("notify"),
    }


def test_a_backfilled_earlier_week_publishes_its_row_but_leaves_state_and_notifies_no_one(monkeypatch):
    import ai.gemini_tts as gt

    monkeypatch.setattr(gt, "synthesize_dialogue", lambda *a, **k: b"RIFF")
    calls: list = []
    g = _desk_g(_Table(), {"last_episode": {"week": 4}, "bet_ledger": [{"week": 4, "bet": "b4", "outcome": "open"}]}, calls)
    desk.publish_desk_episode(3, {"week": 3, "date": WK[3], "backfill": True}, DESK_EP, False, _g=g)
    assert ("index", [4, 3]) in calls, calls  # the episode row is published, newest air date first
    assert not [c for c in calls if isinstance(c, tuple) and c[0] in ("state", "memory")], "state/memory advanced out of order"
    assert "notify" not in calls
    # mutation control: the in-order scheduled run advances and notifies
    calls.clear()
    g = _desk_g(_Table(), {"last_episode": {"week": 2}, "bet_ledger": []}, calls)
    desk.publish_desk_episode(3, {"week": 3, "date": WK[3]}, DESK_EP, False, _g=g)
    assert [c[0] for c in calls if isinstance(c, tuple)][:2] == ["state", "memory"] and "notify" in calls


def test_the_legacy_commit_leaves_state_alone_for_an_earlier_week():
    calls: list = []
    g = {"logger": _Log(), "_state_write": lambda st: calls.append("state"), "_write_show_memory": lambda *a: calls.append("memory")}
    script = {"open_bet": "b3", "last_bet_result": {"outcome": "won"}}
    beats = {"date": WK[3], "title": "Week 3", "guest": {"name": "Lisa Park"}}
    out = desk.commit_legacy(
        3, {"week": 3, "date": WK[3]}, [{"week": 4, "date": WK[4]}], {"last_episode": {"week": 4}}, script, beats, "h", "x", _g=g
    )
    assert [e["week"] for e in out] == [4, 3] and calls == []
    desk.commit_legacy(3, {"week": 3, "date": WK[3]}, [], {"last_episode": {"week": 2}}, script, beats, "h", "x", _g=g)
    assert calls == ["state", "memory"]  # mutation control


# ── 3. a gradable bet, scored from the season ledger ─────────────────────────────────────────────────────


def _ledger_row(bets, **extra):
    return {
        "pk": "USER#matthew#SOURCE#chronicle",
        "sk": f"LEDGER#{WK[4]}",
        "ledger_json": json.dumps({"week": 4, "date": WK[4], "bets": bets}),
        "phase": "experiment",
        **extra,
    }


def _publish_wk4(monkeypatch, table, bet):
    import ai.gemini_tts as gt

    monkeypatch.setattr(gt, "synthesize_dialogue", lambda *a, **k: b"RIFF")
    calls: list = []
    state = {"last_episode": {"week": 3}, "bet_ledger": [{"week": 3, "bet": "b3", "outcome": "open", "date": WK[3]}]}
    g = _desk_g(table, state, calls)
    desk.publish_desk_episode(4, {"week": 4, "date": WK[4]}, dict(DESK_EP, bet=bet), False, _g=g)
    return next(c[1] for c in calls if isinstance(c, tuple) and c[0] == "state")


def test_last_weeks_bet_is_scored_from_the_season_ledger_and_this_weeks_is_registered(monkeypatch):
    graded = _Table([_ledger_row([{"week": 3, "claim": "b3", "result": "right"}, {"week": 4, "claim": "c4", "result": "open"}])])
    st = _publish_wk4(monkeypatch, graded, DESK_EP["bet"])
    by_week = {b["week"]: b for b in st["bet_ledger"]}
    assert by_week[3]["outcome"] == "won", st["bet_ledger"]  # the ledger's verdict, not the writer's
    assert by_week[4] == {"week": 4, "bet": DESK_EP["bet"]["claim"], "outcome": "open", "date": WK[4]}
    assert st["open_bet"] == DESK_EP["bet"]["claim"]
    # mutation controls: a tombstoned ledger row grades nothing; a bet without a rule is not registered
    st = _publish_wk4(monkeypatch, _Table([_ledger_row([{"week": 3, "result": "right"}], **TOMB)]), DESK_EP["bet"])
    assert {b["week"]: b["outcome"] for b in st["bet_ledger"]}[3] == "open"
    st = _publish_wk4(monkeypatch, graded, {"claim": "a vibe, no rule"})
    assert [b["week"] for b in st["bet_ledger"]] == [3] and st["open_bet"] is None


def test_the_ledger_verdict_vocabulary_maps_onto_the_scoreboard():
    led = {"bets": [{"week": 1, "result": "wrong"}, {"week": 2, "result": "not_gradable"}, {"week": 3, "result": "open"}]}
    rows = [{"week": w, "bet": f"b{w}", "outcome": "open"} for w in (1, 2, 3)]
    out = {b["week"]: b["outcome"] for b in desk.score_bets(rows, led, 4, WK[4], None)}
    assert out == {1: "lost", 2: "none", 3: "open"}
