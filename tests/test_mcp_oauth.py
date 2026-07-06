"""tests/test_mcp_oauth.py — remote MCP auth flow (SEC-01 / #779).

Regression guard for the unauthenticated /token breach: /token must NOT mint the
bearer for an unbound request. A bearer may only be exchanged for a code that
/authorize actually issued, single-use, with a verified PKCE code_verifier and a
matching (allowlisted) redirect_uri.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from unittest.mock import patch

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from mcp import (
    core,  # noqa: E402
    handler as h,  # noqa: E402
)


class _ConditionalCheckFailed(Exception):
    """Stand-in for botocore's ConditionalCheckFailedException."""


class _FakeTable:
    """Minimal DDB stand-in supporting put_item + the conditional single-use
    update_item(SET consumed, ConditionExpression exists-and-unconsumed)."""

    def __init__(self):
        self.store = {}

    def put_item(self, Item):
        self.store[(Item["pk"], Item["sk"])] = dict(Item)

    def update_item(self, Key, UpdateExpression=None, ConditionExpression=None, ExpressionAttributeValues=None, ReturnValues=None):
        item = self.store.get((Key["pk"], Key["sk"]))
        # Emulate: attribute_exists(sk) AND attribute_not_exists(consumed)
        if item is None or "consumed" in item:
            raise _ConditionalCheckFailed("ConditionalCheckFailedException")
        item["consumed"] = True
        return {"Attributes": dict(item)} if ReturnValues == "ALL_NEW" else {}


def setup_function(_fn):
    core.table = _FakeTable()  # fresh store per test
    h._BEARER_TOKEN_CACHE.clear()


# ── helpers ──────────────────────────────────────────────────────────────────
def _pkce_pair():
    verifier = "a" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _authorize(redirect_uri, challenge, method="S256"):
    event = {
        "queryStringParameters": {
            "redirect_uri": redirect_uri,
            "state": "xyz",
            "code_challenge": challenge,
            "code_challenge_method": method,
        }
    }
    return h._handle_authorize(event)


def _code_from(resp):
    loc = resp["headers"]["Location"]
    return loc.split("code=")[1].split("&")[0]


def _token(body):
    return h._handle_token({"body": json.dumps(body)})


# ── the breach: an unbound POST must NOT yield a bearer ───────────────────────
def test_token_rejects_unbound_request():
    with patch("mcp.handler.get_api_key", return_value="secret"):
        resp = _token({})  # empty body — the original exploit
        assert resp["statusCode"] == 400
        assert "access_token" not in json.loads(resp["body"])


def test_token_rejects_forged_code():
    with patch("mcp.handler.get_api_key", return_value="secret"):
        resp = _token({"grant_type": "authorization_code", "code": "deadbeef", "code_verifier": "x"})
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"])["error"] == "invalid_grant"


# ── the happy path a real Claude client walks ─────────────────────────────────
def test_full_pkce_flow_issues_bearer():
    verifier, challenge = _pkce_pair()
    redirect = "https://claude.ai/api/mcp/auth_callback"
    with patch("mcp.handler.get_api_key", return_value="secret"):
        code = _code_from(_authorize(redirect, challenge))
        resp = _token({"grant_type": "authorization_code", "code": code, "code_verifier": verifier, "redirect_uri": redirect})
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["access_token"] == h._get_bearer_token()
        assert body["token_type"] == "Bearer"


def test_code_is_single_use():
    verifier, challenge = _pkce_pair()
    redirect = "https://claude.ai/cb"
    with patch("mcp.handler.get_api_key", return_value="secret"):
        code = _code_from(_authorize(redirect, challenge))
        exchange = {"grant_type": "authorization_code", "code": code, "code_verifier": verifier, "redirect_uri": redirect}
        assert _token(exchange)["statusCode"] == 200
        assert _token(exchange)["statusCode"] == 400  # replay rejected


def test_wrong_pkce_verifier_rejected():
    _, challenge = _pkce_pair()
    redirect = "https://claude.ai/cb"
    with patch("mcp.handler.get_api_key", return_value="secret"):
        code = _code_from(_authorize(redirect, challenge))
        resp = _token({"grant_type": "authorization_code", "code": code, "code_verifier": "wrong-verifier", "redirect_uri": redirect})
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"])["error"] == "invalid_grant"


def test_redirect_uri_mismatch_rejected():
    verifier, challenge = _pkce_pair()
    with patch("mcp.handler.get_api_key", return_value="secret"):
        code = _code_from(_authorize("https://claude.ai/cb", challenge))
        resp = _token(
            {"grant_type": "authorization_code", "code": code, "code_verifier": verifier, "redirect_uri": "https://claude.ai/other"}
        )
        assert resp["statusCode"] == 400


def test_unsupported_grant_type_rejected():
    with patch("mcp.handler.get_api_key", return_value="secret"):
        assert _token({"grant_type": "client_credentials"})["statusCode"] == 400


# ── /authorize open-redirect hardening ────────────────────────────────────────
def test_authorize_rejects_untrusted_redirect_host():
    _, challenge = _pkce_pair()
    resp = _authorize("https://evil.example.com/steal", challenge)
    assert resp["statusCode"] == 400


def test_authorize_rejects_http_scheme():
    _, challenge = _pkce_pair()
    resp = _authorize("http://claude.ai/cb", challenge)  # non-loopback must be https
    assert resp["statusCode"] == 400


def test_authorize_allows_loopback_http():
    _, challenge = _pkce_pair()
    resp = _authorize("http://127.0.0.1:8976/callback", challenge)
    assert resp["statusCode"] == 302


def test_authorize_allows_claude_subdomain():
    _, challenge = _pkce_pair()
    resp = _authorize("https://foo.claude.com/cb", challenge)
    assert resp["statusCode"] == 302


def test_redirect_host_suffix_trick_rejected():
    _, challenge = _pkce_pair()
    resp = _authorize("https://claude.ai.evil.com/cb", challenge)
    assert resp["statusCode"] == 400
