#!/usr/bin/env python3
"""training_block_retro.py — the /training-review block retro's readers and its one writer (#5079).

`lambdas/training/block_retro.py` is pure. This is its wiring on the owner's workstation, in two phases so the
model is called once and the AWS write is a separate, deliberate act:

  grade   READ-ONLY. Reads the owner-only rows the retro is graded from — the May tracker's WEEK# rows, the
          weekly PANEL# grades, the owner's DELOAD# and MODE#disruption records, the last RETRO# row and the
          #5089 charter predictions (`diary_claims` PREDICTION# rows, source `charter_build`) — plus the
          `--supplied` JSON the skill builds from MCP tools, then runs the retro (the panel re-grade on route
          `charter.retro` unless `--no-panel`) and writes the retro JSON + the doc-tab markdown to `--out`.
  store   THE WRITE (dry-run unless `--apply`). Puts `USER#matthew#SOURCE#training_constraints / RETRO#<block_end>`
          and flips each graded charter prediction from `observation` to its verdict (conditional on it still
          being open), from a retro JSON `grade` produced. The owner or the driver runs `--apply`; never a lane.
  baseline  THE ONE-TIME WRITE (dry-run unless `--apply`). Puts the owner-only baseline row
          `training_constraints / RETRO#<scorecard baseline.date>` (kind `baseline`) from a `--letters` JSON
          {row_id: letter} the skill reads from the owner's PRIVATE review doc and keeps OUTSIDE the repo (the
          repo is PUBLIC). The first retro reads it as its prior. Refuses a missing row, an unknown row, an
          off-scale letter, or a baseline row that is already stored.

Every read uses a 60 s read timeout. A failed read stops the run and names the partition — a broken read is
never an empty block.

    python3 scripts/training_block_retro.py baseline --letters <scratch>/baseline-letters.json                # dry run
    python3 scripts/training_block_retro.py grade --block-end 2026-12-06 --supplied /tmp/supplied.json --out /tmp/retro-2026-12-06
    python3 scripts/training_block_retro.py store --retro /tmp/retro-2026-12-06/retro.json            # dry run
    python3 scripts/training_block_retro.py store --retro /tmp/retro-2026-12-06/retro.json --apply    # the write
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))

from training import block_retro  # noqa: E402

TABLE = "life-platform"
REGION = "us-west-2"
USER_PK = "USER#matthew"
CONSTRAINTS_PK = f"{USER_PK}#SOURCE#training_constraints"
MAY_PK = f"{USER_PK}#SOURCE#may_tracker"
CLAIMS_PK = f"{USER_PK}#SOURCE#diary_claims"
PREDICTION_SOURCE = "charter_build"


def _table() -> Any:
    import boto3
    from botocore.config import Config

    return boto3.resource("dynamodb", region_name=REGION, config=Config(read_timeout=60, retries={"max_attempts": 3})).Table(TABLE)


def _plain(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=lambda o: float(o) if isinstance(o, Decimal) else str(o)))


def query(table: Any, pk: str, prefix: str) -> list[dict[str, Any]]:
    """Every row of `pk` whose sk begins with `prefix` (paginated). Raises on a failed read."""
    from boto3.dynamodb.conditions import Key

    kwargs: dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(prefix)}
    items: list[dict[str, Any]] = []
    while True:
        resp = table.query(**kwargs)
        items += resp.get("Items") or []
        if not resp.get("LastEvaluatedKey"):
            return _plain(items)
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def read_inputs(table: Any, block_end: str) -> dict[str, Any]:
    retros = [r for r in query(table, CONSTRAINTS_PK, block_retro.RETRO_SK_PREFIX) if str(r.get("block_end")) < block_end]
    return {
        "may_rows": query(table, MAY_PK, "WEEK#"),
        "panel_rows": query(table, CONSTRAINTS_PK, "PANEL#"),
        "deload_records": query(table, CONSTRAINTS_PK, "DELOAD#"),
        "disruption_records": query(table, CONSTRAINTS_PK, "MODE#disruption#"),
        "prior": max(retros, key=lambda r: str(r.get("block_end"))) if retros else None,
        "predictions": [p for p in query(table, CLAIMS_PK, "PREDICTION#") if p.get("source") == PREDICTION_SOURCE],
    }


def cmd_grade(args: argparse.Namespace) -> int:
    supplied = json.load(open(args.supplied, encoding="utf-8")) if args.supplied else {}
    overrides = json.load(open(args.overrides, encoding="utf-8")) if args.overrides else {}
    inputs = read_inputs(_table(), args.block_end)
    retro = block_retro.run(args.block_end, supplied=supplied, with_panel=not args.no_panel, **inputs)
    if retro.get("status") != "graded":
        print(json.dumps(retro, indent=2))
        return 1
    if overrides:
        sc = block_retro.load_scorecard()
        retro["graded"] = block_retro.apply_overrides(retro["graded"], overrides, sc or {})
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "retro.json"), "w", encoding="utf-8") as f:
        json.dump(retro, f, indent=2, sort_keys=True, default=str)
    md = block_retro.render_markdown(retro)
    with open(os.path.join(args.out, "retro.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print(md)
    if inputs["prior"] is None:
        print("WARNING: no prior RETRO# row and no baseline row: no movers. Store the baseline first (`baseline`).")
    print(f"wrote {args.out}/retro.json and retro.md — panel {retro['panel'].get('status')}; nothing stored (run `store`)")
    return 0


def prediction_update(p: dict[str, Any], graded_at: str) -> dict[str, Any]:
    """The conditional update for one graded prediction: its verdict, only while it is still open."""
    return {
        "Key": {"pk": CLAIMS_PK, "sk": p["sk"]},
        "UpdateExpression": "SET #s = :v, block_retro_grade = :g",
        "ConditionExpression": "#s = :open",
        "ExpressionAttributeNames": {"#s": "status"},
        "ExpressionAttributeValues": {
            ":v": p["verdict"],
            ":open": block_retro.PREDICTION_OPEN_STATUSES[0],
            ":g": {"verdict": p["verdict"], "evidence": json.dumps(p["evidence"], sort_keys=True, default=str), "graded_at": graded_at},
        },
    }


def cmd_store(args: argparse.Namespace) -> int:
    from datetime import datetime, timezone

    retro = json.load(open(args.retro, encoding="utf-8"))
    item = block_retro.retro_item(retro, USER_PK)
    graded_at = datetime.now(timezone.utc).isoformat()
    preds = [p for p in retro.get("predictions") or [] if p.get("verdict") in ("confirmed", "refuted", "inconclusive")]
    if not args.apply:
        print(f"DRY RUN — would put {item['pk']} / {item['sk']} and grade {len(preds)} charter prediction(s):")
        print(json.dumps({**item, "graded_at": "<stamped at apply>"}, indent=2, sort_keys=True, default=str))
        for p in preds:
            print(f"  {p['sk']}: observation -> {p['verdict']}")
        return 0
    from experiment.phase_taxonomy import experiment_stamp_for

    item.update(experiment_stamp_for(item["pk"], item["sk"]))
    item["graded_at"] = graded_at
    table = _table()
    table.put_item(Item=json.loads(json.dumps(item, default=str), parse_float=Decimal))
    print(f"stored {item['sk']}")
    for p in preds:
        try:
            table.update_item(**prediction_update(p, graded_at))
            print(f"graded {p['sk']}: {p['verdict']}")
        except Exception as e:  # noqa: BLE001 — a row already graded is reported, never re-graded
            code = getattr(e, "response", {}).get("Error", {}).get("Code")
            if code != "ConditionalCheckFailedException":
                raise
            print(f"already graded, left as is: {p['sk']}")
    return 0


def cmd_baseline(args: argparse.Namespace) -> int:
    from datetime import datetime, timezone

    sc = block_retro.load_scorecard()
    if sc is None:
        print("config/training_scorecard.json unreadable")
        return 1
    letters = json.load(open(args.letters, encoding="utf-8"))
    item = block_retro.baseline_item(letters, sc, USER_PK)
    if not args.apply:
        print(f"DRY RUN — would put {item['pk']} / {item['sk']} (owner-only, {len(item['rows'])} rows); nothing written")
        return 0
    from experiment.phase_taxonomy import experiment_stamp_for

    item.update(experiment_stamp_for(item["pk"], item["sk"]))
    item["graded_at"] = datetime.now(timezone.utc).isoformat()
    try:
        _table().put_item(Item=item, ConditionExpression="attribute_not_exists(sk)")
    except Exception as e:  # noqa: BLE001 — an already-stored baseline is reported, never overwritten
        if getattr(e, "response", {}).get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        print(f"already stored, left as is: {item['sk']}")
        return 0
    print(f"stored {item['sk']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grade", help="read-only: assemble the evidence and grade the block")
    g.add_argument("--block-end", required=True, help="the block's last day (a Sunday, YYYY-MM-DD)")
    g.add_argument("--supplied", help="JSON of the counts the skill read through MCP tools (see the skill)")
    g.add_argument("--overrides", help="JSON {row_id: {letter, reason}} — the session's recorded departures")
    g.add_argument("--no-panel", action="store_true", help="skip the panel re-grade (code scores only, no AI spend)")
    g.add_argument("--out", required=True, help="a directory for retro.json and retro.md")
    s = sub.add_parser("store", help="write the RETRO# row and the prediction verdicts (dry-run unless --apply)")
    s.add_argument("--retro", required=True, help="the retro.json `grade` wrote")
    s.add_argument("--apply", action="store_true", help="write to DynamoDB (default: dry-run)")
    b = sub.add_parser("baseline", help="write the one-time owner-only baseline row (dry-run unless --apply)")
    b.add_argument("--letters", required=True, help="JSON {row_id: letter} from the PRIVATE review doc, kept outside the repo")
    b.add_argument("--apply", action="store_true", help="write to DynamoDB (default: dry-run)")
    args = ap.parse_args(argv)
    return {"grade": cmd_grade, "store": cmd_store, "baseline": cmd_baseline}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
