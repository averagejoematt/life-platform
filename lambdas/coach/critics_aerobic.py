"""critics_aerobic.py — the joints_tendons critic reads what his legs did in the last 48 h (#4387).

On 2026-09-27 the red team approved 60 min of incline treadmill after a trap-bar + squat lower
session, the morning after a 4.4 h walking weekend (walks of 102 and 165 min at ~116 bpm, both
over the owner's then ≤ 75 min / ≤ 105 bpm walking redlines). No critic held the walks: the joints
packet carried pain flags, novelty and the fatigue trigger, and nothing about weight-bearing load.

THE RULE (computed here, never by the model — the #4149 determinism ruling)
  trigger   weight-bearing hours (walks + treadmill) in the last 48 h >= 3.0, OR any walk in the
            last 48 h flagged `over_75_min` (`training.recent_aerobic`);
            (#4412: the numbers also carry the last Hevy cardio block's own joined HR,
            `last_cardio_block_avg_hr` — None/unknown when no wearable covered its minutes);
  AND       the draft is a LOWER session carrying a weight-bearing cardio block (treadmill/walk);
  THEN      `change`: that block becomes cycling (recumbent), the same duration, HR average under the
            redline cap (120 since OD2, #4503) with its 105 target named.
  The 75-min line and the HR cap/target are the owner's (`owner_redlines.walking_floor_hr_wk`). The
  3.0 h trigger is POPULATION-DERIVED and the flag says so at the point of use (ADR-105).

The flag is `governed` (the model cannot re-escalate it into a different change) and
`independent`: it rides as an ADDITIONAL change beside whatever change the packet's first flag
carries (`critics.deterministic_verdict`), so a novel-again set cap on the trap bar and this swap
both land — neither displaces the other.
"""

from __future__ import annotations

from typing import Any

from training import recent_aerobic

SWAP_TO = "cycling"
METRIC = "weight_bearing_hr_48h"


def _weight_bearing_cardio(ex: dict[str, Any]) -> bool:
    """A timed, unloaded treadmill/walk block. `Walking Lunge` carries a load or reps, never only a duration."""
    if not ex.get("duration_seconds") or ex.get("top_weight_lbs") is not None:
        return False
    for name in (ex.get("label"), ex.get("movement_key")):
        if recent_aerobic._hevy_modality(str(name or "").replace("_", " ")) in recent_aerobic.WEIGHT_BEARING:
            return True
    return False


def aerobic_flags(
    draft: dict[str, Any], block: dict[str, Any] | None, numbers: dict[str, Any], flags: list[dict[str, Any]], unknown: list[str]
) -> None:
    """Append the recent-aerobic numbers and, when the rule fires, one swap flag per weight-bearing block."""
    from coach.critics import _flag

    loaded, why = recent_aerobic.legs_loaded(block)
    totals = (block or {}).get("totals") or {}
    numbers[METRIC] = totals.get("weight_bearing_hr_48h") if loaded is not None else None
    numbers["walks_over_75_min_48h"] = totals.get("walks_over_75_min_48h") if loaded is not None else None
    # #4412: the last Hevy cardio block's OWN heart rate, joined from the wearable over its minutes
    last = recent_aerobic.last_cardio_block_hr(block)
    numbers["last_cardio_block_avg_hr"] = last["avg_hr"] if last else None
    numbers["last_cardio_block_over_hr_ceiling"] = last["over_ceiling"] if last else None
    if last is None and any(r.get("source") == "hevy" for r in (block or {}).get("rows") or []):
        # a Hevy cardio block WAS logged, and no wearable covered its minutes: unread, not "no cardio"
        unknown.extend(["last_cardio_block_avg_hr", "last_cardio_block_over_hr_ceiling"])
    if loaded is None:
        unknown.extend([METRIC, "walks_over_75_min_48h"])
        return
    hr_note = (
        f" His last Hevy {last['modality']} block ({last['date']}) ran at {last['avg_hr']:g} bpm avg — wearable HR joined over "
        f"its inferred minutes, coverage {last['hr_coverage']} (#4412)."
        if last
        else ""
    )
    lower = recent_aerobic.is_lower(draft.get("archetype"))
    for ex in draft.get("exercises") or []:
        if not (loaded and lower and _weight_bearing_cardio(ex)):
            continue
        minutes = round(float(ex["duration_seconds"]) / 60.0)
        f = _flag(
            METRIC,
            "change",
            (
                f"{ex['label']} {minutes} min on a lower session after {why} — swap to cycling (recumbent), same {minutes} min, "
                f"HR avg ≤ {recent_aerobic.HR_CEILING_BPM} bpm (target {recent_aerobic.HR_TARGET_BPM}). The {recent_aerobic.WALK_MAX_MIN}-min / "
                f"{recent_aerobic.HR_CEILING_BPM}-bpm walking lines are the owner's; the {recent_aerobic.WEIGHT_BEARING_48H_TRIGGER_HR} h / 48 h trigger is "
                "POPULATION-DERIVED, not his variance (ADR-105, #4387)" + hr_note
            ),
            provenance="owner-history",
            field=f"exercises[{ex['idx']}].movement_key",
            to=SWAP_TO,
            governed=True,
        )
        f["independent"] = True
        f["threshold_provenance"] = recent_aerobic.TRIGGER_PROVENANCE["provenance"]
        flags.append(f)
