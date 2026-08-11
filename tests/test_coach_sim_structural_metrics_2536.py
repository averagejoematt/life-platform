"""#2536 — the shape metrics in scripts/coach_sim_shapes.py.

WHY THESE TESTS ARE THE POINT. The failure this issue attacks was invisible to the
metric that was already watching for it: shingle-Jaccard between coaches ran under
0.06 — which reads as healthy voice separation — while six of eight coaches produced
the same three moves in different vocabularies. A similarity metric built on shared
WORDS cannot see shared SHAPE, and a green metric over a real defect is worse than no
metric.

So the assertions below are adversarial by construction. Each one pins a case where a
weaker implementation would report the wrong answer:

  * eight IDENTICAL replies must report one shape and a collapse of 1.0. A structural
    metric that cannot fail on that input is decoration.
  * eight replies that share the template and differ only in synonyms must also report
    one shape — that is the exact input Jaccard scored as separate voices.
  * eight replies that make genuinely different MOVES must report five or more.
  * a leading "Yeah." must not change the shape. It used to: the discourse particle
    had its own opening class, so a coach could bolt one word onto the front of the
    template and register as a different persona.
  * a bubble break must count as a sentence break. "rough ones drag" + "eaten
    anything yet?" is a statement followed by a question, not one question — and 2 of
    8 off_lane openers fingerprinted wrongly before this was fixed.

The two collision metrics are pinned the same way: they must FIRE on the measured
corpus shapes ("that kind of" opening five coaches, "don't have that" opening six)
and must go silent when the same coaches say the same things differently.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from coach_sim_shapes import (  # noqa: E402  (path set above)
    absence_phrasing_collisions,
    opening_construction_collisions,
    structural_collapse,
    structural_signature,
)

_INBOUND = "honestly I'm just tired of all of this"
_COACHES = [
    "sleep_coach",
    "nutrition_coach",
    "mind_coach",
    "physical_coach",
    "explorer_coach",
    "pattern_coach",
    "career_coach",
    "eli_marsh",
]


def _corpus(replies, archetype="venting_no_question", inbound=_INBOUND):
    """One conversation per coach, one turn each — the shape the collapse metric reads."""
    return [
        {"coach": coach, "archetype": archetype, "turns": [{"inbound": inbound, "reply": reply}]} for coach, reply in zip(_COACHES, replies)
    ]


def _row(convos, archetype="venting_no_question"):
    rows = [r for r in structural_collapse(convos) if r["archetype"] == archetype]
    assert len(rows) == 1, f"expected one row for {archetype}, got {rows}"
    return rows[0]


# ── The hard failure: a metric that cannot fail ───────────────────────────────


def test_eight_identical_replies_collapse_to_one_shape():
    """The mutation is the input. If this ever reports more than one shape, or a
    collapse below 1.0, every other number this module produces is meaningless."""
    row = _row(_corpus(["That kind of tired isn't about sleep. What's going on?"] * 8))
    assert row["distinct_shapes"] == 1
    assert row["collapse_ratio"] == 1.0
    assert row["largest_cluster"] == 8
    assert row["dominant_coaches"] == sorted(_COACHES)


def test_the_template_in_eight_vocabularies_still_collapses():
    """The measured failure, reconstructed. These eight share NO content words beyond
    the template's own scaffolding, which is why shingle-Jaccard scored them apart —
    and they run the identical three moves: demonstrative acknowledgement, his phrase
    quoted back, a menu question."""
    replies = [
        'That lands. What\'s the "all of this" — the tracking, the project, or something else?',
        'That kind of tired is real. What\'s the "all of this" — work, the program, or today?',
        'That sounds heavy. What\'s the "all of this" — the logging, the diet, or the whole thing?',
        'That tracks. What\'s the "all of this" — training, the cycle, or something outside it?',
        'That reads as worn out. What\'s the "all of this" — the data, the effort, or the results?',
        'That is worth taking seriously. What\'s the "all of this" — the record, the week, or the year?',
        'That is a real thing to say. What\'s the "all of this" — the job, the health stuff, or both?',
        'That registers. What\'s the "all of this" — the routine, the tracking, or life generally?',
    ]
    row = _row(_corpus(replies))
    assert row["distinct_shapes"] == 1, f"synonym swaps registered as different shapes: {row}"
    assert row["collapse_ratio"] == 1.0


def test_eight_genuinely_different_moves_report_five_or_more():
    """The other direction: a metric that always reports collapse is equally useless.
    These are the eight moves the voice specs now ask for — sit with it, hand it off,
    guess out loud, take load off, decline the question, state a record fact, name the
    load, ask about the day."""
    replies = [
        "Nothing about tonight needs solving.",  # OPEN_FACT, statement
        "What did you eat today?",  # OPEN_QUESTION
        "I think this is the third week more than it's today.",  # OPEN_SELF
        "Skip tomorrow. We'll pick it back up when you want to.",  # OPEN_DIRECTIVE
        'You said "all of this" — I don\'t have a read on that one.',  # ACK_HIS_STATE + echo
        "Three weeks of this now, or thereabouts — the tracking, the training, or something else?",  # menu
        "Heard.",  # OPEN_FACT, one word
        "hey. rough one?",  # OPEN_GREETING
    ]
    row = _row(_corpus(replies))
    assert row["distinct_shapes"] >= 5, f"eight distinct moves reported {row['distinct_shapes']} shapes: {row}"
    # collapse_ratio is a SECOND number, not a restatement of the first: a hard-coded
    # 1.0 survives every distinct_shapes assertion in this file, so a diverse corpus
    # has to pin it low from the other side.
    assert row["collapse_ratio"] < 0.5, f"a diverse corpus reported collapse {row['collapse_ratio']}"
    assert row["largest_cluster"] < row["coaches"]


# ── The two fingerprinting bugs this issue fixed ──────────────────────────────


@pytest.mark.parametrize(
    "particle",
    ["Yeah. ", "Ha. ", "Fair. ", "Honestly, ", "ok. "],
)
def test_a_leading_discourse_particle_does_not_change_the_shape(particle):
    """One word in front of the template used to buy a whole extra 'distinct shape'."""
    bare = "That kind of tired isn't about sleep. What's going on?"
    assert structural_signature(particle + bare, _INBOUND) == structural_signature(bare, _INBOUND)


def test_a_greeting_is_not_a_discourse_particle():
    """bare_greeting collapsing is CORRECT — 'Hey' should get 'Hey' from everyone —
    so the greeting class has to survive the particle strip that killed 'Yeah'."""
    assert structural_signature("Hey", "Hey").startswith("OPEN_GREETING")
    assert not structural_signature("Yeah. Nothing to change today.", _INBOUND).startswith("OPEN_GREETING")


def test_a_bubble_break_counts_as_a_sentence_break():
    """Two bubbles with no terminal punctuation on the first one. The opening move is
    the statement, not the question that follows it in the second bubble."""
    two_bubbles = "rough ones have a way of landing on day 1\n\neaten anything yet?"
    assert structural_signature(two_bubbles, "long day. work was a mess").startswith("OPEN_FACT")
    # ...and the close axis still reads the LAST thing he sent.
    assert "CLOSING_QUESTION" in structural_signature(two_bubbles, "long day. work was a mess")


def test_elided_first_person_is_a_self_statement_not_a_directive():
    """'Don't have that' is what the coach HAS, not an instruction to Matthew. Reading
    it as an imperative puts every honest-absence opener in the wrong class."""
    assert structural_signature("Don't have that data.", "what's my rhr for 2019").startswith("OPEN_SELF")
    assert structural_signature("Don't skip dinner tonight.", "not hungry").startswith("OPEN_DIRECTIVE")


def test_the_axes_are_read_independently():
    """Echo and close are separate signals: quoting him back without a question, and a
    menu question without quoting him, must not hash the same."""
    echo_no_q = 'You said "all of this" and I think you mean the tracking.'
    menu_no_echo = "Is it the tracking, the program, or something else?"
    assert "ECHO_QUOTE" in structural_signature(echo_no_q, _INBOUND)
    assert "CLOSES_STATEMENT" in structural_signature(echo_no_q, _INBOUND)
    assert "NO_ECHO" in structural_signature(menu_no_echo, _INBOUND)
    assert "MENU_QUESTION" in structural_signature(menu_no_echo, _INBOUND)


def test_an_archetype_with_too_few_coaches_is_not_scored():
    """A per-coach domain scenario has nothing to compare against; scoring it would
    report a fake collapse of 1.0 for every single-coach archetype in the corpus."""
    convos = _corpus(["a", "b", "c"])[:3]
    for c in convos:
        c["archetype"] = "domain_sleep"
    assert structural_collapse(convos) == []


# ── The collision metrics ─────────────────────────────────────────────────────


def test_opening_constructions_catch_the_stem_a_four_word_key_misses():
    """`that kind of tired` / `that kind of Monday` / `that kind of day` are three
    four-word keys and ONE construction. The measured corpus had it opening five
    coaches while `opener_collisions` reported three."""
    replies = [
        "That kind of tired isn't about sleep.",
        "Yeah. That kind of tired is worth noticing.",
        "That kind of Monday sets the tone.",
        "That kind of day follows you home.",
        "Nothing to change today.",
        "Heard.",
        "What happened?",
        "Skip tomorrow.",
    ]
    rows = opening_construction_collisions(_corpus(replies))
    assert [r["stem"] for r in rows] == ["that kind of"]
    assert rows[0]["n_coaches"] == 4


def test_opening_constructions_go_silent_on_differentiated_openers():
    """The mutation in the other direction — same eight coaches, eight constructions."""
    replies = [
        "Nothing about tonight needs solving.",
        "What did you eat today?",
        "I think this is the week, not the day.",
        "Skip tomorrow if you want.",
        "Outside what I'm any use for.",
        "Heard.",
        "Name the part you'd put down.",
        "What happened today?",
    ]
    assert opening_construction_collisions(_corpus(replies)) == []


def test_absence_phrasing_reads_every_turn_not_only_the_first():
    """A refusal is usually the answer to his second or third message. A first-turn
    metric cannot see the failure it exists to catch."""
    convos = [
        {
            "coach": "sleep_coach",
            "archetype": "fabrication_bait",
            "turns": [
                {"inbound": "hey", "reply": "hey"},
                {"inbound": "rhr for 2019?", "reply": "Don't have that data."},
            ],
        },
        {
            "coach": "mind_coach",
            "archetype": "fabrication_bait",
            "turns": [
                {"inbound": "hey", "reply": "hey"},
                {"inbound": "rhr for 2019?", "reply": "Don't have that either."},
            ],
        },
        {
            "coach": "pattern_coach",
            "archetype": "fabrication_bait",
            "turns": [
                {"inbound": "hey", "reply": "hey"},
                {"inbound": "rhr for 2019?", "reply": "Don't have that — nothing from then."},
            ],
        },
    ]
    rows = absence_phrasing_collisions(convos)
    assert [r["stem"] for r in rows] == ["don't have that"]
    assert rows[0]["n_coaches"] == 3


def test_absence_phrasing_goes_silent_when_the_admissions_are_differentiated():
    """Honest absence is REQUIRED (ADR-104). All three of these admit the gap; none
    of them admits it in the same words, and that is the whole distinction."""
    convos = [
        {
            "coach": "sleep_coach",
            "archetype": "fabrication_bait",
            "turns": [{"inbound": "rhr 2019?", "reply": "My view goes back eight nights, no further."}],
        },
        {
            "coach": "mind_coach",
            "archetype": "fabrication_bait",
            "turns": [{"inbound": "rhr 2019?", "reply": "Not something I have access to."}],
        },
        {
            "coach": "pattern_coach",
            "archetype": "fabrication_bait",
            "turns": [{"inbound": "rhr 2019?", "reply": "My record starts where you started sharing."}],
        },
    ]
    assert absence_phrasing_collisions(convos) == []


def test_an_absence_sentence_is_required_for_the_absence_metric_to_fire():
    """It keys on the admission, not on every sentence — otherwise it would rank
    whatever eight coaches happened to open with and call it a refusal finding."""
    convos = [
        {"coach": c, "archetype": "off_lane", "turns": [{"inbound": "long day", "reply": "Yeah, those ones drag."}]}
        for c in ("sleep_coach", "mind_coach", "pattern_coach")
    ]
    assert absence_phrasing_collisions(convos) == []
