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

#2051 moved WHERE that failure is reported, not WHETHER: the postcondition now
returns in `check_subscribe_flow`'s `extras` (the stored-state lane) instead of
flipping the flow's own verdict, because a row written twelve days ago is not
evidence about the deploy in flight — it reverted a correct one on 2026-08-02.
The assertions below follow it into the new lane; the lane's routing is guarded
separately in tests/test_canary_lane_split.py.
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
    ok, msg, _ms, extras = canary.check_subscribe_flow("2026-08-03T12:00:00Z")
    return ok, msg, extras, emitted


def test_subscribe_flow_fails_loudly_when_a_synthetic_row_survives(monkeypatch):
    ddb = _FakeDDBClient(query_pages=[{"Count": 1}], get_item_response=_PENDING_ITEM)
    ok, _msg, extras, emitted = _run_subscribe_flow(monkeypatch, ddb)
    residue = extras["subscribe_residue"]
    assert residue["ok"] is False
    assert "1 synthetic" in residue["message"] and "surviv" in residue["message"]
    assert residue["residue_rows"] == 1
    assert ("CanarySubscribeResidueRows", 1) in [(e[0], e[1]) for e in emitted]
    # #2051: the LIVE round-trip is unaffected — the subscribe API accepted the
    # subscriber and the row appeared, which is the only part of this probe that
    # is evidence about the code that just shipped.
    assert ok is True


def test_subscribe_flow_passes_when_partition_is_clean(monkeypatch):
    ddb = _FakeDDBClient(query_pages=[{"Count": 0}], get_item_response=_PENDING_ITEM)
    ok, _msg, extras, emitted = _run_subscribe_flow(monkeypatch, ddb)
    assert ok is True
    assert extras["subscribe_residue"]["ok"] is True
    assert extras["subscribe_cleanup"]["ok"] is True
    assert ("CanarySubscribeResidueRows", 0) in [(e[0], e[1]) for e in emitted]


def test_subscribe_flow_fails_when_residue_count_unreadable(monkeypatch):
    """If the postcondition cannot be verified, the check fails honestly —
    an unverifiable assertion must never report green (ADR-104 posture).
    It fails in the stored-state lane: what it asserts is about stored data,
    so it alarms and emails rather than reverting a deploy."""

    class _QueryBroken(_FakeDDBClient):
        def query(self, **kwargs):
            raise RuntimeError("AccessDenied: no Query")

    ddb = _QueryBroken(query_pages=[], get_item_response=_PENDING_ITEM)
    _ok, _msg, extras, _emitted = _run_subscribe_flow(monkeypatch, ddb)
    residue = extras["subscribe_residue"]
    assert residue["ok"] is False
    assert "residue" in residue["message"].lower()
    assert residue["residue_rows"] is None


def test_subscribe_flow_cleanup_failure_is_caught_by_the_postcondition(monkeypatch):
    """The old silent-`pass` hole: delete blows up. #2051 gives it a verdict of
    its own (the CAUSE) on top of the residue counter (the AFTERMATH) — the
    stray row sat for 12 days precisely because only the aftermath was watched."""
    ddb = _FakeDDBClient(query_pages=[{"Count": 1}], get_item_response=_PENDING_ITEM, fail_delete=True)
    _ok, _msg, extras, _emitted = _run_subscribe_flow(monkeypatch, ddb)
    assert extras["subscribe_cleanup"]["ok"] is False
    assert "cleanup delete failed" in extras["subscribe_cleanup"]["message"]
    assert extras["subscribe_residue"]["ok"] is False
    assert "surviv" in extras["subscribe_residue"]["message"]
