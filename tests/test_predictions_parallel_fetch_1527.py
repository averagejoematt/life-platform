"""tests/test_predictions_parallel_fetch_1527.py — #1527 origin latency.

CONFIRMED regression this pins the fix for: after #1376 made /api/predictions
and /api/calibration career-backed, each request walked all 8 coaches' full
PREDICTION# partitions SEQUENTIALLY (plus the hypothesis CALIB# ledger) —
~3.6s at origin, blowing /method/board/'s 2500ms cold-cache LCP budget (the
fleet run 29675370138's visual-QA red).

This guard:
  1. pins that both handlers issue their per-coach partition fetches
     CONCURRENTLY — with a table whose every query takes QUERY_DELAY, a
     sequential walk costs ~N×QUERY_DELAY while the concurrent fetch costs
     ~QUERY_DELAY; the wall-clock assertion sits between the two with wide
     margin (red on the pre-#1527 sequential code, green after);
  2. pins that the ProjectionExpression the partition fetch trims payloads
     with still carries every field either surface emits — a seeded
     full-shape record must round-trip into the /api/predictions item and
     into scored calibration pairs (a field silently dropped from the
     projection would zero real data at the API edge);
  3. pins that a monkeypatched fake table is honored as-is by the
     thread-dispatch path (the test-fake contract every other coach-surface
     test relies on).
"""

import json
import os
import sys
import time

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from fakes import FakeDdbTable  # noqa: E402
from web import site_api_coach as api  # noqa: E402

# Per-query artificial latency. Sequential: 8 coach partitions (+1 ledger on
# /api/calibration) → ≥ 8×DELAY = 1.2s. Concurrent: ~1×DELAY. The 0.7s budget
# sits > 4×DELAY above the concurrent cost and > 5×DELAY below the sequential
# cost, so scheduler jitter can't flip it either way.
QUERY_DELAY = 0.15
WALL_CLOCK_BUDGET = 0.7


def _body(resp):
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def _full_pred(coach="sleep_coach"):
    """A PREDICTION# record carrying every field /api/predictions emits."""
    return {
        "pk": f"COACH#{coach}",
        "sk": "PREDICTION#2026-07-19-p1",
        "status": "confirmed",
        "confidence": 0.8,
        "phase": "experiment",
        "claim_natural": "Sleep debt clears by Thursday",
        "created_date": "2026-07-19",
        "evaluation": {"metric": "sleep_duration_hours", "type": "threshold"},
        "outcome_notes": "cleared Wednesday",
        "subdomain": "recovery",
    }


def _slow_hook(table, **kw):
    time.sleep(QUERY_DELAY)
    return {"Items": [_full_pred()]} if "sleep" in str(kw.get("ExpressionAttributeValues", "")) + _pk_of(kw) else {"Items": []}


def _pk_of(kw):
    cond = kw["KeyConditionExpression"]
    return cond._values[0]._values[1]


class TestConcurrentPartitionFetch:
    """The red-pre-#1527 guard: wall-clock ≈ one query, not the sum of nine."""

    def test_calibration_fetches_partitions_concurrently(self, monkeypatch):
        monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=_slow_hook))
        t0 = time.monotonic()
        body = _body(api.handle_calibration({}))
        elapsed = time.monotonic() - t0
        assert elapsed < WALL_CLOCK_BUDGET, f"calibration fetch not concurrent: {elapsed:.2f}s for 9 queries"
        assert len(body["coaches"]) == 8  # all coaches still scored

    def test_predictions_fetches_partitions_concurrently(self, monkeypatch):
        monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=_slow_hook))
        t0 = time.monotonic()
        body = _body(api.handle_predictions({}))
        elapsed = time.monotonic() - t0
        assert elapsed < WALL_CLOCK_BUDGET, f"predictions fetch not concurrent: {elapsed:.2f}s for 8 queries"
        assert len(body["by_coach"]) == 8

    def test_coach_filter_still_single_fetch(self, monkeypatch):
        fake = FakeDdbTable(query_hook=lambda table, **kw: {"Items": [_full_pred()]})
        monkeypatch.setattr(api, "table", fake)
        body = _body(api.handle_predictions({"queryStringParameters": {"coach_id": "sleep"}}))
        assert list(body["by_coach"].keys()) == ["sleep"]
        assert len(fake.query_calls) == 1


class TestProjectionCarriesEveryEmittedField:
    """A field dropped from _PREDICTION_PROJECTION_FIELDS must fail loudly here,
    not silently zero real data at the API edge."""

    def test_full_record_round_trips_through_predictions(self, monkeypatch):
        monkeypatch.setattr(
            api, "table", FakeDdbTable(query_hook=lambda table, **kw: {"Items": [_full_pred()] if "sleep" in _pk_of(kw) else []})
        )
        body = _body(api.handle_predictions({}))
        (item,) = body["predictions"]
        assert item == {
            "coach_id": "sleep",
            "coach_name": "Dr. Lisa Park",
            "text": "Sleep debt clears by Thursday",
            "confidence": 0.8,
            "status": "confirmed",
            "date": "2026-07-19",
            "metric": "sleep_duration_hours",
            "eval_type": "threshold",
            "outcome_notes": "cleared Wednesday",
            "subdomain": "recovery",
        }
        assert body["by_coach"]["sleep"]["lifetime"]["confirmed"] == 1

    def test_every_consumed_field_is_projected(self):
        # The record fields the handlers read, by hand-audit of
        # handle_predictions/_score_coach_calibration/singleton_visible +
        # calibration_core.pairs_from_prediction_records.
        consumed = {
            "status",
            "outcome",
            "confidence",
            "tombstone",
            "phase",
            "claim_natural",
            "created_date",
            "evaluation",
            "outcome_notes",
            "subdomain",
        }
        assert consumed <= set(api._PREDICTION_PROJECTION_FIELDS)

    def test_projection_expression_sent_to_ddb(self, monkeypatch):
        fake = FakeDdbTable(query_hook=lambda table, **kw: {"Items": []})
        monkeypatch.setattr(api, "table", fake)
        api._fetch_prediction_partition("COACH#sleep_coach")
        (call,) = fake.query_calls
        names = call["ExpressionAttributeNames"]
        assert call["ProjectionExpression"] == ", ".join(names)
        assert set(names.values()) == set(api._PREDICTION_PROJECTION_FIELDS)

    def test_scored_pairs_survive_projection(self, monkeypatch):
        monkeypatch.setattr(
            api, "table", FakeDdbTable(query_hook=lambda table, **kw: {"Items": [_full_pred()] if "sleep" in _pk_of(kw) else []})
        )
        body = _body(api.handle_calibration({}))
        sleep = next(c for c in body["coaches"] if c["coach_id"] == "sleep")
        assert sleep["n"] == 1  # the confirmed record scored — status+confidence projected
        assert sleep["lifetime"]["n"] == 1


class TestFakeTableHonored:
    def test_partition_table_returns_patched_fake(self, monkeypatch):
        fake = FakeDdbTable()
        monkeypatch.setattr(api, "table", fake)
        assert api._partition_table() is fake
