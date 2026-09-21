#!/usr/bin/env python3
"""seed_protocols.py — seed `PROTOCOL#` rows from site/config/protocols.json (#3621 box 5).

Replaces the inline `python3 -c` heredoc that used to live in
`deploy/seed_protocols_to_dynamodb.sh` (which still exists and now delegates here). Two
reasons the body had to leave the shell string:

  * it is the ONLY `PROTOCOL#` writer in the repo, so it is where the write-time refusal
    has to live — `experiment.protocol_levers.build_protocol_item` refuses any lever
    whose `spawned_by` is absent or unrecognised, and a refusal inside a quoted heredoc
    is a refusal nothing can unit-test;
  * the heredoc had no dry-run. A seeder with no dry-run is one an operator runs blind.

DRY-RUN BY DEFAULT. `--apply` commits. Refusals are collected and reported TOGETHER, and
NOTHING is written if any lever is refused — a partial seed would leave the partition
half-linked, which grades as "some levers have provenance" and is the least readable of
the three possible states.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT), str(REPO_ROOT / "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from experiment.protocol_levers import PROTOCOLS_SOURCE, ProtocolLeverRefused, build_protocol_item  # noqa: E402

TABLE_NAME = "life-platform"
REGION = "us-west-2"
USER_ID = "matthew"
PK = f"USER#{USER_ID}#SOURCE#{PROTOCOLS_SOURCE}"
CONFIG = REPO_ROOT / "site" / "config" / "protocols.json"


def load_catalog(path: Path | None = None) -> list[dict]:
    data = json.loads((path or CONFIG).read_text(encoding="utf-8"))
    protocols = data.get("protocols")
    if not isinstance(protocols, list) or not protocols:
        raise SystemExit(f"{path or CONFIG}: no `protocols` list — refusing to seed an empty lever registry (#3621)")
    return protocols


def build_items(protocols: list[dict], pk: str = PK) -> list[dict]:
    """Every lever as a validated DDB item, or SystemExit naming every refusal at once."""
    items: list[dict] = []
    refusals: list[str] = []
    for p in protocols:
        try:
            items.append(build_protocol_item(p, pk=pk))
        except ProtocolLeverRefused as e:
            refusals.append(str(e))
    if refusals:
        raise SystemExit("seed_protocols: REFUSED — nothing written.\n  " + "\n  ".join(refusals))
    return items


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="Commit the put_items (default: dry-run).")
    ap.add_argument("--config", default=None, help=f"catalogue to seed from (default: {CONFIG})")
    args = ap.parse_args(argv)

    items = build_items(load_catalog(Path(args.config) if args.config else None))
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] {len(items)} protocol lever(s) -> {TABLE_NAME} {PK}")
    for item in items:
        print(f"  {item['sk']:<48} spawned_by={item['spawned_by']!r}")
    if not args.apply:
        print("\n(dry-run) — nothing written. Pass --apply to commit.")
        return 0

    import boto3

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    for item in items:
        table.put_item(Item=json.loads(json.dumps(item), parse_float=Decimal))
    print(f"\nDone. {len(items)} protocol lever(s) seeded.")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    sys.exit(main())
