#!/usr/bin/env python3
"""
tests/test_function_url_origin_header_validation.py — SEC-04 / #815 (R22-SEC-03)

Verifies that site_api_lambda enforces the X-AMJ-Origin header check when
SITE_API_ORIGIN_SECRET is configured. CloudFront injects this header on every
origin request (set as a custom origin header in the distribution config —
wired for both the LambdaApiOrigin and AiLambdaOrigin origins by #815).
Requests that bypass CloudFront and hit the Function URL directly will lack
the header and must be rejected 403.

site_api_ai_lambda.py gained the identical guard in #815 (it previously had
none — it now imports the same SITE_API_ORIGIN_SECRET from site_api_common).
It is checked source-grep style (no import), matching the established
convention for this file in test_ai_endpoint_hardening.py — a full behavioral
harness would need to mock its much larger dependency surface (bedrock,
privacy_guard, source_registry, phase_filter, rate limiter, ...) for no extra
signal over asserting the guard's presence/ordering/comparison method.

email_subscriber_lambda.py gained the identical guard in #885 (CloudFront's
SubscriberLambdaOrigin now injects the same header — web_stack.py, which also
sets the Lambda's SITE_API_ORIGIN_SECRET env var from the same secrets_helpers
read). It is covered behaviorally below — its dependency surface is small
enough to mock (boto3 + env) — including the fail-open contract: env var unset
→ all requests pass, so Lambda code deployed before the CloudFront header /
env var can't break subscriptions.

Run: python3 -m pytest tests/test_function_url_origin_header_validation.py -v

v1.0.0 — 2026-03-21 (SEC-04)
v1.1.0 — 2026-07-08 (#815): site-api-ai source-grep coverage + CDK wiring note.
v1.2.0 — 2026-07-08 (#885): email-subscriber behavioral coverage.
"""

import importlib
import os
import re
import sys
import types
import unittest.mock as mock

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_event(path: str, method: str = "GET", headers: dict | None = None) -> dict:
    return {
        "rawPath": path,
        "requestContext": {"http": {"method": method, "sourceIp": "1.2.3.4"}},
        "headers": headers or {},
        "queryStringParameters": {},
    }


def _fake_aws_modules() -> dict:
    """A boto3 stand-in module dict so no real AWS calls are made at import."""
    fake_boto3 = types.ModuleType("boto3")
    fake_table = mock.MagicMock()
    fake_table.get_item.return_value = {"Item": {}}
    fake_table.query.return_value = {"Items": []}
    fake_resource = mock.MagicMock()
    fake_resource.return_value.Table.return_value = fake_table
    fake_boto3.resource = fake_resource
    fake_boto3.client = mock.MagicMock()
    fake_conditions = types.ModuleType("boto3.dynamodb.conditions")
    fake_conditions.Key = mock.MagicMock()
    return {
        "boto3": fake_boto3,
        "boto3.dynamodb": types.ModuleType("boto3.dynamodb"),
        "boto3.dynamodb.conditions": fake_conditions,
    }


def _load_site_api(origin_secret: str = ""):
    """Import site_api_lambda with all AWS calls patched out."""
    with (
        mock.patch.dict("sys.modules", _fake_aws_modules()),
        mock.patch.dict(
            os.environ,
            {
                "TABLE_NAME": "test-table",
                "USER_ID": "matthew",
                "S3_BUCKET": "test-bucket",
                "SITE_API_ORIGIN_SECRET": origin_secret,
            },
        ),
    ):
        # Drop every cached site_api_* module (flat + web.* namespaced) so they
        # re-execute under the patched env. SITE_API_ORIGIN_SECRET lives in
        # site_api_common and is imported into site_api_lambda — reloading only
        # site_api_lambda would pick up a stale secret from whichever test
        # imported site_api_common first (order-dependent flake). SEC-04 hardening.
        for _name in list(sys.modules):
            if "site_api" in _name:
                del sys.modules[_name]
        mod = importlib.import_module("site_api_lambda")
    return mod


# ── tests ─────────────────────────────────────────────────────────────────────


class TestOriginHeaderValidationDisabled:
    """When SITE_API_ORIGIN_SECRET is empty (default), ALL requests pass through."""

    def setup_method(self):
        self.mod = _load_site_api(origin_secret="")

    def test_request_without_header_allowed_when_secret_unset(self):
        event = _make_event("/api/vitals", headers={})
        resp = self.mod.lambda_handler(event, None)
        assert resp["statusCode"] != 403, "Should allow all requests when SITE_API_ORIGIN_SECRET is not configured"

    def test_request_with_header_allowed_when_secret_unset(self):
        event = _make_event("/api/vitals", headers={"x-amj-origin": "some-value"})
        resp = self.mod.lambda_handler(event, None)
        assert resp["statusCode"] != 403


class TestOriginHeaderValidationEnabled:
    """When SITE_API_ORIGIN_SECRET is set, missing/wrong header returns 403."""

    SECRET = "test-cf-origin-secret-abc123"

    def setup_method(self):
        self.mod = _load_site_api(origin_secret=self.SECRET)

    def test_missing_header_rejected(self):
        event = _make_event("/api/vitals", headers={})
        resp = self.mod.lambda_handler(event, None)
        assert resp["statusCode"] == 403, "Request without X-AMJ-Origin must be rejected 403 when secret is configured"

    def test_wrong_header_value_rejected(self):
        event = _make_event("/api/vitals", headers={"x-amj-origin": "wrong-value"})
        resp = self.mod.lambda_handler(event, None)
        assert resp["statusCode"] == 403, "Request with incorrect X-AMJ-Origin must be rejected 403"

    def test_correct_header_passes(self):
        event = _make_event("/api/vitals", headers={"x-amj-origin": self.SECRET})
        resp = self.mod.lambda_handler(event, None)
        assert resp["statusCode"] != 403, "Request with correct X-AMJ-Origin must not be rejected"

    def test_correct_header_case_insensitive(self):
        """HTTP headers are case-insensitive; both x-amj-origin and X-AMJ-Origin must work."""
        event = _make_event("/api/vitals", headers={"X-AMJ-Origin": self.SECRET})
        resp = self.mod.lambda_handler(event, None)
        assert resp["statusCode"] != 403

    def test_options_preflight_bypasses_check(self):
        """CORS preflight must not be blocked — CloudFront doesn't send origin header on OPTIONS."""
        event = _make_event("/api/vitals", method="OPTIONS", headers={})
        resp = self.mod.lambda_handler(event, None)
        assert resp["statusCode"] == 200

    def test_403_body_is_valid_json(self):
        event = _make_event("/api/vitals", headers={})
        resp = self.mod.lambda_handler(event, None)
        assert resp["statusCode"] == 403
        import json

        body = json.loads(resp["body"])
        assert "error" in body or "message" in body or body  # any non-empty JSON


# ── site-api-ai (#815) — source-grep style, matches test_ai_endpoint_hardening.py ──

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_AI_SRC_PATH = os.path.join(_HERE, "lambdas", "web", "site_api_ai_lambda.py")
with open(_AI_SRC_PATH, encoding="utf-8") as _f:
    _AI_SRC = _f.read()


def _ai_handler_body(name: str) -> str:
    m = re.search(rf"\ndef {re.escape(name)}\(.*?\n(?=\ndef |\Z)", _AI_SRC, re.S)
    assert m, f"handler {name} not found in site_api_ai_lambda.py"
    return m.group(0)


class TestOriginHeaderValidationSiteApiAi:
    """#815: site_api_ai_lambda gained the same SEC-04 guard site_api_lambda had.

    Before #815 it had none at all — CloudFront's AiLambdaOrigin header would
    have been wired for nothing. These pin presence + ordering + the
    constant-time comparison so the guard can't silently regress or get
    reordered behind a routing branch that would leak a partial response.
    """

    def test_imports_shared_secret_constant(self):
        """Must import the SAME SITE_API_ORIGIN_SECRET site_api_common defines —
        not a second os.environ.get, which would risk drifting from site_api_lambda."""
        m = re.search(r"from web\.site_api_common import \((.*?)\)", _AI_SRC, re.S)
        assert m, "expected a from web.site_api_common import (...) block"
        assert "SITE_API_ORIGIN_SECRET" in m.group(1)

    def test_handler_checks_origin_header(self):
        body = _ai_handler_body("lambda_handler")
        assert "SITE_API_ORIGIN_SECRET" in body
        assert "x-amj-origin" in body.lower()
        assert "_hmac.compare_digest" in body, "must use constant-time comparison, not =="

    def test_options_preflight_precedes_origin_check(self):
        """CORS preflight must bypass the guard — CloudFront doesn't send the
        custom origin header on its own OPTIONS passthrough."""
        body = _ai_handler_body("lambda_handler")
        options_at = body.find('method == "OPTIONS"')
        origin_check_at = body.find("SITE_API_ORIGIN_SECRET")
        assert options_at != -1 and origin_check_at != -1
        assert options_at < origin_check_at, "OPTIONS bypass must precede the origin-header check"

    def test_origin_check_precedes_routing(self):
        """The guard must run before any endpoint dispatch (board_ask/ask/explain),
        so a bypassing request never reaches AI inference or DDB rate-limit writes."""
        body = _ai_handler_body("lambda_handler")
        origin_check_at = body.find("SITE_API_ORIGIN_SECRET")
        first_route_at = body.find('path == "/api/board_ask"')
        assert origin_check_at != -1 and first_route_at != -1
        assert origin_check_at < first_route_at, "origin-header check must precede route dispatch"

    def test_rejects_with_403(self):
        body = _ai_handler_body("lambda_handler")
        # the guard's own if-block must return a 403, not merely reference the constant
        m = re.search(r"if SITE_API_ORIGIN_SECRET:.*?return _error\((\d+),", body, re.S)
        assert m, "origin-header guard must return via _error(...)"
        assert m.group(1) == "403"


# ── email-subscriber (#885) — behavioral, like site_api_lambda above ──────────


def _load_subscriber(origin_secret: str | None = ""):
    """Import web.email_subscriber_lambda with all AWS calls patched out.

    origin_secret=None means the env var is entirely UNSET (the pre-deploy /
    partial-deploy state the fail-open contract protects); "" and unset must
    behave identically (guard disabled).
    """
    env = {
        "TABLE_NAME": "test-table",
        "USER_ID": "matthew",
        "S3_BUCKET": "test-bucket",
    }
    if origin_secret is not None:
        env["SITE_API_ORIGIN_SECRET"] = origin_secret

    with (
        mock.patch.dict("sys.modules", _fake_aws_modules()),
        mock.patch.dict(os.environ, env),
    ):
        if origin_secret is None:
            os.environ.pop("SITE_API_ORIGIN_SECRET", None)
        # Drop cached modules so they re-execute under the patched env. The
        # secret constant lives in site_api_common and is imported into
        # email_subscriber_lambda — both (flat + web.* namespaced) must reload,
        # same order-dependence rationale as _load_site_api above.
        for _name in list(sys.modules):
            if "site_api" in _name or "email_subscriber" in _name:
                del sys.modules[_name]
        mod = importlib.import_module("web.email_subscriber_lambda")
    return mod


def _subscribe_event(method: str = "POST", headers: dict | None = None) -> dict:
    return {
        "rawPath": "/api/subscribe",
        "requestContext": {"http": {"method": method, "sourceIp": "1.2.3.4"}},
        "headers": headers or {},
        "queryStringParameters": {},
        "body": '{"email": "reader@example.org", "source": "test"}',
    }


class TestOriginHeaderSubscriberDisabled:
    """#885 fail-open contract: env var unset or empty → ALL requests pass.

    This is the deploy-ordering guarantee — email-subscriber Lambda code can
    ship before CloudFront starts injecting the header without breaking
    subscriptions.
    """

    def test_env_var_entirely_unset_allows_without_header(self):
        mod = _load_subscriber(origin_secret=None)
        resp = mod.lambda_handler(_subscribe_event(headers={}), None)
        assert resp["statusCode"] != 403, "Guard must fail-open when SITE_API_ORIGIN_SECRET is unset"

    def test_empty_secret_allows_without_header(self):
        mod = _load_subscriber(origin_secret="")
        resp = mod.lambda_handler(_subscribe_event(headers={}), None)
        assert resp["statusCode"] != 403

    def test_empty_secret_allows_with_stray_header(self):
        mod = _load_subscriber(origin_secret="")
        resp = mod.lambda_handler(_subscribe_event(headers={"x-amj-origin": "anything"}), None)
        assert resp["statusCode"] != 403


class TestOriginHeaderSubscriberEnabled:
    """#885: secret configured → missing/wrong header 403s, correct header passes."""

    SECRET = "test-cf-origin-secret-subscriber-885"

    def setup_method(self):
        self.mod = _load_subscriber(origin_secret=self.SECRET)

    def test_missing_header_rejected(self):
        resp = self.mod.lambda_handler(_subscribe_event(headers={}), None)
        assert resp["statusCode"] == 403, "Direct Function-URL request (no X-AMJ-Origin) must be rejected 403"

    def test_wrong_header_value_rejected(self):
        resp = self.mod.lambda_handler(_subscribe_event(headers={"x-amj-origin": "wrong-value"}), None)
        assert resp["statusCode"] == 403

    def test_correct_header_passes(self):
        resp = self.mod.lambda_handler(_subscribe_event(headers={"x-amj-origin": self.SECRET}), None)
        assert resp["statusCode"] != 403, "Via-CloudFront request (correct X-AMJ-Origin) must not be rejected"

    def test_correct_header_case_insensitive(self):
        resp = self.mod.lambda_handler(_subscribe_event(headers={"X-AMJ-Origin": self.SECRET}), None)
        assert resp["statusCode"] != 403

    def test_options_preflight_bypasses_check(self):
        """CORS preflight must not be blocked — the guard sits after the OPTIONS branch."""
        resp = self.mod.lambda_handler(_subscribe_event(method="OPTIONS", headers={}), None)
        assert resp["statusCode"] == 204

    def test_get_confirm_without_header_rejected(self):
        """The guard covers ALL routes (confirm/unsubscribe GETs too), not just POST subscribe."""
        event = _subscribe_event(method="GET", headers={})
        event["queryStringParameters"] = {"action": "confirm", "token": "x" * 64, "h": "abcdef"}
        resp = self.mod.lambda_handler(event, None)
        assert resp["statusCode"] == 403

    def test_403_body_is_valid_json(self):
        resp = self.mod.lambda_handler(_subscribe_event(headers={}), None)
        assert resp["statusCode"] == 403
        import json

        body = json.loads(resp["body"])
        assert body.get("error")

    def test_uses_shared_secret_constant(self):
        """Must import the SAME SITE_API_ORIGIN_SECRET site_api_common defines —
        not a second os.environ.get, which would risk drifting the env-var name
        (same convention pinned for site_api_ai_lambda above)."""
        src_path = os.path.join(ROOT, "lambdas", "web", "email_subscriber_lambda.py")
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        assert "from web.site_api_common import SITE_API_ORIGIN_SECRET" in src
        assert "_hmac.compare_digest" in src, "must use constant-time comparison, not =="


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
