"""nutrition_logging.py — THE nutrition logging record (#4185).

One derivation of "how many days are logged, what was the last one, how far behind is
the log, has it stalled" — read by `/api/nutrition_overview`
(`web.site_api_nutrition.nutrition_overview`) AND by every coach input that talks about
the food log (`coach.coach_input_facts`). Before #4185 the site computed these inline
and the daily nutrition coach was handed no logging record at all: its only notion of
"when was the last log" was its own carried threads and commitments. On 2026-09-25 that
produced "The food log went dark after September 19th … Six days without logs" while
the served record held a row for every day 09-20 → 09-25 (`days_logged 20`,
`lag_days 0`, `stalled false`) — a self-perpetuating premise with no served fact in the
prompt to contradict it.

Pure: no AWS, no clock. The caller supplies the rows (a macrofactor DATE# window) and
the Pacific "today"; the window rule is `window_start` below.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional

# The site's own window: `site_api_common._experiment_date(30)` — the INCLUSIVE start of
# a 30-day window ending today, floored at genesis (#2338 convention). `window_start`
# reproduces it for callers outside the web package; a parity test pins the two together.
WINDOW_DAYS = 30

# z for a two-sided 95% interval — the CI a cited protein figure is judged against.
_Z95 = 1.96


def _day(value: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def window_start(today: str, experiment_start: str, days: int = WINDOW_DAYS) -> str:
    """Inclusive start of the `days`-day window ending `today`, never before genesis and
    never after today (the same rule as `site_api_common._experiment_date`)."""
    t = _day(today)
    if t is None:
        return str(today)[:10]
    raw = (t - timedelta(days=max(days - 1, 0))).isoformat()
    return min(max(raw, str(experiment_start)[:10]), t.isoformat())


def row_date(item: dict) -> str:
    """The row's own day — `date` if present, else the `DATE#` sort key."""
    return str(item.get("date") or str(item.get("sk", "")).replace("DATE#", ""))[:10]


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def protein_of(item: dict) -> Optional[float]:
    """Protein grams by PRESENCE (the `site_api_nutrition._mf(i, "protein_g")` order):
    the legacy short name first, then `total_protein_g`. A logged 0 is a value."""
    for name in ("protein_g", "total_protein_g"):
        v = _num(item.get(name))
        if v is not None:
            return v
    return None


def logging_record(items: Iterable[dict], today: str, stale_hours: Optional[float] = None) -> dict:
    """The record `/api/nutrition_overview.nutrition` serves for days_logged / latest_date
    / today_pending / lag_days / stalled — computed from the window's rows.

    `days_logged` is the row count (the endpoint has always published `len(items)`);
    `latest_date` is the newest row's day; `lag_days` counts whole days from it to
    `today` (1 is the by-design end-of-day upload lag, never a gap); `stalled` grades that
    lag against the macrofactor `stale_hours` facet in `ingestion.source_registry` — the
    one place staleness thresholds live. `stale_hours` may be passed to keep this pure in
    tests; absent, it is read from the registry (fail-soft: stalled stays False).
    """
    rows = sorted((i for i in items or () if isinstance(i, dict)), key=lambda i: str(i.get("sk", "")))
    latest_date = row_date(rows[-1]) if rows else None
    lag_days: Optional[int] = None
    stalled = False
    t, last = _day(today), _day(latest_date)
    if t is not None and last is not None:
        lag_days = max(0, (t - last).days)
        if stale_hours is None:
            try:
                from ingestion.source_registry import DEFAULT_STALE_HOURS, stale_hours_overrides

                stale_hours = stale_hours_overrides().get("macrofactor") or DEFAULT_STALE_HOURS
            except Exception:  # noqa: BLE001 — a registry miss must not invent a stall
                stale_hours = None
        if stale_hours is not None:
            stalled = lag_days * 24 > float(stale_hours)
    return {
        "days_logged": len(rows),
        "latest_date": latest_date,
        "today_pending": bool(latest_date and latest_date < str(today)[:10]),
        "lag_days": lag_days,
        "stalled": stalled,
    }


def protein_series(items: Iterable[dict]) -> list:
    """`[(day, grams)]`, oldest first, for every row that carries a protein figure."""
    rows = sorted((i for i in items or () if isinstance(i, dict)), key=lambda i: str(i.get("sk", "")))
    out = []
    for r in rows:
        g = protein_of(r)
        if g is not None:
            out.append((row_date(r), g))
    return out


def mean_ci(values: list) -> Optional[dict]:
    """`{mean, n, half_width, lo, hi}` — the 95% interval of the mean (normal
    approximation, sample SD). None for an empty set; `half_width` None for n < 2 (a
    single day has no spread to derive a tolerance from — the caller must skip, never
    invent one)."""
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    n = len(vals)
    mean = sum(vals) / n
    half = None
    if n >= 2:
        sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1))
        half = _Z95 * sd / math.sqrt(n)
    return {
        "mean": round(mean, 1),
        "n": n,
        "half_width": round(half, 1) if half is not None else None,
        "lo": round(mean - half, 1) if half is not None else None,
        "hi": round(mean + half, 1) if half is not None else None,
    }


def protein_window(series: list, last_n: Optional[int] = None) -> Optional[dict]:
    """The protein mean + CI over the last `last_n` logged days (all of them when None)."""
    vals = [g for _d, g in series]
    if last_n is not None and last_n > 0:
        vals = vals[-int(last_n) :]
    return mean_ci(vals)
