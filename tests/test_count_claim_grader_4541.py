"""tests/test_count_claim_grader_4541.py — a count claim is graded by COUNTING (#4541).

`pred_20260906_sleep_duration_will_consistently_reach_o` (mind coach, pre-registered) said
"Sleep duration will consistently reach or exceed the 7.5-hour target ... on at least 5 of
the first 7 nights". It was stored with a `directional` spec and graded CONFIRMED by the EWMA
slope (0.0603) while only 3 of the 7 nights reached 7.5 h. These tests pin:

  * the parser — the sentence reads into (K, N, metric, comparator, threshold), and every
    ambiguous variant reads into NOTHING (not graded, with the reason);
  * the counting rule — 3 of 7 refuted, exactly 5 of 7 confirmed, a missing day is never a
    miss and never a hit;
  * the wire — the real Whoop nights, run through `_evaluate_all`, come out REFUTED on a
    count of 3; and the MUTATION CONTROL — the same fixture with the count route removed is
    graded CONFIRMED by slope, so the fixture really does reproduce the bug.

Every expected number is hand-derived from the values in the fixture, never read back.
"""

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform")

from coach import (
    coach_prediction_evaluator as ev,  # noqa: E402
    prediction_count_grader as cg,  # noqa: E402
)

ISSUE_SENTENCE = (
    "Sleep duration will consistently reach or exceed the 7.5-hour target (bed 9:00 PM, wake 4:30 AM) on at least 5 of "
    "the first 7 nights, as the fixed schedule removes decision fatigue and the structured ramp discipline reduces "
    "late-night training stress that would otherwise delay sleep onset."
)
ISSUE_SPEC = {"type": "directional", "metric": "sleep_duration_hours", "condition": "up", "threshold": None, "evaluation_window_days": 7}

# The live Whoop rows (USER#matthew#SOURCE#whoop, phase=experiment), read 2026-10-09. Whoop keys a
# night by its wake date. Window 09-06..09-12: 7.93, 8.37 and 8.76 reach 7.5 — 3 of 7 (7.46 does not).
WHOOP_SLEEP_HOURS = {
    "2026-09-06": 7.93,
    "2026-09-07": 8.37,
    "2026-09-08": 6.78,
    "2026-09-09": 6.48,
    "2026-09-10": 7.46,
    "2026-09-11": 4.70,
    "2026-09-12": 8.76,
    "2026-09-13": 8.98,
    "2026-09-14": 6.32,
    "2026-09-15": 9.00,
    "2026-09-16": 6.28,
    "2026-09-17": 6.97,
    "2026-09-18": 7.91,
    "2026-09-19": 8.61,
}
GRADED_ON = "2026-09-19"  # the day the live row was graded (outcome_date)


def _issue_pred(sentence=ISSUE_SENTENCE, spec=None):
    return {
        "pk": "COACH#mind_coach",
        "sk": "PREDICTION#pred_20260906_sleep_duration_will_consistently_reach_o",
        "prediction_id": "pred_20260906_sleep_duration_will_consistently_reach_o",
        "coach_id": "mind_coach",
        "subdomain": "sleep",
        "created_date": "2026-09-06",
        "status": "pending",
        "claim_natural": sentence,
        "evaluation": dict(spec or ISSUE_SPEC),
    }


def _rows(values):
    return [{"sk": f"DATE#{d}", "date": d, "sleep_duration_hours": v} for d, v in sorted(values.items()) if v is not None]


def _grade(values, sentence=ISSUE_SENTENCE, spec=None, today=GRADED_ON):
    """Run cg.grade over a fake source read that serves `values` (date -> hours | None)."""

    def get_source_data(source, data_cache, end_date, lookback_days=30, include_pilot=False):
        assert source == "whoop"
        return _rows(values)

    pred = _issue_pred(sentence, spec)
    return cg.grade(pred, pred["evaluation"], {}, today, get_source_data, ev._extract_metric_series)


def _week(*hours):
    return {f"2026-09-{6 + i:02d}": h for i, h in enumerate(hours)}


# ── the parser ────────────────────────────────────────────────────────────────


class TestParser:
    def test_the_issue_sentence_parses_into_the_five_parts(self):
        claim, why = cg.parse_count_claim(ISSUE_SENTENCE, "sleep_duration_hours")
        assert why == ""
        assert (claim["rule"], claim["k"], claim["n"], claim["metric"], claim["comparator"], claim["threshold"]) == (
            "at_least",
            5,
            7,
            "sleep_duration_hours",
            "gte",
            7.5,
        )

    def test_the_issue_title_phrasing_reads_over_as_strictly_greater(self):
        claim, why = cg.parse_count_claim("Sleep duration: at least 5 of 7 nights over 7.5 h", "sleep_duration_hours")
        assert why == "" and claim["comparator"] == "gt" and claim["threshold"] == 7.5 and (claim["k"], claim["n"]) == (5, 7)

    def test_every_one_of_the_first_n_days_is_all_n(self):
        s = "Daily step count will remain at or above 6,000 steps on every one of the first 14 days."
        claim, why = cg.parse_count_claim(s, "steps")
        assert why == "" and (claim["k"], claim["n"], claim["comparator"], claim["threshold"]) == (14, 14, "gte", 6000.0)

    def test_a_clock_time_is_not_a_threshold(self):
        # "bed 9:00 PM, wake 4:30 AM" sits in the issue sentence; only 7.5 may be read.
        claim, _ = cg.parse_count_claim(ISSUE_SENTENCE, "sleep_duration_hours")
        assert claim["threshold"] == 7.5

    @pytest.mark.parametrize(
        "sentence,metric,needle",
        [
            ("Sleep duration will exceed 7.5 hours on 5 of 7 nights.", "sleep_duration_hours", "no bound"),
            ("Sleep duration will reach 7.5 hours on approximately 5 of 7 nights.", "sleep_duration_hours", "approximately"),
            ("Sleep duration will reach or exceed 7.5 hours on at least 5 out of every 7 nights.", "sleep_duration_hours", "rate"),
            ("Sleep duration will reach or exceed 7.5 hours on at least 5 of 7 logged nights.", "sleep_duration_hours", "logged"),
            (
                "Sleep duration will reach or exceed 7.5 hours on at least 5 of 7 nights in the first 14 days.",
                "sleep_duration_hours",
                "disagrees",
            ),
            ("Sleep duration will be good on at least 5 of the first 7 nights.", "sleep_duration_hours", "no per-day threshold"),
            (
                "Sleep duration will exceed 7 hours and stay under 9 hours on at least 5 of the first 7 nights.",
                "sleep_duration_hours",
                "more than one threshold",
            ),
            ("Eating window held on at least 5 of the first 7 days, at or above 8 hours.", "sleep_duration_hours", "names"),
            ("Sleep duration will reach or exceed 450 minutes on at least 5 of the first 7 nights.", "sleep_duration_hours", "unit"),
        ],
    )
    def test_an_ambiguous_sentence_parses_into_nothing_with_a_reason(self, sentence, metric, needle):
        assert cg.is_count_shaped(sentence)
        claim, why = cg.parse_count_claim(sentence, metric)
        assert claim is None
        assert needle in why

    def test_a_sentence_with_no_count_clause_is_not_count_shaped(self):
        assert not cg.is_count_shaped("Sleep duration will trend up over the next two weeks.")
        assert not cg.is_count_shaped("Three of the five consecutive points will diverge.")


# ── the counting rule ─────────────────────────────────────────────────────────


class TestCountingRule:
    def test_the_issue_case_three_of_seven_is_refuted(self):
        r = _grade(WHOOP_SLEEP_HOURS)
        assert r["status"] == "refuted"
        assert r["actual_value"] == 3  # 7.93, 8.37, 8.76
        assert r["beats_null"] is False
        assert "slope" not in r["reason"]
        assert "on 3 of 7 days 2026-09-06..2026-09-12" in r["reason"]

    def test_exactly_five_of_seven_is_confirmed(self):
        r = _grade(_week(7.5, 8.0, 6.0, 7.6, 5.0, 9.0, 7.5))  # 7.5 counts: the claim says "reach or exceed"
        assert (r["status"], r["actual_value"], r["beats_null"]) == ("confirmed", 5, True)

    def test_four_of_seven_is_refuted(self):
        r = _grade(_week(7.5, 8.0, 6.0, 7.49, 5.0, 9.0, 7.5))
        assert (r["status"], r["actual_value"]) == ("refuted", 4)

    def test_a_missing_day_that_could_decide_it_leaves_the_claim_undecided(self):
        # 4 qualify, 1 missing, 2 miss: the missing night alone decides 5-of-7 either way.
        r = _grade(_week(8.0, 8.0, None, 8.0, 6.0, 8.0, 6.0))
        assert (r["status"], r["actual_value"]) == ("inconclusive", 4)
        assert "1 day(s) missing" in r["reason"]

    def test_missing_days_cannot_rescue_a_count_that_is_already_short(self):
        # 2 qualify + 2 missing = at most 4 < 5.
        r = _grade(_week(8.0, None, 6.0, 8.0, None, 6.0, 6.0))
        assert (r["status"], r["actual_value"]) == ("refuted", 2)

    def test_missing_days_do_not_block_a_count_that_is_already_met(self):
        r = _grade(_week(8.0, 8.0, None, 8.0, 8.0, None, 8.0))
        assert (r["status"], r["actual_value"]) == ("confirmed", 5)

    def test_days_after_today_are_missing_not_misses(self):
        r = _grade(WHOOP_SLEEP_HOURS, today="2026-09-09")  # 4 of 7 days observed: 7.93, 8.37 qualify
        assert r["status"] == "inconclusive"
        assert "3 day(s) missing" in r["reason"]

    def test_at_most_is_counted_from_the_other_side(self):
        claim = {"rule": "at_most", "k": 1, "comparator": "lt", "threshold": 6.0}
        days = [(str(i), v) for i, v in enumerate([5.0, 7.0, 7.0, None])]
        assert cg.count_verdict(claim, days)["status"] == "inconclusive"  # 1 qualifies (<= 1) but the missing day could make it 2
        days = [(str(i), v) for i, v in enumerate([5.0, 7.0, 7.0, 7.0])]
        assert cg.count_verdict(claim, days)["status"] == "confirmed"
        days = [(str(i), v) for i, v in enumerate([5.0, 5.0, 5.0, 7.0])]
        assert cg.count_verdict(claim, days)["status"] == "refuted"


# ── routing: never slope ──────────────────────────────────────────────────────


class TestRouting:
    def test_an_unparseable_count_sentence_is_not_graded_and_never_falls_back_to_slope(self):
        r = _grade(WHOOP_SLEEP_HOURS, sentence="Sleep duration will be solid on 5 of the first 7 nights.")
        assert r["status"] == "inconclusive"
        assert r["reason"].startswith(cg.NOT_GRADED_PREFIX)
        assert r["actual_value"] is None and r["beats_null"] is False

    def test_a_non_count_claim_is_left_to_the_existing_graders(self):
        assert _grade(WHOOP_SLEEP_HOURS, sentence="Sleep duration will trend upward over the next week.") is None

    def test_a_qualitative_row_is_never_promoted_into_a_verdict(self):
        assert _grade(WHOOP_SLEEP_HOURS, spec={"type": "qualitative"}) is None

    def test_a_conditional_count_claim_is_held_not_graded(self):
        r = _grade(WHOOP_SLEEP_HOURS, spec=dict(ISSUE_SPEC, type="conditional"))
        assert r["status"] == "inconclusive" and r["reason"].startswith(cg.NOT_GRADED_PREFIX)


# ── the wire through _evaluate_all, with the mutation control ─────────────────


@pytest.fixture
def evaluator_io(monkeypatch):
    """The evaluator over the live Whoop rows, with every write captured instead of sent."""
    written = {"status": [], "bayes": [], "learning": [], "stamp_specs": []}

    def fetch_range(source, start, end, include_pilot=False):
        assert source == "whoop"
        return [r for r in _rows(WHOOP_SLEEP_HOURS) if start <= r["date"] <= end]

    def stamp(pred, spec, result, status, *a, **k):
        written["stamp_specs"].append(spec)
        return None

    monkeypatch.setattr(ev, "_fetch_range", fetch_range)
    monkeypatch.setattr(ev, "_update_prediction_status", lambda p, e, b=None: written["status"].append(e))
    monkeypatch.setattr(ev, "_update_bayesian_confidence", lambda c, s, u: written["bayes"].append((c, s, u)))
    monkeypatch.setattr(ev, "_write_learning_record", lambda c, t, e: written["learning"].append(e))
    monkeypatch.setattr(ev.coach_baseline, "stamp_at_grading", stamp)
    return written


def test_the_live_row_is_refuted_by_its_count_through_the_evaluator(evaluator_io):
    evaluations, stats = ev._evaluate_all([_issue_pred()], GRADED_ON)
    (e,) = evaluations
    assert (e["status"], e["actual_value"], e["evaluation_type"]) == ("refuted", 3, "count")
    assert (e["metric"], e["condition"], e["threshold"]) == ("sleep_duration_hours", "gte", 7.5)
    assert e["bayesian_update"] == "failure"
    assert evaluator_io["bayes"] == [("mind_coach", "sleep", "failure")]
    assert stats["refuted"] == 1 and stats["confirmed"] == 0
    # The #4585 baseline rule is not asked to judge a count as a direction call.
    assert evaluator_io["stamp_specs"] == [{"type": "count"}]


def test_mutation_control_without_the_count_route_the_same_fixture_is_confirmed_by_slope(evaluator_io, monkeypatch):
    """Proves the fixture reproduces #4541: remove the count route and the live verdict returns."""
    monkeypatch.setattr(ev.prediction_count_grader, "grade", lambda *a, **k: None)
    evaluations, _ = ev._evaluate_all([_issue_pred()], GRADED_ON)
    (e,) = evaluations
    assert e["status"] == "confirmed"
    assert e["reason"].startswith("sleep_duration_hours trend=up (slope=0.06")


# ── the readers: a day count is never served as the stored spec's slope or level ──


def _graded_row(status="refuted"):
    from coach.prediction_grading import build_outcome_notes

    r = _grade(WHOOP_SLEEP_HOURS) if status == "refuted" else _grade(_week(7.5, 8.0, 6.0, 7.6, 5.0, 9.0, 7.5))
    evaluation = {**r, "status": r["status"], "bayesian_update": None}
    row = _issue_pred()
    row.update(status=r["status"], outcome_date=GRADED_ON, outcome_notes=build_outcome_notes(evaluation, "1.0"))
    return row, evaluation


def test_the_outcome_notes_mark_a_count_grade():
    import json

    row, _ = _graded_row()
    notes = json.loads(row["outcome_notes"])
    assert notes["graded_as"] == "count" and notes["actual_value"] == 3


def test_the_reason_reader_says_the_count_not_a_direction():
    from web import prediction_reason

    row, _ = _graded_row()
    reason, graded = prediction_reason.reason_words(row)
    assert reason == "Sleep time came in at or above 7.5 hours on 3 of 7 days — the call needed at least 5"
    assert graded is True
    row, _ = _graded_row("confirmed")
    assert prediction_reason.reason_words(row)[0] == "Sleep time came in at or above 7.5 hours on 5 of 7 days — the call needed at least 5"


def test_the_latest_checked_block_does_not_serve_a_count_as_a_slope():
    from coach import latest_checked

    row, _ = _graded_row()
    block = latest_checked.to_block(row)
    assert (block["eval_type"], block["condition"], block["threshold"], block["actual_value"]) == ("count", None, None, None)
    assert block["status"] == "refuted"


def test_the_wrong_obituary_counts_days_not_hours():
    from web import site_api_foresight

    _, evaluation = _graded_row()
    believed, number, changed = site_api_foresight._wrong_obituary_text(evaluation)
    assert believed == "sleep duration would come in at or above 7.5 hours on at least 5 of 7 days"
    assert number == "3 of 7 days came in at or above 7.5 hours — the call needed at least 5"
    assert "3 of 7" in changed
