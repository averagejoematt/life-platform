"""
experiment_design.py — n-of-1 trial design: pre-registration + paired analysis (#539, ADR-105).

Experiments previously captured free-form intent (`hypothesis` text) and closed with
narrated outcomes — nothing distinguished a genuine A/B window from post-hoc
storytelling. This module is the deterministic core that fixes that:

  - `validate_design` — the design (baseline window, washout, success criterion) is
    machine-checkable and validated at creation; the creating tool FREEZES it on the
    record with a `pre_registered_at` stamp. No writer mutates it afterward.
  - `design_windows` — one place that turns (start, end, design) into the four
    analysis dates: baseline = the N days before start; analysis window = start +
    washout → end. Washout days are excluded so the intervention gets time to act.
  - `evaluate_design` — paired analysis via stats_core (mean difference with a
    moving-block-bootstrap 95% CI + Cohen's d), verdict mirroring the hypothesis
    engine's rule: supported only when the CI excludes zero in the predicted
    direction AND the effect clears the pre-registered minimum.
  - `analysis_summary` — the human sentence built ONLY from computed stats
    ("criterion X · result Y [CI, n]"); narration may quote it, never replace it.

Pure (stdlib + stats_core only, no boto3): callers own the data fetch and the write.
Shared-layer module — imported flat (`import experiment_design`) from mcp/ and lambdas/.
"""

from datetime import datetime, timedelta

import stats_core

# The criterion metric universe: slug → where the daily value lives. Slugs are what
# a design names; source/field are what the closing analysis queries. Whoop sleep
# aliases (sleep_score, deep_pct, …) exist after normalize_whoop_sleep — the caller
# normalizes whoop rows before extracting.
DESIGN_METRICS = {
    "sleep_score": ("whoop", "sleep_score", "Sleep Score"),
    "sleep_efficiency_pct": ("whoop", "sleep_efficiency_pct", "Sleep Efficiency %"),
    "deep_pct": ("whoop", "deep_pct", "Deep Sleep %"),
    "rem_pct": ("whoop", "rem_pct", "REM Sleep %"),
    "sleep_duration_hours": ("whoop", "sleep_duration_hours", "Sleep Duration (h)"),
    "sleep_onset_latency_min": ("eightsleep", "sleep_onset_latency_min", "Sleep Onset Latency (min)"),
    "recovery_score": ("whoop", "recovery_score", "Whoop Recovery"),
    "hrv_rmssd": ("whoop", "hrv_rmssd", "HRV (rMSSD)"),
    "resting_heart_rate": ("whoop", "resting_heart_rate", "Resting HR"),
    "garmin_stress": ("garmin", "average_stress_level", "Garmin Stress"),
    "body_battery_high": ("garmin", "body_battery_high", "Body Battery Peak"),
    "weight_lbs": ("withings", "weight_lbs", "Weight (lbs)"),
    "calories": ("macrofactor", "calories", "Calories"),
    "protein_g": ("macrofactor", "protein_g", "Protein (g)"),
    "steps": ("apple_health", "steps", "Steps"),
    "cgm_mean_glucose": ("apple_health", "cgm_mean_glucose", "Mean Glucose"),
    "cgm_time_in_range_pct": ("apple_health", "cgm_time_in_range_pct", "CGM Time in Range %"),
}

VALID_DIRECTIONS = ("higher", "lower")
MIN_BASELINE_DAYS = 7
MAX_BASELINE_DAYS = 56
MAX_WASHOUT_DAYS = 14
# stats_core's bootstrap floor; below this per arm the verdict is inconclusive, never forced.
MIN_POINTS_PER_ARM = 5


def validate_design(design):
    """Validate a pre-registration design dict. Returns (is_valid, issues).

    Expected shape:
      {"baseline_days": int, "washout_days": int,
       "criterion": {"metric": slug, "direction": "higher"|"lower", "min_effect": number}}
    """
    issues = []
    if not isinstance(design, dict):
        return False, ["design must be an object"]

    baseline = design.get("baseline_days")
    if not isinstance(baseline, int) or isinstance(baseline, bool) or not (MIN_BASELINE_DAYS <= baseline <= MAX_BASELINE_DAYS):
        issues.append(f"baseline_days must be an integer in [{MIN_BASELINE_DAYS}, {MAX_BASELINE_DAYS}]")

    washout = design.get("washout_days", 0)
    if not isinstance(washout, int) or isinstance(washout, bool) or not (0 <= washout <= MAX_WASHOUT_DAYS):
        issues.append(f"washout_days must be an integer in [0, {MAX_WASHOUT_DAYS}]")

    criterion = design.get("criterion")
    if not isinstance(criterion, dict):
        issues.append("criterion is required: {metric, direction, min_effect}")
        return False, issues

    metric = criterion.get("metric")
    if metric not in DESIGN_METRICS:
        issues.append(f"criterion.metric must be one of {sorted(DESIGN_METRICS)}")
    direction = criterion.get("direction")
    if direction not in VALID_DIRECTIONS:
        issues.append(f"criterion.direction must be one of {VALID_DIRECTIONS}")
    min_effect = criterion.get("min_effect")
    if not isinstance(min_effect, (int, float)) or isinstance(min_effect, bool) or min_effect < 0:
        issues.append("criterion.min_effect must be a number >= 0")

    unknown = set(design) - {"baseline_days", "washout_days", "criterion"}
    if unknown:
        issues.append(f"unknown design fields: {sorted(unknown)}")
    unknown_c = set(criterion) - {"metric", "direction", "min_effect"}
    if unknown_c:
        issues.append(f"unknown criterion fields: {sorted(unknown_c)}")

    return (len(issues) == 0), issues


def design_windows(start_date, end_date, design):
    """The four analysis dates, all inclusive YYYY-MM-DD.

    baseline: the `baseline_days` days immediately before start.
    analysis: start + washout_days → end (washout excluded from the treated arm).
    Returns None when the washout consumes the whole experiment window.
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    washout = int(design.get("washout_days", 0) or 0)
    analysis_start = start + timedelta(days=washout)
    if analysis_start > end:
        return None
    return {
        "baseline_start": (start - timedelta(days=int(design["baseline_days"]))).strftime("%Y-%m-%d"),
        "baseline_end": (start - timedelta(days=1)).strftime("%Y-%m-%d"),
        "analysis_start": analysis_start.strftime("%Y-%m-%d"),
        "analysis_end": end.strftime("%Y-%m-%d"),
    }


def evaluate_design(design, baseline_values, window_values):
    """Paired analysis of the pre-registered criterion. Deterministic (seeded bootstrap).

    Returns a stats dict with the verdict:
      supported     — 95% CI excludes 0 in the predicted direction AND |effect| >= min_effect
      contradicted  — 95% CI excludes 0 in the OPPOSITE direction
      inconclusive  — anything else (including thin arms; the honest n's are in the dict)
    """
    criterion = design.get("criterion") or {}
    direction = criterion.get("direction")
    min_effect = float(criterion.get("min_effect", 0) or 0)

    base = stats_core.clean_series(baseline_values)
    win = stats_core.clean_series(window_values)
    result = {
        "n_baseline": len(base),
        "n_window": len(win),
        "mean_baseline": round(sum(base) / len(base), 2) if base else None,
        "mean_window": round(sum(win) / len(win), 2) if win else None,
        "effect_size": None,
        "ci95_low": None,
        "ci95_high": None,
        "cohens_d": None,
        "verdict": "inconclusive",
    }
    if len(base) < MIN_POINTS_PER_ARM or len(win) < MIN_POINTS_PER_ARM:
        return result

    result["effect_size"] = round(result["mean_window"] - result["mean_baseline"], 2)
    ci = stats_core.bootstrap_mean_diff_ci(base, win)
    if ci:
        result["ci95_low"] = round(ci[0], 2)
        result["ci95_high"] = round(ci[1], 2)
    d = stats_core.cohens_d(base, win)
    if d is not None:
        result["cohens_d"] = round(d, 2)

    if ci is not None and direction in VALID_DIRECTIONS:
        lo, hi = result["ci95_low"], result["ci95_high"]
        wants_higher = direction == "higher"
        excludes_zero_predicted = (lo > 0) if wants_higher else (hi < 0)
        excludes_zero_opposite = (hi < 0) if wants_higher else (lo > 0)
        if excludes_zero_predicted and abs(result["effect_size"]) >= min_effect:
            result["verdict"] = "supported"
        elif excludes_zero_opposite:
            result["verdict"] = "contradicted"
    return result


def analysis_summary(design, stats):
    """The result sentence, built ONLY from computed stats (never narrated numbers)."""
    criterion = design.get("criterion") or {}
    metric = criterion.get("metric", "?")
    label = DESIGN_METRICS.get(metric, (None, None, metric))[2]
    if stats.get("effect_size") is None:
        return (
            f"Paired analysis inconclusive: {stats.get('n_window', 0)} intervention days vs "
            f"{stats.get('n_baseline', 0)} baseline days (need {MIN_POINTS_PER_ARM}+ per arm)."
        )
    line = (
        f"Pre-registered criterion: {label} {criterion.get('direction', '?')} by >= {criterion.get('min_effect')}. "
        f"Result: {stats['mean_window']} over {stats['n_window']} intervention days vs "
        f"{stats['mean_baseline']} over {stats['n_baseline']} baseline days — effect {stats['effect_size']:+g}"
    )
    if stats.get("ci95_low") is not None:
        line += f" (95% CI [{stats['ci95_low']:g}, {stats['ci95_high']:g}]"
        if stats.get("cohens_d") is not None:
            line += f", d={stats['cohens_d']:g}"
        line += ")"
    return line + f" -> {stats['verdict']}."
