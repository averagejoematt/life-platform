#!/usr/bin/env python3
"""apply_habit_pause.py — set `paused_since` on the profile's supplement habits (#5007).

The habit registry lives in the PROFILE#v1 row's `habit_registry` map (owner data, not in the
repo), so the facet reaches it by one owner-run DynamoDB update per entry. Dry-run by default:
prints COUNTS only (habit names are owner data); `--apply` writes. Idempotent. Never touches
Habitify. `--exclude NAME` leaves an entry scheduled (repeatable); `--clear` removes the facet.

    python3 scripts/apply_habit_pause.py                      # preview
    python3 scripts/apply_habit_pause.py --apply
    python3 scripts/apply_habit_pause.py --apply --exclude "Protein Supplement"
"""

from __future__ import annotations

import argparse

import boto3

TABLE = "life-platform"
KEY = {"pk": "USER#matthew", "sk": "PROFILE#v1"}
DEFAULT_SINCE = "2026-10-10"


def targets(registry: dict, category: str, exclude: set[str]) -> list[str]:
    return sorted(n for n, m in registry.items() if isinstance(m, dict) and m.get("category") == category and n not in exclude)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", default=DEFAULT_SINCE)
    ap.add_argument("--category", default="supplement")
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    table = boto3.resource("dynamodb", region_name="us-west-2").Table(TABLE)
    registry = table.get_item(Key=KEY).get("Item", {}).get("habit_registry") or {}
    names = targets(registry, a.category, set(a.exclude))
    print(
        f"{len(names)} of {len(registry)} registry entries in category {a.category!r} "
        f"({'clear' if a.clear else 'paused_since=' + a.since})"
    )
    if not a.apply:
        print("dry-run: nothing written (pass --apply)")
        return 0
    for n in names:
        if a.clear:
            table.update_item(Key=KEY, UpdateExpression="REMOVE habit_registry.#n.paused_since", ExpressionAttributeNames={"#n": n})
        else:
            table.update_item(
                Key=KEY,
                UpdateExpression="SET habit_registry.#n.paused_since = :d",
                ExpressionAttributeNames={"#n": n},
                ExpressionAttributeValues={":d": a.since},
            )
    print(f"applied to {len(names)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
