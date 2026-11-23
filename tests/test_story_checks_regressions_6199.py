"""tests/test_story_checks_regressions_6199.py — the 2026-11-21 review's two regression cases, as story checks.

* attribution (BLOCKING, ``source:``): "he has said"-style words attributed to him in a week with no words of his on
  record. Keyed on the perfect-tense attribution, so a narrated past ("he said he'd walk") passes.
* activity (ADVISORY, ``craft:``): an activity word no stored session label of the week supports ("hike" for a walk).
  A label can be coarse, so it routes the week to the owner's preview and never holds it.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from content import autopublish_audit, story_checks as C  # noqa: E402

WALKS = {"training": {"strava_walks": [{"date": "2026-12-02", "miles": 2.0}], "cardio_and_walks_whoop": [{"sport": "walking"}]}}


def test_an_attribution_with_no_words_on_record_blocks():
    found = C.attribution_findings("As he has said, the walk is the point. In his own words, it is enough.", [])
    assert len(found) == 2 and all(f.startswith("source:") for f in found)
    assert not autopublish_audit.is_style_finding(found[0]), "a source finding is never a craft note"


def test_an_attribution_with_his_words_on_record_or_a_narrated_past_passes():
    assert C.attribution_findings("As he has said, the walk is the point.", ["I walk because it clears my head."]) == []
    assert C.attribution_findings("He said he would walk after dinner, and he did.", []) == []
    assert C.attribution_findings("A clean week, told plainly.", None) == [], "no attribution, nothing to check"


def test_all_findings_never_skips_the_attribution_check_silently():
    md = "As he has said, the walk is the point."
    assert any(f.startswith("source:") for f in C.all_findings(md, stop_reason="end_turn", allowed=set(), owner_lines=[]))
    # #6216: a caller that does not pass the record gets the distinguishable finding, not silence
    assert any("attribution evidence unavailable" in f for f in C.all_findings(md, stop_reason="end_turn", allowed=set()))


def test_a_hike_for_a_walk_is_an_advisory_note():
    found = C.activity_word_findings("On Sunday he hiked for an hour.", WALKS)
    assert len(found) == 1 and found[0].startswith("craft:") and autopublish_audit.is_style_finding(found[0])


def test_the_legacy_hiking_label_is_a_walk_and_a_vendor_hiking_label_is_a_hike():
    legacy = {"training": {"cardio_and_walks_whoop": [{"sport": "Hiking"}]}}
    assert C.activity_word_findings("He hiked on Sunday.", legacy)
    vendor = {"training": {"cardio_and_walks_whoop": [{"sport": "hiking/rucking"}]}}
    assert C.activity_word_findings("He hiked on Sunday.", vendor) == []


def test_plain_walking_prose_raises_nothing():
    assert C.activity_word_findings("He walked every morning and lifted twice.", WALKS) == []
    assert C.activity_word_findings("He ran the numbers on Sunday.", WALKS) == []
