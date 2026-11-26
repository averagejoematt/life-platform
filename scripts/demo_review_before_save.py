#!/usr/bin/env python3
"""demo_review_before_save.py — #6287: review-before-save, shown end to end against stub storage.

What it prints, in order:

  1. a direct write_platform_memory call for `personal_record` — refused, nothing written;
  2. a draft (the model's first wording, tagged as its own interpretation);
  3. the corrected draft (the owner's correction: his recollection, dated only to a season);
  4. both items queued through manage_pending_writes (one corrected record, one he declines),
     and the open queue as get_capture_queues surfaces it;
  5. approve the corrected item, discard the other;
  6. the target partition: exactly ONE row, with its provenance and the approval stamp;
  7. what the coach prompt block injects: nothing (the record is private by default).

The storage is an in-memory table that honours the calls the code makes; the tools are the
real MCP tool functions. No AWS: the MCP config module builds boto3 handles at import (no
network call), every table handle is replaced before any tool runs, the S3 write-audit is
stubbed, the AWS CLI/SDK config files point at /dev/null, and AWS_ENDPOINT_URL points every
SDK client at a closed local port — so an incidental probe elsewhere in the import graph (the
training charter's optional S3 twin) fails locally instead of reaching an account. The person and content are fictional and trivial (the repo is public).

Usage:  python3 scripts/demo_review_before_save.py
Exit code 0 when the demonstration's invariants hold (one write, provenance present), 1 otherwise.
"""

from __future__ import annotations

import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# AWS unreachable, not merely unconfigured — set BEFORE anything imports boto3.
os.environ["AWS_CONFIG_FILE"] = os.devnull
os.environ["AWS_SHARED_CREDENTIALS_FILE"] = os.devnull
os.environ["AWS_ACCESS_KEY_ID"] = "DEMO-NOT-A-KEY"
os.environ["AWS_SECRET_ACCESS_KEY"] = "DEMO-NOT-A-SECRET"  # noqa: S105 — a placeholder; the endpoint below is a closed port
os.environ.pop("AWS_PROFILE", None)
# Every SDK call (an import-time config probe included) goes to a closed local port, once.
os.environ["AWS_ENDPOINT_URL"] = "http://127.0.0.1:9"
os.environ["AWS_MAX_ATTEMPTS"] = "1"
os.environ["AWS_RETRY_MODE"] = "standard"
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "demo-table-not-real")
os.environ.setdefault("S3_BUCKET", "demo-bucket-not-real")
os.environ.setdefault("USER_ID", "matthew")

for _p in (_REPO, os.path.join(_REPO, "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ai import platform_memory as pm  # noqa: E402

import mcp.audit as mcp_audit  # noqa: E402
import mcp.tools_capture as tc  # noqa: E402
import mcp.tools_memory as tm  # noqa: E402
import mcp.tools_pending_writes as tpw  # noqa: E402


class ConditionalCheckFailedException(Exception):
    pass


class StubTable:
    """In-memory stand-in for the DynamoDB calls these tools make (conditions honoured)."""

    def __init__(self):
        self.store: dict = {}
        self.puts = 0

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeNames=None, ExpressionAttributeValues=None):
        key = (Item["pk"], Item["sk"])
        existing = self.store.get(key)
        if ConditionExpression == "attribute_not_exists(sk)" and existing is not None:
            raise ConditionalCheckFailedException("attribute_not_exists(sk)")
        if ConditionExpression == "attribute_exists(sk)" and existing is None:
            raise ConditionalCheckFailedException("attribute_exists(sk)")
        if ConditionExpression == "#st = :expected":
            if existing is None or existing.get("status") != ExpressionAttributeValues[":expected"]:
                raise ConditionalCheckFailedException("status mismatch")
        self.store[key] = dict(Item)
        self.puts += 1
        return {}

    def get_item(self, Key):
        item = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def update_item(self, Key, UpdateExpression, ConditionExpression, ExpressionAttributeValues):
        item = self.store.get((Key["pk"], Key["sk"]))
        if item is None or item.get("deleted_at"):
            raise ConditionalCheckFailedException("update condition")
        item["deleted_at"] = ExpressionAttributeValues[":da"]
        item["deleted_reason"] = ExpressionAttributeValues[":dr"]
        return {}

    def query(self, KeyConditionExpression=None, ExpressionAttributeValues=None, ExclusiveStartKey=None, **kwargs):
        if isinstance(KeyConditionExpression, str):
            eav = ExpressionAttributeValues
            if "BETWEEN" in KeyConditionExpression:
                rows = [v for (p, s), v in self.store.items() if p == eav[":pk"] and eav[":s"] <= s <= eav[":e"]]
            else:
                rows = [v for (p, s), v in self.store.items() if p == eav[":pk"] and s.startswith(eav.get(":pfx") or eav.get(":p"))]
        else:  # boto3 Key() condition from platform_memory_block — read its pk and begins_with prefix
            exp = KeyConditionExpression.get_expression()
            pk = exp["values"][0].get_expression()["values"][1]
            prefix = exp["values"][1].get_expression()["values"][1]
            rows = [v for (p, s), v in self.store.items() if p == pk and s.startswith(prefix)]
        rows = [
            dict(r) for r in rows if not ("attribute_not_exists(deleted_at)" in str(kwargs.get("FilterExpression")) and r.get("deleted_at"))
        ]
        rows.sort(key=lambda r: r["sk"], reverse=not kwargs.get("ScanIndexForward", True))
        limit = kwargs.get("Limit")
        return {"Items": rows[:limit] if limit else rows}

    def rows(self, pk: str) -> list[dict]:
        return [v for (p, _s), v in self.store.items() if p == pk]


def install(table: StubTable) -> None:
    """Point every tool this demo touches at the stub; stub the S3 write-audit."""
    tpw._table_ref = table
    tm._table_ref = table
    tc.table = table
    mcp_audit.record_mutation = lambda *a, **k: None


def _show(out, title: str, obj) -> None:
    out(f"\n== {title}")
    out(json.dumps(obj, indent=2, default=str, sort_keys=True) if not isinstance(obj, str) else obj)


PROVENANCE_KEYS = ("evidence_kind", "event_date", "event_date_precision", "source_ref", "owner_reviewed_at", "reviewed_via", "privacy_tier")


def run_demo(out=print) -> dict:
    table = StubTable()
    install(table)
    memory_pk = tm._memory_pk()

    # 1. The tool itself refuses a direct write — the queue is not skill prose.
    direct = tm.tool_write_platform_memory(
        {"category": "personal_record", "content": {"summary": "Took up swimming at the town pool"}, "evidence_kind": "recollection"}
    )
    _show(out, "1. direct write_platform_memory(personal_record) — refused", direct)
    out(f"   rows in the memory partition after the direct call: {len(table.rows(memory_pk))}")

    # 2. The draft: the model's own reading of something a fictional subject mentioned.
    draft = {
        "category": "personal_record",
        "content": {"summary": "Took up swimming at the town pool"},
        "evidence_kind": "ai_interpretation",
        "event_date": "2019-06-14",
        "source_ref": "demo-page-0001",
    }
    _show(out, "2. draft shown for review", draft)

    # 3. The correction: it is his recollection, and he only knows it was summer 2019.
    corrected = {**draft, "evidence_kind": "recollection", "event_date": "2019-summer", "event_date_precision": "season"}
    _show(out, "3. corrected draft (his correction applied)", corrected)
    out(f"   precheck at enqueue: {tm.queued_write_precheck(corrected) or 'ok'}")

    # 4. Queue both: the corrected record, and a second draft he will decline.
    declined = {
        "category": "personal_record",
        "content": {"summary": "Prefers tea to coffee in the afternoon"},
        "evidence_kind": "ai_interpretation",
    }
    q1 = tpw.tool_manage_pending_writes(
        {
            "action": "enqueue",
            "target_tool": "write_platform_memory",
            "target_args": corrected,
            "summary": "Swimming, summer 2019 (recollection)",
        }
    )
    q2 = tpw.tool_manage_pending_writes(
        {
            "action": "enqueue",
            "target_tool": "write_platform_memory",
            "target_args": declined,
            "summary": "Tea over coffee (interpretation)",
        }
    )
    _show(out, "4. queued", {"approve_candidate": q1.get("pending_id"), "discard_candidate": q2.get("pending_id")})
    surfaced = tc._pending_writes_section()
    out(f"   get_capture_queues pending_writes count: {surfaced.get('count')}")
    out(f"   rows in the memory partition while queued: {len(table.rows(memory_pk))}")

    # 5. His say-so: approve one, discard the other.
    approved = tpw.tool_manage_pending_writes({"action": "approve", "pending_id": q1["pending_id"]})
    discarded = tpw.tool_manage_pending_writes({"action": "discard", "pending_id": q2["pending_id"], "reason": "not accurate"})
    _show(
        out,
        "5. approve one, discard one",
        {"approved": approved.get("approved"), "discarded": discarded.get("discarded"), "target_result": approved.get("target_result")},
    )

    # 6. Exactly one row in the target partition, carrying its provenance.
    rows = table.rows(memory_pk)
    _show(out, f"6. memory partition rows: {len(rows)}", [{k: r.get(k) for k in ("sk", "summary", *PROVENANCE_KEYS)} for r in rows])

    # 7. What a coach prompt would receive: nothing — the record is private by default.
    block = pm.platform_memory_block(coach_id="mind", table=table)
    _show(out, "7. platform_memory_block(coach_id='mind')", block or "(empty — private records are never injected)")

    return {
        "direct": direct,
        "queued": [q1, q2],
        "approved": approved,
        "discarded": discarded,
        "rows": rows,
        "block": block,
        "capture_count": surfaced.get("count"),
    }


def main() -> int:
    result = run_demo()
    rows = result["rows"]
    ok = (
        "error" in result["direct"]
        and len(rows) == 1
        and rows[0].get("evidence_kind") == "recollection"
        and rows[0].get("owner_reviewed_at")
        and rows[0].get("privacy_tier") == "private"
        and result["block"] == ""
    )
    print(f"\nRESULT: {'PASS' if ok else 'FAIL'} — {len(rows)} target write(s)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
