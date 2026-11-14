"""tests/test_chapter_summary_2026_11_14.py — a chapter's summary is read off its published body, in whole sentences.

The posts.json excerpt is a fixed 300 characters of the stored envelope; on chapters 0–4 the editor's note used most of
it, so the front page and /story/ showed fragments ("He is down 15 pounds from his first weigh-in in 24…"), and on
Week 10 the dek and the opening paragraph ran together. The episodes feed cuts the same way ("…every time until n").
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from publish_snapshot_chapters import chapter_summary, whole_sentence_summary  # noqa: E402

NOTE = '<p class="signature"><em>Editor\'s note, October 2026 — a reviewer: this installment was rewritten.</em></p>\n'
DEK = '<p class="signature"><em>He is down 15 pounds in 24 days. Protein collapsed late in the week.</em></p>\n'
FILED = '<p class="signature"><em>Day 24 · 327.3 → 312.3 lb · coaches: A 2–0</em></p>\n'
PROSE = "<p>He hiked more than eight miles on Sunday. The scale closed the week at 312.3 pounds.</p>\n"


def test_the_dek_is_the_summary_past_an_editors_note():
    assert chapter_summary(NOTE + DEK + FILED + PROSE) == "He is down 15 pounds in 24 days. Protein collapsed late in the week."


def test_without_a_dek_the_opening_paragraph_and_never_the_filed_line():
    assert chapter_summary(NOTE + FILED + PROSE) == "He hiked more than eight miles on Sunday. The scale closed the week at 312.3 pounds."


def test_a_long_opening_ends_on_a_whole_sentence():
    long = "<p>" + "One short sentence here. " * 30 + "</p>"
    out = chapter_summary(long, limit=100)
    assert out.endswith(".") and len(out) <= 100


def test_no_body_no_summary():
    assert chapter_summary(None) is None and chapter_summary("") is None
    assert chapter_summary(None, "*A served excerpt.*") == "A served excerpt."


def test_a_feed_summary_cut_mid_word_ends_on_its_last_sentence():
    assert whole_sentence_summary("The flag is lit. Webb has been wrong every time until n") == "The flag is lit."
    assert whole_sentence_summary("Day 1 is tomorrow. Eight calls \\\\ \\\\ — on record.") == "Day 1 is tomorrow. Eight calls — on record."
    assert whole_sentence_summary("No ending punctuation at all") == "No ending punctuation at all"


def test_versus_guess_carries_each_kind_as_served_and_never_adds_them():
    from publish_snapshot_chapters import versus_guess

    comp = {
        "records": {
            "number": {"scored": 24, "coach_right_on_scored": 13, "rule_right": 9, "verdict": "no_clear_difference"},
            "direction": {"scored": 6, "coach_right_on_scored": 0, "rule_right": 6, "verdict": "too_few"},
            "yes_no": {"scored": 0, "coach_right_on_scored": 0, "rule_right": 0, "verdict": "none_scored"},
        }
    }
    out = versus_guess(comp)
    assert [k["kind"] for k in out["kinds"]] == ["number", "direction"]  # a kind with nothing scored is left out
    assert out["kinds"][0] == {"kind": "number", "scored": 24, "coach_right": 13, "rule_right": 9, "verdict": "no_clear_difference"}
    assert versus_guess(None) is None and versus_guess({"records": {}}) is None
