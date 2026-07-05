"""quarter_utils.py — calendar-quarter helpers for quarterly-cadence batch jobs.

#553's coach memoirs is the first consumer. Quarters are CALENDAR quarters
(Jan-Mar=Q1, Apr-Jun=Q2, Jul-Sep=Q3, Oct-Dec=Q4) rather than experiment-relative
— a retrospective on "this stretch of calendar time" reads naturally regardless
of experiment resets/genesis re-anchoring (ADR-077), and it keeps the publish
cadence predictable (four fixed dates a year) instead of drifting with the
genesis date.

Pure functions, no AWS — bundled as a plain sibling module (like er03_gate.py),
not added to the shared layer, since only the memoir batch imports it today.
"""

from datetime import date, datetime, timezone


def quarter_key(iso_date: str) -> str:
    """'2026-07-04' -> '2026-Q3'."""
    d = date.fromisoformat(iso_date)
    q = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{q}"


def previous_quarter_key(iso_date: str) -> str:
    """The calendar quarter immediately before the one `iso_date` falls in.

    This is what a batch running on the 1st of a new quarter should retrospect
    on — e.g. run on 2026-10-01, the quarter to narrate is 2026-Q3.
    """
    d = date.fromisoformat(iso_date)
    q = (d.month - 1) // 3 + 1
    year = d.year
    q -= 1
    if q == 0:
        q, year = 4, year - 1
    return f"{year}-Q{q}"


def quarter_bounds(quarter_key_str: str) -> tuple:
    """'2026-Q3' -> ('2026-07-01', '2026-10-01') — (start inclusive, end
    exclusive), both ISO date strings so callers can build SK range queries
    like `between(f"LEARNING#{start}", f"LEARNING#{end}")`."""
    year_str, q_str = quarter_key_str.split("-Q")
    year, q = int(year_str), int(q_str)
    start_month = (q - 1) * 3 + 1
    start = date(year, start_month, 1)
    if q == 4:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, start_month + 3, 1)
    return start.isoformat(), end.isoformat()


def current_quarter_key(now=None) -> str:
    now = now or datetime.now(timezone.utc)
    return quarter_key(now.date().isoformat())
