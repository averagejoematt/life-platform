"""tests/test_er03_gate.py — CC-08 ER-03 truthfulness gate.

Proves the gate is fail-closed on the four banned classes (fabricated number,
causal connective, unhedged small-N claim, Matthew-prefix) and passes clean,
correctly-framed reflections.
"""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import er03_gate  # noqa: E402


def test_clean_correlative_text_passes():
    txt = "Early days, but sleep and recovery appear to move together — a trend worth watching, not proof."
    ok, reasons = er03_gate.er03_check(txt, allowed_numbers=set(), n=5)
    assert ok, reasons


def test_fabricated_number_fails():
    # 42 is not in the input numbers -> fabrication
    ok, reasons = er03_gate.er03_check("Recovery rose to 42 this week (early signal).", allowed_numbers={7, 8}, n=5)
    assert not ok and any("fabricated" in r for r in reasons)


def test_number_present_in_input_passes():
    ok, reasons = er03_gate.er03_check("So far, around 7 hours of sleep is the early trend.", allowed_numbers={7}, n=5)
    assert ok, reasons


def test_causal_connective_fails():
    ok, reasons = er03_gate.er03_check("Your sleep improved because you trained harder.", allowed_numbers=set(), n=50)
    assert not ok and any("causal" in r for r in reasons)


def test_unhedged_small_n_fails():
    # confident claim, small N, no hedge word
    ok, reasons = er03_gate.er03_check("Sleep and HRV are clearly linked.", allowed_numbers=set(), n=4)
    assert not ok and any("unhedged" in r for r in reasons)


def test_large_n_needs_no_hedge():
    ok, reasons = er03_gate.er03_check("Sleep and HRV are linked across the record.", allowed_numbers=set(), n=120)
    assert ok, reasons


def test_matthew_prefix_fails():
    ok, reasons = er03_gate.er03_check("Matthew, your trend looks early but promising.", allowed_numbers=set(), n=5)
    assert not ok and any("Matthew" in r or "opening" in r for r in reasons)


def test_numbers_in_extractor():
    assert er03_gate.numbers_in("7 hours, 0.8 ratio, and 12%") == {7.0, 0.8, 12.0}
