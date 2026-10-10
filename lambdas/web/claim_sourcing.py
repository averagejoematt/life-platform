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
A served text is NOT QUOTED when all three hold:

  1. it CITES an instrument — one of that instrument's phrases below appears in it
     (`CITES`; the phrase, not the speaker, decides, so a nutrition-coach sentence "based
     on CGM data" is held too);
  2. that instrument is DARK right now — `health.instrument_presence.absent_coaches`, the
     ONE derivation `/api/source_freshness` serves; and
  3. the text is dated AFTER the instrument's last reading (`last_seen`), so the instrument
     had nothing behind it on that day. A text dated on or before `last_seen`, or with no
     date at all, is quoted — this module never guesses.

The words are never edited. A held text is removed from the payload and an `unsourced`
note takes its place, with the engine's reason, the instrument, its last reading and one
sentence a page prints beside the speaker's name. Removing (rather than annotating in
place) is what guards every renderer at once: a page that has never heard of `unsourced`
simply has nothing to quote.

What this does NOT know
-----------------------
Liveness is a NOW fact: the sentinel carries the last reading, not the history of gaps.
Once the sensor reports again its `last_seen` moves forward and an older gap is no longer
visible here, so a text from that gap would be quoted again. Recording gap intervals is
the follow-up named on #4673; until then the rule covers every gap that is still open.

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


def dark_instruments(absent: Mapping[str, Mapping[str, Any]] | None) -> list[dict]:
    """The distinct dark instruments behind an `absent_coaches()` map, each as
    {source, datatype, label, last_seen, reason}. Order is the map's; one row per instrument."""
    out: list[dict] = []
    seen: set[tuple[str, str | None]] = set()
    for state in (absent or {}).values():
        key = (str(state.get("source") or ""), state.get("datatype") or None)
        if not key[0] or key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "source": key[0],
                "datatype": key[1],
                "label": state.get("label"),
                "last_seen": _day(state.get("last_seen")),
                "reason": state.get("reason"),
            }
        )
    return out


def cites(text: Any, source: str, datatype: str | None = None) -> bool:
    """True when `text` names the instrument (or its data) by one of its phrases."""
    pattern = _COMPILED.get((source, datatype or None))
    return bool(pattern and isinstance(text, str) and pattern.search(text))


def sentence(day: str, instrument: Mapping[str, Any]) -> str:
    """The one sentence a page prints in place of the held words (dates in words, #4182)."""
    noun = CITES.get(
        (str(instrument.get("source") or ""), instrument.get("datatype") or None), (str(instrument.get("label") or "sensor"), ())
    )[0]
    last = instrument.get("last_seen")
    since = f"which had sent no reading since {day_in_words(last, weekday=False)}" if last else "which had no reading on record"
    return f"Not quoted: this was said on {day_in_words(day, weekday=False)} and rests on his {noun}, {since}."


def unsourced(texts: Iterable[Any], day: Any, dark: Iterable[Mapping[str, Any]]) -> dict | None:
    """The `unsourced` note for texts dated `day`, or None when they may be quoted.

    None unless some text cites a dark instrument AND `day` is a day key after that
    instrument's last reading (or the instrument has no reading on record at all)."""
    on = _day(day)
    if on is None:
        return None
    pool = [t for t in texts if isinstance(t, str) and t.strip()]
    for inst in dark:
        last = inst.get("last_seen")
        if last and on <= last:
            continue
        if any(cites(t, str(inst.get("source") or ""), inst.get("datatype")) for t in pool):
            return {
                "reason": inst.get("reason"),
                "instrument": {"source": inst.get("source"), "datatype": inst.get("datatype")},
                "last_seen": last,
                "said_on": on,
                "text": sentence(on, inst),
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
