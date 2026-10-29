"""#5433 — a `{"dry_run": true}` traffic-digest invoke must be side-effect free.

Before this fix a dry run suppressed only the SES send (common/send_guard). Both
`cw.put_metric_data` calls still ran: the weekly UniqueVisitors7d / PageViews7d /
SyndicatedReferrals7d put and `_emit_no_logs_alert`'s LogSourceEmpty. UniqueVisitors7d
is read by cost_governor_lambda (`_recent_unique_visitors` takes the latest datapoint
for the surge-ceiling decision; `_weekly_uniques_baseline` expects one point per week),
so a dry-run invoke — the way the #5433 timing proof is taken — silently moved budget
state. These tests pin both metric paths and the SES path under a dry run, with the
non-dry run as the mutation control (metrics still emitted, mail still sent).
"""

import gzip
import io
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "operational"))

import traffic_digest_lambda as td  # noqa: E402

HEADER = "#Version: 1.0\n#Fields: date time c-ip cs-method cs(Host) cs-uri-stem sc-status cs(Referer) cs(User-Agent) cs-uri-query\n"
ONE_VIEW = HEADER + "\t".join(["2026-10-26", "12:00:00", "1.1.1.1", "GET", "averagejoematt.com", "/", "200", "-", "Mozilla/5.0 (Mac)", "-"])


class _FakeS3:
    """A log bucket with `keys` objects (empty list = the LogSourceEmpty path)."""

    def __init__(self, keys, body_text=HEADER):
        self._keys = keys
        self._body = gzip.compress(body_text.encode("utf-8"))

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket, Prefix):
        yield {"Contents": [{"Key": k, "LastModified": datetime.now(timezone.utc)} for k in self._keys]}

    def get_object(self, Bucket, Key):
        if Bucket == td.LOG_BUCKET:
            return {"Body": io.BytesIO(self._body)}
        raise RuntimeError("ops artifact absent in this fixture")  # collect_ops_artifact is fail-soft


class _RecordingCW:
    """Records every write-side call; reads (get_metric_data) answer empty."""

    def __init__(self):
        self.puts = []

    def put_metric_data(self, **kwargs):
        self.puts.append(kwargs)

    def get_metric_data(self, **kwargs):
        return {"MetricDataResults": [{"Values": []}]}


class _RecordingSES:
    def __init__(self):
        self.sends = []

    def send_email(self, **kwargs):
        self.sends.append(kwargs)
        return {"MessageId": "real-send"}


class _FakeBoto3:
    def __init__(self, s3, cw, ses):
        self._clients = {"s3": s3, "cloudwatch": cw, "sesv2": ses}

    def client(self, name, region_name=None):
        if name not in self._clients:
            raise RuntimeError(f"{name} not available in this fixture")  # ssm reads are fail-soft
        return self._clients[name]

    def resource(self, name, region_name=None):
        raise RuntimeError("dynamodb not available in this fixture")  # funnel read is fail-soft


def _invoke(monkeypatch, event, keys, body_text=HEADER):
    monkeypatch.setattr(td, "LOG_BUCKET", "fake-log-bucket")
    cw, ses = _RecordingCW(), _RecordingSES()
    monkeypatch.setattr(td, "boto3", _FakeBoto3(_FakeS3(keys, body_text), cw, ses))
    resp = td.lambda_handler(event, None)
    assert resp["statusCode"] == 200
    return cw, ses


def _metric_names(cw):
    return {m["MetricName"] for call in cw.puts for m in call["MetricData"]}


def test_dry_run_weekly_path_writes_nothing(monkeypatch):
    """Logs present -> the UniqueVisitors7d put and the SES send are both suppressed."""
    cw, ses = _invoke(monkeypatch, {"dry_run": True}, ["cf/log1.gz"], ONE_VIEW)
    assert cw.puts == [], f"dry run emitted CloudWatch metrics: {_metric_names(cw)}"
    assert ses.sends == [], "dry run sent real mail"


def test_dry_run_no_logs_path_writes_nothing(monkeypatch):
    """Zero log objects -> the LogSourceEmpty put and the alert email are both suppressed."""
    cw, ses = _invoke(monkeypatch, {"dry_run": True}, [])
    assert cw.puts == [], f"dry run emitted CloudWatch metrics: {_metric_names(cw)}"
    assert ses.sends == [], "dry run sent the no-logs alert"


def test_dry_run_logs_what_it_would_have_emitted(monkeypatch, caplog):
    caplog.set_level("INFO")
    _invoke(monkeypatch, {"dry_run": True}, ["cf/log1.gz"], ONE_VIEW)
    lines = [r.getMessage() for r in caplog.records if "would PutMetricData" in r.getMessage()]
    assert len(lines) == 1, lines
    assert "UniqueVisitors7d=1" in lines[0] and "PageViews7d[Door=home]=1" in lines[0], lines[0]


def test_mutation_control_real_weekly_run_still_emits_and_sends(monkeypatch):
    """Not a dry run -> exactly the pre-fix weekly put (3 headline + 6 door series) and one email."""
    cw, ses = _invoke(monkeypatch, {}, ["cf/log1.gz"], ONE_VIEW)
    assert len(cw.puts) == 1
    put = cw.puts[0]
    assert put["Namespace"] == "LifePlatform/Traffic"
    headline = {m["MetricName"]: m["Value"] for m in put["MetricData"] if not m.get("Dimensions")}
    assert headline == {"UniqueVisitors7d": 1, "PageViews7d": 1, "SyndicatedReferrals7d": 0}
    doors = {m["Dimensions"][0]["Value"]: m["Value"] for m in put["MetricData"] if m.get("Dimensions")}
    assert set(doors) == set(td.DOORS) and doors["home"] == 1
    assert len(ses.sends) == 1


def test_mutation_control_real_no_logs_run_still_emits_and_sends(monkeypatch):
    cw, ses = _invoke(monkeypatch, {}, [])
    assert cw.puts == [{"Namespace": "LifePlatform/Traffic", "MetricData": [{"MetricName": "LogSourceEmpty", "Value": 1, "Unit": "Count"}]}]
    assert len(ses.sends) == 1
