#!/usr/bin/env python3
"""scripts/blast_radius.py — blast-radius queries over the system model (#2845).

Answers what-touches-X / what-does-X-feed as a lookup against
``model/platform_model.json`` (regenerate with scripts/generate_platform_model.py;
CI keeps it current via tests/test_platform_model_drift.py).

  python3 scripts/blast_radius.py --touches day_grade      # who reads/writes a partition
  python3 scripts/blast_radius.py --feeds daily_brief_lambda.py   # what a module reads/writes,
                                                           # and who consumes what it writes
  python3 scripts/blast_radius.py --list                   # partitions with edge counts
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "model" / "platform_model.json"


def _load() -> dict:
    if not MODEL_PATH.exists():
        sys.exit("model/platform_model.json missing — run: python3 scripts/generate_platform_model.py")
    return json.loads(MODEL_PATH.read_text(encoding="utf-8"))


def _module_matches(edge_module: str, query: str) -> bool:
    return edge_module == query or edge_module.endswith("/" + query) or edge_module.rsplit("/", 1)[-1] == query


def touches(model: dict, partition: str) -> int:
    edges = [e for e in model["edges"] if e["partition"] == partition]
    if not edges:
        known = partition in model["partitions"]
        print(f"no edges for partition {partition!r}" + ("" if known else " (not in the ADR-077 census either — check the spelling)"))
        return 1
    meta = model["partitions"].get(partition, {})
    print(f"partition {partition}  (class: {meta.get('class', '?')}, ingestion: {meta.get('ingestion', False)})")
    for direction in ("write", "read", "unknown"):
        modules = sorted({e["module"] for e in edges if e["direction"] == direction})
        if modules:
            print(f"  {direction} ({len(modules)}):")
            for module in modules:
                lam = next((e["lambda"] for e in edges if e["module"] == module and e["lambda"]), None)
                print(f"    {module}" + (f"  [{lam}]" if lam else ""))
    return 0


def feeds(model: dict, module: str) -> int:
    mine = [e for e in model["edges"] if _module_matches(e["module"], module)]
    if not mine:
        print(f"no edges for module {module!r} — try the file basename (e.g. daily_brief_lambda.py)")
        return 1
    print(f"module {sorted({e['module'] for e in mine})[0]}")
    reads = sorted({e["partition"] for e in mine if e["direction"] == "read"})
    writes = sorted({e["partition"] for e in mine if e["direction"] == "write"})
    other = sorted({e["partition"] for e in mine if e["direction"] == "unknown"} - set(reads) - set(writes))
    if reads:
        print(f"  reads ({len(reads)}): " + ", ".join(reads))
    if writes:
        print(f"  writes ({len(writes)}): " + ", ".join(writes))
    if other:
        print(f"  references, direction unknown ({len(other)}): " + ", ".join(other))
    for part in writes:
        readers = sorted(
            {
                e["module"]
                for e in model["edges"]
                if e["partition"] == part and e["direction"] == "read" and not _module_matches(e["module"], module)
            }
        )
        if readers:
            print(f"  downstream of {part} ({len(readers)}):")
            for reader in readers:
                print(f"    {reader}")
    return 0


def list_partitions(model: dict) -> int:
    by_partition: dict[str, int] = {}
    for edge in model["edges"]:
        by_partition[edge["partition"]] = by_partition.get(edge["partition"], 0) + 1
    for part in sorted(model["partitions"]):
        print(f"{by_partition.get(part, 0):4d}  {part}  ({model['partitions'][part]['class']})")
    orphans = sorted(set(by_partition) - set(model["partitions"]))
    if orphans:
        print("\nedges to names OUTSIDE the ADR-077 census (seam args that are not partitions, or census gaps):")
        for part in orphans:
            print(f"{by_partition[part]:4d}  {part}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--touches", metavar="PARTITION", help="who reads/writes this partition")
    group.add_argument("--feeds", metavar="MODULE", help="what this module reads/writes + downstream readers")
    group.add_argument("--list", action="store_true", help="all partitions with edge counts")
    args = parser.parse_args()
    model = _load()
    if args.touches:
        return touches(model, args.touches)
    if args.feeds:
        return feeds(model, args.feeds)
    return list_partitions(model)


if __name__ == "__main__":
    raise SystemExit(main())
