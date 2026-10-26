"""volume_floors.py — the coverage floors (#5053): which muscles the templates must reach, and the 14-day below-MEV flag.

Two jobs, both reading, neither counting:

  * TEMPLATE side — `floor_coverage(by_muscle, accessories_by_role, landmarks=None)` compares the five roles' weekly set counts
    (`program_structure.weekly_sets_by_muscle`'s own tallies) with the landmark MEV for each charter floor muscle
    (`volume_priorities.mev_floors_in_every_template`: side/rear delts, traps, calves, core) and with the charter band
    (`volume_priorities.sets_per_wk`) for each priority group.
  * LOGGED side — `below_mev_14d(window)` flags every muscle whose trailing-14-day working sets, per week, sit below its
    MEV. The counts are `muscle_volume.working_sets_by_muscle`'s (through `get_muscle_volume`'s trailing window — the one
    per-muscle computation, #4071); this module only compares them with `config/training_landmarks.json`. #5164 adds the
    movement-counted floor beside the muscle rows: side/rear delts summed from the same count's per-exercise working sets
    (`exercise_sets`, resolved to catalog keys by `logged_movement_sets`) over `FLOOR_MOVEMENTS['side_rear_delts']` only,
    against the shoulders MEV — so continued pressing cannot keep a lateral/rear-delt lapse quiet.

The incident it answers: from 2026-10-04 (the Flex day dropped) delts and core fell to 0 sets and calves sat at 6/wk with
no alert. Landmarks are keyed by catalog muscle (`shoulders`, `abs`); logged counts by the `MUSCLES` label (`Shoulders`,
`Core`) — `HEVY_MUSCLE_GROUP` is the one bridge. Granularity caveat: the logged taxonomy has no side/rear/trap split
(`Shoulders` is all delts, presses included; `Back` carries traps), so the `Shoulders` muscle row cannot see a drop that
pressing masks — the live 2026-10-05..18 read was 16 Shoulders sets (8.0/wk, at MEV) with 0 lateral/rear-delt sets. The
`movement_floors['side_rear_delts']` row (#5164) is the one that sees it (the template shortfall was closed by #5162's
trade inside the 75-set week, owner ruling 2026-10-23). The TEMPLATE side counts the movement-specific floors and bands by movement
(`FLOOR_MOVEMENTS`, `BAND_MOVEMENTS`), never by catalog muscle — a shoulder press is not side/rear-delt work, a flat bench
press is not upper-chest work, a row or a shrug is not a vertical pull (ADR-104, honest numbers). Since #5318 (owner ruling
B3) the farmer's carry is the trap slot and counts toward the core and forearms too (`CARRY_MOVEMENTS`, `CARRY_CREDITS`), and
the upper-chest band counts upper_volume's incline dumbbell press (ruling B2).
"""

from __future__ import annotations

from typing import Any

ISSUE = "#5053"
WINDOW_DAYS = 14
FLAG_RULE = "a muscle whose trailing-14-day working sets per week sit below its landmark MEV (config/training_landmarks.json)"
MOVEMENT_FLAG_RULE = (
    "side/rear delts: the trailing-14-day working sets per week of FLOOR_MOVEMENTS['side_rear_delts'] only (presses excluded), "
    "below the shoulders landmark MEV (#5164)"
)

# Charter `mev_floors_in_every_template` name -> the landmark key it is counted under
FLOOR_LANDMARK: dict[str, str] = {"side_rear_delts": "shoulders", "traps": "back", "calves": "calves", "core": "abs"}
# The movements that COUNT toward each charter floor (template side). A catalog 'shoulders' set is not side/rear-delt work:
# presses are excluded. The trap floor has no landmark of its own (Hevy credits a shrug to Back): a slot check as well.
FLOOR_MOVEMENTS: dict[str, tuple[str, ...]] = {
    "side_rear_delts": (
        "db_lateral_raise",
        "lateral_raise_machine",
        "face_pull",
        "reverse_pec_deck",
        "rear_delt_reverse_fly_cable",
        "chest_supported_reverse_fly_dumbbell",
        "db_rear_delt_rows",
        "band_pullaparts",
    ),
    # #5318 (owner ruling B3, 2026-10-24): the farmer's carry replaced the shrug on shoulders+arms — "it covers traps (the
    # shrug's job), adds grip and core" — so it counts toward the trap floor AND the core floor (and the forearms, below)
    "traps": ("shrug_dumbbell", "shrug_barbell", "seated_shrugs", "farmers_walk"),
    "calves": ("calf_raise_machine",),
    "core": ("machine_crunch", "cable_pallof_press", "pallof_press", "farmers_walk"),
}
TRAP_MOVEMENTS = FLOOR_MOVEMENTS["traps"]
# #5318/#5372: the loaded carries. Hevy files the 'Farmers Walk' template under `other`, so its catalog muscle credits nothing; its
# sets are credited to the core (`abs`, the core floor's landmark key) and the forearms (grip) by movement, beside it.
CARRY_MOVEMENTS: tuple[str, ...] = ("farmers_walk",)
CARRY_CREDITS: tuple[str, ...] = ("abs", "forearms")
# The movements that COUNT toward the two movement-specific charter bands that are not floors.
#   upper_chest — incline presses and incline flyes only. A flat bench press or a flat/neutral fly is catalog 'chest' but
#     not upper-chest work; the charter's `rotation.pool.second_press` names the incline barbell press as the upper-chest slot.
#   lats — vertical pulls (pulldowns, pull-ups, chin-ups) plus the straight-arm lat isolations (straight-arm pulldown,
#     pullover). ROWS ARE EXCLUDED: the charter files rows and vertical pulls as separate slots (`rotation.pool.rows` vs
#     `rotation.pool.vertical_pull`) and no charter line or owner ruling credits a row to the lats band; a row's load is
#     shared with the mid-back/rear delts, so counting it here would overstate the band. Shrugs never count (traps).
BAND_MOVEMENTS: dict[str, tuple[str, ...]] = {
    "upper_chest": (
        "incline_bench_press_barbell",
        "incline_db_press",
        "incline_db_squeeze_press",
        "incline_chest_fly_dumbbell",
    ),
    "lats": (
        "lat_pulldown",
        "lat_pulldown_machine",
        "lat_pulldown_close_grip_cable",
        "lat_pulldown_wide_grip_cable",
        "front_lat_pulldown",
        "reverse_grip_lat_pulldown_cable",
        "underhand_lat_pulldowns",
        "prone_grip_dual_handle_pulldowns",
        "dual_handle_underhand_pulldowns",
        "rocking_pulldown",
        "pull_up",
        "pull_up_assisted",
        "pull_up_weighted",
        "chin_up_assisted",
        "chin_up_weighted",
        "straight_arm_pulldown",
        "straight_arm_lat_pulldown_cable",
        "kneeling_straight_arm_pulldown",
        "pullover_dumbbell",
        "db_lat_pullovers",
    ),
}
# the count key a floor's weekly sets are read under (movement-counted floors get a derived key; the rest are catalog muscles)
COUNT_KEY = {"side_rear_delts": "side_rear_delts_direct", "traps": "traps_direct"}
# every derived (movement-counted) key -> the movements summed into it
MOVEMENT_COUNTED: dict[str, tuple[str, ...]] = {
    **{key: FLOOR_MOVEMENTS[floor] for floor, key in COUNT_KEY.items()},
    "upper_chest_direct": BAND_MOVEMENTS["upper_chest"],
    "lats_direct": BAND_MOVEMENTS["lats"],
}

# Charter `volume_priorities.sets_per_wk` group -> its members, each a tuple of template-count muscle keys that sum into
# ONE band member. The charter's legs and arms bands are per member (quads; hamstrings+glutes; biceps; triceps).
BAND_MEMBERS: dict[str, tuple[tuple[str, ...], ...]] = {
    "side_rear_delts": (("side_rear_delts_direct",),),
    "lats": (("lats_direct",),),
    "upper_chest": (("upper_chest_direct",),),
    "legs": (("quadriceps",), ("hamstrings", "glutes")),
    "arms": (("biceps",), ("triceps",)),
}


def _label_of(landmark_key: str) -> str | None:
    from training.muscle_volume import HEVY_MUSCLE_GROUP

    return next((label for label, key in HEVY_MUSCLE_GROUP.values() if label and key == landmark_key), None)


def _landmarks() -> dict[str, dict[str, Any]]:
    from training import block_model

    return block_model.load_landmarks() or {}


def _catalog_movements() -> dict[str, Any]:
    try:
        from health.adherence_calc import _load_catalog

        return (_load_catalog() or {}).get("movements", {}) or {}
    except Exception:  # noqa: BLE001 — an unreadable catalog resolves nothing; the floor then reports `unavailable`
        return {}


def logged_movement_sets(exercise_sets: list[dict[str, Any]] | None, catalog: dict[str, Any] | None = None) -> dict[str, int] | None:
    """`working_sets_by_muscle`'s `exercise_sets` -> {catalog movement key: working sets}, for the movement-counted keys
    only (`MOVEMENT_COUNTED`). A logged exercise resolves by its Hevy template id against the entry's
    `hevy_template_id_hint`, else by its exact title (case-insensitive — the hint-less entries such as `reverse_pec_deck`
    resolve by title on the write side too, ADR-069). Unresolved exercises count toward no floor: a press is never
    side/rear-delt work. None when the window carried no per-exercise counts or the catalog is unreadable."""
    if exercise_sets is None:
        return None
    movements = catalog if catalog is not None else _catalog_movements()
    if not movements:
        return None
    wanted = {m for keys in MOVEMENT_COUNTED.values() for m in keys}
    by_id: dict[str, str] = {}
    by_title: dict[str, str] = {}
    for key in sorted(wanted):
        entry = movements.get(key) or {}
        if entry.get("hevy_template_id_hint"):
            by_id.setdefault(str(entry["hevy_template_id_hint"]).upper(), key)
        if entry.get("title"):
            by_title.setdefault(str(entry["title"]).strip().lower(), key)
    out: dict[str, int] = {}
    for row in exercise_sets:
        key = by_id.get(str(row.get("template_id") or "").upper()) or by_title.get(str(row.get("name") or "").strip().lower())
        if key:
            out[key] = out.get(key, 0) + int(row.get("working_sets") or 0)
    return dict(sorted(out.items()))


def _movement_floor_14d(window_14d: dict[str, Any], lm: dict[str, dict[str, Any]], weeks: float) -> dict[str, Any]:
    """#5164: the side/rear-delt floor, counted by movement over the 14-day window, against the shoulders MEV."""
    floor = "side_rear_delts"
    key = FLOOR_LANDMARK[floor]
    by_movement = window_14d.get("movement_sets")
    mev = int((lm.get(key) or {}).get("MEV") or 0)
    if not isinstance(by_movement, dict) or not mev:
        reason = "no per-movement counts in the 14-day window" if not isinstance(by_movement, dict) else f"no {key} MEV"
        return {"status": "unavailable", "reason": reason, "landmark_key": key, "counted_by": "movement"}
    counted = {m: int(by_movement.get(m) or 0) for m in FLOOR_MOVEMENTS[floor] if by_movement.get(m)}
    per_wk = round(sum(counted.values()) / weeks, 1)
    return {
        "status": "ok",
        "sets_per_wk": per_wk,
        "mev": mev,
        "below_mev": per_wk < mev,
        "landmark_key": key,
        "counted_by": "movement",
        "movements": counted,
        "counts": "volume_floors.FLOOR_MOVEMENTS['side_rear_delts'] — lateral raises, face pulls, rear-delt flyes; presses excluded",
    }


def below_mev_14d(window_14d: dict[str, Any] | None, landmarks: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Per muscle label: its trailing-14-day sets/wk against its MEV, and the flag. `window_14d` is `get_muscle_volume`'s
    `trailing_windows['14d']` ({"muscles": {label: {"total_sets": n}}, "movement_sets": {key: n}, "days": 14}); None ->
    an honest `unavailable`. #5164: `movement_floors['side_rear_delts']` is the movement-counted floor; when it is below
    MEV `side_rear_delts` joins `flagged` beside the muscle labels."""
    if not window_14d or not isinstance(window_14d.get("muscles"), dict):
        return {"status": "unavailable", "reason": "no trailing 14-day window in the muscle-volume read", "rule": FLAG_RULE}
    lm = landmarks if landmarks is not None else _landmarks()
    if not lm:
        return {"status": "unavailable", "reason": "training_landmarks.json unreadable", "rule": FLAG_RULE}
    weeks = float(window_14d.get("weeks") or WINDOW_DAYS / 7)
    rows: dict[str, Any] = {}
    for key, row in sorted(lm.items()):
        label = _label_of(key)
        if not label or not row.get("MEV"):
            continue
        sets = float((window_14d["muscles"].get(label) or {}).get("total_sets") or 0.0)
        per_wk = round(sets / weeks, 1)
        rows[label] = {"sets_per_wk": per_wk, "mev": int(row["MEV"]), "below_mev": per_wk < int(row["MEV"]), "landmark_key": key}
    movement_floors = {"side_rear_delts": _movement_floor_14d(window_14d, lm, weeks)}
    flagged = sorted(m for m, r in rows.items() if r["below_mev"]) + sorted(f for f, r in movement_floors.items() if r.get("below_mev"))
    return {
        "status": "ok",
        "window": {"start": window_14d.get("start"), "end": window_14d.get("end"), "days": WINDOW_DAYS},
        "flagged": flagged,
        "muscles": rows,
        "movement_floors": movement_floors,
        "rule": FLAG_RULE,
        "movement_rule": MOVEMENT_FLAG_RULE,
    }


def floor_coverage(
    by_muscle: dict[str, int], accessories_by_role: dict[str, list[str]], landmarks: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The charter floors against the templates' weekly sets: each floor muscle's sets, its MEV and whether a role carries it."""
    from training.training_charter import charter_value

    lm = landmarks if landmarks is not None else _landmarks()
    out: dict[str, Any] = {}
    for floor in charter_value("volume_priorities.mev_floors_in_every_template") or []:
        key = FLOOR_LANDMARK.get(floor)
        sets = int(by_muscle.get(COUNT_KEY.get(floor, key or ""), 0))
        roles = [r for r, accs in accessories_by_role.items() if any(a in FLOOR_MOVEMENTS.get(floor, ()) for a in accs)]
        mev = int((lm.get(key) or {}).get("MEV") or 0) if floor != "traps" else None
        out[floor] = {
            "landmark_key": key,
            "sets": sets,
            "mev": mev,
            "meets_mev": (sets >= mev) if mev is not None else bool(roles),
            "slot_roles": roles,
        }
    return out


def movement_counts(by_muscle: dict[str, int], by_movement: dict[str, int]) -> dict[str, int]:
    """`by_muscle` plus the movement-counted keys (`MOVEMENT_COUNTED`: side/rear delts, traps, upper chest, lats) tallied
    from the roles' own per-movement sets — the same exposures, summed by movement instead of by catalog muscle — and the
    carries' sets credited to `CARRY_CREDITS` (core and forearms, #5318)."""
    out = dict(by_muscle)
    for key, movements in MOVEMENT_COUNTED.items():
        out[key] = sum(int(by_movement.get(m, 0)) for m in movements)
    carried = sum(int(by_movement.get(m, 0)) for m in CARRY_MOVEMENTS)
    for key in CARRY_CREDITS:
        out[key] = int(out.get(key, 0)) + carried
    return out


def charter_band_rows(by_muscle: dict[str, int]) -> dict[str, Any]:
    """Each charter `sets_per_wk` group: its members' weekly sets, the charter band and the gap below the band's floor
    (the worst member's shortfall; 0 when every member is at or above it)."""
    from training.training_charter import charter_value

    bands = charter_value("volume_priorities.sets_per_wk") or {}
    out: dict[str, Any] = {}
    for group, band in bands.items():
        members = BAND_MEMBERS.get(group, ())
        sets = [sum(int(by_muscle.get(m, 0)) for m in member) for member in members]
        out[group] = {"member_sets": sets, "band": list(band), "gap_to_floor": max([0] + [int(band[0]) - n for n in sets if n < band[0]])}
    return out
