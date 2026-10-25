"""session_cues.py — a prescribed exposure's CUE, generated from its own sets (#5317), and the carry's dose (#5318).

#5317: the intensity cue's set count was a literal beside the sets array ('MODERATE: 3 sets of 6–10') while the
shoulders+arms press anchor prescribed ONE set (#5266); on 2026-10-24 a coach chat read the cue and drafted 3 x 80 lb,
against the owner's ruled once-a-week, one-set press. The cue is now a function of the sets — count, rep range and the
charter's effort band (`training.effort_ceilings`) — so the instruction he reads and the sets he is prescribed are one
thing. `program_structure.session_prescription_for_role` stamps every exposure's cue from here after every trim (time,
deload); `full_body_session` re-derives it for the sets a block actually carries (the Minimum Viable Session's two).

#5318 (owner ruling B3, 2026-10-24): the shoulders+arms farmer's carry is a TIMED accessory (`CARRY_EXPOSURE`).

Split out of `training.program_structure` (which re-exports every public name here) so neither module crosses the
1000-line ceiling (#1665).
"""

from __future__ import annotations

from typing import Any

from training import effort_ceilings

_EFFORT = effort_ceilings.class_bands()
_C, _L = (f"{_EFFORT[k][0]:g}–{_EFFORT[k][1]:g}" for k in (effort_ceilings.COMPOUNDS, effort_ceilings.LAST_ISOLATION_SET))

_CUE_LABEL = {"heavy": "HEAVY", "moderate": "MODERATE", "volume": "VOLUME", "accessory": "ACCESSORY", "carry": "CARRY"}


def _n(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def _rep_groups(sets: list[dict[str, Any]]) -> str:
    """'3 sets of 8–12' from the sets themselves; consecutive sets with one rep range read as one group."""
    groups: list[list[Any]] = []
    for st in sets:
        reps = list(st.get("reps") or [])
        if groups and groups[-1][1] == reps:
            groups[-1][0] += 1
        else:
            groups.append([1, reps])
    return ", then ".join(f"{_n(c, 'set')} of {r[0]}–{r[-1]}" if r else _n(c, "set") for c, r in groups)


def exposure_cue(intensity: str, sets: list[dict[str, Any]]) -> str:
    """#5317: the cue text, GENERATED from the exposure's own sets array (count, rep range, effort band) — never a literal.

    The press anchor's cue said '3 sets of 6–10' while the anchor prescribed ONE set (#5266); a coach chat read the cue and
    drafted 3 sets. Every exposure's `cue` is stamped from this function after every trim (time, deload), and
    `full_body_session` re-derives it for the sets a block actually carries (the Minimum Viable Session's top set + one)."""
    label = _CUE_LABEL.get(intensity, str(intensity).upper())
    if intensity == "heavy":
        tops = [st for st in sets if st.get("kind") == "top"]
        backs = [st for st in sets if st.get("kind") == "back_off"]
        top_reps = list((tops[0] if tops else {}).get("reps") or [])
        line = f"{label}: {_n(len(tops), 'top set')}" + (f" of {top_reps[0]}–{top_reps[-1]}" if top_reps else "") + f" @ RPE {_C}"
        if backs:
            pct = int(backs[0].get("pct_of_top") or 100) - 100
            line += f", then {_n(len(backs), 'back-off')} at {'−' if pct < 0 else '+'}{abs(pct)} % of the top set"
        return line + " (charter ceilings)."
    if intensity == "carry":
        secs = sorted({int(st.get("duration_seconds") or 0) for st in sets})
        dose = f" of {secs[0]} s" if len(secs) == 1 else ""
        return (
            f"{label}: {len(sets)} {'carry' if len(sets) == 1 else 'carries'}{dose} @ RPE {_C}, tall and braced; load: his own pick "
            "on the first exposure, logged — the engine anchors from that log (charter compound ceiling)."
        )
    if intensity == "accessory":
        if len(sets) == 1:
            return f"{label}: {_rep_groups(sets)} @ RPE {_L} (charter last-set ceiling)."
        return f"{label}: {_rep_groups(sets)} @ RPE {_C}; last set RPE {_L} (charter ceilings)."
    return f"{label}: {_rep_groups(sets)} @ RPE {_C} (charter compound ceiling)."


def _default_sets(spec: dict[str, Any], intensity: str) -> list[dict[str, Any]]:
    """The sets an exposure prescribes at its default count — what its default `cue` is generated from."""
    if intensity == "heavy":
        return [{"kind": "top", "reps": list(spec["reps"])}] + [
            {"kind": "back_off", "reps": list(spec["reps"]), "pct_of_top": 100 + spec["back_off_pct"]} for _ in range(spec["back_off_sets"])
        ]
    if intensity == "carry":
        return [{"kind": "working", "duration_seconds": spec["duration_seconds"]} for _ in range(spec["sets"])]
    return [{"kind": "working", "reps": list(spec["reps"])} for _ in range(spec["sets"])]


CARRY_EXPOSURE: dict[str, Any] = {
    "sets": 2,
    "duration_seconds": 40,
    "effort": effort_ceilings.COMPOUNDS,
    "rest_seconds": 90,
    "duration_provenance": "platform-proposed",
    "load": "owner-picked: the first exposure's load is his, logged; the engine anchors from that log and never from the shrug",
    "stated": "2026-10-24",
    "ruling": "owner ruling B3 2026-10-24 (#5318): 'Replace the 2 DB shrug sets on shoulders_arms with 2 sets of farmer's carry.'",
}
"""A loaded carry's dose (#5318): timed sets, no rep range (a carry is dosed by time, Hevy's `weight_duration` type), no load
prescribed — the set count is the owner's (2, set-neutral with the shrug), the 40 s per carry is the platform's and says so.
Not in `EXPOSURES`: every reader of that table reads a rep range, and a carry has none."""
