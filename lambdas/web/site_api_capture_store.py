"""lambdas/web/site_api_capture_store.py — the one conditional write behind the
moderated S3 capture doors (`/api/submit_finding`, `/api/board_question`), #3118.

DIL-025's census found both doors content-addressed but filed under a WALL-CLOCK
prefix (``{YYYY-MM-DD}_{id}.json`` / ``{YYYY-MM}_{id}.json``) with an
unconditional ``put_object``. Two consequences, both reader- and owner-visible:

  1. a retry that crossed the UTC day (or month) boundary landed on a SECOND key,
     so the moderation queue grew a duplicate of an item already triaged; and
  2. worse, a replay of an item Matthew had already moderated **reset ``status``
     back to ``"pending"``**, silently undoing the moderation decision.

The in-repo model for the fix was one file over: ``/api/experiment_suggest`` is
content-addressed AND conditional (``attribute_not_exists(sk)``), so a replay is a
true no-op returning ``duplicate: true``. This is that pattern for S3 — the key
is now the content hash ALONE (no clock in it, so no boundary to cross) and the
write carries ``IfNoneMatch="*"``, S3's native conditional put, which is the exact
analogue of ``attribute_not_exists``.

FAIL-OPEN, deliberately: a capture door losing a reader's submission is worse than
a duplicate pending row. If the runtime's botocore predates ``IfNoneMatch`` the
call is retried unconditionally (with a HEAD first so the common case is still a
no-op), and any *other* S3 error is re-raised for the caller's existing 503 path.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger()

# botocore surfaces the 412 as a ClientError with this code; the raw HTTP status
# is checked too because the modelled name has varied across botocore releases.
_PRECONDITION_CODES = {"PreconditionFailed", "ConditionalRequestConflict"}


def _is_precondition_failure(exc: Exception) -> bool:
    resp = getattr(exc, "response", None)
    if not isinstance(resp, dict):
        return False
    code = str((resp.get("Error") or {}).get("Code") or "")
    status = (resp.get("ResponseMetadata") or {}).get("HTTPStatusCode")
    return code in _PRECONDITION_CODES or status == 412


def _is_unsupported_param(exc: Exception) -> bool:
    """An older botocore rejects the unknown kwarg at parameter-validation time,
    before any HTTP call. That is a client-library gap, never a duplicate."""
    return "IfNoneMatch" in str(exc) and exc.__class__.__name__ in {
        "ParamValidationError",
        "TypeError",
    }


def put_capture_record(s3_client: Any, bucket: str, key: str, record: Dict[str, Any], body: str, *, door: str) -> bool:
    """Store one moderated-queue record at a content-addressed key, once.

    Returns True when this call created the object, False when an object was
    already there (a replay) — in which case NOTHING is written, so whatever
    moderation state the stored copy carries survives untouched. Any S3 error
    other than the precondition failure propagates to the caller.
    """
    try:
        s3_client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json", IfNoneMatch="*")
        return True
    except Exception as e:  # noqa: BLE001 — classified below, unknown shapes re-raise
        if _is_precondition_failure(e):
            logger.info(f"[{door}] replay of {record.get('id')} — existing object left intact at {key}")
            return False
        if not _is_unsupported_param(e):
            raise
    # Fail-open path: no conditional put available. HEAD first so an already-stored
    # (possibly already-moderated) object is still left alone; on any doubt, write.
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        logger.info(f"[{door}] replay of {record.get('id')} — conditional put unavailable, HEAD found {key}")
        return False
    except Exception:  # noqa: BLE001 — absent, or HEAD unavailable: write and accept the overwrite
        pass
    s3_client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")
    return True
