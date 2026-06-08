"""
hevy_webhook_lambda.py — Real-time Hevy workout ingestion via webhook POST.

Per SPEC_HEVY_AND_NUTRITION_BRIDGE_2026_05_25 §2.2-A:
    Hevy workout completed
      → Hevy webhook POST
        → this Lambda (FunctionURL, unauthenticated, secret-validated)
          → validate webhook secret/signature against life-platform/hevy
          → fetch full workout via GET /v1/workouts/{id} (authoritative read)
          → normalize → DDB upsert + raw archive to S3

Important: the webhook body's workout content is NOT trusted. We extract the
workout id (and only the id), then fetch the canonical record via the
authenticated API. This is per spec §2.5 — never trust webhook body as source.

Region: us-west-2
FunctionURL: created by CDK in operational_stack (see add_hevy_function_url).
Auth: NONE (open URL). Protection = mandatory webhook_secret header match.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from hevy_common import (
    HevyAPIError,
    archive_raw,
    fetch_workout,
    normalize_workout,
    verify_webhook_signature,
    write_normalized,
)

try:
    from platform_logger import get_logger

    logger = get_logger("hevy-webhook")
except ImportError:
    logger = logging.getLogger("hevy-webhook")
    logger.setLevel(logging.INFO)


# Header names we'll accept the signature/secret under. Adjust once Hevy's
# actual webhook header is known.
_SIG_HEADERS = (
    "x-hevy-webhook-secret",
    "x-hevy-signature",
    "x-webhook-signature",
    "x-signature",
)


def _response(status: int, body: dict | str) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": body if isinstance(body, str) else json.dumps(body),
    }


def _get_header(event: dict, name: str) -> str | None:
    """Case-insensitive header lookup for both API Gateway and FunctionURL events."""
    headers = event.get("headers") or {}
    name_lower = name.lower()
    for k, v in headers.items():
        if k.lower() == name_lower:
            return v
    return None


def _extract_workout_id(payload: dict) -> str | None:
    """Extract a workout id from Hevy's webhook payload.

    Hevy's documented webhook payloads typically include either `workout_id`,
    `workoutId`, or a `workout: {id: ...}` nested object. Be liberal in
    parsing; verify against real payloads and tighten once the shape is known.
    """
    if not isinstance(payload, dict):
        return None
    # Top-level
    for k in ("workoutId", "workout_id", "id"):
        if k in payload and payload[k]:
            return str(payload[k])
    # Nested under `workout` or `data`
    for nest in ("workout", "data"):
        sub = payload.get(nest)
        if isinstance(sub, dict):
            for k in ("workoutId", "workout_id", "id"):
                if k in sub and sub[k]:
                    return str(sub[k])
    return None


def lambda_handler(event: dict, context: Any) -> dict:
    """Handle a Hevy webhook POST.

    Response codes:
        200 — success (workout ingested, or already-known dedupe)
        202 — accepted but no-op (event type we don't process)
        400 — malformed body / missing id
        401 — signature/secret missing or invalid
        500 — Hevy API call failed (will retry on next backfill run)
    """
    # ── 1. Read body ───────────────────────────────────────────────
    raw_body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        try:
            raw_body = base64.b64decode(raw_body)
        except Exception:
            return _response(400, {"error": "invalid base64 body"})
    body_bytes = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body

    # ── 2. Validate webhook auth ───────────────────────────────────
    provided: str | None = None
    for hname in _SIG_HEADERS:
        provided = _get_header(event, hname)
        if provided:
            break
    if not provided:
        logger.warning("hevy webhook missing signature header")
        return _response(401, {"error": "missing signature"})
    if not verify_webhook_signature(body_bytes, provided):
        logger.warning("hevy webhook signature mismatch")
        return _response(401, {"error": "invalid signature"})

    # ── 3. Parse JSON ─────────────────────────────────────────────
    try:
        payload = json.loads(body_bytes.decode("utf-8") if isinstance(body_bytes, bytes) else body_bytes)
    except Exception as e:
        logger.warning("hevy webhook JSON parse failed: %s", e)
        return _response(400, {"error": "invalid JSON"})

    # ── 4. Extract workout id ─────────────────────────────────────
    workout_id = _extract_workout_id(payload)
    if not workout_id:
        # Some webhook event types don't carry a workout id (e.g. account
        # updated). Accept but no-op.
        event_type = payload.get("event") or payload.get("type") or "unknown"
        logger.info("hevy webhook no workout id, event_type=%s — no-op", event_type)
        return _response(202, {"status": "no-op", "event_type": event_type})

    # ── 5. Fetch authoritative workout + persist ──────────────────
    try:
        raw = fetch_workout(workout_id)
        archive_raw(workout_id, raw)
        record = normalize_workout(raw)
        write_normalized(record)
    except HevyAPIError as e:
        logger.error("hevy fetch failed for %s: %s", workout_id, e)
        # 500 → Hevy may retry; the next scheduled backfill will also catch it
        return _response(500, {"error": "hevy api error", "workout_id": workout_id})
    except Exception as e:
        logger.exception("hevy webhook unhandled error for %s: %s", workout_id, e)
        return _response(500, {"error": "internal", "workout_id": workout_id})

    return _response(
        200,
        {
            "status": "ingested",
            "workout_id": workout_id,
            "date": record["date"],
            "set_count": record["set_count"],
            "total_volume_kg": record["total_volume_kg"],
        },
    )
