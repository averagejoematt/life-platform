"""plan_engine.py — the deterministic constraint block behind every session plan (#3751).

WHY THIS EXISTS

Asked on 2026-09-13 how the platform decides his workout, the honest answer was: over
chat/MCP, nothing does. The tools return data — `get_training`, `get_acwr_status`,
`get_readiness_score`, `get_benchmark` — and `manage_hevy_routine` writes the result.
Everything in between is one chat turn. The 154-line structured procedure (freshness
first, coach-thread continuity, the weight-matched reference, tier-agnostic authoring,
dry-run then commit) lives only in `.claude/skills/daily-debrief/SKILL.md` and runs only
in Claude Code. **The client he happens to type into decided the quality of the plan.**

ADR-105 says deterministic computation comes before any LLM verdict. Today the
"computation" is whatever a model chose to call. This module is that stage, extracted:
one function, no model, no I/O of its own — every reader is injected — so the same inputs
always produce the same block, and the block can be printed beside the plan it produced.

WHAT THIS IS NOT (yet)

v1 computes the CONSTRAINTS and states what the evidence cannot support. It does not draft
the session, and it does not run the adversarial critics (#3752) — four reviewers holding
DIFFERENT evidence packets, which is the thing the owner actually asked for and which a
single model role-playing six personas in one pass is not. The tool says so in its own
output rather than letting a caller assume the red team ran.

ORDERING IS A CLAIM

The walking gap is computed and reported FIRST. Not for emphasis — because the blueprint
mined from his own campaign says walking is "the single most replicable, highest-confidence
driver in the dataset", and the owner's 2026-09-19 correction: count Strava PLUS Hevy treadmill/cycling
blocks (13–19 Sep measured >=8.79 hr against the proven ~8.5 hrs/wk; the Strava-only read said 5.09)
at this bodyweight. A planner that argues about heavy-day conservatism while the engine
that did the work last time sits near zero is having the wrong argument, and an engine that
buries that line under six others is helping it.

STANDING CONSTRAINTS ARE READ HERE TOO (#3715)

`training_context_registry` (#3821) drafted the standing injury/equipment list — the calf
lesion — and the S3-mirrored `TRAINING_CONTEXT.md` a human/chat session reads with `aws s3
cp` per `docs/coaching/COACH_SESSION.md`. That covers the conversational surface. It did
NOT cover this one: before this change, `tool_plan_next_session` (`mcp/tools_plan.py`)
returned a full constraint block with no mention of the calf lesion at all — a fresh MCP
session asking this tool for tomorrow's plan got nothing about it, because nothing in the
deterministic engine read the registry. That is acceptance box 2's gap, closed here by a
plain import of the same bundled registry `owner_redlines` already uses (no S3 read at
runtime — the #3675 inertness class: a Lambda must never depend on a live S3 fetch for a
value it can ship in the bundle). Until `training_context_registry.CONFIRMED_BY_OWNER`
flips (gate:owner), every block carries the same unconfirmed disclosure in `honesty` that
the conversational surface already gives — never silent coverage it does not have.
"""

from __future__ import annotations

from typing import Any, Callable

from health import deficit_disclosures

from training import owner_redlines, program_structure, training_context_registry

ENGINE_VERSION = "plan-engine@1.1.0"  # #3755: the program block + the computed rotation check


def _tripwire_states(
    *,
    protein_days_missed_7d: int | None,
    readiness_low_streak_days: int | None,
    anchor_lift_drop_pct: float | None,
    anchor_lift_drop_sessions: int | None,
    pain_flag_sites: list[str] | None,
    pain_layer_status: str | None,
    weight_stall_days: int | None,
    adherence_on_plan: bool | None,
) -> list[dict[str, Any]]:
    """Evaluate each owner tripwire against the inputs, or say why it could not be read.

    A tripwire whose input is absent reports `state: "unknown"`, never `"clear"`. The
    distinction is the whole #3767 lesson applied to safety conditions: a guard that reads
    as clear because nobody could look is worse than no guard, because it is trusted.
    """
    by_id = {t["id"]: t for t in owner_redlines.engine_evaluated_tripwires()}  # the v2 additions are named, not computed
    out: list[dict[str, Any]] = []

    def _row(tid: str, state: str, observed: Any, detail: str = "") -> dict[str, Any]:
        t = by_id[tid]
        row = {
            "id": tid,
            "state": state,  # tripped | clear | unknown
            "observed": observed,
            "signal": t["signal"],
            "action_if_tripped": t["action"],
            "provenance": t["provenance"],
        }
        if t.get("provenance") == "population-derived":
            # ADR-105 rule 4: a population-derived constant says so at the point of use.
            row["threshold_note"] = t["note"]
        if detail:
            row["detail"] = detail
        return row

    t = by_id["protein_floor_missed"]
    if protein_days_missed_7d is None:
        out.append(_row("protein_floor_missed", "unknown", None, "no intake rollup for the trailing 7d"))
    else:
        tripped = protein_days_missed_7d >= t["threshold_days"]
        out.append(_row("protein_floor_missed", "tripped" if tripped else "clear", f"{protein_days_missed_7d} of 7 days below floor"))

    t = by_id["readiness_floor"]
    if readiness_low_streak_days is None:
        out.append(_row("readiness_floor", "unknown", None, "no recovery series"))
    else:
        tripped = readiness_low_streak_days >= t["consecutive_days"]
        out.append(
            _row(
                "readiness_floor", "tripped" if tripped else "clear", f"{readiness_low_streak_days} consecutive days below {t['threshold']}"
            )
        )

    t = by_id["anchor_lift_strength_drop"]
    if anchor_lift_drop_pct is None or anchor_lift_drop_sessions is None:
        out.append(_row("anchor_lift_strength_drop", "unknown", None, "no band-matched anchor-lift comparison available"))
    else:
        tripped = anchor_lift_drop_pct >= t["threshold_pct"] and anchor_lift_drop_sessions >= t["consecutive_sessions"]
        out.append(
            _row(
                "anchor_lift_strength_drop",
                "tripped" if tripped else "clear",
                f"-{anchor_lift_drop_pct:.1f}% across {anchor_lift_drop_sessions} session(s)",
            )
        )

    # The pain tripwire reads the derived note layer, which was dark from the day it
    # shipped until 2026-09-13 (#3768). Its silence is only meaningful if the layer works.
    if pain_layer_status in (None, "dark", "unknown"):
        out.append(
            _row(
                "pain_flag_named_site",
                "unknown",
                None,
                f"the derived note layer reports layer_status={pain_layer_status!r} — its silence is not evidence of no pain (#3768)",
            )
        )
    elif pain_flag_sites:
        out.append(_row("pain_flag_named_site", "tripped", pain_flag_sites))
    else:
        out.append(_row("pain_flag_named_site", "clear", []))

    t = by_id["weight_stall_with_adherence"]
    if weight_stall_days is None or adherence_on_plan is None:
        out.append(_row("weight_stall_with_adherence", "unknown", None, "needs both a weight trend and an adherence read"))
    else:
        tripped = weight_stall_days >= t["threshold_days"] and adherence_on_plan
        out.append(
            _row(
                "weight_stall_with_adherence", "tripped" if tripped else "clear", f"{weight_stall_days}d stall, on-plan={adherence_on_plan}"
            )
        )

    return out


def constraint_block(
    *,
    date: str,
    weight_lb: float | None = None,
    walk_hr_wk_now: float | None = None,
    recovery_tier: str | None = None,
    acwr_flag: str | None = None,
    muscle_volume: dict[str, Any] | None = None,
    days_since_movement: dict[str, int] | None = None,
    reference: dict[str, Any] | None = None,
    protein_days_missed_7d: int | None = None,
    readiness_low_streak_days: int | None = None,
    anchor_lift_drop_pct: float | None = None,
    anchor_lift_drop_sessions: int | None = None,
    pain_flag_sites: list[str] | None = None,
    pain_layer_status: str | None = None,
    weight_stall_days: int | None = None,
    adherence_on_plan: bool | None = None,
    hevy_workouts_rotation_window: list[dict[str, Any]] | None = None,
    rotation_window_start: str | None = None,
) -> dict[str, Any]:
    """The deterministic inputs to tomorrow's session. No model, no I/O, no hidden state.

    Every argument is a value a caller already fetched, so this function is pure: the same
    inputs produce the same block, byte for byte, which is what makes it auditable and what
    lets chat and Claude Code be held to the same answer.
    """
    redlines = owner_redlines.summary()
    walking_floor = owner_redlines.REDLINES["walking_floor_hr_wk"]

    # FIRST, deliberately. See the module docstring.
    if walk_hr_wk_now is None:
        walking = {
            "state": "unknown",
            "floor_hr_wk": walking_floor["value"],
            "detail": "no walking volume available for the trailing window — the largest lever on the board is unmeasured",
        }
    else:
        gap = round(walking_floor["value"] - walk_hr_wk_now, 2)
        walking = {
            "state": "below_floor" if gap > 0 else "at_or_above_floor",
            "now_hr_wk": walk_hr_wk_now,
            "floor_hr_wk": walking_floor["value"],
            "gap_hr_wk": max(gap, 0),
            "pct_of_floor": round(100 * walk_hr_wk_now / walking_floor["value"], 1) if walking_floor["value"] else None,
            "provenance": walking_floor["provenance"],
            "detail": walking_floor["note"],
        }

    # What the weight-matched reference can and cannot support. These sentences are the
    # SKILL.md §4 rules moved into code, so they cannot be skipped by a caller in a hurry.
    ref_block: dict[str, Any] = {"available": bool(reference)}
    if reference:
        proven = reference.get("proven_target") or {}
        ev_ok = bool(proven.get("volume_citable"))
        ref_block.update(
            {
                "band": proven.get("band"),
                "band_distance_lb": proven.get("band_distance_lb"),
                "n_effective_days": proven.get("n_effective"),
                "evidence_tier": proven.get("evidence_tier"),
                "volume_citable": ev_ok,
                "measurement_is_a_floor": bool(proven.get("measurement_is_a_floor")),
                "must_say": [
                    s
                    for s in [
                        (
                            None
                            if ev_ok
                            else "the nearest losing-phase period is BELOW the volume evidence floor — cite it as description, never as a target"
                        ),
                        (
                            f"the reference band is {proven.get('band_distance_lb')} lb from his current weight — not a mirror"
                            if proven.get("band_distance_lb")
                            else None
                        ),
                        (
                            "this band carries an OWNER-ATTESTED overlay: the measured figure is a FLOOR, not the whole training (#3717)"
                            if proven.get("measurement_is_a_floor")
                            else None
                        ),
                        deficit_disclosures.INTAKE_NOT_COMPARABLE_TO_PRIOR_CUT,
                    ]
                    if s
                ],
            }
        )
    else:
        ref_block["must_say"] = [
            "no weight-matched reference was retrieved — do not substitute the current band, which is the period he is trying to escape"
        ]

    tripwires = _tripwire_states(
        protein_days_missed_7d=protein_days_missed_7d,
        readiness_low_streak_days=readiness_low_streak_days,
        anchor_lift_drop_pct=anchor_lift_drop_pct,
        anchor_lift_drop_sessions=anchor_lift_drop_sessions,
        pain_flag_sites=pain_flag_sites,
        pain_layer_status=pain_layer_status,
        weight_stall_days=weight_stall_days,
        adherence_on_plan=adherence_on_plan,
    )
    tripped = [t["id"] for t in tripwires if t["state"] == "tripped"]
    unknown = [t["id"] for t in tripwires if t["state"] == "unknown"]

    # #3755 — "is the accessory layer rotating" is COMPUTED from the performed Hevy record
    # over the program's own 14-day window, with its n and window stated (ADR-105), not
    # asserted from the pool the program declares. A program can list six accessories per
    # day and still have produced the same four movements every session; only the record
    # knows. The rows are injected (`mcp.tools_plan` reads them) so this function stays
    # pure, and an unreadable window reports `unknown`, never `ok`.
    program = program_structure.summary()
    rotation = program_structure.accessory_rotation(
        window_start=rotation_window_start or date,
        window_end=date,
        hevy_workouts=hevy_workouts_rotation_window,
    )

    return {
        "engine_version": ENGINE_VERSION,
        "date": date,
        "deterministic": True,
        # The order of these keys is the order the coach should reason in. Standing
        # constraints (injury/equipment, #3715) sit second, ahead of every volume/tripwire
        # detail: a session prescribed against an injury nobody re-stated is not a lesser
        # error than a bad volume choice, it is a different KIND of error, and it must be
        # visible before the plan gets that far. This is the MCP/server-side surface #3715
        # asked for — the S3-rendered doc COACH_SESSION.md sends a human/chat session to
        # is a mirror of this same bundled registry, never the other way around (#3675
        # class: a Lambda runtime never depends on a live S3 read for a value it can ship
        # in the bundle).
        "walking": walking,
        "standing_constraints": training_context_registry.summary(),
        "rate_target": owner_redlines.rate_target_lb_per_wk(weight_lb),
        # #3753 v2: tripwires the engine does not yet compute are NAMED here, never silent (ADR-105).
        "unevaluated_tripwires": owner_redlines.unevaluated_tripwires(),
        "recovery_tier": recovery_tier,
        "acwr_flag": acwr_flag,
        "muscle_volume": muscle_volume or {},
        "days_since_movement": days_since_movement or {},
        "reference": ref_block,
        "tripwires": tripwires,
        "tripped": tripped,
        "unreadable_tripwires": unknown,
        "redlines": redlines,
        # #3755 — the program the plan is supposed to be executing, as data, with its own
        # unresolved conflicts attached. `accessory_rotation_ok` is the computed answer to
        # the question the owner actually asked ("why is there so little variety?").
        "program": program,
        "accessory_rotation_ok": rotation["ok"],
        "accessory_rotation": rotation,
        "critics": {
            "ran": False,
            "note": (
                "v1: the deterministic stage only. The adversarial critics (#3752) — muscle-defense, joints/tendons, "
                "aggressive-rate advocate, blueprint historian, each holding a DIFFERENT evidence packet and each "
                "returning approve / change X / veto with the number it argued from — are not wired yet. Do not report "
                "a plan built on this block as red-teamed."
            ),
        },
        "honesty": [
            s
            for s in [
                (None if training_context_registry.CONFIRMED_BY_OWNER else training_context_registry.format_unconfirmed_notice()),
                (
                    None
                    if redlines["active"]
                    else "the owner's redlines are PROPOSED, not confirmed — this plan follows a posture he has not yet signed (#3753)"
                ),
                (
                    f"{len(owner_redlines.unevaluated_tripwires())} proposed v2 tripwire(s) are reported but NOT evaluated by this "
                    f"engine: {', '.join(owner_redlines.unevaluated_tripwires())} (#3753)"
                    if owner_redlines.unevaluated_tripwires()
                    else None
                ),
                f"{len(unknown)} tripwire(s) could not be evaluated: {', '.join(unknown)}" if unknown else None,
                (
                    None
                    if program["active"]
                    else f"TRAINING_PROGRAM v{program['program_version']} ({program['split']}) is PROPOSED, not approved — the engine is still running on the live week grid (#3755)"
                ),
                (
                    "the program has UNRESOLVED conflicts with the owner's own redlines: "
                    + ", ".join(c["id"] for c in program["conflicts"])
                    if program["conflicts"]
                    else None
                ),
                (
                    f"accessory rotation is {rotation['state']}: {rotation['detail']}"
                    if rotation["ok"] is None
                    else (
                        None
                        if rotation["ok"]
                        else "the accessory layer is NOT rotating — "
                        + ", ".join(f"{r['movement']} on {r['n_days']} days" for r in rotation["repeats_within_window"][:4])
                    )
                ),
                (
                    "population-derived thresholds in play: " + ", ".join(redlines["population_derived_thresholds"])
                    if redlines["population_derived_thresholds"]
                    else None
                ),
            ]
            if s
        ],
    }


def gather(readers: dict[str, Callable[[], Any]]) -> dict[str, Any]:
    """Call injected readers defensively and return kwargs for `constraint_block`.

    A reader that raises yields None for its field rather than failing the whole block —
    a plan built on nine of ten inputs, with the tenth reported unknown, is worth more
    than no plan. What it may never do is report the missing one as clear.
    """
    out: dict[str, Any] = {}
    for key, fn in readers.items():
        try:
            out[key] = fn()
        except Exception:  # noqa: BLE001
            out[key] = None
    return out
