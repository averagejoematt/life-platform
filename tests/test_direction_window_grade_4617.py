"""tests/test_direction_window_grade_4617.py — a direction call is graded across its OWN window,
a re-graded call keeps its old grade and the reason, and the headline record states what it
counts (#4617, epic #4580).

THE DEFECT: two calls sealed before day one that weight would trend down over the first 14
days were graded flat, and so wrong, on 2026-10-04, while the served weigh-ins fell from
327.3 lb (September 6) to 312.1 lb (October 4). The grader compared its LATEST readings with
the few before them inside a fixed ±2% band; the start of the call's window never entered.

Pins:
  * box 1 — the specimen: on a weight series shaped like the served one (fifteen pounds down,
    the last week flat) the old trend check reads flat and the window grade reads down, and
    the grade agrees with the sign of (last reading − first reading) of the call's stated
    window; readings after the window never enter; the band is the metric's own day-to-day
    swing (a noisy series with the same net change reads flat); too few readings or a gap at
    an edge is no verdict, never a guess; an undated row keeps the legacy path;
  * the written record carries the window (first/last readings, days, band) and the
    "nothing changes" rule is scored against the call's own band;
  * the reader sentence prints the first and last readings and their days, and a sealed call
    graded flat ACROSS ITS WINDOW gets a page (the old flat read still does not);
  * box 2 — the re-grade script: the plan, the audit map (old grade + its reason) on every
    write, the conditional that makes a second run a no-op, and the sealed/all scope;
  * box 3 — every decided call is exactly one class (sealed / bet / commentary / conditional),
    the counts sum to the record's n, and the edition's record block serves the sentence.

Everything here is pure or runs against in-memory fakes — no AWS.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import pytest  # noqa: E402
import regrade_direction_calls_4617 as regrade  # noqa: E402
from coach import (  # noqa: E402
    coach_baseline,
    coach_prediction_evaluator as ev,
    coach_record,
    prediction_direction_window as dw,  # noqa: E402
)
from coach.prediction_grading import build_outcome_notes  # noqa: E402
from web import prediction_reason, site_api_calls as calls  # noqa: E402

GENESIS = "2026-09-06"
GRADED_ON = "2026-10-04"
WEIGHT_SOURCE = ev.METRIC_SOURCES["weight_lbs"]


def _days(start, n):
    d0 = datetime.strptime(start, "%Y-%m-%d")
    return [(d0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


def served_weight_series():
    """29 daily weigh-ins, September 6 → October 4, shaped like the served chart: 327.34 on
    day one, 316.92 on day fifteen, then down to ~312 and FLAT for the last eight days — the
    shape that made the latest-readings trend check read "flat"."""
    days = _days(GENESIS, 29)
    values = []
    for i in range(29):
        if i <= 14:
            v = 327.34 - (327.34 - 316.92) * i / 14
        elif i <= 20:
            v = 316.92 - (316.92 - 312.3) * (i - 14) / 6
        else:
            v = 312.3
        values.append(round(v + (0.3 if i % 2 else -0.3) * (0 < i < 28 and i != 14), 2))
    values[-1] = 312.11
    return [{"date": d, "weight_lbs": v} for d, v in zip(days, values)]


def _sealed_weight_call(**extra):
    return {
        "pk": "COACH#physical_coach",
        "sk": "PREDICTION#pred_weight",
        "prediction_id": "pred_weight",
        "coach_id": "physical_coach",
        "subdomain": "weight",
        "created_date": GENESIS,
        "pre_registered": True,
        "pre_registered_at": "2026-09-04T18:00:00Z",
        "phase": "experiment",
        "claim_natural": "Starting from 326.2 lbs on Day 1, body weight will trend downward over the first 14 days, with the scale reading lower on Day 14 than on Day 1.",
        "evaluation": {"type": "directional", "metric": "weight_lbs", "condition": "down", "evaluation_window_days": 14, "threshold": None},
        **extra,
    }


@pytest.fixture
def weight_data(monkeypatch):
    rows = served_weight_series()
    monkeypatch.setattr(ev, "_get_source_data", lambda source, cache, end, lookback_days=30, include_pilot=False: rows)
    return rows


# ── box 1: the grade agrees with the window's first and last reading ─────────────────────


def test_the_old_trend_check_reads_the_specimen_flat():
    """The defect, reproduced on the served shape: the latest-readings check says flat."""
    rows = served_weight_series()
    cache = {ev.source_cache_key(WEIGHT_SOURCE, GRADED_ON, 30): rows}
    direction, slope = ev._get_ewma_trend("weight_lbs", cache, GRADED_ON)
    assert direction == "flat", (direction, slope)


def test_the_sealed_weight_call_is_graded_down_across_its_own_window(weight_data):
    result = ev._evaluate_directional(_sealed_weight_call(), _sealed_weight_call()["evaluation"], {}, GRADED_ON)
    w = result["window"]
    assert (w["start"], w["end"]) == ("2026-09-06", "2026-09-20")  # the sentence's 14 days, not the 28-day clamp
    assert (w["first_date"], w["first_value"]) == ("2026-09-06", 327.34)
    assert (w["last_date"], w["last_value"]) == ("2026-09-20", 316.92)
    assert result["status"] == "confirmed" and result["beats_null"] is True
    # acceptance box 1: the grade agrees with the sign of last − first on the served series
    assert (w["last_value"] - w["first_value"] < 0) == (result["status"] == "confirmed")
    assert result["actual_value"] == pytest.approx((316.92 - 327.34) / 327.34, rel=1e-4)


def test_a_reading_after_the_window_never_enters(monkeypatch):
    rows = served_weight_series()[:15] + [{"date": "2026-09-25", "weight_lbs": 400.0}]
    monkeypatch.setattr(ev, "_get_source_data", lambda *a, **k: rows)
    result = ev._evaluate_directional(_sealed_weight_call(), _sealed_weight_call()["evaluation"], {}, GRADED_ON)
    assert result["window"]["last_value"] == 316.92 and result["status"] == "confirmed"


def test_an_unstated_window_falls_back_to_the_clamped_one(weight_data):
    call = _sealed_weight_call()
    spec = dict(call["evaluation"], evaluation_window_days=None)
    result = ev._evaluate_directional(call, spec, {}, GRADED_ON)
    assert (result["window"]["start"], result["window"]["end"]) == ("2026-09-06", "2026-10-04")  # body composition: 28 days
    assert result["window"]["last_value"] == 312.11


def test_the_band_is_the_metrics_own_day_to_day_swing():
    """Same net change (−3), two metrics: a quiet one moves, a noisy one held flat."""
    days = _days(GENESIS, 15)
    quiet = [(d, 100 - 3 * i / 14) for i, d in enumerate(days)]
    noisy = [(d, 100 - 3 * i / 14 + (8 if i % 2 else -8) * (0 < i < 14)) for i, d in enumerate(days)]
    wq, _ = dw.measure(quiet, days[0], days[-1], "hrv")
    wn, _ = dw.measure(noisy, days[0], days[-1], "hrv")
    assert wq["direction"] == "down" and wn["direction"] == "flat"
    assert wn["band"] > 3 > wq["band"]
    assert dw.verdict("down", wn, "hrv")["status"] == "refuted" and dw.FLAT_MARKER in dw.verdict("down", wn, "hrv")["reason"]


def test_too_few_readings_or_a_gap_at_an_edge_is_no_verdict():
    days = _days(GENESIS, 15)
    assert dw.measure([(days[0], 1.0), (days[7], 2.0), (days[14], 3.0)], days[0], days[14], "hrv")[0] is None
    late_start = [(d, float(i)) for i, d in enumerate(days) if i >= 5]
    window, why = dw.measure(late_start, days[0], days[14], "hrv")
    assert window is None and "start" in why
    early_end = [(d, float(i)) for i, d in enumerate(days) if i <= 9]
    assert dw.measure(early_end, days[0], days[14], "hrv")[0] is None


def test_a_window_with_no_reading_is_inconclusive_not_a_guess(monkeypatch):
    monkeypatch.setattr(ev, "_get_source_data", lambda *a, **k: [])
    result = ev._evaluate_directional(_sealed_weight_call(), _sealed_weight_call()["evaluation"], {}, GRADED_ON)
    assert (result["status"], result["actual_value"], result["beats_null"]) == ("inconclusive", None, False)


def test_an_averaged_call_compares_the_first_and_last_k_readings():
    days = _days(GENESIS, 15)
    series = [(d, 40.0 if i < 7 else 50.0) for i, d in enumerate(days)]
    w, _ = dw.measure(series, days[0], days[-1], "hrv_7day_avg")
    assert w["averaged_over"] == 7 and w["first_value"] == 40.0 and w["last_value"] == 50.0 and w["direction"] == "up"


def test_an_undated_row_keeps_the_legacy_trend_verdict(monkeypatch):
    monkeypatch.setattr(ev, "_get_ewma_trend", lambda *a, **k: ("up", 0.05))
    result = ev._evaluate_directional({}, {"metric": "hrv", "condition": "up"}, {}, GRADED_ON)
    assert result["status"] == "confirmed" and "window" not in result


# ── what the graded row carries ──────────────────────────────────────────────────────────


def test_the_written_notes_carry_the_window(weight_data, monkeypatch):
    monkeypatch.setattr(ev, "_update_prediction_status", lambda p, e, b=None: None)
    monkeypatch.setattr(ev, "_update_bayesian_confidence", lambda *a: None)
    monkeypatch.setattr(ev, "_write_learning_record", lambda *a: None)
    evaluations, _ = ev._evaluate_all([_sealed_weight_call(status="pending")], GRADED_ON)
    notes = json.loads(build_outcome_notes(evaluations[0], ev.ALGO_VERSION))
    assert notes["window"]["first_value"] == 327.34 and notes["window"]["last_date"] == "2026-09-20"
    assert evaluations[0]["status"] == "confirmed"


def test_the_simple_guess_is_scored_against_the_calls_own_band():
    result = {"actual_value": -0.01, "noise_band": 0.02}
    stamp = coach_baseline.stamp_at_grading({}, {"type": "directional"}, result, "confirmed", {}, None, None, 0.001)
    assert stamp["right"] is True  # inside the call's own ±2%, though outside the fallback band
    legacy = coach_baseline.stamp_at_grading({}, {"type": "directional"}, {"actual_value": -0.01}, "confirmed", {}, None, None, 0.001)
    assert legacy["right"] is False


# ── the reader sentence and the call page ────────────────────────────────────────────────


def _graded_row(status, result, **extra):
    evaluation = {"status": status, "reason": result["reason"], "actual_value": result["actual_value"], "window": result.get("window")}
    return _sealed_weight_call(
        status=status, outcome=status, outcome_date=GRADED_ON, outcome_notes=build_outcome_notes(evaluation, "1.0"), **extra
    )


def test_the_reason_prints_the_first_and_last_reading_and_their_days(weight_data):
    result = ev._evaluate_directional(_sealed_weight_call(), _sealed_weight_call()["evaluation"], {}, GRADED_ON)
    reason, graded = prediction_reason.reason_words(_graded_row("confirmed", result))
    assert reason == "Weight went down from 327.3 lb on September 6 to 316.9 lb on September 20, as called" and graded is True


def test_a_window_graded_flat_call_gets_a_page_with_its_rule(monkeypatch):
    rows = [{"date": d, "weight_lbs": 320 + (0.5 if i % 2 else -0.5)} for i, d in enumerate(_days(GENESIS, 15))]
    monkeypatch.setattr(ev, "_get_source_data", lambda *a, **k: rows)
    result = ev._evaluate_directional(_sealed_weight_call(), _sealed_weight_call()["evaluation"], {}, GRADED_ON)
    assert result["status"] == "refuted" and dw.FLAT_MARKER in result["reason"]
    built, why = calls.build_call("physical", "Max Reyes", _graded_row("refuted", result), {})
    assert why is None and built["verdict"] == "wrong"
    assert "held flat, from 319.5 lb on September 6 to 319.5 lb on September 20" in built["happened"]
    assert "first reading of its window, September 6, to the last, September 20" in built["called"]


def test_the_old_flat_read_still_gets_no_page():
    old = {"status": "refuted", "reason": "predicted down, metric flat (slope=-0.0076, within ±0.02 noise band)", "actual_value": -0.0076}
    row = _graded_row("refuted", old)
    assert calls.build_call("physical", "Max Reyes", row, {}) == (None, calls.FLAT_READ)


# ── box 2: the re-grade keeps the old grade and the reason ───────────────────────────────


def _old_flat_row(**extra):
    notes = {
        "actual_value": -0.0076,
        "reason": "predicted down, metric flat (slope=-0.0076, within ±0.02 noise band)",
        "algo_version": "1.0",
    }
    return _sealed_weight_call(status="refuted", outcome="refuted", outcome_date=GRADED_ON, outcome_notes=json.dumps(notes), **extra)


def _commentary_row():
    return {
        **_old_flat_row(),
        "sk": "PREDICTION#pred_c",
        "prediction_id": "pred_c",
        "pre_registered": False,
        "claim_natural": "Weight keeps trending downward this fortnight.",
    }


def test_the_plan_regrades_the_sealed_call_and_leaves_commentary_to_scope_all(weight_data):
    rows = {"physical_coach": [_old_flat_row(), _commentary_row()]}
    sealed = regrade.plan(rows, genesis=GENESIS, today="2026-10-11", ev=ev)
    assert [(e["sk"], e["action"], e["status"], e["new_status"]) for e in sealed] == [
        ("PREDICTION#pred_weight", regrade.REGRADE, "refuted", "confirmed")
    ]
    everything = regrade.plan(rows, genesis=GENESIS, today="2026-10-11", ev=ev, scope="all")
    assert {e["sk"] for e in everything} == {"PREDICTION#pred_weight", "PREDICTION#pred_c"}


def test_every_write_keeps_the_old_grade_and_its_reason_and_is_conditional(weight_data):
    (entry,) = regrade.plan({"physical_coach": [_old_flat_row()]}, genesis=GENESIS, today="2026-10-11", ev=ev)
    kw = regrade.update_kwargs(entry, "2026-10-12T05:00:00+00:00", "1.0")
    vc = kw["ExpressionAttributeValues"][":vc"]
    assert vc["prior"]["status"] == "refuted" and "metric flat" in vc["prior"]["reason"]
    assert vc["new_status"] == "confirmed" and vc["issue"] == "#4617" and vc["reason"]
    notes = json.loads(kw["ExpressionAttributeValues"][":notes"])
    assert notes["verdict_correction"]["prior_status"] == "refuted" and "metric flat" in notes["verdict_correction"]["prior_reason"]
    assert notes["window"]["first_value"] == 327.34
    assert kw["ConditionExpression"] == "#s = :prior AND attribute_not_exists(verdict_correction)"
    assert kw["ExpressionAttributeValues"][":prior"] == "refuted"
    assert "verdict_correction = :vc" in kw["UpdateExpression"] and "baseline = :bl" in kw["UpdateExpression"]


def test_a_second_run_changes_nothing(weight_data):
    corrected = _old_flat_row(verdict_correction={"issue": "#4617"})
    window_graded = _sealed_weight_call(
        status="confirmed",
        outcome="confirmed",
        outcome_date=GRADED_ON,
        outcome_notes=json.dumps({"reason": "x", "window": {"start": GENESIS}}),
    )
    assert regrade.plan({"physical_coach": [corrected, window_graded]}, genesis=GENESIS, today="2026-10-11", ev=ev, scope="all") == []


def test_the_apply_path_writes_only_when_asked():
    class Table:
        def __init__(self):
            self.calls = []

        def update_item(self, **kw):
            self.calls.append(kw)

    entry = {
        "action": regrade.WITHDRAW,
        "coach": "physical_coach",
        "pk": "COACH#physical_coach",
        "sk": "PREDICTION#x",
        "status": "refuted",
        "new_status": "inconclusive",
        "result": {"status": "inconclusive", "reason": "too few"},
    }
    t = Table()
    assert regrade.apply(t, [entry], "1.0", now="2026-10-12T05:00:00+00:00") == 1
    assert t.calls[0]["ExpressionAttributeValues"][":new"] == "inconclusive"


# ── box 3: the headline record states what it counts ─────────────────────────────────────


def _decided(status, **row):
    return {"status": status, "outcome_date": GRADED_ON, "phase": "experiment", **row}


DECIDED = [
    _decided("confirmed", prediction_id="a", pre_registered=True, claim_natural="If X then weight will fall"),
    _decided("refuted", prediction_id="b", source="dispute_docket"),
    _decided("refuted", prediction_id="c", claim_natural="If dinner is missed, protein will not be met"),
    _decided("confirmed", prediction_id="d", evaluation={"type": "conditional"}, claim_natural="Protein goes up"),
    _decided("confirmed", prediction_id="e", claim_natural="HRV will rise this week"),
    _decided("refuted", prediction_id="f", claim_natural="Recovery could dip"),
]


def test_every_decided_call_is_exactly_one_class_and_nothing_is_dropped():
    assert [coach_record.call_class(r) for r in DECIDED] == ["sealed", "bet", "conditional", "conditional", "commentary", "conditional"]
    counts = coach_record.class_counts(DECIDED)
    assert sum(c["n"] for c in counts.values()) == coach_record.record_from_rows(DECIDED, genesis=GENESIS)["n"] == 6
    assert sum(c["right"] for c in counts.values()) == coach_record.record_from_rows(DECIDED, genesis=GENESIS)["confirmed"]
    assert counts["conditional"] == {"n": 3, "right": 1}


def test_the_counted_sentence_names_every_class_with_a_count():
    text = coach_record.counted_text(coach_record.class_counts(DECIDED))
    assert text == (
        "Counted: 1 sealed before day one, 1 side of a bet between two coaches, "
        "1 read out of the coaches' running commentary and 3 conditional or hedged sentences."
    )
    assert coach_record.counted_text(coach_record.class_counts([])) is None


def test_the_edition_record_block_serves_what_it_counts():
    from web import site_api_coach_ledger as ledger, site_api_edition as edition

    overall = {"confirmed": 4, "refuted": 2, "decided": 6, "due": {"as_of": GRADED_ON}, **ledger._counted_block(DECIDED)}
    block = edition._record({"overall": overall}, {"platform": {"strata": {"coaches": {"brier_skill": -0.1, "n": 6}}}}, GRADED_ON)
    assert block["data"]["count_text"] == "4 of 6 checked calls right."
    assert block["data"]["counted_text"].startswith("Counted: 1 sealed before day one")
    assert sum(c["n"] for c in block["data"]["counted"].values()) == block["data"]["decided"]


def test_the_narrow_edition_read_projects_what_the_classes_read():
    from web import site_api_coach_ledger as ledger

    for field in ("pre_registered", "source", "evaluation", "claim_natural"):
        assert field in ledger._RECORD_PROJECTION_FIELDS
    assert set(ledger._RECORD_PROJECTION_FIELDS) < set(ledger._PREDICTION_PROJECTION_FIELDS)
