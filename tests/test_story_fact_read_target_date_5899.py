"""tests/test_story_fact_read_target_date_5899.py — the fact read knows the day a call TARGETED (#5899).

Week 10 shape: a call filed Thursday 2026-11-05 about "tomorrow morning" is scored against Friday 11-06 but its
``outcome_date`` (graded) is Saturday 11-07. The dossier entry used to carry only ``made`` and ``graded``, so the
fact read inferred the target from ``graded`` and blocked a correct sentence. The model call itself is not made
here: the deterministic proof is the dossier INPUT, the rubric and the request body.
"""

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from content import story_dossier, story_writers  # noqa: E402

WEEK10 = next(w for w in story_dossier.season_weeks(through="2026-11-12") if w["week"] == 10)


def _row(**over):
    row = {
        "pk": "COACH#physical_coach",
        "sk": "PREDICTION#2026-11-05#w",
        "cycle": "17",
        "created_date": "2026-11-05",
        "claim_natural": "Weight will hold around 295 lbs tomorrow morning",
        "status": "confirmed",
        "outcome_date": "2026-11-07",
        "outcome_notes": json.dumps({"reason": "weight on the target morning within tolerance"}),
        "evaluation": {"type": "point", "metric": "weight_lbs", "threshold": Decimal("295"), "target_date": "2026-11-06"},
    }
    row.update(over)
    return row


class _Table:
    def __init__(self, rows):
        self.rows = rows

    def query(self, **kw):
        want = kw["KeyConditionExpression"].get_expression()["values"][0].get_expression()["values"][1]
        return {"Items": [r for r in self.rows if r["pk"] == want]}


class _Public:
    row_is_public = staticmethod(lambda *a, **k: True)


_REAL = story_dossier.prediction_publication


def _entries(row):
    # the publication classifier is not under test; a public row is the premise (its own suite owns the rule)
    story_dossier.prediction_publication = _Public
    try:
        out = story_dossier._predictions(_Table([row]), WEEK10, {"physical_coach": "Coach"})
    finally:
        story_dossier.prediction_publication = _REAL
    return out["graded_this_week"]


def _entry(row):
    got = _entries(row)
    assert len(got) == 1, got
    return got[0]


def test_week10_entry_carries_target_before_graded():
    e = _entry(_row())
    assert (e["made"], e["target"], e["graded"]) == ("2026-11-05", "2026-11-06", "2026-11-07")


def test_target_falls_back_to_the_sentence_then_the_window_then_omits():
    no_spec = _row(evaluation={"type": "point"})
    assert _entry(no_spec)["target"] == "2026-11-06"  # "tomorrow" from the filing day
    quiet = _row(evaluation={}, claim_natural="Weight holds near 295 lbs", outcome_notes=json.dumps({"window": "2026-11-05 to 2026-11-06"}))
    assert _entry(quiet)["target"] == "2026-11-06"
    bare = _entry(_row(evaluation={}, claim_natural="Weight holds near 295 lbs"))
    assert "target" not in bare  # never a guess from outcome_date


def test_rubric_states_the_rule():
    r = story_writers.FACT_RUBRIC
    assert "`target` is the day the call was about" in r and "`graded` is only when scoring ran" in r
    assert "do not infer one from `graded`" in r and "wrong target day" in r


def _request_dossier(row):
    body = story_writers.fact_check_body("Friday morning's weigh-in held.", {"predictions": {"graded_this_week": _entries(row)}})
    return body["messages"][0]["content"]


def test_request_body_carries_target_and_control_is_distinguishable():
    good = _request_dossier(_row())
    assert '"target": "2026-11-06"' in good and '"graded": "2026-11-07"' in good
    # must-fail control: a dropped target, or one equal to graded, is a different (and detectable) input
    dropped = _request_dossier(_row(evaluation={}, claim_natural="Weight holds near 295 lbs"))
    assert '"target"' not in dropped and dropped != good
    wrong = _request_dossier(_row(evaluation={"type": "point", "target_date": "2026-11-07"}))
    assert '"target": "2026-11-07"' in wrong and wrong != good  # a genuinely wrong target day reads differently
