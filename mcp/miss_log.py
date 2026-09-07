"""mcp/miss_log.py — the durable record of a question the platform could not answer (#3668).

WHY
---
The cycle-number question that opened #3668 **left no trace at all**. It was asked, no
surface answered it, and the platform never learned it had been wanted. That is not a
missing feature; it is a measurement defect of the same class as everything else in this
backlog — an instrument that cannot tell "no" from "never asked".

It also inverts the ratchet. ``docs/MCP_TOOL_AUDIT.md`` governs REMOVALS against
invocation telemetry: it measures what was USED and is structurally silent on what was
WANTED. Absence of invocation is equally consistent with "unwanted", "unfindable" and
"the owner never reached the stage of a cycle where it applies" — and the #395 prune's
30-day window sat inside a period the owner describes as BUILDING the platform rather
than using it. A miss log measures demand directly, so the next expand-or-prune decision
can rest on evidence the prune's telemetry could never have carried.

WHERE
-----
One JSON object per miss, under the existing append-only prefix::

    mcp-audit/misses/YYYY/MM/DD/HHMMSS-<uuid8>.json

Deliberately INSIDE ``mcp-audit/`` rather than a new prefix: the MCP role already holds
``s3:PutObject`` (and only PutObject) there, and ``deploy/bucket_policy.json``'s
``ProtectDataFromDeployScripts`` Deny already covers it — so the log is append-only and
delete-protected on day one, with no IAM change and no new bucket-policy row to forget.

FAIL-OPEN, always
-----------------
``record_miss()`` never raises and never blocks. A miss log that can break a tool call is
worse than no miss log: it would turn "I could not answer that" into "the platform is
down". The S3 client uses tight timeouts and a single attempt, exactly like
``mcp/audit.py``'s trail, and a write failure is logged and swallowed.

WHAT IS RECORDED
----------------
The QUESTION, not the answer — there is no answer. The requested surface name, the
params, the caller's own phrasing when it supplied one, the reason no surface matched,
and the closest indexed names. No free-text health data is involved: a miss is by
definition a request that never reached a partition.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from mcp.config import S3_BUCKET, logger

MISS_PREFIX = "mcp-audit/misses"

# Why nothing answered. A closed vocabulary so the log is countable, not just readable.
REASON_NO_SUCH_SURFACE = "no_such_surface"  # the name is not in the derived index at all
REASON_READER_ONLY = "reader_only_surface"  # indexed, deliberately excluded, reason on record
REASON_SURFACE_ERROR = "surface_errored"  # indexed and reachable, but the handler failed
REASON_UNROUTED = "surface_unrouted"  # the router returned no response for the path
REASON_UNANSWERED_QUESTION = "unanswered_question"  # a caller-declared miss with no candidate surface

VALID_REASONS = frozenset(
    {
        REASON_NO_SUCH_SURFACE,
        REASON_READER_ONLY,
        REASON_SURFACE_ERROR,
        REASON_UNROUTED,
        REASON_UNANSWERED_QUESTION,
    }
)


def _client():
    """A short-timeout, single-attempt S3 client (the mcp/audit.py posture)."""
    import boto3
    from botocore.config import Config

    from mcp.config import _REGION  # noqa: PLC0415 — lazy so import order never matters

    return boto3.client(
        "s3",
        region_name=_REGION,
        config=Config(connect_timeout=1.5, read_timeout=2.0, retries={"max_attempts": 1}),
    )


def build_record(
    *, reason: str, asked_for: str = "", question: str = "", params: dict | None = None, near_misses=None, detail: str = ""
) -> dict:
    """The record shape — pure, so a test can assert it without touching S3."""
    now = datetime.now(timezone.utc)
    return {
        "schema": "mcp-miss/v1",
        "issue": 3668,
        "recorded_at": now.isoformat().replace("+00:00", "Z"),
        # An unrecognised reason is STORED, never dropped and never coerced to a known
        # one: a miss log that silently reclassifies is the instrument this fixes.
        "reason": reason if reason in VALID_REASONS else "other",
        "reason_raw": reason,
        "asked_for": str(asked_for or "")[:200],
        "question": str(question or "")[:500],
        "params": {str(k)[:60]: str(v)[:200] for k, v in (params or {}).items()},
        "near_misses": [str(n)[:80] for n in (near_misses or [])][:10],
        "detail": str(detail or "")[:500],
    }


def record_miss(
    *, reason: str, asked_for: str = "", question: str = "", params: dict | None = None, near_misses=None, detail: str = ""
) -> dict | None:
    """Write one miss record. NEVER raises; returns the record written, or None.

    The return value is what a caller echoes back to the model ("this was recorded"), so
    an honest tool response can say the question was captured rather than pretending it
    was answered.
    """
    record = build_record(reason=reason, asked_for=asked_for, question=question, params=params, near_misses=near_misses, detail=detail)
    try:
        now = datetime.now(timezone.utc)
        key = f"{MISS_PREFIX}/{now:%Y/%m/%d}/{now:%H%M%S}-{uuid.uuid4().hex[:8]}.json"
        _client().put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=json.dumps(record, sort_keys=True).encode("utf-8"),
            ContentType="application/json",
        )
        record["_key"] = key
        logger.info(f"[#3668] miss recorded: {record['reason']} asked_for={record['asked_for']!r} -> s3://{S3_BUCKET}/{key}")
    except Exception as e:  # noqa: BLE001 — FAIL-OPEN by contract; see module docstring
        logger.warning(f"[#3668] miss log write failed ({e}) — the miss is reported to the caller but NOT durable")
        record["_key"] = None
        record["_durable"] = False
    else:
        record["_durable"] = True
    return record
