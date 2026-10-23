"""cardio_cues.py — the cardio note pass over a RoutineSpec (#3700, #5048).

Split out of `training.routine_generator` (the module-size ceiling, #1665) with no contract change:
`routine_generator.attach_cardio_cues` is this function, re-exported, and every caller still imports it
from there. The note itself is `training.cardio_note.compose`'s; this module is the I/O around it —
the history and Whoop indexes, loaded when the caller does not supply them, each fail-soft.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("routine_generator")


def attach_cardio_cues(
    spec: Any,
    catalog: dict[str, Any] | None = None,
    cardio_index: dict[str, list] | None = None,
    whoop_index: dict[str, list] | None = None,
    aerobic_block: dict[str, Any] | None = None,
) -> int:
    """Write the prescription-first note onto every cardio block of a RoutineSpec (#3700, #5048).

    Returns how many blocks were written. The note is `training.cardio_note.compose`'s: line 1 the
    prescription in one fixed grammar (machine · minutes · level N shape · effort rule), line 2 the
    recovery answer, the dose's reason and at most one sentence of why. #5076: each block's KIND is the
    charter menu's weekly placement (`cardio_menu.choose_kind` over every cardio machine's history this
    week), or the kind the draft path placed (`rationale_tag` `cardio:<key>:menu:<kind>`); the treadmill
    dose is `cardio_menu.treadmill_dose`. The level is still derived from his history
    (`cardio_progression.cardio_facts` + `level_verdict`: the last ride's level, else his calibration
    note); the "Last: …" sentence and the calibration quote are no longer printed (#5048).

    A note that is not already a composed note (a chat author's prose) is REPLACED, and the replaced
    text is kept on `spec.inputs_snapshot["cardio_notes_replaced"]` so nothing is silently lost.
    Idempotent: a re-draft recomposes from the same inputs.

    `aerobic_block` is `constraint_block.recent_aerobic` (`mcp.shared_quantities.recent_aerobic_layer`)
    when the caller has it: the ramp state that allows a harder shape and the why line. None = unread,
    so the shape stays flat.

    WHY THIS EXISTS SEPARATELY from `_build_exercise_note`. `generate_routines`'s selector budgets by
    LANDMARK MUSCLE and never picks a bike; Matthew's real cycling blocks arrive through `draft_custom`
    and the #5000 gate path, which build blocks from arguments. This is the one call those paths need —
    it loads its own indexes and fails soft: a failed history load leaves every note untouched.
    """
    exercises = list(getattr(spec, "exercises", None) or [])
    if not exercises:
        return 0
    from training import cardio_note

    if catalog is None:
        try:
            from training.routine_generator import _load_json

            catalog = _load_json("movement_catalog.json")
        except Exception as e:  # pragma: no cover - config read
            logger.warning(f"cardio cue: catalog load failed ({e}); notes untouched")
            return 0
    movements = (catalog or {}).get("movements", {})
    targets = [ex for ex in exercises if cardio_note.machine_for(str(getattr(ex, "movement_key", "") or ""))]
    targets = [ex for ex in targets if sum(int(getattr(s, "duration_seconds", 0) or 0) for s in getattr(ex, "sets", None) or [])]
    if not targets:
        return 0
    if cardio_index is None:
        try:
            from training.exercise_history import DEFAULT_LOOKBACK_DAYS, FLOOR_LOOKBACK_DAYS, load_history_indexes

            cardio_index = load_history_indexes(lookback_days=max(DEFAULT_LOOKBACK_DAYS, FLOOR_LOOKBACK_DAYS))[1]
        except Exception as e:
            # the level cannot be derived, so the note is not rewritten: an authored note beats a level-less guess
            logger.warning(f"cardio cue: history load failed ({e}); notes untouched")
            return 0
    if whoop_index is None:
        try:
            from training.exercise_history import load_whoop_workout_index

            whoop_index = load_whoop_workout_index()
        except Exception as e:
            logger.warning(f"cardio cue: whoop load failed ({e}); cue renders without HR-at-level: {e}")
            whoop_index = {}

    from training import cardio_menu, recent_aerobic, standing_constraints
    from training.cardio_progression import cardio_facts, level_verdict

    target_date = str(getattr(spec, "target_date", "") or "")[:10]
    constraint = standing_constraints.active_constraint(target_date) if target_date else None
    archetype = getattr(spec, "archetype", "") or ""

    def _tid(key: str) -> str | None:
        return movements.get(key, {}).get("hevy_template_id_hint") or (key[5:] if key.startswith("tmpl:") else None)

    # #5076: the week's placement reads every cardio machine's history, not only this block's
    hist = cardio_menu.history_context(cardio_index, catalog, target_date)
    prior_kinds = hist["week_kinds"]
    loaded, _why = recent_aerobic.legs_loaded(aerobic_block)
    replaced: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    placed: list[str] = []
    stamped = 0
    for ex in targets:
        key = str(getattr(ex, "movement_key", "") or "")
        tid = _tid(key)
        sessions = (cardio_index or {}).get(tid or "") or []
        facts = cardio_facts(tid, cardio_index, whoop_index) if sessions else {}
        verdict = level_verdict(facts.get("series"), facts.get("last_level")) if sessions else None
        minutes = round(sum(int(getattr(s, "duration_seconds", 0) or 0) for s in ex.sets) / 60)
        tag = str(getattr(ex, "rationale_tag", "") or "").split(":")
        existing = (getattr(ex, "notes", "") or "").strip()
        authored = cardio_note.composed_kind(existing) or (cardio_menu.authored_kind(key, existing) if existing else None)
        if len(tag) >= 4 and tag[0] == "cardio" and tag[2] == "menu" and tag[3] in cardio_menu.KINDS:
            kind, why = tag[3], "placed by the draft"
        elif authored:
            kind, why = authored, "the author's note names it"
        else:
            pick = cardio_menu.choose_kind(
                target_date=target_date,
                archetype=archetype,
                week_kinds=prior_kinds + placed,
                prior_day_kind=hist["prior_day_kind"],
                legs_loaded=loaded,
                last_tempo_or_hills=hist["last_tempo_or_hills"],
                machines=(key,),
            )
            kind, why = pick["kind"], pick["why"]
        note, audit = cardio_note.compose(
            movement_key=key,
            minutes=minutes,
            target_date=target_date,
            archetype=archetype,
            kind=kind,
            facts=facts,
            verdict=verdict,
            treadmill_sessions=hist["by_machine"].get(cardio_menu.TREADMILL),
            aerobic_block=aerobic_block,
            constraint=constraint,
            hr_ceiling_bpm=None if constraint else recent_aerobic.HR_CEILING_BPM,
            placement_why=why,
        )
        placed.append(audit["kind"])
        if existing and not cardio_note.is_composed(existing) and existing != note:
            replaced.append({"movement_key": key, "notes": existing})
        ex.notes = note
        audits.append({"movement_key": key, **audit})
        stamped += 1
    plan = {
        "version": cardio_menu.CARDIO_MENU_VERSION,
        "charter_version": audits[0].get("charter_version") if audits else None,
        "kinds": placed,
        "week_kinds_before": prior_kinds,
        # the gym cardio minutes this routine adds to the day's steps/movement goal (#5076 -> #5056)
        "movement_minutes": cardio_menu.movement_minutes(exercises),
    }
    snap = getattr(spec, "inputs_snapshot", None)
    if isinstance(snap, dict) or snap is None:
        try:
            spec.inputs_snapshot = {
                **(snap or {}),
                "cardio_notes": audits,
                "cardio_plan": plan,
                **({"cardio_notes_replaced": replaced} if replaced else {}),
            }
        except AttributeError:  # pragma: no cover - a spec without the field
            pass
    return stamped
