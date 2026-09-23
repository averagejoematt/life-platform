"""critics_muscle_defense.py — the muscle-defense packet, extracted from `coach.critics`
(#4112 — the module was at its module-size ceiling; see docs/ENGINEERING_STANDARDS.md §2 and
the #2610/#2604 extraction precedent). No behavior moved with it: `coach.critics` re-exports
`build_muscle_defense_packet` unchanged, so every existing caller (`mcp.tools_plan`, the test
suite) reads it exactly as before.

WHAT THIS PACKET HOLDS: strength trend on the draft's anchor lifts + protein against the
owner's floor. `anchor_trends` is keyed by draft exercise idx: {last_top_lbs, drop_pct,
sessions_below, recent_median_e1rm_lb, baseline_median_e1rm_lb, n_sessions, anchor_family} —
built by `plan_engine.anchor_e1rm_trend`, the SAME rolling e1RM median the engine's tripwire
reads (#4098). Whether a trend trips is `plan_engine.anchor_drop_tripped`, and whether the
tripwire is armed at all is `plan_engine.not_before_week_gate` over `program_week` (the block
calendar's week — required, so no caller arms it by omission). This packet computes no drop
of its own. Missing -> unknown, never clear.

TWO TIERS, ONE COMPUTATION (#4112). Owner ruling, 2026-09-23 ~06:00 PT, on which lifts can
trigger a strength-drop flag: *"B but more emphasis on A as a benchmark, B more ancillary
tracked."* `anchor_family` (set only for the four core anchors — bench, row, squat, hinge —
#4069) is the tier gate. A row with no `anchor_family` is an ACCESSORY: its drop is always
reported `info`, tracked but never `change`/`veto`, whatever the numbers say — only a core
anchor can reach `tripped`. The accessory tier's full trend (including lifts with no drop to
report) is tracked in `training.accessory_strength_trend`, attached to the constraint block
beside this packet, never inside it — this packet's job is only the tripwire severity.
"""

from __future__ import annotations

from typing import Any

from training import owner_redlines


def build_muscle_defense_packet(
    draft: dict[str, Any],
    *,
    anchor_trends: dict[int, dict[str, Any]] | None,
    protein_days_missed_7d: int | None,
    protein_days_measured_7d: int | None,
    program_week: int | None,
) -> dict[str, Any]:
    from training import plan_engine

    from coach.critics import _flag

    by_id = {t["id"]: t for t in owner_redlines.TRIPWIRES}
    drop_t = by_id["anchor_lift_strength_drop"]
    prot_t = by_id["protein_floor_missed"]
    floor_g = owner_redlines.REDLINES["protein_floor_g"]["value"]
    numbers: dict[str, Any] = {
        "protein_floor_g": floor_g,
        "protein_days_missed_7d": protein_days_missed_7d,
        "protein_days_measured_7d": protein_days_measured_7d,
    }
    flags: list[dict[str, Any]] = []
    unknown: list[str] = []
    if protein_days_missed_7d is None:
        unknown.append("protein_days_missed_7d")
    elif protein_days_missed_7d >= prot_t["threshold_days"]:
        flags.append(
            _flag(
                "protein_days_missed_7d",
                "change",
                f"{protein_days_missed_7d} of the trailing 7 days below the {floor_g} g floor (threshold {prot_t['threshold_days']}) — {prot_t['action']}",
                provenance=prot_t["provenance"],
                field="session.total_sets",
                to="hold",
            )
        )
    elif protein_days_missed_7d > 0:
        flags.append(
            _flag(
                "protein_days_missed_7d",
                "info",
                f"{protein_days_missed_7d} day(s) below the floor in the trailing 7",
                provenance=prot_t["provenance"],
            )
        )
    gate = plan_engine.not_before_week_gate(drop_t, program_week)
    numbers["program_week"] = program_week
    for ex in draft["exercises"]:
        tr = (anchor_trends or {}).get(ex["idx"])
        k = f"anchor_drop_pct[{ex['idx']}]"
        if not tr or tr.get("drop_pct") is None:
            numbers[k] = None
            unknown.append(k)
            continue
        numbers[k] = tr["drop_pct"]
        numbers[f"anchor_sessions_below[{ex['idx']}]"] = tr.get("sessions_below")
        numbers[f"anchor_baseline_median_e1rm_lb[{ex['idx']}]"] = tr.get("baseline_median_e1rm_lb")
        numbers[f"anchor_recent_median_e1rm_lb[{ex['idx']}]"] = tr.get("recent_median_e1rm_lb")
        numbers[f"anchor_last_top_lbs[{ex['idx']}]"] = tr.get("last_top_lbs")
        # #4112: only a CORE anchor (#4069's `anchor_family`) can reach `change`/`veto` — an
        # accessory's drop is tracked and reported, never a plan-changing flag (owner ruling).
        is_core = bool(tr.get("anchor_family"))
        numbers[f"anchor_is_core_anchor[{ex['idx']}]"] = is_core
        tripped = is_core and plan_engine.anchor_drop_tripped(tr["drop_pct"], tr.get("sessions_below"))
        if gate and is_core and tr["drop_pct"] > 0:
            # #4098: the ramp weeks. A detraining return is not a strength loss, so the drop is
            # REPORTED (with the gate named) and never becomes a change.
            flags.append(
                _flag(
                    k,
                    "info",
                    f"{ex['label']}: -{tr['drop_pct']:.1f}% rolling e1RM median vs its baseline — anchor_lift_strength_drop is {gate}",
                    provenance=drop_t["provenance"],
                )
            )
        elif tripped:
            hold_to = tr.get("last_top_lbs")
            over = ex.get("top_weight_lbs") is not None and hold_to is not None and ex["top_weight_lbs"] > hold_to
            flags.append(
                _flag(
                    k,
                    "change",
                    f"{ex['label']}: -{tr['drop_pct']:.1f}% rolling e1RM median vs its baseline, {tr.get('sessions_below')} session(s) below "
                    f"— {drop_t['action']} "
                    f"[{drop_t['threshold_pct']}%/{drop_t['consecutive_sessions']}-session threshold is {drop_t['provenance']}, not his variance]",
                    provenance=drop_t["provenance"],
                    field=f"exercises[{ex['idx']}].weight_lbs" if over else None,
                    to=round(hold_to, 1) if over else None,
                )
            )
        elif tr["drop_pct"] > 0:
            flags.append(
                _flag(
                    k,
                    "info",
                    (
                        f"{ex['label']}: -{tr['drop_pct']:.1f}% rolling e1RM median vs its baseline ({tr.get('n_sessions')} sessions)"
                        if is_core
                        else f"{ex['label']} (accessory, tracked not benchmark): -{tr['drop_pct']:.1f}% rolling e1RM median vs its "
                        f"baseline ({tr.get('n_sessions')} sessions) — never a change or veto (#4112)"
                    ),
                    provenance=drop_t["provenance"],
                )
            )
    return {"critic": "muscle_defense", "numbers": numbers, "flags": flags, "unknown": unknown, "violations": []}
