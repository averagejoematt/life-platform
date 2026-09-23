"""pending_writes_qa.py — #4078: the dead-man on the chat pending-writes queue.

THE FAILURE THIS WATCHES FOR
  Before #4078, a chat that said "queued pending approval" lost the write when the
  conversation ended. The queue (`lambdas/coach/pending_writes.py`) makes the write
  durable, and `get_capture_queues` surfaces it at the next session opener. Both of those
  depend on a chat actually being opened and the item actually being raised. If neither
  happens, an open item sits in DynamoDB with nothing reporting it — durable, and just as
  lost to Matthew as before. Absence of a RESOLUTION is the signal, so this leg reports
  every open item older than `pending_writes.DEAD_MAN_DAYS` (ruled 3 — see that module).

WHY WARN, NOT FAIL
  An unresolved item is an owner decision outstanding, not a system fault, and reverting a
  deploy cannot resolve it. `CONTENT_TRUTH`, like the orphaned-routine-draft leg (#3772)
  this is modelled on: the WARN names the ids, target tools and ages, and says how to
  clear them.

`approving` COUNTS AS OPEN
  An `approving` row is an approval whose MCP invocation died mid-write — whether the
  write landed is unknown. It is the most important row to surface, not one to skip.

PRIVACY
  The partition is Tier 2 owner-only. This leg reports the pending_id, the target tool
  name and the age — never `target_args_json`, `summary` or `context` — because the
  qa-smoke report is emailed.

Read-only: one paginated Query on a partition of tens of items. The qa-smoke role already
holds table-wide `dynamodb:Query`, so no IAM change.
"""

from __future__ import annotations

import time

from coach import pending_writes as pw


def assess_pending_writes(items, now_epoch, days=pw.DEAD_MAN_DAYS):
    """Pure: (open_count, overdue rows oldest-first) for a list of queue rows."""
    open_rows = [it for it in items if it.get("status") in pw.OPEN_STATUSES]
    overdue = sorted((it for it in open_rows if pw.is_overdue(it, now_epoch, days)), key=lambda it: str(it.get("sk", "")))
    return len(open_rows), overdue


def check_pending_writes_age(table, check_cls, partition, now_epoch=None):
    c = check_cls("data:pending_writes_age", "Chat pending writes", partition)
    now_epoch = time.time() if now_epoch is None else now_epoch
    try:
        items = pw.query_partition(table)
    except Exception as e:  # noqa: BLE001 — a read failure is not "nothing pending" (#2662)
        return [c.warn(f"pending-writes queue could not be read (no verdict was reached): {e}")]

    open_count, overdue = assess_pending_writes(items, now_epoch)
    if overdue:
        named = ", ".join(
            f"{it.get('pending_id')} ({it.get('target_tool')}, {it.get('status')}, {pw.age_days(it, now_epoch):.1f}d)" for it in overdue[:5]
        )
        more = f" (+{len(overdue) - 5} more)" if len(overdue) > 5 else ""
        return [
            c.warn(
                f"{len(overdue)} of {open_count} queued chat write(s) open longer than {pw.DEAD_MAN_DAYS} days: {named}{more} — "
                "nothing resolves these but Matthew. `manage_pending_writes action=list` shows them; approve performs the "
                "write, discard drops it. An `approving` row died mid-write: read the target back before resolving (#4078)."
            )
        ]
    return [c.ok(f"no queued chat write is older than {pw.DEAD_MAN_DAYS} days ({open_count} open) (#4078).")]
