"""mcp/phase_evaluator_leg.py — the weekly phase evaluator's reads, its store and its weekly run (#5575). OWNER-ONLY.

`training.phase_evaluator` is the pure core (the charter's gates -> met / not_met / unknown) and `training.stage_machine`
the proposal/transition step; this module does the sanctioned reads, hands them in and writes the rows.

WHERE IT RUNS (owner ruling 2026-11-08: inside an EXISTING weekly job — no new Lambda, schedule or IAM). It is a second,
fail-soft leg on the weekly panel grade (`mcp.panel_weekly_grade.lambda_entry`, rule `PanelWeeklyGrade`, Monday 08:30
Pacific on `life-platform-mcp-warmer`), so the week it evaluates is the Monday-Sunday week that run grades. The function's
role (`role_policies_serve.mcp_server`) already holds table-wide `dynamodb:GetItem/Query/PutItem` and `s3:GetObject` on
`config/*` (the charter and its owner-only twin). The leg never changes the grade's status or its dead-man datapoint.

THE READS (every one names its failure; an unread input makes its gates unknown, never met and never not met)

  charter      `training_charter.load_charter()` — the public charter merged with the owner-only twin (the goal weight);
  weight       the Withings partition (`core.query_source`) -> `shared_quantities._weighins` ->
               `health.milestone_ledger.trailing_weight_mean` at each weekly checkpoint Sunday (the platform's trailing
               7-day mean: 7 calendar days, >= 3 weigh-ins). `get_weight_loss_progress` reads the same partition rows
               (`recent_weights`), so each checkpoint's window, n and mean are checkable against it;
  Hevy         ONE read (`tools_strength._read_hevy_all_phases`, the sanctioned Hevy read) serves the sessions per week
               (`routine_title.count_distinct_performed` per completed Monday-Sunday week), the pain notes and the run
               gate's Stage 4 history;
  pain         `tools_may_tracker.pain_instances` (the Hevy note layer's pain net) over the window, resolved against the
               owner's dismissals (`tools_plan._pain_dismissals`, read only when a flag exists) by
               `training_context_registry.expand_instances` / `resolve_flags` — the plan engine's rule;
  run gate     `tools_may_tracker.running_inputs` (walking weeks from `shared_quantities.walking_layer`, the strain hold,
               Stage 4) + the latest weigh-in on or before Sunday -> `run_onramp.gate_state`, as the May tracker reads it;
  block starts `plan_hevy_windows._block_workouts` -> `session_sequence.block_boundaries` (when a proposal takes effect).

THE ROWS — `USER#matthew#SOURCE#training_constraints` (Tier 2 owner-only, CROSS_PHASE; docs/SCHEMA.md):
  `PHASE#EVAL#<monday>`                 one per evaluated week (idempotent: a re-run overwrites it), written LAST;
  `PHASE#STATE`                         the current phase, since, origin and the pending proposal (if any);
  `PHASE#TRANSITION#<effective_on>#<to>` one per phase change (the evaluator's at a block start, or the owner's override).
The owner's door to these rows (status, veto, override) is `mcp/tools_training_phase.py`. A missing EVAL row for the
newest completed week is reported by the qa-smoke dead-man
(`lambdas/operational/phase_eval_qa.py`). Logs carry ids, verdicts and classes — never a weight.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from training import phase_evaluator as pe, stage_machine as sm

logger = logging.getLogger("phase_evaluator")


def _err(e: BaseException) -> str:
    return f"{type(e).__name__}: {e}"[:200]


def _shift(day: str, days: int) -> str:
    from training.may_tracker import shift

    return shift(day, days)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── the reads ───────────────────────────────────────────────────────────────────────────────────────────────────────
def weight_checkpoints(rows: Optional[list], checkpoints: list[str]) -> list[dict[str, Any]]:
    """The trailing 7-day mean at each checkpoint (newest first); a checkpoint with < 3 weigh-ins carries mean None."""
    from health.milestone_ledger import WEIGHT_WINDOW_DAYS, trailing_weight_mean

    from mcp.shared_quantities import _weighins

    series = _weighins(rows) if rows is not None else []
    out = []
    for cp in checkpoints:
        if rows is None:
            out.append({"as_of": cp, "mean_lbs": None, "n": None, "state": "read_failed"})
            continue
        window = trailing_weight_mean(series, cp)
        if window is None:
            start = _shift(cp, -(WEIGHT_WINDOW_DAYS - 1))
            n = sum(1 for d, _w in series if start <= d <= cp)
            out.append({"as_of": cp, "mean_lbs": None, "n": n, "window_start": start, "window_end": cp, "state": "too_few_weighins"})
        else:
            out.append({"as_of": cp, **window, "state": "measured"})
    return out


def _day(r: Any) -> str:
    return str(r.get("date") or str(r.get("sk") or "")[5:15])[:10]


def sessions_by_week(hevy: Optional[list], week_start: str, weeks: int) -> list[dict[str, Any]]:
    """Performed Hevy sessions per completed week, newest first (`routine_title.count_distinct_performed`)."""
    from training.routine_title import count_distinct_performed

    out = []
    for k in range(max(1, int(weeks))):
        mon = _shift(week_start, -7 * k)
        sun = _shift(mon, 6)
        n = None if hevy is None else count_distinct_performed([r for r in hevy if mon <= _day(r) <= sun])
        out.append({"week_start": mon, "week_end": sun, "sessions": n})
    return out


def live_pain_flags(instances: Optional[list], dismissals: Optional[list]) -> list[dict[str, Any]]:
    """The flags no dismissal covers — `plan_engine`'s `pain_flag_named_site` resolution over the same registry rule."""
    from training import training_context_registry as tcr

    expanded = tcr.expand_instances(instances, dismissals)
    resolutions = tcr.resolve_flags(expanded, dismissals)
    dismissed = {(str(r["movement"]), r.get("instance_site")) for r in resolutions if r.get("dismissed")}
    live = [i for i in expanded if (str(i.get("movement")), i.get("site")) not in dismissed]
    return [{"movement": i.get("movement"), "site": i.get("site"), "note_dates": sorted(i.get("note_dates") or [])} for i in live]


def pain_read(
    hevy: Optional[list], window_start: str, window_end: str, dismissals: Optional[list], dismissals_read: bool
) -> dict[str, Any]:
    """The live pain flags in the window. Hevy unread, or a flag present with the dismissals unread, is unknown (`live`
    None) — never pain-free and never a flag the owner may already have dismissed."""
    from mcp.tools_may_tracker import pain_instances

    base = {"window_start": window_start, "window_end": window_end}
    if hevy is None:
        return {**base, "live": None, "error": "hevy unread"}
    instances = pain_instances([r for r in hevy if window_start <= _day(r) <= window_end])
    if not instances:
        return {**base, "live": []}
    if not dismissals_read:
        return {**base, "live": None, "error": "dismissals unread"}
    return {**base, "live": live_pain_flags(instances, dismissals)}


def run_gate_read(
    week_end: str, wrows: Optional[list], strava: Optional[list], hevy: Optional[list], dismissals
) -> Optional[dict[str, Any]]:
    """The run gate for the week ending `week_end`, read exactly as the May tracker reads it (#5090)."""
    from training import run_onramp

    from mcp.shared_quantities import _weighins
    from mcp.tools_may_tracker import running_inputs

    ri = running_inputs(week_end, strava, hevy, dismissals)
    pts = [p for p in _weighins(wrows) if p[0] <= week_end] if wrows is not None else []
    w, wd = (pts[-1][1], pts[-1][0]) if pts else (None, None)
    gs = run_onramp.gate_state(w, ri["walking_weeks"], ri["holds"], ri["stage4_done"], weight_date=wd)
    walking = gs.get("walking") or {}
    unknown_week = any(x.get("hours") is None or x.get("pain_flag") is None for x in ri["walking_weeks"])
    return {
        "gate_state": gs.get("state"),
        "reason": gs.get("reason"),
        "weight_lb": gs.get("weight_lb"),
        "weight_date": gs.get("weight_date"),
        "gate_lb": gs.get("gate_lb"),
        "lb_to_gate": gs.get("lb_to_gate"),
        "holds_read": gs.get("holds_read"),
        "walking_met": walking.get("met"),
        "walking_needed": walking.get("needed"),
        "walking_unknown": unknown_week,
    }


def gather(charter: dict[str, Any], week_start: str, week_end: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """(inputs for `phase_evaluator.evaluate_next`, the read ledger {read: ok | error}). Never raises on a source."""
    from training.run_onramp import history_from, running

    from mcp import core
    from mcp.tools_may_tracker import pain_instances
    from mcp.tools_plan import _pain_dismissals
    from mcp.tools_strength import _read_hevy_all_phases

    reads: dict[str, Any] = {}
    adv_n = int((pe.phases(charter).get("advance") or {}).get("consecutive_evaluations") or 1)
    weeks = pe.max_lookback_weeks(charter)
    checkpoints = pe.weekly_checkpoints(week_end, adv_n, _shift)
    walk_weeks = int(running().get("walking_weeks") or 0)
    oldest = _shift(week_start, -7 * max(weeks, walk_weeks, adv_n))

    def _read(name: str, fn, *a):
        try:
            out = fn(*a)
            reads[name] = "ok"
            return out
        except Exception as e:  # noqa: BLE001 — named on the row; the gates it feeds read unknown
            logger.warning("[phase_evaluator] %s read failed (%s)", name, type(e).__name__)
            reads[name] = f"read_failed: {_err(e)}"
            return None

    wrows = _read("withings", core.query_source, "withings", _shift(oldest, -7), week_end)
    hevy_out = _read("hevy", _read_hevy_all_phases, min(oldest, history_from() or oldest), week_end)
    hevy = None if hevy_out is None else list(hevy_out[0] or [])
    strava = _read("strava", core.query_source_range, "strava", oldest, week_end)
    lookback = int(pe.every_transition_param(charter, "joint_or_lower_leg_pain_flags", "pain_lookback_weeks", 2))
    # the owner's dismissals are read only when a pain note exists (the May tracker's rule); unread = a flag holds
    dismissals = _read("pain_dismissals", _pain_dismissals) if hevy is not None and pain_instances(hevy) else None
    pain = pain_read(hevy, _shift(week_end, -(7 * lookback - 1)), week_end, dismissals, reads.get("pain_dismissals") == "ok")
    reads["pain_flags"] = "ok" if pain.get("live") is not None else f"unknown: {pain.get('error')}"
    run_gate = None
    try:
        run_gate = run_gate_read(week_end, wrows, None if strava is None else list(strava), hevy, dismissals)
        reads["run_gate"] = "ok"
    except Exception as e:  # noqa: BLE001 — the Forge gate reads unknown
        logger.warning("[phase_evaluator] run gate read failed (%s)", type(e).__name__)
        reads["run_gate"] = f"read_failed: {_err(e)}"
    of_last = int(pe.every_transition_param(charter, "performed_hevy_sessions_per_wk", "of_last_weeks", 4))
    inputs = {
        "as_of": week_end,
        "weight_trend_7d_lb": weight_checkpoints(wrows, checkpoints),
        "sessions_by_week": sessions_by_week(hevy, week_start, of_last),
        "pain_flags": pain,
        "run_gate": run_gate,
    }
    return inputs, reads


def block_boundaries(today: str) -> Optional[list[str]]:
    """The block starts on record before `today`; None when the Hevy record could not be read."""
    from training import session_sequence

    from mcp.plan_hevy_windows import _block_workouts

    try:
        return session_sequence.block_boundaries(_block_workouts(today), today)
    except Exception as e:  # noqa: BLE001 — a pending proposal then waits (unknown block), never applies
        logger.warning("[phase_evaluator] block boundaries unread (%s)", type(e).__name__)
        return None


# ── the store ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _put(table: Any, item: dict[str, Any]) -> None:
    from experiment.phase_taxonomy import experiment_stamp_for

    item = {**item, **experiment_stamp_for(item["pk"], item["sk"])}
    table.put_item(Item=json.loads(json.dumps(item, default=str), parse_float=Decimal))


def _plain(item: Any) -> Any:
    return json.loads(json.dumps(item, default=float)) if item is not None else None


def read_state(table: Any, user_id: str = "matthew") -> Optional[dict[str, Any]]:
    """The stored STATE row, or None when none exists. Raises on a failed read (never "no state")."""
    resp = table.get_item(Key={"pk": pe.pk(user_id), "sk": pe.SK_STATE})
    return _plain(resp.get("Item"))


def seeded_state(charter: dict[str, Any]) -> dict[str, Any]:
    """The first STATE from the Hevy title's hand-set phase (`routine_title.load_phase_state`)."""
    from training.routine_title import load_phase_state

    try:
        title_state = load_phase_state()
    except Exception as e:  # noqa: BLE001 — the first phase in the order, said so
        logger.warning("[phase_evaluator] training_phases.json unread (%s) — seeding the first phase", type(e).__name__)
        title_state = {}
    return pe.seed_state(charter, title_state.get("current"), title_state.get("current_started"))


def _state_of(row: dict[str, Any]) -> dict[str, Any]:
    return {k: row.get(k) for k in ("stage", "since", "pending", "origin", "last_eval")}


def latest_eval(table: Any, user_id: str = "matthew") -> Optional[dict[str, Any]]:
    from boto3.dynamodb.conditions import Key

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pe.pk(user_id)) & Key("sk").begins_with(pe.SK_EVAL), ScanIndexForward=False, Limit=1
    )
    items = resp.get("Items") or []
    return _plain(items[0]) if items else None


def transitions(table: Any, user_id: str = "matthew") -> list[dict[str, Any]]:
    from boto3.dynamodb.conditions import Key

    resp = table.query(KeyConditionExpression=Key("pk").eq(pe.pk(user_id)) & Key("sk").begins_with(pe.SK_TRANSITION))
    return [_plain(i) for i in resp.get("Items") or []]


# ── the weekly run ──────────────────────────────────────────────────────────────────────────────────────────────────
def evaluate_week(week_end: Optional[str] = None, *, today: Optional[str] = None, table: Any = None) -> dict[str, Any]:
    """Evaluate the Monday-Sunday week ending `week_end` (default: the newest completed week) and store the rows."""
    from common.pacific_time import pacific_today
    from training.may_tracker import last_completed_monday
    from training.training_charter import load_charter

    if table is None:
        from mcp.config import table as _table

        table = _table
    today = today or pacific_today()
    week_start = _shift(week_end, -6) if week_end else last_completed_monday(today)
    week_end = week_end or _shift(week_start, 6)
    charter = load_charter()
    stored = read_state(table)
    state = _state_of(stored) if stored else seeded_state(charter)
    inputs, reads = gather(charter, week_start, week_end)
    evaluation = pe.evaluate_next(charter, str(state["stage"]), inputs)
    boundaries = block_boundaries(today)
    reads["block_boundaries"] = "ok" if boundaries is not None else "read_failed"
    eval_sk = pe.SK_EVAL + week_start
    step = sm.step(pe.order(charter), state, as_of=week_end, next_verdict=evaluation["verdict"], boundaries=boundaries, eval_key=eval_sk)
    now = _now_iso()
    if step["transition"]:
        _put(table, pe.transition_row(charter, step["transition"], recorded_at=now))
    new_state = {**step["state"], "last_eval": eval_sk}
    _put(table, pe.state_row(charter, new_state, updated_at=now))
    row = pe.eval_row(
        charter,
        week_start=week_start,
        week_end=week_end,
        state_before=state,
        evaluation=evaluation,
        step=step,
        reads=reads,
        evaluated_at=now,
    )
    _put(table, row)  # LAST: its presence is what the dead-man reads, so it implies the rest landed
    return {
        "outcome": "written",
        "sk": eval_sk,
        "phase": new_state["stage"],
        "next": evaluation["next"],
        "next_verdict": evaluation["verdict"],
        "gates": pe.gate_summary(evaluation["gates"]),
        "blocking_gate": (evaluation.get("blocking_gate") or {}).get("id"),
        "action": step["action"],
        "seeded": stored is None,
    }


def weekly_leg(week_end: Optional[str] = None) -> dict[str, Any]:
    """The fail-soft leg on the weekly panel grade. Never raises; logs ids, verdicts and classes only."""
    try:
        out = evaluate_week(week_end)
    except Exception as e:  # noqa: BLE001 — named on the run's result; the qa-smoke dead-man sees the missing row
        logger.warning("[phase_evaluator] weekly evaluation failed (%s)", type(e).__name__)
        return {"outcome": "failed", "error": type(e).__name__}
    logger.info("[phase_evaluator] wrote %s phase=%s action=%s gates=%s", out["sk"], out["phase"], out["action"], out["gates"])
    return out
