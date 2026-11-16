#!/usr/bin/env python3
"""write_walk_correction.py — record the owner's ruling on a walk no counted source holds (#5669).

The walking layer (`lambdas/training/walking_volume.py`) counts a `WALK_CORRECTION#<YYYY-MM-DD>` row in
the owner-only `training_constraints` partition as a labelled walk (method `owner_correction`) on a day
with no counted walk, and it resolves that day's walk-signal gap. Vendor partitions hold vendor data only
(capture-all), so a correction never goes into `strava` or `whoop`.

DRY RUN by default: prints the row and writes nothing. `--apply` writes it with a conditional PutItem
(`attribute_not_exists(sk)`): an existing correction for the day is reported and NEVER overwritten — to
change one, tombstone the old row by hand first, so the record of what was ruled is kept.

    python3 scripts/write_walk_correction.py --date 2026-10-20 --minutes 55 \\
        --basis "..." --ruled-at 2026-11-09 --issue '#5669'            # dry run
    ... --apply                                                         # the write
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))

from training import walking_volume  # noqa: E402

TABLE = "life-platform"
REGION = "us-west-2"


def _table() -> Any:
    import boto3
    from botocore.config import Config

    return boto3.resource("dynamodb", region_name=REGION, config=Config(read_timeout=60, retries={"max_attempts": 3})).Table(TABLE)


def build_item(*, day: str, minutes: float, basis: str, ruled_by: str, ruled_at: str, issue: str, kind: str = "outdoor_walk") -> dict:
    """The correction row. Raises ValueError on a malformed day, kind or minutes — nothing is guessed."""
    date.fromisoformat(day)  # raises on a bad day key
    date.fromisoformat(ruled_at[:10])
    if kind not in walking_volume.CORRECTION_KINDS:
        raise ValueError(f"kind must be one of {sorted(walking_volume.CORRECTION_KINDS)}, got {kind!r}")
    if not (0 < minutes <= 24 * 60):
        raise ValueError(f"minutes must be in (0, 1440], got {minutes}")
    if not basis.strip():
        raise ValueError("basis is required: say what the minutes rest on")
    return {
        "pk": walking_volume.CORRECTION_PK,
        "sk": walking_volume.CORRECTION_SK_PREFIX + day,
        "date": day,
        "minutes": Decimal(str(minutes)),
        "kind": kind,
        "basis": basis.strip(),
        "ruled_by": ruled_by,
        "ruled_at": ruled_at,
        "source": walking_volume.CORRECTION_METHOD,
        "issue": issue,
        "tier": "owner_only",
    }


def _show(item: dict) -> str:
    return json.dumps(item, default=lambda v: float(v) if isinstance(v, Decimal) else str(v), indent=2, sort_keys=True)


def main(argv: list[str] | None = None, table: Any = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--date", required=True, help="the walk's Pacific day, YYYY-MM-DD")
    ap.add_argument("--minutes", required=True, type=float, help="walking minutes the owner ruled")
    ap.add_argument("--basis", required=True, help="what the minutes rest on (free text)")
    ap.add_argument("--ruled-by", default="owner", help="who ruled (default: owner)")
    ap.add_argument("--ruled-at", required=True, help="the day of the ruling, YYYY-MM-DD")
    ap.add_argument("--issue", required=True, help="the issue carrying the ruling, e.g. '#5669'")
    ap.add_argument("--kind", default="outdoor_walk", help="the walk's kind (default: outdoor_walk)")
    ap.add_argument("--apply", action="store_true", help="write to DynamoDB (default: dry run)")
    args = ap.parse_args(argv)
    try:
        item = build_item(
            day=args.date,
            minutes=args.minutes,
            basis=args.basis,
            ruled_by=args.ruled_by,
            ruled_at=args.ruled_at,
            issue=args.issue,
            kind=args.kind,
        )
    except ValueError as e:
        print(f"refused: {e}")
        return 2
    if not args.apply:
        print("DRY RUN — would put (conditional on no existing row for the day); nothing written:")
        print(_show(item))
        return 0
    from experiment.phase_taxonomy import experiment_stamp_for

    item.update(experiment_stamp_for(item["pk"], item["sk"]))
    item["recorded_at"] = datetime.now(timezone.utc).isoformat()
    try:
        (table if table is not None else _table()).put_item(Item=item, ConditionExpression="attribute_not_exists(sk)")
    except Exception as e:  # noqa: BLE001 — an existing correction is reported, never overwritten
        if getattr(e, "response", {}).get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        print(f"a correction for {args.date} already exists — left as is: {item['sk']}")
        return 1
    print("stored:")
    print(_show(item))
    return 0


if __name__ == "__main__":
    sys.exit(main())
