"""#2738 — a coach that DATES a reading is not contradicting today's cockpit.

The live 2026-08-15 `cross_surface:vitals` FAIL, and the sole driver of that night's
alarmed FailCount:

    "I can see your wearables—Whoop caught 40% recovery and 35.3 ms HRV on the night
     of 2026-08-13—but MacroFactor has been blank for four days."

40 / 35.32 IS the 2026-08-14 morning reading (the night of 08-13) — confirmed against
the `published_vitals` stamps two other coaches were still carrying that day. The coach
named the night it was talking about, which is exactly the provenance ADR-104 asks for,
and the check called it a contradiction with the live cockpit.

`_HISTORICAL_ANCHOR` was already the escape hatch for this and missed it three ways:
the vocabulary lacked the phrasing, it is forward-only and anchored at offset 0 (so a
date BEFORE the figure can never match), and its 24-char window cannot span a compound
clause. Hence a SENTENCE-scoped rule, in the same idiom as `_VITALS_TARGET_SENTENCE`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambdas"))

from operational import weight_truth_qa as wq  # noqa: E402

# The live payload, verbatim.
_WEBB_PROSE = (
    "I can see your wearables—Whoop caught 40% recovery and 35.3 ms HRV on the night "
    "of 2026-08-13—but MacroFactor has been blank for four days."
)
_COCKPIT = {"recovery_pct": 57.0, "hrv_ms": 39.8, "rhr_bpm": 61.0, "sleep_hours": 8.8}


def test_the_live_2026_08_15_payload_no_longer_fires():
    """The regression proper."""
    ok, msg = wq.assess_cross_surface_vitals(_COCKPIT, [{"name": "Dr. Marcus Webb", "position_summary": _WEBB_PROSE}])
    assert ok, msg


def test_a_date_after_the_figure_across_a_compound_clause():
    """Gap 3: recovery's 24-char forward window here is ' and 35.3 ms HRV on the n',
    so the adjacent-anchor check could never have saved it even with the right words."""
    assert wq.vitals_cited_in(_WEBB_PROSE) == {}


def test_a_date_before_the_figure():
    """Gap 2: `_HISTORICAL_ANCHOR` only ever looked FORWARD from the figure."""
    assert wq.vitals_cited_in("On 2026-08-13, recovery was 40% and HRV was 35.3 ms.") == {}


def test_an_undated_stale_claim_still_fails():
    """The half that must NOT regress — this is the whole point of the check."""
    ok, msg = wq.assess_cross_surface_vitals(
        _COCKPIT, [{"name": "Dr. Marcus Webb", "position_summary": "Recovery is 40% today and HRV sits at 35.3 ms."}]
    )
    assert not ok
    assert "recovery 40" in msg


def test_last_night_is_a_CURRENT_claim_not_a_historical_one():
    """A whoop morning IS last night's sleep. The first draft of the sentence rule
    listed 'last night' as a historical anchor, which would have blinded the sleep
    check entirely; tests/test_genesis_week_coach_vitals_2113.py caught it."""
    assert wq.vitals_cited_in("You slept 6.1 hours last night.") == {"sleep": [6.1]}
    ok, msg = wq.assess_cross_surface_vitals(_COCKPIT, [{"name": "Dr. Lisa Park", "position_summary": "You slept 6.1 hours last night."}])
    assert not ok and "sleep 6.1" in msg


def test_the_dated_escape_hatch_is_one_seam_shared_with_weights():
    """`weights_cited_in` and `vitals_cited_in` must not drift apart on what 'dated' means."""
    assert wq.weights_cited_in("You were 316.3 lbs on 2026-06-01.") == []
    assert wq.weights_cited_in("The latest reading is 316.3 lbs.") == [316.3]


def test_a_bare_backward_hint_is_not_enough():
    """Narrowness check: only an EXPLICIT calendar date (or Day N) exempts. Vague
    past-tense framing must still be judged as a present-tense claim, or the gate
    becomes trivially evadable."""
    assert wq.vitals_cited_in("Earlier, recovery was 40%.") == {"recovery": [40.0]}
    assert wq.vitals_cited_in("Recently your HRV was 35.3 ms.") == {"hrv": [35.3]}
