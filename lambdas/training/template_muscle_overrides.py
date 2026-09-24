"""template_muscle_overrides.py — id-keyed corrections for a Hevy custom exercise
template whose `primary_muscle_group` is permanently wrong (#3770).

WHY THIS EXISTS

Hevy's write client exposes create + list + get for exercise templates, but no
template PUT (`training/hevy_write_client.py`). Once a custom template is created
with the wrong muscle group, there is no API call that fixes it in place — the
owner's in-app edit on this account never reached the API either (five live GETs
2026-09-1x..20 still read the pre-edit value), so the group is genuinely
permanent on that id.

Template `70b39605-52c0-4b79-855c-e26ea10440da` ("Calf Press on Leg Press
Machine") was auto-created 2026-09-08 by `create_missing`'s pre-#3718
guess-the-muscle-group path with `primary_muscle_group='shoulders'`. Every set
logged against it counted as shoulders volume and zero calves volume in
`get_muscle_volume`. #3718 flipped `create_missing`'s default so a NEW template
can never again ship without an explicit `muscle_group`
(`mcp/tools_hevy_routine.py::_explicit_muscle_group`); this module is the
retroactive half — the owner's 2026-09-20 ruling on #3770 is RETIRE-AND-RECREATE
(`deploy/hevy_recreate_template.py`), not an in-place fix that doesn't exist.

TWO TABLES, TWO JOBS

`TEMPLATE_MUSCLE_OVERRIDES` is read by `training/muscle_volume.attribute_exercise`
(#4071) — the ONE place a Hevy exercise is classified by template id rather than by
name. Every per-muscle reader goes through it: `mcp/strength_helpers.classify_exercise`,
`mcp/tools_strength.py::tool_get_muscle_volume`, and (#4095)
`lambdas/web/site_api_training.py::_compute_muscle_volume`, which used to carry its own
copy of this lookup and now delegates to `attribute_exercise` like everything else. It
makes every set ALREADY logged against the old id count as the corrected muscle group,
forever — nothing here re-tags Hevy, it only corrects how this platform reads Hevy.

`RETIRED_TEMPLATE_IDS` is read by the title resolvers
(`mcp/hevy_resolution.py`, `lambdas/training/hevy_template_index.py`) so that once
a replacement template is created with the SAME title (`deploy/hevy_recreate_template.py`),
name resolution can never route a fresh set back to the retired id even though the
two templates share a title in the live Hevy catalogue.
"""

from __future__ import annotations

#: Hevy template id (lowercased, as the API returns it) -> the corrected muscle-group
#: label, in THIS platform's vocabulary (matches `training/muscle_volume.MUSCLES` /
#: `_VOLUME_LANDMARKS` keys in mcp/strength_helpers.py and the `_LANDMARKS` keys in
#: lambdas/web/site_api_training.py — both use "Calves").
TEMPLATE_MUSCLE_OVERRIDES: dict[str, str] = {
    # 2026-09-08: created by create_missing's pre-#3718 guessed-muscle-group path with
    # primary_muscle_group='shoulders' (live-confirmed 2026-09-13 and again 2026-09-20 —
    # the owner's in-app correction never reached the API). Retired 2026-09-20 in favor
    # of a recreated template (#3770); every set already logged against this id keeps
    # counting as Calves.
    "70b39605-52c0-4b79-855c-e26ea10440da": "Calves",
}

#: Hevy template ids that must never be resolved TO by a title lookup, even when a
#: live/cached template list contains a title-identical match (the recreated template
#: is deliberately titled identically — #3770).
RETIRED_TEMPLATE_IDS: set[str] = {
    "70b39605-52c0-4b79-855c-e26ea10440da",
}


def muscle_override_for(template_id: str | None) -> str | None:
    """The corrected muscle-group label for a Hevy template id, or None (no override)."""
    if not template_id:
        return None
    return TEMPLATE_MUSCLE_OVERRIDES.get(template_id.strip().lower())


def is_retired_template(template_id: str | None) -> bool:
    """True when `template_id` must be excluded from title-resolution results."""
    if not template_id:
        return False
    return template_id.strip().lower() in RETIRED_TEMPLATE_IDS
