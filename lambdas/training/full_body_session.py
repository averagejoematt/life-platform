"""full_body_session.py — the program's session for one role, as IR (#4064; v0.4 #4147).

The module name is v0.3's (full body, superseded 2026-09-24); it now builds whatever the ACTIVE
program's role is — since #5069 the five roles of the charter's split (upper_heavy / lower_heavy /
shoulders_arms / upper_volume / lower_volume), archetype `upper` / `lower`, the Upper / Lower Hevy folders.

`routine_generator.generate_routines` hands a day here when the schedule entry carries a
program role (`program_structure.SESSION_TEMPLATES`). Split out of `routine_generator` so
neither module crosses the 1000-line ceiling (#1665); it reuses the generator's helpers rather
than copying them, so the load floor, the notes and the ceilings are the SAME code on both paths.

`program_structure.session_prescription_for_role` is the session as data; this turns it
into IR. Everything the muscle-budget path guarantees still holds here — the load floor
(#3927) is the last thing to touch a WORKING or TOP set's load, re-based onto v0.3 §3's
entry ramp (`load_ramp`, #4090: the week's share of the discounted band anchor, never
100 % of the band best), the ceilings are asserted,
the notes quote the same history — with one addition §3 names explicitly: a heavy
exposure's back-offs sit at −10 % of the top set. That is the one sanctioned set below the
floor, and every one is written into the rationale, never applied silently.
"""

from __future__ import annotations

import functools
from typing import Any

from training import in_block_variant, load_ramp, program_structure, routine_generator as _rg, variant_rotation, warmup_sets
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
        # #5318/#5372: a carry set is distance-typed (his step count in the distance field; no rep range, no load — his
        # first-exposure pick); every other set is a rep range
        sets = [
            (
                Set(type="normal", distance_meters=int(sp["distance_meters"]))
                if sp.get("distance_meters")
                else Set(type="normal", rep_range_start=sp["reps"][0], rep_range_end=sp["reps"][1])
            )
            for sp in sets_spec
        ]
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
        # #5317: the cue is generated from the sets THIS block carries (the Minimum Viable Session cuts them to two)
        cue = program_structure.exposure_cue(e["intensity"], sets_spec)
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
        used.append({**e, "sets": sets_spec, "cue": cue})
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


def _back_offs_then_warmups(
    blocks: list[ExerciseBlock], used: list[dict[str, Any]], rationale: list[str], load_floors: dict[str, Any], movements: dict[str, Any]
) -> dict[str, Any]:
    """The last two passes over a block's sets, in this order: §3's back-offs, then #5049's warm-up
    climb — prepended after every load pass, so it climbs to the load the block finally carries."""
    load_floors["back_offs"] = _apply_back_offs(blocks, used, rationale, load_floors)
    return warmup_sets.attach_and_note(blocks, movements, rationale)


def _sequence_line(day_entry: dict[str, Any]) -> str:
    """The rationale line naming where the session came from: the sequence position (and what advanced it), or the weekday grid."""
    if day_entry.get("source") != "session_sequence":
        return f"weekday grid: {day_entry.get('label')}"
    adv = day_entry.get("advanced_by")
    return f"session sequence: {day_entry['position_label']}, block {day_entry['block']}" + (
        f"; advanced by {adv['date']} {adv.get('title') or ''} ({adv['was']})".rstrip() if adv else "; the first session of the program"
    )


def _fit_session_shape(
    blocks: list[ExerciseBlock], rx: dict[str, Any], caps: dict[str, Any], load_catalog: dict[str, Any], rationale: list[str]
) -> dict[str, Any]:
    """#5069 (owner ruling 5): ONE lifting-minute estimate (sets as written, warm-ups included, x set time + rest) and the
    charter's session shape — one cardio block and the stretching cut to their caps (`program_structure.enforce_session_shape`).
    The lifting minutes were fitted upstream (`session_prescription_for_role` trims accessories first); an overrun that
    survives is flagged, never cut from the anchors."""
    shape = program_structure.enforce_session_shape(blocks, load_catalog.get("movements") or {})
    rationale += [f"session shape: {a}" for a in shape["actions"]]
    t = rx.get("time_trim") or {}
    if t.get("dropped_accessories"):
        rationale.append(
            f"time: ~{t['estimate_before_min']} min > the {t['cap_minutes']}-min lifting cap — dropped "
            f"{', '.join(map(str, t['dropped_accessories']))} (accessories first) -> ~{t['estimate_after_min']} min"
        )
    if shape["lifting_minutes"] > caps["session_minutes"]:
        rationale.append(
            f"OVER the {caps['session_minutes']}-min lifting cap at ~{shape['lifting_minutes']} min — anchors are never cut for time; flagged"
        )
    return shape


def _session_loads(
    blocks: list[ExerciseBlock],
    load_catalog: dict[str, Any],
    history_index: dict[str, list],
    weight_index: dict[str, float],
    inputs: GeneratorInputs,
    week_cfg: dict[str, Any],
    rationale: list[str],
    ramp_week: int,
    ramp_p: dict[str, Any],
    deload: bool,
) -> dict[str, Any]:
    """The floor (#4107: the ONE v0.3 load path, `load_ramp.v03_floor`) and then the double
    progression (#5052) — held on a deload the owner applied, whose loads are held as written."""
    load_floors = _enforce_load_floors(
        blocks,
        load_catalog,
        history_index,
        weight_index,
        target_date=inputs.target_date,
        days_since_last_workout=inputs.days_since_last_workout,
        layoff_days=int(week_cfg.get("re_entry_days_threshold", LAYOFF_DAYS_DEFAULT)),
        rationale=rationale,
        floor_fn=functools.partial(load_ramp.v03_floor, week=ramp_week),
        hold_reason="a deload the owner applied holds every load" if deload else None,
    )
    load_floors["load_rule"] = {"rule": "v0.3 §3 entry ramp", "week": ramp_week, "params": ramp_p}
    return load_floors


def _prescription(
    inputs: GeneratorInputs, day_entry: dict[str, Any], catalog: dict[str, Any], block_workouts: Any, deload: bool, skill_ceiling: int
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """(in-block record, rotation, prescription) for the served role. #4409: within a block an ANCHOR slot keeps the variant
    he performed in it (`in_block_variant`); #5075: each ACCESSORY slot serves its rotation variant
    (`variant_rotation`, the ledger read here unless `inputs.rotation_rows` injects it) — anchors are fixed for the block."""
    movements = catalog.get("movements") or {}
    in_block = in_block_variant.performed_in_block(block_workouts, movements, inputs.target_date)
    rotation = variant_rotation.for_session(
        {**day_entry, "date": inputs.target_date}, movements, rows=inputs.rotation_rows, skill_ceiling=skill_ceiling
    )
    rx = program_structure.session_prescription_for_role(
        day_entry["session_role"],
        deload=deload,
        catalog_movements=movements,
        skill_ceiling=skill_ceiling,
        in_block=in_block,
        accessory_variants=rotation["variants"],
    )
    return in_block, rotation, rx


def full_body_routines(
    inputs: GeneratorInputs,
    day_entry: dict[str, Any],
    week_cfg: dict[str, Any],
    landmarks: dict[str, Any],
    catalog: dict[str, Any],
    resolved_week: Any,
    targets: list[str],
    block_workouts: list[dict[str, Any]] | None = None,
) -> list[RoutineSpec]:
    """The program session for `day_entry['session_role']` — ideal + Minimum Viable Session
    floor (+ re-entry after a layoff). Pure apart from the same config/history reads as the
    muscle-budget path."""
    role = day_entry["session_role"]
    archetype = program_structure.SESSION_TEMPLATES[role]["archetype"]
    deload = bool(day_entry.get("deload"))
    skill_ceiling = int(week_cfg.get("skill_ceiling", 2))
    in_block, rotation, rx = _prescription(inputs, day_entry, catalog, block_workouts, deload, skill_ceiling)
    # a kept title-only variant (ADR-069) loads from its wire template id; the snapshot keeps the catalog's own hash
    load_catalog = in_block_variant.with_performed_template_ids(catalog, rx, in_block)  # #4431: the one resolver
    autoreg = _autoreg_multiplier(inputs.recovery_tier, inputs.acwr_flag)
    rationale: list[str] = [
        f"week grid source={resolved_week.source} ({resolved_week.detail})",
        f"archetype={archetype}; program=v{program_structure.PROGRAM_VERSION}; session_role={role}; autoreg={autoreg:.2f} (recovery={inputs.recovery_tier}, acwr={inputs.acwr_flag})",
    ]
    rationale.append(_sequence_line(day_entry))
    rationale += rotation["rationale"]
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
    elif inputs.z2_minutes_7d is None:
        rationale.append(_rg.Z2_UNKNOWN_NOTE)

    notes_mode = week_cfg.get("exercise_notes_mode", "one_best_line")
    # through the module attribute, so ONE patch point (routine_generator._load_note_indexes)
    # stubs the history read for both paths
    note_indexes = _rg._load_note_indexes(week_cfg, notes_mode)
    blocks, used, unresolved = _blocks_from_prescription(rx, load_catalog, note_indexes, notes_mode, anchors_only=drop_accessories)
    for line in unresolved:
        rationale.append(f"UNRESOLVED — {line}")

    history_index, weight_index, _cardio, _whoop = note_indexes
    # #4090: v0.3 §3's entry ramp — the week's share of band e1RM (#4388; a novel-again anchor's set), never 100 %
    # of the band best. The week is the session sequence's (#4110 — completed sessions, not
    # calendar weeks); a day with no program week (before the block start) ramps as week 1.
    ramp_week = int(day_entry.get("week") or 1)
    ramp_p = load_ramp.params()
    rationale.append(
        f"loads: v0.3 §3 entry ramp, week {ramp_week} = {load_ramp.ramp_pct(ramp_week, ramp_p)}% of band e1RM — of the anchor set, "
        f"after the {ramp_p['discount_pct']}% detraining discount, on novel-again anchors >= {load_ramp.DETRAINING_ANCHOR_AGE_DAYS} d "
        "older than block 1 (#4388) "
        f"(cap {ramp_p['cap_pct']}% of band e1RM; no in-band history -> the nearest band he has lifted in); "
        "a load already moved at the set's rep floor at this band this cycle, no layoff, is held — never ramped under (#4408); "
        "back-offs −10 % of the top set"
    )
    load_floors = _session_loads(blocks, load_catalog, history_index, weight_index, inputs, week_cfg, rationale, ramp_week, ramp_p, deload)
    warmups = _back_offs_then_warmups(blocks, used, rationale, load_floors, load_catalog.get("movements") or {})

    caps = {
        "total_sets": week_cfg["session_set_ceiling"],
        "session_minutes": week_cfg["session_minutes_ceiling"],
        "weekly_volume_per_muscle": week_cfg["weekly_volume_cap_per_muscle"],
    }
    total_sets = sum(warmup_sets.working_set_count(b.sets) for b in blocks)
    assert total_sets <= caps["total_sets"], f"BUG: total_sets {total_sets} > cap {caps['total_sets']}"
    shape = _fit_session_shape(blocks, rx, caps, load_catalog, rationale)  # #5069: the charter's session shape
    est_minutes = shape["lifting_minutes"]

    budget_used: dict[str, int] = {}
    for b in blocks:
        muscle = catalog.get("movements", {}).get(b.movement_key, {}).get("primary_muscle") or "unknown"
        budget_used[muscle] = budget_used.get(muscle, 0) + warmup_sets.working_set_count(b.sets)
    rationale.append(f"{total_sets} sets over {len(blocks)} movements (~{est_minutes} min) + {warmups['warmup_sets']} warm-up set(s)")

    label = rx["role_label"]
    week_tag = f" — W{day_entry['week']}" if day_entry.get("week") else ""
    title = f"{label}{week_tag}" + (" DELOAD" if deload else "") + f" — {inputs.target_date}"  # e.g. "LOWER-HEAVY — W1 — 2026-09-25"
    if day_entry.get("optional"):
        title += " (optional)"
    calendar_snapshot = {
        k: day_entry.get(k)
        for k in ("source", "week", "block", "deload", "label", "session_role", "session_in_week", "sequence_index", "position_label")
    }
    calendar_snapshot["advanced_by"] = day_entry.get("advanced_by")
    ideal = RoutineSpec(
        routine_id=_new_routine_id(inputs.target_date, archetype, "ideal"),
        target_date=inputs.target_date,
        archetype=archetype,
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
        | {
            "load_floors": load_floors,
            "session_prescription": rx,
            "calendar": calendar_snapshot,
            "warmups": warmups,
            "session_shape": shape,
            "rotation": rotation,  # #5075: routine_repo.draft_versioned records its ledger_writes
        },
        rationale=rationale,
        caps=caps,
    )
    attach_cardio_cues(ideal, catalog=catalog, cardio_index=note_indexes[2], whoop_index=note_indexes[3])

    # The Minimum Viable Session (§3): anchors only, top set + one back-off, ~25 min.
    # Resolved at skill tier 1 — the floor has always been machine/DB-only for the version
    # of Matthew who shows up tired, so the bench anchor is the machine press here.
    # anchor_exempt=False: the #4080 exemption targets the interim Sports-Medicine ceiling
    # (2), not this deliberately lower tired-day floor — a barbell top set has no business
    # on the Minimum Viable Session regardless of which pattern family it belongs to.
    mvs_rx = program_structure.session_prescription_for_role(
        role, deload=False, catalog_movements=catalog.get("movements") or {}, skill_ceiling=1, anchor_exempt=False
    )
    mvs_blocks, _mvs_used, _ = _blocks_from_prescription(mvs_rx, catalog, None, "off", anchors_only=True, top_plus_one=True)
    floor_cap = int(week_cfg.get("floor_session_set_count", 6)) + 2
    floor = RoutineSpec(
        routine_id=_new_routine_id(inputs.target_date, archetype, "floor"),
        target_date=inputs.target_date,
        archetype=archetype,
        variant="floor",
        title=f"Floor — {inputs.target_date}",
        notes="Minimum Viable Session (§3): anchors only, top set + one back-off, ~25 min.",
        version=1,
        created_at=_now_iso(),
        created_by="cron",
        source_action="floor",
        status="draft",
        sibling_routine_id=ideal.routine_id,
        exercises=mvs_blocks,
        budget_used={b.movement_key: len(b.sets) for b in mvs_blocks},
        inputs_snapshot={"variant": "floor", "target_minutes": week_cfg.get("floor_session_minutes", 25), "session_role": role},
        rationale=["Minimum Viable Session — anchors only, top set + one back-off (§3)."],
        caps={
            "total_sets": max(floor_cap, sum(len(b.sets) for b in mvs_blocks)),
            "session_minutes": week_cfg.get("floor_session_minutes", 25) + 5,
        },
    )
    ideal.sibling_routine_id = floor.routine_id
    result = [ideal, floor]
    if inputs.days_since_last_workout >= week_cfg.get("re_entry_days_threshold", 7):
        result.append(_make_re_entry(inputs, archetype, targets, catalog, week_cfg, ideal.routine_id))
    return result
