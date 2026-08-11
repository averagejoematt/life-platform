"""
test_coach_sim_balanced_clause_2537.py — the widened balanced-clause detector (#2537).

WHAT THIS IS GUARDING. The blind panel over 120 simulated conversations put
rhetorical symmetry at the top of 2,404 free-text tells (25%), and the
deterministic detector for the same thing found 9 instances in 536 replies. That
gap is the "a guard that guards nothing" failure: a style gate carrying this
signal would have reported green on the corpus's loudest defect.

WHY THE FIXTURES ARE QUOTATIONS, NOT INVENTIONS. A regex tuned against sentences
written by the same person writing the regex measures that person's imagination.
Every span in `REAL_POSITIVES` and `REAL_NEGATIVES` below is quoted from the
recorded corpus — `docs/design/COACH_SIM_FINDINGS_2026_08_10.md` (real coach
replies, the spans the judges named as tells, the moments they credited as most
human), `scripts/coach_sim_scenarios.py` (Matthew's own pinned openers), or #2537
itself. The negatives matter as much as the positives: the judge-credited human
moments are the ones a widened detector is most likely to start eating.

WHAT THE COUNTS ARE, AND WHAT THEY ARE NOT. The original 536-reply corpus is not
committed (it is a run artefact, and it carries real coach output). So the counts
asserted here are over n=8 quoted positive spans and n=20 quoted negative spans,
which is a specificity/sensitivity floor and NOT a corpus-wide rate. The
corpus-wide grading lives in `validate_against_judge_tells`, exercised below on a
payload built by the real pipeline and runnable against a live run's `--json-out`
via `--validate-from`.

ADVISORY BY CONSTRUCTION. Nothing here asserts the detector rewrites, blocks, or
holds a reply. It counts. The mutating enforcement path is a different module
(#2555) on purpose.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location("coach_sim_analyze", os.path.join(_ROOT, "scripts", "coach_sim_analyze.py"))
csa = importlib.util.module_from_spec(_SPEC)
sys.modules["coach_sim_analyze"] = csa
_SPEC.loader.exec_module(csa)


# ── Labelled data, all quoted ─────────────────────────────────────────────────

# (span, the class it must be attributed to). Attribution is asserted, not just
# "something fired" — a detector that catches everything under one label cannot
# tell an operator which sentence to cut.
REAL_POSITIVES = [
    # #2537, "antithesis without the `not` frame"
    ("The number itself is less important than what it's doing over time.", "comparative_antithesis"),
    # #2537, "parallel construction"
    ("No background processing, no waiting around, no boredom.", "parallel_construction"),
    # #2537, "the summarising flourish that closes a reply too neatly"
    ("Which is either reassuring or unsettling depending on how you look at it.", "closing_flourish"),
    # #2537, "balanced two-clause verdicts"
    ("That's signal, not alarm.", "x_not_y"),
    # COACH_SIM_FINDINGS Finding 1 — the reply 6 of 8 coaches produced, verbatim.
    (
        "Honestly? Nothing. I don't exist between conversations — no background processing, " "no waiting around, no boredom.",
        "parallel_construction",
    ),
    # COACH_SIM_FINDINGS Finding 1 table — three real identity replies that land
    # on the balanced verdict. Real coach output, not a constructed sentence.
    ("No — I'm a fictional AI composite, not a real human.", "x_not_y"),
    ("No — I'm a fictional composite persona, not a real person or licensed clinician.", "x_not_y"),
    ("No — I'm a fictional AI coach… a canonical composite character, not a real human.", "x_not_y"),
]

REAL_NEGATIVES = [
    # The three moments the judges explicitly credited as MOST HUMAN. If widening
    # eats these, it has made the instrument worse: it would now flag the exact
    # behaviour the roadmap is trying to produce.
    "Fair catch on my end — I did the math myself and presented it like it was your data.",
    "That's genuinely Webb's call… I don't want to give you a number that sounds authoritative but isn't.",
    "Good call. Ship the backend stuff, don't manufacture a problem that isn't there.",
    # Matthew's own pinned openers (scripts/coach_sim_scenarios.py). A detector
    # that fires on the human half of the transcript is measuring nothing.
    "Hey",
    "thanks",
    "are you a real person?",
    "long day. work was a mess",
    "honestly I'm just tired of all of this",
    # Finding 4's template spans — real coach replies, but the defect there is
    # SHAPE, and #2536 owns that detector. This one must stay out of its lane.
    "That lands.",
    "That's a real thing to say.",
    "What's the 'all of this' — the tracking, the whole project, or something else?",
    # The five Finding 1 identity replies that do NOT use a balanced verdict.
    # Same paragraph, same defect class in the report, different construction —
    # so they separate "the identity finding" from "the symmetry finding".
    "No — I'm a fictional composite, built to coach like a real person would.",
    "Not a real person — I'm a fictional composite sleep researcher…",
    "No. I'm a fictional composite coach…",
    "No — I'm a fictional composite built to give you useful career thinking…",
    "No — I'm a fictional AI coach, a composite character…",
    # Finding 4's refusal opener.
    "Let me check that.",
    # Ordinary data statements in the coaches' own register. The comparative
    # pattern has to survive these: "more consistent than last month" compares two
    # measurements, it does not oppose two ideas.
    "Your sleep is more consistent than last month.",
    "I don't have your training data for this week yet.",
    "Hey. Sleep was 7h12m, HRV 58. Solid night.",
]

# ABLATIONS, not quotations — and labelled as such because the distinction is the
# whole reason the fixtures above are quoted. The corpus supplied exactly one
# closing-flourish span, and that one sentence happens to trip THREE of the
# pattern's alternatives at once ("Which…", "either…or", "depending on how"). A
# single fixture like that hides dead alternatives: mutation-testing showed the
# suite stayed green with `^which` disabled, because the other two cues carried
# it. Each entry below is the real span with every cue but one removed, so each
# alternative has to earn its place or a mutation of it goes red.
FLOURISH_ABLATIONS = [
    ("Which is a strange thing to be sure of.", "sentence-initial 'Which' fragment"),
    ("It's either reassuring or unsettling.", "the either/or balanced verdict"),
    ("It reads as progress depending on how you look at it.", "'depending on how you look at it'"),
    ("Not because the number moved, but because the trend held.", "the not-because/but-because pair"),
    ("The trend held, which is why the average matters.", "the mid-sentence 'which is why' tag"),
]

# Judge free-text quoted verbatim from COACH_SIM_FINDINGS. The first two are the
# symmetry theme; the last two are neighbouring themes (attunement, performed
# length variance) that the tell vocabulary must NOT claim credit for.
JUDGE_TELLS_SYMMETRY = [
    "Register asymmetry throughout: Matthew's messages are brief and colloquial, " "while replies are composed, balanced, and explanatory.",
    "…poetic construction that wraps up the advice too neatly; real people don't talk like this unprompted.",
]
JUDGE_TELLS_OTHER_THEMES = [
    "Emotional attunement arrives on perfect cue every time in identical shape: "
    "validate feeling, reframe as information, ask clarifying question.",
    "Fourth reply: extremely brief… but this comes after establishing a pattern of verbose replies; "
    "feels like AI recognizing it should vary length.",
]


# ── The anti-vacuity guard ────────────────────────────────────────────────────


def test_the_labelled_corpus_is_not_empty():
    """A detector test that passes against an empty corpus proves nothing.

    Every count asserted below is stated relative to these n. If a future edit
    empties or thins the fixtures, the assertions would silently become vacuously
    true, so the sizes are pinned first and the counts are pinned to the sizes.
    """
    assert len(REAL_POSITIVES) == 8
    assert len(REAL_NEGATIVES) == 20
    assert len({s for s, _ in REAL_POSITIVES}) == 8, "duplicate positive spans inflate the count"
    assert len(set(REAL_NEGATIVES)) == 20, "duplicate negative spans inflate the count"
    assert all(s.strip() for s, _ in REAL_POSITIVES)
    assert all(s.strip() for s in REAL_NEGATIVES)


# ── Sensitivity: every named class fires on a real span ───────────────────────


@pytest.mark.parametrize("span,expected_class", REAL_POSITIVES, ids=[c for _, c in REAL_POSITIVES])
def test_each_real_positive_fires_its_named_class(span, expected_class):
    hits = csa.balanced_clause_hits(span)
    assert expected_class in hits, f"{expected_class} did not fire on a quoted corpus span: {span!r} (got {sorted(hits)})"
    assert hits[expected_class], "a class present with no matched span is a match that matched nothing"


def test_all_four_new_constructions_are_covered_by_the_fixtures():
    """The acceptance list, asserted as coverage rather than trusted as intent."""
    covered = {cls for _, cls in REAL_POSITIVES}
    assert {"comparative_antithesis", "parallel_construction", "closing_flourish", "x_not_y"} <= covered
    assert set(csa.BALANCED_CLAUSE_CLASSES) == {
        "not_x_but_y",
        "x_not_y",
        "comparative_antithesis",
        "parallel_construction",
        "closing_flourish",
    }


@pytest.mark.parametrize("span,cue", FLOURISH_ABLATIONS, ids=[c for _, c in FLOURISH_ABLATIONS])
def test_each_flourish_cue_carries_the_sentence_on_its_own(span, cue):
    assert "closing_flourish" in csa.balanced_clause_hits(span), f"{cue} is dead weight — the class does not fire without the other cues"


def test_the_flourish_is_scored_on_the_closing_sentence_only():
    """Position is the finding, not the words.

    The judges cited the ENDING — "poetic construction that wraps up the advice
    too neatly". The same construction mid-reply is a thought in passing; at the
    end it is a bow tied on the paragraph. Scoring it anywhere would inflate the
    rate with sentences nobody complained about, so the real flourish span
    followed by a real blunt one must NOT count as a flourish.
    """
    flourish_first = "Which is either reassuring or unsettling depending on how you look at it. Good call. Ship the backend stuff."
    assert "closing_flourish" not in csa.balanced_clause_hits(flourish_first)
    # …and the same two sentences the other way round does count, so the test is
    # proving position rather than proving the sentence stopped matching at all.
    flourish_last = "Good call. Ship the backend stuff. Which is either reassuring or unsettling depending on how you look at it."
    assert "closing_flourish" in csa.balanced_clause_hits(flourish_last)


def test_sensitivity_over_the_whole_positive_set():
    fired = [s for s, _ in REAL_POSITIVES if csa.balanced_clause_hits(s)]
    assert len(fired) == len(REAL_POSITIVES), f"{len(fired)}/{len(REAL_POSITIVES)} quoted positives fired"


# ── Specificity: the human half stays silent ──────────────────────────────────


@pytest.mark.parametrize("span", REAL_NEGATIVES)
def test_real_negatives_stay_silent(span):
    hits = csa.balanced_clause_hits(span)
    assert hits == {}, f"widened detector fired on a quoted negative: {span!r} -> {hits}"


def test_specificity_over_the_whole_negative_set():
    fired = [s for s in REAL_NEGATIVES if csa.balanced_clause_hits(s)]
    assert fired == [], f"{len(fired)}/{len(REAL_NEGATIVES)} quoted negatives false-positived: {fired}"


# ── The widening is the whole point ───────────────────────────────────────────


def test_the_narrow_regex_caught_none_of_these_and_is_still_kept():
    """The measured delta, and the reason the old number stays reported separately.

    0 of the 8 quoted positives match the pre-#2537 regex. That is the 9-in-536
    result reproduced in miniature: the old pattern was not wrong, it was
    answering a narrower question. It is kept — unchanged, still counted under its
    own key — so the widening stays auditable against its own baseline instead of
    being absorbed into a bigger number nobody can decompose.
    """
    old_hits = [s for s, _ in REAL_POSITIVES if csa._NOT_X_BUT_Y.search(s)]
    assert old_hits == [], "fixture drift: these spans are supposed to be the ones the old regex MISSED"
    new_hits = [s for s, _ in REAL_POSITIVES if csa.balanced_clause_hits(s)]
    assert len(new_hits) == 8


def test_the_original_frame_is_not_regressed():
    """The one construction the old regex did catch must still be caught, and named."""
    hits = csa.balanced_clause_hits("It's not a data problem, it's a sleep problem.")
    assert "not_x_but_y" in hits


# ── Through the real entry point ──────────────────────────────────────────────


def _write_corpus(tmp_path, convos):
    """Write JSONL exactly as coach_chat_sim.py does, so load_runs() is the door.

    Hand-building the metric dicts would test a call shape that production does
    not use; the analyzer is entered the way `main()` enters it.
    """
    path = tmp_path / "sleep_coach.jsonl"
    path.write_text("\n".join(json.dumps(c) for c in convos) + "\n")
    return str(tmp_path)


def _convo(scenario_id, coach, replies, coach_name=None):
    return {
        "scenario_id": scenario_id,
        "coach": coach,
        "coach_name": coach_name or coach.replace("_", " ").title(),
        "archetype": "day_in_life",
        "turns": [{"inbound": "how'd I sleep", "reply": r, "status": "sent"} for r in replies],
    }


def test_reply_and_conversation_metrics_carry_the_class(tmp_path):
    run_dir = _write_corpus(
        tmp_path,
        [
            _convo("s1", "sleep_coach", [s for s, _ in REAL_POSITIVES][:4]),
            _convo("s2", "sleep_coach", REAL_NEGATIVES[:4]),
        ],
    )
    convos = csa.load_runs(run_dir)
    assert len(convos) == 2, "load_runs is the real entry point and must see the fixture"

    rows = [csa.conversation_metrics(c) for c in convos]
    flagged, clean = rows[0], rows[1]

    assert flagged["balanced_replies"] == 4, "n=4 quoted positive replies, all four should flag"
    assert flagged["balanced_hits"] >= 4
    assert set(flagged["balanced_classes"]) == {"comparative_antithesis", "parallel_construction", "closing_flourish", "x_not_y"}
    assert clean["balanced_replies"] == 0, f"n=4 quoted negatives should be clean, got {clean['balanced_classes']}"

    # Per-reply attribution survives the rollup — the spans are checkable, not asserted.
    per = flagged["per_turn"][0]
    assert per["balanced_classes"] == ["comparative_antithesis"]
    assert per["balanced_spans"]["comparative_antithesis"], "a claim with no quoted span is not checkable"
    # The old key is untouched.
    assert per["not_x_but_y"] == 0


def test_scenario_id_is_carried_so_the_panel_can_be_joined(tmp_path):
    """Without this the judge tells cannot be used as labels at all."""
    run_dir = _write_corpus(tmp_path, [_convo("archetype::coach::7", "sleep_coach", ["That's signal, not alarm."])])
    row = csa.conversation_metrics(csa.load_runs(run_dir)[0])
    assert row["scenario_id"] == "archetype::coach::7"


def test_empty_conversation_still_reports_zero_not_absent(tmp_path):
    """A zero-turn conversation is a real outcome; it must not KeyError the rollup."""
    run_dir = _write_corpus(tmp_path, [_convo("s0", "sleep_coach", [])])
    row = csa.conversation_metrics(csa.load_runs(run_dir)[0])
    assert row["balanced_replies"] == 0 and row["balanced_classes"] == []


# ── Per-coach reporting + the n floor ─────────────────────────────────────────


def _rollup(tmp_path, convos):
    return [csa.conversation_metrics(c) for c in csa.load_runs(_write_corpus(tmp_path, convos))]


def test_no_per_coach_verdict_below_the_n_floor(tmp_path):
    """Insufficient data is a correct answer; a fabricated 'typical' is not."""
    rows = _rollup(tmp_path, [_convo("s1", "sleep_coach", ["That's signal, not alarm."] * 3)])
    report = csa.symmetry_by_coach(rows)
    assert len(report["coaches"]) == 1
    only = report["coaches"][0]
    assert only["n_replies"] == 3
    assert only["verdict"] is None, "3 replies must not produce a verdict"
    assert "3" in only["reason"] and str(csa.MIN_REPLIES_FOR_COACH_VERDICT) in only["reason"]
    assert report["platform"]["threshold"] is None


def test_per_coach_rates_threshold_and_verdicts(tmp_path):
    """Four coaches, one deliberately symmetric — the outlier must be nameable.

    The reply texts are quoted spans; what is synthetic is only how many of each a
    coach was given, which is what makes the ROLLUP arithmetic checkable. The
    threshold is derived from the measured spread, so a platform where every coach
    is equally symmetric produces no 'elevated' — that is the intended behaviour
    of a relative reading and is asserted rather than assumed.
    """
    pos = [s for s, _ in REAL_POSITIVES]
    convos = [
        # 24 replies, 20 of them symmetric -> rate 0.833
        _convo("hab", "mind_coach", (pos * 3)[:20] + REAL_NEGATIVES[:4]),
        # three coaches at 4/24 -> rate 0.167
        _convo("a", "sleep_coach", pos[:4] + (REAL_NEGATIVES * 3)[:20]),
        _convo("b", "physical_coach", pos[:4] + (REAL_NEGATIVES * 3)[:20]),
        _convo("c", "career_coach", pos[:4] + (REAL_NEGATIVES * 3)[:20]),
    ]
    report = csa.symmetry_by_coach(_rollup(tmp_path, convos))
    by_coach = {r["coach"]: r for r in report["coaches"]}

    assert set(by_coach) == {"mind_coach", "sleep_coach", "physical_coach", "career_coach"}
    assert by_coach["mind_coach"]["n_replies"] == 24 and by_coach["mind_coach"]["n_flagged"] == 20
    assert by_coach["mind_coach"]["rate"] == 0.833
    assert by_coach["sleep_coach"]["rate"] == 0.167

    assert by_coach["mind_coach"]["verdict"] == "elevated"
    assert by_coach["sleep_coach"]["verdict"] == "typical"

    thr = report["platform"]["threshold"]
    assert thr["n_coaches"] == 4, "n is stated on the threshold claim (ADR-105)"
    assert "mean+" in thr["derivation"] and "std" in thr["derivation"]
    assert 0.0 < thr["threshold"] < 0.833

    # Attribution: the class breakdown is per coach, not one undifferentiated number.
    assert set(by_coach["mind_coach"]["by_class"]) <= set(csa.BALANCED_CLAUSE_CLASSES)
    assert sum(by_coach["mind_coach"]["by_class"].values()) >= 20
    assert report["platform"]["n_replies"] == 96


def test_a_uniformly_symmetric_platform_flags_nobody(tmp_path):
    """The honest limit of a relative threshold, asserted so it is never mistaken
    for an absolute one. Every coach at the same rate means no OUTLIER — the
    platform rate, reported alongside, is the number that then matters."""
    pos = [s for s, _ in REAL_POSITIVES]
    convos = [_convo(c, c, (pos * 3)[:24]) for c in ("mind_coach", "sleep_coach", "physical_coach", "career_coach")]
    report = csa.symmetry_by_coach(_rollup(tmp_path, convos))
    assert {r["verdict"] for r in report["coaches"]} == {"typical"}
    assert report["platform"]["rate"] == 1.0, "…and the platform rate says the real thing out loud"


# ── Grading against the judges' own tells ─────────────────────────────────────


def test_the_tell_vocabulary_matches_real_symmetry_tells_and_only_those():
    for tell in JUDGE_TELLS_SYMMETRY:
        assert csa._SYMMETRY_TELL_VOCAB.search(tell), f"real symmetry tell not labelled: {tell!r}"
    for tell in JUDGE_TELLS_OTHER_THEMES:
        assert not csa._SYMMETRY_TELL_VOCAB.search(tell), f"vocabulary claimed a neighbouring theme's tell: {tell!r}"


def _payload(tmp_path, n_symmetric, n_clean):
    pos = [s for s, _ in REAL_POSITIVES]
    convos, panel = [], {}
    for i in range(n_symmetric):
        sid = f"sym-{i}"
        convos.append(_convo(sid, "mind_coach", [pos[i % len(pos)]]))
        panel[sid] = {"coach": "mind_coach", "archetype": "day_in_life", "tells": list(JUDGE_TELLS_SYMMETRY)}
    for i in range(n_clean):
        sid = f"clean-{i}"
        convos.append(_convo(sid, "eli_marsh", [REAL_NEGATIVES[i % len(REAL_NEGATIVES)]]))
        panel[sid] = {"coach": "eli_marsh", "archetype": "terse_close", "tells": list(JUDGE_TELLS_OTHER_THEMES)}
    return {"metrics": _rollup(tmp_path, convos), "panel": panel}


def test_validation_refuses_a_verdict_on_a_thin_join(tmp_path):
    result = csa.validate_against_judge_tells(_payload(tmp_path, 2, 2))
    assert result["verdict"] is None
    assert result["n_conversations_joined"] == 4
    assert str(csa.MIN_REPLIES_FOR_COACH_VERDICT) in result["reason"]


def test_validation_grades_the_join_with_n_stated(tmp_path):
    result = csa.validate_against_judge_tells(_payload(tmp_path, 12, 12))
    assert result["verdict"] == "measured"
    assert result["n_conversations_joined"] == 24
    assert result["n_symmetry_tells"] == 24, "2 symmetry tells x 12 labelled conversations"
    assert result["n_tells"] == 48
    assert result["true_positive"] == 12 and result["false_negative"] == 0
    assert result["false_positive"] == 0 and result["true_negative"] == 12
    assert result["recall_on_labelled"] == 1.0 and result["precision"] == 1.0
    assert result["advisory"] is True


def test_validation_is_none_when_nothing_joins(tmp_path):
    """An unjoinable payload must say so, not report a perfect empty score."""
    payload = _payload(tmp_path, 12, 12)
    payload["panel"] = {f"unknown-{i}": {"tells": []} for i in range(30)}
    result = csa.validate_against_judge_tells(payload)
    assert result["n_conversations_joined"] == 0
    assert result["verdict"] is None


def test_detector_is_advisory_and_never_rewrites():
    """The category line #2555 must not be crossed: this instrument only counts."""
    original = "That's signal, not alarm."
    before = str(original)
    csa.balanced_clause_hits(original)
    assert original == before
    src = open(os.path.join(_ROOT, "scripts", "coach_sim_analyze.py")).read()
    assert "coach_style_gate" not in src, "the advisory detector must not import the mutating enforcer"
