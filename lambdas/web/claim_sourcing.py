"""claim_sourcing.py — a coach's words that rest on a sensor with no reading that day are not quoted (#4673).

Why this module exists
----------------------
#4217 stopped a coach whose instrument is DARK from writing anything new, and hid its
claim on an OPEN docket item. It left every DATED record alone ("history stays"), and a
dated record is exactly where the defect lived: the glucose/nutrition bet opened
2026-09-23 settled on 2026-09-30, and from then on `/api/coach_docket.resolved[]`,
`/api/calls` (`bet-20260930-994b3d89f6`) and the v8 coach and call pages printed Amara
Patel's side verbatim — "Evening carb reduction is likely coming based on CGM data…" —
while `/api/coach/glucose_coach` said, correctly, "no sensor since 2026-08-27". The coach
argued from readings that did not exist on the day it argued.

The rule
--------
A served text is NOT QUOTED when both hold:

  1. it CITES an instrument — one of that instrument's phrases below appears in it
     (`CITES`; the phrase, not the speaker, decides, so a nutrition-coach sentence "based
     on CGM data" is held too); and
  2. the text is dated INSIDE one of that instrument's GAP INTERVALS — strictly after the
     gap's `start` (the last reading before it) and strictly before its `end` (the first
     reading after it; null while the gap is still open). On that day the instrument had
     nothing behind it. A text dated on a reading day, outside every gap, or with no date
     at all, is quoted — this module never guesses.

The gaps are the INTERVAL FORM `gap_instruments()` builds, and it is the only form any
route hands this module (#4702):
  * the OPEN gap is `health.instrument_presence.absent_coaches` — the ONE derivation
    `/api/source_freshness` serves — from the instrument's `last_seen`, end null;
  * the CLOSED gaps are `health.instrument_presence.gap_history`, derived from the stored
    DATE# rows. Before #4702 the hold read only the first, so a text written during a gap
    was quoted again the day the sensor reported (its `last_seen` moved past the text).
    A closed gap holds a text exactly as an open one does, whether the sensor is dark now
    or not.

The words are never edited. A held text is removed from the payload and an `unsourced`
note takes its place, with the engine's reason, the instrument, the gap and one sentence a
page prints beside the speaker's name (naming the gap's start and, once it closed, its
end). Removing (rather than annotating in place) is what guards every renderer at once: a
page that has never heard of `unsourced` simply has nothing to quote.

Every phrase table entry is keyed by the instrument as `coach_instruments()` names it
(`source`, `datatype`); `tests/test_claim_sourcing_4673.py` fails if a registry instrument
has no entry, so a new sensor cannot join the roster with nothing to recognise it by.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from common.pacific_time import day_in_words

#: (source, datatype) → (the noun a reader is told, the phrases that cite it). A phrase is
#: a regex matched case-insensitively on word boundaries. Phrases name the INSTRUMENT or
#: its data ("CGM", "glucose readings"), never the domain ("glucose", "carbs"): a coach
#: may speak about blood sugar without a sensor; it may not speak FROM one.
CITES: dict[tuple[str, str | None], tuple[str, tuple[str, ...]]] = {
    ("apple_health", "cgm"): (
        "glucose sensor",
        (
            r"cgms?",
            r"continuous glucose",
            r"glucose (?:sensor|monitor\w*|trace\w*|waveform\w*|data|readings?|curves?|stream)",
            r"libre",
            r"dexcom",
            r"stelo",
        ),
    ),
    ("whoop", None): ("Whoop strap", (r"whoop", r"wrist strap", r"strap data")),
    ("macrofactor", None): ("MacroFactor food log", (r"macrofactor", r"food log(?:ging)?", r"meal log(?:ging)?", r"logged meals")),
    ("hevy", None): ("Hevy lifting log", (r"hevy", r"lifting log", r"workout log")),
    ("labs", None): ("blood-lab panel", (r"lab panel", r"blood panel", r"bloodwork", r"blood work", r"lab results?")),
}

_COMPILED = {key: re.compile(r"\b(?:" + "|".join(phrases) + r")\b", re.IGNORECASE) for key, (_noun, phrases) in CITES.items()}
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _day(value: Any) -> str | None:
    text = str(value or "")[:10]
    return text if _DAY_RE.match(text) else None


def claim_day(row: Mapping[str, Any] | None) -> str | None:
    """The day a PREDICTION# row's `claim_natural` was SAID, or None when the row does not say.

    `created_date` when the row carries one. A dispute-docket row (`source ==
    "dispute_docket"`, `coach.dispute_docket._write_docket_prediction`) carries none — its
    words are the docket claim, said on the docket's `opened_date`, which the writer stamps
    as the trailing `YYYY-MM-DD` of `prediction_id` (`docket-<ref>-<opened_date>`; the same
    suffix `/api/calls` matches a docket row by). Read, never guessed: any other shape is
    None, and an undated text is quoted (#4701)."""
    if not isinstance(row, Mapping):
        return None
    day = _day(row.get("created_date"))
    if day:
        return day
    pid = str(row.get("prediction_id") or "")
    if row.get("source") == "dispute_docket" and pid.startswith("docket-"):
        return _day(pid[-10:])
    return None


def gap_instruments(absent: Mapping[str, Mapping[str, Any]] | None, history: Iterable[Mapping[str, Any]] | None = None) -> list[dict]:
    """The INTERVAL FORM every route hands `unsourced` (#4702): one row per instrument that
    has any gap, {source, datatype, label, gaps: [{start, end, reason}]}.

    `history` is `health.instrument_presence.gap_history(...)` — the CLOSED gaps; `absent`
    is an `absent_coaches()` map — each dark instrument contributes its OPEN gap
    {start: last_seen, end: None}. An instrument with no gap at all is left out, so an
    empty list means nothing can be held."""
    rows: dict[tuple[str, str | None], dict] = {}

    def _row(source: Any, datatype: Any, label: Any) -> dict | None:
        key = (str(source or ""), datatype or None)
        if not key[0]:
            return None
        if key not in rows:
            rows[key] = {"source": key[0], "datatype": key[1], "label": label, "gaps": []}
        return rows[key]

    for inst in history or []:
        if not isinstance(inst, Mapping):
            continue
        row = _row(inst.get("source"), inst.get("datatype"), inst.get("label"))
        if row is None:
            continue
        for gap in inst.get("gaps") or []:
            start, end = _day(gap.get("start")), _day(gap.get("end"))
            if start and end and start < end:  # a closed gap is bounded on both sides, or it is not one
                row["gaps"].append({"start": start, "end": end, "reason": gap.get("reason")})
    seen_open: set[tuple[str, str | None]] = set()
    for state in (absent or {}).values():
        row = _row(state.get("source"), state.get("datatype"), state.get("label"))
        if row is None or (row["source"], row["datatype"]) in seen_open:
            continue
        seen_open.add((row["source"], row["datatype"]))
        row["gaps"].append({"start": _day(state.get("last_seen")), "end": None, "reason": state.get("reason")})
    return [row for row in rows.values() if row["gaps"]]


def in_gap(day: str, gap: Mapping[str, Any]) -> bool:
    """True when `day` falls strictly inside the gap: after its last reading (`start`; a
    null start is an instrument with no reading on record) and before the reading that
    closed it (`end`; null while open). A reading day itself is never inside."""
    start, end = gap.get("start"), gap.get("end")
    return (not start or start < day) and (not end or day < end)


def cites(text: Any, source: str, datatype: str | None = None) -> bool:
    """True when `text` names the instrument (or its data) by one of its phrases."""
    pattern = _COMPILED.get((source, datatype or None))
    return bool(pattern and isinstance(text, str) and pattern.search(text))


def sentence(day: str, instrument: Mapping[str, Any], gap: Mapping[str, Any]) -> str:
    """The one sentence a page prints in place of the held words (dates in words, #4182).
    It names the gap's start and, once the gap has closed, its end (#4702)."""
    noun = CITES.get(
        (str(instrument.get("source") or ""), instrument.get("datatype") or None), (str(instrument.get("label") or "sensor"), ())
    )[0]
    start, end = gap.get("start"), gap.get("end")
    if not start:
        since = "which had no reading on record"
    elif end:
        since = (
            f"which had sent no reading since {day_in_words(start, weekday=False)} "
            f"and did not report again until {day_in_words(end, weekday=False)}"
        )
    else:
        since = f"which had sent no reading since {day_in_words(start, weekday=False)}"
    return f"Not quoted: this was said on {day_in_words(day, weekday=False)} and rests on his {noun}, {since}."


def unsourced(texts: Iterable[Any], day: Any, gapped: Iterable[Mapping[str, Any]]) -> dict | None:
    """The `unsourced` note for texts dated `day`, or None when they may be quoted.

    `gapped` is the interval form (`gap_instruments`). None unless some text cites an
    instrument AND `day` falls inside one of that instrument's gaps (`in_gap`) — open or
    closed, whatever the instrument's state is now."""
    on = _day(day)
    if on is None:
        return None
    pool = [t for t in texts if isinstance(t, str) and t.strip()]
    if not pool:
        return None
    for inst in gapped:
        gap = next((g for g in inst.get("gaps") or [] if in_gap(on, g)), None)
        if gap is None:
            continue
        if any(cites(t, str(inst.get("source") or ""), inst.get("datatype")) for t in pool):
            return {
                "reason": gap.get("reason"),
                "instrument": {"source": inst.get("source"), "datatype": inst.get("datatype")},
                "last_seen": gap.get("start"),
                "gap": {"start": gap.get("start"), "end": gap.get("end")},
                "said_on": on,
                "text": sentence(on, inst, gap),
            }
    return None


def split_claims(claims: Mapping[str, Any] | None, day: Any, dark: list[dict]) -> tuple[dict, dict]:
    """A docket item's `claims` → (the claims that may be quoted, {coach: unsourced note})."""
    kept: dict = {}
    held: dict = {}
    for coach, text in dict(claims or {}).items():
        note = unsourced([text], day, dark)
        if note:
            held[coach] = note
        else:
            kept[coach] = text
    return kept, held


def scrub_rows(rows: Any, dark: list[dict], *, day_key: str, text_keys: tuple[str, ...], list_keys: tuple[str, ...] = ()) -> Any:
    """Dated rows (a coach's output trail, stance history, latest checked call) with every
    held row's words removed: each `text_keys` field becomes "" and each `list_keys` field []
    (the renderers already drop a row with nothing to say), and the row gains `unsourced`.
    Rows that may be quoted come back untouched; a non-list comes back as it was."""
    if not dark or not isinstance(rows, list):
        return rows
    out = []
    for row in rows:
        if not isinstance(row, dict):
            out.append(row)
            continue
        texts = [row.get(k) for k in text_keys] + [t for k in list_keys for t in (row.get(k) or []) if isinstance(t, str)]
        note = unsourced(texts, row.get(day_key), dark)
        if note is None:
            out.append(row)
            continue
        out.append({**row, **{k: "" for k in text_keys if k in row}, **{k: [] for k in list_keys if k in row}, "unsourced": note})
    return out


def scrub_one(row: Any, dark: list[dict], *, day_key: str, text_keys: tuple[str, ...]) -> Any:
    """`scrub_rows` for a single dated record (or None)."""
    if not isinstance(row, dict):
        return row
    return scrub_rows([row], dark, day_key=day_key, text_keys=text_keys)[0]
