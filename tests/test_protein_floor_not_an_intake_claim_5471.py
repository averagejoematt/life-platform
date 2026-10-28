"""tests/test_protein_floor_not_an_intake_claim_5471.py — #5471: a stated protein FLOOR is a target reference.

THE LIVE SPECIMEN, 2026-10-27 (`qa-smoke-failures` CAUSE `cross_surface:coach_vs_engine`): Eli Marsh (lead_daily) wrote
"he ate 126 grams of protein yesterday but his floor is 170 grams daily" and the leg failed "cites 170g vs engine 138.3g".
170 g is the charter's protein floor, the number he is short of, not a claim about intake.

THE RULE: a protein gram figure a floor / target / goal / minimum word binds to (nearest figure, within one clause) is
skipped as a target reference — counted on the emitted counts line, in no claim bucket — while the real intake claim
in the same sentence stays in play. Offline, no clock.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from operational import weight_truth_qa as wq  # noqa: E402

SPECIMEN = "he ate 126 grams of protein yesterday but his floor is 170 grams daily"
ENGINE = {"avg_protein_g": 138.3, "lag_days": 0}


def _coach(text):
    return {"name": "Eli Marsh (lead_daily)", "summary": text}


def _protein(text):
    return sorted(v for v, _cls in wq.coach_quantity_claims(_coach(text)).get("protein", []))


def test_the_specimen_keeps_the_intake_claim_and_drops_the_floor():
    assert _protein(SPECIMEN) == [126.0]


def test_the_specimen_passes_vs_engine_and_counts_the_skip():
    ok, msg = wq.assess_cross_surface_coach_vs_engine([_coach(SPECIMEN)], nutrition=ENGINE)
    assert ok, msg
    assert "1 skipped as a protein floor/target reference" in msg
    assert "2 extracted, 1 compared" in msg  # the 126 g leg is judged (126 vs 138.3 is inside tolerance)


def test_the_consistency_leg_names_the_skip_too():
    ok, msg = wq.assess_cross_surface_coach_consistency([_coach(SPECIMEN), {"name": "B", "summary": "protein intake is 130 g."}])
    assert ok, msg
    assert "1 skipped as a protein floor/target reference" in msg


def test_a_floor_word_after_the_figure():
    assert _protein("the protein is a 170 g floor.") == []
    ok, msg = wq.assess_cross_surface_coach_vs_engine([_coach("His protein floor is 170 g.")], nutrition=ENGINE)
    assert ok, msg


def test_a_target_of_figure_is_counted_not_compared():
    ok, msg = wq.assess_cross_surface_coach_vs_engine([_coach("Protein: a target of 170 g.")], nutrition=ENGINE)
    assert ok, msg
    assert "1 skipped as a protein floor/target reference" in msg


def test_goal_and_minimum_words_bind_the_same_way():
    for text in ("protein goal is 170 g", "a minimum of 170 g protein", "170 g protein is the daily target"):
        ok, msg = wq.assess_cross_surface_coach_vs_engine([_coach(text)], nutrition=ENGINE)
        assert ok, (text, msg)


def test_nearest_figure_wins_in_one_clause():
    # the floor binds to 170 (adjacent), not 126 (further away) — no contrast word needed
    assert 170.0 not in _protein("he ate 126 g of protein, well under the 170 g floor")
    assert 126.0 in _protein("he ate 126 g of protein, well under the 170 g floor")


def test_control_a_wrong_intake_claim_still_fails():
    ok, msg = wq.assess_cross_surface_coach_vs_engine([_coach("he averaged 170 g of protein this week")], nutrition=ENGINE)
    assert not ok, msg
    assert "cites 170g vs engine 138.3g" in msg
    assert "0 skipped as a protein floor/target reference" in msg


def test_control_a_wrong_intake_claim_beside_a_floor_still_fails():
    text = "he ate 170 grams of protein yesterday but his floor is 170 grams daily"
    ok, msg = wq.assess_cross_surface_coach_vs_engine([_coach(text)], nutrition=ENGINE)
    assert not ok, msg
    assert "1 skipped as a protein floor/target reference" in msg


def test_other_quantities_are_untouched():
    claims = wq.coach_quantity_claims(_coach("recovery was 44% but his protein floor is 170 g"))
    assert claims.get("recovery") == [(44.0, "current")]


def test_classify_claims_keeps_its_three_tuple_contract():
    out = wq.classify_claims(SPECIMEN, wq._CLAIM_PATTERNS, wq._CLAIM_DOMAIN)
    assert len(out) == 3
    assert len(wq.classify_claims_counted(SPECIMEN, wq._CLAIM_PATTERNS, wq._CLAIM_DOMAIN)) == 4
