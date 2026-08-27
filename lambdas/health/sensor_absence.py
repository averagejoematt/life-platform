"""sensor_absence.py — the ONE ADR-104 absence verdict for a sub-datatype that a
reader surface publishes as current-looking statistics (#3204).

Why this module exists
----------------------
On 2026-08-24 the Dexcom Stelo sensor session ended. The `apple_health` DynamoDB
partition stayed fresh every day afterwards — steps, water and the rest kept
landing — the CGM sub-datatype's behavioural `stale_days: 3` bar had not yet
tripped, and `/api/glucose` went on serving 08-24's `avg_mg_dl = 104.3`,
`time_in_range_pct = 100`, `tir_status = "excellent"` and `as_of_date = 2026-08-24`
for days afterwards. Nothing in the platform said the sensor had stopped. The
nightly reader-truth oracle was the only thing that noticed, and it noticed as a
temporal contradiction rather than as an absence.

A sensor session ending is routine and legitimate — sensors end and restart every
couple of weeks. Serving the last good day's numbers unqualified is not: that is
exactly the ADR-104 defect, behavioural absence rendered as a current reading.

The shape of the fix
--------------------
Two different questions were being answered by ONE threshold:

  * "has the capture habit lapsed?" — behavioural, deliberately lenient, the
    `stale_days` facet (CGM: 3 days). It nudges; it must never page.
  * "is the number this endpoint prints actually today's?" — a reader-truth
    question, and its bar is the reader-truth oracle's own: no more than
    `max_days_behind` days behind today for a near-real-time source (CGM: 1).

The second lives in `source_registry`'s `reader_surface` facet (#2003: read the
registry, never hand-state a cadence). This module is the ONE place that turns it
into a verdict and `absence_note()` is the ONE place that phrases it, so a JSON
payload, a stored artifact and a prompt cannot describe the same silence three
different ways.

Vocabulary reused deliberately, not invented:

  * `status` in {"fresh", "stale"} — `/api/source_freshness`'s own word.
  * `days_behind` — days behind TODAY (not behind the partition, which stayed
    fresh throughout; that is the whole point of the bug).
  * "…last-known value, NOT current" — the phrasing shape `site_api_ai_context`'s
    age annotation already uses for weight and vitals, so the honest sentence a
    reader meets on the glucose door is the one they already meet elsewhere.

Absence is STATED, never fabricated: a window with no reading at all returns
`as_of_date: None` and says so, rather than reaching further back for a number to
print.

Pure except for the registry read, and the registry map is injectable
(`surfaces=`) so tests drive the verdict without importing the ingestion package.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

FRESH = "fresh"
STALE = "stale"


def _reader_surfaces() -> dict:
    """The registry's reader-published HAE sub-datatypes.

    Deliberately NOT fail-soft. An empty map means "nothing is reader-published",
    which this module reports as fresh — so swallowing an import fault here would
    silently turn every labelled surface back into an unlabelled one and would look
    exactly like a working absence path (#3200's lesson: a broken fail-closed path
    is indistinguishable from a working one). The registry is a bundled shared
    module (#781); if it cannot be imported the handler is already broken and
    should say so."""
    from ingestion.source_registry import hae_reader_surfaces

    return hae_reader_surfaces()


def _days_between(later: str, earlier: str) -> int | None:
    """Whole calendar days from `earlier` to `later`, or None if either is unparseable.

    Dates only, never clocks: both sides are bare ISO `YYYY-MM-DD` day keys, and a
    same-day gap of any clock size is never this module's concern — only a day that
    has rolled over with no fresher reading behind it.
    """
    try:
        return (datetime.strptime(later[:10], "%Y-%m-%d") - datetime.strptime(earlier[:10], "%Y-%m-%d")).days
    except (ValueError, TypeError):
        return None


def absence_note(label: str, as_of_date: str | None, days_behind: int | None) -> str:
    """The ONE sentence every surface uses for a quiet reader-published sensor.

    - no reading at all -> "No CGM (glucose) reading in this window."
    - a dated last read -> "No CGM (glucose) reading since 2026-08-24 — 3 days
      dark. The values shown are that day's last-known readings, NOT current."
    """
    if not as_of_date:
        return f"No {label} reading in this window."
    if not days_behind or days_behind < 1:
        return f"No {label} reading since {as_of_date}."
    day_word = "day" if days_behind == 1 else "days"
    return (
        f"No {label} reading since {as_of_date} — {days_behind} {day_word} dark. "
        f"The values shown are that day's last-known readings, NOT current."
    )


def absence_verdict(datatype_key: str, as_of_date: str | None, today: str, *, surfaces: dict | None = None) -> dict:
    """ADR-104 currency verdict for one reader-published sub-datatype.

    ``as_of_date`` is the newest day that actually CARRIES the datatype (None when
    the window holds no reading at all); ``today`` is the Pacific calendar day the
    surface is being rendered for. Returns::

        {"status": "fresh"|"stale", "datatype", "label", "last_reading_date",
         "days_behind": int|None, "max_days_behind": int|None, "note": str|None}

    The date is published as ``last_reading_date``, deliberately NOT ``as_of_date``.
    ``as_of_date`` is the platform's word for "the currency stamp of the values in
    this object", and the reader-truth oracle (R8) reads it as exactly that. The
    date here means the opposite — the last day a reading EXISTED, stated precisely
    because the values are absent. Reusing the currency word for it would republish
    a stale currency stamp inside the very block that says there is none.

    ``note`` is populated ONLY when the verdict is stale — a fresh surface carries
    no absence noise, the same way an age annotation is empty on a same-day reading.

    A datatype with no `reader_surface` facet is not a reader-published stream and
    is always reported fresh with a null threshold: this module rules on published
    currency only and must never invent a bar the registry did not state.
    """
    surfaces = _reader_surfaces() if surfaces is None else surfaces
    spec = (surfaces or {}).get(datatype_key) or {}
    label = spec.get("label") or datatype_key
    max_behind = spec.get("max_days_behind")

    out: dict[str, Any] = {
        "status": FRESH,
        "datatype": datatype_key,
        "label": label,
        "last_reading_date": as_of_date,
        "days_behind": None,
        "max_days_behind": max_behind,
        "note": None,
    }
    if max_behind is None:
        return out

    if not as_of_date:
        # Nothing in the window at all. Absence STATED (ADR-104), with no number
        # invented for how long — the caller's window is the only bound we know.
        out["status"] = STALE
        out["note"] = absence_note(label, None, None)
        return out

    days_behind = _days_between(today, as_of_date)
    out["days_behind"] = days_behind
    if days_behind is None:
        # An unparseable date is not evidence of freshness. Fail toward honesty.
        out["status"] = STALE
        out["note"] = f"{label} reading date unknown — treat as not current."
        return out
    if days_behind > int(max_behind):
        out["status"] = STALE
        out["note"] = absence_note(label, as_of_date, days_behind)
    return out


def is_stale(verdict: dict) -> bool:
    """True when the verdict says the published numbers are not today's.

    A helper rather than a bare ``== STALE`` at each call site so the writers that
    must DROP a carried-forward value (site_stats_refresh, dashboard_refresh) and
    the endpoint that must LABEL one all branch on the same expression.
    """
    return bool(verdict.get("status") == STALE)


def carry_forward_ok(datatype_key: str, as_of_date: str | None, today: str, *, surfaces: dict | None = None) -> bool:
    """May a writer carry a previous day's value forward under a CURRENT-looking name?

    The stored-artifact form of the same question. `site_stats_refresh_lambda` and
    `dashboard_refresh_lambda` both persist glucose into documents that carry no
    date of their own, so a value they keep never decays and no reader can date it
    — worse than the endpoint, which at least stamps `as_of_date`. Both now ask
    here first, and both drop rather than keep when the answer is False.
    """
    return not is_stale(absence_verdict(datatype_key, as_of_date, today, surfaces=surfaces))
