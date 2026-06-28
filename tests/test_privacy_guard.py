"""Tests for privacy_guard — the deterministic real-name + vice gate."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import privacy_guard as pg  # noqa: E402


def test_clean_text_passes():
    txt = "Dr. Marcus Webb reviewed the protein numbers; Dr. Amara Patel flagged the micronutrients."
    assert pg.is_clean(txt)
    assert pg.find_violations(txt) == []
    assert pg.assert_clean(txt) == txt  # returns text, no raise


def test_real_full_name_blocked():
    v = pg.find_violations("I called Dr. Layne Norton about the cut.")
    assert ("real_name", "layne norton") in v
    try:
        pg.assert_clean("I called Dr. Layne Norton about the cut.")
        assert False, "should have raised"
    except pg.PrivacyViolation:
        pass


def test_real_surname_blocked():
    assert not pg.is_clean("As Goggins would say, push harder.")
    assert not pg.is_clean("Huberman's protocol")
    assert not pg.is_clean("per Attia")


def test_vice_blocked():
    assert not pg.is_clean("the no-marijuana streak held")
    assert not pg.is_clean("cut out cannabis")
    assert not pg.is_clean("avoiding pornography")


def test_subject_name_not_a_false_positive():
    # The subject IS Matthew Walker — bare "Walker" / "Matthew Walker" must stay clean.
    assert pg.is_clean("Matthew Walker logged his weight; Walker trained twice.")
    # but the disambiguated sleep-scientist forms are caught
    assert not pg.is_clean("as sleep scientist Dr. Matthew Walker notes")


def test_common_words_not_false_positives():
    # "clear", "patrick", "patel", "cole" should NOT trip (ambiguous → only full names banned)
    assert pg.is_clean("the plan is clear and the path is patrick-free")  # 'patrick' alone is allowed
    assert pg.is_clean("a clear improvement in recovery")


def test_scrub_redacts_inline():
    out, n = pg.scrub("Goggins says marijuana is fine")
    assert n >= 2
    assert "Goggins" not in out and "marijuana" not in out
    assert "[redacted]" in out


def test_stale_draft_detection():
    assert pg.is_stale_draft("2026-06-01")  # older than GUARD_VERSION
    assert pg.is_stale_draft(None)
    assert not pg.is_stale_draft(pg.GUARD_VERSION)
    assert not pg.is_stale_draft("2099-01-01")
