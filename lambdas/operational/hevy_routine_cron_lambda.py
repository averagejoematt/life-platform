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
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import boto3
from common.pacific_time import pacific_today, shift_day_key  # #2798: routine target_date is a Pacific-day WRITE KEY

if TYPE_CHECKING:  # #1656: the annotation-only import (runtime import stays inside the function)
    from training.routine_generator import GeneratorInputs

try:
    from common.platform_logger import get_logger

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
    # #2798 — THE PAIR. `target_date` is a WRITE KEY: `training.routine_repo` derives
    # `routine_id` from (target_date, archetype, variant) (#3115) and indexes the routine
    # at `DATE#{target_date}#ROUTINE#…`. The other author of that same key is
    # `mcp.tools_hevy_routine`, used interactively in PT evenings — so a UTC day here and
    # a UTC day there agreed only by accident of this cron's 06:30-PT slot. Both sides move
    # to Pacific in one change; converting either alone authors a different routine row.
    return pacific_today()


def _gates(event: dict[str, Any]) -> dict[str, str | bool | int]:
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


def _read_partition(source: str, start: str, end: str) -> list[dict[str, Any]]:
    """Every row of `source` in [start, end] — the bundled twin of `mcp.core.query_source`'s derived
    read: the phase decision from the taxonomy, full pagination, superseded (tombstoned) rows out."""
    from boto3.dynamodb.conditions import Key
    from common.strava_read_seam import strava_read_seam  # #4419: multi-device strava duplicates removed at the read
    from experiment.phase_filter import source_reads_cross_phase, with_phase_filter
    from training import exercise_history

    pk = f"USER#{exercise_history.USER_ID}#SOURCE#{source}"
    kwargs: dict[str, Any] = with_phase_filter(
        {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{start}", f"DATE#{end}~")},
        include_pilot=source_reads_cross_phase(source),
    )
    rows: list[dict[str, Any]] = []
    while True:
        resp = exercise_history._table().query(**kwargs)
        rows.extend(i for i in resp.get("Items", []) if not i.get("tombstone"))
        if not resp.get("LastEvaluatedKey"):
            return strava_read_seam(source, rows)
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _read_corrections(start: str, end: str) -> list[dict[str, Any]] | None:
    """The owner's WALK_CORRECTION# rows in [start, end] (#5669), the bundled twin of
    `mcp.shared_quantities._read_corrections`; a raise is None (unreadable — the corrected day keeps its gap)."""
    from training import exercise_history, walking_volume

    try:
        return walking_volume.query_corrections(exercise_history._table(), start, end)
    except Exception as e:  # noqa: BLE001 — unreadable is reported by the block, never raised past it
        logger.warning(f"recent-aerobic correction read failed: {e}")
        return None


def _z2_minutes_7d(target_date: str, read=None) -> float | None:
    """#4410: the generator's aerobic minutes from the ONE recent-aerobic quantity
    (`training.recent_aerobic`, the block `mcp.shared_quantities.recent_aerobic_layer` builds) —
    never a hard-coded 0. A source that cannot be read reaches the block as None, and the
    minutes come back None (UNKNOWN, ADR-104): no "walk more" note on an unread week."""
    from training import recent_aerobic, walking_volume

    w = recent_aerobic.window(target_date)

    def _safe(source: str) -> list[dict[str, Any]] | None:
        try:
            return (read or _read_partition)(source, w["start"], w["end"])
        except Exception as e:  # noqa: BLE001 — unreadable is unknown, never zero hours
            logger.warning(f"recent-aerobic read failed for {source}: {e}")
            return None

    def _safe_apple() -> list[dict[str, Any]] | None:
        # #5369: the watch backstop — one UTC day past the window (a workout is keyed by its UTC start day)
        try:
            return (read or _read_partition)("apple_health", w["start"], shift_day_key(w["end"], 1))
        except Exception as e:  # noqa: BLE001 — unreadable is a floor, never zero hours
            logger.warning(f"recent-aerobic read failed for apple_health: {e}")
            return None

    def _signals() -> dict[str, list[dict[str, Any]] | None]:
        # #5669: WHOOP one UTC day past the window (its rows are keyed by the UTC day of the start)
        out: dict[str, list[dict[str, Any]] | None] = {}
        for source, past in walking_volume.COMPLETENESS_READ_PAST_END_DAYS.items():
            try:
                out[source] = (read or _read_partition)(source, w["start"], shift_day_key(w["end"], past))
            except Exception as e:  # noqa: BLE001 — the check says it could not read the source
                logger.warning(f"recent-aerobic signal read failed for {source}: {e}")
                out[source] = None
        out[walking_volume.CORRECTION_INPUT] = _read_corrections(w["start"], w["end"])  # #5669: the owner's corrections
        return out

    block = recent_aerobic.build(
        target_date=target_date,
        today=pacific_today(),
        strava_items=_safe("strava"),
        hevy_workouts=_safe("hevy"),
        apple_items=_safe_apple(),
        completeness_inputs=_signals(),  # #5669: the walk-signal check
    )
    return recent_aerobic.aerobic_minutes_7d(block)


def _gather_inputs(target_date: str, add_load_enabled: bool) -> "GeneratorInputs":
    """Pull recovery / acwr / volume / z2 / last-workout state for the generator.

    Day one: returns conservative defaults for recovery / acwr / volume so the
    deterministic engine ships safely without a live tools_strength/get_muscle_volume
    integration. The aerobic minutes are READ (#4410) — a placeholder 0 there wrote
    "walk more" into the note after 9 h of walking + cycling.
    """
    from training.routine_generator import GeneratorInputs

    live = _live_inputs(target_date)  # #5861 L3: {} unless the exercise library is approved — then the real values
    inputs = GeneratorInputs(
        target_date=target_date,
        recovery_tier=live.get("recovery_tier") or "yellow",
        acwr_flag=live.get("acwr_flag") or "safe",
        volume_7d=live.get("volume_7d") or {},
        z2_minutes_7d=_z2_minutes_7d(target_date),
        days_since_last_workout=2,
        add_load_enabled=add_load_enabled,
    )
    if live.get("sleep_hours") is not None:
        setattr(inputs, "sleep_hours", live["sleep_hours"])  # read by fatigue_model.for_live_draft (live only)
    if live.get("steps_by_day"):
        setattr(inputs, "steps_by_day", live["steps_by_day"])  # #5861 L6: the walking dose, into cardio_model.cardio_load (live only)
    for key in ("aerobic_record", "weights_by_day"):  # #5861 FIX6: rulings 11 + 12 (live only)
        if live.get(key):
            setattr(inputs, key, live[key])
    if live.get("medical_stop_lines"):
        setattr(inputs, "medical_stop_lines", live["medical_stop_lines"])  # #5861: tripped -> no hard cardio (live_week.symptom_gate)
    return inputs


# #5861 L3 — the audit's live-wiring bug (gap 4): the cron typed recovery "yellow", ACWR "safe" and an empty 7-day volume
# for every draft, and the ACWR writer's zones (`safe | caution | danger`) never matched the generator's autoreg keys
# (`high | very_high`), so "danger" could not reach the 0.6 multiplier. Behind THE SWITCH only: while the library is
# proposed the three values stay exactly as they were.
ACWR_ZONE_TO_AUTOREG = {"safe": "safe", "caution": "caution", "danger": "high"}  # anything else (detraining, re-baselining) = safe
RECOVERY_BANDS = (67, 34)  # green >= 67, yellow >= 34 — the bands `mcp/tools_plan._recovery_tier` maps the score with


MEDICAL_RHR_NIGHTS = 14  # `health.tripwire_readers._rhr_arm`: the latest night against the mean of the nights before it


def _medical_stop_lines(whoop: list[dict[str, Any]], target_date: str) -> dict[str, Any] | None:
    """`owner_redlines` `medical_stop_lines` through its ONE reader (`health.tripwire_readers.medical_stop_lines`) over the
    whoop rows the cron already read: the RHR arm is measured; the labs arms read unknown (no labs read here); palpitations and
    syncope are self-report with no input on the platform (unknown, never clear). Live only; the draft acts on `tripped`."""
    try:
        from health import tripwire_readers

        rows = sorted((r for r in whoop if r.get("resting_heart_rate") is not None), key=lambda r: str(r.get("sk") or r.get("date") or ""))
        return tripwire_readers.medical_stop_lines(
            {"rhr_by_day": [r["resting_heart_rate"] for r in rows], "lab_draws": None, "window_end": target_date}
        )
    except Exception as e:  # noqa: BLE001 — an unread stop line is unknown, never a blocked draft
        logger.warning(f"medical stop line read failed: {type(e).__name__}")
        return None


def _latest(rows: list[dict[str, Any]] | None, field: str) -> Any:
    hits = sorted((r for r in rows or [] if r.get(field) is not None), key=lambda r: str(r.get("sk") or r.get("date") or ""))
    return hits[-1].get(field) if hits else None


def _live_inputs(target_date: str, read=None) -> dict[str, Any]:
    """The real recovery tier, ACWR flag, 7-day hard sets per muscle and sleep — ONLY when the exercise library is approved
    (`selection_engine.mode`). Each read is fail-soft: an unread value keeps the conservative default."""
    from training import fatigue_model, selection_engine as se

    lib = se.load_library_failsoft()  # the same cached read the draft's selection makes
    if se.mode(lib) != se.MODE_LIVE:
        return {}
    read = read or _read_partition
    out: dict[str, Any] = {}

    def _safe(source: str, days: int) -> list[dict[str, Any]] | None:
        try:
            return read(source, shift_day_key(target_date, -days), target_date)
        except Exception as e:  # noqa: BLE001 — unread keeps the default
            logger.warning(f"live input read failed for {source}: {type(e).__name__}")
            return None

    from health import hr_regime

    whoop = _safe("whoop", MEDICAL_RHR_NIGHTS)  # one read: the latest night + the RHR stop line's 14-night baseline
    score = _latest(whoop, "recovery_score")
    rebaselining = hr_regime.is_rebaselining(target_date)
    if score is not None and not rebaselining:  # HR-derived tiers are not evidence in the window
        out["recovery_tier"] = "green" if float(score) >= RECOVERY_BANDS[0] else ("yellow" if float(score) >= RECOVERY_BANDS[1] else "red")
    if whoop is not None and not rebaselining:  # #5861 second red team: the medical stop line, read (report-only reader)
        out["medical_stop_lines"] = _medical_stop_lines(whoop, target_date)
    sleep = _latest(whoop, "sleep_duration_hours")
    out["sleep_hours"] = float(sleep) if sleep is not None else None
    zone = _latest(_safe("computed_metrics", 2), "acwr_zone")
    out["acwr_flag"] = ACWR_ZONE_TO_AUTOREG.get(str(zone), "safe") if zone is not None else None
    try:  # #5861 L6: the week's steps through the one steps-truth resolver, so the fatigue model counts the walking dose
        from training import steps_resolver

        sr = steps_resolver.steps_range(shift_day_key(target_date, -7), shift_day_key(target_date, -1), fetch=read, derived=False)
        resolved = [d for d in sr.get("days") or [] if d.get("steps") is not None]  # steps-truth: steps_range output
        out["steps_by_day"] = {d["date"]: d["steps"] for d in resolved}  # steps-truth: steps_resolver.steps_range output
    except Exception as e:  # noqa: BLE001 — unread steps keep the walking dose out of the cardio load, said so in the model
        logger.warning(f"live input read failed for steps: {type(e).__name__}")
    hevy = _safe("hevy", 7)
    if hevy is not None:
        sets = fatigue_model.hard_sets_by_muscle(hevy, fatigue_model.library_index(lib), as_of=target_date)
        out["volume_7d"] = {m: int(round(n)) for m, n in sets.items() if m != "unplaced"}
    out |= _live_activity_inputs(target_date, _safe, hevy)
    return out


RATE_WEIGH_IN_DAYS = 35  # #5861 FIX6: five weeks of weigh-ins — the advisory ceiling's sustained-trend guard reads 4 weekly rates


def _live_activity_inputs(target_date: str, safe: Any, hevy: list[dict[str, Any]] | None) -> dict[str, Any]:
    """#5861 FIX6 (owner rulings 11 and 12), live only — `_live_inputs` returns before this while the library is proposed:
    the week's RECORDED aerobic sessions (Apple workouts + Strava + the Hevy record, one workout identity counted once:
    `cardio_model.recorded_aerobic`) and the weigh-ins the advisory loss-rate ceiling reads. Each read fail-soft; an unread
    input adds no key."""
    from training import cardio_model

    out: dict[str, Any] = {}
    apple, strava = safe("apple_health", 7), safe("strava", 7)
    if apple is not None or strava is not None:
        try:
            out["aerobic_record"] = cardio_model.recorded_aerobic(apple=apple or [], strava=strava or [], hevy=hevy or [])
        except Exception as e:  # noqa: BLE001 — an unresolved record is unknown, never a blocked draft
            logger.warning(f"recorded aerobic failed: {type(e).__name__}")
    withings = safe("withings", RATE_WEIGH_IN_DAYS)
    weights = {str(r.get("date") or str(r.get("sk") or "")[5:15]): float(r["weight_lbs"]) for r in withings or [] if r.get("weight_lbs")}
    if weights:
        out["weights_by_day"] = weights
    return out


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

        from training import hevy_write_client as wc, routine_repo as repo, session_block
        from training.hevy_compiler import to_create_body
        from training.hevy_template_cache import resolve_movement
        from training.routine_generator import emit_branch_model, generate_routines
        from training.routine_title import build_title_context, format_why_note

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
            # #3115: a re-run for the same target_date now lands on the same
            # routine_id, so persist as the next VERSION of it (carrying the Hevy
            # link forward) rather than raising RoutineConflict or forking a routine.
            repo.draft_versioned(ir)
            # Push only the primary (branch-carrying) routine. Siblings are
            # persisted above for the record but folded into the primary's
            # branch menu — they are not pushed as separate routines anymore.
            if primary is None or ir.routine_id != primary.routine_id or pushed_one or not ir.exercises:
                summary.append({"routine_id": ir.routine_id, "variant": ir.variant, "pushed": False})
                continue
            try:
                title_ctx = build_title_context(ir)
                why = session_block.why_note_for(ir, format_why_note(ir))  # #5428: no second session line over the block
                from training.live_balance import template_resolver  # #5861 FIX3: the KB template setting (approved only)

                body = to_create_body(ir, template_resolver(resolve_movement), title_context=title_ctx, why_note=why)
                resp = wc.create_routine(body)
                from training.hevy_compiler import from_hevy_response

                parsed = from_hevy_response(resp)
                ir.hevy_routine_id = parsed["hevy_routine_id"]
                ir.hevy_updated_at = parsed["updated_at"]
                ir.hevy_pushed_at = datetime.now(timezone.utc).isoformat()
                ir.status = "active"
                ir.version += 1
                ir.parent_version = ir.version - 1
                repo.put_versioned(ir)
                if ir.hevy_routine_id:
                    # #3115: routine_id is deterministic now, so a cron re-run for the
                    # same day reaches this with the mapping ALREADY present. The
                    # conditional id-map put then raises — which the MCP commit path has
                    # always swallowed here and this one did not, so an idempotent re-run
                    # would have gone to the DLQ for having nothing to do.
                    try:
                        repo.upsert_id_map(ir.routine_id, ir.hevy_routine_id)
                    except repo.RoutineConflict:
                        logger.info(f"id-map already present for routine {ir.routine_id}")
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
