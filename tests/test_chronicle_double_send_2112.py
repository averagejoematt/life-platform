"""#2112 — the Wednesday chronicle sender double-send.

`chronicle-email-sender` fires on cron(10 15 ? * WED *) 10 minutes after
wednesday-chronicle DRAFTS week N (approval comes later), so at 15:10 UTC it can
find LAST week's PUBLISHED installment and send it stale. `chronicle-approve`
ALSO async-invokes the same sender on publish. Result: two subscriber emails on
an approval Wednesday, the first stale — and the subject rendered "Week 0.0"
(float week_number round-tripped through Decimal -> d2f -> float).

Fix: a `delivered_at`/`sent_to_count` marker written on the installment row after
a successful send, checked by `_get_this_weeks_installment` before sending —
whichever trigger (cron or approve-invoke) fires first delivers; the other one
no-ops. `_fmt_week` renders week_number as an int. These tests prove:
  1. an already-delivered installment is never re-sent (both call sites: the
     lookup helper directly, and the full handler with SES mocked)
  2. a fresh, not-yet-delivered installment still sends, and gets marked after
  3. week_number renders without a trailing ".0" in subject and body
  4. the DDB write casts sent_to_count to Decimal (never a bare float)

All DDB/SES access is mocked — this test never touches AWS.
"""

import importlib
from decimal import Decimal
from unittest import mock

import pytest

cel = importlib.import_module("chronicle_email_sender_lambda")


def _installment(**overrides):
    base = {
        "pk": "USER#matthew#SOURCE#chronicle",
        "sk": "DATE#2026-08-02",
        "date": "2026-08-02",
        "source": "chronicle",
        "week_number": 0.0,  # float, as it comes back through d2f()
        "title": "The Plan, On the Record",
        "status": "published",
        "content_html": "<p>Some content.</p>",
    }
    base.update(overrides)
    return base


# ── _fmt_week ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0.0, "0"),
        (0, "0"),
        (Decimal("0"), "0"),
        (12.0, "12"),
        (Decimal("12"), "12"),
        ("?", "?"),  # the installment.get("week_number", "?") placeholder
    ],
)
def test_fmt_week(raw, expected):
    assert cel._fmt_week(raw) == expected


# ── _get_this_weeks_installment: the delivered-marker gate ────────────────────


def test_already_delivered_installment_is_not_returned():
    """The core #2112 assertion: once delivered_at is stamped, the lookup used by
    BOTH triggers (cron and approve-invoke) must no-op, not re-surface the row."""
    item = _installment(delivered_at="2026-08-02T15:10:00+00:00", sent_to_count=Decimal("1"))
    with mock.patch.object(cel.table, "query", return_value={"Items": [item]}):
        assert cel._get_this_weeks_installment() is None


def test_fresh_undelivered_installment_is_still_returned():
    item = _installment()
    assert "delivered_at" not in item
    with mock.patch.object(cel.table, "query", return_value={"Items": [item]}):
        result = cel._get_this_weeks_installment()
    assert result is not None
    assert result["date"] == "2026-08-02"


def test_draft_still_skipped_before_delivered_check():
    # unrelated regression guard: the pre-existing draft skip must keep working
    item = _installment(status="draft")
    with mock.patch.object(cel.table, "query", return_value={"Items": [item]}):
        assert cel._get_this_weeks_installment() is None


# ── _mark_installment_delivered ────────────────────────────────────────────────


def test_mark_delivered_writes_decimal_and_condition():
    with mock.patch.object(cel.table, "update_item") as upd:
        cel._mark_installment_delivered("2026-08-02", 3)
    upd.assert_called_once()
    _, kwargs = upd.call_args
    assert kwargs["Key"] == {"pk": cel.CHRONICLE_PK, "sk": "DATE#2026-08-02"}
    assert kwargs["ConditionExpression"] == "attribute_not_exists(delivered_at)"
    n = kwargs["ExpressionAttributeValues"][":n"]
    assert isinstance(n, Decimal)  # never a bare float on a DDB write
    assert n == Decimal(3)


def test_mark_delivered_is_failsoft_on_conditional_check_failure():
    """A concurrent double-invoke racing past the read-check (the defense-in-depth
    case, not the normal minutes-apart case) must not raise — the send already
    happened either way."""

    class _Boom(Exception):
        pass

    with mock.patch.object(cel.table, "update_item", side_effect=_Boom("ConditionalCheckFailedException")):
        cel._mark_installment_delivered("2026-08-02", 1)  # must not raise


# ── full handler: no double-send, subject renders cleanly ─────────────────────


def _run_handler_with(installment_item, subscribers):
    sent_emails = []

    def _fake_send_email(**kwargs):
        sent_emails.append(kwargs)
        return {"MessageId": "fake"}

    with (
        mock.patch.object(cel.table, "query", return_value={"Items": [installment_item]}),
        mock.patch.object(cel, "_get_confirmed_subscribers", return_value=subscribers),
        mock.patch.object(cel.ses, "send_email", side_effect=_fake_send_email),
        mock.patch.object(cel, "time") as fake_time,
        mock.patch.object(cel.table, "update_item") as upd,
        # #2820: the delivery-heartbeat emit is exercised by its own test file
        # (test_chronicle_delivery_deadman_2820.py); silenced here so these
        # offline tests never attempt a real CloudWatch call.
        mock.patch.object(cel, "_emit_sent_metric"),
    ):
        fake_time.sleep.return_value = None
        result = cel.lambda_handler({}, None)
    return result, sent_emails, upd


def test_handler_sends_fresh_installment_and_marks_delivered(monkeypatch):
    monkeypatch.setenv("EXTERNAL_EMAILS_ENABLED", "true")
    item = _installment()
    subs = [{"email": "reader@example.com", "status": "confirmed"}]
    result, sent_emails, upd = _run_handler_with(item, subs)

    assert result["sent"] == 1
    assert len(sent_emails) == 1
    subject = sent_emails[0]["Content"]["Simple"]["Subject"]["Data"]
    assert "Week 0:" in subject
    assert "Week 0.0" not in subject  # the exact #2112 cosmetic defect

    # the marker write happened, keyed to the right installment, with a Decimal count
    upd.assert_called_once()
    _, kwargs = upd.call_args
    assert kwargs["Key"] == {"pk": cel.CHRONICLE_PK, "sk": "DATE#2026-08-02"}
    assert isinstance(kwargs["ExpressionAttributeValues"][":n"], Decimal)


def test_handler_no_ops_on_already_delivered_installment(monkeypatch):
    """The end-to-end double-send proof: an installment already marked delivered
    must produce ZERO SES sends when the handler runs again (simulating the
    second trigger firing)."""
    monkeypatch.setenv("EXTERNAL_EMAILS_ENABLED", "true")
    item = _installment(delivered_at="2026-08-02T15:10:00+00:00", sent_to_count=Decimal("1"))
    subs = [{"email": "reader@example.com", "status": "confirmed"}]
    result, sent_emails, upd = _run_handler_with(item, subs)

    assert result["sent"] == 0
    assert result.get("skipped") is True
    assert sent_emails == []  # no SES call at all
    upd.assert_not_called()  # nothing to re-mark


def test_handler_does_not_mark_delivered_on_total_send_failure(monkeypatch):
    """sent == 0 (e.g. every SES call failed) must NOT stamp delivered_at — a
    future trigger should get a genuine retry, not a permanently-stuck install."""
    monkeypatch.setenv("EXTERNAL_EMAILS_ENABLED", "true")
    item = _installment()
    subs = [{"email": "reader@example.com", "status": "confirmed"}]

    with (
        mock.patch.object(cel.table, "query", return_value={"Items": [item]}),
        mock.patch.object(cel, "_get_confirmed_subscribers", return_value=subs),
        mock.patch.object(cel.ses, "send_email", side_effect=RuntimeError("SES down")),
        mock.patch.object(cel, "time") as fake_time,
        mock.patch.object(cel.table, "update_item") as upd,
        mock.patch.object(cel, "_emit_sent_metric"),  # #2820: covered in its own test file
    ):
        fake_time.sleep.return_value = None
        result = cel.lambda_handler({}, None)

    assert result["sent"] == 0
    assert result["failed"] == 1
    upd.assert_not_called()
