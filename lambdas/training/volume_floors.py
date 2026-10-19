"""volume_floors.py — the coverage floors (#5053): which muscles the templates must reach, and the 14-day below-MEV flag.

Two jobs, both reading, neither counting:

  * TEMPLATE side — `floor_coverage(by_muscle, sessions_by_muscle)` compares the five roles' weekly set counts
    (`program_structure.weekly_sets_by_muscle`'s own tallies) with the landmark MEV for each charter floor muscle
    (`volume_priorities.mev_floors_in_every_template`: side/rear delts, traps, calves, core) and with the charter band
    (`volume_priorities.sets_per_wk`) for each priority group.
  * LOGGED side — `below_mev_14d(window)` flags every muscle whose trailing-14-day working sets, per week, sit below its
    MEV. The counts are `muscle_volume.working_sets_by_muscle`'s (through `get_muscle_volume`'s trailing window — the one
    per-muscle computation, #4071); this module only compares them with `config/training_landmarks.json`.

The incident it answers: from 2026-10-04 (the Flex day dropped) delts and core fell to 0 sets and calves sat at 6/wk with
no alert. Landmarks are keyed by catalog muscle (`shoulders`, `abs`); logged counts by the `MUSCLES` label (`Shoulders`,
`Core`) — `HEVY_MUSCLE_GROUP` is the one bridge. Granularity caveat: the logged taxonomy has no side/rear/trap split
(`Shoulders` is all delts, `Back` carries traps), so those floors are checked per `Shoulders` / by template slot.
"""

from __future__ import annotations

from typing import Any

ISSUE = "#5053"
WINDOW_DAYS = 14
FLAG_RULE = "a muscle whose trailing-14-day working sets per week sit below its landmark MEV (config/training_landmarks.json)"

# Charter `mev_floors_in_every_template` name -> the landmark key it is counted under
FLOOR_LANDMARK: dict[str, str] = {"side_rear_delts": "shoulders", "traps": "back", "calves": "calves", "core": "abs"}
# the trap floor has no landmark of its own (Hevy's taxonomy credits a shrug to Back): it is a SLOT check on these keys
TRAP_MOVEMENTS = ("shrug_dumbbell", "shrug_barbell")

# Charter `volume_priorities.sets_per_wk` group -> its members, each a tuple of template-count muscle keys that sum into
# ONE band member. The charter's legs and arms bands are per member (quads; hamstrings+glutes; biceps; triceps).
BAND_MEMBERS: dict[str, tuple[tuple[str, ...], ...]] = {
    "side_rear_delts": (("shoulders",),),
    "lats": (("back",),),
    "upper_chest": (("chest",),),
    "legs": (("quadriceps",), ("hamstrings", "glutes")),
    "arms": (("biceps",), ("triceps",)),
}


def _label_of(landmark_key: str) -> str | None:
    from training.muscle_volume import HEVY_MUSCLE_GROUP

    return next((label for label, key in HEVY_MUSCLE_GROUP.values() if label and key == landmark_key), None)


def _landmarks() -> dict[str, dict[str, Any]]:
    from training import block_model

    return block_model.load_landmarks() or {}


def below_mev_14d(window_14d: dict[str, Any] | None, landmarks: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Per muscle label: its trailing-14-day sets/wk against its MEV, and the flag. `window_14d` is `get_muscle_volume`'s
    `trailing_windows['14d']` ({"muscles": {label: {"total_sets": n}}, "days": 14}); None -> an honest `unavailable`."""
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
    flagged = sorted(m for m, r in rows.items() if r["below_mev"])
    return {
        "status": "ok",
        "window": {"start": window_14d.get("start"), "end": window_14d.get("end"), "days": WINDOW_DAYS},
        "flagged": flagged,
        "muscles": rows,
        "rule": FLAG_RULE,
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
        sets = int(by_muscle.get(key, 0)) if key else 0
        roles = [r for r, accs in accessories_by_role.items() if floor == "traps" and any(a in TRAP_MOVEMENTS for a in accs)]
        mev = int((lm.get(key) or {}).get("MEV") or 0) if floor != "traps" else None
        out[floor] = {
            "landmark_key": key,
            "sets": sets,
            "mev": mev,
            "meets_mev": (sets >= mev) if mev is not None else bool(roles),
            "slot_roles": roles,
        }
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
