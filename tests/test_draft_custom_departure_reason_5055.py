"""#5055 — the engine's `draft` is the default; `draft_custom` is a deliberate departure and says why."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mcp import routine_spec_ledger as ledger, tools_hevy_routine as t

ROOT = Path(__file__).resolve().parent.parent
FAKE_INDEX = {"burpee": {"id": "BB792A36", "title": "Burpee"}}
EXERCISES = [{"title": "Burpee", "sets": [{"reps": 15, "count": 3}]}]


def _draft(extra: dict) -> tuple[dict, dict]:
    captured: dict = {}

    def fake_put(ir):
        captured["ir"] = ir
        return ir

    with patch("training.routine_repo.draft_versioned", side_effect=fake_put), patch.object(t, "_template_index", return_value=FAKE_INDEX):
        out = t.tool_manage_hevy_routine(
            {"action": "draft_custom", "target_date": "2026-10-20", "archetype": "circuit", "exercises": EXERCISES, **extra}
        )
    return out, captured


def test_draft_custom_without_a_reason_refuses_by_name():
    for extra in ({}, {"departure_reason": ""}, {"departure_reason": "  short "}):
        out, captured = _draft(extra)
        assert "DEPARTURE_REASON_REQUIRED" in str(out) and "ir" not in captured, extra


def test_draft_custom_with_a_reason_records_it_on_the_ir_and_the_spec_row():
    out, captured = _draft({"departure_reason": "  owner asked for a hotel-room circuit, no engine slot fits  "})
    assert out["status"] == "drafted_custom"
    ir = captured["ir"]
    assert ir.inputs_snapshot["departure_reason"] == "owner asked for a hotel-room circuit, no engine slot fits"
    ir.hevy_routine_id = "h1"
    ir.version = 1
    row = ledger.build_spec(ir)
    assert row["departure_reason"] == ir.inputs_snapshot["departure_reason"]


def test_an_engine_draft_has_no_departure_reason_in_its_spec_row():
    ir = SimpleNamespace(
        routine_id="r",
        hevy_routine_id=None,
        archetype="push",
        variant="ideal",
        title="t",
        target_date="d",
        status="active",
        version=1,
        created_by="cron",
        inputs_snapshot={},
        exercises=[],
    )
    with patch.object(ledger, "content_hash", return_value="h"):
        assert ledger.build_spec(ir)["departure_reason"] is None


def test_the_mcp_schema_declares_the_argument():
    # source read, not an import: mcp.registry needs the deployed env at import time
    src = (ROOT / "mcp/registry.py").read_text()
    assert re.search(r'"departure_reason":\s*\{[^}]*REQUIRED', src, re.S)


def test_the_daily_debrief_skill_names_draft_as_the_default_route():
    text = (ROOT / ".claude/skills/daily-debrief/SKILL.md").read_text()
    assert re.search(r"`manage_hevy_routine` \*\*`draft`\*\*", text)
    assert "departure_reason" in text and "deliberate departure" in text
    assert "`manage_hevy_routine` `draft_custom` →" not in text
    assert "Personal Board" not in text
