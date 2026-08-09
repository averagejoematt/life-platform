"""lambdas/health/tdee.py — THE one TDEE definition (ADR-152).

Before this module the platform published "today's calorie target" twice, from two
formulas, ~2x apart (#2310): ``mcp/tools_nutrition._mifflin_tdee`` multiplied a
Mifflin-St Jeor BMR by a flat 1.55 activity factor and applied NO deficit (3055 kcal for
a 220 lb man), while ``mcp/tools_health._get_energy_expenditure`` added *measured*
7-day exercise energy and subtracted 500 kcal (1557 kcal). Both were internally correct;
together they were a rigor failure under ADR-104/105.

ADR-152 settles it:

  * **TDEE = Mifflin-St Jeor BMR + measured trailing-window exercise energy.**
    The flat multiplier is retired — a flat multiplier is an assumption wearing a
    number, and ADR-105 prefers the platform's own measured data. The rejected
    tradeoff, stated rather than dropped: the measured form inherits every gap in
    exercise-energy capture (a Strava/Whoop outage reads as "no training"). That is
    mitigated, not hidden — the payload carries ``exercise_energy_days`` so a gap is
    visible. When no exercise data exists for the window the exercise term is 0 AND
    ``exercise_energy_days`` is 0 (honest absence, ADR-104), never a fabricated
    multiplier.

  * **TDEE means MAINTENANCE.** The deficit lives ONLY in the published target:
    ``target = tdee - deficit``. Both numbers and the deficit ship explicitly.

  * **Every surface publishing a target ships its method and its inputs** (ADR-105),
    so the number is checkable without reading this source.

This module is pure: no I/O, no boto3, no clock reads except an explicit ``now``
argument. It is staged at the bundle root by ``deploy/build_bundle.py`` (which copies
the whole ``lambdas/`` tree), so ``from health import tdee`` resolves identically from
the MCP bundle, the site-api bundle and the compute path.

**Known deliberate non-caller:** ``health/process_milestones.mifflin_tdee_estimate``
still carries the flat-multiplier form. It is not a published "what should I eat"
target — it is a per-day expenditure floor for the ``strength_in_deficit`` milestone,
running in a dependency-free compute path that has no exercise-energy input at all.
ADR-152 records that as a stated exception, not a second answer to the same question.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping, Optional, Tuple

#: The single method label every published target carries (ADR-105).
METHOD = "mifflin_bmr_plus_measured_7d_exercise"

#: The cut Matthew is running. Applied to the TARGET only, never folded into TDEE.
DEFAULT_DEFICIT_KCAL = 500

#: The trailing window the exercise term is measured over.
EXERCISE_WINDOW_DAYS = 7

LB_TO_KG = 0.453592
IN_TO_CM = 2.54

#: Used only when the profile carries no parseable date_of_birth. Always surfaced as
#: ``age_basis`` so it can never be mistaken for a measured input (ADR-104).
ASSUMED_AGE_YEARS = 35

#: Duration proxy for activities that report no mechanical work — ~6 kcal/kg/hour.
PROXY_KCAL_PER_KG_HOUR = 6.0

KCAL_PER_LB_FAT = 3500


def _num(v: Any) -> Optional[float]:
    """``float(v)`` or ``None`` — never raises. An unreadable value is ABSENT."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def mifflin_bmr(weight_kg: float, height_cm: float, age_years: float, sex: str = "male") -> float:
    """Mifflin-St Jeor resting metabolic rate, kcal/day. No activity factor."""
    base = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age_years
    return round(base - 161.0 if str(sex).lower() == "female" else base + 5.0, 0)


def resolve_age(dob_str: Any, now: Optional[datetime] = None) -> Tuple[float, str, Optional[Exception]]:
    """``(age_years, age_basis, parse_error)`` from a profile ``date_of_birth``.

    The basis string is published so a reader can tell a measured age from the
    assumed one. The exception is RETURNED rather than logged here — a date_of_birth
    is PII (docs/DATA_GOVERNANCE.md) and the caller owns its log posture.
    """
    if not dob_str:
        return float(ASSUMED_AGE_YEARS), "no_date_of_birth_in_profile", None
    try:
        dob = datetime.strptime(str(dob_str), "%Y-%m-%d")
        ref = (now or datetime.utcnow()).replace(tzinfo=None)
        return (ref - dob).days / 365.25, "profile_date_of_birth", None
    except Exception as exc:  # noqa: BLE001 — the basis marker is the signal, not the type
        return float(ASSUMED_AGE_YEARS), "date_of_birth_unparseable", exc


def exercise_energy(strava_items: Optional[Iterable[Mapping[str, Any]]], weight_kg: float) -> dict:
    """Measured exercise energy over whatever window ``strava_items`` covers.

    Returns ``{"kcal", "basis", "days"}``. ``days`` is the count of rows that actually
    carried an activity signal — the ADR-152 gap tell. ``basis`` names which branch ran:
    until the strava writer rolled ``total_kilojoules`` up, ``total_kj`` was always 0 and
    every TDEE came from the duration proxy while the payload said nothing about it.
    """
    rows = list(strava_items or [])
    total_kj = 0.0
    total_time = 0.0
    days = 0
    for d in rows:
        kj = _num(d.get("total_kilojoules")) or 0.0
        secs = _num(d.get("total_moving_time_seconds")) or 0.0
        total_kj += kj
        total_time += secs
        if kj > 0 or secs > 0:
            days += 1

    if total_kj <= 0:
        hours = total_time / 3600.0
        basis = "duration_proxy_6_kcal_per_kg_hour" if total_time > 0 else "no_activity_in_window"
        return {"kcal": round(PROXY_KCAL_PER_KG_HOUR * weight_kg * hours, 0), "basis": basis, "days": days}

    # Only power-equipped activities report kJ. Counting the day's kJ as the WHOLE day's
    # expenditure would drop a run that shared the day with a ride, so moving time NOT
    # covered by a kJ reading still gets the proxy. Rows written before the writer
    # recorded that split carry no covered-time field — for them kJ is taken to cover the
    # day (the old behaviour) rather than double-counting.
    covered_s = 0.0
    for d in rows:
        if (_num(d.get("total_kilojoules")) or 0.0) <= 0:
            continue
        explicit = _num(d.get("kilojoules_moving_time_seconds"))
        covered_s += explicit if explicit is not None else (_num(d.get("total_moving_time_seconds")) or 0.0)
    uncovered_hours = max(0.0, total_time - covered_s) / 3600.0
    # kJ of mechanical work ~= kcal expended at ~25% gross efficiency.
    kcal = total_kj + PROXY_KCAL_PER_KG_HOUR * weight_kg * uncovered_hours
    basis = "measured_kilojoules" if uncovered_hours <= 0 else "mixed_measured_kilojoules_and_duration_proxy"
    return {"kcal": round(kcal, 0), "basis": basis, "days": days}


def energy_budget(
    *,
    weight_lbs: Optional[float],
    height_inches: Optional[float],
    age_years: Optional[float] = None,
    age_basis: str = "assumed",
    sex: str = "male",
    exercise_kcal: float = 0.0,
    exercise_energy_days: int = 0,
    exercise_energy_basis: str = "no_activity_in_window",
    window_days: int = EXERCISE_WINDOW_DAYS,
    deficit_kcal: float = DEFAULT_DEFICIT_KCAL,
) -> Optional[dict]:
    """THE calorie-target payload (ADR-152). ``None`` when weight or height is absent.

    ``None`` rather than a guess is deliberate: Mifflin-St Jeor is 6.25 kcal per cm of
    height, so assuming a height publishes a BMR, a TDEE and a number he would eat to,
    all derived from a guess, with nothing saying so (ADR-104).
    """
    wl = _num(weight_lbs)
    hi = _num(height_inches)
    if wl is None or wl <= 0 or hi is None or hi <= 0:
        return None

    weight_kg = wl * LB_TO_KG
    height_cm = hi * IN_TO_CM
    age = float(age_years) if age_years is not None else float(ASSUMED_AGE_YEARS)
    bmr = mifflin_bmr(weight_kg, height_cm, age, sex)

    days = max(1, int(window_days))
    ex_kcal = _num(exercise_kcal) or 0.0
    ex_daily = round(ex_kcal / days, 0)

    tdee = round(bmr + ex_daily, 0)
    deficit = round(_num(deficit_kcal) or 0.0, 0)
    target = round(tdee - deficit, 0)

    return {
        # TDEE means MAINTENANCE. The deficit lives only in `target`.
        "tdee": int(tdee),
        "deficit": int(deficit),
        "target": int(target),
        "method": METHOD,
        "inputs": {
            "weight_lbs": round(wl, 1),
            "weight_kg": round(weight_kg, 1),
            "height_inches": round(hi, 1),
            "height_cm": round(height_cm, 1),
            "age_years": round(age, 1),
            "age_basis": age_basis,
            "sex": str(sex).lower(),
            "bmr_kcal": int(bmr),
            "exercise_window_days": days,
            "exercise_kcal_7d": int(ex_kcal),
            # The gap tell (ADR-152): 0 means the window carried NO exercise data, so
            # the exercise term is an honest absence, not a measurement of zero.
            "exercise_energy_days": int(exercise_energy_days),
            "exercise_kcal_daily_avg": int(ex_daily),
            "exercise_energy_basis": exercise_energy_basis,
        },
    }


def implied_weekly_loss_lbs(deficit_kcal: float) -> float:
    """Weekly loss a sustained daily deficit implies, at 3500 kcal per lb of fat."""
    return round((_num(deficit_kcal) or 0.0) * 7 / KCAL_PER_LB_FAT, 2)
