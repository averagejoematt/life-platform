"""pending_writes.py — the persisted queue for chat writes awaiting Matthew's approval (#4078).

THE INCIDENT THIS EXISTS FOR
  Chat coaching sessions on 2026-09-08, 09-18, 09-20 and 09-21 each ended with the model
  telling Matthew that one or more writes were "queued pending approval". There was no
  queue. The sentence described an intention held only in that conversation's context, so
  when the chat ended the writes were gone — never written, never surfaced, never
  refused. A lost write that was announced as safe is worse than a refused one: nothing
  downstream can tell it apart from a write he declined.

WHAT THIS MODULE IS
  The storage half: key shape, the pure item builder, the partition read, and the age
  arithmetic both readers share. The MCP half (`mcp/tools_pending_writes.py`) enqueues,
  approves (performs the queued write through the registered tool) and discards; the
  session opener (`mcp/tools_capture.py::get_capture_queues`) surfaces open items with
  their age; the nightly dead-man (`lambdas/operational/pending_writes_qa.py`, a
  `life-platform-qa-smoke` leg) warns when an item has sat open past DEAD_MAN_DAYS.
  All three import PK / SK_PREFIX / OPEN_STATUSES / DEAD_MAN_DAYS from HERE — one
  definition, no copies.

KEYS (single table, no GSI)
  pk  USER#matthew#SOURCE#pending_writes
  sk  PENDING#<YYYYMMDDTHHMMSSZ>-<hash8>   — sorts by enqueue time; the suffix after
      `PENDING#` IS the `pending_id` the tools take, so approve/discard are a GetItem,
      never a scan.

RULINGS (recorded here because the code enforces them)
  * Phase class: SYSTEM_STATE (`lambdas/experiment/phase_taxonomy.py`). The queue is a
    workflow buffer, not a fact about the experiment: an approved item's payload lands in
    its TARGET partition, which carries that partition's own class; the queue row is only
    the record that a write was proposed and what became of it. A reset must neither wipe
    nor phase-filter an open item — an owner's pending decision does not expire because
    the experiment re-anchored — and SYSTEM_STATE is the class the phase machinery
    ignores entirely. Same reasoning as `experiment_suggestions` (awaiting moderation,
    kept across resets).
  * Privacy tier: Tier 2 OWNER-ONLY (`lambdas/privacy/field_tiers.py` SOURCE_TIERS,
    `docs/DATA_GOVERNANCE.md`). A queued write can carry anything a write tool accepts —
    journal-grade text, a pain-site statement, nutrition — so the row takes the highest
    tier of what it may hold. No public projection of any kind; readers are MCP-only.
  * Dead-man N = 3 days. The chat cadence behind this issue was 8 sessions in 9 days, so
    an item open for 3 days has been passed over by roughly three session openers — that
    is the approval step being skipped, not a slow owner. Past 3 days the queued write's
    own context (a day's log, a session's numbers) is also going stale. WARN, not FAIL:
    an unapproved item is an owner decision outstanding, not a system fault, and a
    reverting deploy cannot resolve it.
  * Open items NEVER carry a TTL. A pending row that self-expired would be exactly the
    silent loss this module exists to end. Only a RESOLVED row (approved / discarded)
    gets a `ttl`, RESOLVED_TTL_DAYS out, so the partition does not grow without bound.
  * Discard is a status transition, never a DeleteItem: the MCP role holds no
    `dynamodb:DeleteItem` on this partition, and the discarded row is the record that
    the write was refused rather than lost.
  * `target_args` is stored as canonical JSON TEXT, not a DynamoDB map. A map would force
    every float through Decimal and back, and `decimals_to_float` turns an int-valued
    Decimal into a float — an `item_number: 3` would come back as `3.0` and fail the
    target tool's integer check at approval time. Text round-trips exactly. The only
    numbers written as attributes are epoch ints (boto3 accepts int; no float is ever
    written, so no Decimal cast is needed or possible to get wrong).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

SOURCE = "pending_writes"
PK = "USER#matthew#SOURCE#pending_writes"
SK_PREFIX = "PENDING#"

STATUS_PENDING = "pending"
#: Claimed by an approve call whose write is in flight. If the MCP invocation dies
#: mid-write the row stays here — surfaced and aged like `pending`, because whether the
#: write landed is unknown and only a read-back of the target can say.
STATUS_APPROVING = "approving"
STATUS_APPROVED = "approved"
STATUS_DISCARDED = "discarded"
OPEN_STATUSES = frozenset({STATUS_PENDING, STATUS_APPROVING})
RESOLVED_STATUSES = frozenset({STATUS_APPROVED, STATUS_DISCARDED})

#: The ruled dead-man age (see RULINGS above).
DEAD_MAN_DAYS = 3

RESOLVED_TTL_DAYS = 90

#: A queued write larger than this is refused at enqueue. DynamoDB's item ceiling is
#: 400 KB; this leaves room for the rest of the row and is far above any write tool's
#: realistic argument set (the MCP layer already caps each string argument at 2,000 chars).
MAX_ARGS_JSON_BYTES = 32_000


def canonical_args(args: dict) -> str:
    """Canonical JSON text for a target tool's arguments — sorted keys, no whitespace."""
    return json.dumps(args or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def content_hash(target_tool: str, args_json: str) -> str:
    """The identity of a queued write: the same tool with the same arguments is the same write."""
    return hashlib.sha256(f"{target_tool}\x1f{args_json}".encode("utf-8")).hexdigest()[:16]


def make_pending_id(now: datetime, digest: str) -> str:
    return f"{now.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}-{digest[:8]}"


def sk_for(pending_id: str) -> str:
    return SK_PREFIX + pending_id


def build_item(
    target_tool: str,
    target_args: dict,
    summary: str,
    *,
    context: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Pure: the row an enqueue writes. No AWS."""
    now = now or datetime.now(timezone.utc)
    args_json = canonical_args(target_args)
    digest = content_hash(target_tool, args_json)
    pending_id = make_pending_id(now, digest)
    item: dict[str, Any] = {
        "pk": PK,
        "sk": sk_for(pending_id),
        "pending_id": pending_id,
        "content_hash": digest,
        "status": STATUS_PENDING,
        "target_tool": target_tool,
        "target_args_json": args_json,
        "summary": summary,
        "enqueued_at": now.astimezone(timezone.utc).isoformat(),
        "enqueued_epoch": int(now.timestamp()),
        "schema_version": 1,
    }
    if context:
        item["context"] = context
    return item


def age_days(item: dict, now_epoch: float) -> float:
    """Age in days from the stored epoch — never a timestamp parse."""
    try:
        return max(0.0, (float(now_epoch) - float(item.get("enqueued_epoch") or 0)) / 86400.0)
    except (TypeError, ValueError):
        return 0.0


def is_overdue(item: dict, now_epoch: float, days: int = DEAD_MAN_DAYS) -> bool:
    return item.get("status") in OPEN_STATUSES and age_days(item, now_epoch) > days


def query_partition(table) -> list[dict]:
    """Every row in the queue partition, oldest first, paginated. The partition holds
    open items plus resolved rows inside their TTL — tens of items, one or two pages."""
    items: list[dict] = []
    kw: dict[str, Any] = {
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :pfx)",
        "ExpressionAttributeValues": {":pk": PK, ":pfx": SK_PREFIX},
    }
    while True:
        resp = table.query(**kw)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kw["ExclusiveStartKey"] = lek
    return items


def open_items(table) -> list[dict]:
    return [it for it in query_partition(table) if it.get("status") in OPEN_STATUSES]


def present(item: dict, now_epoch: float) -> dict:
    """The JSON-safe view of a row that every reader returns."""
    age = age_days(item, now_epoch)
    out = {
        "pending_id": item.get("pending_id"),
        "status": item.get("status"),
        "summary": item.get("summary"),
        "target_tool": item.get("target_tool"),
        "enqueued_at": item.get("enqueued_at"),
        "age_days": round(age, 1),
        "overdue": is_overdue(item, now_epoch),
    }
    for key in ("context", "last_error", "resolved_at", "resolution_note"):
        if item.get(key):
            out[key] = item.get(key)
    return out
