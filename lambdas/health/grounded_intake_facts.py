"""health/grounded_intake_facts.py — three grounded nutrition and body-composition facts for coach context (#6212, epic #6206).

PURE. Wired by #6291 through ONE reader, ``coach.personal_context``, which loads the series and is reached only
through the coach-context assembly behind its switch (``coach.coach_context_pilot.LIVE``, committed False). The
one-importer guard in ``tests/test_grounded_intake_facts_6212.py`` pins that single importer.

Every function here is pure over series the caller has already loaded: no DynamoDB, no S3, no clock. The one
indirect read is the complete-log line (``complete_log_kcal``), which defaults to the titration rule's own value
(``health.titration.settings()``, the redlines' dark-day kcal) so there is ONE complete-day threshold on the
platform; a caller (and every test) can pass it explicitly.

THE ENTRY POINT is ``build_facts``. It returns a list of fact dicts, each shaped so a context builder can hand it
over as one section::

    {label, as_of, source, statement, uncertainty, basis: {...numbers used...}, limits: [...]}

FACT 1 — logged intake against implied intake (``logged_vs_implied_intake``)
    Window: the trailing ``WINDOW_MAX_DAYS`` days ending ``as_of``, starting no earlier than ``WATER_SHIFT_DAYS``
    after a declared phase start (the early water shift is not tissue). The window must span at least
    ``WINDOW_MIN_DAYS``. Loss rate is the least-squares slope of the weigh-ins in the window. Implied intake is
    mean expenditure minus loss rate x energy density, at both ``KCAL_PER_LB_LOW`` and ``KCAL_PER_LB_HIGH``, then
    widened by the expenditure error band (``EXPENDITURE_ERROR_FRACTION``). The complete-day logged mean is tested
    against the widened range. Verdicts: ``consistent`` / ``logged_below_implied`` / ``logged_above_implied``;
    insufficient data (too few complete days, weigh-ins or expenditure days, no complete-log line, too short a
    window) returns NO fact. Implied intake is never stated as measured intake.

FACT 2 — the stored scan record (``body_composition_scan_record``)
    The most recent stored scan on or before ``as_of``: its date, which provider-agnostic fields it carries, and a
    label — "historical reference, not a baseline for the current phase" unless it is dated inside the phase AND
    its weight is within ``SCAN_WEIGHT_TOLERANCE_LB`` of the phase-start weight. Always carries the caveat that
    scan lean mass is not skeletal muscle. No scan -> a fact saying none is stored, so a coach asserts neither.

FACT 3 — home-scale limits (``home_scale_body_composition_limits``)
    Only when scale body-composition days exist: impedance estimates differ from scan estimates at the individual
    level and cannot alone establish lean-tissue loss (``SCALE_STUDY_ID``). A measured scale-minus-scan offset is
    added only when a scale day and a scan fall within ``SCALE_SCAN_PAIR_DAYS`` of each other.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from common.pacific_time import parse_day_key

logger = logging.getLogger(__name__)

# ── named constants (the only numeric literals of any size in this module) ─────────────────────────

METHOD_ID = "energy-balance reconciliation, research session 2026-11-22 method"

# Energy density of a pound of body-weight change, as a range: the classic figure and a lower one that allows for
# the lean and water share of early loss. Both are textbook assumptions, not measurements of this subject.
KCAL_PER_LB_LOW = 3000
KCAL_PER_LB_HIGH = 3500

# Device expenditure is an ESTIMATE, not a measurement: wrist and phone energy models carry individual errors of
# this order, so the implied-intake range is widened by +/- this fraction of mean expenditure.
EXPENDITURE_ERROR_FRACTION = 0.15

WINDOW_MIN_DAYS = 28
WINDOW_MAX_DAYS = 63
WATER_SHIFT_DAYS = 14  # days after a declared start excluded from the window: early loss is mostly water
MIN_COMPLETE_DAYS = 14
MIN_WEIGH_INS = 8
MIN_EXPENDITURE_DAYS = 14

SCAN_WEIGHT_TOLERANCE_LB = 5.0  # scan weight further than this from phase-start weight -> not a phase baseline
PHASE_START_WEIGHT_SEARCH_DAYS = 7  # how far after the phase start a first weigh-in still counts as its weight
SCALE_SCAN_PAIR_DAYS = 14
SCALE_STUDY_ID = "PMID 21236715"
SCAN_COMPARABLE_FIELDS = ("body_fat_pct", "fat_mass_lb", "lean_mass_lb")

STATEMENT_ROUND_KCAL = 50
BASIS_ROUND_KCAL = 10

VERDICT_CONSISTENT = "consistent"
VERDICT_BELOW = "logged_below_implied"
VERDICT_ABOVE = "logged_above_implied"
VERDICTS = (VERDICT_CONSISTENT, VERDICT_BELOW, VERDICT_ABOVE)

LABEL_INTAKE = "logged_vs_implied_intake"
LABEL_SCAN = "body_composition_scan_record"
LABEL_SCALE = "home_scale_body_composition_limits"

# owner-approved wording (epic #6206, 2026-11-22) — used verbatim for the consistent verdict
CONSISTENT_STATEMENT = (
    "Logged intake appears broadly consistent with substantial real energy restriction and observed weight loss. "
    "Some recent under-logging remains possible, and expenditure estimates introduce meaningful uncertainty. "
    "The evidence does not support assuming that low logged intake is merely a missing export."
)

HISTORICAL_LABEL = "historical reference, not a baseline for the current phase"
CURRENT_PHASE_LABEL = "dated inside the current phase, near the phase-start weight"
LEAN_MASS_CAVEAT = "Lean mass on a scan is not the same as skeletal muscle: it also counts water, organs and other non-fat tissue."

_SENTINEL_READ = "read"


# ── small helpers ─────────────────────────────────────────────────────────────────────────────────


def _day(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str) and len(v) >= 10:
        return parse_day_key(v[:10])  # THE calendar-day parse (#3741)
    return None


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _series(raw: Optional[Mapping[Any, Any]], lo: date, hi: date) -> Dict[date, float]:
    """Parse a ``{day: number}`` mapping into the days inside ``[lo, hi]`` with a readable number."""
    out: Dict[date, float] = {}
    for k, v in (raw or {}).items():
        d, x = _day(k), _num(v)
        if d is not None and x is not None and lo <= d <= hi:
            out[d] = x
    return out


def _round(x: float, step: int) -> int:
    return int(round(x / step) * step)


def _fmt_kcal(x: float) -> str:
    return f"{_round(x, STATEMENT_ROUND_KCAL):,}"


def _slope_per_day(points: Sequence[Tuple[date, float]]) -> Optional[float]:
    """Least-squares slope (units per day) of ``(day, value)`` points; None when undefined."""
    if len(points) < 2:
        return None
    x0 = points[0][0]
    xs = [(d - x0).days for d, _ in points]
    ys = [v for _, v in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx


def default_complete_log_kcal() -> Optional[float]:
    """The platform's ONE complete-log line: the titration rule's ``complete_log_kcal`` (the redlines' dark-day kcal).

    The same value the relapse food-log-gap signal and ``health.checkin_intake_pairs`` read. None when unreadable, and
    Fact 1 is then not built (no second threshold is invented here)."""
    try:
        from health import titration  # noqa: PLC0415 — lazy: keeps this module import-safe offline

        return _num(titration.settings().get("complete_log_kcal"))
    except Exception as e:  # noqa: BLE001 — an unreadable line means no complete-day split, so no Fact 1
        logger.warning("[grounded-intake-facts] complete-log line unreadable: %s", type(e).__name__)
        return None


# ── Fact 1 ────────────────────────────────────────────────────────────────────────────────────────


def intake_fact(
    *,
    as_of: Any,
    intake_by_day: Optional[Mapping[Any, Any]],
    weight_by_day: Optional[Mapping[Any, Any]],
    expenditure_by_day: Optional[Mapping[Any, Any]],
    expenditure_source: str,
    complete_log_kcal: Optional[float],
    phase_start: Any = None,
    expenditure_error: float = EXPENDITURE_ERROR_FRACTION,
    method_id: str = METHOD_ID,
) -> Optional[Dict[str, Any]]:
    """Fact 1, or None when the data cannot support it (never a guess)."""
    end = _day(as_of)
    threshold = _num(complete_log_kcal)
    if end is None or threshold is None:
        return None
    start = end - timedelta(days=WINDOW_MAX_DAYS - 1)
    ps = _day(phase_start)
    if ps is not None:
        start = max(start, ps + timedelta(days=WATER_SHIFT_DAYS))
    span = (end - start).days + 1
    if span < WINDOW_MIN_DAYS:
        return None

    weights = sorted(_series(weight_by_day, start, end).items())
    expenditure = _series(expenditure_by_day, start, end)
    intake = _series(intake_by_day, start, end)
    logged = {d: v for d, v in intake.items() if v > 0}
    complete = {d: v for d, v in logged.items() if v >= threshold}
    n_partial = len(logged) - len(complete)
    n_missing = span - len(logged)

    if len(complete) < MIN_COMPLETE_DAYS or len(weights) < MIN_WEIGH_INS or len(expenditure) < MIN_EXPENDITURE_DAYS:
        return None
    slope = _slope_per_day(weights)
    if slope is None:
        return None

    loss_per_day = -slope  # positive when losing
    mean_exp = sum(expenditure.values()) / len(expenditure)
    central = [mean_exp - loss_per_day * k for k in (KCAL_PER_LB_LOW, KCAL_PER_LB_HIGH)]
    widened = [mean_exp * (1 + s * expenditure_error) - loss_per_day * k for s in (-1, 1) for k in (KCAL_PER_LB_LOW, KCAL_PER_LB_HIGH)]
    implied_lo, implied_hi = min(central), max(central)
    wide_lo, wide_hi = min(widened), max(widened)
    mean_complete = sum(complete.values()) / len(complete)
    mean_all = sum(logged.values()) / len(logged)

    if wide_lo <= mean_complete <= wide_hi:
        verdict = VERDICT_CONSISTENT
        statement = CONSISTENT_STATEMENT
    elif mean_complete < wide_lo:
        verdict = VERDICT_BELOW
        gap_lo, gap_hi = wide_lo - mean_complete, wide_hi - mean_complete
        statement = (
            "Logged intake on complete-log days sits below the intake implied by the weight trend and estimated "
            f"expenditure. Logging may be incomplete by roughly {_fmt_kcal(gap_lo)} to {_fmt_kcal(gap_hi)} kcal a day. "
            "That gap is an estimate from the trend, not a measured shortfall."
        )
    else:
        verdict = VERDICT_ABOVE
        gap_lo, gap_hi = mean_complete - wide_hi, mean_complete - wide_lo
        statement = (
            "Logged intake on complete-log days sits above the intake implied by the weight trend and estimated "
            f"expenditure, by roughly {_fmt_kcal(gap_lo)} to {_fmt_kcal(gap_hi)} kcal a day. Expenditure may be "
            "underestimated, portions may be over-logged, or the weight trend may carry a water change."
        )

    uncertainty = (
        f"Implied intake is an estimate, not a measurement. Expenditure comes from {expenditure_source or 'a device estimate'} "
        f"and is assumed to be off by up to {expenditure_error:.0%} either way; a pound of weight change "
        f"is taken as {KCAL_PER_LB_LOW:,} to {KCAL_PER_LB_HIGH:,} kcal; the trend is a straight line through "
        f"{len(weights)} weigh-ins over {span} days and carries day-to-day water noise."
    )
    limits = [
        "Implied intake is computed from weight trend and estimated expenditure; it is never measured intake.",
        f"The verdict uses complete-log days only ({len(complete)} complete, {n_partial} partial, {n_missing} missing); "
        "partial and missing days may hide intake.",
        f"The first {WATER_SHIFT_DAYS} days after a declared start are excluded because early loss is mostly water.",
        "Under-logging on complete-log days cannot be ruled out by this check.",
    ]
    basis = {
        "verdict": verdict,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "window_days": span,
        "weigh_ins": len(weights),
        "weight_slope_lb_per_week": round(slope * 7, 2),
        "expenditure_days": len(expenditure),
        "mean_expenditure_kcal": _round(mean_exp, BASIS_ROUND_KCAL),
        "expenditure_error_fraction": expenditure_error,
        "kcal_per_lb": [KCAL_PER_LB_LOW, KCAL_PER_LB_HIGH],
        "implied_intake_kcal": [_round(implied_lo, BASIS_ROUND_KCAL), _round(implied_hi, BASIS_ROUND_KCAL)],
        "implied_intake_widened_kcal": [_round(wide_lo, BASIS_ROUND_KCAL), _round(wide_hi, BASIS_ROUND_KCAL)],
        "complete_log_kcal": threshold,
        "complete_days": len(complete),
        "partial_days": n_partial,
        "missing_days": n_missing,
        "logged_mean_complete_days_kcal": _round(mean_complete, BASIS_ROUND_KCAL),
        "logged_mean_all_logged_days_kcal": _round(mean_all, BASIS_ROUND_KCAL),
    }
    return {
        "label": LABEL_INTAKE,
        "as_of": end.isoformat(),
        "source": f"{method_id}; weight: weigh-ins; expenditure: {expenditure_source or 'unnamed estimate'}; intake: food log",
        "statement": statement,
        "uncertainty": uncertainty,
        "basis": basis,
        "limits": limits,
    }


# ── Fact 2 ────────────────────────────────────────────────────────────────────────────────────────


def _scans_up_to(scans: Optional[Iterable[Mapping[str, Any]]], end: date) -> List[Tuple[date, Mapping[str, Any]]]:
    out = []
    for row in scans or ():
        d = _day((row or {}).get("date"))
        if d is not None and d <= end:
            out.append((d, row))
    return sorted(out, key=lambda t: t[0])


def _phase_start_weight(weight_by_day: Optional[Mapping[Any, Any]], phase_start: Optional[date]) -> Optional[float]:
    if phase_start is None:
        return None
    near = sorted(_series(weight_by_day, phase_start, phase_start + timedelta(days=PHASE_START_WEIGHT_SEARCH_DAYS)).items())
    return near[0][1] if near else None


def scan_fact(
    *,
    as_of: Any,
    scans: Optional[Iterable[Mapping[str, Any]]],
    weight_by_day: Optional[Mapping[Any, Any]] = None,
    phase_start: Any = None,
    weight_tolerance_lb: float = SCAN_WEIGHT_TOLERANCE_LB,
    method_id: str = METHOD_ID,
) -> Optional[Dict[str, Any]]:
    """Fact 2: the stored scan record, or an explicit none-stored fact. None only when ``as_of`` is unreadable."""
    end = _day(as_of)
    if end is None:
        return None
    rows = _scans_up_to(scans, end)
    if not rows:
        return {
            "label": LABEL_SCAN,
            "as_of": end.isoformat(),
            "source": f"{method_id}; stored body-composition scan records",
            "statement": (
                "No body-composition scan is stored on the platform. This describes stored records only: "
                "a scan taken elsewhere and never recorded would not appear here."
            ),
            "uncertainty": "Absence from the store says nothing about whether a scan was ever taken.",
            "basis": {"scans_stored": 0},
            "limits": ["Do not assert that no scan exists, and do not cite scan values."],
        }

    scan_day, scan = rows[-1]
    ps = _day(phase_start)
    start_weight = _phase_start_weight(weight_by_day, ps)
    scan_weight = _num(scan.get("weight_lb"))
    in_phase = ps is not None and scan_day >= ps
    weight_close = scan_weight is not None and start_weight is not None and abs(scan_weight - start_weight) <= weight_tolerance_lb
    historical = not (in_phase and weight_close)
    label_text = HISTORICAL_LABEL if historical else CURRENT_PHASE_LABEL
    fields = sorted(k for k, v in scan.items() if k not in ("date", "provider") and _num(v) is not None)

    reasons = []
    if ps is None:
        reasons.append("no phase start was given")
    elif not in_phase:
        reasons.append("it predates the phase start")
    if scan_weight is None or start_weight is None:
        reasons.append("its weight cannot be compared with the phase-start weight")
    elif abs(scan_weight - start_weight) > weight_tolerance_lb:
        reasons.append(f"its weight differs from the phase-start weight by more than {weight_tolerance_lb:g} lb")

    statement = f"A body-composition scan dated {scan_day.isoformat()} is stored; treat it as a {label_text}."
    if historical and reasons:
        statement += f" It is historical because {' and '.join(reasons)}."
    statement += " " + LEAN_MASS_CAVEAT
    basis: Dict[str, Any] = {
        "scans_stored": len(rows),
        "scan_date": scan_day.isoformat(),
        "earlier_scan_dates": [d.isoformat() for d, _ in rows[:-1]],
        "fields_present": fields,
        "historical": historical,
        "phase_start": ps.isoformat() if ps else None,
        "weight_tolerance_lb": weight_tolerance_lb,
        "scan_weight_minus_phase_start_weight_lb": (
            round(scan_weight - start_weight, 1) if scan_weight is not None and start_weight is not None else None
        ),
    }
    return {
        "label": LABEL_SCAN,
        "as_of": end.isoformat(),
        "source": f"{method_id}; stored body-composition scan records",
        "statement": statement,
        "uncertainty": "A scan is one dated estimate with its own measurement error; it describes the body on that date only.",
        "basis": basis,
        "limits": [
            "Do not use a historical scan as the starting point for the current phase.",
            "Scan lean mass is not skeletal muscle.",
        ],
    }


# ── Fact 3 ────────────────────────────────────────────────────────────────────────────────────────


def _closest_pair(
    scale: Mapping[date, Mapping[str, Any]], scans: Sequence[Tuple[date, Mapping[str, Any]]]
) -> Optional[Tuple[date, Mapping[str, Any], date, Mapping[str, Any]]]:
    best = None
    for sd, srow in scale.items():
        for cd, crow in scans:
            gap = abs((sd - cd).days)
            if gap > SCALE_SCAN_PAIR_DAYS:
                continue
            if not any(_num(srow.get(f)) is not None and _num(crow.get(f)) is not None for f in SCAN_COMPARABLE_FIELDS):
                continue
            if best is None or gap < best[0]:
                best = (gap, sd, srow, cd, crow)
    return None if best is None else best[1:]


def scale_fact(
    *,
    as_of: Any,
    scale_bodycomp_days: Optional[Mapping[Any, Any]],
    scans: Optional[Iterable[Mapping[str, Any]]] = None,
    method_id: str = METHOD_ID,
) -> Optional[Dict[str, Any]]:
    """Fact 3, only when scale body-composition days exist; None otherwise."""
    end = _day(as_of)
    if end is None:
        return None
    scale: Dict[date, Mapping[str, Any]] = {}
    for k, v in (scale_bodycomp_days or {}).items():
        d = _day(k)
        if d is not None and d <= end and isinstance(v, Mapping) and any(_num(x) is not None for x in v.values()):
            scale[d] = v
    if not scale:
        return None

    last = max(scale)
    statement = (
        f"Home-scale body-composition readings (bioelectrical impedance) are stored for {len(scale)} day(s), most "
        f"recently {last.isoformat()}. Impedance estimates differ from scan estimates at the individual level and "
        "cannot by themselves establish lean-tissue loss."
    )
    basis: Dict[str, Any] = {"scale_days": len(scale), "last_scale_day": last.isoformat(), "offset": None}
    pair = _closest_pair(scale, _scans_up_to(scans, end))
    if pair is not None:
        sd, srow, cd, crow = pair
        offsets = {}
        for f in SCAN_COMPARABLE_FIELDS:
            a, b = _num(srow.get(f)), _num(crow.get(f))
            if a is not None and b is not None:
                offsets[f] = round(a - b, 1)
        basis["offset"] = {"scale_day": sd.isoformat(), "scan_day": cd.isoformat(), "scale_minus_scan": offsets}
        parts = [f"{f.replace('_', ' ')} {v:+g}" for f, v in offsets.items()]
        statement += (
            f" On the closest pair (scale {sd.isoformat()}, scan {cd.isoformat()}, {abs((sd - cd).days)} day(s) apart) "
            f"the scale minus the scan read: {', '.join(parts)}. One pair is an offset on one occasion, not a calibration."
        )
    return {
        "label": LABEL_SCALE,
        "as_of": end.isoformat(),
        "source": f"{method_id}; comparison study {SCALE_STUDY_ID}",
        "statement": statement,
        "uncertainty": "Impedance readings move with hydration, food and time of day, often by more than a real week's change.",
        "basis": basis,
        "limits": [
            "Do not read a scale lean-mass drop as muscle loss.",
            "Scale and scan numbers are not interchangeable.",
        ],
    }


# ── entry point ───────────────────────────────────────────────────────────────────────────────────


def build_facts(
    *,
    as_of: Any,
    intake_by_day: Optional[Mapping[Any, Any]],
    weight_by_day: Optional[Mapping[Any, Any]],
    expenditure_by_day: Optional[Mapping[Any, Any]],
    expenditure_source: str,
    scans: Optional[Iterable[Mapping[str, Any]]],
    scale_bodycomp_days: Optional[Mapping[Any, Any]],
    phase_start: Any = None,
    complete_log_kcal: Any = _SENTINEL_READ,
    expenditure_error: float = EXPENDITURE_ERROR_FRACTION,
    scan_weight_tolerance_lb: float = SCAN_WEIGHT_TOLERANCE_LB,
    method_id: str = METHOD_ID,
) -> List[Dict[str, Any]]:
    """The grounded facts that the inputs support, in order: intake (if sufficient), scan record, scale limits (if any).

    ``complete_log_kcal`` defaults to the platform's one complete-log line (``default_complete_log_kcal``)."""
    threshold = default_complete_log_kcal() if complete_log_kcal == _SENTINEL_READ else _num(complete_log_kcal)
    scan_rows = list(scans or ())
    facts = [
        intake_fact(
            as_of=as_of,
            intake_by_day=intake_by_day,
            weight_by_day=weight_by_day,
            expenditure_by_day=expenditure_by_day,
            expenditure_source=expenditure_source,
            complete_log_kcal=threshold,
            phase_start=phase_start,
            expenditure_error=expenditure_error,
            method_id=method_id,
        ),
        scan_fact(
            as_of=as_of,
            scans=scan_rows,
            weight_by_day=weight_by_day,
            phase_start=phase_start,
            weight_tolerance_lb=scan_weight_tolerance_lb,
            method_id=method_id,
        ),
        scale_fact(as_of=as_of, scale_bodycomp_days=scale_bodycomp_days, scans=scan_rows, method_id=method_id),
    ]
    return [f for f in facts if f is not None]
