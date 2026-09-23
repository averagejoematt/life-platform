"""tests/test_movement_catalog_4108.py — the movement catalog built from the whole Hevy history (#4108).

`config/movement_catalog.json` held 26 hand-curated movements; the owner has logged 537 distinct
exercise identities in Hevy since 2021. `deploy/build_movement_catalog.py` builds the catalog
from that history, enriched from Hevy's template metadata, and commits the output. These tests
hold:

  1. the committed catalog: ≥ 500 entries, the 26 curated entries preserved + `reviewed: true`,
     every entry carrying provenance / sessions / last_done / reviewed, Squat (Barbell) at tier 3;
  2. the ONE muscle table (`muscle_volume.HEVY_MUSCLE_GROUP`) covers Hevy's whole enum and maps
     into both vocabularies it claims;
  3. the rules (`training.movement_catalog`): eligibility (owner ruling C — no frequency gate),
     anchor-family tagging, and every stored value equal to what the rule computes;
  4. the builder, offline: deterministic, preserving, alias-folding, both phases, coach_added;
  5. the consumers: the muscle selector reads the eligibility rule, and the chat resolver's
     loose-contains step still reads only reviewed entries.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import random
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO / "deploy"))
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import build_movement_catalog as bmc  # noqa: E402
from training import (
    movement_catalog as mc,  # noqa: E402
    muscle_volume,  # noqa: E402
)

CATALOG_DOC = json.loads((REPO / "config" / "movement_catalog.json").read_text())
CATALOG = CATALOG_DOC["movements"]
LANDMARK_MUSCLES = set(json.loads((REPO / "config" / "training_landmarks.json").read_text())["muscles"])

#: The 26 movements hand-written on 2026-05-31 (ADR-066) — the curated half.
CURATED_KEYS = {
    "db_bench_press_flat",
    "machine_chest_press",
    "incline_db_press",
    "cable_chest_fly",
    "lat_pulldown",
    "machine_row",
    "one_arm_db_row",
    "machine_shoulder_press",
    "db_lateral_raise",
    "db_curl",
    "cable_tricep_pushdown",
    "leg_press",
    "goblet_squat",
    "leg_curl",
    "machine_hip_thrust",
    "calf_raise_machine",
    "machine_crunch",
    "db_wrist_curl",
    "barbell_bench_press",
    "db_shoulder_press",
    "reverse_pec_deck",
    "cycling",
    "rowing_machine",
    "treadmill",
    "elliptical",
    "air_bike",
}


# ── 1. the committed catalog ─────────────────────────────────────────────────
def test_catalog_carries_the_whole_history():
    prov = CATALOG_DOC["_provenance"]
    assert len(CATALOG) >= 500
    assert prov["entries"] == len(CATALOG)
    assert prov["generated_by"] == "deploy/build_movement_catalog.py"
    assert prov["history_first"] == "2021-04-12"
    assert sum(1 for v in CATALOG.values() if v["provenance"] == mc.PROVENANCE_HISTORY) == prov["generated"]


def test_every_entry_carries_the_acceptance_fields():
    for key, v in CATALOG.items():
        assert v["provenance"] in mc.PROVENANCES, key
        assert isinstance(v["reviewed"], bool), key
        assert isinstance(v["sessions"], int) and v["sessions"] >= 0, key
        assert "last_done" in v and "first_done" in v, key
        assert v.get("skill_tier") in (1, 2, 3), key
        assert isinstance(v.get("joint_friendly_score"), int), key
        assert v.get("hevy_template_id_hint") or v.get("_resolves_by_title"), key
        if v["provenance"] == mc.PROVENANCE_HISTORY:
            assert v["reviewed"] is False and v["sessions"] >= 1 and v["last_done"], key
            assert v["joint_friendly_score"] == bmc.UNREVIEWED_JOINT_FRIENDLY_SCORE, key


def test_the_26_curated_entries_are_kept_and_marked_reviewed():
    assert CURATED_KEYS <= set(CATALOG)
    for k in CURATED_KEYS:
        assert CATALOG[k]["reviewed"] is True and CATALOG[k]["provenance"] == mc.PROVENANCE_CURATED, k
    # their hand-written fields are untouched — a spot check of values the builder could only have changed by mistake
    assert CATALOG["barbell_bench_press"]["skill_tier"] == 3 and CATALOG["barbell_bench_press"]["joint_friendly_score"] == 1
    assert "hevy_template_id_hint" not in CATALOG["barbell_bench_press"]  # ADR-069: resolves by title, on purpose
    assert CATALOG["lat_pulldown"]["skill_tier"] == 1  # curated at 1 although a cable movement generates at 2
    assert CATALOG["cycling"]["_cardio"]
    # and the curated movements come first, in their original order
    assert list(CATALOG)[: len(CURATED_KEYS)] == [k for k in CATALOG if k in CURATED_KEYS]


def test_no_template_id_is_catalogued_twice():
    hints = [str(v["hevy_template_id_hint"]).upper() for v in CATALOG.values() if v.get("hevy_template_id_hint")]
    assert len(hints) == len(set(hints))


def test_a_confirmed_alias_is_folded_not_catalogued():
    aliases = json.loads((REPO / "config" / "hevy_template_aliases.json").read_text())["aliases"]
    hints = {str(v.get("hevy_template_id_hint") or "").upper() for v in CATALOG.values()}
    for alias_tid in aliases:
        assert alias_tid.upper() not in hints


def test_squat_barbell_fixture():
    """The issue's fixture: Squat (Barbell) present at tier 3 with its template id, eligible once the ceiling allows 3."""
    sq = CATALOG["squat_barbell"]
    assert sq["title"] == "Squat (Barbell)"
    assert sq["hevy_template_id_hint"] == "D04AC939"
    assert sq["skill_tier"] == 3 and sq["equipment"] == "barbell"
    assert sq["primary_muscle"] == "quadriceps" and sq["volume_muscle"] == "Quads"
    assert sq["anchor_family"] == "squat"
    assert sq["sessions"] >= 80
    assert mc.generator_eligible(sq, 3) is True
    assert mc.generator_eligible(sq, 2) is False


@pytest.mark.parametrize(
    "key,family,tier",
    [
        ("front_squat", "squat", 3),
        ("zercher_squat", "squat", 3),
        ("deadlift_trap_bar", "hinge", 3),
        ("deadlift_barbell", "hinge", 3),
        ("bent_over_row_barbell", "row", 3),
        ("barbell_bench_press", "bench", 3),
        ("pull_up", "vertical_pull", 1),
    ],
)
def test_the_anchor_lifts_he_has_trained_are_tagged(key, family, tier):
    assert CATALOG[key]["anchor_family"] == family
    assert CATALOG[key]["skill_tier"] == tier


def test_every_stored_anchor_family_is_what_the_rule_computes():
    for key, v in CATALOG.items():
        assert v.get("anchor_family") == mc.anchor_family(v), key


def test_anchor_family_refuses_the_substring_false_friends():
    assert CATALOG["upright_row_barbell"]["anchor_family"] is None  # "row", but a shoulders movement
    jumps = [k for k, v in CATALOG.items() if "squat jump" in v["title"].lower()]
    assert jumps and all(CATALOG[k]["anchor_family"] is None for k in jumps)  # unloaded
    assert CATALOG["rowing_machine"]["anchor_family"] is None  # cardio first


def test_every_generated_skill_tier_follows_the_stated_equipment_rule():
    for key, v in CATALOG.items():
        if v["provenance"] != mc.PROVENANCE_HISTORY:
            continue
        src = v["skill_tier_source"]
        if src.startswith("hevy_equipment:") and src != "hevy_equipment:unknown":
            assert v["skill_tier"] == bmc.EQUIPMENT_SKILL_TIER[src.split(":", 1)[1]], key
        elif src == "title:cable":
            assert v["skill_tier"] == 2 and v["equipment"] == "cable", key
        elif src == "title:smith":
            assert v["skill_tier"] == 3, key
        else:
            assert v["skill_tier"] == bmc.UNKNOWN_EQUIPMENT_TIER, key


def test_every_generated_muscle_is_the_one_tables_mapping():
    for key, v in CATALOG.items():
        if v["provenance"] != mc.PROVENANCE_HISTORY or v.get("hevy_metadata") == "unavailable":
            continue
        volume, planner = muscle_volume.HEVY_MUSCLE_GROUP[v["hevy_primary_muscle_group"]]
        assert v["primary_muscle"] == planner and v["volume_muscle"] == volume, key


# ── 2. the one muscle table ──────────────────────────────────────────────────
def _hevy_muscle_enum() -> set[str]:
    tree = ast.parse((REPO / "mcp" / "tools_hevy_routine.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "_HEVY_MUSCLE_GROUPS" for t in node.targets):
            return set(ast.literal_eval(node.value))
    raise AssertionError("_HEVY_MUSCLE_GROUPS not found")


def test_the_muscle_table_covers_hevys_enum_and_maps_into_both_vocabularies():
    table = muscle_volume.HEVY_MUSCLE_GROUP
    assert set(table) == _hevy_muscle_enum()
    for group, (volume, planner) in table.items():
        assert volume is None or volume in muscle_volume.MUSCLES, group
        assert planner in LANDMARK_MUSCLES | {"cardio", "other"}, group


# ── 3. the rules ─────────────────────────────────────────────────────────────
def test_eligibility_has_no_frequency_gate():
    """Owner ruling C: a movement done once — or never — may be programmed."""
    once = {"skill_tier": 2, "reviewed": False, "sessions": 1, "default_rep_range": {"start": 8, "end": 12}}
    never = {"skill_tier": 1, "reviewed": False, "sessions": 0, "provenance": "coach_added", "default_rep_range": {"start": 10, "end": 15}}
    assert mc.generator_eligible(once, 2) and mc.generator_eligible(never, 1)


def test_eligibility_keeps_the_ceiling_and_the_shape():
    assert not mc.generator_eligible({"skill_tier": 3, "reviewed": True}, 2)  # the ceiling binds reviewed entries too
    plank = {"skill_tier": 1, "reviewed": False, "sessions": 40, "hevy_type": "duration"}
    assert not mc.generator_eligible(plank, 3)  # no rep range to prescribe
    assert mc.generator_eligible({"skill_tier": 1}, 1)  # a pre-#4108 / fixture entry is curated by construction
    assert not mc.generator_eligible({"skill_tier": "x"}, 3)


def test_eligible_counts_reach_the_history():
    eligible_3 = [k for k, v in CATALOG.items() if mc.generator_eligible(v, 3)]
    assert "squat_barbell" in eligible_3 and len(eligible_3) >= 450


# ── 4. the builder, offline ──────────────────────────────────────────────────
def _row(day, wid, exercises, **extra):
    return {"sk": f"DATE#{day}#WORKOUT#{wid}", "exercises": exercises, **extra}


def _ex(tid, name):
    return {"template_id": tid, "name": name, "sets": [{"reps": 5}]}


def test_summarize_history_counts_workouts_both_phases_and_skips_legacy_aggregates():
    rows = [
        _row("2021-04-12", "a", [_ex("D04AC939", "Squat (Barbell)"), _ex("D04AC939", "Squat (Barbell)")], phase="pilot"),
        _row("2026-09-20", "b", [_ex("d04ac939", "Squat (Barbell)")], phase="experiment"),
        {"sk": "DATE#2022-01-01", "exercises": [_ex("D04AC939", "Squat (Barbell)")], "tombstoned_reason": bmc.LEGACY_TOMBSTONE},
        _row("2022-01-02", "c", [_ex("B5EFBF9C", "Overhead Triceps Extension (Cable)"), _ex(None, "Mystery")]),
    ]
    h = bmc.summarize_history(rows, {"B5EFBF9C": "21310F5F"})
    assert h["workouts"] == 3 and h["first"] == "2021-04-12" and h["last"] == "2026-09-20"
    sq = h["templates"]["D04AC939"]
    assert (sq["sessions"], sq["first_done"], sq["last_done"]) == (2, "2021-04-12", "2026-09-20")
    assert "B5EFBF9C" not in h["templates"] and h["templates"]["21310F5F"]["sessions"] == 1
    assert h["untagged_exercises"] == 1


_META = {
    "D04AC939": {
        "id": "D04AC939",
        "title": "Squat (Barbell)",
        "type": "weight_reps",
        "primary_muscle_group": "quadriceps",
        "secondary_muscle_groups": ["glutes", "hamstrings"],
        "equipment": "barbell",
        "is_custom": False,
    },
    "AAAA0001": {
        "id": "AAAA0001",
        "title": "Face Pull (Cable)",
        "type": "weight_reps",
        "primary_muscle_group": "shoulders",
        "secondary_muscle_groups": ["upper_back"],
        "equipment": "machine",
        "is_custom": False,
    },
    "BBBB0002": {
        "id": "BBBB0002",
        "title": "Landmine Press",
        "type": "weight_reps",
        "primary_muscle_group": "shoulders",
        "secondary_muscle_groups": ["triceps"],
        "equipment": "barbell",
        "is_custom": False,
    },
    "CCCC0003": {
        "id": "CCCC0003",
        "title": "Plank",
        "type": "duration",
        "primary_muscle_group": "abdominals",
        "secondary_muscle_groups": [],
        "equipment": "none",
        "is_custom": False,
    },
}
_CURATED = {
    "_version": 1,
    "movements": {
        "leg_press": {"title": "Leg Press (Machine)", "hevy_template_id_hint": "C7973E0E", "primary_muscle": "quadriceps", "skill_tier": 1}
    },
}


def _history(**tids):
    return {
        "workouts": 3,
        "first": "2021-04-12",
        "last": "2026-09-20",
        "templates": {
            t: {"sessions": n, "first_done": "2021-04-12", "last_done": "2026-09-20", "names": {"x": n}} for t, n in tids.items()
        },
    }


def test_build_is_deterministic_and_idempotent():
    hist = _history(D04AC939=85, AAAA0001=3, CCCC0003=9, C7973E0E=5, DEADBEEF=1)
    first = bmc.build_catalog(_CURATED, hist, _META)
    assert json.dumps(first) == json.dumps(bmc.build_catalog(_CURATED, hist, _META))
    # rebuilding from its own output changes nothing — generated entries regenerate, curated ones are kept
    assert json.dumps(bmc.build_catalog(first, hist, _META)) == json.dumps(first)


def test_build_derives_tier_muscles_and_keeps_curated_fields():
    out = bmc.build_catalog(_CURATED, _history(D04AC939=85, AAAA0001=3, CCCC0003=9, C7973E0E=5, DEADBEEF=1), _META)["movements"]
    assert out["leg_press"] == {
        "title": "Leg Press (Machine)",
        "hevy_template_id_hint": "C7973E0E",
        "primary_muscle": "quadriceps",
        "skill_tier": 1,
        "provenance": "hand_curated",
        "reviewed": True,
        "sessions": 5,
        "first_done": "2021-04-12",
        "last_done": "2026-09-20",
        "anchor_family": "squat",
    }
    assert out["squat_barbell"]["skill_tier"] == 3 and out["squat_barbell"]["secondary_muscles"] == ["glutes", "hamstrings"]
    face = out["face_pull_cable"]
    assert (face["skill_tier"], face["equipment"], face["secondary_muscles"]) == (2, "cable", ["back"])
    assert "default_rep_range" not in out["plank"] and not mc.generator_eligible(out["plank"], 3)
    gone = next(v for v in out.values() if v["hevy_template_id_hint"] == "DEADBEEF")
    assert gone["hevy_metadata"] == "unavailable" and gone["skill_tier"] == 3 and not mc.generator_eligible(gone, 3)
    assert list(out)[0] == "leg_press"  # curated first, then sessions desc
    assert list(out)[1] == "squat_barbell"


def test_a_reviewed_generated_entry_is_preserved_verbatim():
    hist = _history(AAAA0001=3)
    first = bmc.build_catalog({"movements": {}}, hist, _META)
    first["movements"]["face_pull_cable"] |= {"reviewed": True, "joint_friendly_score": 3, "notes": "owner reviewed"}
    again = bmc.build_catalog(first, hist, _META)["movements"]["face_pull_cable"]
    assert again["reviewed"] is True and again["joint_friendly_score"] == 3 and again["notes"] == "owner reviewed"


def test_a_coach_added_entry_is_enriched_kept_and_eligible():
    current = {
        "movements": {
            "landmine_press": {
                "title": "Landmine Press",
                "hevy_template_id_hint": "BBBB0002",
                "provenance": "coach_added",
                "joint_friendly_score": 3,
            }
        }
    }
    out = bmc.build_catalog(current, _history(D04AC939=85), _META)["movements"]
    lp = out["landmine_press"]
    assert lp["provenance"] == "coach_added" and lp["reviewed"] is False
    assert lp["joint_friendly_score"] == 3  # a written field is kept
    assert (lp["skill_tier"], lp["primary_muscle"], lp["hevy_type"]) == (3, "shoulders", "weight_reps")  # absent ones enriched
    assert (lp["sessions"], lp["last_done"]) == (0, None)
    assert lp["anchor_family"] is None  # "landmine press" is not an overhead_press hint
    assert mc.generator_eligible(lp, 3) and not mc.generator_eligible(lp, 2)


def test_a_coach_added_entry_claims_its_template_when_it_is_later_trained():
    current = {"movements": {"back_squat": {"title": "Squat (Barbell)", "hevy_template_id_hint": "D04AC939", "provenance": "coach_added"}}}
    out = bmc.build_catalog(current, _history(D04AC939=4), _META)["movements"]
    assert list(out) == ["back_squat"] and out["back_squat"]["sessions"] == 4


def test_a_retired_template_is_never_catalogued():
    retired = "70b39605-52c0-4b79-855c-e26ea10440da".upper()
    out = bmc.build_catalog({"movements": {}}, _history(**{retired: 3}), {})
    assert out["movements"] == {} and out["_provenance"]["excluded_retired_template_ids"] == [retired]


# ── 5. the consumers ─────────────────────────────────────────────────────────
def test_the_muscle_selector_reads_the_eligibility_rule():
    from training import routine_generator as rg

    catalog = {
        "movements": {
            "curated": {"primary_muscle": "abs", "skill_tier": 1, "joint_friendly_score": 3},
            "plank": {"primary_muscle": "abs", "skill_tier": 1, "joint_friendly_score": 3, "reviewed": False, "hevy_type": "duration"},
            "hanging_leg_raise": {
                "primary_muscle": "abs",
                "skill_tier": 1,
                "joint_friendly_score": 1,
                "reviewed": False,
                "default_rep_range": {"start": 10, "end": 15},
            },
        }
    }
    picks = rg._select_movements_for_muscle("abs", 8, catalog, 2, {}, random.Random(0), [])
    assert [k for k, _ in picks] == ["curated", "hanging_leg_raise"]


def test_the_chat_resolvers_loose_step_reads_only_reviewed_entries(monkeypatch):
    import mcp.tools_hevy_routine as thr

    monkeypatch.setattr(thr, "_template_index", lambda *a, **k: {})
    monkeypatch.setattr(thr, "_index_fuzzy", lambda *a, **k: None)
    monkeypatch.setattr(thr, "_live_template_id_by_title", lambda *a, **k: None)
    catalog = {"db_curl": {"title": "Bicep Curl (Dumbbell)"}, "generated": {"title": "Squat Hold", "reviewed": False}}
    assert thr._resolve_movement_key({"title": "Squat"}, catalog, None) is None
    assert thr._resolve_movement_key({"title": "Bicep Curl"}, catalog, None) == "db_curl"
