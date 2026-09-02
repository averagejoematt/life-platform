"""lambdas/web/site_api_discovery.py — what the platform has actually found.

Split out of ``site_api_intelligence.py`` (#1654 — god-module breakup). One seam:
**the statistical-discovery surface** — the standing hypotheses and their status,
the counts rollup the Intelligence page opens on, the pillar-coupling matrix, and
the FDR-corrected correlation table. All four publish evidence under the same
rules (ADR-104/ADR-105): an n-gate, a stated uncertainty, and honest omission
rather than a claim the sample can't carry.

The routed handler entrypoints stay in the ``site_api_intelligence`` facade as
thin delegators; the logic lives here. Handlers receive the facade's ``globals()``
as ``_g`` and read the injectable state (``table``, ``EXPERIMENT_START``) via
``_g["<name>"]`` — the surface ``test_hypotheses_serving`` /
``test_correlations_serving`` / ``test_experiment_gates`` /
``test_effect_fit_status_1411`` patch on the facade. This module does NOT import
the facade; no import cycle.
"""

from datetime import datetime, timezone
from typing import Any

from boto3.dynamodb.conditions import Key
from common import stats_core  # #1240: sanctioned stats implementation (ADR-105) — correlations
from experiment import experiment_gates  # #1371: arming thresholds served to zero-states — same objects the engines enforce
from experiment.phase_filter import with_phase_filter  # ADR-058 / #946 / #1197

from web.site_api_common import (
    USER_PREFIX,
    _decimal_to_float,
    _error,
    _ok,
    logger,
)

# ── PB-08 / #8: Hypotheses + Intelligence summary ─────────
# Both are public read-only routes that feed the Intelligence-page tabbed
# rebuild. Henning/Anika evidence rules apply: hypotheses MUST carry a status
# and confidence, never causal claims; the summary surfaces counts only.

_HYPOTHESES_PK = f"{USER_PREFIX}hypotheses"


def hypotheses(*, _g) -> dict:
    """
    GET /api/hypotheses
    Returns active hypotheses with status + confidence + domain, plus the
    verdict trail (last_checked / last_evidence) once the engine grades one.
    Filters out `public: false` so private records never leak.
    Cache: 3600s (the hypothesis engine runs WEEKLY, Sundays; data shifts slowly).
    """
    table = _g["table"]

    try:
        resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot hypotheses
                    "KeyConditionExpression": Key("pk").eq(_HYPOTHESES_PK) & Key("sk").begins_with("HYPOTHESIS#"),
                    "ScanIndexForward": False,  # newest first
                    "Limit": 50,
                }
            )
        )
    except Exception as e:
        logger.warning(f"hypotheses query failed: {e}")
        return _error(503, "Hypotheses unavailable.")

    items = _decimal_to_float(resp.get("Items", []))
    hypotheses = []
    for it in items:
        # Hide explicitly-private hypotheses. Default is public for hypotheses
        # written by the IC-18 engine, which produces user-visible findings.
        if it.get("public") is False:
            continue
        hypotheses.append(
            {
                "hypothesis_id": it.get("hypothesis_id") or it.get("sk", "").replace("HYPOTHESIS#", ""),
                "hypothesis": it.get("hypothesis", ""),
                "domains": it.get("domains", []),
                "status": it.get("status", "pending"),
                "confidence": it.get("confidence"),
                "created_at": it.get("created_at"),
                "check_count": it.get("check_count", 0),
                "evidence": it.get("evidence", {}),
                # The weekly check's verdict trail — the citing evidence sentence the
                # engine wrote when it last graded this bet (AI-4 requires confirming/
                # refuted verdicts to cite numbers). Null until the first check lands.
                "last_checked": it.get("last_checked"),
                "last_evidence": it.get("last_evidence"),
                # #530 (engine v2): the FROZEN pre-registered test spec + the
                # deterministic test's measured stats — the public proof that the
                # criterion predates the data that graded it (ADR-105). Null on
                # v1-era records (they age out within 30 days).
                "test_spec": it.get("test_spec"),
                "pre_registered_at": it.get("pre_registered_at") or it.get("created_at"),
                "deterministic_verdict": it.get("deterministic_verdict"),
                "effect_size": it.get("effect_size"),
                "ci95_low": it.get("ci95_low"),
                "ci95_high": it.get("ci95_high"),
                "n_condition": it.get("n_condition"),
                "n_comparison": it.get("n_comparison"),
                "days_observed": it.get("days_observed"),
            }
        )

    return _ok(
        {
            "hypotheses": hypotheses,
            "count": len(hypotheses),
            # #1371: on a cold start the engine's real arming gates + measured progress
            # ride along, so the zero-state renders a computed trigger. Only fetched
            # when the ledger is empty — armed instruments don't need the countdown.
            "gates": (experiment_gates.hypothesis_gates(current_n=_data_days_this_cycle(_g=_g)) if not hypotheses else None),
            "_notice": "N=1 personal-platform observations — not population claims.",
        },
        cache_seconds=3600,
    )


def intelligence_summary(*, _g) -> dict:
    """
    GET /api/intelligence_summary
    Top-line counts for the Intelligence page hero strip:
      - active hypotheses
      - validated discoveries / correlations
      - experiments active
      - last computed-at timestamps per signal class
    Cache: 1800s.
    """
    table = _g["table"]

    summary: dict[str, Any] = {
        "hypotheses": {"count": 0, "by_status": {}},
        "correlations": {"count": 0, "last_week": None},
        "experiments": {"active": 0},
        "_meta": {"computed_at": datetime.now(timezone.utc).isoformat()},
    }
    # Hypotheses count + by-status
    try:
        resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot hypotheses
                    "KeyConditionExpression": Key("pk").eq(_HYPOTHESES_PK) & Key("sk").begins_with("HYPOTHESIS#"),
                    "Limit": 200,
                }
            )
        )
        items = _decimal_to_float(resp.get("Items", []))
        public_items = [it for it in items if it.get("public") is not False]
        summary["hypotheses"]["count"] = len(public_items)
        by_status: dict[str, int] = {}
        for it in public_items:
            s = it.get("status", "pending")
            by_status[s] = by_status.get(s, 0) + 1
        summary["hypotheses"]["by_status"] = by_status
    except Exception as e:
        logger.warning(f"intel summary: hypotheses count failed: {e}")

    # Latest weekly correlation matrix
    try:
        resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot correlations
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}weekly_correlations"),
                    "ScanIndexForward": False,
                    "Limit": 1,
                }
            )
        )
        items = _decimal_to_float(resp.get("Items", []))
        if items:
            record = items[0]
            corrs = record.get("correlations", {})
            summary["correlations"]["count"] = len(corrs) if isinstance(corrs, (dict, list)) else 0
            summary["correlations"]["last_week"] = record.get("sk", "").replace("WEEK#", "")
    except Exception as e:
        logger.warning(f"intel summary: correlations failed: {e}")

    # Active experiments — query the experiments partition (best-effort)
    try:
        resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot experiments
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}experiments"),
                    "Limit": 100,
                }
            )
        )
        items = _decimal_to_float(resp.get("Items", []))
        summary["experiments"]["active"] = sum(1 for it in items if it.get("status") == "active")
    except Exception as e:
        logger.warning(f"intel summary: experiments failed: {e}")

    return _ok(summary, cache_seconds=1800)


# ════════════════════════════════════════════════════════════════════════
# #1240: intelligence-adjacent domain handlers — moved verbatim from site_api_data.py
# (correlations / forecast / scenarios / state_of_matthew / inference_receipt /
# wrong / pillar_coupling). Behavior-identical; the router imports these from here.
# ════════════════════════════════════════════════════════════════════════

_COUPLING_PILLARS = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]

_COUPLING_WINDOW = 60  # trailing character-sheet records to read

_COUPLING_MIN_N = experiment_gates.COUPLING_MIN_N  # a pair needs this many co-present real days or it's honestly omitted


def _coupling_real_score(pd: dict):
    """The pillar's raw_score for a day IF that day carried real signal, else None.

    ADR-104/105: a held/zero-coverage day is NOT a real low — counting a floored or
    carried-forward score would manufacture spurious (anti-)correlation, especially
    across a manual-logging gap. We correlate only days with genuine data.
    """
    if not isinstance(pd, dict):
        return None
    v = pd.get("raw_score")
    if v is None:
        return None
    if pd.get("coverage_hold"):
        return None
    cov = pd.get("data_coverage")
    if cov is not None and float(cov) <= 0:
        return None
    return float(v)


def pillar_coupling(*, _g) -> dict:
    """GET /api/pillar_coupling — #590: how the seven pillars have actually co-moved.

    Deterministic pairwise Pearson of each pillar's daily raw_score over a trailing
    window (real-signal days only, per _coupling_real_score). Every edge carries its
    own n; pairs below the n floor or with no variance are omitted, never faked — the
    constellation draws thin/absent data honestly faint. No AI, no forecast: this is a
    descriptive statistic over the last ~60 days, labeled by its actual date range.
    """
    table = _g["table"]

    # #1895: phase-filter the window. character_sheet is wiped ("all") at a restart
    # and TOMBSTONED rather than deleted, so an unfiltered trailing-60 read draws the
    # PRIOR cycle's sheets. Live on Day 3 of cycle 11: 118 of 122 DATE# records were
    # tombstoned, and the home constellation — the first beat on the page — rendered
    # 14 edges (r=-0.87, n=47, p=0.0, "significant") computed almost entirely from the
    # wiped cycle, over a window labelled 2026-05-30 → 2026-07-28. Filtered, a fresh
    # cycle falls under _COUPLING_MIN_N and the endpoint returns honest_null with no
    # edges — which is what this module's own docstring calls the honest signal.
    resp = table.query(
        **with_phase_filter(
            {
                "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}character_sheet") & Key("sk").begins_with("DATE#"),
                "ScanIndexForward": False,
                "Limit": _COUPLING_WINDOW,
            }
        )
    )
    recs = _decimal_to_float(resp.get("Items", []))
    recs.sort(key=lambda r: str(r.get("sk", "")))  # chronological
    if len(recs) < _COUPLING_MIN_N:
        return _ok(
            {
                "edges": [],
                "pillars": [],
                "window_start": None,
                "window_end": None,
                "window_days": 0,
                "min_n": _COUPLING_MIN_N,
                "honest_null": True,
            },
            cache_seconds=3600,
        )

    series = {p: [_coupling_real_score(r.get(f"pillar_{p}")) for r in recs] for p in _COUPLING_PILLARS}
    present = [p for p in _COUPLING_PILLARS if any(v is not None for v in series[p])]

    edges = []
    for i in range(len(present)):
        for j in range(i + 1, len(present)):
            a, b = present[i], present[j]
            r = stats_core.pearson_r(series[a], series[b], min_n=_COUPLING_MIN_N)
            if r is None:  # thin or flat → no honest edge to draw
                continue
            n = sum(1 for x, y in zip(series[a], series[b]) if x is not None and y is not None)
            p_val = stats_core.pearson_p_value(r, n)
            edges.append(
                {
                    "a": a,
                    "b": b,
                    "r": round(r, 2),
                    "n": n,
                    "p": round(p_val, 3) if p_val is not None else None,
                    "significant": bool(p_val is not None and p_val < 0.05),
                }
            )
    edges.sort(key=lambda e: -abs(e["r"]))
    return _ok(
        {
            "edges": edges,
            "pillars": present,
            "window_start": str(recs[0].get("sk", "")).replace("DATE#", "")[:10],
            "window_end": str(recs[-1].get("sk", "")).replace("DATE#", "")[:10],
            "window_days": len(recs),
            "min_n": _COUPLING_MIN_N,
            "honest_null": not edges,
        },
        cache_seconds=3600,
    )


def _corr_p_value(p: dict):
    """Serve the stored p-value faithfully, or None when absent.

    The compute lambda rounds p to 4 decimals, so a highly-significant pair
    stores p=0.0 — and the old `float(... or 1)` coerced that 0.0 to 1.0,
    rendering the flagship FDR-significant pair as "p 1.000". Zero is a
    value, not a missing value.
    """
    raw = p.get("p_value", p.get("p"))
    if raw is None:
        return None
    return round(float(raw), 4)


def _corr_strength(r_val: float, stored: str) -> str:
    """Deterministic strength label from |r| (Cohen-style bands).

    The stored `interpretation` has disagreed with the number it sits next
    to (r=0.843 labeled "weak"); the served label must match the served r.
    Falls back to the stored label only for degenerate r=0 rows so
    "insufficient_data" survives.
    """
    a = abs(r_val)
    if a >= 0.7:
        return "strong"
    if a >= 0.4:
        return "moderate"
    if a > 0:
        return "weak"
    return stored or "weak"


def _data_days_this_cycle(*, _g) -> int | None:
    """Days of computed daily metrics since genesis — the honest progress numerator
    a zero-state renders against the arming gates ("currently 3/10"). A cheap
    Select=COUNT on the computed_metrics partition; None (never a fabricated 0)
    when the count can't be measured (#1371, ADR-104)."""
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    table = _g["table"]

    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}computed_metrics") & Key("sk").gte(f"DATE#{EXPERIMENT_START}"),
            Select="COUNT",
        )
        return int(resp.get("Count", 0))
    except Exception as e:
        logger.warning("data_days_this_cycle count failed: %s", e)
        return None


def correlations(event: dict = None, *, _g) -> dict:
    """
    GET /api/correlations
    Returns the most recent weekly correlation matrix (all
    CORRELATION_PAIRS, incl. the #1406 cross-domain edges)
    for the public Correlation Explorer.

    HP-06: When ?featured=true is passed, returns a flat array of
    the top N significant correlations (default 3) for the homepage
    dynamic discoveries section. Response shape changes to:
      {"correlations": [{...}, ...], "week": "...", "count": N}
    so the homepage JS can iterate directly.

    Cache: 3600s.
    """
    table = _g["table"]

    # HP-06: Parse query params
    params: dict[str, Any] = {}
    if event:
        params = event.get("queryStringParameters") or {}
    featured = (params.get("featured") or "").lower() == "true"
    limit = None
    if params.get("limit"):
        try:
            limit = max(1, min(20, int(params["limit"])))
        except (ValueError, TypeError):
            pass

    pk = f"{USER_PREFIX}weekly_correlations"
    resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot weekly correlations
                "KeyConditionExpression": Key("pk").eq(pk),
                "ScanIndexForward": False,
                "Limit": 1,
            }
        )
    )
    items = _decimal_to_float(resp.get("Items", []))
    if not items:
        # Genesis week / weekly-correlation compute hasn't run — shaped-empty 200
        # so the site shows an honest "fills as data accrues" state, not a 503.
        # #1371: the zero-state carries the ENGINE's real arming gates + measured
        # progress, so the page renders a computed trigger, never authored copy.
        return _ok(
            {
                "correlations": [],
                "week": None,
                "start_date": None,
                "end_date": None,
                "count": 0,
                "gates": experiment_gates.correlation_gates(current_n=_data_days_this_cycle(_g=_g)),
            },
            cache_seconds=300,
        )

    record = items[0]
    week = record.get("sk", "").replace("WEEK#", "")
    start_date = record.get("start_date", "")
    end_date = record.get("end_date", "")

    # The compute lambda stores correlations as a dict (label → data).
    # Convert to list for the public API. Also supports legacy "pairs" list format.
    raw_corrs = record.get("correlations", {})
    if isinstance(raw_corrs, list):
        # Legacy format: already a list
        pairs = raw_corrs
    elif isinstance(raw_corrs, dict):
        # Current format: dict keyed by label. Convert to list.
        pairs = []
        for label, data in raw_corrs.items():
            entry = dict(data)
            entry["label"] = label
            pairs.append(entry)
    else:
        pairs = []

    # Human-readable labels and source names for each metric
    _METRIC_META = {
        "hrv": {"label": "Heart Rate Variability", "source": "Whoop"},
        "recovery_score": {"label": "Recovery Score", "source": "Whoop"},
        "sleep_duration": {"label": "Sleep Duration", "source": "Whoop"},
        "sleep_score": {"label": "Sleep Score", "source": "Whoop"},
        "resting_hr": {"label": "Resting Heart Rate", "source": "Whoop"},
        "strain": {"label": "Strain", "source": "Whoop"},
        "tsb": {"label": "Training Stress Balance", "source": "Computed"},
        "training_kj": {"label": "Training Load (kJ)", "source": "Strava"},
        "training_mins": {"label": "Training Minutes", "source": "Strava"},
        "protein_g": {"label": "Protein (g)", "source": "MacroFactor"},
        "calories": {"label": "Calories", "source": "MacroFactor"},
        "carbs_g": {"label": "Carbs (g)", "source": "MacroFactor"},
        "fat_g": {"label": "Fat (g)", "source": "MacroFactor"},
        "steps": {"label": "Steps", "source": "Apple Health"},
        "habit_pct": {"label": "Habit Completion %", "source": "Habitify"},
        "day_grade": {"label": "Day Grade", "source": "Computed"},
        "readiness": {"label": "Readiness Score", "source": "Computed"},
        "tier0_streak": {"label": "Tier 0 Streak", "source": "Computed"},
    }

    public_pairs = []
    for p in pairs:
        metric_a = p.get("metric_a", p.get("field_a", ""))
        metric_b = p.get("metric_b", p.get("field_b", ""))
        meta_a = _METRIC_META.get(metric_a, {})
        meta_b = _METRIC_META.get(metric_b, {})
        r_val = float(p.get("pearson_r", p.get("r", 0)) or 0)
        n_val = int(p.get("n_days", p.get("n", 0)) or 0)
        # #3445: the autocorrelation-corrected effective n stored alongside n_days —
        # None (never coerced to n_val here) lets correlation_evidence fall back to
        # raw n honestly for a record that predates n_eff, rather than us silently
        # asserting a corrected value that was never computed.
        n_eff_val = p.get("n_eff")
        fdr_flag = bool(p.get("fdr_significant", False))
        public_pairs.append(
            {
                "source_a": meta_a.get("source", p.get("source_a", "")),
                "field_a": metric_a,
                "label_a": meta_a.get("label", p.get("label_a", metric_a)),
                "source_b": meta_b.get("source", p.get("source_b", "")),
                "field_b": metric_b,
                "label_b": meta_b.get("label", p.get("label_b", metric_b)),
                "r": round(r_val, 3),
                "p": _corr_p_value(p),
                "n": n_val,
                "strength": _corr_strength(r_val, p.get("interpretation", p.get("strength", ""))),
                "fdr_significant": p.get("fdr_significant", False),
                # #1372/#3445 Evidence Bar: the per-claim rigor readout, computed by
                # the ONE sanctioned pure function (stats_core.correlation_evidence,
                # ADR-105) — never an authored grade. n_eff (not raw n) drives the
                # served level/score; a level flip vs raw n is real, not a bug.
                "evidence": stats_core.correlation_evidence(r_val, n_val, n_eff=n_eff_val, fdr_significant=fdr_flag),
                "correlation_type": p.get("correlation_type", "cross_sectional"),
                "lag_days": int(p.get("lag_days", 0) or 0),
                "description": p.get("description", ""),
                "direction": p.get("direction", ""),
                # DISC-1: counterintuitive flag from compute lambda
                "counterintuitive": p.get("counterintuitive", False),
                "expected_direction": p.get("expected_direction", ""),
                # HP-06: metric labels for homepage cards
                "metric_a": meta_a.get("label", p.get("label_a", metric_a)),
                "metric_b": meta_b.get("label", p.get("label_b", metric_b)),
            }
        )

    # Sort all by absolute r descending
    public_pairs.sort(key=lambda x: -abs(x["r"]))

    # HP-06: Featured mode — return flat array of top significant correlations
    if featured:
        # Filter to significant only (p < 0.05 or FDR-significant).
        # p may be None (absent) — and p=0.0 is maximally significant, not missing.
        significant = [p for p in public_pairs if p.get("fdr_significant") or (p.get("p") is not None and p["p"] < 0.05)]
        # Fall back to strongest by |r| if no significant ones found
        if not significant:
            significant = public_pairs
        # Apply limit (default 3)
        top = significant[: limit or 3]
        # Auto-generate description if missing
        for p in top:
            if not p.get("description"):
                direction = "positive" if p["r"] > 0 else "inverse"
                p["description"] = f"{direction.title()} correlation between " f"{p['metric_a']} and {p['metric_b']} " f"(r={p['r']:.2f})"
        return _ok(
            {
                "correlations": top,
                "week": week,
                "count": len(top),
            },
            cache_seconds=3600,
        )

    # Standard mode — return full object for explorer page
    return _ok(
        {
            "correlations": {
                "week": week,
                "start_date": start_date,
                "end_date": end_date,
                "pairs": public_pairs,
                "count": len(public_pairs),
                "methodology": "Pearson r over 90-day rolling window. Benjamini-Hochberg FDR correction. n-gated strength labels.",
            }
        },
        cache_seconds=3600,
    )
