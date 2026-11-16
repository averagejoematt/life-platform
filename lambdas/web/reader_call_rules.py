"""reader_call_rules.py — the pure half of "your call beside the coaches" (#6088, built DARK).

Owner ruling 2026-11-16: reader participation is part of the product, but no reader action may alter the owner's
historical evidence, grading records or experiments, and it is developed and tested privately until its safeguards
are ready. This module is everything about a reader's call that needs no AWS and no clock of its own:

  * WHICH calls a reader may call beside — a coach's direction call (``directional`` spec, ``up``/``down``) or number
    call (``point`` spec with a level and a tolerance). Nothing else: a yes/no, a sealed bet, an observation and a
    conditional are refused, because their "same kind of call" is not one tap.
  * THE CLOSED CHOICE SET for each kind — direction: up / down / about the same; number: above / within / below the
    coach's stated level and tolerance. No free text exists anywhere in the feature.
  * THE TIMING TOKEN — ``mint_token`` / ``check_token``: an HMAC over (purpose, call, identity, issued-at) that the
    GET hands out and the POST must return between ``TOKEN_MIN_AGE_S`` and ``TOKEN_MAX_AGE_S`` later.
  * THE READING'S SIDE — ``reading_side``: given a graded call's PUBLIC grading fields, which choice the reading came
    down on. Pure; never re-grades, never writes, and reads only what the grader already stored.

The master switch ``READER_CALL_LIVE`` is committed False. With it off the route answers "not available" and writes
nothing (``web.site_api_reader_call``), and the v9 control is not built into any page.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
from typing import Any, Optional

#: The master switch, COMMITTED OFF (#6088). Turning it on is a reviewed one-line change, after the owner's go.
READER_CALL_LIVE = False

#: The partition every reader-call row lives in. Never ``USER#…`` and never ``COACH#…`` (the owner's hard line).
PK_PREFIX = "READERCALL#"
TAP_SK_PREFIX = "TAP#"  # the dedup marker: one per (identity, call), TTL'd
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

#: A public call id as the v9 page addresses it: ``<coach short id>-<prediction id>`` (scripts/publish_snapshot.py).
CALL_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}-[A-Za-z0-9_][A-Za-z0-9_\-]{0,150}$")

COPY = "Make your own call. It is counted with other readers', apart from the coach's record."
NOT_EVIDENCE = "A count of readers' taps. It is not evidence about the experiment and is never part of the coach's record."


def call_kind(spec: Any) -> Optional[str]:
    """``direction`` / ``number`` for a spec a reader can call beside, else None (refused)."""
    if not isinstance(spec, dict):
        return None
    t = str(spec.get("type") or "").strip().lower()
    if t == "directional" and str(spec.get("condition") or "").strip().lower() in ("up", "down"):
        return DIRECTION
    if t == "point" and _num(spec.get("threshold")) is not None and _num(spec.get("tolerance")) is not None:
        return NUMBER
    return None


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


def choices(spec: dict) -> list[dict]:
    """The closed choice set for this call, with the words a page prints. ``[]`` when the call is refused."""
    kind = call_kind(spec)
    if kind == DIRECTION:
        return [{"id": c, "label": _DIRECTION_WORDS[c]} for c in CHOICES[DIRECTION]]
    if kind == NUMBER:
        level, tol = _fmt(_num(spec["threshold"])), _fmt(_num(spec["tolerance"]))
        return [
            {"id": "above", "label": f"Above {level} (by more than {tol})"},
            {"id": "within", "label": f"Within {tol} of {level}"},
            {"id": "below", "label": f"Below {level} (by more than {tol})"},
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


def reading_side(spec: dict, notes: Any) -> Optional[str]:
    """Which choice the graded reading came down on, from the grader's stored public fields — or None.

    Direction: the window the grader measured (``outcome_notes.window.direction`` — up / down / flat, #4617).
    Number: the grader's reading (``actual_value``) against the call's level ± tolerance, with the grader's own rule
    (``|actual − level| <= tolerance`` is within, ``coach.prediction_point_grader``). A call graded by counting days
    (``graded_as: count``), a legacy window-less direction grade, or a missing reading names no side.
    """
    kind = call_kind(spec)
    if kind is None or not isinstance(notes, dict) or notes.get("graded_as") == "count":
        return None
    if kind == DIRECTION:
        window = notes.get("window")
        d = str(window.get("direction") or "").lower() if isinstance(window, dict) else ""
        return {"up": "up", "down": "down", "flat": "same"}.get(d)
    actual, level, tol = _num(notes.get("actual_value")), _num(spec.get("threshold")), _num(spec.get("tolerance"))
    if actual is None or level is None or tol is None:
        return None
    if abs(actual - level) <= tol:
        return "within"
    return "above" if actual > level else "below"


def tally_of(rows: Any, spec: dict) -> dict:
    """``{choice: count}`` over the call's closed set (zeros included) from ``TALLY#`` rows, plus ``total``."""
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
