"""tests/test_hevy_routine_cron.py — gates, happy path, conflict handling."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def cron_module():
    import importlib
    import sys

    sys.modules.pop("operational.hevy_routine_cron_lambda", None)
    mod = importlib.import_module("operational.hevy_routine_cron_lambda")
    return mod


def _ssm_returns(values: dict[str, str]):
    """Build a side_effect that returns the right value per SSM param."""

    def fake_get(name: str, default: str = "") -> str:
        return values.get(name, default)

    return fake_get


def test_noop_when_paused(cron_module):
    with patch.object(
        cron_module,
        "_ssm_get",
        side_effect=_ssm_returns({"/life-platform/pause-mode": "paused", "/life-platform/hevy/cron_enabled": "true"}),
    ):
        result = cron_module.lambda_handler({}, None)
    assert result["status"] == "noop"
    assert "pause" in result["reason"]


def test_noop_when_cron_disabled(cron_module):
    with patch.object(
        cron_module,
        "_ssm_get",
        side_effect=_ssm_returns({"/life-platform/pause-mode": "active", "/life-platform/hevy/cron_enabled": "false"}),
    ):
        result = cron_module.lambda_handler({}, None)
    assert result["status"] == "noop"
    assert "cron_enabled" in result["reason"]


def test_noop_when_budget_tier_3(cron_module):
    with patch.object(
        cron_module,
        "_ssm_get",
        side_effect=_ssm_returns(
            {"/life-platform/pause-mode": "active", "/life-platform/hevy/cron_enabled": "true", "/life-platform/budget-tier": "3"}
        ),
    ):
        result = cron_module.lambda_handler({}, None)
    assert result["status"] == "noop"
    assert "budget_tier" in result["reason"]


def test_force_overrides_all_gates(cron_module, monkeypatch):
    """force=True still requires all downstream calls; mock them out."""
    with patch.object(
        cron_module,
        "_ssm_get",
        side_effect=_ssm_returns({"/life-platform/pause-mode": "paused", "/life-platform/hevy/cron_enabled": "false"}),
    ):
        with patch("routine_generator.generate_routines", return_value=[]), patch("routine_repo.put_versioned"):
            result = cron_module.lambda_handler({"force": True, "target_date": "2026-06-01"}, None)
    assert result["status"] == "ok"
    assert result["routines"] == []


def _ideal_floor_pair():
    """A minimal ideal + floor variant pair with pushable exercises (#417)."""
    from routine_ir import ExerciseBlock, RoutineSpec, Set

    def _mk(variant, rid):
        return RoutineSpec(
            routine_id=rid,
            target_date="2026-06-01",
            archetype="upper",
            variant=variant,
            rationale=[f"{variant} rationale line"],
            exercises=[ExerciseBlock(movement_key="db_bench_press_flat", sets=[Set(type="normal", reps=10)])],
        )

    ideal = _mk("ideal", "id-ideal")
    floor = _mk("floor", "id-floor")
    ideal.sibling_routine_id = floor.routine_id
    floor.sibling_routine_id = ideal.routine_id
    return [ideal, floor]


def test_cron_pushes_branch_model_not_ideal_floor_pair(cron_module):
    """#417 TR-04: the scheduled path pushes ONE branched routine, folding the floor
    into a branch instead of dropping it."""
    import hevy_write_client as wc

    captured = {}

    def _fake_create(body):
        captured["body"] = body
        return {"routine": {"id": "hevy-xyz", "updated_at": "2026-06-01T13:00:00Z"}}

    with patch.object(
        cron_module,
        "_ssm_get",
        side_effect=_ssm_returns({"/life-platform/pause-mode": "active", "/life-platform/hevy/cron_enabled": "true"}),
    ):
        with patch("routine_generator.generate_routines", return_value=_ideal_floor_pair()):
            with patch("routine_repo.put_versioned"), patch("routine_repo.upsert_id_map"):
                with patch("hevy_template_cache.resolve_movement", return_value="TID"):
                    with patch("routine_title.build_title_context", return_value=None):
                        with patch("routine_title.format_why_note", return_value="Programmed."):
                            with patch.object(wc, "create_routine", side_effect=_fake_create):
                                result = cron_module.lambda_handler({"target_date": "2026-06-01"}, None)

    assert result["status"] == "ok"
    pushed = [r for r in result["routines"] if r.get("pushed")]
    assert len(pushed) == 1  # exactly one routine pushed
    assert set(pushed[0]["branches"]) == {"as-written", "easier"}  # floor folded in, not dropped
    # The pushed body's notes carry the branch menu.
    assert "CHOOSE YOUR BRANCH" in captured["body"]["routine"]["notes"]
    assert "EASIER" in captured["body"]["routine"]["notes"]
