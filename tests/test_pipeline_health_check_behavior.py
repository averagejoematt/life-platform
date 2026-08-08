"""tests/test_pipeline_health_check_behavior.py — behavioural contracts for
``lambdas/operational/pipeline_health_check_lambda.py`` (#1658 coverage tranche 5).

Measured 16.8% covered before this file (144 of 173 statements missing). Three
modes live in one handler — boot-probe, compute-output verification, and ER-01
infra-liveness — and all three write the numbers the status page and the
``ingest-liveness-unhealthy`` alarm read. The alarm arm in particular is the
44-day-silent-outage class: it is the only check that notices a source whose
cron was removed.

Contracts pinned here:

  * **A paused source is a third state.** DI-1.1: a deliberately-paused source
    must be reported ``paused`` — never counted as healthy (which would mask a
    missing cron) and never as failed (which would alarm on an intentional
    decision). Both the probe path and the liveness path are checked.
  * **Best-effort exclusion narrows the ALARM, not the report.** Garmin's
    accepted upstream 429 must still appear in the verdict list while being
    excluded from ``UnhealthySourceCount``, so it cannot keep the alarm red and
    mask a real death.
  * **Every AWS side-effect is optional.** The CloudWatch emit, the SNS digest
    and the DDB store are each individually allowed to fail without losing the
    verdict — each failure path is exercised.
  * **The compute-output check names the date it expects** — the cascade writes
    yesterday's record, so the probe must ask for yesterday, not today; asking
    for the wrong date is how a vacuous green happens.

No AWS and no network: ``lambda_client``, ``table`` and ``boto3.client`` are
all replaced with recorders. Nothing here ever invokes a real Lambda — note
that ``PIPELINES`` includes ``daily-brief``, so the fake client is installed by
a fixture that every handler test takes.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from operational import pipeline_health_check_lambda as phc

NOW = datetime(2026, 8, 8, 16, 58, tzinfo=timezone.utc)
TODAY = "2026-08-08"
YESTERDAY = "2026-08-07"


# ──────────────────────────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────────────────────────


class _FakeLambdaClient:
    """Records invokes; never touches AWS."""

    def __init__(self, errors=None, raises=frozenset()):
        self.errors = errors or {}
        self.raises = raises
        self.invoked: list[str] = []

    def invoke(self, FunctionName, InvocationType=None, Payload=None):
        self.invoked.append(FunctionName)
        assert Payload == b'{"healthcheck": true}', "the probe must ask for a boot check, never a real run"
        if FunctionName in self.raises:
            raise RuntimeError("ResourceNotFoundException")
        if FunctionName in self.errors:

            class _Body:
                def read(_self):
                    return json.dumps(self.errors[FunctionName]).encode()

            return {"StatusCode": 200, "FunctionError": "Unhandled", "Payload": _Body()}
        return {"StatusCode": 200}


class _FakeTable:
    def __init__(self, items=None, query_items=None, get_boom=False, put_boom=False, query_boom=False):
        self.items = items or {}
        self.query_items = query_items or []
        self.get_boom = get_boom
        self.put_boom = put_boom
        self.query_boom = query_boom
        self.puts: list[dict] = []

    def get_item(self, Key, **kw):
        if self.get_boom:
            raise RuntimeError("throttled")
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}

    def query(self, **kw):
        if self.query_boom:
            raise RuntimeError("query denied")
        return {"Items": list(self.query_items)}

    def put_item(self, Item):
        if self.put_boom:
            raise RuntimeError("AccessDenied")
        self.puts.append(Item)


class _Recorder:
    def __init__(self, boom=False):
        self.metrics: list[dict] = []
        self.publishes: list[dict] = []
        self.described: list[str] = []
        self.boom = boom
        self.secret_state: dict = {}

    def put_metric_data(self, **kw):
        if self.boom:
            raise RuntimeError("cloudwatch down")
        self.metrics.append(kw)

    def publish(self, **kw):
        if self.boom:
            raise RuntimeError("sns down")
        self.publishes.append(kw)

    def describe_secret(self, SecretId):
        self.described.append(SecretId)
        state = self.secret_state.get(SecretId, "ok")
        if state == "missing":
            raise RuntimeError("ResourceNotFoundException: nope")
        if state == "other":
            raise RuntimeError("AccessDeniedException")
        return {"DeletedDate": "2026-09-01"} if state == "deleted" else {}


@pytest.fixture()
def aws(monkeypatch):
    """Install the shared recorder for cloudwatch/sns/secretsmanager."""
    rec = _Recorder()
    monkeypatch.setattr(phc.boto3, "client", lambda name, region_name=None: rec)
    return rec


@pytest.fixture()
def fake_lambda(monkeypatch):
    def _install(**kw):
        c = _FakeLambdaClient(**kw)
        monkeypatch.setattr(phc, "lambda_client", c)
        return c

    return _install


@pytest.fixture()
def fake_table(monkeypatch):
    def _install(**kw):
        t = _FakeTable(**kw)
        monkeypatch.setattr(phc, "table", t)
        return t

    return _install


# ──────────────────────────────────────────────────────────────────────────────
# _probe_lambda
# ──────────────────────────────────────────────────────────────────────────────


def test_probe_reports_a_clean_boot_as_healthy(fake_lambda):
    c = fake_lambda()
    assert phc._probe_lambda("whoop-data-ingestion") == {"healthy": True}
    assert c.invoked == ["whoop-data-ingestion"]


def test_probe_surfaces_the_functions_own_error_type_and_message(fake_lambda):
    fake_lambda(errors={"garmin-data-ingestion": {"errorType": "AuthError", "errorMessage": "x" * 400}})
    out = phc._probe_lambda("garmin-data-ingestion")
    assert out["healthy"] is False
    assert out["error_type"] == "AuthError"
    assert len(out["error_message"]) == 120, "the message is truncated so one bad probe cannot blow the DDB item"


def test_probe_distinguishes_an_invocation_failure_from_a_function_failure(fake_lambda):
    fake_lambda(raises={"ghost-lambda"})
    out = phc._probe_lambda("ghost-lambda")
    assert out["healthy"] is False and out["error_type"] == "InvocationError"


def test_probe_defaults_an_unlabelled_error(fake_lambda):
    fake_lambda(errors={"fn": {}})
    assert phc._probe_lambda("fn")["error_type"] == "Unknown"


# ──────────────────────────────────────────────────────────────────────────────
# _check_compute_outputs
# ──────────────────────────────────────────────────────────────────────────────

_COMPUTE_PARTITIONS = ("character_sheet", "computed_metrics", "computed_insights", "adaptive_mode")


def _compute_rows(present, date=YESTERDAY):
    return {(f"USER#matthew#SOURCE#{p}", f"DATE#{date}"): {"sk": f"DATE#{date}"} for p in present}


def test_compute_outputs_asks_for_yesterdays_record_not_todays(fake_table, aws):
    """The cascade computes the COMPLETED day. Probing today's key would pass
    only by accident and would go green on a day the cascade never ran."""
    fake_table(items=_compute_rows(_COMPUTE_PARTITIONS, date=TODAY))
    out = phc._check_compute_outputs(TODAY)
    assert out["all_present"] is False, "today-dated rows must NOT satisfy the check"
    assert {m["expected_date"] for m in out["missing"]} == {YESTERDAY}


def test_compute_outputs_green_when_the_whole_cascade_landed(fake_table, aws):
    fake_table(items=_compute_rows(_COMPUTE_PARTITIONS))
    out = phc._check_compute_outputs(TODAY)
    assert out["all_present"] is True
    assert sorted(out["present"]) == sorted(_COMPUTE_PARTITIONS)
    assert out["missing"] == []


def test_compute_outputs_names_each_missing_partition_with_its_key(fake_table, aws):
    fake_table(items=_compute_rows(("character_sheet", "computed_metrics")))
    out = phc._check_compute_outputs(TODAY)
    assert [m["source_id"] for m in out["missing"]] == ["computed_insights", "adaptive_mode"]
    assert out["missing"][0]["pk"] == "USER#matthew#SOURCE#computed_insights"
    assert out["missing"][0]["sk"] == f"DATE#{YESTERDAY}"
    assert out["missing"][0]["display"] == "Daily Insights"


def test_compute_outputs_counts_a_read_error_as_missing_and_says_why(fake_table, aws):
    fake_table(get_boom=True)
    out = phc._check_compute_outputs(TODAY)
    assert len(out["missing"]) == 4
    assert all("error" in m for m in out["missing"])


def test_compute_outputs_emits_the_missing_count_metric(fake_table, aws):
    fake_table(items=_compute_rows(("character_sheet",)))
    phc._check_compute_outputs(TODAY)
    (emit,) = aws.metrics
    assert emit["Namespace"] == "LifePlatform/Pipeline"
    assert emit["MetricData"][0] == {"MetricName": "ComputeOutputsMissing", "Value": 3.0, "Unit": "Count"}


def test_compute_outputs_survives_a_failed_metric_emit(fake_table, monkeypatch):
    fake_table(items=_compute_rows(_COMPUTE_PARTITIONS))
    monkeypatch.setattr(phc.boto3, "client", lambda name, region_name=None: _Recorder(boom=True))
    assert phc._check_compute_outputs(TODAY)["all_present"] is True


# ──────────────────────────────────────────────────────────────────────────────
# _check_ingest_liveness
# ──────────────────────────────────────────────────────────────────────────────


def _sentinel(source, streak=0, minutes_ago=60, err="none"):
    ts = (NOW - timedelta(minutes=minutes_ago)).isoformat()
    return {
        "sk": f"INGEST_HEALTH#{source}",
        "source": source,
        "consecutive_failures": streak,
        "last_attempt_ts": ts,
        "last_error_class": err,
    }


@pytest.fixture()
def liveness_env(monkeypatch, fake_table, aws):
    def _install(sources, sentinels, best_effort=(), paused=()):
        monkeypatch.setattr(phc, "ACTIVE_API_SOURCES", list(sources))
        monkeypatch.setattr(phc, "BEST_EFFORT_SOURCES", list(best_effort))
        monkeypatch.setattr(phc, "is_paused", lambda s: s in paused)
        t = fake_table(query_items=sentinels)
        return t, aws

    return _install


def test_liveness_all_ok_emits_zero_and_does_not_page(liveness_env):
    t, rec = liveness_env(["whoop", "withings"], [_sentinel("whoop"), _sentinel("withings")])
    out = phc._check_ingest_liveness(NOW)
    assert out["unhealthy_count"] == 0
    assert [v["status"] for v in out["verdicts"]] == ["ok", "ok"]
    assert rec.metrics[0]["MetricData"][0] == {"MetricName": "UnhealthySourceCount", "Value": 0, "Unit": "Count"}
    assert rec.publishes == [], "a healthy sweep must be silent"


def test_liveness_a_source_that_stopped_running_alerts(liveness_env):
    t, rec = liveness_env(["whoop"], [_sentinel("whoop", minutes_ago=3000)])
    out = phc._check_ingest_liveness(NOW)
    assert out["unhealthy_count"] == 1
    assert out["verdicts"][0]["status"] == "stale", "attempt-staleness is the arm that notices a removed cron"
    (pub,) = rec.publishes
    assert "1 source(s) failing" in pub["Subject"]
    assert "whoop: STALE" in pub["Message"]
    assert "NOT data-freshness" in pub["Message"]


def test_liveness_a_source_with_no_sentinel_is_unknown_and_never_alerts(liveness_env):
    t, rec = liveness_env(["hevy"], [])
    out = phc._check_ingest_liveness(NOW)
    assert out["verdicts"][0]["status"] == "unknown"
    assert out["unhealthy_count"] == 0, "a first-deploy source must not flood the alarm"


def test_liveness_best_effort_source_is_reported_but_excluded_from_the_count(liveness_env):
    t, rec = liveness_env(["whoop", "garmin"], [_sentinel("whoop"), _sentinel("garmin", minutes_ago=9999)], best_effort=["garmin"])
    out = phc._check_ingest_liveness(NOW)
    assert out["unhealthy_count"] == 0, "an accepted upstream failure must not keep the alarm red"
    statuses = {v["source"]: v["status"] for v in out["verdicts"]}
    assert statuses["garmin"] == "stale", "…but it stays fully visible in the verdict list"
    assert rec.publishes == []


def test_liveness_paused_source_is_excluded_and_stamped(liveness_env):
    """DI-1.1: a paused source has no cron to be 'stopped'; the staleness arm
    would false-fire on it forever."""
    t, rec = liveness_env(["strava"], [_sentinel("strava", minutes_ago=99999)], paused=["strava"])
    out = phc._check_ingest_liveness(NOW)
    assert out["unhealthy_count"] == 0
    assert out["verdicts"][0]["paused"] is True


def test_liveness_persists_the_verdicts_for_the_status_page(liveness_env):
    t, rec = liveness_env(["whoop"], [_sentinel("whoop")])
    phc._check_ingest_liveness(NOW)
    (item,) = t.puts
    assert item["pk"] == "USER#matthew#SOURCE#ingest_liveness"
    assert item["sk"] == f"DATE#{TODAY}"
    assert item["unhealthy_count"] == 0
    assert json.loads(item["verdicts"])[0]["source"] == "whoop"


def test_liveness_reports_a_sentinel_query_failure_rather_than_a_false_all_clear(liveness_env, fake_table):
    liveness_env(["whoop"], [])
    fake_table(query_boom=True)
    out = phc._check_ingest_liveness(NOW)
    assert set(out) == {"error"}, "a failed read must not be reported as zero unhealthy sources"


def test_liveness_skips_cleanly_when_the_ingest_health_module_is_unavailable(monkeypatch):
    monkeypatch.setattr(phc, "_INGEST_HEALTH_AVAILABLE", False)
    assert phc._check_ingest_liveness(NOW) == {"skipped": "ingest_health_unavailable"}


def test_liveness_survives_failures_of_every_optional_side_effect(liveness_env, monkeypatch, fake_table):
    monkeypatch.setattr(phc, "ACTIVE_API_SOURCES", ["whoop"])
    monkeypatch.setattr(phc, "BEST_EFFORT_SOURCES", [])
    monkeypatch.setattr(phc, "is_paused", lambda s: False)
    fake_table(query_items=[_sentinel("whoop", minutes_ago=9999)], put_boom=True)
    monkeypatch.setattr(phc.boto3, "client", lambda name, region_name=None: _Recorder(boom=True))
    out = phc._check_ingest_liveness(NOW)
    assert out["unhealthy_count"] == 1, "metric, SNS and store may all fail; the verdict still returns"


# ──────────────────────────────────────────────────────────────────────────────
# lambda_handler — mode routing
# ──────────────────────────────────────────────────────────────────────────────


def test_handler_routes_to_the_liveness_mode(monkeypatch, fake_lambda):
    fake_lambda()
    monkeypatch.setattr(phc, "_check_ingest_liveness", lambda now: {"unhealthy_count": 2, "verdicts": []})
    resp = phc.lambda_handler({"check_ingest_liveness": True}, None)
    assert json.loads(resp["body"])["unhealthy_count"] == 2


def test_handler_compute_mode_pages_the_digest_when_records_are_missing(monkeypatch, fake_lambda, fake_table, aws):
    fake_lambda()
    fake_table(items=_compute_rows(("character_sheet",)))
    resp = phc.lambda_handler({"check_compute_outputs": True}, None)
    body = json.loads(resp["body"])
    assert body["all_present"] is False
    (pub,) = aws.publishes
    assert pub["Subject"].startswith("Compute pipeline incomplete")
    assert "Daily-brief will read yesterday's data" in pub["Message"]
    assert "Daily Metrics" in pub["Message"]


def test_handler_compute_mode_is_silent_when_the_cascade_is_whole(monkeypatch, fake_lambda, fake_table, aws):
    fake_lambda()
    fake_table(items=_compute_rows(_COMPUTE_PARTITIONS))
    resp = phc.lambda_handler({"check_compute_outputs": True}, None)
    assert json.loads(resp["body"])["all_present"] is True
    assert aws.publishes == []


def test_handler_compute_mode_survives_a_failed_sns_publish(monkeypatch, fake_lambda, fake_table):
    fake_lambda()
    fake_table(items={})
    monkeypatch.setattr(phc.boto3, "client", lambda name, region_name=None: _Recorder(boom=True))
    resp = phc.lambda_handler({"check_compute_outputs": True}, None)
    assert resp["statusCode"] == 200


# ──────────────────────────────────────────────────────────────────────────────
# lambda_handler — default boot-probe mode
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def probe_env(monkeypatch, fake_lambda, fake_table):
    def _install(errors=None, paused=(), secret_state=None, pipelines=None, put_boom=False):
        rec = _Recorder()
        rec.secret_state = secret_state or {}
        monkeypatch.setattr(phc.boto3, "client", lambda name, region_name=None: rec)
        monkeypatch.setattr(phc, "is_paused", lambda s: s in paused)
        if pipelines is not None:
            monkeypatch.setattr(phc, "PIPELINES", pipelines)
        c = fake_lambda(errors=errors or {})
        t = fake_table(put_boom=put_boom)
        return c, t, rec

    return _install


_TWO = [("whoop-data-ingestion", "Whoop", "whoop"), ("strava-data-ingestion", "Strava", "strava")]


def test_default_mode_probes_every_pipeline_and_tallies(probe_env):
    c, t, rec = probe_env(pipelines=_TWO)
    body = json.loads(phc.lambda_handler({}, None)["body"])
    assert sorted(c.invoked) == ["strava-data-ingestion", "whoop-data-ingestion"]
    assert body == {"passed": 2, "failed": 0, "paused": 0, "total": 2, "failures": []}


def test_default_mode_skips_the_boot_probe_for_a_paused_source(probe_env):
    """A paused source's 'ok' would only prove the Lambda boots — it would mask
    that the cron is gone. Neither green nor red: paused."""
    c, t, rec = probe_env(pipelines=_TWO, paused={"strava"})
    body = json.loads(phc.lambda_handler({}, None)["body"])
    assert c.invoked == ["whoop-data-ingestion"], "the paused source is never invoked"
    assert body["paused"] == 1 and body["passed"] == 1 and body["failed"] == 0
    stored = json.loads(t.puts[0]["results"])
    paused_row = next(r for r in stored if r["source_id"] == "strava")
    assert paused_row["state"] == "paused" and paused_row["paused"] is True


def test_default_mode_reports_a_crashing_pipeline_in_the_failures_list(probe_env):
    c, t, rec = probe_env(pipelines=_TWO, errors={"strava-data-ingestion": {"errorType": "AuthError", "errorMessage": "token dead"}})
    body = json.loads(phc.lambda_handler({}, None)["body"])
    assert body["failed"] == 1
    assert body["failures"] == [{"name": "Strava", "error": "token dead"}]


def test_default_mode_flags_a_deleted_and_a_missing_required_secret(probe_env):
    c, t, rec = probe_env(
        pipelines=_TWO,
        secret_state={"life-platform/whoop": "deleted", "life-platform/hevy": "missing", "life-platform/notion": "other"},
    )
    body = json.loads(phc.lambda_handler({}, None)["body"])
    names = {f["name"] for f in body["failures"]}
    assert "Secret: life-platform/whoop" in names
    assert "Secret: life-platform/hevy" in names
    assert not any("notion" in n for n in names), "a non-NotFound error (e.g. AccessDenied) is not evidence the secret is gone"
    assert len(rec.described) == 12, "the audited REQUIRED_SECRETS list (#518) — dropbox deliberately absent"
    assert "life-platform/dropbox" not in rec.described


def test_default_mode_stores_the_run_and_survives_a_failed_store(probe_env):
    c, t, rec = probe_env(pipelines=_TWO)
    phc.lambda_handler({}, None)
    (item,) = t.puts
    assert item["pk"] == "USER#matthew#SOURCE#health_check"
    assert item["passed"] == 2 and item["failed"] == 0

    c, t, rec = probe_env(pipelines=_TWO, put_boom=True)
    assert phc.lambda_handler({}, None)["statusCode"] == 200


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT: the health-check tally does not add up. `total` is hardcoded to "
        "len(PIPELINES), but a deleted/missing REQUIRED_SECRET increments "
        "fail_count and appends to `results` without being part of that total — "
        "so a run with two dead secrets reports e.g. total=2, passed=2, failed=2, "
        "and both the API response and the DDB item the status page reads are "
        "internally inconsistent (passed+failed+paused > total). Correct "
        "behaviour: total counts everything evaluated, or the secret findings are "
        "tallied on their own axis. ADR-105. Reported by #1658 coverage tranche 5; "
        "not fixed here."
    ),
)
def test_defect_health_check_tally_must_reconcile(probe_env):
    c, t, rec = probe_env(pipelines=_TWO, secret_state={"life-platform/whoop": "deleted", "life-platform/hevy": "missing"})
    body = json.loads(phc.lambda_handler({}, None)["body"])
    assert body["passed"] + body["failed"] + body["paused"] == body["total"], body


# ──────────────────────────────────────────────────────────────────────────────
# Registry-derived constants
# ──────────────────────────────────────────────────────────────────────────────


def test_active_and_best_effort_sets_are_derived_from_the_registry():
    """#498 (X-10): these were two hand-rolled copies of 'which pulls must
    attempt daily'. They must stay derived, and best-effort must be a subset."""
    from ingestion.source_registry import active_api_source_ids, best_effort_source_ids

    assert phc.ACTIVE_API_SOURCES == active_api_source_ids()
    assert phc.BEST_EFFORT_SOURCES == best_effort_source_ids()
    assert set(phc.BEST_EFFORT_SOURCES) <= set(
        phc.ACTIVE_API_SOURCES
    ), "a best-effort source that isn't in the active set silently excludes nothing"


def test_no_per_source_gap_override_is_currently_needed():
    """Census: SOURCE_MAX_GAP_MINUTES is empty, so every source uses the 1560-minute
    (26h) default. A sparser-than-daily source added without an entry here would
    alarm every day."""
    assert phc.SOURCE_MAX_GAP_MINUTES == {}


def test_environment_defaults_are_the_documented_ones():
    assert phc.USER_ID == os.environ.get("USER_ID", "matthew")
    assert phc.TABLE_NAME == os.environ.get("TABLE_NAME", "life-platform")
