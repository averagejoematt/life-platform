"""tests/test_reader_engagement.py — the reader engagement loop write surface.

Covers /api/predict_week (reader predicts which way the week's metric moves) and
/api/board_question (reader question captured for the AI board). Both reuse the
sanctioned write plumbing; these tests lock the validation + abuse-resistance:
  * predict_week: fail-closed when no active subject; week/metric/choice validated
    against the live challenge; 1-per-IP-per-week-per-metric dedup; IP hashed.
  * board_question: rate-limited; HTML-stripped + length-capped; vice-filtered;
    written pending to S3; email never echoed; IP hashed.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from fakes import FakeDdbTable  # noqa: E402
from web import site_api_social as social  # noqa: E402


def _event(body=None, qs=None):
    return {
        "body": json.dumps(body) if body is not None else None,
        "queryStringParameters": qs,
        "headers": {"x-forwarded-for": "203.0.113.7"},
        "requestContext": {"http": {"sourceIp": "203.0.113.7", "method": "POST"}},
    }


def _FakeTable():
    """DynamoDB Table double: put_item honors attribute_not_exists, update_item ADDs,
    query returns every VOTES#predict_week row (the handler filters by choice)."""

    def _put_hook(table, item, ConditionExpression=None, **_kw):
        key = table._key_of(item)
        if ConditionExpression and "attribute_not_exists" in str(ConditionExpression) and key in table.store:
            raise Exception("ConditionalCheckFailedException: exists")
        table.store[key] = dict(item)

    def _update_hook(table, Key=None, ExpressionAttributeValues=None, **_kw):
        key = table._key_of(Key)
        it = table.store.setdefault(key, {"pk": Key["pk"], "sk": Key["sk"], "vote_count": 0})
        it["vote_count"] = int(it.get("vote_count", 0)) + int(ExpressionAttributeValues.get(":one", 1))
        for token, field in ((":w", "week_id"), (":m", "metric"), (":c", "choice")):
            if token in ExpressionAttributeValues:
                it[field] = ExpressionAttributeValues[token]
        return {"Attributes": it}

    def _query_hook(table, **_kw):
        return {"Items": [v for (pk, sk), v in table.store.items() if pk == "VOTES#predict_week"]}

    return FakeDdbTable(put_item_hook=_put_hook, update_item_hook=_update_hook, query_hook=_query_hook)


_SUBJECT = {"week_id": "2026-W26", "metrics": {"weight": "scale weight", "recovery": "avg recovery"}, "result": None}


# ── predict_week ────────────────────────────────────────────────────────────


def test_predict_week_fails_closed_without_subject(monkeypatch):
    monkeypatch.setattr(social, "_predict_subject", lambda: None)
    r = social._handle_predict_week(_event({"week_id": "x", "metric": "weight", "choice": "down"}))
    assert r["statusCode"] == 404


def test_predict_week_happy_path_increments_and_dedupes(monkeypatch):
    monkeypatch.setattr(social, "_predict_subject", lambda: _SUBJECT)
    monkeypatch.setattr(social, "table", _FakeTable())
    ev = _event({"week_id": "2026-W26", "metric": "weight", "choice": "down"})
    r = social._handle_predict_week(ev)
    assert r["statusCode"] == 200
    body = json.loads(r["body"])
    assert body["tallies"]["down"] == 1
    # the dedup row keys on a hashed IP, never the raw address
    rate_rows = [sk for (pk, sk) in social.table.store if pk == "VOTES#rate_limit"]
    assert rate_rows and "203.0.113.7" not in rate_rows[0]
    # a second identical prediction is rejected
    assert social._handle_predict_week(ev)["statusCode"] == 429


def test_predict_week_rejects_bad_inputs(monkeypatch):
    monkeypatch.setattr(social, "_predict_subject", lambda: _SUBJECT)
    monkeypatch.setattr(social, "table", _FakeTable())
    assert social._handle_predict_week(_event({"week_id": "OLD", "metric": "weight", "choice": "down"}))["statusCode"] == 409
    assert social._handle_predict_week(_event({"week_id": "2026-W26", "metric": "blood", "choice": "down"}))["statusCode"] == 404
    assert social._handle_predict_week(_event({"week_id": "2026-W26", "metric": "weight", "choice": "sideways"}))["statusCode"] == 400


def test_predict_week_tally_inactive(monkeypatch):
    monkeypatch.setattr(social, "_predict_subject", lambda: None)
    r = social.handle_predict_week_tally(_event(qs={}))
    assert json.loads(r["body"])["active"] is False


# ── board_question ──────────────────────────────────────────────────────────


class _FakeS3:
    def __init__(self):
        self.puts = []

    def put_object(self, Bucket=None, Key=None, Body=None, **_kw):
        self.puts.append({"Key": Key, "Body": Body})


def _patch_board(monkeypatch, blocked=False, allowed=True):
    monkeypatch.setattr(social, "_RATE_LIMITER_READY", True)
    monkeypatch.setattr(social, "_ddb_rate_check", lambda *a, **k: (allowed, 2, 0))
    monkeypatch.setattr(social, "_is_blocked_vice", lambda s: blocked)
    fake = _FakeS3()
    monkeypatch.setattr(social.boto3, "client", lambda *a, **k: fake)
    return fake


def test_board_question_happy_path(monkeypatch):
    fake = _patch_board(monkeypatch)
    r = social._handle_board_question(_event({"question": "Is my sleep actually improving over the month?", "email": "a@b.com"}))
    assert r["statusCode"] == 200
    assert fake.puts and fake.puts[0]["Key"].startswith("generated/board_questions/")
    stored = json.loads(fake.puts[0]["Body"])
    assert stored["status"] == "pending"
    assert "203.0.113.7" not in stored["ip_hash"]  # IP hashed
    assert "a@b.com" not in r["body"]  # email never echoed back


def test_board_question_rejects_short_and_vice_and_ratelimit(monkeypatch):
    _patch_board(monkeypatch)
    assert social._handle_board_question(_event({"question": "too short"}))["statusCode"] == 400
    _patch_board(monkeypatch, blocked=True)
    assert social._handle_board_question(_event({"question": "a perfectly long but blocked question here"}))["statusCode"] == 400
    _patch_board(monkeypatch, allowed=False)
    assert social._handle_board_question(_event({"question": "a perfectly long allowed question here please"}))["statusCode"] == 429
