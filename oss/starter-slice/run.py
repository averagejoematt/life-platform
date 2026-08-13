#!/usr/bin/env python3
"""starter-slice command line.

    python3 run.py ingest --local          # fetch + store, on your disk, free
    python3 run.py chart  --local          # read the table, write out/chart.html
    python3 run.py cost                    # what this costs, and what the full platform costs
    python3 run.py ingest                  # the same pipeline against real S3 + DynamoDB

The AWS path needs credentials, the stack from infrastructure.yaml, and
SLICE_BUCKET / SLICE_TABLE. It costs real money -- see `cost`.
"""

import argparse
import sys

from starter_slice import config, cost, pipeline, store


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("ingest", "chart", "cost"))
    parser.add_argument("--local", action="store_true", help="use the on-disk backend instead of S3 + DynamoDB")
    parser.add_argument("--days", type=int, default=14, help="how many settled days to fetch (default 14)")
    parser.add_argument("--out", default="out/chart.html", help="where to write the chart page")
    args = parser.parse_args(argv)

    if args.command == "cost":
        print("\n".join(cost.lines()))
        return 0

    cfg = config.load()
    try:
        backend = store.open_store(cfg, args.local)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "ingest":
        rows = pipeline.ingest(cfg, backend, days=args.days)
        print(f"ingested {len(rows)} day(s) into the {backend.kind} backend under {cfg.partition_key}")
        if not rows:
            print("no settled readings in that window — try a longer --days", file=sys.stderr)
        return 0

    path = pipeline.render(cfg, backend, args.out)
    print(f"wrote {path} — open it in a browser")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
