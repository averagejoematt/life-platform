"""tests/test_ses_event_driven_exempt_2291.py — handler-level behavior of the
event-driven SES exemption (#2291).

**The recorded decision (#2291): the exemption axis is TRIGGER TYPE, not
recipient consent.** The send-suppressor guard exists for operator-invocation
safety — "will invoking this by hand mail someone?" — and consent doesn't
change what a stray manual invoke does. Verdicts:

  - `emails/insight_email_parser_lambda.py` — STAYS exempt. SES inbound
    receipt rule → S3 → Lambda; it sends only in reply to a real inbound
    email. (#2222 never reviewed this module; this is the recorded review.)
  - `web/email_subscriber_lambda.py` — STAYS exempt. A reader's HTTP request
    via the CloudFront /api/subscribe* Function URL; it sends double-opt-in
    mail to the requester only.
  - `web/subscriber_onboarding_lambda.py` — exemption REVOKED. It is
    EventBridge-scheduled (cron(5 17 * * ? *), email_stack.py), so #2222's
    "event-driven" reasoning was factually wrong for it; it now uses the
    shared suppressor like every other scheduled sender.

What "exempt" now buys is ONLY the default posture: no suppression on a real
event. What it does NOT buy is undefined dry-run behavior — every module above
must honor an EXPLICIT `{"dry_run": true}` payload by suppressing the send
(and the paired persistence writes: #2255's "a dry run leaves no record
claiming the real run happened") and reporting the would-have-sent summary via
`common.send_guard.guarded_send_email`. This file proves that contract at the
handler level with the SES double asserted uncalled — and proves the positive
control (the same event without the flag DOES send), so the suppression test
cannot pass vacuously.

The set-level machinery — marker derivation, the no-`schedule=` rule, stale
exemptions — lives in tests/test_ses_send_guard_set_2222.py.
"""

import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
for p in (LAMBDAS,):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("S3_BUCKET", "test-bucket")

from common import dry_run as dry_run_mod  # noqa: E402
from emails import insight_email_parser_lambda as parser_mod  # noqa: E402
from web import (
    email_subscriber_lambda as subscriber_mod,  # noqa: E402
    subscriber_onboarding_lambda as onboarding_mod,  # noqa: E402
)


class FakeSes:
    """Records every send. The suppression tests assert `sends == []` — the
    literal 'SES client mock is uncalled' acceptance of #2291."""

    def __init__(self):
        self.sends = []

    def send_email(self, **kwargs):
        self.sends.append(kwargs)
        return {"MessageId": "really-sent"}


class FakeTable:
    def __init__(self, query_items=None, get_item_item=None):
        self.query_items = query_items or []
        self.get_item_item = get_item_item
        self.puts = []
        self.updates = []

    def put_item(self, **kwargs):
        self.puts.append(kwargs)
        return {}

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        return {}

    def get_item(self, **kwargs):
        return {"Item": self.get_item_item} if self.get_item_item else {}

    def query(self, **kwargs):
        return {"Items": list(self.query_items)}


class FakeS3:
    def __init__(self, body: bytes):
        self._body = body

    def get_object(self, **kwargs):
        return {"Body": io.BytesIO(self._body)}


@pytest.fixture(autouse=True)
def _clean_suppressor_env(monkeypatch):
    """No ambient DRY_RUN/NO_SEND/... may leak into the positive controls."""
    for name in dry_run_mod.SUPPRESSOR_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# ──────────────────────────────────────────────────────────────────────────
# insight_email_parser — SES receipt → S3 → Lambda
# ──────────────────────────────────────────────────────────────────────────

_SENDER_ADDR = "matthew@example.invalid"

_RAW_EMAIL = (
    f"From: Matthew <{_SENDER_ADDR}>\r\n"
    "To: insight@aws.example.invalid\r\n"
    "Subject: Re: Daily Brief\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n"
    "\r\n"
    "track this: sleep debt is clearly driving the afternoon craving window\r\n"
)


def _parser_event(dry_run: bool):
    event = {"Records": [{"s3": {"bucket": {"name": "test-bucket"}, "object": {"key": "raw/inbound_email/msg-1"}}}]}
    if dry_run:
        event["dry_run"] = True
    return event


@pytest.fixture
def parser_env(monkeypatch):
    ses = FakeSes()
    table = FakeTable()
    monkeypatch.setattr(parser_mod, "ses", ses)
    monkeypatch.setattr(parser_mod, "table", table)
    monkeypatch.setattr(parser_mod, "s3", FakeS3(_RAW_EMAIL.encode("utf-8")))
    monkeypatch.setattr(parser_mod, "ALLOWED_SENDERS", {_SENDER_ADDR})
    return ses, table


def test_parser_explicit_dry_run_sends_nothing_and_writes_nothing(parser_env, capsys):
    ses, table = parser_env
    resp = parser_mod.lambda_handler(_parser_event(dry_run=True), None)
    assert ses.sends == [], "explicit dry_run reached SES"
    assert table.puts == [], "explicit dry_run wrote the insight anyway"
    assert json.loads(resp["body"])["dry_run"] is True
    out = capsys.readouterr().out
    assert "[DRY-RUN] SES send suppressed" in out, "the would-have-sent summary was not reported"
    assert _SENDER_ADDR in out, "the dry run did not say WHO it would have mailed"


def test_parser_real_event_still_sends(parser_env):
    """Positive control — the exemption's point is that a REAL inbound-email
    event (no flag) sends the confirmation. Without this, the dry-run test
    could pass because the handler was broken outright."""
    ses, table = parser_env
    parser_mod.lambda_handler(_parser_event(dry_run=False), None)
    assert len(ses.sends) == 1, "a real event must still send the confirmation"
    assert ses.sends[0]["Destination"]["ToAddresses"] == [_SENDER_ADDR]
    # Asserted by PARTITION, not by count: since #3113 a real event writes two
    # rows — the insight, and the DIL-025 send-ledger row recorded one line
    # after the confirmation reply. A bare count would have to be re-bumped by
    # every future writer and says nothing about which write happened.
    saved = [p for p in table.puts if "SOURCE#insights" in p["Item"]["pk"]]
    assert len(saved) == 1, "a real event must still save the insight"


def test_parser_bare_operator_invoke_mails_nobody(parser_env):
    """The trigger-type rationale itself: a stray `{}` invoke has no Records,
    so there is nothing to reply to and no mail goes out even WITHOUT dry_run."""
    ses, table = parser_env
    parser_mod.lambda_handler({}, None)
    assert ses.sends == []
    assert table.puts == []


# ──────────────────────────────────────────────────────────────────────────
# email_subscriber — reader HTTP request via CloudFront Function URL
# ──────────────────────────────────────────────────────────────────────────

_READER = "reader@example-reader.invalid"


def _subscribe_event(dry_run: bool):
    event = {
        "requestContext": {"http": {"method": "POST"}},
        "queryStringParameters": None,
        "headers": {},
        "body": json.dumps({"email": _READER}),
    }
    if dry_run:
        event["dry_run"] = True
    return event


@pytest.fixture
def subscriber_env(monkeypatch):
    ses = FakeSes()
    table = FakeTable()
    monkeypatch.setattr(subscriber_mod, "ses", ses)
    monkeypatch.setattr(subscriber_mod, "table", table)
    # Origin guard off (fail-open state) — this test is about the send gate.
    monkeypatch.setattr(subscriber_mod, "SITE_API_ORIGIN_SECRET", "")
    return ses, table


def test_subscriber_explicit_dry_run_sends_nothing_and_writes_nothing(subscriber_env):
    ses, table = subscriber_env
    resp = subscriber_mod.lambda_handler(_subscribe_event(dry_run=True), None)
    assert ses.sends == [], "explicit dry_run reached SES"
    assert table.puts == [], "explicit dry_run wrote a pending-subscriber record anyway"
    body = json.loads(resp["body"])
    assert body["dry_run"] is True and body["status"] == "pending_confirmation"


def test_subscriber_real_request_still_sends(subscriber_env):
    """Positive control: a real subscribe POST writes the pending record and
    sends the double-opt-in confirmation to the requester."""
    ses, table = subscriber_env
    resp = subscriber_mod.lambda_handler(_subscribe_event(dry_run=False), None)
    assert resp["statusCode"] == 200
    assert len(table.puts) == 1
    assert len(ses.sends) == 1
    assert ses.sends[0]["Destination"]["ToAddresses"] == [_READER]


def test_subscriber_confirm_dry_run_flips_nothing_and_mails_nobody(monkeypatch):
    token = "ab" * 32
    record = {
        "pk": subscriber_mod.SUBSCRIBERS_PK,
        "sk": "EMAIL#deadbeef",
        "email": _READER,
        "email_hash": "deadbeef",
        "status": "pending_confirmation",
        "confirm_token": token,
        "token_expires": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
    }
    ses = FakeSes()
    table = FakeTable(query_items=[record])
    monkeypatch.setattr(subscriber_mod, "ses", ses)
    monkeypatch.setattr(subscriber_mod, "table", table)
    monkeypatch.setattr(subscriber_mod, "SITE_API_ORIGIN_SECRET", "")
    event = {
        "requestContext": {"http": {"method": "GET"}},
        "queryStringParameters": {"action": "confirm", "token": token, "h": "deadbeef"},
        "headers": {},
        "dry_run": True,
    }
    resp = subscriber_mod.lambda_handler(event, None)
    assert ses.sends == [], "dry-run confirm sent the welcome email"
    assert table.updates == [], "dry-run confirm flipped the subscriber's status"
    assert resp["statusCode"] == 302


def test_subscriber_http_payload_cannot_reach_the_flag(subscriber_env):
    """The exemption's safety premise: a real HTTP request cannot set top-level
    event keys, and the resolver never reads body/queryStringParameters — so a
    reader posting `{"email": ..., "dry_run": true}` in the BODY still gets a
    real (sent) subscription flow."""
    ses, table = subscriber_env
    event = _subscribe_event(dry_run=False)
    event["body"] = json.dumps({"email": _READER, "dry_run": True})
    subscriber_mod.lambda_handler(event, None)
    assert len(ses.sends) == 1, "a body-level dry_run must NOT suppress a real reader's confirmation email"
    assert len(table.puts) == 1


# ──────────────────────────────────────────────────────────────────────────
# subscriber_onboarding — exemption REVOKED (it is scheduled)
# ──────────────────────────────────────────────────────────────────────────


class FailingS3:
    def get_object(self, **kwargs):
        raise RuntimeError("no posts.json in this test")


@pytest.fixture
def onboarding_env(monkeypatch):
    sub = {
        "pk": onboarding_mod.SUBSCRIBERS_PK,
        "sk": "EMAIL#cafe1234",
        "email": _READER,
        "confirmed_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
    }
    ses = FakeSes()
    table = FakeTable(query_items=[sub])
    monkeypatch.setattr(onboarding_mod, "ses", ses)
    monkeypatch.setattr(onboarding_mod, "table", table)
    monkeypatch.setattr(onboarding_mod, "s3", FailingS3())
    # Pin the wall-clock-dependent Wednesday gate open (golden-test discipline).
    monkeypatch.setattr(onboarding_mod, "_days_until_wednesday", lambda: 5)
    return ses, table


def test_onboarding_dry_run_sends_nothing_and_marks_nothing(onboarding_env):
    """The revoked exemption, proven at handler level: this scheduled sender now
    honors the DEFAULT suppressor contract — no mail, and crucially no
    onboarding_sent marker (a marked-but-never-mailed subscriber would silently
    lose their bridge email)."""
    ses, table = onboarding_env
    resp = onboarding_mod.lambda_handler({"dry_run": True}, None)
    assert ses.sends == [], "dry_run reached SES"
    assert table.updates == [], "dry_run stamped onboarding_sent without sending"
    body = json.loads(resp["body"])
    assert body["dry_run"] is True and body["would_send"] == 1 and body["sent"] == 0


def test_onboarding_real_run_still_sends_and_marks(onboarding_env):
    """Positive control: the scheduled run sends and stamps the marker."""
    ses, table = onboarding_env
    resp = onboarding_mod.lambda_handler({}, None)
    assert len(ses.sends) == 1
    assert ses.sends[0]["Destination"]["ToAddresses"] == [_READER]
    assert len(table.updates) == 1
    assert json.loads(resp["body"])["sent"] == 1
