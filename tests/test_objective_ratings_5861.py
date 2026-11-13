"""#5861 — the exercise library rates five objectives separately, each by its own small categorical rubric, with evidence
confidence beside every tier; the canonical layer consolidates duplicates without breaking a key or a template id.

Held here, each beside a must-fail control that was run:

  * every stored rating is what its rubric derives (a hand-edited rating is a schema error), and each carries its basis;
  * hypertrophy S only when every S criterion holds — a direct trial never lifts a row into S past an unmet criterion;
  * cardio is never rated by the hypertrophy rubric, and every carry / mobility / rehab / athletic / conditioning
    movement is rated on at least one non-hypertrophy objective (never judged on direct stimulus alone);
  * ratings are deterministic and `objective_tier` is the one accessor;
  * every pre-#5861 key and Hevy template id still resolves; an alias carries its canonical's attributes and ratings;
  * every reviewed-layer row is applied (none can vanish silently), and no S/A/B row escapes the reviewed pass;
  * the owner's anomaly table (docs/coaching/EXERCISE_LIBRARY.md) holds;
  * the S census in the library is the census of the library;
  * the L2 additions hook: absent module = no additions, a clashing key is a hard stop, an addition is rated.

Pure: the committed config and a frozen key fixture, no AWS, no network, no clock.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import sys
import types

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO / "deploy"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import exercise_library_objectives as objectives  # noqa: E402
import exercise_library_targets as targets  # noqa: E402
from training import (
    exercise_library as xl,  # noqa: E402
    quality_rubric as qr,  # noqa: E402
)

LIB = json.loads((REPO / "config" / "exercise_library.json").read_text())
MV = LIB["movements"]
PRE = json.loads((REPO / "tests" / "fixtures" / "exercise_library_keys_pre_5861.json").read_text())["keys"]
NOT_GROWTH = ("conditioning", "carry", "mobility", "rehab_control", "athletic")


# ── derivation ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _rating_offenders(movements: dict) -> list[str]:
    return [f"{k}: {why}" for k, e in movements.items() for why in qr.rating_problems(e)]


def test_every_rating_is_what_its_rubric_derives_and_carries_its_basis():
    assert _rating_offenders(MV) == []
    for k, e in MV.items():
        assert set(e["ratings"]) == set(qr.OBJECTIVES), k
        for o, r in e["ratings"].items():
            assert r["basis"], (k, o)
            if r["tier"] is None:
                assert r["evidence_confidence"] is None and "not applicable" in r["basis"][0], (k, o)
            else:
                assert r["tier"] in qr.QUALITY_TIERS and r["evidence_confidence"] in qr.EVIDENCE_CONFIDENCE, (k, o)


def test_control_a_hand_edited_rating_goes_red():
    for k, o in (("farmers_walk", "functional"), ("treadmill", "conditioning"), ("squat_barbell", "strength")):
        bad = copy.deepcopy(LIB)
        bad["movements"][k]["ratings"][o]["tier"] = "D"
        assert any(f"ratings.{o}" in x for x in _rating_offenders({k: bad["movements"][k]})), (k, o)
        assert any(k in err and f"ratings.{o}" in err for err in xl.validate(bad)), (k, o)


def test_ratings_are_deterministic_and_objective_tier_is_the_accessor():
    for k in ("pull_up_weighted", "farmers_walk", "treadmill", "db_cossack_squats", "rotator_cuff_external_rotation"):
        e = MV[k]
        assert qr.objective_ratings(e) == qr.objective_ratings(copy.deepcopy(e)) == e["ratings"]
        for o in qr.OBJECTIVES:
            assert qr.objective_tier(e, o) == e["ratings"][o]["tier"]
            assert qr.objective_tier({k2: v for k2, v in e.items() if k2 != "ratings"}, o) == e["ratings"][o]["tier"]
    assert qr.objective_tier(MV["db_cossack_squats"], "hypertrophy", "adductors") == "A"
    assert qr.objective_tier(MV["db_cossack_squats"], "hypertrophy", "quadriceps") == "B"
    assert qr.objective_tier(MV["overhead_triceps_extension_cable"], "hypertrophy", "triceps") == "S"  # a sub-target counts
    assert qr.objective_tier(MV["treadmill"], "hypertrophy", "quadriceps") is None
    with pytest.raises(ValueError):
        qr.objective_tier(MV["treadmill"], "power")


# ── hypertrophy S needs every S criterion ─────────────────────────────────────────────────────────────────────────────
def _s_offenders(movements: dict) -> list[str]:
    out = []
    for k, e in movements.items():
        for r in e["hypertrophy"]:
            if r["tier"] == "S" and not all(qr.s_criteria(e, r).values()):
                out.append(f"{k}/{r['target']}: S without {[c for c, ok in qr.s_criteria(e, r).items() if not ok]}")
    return out


def test_every_hypertrophy_s_meets_every_s_criterion():
    assert _s_offenders(MV) == []
    assert any(r["tier"] == "S" for e in MV.values() for r in e["hypertrophy"])


def test_control_an_unmet_s_criterion_or_a_trial_cannot_buy_s():
    e = copy.deepcopy(MV["hack_squat_machine"])
    row = e["hypertrophy"][0]
    assert qr.quality_tier(e, row) == "S"
    e["objective_inputs"]["limiter"] = "balance"
    assert qr.quality_tier(e, row) == "B", "a limiter that is not the target caps at B"
    e["objective_inputs"] |= {"limiter": "target", "systemic_fatigue": "high"}
    assert qr.quality_tier(e, row) == "A", "poor stimulus-to-fatigue caps at A"
    # a +1 direct trial on an A row whose S criteria fail stays A (the barbell standing calf raise: stability low)
    calf = MV["standing_calf_raise_barbell"]
    adj = next(r for r in calf["hypertrophy"] if r.get("evidence_adjustment"))
    assert adj["evidence_adjustment"]["bands"] == 1 and adj["tier"] == "A" and not all(qr.s_criteria(calf, adj).values())
    # the guard itself: plant an S on a row that fails a criterion -> named
    bad = copy.deepcopy(MV)
    bad["db_cossack_squats"]["hypertrophy"][0]["tier"] = "S"
    assert any(o.startswith("db_cossack_squats/") for o in _s_offenders(bad))


# ── never the wrong rubric ────────────────────────────────────────────────────────────────────────────────────────────
def _wrong_rubric(movements: dict) -> list[str]:
    out = []
    for k, e in movements.items():
        r = e["ratings"]
        if e["category"] == "conditioning" and (r["hypertrophy"]["tier"] is not None or r["conditioning"]["tier"] is None):
            out.append(f"{k}: cardio rated on hypertrophy, or not on conditioning")
        if e["category"] in NOT_GROWTH and r["hypertrophy"]["tier"] is not None:
            out.append(f"{k}: a {e['category']} movement judged on direct stimulus")
        if e["category"] in NOT_GROWTH and all(r[o]["tier"] is None for o in qr.OBJECTIVES if o != "hypertrophy"):
            out.append(f"{k}: a {e['category']} movement rated on no objective")
    return out


def test_cardio_is_rated_on_conditioning_and_never_on_hypertrophy():
    assert _wrong_rubric(MV) == []
    cardio = [k for k, e in MV.items() if e["category"] == "conditioning"]
    assert len(cardio) >= 8 and all(MV[k]["ratings"]["conditioning"]["tier"] in qr.QUALITY_TIERS for k in cardio)
    assert "D" not in {MV[k]["ratings"]["conditioning"]["tier"] for k in cardio}, "no modality is globally penalised"


def test_control_cardio_pushed_through_hypertrophy_or_a_carry_left_unrated_goes_red():
    bad = copy.deepcopy(MV)
    bad["treadmill"]["category"] = "hypertrophy"
    bad["treadmill"]["target"]["primary"] = "quadriceps"
    bad["treadmill"]["hypertrophy"][0]["target"] = "quadriceps"
    bad["treadmill"]["ratings"] = qr.objective_ratings(bad["treadmill"])
    bad["treadmill"]["category"] = "conditioning"  # the movement still says cardio; the rating went through growth
    assert any(o.startswith("treadmill:") for o in _wrong_rubric({"treadmill": bad["treadmill"]}))
    bad["bird_dog"]["objective_inputs"] |= {"functional": [], "mobility": None}  # a rehab drill stripped of its objectives
    bad["bird_dog"]["ratings"] = qr.objective_ratings(bad["bird_dog"])
    assert any("rated on no objective" in o for o in _wrong_rubric({"bird_dog": bad["bird_dog"]}))


# ── the canonical layer ───────────────────────────────────────────────────────────────────────────────────────────────
def _id_offenders(lib: dict) -> list[str]:
    out = []
    for key, tid in PRE.items():
        e = lib["movements"].get(key)
        if e is None:
            out.append(f"{key}: key gone")
            continue
        if e.get("template_id") != tid:
            out.append(f"{key}: template id {e.get('template_id')} != {tid}")
        head = xl.canonical_of(lib, key)
        if head not in lib["movements"] or (tid and xl.canonical_of(lib, tid) != head):
            out.append(f"{key}: does not resolve")
    return out


def test_every_pre_5861_key_and_template_id_still_resolves():
    assert len(PRE) == 578
    assert _id_offenders(LIB) == []
    fams = LIB["canonical_families"]
    assert LIB["_provenance"]["canonical"] == {
        "families": len(fams),
        "aliases": sum(len(f["aliases"]) for f in fams.values()),
        "variants": sum(len(f["variants"]) for f in fams.values()),
    }
    # the audit's seven duplicate pairs and three hash-suffixed keys each resolve to one canonical
    for alias, head in {
        "tricep_pushaways": "tricep_pushaway",
        "tricep_pushdown": "triceps_pushdown",
        "glute_machine_kickback": "glute_kickback_machine",
        "farmers_walk_8d414b80": "farmers_walk",
        "reverse_lunge_dumbbell": "db_reverse_lunge",
        "db_incline_power_bombs": "db_power_incline_bombs",
        "high_knee_flying_20s_2476151f": "high_knee_flying_20s",
        "pallof_press_cc55119b": "cable_pallof_press",
    }.items():
        assert xl.canonical_of(LIB, alias) == head and MV[alias]["variant"] == {"duplicate_of": head}, alias
    assert {xl.canonical_of(LIB, k) for k in fams["lat_pulldown_cable"]["variants"]} == {"lat_pulldown_cable"}


def test_control_a_dropped_key_or_a_rewritten_template_id_goes_red():
    bad = copy.deepcopy(LIB)
    del bad["movements"]["farmers_walk_8d414b80"]
    bad["movements"]["tricep_pushdown"]["template_id"] = "FFFFFFFF"
    off = _id_offenders(bad)
    assert any(o.startswith("farmers_walk_8d414b80: key gone") for o in off)
    assert any(o.startswith("tricep_pushdown: template id") for o in off)


def test_an_alias_never_scores_differently_from_its_canonical():
    for head, fam in LIB["canonical_families"].items():
        for a in fam["aliases"]:
            # the same tier and confidence on every objective; a basis may cite the alias's own template's N=1 count
            assert {o: (r["tier"], r["evidence_confidence"]) for o, r in MV[a]["ratings"].items()} == {
                o: (r["tier"], r["evidence_confidence"]) for o, r in MV[head]["ratings"].items()
            }, a
            assert [r["tier"] for r in MV[a]["hypertrophy"]] == [r["tier"] for r in MV[head]["hypertrophy"]], a
    # control: an alias carrying different attributes is a schema error
    bad = copy.deepcopy(LIB)
    bad["movements"]["farmers_walk_8d414b80"]["stability"] = "high"
    assert any("farmers_walk_8d414b80" in err and "alias" in err for err in xl.validate(bad))


# ── the reviewed layer cannot vanish ──────────────────────────────────────────────────────────────────────────────────
PINNED = {
    "PATTERN_OVERRIDES": 14,
    "STRENGTH_LIFTS": 9,
    "CATEGORY_OVERRIDES": 12,
    "INPUT_OVERRIDES": 11,
    "SECONDARY_ROWS": 6,
    "CANONICAL_FAMILIES": 44,
}


def _layer_offenders(movements: dict) -> list[str]:
    out = []
    for k, (pattern, job, _why) in targets.PATTERN_OVERRIDES.items():
        if (movements[k]["pattern"], movements[k]["job"]) != (pattern, job):
            out.append(f"{k}: pattern override not applied")
    for k, (cat, _why) in targets.CATEGORY_OVERRIDES.items():
        if movements[k]["category"] != cat:
            out.append(f"{k}: category override not applied")
    for k in targets.STRENGTH_LIFTS:
        if not movements[k]["objective_inputs"]["strength_lift"]:
            out.append(f"{k}: strength lift not recorded")
    for k, (vals, _why) in targets.INPUT_OVERRIDES.items():
        inp = movements[k]["objective_inputs"]
        if any(inp.get(f) != v for f, v in vals.items()) or not inp["reviewed"]:
            out.append(f"{k}: input override not applied")
    for k, rows in targets.SECONDARY_ROWS.items():
        have = {r["target"]: r for r in movements[k]["hypertrophy"]}
        if any(t not in have or have[t].get("limiter") != lim for t, lim, _why in rows):
            out.append(f"{k}: secondary row missing")
    for head, (aliases, variants) in targets.CANONICAL_FAMILIES.items():
        for k in (head, *aliases, *variants):
            if movements[k]["canonical"] != head:
                out.append(f"{k}: canonical not {head}")
    return out


def test_every_reviewed_row_is_applied_and_the_tables_are_pinned():
    assert _layer_offenders(MV) == []
    assert {t: len(getattr(targets, t)) for t in PINNED} == PINNED, "a reviewed row was added or removed: review it, move the pin"


def test_control_a_reverted_override_or_a_missing_movement_goes_red(monkeypatch):
    bad = copy.deepcopy(MV)
    bad["crossover_stepup"]["pattern"] = "chest_fly"
    bad["ab_wheel"]["objective_inputs"]["ladder"] = False
    off = _layer_offenders(bad)
    assert any(o.startswith("crossover_stepup") for o in off) and any(o.startswith("ab_wheel") for o in off)
    monkeypatch.setitem(targets.INPUT_OVERRIDES, "no_such_movement", ({"ladder": True}, "x"))
    with pytest.raises(SystemExit):
        objectives.apply(copy.deepcopy(MV), lambda t: {"target": t, "evidence_confidence": "none_reviewed"})


def _unreviewed(movements: dict) -> list[str]:
    return sorted(
        k
        for k, e in movements.items()
        if not e["objective_inputs"]["reviewed"]
        and (
            any(t in ("S", "A", "B") for t in e["ratings"]["hypertrophy"]["by_target"].values())
            or any(e["ratings"][o]["tier"] in ("S", "A") for o in ("strength", "functional", "conditioning", "mobility"))
        )
    )


def test_no_top_band_rating_escapes_the_reviewed_pass():
    assert _unreviewed(MV) == []
    bad = copy.deepcopy(MV)
    bad["hack_squat_machine"]["objective_inputs"]["reviewed"] = False
    assert _unreviewed(bad) == ["hack_squat_machine"]


# ── the owner's anomalies (docs/coaching/EXERCISE_LIBRARY.md table) ───────────────────────────────────────────────────
ANOMALIES = {  # key: (hypertrophy, strength, functional, conditioning, mobility)
    "push_up_weighted": ("A", "B", None, None, None),
    "pull_up": ("A", "A", None, None, None),
    "pull_up_weighted": ("S", "S", None, None, None),
    "pull_up_assisted": ("A", "B", None, None, None),
    "lat_pulldown_cable": ("S", "B", None, None, None),
    "lateral_raise_dumbbell": ("B", None, None, None, None),
    "step_up": ("C", "C", "B", None, None),
    "db_step_up": ("B", "B", "A", None, None),
    "walking_lunge_dumbbell": ("B", "B", "S", None, None),
    "farmers_walk": (None, "B", "S", "C", None),
    "farmers_walk_8d414b80": (None, "B", "S", "C", None),
    "sled_push": (None, "A", "A", "B", None),
    "sled_drag": (None, "A", "A", "B", None),
    "ab_wheel": ("A", None, "B", None, None),
    "bird_dog": (None, None, "C", None, "B"),
    "side_plank": (None, None, "B", None, None),
    # #5861 L6: cuff rotation is loaded joint-capacity work (FUNCTIONAL_QUALITIES `joint_capacity`) — functional B, never S
    "rotator_cuff_external_rotation": (None, None, "B", None, "A"),
    "db_cossack_squats": ("B", "B", "A", None, "A"),
    "offset_lunges": ("B", "B", "S", None, None),
    "3_way_lunge": ("B", "B", "A", None, None),
    "treadmill": (None, None, None, "S", None),
    "walking": (None, None, None, "C", None),  # lane L4's cardio model owns the rating: hard to dose and progress
    "rowing_machine": (None, None, None, "A", None),
    "hip_thrust_machine": ("S", None, None, None, None),
    "hip_thrust_barbell": ("A", None, None, None, None),
    "squat_barbell": ("A", "S", "B", None, None),
    "rear_delt_reverse_fly_machine": ("S", None, None, None, None),
    "rear_delt_reverse_fly_cable": ("A", None, None, None, None),
    "face_pull": ("B", None, None, None, "A"),
}


def test_the_owners_anomalies_land_where_the_framework_puts_them():
    got = {k: tuple(MV[k]["ratings"][o]["tier"] for o in qr.OBJECTIVES) for k in ANOMALIES}
    assert got == ANOMALIES
    assert MV["db_cossack_squats"]["ratings"]["hypertrophy"]["by_target"] == {"quadriceps": "B", "adductors": "A"}
    # traditional squats, leg press and split squats sit above the unusual lunges for the quads
    quad = {
        k: qr.objective_tier(MV[k], "hypertrophy", "quadriceps")
        for k in ("leg_press_machine", "split_squat_dumbbell", "db_alt_side_lunges")
    }
    assert quad == {"leg_press_machine": "A", "split_squat_dumbbell": "A", "db_alt_side_lunges": "B"}


# ── the census and the hook ───────────────────────────────────────────────────────────────────────────────────────────
def test_the_s_census_is_the_census_of_the_library():
    census = LIB["_provenance"]["s_census"]
    assert census == qr.s_census(MV)
    assert set(census) == set(qr.OBJECTIVES) and census["mobility"] == {}, "no public mobility S (needs a recorded limitation)"
    for obj, muscles in census.items():
        for m, cell in muscles.items():
            assert cell["s"] == len(cell["movements"]) and 1 <= cell["families"] <= cell["s"], (obj, m)


def test_the_additions_hook(monkeypatch):
    import build_exercise_library as b

    monkeypatch.delitem(sys.modules, b.ADDITIONS_MODULE, raising=False)
    monkeypatch.setattr("importlib.util.find_spec", lambda name, *a: None)
    assert b.library_additions() == []
    monkeypatch.undo()
    mod = types.ModuleType(b.ADDITIONS_MODULE)
    mod.ADDITIONS = [{"key": "kettlebell_swing", "title": "x", "template_id": None, "template_note": "x"}]
    monkeypatch.setitem(sys.modules, b.ADDITIONS_MODULE, mod)
    monkeypatch.setattr("importlib.util.find_spec", lambda name, *a: object())
    with pytest.raises(SystemExit):
        b.library_additions()
    mod.ADDITIONS = [{"key": "synthetic_cable_hip_adduction", "title": "Hip Adduction (Cable)", "template_id": None}]
    assert [x["key"] for x in b.library_additions()] == ["synthetic_cable_hip_adduction"]


def test_an_addition_with_authored_inputs_is_rated_and_counts_as_reviewed():
    e = {
        "title": "Synthetic Standing Cable Adduction",
        "source": "expansion",
        "target": {"primary": "adductors", "secondary": [], "region": "lower"},
        "family": "hypertrophy",
        "job": "isolation",
        "pattern": "other",
        "length_bias": "lengthened",
        "resistance_profile": "cable",
        "stability": "moderate",
        "skill_complexity": "low",
        "joint_stress": dict.fromkeys(("spinal_load", "shear", "wrist", "elbow", "shoulder"), "low"),
        "equipment": ["cable_stack"],
        "hypertrophy": [{"target": "adductors", "evidence_confidence": "none_reviewed", "citations": [], "last_reviewed": "unreviewed"}],
        "objective_inputs": {"ceiling": "high", "limiter": "target", "functional": ["unilateral", "balance"]},
    }
    objectives.evaluate_entry("synthetic_cable_adduction", e, lambda t: {"target": t})
    assert e["objective_inputs"]["reviewed"] is True and e["objective_inputs"]["ceiling"] == "high"
    r = qr.objective_ratings(e)
    assert r["hypertrophy"]["tier"] in qr.QUALITY_TIERS and r["functional"]["tier"] == "A"


def test_conditioning_has_one_rule_per_movement_and_cardio_is_the_cardio_models():
    """Lane L4 owns cardio: wherever `cardio_model.conditioning_rating` rates a movement, the library's rating IS it."""
    from training import cardio_model as cm

    off = []
    for k, e in MV.items():
        r = cm.conditioning_rating(e, e.get("canonical"))
        if r is not None and (e["ratings"]["conditioning"]["tier"], e["ratings"]["conditioning"]["evidence_confidence"]) != (
            r["tier"],
            r["evidence_confidence"],
        ):
            off.append(k)
    assert off == [] and MV["walking"]["ratings"]["conditioning"]["basis"][0].startswith("cardio_model")
    # control: the library's own fallback table applied to a cardio row disagrees (walking: A there, C in the model)
    alt = copy.deepcopy(MV["walking"])
    alt["title"], alt["category"], alt["target"]["primary"], alt["canonical"] = "Walking", "carry", "full_body", "x"
    assert qr.conditioning_rating(alt)[0] == "A" != MV["walking"]["ratings"]["conditioning"]["tier"]


def test_the_walking_lunge_is_not_cardio_but_walking_is():
    import build_exercise_library as b

    assert not b._is_cardio("Walking Lunge (Dumbbell)") and not b._is_cardio("Farmers Walk")
    assert b._is_cardio("Walking") and b._is_cardio("Treadmill")
    assert MV["walking_lunge_dumbbell"]["family"] == "hypertrophy" and MV["walking"]["category"] == "conditioning"
