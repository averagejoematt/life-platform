"""grading_quality.py — what the grader says about its own grade (#5533, epic #5529).

Rendering every prediction on the v9 ledger exposed five evaluator defects (the 2026-10-31
audit, Stage 4 plan §F Phase 3). Three of the five are *interpretation* rules the grader
needs and ``coach_prediction_evaluator`` (at its module-size baseline, #1665) has no room
for, so they live here and the evaluator calls them:

(a) **Quality flags** — every row the evaluator grades from now on carries
    ``quality_flags`` ⊆ {``logging_gap``, ``low_power``, ``proxy_metric``} and an
    ``evaluator_version``, emitted from the record itself:

      * ``logging_gap``  — the grading window contains a zero-entry behavioral day
        (``is_zero_entry_day``): the grade ran through a day on which nothing was logged.
      * ``low_power``    — the band (direction call) or the tolerance (number call) is at
        least ``LOW_POWER_RATIO`` of |first value| / |predicted|: a grade almost any outcome
        would have satisfied or refuted by noise.
      * ``proxy_metric`` — the metric graded is not the metric the claim names. No emitted
        record carries a declared-metric field separate from ``evaluation.metric`` (the
        extractor's hint IS the spec's metric — ``prediction_emission.resolve_eval_spec``),
        so this is DERIVED, conservatively: a row is flagged only when its ``claim_natural``
        names NONE of the graded base metric's aliases (the metric key's own tokens, every
        prose needle ``measurable_metrics`` normalizes to it, and its units). A claim that
        says "sleep score" while the grader read ``recovery_score`` is NOT caught (both
        share the token "score") — the flag under-reports rather than invents, and a row
        with no claim text is never flagged.

(c) **A zero-entry behavioral day is missing, not a default** — the #5519 class. A
    MacroFactor row written from a summary export for a day with no diary entries carries
    ``entries_count = 0`` beside a pre-filled scheduled item's ~80 kcal / ~15 g, and the
    grader read those numbers as intake. ``is_zero_entry_day`` is the predicate the
    evaluator's ``_extract_metric_series`` applies: such a row yields no reading, the
    window's n drops accordingly, and a window below the minimum readings goes
    inconclusive — and expires — by the existing rules, never graded on the default.
    Nothing stored changes (owner rule 2026-10-04: capture all, interpret later); only how
    the grader reads it.

(e) **The HR regime marker** — ``health.hr_regime`` declares the 2026-10-10 marker after
    which heart-rate-derived numbers no longer compare with what came before; readiness
    and ACWR read it, grading did not. ``regime_adjust`` applies the module's own rules to
    a direction or number call on an HR metric whose window spans the marker: the window
    is re-baselined to start the day after the marker (``hr_regime.baseline_window``), AF
    days are excluded (``hr_regime.af_days_from`` through the evaluator's own fetch), a
    number call whose target was priced before the marker and falls after it has no
    single-regime comparison and is inconclusive, and ``outcome_notes`` names the boundary.

Pure over injected I/O: the evaluator hands in its own ``extract_metric_series`` /
``_fetch_range`` and its ``data_cache``; no clock is read (every function takes the day it
reasons about).
"""

from __future__ import annotations

import re
from typing import Any, Callable

from common.pacific_time import parse_day_key, shift_day_key
from experiment.measurable_metrics import _METRIC_HINT_NORMALIZERS, METRIC_SOURCES, METRIC_SUBDOMAIN, base_metric
from health import hr_regime

#: The grading-rule version stamped on every graded row and every correction (the
#: evaluator's ``ALGO_VERSION`` is this value). 1.0 = the rules before #5533.
EVALUATOR_VERSION = "1.1"

#: The closed vocabulary. A reader of the row never sees a flag outside it.
FLAGS = ("logging_gap", "low_power", "proxy_metric")

#: A band or tolerance at or above this share of the value it is measured against is low
#: power — ADR-105 provenance: editorial (owner brief 2026-10-31, "≥ 35%"); re-derive
#: against the corpus once a season of flagged rows exists.
LOW_POWER_RATIO = 0.35

#: The subdomains whose metrics are computed from heart rate (``METRIC_SUBDOMAIN`` values).
_HR_SUBDOMAINS = frozenset({"hrv", "recovery"})
#: Every registry metric that is heart-rate-derived — derived from the subdomain map, never listed.
HR_METRICS = frozenset(m for m, sd in METRIC_SUBDOMAIN.items() if sd in _HR_SUBDOMAINS)

#: Key tokens that name a shape, not a quantity, and so never identify a metric in prose.
_GENERIC_TOKENS = frozenset({"total", "avg", "pct", "std", "dev"})

# The reason prefix a regime-adjusted grade carries, so a reader of the raw row can tell.
REGIME_MARKER = "[hr-regime]"


# ── (c) a zero-entry behavioral day ──────────────────────────────────────────────────────


def is_zero_entry_day(rec: Any) -> bool:
    """True for a behavioral source's row on which nothing was logged.

    The predicate is the row's own ``entries_count`` (MacroFactor writes it on every
    nutrient-carrying row: the diary's entry count, or 0 on a summary-only row) read as
    zero with no ``food_log`` entries. A row without the field is not judged — a scalar
    partial carries no intake fields anyway. Any behavioral source that adopts
    ``entries_count`` gets the same reading.
    """
    if not isinstance(rec, dict) or "entries_count" not in rec:
        return False
    try:
        n = int(float(rec.get("entries_count") or 0))
    except (TypeError, ValueError):
        n = 0
    return n <= 0 and not rec.get("food_log")


def _row_day(rec: dict) -> str:
    return str(rec.get("date") or str(rec.get("sk") or "").replace("DATE#", ""))[:10]


def zero_entry_days(records: Any, start: str, end: str) -> list[str]:
    """The zero-entry days among ``records`` inside [start, end], sorted."""
    out = set()
    for rec in records or []:
        if is_zero_entry_day(rec):
            d = _row_day(rec)
            if d and start <= d <= end:
                out.add(d)
    return sorted(out)


def cached_source_records(source: str | None, data_cache: dict | None) -> list:
    """Every record the evaluator has already read for ``source`` this run — the union of
    its ``source_cache_key`` slots. Reads the cache only; never a query."""
    if not source or not data_cache:
        return []
    seen: dict[str, dict] = {}
    for key, records in data_cache.items():
        if not str(key).startswith(f"{source}:"):
            continue
        for rec in records or []:
            if isinstance(rec, dict):
                seen.setdefault(_row_day(rec) or str(id(rec)), rec)
    return list(seen.values())


# ── (e) the HR regime marker ─────────────────────────────────────────────────────────────


def is_hr_metric(metric_key: Any) -> bool:
    return bool(metric_key) and base_metric(metric_key) in HR_METRICS


def _days_between(start: str, end: str) -> int:
    a, b = parse_day_key(start), parse_day_key(end)
    if a is None or b is None:
        return 0
    return (b - a).days


def window_end(pred: dict, eval_spec: dict, window_days: Any, today_str: str) -> str | None:
    """The last day a call's grade may read: a number call's ``target_date``, else the
    stated window after filing; never after ``today_str``. None when undated."""
    created = str((pred or {}).get("created_date") or "")[:10]
    if parse_day_key(created) is None:
        return None
    end = str((eval_spec or {}).get("target_date") or "")[:10] if (eval_spec or {}).get("type") == "point" else ""
    if parse_day_key(end) is None:
        try:
            end = shift_day_key(created, int(window_days))
        except (TypeError, ValueError):
            return None
    return min(end, str(today_str)[:10])


def regime_split(created: str, end: str) -> dict | None:
    """The marker a window [created, end] spans, per ``hr_regime.baseline_window`` — None
    when the window sits inside one regime. ``since`` is the first gradable day."""
    try:
        since, trunc = hr_regime.baseline_window(created, end)
    except ValueError:
        return None
    if not trunc:
        return None
    return {"marker_date": trunc["truncated_at_marker"], "requested_start": created, "since": since, "window_end": end}


def _inconclusive(reason: str, regime: dict) -> dict:
    # A COPY of the note: the caller stores this verdict on the same dict, and a note that held
    # its own verdict would be a cycle no outcome_notes JSON could carry.
    return {"status": "inconclusive", "reason": reason, "actual_value": None, "beats_null": False, "hr_regime": dict(regime)}


def _af_days(fetch_range: Callable | None, since: str, end: str, data_cache: dict | None) -> set[str]:
    if fetch_range is None:
        return set()
    key = f"af_days:{since}:{end}"
    if data_cache is not None and key in data_cache:
        return set(data_cache[key])
    anchor = parse_day_key(since)
    try:
        days = set(hr_regime.af_days_from(fetch_range, anchor, end)) if anchor else set()
    except Exception:  # noqa: BLE001 — a failed AF read excludes nothing and says so in the note
        days = set()
    if data_cache is not None:
        data_cache[key] = sorted(days)
    return days


def regime_adjust(
    pred: dict,
    eval_spec: dict,
    window_days: Any,
    today_str: str,
    extract_metric_series: Callable,
    fetch_range: Callable | None = None,
    data_cache: dict | None = None,
) -> tuple[dict, Any, Callable, dict | None]:
    """``(pred, window_days, series_fn, regime)`` for one call — unchanged, with
    ``regime=None``, unless the call is on an HR metric and its window spans a marker.

    A direction call is re-baselined: it is graded over [the day after the marker, its
    stated end] (``pred`` comes back with that ``created_date`` and ``window_days`` the
    remaining span) on a series that excludes the marker's transition day, every day before
    it and the AF days ``hr_regime`` excludes. A number call cannot be re-baselined — its
    target and tolerance were priced in the old regime — so ``regime["verdict"]`` carries the
    inconclusive result the evaluator returns as-is. The marker is named in both.
    """
    metric = (eval_spec or {}).get("metric")
    created = str((pred or {}).get("created_date") or "")[:10]
    end = window_end(pred, eval_spec, window_days, today_str)
    if not is_hr_metric(metric) or not end or created >= end:
        return pred, window_days, extract_metric_series, None
    split = regime_split(created, end)
    if split is None:
        return pred, window_days, extract_metric_series, None
    marker = split["marker_date"]
    if (eval_spec or {}).get("type") == "point":
        split["verdict"] = _inconclusive(
            f"{REGIME_MARKER} {metric}: the call was filed {created} and its target day {end} falls after the {marker} HR regime "
            f"marker (health.hr_regime); a level priced in the earlier regime has no single-regime comparison",
            split,
        )
        return pred, window_days, extract_metric_series, split
    since = split["since"]
    remaining = _days_between(since, end)
    if remaining <= 0:
        split["verdict"] = _inconclusive(
            f"{REGIME_MARKER} {metric}: the window {created}..{end} ends on the {marker} HR regime marker's transition day "
            "(health.hr_regime); nothing after the marker to grade",
            split,
        )
        return pred, window_days, extract_metric_series, split
    excluded = _af_days(fetch_range, since, end, data_cache)
    split["excluded_days_n"] = len(excluded)

    def series_fn(records: Any, base: str) -> list:
        return [(d, v) for d, v in extract_metric_series(records, base) if str(d)[:10] >= since and str(d)[:10] not in excluded]

    return dict(pred, created_date=since), remaining, series_fn, split


def note_regime(result: dict | None, regime: dict | None) -> dict | None:
    """Attach the regime note to a graded result and name the boundary in its reason."""
    if not result or not regime:
        return result
    out = dict(result)
    out["hr_regime"] = {k: v for k, v in regime.items() if k != "verdict"}
    if not str(out.get("reason") or "").startswith(REGIME_MARKER):
        out["reason"] = (
            f"{REGIME_MARKER} graded from {regime['since']} (re-baselined after the {regime['marker_date']} HR regime marker, "
            f"health.hr_regime; the call asked from {regime['requested_start']}) " + str(out.get("reason") or "")
        )
    return out


# ── (a) the flags ────────────────────────────────────────────────────────────────────────


def metric_aliases(metric_key: str) -> list[str]:
    """Every way prose names ``metric_key``'s base metric: the key and its tokens (shape
    tokens dropped), every normalizer needle that maps to it, and its units."""
    base = base_metric(metric_key).lower()
    names = {base, base.replace("_", " ")}
    names |= {tok for tok in base.split("_") if len(tok) >= 3 and tok not in _GENERIC_TOKENS}
    names |= {needle for needle, target in _METRIC_HINT_NORMALIZERS if target == base}
    try:
        from coach.prediction_emission import _METRIC_UNITS  # the one unit table (#3551); same package

        names |= set(_METRIC_UNITS.get(base, ()))
    except ImportError:  # pragma: no cover
        pass
    return sorted(n for n in names if n)


def claim_names_metric(claim: Any, metric_key: Any) -> bool | None:
    """Does the claim sentence name the graded metric? None when there is no sentence or no
    metric to compare — the flag is never derived from an absence."""
    text = str(claim or "").lower()
    if not text.strip() or not metric_key:
        return None
    for alias in metric_aliases(str(metric_key)):
        if alias.isalnum() or " " in alias or "_" in alias:
            if re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z])", text):
                return True
        elif alias in text:
            return True
    return False


def low_power(eval_spec: dict, result: dict) -> bool:
    """Band / tolerance at or above ``LOW_POWER_RATIO`` of the value it is measured against.
    Only a direction call (its own ``noise_band``, already fractional) or a number call
    (tolerance over |predicted|) has a band; a threshold or count call is never low power."""
    t = (eval_spec or {}).get("type")
    if (result or {}).get("evaluation_type") == "count":
        return False
    if t == "point":
        try:
            tol, target = float(eval_spec.get("tolerance")), float(eval_spec.get("threshold"))
        except (TypeError, ValueError):
            return False
        return True if target == 0 else abs(tol / target) >= LOW_POWER_RATIO
    band = (result or {}).get("noise_band")
    if band is None:
        return False
    try:
        return abs(float(band)) >= LOW_POWER_RATIO
    except (TypeError, ValueError):
        return False


def quality_flags(pred: dict, eval_spec: dict, result: dict, data_cache: dict | None, *, start: str, end: str) -> list[str]:
    """The flags for one graded call, in ``FLAGS`` order; empty = clean."""
    spec = eval_spec or {}
    res = result or {}
    graded = str(res.get("metric") or spec.get("metric") or "")
    flags = []
    if graded and zero_entry_days(cached_source_records(METRIC_SOURCES.get(base_metric(graded)), data_cache), start, end):
        flags.append("logging_gap")
    if low_power(spec, res):
        flags.append("low_power")
    named = claim_names_metric((pred or {}).get("claim_natural"), graded)
    declared = spec.get("metric")
    if named is False or (graded and declared and base_metric(graded) != base_metric(str(declared))):
        flags.append("proxy_metric")
    return flags


def stamp(pred: dict, eval_spec: dict, result: dict, data_cache: dict | None, effective_window: Any, today_str: str) -> dict:
    """The quality fields the evaluator merges into its evaluation dict for every graded
    row: ``quality_flags``, ``evaluator_version`` and, when the grade was regime-adjusted,
    ``hr_regime``. Never raises — a grade is never lost to its own annotation."""
    try:
        created = str((pred or {}).get("created_date") or "")[:10]
        raw_window = (result or {}).get("window")
        window: dict = raw_window if isinstance(raw_window, dict) else {}
        end = str(window.get("end") or window_end(pred, eval_spec, effective_window, today_str) or today_str)[:10]
        start = str(window.get("start") or created or end)[:10]
        flags = quality_flags(pred, eval_spec, result, data_cache, start=start, end=end)
    except Exception:  # noqa: BLE001
        flags = []
    out: dict[str, Any] = {"quality_flags": flags, "evaluator_version": EVALUATOR_VERSION}
    if isinstance((result or {}).get("hr_regime"), dict):
        out["hr_regime"] = {k: v for k, v in result["hr_regime"].items() if k != "verdict"}
    return out


def is_clean(row: dict) -> bool | None:
    """True when a graded row was assessed and carries no flag, False when it carries one,
    None when the row predates the flags (no ``quality_flags`` attribute) — a reader must
    never count an unassessed row as clean."""
    flags = (row or {}).get("quality_flags")
    if flags is None:
        return None
    return not list(flags)
