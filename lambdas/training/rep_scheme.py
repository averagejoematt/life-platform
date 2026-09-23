"""rep_scheme.py — the program's heavy-exposure rep scheme as a value the gates can read (#4065).

WHY THIS EXISTS

v0.3 §3 prescribes a heavy exposure as ONE top set at RPE 7–8 plus TWO back-offs at −10 %.
The chat-path subtract-only gate (`mcp/hevy_prescription_gate.py` → `recovery_authoring.
audit_prescription`) compared EVERY working set against the movement's band-matched floor,
so the two back-offs the program itself prescribes read as subtraction violations and the
scheme could not be committed as written (owner report, 2026-09-22).

ONE HOME, PARSED — NOT A SECOND COPY

The scheme has one home: `owner_redlines.REDLINES["lifting_sessions_per_wk"]["rep_scheme"]`,
owner-approved prose. This module DERIVES the structured scheme from that string rather than
restating "1 top + 2 back-offs at 10 %" as a hand list, so a redline edit moves the gate with
it. When the prose stops parsing the result says so (`status: "unparsed"`) and the gate exempts
NOTHING — a scheme the gate cannot read fails closed to the strict floor, never open.

WHAT IS PLATFORM-PROPOSED HERE (ADR-105 — the weakest label, stated where it fires)

`BACK_OFF_ROUNDING_LB`: the −10 % target is rounded DOWN to the next 5 lb before it is used as
a back-off's minimum. 10 % off 80 lb is 72 lb, and the dumbbell rack holds 70 — a back-off the
athlete can actually pick up must pass. 5 lb is the common barbell/dumbbell step; it is the
platform's choice, not the owner's, and it is the ONLY slack in the exemption.
"""

from __future__ import annotations

import math
import re
from typing import Any

LB_IN_KG = 0.45359237

BACK_OFF_ROUNDING_LB = 5.0
"""platform-proposed: the −pct back-off target rounds DOWN to this load step (see module doc)."""

_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4}

# "heavy exposure 4–6: one top set at RPE 7–8 plus two back-offs at −10 %"
_SCHEME_RE = re.compile(
    r"heavy exposure\s+(?P<lo>\d+)\s*[–-]\s*(?P<hi>\d+)\s*:\s*(?P<tops>one|\d+)\s+top sets?\b.*?"
    r"plus\s+(?P<backs>one|two|three|four|\d+)\s+back-?offs?\s+at\s+[−-]\s*(?P<pct>\d+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)


def _count(tok: str) -> int:
    return _WORDS.get(tok.lower()) or int(tok)


def parse_rep_scheme(text: str | None) -> dict[str, Any]:
    """Prose → the structured heavy-exposure scheme. Pure. `status` is "ok" or "unparsed"."""
    m = _SCHEME_RE.search(str(text or ""))
    if not m:
        return {"status": "unparsed", "source_text": text, "reason": "rep_scheme prose did not match the heavy-exposure grammar"}
    return {
        "status": "ok",
        "top_sets": _count(m.group("tops")),
        "back_offs": _count(m.group("backs")),
        "back_off_pct": float(m.group("pct")),
        "top_reps": [int(m.group("lo")), int(m.group("hi"))],
        "rounding_lb": BACK_OFF_ROUNDING_LB,
        "source": "owner_redlines.REDLINES['lifting_sessions_per_wk']['rep_scheme']",
        "source_text": text,
    }


def heavy_back_off_scheme() -> dict[str, Any]:
    """The ACTIVE program's scheme, parsed from its one home. Fail-closed on any read error."""
    try:
        from training import owner_redlines

        text = owner_redlines.REDLINES["lifting_sessions_per_wk"]["rep_scheme"]
    except Exception as e:  # noqa: BLE001 — an unreadable scheme exempts nothing
        return {"status": "unparsed", "source_text": None, "reason": f"redlines unreadable ({type(e).__name__}: {e})"}
    return parse_rep_scheme(text)


def back_off_min_kg(top_kg: float, scheme: dict[str, Any]) -> float:
    """The lightest load a prescribed back-off off `top_kg` may carry: top × (1 − pct), rounded
    DOWN to the scheme's load step, in pounds (the unit he loads), returned in kg."""
    target_lb = float(top_kg) / LB_IN_KG * (1.0 - float(scheme["back_off_pct"]) / 100.0)
    step = float(scheme.get("rounding_lb") or BACK_OFF_ROUNDING_LB)
    return math.floor(target_lb / step + 1e-9) * step * LB_IN_KG
