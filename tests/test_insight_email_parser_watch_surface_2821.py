"""tests/test_insight_email_parser_watch_surface_2821.py — #2821 regression: a parse
failure in insight-email-parser must leave (1) a durable envelope in S3 and (2) an
alarmable EMF metric, instead of nothing.

Before this fix, several per-record failure paths in lambda_handler caught their own
exception and just `continue`d — the function still returned 200, so neither a raised
exception (Lambda Errors metric) nor a DLQ landing would ever see it. This file drives
each of those paths with a dry-run-safe, offline-mocked event and asserts the new
_persist_failure_envelope / _emit_parse_failure_metric contract fires every time:

  - missing S3 key AND no SES messageId on a record        -> reason "missing_s3_key"
  - S3 GetObject raises                                     -> reason "s3_read_failed"
  - email parsing/extraction raises                          -> reason "parse_exception"
  - the DDB insight write raises (the actual write path #2821 is about) -> reason
    "insight_write_failed"
  - anything else, caught by the outer try/except before re-raising -> reason
    "unhandled_exception" (and the exception still propagates — the DLQ safety net,
    wired in cdk/stacks/operational_stack.py, is unchanged by this handler-level fix)

Fully offline: real SES event/record shapes (reused from
tests/test_ses_event_driven_exempt_2291.py's fixtures), a fake S3 client, a fake
CloudWatch client, and a fake DDB table. No AWS credentials, no network.
"""

import io
import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("S3_BUCKET", "test-bucket")

from emails import insight_email_parser_lambda as iep  # noqa: E402

_SENDER_ADDR = "matthew@example.invalid"

_RAW_EMAIL = (
    f"From: Matthew <{_SENDER_ADDR}>\r\n"
    "To: insight@aws.example.invalid\r\n"
    "Subject: Re: Daily Brief\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n"
    "\r\n"
    "track this: sleep debt is clearly driving the afternoon craving window\r\n"
)


def _parser_event(key="raw/inbound_email/msg-1"):
    return {"Records": [{"s3": {"bucket": {"name": "test-bucket"}, "object": {"key": key}}}]}


class FakeTable:
    def __init__(self, put_item_error: Exception = None):
        self.puts = []
        self._put_item_error = put_item_error

    def put_item(self, **kwargs):
        self.puts.append(kwargs)
        if self._put_item_error is not None:
            raise self._put_item_error
        return {}


class FakeS3:
    """Serves a fixed raw email on get_object; records every put_object (the
    failure-envelope archive writes) so tests can assert on them directly."""

    def __init__(self, body: bytes = None, get_object_error: Exception = None):
        self._body = body if body is not None else _RAW_EMAIL.encode("utf-8")
        self._get_object_error = get_object_error
        self.puts = []  # list of (Bucket, Key, parsed-JSON-body)

    def get_object(self, **kwargs):
        if self._get_object_error is not None:
            raise self._get_object_error
        return {"Body": io.BytesIO(self._body)}

    def put_object(self, **kwargs):
        self.puts.append({"Bucket": kwargs.get("Bucket"), "Key": kwargs.get("Key"), "record": json.loads(kwargs.get("Body"))})
        return {}


class FakeCloudWatch:
    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kwargs):
        self.calls.append(kwargs)
        return {}


class FakeSes:
    def __init__(self):
        self.sends = []

    def send_email(self, **kwargs):
        self.sends.append(kwargs)
        return {"MessageId": "sent"}


@pytest.fixture
def env(monkeypatch):
    """The common wiring every test in this file starts from — override
    individual pieces (s3/table) per test to inject the failure under test."""
    table = FakeTable()
    s3 = FakeS3()
    cw = FakeCloudWatch()
    ses = FakeSes()
    monkeypatch.setattr(iep, "table", table)
    monkeypatch.setattr(iep, "s3", s3)
    monkeypatch.setattr(iep, "cloudwatch", cw)
    monkeypatch.setattr(iep, "ses", ses)
    monkeypatch.setattr(iep, "ALLOWED_SENDERS", {_SENDER_ADDR})
    return table, s3, cw, ses


def _assert_failure_signal(s3: FakeS3, cw: FakeCloudWatch, reason: str):
    """The shared contract every failure path must honor: exactly the metric
    the new CDK alarm (life-platform-insight-email-parser-parse-failure)
    watches, and an archived envelope under the handler's own subfolder."""
    assert len(cw.calls) == 1, f"expected exactly one metric emit, got {cw.calls}"
    call = cw.calls[0]
    assert call["Namespace"] == "LifePlatform/Email"
    metric = call["MetricData"][0]
    assert metric["MetricName"] == "InsightParseFailure"
    assert metric["Value"] == 1.0
    assert metric["Unit"] == "Count"

    assert len(s3.puts) == 1, f"expected exactly one archived envelope, got {s3.puts}"
    put = s3.puts[0]
    assert put["Key"].startswith("dead-letter-archive/insight-email-parser/")
    assert put["record"]["reason"] == reason
    assert "failed_at" in put["record"]


# ── missing S3 key AND no SES messageId ──────────────────────────────────────


def test_missing_key_and_message_id_persists_and_emits(env):
    table, s3, cw, ses = env
    event = {"Records": [{}]}  # no s3.object.key, no ses.mail.messageId
    resp = iep.lambda_handler(event, None)
    assert resp["statusCode"] == 200  # the batch is not crashed — just this record skipped
    _assert_failure_signal(s3, cw, "missing_s3_key")
    assert table.puts == []  # nothing written for a record we never even parsed


# ── S3 read failure ───────────────────────────────────────────────────────────


def test_s3_read_failure_persists_and_emits(env, capsys):
    table, s3, cw, ses = env
    s3._get_object_error = RuntimeError("NoSuchKey: the object does not exist")
    resp = iep.lambda_handler(_parser_event(), None)
    assert resp["statusCode"] == 200
    _assert_failure_signal(s3, cw, "s3_read_failed")
    assert table.puts == []
    assert "Failed to read email from S3" in capsys.readouterr().out


# ── email parsing/extraction raises ───────────────────────────────────────────


def test_parse_exception_persists_and_emits(env, monkeypatch):
    table, s3, cw, ses = env

    def _boom(*a, **kw):
        raise ValueError("unexpected MIME structure")

    monkeypatch.setattr(iep, "extract_reply_text", _boom)
    resp = iep.lambda_handler(_parser_event(), None)
    assert resp["statusCode"] == 200
    _assert_failure_signal(s3, cw, "parse_exception")
    assert table.puts == []
    # the raw email itself is preserved so the reply can be recovered by hand
    assert "raw_email" in s3.puts[0]["record"]["payload"]


# ── the DDB insight write itself raises (the actual write path #2821 is about) ──


def test_insight_write_failure_persists_and_emits(env):
    table, s3, cw, ses = env
    table._put_item_error = RuntimeError("ProvisionedThroughputExceededException")
    resp = iep.lambda_handler(_parser_event(), None)
    assert resp["statusCode"] == 200
    _assert_failure_signal(s3, cw, "insight_write_failed")
    # the write was ATTEMPTED (that's how we know it failed) but never landed
    assert len(table.puts) == 1
    # the extracted reply text is preserved in the envelope so it is not lost
    payload = s3.puts[0]["record"]["payload"]
    assert "sleep debt" in payload["reply_text"]
    assert ses.sends == [], "a failed write must not send a false confirmation"


# ── anything else: the outer catch-all, still re-raises (DLQ safety net) ────────


def test_unhandled_exception_persists_then_still_reraises(env, monkeypatch):
    table, s3, cw, ses = env

    def _boom(event):
        raise RuntimeError("totally unexpected shape")

    monkeypatch.setattr(iep, "is_dry_run", _boom)
    with pytest.raises(RuntimeError, match="totally unexpected shape"):
        iep.lambda_handler(_parser_event(), None)
    _assert_failure_signal(s3, cw, "unhandled_exception")


# ── positive control: a clean reply still lands + sends, no failure signal ──────


def test_happy_path_emits_no_failure_signal(env):
    table, s3, cw, ses = env
    resp = iep.lambda_handler(_parser_event(), None)
    assert resp["statusCode"] == 200
    # Two writes since #3113: the insight itself, and the send-ledger completion
    # row recorded one line after the confirmation reply (DIL-025). Asserted by
    # partition rather than by count so a third unrelated write is still caught.
    insight_puts = [p for p in table.puts if "SOURCE#insights" in p["Item"]["pk"]]
    ledger_puts = [p for p in table.puts if "SOURCE#email_log#" in p["Item"]["pk"]]
    assert len(insight_puts) == 1
    assert len(ledger_puts) == 1
    assert len(table.puts) == 2
    assert len(ses.sends) == 1
    assert cw.calls == [], "a successful save must not emit the failure metric"
    assert s3.puts == [], "a successful save must not archive a failure envelope"
