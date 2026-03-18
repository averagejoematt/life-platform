"""
Secrets Manager rotation Lambda for life-platform MCP API key.

Generates a cryptographically secure random API key every 90 days.
Follows the Secrets Manager 4-step rotation protocol:
  createSecret → setSecret → testSecret → finishSecret

After rotation completes:
- MCP Lambda picks up the new key within 5 min (Bearer cache TTL)
- Remote MCP (Claude connector): re-authenticates via OAuth on next 401
- Bridge (.config.json): run `aws secretsmanager get-secret-value` to get new key
"""
import json
import logging
import secrets
import base64
import boto3

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger
    logger = get_logger("key-rotator")
except ImportError:
    logger = logging.getLogger("key-rotator")
    logger.setLevel(logging.INFO)

sm = boto3.client("secretsmanager")


def _generate_api_key(length: int = 32) -> str:
    """Generate a URL-safe random API key (44 chars from 32 bytes)."""
    return base64.urlsafe_b64encode(secrets.token_bytes(length)).decode().rstrip("=")


def create_secret(secret_id: str, client_request_token: str):
    """Step 1: Generate a new secret and store it as AWSPENDING."""
    # Check if AWSPENDING already exists (idempotency)
    try:
        sm.get_secret_value(SecretId=secret_id, VersionStage="AWSPENDING",
                            VersionId=client_request_token)
        logger.info("createSecret: AWSPENDING already exists, skipping.")
        return
    except sm.exceptions.ResourceNotFoundException:
        pass  # Expected — no pending version yet

    new_key = _generate_api_key()
    logger.info(f"createSecret: Generated new API key ({len(new_key)} chars)")

    sm.put_secret_value(
        SecretId=secret_id,
        ClientRequestToken=client_request_token,
        SecretString=new_key,
        VersionStages=["AWSPENDING"],
    )
    logger.info("createSecret: Stored AWSPENDING version")


def set_secret(secret_id: str, client_request_token: str):
    """Step 2: No external system to update — API key is only in Secrets Manager."""
    logger.info("setSecret: No-op (no external system to update)")


def test_secret(secret_id: str, client_request_token: str):
    """Step 3: Verify the pending secret can be retrieved."""
    resp = sm.get_secret_value(SecretId=secret_id, VersionStage="AWSPENDING",
                               VersionId=client_request_token)
    new_key = resp["SecretString"]

    # Basic sanity: non-empty, reasonable length
    if not new_key or len(new_key) < 20:
        raise ValueError(f"testSecret: Invalid key (length={len(new_key)})")

    logger.info(f"testSecret: Pending key validated ({len(new_key)} chars)")


def finish_secret(secret_id: str, client_request_token: str):
    """Step 4: Promote AWSPENDING → AWSCURRENT."""
    # Find the current version to demote
    metadata = sm.describe_secret(SecretId=secret_id)
    for version_id, stages in metadata.get("VersionIdsToStages", {}).items():
        if "AWSCURRENT" in stages and version_id != client_request_token:
            # Demote old current → previous
            sm.update_secret_version_stage(
                SecretId=secret_id,
                VersionStage="AWSCURRENT",
                MoveToVersionId=client_request_token,
                RemoveFromVersionId=version_id,
            )
            logger.info(f"finishSecret: Promoted {client_request_token[:8]}... to AWSCURRENT, "
                        f"demoted {version_id[:8]}... to AWSPREVIOUS")
            return

    # If we get here, the pending version is somehow already current
    logger.info("finishSecret: Pending version already has AWSCURRENT stage")


# ── Lambda handler ────────────────────────────────────────────────────────────
STEPS = {
    "createSecret": create_secret,
    "setSecret":    set_secret,
    "testSecret":   test_secret,
    "finishSecret": finish_secret,
}


def lambda_handler(event, context):
    try:
        secret_id = event["SecretId"]
        client_request_token = event["ClientRequestToken"]
        step = event["Step"]

        logger.info(f"[key-rotator] Step={step}, SecretId={secret_id}, Token={client_request_token[:8]}...")

        # Verify the secret exists and rotation is enabled
        metadata = sm.describe_secret(SecretId=secret_id)
        if not metadata.get("RotationEnabled"):
            raise ValueError(f"Rotation is not enabled for secret {secret_id}")

        # Verify the version is in the right state
        versions = metadata.get("VersionIdsToStages", {})
        if client_request_token not in versions:
            raise ValueError(f"Secret version {client_request_token} has no stage for rotation")

        handler = STEPS.get(step)
        if not handler:
            raise ValueError(f"Unknown rotation step: {step}")

        handler(secret_id, client_request_token)
        logger.info(f"[key-rotator] Step={step} completed successfully")
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
