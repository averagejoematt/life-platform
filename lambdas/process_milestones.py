"""
process_milestones.py — window-validated process milestones (#1628).

Every milestone here is a PURE WINDOW FUNCTION over stored metrics: given the
same series and the same evaluation date, it returns the same verdict. There
are deliberately NO day-triggered variants ("did X happen today") — a milestone
is a property of a window, not of a day (the Personal Board's framing, issue
#1628 / docs/BOARDS.md). Each definition carries its window length, threshold
and minimum n explicitly (the `DEFINITIONS` registry below is the introspection
surface tests pin).

The set, ranked (this order is the ledger's LADDER_PRIORITY):

1. **return_after_gap** — trained again within RETURN_WITHIN_DAYS of a missed
   week. The highest-value milestone on the evidence: Matthew has never had
   trouble starting, only RE-starting, and a return-after-a-gap is the exact
   behaviour whose absence ended every previous cycle. Identity is anchored to
   the return date (a dated past fact, the #1626 ledger philosophy), so each
   distinct restart is a distinct write-once event — the one milestone that can
   honestly recur.
2. **sustained_sessions** — training days/week has NOT DECLINED over 8+ weeks.
   Phrased and computed as a non-decline (second-half mean >= first-half mean,
   with a per-week floor), never as a peak: the documented failure mode is
   5 → 3 → 1 → 0, and a peak-then-decline series must not fire it.
3. **strength_in_deficit** — strength volume maintained while in a caloric
   deficit (the composition proof that the right mass is being lost). Requires
   BOTH signals present with sufficient n; missing either yields NO milestone —
   never a partial claim (ADR-104).
4. **zone2_accumulation** — Zone 2 minutes accumulated over a 4-week window.
5. **rhr_hrv_trend** — 30-day RHR down AND HRV up versus the previous 30 days,
   each beyond the standard error of its own difference (threshold derived from
   personal variance, ADR-105 rule 4 — not a hand-set population constant).
6. **waist_change** — trailing 14-day mean navel waist under an absolute rung
   (absolute, not delta-from-baseline: baselines re-anchor at every experiment
   reset, so only an absolute rung is a lifetime fact — the #1626 weight-rung
   reasoning).

Weight is NOT in this module and ranks LAST in the ledger: a weight milestone
is structurally prevented from emitting alone — it may only be written as a
companion to a process/composition milestone (enforced in
milestone_ledger.evaluate, tested in tests/test_process_milestones_1628.py).

Every emission carries its window, its n, and an explicit uncertainty facet
(ADR-105 rule 1): sd/sem where a mean is claimed, exact-count resolution where
the evidence is a set of dates. Where a sum can only be UNDER-counted by
missing data (zone2), the measurement says so instead of pretending precision.

This module does no I/O and never touches DynamoDB: milestone_ledger.py is the
ONE writer of the MILESTONE# partition and calls `candidates()` from inside its
sweep, which also subjects every emission here to the global cooldown and the
spiral circuit breaker (#1627).

v1.0.0 — 2026-07-26 (#1628)
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import NamedTuple

# ── Categories (the ledger's companion rule keys off these) ──────────────────
CATEGORY_PROCESS = "process"
CATEGORY_COMPOSITION = "composition"

# ── return_after_gap ──────────────────────────────────────────────────────────
RETURN_MISSED_WEEK_DAYS = 7  # a "missed week" = this many consecutive days with no training
RETURN_WITHIN_DAYS = 7  # the return must land within this many days AFTER the missed week completes
RETURN_LOOKBACK_DAYS = 60  # the window the gap/return pattern is evaluated over
RETURN_EMIT_WINDOW_DAYS = 14  # only emit while the return is recent enough to be news, not archaeology

# ── sustained_sessions ────────────────────────────────────────────────────────
SUSTAIN_RUNG_WEEKS = (8, 12, 26)  # ladder rungs, in weeks of sustained non-decline
SUSTAIN_MIN_SESSIONS_PER_WEEK = 2  # every week must clear this floor — "still training every week"

# ── strength_in_deficit ───────────────────────────────────────────────────────
STRENGTH_WINDOW_DAYS = 28
STRENGTH_MIN_SESSION_DAYS = 8  # strength session-days required in the window
STRENGTH_MIN_SESSION_DAYS_PER_HALF = 3  # …and in EACH half, so "maintained" compares real halves
STRENGTH_MAINTAIN_RATIO = 0.90  # second-half volume >= 90% of first-half volume = maintained
DEFICIT_MIN_DAYS = 14  # days with BOTH intake and expenditure logged
DEFICIT_MIN_KCAL = 200.0  # mean daily (expenditure - intake) must be at least this

# ── zone2_accumulation ────────────────────────────────────────────────────────
ZONE2_WINDOW_DAYS = 28
ZONE2_RUNG_MINUTES = (300, 600, 1000)  # ladder rungs: total Zone 2 minutes in the window

# ── rhr_hrv_trend ─────────────────────────────────────────────────────────────
TREND_WINDOW_DAYS = 30  # recent block; the baseline is the 30 days before it
TREND_MIN_N = 20  # minimum readings per block, per metric

# ── waist_change ──────────────────────────────────────────────────────────────
WAIST_WINDOW_DAYS = 14
WAIST_MIN_MEASUREMENTS = 3  # a single tape measurement can never fire a rung
WAIST_RUNGS_IN = tuple(range(48, 30, -2))  # absolute rungs: 48, 46, …, 32 inches (navel)


class WindowMilestone(NamedTuple):
    """One emission candidate: identity + ladder position. Duck-type compatible
    with milestone_ledger.MilestoneRule where evaluate/_entry consume it."""

    id: str
    label: str
    category: str
    ladder: str
    description: str
    depth: int


# The introspection registry the ACs pin: every definition's window length,
# threshold and minimum n are explicit DATA, not implications buried in code.
DEFINITIONS = {
    "return_after_gap": {
        "category": CATEGORY_PROCESS,
        "window_days": RETURN_LOOKBACK_DAYS,
        "threshold": {"missed_week_days": RETURN_MISSED_WEEK_DAYS, "return_within_days": RETURN_WITHIN_DAYS},
        "min_n": 2,  # at least the pre-gap training day and the return day
    },
    "sustained_sessions": {
        "category": CATEGORY_PROCESS,
        "window_days": tuple(w * 7 for w in SUSTAIN_RUNG_WEEKS),
        "threshold": {"min_sessions_per_week": SUSTAIN_MIN_SESSIONS_PER_WEEK, "non_decline": "second_half_mean >= first_half_mean"},
        "min_n": SUSTAIN_MIN_SESSIONS_PER_WEEK * min(SUSTAIN_RUNG_WEEKS),
    },
    "strength_in_deficit": {
        "category": CATEGORY_COMPOSITION,
        "window_days": STRENGTH_WINDOW_DAYS,
        "threshold": {"maintain_ratio": STRENGTH_MAINTAIN_RATIO, "deficit_min_kcal": DEFICIT_MIN_KCAL},
        "min_n": {"session_days": STRENGTH_MIN_SESSION_DAYS, "deficit_days": DEFICIT_MIN_DAYS},
    },
    "zone2": {
        "category": CATEGORY_PROCESS,
        "window_days": ZONE2_WINDOW_DAYS,
        "threshold": {"rung_minutes": ZONE2_RUNG_MINUTES},
        "min_n": 1,  # a sum only under-counts on missing days — thin data is conservative, not dishonest
    },
    "rhr_hrv_trend": {
        "category": CATEGORY_PROCESS,
        "window_days": TREND_WINDOW_DAYS,
        "threshold": {"improvement": "beyond the SE of the difference, both metrics (personal variance, ADR-105 r4)"},
        "min_n": TREND_MIN_N,
    },
    "waist": {
        "category": CATEGORY_COMPOSITION,
        "window_days": WAIST_WINDOW_DAYS,
        "threshold": {"rungs_in": WAIST_RUNGS_IN},
        "min_n": WAIST_MIN_MEASUREMENTS,
    },
}


# ── Small pure helpers ────────────────────────────────────────────────────────


def _parse_day(value):
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _coerce_today(today) -> date:
    if isinstance(today, datetime):
        return today.date()
    if isinstance(today, date):
        return today
    parsed = _parse_day(today)
    if parsed is None:
        raise ValueError(f"unparseable evaluation date: {today!r}")
    return parsed


def _to_float(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _series_in_window(by_day, start: date, end: date) -> list[tuple[date, float]]:
    """{date_str: value} -> sorted [(date, float)] within [start, end]; Nones dropped."""
    out = []
    for k, v in (by_day or {}).items():
        d = _parse_day(k)
        f = _to_float(v)
        if d is not None and f is not None and start <= d <= end:
            out.append((d, f))
    return sorted(out)


def _mean(values):
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _sd(values):
    """Sample standard deviation; None below n=2."""
    vals = [v for v in values if v is not None]
    n = len(vals)
    if n < 2:
        return None
    m = sum(vals) / n
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (n - 1))


def _training_days(training_dates, today: date) -> list[date]:
    return sorted({d for d in (_parse_day(x) for x in (training_dates or ())) if d is not None and d <= today})


# ── The window functions (all pure) ───────────────────────────────────────────


def return_after_gap(training_dates, today):
    """Trained again within RETURN_WITHIN_DAYS of a missed week.

    A missed week = RETURN_MISSED_WEEK_DAYS consecutive days with no training
    day. The milestone fires iff the next training day lands on day 1..RETURN_WITHIN_DAYS
    after that missed week completes — a later return does NOT fire (the window
    is the definition, not a grace note). Pure function of (series, today):
    identity anchors to the return date, so each distinct restart is a distinct
    write-once fact. Returns (WindowMilestone, measurement) or None.
    """
    today = _coerce_today(today)
    days = _training_days(training_dates, today)
    window_start = today - timedelta(days=RETURN_LOOKBACK_DAYS - 1)
    n_in_window = sum(1 for d in days if d >= window_start)

    best = None
    for prev, ret in zip(days, days[1:]):
        missed = (ret - prev).days - 1  # full days with no training between the two sessions
        if missed < RETURN_MISSED_WEEK_DAYS:
            continue  # not a missed week
        returned_on_day = missed - RETURN_MISSED_WEEK_DAYS + 1  # 1-based day after the missed week completed
        if returned_on_day > RETURN_WITHIN_DAYS:
            continue  # returned, but not within the window — does not fire, ever
        if (today - ret).days > RETURN_EMIT_WINDOW_DAYS:
            continue  # old news — the sweep saw (or consumed) it when it was fresh
        best = (prev, ret, missed, returned_on_day)
    if best is None:
        return None

    prev, ret, missed, returned_on_day = best
    milestone = WindowMilestone(
        id=f"return_after_gap_{ret.isoformat()}",
        label="Returned after a gap",
        category=CATEGORY_PROCESS,
        ladder="return_after_gap",
        description=(
            f"Trained again on day {returned_on_day} after a missed week "
            f"({missed} days without training; window {RETURN_WITHIN_DAYS} days)"
        ),
        depth=0,
    )
    measurement = {
        "window_days": RETURN_LOOKBACK_DAYS,
        "n": n_in_window,  # training days observed in the lookback window
        "last_training_before_gap": prev.isoformat(),
        "return_date": ret.isoformat(),
        "missed_days": missed,
        "missed_week_days": RETURN_MISSED_WEEK_DAYS,
        "returned_on_day": returned_on_day,
        "return_window_days": RETURN_WITHIN_DAYS,
        "uncertainty": {"type": "exact_dates", "resolution_days": 1},
    }
    return milestone, measurement


def sustained_sessions(training_dates, today):
    """Training days/week has NOT DECLINED over each rung's window.

    Computed as a non-decline, never a peak: every week must clear the
    SUSTAIN_MIN_SESSIONS_PER_WEEK floor AND the second-half weekly mean must be
    >= the first-half weekly mean. Weeks are fixed 7-day buckets counting back
    from `today` (pure function of the series and the evaluation date).
    Returns [(WindowMilestone, measurement), …] — one per satisfied rung.
    """
    today = _coerce_today(today)
    day_set = set(_training_days(training_dates, today))
    out = []
    for depth, weeks in enumerate(SUSTAIN_RUNG_WEEKS):
        counts = []
        for k in range(weeks - 1, -1, -1):  # oldest bucket first
            end = today - timedelta(days=7 * k)
            start = end - timedelta(days=6)
            counts.append(sum(1 for d in day_set if start <= d <= end))
        if min(counts) < SUSTAIN_MIN_SESSIONS_PER_WEEK:
            continue
        half = weeks // 2
        first_mean = _mean(counts[:half])
        second_mean = _mean(counts[half:])
        if second_mean < first_mean:
            continue  # declined — the honest milestone is "has not declined"
        milestone = WindowMilestone(
            id=f"sustained_sessions_{weeks}w",
            label=f"{weeks} weeks sustained",
            category=CATEGORY_PROCESS,
            ladder="sustained_sessions",
            description=(
                f"Training days/week did not decline over {weeks} weeks "
                f"(every week >= {SUSTAIN_MIN_SESSIONS_PER_WEEK} sessions; second-half mean >= first-half mean)"
            ),
            depth=depth,
        )
        measurement = {
            "window_days": weeks * 7,
            "weeks": weeks,
            "n": sum(counts),  # total training days in the window
            "weekly_counts": counts,
            "min_week": min(counts),
            "floor_sessions_per_week": SUSTAIN_MIN_SESSIONS_PER_WEEK,
            "first_half_mean": round(first_mean, 2),
            "second_half_mean": round(second_mean, 2),
            "uncertainty": {"type": "exact_count", "weekly_sd": round(_sd(counts) or 0.0, 2)},
        }
        out.append((milestone, measurement))
    return out


def strength_in_deficit(strength_volume_by_day, calories_by_day, expenditure_by_day, today):
    """Strength volume maintained while in a caloric deficit — BOTH signals or nothing.

    Strength: session-day volume over STRENGTH_WINDOW_DAYS; needs
    STRENGTH_MIN_SESSION_DAYS session-days (and >= STRENGTH_MIN_SESSION_DAYS_PER_HALF
    in each half); maintained = second-half volume >= STRENGTH_MAINTAIN_RATIO x first-half.
    Deficit: mean daily (expenditure - intake) >= DEFICIT_MIN_KCAL over >= DEFICIT_MIN_DAYS
    days where BOTH numbers were logged. If either signal is missing or thin the
    function returns None — never a partial claim (ADR-104).
    """
    today = _coerce_today(today)
    start = today - timedelta(days=STRENGTH_WINDOW_DAYS - 1)
    mid = today - timedelta(days=STRENGTH_WINDOW_DAYS // 2 - 1)  # second half starts here

    vols = [(d, v) for d, v in _series_in_window(strength_volume_by_day, start, today) if v > 0]
    if len(vols) < STRENGTH_MIN_SESSION_DAYS:
        return None
    first = [v for d, v in vols if d < mid]
    second = [v for d, v in vols if d >= mid]
    if len(first) < STRENGTH_MIN_SESSION_DAYS_PER_HALF or len(second) < STRENGTH_MIN_SESSION_DAYS_PER_HALF:
        return None
    if sum(second) < STRENGTH_MAINTAIN_RATIO * sum(first):
        return None  # strength NOT maintained

    intake = dict(_series_in_window(calories_by_day, start, today))
    expend = dict(_series_in_window(expenditure_by_day, start, today))
    balances = [expend[d] - intake[d] for d in sorted(set(intake) & set(expend)) if intake[d] > 0 and expend[d] > 0]
    if len(balances) < DEFICIT_MIN_DAYS:
        return None  # deficit signal absent or too thin — no milestone (ADR-104)
    mean_deficit = _mean(balances)
    if mean_deficit < DEFICIT_MIN_KCAL:
        return None  # not in a deficit
    sd = _sd(balances) or 0.0
    sem = sd / math.sqrt(len(balances))

    milestone = WindowMilestone(
        id=f"strength_in_deficit_{STRENGTH_WINDOW_DAYS // 7}w",
        label="Strength held in a deficit",
        category=CATEGORY_COMPOSITION,
        ladder="strength_in_deficit",
        description=(
            f"Strength volume maintained (>= {int(STRENGTH_MAINTAIN_RATIO * 100)}% half-over-half) while in a "
            f">= {int(DEFICIT_MIN_KCAL)} kcal/day mean deficit over {STRENGTH_WINDOW_DAYS} days"
        ),
        depth=0,
    )
    measurement = {
        "window_days": STRENGTH_WINDOW_DAYS,
        "n": len(vols),  # strength session-days in the window
        "n_deficit_days": len(balances),
        "first_half_volume_kg": round(sum(first), 1),
        "second_half_volume_kg": round(sum(second), 1),
        "maintain_ratio_threshold": STRENGTH_MAINTAIN_RATIO,
        "mean_deficit_kcal": round(mean_deficit, 1),
        "deficit_threshold_kcal": DEFICIT_MIN_KCAL,
        "uncertainty": {"type": "sem", "deficit_sd_kcal": round(sd, 1), "deficit_sem_kcal": round(sem, 1)},
    }
    return milestone, measurement


def zone2_accumulation(zone2_minutes_by_day, today):
    """Total Zone 2 minutes accumulated over ZONE2_WINDOW_DAYS. Rung ladder.

    A sum can only be UNDER-counted by missing days, so thin coverage is
    conservative rather than dishonest — the measurement still records how many
    days actually carried data. Returns [(WindowMilestone, measurement), …].
    """
    today = _coerce_today(today)
    start = today - timedelta(days=ZONE2_WINDOW_DAYS - 1)
    series = _series_in_window(zone2_minutes_by_day, start, today)
    total = sum(v for _, v in series)
    out = []
    for depth, rung in enumerate(ZONE2_RUNG_MINUTES):
        if total < rung:
            continue
        milestone = WindowMilestone(
            id=f"zone2_{ZONE2_WINDOW_DAYS // 7}w_{rung}",
            label=f"{rung} Zone 2 minutes in {ZONE2_WINDOW_DAYS // 7} weeks",
            category=CATEGORY_PROCESS,
            ladder="zone2",
            description=f"Accumulated >= {rung} Zone 2 minutes over a {ZONE2_WINDOW_DAYS}-day window",
            depth=depth,
        )
        measurement = {
            "window_days": ZONE2_WINDOW_DAYS,
            "n": len(series),  # days carrying Zone 2 data in the window
            "total_minutes": round(total, 1),
            "threshold_minutes": rung,
            "uncertainty": {"type": "sum_undercount_only", "coverage_days": len(series)},
        }
        out.append((milestone, measurement))
    return out


def rhr_hrv_trend(rhr_by_day, hrv_by_day, today):
    """30-day RHR down AND HRV up vs the previous 30 days, each beyond its noise.

    The improvement threshold is the standard error of the difference of the two
    block means, computed from Matthew's own readings — personal variance, not a
    hand-set constant (ADR-105 rule 4). BOTH metrics must clear it; one alone is
    not the milestone. Returns (WindowMilestone, measurement) or None.
    """
    today = _coerce_today(today)
    recent_start = today - timedelta(days=TREND_WINDOW_DAYS - 1)
    prev_start = recent_start - timedelta(days=TREND_WINDOW_DAYS)
    prev_end = recent_start - timedelta(days=1)

    def _block_stats(by_day):
        recent = [v for _, v in _series_in_window(by_day, recent_start, today)]
        prev = [v for _, v in _series_in_window(by_day, prev_start, prev_end)]
        if len(recent) < TREND_MIN_N or len(prev) < TREND_MIN_N:
            return None
        sd_r, sd_p = _sd(recent), _sd(prev)
        if sd_r is None or sd_p is None:
            return None
        se_diff = math.sqrt(sd_r**2 / len(recent) + sd_p**2 / len(prev))
        return {
            "prev_mean": round(_mean(prev), 2),
            "recent_mean": round(_mean(recent), 2),
            "delta": round(_mean(recent) - _mean(prev), 2),
            "se_diff": round(se_diff, 3),
            "n_prev": len(prev),
            "n_recent": len(recent),
        }

    rhr = _block_stats(rhr_by_day)
    hrv = _block_stats(hrv_by_day)
    if rhr is None or hrv is None:
        return None  # a block too thin to characterise makes no claim (ADR-105)
    # Strict inequality on the sign: a flat series (delta 0, se 0) is not an improvement.
    rhr_improved = rhr["delta"] < 0 and rhr["delta"] <= -rhr["se_diff"]
    hrv_improved = hrv["delta"] > 0 and hrv["delta"] >= hrv["se_diff"]
    if not (rhr_improved and hrv_improved):
        return None

    milestone = WindowMilestone(
        id=f"rhr_hrv_trend_{TREND_WINDOW_DAYS}d",
        label=f"{TREND_WINDOW_DAYS}-day RHR/HRV trend improved",
        category=CATEGORY_PROCESS,
        ladder="rhr_hrv_trend",
        description=(
            f"{TREND_WINDOW_DAYS}-day mean RHR fell and HRV rose vs the previous {TREND_WINDOW_DAYS} days, "
            "each beyond the SE of its own difference"
        ),
        depth=0,
    )
    measurement = {
        "window_days": TREND_WINDOW_DAYS,
        "n": min(rhr["n_recent"], rhr["n_prev"], hrv["n_recent"], hrv["n_prev"]),
        "rhr": rhr,
        "hrv": hrv,
        "uncertainty": {"type": "se_of_difference", "rhr_se_diff": rhr["se_diff"], "hrv_se_diff": hrv["se_diff"]},
    }
    return milestone, measurement


def waist_change(waist_by_day, today):
    """Trailing WAIST_WINDOW_DAYS-day mean navel waist under an absolute rung.

    Needs >= WAIST_MIN_MEASUREMENTS tape measurements in the window — a single
    reading can never fire a rung (the #1626 weight-rung discipline applied to
    the tape). Returns [(WindowMilestone, measurement), …].
    """
    today = _coerce_today(today)
    start = today - timedelta(days=WAIST_WINDOW_DAYS - 1)
    series = _series_in_window(waist_by_day, start, today)
    if len(series) < WAIST_MIN_MEASUREMENTS:
        return []
    values = [v for _, v in series]
    mean_in = _mean(values)
    out = []
    for depth, rung in enumerate(WAIST_RUNGS_IN):
        if mean_in >= rung:
            continue
        milestone = WindowMilestone(
            id=f"waist_sub_{rung}",
            label=f'Waist under {rung}"',
            category=CATEGORY_COMPOSITION,
            ladder="waist",
            description=f"Trailing {WAIST_WINDOW_DAYS}-day mean navel waist under {rung} inches",
            depth=depth,
        )
        measurement = {
            "window_days": WAIST_WINDOW_DAYS,
            "n": len(values),
            "mean_in": round(mean_in, 2),
            "threshold_in": rung,
            "uncertainty": {"type": "sd", "sd_in": round(_sd(values) or 0.0, 2)},
        }
        out.append((milestone, measurement))
    return out


# ── The one aggregation surface the ledger calls ─────────────────────────────


def candidates(signals, today):
    """All window milestones satisfied by `signals` on `today`, as
    [(WindowMilestone, measurement), …]. Pure; missing signal families simply
    yield no candidates from their milestones (absence of evidence emits
    nothing — ADR-104). Consumption, cooldown, the weight-companion rule and
    the spiral circuit breaker are all applied by milestone_ledger, the ONE
    writer of the MILESTONE# partition.
    """
    signals = signals or {}
    out = []

    single = return_after_gap(signals.get("training_dates"), today)
    if single:
        out.append(single)

    out.extend(sustained_sessions(signals.get("training_dates"), today))

    sid = strength_in_deficit(
        signals.get("strength_volume_by_day"),
        signals.get("calories_by_day"),
        signals.get("expenditure_by_day"),
        today,
    )
    if sid:
        out.append(sid)

    out.extend(zone2_accumulation(signals.get("zone2_minutes_by_day"), today))

    trend = rhr_hrv_trend(signals.get("rhr_by_day"), signals.get("hrv_by_day"), today)
    if trend:
        out.append(trend)

    out.extend(waist_change(signals.get("waist_by_day"), today))
    return out
