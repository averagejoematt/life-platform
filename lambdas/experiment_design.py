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
# #728: a pre-registration without a stopping rule is post-hoc storytelling with
# extra steps — the rule must be stated before the data exists, in plain words
# long enough to be checkable ("stop at N days regardless of trend", "abort if
# recovery drops below X for 3 straight days", ...).
MIN_STOPPING_RULE_CHARS = 20
MAX_STOPPING_RULE_CHARS = 500
# stats_core's bootstrap floor; below this per arm the verdict is inconclusive, never forced.
MIN_POINTS_PER_ARM = 5


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

    unknown = set(design) - {"baseline_days", "washout_days", "criterion", "stopping_rule"}
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
