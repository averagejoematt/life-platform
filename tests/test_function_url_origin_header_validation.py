#!/usr/bin/env python3
"""
tests/test_function_url_origin_header_validation.py — SEC-04

Verifies that site_api_lambda enforces the X-AMJ-Origin header check when
SITE_API_ORIGIN_SECRET is configured. CloudFront injects this header on every
origin request (set as a custom origin header in the distribution config).
Requests that bypass CloudFront and hit the Function URL directly will lack
the header and must be rejected 403.

Run: python3 -m pytest tests/test_function_url_origin_header_validation.py -v

v1.0.0 — 2026-03-21 (SEC-04)
"""

import importlib
import os
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


def _load_site_api(origin_secret: str = ""):
    """Import site_api_lambda with all AWS calls patched out."""
    # Patch boto3 so no real AWS calls are made
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

    with (
        mock.patch.dict("sys.modules", {
            "boto3": fake_boto3,
            "boto3.dynamodb": types.ModuleType("boto3.dynamodb"),
            "boto3.dynamodb.conditions": fake_conditions,
        }),
        mock.patch.dict(os.environ, {
            "TABLE_NAME": "test-table",
            "USER_ID": "matthew",
            "S3_BUCKET": "test-bucket",
            "SITE_API_ORIGIN_SECRET": origin_secret,
        }),
    ):
        if "site_api_lambda" in sys.modules:
            del sys.modules["site_api_lambda"]
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
        assert resp["statusCode"] != 403, (
            "Should allow all requests when SITE_API_ORIGIN_SECRET is not configured"
        )

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
        assert resp["statusCode"] == 403, (
            "Request without X-AMJ-Origin must be rejected 403 when secret is configured"
        )

    def test_wrong_header_value_rejected(self):
        event = _make_event("/api/vitals", headers={"x-amj-origin": "wrong-value"})
        resp = self.mod.lambda_handler(event, None)
        assert resp["statusCode"] == 403, (
            "Request with incorrect X-AMJ-Origin must be rejected 403"
        )

    def test_correct_header_passes(self):
        event = _make_event("/api/vitals", headers={"x-amj-origin": self.SECRET})
        resp = self.mod.lambda_handler(event, None)
        assert resp["statusCode"] != 403, (
            "Request with correct X-AMJ-Origin must not be rejected"
        )

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
