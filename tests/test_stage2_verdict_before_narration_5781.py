"""tests/test_stage2_verdict_before_narration_5781.py — stage 2 stores its verdicts BEFORE the model step.

Live, 2026-11-11: `plan_next_session` stage 2 on the draft_custom routine f4569682 ran 28.1 / 27.2 / 27.8 s (MCP
Lambda REPORT lines, requests 44e83743 / 86f43954 / d52117ad). Each reached its one write past the 26 s deadline
(`plan_call_scope.STAGE_2_WRITE_DEADLINE_SECS`, below `mcp.handler.TOOL_TIMEOUT_SECS` = 30), stored NOTHING, and every
commit was refused `not_red_teamed`. The read-only profile (PR body) put the time in the stage-1 reads and, after the
model wait, the draft_custom floor re-derivation (`critic_set_floors`) — not in the model replies, and not in the
~300 KB response (10 ms to serialise).

The fake clock below is the plan call's own (`plan_call_scope.elapsed_secs`): 20 s when stage 2 starts, 27 s once the
model has replied — the live shape. Before #5781 that run stored nothing (`test_stage_2_past_its_write_deadline_…` in
the #5313 file is the same refusal, made at the one write). Now the deterministic record lands at 20 s and binds the
commit; the late model replies are named and not stored.

Mutation controls (run on the lane, recorded on the PR): (M1) delete the checkpoint `run_.store(record, …)` call before
the model step -> nothing is stored and the 27 s test reds; (M2) move `critic_set_floors` back after the model call
(read it inside `record`) -> the floors-order test reds; (M3) drop the `MODEL_MIN_SECS` skip -> the no-time test reds
(the model is asked with a 1 s wait).
"""

from __future__ import annotations

import os
from contextlib import ExitStack
from unittest.mock import patch

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import test_tools_plan_critics_3752 as base  # noqa: E402 — the stage-2 offline harness
from coach import critics  # noqa: E402
from training import commit_binding  # noqa: E402

from mcp import (  # noqa: E402
    plan_call_scope,
    plan_stage2_run,
    tools_plan as tp,  # noqa: E402
)

ORDER: list[str] = []


def _stage2(clock: list[float], invoke):
    """One stage-2 run through `tool_plan_next_session` on the harness's draft_custom routine, the plan clock fake."""
    ir = base._ir()
    assert ir.source_action == "draft_custom"
    stored, thread = [], []
    ORDER.clear()

    def floors(_ir, **kw):
        ORDER.append("floors")
        return None

    def recorded_invoke(body):
        ORDER.append("model")
        return invoke(body)

    with ExitStack() as st:
        for cm in base._stage2_patches(ir, base._evidence(), invoke=recorded_invoke, stored=stored, thread=thread):
            st.enter_context(cm)
        st.enter_context(patch("mcp.hevy_prescription_gate.critic_set_floors", side_effect=floors))
        st.enter_context(patch.object(plan_call_scope, "elapsed_secs", lambda: clock[0]))
        out = tp.tool_plan_next_session({"target_date": "2026-09-20", "routine_id": ir.routine_id})
    return ir, out["critics"], stored, thread


def test_a_model_step_that_ends_at_27s_leaves_the_deterministic_verdicts_stored_and_commit_unblocked():
    clock = [20.0]

    def slow(body):  # the live shape: the replies come back after the write deadline
        clock[0] = 27.0
        return base._approving(body)

    ir, crit, stored, thread = _stage2(clock, slow)
    assert crit["written"] is True and crit["verdict_state"] == "landed_deterministic", crit.get("next")
    assert len(stored) == 1 and stored[0] is ir and ir.version == 2, "the deterministic record is the one version stored"
    rec = ir.inputs_snapshot["critics"]
    assert rec["model_ran"] is False and rec["model_paused_reason"] == plan_stage2_run.CHECKPOINT_REASON
    assert [v["critic"] for v in rec["verdicts"]] == list(critics.CRITIC_IDS)
    # the commit gate reads the stored routine: bound to this content, no veto standing
    assert commit_binding.check(ir)["bound"] is True, commit_binding.check(ir)
    assert critics.veto_reason(ir) is None
    assert "NOT stored" in crit["model_step"] and crit["next"].startswith("STORED")
    # past the deadline the thread row is not attempted (never race the MCP cap) — and says so
    assert thread == [] and crit["thread"]["written"] is False
    assert set(crit["timing_ms"]) == {*plan_stage2_run.TIMING_KEYS, "total"}


def test_a_model_step_that_lands_in_time_is_stored_on_top_and_binds_the_commit():
    ir, crit, stored, thread = _stage2([20.0], base._approving)
    assert crit["verdict_state"] == "landed" and crit["model_ran"] is True and "model_step" not in crit
    assert len(stored) == 2 and ir.version == 3 and ir.inputs_snapshot["critics"]["model_ran"] is True
    assert commit_binding.check(ir)["bound"] is True and thread == [ir]


def test_the_floors_are_read_before_the_model_is_asked():
    """`critic_set_floors` re-derives a draft_custom routine's floors from history; it used to run AFTER the model wait,
    eating the 2 s reserve before the write (the 11-11 overrun)."""
    _stage2([20.0], base._approving)
    assert ORDER.index("floors") < ORDER.index("model") and ORDER.count("floors") == 1, ORDER


def test_with_no_time_left_for_the_model_it_is_not_asked_and_the_verdicts_still_land():
    calls = []
    ir, crit, stored, _ = _stage2([23.5], lambda body: calls.append(body) or base._approving(body))
    assert calls == [], "1 s of model wait buys four timeouts and a second write — not started"
    assert crit["verdict_state"] == "landed_deterministic" and "not started" in crit["model_step"]
    assert len(stored) == 1 and commit_binding.check(ir)["bound"] is True


def test_past_the_deadline_before_the_first_write_nothing_is_stored_and_the_model_is_never_asked():
    calls = []
    ir, crit, stored, thread = _stage2([26.5], lambda body: calls.append(body) or base._approving(body))
    assert crit["written"] is False and crit["verdict_state"] == "not_written" and stored == [] and thread == []
    assert calls == [] and ir.version == 1 and "critics" not in (ir.inputs_snapshot or {})


def test_the_timing_breakdown_is_small_and_stable_keyed():
    _ir, crit, _stored, _thread = _stage2([20.0], base._approving)
    t = crit["timing_ms"]
    assert list(t) == [*plan_stage2_run.TIMING_KEYS, "total"] and all(isinstance(v, int) and v >= 0 for v in t.values())
    assert t["reads"] == 20000  # the plan clock at stage 2's start


def test_the_block_record_is_read_once_per_plan_call_and_every_caller_gets_its_own_rows(monkeypatch):
    """Stage 1 and the commit gate's floors (`v03_load_rule`, `_in_block_performed`) each read the block's Hevy record —
    three reads of the same rows on a draft_custom stage 2 (~2 s of the 11-11 tail). Mutation control: drop
    `BLOCK_WORKOUTS` from `plan_call`'s scope -> 3 reads and this reds; return the memo without `deepcopy` -> a caller's
    edit reaches the next caller and this reds."""
    from mcp import plan_hevy_windows

    reads = []

    def read(target_date):
        reads.append(target_date)
        return [{"date": "2026-11-10", "exercises": []}]

    monkeypatch.setattr(plan_hevy_windows, "_read_block_workouts", read)

    @plan_call_scope.plan_call
    def one_call():
        a = plan_hevy_windows._block_workouts("2026-11-11")
        a[0]["mutated"] = True
        return a, plan_hevy_windows._block_workouts("2026-11-11"), plan_hevy_windows._block_workouts("2026-11-11")

    a, b, c = one_call()
    assert reads == ["2026-11-11"] and "mutated" not in b[0] and b is not c
    plan_hevy_windows._block_workouts("2026-11-11")
    assert len(reads) == 2, "outside a plan call nothing is memoized"
