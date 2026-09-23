"""full_body_session.py — v0.3 §3's full-body session as IR (#4064).

`routine_generator.generate_routines` hands a day here when the schedule entry is a v0.3
role (`program_structure.SESSION_TEMPLATES`: heavy / moderate / heavy_moderate /
optional_fourth). Split out of `routine_generator` so neither module crosses the 1000-line
ceiling (#1665); it reuses the generator's helpers rather than copying them, so the load
floor, the notes and the ceilings are the SAME code on both paths.

`program_structure.session_prescription_for_role` is the §3 session as data; this turns it
into IR. Everything the muscle-budget path guarantees still holds here — the load floor
(#3927) is the last thing to touch a WORKING or TOP set's load, re-based onto v0.3 §3's
entry ramp (`load_ramp`, #4090: the week's share of the discounted band anchor, never
100 % of the band best), the ceilings are asserted,
the notes quote the same history — with one addition §3 names explicitly: a heavy
exposure's back-offs sit at −10 % of the top set. That is the one sanctioned set below the
floor, and every one is written into the rationale, never applied silently.
"""

from __future__ import annotations

from typing import Any

from training import load_ramp, program_structure, routine_generator as _rg
from training.routine_generator import (
    LAYOFF_DAYS_DEFAULT,
    GeneratorInputs,
    _autoreg_multiplier,
    _build_exercise_note,
    _build_inputs_snapshot,
    _enforce_load_floors,
    _floor_half_kg,
    _fmt_load,
    _make_re_entry,
    _new_routine_id,
    _now_iso,
    _portfolio_guard,
    attach_cardio_cues,
)
from training.routine_ir import ExerciseBlock, RoutineSpec, Set

_AUTOREG_DROP_ACCESSORIES_AT = 0.6
"""At the red autoregulation multiplier the accessories go — §3: 'first thing dropped on a
bad day'. Subtract-only: nothing is ever added on a green day."""


def _blocks_from_prescription(
    rx: dict[str, Any],
    catalog: dict[str, Any],
    note_indexes: tuple[dict[str, list], dict[str, float], dict[str, list], dict[str, list]] | None,
    notes_mode: str,
    *,
    anchors_only: bool = False,
    top_plus_one: bool = False,
) -> tuple[list[ExerciseBlock], list[dict[str, Any]], list[str]]:
    """(blocks, exposures-in-block-order, unresolved lines). `top_plus_one` is the Minimum
    Viable Session: every anchor as its first two sets (top set + one back-off)."""
    history_index, weight_index, cardio_index, whoop_index = note_indexes or ({}, {}, {}, {})
    blocks: list[ExerciseBlock] = []
    used: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for e in rx["exposures"]:
        if anchors_only and e["kind"] != "anchor":
            continue
        key = e.get("movement_key")
        if not key:
            unresolved.append(f"{e.get('pattern') or 'accessory'}: {e.get('resolution_note')}")
            continue
        mdef = catalog.get("movements", {}).get(key, {})
        sets_spec = e["sets"][:2] if top_plus_one else e["sets"]
        sets = [Set(type="normal", rep_range_start=sp["reps"][0], rep_range_end=sp["reps"][1]) for sp in sets_spec]
        note = ""
        if not anchors_only:
            note = _build_exercise_note(
                key,
                catalog,
                history_index,
                notes_mode,
                weight_index=weight_index,
                cardio_index=cardio_index,
                whoop_index=whoop_index,
            )
        # History first (the ADR-068 one-best-line convention every note reader expects to
        # lead), then the §3 prescription; the floor cue is appended after both.
        cue = e["cue"]
        notes = f"{note} {cue}".strip() if note else cue
        tag = f"{e['kind']}:{e.get('pattern') or key}:{e['intensity']}"
        blocks.append(
            ExerciseBlock(
                movement_key=key,
                sets=sets,
                rest_seconds=e["rest_seconds"],
                notes=notes,
                joint_friendly_score=mdef.get("joint_friendly_score", 3),
                skill_tier=mdef.get("skill_tier", 1),
                rationale_tag=tag,
            )
        )
        used.append({**e, "sets": sets_spec})
    return blocks, used, unresolved


def _apply_back_offs(
    blocks: list[ExerciseBlock], used: list[dict[str, Any]], rationale: list[str], floors: dict[str, Any] | None = None
) -> list[str]:
    """Set every back-off to −10 % of its top set (rounded DOWN to 0.5 kg). Runs AFTER the
    floor, which stamps the top set; a top set with no load leaves its back-offs unloaded.

    #4090: the back-off load is recorded as `back_off_floor_kg` on the movement's audit row,
    so the commit gate checks each back-off against ITS floor rather than the top set's —
    without it every §3 heavy exposure read as a subtract-only violation at commit."""
    lines: list[str] = []
    movements = (floors or {}).get("movements") or {}
    for block, e in zip(blocks, used):
        kinds = [sp["kind"] for sp in e["sets"]]
        if "top" not in kinds:
            continue
        pct = next((sp["pct_of_top"] for sp in e["sets"] if sp["kind"] == "back_off"), None)
        top = block.sets[kinds.index("top")].weight_kg
        if not top or pct is None:
            continue
        back_off_kg = _floor_half_kg(float(top) * pct / 100.0)
        for s_obj, sp in zip(block.sets, e["sets"]):
            if sp["kind"] == "back_off":
                s_obj.weight_kg = back_off_kg
        if block.movement_key in movements:
            movements[block.movement_key]["back_off_floor_kg"] = back_off_kg
        line = (
            f"{block.movement_key}: back-offs at {pct}% of the {_fmt_load(float(top))} top set "
            "(§3 — the one sanctioned set below the floor)"
        )
        lines.append(line)
        rationale.append(line)
    return lines


def full_body_routines(
    inputs: GeneratorInputs,
    day_entry: dict[str, Any],
    week_cfg: dict[str, Any],
    landmarks: dict[str, Any],
    catalog: dict[str, Any],
    resolved_week: Any,
    targets: list[str],
) -> list[RoutineSpec]:
    """The v0.3 §3 session for `day_entry['session_role']` — ideal + Minimum Viable Session
    floor (+ re-entry after a layoff). Pure apart from the same config/history reads as the
    muscle-budget path."""
    role = day_entry["session_role"]
    deload = bool(day_entry.get("deload"))
    skill_ceiling = int(week_cfg.get("skill_ceiling", 2))
    rx = program_structure.session_prescription_for_role(
        role, deload=deload, catalog_movements=catalog.get("movements") or {}, skill_ceiling=skill_ceiling
    )
    autoreg = _autoreg_multiplier(inputs.recovery_tier, inputs.acwr_flag)
    rationale: list[str] = [
        f"week grid source={resolved_week.source} ({resolved_week.detail})",
        f"archetype=full; session_role={role}; autoreg={autoreg:.2f} (recovery={inputs.recovery_tier}, acwr={inputs.acwr_flag})",
    ]
    if day_entry.get("source") == "block_calendar":
        rationale.append(f"block calendar: week {day_entry['week']}, block {day_entry['block']}" + (" — DELOAD" if deload else ""))
    else:
        rationale.append(f"weekday grid: {day_entry.get('label')}")
    if deload and rx.get("deload_trim"):
        t = rx["deload_trim"]
        rationale.append(f"deload: sets {t['sets_before']} -> {t['sets_after']} ({t['pct']}%), loads held")
    if day_entry.get("optional"):
        rationale.append(f"OPTIONAL session — {day_entry.get('gate') or 'not required this week'}")
    drop_accessories = autoreg <= _AUTOREG_DROP_ACCESSORIES_AT
    if drop_accessories:
        rationale.append("recovery/ACWR red: accessories dropped (§3 — the first thing dropped on a bad day); anchors unchanged")
    z2_floor = week_cfg.get("z2_floor_minutes", 90)
    if not _portfolio_guard(inputs.z2_minutes_7d, z2_floor):
        rationale.append(
            f"z2 7d={inputs.z2_minutes_7d:.0f} < floor {z2_floor}: the §3 session is already the minimum effective dose, "
            "so the strength budget is NOT trimmed further — walk more instead"
        )

    notes_mode = week_cfg.get("exercise_notes_mode", "one_best_line")
    # through the module attribute, so ONE patch point (routine_generator._load_note_indexes)
    # stubs the history read for both paths
    note_indexes = _rg._load_note_indexes(week_cfg, notes_mode)
    blocks, used, unresolved = _blocks_from_prescription(rx, catalog, note_indexes, notes_mode, anchors_only=drop_accessories)
    for line in unresolved:
        rationale.append(f"UNRESOLVED — {line}")

    history_index, weight_index, _cardio, _whoop = note_indexes
    # #4090: v0.3 §3's entry ramp — the week's share of the discounted band anchor, never 100 %
    # of the band best. A day with no calendar week (before block 1) ramps as week 1.
    ramp_week = int(day_entry.get("week") or 1)
    ramp_p = load_ramp.params()
    rationale.append(
        f"loads: v0.3 §3 entry ramp, week {ramp_week} = {load_ramp.ramp_pct(ramp_week, ramp_p)}% of the band anchor after the "
        f"{ramp_p['discount_pct']}% detraining discount (cap {ramp_p['cap_pct']}% of band e1RM); back-offs −10 % of the top set"
    )
    load_floors = _enforce_load_floors(
        blocks,
        catalog,
        history_index,
        weight_index,
        target_date=inputs.target_date,
        days_since_last_workout=inputs.days_since_last_workout,
        layoff_days=int(week_cfg.get("re_entry_days_threshold", LAYOFF_DAYS_DEFAULT)),
        rationale=rationale,
        floor_transform=lambda f: load_ramp.ramp_floor(f, ramp_week),
    )
    load_floors["load_rule"] = {"rule": "v0.3 §3 entry ramp", "week": ramp_week, "params": ramp_p}
    load_floors["back_offs"] = _apply_back_offs(blocks, used, rationale, load_floors)

    caps = {
        "total_sets": week_cfg["session_set_ceiling"],
        "session_minutes": week_cfg["session_minutes_ceiling"],
        "weekly_volume_per_muscle": week_cfg["weekly_volume_cap_per_muscle"],
    }
    total_sets = sum(len(b.sets) for b in blocks)
    assert total_sets <= caps["total_sets"], f"BUG: total_sets {total_sets} > cap {caps['total_sets']}"
    est_minutes = total_sets * 3 + len(blocks) * 2
    assert est_minutes <= caps["session_minutes"], f"BUG: est_minutes {est_minutes} > cap {caps['session_minutes']}"

    budget_used: dict[str, int] = {}
    for b in blocks:
        muscle = catalog.get("movements", {}).get(b.movement_key, {}).get("primary_muscle") or "unknown"
        budget_used[muscle] = budget_used.get(muscle, 0) + len(b.sets)
    rationale.append(f"{total_sets} sets over {len(blocks)} movements (~{est_minutes} min)")

    label = rx["role_label"]
    week_tag = f" — W{day_entry['week']}" if day_entry.get("week") else ""
    title = f"Full Body {label}{week_tag}" + (" DELOAD" if deload else "") + f" — {inputs.target_date}"
    if day_entry.get("optional"):
        title += " (optional)"
    calendar_snapshot = {k: day_entry.get(k) for k in ("source", "week", "block", "deload", "label", "session_role")}
    ideal = RoutineSpec(
        routine_id=_new_routine_id(inputs.target_date, "full", "ideal"),
        target_date=inputs.target_date,
        archetype="full",
        variant="ideal",
        title=title,
        notes="\n".join(rationale[:6]),
        version=1,
        created_at=_now_iso(),
        created_by="cron",
        source_action="cron_generated",
        status="draft",
        exercises=blocks,
        budget_used=budget_used,
        inputs_snapshot=_build_inputs_snapshot(inputs, landmarks, catalog)
        | {"load_floors": load_floors, "session_prescription": rx, "calendar": calendar_snapshot},
        rationale=rationale,
        caps=caps,
    )
    attach_cardio_cues(ideal, catalog=catalog, cardio_index=note_indexes[2], whoop_index=note_indexes[3])

    # The Minimum Viable Session (§3): anchors only, top set + one back-off, ~25 min.
    # Resolved at skill tier 1 — the floor has always been machine/DB-only for the version
    # of Matthew who shows up tired, so the bench anchor is the machine press here.
    mvs_rx = program_structure.session_prescription_for_role(
        role, deload=False, catalog_movements=catalog.get("movements") or {}, skill_ceiling=1
    )
    mvs_blocks, _mvs_used, _ = _blocks_from_prescription(mvs_rx, catalog, None, "off", anchors_only=True, top_plus_one=True)
    floor_cap = int(week_cfg.get("floor_session_set_count", 6)) + 2
    floor = RoutineSpec(
        routine_id=_new_routine_id(inputs.target_date, "full", "floor"),
        target_date=inputs.target_date,
        archetype="full",
        variant="floor",
        title=f"Floor — {inputs.target_date}",
        notes="Minimum Viable Session (v0.3 §3): anchors only, top set + one back-off, ~25 min.",
        version=1,
        created_at=_now_iso(),
        created_by="cron",
        source_action="floor",
        status="draft",
        sibling_routine_id=ideal.routine_id,
        exercises=mvs_blocks,
        budget_used={b.movement_key: len(b.sets) for b in mvs_blocks},
        inputs_snapshot={"variant": "floor", "target_minutes": week_cfg.get("floor_session_minutes", 25), "session_role": role},
        rationale=["Minimum Viable Session — anchors only, top set + one back-off (v0.3 §3)."],
        caps={
            "total_sets": max(floor_cap, sum(len(b.sets) for b in mvs_blocks)),
            "session_minutes": week_cfg.get("floor_session_minutes", 25) + 5,
        },
    )
    ideal.sibling_routine_id = floor.routine_id
    result = [ideal, floor]
    if inputs.days_since_last_workout >= week_cfg.get("re_entry_days_threshold", 7):
        result.append(_make_re_entry(inputs, "full", targets, catalog, week_cfg, ideal.routine_id))
    return result
