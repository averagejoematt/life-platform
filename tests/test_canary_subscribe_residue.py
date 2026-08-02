"""#1954 — the subscribe canary must assert its synthetic row count in DDB is 0
after each run.

Background: the canary POSTs a synthetic subscriber (source='canary') to
/api/subscribe every 4h and deletes its own row afterwards. On 2026-07-21 that
cleanup failed silently (`except Exception: pass`) and the stray row sat in the
REAL subscriber partition for 12 days, invisible to every count. These tests pin
the new postcondition: after cleanup the canary counts source='canary' rows in
USER#matthew#SOURCE#subscribers (read-only, bounded pagination) and FAILS the
check loudly if any survive.

All offline — fake clients are plain classes with scripted dict responses,
never MagicMock (a MagicMock feeding a pagination loop returns truthy
LastEvaluatedKeys forever → OOM; the loop is also bounded for the same reason).
"""

import os
import sys
import urllib.request

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("EMAIL_SENDER", "test@example.com")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "operational"))

import canary_lambda as canary  # noqa: E402


class _FakeDDBClient:
    """Scripted DynamoDB client — plain dicts, no MagicMock."""

    def __init__(self, query_pages, get_item_response=None, fail_delete=False):
        self._pages = list(query_pages)
        self._get_item_response = get_item_response or {}
        self._fail_delete = fail_delete
        self.query_calls = []
        self.deleted_keys = []

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        if self._pages:
            return self._pages.pop(0)
        return {"Count": 0}

    def get_item(self, **kwargs):
        return self._get_item_response

    def delete_item(self, **kwargs):
        if self._fail_delete:
            raise RuntimeError("cleanup blew up")
        self.deleted_keys.append(kwargs["Key"])
        return {}


# ── count_canary_subscriber_rows ──────────────────────────────────────────────


def test_count_sums_across_pages_and_carries_start_key():
    ddb = _FakeDDBClient(
        query_pages=[
            {"Count": 1, "LastEvaluatedKey": {"pk": {"S": "x"}, "sk": {"S": "y"}}},
            {"Count": 2},
        ]
    )
    assert canary.count_canary_subscriber_rows(ddb) == 3
    assert len(ddb.query_calls) == 2
    assert ddb.query_calls[1]["ExclusiveStartKey"] == {"pk": {"S": "x"}, "sk": {"S": "y"}}


def test_count_query_is_scoped_read_only_count_on_the_subscriber_partition():
    ddb = _FakeDDBClient(query_pages=[{"Count": 0}])
    canary.count_canary_subscriber_rows(ddb)
    call = ddb.query_calls[0]
    assert call["Select"] == "COUNT"
    assert call["ExpressionAttributeValues"][":pk"] == {"S": "USER#matthew#SOURCE#subscribers"}
    assert call["ExpressionAttributeValues"][":canary"] == {"S": "canary"}
    # `source` is a DynamoDB reserved word — must go through an attribute name
    assert call["ExpressionAttributeNames"] == {"#src": "source"}


def test_count_pagination_is_bounded_never_spins_forever():
    """A pathological (or mocked) client that always returns a LastEvaluatedKey
    must terminate at the page bound instead of looping/OOMing."""

    class _Endless:
        def __init__(self):
            self.calls = 0

        def query(self, **kwargs):
            self.calls += 1
            return {"Count": 1, "LastEvaluatedKey": {"pk": {"S": "x"}, "sk": {"S": str(self.calls)}}}

    endless = _Endless()
    count = canary.count_canary_subscriber_rows(endless)
    assert endless.calls == canary.CANARY_COUNT_MAX_PAGES
    assert count == canary.CANARY_COUNT_MAX_PAGES


# ── check_subscribe_flow postcondition ────────────────────────────────────────


class _FakeHTTPResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b"{}"


_PENDING_ITEM = {"Item": {"status": {"S": "pending_confirmation"}}}


def _run_subscribe_flow(monkeypatch, ddb):
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=10: _FakeHTTPResponse())

    class _FakeBoto3:
        def client(self, name, region_name=None):
            assert name == "dynamodb"
            return ddb

    monkeypatch.setattr(canary, "boto3", _FakeBoto3())
    emitted = []
    monkeypatch.setattr(canary, "emit", lambda *a, **k: emitted.append(a))
    ok, msg, _ms = canary.check_subscribe_flow("2026-08-03T12:00:00Z")
    return ok, msg, emitted


def test_subscribe_flow_fails_loudly_when_a_synthetic_row_survives(monkeypatch):
    ddb = _FakeDDBClient(query_pages=[{"Count": 1}], get_item_response=_PENDING_ITEM)
    ok, msg, emitted = _run_subscribe_flow(monkeypatch, ddb)
    assert ok is False
    assert "1 synthetic" in msg and "surviv" in msg
    assert ("CanarySubscribeResidueRows", 1) in [(e[0], e[1]) for e in emitted]


def test_subscribe_flow_passes_when_partition_is_clean(monkeypatch):
    ddb = _FakeDDBClient(query_pages=[{"Count": 0}], get_item_response=_PENDING_ITEM)
    ok, msg, emitted = _run_subscribe_flow(monkeypatch, ddb)
    assert ok is True
    assert ("CanarySubscribeResidueRows", 0) in [(e[0], e[1]) for e in emitted]


def test_subscribe_flow_fails_when_residue_count_unreadable(monkeypatch):
    """If the postcondition cannot be verified, the check fails honestly —
    an unverifiable assertion must never report green (ADR-104 posture)."""

    class _QueryBroken(_FakeDDBClient):
        def query(self, **kwargs):
            raise RuntimeError("AccessDenied: no Query")

    ddb = _QueryBroken(query_pages=[], get_item_response=_PENDING_ITEM)
    ok, msg, _emitted = _run_subscribe_flow(monkeypatch, ddb)
    assert ok is False
    assert "residue" in msg.lower()


def test_subscribe_flow_cleanup_failure_is_caught_by_the_postcondition(monkeypatch):
    """The old silent-`pass` hole: delete blows up, but the residue count now
    sees the survivor and the check fails instead of returning green."""
    ddb = _FakeDDBClient(query_pages=[{"Count": 1}], get_item_response=_PENDING_ITEM, fail_delete=True)
    ok, msg, _emitted = _run_subscribe_flow(monkeypatch, ddb)
    assert ok is False
    assert "surviv" in msg
