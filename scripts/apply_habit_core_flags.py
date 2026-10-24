#!/usr/bin/env python3
"""apply_habit_core_flags.py — set the `core` flag on the profile's habit_registry entries (#5124, M4).

The charter's `habits.core` (config/training_charter.json) names the core-12 calculation set by id; a
Habitify-basis core habit is read from the registry entries whose `core` field is that id. The registry
lives in the PROFILE#v1 row (owner data, not in the repo), so the flag reaches it by one owner-run
DynamoDB update per entry — the same channel as scripts/apply_habit_pause.py. Never touches Habitify.

Dry-run by default: validates every pair and prints COUNTS only (habit names are owner data); `--apply`
writes. Idempotent. `--set ID=KEY` is repeatable, and one id may take several entries (a core habit
held only when every member is held). `--clear` removes every `core` flag (the set is then unarmed and
the habit score is the tier-weighted read again). Derived-basis ids (steps, the check-in, out of bed on
time) carry no registry flag and are refused.

    python3 scripts/apply_habit_core_flags.py --set weigh_in="<registry key>" ...            # preview
    python3 scripts/apply_habit_core_flags.py --set weigh_in="<registry key>" ... --apply
    python3 scripts/apply_habit_core_flags.py --clear --apply

Then `python3 scripts/check_habit_registry_drift.py --live` must print HABIT-REGISTRY-DRIFT: OK.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLE = "life-platform"
KEY = {"pk": "USER#matthew", "sk": "PROFILE#v1"}


def _core_habits():
    if str(ROOT / "lambdas") not in sys.path:
        sys.path.insert(0, str(ROOT / "lambdas"))
    from health import core_habits  # noqa: E402

    return core_habits


def plan(registry: dict, pairs: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """`([(registry_key, core_id), ...], [error, ...])` — errors carry no habit name (the key is owner data)."""
    core = _core_habits()
    habitify_ids = {e["id"] for e in core.core_spec() if e["basis"] == "habitify"}
    derived = {e["id"] for e in core.core_spec() if e["basis"] != "habitify"}
    writes, errors, seen = [], [], set()
    for i, raw in enumerate(pairs, 1):
        cid, sep, key = raw.partition("=")
        cid, key = cid.strip(), key.strip()
        if not sep or not cid or not key:
            errors.append(f"--set #{i}: expected ID=KEY")
        elif cid in derived:
            errors.append(f"--set #{i}: {cid!r} is a derived-basis core habit; it carries no registry flag")
        elif cid not in habitify_ids:
            errors.append(f"--set #{i}: {cid!r} is not a Habitify-basis id in habits.core")
        elif not isinstance(registry.get(key), dict):
            errors.append(f"--set #{i} ({cid}): no registry entry has that key")
        elif registry[key].get("status") != "active":
            errors.append(f"--set #{i} ({cid}): that registry entry is not active")
        elif key in seen:
            errors.append(f"--set #{i} ({cid}): that registry entry is already in this run")
        else:
            seen.add(key)
            writes.append((key, cid))
    return writes, errors


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", dest="pairs", action="append", default=[], metavar="ID=KEY")
    ap.add_argument("--clear", action="store_true", help="remove every core flag")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    if bool(a.pairs) == a.clear:
        ap.error("pass --set ID=KEY (repeatable) or --clear, not both")
    import boto3  # noqa: PLC0415 — lazy, so plan() is testable offline

    table = boto3.resource("dynamodb", region_name="us-west-2").Table(TABLE)
    registry = table.get_item(Key=KEY).get("Item", {}).get("habit_registry") or {}
    core = _core_habits()
    if a.clear:
        names = sorted(k for k, m in registry.items() if core.flag_of(m))
        print(f"clear: {len(names)} of {len(registry)} registry entries carry a core flag")
        if not a.apply:
            print("dry-run: nothing written (pass --apply)")
            return 0
        for n in names:
            table.update_item(Key=KEY, UpdateExpression="REMOVE habit_registry.#n.#c", ExpressionAttributeNames={"#n": n, "#c": core.FLAG})
        print(f"cleared {len(names)} entries")
        return 0
    writes, errors = plan(registry, a.pairs)
    for e in errors:
        print("ERROR " + e)
    after = {k: dict(m) for k, m in registry.items() if isinstance(m, dict)}
    for k, cid in writes:
        after[k][core.FLAG] = cid
    drift = core.flag_drift(after)
    print(f"{len(writes)} flag(s) to set across {len({c for _, c in writes})} core id(s); after: {drift}")
    if errors:
        print("refused: fix the errors above; nothing written")
        return 1
    if not a.apply:
        print("dry-run: nothing written (pass --apply)")
        return 0
    for k, cid in writes:
        table.update_item(
            Key=KEY,
            UpdateExpression="SET habit_registry.#n.#c = :c",
            ExpressionAttributeNames={"#n": k, "#c": core.FLAG},
            ExpressionAttributeValues={":c": cid},
        )
    print(f"applied {len(writes)} flag(s); now run scripts/check_habit_registry_drift.py --live")
    return 0


if __name__ == "__main__":
    sys.exit(main())
