"""#4643 — Hevy ingestion: an auth breaker, a truncated walk that reads as a FAILED run,
and a quarantine for an event that fails on every run.

Three gaps from the 2026-10-04 data-source sweep, each a failure that would go unseen:

  1. A revoked API key failed every hourly run three times (two async retries) into the
     dead-letter queue, while the registry claimed hevy `oauth: True` "routes through
     auth_breaker" — it never did, so the IngestAuthHealthy stream (read by the
     dimensionless `ingest-auth-unhealthy-24h`; there is no per-source hevy auth alarm)
     never carried a hevy point, and `ingest-consecutive-failures-hevy` was the only page.
  2. A truncated walk (backlog > MAX_PAGES_PER_RUN) froze `since` correctly but recorded
     `succeeded=True`, so a permanent truncation loop was a healthy-looking source.
  3. One permanently failing event froze `since` forever (re-proved below: the pre-fix
     loop blocks on every run, no matter how many).

No AWS: the module's `_table` is a FakeTable, the breaker's CloudWatch emit is captured.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))

HEVY_PK = "USER#matthew#SOURCE#hevy"
Q_PK = "USER#system"  # the quarantine lives beside the cursor, never in the workout partition
Q_SK = "INGESTION_QUARANTINE#hevy#WORKOUT#"
SINCE = "2026-07-01T00:00:00Z"


def _match(cond, item) -> bool:
    exp = cond.get_expression()
    op = exp["operator"]
    vals = exp["values"]
    if op == "AND":
        return _match(vals[0], item) and _match(vals[1], item)
    attr, val = vals[0], vals[1]
    if op == "=":
        return item.get(attr.name) == val
    if op == "begins_with":
        return str(item.get(attr.name, "")).startswith(val)
    if op == ">=":
        return str(item.get(attr.name, "")) >= val
    if op == "BETWEEN":
        return vals[1] <= str(item.get(attr.name, "")) <= vals[2]
    raise NotImplementedError(op)


class FakeTable:
    def __init__(self):
        self.items: dict[tuple, dict] = {}
        self.deletes: list[str] = []
        self.query_raises = False

    def put_item(self, Item):
        self.items[(Item["pk"], Item["sk"])] = dict(Item)
        return {}

    def get_item(self, Key):
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(it)} if it else {}

    def delete_item(self, Key):
        self.deletes.append(Key["sk"])
        self.items.pop((Key["pk"], Key["sk"]), None)
        return {}

    def query(self, KeyConditionExpression=None, ProjectionExpression=None, ExpressionAttributeNames=None, **kw):
        if self.query_raises:
            raise RuntimeError("ddb down")
        hits = [dict(it) for _, it in sorted(self.items.items()) if _match(KeyConditionExpression, it)]
        if ProjectionExpression:  # DynamoDB semantics: a row with none of the attributes comes back as {}
            names = ExpressionAttributeNames or {}
            fields = [names.get(f.strip(), f.strip()) for f in ProjectionExpression.split(",")]
            hits = [{f: it[f] for f in fields if f in it} for it in hits]
        return {"Items": hits}


@pytest.fixture
def hevy(monkeypatch):
    import hevy_backfill_lambda as mod
    from common import auth_breaker

    tbl = FakeTable()
    state = {"since": [], "health": [], "auth_metric": [], "fetches": 0}

    monkeypatch.setattr(mod, "_table", tbl)
    monkeypatch.setattr(mod, "_HAS_AUTH_BREAKER", True)
    monkeypatch.setattr(mod, "_INGEST_HEALTH_AVAILABLE", True)
    monkeypatch.setattr(mod, "record_ingest_health", lambda table, src, log, **kw: state["health"].append(kw), raising=False)
    monkeypatch.setattr(auth_breaker, "_emit_auth_health", lambda healthy, src, log: state["auth_metric"].append((src, healthy)))
    monkeypatch.setattr(mod, "load_since", lambda: SINCE)
    monkeypatch.setattr(mod, "save_since", lambda ts: state["since"].append(ts))
    monkeypatch.setattr(mod, "archive_raw", lambda wid, raw: None)
    monkeypatch.setattr(mod, "write_normalized", lambda rec: None)
    monkeypatch.setattr(mod, "_derive_training_notes", lambda rec: None)
    monkeypatch.setattr(mod, "_attach_adherence", lambda rec, raw: None)
    monkeypatch.setattr(mod.cardio_hr_store, "attach", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_rejoin_cardio_hr", lambda: {})
    monkeypatch.setattr(mod, "resolve_tombstones", lambda: {"markers_seen": 0, "resolved": 0, "records_removed": 0, "failures": 0})
    return mod, tbl, state


def _feed(state, events, page_count=1):
    def fetch(since, page=1, page_size=10):
        state["fetches"] += 1
        return {"page": page, "page_count": page_count, "events": events(page) if callable(events) else events}

    return fetch


def _updated(wid):
    return {"type": "updated", "workout": {"id": wid, "start_time": "2026-07-02T16:00:00Z", "exercises": []}}


# ── 1 · auth breaker ─────────────────────────────────────────────────────────


def test_auth_failure_latches_breaker_and_the_async_retry_short_circuits(hevy, monkeypatch):
    """The DLQ path: invocation 1 gets a 401 and raises (Lambda Errors engage); its async
    retry must then find the latched breaker and return 200 WITHOUT calling Hevy — so the
    event never exhausts its retries into the dead-letter queue."""
    mod, tbl, state = hevy
    from training.hevy_common import HevyAPIError

    def revoked(since, page=1, page_size=10):
        state["fetches"] += 1
        raise HevyAPIError("Hevy GET /v1/workouts/events → HTTP 401: invalid api key", status=401)

    monkeypatch.setattr(mod, "fetch_events_page", revoked)

    with pytest.raises(HevyAPIError):
        mod.lambda_handler({}, None)
    assert (HEVY_PK, "AUTH_FAILURE") in tbl.items, "a 401 must latch the shared auth breaker"
    assert state["health"][-1] == {"attempted": True, "succeeded": False, "error_class": "auth"}
    assert ("hevy", 0) in state["auth_metric"], "IngestAuthHealthy{Source=hevy}=0 must be emitted"

    # The async retry of the same event.
    out = mod.lambda_handler({}, None)
    body = json.loads(out["body"])
    assert out["statusCode"] == 200
    assert body["skipped"] == "auth_failure_circuit_breaker"
    assert state["fetches"] == 1, "the retry must not reach the Hevy API"
    assert state["health"][-1] == {"attempted": True, "succeeded": False, "error_class": "auth"}


def test_403_also_latches(hevy, monkeypatch):
    mod, tbl, state = hevy
    from training.hevy_common import HevyAPIError

    def forbidden(since, page=1, page_size=10):
        raise HevyAPIError("Hevy GET /v1/workouts/events → HTTP 403: pro required", status=403)

    monkeypatch.setattr(mod, "fetch_events_page", forbidden)
    with pytest.raises(HevyAPIError):
        mod.lambda_handler({}, None)
    assert (HEVY_PK, "AUTH_FAILURE") in tbl.items


def test_a_500_whose_message_contains_401_does_not_latch(hevy, monkeypatch):
    """The breaker keys on the HTTP status, never the text: a since= timestamp's
    microseconds can spell 401 on a run that failed for an unrelated reason."""
    mod, tbl, _ = hevy
    from training.hevy_common import HevyAPIError

    def server_error(since, page=1, page_size=10):
        raise HevyAPIError("Hevy GET /v1/workouts/events?since=2026-07-01T00:00:00.401000 → HTTP 500: oops", status=500)

    monkeypatch.setattr(mod, "fetch_events_page", server_error)
    with pytest.raises(HevyAPIError):
        mod.lambda_handler({}, None)
    assert (HEVY_PK, "AUTH_FAILURE") not in tbl.items


def test_an_authenticated_page_clears_the_breaker(hevy, monkeypatch):
    """A quiet hour (empty feed) still proves the key works — it must clear the marker and
    emit IngestAuthHealthy=1, or the per-source alarm never recovers."""
    mod, tbl, state = hevy
    monkeypatch.setattr(mod, "fetch_events_page", _feed(state, []))
    mod.lambda_handler({}, None)
    assert "AUTH_FAILURE" in tbl.deletes
    assert ("hevy", 1) in state["auth_metric"]


def test_hevy_get_carries_the_http_status(monkeypatch):
    """The status the breaker reads is set where the HTTPError is caught."""
    import io
    import urllib.error

    from training import hevy_common as hc

    def raise_401(req, timeout=30):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b"bad key"))

    monkeypatch.setattr(hc, "load_secret", lambda: {"api_key": "k"})
    monkeypatch.setattr(hc, "urlopen_with_retry", raise_401)
    with pytest.raises(hc.HevyAPIError) as ei:
        hc.hevy_get("/v1/workouts/events")
    assert ei.value.status == 401


# ── 2 · truncation is a failed run ───────────────────────────────────────────


def test_truncated_walk_is_recorded_as_a_failed_run(hevy, monkeypatch):
    mod, _, state = hevy
    monkeypatch.setattr(mod, "MAX_PAGES_PER_RUN", 2)
    monkeypatch.setattr(mod, "fetch_events_page", _feed(state, lambda page: [_updated(f"w{page}")], page_count=5))

    body = json.loads(mod.lambda_handler({}, None)["body"])

    assert body["truncated"] is True and body["errors"] == 0
    assert state["since"] == []
    assert state["health"][-1]["succeeded"] is False, "a truncated walk must not read as a healthy run"
    assert state["health"][-1]["error_class"] == "transport"


def test_complete_clean_walk_is_still_a_success(hevy, monkeypatch):
    mod, _, state = hevy
    monkeypatch.setattr(mod, "fetch_events_page", _feed(state, [_updated("w1")]))
    mod.lambda_handler({}, None)
    assert state["health"][-1] == {"attempted": True, "succeeded": True, "error_class": "none"}
    assert len(state["since"]) == 1


# ── 3 · quarantine ───────────────────────────────────────────────────────────


def _poison(monkeypatch, mod, bad="w_bad"):
    def write(rec):
        if rec.get("source_workout_id") == bad or bad in str(rec.get("sk", "")):
            raise ValueError("unparseable set payload")

    monkeypatch.setattr(mod, "write_normalized", write)


def test_a_repeatedly_failing_event_is_quarantined_and_the_cursor_advances(hevy, monkeypatch):
    """Re-proof of the unverified row: before #4643 the bad event blocked `since` on EVERY
    run. Now runs 1..N-1 still hold the cursor (a transient failure must retry), run N
    quarantines the event and the cursor advances past it."""
    mod, tbl, state = hevy
    _poison(monkeypatch, mod)
    monkeypatch.setattr(mod, "fetch_events_page", _feed(state, [_updated("w_good"), _updated("w_bad")]))

    for run in range(1, mod.QUARANTINE_AFTER):
        body = json.loads(mod.lambda_handler({}, None)["body"])
        assert body["blocking_errors"] == 1, f"run {run} must still hold the cursor"
        assert state["since"] == []

    body = json.loads(mod.lambda_handler({}, None)["body"])
    assert body["quarantined"] == ["w_bad"]
    assert body["blocking_errors"] == 0
    assert len(state["since"]) == 1, "the quarantining run must advance the cursor"
    rec = tbl.items[(Q_PK, f"{Q_SK}w_bad")]
    assert rec["quarantined"] is True and rec["fail_count"] == mod.QUARANTINE_AFTER
    # Nothing the quarantine path writes may land in the workout partition, where every
    # reader assumes a row is a workout (routine_title counted such a row as a session).
    assert not [k for k in tbl.items if k[0] == HEVY_PK and k[1] != "AUTH_FAILURE"]
    # The run that quarantined still failed an event — visible to liveness, never silent.
    assert state["health"][-1]["succeeded"] is False


def test_a_clean_retry_clears_the_failure_streak(hevy, monkeypatch):
    """A transient failure followed by a clean run must not accrue toward quarantine."""
    mod, tbl, state = hevy
    _poison(monkeypatch, mod)
    monkeypatch.setattr(mod, "fetch_events_page", _feed(state, [_updated("w_bad")]))
    mod.lambda_handler({}, None)
    assert (Q_PK, f"{Q_SK}w_bad") in tbl.items

    monkeypatch.setattr(mod, "write_normalized", lambda rec: None)
    mod.lambda_handler({}, None)
    assert (Q_PK, f"{Q_SK}w_bad") not in tbl.items
    assert len(state["since"]) == 1


def test_quarantine_fails_closed_when_the_streak_cannot_be_read(hevy, monkeypatch):
    """Quarantine is the one path that lets an event be skipped, so an unreadable streak
    must mean "every failure blocks" — even an event already past the threshold."""
    mod, tbl, state = hevy
    tbl.put_item({"pk": Q_PK, "sk": f"{Q_SK}w_bad", "workout_id": "w_bad", "fail_count": 9, "quarantined": True})
    tbl.query_raises = True
    _poison(monkeypatch, mod)
    monkeypatch.setattr(mod, "fetch_events_page", _feed(state, [_updated("w_bad")]))

    body = json.loads(mod.lambda_handler({}, None)["body"])
    assert body["blocking_errors"] == 1
    assert state["since"] == []
    # An unread streak is not an empty one: it must not be overwritten with a count of 1.
    assert tbl.items[(Q_PK, f"{Q_SK}w_bad")]["fail_count"] == 9


# ── 4 · no phantom session in the routine-title counters ─────────────────────


def test_routine_title_counts_only_workout_rows(monkeypatch):
    """Verifier finding on this PR: a QUARANTINE# row in the hevy partition came back from
    routine_title._query_performed's open `sk >= DATE#` query as an empty projected item,
    and count_distinct_performed counted it (key "None") as one more session. The same
    held for the pre-existing DELETE#WORKOUT# tombstones. Plant every non-workout sk family
    that sorts after DATE# and assert the all-time count is exactly the workouts."""
    from training import routine_title as rt

    tbl = FakeTable()
    for wid, day in (("a", "2026-09-07"), ("b", "2026-09-08")):
        tbl.put_item({"pk": HEVY_PK, "sk": f"DATE#{day}#WORKOUT#{wid}", "date": day, "workout_uid": f"hevy:{wid}"})
    tbl.put_item({"pk": HEVY_PK, "sk": "QUARANTINE#WORKOUT#zz", "workout_id": "zz", "fail_count": 3, "quarantined": True})
    tbl.put_item({"pk": HEVY_PK, "sk": "DELETE#WORKOUT#yy", "tombstone": True})
    tbl.put_item({"pk": HEVY_PK, "sk": "AUTH_FAILURE", "error": "401"})
    monkeypatch.setattr(rt, "_table", lambda: tbl)

    performed = rt._query_performed("2026-09-06")
    assert rt.count_distinct_performed(performed) == 2
    assert all(r.get("date") for r in performed), performed
