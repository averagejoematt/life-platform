"""test_coach_corrections_follow_the_coach_6149.py — a correction given in conversation
reaches the coach it corrects, wherever that coach next speaks to the owner.

#6149: `log_coach_correction`'s signal path stores `surface="chat_coaching"`; the only
prompt reader (`ai_calls._coach_corrections_block`) asked for `coach_brief` alone, and the
Telegram chat read no corrections at all. So every correction given in conversation
reached nobody. The fix: one owner-facing surface set (`OWNER_FACING_SURFACES`) that the
brief, the Telegram chat and the Claude coach-session packet all read.

Each test names the mutation that reds it. Fully offline — in-memory `FakeDdbTable`, the
SSM cycle read stubbed, no Bedrock, no Telegram. Fixture text is synthetic.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from ai import ai_calls  # noqa: E402
from coach import coach_chat, coach_corrections as cc  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402


@pytest.fixture(autouse=True)
def _no_ssm(monkeypatch):
    """The cycle stamp is an SSM read; pin it so nothing here reaches AWS."""
    monkeypatch.setattr(cc, "read_cycle", lambda *a, **k: None)


def _table():
    return FakeDdbTable(rows=[], query_hook=lambda t, **_kw: {"Items": list(t.store.values())})


def _write(table, item_ref, text, *, cid, date="2026-11-01", cls="other"):
    return cc.write_correction(
        table, item_ref, text, cls, now=datetime.fromisoformat(f"{date}T18:00:00+00:00").astimezone(timezone.utc), correction_id=cid
    )


def _seeded():
    t = _table()
    _write(t, {"surface": "chat_coaching", "coach": "mind", "signal": "s1"}, "CHAT-MIND: synthetic chat correction", cid="aaaa0001")
    _write(
        t, {"surface": "chat_coaching", "coach": None, "signal": "s2"}, "CHAT-ALL: synthetic surface-wide chat correction", cid="aaaa0002"
    )
    _write(t, {"surface": "coach_brief", "coach": "mind_coach"}, "BRIEF-MIND: synthetic brief correction", cid="aaaa0003")
    _write(t, {"surface": "chat_coaching", "coach": "sleep", "signal": "s3"}, "CHAT-SLEEP: another coach's correction", cid="aaaa0004")
    _write(t, {"surface": "plan_critics", "coach": "mind_coach"}, "CRITIC-AUDIT: a veto override audit row", cid="aaaa0005")
    _write(t, {"surface": "coach_dossier", "coach": "mind_coach", "action": "retract"}, "DOSSIER: a retraction", cid="aaaa0006")
    return t


def test_owner_facing_set_is_the_brief_and_chat_only():
    """Mutation: add the dossier / plan-critic surface to the set (those are not corrections of a coach's words)."""
    assert set(cc.OWNER_FACING_SURFACES) == {"coach_brief", "chat_coaching"}


def test_brief_block_carries_chat_corrections_for_its_coach():
    """Mutation: revert the brief call to `surface="coach_brief"` — CHAT-MIND and CHAT-ALL vanish."""
    block = ai_calls._coach_corrections_block("mind_coach", table=_seeded())
    assert "CHAT-MIND" in block and "CHAT-ALL" in block and "BRIEF-MIND" in block
    assert "CHAT-SLEEP" not in block, "another coach's chat correction leaked into the mind brief"
    assert "CRITIC-AUDIT" not in block and "DOSSIER" not in block


def test_surface_wide_chat_correction_reaches_every_brief_coach():
    """Mutation: treat a coach-less row as nobody's — CHAT-ALL reaches no coach."""
    t = _seeded()
    for coach_id in ("sleep_coach", "nutrition_coach", "physical_coach", "labs_coach"):
        block = ai_calls._coach_corrections_block(coach_id, table=t)
        assert "CHAT-ALL" in block, coach_id
        assert "CHAT-MIND" not in block and "BRIEF-MIND" not in block, coach_id


def test_a_named_surface_still_scopes_to_that_surface_alone():
    """Mutation: ignore an explicit `surface=` — the 1786 scoping tests would silently widen."""
    block = ai_calls._coach_corrections_block("mind_coach", surface="coach_brief", table=_seeded())
    assert "BRIEF-MIND" in block and "CHAT-MIND" not in block


def test_naming_both_surface_and_surfaces_is_refused():
    """Mutation: silently prefer one — a caller bug would pass unnoticed."""
    with pytest.raises(ValueError):
        cc.open_corrections_for(_seeded(), surface="coach_brief", surfaces=cc.OWNER_FACING_SURFACES)


def test_bound_and_newest_first_hold_across_surfaces():
    """Mutation: drop the bound when several surfaces are read, or sort oldest-first."""
    t = _table()
    for i in range(cc.PROMPT_MEMORY_MAX_PER_COACH + 4):
        surface = "chat_coaching" if i % 2 else "coach_brief"
        _write(t, {"surface": surface, "coach": "mind", "n": i}, f"ROW-{i:02d}", cid=f"bbbb{i:04d}", date=f"2026-10-{i + 10:02d}")
    rows = cc.open_corrections_for(t, coach="mind_coach", surfaces=cc.OWNER_FACING_SURFACES)
    assert len(rows) == cc.PROMPT_MEMORY_MAX_PER_COACH
    assert [r["sk"] for r in rows] == sorted((r["sk"] for r in rows), reverse=True)
    assert rows[0]["correction_text"] == f"ROW-{cc.PROMPT_MEMORY_MAX_PER_COACH + 3:02d}"
    block = cc.chat_corrections_block(t, "mind_coach")
    assert block.count("\n- [") == cc.PROMPT_MEMORY_MAX_PER_COACH


def test_chat_block_carries_chat_corrections_in_conversational_wording():
    """Mutation: give the chat the brief's header, or read only one surface."""
    block = cc.chat_corrections_block(_seeded(), "mind_coach")
    assert block.startswith(cc.CHAT_CORRECTIONS_HEADER)
    assert "do not recite" in block.lower() and "already corrected" in block.lower()
    assert "CHAT-MIND" in block and "CHAT-ALL" in block and "BRIEF-MIND" in block
    assert "CHAT-SLEEP" not in block


def test_chat_block_naming_another_coach_is_empty_when_nothing_applies():
    t = _table()
    _write(t, {"surface": "chat_coaching", "coach": "sleep"}, "CHAT-SLEEP", cid="cccc0001")
    assert cc.chat_corrections_block(t, "mind_coach") == ""


def test_chat_block_fails_soft_on_a_read_error():
    """Mutation: let the read raise — a corrections outage would break every chat turn."""

    class _Broken:
        def query(self, **_):
            raise RuntimeError("ddb down")

    assert cc.chat_corrections_block(_Broken(), "mind_coach") == ""


def test_worker_memory_block_carries_the_corrections_into_the_dynamic_tail(monkeypatch):
    """Mutation: drop the worker's `chat_corrections_block` join, or move memory into the cached prefix."""
    from coach import coach_chat_summary, telegram_worker_lambda as w

    monkeypatch.setattr(w, "_table", lambda: _seeded())
    monkeypatch.setattr(coach_chat_summary, "read_recent_summaries", lambda table, pk: "")
    memory = w._memory_block("mind_coach")
    assert "CHAT-MIND" in memory and cc.CHAT_CORRECTIONS_HEADER in memory
    blocks = coach_chat.build_system_blocks("PERSONA", memory, "FACTS", "Coach")
    cached = [b for b in blocks if b.get("cache_control")]
    assert cached and all("CHAT-MIND" not in b["text"] for b in cached), "corrections reached the cached prefix"
    assert any("CHAT-MIND" in b["text"] for b in blocks if not b.get("cache_control"))


def test_worker_memory_block_survives_a_corrections_outage(monkeypatch):
    """Mutation: call the reader outside its fail-soft wrapper — a raise here would break the turn."""
    from coach import coach_chat_summary, telegram_worker_lambda as w

    monkeypatch.setattr(coach_chat_summary, "read_recent_summaries", lambda table, pk: "RECENT CONVERSATIONS: x")

    class _Broken:
        def get_item(self, **_):
            raise RuntimeError("ddb down")

        def query(self, **_):
            raise RuntimeError("ddb down")

    monkeypatch.setattr(w, "_table", lambda: _Broken())
    assert w._memory_block("mind_coach") == "RECENT CONVERSATIONS: x"


def test_session_packet_carries_the_training_coachs_open_corrections(monkeypatch):
    """Mutation: drop `open_corrections` from the packet's READERS, or scope it to one surface."""
    from mcp import tools_coach_packet as pkt

    t = _table()
    _write(t, {"surface": "chat_coaching", "coach": "training", "signal": "s"}, "TRAINING-CHAT", cid="dddd0001")
    _write(t, {"surface": "coach_brief", "coach": None}, "BRIEF-ALL", cid="dddd0002")
    _write(t, {"surface": "chat_coaching", "coach": "mind"}, "MIND-CHAT", cid="dddd0003")
    import mcp.config

    monkeypatch.setattr(mcp.config, "table", t)
    value, status = pkt._open_corrections("2026-11-21")
    assert status["state"] == "measured"
    texts = [v["correction_text"] for v in value]
    assert "TRAINING-CHAT" in texts and "BRIEF-ALL" in texts and "MIND-CHAT" not in texts
    assert {v["surface"] for v in value} == {"chat_coaching", "coach_brief"}
    assert "open_corrections" in pkt.READERS and "open_corrections" in pkt.SOURCES

    monkeypatch.setattr(mcp.config, "table", _table())
    value, status = pkt._open_corrections("2026-11-21")
    assert value == [] and status["state"] == "absent"
