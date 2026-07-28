"""tests/test_notion_template_schema_1840.py — #1840: Notion Template
schema-drift gate.

#1572/#1573 shipped Video Diary + Solo Recording template support in
notion_lambda.py's TEMPLATE_SK, but the live Notion Journal database's
`Template` select property never got the matching options added — the
Notion API silently rejected any page carrying those values, so both
channels were unreachable from the moment the code shipped, with NO
signal anywhere (the "unknown template" fallback only fires when a
template string IS present-but-unrecognized; here it could never be set
at all). qa_smoke_lambda.check_notion_template_schema() closes that gap:
it reads the live Notion schema nightly and asserts every non-fallback
TEMPLATE_SK entry is a real select option.

Non-vacuous: `test_missing_options_fails_loudly` replays the actual
pre-2026-07-26 incident shape (TEMPLATE_SK has 7 templates, the live
select only has the original 5) and asserts a real `.fail()` — a check
that can never fail would not satisfy this test.

Fail-open coverage: a Notion secret-fetch error, a Notion API HTTP error,
and a malformed/empty schema response must all report `.warn()` (skipped),
never a false `.ok()` and never a `.fail()` that would page for an
unrelated Notion outage.
"""

import io
import json
import os
import sys
import urllib.error

# qa_smoke_lambda reads these at import time (conftest supplies fake AWS creds).
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import qa_smoke_lambda as qa  # noqa: E402
from common import secret_cache  # noqa: E402

NOTION_SECRET = {"notion_api_key": "secret_fake_key", "notion_database_id": "d86e0aaa-1379-42cc-94db-8ef56efb45ac"}

# The five options the live database actually had before the 2026-07-26 manual
# patch — the historical incident shape.
FIVE_LEGACY_OPTIONS = ["Morning", "Evening", "Stressor", "Health Event", "Weekly Reflection"]
# The full seven options after the manual patch.
ALL_SEVEN_OPTIONS = FIVE_LEGACY_OPTIONS + ["Video Diary", "Solo Recording"]


class _FakeSecretsClient:
    """Minimal boto3 secretsmanager client stub — get_secret_value only."""

    def __init__(self, secret_dict=None, raise_exc=None):
        self._secret_dict = secret_dict
        self._raise_exc = raise_exc

    def get_secret_value(self, SecretId):  # noqa: N803 — matches boto3's kw name
        if self._raise_exc:
            raise self._raise_exc
        return {"SecretString": json.dumps(self._secret_dict)}


class _FakeHTTPResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _db_payload(option_names):
    return {
        "properties": {
            "Template": {
                "type": "select",
                "select": {"options": [{"name": n, "id": f"id-{n}", "color": "gray"} for n in option_names]},
            }
        }
    }


def _patch_secret(monkeypatch, secret_dict=None, raise_exc=None):
    monkeypatch.setattr(qa.boto3, "client", lambda *a, **k: _FakeSecretsClient(secret_dict, raise_exc))
    secret_cache.invalidate()  # #1840: the 15-min TTL cache is a module-level dict shared across tests


def _patch_urlopen(monkeypatch, *, payload=None, http_error=None, generic_error=None):
    def _fake_urlopen(req, timeout=None):
        if http_error is not None:
            raise http_error
        if generic_error is not None:
            raise generic_error
        return _FakeHTTPResponse(payload)

    monkeypatch.setattr(qa.urllib.request, "urlopen", _fake_urlopen)


def test_missing_options_fails_loudly(monkeypatch):
    # The actual #1572/#1573 incident shape: code depends on 7 templates,
    # live Notion only ever had the original 5.
    _patch_secret(monkeypatch, secret_dict=NOTION_SECRET)
    _patch_urlopen(monkeypatch, payload=_db_payload(FIVE_LEGACY_OPTIONS))

    checks = qa.check_notion_template_schema()
    assert len(checks) == 1
    c = checks[0]
    assert c.passed is False, c.message
    assert "Video Diary" in c.message
    assert "Solo Recording" in c.message


def test_all_options_present_passes(monkeypatch):
    # Post-2026-07-26 manual patch: live schema has all 7 — clean pass.
    _patch_secret(monkeypatch, secret_dict=NOTION_SECRET)
    _patch_urlopen(monkeypatch, payload=_db_payload(ALL_SEVEN_OPTIONS))

    checks = qa.check_notion_template_schema()
    assert len(checks) == 1
    c = checks[0]
    assert c.passed is True, c.message
    assert c.paused is False


def test_notion_secret_fetch_failure_warns_not_fails(monkeypatch):
    # Fail-open: a Secrets Manager error must never look like a real schema mismatch.
    _patch_secret(monkeypatch, raise_exc=RuntimeError("AccessDeniedException"))

    checks = qa.check_notion_template_schema()
    assert len(checks) == 1
    c = checks[0]
    assert c.passed is None, c.message  # warn == passed is None in this Check schema
    assert c.paused is False


def test_notion_secret_missing_fields_warns(monkeypatch):
    _patch_secret(monkeypatch, secret_dict={"some_other_key": "x"})

    checks = qa.check_notion_template_schema()
    assert len(checks) == 1
    assert checks[0].passed is None


def test_notion_api_http_error_warns_not_fails(monkeypatch):
    # Fail-open: a Notion outage (5xx) must never be reported as a code<->schema
    # mismatch — that would page someone for a problem that isn't ours.
    _patch_secret(monkeypatch, secret_dict=NOTION_SECRET)
    err = urllib.error.HTTPError(
        url="https://api.notion.com/v1/databases/x", code=503, msg="Service Unavailable", hdrs=None, fp=io.BytesIO(b"")
    )
    _patch_urlopen(monkeypatch, http_error=err)

    checks = qa.check_notion_template_schema()
    assert len(checks) == 1
    c = checks[0]
    assert c.passed is None, c.message
    assert "503" in c.message


def test_notion_api_network_error_warns_not_fails(monkeypatch):
    _patch_secret(monkeypatch, secret_dict=NOTION_SECRET)
    _patch_urlopen(monkeypatch, generic_error=TimeoutError("timed out"))

    checks = qa.check_notion_template_schema()
    assert len(checks) == 1
    assert checks[0].passed is None


def test_empty_schema_response_warns_not_fails(monkeypatch):
    # A malformed/empty Template property (schema itself broken, not a code drift
    # question) reports skipped rather than a false fail.
    _patch_secret(monkeypatch, secret_dict=NOTION_SECRET)
    _patch_urlopen(monkeypatch, payload={"properties": {}})

    checks = qa.check_notion_template_schema()
    assert len(checks) == 1
    assert checks[0].passed is None
