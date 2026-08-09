"""tests/test_coach_chat_grounding.py — the chat's fact block and gate arming
(#2364, epic #2363).

The property under test is narrow and load-bearing: **a coach in a text message
cannot state a number, a date, or a day that the material it was given does not
support.** #2343 is the failure this is built against, and note its shape — the
cited HRV and recovery were REAL readings, present in the platform, just belonging
to a different day. An existence-only check passes that. Only the night class
catches it.

These tests run the REAL gate (``ai.grounded_generation`` and friends), not a
double: the module under test is a thin arming layer, and testing it against a fake
gate would prove nothing about the one property that matters.
"""

from __future__ import annotations

import os

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


def grounder(facts=FACTS, **kw):
    kw.setdefault("generation_date_iso", "2026-08-08")
    return g.build_grounder(facts, **kw)


# ── Reuse is the design: this module must not fork the gate's vocabulary ──────


def test_the_module_delegates_to_the_shared_allow_list_builders_rather_than_forking_them():
    """The first draft reimplemented ``allowed_numbers``/``allowed_dates`` locally;
    review caught that ``ai.grounded_generation`` already exports both, and the
    shared versions are behaviourally better (they ground the memory block and the
    thread, not just the fact dict). This guard keeps the fork from growing back —
    a local reimplementation would drift from the gate's own extraction rules and
    the two would disagree about what counts as a number."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "lambdas", "coach", "coach_chat_grounding.py")).read()
    assert "from ai.grounded_generation import allowed_dates, allowed_numbers" in src
    assert "def allowed_numbers" not in src
    assert "def allowed_dates" not in src
    import re

    assert not re.search(r"^_BENIGN\w*\s*=", src, re.M), "benign smalls are the gate's own _BENIGN_NUMBERS, not a local list"


# ── The allow-list covers everything the model was given ──────────────────────


def test_numbers_from_the_facts_pass_including_nested_ones():
    assert grounder()("Protein came in at 148 g against a 620 kcal deficit.") == []


def test_a_number_absent_from_everything_is_caught():
    findings = grounder()("You averaged 165 g of protein.")
    assert findings, "165 appears nowhere in the facts"


def test_a_number_from_the_MEMORY_block_is_not_a_fabrication():
    """The behavioural reason the shared builders won over the local walker: a coach
    quoting its own memory ("you committed to 170 g") must not read as inventing
    170. The memory block rides in ``extra_sources``."""
    memory = "You remember: he committed to 170 g protein as his floor."
    strict = grounder()("Your floor is 170 g — that was the deal.")
    assert strict, "without the memory in scope, 170 is ungrounded (the negative control)"
    with_memory = grounder(extra_sources=(memory,))("Your floor is 170 g — that was the deal.")
    assert with_memory == []


def test_a_number_matthew_himself_said_can_be_quoted_back():
    thread_text = "Matthew: I think I got about 132 g in yesterday."
    assert grounder(extra_sources=(thread_text,))("132 g would put you under the floor.") == []


def test_a_newly_added_fact_is_grounded_automatically():
    """A hand-listed allow-list rots the moment an upstream fact is added — the new
    field would read as a fabrication on first appearance. Derivation is the guard."""
    assert grounder()("Your readiness index is 91.7.") != []
    assert grounder(dict(FACTS, brand_new_metric=91.7))("Your readiness index is 91.7.") == []


# ── Dates ─────────────────────────────────────────────────────────────────────


def test_a_date_present_in_the_facts_may_be_cited():
    assert grounder()("Your last weigh-in was 2026-08-08.") == []


def test_a_fabricated_date_is_caught():
    assert grounder()("Back on 2025-01-14 you were heavier."), "a date absent from the facts must not pass"


def test_a_fact_set_with_no_dates_means_no_date_is_legitimate():
    """Empty and None mean different things to the gate: an empty allow-list says
    'no date is legitimate' (the correct posture), None switches the class OFF.
    The arming must produce the former."""
    bare = {"recovery_pct": 55.0}
    assert grounder(bare)("It was 2026-08-05 when this started."), "with no dates in scope, any cited date is fabricated"


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


# ── The #2343 class: day-correspondence, not existence ────────────────────────


def test_the_2343_case_a_real_reading_attributed_to_the_WRONG_DAY_is_caught():
    """The whole reason this surface arms `night`. 55% and 42 ms are REAL — they are
    2026-08-07's readings, right there in the facts. Presented as today's they are a
    lie, and an existence-only allow-list passes them without complaint."""
    ungrounded = grounder()("Whoop shows 55% recovery and HRV at 42 ms right now.")
    assert ungrounded, "a real reading attributed to the wrong day must not pass"
    # NB the phrasing: "recovery 55%" and "HRV 42 ms" keep each figure adjacent to its
    # own metric noun. The gate's proximity patterns read "recovery, HRV 42" as a
    # recovery figure of 42 — correct behaviour for the gate (adjacency IS the claim
    # structure in prose), and a phrasing this test must not manufacture.
    grounded = grounder()("On the night of 2026-08-07 you came in at recovery 55%, with HRV 42 ms.")
    assert grounded == [], "the same values, correctly day-labelled, must pass"


def test_naming_the_night_is_what_makes_the_claim_honest():
    """The positive half restated: the fix for a night-scope finding is to NAME the
    night, never to widen a tolerance."""
    assert grounder()("Night of 2026-08-07: HRV 42 ms.") == []


def test_a_remembered_vital_is_still_night_checked_even_though_the_number_is_allowed():
    """extra_sources widen the NUMBER vocabulary, never the vitals adjudication: the
    night map builds from the facts alone. A recovery figure that the memory block
    happens to contain still may not be pinned to a night whose stored value
    disagrees."""
    memory = "Last week he bottomed out at recovery 31%."
    findings = grounder(extra_sources=(memory,))("On the night of 2026-08-07 your recovery was 31%.")
    assert findings, "31% is allowed as a NUMBER, but 2026-08-07's stored recovery is 55% — the night class must still fire"


# ── Failure postures ──────────────────────────────────────────────────────────


def test_an_empty_fact_set_still_gates_rather_than_failing_open():
    """With MacroFactor quiet 45 days (#2326) this is the LIVE case for the nutrition
    coach — no facts at all. It must be the strictest state, not the loosest."""
    assert grounder({})("You hit 190 g of protein yesterday."), "no facts must mean no numbers, not a free pass"


def test_a_reply_with_no_numbers_at_all_passes_on_an_empty_fact_set():
    """The honest answer when there is nothing to cite — it must remain sayable."""
    assert grounder({})("I don't have your food logs for that stretch, so I can't tell you.") == []


def test_the_grounder_is_reusable_across_turns_without_rebuilding():
    """It is built once per turn and called up to twice (generate, then regenerate).
    A grounder that mutated its own allow-list would let attempt 2 pass what attempt
    1 failed."""
    gr = grounder()
    first = gr("You averaged 165 g.")
    second = gr("You averaged 165 g.")
    assert first and second and len(first) == len(second)
