"""block_model.py — the block mesocycle model: volume ramps inside a block, the next block is modelled, no deload week (#5077).

WHY THIS EXISTS

Before #5077 the engine knew one block: `load_ramp` modelled a single hard-coded 6-week entry ramp
(60 % -> +5 %/wk -> 85 % of band e1RM) and the program ended it in a scheduled deload. The owner
ruled on 2026-10-18 that there is NO scheduled or automatic deload (charter `deload.scheduled:
false`, `deload.automatic: false`) and asked for a program that ramps volume within a block and
then models the next one. This module is that model, as data. Pure: the landmarks, the program
week and the owner's deload records are handed in; `for_session` is the one wrapper that reads
the landmark config.

THE RULE, AS ARITHMETIC (every number from the charter or the landmarks, never a literal)

    block_weeks       = charter `rotation.anchors_fixed_weeks`           (a block is the anchors' fixed span)
    block, week_in    = (program_week - 1) // block_weeks + 1, (program_week - 1) % block_weeks + 1
    band(muscle)      = the charter `volume_priorities.sets_per_wk` band of the muscle's group,
                        clamped into the landmark band [MEV, MRV] (`config/training_landmarks.json`);
                        a muscle no charter group names holds at its MEV
    start(block 1)    = max(band low, MEV)                                (the MEV side)
    start(block n)    = min(start(1) + (n - 1) x SETS_PER_STEP, cap - steps_per_block x SETS_PER_STEP)
    sets(week)        = start(block) + ((week_in - 1) // RAMP_EVERY_WEEKS) x SETS_PER_STEP   (priority muscles)
                      = start(block)                                                          (maintenance muscles)
    cap               = min(band high, MRV)                               (the MAV side; never past MRV)

  * PRIORITY vs MAINTENANCE comes from the charter: a group whose `<group>_posture` reads
    "maintenance" (`legs_posture: "strong maintenance"`) holds; every other charter group is the
    aesthetic priority set and ramps.
  * the added set goes on an ACCESSORY first (`add_to`), so the anchors' set counts stay fixed for
    the block (#5075 owns which accessory fills a slot; this model only says how many sets).
  * LOADS are not modelled here: #5052's double progression owns them. The next block's anchors are
    re-anchored to the block's best (`next_block_preview.anchors`), the accessory slots rotate per
    #5075 on the charter's `rotation.accessory_slots_rotate_every_weeks`.
  * `load_ramp`'s entry ramp is a RE-ENTRY ramp (a layoff > 90 d or a novel-again lift, `layoff_tiers`),
    not a block: it is never consulted here and never ends in a deload.

NO DELOAD WEEK. A deload exists only as #5070's recommendation (`deload_word.recommendation`) and the
owner's DELOAD# record. When a record's window overlaps a week, that week yields its targets cut by
the record's own `sets_pct` (−40 % proposed, `owner_redlines` `lifting_sessions_per_wk.deload`) and the
next week resumes the ramp at its own position; with no record, `deload.applied` is False whatever the
signals say.

RAMP_EVERY_WEEKS / SETS_PER_STEP: "+1 set per priority muscle every 2 weeks, accessories first" — the
charter-build plan's volume progression (2026-10-18, epic #5050), platform-proposed, in the population
range for a hypertrophy mesocycle that adds volume from MEV toward MAV (Israetel, Hoffmann & Smith 2017,
*Scientific Principles of Hypertrophy Training*, the volume-landmark model; Schoenfeld et al. 2017,
J Sports Sci 35(11):1073, the weekly-set dose response). ADR-105: population-derived, not fitted to him.
"""

from __future__ import annotations

import logging
from typing import Any

from common.pacific_time import parse_day_key, shift_day_key

logger = logging.getLogger(__name__)

ISSUE = "#5077"
RAMP_EVERY_WEEKS = 2
SETS_PER_STEP = 1
RAMP_PROVENANCE = "platform-proposed (the charter-build plan, epic #5050, 2026-10-18); population-derived (ADR-105 rule 4)"
LANDMARKS_FILE = "training_landmarks.json"

# Charter `volume_priorities.sets_per_wk` group -> the landmark muscles it governs. A charter group with no row
# here is reported on `unmapped_groups` (never silently dropped) — tests hold every charter group mapped.
GROUP_MUSCLES: dict[str, tuple[str, ...]] = {
    "side_rear_delts": ("shoulders",),
    "lats": ("back",),
    "upper_chest": ("chest",),
    "legs": ("quadriceps", "hamstrings", "glutes"),
    "arms": ("biceps", "triceps"),
}

_landmarks_cache: dict[str, Any] | None = None


def block_weeks() -> int:
    """A block's length in program weeks: the charter's `rotation.anchors_fixed_weeks`. Raises when the charter cannot say."""
    from training.training_charter import charter_value

    n = charter_value("rotation.anchors_fixed_weeks")
    if not isinstance(n, int) or n < 1:
        raise ValueError(f"block_model: charter rotation.anchors_fixed_weeks is {n!r} — a block needs a whole number of weeks")
    return n


def load_landmarks() -> dict[str, dict[str, Any]] | None:
    """`config/training_landmarks.json` muscles (the generator's own read: local config, else S3), cached; None when unreadable."""
    global _landmarks_cache
    if _landmarks_cache is None:
        try:
            from training.routine_generator import _load_json

            _landmarks_cache = dict(_load_json(LANDMARKS_FILE).get("muscles") or {})
        except Exception as e:  # noqa: BLE001 — the model then says the landmarks were unreadable, never a guessed band
            logger.warning(f"block_model: {LANDMARKS_FILE} unreadable ({type(e).__name__}: {e})")
            return None
    return _landmarks_cache


def _priorities() -> dict[str, Any]:
    from training.training_charter import charter_value

    vp = charter_value("volume_priorities", {}) or {}
    bands = {g: list(b) for g, b in (vp.get("sets_per_wk") or {}).items()}
    held = {k[: -len("_posture")] for k, v in vp.items() if k.endswith("_posture") and "maintenance" in str(v).lower()}
    return {"bands": bands, "maintenance_groups": sorted(held & set(bands))}


def muscle_plan(landmarks: dict[str, dict[str, Any]], priorities: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Per landmark muscle: its band (charter clamped into [MEV, MRV]), its block-1 start, its cap and whether it ramps."""
    pr = priorities if priorities is not None else _priorities()
    group_of = {m: g for g, ms in GROUP_MUSCLES.items() for m in ms if g in pr["bands"]}
    out: dict[str, dict[str, Any]] = {}
    for muscle, lm in sorted(landmarks.items()):
        mev, mav, mrv = int(lm["MEV"]), int(lm["MAV"]), int(lm["MRV"])
        group = group_of.get(muscle)
        lo, hi = pr["bands"][group] if group else [mev, mev]
        start = min(max(int(lo), mev), mav)
        cap = max(start, min(int(hi), mrv))
        ramps = bool(group) and group not in pr["maintenance_groups"] and cap > start
        out[muscle] = {
            "group": group,
            "priority": ramps,
            "band": [start, cap],
            "landmarks": {"MEV": mev, "MAV": mav, "MRV": mrv},
            "start": start,
            "cap": cap,
        }
    return out


def _block_start(row: dict[str, Any], block: int, steps_per_block: int) -> int:
    if not row["priority"]:
        return row["start"]
    return max(row["start"], min(row["start"] + (block - 1) * SETS_PER_STEP, row["cap"] - steps_per_block * SETS_PER_STEP))


def _sets(row: dict[str, Any], block: int, week_in: int, steps_per_block: int) -> tuple[int, int]:
    """(target sets, sets added in this block so far) for one muscle in one week — never above its cap."""
    base = _block_start(row, block, steps_per_block)
    added = ((week_in - 1) // RAMP_EVERY_WEEKS) * SETS_PER_STEP if row["priority"] else 0
    sets = min(base + added, row["cap"])
    return sets, sets - base


def ramp_stage(week_in: int, n_weeks: int) -> str:
    """'MEV-side' on the block's first step, 'MAV-side' on its last, 'mid-band' between."""
    step, last = (week_in - 1) // RAMP_EVERY_WEEKS, (n_weeks - 1) // RAMP_EVERY_WEEKS
    return "MEV-side" if step == 0 else ("MAV-side" if step >= last else "mid-band")


def _overlapping_record(records: list[dict[str, Any]] | None, week_start: str | None, days: int = 7) -> dict[str, Any] | None:
    """The owner's DELOAD# record whose window overlaps the 7 days from `week_start`, else None."""
    from training import deload_word

    if not week_start or parse_day_key(str(week_start)[:10]) is None:
        return None
    for i in range(days):
        rec = deload_word.active_record(records, shift_day_key(str(week_start)[:10], i))
        if rec is not None:
            return rec
    return None


def _next_block_preview(plan: dict[str, dict[str, Any]], block: int, n_weeks: int, anchor_bests: dict[str, Any] | None) -> dict[str, Any]:
    from training.training_charter import charter_value

    steps = (n_weeks - 1) // RAMP_EVERY_WEEKS
    rotate = charter_value("rotation.accessory_slots_rotate_every_weeks")
    return {
        "block": block + 1,
        "starts_program_week": block * n_weeks + 1,
        "sets_by_muscle_start": {m: _block_start(r, block + 1, steps) for m, r in plan.items()},
        "anchors": {
            "rule": f"re-anchored to block {block}'s best (the top working set per anchor across the block); loads progress by #5052's double progression",
            "bests": anchor_bests,
        },
        "accessory_rotation": {
            "every_weeks": rotate,
            "rotates_at_week_in_block": list(range(1, n_weeks + 1, int(rotate))) if isinstance(rotate, int) and rotate > 0 else None,
            "slots_from": "#5075 (the vetted pool; which accessory fills a slot is not modelled here)",
        },
    }


def week_plan(
    program_week: int,
    *,
    landmarks: dict[str, dict[str, Any]],
    week_start: str | None = None,
    deload_records: list[dict[str, Any]] | None = None,
    recommended: bool | None = None,
    anchor_bests: dict[str, Any] | None = None,
    priorities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One program week of the block model. Pure: `landmarks` and the owner's `deload_records` are handed in.

    `week_start` is the day the week opened (the ledger's `week_basis.week_opened_on`): a DELOAD# record overlapping
    [week_start, +7 d) applies its own cut to this week. `recommended` is #5070's `deload_recommendation.active` —
    reported, never acted on."""
    from training.training_charter import charter_version

    if int(program_week) < 1:
        raise ValueError(f"block_model: program week {program_week!r} — the model starts at week 1")
    n = block_weeks()
    block, week_in = (int(program_week) - 1) // n + 1, (int(program_week) - 1) % n + 1
    steps = (n - 1) // RAMP_EVERY_WEEKS
    plan = muscle_plan(landmarks, priorities)
    rec = _overlapping_record(deload_records, week_start)
    pct = int(rec.get("sets_pct") or 0) if rec else 0
    targets: dict[str, dict[str, Any]] = {}
    for m, row in plan.items():
        sets, added = _sets(row, block, week_in, steps)
        targets[m] = {
            "sets": int(round(sets * (100 + pct) / 100.0)) if rec else sets,
            "ramp_sets": sets,
            "added_this_block": added,
            "band": row["band"],
            "landmarks": row["landmarks"],
            "priority": row["priority"],
            "add_to": "accessories first" if row["priority"] else None,
        }
    pr = priorities if priorities is not None else _priorities()
    return {
        "block": block,
        "week_in_block": week_in,
        "program_week": int(program_week),
        "block_weeks": n,
        "sets_by_muscle_target": targets,
        "ramp_stage": ramp_stage(week_in, n),
        "deload": {
            "recommended": recommended,
            "applied": rec is not None,
            "sets_pct": pct if rec else None,
            "record_start": rec.get("start_date") if rec else None,
            "rule": "no scheduled or automatic deload: signals recommend (#5070), only the owner's DELOAD# record applies a cut, then the ramp resumes",
        },
        "next_block_preview": _next_block_preview(plan, block, n, anchor_bests),
        "unmapped_groups": sorted(set(pr["bands"]) - set(GROUP_MUSCLES)),
        "ramp_rule": {
            "every_weeks": RAMP_EVERY_WEEKS,
            "sets_per_step": SETS_PER_STEP,
            "provenance": RAMP_PROVENANCE,
            "loads": "#5052 double progression (not modelled here); load_ramp is the re-entry ramp for a layoff or novel-again lift only",
        },
        "charter_version": charter_version(),
        "issue": ISSUE,
    }


def project(
    n_weeks: int,
    *,
    landmarks: dict[str, dict[str, Any]],
    start_week: int = 1,
    first_week_start: str | None = None,
    deload_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """`n_weeks` consecutive weeks from `start_week` (weeks 7 d apart from `first_week_start`) — the multi-block view."""
    return [
        week_plan(
            start_week + i,
            landmarks=landmarks,
            week_start=shift_day_key(first_week_start, 7 * i) if first_week_start else None,
            deload_records=deload_records,
        )
        for i in range(max(0, int(n_weeks)))
    ]


def for_session(session: dict[str, Any], deload_records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The served session's week of the model (`plan_engine._scheduled_session`). Never raises: an unknown week or an
    unreadable landmark file is a stated state, not a guessed target."""
    week = session.get("week")
    if not isinstance(week, int) or week < 1:
        return {"state": "week_unknown", "issue": ISSUE, "note": "the program week is not known, so no block position is modelled"}
    landmarks = load_landmarks()
    if not landmarks:
        return {"state": "landmarks_unreadable", "issue": ISSUE, "note": f"config/{LANDMARKS_FILE} could not be read — no set targets"}
    try:
        out = week_plan(
            week,
            landmarks=landmarks,
            week_start=(session.get("week_basis") or {}).get("week_opened_on"),
            deload_records=deload_records,
            recommended=(session.get("deload_recommendation") or {}).get("active"),
        )
    except ValueError as e:
        return {"state": "charter_unreadable", "issue": ISSUE, "note": str(e)}
    return {"state": "modelled", **out}


def with_recommendation(view: dict[str, Any] | None, deload_rec: dict[str, Any] | None) -> dict[str, Any] | None:
    """Stamp the constraint block's full #5070 recommendation (signals filled) onto a `for_session` view, in place."""
    if isinstance(view, dict) and isinstance(view.get("deload"), dict):
        view["deload"]["recommended"] = bool((deload_rec or {}).get("active"))
    return view
