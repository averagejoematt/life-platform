"""lambdas/subscriber_retention.py — signed subscriber-email retention policy (#1350).

Single source of truth for the retention WINDOW + MODE Matthew signed into
docs/DATA_GOVERNANCE.md's "Subscriber emails" row, plus the pure eligibility/redaction
logic the scheduled sweep shares. Bundled at the lambdas/ root (#781 one-bundle) so the
operational Lambda imports it by bare name, exactly like platform_logger / client_ip.

SIGNED POLICY (docs/DATA_GOVERNANCE.md, 2026-07-25):
  ANONYMIZE the plaintext email on unsubscribed subscriber rows 18 months
  (RETENTION_WINDOW_DAYS) after `unsubbed_at`. Only the PII is scrubbed — the sk
  (sha256 hash), `status`, and all timestamps are preserved, so the subscriber COUNT
  and confirmation state that public stats reference survive the sweep. Active
  (pending/confirmed) subscribers are NEVER touched: an ongoing delivery relationship
  is the lawful basis to hold their address.

Two independent enactment paths read these constants (deliberately not one runtime, to
avoid coupling independently deployed contexts):
  - the scheduled sweep — delete_user_data_lambda's `subscriber_retention_sweep` event
    (weekly EventBridge rule, operational_stack.py); reuses that Lambda's existing DDB
    access (Scan + PutItem + DeleteItem) — no new IAM.
  - the attended CLI — deploy/subscriber_retention_purge.py (operator-run, dry-run by
    default), whose --window-days / --mode default to these same constants.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# ── Signed window (docs/DATA_GOVERNANCE.md "Subscriber emails" row) ──────────────
RETENTION_WINDOW_MONTHS = 18
# 18 months expressed in days for a day-granularity `unsubbed_at` cutoff
# (18 × 30.4375 ≈ 548). The doc row names both forms; the guard test asserts they agree.
RETENTION_WINDOW_DAYS = 548
# Signed mode: scrub the email but keep the row (hash/status/timestamps) so aggregate
# subscriber-count analytics survive. "purge" (hard-delete the row) is the other option.
RETENTION_MODE = "anonymize"
REDACTED_EMAIL = "[redacted]"


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
