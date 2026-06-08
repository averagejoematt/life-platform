"""
remediation_dispatcher_lambda.py — ADR-064 urgent-alarm fast path.

Subscribed to the `life-platform-alerts` (urgent) SNS topic. When an alarm fires
with `NewStateValue=ALARM` AND its name matches the URGENT_PATTERNS list, this
Lambda calls GitHub's repository_dispatch API to fire `event_type=urgent_alarm`
on `averagejoematt/life-platform`. The `remediation-agent.yml` workflow accepts
that trigger and runs the remediation agent immediately, closing the urgent-
alarm → triage latency that the daily 07:45 PT sweep otherwise covers.

Routine ingestion-source error alarms are NOT urgent (the daily sweep handles
them); the URGENT_PATTERNS list keeps the firing surface narrow.

Dedupe: a 30-minute window marker is written to
`s3://matthew-life-platform/remediation-log/dispatch-dedupe/{alarm}-{YYYYMMDDHHmm30}.marker`.
A duplicate alarm in the same window is skipped — prevents flap-storms from
chaining workflow runs.

Operator setup (one-time, see RUNBOOK):
  1. Create a fine-grained GitHub PAT, Contents: Read & Write on
     averagejoematt/life-platform only.
  2. `aws secretsmanager create-secret --name life-platform/github-dispatch-token \
        --secret-string '<paste-PAT>' --region us-west-2`

Environment:
  REPO_OWNER          (default: averagejoematt)
  REPO_NAME           (default: life-platform)
  TOKEN_SECRET        (default: life-platform/github-dispatch-token)
  URGENT_PATTERNS     (comma-separated substrings; default below)
  DEDUPE_BUCKET       (default: matthew-life-platform)
  DEDUPE_WINDOW_MIN   (default: 30)
"""

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

import boto3

try:
    from platform_logger import get_logger

    logger = get_logger("remediation-dispatcher")
except ImportError:
    logger = logging.getLogger("remediation-dispatcher")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
REPO_OWNER = os.environ.get("REPO_OWNER", "averagejoematt")
REPO_NAME = os.environ.get("REPO_NAME", "life-platform")
TOKEN_SECRET = os.environ.get("TOKEN_SECRET", "life-platform/github-dispatch-token")
DEDUPE_BUCKET = os.environ.get("DEDUPE_BUCKET", "matthew-life-platform")
DEDUPE_WINDOW_MIN = int(os.environ.get("DEDUPE_WINDOW_MIN", "30"))

# Substrings — match if any is in the alarm name. Narrow on purpose: the daily
# 07:45 PT sweep already handles routine ingestion-source errors / QA smoke /
# freshness — those should NOT fire urgent dispatches and cost a workflow run.
_DEFAULT_PATTERNS = "canary,dlq-depth,site-api-error,budget-tier,bedrock-throttle,slo-"
URGENT_PATTERNS = tuple(p.strip().lower() for p in os.environ.get("URGENT_PATTERNS", _DEFAULT_PATTERNS).split(",") if p.strip())

_sm = boto3.client("secretsmanager", region_name=REGION)
_s3 = boto3.client("s3", region_name=REGION)
_token_cache = None


def _get_token():
    global _token_cache
    if _token_cache:
        return _token_cache
    resp = _sm.get_secret_value(SecretId=TOKEN_SECRET)
    _token_cache = resp["SecretString"].strip()
    return _token_cache


def _is_urgent(alarm_name):
    n = (alarm_name or "").lower()
    return any(p in n for p in URGENT_PATTERNS)


def _dedupe_key(alarm_name):
    now = datetime.now(timezone.utc)
    window = (now.minute // DEDUPE_WINDOW_MIN) * DEDUPE_WINDOW_MIN
    stamp = now.strftime("%Y%m%d%H") + f"{window:02d}"
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in alarm_name)[:80]
    return f"remediation-log/dispatch-dedupe/{safe}-{stamp}.marker"


def _seen(key):
    try:
        _s3.head_object(Bucket=DEDUPE_BUCKET, Key=key)
        return True
    except _s3.exceptions.ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def _mark(key, payload):
    _s3.put_object(Bucket=DEDUPE_BUCKET, Key=key, Body=json.dumps(payload, default=str), ContentType="application/json")


def _dispatch(payload):
    """POST to GitHub repository_dispatch. Raises on non-2xx."""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/dispatches"
    body = json.dumps({"event_type": "urgent_alarm", "client_payload": payload}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {_get_token()}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "life-platform-remediation-dispatcher",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        if not (200 <= resp.status < 300):
            raise RuntimeError(f"GitHub dispatch returned {resp.status}: {resp.read()[:200]}")


def _parse_alarm(sns_message):
    """SNS Message field carries the CloudWatch alarm JSON as a string."""
    try:
        return json.loads(sns_message)
    except (TypeError, ValueError):
        return {"AlarmName": "unparseable", "NewStateReason": (sns_message or "")[:300]}


def lambda_handler(event, context):
    results = {"dispatched": 0, "skipped_filter": 0, "skipped_dedupe": 0, "skipped_state": 0, "errors": 0}
    try:
        for rec in event.get("Records", []):
            try:
                sns = rec.get("Sns", {})
                alarm = _parse_alarm(sns.get("Message", ""))
                name = alarm.get("AlarmName", "")
                state = alarm.get("NewStateValue", "")
                reason = alarm.get("NewStateReason", "")[:500]

                if state != "ALARM":
                    results["skipped_state"] += 1
                    continue
                if not _is_urgent(name):
                    logger.info(f"non-urgent alarm '{name}' — daily sweep will handle")
                    results["skipped_filter"] += 1
                    continue

                key = _dedupe_key(name)
                if _seen(key):
                    logger.info(f"dedupe hit for '{name}' (key={key}) — skipping")
                    results["skipped_dedupe"] += 1
                    continue

                payload = {
                    "alarm_name": name,
                    "state": state,
                    "reason": reason,
                    "timestamp": alarm.get("StateChangeTime") or datetime.now(timezone.utc).isoformat(),
                    "metric": alarm.get("Trigger", {}).get("MetricName"),
                    "namespace": alarm.get("Trigger", {}).get("Namespace"),
                }
                _dispatch(payload)
                _mark(key, payload)
                logger.info(f"dispatched urgent_alarm for '{name}'")
                results["dispatched"] += 1
            except urllib.error.HTTPError as e:
                logger.error(f"GitHub HTTP {e.code}: {e.read()[:200]}")
                results["errors"] += 1
            except Exception as e:
                logger.exception(f"dispatch failed: {e}")
                results["errors"] += 1
    except Exception as e:
        # I4: top-level safety — never raise out of the handler.
        logger.exception(f"handler-level error: {e}")
        results["errors"] += 1

    return {"statusCode": 200, "body": json.dumps(results)}
