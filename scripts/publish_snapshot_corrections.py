#!/usr/bin/env python3
"""scripts/publish_snapshot_corrections.py — dated corrections beside the coaches' historical lines (acceptance, 2026-11-02).

The owner's ruling on the Journey/Day review: "Preserve historical quotes verbatim; add explicit corrections
beside unsupported interpretations." A coach line is published exactly as /api/coach_moves served it; this
module only ADDS a `corrections` list to each line, from the day objects the same snapshot carries — never a
model, never a rewrite. Three checks, each stated in words a reader can verify on the page:

* a figure from an incomplete food record quoted as intake — a number in the line equals the protein grams or
  the calories of a logging-gap day within the line's reach (the day, or the two before it; the coaches write
  each morning about the day before) → the record, its date, and "intake that day is unknown";
* a count of logged days — "N logged days", "every one of them" — against the complete food logs the
  snapshot holds for that month up to the day (incomplete records and days with none counted apart);
* a reading said to climb (or fall) to a value it reached from the other side — "recovery climbing to 58"
  when the morning before read 74.

A check that cannot be decided from the snapshot adds nothing; silence is never a correction.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_COUNT = re.compile(r"\b(\d{1,3})\s+(?:logged days|days logged|days with a food log)\b|\bevery one of them\b", re.IGNORECASE)
_MOVE = re.compile(
    r"\brecovery(?:\s+score)?\s+(climbing|climbed|climbs|rising|rose|rises|up|falling|fell|falls|dropping|dropped|down)\s+to\s+(\d{1,3})\b",
    re.IGNORECASE,
)
_UPWARD = {"climbing", "climbed", "climbs", "rising", "rose", "rises", "up"}


def _words(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{_WEEKDAYS[d.weekday()]} {d.day} {_MONTHS[d.month - 1]}"


def _back(iso: str, n: int) -> str:
    return (date.fromisoformat(iso) - timedelta(days=n)).isoformat()


def _fmt(v: float) -> str:
    return f"{v:g}"


def _gap_figure(text: str, day: str, by_date: dict[str, dict]) -> list[str]:
    quoted: dict[str, list[str]] = {}  # the figure as quoted → the gap days within reach whose record holds it
    for back in (2, 1, 0):
        d = by_date.get(_back(day, back))
        food = (d or {}).get("food") or {}
        if not food.get("logging_gap"):
            continue
        for value, unit, said in (
            (food.get("protein_g"), r"(?:g|grams?)\b", "g of protein"),
            (food.get("calories"), r"(?:kcal|calories)\b", "kcal"),
        ):
            if isinstance(value, (int, float)) and re.search(rf"(?<![\d.]){re.escape(_fmt(float(value)))}\s*{unit}", text, re.IGNORECASE):
                quoted.setdefault(f"{_fmt(float(value))} {said}", []).append(d["date"])
    out = []
    for figure, ds in quoted.items():
        food = by_date[ds[0]]["food"]
        held = f"{_fmt(float(food.get('calories') or 0))} kcal and {_fmt(float(food.get('protein_g') or 0))} g of protein"
        names = [_words(x) for x in ds]
        when = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        out.append(
            f"Correction: {figure} is not what he ate. It is what an incomplete food record held — no diary entries, {held} recorded in all"
            f" — on {when}. Intake {'that day is' if len(ds) == 1 else 'on those days is'} unknown."
        )
    return out


def _logged_count(text: str, day: str, by_date: dict[str, dict]) -> list[str]:
    if not _COUNT.search(text):
        return []
    month = day[:7]
    complete, partial, none = [], [], []
    for iso in sorted(k for k in by_date if k[:7] == month and k <= day):
        d = by_date[iso]
        food = d.get("food")
        if food and not food.get("logging_gap"):
            complete.append(iso)
        elif food:
            partial.append(iso)
        elif d.get("food_state") == "not logged":
            none.append(iso)
    n = len(complete) + len(partial) + len(none)
    if not n or not (partial or none):
        return []
    tail = []
    if partial:
        tail.append(
            f"{len(partial)} {'is an incomplete record' if len(partial) == 1 else 'are incomplete records'} ({', '.join(_words(x) for x in partial)})"
        )
    if none:
        tail.append(f"{len(none)} {'has' if len(none) == 1 else 'have'} no record")
    return [
        f"Correction: through {_words(day)}, {len(complete)} of the {n} days this month have a complete food log; "
        + " and ".join(tail)
        + "."
    ]


def _reading_move(text: str, day: str, by_date: dict[str, dict]) -> list[str]:
    out = []
    for m in _MOVE.finditer(text):
        verb, value = m.group(1).lower(), float(m.group(2))
        for back in range(2):
            here = by_date.get(_back(day, back))
            prev = by_date.get(_back(day, back + 1))
            a = ((prev or {}).get("readings") or {}).get("recovery_pct")
            b = ((here or {}).get("readings") or {}).get("recovery_pct")
            if a is None or b is None or float(b) != value:
                continue
            went_up = float(b) > float(a)
            if (verb in _UPWARD) != went_up and float(a) != float(b):
                said = "climbing" if verb in _UPWARD else "falling"
                fact = "fell" if not went_up else "rose"
                out.append(
                    f"Correction: recovery {fact} to {_fmt(value)} on {_words(here['date'])} from {_fmt(float(a))} the morning before; it was not {said}."
                )
            break
    return out


def annotate_coach_lines(days: list[dict]) -> None:
    """Add `corrections` (a list of sentences, usually empty) to every coach line of every day, in place."""
    by_date = {d["date"]: d for d in days}
    for d in days:
        for line in d.get("coach_lines") or []:
            text = line.get("text") or ""
            line["corrections"] = (
                _gap_figure(text, d["date"], by_date) + _logged_count(text, d["date"], by_date) + _reading_move(text, d["date"], by_date)
            )
