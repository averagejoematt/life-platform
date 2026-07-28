"""lambdas/glycemic.py — deterministic glycemic-variability features (#1406).

Pure Python, no numpy, no LLM (ADR-062/105): CGM variability is computed in code
and the model never does the math. Functions operate either on a day's ordered
list of glucose readings (mg/dL) or on an already-stored daily aggregate
(mean/sd). Every function is a plain arithmetic transform, unit-tested against
hand-computed fixtures in ``tests/test_glycemic.py``.

Behavioral-absence semantics (ADR-104): a day with too few readings, a
degenerate (zero-mean) series, or no qualifying excursion returns ``None`` —
measured absence, never a fabricated 0. The caller stores the field only when a
real value exists, so an uninstrumented day stays honestly blank.

Metrics
-------
coefficient_of_variation(readings)     %CV = 100 * sd / mean over the day's
                                       readings. Monnier's primary glycemic-
                                       variability index (%CV < 36 = "stable").
cv_from_mean_sd(mean, sd)              same %CV, from a stored daily aggregate
                                       (the DDB blood_glucose_avg / _std_dev
                                       fields already carry mean + population sd).
time_in_range_pct(readings, lo, hi)    % of readings within [lo, hi]. ADA
                                       Time-in-Range uses 70-180 mg/dL; Attia
                                       "optimal" uses 70-120.
mage(readings, sd_multiplier=1.0)      Mean Amplitude of Glycemic Excursions
                                       (Service 1970): the mean amplitude of the
                                       peak-to-nadir excursions whose size
                                       exceeds ``sd_multiplier`` * the day's SD.

SD convention: population SD (divide by n), matching the CGM daily-aggregate
std_dev the ingestion Lambda already writes, so ``cv_from_mean_sd`` reproduces
``coefficient_of_variation`` to rounding on the same readings.
"""

import math

# ADA Time-in-Range default band (mg/dL).
TIR_LOW_DEFAULT = 70.0
TIR_HIGH_DEFAULT = 180.0


def _clean(readings):
    """Coerce an iterable of readings to a list of floats, dropping non-numeric
    / None entries. Order is preserved (MAGE needs the time order the caller
    passed in)."""
    out = []
    for r in readings or []:
        try:
            out.append(float(r))
        except (TypeError, ValueError):
            continue
    return out


def _mean(vals):
    return sum(vals) / len(vals)


def _pop_sd(vals, mean=None):
    """Population standard deviation (÷ n) — matches the ingestion aggregate."""
    if len(vals) < 2:
        return 0.0
    m = _mean(vals) if mean is None else mean
    return math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))


def coefficient_of_variation(readings, ndigits=2):
    """%CV = 100 * population_sd / mean over the day's readings.

    Returns None when < 2 readings or the mean is non-positive (a zero/negative
    mean CV is undefined — measured absence, not 0)."""
    vals = _clean(readings)
    if len(vals) < 2:
        return None
    m = _mean(vals)
    if m <= 0:
        return None
    cv = 100.0 * _pop_sd(vals, m) / m
    return round(cv, ndigits)


def cv_from_mean_sd(mean, sd, ndigits=2):
    """%CV from a stored daily aggregate (mean + population sd).

    Lets the weekly correlation engine derive glycemic variability over
    historical days that only carry the DDB blood_glucose_avg / _std_dev
    aggregate, with no S3 intraday fetch. Returns None on missing inputs or a
    non-positive mean."""
    try:
        m = float(mean)
        s = float(sd)
    except (TypeError, ValueError):
        return None
    if m <= 0:
        return None
    return round(100.0 * s / m, ndigits)


def time_in_range_pct(readings, lo=TIR_LOW_DEFAULT, hi=TIR_HIGH_DEFAULT, ndigits=1):
    """% of readings within the inclusive [lo, hi] band. Returns None on no
    readings (an uninstrumented day has no TIR, ADR-104)."""
    vals = _clean(readings)
    if not vals:
        return None
    in_band = sum(1 for v in vals if lo <= v <= hi)
    return round(in_band / len(vals) * 100.0, ndigits)


def _extrema(vals):
    """Local extrema of a 1-D series, endpoints included, flats collapsed.

    A point is a turning point when the sign of the change flips across it. Runs
    of equal values are collapsed first so a plateau never fakes an excursion.
    Returns the list of extreme VALUES in series order."""
    # Collapse consecutive duplicates.
    seq = [vals[0]]
    for v in vals[1:]:
        if v != seq[-1]:
            seq.append(v)
    if len(seq) <= 2:
        return seq
    ext = [seq[0]]
    for i in range(1, len(seq) - 1):
        prev, cur, nxt = seq[i - 1], seq[i], seq[i + 1]
        if (cur - prev) * (nxt - cur) < 0:  # sign flip → local extremum
            ext.append(cur)
    ext.append(seq[-1])
    return ext


def mage(readings, sd_multiplier=1.0, ndigits=1):
    """Mean Amplitude of Glycemic Excursions (Service 1970), deterministic.

    Turning points are the local extrema of the ordered readings; an excursion
    is the swing between consecutive extrema. Only excursions whose absolute
    amplitude exceeds ``sd_multiplier`` * the day's population SD count. MAGE is
    the mean of those qualifying amplitudes.

    Requires the readings to already be in time order. Returns None when there
    are < 3 readings, the SD is 0 (a flat day has no excursions), or no
    excursion clears the threshold — all honest measured-absence, never 0."""
    vals = _clean(readings)
    if len(vals) < 3:
        return None
    sd = _pop_sd(vals)
    if sd <= 0:
        return None
    threshold = sd_multiplier * sd
    ext = _extrema(vals)
    amplitudes = [abs(ext[i + 1] - ext[i]) for i in range(len(ext) - 1)]
    qualifying = [a for a in amplitudes if a > threshold]
    if not qualifying:
        return None
    return round(sum(qualifying) / len(qualifying), ndigits)
