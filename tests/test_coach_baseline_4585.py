"""tests/test_coach_baseline_4585.py — the "nothing changes" rule beside every coach count
(#4585, epic #4580 rule 3).

Pins, on the wire shapes the grader writes and the API reads:
  * the rule's verdict per kind of call (number / direction / yes-no) and the filed
    reading it uses (the day BEFORE filing — never a reading the coach did not have);
  * four SEPARATE records (number calls, direction calls, yes/no bets, sealed day-one
    predictions) — no field anywhere adds two of them together;
  * the sentence: the engine's skill score with its n until every graded call is
    scored; then the rule's counts, saying so when the guess did better; no percentage
    and no verdict below 20 scored calls; unscorable calls counted and named;
  * the grader freezes the stamp beside the grade; the docket stamps both sides;
  * /api/predictions and /api/calibration serve right / scored / unscorable counts;
  * the back-fill is dry-run by default and idempotent under --apply.
"""

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal

import pytest

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

from coach import coach_baseline as cb  # noqa: E402
from common import stats_core  # noqa: E402
from common.constants import EXPERIMENT_START_DATE as GENESIS  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

BAND = 0.02


def _day(offset):
    from datetime import datetime, timedelta

    return (datetime.strptime(GENESIS, "%Y-%m-%d") + timedelta(days=offset)).strftime("%Y-%m-%d")


def _row(pid, status, *, kind="directional", baseline=None, sealed=False, docket=False, coach="sleep_coach", day=5, **spec):
    row = {
        "pk": f"COACH#{coach}",
        "sk": f"PREDICTION#{pid}",
        "prediction_id": pid,
        "status": status,
        "outcome": status,
        "outcome_date": _day(day + 7),
        "created_date": _day(day),
        "phase": "experiment",
        "confidence": 0.5,
    }
    if docket:
        row["source"] = "dispute_docket"
    else:
        row["evaluation"] = {"type": kind, "metric": spec.pop("metric", "recovery_score"), **spec}
    if sealed:
        row["pre_registered"] = True
    if baseline is not None:
        row["baseline"] = baseline
    return row


def _scored(right):
    return cb.stamp(right) if right is not None else cb.stamp(None, cb.NO_FILED_READING)


# ── the pure rule ──────────────────────────────────────────────────────────────────────


def test_direction_rule_predicts_flat_inside_the_graders_own_noise_band():
    assert cb.verdict("direction", {}, actual=0.0180, noise_band=BAND) == (True, None)
    assert cb.verdict("direction", {}, actual=-0.0200, noise_band=BAND) == (True, None)
    assert cb.verdict("direction", {}, actual=0.0241, noise_band=BAND) == (False, None)
    assert cb.verdict("direction", {}, actual=None, noise_band=BAND) == (None, cb.NO_GRADED_READING)


def test_number_rule_uses_the_calls_own_frozen_tolerance():
    spec = {"tolerance": 17.9}
    assert cb.verdict("number", spec, actual=67.0, filed_value=55.0, noise_band=BAND) == (True, None)
    assert cb.verdict("number", spec, actual=24.0, filed_value=55.0, noise_band=BAND) == (False, None)
    assert cb.verdict("number", spec, actual=67.0, filed_value=None, noise_band=BAND) == (None, cb.NO_FILED_READING)
    assert cb.verdict("number", {}, actual=67.0, filed_value=55.0, noise_band=BAND) == (None, cb.INCOMPLETE_SPEC)


def test_yes_no_rule_answers_from_the_filed_reading():
    spec = {"condition": "lt", "threshold": 70}
    # filed 74 → the rule says "not below 70"; the metric ended below 70 → the rule is wrong
    assert cb.verdict("yes_no", spec, filed_value=74.0, holds=True, noise_band=BAND) == (False, None)
    assert cb.verdict("yes_no", spec, filed_value=65.0, holds=True, noise_band=BAND) == (True, None)
    assert cb.verdict("yes_no", {"condition": "lt"}, filed_value=65.0, holds=True, noise_band=BAND) == (None, cb.INCOMPLETE_SPEC)


def test_the_filed_reading_is_the_day_before_filing_never_the_filing_day():
    series = [(_day(1), 50.0), (_day(2), 60.0), (_day(3), 99.0)]
    assert cb.filed_reading(series, "recovery_score", _day(3)) == (60.0, _day(2), None), "the filing day's own reading leaked"
    # a reading older than the grace is no reading
    assert cb.filed_reading([(_day(1), 50.0)], "recovery_score", _day(6))[2] == cb.NO_FILED_READING
    # an aggregate key is the mean of the last N readings before the filing day
    series7 = [(_day(i), float(i)) for i in range(1, 10)]
    value, _on, why = cb.filed_reading(series7, "hrv_7day_avg", _day(9))
    assert why is None and value == pytest.approx(sum(range(2, 9)) / 7)


def test_classification_keeps_the_four_records_apart():
    assert cb.record_of(_row("a", "confirmed", kind="point")) == "number"
    assert cb.record_of(_row("b", "confirmed")) == "direction"
    assert cb.record_of(_row("c", "confirmed", kind="machine", threshold=50, condition="gt")) == "yes_no"
    assert cb.record_of(_row("d", "confirmed", kind="machine")) == "direction", "a threshold-less machine spec is graded as a direction"
    assert cb.record_of(_row("e", "confirmed", docket=True)) == "yes_no"
    assert cb.record_of(_row("f", "confirmed", sealed=True)) == "sealed", "a sealed day-one prediction is its own record"
    assert cb.record_of(_row("g", "confirmed", kind="qualitative")) is None


def test_exact_sign_test():
    assert stats_core.exact_sign_test_p(15, 5) == pytest.approx(0.0414, abs=1e-4)
    assert stats_core.exact_sign_test_p(6, 5) == 1.0
    assert stats_core.exact_sign_test_p(0, 0) == 1.0
    assert stats_core.exact_sign_test_p(-1, 2) is None
    assert stats_core.exact_sign_test_p(1.5, 2) is None


# ── the served block ───────────────────────────────────────────────────────────────────


def test_before_the_back_fill_the_sentence_is_the_skill_score_with_its_n():
    rows = [_row(f"p{i}", "confirmed" if i % 2 else "refuted") for i in range(24)]
    block = cb.comparison_block(rows)
    assert block["scored_complete"] is False
    assert block["records"]["direction"]["not_yet_scored"] == 24
    assert block["sentence"] == block["skill"]["sentence"] == "Across 24 checked calls, so far they do not beat a simple guess."
    assert block["rule_sentence"] is None
    few = cb.comparison_block(rows[:5])
    assert few["sentence"] == "Too few checked calls yet (5) to compare them with a simple guess."
    assert cb.comparison_block([])["sentence"].startswith("No checked call yet")


def test_after_the_back_fill_each_record_reads_on_its_own_and_none_is_summed():
    rows = (
        [_row(f"d{i}", "confirmed", baseline=_scored(False)) for i in range(15)]
        + [_row(f"x{i}", "refuted", baseline=_scored(True)) for i in range(5)]
        + [_row(f"y{i}", "refuted", baseline=_scored(False)) for i in range(30)]
        + [_row(f"n{i}", "confirmed", kind="point", tolerance=1, baseline=_scored(True)) for i in range(3)]
        + [_row("nu", "refuted", kind="point", tolerance=1, baseline=_scored(None))]
        + [_row("s1", "confirmed", sealed=True, baseline=_scored(False))]
    )
    block = cb.comparison_block(rows)
    d = block["records"]["direction"]
    assert (d["graded"], d["scored"], d["coach_right_on_scored"], d["rule_right"], d["coach_only"], d["rule_only"]) == (
        50,
        50,
        15,
        5,
        15,
        5,
    )
    assert d["verdict"] == "coaches_better" and d["sign_test_p"] == pytest.approx(0.0414, abs=1e-4)
    assert d["coach_right_pct"] == 30.0 and d["rule_right_pct"] == 10.0
    n = block["records"]["number"]
    assert (n["graded"], n["scored"], n["unscorable"]) == (4, 3, 1)
    assert n["unscorable_reasons"] == {cb.NO_FILED_READING: 1}, "an unscorable call is counted AND named"
    assert n["verdict"] == "too_few" and n["coach_right_pct"] is None and n["sign_test_p"] is None, "no % and no verdict below 20"
    assert (
        block["records"]["sealed"]["graded"] == 1 and block["records"]["direction"]["graded"] == 50
    ), "a sealed call never joins its spec's record"
    assert block["scored_complete"] is True
    s = block["sentence"]
    assert s == block["rule_sentence"]
    assert "Direction calls: on the 50 a guess could also be checked against, the coaches were right 15 times" in s
    assert "a guess that nothing changes 5 times — the coaches did better." in s
    assert "1 more could not be checked against the guess." in s
    assert "%" not in s
    # never added together: no key on the block or its records totals two records
    assert not {"total", "overall", "all"} & set(block) and not {"total", "overall", "all"} & set(block["records"])


def test_when_the_rule_wins_the_sentence_says_so():
    rows = [_row(f"w{i}", "refuted", kind="point", tolerance=1, baseline=_scored(True)) for i in range(20)] + [
        _row(f"v{i}", "confirmed", kind="point", tolerance=1, baseline=_scored(True)) for i in range(2)
    ]
    rec = cb.comparison_block(rows)["records"]["number"]
    assert rec["verdict"] == "rule_better"
    assert "the guess did better" in cb.comparison_block(rows)["sentence"]
    small = cb.comparison_block(rows[:4])
    assert "the guess was right more often, on too few calls to tell" in small["sentence"]


def test_comparison_from_rows_counts_only_this_experiments_record():
    archived = dict(_row("old", "confirmed", baseline=_scored(True)), phase="pilot", tombstone=True)
    pre_genesis = dict(_row("pre", "confirmed", baseline=_scored(True)), outcome_date="2000-01-01")
    live = _row("live", "refuted", baseline=_scored(False))
    block = cb.comparison_from_rows([archived, pre_genesis, live], genesis=GENESIS)
    assert block["records"]["direction"]["graded"] == 1


# ── grading-time stamping ──────────────────────────────────────────────────────────────


def _io(records):
    calls = []

    def get_source_data(source, cache, end, lookback_days=30, include_pilot=False):
        calls.append((source, end))
        return records

    def extract(rows, metric):
        return sorted((r["date"], r[metric]) for r in rows if metric in r)

    return calls, get_source_data, extract


def test_stamp_at_grading_direction_reads_no_data():
    calls, gsd, ex = _io([])
    pred = _row("p", "refuted")
    out = cb.stamp_at_grading(pred, pred["evaluation"], {"actual_value": 0.01}, "refuted", {}, gsd, ex, BAND)
    assert out == {"rule": cb.RULE_ID, "version": cb.RULE_VERSION, "right": True}
    assert calls == []


def test_stamp_at_grading_number_reads_the_day_before_filing():
    recs = [{"date": _day(3), "recovery_score": 61.0}, {"date": _day(4), "recovery_score": 70.0}, {"date": _day(5), "recovery_score": 10.0}]
    calls, gsd, ex = _io(recs)
    pred = _row("p", "confirmed", kind="point", tolerance=10)
    out = cb.stamp_at_grading(pred, pred["evaluation"], {"actual_value": 75.0}, "confirmed", {}, gsd, ex, BAND)
    assert calls == [("whoop", _day(4))]
    assert out["right"] is True and out["filed_on"] == _day(4) and out["filed_value"] == Decimal("70.0")


def test_stamp_at_grading_absence_and_failure_are_not_a_verdict():
    _c, gsd, ex = _io([])
    pred = _row("p", "confirmed", kind="point", tolerance=10)
    assert (
        cb.stamp_at_grading(pred, pred["evaluation"], {"actual_value": 1}, "confirmed", {}, gsd, ex, BAND) is None
    ), "an empty read inside the experiment waits"
    day_one = _row("p1", "confirmed", kind="point", tolerance=10, day=0)
    assert (
        cb.stamp_at_grading(day_one, day_one["evaluation"], {"actual_value": 1}, "confirmed", {}, gsd, ex, BAND)["unscorable"]
        == cb.NO_FILED_READING
    )

    def boom(*a, **k):
        raise RuntimeError("ddb down")

    assert cb.stamp_at_grading(pred, pred["evaluation"], {"actual_value": 1}, "confirmed", {}, boom, ex, BAND) is None
    assert cb.stamp_at_grading(pred, pred["evaluation"], {}, "inconclusive", {}, gsd, ex, BAND)["unscorable"] == cb.NOT_GRADED


def test_write_stamp_is_conditional_and_never_writes_nothing():
    t = FakeDdbTable()
    assert cb.write_stamp(t, "COACH#x", "PREDICTION#y", None) is False and t.updates == []
    assert cb.write_stamp(t, "COACH#x", "PREDICTION#y", cb.stamp(True), only_if_absent=True) is True
    assert "attribute_not_exists(baseline)" in t.updates[0]["ConditionExpression"]

    def refuse(table, **kw):
        raise RuntimeError("ConditionalCheckFailedException")

    assert cb.write_stamp(FakeDdbTable(update_item_hook=refuse), "a", "b", cb.stamp(True)) is False


def test_the_grader_freezes_the_stamp_beside_the_grade(monkeypatch):
    import inspect

    from coach import coach_prediction_evaluator as ev

    t = FakeDdbTable()
    monkeypatch.setattr(ev, "table", t)
    pred = _row("p", "confirmed")
    evaluation = {"prediction_id": "p", "status": "confirmed", "evaluated_date": _day(20), "actual_value": 0.05, "reason": "r"}
    ev._update_prediction_status(pred, evaluation, cb.stamp(False))
    assert len(t.updates) == 2 and t.updates[1]["ExpressionAttributeValues"][":baseline"]["right"] is False
    ev._update_prediction_status(pred, evaluation)  # no stamp → the old single write, nothing else
    assert len(t.updates) == 3
    src = inspect.getsource(ev._evaluate_all)
    assert "coach_baseline.stamp_at_grading(" in src and "_update_prediction_status(pred, evaluation, _bl)" in src
    assert ev._BASELINE_IO == (ev._get_source_data, ev._extract_metric_series, ev.DIRECTIONAL_NOISE_THRESHOLD)


def test_the_docket_stamps_both_sides_with_one_answer(monkeypatch):
    from coach import dispute_docket as dd

    t = FakeDdbTable()
    monkeypatch.setattr(dd, "table", t)
    docket = {
        "sk": "OPEN#a__b#recovery",
        "opened_date": _day(10),
        "criterion": {"metric": "recovery_score", "condition": "lt", "threshold": 70},
    }
    recs = [{"date": _day(9), "recovery_score": 74.0}]
    _c, gsd, ex = _io(recs)
    bl = cb.docket_stamp(docket, True, {}, gsd, ex)
    assert bl["right"] is False and bl["filed_on"] == _day(9)
    dd._write_docket_prediction("a", {**docket, "coach_a": "a", "coach_b": "b"}, "confirmed", 59, _day(17), bl)
    assert t.puts and t.puts[-1]["baseline"]["right"] is False
    import inspect

    assert "coach_baseline.docket_stamp(" in inspect.getsource(dd._resolve_one)


# ── the API ────────────────────────────────────────────────────────────────────────────


def _api_rows():
    return [
        _row("a1", "confirmed", baseline=_scored(False)),
        _row("a2", "refuted", baseline=_scored(True)),
        _row("a3", "refuted", kind="point", tolerance=1, baseline=_scored(None)),
        _row("a4", "pending"),
    ]


def _hook(table, **kw):
    pk = kw["KeyConditionExpression"]._values[0]._values[1]
    return {"Items": [dict(r) for r in _api_rows()] if pk == "COACH#sleep_coach" else []}


def test_api_predictions_serves_the_rules_counts(monkeypatch):
    from web import site_api_coach as api

    monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=_hook))
    body = json.loads(api.handle_predictions({})["body"])
    cmp_ = body["comparison"]
    d, n = cmp_["records"]["direction"], cmp_["records"]["number"]
    assert (d["scored"], d["coach_right_on_scored"], d["rule_right"], d["unscorable"]) == (2, 1, 1, 0)
    assert (n["graded"], n["scored"], n["unscorable"]) == (1, 0, 1)
    assert cmp_["sentence"], "the one line a page prints"
    assert body["by_coach"]["sleep"]["comparison"]["records"]["direction"]["scored"] == 2


def test_api_calibration_serves_the_same_comparison(monkeypatch):
    from web import site_api_coach as api

    monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=_hook))
    body = json.loads(api.handle_calibration({})["body"])
    assert body["comparison"]["records"]["direction"]["scored"] == 2
    sleep = next(c for c in body["coaches"] if c["coach_id"] == "sleep")
    assert sleep["comparison"]["records"] == body["comparison"]["records"]


def test_every_record_producer_serves_its_comparison():
    """The SET of server-side record producers: every module that serves a coach record
    also serves `comparison` beside it (a source sweep over lambdas/web + the renderer)."""
    import pathlib
    import re

    root = pathlib.Path(_REPO) / "lambdas"
    missing = []
    for p in sorted(list((root / "web").glob("*.py")) + [root / "coach" / "coach_observatory_renderer.py"]):
        src = p.read_text()
        if re.search(r"coach_record\.(for_coach|for_coach_with_rows|record_from_rows)\(", src) and "comparison" not in src:
            missing.append(p.name)
        if re.search(r"coach_baseline\.for_coach\(", src) and '"comparison": comparison' not in src:
            missing.append(p.name)
    assert not missing, f"serve a coach record without its comparison: {missing}"


# ── the back-fill ──────────────────────────────────────────────────────────────────────


def test_backfill_plan_skips_stamped_rows_and_apply_is_idempotent(monkeypatch, capsys):
    import backfill_coach_baseline_4585 as bf

    graded = dict(_row("g", "refuted"), outcome_notes=json.dumps({"actual_value": 0.01}))
    stamped = _row("s", "confirmed", baseline=_scored(True))
    t = FakeDdbTable(rows=[graded, stamped])
    io = (lambda *a, **k: [], lambda r, m: [], BAND)
    rows = bf.plan(t, ["sleep_coach"], io)
    assert [r["prediction_id"] for _c, r, _s in rows] == ["g"]
    assert rows[0][2]["right"] is True

    class _Ev:
        table = t
        _get_source_data = staticmethod(lambda *a, **k: [])
        _extract_metric_series = staticmethod(lambda r, m: [])
        DIRECTIONAL_NOISE_THRESHOLD = BAND

    monkeypatch.setattr(bf, "_evaluator", lambda: _Ev)
    monkeypatch.setattr(bf, "_coach_ids", lambda: ["sleep_coach"])
    assert bf.main([]) == 0
    assert t.updates == [], "the default is a dry run — nothing written"
    assert "dry run" in capsys.readouterr().out
    assert bf.main(["--apply"]) == 0
    assert len(t.updates) == 1 and "attribute_not_exists(baseline)" in t.updates[0]["ConditionExpression"]
