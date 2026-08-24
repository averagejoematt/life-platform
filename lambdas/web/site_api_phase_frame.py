"""lambdas/web/site_api_phase_frame.py — cycle-honest framing for cross-phase text (#2957).

ADR-104 and the phase rubric (``docs/PHASE_TAXONOMY.md``) draw one line: a counter or
a dated artefact that reaches back past the live cycle's genesis is the platform's
**lifetime** memory, not this cycle's record, and the surface that renders it has to
say so. Reader-truth run ``32545820852`` and the four sweeps after it flagged exactly
that gap — 'No training logged — 57 days' on Day 5 of a 5-day cycle, a 2026-07-26
diary reaction served as current coaching on Day 7 — as temporal contradictions. The
judge was right: the numbers were true, the frame was missing.

The cure is one shared vocabulary applied at the **producer**, so the reader and the
reader-truth judge read the same frame off the same bytes:

* :func:`spans_cycle` — does an N-day counter reach back past Day 1?
* :func:`cross_cycle_suffix` — the parenthetical a lifetime counter wears.
* :func:`archival_frame` — the ``{pre_cycle, days_before, label}`` block a dated
  artefact carries onto the wire so the front-end never has to re-derive it.

Pure functions: no AWS, no clock reads except the caller's own, no I/O. Imported by
``site_api_pulse`` (the cockpit/vitals glyph labels) and ``site_api_thirdwall`` (the
lab-notes diary reactions), and unit-tested directly in
``tests/test_phase_frame_2957.py``.
"""

from datetime import date, datetime
from typing import Optional, Union

DateLike = Union[str, date, datetime, None]


def _as_date(value: DateLike) -> Optional[date]:
    """``YYYY-MM-DD`` (or a date/datetime) → ``date``; ``None`` when unparseable.

    Fail-soft by construction: every caller below is a public read path, and a
    malformed stored date must degrade to "no frame", never to a 500.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def spans_cycle(days: Optional[int], day_n: Optional[int]) -> bool:
    """True when a ``days``-long backward counter reaches past the live cycle's Day 1.

    On Day ``day_n`` a gap of ``days`` points at day ``day_n - days``; anything at or
    below day 0 predates the genesis. So ``days >= day_n`` is the whole test — a
    7-day gap on Day 7 lands exactly on the day BEFORE Day 1 and is cross-cycle.
    """
    if days is None or day_n is None:
        return False
    try:
        return int(days) >= int(day_n)
    except (TypeError, ValueError):
        return False


def cross_cycle_suffix(genesis: DateLike, cycle: Optional[int] = None) -> str:
    """The parenthetical a cross-cycle counter wears, e.g.::

        ' (lifetime — predates the 2026-08-17 restart)'

    Empty string when the genesis is unknown: a frame we cannot substantiate is worse
    than no frame. ``cycle`` is folded in when the SSM cycle number is readable.
    """
    g = _as_date(genesis)
    if g is None:
        return " (lifetime — spans cycles)"
    if cycle:
        return f" (lifetime — predates the {g.isoformat()} restart that began cycle {cycle})"
    return f" (lifetime — predates the {g.isoformat()} restart)"


def label_with_span(base: str, days: Optional[int], day_n: Optional[int], genesis: DateLike, cycle: Optional[int] = None) -> str:
    """``base`` verbatim when the counter is in-cycle, ``base`` + the lifetime
    parenthetical when it reaches back past the genesis."""
    if not spans_cycle(days, day_n):
        return base
    return base + cross_cycle_suffix(genesis, cycle)


def archival_frame(when: DateLike, genesis: DateLike, cycle: Optional[int] = None) -> Optional[dict]:
    """The framing block a dated artefact carries when it predates the live genesis.

    ``None`` for in-cycle content — there is nothing to disclaim, and an always-on
    badge would train the reader to ignore it. For anything older::

        {"pre_cycle": True, "days_before": 28, "cycle": 14, "genesis": "2026-08-17",
         "label": "from a previous cycle — 28 days before cycle 14 began 2026-08-17"}

    The ``label`` is the reader-facing sentence; the structured fields let a caller
    render it differently without re-parsing prose.
    """
    d = _as_date(when)
    g = _as_date(genesis)
    if d is None or g is None or d >= g:
        return None
    days_before = (g - d).days
    cycle_phrase = f"cycle {cycle} began" if cycle else "this cycle began"
    return {
        "pre_cycle": True,
        "days_before": days_before,
        "cycle": cycle,
        "genesis": g.isoformat(),
        "label": (f"from a previous cycle — {days_before} day{'s' if days_before != 1 else ''} before {cycle_phrase} {g.isoformat()}"),
    }


def lifetime_scope() -> str:
    """The scope word a CROSS_PHASE accumulator's own count wears.

    Some counters (voice-fidelity's judgment tally, calibration's career ledger)
    have no window at all — per ``docs/PHASE_TAXONOMY.md``'s ``cross_phase`` class
    they are never tagged and never wiped at a restart, so unlike a ``spans_cycle``
    gap (which only *sometimes* reaches back past a genesis) they are
    unconditionally the platform's whole history, never "this cycle's" number.
    One shared word so a future page can't drift to "every cycle" or "career" for
    the same fact — reuse this rather than writing the string again.
    """
    return "all cycles"
