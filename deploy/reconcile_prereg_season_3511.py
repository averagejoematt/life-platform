#!/usr/bin/env python3
"""reconcile_prereg_season_3511.py — put the SEALED bets back in the season (#3511).

THE DEFECT THIS REPAIRS (measured live 2026-09-17, cycle 17, genesis 2026-09-06)
────────────────────────────────────────────────────────────────────────────────
All 16 pre-registered bets in `deploy/generated/genesis_preregistration.json` exist in
DynamoDB, carry `pre_registered=True` and `pre_registered_at=2026-09-06T02:13:38Z`, and
are stamped **`phase=pilot, cycle=16`** — the closing cycle. The attended seed ran at
2026-09-06T02:13:38Z, which is 2026-09-05 19:13 PT: still pre-genesis, so
`experiment_stamp()` truthfully said "pilot". Nothing re-stamps a `COACH#*` row
(`restart_phase_tag.py` only reaches `USER#matthew#SOURCE#*`), so all 16 fail
`PHASE_FILTER_EXPRESSION` permanently. The cycle's entire pre-registration is invisible
on /api/predictions and ungradeable, while nine unsealed Day-1 coach calls ARE served.

The durable fix is in the seeder (`genesis_cycle_stamp()`, same PR) — it stamps for the
genesis the freeze is FOR, not for the clock. This script is the one-time repair for the
rows already written that way.

WHAT IT TOUCHES, AND NOTHING ELSE
─────────────────────────────────
Exactly the rows whose `prediction_id` is derived from the frozen artifact's own claims
(`prereg_provenance_gate.frozen_prediction_ids`), that are NOT tombstoned, and that are
NOT already in the season. For each it sets `phase` and `cycle` to the genesis cycle
from `CYCLE_GENESES`. It never writes a row it did not read, never tombstones, never
creates, and never touches a row the artifact does not seal — in particular it does NOT
touch the 10 stale `PREDICTION#docket-…-2026-08-03` rows the #3511 gate also reports
(cross-cycle dispute-docket survivors: a different defect, filed separately).

DRY RUN IS THE DEFAULT. `--apply` is the only path that writes.

Usage:
    python3 deploy/reconcile_prereg_season_3511.py            # plan only (read-only)
    python3 deploy/reconcile_prereg_season_3511.py --apply    # write phase/cycle
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT), str(REPO_ROOT / "deploy"), str(REPO_ROOT / "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import prereg_provenance_gate as gate  # noqa: E402
from seed_genesis_preregistration import genesis_cycle_stamp  # noqa: E402


def plan(rows: list[dict], frozen: dict, stamp: dict) -> list[dict]:
    """Pure: the UpdateItem plan. One entry per out-of-season sealed row."""
    sealed = gate.frozen_prediction_ids(frozen)
    planned = []
    for row in rows:
        if row.get("tombstone"):
            continue
        if gate._row_id(row) not in sealed:
            continue
        if gate.in_season(row):
            continue
        planned.append(
            {
                "pk": row["pk"],
                "sk": row["sk"],
                "from": {"phase": row.get("phase"), "cycle": row.get("cycle")},
                "to": dict(stamp),
            }
        )
    return planned


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Re-stamp the sealed pre-registration rows into the season (#3511)")
    ap.add_argument("--apply", action="store_true", help="write the plan (default: dry run, read-only)")
    args = ap.parse_args(argv)

    frozen = gate.load_frozen()
    genesis = frozen["genesis"]
    stamp = genesis_cycle_stamp(genesis)
    if not stamp:
        print(f"REFUSING: CYCLE_GENESES names no cycle for genesis {genesis!r} — will not guess a cycle number.")
        return 2

    rows = gate.fetch_season_prediction_rows(frozen)
    steps = plan(rows, frozen, stamp)
    print(f"genesis {genesis} · target stamp {stamp} · {len(rows)} PREDICTION# rows read · {len(steps)} to re-stamp\n")
    for s in steps:
        print(f"  {s['pk']} / {s['sk']}\n      {s['from']}  ->  {s['to']}")
    if not steps:
        print("nothing to do — every sealed bet is already in the season.")
        return 0
    if not args.apply:
        print("\nDRY RUN — re-run with --apply to write.")
        return 0

    import boto3

    table = boto3.resource("dynamodb", region_name=gate.REGION).Table(gate.TABLE_NAME)
    for s in steps:
        table.update_item(
            Key={"pk": s["pk"], "sk": s["sk"]},
            UpdateExpression="SET #p = :p, #c = :c, reconciled_by = :r",
            ExpressionAttributeNames={"#p": "phase", "#c": "cycle"},
            ExpressionAttributeValues={
                ":p": s["to"]["phase"],
                ":c": s["to"]["cycle"],
                ":r": "reconcile_prereg_season_3511.py",
            },
        )
        print(f"  RESTAMPED {s['pk']} / {s['sk']}")
    remaining = gate.blocking(gate.audit_prereg_provenance(gate.fetch_season_prediction_rows(frozen), frozen, as_of=genesis))
    print(f"\npost-apply audit: {len(remaining)} blocking finding(s) remain")
    return 0


if __name__ == "__main__":
    sys.exit(main())
