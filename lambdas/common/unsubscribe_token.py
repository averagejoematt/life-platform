"""common/unsubscribe_token.py — signed one-click unsubscribe links (#3044, DIL-003/DIL-013).

Every subscriber-facing sender used to build its unsubscribe link with the
subscriber's PLAINTEXT ADDRESS in the `email=` query param — an unauthenticated GET
mutation that
(a) let anyone unsubscribe anyone by guessing an address, and (b) leaked the
subscriber's plaintext address into referrer/CDN/access-log surfaces. This module is
the ONE mint/verify pair that replaces that construction across all senders:

  URL   {SITE_URL}/api/subscribe?action=unsubscribe&t=<token>
  token v1.<sha256(email)>.<exp-epoch>.<sig>
  sig   HMAC-SHA256(secret, "unsub:v1.<hash>.<exp>")[:32]  — hex

Design decisions (argued in PR for #3044):
  - The token carries the sha256 email HASH, never the address — the subscriber row's
    sk is EMAIL#<sha256>, so the verify side needs nothing else, and the URL contains
    no PII even before signature checking.
  - Key material is the EXISTING `life-platform/subscriber-token-secret` (a dedicated
    256-bit random HMAC key, #106) — same trust domain (subscriber-scoped tokens), no
    new secret to provision. Domain separation: the HMAC input is prefixed "unsub:",
    and the session-token payload shape (`email:expires`, '@' present) can never
    collide with this one (hex hash, dotted) — neither validator will ever accept the
    other's tokens.
  - Validity is UNSUB_TOKEN_TTL_DAYS (60): CAN-SPAM requires the unsubscribe mechanism
    in a sent email to work for >= 30 days, so "short-lived" here means
    email-lifetime-scale, not session-scale. Rotating the secret invalidates
    outstanding links for their remaining validity (the legacy-window/`/privacy/`
    fallback covers that gap operationally).
  - Replay is harmless by construction: the only state a valid token can produce is
    status=unsubscribed + anonymized PII, and that write is idempotent. A token never
    authenticates anything else.
  - Mint NEVER falls back to a plaintext-email URL. If key material is unavailable the
    guarded helper returns the /privacy/ mail-based unsubscribe instructions instead,
    and logs at ERROR so the gap is visible.

Secret resolution order: env `UNSUB_TOKEN_SECRET` (tests / break-glass override) ->
Secrets Manager `SUBSCRIBER_TOKEN_SECRET_NAME` (default
`life-platform/subscriber-token-secret`, us-west-2 — same pinned region as
site_api_social's fetch; email-subscriber itself runs in us-east-1).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)

UNSUB_TOKEN_VERSION = "v1"  # noqa: S105 — token format version, not a secret
UNSUB_TOKEN_PARAM = "t"  # noqa: S105 — query-param name, not a secret
UNSUB_TOKEN_TTL_DAYS = 60
_SIG_HEX_CHARS = 32

# #3044 grace window: links minted BEFORE this change carry `email=<plaintext>` and sit
# in inboxes. The handler honors them (logged) until this date, then rejects — a dated,
# automatic removal, no deploy needed on the day.
LEGACY_EMAIL_PARAM_SUNSET = date(2026, 9, 22)

UNSUB_SECRET_NAME = os.environ.get("SUBSCRIBER_TOKEN_SECRET_NAME", "life-platform/subscriber-token-secret")


def subscriber_email_hash(email: str) -> str:
    """sha256 of the lowercased/stripped email — the subscriber row's sk identity."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def get_unsub_secret() -> str:
    """The HMAC key. Env override first (tests/break-glass), then Secrets Manager
    (cached 15 min via secret_cache). Raises RuntimeError when neither answers —
    minting must fail LOUD, never fall back to a plaintext-email link."""
    env_secret = os.environ.get("UNSUB_TOKEN_SECRET", "")
    if env_secret:
        return env_secret
    try:
        import boto3

        from common.secret_cache import get_secret

        client = boto3.client("secretsmanager", region_name="us-west-2")
        return get_secret(UNSUB_SECRET_NAME, client)
    except Exception as exc:
        raise RuntimeError(f"unsubscribe signing secret unavailable: {exc}") from exc


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), f"unsub:{payload}".encode(), hashlib.sha256).hexdigest()[:_SIG_HEX_CHARS]


def mint_unsub_token(email: str, secret: str, now: datetime | None = None) -> str:
    """`v1.<email_hash>.<exp>.<sig>` — valid UNSUB_TOKEN_TTL_DAYS from `now`."""
    now = now or datetime.now(timezone.utc)
    exp = int((now + timedelta(days=UNSUB_TOKEN_TTL_DAYS)).timestamp())
    payload = f"{UNSUB_TOKEN_VERSION}.{subscriber_email_hash(email)}.{exp}"
    return f"{payload}.{_sign(payload, secret)}"


def verify_unsub_token(token: str, secret: str, now: datetime | None = None) -> str | None:
    """The email HASH the token was minted for, or None (bad shape / bad signature /
    expired). Never raises on hostile input; comparison is constant-time."""
    now = now or datetime.now(timezone.utc)
    parts = (token or "").split(".")
    if len(parts) != 4:
        return None
    version, email_hash, exp_str, sig = parts
    if version != UNSUB_TOKEN_VERSION or len(email_hash) != 64 or len(sig) != _SIG_HEX_CHARS:
        return None
    if not exp_str.isdigit():
        return None
    payload = f"{version}.{email_hash}.{exp_str}"
    if not hmac.compare_digest(_sign(payload, secret), sig):
        return None
    if int(exp_str) < int(now.timestamp()):
        return None
    return email_hash


def build_unsub_url(email: str, site_url: str, secret: str | None = None) -> str:
    """The signed unsubscribe URL for one subscriber. Raises RuntimeError when key
    material is unavailable — use `unsub_url_or_fallback` in send loops."""
    secret = secret or get_unsub_secret()
    return f"{site_url}/api/subscribe?action=unsubscribe&{UNSUB_TOKEN_PARAM}={mint_unsub_token(email, secret)}"


def unsub_url_or_fallback(email: str, site_url: str) -> str:
    """`build_unsub_url`, degrading to the /privacy/ mail-based unsubscribe
    instructions when the signing key is unavailable. The degraded link still
    satisfies CAN-SPAM (a working unsubscribe mechanism) and NEVER carries the
    subscriber's address; the ERROR log line is the operational signal."""
    try:
        return build_unsub_url(email, site_url)
    except RuntimeError as exc:
        logger.error("unsub link degraded to /privacy/ fallback (no signing key): %s", exc)
        return f"{site_url}/privacy/#unsubscribe"


def legacy_email_param_accepted(today: date | None = None) -> bool:
    """True while the #3044 grace window for pre-token `email=` links is open."""
    today = today or datetime.now(timezone.utc).date()
    return today < LEGACY_EMAIL_PARAM_SUNSET
