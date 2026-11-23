"""mcp/experiment_close.py — the pre-registered close path (#539) and the write-once lift baseline snapshot (#6209).

Split out of ``mcp/tools_lifestyle.py`` (at its #1665 module-size ceiling) when #6209 gave the close path a second job.
``tools_lifestyle._run_design_analysis`` stays the entry point — a thin wrapper that injects that module's reads, so
every test that patches ``tools_lifestyle.query_source`` / ``table`` / ``datetime`` still reaches this code.

THE BASELINE SNAPSHOT (owner condition 2026-11-23: "baseline strength values are immutable, timestamped experiment
snapshots"). A design whose criterion is a lift metric gets ``baseline_snapshot`` on its experiment row:

* captured at ``create_experiment`` when the baseline window is already complete (start today or earlier);
* otherwise (a future or randomized start) captured at the first analysis-path read on or after the start, and marked
  ``captured_after_start`` with ``capture_lag_days``;
* written with ``attribute_not_exists(baseline_snapshot)`` — it can never be overwritten; a second capture is a no-op
  that returns the stored one;
* READ by the close path, which never recomputes a reference. A lift experiment that reaches close with no snapshot
  and cannot capture one closes ``inconclusive`` with reason ``no_baseline_snapshot``.

The snapshot is PRIVATE: no public reader projects it (``site_api_protocols`` allowlists ``analysis`` keys and never
reads ``baseline_snapshot``; the public pre-registration artifact is written before it exists and never carries it).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Callable

from experiment import experiment_design, lift_outcomes

from mcp.config import EXPERIMENTS_PK, logger
from mcp.experiment_metrics import _extract_metric
from mcp.helpers import normalize_whoop_sleep

ANALYSIS_ENGINE = "n1-design-v1"


def _plain(v: Any) -> Any:
    """DynamoDB Decimals → floats (and a deep copy), so a stored snapshot reads exactly like a fresh one."""
    return json.loads(json.dumps(v, default=float))


def lift_metric_of(design: Any) -> str | None:
    metric = ((design or {}).get("criterion") or {}).get("metric") if isinstance(design, dict) else None
    return metric if lift_outcomes.is_lift_metric(metric) else None


def _baseline_window(start_date: str, design: dict) -> tuple[str, str]:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    return (
        (start - timedelta(days=int(design["baseline_days"]))).strftime("%Y-%m-%d"),
        (start - timedelta(days=1)).strftime("%Y-%m-%d"),
    )


def _conditional_failed(e: Exception) -> bool:
    code = ((getattr(e, "response", None) or {}).get("Error") or {}).get("Code")
    return code == "ConditionalCheckFailedException" or type(e).__name__ == "ConditionalCheckFailedException"


def ensure_baseline_snapshot(existing: dict, *, query_source: Callable, table: Any, now: datetime, today: str) -> dict | None:
    """Return the experiment's baseline snapshot, capturing it (write-once) if it is due and absent.

    None when the design has no lift criterion, the start is still in the future, or the write failed for any reason
    other than "already captured" (then the stored one is re-read and returned)."""
    stored = existing.get("baseline_snapshot")
    if stored:
        return _plain(stored)
    design = _plain(existing.get("design") or {})
    if lift_metric_of(design) is None:
        return None
    start = str(existing.get("start_date") or "")
    if not start or start > today:
        return None
    ws, we = _baseline_window(start, design)
    snap = lift_outcomes.capture_baseline(
        query_source(lift_outcomes.LIFT_SOURCE, ws, we),
        ws,
        we,
        start_date=start,
        captured_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        today=today,
    )
    key = {"pk": EXPERIMENTS_PK, "sk": existing["sk"]}
    try:
        table.update_item(
            Key=key,
            UpdateExpression="SET baseline_snapshot = :b",
            ConditionExpression="attribute_not_exists(baseline_snapshot)",
            ExpressionAttributeValues={":b": json.loads(json.dumps(snap), parse_float=Decimal)},
        )
    except Exception as e:  # noqa: BLE001
        if not _conditional_failed(e):
            logger.warning(f"baseline snapshot write failed for {existing.get('sk')}: {e}")
            return None
        again = (table.get_item(Key=key).get("Item") or {}).get("baseline_snapshot")
        return _plain(again) if again else None
    existing["baseline_snapshot"] = snap
    return snap


def on_create(item: dict, *, query_source: Callable, table: Any, now: datetime, today: str) -> dict:
    """create_experiment's lift hook: capture the snapshot when due, and the advisory ``baseline_note``. {} otherwise."""
    metric = lift_metric_of(_plain(item.get("design") or {}))
    if metric is None:
        return {}
    snap = ensure_baseline_snapshot(item, query_source=query_source, table=table, now=now, today=today)
    out: dict[str, Any] = {"baseline_snapshot_captured_at": snap.get("captured_at") if snap else None}
    note = lift_outcomes.baseline_note(snap, metric, str(item.get("start_date")))
    if note:
        out["baseline_note"] = note
    return out


def run_design_analysis(
    existing: dict, design: dict, end_date: str, *, query_source: Callable, metric_query: Callable, table: Any, now: datetime, today: str
) -> dict:
    """#539: the deterministic close-path analysis for a pre-registered design.

    Fetches the criterion metric's daily series for the baseline window and the
    washout-trimmed intervention window, then evaluates against the frozen
    criterion via experiment_design (stats_core underneath). Returns the analysis
    dict (windows + stats + verdict + summary sentence), or the washout refusal.
    #6209: a lift criterion reads its baseline from the write-once snapshot."""
    design_f = json.loads(json.dumps(design, default=float))  # Decimals → floats for math
    windows = experiment_design.design_windows(existing.get("start_date", ""), end_date, design_f)
    if windows is None:
        return {
            "verdict": "inconclusive",
            "summary": "Washout consumed the whole experiment window — no analysis possible.",
            "windows": None,
        }
    metric = (design_f.get("criterion") or {}).get("metric", "")
    source, field, _label = experiment_design.DESIGN_METRICS[metric]
    analyzed_at = now.strftime("%Y-%m-%dT%H:%M:%S")

    snapshot = None
    if lift_outcomes.is_lift_metric(field):
        snapshot = ensure_baseline_snapshot(existing, query_source=query_source, table=table, now=now, today=today)
        if snapshot is None:
            return {
                "windows": windows,
                "metric": metric,
                "verdict": "inconclusive",
                "reason": lift_outcomes.NO_BASELINE_SNAPSHOT,
                "summary": "No baseline snapshot exists and none could be captured — no analysis; references are never recomputed.",
                "analyzed_at": analyzed_at,
                "engine": ANALYSIS_ENGINE,
            }

    def _dated_values(start, end, metric_source=None, metric_field=None):
        """date → value over [start, end] (last record wins on a duplicate date).
        Defaults to the criterion metric; #1410's control series pass their own
        source/field (from DESIGN_METRICS) through the same fetch path."""
        src = metric_source or source
        fld = metric_field or field
        if lift_outcomes.is_lift_metric(fld):  # #6209: baseline days from the snapshot, the rest against its references
            return lift_outcomes.read_series(query_source, src, fld, windows, start, end, snapshot)
        items = metric_query(src, start, end)
        if src == "whoop":
            items = [normalize_whoop_sleep(i) for i in items]
        out = {}
        for it in items:
            v = _extract_metric(it, fld)
            date = str(it.get("sk", ""))[5:15]  # sk = "DATE#YYYY-MM-DD..."
            if v is not None and len(date) == 10:
                out[date] = v
        return out

    baseline_vals = [v for _d, v in sorted(_dated_values(windows["baseline_start"], windows["baseline_end"]).items())]
    window_vals = [v for _d, v in sorted(_dated_values(windows["analysis_start"], windows["analysis_end"]).items())]
    stats = experiment_design.evaluate_design(design_f, baseline_vals, window_vals)
    lift_outcomes.attach_observations(stats, query_source, source, field, windows, snapshot)  # #6209: raw observations

    # #1413 SCED: a randomized-start design ALSO closes with the start-point
    # randomization test — the observed pre/post difference ranked against every
    # start the pre-declared window could have produced (exact under the draw
    # actually performed, valid under autocorrelation). Reported alongside the
    # effect+CI, with provenance; the frozen #539 verdict rule is unchanged.
    if design_f.get("randomized_start"):
        series_start = experiment_design.randomization_series_start(design_f)
        if series_start:
            dated = _dated_values(series_start, end_date)
            rand = experiment_design.randomization_test(design_f, dated, existing.get("start_date", ""), end_date)
            if rand is not None:
                stats["randomization"] = rand

    # #1410: a design that froze a counterfactual spec closes with the ghost —
    # observed vs the BSTS-lite forecast of "had the experiment never started",
    # or a stated refusal (bad pre-fit / thin data). The spec comes from the
    # frozen design; every number from experiment_design/bsts_lite — the LLM
    # narration layer only ever reads the precomputed block (ADR-062/105).
    if design_f.get("counterfactual") is not None:
        cf_start_date = existing.get("start_date", "")
        cf_series_start = experiment_design.counterfactual_series_start(design_f, cf_start_date)
        dated_criterion = _dated_values(cf_series_start, end_date)
        dated_controls = {}
        for cm in design_f["counterfactual"].get("controls") or []:
            c_src, c_field, _cl = experiment_design.DESIGN_METRICS[cm]
            dated_controls[cm] = _dated_values(cf_series_start, end_date, metric_source=c_src, metric_field=c_field)
        stats["counterfactual"] = experiment_design.counterfactual_analysis(
            design_f, dated_criterion, dated_controls, cf_start_date, end_date
        )

    return {
        "windows": windows,
        "metric": metric,
        **stats,
        "summary": experiment_design.analysis_summary(design_f, stats),
        "analyzed_at": analyzed_at,
        "engine": ANALYSIS_ENGINE,
    }
