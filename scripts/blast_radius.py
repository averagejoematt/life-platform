#!/usr/bin/env python3
"""scripts/blast_radius.py — blast-radius queries over the system model (#2845).

Answers what-touches-X / what-does-X-feed as a lookup against
``model/platform_model.json`` (regenerate with scripts/generate_platform_model.py;
CI keeps it current via tests/test_platform_model_drift.py).

  python3 scripts/blast_radius.py --touches day_grade      # who reads/writes a partition
  python3 scripts/blast_radius.py --feeds daily_brief_lambda.py   # what a module reads/writes,
                                                           # and who consumes what it writes
  python3 scripts/blast_radius.py --list                   # partitions with edge counts
  python3 scripts/blast_radius.py --alarm ingest-liveness-unhealthy   # routing, kind, composites (#3314)
  python3 scripts/blast_radius.py --at 16                  # what runs in UTC hour 16 (or --at 16:00)
  python3 scripts/blast_radius.py --privacy withings       # tier, owner-only fields, and who reads it
  python3 scripts/blast_radius.py --lambda cost-governor   # stack, schedule, alarm, edges — one card
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


def alarm(model: dict, name: str) -> int:
    """One alarm's operator card: where it is declared, how it routes, what it belongs to."""
    rec = model.get("alarms", {}).get(name)
    if rec is None:
        near = sorted(a for a in model.get("alarms", {}) if name in a)
        print(f"no alarm {name!r} in the model" + (f" — near: {', '.join(near[:8])}" if near else ""))
        return 1
    print(f"alarm {name}  (stack: {rec['stack']}, kind: {rec.get('kind', 'metric')})")
    print(f"  routing: {rec['routing']}   via: {rec.get('via', 'declaration')}")
    if rec.get("members"):
        print(f"  members ({len(rec['members'])}): " + ", ".join(rec["members"]))
    if rec.get("composites"):
        print("  member of: " + ", ".join(rec["composites"]))
    owners = sorted(n for n, lam in model["lambdas"].items() if lam.get("declared_alarm") == name)
    if owners:
        print("  declared by lambda: " + ", ".join(owners))
    return 0


def at(model: dict, when: str) -> int:
    """What runs at a UTC hour (`16`) or minute (`16:00`), from the schedules plane."""
    rows = model.get("schedules", [])
    key = when.zfill(2) if ":" not in when else when
    hits = [r for r in rows if r.get("utc") and (r["utc"] == key or (":" not in when and r["utc"].startswith(key + ":")))]
    if not hits:
        print(f"nothing fixed-time at {when} UTC ({sum(1 for r in rows if r.get('utc'))} fixed-time rows; rate() rows have no clock)")
        return 1
    for r in hits:
        print(f"  {r['utc']}Z  {r['lambda']}  [{r['stack']}]  {r['expr']}")
    return 0


def privacy(model: dict, source: str) -> int:
    """A source's tier, its owner-only fields, and every reader — the blast radius of a tier change."""
    priv = model.get("privacy", {})
    tier = priv.get("sources", {}).get(source)
    fields = priv.get("fields", {}).get(source, {})
    if tier is None and not fields and source not in model["partitions"]:
        print(f"no source {source!r} in the census or the privacy registry")
        return 1
    print(f"source {source}  tier: {tier or 'public (unlisted — public by omission)'}")
    if fields:
        by_tier: dict[str, list[str]] = {}
        for f, t in sorted(fields.items()):
            by_tier.setdefault(t, []).append(f)
        for t, fs in sorted(by_tier.items()):
            print(f"  {t} fields ({len(fs)}): " + ", ".join(fs))
    readers = sorted({e["module"] for e in model["edges"] if e["partition"] == source and e["direction"] == "read"})
    if readers:
        print(f"  readers ({len(readers)}):")
        for r in readers:
            print(f"    {r}")
    return 0


def lambda_card(model: dict, name: str) -> int:
    rec = model["lambdas"].get(name)
    if rec is None:
        near = sorted(n for n in model["lambdas"] if name in n)
        print(f"no lambda {name!r}" + (f" — near: {', '.join(near[:8])}" if near else ""))
        return 1
    print(f"lambda {name}  [{rec['stack']}]  handler: {rec['handler']}  timeout: {rec['timeout_seconds']}s  memory: {rec['memory_mb']}")
    for s in rec["schedules"]:
        print(f"  schedule: {s['expr']} ({s['resolution']})")
    if rec.get("declared_alarm"):
        a = model.get("alarms", {}).get(rec["declared_alarm"], {})
        print(f"  alarm: {rec['declared_alarm']} → {a.get('routing', '?')}")
    module = rec.get("module")
    if module:
        mine = [e for e in model["edges"] if e["module"] == module]
        for direction in ("write", "read"):
            parts = sorted({e["partition"] for e in mine if e["direction"] == direction})
            if parts:
                print(f"  {direction}s ({len(parts)}): " + ", ".join(parts))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--touches", metavar="PARTITION", help="who reads/writes this partition")
    group.add_argument("--feeds", metavar="MODULE", help="what this module reads/writes + downstream readers")
    group.add_argument("--list", action="store_true", help="all partitions with edge counts")
    group.add_argument("--alarm", metavar="NAME", help="one alarm: routing, kind, composites, declaring lambda (#3314)")
    group.add_argument("--at", metavar="HH[:MM]", help="what runs at this UTC hour/minute (#3314)")
    group.add_argument("--privacy", metavar="SOURCE", help="a source's privacy tier, restricted fields, readers (#3314)")
    group.add_argument("--lambda", dest="lambda_name", metavar="NAME", help="one lambda's card: schedule, alarm, edges (#3314)")
    args = parser.parse_args()
    model = _load()
    if args.touches:
        return touches(model, args.touches)
    if args.feeds:
        return feeds(model, args.feeds)
    if args.alarm:
        return alarm(model, args.alarm)
    if args.at:
        return at(model, args.at)
    if args.privacy:
        return privacy(model, args.privacy)
    if args.lambda_name:
        return lambda_card(model, args.lambda_name)
    return list_partitions(model)


if __name__ == "__main__":
    raise SystemExit(main())
