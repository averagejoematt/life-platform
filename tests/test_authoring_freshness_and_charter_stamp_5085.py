"""tests/test_authoring_freshness_and_charter_stamp_5085.py — #5085 D6.

1. The authoring gate refuses a stale Whoop recovery or a stale Hevy workout BY NAME, with the thresholds
   read from the source registry (never typed): `blocked_stale_inputs: whoop recovery 61 h old > 48 h`.
2. Every drafted plan carries `inputs_snapshot.charter_version` — `draft`, `draft_custom` and the nightly
   predraft marker — and the committed routine's spec-ledger row carries it too.
The clock is passed in (`now=`), never read.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from ingestion import source_registry  # noqa: E402
from training import routine_repo  # noqa: E402
from training.routine_ir import RoutineSpec  # noqa: E402
from training.training_charter import charter_version  # noqa: E402

from mcp import authoring_input_age as age  # noqa: E402

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


# ── 1. the age gate ────────────────────────────────────────────────────────────
def test_thresholds_are_the_registry_facets_not_typed():
    assert age.threshold_hours("hevy") == source_registry.SOURCE_REGISTRY["hevy"]["stale_hours"]
    # whoop declares none: the registry's own default is the bar
    assert source_registry.SOURCE_REGISTRY["whoop"]["stale_hours"] is None
    assert age.threshold_hours("whoop") == source_registry.DEFAULT_STALE_HOURS


def test_a_stale_whoop_recovery_is_refused_with_a_named_reason():
    # latest recovery 2026-10-16: its UTC day ended 2026-10-17 00:00Z, 60 h before NOW
    gaps = age.assess_input_age("2026-10-16", "2026-10-19", NOW)
    assert [g["input"] for g in gaps] == ["whoop"]
    assert gaps[0]["reason"] == f"blocked_stale_inputs: whoop recovery 60 h old > {source_registry.DEFAULT_STALE_HOURS} h"


def test_a_fresh_recovery_and_workout_pass():
    assert age.assess_input_age("2026-10-19", "2026-10-18", NOW) == []


def test_a_stale_hevy_workout_is_refused_only_while_lifting_is_expected():
    limit = source_registry.SOURCE_REGISTRY["hevy"]["stale_hours"]
    gaps = age.assess_input_age("2026-10-19", "2026-10-05", NOW)
    assert [g["input"] for g in gaps] == ["hevy"] and gaps[0]["reason"].endswith(f"> {limit} h")
    assert age.assess_input_age("2026-10-19", "2026-10-05", NOW, hevy_expected=False) == []


def test_a_changed_registry_facet_moves_the_bar():
    with patch.dict(source_registry.SOURCE_REGISTRY["hevy"], {"stale_hours": 24 * 30}):
        assert age.assess_input_age("2026-10-19", "2026-10-05", NOW) == []


def test_nothing_on_record_is_not_this_gates_finding():
    assert age.assess_input_age(None, None, NOW) == []


def test_add_input_age_flips_the_gate_and_keeps_existing_gaps():
    gate = {"ok": True, "gaps": []}
    with patch.object(age, "_latest_hevy_date", return_value="2026-10-01"), patch.object(age, "_lifting_expected", return_value=True):
        out = age.add_input_age(gate, "2026-10-19", "2026-10-20", now=NOW)
    assert out["ok"] is False and out["gaps"][0]["input"] == "hevy" and out["latest_hevy"] == "2026-10-01"


def test_add_input_age_is_fail_soft_on_a_read_failure():
    with (
        patch.object(age, "_latest_hevy_date", side_effect=RuntimeError("ddb down")),
        patch.object(age, "_lifting_expected", return_value=True),
    ):
        out = age.add_input_age({"ok": True, "gaps": []}, "2026-10-19", "2026-10-20", now=NOW)
    assert out["ok"] is True


def test_the_draft_gate_runs_the_age_check():
    import inspect

    from mcp import tools_hevy_routine

    assert "add_input_age(gate" in inspect.getsource(tools_hevy_routine._authoring_freshness_gate)


# ── 2. the charter stamp ───────────────────────────────────────────────────────
class _Repo:
    def __init__(self):
        self.written = []

    def get_current(self, _rid):
        return None

    def put_versioned(self, ir):
        self.written.append(ir)
        return ir


def test_the_charter_version_is_real():
    assert charter_version()


def test_draft_versioned_stamps_every_drafted_plan():
    repo = _Repo()
    ir = RoutineSpec(routine_id="r-5085", target_date="2026-10-20", archetype="upper", variant="ideal", created_by="cron")
    with patch.object(routine_repo, "get_current", repo.get_current), patch.object(routine_repo, "put_versioned", repo.put_versioned):
        routine_repo.draft_versioned(ir)
    assert repo.written[0].inputs_snapshot["charter_version"] == charter_version()


def test_the_draft_action_persists_through_the_stamping_seam():
    from mcp import tools_hevy_routine

    ir = RoutineSpec(routine_id="r-d", target_date="2026-10-20", archetype="upper", variant="ideal", created_by="cron")
    repo = _Repo()
    with (
        patch.object(tools_hevy_routine, "_authoring_freshness_gate", return_value={"ok": True, "gaps": []}),
        patch.object(tools_hevy_routine, "_generator_inputs", return_value=type("I", (), {"target_date": "2026-10-20"})()),
        patch("training.routine_generator.generate_routines", return_value=[ir]),
        patch.object(tools_hevy_routine, "_gather_training_context", return_value={}),
        patch("mcp.draft_standing_constraint.gate_draft", return_value={"adaptation": {}}),
        patch.object(routine_repo, "get_current", repo.get_current),
        patch.object(routine_repo, "put_versioned", repo.put_versioned),
    ):
        out = tools_hevy_routine._action_draft({"target_date": "2026-10-20"})
    assert out["status"] == "drafted"
    assert repo.written and repo.written[0].inputs_snapshot["charter_version"] == charter_version()


def test_the_draft_action_refuses_a_stale_input_by_name():
    from mcp import tools_hevy_routine

    gaps = age.assess_input_age("2026-10-10", None, NOW)
    with patch.object(tools_hevy_routine, "_authoring_freshness_gate", return_value={"ok": False, "gaps": gaps}):
        out = tools_hevy_routine._action_draft({"target_date": "2026-10-20"})
    assert out["status"] == "blocked_stale_inputs" and out["gaps"][0]["reason"].startswith("blocked_stale_inputs: whoop recovery")


def test_the_draft_custom_action_stamps_the_charter_version():
    import test_draft_custom_slot_inherit_5005 as t5005

    repo = _Repo()
    exercises = [
        {"movement_key": e["movement_key"], "sets": e["sets"]}
        for e in t5005.WIRE["drafts_2026_10_18"]["custom"]["exercises"]
        if e["movement_key"] in t5005.PROGRAM_KEYS
    ]
    from mcp import tools_hevy_routine

    with (
        patch.object(routine_repo, "get_current", repo.get_current),
        patch.object(routine_repo, "put_versioned", repo.put_versioned),
        patch("mcp.plan_hevy_windows._block_workouts", return_value=t5005.ROWS),
        patch("mcp.plan_cardio_pick.draft_cardio_warnings", return_value=[]),
        patch("training.routine_generator.attach_cardio_cues", return_value=0),
    ):
        resp = tools_hevy_routine._action_draft_custom({"exercises": exercises, "target_date": t5005.DAY})
    assert resp["status"] == "drafted_custom"
    assert repo.written[-1].inputs_snapshot["charter_version"] == charter_version()


def test_the_predraft_marker_carries_the_charter_version():
    import test_nightly_predraft_4084 as t4084

    out, repo, _drafts = t4084._run_4568(t4084._on_file_4568(status="archived"))
    assert out["outcome"] == t4084.npd.DRAFTED
    snap = repo.get_current(t4084.LIVE_IDEAL_4568).inputs_snapshot
    assert snap[t4084.npd.MARKER]["charter_version"] == charter_version() == snap["charter_version"]


def test_the_committed_routine_spec_row_carries_the_charter_version():
    from mcp.routine_spec_ledger import build_spec

    ir = RoutineSpec(
        routine_id="r-s",
        target_date="2026-10-20",
        archetype="upper",
        variant="ideal",
        created_by="chat",
        inputs_snapshot={"charter_version": "1.5.0"},
    )
    assert build_spec(ir)["charter_version"] == "1.5.0"
