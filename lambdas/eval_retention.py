"""eval_retention.py — retain the honesty layer's own eval dataset (#812, minimal #744).

Every ADR-104 gate verdict and regeneration pair used to be a log line and then
gone — the AI Practitioner blind spot from R21 (#744): the platform generates
labeled eval data (a draft the gate flagged + the findings that flagged it + the
corrected/refused final) and throws it away. This module is the minimal retention
that the #812 harvest loop consumes: when a grounding gate FIRES on any surface,
the pair is persisted to DynamoDB so `scripts/harvest_eval_fixtures.py` can turn
it into new golden/canary candidates for the per-surface eval packs
(`tests/fixtures/golden_surfaces/`).

Design:
- Records live at pk `EVALRET#<surface>`, sk `TS#<utc-iso>#<uuid8>` — registered
  CROSS_PHASE in `phase_taxonomy.py` (same rationale as VOICEFIDELITY#: this
  measures the honesty MACHINERY's behavior, not a property of the current
  experiment run) with a belt-and-braces TTL (~180 days) because the harvest
  consumes recent months and the dataset regrows continuously.
- Only FLAGGED events are retained (the gate fires rarely); clean passes are
  already persisted by each surface's own record (board interactions, chronicle
  installments, SoM briefs, field notes) and need no second copy.
- The payload is stored as ONE JSON string field — no float→Decimal dance, and
  the harvest reads it back with plain json.loads.
- `retain()` is FAIL-SOFT by contract: it must never raise into a generation
  path. A retention failure costs one log line, never a reader-facing surface.

Writer IAM: the compute/email/intelligence surface roles already hold table-wide
PutItem; site-api-ai is LeadingKeys-scoped and gets an `EVALRET#*` PutItem grant
in `cdk/stacks/role_policies.py::site_api_ai`.
"""

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

logger = logging.getLogger()

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
PK_PREFIX = "EVALRET#"
RECORD_TYPE = "eval_retention"
TTL_DAYS = 180

# The five reader-facing surfaces the ADR-104 gate protects (#812). Kept as a
# tuple so the harvest and the tests iterate one canonical list.
SURFACES = ("board_ask", "chronicle", "memoir", "state_of_matthew", "field_notes")

_TEXT_CAP = 6000  # chars per retained draft/final — plenty for any surface
_ALLOWED_CAP = 500  # distinct numbers kept from the allow-list

_table = None


def _get_table():
    global _table
    if _table is None:
        import boto3

        _table = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-west-2")).Table(TABLE_NAME)
    return _table


def build_record(surface, verdict, draft=None, final=None, findings=None, allowed=None, facts=None, extra=None, now=None):
    """Pure: the DDB item for one retained gate event. Split from retain() so the
    shape is unit-testable without AWS."""
    if surface not in SURFACES:
        raise ValueError(f"unknown surface {surface!r} (known: {SURFACES})")
    now = now or datetime.now(timezone.utc)
    payload = {
        "surface": surface,
        "verdict": verdict,
        "draft": (draft or "")[:_TEXT_CAP],
        "final": (final or "")[:_TEXT_CAP],
        # findings may contain floats — they live inside the JSON string, so no
        # Decimal conversion is ever needed.
        "findings": findings or [],
        "allowed": sorted(float(x) for x in (allowed or set()))[:_ALLOWED_CAP],
        "facts": facts,
        "extra": extra or {},
    }
    return {
        "pk": f"{PK_PREFIX}{surface}",
        "sk": f"TS#{now.isoformat()}#{uuid.uuid4().hex[:8]}",
        "record_type": RECORD_TYPE,
        "surface": surface,
        "verdict": verdict,
        "created_at": now.isoformat(),
        "ttl": int(time.time()) + TTL_DAYS * 86400,
        "payload_json": json.dumps(payload, default=str),
    }


def retain(surface, verdict, draft=None, final=None, findings=None, allowed=None, facts=None, extra=None):
    """Persist one flagged gate event. FAIL-SOFT: never raises, returns bool.

    verdict ∈ {"flagged_corrected", "flagged_refused", "flagged_kept_best",
    "flagged_fallback", "flagged_dropped"} — how the surface disposed of the flag.
    """
    try:
        item = build_record(surface, verdict, draft=draft, final=final, findings=findings, allowed=allowed, facts=facts, extra=extra)
        _get_table().put_item(Item=item)
        return True
    except Exception as e:  # noqa: BLE001 — retention is never load-bearing
        logger.warning(f"[eval_retention] retain({surface}) failed (non-fatal): {e}")
        return False


def fetch(surface, since_days=35, limit=200):
    """Read back retained events for one surface (newest first), payloads parsed.

    Used by the harvest loop (read-only role: dynamodb:Query LeadingKeys EVALRET#*).
    Raises on AWS errors — the harvest wants loud failures, unlike retain()."""
    from boto3.dynamodb.conditions import Key

    cutoff = datetime.now(timezone.utc).timestamp() - since_days * 86400
    resp = _get_table().query(
        KeyConditionExpression=Key("pk").eq(f"{PK_PREFIX}{surface}"),
        ScanIndexForward=False,
        Limit=limit,
    )
    out = []
    for item in resp.get("Items", []):
        try:
            created = datetime.fromisoformat(item["created_at"]).timestamp()
            if created < cutoff:
                continue
            payload = json.loads(item["payload_json"])
            payload["_sk"] = item["sk"]
            payload["_created_at"] = item["created_at"]
            out.append(payload)
        except Exception as e:  # noqa: BLE001 — one bad record must not sink the harvest
            logger.warning(f"[eval_retention] skipping unparseable record {item.get('sk')}: {e}")
    return out
