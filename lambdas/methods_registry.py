"""methods_registry.py — the single source of truth for the public Methods page (#544).

ADR-105 is the rigor bar: uncertainty + n on every statistical claim, deterministic
computation before any LLM verdict, thresholds derived from personal variance rather
than picked out of thin air. This module is the credibility artifact that makes that
bar auditable — every statistic the platform publishes gets one entry here: its
formula, the window it runs over, its known limitations, and what surfaces it feeds.

Anti-drift by construction (the pattern of sync_doc_metadata.py's tool-count
auto-discovery, #389): each entry names the actual function it documents, and
`_fingerprint()` hashes that function's live source. The entry also carries the hash
recorded the last time its prose was verified accurate. `verify_fingerprints()` (run in
tests/test_methods_registry.py) diffs the two — if a function's implementation changes
without a human re-reading and re-committing its registry entry, the test goes red.
The registry can go stale by omission (nobody added an entry for a new stat) but it
cannot silently drift out of sync with a documented one.

This is a pure, read-only module — no I/O, no AI, matching the "zero AI cost" /
"deterministic before narrative" posture of every other stats_core/calibration_core
consumer. `scripts/v4_build_methods.py` renders it into the public
`/method/registry/` page; `lambdas/web/site_api_lambda.py` (`handle_methods`) serves it
as JSON at `/api/methods` for machine consumption — same registry, two surfaces, one
source. The per-stat dict shape (keyed by `id`) is deliberately a clean lookup table so
a future "how was this computed?" provenance popover (#584) can resolve a stat id to
its entry without this module knowing anything about that UI.
"""

import hashlib
import inspect

import calibration_core
import stats_core


def _fingerprint(fn):
    """Short source-hash for a function — the drift tripwire (see module docstring).

    Returns None (never raises) when source isn't available, e.g. a built-in —
    none of the functions registered below hit that path.
    """
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        return None
    return hashlib.sha256(src.encode("utf-8")).hexdigest()[:12]


def _entry(id_, name, fn, category, formula, window, limitations, recorded_fingerprint, min_n=None, used_by=None):
    return {
        "id": id_,
        "name": name,
        "module": fn.__module__,
        "function": fn.__name__,
        "category": category,
        "formula": formula,
        "window": window,
        "limitations": limitations,
        "min_n": min_n,
        "used_by": used_by,
        # `fingerprint` is always the LIVE hash of the current source — recomputed on
        # every import. `recorded_fingerprint` is the value pasted in below the last
        # time this entry's prose was reviewed against the code. verify_fingerprints()
        # compares the two.
        "fingerprint": _fingerprint(fn),
        "recorded_fingerprint": recorded_fingerprint,
    }


# Source modules the registry currently covers, for the page's "where this lives"
# framing. Extend this (and add entries below) before adding a third module.
SOURCE_MODULES = {
    "stats_core": {
        "title": "stats_core.py",
        "path": "lambdas/stats_core.py",
        "description": (
            "The one sanctioned statistics module (ADR-105, story #529) — pure, stdlib-only, "
            "deterministic. Replaced three divergent Pearson-r implementations and two p-value "
            "copies that used to disagree with each other."
        ),
    },
    "calibration_core": {
        "title": "calibration_core.py",
        "path": "lambdas/calibration_core.py",
        "description": (
            "The one prediction-calibration scorer (#538, ADR-105) — grades every forecast the "
            "platform makes against what actually happened, so the public calibration scoreboard, "
            "/api/coach_team, and the coach track-record tool all read the same numbers."
        ),
    },
}

# ── The registry ──────────────────────────────────────────────────────────────
# Recorded fingerprints below were computed against the source as of #544 (2026-07-05
# session 16) — see tests/test_methods_registry.py::test_fingerprints_match_source.
REGISTRY = {
    "pearson_r": _entry(
        "pearson_r",
        "Pearson correlation (r)",
        stats_core.pearson_r,
        "Correlation",
        "r = Σ(x-x̄)(y-ȳ) / √(Σ(x-x̄)² · Σ(y-ȳ)²), clamped to [-1, 1]",
        "Whatever paired series the caller passes in — the function has no lookback of its "
        "own. The platform's primary caller, the weekly correlation compute, passes a 90-day "
        "rolling window (LOOKBACK_DAYS).",
        "Requires n ≥ min_n (default 3, callers commonly raise this to 5); returns None below "
        "that threshold or when either series has zero variance. Measures linear association "
        "only — a real non-linear relationship can score near zero. Not corrected for "
        "day-to-day autocorrelation on its own (see effective_sample_size) — a raw r without "
        "the effective-n-based p-value/CI overstates confidence on daily physiological series.",
        "cc43b664c7de",
        min_n=3,
        used_by=(
            "The correlation engine (/method/intelligence/), tools_training zone-2 and "
            "exercise-efficiency correlations, get_cross_source_correlation."
        ),
    ),
    "lag1_autocorr": _entry(
        "lag1_autocorr",
        "Lag-1 autocorrelation",
        stats_core.lag1_autocorr,
        "Correlation",
        "r1 = Σ(xₜ-x̄)(xₜ₊₁-x̄) / Σ(xₜ-x̄)², clamped to [-1, 1]",
        "Caller-supplied series, in the order given — treats the series as one continuous "
        "sequence with no gap-awareness (a missing day is not distinguished from a lag of 1).",
        "Returns 0.0 (no detectable memory) below n=3 or zero variance, which makes the "
        "downstream effective-n correction a no-op rather than an error. A helper, not a "
        "reported statistic on its own — it feeds effective_sample_size.",
        "1523ef8b9895",
    ),
    "effective_sample_size": _entry(
        "effective_sample_size",
        "Effective sample size (n_eff)",
        stats_core.effective_sample_size,
        "Correlation",
        "Single series: n_eff = n·(1-r1)/(1+r1). Paired (Pyper & Peterman 1998): " "n_eff = n·(1-r1x·r1y)/(1+r1x·r1y)",
        "Same series/window as the r or mean it's correcting.",
        "Clamped to [2, n] — a negative-autocorrelation 'bonus' (n_eff > n) is discarded so "
        "the correction only ever moves toward conservatism, never inflates apparent evidence. "
        "First-order (Bartlett/AR(1)) only — does not model higher-order or seasonal "
        "autocorrelation. The core answer to the ADR-105 rule that daily physiological series "
        "(recovery, HRV, weight) are not i.i.d. and raw n overstates the evidence.",
        "cc8455887d33",
        used_by="Every correlation surface: correlation_report (mcp/helpers.py), tools_training, the weekly correlation compute.",
    ),
    "pearson_p_value": _entry(
        "pearson_p_value",
        "Pearson p-value",
        stats_core.pearson_p_value,
        "Correlation",
        "Two-tailed via the t-distribution: t = r·√df / √(1-r²), df = n-2; erf-based normal "
        "approximation with a small-df shrink z = t·√(df/(df+2)) below df=30",
        "Takes fractional n, so it composes directly with effective_sample_size's "
        "autocorrelation-corrected n_eff rather than the raw observation count.",
        "None when |r| ≥ 1 or n ≤ 2. Accurate to ~3 decimals for df > 10, conservative "
        "(slightly wider) below — a stated intentional trade-off, not an unhandled edge case. "
        "Always compute on n_eff for daily series, never raw n (ADR-105).",
        "dad41124dc37",
        used_by="correlation_report (the ONE correlation-reporting helper, replacing 6 duplicate copies), tools_training.",
    ),
    "fisher_ci": _entry(
        "fisher_ci",
        "Correlation confidence interval (Fisher z)",
        stats_core.fisher_ci,
        "Correlation",
        "z_r = atanh(r); CI = tanh(z_r ± z_crit·SE), SE = 1/√(n-3)",
        "Same n as the r it's bounding — pass effective_sample_size's n_eff for " "autocorrelated daily series.",
        "None when |r| ≥ 1 or n ≤ 3. Supports exactly four confidence levels (0.80, 0.90, "
        "0.95, 0.99) — anything else raises ValueError rather than silently approximating.",
        "dd89a9450ce8",
        used_by="correlation_report, tools_training correlation reads.",
    ),
    "moving_block_bootstrap_ci": _entry(
        "moving_block_bootstrap_ci",
        "Moving-block bootstrap CI",
        stats_core.moving_block_bootstrap_ci,
        "Interval estimation",
        "Percentile CI over 1000 resamples of contiguous blocks (default block length "
        "n^(1/3), floored at 2) — preserves short-range autocorrelation that i.i.d. "
        "resampling would destroy",
        "Caller-supplied series (paired or single); a fixed seed (1337) makes the interval "
        "reproducible for identical input — same data always yields the same interval.",
        "Needs n ≥ 5, and at least 100 of the 1000 replicates must produce a valid statistic "
        "or the call returns None (e.g. degenerate resamples with zero variance). Default "
        "statistic is Pearson r (paired) or the mean (single series); a custom stat may be "
        "passed in. Only 4 confidence levels supported (see fisher_ci).",
        "e5bc510cc54f",
        min_n=5,
        used_by="weight_trend.py (the weight-rate confidence interval on /api/journey, #535).",
    ),
    "bootstrap_mean_diff_ci": _entry(
        "bootstrap_mean_diff_ci",
        "Bootstrap CI for a mean difference",
        stats_core.bootstrap_mean_diff_ci,
        "Interval estimation",
        "Block-resamples baseline and window series independently (1000 replicates each), "
        "returns the percentile CI of mean(window) - mean(baseline)",
        "The two series the caller defines as 'baseline' and 'window' — the n-of-1 "
        "experiment primitive: is this metric different in the test window than before it "
        "started, and by how much?",
        "Both series need n ≥ 5 or the call returns None. Independent block-resampling means "
        "it does not account for any correlation between the baseline and window periods "
        "themselves (e.g. a slow seasonal drift spanning both).",
        "2ebc196523b9",
        min_n=5,
        used_by="experiment_design.py (evaluate_design) — the n-of-1 pre-registered experiment analysis (#539).",
    ),
    "cohens_d": _entry(
        "cohens_d",
        "Cohen's d (effect size)",
        stats_core.cohens_d,
        "Effect size",
        "d = (mean(window) - mean(baseline)) / pooled SD, pooled SD from both groups' " "sample variances",
        "The same two caller-supplied series as bootstrap_mean_diff_ci — the two are always "
        "reported together (a CI without a size, or a size without a CI, is half the honesty "
        "bar).",
        "None when either group has n < 2 or pooled SD is 0. A standardized magnitude, not a "
        "significance test — always report alongside the bootstrap CI, never alone.",
        "ef546176a048",
        used_by="experiment_design.py (evaluate_design).",
    ),
    "start_point_randomization_test": _entry(
        "start_point_randomization_test",
        "Start-point randomization test (SCED)",
        stats_core.start_point_randomization_test,
        "Randomization inference",
        "For every candidate start k the pre-declared window could have produced: "
        "T(k) = mean(post_k) - mean(pre_k), washout excluded identically at each; "
        "one-sided p = #{T(k) at least as extreme as the observed split} / k_valid",
        "The full daily series of the pre-registered criterion metric, from baseline_days "
        "before the declared window's first candidate through the experiment's end — one "
        "continuous series, so every candidate start sees the same data.",
        "Only valid when the start was actually DRAWN at random from the frozen window "
        "(experiment_design.draw_start_date) — applied to a hand-picked start it is decorative, "
        "not inferential. Exact under the randomization performed, so no independence assumption "
        "is needed (the autocorrelation objection to parametric tests on N=1 daily series does "
        "not apply), but resolution is capped at p = 1/k: a 7-14 day window can never report "
        "below 1/7-1/14, which is a granularity floor, not high precision. Candidates with a "
        "thin arm (< 5 points after gaps) are excluded and reported in n_excluded; a pure "
        "pre-existing linear trend scores p ≈ 1 by construction — the coincident-trend "
        "confound the design exists to defeat.",
        "ce658c9d7d25",
        min_n=2,
        used_by=(
            "experiment_design.randomization_test — the end_experiment close-path analysis for "
            "randomized-start designs (#1413); reported on /data/ experiment cards next to the "
            "effect + CI, and in the analysis summary sentence."
        ),
    ),
    "ewma_fit": _entry(
        "ewma_fit",
        "EWMA fit (simple exponential smoothing)",
        stats_core.ewma_fit,
        "Forecasting",
        "level update: levelₜ = levelₜ₋₁ + α·(xₜ - levelₜ₋₁); α chosen by deterministic grid "
        "search over 0.05–0.95 (step 0.05) minimizing one-step-ahead squared error when not "
        "given explicitly",
        "Caller-supplied series in chronological order.",
        "Needs ≥ 4 clean points or returns None. The grid search always picks the same α for "
        "the same data (ties go to the smaller α) — deterministic, no randomness, per ADR-105's "
        "'deterministic computation before any LLM verdict' rule.",
        "d1462361a90e",
        used_by="ewma_forecast (below); indirectly, the forecast engine.",
    ),
    "ewma_forecast": _entry(
        "ewma_forecast",
        "EWMA h-step-ahead forecast",
        stats_core.ewma_forecast,
        "Forecasting",
        "Point forecast = final smoothed level; interval width σ_h = σ·√(1 + (h-1)·α²) where "
        "σ is the sample SD of one-step-ahead residuals",
        "Caller-supplied series; the platform's forecast engine runs this daily at 0.80 "
        "confidence — chosen deliberately below the more common 0.95 so the 'did the interval "
        "cover the outcome ~80% of the time?' calibration question is answerable in weeks, not "
        "months.",
        "Needs ≥ min_n clean points (default 10) and ≥ 3 residuals or returns None. An "
        "EXPECTATION extrapolated from the series' own recent pattern — never a causal claim. "
        "Supports only the 4 fisher_ci confidence levels.",
        "4b50c3a63abf",
        min_n=10,
        used_by="forecast_engine_lambda.py — daily expectations graded into the calibration ledger.",
    ),
    "ewma_series": _entry(
        "ewma_series",
        "EWMA series (exponentially-weighted moving average)",
        stats_core.ewma_series,
        "Forecasting",
        "ewaₜ = α·xₜ + (1-α)·ewaₜ₋₁, with α = 1 - exp(-1/decay_days); optional warm-start seed",
        "Caller-supplied chronological series; EWMA-ACWR runs it with a 7-day (acute) and "
        "28-day (chronic) time-constant over the daily Whoop-strain series.",
        "Recent observations are weighted most, older ones decay smoothly — unlike a flat "
        "rolling mean, which weights its whole window equally and drops days off a cliff at "
        "the edge. ACWR = EWMA(acute)/EWMA(chronic) is a COUPLED ratio: the acute load is a "
        "mathematical component of the chronic load, so they move together by construction "
        "(Lolli et al. 2019) — a directional signal, not a precise injury predictor. The "
        "Gabbett zone thresholds it is compared against are population-derived (ADR-105 r4).",
        "d184d690c287",
        used_by="acwr_compute_lambda.py (EWMA-ACWR, #543); mcp/helpers.compute_ewa.",
    ),
    "bh_fdr": _entry(
        "bh_fdr",
        "Benjamini-Hochberg FDR correction",
        stats_core.bh_fdr,
        "Multiple comparisons",
        "Sort p-values ascending; adjusted p(k) = min(1, m/(k+1) · p(k)), then enforced "
        "monotone non-decreasing from the largest rank down",
        "Applied across one batch of simultaneous comparisons (e.g. all correlation pairs "
        "computed by one tool call) — not across the platform's entire history of tests.",
        "None entries (untestable pairs) pass through unadjusted and don't count toward m. "
        "Controls the FALSE DISCOVERY rate, not the false-positive rate of any single test — "
        "with ~23 simultaneous correlation pairs, some individually-significant p-values will "
        "still be flagged non-significant after correction, by design.",
        "6fbd08d7dfe7",
        used_by="correlation_report (per-tool FDR across every correlation in a batch).",
    ),
    "brier_score": _entry(
        "brier_score",
        "Brier score",
        stats_core.brier_score,
        "Calibration",
        "mean((p - y)²) over all (stated probability, realized outcome) pairs",
        "Every resolved prediction to date for the surface being scored (a coach, the "
        "hypothesis engine, or platform-wide) — grows as more predictions resolve, never a "
        "fixed lookback.",
        "0.0 is perfect, 0.25 is the always-say-50% baseline, 1.0 is confidently-wrong-every-"
        "time. None when there are no valid (probability in [0,1], outcome in {0,1}) pairs — "
        "an unresolved or too-new coach shows no score rather than a misleading 0.",
        "549af3654060",
        used_by="The calibration scoreboard (/method/calibration/), /api/calibration, /api/coach_team, the coach track-record MCP tool.",
    ),
    "brier_skill_score": _entry(
        "brier_skill_score",
        "Brier skill score",
        stats_core.brier_skill_score,
        "Calibration",
        "1 - (Brier score / Brier score of the base-rate climatology forecast)",
        "Same pair set as the Brier score it's compared against.",
        "None when fewer than 2 pairs or every outcome is identical (skill is undefined "
        "against a degenerate base rate). 1.0 is perfect, 0.0 means no better than always "
        "guessing the observed base rate, negative means worse than that baseline — the "
        "honest 'does stated confidence beat just guessing the average?' number.",
        "53f6f9353525",
        used_by="The calibration scoreboard.",
    ),
    "reliability_bins": _entry(
        "reliability_bins",
        "Reliability curve (calibration bins)",
        stats_core.reliability_bins,
        "Calibration",
        "Splits [0,1] into n_bins equal bands (default 10); each non-empty bin reports mean " "stated confidence vs. observed outcome rate",
        "Same pair set as the Brier score for that surface.",
        "Empty list when there are no valid pairs. Bins with very few points can show a noisy "
        "observed rate — the bin's n is always reported alongside so a 1-of-1 bin isn't read "
        "as strong evidence.",
        "ff2ff67a8f4a",
        used_by="The calibration scoreboard's reliability curve.",
    ),
    "calibration_score_pairs": _entry(
        "calibration_score_pairs",
        "Calibration summary (n, Brier, reliability, verdict)",
        calibration_core.score_pairs,
        "Calibration",
        "Composes brier_score + brier_skill_score + reliability_bins over the same " "(confidence, outcome) pairs into one summary dict",
        "Every resolved prediction for the coach/surface being scored, to date.",
        "Needs at least 1 resolved pair to report accuracy_pct; the calibration verdict "
        "(over/under-confident) needs ≥ 5. Below those thresholds the relevant field is None "
        "rather than a guess dressed as a number. Also reports `skilled` (Brier skill > 0?) — "
        "calibrated (reliability: stated confidence tracks observed rates) and skilled (beats "
        "the base rate) are different claims, and the summary carries both so no surface can "
        "conflate them (#1370).",
        "96a2d825721f",
        used_by="/api/calibration, /api/coach_team's per-coach calibration line.",
    ),
    "calibration_verdict": _entry(
        "calibration_verdict",
        "Over/under-confident verdict",
        calibration_core.score_pairs,
        "Calibration",
        "Weighted mean gap = Σ(bin_n · (bin_mean_confidence - bin_observed_rate)) / Σ(bin_n); "
        "gap > 0.15 → over-confident, gap < -0.15 → under-confident; otherwise well-calibrated "
        "only when Brier skill > 0 — a skill ≤ 0 surface reads not-yet-skillful instead (#1370)",
        "Same reliability bins as reliability_bins for that surface.",
        "Requires n ≥ 5 resolved predictions AND at least one non-empty bin, else "
        "'insufficient_data'. The ±0.15 threshold is a fixed editorial choice (not derived "
        "from this platform's own variance) — a documented exception to the ADR-105 'thresholds "
        "from personal variance' rule, tracked as a candidate for future recalibration once "
        "more predictions resolve. 'Well-calibrated' asserts reliability AND skill: a forecaster "
        "whose stated confidence tracks observed rates but whose Brier skill is ≤ 0 (worse than "
        "always guessing the base rate) reads 'not_yet_skillful' — reliability alone never earns "
        "the flattering verdict (ADR-104/105, #1370). An undefined skill (degenerate base rate) "
        "is treated as unknown, not as unskilled.",
        "96a2d825721f",
        min_n=5,
    ),
    "credibility_label": _entry(
        "credibility_label",
        "Coarse credibility label (nascent / not-yet-skillful / developing / reliable / authoritative)",
        calibration_core.score_pairs,
        "Calibration",
        "n < 3 → nascent. Brier skill ≤ 0 → not-yet-skillful. Brier ≤ 0.15 AND n ≥ 12 → "
        "authoritative. Brier ≤ 0.20 → reliable. Else → developing",
        "Same pair set as the Brier score for that surface.",
        "A coarse, backward-compatible label kept for surfaces that pre-date the Brier-based "
        "scorer — always shown alongside the underlying Brier score and n, never as a "
        "substitute for them. The 0.15/0.20 cut points are fixed, not personal-variance-"
        "derived. A negative Brier skill (worse than the base rate) can never render the "
        "reliable/authoritative rungs, however good the raw Brier looks against an extreme "
        "base rate — it reads not-yet-skillful (#1370).",
        "96a2d825721f",
        used_by="Coach cards that need a single at-a-glance credibility word.",
    ),
}


def get_registry():
    """The full registry, keyed by stat id."""
    return REGISTRY


def get_stat(stat_id):
    """One entry, or None — the lookup a future provenance popover (#584) would call."""
    return REGISTRY.get(stat_id)


def list_stats():
    """All entries as a list, insertion order (roughly: correlation → calibration)."""
    return list(REGISTRY.values())


def list_categories():
    """Ordered, de-duplicated category names as they first appear in the registry."""
    seen = []
    for entry in REGISTRY.values():
        if entry["category"] not in seen:
            seen.append(entry["category"])
    return seen


def verify_fingerprints():
    """Entries whose live source no longer matches the recorded fingerprint.

    Returns a list of {id, function, recorded, live} dicts — empty when everything is
    in sync. Exercised by tests/test_methods_registry.py so a code change to a
    documented function fails CI until a human re-reads the entry and updates
    `recorded_fingerprint` to match.
    """
    stale = []
    for stat_id, entry in REGISTRY.items():
        if entry["fingerprint"] != entry["recorded_fingerprint"]:
            stale.append(
                {
                    "id": stat_id,
                    "function": f"{entry['module']}.{entry['function']}",
                    "recorded": entry["recorded_fingerprint"],
                    "live": entry["fingerprint"],
                }
            )
    return stale
