"""site_api_pairs.py — GET /api/pairs: precomputed pair statistics for the data room (#5532).

REQUIREMENT A (the v9 brief, docs/design/v9/STAGE4_ENGINEERING_PLAN.md §F Phase 2): no
official statistic is computed in the browser. The data room's compare/lag panel draws
what this route serves and nothing else. Every number here comes from
``lambdas/common/stats_core.py`` — the ONE sanctioned statistics module (ADR-105) — and
the ids under ``method_ids`` are the Methods Registry's (`/api/methods`,
``experiment.methods_registry``), so every figure cites its method.

THE FAMILY. The offered metric pairs (below) × every lag in −2…+2 days over the experiment
window (genesis → today) is ONE family: the Benjamini-Hochberg adjustment runs across all
of its tested cells at once, so a reader who scans thirty cells for the brightest one is
shown a q that already paid for the scan. A cell with fewer than ``MIN_N`` paired days
is listed with its n and no statistics — it is not tested and does not join the family.

    {pairs: [{a, b, lag, n, n_eff, r, rho, ci95, p_eff, fdr_q, family_size, window, method_ids}],
     family: {offered, tested}, lags, window, as_of, method_ids}

  * ``lag``   — b is read ``lag`` days after a: a on day d is paired with b on day d+lag.
                A positive lag asks whether today's a goes with a later b.
  * ``n``     — paired days with a measured value on both sides (a logging gap, #5519,
                is not a value and is not paired).
  * ``n_eff`` — the Pyper-Peterman effective n for the two autocorrelated daily series
                (ADR-105 rule 1: raw n overstates the evidence); ``ci95`` and ``p_eff``
                are computed on n_eff, never on n.
  * ``fdr_q`` — the BH-adjusted p across the whole tested family.

NO VERDICT. The payload carries r, rho, the interval, p and q with their n and method — and
no label. Whether a q clears a threshold is the reader's call with the number in front of
them; this route never writes the word for it (tests/test_v9_api_routes_5532.py pins that).

THE READ. The same per-metric reader `/api/series` uses (``site_api_series.series_days``) —
one source of a day's value, so a pair here cannot disagree with the chart beside it.
Cached for an hour: the inputs move once a day.
"""

from __future__ import annotations

from typing import Callable

from common import stats_core
from common.pacific_time import pacific_today, shift_day_key

from web import site_api_series as series
from web.site_api_common import EXPERIMENT_START, _error, _ok, logger

SOURCE = "/api/pairs"
CACHE_SECONDS = 3600
LAGS = (-2, -1, 0, 1, 2)
#: Below this many paired days a cell is listed with its n and nothing else (not tested).
MIN_N = 10
UNAVAILABLE = "The pair table is not served right now."

#: The offered pairs — every key is one `/api/series` serves. Add here, not in the page.
OFFERED_PAIRS: tuple[tuple[str, str], ...] = (
    ("weight_lbs", "hrv"),
    ("weight_lbs", "resting_hr"),
    ("sleep_duration_hours", "total_protein_g"),
    ("deep_pct", "total_protein_g"),
    ("recovery_score", "total_calories_kcal"),
    ("hrv", "sleep_duration_hours"),
)

#: The registry ids of every statistic a tested cell carries, in the order they are applied.
METHOD_IDS = ("pearson_r", "spearman_rho", "effective_sample_size", "pearson_p_value", "fisher_ci", "bh_fdr")


def _round(v, places):
    return None if v is None else round(float(v), places)


def paired(a_vals: dict, b_vals: dict, lag: int) -> tuple[list, list]:
    """``(xs, ys)`` — a on day d beside b on day d+lag, over the days both have a value, in day order."""
    xs, ys = [], []
    for d in sorted(a_vals):
        bd = shift_day_key(d, lag) if lag else d
        if bd in b_vals:
            xs.append(a_vals[d])
            ys.append(b_vals[bd])
    return xs, ys


def cell(a: str, b: str, lag: int, xs: list, ys: list) -> dict:
    """One family cell: the statistics stats_core computes on the paired days, or none below MIN_N."""
    n = len(xs)
    out = {"a": a, "b": b, "lag": lag, "n": n, "n_eff": None, "r": None, "rho": None, "ci95": None, "p_eff": None, "fdr_q": None}
    if n < MIN_N:
        return out
    r = stats_core.pearson_r(xs, ys, min_n=MIN_N)
    n_eff = stats_core.effective_sample_size(xs, ys)
    out.update(
        n_eff=_round(n_eff, 1),
        r=_round(r, 3),
        rho=_round(stats_core.spearman_rho(xs, ys, min_n=MIN_N), 3),
        ci95=[_round(v, 3) for v in stats_core.fisher_ci(r, n_eff)] if r is not None and stats_core.fisher_ci(r, n_eff) else None,
        p_eff=stats_core.pearson_p_value(r, n_eff),
    )
    return out


def compose(values_by_metric: dict[str, dict[str, float]], start: str, end: str, today: str) -> dict:
    """The document — pure: ``{metric: {day: value}}`` in, the family out, FDR across every tested cell."""
    cells = [
        cell(a, b, lag, *paired(values_by_metric.get(a, {}), values_by_metric.get(b, {}), lag)) for a, b in OFFERED_PAIRS for lag in LAGS
    ]
    qs = stats_core.bh_fdr([c["p_eff"] for c in cells])
    tested = sum(1 for c in cells if c["p_eff"] is not None)
    window = {"from": start, "to": end}
    for c, q in zip(cells, qs):
        c["fdr_q"] = _round(q, 6)
        c["p_eff"] = _round(c["p_eff"], 6)
        c["family_size"] = tested
        c["window"] = window
        c["method_ids"] = list(METHOD_IDS) if c["p_eff"] is not None else []
        c["tested"] = c["p_eff"] is not None
    return {
        "pairs": cells,
        "family": {"offered": len(cells), "tested": tested},
        "lags": list(LAGS),
        "lag_meaning": "b is read lag days after a; a on day d is paired with b on day d+lag",
        "min_n": MIN_N,
        "window": window,
        "as_of": today,
        "method_ids": list(METHOD_IDS),
        "source": SOURCE,
    }


def _values(spec: series.SeriesSpec, start: str, end: str, query: Callable) -> dict[str, float]:
    return {d["date"]: d["value"] for d in series.series_days(spec, start, end, query=query) if d["present"]}


def handle_pairs(event, *, query: Callable = series._query_source, today: str | None = None):
    """GET /api/pairs — see the module docstring. ``query`` is the injectable row reader."""
    today = today or pacific_today()
    start, end = EXPERIMENT_START, today
    if start > end:
        return _ok(compose({}, start, end, today), cache_seconds=CACHE_SECONDS)
    metrics = sorted({m for pair in OFFERED_PAIRS for m in pair})
    try:
        values = {m: _values(series.SERIES[m], start, end, query) for m in metrics if series.publishable(series.SERIES[m])}
    except Exception as e:  # noqa: BLE001 — a failed read is a 503, never an empty family
        logger.error(f"[pairs] series read failed: {type(e).__name__}: {e}")
        return _error(503, UNAVAILABLE)
    return _ok(compose(values, start, end, today), cache_seconds=CACHE_SECONDS)
