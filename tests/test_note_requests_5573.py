"""tests/test_note_requests_5573.py — Hevy notes that ask the platform for something (#5573).

Fixture = wire: `tests/fixtures/note_requests_5573/hevy_rows.json` is a field-projected copy of the live
`USER#matthew#SOURCE#hevy` rows carrying the three notes the issue quotes verbatim (read 2026-11-08). The negative
control is the issue's own: a plain form note, "felt off on rep 6", must not raise a request.

Clock: every function that reads "today" takes it as an argument here (`today=`/`now_iso=`), and the one path that
defaults it (the Lambda hook) is pinned by monkeypatching `common.pacific_time.pacific_today` (#4848).
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import pytest

for _k, _v in (("TABLE_NAME", "life-platform-test"), ("USER_ID", "matthew"), ("S3_BUCKET", "test-bucket"), ("AWS_REGION", "us-west-2")):
    os.environ.setdefault(_k, _v)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT))

from training import (
    form_cue_sheets as fcs,  # noqa: E402
    note_requests as nr,  # noqa: E402
    training_notes as tn,  # noqa: E402
)

FIX = json.loads((ROOT / "tests" / "fixtures" / "note_requests_5573" / "hevy_rows.json").read_text())["rows"]
TODAY = "2026-11-08"
NOW = "2026-11-08T18:00:00Z"
NEGATIVE_CONTROL = "felt off on rep 6"


def _row(date: str) -> dict:
    return copy.deepcopy(next(r for r in FIX if r["date"] == date))


def _items(date: str) -> list[dict]:
    r = _row(date)
    return tn.build_workout_note_items(r["date"], r["workout_uid"], r["exercises"], now_iso=NOW)


def _by_name(items: list[dict]) -> dict[str, dict]:
    return {it["exercise_name"]: it for it in items}


def _owner_request(item: dict) -> dict | None:
    return next((s for s in item["signals"] if s["class"] == "owner_request"), None)


class FakeTable:
    """The DynamoDB subset this path uses, with the two condition shapes it writes under evaluated for real."""

    def __init__(self):
        self.items: dict[tuple[str, str], dict] = {}
        self.puts = 0

    def get_item(self, Key):
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": copy.deepcopy(it)} if it else {}

    def put_item(self, Item, ConditionExpression=None):
        key = (Item["pk"], Item["sk"])
        if ConditionExpression is not None:
            expr = ConditionExpression.get_expression()
            op, vals = expr["operator"], expr["values"]
            cur = self.items.get(key)
            if op == "attribute_not_exists":
                ok = cur is None
            elif op == "=":
                ok = cur is not None and cur.get(vals[0].name) == vals[1]
            else:  # pragma: no cover — a new condition shape must be added here, not passed
                raise AssertionError(f"unhandled condition {op}")
            if not ok:
                raise type("ConditionalCheckFailedException", (Exception,), {})("ConditionalCheckFailed")
        self.items[key] = copy.deepcopy(Item)
        self.puts += 1

    def query(self, KeyConditionExpression, **kw):
        expr = KeyConditionExpression.get_expression()
        pk = expr["values"][0].get_expression()["values"][1]
        prefix = expr["values"][1].get_expression()["values"][1]
        return {"Items": [copy.deepcopy(v) for (p, s), v in self.items.items() if p == pk and s.startswith(prefix)]}

    def requests(self) -> dict[str, dict]:
        return {v["exercise_name"]: v for (p, s), v in self.items.items() if s.startswith(nr.REQUEST_SK_PREFIX)}


# ── the taxonomy amendment ──────────────────────────────────────────────────────────────────
def test_owner_request_is_in_the_locked_taxonomy_and_the_extractor_version_moved():
    """Mutation: drop the class from TAXONOMY (merge_signals then silently drops every owner_request signal)."""
    assert "owner_request" in tn.TAXONOMY
    assert tn.OWNER_REQUEST_SUBTYPES == nr.SUBTYPES == ("form_guidance", "question", "rule_request")
    assert tn.ALGO_VERSION >= "note-extractor@1.2.0"  # #5800 moved it again (1.3.0, pain severity)
    spec = (ROOT / "docs" / "specs" / "SPEC_HEVY_NOTES_FEEDBACK_LOOP_2026-06-21.md").read_text()
    assert "§5d" in spec and "owner_request" in spec, "the taxonomy is a Phase-0 lock: an added class is dated and argued in the spec"


# ── the three verbatim fixtures + the negative control (acceptance box 1) ───────────────────
def test_the_three_live_notes_are_detected_with_their_subtypes():
    """Mutation: reorder the precedence (the pushdown note carries 'form' AND '?'), or loosen the form_guidance
    rule to medium-without-ask — the pushdown note is a question, the lateral raise a form request."""
    got = {**_by_name(_items("2026-11-01")), **_by_name(_items("2026-10-25"))}
    subtypes = {name: (_owner_request(it) or {}).get("value", {}).get("subtype") for name, it in got.items()}
    assert subtypes == {
        "Lateral Raise (Machine)": "form_guidance",
        "Triceps Rope Pushdown": "question",
        "Farmers Walk": "rule_request",
    }
    # the class rides beside the existing ones — the lateral raise is still a form note, the walk still a logging quirk
    assert any(s["class"] == "form_technique" for s in got["Lateral Raise (Machine)"]["signals"])
    assert any(s["class"] == "logging_quirk" for s in got["Farmers Walk"]["signals"])


def test_negative_control_a_plain_form_note_raises_nothing():
    """The issue's negative control. It IS a form note (form_technique fires) and it asks for nothing."""
    rec = tn.extract_signals(NEGATIVE_CONTROL, llm_fn=None, date=TODAY)
    classes = {s["class"] for s in rec["signals"]}
    assert "form_technique" in classes and "owner_request" not in classes
    assert tn.owner_request_of(NEGATIVE_CONTROL) is None


def test_non_requests_stay_non_requests():
    """One test that reports every offender (a parametrized test is one census gate per parameter)."""
    notes = [
        "watched a youtube video on form and it helped",  # a medium + a topic, no ask
        "Also today i went lighter to really focus on form.",  # the pushdown note's own last sentence
        "L9? maybe L10 next time",  # a question mark after a number is a logging shrug, not a question
        "Different machine today",
    ]
    offenders = {n: tn.owner_request_of(n) for n in notes if tn.owner_request_of(n) is not None}
    assert not offenders, offenders


# ── raising the rows (acceptance boxes 2, 3, 5) ─────────────────────────────────────────────
def _raise(table, date, today=TODAY):
    return nr.raise_requests(table, _items(date), today=today, now_iso=NOW)


def test_each_request_writes_one_row_with_the_issue_fields():
    t = FakeTable()
    out = _raise(t, "2026-11-01")
    assert (out["requests"], out["raised"], out["failed"]) == (2, 2, 0)
    rows = t.requests()
    q = rows["Triceps Rope Pushdown"]
    assert q["pk"] == "USER#matthew#SOURCE#training_constraints"
    assert q["sk"] == "REQUEST#2026-11-01#4b137083-8c34-49b3-8609-bbef1a39f689#94B7239B#0"
    assert q["request_id"] == "2026-11-01#4b137083-8c34-49b3-8609-bbef1a39f689#94B7239B#0"
    assert (q["workout_id"], q["template_id"], q["exercise_name"]) == (
        "4b137083-8c34-49b3-8609-bbef1a39f689",
        "94B7239B",
        "Triceps Rope Pushdown",
    )
    assert q["note_raw"] == _row("2026-11-01")["exercises"][1]["notes"], "the note is stored verbatim"
    assert (q["subtype"], q["status"], q["detected_by"]) == ("question", "open", "deterministic")
    assert "answered_at" not in q and "reply" not in q, "code never answers a question"


def test_form_guidance_is_answered_once_with_a_labelled_cue_sheet_from_the_catalog():
    t = FakeTable()
    _raise(t, "2026-11-01")
    lr = t.requests()["Lateral Raise (Machine)"]
    assert (lr["status"], lr["channel"], lr["answered_at"]) == ("answered", "coach_packet", NOW)
    reply = lr["reply"]
    assert reply["kind"] == "form_cue_sheet" and reply["label"] == nr.GENERAL_GUIDANCE_LABEL
    assert reply["catalog"]["catalog_key"] == "lateral_raise_machine"  # the real config/movement_catalog.json entry
    assert reply["catalog"]["default_rep_range"] == [10, 15]
    sheet = reply["sheet"]
    assert sheet["pattern"] == "lateral_raise" and len(sheet["cues"]) == 3
    text = reply["text"]
    for part in (
        "Setup:",
        "Cue 1:",
        "Cue 2:",
        "Cue 3:",
        "Common fault:",
        "What right feels like:",
        nr.GENERAL_GUIDANCE_LABEL,
        nr.NO_VIDEO_LINE,
    ):
        assert part in text, part
    assert "http" not in text, "no link is offered without an owner-approved form_reference_urls entry"


def test_rule_request_is_a_drafted_story_never_filed():
    t = FakeTable()
    out = _raise(t, "2026-10-25")
    assert out["raised"] == 1
    fw = t.requests()["Farmers Walk"]
    assert (fw["subtype"], fw["status"], fw["channel"]) == ("rule_request", "answered", "coach_packet")
    assert fw["reply"]["kind"] == "story_draft" and "Not filed and not applied" in fw["reply"]["text"]
    assert "we should create a rule for that" in fw["reply"]["draft"]["body"], "the draft quotes his note verbatim"


def test_a_request_is_raised_once_and_never_rewritten():
    """Mutation: drop the attribute_not_exists condition — the second pass then re-opens/re-answers the rows."""
    t = FakeTable()
    _raise(t, "2026-11-01")
    before = copy.deepcopy(t.items)
    again = nr.raise_requests(t, _items("2026-11-01"), today=TODAY, now_iso="2026-11-09T00:00:00Z")
    assert (again["raised"], again["already"]) == (0, 2)
    assert t.items == before


def test_a_historical_note_raises_nothing():
    """A backfill over old history must never mint a queue of stale asks."""
    t = FakeTable()
    out = _raise(t, "2026-10-25", today="2026-11-20")  # 26 days later
    assert (out["requests"], out["historical"], out["raised"]) == (1, 1, 0) and not t.items


def test_form_guidance_on_a_movement_with_no_sheet_stays_open():
    t = FakeTable()
    items = tn.build_workout_note_items(
        "2026-11-07",
        "hevy:abc",
        [{"name": "Hack Squat", "template_id": "ZZZ", "notes": "can you send me a video on hack squat form"}],
        now_iso=NOW,
    )
    nr.raise_requests(t, items, today=TODAY, now_iso=NOW, movements={})
    row = t.requests()["Hack Squat"]
    assert (row["subtype"], row["status"]) == ("form_guidance", "open") and "no cue sheet" in row["reply_pending"]


def test_a_model_only_request_needs_a_subtype_and_confidence():
    base = {"date": "2026-11-07", "workout_uid": "hevy:w", "exercise_name": "X", "exercise_template": "T", "note_raw": "hmm"}
    low = dict(base, signals=[{"class": "owner_request", "confidence": 0.5, "value": {"subtype": "question"}}])
    bad = dict(base, signals=[{"class": "owner_request", "confidence": 0.9, "value": {"subtype": "wish"}}])
    good = dict(base, signals=[{"class": "owner_request", "confidence": 0.8, "value": {"subtype": "question"}}])
    assert nr.request_signal(low) is None and nr.request_signal(bad) is None
    assert nr.request_signal(good) == {"subtype": "question", "matched": [], "detected_by": "haiku"}


# ── the curated link rule ───────────────────────────────────────────────────────────────────
def test_only_an_owner_approved_https_link_is_ever_offered():
    entry = {
        "form_reference_urls": [
            {"url": "https://example.com/a", "approved_by_owner": "2026-11-08"},
            {"url": "https://example.com/b"},  # not approved
            {"url": "http://example.com/c", "approved_by_owner": "2026-11-08"},  # not https
            "https://example.com/d",  # a bare string carries no approval
        ]
    }
    assert nr.approved_reference_urls(entry) == ["https://example.com/a"]
    reply = nr.form_guidance_reply(
        "Lateral Raise (Machine)", "D5D0354D", {"k": {"title": "Lateral Raise (Machine)", "hevy_template_id_hint": "D5D0354D", **entry}}
    )
    assert "Owner-approved reference: https://example.com/a" in reply["text"] and nr.NO_VIDEO_LINE not in reply["text"]


def test_no_catalog_entry_carries_a_reference_link_yet():
    """The live state the 'no curated link' reply line describes. When the owner approves the first link this test is
    the reminder to check that the reply now carries it."""
    movements = json.loads((ROOT / "config" / "movement_catalog.json").read_text())["movements"]
    assert not [k for k, e in movements.items() if e.get("form_reference_urls")]


def test_every_cue_sheet_has_setup_three_cues_fault_and_feel():
    for pid in fcs.patterns():
        s = fcs._SHEETS[pid]
        assert s["setup"] and s["common_fault"] and s["feels_right"] and len(s["cues"]) == 3, pid
    assert fcs.pattern_of("Lateral Raise (Machine)") == "lateral_raise"
    assert fcs.pattern_of("Triceps Rope Pushdown") == "triceps_pushdown"
    assert fcs.pattern_of("Overhead Triceps Extension (Cable)") == "overhead_triceps_extension"
    assert fcs.pattern_of("Rear Delt Reverse Fly (Machine)") == "rear_delt_fly"
    for none in ("Lying Leg Curl (Machine)", "Wrist Curl", "Squat (Barbell)", ""):
        assert fcs.pattern_of(none) is None, none


# ── resolution: once, with channel + UTC instant (acceptance box 5) ─────────────────────────
def test_a_question_is_answered_once_by_the_chat_and_a_second_answer_is_refused():
    t = FakeTable()
    _raise(t, "2026-11-01")
    rid = t.requests()["Triceps Rope Pushdown"]["request_id"]
    out = nr.resolve(t, rid, status="answered", text="Evidence is mixed: ...", now_iso="2026-11-08T19:00:00Z")
    assert out["wrote"] and out["row"]["status"] == "answered"
    row = t.requests()["Triceps Rope Pushdown"]
    assert (row["channel"], row["answered_at"], row["reply"]["kind"]) == ("coach_chat", "2026-11-08T19:00:00Z", "coach_answer")
    assert "reply_pending" not in row
    again = nr.resolve(t, rid, status="declined", text="dup")
    assert not again["wrote"] and "already answered" in again["error"]


def test_a_raise_time_answer_cannot_be_answered_again_and_decline_needs_a_reason():
    t = FakeTable()
    _raise(t, "2026-11-01")
    lr = t.requests()["Lateral Raise (Machine)"]["request_id"]
    assert not nr.resolve(t, lr, status="answered", text="again")["wrote"]
    q = t.requests()["Triceps Rope Pushdown"]["request_id"]
    with pytest.raises(ValueError):
        nr.resolve(t, q, status="declined", text="  ")
    out = nr.resolve(t, "REQUEST#" + q, status="declined", text="asked and answered in chat on 11-02", now_iso="2026-11-08T19:00:00Z")
    assert out["wrote"] and t.requests()["Triceps Rope Pushdown"]["decline_reason"].startswith("asked and answered")
    assert not nr.resolve(t, "2026-01-01#nope#T#0", status="declined", text="x")["wrote"]


def test_the_store_refuses_a_racing_second_answer():
    """The open-check is the store's condition, not only the read: a row resolved between the read and the write."""
    t = FakeTable()
    _raise(t, "2026-11-01")
    rid = t.requests()["Triceps Rope Pushdown"]["request_id"]
    real_get = t.get_item

    def stale_get(Key):
        got = real_get(Key)
        t.items[(Key["pk"], Key["sk"])]["status"] = "answered"  # another writer lands after this read
        return got

    t.get_item = stale_get
    out = nr.resolve(t, rid, status="answered", text="x")
    assert not out["wrote"] and "another writer" in out["error"]


# ── the packet view: open list, overdue COUNT, recent replies (acceptance boxes 2, 5) ─────────
def test_view_counts_open_requests_past_seven_days_as_overdue():
    t = FakeTable()
    _raise(t, "2026-11-01")
    rows = list(t.items.values())
    on_day_7 = nr.view(rows, "2026-11-08")  # the 11-01 question is 7 days old: not yet overdue
    on_day_8 = nr.view(rows, "2026-11-09")
    assert (on_day_7["open_count"], on_day_7["overdue_count"]) == (1, 0)
    assert (on_day_8["open_count"], on_day_8["overdue_count"]) == (1, 1)
    assert on_day_8["open"][0]["note"].startswith("I have seen people suggesting")
    assert [r["subtype"] for r in on_day_7["answered_recent"]] == ["form_guidance"]
    assert on_day_7["answered_recent"][0]["reply"]["text"].startswith("Lateral Raise (Machine) — form cue sheet.")


def test_packet_field_and_capture_section_read_the_same_rows(monkeypatch):
    from mcp import tools_training_notes as ttn

    t = FakeTable()
    _raise(t, "2026-11-01")
    monkeypatch.setattr(ttn, "_note_request_rows", lambda: list(t.items.values()))
    value, status = ttn.note_requests_packet_field("2026-11-09")
    assert status["state"] == "measured" and value["overdue_count"] == 1 and "answer_request" in value["how_to_answer"]
    monkeypatch.setattr(ttn, "pacific_today", lambda: "2026-11-09")
    cap = ttn.note_requests_capture_section()
    assert (cap["count"], cap["overdue_count"], cap["answered_recent_count"]) == (1, 1, 1)
    assert "note" not in cap["items"][0], "the capture queue carries no note text; the packet does"
    monkeypatch.setattr(ttn, "_note_request_rows", lambda: [])
    assert ttn.note_requests_packet_field("2026-11-09")[1]["state"] == "absent"


def test_get_exercise_notes_routes_the_three_actions(monkeypatch):
    from mcp import tools_training_notes as ttn

    t = FakeTable()
    _raise(t, "2026-11-01")
    monkeypatch.setattr(ttn, "table", t)
    monkeypatch.setattr(ttn, "pacific_today", lambda: TODAY)
    listed = ttn.tool_get_exercise_notes({"action": "note_requests"})
    assert listed["open_count"] == 1 and "owner-only" in listed["privacy"]
    rid = listed["open"][0]["request_id"]
    assert ttn.tool_get_exercise_notes({"action": "answer_request", "reply": "x"})["error"].startswith("refused: request_id is required")
    ans = ttn.tool_get_exercise_notes({"action": "answer_request", "request_id": rid, "reply": "The evidence is mixed."})
    assert ans["wrote"] and ans["status"] == "answered" and ans["row"]["channel"] == "coach_chat"
    dec = ttn.tool_get_exercise_notes({"action": "decline_request", "request_id": rid, "reason": "already answered"})
    assert not dec["wrote"] and "already answered" in dec["error"]
    from mcp.tools_descriptions import GET_EXERCISE_NOTES_INPUT

    enum = GET_EXERCISE_NOTES_INPUT["properties"]["action"]["enum"]
    assert {"note_requests", "answer_request", "decline_request"} <= set(enum)


# ── the Lambda hook: the on-ingest path raises the rows (fixture = wire end to end) ──────────
def test_the_hevy_ingest_hook_raises_the_rows(monkeypatch):
    sys.path.insert(0, str(ROOT / "lambdas" / "ingestion"))
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
    import hevy_backfill_lambda as mod
    from common import pacific_time
    from training import training_notes_llm

    t = FakeTable()
    monkeypatch.setattr(mod, "_table", t)
    monkeypatch.setattr(training_notes_llm, "make_llm_fn", lambda table, lane="live": None)
    monkeypatch.setattr(pacific_time, "pacific_today", lambda: TODAY)
    mod._derive_training_notes(_row("2026-11-01"))
    rows = t.requests()
    assert {n: r["status"] for n, r in rows.items()} == {"Lateral Raise (Machine)": "answered", "Triceps Rope Pushdown": "open"}
    mod._derive_training_notes(_row("2026-11-01"))  # a re-ingest of the same workout
    assert {n: r["status"] for n, r in t.requests().items()} == {"Lateral Raise (Machine)": "answered", "Triceps Rope Pushdown": "open"}


# ── privacy: owner-only partition, no reader surface, no private-source join (acceptance box 6) ──
def test_rows_live_in_an_owner_only_partition():
    from privacy.field_tiers import SOURCE_TIERS, TIER_OWNER_ONLY

    assert nr.REQUEST_PK == "USER#matthew#SOURCE#training_constraints"
    assert SOURCE_TIERS["training_constraints"] == TIER_OWNER_ONLY


# premerge-gate: reads every site-API module and the request modules' imports, so a new reader surface or a private-source join anywhere in those trees reds this
def test_no_reader_surface_reads_the_requests_and_the_requests_read_no_private_source():
    web = [p for p in (ROOT / "lambdas" / "web").rglob("*.py")]
    assert web, "the site-API tree moved; re-point this guard"
    leaks = [str(p.relative_to(ROOT)) for p in web if "note_requests" in p.read_text() or "REQUEST#" in p.read_text()]
    assert not leaks, leaks
    for mod in ("lambdas/training/note_requests.py", "lambdas/training/form_cue_sheets.py", "lambdas/training/training_notes_requests.py"):
        src = (ROOT / mod).read_text().split('"""', 2)[-1]  # the code, not the docstring that names what it never reads
        for private in ("journal", "state_of_mind", "video_diary", "vlog"):
            assert private not in src, (mod, private)
