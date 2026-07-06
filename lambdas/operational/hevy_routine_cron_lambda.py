"""
hevy_routine_cron_lambda.py — Phase 3 scheduled routine generator (ADR-066).

Reads SSM gates: no-ops when paused, when cron_enabled=false, or when
budget tier ≥ 3. Otherwise generates a routine for the target date, persists
the IR, compiles via hevy_compiler, and pushes through hevy_write_client.

Default schedule: Sunday 06:30 PT (cron 30 13 * * SUN — UTC fixed). The
EventBridge rule ships disabled; operator flips it on after ~3 weeks of
Phase 1 chat-path usage justifies it.

Failures:
  HevyRetryable  → raise (Lambda async retry → DLQ → operator inspects)
  HevyConflict   → do NOT retry (re-read would see same mismatch); emit
                   metric, log, return success-with-warning so DLQ doesn't
                   poison-pill on a routine-edit-in-app conflict.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from typing import Any

import boto3

try:
    from platform_logger import get_logger

    logger = get_logger("hevy-routine-cron")
except ImportError:
    logger = logging.getLogger("hevy-routine-cron")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
PAUSE_PARAM = os.environ.get("PAUSE_MODE_PARAM", "/life-platform/pause-mode")
BUDGET_TIER_PARAM = os.environ.get("BUDGET_TIER_PARAM", "/life-platform/budget-tier")
CRON_ENABLED_PARAM = os.environ.get("HEVY_CRON_ENABLED_PARAM", "/life-platform/hevy/cron_enabled")
ADD_LOAD_PARAM = os.environ.get("HEVY_ADD_LOAD_PARAM", "/life-platform/hevy/autoreg_add_load_enabled")

_ssm = boto3.client("ssm", region_name=REGION)
_cw = boto3.client("cloudwatch", region_name=REGION)


def _ssm_get(name: str, default: str = "") -> str:
    try:
        resp = _ssm.get_parameter(Name=name)
        return (resp.get("Parameter", {}).get("Value") or "").strip()
    except _ssm.exceptions.ParameterNotFound:
        return default
    except Exception as e:
        logger.warning(f"SSM read failed for {name}: {e}")
        return default


def _emit_metric(metric_name: str, value: float = 1.0, unit: str = "Count") -> None:
    try:
        _cw.put_metric_data(
            Namespace="LifePlatform/HevyRoutine",
            MetricData=[{"MetricName": metric_name, "Value": value, "Unit": unit}],
        )
    except Exception as e:
        logger.warning(f"metric emit failed for {metric_name}: {e}")


def _target_date_for_event(event: dict[str, Any]) -> str:
    if event.get("target_date"):
        return event["target_date"]
    return date.today().isoformat()


def _gates(event: dict[str, Any]) -> dict[str, str | bool]:
    pause = _ssm_get(PAUSE_PARAM, "active").lower()
    cron_enabled = _ssm_get(CRON_ENABLED_PARAM, "false").lower() in ("1", "true", "yes")
    budget_tier_raw = _ssm_get(BUDGET_TIER_PARAM, "0")
    try:
        budget_tier = int(budget_tier_raw)
    except ValueError:
        budget_tier = 0
    add_load_enabled = _ssm_get(ADD_LOAD_PARAM, "false").lower() in ("1", "true", "yes")
    force = bool(event.get("force"))
    return {
        "pause": pause,
        "cron_enabled": cron_enabled,
        "budget_tier": budget_tier,
        "add_load_enabled": add_load_enabled,
        "force": force,
    }


def _gather_inputs(target_date: str, add_load_enabled: bool) -> "GeneratorInputs":  # noqa: F821
    """Pull recovery / acwr / volume / z2 / last-workout state for the generator.

    Day one: returns conservative defaults so the deterministic engine ships
    safely without a live tools_strength/get_muscle_volume integration. Phase 2
    swaps the placeholders for direct DDB reads.
    """
    from routine_generator import GeneratorInputs

    return GeneratorInputs(
        target_date=target_date,
        recovery_tier="yellow",
        acwr_flag="safe",
        volume_7d={},
        z2_minutes_7d=0.0,
        days_since_last_workout=2,
        add_load_enabled=add_load_enabled,
    )


def lambda_handler(event, context):
    try:
        gates = _gates(event or {})
        logger.info(f"gates={gates}")

        if gates["pause"] == "paused" and not gates["force"]:
            _emit_metric("CronNoOpPaused")
            return {"status": "noop", "reason": "pause-mode=paused"}
        if not gates["cron_enabled"] and not gates["force"]:
            _emit_metric("CronNoOpDisabled")
            return {"status": "noop", "reason": "cron_enabled=false"}
        if gates["budget_tier"] >= 3 and not gates["force"]:
            _emit_metric("CronNoOpBudgetTier3")
            return {"status": "noop", "reason": "budget_tier>=3"}

        target_date = _target_date_for_event(event or {})
        inputs = _gather_inputs(target_date, gates["add_load_enabled"])

        import hevy_write_client as wc
        import routine_repo as repo
        from hevy_compiler import to_create_body
        from hevy_template_cache import resolve_movement
        from routine_generator import emit_branch_model, generate_routines
        from routine_title import build_title_context, format_why_note

        routines = generate_routines(inputs)
        # #417 (TR-04): fold the generated variants (ideal + floor + optional
        # re-entry) into ONE primary routine carrying first-class branches. We
        # push the branch model — a single routine whose morning selection is a
        # branch choice — instead of the legacy "push only ideal, drop floor".
        primary = emit_branch_model(routines)
        logger.info(
            f"generated {len(routines)} variant(s) for {target_date}: "
            f"{[r.variant for r in routines]}; "
            f"branch model primary={getattr(primary, 'routine_id', None)} "
            f"branches={[b.label for b in (getattr(primary, 'branches', []) or [])]}"
        )

        summary: list[dict[str, Any]] = []
        pushed_one = False
        for ir in routines:
            repo.put_versioned(ir)
            # Push only the primary (branch-carrying) routine. Siblings are
            # persisted above for the record but folded into the primary's
            # branch menu — they are not pushed as separate routines anymore.
            if primary is None or ir.routine_id != primary.routine_id or pushed_one or not ir.exercises:
                summary.append({"routine_id": ir.routine_id, "variant": ir.variant, "pushed": False})
                continue
            try:
                title_ctx = build_title_context(ir)
                why = format_why_note(ir)
                body = to_create_body(ir, resolve_movement, title_context=title_ctx, why_note=why)
                resp = wc.create_routine(body)
                from hevy_compiler import from_hevy_response

                parsed = from_hevy_response(resp)
                ir.hevy_routine_id = parsed["hevy_routine_id"]
                ir.hevy_updated_at = parsed["updated_at"]
                ir.hevy_pushed_at = datetime.now(timezone.utc).isoformat()
                ir.status = "active"
                ir.version += 1
                ir.parent_version = ir.version - 1
                repo.put_versioned(ir)
                if ir.hevy_routine_id:
                    repo.upsert_id_map(ir.routine_id, ir.hevy_routine_id)
                pushed_one = True
                _emit_metric("RoutinePushed")
                summary.append(
                    {
                        "routine_id": ir.routine_id,
                        "variant": ir.variant,
                        "pushed": True,
                        "hevy_routine_id": ir.hevy_routine_id,
                        "branches": [b.label for b in (ir.branches or [])],
                    }
                )
            except wc.HevyOrphanCreated as e:
                logger.warning(
                    f"HevyOrphanCreated on push for {ir.routine_id}: " f"Hevy returned {e.status} but created {e.hevy_routine_id}. Linking."
                )
                ir.hevy_routine_id = e.hevy_routine_id
                ir.hevy_updated_at = e.hevy_updated_at
                ir.hevy_pushed_at = datetime.now(timezone.utc).isoformat()
                ir.status = "active"
                ir.version += 1
                ir.parent_version = ir.version - 1
                repo.put_versioned(ir)
                if ir.hevy_routine_id:
                    try:
                        repo.upsert_id_map(ir.routine_id, ir.hevy_routine_id)
                    except Exception:
                        pass
                _emit_metric("RoutineOrphanRecovered")
                summary.append(
                    {
                        "routine_id": ir.routine_id,
                        "variant": ir.variant,
                        "pushed": True,
                        "hevy_routine_id": ir.hevy_routine_id,
                        "warning": f"orphan-recovered (status={e.status})",
                    }
                )
                pushed_one = True
            except wc.HevyConflict as e:
                logger.warning(f"HevyConflict on push for {ir.routine_id}: {e}")
                _emit_metric("RoutineConflict")
                summary.append({"routine_id": ir.routine_id, "variant": ir.variant, "pushed": False, "error": "conflict"})
            except wc.HevyRetryable:
                _emit_metric("RoutineRetryable")
                raise

        return {"status": "ok", "target_date": target_date, "gates": gates, "routines": summary}
    except Exception:
        # Let HevyRetryable + boto3 transient errors propagate to Lambda async
        # retry → DLQ. Log + re-raise rather than swallow.
        logger.exception("hevy-routine-cron failed; raising to DLQ")
        raise
