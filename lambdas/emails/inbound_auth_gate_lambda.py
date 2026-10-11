"""
Inbound Auth Gate Lambda — v1.0.0 (#4633)

The provider-level sender-authentication verdict for the platform's one mail-fed
capture path, enforced BEFORE the message is stored and before the parser can run.

Trigger: SES receipt rule (`insight-auth-gate`, cdk/stacks/operational_stack.py) →
this function, invoked RequestResponse as the rule's FIRST action — ahead of the
S3 action that lands the message under raw/inbound_email/ and therefore ahead of
the S3 notification that fires insight-email-parser. The return value is SES's
disposition contract:

    {"disposition": "CONTINUE"}       the message is stored and the parser runs
    {"disposition": "STOP_RULE_SET"}  nothing further happens — no S3 object, no
                                      notification, no parser, no record

The verdict (fail closed — every "don't know" is a refusal):
  * the receipt's `dmarcVerdict` must be PASS. Both sender domains the allowlist
    names publish DMARC with strict alignment (adkim=s / aspf=s, read 2026-10-11),
    so a DMARC pass is an ALIGNED pass — the From domain is the one SES verified.
    GRAY (no policy), FAIL, PROCESSING_FAILED and a missing verdict all refuse.
  * `spamVerdict` and `virusVerdict` must not be FAIL / PROCESSING_FAILED.
  * the From header's address must be in ALLOWED_SENDERS or STORY_REPLY_SENDERS —
    the same two environment variables the parser reads, set from ONE constant in
    the CDK stack so the two lists cannot drift. With both unset the gate refuses
    everything (no fallback address in source — the #4633 finding).
  * an exception anywhere above is a refusal too, never a pass-through.

Hazard-gate ordering (memory: hazard gate BEFORE model, privacy filter, rate limit):
this function IS the hazard gate for the inbound-email door. It runs before any
byte of the message body is stored or read; the parser's own `_ses_authenticated`
(Authentication-Results header, aligned DKIM-or-DMARC) is the defence-in-depth
twin that still refuses a message that somehow reached S3 without this verdict.

No grants of its own (role_policies_operational.operational_inbound_auth_gate is
an empty list — the role carries only the helper's fleet-wide baseline: CloudWatch
Logs, X-Ray traces, ssm:GetParameter on the two budget parameters; nothing on the
table, the bucket, SES or Secrets), and no boto3 client is constructed here, so a
verdict bug cannot write anything — the "writes nothing" clause of the acceptance
is structural, not behavioural.

Absence signal: `life-platform-inbound-auth-gate-bypassed` (operational_stack.py)
fires when insight-email-parser is invoked more often than this gate in a day —
the one way the gate goes silently absent (the hand-made rule set edited to drop
or reorder its rule) shows up as a parser run with no gate run before it.

Log hygiene: the REJECT line is the live proof the issue closes on and is meant to
be pasted into a public issue verbatim — it carries the SES messageId and the five
verdict statuses, never an address, never a rule name, never the body.
"""

import logging
import os
from email.utils import parseaddr
from typing import Any

# OBS-1: structured logger — the exception path logs through it; the verdict lines are plain prints, the same
# convention insight_email_parser_lambda.py uses for its per-message [WARN]/[INFO] lines (CloudWatch shows both).
try:
    from common.platform_logger import get_logger

    logger = get_logger("inbound-auth-gate")
except ImportError:  # pragma: no cover — bundle-dependent
    logger = logging.getLogger("inbound-auth-gate")
    logger.setLevel(logging.INFO)

#: The receipt verdict keys SES attaches to a receipt-rule Lambda invocation, in log order.
VERDICT_KEYS = ("spfVerdict", "dkimVerdict", "dmarcVerdict", "spamVerdict", "virusVerdict")

#: The statuses that mean "the scanner positively found a problem" — spam/virus refuse on these only.
_SCAN_REFUSE = frozenset({"FAIL", "PROCESSING_FAILED"})

CONTINUE = {"disposition": "CONTINUE"}
STOP = {"disposition": "STOP_RULE_SET"}


def _csv_set(name: str) -> frozenset:
    return frozenset(s.strip().lower() for s in os.environ.get(name, "").split(",") if s.strip())


def accepted_senders() -> frozenset:
    """The union of the parser's two sender lists, read from the environment at call time (never cached at import —
    a test or a redeploy that changes the variables must be seen). Empty means: refuse everything."""
    return _csv_set("ALLOWED_SENDERS") | _csv_set("STORY_REPLY_SENDERS")


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def verdict_statuses(receipt: Any) -> dict:
    """Each verdict's status as SES wrote it, upper-cased; a missing verdict reads MISSING (which never passes)."""
    out = {}
    for key in VERDICT_KEYS:
        status = _dict(_dict(receipt).get(key)).get("status")
        out[key] = str(status).upper() if status else "MISSING"
    return out


def receipt_verdict(receipt: Any) -> tuple:
    """(accepted, reason, statuses) for one SES receipt object. Pure; the allowlist is NOT consulted here — this is the
    provider's word alone, so the parser can reuse it on an SES-direct record without a second copy of the rule."""
    statuses = verdict_statuses(receipt)
    for key in ("virusVerdict", "spamVerdict"):
        if statuses[key] in _SCAN_REFUSE:
            return False, f"{key}_{statuses[key].lower()}", statuses
    if statuses["dmarcVerdict"] != "PASS":
        return False, f"dmarc_{statuses['dmarcVerdict'].lower()}", statuses
    return True, "ok", statuses


def from_address(mail: Any) -> str:
    """The From header's bare address, lower-cased, or "" when SES gave none / it does not parse."""
    froms = _dict(_dict(mail).get("commonHeaders")).get("from")
    if not froms or not isinstance(froms, list):
        return ""
    addr = parseaddr(str(froms[0]))[1].strip().lower()
    return addr if "@" in addr else ""


def gate_record(record: Any) -> tuple:
    """(accepted, reason, statuses, message_id) for one SES event record — the whole verdict, allowlist included."""
    ses_info = _dict(_dict(record).get("ses"))
    mail = _dict(ses_info.get("mail"))
    receipt = _dict(ses_info.get("receipt"))
    message_id = str(mail.get("messageId") or "unknown")
    senders = accepted_senders()
    if not senders:
        return False, "allowlist_unset", verdict_statuses(receipt), message_id
    ok, reason, statuses = receipt_verdict(receipt)
    if not ok:
        return False, reason, statuses, message_id
    if from_address(mail) not in senders:
        return False, "sender_not_listed", statuses, message_id
    return True, "ok", statuses, message_id


def _fmt(statuses: dict) -> str:
    return " ".join(f"{k.replace('Verdict', '')}={v}" for k, v in statuses.items())


def _reject(message_id: str, reason: str, statuses: dict) -> dict:
    print(
        f"[REJECT] inbound message refused at the receipt gate: messageId={message_id} reason={reason} "
        f"{_fmt(statuses)} — STOP_RULE_SET, nothing stored"
    )
    return dict(STOP)


def lambda_handler(event: dict, context) -> dict:
    """One disposition for the invocation. SES sends one record per invocation; should several ever arrive, a single
    refusal refuses the batch — the only fail-closed reading of a shared disposition."""
    try:
        records = _dict(event).get("Records")
        if not records or not isinstance(records, list):
            return _reject("unknown", "no_ses_record", verdict_statuses({}))
        for record in records:
            ok, reason, statuses, message_id = gate_record(record)
            if not ok:
                return _reject(message_id, reason, statuses)
            print(f"[PASS] inbound message accepted at the receipt gate: messageId={message_id} {_fmt(statuses)} — CONTINUE")
        return dict(CONTINUE)
    except Exception as e:  # noqa: BLE001 — a gate that cannot decide refuses; it never lets the message through
        logger.error("inbound auth gate failed closed: %s", type(e).__name__)
        return _reject("unknown", f"gate_exception_{type(e).__name__.lower()}", verdict_statuses({}))
