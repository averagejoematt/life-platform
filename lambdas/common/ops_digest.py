"""common/ops_digest.py — put one ops notice into the daily LP digest instead of mailing it (#5821).

Owner ruling 2026-11-15 (#5821): the QA-smoke failure email, the remediation summary email and
the budget-tier change notice stop arriving on their own and become lines in the ONE daily
`[LP digest <date>]` email. Only a genuinely urgent condition still mails immediately, and each
caller decides that boundary itself.

THE MECHANISM IS THE DIGEST'S OWN, not a second digest. CloudWatch alarms reach the digest by
publishing to the `life-platform-alerts-digest` SNS topic, which delivers raw into
`life-platform-alerts-digest-queue`; `operational/alert_digest_lambda.py` drains that queue once a
day and groups by `AlarmName`. This module publishes to the same topic in the same JSON shape a
CloudWatch alarm notification has (`AlarmName`, `NewStateValue`, `NewStateReason`,
`StateChangeTime`), so the digest renders the line with no change on its side. A plain-text publish
would parse as `unparseable` and collapse into one line with every other plain-text producer.

FAIL TOWARDS DELIVERY: `enqueue_digest_line` returns False when the publish fails (no IAM grant
yet, throttling, a bad ARN), and every caller then sends the email it sent before #5821. Losing
the notice is worse than one more email. Under a dry run nothing is published and the call
returns True — the build path is exercised and nothing leaves the process.

Stdlib only, and the SNS client is a parameter, so the remediation agent (a GitHub Actions job,
not a Lambda) imports it the same way the Lambdas do.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("ops-digest")

DIGEST_TOPIC_NAME = "life-platform-alerts-digest"
# The state the digest prints in brackets after the line's name. Not a CloudWatch state: an ops
# notice is a fact that happened, not an alarm that can return to OK.
NOTICE_STATE = "NOTICE"
# The digest keeps the first 300 characters of a reason; stay under it so nothing is cut.
REASON_MAX = 300


def digest_topic_arn(region: Optional[str] = None, account: Optional[str] = None) -> str:
    """The digest topic ARN, built the way the platform's other digest producers build it."""
    region = region or os.environ.get("AWS_REGION", "us-west-2")
    account = account or os.environ.get("CDK_ACCOUNT", "205930651321")
    return f"arn:aws:sns:{region}:{account}:{DIGEST_TOPIC_NAME}"


def digest_line_payload(name: str, reason: str, *, state: str = NOTICE_STATE, when: Optional[datetime] = None) -> str:
    """The JSON body one digest line is made of, shaped like a CloudWatch alarm notification."""
    when = when or datetime.now(timezone.utc)
    reason = " ".join(str(reason).split())
    if len(reason) > REASON_MAX:
        reason = reason[: REASON_MAX - 1] + "…"
    return json.dumps(
        {
            "AlarmName": name,
            "NewStateValue": state,
            "NewStateReason": reason,
            "StateChangeTime": when.strftime("%Y-%m-%dT%H:%M:%S.000+0000"),
            "Source": "ops-digest-line",
        }
    )


def enqueue_digest_line(
    sns_client: Any,
    name: str,
    reason: str,
    *,
    state: str = NOTICE_STATE,
    dry_run: bool = False,
    topic_arn: Optional[str] = None,
) -> bool:
    """Publish one line to the daily digest. True when it is queued (or a dry run), False on failure.

    A False return is the caller's cue to send the email it would have sent before #5821.
    """
    body = digest_line_payload(name, reason, state=state)
    if dry_run:
        logger.info("DRY-RUN ops digest line not published: %s", body)
        return True
    try:
        sns_client.publish(TopicArn=topic_arn or digest_topic_arn(), Message=body)
    except Exception as e:  # noqa: BLE001 — fail towards delivery: the caller mails instead
        logger.warning("ops digest line publish failed (%s: %s) — the caller falls back to email", type(e).__name__, e)
        return False
    return True
