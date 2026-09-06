"""email_identity.py — the ONE home for who platform mail is From (#3568; epic #3498).

Root cause this fixes: the sending vocabulary had two homes and no guard between
them. Every `SENDER` in `lambdas/` reads `EMAIL_SENDER` from the environment, and
`cdk/stacks/lambda_helpers.py` supplies that env var to every function from a
hand-typed literal — so the code default and the CDK value could disagree with
each other, and with SES, and nothing failed. They did disagree:
`between_chronicle_lambda.py` defaulted to `Elena Voss <elena@averagejoematt.com>`
while `averagejoematt.com` was not an SES identity at all. That default was
unreachable (the CDK env var is always set), so it was a vocabulary defect rather
than an outage — but "wrong and unreachable" is one CDK refactor away from
"wrong and sending".

The rule: **an address a Lambda may send From is named here, and its domain is
one this account has actually verified in SES.** Both halves are asserted by
`tests/test_email_sender_identity_3568.py`, which AST-scans every code default
and every CDK `EMAIL_SENDER` literal against the constants below. A new sender
address whose domain is not in `VERIFIED_SENDING_DOMAINS` reds the build.

AUDIENCE ORDER (this is the reason there is more than one address):

  * READER mail — people who subscribed on the public site. It goes From the
    site's own domain, because a stranger who gets mail From a personal domain
    they never heard of has no way to tell it is the thing they signed up for.
  * OWNER mail — the daily brief, digests, nudges, review packs. One recipient,
    who knows exactly what it is. Stays on the personal domain.
  * OPS mail — alarm digests, DLQ notices, QA smoke. Owner-only, deliberately a
    distinct address so a mail rule can filter it away from the reading pile.

VERIFYING A NEW DOMAIN is an owner act with a DNS half; it is not something a
deploy can do. The record for `averagejoematt.com` (done 2026-09-06):

    aws sesv2 create-email-identity --email-identity <domain> --region us-west-2
    aws sesv2 put-email-identity-mail-from-attributes \
        --email-identity <domain> --mail-from-domain mail.<domain> --region us-west-2
    # then the 3 Easy-DKIM CNAMEs + the MAIL FROM MX/SPF into Route 53

RE-DERIVE the list below from the account (the check this file cannot make for
itself, since a Lambda has no SES read permission at import time):

    aws sesv2 list-email-identities --region us-west-2 \
        --query 'EmailIdentities[?VerifiedForSendingStatus].IdentityName'

DMARC NOTE, because it decides what a broken DKIM costs: `averagejoematt.com`
publishes `p=quarantine; adkim=s; aspf=s`. The custom MAIL FROM is
`mail.averagejoematt.com`, a SUBDOMAIN of the From domain — under `aspf=s` that
does NOT align, so SPF cannot carry DMARC here. Easy DKIM signs
`d=averagejoematt.com`, which does align strictly, and DMARC passes on that leg
alone. Reader mail therefore depends on DKIM specifically: if the three
`_domainkey` CNAMEs are ever pruned, reader mail is quarantined and SPF will not
rescue it.
"""

from __future__ import annotations

# ── The registry: domains this AWS account has verified for sending ──
# us-west-2. Re-derive with the list-email-identities command in the docstring.
# This set only grows by an owner act (create-email-identity + DNS); a sender
# address whose domain is absent here fails the gate rather than SES.
VERIFIED_SENDING_DOMAINS: frozenset[str] = frozenset(
    {
        "averagejoematt.com",  # the site's own domain — Easy DKIM + MAIL FROM mail.averagejoematt.com (2026-09-06)
        "mattsusername.com",  # the personal domain — Easy DKIM, no custom MAIL FROM
    }
)

# The site domain, named once so the reader senders below cannot drift apart.
SITE_DOMAIN = "averagejoematt.com"
PERSONAL_DOMAIN = "mattsusername.com"

# ── Reader-facing senders (public subscribers) ──
# Display names are the personas the site already publishes under; the local
# parts are the ones the repo already used (`elena@`, `signal@`, `hello@` — the
# last is on deploy/pii_surface_guard.py's public-contact allowlist).
CHRONICLE_SENDER = f"Elena Voss <elena@{SITE_DOMAIN}>"
SIGNAL_SENDER = f"The Weekly Signal <signal@{SITE_DOMAIN}>"
TRANSACTIONAL_SENDER = f"Average Joe Matt <hello@{SITE_DOMAIN}>"

# ── Owner-facing and operational senders (single recipient, not readers) ──
OWNER_SENDER = f"lifeplatform@{PERSONAL_DOMAIN}"
OPS_SENDER = f"awsdev@{PERSONAL_DOMAIN}"

# ── The reader set, by live function name ──
# The audience classification the gate enforces: these functions send to people
# who are not Matthew, so their From must be on SITE_DOMAIN. Kept as a mapping
# rather than a set so the CDK literal and the code default are checked against
# the SAME expected value, not merely against "some site address".
READER_FACING_SENDERS: dict[str, str] = {
    "chronicle-email-sender": CHRONICLE_SENDER,
    "between-chronicle": CHRONICLE_SENDER,
    "weekly-signal": SIGNAL_SENDER,
    "email-subscriber": TRANSACTIONAL_SENDER,
    "subscriber-onboarding": TRANSACTIONAL_SENDER,
}


def sender_domain(value: str) -> str:
    """The domain of a sender value, in either form SES accepts.

    Handles both the bare `a@b.com` and the RFC 5322 `Display Name <a@b.com>`
    that SES's `FromEmailAddress` also takes. Returns "" for anything without
    an `@`, so a caller can tell "no domain" from a domain it does not like.
    """
    v = value.strip()
    if v.endswith(">") and "<" in v:
        v = v[v.rindex("<") + 1 : -1].strip()
    if "@" not in v:
        return ""
    return v.rsplit("@", 1)[1].strip().lower()


def is_verified_sender(value: str) -> bool:
    """True when `value`'s domain is one this account has verified for sending."""
    return sender_domain(value) in VERIFIED_SENDING_DOMAINS
