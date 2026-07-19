"""
delete_user_data_lambda.py — Phase 7.3 (2026-05-16): right-to-be-forgotten flow.

Purges every record belonging to a user across DynamoDB, S3, and Secrets
Manager. Used for:
  - Subscriber account deletion requests
  - Test user cleanup
  - Compliance with CCPA/GDPR-style data subject rights (P7 prep)

SAFETY:
  - The handler ONLY operates if explicitly invoked with `{"user_id":"...","confirm":"DELETE"}`.
    Both fields required. No default user_id. No partial-delete shortcuts.
  - Hardcoded refusal for `user_id == "matthew"` — the owner account is not
    deletable via this Lambda (would require manual operator action).
  - Returns a dry-run plan if `{"dry_run":true}` — counts what WOULD be deleted
    without actually deleting. Recommended first step.

OUTPUT:
  Lambda response includes:
    - ddb_items_deleted: int
    - s3_objects_deleted: int
    - secrets_deleted: list[name]
    - dry_run: bool
    - completed_at: ISO timestamp
  Audit record written to DDB: USER#admin#SOURCE#deletion_log / DATE#{ts}

SUBSCRIBER DELETION (#1350):
  Subscriber rows live under the OWNER's pk namespace (`USER#{OWNER}#SOURCE#subscribers`,
  sk `EMAIL#{sha256}`) — a shape the generic `user_id` path above structurally cannot
  reach (it scans `USER#{user_id}#*`, and the owner user_id is protected). A single
  subscriber can be deleted on request via a SEPARATE event shape that targets exactly
  one item, never the owner's other partitions:

    {"subscriber_email": "person@example.com", "dry_run": true}     # count-only
    {"subscriber_email": "person@example.com", "confirm": "DELETE"} # actual delete

  This is the right-to-be-forgotten path for an individual subscriber. It is distinct
  from the RETENTION-WINDOW bulk purge/anonymize of already-unsubscribed rows, which is
  `deploy/subscriber_retention_purge.py` (gated on the window Matthew signs into
  docs/DATA_GOVERNANCE.md's "Subscriber emails" retention row — see #1350).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone

import boto3

try:
    from platform_logger import get_logger

    logger = get_logger("delete-user-data")
except ImportError:
    logger = logging.getLogger("delete-user-data")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3", region_name=REGION)
secrets = boto3.client("secretsmanager", region_name=REGION)

# Owner account — refused by the deletion handler.
PROTECTED_USERS = {"matthew", "admin", "system"}

# #1350: subscriber rows live under the OWNER's pk namespace (email_subscriber_lambda.py
# SUBSCRIBERS_PK), not under a per-user pk — kept in sync via the same env var, no
# second hardcoded owner id.
SUBSCRIBERS_OWNER_USER_ID = os.environ.get("USER_ID", "matthew")
SUBSCRIBERS_PK = f"USER#{SUBSCRIBERS_OWNER_USER_ID}#SOURCE#subscribers"


def _scan_user_pks(user_id: str) -> list[dict]:
    """Find all DDB keys belonging to a user. Returns list of {pk, sk}."""
    keys = []
    last_evaluated = None
    while True:
        scan_kwargs = {
            "FilterExpression": "begins_with(pk, :p)",
            "ExpressionAttributeValues": {":p": f"USER#{user_id}#"},
            "ProjectionExpression": "pk,sk",
        }
        if last_evaluated:
            scan_kwargs["ExclusiveStartKey"] = last_evaluated
        resp = table.scan(**scan_kwargs)
        for item in resp.get("Items", []):
            keys.append({"pk": item["pk"], "sk": item["sk"]})
        last_evaluated = resp.get("LastEvaluatedKey")
        if not last_evaluated:
            break
    return keys


def _list_user_s3_objects(user_id: str) -> list[str]:
    """Find all S3 keys under per-user prefixes."""
    prefixes = [f"raw/{user_id}/", f"uploads/{user_id}/", f"dashboard/{user_id}/", f"generated/{user_id}/", f"exports/{user_id}/"]
    keys = []
    for prefix in prefixes:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
    return keys


def _list_user_secrets(user_id: str) -> list[str]:
    """Find per-user secrets at `life-platform/{user_id}/*`."""
    found = []
    paginator = secrets.get_paginator("list_secrets")
    for page in paginator.paginate():
        for s in page.get("SecretList", []):
            name = s.get("Name", "")
            if name.startswith(f"life-platform/{user_id}/"):
                found.append(name)
    return found


def _batch_delete_ddb(keys: list[dict]) -> int:
    """Delete DDB keys in batches of 25 (BatchWriteItem limit)."""
    deleted = 0
    for i in range(0, len(keys), 25):
        batch = keys[i : i + 25]
        request_items = {TABLE_NAME: [{"DeleteRequest": {"Key": k}} for k in batch]}
        resp = dynamodb.batch_write_item(RequestItems=request_items)
        unprocessed = resp.get("UnprocessedItems", {}).get(TABLE_NAME, [])
        deleted += len(batch) - len(unprocessed)
        # Retry unprocessed items (rare; usually transient throttle)
        retries = 0
        while unprocessed and retries < 3:
            time.sleep(0.5 * (retries + 1))
            resp = dynamodb.batch_write_item(RequestItems={TABLE_NAME: unprocessed})
            unprocessed = resp.get("UnprocessedItems", {}).get(TABLE_NAME, [])
            retries += 1
        if unprocessed:
            logger.warning("ddb_batch_delete unprocessed=%d after retries", len(unprocessed))
    return deleted


def _batch_delete_s3(keys: list[str]) -> int:
    """Delete S3 objects in batches of 1000 (DeleteObjects limit)."""
    deleted = 0
    for i in range(0, len(keys), 1000):
        batch = keys[i : i + 1000]
        resp = s3.delete_objects(
            Bucket=S3_BUCKET,
            Delete={"Objects": [{"Key": k} for k in batch]},
        )
        deleted += len(resp.get("Deleted", []))
        errors = resp.get("Errors", [])
        if errors:
            logger.warning("s3_delete errors: %s", errors[:5])
    return deleted


def _delete_secrets(secret_names: list[str]) -> list[str]:
    """Soft-delete with 7-day recovery (matches AWS default)."""
    deleted = []
    for name in secret_names:
        try:
            secrets.delete_secret(SecretId=name, RecoveryWindowInDays=7)
            deleted.append(name)
        except Exception as e:
            logger.warning("secret_delete_failed name=%s err=%s", name, e)
    return deleted


def _subscriber_email_hash(email: str) -> str:
    """SHA256 of lowercased email — MUST match email_subscriber_lambda._email_hash
    exactly (same algorithm, independently reimplemented — no cross-module import
    across the operational/ and web/ trees, so this is deliberately duplicated, not
    shared, to avoid a spurious deploy-time coupling between two independently
    deployed Lambdas)."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def _get_subscriber(email_hash: str) -> dict | None:
    """Look up one subscriber row by email hash. Returns None if absent."""
    try:
        resp = table.get_item(Key={"pk": SUBSCRIBERS_PK, "sk": f"EMAIL#{email_hash}"})
        return resp.get("Item")
    except Exception as e:
        logger.error("subscriber_get_failed: %s", e)
        return None


def _delete_subscriber(email_hash: str) -> None:
    table.delete_item(Key={"pk": SUBSCRIBERS_PK, "sk": f"EMAIL#{email_hash}"})


def _handle_subscriber_deletion(email: str, dry_run: bool, confirmed: bool) -> dict:
    """#1350: right-to-be-forgotten for ONE subscriber. Never touches any other
    partition — a narrow single-item delete, unlike the broad `user_id` scan path."""
    if not dry_run and not confirmed:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Either dry_run=true OR confirm='DELETE' is required"}),
        }

    email_hash = _subscriber_email_hash(email)
    record = _get_subscriber(email_hash)

    plan = {
        "subscriber_email_hash": email_hash[:8] + "…",  # never echo the hash in full, never the plaintext email
        "found": record is not None,
        "status": record.get("status") if record else None,
        "dry_run": dry_run,
    }

    if dry_run:
        return {"statusCode": 200, "body": json.dumps({"plan": plan})}

    if record is None:
        return {"statusCode": 200, "body": json.dumps({"plan": plan, "note": "no matching subscriber row; nothing to delete"})}

    _delete_subscriber(email_hash)
    summary = {
        "subscriber_email_hash": email_hash[:8] + "…",
        "deleted": True,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    # Audit by hash prefix only — the audit trail must never hold the plaintext email.
    _write_audit_record(f"subscriber:{email_hash[:8]}", summary)
    logger.info("subscriber_deletion_complete hash=%s", email_hash[:8])
    return {"statusCode": 200, "body": json.dumps(summary)}


def _write_audit_record(user_id: str, summary: dict) -> None:
    """Audit log: a non-deletable record of every deletion event."""
    now = datetime.now(timezone.utc)
    try:
        table.put_item(
            Item={
                "pk": "USER#admin#SOURCE#deletion_log",
                "sk": f"DATE#{now.isoformat()}#USER#{user_id}",
                "user_id": user_id,
                "completed_at": now.isoformat(),
                "summary": json.dumps(summary, default=str),
            }
        )
    except Exception as e:
        logger.error("audit_write_failed: %s", e)


def lambda_handler(event: dict, context) -> dict:
    """Phase 7.3 — delete a user's data. Required event shape:

        {"user_id": "<id>", "confirm": "DELETE"}            # actual delete
        {"user_id": "<id>", "dry_run": true}                # count-only

    Returns counts + audit metadata. Refuses on protected users or missing confirm.
    """
    try:
        # #1350: a distinct, narrower path for a single subscriber — never routes
        # through the user_id/PROTECTED_USERS logic below (subscriber rows live
        # under the OWNER's pk namespace, so they can never be reached that way).
        subscriber_email = event.get("subscriber_email")
        if subscriber_email:
            return _handle_subscriber_deletion(
                subscriber_email,
                dry_run=bool(event.get("dry_run")),
                confirmed=event.get("confirm") == "DELETE",
            )

        user_id = event.get("user_id")
        if not user_id:
            return {"statusCode": 400, "body": json.dumps({"error": "user_id required"})}

        if user_id in PROTECTED_USERS:
            return {
                "statusCode": 403,
                "body": json.dumps(
                    {
                        "error": f"user_id {user_id!r} is protected; manual operator action required",
                    }
                ),
            }

        dry_run = bool(event.get("dry_run"))
        confirmed = event.get("confirm") == "DELETE"

        if not dry_run and not confirmed:
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {
                        "error": "Either dry_run=true OR confirm='DELETE' is required",
                    }
                ),
            }

        logger.info("deletion_start user=%s dry_run=%s", user_id, dry_run)

        # Plan: enumerate everything that would be deleted.
        ddb_keys = _scan_user_pks(user_id)
        s3_keys = _list_user_s3_objects(user_id)
        secret_names = _list_user_secrets(user_id)

        plan = {
            "user_id": user_id,
            "ddb_items": len(ddb_keys),
            "s3_objects": len(s3_keys),
            "secrets": len(secret_names),
            "dry_run": dry_run,
        }

        if dry_run:
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "plan": plan,
                        "ddb_sample_keys": ddb_keys[:5],
                        "s3_sample_keys": s3_keys[:5],
                        "secret_names": secret_names,
                    }
                ),
            }

        # Execute deletion.
        ddb_deleted = _batch_delete_ddb(ddb_keys)
        s3_deleted = _batch_delete_s3(s3_keys)
        secrets_deleted = _delete_secrets(secret_names)

        summary = {
            "user_id": user_id,
            "ddb_items_deleted": ddb_deleted,
            "s3_objects_deleted": s3_deleted,
            "secrets_deleted": secrets_deleted,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_audit_record(user_id, summary)
        logger.info("deletion_complete %s", summary)
        return {"statusCode": 200, "body": json.dumps(summary)}
    except Exception as e:
        logger.error("delete_user_data_failed: %s", e, exc_info=True)
        raise
