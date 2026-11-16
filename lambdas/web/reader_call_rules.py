"""reader_call_rules.py — the pure half of "your call beside the coaches" (#6088 built it dark; #6114 readies it).

Owner rulings 2026-11-16: reader participation is part of the product, but no reader action may alter the owner's
historical evidence, grading records or experiments (ADR-169), reader calls never enter the coaches-versus-baseline
record, every count is a count of READER CALLS (never of unique readers), no live total is shown before the window
closes, and nothing is accepted once the deadline is reached or the outcome is available. This module is everything
about a reader's call that needs no AWS and no clock of its own:

  * WHO MAY BE CALLED BESIDE — a coach's direction call (``directional`` spec, ``up``/``down``) or number call
    (``point`` spec with a level and a tolerance). Nothing else: a yes/no, a sealed bet, an observation and a
    conditional are refused, because their "same kind of call" is not one tap.
  * THE QUESTION — ``question``: stated ENTIRELY from fields the call's own public page already prints for a call whose
    words are withheld (the measure in reader words, the day it was made, the call's kind, and the grading line —
    ``grading.how`` — which already carries the window length, the level and the tolerance). Never the claim, never
    stored prose, never an id slug.
  * THE LOCK — ``closes_on``: the earlier of the call's due day and the day its outcome can be read (a direction call's
    measured window ends; a number call's target day). A call is OPEN only before that day, while it is pending and
    while no outcome field is present (``is_open``).
  * THE CLOSED CHOICE SET for each kind — direction: up / down / about the same; number: above / within / below.
  * THE TIMING TOKEN — ``mint_token`` / ``check_token``: an HMAC over (purpose, call, identity, issued-at).
  * THE READING'S SIDE — ``reading_side``: which choice the graded reading came down on, from the grader's stored fields.

The master switch ``READER_CALL_LIVE`` is committed False; ``web.site_api_reader_call`` ANDs it with a runtime kill
switch (SSM ``/life-platform/reader-call``, fail closed).
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
from datetime import date, timedelta
from typing import Any, Optional

#: The master switch, COMMITTED OFF (#6088). Going public is a reviewed one-line change, after the owner's go.
READER_CALL_LIVE = False

#: The partition every reader-call row lives in, keyed by the call's public item id. Never ``USER#…`` / ``COACH#…``.
PK_PREFIX = "READERCALL#"
TAP_SK_PREFIX = "TAP#"  # the dedup marker: one per (identity, call), TTL'd; it carries the reader's own choice
TALLY_SK_PREFIX = "TALLY#"  # the counter: one per (call, choice)

#: What the timing token is for — bound into the MAC so a token minted for anything else never verifies here.
TOKEN_PURPOSE = "reader_call/v1"  # noqa: S105 — a domain-separation label, not a secret
TOKEN_MIN_AGE_S = 2  # a POST faster than a person can read the question is a script
TOKEN_MAX_AGE_S = 3600  # a token is good for one sitting, not a harvest
#: How long a dedup marker outlives the call's due day (seconds), so a late duplicate is still refused.
DEDUP_GRACE_S = 3 * 86400

DIRECTION = "direction"
NUMBER = "number"
CHOICES = {DIRECTION: ("up", "down", "same"), NUMBER: ("above", "within", "below")}
_DIRECTION_WORDS = {"up": "Up", "down": "Down", "same": "About the same"}
#: Row fields that mean an outcome exists. Any one present closes the call, whatever the status says.
OUTCOME_FIELDS = ("outcome", "outcome_date", "outcome_notes", "outcome_value", "evaluated_date", "settled_date")

#: A call's PUBLIC item id, as /api/ledger_export serves it: ``<coach short id>:<prediction id>``.
ITEM_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}:[A-Za-z0-9_][A-Za-z0-9_\-]{0,150}$")

COPY = "Make your own call. It is counted with the other reader calls, apart from the coach's record."
NOT_EVIDENCE = "A count of reader calls. It is not evidence about the experiment and is never part of the coach's record."
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _day(iso: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(iso)[:10])
    except (TypeError, ValueError):
        return None


def day_words(iso: Any) -> Optional[str]:
    """``2026-11-23`` → ``23 November`` (the v9 rule: dates in words)."""
    d = _day(iso)
    return f"{d.day} {_MONTHS[d.month - 1]}" if d else None


def call_kind(spec: Any) -> Optional[str]:
    """``direction`` / ``number`` for a spec a reader can call beside, else None (refused)."""
    if not isinstance(spec, dict):
        return None
    t = str(spec.get("type") or "").strip().lower()
    if t == "directional" and str(spec.get("condition") or "").strip().lower() in ("up", "down"):
        return DIRECTION
    if (
        t == "point"
        and _num(spec.get("threshold")) is not None
        and _num(spec.get("tolerance")) is not None
        and _day(spec.get("target_date"))
    ):
        return NUMBER
    return None


def _unit(unit: Optional[str]) -> str:
    return unit or ""


def choices(spec: dict, unit: Optional[str] = None) -> list[dict]:
    """The closed choice set for this call, with the words a page prints. ``[]`` when the call is refused."""
    kind = call_kind(spec)
    if kind == DIRECTION:
        return [{"id": c, "label": _DIRECTION_WORDS[c]} for c in CHOICES[DIRECTION]]
    if kind == NUMBER:
        level, tol = _fmt(_num(spec["threshold"])), _fmt(_num(spec["tolerance"]))
        u = _unit(unit)
        return [
            {"id": "above", "label": f"Above {level}{u} by more than {tol}"},
            {"id": "within", "label": f"Within {tol} of {level}{u}"},
            {"id": "below", "label": f"Below {level}{u} by more than {tol}"},
        ]
    return []


def coach_choice(spec: dict) -> Optional[str]:
    """The coach's own call in the reader vocabulary: its direction, or ``within`` for a number call."""
    kind = call_kind(spec)
    if kind == DIRECTION:
        return str(spec["condition"]).strip().lower()
    if kind == NUMBER:
        return "within"
    return None


def valid_choice(spec: dict, choice: Any) -> bool:
    kind = call_kind(spec)
    return kind is not None and isinstance(choice, str) and choice in CHOICES[kind]


def window(spec: dict, made_on: Any, effective_days: Any) -> Optional[tuple]:
    """``(start, end)`` ISO days the grade reads. Direction: the day the call was made to that day plus the window the
    grader uses (the spec's stated ``evaluation_window_days``, else ``effective_days``) — the same rule as
    ``coach_prediction_evaluator._evaluate_directional``. Number: the target day, both ends."""
    kind = call_kind(spec)
    if kind == NUMBER:
        t = _day(spec.get("target_date"))
        return (t.isoformat(), t.isoformat()) if t else None
    start = _day(made_on)
    days = spec.get("evaluation_window_days") or effective_days
    try:
        n = int(days)
    except (TypeError, ValueError):
        return None
    if start is None or n <= 0:
        return None
    return start.isoformat(), (start + timedelta(days=n)).isoformat()


def closes_on(spec: dict, made_on: Any, effective_days: Any, due: Any) -> Optional[str]:
    """The day reader calls close: the earlier of the due day and the day the outcome can first be read (the window's
    last day). None when either is unknown — such a call never opens."""
    w = window(spec, made_on, effective_days)
    d = _day(due)
    end = _day(w[1]) if w else None
    if end is None or d is None:
        return None
    return min(end, d).isoformat()


def outcome_present(row: dict) -> bool:
    """Any stored outcome field closes the call, whatever its status says (the lock does not trust one field)."""
    return any(row.get(f) not in (None, "", {}, []) for f in OUTCOME_FIELDS)


def is_open(row: dict, status: Any, close_day: Optional[str], today: str) -> bool:
    """Open = pending AND no outcome field AND today is before the close day. Whichever fails first closes it."""
    return status == "pending" and not outcome_present(row) and bool(close_day) and str(today) < str(close_day)


def question(spec: dict, measure: str, made_on: Any, effective_days: Any, unit: Optional[str] = None) -> Optional[str]:
    """The question, from public structured fields only (see the module docstring). None when it cannot be stated."""
    kind = call_kind(spec)
    w = window(spec, made_on, effective_days)
    if not kind or not w or not measure:
        return None
    if kind == DIRECTION:
        return f"From {day_words(w[0])} to {day_words(w[1])}, will the {measure} go up, go down, or stay about the same?"
    level, tol = _fmt(_num(spec["threshold"])), _fmt(_num(spec["tolerance"]))
    return f"On {day_words(w[1])}, will the {measure} be above, within {tol} of, or below {level}{_unit(unit)}?"


def reading_side(spec: dict, notes: Any) -> Optional[str]:
    """Which choice the graded reading came down on, from the grader's stored public fields — or None.

    Direction: the window the grader measured (``outcome_notes.window.direction`` — up / down / flat, #4617).
    Number: the grader's reading (``actual_value``) against the call's level ± tolerance, with the grader's own rule
    (``|actual − level| <= tolerance`` is within, ``coach.prediction_point_grader``). A call graded by counting days,
    a legacy window-less direction grade, or a missing reading names no side.
    """
    kind = call_kind(spec)
    if kind is None or not isinstance(notes, dict) or notes.get("graded_as") == "count":
        return None
    if kind == DIRECTION:
        w = notes.get("window")
        d = str(w.get("direction") or "").lower() if isinstance(w, dict) else ""
        return {"up": "up", "down": "down", "flat": "same"}.get(d)
    actual, level, tol = _num(notes.get("actual_value")), _num(spec.get("threshold")), _num(spec.get("tolerance"))
    if actual is None or level is None or tol is None:
        return None
    if abs(actual - level) <= tol:
        return "within"
    return "above" if actual > level else "below"


def reader_calls_of(rows: Any, spec: dict) -> dict:
    """``{"counts": {choice: n}, "total": n}`` — a count of reader CALLS per choice (zeros included), from ``TALLY#``
    rows. Never a count of people: one network may call once per call, and nothing establishes who is behind it."""
    kind = call_kind(spec)
    counts = {c: 0 for c in CHOICES.get(kind or "", ())}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        choice = str(row.get("sk") or "")[len(TALLY_SK_PREFIX) :]
        n = _num(row.get("count"))
        if choice in counts and n is not None and n > 0:
            counts[choice] = int(n)
    return {"counts": counts, "total": sum(counts.values())}


def _mac(key: bytes, call_id: str, identity: str, issued: int) -> str:
    msg = f"{TOKEN_PURPOSE}|{call_id}|{identity}|{issued}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()[:32]


def mint_token(key: bytes, call_id: str, identity: str, now: int) -> str:
    """``<issued>.<mac>`` — bound to the call, the caller's salted identity and the instant it was issued."""
    return f"{int(now)}.{_mac(key, call_id, identity, int(now))}"


def check_token(key: bytes, token: Any, call_id: str, identity: str, now: int) -> Optional[str]:
    """None when the token verifies; otherwise the refusal reason (``malformed`` / ``forged`` / ``too_young`` /
    ``expired``). The MAC is checked before the age, so a forged token is never told its age was fine."""
    if not isinstance(token, str) or token.count(".") != 1 or len(token) > 64:
        return "malformed"
    issued_s, mac = token.split(".")
    if not issued_s.isdigit() or len(mac) != 32:
        return "malformed"
    issued = int(issued_s)
    if not hmac.compare_digest(mac, _mac(key, call_id, identity, issued)):
        return "forged"
    age = int(now) - issued
    if age < TOKEN_MIN_AGE_S:
        return "too_young"
    if age > TOKEN_MAX_AGE_S:
        return "expired"
    return None


def honeypot_filled(body: dict) -> bool:
    """The ``hp`` field is never shown to a person; any non-empty value is a form-filling script."""
    v = body.get("hp")
    return v not in (None, "", False)
