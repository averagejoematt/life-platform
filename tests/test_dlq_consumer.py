"""
tests/test_dlq_consumer.py — Unit tests for dlq_consumer_lambda v2 (#402 / ADR-115).

Covers:
  - Stable content identity is stable across re-invoke/re-land, distinct per body
  - record_failure ADDs receive_count to the durable ledger and returns cumulative
  - Transient below threshold + confirmed re-invoke → deleted, no escalation, no noise
  - Transient with an UNCONFIRMED re-invoke → NOT deleted (left on queue to redrive)
  - Permanent classification → escalated (archive + page + SES + delete)
  - Cumulative attempts crossing the threshold → escalate even for a transient body
  - Unretryable message (no resolvable function) → escalate
  - Empty queue → no SES, no SNS
  - Drain loop pulls successive batches until the queue is empty
  - Deliberately-poisoned message that keeps failing accumulates → pages the operator

Run:  python3 -m pytest tests/test_dlq_consumer.py -v
"""

import json
import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
sys.path.insert(0, LAMBDAS)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("DLQ_URL", "https://sqs.fake/queue")
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setenv("ALERTS_TOPIC_ARN", "arn:aws:sns:us-west-2:123:life-platform-alerts")
    monkeypatch.setenv("ESCALATE_THRESHOLD", "3")
    monkeypatch.setenv("AWS_REGION", "us-west-2")


class _Ctx:
    def get_remaining_time_in_millis(self):
        return 120000


def _import_module(ledger_attempts=1):
    """Import dlq_consumer_lambda fresh with all AWS clients/resources mocked.

    `ledger_attempts` seeds the cumulative count returned by record_failure's
    UpdateItem so tests can drive the threshold logic deterministically.
    """
    sys.modules.pop("operational.dlq_consumer_lambda", None)
    sys.modules.pop("dlq_consumer_lambda", None)

    sqs_mock = MagicMock()
    lam_mock = MagicMock()
    ses_mock = MagicMock()
    s3_mock = MagicMock()
    events_mock = MagicMock()
    sns_mock = MagicMock()
    table_mock = MagicMock()
    table_mock.update_item.return_value = {"Attributes": {"attempts": Decimal(ledger_attempts)}}

    clients = {
        "sqs": sqs_mock,
        "lambda": lam_mock,
        "sesv2": ses_mock,
        "s3": s3_mock,
        "events": events_mock,
        "sns": sns_mock,
    }

    def _client_factory(svc, **kw):
        return clients[svc]

    resource_mock = MagicMock()
    resource_mock.Table.return_value = table_mock

    with patch("boto3.client", side_effect=_client_factory), patch("boto3.resource", return_value=resource_mock):
        import importlib

        mod = importlib.import_module("operational.dlq_consumer_lambda")
        importlib.reload(mod)

    mod._sqs, mod._lam, mod._ses, mod._s3, mod._events, mod._sns, mod._tbl = (
        sqs_mock,
        lam_mock,
        ses_mock,
        s3_mock,
        events_mock,
        sns_mock,
        table_mock,
    )
    return mod


def _msg(msg_id="m1", body=None, receive_count=1, handle="h1"):
    if body is None:
        body = json.dumps({"source": "aws.events", "resources": ["arn:aws:events:us-west-2:1:rule/LifePlatformFoo"]})
    return {
        "MessageId": msg_id,
        "ReceiptHandle": handle,
        "Body": body,
        "Attributes": {"ApproximateReceiveCount": str(receive_count)},
    }


# ── Stable identity ──────────────────────────────────────────────────────────────


def test_stable_id_is_stable_and_content_derived(env):
    mod = _import_module()
    a = mod.stable_message_id("fn-x", '{"a":1}')
    b = mod.stable_message_id("fn-x", '{"a":1}')
    c = mod.stable_message_id("fn-x", '{"a":2}')
    d = mod.stable_message_id("fn-y", '{"a":1}')
    assert a == b  # same fn + body → same identity across re-land
    assert a != c  # different body → different identity
    assert a != d  # different function → different identity


def test_record_failure_adds_receive_count_and_returns_cumulative(env):
    mod = _import_module()
    mod._tbl.update_item.return_value = {"Attributes": {"attempts": Decimal(5)}}
    out = mod.record_failure("sid", "fn-x", receive_count=2, body_str="{}")
    assert out == 5
    kwargs = mod._tbl.update_item.call_args.kwargs
    assert kwargs["Key"] == {"pk": "SYSTEM#dlq-ledger", "sk": "MSG#sid"}
    assert "ADD attempts :inc" in kwargs["UpdateExpression"]
    assert kwargs["ExpressionAttributeValues"][":inc"] == Decimal(2)
    # TTL + preview persisted as Decimal/str (DDB-safe, no float)
    assert isinstance(kwargs["ExpressionAttributeValues"][":ttl"], Decimal)


def test_record_failure_fails_soft_on_ddb_error(env):
    mod = _import_module()
    mod._tbl.update_item.side_effect = RuntimeError("ddb down")
    # Falls back to the receive_count so the caller still has a sane number.
    assert mod.record_failure("sid", "fn", receive_count=2, body_str="{}") == 2


# ── Transient path ───────────────────────────────────────────────────────────────


def test_transient_confirmed_retry_deletes_and_does_not_escalate(env):
    mod = _import_module(ledger_attempts=1)
    mod._events.list_targets_by_rule.return_value = {"Targets": [{"Arn": "arn:aws:lambda:us-west-2:1:function:life-platform-foo"}]}
    mod._lam.invoke.return_value = {"StatusCode": 202}
    stats = {"transient": 0, "escalated": 0, "retried_ok": 0, "retried_fail": 0, "left_on_queue": 0}
    escalations = []

    mod.process_message(_msg(), stats, escalations)

    assert stats["retried_ok"] == 1
    assert stats["escalated"] == 0
    assert escalations == []
    mod._lam.invoke.assert_called_once()
    mod._sqs.delete_message.assert_called_once()  # confirmed accept → delete


def test_transient_unconfirmed_retry_is_left_on_queue(env):
    mod = _import_module(ledger_attempts=1)
    mod._events.list_targets_by_rule.return_value = {"Targets": [{"Arn": "arn:aws:lambda:us-west-2:1:function:life-platform-foo"}]}
    mod._lam.invoke.return_value = {"StatusCode": 500}  # NOT accepted
    stats = {"transient": 0, "escalated": 0, "retried_ok": 0, "retried_fail": 0, "left_on_queue": 0}
    escalations = []

    mod.process_message(_msg(), stats, escalations)

    assert stats["retried_fail"] == 1
    assert stats["left_on_queue"] == 1
    assert stats["escalated"] == 0
    mod._sqs.delete_message.assert_not_called()  # unconfirmed → keep on queue


# ── Escalation paths ─────────────────────────────────────────────────────────────


def test_permanent_body_escalates(env):
    mod = _import_module(ledger_attempts=1)
    mod._events.list_targets_by_rule.return_value = {"Targets": [{"Arn": "arn:aws:lambda:us-west-2:1:function:life-platform-foo"}]}
    body = json.dumps(
        {
            "source": "aws.events",
            "resources": ["arn:aws:events:us-west-2:1:rule/LifePlatformFoo"],
            "errorMessage": "403 Forbidden: invalid token",
        }
    )
    stats = {"transient": 0, "escalated": 0, "retried_ok": 0, "retried_fail": 0, "left_on_queue": 0}
    escalations = []

    mod.process_message(_msg(body=body), stats, escalations)

    assert stats["escalated"] == 1
    assert len(escalations) == 1
    assert escalations[0]["classification"] == "permanent"
    mod._s3.put_object.assert_called_once()  # archived
    mod._lam.invoke.assert_not_called()  # permanent → never retried
    mod._sqs.delete_message.assert_called_once()


def test_cumulative_threshold_escalates_a_transient(env):
    # A transient body, but the durable ledger says it has now failed 3 times.
    mod = _import_module(ledger_attempts=3)
    mod._events.list_targets_by_rule.return_value = {"Targets": [{"Arn": "arn:aws:lambda:us-west-2:1:function:life-platform-foo"}]}
    stats = {"transient": 0, "escalated": 0, "retried_ok": 0, "retried_fail": 0, "left_on_queue": 0}
    escalations = []

    mod.process_message(_msg(), stats, escalations)

    assert stats["escalated"] == 1
    assert escalations[0]["classification"] == "threshold"
    assert escalations[0]["attempts"] == 3
    mod._lam.invoke.assert_not_called()  # over threshold → stop retrying


def test_unretryable_message_escalates(env):
    mod = _import_module(ledger_attempts=1)
    # Body with no function name and no resolvable EventBridge rule.
    body = json.dumps({"nothing": "useful"})
    stats = {"transient": 0, "escalated": 0, "retried_ok": 0, "retried_fail": 0, "left_on_queue": 0}
    escalations = []

    mod.process_message(_msg(body=body), stats, escalations)

    assert stats["escalated"] == 1
    assert escalations[0]["classification"] == "unretryable"
    mod._lam.invoke.assert_not_called()


# ── Handler orchestration ────────────────────────────────────────────────────────


def test_empty_queue_no_alerts(env):
    mod = _import_module()
    mod._sqs.receive_message.return_value = {"Messages": []}
    result = mod.lambda_handler({}, _Ctx())
    assert result["statusCode"] == 200
    mod._ses.send_email.assert_not_called()
    mod._sns.publish.assert_not_called()


def test_drain_loops_until_empty(env):
    mod = _import_module(ledger_attempts=1)
    mod._events.list_targets_by_rule.return_value = {"Targets": [{"Arn": "arn:aws:lambda:us-west-2:1:function:life-platform-foo"}]}
    mod._lam.invoke.return_value = {"StatusCode": 202}
    mod._sqs.receive_message.side_effect = [
        {"Messages": [_msg("a", handle="ha"), _msg("b", handle="hb")]},
        {"Messages": [_msg("c", handle="hc")]},
        {"Messages": []},
    ]
    result = mod.lambda_handler({}, _Ctx())
    assert result["statusCode"] == 200
    assert json.loads(result["body"])["messages_processed"] == 3


def test_poisoned_message_pages_operator_end_to_end(env):
    # Deliberately-poisoned message: unretryable + over threshold. Verifies the
    # escalation reaches BOTH the SNS page and the SES summary.
    mod = _import_module(ledger_attempts=4)
    poison = json.dumps({"deliberately": "poisoned", "no_function": True})
    mod._sqs.receive_message.side_effect = [
        {"Messages": [_msg("poison-1", body=poison)]},
        {"Messages": []},
    ]
    result = mod.lambda_handler({}, _Ctx())
    body = json.loads(result["body"])
    assert body["escalated"] == ["poison-1"]
    mod._sns.publish.assert_called_once()  # paged the operator on the urgent topic
    mod._ses.send_email.assert_called_once()  # redundant summary
    mod._s3.put_object.assert_called_once()  # archived for post-mortem
    # The page names the urgent topic ARN and includes an attempt count.
    pub = mod._sns.publish.call_args.kwargs
    assert pub["TopicArn"].endswith("life-platform-alerts")
    assert "URGENT" in pub["Subject"]
