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

# PLATFORM-CHOSEN: how far back a performed ride is matched to the routine he performed (the week's placement and
# last week's tempo-or-hills both sit inside it), and how much earlier than the ride that routine may be dated
# (a routine stamped for one day is often performed a day or two later: 10-20's Upper-heavy was done on 10-21).
SERVED_LOOKBACK_DAYS = 14
SERVED_ROUTINE_LEAD_DAYS = 7


def with_served_kinds(
    cardio_index: dict[str, list] | None, target_date: str, catalog: dict[str, Any] | None = None
) -> dict[str, list] | None:
    """`cardio_index` with each recent ride's `served_kind`: the kind the routine he performed prescribed (#5076),
    and its `served_level`: the level that routine's block printed (`cardio_menu.served_levels`, the same read), which
    `cardio_progression.cardio_facts` takes as the ride's level when his own note names none.

    He logs the menu's rides with an empty note, so the note alone read every performed tempo as easy and the week's
    conditioning never counted. This joins a ride's `hevy_routine_id` to the routine record
    (`routine_repo.list_by_date_range`) and reads its cardio block's kind (`cardio_menu.served_kinds`).
    No ride in the window carries a routine id -> no read at all. Fail-soft: a failed read returns the index unchanged
    (named in the log), so the placement falls back to his notes."""
    from datetime import timedelta

    from common.pacific_time import parse_day_key

    from training import cardio_menu

    day = parse_day_key(str(target_date or "")[:10])
    if day is None:
        return cardio_index
    floor = (day - timedelta(days=SERVED_LOOKBACK_DAYS)).isoformat()
    recent = [s for ss in (cardio_index or {}).values() for s in ss or [] if floor <= str(s.get("date") or "")[:10] < day.isoformat()]
    if not any(s.get("hevy_routine_id") for s in recent):
        return cardio_index
    try:
        from training.routine_repo import list_by_date_range

        if catalog is None:
            from training.routine_generator import _load_json

            catalog = _load_json("movement_catalog.json")
        first = parse_day_key(min(str(s["date"])[:10] for s in recent)) or day
        start = (first - timedelta(days=SERVED_ROUTINE_LEAD_DAYS)).isoformat()
        routines = list_by_date_range(start, day.isoformat())
        served = cardio_menu.served_kinds(routines)
        levels = cardio_menu.served_levels(routines)
    except Exception as e:  # noqa: BLE001 — the placement then reads his notes alone
        logger.warning(f"cardio cue: served-routine read failed ({type(e).__name__}: {e}); kinds and levels read from his notes")
        return cardio_index
    return cardio_menu.annotate_served(cardio_index, served, catalog, levels)


def previous_of(spec: Any, target_date: str) -> dict[str, Any] | None:
    """The previous PERFORMED lifting session for a draft (#5076, ruling 2026-10-25): the session the Hevy sequence last
    credited and its role (`inputs_snapshot["calendar"]["advanced_by"]`, `session_sequence.next_session`), so the cardio
    menu reads it without a second Hevy read. None when the draft carries no calendar (a chat draft): not read."""
    from training import cardio_menu

    snap = getattr(spec, "inputs_snapshot", None)
    cal = (snap or {}).get("calendar") if isinstance(snap, dict) else None
    return cardio_menu.previous_performed((cal or {}).get("advanced_by") if isinstance(cal, dict) else None, target_date)


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
        cardio_index = with_served_kinds(cardio_index, str(getattr(spec, "target_date", "") or "")[:10], catalog)
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
    previous = previous_of(spec, target_date)

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
        index = next(i for i, e in enumerate(exercises) if e is ex)
        tid = _tid(key)
        sessions = (cardio_index or {}).get(tid or "") or []
        facts = cardio_facts(tid, cardio_index, whoop_index) if sessions else {}
        verdict = level_verdict(facts.get("series"), facts.get("last_level"), facts.get("shaped")) if sessions else None
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
                previous=previous,
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
            previous=previous,
            # #5428: the watch step when a Hevy block follows (owner protocol 2026-10-27), and an author's route why
            followed=cardio_note.after_line_needed(exercises, index),
            route_why=cardio_note.route_why_of(existing),
        )
        placed.append(audit["kind"])
        if existing and not cardio_note.is_composed(existing) and existing != note:
            # #5312: old/new kind so the draft result can state what replaced what he authored
            replaced.append({"movement_key": key, "notes": existing, "old_kind": authored, "new_kind": audit["kind"]})
        ex.notes = note
        audits.append({"movement_key": key, **audit})
        stamped += 1
    # #5428: the After line follows the list's order as it stands now (a block placed after the cardio one adds it)
    cardio_note.apply_after_lines(exercises)
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
