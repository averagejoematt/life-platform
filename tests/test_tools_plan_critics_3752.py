"""tests/test_tools_plan_critics_3752.py — stage 2 of plan_next_session, and what the Hevy commit does with it.

The pure critic logic is held in test_plan_critics_3752.py. This file holds the WIRING:

  * `plan_next_session(routine_id=...)` runs the four critics over evidence gathered from
    the same readers a chat turn would call, applies their changes, stores the verdicts on
    the routine as a new version, and writes the training coach thread row;
  * `manage_hevy_routine commit` REFUSES on a stored veto (CRITIC_VETO), warns when no
    critic ran, and carries the verdicts into the Hevy notes on both the create and the
    dry-run bodies;
  * a paused budget tier is reported as paused, never as an approval.

Every reader is stubbed at its source module (the tool imports them lazily by name), so
these run offline. Mutation controls are named per test.
"""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from unittest.mock import patch

import pytest

# mcp.config reads these at import time; the MCP Lambda has them, a unit test must supply them.
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import hevy_write_client as wc  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

from mcp import (
    tools_hevy_routine as t,  # noqa: E402
    tools_plan as tp,  # noqa: E402
)

_TITLE_CTX = {"phase": "Phase", "type_count_in_phase": 1, "all_time_count": 1, "phase_started": "2026-06-01", "reset_epoch": "2026-06-01"}
KG = 1 / 2.2046226218


def _ir(routine_id="r-3752", squat_lbs=176.0, version=1):
    return RoutineSpec(
        routine_id=routine_id,
        target_date="2026-09-20",
        archetype="legs",
        version=version,
        source_action="draft_custom",
        notes="Legs — quality day.",
        exercises=[
            ExerciseBlock(movement_key="tmpl:1", rationale_tag="Squat (Barbell)", sets=[Set(weight_kg=squat_lbs * KG, reps=5)]),
            ExerciseBlock(
                movement_key="tmpl:2", rationale_tag="Leg Extension (Machine)", sets=[Set(weight_kg=40, reps=12) for _ in range(3)]
            ),
        ],
    )


def _evidence(pain0=False, drop=0.0, days0=3, weeks_in_block=0):
    return {
        "exercises": [
            {
                "idx": 0,
                "label": "Squat (Barbell)",
                "template_id": "1",
                "days_since": days0,
                "last_top_lbs": 176.0,
                "trailing_best_lbs": 180.0,
                "drop_pct": drop,
                "sessions_below": 2 if drop >= 10 else 0,
                "n_sessions": 6,
                "pain_flag_any": pain0,
                "pain_dates": ["2026-09-12"] if pain0 else [],
                "pain_layer_status": "ok",
            },
            {
                "idx": 1,
                "label": "Leg Extension (Machine)",
                "template_id": "2",
                "days_since": 5,
                "pain_flag_any": False,
                "pain_dates": [],
                "pain_layer_status": "ok",
            },
        ],
        "consecutive_days": 1,
        "lifting_sessions_7d": 2,
        "weeks_in_block": weeks_in_block,
        "pain_layer_status": "ok",
    }


_REFERENCE = {
    "applicable": True,
    "current_weight": 319.7,
    "current_rate_lb_wk": 2.0,
    "proven_target": {
        "band": "310-319",
        "band_distance_lb": 0,
        "n_effective": 12.0,
        "evidence_tier": "medium",
        "volume_citable": True,
        "sets_wk": 40,
        "walk_hr_wk": 8.5,
        "top_kg_by_movement": {"Squat (Barbell)": 90},
        "attested": {"minutes_typical": 45},
    },
}


def _stage2_patches(ir, evidence, *, invoke, allowed=(True, None), stored=None, thread=None):
    """Offline patch set for a stage-2 run. `stored` collects put_versioned calls."""
    stored = stored if stored is not None else []
    thread = thread if thread is not None else []
    return [
        patch("mcp.tools_benchmark.tool_get_benchmark", return_value=_REFERENCE),
        patch("mcp.tools_health.tool_get_readiness_score", return_value={"score": 55}),
        patch("mcp.tools_training.tool_get_acwr_status", return_value={"alert": "safe"}),
        patch("mcp.tools_strength.tool_get_muscle_volume", return_value={"muscle_sets": {"quads": 8}}),
        patch("mcp.tools_plan._walk_hours_last_7d", return_value=1.1),
        patch("mcp.tools_plan._protein_days_7d", return_value=(1, 7)),
        patch("mcp.tools_plan._gather_draft_evidence", return_value=evidence),
        patch("mcp.tools_plan._model_allowed", return_value=allowed),
        patch(
            "mcp.tools_plan._write_thread",
            side_effect=lambda ir_, today: thread.append(ir_) or {"written": True, "sk": f"SOURCE#coach_thread#training#{today}#critics"},
        ),
        patch("training.routine_repo.get_current", return_value=ir),
        patch("training.routine_repo.put_versioned", side_effect=lambda ir_: stored.append(ir_) or ir_),
        patch("ai.bedrock_client.invoke", side_effect=invoke),
        patch("training.training_notes.training_notes_health", side_effect=RuntimeError("offline")),
    ]


def _approving(body):
    return {
        "content": [{"type": "text", "text": '{"verdict":"approve","metric":null,"sentence":"Nothing here argues against it."}'}],
        "stop_reason": "end_turn",
    }


def _run(ir, evidence, invoke=_approving, **kw):
    stored, thread = [], []
    with ExitStack() as st:
        for cm in _stage2_patches(ir, evidence, invoke=invoke, stored=stored, thread=thread, **kw):
            st.enter_context(cm)
        out = tp.tool_plan_next_session({"target_date": "2026-09-20", "routine_id": ir.routine_id})
    return out, stored, thread


# ── stage 2 wiring ───────────────────────────────────────────────────────────
def test_stage_2_stores_the_verdicts_as_a_new_version_and_writes_the_thread_row():
    """Mutation control: delete the `put_versioned(ir)` line in `_run_stage_2` → `stored`
    is empty and this reds."""
    ir = _ir()
    calls = []

    def invoke(body):
        calls.append(body)
        return _approving(body)

    out, stored, thread = _run(ir, _evidence(), invoke=invoke)
    assert "error" not in out, out
    crit = out["critics"]
    assert crit["engine"] == "critics@1.0.0" and crit["model_ran"] is True and crit["veto"] is False
    assert [v["critic"] for v in crit["verdicts"]] == ["muscle_defense", "joints_tendons", "rate_advocate", "blueprint_historian"]
    assert len(calls) == 4, "one model call per critic"
    assert stored and stored[-1] is ir and ir.version == 2 and ir.parent_version == 1
    assert ir.inputs_snapshot["critics"]["verdicts"] == crit["verdicts"]
    assert thread == [ir] and out["critics"]["thread"]["written"] is True
    assert out["critics"]["routine_version"] == 2
    assert "RED TEAM" in out["critics"]["notes_preview"]
    assert out["critics"]["recheck"]["passed"] is True
    # stage 2 also fed the constraint block what stage 1 alone could not read
    tw = {t_["id"]: t_["state"] for t_ in out["constraint_block"]["tripwires"]}
    assert tw["protein_floor_missed"] == "clear" and tw["anchor_lift_strength_drop"] == "clear" and tw["pain_flag_named_site"] == "clear"
    assert "Stage 2 ran" in out["how_to_use"]


def test_stage_2_veto_is_stored_and_the_commit_then_refuses_by_name():
    """THE gate. Mutation control: in `_action_commit`, drop the `veto_reason` check →
    create_routine is called and this reds."""
    ir = _ir()
    out, stored, _ = _run(ir, _evidence(pain0=True))
    crit = out["critics"]
    assert crit["veto"] is True
    j = next(v for v in crit["verdicts"] if v["critic"] == "joints_tendons")
    assert j["verdict"] == "veto" and j["metric"] == "pain_flag[0]" and j["value"] is True
    assert out["critics"]["next"].startswith("VETO")
    assert crit["recheck"]["passed"] is False

    created = []
    with ExitStack() as st:
        for cm in _commit_patches(ir, created):
            st.enter_context(cm)
        res = t.tool_manage_hevy_routine({"action": "commit", "routine_id": ir.routine_id})
    assert res.get("error_code") == "CRITIC_VETO" or "CRITIC_VETO" in json.dumps(res), res
    assert "pain flag" in json.dumps(res)
    assert created == [], "a vetoed routine must never reach Hevy"


def test_stage_2_applies_a_change_before_storing_and_the_dry_run_shows_the_revised_body():
    ir = _ir(squat_lbs=200.0)  # over the band-matched 90 kg less the 10% discount
    out, stored, _ = _run(ir, _evidence())
    h = next(v for v in out["critics"]["verdicts"] if v["critic"] == "blueprint_historian")
    assert h["verdict"] == "change" and h["field"] == "exercises[0].weight_lbs"
    assert out["critics"]["changes"] == [
        {"critic": "blueprint_historian", "field": "exercises[0].weight_lbs", "to": h["to"], "applied": True, "why": None}
    ]
    assert ir.exercises[0].sets[0].weight_kg == pytest.approx(h["to"] * KG, abs=0.01)
    with ExitStack() as st:
        for cm in _commit_patches(ir, []):
            st.enter_context(cm)
        preview = t.tool_manage_hevy_routine({"action": "dry_run", "routine_id": ir.routine_id})
    notes = preview["wire_body"]["routine"]["exercises"][0]["notes"]
    assert notes.startswith("Legs — quality day.\n\nRED TEAM (critics@1.0.0, 4 critics,")
    assert f"applied: exercises[0].weight_lbs -> {h['to']}" in notes
    assert preview["wire_body"]["routine"]["exercises"][0]["sets"][0]["weight_kg"] == pytest.approx(h["to"] * KG, abs=0.01)


def test_a_paused_budget_tier_runs_the_deterministic_layer_and_says_the_model_did_not():
    """Mutation control: in `run_critics`, stop setting `v["model"] = {"paused": …}` → the
    verdicts read as model approvals and this reds."""
    ir = _ir()
    calls = []
    out, _, _ = _run(
        ir, _evidence(pain0=True), invoke=lambda b: calls.append(b) or _approving(b), allowed=(False, "budget tier 2 — plan_critics paused")
    )
    assert calls == [], "no Bedrock call at a paused tier"
    crit = out["critics"]
    assert crit["model_ran"] is False and crit["model_paused_reason"].startswith("budget tier 2")
    assert all(v["model"] == {"paused": "budget tier 2 — plan_critics paused"} for v in crit["verdicts"])
    assert crit["veto"] is True, "the deterministic veto still fires at $0"
    assert "(model paused)" in crit["notes_preview"]


def test_the_model_calls_are_gated_by_the_plan_critics_budget_feature(monkeypatch):
    from ai import budget_guard

    assert budget_guard._FEATURE_CUTOFF["plan_critics"] == 2
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 1)
    monkeypatch.setitem(budget_guard._cache, "readable", True)
    assert tp._model_allowed() == (True, None)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 2)
    allowed, why = tp._model_allowed()
    assert allowed is False and "tier 2" in why and "plan_critics" in why


def test_an_unknown_routine_id_is_an_error_not_a_stage_1_answer():
    with patch("training.routine_repo.get_current", return_value=None):
        out = tp.tool_plan_next_session({"routine_id": "nope"})
    assert out.get("error_code") == "NOT_FOUND" or "NOT_FOUND" in json.dumps(out)


def test_stage_1_without_a_routine_id_runs_no_critics_and_says_so():
    with ExitStack() as st:
        for cm in _stage2_patches(_ir(), _evidence(), invoke=_approving)[:6] + [
            patch("training.training_notes.training_notes_health", side_effect=RuntimeError("offline"))
        ]:
            st.enter_context(cm)
        with patch("ai.bedrock_client.invoke", side_effect=AssertionError("no model in stage 1")):
            out = tp.tool_plan_next_session({"target_date": "2026-09-20"})
    assert "critics" not in out
    assert "NOT red-teamed" in out["how_to_use"]
    assert out["constraint_block"]["critics"]["ran"] is False


# ── the commit side ───────────────────────────────────────────────────────────
def _commit_patches(ir, created):
    def _create(body):
        created.append(body)
        return {"routine": {"id": "new-id", "updated_at": "2026-09-20T12:00:00Z"}}

    return [
        patch("training.routine_repo.get_current", return_value=ir),
        patch("training.routine_repo.put_versioned"),
        patch("training.routine_repo.upsert_id_map"),
        patch("training.hevy_template_cache.resolve_movement", return_value="55E6546B"),
        patch("training.routine_title.build_title_context", return_value=_TITLE_CTX),
        patch("training.hevy_write_client.list_folders", return_value=[]),
        patch("training.hevy_write_client.create_folder", return_value={"id": 1}),
        patch("training.hevy_write_client.create_routine", side_effect=_create),
        patch.object(
            wc,
            "verify_commit_landed",
            lambda rid, body, before: {"verified": True, "reason": None, "folder_id": None, "updated_at": "2026-09-20T12:00:00Z"},
        ),
    ]


def test_commit_without_stage_2_says_the_routine_was_not_red_teamed():
    """Mutation control: drop the `"critics": commit_status(ir)` line from the commit result → this reds."""
    ir = _ir()
    created = []
    with ExitStack() as st:
        for cm in _commit_patches(ir, created):
            st.enter_context(cm)
        res = t.tool_manage_hevy_routine({"action": "commit", "routine_id": ir.routine_id})
    assert res["status"] == "committed", res
    assert "NOT red-teamed" in res["critics"], res
    assert "warnings" not in res, "the note rides in its own key — a quiet commit keeps no warnings key (test_tools_hevy_routine)"
    assert "RED TEAM" not in created[0]["routine"]["exercises"][0]["notes"]


def test_commit_carries_the_verdicts_and_their_numbers_into_the_hevy_notes():
    """Box 4 (#3752): the routine's notes carry the four verdicts and the numbers they argued
    from. Mutation control (re-based 2026-09-20, #3938): drop the `_place_block_on_first_exercise(ir)`
    call in the plan engine → the wire notes (exercises[0], the channel Hevy returns) lose the block
    and this reds."""
    ir = _ir(squat_lbs=200.0)
    out, _, _ = _run(ir, _evidence())
    created = []
    with ExitStack() as st:
        for cm in _commit_patches(ir, created):
            st.enter_context(cm)
        res = t.tool_manage_hevy_routine({"action": "commit", "routine_id": ir.routine_id})
    assert res["status"] == "committed", res
    assert res["critics"] == "critics@1.0.0: muscle-defense approve, joints/tendons approve, rate-advocate approve, historian change"
    notes = created[0]["routine"]["exercises"][0]["notes"]
    assert "RED TEAM (critics@1.0.0, 4 critics," in notes
    for line in (
        "- muscle-defense APPROVE",
        "- joints/tendons APPROVE",
        "- rate-advocate APPROVE",
        "- historian CHANGE: band_top_lbs[0]=198.4 [owner]",
    ):
        assert line in notes, notes
    assert "detraining discount" in notes
    assert notes.startswith("Legs — quality day.")


def test_a_veto_stored_on_an_already_pushed_routine_blocks_the_update_branch_too():
    ir = _ir()
    ir.hevy_routine_id = "hevy-1"
    ir.hevy_updated_at = "2026-09-19T00:00:00Z"
    ir.inputs_snapshot["critics"] = {
        "engine": "critics@1.0.0",
        "ran_at": "x",
        "verdicts": [
            {"critic": "joints_tendons", "verdict": "veto", "reason": "pain flag on Squat", "metric": "pain_flag[0]", "value": True}
        ],
        "changes": [],
    }
    updated = []
    with ExitStack() as st:
        for cm in _commit_patches(ir, []) + [
            patch(
                "training.hevy_write_client.update_routine_with_guard",
                side_effect=lambda *a, **k: updated.append(a) or {"routine": {"id": "hevy-1", "updated_at": "z"}},
            )
        ]:
            st.enter_context(cm)
        res = t.tool_manage_hevy_routine({"action": "commit", "routine_id": ir.routine_id})
    assert "CRITIC_VETO" in json.dumps(res) and updated == []


def test_in_a_consistent_block_the_historian_does_not_cut_a_load_the_band_never_saw():
    ir = _ir(squat_lbs=200.0)
    out, _, _ = _run(ir, _evidence(weeks_in_block=3))
    h = next(v for v in out["critics"]["verdicts"] if v["critic"] == "blueprint_historian")
    assert h["verdict"] == "approve" and out["critics"]["changes"] == []
    assert ir.exercises[0].sets[0].weight_kg == pytest.approx(200.0 * KG, abs=0.01)


def test_weeks_in_block_counts_trailing_consistent_weeks_only():
    # weeks ending 09-19: [09-12..09-18] 4 lifts, [09-05..09-11] 2 lifts, [08-29..09-04] 1 lift -> 2
    dates = ["2026-09-18", "2026-09-16", "2026-09-14", "2026-09-12", "2026-09-10", "2026-09-06", "2026-09-01"]
    assert tp._weeks_in_block(dates, "2026-09-19") == 2
    assert tp._weeks_in_block([], "2026-09-19") == 0
    assert tp._weeks_in_block(["2026-09-19"], "2026-09-19") == 0, "the target day itself is not a trailing week"


# ── the stage-1 readers, held to the LIVE wire shapes (2026-09-20) ───────────
# The first deployed stage-2 run reported protein, recovery tier, ACWR and muscle volume
# all UNKNOWN on a day every one of them had data — each reader keyed on a name the live
# tool does not return. These fixtures are the wire shapes copied off the deployed tools.
_LIVE_NUTRITION = {
    "period": {"days_with_data": 6},
    "daily_breakdown": [
        {"date": "2026-09-13", "protein_g": 245.0},
        {"date": "2026-09-14", "protein_g": 105.0},
        {"date": "2026-09-15", "protein_g": 90.0},
        {"date": "2026-09-16", "protein_g": 200.0},
        {"date": "2026-09-17", "protein_g": 124.0},
        {"date": "2026-09-18", "protein_g": 164.0},
    ],
}
_LIVE_READINESS = {"date": "2026-09-19", "readiness_score": 80.1, "label": "GREEN"}
_LIVE_ACWR = {
    "date": "2026-09-18",
    "acwr": 1.241,
    "zone": "safe",
    "alert": False,
    "alert_reason": "ACWR 1.24 is within the safe zone (0.8–1.3).",
    "interpretation": "ACWR = EWMA(7d) ...",
}
_LIVE_VOLUME = {
    "muscle_volume": {"Back": {"total_sets": 20, "avg_sets_per_week": 23.3}, "Chest": {"total_sets": 37, "avg_sets_per_week": 43.2}}
}


def test_protein_days_read_the_live_daily_breakdown_key():
    with patch("mcp.tools_nutrition.tool_get_nutrition", return_value=_LIVE_NUTRITION):
        assert tp._protein_days_7d("2026-09-20") == (4, 6)
    with patch("mcp.tools_nutrition.tool_get_nutrition", return_value={"error": "No MacroFactor data"}):
        assert tp._protein_days_7d("2026-09-20") == (None, None)


def test_recovery_tier_reads_the_live_readiness_score_key():
    assert tp._recovery_tier(_LIVE_READINESS) == "green"
    assert tp._recovery_tier({"readiness_score": 50}) == "yellow"
    assert tp._recovery_tier({"readiness_score": 20}) == "red"
    assert tp._recovery_tier({}) is None


def test_muscle_sets_reads_the_live_muscle_volume_table():
    assert tp._muscle_sets(_LIVE_VOLUME) == {"Back": 23.3, "Chest": 43.2}
    assert tp._muscle_sets({}) == {}


def test_stage_1_block_is_populated_from_the_live_shapes_not_unknown():
    with ExitStack() as st:
        for cm in [
            patch("mcp.tools_benchmark.tool_get_benchmark", return_value=_REFERENCE),
            patch("mcp.tools_health.tool_get_readiness_score", return_value=_LIVE_READINESS),
            patch("mcp.tools_training.tool_get_acwr_status", return_value=_LIVE_ACWR),
            patch("mcp.tools_strength.tool_get_muscle_volume", return_value=_LIVE_VOLUME),
            patch("mcp.tools_nutrition.tool_get_nutrition", return_value=_LIVE_NUTRITION),
            patch("mcp.tools_plan._walk_hours_last_7d", return_value=5.09),
            patch("training.training_notes.training_notes_health", side_effect=RuntimeError("offline")),
        ]:
            st.enter_context(cm)
        out = tp.tool_plan_next_session({"target_date": "2026-09-20"})
    block = out["constraint_block"]
    assert block["recovery_tier"] == "green"
    assert block["acwr_flag"] == "safe"
    assert block["muscle_volume"] == {"Back": 23.3, "Chest": 43.2}
    tw = {t_["id"]: t_ for t_ in block["tripwires"]}
    assert tw["protein_floor_missed"]["state"] == "tripped" and "4 of 7" in tw["protein_floor_missed"]["observed"]
    assert out["protein_days_measured_7d"] == 6


def test_the_verdicts_ride_on_the_first_exercise_notes_the_channel_hevy_actually_returns():
    """LIVE FINDING 2026-09-20: Hevy's API routine object has no `notes` field; twelve September
    routines read back with 0-char routine notes while exercise notes landed. The block therefore
    goes on exercise[0].notes too, and a re-run replaces it rather than stacking.
    Mutation control: drop the `_place_block_on_first_exercise(ir)` call → this reds."""
    ir = _ir(squat_lbs=200.0)
    ir.exercises[0].notes = "Anchor cue."
    out, _, _ = _run(ir, _evidence())
    assert ir.exercises[0].notes.startswith("RED TEAM (critics@1.0.0, 4 critics,")
    assert ir.exercises[0].notes.endswith("Anchor cue.")
    assert "- historian CHANGE" in ir.exercises[0].notes
    # re-run: one block, not two
    ir.version = 1
    _run(ir, _evidence())
    assert ir.exercises[0].notes.count("RED TEAM (") == 1 and ir.exercises[0].notes.endswith("Anchor cue.")
    # and the compiled body carries it where the app shows it
    with ExitStack() as st:
        for cm in _commit_patches(ir, []):
            st.enter_context(cm)
        preview = t.tool_manage_hevy_routine({"action": "dry_run", "routine_id": ir.routine_id})
    wire_notes = preview["wire_body"]["routine"]["exercises"][0]["notes"]
    assert "RED TEAM (" in wire_notes and wire_notes.count("RED TEAM (") == 1  # #3938: WHY line first, block once


def test_a_second_stage_2_run_re_evaluates_the_coachs_draft_not_its_own_cut():
    """LIVE FINDING 2026-09-20: routine 73bc228c went 22 -> 18 -> 14 across two runs because the
    joints cut was applied to an already-cut draft. Mutation control: drop the restore-from-
    `draft_exercises` block → the second run sees 18 and this reds."""
    ir = RoutineSpec(
        routine_id="r-rerun",
        target_date="2026-09-20",
        archetype="pull",
        version=1,
        source_action="draft_custom",
        notes="Pull.",
        exercises=[
            ExerciseBlock(movement_key=f"tmpl:{i}", rationale_tag=f"Move {i}", sets=[Set(weight_kg=40, reps=10) for _ in range(4)])
            for i in range(5)
        ],
    )  # 20 sets

    def cut_by_4(body):
        # RELATIVE, like the live model: four sets off whatever draft it was handed. This is the
        # shape that compounded live; an absolute "to 16" fake let the first version of this test
        # pass with the restore disabled (mutation GREEN — a test that cannot fail, caught 2026-09-20).
        if "joints_tendons" in body["system"]:
            sent = json.loads(body["messages"][0]["content"].split("\nReturn the JSON object.")[0])
            to = sent["draft"]["total_sets"] - 4
            reply = {
                "verdict": "change",
                "metric": "consecutive_training_days",
                "value": 9,
                "field": "session.total_sets",
                "to": to,
                "sentence": f"Streak; trim to {to}.",
            }
            return {"content": [{"type": "text", "text": json.dumps(reply)}], "stop_reason": "end_turn"}
        return _approving(body)

    ev = _evidence()
    ev["consecutive_days"] = 9  # info flag on the metric the model cites
    ev["exercises"] = [
        {
            "idx": i,
            "label": f"Move {i}",
            "template_id": str(i),
            "days_since": 3,
            "pain_flag_any": False,
            "pain_dates": [],
            "pain_layer_status": "ok",
        }
        for i in range(5)
    ]
    out1, _, _ = _run(ir, ev, invoke=cut_by_4)
    assert out1["critics"]["recheck"]["total_sets"] == 16
    assert len(out1["critics"]["draft_exercises"]) == 5 and sum(len(e["sets"]) for e in out1["critics"]["draft_exercises"]) == 20
    out2, _, _ = _run(ir, ev, invoke=cut_by_4)
    assert out2["critics"]["recheck"]["total_sets"] == 16, "a re-run must land on the same cut, not cut again"
    assert sum(len(e.sets) for e in ir.exercises) == 16
