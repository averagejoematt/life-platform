"""The HAE webhook's bearer-token lookup — a cohesive sibling of `health_auto_export_lambda.py`.

#5513 (c): the internet-facing webhook read its token out of the shared bundle
`life-platform/ingestion-keys`, which also holds the notion, todoist, habitify and dropbox
keys, so a leaked webhook role could read five services' credentials. The token now lives in
its own Secrets Manager secret, `life-platform/hae-webhook`, JSON `{"health_auto_export_api_key": "<token>"}`
(the same field name the bundle uses, so the owner copies the value without reshaping it).

The cutover is zero-downtime, in this order: the dedicated secret is read first; if it does not
exist yet, the role cannot read it yet (the CDK grant not deployed), it is unparseable or it
lacks the field, the lookup falls back to the bundle key exactly as before. Every lookup logs
which source answered (`hae_auth_key_source source=dedicated|bundle`), never the value. A
failed dedicated read is not retried for 15 minutes, the same window as the value cache.

The fallback and the bundle grant are TEMPORARY. Once CloudWatch shows `source=dedicated`, the
follow-up removes both (and the bundle's health_auto_export field); until then the role reads
both secrets. Moved out of the webhook module because that file is at its #1665 size ceiling.
"""

import json
import logging
import os
import time

import boto3
from common.secret_cache import get_secret

try:
    from common.platform_logger import get_logger

    logger = get_logger("health-auto-export")
except ImportError:
    logger = logging.getLogger("health-auto-export")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
# The dedicated secret: owner-provisioned (#5513), granted by role_policies_ingestion.ingestion_hae.
DEDICATED_SECRET_NAME = "life-platform/hae-webhook"  # noqa: S105 — a secret NAME, not a credential
# The COST-B bundle, read only as the cutover fallback until the follow-up removes it.
SECRET_NAME = os.environ.get("SECRET_NAME", "life-platform/ingestion-keys")
KEY_FIELD = "health_auto_export_api_key"
_DEDICATED_RETRY_SECONDS = 900  # the secret_cache TTL — a missing secret is re-tried once per window

secrets_client = boto3.client("secretsmanager", region_name=REGION)
_dedicated_retry_at = 0.0


def _failure_reason(exc):
    """A log-safe reason: the AWS error code or the exception class, never its message."""
    response = getattr(exc, "response", None)
    code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
    return code or type(exc).__name__


def get_api_key():
    """The expected bearer token: the dedicated secret first, the bundle as the fallback.

    Raises only when the bundle read itself fails, which the handler already answers with 500;
    a bundle without the field returns None, which the handler answers with 403.
    """
    global _dedicated_retry_at
    if time.time() >= _dedicated_retry_at:
        try:
            key = json.loads(get_secret(DEDICATED_SECRET_NAME, secrets_client)).get(KEY_FIELD)
            reason = "key_missing"
        except Exception as exc:  # noqa: BLE001 — any dedicated failure falls back to the bundle
            key, reason = None, _failure_reason(exc)
        if key:
            logger.info("hae_auth_key_source source=dedicated secret=%s", DEDICATED_SECRET_NAME)
            return key
        _dedicated_retry_at = time.time() + _DEDICATED_RETRY_SECONDS
        logger.warning("hae_auth_key_fallback secret=%s reason=%s retry_in_s=%d", DEDICATED_SECRET_NAME, reason, _DEDICATED_RETRY_SECONDS)
    secret = json.loads(get_secret(SECRET_NAME, secrets_client))
    logger.info("hae_auth_key_source source=bundle secret=%s", SECRET_NAME)
    return secret.get(KEY_FIELD) or secret.get("api_key")
