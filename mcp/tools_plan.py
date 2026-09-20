"""tools_plan.py — one server-side planning surface, so the client stops deciding (#3751, #3752).

Before this, asking for tomorrow's session over chat/MCP got you fourteen data tools and
whatever rigor that one turn happened to bring. The structured procedure existed only in
`.claude/skills/daily-debrief/SKILL.md`, which only Claude Code runs. Same owner, same
data, same question, two different answers depending on which app he opened.

STAGE 1 — `plan_next_session()` is the deterministic stage (`training.plan_engine`)
reachable from every client. It gathers the same inputs the debrief skill enumerates,
computes the constraint block with no model in the loop, and returns it — with what the
evidence cannot support stated in the payload rather than left to the caller's discipline.

STAGE 2 — `plan_next_session(routine_id=...)` is the red team (#3752). Four critics —
`coach.critics` — each get a DISJOINT evidence packet assembled here from the same readers
a chat turn would call, each make ONE model call, and each return approve / change <field>
to <value> / veto with the number they argued from. Changes are applied to the draft and
the revised draft is re-checked deterministically; the verdicts are stored on the routine
(`inputs_snapshot["critics"]`), where `manage_hevy_routine` reads them: a veto blocks the
commit and the verdicts ride into the Hevy notes. A thread row goes to the training coach.

The model calls are tier-gated by `budget_guard` (feature `plan_critics`). When paused,
the deterministic layer still runs and every verdict says the model did not — a routine is
never reported as red-teamed by a model that was not consulted.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from common.pacific_time import pacific_today

from mcp.core import LAYER_UNKNOWN

logger = logging.getLogger("tools_plan")

ANCHOR_HISTORY_LOOKBACK_DAYS = 180
PAIN_LOOKBACK_DAYS = 28
STREAK_LOOKBACK_DAYS = 14
BLOCK_LOOKBACK_DAYS = 56  # 8 weeks, enough to count the trailing consistent block (>=2 lifts/wk)


def _safe(fn, *a, **kw):
    """Call a tool defensively — a reader that fails yields None, never a default."""
    try:
        return fn(*a, **kw)
    except Exception:  # noqa: BLE001
        return None


def _walking_volume_last_7d(end_date: str) -> dict[str, Any] | None:
    """The derived walking-volume layer for the trailing 7 days: Strava UNION Hevy (#3930).

    Was Strava-only, and that single-source read is what reported 5.09 hr/wk — "the largest
    gap on the board" — for a week carrying 8.33 hr of treadmill and cycling duration logged
    INSIDE Hevy sessions. A floor stated in hours must be measured in hours from every source
    that produces them; `training.walking_volume` is the union and the per-source breakdown.

    Hours, not miles and not steps: the blueprint's floor is stated in hours per week, and
    converting from either needs an assumption this module would be inventing.

    Reads both partitions DIRECTLY rather than through `get_workouts`: that tool's
    `_slim_workout` projection drops `exercises`, which is where the cardio blocks live, and
    the per-workout detail tool costs a five-year scan each. A source that RAISES is passed
    to the layer as None — unreadable, never zero.
    """
    from common.pacific_time import shift_day_key
    from training import walking_volume

    from mcp.core import query_source_range

    start = shift_day_key(end_date, -6)
    if start == end_date:  # unparseable day key — shift_day_key returns it unchanged
        return None
    # `query_source` always returns a list, so None here means the read RAISED — the one
    # case the layer must not read as "he did nothing".
    return walking_volume.build(
        window_start=start,
        window_end=end_date,
        strava_items=_safe(query_source_range, "strava", start, end_date),
        hevy_workouts=_safe(query_source_range, "hevy", start, end_date),
    )


def _rotation_window(end_date: str) -> tuple[str | None, list[dict[str, Any]] | None]:
    """(window start, Hevy rows) for the program's trailing accessory-rotation window (#3755).

    Read DIRECTLY from the hevy partition, the same way `_walking_volume_last_7d` does and
    for the same reason: `get_workouts`'s `_slim_workout` projection drops `exercises`,
    which is the only place the movement NAMES live — and the names ARE the measurement
    here. A read that RAISES yields None, so the engine reports rotation `unknown` rather
    than reading an empty window as a clean rotation.
    """
    from common.pacific_time import shift_day_key
    from training import program_structure

    from mcp.core import query_source_range

    window_days = int(program_structure.ROTATION_RULE["window_days"])
    start = shift_day_key(end_date, -(window_days - 1))
    if start == end_date:  # unparseable day key — shift_day_key returns it unchanged
        return None, None
    return start, _safe(query_source_range, "hevy", start, end_date)


def _merge_walking_volume(block: dict[str, Any], layer: dict[str, Any] | None) -> None:
    """Put the per-source breakdown on the block's walking read, beside the total (#3930).

    The engine computes state/gap from one number. That number is now a union of two sources,
    and a union whose parts you cannot see is exactly the shape that produced the wrong flag
    in the first place — so the breakdown, the counting rule, the overlap ruling and the
    steps exclusion all travel WITH the verdict rather than in a separate payload a caller
    may not read. The engine keeps its single-float contract; this is presentation.
    """
    w = block.get("walking")
    if not isinstance(w, dict):
        return
    if not layer:
        w["sources"] = {"status": "unreadable", "detail": "the walking-volume layer could not be built for this window"}
        return
    w["sources"] = layer["by_source"]
    w["by_modality"] = layer["by_modality"]
    w["counted_modalities"] = layer["counted_modalities"]
    w["counting_rule"] = layer["counting_rule"]
    w["overlap_rule"] = layer["overlap_rule"]
    w["excluded_proxies"] = layer["excluded_proxies"]
    w["derived_steps_estimate"] = layer["derived_steps_estimate"]
    w["window"] = layer["window"]
    w["volume_layer"] = layer["version"]
    w["total_is_floor"] = layer["total_is_floor"]
    if layer["honesty"]:
        w["honesty"] = list(layer["honesty"])


def _protein_days_7d(end_date: str) -> tuple[int | None, int | None]:
    """(days below the owner's protein floor, days measured) over the trailing 7 days.

    Counts only days MacroFactor logged — an unlogged day is not a missed day, it is an
    unmeasured one, and the measured count travels with the answer so 0-of-2 is never
    read as 0-of-7 (ADR-104).
    """
    from training import owner_redlines

    from mcp.tools_nutrition import tool_get_nutrition

    floor_g = owner_redlines.REDLINES["protein_floor_g"]["value"]
    res = tool_get_nutrition({"view": "summary", "start_date": _minus_days(end_date, 6), "end_date": end_date}) or {}
    # LIVE SHAPE (2026-09-20): the summary view returns `daily_breakdown`, not `daily_rows`. The
    # first deployed stage-2 run read the wrong key and reported protein UNKNOWN on a week with
    # six logged days — the #3767 class this module's own comment claims to have checked.
    rows = [r for r in (res.get("daily_breakdown") or res.get("daily_rows") or []) if r.get("protein_g") is not None]
    if not rows:
        return None, None
    return sum(1 for r in rows if float(r["protein_g"]) < floor_g), len(rows)


def tool_plan_next_session(args):
    """Stage 1: the deterministic constraint block (#3751). Stage 2, with `routine_id`: the
    four critics over disjoint evidence, verdicts stored on the draft (#3752)."""
    args = args or {}
    target_date = args.get("target_date") or pacific_today()
    routine_id = args.get("routine_id")

    from training import plan_engine

    # Each reader is the SAME tool a chat turn would have called — the point is not new
    # data, it is that the call set is fixed instead of improvised per conversation.
    from mcp.tools_benchmark import tool_get_benchmark
    from mcp.tools_health import tool_get_readiness_score
    from mcp.tools_strength import tool_get_muscle_volume
    from mcp.tools_training import tool_get_acwr_status

    ir = None
    if routine_id:
        from training.routine_repo import get_current

        from mcp.utils import mcp_error

        ir = _safe(get_current, routine_id)
        if not ir:
            return mcp_error(
                f"routine_id={routine_id} not found — draft it first (manage_hevy_routine draft_custom)", error_code="NOT_FOUND"
            )

    reference = _safe(tool_get_benchmark, {"view": "prescription", "date": target_date})
    if isinstance(reference, dict) and reference.get("applicable") is False:
        # An inapplicable reference is not a reference. Carry the reason, drop the shape.
        reference = {"proven_target": None, "_inapplicable_reason": reference.get("reason")}

    weight = None
    if isinstance(reference, dict):
        weight = reference.get("current_weight")

    readiness = _safe(tool_get_readiness_score, {"date": target_date}) or {}
    acwr = _safe(tool_get_acwr_status, {}) or {}
    volume = _safe(tool_get_muscle_volume, {"start_date": _minus_days(target_date, 28), "end_date": target_date}) or {}
    protein_missed, protein_measured = _safe(_protein_days_7d, target_date) or (None, None)

    # The pain tripwire reads the derived note layer; its STATUS decides whether silence
    # means anything (#3767/#3768). Absent a per-movement query here, the layer's own
    # health is the honest input, and `unknown` is the honest default.
    layer_status = LAYER_UNKNOWN
    try:
        from training.training_notes import training_notes_health

        from mcp.config import table
        from mcp.core import derived_layer_status

        layer_status = derived_layer_status(training_notes_health(table))[0]
    except Exception:  # noqa: BLE001
        pass

    evidence = _gather_draft_evidence(ir, target_date, layer_status) if ir is not None else None
    worst = _worst_anchor(evidence) if evidence else (None, None)

    # #3930: the walking read is a UNION layer (Strava + Hevy treadmill/cycling blocks), not a
    # Strava-only number. The engine takes the total in hours — the floor's own unit — and the
    # per-source breakdown is merged onto the block below so no reader has to trust the total.
    walk_layer = _safe(_walking_volume_last_7d, target_date)

    # #3755: the performed Hevy record over the program's rotation window, so the engine
    # can COMPUTE whether the accessory layer is rotating instead of assuming the pool.
    rotation_start, rotation_rows = _safe(_rotation_window, target_date) or (None, None)

    block = plan_engine.constraint_block(
        date=target_date,
        weight_lb=weight,
        walk_hr_wk_now=(walk_layer or {}).get("total_hr"),
        # Key names verified against each tool's live return shape rather than assumed —
        # a planner reading a key that does not exist degrades to "unknown" silently,
        # which is the #3767 failure wearing different clothes.
        recovery_tier=_recovery_tier(readiness),
        # LIVE SHAPES (2026-09-20, read off the deployed tools, not assumed): get_acwr_status
        # carries the flag as `zone` (`alert` is a bool that is False when safe, so `alert or
        # interpretation` returned the METHODOLOGY PROSE as the flag); get_muscle_volume keys its
        # per-muscle table as `muscle_volume`, each row with `total_sets` / `avg_sets_per_week`.
        acwr_flag=(acwr.get("zone") or acwr.get("alert_reason")),
        muscle_volume=_muscle_sets(volume),
        days_since_movement=(
            {e["label"]: e["days_since"] for e in evidence["exercises"] if e.get("days_since") is not None} if evidence else None
        ),
        reference=reference if isinstance(reference, dict) else None,
        protein_days_missed_7d=protein_missed,
        anchor_lift_drop_pct=worst[0],
        anchor_lift_drop_sessions=worst[1],
        pain_flag_sites=([e["label"] for e in evidence["exercises"] if e.get("pain_flag_any")] if evidence else None),
        # with a draft in hand the per-movement note reads report the layer's status themselves
        pain_layer_status=((evidence or {}).get("pain_layer_status") or layer_status),
        hevy_workouts_rotation_window=rotation_rows,
        rotation_window_start=rotation_start,
    )
    _merge_walking_volume(block, walk_layer)

    out: dict[str, Any] = {
        "target_date": target_date,
        "constraint_block": block,
        "protein_days_measured_7d": protein_measured,
        "how_to_use": (
            "Stage 1 is the deterministic constraint block: draft against it, then say plainly which constraint "
            "shaped which choice. Every line under `reference.must_say` is required in the answer, verbatim in "
            "substance, not summarised away. Then draft (manage_hevy_routine draft_custom) and call this tool again "
            "WITH routine_id — stage 2, the red team (#3752). A routine that skipped stage 2 is NOT red-teamed and "
            "its commit says so."
        ),
        "_disclaimer": (
            "For personal health tracking only. Not medical advice. Descriptive of Matthew's own n=1 history. "
            "Consult a qualified healthcare provider before making health decisions based on this data."
        ),
    }
    if ir is not None:
        out["critics"] = _run_stage_2(
            ir, block, reference if isinstance(reference, dict) else None, evidence, protein_missed, protein_measured, target_date
        )
        out["how_to_use"] = (
            "Stage 2 ran. Read `critics.verdicts` — each names the metric and number it argued from. A `veto` blocks "
            "commit: redraft and run stage 2 again. `change` verdicts are already applied to the draft (see "
            "`critics.changes`); dry_run shows the revised body. Then commit — the verdicts ride in the Hevy notes."
        )
    return out


# ── stage 2 evidence: the SAME readers a chat turn would call, gathered per draft lift ──
def _gather_draft_evidence(ir: Any, target_date: str, layer_status: str) -> dict[str, Any]:
    """Per-draft-exercise evidence for the critics: anchor-lift trend, pain flags, days since.
    Plus the streak and lifting-session count from the performed Hevy record."""
    from training import owner_redlines

    from mcp.recovery_authoring import _consecutive_days
    from mcp.tools_strength import tool_get_exercise_history
    from mcp.tools_training_notes import tool_get_exercise_notes

    drop_t = next(t for t in owner_redlines.TRIPWIRES if t["id"] == "anchor_lift_strength_drop")
    resolver = _safe(_resolver)
    exercises: list[dict[str, Any]] = []
    for idx, ex in enumerate(getattr(ir, "exercises", None) or []):
        key = getattr(ex, "movement_key", "") or ""
        label = (getattr(ex, "rationale_tag", "") or "") if (getattr(ex, "rationale_tag", "") or "") != "custom" else key
        tid = _safe(resolver, key) if resolver else None
        row: dict[str, Any] = {"idx": idx, "label": label or key, "template_id": tid}
        hist = (
            _safe(
                tool_get_exercise_history,
                {"template_id": tid, "start_date": _minus_days(target_date, ANCHOR_HISTORY_LOOKBACK_DAYS), "end_date": target_date},
            )
            if tid
            else None
        )
        sessions = (hist or {}).get("sessions") or []
        if sessions:
            last = sessions[-1]
            row["days_since"] = _days_between(last.get("date"), target_date)
            row["last_top_lbs"] = last.get("best_weight")
            prior = [s.get("best_weight") for s in sessions[:-2] if s.get("best_weight")]
            if prior:
                best = max(float(w) for w in prior)
                row["trailing_best_lbs"] = round(best, 1)
                last_two = [float(s.get("best_weight") or 0) for s in sessions[-2:]]
                row["drop_pct"] = round(max(0.0, (best - last_two[-1]) / best * 100.0), 1) if best else None
                row["sessions_below"] = sum(1 for w in last_two if w < best * (1 - drop_t["threshold_pct"] / 100.0))
                row["n_sessions"] = len(sessions)
        pain = _safe(tool_get_exercise_notes, {"template_id": tid, "lookback_days": PAIN_LOOKBACK_DAYS}) if tid else None
        if pain and "error" not in pain:
            row["pain_flag_any"] = pain.get("pain_flag_any")
            row["pain_dates"] = pain.get("pain_dates") or []
            row["pain_layer_status"] = pain.get("layer_status")
        exercises.append(row)

    dates = _safe(_workout_dates, _minus_days(target_date, BLOCK_LOOKBACK_DAYS), target_date)
    consecutive = _consecutive_days(dates, target_date) if dates is not None else None
    week_start = _minus_days(target_date, 7)
    lifting_7d = len({d for d in dates if week_start <= d < target_date}) if dates is not None else None
    weeks_in_block = _weeks_in_block(dates, target_date) if dates is not None else None
    # the per-movement reads each carry the derived layer's own status; a dark read on ANY
    # drafted movement makes the whole pain input unknown (never clear by omission, #3768)
    statuses = [e.get("pain_layer_status") for e in exercises if e.get("pain_layer_status")]
    if statuses and all(s not in ("dark", "unknown") for s in statuses):
        layer_status = statuses[0]
    elif statuses:
        layer_status = next(s for s in statuses if s in ("dark", "unknown"))
    return {
        "exercises": exercises,
        "consecutive_days": consecutive,
        "lifting_sessions_7d": lifting_7d,
        "weeks_in_block": weeks_in_block,
        "pain_layer_status": layer_status,
    }


def _weeks_in_block(dates: list[str], target_date: str, min_per_week: int = 2, max_weeks: int = 8) -> int:
    """Trailing consecutive 7-day windows (ending the day before target) with >= min_per_week lifts."""
    weeks = 0
    for w in range(max_weeks):
        end = _minus_days(target_date, 7 * w)  # exclusive
        start = _minus_days(target_date, 7 * (w + 1))
        if len({d for d in dates if start <= d < end}) >= min_per_week:
            weeks += 1
        else:
            break
    return weeks


def _resolver():
    from mcp.tools_hevy_routine import _make_resolver

    return _make_resolver()


def _workout_dates(start: str, end: str) -> list[str]:
    """Performed lifting days, read through `get_workouts` — the SAME tool a chat turn calls.

    Deliberately not a direct partition read: a new reader of a partition another module
    writes is a new must-agree seam (#2847), and this module needs only the dates the
    existing tool already normalises."""
    from mcp.tools_hevy import tool_get_workouts

    res = tool_get_workouts({"start_date": start, "end_date": end, "source": "hevy", "limit": 500}) or {}
    return sorted({(w.get("date") or "")[:10] for w in res.get("workouts") or [] if w.get("date")})


def _worst_anchor(evidence: dict[str, Any]) -> tuple[float | None, int | None]:
    rows = [e for e in evidence.get("exercises", []) if e.get("drop_pct") is not None]
    if not rows:
        return None, None
    w = max(rows, key=lambda e: e["drop_pct"])
    return w["drop_pct"], w.get("sessions_below")


def _days_between(a: str | None, b: str) -> int | None:
    try:
        return (datetime.strptime(b, "%Y-%m-%d") - datetime.strptime(str(a)[:10], "%Y-%m-%d")).days
    except (TypeError, ValueError):
        return None


# ── stage 2: the red team ────────────────────────────────────────────────────────────
def _run_stage_2(
    ir: Any,
    block: dict[str, Any],
    reference: dict[str, Any] | None,
    evidence: dict[str, Any],
    protein_missed,
    protein_measured,
    target_date: str,
) -> dict[str, Any]:
    from coach import critics
    from training.routine_repo import put_versioned

    from mcp.tools_hevy_routine import _validate_ir_for_hevy

    by_idx = {e["idx"]: e for e in evidence["exercises"]}

    def build(draft: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            "muscle_defense": critics.build_muscle_defense_packet(
                draft,
                anchor_trends={i: e for i, e in by_idx.items() if e.get("drop_pct") is not None},
                protein_days_missed_7d=protein_missed,
                protein_days_measured_7d=protein_measured,
            ),
            "joints_tendons": critics.build_joints_packet(
                draft,
                pain_by_idx={i: e for i, e in by_idx.items() if "pain_flag_any" in e},
                days_since_by_idx={i: e.get("days_since") for i, e in by_idx.items()},
                consecutive_days=evidence.get("consecutive_days"),
                pain_layer_status=evidence.get("pain_layer_status"),
            ),
            "rate_advocate": critics.build_rate_advocate_packet(
                draft,
                tripwires=block.get("tripwires"),
                walking=block.get("walking"),
                rate_target=block.get("rate_target"),
                current_rate_lb_wk=(reference or {}).get("current_rate_lb_wk"),
                lifting_sessions_7d=evidence.get("lifting_sessions_7d"),
            ),
            "blueprint_historian": critics.build_historian_packet(
                draft, reference=reference, weeks_in_block=evidence.get("weeks_in_block")
            ),
        }

    # LIVE FINDING 2026-09-20 (routine 73bc228c v5 -> v6): a re-run on an already-critiqued
    # routine compounded the joints critic's cut (22 -> 18 -> 14) because every `session.total_sets`
    # change is relative to the draft the critic sees. Stage 2 must be a re-EVALUATION of the
    # coach's draft, never a second cut on its own output: restore the pre-critics exercise list
    # first, and keep that snapshot on the record so the next run can do the same.
    prior = (getattr(ir, "inputs_snapshot", None) or {}).get("critics") or {}
    if prior.get("draft_exercises"):
        from training.routine_ir import _exercise_from_raw

        ir.exercises = [_exercise_from_raw(dict(e)) for e in prior["draft_exercises"]]
    from dataclasses import asdict

    draft_exercises = [asdict(e) for e in ir.exercises]
    draft = critics.draft_summary(ir)
    packets = build(draft)
    allowed, paused = _model_allowed()
    invoke = None
    if allowed:
        from ai.bedrock_client import invoke as _invoke

        invoke = _invoke
    verdicts = critics.run_critics(packets, draft, invoke=invoke, model_allowed=allowed, model_paused_reason=paused)
    changes = critics.apply_changes(ir, verdicts)
    rc = critics.recheck(ir, build)
    precheck = _validate_ir_for_hevy(ir)
    rc["hevy_precheck_errors"] = precheck["errors"]
    rc["passed"] = bool(rc["passed"] and not precheck["errors"])
    record = {
        "engine": critics.CRITICS_VERSION,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "target_date": target_date,
        "model_ran": allowed,
        "model_paused_reason": paused,
        "verdicts": verdicts,
        "changes": changes,
        "recheck": rc,
        "veto": any(v.get("verdict") == "veto" for v in verdicts),
        "packet_numbers": {cid: p["numbers"] for cid, p in packets.items()},
        # the coach's draft as critiqued, so a re-run re-evaluates THIS, not its own output
        "draft_exercises": draft_exercises,
    }
    ir.inputs_snapshot = {**(getattr(ir, "inputs_snapshot", None) or {}), "critics": record}
    # LIVE FINDING 2026-09-20: Hevy's routine object carries NO `notes` field on the API (GET keys
    # are created_at/exercises/folder_id/id/title/updated_at; a PUT with notes reads back without
    # them). Every routine-level WHY note the compiler has ever sent is invisible there. EXERCISE
    # notes do land, verifiably — the recovery session block already lives there for that reason
    # (`_apply_recovery_adaptation`). So the verdicts ride on the FIRST exercise's notes, where he
    # will actually read them at the gym, as well as the routine-level field.
    _place_block_on_first_exercise(ir)
    ir.parent_version = ir.version
    ir.version = int(ir.version) + 1
    put_versioned(ir)
    out = dict(record)
    out["routine_id"] = ir.routine_id
    out["routine_version"] = ir.version
    out["thread"] = _write_thread(ir, pacific_today())
    out["notes_preview"] = critics.notes_block(ir)
    out["next"] = (
        "VETO — redraft (manage_hevy_routine draft_custom), then run stage 2 again; commit will refuse until no veto stands."
        if record["veto"]
        else "no veto — manage_hevy_routine dry_run shows the revised body, then commit."
    )
    return out


_BLOCK_MARK = "RED TEAM ("


def _place_block_on_first_exercise(ir: Any) -> None:
    """Prepend the critics' block to exercise[0].notes, replacing any earlier block (a re-run
    must not stack two)."""
    from coach import critics

    block = critics.notes_block(ir)
    if not block or not getattr(ir, "exercises", None):
        return
    first = ir.exercises[0]
    existing = first.notes or ""
    if _BLOCK_MARK in existing:
        head, _, tail = existing.partition(_BLOCK_MARK)
        # drop the old block: everything from the mark to the next blank line
        rest = tail.split("\n\n", 1)
        existing = (head + (rest[1] if len(rest) > 1 else "")).strip()
    first.notes = (block + ("\n\n" + existing if existing else "")).strip()


def _model_allowed() -> tuple[bool, str | None]:
    """Whether the four model calls may run at the current budget tier."""
    try:
        from ai import budget_guard
        from coach.critics import BUDGET_FEATURE

        if budget_guard.allow(BUDGET_FEATURE):
            return True, None
        return False, f"budget tier {budget_guard.current_tier()} — {BUDGET_FEATURE} paused; deterministic layer only"
    except Exception as e:  # noqa: BLE001
        return False, f"budget guard unreadable ({type(e).__name__}) — deterministic layer only"


def _write_thread(ir: Any, today: str) -> dict[str, Any]:
    """Tonight's verdicts as a training coach thread row — keyed with a `#critics` suffix so it
    sits beside the analyzer's weekly entry and never overwrites it; class-gated phase stamp
    at write time (#3514/#3900)."""
    from coach import critics
    from experiment.phase_taxonomy import experiment_stamp_for

    from mcp.config import table

    item = critics.thread_entry(ir, today=today)
    try:
        item.update(experiment_stamp_for(item["pk"], item["sk"]))
        item["created_at"] = datetime.now(timezone.utc).isoformat()
        clean = json.loads(json.dumps(item, default=str), parse_float=Decimal)
        table.put_item(Item=clean)
        return {"written": True, "sk": item["sk"]}
    except Exception as e:  # noqa: BLE001 — reported in the result, never swallowed (#3670 class)
        logger.warning("critics thread write failed: %s", e)
        return {"written": False, "sk": item["sk"], "error": f"{type(e).__name__}: {e}"[:200]}


def _recovery_tier(readiness: dict) -> str | None:
    """GREEN / YELLOW / RED from the readiness score, in the authoring spec's bands.

    `get_readiness_score` returns a 0-100 `score`, not a tier; the recovery-adaptive
    authoring spec (SPEC_RECOVERY_ADAPTIVE_AUTHORING_2026-06-21) is what maps a number to
    a branch. Doing the mapping here keeps the engine's input in the vocabulary the
    cues are written in.
    """
    # LIVE SHAPE (2026-09-20): get_readiness_score returns `readiness_score`; the two names read
    # before it were guesses and the tier came back None on a GREEN 80.1 day.
    score = readiness.get("readiness_score")
    if score is None:
        score = readiness.get("score")
    if score is None:
        score = readiness.get("recovery_score")
    try:
        score = float(score)
    except (TypeError, ValueError):
        return None
    if score >= 67:
        return "green"
    if score >= 34:
        return "yellow"
    return "red"


def _muscle_sets(volume: dict[str, Any]) -> dict[str, Any]:
    """{muscle: weekly sets} from get_muscle_volume's live shape, or {} when it is absent."""
    table = volume.get("muscle_volume") or volume.get("muscle_sets") or volume.get("by_muscle") or {}
    out: dict[str, Any] = {}
    for muscle, row in table.items():
        if isinstance(row, dict):
            v = row.get("avg_sets_per_week", row.get("total_sets"))
            if v is not None:
                out[muscle] = v
        elif isinstance(row, (int, float)):
            out[muscle] = row
    return out


def _minus_days(date_str: str, days: int) -> str:
    """#3751: day-key arithmetic belongs to the Pacific frame, not to this module.

    Was a local `date.fromisoformat(...) - timedelta(...)`, which is the idiom #3609's
    registry exists to inventory. `shift_day_key` is that operation, named once, with
    the same return-it-unchanged fallback this function already had.
    """
    from common.pacific_time import shift_day_key

    return shift_day_key(date_str, -days)
