"""tests/test_stage1_training_memory_4077.py — `plan_next_session` stage 1 reads
standing training constraints from platform memory (#4077).

THE DEFECT
  `write_platform_memory` rejected a `training` category outright, so a standing
  training constraint stated in chat (the RDL gate, a toe flag, a back flag) had no
  durable home and never reached the ONE surface that plans tomorrow's session.

THE FIX, PINNED HERE
  1. `mcp.tools_plan._training_memory_constraints()` reads through the SAME MCP tool a
     chat write would use — `mcp.tools_memory.tool_read_platform_memory` — with
     `category='training'`.
  2. Stage 1 (`tool_plan_next_session`, no `routine_id`) carries the result on
     `constraint_block.standing_constraints_from_chat`, and its read state on
     `constraint_block.inputs.training_memory_constraints` (#4072 convention: measured /
     absent / read_failed, never a bare `unknown`).

Every OTHER stage-1 reader is stubbed (this file is not re-testing #4051/#4072/#3930) —
only `tool_read_platform_memory` is real-ish (patched directly at the one seam this
change added), so a change to how it is called shows up here.
"""

from __future__ import annotations

import os
import pathlib
import sys
from contextlib import ExitStack
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import mcp.tools_plan as tp  # noqa: E402

TODAY = "2026-09-22"


@pytest.fixture(autouse=True)
def frozen_plan_clock(monkeypatch):
    """Stage 1 defaults its target date from `tools_plan.pacific_today()`; pin it to TODAY so
    no test here depends on the real wall clock (#2376's time-bomb class)."""
    monkeypatch.setattr(tp, "pacific_today", lambda: TODAY)


_BASE_PATCHES = [
    patch("mcp.tools_benchmark.tool_get_benchmark", return_value={"applicable": False, "reason": "no band"}),
    patch("mcp.tools_health.tool_get_readiness_score", return_value={"score": 55}),
    patch("mcp.tools_training.tool_get_acwr_status", return_value={"zone": "safe"}),
    patch("mcp.tools_strength.tool_get_muscle_volume", return_value={}),
    patch("mcp.tools_plan._protein_days_7d", return_value=(None, None)),
    patch("mcp.tools_plan._walking_volume_last_7d", return_value=None),
    patch("mcp.tools_plan._rotation_window", return_value=(None, None)),
    patch("mcp.tools_plan._nutrition_critics_block", return_value={"verdicts": []}),
    patch("mcp.tools_plan._performed_movements", return_value=([], ["experiment"], TODAY, 0)),
    patch("mcp.tools_plan._pain_dismissals", return_value=[]),
    patch("training.training_notes.training_notes_health", return_value={"checked": True, "extractor_dark": False}),
]


def _stage1(*, memory_response, target_date=TODAY):
    """`plan_next_session` stage 1, every reader stubbed except the one this issue wires:
    `mcp.tools_memory.tool_read_platform_memory`, injected with `memory_response`."""
    patches = [*_BASE_PATCHES, patch("mcp.tools_memory.tool_read_platform_memory", return_value=memory_response)]
    with ExitStack() as st:
        for cm in patches:
            st.enter_context(cm)
        return tp.tool_plan_next_session({"target_date": target_date})


_RDL_GATE = {
    "sk": "MEMORY#training#2026-09-15",
    "category": "training",
    "date": "2026-09-15",
    "summary": "RDL gate: hold to 40kg until the back flag clears",
    "channel": "conversation",
}


def test_stage1_reads_training_memory_via_the_same_mcp_tool_a_chat_write_would_use():
    """The reader is `tool_read_platform_memory(category='training')`, not a second,
    stale query the write path doesn't share."""
    with patch("mcp.tools_memory.tool_read_platform_memory", return_value={"records": [], "count": 0}) as mock_read:
        with ExitStack() as st:
            for cm in _BASE_PATCHES:
                st.enter_context(cm)
            tp.tool_plan_next_session({"target_date": TODAY})
    args = mock_read.call_args.args[0]
    assert args["category"] == "training"


def test_stage1_carries_the_standing_constraint_on_the_block():
    out = _stage1(memory_response={"records": [_RDL_GATE], "count": 1})
    block = out["constraint_block"]
    assert block["standing_constraints_from_chat"] == [_RDL_GATE]
    assert block["inputs"]["training_memory_constraints"]["state"] == "measured"


def test_stage1_empty_memory_reads_absent_never_a_bare_unknown():
    out = _stage1(memory_response={"records": [], "count": 0})
    block = out["constraint_block"]
    assert block["standing_constraints_from_chat"] == []
    status = block["inputs"]["training_memory_constraints"]
    assert status["state"] == "absent"
    assert "training" in status.get("detail", "")


def test_stage1_a_tool_error_reads_failed_not_silently_empty():
    out = _stage1(memory_response={"error": "DynamoDB unavailable"})
    block = out["constraint_block"]
    assert block["standing_constraints_from_chat"] == []  # never invented
    status = block["inputs"]["training_memory_constraints"]
    assert status["state"] == "read_failed"
    assert "DynamoDB unavailable" in status.get("error", "")


def test_stage1_standing_constraints_from_chat_stays_separate_from_the_code_registry():
    """#3715's owner-gate-reviewed registry (`standing_constraints`) and the chat-written
    memory category (`standing_constraints_from_chat`, #4077) must never be merged — one
    is owner-confirmed, the other is not."""
    out = _stage1(memory_response={"records": [_RDL_GATE], "count": 1})
    block = out["constraint_block"]
    assert "standing_constraints" in block
    assert block["standing_constraints"] != block["standing_constraints_from_chat"]
