"""rep_scheme.py — the program's heavy-exposure scheme, and the load grid loads are judged on (#4065).

WHY THIS EXISTS

v0.3 §3 prescribes a heavy exposure as ONE top set at RPE 7–8 plus TWO back-offs at −10 %.
The chat-path subtract-only gate (`mcp/hevy_prescription_gate.py` → `recovery_authoring.
audit_prescription`) compared EVERY working set against the movement's band-matched floor,
so the two back-offs the program itself prescribes read as subtraction violations and the
scheme could not be committed as written (owner report, 2026-09-22). And it compared loads
as bare floats: a set AT the floor failed on a kg<->lb round trip (63.5029 < 63.50300732).

ONE SOURCE — THE PROGRAM'S OWN NUMBERS, NOT A HAND LIST AND NOT A SECOND PARSE

The scheme the gate exempts is `program_structure.EXPOSURES["heavy"]` — the SAME dict
`program_structure.session_for_role` builds the generator's top / back-off sets from, so the
gate cannot exempt a scheme the generator does not prescribe, nor refuse one it does. #4138
first derived it by regex from the owner's redline prose; that made TWO derivations of one
scheme (the generator read the numbers, the gate parsed the prose), and a prose edit that
broke the grammar would have refused the generator's own back-offs — the #4065 defect
re-created by its fix. The prose (`owner_redlines.REDLINES["lifting_sessions_per_wk"]
["rep_scheme"]`) stays the owner-approved WORDING: `parse_rep_scheme` still reads it, and
`heavy_back_off_scheme()` reports whether it agrees with the numbers (`prose_check`) —
tests/test_program_session_4064_4147.py holds the two equal, so a disagreement reds CI
rather than silently changing what the gate exempts. Read failure fails CLOSED
(`status: "unparsed"`): a scheme the gate cannot read exempts nothing.

THE LOAD GRID (the ONLY tolerance, derived from the equipment, not typed)

Loads reach Hevy two ways and neither is a plate: the chat path converts the owner's pounds at
4 dp (`tools_hevy_routine._coerce_sets`, 140 lb -> 63.5029 kg), the generator rounds to 0.5 kg
(`load_ramp`, `full_body_session._apply_back_offs`), and Hevy's history hands back the exact
kg of the pound he logged (140 lb -> 63.50300732). So two numbers for the same bar differ at
the fourth decimal — or, for a 0.5 kg floor displayed in lb and typed back whole (64.5 kg ->
142.2 lb -> "142" -> 64.41 kg), by 0.09 kg, which #4138's hand-typed 0.05 kg tolerance still
REFUSED. Neither difference is a weight he can take off the bar.

So the comparison is on the plate grid: the gap between floor and set, in the pound he loads,
is rounded to whole `PLATE_STEP_LB` steps, and a set is below its floor only when it is at
least ONE step under (`steps_under_floor`). Equality passes by construction; so does every
representation of the same loadable weight; one real plate step down still refuses. The gap
is rounded rather than each value snapped to the grid, because snapping has a cliff at every
cell boundary (a 0.5 kg floor at 146.6 lb snaps UP to 147.5 and refuses "146") — the exact
false refusal this module exists to end.

WHAT IS PLATFORM-PROPOSED HERE (ADR-105 — the weakest label, stated where it fires)

`PLATE_STEP_LB`: 2.5 lb, the smallest barbell increment (one 1.25 lb plate a side) and the
finest step two loads he can actually lift may differ by; dumbbell racks step 5. It is the
platform's statement of his equipment, not a measurement, and it is the ONLY slack in the
floor comparison.

`BACK_OFF_ROUNDING_LB`: the −pct back-off target is rounded DOWN to the next 5 lb before it is
used as a back-off's minimum on the non-v0.3 path. 10 % off 80 lb is 72 lb, and the dumbbell
rack holds 70 — a back-off the athlete can actually pick up must pass. 5 lb is the common
barbell/dumbbell step; it is the platform's choice, not the owner's.
"""

from __future__ import annotations

import math
import re
from typing import Any

LB_IN_KG = 0.45359237

PLATE_STEP_LB = 2.5
"""platform-proposed: the finest step two loadable weights differ by (see module doc)."""

BACK_OFF_ROUNDING_LB = 5.0
"""platform-proposed: the −pct back-off target rounds DOWN to this load step (see module doc)."""

SCHEME_SOURCE = "program_structure.EXPOSURES['heavy']"
PROSE_SOURCE = "owner_redlines.REDLINES['lifting_sessions_per_wk']['rep_scheme']"

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
    """The owner's PROSE → the structured heavy-exposure scheme. Pure. `status` is "ok" or "unparsed".

    The cross-check, not the source: `heavy_back_off_scheme` compares this against the program's numbers."""
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
        "source": PROSE_SOURCE,
        "source_text": text,
    }


def _prose_check(numbers: dict[str, Any]) -> tuple[str, str | None]:
    """Does the owner-approved wording say what the program's numbers say? Fail-soft: a prose read
    problem is reported, never lets it override the numbers the generator builds from."""
    try:
        from training import owner_redlines

        text = owner_redlines.REDLINES["lifting_sessions_per_wk"]["rep_scheme"]
    except Exception as e:  # noqa: BLE001 — reported on the scheme, not raised
        return f"unreadable ({type(e).__name__}: {e})", None
    prose = parse_rep_scheme(text)
    if prose.get("status") != "ok":
        return "unparsed", text
    keys = ("top_sets", "back_offs", "back_off_pct", "top_reps")
    return ("agrees" if all(prose[k] == numbers[k] for k in keys) else "disagrees"), text


def heavy_back_off_scheme() -> dict[str, Any]:
    """The ACTIVE program's heavy scheme, from its ONE numeric home — the dict the generator
    prescribes from. Fail-closed on any read error (`status: "unparsed"` exempts nothing)."""
    try:
        from training import program_structure

        heavy = program_structure.EXPOSURES["heavy"]
        numbers = {
            "top_sets": int(heavy["top_sets"]),
            "back_offs": int(heavy["back_off_sets"]),
            "back_off_pct": float(abs(heavy["back_off_pct"])),  # EXPOSURES carries the signed −10; the gate wants the size of the cut
            "top_reps": [int(heavy["reps"][0]), int(heavy["reps"][1])],
        }
    except Exception as e:  # noqa: BLE001 — an unreadable scheme exempts nothing
        return {
            "status": "unparsed",
            "source": SCHEME_SOURCE,
            "source_text": None,
            "reason": f"program scheme unreadable ({type(e).__name__}: {e})",
        }
    check, text = _prose_check(numbers)
    return {
        "status": "ok",
        **numbers,
        "rounding_lb": BACK_OFF_ROUNDING_LB,
        "source": SCHEME_SOURCE,
        "prose_check": check,
        "prose_source": PROSE_SOURCE,
        "source_text": text,
    }


def back_off_min_kg(top_kg: float, scheme: dict[str, Any]) -> float:
    """The lightest load a prescribed back-off off `top_kg` may carry: top × (1 − pct), rounded
    DOWN to the scheme's load step, in pounds (the unit he loads), returned in kg."""
    target_lb = float(top_kg) / LB_IN_KG * (1.0 - float(scheme["back_off_pct"]) / 100.0)
    step = float(scheme.get("rounding_lb") or BACK_OFF_ROUNDING_LB)
    return math.floor(target_lb / step + 1e-9) * step * LB_IN_KG


def steps_under_floor(weight_kg: float, floor_kg: float) -> int:
    """How many whole plate steps `weight_kg` sits UNDER `floor_kg` — 0 at or above the floor,
    and 0 for any gap smaller than half a step (a representation of the same bar, not a plate
    taken off). Round-half-up on the gap, in the pound he loads. Never negative."""
    gap_lb = (float(floor_kg) - float(weight_kg)) / LB_IN_KG
    if gap_lb <= 0:
        return 0
    return int(math.floor(gap_lb / PLATE_STEP_LB + 0.5))


def is_below_floor(weight_kg: float, floor_kg: float) -> bool:
    """The ONE floor comparison: True only when the set is at least one plate step under its floor.
    `audit_prescription` (the commit gate) and `critics_apply._hold_at_floors` (stage 2's clamp)
    both judge with this, so a clamped draft is, by construction, one the gate accepts."""
    return steps_under_floor(weight_kg, floor_kg) >= 1
