"""movement_catalog_additions.py — library movements the generator could not WRITE, added to the movement catalog on purpose
(`coach_added`, epic #5861 L6). Read by `deploy/build_movement_catalog.py` (`with_coach_additions`); never by a Lambda.

WHY. The selection engine serves only what the movement catalog can write (`selection_engine._not_prescribable`: "no
movement-catalog entry (the generator cannot write it)"). The library expansion (#5861 L2) and the earlier expansion
candidates rated these movements — several of them the best for their muscle or the only loadable movement for their
function — but none had a catalog entry, so each was excluded from every slot. The sample weeks showed the cost: a crunch
slot served a torso-rotation machine because the cable crunch could not be written; hip abduction and adduction had no
loadable movement at all.

WHAT QUALIFIES. A library movement with a Hevy BUILT-IN template (its metadata is in Hevy's index, so the builder fills
every field from it), rated on at least one objective, not `not_for_you_now`, and serving a function or a slot the program
uses. A movement that needs a custom Hevy template is NOT here (template creation is owner-gated — L2's approval list).

WHAT AN ENTRY CHANGES. Nothing on today's drafts: the program's templates name their own movements, the #5075 pools are a
named list, and the selection that could serve these runs live only once the owner approves the library (the no-live-change
proof, tests/test_no_live_change_5861_l6.py, holds the proposed drafts byte-identical). Equipment the home_gym state calls
`unknown` (the abduction/adduction machines, belt and pendulum squat, sled, pullover machine, incline chest press machine)
still keeps the movement out until the owner confirms it.

Each entry: the catalog key (= the library key), Hevy's title, the template id, the reason. Every other field comes from
Hevy's template metadata in the builder (`enrichment`), exactly like any coach_added entry.
"""

from __future__ import annotations

from typing import Any

ISSUE = "#5861"
_WHY_P0 = "the only loadable movement for its function (#5861 L2 P0)"

ADDITIONS: tuple[tuple[str, str, str, str], ...] = (
    ("hip_abduction_machine", "Hip Abduction (Machine)", "F4B4C6EE", _WHY_P0 + ": glute med/min, lateral hip strength"),
    ("hip_adduction_machine", "Hip Adduction (Machine)", "8BEBFED6", _WHY_P0 + ": the adductors, large and nearly unserved"),
    (
        "chest_supported_y_raise_dumbbell",
        "Chest Supported Y Raise (Dumbbell)",
        "F21D5693",
        "the only lower-trap upward-rotation movement (L2 P1)",
    ),
    ("cable_crunch", "Cable Crunch", "23A48484", "loaded spinal flexion — the crunch slot served a rotation machine without it"),
    ("reverse_crunch", "Reverse Crunch", "7952B5CD", "loaded flexion from the pelvis (L2 P2), a bodyweight crunch option"),
    ("sled_drag", "Sled Pull", "7D1BD41D", "loaded locomotion (Hevy's Sled Pull); home_gym sled state unknown until confirmed"),
    ("sled_push", "Sled Push", "AC0A1BF3", "loaded locomotion, knee-dominant; home_gym sled state unknown until confirmed"),
    (
        "lateral_raise_cable_single_arm",
        "Single Arm Lateral Raise (Cable)",
        "DE68C825",
        "the side delts' best-rated raise (long-length loading)",
    ),
    ("low_cable_fly", "Low Cable Fly Crossovers", "293483AD", "a top-rated chest adduction movement"),
    ("behind_the_back_curl_cable", "Behind the Back Curl (Cable)", "2DBCA395", "a top-rated lengthened biceps curl"),
    ("overhead_curl_cable", "Overhead Curl (Cable)", "582ADA23", "a lengthened biceps curl option"),
    ("single_leg_extension", "Single Leg Extensions", "629AE73D", "a top-rated quadriceps isolation, one leg at a time"),
    ("single_leg_standing_calf_raise_machine", "Single Leg Standing Calf Raise (Machine)", "B05C2C29", "a top-rated calf raise"),
    ("split_squat_dumbbell", "Split Squat (Dumbbell)", "20C1A3CB", "the basic loaded split squat: single-leg strength"),
    ("single_leg_press", "Single Leg Press (Machine)", "3FD83744", "single-leg quadriceps work at a low balance cost"),
    ("belt_squat", "Belt Squat (Machine)", "3D1CDC75", "a top-rated squat with no spinal load; equipment state unknown"),
    ("pendulum_squat", "Pendulum Squat (Machine)", "30E293E3", "a top-rated machine squat; equipment state unknown"),
    ("chin_up", "Chin Up", "29083183", "the bodyweight vertical pull (gated by the library's bodyweight gate)"),
    ("pull_up_negative", "Negative Pull Up", "F60BDDF8", "the eccentric rung of the pull-up ladder (gated)"),
    ("chest_supported_t_bar_row", "Chest Supported T Bar Row", "6A8D3193", "a loadable row with no spinal load"),
    ("pullover_machine", "Pullover (Machine)", "B123DD01", "a top-rated lat isolation; equipment state unknown"),
    ("incline_chest_press_machine", "Incline Chest Press (Machine)", "FBF92739", "a stable incline press; equipment state unknown"),
    ("wrist_extension_dumbbell", "Reverse Wrist Curl (Dumbbell)", "D8460FA6", "wrist extension had no movement (L2 P2, optional)"),
    ("lateral_band_walks", "Banded Lateral Steps", "EC02979E", "hip abduction in a closed chain (L2 P3), warm-up work"),
)
"""(catalog key, title, Hevy built-in template id, why). Keys equal the library's, so the selection joins them directly."""


def stubs() -> dict[str, dict[str, Any]]:
    """The coach_added stubs the catalog builder merges (`build_movement_catalog.with_coach_additions`)."""
    return {
        key: {
            "title": title,
            "hevy_template_id_hint": tid,
            "provenance": "coach_added",
            "notes": f"coach_added {ISSUE} L6: {why}; template id from Hevy's built-in index",
        }
        for key, title, tid, why in ADDITIONS
    }
