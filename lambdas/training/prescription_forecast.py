"""prescription_forecast.py — the weekly prescription, registered as a graded forecast (#3712).

WHAT THIS CLOSES (epic #3707's last open child)

#3709/#3710/#3711 gave the planner a weight-matched reference, a prescription view
and a ranked campaign delta. All three are *descriptions*: they say what he was
doing when it worked and how far below that he is now. None of them commits the
week to a number, so nothing about the coaching can be shown to be wrong. A plan
that cannot be wrong is order-taking with a table attached.

This module is the claim. Each week the prescription states the outcome it expects
under the volume it prescribes — a point and an 80% interval on the coming week's
weight-change rate — and the following week grades that claim against what actually
happened, through the platform's EXISTING interval-grading path: a
``forecast_resolution`` row in the CROSS_PHASE ``SOURCE#calibration`` ledger,
carrying ``covered``, exactly the shape ``forecast_engine_lambda`` writes and
``calibration_core.pairs_from_forecast_resolution_rows`` already scores (#1246). No
new grader, no second calibration ledger.

WHAT IS AND IS NOT BEING CLAIMED (ADR-104/ADR-105, BENCH-1's board guardrails)

The model is an ordinary least-squares line through HIS OWN weekly history —
weekly cardio hours (Strava walking + cycling, per #3716's correction that walking
alone understates cardio by up to half) against that week's measured weight-change
rate. It is descriptive and correlational. It does not say cardio hours *cause* a
loss rate, and every emitted string says so. Intake — the dominant lever — is not
in the model at all and cannot be: MacroFactor begins 2025-11-24, so most of the
history the line is fitted through has no nutrition data. That is stated on every
forecast rather than left to be inferred from its absence.

THE INTERVAL IS EARNED, NOT ASSUMED

The 80% interval comes from **leave-one-out** residual quantiles, not from a
t-distribution: refit the line n times with one week held out, predict the held-out
week, and take the empirical 10th/90th percentiles of those out-of-sample errors.
This costs nothing at n≈100 weeks, assumes no error distribution, and — because the
same loop scores the null model (the trailing mean rate) on the same held-out weeks
— it yields ``skill_vs_null`` for free. An in-sample interval would have been
narrower and would have been a lie about how well the line predicts a week it has
not seen.

DECLINING IS A RESULT

``build_forecast`` refuses in three named cases rather than guessing: too few
complete weeks (``MIN_FORECAST_WEEKS``), no variation in the prescribed lever (no
slope is identifiable), and extrapolation — a prescribed volume more than
``EXTRAPOLATION_CAP`` above the most he has ever logged in a week is a number the
line has never seen. A declined forecast is written and surfaced as a decline; it
is never silently replaced with the null.

THE MISS FEEDS THE NEXT WEEK

``derive_adjustment`` converts a graded miss into next week's number by arithmetic,
never by re-authoring. Its first question is whether the plan was actually run:
below ``ADHERENCE_FLOOR`` the model was not tested, so the target is re-derived from
what was DELIVERED (a ``RAMP_CAP`` step off it) rather than re-issued unchanged — a
target that goes unmet three weeks running and is re-printed identically is the
order-taking this issue exists to end. Only on a delivered week does a miss move the
volume, and then by ``shortfall_lb / slope`` hours, capped by the same ramp.

Pure and deterministic — no I/O, no AWS, no clock of its own. The weekly producer
(``compute/episode_detect_lambda.py``) supplies the records and owns the writes; the
read side (``mcp/tools_benchmark.py`` view=forecast) supplies the track record.
"""

from __future__ import annotations

from typing import Any

from common import stats_core

# THE calendar-day helpers (#3741/#3751). A week window is pure day-key arithmetic —
# no instant, no zone — so it routes through these rather than open-coding
# `date.fromisoformat`, which is what `tests/test_iso_parse_site_registry_3609.py`'s
# capped, shrink-only registry exists to stop growing a 66th row for.
from common.pacific_time import parse_day_key, shift_day_key

MODEL_ID = "prescription-cardio-loo@1"

# The record/row discriminators. `RESOLUTION_RECORD_TYPE` is deliberately the string
# the forecast engine already writes — this rides the existing grading path, and a
# second spelling would make the calibration scoreboard silently drop these rows.
FORECAST_RECORD_TYPE = "prescription_forecast"
RESOLUTION_RECORD_TYPE = "forecast_resolution"

# Nominal interval coverage. 0.80 matches forecast_engine_lambda's, so a coverage
# number read off the shared calibration ledger means the same thing for both.
CONFIDENCE = 0.80

WEEK_DAYS = 7

# A week's rate is the least-squares slope of that week's own weigh-ins, x7. Daily
# bodyweight swings 1-5 lb (band_reference.RATE_FLOOR_WEIGHINS carries the same
# reasoning), so a slope through two readings four days apart is noise wearing a
# rate's units. A week below either floor yields NO rate and is neither fitted nor
# graded — the interval is allowed to be wide, but the inputs are not allowed to be
# arithmetic on nothing.
#
# WHY THE WEEK'S OWN SLOPE, and not the difference of two weekly mean weights. The
# mean of a week's readings sits at that week's MIDPOINT, so differencing two of them
# measures the seven days straddling the week boundary — the back half of one week
# and the front half of the next — and pairing that with either week's cardio hours
# grades the plan partly on volume from a week it did not cover. Measured while
# building this: on a synthetic history with a perfect 0.25 lb per cardio-hour
# relationship, the mean-difference pairing scored skill_vs_null of -0.001, i.e. it
# destroyed a signal that was there by construction. One window on both sides is the
# fix; the noise that remains is real and the interval is where it shows up.
MIN_WEIGHINS_PER_WEEK = 3
MIN_WEEK_SPAN_DAYS = 4

# The fitting floor. Below this the line is not a measurement — decline instead.
MIN_FORECAST_WEEKS = 8

# How far above the observed weekly maximum a prescription may be forecast at. The
# line has never seen a week there; beyond this it is extrapolation wearing an
# interval.
EXTRAPOLATION_CAP = 1.25

# Below this fraction of the prescribed volume, the week did not test the model.
ADHERENCE_FLOOR = 0.80

# Chronic-load ramp: the most a derived target may step above what was delivered.
# Same 10%/wk convention the ACWR literature uses and `personal_baselines` already
# trusts for training load.
RAMP_CAP = 0.10

# How many graded weeks the bias correction averages over.
BIAS_WINDOW = 4

# Below this many graded weeks, "is the coaching working" has no answer yet.
MIN_TRACK_RECORD = 4

# Strava kinds that count as the prescribed cardio lever (#3716 — cycling was dropped
# from every training covariate until 2026-09-08 and is 17-56% of cardio hours in the
# mid bands).
CARDIO_KINDS = ("walk", "cycle")

INTAKE_NOTE = (
    "Training and activity only. Intake is not in this model and cannot be — MacroFactor "
    "begins 2025-11-24, so most of the weeks this line is fitted through have no nutrition "
    "data at all. Intake is the dominant lever in weight change."
)

BASIS_NOTE = (
    "Descriptive of Matthew's own n=1 weekly history (correlational, not causal). The "
    "forecast is what weeks at this cardio volume have historically run at, not a claim "
    "that the volume produces the rate."
)


# ── small deterministic helpers ────────────────────────────────────────────────


def _percentile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolated quantile of an already-sorted list (q in [0,1])."""
    if not sorted_vals:
        raise ValueError("percentile of an empty series")
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return float(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac)


def _ols(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    """(slope, intercept), or None when the predictor does not vary."""
    n = len(xs)
    if n < 2:
        return None
    xbar = sum(xs) / n
    ybar = sum(ys) / n
    sxx = sum((x - xbar) ** 2 for x in xs)
    if sxx <= 0:
        return None
    slope = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys)) / sxx
    return slope, ybar - slope * xbar


def week_windows(anchor: str, n_weeks: int) -> list[tuple[str, str]]:
    """The `n_weeks` 7-day windows ending on `anchor` (inclusive), oldest first.

    An unparseable anchor returns NO windows rather than the anchor string repeated —
    `shift_day_key` hands a bad key back unchanged by contract, and seven identical
    "windows" would be silently fitted as history.
    """
    if parse_day_key(anchor) is None:
        return []
    out: list[tuple[str, str]] = []
    for k in range(n_weeks - 1, -1, -1):
        end = shift_day_key(anchor, -WEEK_DAYS * k)
        out.append((shift_day_key(end, -(WEEK_DAYS - 1)), end))
    return out


# ── the weekly series ──────────────────────────────────────────────────────────


def weekly_weeks(
    weigh_ins: list[tuple[str, float]],
    activities: list[dict[str, Any]],
    anchor: str,
    n_weeks: int,
) -> list[dict[str, Any]]:
    """Per-week measured rate + delivered cardio hours, oldest→newest.

    `weigh_ins` is [(date, lb)] and `activities` is episode-detect's normalized
    [{date, kind, hours, ...}] — the same two structures `build_reference` reads, so
    the forecast is fitted on exactly the history the prescription is drawn from.

    `rate_lb_wk` is the week's own least-squares slope x7 (positive = losing), or
    None when the week does not clear the weigh-in / span floors. None means "not
    measured", never 0.0 (ADR-104).
    """
    by_day_weight: dict[str, list[float]] = {}
    for day, lb in weigh_ins or []:
        if lb is None:
            continue
        by_day_weight.setdefault(str(day)[:10], []).append(float(lb))

    cardio_by_day: dict[str, float] = {}
    for act in activities or []:
        if act.get("kind") not in CARDIO_KINDS:
            continue
        day = str(act.get("date") or "")[:10]
        cardio_by_day[day] = cardio_by_day.get(day, 0.0) + float(act.get("hours") or 0.0)

    out: list[dict[str, Any]] = []
    for start, end in week_windows(anchor, n_weeks):
        offsets: list[float] = []
        readings: list[float] = []
        hours = 0.0
        for offset in range(WEEK_DAYS):
            key = shift_day_key(start, offset)
            for lb in by_day_weight.get(key, []):
                offsets.append(float(offset))
                readings.append(lb)
            hours += cardio_by_day.get(key, 0.0)
        span = (max(offsets) - min(offsets)) if offsets else 0.0
        rate: float | None = None
        reason: str | None = None
        if len(readings) < MIN_WEIGHINS_PER_WEEK:
            reason = f"{len(readings)} weigh-in(s) in the week against a floor of {MIN_WEIGHINS_PER_WEEK}"
        elif span < MIN_WEEK_SPAN_DAYS:
            reason = f"the week's weigh-ins span {int(span)} day(s) against a floor of {MIN_WEEK_SPAN_DAYS}"
        else:
            fit = _ols(offsets, readings)
            if fit is None:
                reason = "the week's weigh-ins carry no usable span"
            else:
                rate = round(-fit[0] * WEEK_DAYS, 3)  # positive when losing
        out.append(
            {
                "week_start": start,
                "week_end": end,
                "n_weighins": len(readings),
                "span_days": round(span, 1),
                # Absence reported as absence, never as 0 lb (ADR-104).
                "mean_weight_lb": round(sum(readings) / len(readings), 2) if readings else None,
                "rate_lb_wk": rate,
                "unmeasurable_reason": reason,
                "cardio_hr_wk": round(hours, 2),
            }
        )
    return out


def rate_observations(weeks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The weeks that carry a measured rate, as (x=cardio hours, y=rate) rows.

    One window on both sides: a week's rate and the cardio hours it is paired with
    are measured over the SAME seven days, so nothing about the fit borrows volume
    from a week the rate does not cover.
    """
    return [
        {
            "week_start": w["week_start"],
            "week_end": w["week_end"],
            "cardio_hr_wk": float(w["cardio_hr_wk"]),
            "rate_lb_wk": float(w["rate_lb_wk"]),
            "n_weighins": int(w["n_weighins"]),
        }
        for w in weeks or []
        if w.get("rate_lb_wk") is not None
    ]


def measured_week_rate(weeks: list[dict[str, Any]], week_end: str) -> dict[str, Any]:
    """The MEASURED outcome of one week — the grading input, by the same arithmetic.

    Returns {"rate_lb_wk", "cardio_hr_wk", "n_weighins", "measurable", "reason"}. A
    week that cannot be measured returns measurable=False with the reason, and the
    grade that reads it is inconclusive rather than a fabricated zero.
    """
    cur = next((w for w in weeks or [] if w.get("week_end") == week_end), None)
    if cur is None:
        return {
            "measurable": False,
            "reason": f"no weekly record ending {week_end}",
            "rate_lb_wk": None,
            "cardio_hr_wk": None,
            "n_weighins": 0,
        }
    return {
        "week_end": week_end,
        "cardio_hr_wk": cur.get("cardio_hr_wk"),
        "n_weighins": int(cur.get("n_weighins") or 0),
        "rate_lb_wk": cur.get("rate_lb_wk"),
        "measurable": cur.get("rate_lb_wk") is not None,
        "reason": cur.get("unmeasurable_reason"),
    }


def fit_rate_model(
    observations: list[dict[str, Any]],
    min_weeks: int = MIN_FORECAST_WEEKS,
    confidence: float = CONFIDENCE,
) -> dict[str, Any]:
    """OLS of weekly rate on weekly cardio hours + leave-one-out interval and skill.

    Always returns a dict. ``usable`` False carries the ``reason`` verbatim onto the
    declined forecast, so a decline names WHICH floor it failed rather than reading
    as a finding about his history.
    """
    xs = [float(o["cardio_hr_wk"]) for o in observations or []]
    ys = [float(o["rate_lb_wk"]) for o in observations or []]
    n = len(xs)
    base: dict[str, Any] = {"model": MODEL_ID, "n_weeks": n, "confidence": confidence}
    if n < min_weeks:
        base.update(usable=False, reason=f"only {n} complete measurable week(s) of history against a floor of {min_weeks}")
        return base
    fit = _ols(xs, ys)
    if fit is None:
        base.update(usable=False, reason="cardio volume does not vary across the observed weeks — no slope is identifiable")
        return base
    slope, intercept = fit

    loo_res: list[float] = []
    null_res: list[float] = []
    for i in range(n):
        ox = xs[:i] + xs[i + 1 :]
        oy = ys[:i] + ys[i + 1 :]
        f = _ols(ox, oy)
        if f is None:
            continue
        loo_res.append(ys[i] - (f[1] + f[0] * xs[i]))
        null_res.append(ys[i] - sum(oy) / len(oy))
    if len(loo_res) < min_weeks:
        base.update(usable=False, reason=f"only {len(loo_res)} week(s) could be held out and predicted against a floor of {min_weeks}")
        return base

    ordered = sorted(loo_res)
    tail = (1.0 - confidence) / 2.0
    mae = sum(abs(r) for r in loo_res) / len(loo_res)
    null_mae = sum(abs(r) for r in null_res) / len(null_res)
    base.update(
        usable=True,
        reason=None,
        slope_lb_per_cardio_hour=round(slope, 4),
        intercept_lb_wk=round(intercept, 3),
        r=stats_core.pearson_r(xs, ys),
        loo_q_lo=round(_percentile(ordered, tail), 3),
        loo_q_hi=round(_percentile(ordered, 1.0 - tail), 3),
        loo_mae_lb_wk=round(mae, 3),
        null_loo_mae_lb_wk=round(null_mae, 3),
        skill_vs_null=(round(1.0 - mae / null_mae, 3) if null_mae > 0 else None),
        baseline_rate_lb_wk=round(sum(ys) / n, 3),
        cardio_hr_wk_min=round(min(xs), 2),
        cardio_hr_wk_max=round(max(xs), 2),
        cardio_hr_wk_mean=round(sum(xs) / n, 2),
    )
    return base


def build_forecast(
    model: dict[str, Any],
    prescribed_cardio_hr_wk: float | None,
    issued_date: str,
    target_week_start: str,
    target_week_end: str,
    bias_correction_lb_wk: float = 0.0,
    reference_band: str | None = None,
) -> dict[str, Any]:
    """The week's claim: a point + interval on the coming week's lb/wk, or a decline.

    Every returned dict — issued or declined — carries ``n_weeks`` and the stated
    confidence, so no consumer can render a number without its uncertainty and n
    (ADR-105 rule 1).
    """
    out: dict[str, Any] = {
        "record_type": FORECAST_RECORD_TYPE,
        "model": MODEL_ID,
        "issued_date": issued_date,
        "target_week_start": target_week_start,
        "target_week_end": target_week_end,
        "prescribed_cardio_hr_wk": (round(float(prescribed_cardio_hr_wk), 2) if prescribed_cardio_hr_wk is not None else None),
        "reference_band": reference_band,
        "confidence": model.get("confidence", CONFIDENCE),
        "n_weeks": int(model.get("n_weeks") or 0),
        "intake_comparable": False,
        "intake_note": INTAKE_NOTE,
        "basis_note": BASIS_NOTE,
    }
    if prescribed_cardio_hr_wk is None:
        # No weight-matched proven period means there is no volume to commit to.
        # Saying so is the result; substituting the current band would hand back
        # the very weeks he is trying to escape as this week's target (#3709).
        reason = "no weight-matched losing-phase period is available, so there is no prescribed volume to forecast against"
        out.update(
            issued=False,
            declined=True,
            declined_reason=reason,
            statement=f"No forecast issued for the week ending {target_week_end}: {reason}. Declined rather than guessed.",
        )
        return out

    if not model.get("usable"):
        out.update(
            issued=False,
            declined=True,
            declined_reason=model.get("reason") or "no usable weekly history",
            statement=(
                f"No forecast issued for the week ending {target_week_end}: "
                f"{model.get('reason') or 'no usable weekly history'}. Declined rather than guessed."
            ),
        )
        return out

    x0 = float(prescribed_cardio_hr_wk)
    ceiling = float(model["cardio_hr_wk_max"]) * EXTRAPOLATION_CAP
    if x0 > ceiling:
        out.update(
            issued=False,
            declined=True,
            declined_reason=(
                f"the prescribed {round(x0, 2)} cardio hr/wk is more than "
                f"{int((EXTRAPOLATION_CAP - 1) * 100)}% above the most he has logged in a week "
                f"({model['cardio_hr_wk_max']}); the model has never seen a week there"
            ),
            statement=(
                f"No forecast issued for the week ending {target_week_end}: the prescribed "
                f"{round(x0, 2)} cardio hr/wk is outside the range the line was fitted over "
                f"({model['cardio_hr_wk_min']}..{model['cardio_hr_wk_max']} hr/wk). Declined rather than extrapolated."
            ),
        )
        return out

    bias = float(bias_correction_lb_wk or 0.0)
    point = float(model["intercept_lb_wk"]) + float(model["slope_lb_per_cardio_hour"]) * x0 - bias
    lo = point + float(model["loo_q_lo"])
    hi = point + float(model["loo_q_hi"])
    out.update(
        issued=True,
        declined=False,
        declined_reason=None,
        point_lb_wk=round(point, 2),
        lo_lb_wk=round(lo, 2),
        hi_lb_wk=round(hi, 2),
        slope_lb_per_cardio_hour=model["slope_lb_per_cardio_hour"],
        intercept_lb_wk=model["intercept_lb_wk"],
        bias_correction_lb_wk=round(bias, 3),
        null_point_lb_wk=model["baseline_rate_lb_wk"],
        skill_vs_null=model.get("skill_vs_null"),
        loo_mae_lb_wk=model.get("loo_mae_lb_wk"),
        r=model.get("r"),
        cardio_hr_wk_observed_max=model["cardio_hr_wk_max"],
        statement=(
            f"Week ending {target_week_end}: at {round(x0, 2)} cardio hr/wk this plan expects "
            f"{round(point, 2)} lb/wk "
            f"({int(round(float(out['confidence']) * 100))}% interval {round(lo, 2)}..{round(hi, 2)}, "
            f"n={model['n_weeks']} weeks). {BASIS_NOTE} {INTAKE_NOTE}"
        ),
    )
    return out


def grade_forecast(
    forecast: dict[str, Any],
    measured: dict[str, Any],
) -> dict[str, Any]:
    """Grade an issued forecast against the measured week. `measured` is measured_week_rate's output."""
    out: dict[str, Any] = {
        "model": forecast.get("model", MODEL_ID),
        "target_week_end": forecast.get("target_week_end"),
        "issued_date": forecast.get("issued_date"),
        "confidence": forecast.get("confidence", CONFIDENCE),
        "n_weeks": forecast.get("n_weeks"),
        "prescribed_cardio_hr_wk": forecast.get("prescribed_cardio_hr_wk"),
        "delivered_cardio_hr_wk": measured.get("cardio_hr_wk"),
        "n_weighins": measured.get("n_weighins"),
        "covered": None,
        "actual_lb_wk": measured.get("rate_lb_wk"),
    }
    prescribed = forecast.get("prescribed_cardio_hr_wk")
    delivered = measured.get("cardio_hr_wk")
    out["adherence"] = round(float(delivered) / float(prescribed), 3) if (prescribed not in (None, 0) and delivered is not None) else None

    if not forecast.get("issued"):
        out.update(status="not_issued", reason=forecast.get("declined_reason"))
        return out
    if not measured.get("measurable"):
        out.update(status="inconclusive", reason=measured.get("reason") or "the week could not be measured")
        return out

    actual = float(measured["rate_lb_wk"])
    point = float(forecast["point_lb_wk"])
    lo = float(forecast["lo_lb_wk"])
    hi = float(forecast["hi_lb_wk"])
    null_point = float(forecast.get("null_point_lb_wk") or 0.0)
    abs_err = abs(actual - point)
    null_abs_err = abs(actual - null_point)
    out.update(
        status="graded",
        reason=None,
        covered=bool(lo <= actual <= hi),
        point_lb_wk=round(point, 2),
        lo_lb_wk=round(lo, 2),
        hi_lb_wk=round(hi, 2),
        abs_error_lb_wk=round(abs_err, 3),
        signed_error_lb_wk=round(point - actual, 3),
        null_point_lb_wk=round(null_point, 2),
        null_abs_error_lb_wk=round(null_abs_err, 3),
        beats_null=bool(abs_err < null_abs_err),
        direction=("inside" if lo <= actual <= hi else ("under" if actual < lo else "over")),
    )
    return out


def bias_correction(grades: list[dict[str, Any]], window: int = BIAS_WINDOW) -> float:
    """Mean signed error over the most recent graded weeks — positive = over-predicts loss.

    This is the whole of "a missed forecast feeds the next prescription" on the
    MODEL side: the next point estimate is shifted by the bias the last few weeks
    actually showed, rather than the line being re-fitted by hand.
    """
    signed = [
        float(g["signed_error_lb_wk"]) for g in grades or [] if g.get("status") == "graded" and g.get("signed_error_lb_wk") is not None
    ]
    if not signed:
        return 0.0
    tail = signed[-window:]
    return round(sum(tail) / len(tail), 3)


def derive_adjustment(
    forecast: dict[str, Any],
    grade: dict[str, Any],
    proven_cardio_hr_wk: float | None = None,
) -> dict[str, Any]:
    """Next week's volume target, derived from this week's miss. Never re-authored.

    The order of the branches IS the rule: adherence is asked before accuracy,
    because a week that did not run the plan did not test the model, and raising a
    target nobody reached is how a prescription becomes decoration.
    """
    prescribed = float(forecast.get("prescribed_cardio_hr_wk") or 0.0)
    delivered = grade.get("delivered_cardio_hr_wk")
    delivered_f = float(delivered) if delivered is not None else None
    ramp_ceiling = round(delivered_f * (1.0 + RAMP_CAP), 2) if delivered_f is not None else None
    out: dict[str, Any] = {
        "prescribed_cardio_hr_wk": round(prescribed, 2),
        "delivered_cardio_hr_wk": delivered_f,
        "adherence": grade.get("adherence"),
        "ramp_cap_pct": int(RAMP_CAP * 100),
        "ramp_ceiling_hr_wk": ramp_ceiling,
        "bias_lb_wk": grade.get("signed_error_lb_wk"),
        "ramp_capped": False,
    }

    if grade.get("status") != "graded":
        out.update(
            basis="not_graded",
            next_cardio_hr_wk=round(prescribed, 2),
            delta_hr_wk=0.0,
            derivation=(
                f"The week ending {grade.get('target_week_end')} could not be graded "
                f"({grade.get('reason') or 'no verdict'}), so the target is carried unchanged. "
                "An ungraded week moves nothing."
            ),
        )
        return out

    adherence = out["adherence"]
    if adherence is not None and float(adherence) < ADHERENCE_FLOOR and ramp_ceiling is not None:
        nxt = round(min(prescribed, ramp_ceiling), 2)
        out.update(
            basis="adherence_shortfall",
            next_cardio_hr_wk=nxt,
            delta_hr_wk=round(nxt - prescribed, 2),
            ramp_capped=bool(ramp_ceiling < prescribed),
            derivation=(
                f"Delivered {delivered_f} of {round(prescribed, 2)} cardio hr/wk "
                f"({int(float(adherence) * 100)}% of the plan, below the {int(ADHERENCE_FLOOR * 100)}% floor), so the week "
                f"did not test the forecast. The next target is derived from what was delivered — "
                f"{delivered_f} x {1 + RAMP_CAP:.2f} = {ramp_ceiling} hr/wk — not re-issued unchanged."
            ),
        )
        return out

    signed = float(grade.get("signed_error_lb_wk") or 0.0)
    slope = float(forecast.get("slope_lb_per_cardio_hour") or 0.0)

    if grade.get("covered"):
        target = prescribed if proven_cardio_hr_wk is None else max(prescribed, float(proven_cardio_hr_wk))
        nxt_raw = min(target, ramp_ceiling) if ramp_ceiling is not None else target
        nxt = round(max(prescribed, nxt_raw), 2)
        out.update(
            basis="on_target",
            next_cardio_hr_wk=nxt,
            delta_hr_wk=round(nxt - prescribed, 2),
            ramp_capped=bool(ramp_ceiling is not None and target > ramp_ceiling),
            derivation=(
                f"Actual {grade.get('actual_lb_wk')} lb/wk landed inside the "
                f"{round(float(grade.get('lo_lb_wk') or 0.0), 2)}..{round(float(grade.get('hi_lb_wk') or 0.0), 2)} interval. "
                f"The plan is doing what it said, so the target advances toward the proven volume "
                f"({proven_cardio_hr_wk if proven_cardio_hr_wk is not None else 'none available'}) "
                f"within the {int(RAMP_CAP * 100)}%/wk ramp."
            ),
        )
        return out

    if grade.get("direction") == "over":
        out.update(
            basis="model_under_predicted",
            next_cardio_hr_wk=round(prescribed, 2),
            delta_hr_wk=0.0,
            derivation=(
                f"Actual {grade.get('actual_lb_wk')} lb/wk came in ABOVE the interval "
                f"(expected {grade.get('point_lb_wk')}). Volume holds — nothing is asked for that the week "
                f"already beat — and the {abs(signed)} lb/wk miss is carried as a bias correction into the "
                "next forecast."
            ),
        )
        return out

    # Under-performed on a delivered week: convert the miss into hours via the slope.
    if slope <= 0 or signed <= 0:
        out.update(
            basis="model_over_predicted_no_lever",
            next_cardio_hr_wk=round(prescribed, 2),
            delta_hr_wk=0.0,
            derivation=(
                f"Actual {grade.get('actual_lb_wk')} lb/wk came in below the interval, but the fitted slope is "
                f"{slope} lb per cardio hour — the miss cannot be converted into a volume change without "
                "inventing a lever. Carried as a bias correction only."
            ),
        )
        return out

    extra = signed / slope
    raw = prescribed + extra
    nxt = round(min(raw, ramp_ceiling), 2) if ramp_ceiling is not None else round(raw, 2)
    out.update(
        basis="model_over_predicted",
        next_cardio_hr_wk=nxt,
        delta_hr_wk=round(nxt - prescribed, 2),
        ramp_capped=bool(ramp_ceiling is not None and raw > ramp_ceiling),
        derivation=(
            f"Actual {grade.get('actual_lb_wk')} lb/wk came in below the interval, a {round(signed, 2)} lb/wk miss on a "
            f"week that ran the plan. At {slope} lb per cardio hour that is {round(extra, 2)} more hours "
            f"({round(prescribed, 2)} + {round(extra, 2)} = {round(raw, 2)}), "
            f"{'capped by' if (ramp_ceiling is not None and raw > ramp_ceiling) else 'inside'} the "
            f"{int(RAMP_CAP * 100)}%/wk ramp off the {delivered_f} delivered."
        ),
    )
    return out


# ── the track record ───────────────────────────────────────────────────────────


def track_record(resolutions: list[dict[str, Any]], min_n: int = MIN_TRACK_RECORD) -> dict[str, Any]:
    """ "Is the coaching actually working" — from the graded rows, or an honest no-answer.

    `resolutions` are the ``forecast_resolution`` rows this module's producer writes
    into the shared CALIB# ledger. Scored with the platform's own instruments
    (`calibration_core` for the pairs, `stats_core` for Brier and the Wilson
    interval) so this number cannot diverge from the calibration scoreboard's.
    """
    from experiment import calibration_core

    # Filtered on the model id as well as the row type: the CALIB# ledger is SHARED
    # (forecast_engine_lambda writes daily EWMA resolutions into the same partition),
    # so a reader handed the whole slice must not fold another model's coverage into
    # this one's track record.
    rows = [
        r
        for r in resolutions or []
        if r.get("record_type") == RESOLUTION_RECORD_TYPE and r.get("model") == MODEL_ID and r.get("covered") is not None
    ]
    out: dict[str, Any] = {
        "n_graded": len(rows),
        "min_for_verdict": min_n,
        "answerable": False,
        "confidence": CONFIDENCE,
        "model": MODEL_ID,
    }
    if not rows:
        out["verdict"] = "No weekly prescription forecast has been graded yet — there is nothing to answer with."
        return out

    covered = [r for r in rows if r.get("covered")]
    n, k = len(rows), len(covered)
    lo, hi = stats_core.wilson_interval(k, n)
    errs = [float(r["abs_error_lb_wk"]) for r in rows if r.get("abs_error_lb_wk") is not None]
    null_errs = [float(r["null_abs_error_lb_wk"]) for r in rows if r.get("null_abs_error_lb_wk") is not None]
    mae = round(sum(errs) / len(errs), 3) if errs else None
    null_mae = round(sum(null_errs) / len(null_errs), 3) if null_errs else None
    out.update(
        n_covered=k,
        coverage_pct=round(100.0 * k / n, 1),
        coverage_ci_pct=[round(100.0 * lo, 1), round(100.0 * hi, 1)] if lo is not None and hi is not None else None,
        nominal_coverage_pct=round(CONFIDENCE * 100, 1),
        mae_lb_wk=mae,
        null_mae_lb_wk=null_mae,
        beats_null=(bool(mae < null_mae) if (mae is not None and null_mae is not None) else None),
        brier=(
            round(b, 4) if (b := stats_core.brier_score(calibration_core.pairs_from_forecast_resolution_rows(rows))) is not None else None
        ),
        answerable=bool(n >= min_n),
    )
    if n < min_n:
        out["verdict"] = (
            f"Not answerable yet: {n} graded week(s) against a floor of {min_n}. "
            f"{k} of {n} landed inside the stated interval, which at this n says nothing."
        )
        return out
    covers = "covers" if lo is not None and lo <= CONFIDENCE <= (hi if hi is not None else 1.0) else "does not cover"
    beat = "beats" if out.get("beats_null") else "does not beat"
    out["verdict"] = (
        f"{k} of {n} weekly forecasts landed inside their stated {int(CONFIDENCE * 100)}% interval "
        f"({out['coverage_pct']}%, 95% CI {out['coverage_ci_pct']}), which {covers} the nominal "
        f"{int(CONFIDENCE * 100)}%. Mean absolute error {mae} lb/wk against {null_mae} for the "
        f"no-model baseline — the prescription {beat} saying nothing."
    )
    return out
