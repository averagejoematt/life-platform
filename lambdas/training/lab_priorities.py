"""training/lab_priorities.py — the SEAM that carries owner-only lab-driven priorities into the coach context (#5111, #4639).

The repo carries the seam, never the content. The owner writes ONE row into his own clinical partition
(`USER#matthew#SOURCE#clinical`, sk `PRIORITIES#current`, TIER_INTERNAL — the partition `health.clinical_facts` already reads) with a
`text` field: a few plain lines naming what the coach should weight. `from_rows` picks that row out of the clinical rows a caller has
ALREADY read (no second read, no new partition) and `training.coach_context.assemble(lab_priorities=...)` renders it on the owner
channel only. Absent row, empty text or a failed read -> None, and the context says nothing (ADR-104: no invented priority).

THE NEXT DRAW (#5111). `read(table, today)` adds the follow-up draw's due date and state beside the priorities: the
calibration cadence's ONE lab_draw row (`training.calibration_cadence.lab_draw_row`, the same row the reminder and the
dead-man ride), reduced by `followup_view` to dates and a state. It is for the owner contexts that hold no clinical rows
(the owner's Telegram training and nutrition threads): one key-and-priorities projection of the clinical partition (no
result attribute is projected) plus the labs partition's draw dates. A caller that already holds the clinical rows passes
them (`rows=`), and the clinical partition is not read again.

PRIVACY (PUBLIC repo): this module names no result, marker or diagnosis. Owner-only by construction: a published context
(`published=True`) drops it, and `tests/test_calibration_cadence_5061.py` holds that no `lambdas/web/` or `lambdas/emails/` module
names the row or imports this one.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

SK = "PRIORITIES#current"
LABS_PREFIX = "LABS#"
SRC_FOLLOWUP = "training.calibration_cadence lab_draw (nutrition.labs cadence; draw dates only)"
FOLLOWUP_KEYS = ("state", "due_on", "last_logged", "days_until_due", "dead_man_on", "cycle_weeks", "reminder_lead_days", "error")
MAX_CHARS = 600


def from_rows(rows: Any) -> Optional[dict[str, Any]]:
    """The priorities row among the clinical partition's rows, or None. Pure."""
    if not isinstance(rows, Iterable) or isinstance(rows, (str, bytes, dict)):
        return None
    for r in rows:
        if isinstance(r, dict) and str(r.get("sk") or "") == SK:
            text = " ".join(str(r.get("text") or "").split())
            if not text:
                return None
            return {"text": text[:MAX_CHARS], "updated_at": str(r.get("updated_at") or "")[:10] or None, "source": f"clinical {SK}"}
    return None


def read_priorities(table: Any) -> Optional[dict[str, Any]]:
    """The priorities row alone, for an owner read that holds no clinical rows (the weekly menu's quality report,
    #5105): one key-and-priorities projection of the clinical partition. A failed read is None (nothing is weighted),
    logged, never raised."""
    try:
        return from_rows(_clinical_keys(table))
    except Exception as e:  # noqa: BLE001 — a broken read leaves the priorities unweighted, never breaks the caller
        logger.warning("lab priorities unreadable: %s", type(e).__name__)
        return None


def _clinical_draw_dates(rows: Any) -> list[str]:
    """The `LABS#<date>` sort-key dates among clinical rows already held. Pure."""
    out = []
    for r in rows or ():
        sk = str((r or {}).get("sk") or "") if isinstance(r, dict) else ""
        if sk.startswith(LABS_PREFIX) and len(sk) >= len(LABS_PREFIX) + 10:
            out.append(sk[len(LABS_PREFIX) : len(LABS_PREFIX) + 10])
    return out


def _clinical_keys(table: Any) -> list[dict[str, Any]]:
    """The clinical partition's sort keys plus the priorities row's own two fields — no result attribute is projected."""
    from boto3.dynamodb.conditions import Key  # noqa: PLC0415

    out: list[dict[str, Any]] = []
    kw: dict[str, Any] = {
        "KeyConditionExpression": Key("pk").eq("USER#matthew#SOURCE#clinical"),
        "ProjectionExpression": "sk, #t, updated_at",
        "ExpressionAttributeNames": {"#t": "text"},
    }
    while True:
        resp = table.query(**kw)
        out.extend(resp.get("Items") or [])
        if not resp.get("LastEvaluatedKey"):
            return out
        kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def followup_view(row: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The lab_draw cadence row reduced to dates and a state for a coach context, with one plain line. Pure."""
    if not isinstance(row, dict) or not row.get("state"):
        return None
    out: dict[str, Any] = {"source": SRC_FOLLOWUP, **{k: row[k] for k in FOLLOWUP_KEYS if row.get(k) is not None}}
    state = out["state"]
    if out.get("due_on"):
        line = f"next follow-up draw due about {out['due_on']} (state {state}"
        line += f"; last draw {out['last_logged']}" if out.get("last_logged") else "; no draw on record, the owner's own date"
        line += ")"
        if state in ("due", "overdue", "missed_2"):
            line += "; ask whether it is booked, and log the date once it is done"
    elif state == "read_failed":
        line = f"the follow-up draw date could not be read ({out.get('error')}); say it is unknown, never guess one"
    else:
        line = "no follow-up draw date is known (no draw on record and no owner date set); say so, never guess one"
    out["line"] = line
    return out


def read(table: Any, today: str, rows: Any = None) -> dict[str, Any]:
    """`{"priorities": from_rows(...) | None, "followup": followup_view(lab_draw row)}` for `today`. Never raises.

    `rows` = the clinical partition's rows a caller already holds (then that partition is not read again); otherwise one
    key-and-priorities projection here. A failed clinical read leaves the priorities None and the follow-up `read_failed`."""
    from training import calibration_cadence as cc  # noqa: PLC0415

    err: Optional[str] = None
    if not isinstance(rows, list):
        try:
            rows = _clinical_keys(table)
        except Exception as e:  # noqa: BLE001 — a broken read is stated on the follow-up row, never raised into a coach turn
            rows, err = None, type(e).__name__

    if err:
        followup = followup_view({"state": cc.READ_FAILED, "error": err})
    else:
        try:
            followup = followup_view(cc.lab_draw_row(today, lambda: cc.draw_dates(table, clinical=_clinical_draw_dates(rows))))
        except Exception as e:  # noqa: BLE001 — e.g. an invalid `today`
            followup = followup_view({"state": cc.READ_FAILED, "error": type(e).__name__})
    return {"priorities": from_rows(rows) if rows is not None else None, "followup": followup}
