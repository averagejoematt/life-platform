"""tests/test_v9_api_routes_5532.py — the four v9 reads: /api/series, /api/ledger_export, /api/chapters, /api/pairs (#5532).

The fixtures are the wire:
  * ``tests/fixtures/calls_wire_4586/prediction_rows.json`` — every coach's PREDICTION# partition as the
    shared projected fetch returns it (captured read-only 2026-10-04, #4586);
  * ``tests/fixtures/v9_api_5532/posts.json`` — the live ``/journal/posts.json`` manifest (2026-10-31);
  * ``tests/fixtures/v9_api_5532/chronicle_rows.json`` — the chronicle partition's DATE# rows >= genesis as
    the read-only query returned them on 2026-10-31 (``week_number`` is a STRING on the wire).

Pins:
  * /api/series — one row per calendar day; ``present`` and ``gap`` are distinct (a diary stub is a gap,
    a missing row is not); steps resolve through metric_truth; a Tier-2 key is a 404 that serializes
    nothing, indistinguishable from an unknown key; bad days are 400; the bare route is the catalogue.
  * /api/ledger_export — ``total`` equals /api/predictions ``overall.total`` on the SAME rows (run through
    the real handler); the item shape is pinned on every real row; diary-claim rows are excluded; flags
    and corrections ride off the row, ``[]`` otherwise; paging; a failed read is 503 / degraded.
  * /api/chapters — on the live manifest + rows: weeks 1–6 published, 7 skipped with its reason, 8 held
    with NO title; the writer's marker is the skipped reason; the edition's ``held`` is the same reader.
  * /api/pairs — stats_core's numbers (recomputed here), FDR across the whole tested family, under-n
    cells untested, every method id in the registry, and no verdict word anywhere in the payload.
  * stats_core.spearman_rho — ties averaged, monotone = 1, registered with a live fingerprint.
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import math
import os
import random
import sys

import pytest

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from common import journal_silence, stats_core  # noqa: E402
from experiment import methods_registry as mr  # noqa: E402
from privacy import field_tiers  # noqa: E402
from web import (
    site_api_chapters as chapters,  # noqa: E402
    site_api_coach_ledger as coach_ledger,  # noqa: E402
    site_api_edition as edition,  # noqa: E402
    site_api_lambda as L,  # noqa: E402
    site_api_ledger_export as ledger,  # noqa: E402
    site_api_pairs as pairs,  # noqa: E402
    site_api_series as series,  # noqa: E402
)

GENESIS = "2026-09-06"
TODAY = "2026-10-31"
_FIX = os.path.join(_REPO, "tests", "fixtures", "v9_api_5532")
_ROWS = os.path.join(_REPO, "tests", "fixtures", "calls_wire_4586", "prediction_rows.json")


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _body(resp):
    return json.loads(resp["body"])


def _event(**qs):
    return {"queryStringParameters": {k: str(v) for k, v in qs.items()}} if qs else {"queryStringParameters": None}


# ═══════════════════════════════════════════════════════════════════════════════════════
# routing
# ═══════════════════════════════════════════════════════════════════════════════════════


def test_the_four_routes_are_registered_as_get_only_query_string_routes():
    for path, fn in {
        "/api/series": series.handle_series,
        "/api/ledger_export": ledger.handle_ledger_export,
        "/api/chapters": chapters.handle_chapters,
        "/api/pairs": pairs.handle_pairs,
    }.items():
        assert path in L.ROUTES and L.ROUTES[path] is None, f"{path}: ROUTES placeholder missing"
        methods, handler = L._SIMPLE_ROUTES[path]
        assert methods == {"GET"} and handler is fn
        assert L._dispatch_route({"queryStringParameters": None}, path, "POST")["statusCode"] == 405


def test_the_bare_series_route_dispatches_to_the_catalogue_without_a_table_read():
    resp = L._dispatch_route({"queryStringParameters": None}, "/api/series", "GET")
    assert resp["statusCode"] == 200
    body = _body(resp)
    assert [m["metric"] for m in body["metrics"]] == list(series.SERIES)
    assert "max-age=600" in resp["headers"]["Cache-Control"]


# ═══════════════════════════════════════════════════════════════════════════════════════
# /api/series
# ═══════════════════════════════════════════════════════════════════════════════════════


def _whoop_rows():
    return [
        {"sk": "DATE#2026-10-27", "date": "2026-10-27", "hrv": 41.2, "resting_heart_rate": 58, "step_count": 7000},
        {"sk": "DATE#2026-10-29", "date": "2026-10-29", "hrv": 0, "resting_heart_rate": 61, "step_count": 0},  # 0 ms HRV: no reading
        {"sk": "DATE#2026-10-30", "date": "2026-10-30", "hrv": 44.0, "resting_heart_rate": 57, "step_count": 9100},
    ]


def _mf_rows():
    return [
        {"sk": "DATE#2026-10-27", "date": "2026-10-27", "total_calories_kcal": 1810, "total_protein_g": 171, "entries_count": 9},
        {
            "sk": "DATE#2026-10-28",
            "date": "2026-10-28",
            "total_calories_kcal": 80,
            "total_protein_g": 15,
            "entries_count": 0,
            "food_log": [],
        },  # #5519 stub
        {
            "sk": "DATE#2026-10-29",
            "date": "2026-10-29",
            "total_calories_kcal": 0,
            "total_protein_g": 0,
            "entries_count": 2,
        },  # an honest logged zero
        {
            "sk": "DATE#2026-10-30",
            "date": "2026-10-30",
            "total_calories_kcal": 95,
            "total_protein_g": 12,
            "food_log": [],
        },  # legacy stub: no count
    ]


def _query_for(rows_by_source):
    def query(source, start, end, **_kw):
        return [dict(r) for r in rows_by_source.get(source, []) if start <= r["date"] <= end]

    return query


def test_series_serves_one_row_per_calendar_day_with_presence_and_gap_distinct():
    q = _query_for({"whoop": _whoop_rows(), "macrofactor": _mf_rows()})
    hrv = _body(series.handle_series(_event(metric="hrv", **{"from": "2026-10-27", "to": "2026-10-31"}), query=q, today=TODAY))
    assert hrv["metric"] == "hrv" and hrv["source_id"] == "whoop" and hrv["unit"] == "ms" and hrv["method_ids"] == []
    assert hrv["window"] == {"from": "2026-10-27", "to": "2026-10-31"} and hrv["as_of"] == TODAY
    assert [d["date"] for d in hrv["days"]] == ["2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31"]
    by = {d["date"]: d for d in hrv["days"]}
    assert by["2026-10-27"] == {"date": "2026-10-27", "value": 41.2, "present": True, "gap": False}
    assert by["2026-10-28"] == {"date": "2026-10-28", "value": None, "present": False, "gap": False}  # no row: not a gap
    assert by["2026-10-29"]["present"] is True and by["2026-10-29"]["value"] == 0.0  # a device's 0 is a stored value here, not a gap
    assert hrv["n_present"] == 3 and hrv["n_gap"] == 0 and hrv["behavioral"] is False

    kcal = _body(
        series.handle_series(_event(metric="total_calories_kcal", **{"from": "2026-10-26", "to": "2026-10-30"}), query=q, today=TODAY)
    )
    by = {d["date"]: d for d in kcal["days"]}
    assert kcal["behavioral"] is True and kcal["source_id"] == "macrofactor"
    assert by["2026-10-26"] == {"date": "2026-10-26", "value": None, "present": False, "gap": False}  # no row at all
    assert by["2026-10-27"] == {"date": "2026-10-27", "value": 1810.0, "present": True, "gap": False}
    assert by["2026-10-28"] == {
        "date": "2026-10-28",
        "value": None,
        "present": False,
        "gap": True,
    }  # the stub: a logging gap, value withheld
    assert by["2026-10-29"] == {"date": "2026-10-29", "value": 0.0, "present": True, "gap": False}  # a logged zero is a value (#2221)
    assert by["2026-10-30"] == {"date": "2026-10-30", "value": None, "present": False, "gap": True}  # an empty food_log with no count
    assert "80" not in json.dumps([d["value"] for d in kcal["days"]])
    assert kcal["n_present"] == 2 and kcal["n_gap"] == 2


def test_series_projects_the_gap_columns_only_for_a_behavioral_source():
    seen = {}

    def query(source, start, end, projection=None, **_kw):
        seen[source] = projection
        return []

    series.handle_series(_event(metric="hrv"), query=query, today=TODAY)
    series.handle_series(_event(metric="total_protein_g"), query=query, today=TODAY)
    assert seen["whoop"] == ("date", "hrv")
    assert set(seen["macrofactor"]) == {"date", "total_protein_g", "entries_count", "food_log", "_format"}


def test_steps_resolve_per_day_through_metric_truth_and_name_the_source_that_answered():
    from common import metric_truth

    apple = [
        {"sk": "DATE#2026-10-28", "date": "2026-10-28", "steps": 6400},
        {"sk": "DATE#2026-10-29", "date": "2026-10-29", "steps": 5100},  # Whoop said 0 that day: Apple answers
    ]
    q = _query_for({"whoop": _whoop_rows(), "apple_health": apple})
    body = _body(series.handle_series(_event(metric="steps", **{"from": "2026-10-27", "to": "2026-10-30"}), query=q, today=TODAY))
    expected = metric_truth.resolve_by_date("steps", {"whoop": _whoop_rows(), "apple_health": apple, "garmin": []})
    by = {d["date"]: d for d in body["days"]}
    for day, res in expected.items():
        assert by[day]["value"] == res.value and by[day]["present"] is (res.value is not None)
        if res.value is not None:
            assert by[day]["source_id"] == res.source
    assert by["2026-10-27"]["source_id"] == "whoop" and by["2026-10-29"]["source_id"] == "apple_health"
    assert body["source_id"] == "resolved:steps"


def test_every_offered_key_is_publishable_and_reads_the_graders_own_source():
    from experiment.measurable_metrics import METRIC_SOURCES

    for key, spec in series.SERIES.items():
        assert series.publishable(spec), key
        assert spec.source == METRIC_SOURCES[spec.field], key
    assert [m["metric"] for m in series.offered()] == list(series.SERIES)


@pytest.mark.parametrize(
    "spec",
    [
        series.SeriesSpec("vascular_age", "withings", "vascular_age", "years"),  # TIER_OWNER_ONLY field (#2782 age-class)
        series.SeriesSpec("rhythm_ecg_avg_hr_bpm", "clinical", "rhythm_ecg_avg_hr_bpm", "bpm"),  # TIER_OWNER_ONLY clinical field
        series.SeriesSpec("spo2_percentage", "whoop", "spo2_percentage", "%"),  # a Tier-2 field on an otherwise-served source
    ],
)
def test_a_tier_2_key_is_a_404_that_serializes_nothing_and_matches_an_unknown_key(monkeypatch, spec):
    assert not field_tiers.is_publishable(field_tiers.tier_of(spec.source, spec.field))
    monkeypatch.setitem(series.SERIES, spec.key, spec)
    secret = 55.5

    def query(source, start, end, **_kw):
        return [{"sk": "DATE#2026-10-30", "date": "2026-10-30", spec.field: secret}]

    resp = series.handle_series(_event(metric=spec.key), query=query, today=TODAY)
    unknown = series.handle_series(_event(metric="no_such_metric"), query=query, today=TODAY)
    assert resp["statusCode"] == 404 and unknown["statusCode"] == 404
    assert str(secret) not in resp["body"] and spec.field not in resp["body"]
    assert _body(resp)["error"] == _body(unknown)["error"] == series.NOT_SERVED
    assert spec.key not in json.dumps(series.offered())  # the catalogue never lists it either


def test_series_window_defaults_clamps_and_rejects_non_days():
    calls = []

    def query(source, start, end, **_kw):
        calls.append((start, end))
        return []

    body = _body(series.handle_series(_event(metric="weight_lbs"), query=query, today=TODAY))
    assert body["window"] == {"from": GENESIS, "to": TODAY} and calls[-1] == (GENESIS, TODAY)
    body = _body(series.handle_series(_event(metric="weight_lbs", to="2027-01-01"), query=query, today=TODAY))
    assert body["window"]["to"] == TODAY  # never a day that has not happened
    for bad in ({"from": "yesterday"}, {"to": "2026-13-01"}, {"from": "2026-10-30", "to": "2026-10-01"}):
        resp = series.handle_series(_event(metric="weight_lbs", **bad), query=query, today=TODAY)
        assert resp["statusCode"] == 400 and _body(resp)["error"] == series.BAD_DAY
    body = _body(series.handle_series(_event(metric="weight_lbs", **{"from": "2024-01-01"}), query=query, today=TODAY))
    assert len(body["days"]) == series.MAX_SPAN_DAYS


def test_a_failed_series_read_is_a_503_never_an_empty_series():
    def query(*_a, **_k):
        raise RuntimeError("ProvisionedThroughputExceeded")

    resp = series.handle_series(_event(metric="hrv"), query=query, today=TODAY)
    assert resp["statusCode"] == 503 and "days" not in resp["body"]


# ═══════════════════════════════════════════════════════════════════════════════════════
# /api/ledger_export
# ═══════════════════════════════════════════════════════════════════════════════════════

ITEM_KEYS = {
    "item_id",
    "prediction_id",
    "coach_id",
    "coach_name",
    "retired",
    "metric",
    "claim",
    "logged_date",
    "due_date",
    "settled_date",
    "kind",
    "status",
    "confidence",
    "sealed",
    "grading",
    "simple_guess",
    "quality_flags",
    "corrections",
}
GRADING_KEYS = {"how", "actual_text", "tolerance_text", "outcome_notes"}
KINDS = {"number", "direction", "yes_no", "sealed", "observation"}


def _rows():
    return _load(_ROWS)


def _visible_pending(partition):
    """A this-cycle pending row (the fixture's first rows are tombstoned pilot-phase docket rows)."""
    return next(r for r in partition if r.get("status") == "pending" and r.get("phase") == "experiment" and not r.get("tombstone"))


def _predictions_overall(rows):
    """/api/predictions on the same rows, through the REAL handler with its injectable globals."""

    class _NoTable:
        def get_item(self, **_k):
            raise RuntimeError("no table in this test")

        def query(self, **_k):
            raise RuntimeError("no table in this test")

    g = {
        "table": _NoTable(),
        "EXPERIMENT_START": GENESIS,
        "_current_cycle": lambda: None,
        "_fetch_prediction_partition": lambda pk: rows[pk.split("#")[1].replace("_coach", "")],
        "_parallel_fetch": coach_ledger._parallel_fetch,
        "datetime": _dt.datetime,
    }
    resp = coach_ledger.handle_predictions({"queryStringParameters": {"limit": "1"}}, _g=g)
    assert resp["statusCode"] == 200
    return _body(resp)


def test_total_equals_api_predictions_overall_total_on_the_same_rows():
    rows = _rows()
    overall = _predictions_overall(rows)
    body = _body(ledger.handle_ledger_export(_event(size=200), fetch=lambda: (rows, [], []), today=TODAY))
    # `record_total` is the /api/predictions row-set; `total` is what the journal-silence guard (#5131) lets
    # through — the captured partition holds two rows whose claim speaks of the journal's silence.
    assert body["record_total"] == overall["overall"]["total"] == 147
    assert body["withheld"] == {"journal_silence": 2} and body["total"] == 145 == len(body["items"])
    counted = ledger.export_items(rows, genesis=ledger.EXPERIMENT_START, dark=[])
    per_coach = {cid: sum(1 for i in counted if i["coach_id"] == cid) for cid in rows}
    assert per_coach == {cid: overall["by_coach"][cid]["total"] for cid in rows}
    for bucket in ledger.BUCKETS:
        assert sum(1 for i in counted if i["status"] == bucket) == overall["overall"][bucket], bucket


def test_every_item_is_pinned_to_the_shape_on_every_real_row():
    body = _body(ledger.handle_ledger_export(_event(size=200), fetch=lambda: (_rows(), [], []), today=TODAY))
    assert body["page"] == 1 and body["size"] == 200 and body["pages"] == 1 and body["as_of"] == TODAY
    items = body["items"]
    assert len(items) == body["total"] and len({i["item_id"] for i in items}) == len(items)
    # the stored id alone is NOT unique across coaches: one docket bet sits on both sides' rows, and two coaches
    # filed the same sentence on 2026-09-08 — so the page's address is the coach-scoped item_id
    assert len({i["prediction_id"] for i in items}) == len(items) - 2
    assert all(i["item_id"] == f"{i['coach_id']}:{i['prediction_id']}" for i in items)
    for item in items:
        assert set(item) - {"withheld", "unsourced"} == ITEM_KEYS, item["prediction_id"]
        assert set(item["grading"]) == GRADING_KEYS and item["grading"]["how"]
        assert item["kind"] in KINDS and item["status"] in ledger.BUCKETS
        assert isinstance(item["sealed"], bool) and isinstance(item["retired"], bool)
        assert item["quality_flags"] == [] and item["corrections"] == []  # rows captured before the grader stamped them (#5533)
        assert item["simple_guess"]["state"] in ("scored", "unscorable", "not_yet_scored")
        assert item["logged_date"] and len(item["logged_date"]) == 10  # a docket row's is the day its id says the bet opened
        if item["status"] in ("confirmed", "refuted"):
            assert item["settled_date"]  # the grader's words may be absent (ADR-104: none written -> none served)
    assert [i["logged_date"] for i in items] == sorted((i["logged_date"] for i in items), reverse=True)
    sealed = [i for i in items if i["sealed"]]
    assert sealed and all(i["kind"] == "sealed" and i["logged_date"] <= GENESIS for i in sealed)  # the freeze day, not the effective date
    number = next(i for i in items if i["kind"] == "number" and i["status"] == "confirmed")
    assert number["grading"]["tolerance_text"].startswith("±1 SD of the trailing") and number["grading"]["actual_text"]
    assert number["due_date"] and number["due_date"] >= number["logged_date"]
    direction = next(i for i in items if i["kind"] == "direction")
    assert direction["grading"]["actual_text"] is None  # a slope is not a reading


def test_flags_and_corrections_ride_off_the_row_and_a_diary_claim_is_excluded():
    rows = _rows()
    flagged = copy.deepcopy(_visible_pending(rows["sleep"]))
    flagged.update(
        prediction_id="pred_20261030_flagged",
        quality_flags=["logging_gap", "low_power"],
        corrections=[
            {"original_status": "confirmed", "corrected_status": "refuted", "corrected_at": "2026-10-31T00:00:00Z", "reason": "r"}
        ],
    )
    diary = copy.deepcopy(_visible_pending(rows["sleep"]))
    diary.update(prediction_id="diary_claim_x", coach_id="")
    rows["sleep"] = [flagged, diary] + rows["sleep"]
    body = _body(ledger.handle_ledger_export(_event(size=200), fetch=lambda: (rows, [], []), today=TODAY))
    assert body["record_total"] == 148 and body["total"] == 148 - body["withheld"]["journal_silence"]
    got = next(i for i in body["items"] if i["prediction_id"] == "pred_20261030_flagged")
    assert got["quality_flags"] == ["logging_gap", "low_power"] and got["corrections"][0]["corrected_status"] == "refuted"
    assert not any(i["prediction_id"] == "diary_claim_x" for i in body["items"])


def test_a_claim_the_dossier_filter_withholds_keeps_its_place_without_its_words():
    rows = _rows()
    row = copy.deepcopy(_visible_pending(rows["sleep"]))
    row.update(
        prediction_id="pred_20261030_withheld", claim_natural="He will sleep better after fizzlewick tonight."
    )  # the suite's neutral vocabulary
    rows["sleep"].insert(0, row)
    body = _body(ledger.handle_ledger_export(_event(size=200), fetch=lambda: (rows, [], []), today=TODAY))
    got = next(i for i in body["items"] if i["prediction_id"] == "pred_20261030_withheld")
    assert got["claim"] == "" and got["withheld"] is True and got["status"]
    assert "fizzlewick" not in json.dumps(body)


def test_a_claim_resting_on_a_dark_instrument_is_held_not_quoted():
    """#4701: the same hold /api/predictions applies — the row keeps its place and grade, its words do not travel."""
    from web import claim_sourcing

    rows = _rows()
    row = copy.deepcopy(_visible_pending(rows["sleep"]))
    row.update(
        prediction_id="pred_20260920_cgm_call",
        created_date="2026-09-20",
        claim_natural="The CGM will show a flatter overnight glucose trace.",
    )
    rows["sleep"].insert(0, row)
    dark = claim_sourcing.gap_instruments(
        {"glucose_coach": {"source": "apple_health", "datatype": "cgm", "label": "CGM", "last_seen": "2026-09-15", "reason": "sensor_dark"}}
    )
    held = _body(ledger.handle_ledger_export(_event(size=200), fetch=lambda: (rows, [], dark), today=TODAY))
    got = next(i for i in held["items"] if i["prediction_id"] == "pred_20260920_cgm_call")
    assert got["claim"] == "" and got["unsourced"]["instrument"] == {"source": "apple_health", "datatype": "cgm"}
    assert got["unsourced"]["said_on"] == "2026-09-20" and got["unsourced"]["text"].startswith("Not quoted:")
    assert got["status"] == "pending" and got["logged_date"] == "2026-09-20"  # the row stays, dated and counted
    quoted = _body(ledger.handle_ledger_export(_event(size=200), fetch=lambda: (rows, [], []), today=TODAY))
    assert next(i for i in quoted["items"] if i["prediction_id"] == "pred_20260920_cgm_call")["claim"].startswith("The CGM")
    assert "CGM will show" not in json.dumps(held["items"])


def test_paging_is_stable_and_bad_paging_is_400():
    rows = _rows()
    fetch = lambda: (rows, [], [])  # noqa: E731
    whole = _body(ledger.handle_ledger_export(_event(size=200), fetch=fetch, today=TODAY))["items"]
    p1 = _body(ledger.handle_ledger_export(_event(page=1, size=50), fetch=fetch, today=TODAY))
    p2 = _body(ledger.handle_ledger_export(_event(page=2, size=50), fetch=fetch, today=TODAY))
    p3 = _body(ledger.handle_ledger_export(_event(page=3, size=50), fetch=fetch, today=TODAY))
    p9 = _body(ledger.handle_ledger_export(_event(page=9, size=50), fetch=fetch, today=TODAY))
    assert p1["items"] + p2["items"] + p3["items"] == whole and p1["pages"] == 3
    assert p9["items"] == [] and p9["total"] == p1["total"] == len(whole)
    default = _body(ledger.handle_ledger_export(_event(), fetch=fetch, today=TODAY))
    assert default["page"] == 1 and default["size"] == 100 and len(default["items"]) == 100
    for bad in ({"page": "0"}, {"size": "0"}, {"size": "201"}, {"page": "two"}):
        resp = ledger.handle_ledger_export(_event(**bad), fetch=fetch, today=TODAY)
        assert resp["statusCode"] == 400 and _body(resp)["error"] == ledger.BAD_PAGE


def test_every_partition_failing_is_503_and_a_partial_failure_is_declared():
    rows = _rows()
    all_failed = ledger.handle_ledger_export(_event(), fetch=lambda: ({}, sorted(rows), []), today=TODAY)
    assert all_failed["statusCode"] == 503
    partial = ledger.handle_ledger_export(
        _event(size=200), fetch=lambda: ({k: v for k, v in rows.items() if k != "labs"}, ["labs"], []), today=TODAY
    )
    body = _body(partial)
    assert partial["statusCode"] == 200 and "labs" in body["_meta"]["degraded"]["reason"]
    assert body["record_total"] == 147 - 9  # the nine labs rows the fixture carries are missing, and the envelope says so
    assert body["total"] == body["record_total"] - body["withheld"]["journal_silence"]

    def boom():
        raise RuntimeError("dynamo down")

    assert ledger.handle_ledger_export(_event(), fetch=boom, today=TODAY)["statusCode"] == 503


def test_the_export_projection_covers_the_predictions_sweep_plus_the_graders_fields():
    assert set(coach_ledger._PREDICTION_PROJECTION_FIELDS) <= set(ledger.PROJECTION)
    assert {"quality_flags", "corrections", "sk", "coach_id"} <= set(ledger.PROJECTION)


# ═══════════════════════════════════════════════════════════════════════════════════════
# /api/chapters
# ═══════════════════════════════════════════════════════════════════════════════════════


def _journal():
    return _load(os.path.join(_FIX, "posts.json"))


def _chronicle_rows():
    return _load(os.path.join(_FIX, "chronicle_rows.json"))["rows"]


def _chapters(journal=None, rows=None, today=TODAY):
    j = journal if journal is not None else _journal()
    r = rows if rows is not None else _chronicle_rows()
    resp = chapters.handle_chapters(_event(), query=lambda *a, **k: r, read_manifest=lambda: j, today=today)
    assert resp["statusCode"] == 200
    return _body(resp)


def test_every_program_week_since_genesis_is_listed_with_the_chronicles_own_state():
    body = _chapters()
    assert body["genesis"] == GENESIS and body["as_of"] == TODAY and body["week_length_days"] == 7
    weeks = body["weeks"]
    assert [w["week"] for w in weeks] == list(range(1, 9))  # 2026-10-31 is day 56: eight weeks, the prologue is not one
    assert (
        weeks[0]["start"] == GENESIS
        and weeks[0]["end"] == "2026-09-12"
        and weeks[7] == {**weeks[7], "start": "2026-10-25", "end": "2026-10-31"}
    )
    assert [w["status"] for w in weeks] == ["published"] * 6 + ["skipped", "held"]
    posts = {p["week"]: p for p in _journal()["posts"]}
    for w in weeks[:6]:
        p = posts[w["week"]]
        assert (w["date"], w["title"], w["url"], w["label"]) == (p["date"], p["title"], p["url"], p["label"])
    assert body["counts"] == {"published": 6, "held": 1, "skipped": 1, "pending": 0}


def test_a_skipped_week_carries_its_reason_and_a_held_week_exposes_no_title_excerpt_or_body():
    body = _chapters()
    seven, eight = body["weeks"][6], body["weeks"][7]
    assert seven["status"] == "skipped" and seven["reason"] == chapters.NO_CHAPTER
    assert seven["date"] is None and seven["title"] is None and seven["url"] is None
    assert eight["status"] == "held" and eight["drafted_at"] == "2026-10-28T15:03:53.828371+00:00"
    assert eight["title"] is None and eight["url"] is None and eight["date"] is None and eight["reason"] is None
    assert not {"excerpt", "body", "content_markdown", "content_html", "stats_line"} & set(eight)
    # the fixture row carries the draft's title on purpose: the route must never serve it
    assert "The Weight of 299" in json.dumps(_chronicle_rows()) and "The Weight of 299" not in json.dumps(body)
    assert "title" not in chapters.ROW_PROJECTION and "content" not in " ".join(chapters.ROW_PROJECTION)


def test_the_writers_pending_marker_is_the_served_reason_and_the_editions_held():
    journal = _journal()
    journal["pending"] = {
        "week": 7,
        "reason": "budget_tier_2",
        "display": "Week 7 was not written: the AI budget was paused.",
        "noted_at": "2026-10-21T15:00:00+00:00",
    }
    body = _chapters(journal)
    assert body["weeks"][6]["status"] == "skipped" and body["weeks"][6]["reason"] == "Week 7 was not written: the AI budget was paused."
    assert body["held"] == chapters.held_marker(journal) == edition._held_chapter(journal)
    assert body["held"] == {
        "week": 7,
        "reason": "budget_tier_2",
        "display": "Week 7 was not written: the AI budget was paused.",
        "noted_at": "2026-10-21T15:00:00+00:00",
    }
    # the marker on the held week reads as the held reason; a marker without a week is not a marker
    journal["pending"]["week"] = 8
    assert _chapters(journal)["weeks"][7]["reason"] == "Week 7 was not written: the AI budget was paused."
    journal["pending"] = {"reason": "x"}
    assert _chapters(journal)["held"] is None and edition._held_chapter(journal) is None
    assert edition._held_chapter(_journal()) is None  # the live manifest carries no marker


def test_the_week_in_progress_is_pending_not_skipped_and_a_future_genesis_lists_nothing():
    body = _chapters(today="2026-11-03")
    assert [w["status"] for w in body["weeks"]] == ["published"] * 6 + ["skipped", "held", "pending"]
    assert body["weeks"][8] == {**body["weeks"][8], "week": 9, "start": "2026-11-01", "end": "2026-11-07", "reason": None}
    early = chapters.compose([], {"posts": []}, GENESIS, "2026-09-06")
    assert [w["status"] for w in early["weeks"]] == ["pending"]


def test_a_week_published_in_the_store_but_not_yet_in_the_manifest_reads_as_the_stores_state():
    rows = _chronicle_rows()
    rows[-1] = {**rows[-1], "status": "published"}
    body = _chapters(rows=rows)
    assert body["weeks"][7]["status"] == "published" and body["weeks"][7]["date"] == "2026-10-27" and body["weeks"][7]["title"] is None


def test_row_week_reads_week_number_as_the_wire_writes_it_and_falls_back_to_the_date_bin():
    assert chapters.row_week({"week_number": "8", "date": "2026-10-27"}, GENESIS) == 8
    assert chapters.row_week({"week_number": 8}, GENESIS) == 8
    assert chapters.row_week({"date": "2026-10-27"}, GENESIS) == 8 and chapters.row_week({"sk": "DATE#2026-09-08"}, GENESIS) == 1
    assert chapters.row_week({"week_number": "0", "date": "2026-09-05"}, GENESIS) is None  # the prologue is not a program week


def test_a_failed_chronicle_read_is_503_and_an_unreadable_manifest_is_declared():
    def boom(*_a, **_k):
        raise RuntimeError("dynamo down")

    assert chapters.handle_chapters(_event(), query=boom, read_manifest=lambda: _journal(), today=TODAY)["statusCode"] == 503
    resp = chapters.handle_chapters(_event(), query=lambda *a, **k: _chronicle_rows(), read_manifest=lambda: None, today=TODAY)
    body = _body(resp)
    assert resp["statusCode"] == 200 and "manifest" in body["_meta"]["degraded"]["reason"]
    assert [w["status"] for w in body["weeks"]] == ["published"] * 6 + ["skipped", "held"]  # the store's rows still answer


# ═══════════════════════════════════════════════════════════════════════════════════════
# /api/pairs
# ═══════════════════════════════════════════════════════════════════════════════════════


def _synthetic_values(days=56, seed=11):
    """Two autocorrelated daily series where b follows a by one day, plus a short third series."""
    rng = random.Random(seed)
    start = _dt.date.fromisoformat(GENESIS)
    a_vals, b_vals = {}, {}
    level = 50.0
    prev = {}
    for i in range(days):
        day = (start + _dt.timedelta(days=i)).isoformat()
        level = 0.7 * level + 0.3 * 50.0 + rng.gauss(0, 4)
        a_vals[day] = round(level, 2)
        prev[day] = level
        yesterday = (start + _dt.timedelta(days=i - 1)).isoformat()
        if yesterday in prev:
            b_vals[day] = round(0.9 * prev[yesterday] + rng.gauss(0, 2), 2)
    short = {d: a_vals[d] for d in sorted(a_vals)[:5]}
    return a_vals, b_vals, short


def test_pairs_are_stats_core_numbers_with_fdr_across_the_whole_tested_family_and_no_verdict_word():
    a_vals, b_vals, short = _synthetic_values()
    values = {"weight_lbs": a_vals, "hrv": b_vals, "resting_hr": short}
    doc = pairs.compose(values, GENESIS, TODAY, TODAY)
    assert "significant" not in json.dumps(doc).lower()
    assert doc["family"]["offered"] == len(pairs.OFFERED_PAIRS) * len(pairs.LAGS) == len(doc["pairs"])
    cells = {(c["a"], c["b"], c["lag"]): c for c in doc["pairs"]}
    # a cell is recomputed here from the same module and the same pairing
    xs, ys = pairs.paired(a_vals, b_vals, 1)
    cell = cells[("weight_lbs", "hrv", 1)]
    r = stats_core.pearson_r(xs, ys, min_n=pairs.MIN_N)
    n_eff = stats_core.effective_sample_size(xs, ys)
    assert cell["n"] == len(xs) == 55 and cell["r"] == round(r, 3) and cell["rho"] == round(stats_core.spearman_rho(xs, ys), 3)
    assert cell["n_eff"] == round(n_eff, 1) and cell["n_eff"] <= cell["n"]
    assert cell["ci95"] == [round(v, 3) for v in stats_core.fisher_ci(r, n_eff)] and cell["ci95"][0] <= cell["r"] <= cell["ci95"][1]
    assert cell["p_eff"] == round(stats_core.pearson_p_value(r, n_eff), 6)
    assert cell["method_ids"] == list(pairs.METHOD_IDS) and cell["window"] == {"from": GENESIS, "to": TODAY} and cell["tested"] is True
    # b follows a by a day: the +1 lag reads tighter than the −2 lag on this construction
    assert cells[("weight_lbs", "hrv", 1)]["r"] > cells[("weight_lbs", "hrv", -2)]["r"]
    # FDR: the q's are bh_fdr over the tested cells' p's, in cell order, and every tested cell names the family size
    tested = [c for c in doc["pairs"] if c["tested"]]
    assert len(tested) == doc["family"]["tested"] == 5  # weight×hrv at five lags: the only pair with two long series
    assert all(c["family_size"] == 5 for c in tested)
    raw_p = [stats_core.pearson_p_value(*_r_and_neff(values, c)) if c["tested"] else None for c in doc["pairs"]]
    expected_q = stats_core.bh_fdr(raw_p)
    assert [c["fdr_q"] for c in doc["pairs"]] == [None if q is None else round(q, 6) for q in expected_q]
    # an under-n cell is listed with its n and nothing else, and does not join the family
    under = cells[("weight_lbs", "resting_hr", 0)]
    assert under["n"] == 5 and under["tested"] is False and under["method_ids"] == []
    assert all(under[k] is None for k in ("n_eff", "r", "rho", "ci95", "p_eff", "fdr_q"))
    absent = cells[("deep_pct", "total_protein_g", 0)]
    assert absent["n"] == 0 and absent["tested"] is False


def _r_and_neff(values, c):
    xs, ys = pairs.paired(values.get(c["a"], {}), values.get(c["b"], {}), c["lag"])
    return stats_core.pearson_r(xs, ys, min_n=pairs.MIN_N), stats_core.effective_sample_size(xs, ys)


def test_lag_pairs_a_on_day_d_with_b_on_day_d_plus_lag():
    a = {"2026-10-01": 1.0, "2026-10-02": 2.0, "2026-10-03": 3.0}
    b = {"2026-10-02": 10.0, "2026-10-03": 20.0, "2026-10-04": 30.0}
    assert pairs.paired(a, b, 0) == ([2.0, 3.0], [10.0, 20.0])
    assert pairs.paired(a, b, 1) == ([1.0, 2.0, 3.0], [10.0, 20.0, 30.0])
    assert pairs.paired(a, b, -1) == ([3.0], [10.0])


def test_every_pairs_method_id_is_in_the_registry_and_every_offered_key_is_a_served_series():
    for mid in pairs.METHOD_IDS:
        entry = mr.get_stat(mid)
        assert entry is not None and entry["module"] == "stats_core", mid
    assert "spearman_rho" in pairs.METHOD_IDS and "bh_fdr" in pairs.METHOD_IDS and "effective_sample_size" in pairs.METHOD_IDS
    for a, b in pairs.OFFERED_PAIRS:
        assert a in series.SERIES and b in series.SERIES


def test_handle_pairs_reads_each_metric_once_through_the_series_reader_and_a_failed_read_is_503():
    a_vals, b_vals, _ = _synthetic_values()
    reads = []

    def query(source, start, end, **_kw):
        reads.append(source)
        if source == "withings":
            return [{"sk": f"DATE#{d}", "date": d, "weight_lbs": v} for d, v in a_vals.items()]
        if source == "whoop":
            return [{"sk": f"DATE#{d}", "date": d, "hrv": v, "sleep_duration_hours": 7.0} for d, v in b_vals.items()]
        return []

    resp = pairs.handle_pairs(_event(), query=query, today=TODAY)
    assert resp["statusCode"] == 200 and "max-age=3600" in resp["headers"]["Cache-Control"]
    body = _body(resp)
    assert body["as_of"] == TODAY and body["window"] == {"from": GENESIS, "to": TODAY} and body["min_n"] == pairs.MIN_N
    assert "significant" not in resp["body"].lower()
    got = next(c for c in body["pairs"] if (c["a"], c["b"], c["lag"]) == ("weight_lbs", "hrv", 1))
    assert (
        got["tested"]
        and got["n"] == 55
        and got["r"] == pairs.compose({"weight_lbs": a_vals, "hrv": b_vals}, GENESIS, TODAY, TODAY)["pairs"][3]["r"]
    )
    assert reads.count("withings") == 1 and reads.count("whoop") >= 1

    def boom(*_a, **_k):
        raise RuntimeError("dynamo down")

    assert pairs.handle_pairs(_event(), query=boom, today=TODAY)["statusCode"] == 503


# ═══════════════════════════════════════════════════════════════════════════════════════
# stats_core.spearman_rho + its registry entry
# ═══════════════════════════════════════════════════════════════════════════════════════


def test_spearman_rho_is_pearson_over_mid_ranks_with_ties_averaged():
    assert stats_core.average_ranks([10, 20, 20, 30]) == [1.0, 2.5, 2.5, 4.0]
    assert stats_core.average_ranks([3, 1, 2]) == [3.0, 1.0, 2.0]
    assert stats_core.spearman_rho([1, 2, 3, 4, 5], [1, 4, 9, 16, 25]) == 1.0  # monotone, not linear
    assert stats_core.spearman_rho([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == -1.0
    assert stats_core.spearman_rho([1, 1, 1, 1], [1, 2, 3, 4]) is None  # one side all tied: no variance
    assert stats_core.spearman_rho([1, 2], [1, 2]) is None and stats_core.spearman_rho([1, 2, None, 4], [1, 2, 3, None], min_n=2) == 1.0
    xs, ys = [1, 2, 3, 4, 5, 6], [2, 1, 4, 3, 6, 5]
    assert math.isclose(stats_core.spearman_rho(xs, ys), 1 - 6 * 6 / (6 * 35))  # the textbook 1 − 6Σd²/(n(n²−1)) with no ties
    # one outlying day moves rho by one rank, where r moves by its distance
    base_x, base_y = list(range(1, 13)), [v + 0.1 for v in range(1, 13)]
    far_y = base_y[:-1] + [500.0]
    assert stats_core.spearman_rho(base_x, far_y) == stats_core.spearman_rho(base_x, base_y) == 1.0
    assert stats_core.pearson_r(base_x, far_y) < stats_core.pearson_r(base_x, base_y)


def test_spearman_rho_is_registered_with_a_live_fingerprint():
    entry = mr.get_stat("spearman_rho")
    assert entry is not None and entry["function"] == "spearman_rho" and entry["module"] == "stats_core" and entry["min_n"] == 3
    assert entry["fingerprint"] == entry["recorded_fingerprint"] == mr._fingerprint(stats_core.spearman_rho)
    assert "/api/pairs" in entry["used_by"] and entry["category"] == "Correlation"
    assert "spearman_rho" not in mr.verify_fingerprints()


# ── #5532 follow-up (2026-11-01): the journal-silence guard and the page count ───────────────────────────
def _journaling_row(coach="mind", n=1):
    """A real-shaped row whose claim AND stored id carry the journal-silence pattern (#5131)."""
    return {
        "pk": f"COACH#{coach}_coach",
        "sk": f"PREDICTION#pred_2026100{n}_if_journaling_silence_persists_through_p",
        "prediction_id": f"pred_2026100{n}_if_journaling_silence_persists_through_p",
        "coach_id": f"{coach}_coach",
        "claim_natural": "If journaling silence persists through protein recovery, the barrier is not metabolic.",
        "created_date": f"2026-10-0{n}",
        "status": "observation",
        "confidence": 0.5,
        "evaluation": {"type": "observation", "metric": None},
        "phase": "experiment",
        "subdomain": "mind",
    }


def test_a_row_the_journal_silence_guard_would_drop_is_counted_as_withheld_not_as_a_missing_seat():
    """Before the fix a 100-row page came back with 97 and `total` named rows no page could reach
    (live, 2026-11-01: 12 of 468). The handler now scrubs BEFORE paging — the same rule the wire applies —
    so every page is whole and the withheld count is named."""
    rows = _rows()
    base_counted = ledger.export_items(rows, genesis="2026-09-06", dark=[])
    _, base_withheld = ledger.servable(base_counted)  # the captured partition already carries two such rows
    rows_with = {k: list(v) for k, v in rows.items()}
    rows_with.setdefault("mind", []).extend([_journaling_row("mind", 1), _journaling_row("mind", 2)])
    counted = ledger.export_items(rows_with, genesis="2026-09-06", dark=[])
    served, withheld = ledger.servable(counted)
    assert withheld == base_withheld + 2 and len(served) == len(counted) - withheld
    assert all("journaling_silence" not in (i["prediction_id"] or "") for i in served)
    resp = ledger.handle_ledger_export(_event(page="1", size="5"), fetch=lambda: (rows_with, [], []), today="2026-11-01")
    body = _body(resp)
    assert resp["statusCode"] == 200
    assert len(body["items"]) == 5, "a page is whole"
    assert body["total"] == len(served) and body["record_total"] == len(counted) and body["withheld"] == {"journal_silence": withheld}
    assert body["pages"] == math.ceil(len(served) / 5)
    # the wire guard then finds nothing left to withhold — the two scrubs agree
    guarded = journal_silence.guard_api_response(resp)
    assert guarded is resp or guarded["headers"].get(journal_silence.WITHHELD_HEADER) is None
    # every page concatenated is exactly the served set, once each
    seen = []
    for pg in range(1, body["pages"] + 1):
        seen += [
            i["item_id"]
            for i in _body(
                ledger.handle_ledger_export(_event(page=str(pg), size="5"), fetch=lambda: (rows_with, [], []), today="2026-11-01")
            )["items"]
        ]
    assert len(seen) == len(set(seen)) == body["total"]


def test_a_clean_ledger_withholds_nothing_and_total_equals_record_total():
    rows = {k: [r for r in v if not journal_silence.mentions_journal_silence(json.dumps(r, default=str))] for k, v in _rows().items()}
    resp = ledger.handle_ledger_export(_event(page="1", size="100"), fetch=lambda: (rows, [], []), today="2026-11-01")
    body = _body(resp)
    assert body["withheld"] == {"journal_silence": 0} and body["total"] == body["record_total"]
