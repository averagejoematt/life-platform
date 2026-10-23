"""THE registry of dated heart-rate regime markers, and the rules every HR-derived consumer reads (#4999).

A regime marker is a dated clinical event after which heart-rate-derived numbers no longer
compare with what came before — the HR physiology itself changed that day. It is shaped like
the experiment's cycle markers (`common.constants.EXPERIMENT_START_DATE`, the SSM cycle
geneses): one ISO date and a kind, declared once, read everywhere. The specifics of an event
are owner-only and live in platform memory (the marker names the memory row), never here.

The 2026-10-10 marker is the clinical-event marker / HR regime change; the standing
constraint behind it is platform memory `MEMORY#training#2026-10-10#1c0bee61d2`.

What a marker does, for every HR-derived component (`HR_DERIVED_COMPONENTS`):

1. **Re-baselining window** — from the marker date through `marker + rebaseline_days`,
   inclusive, the component reports `REBASELINING` and contributes NO green / yellow / red
   label. A readiness composite built on any of them reports re-baselining, not a tier.
2. **Post-marker baselines** — after the window, a trailing baseline whose start would reach
   before the marker is truncated to the first day after it (`baseline_window`), and says so
   with its n. The marker day itself is a transition day and is never a baseline day.
3. **AF-day exclusion** — a day is dropped from the HRV and RHR baselines when Eight Sleep's
   `hrv_avg` exceeds `AF_HRV_SPIKE_RATIO` × its trailing `AF_HRV_TRAILING_DAYS`-day max, or a
   device returned a rhythm classification (`af_days`). The device field is owner-only
   (`privacy.field_tiers`): it is read where the row is and only ever reduced to "this date is
   excluded" — never surfaced, never counted by reason.

ADR-105 provenance of every threshold here (also stated in docs/engines/READINESS.md):

- `rebaseline_days = 14` — **owner** (brief 2026-10-18 §A1, "through roughly 2026-10-24").
- `AF_HRV_SPIKE_RATIO = 1.5` — **owner** (same brief; checked against owner history: the
  2026-10-10 Eight Sleep row read 123.7 ms against a prior 30-day range of 17.7–67.5 ms).
- `AF_HRV_TRAILING_DAYS = 30` — **owner** (same brief).
- "any non-negative rhythm classification excludes the day" — **population** convention made
  conservative: a device's inconclusive result is treated like a positive one for baseline
  purposes, because excluding a normal day costs one sample and including an irregular-rhythm
  day corrupts the baseline.

Pure module: no I/O, no clock. Every function takes the date it reasons about.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from typing import Any

from common.pacific_time import parse_day_key  # THE calendar-day parse (#3741)

REBASELINING = "re-baselining"

# The one registry. Append-only, oldest first; each entry is a dated marker like a cycle genesis.
HR_REGIME_MARKERS: tuple[dict[str, Any], ...] = (
    {
        "date": "2026-10-10",
        "kind": "hr_regime_change",
        "rebaseline_days": 14,  # owner (brief 2026-10-18 §A1)
        "memory_ref": "MEMORY#training#2026-10-10#1c0bee61d2",
    },
)

# Every component whose value is computed from heart rate. Keys are the platform's names for
# them across surfaces (readiness models, plan engine, training recommendation).
HR_DERIVED_COMPONENTS: tuple[str, ...] = (
    "whoop_recovery",
    "rhr",
    "hrv",
    "strain",
    "eightsleep_hr_avg",
    "eightsleep_hrv_avg",
    "hrv_trend",
    "zone2_pct",
    "acwr_hr",
)

AF_HRV_SPIKE_RATIO = 1.5  # owner (brief 2026-10-18 §A1)
AF_HRV_TRAILING_DAYS = 30  # owner (brief 2026-10-18 §A1)
# The device rhythm-classification field (Withings ECG). Owner-only; see the module docstring.
DEVICE_RHYTHM_FIELD = "afib_result"
_RHYTHM_NOT_DETECTED = 0


def _d(s: str) -> date:
    d = parse_day_key(str(s)[:10])
    if d is None:
        raise ValueError(f"not a YYYY-MM-DD day key: {s!r}")
    return d


def window_end(marker: Mapping[str, Any]) -> str:
    """The last day (inclusive) of a marker's re-baselining window."""
    return (_d(marker["date"]) + timedelta(days=int(marker["rebaseline_days"]))).isoformat()


def latest_marker(as_of: str, markers: Iterable[Mapping[str, Any]] = HR_REGIME_MARKERS) -> Mapping[str, Any] | None:
    """The newest marker dated on or before `as_of`, else None."""
    on_or_before = [m for m in markers if str(m["date"]) <= str(as_of)[:10]]
    return max(on_or_before, key=lambda m: m["date"]) if on_or_before else None


def active_marker(as_of: str, markers: Iterable[Mapping[str, Any]] = HR_REGIME_MARKERS) -> Mapping[str, Any] | None:
    """The marker whose re-baselining window contains `as_of` (inclusive both ends), else None."""
    m = latest_marker(as_of, markers)
    if m is None:
        return None
    return m if str(as_of)[:10] <= window_end(m) else None


def is_rebaselining(as_of: str | None, markers: Iterable[Mapping[str, Any]] = HR_REGIME_MARKERS) -> bool:
    if not as_of:
        return False
    try:
        return active_marker(as_of, markers) is not None
    except ValueError:
        return False


def regime_status(as_of: str, markers: Iterable[Mapping[str, Any]] = HR_REGIME_MARKERS) -> dict[str, Any] | None:
    """The block a surface attaches during a re-baselining window, else None (no window active).

    Names the marker by date and kind only — the event's specifics are owner-only memory.
    """
    m = active_marker(as_of, markers)
    if m is None:
        return None
    return {
        "state": REBASELINING,
        "marker_date": m["date"],
        "marker_kind": m["kind"],
        "window_end": window_end(m),
        "rebaseline_days": int(m["rebaseline_days"]),
        "rebaseline_days_basis": "owner",
        "components": {k: REBASELINING for k in HR_DERIVED_COMPONENTS},
        "note": (
            f"Heart-rate-derived components are re-baselining after the {m['date']} HR regime marker "
            f"(through {window_end(m)}): no green/yellow/red label is drawn from them. Gate the session on the "
            f"standing constraint in platform memory ({m.get('memory_ref')}), not on these numbers."
        ),
    }


def baseline_window(start: str, end: str, markers: Iterable[Mapping[str, Any]] = HR_REGIME_MARKERS) -> tuple[str, dict[str, Any] | None]:
    """(effective_start, truncation) for a trailing baseline [start, end].

    When a marker sits inside (start, end], the window is cut to the day after the marker — the
    baseline must not average two HR regimes. `truncation` is None when nothing was cut, else
    `{"truncated_at_marker": <marker date>, "requested_start": start, "since": <new start>}`.
    """
    m = latest_marker(end, markers)
    if m is None:
        return start, None
    floor = (_d(m["date"]) + timedelta(days=1)).isoformat()
    if str(start)[:10] >= floor:
        return start, None
    return floor, {"truncated_at_marker": m["date"], "requested_start": str(start)[:10], "since": floor}


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _row_date(r: Mapping[str, Any]) -> str | None:
    d = r.get("date") or str(r.get("sk", "")).replace("DATE#", "")[:10]
    return str(d)[:10] if d else None


def af_days(
    eightsleep_rows: Iterable[Mapping[str, Any]] = (),
    rhythm_rows: Iterable[Mapping[str, Any]] = (),
    *,
    ratio: float = AF_HRV_SPIKE_RATIO,
    trailing_days: int = AF_HRV_TRAILING_DAYS,
) -> set[str]:
    """The dates excluded from the HRV and RHR baselines.

    A date is excluded when (a) its Eight Sleep `hrv_avg` exceeds `ratio` × the max `hrv_avg`
    over the `trailing_days` days BEFORE it (a day already excluded never raises that max), or
    (b) any row of that date carries a device rhythm classification other than "not detected".
    A date with fewer than 7 trailing readings is never flagged by (a) — no max to compare with.
    """
    out: set[str] = set()
    for r in rhythm_rows or ():
        v = _num(r.get(DEVICE_RHYTHM_FIELD))
        d = _row_date(r)
        if d and v is not None and v != _RHYTHM_NOT_DETECTED:
            out.add(d)
    series = sorted(((d, _num(r.get("hrv_avg"))) for r in (eightsleep_rows or ()) if (d := _row_date(r))), key=lambda x: x[0])
    kept: list[tuple[str, float]] = []
    for d, v in series:
        if v is None:
            continue
        lo = (_d(d) - timedelta(days=trailing_days)).isoformat()
        prior = [pv for pd, pv in kept if lo <= pd < d]
        if len(prior) >= 7 and v > ratio * max(prior):
            out.add(d)
            continue
        if d not in out:
            kept.append((d, v))
    return out


def baseline_values(
    rows: Iterable[Mapping[str, Any]],
    field: str,
    start: str,
    end: str,
    excluded: Iterable[str] = (),
    markers: Iterable[Mapping[str, Any]] = HR_REGIME_MARKERS,
) -> tuple[list[float], dict[str, Any]]:
    """The values of `field` over [start, end] a baseline may average, and the basis that says why.

    Applies the marker truncation and drops excluded (AF) days. The basis carries the n, the
    effective start, the truncation (if any) and how many readings were excluded — a count only.
    """
    eff_start, trunc = baseline_window(start, end, markers)
    skip = set(excluded or ())
    vals: list[float] = []
    n_excluded = 0
    for r in rows or ():
        d = _row_date(r)
        v = _num(r.get(field))
        if not d or v is None or not (eff_start <= d <= str(end)[:10]):
            continue
        if d in skip:
            n_excluded += 1
            continue
        vals.append(v)
    basis: dict[str, Any] = {"since": eff_start, "through": str(end)[:10], "n": len(vals), "excluded_days_n": n_excluded}
    if trunc:
        basis.update(trunc)
    return vals, basis


def trailing_baselines(
    rows: Iterable[Mapping[str, Any]],
    fields: Iterable[str],
    anchor: date,
    end: str,
    excluded: Iterable[str] = (),
    windows: Iterable[int] = (7, 30),
    *,
    fetch_range: Any = None,
) -> dict[tuple[str, int], tuple[list[float], dict[str, Any]]]:
    """`{(field, days): (values, basis)}` — each trailing window `[anchor - days, end]` through
    `baseline_values` (marker cut + excluded days). One read of `rows` serves every window. Given
    the caller's `fetch_range`, the AF days are read through it (`af_days_from`) and excluded too."""
    rows = list(rows or ())
    ex = set(excluded or ()) | (af_days_from(fetch_range, anchor, end) if fetch_range else set())
    return {(f, n): baseline_values(rows, f, (anchor - timedelta(days=n)).isoformat(), end, ex) for f in fields for n in windows}


def af_days_from(fetch_range: Any, anchor: date, end: str) -> set[str]:
    """`af_days` over the reads it needs, through the caller's own `fetch_range(source, start, end)`:
    60 days of Eight Sleep (30 baseline days x a 30-day trailing max) and 30 days of device rhythm."""
    es = fetch_range("eightsleep", (anchor - timedelta(days=2 * AF_HRV_TRAILING_DAYS)).isoformat(), end)
    return af_days(es, fetch_range("withings", (anchor - timedelta(days=AF_HRV_TRAILING_DAYS)).isoformat(), end))


def computed_row_fields(as_of: str, hrv_basis: Mapping[str, Any] | None) -> dict[str, Any]:
    """The computed_metrics fields this module owns (#4999): `readiness_state` inside a marker's
    window, and `hrv_{7d,30d}_n` / `hrv_{7d,30d}_basis` — the n and window behind each HRV
    average, so a reader sees a baseline cut at a marker instead of a bare mean."""
    out: dict[str, Any] = {"readiness_state": REBASELINING} if is_rebaselining(as_of) else {}
    for key in ("7d", "30d"):
        basis = (hrv_basis or {}).get(f"hrv_{key}_basis")
        if basis:
            out[f"hrv_{key}_n"], out[f"hrv_{key}_basis"] = int(basis.get("n") or 0), dict(basis)
    return out
