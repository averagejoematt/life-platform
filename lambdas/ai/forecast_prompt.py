"""forecast_prompt.py — the coach prompt's MODEL EXPECTATIONS lines (#541, #4672).

Split out of `ai_calls.py`, which sits at its module-size ceiling (#1665).
"""

from __future__ import annotations

from decimal import Decimal


def forecast_prompt_lines(forecasts) -> list[str]:
    """One prompt line per forecast in a `SOURCE#forecast` summary row (#541, #4672).

    The line carries the day the forecast is FOR (`target_date`) beside its frame. Without
    it a coach handed "recovery_pct tomorrow: the model expects 52.9%" on 2026-09-11 wrote
    "52.9% tomorrow (2026-09-10)", inventing a date, and the #4618 grader then read that
    call as a statement about a day already past. A forecast missing any of its three
    numbers is left out, as before.
    """
    out: list[str] = []
    for f in forecasts or []:
        nums = [f.get(k) for k in ("point", "lo", "hi")]
        if not all(isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) for v in nums):
            continue
        p, lo, hi = (float(v) for v in nums)
        day = f.get("target_date")
        when = f" ({day})" if isinstance(day, str) and day else ""
        out.append(
            f"  - {f.get('metric', '?')} {f.get('frame', '')}{when}: the model expects {p:g}{f.get('unit', '')} (80% interval {lo:g}-{hi:g})"
        )
    return out
