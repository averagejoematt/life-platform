"""training/layoff_tiers.py — the owner's OD1 re-entry tiers (#4503, training program v0.5).

Owner ruling OD1 (A), adopted 2026-09-30 (Session BB, the v0.5 red team):

    "this-cycle anchors (<= 28 d at this band) are held at the RPE-adjusted load. A 29–90 d gap
    -> 85–90 % of band best; > 90 d / novel-again -> the 60–65 % ramp (RPE <= 7, reps <= 8 for
    exposures 1–3, then +5 %/exposure, <= +10 %/7 d). #4417's layoff line moves from 7 d to 28 d."

`load_ramp._apply_hold` reads the tier off ONE gap: the larger of the caller's days since the last
workout, the record's gap since the last loaded session (any movement), and THIS movement's gap
since its last session at the current bodyweight band. So "≤ 28 d at this band" is read per
movement, as the ruling words it — a squat last done 40 days ago is a 29–90 d re-entry even if he
benched last week.

  * HOLD (gap <= 28): the #4408 hold, its qualifying sets read from the last 28 days.
  * RE-ENTRY (29..90): the same RPE-adjusted, slot-aware hold over the last 90 days, at 90 %
    rounded DOWN on the one 5-lb grid (`rep_scheme.load_step_kg`) — inside the ruling's 85–90 %
    for any load over ~100 lb; under that the grid can step below 85 %, and the row's
    `pct_of_band_best` says so rather than rounding up past 90.
  * RAMP (> 90, or nothing at this band in 90 days): the week's entry ramp, unchanged.

Exposure caps (RPE <= 7, reps <= 8) are RECORDED on every ramped row for exposures 1–3 after an
OBSERVED gap of more than 90 days in this movement's own record (a gap before the start of the
loaded history is not observed — it is not counted). The generator names them in the load cue;
it does not rewrite the set shape (the IR `Set` carries no RPE field).
"""

from __future__ import annotations

from typing import Any

HOLD_MAX_GAP_DAYS = 28
REENTRY_MAX_GAP_DAYS = 90
REENTRY_PCT_OF_BAND_BEST = (85, 90)
EXPOSURE_CAPS = {"exposures": 3, "rpe_max": 7, "reps_max": 8}

TIER_HOLD = "hold"
TIER_REENTRY = "reentry"
TIER_RAMP = "ramp"

OD1_RULING = (
    "owner ruling OD1 (A), 2026-09-30 (#4503): <= 28 d at this band -> held at the RPE-adjusted load; "
    "29–90 d -> 85–90 % of band best; > 90 d / novel-again -> the 60–65 % ramp, RPE <= 7 and reps <= 8 for exposures 1–3"
)


def od1_tier(gap_days: int | None) -> str:
    """The OD1 tier for a gap in days. None (no gap readable) is the hold tier — the #4408 hold
    still needs a qualifying set, so an unreadable gap never invents a load."""
    if gap_days is None or gap_days <= HOLD_MAX_GAP_DAYS:
        return TIER_HOLD
    return TIER_REENTRY if gap_days <= REENTRY_MAX_GAP_DAYS else TIER_RAMP


def movement_band_gap_days(
    template_id: str | None,
    history_index: dict[str, list],
    weight_index: dict[str, float] | None,
    current_weight_lb: float | None,
    as_of: str | None,
    tolerance_days: int | None = None,
) -> int | None:
    """Days from this movement's last session at the current band to `as_of` (None: none on record)."""
    from common.pacific_time import parse_day_key

    from training.band_reference import band_key
    from training.exercise_history import BODYWEIGHT_TOLERANCE_DAYS, nearest_bodyweight

    if not template_id or not current_weight_lb or not as_of:
        return None
    band = band_key(float(current_weight_lb))
    tol = BODYWEIGHT_TOLERANCE_DAYS if tolerance_days is None else tolerance_days
    latest = ""
    for s in (history_index or {}).get(template_id) or []:
        d = str(s.get("date") or "")
        if not d or d >= as_of or d <= latest:
            continue
        lbs = nearest_bodyweight(d, weight_index, tol)
        if lbs is not None and band_key(lbs) == band:
            latest = d
    a, b = parse_day_key(as_of), parse_day_key(latest)
    return (a - b).days if (a is not None and b is not None) else None


def reentry_load_kg(band_best_kg: float) -> tuple[float, float]:
    """(load, % of band best) for a 29–90 d re-entry: 90 % rounded DOWN on the one 5-lb grid."""
    from training.rep_scheme import load_step_kg

    kg = load_step_kg(float(band_best_kg) * REENTRY_PCT_OF_BAND_BEST[1] / 100.0, down=True)
    return kg, round(100.0 * kg / float(band_best_kg), 1)


def exposure_caps(template_id: str | None, history_index: dict[str, list], as_of: str | None) -> dict[str, Any] | None:
    """The OD1 exposure-1–3 caps, or None when no gap of more than 90 days is observed in this
    movement's own record before `as_of` (or the caps have run out: exposure 4 onward)."""
    from common.pacific_time import parse_day_key

    if not template_id or not as_of:
        return None
    dates = sorted(
        {str(s.get("date") or "")[:10] for s in (history_index or {}).get(template_id) or [] if str(s.get("date") or "") < as_of}
    )
    days = [parse_day_key(d) for d in dates if d]
    end = parse_day_key(as_of)
    if end is None or any(d is None for d in days):
        return None
    points = [d for d in days if d is not None] + [end]
    gap_at = next((i for i in range(len(points) - 1, 0, -1) if (points[i] - points[i - 1]).days > REENTRY_MAX_GAP_DAYS), None)
    if gap_at is None:
        return None
    exposure = len(points) - gap_at  # the session being drafted is exposure 1 when the gap ends at `as_of`
    if exposure > int(EXPOSURE_CAPS["exposures"]):
        return None
    return {
        "exposure": exposure,
        "rpe_max": EXPOSURE_CAPS["rpe_max"],
        "reps_max": EXPOSURE_CAPS["reps_max"],
        "gap_days": (points[gap_at] - points[gap_at - 1]).days,
        "rule": OD1_RULING,
    }
