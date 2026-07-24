"""tests/test_prop_grounded_generation.py — property-based (Hypothesis) proofs of the
ADR-104 grounded-generation harness (lambdas/grounded_generation.py), #1664 / epic #1648.

grounded_generation is pure (datetime/json/re only, no AWS/HTTP; the caller supplies
regeneration). These properties prove the honesty invariants over input SPACES:

  * a non-benign number absent from the allow-list is ALWAYS flagged; an allowed or
    benign number is NEVER flagged (fabricated_numbers);
  * text grounded against ITS OWN numbers/dates flags nothing (self-grounding);
  * an invented full calendar date is flagged; the deterministic weekday<->date and
    cycle-freshness (stale baseline / stale "Day N") gates fire exactly on the
    inconsistency and stay silent on the consistent case;
  * regen_once NEVER regresses — a rewrite is kept only if findings strictly decrease.
"""

import datetime as dt
import os
import sys

from hypothesis import assume, given, settings
from hypothesis import strategies as st

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "intelligence"))

import grounded_generation as gg  # noqa: E402

# Non-benign integers: outside range(0,13), the {15,20,30,45,60,90,100} anchors,
# and the 2020..2030 year band. 101..999 contains none of those.
_non_benign_int = st.integers(min_value=101, max_value=999)
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@given(x=_non_benign_int)
@settings(max_examples=200)
def test_ungrounded_non_benign_number_always_flagged(x):
    text = f"The narrative claims a value of {x} here."
    assert float(x) in gg.fabricated_numbers(text, set())
    findings = gg.grounding_findings(text, allowed=set())
    assert any(f["type"] == "fabricated_number" and abs(f["claimed"] - x) < 0.01 for f in findings)


@given(x=_non_benign_int)
@settings(max_examples=200)
def test_number_in_allowlist_never_flagged(x):
    text = f"The narrative claims a value of {x} here."
    assert gg.fabricated_numbers(text, {float(x)}) == []


@given(b=st.sampled_from(sorted(gg._BENIGN_NUMBERS)))
@settings(max_examples=100)
def test_benign_numbers_never_flagged(b):
    # Benign small counts / round anchors / years are grounded even against nothing.
    text = f"There were {b:g} of them in the log."
    assert gg.fabricated_numbers(text, set()) == []


@given(nums=st.lists(st.integers(min_value=1, max_value=9999), min_size=1, max_size=6, unique=True))
@settings(max_examples=150)
def test_self_grounded_numbers_flag_nothing(nums):
    text = "Values: " + ", ".join(str(v) for v in nums) + "."
    assert gg.fabricated_numbers(text, gg.allowed_numbers(text)) == []


@given(d=st.dates(min_value=dt.date(2020, 1, 1), max_value=dt.date(2030, 12, 31)))
@settings(max_examples=200)
def test_invented_iso_date_flagged_and_grounded_date_not(d):
    iso = d.isoformat()
    text = f"The entry is dated {iso} in the record."
    # Against no legitimate dates, the cited date is fabricated.
    assert gg.fabricated_dates(text, set()) == [iso]
    # Once it is in the allow-list (any format), it is grounded.
    assert gg.fabricated_dates(text, {iso}) == []
    # Self-grounding against the text's own dates flags nothing.
    assert gg.fabricated_dates(text, gg.allowed_dates(text)) == []


@given(
    nums=st.lists(st.integers(min_value=1, max_value=9999), min_size=0, max_size=4, unique=True),
    d=st.dates(min_value=dt.date(2020, 1, 1), max_value=dt.date(2030, 12, 31)),
)
@settings(max_examples=150)
def test_grounding_findings_self_grounded_is_empty(nums, d):
    text = "Log " + " ".join(str(v) for v in nums) + f" dated {d.isoformat()}."
    findings = gg.grounding_findings(text, facts=None, allowed=gg.allowed_numbers(text), allowed_dates=gg.allowed_dates(text))
    assert findings == []


@given(d=st.dates(min_value=dt.date(2020, 1, 1), max_value=dt.date(2030, 12, 31)), data=st.data())
@settings(max_examples=200)
def test_weekday_date_consistency(d, data):
    actual_weekday = d.strftime("%A")
    month_name = d.strftime("%B")
    consistent = f"On {actual_weekday}, {month_name} {d.day}, the log updated."
    assert gg.weekday_date_findings(consistent, year=d.year) == []
    # A DIFFERENT stated weekday for the same date is a mismatch finding.
    wrong = data.draw(st.sampled_from([w for w in _WEEKDAYS if w != actual_weekday]))
    inconsistent = f"On {wrong}, {month_name} {d.day}, the log updated."
    findings = gg.weekday_date_findings(inconsistent, year=d.year)
    assert findings and all(f["type"] == "weekday_mismatch" for f in findings)


@given(
    start=st.dates(min_value=dt.date(2024, 1, 1), max_value=dt.date(2028, 12, 31)),
    gap=st.integers(min_value=1, max_value=400),
    day_n=st.integers(min_value=1, max_value=400),
)
@settings(max_examples=200)
def test_pre_start_day_framing_always_stale(start, gap, day_n):
    # generation strictly BEFORE genesis: any "Day N" (N>=1) is stale framing.
    gen = start - dt.timedelta(days=gap)
    text = f"Welcome to Day {day_n} of the experiment."
    findings = gg.baseline_freshness_findings(text, generation_date_iso=gen.isoformat(), start_date_iso=start.isoformat())
    assert any(f["type"] == "stale_phase" for f in findings)


@given(
    start=st.dates(min_value=dt.date(2024, 1, 1), max_value=dt.date(2028, 12, 31)),
    offset=st.integers(min_value=0, max_value=400),
    delta=st.integers(min_value=1, max_value=50),
)
@settings(max_examples=200)
def test_in_experiment_day_framing_exact_match(start, offset, delta):
    gen = start + dt.timedelta(days=offset)
    expected_day = offset + 1  # 1-indexed, matching constants.day_n
    ok_text = f"Today is Day {expected_day}."
    assert not any(
        f["type"] == "stale_phase"
        for f in gg.baseline_freshness_findings(ok_text, generation_date_iso=gen.isoformat(), start_date_iso=start.isoformat())
    )
    wrong_text = f"Today is Day {expected_day + delta}."
    wrong = gg.baseline_freshness_findings(wrong_text, generation_date_iso=gen.isoformat(), start_date_iso=start.isoformat())
    assert any(f["type"] == "stale_phase" for f in wrong)


@given(baseline=st.integers(min_value=150, max_value=400), claimed=st.integers(min_value=150, max_value=400))
@settings(max_examples=200)
def test_stale_baseline_fires_on_disagreement_only(baseline, claimed):
    text = f"His starting weight of {claimed} lb anchors the run."
    findings = gg.baseline_freshness_findings(
        text,
        generation_date_iso="2026-07-24",
        start_date_iso="2026-07-22",
        baseline_lbs=float(baseline),
    )
    stale = [f for f in findings if f["type"] == "stale_baseline"]
    if abs(claimed - baseline) > 1.0:
        assert stale, (claimed, baseline)
    else:
        assert not stale, (claimed, baseline)


@given(n_orig=st.integers(min_value=1, max_value=5), n_fixed=st.integers(min_value=0, max_value=6))
@settings(max_examples=150)
def test_regen_once_never_regresses(n_orig, n_fixed):
    # findings_fn is deterministic per text; regen_fn always yields "fixed".
    # Findings are dict-shaped so correction_prompt() can render them.
    def findings_fn(t):
        count = n_orig if t == "orig" else n_fixed
        return [{"detail": f"finding {i}"} for i in range(count)]

    def regen_fn(_correction):
        return "fixed"

    best, best_findings, corrected = gg.regen_once("orig", findings_fn, regen_fn)
    # Never worse than the original draft.
    assert len(best_findings) <= n_orig
    if n_fixed < n_orig:
        assert corrected and best == "fixed"
    else:
        # No strict improvement => keep the original untouched.
        assert not corrected and best == "orig"


@given(text=st.text(max_size=40))
@settings(max_examples=100)
def test_regen_once_clean_text_is_a_noop(text):
    assume(True)

    def findings_fn(_t):
        return []  # already grounded

    calls = []

    def regen_fn(correction):
        calls.append(correction)
        return "should not be used"

    best, findings, corrected = gg.regen_once(text, findings_fn, regen_fn)
    assert best == text and findings == [] and corrected is False
    assert calls == []  # no wasted regeneration when nothing is wrong
