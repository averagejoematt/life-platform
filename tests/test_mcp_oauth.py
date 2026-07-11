"""tests/test_mcp_oauth.py — remote MCP auth flow (SEC-01 / #779).

Regression guard for the unauthenticated /token breach: /token must NOT mint the
bearer for an unbound request. A bearer may only be exchanged for a code that
/authorize actually issued, single-use, with a verified PKCE code_verifier and a
matching (allowlisted) redirect_uri.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import urllib.parse
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
    """Minimal DDB stand-in supporting put_item, get_item, and two update_item
    shapes: the conditional single-use auth-code consume (SET consumed) and the
    session-bearer revoke (SET revoked)."""

    def __init__(self):
        self.store = {}

    def put_item(self, Item):
        self.store[(Item["pk"], Item["sk"])] = dict(Item)

    def get_item(self, Key):
        item = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item is not None else {}

    def update_item(
        self,
        Key,
        UpdateExpression=None,
        ConditionExpression=None,
        ExpressionAttributeNames=None,
        ExpressionAttributeValues=None,
        ReturnValues=None,
    ):
        item = self.store.get((Key["pk"], Key["sk"]))
        names = ExpressionAttributeNames or {}
        # Session revoke: attribute_exists(sk) → set revoked=true.
        if "#revoked" in names:
            if item is None:
                raise _ConditionalCheckFailed("ConditionalCheckFailedException")
            item["revoked"] = True
            return {}
        # Auth-code consume: attribute_exists(sk) AND attribute_not_exists(consumed).
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


def _authorize_get(redirect_uri, challenge, method="S256", cookies=None):
    """Raw GET /authorize — returns the consent form (200), a 302 (valid cookie), or 400."""
    event = {
        "queryStringParameters": {
            "redirect_uri": redirect_uri,
            "state": "xyz",
            "code_challenge": challenge,
            "code_challenge_method": method,
        }
    }
    if cookies is not None:
        event["cookies"] = cookies
    return h._handle_authorize(event)


def _passcode():
    """The access code the consent form expects (tests patch get_api_key → 'secret')."""
    return hmac.new(b"secret", h._AUTHORIZE_PASSCODE_DOMAIN, hashlib.sha256).hexdigest()


def _authorize(redirect_uri, challenge, method="S256", passcode=None):
    """Full consent: POST /authorize with the passcode → 302 with a code (happy path)."""
    body = urllib.parse.urlencode(
        {
            "redirect_uri": redirect_uri,
            "state": "xyz",
            "code_challenge": challenge,
            "code_challenge_method": method,
            "passcode": _passcode() if passcode is None else passcode,
        }
    )
    return h._handle_authorize_submit({"body": body})


def _code_from(resp):
    loc = resp["headers"]["Location"]
    return loc.split("code=")[1].split("&")[0]


def _token(body):
    return h._handle_token({"body": json.dumps(body)})


def _validate(token):
    return h._validate_bearer({"headers": {"authorization": f"Bearer {token}"}})


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
def test_full_pkce_flow_issues_session_bearer():
    """#893: /token now mints a short-lived SESSION bearer, NOT the permanent
    key-derived Desktop bearer. Address possession no longer yields a forever token."""
    verifier, challenge = _pkce_pair()
    redirect = "https://claude.ai/api/mcp/auth_callback"
    with patch("mcp.handler.get_api_key", return_value="secret"):
        code = _code_from(_authorize(redirect, challenge))
        resp = _token({"grant_type": "authorization_code", "code": code, "code_verifier": verifier, "redirect_uri": redirect})
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        token = body["access_token"]
        assert body["token_type"] == "Bearer"
        # It is a session token, distinct from the permanent static Desktop bearer…
        assert token.startswith(core.SESSION_TOKEN_PREFIX)
        assert token != h._get_bearer_token()
        # …with the real (finite) lifetime advertised…
        assert body["expires_in"] == core.SESSION_TOKEN_TTL_SECS
        # …and it actually authenticates a request.
        assert _validate(token) is True


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


# ── /authorize open-redirect hardening (validated on the GET entry, before any gate) ──
def test_authorize_rejects_untrusted_redirect_host():
    _, challenge = _pkce_pair()
    assert _authorize_get("https://evil.example.com/steal", challenge)["statusCode"] == 400


def test_authorize_rejects_http_scheme():
    _, challenge = _pkce_pair()
    assert _authorize_get("http://claude.ai/cb", challenge)["statusCode"] == 400  # non-loopback must be https


def test_redirect_host_suffix_trick_rejected():
    _, challenge = _pkce_pair()
    assert _authorize_get("https://claude.ai.evil.com/cb", challenge)["statusCode"] == 400


def test_authorize_allows_loopback_http():
    _, challenge = _pkce_pair()
    with patch("mcp.handler.get_api_key", return_value="secret"):
        resp = _authorize_get("http://127.0.0.1:8976/callback", challenge)  # good → consent form, not 400
        assert resp["statusCode"] == 200 and "passcode" in resp["body"]


def test_authorize_allows_claude_subdomain():
    _, challenge = _pkce_pair()
    with patch("mcp.handler.get_api_key", return_value="secret"):
        resp = _authorize_get("https://foo.claude.com/cb", challenge)
        assert resp["statusCode"] == 200 and "passcode" in resp["body"]


# ── #893-B: /authorize consent gate — URL possession alone cannot mint a code ──
def test_authorize_get_shows_form_and_leaks_no_code():
    with patch("mcp.handler.get_api_key", return_value="secret"):
        resp = _authorize_get("https://claude.ai/cb", _pkce_pair()[1])
        assert resp["statusCode"] == 200
        assert "passcode" in resp["body"] and "code=" not in resp["body"]


def test_authorize_wrong_passcode_rejected_no_code():
    _, challenge = _pkce_pair()
    with patch("mcp.handler.get_api_key", return_value="secret"):
        resp = _authorize("https://claude.ai/cb", challenge, passcode="wrong")
        assert resp["statusCode"] == 401
        assert "Location" not in resp.get("headers", {})


def test_authorize_correct_passcode_issues_code_and_cookie():
    _, challenge = _pkce_pair()
    with patch("mcp.handler.get_api_key", return_value="secret"):
        resp = _authorize("https://claude.ai/cb", challenge)  # correct passcode by default
        assert resp["statusCode"] == 302 and "code=" in resp["headers"]["Location"]
        assert resp.get("cookies") and resp["cookies"][0].startswith("lp_approval=")


def test_valid_approval_cookie_skips_passcode():
    _, challenge = _pkce_pair()
    with patch("mcp.handler.get_api_key", return_value="secret"):
        cookie = h._issue_approval_cookie().split(";")[0]  # "lp_approval=exp.sig"
        resp = _authorize_get("https://claude.ai/cb", challenge, cookies=[cookie])
        assert resp["statusCode"] == 302 and "code=" in resp["headers"]["Location"]


def test_forged_approval_cookie_shows_form():
    _, challenge = _pkce_pair()
    with patch("mcp.handler.get_api_key", return_value="secret"):
        resp = _authorize_get("https://claude.ai/cb", challenge, cookies=["lp_approval=9999999999.deadbeef"])
        assert resp["statusCode"] == 200 and "passcode" in resp["body"]


def test_expired_approval_cookie_shows_form():
    _, challenge = _pkce_pair()
    with patch("mcp.handler.get_api_key", return_value="secret"):
        exp = 1  # correctly signed but long past
        sig = hmac.new(b"secret", f"lp-authorize-cookie-v1:{exp}".encode(), hashlib.sha256).hexdigest()
        resp = _authorize_get("https://claude.ai/cb", challenge, cookies=[f"lp_approval={exp}.{sig}"])
        assert resp["statusCode"] == 200 and "passcode" in resp["body"]


# ── #893: session-bearer hardening — no permanent token from address possession ──
def test_static_desktop_bearer_still_validates():
    """The additive change must not break Claude Desktop, which presents the static
    key-derived bearer directly (no OAuth flow, no DDB lookup)."""
    with patch("mcp.handler.get_api_key", return_value="secret"):
        assert _validate(h._get_bearer_token()) is True


def test_session_token_validates_then_revoke_kills_it():
    with patch("mcp.handler.get_api_key", return_value="secret"):
        token = core.session_token_issue()
        assert token and token.startswith(core.SESSION_TOKEN_PREFIX)
        assert _validate(token) is True
        assert core.session_token_revoke(token) is True
        assert _validate(token) is False  # revocation is immediate, ahead of TTL


def test_expired_session_token_rejected():
    with patch("mcp.handler.get_api_key", return_value="secret"):
        token = core.session_token_issue()
        # Force the stored TTL into the past — DDB TTL deletion lags, so validity is
        # enforced in-process against the stored epoch.
        core.table.store[(core._OAUTH_PK, f"SESSION#{token}")]["ttl"] = 1
        assert _validate(token) is False


def test_unknown_session_token_rejected():
    with patch("mcp.handler.get_api_key", return_value="secret"):
        assert _validate("lps_deadbeefdeadbeef") is False


def test_fail_closed_rejects_session_token_when_no_key():
    """Fail-closed: with no API key configured the whole boundary is off — even a
    token that is otherwise present in the store must be rejected."""
    with patch("mcp.handler.get_api_key", return_value="secret"):
        token = core.session_token_issue()
        assert _validate(token) is True
    h._BEARER_TOKEN_CACHE.clear()
    with patch("mcp.handler.get_api_key", return_value=""):
        assert _validate(token) is False


def test_malformed_authorization_header_rejected():
    with patch("mcp.handler.get_api_key", return_value="secret"):
        assert h._validate_bearer({"headers": {}}) is False
        assert h._validate_bearer({"headers": {"authorization": "Basic xyz"}}) is False
