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
import threading
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

# #3849: this file used to assert WALL CLOCK — `elapsed < 0.7s for 9 queries`. That is a
# proxy for concurrency, and after #3797 made the pre-merge suite parallel
# (`-n auto --dist loadfile`) the proxy started measuring the runner instead of the code.
# It failed a PR whose whole diff was `deploy/lib/canary_gate_retry.py`; reproduced under
# deliberate CPU load it failed at **2.73s**, which is WORSE than the sequential path the
# budget exists to exclude (~1.35s) — the tell that the pool was being starved, not that
# the fetch had lost its concurrency. The hazard arrived underneath a test that did not
# change, exactly like #3832.
#
# The property is "the N partition reads are IN FLIGHT AT THE SAME TIME", and that is
# directly observable. `_ConcurrencyProbe` counts queries concurrently open and records
# the peak. There is no budget anywhere: a sequential walk can only ever reach peak 1,
# however fast the machine, and a concurrent dispatch reaches at least 2 however slow it
# is — the threads are all submitted before the first sleep returns.
#
# The sleep that remains is not an assertion. It holds each query open long enough for
# overlap to be *observable*; shortening or lengthening it cannot change a verdict.
QUERY_DELAY = 0.05


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
        "pre_registered_at": "2026-07-18T22:00:00+00:00",  # #3480
    }


def _slow_hook(table, **kw):
    time.sleep(QUERY_DELAY)
    return {"Items": [_full_pred()]} if "sleep" in str(kw.get("ExpressionAttributeValues", "")) + _pk_of(kw) else {"Items": []}


class _ConcurrencyProbe:
    """Counts partition queries open AT THE SAME INSTANT. No clock is asserted (#3849).

    `peak` is the most queries ever simultaneously in flight. It is a structural
    property of the dispatch, not of the machine:

      * a SEQUENTIAL walk can only ever reach `peak == 1` — the next query is not issued
        until the previous returns, on any hardware at any speed;
      * a CONCURRENT dispatch submits every job before the first returns, so `peak >= 2`
        even on a runner so starved that the wall clock looks sequential.

    That asymmetry is what the old wall-clock budget did not have: 0.7s was ~4.7x the
    ideal concurrent time but only ~0.5x the sequential time, so it had plenty of
    headroom against the property and almost none against a busy machine.
    """

    def __init__(self, delay=QUERY_DELAY):
        self._lock = threading.Lock()
        self._delay = delay
        self.in_flight = 0
        self.peak = 0
        self.calls = 0

    def hook(self, table, **kw):
        with self._lock:
            self.calls += 1
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
        try:
            time.sleep(self._delay)
            return _slow_hook(table, **kw)
        finally:
            with self._lock:
                self.in_flight -= 1


def _pk_of(kw):
    cond = kw["KeyConditionExpression"]
    return cond._values[0]._values[1]


class TestConcurrentPartitionFetch:
    """The red-pre-#1527 guard: the partition reads OVERLAP, not "they finished fast".

    #3849 converted both assertions from a wall-clock budget to an in-flight count. See
    the note above `QUERY_DELAY` for the measurement that forced it.
    """

    def test_calibration_fetches_partitions_concurrently(self, monkeypatch):
        probe = _ConcurrencyProbe()
        monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=probe.hook))
        body = _body(api.handle_calibration({}))
        assert probe.calls >= 8, f"the fan-out shrank — only {probe.calls} partition queries were issued"
        assert probe.peak > 1, (
            f"calibration fetch is SEQUENTIAL: {probe.calls} queries issued and never more than "
            f"{probe.peak} in flight at once (#1527 regressed; this verdict does not depend on the clock)"
        )
        assert len(body["coaches"]) == 8  # all coaches still scored

    def test_predictions_fetches_partitions_concurrently(self, monkeypatch):
        probe = _ConcurrencyProbe()
        monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=probe.hook))
        body = _body(api.handle_predictions({}))
        assert probe.calls >= 8, f"the fan-out shrank — only {probe.calls} partition queries were issued"
        assert probe.peak > 1, (
            f"predictions fetch is SEQUENTIAL: {probe.calls} queries issued and never more than "
            f"{probe.peak} in flight at once (#1527 regressed; this verdict does not depend on the clock)"
        )
        assert len(body["by_coach"]) == 8

    def test_MUST_FAIL_a_sequential_walk_is_still_caught(self, monkeypatch):
        """The control #3849's acceptance names: with the concurrent dispatch reverted to
        a sequential walk, the probe must still red. This is what makes the conversion a
        fix rather than a relaxation — the old budget caught this too, and so must the
        new assertion, on a machine of any speed."""

        def _sequential_fetch(jobs, *, failures=None):
            return {key: fn() for key, fn in (jobs or {}).items()}

        probe = _ConcurrencyProbe()
        # The handler resolves `_parallel_fetch` out of `site_api_coach.globals()` (it is
        # `_g["_parallel_fetch"]`, not a module-local of the ledger), so THIS is the name
        # the revert has to replace. Patching the ledger's copy leaves the real dispatch
        # running and the control passes over its own mutation — which is what the first
        # draft of this test did, and it reported peak 8.
        monkeypatch.setattr(api, "_parallel_fetch", _sequential_fetch)
        monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=probe.hook))
        _body(api.handle_predictions({}))
        assert probe.calls >= 8, "the control did not exercise the fan-out at all"
        assert probe.peak == 1, (
            f"a deliberately SEQUENTIAL walk reported peak {probe.peak} — the probe is not measuring "
            "dispatch, and the two assertions above would pass over a #1527 regression"
        )

    def test_coach_filter_still_single_fetch(self, monkeypatch):
        """One coach, one QUERY — still true after #3553.

        That issue first added the seven COMMITMENT# partitions to this same concurrent
        round, which doubled the fan-out to 16 queries against a 9-worker pool and made
        THIS file's sibling assertion fail at 0.76s against the 0.70s budget. The fix was
        not a bigger budget: the follow-through tally is now a daily rollup the grader
        writes and this handler reads with one GetItem, so the Query count is unchanged."""
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
            # #3046: a decided call has no due date to promise; gradeable says it
            # had a deterministic grading path (non-qualitative eval spec).
            "due_date": None,
            "gradeable": True,
            "metric": "sleep_duration_hours",
            "eval_type": "threshold",
            "outcome_notes": "cleared Wednesday",
            "subdomain": "recovery",
            # #3480: the freeze instant rides the projection too — dropped from
            # _PREDICTION_PROJECTION_FIELDS it would silently serve None for every row.
            "pre_registered_at": "2026-07-18T22:00:00+00:00",
            # #3520: the walk includes RETIRED seats (their career records are real and
            # keep their real byline), and the scorecard used to render them beside the
            # live cast with nothing to say so. The flag is registry-derived.
            "retired": False,
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
    def test_query_partition_routes_through_patched_fake(self, monkeypatch):
        fake = FakeDdbTable(query_hook=lambda table, **kw: {"Items": []})
        monkeypatch.setattr(api, "table", fake)
        api._query_partition("COACH#sleep_coach", "PREDICTION#")
        assert len(fake.query_calls) == 1  # the fake took the call — no real client involved
