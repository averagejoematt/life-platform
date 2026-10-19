"""predraft_shadow.py — the nightly pre-draft's plan-source switch and its v0.4 shadow (#5080).

WHY THIS EXISTS
  Wave 1 of the May-2027 charter (#5067) made the generator the charter engine, so the nightly pre-draft
  (`mcp/nightly_predraft.py`) already drafts the charter plan. Nothing showed the owner, side by side, what
  that plan changed against the program he had been training (v0.4), and nothing let him go back to it with
  one command if a wave misbehaved. This module is both halves:

  THE SWITCH — SSM `/life-platform/training-plan-source` = `v04 | charter`, read once per 60 s (`plan_source`).
    Which plan the pre-draft PERSISTS (drafts into the routine repo, marks, red-teams). Only one ever does.
    FAIL-SAFE: a missing parameter, a missing `ssm:GetParameter` grant, any read error or an unrecognised value
    all resolve to `DEFAULT_SOURCE` and say why — so merging this before the IAM grant is applied changes
    nothing. OWNER DECISION (#5080 PR): `DEFAULT_SOURCE = CHARTER` (the parameter's absence = what is live
    today); the alternative — absence means `v04` until he has read the diff — is the one-line change of that
    constant, and would roll tonight's pre-draft back to the pre-charter plan.
      revert:  aws ssm put-parameter --name /life-platform/training-plan-source --value v04 --type String --overwrite
      forward: aws ssm put-parameter --name /life-platform/training-plan-source --value charter --type String --overwrite
    The parameter is NOT CDK-owned on purpose: a CDK-owned value is re-asserted on every stack deploy, which would
    silently undo a revert. The stack owns only the read grant (`role_policies_serve.mcp_server` HevySsmParams).

  THE SHADOW — for the first `SHADOW_NIGHTS` nights the pre-draft also builds the plan it does NOT persist (the
  frozen v0.4 builder `training.program_v04.build_session`, or the charter generator's routine un-persisted) and
  writes ONE owner-only diff row: `USER#matthew#SOURCE#training_constraints / SHADOW#<date>` (Tier 2 owner-only,
  CROSS_PHASE — docs/SCHEMA.md). Side by side: role, exercises, sets, loads, cardio block, lifting minutes, the
  step target, the deload state, and a one-line summary. Fail-soft end to end: a shadow error is named on the
  run's result and never changes the pre-draft's outcome or its dead-man.

WHAT IT NEVER DOES
  Commit to Hevy, persist both plans, or read a live AI. The v0.4 side is HISTORY (`program_v04`), never the charter.
"""

from __future__ import annotations

import json
import logging
import time
from decimal import Decimal
from typing import Any, Callable

logger = logging.getLogger("predraft_shadow")

ISSUE = "#5080"
PARAM_NAME = "/life-platform/training-plan-source"
CHARTER = "charter"
V04 = "v04"
SOURCES = (V04, CHARTER)
DEFAULT_SOURCE = CHARTER
"""OWNER DECISION (#5080): the parameter's ABSENCE means the charter engine — what is live today. Set to V04 for the
alternative (absence = v0.4 until he flips it); nothing else changes."""
CACHE_SECONDS = 60
REVERT_COMMAND = f"aws ssm put-parameter --name {PARAM_NAME} --value {V04} --type String --overwrite"
FORWARD_COMMAND = f"aws ssm put-parameter --name {PARAM_NAME} --value {CHARTER} --type String --overwrite"

SHADOW_NIGHTS = 5
"""The shadow runs until this many SHADOW# rows exist (the issue's 3–5 nights), then stops by itself."""
SHADOW_SK_PREFIX = "SHADOW#"
E1RM_LOOKBACK_DAYS = 90
"""The v0.4 side's loads read e1RM off his last 90 days of logged sets (best Epley set) — not bodyweight-band matched."""

_cache: dict[str, Any] = {"at": None, "value": None}


def _reset_cache() -> None:
    _cache.update(at=None, value=None)


def _ssm_get(_name: str = PARAM_NAME) -> str:
    """The one SSM read — the parameter id is the module constant at the call, so the grant lockstep (#2824) sees it."""
    import boto3
    from botocore.config import Config

    client = boto3.client("ssm", config=Config(connect_timeout=3, read_timeout=3, retries={"max_attempts": 2}))
    return str(client.get_parameter(Name=PARAM_NAME)["Parameter"]["Value"])


def _error_kind(e: Exception) -> str:
    code = str(((getattr(e, "response", None) or {}).get("Error") or {}).get("Code") or type(e).__name__)
    if code == "ParameterNotFound":
        return "parameter_absent"
    if code in ("AccessDeniedException", "AccessDenied", "UnauthorizedOperation"):
        return "no_permission"
    return f"read_failed:{code}"


def plan_source(getter: Callable[[str], str] | None = None, now: float | None = None) -> dict[str, Any]:
    """Which plan the pre-draft persists tonight: {source, read, reason, cached}. One read per 60 s; never raises."""
    t = time.monotonic() if now is None else now
    if _cache["at"] is not None and 0 <= t - _cache["at"] < CACHE_SECONDS:
        return dict(_cache["value"], cached=True)
    try:
        raw = (getter or _ssm_get)(PARAM_NAME).strip().lower()
        if raw in SOURCES:
            out = {"source": raw, "read": "ssm", "reason": f"{PARAM_NAME} = {raw}"}
        else:
            out = {"source": DEFAULT_SOURCE, "read": "default", "reason": f"unrecognised value {raw!r} — the default stands"}
    except Exception as e:  # noqa: BLE001 — FAIL-SAFE: absent / no grant / any error is the default, named
        out = {"source": DEFAULT_SOURCE, "read": "default", "reason": _error_kind(e)}
    _cache.update(at=t, value=out)
    return dict(out, cached=False)


# ── the shadow window ─────────────────────────────────────────────────────────────────────
def _shadow_sks(query: Callable[[], list[str]] | None = None) -> list[str]:
    if query is not None:
        return query()
    from boto3.dynamodb.conditions import Key

    from mcp.config import table

    kwargs: dict[str, Any] = {
        "KeyConditionExpression": Key("pk").eq("USER#matthew#SOURCE#training_constraints") & Key("sk").begins_with(SHADOW_SK_PREFIX),
        "ProjectionExpression": "sk",
    }
    sks: list[str] = []
    while True:
        resp = table.query(**kwargs)
        sks += [str(i["sk"]) for i in resp.get("Items", [])]
        if "LastEvaluatedKey" not in resp:
            return sks
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def shadow_due(target_date: str, query: Callable[[], list[str]] | None = None) -> dict[str, Any]:
    """{due, nights_recorded, reason}. Due while fewer than SHADOW_NIGHTS rows exist, or tonight's date is one of them
    (a re-run rewrites its own row). An unreadable count is NOT due — a shadow it cannot bound never runs."""
    try:
        sks = _shadow_sks(query)
    except Exception as e:  # noqa: BLE001 — named; the pre-draft runs without a shadow
        return {"due": False, "nights_recorded": None, "reason": f"shadow count unreadable ({type(e).__name__})"}
    mine = f"{SHADOW_SK_PREFIX}{target_date}" in sks
    due = mine or len(sks) < SHADOW_NIGHTS
    return {"due": due, "nights_recorded": len(sks), "reason": "rerun of tonight's row" if mine else f"{len(sks)}/{SHADOW_NIGHTS} nights"}


# ── the v0.4 side: inputs for the frozen builder ─────────────────────────────────────────
def credited_sessions(target_date: str, block_workouts: list[dict[str, Any]] | None) -> int:
    """Loaded sessions since the block start, before `target_date` — what v0.4's order and week counted."""
    from training import training_streaks

    return sum(
        1
        for w in block_workouts or []
        if not w.get("tombstone")
        and str(w.get("date") or str(w.get("sk") or "").replace("DATE#", ""))[:10] < target_date
        and training_streaks.is_loaded_session(w)
    )


def e1rm_by_movement(target_date: str, history_index: dict[str, list], catalog: dict[str, Any], keys: list[str]) -> dict[str, float]:
    """{movement_key: best Epley e1RM (kg)} over the history window, sessions before `target_date` only."""
    out: dict[str, float] = {}
    for key in keys:
        tid = ((catalog or {}).get(key) or {}).get("hevy_template_id_hint")
        best = 0.0
        for s in (history_index or {}).get(str(tid or ""), []) if tid else []:
            if str(s.get("date") or "") >= target_date:
                continue
            for st in s.get("sets") or []:
                w, r = float(st.get("weight_kg") or 0), int(st.get("reps") or 0)
                if w > 0 and r > 0:
                    best = max(best, w * (1 + r / 30.0))
        if best > 0:
            out[key] = round(best, 2)
    return out


def _catalog() -> dict[str, Any]:
    from training.routine_generator import _load_json

    return (_load_json("movement_catalog.json") or {}).get("movements") or {}


def _history_index() -> dict[str, list]:
    from training.exercise_history import load_history_indexes

    return load_history_indexes(lookback_days=E1RM_LOOKBACK_DAYS)[0]


def v04_plan(target_date: str, block_workouts: list[dict[str, Any]] | None, history_index=None, catalog=None) -> dict[str, Any]:
    """The frozen v0.4 session for the date, its loads from his logged e1RM (a failed history read leaves loads None, named)."""
    from training import program_v04

    credited = credited_sessions(target_date, block_workouts)
    role = program_v04.v04_role(credited)
    keys = [a[2] for a in program_v04.V04_TEMPLATES[role]["anchors"]] + list(program_v04.V04_TEMPLATES[role]["accessories"])
    note = None
    try:
        e1rm = e1rm_by_movement(target_date, history_index if history_index is not None else _history_index(), catalog or _catalog(), keys)
    except Exception as e:  # noqa: BLE001 — the plan still builds; its loads say why they are empty
        e1rm, note = {}, f"history unreadable ({type(e).__name__}) — loads unprescribed"
    plan = program_v04.build_session(target_date, {"credited_sessions": credited, "e1rm_kg": e1rm})
    plan["credited_basis"] = "the Hevy record since the block start" if block_workouts is not None else "record unread — counted 0"
    plan["e1rm_basis"] = note or f"best Epley set per movement, last {E1RM_LOOKBACK_DAYS} days (not bodyweight-band matched)"
    return plan


# ── the persist path when the switch says v04 ────────────────────────────────────────────
def _v04_note(ex: dict[str, Any]) -> str:
    return f"v0.4 revert: {ex['load_basis']}; {ex['intensity']} {ex['sets'][0]['reps'][0]}-{ex['sets'][0]['reps'][1]} reps."


def draft_v04(target_date: str, plan: dict[str, Any]) -> dict[str, Any]:
    """Persist the frozen v0.4 plan as tonight's draft — `manage_hevy_routine draft_custom`'s action function, behind the
    SAME freshness refusal the charter draft honours (#5085). Returns the pre-draft's draft shape."""
    from mcp.tools_hevy_routine import _action_draft_custom, _authoring_freshness_gate

    gate = _authoring_freshness_gate(target_date)
    if not gate.get("ok"):
        return {"status": "blocked_stale_inputs", "gaps": gate.get("gaps", []), "note": "v0.4 draft refused: an input lags (#5085)"}
    exercises = [
        {
            "movement_key": ex["movement_key"],
            "sets": [
                (
                    {"weight_lbs": s["load_lb"], "rep_range_start": s["reps"][0], "rep_range_end": s["reps"][1]}
                    if s["load_lb"]
                    else {"rep_range_start": s["reps"][0], "rep_range_end": s["reps"][1]}
                )
                for s in ex["sets"]
            ],
            "rest_seconds": ex["rest_seconds"],
            "notes": _v04_note(ex),
        }
        for ex in plan["exercises"]
    ]
    res = _action_draft_custom({"target_date": target_date, "archetype": plan["archetype"], "exercises": exercises})
    if res.get("status") != "drafted_custom" or not res.get("routine_id"):
        return {"status": "failed", "error": str(res.get("error") or res)[:300]}
    return {"status": "drafted", "ideal_routine_id": res["routine_id"], "plan_source": V04}


def charter_preview(target_date: str) -> Any:
    """The charter generator's ideal routine for the date, NOT persisted — the shadow side when the switch says v04."""
    from training.routine_generator import generate_routines

    from mcp.tools_hevy_routine import _generator_inputs

    routines = generate_routines(_generator_inputs({"target_date": target_date}))
    return next((r for r in routines if r.variant == "ideal"), None) or next(iter(routines), None)


# ── the diff report ──────────────────────────────────────────────────────────────────────
_KG_TO_LB = 2.20462


def _minutes(blocks: list[Any], catalog: dict[str, Any]) -> dict[str, Any]:
    from training.session_shape import routine_minutes

    return routine_minutes(blocks, catalog)


def charter_side(ir: Any, session: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    """The charter plan, summarised off its routine IR (what was, or would be, persisted)."""
    from training.training_charter import charter_value, charter_version

    exercises = []
    for b in getattr(ir, "exercises", None) or []:
        work = [s for s in b.sets or [] if str(getattr(s, "type", "normal")).lower() not in ("warmup", "warm_up", "warm-up")]
        loads = [float(s.weight_kg) * _KG_TO_LB for s in work if getattr(s, "weight_kg", None)]
        exercises.append({"movement_key": b.movement_key, "sets": len(work), "top_load_lb": round(max(loads)) if loads else None})
    mins = _minutes(list(getattr(ir, "exercises", None) or []), catalog)
    rec = session.get("deload_recommendation") or {}
    return {
        "charter_version": charter_version(),
        "session_role": session.get("session_role"),
        "archetype": getattr(ir, "archetype", None),
        "exercises": exercises,
        "total_sets": sum(e["sets"] for e in exercises),
        "lifting_minutes": mins["lifting_minutes"],
        "cardio_blocks": mins["cardio_blocks"],
        "steps_target": {"floor": charter_value("steps.floor"), "target": charter_value("steps.target")},
        "deload": {"on": bool(session.get("deload")), "recommended": rec.get("recommended") if isinstance(rec, dict) else None},
    }


def v04_side(plan: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    from training.routine_ir import ExerciseBlock, Set

    blocks = [
        ExerciseBlock(movement_key=e["movement_key"], sets=[Set() for _ in e["sets"]], rest_seconds=e["rest_seconds"])
        for e in plan["exercises"]
    ]
    mins = _minutes(blocks, catalog)
    return {
        "program_version": plan["program_version"],
        "session_role": plan["session_role"],
        "archetype": plan["archetype"],
        "week": plan["week"],
        "exercises": [
            {"movement_key": e["movement_key"], "sets": len(e["sets"]), "top_load_lb": max((s["load_lb"] or 0) for s in e["sets"]) or None}
            for e in plan["exercises"]
        ],
        "total_sets": plan["total_sets"],
        "lifting_minutes": mins["lifting_minutes"],
        "cardio_blocks": [],
        "steps_target": None,
        "deload": {"on": plan["deload"]["on"], "rule": plan["deload"]["rule"]},
        "e1rm_basis": plan.get("e1rm_basis"),
    }


def diff_report(target_date: str, persisted: str, charter: dict[str, Any], v04: dict[str, Any], run_at: str) -> dict[str, Any]:
    """The owner-only side-by-side for one night, with its one-line summary."""
    ck = {e["movement_key"] for e in charter["exercises"]}
    vk = {e["movement_key"] for e in v04["exercises"]}
    cardio = ", ".join(f"{c['movement_key']} {c['minutes']} min" for c in charter["cardio_blocks"]) or "none"
    steps = charter["steps_target"] or {}
    summary = (
        f"{target_date}: persisted {persisted}. Role {charter['session_role']} vs v0.4 {v04['session_role']}; "
        f"{charter['total_sets']} vs {v04['total_sets']} working sets; ~{charter['lifting_minutes']:g} vs ~{v04['lifting_minutes']:g} lifting min; "
        f"cardio {cardio} vs none; steps {steps.get('floor')}-{steps.get('target')} vs none; "
        f"deload {'on' if charter['deload']['on'] else 'off'} vs {'on' if v04['deload']['on'] else 'off'}; "
        f"{len(ck - vk)} movement(s) only in the charter plan, {len(vk - ck)} only in v0.4."
    )
    return {
        "sk": f"{SHADOW_SK_PREFIX}{target_date}",
        "target_date": target_date,
        "issue": ISSUE,
        "persisted": persisted,
        "shadow": V04 if persisted == CHARTER else CHARTER,
        "charter": charter,
        "v04": v04,
        "diff": {
            "role": [charter["session_role"], v04["session_role"]],
            "only_charter": sorted(ck - vk),
            "only_v04": sorted(vk - ck),
            "total_sets": [charter["total_sets"], v04["total_sets"]],
            "lifting_minutes": [charter["lifting_minutes"], v04["lifting_minutes"]],
            "cardio_blocks": [len(charter["cardio_blocks"]), 0],
            "steps_target": [steps.get("target"), None],
            "deload": [charter["deload"]["on"], v04["deload"]["on"]],
        },
        "summary": summary,
        "revert_command": REVERT_COMMAND,
        "recorded_at": run_at,
        "tier": "owner-only (Tier 2)",
    }


def write_report(report: dict[str, Any], put: Callable[[dict[str, Any]], Any] | None = None) -> None:
    """One SHADOW#<date> row (Decimal-safe). The pk is literal so the partition's writers stay greppable."""
    item = json.loads(json.dumps({"pk": "USER#matthew#SOURCE#training_constraints", **report}, default=str), parse_float=Decimal)
    if put is None:
        from mcp.config import table

        put = lambda i: table.put_item(Item=i)  # noqa: E731 — one call site
    put(item)


def shadow_leg(
    target_date: str,
    persisted: str,
    session: dict[str, Any],
    persisted_ir: Any,
    block_workouts: list[dict[str, Any]] | None,
    run_at: str,
    *,
    put: Callable[[dict[str, Any]], Any] | None = None,
    v04_built: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the side the pre-draft did NOT persist, diff it against the one it did, write the owner-only row.
    Never raises: a failure is the leg's `error`, never the pre-draft's outcome."""
    try:
        catalog = _catalog()
        charter_ir = persisted_ir if persisted == CHARTER else charter_preview(target_date)
        charter = charter_side(charter_ir, session, catalog)
        plan = v04_built or v04_plan(target_date, block_workouts, catalog=catalog)
        report = diff_report(target_date, persisted, charter, v04_side(plan, catalog), run_at)
        write_report(report, put)
        return {"outcome": "recorded", "sk": report["sk"], "summary": report["summary"]}
    except Exception as e:  # noqa: BLE001 — named on the run's result, never the pre-draft's outcome
        logger.warning(f"predraft shadow failed ({type(e).__name__}: {e})")
        return {"outcome": "failed", "error": f"{type(e).__name__}: {e}"[:300]}
