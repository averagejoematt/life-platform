"""Experiment instrument gates — the ONE registry of arming thresholds (#1371).

Every "not enough data yet" decision an engine makes (correlation interpretation
floors, hypothesis-generation minimums, coupling floors) is defined HERE, and the
engines import their gates from this module. The site API serves the same values
inside its shaped-empty payloads, so a cold-start zero-state can render the real
trigger ("first correlations at n≥10 — currently 3/10") and can structurally
never drift from the engine that enforces it (ADR-104: computed, never authored).

Adding a threshold to an engine? Define it here and import it there — a test
(tests/test_experiment_gates.py) asserts the engines' module attributes are THIS
module's objects, so a re-hardcoded literal reds CI.

PROVENANCE (#3621 box 3, ADR-105)
─────────────────────────────────
Every threshold below also carries a ``{value, kind, source}`` facet in ``_PROVENANCE``,
read through ``gate_provenance()`` and served inside the same zero-state payloads as the
numbers themselves. Two kinds are allowed on a threshold:

  * ``population_constant`` — a general statistical floor or an adopted convention.
    ``source`` is a CITATION STRING naming where the number actually came from.
  * ``personal_derivation`` — derived from the subject's own measured variance.
    ``source`` is the #3552 ``derived_from`` block: ``{metric, sd, n, window_days}``
    (see ``lambdas/experiment/prereg_effect.py``). That spelling is deliberate — reusing
    the shape #3552 shipped rather than minting a second one for the same idea.

**Today every one of them is ``population_constant``, and that is the honest answer, not a
placeholder.** ADR-105's bar — thresholds from personal variance — is NOT met by this
registry. What the prose comments carried (an internal review persona, a method name, a
module reference) is neither a derivation nor a labelled constant, so the facet does not
UPGRADE these numbers; it LABELS them, so a reader can tell an adopted convention from a
measurement. The only personally-derived thresholds on the platform today are #3552's two
hypothesis ``min_effect``s, and they live in ``prereg_effect.py``, not here. Re-deriving
these nine against Matthew's own series is separate, measurable work — it needs a trailing
series per gated quantity, which is the same thing a short cycle cannot supply.

``tests/test_gate_threshold_provenance_3621.py`` AST-sweeps this module: a bare new
module-level numeric literal with no facet reds CI.

A third kind, ``measurement``, appears ONLY on the ``current_n`` a payload carries. It is
not a threshold — it is the caller's count at request time — and it is labelled rather
than served as a bare integer for the same reason the thresholds are.
"""

# ── Correlation engine (weekly_correlation_compute_lambda) ────────────────────
# Below this many overlapping days a pair has no r at all (stats_core min_n).
CORRELATION_MIN_N = 10
# Interpretation floors (Henning, R9): r on small n is noisy — a label must be
# backed by sample size, or it downgrades.
CORRELATION_INTERP_N = {
    "strong": 50,  # |r| >= 0.6 AND n >= 50
    "moderate": 30,  # |r| >= 0.4 AND n >= 30
    "weak": 10,  # |r| >= 0.2 AND n >= 10
}

# ── Hypothesis engine (hypothesis_engine_lambda, AI-4/#530) ───────────────────
HYPOTHESIS_MIN_DATA_DAYS = 10  # >= this many complete days before generating
HYPOTHESIS_MIN_METRICS_PER_DAY = 5  # a "complete" day has >= 5 non-null metrics
HYPOTHESIS_MIN_SAMPLE_DAYS_FOR_CHECK = 7  # data days since creation before evaluating
HYPOTHESIS_MIN_DAYS_PER_ARM = 5  # each arm needs 5+ days (stats_core bootstrap floor)

# ── Pillar-coupling matrix (site_api_intelligence) ────────────────────────────
COUPLING_MIN_N = 6  # a pair needs >= this many co-present days or it is omitted


# ── Felt-reality calibration (site_api_data.handle_character_calibration, #1409) ─
# Below this many probe-week pairs a pillar has no r at all — the card renders
# the honest "uncalibrated (n=X)" state with the arming trigger instead. The
# floor follows stats_core.pearson_r's noise argument: Fisher CI needs n-3 > 0
# and r on fewer than 5 weekly pairs is coin-flip territory.
FELT_CALIBRATION_MIN_WEEKS = 5
# Below this the CONFIDENCE GRAMMAR downgrades: r renders as a point estimate
# only — never a fabricated band (ADR-105 rule 1).
FELT_CALIBRATION_CI_MIN_WEEKS = 8


# ── The provenance facets (#3621 box 3) ───────────────────────────────────────
POPULATION_CONSTANT = "population_constant"
PERSONAL_DERIVATION = "personal_derivation"
MEASUREMENT = "measurement"
THRESHOLD_KINDS = (POPULATION_CONSTANT, PERSONAL_DERIVATION)

# Keyed by the module-level NAME, so the completeness sweep can compare this registry
# against the module's own literals. The `value` is deliberately NOT copied in here — it
# is read off the live attribute by `gate_provenance()`, so a facet cannot drift from the
# number its engine enforces (the #1371 rule, applied to provenance).
_PROVENANCE: dict[str, dict] = {
    "CORRELATION_MIN_N": {
        "kind": POPULATION_CONSTANT,
        "source": (
            "common/stats_core.pearson_r's own min_n floor — the general small-sample convention that a "
            "Pearson r under ~10 paired observations is dominated by sampling noise (Fisher's z CI needs "
            "n-3 > 0 to exist at all). Adopted, not derived from Matthew's series."
        ),
    },
    "CORRELATION_INTERP_N": {
        "kind": POPULATION_CONSTANT,
        "source": (
            "Internal review R9 (reviewer persona 'Henning'), 2026 — the conventional |r| label bands "
            "(weak 0.2 / moderate 0.4 / strong 0.6), each paired with an n floor so a label is backed by "
            "sample size. A convention this platform adopted in review: there is no external citation "
            "behind the specific 10/30/50 n floors and no personal derivation."
        ),
    },
    "HYPOTHESIS_MIN_DATA_DAYS": {
        "kind": POPULATION_CONSTANT,
        "source": (
            "AI-4 / #530 design floor: the generator does not run until ten complete days exist, so a "
            "hypothesis is never proposed against a window too short to have shown a pattern. A design "
            "convention chosen at build time, not a power calculation on Matthew's variance."
        ),
    },
    "HYPOTHESIS_MIN_METRICS_PER_DAY": {
        "kind": POPULATION_CONSTANT,
        "source": (
            "AI-4 / #530 definition of a 'complete' day: at least five non-null metrics. A completeness "
            "convention for this platform's own ingest surface, not a statistical constant."
        ),
    },
    "HYPOTHESIS_MIN_SAMPLE_DAYS_FOR_CHECK": {
        "kind": POPULATION_CONSTANT,
        "source": (
            "AI-4 / #530: one full week of data days after a hypothesis is created before it may be "
            "evaluated — a calendar convention (one weekly cycle of behaviour), not a derived bar."
        ),
    },
    "HYPOTHESIS_MIN_DAYS_PER_ARM": {
        "kind": POPULATION_CONSTANT,
        "source": (
            "common/stats_core's bootstrap floor: under five observations in an arm, a resampled interval "
            "is not a confidence interval. A general small-sample constant, adopted here."
        ),
    },
    "COUPLING_MIN_N": {
        "kind": POPULATION_CONSTANT,
        "source": (
            "site_api_intelligence's pillar-coupling floor: a pillar pair with fewer than six co-present "
            "days is omitted from the matrix rather than rendered weakly. Chosen as the smallest n at "
            "which the cell is worth showing — a product convention, not a derived threshold."
        ),
    },
    "FELT_CALIBRATION_MIN_WEEKS": {
        "kind": POPULATION_CONSTANT,
        "source": (
            "#1409, following common/stats_core.pearson_r: Fisher's z CI needs n-3 > 0, and r over fewer "
            "than five WEEKLY probe pairs is coin-flip territory. The same general small-sample argument "
            "as CORRELATION_MIN_N, applied to a weekly pair rather than a daily one."
        ),
    },
    "FELT_CALIBRATION_CI_MIN_WEEKS": {
        "kind": POPULATION_CONSTANT,
        "source": (
            "#1409 / ADR-105 rule 1: below eight weekly pairs the confidence grammar downgrades to a "
            "point estimate rather than publish a band the n cannot support. An honesty convention for "
            "the rendered claim, not a measured property of Matthew's felt-vs-level series."
        ),
    },
}


def gate_provenance(name: str) -> dict:
    """The ``{value, kind, source}`` facet for one module-level threshold.

    ``value`` is read from the live module attribute rather than stored, so the facet and
    the number a gate enforces cannot drift apart. A dict threshold is copied on the way
    out, so a payload consumer can never mutate the registry.
    """
    facet = _PROVENANCE[name]
    value = globals()[name]
    return {"value": dict(value) if isinstance(value, dict) else value, "kind": facet["kind"], "source": facet["source"]}


def all_gate_provenance() -> dict:
    """Every threshold's facet, keyed by module-level name — what the completeness sweep
    grades this module against, and what any surface publishing the whole registry reads."""
    return {name: gate_provenance(name) for name in _PROVENANCE}


def measured_n(current_n, *, metric: str, window: str) -> dict:
    """The facet for a payload's ``current_n`` — a COUNT the caller measured, not a
    threshold, so it carries ``kind='measurement'`` and names what was counted over what
    window. ``value: None`` is the honest "could not be measured" (ADR-104), never a 0."""
    return {
        "value": current_n,
        "kind": MEASUREMENT,
        "source": {"metric": metric, "window": window, "measured_at": "request time, by the site-api handler"},
    }


_CYCLE_WINDOW = "this experiment cycle (since genesis)"
_DATA_DAYS = "days with computed daily metrics"


def correlation_gates(current_n=None):
    """The correlation zero-state payload block: real thresholds + honest progress.

    current_n is the caller-measured count of complete data days this cycle
    (None when the caller can't measure it — the block still carries the gates).

    #3621: `provenance` travels with the numbers — kind + source in the same payload as
    the bar itself, so a reader is never shown a threshold without its warrant.
    """
    return {
        "min_n": CORRELATION_MIN_N,
        "interp_n": dict(CORRELATION_INTERP_N),
        "current_n": current_n,
        "provenance": {
            "min_n": gate_provenance("CORRELATION_MIN_N"),
            "interp_n": gate_provenance("CORRELATION_INTERP_N"),
            "current_n": measured_n(current_n, metric=_DATA_DAYS, window=_CYCLE_WINDOW),
        },
    }


def hypothesis_gates(current_n=None):
    """The hypothesis zero-state payload block (same shape as correlation_gates)."""
    return {
        "min_data_days": HYPOTHESIS_MIN_DATA_DAYS,
        "min_metrics_per_day": HYPOTHESIS_MIN_METRICS_PER_DAY,
        "min_sample_days_for_check": HYPOTHESIS_MIN_SAMPLE_DAYS_FOR_CHECK,
        "current_n": current_n,
        "provenance": {
            "min_data_days": gate_provenance("HYPOTHESIS_MIN_DATA_DAYS"),
            "min_metrics_per_day": gate_provenance("HYPOTHESIS_MIN_METRICS_PER_DAY"),
            "min_sample_days_for_check": gate_provenance("HYPOTHESIS_MIN_SAMPLE_DAYS_FOR_CHECK"),
            "current_n": measured_n(current_n, metric=_DATA_DAYS, window=_CYCLE_WINDOW),
        },
    }


def felt_calibration_gates(current_n=None):
    """The calibration-card zero-state payload block (same shape as the others)."""
    return {
        "min_weeks": FELT_CALIBRATION_MIN_WEEKS,
        "ci_min_weeks": FELT_CALIBRATION_CI_MIN_WEEKS,
        "current_n": current_n,
        "provenance": {
            "min_weeks": gate_provenance("FELT_CALIBRATION_MIN_WEEKS"),
            "ci_min_weeks": gate_provenance("FELT_CALIBRATION_CI_MIN_WEEKS"),
            "current_n": measured_n(current_n, metric="usable felt-probe / character-sheet week pairs", window=_CYCLE_WINDOW),
        },
    }
