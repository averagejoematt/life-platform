"""tests/test_prop_er03_gate.py — property-based (Hypothesis) proofs of the ER-03
offline truthfulness gate (lambdas/er03_gate.py), #1664 / epic #1648.

er03_gate is a genuinely pure module (import re only — no AWS, no clock, no I/O),
so its honesty invariants can be proven over input SPACES rather than the handful
of examples in tests/test_er03_gate.py. The load-bearing invariants here are the
honesty ones: an ungrounded number ALWAYS can flag, a grounded one NEVER flags for
fabrication, a banned causal connective always flags, and the small-N hedge rule
is symmetric (an unhedged small-N claim flags; adding a hedge clears exactly that).
"""

import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import er03_gate  # noqa: E402

# A clean, correlative, hedge-free, number-free, non-causal base sentence that does
# not start with "Matthew". Verified against BANNED_CAUSAL and HEDGES below.
_CLEAN_BASE = "Sleep and recovery moved in tandem this stretch of the log."


def _clean_base_is_actually_clean():
    low = _CLEAN_BASE.lower()
    assert not any(er03_gate._has(low, p) for p in er03_gate.BANNED_CAUSAL)
    assert not any(er03_gate._has(low, h) for h in er03_gate.HEDGES)
    assert not er03_gate.numbers_in(_CLEAN_BASE)


_clean_base_is_actually_clean()


@given(blank=st.sampled_from(["", "   ", "\n\t ", "\r\n"]))
@settings(max_examples=25)
def test_empty_text_always_fails(blank):
    ok, reasons = er03_gate.er03_check(blank, allowed_numbers={1, 2, 3}, n=100)
    assert ok is False
    assert reasons == ["empty"]


@given(x=st.integers(min_value=1, max_value=99999))
@settings(max_examples=200)
def test_ungrounded_number_always_can_flag(x):
    # Against an EMPTY allow-list, any number in the output is ungrounded and MUST
    # be reported as a fabrication — the anti-fabrication invariant.
    ok, reasons = er03_gate.er03_check(f"The reading landed at {x} for the window.", allowed_numbers=set(), n=None)
    assert ok is False
    assert any("fabricated number" in r for r in reasons)


@given(nums=st.lists(st.integers(min_value=1, max_value=99999), min_size=1, max_size=5, unique=True))
@settings(max_examples=200)
def test_grounded_numbers_never_flag_fabrication(nums):
    # Every number in the output appears in allowed_numbers => no fabrication reason.
    text = "The readings were " + ", ".join(str(v) for v in nums) + " across the window."
    ok, reasons = er03_gate.er03_check(text, allowed_numbers=set(nums), n=None)
    assert not any("fabricated number" in r for r in reasons)


@given(phrase=st.sampled_from(er03_gate.BANNED_CAUSAL))
@settings(max_examples=100)
def test_banned_causal_connective_always_flags(phrase):
    # A correlative reflection may never assert causation. Any banned connective
    # in the text is a hard fail with a "causal connective" reason.
    text = f"Recovery {phrase} sleep across the window."
    ok, reasons = er03_gate.er03_check(text, allowed_numbers=set(), n=None)
    assert ok is False
    assert any("causal connective" in r for r in reasons)


@given(n=st.integers(min_value=0, max_value=29), hedge=st.sampled_from(er03_gate.HEDGES))
@settings(max_examples=200)
def test_small_n_unhedged_flags_and_hedge_clears(n, hedge):
    # Small-sample claim with no hedge => the unhedged reason fires.
    ok_bare, reasons_bare = er03_gate.er03_check(_CLEAN_BASE, allowed_numbers=set(), n=n)
    assert any("unhedged" in r for r in reasons_bare)
    # Adding a confidence/hedge word clears EXACTLY that reason.
    hedged = _CLEAN_BASE + f" {hedge}"
    ok_h, reasons_h = er03_gate.er03_check(hedged, allowed_numbers=set(), n=n)
    assert not any("unhedged" in r for r in reasons_h)


@given(n=st.integers(min_value=30, max_value=100000))
@settings(max_examples=100)
def test_large_n_never_requires_hedge(n):
    # At N >= 30 the hedge requirement does not apply, hedged or not.
    ok, reasons = er03_gate.er03_check(_CLEAN_BASE, allowed_numbers=set(), n=n)
    assert not any("unhedged" in r for r in reasons)


@given(nums=st.lists(st.integers(min_value=0, max_value=99999), min_size=0, max_size=6, unique=True))
@settings(max_examples=200)
def test_numbers_in_extracts_exactly_the_cited_integers(nums):
    text = " ".join(str(v) for v in nums)
    assert er03_gate.numbers_in(text) == {round(float(v), 4) for v in nums}
