"""coach_corrections.py — the durable ledger for Matthew's corrections to weekly
AI-review-pack items (#1689, foundation story for epic #1687 "The Coach Correction Loop").

The weekly AI-review-pack email (#1594) numbers + stack-ranks each generation and
tags it with a checkable claim (S1, #1688). When Matthew corrects an item, the
correction needs a durable home — tagged by **error-class** — so it can later feed
three downstream mechanisms (none of them built by this story):
  - prompt-memory: a per-coach "past corrections for you" few-shot block (S5, #1691+)
  - deterministic gates: recurring classes graduate to hard checks (ADR-104/105)
  - pattern-extraction: periodic clustering that proposes memory→gate promotions (S6)

This module is JUST the ledger: storage + a pure item-builder + a mockable
writer/reader. The feedback CHANNELS that call `write_correction()` — an MCP tool
(`log_coach_correction`) and an email-reply parser — are #1690, out of scope here.

Design (mirrors `lambdas/eval_retention.py`'s build/write/read split and
`lambdas/emails/ai_review_pack_lambda.py::record_email_send`'s mockable-table idiom):
- Records live at pk `USER#matthew#SOURCE#coach_corrections`,
  sk `CORRECTION#<YYYY-MM-DD>#<id8>` (id8 = uuid4().hex[:8]) — single-table
  convention, no new GSI (adding one requires an ADR; this module reads via a
  plain partition Query + client-side filter).
- Classified **CROSS_PHASE** in `lambdas/phase_taxonomy.py`: a correction Matthew
  makes about a coach's error stays true across experiment resets — it is not a
  property of the current run (same rationale as the CROSS_PHASE "calibration"
  and "EVALRET#" ledgers), so it is NEVER tagged, wiped, or phase-filtered.
- `build_correction_item()` is PURE (no AWS) — unit-testable in isolation.
- `write_correction()` / `list_corrections()` / `get_correction()` /
  `update_status()` all take a boto3 Table resource as their first argument
  (mockable with `tests/fakes.py::FakeDdbTable`), mirroring
  `ai_review_pack_lambda.record_email_send(table, ...)`.
- Decimal-before-write (ADR/CLAUDE.md convention): any float inside `item_ref`
  (e.g. a pack number) is cast to `Decimal` before the put via the shared
  `lambdas/numeric.py::floats_to_decimal` walker (#1207) — boto3 rejects a bare
  Python `float`, and this module deliberately does NOT fork its own copy (the
  D5 regression guard in `tests/test_ddb_patterns.py` enforces that).

v1.0.0 — 2026-07-22 (#1689)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from numeric import floats_to_decimal

PK = "USER#matthew#SOURCE#coach_corrections"
SK_PREFIX = "CORRECTION#"

# The error-class vocabulary locked by epic #1687 / story #1688 — the checkable-claim
# tags the review pack applies to each ranked item. Kept as a tuple so #1688 (the
# ranker/tagger) and #1690 (the feedback channels) import ONE source of truth rather
# than each hand-rolling the list. "other" is the deliberate free-form fallback: an
# unrecognized tag is never silently dropped (see `build_correction_item` below) — it
# is normalized to "other" with the original label preserved in `error_class_raw`.
ERROR_CLASSES = (
    "stale-baseline",  # reset-window contamination — frozen pre-genesis baselines cited as current
    "ungrounded-behavioral",  # a behavioral claim with no supporting log ("you maintained your window")
    "cross-coach-inconsistency",  # two coaches asserting conflicting numbers for the same target
    "framing",  # technically-true but misleadingly framed
    "checkable-metric",  # a specific numeric claim that is simply wrong
    "hedged-safe",  # correctly hedged / appropriately uncertain (a "no correction needed" tag)
    "defense-held",  # Matthew reviewed a flagged item and the generation's claim held up
    "other",  # free-form fallback — never silently drops an unrecognized class
)

# The lifecycle a correction moves through once #1690's channels + #1691's gate
# start consuming the ledger. "open" is the only state this story ever writes;
# the other two are downstream transitions via `update_status()`.
STATUSES = ("open", "applied-to-prompt", "applied-to-gate")

_ID_LEN = 8


def build_correction_item(
    item_ref: Optional[dict],
    correction_text: str,
    error_class: str,
    *,
    now: Optional[datetime] = None,
    correction_id: Optional[str] = None,
) -> dict:
    """Pure: build the DDB item for one correction. No AWS calls — unit-testable
    without a table (mirrors `eval_retention.build_record` / `ai_review_pack_lambda.build_html`).

    `item_ref` identifies what was corrected — the caller's convention (per #1687/#1688)
    is a dict with keys like `surface`, `coach`, `date`, `pack_number`/`pack_item_ref`,
    but this function does not require or validate a specific shape beyond making it
    Decimal-safe: it is stored as given (deep-copied + float-cast), so #1690's channels
    are free to pass whatever fields the S1 ranked pack exposes.

    An `error_class` outside `ERROR_CLASSES` is never dropped: it is normalized to
    "other" and the original value is preserved verbatim in `error_class_raw`.

    Float->Decimal conversion inside `item_ref` uses the shared `numeric.floats_to_decimal`
    walker (#1207) rather than a private copy — see the D5 regression guard in
    `tests/test_ddb_patterns.py`.
    """
    now = now or datetime.now(timezone.utc)
    correction_id = correction_id or uuid.uuid4().hex[:_ID_LEN]
    date_str = now.strftime("%Y-%m-%d")
    sk = f"{SK_PREFIX}{date_str}#{correction_id}"

    normalized_class = error_class if error_class in ERROR_CLASSES else "other"

    item: dict = {
        "pk": PK,
        "sk": sk,
        "correction_id": correction_id,
        "item_ref": floats_to_decimal(dict(item_ref or {})),
        "correction_text": correction_text,
        "error_class": normalized_class,
        "status": "open",
        "created_at": now.isoformat(),
    }
    if normalized_class != error_class:
        item["error_class_raw"] = error_class
    return item


def write_correction(
    table,
    item_ref: Optional[dict],
    correction_text: str,
    error_class: str,
    *,
    now: Optional[datetime] = None,
    correction_id: Optional[str] = None,
) -> str:
    """Put one correction. Returns the `sk` (the record's id) so a caller (#1690's
    MCP tool / email parser) can echo or reference it. Raises on a DDB error — unlike
    `eval_retention.retain()`, a correction write is user-initiated feedback, not a
    best-effort side channel, so a silent failure would mean Matthew's correction is
    lost without him knowing.
    """
    item = build_correction_item(item_ref, correction_text, error_class, now=now, correction_id=correction_id)
    table.put_item(Item=item)
    return item["sk"]


def get_correction(table, sk: str) -> Optional[dict]:
    """Fetch one correction by its `sk`. Returns None if not found."""
    resp = table.get_item(Key={"pk": PK, "sk": sk})
    return resp.get("Item")


def list_corrections(
    table,
    *,
    status: Optional[str] = None,
    error_class: Optional[str] = None,
    limit: int = 100,
) -> list:
    """Query the corrections partition (newest first), optionally filtered by
    `status` and/or `error_class`. No GSI (adding one requires an ADR) — this is a
    single-partition Query with client-side filtering, which is the right tradeoff
    for a durable feedback ledger that is written at human speed, not high volume.
    """
    from boto3.dynamodb.conditions import Key

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(PK),
        ScanIndexForward=False,
    )
    items = resp.get("Items", [])
    if status is not None:
        items = [i for i in items if i.get("status") == status]
    if error_class is not None:
        items = [i for i in items if i.get("error_class") == error_class]
    return items[:limit]


def update_status(table, sk: str, new_status: str) -> bool:
    """Transition one correction's status (open -> applied-to-prompt|applied-to-gate).

    Raises ValueError on an unknown status rather than writing a typo'd state.
    """
    if new_status not in STATUSES:
        raise ValueError(f"unknown correction status {new_status!r} (expected one of {STATUSES})")
    table.update_item(
        Key={"pk": PK, "sk": sk},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": new_status},
    )
    return True
