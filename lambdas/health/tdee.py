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

# #4158: the ONE stored Hevy set-duration key (`training.hevy_common._normalize_set`
# is the schema owner; the constant lives in `common/`, not `training/`, because this
# module reads no training/load model at all — see
# tests/test_training_load_worked_set_4075.py::test_the_energy_targets_load_input_is_the_stored_tsb_not_a_recompute).
# Pure — no boto3, no I/O — so importing it here does not break this module's
# dependency-free contract (see the module docstring).
from common.activity_overlap import hr_intervals, overlap_seconds  # #4158: the ONE HR-covered-interval derivation
from common.hevy_schema import SET_DURATION_FIELD
from common.pacific_time import parse_iso_utc  # #1964: THE ISO parser (naive == UTC) — pure, no clock read

#: The single method label every published target carries (ADR-105).
#:
#: **Renamed by #3931** from ``mifflin_bmr_plus_measured_7d_exercise``. The rename is
#: load-bearing, not cosmetic: the old label named a number that charged the ~6
#: kcal/kg/hour duration proxy across the FULL logged gym duration, rest between sets
#: included — roughly 3,000 kcal for one 3.5-hour lifting session, 20,276 kcal over a
#: 7-day window, a 5,059 kcal TDEE and a published 3,529 kcal/day (69.8%) deficit that
#: is arithmetically impossible against the same page's own weight trend. Any consumer
#: still carrying the old string is carrying the old number under a label the platform
#: no longer means, so the string is asserted absent from the tree by
#: ``tests/test_tdee_worked_set_3931_behavior.py``.
METHOD = "mifflin_bmr_plus_worked_set_exercise"

#: The retired label. Published NOWHERE — it exists so the sweep test and any future
#: archaeologist can name what changed without grepping git history.
RETIRED_METHOD = "mifflin_bmr_plus_measured_7d_exercise"

#: The SECOND method (#3931 box 3). Not a refinement of ``METHOD`` — an independent
#: estimator with different failure modes, offered alongside it so the two can disagree
#: out loud instead of one of them being quietly wrong.
TREND_METHOD = "weight_trend_back_solve_3500_kcal_per_lb"

#: The impossibility check's own name, carried on every verdict it returns.
TREND_CHECK_METHOD = "implied_deficit_vs_measured_weight_trend"

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
#: Applied to time the body was actually MOVING. Applying it to rest between sets
#: double-charges that time: a minute sitting on a bench is already inside the 24-hour
#: BMR term, and charging it again at ~6x resting is the #3931 inflation.
#:
#: **ONE rate, two call sites (#4158).** ``exercise_energy``'s own proxy branch (below)
#: and ``lifting_energy``'s Hevy-cardio term (a timed Hevy set with ``distance_m`` —
#: cycling/treadmill/walking) both charge THIS constant, never a second cardio-specific
#: rate — a Hevy-logged cardio block is the same kind of continuous movement Strava's
#: own Run/Ride/Walk/Elliptical proxy already prices, so it is priced identically. What
#: #4158 changed is which SECONDS reach either formula (the stored-key fix) and that a
#: Hevy cardio block's seconds are net of whatever an HR-bearing Strava/Whoop activity
#: already scored over the same window (``common.activity_overlap`` — #4157's own
#: overlap derivation, shared rather than re-implemented) — never the rate itself.
PROXY_KCAL_PER_KG_HOUR = 6.0

#: **The stated assumption** (#3931). A Hevy set row carries ``reps`` and, for
#: duration-style movements, an optional ``duration_seconds``. When a weight-rep set logs
#: no duration the platform assumes **40 seconds of work per set** and SAYS SO — the
#: number rides in every ``exercise_energy`` basis string as
#: ``assumed_40s_per_unlogged_set``. 40 s is deliberately generous (a 5-rep heavy single
#: is nearer 15–20 s, a 15-rep set nearer 45 s), so the term errs toward OVER-stating
#: worked time rather than understating expenditure. It is an assumption wearing a
#: number, which is exactly why it is labelled rather than buried.
WORK_SECONDS_PER_REP_SET = 40.0

#: Fallback when a lifting block is visible in Strava but NO Hevy set log covers the
#: window: charge this fraction of the logged duration as work. A hypertrophy session
#: runs roughly 1:3 work:rest, so ~0.25. Labelled in the basis as
#: ``lifting_duration_x0.25_no_set_log`` — never silently applied.
LIFTING_WORK_FRACTION_FALLBACK = 0.25

#: Strava sport/activity types whose logged duration is mostly REST. ``HighIntensity
#: IntervalTraining`` is deliberately absent — it is continuous by construction, so its
#: duration is honest. Cardio blocks (Run/Ride/Walk/Elliptical/…) keep being charged by
#: duration exactly as before; this set is the only thing that changes.
LIFTING_SPORT_TYPES = frozenset({"weighttraining", "workout", "crossfit", "strengthtraining", "weight_training"})

KCAL_PER_LB_FAT = 3500

#: The impossibility check refuses below this many days of measured weight trend — a
#: 3-day "trend" is water, not tissue.
MIN_TREND_DAYS = 7

#: **The stated tolerance** (#3931 box 2). The model-implied deficit and the
#: trend-implied deficit may differ by up to ``max(400 kcal/day, 40% of the larger)``
#: before the platform refuses to publish a calorie target.
#:
#: Where the two arms come from:
#:   * **40%** is the issue's own suggested relative tolerance. It scales because the
#:     bigger the deficit, the bigger the water/glycogen component of the trend that the
#:     3,500-kcal-per-lb constant mis-prices.
#:   * **400 kcal/day** is the absolute floor, so a near-maintenance comparison (where
#:     both numbers are small and a percentage is meaningless) does not refuse on noise.
#:     It is the noise floor of the measurement itself: a 7-day weight trend carries
#:     roughly ±0.8 lb of water/glycogen/gut-content, and 0.8 lb x 3500 / 7 = 400
#:     kcal/day. Below that the two methods are not distinguishable by the data.
TREND_TOLERANCE_FRACTION = 0.40
TREND_TOLERANCE_FLOOR_KCAL = 400.0

#: A deficit larger than this fraction of TDEE is refused outright regardless of the
#: trend — the 69.8% label in #3931 is the specimen. Clinical very-low-calorie protocols
#: top out near a 40-50% deficit and are supervised; a platform publishing 70% to a
#: reader is publishing an artifact, not a target.
MAX_PUBLISHABLE_DEFICIT_FRACTION = 0.50


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


def _is_lifting(activity: Mapping[str, Any]) -> bool:
    """True when this Strava activity's logged duration is mostly rest between sets."""
    for key in ("sport_type", "type"):
        v = str(activity.get(key) or "").strip().lower().replace(" ", "")
        if v and v in LIFTING_SPORT_TYPES:
            return True
    return False


def worked_set_seconds(
    hevy_workouts: Optional[Iterable[Mapping[str, Any]]],
    covered_intervals: Optional[Iterable[Tuple[datetime, datetime]]] = None,
) -> dict:
    """Seconds of actual WORK in a Hevy set log — rest between sets excluded (#3931).

    Reads the set rows as they are STORED (``workout.exercises[].sets[] ->
    {type|set_type, weight_kg, reps, duration_sec?, distance_m?}``) — ``SET_DURATION_FIELD``
    (``duration_sec``), the key ``training.hevy_common._normalize_set`` actually
    writes, never a second spelling (#4158: this used to read only the raw Hevy API
    wire name ``duration_seconds``, a key no stored set row carries, so
    ``sets_with_logged_duration`` read 0 on every real day). The raw wire name is
    still accepted as a fallback for a payload that reaches this function
    pre-normalization. Per set:

      * a timed set carrying ``distance_m`` (cycling, treadmill, walking) is a
        **cardio block** — MEASURED work, discounted by ``covered_intervals``
        (below) so a minute an HR-bearing Strava/Whoop activity already scored is
        never charged twice;
      * a timed set with no distance (a hold: plank, sled, machine interval) is
        MEASURED work, used as-is — nothing else records these minutes, so no
        overlap discount applies;
      * a weight-rep set with no logged duration is charged the stated
        ``WORK_SECONDS_PER_REP_SET`` assumption (40 s) — counted separately so the
        payload can say how much of the total is measured and how much is assumed;
      * a set with neither reps nor a duration contributes nothing.

    **Warmup sets are counted as work.** The thing being excluded here is REST, not
    warmups — a warmup set moves a load and costs energy. Calling the term
    "worked-set time" rather than "working-set time" is deliberate for that reason.

    **The double-count this fixes (#4158, found on the 09-08..09-22 replay):** before
    this discount, a Hevy-logged Treadmill/Cycling block counted its full duration
    here as lifting-side energy AND, whenever a Strava/Whoop activity with average
    HR covered the same window (a WHOOP walk echoing the same treadmill session —
    09-19's specimen: a 3,600 s Hevy Treadmill block against a WHOOP walk carrying HR
    over 3,539 s of it), the SAME minutes a second time through ``exercise_energy``'s
    own duration proxy. ``covered_intervals`` — the merged HR-covered spans from
    ``common.activity_overlap.hr_intervals``, the identical derivation
    ``training.training_load.hevy_session_load`` (#4075) uses on the TSB-load side —
    is looked up against each WORKOUT's own ``[start_time, end_time]`` (Hevy carries
    no per-set timestamps, so the discount is workout-level, exactly as #4075's is),
    capped at that workout's own cardio seconds, and subtracted before this function's
    cardio total is ever charged. Passing ``None`` (the default) applies no discount —
    every existing caller/fixture that predates this parameter keeps its old answer.

    Returns ``{"seconds", "sets", "measured_seconds", "assumed_seconds",
    "sets_with_logged_duration", "workouts", "cardio_seconds", "cardio_seconds_hr_covered"}``.
    ``measured_seconds`` already has the HR-covered cardio share removed;
    ``cardio_seconds``/``cardio_seconds_hr_covered`` are reported so a caller can audit the
    discount itself. Everything zero means the log carried nothing, which the caller must
    treat as ABSENCE, not as a measurement of zero work.
    """
    hold_measured = 0.0
    cardio_gross = 0.0
    cardio_covered = 0.0
    assumed = 0.0
    n_sets = 0
    n_logged = 0
    n_workouts = 0
    for w in hevy_workouts or []:
        exercises = w.get("exercises") or w.get("workout_exercises") or []
        touched = False
        workout_cardio_secs = 0.0
        for ex in exercises:
            for st in ex.get("sets") or []:
                dur = _num(st.get(SET_DURATION_FIELD))
                if dur is None:
                    dur = _num(st.get("duration_seconds"))  # raw Hevy API wire name (pre-normalization)
                reps = _num(st.get("reps")) or 0.0
                distance = _num(st.get("distance_m")) or 0.0
                if dur is not None and dur > 0:
                    n_sets += 1
                    n_logged += 1
                    touched = True
                    if distance > 0:
                        cardio_gross += dur
                        workout_cardio_secs += dur
                    else:
                        hold_measured += dur
                elif reps > 0:
                    assumed += WORK_SECONDS_PER_REP_SET
                    n_sets += 1
                    touched = True
        if touched:
            n_workouts += 1
        if workout_cardio_secs > 0 and covered_intervals:
            start = parse_iso_utc(w.get("start_time"))
            end = parse_iso_utc(w.get("end_time"))
            cardio_covered += min(overlap_seconds(start, end, covered_intervals), workout_cardio_secs)
    cardio_net = max(0.0, cardio_gross - cardio_covered)
    measured = hold_measured + cardio_net
    return {
        "seconds": round(measured + assumed, 1),
        "sets": n_sets,
        "measured_seconds": round(measured, 1),
        "assumed_seconds": round(assumed, 1),
        "sets_with_logged_duration": n_logged,
        "workouts": n_workouts,
        "cardio_seconds": round(cardio_gross, 1),
        "cardio_seconds_hr_covered": round(cardio_covered, 1),
    }


def lifting_energy(
    hevy_workouts: Optional[Iterable[Mapping[str, Any]]],
    weight_kg: float,
    logged_duration_seconds: float = 0.0,
    covered_intervals: Optional[Iterable[Tuple[datetime, datetime]]] = None,
) -> dict:
    """Energy for the LIFTING + Hevy-cardio portion of a window — rest time excluded
    (#3931) and HR-covered Hevy cardio minutes excluded (#4158).

    Preference order, each branch naming itself in ``basis``:

      1. **Hevy set log present** -> ``worked_set_seconds`` x the same ~6 kcal/kg/hour
         duration-proxy rate ``exercise_energy`` already charges its own non-kJ cardio at
         (``PROXY_KCAL_PER_KG_HOUR`` — ONE constant, not a second lifting-specific rate;
         see the module-level note on that constant). Same rate, correct denominator, and
         (#4158) a Hevy cardio block's seconds are net of whatever an HR-bearing
         Strava/Whoop activity already scored over the same window — ``covered_intervals``
         passes straight through to ``worked_set_seconds``, which is where the discount
         happens.
      2. **No set log but Strava logged lifting duration** -> that duration x the stated
         ``LIFTING_WORK_FRACTION_FALLBACK``.
      3. **Neither** -> 0 kcal, ``no_lifting_in_window``.

    Returns ``{"kcal", "basis", "worked_seconds", "logged_seconds", "cardio_seconds",
    "cardio_seconds_hr_covered", ...}``.
    """
    ws = worked_set_seconds(hevy_workouts, covered_intervals=covered_intervals)
    logged = max(0.0, _num(logged_duration_seconds) or 0.0)
    if ws["sets"] > 0:
        secs = ws["seconds"]
        if ws["sets_with_logged_duration"] == ws["sets"]:
            basis = "worked_set_time_from_hevy_set_log"
        elif ws["sets_with_logged_duration"] == 0:
            basis = "worked_set_time_from_hevy_set_log_assumed_40s_per_unlogged_set"
        else:
            basis = "worked_set_time_from_hevy_set_log_mixed_logged_and_assumed_40s_per_unlogged_set"
        if ws["cardio_seconds_hr_covered"] > 0:
            basis += "_cardio_hr_covered_discounted"
    elif logged > 0:
        secs = logged * LIFTING_WORK_FRACTION_FALLBACK
        basis = "lifting_duration_x0.25_no_set_log"
    else:
        secs = 0.0
        basis = "no_lifting_in_window"
    return {
        "kcal": round(PROXY_KCAL_PER_KG_HOUR * weight_kg * (secs / 3600.0), 0),
        "basis": basis,
        "worked_seconds": round(secs, 1),
        "logged_seconds": round(logged, 1),
        "sets": ws["sets"],
        "sets_with_logged_duration": ws["sets_with_logged_duration"],
        "cardio_seconds": ws["cardio_seconds"],
        "cardio_seconds_hr_covered": ws["cardio_seconds_hr_covered"],
    }


def exercise_energy(
    strava_items: Optional[Iterable[Mapping[str, Any]]],
    weight_kg: float,
    hevy_workouts: Optional[Iterable[Mapping[str, Any]]] = None,
) -> dict:
    """Measured exercise energy over whatever window ``strava_items`` covers.

    Returns ``{"kcal", "basis", "days", "lifting"}``. ``days`` is the count of rows that
    actually carried an activity signal — the ADR-152 gap tell. ``basis`` names which
    branch ran: until the strava writer rolled ``total_kilojoules`` up, ``total_kj`` was
    always 0 and every TDEE came from the duration proxy while the payload said nothing
    about it.

    **#3931 — rest time is no longer charged.** Each day's activities are split three
    ways instead of summed into one duration:

      * activities reporting mechanical work (``kilojoules``) -> measured, unchanged;
      * **lifting** activities (``LIFTING_SPORT_TYPES``) -> their duration is REMOVED
        from the proxy and replaced by ``lifting_energy`` (worked-set time from the Hevy
        set log, or the stated 0.25 work fraction when no set log covers the window);
      * everything else (Run / Ride / Walk / Elliptical / row / HIIT…) -> the duration
        proxy, **exactly as before**. Cardio was never the bug.

    A legacy Strava row that carries no per-activity ``activities`` list cannot be split,
    so its whole moving time stays on the proxy — the old behaviour, stated rather than
    silently assumed. The residual that implies: on such a day a Hevy set log would add
    worked-set energy ON TOP of a duration that still includes its own rest. Every row
    the current writer produces carries ``activities`` (``ingestion/strava_lambda.py``),
    so this is a pre-2026-05 archaeology case, and it over-states rather than hides.
    """
    rows = list(strava_items or [])
    total_kj = 0.0
    covered_s = 0.0
    proxy_s = 0.0
    lifting_s = 0.0
    unsplit_days = 0
    days = 0
    all_acts: list = []
    for d in rows:
        day_kj = _num(d.get("total_kilojoules")) or 0.0
        day_time = _num(d.get("total_moving_time_seconds")) or 0.0
        total_kj += day_kj
        if day_kj > 0 or day_time > 0:
            days += 1

        # The kJ split is UNCHANGED (#2310): only power-equipped activities report kJ, and
        # rows written before the writer recorded the covered-time split carry no such
        # field — for them kJ is taken to cover the day rather than double-counting.
        if day_kj > 0:
            explicit = _num(d.get("kilojoules_moving_time_seconds"))
            covered = explicit if explicit is not None else day_time
        else:
            covered = 0.0
        covered = max(0.0, min(covered, day_time))

        acts = d.get("activities") or []
        all_acts.extend(acts)
        if not acts and day_time > 0:
            unsplit_days += 1
        # #3931: the ONLY new subtraction — the logged duration of lifting activities,
        # which is mostly rest between sets. Clamped so it can never eat kJ-covered time.
        lifting = 0.0
        for a in acts:
            if (_num(a.get("kilojoules")) or 0.0) > 0:
                continue
            if _is_lifting(a):
                lifting += _num(a.get("moving_time_seconds")) or 0.0
        lifting = max(0.0, min(lifting, day_time - covered))

        covered_s += covered
        lifting_s += lifting
        proxy_s += max(0.0, day_time - covered - lifting)

    # #4158: the SAME HR-covered-interval derivation `training.training_load.hevy_session_load`
    # (#4075) uses on the TSB-load side, so a Hevy cardio block already scored by an
    # HR-bearing Strava/Whoop activity (09-19's specimen: a 3,600 s Hevy Treadmill block
    # against a WHOOP walk carrying HR over 3,539 s of it) is not charged twice here.
    covered_intervals = hr_intervals(all_acts)
    lift = lifting_energy(hevy_workouts, weight_kg, logged_duration_seconds=lifting_s, covered_intervals=covered_intervals)
    proxy_kcal = PROXY_KCAL_PER_KG_HOUR * weight_kg * (proxy_s / 3600.0)

    if total_kj <= 0:
        if proxy_s <= 0 and lift["kcal"] <= 0:
            basis = "no_activity_in_window"
        elif lift["worked_seconds"] > 0:
            basis = f"duration_proxy_6_kcal_per_kg_hour_plus_{lift['basis']}"
        else:
            basis = "duration_proxy_6_kcal_per_kg_hour"
        kcal = proxy_kcal + lift["kcal"]
    else:
        # kJ of mechanical work ~= kcal expended at ~25% gross efficiency. Moving time
        # NOT covered by a kJ reading still gets the proxy, so a run sharing the day with
        # a ride is not dropped.
        kcal = total_kj + proxy_kcal + lift["kcal"]
        if proxy_s <= 0 and lift["worked_seconds"] <= 0:
            basis = "measured_kilojoules"
        elif lift["worked_seconds"] > 0:
            basis = f"mixed_measured_kilojoules_and_duration_proxy_plus_{lift['basis']}"
        else:
            basis = "mixed_measured_kilojoules_and_duration_proxy"

    return {
        "kcal": round(kcal, 0),
        "basis": basis,
        "days": days,
        "method": METHOD,
        "lifting": lift,
        "proxy_seconds": round(proxy_s, 1),
        "unsplit_legacy_days": unsplit_days,
    }


def tdee_from_trend(intake_avg_kcal: Any, trend_lb_per_wk: Any, days: Optional[int] = None) -> Optional[dict]:
    """**The second method** (#3931 box 3) — back-solve TDEE from the observed trend.

    ``TDEE = mean intake + (tissue energy the body drew down per day)``, at
    ``KCAL_PER_LB_FAT`` per pound. A LOSS is a negative ``trend_lb_per_wk`` and ADDS to
    TDEE; a gain subtracts. ``None`` when either input is unreadable.

    The independence is the point: this estimator never touches a MET table, a duration
    log or a Mifflin coefficient, so it fails in different directions than ``METHOD``
    does. Its own weakness, stated rather than dropped: the 3,500 kcal/lb constant prices
    FAT, and the first two weeks of a cut are heavily water and glycogen — so a short
    window over-reads TDEE, badly. That is why ``MIN_TREND_DAYS`` exists and why the
    13-day #3931 specimen back-solves to a number the issue's own red-team band does not
    contain: the specimen is the failure mode, not a validation of it.
    """
    intake = _num(intake_avg_kcal)
    trend = _num(trend_lb_per_wk)
    if intake is None or trend is None:
        return None
    tissue_kcal_per_day = -trend * KCAL_PER_LB_FAT / 7.0
    return {
        "tdee": int(round(intake + tissue_kcal_per_day)),
        "method": TREND_METHOD,
        "basis": ("short_window_water_weight_inflates_this" if (days is not None and days < 14) else "measured_trend"),
        "inputs": {
            "intake_avg_kcal": round(intake, 0),
            "weight_trend_lb_per_wk": round(trend, 2),
            "tissue_kcal_per_day": round(tissue_kcal_per_day, 0),
            "kcal_per_lb": KCAL_PER_LB_FAT,
            "trend_days": days,
        },
    }


def implied_deficit_vs_trend(
    tdee: Any,
    intake_7d_avg: Any,
    weight_trend_lb_per_wk: Any,
    days: int = 0,
) -> dict:
    """**The impossibility check** (#3931 box 2). Never returns a silent number.

    Compares the deficit the MODEL implies (``tdee - intake``) against the deficit the
    MEASURED weight trend implies (``-trend_lb_per_wk * 3500 / 7``) and returns a verdict
    carrying BOTH numbers, the gap, the tolerance it was judged against, and a ``basis``
    string that begins with ``"refused: "`` whenever a calorie target must not be
    published.

    Refusal clauses, in order:

      1. ``refused: deficit_exceeds_50pct_of_tdee`` — independent of the trend. The
         #3931 specimen published 3,529 kcal/day against a 5,059 TDEE: a 69.8% deficit.
      2. ``refused: model_and_trend_disagree`` — the gap exceeds
         ``max(400, 40% of the larger)`` (see ``TREND_TOLERANCE_FRACTION``).

    Non-refusal outcomes are equally explicit: an absent or too-short trend returns
    ``publish: True`` with ``basis: "published_unverified_no_measured_weight_trend"`` —
    the target ships, but the payload says out loud that nothing checked it, rather than
    letting "no data" read as "agreed".
    """
    t = _num(tdee)
    intake = _num(intake_7d_avg)
    trend = _num(weight_trend_lb_per_wk)
    n = int(days or 0)

    out: dict = {
        "method": TREND_CHECK_METHOD,
        "tolerance_fraction": TREND_TOLERANCE_FRACTION,
        "tolerance_floor_kcal_per_day": TREND_TOLERANCE_FLOOR_KCAL,
        "max_deficit_fraction_of_tdee": MAX_PUBLISHABLE_DEFICIT_FRACTION,
        "min_trend_days": MIN_TREND_DAYS,
        "trend_days": n,
        "tdee": int(round(t)) if t is not None else None,
        "intake_avg_kcal": int(round(intake)) if intake is not None else None,
        "weight_trend_lb_per_wk": round(trend, 2) if trend is not None else None,
        "implied_deficit_kcal_per_day": None,
        "trend_implied_deficit_kcal_per_day": None,
        "gap_kcal_per_day": None,
        "deficit_fraction_of_tdee": None,
        "tolerance_kcal_per_day": None,
    }

    if t is None or t <= 0 or intake is None:
        out["publish"] = False
        out["basis"] = "refused: no_tdee_or_intake_to_check"
        return out

    implied = t - intake
    out["implied_deficit_kcal_per_day"] = int(round(implied))
    frac = implied / t
    out["deficit_fraction_of_tdee"] = round(frac, 3)

    if frac > MAX_PUBLISHABLE_DEFICIT_FRACTION:
        out["publish"] = False
        out["basis"] = (
            f"refused: deficit_exceeds_{int(MAX_PUBLISHABLE_DEFICIT_FRACTION * 100)}pct_of_tdee — "
            f"model says {int(round(implied))} kcal/day ({round(frac * 100, 1)}% of a {int(round(t))} kcal TDEE) "
            f"against a measured intake of {int(round(intake))} kcal/day"
        )
        return out

    if trend is None or n < MIN_TREND_DAYS:
        out["publish"] = True
        out["basis"] = (
            "published_unverified_no_measured_weight_trend"
            if trend is None
            else f"published_unverified_trend_window_{n}d_below_{MIN_TREND_DAYS}d_minimum"
        )
        return out

    trend_implied = -trend * KCAL_PER_LB_FAT / 7.0
    gap = abs(implied - trend_implied)
    tol = max(TREND_TOLERANCE_FLOOR_KCAL, TREND_TOLERANCE_FRACTION * max(abs(implied), abs(trend_implied)))
    out["trend_implied_deficit_kcal_per_day"] = int(round(trend_implied))
    out["gap_kcal_per_day"] = int(round(gap))
    out["tolerance_kcal_per_day"] = int(round(tol))

    if gap > tol:
        out["publish"] = False
        out["basis"] = (
            f"refused: model_and_trend_disagree — model {int(round(implied))} kcal/day vs "
            f"{int(round(trend_implied))} kcal/day implied by {round(trend, 2)} lb/wk measured over {n} days "
            f"(gap {int(round(gap))} > tolerance {int(round(tol))})"
        )
        return out

    out["publish"] = True
    out["basis"] = (
        f"agrees_with_measured_weight_trend — model {int(round(implied))} kcal/day vs "
        f"{int(round(trend_implied))} kcal/day over {n} days (gap {int(round(gap))} <= tolerance {int(round(tol))})"
    )
    return out


def weight_trend_lb_per_wk(weight_rows: Optional[Iterable[Mapping[str, Any]]]) -> Tuple[Optional[float], int]:
    """``(lb_per_week, span_days)`` from dated weigh-in rows — first vs last, no fit.

    A straight endpoint slope, not a regression: the check it feeds asks "could this
    intake have produced this much tissue change", which is an endpoint question. Rows
    need a ``date`` (or ``sk`` ending ``DATE#...``) and a positive ``weight_lbs``;
    anything else is ABSENT. ``(None, 0)`` when fewer than two usable weigh-ins exist.
    """
    pts = []
    for r in weight_rows or []:
        w = _num(r.get("weight_lbs"))
        if w is None or w <= 0:
            continue
        d = r.get("date") or str(r.get("sk") or "").split("DATE#")[-1]
        if not d:
            continue
        pts.append((str(d)[:10], w))
    if len(pts) < 2:
        return None, 0
    pts.sort(key=lambda x: x[0])
    (d0, w0), (d1, w1) = pts[0], pts[-1]
    try:
        span = (datetime.strptime(d1, "%Y-%m-%d") - datetime.strptime(d0, "%Y-%m-%d")).days
    except (TypeError, ValueError):
        return None, 0
    if span < 1:
        return None, 0
    return round((w1 - w0) * 7.0 / span, 3), span


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
    trend_check: Optional[dict] = None,
    lifting: Optional[dict] = None,
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

    # #3931 box 4: where the impossibility check refuses, the surface says REFUSED. It
    # does not publish a smaller number, or the same number with a warning beside it —
    # `target` is None and `target_basis` carries the refusal with both figures in it.
    check: dict = trend_check or {}
    refused = bool(check) and not check.get("publish", True)
    target_basis = check.get("basis") if check else f"{METHOD}_minus_deficit"

    return {
        # TDEE means MAINTENANCE. The deficit lives only in `target`.
        "tdee": int(tdee),
        "deficit": int(deficit),
        "target": None if refused else int(target),
        "method": METHOD,
        "target_basis": target_basis,
        "target_published": not refused,
        "trend_check": trend_check,
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
            # #3931: the worked-set breakdown behind the exercise term, so a reader can
            # see how much of it is measured set duration and how much is the stated 40 s
            # assumption — without reading this source (ADR-105).
            "lifting": lifting,
        },
    }


def implied_weekly_loss_lbs(deficit_kcal: float) -> float:
    """Weekly loss a sustained daily deficit implies, at 3500 kcal per lb of fat."""
    return round((_num(deficit_kcal) or 0.0) * 7 / KCAL_PER_LB_FAT, 2)
