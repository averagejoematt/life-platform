"""Tests for setup/setup_whoop_auth.py — the Whoop OAuth re-auth bootstrap (#935).

The interactive browser leg (callback server + real Whoop consent) can't run
headlessly; these tests cover the pure/mockable core the flow is built on:
code extraction, the authorize URL, the token exchange payload, and the
preserve-in-place secret write that whoop_lambda's refresh path depends on.
"""

import importlib.util
import json
import urllib.parse
from pathlib import Path
from unittest import mock

import pytest

_MOD_PATH = Path(__file__).resolve().parents[1] / "setup" / "setup_whoop_auth.py"


def _load():
    spec = importlib.util.spec_from_file_location("setup_whoop_auth", _MOD_PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def wa():
    return _load()


# ── extract_code ──────────────────────────────────────────────────────────────


def test_extract_code_from_full_redirect_url(wa):
    url = "http://localhost:3000/callback?code=abc123XYZ&state=lifeplatform-reauth"
    assert wa.extract_code(url) == "abc123XYZ"


def test_extract_code_accepts_bare_code(wa):
    assert wa.extract_code("  abc123XYZ \n") == "abc123XYZ"


def test_extract_code_empty_when_code_param_blank(wa):
    assert wa.extract_code("http://localhost:3000/callback?state=x&code=") == ""


# ── build_authorize_url ───────────────────────────────────────────────────────


def test_authorize_url_carries_registered_redirect_and_offline_scope(wa):
    url = wa.build_authorize_url("client-id-1", wa.DEFAULT_REDIRECT)
    assert url.startswith("https://api.prod.whoop.com/oauth/oauth2/auth?")
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert qs["response_type"] == ["code"]
    assert qs["client_id"] == ["client-id-1"]
    assert qs["redirect_uri"] == ["http://localhost:3000/callback"]
    # `offline` is load-bearing: without it Whoop returns no refresh_token.
    assert "offline" in qs["scope"][0].split()
    assert qs["scope"][0] == wa.SCOPES


# ── exchange_code ─────────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_exchange_code_posts_authorization_code_grant(wa, monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["method"] = req.get_method()
        seen["fields"] = urllib.parse.parse_qs(req.data.decode())
        return _FakeResponse({"access_token": "at-new", "refresh_token": "rt-new"})

    monkeypatch.setattr(wa.urllib.request, "urlopen", fake_urlopen)
    tok = wa.exchange_code("cid", "csec", "the-code", wa.DEFAULT_REDIRECT)

    assert tok == {"access_token": "at-new", "refresh_token": "rt-new"}
    assert seen["url"] == "https://api.prod.whoop.com/oauth/oauth2/token"
    assert seen["method"] == "POST"
    assert seen["fields"]["grant_type"] == ["authorization_code"]
    assert seen["fields"]["code"] == ["the-code"]
    assert seen["fields"]["client_id"] == ["cid"]
    assert seen["fields"]["client_secret"] == ["csec"]
    assert seen["fields"]["redirect_uri"] == ["http://localhost:3000/callback"]
    assert seen["fields"]["scope"] == [wa.SCOPES]


# ── save_tokens ───────────────────────────────────────────────────────────────


def test_save_tokens_updates_in_place_preserving_all_other_fields(wa, monkeypatch):
    sm = mock.MagicMock()
    monkeypatch.setattr(wa.boto3, "client", mock.MagicMock(return_value=sm))

    secret = {
        "client_id": "cid",
        "client_secret": "csec",
        "access_token": "at-old",
        "refresh_token": "rt-old",
        "some_extra_field": "kept",
    }
    updated = wa.save_tokens(secret, {"access_token": "at-new", "refresh_token": "rt-new", "expires_in": 3600})

    # In-place update: tokens replaced, everything else preserved, no new keys leak in.
    assert updated["access_token"] == "at-new"
    assert updated["refresh_token"] == "rt-new"
    assert updated["client_id"] == "cid"
    assert updated["client_secret"] == "csec"
    assert updated["some_extra_field"] == "kept"
    assert "expires_in" not in updated

    (kwargs,) = [c.kwargs for c in sm.update_secret.call_args_list]
    assert kwargs["SecretId"] == "life-platform/whoop"
    assert json.loads(kwargs["SecretString"]) == updated
    # The caller's dict is not mutated (it's re-read on failure paths).
    assert secret["access_token"] == "at-old"


def test_save_tokens_raises_if_no_refresh_token(wa, monkeypatch):
    monkeypatch.setattr(wa.boto3, "client", mock.MagicMock())
    with pytest.raises(KeyError):
        wa.save_tokens({"client_id": "cid"}, {"access_token": "at-only"})


# ── callback handler ──────────────────────────────────────────────────────────


def test_callback_handler_captures_code(wa):
    handler = object.__new__(wa.CallbackHandler)  # skip BaseHTTPRequestHandler's socket __init__
    handler.path = "/callback?code=cb-code-1&state=lifeplatform-reauth"
    handler.send_response = mock.MagicMock()
    handler.send_header = mock.MagicMock()
    handler.end_headers = mock.MagicMock()
    handler.wfile = mock.MagicMock()

    wa.captured_code = None
    handler.do_GET()
    assert wa.captured_code == "cb-code-1"
    handler.send_response.assert_called_once_with(200)


def test_callback_handler_400_without_code(wa):
    handler = object.__new__(wa.CallbackHandler)
    handler.path = "/callback?error=access_denied"
    handler.send_response = mock.MagicMock()
    handler.send_header = mock.MagicMock()
    handler.end_headers = mock.MagicMock()
    handler.wfile = mock.MagicMock()

    wa.captured_code = None
    handler.do_GET()
    assert wa.captured_code is None
    handler.send_response.assert_called_once_with(400)
