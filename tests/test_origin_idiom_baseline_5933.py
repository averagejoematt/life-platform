"""#5933 (aiq-1, /review full 2026-11-13) — the baseline gate must read the ORIGIN idiom.

`stale_baseline` matched framing WORDS ("starting weight", "started at"). The 2026-10-31
weekly read said "brought him from 305 lbs to 296.1 lbs": 305 was a real mid-cycle weigh-in
(so the number gate passed it) and the sentence carried no framing word (so this gate never
looked), yet an unlabelled "from X" reads as where the journey started — 22 lb higher.

Three things are pinned, each as ONE test that iterates and reports every offender:
  * every origin form the issue names fails when X is not the journey start;
  * the same forms PASS when X is the journey start (the false-positive guard), and so do
    a labelled window, a lift, and a figure that is not a body weight;
  * a "window" as long as the journey, or anchored on the genesis, is not a window.

The frozen specimen itself lives in tests/grounding_corpus/ and is replayed by
tests/test_grounding_corpus_3614.py. No clock: every date is an argument.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from ai import grounded_generation as gg  # noqa: E402

BASELINE = 327.3
START = "2026-09-06"
GEN = "2026-11-13"  # day 69
ALLOWED = {327.3, 327.0, 296.1, 305.4, 305.0, 3.9, 185.0, 225.0, 20.0, 31.0, 13.0, 17.0, 6.0}


def _stale(text, gen=GEN):
    findings = gg.grounding_findings(
        text, facts=None, allowed=ALLOWED, baseline_lbs=BASELINE, generation_date_iso=gen, start_date_iso=START
    )
    return [f for f in findings if f["type"] == "stale_baseline"]


MUST_FAIL = [
    # the four framings the issue names
    "He went from 305 lbs to 296.1 lbs since the experiment began.",
    "He is down from 305.4 lbs to 296.1 lbs.",
    "His weight has fallen from 305.4 lbs to 296.1 lbs since the experiment began.",
    "A 3.9 lb per week fat loss has brought him from 305 lbs to 296.1 lbs.",
    # neighbours of the same shape
    "He has dropped from 305.4 pounds, and the trend is holding.",
    "The scale moved from 305.4 to 296.1 lbs.",
    "From roughly 305 pounds down to 296.1 pounds: that is the story.",
]

MUST_PASS = [
    # the journey-start figure, in every one of the same forms
    "He went from 327.3 lbs to 296.1 lbs since the experiment began.",
    "He is down from 327.3 lbs to 296.1 lbs.",
    "His weight has fallen from 327 lbs to 296.1 lbs since the experiment began.",
    "A 3.9 lb per week fat loss has brought him from 327.3 lbs to 296.1 lbs.",
    # a labelled window is an honest claim about that window (#4547)
    "Over the last two weeks he has gone from 305.4 lbs to 296.1 lbs.",
    "Since October 13 he is down from 305.4 lbs to 296.1 lbs.",
    "In 17 days the scale moved from 305.4 lbs to 296.1 lbs.",
    # a load, and a figure that is not a body weight
    "His deadlift went from 185 lbs to 225 lbs.",
    "Total loss went from 20 lbs to 31 lbs.",
    # no origin claim at all
    "He weighs 296.1 lbs this morning.",
]

NOT_A_WINDOW = [
    # day 69: ten weeks is the whole journey; the genesis date and "Day 1" are its start
    "In the last ten weeks he went from 305.4 lbs to 296.1 lbs.",
    "Since September 6 he is down from 305.4 lbs to 296.1 lbs.",
    "Since Day 1 he is down from 305.4 lbs to 296.1 lbs.",
    "Over the last two weeks of the experiment overall he fell from 305.4 lbs to 296.1 lbs.",
]


def test_every_origin_form_is_checked_against_the_journey_start():
    missed = [t for t in MUST_FAIL if not _stale(t)]
    assert not missed, f"the origin idiom walked through stale_baseline: {missed}"
    f = _stale(MUST_FAIL[3])[0]
    assert f["claimed"] == 305.0 and f["expected"] == 327.3 and f["framing"] == "origin"
    assert "Use 327.3 lb" in gg.correction_prompt([f]), "the corrective rewrite must be handed the real start"


def test_the_journey_start_a_labelled_window_and_a_lift_all_pass():
    tripped = {t: _stale(t) for t in MUST_PASS if _stale(t)}
    assert not tripped, f"the origin class is over-firing: {tripped}"


def test_a_window_as_long_as_the_journey_is_not_a_label():
    slipped = [t for t in NOT_A_WINDOW if not _stale(t)]
    assert not slipped, f"a whole-journey span was accepted as a window label: {slipped}"
    # the same ten-week span IS a window once the journey is longer than it (day 100)
    assert _stale(NOT_A_WINDOW[0], gen="2026-12-14") == []


def test_one_weight_is_reported_once_across_both_framings():
    # "started from" (the word class) and "from X to Y" (the origin class) both see 305.4
    assert len(_stale("He started from 305.4 lbs to 296.1 lbs.")) == 1
