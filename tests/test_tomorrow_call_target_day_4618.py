"""tests/test_tomorrow_call_target_day_4618.py — a number call settles on the day its own
sentence names (#4618, epic #4580).

THE DEFECT: "Recovery will soften to roughly 59% tomorrow", filed September 14, was stored
with a target fourteen days out and graded right on September 28's reading; six more
"tomorrow" calls were pending with due dates in 2032 (the year of an ISO date read as a
day count), and a number stated for September 20 was filed as a forecast on September 21.

Pins:
  * the sentence -> target-day derivation (``prediction_windows.sentence_target_day``):
    "tomorrow", "tonight", a named date, a reference date, no time phrase;
  * the writer: the sentence outranks the extractor's hint, a sentence with no time phrase
    is written exactly as before, a number stated for a day already past is an observation;
  * the write-time bound: a call due more than a year out is refused as a pending call;
  * the grader: a number call is due on its target day (no domain clamp), and a reading
    the coach had already seen when filing can never settle it;
  * the re-grade script: the plan for each row class, that a named day with no reading is
    withdrawn rather than given a borrowed reading, that every write is Decimal-safe,
    conditional and keeps the old verdict, and that a second run changes nothing.

Everything here is pure or runs against an in-memory fake — no AWS.
"""

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import regrade_tomorrow_calls_4618 as regrade  # noqa: E402
from coach import (  # noqa: E402
    prediction_emission as pe,
    prediction_point_grader as grader,
    prediction_windows as pw,
)
from common.pacific_time import pacific_date_of  # noqa: E402

GENESIS = "2026-09-06"
TOL = (18.5929, "±1 SD of the trailing 30-day personal series (n=31 readings, SD=18.5929)", 31)


def _no_direction(*_a):
    return None


def _resolve(claim, hint=None, filed="2026-09-14", metric="recovery_score", tolerance=TOL):
    pred = {"timeframe_hint": hint} if hint is not None else {}
    return pe.resolve_eval_spec(claim, metric, pred, filed, lambda _m: tolerance, _no_direction)


# ── the derivation ──────────────────────────────────────────────────────────────────────


def test_tomorrow_is_the_day_after_the_call_was_filed():
    assert pw.sentence_target_day("Recovery will soften to roughly 59% tomorrow (from 73% on 2026-09-12).", "2026-09-14") == (
        "2026-09-15",
        "tomorrow",
    )
    assert pw.sentence_target_day("Tomorrow's recovery will be 83.7%", "2026-09-30") == ("2026-10-01", "tomorrow")
    assert pw.sentence_target_day("Weight tomorrow morning will be 326.8 lbs", "2026-12-31") == ("2027-01-01", "tomorrow")


def test_tonight_is_the_next_days_reading():
    # Tonight's sleep is recorded on the day he wakes: the day after filing.
    assert pw.sentence_target_day("Tonight's sleep duration will land around 7 hours", "2026-09-09") == ("2026-09-10", "tonight")


def test_a_named_date_after_filing_is_the_target_and_a_date_before_it_is_a_reference():
    assert pw.sentence_target_day("Weight will sit at 318 lbs by 2026-09-20", "2026-09-14") == ("2026-09-20", "named_date")
    # A date on or before the filing day is what the call is measured against, never its target.
    assert pw.sentence_target_day("Recovery will hold near 70% after the 73% on 2026-09-12", "2026-09-14") == (None, None)
    # ...and the relative word outranks any date in the sentence.
    assert pw.sentence_target_day("Recovery will be around 52.9% tomorrow (2026-09-10)", "2026-09-11")[0] == "2026-09-12"


def test_no_time_phrase_names_no_day():
    assert pw.sentence_target_day("Recovery will be around 52.9%", "2026-09-13") == (None, None)
    # "today" is the reference in these sentences, not a target.
    assert pw.sentence_target_day("Recovery will be modestly above today's 44%", "2026-09-13") == (None, None)
    assert pw.sentence_target_day("", "2026-09-13") == (None, None)
    assert pw.sentence_target_day("Recovery will be 60% tomorrow", "not-a-day") == (None, None)


def test_tomorrow_is_counted_on_the_pacific_day_the_call_was_filed():
    # A call written at 8:12 pm Pacific on September 30 is stamped 03:12 UTC on October 1.
    # Its filing day is the Pacific one, so its "tomorrow" is October 1 — not October 2.
    filed = pacific_date_of("2026-10-01T03:12:35+00:00")
    assert filed == "2026-09-30"
    assert pw.sentence_target_day("Recovery will reach around 64.7% tomorrow", filed)[0] == "2026-10-01"


def test_a_day_stated_right_after_the_number_is_the_day_the_number_is_for():
    assert pw.day_named_after_number("% on the night of 2026-09-15") == "2026-09-15"
    assert pw.day_named_after_number("% on 2026-09-20 based on current model") == "2026-09-20"
    assert pw.day_named_after_number(" lbs by 2026-09-20") == "2026-09-20"
    assert pw.day_named_after_number("% tomorrow (from 73% on 2026-09-12)") is None
    assert pw.day_named_after_number(" hours, with an 80% interval") is None
    shape = pe.classify_claim_shape("Recovery would land around 59.3% on the night of 2026-09-15", "recovery_score")
    assert shape["shape"] == "level" and shape["named_day"] == "2026-09-15"
    assert (
        pe.classify_claim_shape("Recovery will soften to roughly 59% tomorrow (from 73% on 2026-09-12).", "recovery_score")["named_day"]
        is None
    )
    assert pw.names_day_already_past("2026-09-15", "2026-09-17") and pw.names_day_already_past("2026-09-17", "2026-09-17")
    assert not pw.names_day_already_past("2026-09-18", "2026-09-17") and not pw.names_day_already_past(None, "2026-09-17")


# ── the writer ──────────────────────────────────────────────────────────────────────────


def test_the_sentence_outranks_the_extractors_hint():
    # The live specimen: the extractor's hint gave fourteen days; the sentence says tomorrow.
    for hint in ("14 days", "2 weeks", "next day (2026-09-13)", "over the coming month"):
        spec, window, shape = _resolve("Recovery will soften to roughly 59% tomorrow (from 73% on 2026-09-12).", hint)
        assert (spec["type"], spec["target_date"], window, shape) == ("point", "2026-09-15", 1, "level"), hint
        assert spec["evaluation_window_days"] == 1
    spec, window, _ = _resolve(
        "Tonight's sleep duration will land around 7 hours", "2 weeks", filed="2026-09-09", metric="sleep_duration_hours"
    )
    assert (spec["target_date"], window) == ("2026-09-10", 1)


def test_a_sentence_with_no_time_phrase_is_written_exactly_as_before():
    spec, window, _ = _resolve("Recovery will be around 52.9%", filed="2026-09-13")
    assert (spec["type"], spec["target_date"], window) == ("point", "2026-09-27", 14)
    spec, window, _ = _resolve("Recovery will be around 52.9%", "3 weeks", filed="2026-09-13")
    assert (spec["target_date"], window) == ("2026-10-04", 21)
    spec, window, _ = _resolve("Weight will sit at 318 lbs by 2026-09-20", metric="weight_lbs", tolerance=(3.9, "±1 SD", 30))
    assert (spec["target_date"], window) == ("2026-09-20", 6)
    # A direction call is untouched by any of this.
    spec, window, shape = pe.resolve_eval_spec(
        "HRV will improve tomorrow", "hrv", {"timeframe_hint": "2 weeks"}, "2026-09-14", lambda _m: None, lambda *_a: "up"
    )
    assert (spec["type"], window, shape) == ("directional", 14, "other")


def test_a_number_stated_for_a_day_already_past_is_an_observation_not_a_pending_call():
    for claim, filed in (
        ("Recovery would land around 59.3% on the night of 2026-09-15", "2026-09-17"),
        ("Recovery score is expected to hold around 90.9% on 2026-09-20 based on current model", "2026-09-21"),
    ):
        spec, _window, shape = _resolve(claim, filed=filed)
        assert spec["type"] == "qualitative" and shape == "level"
        record = pe.build_prediction_record("sleep_coach", filed, claim, spec, 0.5, "observational")
        assert (record["status"], record["gradeable_by"]) == ("observation", "none")


def test_a_timeframe_hint_is_never_read_as_a_window_past_a_year():
    assert pe.prediction_window_days("night of 2026-09-19, next day") == 14  # was 2,026 days: due 2032
    assert pe.prediction_window_days("another week at 145+ g/day") == 14  # was 1,015 days: due 2029
    assert pe.prediction_window_days("2026-09-14 two-week window") == 14  # was 14,182 days: due 2065
    # ...and every ordinary hint reads as it always did.
    assert [pe.prediction_window_days(h) for h in ("tomorrow", "tonight", "2 weeks", "3 days", "next month", "", "soon")] == [
        1,
        1,
        14,
        3,
        30,
        14,
        14,
    ]
    assert pe.prediction_window_days("52 weeks") == 364 and pe.prediction_window_days("400 days") == 14


# ── the write-time bound ────────────────────────────────────────────────────────────────


def test_a_due_date_more_than_a_year_out_is_refused_at_write_time():
    far = pe.build_point_eval_spec("recovery_score", 63.5, 19.29, "±1 SD", 2026, "2026-09-15")
    assert far["target_date"] == "2032-04-02"  # the live row
    record = pe.build_prediction_record(
        "explorer_coach", "2026-09-15", "Whoop recovery will rebound to approximately 63.5%", far, 0.5, "observational"
    )
    assert (record["status"], record["gradeable_by"]) == ("observation", "none")
    assert "2032-04-02" in record["emission_refused"] and "365 days" in record["emission_refused"]
    # A direction call is bounded the same way (the live 2029 rows were directional).
    direction = pe.build_prediction_eval_spec("deep_pct", "up", 1015)
    refused = pe.build_prediction_record("sleep_coach", "2026-09-20", "Deep sleep will improve", direction, 0.5, "observational")
    assert refused["status"] == "observation" and refused["emission_refused"]


def test_a_call_due_within_the_year_is_filed_as_before():
    spec = pe.build_point_eval_spec("recovery_score", 59.0, 18.59, "±1 SD", 1, "2026-09-14")
    record = pe.build_prediction_record(
        "glucose_coach", "2026-09-14", "Recovery will soften to roughly 59% tomorrow", spec, 0.5, "observational"
    )
    assert (record["status"], record["gradeable_by"]) == ("pending", "deterministic") and "emission_refused" not in record
    assert pw.refuse_due("2026-09-14", dict(spec, target_date="2027-09-14", evaluation_window_days=365), "recovery") is None
    assert pw.refuse_due("2026-09-14", dict(spec, target_date="2027-09-15", evaluation_window_days=366), "recovery")
    # The longest domain minimum (labs, 60 days) is nowhere near the bound.
    assert pw.refuse_due("2026-09-14", pe.build_prediction_eval_spec("hrv", "up", 14), "cholesterol") is None
    assert pw.refuse_due(None, spec, "recovery") is None


# ── the grader ──────────────────────────────────────────────────────────────────────────


def test_a_number_call_is_due_on_its_target_day_and_a_trend_call_keeps_its_minimum():
    point = {"type": "point", "evaluation_window_days": 1}
    assert pw.effective_window_days(point, "recovery") == 1
    assert pw.due_date("2026-10-03", point, "recovery") == "2026-10-04"
    assert pw.effective_window_days({"type": "point", "evaluation_window_days": 14}, "recovery") == 14
    assert pw.effective_window_days({"type": "directional", "evaluation_window_days": 1}, "recovery") == 14
    assert pw.effective_window_days({"type": "directional", "evaluation_window_days": 1}, "weight") == 28


def _io(series):
    """The evaluator's two data helpers over a fixed {day: value} series."""

    def get_source_data(_source, _cache, _today, lookback_days=30, include_pilot=False):
        return [{"date": d, "v": v} for d, v in sorted(series.items())]

    def extract_metric_series(records, _metric):
        return [(r["date"], r["v"]) for r in records]

    return get_source_data, extract_metric_series


def _grade(series, filed, target, threshold=59.0, tolerance=18.5929):
    get, extract = _io(series)
    spec = {"type": "point", "metric": "recovery_score", "threshold": threshold, "tolerance": tolerance, "target_date": target}
    return grader.evaluate_point({"created_date": filed}, spec, {}, "2026-10-04", get_source_data=get, extract_metric_series=extract)


def test_a_reading_the_coach_had_already_seen_never_settles_the_call():
    # No reading on September 15. The two-day look-back used to reach September 14's own
    # reading — the one on the page when the call was written — and grade the call on it.
    got = _grade({"2026-09-13": 73.0, "2026-09-14": 60.0}, filed="2026-09-14", target="2026-09-15")
    assert got["status"] == "inconclusive" and got["actual_value"] is None
    got = _grade({"2026-09-14": 60.0, "2026-09-15": 82.0}, filed="2026-09-14", target="2026-09-15")
    assert (got["status"], got["actual_value"]) == ("refuted", 82.0)
    # A longer call keeps its look-back: a missed reading on the day is not a miss.
    got = _grade({"2026-09-14": 60.0, "2026-09-27": 64.0}, filed="2026-09-14", target="2026-09-28")
    assert (got["status"], got["actual_value"]) == ("confirmed", 64.0)


# ── the re-grade script ─────────────────────────────────────────────────────────────────

RECOVERY = {"2026-09-13": 59.0, "2026-09-14": 70.0, "2026-09-15": 82.0, "2026-09-28": 64.0, "2026-10-01": 62.0}


def _row(pid, claim, filed, status, *, target=None, window=14, kind="point", coach="glucose_coach", reading=None, **extra):
    spec = {"type": kind, "metric": "recovery_score", "evaluation_window_days": window}
    if kind == "point":
        spec.update(threshold=59.0, tolerance=18.5929, tolerance_rule="±1 SD", condition="within", target_date=target)
    else:
        spec.update(condition="up", threshold=None)
    graded = status in ("confirmed", "refuted")
    return {
        "pk": f"COACH#{coach}",
        "sk": f"PREDICTION#{pid}",
        "prediction_id": pid,
        "coach_id": coach,
        "created_date": filed,
        "claim_natural": claim,
        "evaluation": spec,
        "subdomain": "recovery",
        "status": status,
        "outcome": status if graded else None,
        "outcome_date": target if graded else None,
        "outcome_notes": json.dumps({"actual_value": reading, "reason": "old reason", "algo_version": "1.0"}) if graded else None,
        "phase": "experiment",
        **extra,
    }


def _rows():
    return {
        "glucose_coach": [
            _row(
                "soften",
                "Recovery will soften to roughly 59% tomorrow (from 73% on 2026-09-12).",
                "2026-09-14",
                "confirmed",
                target="2026-09-28",
                reading=64.0,
            ),
            _row("next_day", "Recovery score will be 59% tomorrow", "2026-09-13", "confirmed", target="2026-09-14", window=1, reading=70.0),
            _row("no_day", "Recovery will be around 59%", "2026-09-14", "confirmed", target="2026-09-28", reading=64.0),
            _row("dark_day", "Recovery will be roughly 59% tomorrow", "2026-09-19", "confirmed", target="2026-10-03", reading=64.0),
        ],
        "mind_coach": [
            _row(
                "recalled",
                "Recovery would land around 59% on the night of 2026-09-15",
                "2026-09-17",
                "confirmed",
                target="2026-10-01",
                coach="mind_coach",
                reading=62.0,
            ),
            _row(
                "far",
                "Recovery score will be 59% tomorrow with 80% confidence interval of 60.9–100%",
                "2026-09-26",
                "pending",
                target="2032-04-13",
                window=2026,
                coach="mind_coach",
            ),
            _row(
                "far_trend",
                "Deep sleep should improve once protein holds",
                "2026-09-20",
                "pending",
                window=1015,
                kind="directional",
                coach="mind_coach",
            ),
            _row(
                "recalled_pending",
                "Recovery score is expected to hold around 59% on 2026-09-20 based on current model",
                "2026-09-21",
                "pending",
                target="2026-10-05",
                coach="mind_coach",
            ),
            _row(
                "fine_pending",
                "Recovery will reach 59% tomorrow",
                "2026-10-03",
                "pending",
                target="2026-10-04",
                window=1,
                coach="mind_coach",
            ),
        ],
    }


def _plan(rows=None, exclude=()):
    get, extract = _io(RECOVERY)
    return regrade.plan(rows or _rows(), genesis=GENESIS, today="2026-10-04", io=(get, extract), noise_band=0.02, exclude=exclude)


def _by_id(entries):
    return {e["prediction_id"]: e for e in entries}


def test_the_plan_grades_a_tomorrow_call_on_the_day_it_named_and_keeps_the_old_grade():
    got = _by_id(_plan())
    soften = got["soften"]
    assert (soften["action"], soften["named_day"], soften["basis"]) == ("regrade", "2026-09-15", "tomorrow")
    assert (soften["status"], soften["old_target"], soften["old_reading"]) == ("confirmed", "2026-09-28", 64.0)
    assert (soften["new_status"], soften["new_reading"]) == ("refuted", 82.0)
    assert (soften["new_spec"]["target_date"], soften["new_spec"]["evaluation_window_days"]) == ("2026-09-15", 1)
    assert "next_day" not in got and "fine_pending" not in got, "a call already graded or due on the day it named is not touched"
    assert (got["no_day"]["action"], got["no_day"]["new_status"]) == ("unchanged:no-day-named", "confirmed")


def test_a_named_day_with_no_reading_is_withdrawn_and_no_reading_is_invented():
    dark = _by_id(_plan())["dark_day"]  # September 20 has no reading; the 19th and 21st are not borrowed
    assert (dark["action"], dark["named_day"]) == ("withdraw:no-reading", "2026-09-20")
    assert dark["new_reading"] is None and dark["new_status"] == "inconclusive" and "regrade" not in dark


def test_a_number_stated_for_a_day_already_past_is_withdrawn_graded_or_pending():
    got = _by_id(_plan())
    assert (got["recalled"]["action"], got["recalled"]["new_status"], got["recalled"]["named_day"]) == (
        "withdraw:not-a-forecast",
        "observation",
        "2026-09-15",
    )
    assert (got["recalled_pending"]["action"], got["recalled_pending"]["new_status"]) == ("withdraw:not-a-forecast", "observation")


def test_every_pending_call_due_more_than_a_year_out_is_brought_back_inside_it():
    got = _by_id(_plan())
    far = got["far"]
    assert (far["action"], far["old_target"]) == ("respecify", "2032-04-13")
    assert (far["new_spec"]["target_date"], far["new_spec"]["evaluation_window_days"]) == ("2026-09-27", 1)
    trend = got["far_trend"]
    assert (trend["action"], trend["new_spec"]["evaluation_window_days"]) == ("respecify", 14)
    after = regrade.after_rows(_rows(), _plan())
    for rows in after.values():
        for row in rows:
            if row["status"] == "pending":
                assert pw.refuse_due(row["created_date"], row["evaluation"], row["subdomain"]) is None, row["prediction_id"]


def test_the_record_before_and_after_is_counted_from_the_same_rows():
    rows = _rows()
    before = regrade.records(rows, GENESIS)
    after = regrade.records(regrade.after_rows(rows, _plan()), GENESIS)
    assert (before["glucose_coach"]["confirmed"], before["glucose_coach"]["n"]) == (4, 4)
    assert (after["glucose_coach"]["confirmed"], after["glucose_coach"]["n"]) == (2, 3)  # one flipped, one withdrawn
    assert (before["mind_coach"]["confirmed"], before["mind_coach"]["n"]) == (1, 1)
    assert (after["mind_coach"]["confirmed"], after["mind_coach"]["n"]) == (0, 0)  # the recollection leaves the record
    assert rows == _rows(), "the plan and the tally never mutate the rows they read"


def test_an_excluded_row_and_an_archived_phase_are_left_alone():
    assert "soften" not in _by_id(_plan(exclude={"PREDICTION#soften"}))
    rows = _rows()
    rows["glucose_coach"][0]["tombstone"] = True
    assert "soften" not in _by_id(_plan(rows))


class _Table:
    """Captures update_item calls and honours the two condition shapes the script writes."""

    def __init__(self, rows):
        self.items = {(r["pk"], r["sk"]): dict(r) for rs in rows.values() for r in rs}
        self.calls = []

    def update_item(self, **kw):
        item = self.items[(kw["Key"]["pk"], kw["Key"]["sk"])]
        guard = "respecified_at" if "respecified_at" in kw["ConditionExpression"] else "verdict_correction"
        if item["status"] != kw["ExpressionAttributeValues"][":prior"] or guard in item:
            raise RuntimeError("ConditionalCheckFailedException")
        self.calls.append(kw)
        values = kw["ExpressionAttributeValues"]
        for part in kw["UpdateExpression"].removeprefix("SET ").split(", "):
            name, ref = part.split(" = ")
            item[kw["ExpressionAttributeNames"].get(name, name)] = values[ref]


def _floats(obj):
    if isinstance(obj, float):
        return [obj]
    if isinstance(obj, dict):
        return [f for v in obj.values() for f in _floats(v)]
    if isinstance(obj, (list, tuple)):
        return [f for v in obj for f in _floats(v)]
    return []


def test_the_writes_are_decimal_safe_conditional_and_keep_the_old_verdict():
    table = _Table(_rows())
    entries = _plan()
    written = regrade.apply(table, entries, "1.0", now="2026-10-05T00:00:00+00:00")
    assert written == 6 and len(table.calls) == 6  # the unchanged row is never written
    for call in table.calls:
        assert not _floats(call["ExpressionAttributeValues"]), "boto3 rejects a float — every number is a Decimal"
        assert call["ConditionExpression"].startswith("#s = :prior AND attribute_not_exists(")
    soften = table.items[("COACH#glucose_coach", "PREDICTION#soften")]
    assert (soften["status"], soften["outcome"]) == ("refuted", "refuted")
    assert soften["evaluation"]["target_date"] == "2026-09-15" and soften["evaluation"]["tolerance"] == Decimal("18.5929")
    correction = soften["verdict_correction"]
    assert (correction["issue"], correction["action"], correction["new_status"]) == ("#4618", "regrade", "refuted")
    prior = correction["prior"]
    assert (prior["status"], prior["target_date"], prior["reading"]) == ("confirmed", "2026-09-28", Decimal("64.0"))
    assert json.loads(prior["outcome_notes"])["reason"] == "old reason"
    notes = json.loads(soften["outcome_notes"])
    assert notes["actual_value"] == 82.0 and "on 2026-09-15" in notes["reason"]
    assert notes["verdict_correction"]["prior_status"] == "confirmed" and notes["verdict_correction"]["prior_reason"] == "old reason"
    dark = table.items[("COACH#glucose_coach", "PREDICTION#dark_day")]
    assert dark["status"] == "inconclusive" and json.loads(dark["outcome_notes"])["actual_value"] is None
    assert dark["verdict_correction"]["prior"]["status"] == "confirmed"
    recalled = table.items[("COACH#mind_coach", "PREDICTION#recalled")]
    assert (recalled["status"], recalled["gradeable_by"]) == ("observation", "none")
    far = table.items[("COACH#mind_coach", "PREDICTION#far")]
    assert far["status"] == "pending" and far["evaluation"]["target_date"] == "2026-09-27"
    assert far["respecified_from"]["evaluation"]["target_date"] == "2032-04-13" and "#4618" in far["respecified_reason"]
    pending_recalled = table.items[("COACH#mind_coach", "PREDICTION#recalled_pending")]
    assert pending_recalled["status"] == "observation" and pending_recalled["respecified_from"]["status"] == "pending"


def test_a_second_run_changes_nothing(capsys):
    table = _Table(_rows())
    entries = _plan()
    assert regrade.apply(table, entries, "1.0") == 6
    # The stale plan is refused row by row by the write conditions...
    assert regrade.apply(table, entries, "1.0") == 0 and "NOT WRITTEN" in capsys.readouterr().out
    # ...and a fresh plan over the corrected rows proposes no write at all.
    corrected: dict = {}
    for (pk, _sk), item in table.items.items():
        corrected.setdefault(pk.removeprefix("COACH#"), []).append(regrade.decimals_to_float(item))
    assert [e for e in _plan(corrected) if e["action"] in regrade.WRITES] == []


def test_the_dry_run_tables_name_every_column_the_owner_approves_on():
    entries = _plan()
    graded = regrade.graded_table([e for e in entries if e["status"] not in regrade.PENDING])
    line = next(row for row in graded.splitlines() if "soften to roughly" in row)
    for cell in (
        "glucose-20260914-",
        "glucose_coach",
        "2026-09-14",
        "2026-09-28",
        "right (64)",
        "2026-09-15 (tomorrow)",
        "| 82 |",
        "wrong",
        "regrade",
    ):
        assert cell in line, cell
    assert "no reading that day" in graded and "withdrawn: inconclusive" in graded
    pending = regrade.pending_table([e for e in entries if e["status"] in regrade.PENDING])
    assert "2032-04-13" in pending and "2026-09-27 / 1 d" in pending and "withdrawn: observation" in pending
    tally = regrade.record_table(regrade.records(_rows(), GENESIS), regrade.records(regrade.after_rows(_rows(), entries), GENESIS))
    assert "| glucose_coach | 4 of 4 | 2 of 3  **changed** |" in tally and "| **all coaches** | 5 of 5 | 2 of 3 |" in tally


def test_the_regraded_live_specimen_gains_its_page():
    # The wire fixture's own row: once its target is the day its sentence names, the
    # settled-call route gives it a page — with no change to the route.
    from web import site_api_calls as calls

    with open(os.path.join(_REPO, "tests", "fixtures", "calls_wire_4586", "prediction_rows.json"), encoding="utf-8") as fh:
        rows = json.load(fh)["glucose"]
    row = next(r for r in rows if r.get("prediction_id") == "pred_20260914_recovery_will_soften_to_roughly_59_tomo")
    assert calls.page_kind(row) == (None, calls.OTHER_DAY)
    day, _basis = pw.sentence_target_day(row["claim_natural"], row["created_date"])
    row["evaluation"] = dict(row["evaluation"], target_date=day)
    assert calls.page_kind(row) == ("number", None)
