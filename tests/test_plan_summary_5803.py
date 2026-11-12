"""tests/test_plan_summary_5803.py — `plan_next_session(detail="summary")`, the compact view a chat reads (#5803).

The full result is ~250-335 KB on a live stage-2 call (PR #5791 measured ~305 KB; the read-only lane measurement on
draft_custom f4569682 for 2026-11-11 is in this PR's body). It serialises in milliseconds, so the cost is chat context,
not latency. This file is the feature's own contract (no ratchet, no census):

  * the summary's keys EQUAL the declared set (`plan_summary.SUMMARY_KEYS`), on stage 1 and on stage 2;
  * it fits a size budget on the harness's draft_custom stage-2 shape, against a full result many times larger;
  * every critic verdict rides with its declared fields (`VERDICT_KEYS`) — the must-fail control: drop `reason` from
    `plan_summary._verdict` and `test_every_verdict_rides_with_its_declared_fields` reds;
  * nothing is dropped silently: every full-result key is either carried verbatim or named in `omitted` with a fetch;
  * commit binding is unaffected: stage 2 under `detail="summary"` still stores the FULL critics record on the routine,
    and `commit_binding.check` binds to it (binding reads the stored record, never the response);
  * the default stays `full`; a bad `detail` is refused BEFORE stage 2 runs, so nothing is written.

Offline: the stage-2 harness of tests/test_tools_plan_critics_3752.py (every reader stubbed at its source module).
"""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from unittest.mock import patch

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import test_tools_plan_critics_3752 as base  # noqa: E402 — the stage-2 offline harness
from training import commit_binding  # noqa: E402

from mcp import (
    plan_summary as ps,  # noqa: E402
    tools_plan as tp,  # noqa: E402
)

TARGET = "2026-11-11"  # the 11-11 draft_custom shape (the harness routine is draft_custom)
BUDGET_BYTES = 15_000  # what a summary may cost the chat; the full result on this shape is >10x that


@pytest.fixture(autouse=True)
def _output_schema_conformance(monkeypatch):
    """Every result this file produces, full or summary, is validated against the declared outputSchema."""
    from test_mcp_registry import check_output_schema

    check_output_schema(monkeypatch, tp, "plan_next_session")


def _wire_bytes(result) -> int:
    return len(json.dumps(result, default=str).encode())  # exactly the handler's text content (`handler._call_result`)


def _stage2(detail=None, **extra):
    ir = base._ir()
    assert ir.source_action == "draft_custom"
    stored, thread = [], []
    args = {"target_date": TARGET, "routine_id": ir.routine_id, **extra}
    if detail is not None:
        args["detail"] = detail
    with ExitStack() as st:
        for cm in base._stage2_patches(ir, base._evidence(), invoke=base._approving, stored=stored, thread=thread):
            st.enter_context(cm)
        out = tp.tool_plan_next_session(args)
    return ir, out, stored


_READY_PREDRAFT = {
    "target_date": TARGET,
    "routine_id": "pre-1",
    "routine_version": 2,
    "status_in_repo": "draft",
    "drafted_at": "2026-11-11T05:00:00Z",
    "plan_source": "charter",
    "status": "ready",
    "critics": {
        "model_ran": True,
        "model_paused_reason": None,
        "veto": False,
        "ran_at": "2026-11-11T05:01:00Z",
        "verdicts": [{"critic": "muscle_defense", "verdict": "approve"}],
        "recheck_passed": True,
    },
    "how_to_use": "A draft for this date was built and red-teamed overnight — REVIEW it rather than building a new one.",
}


def _stage1(detail=None):
    args = {"target_date": TARGET} if detail is None else {"target_date": TARGET, "detail": detail}
    with ExitStack() as st:
        for cm in base._stage2_patches(base._ir(), base._evidence(), invoke=base._approving)[:6]:
            st.enter_context(cm)
        st.enter_context(patch("training.training_notes.training_notes_health", side_effect=RuntimeError("offline")))
        st.enter_context(patch("mcp.nightly_predraft.predraft_for", return_value=dict(_READY_PREDRAFT)))
        st.enter_context(patch("ai.bedrock_client.invoke", side_effect=AssertionError("no model in stage 1")))
        return tp.tool_plan_next_session(args)


# ── the declared key set + the budget ────────────────────────────────────────────────────────────────────────────
def test_stage_2_summary_carries_exactly_the_declared_keys_within_budget():
    _, full, _ = _stage2()
    _, summ, _ = _stage2("summary")
    assert set(summ) == set(ps.SUMMARY_KEYS), sorted(set(summ) ^ set(ps.SUMMARY_KEYS))
    assert summ["detail"] == "summary" and summ["stage"] == 2
    size, full_size = _wire_bytes(summ), _wire_bytes(full)
    assert size <= BUDGET_BYTES, f"summary is {size} B against a {BUDGET_BYTES} B budget (full: {full_size} B)"
    assert full_size > 5 * size, (full_size, size)


def test_stage_1_summary_carries_exactly_the_declared_keys_and_the_predraft_status():
    summ = _stage1("summary")
    assert set(summ) == set(ps.SUMMARY_KEYS)
    assert summ["stage"] == 1 and summ["red_team"] is None
    assert summ["predraft"]["status"] == "ready" and summ["predraft"]["routine_id"] == "pre-1"
    assert summ["predraft"]["critics"]["veto"] is False and summ["predraft"]["critics"]["verdicts"][0]["verdict"] == "approve"
    assert _wire_bytes(summ) <= BUDGET_BYTES


# ── the verdicts (the must-fail control lives here) ──────────────────────────────────────────────────────────────
def test_every_verdict_rides_with_its_declared_fields():
    """Mutation control: delete `"reason"` (or any VERDICT_KEYS field) from `plan_summary._verdict` -> red."""
    _, full, _ = _stage2()
    summ = ps.summarize(full)
    full_v, summ_v = full["critics"]["verdicts"], summ["red_team"]["verdicts"]
    assert len(summ_v) == len(full_v) == 4
    for f, s in zip(full_v, summ_v):
        assert set(ps.VERDICT_KEYS) <= set(s), (sorted(set(ps.VERDICT_KEYS) - set(s)), s)
        assert (s["critic"], s["verdict"], s["reason"]) == (f["critic"], f["verdict"], f["reason"])
    for v in summ["nutrition_verdicts"]["verdicts"]:
        assert set(ps.VERDICT_KEYS) <= set(v), v
    rt = summ["red_team"]
    assert rt["veto"] == full["critics"]["veto"] and rt["written"] is True and rt["verdict_state"] == full["critics"]["verdict_state"]


def test_a_veto_and_its_number_survive_the_projection():
    full = {
        "target_date": TARGET,
        "constraint_block": {},
        "critics": {
            "routine_id": "r",
            "veto": True,
            "verdicts": [
                {"critic": "joints_tendons", "verdict": "veto", "metric": "pain_flag", "value": 2, "reason": "x" * 900},
            ],
        },
    }
    v = ps.summarize(full)["red_team"]["verdicts"][0]
    assert (v["verdict"], v["metric"], v["value"], v["overridden"]) == ("veto", "pain_flag", 2, False)
    assert len(v["reason"]) <= 300, "a reason is bounded, never unbounded prose"


# ── nothing dropped silently ─────────────────────────────────────────────────────────────────────────────────────
def test_every_full_key_is_carried_verbatim_or_named_in_omitted_with_a_fetch():
    _, full, _ = _stage2()
    summ = ps.summarize(full)
    om = summ["omitted"]
    for key in full:
        if key in om["keys"]:
            assert om["keys"][key] in om["fetch"], key
        else:
            assert summ.get(key) == full[key], f"{key} is neither carried verbatim nor named in omitted"
    assert om["keys"]["critics"] == "stage_2" and "manage_hevy_routine action=get" in om["fetch"]["stage_2"]
    block = full["constraint_block"]
    assert set(om["constraint_block_not_condensed"]) | set(ps._BLOCK_CONDENSED) >= set(block)


def test_the_lines_the_chat_must_say_are_verbatim():
    _, full, _ = _stage2()
    summ = ps.summarize(full)
    block = full["constraint_block"]
    assert summ["honesty"] == block["honesty"]
    assert summ["must_say"] == block["reference"]["must_say"]
    assert summ["calibration_due"] == full["calibration_due"]
    walk = block["steps_ramp"]["walk_to_close_gap"]
    assert summ["steps"]["walk_to_close_gap"]["state"] == walk["state"]
    assert summ["week_commitments"]["verdict"] == block["week_commitments"]["verdict"]
    assert summ["training_phase"]["state"] == full["training_phase"]["state"]


def test_exercise_unlocks_ride_verbatim_because_they_are_announced_once():
    unlocks = {"state": "measured", "lines": ["The trap-bar deadlift is unlocked."], "claimed": True}
    summ = ps.summarize({"target_date": TARGET, "constraint_block": {}, "exercise_unlocks": unlocks})
    assert summ["exercise_unlocks"] == unlocks and "exercise_unlocks" not in summ["omitted"]["keys"]


# ── commit binding is unaffected ─────────────────────────────────────────────────────────────────────────────────
def test_stage_2_under_summary_stores_the_full_record_and_the_commit_binds_to_it():
    ir, summ, stored = _stage2("summary")
    assert stored and stored[-1] is ir
    rec = ir.inputs_snapshot["critics"]
    assert {"verdicts", "binding", "packet_numbers", "draft_exercises"} <= set(rec), "the stored record is the FULL one"
    assert commit_binding.check(ir)["bound"] is True, commit_binding.check(ir)
    assert summ["red_team"]["binding"] == rec["binding"]


# ── the default and the refusal ──────────────────────────────────────────────────────────────────────────────────
def test_the_default_and_full_are_the_whole_result():
    for detail in (None, "full"):
        out = _stage1(detail)
        assert "constraint_block" in out and "detail" not in out and "omitted" not in out


def test_a_bad_detail_is_refused_before_stage_2_writes_anything():
    ir, out, stored = _stage2("brief")
    assert out.get("error_code") == "INVALID_ARG" or "INVALID_ARG" in json.dumps(out), out
    assert stored == [] and ir.version == 1


def test_a_projection_that_raises_returns_the_full_result_and_names_the_failure():
    with patch.object(ps, "summarize", side_effect=KeyError("boom")):
        out = _stage1("summary")
    assert "constraint_block" in out and out["summary_error"].startswith("KeyError")
