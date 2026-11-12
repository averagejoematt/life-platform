"""#5857 — the exercise library's tiers grade QUALITY, not evidence: an S-D ladder derived by a written rubric
(`training.quality_rubric`) from the attributes the library records, with evidence confidence as its own field.

Held here, each beside a must-fail control:

  * every row's `tier` / `rubric_tier` / `rubric_score` is what the rubric derives, plus at most one recorded band of
    direct-trial evidence — a hand-edited tier is red (and `exercise_library.validate` refuses it);
  * an evidence adjustment is only rct_direct, only +/-1, citing one of the row's own citations, with a why;
  * the derivation is deterministic: the builder twice over the same inputs writes the same library, and re-deriving the
    committed file changes nothing;
  * bands, not a single winner: every major muscle holds >= 2 selectable movements in S, or names why not
    (`quality_rubric.TOP_BAND_SHORTFALL`), and no stale shortfall entry survives;
  * the library carries the rubric it was derived with (`quality_rubric` header block) and the doc names its version.

Pure: the committed config, no AWS, no network, no clock.
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
sys.path.insert(0, str(REPO / "deploy"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import (
    exercise_library as xl,  # noqa: E402
    quality_rubric as qr,  # noqa: E402
)

LIB = json.loads((REPO / "config" / "exercise_library.json").read_text())
MV = LIB["movements"]
DOC = (REPO / "docs" / "coaching" / "EXERCISE_LIBRARY.md").read_text()
SELECTABLE_EXCLUDED = ("skill_athletic", "strength_anchor")  # `selection_engine.EXCLUDED_FAMILIES`
MAJOR_MUSCLES = {
    "chest": ("chest",),
    "back": ("back",),
    "side_delts": ("side_delts",),  # #5857 target audit: the shoulder split into its three heads
    "rear_delts": ("rear_delts",),
    "front_delts": ("front_delts",),
    "biceps": ("biceps",),
    "triceps": ("triceps",),
    "quadriceps": ("quadriceps",),
    "hamstrings": ("hamstrings",),
    "glutes": ("glutes",),
    "calves": ("calves", "gastrocnemius", "soleus"),
    "abs": ("abs",),
}


def _derivation_offenders(lib: dict) -> list[str]:
    return [
        f"{k}/{r.get('target')}: {why}"
        for k, e in lib["movements"].items()
        for r in e["hypertrophy"]
        for why in qr.derivation_problems(e, r)
    ]


def _top_band(lib: dict, targets: tuple[str, ...]) -> list[str]:
    out = []
    for k, e in lib["movements"].items():
        if e["family"] in SELECTABLE_EXCLUDED or e["target"]["primary"] not in targets:
            continue
        if any(r["tier"] == "S" for r in e["hypertrophy"] if r["target"].startswith(targets)):
            out.append(k)
    return out


def test_every_tier_is_the_rubric_plus_at_most_one_recorded_band():
    assert _derivation_offenders(LIB) == []
    assert {r["tier"] for e in MV.values() for r in e["hypertrophy"]} <= set(qr.QUALITY_TIERS)
    moved = [(k, r) for k, e in MV.items() for r in e["hypertrophy"] if r["tier"] != r["rubric_tier"]]
    assert all(r.get("evidence_adjustment") for _k, r in moved), "a row off its rubric tier carries its recorded adjustment"
    assert all(abs(qr.QUALITY_TIERS.index(r["tier"]) - qr.QUALITY_TIERS.index(r["rubric_tier"])) == 1 for _k, r in moved)


def test_control_a_hand_edited_tier_goes_red():
    for k in ("overhead_triceps_extension_cable", "lateral_raise_dumbbell", "seated_leg_curl"):
        bad = copy.deepcopy(LIB)
        row = bad["movements"][k]["hypertrophy"][0]
        row["tier"] = "D" if row["tier"] != "D" else "S"
        assert any(o.startswith(f"{k}/") and "tier" in o for o in _derivation_offenders(bad)), k
        assert any(k in err and "!= derived" in err for err in xl.validate(bad)), k
    # control: a hand-edited rubric score (the tier left alone) is red too
    bad = copy.deepcopy(LIB)
    bad["movements"]["seated_leg_curl"]["hypertrophy"][0]["rubric_score"] += 1
    assert any("rubric_score" in o for o in _derivation_offenders(bad))


def test_evidence_moves_a_row_one_band_only_from_a_direct_trial_with_its_citation():
    adjusted = [(k, r) for k, e in MV.items() for r in e["hypertrophy"] if r.get("evidence_adjustment")]
    assert adjusted, "the shipped library records direct-trial adjustments (Maeo 2021/2023, Kinoshita 2023)"
    for k, r in adjusted:
        assert r["evidence_confidence"] == "rct_direct", k
        assert r["evidence_adjustment"]["citation"] in r["citations"] and r["evidence_adjustment"]["why"], k
        assert r["evidence_adjustment"]["bands"] in (1, -1), k
    assert {r["evidence_confidence"] for e in MV.values() for r in e["hypertrophy"]} <= set(qr.EVIDENCE_CONFIDENCE)
    # controls: two bands, a characteristic trial, a citation the row does not carry — each refused
    k, r = adjusted[0]
    for bad_row in (
        r | {"evidence_adjustment": {**r["evidence_adjustment"], "bands": 2}},
        r | {"evidence_confidence": "rct_characteristic"},
        r | {"evidence_adjustment": {**r["evidence_adjustment"], "citation": "not_on_this_row"}},
        r | {"evidence_confidence": "none_reviewed", "citations": [], "last_reviewed": "unreviewed"},
    ):
        assert qr.adjustment_problems(bad_row), bad_row
        assert qr.quality_tier(MV[k], bad_row) == bad_row["rubric_tier"], "a refused adjustment never moves the tier"


def test_the_rubric_is_deterministic_and_the_committed_file_re_derives_unchanged():
    import exercise_library_reviews as reviews

    again = copy.deepcopy(MV)
    reviews.finalize_tiers(again)
    assert again == MV
    e = MV["overhead_triceps_extension_cable"]
    assert [qr.score(e, "triceps") for _ in range(3)] == [qr.score(e, "triceps")] * 3


def test_the_builder_twice_over_the_same_inputs_writes_the_same_library(monkeypatch):
    import build_exercise_library as b

    monkeypatch.setattr(b, "_LEDGER", {"reviews": []})
    catalog = json.loads((REPO / "config" / "movement_catalog.json").read_text())
    # the history the committed library was built from, as the builder's summary shape (no AWS read)
    hist = {e["template_id"]: e for e in MV.values() if e["source"] == "history"}
    history = {
        "workouts": LIB["_provenance"]["workouts"],
        "first": LIB["_provenance"]["history_first"],
        "last": LIB["_provenance"]["history_through"],
        "templates": {tid: {**e["history"], "names": {e["title"]: e["history"]["exposures"]}} for tid, e in sorted(hist.items())},
    }
    one = b.build_library(copy.deepcopy(LIB), history, catalog, {})
    two = b.build_library(copy.deepcopy(LIB), history, catalog, {})
    assert one == two and xl.validate(one) == []
    assert _derivation_offenders(one) == []


def test_bands_not_a_single_winner_every_major_muscle_has_two_in_s_or_names_why():
    short = {m: _top_band(LIB, t) for m, t in MAJOR_MUSCLES.items() if len(_top_band(LIB, t)) < 2}
    assert set(short) == set(qr.TOP_BAND_SHORTFALL), (short, sorted(qr.TOP_BAND_SHORTFALL))
    assert all(qr.TOP_BAND_SHORTFALL[m].strip() for m in short)
    # the owner's specimen: triceps no longer has a single top-band movement
    assert len(_top_band(LIB, ("triceps",))) >= 2
    # control: collapse triceps' S band to the overhead extension alone -> the muscle is short and unnamed -> red
    bad = copy.deepcopy(LIB)
    for k, e in bad["movements"].items():
        if k != "overhead_triceps_extension_cable" and e["target"]["primary"] == "triceps":
            for r in e["hypertrophy"]:
                r["tier"] = "A" if r["tier"] == "S" else r["tier"]
    assert len(_top_band(bad, ("triceps",))) == 1 and "triceps" not in qr.TOP_BAND_SHORTFALL


def test_the_library_carries_its_rubric_and_the_doc_names_its_version():
    assert LIB["quality_rubric"] == qr.rubric_doc()
    assert LIB["quality_rubric"]["provenance"].endswith("owner to confirm")
    assert f"rubric v{qr.RUBRIC_VERSION}" in DOC and "proposed weights — owner to confirm" in DOC
    for term in ("stretch", "stability", "resistance profile", "progressability", "joint stress"):
        assert term in DOC.lower(), term
    for floor, tier in qr.BANDS:
        assert f"{tier} >= {floor}" in DOC, (tier, floor)
