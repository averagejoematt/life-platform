"""critics_apply.py — applying the critics' `change` verdicts to a routine IR (#3752, #4149).

Extracted from `coach.critics` (#4149; the #4112 sibling precedent — that module was nearing
its size ceiling). `critics.apply_changes` re-exports `apply_changes` from here unchanged, so
every caller and test still reads it through `coach.critics`.

THE FLOOR CLAMP (#4149). On 2026-09-23 the joints critic cut squat_barbell to 36 kg and the
commit gate then refused the draft against its 48 kg subtract-only floor — a red-team change
that produced an uncommittable routine. `apply_changes(..., set_floors=...)` takes the commit
gate's own per-set floors (`mcp.hevy_prescription_gate.critic_set_floors`) and holds every
working set a change touched at that floor, naming the clash on the change record
(`conflict`). A load change the floor swallows whole is `applied: False` — surfaced, never an
uncommittable draft.

PURE: no I/O, and no import of `coach.critics` (which imports this module).
"""

from __future__ import annotations

import re
from typing import Any, Callable

# `change` grammar — the only fields a critic may move, and the only ones `apply_changes`
# knows how to move. Anything else is recorded as `unapplied` and never silently dropped.
CHANGE_FIELD_RE = re.compile(r"^(exercises\[(\d+)\]\.(weight_lbs|set_count|reps|drop)|session\.total_sets)$")
# #4161 RULING (the 2026-09-24 red team, owner-approved: "drop" was its primary recommendation): NO critic adds
# sets. The rate advocate's "+1 set" is DROPPED, not restricted — in a deficit 20 vs 12 sets/week gave identical
# lean-mass retention (Roth 2023 SJMSS 33(1):20 doi:10.1111/sms.14237), so an added set buys nothing the evidence
# can see. Was 3 (#4149). A `session.total_sets` change ABOVE the draft is refused by name, never applied.
MAX_ADDED_SETS = 0
_LBS_PER_KG = 2.2046226218


def _label(ex: Any) -> str:
    tag = getattr(ex, "rationale_tag", "") or ""
    key = getattr(ex, "movement_key", "") or ""
    return (tag if tag and tag != "custom" else key) or "?"


# #4149: the commit gate's tolerance (`mcp.recovery_authoring.LOAD_TOLERANCE_KG`, #4065) — this
# module cannot import mcp/, so the number is mirrored and a test holds the two equal.
FLOOR_TOLERANCE_KG = 0.05


def apply_changes(ir: Any, verdicts: list[dict[str, Any]], *, set_floors: Callable[[Any], list] | None = None) -> list[dict[str, Any]]:
    """Apply every `change` verdict to the IR in place. Returns one record per change,
    `applied` True/False with the reason — an unapplied change is visible, never dropped.

    `set_floors(exercise)` (#4149) is the commit gate's own per-set floor in kg (None where no
    floor applies), injected by the caller from `mcp.hevy_prescription_gate.critic_set_floors`.
    After each change, every working set of the exercise it touched is held at that floor and
    the clash is NAMED on the record (`conflict`): no critic change may produce a draft the
    subtract-only gate refuses. A load change the floor swallows whole is `applied: False`."""
    records: list[dict[str, Any]] = []
    for v in verdicts:
        if v.get("verdict") != "change" or not v.get("field"):
            if v.get("verdict") == "change":
                records.append(
                    {
                        "critic": v["critic"],
                        "field": None,
                        "applied": False,
                        "why": "change carried no mechanical field — coach must act on it",
                    }
                )
            continue
        m = CHANGE_FIELD_RE.match(v["field"])
        rec = {"critic": v["critic"], "field": v["field"], "to": v.get("to"), "applied": False, "why": None}
        if not m:
            rec["why"] = "field outside the change grammar"
            records.append(rec)
            continue
        try:
            before = _loads(ir)
            rec["applied"], rec["why"] = _apply_one(ir, m, v.get("to"))
            if set_floors is not None and rec["applied"]:
                _hold_at_floors(ir, m, set_floors, rec, before, v["critic"])
        except Exception as e:  # noqa: BLE001
            rec["why"] = f"{type(e).__name__}: {e}"
        records.append(rec)
    return records


def _loads(ir: Any) -> list[tuple[int, list]]:
    return [(id(ex), [getattr(s, "weight_kg", None) for s in ex.sets]) for ex in getattr(ir, "exercises", None) or []]


def _hold_at_floors(ir: Any, m: "re.Match[str]", set_floors: Callable[[Any], list], rec: dict[str, Any], before: list, critic: str) -> None:
    """Raise every working set the change touched back to the gate's floor, naming each clash."""
    prior = dict(before)
    clashes: list[str] = []
    for ex in getattr(ir, "exercises", None) or []:
        if [getattr(s, "weight_kg", None) for s in ex.sets] == prior.get(id(ex)):
            continue  # untouched by this change — the coach's own draft is the gate's business, not the clamp's
        floors = list(set_floors(ex) or [])
        for i, s in enumerate(ex.sets):
            f = floors[i] if i < len(floors) else None
            w = getattr(s, "weight_kg", None)
            if f is None or w is None or (getattr(s, "type", "normal") or "normal") == "warmup" or w >= float(f) - FLOOR_TOLERANCE_KG:
                continue
            clashes.append(f"{_label(ex)} set {i + 1} {float(w):.1f}kg < floor {float(f):.1f}kg")
            s.weight_kg = float(f)
    if not clashes:
        return
    rec["conflict"] = f"{critic} vs the subtract-only floor: " + "; ".join(clashes) + " — clamped to the floor (#4149)"
    if m.group(3) == "weight_lbs" and dict(_loads(ir)) == prior:
        rec["applied"], rec["why"] = (
            False,
            "conflict: the floor holds every working set this load change would move — surfaced, not applied",
        )


def _apply_one(ir: Any, m: "re.Match[str]", to: Any) -> tuple[bool, str | None]:
    exercises = getattr(ir, "exercises", None) or []
    if m.group(1) == "session.total_sets":
        if to == "hold":
            return False, "hold: no growth this week — the draft is not enlarged, nothing to trim automatically"
        target = int(to)
        current = sum(len(getattr(e, "sets", []) or []) for e in exercises)
        if target == current:
            return False, f"total_sets already {current}"
        if target > current:
            # #4161: the advocate's add-sets lane is closed — MAX_ADDED_SETS is 0 (Roth 2023)
            return False, f"refused: no critic adds sets ({current} -> {target}; MAX_ADDED_SETS={MAX_ADDED_SETS}, #4161 — Roth 2023)"
        # LIVE FINDING 2026-09-20 (routine 73bc228c v2): trimming from the LAST exercise backwards
        # took a 22 -> 18 cut entirely out of face pulls and hammer curls (3 -> 1 each) and left
        # the two 4-set anchors untouched — a deload shape no coach would write. Round-robin:
        # one set at a time from the exercise with the MOST sets (ties -> the later one), never
        # below one set per exercise, so a cut spreads across the session instead of hollowing
        # out its tail.
        while current > target:
            candidates = [ex for ex in exercises if len(ex.sets) > 1]
            if not candidates:
                break
            victim = max(candidates, key=lambda ex: (len(ex.sets), exercises.index(ex)))
            victim.sets.pop()
            current -= 1
        return current == target, None if current == target else f"could only trim to {current}"
    idx, attr = int(m.group(2)), m.group(3)
    if idx >= len(exercises):
        return False, f"exercises[{idx}] does not exist"
    ex = exercises[idx]
    if attr == "drop":
        exercises.pop(idx)
        return True, None
    if attr == "weight_lbs":
        kg = float(to) / _LBS_PER_KG
        for s in ex.sets:
            if (getattr(s, "type", "normal") or "normal") != "warmup" and getattr(s, "weight_kg", None) is not None:
                s.weight_kg = round(kg, 2)
        return True, None
    if attr == "reps":
        for s in ex.sets:
            if (getattr(s, "type", "normal") or "normal") != "warmup":
                s.reps = int(to)
        return True, None
    if attr == "set_count":
        n = int(to)
        if n < 1:
            return False, "set_count below 1"
        if n > len(ex.sets):
            # #4161: MAX_ADDED_SETS = 0 is structural — a set_count ABOVE the draft is an addition, refused by name
            return False, f"refused: no critic adds sets (set_count {len(ex.sets)} -> {n}; MAX_ADDED_SETS={MAX_ADDED_SETS}, #4161)"
        while len(ex.sets) > n:
            ex.sets.pop()
        return len(ex.sets) == n, None
    return False, "unreachable"
