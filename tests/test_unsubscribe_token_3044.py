"""tests/test_unsubscribe_token_3044.py — the subscriber trust package (#3044, DIL-003/DIL-013).

Four guarantees, each of which was FALSE before #3044:

  1. TOKEN: the signed unsubscribe token round-trips, expires, and rejects every
     tampered/foreign shape without raising — and no minted URL ever carries a
     plaintext email address.
  2. SET-GUARD: no module in lambdas/ or deploy/ constructs the old
     `action=unsubscribe&email=` plaintext link — guarding the SET, so a new sender
     can't quietly reintroduce the leak — and every known subscriber-email sender
     mints through the ONE shared helper.
  3. SUNSET: the legacy `email=` grace window is dated and the handler rejects the
     legacy parameter once it closes (no deploy needed on the day).
  4. POLICY IDENTITY: page copy, runtime constants, and the retention registry state
     the SAME policy — anonymize at unsubscribe (window 0), sha256 suppression hash
     retained — and the old false claims are gone from /privacy/.

The end-to-end deletion evidence (synthetic subscriber → unsubscribe → plaintext gone
from the store in the same request) lives in tests/test_e2e_write_paths.py's
subscribe→confirm→unsubscribe lifecycle, on the same fake-wire harness as every other
write path.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from common import unsubscribe_token as ut  # noqa: E402

SECRET = "test-unsub-signing-key"
EMAIL = "reader+3044@example.com"
NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)


# ── 1. Token mint/verify ─────────────────────────────────────────────────────────


def test_roundtrip_returns_the_email_hash():
    token = ut.mint_unsub_token(EMAIL, SECRET, now=NOW)
    assert ut.verify_unsub_token(token, SECRET, now=NOW) == ut.subscriber_email_hash(EMAIL)


def test_token_carries_no_plaintext_email():
    token = ut.mint_unsub_token(EMAIL, SECRET, now=NOW)
    url = ut.build_unsub_url(EMAIL, "https://averagejoematt.com", secret=SECRET)
    for surface in (token, url):
        assert EMAIL not in surface
        assert "@" not in surface.replace("averagejoematt.com", "")
        assert "%40" not in surface  # not merely URL-encoded either
    assert f"action=unsubscribe&{ut.UNSUB_TOKEN_PARAM}=" in url


def test_expired_token_rejected():
    token = ut.mint_unsub_token(EMAIL, SECRET, now=NOW)
    just_valid = NOW + timedelta(days=ut.UNSUB_TOKEN_TTL_DAYS) - timedelta(seconds=1)
    expired = NOW + timedelta(days=ut.UNSUB_TOKEN_TTL_DAYS, seconds=5)
    assert ut.verify_unsub_token(token, SECRET, now=just_valid) is not None
    assert ut.verify_unsub_token(token, SECRET, now=expired) is None


def test_tampered_and_foreign_shapes_rejected_without_raising():
    token = ut.mint_unsub_token(EMAIL, SECRET, now=NOW)
    version, ehash, exp, sig = token.split(".")
    other_hash = ut.subscriber_email_hash("victim@example.com")
    hostile = [
        "",  # empty
        "v1",  # too few parts
        token + ".extra",  # too many parts
        f"v2.{ehash}.{exp}.{sig}",  # wrong version
        f"{version}.{other_hash}.{exp}.{sig}",  # swapped victim hash, old sig
        f"{version}.{ehash}.{int(exp) + 9999999}.{sig}",  # extended expiry, old sig
        f"{version}.{ehash}.{exp}.{'0' * 32}",  # forged sig
        f"{version}.{ehash}.notanumber.{sig}",  # non-numeric expiry
        f"{version}.{ehash[:10]}.{exp}.{sig}",  # truncated hash
        "eyJmb28iOiAiYmFyIn0=:12345:deadbeef",  # session-token-shaped (site_api_social) — domain separation
    ]
    for bad in hostile:
        assert ut.verify_unsub_token(bad, SECRET, now=NOW) is None, bad


def test_wrong_secret_rejected():
    token = ut.mint_unsub_token(EMAIL, SECRET, now=NOW)
    assert ut.verify_unsub_token(token, "a-different-key", now=NOW) is None


def test_email_hash_is_normalized():
    assert ut.subscriber_email_hash("  Reader+3044@EXAMPLE.com ") == ut.subscriber_email_hash("reader+3044@example.com")


def test_fallback_url_never_carries_the_address(monkeypatch):
    """With NO key material anywhere, the guarded helper degrades to the /privacy/
    mail-based unsubscribe instructions — never to a plaintext-email link."""
    monkeypatch.delenv("UNSUB_TOKEN_SECRET", raising=False)
    monkeypatch.setattr(ut, "get_unsub_secret", MagicMock(side_effect=RuntimeError("no key")))
    url = ut.unsub_url_or_fallback(EMAIL, "https://averagejoematt.com")
    assert url == "https://averagejoematt.com/privacy/#unsubscribe"
    assert EMAIL not in url


# ── 2. Set-guard: the plaintext-email unsubscribe link is EXTINCT ────────────────

_PLAINTEXT_LINK = re.compile(r"action=unsubscribe&email=")

# Every module that sends subscriber email mints through the ONE shared helper.
SENDER_FILES = [
    "lambdas/web/email_subscriber_lambda.py",
    "lambdas/web/subscriber_onboarding_lambda.py",
    "lambdas/emails/between_chronicle_lambda.py",
    "lambdas/emails/chronicle_email_sender_lambda.py",
    "lambdas/emails/coach_panel_podcast_lambda.py",
    "lambdas/compute/weekly_signal_lambda.py",
    "deploy/send_prereg_lock_email.py",
]


def test_no_module_constructs_a_plaintext_email_unsub_link():
    offenders = []
    for base in ("lambdas", "deploy"):
        for path in (ROOT / base).rglob("*.py"):
            if _PLAINTEXT_LINK.search(path.read_text(encoding="utf-8", errors="ignore")):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"plaintext-email unsubscribe links reintroduced in: {offenders}"


def test_every_known_sender_mints_through_the_shared_helper():
    for rel in SENDER_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "unsub_url_or_fallback" in text, f"{rel} no longer mints via common.unsubscribe_token"


# ── 3. The legacy grace window is dated and closes by itself ─────────────────────


def test_legacy_window_dates():
    assert ut.legacy_email_param_accepted(ut.LEGACY_EMAIL_PARAM_SUNSET - timedelta(days=1)) is True
    assert ut.legacy_email_param_accepted(ut.LEGACY_EMAIL_PARAM_SUNSET) is False
    assert ut.legacy_email_param_accepted(ut.LEGACY_EMAIL_PARAM_SUNSET + timedelta(days=30)) is False
    assert ut.LEGACY_EMAIL_PARAM_SUNSET == date(2026, 9, 22)


@pytest.fixture()
def sub_module(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    from web import email_subscriber_lambda as sub

    monkeypatch.setattr(sub, "table", MagicMock())
    monkeypatch.setattr(sub, "ses", MagicMock())
    return sub


def test_handler_rejects_legacy_email_param_after_sunset(sub_module, monkeypatch):
    class _PostSunset(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 1, 12, 0, 0, tzinfo=tz or timezone.utc)

    monkeypatch.setattr(sub_module, "datetime", _PostSunset)
    event = {
        "requestContext": {"http": {"method": "GET"}},
        "queryStringParameters": {"action": "unsubscribe", "email": EMAIL},
        "headers": {},
    }
    resp = sub_module.lambda_handler(event, None)
    assert resp["statusCode"] == 302 and "error=invalid_token" in resp["headers"]["Location"]
    sub_module.table.update_item.assert_not_called()  # rejected BEFORE any state touch


def test_handler_tokenless_get_cannot_mutate(sub_module):
    event = {
        "requestContext": {"http": {"method": "GET"}},
        "queryStringParameters": {"action": "unsubscribe"},
        "headers": {},
    }
    resp = sub_module.lambda_handler(event, None)
    assert resp["statusCode"] == 302 and "error=invalid_token" in resp["headers"]["Location"]
    sub_module.table.update_item.assert_not_called()
    sub_module.table.get_item.assert_not_called()


# ── 4. Policy identity: page ↔ runtime ↔ registry ────────────────────────────────

PRIVACY_PAGE = ROOT / "site" / "privacy" / "index.html"
GOVERNANCE = ROOT / "docs" / "DATA_GOVERNANCE.md"


def test_privacy_page_states_the_implemented_contract():
    html = PRIVACY_PAGE.read_text(encoding="utf-8")
    # The true mechanism, stated: anonymize on the spot, hash retained, hard-delete on request.
    assert "anonymized on the spot" in html
    assert "SHA-256" in html
    assert 'id="unsubscribe"' in html  # the anchor the degraded-mint fallback URL targets
    assert "hard-deleted within 7 days" in html
    # The pre-#3044 false claims are gone.
    assert "deleted from the subscriber list entirely" not in html
    assert "removed immediately" not in html


def test_runtime_and_registry_agree_on_window_zero():
    from content import subscriber_retention as sr

    assert sr.RETENTION_WINDOW_DAYS == 0 and sr.RETENTION_MODE == "anonymize"
    row = [ln for ln in GOVERNANCE.read_text(encoding="utf-8").splitlines() if "Subscriber emails" in ln and "|" in ln][0]
    assert "0 days" in row and "at unsubscribe" in row.lower()


def test_handler_redacts_with_the_sweeps_literal():
    """The inline anonymize and the weekly backstop sweep must write the SAME
    redaction marker, or the sweep's idempotency check stops recognizing
    handler-scrubbed rows."""
    from content.subscriber_retention import REDACTED_EMAIL
    from web import email_subscriber_lambda as sub

    assert sub.REDACTED_EMAIL == REDACTED_EMAIL == "[redacted]"


def test_conftest_supplies_the_test_signing_key():
    """Sender template tests assert tokenized links; that only holds because the
    suite-wide env key is present (hermetic — no Secrets Manager round-trip)."""
    assert os.environ.get("UNSUB_TOKEN_SECRET"), "conftest.py must set UNSUB_TOKEN_SECRET for the unit suite"
