"""tests/test_tools_reading.py — the MCP reading tools (Phase B).

Patches the shared table (FakeTable) used by both reading_store and tools_reading.
Asserts read-tool shapes, the recommendation surface, and the draft→dry_run→commit
write contract (preview by default; writes only on explicit dry_run=false).
"""

from __future__ import annotations

import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")  # mcp.config requires these at import
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402
from reading import reading_store as rs  # noqa: E402
from reading_fakes import FakeTable  # noqa: E402

from mcp import tools_reading as tr  # noqa: E402


@pytest.fixture(autouse=True)
def fake_table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(rs, "table", t)
    monkeypatch.setattr(tr, "table", t)
    return t


def _add(title, status="want", **kw):
    return rs.add_book({"title": title, "author": "A", **kw}, initial_status=status, enricher=lambda m: {"domainTags": ["fiction"]})


# ── read tools ────────────────────────────────────────────────────────────────
def test_shelf_groups_by_status():
    _add("Now", status="reading")
    _add("Queued", status="want")
    shelf = tr.tool_get_reading_shelf({})
    assert len(shelf["reading"]) == 1 and len(shelf["queue"]) == 1
    assert shelf["finished"] == [] and shelf["set_down"] == []


def test_recommendation_empty_queue_notes():
    out = tr.tool_get_reading_recommendation({})
    assert out["recommendations"] == [] and "note" in out


def test_recommendation_ranks_queue_with_reason():
    _add("A Novel", status="want", pageCount=280)
    _add("Another", status="want", pageCount=300)
    out = tr.tool_get_reading_recommendation({})
    assert out["candidate_count"] == 2
    # low n (0 finished) → propose-and-dispose, one pick, with a reason
    assert out["propose_and_dispose"] is True
    assert len(out["recommendations"]) == 1
    assert out["recommendations"][0]["reason"].startswith("Recommended because")


def test_profile_absent_notes_onboarding():
    out = tr.tool_get_reading_profile({})
    assert out["profile"] is None and "onboard" in out["note"]


def test_constellation_honest_empty():
    out = tr.tool_get_constellation({})
    assert out["ready"] is False and "begins with the first idea" in out["note"]


def test_due_recalls_shape():
    out = tr.tool_get_due_recalls({})
    assert out["count"] == 0 and out["due"] == []


# ── write fat-tool ────────────────────────────────────────────────────────────
def test_invalid_action_errors():
    out = tr.tool_manage_reading({"action": "nuke"})
    assert out.get("error_code") == "INVALID_ACTION"


def test_add_book_dry_run_then_commit(fake_table):
    preview = tr.tool_manage_reading({"action": "add_book", "title": "Klara and the Sun", "author": "Ishiguro"})
    assert preview["status"] == "preview" and "inputs_current_through" in preview
    # nothing written yet
    assert tr.tool_get_reading_shelf({})["queue"] == []
    # commit
    out = tr.tool_manage_reading({"action": "add_book", "title": "Klara and the Sun", "author": "Ishiguro", "dry_run": False})
    assert out["status"] == "committed" and out["bookId"]
    assert len(tr.tool_get_reading_shelf({})["queue"]) == 1


def test_add_book_requires_title():
    out = tr.tool_manage_reading({"action": "add_book", "dry_run": False})
    assert out.get("error_code") == "MISSING_ARG"


def test_add_book_triggers_cover_fetch(monkeypatch):
    calls = []
    monkeypatch.setattr(tr, "_trigger_cover", lambda bid, meta: calls.append((bid, meta)) or True)
    out = tr.tool_manage_reading(
        {"action": "add_book", "title": "Project Hail Mary", "author": "Weir", "isbn13": "9780593135204", "dry_run": False}
    )
    assert out["status"] == "committed" and out["cover_fetch"] == "triggered"
    assert len(calls) == 1 and calls[0][0] == out["bookId"] and calls[0][1]["isbn13"] == "9780593135204"


def test_add_book_cover_failure_is_soft(monkeypatch):
    monkeypatch.setattr(tr, "_trigger_cover", lambda bid, meta: False)  # cover invoke failed
    out = tr.tool_manage_reading({"action": "add_book", "title": "T", "author": "A", "dry_run": False})
    assert out["status"] == "committed" and "deferred" in out["cover_fetch"]  # book still added


def test_update_status_abandon_requires_reason():
    bid = _add("Stalled")
    out = tr.tool_manage_reading({"action": "update_status", "bookId": bid, "status": "abandoned", "dry_run": False})
    assert out.get("error_code") == "MISSING_ARG"
    ok = tr.tool_manage_reading(
        {"action": "update_status", "bookId": bid, "status": "abandoned", "abandon_reason": "wrong-time", "dry_run": False}
    )
    assert ok["status"] == "committed" and ok["state"]["abandonReason"] == "wrong-time"


def test_log_session_commit():
    bid = _add("Reading")
    out = tr.tool_manage_reading(
        {"action": "log_session", "bookId": bid, "minutes": 25, "pages": 18, "date": "2026-06-29", "dry_run": False}
    )
    assert out["status"] == "committed" and out["session"]["minutes"] == 25


def test_onboard_returns_questions_without_answers():
    out = tr.tool_manage_reading({"action": "onboard"})
    assert out["status"] == "questions" and len(out["questions"]) >= 6


def test_dry_run_default_is_preview():
    bid = _add("Book")
    out = tr.tool_manage_reading({"action": "add_note", "bookId": bid, "text": "a thought"})
    assert out["status"] == "preview"  # default dry_run, nothing written
    assert rs.notes(bid) == []


# ── Phase D: the loop (debrief starts the probe clock; answer_recall scores) ──
def test_debrief_starts_the_retention_clock():
    bid = _add("Finished", status="finished")
    out = tr.tool_manage_reading({"action": "debrief", "bookId": bid, "takeaway": "The one idea that stuck.", "dry_run": False})
    assert out["status"] == "committed" and out["first_probe_due"]
    # a synthesis note (the public takeaway) AND a recall probe were created
    assert any(n["type"] == "synthesis" for n in rs.notes(bid))
    due = rs.due_recalls(now="2099-01-01")  # far future → the new probe is "due"
    assert any(r["bookId"] == bid for r in due)


def test_answer_recall_scores_and_advances(monkeypatch):
    bid = _add("Finished", status="finished")
    rs.put_recall(bid, prompt_id="p1", prompt="what stuck?", interval_index=1, next_due="2026-06-01T00:00:00")
    # stub the gist scorer so the test stays offline
    monkeypatch.setattr(tr.reading_recall, "score_gist", lambda p, a, caller=None: {"gist": 0.85, "note": "solid", "scored": True})
    out = tr.tool_manage_reading(
        {"action": "answer_recall", "bookId": bid, "prompt_id": "p1", "answer": "I can reconstruct the core argument.", "dry_run": False}
    )
    assert out["status"] == "committed" and out["interval_index"] == 2  # advanced on strong gist
    assert out["probes"] == 1 and out["retention_score"] is None  # 1 probe → n-gated


def test_answer_recall_requires_answer():
    bid = _add("Finished", status="finished")
    rs.put_recall(bid, prompt_id="p1", prompt="q", next_due="2026-06-01T00:00:00")
    out = tr.tool_manage_reading({"action": "answer_recall", "bookId": bid, "prompt_id": "p1", "dry_run": False})
    assert out.get("error_code") == "MISSING_ARG"
