"""
mcp/audit.py — MCP write-audit trail (#753).

The MCP server is an authenticated write path into the life record
(log_*/update_*/delete_*/create_*/manage_*/…) from any connected Claude
session. A compromised session could poison the historical record and,
before this module, no mutation trail existed.

Every mutating tool call is recorded — tool name, SHA-256 of the
canonicalized arguments (never the raw args: journal text, memory contents
etc. stay out of the trail), UTC timestamp, result status, duration — as one
JSON object per call under the append-only S3 prefix:

    mcp-audit/YYYY/MM/DD/HHMMSS-<tool>-<uuid8>.json

The tool name is embedded in the KEY so consumers (the weekly digest line)
can aggregate with s3:ListBucket alone — no GetObject required.

Design rules:
  * FAIL-OPEN — an audit failure must NEVER block, fail, or delay the actual
    tool call. record_mutation() never raises; the S3 client uses tight
    connect/read timeouts and a single attempt so a wedged S3 endpoint cannot
    stall the MCP response. The audit failure itself is logged.
  * CENTRAL CLASSIFICATION — write-vs-read is derived from the tool-name verb
    (the first `_`-separated token). The registry has no per-tool facet for
    this, and the naming convention is total over all 142 tools, so the verb
    rule is the cleanest single source. tests/test_mcp_audit.py asserts every
    registered tool's verb is explicitly classified — a new verb fails CI
    until it is added to exactly one set below. At runtime an UNKNOWN verb is
    treated as a write (over-audit rather than silently miss a mutation).
  * APPEND-ONLY — the bucket-policy `ProtectDataFromDeployScripts` Deny
    (ADR-032/033/046, deploy/bucket_policy.json) covers mcp-audit/*, and the
    MCP role gets s3:PutObject only (no Delete) on the prefix.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from mcp.config import S3_BUCKET, logger

AUDIT_PREFIX = "mcp-audit"

# Verbs that mutate the life record (or an external system: Todoist, Hevy).
# Fat tools (manage_*) are classified write even though some of their actions
# are reads — over-inclusive by design for an audit trail.
WRITE_VERBS = frozenset(
    {
        "activate",
        "annotate",
        "capture",
        "checkin",
        "close",
        "complete",
        "create",
        "delete",
        "end",
        "evaluate",
        "log",
        "manage",
        "retire",
        "save",
        "set",
        "update",
        "write",
    }
)

# Verbs that only read.
READ_VERBS = frozenset(
    {
        "compare",
        "find",
        "get",
        "list",
        "read",
        "search",
    }
)


def classify_verb(tool_name: str) -> str:
    """The classification token: the first `_`-separated word of the tool name."""
    return tool_name.split("_", 1)[0]


def is_write_tool(tool_name: str) -> bool:
    """Central write/read classification for the dispatch path.

    Unknown verbs classify as WRITE (fail-safe: an unclassified mutation gets
    audited; an unclassified read costs one harmless extra S3 object). The
    coverage test keeps unknown verbs out of the registry in practice.
    """
    return classify_verb(tool_name) not in READ_VERBS


def args_hash(arguments: dict | None) -> str:
    """Deterministic SHA-256 of the canonicalized tool arguments.

    Canonical form: JSON with sorted keys, no whitespace, non-JSON types via
    str(). Key order and formatting never change the hash; any value change
    does. The raw arguments are never stored — the hash proves what was sent
    without leaking journal text / memory contents into the trail.
    """
    canonical = json.dumps(arguments or {}, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_S3_CLIENT = None


def _audit_s3():
    """Lazy S3 client with tight timeouts + one attempt (fail-open, never stall)."""
    global _S3_CLIENT
    if _S3_CLIENT is None:
        import os

        import boto3
        from botocore.config import Config

        _S3_CLIENT = boto3.client(
            "s3",
            region_name=os.environ.get("AWS_REGION", "us-west-2"),
            config=Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 1}),
        )
    return _S3_CLIENT


def record_mutation(tool_name: str, arguments: dict | None, status: str, duration_ms: float | None = None) -> None:
    """Append one audit record to S3. NEVER raises (fail-open by contract).

    status: "success" | "error" | "timeout" (timeout = the write may or may
    not have landed — recorded precisely because it is ambiguous).
    """
    try:
        now = datetime.now(timezone.utc)
        record = {
            "tool": tool_name,
            "args_sha256": args_hash(arguments),
            "timestamp": now.isoformat(),
            "status": status,
        }
        if duration_ms is not None:
            record["duration_ms"] = round(duration_ms, 1)
        key = f"{AUDIT_PREFIX}/{now:%Y/%m/%d}/{now:%H%M%S}-{tool_name}-{uuid.uuid4().hex[:8]}.json"
        _audit_s3().put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=json.dumps(record),
            ContentType="application/json",
        )
    except Exception as e:  # noqa: BLE001 — fail-open is the contract (#753)
        try:
            logger.warning(f"[#753] MCP audit write failed for '{tool_name}' (tool call unaffected): {e}")
        except Exception:
            pass
