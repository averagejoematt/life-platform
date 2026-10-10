"""#4643 box 2 — a daily Hevy reconcile: the vendor's workout count against the stored,
non-tombstoned rows, emitted as MissingActivityCount{Source=hevy}.

Every other Hevy check reads only the store, so a workout the events cursor walked past
(a quarantined event, a feed that skipped one) was invisible to all of them. The vendor
publishes a one-call all-time count; this pins the comparison, the read-only contract
(no row, cursor, health record or breaker marker written), the in-flight discount, and
the wiring — the registry facet, the EventBridge rule and the alarm pair — as a SET over
every `provider_reconcile` source, so the next opted-in source cannot ship unalarmed.

The vendor wire is the live response captured 2026-10-10 (`{"workout_count":513}`,
GET /v1/workouts/count); the stored rows use the live sk shapes of the hevy partition
(513 `DATE#<day>#WORKOUT#<uuid>` rows beside 421 legacy bare `DATE#<day>` rows).

No AWS: `_table` is a FakeTable, `hevy_get` and boto3's CloudWatch client are stubbed.
"""

from __future__ import annotations

import ast
import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))

from test_hevy_breaker_quarantine_4643 import FakeTable  # noqa: E402

HEVY_PK = "USER#matthew#SOURCE#hevy"
SINCE = "2026-10-10T08:00:05.313755+00:00"
IDS = ["b12e3088-d3ae-4953-9aaf-322dd2779079", "a49f3ca8-306c-4094-8170-1017755b6fd4", "ad48dd7a-d9f1-44f2-a9aa-6b4623bc12c4"]
DAYS = ["2026-10-01", "2026-10-02", "2026-10-04"]
NEW_ID = "966150d1-7307-4229-b377-109cf7938d42"


class RecordingTable(FakeTable):
    """FakeTable that also records every write path, so 'read-only' is asserted, not assumed."""

    def __init__(self):
        super().__init__()
        self.writes: list[str] = []

    def put_item(self, Item):
        self.writes.append(f"put {Item.get('sk')}")
        return super().put_item(Item)

    def delete_item(self, Key):
        self.writes.append(f"delete {Key.get('sk')}")
        return super().delete_item(Key)

    def update_item(self, **kw):
        self.writes.append(f"update {kw.get('Key')}")
        return {}

    def seed(self, sk, **attrs):
        super().put_item({"pk": HEVY_PK, "sk": sk, **attrs})


@pytest.fixture
def rec(monkeypatch):
    import boto3
    import hevy_backfill_lambda as mod
    from common import auth_breaker
    from training import hevy_common

    tbl = RecordingTable()
    for wid, day in zip(IDS, DAYS):
        tbl.seed(f"DATE#{day}#WORKOUT#{wid}", source_workout_id=wid, phase="experiment")
    tbl.seed("DATE#2021-04-12", total_volume_kg=1)  # legacy bare daily row — never a workout
    state = {"vendor": {"workout_count": 3}, "feed": [], "metrics": [], "calls": [], "side": []}

    def hevy_get(path, timeout=30):
        state["calls"].append(path)
        if isinstance(state["vendor"], Exception):
            raise state["vendor"]
        return state["vendor"]

    def fetch_events_page(since, page=1, page_size=10):
        state["calls"].append(f"events?since={since}&page={page}")
        return {"page": page, "page_count": 1, "events": state["feed"]}

    class CW:
        def put_metric_data(self, **kw):
            state["metrics"].append(kw)

    monkeypatch.setattr(mod, "_table", tbl)
    monkeypatch.setattr(mod, "_HAS_AUTH_BREAKER", True)
    monkeypatch.setattr(hevy_common, "hevy_get", hevy_get)
    monkeypatch.setattr(mod, "fetch_events_page", fetch_events_page)
    monkeypatch.setattr(mod, "load_since", lambda: SINCE)
    monkeypatch.setattr(boto3, "client", lambda *a, **k: CW())
    monkeypatch.setattr(auth_breaker, "_emit_auth_health", lambda healthy, src, log: None)
    # Every write-shaped side effect the poll path has: none may fire in reconcile mode.
    monkeypatch.setattr(mod, "save_since", lambda ts: state["side"].append(("save_since", ts)))
    monkeypatch.setattr(mod, "_record_health", lambda **kw: state["side"].append(("health", kw)))
    monkeypatch.setattr(mod, "mark_failure", lambda *a, **k: state["side"].append(("mark_failure",)), raising=False)
    monkeypatch.setattr(mod, "clear_failure", lambda *a, **k: state["side"].append(("clear_failure",)), raising=False)
    monkeypatch.setattr(mod, "write_normalized", lambda r: state["side"].append(("write", r)))
    monkeypatch.setattr(mod, "resolve_tombstones", lambda: state["side"].append(("tombstones",)))
    return mod, tbl, state


def _run(mod):
    out = mod.lambda_handler({"reconcile": True}, None)
    assert out["statusCode"] == 200
    return json.loads(out["body"])


def _missing_points(state):
    pts = []
    for call in state["metrics"]:
        assert call["Namespace"] == "LifePlatform/IngestReconciliation"
        for d in call["MetricData"]:
            assert d["MetricName"] == "MissingActivityCount"
            assert d["Dimensions"] == [{"Name": "Source", "Value": "hevy"}]
            pts.append(d["Value"])
    return pts


def _assert_read_only(tbl, state):
    assert tbl.writes == [], f"reconcile wrote to the store: {tbl.writes}"
    assert state["side"] == [], f"reconcile triggered a write-shaped side effect: {state['side']}"


# ── the comparison ────────────────────────────────────────────────────────────────


def test_a_clean_store_emits_zero(rec):
    mod, tbl, state = rec
    body = _run(mod)
    assert body["vendor_count"] == 3 and body["stored_count"] == 3
    assert body["missing_count"] == 0 and body["store_only_count"] == 0
    assert _missing_points(state) == [0.0]
    assert "/v1/workouts/count" in state["calls"]
    _assert_read_only(tbl, state)


def test_a_workout_the_vendor_has_and_the_store_lacks_is_counted_missing(rec):
    """The drop this exists for: one more workout at Hevy than live rows here."""
    mod, tbl, state = rec
    state["vendor"] = {"workout_count": 5}
    body = _run(mod)
    assert body["missing_count"] == 2
    assert _missing_points(state) == [2.0]
    _assert_read_only(tbl, state)


def test_tombstoned_rows_and_pending_deletes_are_not_stored_workouts(rec):
    """A `tombstone=true` row and a row whose id has an UNRESOLVED delete marker are both
    already gone from the vendor's count; counting them would hide a real drop."""
    mod, tbl, state = rec
    tbl.seed("DATE#2026-10-05#WORKOUT#t0mb", tombstone=True)
    tbl.seed("DATE#2026-10-06#WORKOUT#pend", phase="experiment")
    tbl.seed("DELETE#WORKOUT#pend", tombstone=True, tombstoned_at="2026-10-10T07:00:00Z")
    tbl.seed("DELETE#WORKOUT#" + IDS[0], tombstone=True, resolved_at="2026-10-09T00:00:00Z")  # resolved: row stays counted
    state["vendor"] = {"workout_count": 4}
    body = _run(mod)
    assert body["stored_count"] == 3
    assert body["missing_count"] == 1
    assert _missing_points(state) == [1.0]
    _assert_read_only(tbl, state)


def test_feed_events_the_hourly_poll_has_not_applied_are_not_a_drop(rec):
    """The reconcile runs between polls: a workout saved since the cursor is in the count
    and not yet stored, a delete since the cursor is the reverse. Neither is a drop."""
    mod, tbl, state = rec
    state["vendor"] = {"workout_count": 4}  # one saved since the cursor
    state["feed"] = [
        {"type": "updated", "workout": {"id": NEW_ID}},
        {"type": "updated", "workout": {"id": IDS[1]}},  # an edit of a stored workout: no count change
    ]
    body = _run(mod)
    assert body["pending_new"] == [NEW_ID] and body["pending_deleted"] == []
    assert body["missing_count"] == 0 and body["store_only_count"] == 0
    assert _missing_points(state) == [0.0]
    assert f"events?since={SINCE}&page=1" in state["calls"]
    _assert_read_only(tbl, state)

    state["metrics"].clear()
    state["vendor"] = {"workout_count": 2}  # one deleted since the cursor, row not yet removed
    state["feed"] = [{"type": "deleted", "id": IDS[2], "deleted_at": "2026-10-10T08:10:00Z"}]
    body = _run(mod)
    assert body["pending_new"] == [] and body["pending_deleted"] == [IDS[2]]
    assert body["missing_count"] == 0 and body["store_only_count"] == 0
    _assert_read_only(tbl, state)

    # ...and the pending delete must not mask a real drop: one more at the vendor than live rows.
    state["metrics"].clear()
    state["vendor"] = {"workout_count": 3}
    body = _run(mod)
    assert body["missing_count"] == 1
    assert _missing_points(state) == [1.0]


def test_a_store_surplus_is_reported_but_is_not_missing(rec):
    mod, tbl, state = rec
    state["vendor"] = {"workout_count": 2}
    body = _run(mod)
    assert body["missing_count"] == 0 and body["store_only_count"] == 1
    assert _missing_points(state) == [0.0]


# ── failure paths: no datapoint, no write ───────────────────────────────────────────


def test_a_vendor_auth_failure_emits_nothing_and_writes_nothing(rec):
    """An auth failure here is left for the hourly poll to latch — reconcile never writes
    the breaker marker — and no datapoint is emitted, so it is never a false 0."""
    mod, tbl, state = rec
    from training.hevy_common import HevyAPIError

    state["vendor"] = HevyAPIError("Hevy GET /v1/workouts/count → HTTP 401: invalid api key", status=401)
    body = _run(mod)
    assert "HevyAPIError" in body["error"]
    assert state["metrics"] == []
    assert (HEVY_PK, "AUTH_FAILURE") not in tbl.items
    _assert_read_only(tbl, state)


def test_a_changed_count_shape_is_an_error_not_a_zero(rec):
    mod, tbl, state = rec
    state["vendor"] = {"count": 3}
    body = _run(mod)
    assert "workout_count" in body["error"]
    assert state["metrics"] == []
    _assert_read_only(tbl, state)


def test_a_latched_breaker_skips_the_vendor(rec):
    mod, tbl, state = rec
    from datetime import datetime, timezone

    tbl.seed("AUTH_FAILURE", marked_at=datetime.now(timezone.utc).isoformat(), error="401")
    tbl.writes.clear()
    body = _run(mod)
    assert body["skipped"] == "auth_failure_circuit_breaker"
    assert state["calls"] == [] and state["metrics"] == []
    _assert_read_only(tbl, state)


# ── wiring: every provider_reconcile source has a schedule and an alarm pair ─────────

_STACKS = os.path.join(ROOT, "cdk", "stacks")
# Each opted-in source's reconcile is a constant-input rule on its own ingestion Lambda.
_RECONCILE_LAMBDA_VAR = {"strava": "strava", "whoop": "whoop", "hevy": "hevy_backfill"}


def _read(name):
    with open(os.path.join(_STACKS, name), encoding="utf-8") as f:
        return f.read()


def _reconcile_rule_targets(src):
    """Lambda variable names that an events rule targets with the input {"reconcile": True}."""
    found = set()
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "LambdaFunction" and node.args):
            continue
        for kw in node.keywords:
            if kw.arg != "event" or not isinstance(kw.value, ast.Call) or not kw.value.args:
                continue
            arg = kw.value.args[0]
            if isinstance(arg, ast.Dict) and any(
                isinstance(k, ast.Constant) and k.value == "reconcile" and isinstance(v, ast.Constant) and v.value is True
                for k, v in zip(arg.keys, arg.values)
            ):
                if isinstance(node.args[0], ast.Name):
                    found.add(node.args[0].id)
    return found


def test_every_provider_reconcile_source_is_scheduled_and_alarmed():
    """Guard the SET: hevy is one member. A source that opts in through the registry facet
    with no rule never runs; one with no alarm pair emits into nothing."""
    from ingestion.source_registry import provider_reconcile_source_ids

    sources = provider_reconcile_source_ids()
    assert "hevy" in sources
    targets = _reconcile_rule_targets(_read("ingestion_stack.py"))
    monitoring = _read("monitoring_stack.py")
    problems = []
    for src in sources:
        var = _RECONCILE_LAMBDA_VAR.get(src)
        if var is None:
            problems.append(f"{src}: add its Lambda variable to _RECONCILE_LAMBDA_VAR")
        elif var not in targets:
            problems.append(f"{src}: no events rule targets `{var}` with {{'reconcile': True}}")
        for name in (f'"ingest-reconciliation-{src}"', f'"ingest-reconciliation-{src}-heartbeat"'):
            if name not in monitoring:
                problems.append(f"{src}: no alarm {name} in monitoring_stack.py")
        if f'dims={{"Source": "{src}"}}' not in monitoring:
            problems.append(f"{src}: no MissingActivityCount alarm dimensioned Source={src}")
    assert not problems, "\n".join(problems)
