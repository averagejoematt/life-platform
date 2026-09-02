"""
tests/test_sentinel_scan_structural_3453.py — #3453: accuracy_audit's sentinel
scan must be STRUCTURAL (rendered-value position), never phrase-matched.

Background: the #3324 fix anchored "None"/"null" to whole-string values (common
English/statistics words), but kept "undefined"/"NaN" as a bare substring match on
the premise those two "never occur as innocent English." That premise is FALSE —
the platform's own published prose (`/method/registry/`, ADR-104/105 #1370's
calibration-verdict language, captured live in the 2026-09-01 AXIS-A qa-screenshots
run) reads:

    "...skill is undefined against a degenerate base rate..."
    "An undefined skill (degenerate base rate) is treated as unknown, not as
    unskilled."

Both are deliberate honest statistics prose, not a leak — yet the phrase-matched
scan raised two HIGH findings on them. This is the #2959/#3003/#3199/#3379
suppressor-family rule (structural, never phrase-matched) inverted onto a
DETECTOR, and it failed the same way: `_is_isolated_value` in
tests/accuracy_audit.py replaces the substring check with a position check — a
hit only counts when the token sits adjacent to a label/colon/punctuation/
boundary (a rendered VALUE), never mid-sentence flanked by two ordinary words.

This file is the regression fixture (the exact two false positives, verbatim)
plus the positive/negative controls the #3453 acceptance boxes require.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import accuracy_audit as aa  # noqa: E402

# ── the exact 2026-09-01 false positives, verbatim from lambdas/experiment/methods_registry.py ──

_FALSE_POSITIVE_1 = (
    "None when fewer than 2 pairs or every outcome is identical (skill is undefined "
    "against a degenerate base rate). 1.0 is perfect, 0.0 means no better than always "
    "guessing the observed base rate, negative means worse than that baseline — the "
    "honest 'does stated confidence beat just guessing the average?' number."
)

_FALSE_POSITIVE_2 = (
    "'Well-calibrated' asserts reliability AND skill: a forecaster whose stated "
    "confidence tracks observed rates but whose Brier skill is <= 0 (worse than "
    "always guessing the base rate) reads 'not_yet_skillful' — reliability alone "
    "never earns the flattering verdict (ADR-104/105, #1370). An undefined skill "
    "(degenerate base rate) is treated as unknown, not as unskilled."
)


# ── acceptance box 2: the method-registry false positives are the regression fixture ──


def test_method_registry_false_positives_do_not_fire_via_json_scan():
    findings = aa.scan_json_value_leaks(
        {"stats": [{"limitations": _FALSE_POSITIVE_1}, {"limitations": _FALSE_POSITIVE_2}]},
        "test:/api/methods",
    )
    assert findings == [], f"honest prose must not fire: {findings}"


def test_method_registry_false_positives_do_not_fire_via_rendered_prose_scan(tmp_path):
    """Same two sentences via the rendered-prose (.txt) path `sanity_scan` reads
    for a /review capture — the scope the false positives were actually found in
    (AXIS-A, qa-screenshots/2026-09-01)."""
    run_dir = tmp_path / "run"
    (run_dir / "api").mkdir(parents=True)
    (run_dir / "method-registry.txt").write_text(_FALSE_POSITIVE_1 + "\n\n" + _FALSE_POSITIVE_2)

    findings = aa.sanity_scan(str(run_dir))
    high = [f for f in findings if f["severity"] == "high"]
    assert high == [], f"honest prose must not fire: {high}"


# ── acceptance box 1: never mid-sentence between lowercase words ────────────────


def test_undefined_mid_sentence_between_lowercase_words_is_not_isolated():
    text = "the value is undefined right now on the card"
    idx = text.index("undefined")
    assert not aa._is_isolated_value(text, idx, idx + len("undefined"))


def test_nan_mid_sentence_between_lowercase_words_is_not_isolated():
    text = "the score is NaN this week for that coach"
    idx = text.index("NaN")
    assert not aa._is_isolated_value(text, idx, idx + len("NaN"))


def test_find_leak_matches_skips_mid_sentence_undefined_and_nan():
    assert list(aa._find_leak_matches("the value is undefined right now on the card")) == []
    assert list(aa._find_leak_matches("the score is NaN this week for that coach")) == []


# ── acceptance box 3: positive control — a genuinely rendered leak still reds ────


def test_rendered_undefined_value_still_fires_via_json_scan():
    findings = aa.scan_json_value_leaks({"vitals": {"weight_lbs_display": "undefined"}}, "test:/api/vitals")
    assert findings
    assert findings[0]["where"] == ".vitals.weight_lbs_display"


def test_rendered_undefined_label_adjacent_still_fires_via_json_scan():
    findings = aa.scan_json_value_leaks({"vitals": {"note": "Weight: undefined"}}, "test:/api/vitals")
    assert findings


def test_rendered_undefined_value_still_fires_via_prose_scan(tmp_path):
    """The positive control at the scope the false positives were actually found
    in: a real leak sitting isolated in the rendered page text still reds."""
    run_dir = tmp_path / "run"
    (run_dir / "api").mkdir(parents=True)
    (run_dir / "leaky-page.txt").write_text("Current streak\nundefined\ndays")

    findings = aa.sanity_scan(str(run_dir))
    high = [f for f in findings if f["severity"] == "high"]
    assert high, "a genuinely rendered `undefined` value must still fire"


def test_rendered_nan_value_still_fires_via_prose_scan(tmp_path):
    run_dir = tmp_path / "run"
    (run_dir / "api").mkdir(parents=True)
    (run_dir / "leaky-page.txt").write_text("ACWR score: NaN")

    findings = aa.sanity_scan(str(run_dir))
    high = [f for f in findings if f["severity"] == "high"]
    assert high, "a genuinely rendered `NaN` value must still fire"


def test_object_object_still_fires_mid_sentence():
    """[object Object] keeps its pure-substring match — #3453 doesn't touch it;
    it never occurs as innocent English, brackets included."""
    assert list(aa._find_leak_matches("it rendered [object Object] on the card"))
