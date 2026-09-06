"""lambdas/experiment/prereg_effect.py — the pre-registered `min_effect` derived from
the subject's OWN measured variance (#3552, ADR-105 rule: thresholds from personal
variance).

THE DEFECT
──────────
`deploy/seed_genesis_preregistration.build_hypotheses` wrote `"min_effect": 0.1` (lbs)
and `"min_effect": 3` (recovery points) as bare literals, in the same specs whose
kcal/steps/start-weight numbers are goal-derived. Measured against the subject's real
series, 0.1 lb is ~3% of day-to-day weight noise and 3 points is ~14% of the recovery
SD — thresholds BELOW the noise floor, so "confirmed" would have meant nothing. And the
public artifact carried the number with no SD, no n and no window: a reader could not
tell whether the bar was demanding or decorative.

THE RULE
────────
``min_effect = round(EFFECT_SD_FRACTION * sigma, 2)`` where ``sigma`` is estimated from
SUCCESSIVE DIFFERENCES of the metric's own trailing readings:

    sigma_hat = SD(successive differences) / sqrt(2)

That is the standard mean-successive-difference estimator. It is used here rather than
the plain level SD because both genesis hypotheses run against a metric with a deliberate
TREND (weight under a 1,500 kcal deficit): the level SD of a trending series measures the
trend, not the noise a between-arm comparison has to beat, and would inflate the bar for
the very intervention the hypothesis is testing. Differencing removes the trend; the
1/sqrt(2) recovers the per-observation scale that the difference operator doubles.

``EFFECT_SD_FRACTION = 0.5`` is Cohen's medium effect on the subject's own noise scale —
stated once, here, rather than chosen per hypothesis.

WHEN IT CANNOT BE DERIVED
─────────────────────────
Under ``MIN_PAIRS`` usable differences there is no variance measurement, and this module
returns None. The seeder then REFUSES to freeze rather than falling back to a literal:
a pre-registration is sealed by content hash the instant it is written (#1378) and can
never be corrected, so an underived threshold in it is permanent. "Could not derive" is
a result; substituting a number nobody priced is the thing this issue is about.
"""

from __future__ import annotations

import math
import statistics

# Cohen's medium effect, expressed against the subject's own per-observation SD.
EFFECT_SD_FRACTION = 0.5
# Fewer usable successive differences than this and the SD is not a measurement.
MIN_PAIRS = 5
# The trailing window the derivation reads. Wide enough that a sparsely-logged metric
# (weight: 14 weigh-ins in 65 days at the time of writing) still clears MIN_PAIRS.
DEFAULT_WINDOW_DAYS = 90


def sigma_from_successive_differences(values) -> tuple[float, int] | None:
    """(sigma_hat, n_pairs) from a series, or None when there are too few pairs.

    `values` is oldest-first. Non-finite entries are dropped rather than silently
    treated as zero.
    """
    series = []
    for v in values or []:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            series.append(f)
    diffs = [b - a for a, b in zip(series, series[1:])]
    if len(diffs) < MIN_PAIRS:
        return None
    sd_diff = statistics.stdev(diffs)
    return sd_diff / math.sqrt(2), len(diffs)


def derive_min_effect(values, *, metric: str, window_days: int = DEFAULT_WINDOW_DAYS, unit: str = "") -> dict | None:
    """The pre-registered minimum effect for `metric`, with its whole derivation.

    Returns ``{"min_effect": float, "derived_from": {...}}`` — the shape the frozen
    artifact carries so the public number travels with the SD, n and window it came
    from — or None when the series cannot support a variance estimate.
    """
    est = sigma_from_successive_differences(values)
    if est is None:
        return None
    sigma, n_pairs = est
    min_effect = round(EFFECT_SD_FRACTION * sigma, 2)
    if min_effect <= 0:
        # A zero-variance series would pre-register a bar of 0, i.e. "any difference at
        # all confirms" — the same vacuous threshold in the other direction.
        return None
    return {
        "min_effect": min_effect,
        "derived_from": {
            "metric": metric,
            "unit": unit,
            "rule": f"{EFFECT_SD_FRACTION} x SD of successive differences / sqrt(2) (mean-successive-difference estimator)",
            "sd": round(sigma, 3),
            "n": n_pairs,
            "window_days": window_days,
        },
    }


def criteria_sentence(
    min_effect: float, unit: str, direction_word: str, window_days: int, derived_from: dict, min_days_per_arm: int
) -> str:
    """The public `confirmation_criteria` line: the bar, its derivation, and the n floor.

    The n floor was previously invisible to readers — it lived only in
    `hypothesis_engine_lambda.MIN_DAYS_PER_ARM` — so the artifact stated a threshold
    without stating how much data had to exist before it could be applied.
    """
    unit_str = f" {unit}".rstrip()
    return (
        f"Mean next-day {derived_from['metric']} at least {min_effect}{unit_str} {direction_word} on condition days "
        f"within {window_days} days, 95% CI excluding 0, with at least {min_days_per_arm} days in each arm. "
        f"The {min_effect}{unit_str} bar is derived, not chosen: {derived_from['rule']}, "
        f"SD {derived_from['sd']}{unit_str} over n={derived_from['n']} successive readings "
        f"in the trailing {derived_from['window_days']} days."
    )
