"""tests/test_coach_chat_grounding.py — the chat's fact block and gate arming
(#2364, epic #2363).

The property under test is narrow and load-bearing: **a coach in a text message
cannot state a number, a date, or a day that the facts do not support.** #2343 is
the failure this is built against, and note its shape — the cited HRV and recovery
were REAL readings, present in the platform, just belonging to a different day. An
existence-only check passes that. Only the night class catches it.
"""

from __future__ import annotations

from coach import coach_chat_grounding as g

FACTS = {
    "night_of": "2026-08-07",
    "recovery_pct": 55.0,
    "hrv_ms": 42.0,
    "rhr_bpm": 58.0,
    "weight_lbs": 318.4,
    "protein_g": 148,
    "generation_date": "2026-08-08",
    "nested": {"deficit_kcal": 620, "days": [3, 970]},
}


# ── The allow-list is DERIVED, not hand-listed ────────────────────────────────


def test_every_number_in_the_facts_is_allowed_including_nested_ones():
    a = g.allowed_numbers(FACTS)
    for v in (55.0, 42.0, 58.0, 318.4, 148, 620, 970):
        assert v in a, f"{v} is in the facts and must not read as fabricated"


def test_a_number_absent_from_the_facts_is_not_allowed():
    assert 165 not in g.allowed_numbers(FACTS)


def test_a_newly_added_fact_is_grounded_automatically():
    """A hand-listed allow-list rots the moment an upstream fact is added — the new
    field reads as a fabrication on first appearance, and the reflex fix (widen the
    list) is how allow-lists stop meaning anything. Derivation is the guard."""
    assert 91.7 not in g.allowed_numbers(FACTS)
    assert 91.7 in g.allowed_numbers(dict(FACTS, brand_new_metric=91.7))


def test_booleans_are_not_treated_as_the_numbers_one_and_zero():
    """`True` is an int in Python. Letting it seed the allow-list would silently
    ground a literal 1 that no fact actually contains."""
    a = g.allowed_numbers({"stalled": True, "ready": False})
    assert a == set(g._BENIGN)


def test_small_conversational_integers_stay_benign():
    a = g.allowed_numbers({})
    assert 1 in a and 3 in a, "a coach saying 'one more day' is not fabricating data"


def test_the_allow_list_survives_an_empty_or_missing_fact_set():
    assert g.allowed_numbers({}) == set(g._BENIGN)
    assert g.allowed_numbers(None) == set(g._BENIGN)


# ── Dates ─────────────────────────────────────────────────────────────────────


def test_dates_present_in_the_facts_are_collected():
    d = g.allowed_dates(FACTS)
    assert "2026-08-07" in d and "2026-08-08" in d


def test_a_fact_set_with_no_dates_yields_an_EMPTY_set_not_none():
    """Empty and None mean different things to the gate: empty says 'no date is
    legitimate' (the correct posture), None switches the date class OFF."""
    d = g.allowed_dates({"recovery_pct": 55})
    assert d == set()
    assert d is not None


def test_a_non_date_string_of_the_same_length_is_not_collected():
    assert g.allowed_dates({"note": "abcd-ef-gh"}) == set()


# ── The facts block ───────────────────────────────────────────────────────────


def test_an_empty_fact_set_produces_an_explicit_statement_of_absence():
    """Silence is never the honest default. A coach handed no facts must be TOLD it
    has none, or it answers from the persona's general knowledge and sounds exactly
    as confident as one that checked."""
    block = g.build_facts_block({})
    assert block.strip()
    assert "none available" in block.lower()
    assert "no numbers to cite" in block.lower()


def test_a_populated_fact_set_renders_through_the_shared_renderer():
    """Reused, not forked: the shared renderer carries the #2113 rider that WITHHOLDS
    values from before this cycle's genesis. A chat-specific wording would drop it."""
    block = g.build_facts_block(FACTS)
    assert block.strip()
    assert "none available" not in block.lower()


# ── The arming: all five classes, on a real gate call ─────────────────────────


def test_a_reply_citing_only_grounded_numbers_passes():
    grounder = g.build_grounder(FACTS, generation_date_iso="2026-08-08")
    assert grounder("Protein came in at 148 g.") == []


def test_a_fabricated_number_is_caught():
    grounder = g.build_grounder(FACTS, generation_date_iso="2026-08-08")
    findings = grounder("You averaged 165 g of protein.")
    assert findings, "165 appears nowhere in the facts"


def test_the_2343_case_a_real_reading_attributed_to_the_WRONG_DAY_is_caught():
    """The whole reason this surface arms `night`. 55% and 42 ms are REAL — they are
    2026-08-07's readings, right there in the facts. Presented as today's they are a
    lie, and an existence-only allow-list passes them without complaint."""
    grounder = g.build_grounder(FACTS, generation_date_iso="2026-08-08")
    ungrounded = grounder("Whoop shows 55% recovery and HRV at 42 ms right now.")
    assert ungrounded, "a real reading attributed to the wrong day must not pass"
    grounded = grounder("On the night of 2026-08-07 you came in at 55% recovery, HRV 42 ms.")
    assert grounded == [], "the same values, correctly day-labelled, must pass"


def test_naming_the_night_is_what_makes_the_claim_honest():
    """Restating the positive half: the fix for a night-scope finding is to NAME the
    night, never to widen a tolerance."""
    grounder = g.build_grounder(FACTS, generation_date_iso="2026-08-08")
    assert grounder("Night of 2026-08-07: HRV 42 ms.") == []


def test_a_fabricated_date_is_caught():
    grounder = g.build_grounder(FACTS, generation_date_iso="2026-08-08")
    assert grounder("Back on 2025-01-14 you were heavier."), "a date absent from the facts must not pass"


def test_the_grounder_is_reusable_across_turns_without_rebuilding():
    """It is built once per turn and called up to twice (generate, then regenerate).
    A grounder that mutated its own allow-list would let attempt 2 pass what attempt
    1 failed."""
    grounder = g.build_grounder(FACTS, generation_date_iso="2026-08-08")
    first = grounder("You averaged 165 g.")
    second = grounder("You averaged 165 g.")
    assert first and second and len(first) == len(second)


def test_an_empty_fact_set_still_gates_rather_than_failing_open():
    """With MacroFactor quiet 45 days (#2326) this is the LIVE case for the nutrition
    coach — no facts at all. It must be the strictest state, not the loosest."""
    grounder = g.build_grounder({}, generation_date_iso="2026-08-08")
    assert grounder("You hit 190 g of protein yesterday."), "no facts must mean no numbers, not a free pass"


def test_a_reply_with_no_numbers_at_all_passes_on_an_empty_fact_set():
    """The honest answer when there is nothing to cite — it must remain sayable."""
    grounder = g.build_grounder({}, generation_date_iso="2026-08-08")
    assert grounder("I don't have your food logs for that stretch, so I can't tell you.") == []
