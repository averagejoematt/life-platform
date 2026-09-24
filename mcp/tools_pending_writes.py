"""tools_pending_writes.py — `manage_pending_writes`: chat's persisted "queued pending approval" (#4078).

Chat sessions on 2026-09-08, 09-18, 09-20 and 09-21 each ended by telling Matthew that
writes were "queued pending approval". No queue existed; the writes died with the
conversation. This tool is that queue, so the sentence becomes true or is never said:

  enqueue  — persist ONE proposed write: the registered write tool it will call, the exact
             arguments, and a one-line summary. The arguments are validated NOW against the
             target tool's own schema (the same SEC-3 check `mcp/handler.py` runs on every
             call), so an item that is queued is an item that can be performed.
  list     — the open items with their age (get_capture_queues surfaces the same set).
  approve  — PERFORM the queued write by calling the target tool with the stored arguments,
             then mark the row approved. A target that errors leaves the row pending with
             the error attached — a failed approval is visible, never a silent drop.
  discard  — mark the row discarded (a status transition, not a delete — the row is the
             record that the write was refused rather than lost).

The storage half — key shape, age arithmetic, rulings — is `lambdas/coach/pending_writes.py`;
the nightly dead-man is `lambdas/operational/pending_writes_qa.py`.

WHAT MAY BE QUEUED is derived, not listed: any tool in the live registry that
`mcp/audit.py::is_write_tool` classifies as a write, except this tool itself (a queued
enqueue would be a queue of queues). A new write tool is queueable the day it is
registered; a read tool never is.

The approval runs the target's function in-process, so it records its own entry in the
#753 S3 write-audit trail under the TARGET tool's name — the handler only audits the outer
`manage_pending_writes` call, and without this the approved write would be the one
mutation with no trail entry of its own.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from mcp.config import logger, table as _table_ref

try:
    # Shared, bundled module (#781) — staged at zip root in the Lambda.
    from coach import pending_writes as pw
except ImportError:  # pragma: no cover — the MCP bundle always ships lambdas/ at root
    if not TYPE_CHECKING:
        from lambdas.coach import pending_writes as pw

SELF_TOOL = "manage_pending_writes"
ACTIONS = ("enqueue", "list", "approve", "discard")

MANAGE_PENDING_WRITES_DESCRIPTION = (
    "#4078: the PERSISTED queue for writes that wait on Matthew's approval. Whenever you would tell him a "
    "write is 'queued', 'pending approval', 'staged' or 'saved for later', call action='enqueue' FIRST "
    "and only say it is queued if the call returned a pending_id — a queue that exists only in this "
    "conversation is lost when the chat ends (09-08, 09-18, 09-20 and 09-21 all ended that way). "
    "enqueue: target_tool (any registered WRITE tool, e.g. log_decision, write_platform_memory, "
    "manage_sick_days), target_args (the exact arguments that tool takes — validated against its schema "
    "now, so a queued item can always be performed), summary (one line he will recognise), optional "
    "context. An identical pending item is returned instead of duplicated. list: the open items with "
    "age_days (get_capture_queues also surfaces them at session start). approve: pending_id — PERFORMS the "
    "write through the target tool and marks it approved; if the target errors the item stays pending with "
    "the error. discard: pending_id (+ optional reason) — drops it; the row is kept as the record that it was "
    "refused. Only approve or discard on his explicit say-so. An item open more than 3 days is flagged "
    "overdue and warned on nightly."
)

MANAGE_PENDING_WRITES_INPUT = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["enqueue", "list", "approve", "discard"],
            "description": "enqueue a proposed write, list open items, approve (perform) one, or discard one.",
        },
        "target_tool": {
            "type": "string",
            "description": "action='enqueue': the registered WRITE tool the approval will call (e.g. 'log_decision').",
        },
        "target_args": {
            "type": "object",
            "description": "action='enqueue': the exact arguments for target_tool — checked against its schema before queueing.",
        },
        "summary": {
            "type": "string",
            "description": "action='enqueue': one line describing the write in words Matthew will recognise. Required.",
        },
        "context": {
            "type": "string",
            "description": "action='enqueue': optional — why it was proposed (the session, the conversation turn).",
        },
        "pending_id": {
            "type": "string",
            "description": "action='approve'/'discard': the id enqueue returned (also shown by list and get_capture_queues).",
        },
        "reason": {"type": "string", "description": "action='discard': optional — why it was dropped."},
        "include_resolved": {
            "type": "boolean",
            "description": "action='list': also return approved/discarded rows still inside their 90-day retention.",
        },
    },
    "required": ["action"],
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _registry():
    # Lazy: mcp.registry imports this module, so the reverse import happens at call time.
    from mcp.registry import TOOLS

    return TOOLS


def _queueable_error(target_tool: str) -> str | None:
    """None when target_tool may be queued, else the reason it may not."""
    from mcp.audit import is_write_tool

    tools = _registry()
    if target_tool == SELF_TOOL:
        return "manage_pending_writes cannot queue itself."
    if target_tool not in tools:
        return f"'{target_tool}' is not a registered tool."
    if not is_write_tool(target_tool):
        return f"'{target_tool}' is a READ tool — only writes wait on approval; call it directly."
    return None


def _args_error(target_tool: str, target_args: dict) -> str | None:
    """The target's own SEC-3 validation (required fields, types, bounds, enums, dates)."""
    from mcp.handler import _validate_tool_args

    return _validate_tool_args(target_tool, target_args)


def _is_conditional_failure(exc: Exception) -> bool:
    return "ConditionalCheckFailed" in type(exc).__name__ or "ConditionalCheckFailedException" in str(exc)


def _transition(table, item: dict, new_fields: dict, expected_status: str) -> bool:
    """Conditional put: move a row out of `expected_status`. False when another call already moved it."""
    # A None value REMOVES the attribute (a cleared `last_error` must not outlive a later success).
    updated = {k: v for k, v in {**item, **new_fields}.items() if v is not None}
    try:
        table.put_item(
            Item=updated,
            ConditionExpression="#st = :expected",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":expected": expected_status},
        )
        item.clear()
        item.update(updated)
        return True
    except Exception as e:  # noqa: BLE001
        if _is_conditional_failure(e):
            return False
        raise


def _resolved_fields(status: str, now: datetime, note: str | None) -> dict:
    fields: dict[str, Any] = {
        "status": status,
        "resolved_at": now.isoformat(),
        "ttl": int((now + timedelta(days=pw.RESOLVED_TTL_DAYS)).timestamp()),
    }
    if note:
        fields["resolution_note"] = note[:1000]
    return fields


def _get(table, pending_id: str) -> dict | None:
    resp = table.get_item(Key={"pk": pw.PK, "sk": pw.sk_for(pending_id)}) or {}
    return resp.get("Item")


def _enqueue(table, args: dict) -> dict:
    target_tool = (args.get("target_tool") or "").strip()
    target_args = args.get("target_args")
    summary = (args.get("summary") or "").strip()
    context = (args.get("context") or "").strip() or None
    if not target_tool:
        return {"error": "target_tool required — the registered write tool the approval will call."}
    if not isinstance(target_args, dict):
        return {"error": "target_args required — an object holding the exact arguments for target_tool."}
    if not summary:
        return {"error": "summary required — one line describing the write in words Matthew will recognise."}
    err = _queueable_error(target_tool)
    if err:
        return {"error": err}
    err = _args_error(target_tool, target_args)
    if err:
        return {"error": f"target_args would be rejected by {target_tool}: {err}. Nothing was queued."}

    item = pw.build_item(target_tool, target_args, summary, context=context, now=_now())
    if len(item["target_args_json"].encode("utf-8")) > pw.MAX_ARGS_JSON_BYTES:
        return {"error": f"target_args exceed {pw.MAX_ARGS_JSON_BYTES} bytes as JSON — nothing was queued."}

    now_epoch = time.time()
    # Read-before-write replay guard: the same tool + the same arguments still open is the
    # same proposed write, so a retried enqueue returns the first row instead of a twin.
    for existing in pw.open_items(table):
        if existing.get("content_hash") == item["content_hash"]:
            return {**pw.present(existing, now_epoch), "duplicate": True, "queued": True}

    table.put_item(Item=item, ConditionExpression="attribute_not_exists(sk)")
    logger.info(f"[#4078] queued {item['pending_id']} -> {target_tool}")
    return {
        **pw.present(item, now_epoch),
        "queued": True,
        "note": "Persisted. It is safe to tell Matthew this write is queued; it surfaces in get_capture_queues until approved or discarded.",
    }


def _list(table, args: dict) -> dict:
    now_epoch = time.time()
    rows = pw.query_partition(table)
    include_resolved = bool(args.get("include_resolved"))
    shown = [r for r in rows if include_resolved or r.get("status") in pw.OPEN_STATUSES]
    open_rows = [r for r in rows if r.get("status") in pw.OPEN_STATUSES]
    return {
        "open_count": len(open_rows),
        "overdue_count": sum(1 for r in open_rows if pw.is_overdue(r, now_epoch)),
        "dead_man_days": pw.DEAD_MAN_DAYS,
        "items": [pw.present(r, now_epoch) for r in shown],
    }


def _approve(table, args: dict) -> dict:
    pending_id = (args.get("pending_id") or "").strip()
    if not pending_id:
        return {"error": "pending_id required."}
    item = _get(table, pending_id)
    if not item:
        return {"error": f"No queued write with pending_id '{pending_id}'."}
    status = item.get("status")
    if status != pw.STATUS_PENDING:
        return {
            "error": f"'{pending_id}' is {status}, not pending — nothing was performed.",
            **pw.present(item, time.time()),
        }
    target_tool = str(item.get("target_tool") or "")
    target_args = json.loads(item.get("target_args_json") or "{}")
    # Re-check at approval: the target may have been renamed, pruned or re-schemaed since
    # the item was queued. A stale item is reported, never half-performed.
    err = _queueable_error(target_tool) or _args_error(target_tool, target_args)
    if err:
        return {
            "error": f"Cannot perform '{pending_id}' now: {err} It stays pending — discard it or re-queue.",
            **pw.present(item, time.time()),
        }

    if not _transition(table, item, {"status": pw.STATUS_APPROVING, "approving_at": _now().isoformat()}, pw.STATUS_PENDING):
        return {"error": f"'{pending_id}' was already taken by another approve/discard call — nothing was performed twice."}

    from mcp import audit as mcp_audit

    t0 = time.time()
    try:
        result = _registry()[target_tool]["fn"](target_args)
    except Exception as e:  # noqa: BLE001 — the row must not be left claiming success
        mcp_audit.record_mutation(target_tool, target_args, "error", (time.time() - t0) * 1000)
        _transition(table, item, {"status": pw.STATUS_PENDING, "last_error": f"{type(e).__name__}: {e}"[:500]}, pw.STATUS_APPROVING)
        logger.warning(f"[#4078] approve {pending_id} -> {target_tool} raised: {e}")
        return {"error": f"{target_tool} failed: {type(e).__name__}: {e}. The item stays pending.", **pw.present(item, time.time())}

    if isinstance(result, dict) and result.get("error"):
        mcp_audit.record_mutation(target_tool, target_args, "error", (time.time() - t0) * 1000)
        _transition(table, item, {"status": pw.STATUS_PENDING, "last_error": str(result.get("error"))[:500]}, pw.STATUS_APPROVING)
        return {
            "error": f"{target_tool} refused the write: {result.get('error')}. The item stays pending.",
            **pw.present(item, time.time()),
        }

    mcp_audit.record_mutation(target_tool, target_args, "success", (time.time() - t0) * 1000)
    excerpt = json.dumps(result, default=str)[:1000]
    _transition(
        table,
        item,
        {**_resolved_fields(pw.STATUS_APPROVED, _now(), None), "result_excerpt": excerpt, "last_error": None},
        pw.STATUS_APPROVING,
    )
    logger.info(f"[#4078] approved {pending_id} -> {target_tool}")
    return {**pw.present(item, time.time()), "approved": True, "target_result": result}


def _discard(table, args: dict) -> dict:
    pending_id = (args.get("pending_id") or "").strip()
    if not pending_id:
        return {"error": "pending_id required."}
    item = _get(table, pending_id)
    if not item:
        return {"error": f"No queued write with pending_id '{pending_id}'."}
    status = item.get("status")
    if status not in pw.OPEN_STATUSES:
        return {"error": f"'{pending_id}' is already {status} — nothing changed.", **pw.present(item, time.time())}
    # `approving` may be discarded: that row's write outcome is unknown (the approving call
    # died mid-flight), so the owner reads the target back and resolves it by hand.
    reason = (args.get("reason") or "").strip() or None
    if not _transition(table, item, _resolved_fields(pw.STATUS_DISCARDED, _now(), reason), str(status)):
        return {"error": f"'{pending_id}' changed state while discarding — call list and retry."}
    logger.info(f"[#4078] discarded {pending_id}")
    return {**pw.present(item, time.time()), "discarded": True}


_DISPATCH = {"enqueue": _enqueue, "list": _list, "approve": _approve, "discard": _discard}


def tool_manage_pending_writes(args):
    """Enqueue / list / approve / discard a chat write awaiting Matthew's approval (#4078)."""
    args = args or {}
    action = (args.get("action") or "list").strip().lower()
    fn = _DISPATCH.get(action)
    if fn is None:
        return {"error": f"Unknown action '{action}'. One of: {', '.join(ACTIONS)}."}
    return fn(_table_ref, args)
