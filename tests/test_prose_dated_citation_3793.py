"""#3793 — a coach that dates a reading in ENGLISH is not contradicting the cockpit.

The second instance of the #2738 class, and the sole driver of the 2026-09-14
`cross_surface:vitals` FAILs (18:31Z, 20:33Z, 21:19Z, 22:04Z, 22:34Z) that held
`qa-smoke-failures` in ALARM all day:

    "On September 12th, his Whoop recorded 73% recovery, 36.4 ms HRV, and 60 bpm
     resting heart rate — solid single-night readings…"        (Dr. Max Reyes)

Three surfaces, all correct, one red gate:

  * the coach — 73 / 36.42 / 60 is `DATE#2026-09-13` verbatim, whose night IS
    2026-09-12. That label is the platform's own: /api/vitals ships `night_of` =
    as-of minus one day.
  * the cockpit — 63 / 35.07 / 59, `recovery_as_of 2026-09-14`, `night_of
    2026-09-13`. A different night, two days later.
  * the `published_vitals` stamp — 63.0 as-of 2026-09-14, byte-identical to the
    cockpit, so the #2575 finalization-lag path was never reached at all.

`_DATED_SENTENCE` knew a date only as an ISO string or "Day N". A narrative coach
writes prose dates, so a correctly-dated citation was read as a claim about now —
#1985's failure mode, firing on a coach doing exactly what ADR-104 asks of it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambdas"))

from operational import weight_truth_qa as wq  # noqa: E402

# The live 2026-09-14 payload, verbatim from /api/coaching-dashboard.
_REYES_PROSE = (
    "On September 12th, his Whoop recorded 73% recovery, 36.4 ms HRV, and 60 bpm resting heart rate "
    "— solid single-night readings, though I'm treating them as observations rather than trend "
    "signals given…"
)
# The cockpit at the same instant, verbatim from /api/vitals.
_COCKPIT = {"recovery_pct": 63.0, "hrv_ms": 35.1, "rhr_bpm": 59.0, "sleep_hours": 6.3, "recovery_as_of": "2026-09-14"}
# And the stamp every coach carried — the same reading, so it can never be what saves this.
_STAMP = {"recovery_pct": 63.0, "hrv_ms": 35.07, "rhr_bpm": 59.0, "sleep_hours": 6.32, "recovery_as_of": "2026-09-14"}


def test_the_live_2026_09_14_payload_no_longer_fires():
    """The regression proper — all three metrics in one sentence, one prose date."""
    ok, msg = wq.assess_cross_surface_vitals(
        _COCKPIT, [{"name": "Dr. Max Reyes", "position_summary": _REYES_PROSE, "published_vitals": _STAMP}]
    )
    assert ok, msg


def test_the_stamp_is_not_what_rescues_it():
    """The #2575 lag path is unreachable here: stamp and cockpit are the SAME morning,
    so `publication_baseline` returns the cockpit. Without the sentence rule this fails."""
    assert wq.publication_baseline(_COCKPIT, {"published_vitals": _STAMP}, "recovery") == (63.0, "cockpit")


def test_every_metric_in_the_live_sentence_is_exempted_together():
    """Sentence-scoped, so the compound clause that defeated `_ANCHOR_WINDOW_CHARS`
    in #2738 cannot leave one of the three still flagged."""
    assert wq.vitals_cited_in(_REYES_PROSE) == {}


def test_prose_dates_in_both_orders_and_abbreviated():
    for prose in (
        "On September 12th, recovery was 73%.",
        "Sep 12 recovery was 73%.",
        "Sept. 12 recovery was 73%.",
        "Recovery was 73% on 12 September.",
        "Recovery was 73% on the 12th of September.",
    ):
        assert wq.vitals_cited_in(prose) == {}, prose


def test_may_the_modal_verb_cannot_launder_an_undated_figure():
    """`May` is the one month that is also an English modal. It needs an ordinal, a
    year or a date preposition before it counts as a date."""
    assert wq.vitals_cited_in("That may 3% of the time; recovery is 73%.") == {"recovery": [73.0]}
    for prose in ("On May 3 recovery was 73%.", "May 3rd recovery was 73%.", "May 3, 2026 recovery was 73%."):
        assert wq.vitals_cited_in(prose) == {}, prose


def test_a_bare_month_is_still_not_a_date():
    """Narrowness: the exemption is an explicit calendar date, not any month word.
    (`in <month>` AFTER a figure was already `_HISTORICAL_ANCHOR`'s job and stays so.)"""
    assert wq.vitals_cited_in("In September recovery was 73%.") == {"recovery": [73.0]}
    assert wq.vitals_cited_in("Across September your HRV was 35.3 ms.") == {"hrv": [35.3]}


def test_an_undated_stale_claim_still_fails():
    """The half that must not regress — the whole point of the check."""
    ok, msg = wq.assess_cross_surface_vitals(_COCKPIT, [{"name": "Dr. Max Reyes", "position_summary": "Recovery is 73% right now."}])
    assert not ok and "recovery 73" in msg


def test_the_dated_seam_stays_shared_with_weights():
    """`weights_cited_in` and `vitals_cited_in` must not drift on what 'dated' means."""
    assert wq.weights_cited_in("You were 316.3 lbs on September 12th.") == []
    assert wq.weights_cited_in("The latest reading is 316.3 lbs.") == [316.3]
