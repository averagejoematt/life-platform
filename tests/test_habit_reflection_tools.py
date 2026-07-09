"""tests/test_habit_reflection_tools.py — #422 secondary channel (Claude reflection loop).

The MCP surface mirrors the field-notes idiom: a READ tool surfaces what to ask about,
a WRITE tool records the answer with update semantics (never clobbering the Habitify-sourced
note channel). Hermetic — the DDB table is faked/monkeypatched.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

from fakes import FakeDdbTable  # noqa: E402

import mcp.tools_habits as th  # noqa: E402


def test_queue_flags_missed_day_with_no_why(monkeypatch):
    habitify = [
        {"date": "2026-07-01", "habit_statuses": {"Meditate": {"status": "failed", "group": "Growth"}}},
        {"date": "2026-07-02", "habit_statuses": {"Walk": {"status": "completed", "group": "Performance"}}},
    ]
    monkeypatch.setattr(th, "_recent_habitify", lambda days: habitify)
    monkeypatch.setattr(th, "_captured_reflections", lambda days: {})
    out = th.tool_get_habit_reflection_queue({"days": 7})
    missed = {(m["habit"], m["date"]) for m in out["missed_needs_why"]}
    done = {(d["habit"], d["date"]) for d in out["completed_needs_driver"]}
    assert ("Meditate", "2026-07-01") in missed
    assert ("Walk", "2026-07-02") in done


def test_queue_excludes_days_already_captured(monkeypatch):
    habitify = [{"date": "2026-07-01", "habit_statuses": {"Meditate": {"status": "failed", "group": "Growth"}}}]
    reflections = {("2026-07-01", "meditate"): {"why_missed": "was sick"}}
    monkeypatch.setattr(th, "_recent_habitify", lambda days: habitify)
    monkeypatch.setattr(th, "_captured_reflections", lambda days: reflections)
    out = th.tool_get_habit_reflection_queue({"days": 7})
    assert out["missed_needs_why"] == []


def test_queue_excludes_days_with_habitify_note(monkeypatch):
    # A note captured in-app already answers the why — don't re-ask.
    habitify = [{"date": "2026-07-01", "habit_statuses": {"Meditate": {"status": "failed", "group": "Growth", "notes": ["traveling"]}}}]
    monkeypatch.setattr(th, "_recent_habitify", lambda days: habitify)
    monkeypatch.setattr(th, "_captured_reflections", lambda days: {})
    out = th.tool_get_habit_reflection_queue({"days": 7})
    assert out["missed_needs_why"] == []


def test_log_reflection_writes_keyed_record(monkeypatch):
    fake = FakeDdbTable()
    monkeypatch.setattr(th, "_table_ref", fake)
    res = th.tool_log_habit_reflection({"habit": "Meditate", "date": "2026-07-01", "why_missed": "was traveling"})
    assert res["status"] == "saved"
    assert res["channel"] == "claude_reflection"
    assert fake.updates, "must persist via update_item (merge semantics, never clobber)"
    upd = fake.updates[0]
    assert upd["Key"]["sk"] == "HABITDAY#2026-07-01#meditate"
    assert upd["ExpressionAttributeValues"][":why_missed"] == "was traveling"
    assert upd["ExpressionAttributeValues"][":ch"] == "claude_reflection"


def test_log_reflection_lifts_trigger_prefix_from_context(monkeypatch):
    fake = FakeDdbTable()
    monkeypatch.setattr(th, "_table_ref", fake)
    th.tool_log_habit_reflection({"habit": "Walk", "context": "trigger: morning coffee"})
    vals = fake.updates[0]["ExpressionAttributeValues"]
    assert vals[":trigger"] == "morning coffee"


def test_log_reflection_requires_a_field():
    res = th.tool_log_habit_reflection({"habit": "Walk"})
    assert "error" in res


def test_log_reflection_requires_habit():
    res = th.tool_log_habit_reflection({"why_missed": "x"})
    assert "error" in res
