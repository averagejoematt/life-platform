"""tests/test_advice_queue.py — `get_advice_link_queue` is read-only, private-free, shaped and capped.

What each test holds:
  READ-ONLY     the module makes no DynamoDB write call (AST), the run writes nothing to the fake table, the
                audit classifies the tool as a read, and the module never names the ADVICELINK# family.
  PRIVATE-FREE  seeded journal / State of Mind / video-diary sentinels never reach the answer: the journal habits
                drop out of Habitify, a check-in driven by a private or mixed source is left out, and no private
                partition is ever queried. The MUST-FAIL CONTROL runs the same detector over a build whose
                Habitify filter is bypassed and requires it to fire.
  SHAPE + CAP   most answerable first, same-window ids never called links, context labelled, every list and the
                whole payload bounded.
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "lambdas"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fakes import FakeDdbTable  # noqa: E402

import mcp.tools_advice_queue as taq  # noqa: E402

MODULE = ROOT / "mcp" / "tools_advice_queue.py"
TODAY = "2026-11-11"
JOURNAL_HABIT_ID = "99A94E6D-3D82-4BE9-85EF-8858CB4BA340"  # Morning Journal (activity_publication.HABIT_FAMILIES)
PUBLIC_HABIT_ID = "1427C438-3012-47B6-846D-3CAEF84F4F9A"  # one of PUBLIC_HABIT_IDS
SENTINELS = ("SENTINEL_JOURNAL", "SENTINEL_SOM", "SENTINEL_DIARY")
PRIVATE_PKS = ("SOURCE#notion", "SOURCE#state_of_mind", "SOURCE#journal", "SOURCE#diary", "SOURCE#video_diary", "SOURCE#vlog")


# ── the fake table: evaluates the real boto3 Key conditions (eq / begins_with / between) ─────────────


def _key_parts(cond):
    pk, pred = None, None
    stack = [cond]
    while stack:
        c = stack.pop()
        expr = c.get_expression()
        op, vals = expr["operator"], expr["values"]
        if op == "AND":
            stack.extend(vals)
        elif op == "=":
            pk = vals[1]
        elif op == "begins_with":
            pred = lambda s, p=vals[1]: s.startswith(p)  # noqa: E731
        elif op == "BETWEEN":
            pred = lambda s, lo=vals[1], hi=vals[2]: lo <= s <= hi  # noqa: E731
    return pk, pred


def _query_hook(table, **kwargs):
    pk, pred = _key_parts(kwargs["KeyConditionExpression"])
    rows = [r for (p, s), r in table.store.items() if p == pk and (pred is None or pred(s))]
    if "#phase" in (kwargs.get("FilterExpression") or ""):
        rows = [r for r in rows if r.get("phase") in (None, "experiment")]
    return {"Items": sorted(rows, key=lambda r: r["sk"])}


def _ask(coach, cid, created, due, text, status="pending", **extra):
    return {
        "pk": f"COACH#{coach}",
        "sk": f"COMMITMENT#{cid}",
        "commitment_id": cid,
        "coach_id": coach,
        "created_date": created,
        "due_date": due,
        "commitment_natural": text,
        "status": status,
        "phase": "experiment",
        **extra,
    }


def _rows(n_extra_asks: int = 0):
    rows = [
        _ask("sleep_coach", "commit_20261102_lights_out", "2026-11-02", "2026-11-09", "Lights out by 22:30 for a week"),
        _ask("nutrition_coach", "commit_20261101_protein", "2026-11-01", "2026-11-08", "Protein at breakfast"),
        _ask("mind_coach", "commit_20261030_walk", "2026-10-30", "2026-11-06", "A ten-minute walk after lunch"),
        _ask("physical_coach", "commit_20260901_old", "2026-08-25", "2026-09-01", "Out of window"),
        _ask("sleep_coach", "commit_20261103_pilot", "2026-11-03", "2026-11-10", "Wiped cycle", phase="pilot"),
        # his words
        {"pk": "USER#matthew#SOURCE#decisions", "sk": "DECISION#2026-11-05T07:00:00Z", "date": "2026-11-05", "decision": "Bed by 10:30"},
        {
            "pk": "USER#matthew#SOURCE#owner_words",
            "sk": "WORDS#2026-11-04#aaaaaaaaaaaa",
            "date": "2026-11-04",
            "text": "Slept better this week.",
            "verdict": "clean",
        },
        {
            "pk": "USER#matthew#SOURCE#owner_words",
            "sk": "WORDS#2026-11-04#bbbbbbbbbbbb",
            "date": "2026-11-04",
            "text": "held words",
            "verdict": "held",
        },
        {
            "pk": "COACH#sleep_coach",
            "sk": "CHECKIN#2026-11-06#11111111",
            "status": "answered",
            "answered_at": "2026-11-06T15:00:00Z",
            "question": "How are nights?",
            "answer": "Mostly in bed by 10:30.",
        },
        # private-driven check-ins: must never appear
        {
            "pk": "COACH#mind_coach",
            "sk": "CHECKIN#2026-11-05#22222222",
            "status": "answered",
            "answered_at": "2026-11-05T15:00:00Z",
            "source_key": "notion",
            "question": "Journaling?",
            "answer": "SENTINEL_JOURNAL",
        },
        {
            "pk": "COACH#mind_coach",
            "sk": "CHECKIN#2026-11-05#33333333",
            "status": "answered",
            "answered_at": "2026-11-05T16:00:00Z",
            "source_key": "apple_health",
            "question": "Mood logging?",
            "answer": "SENTINEL_SOM",
        },
        {
            "pk": "COACH#mind_coach",
            "sk": "CHECKIN#2026-11-05#44444444",
            "status": "answered",
            "answered_at": "2026-11-05T17:00:00Z",
            "source_key": "video_diary",
            "question": "Diary?",
            "answer": "SENTINEL_DIARY",
        },
        # private partitions seeded so a stray read WOULD find them
        {"pk": "USER#matthew#SOURCE#notion", "sk": "DATE#2026-11-05", "text": "SENTINEL_JOURNAL"},
        {"pk": "USER#matthew#SOURCE#state_of_mind", "sk": "DATE#2026-11-05", "label": "SENTINEL_SOM"},
        {"pk": "USER#matthew", "sk": "PROFILE#v1", "habit_registry": {}},
    ]
    for i in range(n_extra_asks):
        rows.append(_ask("explorer_coach", f"commit_2026110{i % 9}_extra_{i}", "2026-11-01", "2026-11-0" + str(2 + i % 7), "x" * 900))
    return rows


def _context_rows(source, start, end):
    days = [f"2026-11-{d:02d}" for d in range(1, 12) if start <= f"2026-11-{d:02d}" <= end]
    if source == "hevy":
        return [
            {
                "sk": f"DATE#{d}#WORKOUT#w{d}",
                "date": d,
                "title": "Upper",
                "duration_sec": 3600,
                "set_count": 20,
                "total_volume_kg": 5000,
                "description": "SENTINEL_DIARY",
                "owner_session_note": "SENTINEL_DIARY",
            }
            for d in days
        ]
    if source == "macrofactor":
        return [{"sk": f"DATE#{d}", "date": d, "total_calories_kcal": 2100, "total_protein_g": 180, "entries_count": 9} for d in days]
    if source == "habitify":
        return [
            {
                "sk": f"DATE#{d}",
                "date": d,
                "habit_statuses": {
                    "SENTINEL_JOURNAL": {"status": "completed", "habit_id": JOURNAL_HABIT_ID},
                    "Walk": {"status": "completed", "habit_id": PUBLIC_HABIT_ID, "notes": "SENTINEL_JOURNAL"},
                    "Unclassified new habit": {"status": "completed", "habit_id": "NOT-A-KNOWN-ID"},
                },
            }
            for d in days
        ]
    raise AssertionError(f"the tool read an unexpected source: {source}")


@pytest.fixture
def run(monkeypatch):
    def _run(args=None, rows=None):
        t = FakeDdbTable(rows=rows if rows is not None else _rows(), query_hook=_query_hook)
        sources = []

        def fake_query_source(source, start, end, **kw):
            sources.append(source)
            return _context_rows(source, start, end)

        monkeypatch.setattr(taq, "_table_ref", t)
        monkeypatch.setattr(taq, "query_source", fake_query_source)
        monkeypatch.setattr(taq, "pacific_today", lambda: TODAY)
        res = taq.tool_get_advice_link_queue(args or {})
        return res, t, sources

    return _run


def _leaks(payload) -> list:
    blob = json.dumps(payload, default=str)
    return [s for s in SENTINELS if s in blob]


# ── READ-ONLY ───────────────────────────────────────────────────────────────────────────────────────

_WRITE_ATTRS = {"put_item", "update_item", "delete_item", "batch_writer", "batch_write_item", "transact_write_items"}


def test_the_module_makes_no_write_call_and_never_names_the_link_family():
    src = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = {c.func.attr for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
    assert not calls & _WRITE_ATTRS, calls & _WRITE_ATTRS
    assert "ADVICELINK" not in src and "advice_links" not in {
        a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names
    }, "the queue must not touch the link family — log_advice_link is the only writer"
    assert "log_advice_link(" not in src


def test_a_run_writes_nothing_and_is_classified_a_read(run):
    from mcp import audit
    from mcp.registry import TOOLS

    res, t, _ = run()
    assert t.puts == [] and t.updates == [] and t.deletes == []
    assert res["read_only"] is True
    assert TOOLS["get_advice_link_queue"]["fn"] is taq.tool_get_advice_link_queue
    assert not audit.is_write_tool("get_advice_link_queue")


# ── PRIVATE-FREE (with the must-fail control) ──────────────────────────────────────────────────────


def test_no_private_source_reaches_the_answer(run):
    res, t, sources = run()
    assert _leaks(res) == [], _leaks(res)
    assert set(sources) == {"hevy", "macrofactor", "habitify"}
    queried = [str(_key_parts(q["KeyConditionExpression"])[0]) for q in t.query_calls]
    assert not [pk for pk in queried if any(p in pk for p in PRIVATE_PKS)], queried
    hab = res["context_not_evidence"]["habitify"]
    assert hab and all(d["completed"] == ["Walk"] and d["public_habits_tracked"] == 1 for d in hab)
    assert [c["id"] for c in res["his_words"]["checkin_answers"]] == ["CHECKIN#2026-11-06#11111111"]
    assert all("description" not in w and "owner_session_note" not in w for w in res["context_not_evidence"]["hevy"])


def test_control_the_detector_fires_when_the_habit_filter_is_bypassed(run, monkeypatch):
    """MUST FAIL: with the publication filter replaced by a pass-through, the journal habit leaks and the
    detector above catches it. If this control stops firing, the privacy test has gone vacuous."""
    monkeypatch.setattr(taq.AP, "public_habit_statuses", lambda statuses, registry=None: dict(statuses))
    res, _, _ = run()
    assert "SENTINEL_JOURNAL" in _leaks(res)


def test_control_the_detector_fires_when_the_checkin_screen_is_bypassed(run, monkeypatch):
    monkeypatch.setattr(taq, "checkin_is_shareable", lambda item: True)
    res, _, _ = run()
    assert {"SENTINEL_JOURNAL", "SENTINEL_SOM", "SENTINEL_DIARY"} <= set(_leaks(res))


def test_a_checkin_is_screened_by_its_driving_source():
    assert taq.checkin_is_shareable({"source_key": "measurements"})
    assert taq.checkin_is_shareable({})  # a rotation question names no source
    for src in ("notion", "state_of_mind", "apple_health", "computed_metrics", "video_diary", "never_classified"):
        assert not taq.checkin_is_shareable({"source_key": src}), src


# ── SHAPE + CAP ─────────────────────────────────────────────────────────────────────────────────────


def test_shape_most_answerable_first_and_nothing_called_a_link(run):
    res, _, _ = run()
    assert res["window"] == {"days": 14, "asks_due_from": "2026-10-28", "asks_due_to": TODAY, "his_words_from": "2026-10-30"}
    ids = [a["ask_id"] for a in res["asks"]]
    # out-of-window and wiped-cycle asks are not asks in this window
    assert ids == ["commit_20261102_lights_out", "commit_20261101_protein", "commit_20261030_walk"], ids
    top = res["asks"][0]
    assert top["same_window_ids"] == {
        "checkin_answers": ["CHECKIN#2026-11-06#11111111"],
        "decisions": ["DECISION#2026-11-05T07:00:00Z"],
        "owner_notes": ["WORDS#2026-11-04#aaaaaaaaaaaa"],
    }
    assert top["answerability"] == 6
    assert set(top) == {
        "coach_id",
        "coach",
        "ask_id",
        "asked_on",
        "due",
        "ask",
        "grader_status",
        "same_window_ids",
        "answerability",
        "your_answer",
    }
    assert all(a["your_answer"] is None for a in res["asks"]), "no answer recorded in the fixture: none is shown, none proposed"
    assert res["his_words"]["owner_notes_not_shown"] == 1 and len(res["his_words"]["owner_notes"]) == 1
    assert res["context_not_evidence"]["label"].startswith("context, not evidence")
    assert "not a link" in res["how_to_record"]
    # how_to_record names the vocabulary he answers in; nothing else in the answer spells (proposes) a state
    blob = json.dumps({k: v for k, v in res.items() if k != "how_to_record"})
    for state in ("acted_on", "declined", "partially_followed", "not_yet_decided"):
        assert state not in blob


def test_one_coach_and_a_bad_coach(run):
    res, _, _ = run({"coach_id": "sleep"})
    assert [a["coach_id"] for a in res["asks"]] == ["sleep_coach"]
    bad, _, _ = run({"coach_id": "dr_nobody"})
    assert "error" in bad


def test_every_list_and_the_whole_payload_are_capped(run):
    res, _, _ = run({"days": 999, "max_asks": 999}, rows=_rows(n_extra_asks=80))
    assert res["window"]["days"] == taq.MAX_DAYS
    assert res["asks_total"] == 83
    assert res["asks_shown"] == len(res["asks"]) <= taq.MAX_ASKS
    assert res["truncated"]["asks"] is True
    assert all(len(a["ask"]) <= taq.ASK_CHARS for a in res["asks"])
    assert len(json.dumps(res, default=str)) <= taq.MAX_PAYLOAD_CHARS


def test_cap_payload_trims_context_before_asks():
    out = {
        "asks": [{"ask": "a" * 200} for _ in range(5)],
        "truncated": {"asks": False, "context": False},
        "context_not_evidence": {"hevy": [{"x": "y" * 200} for _ in range(10)], "macrofactor": [], "habitify": []},
    }
    taq.cap_payload(out, limit=1500)
    assert out["truncated"]["context"] is True and out["truncated"]["asks"] is False
    assert len(out["asks"]) == 5 and len(json.dumps(out)) <= 1500


def test_his_current_answer_rides_the_ask_and_answered_asks_go_last():
    """Owner-side only: the current state (not_yet_decided included) and the revision count, never the note."""
    asks = [
        {"coach_id": "sleep_coach", "ask_id": "commit_20261102_a", "asked_on": "", "due": "2026-11-09"},
        {"coach_id": "sleep_coach", "ask_id": "commit_20261102_b", "asked_on": "", "due": "2026-11-08"},
        {"coach_id": "sleep_coach", "ask_id": "commit_20261102_c", "asked_on": "", "due": "2026-11-07"},
    ]
    answers = {
        ("sleep_coach", "commit_20261102_a"): {"state": "acted_on", "recorded_at": "2026-11-10T00:00:00.000Z", "revisions": 2},
        ("sleep_coach", "commit_20261102_b"): {"state": "not_yet_decided", "recorded_at": "2026-11-10T00:00:00.000Z", "revisions": 1},
    }
    ranked = taq.rank_asks(asks, [], [], [], answers)
    assert [a["ask_id"] for a in ranked] == ["commit_20261102_b", "commit_20261102_c", "commit_20261102_a"]
    assert ranked[2]["your_answer"] == {"state": "acted_on", "recorded_at": "2026-11-10T00:00:00.000Z", "revisions": 2}
    assert ranked[1]["your_answer"] is None
