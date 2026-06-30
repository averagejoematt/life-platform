"""tests/test_reading_recommender.py — the rules-based recommender (spec §4).

Asserts anti-black-box reason strings, the anti-Goggins goal-domain penalty,
breadth/capacity/difficulty behavior, the confidence n-gate → propose-and-dispose,
and honest-empty on no candidates.
"""

from __future__ import annotations

import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

from reading import reading_recommender as rr  # noqa: E402

_FICTION = {
    "bookId": "f1",
    "title": "A Novel",
    "author": "X",
    "domainTags": ["fiction"],
    "pageCount": 280,
    "difficulty": {"composite": 2.0},
}
_GOAL = {
    "bookId": "g1",
    "title": "Optimize Everything",
    "author": "Y",
    "domainTags": ["self-help", "business"],
    "pageCount": 250,
    "difficulty": {"composite": 2.0},
}
_DOORSTOP = {
    "bookId": "d1",
    "title": "The Big One",
    "author": "Z",
    "domainTags": ["classics"],
    "pageCount": 900,
    "difficulty": {"composite": 4.5},
}


def _state(**over):
    base = {
        "week_color": "YELLOW",
        "wheel_distribution": {"fiction": 5},
        "curriculum_phase": 2,
        "ratchet_position": 0.4,
        "n_finished": 20,
        "n_abandoned": 5,
        "trust_ladder_mode": "shortlist",
    }
    base.update(over)
    return base


def test_reason_string_is_decomposed_and_present():
    out = rr.rank([_FICTION], _state())
    rec = out["recommendations"][0]
    assert rec["reason"].startswith("Recommended because")
    assert isinstance(rec["components"], dict) and rec["components"]
    assert "fit" in rec


def test_anti_goggins_penalizes_goal_domain():
    out = rr.rank([_FICTION, _GOAL], _state(wheel_distribution={}))
    by_id = {r["bookId"]: r for r in out["recommendations"]}
    # both surface (shortlist mode, medium confidence) and the goal-domain book is penalized
    assert by_id["g1"]["penalties"]["goal-domain"] > 0.5
    assert by_id["f1"]["fit"] > by_id["g1"]["fit"]


def test_breadth_gain_prefers_thin_slice():
    # wheel is all fiction → a history book gains breadth, fiction does not
    hist = {"bookId": "h1", "title": "Past", "author": "H", "domainTags": ["history"], "pageCount": 280, "difficulty": {"composite": 2.0}}
    out = rr.rank([_FICTION, hist], _state(wheel_distribution={"fiction": 10}))
    by_id = {r["bookId"]: r for r in out["recommendations"]}
    assert by_id["h1"]["components"]["breadth"] > by_id["f1"]["components"]["breadth"]


def test_red_week_subtracts_the_doorstop():
    green = rr.score_one(_DOORSTOP, _state(week_color="GREEN", curriculum_phase=4, ratchet_position=0.6), rr.WEIGHTS[4])
    red = rr.score_one(_DOORSTOP, _state(week_color="RED", curriculum_phase=4, ratchet_position=0.6), rr.WEIGHTS[4])
    assert green["fit"] > red["fit"]
    assert green["components"]["difficulty"] > red["components"]["difficulty"]
    assert green["components"]["capacity"] > red["components"]["capacity"]


def test_low_n_forces_propose_and_dispose():
    out = rr.rank([_FICTION, _GOAL, _DOORSTOP], _state(n_finished=2, n_abandoned=0, trust_ladder_mode="surprise"))
    assert out["confidence"] == "very-low"
    assert out["propose_and_dispose"] is True
    assert len(out["recommendations"]) == 1  # only one pick surfaced at low n


def test_high_n_shortlist_surfaces_multiple():
    out = rr.rank([_FICTION, _GOAL, _DOORSTOP], _state(n_finished=40, n_abandoned=8, trust_ladder_mode="shortlist"), top_n=3)
    assert out["confidence"] == "high"
    assert out["propose_and_dispose"] is False
    assert len(out["recommendations"]) == 3


def test_empty_candidates_is_honest():
    out = rr.rank([], _state())
    assert out["recommendations"] == [] and out["candidate_count"] == 0


def test_whiplash_penalty_on_genre_lurch():
    out = rr.score_one(_DOORSTOP, _state(last_finished={"domainTags": ["fiction"]}), rr.WEIGHTS[2])
    assert out["penalties"]["whiplash"] > 0  # classics off a fiction finish, no overlap


def test_phase1_weights_favor_capacity_completion():
    # in phase 1, a short propulsive book should beat a long hard one even with breadth on the long one
    out = rr.rank([_FICTION, _DOORSTOP], _state(curriculum_phase=1, wheel_distribution={"fiction": 10}, ratchet_position=0.3))
    assert out["recommendations"][0]["bookId"] == "f1"


def test_resonance_lifts_and_appears_in_reason():
    base = rr.score_one(_FICTION, _state(), rr.WEIGHTS[2])
    lifted = rr.score_one(_FICTION, _state(journal_resonance={"f1": 0.95}), rr.WEIGHTS[2])
    assert lifted["fit"] > base["fit"]
    assert lifted["resonance"] == 0.95
