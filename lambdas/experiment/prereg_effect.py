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

from experiment import experiment_gates  # the ONE provenance vocabulary (#3621/#4003)

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


# ── The provenance FACET (#3552, reusing the #3621/#4003 vocabulary) ──────────
#
# `experiment_gates.gate_provenance()` returns `{value, kind, source}` for every arming
# threshold the platform serves, and its own docstring names THIS module's `derived_from`
# block as the shape a `personal_derivation`'s `source` must arrive in ("reusing the
# shape #3552 shipped rather than minting a second one for the same idea"). A
# pre-registered `min_effect` is the same kind of object — a number a reader is asked to
# trust — so it ships in that facet, not in a third spelling of it.
#
# The facet LABELS a number; it never upgrades one. A bar that was declared by design, or
# proposed by a model, stays exactly the number it was — the facet is what lets a reader
# tell it apart from a derived one, which is the whole defect this issue was filed about
# (0.1 lb read as a pre-registered threshold and was ~3% of the day-to-day noise).
# The phrase the per-arm floor is stated in. Checked before appending so a criterion that
# already names the floor (the seeder's sentence does) is never restated.
ARM_FLOOR_PHRASE = "days in each arm"


def effect_provenance(derived: dict) -> dict:
    """The `{value, kind, source}` facet for a DERIVED bar.

    `source` is the `derived_from` block verbatim — the shape
    `experiment_gates.gate_provenance()` documents for `personal_derivation`. Copied on
    the way out so a payload consumer cannot mutate the artifact's own block.
    """
    return {
        "value": derived["min_effect"],
        "kind": experiment_gates.PERSONAL_DERIVATION,
        "source": dict(derived["derived_from"]),
    }


def noise_scale_note(min_effect, values, *, metric: str, window_days: int, unit: str = "") -> str:
    """The "measured against the subject's own series" clause — the scale a DECLARED bar sits on.

    This does not derive anything: the bar stays the number that was declared. It states
    what that number is worth against the subject's own per-observation noise, which is
    the one fact the literal thresholds never carried. Returns "" when the series cannot
    support a variance estimate — an honest silence, never a guessed ratio (ADR-104).
    """
    est = sigma_from_successive_differences(values)
    if est is None:
        return ""
    sigma, n_pairs = est
    if sigma <= 0:
        return ""
    unit_str = f" {unit}".rstrip()
    ratio = round(float(min_effect) / sigma, 2)
    return (
        f" Measured against the subject's own series for SCALE (this is not a derivation of the bar): "
        f"SD {round(sigma, 3)}{unit_str} over n={n_pairs} successive {metric} readings in the trailing "
        f"{window_days} days, so the declared bar is {ratio}x that per-observation noise scale."
    )


def declared_effect_provenance(
    min_effect, *, kind: str, citation: str, values=None, metric: str = "", window_days=None, unit: str = ""
) -> dict:
    """The facet for a bar that was NOT derived — declared by design, or model-proposed.

    `kind` is `experiment_gates.POPULATION_CONSTANT` (an adopted design convention) or
    `experiment_gates.MODEL_PROPOSED` (the number arrived with an LLM-generated
    hypothesis). Either way `source` is a citation STRING, matching what
    `gate_provenance()` carries for a non-derived threshold — with the measured noise
    scale appended when the outcome metric's own series can supply one.
    """
    source = citation
    if values and window_days:
        source += noise_scale_note(min_effect, values, metric=metric, window_days=window_days, unit=unit)
    return {"value": min_effect, "kind": kind, "source": source}


def arm_floor_clause(min_days_per_arm: int) -> str:
    """The sentence that puts the checker's per-arm n floor on the public artifact."""
    return (
        f" No verdict is possible below {min_days_per_arm} {ARM_FLOOR_PHRASE} — the deterministic check "
        "stamps both arm counts, and they are read alongside any verdict, never the verdict alone."
    )


def stamp_spec_provenance(
    hyp: dict,
    *,
    min_days_per_arm: int,
    fallback_kind: str,
    fallback_citation: str,
    outcome_series=None,
    window_days=None,
    unit: str = "",
) -> dict:
    """Every stored hypothesis leaves here with its bar LABELLED and its n floor stated.

    #3552 fixed the two genesis hypotheses at the seeder. It did not reach the other two
    writers — the standing diary-intervention hypothesis (#1843) and the weekly LLM
    generator — so the ONE hypothesis live on `/api/hypotheses` still served
    `min_effect: 0.05` with no derivation, no arm floor, and a `confirmation_criteria`
    that named no n. This is the chokepoint that closes the set.

    Additive and idempotent: an existing facet, an existing `min_days_per_arm` and a
    criterion that already names the floor are all left exactly as they are, so the
    seeder's derived specs pass through untouched. Returns a new dict; never mutates the
    caller's.
    """
    spec = hyp.get("test_spec")
    if not isinstance(spec, dict):
        return hyp
    spec = dict(spec)
    out = dict(hyp)
    out["test_spec"] = spec

    spec.setdefault("min_days_per_arm", min_days_per_arm)

    if "min_effect" in spec and "min_effect_provenance" not in spec:
        derivation = spec.get("min_effect_derivation")
        if isinstance(derivation, dict):
            # The seeder's already-derived block, expressed in the shared facet shape.
            spec["min_effect_provenance"] = effect_provenance({"min_effect": spec["min_effect"], "derived_from": derivation})
        else:
            spec["min_effect_provenance"] = declared_effect_provenance(
                spec["min_effect"],
                kind=fallback_kind,
                citation=fallback_citation,
                values=outcome_series,
                metric=str(spec.get("outcome_metric") or ""),
                window_days=window_days,
                unit=unit,
            )

    criteria = out.get("confirmation_criteria")
    if isinstance(criteria, str) and criteria.strip() and ARM_FLOOR_PHRASE not in criteria:
        out["confirmation_criteria"] = criteria.rstrip() + arm_floor_clause(min_days_per_arm)
    return out
