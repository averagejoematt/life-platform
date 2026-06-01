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
    with patch.object(cron_module, "_ssm_get",
                      side_effect=_ssm_returns({"/life-platform/pause-mode": "paused",
                                                "/life-platform/hevy/cron_enabled": "true"})):
        result = cron_module.lambda_handler({}, None)
    assert result["status"] == "noop"
    assert "pause" in result["reason"]


def test_noop_when_cron_disabled(cron_module):
    with patch.object(cron_module, "_ssm_get",
                      side_effect=_ssm_returns({"/life-platform/pause-mode": "active",
                                                "/life-platform/hevy/cron_enabled": "false"})):
        result = cron_module.lambda_handler({}, None)
    assert result["status"] == "noop"
    assert "cron_enabled" in result["reason"]


def test_noop_when_budget_tier_3(cron_module):
    with patch.object(cron_module, "_ssm_get",
                      side_effect=_ssm_returns({"/life-platform/pause-mode": "active",
                                                "/life-platform/hevy/cron_enabled": "true",
                                                "/life-platform/budget-tier": "3"})):
        result = cron_module.lambda_handler({}, None)
    assert result["status"] == "noop"
    assert "budget_tier" in result["reason"]


def test_force_overrides_all_gates(cron_module, monkeypatch):
    """force=True still requires all downstream calls; mock them out."""
    with patch.object(cron_module, "_ssm_get",
                      side_effect=_ssm_returns({"/life-platform/pause-mode": "paused",
                                                "/life-platform/hevy/cron_enabled": "false"})):
        with patch("routine_generator.generate_routines", return_value=[]), \
             patch("routine_repo.put_versioned"):
            result = cron_module.lambda_handler({"force": True,
                                                 "target_date": "2026-06-01"}, None)
    assert result["status"] == "ok"
    assert result["routines"] == []
