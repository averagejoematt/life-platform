"""movement_resolver.py — which listed catalog key a pattern's slot may prescribe (#6014: moved out of `program_structure`).

`program_structure._resolve_movement` is this function, re-exported under its old name, so every caller and every doc that
names it keeps working. Moved unchanged when the heavy-row pin (#6014, `SESSION_TEMPLATES['upper_heavy']['anchor_keys']`) took
`program_structure` over the 1000-line module ceiling: it is the resolver that gives a pin its meaning — the listed order, the
skill ceiling, and a pinned slot with no reachable member saying so ("no reachable member: ...")."""

from __future__ import annotations

from typing import Any

from training import program_conflicts


def resolve_movement(
    keys: list[str],
    catalog_movements: dict[str, Any] | None,
    skill_ceiling: int,
    taken: set[str],
    *,
    family: str | None = None,
    allow_anchor_exemption: bool = True,
):
    """The first catalog key of a pattern the generator may prescribe, in the listed order.

    `family` is the anchor pattern name ("squat", "hinge", "bench", "row", …) when this call
    is resolving one anchor's `catalog_keys`; `None` for an accessory, which never qualifies
    for the exemption below regardless of `allow_anchor_exemption`.

    When `family` is one of `program_conflicts.ANCHOR_SKILL_CEILING_RULING["exempt_families"]`
    AND `allow_anchor_exemption` is True, THIS resolution uses that ruling's
    `effective_ceiling` instead of `skill_ceiling` (owner ruling 2026-09-23, #4080,
    option B) — every other pattern and every accessory still uses `skill_ceiling` unchanged.
    `allow_anchor_exemption=False` is how a deliberately-lower ceiling (the Minimum Viable
    Session's skill_ceiling=1) opts OUT of the exemption rather than being silently raised.
    """
    if catalog_movements is None:
        return None, "movement catalog not read — the pattern is prescribed, the movement is unresolved"
    ruling = program_conflicts.ANCHOR_SKILL_CEILING_RULING
    exempt = allow_anchor_exemption and family is not None and family in ruling["exempt_families"]
    ceiling = max(int(skill_ceiling), int(ruling["effective_ceiling"])) if exempt else skill_ceiling
    skipped: list[str] = []
    for k in keys:
        m = catalog_movements.get(k)
        if m is None:
            skipped.append(f"{k} (not in catalog)")
            continue
        tier = int(m.get("skill_tier", 99))
        if tier > ceiling:
            skipped.append(f"{k} (skill_tier {tier} > ceiling {ceiling}" + (", anchor-exempt" if exempt else "") + ")")
            continue
        if k in taken:
            skipped.append(f"{k} (already in this session)")
            continue
        return k, ("skipped: " + ", ".join(skipped)) if skipped else None
    return None, "no reachable member: " + ", ".join(skipped)
