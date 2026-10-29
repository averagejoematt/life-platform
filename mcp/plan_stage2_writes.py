"""mcp/plan_stage2_writes.py — every write stage 2 of `plan_next_session` makes, and its dry run (#4076).

Stage 2 (`tools_plan._run_stage_2`) writes three things, and only three:

  1. the routine's new version — `routine_repo.put_versioned`: VERSION#<n>, VERSION#current and the
     date-sorted `routine_index` row (`routine_repo.versioned_items` builds all three);
  2. tonight's critics thread row for the training coach (`write_thread`, `#critics` sk, keyed by today —
     it can overwrite tonight's real row);
  3. the owner's override words into the corrections ledger, one row per applied override
     (`record_override_correction`, the `log_coach_correction` write path).

It calls no Hevy endpoint and writes no S3 object (`_validate_ir_for_hevy` is a local check).

`dry_run=True` on stage 2 runs the SAME critics, the SAME override path and the SAME change
application, then writes none of the three and returns each item it WOULD have put under
`would_write` — so the override path can be proven end to end against live reads with no side
effect (the 2026-10-28 synthetic proof was blocked on exactly this: a real stage 2 run writes a
thread row and an index row). The items are built by the same functions the writers use, so the
dry run cannot drift from the real write.

`tools_plan` re-exports `write_thread` / `record_override_correction` under their old private names
(`_write_thread`, `_record_override_correction`) — the tests patch them there.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

logger = logging.getLogger(__name__)

DRY_RUN_STATE = "dry_run"


def write_thread(ir: Any, today: str, *, put: bool = True) -> dict[str, Any]:
    """Tonight's verdicts as a training coach thread row — keyed with a `#critics` suffix so it
    sits beside the analyzer's weekly entry and never overwrites it; class-gated phase stamp
    at write time (#3514/#3900). `put=False` (the #4076 dry run) builds the row and returns it
    unwritten."""
    from coach import critics
    from experiment.phase_taxonomy import experiment_stamp_for

    from mcp.config import table

    item = critics.thread_entry(ir, today=today)
    try:
        item.update(experiment_stamp_for(item["pk"], item["sk"]))
        item["created_at"] = datetime.now(timezone.utc).isoformat()
        clean = json.loads(json.dumps(item, default=str), parse_float=Decimal)
        if not put:
            return {"written": False, "dry_run": True, "sk": item["sk"], "item": clean}
        table.put_item(Item=clean)
        return {"written": True, "sk": item["sk"]}
    except Exception as e:  # noqa: BLE001 — reported in the result, never swallowed (#3670 class)
        logger.warning("critics thread write failed: %s", e)
        return {"written": False, "sk": item["sk"], "error": f"{type(e).__name__}: {e}"[:200]}


def record_override_correction(item_ref: dict[str, Any], owner_words: str, error_class: str) -> str:
    """#4076: the owner's override words into the corrections ledger — the SAME write the
    `log_coach_correction` tool makes (`coach_corrections.write_correction`, cycle-stamped
    via `coach_checkin.read_cycle`), naming the vetoing critic and signal in `item_ref`.
    Raises on a DDB error: `critics.apply_overrides` then refuses the override."""
    from coach import coach_checkin, coach_corrections

    from mcp.config import table

    return coach_corrections.write_correction(table, item_ref, owner_words, error_class, cycle=coach_checkin.read_cycle())


def dry_ledger(would: list[dict[str, Any]]) -> Callable[[dict[str, Any], str, str], str]:
    """A `record_correction` for the dry run: builds the ledger row `write_correction` would put
    (`coach_corrections.build_correction_item`, same cycle stamp) and appends it to `would`
    instead of writing it. Returns the row's real would-be sk, so the override applies exactly as
    it would live — a dry run that refused the override could not prove the override path."""
    from coach import coach_checkin, coach_corrections

    def record(item_ref: dict[str, Any], owner_words: str, error_class: str) -> str:
        item = coach_corrections.build_correction_item(item_ref, owner_words, error_class, cycle=coach_checkin.read_cycle())
        would.append(_write("corrections_ledger", item, condition="attribute_not_exists(sk)"))
        return item["sk"]

    return record


def _write(kind: str, item: dict[str, Any], *, condition: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"kind": kind, "op": "put_item", "pk": item.get("pk"), "sk": item.get("sk"), "item": item}
    if condition:
        row["condition"] = condition
    return row


def dry_run_result(record: dict[str, Any], ir: Any, would: list[dict[str, Any]], today: str, notes_preview: str) -> dict[str, Any]:
    """The stage-2 result of a dry run: the full critics record, `written: False`, and every put
    the real run makes under `would_write` — routine version + pointer + index, the thread row,
    and any ledger rows the override path recorded. Nothing here touches DynamoDB, S3 or Hevy."""
    from coach import critics
    from training import routine_repo

    kinds = ("routine_version", "routine_current", "routine_index")
    puts = [_write(k, it) for k, it in zip(kinds, routine_repo.versioned_items(ir))]
    puts[0]["condition"] = "attribute_not_exists(pk) AND attribute_not_exists(sk)"
    thread = write_thread(ir, today, put=False)
    if thread.get("item") is not None:
        puts.append(_write("coach_thread", thread["item"]))
    out = dict(record)
    out.update(routine_id=ir.routine_id, routine_version=ir.version, written=False, verdict_state=DRY_RUN_STATE, dry_run=True)
    out["thread"] = {k: v for k, v in thread.items() if k != "item"}
    out["would_write"] = list(would) + puts  # real write order: the ledger (during the override), then the version, then the thread
    out["notes_preview"] = notes_preview
    overridden = sorted(v["critic"] for v in record.get("verdicts") or [] if critics.is_overridden(v))
    state = "a veto STANDS" if record.get("veto") else (f"{', '.join(overridden)} OVERRIDDEN" if overridden else "no veto")
    out["next"] = (
        f"DRY RUN — nothing was written ({len(out['would_write'])} put(s) listed under `would_write`); {state}. "
        "Run stage 2 again without dry_run to store the verdicts; commit reads only a stored record."
    )
    return out
