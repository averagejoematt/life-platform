"""tests/test_reading_constellation.py — the Constellation signature (Phase E).

Idea extraction (grounded, fail-soft), the idea index + enumeration, the honesty
gate, and the public endpoint's honest single-point empty state.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402
from reading import (
    reading_constellation as rcst,  # noqa: E402
    reading_store as rs,  # noqa: E402
)
from reading_fakes import FakeTable  # noqa: E402
from web import site_api_reading as sar  # noqa: E402


@pytest.fixture(autouse=True)
def fake_table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(rs, "table", t)
    return t


def test_idea_id_is_stable():
    assert rcst.idea_id("Entropy always wins") == rcst.idea_id("entropy always wins")
    assert rcst.idea_id("a") != rcst.idea_id("b")


def test_extract_grounded_and_failsoft():
    def caller(_b):
        return {"content": [{"type": "text", "text": json.dumps({"ideas": [{"label": "Quiet Persistence", "gist": "small steady acts"}]})}]}

    ideas = rcst.extract_ideas("Stoner", "A life of quiet persistence...", caller=caller)
    assert len(ideas) == 1 and ideas[0]["label"] == "quiet persistence" and ideas[0]["ideaId"]
    # no source text → nothing invented
    assert rcst.extract_ideas("X", "", caller=caller) == []

    def boom(_b):
        raise RuntimeError("down")

    assert rcst.extract_ideas("X", "some notes", caller=boom) == []


# ── #2425: the code-level grounding gate over the owner's own words ──────────
def test_idea_with_number_not_in_owners_words_is_held():
    """The prompt said 'grounded ONLY in the text you're given'; #2425 makes that
    code. A label/gist carrying a figure the owner never wrote is dropped."""

    def caller(_b):
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "ideas": [
                                {"label": "the 10,000 hour rule", "gist": "mastery takes 10000 hours of practice"},
                                {"label": "quiet persistence", "gist": "small steady acts compound"},
                            ]
                        }
                    ),
                }
            ]
        }

    ideas = rcst.extract_ideas("Stoner", "A life of quiet persistence, small steady acts.", caller=caller)
    assert [i["label"] for i in ideas] == ["quiet persistence"], "the 10000 appears nowhere in his notes — held (#2425)"


def test_idea_number_grounded_in_owners_words_survives():
    def caller(_b):
        return {
            "content": [
                {"type": "text", "text": json.dumps({"ideas": [{"label": "the 40-hour myth", "gist": "he wrote 40 hours is a myth"}]})}
            ]
        }

    ideas = rcst.extract_ideas("Rest", "His notes: the 40-hour work week is mostly myth.", caller=caller)
    assert len(ideas) == 1 and ideas[0]["label"] == "the 40-hour myth"


def test_gate_unavailable_holds_everything(monkeypatch):
    """Fail-closed: no gate module → no idea ships (and no idea is invented)."""
    monkeypatch.setattr(rcst, "_gg", None)
    called = {"n": 0}

    def caller(_b):
        called["n"] += 1
        return {"content": [{"type": "text", "text": json.dumps({"ideas": [{"label": "anything", "gist": ""}]})}]}

    assert rcst.extract_ideas("X", "some notes", caller=caller) == []
    assert called["n"] == 0, "fail-closed must also mean no tokens spent"


def test_is_ready_gate():
    assert rcst.is_ready(3) is False
    assert rcst.is_ready(4) is True


def test_idea_index_and_enumeration():
    rs.put_idea({"ideaId": "i1", "label": "entropy", "recency": 0.9}, source_book_id="b1")
    rs.put_idea({"ideaId": "i2", "label": "memory", "recency": 0.2}, source_book_id="b1")
    rs.put_edge("i1", "i2", weight=0.5, rationale="same book")
    graph = rs.all_ideas()
    assert graph["node_count"] == 2
    assert {n["ideaId"] for n in graph["nodes"]} == {"i1", "i2"}
    assert graph["edges"] and graph["edges"][0]["from"] == "i1" and graph["edges"][0]["to"] == "i2"


def test_constellation_endpoint_honest_empty():
    body = json.loads(sar.handle_constellation()["body"])
    assert body["ready"] is False and body["node_count"] == 0
    assert "first idea you keep" in body["note"]


def test_constellation_endpoint_ready_when_enough():
    for i in range(4):
        rs.put_idea({"ideaId": f"i{i}", "label": f"idea {i}", "recency": 0.5}, source_book_id="b1")
    body = json.loads(sar.handle_constellation()["body"])
    assert body["ready"] is True and body["node_count"] == 4
    assert len(body["nodes"]) == 4 and all("label" in n for n in body["nodes"])
