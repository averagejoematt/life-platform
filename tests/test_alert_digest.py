"""
tests/test_alert_digest.py — Unit tests for alert_digest_lambda.

Covers:
  - SQS drain loop reads until empty and batch-deletes
  - Raw-delivery SNS body is parsed directly as alarm JSON
  - Envelope SNS body falls back to parsing the Message field
  - Grouping dedupes by AlarmName and tracks fire count
  - Empty queue → no SES send, statusCode 200, sent=False
  - Non-empty queue → exactly one SES send with subject + body containing alarm names

Run:  python3 -m pytest tests/test_alert_digest.py -v
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
sys.path.insert(0, LAMBDAS)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("DIGEST_QUEUE_URL", "https://sqs.fake/queue")
    monkeypatch.setenv("EMAIL_RECIPIENT", "test@example.com")
    monkeypatch.setenv("EMAIL_SENDER", "test@example.com")
    monkeypatch.setenv("AWS_REGION", "us-west-2")


def _alarm(name, reason="threshold breached", state="ALARM", t="2026-05-16T15:00:00Z"):
    return json.dumps(
        {
            "AlarmName": name,
            "NewStateValue": state,
            "NewStateReason": reason,
            "StateChangeTime": t,
        }
    )


def _import_module():
    """Import alert_digest_lambda fresh, patching boto3 first."""
    sys.modules.pop("alert_digest_lambda", None)
    with patch("boto3.client") as mock_client:
        sqs_mock = MagicMock()
        ses_mock = MagicMock()

        def _factory(svc, **kw):
            return sqs_mock if svc == "sqs" else ses_mock

        mock_client.side_effect = _factory
        import alert_digest_lambda

        alert_digest_lambda._sqs_mock = sqs_mock
        alert_digest_lambda._ses_mock = ses_mock
    return alert_digest_lambda


def test_parse_raw_delivery_body(env):
    mod = _import_module()
    body = _alarm("ingestion-error-whoop")
    parsed = mod._parse_alarm_payload(body)
    assert parsed["AlarmName"] == "ingestion-error-whoop"
    assert parsed["NewStateValue"] == "ALARM"


def test_parse_envelope_fallback(env):
    mod = _import_module()
    envelope = json.dumps(
        {
            "Type": "Notification",
            "MessageId": "abc",
            "Message": _alarm("ingestion-error-garmin"),
        }
    )
    parsed = mod._parse_alarm_payload(envelope)
    assert parsed["AlarmName"] == "ingestion-error-garmin"


def test_parse_garbage_body(env):
    mod = _import_module()
    parsed = mod._parse_alarm_payload("not json at all")
    assert parsed["AlarmName"] == "unparseable"


def test_group_dedupes_by_alarm_name(env):
    mod = _import_module()
    alarms = [
        {"AlarmName": "A", "NewStateReason": "r1", "StateChangeTime": "2026-05-16T10:00:00Z", "NewStateValue": "ALARM"},
        {"AlarmName": "A", "NewStateReason": "r2", "StateChangeTime": "2026-05-16T11:00:00Z", "NewStateValue": "ALARM"},
        {"AlarmName": "B", "NewStateReason": "rB", "StateChangeTime": "2026-05-16T09:00:00Z", "NewStateValue": "ALARM"},
    ]
    grouped = mod._group_by_alarm(alarms)
    assert set(grouped.keys()) == {"A", "B"}
    assert grouped["A"]["count"] == 2
    # First reason kept; latest state-change kept.
    assert grouped["A"]["reason"] == "r1"
    assert grouped["A"]["last_state_change"] == "2026-05-16T11:00:00Z"
    assert grouped["B"]["count"] == 1


def test_format_email_includes_alarms(env):
    mod = _import_module()
    grouped = {
        "ingestion-error-whoop": {"count": 3, "reason": "API 503", "last_state_change": "...", "last_state": "ALARM"},
        "slo-source-freshness": {"count": 1, "reason": "4 stale sources", "last_state_change": "...", "last_state": "ALARM"},
    }
    subject, body = mod._format_email(grouped)
    assert "2 alarm" in subject
    assert "4 fire" in subject
    assert "ingestion-error-whoop" in body
    assert "slo-source-freshness" in body
    # Sorted by fire count descending.
    assert body.index("ingestion-error-whoop") < body.index("slo-source-freshness")


def test_handler_empty_queue_sends_nothing(env):
    mod = _import_module()
    mod._sqs_mock.receive_message.return_value = {"Messages": []}
    result = mod.lambda_handler({}, None)
    assert result["sent"] is False
    assert result["drained"] == 0
    mod._ses_mock.send_email.assert_not_called()


def test_handler_non_empty_sends_one_email(env):
    mod = _import_module()
    # Two messages for same alarm, then empty on second poll.
    mod._sqs_mock.receive_message.side_effect = [
        {
            "Messages": [
                {"MessageId": "1", "ReceiptHandle": "h1", "Body": _alarm("ingestion-error-whoop")},
                {"MessageId": "2", "ReceiptHandle": "h2", "Body": _alarm("ingestion-error-whoop")},
            ]
        },
        {"Messages": []},
    ]
    result = mod.lambda_handler({}, None)
    assert result["sent"] is True
    assert result["drained"] == 2
    assert result["distinct"] == 1
    mod._ses_mock.send_email.assert_called_once()
    call_kwargs = mod._ses_mock.send_email.call_args.kwargs
    body_text = call_kwargs["Content"]["Simple"]["Body"]["Text"]["Data"]
    assert "ingestion-error-whoop" in body_text
    assert "×2" in body_text
    # Batch delete called once with both messages.
    mod._sqs_mock.delete_message_batch.assert_called_once()


def test_qa_paused_by_budget_alarm_reaches_the_digest_email(env):
    """#1440: the qa-paused-by-budget CloudWatch alarm (monitoring_stack.py,
    watching LifePlatform/QA QAPausedByBudget — emitted by
    lambdas/reader_truth_qa.emit_budget_pause_metric() on a budget-tier pause of
    the reader-truth AI QA pass, either hook — is routed to_digest=True) needs
    NO new code in this lambda: the existing generic drain → group → format
    pipeline already carries ANY alarm on the digest topic into the batched
    email. This test proves that pipeline actually surfaces the new alarm's
    name — the guaranteed 'digest/report line' for a day nothing else fails
    (qa_smoke's own email stays silent on a pause-only night)."""
    mod = _import_module()
    mod._sqs_mock.receive_message.side_effect = [
        {
            "Messages": [
                {
                    "MessageId": "1",
                    "ReceiptHandle": "h1",
                    "Body": _alarm(
                        "qa-paused-by-budget",
                        reason="Threshold Crossed: 1 datapoint [1.0] was greater than or equal to the threshold (1.0).",
                    ),
                }
            ]
        },
        {"Messages": []},
    ]
    result = mod.lambda_handler({}, None)
    assert result["sent"] is True
    call_kwargs = mod._ses_mock.send_email.call_args.kwargs
    body_text = call_kwargs["Content"]["Simple"]["Body"]["Text"]["Data"]
    assert "qa-paused-by-budget" in body_text  # the AI QA pause reaches the digest, never silent
