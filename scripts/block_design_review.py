#!/usr/bin/env python3
"""block_design_review.py — the /training-review block design review: a proposal, then the owner's approval (#5776).

`lambdas/training/block_design_review.py` is pure. This is its wiring on the owner's workstation, in two phases so the
proposal is read before anything is stored and the AWS write is a separate, deliberate act:

  propose   READ-ONLY. For block N, reads the exercise library (`config/exercise_library.json`), the movement catalog,
            the owner-private overlay (env / the gitignored local file / S3 GetObject), the rotation ledger rows for
            blocks N-1..N, the prior block's approval row and the latest #5772 gate evaluation (`EXGATE#EVAL#`, only
            its `state`/`input` fields are used) — each fail-soft and named in `reads` — runs the selection engine for
            the block's first week and writes `proposal.json` + `proposal.md` to `--out` (an OWNER-ONLY scratch dir,
            never inside the repo). `--volume-response <json>` carries #5801's report in; `--experiment <json>` fills
            the experiment slot (empty by default); `--narrate` adds the ONE model narration (fail-soft).
  approve   THE WRITE (dry-run unless `--apply`). Builds the owner-only `training_constraints / BLOCKREVIEW#APPROVED#B<nnn>`
            row from a `proposal.json`, every slot as proposed unless `--decisions <json>` {slot_id: catalog_key |
            "incumbent"} departs. `--apply` is the owner's word in the session; never a lane, never a schedule.

    python3 scripts/block_design_review.py propose --block 3 --out <scratch>/block-3 [--volume-response <scratch>/volume_response.json]
    python3 scripts/block_design_review.py approve --proposal <scratch>/block-3/proposal.json            # dry run
    python3 scripts/block_design_review.py approve --proposal <scratch>/block-3/proposal.json --apply    # the write
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

from training import block_design_review as bdr  # noqa: E402

TABLE = "life-platform"
REGION = "us-west-2"


def _table() -> Any:
    import boto3
    from botocore.config import Config

    return boto3.resource("dynamodb", region_name=REGION, config=Config(read_timeout=60, retries={"max_attempts": 3})).Table(TABLE)


def _plain(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=lambda o: int(o) if isinstance(o, Decimal) and o == int(o) else float(o)))


def _inside_repo(path: str) -> bool:
    return os.path.realpath(path).startswith(os.path.realpath(_ROOT) + os.sep)


def _load_json(path: str | None) -> Any:
    if not path:
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def latest_gate_eval(table: Any) -> dict[str, Any] | None:
    """The newest #5772 `EXGATE#EVAL#<monday>` row (read-only), or None when none is stored yet."""
    from boto3.dynamodb.conditions import Key

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(bdr.pk()) & Key("sk").begins_with("EXGATE#EVAL#"), ScanIndexForward=False, Limit=1
    )
    items = resp.get("Items") or []
    return _plain(items[0]) if items else None


def gather(block: int, table: Any = None) -> dict[str, Any]:
    """Every read the proposal needs, each fail-soft and named. Read-only."""
    from training import exercise_library as xl, variant_rotation as vr

    reads: dict[str, str] = {}
    out: dict[str, Any] = {"reads": reads}
    try:
        out["lib"] = xl.load_library()
        reads["library"] = "ok"
    except (OSError, ValueError) as e:
        raise SystemExit(f"the exercise library is unreadable ({type(e).__name__}) — no proposal without it")
    with open(os.path.join(_ROOT, "config", "movement_catalog.json"), encoding="utf-8") as f:
        out["catalog"] = json.load(f)["movements"]
    reads["catalog"] = "ok"
    out["overlay"] = xl.load_private_overlay(allow_s3=True)
    reads["overlay"] = "ok" if isinstance(out["overlay"], dict) else "absent (N=1 fit unknown)"
    try:
        table = table or _table()
    except Exception as e:  # noqa: BLE001
        table, reads["ddb"] = None, f"read_failed: {type(e).__name__}"
    rows, reads["ledger"] = vr.load_rows_failsoft(block, table) if table is not None else (None, "not_read")
    out["rows"] = _plain(rows) if rows else rows
    try:
        approvals = _plain(bdr.load_rows(block - 1, table)) if table is not None and block > 1 else []
        out["prior"] = next((r for r in approvals if r.get("sk") == bdr.approval_sk(block - 1)), None)
        reads["prior_approval"] = "ok" if out["prior"] else "none"
    except Exception as e:  # noqa: BLE001
        out["prior"], reads["prior_approval"] = None, f"read_failed: {type(e).__name__}"
    try:
        out["gate_eval"] = latest_gate_eval(table) if table is not None else None
        reads["gate_eval"] = "ok" if out["gate_eval"] else "none stored (every gate reads 'not evaluated yet')"
    except Exception as e:  # noqa: BLE001
        out["gate_eval"], reads["gate_eval"] = None, f"read_failed: {type(e).__name__}"
    return out


def cmd_propose(args: argparse.Namespace) -> int:
    from training import selection_engine as se

    if _inside_repo(args.out):
        print("refusing: --out is inside the repo; the proposal is owner-only. Use a scratch directory outside it.")
        return 1
    g = gather(args.block)
    sel = se.select_week(bdr.block_position(args.block), g["catalog"], g["lib"], g["overlay"], rows=g["rows"])
    vol = _load_json(args.volume_response)
    g["reads"]["volume_response"] = "supplied" if vol else "not supplied"
    proposal = bdr.build_proposal(
        args.block,
        sel,
        g["lib"],
        g["catalog"],
        rows=g["rows"],
        prior=g["prior"],
        gate_eval=g["gate_eval"],
        volume_report=vol,
        experiment=_load_json(args.experiment),
        reads=g["reads"],
    )
    narration = bdr.narrate(proposal) if args.narrate else None
    if narration:
        proposal["narration"] = narration
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "proposal.json"), "w", encoding="utf-8") as f:
        json.dump(proposal, f, indent=2, sort_keys=True, default=str)
    md = bdr.render_markdown(proposal, narration)
    with open(os.path.join(args.out, "proposal.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print(md)
    print(f"wrote {args.out}/proposal.json and .md (owner-only; nothing stored — approve with `approve --proposal`)")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    from datetime import datetime, timezone

    proposal = _load_json(args.proposal)
    item = bdr.approval_item(proposal, _load_json(args.decisions), approved_at=datetime.now(timezone.utc).isoformat())
    if not args.apply:
        print(f"DRY RUN — would put {item['pk']} / {item['sk']} (owner-only, {len(item['pins'])} slot pin(s)); nothing written")
        print(json.dumps(item, indent=2, sort_keys=True, default=str))
        return 0
    from experiment.phase_taxonomy import experiment_stamp_for

    item.update(experiment_stamp_for(item["pk"], item["sk"]))
    _table().put_item(Item=json.loads(json.dumps(item, default=str), parse_float=Decimal))
    print(f"stored {item['sk']} — drafting honours it as owner pins for block {item['block']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("propose", help="read-only: the block's selection proposal for owner approval")
    p.add_argument("--block", type=int, required=True, help="the NEW block's number (the session sequence's block)")
    p.add_argument("--out", required=True, help="an OWNER-ONLY scratch directory (never inside the repo)")
    p.add_argument("--volume-response", help="the volume_response.json `training_block_retro.py volume-response` wrote (#5801)")
    p.add_argument("--experiment", help="JSON {slot_id, technique, experiment_id, catalog_key?, hypothesis?, outcome_metric?}")
    p.add_argument("--narrate", action="store_true", help="add the ONE model narration (budget-aware, fail-soft)")
    a = sub.add_parser("approve", help="write the owner-only approval row (dry-run unless --apply)")
    a.add_argument("--proposal", required=True, help="the proposal.json `propose` wrote")
    a.add_argument("--decisions", help='JSON {slot_id: catalog_key | "incumbent"} — the owner\'s departures from the proposal')
    a.add_argument("--apply", action="store_true", help="write to DynamoDB (default: dry-run)")
    args = ap.parse_args(argv)
    return {"propose": cmd_propose, "approve": cmd_approve}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
