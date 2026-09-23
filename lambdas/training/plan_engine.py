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

THE OWNER MAY DISMISS A PAIN FLAG (#4036)

The derived note layer flags pain over-inclusively by design ("confirm or dismiss before
loading that movement"), and under the v0.3 program a tripped `pain_flag_named_site`
substitutes the movement pattern for two weeks. Before #4036 the second half of that
sentence had nowhere to live: on 2026-09-21 Matthew said the right lower back flagged from
the 2026-09-13 Romanian Deadlift note was gone, and the tripwire had no way to hear it.
`pain_dismissals` is the owner-only DDB record (`USER#matthew#SOURCE#training_constraints /
DISMISSAL#<site>#<date>`) the CALLER read — injected like every other input, so this module
stays pure — and the comparison that decides whether it still holds lives once, in
`training_context_registry.resolve_flags`, shared with `coach.critics.build_joints_packet`.

A TRIPWIRE MUST SAY WHAT IT LOOKED AT (#4051)

The #4036 machinery above was correct and unreachable. Stage 1's flag input was built from
a DRAFT routine's exercise list, so on a day with no draft the set was empty, every branch
below fell through to `clear`, and the constraint block reported `pain_flag_named_site:
clear, observed []` at the same minute the note layer held a live pain flag on the Romanian
Deadlift and the owner's dismissal of that exact site sat in DynamoDB. A guard that cannot
see the layer it guards is silence dressed as clearance (#3768's class, one level up).

So `pain_evidence_scope` is now an input in its own right: the caller states which
movements it examined, over which window, across which phases, with the note layer's
status. `clear` is reachable ONLY from a scope that was read and named at least one
movement; an empty or unreadable scope reads `unknown` with `evidence: none — <reason>`.
And flags are evaluated BEFORE the layer-health branch, because a degraded layer qualifies
an ABSENCE of flags and can never un-say one that is on the record.

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

from training import owner_redlines, program_structure, self_added_volume, training_context_registry

ENGINE_VERSION = "plan-engine@1.6.0"  # #4081: self_added_volume evaluated from adherence's set counts; 1.5.0 #4098: `not_before_week` enforced + rolling e1RM anchor drop (1.4.0 #4072: input read states)
# plan-engine@1.4.0 (#4072): every input carries measured / absent / read_failed / not_read — a failed read is never "unknown"

# ── #4072: the read state of every engine input ──────────────────────────────────────
# `measured`   — the reader ran and returned a usable value.
# `absent`     — the reader ran and the window holds no data (a true absence, with its reason).
# `read_failed`— the reader RAISED, returned a tool error, or returned a shape with none of the
#                keys it is known to carry; the error class travels with it.
# `not_read`   — no reader is wired for this input on this path (named, never implied).
# `not_supplied` — a pure caller passed neither a value nor a status (the pre-#4072 contract).
MEASURED = "measured"
ABSENT = "absent"
READ_FAILED = "read_failed"
NOT_READ = "not_read"
NOT_SUPPLIED = "not_supplied"
INPUT_STATES = (MEASURED, ABSENT, READ_FAILED, NOT_READ, NOT_SUPPLIED)

# The engine inputs a status is reported for, and the tripwire each one feeds (if any).
ENGINE_INPUTS = (
    "walk_hr_wk_now",
    "weight_lb",
    "recovery_tier",
    "readiness_low_streak_days",
    "acwr_flag",
    "muscle_volume",
    "protein_days_missed_7d",
    "reference",
    "anchor_lift_drop_pct",
    "pain_evidence_scope",
    "pain_layer_status",
    "pain_dismissals",
    "weight_stall_days",
    "adherence_on_plan",
    "hevy_workouts_rotation_window",
    "hevy_workouts_prescription_window",
)
_TRIPWIRE_INPUT = {
    "protein_floor_missed": "protein_days_missed_7d",
    "readiness_floor": "readiness_low_streak_days",
    "anchor_lift_strength_drop": "anchor_lift_drop_pct",
    "weight_stall_with_adherence": "weight_stall_days",
    "pain_flag_named_site": "pain_evidence_scope",
    "self_added_volume": "hevy_workouts_prescription_window",
}


def input_status(state: str, detail: str | None = None, *, error: str | None = None, **extra: Any) -> dict[str, Any]:
    """One input's read state (#4072). `error` is `<ExceptionClass>: <message>` for a failed read."""
    if state not in INPUT_STATES:
        raise ValueError(f"unknown input state {state!r}")
    out: dict[str, Any] = {"state": state}
    if detail:
        out["detail"] = detail
    if error:
        out["error"] = error
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def error_label(exc: BaseException) -> str:
    """`<ExceptionClass>: <message>`, bounded — the class is the load-bearing half."""
    msg = str(exc).strip().replace("\n", " ")
    return f"{type(exc).__name__}: {msg}"[:200] if msg else type(exc).__name__


def _empty(v: Any) -> bool:
    return v is None or (isinstance(v, (list, dict, str)) and not v)


def resolve_input_states(values: dict[str, Any], stated: dict[str, dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """Every engine input's state: the caller's stated status, else inferred from the value.

    A value with no stated status is `measured` when non-empty and `not_supplied` when empty —
    never `absent`, because only the reader knows whether it looked and found nothing.
    """
    stated = stated or {}
    out: dict[str, dict[str, Any]] = {}
    for name in ENGINE_INPUTS:
        if name in stated and isinstance(stated[name], dict) and stated[name].get("state") in INPUT_STATES:
            out[name] = dict(stated[name])
        elif not _empty(values.get(name)):
            out[name] = input_status(MEASURED)
        else:
            out[name] = input_status(NOT_SUPPLIED, "the caller passed no value and no read status")
    return out


# ── the anchor-lift trend: ONE computation (#4098) ───────────────────────────
# v3's definition (`owner_redlines.TRIPWIRES` → `anchor_lift_strength_drop.definition_v3`): a
# rolling 3-session e1RM median against the 6-session baseline before it, per template
# identity. Before #4098 the engine compared the latest TOP WEIGHT with the trailing best
# weight, reps ignored — 75 lb × 5 on 2026-05-30 against 45 lb × 8 on 2026-09-19, one
# template (`878CD1D0`), read as "-40 %". The e1RM here is the session's `best_1rm` exactly as
# `mcp.strength_helpers.extract_hevy_sessions` computes it (Epley, warm-ups excluded) — this
# module adds no formula of its own. The per-exercise muscle-defense critic reads the SAME two
# functions below (`tests/test_anchor_e1rm_not_before_week_4098.py` holds that by AST).
E1RM_RECENT_SESSIONS = 3
E1RM_BASELINE_SESSIONS = 6


def _anchor_tripwire() -> dict[str, Any]:
    return next(t for t in owner_redlines.TRIPWIRES if t["id"] == "anchor_lift_strength_drop")


def anchor_e1rm_trend(e1rms_lb: list[float | None]) -> dict[str, Any]:
    """The rolling-median comparison over ONE identity's e1RM series (oldest first). Pure.

    Sessions with no e1RM (a bodyweight lift, reps outside the formula's gate) are skipped and
    counted. Fewer than `E1RM_RECENT_SESSIONS + E1RM_BASELINE_SESSIONS` usable sessions yields
    NO `drop_pct` — a comparison the series cannot support is unknown, never a small drop.
    """
    t = _anchor_tripwire()
    threshold = float(t["threshold_pct"])
    vals = [float(v) for v in e1rms_lb if v is not None and float(v) > 0]
    need = E1RM_RECENT_SESSIONS + E1RM_BASELINE_SESSIONS
    out: dict[str, Any] = {
        "metric": "e1rm_rolling_median",
        "window_sessions": {"recent": E1RM_RECENT_SESSIONS, "baseline": E1RM_BASELINE_SESSIONS},
        "n_sessions_e1rm": len(vals),
    }
    if len(vals) < len(e1rms_lb):
        out["sessions_without_e1rm"] = len(e1rms_lb) - len(vals)
    if len(vals) < need:
        out["insufficient"] = (
            f"{len(vals)} session(s) with an e1RM on this template — the rolling {E1RM_RECENT_SESSIONS}-session median against the "
            f"{E1RM_BASELINE_SESSIONS}-session baseline needs {need}"
        )
        return out
    from statistics import median

    recent = vals[-E1RM_RECENT_SESSIONS:]
    baseline = vals[-need:-E1RM_RECENT_SESSIONS]
    r_med = float(median(recent))
    b_med = float(median(baseline))
    out["recent_median_e1rm_lb"] = round(r_med, 1)
    out["baseline_median_e1rm_lb"] = round(b_med, 1)
    out["drop_pct"] = round(max(0.0, (b_med - r_med) / b_med * 100.0), 1) if b_med else None
    out["sessions_below"] = sum(1 for v in recent if v < b_med * (1 - threshold / 100.0))
    return out


def anchor_drop_tripped(drop_pct: float | None, sessions_below: int | None) -> bool:
    """The redline's own threshold over a trend from `anchor_e1rm_trend` — the one place it is applied."""
    if drop_pct is None:
        return False
    t = _anchor_tripwire()
    return float(drop_pct) >= float(t["threshold_pct"]) and int(sessions_below or 0) >= int(t["consecutive_sessions"])


# ── `not_before_week`: a redline that is not armed yet (#4098) ───────────────
# `anchor_lift_strength_drop` declares `not_before_week: 6` ("the ramp is still under 85 % of
# band e1RM"). Before #4098 nothing read it: the tripwire was live in the ramp weeks, comparing
# a detraining return with a best from before the break. The week is the v0.3 block calendar's
# (`program_structure.calendar_entry`, #4064); before block 1 it is week 0.
def program_week(day: str) -> int | None:
    """The block calendar's program week for `day` — 0 before block 1, None for an unreadable day key."""
    try:
        entry = program_structure.calendar_entry(day)
    except ValueError:
        return None
    return int(entry["week"]) if entry else 0


def not_before_week_gate(tripwire: dict[str, Any], week: int | None) -> str | None:
    """None when the tripwire is armed; otherwise the `not_yet_active (week N < M)` reason.

    The ONLY reader of `not_before_week` — the engine (`_tripwire_states`) and the
    muscle-defense critic both call it. An unknown week never arms a gated tripwire.
    """
    m = tripwire.get("not_before_week")
    if m is None:
        return None
    if week is None:
        return f"not_yet_active (week unknown < {int(m)})"
    if week < int(m):
        return f"not_yet_active (week {week} < {int(m)})"
    return None


def _evidence_scope_read(scope: dict[str, Any] | None) -> bool:
    """Did the caller actually examine anything? (#4051)

    A scope is only "read" when its own status says so AND it names at least one movement.
    Zero movements examined is the empty-evidence path that produced the defect — the read
    succeeded and looked at nothing, which is not the same as looking and finding nothing.
    """
    if not scope:
        return False
    if str(scope.get("status") or "") != "read":
        return False
    n = scope.get("movements_considered")
    try:
        return int(n) > 0
    except (TypeError, ValueError):
        return False


def _pain_read_failed(scope: dict[str, Any] | None, layer_status: str | None, input_states: dict[str, dict[str, Any]]) -> bool:
    """Did the pain row's evidence fail to READ (#4072)? Only asked once no flag is on the record."""
    if scope is not None and str(scope.get("status") or "") == READ_FAILED:
        return True
    if scope is None and (input_states.get("pain_evidence_scope") or {}).get("state") == READ_FAILED:
        return True
    return layer_status in (None, "dark", "unknown") and (input_states.get("pain_layer_status") or {}).get("state") == READ_FAILED


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
    pain_flag_instances: list[dict[str, Any]] | None = None,
    pain_dismissals: list[dict[str, Any]] | None = None,
    pain_evidence_scope: dict[str, Any] | None = None,
    input_states: dict[str, dict[str, Any]] | None = None,
    prescription_rows: list[dict[str, Any]] | None = None,
    date: str | None = None,
    week: int | None = None,
) -> list[dict[str, Any]]:
    """Evaluate each owner tripwire against the inputs, or say why it could not be read.

    A tripwire whose input is absent reports `state: "unknown"`, never `"clear"`. The
    distinction is the whole #3767 lesson applied to safety conditions: a guard that reads
    as clear because nobody could look is worse than no guard, because it is trusted.

    #4036 adds a fourth state for the same reason: a pain flag the OWNER dismissed reads
    `dismissed_by_owner` with his date and his words, never `clear`. An absence and an
    override are different facts, and only one of them has a human behind it.

    #4051 closes the hole under both of those: a `clear` (or `unknown`) pain row is only
    honest if something was actually LOOKED at, and stage 1 was looking at nothing — its
    flag input came from a draft's exercise list, so with no draft the set was empty and the
    row read `clear` over a live, flagged, owner-dismissed site. `pain_evidence_scope` is
    the caller's statement of WHAT it examined (which movements, over which window, across
    which phases); when it says nothing was examined the row is `unknown` with
    `evidence: none — <reason>`, never `clear`. Two ordering rules follow from it:
      * flags are evaluated BEFORE the layer-health check, so a degraded or dark layer can
        no longer erase a flag that is on the record (it only qualifies absence);
      * a scope that was read, with movements in it and no flags, is the ONLY thing that
        earns `clear`.
    `pain_evidence_scope=None` means the caller did not state a scope — the pre-#4051
    behaviour, kept for the pure-function callers that inject flags directly.

    #4072: `unknown` is reserved for an input that was ABSENT (or never read). An input whose
    read FAILED makes its row `read_failed`, with the error class — on 2026-09-15..18 the
    owner was told recovery, volume and protein were "unknown" while every source was fresh,
    and a reader cannot act on the difference between "no data" and "the read broke" if the
    block will not say which one it was. Every row carries its input's `input_state`.

    #4098: every tripwire that declares `not_before_week` reads `not_yet_active (week N < M)`
    until the block calendar's `week` reaches M — whatever its input says, which rides along
    as `state_if_active` so the gate never hides the number.
    """
    input_states = input_states or {}
    by_id = {t["id"]: t for t in owner_redlines.engine_evaluated_tripwires()}  # the v2 additions are named, not computed
    out: list[dict[str, Any]] = []

    def _row(tid: str, state: str, observed: Any, detail: str = "") -> dict[str, Any]:
        t = by_id[tid]
        row = {
            "id": tid,
            "state": state,  # tripped | clear | unknown | dismissed_by_owner (#4036) | not_yet_active (#4098, set below)
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
        src = _TRIPWIRE_INPUT.get(tid)
        if src and src in input_states:
            row["input"] = src
            row["input_state"] = input_states[src]
        return row

    def _missing(tid: str, fallback: str) -> dict[str, Any]:
        """The row for a tripwire whose input is None: `read_failed` or `unknown`, never conflated."""
        st = input_states.get(_TRIPWIRE_INPUT.get(tid, ""), {})
        if st.get("state") == READ_FAILED:
            return _row(tid, READ_FAILED, None, f"the read FAILED ({st.get('error') or 'error not captured'}) — not absent, not clear")
        why = st.get("detail")
        label = st.get("state")
        return _row(tid, "unknown", None, f"{label}: {why}" if (label and why and label != NOT_SUPPLIED) else fallback)

    t = by_id["protein_floor_missed"]
    if protein_days_missed_7d is None:
        out.append(_missing("protein_floor_missed", "no intake rollup for the trailing 7d"))
    else:
        tripped = protein_days_missed_7d >= t["threshold_days"]
        out.append(_row("protein_floor_missed", "tripped" if tripped else "clear", f"{protein_days_missed_7d} of 7 days below floor"))

    t = by_id["readiness_floor"]
    if readiness_low_streak_days is None:
        out.append(_missing("readiness_floor", "no recovery series was supplied to the engine"))
    else:
        tripped = readiness_low_streak_days >= t["consecutive_days"]
        out.append(
            _row(
                "readiness_floor", "tripped" if tripped else "clear", f"{readiness_low_streak_days} consecutive days below {t['threshold']}"
            )
        )

    t = by_id["anchor_lift_strength_drop"]
    if anchor_lift_drop_pct is None or anchor_lift_drop_sessions is None:
        out.append(
            _missing(
                "anchor_lift_strength_drop",
                f"no core-anchor e1RM comparison available (the rolling {E1RM_RECENT_SESSIONS}-session median needs "
                f"{E1RM_RECENT_SESSIONS + E1RM_BASELINE_SESSIONS} sessions on one template)",
            )
        )
    else:
        tripped = anchor_drop_tripped(anchor_lift_drop_pct, anchor_lift_drop_sessions)
        out.append(
            _row(
                "anchor_lift_strength_drop",
                "tripped" if tripped else "clear",
                f"-{anchor_lift_drop_pct:.1f}% rolling e1RM median, {anchor_lift_drop_sessions} of the last "
                f"{E1RM_RECENT_SESSIONS} session(s) below threshold",
            )
        )

    # The pain tripwire. Flags FIRST (#4051): a degraded or dark layer qualifies the
    # ABSENCE of flags — it can never un-say one that is on the record. The live layer is
    # `degraded` today (`cap_exceeded x24`, deterministic signals only) and the 2026-09-13
    # Romanian Deadlift flag is one of those degraded rows.
    scope_read = _evidence_scope_read(pain_evidence_scope)
    if pain_flag_sites or pain_flag_instances:
        # #4036: the owner may dismiss a flagged site ("right lower back gone", 2026-09-21).
        # The dismissal is a DDB record the caller read; the RULE — including the date
        # comparison that re-arms it — lives in `training_context_registry`, once, so this
        # engine and the joints critic cannot drift into two different answers.
        instances = pain_flag_instances or [{"movement": s, "note_dates": []} for s in (pain_flag_sites or [])]
        sites = pain_flag_sites or [str(i.get("movement")) for i in instances]
        resolutions = training_context_registry.resolve_flags(instances, pain_dismissals)
        dismissed = {r["movement"] for r in resolutions if r.get("dismissed")}
        live = [str(i.get("movement")) for i in instances if i.get("movement") not in dismissed]
        if resolutions and not live:
            # NEVER "clear": the flag happened and a human overrode it. That is a different
            # row from "nothing was flagged", and a reader must be able to tell them apart.
            row = _row("pain_flag_named_site", "dismissed_by_owner", sites, "; ".join(r["detail"] for r in resolutions))
            row["dismissals"] = resolutions
        else:
            detail = "; ".join(r["detail"] for r in resolutions)
            row = _row("pain_flag_named_site", "tripped", live or sites, detail)
            if resolutions:
                row["dismissals"] = resolutions
        # #4051: the layer's status travels WITH the flags, never instead of them, and the
        # instances carry their own note dates so the dismissal comparison is auditable.
        #
        # `by_movement` is the per-site verdict, because the row's single `state` is an
        # AGGREGATE and the aggregate is the coarser question. Once stage 1 reads every
        # movement he PERFORMED rather than the two or three in a draft, two flags on one
        # day is the ordinary case — measured 2026-09-22: Romanian Deadlift (dismissed
        # 2026-09-21) AND Walking ("lower back aching", 2026-09-08, never dismissed). The
        # aggregate is correctly `tripped` there, and a reader who wants to know whether
        # HIS dismissal held must not have to infer it from that.
        row["instances"] = instances
        row["by_movement"] = {
            str(i.get("movement")): ("dismissed_by_owner" if i.get("movement") in dismissed else "tripped") for i in instances
        }
        row["layer_status"] = pain_layer_status
        if pain_layer_status in (None, "dark", "unknown", "degraded"):
            row["layer_note"] = (
                f"the derived note layer reports layer_status={pain_layer_status!r}: these are the DETERMINISTIC flags on "
                "the record and they stand, but the layer's silence about any other movement is not evidence of no pain (#3768/#4051)"
            )
        if pain_evidence_scope:
            row["evidence"] = pain_evidence_scope
        out.append(row)
    elif _pain_read_failed(pain_evidence_scope, pain_layer_status, input_states):
        # #4072: the performed-movement read (or the note layer's health read) RAISED. That
        # is not an empty set and not an unknown one — it is a broken read, and it says which
        # error broke it.
        scope = pain_evidence_scope or {}
        err = (
            scope.get("error")
            or (input_states.get("pain_evidence_scope") or {}).get("error")
            or (input_states.get("pain_layer_status") or {}).get("error")
            or "error not captured"
        )
        row = _row(
            "pain_flag_named_site",
            READ_FAILED,
            None,
            f"evidence: read FAILED ({err}) — " + str(scope.get("reason") or "the pain evidence could not be read"),
        )
        if pain_evidence_scope:
            row["evidence"] = pain_evidence_scope
        row["layer_status"] = pain_layer_status
        out.append(row)
    elif pain_layer_status in (None, "dark", "unknown"):
        # #3768: the layer was dark from the day it shipped until 2026-09-13. With no flag
        # on the record, its silence is only meaningful if the layer works.
        row = _row(
            "pain_flag_named_site",
            "unknown",
            None,
            f"the derived note layer reports layer_status={pain_layer_status!r} — its silence is not evidence of no pain (#3768)",
        )
        if pain_evidence_scope:
            row["evidence"] = pain_evidence_scope
        out.append(row)
    elif pain_evidence_scope is not None and not scope_read:
        # #4051: nothing was examined, so nothing can be called clear.
        row = _row(
            "pain_flag_named_site",
            "unknown",
            None,
            "evidence: none — " + str(pain_evidence_scope.get("reason") or "the caller stated no readable evidence scope"),
        )
        row["evidence"] = pain_evidence_scope
        row["layer_status"] = pain_layer_status
        out.append(row)
    else:
        row = _row("pain_flag_named_site", "clear", [])
        row["layer_status"] = pain_layer_status
        if pain_evidence_scope:
            row["evidence"] = pain_evidence_scope
        out.append(row)

    t = by_id["weight_stall_with_adherence"]
    if weight_stall_days is None or adherence_on_plan is None:
        out.append(_missing("weight_stall_with_adherence", "needs both a weight trend and an adherence read"))
    else:
        tripped = weight_stall_days >= t["threshold_days"] and adherence_on_plan
        out.append(
            _row(
                "weight_stall_with_adherence", "tripped" if tripped else "clear", f"{weight_stall_days}d stall, on-plan={adherence_on_plan}"
            )
        )

    # #4081 — self_added_volume: training above the prescription two weeks running, from the
    # per-movement programmed/performed set counts `health.adherence_calc` stored on each Hevy
    # row against the routine that was COMMITTED for it. `training.self_added_volume` reads
    # those counts; it counts nothing of its own. The row carries every week's set-level
    # evidence (which movement, which day, prescribed → performed), so `tripped` and `clear`
    # are both auditable without leaving the block.
    # #4098's week gate below applies to this row too (it carries no `not_before_week` today).
    t = by_id["self_added_volume"]
    if prescription_rows is None or not date:
        out.append(_missing("self_added_volume", "no Hevy rows were supplied for the prescription window"))
    else:
        ev = self_added_volume.evaluate(prescription_rows, date, int(t["threshold_weeks"]))
        row = _row("self_added_volume", ev["state"], ev.get("observed"), ev.get("detail") or "")
        row["evidence"] = {
            "rule": ev["rule"],
            "threshold_weeks": ev["threshold_weeks"],
            "run_weeks": ev.get("run_weeks"),
            "window": {"start": ev.get("window_start"), "end": ev.get("window_end")},
            "weeks": ev["weeks"],
            "counts_from": "health.adherence_calc (adherence.movements on each Hevy row: programmed_sets vs performed_sets)",
        }
        out.append(row)
    # #4098: the week gate, applied to EVERY row whose tripwire declares `not_before_week` —
    # never per-tripwire, so a new declaration is read the day it is written.
    for row in out:
        reason = not_before_week_gate(by_id[row["id"]], week)
        if reason:
            row["state_if_active"] = row["state"]
            row["state"] = "not_yet_active"
            row["not_before_week"] = by_id[row["id"]]["not_before_week"]
            row["program_week"] = week
            row["detail"] = reason + (f" — {row['detail']}" if row.get("detail") else "")

    return out


def _scheduled_session(day: str, catalog_movements: dict[str, Any] | None, skill_ceiling: int) -> dict[str, Any]:
    """The session the program schedules on `day` (#4064). Pure.

    ACTIVE program: `program_structure.planned_session` — the block calendar, then the §3
    prescription. Inactive: the engine runs on the JSON grid, which this pure function
    cannot read, so it says that rather than inventing a session.
    """
    if not program_structure.ACTIVE:
        return {
            "date": day,
            "source": "json",
            "archetype": None,
            "note": (
                f"TRAINING_PROGRAM v{program_structure.PROGRAM_VERSION} is PROPOSED — the live config/training_week.json grid decides "
                "this day's archetype; `manage_hevy_routine draft` reads it"
            ),
        }
    try:
        out = program_structure.planned_session(day, catalog_movements=catalog_movements, skill_ceiling=skill_ceiling)
    except ValueError as e:
        return {"date": day, "source": "unreadable", "archetype": None, "note": str(e)}
    if catalog_movements is None and out.get("prescription"):
        out["catalog_note"] = "the movement catalog was not read — anchors are named by PATTERN, movements unresolved"
    elif out.get("prescription"):
        # #4090: the week's direct hard sets per redline muscle, beside the range each must sit in
        out["weekly_sets_by_muscle"] = program_structure.weekly_sets_by_muscle(catalog_movements or {}, skill_ceiling)
    out["how_to_draft"] = (
        "manage_hevy_routine action=draft target_date=" + day + " builds exactly this session (the generator reads the same "
        "calendar and prescription); draft_custom only for a deliberate departure"
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
    pain_flag_instances: list[dict[str, Any]] | None = None,
    pain_dismissals: list[dict[str, Any]] | None = None,
    pain_evidence_scope: dict[str, Any] | None = None,
    weight_stall_days: int | None = None,
    adherence_on_plan: bool | None = None,
    hevy_workouts_rotation_window: list[dict[str, Any]] | None = None,
    rotation_window_start: str | None = None,
    hevy_workouts_prescription_window: list[dict[str, Any]] | None = None,
    catalog_movements: dict[str, Any] | None = None,
    skill_ceiling: int = 2,
    input_status: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The deterministic inputs to tomorrow's session. No model, no I/O, no hidden state.

    Every argument is a value a caller already fetched, so this function is pure: the same
    inputs produce the same block, byte for byte, which is what makes it auditable and what
    lets chat and Claude Code be held to the same answer.

    `input_status` (#4072) is the caller's statement of HOW each value was obtained —
    `measured` / `absent` / `read_failed` (+ error class) / `not_read`. It is reported per
    input on `inputs`, and it is what lets a None read `read_failed` instead of `unknown`.
    """
    states = resolve_input_states(
        {
            "walk_hr_wk_now": walk_hr_wk_now,
            "weight_lb": weight_lb,
            "recovery_tier": recovery_tier,
            "readiness_low_streak_days": readiness_low_streak_days,
            "acwr_flag": acwr_flag,
            "muscle_volume": muscle_volume,
            "protein_days_missed_7d": protein_days_missed_7d,
            "reference": reference,
            "anchor_lift_drop_pct": anchor_lift_drop_pct,
            "pain_evidence_scope": pain_evidence_scope,
            "pain_layer_status": pain_layer_status,
            "pain_dismissals": pain_dismissals,
            "weight_stall_days": weight_stall_days,
            "adherence_on_plan": adherence_on_plan,
            "hevy_workouts_rotation_window": hevy_workouts_rotation_window,
            "hevy_workouts_prescription_window": hevy_workouts_prescription_window,
        },
        input_status,
    )
    failed_reads = {k: v for k, v in states.items() if v["state"] == READ_FAILED}
    redlines = owner_redlines.summary()
    walking_floor = owner_redlines.REDLINES["walking_floor_hr_wk"]

    # FIRST, deliberately. See the module docstring.
    if walk_hr_wk_now is None and "walk_hr_wk_now" in failed_reads:
        walking = {
            "state": READ_FAILED,
            "floor_hr_wk": walking_floor["value"],
            "error": failed_reads["walk_hr_wk_now"].get("error"),
            "detail": "the walking-volume read FAILED — the largest lever on the board is unread, which is not the same as zero (#4072)",
        }
    elif walk_hr_wk_now is None:
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

    # #4098: the block calendar's week decides which redlines are armed (`not_before_week`).
    week = program_week(date)

    tripwires = _tripwire_states(
        protein_days_missed_7d=protein_days_missed_7d,
        readiness_low_streak_days=readiness_low_streak_days,
        anchor_lift_drop_pct=anchor_lift_drop_pct,
        anchor_lift_drop_sessions=anchor_lift_drop_sessions,
        pain_flag_sites=pain_flag_sites,
        pain_layer_status=pain_layer_status,
        weight_stall_days=weight_stall_days,
        adherence_on_plan=adherence_on_plan,
        pain_flag_instances=pain_flag_instances,
        pain_dismissals=pain_dismissals,
        pain_evidence_scope=pain_evidence_scope,
        input_states=states,
        prescription_rows=hevy_workouts_prescription_window,
        date=date,
        week=week,
    )
    tripped = [t["id"] for t in tripwires if t["state"] == "tripped"]
    unknown = [t["id"] for t in tripwires if t["state"] == "unknown"]
    failed_tripwires = [t["id"] for t in tripwires if t["state"] == READ_FAILED]
    not_yet_active = [t["id"] for t in tripwires if t["state"] == "not_yet_active"]
    # #4036: every dismissal in play, named on the block — a reader never has to dig into
    # the tripwire row to find out that a human overrode a safety flag.
    dismissals_in_play = [d for t in tripwires for d in (t.get("dismissals") or [])]

    # #3755 — "is the accessory layer holding still" (v0.3: accessories are FIXED for the
    # block, so the defect is an accessory ADDED mid-block, not one repeated) is COMPUTED
    # from the performed Hevy record over the program's own 14-day window, with its n and
    # window stated (ADR-105), not asserted from the pool the program declares. Only the
    # record knows what was actually done. The rows are injected (`mcp.tools_plan` reads them) so this function stays
    # pure, and an unreadable window reports `unknown`, never `ok`.
    program = program_structure.summary()
    rotation = program_structure.accessory_rotation(
        window_start=rotation_window_start or date,
        window_end=date,
        hevy_workouts=hevy_workouts_rotation_window,
    )

    session = _scheduled_session(date, catalog_movements, skill_ceiling)

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
        # #4064 — WHAT the program schedules on this date: the block calendar's answer
        # (block 1 starts Thu 2026-09-24, then Mon/Wed/Fri, deload every 6th week) and, on a
        # lifting day, the §3 session — anchors at heavy/moderate with their sets and reps,
        # the fixed accessories, the Hevy folder. Third, right after the two safety keys:
        # walking and the standing constraints outrank any single session.
        "session": session,
        "rate_target": owner_redlines.rate_target_lb_per_wk(weight_lb),
        # #3753 v3: tripwires the engine does not yet compute are NAMED here, never silent (ADR-105).
        "unevaluated_tripwires": owner_redlines.unevaluated_tripwires(),
        "recovery_tier": recovery_tier,
        "acwr_flag": acwr_flag,
        "muscle_volume": muscle_volume or {},
        "days_since_movement": days_since_movement or {},
        "reference": ref_block,
        "tripwires": tripwires,
        "tripped": tripped,
        # #4072: both kinds of "could not evaluate", kept apart — `unreadable_tripwires` is the
        # union (its pre-#4072 meaning: not evaluable), `failed_read_tripwires` the broken reads.
        "unreadable_tripwires": unknown + failed_tripwires,
        "failed_read_tripwires": failed_tripwires,
        # #4072: every input's read state — measured / absent / read_failed (+ error) / not_read.
        "inputs": states,
        # #4098 — the block calendar's week, and the tripwires its `not_before_week` holds off.
        "program_week": week,
        "not_yet_active_tripwires": not_yet_active,
        # #4051 — WHAT the pain tripwire looked at: the movements PERFORMED in the trailing
        # window, the window, the phases read, the note layer's status. A reader can tell an
        # examined-and-clean row from an empty one without leaving the block.
        "pain_evidence": pain_evidence_scope or {"status": "not_stated", "reason": "the caller stated no pain-evidence scope"},
        "owner_dismissals": dismissals_in_play,  # #4036 — empty list means none in play, never "none exist"
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
                    f"{len(owner_redlines.unevaluated_tripwires())} v{owner_redlines.REDLINES_VERSION} tripwire(s) are reported but NOT evaluated by this "
                    f"engine: {', '.join(owner_redlines.unevaluated_tripwires())} (#3753)"
                    if owner_redlines.unevaluated_tripwires()
                    else None
                ),
                f"{len(unknown)} tripwire(s) could not be evaluated: {', '.join(unknown)}" if unknown else None,
                (
                    f"{len(not_yet_active)} tripwire(s) are not yet active in program week {week}: "
                    + ", ".join(not_yet_active)
                    + " — held off by their own not_before_week, not cleared (#4098)"
                    if not_yet_active
                    else None
                ),
                # #4072: a failed read is named as FAILED, with its error class — never folded
                # into "could not be evaluated", which a reader takes to mean "no data".
                (
                    f"{len(failed_reads)} engine input(s) FAILED to read — not absent, not clear: "
                    + "; ".join(f"{k} ({v.get('error') or 'error not captured'})" for k, v in failed_reads.items())
                    + " (#4072)"
                    if failed_reads
                    else None
                ),
                # #4051: the pain row's evidence set, named out loud. An empty one is the
                # defect this issue is about, so it is a sentence in `honesty`, not a key
                # a reader has to go looking for.
                (
                    None
                    if _evidence_scope_read(pain_evidence_scope)
                    else (
                        "the pain tripwire examined NO movements — "
                        + str((pain_evidence_scope or {}).get("reason") or "the caller stated no pain-evidence scope")
                        + " (#4051)"
                    )
                ),
                # #4036: a dismissal is an owner OVERRIDE of a safety flag. It is named out
                # loud, with his words and the date, whether it currently holds or has been
                # superseded by a later note on the same site.
                *[
                    (
                        f"owner dismissal in play — {d['site']!r} dismissed {d['dismissed_on']} ({str(d['words'])!r}): "
                        f"the {d['movement']} pain flag reads dismissed_by_owner, NOT clear (#4036)"
                        if d.get("dismissed")
                        else f"owner dismissal SUPERSEDED — {d['detail']} (#4036)"
                    )
                    for d in dismissals_in_play
                ],
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
                    f"the accessory layer is {rotation['state']}: {rotation['detail']}"
                    if rotation["ok"] is None
                    else (
                        None
                        if rotation["ok"]
                        else "the accessory layer is DRIFTING (v0.3 fixes accessories for the block) — added in the trailing 7 days: "
                        + ", ".join(rotation["added_in_trailing_7d"][:4])
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
    a plan built on nine of ten inputs, with the tenth reported, is worth more than no plan.
    What it may never do is report the missing one as clear — or, since #4072, as merely
    "unknown": the raise is recorded under `input_status` as `read_failed` with its error
    class, and an empty return as `absent`.
    """
    out: dict[str, Any] = {}
    status: dict[str, dict[str, Any]] = {}
    for key, fn in readers.items():
        try:
            out[key] = fn()
        except Exception as e:  # noqa: BLE001
            out[key] = None
            status[key] = input_status(READ_FAILED, error=error_label(e))
            continue
        status[key] = input_status(ABSENT, "the reader returned no data") if _empty(out[key]) else input_status(MEASURED)
    out["input_status"] = status
    return out
