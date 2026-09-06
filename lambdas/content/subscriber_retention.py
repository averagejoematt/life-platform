"""lambdas/subscriber_retention.py — signed subscriber-email retention policy (#3044).

Single source of truth for the retention WINDOW + MODE Matthew signed into
docs/DATA_GOVERNANCE.md's "Subscriber emails" row, plus the pure eligibility/redaction
logic the scheduled sweep shares. Bundled at the lambdas/ root (#781 one-bundle) so the
operational Lambda imports it by bare name, exactly like platform_logger / client_ip.

SIGNED POLICY (docs/DATA_GOVERNANCE.md, v2 2026-08-23, #3044 — supersedes the #1350
548-day window signed 2026-07-25):
  ANONYMIZE at unsubscribe. The unsubscribe handler itself
  (web/email_subscriber_lambda.handle_unsubscribe) scrubs the PII in the same write
  that flips the status — plaintext `email` redacted, `ip_hash` dropped,
  `anonymized_at` stamped. Only the PII is scrubbed — the sk (sha256 hash), `status`,
  and all timestamps are preserved, so the subscriber COUNT and confirmation state
  that public stats reference survive, and the hash doubles as the suppression record
  that prevents re-mailing. Active (pending/confirmed) subscribers are NEVER touched:
  an ongoing delivery relationship is the lawful basis to hold their address.

  RETENTION_WINDOW_DAYS = 0 makes the weekly sweep the BACKSTOP, not the mechanism:
  any unsubscribed row still carrying plaintext (rows unsubscribed under the old
  548-day policy, or a row where the inline anonymize write failed) is scrubbed on
  the next weekly run. Stated SLA: immediate at the unsubscribe click; ≤7 days
  worst-case via the sweep; on-request hard delete (including the hash) via
  delete_user_data_lambda's `subscriber_email` path.

Two independent enactment paths read these constants (deliberately not one runtime, to
avoid coupling independently deployed contexts):
  - the scheduled sweep — delete_user_data_lambda's `subscriber_retention_sweep` event
    (weekly EventBridge rule, operational_stack.py); reuses that Lambda's existing DDB
    access (Scan + PutItem + DeleteItem) — no new IAM.
  - the attended CLI — deploy/subscriber_retention_purge.py (operator-run, dry-run by
    default), whose --window-days / --mode default to these same constants.

PENDING-CONFIRMATION EXPIRY (#3566): the anonymize-at-unsubscribe policy above has no
terminal state for a `pending_confirmation` row whose confirm token expired and was
never re-sent — `is_retention_eligible` requires `status == "unsubscribed"`, so a stale
pending row is structurally NEVER eligible for the sweep above and sits forever
carrying a plaintext email (found live: two 2026-07-03 rows, tokens expired 2026-07-05,
still `pending_confirmation` 61+ days later). `PENDING_EXPIRY_GRACE_DAYS` below is a
SEPARATE, independent grace window — not the unsubscribe retention window — governing
when a dead confirmation attempt is declared over: `is_pending_expired` fires
`PENDING_EXPIRY_GRACE_DAYS` after `token_expires` (never at expiry itself — a slow
inbox check should not race the sweep), and `expired_pending_item` transitions the row
to a terminal `status="expired"` with the same PII scrub `anonymized_item` applies to
an unsubscribed row (plaintext `email` redacted, `ip_hash` dropped). The same two
enactment paths above run this leg too."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from common.pacific_time import parse_iso_utc  # #1964 — THE ISO parser, never a private fork

# ── Signed window (docs/DATA_GOVERNANCE.md "Subscriber emails" row) ──────────────
RETENTION_WINDOW_MONTHS = 0
# 0 days: anonymize-at-unsubscribe (#3044). The handler scrubs inline; the weekly
# sweep treats EVERY unsubscribed row still carrying plaintext as past-window.
# The doc row names both forms; the guard test asserts they agree.
RETENTION_WINDOW_DAYS = 0
# Signed mode: scrub the email but keep the row (hash/status/timestamps) so aggregate
# subscriber-count analytics survive. "purge" (hard-delete the row) is the other option.
RETENTION_MODE = "anonymize"
REDACTED_EMAIL = "[redacted]"

# ── Pending-confirmation expiry (#3566) — a SEPARATE grace window from the
# unsubscribe-retention one above; see the module docstring. ─────────────────────
PENDING_EXPIRY_GRACE_DAYS = 7


def retention_cutoff_iso(now: datetime | None = None) -> str:
    """ISO timestamp `RETENTION_WINDOW_DAYS` before `now`. Rows unsubscribed before
    this instant are past the signed window."""
    now = now or datetime.now(timezone.utc)
    return (now - timedelta(days=RETENTION_WINDOW_DAYS)).isoformat()


def is_retention_eligible(item: dict, cutoff_iso: str) -> bool:
    """True iff `item` is an unsubscribed subscriber row whose `unsubbed_at` predates
    `cutoff_iso`. Fails safe: an unsubscribed row missing `unsubbed_at` is NOT eligible
    (never act on missing data). Active pending/confirmed rows are never eligible."""
    return item.get("status") == "unsubscribed" and bool(item.get("unsubbed_at")) and str(item["unsubbed_at"]) < cutoff_iso


def needs_anonymization(item: dict, cutoff_iso: str) -> bool:
    """Sweep-time filter: eligible AND still carrying PII (not already anonymized).
    Makes the anonymize sweep idempotent — a second run is a no-op on scrubbed rows."""
    return is_retention_eligible(item, cutoff_iso) and not item.get("anonymized_at") and item.get("email") != REDACTED_EMAIL


def anonymized_item(item: dict, now_iso: str | None = None) -> dict:
    """A copy of `item` with PII scrubbed: plaintext `email` redacted, `ip_hash`
    dropped, `anonymized_at` stamped. sk, status, and timestamps are preserved."""
    now_iso = now_iso or datetime.now(timezone.utc).isoformat()
    out = dict(item)
    out["email"] = REDACTED_EMAIL
    out.pop("ip_hash", None)
    out["anonymized_at"] = now_iso
    return out


def is_pending_expired(item: dict, now: datetime | None = None) -> bool:
    """True iff `item` is a `pending_confirmation` row whose `token_expires` is more
    than `PENDING_EXPIRY_GRACE_DAYS` in the past. Fails safe: a pending row missing
    `token_expires` is NOT eligible — never act on missing data, same posture as
    `is_retention_eligible`'s `unsubbed_at` check. Already-expired rows (this
    function returning True on a prior sweep) stay eligible until actually
    transitioned — the sweep-side idempotence lives in `needs_pending_expiry`."""
    if item.get("status") != "pending_confirmation":
        return False
    expires = parse_iso_utc(item.get("token_expires"))
    if expires is None:
        return False
    now = now or datetime.now(timezone.utc)
    return now >= expires + timedelta(days=PENDING_EXPIRY_GRACE_DAYS)


def needs_pending_expiry(item: dict, now: datetime | None = None) -> bool:
    """Sweep-time filter: `is_pending_expired` AND not already transitioned. Makes
    the expiry sweep idempotent, mirroring `needs_anonymization`'s contract."""
    return is_pending_expired(item, now) and item.get("status") == "pending_confirmation"


def expired_pending_item(item: dict, now_iso: str | None = None) -> dict:
    """A copy of `item` transitioned to the terminal `status="expired"`, with the
    same PII scrub `anonymized_item` applies (plaintext `email` redacted, `ip_hash`
    dropped). `token_expires`/`confirm_token` are dropped too — a terminal row has
    no live confirmation path left to protect. `email_hash`/`created_at`/`sk` are
    preserved so the row's history and the suppression record survive."""
    now_iso = now_iso or datetime.now(timezone.utc).isoformat()
    out = dict(item)
    out["status"] = "expired"
    out["email"] = REDACTED_EMAIL
    out.pop("ip_hash", None)
    out.pop("confirm_token", None)
    out.pop("token_expires", None)
    out["anonymized_at"] = now_iso
    out["expired_at"] = now_iso
    return out
