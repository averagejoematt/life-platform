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
Bundled module (#781 — ships in every function's code bundle, no separate layer);
imported flat (`import experiment_design`) from mcp/ and lambdas/.
"""

import math
import random
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
# #728: a pre-registration without a stopping rule is post-hoc storytelling with
# extra steps — the rule must be stated before the data exists, in plain words
# long enough to be checkable ("stop at N days regardless of trend", "abort if
# recovery drops below X for 3 straight days", ...).
MIN_STOPPING_RULE_CHARS = 20
MAX_STOPPING_RULE_CHARS = 500
# stats_core's bootstrap floor; below this per arm the verdict is inconclusive, never forced.
MIN_POINTS_PER_ARM = 5
# #1413 SCED randomized start: the pre-declared window the start is drawn from must be
# wide enough that the randomization test has resolution (min attainable p = 1/k), and
# narrow enough that the declared protocol is still one experiment, not an open-ended
# "sometime this month". 7-14 days ⇒ min p between 1/7 and 1/14.
MIN_START_WINDOW_DAYS = 7
MAX_START_WINDOW_DAYS = 14


def validate_design(design):
    """Validate a pre-registration design dict. Returns (is_valid, issues).

    Expected shape:
      {"baseline_days": int, "washout_days": int, "stopping_rule": str,
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

    # #728: the stopping rule is REQUIRED. It is free text by design — the analysis
    # never executes it — but it must be declared up front so "we stopped early
    # because it was working / hurting" is checkable against what was promised.
    stopping_rule = design.get("stopping_rule")
    if not isinstance(stopping_rule, str) or not (MIN_STOPPING_RULE_CHARS <= len(stopping_rule.strip()) <= MAX_STOPPING_RULE_CHARS):
        issues.append(
            f"stopping_rule is required: a plain-language rule of {MIN_STOPPING_RULE_CHARS}-{MAX_STOPPING_RULE_CHARS} chars "
            'stating when the experiment ends or aborts (e.g. "run the full 21 days regardless of interim trend; '
            'abort only if recovery < 40% for 3 consecutive days")'
        )

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

    # #1413 SCED: an OPTIONAL randomized-start declaration. The window is part of the
    # frozen pre-registration — validated here, drawn from at creation, never edited.
    rand = design.get("randomized_start")
    if rand is not None:
        issues.extend(_randomized_start_issues(rand))

    # #1410: an OPTIONAL counterfactual (ghost) spec. Frozen at pre-registration
    # like everything else in the design — control series, pre-window, and the
    # MAPE gate are declared BEFORE the data exists, so there is no post-hoc
    # spec shopping at close time.
    cf = design.get("counterfactual")
    if cf is not None:
        issues.extend(_counterfactual_issues(cf, (criterion.get("metric") if isinstance(criterion, dict) else None)))

    unknown = set(design) - {"baseline_days", "washout_days", "criterion", "stopping_rule", "randomized_start", "counterfactual"}
    if unknown:
        issues.append(f"unknown design fields: {sorted(unknown)}")
    unknown_c = set(criterion) - {"metric", "direction", "min_effect"}
    if unknown_c:
        issues.append(f"unknown criterion fields: {sorted(unknown_c)}")

    return (len(issues) == 0), issues


# ══════════════════════════════════════════════════════════════════════════════
# #1413: SCED randomized start — draw the intervention start from a pre-declared
# 7-14 day window, then close with a start-point randomization (permutation) test.
#
# Why: a hand-picked start date correlates with how the subject already feels —
# you start the sleep intervention the week sleep is at its worst (regression to
# the mean gets credited) or the week momentum is building (the coincident trend
# gets credited). Drawing the start at random from a window frozen in the prereg
# spec breaks that correlation, and makes an EXACT test available: rank the
# observed pre/post difference against the same statistic at every start the
# window could have produced (stats_core.start_point_randomization_test). Valid
# under autocorrelation, unlike naive parametric tests on an N=1 daily series
# (ADR-105). All helpers are pure; the caller supplies `today` and the rng.
# ══════════════════════════════════════════════════════════════════════════════


def _parse_date(s):
    try:
        return datetime.strptime(str(s), "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _randomized_start_issues(rand):
    """Shape issues for a design's randomized_start declaration (empty list = valid)."""
    if not isinstance(rand, dict):
        return ["randomized_start must be an object: {window_start, window_end} (YYYY-MM-DD)"]
    issues = []
    start = _parse_date(rand.get("window_start"))
    end = _parse_date(rand.get("window_end"))
    if start is None or end is None:
        issues.append("randomized_start.window_start and window_end must be YYYY-MM-DD dates")
    else:
        span = (end - start).days + 1
        if not (MIN_START_WINDOW_DAYS <= span <= MAX_START_WINDOW_DAYS):
            issues.append(
                f"randomized_start window must span {MIN_START_WINDOW_DAYS}-{MAX_START_WINDOW_DAYS} days "
                f"(got {span}) — wide enough for the randomization test to have resolution (min p = 1/k)"
            )
    unknown = set(rand) - {"window_start", "window_end"}
    if unknown:
        issues.append(f"unknown randomized_start fields: {sorted(unknown)}")
    return issues


def candidate_start_dates(rand):
    """Every start date (YYYY-MM-DD, inclusive) the pre-declared window could produce."""
    start = _parse_date(rand.get("window_start"))
    end = _parse_date(rand.get("window_end"))
    if start is None or end is None or end < start:
        return []
    return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((end - start).days + 1)]


def validate_start_window_not_past(rand, today):
    """(ok, issue) — the window must not have begun before registration.

    `today` is the registration date (YYYY-MM-DD), passed EXPLICITLY so this stays a
    pure function (wallclock-safe in tests). A window that already started is a
    post-hoc story, not a pre-declaration.
    """
    start = _parse_date(rand.get("window_start"))
    if start is None:
        return False, "randomized_start.window_start must be a YYYY-MM-DD date"
    if start < _parse_date(today):
        return False, (
            f"randomized_start window begins {rand.get('window_start')}, before the registration date {today} — "
            "the window must be pre-declared, never post-hoc"
        )
    return True, None


def draw_start_date(rand, rng=None):
    """Draw the intervention start uniformly from the pre-declared window.

    Returns (start_date, provenance). The draw is the ONE deliberately random step
    in the pipeline (that randomness is what buys the exact test); everything about
    it is recorded — window, candidate count, drawn index, method — so the analysis
    can later prove the start was drawn, not chosen. Production callers use the
    default SystemRandom; tests inject a seeded rng.
    """
    dates = candidate_start_dates(rand)
    if not dates:
        raise ValueError(f"randomized_start window is invalid: {rand!r}")
    rng = rng or random.SystemRandom()
    idx = rng.randrange(len(dates))
    return dates[idx], {
        "method": "uniform_random",
        "window_start": rand["window_start"],
        "window_end": rand["window_end"],
        "n_candidates": len(dates),
        "drawn_index": idx,
    }


def randomization_series_start(design):
    """First date of the series the randomization test runs over: baseline_days
    before the WINDOW start, so the earliest candidate still has a full baseline."""
    rand = design.get("randomized_start") or {}
    start = _parse_date(rand.get("window_start"))
    if start is None:
        return None
    return (start - timedelta(days=int(design["baseline_days"]))).strftime("%Y-%m-%d")


def randomization_test(design, values_by_date, start_date, end_date):
    """The close-path start-point randomization test for a randomized-start design.

    `values_by_date` maps YYYY-MM-DD → criterion-metric value over (at least)
    [randomization_series_start(design), end_date]; missing days are honest gaps.
    Returns the provenance-carrying result dict, or None when the design has no
    randomized_start, the actual start is not one of the declared candidates, or
    the data can't support the test (thin arms — see stats_core). The washout is
    applied identically at EVERY candidate start, mirroring the primary analysis.
    """
    rand = design.get("randomized_start")
    if not rand:
        return None
    series_start = randomization_series_start(design)
    first = _parse_date(series_start)
    last = _parse_date(end_date)
    if first is None or last is None or last < first:
        return None
    dates = [(first + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((last - first).days + 1)]
    values = [values_by_date.get(d) for d in dates]
    index_of = {d: i for i, d in enumerate(dates)}
    candidates = [index_of[d] for d in candidate_start_dates(rand) if d in index_of]
    actual = index_of.get(start_date)
    if actual is None or actual not in candidates:
        return None
    result = stats_core.start_point_randomization_test(
        values,
        candidates,
        actual,
        direction=(design.get("criterion") or {}).get("direction", "higher"),
        washout=int(design.get("washout_days", 0) or 0),
        min_per_arm=MIN_POINTS_PER_ARM,
    )
    if result is None:
        return None
    return {
        **result,
        "window_start": rand["window_start"],
        "window_end": rand["window_end"],
        "actual_start": start_date,
        "direction": (design.get("criterion") or {}).get("direction"),
        "method": (
            "start-point randomization test (Edgington): the observed pre/post mean difference ranked "
            "one-sided against the same statistic at every start the pre-declared window could have "
            "produced — exact under the randomization actually performed, valid under autocorrelation"
        ),
        "engine": "sced-randstart-v1",
    }


# ══════════════════════════════════════════════════════════════════════════════
# #1410: the Ghost — a BSTS-lite synthetic-control counterfactual for every
# concluded intervention whose design declared one.
#
# Why: post − pre answers "did it change?"; the ghost answers "compared to
# WHAT?" — the criterion forecast from its own pre-period behavior (local level)
# plus control series the intervention shouldn't move (bsts_lite.py). The spec —
# controls, pre-window, MAPE gate — is part of the FROZEN design (validated at
# create alongside criterion/stopping_rule), so there is no post-hoc spec
# shopping. The pre-fit MAPE gate withholds the ghost with a stated reason when
# the model couldn't track the pre-period (ADR-104: a dignified refusal, never a
# fabricated counterfactual). All helpers pure; callers fetch the series.
# ══════════════════════════════════════════════════════════════════════════════

CF_MIN_PRE_POINTS = 14  # below this the ghost has no honest footing (aligned days)
CF_MIN_PRE_DAYS, CF_MAX_PRE_DAYS = 14, 120
CF_DEFAULT_PRE_DAYS = 28
CF_DEFAULT_MAPE_GATE_PCT = 15.0
CF_MAX_CONTROLS = 3
# Series payload cap for the card chart — post windows are ≤ ~8 weeks in
# practice; this is a hard bound on the served array, never a silent truncation
# of the ANALYSIS (the effect uses every aligned day regardless).
CF_MAX_SERIES_POINTS = 120


def _counterfactual_issues(cf, criterion_metric):
    issues = []
    if not isinstance(cf, dict):
        return ["counterfactual must be an object: {controls?, pre_days?, mape_gate_pct?}"]
    controls = cf.get("controls", [])
    if not isinstance(controls, list) or len(controls) > CF_MAX_CONTROLS:
        issues.append(f"counterfactual.controls must be a list of at most {CF_MAX_CONTROLS} metric slugs")
    else:
        for m in controls:
            if m not in DESIGN_METRICS:
                issues.append(f"counterfactual.controls: unknown metric '{m}' (must be one of {sorted(DESIGN_METRICS)})")
            elif m == criterion_metric:
                issues.append("counterfactual.controls must not include the criterion metric itself")
        if len(set(controls)) != len(controls):
            issues.append("counterfactual.controls must not repeat a metric")
    pre_days = cf.get("pre_days", CF_DEFAULT_PRE_DAYS)
    if not isinstance(pre_days, int) or isinstance(pre_days, bool) or not (CF_MIN_PRE_DAYS <= pre_days <= CF_MAX_PRE_DAYS):
        issues.append(f"counterfactual.pre_days must be an integer in [{CF_MIN_PRE_DAYS}, {CF_MAX_PRE_DAYS}]")
    gate = cf.get("mape_gate_pct", CF_DEFAULT_MAPE_GATE_PCT)
    if not isinstance(gate, (int, float)) or isinstance(gate, bool) or not (1 <= gate <= 50):
        issues.append("counterfactual.mape_gate_pct must be a number in [1, 50]")
    unknown = set(cf) - {"controls", "pre_days", "mape_gate_pct"}
    if unknown:
        issues.append(f"unknown counterfactual fields: {sorted(unknown)}")
    return issues


def counterfactual_series_start(design, start_date):
    """First date the ghost's inputs need: pre_days before the intervention start."""
    cf = design.get("counterfactual") or {}
    pre_days = int(cf.get("pre_days", CF_DEFAULT_PRE_DAYS) or CF_DEFAULT_PRE_DAYS)
    return (_parse_date(start_date) - timedelta(days=pre_days)).strftime("%Y-%m-%d")


def counterfactual_analysis(design, dated_criterion, dated_controls, start_date, end_date):
    """Fit the frozen ghost spec at close. Pure — callers fetch the dated series.

    dated_criterion: {date: value} for the criterion metric, from
      counterfactual_series_start() through end_date.
    dated_controls: {metric_slug: {date: value}} for each declared control.

    Returns the analysis block: state "ok" (effect + CI + the served series) or
    state "no_counterfactual" with a stated reason — never None-and-silent, so
    the close-path record always says WHY a declared ghost is absent.
    """
    import bsts_lite

    cf = design.get("counterfactual") or {}
    controls = list(cf.get("controls") or [])
    gate_pct = float(cf.get("mape_gate_pct", CF_DEFAULT_MAPE_GATE_PCT) or CF_DEFAULT_MAPE_GATE_PCT)
    spec = {
        "controls": controls,
        "pre_days": int(cf.get("pre_days", CF_DEFAULT_PRE_DAYS) or CF_DEFAULT_PRE_DAYS),
        "mape_gate_pct": gate_pct,
        "engine": "bsts-lite-v1",
    }

    def _refuse(reason, **extra):
        return {"state": "no_counterfactual", "reason": reason, "spec": spec, **extra}

    windows = design_windows(start_date, end_date, design)
    if windows is None:
        return _refuse("washout consumed the whole experiment window")

    pre_start = counterfactual_series_start(design, start_date)
    pre_end = (_parse_date(start_date) - timedelta(days=1)).strftime("%Y-%m-%d")

    def _aligned_days(d_from, d_to):
        """Dates in [d_from, d_to] where the criterion AND every control have a
        value — a day missing any input is dropped (counted, never imputed)."""
        days, dropped = [], 0
        cur, last = _parse_date(d_from), _parse_date(d_to)
        while cur <= last:
            d = cur.strftime("%Y-%m-%d")
            if dated_criterion.get(d) is not None and all((dated_controls.get(m) or {}).get(d) is not None for m in controls):
                days.append(d)
            elif dated_criterion.get(d) is not None or any((dated_controls.get(m) or {}).get(d) is not None for m in controls):
                dropped += 1
            cur += timedelta(days=1)
        return days, dropped

    pre_dates, pre_dropped = _aligned_days(pre_start, pre_end)
    post_dates, post_dropped = _aligned_days(windows["analysis_start"], windows["analysis_end"])
    if len(pre_dates) < CF_MIN_PRE_POINTS:
        return _refuse(
            f"insufficient pre-period: {len(pre_dates)} aligned days (need {CF_MIN_PRE_POINTS}+)",
            n_pre=len(pre_dates),
            n_pre_dropped=pre_dropped,
        )
    if not post_dates:
        return _refuse("no aligned post-period days", n_pre=len(pre_dates), n_post_dropped=post_dropped)

    pre_y = [float(dated_criterion[d]) for d in pre_dates]
    pre_x = [[float(dated_controls[m][d]) for m in controls] for d in pre_dates] if controls else None
    post_x = [[float(dated_controls[m][d]) for m in controls] for d in post_dates] if controls else None

    fit = bsts_lite.fit_counterfactual(pre_y, len(post_dates), pre_x=pre_x, post_x=post_x)
    if fit is None:
        return _refuse("model could not be fit (collinear controls or degenerate pre-period)", n_pre=len(pre_dates))
    if fit["mape_pct"] is None:
        return _refuse("pre-fit MAPE unevaluable (criterion too close to zero on most pre-period days)", n_pre=fit["n_pre"])
    if fit["mape_pct"] > gate_pct:
        return _refuse(
            f"pre-fit MAPE {fit['mape_pct']:g}% exceeds the frozen gate {gate_pct:g}%",
            mape_pct=fit["mape_pct"],
            n_pre=fit["n_pre"],
        )

    observed_post = [float(dated_criterion[d]) for d in post_dates]
    eff = bsts_lite.effect_summary(observed_post, fit)
    if eff is None:
        return _refuse("no usable post-period observations", n_pre=fit["n_pre"])

    # The served series (capped, honest about it): observed vs ghost with the
    # honestly-widening 95% band. Confidence grammar level rides along so the
    # renderer can apply LOW ⇒ point-marks-only, never a fabricated band.
    idx = list(range(len(post_dates)))[:CF_MAX_SERIES_POINTS]
    series = {
        "dates": [post_dates[i] for i in idx],
        "observed": [round(observed_post[i], 2) for i in idx],
        "ghost": [round(fit["ghost"][i], 2) for i in idx],
        "ci_low": [round(fit["ghost"][i] - bsts_lite.Z95 * math.sqrt(fit["point_var"][i]), 2) for i in idx],
        "ci_high": [round(fit["ghost"][i] + bsts_lite.Z95 * math.sqrt(fit["point_var"][i]), 2) for i in idx],
        "truncated": len(post_dates) > CF_MAX_SERIES_POINTS,
    }
    level = "high" if fit["n_pre"] >= 21 else "medium"  # CF_MIN_PRE_POINTS floors out "low"
    return {
        "state": "ok",
        "spec": spec,
        "n_pre": fit["n_pre"],
        "n_pre_dropped": pre_dropped,
        "n_post": len(post_dates),
        "n_post_dropped": post_dropped,
        "mape_pct": fit["mape_pct"],
        "q": fit["q"],
        "effect_mean": eff["effect_mean"],
        "ci95_low": eff["ci95_low"],
        "ci95_high": eff["ci95_high"],
        "level": level,
        "series": series,
    }


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
    # #1413: a randomized-start design also reports its permutation p, with its
    # honest resolution — with k candidate starts the test can never report below 1/k.
    rand = stats.get("randomization")
    if isinstance(rand, dict) and rand.get("p_value") is not None:
        line += (
            f"; randomization p={rand['p_value']:g} (one-sided, {rand.get('n_used')} candidate starts "
            f"from the pre-declared window, min attainable p {rand.get('min_p'):g})"
        )
    # #1410: the ghost's answer to "compared to what?" — or its stated refusal.
    # Numbers only ever come from counterfactual_analysis; nothing is narrated.
    cf = stats.get("counterfactual")
    if isinstance(cf, dict):
        if cf.get("state") == "ok":
            line += (
                f"; vs the counterfactual: {cf['effect_mean']:+g} "
                f"(95% CI [{cf['ci95_low']:g}, {cf['ci95_high']:g}], pre-fit MAPE {cf['mape_pct']:g}%, n_pre {cf['n_pre']})"
            )
        elif cf.get("reason"):
            line += f"; no counterfactual ({cf['reason']})"
    return line + f" -> {stats['verdict']}."


# ══════════════════════════════════════════════════════════════════════════════
# #1117: the justification contract — why_now / priority / hoped_outcome /
# measurement / evidence_links.
#
# An experiment record previously carried its hypothesis but not its
# justification: WHY this, WHY now, what outcome is hoped for, how it will be
# measured, and what evidence motivated it. These helpers are the pure core:
#   - `validate_justification` — what the field set may say (same posture as
#     `validate_design`: an invalid justification rejects the creation).
#   - `derive_why_now` — wires `why_now` to the promotion trigger, so the
#     provenance is automatic where it exists: an explicit value always wins;
#     else a confirmed hypothesis (the hypothesis-engine promotion path) or a
#     promoted experiment-library entry (rationale + promoted_date) supplies it.
#   - `derive_evidence_links` — evidence links carried from the library entry's
#     for/against citations (dissent kept, per the P2.3 disclosure grammar).
#
# ADR-104 honest-empty: every helper returns None/[] when there is no real
# trigger — callers store nothing and surfaces render nothing.
# ══════════════════════════════════════════════════════════════════════════════

VALID_PRIORITIES = ("high", "medium", "low")
MAX_JUSTIFICATION_CHARS = 600
MAX_EVIDENCE_LINKS = 8
VALID_LINK_STANCES = ("for", "against")


def validate_justification(just):
    """Validate the justification field set. Returns (is_valid, issues).

    Expected shape (every field optional — honest-empty is a valid state):
      {"why_now": str, "priority": "high"|"medium"|"low", "hoped_outcome": str,
       "measurement": str, "evidence_links": [{"url": http(s) str,
       "title": str?, "stance": "for"|"against"?}]}
    """
    issues = []
    if not isinstance(just, dict):
        return False, ["justification must be an object"]

    for field in ("why_now", "hoped_outcome", "measurement"):
        val = just.get(field)
        if val is None:
            continue
        if not isinstance(val, str) or not val.strip() or len(val.strip()) > MAX_JUSTIFICATION_CHARS:
            issues.append(f"{field} must be a non-empty string of at most {MAX_JUSTIFICATION_CHARS} chars")

    priority = just.get("priority")
    if priority is not None and priority not in VALID_PRIORITIES:
        issues.append(f"priority must be one of {VALID_PRIORITIES}")

    links = just.get("evidence_links")
    if links is not None:
        if not isinstance(links, list) or len(links) > MAX_EVIDENCE_LINKS:
            issues.append(f"evidence_links must be a list of at most {MAX_EVIDENCE_LINKS} links")
        else:
            for i, link in enumerate(links):
                if (
                    not isinstance(link, dict)
                    or not isinstance(link.get("url"), str)
                    or not link["url"].startswith(("http://", "https://"))
                ):
                    issues.append(f"evidence_links[{i}] must be an object with an http(s) 'url'")
                    continue
                if link.get("stance") is not None and link["stance"] not in VALID_LINK_STANCES:
                    issues.append(f"evidence_links[{i}].stance must be one of {VALID_LINK_STANCES}")

    unknown = set(just) - {"why_now", "priority", "hoped_outcome", "measurement", "evidence_links"}
    if unknown:
        issues.append(f"unknown justification fields: {sorted(unknown)}")

    return (len(issues) == 0), issues


def derive_why_now(explicit, hypothesis=None, library_entry=None):
    """Resolve why_now from the promotion trigger. Returns (text, source).

    Precedence: an explicit value ("explicit") > a CONFIRMED hypothesis record
    ("hypothesis" — the hypothesis-engine promotion path, carrying the measured
    effect when the deterministic check persisted one, per ADR-104/105) > a
    promoted experiment-library entry ("library" — rationale + promoted_date).
    Returns (None, None) when no trigger exists — honest-empty.
    """
    if explicit and str(explicit).strip():
        return str(explicit).strip(), "explicit"

    if isinstance(hypothesis, dict) and hypothesis.get("status") == "confirmed" and str(hypothesis.get("hypothesis") or "").strip():
        text = f"Promoted from a confirmed hypothesis: {str(hypothesis['hypothesis']).strip()}"
        confirmed_on = str(hypothesis.get("last_checked") or "")[:10]
        if confirmed_on:
            text += f" (confirmed {confirmed_on})"
        effect = hypothesis.get("effect_size")
        lo, hi = hypothesis.get("ci95_low"), hypothesis.get("ci95_high")
        if effect is not None and lo is not None and hi is not None:
            text += (
                f" — measured effect {float(effect):+g}, 95% CI [{float(lo):g}, {float(hi):g}], "
                f"n={int(hypothesis.get('n_condition') or 0)}/{int(hypothesis.get('n_comparison') or 0)} days"
            )
        return text + ".", "hypothesis"

    if isinstance(library_entry, dict):
        rationale = str(library_entry.get("rationale") or "").strip()
        promoted = str(library_entry.get("promoted_date") or "").strip()
        if rationale or promoted:
            text = "Promoted from the experiment library"
            if promoted:
                text += f" on {promoted}"
            text += f": {rationale}" if rationale else "."
            votes = library_entry.get("votes")
            if isinstance(votes, (int, float)) and not isinstance(votes, bool) and votes > 0:
                text += f" ({int(votes)} reader vote{'s' if votes != 1 else ''})"
            return text, "library"

    return None, None


def derive_evidence_links(explicit, library_entry=None):
    """Resolve evidence links. An explicit list wins; else carry the library
    entry's for/against citations (URL'd ones only — these are LINKS; the
    dissent is kept and tagged, never filtered). Returns [] when neither exists."""
    if explicit:
        return list(explicit)[:MAX_EVIDENCE_LINKS]

    links = []
    if isinstance(library_entry, dict):
        for stance, key in (("for", "evidence_for"), ("against", "evidence_against")):
            for src in library_entry.get(key) or []:
                url = isinstance(src, dict) and src.get("url")
                if url:
                    links.append({"url": url, "title": str(src.get("title") or "").strip() or url, "stance": stance})
    return links[:MAX_EVIDENCE_LINKS]
