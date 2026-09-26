"""tests/test_accessory_pool_logged_templates_4169.py — the accessory pool resolves to
machines the owner actually trains (#4169).

WHY

`config/movement_catalog.json`'s v0.4 accessory pool (`training.program_structure.ACCESSORY_POOL`
/ `SESSION_TEMPLATES`, and v0.3's `program_v03` twins over the SAME catalog keys) named two
machines the owner had never logged: `leg_curl` hinted `B8127AD1` (Lying Leg Curl) while he
trains Seated Leg Curl (`11A123F3`); `calf_raise_machine` hinted `E05C2C38` (Standing Calf
Raise) while he trains Calf Press (`91237BDD`). Because `training.hevy_template_cache.
resolve_movement` and `mcp.tools_hevy_routine._make_resolver` resolve a pool key straight to
its catalog hint, the drafted routine named a machine with zero logged history under that id,
`accessory_strength_trend` (#4112) could never populate for it, and `days_since_movement` read
null for a lift the owner did days earlier.

This module holds the guard: every accessory-pool key resolves to a template the owner's own
history (a checked-in fixture of the measured ids, read 2026-09-26 via the deployed MCP
`get_exercise_history` — never a live call from a test) shows he actually logs, whenever the
fixture has an opinion at all. It also proves the guard WOULD have caught the original bug
(the mutation control: revert the fix and watch it red) and confirms `machine_crunch` is
correctly left alone: the owner ruled 2026-09-25 to keep it as a novel (never-trained) lift
rather than swap it for a logged core movement, so this test asserts the fix does not
silently override that ruling — never a live call, and no same-pattern alternative in the
fixture either way.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import program_structure, program_v03  # noqa: E402

CATALOG = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]

#: Checked-in fixture of the owner's MEASURED logged template ids (issue #4169's own table,
#: read 2026-09-26 via the deployed MCP `get_exercise_history` — offline here, never a live
#: call). Each entry names the pool key it is the live substitute for. An id absent from this
#: fixture makes NO claim either way — the fixture only asserts what it has actually measured.
FIXTURE_LOGGED_TEMPLATE_IDS: dict[str, dict[str, object]] = {
    "11A123F3": {"title": "Seated Leg Curl (Machine)", "sessions": 4, "replaces_pool_key": "leg_curl"},
    "91237BDD": {"title": "Calf Press (Machine)", "sessions": 6, "replaces_pool_key": "calf_raise_machine"},
}

#: The pre-#4169 hints, for the mutation control — proves the guard fires on the ORIGINAL bug.
PRE_4169_HINTS: dict[str, str] = {
    "leg_curl": "B8127AD1",  # Lying Leg Curl (Machine) — 0 sessions in the fixture
    "calf_raise_machine": "E05C2C38",  # Standing Calf Raise (Machine) — 0 sessions in the fixture
}


def _pool_keys() -> set[str]:
    """Every movement key any accessory pool (v0.3 or v0.4) can name."""
    keys: set[str] = set()
    for pool in program_structure.ACCESSORY_POOL.values():
        keys.update(pool)
    for tmpl in program_structure.SESSION_TEMPLATES.values():
        keys.update(tmpl.get("accessories") or [])
    for pool in program_v03.ACCESSORY_POOL.values():
        keys.update(pool)
    for tmpl in program_v03.SESSION_TEMPLATES.values():
        keys.update(tmpl.get("accessories") or [])
    return keys


def _dead_pool_keys(pool_keys: set[str], catalog: dict[str, dict], fixture: dict[str, dict]) -> list[tuple[str, str, str]]:
    """Pool keys whose catalog hint has NO fixture entry while a same-pattern id DOES.

    Returns (pool_key, dead_hint, alt_hint) triples, naming both templates, per the issue's
    acceptance criterion.
    """
    dead = []
    for key in sorted(pool_keys):
        entry = catalog.get(key)
        if not entry:
            continue
        hint = str(entry.get("hevy_template_id_hint") or "").upper()
        if not hint or hint in fixture:
            continue  # resolves to a template the fixture confirms is logged, or unknown to it
        alt = [tid for tid, rec in fixture.items() if rec.get("replaces_pool_key") == key]
        if alt:
            dead.append((key, hint, alt[0]))
    return dead


def test_fixture_ids_are_the_measured_ones_the_issue_names():
    """The fixture must be the wire (#4169): its ids are exactly the ones read live 2026-09-26,
    not stand-ins — a mismatch here would make every other assertion in this file meaningless."""
    assert FIXTURE_LOGGED_TEMPLATE_IDS["11A123F3"]["title"] == "Seated Leg Curl (Machine)"
    assert FIXTURE_LOGGED_TEMPLATE_IDS["91237BDD"]["title"] == "Calf Press (Machine)"
    assert FIXTURE_LOGGED_TEMPLATE_IDS["11A123F3"]["sessions"] >= 3
    assert FIXTURE_LOGGED_TEMPLATE_IDS["91237BDD"]["sessions"] >= 3


def test_no_accessory_pool_key_resolves_to_a_dead_template():
    """The live guard: today's committed catalog names zero dead pool keys."""
    dead = _dead_pool_keys(_pool_keys(), CATALOG, FIXTURE_LOGGED_TEMPLATE_IDS)
    assert dead == [], f"accessory pool key(s) resolve to an unlogged template while a logged alternative exists: {dead}"


def test_leg_curl_and_calf_raise_machine_resolve_to_the_logged_templates():
    """The two known remaps (#4169's own acceptance): leg_curl -> 11A123F3, calf_raise_machine -> 91237BDD."""
    assert CATALOG["leg_curl"]["hevy_template_id_hint"] == "11A123F3"
    assert CATALOG["leg_curl"]["title"] == "Seated Leg Curl (Machine)"
    assert CATALOG["calf_raise_machine"]["hevy_template_id_hint"] == "91237BDD"
    assert CATALOG["calf_raise_machine"]["title"] == "Calf Press (Machine)"


def test_the_prior_templates_are_preserved_not_deleted():
    """The old ids are still real logged history — demoted to unclaimed catalog entries, never dropped."""
    assert CATALOG["lying_leg_curl_machine"]["hevy_template_id_hint"] == "B8127AD1"
    assert CATALOG["lying_leg_curl_machine"]["sessions"] == 12
    assert CATALOG["standing_calf_raise_machine"]["hevy_template_id_hint"] == "E05C2C38"
    assert CATALOG["standing_calf_raise_machine"]["sessions"] == 38


def test_no_template_id_is_catalogued_twice_after_the_remap():
    """The remap must not create a second catalog key pointing at the same Hevy template
    (`tests/test_movement_catalog_4108.py` holds this for the whole file; re-asserted here
    because a remap is exactly the shape of change that could reintroduce a duplicate)."""
    hints = [str(v["hevy_template_id_hint"]).upper() for v in CATALOG.values() if v.get("hevy_template_id_hint")]
    assert len(hints) == len(set(hints))


def test_mutation_control_the_pre_4169_hints_would_have_reddened():
    """Revert leg_curl / calf_raise_machine to their pre-fix hints and confirm the SAME guard
    catches the original bug — proof the guard is not vacuously green."""
    mutated = copy.deepcopy(CATALOG)
    for key, old_hint in PRE_4169_HINTS.items():
        mutated[key]["hevy_template_id_hint"] = old_hint
    dead = _dead_pool_keys(_pool_keys(), mutated, FIXTURE_LOGGED_TEMPLATE_IDS)
    dead_keys = {d[0] for d in dead}
    assert dead_keys == set(PRE_4169_HINTS), f"mutation control did not reproduce the original bug: {dead}"
    # and it names both templates, not just the dead key
    for pool_key, dead_hint, alt_hint in dead:
        assert dead_hint == PRE_4169_HINTS[pool_key]
        assert alt_hint in FIXTURE_LOGGED_TEMPLATE_IDS


def test_machine_crunch_stays_a_novel_lift_per_the_owner_ruling():
    """`machine_crunch` (EB43ADD4, never logged) has no same-pattern id in the fixture, and the
    owner ruled 2026-09-25 to keep it as a novel lift rather than swap it (PR body). It must
    NOT be silently swapped by this fix, and it must NOT trip the dead-template guard (no
    fixture entry claims to replace it) — a never-trained lift is a stated, capped case
    (`coach.critics_fatigue.STALE_CAPS["long"]`, #4161), not a defect."""
    assert CATALOG["machine_crunch"]["hevy_template_id_hint"] == "EB43ADD4"
    assert CATALOG["machine_crunch"]["sessions"] == 0
    assert not any(rec.get("replaces_pool_key") == "machine_crunch" for rec in FIXTURE_LOGGED_TEMPLATE_IDS.values())
    dead = _dead_pool_keys(_pool_keys(), CATALOG, FIXTURE_LOGGED_TEMPLATE_IDS)
    assert not any(d[0] == "machine_crunch" for d in dead)
