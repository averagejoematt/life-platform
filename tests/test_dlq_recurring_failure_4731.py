"""
tests/test_dlq_recurring_failure_4731.py — a recurring failure escalates (#4731).

The live specimen (2026-10-05 → 10-10): `daily-metrics-compute` crashed on every
run with the same TypeError. Each scheduled run is a NEW EventBridge event (new
`id`/`time`), so the consumer's body-hash ledger counted 1,2,3 and then 1 again
every day, re-invoking the crashing function every 6 hours. Meanwhile the
16:40Z run's failures came from a hand-made rule the consumer's role cannot
`ListTargetsByRule`, and archived as `fn=unknown` without a retry.

The fixtures below are the real DLQ message shapes, copied from the consumer's
own `dead-letter-archive/2026/10/09/*.json` records (read-only).

Run:  python3 -m pytest tests/test_dlq_recurring_failure_4731.py -v
"""

import json
import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

ERROR_TEXT = "'>' not supported between instances of 'int' and 'str'"


def _event_body(rule: str, event_id: str, time_iso: str) -> str:
    """The exact body shape Lambda's async DLQ hands the consumer: the original
    EventBridge scheduled event, compact-serialised."""
    return json.dumps(
        {
            "version": "0",
            "id": event_id,
            "detail-type": "Scheduled Event",
            "source": "aws.events",
            "account": "205930651321",
            "time": time_iso,
            "region": "us-west-2",
            "resources": [f"arn:aws:events:us-west-2:205930651321:rule/{rule}"],
            "detail": {},
        },
        separators=(",", ":"),
    )


# Real shapes (dead-letter-archive/2026/10/09/7aebbca3-….json and 30a13f99-….json).
RULE_1640 = "daily-metrics-compute"
RULE_CDK_EVENING = "LifePlatformCompute-DailyMetricsComputeEvening76492-JXPpasegfsuT"


def _dlq_msg(msg_id: str, body: str, error_text: str = ERROR_TEXT, request_id: str = "045aed0d-5e0a-4e8d-96dc-2a992a1cf962") -> dict:
    return {
        "MessageId": msg_id,
        "ReceiptHandle": f"rh-{msg_id}",
        "Body": body,
        "Attributes": {
            "SenderId": "AROAS74TML24X5WYYCV5Y:awslambda_215_20261009164326292",
            "ApproximateReceiveCount": "1",
            "SentTimestamp": "1791564206327",
        },
        "MessageAttributes": {
            "ErrorCode": {"StringValue": "200", "DataType": "Number"},
            "ErrorMessage": {"StringValue": error_text, "DataType": "String"},
            "RequestID": {"StringValue": request_id, "DataType": "String"},
        },
    }


MSG_1640 = _dlq_msg(
    "7aebbca3-bb46-4c09-b7c9-b4b8c39344ad", _event_body(RULE_1640, "26a8d5f0-1aeb-21cd-3b69-dd02097630e2", "2026-10-09T16:40:00Z")
)
MSG_CDK = _dlq_msg(
    "30a13f99-392b-4928-8681-7fe782452c84",
    _event_body(RULE_CDK_EVENING, "a2dc43eb-808a-72f0-32b9-1346d20a42b3", "2026-10-09T00:00:00Z"),
    request_id="dfebc64d-7ad8-4284-98dd-23adcda5a638",
)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("DLQ_URL", "https://sqs.fake/queue")
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setenv("ALERTS_TOPIC_ARN", "arn:aws:sns:us-west-2:123:life-platform-alerts")
    monkeypatch.setenv("ESCALATE_THRESHOLD", "3")
    monkeypatch.setenv("AWS_REGION", "us-west-2")


class _Ledger:
    """A stateful stand-in for the DDB ledger: ADD attempts per sort key."""

    def __init__(self):
        self.rows: dict[str, int] = {}

    def update_item(self, **kw):
        sk = kw["Key"]["sk"]
        vals = kw.get("ExpressionAttributeValues", {})
        if ":inc" in vals:
            self.rows[sk] = self.rows.get(sk, 0) + int(vals[":inc"])
        return {"Attributes": {"attempts": Decimal(self.rows.get(sk, 0))}}


def _import_module():
    sys.modules.pop("operational.dlq_consumer_lambda", None)
    mocks = {svc: MagicMock() for svc in ("sqs", "lambda", "sesv2", "s3", "events", "sns")}
    ledger = _Ledger()
    table = MagicMock()
    table.update_item.side_effect = ledger.update_item
    resource = MagicMock()
    resource.Table.return_value = table

    with patch("boto3.client", side_effect=lambda svc, **kw: mocks[svc]), patch("boto3.resource", return_value=resource):
        import importlib

        mod = importlib.import_module("operational.dlq_consumer_lambda")
        importlib.reload(mod)

    # The live role is denied ListTargetsByRule on every non-LifePlatform* rule.
    def _list_targets(Rule):
        if Rule.startswith("LifePlatform"):
            return {"Targets": [{"Arn": "arn:aws:lambda:us-west-2:205930651321:function:daily-metrics-compute"}]}
        raise RuntimeError("AccessDeniedException: not authorized to perform: events:ListTargetsByRule")

    mocks["events"].list_targets_by_rule.side_effect = _list_targets
    mocks["lambda"].invoke.return_value = {"StatusCode": 202}
    mod._rule_fn_cache.clear()
    return mod, mocks, ledger, table


def _stats():
    return {"transient": 0, "escalated": 0, "retried_ok": 0, "retried_fail": 0, "left_on_queue": 0}


# ── Acceptance 1: keyed by function + failure signature ─────────────────────────


def test_two_message_ids_for_the_same_failure_accumulate_on_one_ledger_row(env):
    """The 00:00Z (CDK rule, ARN-resolved) and 16:40Z (hand rule, name-resolved)
    crashes are different message ids AND different bodies — one ledger row."""
    mod, _mocks, ledger, table = _import_module()
    escalations: list = []

    mod.process_message(MSG_CDK, _stats(), escalations)
    mod.process_message(MSG_1640, _stats(), escalations)

    ledger_sks = {c.kwargs["Key"]["sk"] for c in table.update_item.call_args_list if ":inc" in c.kwargs["ExpressionAttributeValues"]}
    assert len(ledger_sks) == 1, f"same failure split across ledger rows: {ledger_sks}"
    assert list(ledger.rows.values()) == [2], ledger.rows


def test_a_different_failure_on_the_same_function_is_a_different_row(env):
    mod, _mocks, ledger, _table = _import_module()
    other = _dlq_msg("m-other", MSG_1640["Body"], error_text="KeyError: 'habit_registry'")
    mod.process_message(MSG_1640, _stats(), [])
    mod.process_message(other, _stats(), [])
    assert sorted(ledger.rows.values()) == [1, 1]


def test_signature_masks_volatile_tokens(env):
    mod, _mocks, _ledger, _table = _import_module()
    a = mod.failure_signature(_dlq_msg("a", "{}", error_text="timeout after 30012 ms on req 1f2e3d4c-1111-2222-3333-444455556666"))
    b = mod.failure_signature(_dlq_msg("b", "{}", error_text="timeout after 29870 ms on req 99999999-aaaa-bbbb-cccc-ddddeeeeffff"))
    assert a == b and a
    assert mod.failure_signature({"Body": "{}"}) == ""  # no error attribute → body fallback


# ── Acceptance 2: past the threshold, stop re-invoking and escalate by name ─────


def test_a_crash_recurring_across_days_stops_being_reinvoked_and_escalates(env, capsys):
    """Five days of the same crash, one new scheduled event per consumer pass.
    The first two passes re-invoke; from the third on, never again — each one
    escalates with the function named in the metric and the page."""
    mod, mocks, _ledger, _table = _import_module()
    passes = [
        _dlq_msg(
            f"m{i}", _event_body(RULE_1640, f"evt-{i}", f"2026-10-0{5 + i}T16:40:00Z"), request_id=f"0000000{i}-0000-0000-0000-000000000000"
        )
        for i in range(5)
    ]
    for p in passes:
        mocks["sqs"].receive_message.side_effect = [{"Messages": [p]}, {"Messages": []}]

        class _Ctx:
            def get_remaining_time_in_millis(self):
                return 120000

        mod.lambda_handler({}, _Ctx())

    assert mocks["lambda"].invoke.call_count == 2, "re-invoked past the threshold"
    for call in mocks["lambda"].invoke.call_args_list:
        assert call.kwargs["FunctionName"] == "daily-metrics-compute"

    # One escalation metric per escalated pass, dimensioned by the function.
    emf = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith('{"_aws"')]
    assert len(emf) == 3
    for doc in emf:
        assert doc["FunctionName"] == "daily-metrics-compute"
        assert doc["DlqEscalation"] == 1
        assert doc["Reason"] == "threshold"
        cw = doc["_aws"]["CloudWatchMetrics"][0]
        assert cw["Namespace"] == "LifePlatform/DLQ"
        assert ["FunctionName"] in cw["Dimensions"]
    assert [d["CumulativeAttempts"] for d in emf] == [3, 4, 5]

    # The urgent page names the function, not just a count.
    subjects = [c.kwargs["Subject"] for c in mocks["sns"].publish.call_args_list]
    assert len(subjects) == 3
    assert all("daily-metrics-compute" in s and len(s) <= 100 for s in subjects), subjects
    assert ERROR_TEXT in mocks["sns"].publish.call_args.kwargs["Message"]


# ── Acceptance 3: the 16:40Z rule resolves to daily-metrics-compute ─────────────


def test_the_1640z_rule_payload_resolves_to_daily_metrics_compute(env):
    mod, mocks, _ledger, _table = _import_module()
    assert mod.extract_function_name(MSG_1640) == "daily-metrics-compute"
    escalations: list = []
    stats = _stats()
    mod.process_message(MSG_1640, stats, escalations)
    assert stats["retried_ok"] == 1 and escalations == []
    assert mocks["lambda"].invoke.call_args.kwargs["FunctionName"] == "daily-metrics-compute"


def test_an_unmapped_hand_rule_escalates_named_by_its_rule_not_unknown(env):
    """Email rules stay deliberately unresolved (never silently re-send), but the
    escalation names where the failure came from."""
    mod, mocks, _ledger, _table = _import_module()
    msg = _dlq_msg("m-brief", _event_body("daily-brief-schedule", "evt-b", "2026-10-09T17:00:00Z"))
    escalations: list = []
    mod.process_message(msg, _stats(), escalations)
    mocks["lambda"].invoke.assert_not_called()
    assert escalations[0]["function_name"] == "rule/daily-brief-schedule"
    assert escalations[0]["classification"] == "unretryable"


def test_non_cdk_rule_targets_are_real_functions(env):
    """Every pinned rule target is a function this repo deploys — a renamed or
    retired function fails here, not as a silent 404 re-invoke."""
    mod, _mocks, _ledger, _table = _import_module()
    with open(os.path.join(ROOT, "ci", "lambda_map.json")) as fh:
        lmap = json.load(fh)
    deployed = {v.get("function") for v in lmap["lambdas"].values() if isinstance(v, dict)}
    missing = {r: f for r, f in mod.NON_CDK_RULE_TARGETS.items() if f not in deployed}
    assert not missing, f"NON_CDK_RULE_TARGETS names functions absent from ci/lambda_map.json: {missing}"
    assert mod.NON_CDK_RULE_TARGETS[RULE_1640] == "daily-metrics-compute"
