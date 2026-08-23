"""tests/test_auth_breaker_metrics.py — elite review (2026-06-15) batch 3.

The standalone auth_breaker (used by the non-framework ingestion lambdas — notion
+ dropbox-poll) returns a healthy-looking 200 "skip" when tripped, so a dead
credential silently suppressed those sources for 24h with no signal (the same
class that hid the Garmin/Strava deaths). auth_breaker now emits
LifePlatform/OAuth IngestAuthHealthy (0 = broken / short-circuited, 1 = healthy)
so a fleet-wide alarm (Min < 1) catches it.

(SIMP-2 framework sources already record health on breaker-trip via ER-01's
_record_ingest_health, so they're covered separately — these tests cover the
previously-blind standalone path.)
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import boto3  # noqa: E402
from common import auth_breaker as ab  # noqa: E402


class _CW:
    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kw):
        self.calls.append(kw)


def _patch_cw(monkeypatch):
    cw = _CW()
    monkeypatch.setattr(boto3, "client", lambda *a, **k: cw)
    return cw


def _last_value(cw):
    return cw.calls[-1]["MetricData"][0]["Value"]


def test_mark_failure_emits_zero(monkeypatch):
    cw = _patch_cw(monkeypatch)
    ab.mark_failure(MagicMock(), "notion", "matthew", "401 Unauthorized", None)
    assert cw.calls, "mark_failure must emit a metric"
    last = cw.calls[-1]
    assert last["Namespace"] == "LifePlatform/OAuth"
    assert last["MetricData"][0]["MetricName"] == "IngestAuthHealthy"
    assert _last_value(cw) == 0


def test_clear_failure_emits_one(monkeypatch):
    cw = _patch_cw(monkeypatch)
    ab.clear_failure(MagicMock(), "notion", "matthew", None)
    assert _last_value(cw) == 1


def test_check_breaker_fresh_emits_zero_and_returns_item(monkeypatch):
    cw = _patch_cw(monkeypatch)
    table = MagicMock()
    table.get_item.return_value = {
        "Item": {
            "pk": "USER#matthew#SOURCE#notion",
            "sk": "AUTH_FAILURE",
            "marked_at": datetime.now(timezone.utc).isoformat(),
            "error": "401 Unauthorized",
        }
    }
    result = ab.check_breaker(table, "notion", "matthew", None)
    assert result is not None, "fresh marker must short-circuit"
    assert _last_value(cw) == 0, "a short-circuited (suppressed) run must emit 0"


def test_check_breaker_absent_emits_nothing(monkeypatch):
    cw = _patch_cw(monkeypatch)
    table = MagicMock()
    table.get_item.return_value = {}
    assert ab.check_breaker(table, "notion", "matthew", None) is None
    assert cw.calls == [], "no metric when the breaker isn't tripped (only 0/1 on real state)"


def test_check_breaker_expired_emits_nothing(monkeypatch):
    cw = _patch_cw(monkeypatch)
    table = MagicMock()
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    table.get_item.return_value = {"Item": {"sk": "AUTH_FAILURE", "marked_at": old}}
    assert ab.check_breaker(table, "notion", "matthew", None) is None
    assert cw.calls == [], "an expired marker is treated as recovered — no 0 emitted"


def test_emit_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no creds in this env")

    monkeypatch.setattr(boto3, "client", boom)
    # Observability is best-effort: a metric failure must never break ingestion.
    ab.mark_failure(MagicMock(), "notion", "matthew", "401", None)
    ab.clear_failure(MagicMock(), "notion", "matthew", None)


# ── #1960: the Source dimension ─────────────────────────────────────────────
# The metric used to be dimensionless "on purpose" (source name to the log), which
# meant the URGENT page fired by `ingest-auth-unhealthy-24h` could not name WHICH
# OAuth source had died — and made the remediation agent's "duplicate, covered by
# source-specific alarms" ack factually wrong for every source outside the 5-alarm
# consecutive-failures set. Both datapoints now ship in one call.


def _dims(point):
    return {d["Name"]: d["Value"] for d in point.get("Dimensions", [])}


def test_emission_carries_both_dimensionless_and_source_dimensioned(monkeypatch):
    cw = _patch_cw(monkeypatch)
    ab.mark_failure(MagicMock(), "garmin", "matthew", "401 Unauthorized", None)
    data = cw.calls[-1]["MetricData"]
    assert len(data) == 2, "expected exactly two datapoints (aggregate + per-source)"
    plain = [p for p in data if not p.get("Dimensions")]
    tagged = [p for p in data if p.get("Dimensions")]
    assert len(plain) == 1, "the fleet aggregate alarm reads the DIMENSIONLESS stream — it must still be emitted"
    assert len(tagged) == 1
    assert _dims(tagged[0]) == {"Source": "garmin"}, "the per-source page needs Source=<name> to name the culprit"
    assert plain[0]["Value"] == tagged[0]["Value"] == 0
    assert plain[0]["MetricName"] == tagged[0]["MetricName"] == "IngestAuthHealthy"


def test_clear_and_short_circuit_also_carry_the_dimension(monkeypatch):
    cw = _patch_cw(monkeypatch)
    ab.clear_failure(MagicMock(), "todoist", "matthew", None)
    assert _dims(cw.calls[-1]["MetricData"][1]) == {"Source": "todoist"}
    assert cw.calls[-1]["MetricData"][1]["Value"] == 1, "recovery must clear the per-source stream, not just the aggregate"

    table = MagicMock()
    table.get_item.return_value = {"Item": {"sk": "AUTH_FAILURE", "marked_at": datetime.now(timezone.utc).isoformat()}}
    ab.check_breaker(table, "dropbox", "matthew", None)
    assert _dims(cw.calls[-1]["MetricData"][1]) == {"Source": "dropbox"}


def test_metric_data_builder_is_pure_and_stringifies_the_source():
    data = ab.auth_health_metric_data(1, "notion")
    assert data == [
        {"MetricName": "IngestAuthHealthy", "Value": 1, "Unit": "None"},
        {"MetricName": "IngestAuthHealthy", "Value": 1, "Unit": "None", "Dimensions": [{"Name": "Source", "Value": "notion"}]},
    ]


# ── #2976: the healthy path must emit on EVERY authenticated success ────────
# The three-alarm latch incident (2026-08-21→22): IngestAuthHealthy's healthy
# emission only ran on runs that produced NEW DATA (framework: records_written>0;
# dropbox: a CSV processed; notion: pages found), so the Source=dropbox stream had
# never carried a single 1 in its life and a recovered source's alarm could only
# clear by its 24h window sliding past the last 0. The state machine now:
#   failure → 0 (alarm-eligible) · authenticated success → 1 (recovery-eligible,
#   EVEN with zero new records) · paused source → no run, so no emission at all.


def test_framework_clean_zero_record_run_emits_healthy(monkeypatch):
    """A SIMP-2 run whose authenticated fetch finds NO new data is still proof
    the credential works — it must emit IngestAuthHealthy=1. This is the
    load-bearing #2976 case: 'no new data' is the overwhelmingly common run."""
    os.environ.setdefault("S3_BUCKET", "test-bucket")
    from ingestion import ingestion_framework as fw

    cw = _patch_cw(monkeypatch)
    table = MagicMock()
    table.get_item.return_value = {}  # no breaker marker
    monkeypatch.setattr(fw, "_init_aws", lambda config: (table, None, None))
    monkeypatch.setattr(fw, "record_ingest_health", lambda *a, **k: None)

    config = fw.IngestionConfig(source_name="testsrc")
    resp = fw.run_ingestion(
        config,
        authenticate_fn=lambda secret: {},
        fetch_day_fn=lambda creds, d: None,  # clean fetch, nothing new
        transform_fn=lambda raw, d: [],
        event={"date_override": "today"},
        context=None,
    )
    assert resp["statusCode"] == 200
    healthy = [c for c in cw.calls if c["MetricData"][0]["Value"] == 1]
    assert healthy, "a clean zero-record run must emit IngestAuthHealthy=1 — zero new records is not zero proof"
    assert _dims(healthy[-1]["MetricData"][1]) == {"Source": "testsrc"}
    table.delete_item.assert_called()  # the lingering marker (if any) is dropped too


def test_framework_erroring_run_does_not_emit_healthy(monkeypatch):
    """The negative that keeps the test above honest: a run whose per-date fetch
    ERRORS must not emit a 1 (and an auth-shaped error must emit the 0)."""
    os.environ.setdefault("S3_BUCKET", "test-bucket")
    from ingestion import ingestion_framework as fw

    cw = _patch_cw(monkeypatch)
    table = MagicMock()
    table.get_item.return_value = {}

    def _fetch_boom(creds, d):
        raise RuntimeError("401 Unauthorized")

    monkeypatch.setattr(fw, "_init_aws", lambda config: (table, None, None))
    monkeypatch.setattr(fw, "record_ingest_health", lambda *a, **k: None)
    fw.run_ingestion(
        fw.IngestionConfig(source_name="testsrc"),
        authenticate_fn=lambda secret: {},
        fetch_day_fn=_fetch_boom,
        transform_fn=lambda raw, d: [],
        event={"date_override": "today"},
        context=None,
    )
    values = [c["MetricData"][0]["Value"] for c in cw.calls]
    assert 1 not in values, "an erroring run must never claim the credential healthy"
    assert 0 in values, "an auth-shaped per-date error must trip the breaker and emit 0"


def test_dropbox_empty_folder_run_emits_healthy(monkeypatch):
    """The exact incident shape: dropbox recovers, polls, finds 0 files — that
    run must emit IngestAuthHealthy=1 so the per-source alarm can fall."""
    from ingestion import dropbox_poll_lambda as dp

    cw = _patch_cw(monkeypatch)
    table = MagicMock()
    table.get_item.return_value = {}  # no breaker marker
    monkeypatch.setattr(dp, "table", table)
    monkeypatch.setattr(dp, "get_tracker_item", lambda: {})
    monkeypatch.setattr(dp, "_is_recently_empty", lambda tracker: False)
    monkeypatch.setattr(dp, "_mark_empty_poll", lambda: None)
    monkeypatch.setattr(dp, "_record_health", lambda **kw: None)
    monkeypatch.setattr(dp, "get_dropbox_secret", lambda: {"dropbox_app_key": "k", "dropbox_app_secret": "s", "dropbox_refresh_token": "r"})
    monkeypatch.setattr(dp, "refresh_access_token", lambda *a: "token")
    monkeypatch.setattr(dp, "list_folder", lambda tok: [])

    resp = dp.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    healthy = [c for c in cw.calls if c["MetricData"][0]["Value"] == 1]
    assert healthy, "an empty-folder poll authenticated successfully — it must emit IngestAuthHealthy=1"
    assert _dims(healthy[-1]["MetricData"][1]) == {"Source": "dropbox"}


def test_dropbox_recently_empty_skip_emits_nothing(monkeypatch):
    """The COST-03 skip never touches Dropbox, so it proves nothing about the
    credential — it must not emit (in either direction)."""
    from ingestion import dropbox_poll_lambda as dp

    cw = _patch_cw(monkeypatch)
    table = MagicMock()
    table.get_item.return_value = {}
    monkeypatch.setattr(dp, "table", table)
    monkeypatch.setattr(dp, "get_tracker_item", lambda: {"marker": "fresh"})
    monkeypatch.setattr(dp, "_is_recently_empty", lambda tracker: True)
    monkeypatch.setattr(dp, "_record_health", lambda **kw: None)

    resp = dp.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    assert cw.calls == [], "a skip that never reached Dropbox must not claim auth health either way"


def test_notion_no_new_entries_run_emits_healthy(monkeypatch):
    """Notion's common case — an authenticated query returning no pages — must
    emit IngestAuthHealthy=1, not only the entries-written path."""
    from ingestion import notion_lambda as nl

    cw = _patch_cw(monkeypatch)
    table = MagicMock()
    table.get_item.return_value = {}
    monkeypatch.setattr(nl, "table", table)
    monkeypatch.setattr(nl, "get_secrets", lambda: ("api-key", "db-id"))
    monkeypatch.setattr(nl, "query_database", lambda *a, **k: [])
    monkeypatch.setattr(nl, "_record_health", lambda **kw: None)

    resp = nl.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    healthy = [c for c in cw.calls if c["MetricData"][0]["Value"] == 1]
    assert healthy, "a no-new-entries notion run authenticated successfully — it must emit IngestAuthHealthy=1"
    assert _dims(healthy[-1]["MetricData"][1]) == {"Source": "notion"}


def test_emissions_are_strictly_run_driven():
    """The paused-source arm of the #2976 state machine: a paused source (e.g.
    garmin, ADR-074 — no EventBridge rule) must produce NO emission churn. That
    holds structurally iff _emit_auth_health is called only from the three
    state-transition functions, all of which run inside a source's own
    invocation — no cron-independent emitter may exist."""
    import ast as _ast
    import inspect

    src = inspect.getsource(ab)
    tree = _ast.parse(src)
    callers = set()
    for fn in _ast.walk(tree):
        if not isinstance(fn, _ast.FunctionDef):
            continue
        for node in _ast.walk(fn):
            if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Name) and node.func.id == "_emit_auth_health":
                callers.add(fn.name)
    assert callers == {"check_breaker", "mark_failure", "clear_failure"}, (
        f"_emit_auth_health called from {sorted(callers)} — emissions must stay strictly run-driven "
        "so a paused source (no cron) generates no metric churn"
    )


def test_every_registry_oauth_source_can_be_named(monkeypatch):
    """A per-source alarm is only real if the emitter actually tags that source.
    Derived from the registry — never hand-listed (#1960)."""
    import os as _os
    import sys as _sys

    _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "lambdas"))
    from ingestion.source_registry import oauth_source_ids

    for src in oauth_source_ids():
        cw = _patch_cw(monkeypatch)
        ab.mark_failure(MagicMock(), src, "matthew", "401", None)
        assert _dims(cw.calls[-1]["MetricData"][1]) == {"Source": src}
