"""tests/test_hevy_restamp.py — overnight branch re-stamp (#417 / TR-05).

Covers: gates, the pure recovery→branch selection core, the never-removes-a-branch
invariant, the safe default, and fail-open behaviour on every error path.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from routine_ir import RoutineBranch, RoutineSpec


@pytest.fixture
def restamp():
    import importlib
    import sys

    sys.modules.pop("operational.hevy_restamp_lambda", None)
    return importlib.import_module("operational.hevy_restamp_lambda")


def _ssm_returns(values: dict[str, str]):
    def fake_get(name: str, default: str = "") -> str:
        return values.get(name, default)

    return fake_get


def _branches():
    return [
        RoutineBranch(label="as-written", cue="the plan", recommended=True, order=0),
        RoutineBranch(label="easier", cue="min dose", recommended=False, order=1),
    ]


# ── Gates ─────────────────────────────────────────────────────────────────────


def test_noop_when_paused(restamp):
    with patch.object(
        restamp,
        "_ssm_get",
        side_effect=_ssm_returns({"/life-platform/pause-mode": "paused", "/life-platform/hevy/restamp_enabled": "true"}),
    ):
        result = restamp.lambda_handler({}, None)
    assert result["status"] == "noop"
    assert "pause" in result["reason"]


def test_noop_when_disabled(restamp):
    with patch.object(
        restamp,
        "_ssm_get",
        side_effect=_ssm_returns({"/life-platform/pause-mode": "active", "/life-platform/hevy/restamp_enabled": "false"}),
    ):
        result = restamp.lambda_handler({}, None)
    assert result["status"] == "noop"
    assert "restamp_enabled" in result["reason"]


def test_noop_when_budget_tier_3(restamp):
    with patch.object(
        restamp,
        "_ssm_get",
        side_effect=_ssm_returns(
            {
                "/life-platform/pause-mode": "active",
                "/life-platform/hevy/restamp_enabled": "true",
                "/life-platform/budget-tier": "3",
            }
        ),
    ):
        result = restamp.lambda_handler({}, None)
    assert result["status"] == "noop"
    assert "budget_tier" in result["reason"]


# ── Pure selection core ───────────────────────────────────────────────────────


def test_preference_safe_default_when_no_recovery(restamp):
    assert restamp.preference_for_recovery(None) == ["as-written"]


def test_preference_green_reaches_for_harder(restamp):
    pref = restamp.preference_for_recovery(80)
    assert pref[0] == "harder"
    assert "as-written" in pref


def test_preference_red_steps_down(restamp):
    pref = restamp.preference_for_recovery(20)
    assert pref[0] == "easier"


def test_pick_label_only_uses_present_branches(restamp):
    # Green wants "harder" but it doesn't exist → falls back to as-written.
    assert restamp.pick_label(80, ["as-written", "easier"]) == "as-written"


def test_restamp_red_recommends_easier(restamp):
    reordered, chosen, changed = restamp.restamp_branches(_branches(), 20)
    assert chosen == "easier"
    assert changed is True
    assert reordered[0].label == "easier"
    assert reordered[0].recommended is True
    assert sum(b.recommended for b in reordered) == 1


def test_restamp_yellow_keeps_as_written(restamp):
    reordered, chosen, changed = restamp.restamp_branches(_branches(), 50)
    assert chosen == "as-written"
    # already the recommendation + already first → no change, so no re-push.
    assert changed is False


def test_restamp_never_removes_a_branch(restamp):
    for score in (None, 10, 33, 34, 66, 67, 100):
        branches = _branches() + [RoutineBranch(label="re-entry", order=2)]
        reordered, _, _ = restamp.restamp_branches(branches, score)
        assert len(reordered) == 3
        assert {b.label for b in reordered} == {"as-written", "easier", "re-entry"}


def test_restamp_never_touches_set_content(restamp):
    from routine_ir import ExerciseBlock, Set

    branches = [
        RoutineBranch(label="as-written", recommended=True, order=0),
        RoutineBranch(
            label="easier",
            order=1,
            exercises=[ExerciseBlock(movement_key="m", sets=[Set(type="normal", weight_kg=40.0, reps=8)])],
        ),
    ]
    restamp.restamp_branches(branches, 20)
    easier = next(b for b in branches if b.label == "easier")
    assert easier.exercises[0].sets[0].weight_kg == 40.0
    assert easier.exercises[0].sets[0].reps == 8


def test_restamp_empty_branches(restamp):
    assert restamp.restamp_branches([], 50) == ([], None, False)


# ── Fail-open I/O paths ───────────────────────────────────────────────────────


def _enabled_ssm():
    return _ssm_returns(
        {
            "/life-platform/pause-mode": "active",
            "/life-platform/hevy/restamp_enabled": "true",
            "/life-platform/budget-tier": "0",
        }
    )


def test_noop_when_no_pushed_routine(restamp):
    with patch.object(restamp, "_ssm_get", side_effect=_enabled_ssm()):
        with patch.object(restamp, "_find_pushed_routine", return_value=None):
            result = restamp.lambda_handler({"target_date": "2026-06-01"}, None)
    assert result["status"] == "noop"
    assert result["reason"] == "no-pushed-branched-routine"


def test_fail_open_on_unexpected_exception(restamp):
    with patch.object(restamp, "_ssm_get", side_effect=_enabled_ssm()):
        with patch.object(restamp, "_find_pushed_routine", side_effect=RuntimeError("boom")):
            result = restamp.lambda_handler({"target_date": "2026-06-01"}, None)
    # Never raises; returns a no-op so the morning routine stays usable.
    assert result["status"] == "noop"
    assert result["reason"] == "error-failed-open"


def test_unchanged_recommendation_no_repush(restamp):
    ir = RoutineSpec(
        routine_id="r1",
        target_date="2026-06-01",
        archetype="upper",
        hevy_routine_id="hevy-1",
        branches=_branches(),  # as-written already recommended + first
    )
    with patch.object(restamp, "_ssm_get", side_effect=_enabled_ssm()):
        with patch.object(restamp, "_find_pushed_routine", return_value=ir):
            with patch.object(restamp, "_latest_recovery_score", return_value=50):  # yellow → as-written
                result = restamp.lambda_handler({"target_date": "2026-06-01"}, None)
    assert result["status"] == "noop"
    assert result["reason"] == "recommendation-already-current"


def test_applies_and_repushes_on_change(restamp):
    ir = RoutineSpec(
        routine_id="r1",
        target_date="2026-06-01",
        archetype="upper",
        version=1,
        hevy_routine_id="hevy-1",
        hevy_updated_at="2026-06-01T10:00:00Z",
        branches=_branches(),
    )

    import hevy_write_client as wc

    fake_resp = {"routine": {"id": "hevy-1", "updated_at": "2026-06-01T13:00:00Z"}}
    with patch.object(restamp, "_ssm_get", side_effect=_enabled_ssm()):
        with patch.object(restamp, "_find_pushed_routine", return_value=ir):
            with patch.object(restamp, "_latest_recovery_score", return_value=20):  # red → easier
                with patch.object(wc, "update_routine_with_guard", return_value=fake_resp) as push:
                    with patch("routine_repo.put_versioned"):
                        with patch("hevy_template_cache.resolve_movement", return_value="TID"):
                            with patch("routine_title.build_title_context", return_value=None):
                                with patch("routine_title.format_why_note", return_value="why"):
                                    result = restamp.lambda_handler({"target_date": "2026-06-01"}, None)
    assert result["status"] == "ok"
    assert result["recommended"] == "easier"
    assert push.called
    # version bumped, recommended branch is now easier
    assert ir.version == 2
    assert next(b for b in ir.branches if b.recommended).label == "easier"


def test_conflict_fails_open(restamp):
    ir = RoutineSpec(
        routine_id="r1",
        target_date="2026-06-01",
        archetype="upper",
        hevy_routine_id="hevy-1",
        hevy_updated_at="2026-06-01T10:00:00Z",
        branches=_branches(),
    )
    import hevy_write_client as wc

    with patch.object(restamp, "_ssm_get", side_effect=_enabled_ssm()):
        with patch.object(restamp, "_find_pushed_routine", return_value=ir):
            with patch.object(restamp, "_latest_recovery_score", return_value=20):
                with patch.object(wc, "update_routine_with_guard", side_effect=wc.HevyConflict("edited in-app")):
                    with patch("hevy_template_cache.resolve_movement", return_value="TID"):
                        with patch("routine_title.build_title_context", return_value=None):
                            with patch("routine_title.format_why_note", return_value="why"):
                                result = restamp.lambda_handler({"target_date": "2026-06-01"}, None)
    assert result["status"] == "noop"
    assert result["reason"] == "in-app-edit-conflict"
