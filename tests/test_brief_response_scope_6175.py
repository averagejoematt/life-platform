"""tests/test_brief_response_scope_6175.py — the owner's scope conditions for /api/brief_response (#6175, 2026-11-22).

NEGATIVE tests: no caller — valid token, invalid token, crafted body — can make the handler write anywhere
but the ``brief_trial`` partition (plus the shared limiter's own ``RATE#`` counter rows). Never the
recommendation record (``coach_recommendations``), a coach partition or an experiment partition. A GET and a
HEAD record nothing and leave the token unspent; expired / reused / malformed tokens record nothing.

The REAL shared rate limiter runs against a recording fake table (no AWS), so its writes are inside the proof.
"""

from __future__ import annotations

import time
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from coach import brief_recommendations as rr

PK = "USER#matthew#SOURCE#brief_trial"
DAY = "2026-11-20"
FORBIDDEN_PREFIXES = (
    "USER#matthew#SOURCE#coach_recommendations",
    "USER#matthew#SOURCE#coach",
    "USER#matthew#SOURCE#experiment",
    "USER#matthew#SOURCE#journal",
)


class _CCF(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class _Log:
    def warning(self, *a, **k):
        pass

    info = error = warning


class RecordingTable:
    """Records the (op, pk, sk) of EVERY call; any put/delete is a recorded write, then refused."""

    def __init__(self):
        self.store, self.ops = {}, []

    def get_item(self, Key=None, **_):
        self.ops.append(("get", Key["pk"], Key["sk"]))
        it = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(it)} if it else {}

    def put_item(self, **kw):
        self.ops.append(("put", (kw.get("Item") or {}).get("pk"), (kw.get("Item") or {}).get("sk")))
        raise AssertionError("the door must never put_item")

    def delete_item(self, **kw):
        self.ops.append(("delete", (kw.get("Key") or {}).get("pk"), (kw.get("Key") or {}).get("sk")))
        raise AssertionError("the door must never delete_item")

    def update_item(self, Key=None, ConditionExpression="", ExpressionAttributeValues=None, **kw):
        self.ops.append(("update", Key["pk"], Key["sk"]))
        v = ExpressionAttributeValues or {}
        k = (Key["pk"], Key["sk"])
        if Key["pk"].startswith("RATE#"):  # the shared limiter's counter
            it = self.store.setdefault(k, {"count": 0})
            it["count"] += v.get(":inc", 1)
            return {"Attributes": {"count": it["count"]}}
        it = self.store.get(k)
        if it is None:
            raise _CCF("ConditionalCheckFailedException")
        if Key["sk"].startswith("TOKEN#"):
            if it.get("used_at") or int(it["expires_at"]) <= v[":now"]:
                raise _CCF("ConditionalCheckFailedException")
            it.update(used_at=v[":u"], response=v[":r"], response_status=v[":s"])
        else:
            it.update(response=v[":s"], response_word=v[":r"], response_at=v[":u"], response_rec_id=v[":id"])
        return {"Attributes": dict(it)}

    def writes(self):
        return [o for o in self.ops if o[0] != "get"]

    def trial_writes(self):
        return [o for o in self.writes() if o[1] == PK]


@pytest.fixture
def door(monkeypatch):
    from web import site_api_brief_response as sb

    t = RecordingTable()
    monkeypatch.setattr(sb, "_deps", lambda: (t, _Log()))
    monkeypatch.setattr(sb, "salted_ip_hash", lambda ip, logger=None: "iphash")  # the limiter itself stays real
    tok = rr.new_token()
    t.store[(PK, "TOKEN#" + rr.token_hash(tok))] = {
        "pk": PK,
        "sk": "TOKEN#" + rr.token_hash(tok),
        "rec_id": "2026-11-20#movement",
        "send_day": DAY,
        "expires_at": Decimal(int(time.time()) + 3600),
    }
    t.store[(PK, "SEND#" + DAY)] = {"pk": PK, "sk": "SEND#" + DAY, "response": "not_recorded"}
    return sb, t, tok


def _ev(method, tok=None, response=None, extra=""):
    h = {"cloudfront-viewer-address": "203.0.113.7:1"}
    if method == "POST":
        body = urlencode({"t": tok or "", "response": response or ""}) + extra
        return {"body": body, "headers": h, "requestContext": {"http": {"method": "POST"}}}
    return {"queryStringParameters": {"t": tok or ""}, "headers": h, "requestContext": {"http": {"method": method}}}


def _only_allowed_targets(t):
    for op, pk, _sk in t.writes():
        assert op == "update", f"the door issued a {op}"
        assert pk == PK or str(pk).startswith("RATE#brief_response#"), f"write outside the trial partition: {pk}"
        assert not str(pk).startswith(FORBIDDEN_PREFIXES)


def test_valid_token_writes_only_the_trial_partition_and_its_own_rate_counter(door):
    sb, t, tok = door
    assert sb.handle_brief_response(_ev("POST", tok, "done"))["statusCode"] == 200
    _only_allowed_targets(t)
    assert {o[1] for o in t.trial_writes()} == {PK}
    assert {o[2] for o in t.trial_writes()} == {"TOKEN#" + rr.token_hash(tok), "SEND#" + DAY}


def test_invalid_token_writes_nothing_but_the_limiter_counter(door):
    sb, t, _tok = door
    for bad in (rr.new_token(), "", "short", "../" + rr.new_token()[3:], "a" * 500):
        assert sb.handle_brief_response(_ev("POST", bad, "done"))["statusCode"] == 404
    _only_allowed_targets(t)
    assert t.trial_writes() == []  # not one write to the trial partition
    assert t.store[(PK, "SEND#" + DAY)]["response"] == "not_recorded"


@pytest.mark.parametrize(
    "extra",
    [
        "&pk=USER%23matthew%23SOURCE%23coach_recommendations",
        "&sk=HEAD%23rec_1&rec_id=2026-11-01%23food_log",
        "&pk=USER%23matthew%23SOURCE%23experiment&response_status=accepted",
        "&t=" + "b" * 43,  # a second token field must not retarget the first
        "&UpdateExpression=REMOVE%20x&ConditionExpression=attribute_exists(sk)",
    ],
)
def test_a_crafted_body_cannot_retarget_a_write(door, extra):
    sb, t, tok = door
    sb.handle_brief_response(_ev("POST", tok, "done", extra=extra))
    sb.handle_brief_response(_ev("POST", rr.new_token(), "done", extra=extra))  # and with an unminted token
    _only_allowed_targets(t)
    assert all(o[1] in (PK,) or o[1].startswith("RATE#") for o in t.writes())
    assert t.store[(PK, "SEND#" + DAY)].get("response_rec_id", "2026-11-20#movement") == "2026-11-20#movement"
    assert set(k[0] for k in t.store if not k[0].startswith("RATE#")) == {PK}  # no other partition was created


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_a_get_or_head_with_a_valid_token_records_nothing_and_leaves_the_token_unspent(door, method):
    sb, t, tok = door
    for _ in range(3):
        assert sb.handle_brief_response(_ev(method, tok))["statusCode"] == 200
    assert t.trial_writes() == []
    _only_allowed_targets(t)
    assert not t.store[(PK, "TOKEN#" + rr.token_hash(tok))].get("used_at")
    assert t.store[(PK, "SEND#" + DAY)]["response"] == "not_recorded"
    assert sb.handle_brief_response(_ev("POST", tok, "done"))["statusCode"] == 200  # still spendable afterwards


def test_expired_reused_and_malformed_tokens_record_nothing(door):
    sb, t, tok = door
    key = (PK, "TOKEN#" + rr.token_hash(tok))
    t.store[key]["expires_at"] = Decimal(int(time.time()) - 1)
    assert sb.handle_brief_response(_ev("POST", tok, "done"))["statusCode"] == 410  # expired
    assert t.trial_writes() == [] and not t.store[key].get("used_at")
    t.store[key]["expires_at"] = Decimal(int(time.time()) + 3600)
    assert sb.handle_brief_response(_ev("POST", tok, "done"))["statusCode"] == 200
    n = len(t.trial_writes())
    assert sb.handle_brief_response(_ev("POST", tok, "not_doing"))["statusCode"] == 410  # same token again
    assert len(t.trial_writes()) == n and t.store[key]["response"] == "done"
    for bad in ("not-a-token", "%00", "x" * 5):
        before = len(t.trial_writes())
        assert sb.handle_brief_response(_ev("POST", bad, "done"))["statusCode"] == 404
        assert len(t.trial_writes()) == before
    _only_allowed_targets(t)


def test_nothing_in_the_trial_path_imports_or_writes_the_canonical_recommendation_record():
    """No code path folds a brief answer into coach_recommendations: neither the door, the seam, the hybrid
    renderer nor the trial recorder references the record module or its partition."""
    from pathlib import Path

    import web.site_api_brief_response as door_mod
    from coach import brief_recommendations as seam
    from content import brief_hybrid as hyb
    from emails import brief_trial as trial

    for mod in (door_mod, seam, hyb, trial):
        src = Path(mod.__file__).read_text()
        assert "recommendation_record" not in src, mod.__name__
        assert "SOURCE#coach_recommendations" not in src, mod.__name__
