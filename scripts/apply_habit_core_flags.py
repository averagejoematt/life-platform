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

#6090 — a PUBLIC ALIAS (a charter entry marked `id_alias`): the stored id stays owner data in the registry.
`--alias ALIAS` writes the private mapping — `core_alias: ALIAS` on every entry carrying the ONE `core` flag the
local charter no longer names (the stored id the alias replaced) — dry-run first, idempotent, then reads it back.
Run it from a checkout whose charter carries the alias, BEFORE the code that reads the alias deploys:

    python3 scripts/apply_habit_core_flags.py --alias core_h10            # preview (counts only)
    python3 scripts/apply_habit_core_flags.py --alias core_h10 --apply    # write + read-back

`--set ALIAS=KEY` flags KEY with the alias's STORED id (and the alias), never with the alias itself, so no new row
keys differently from the old ones; an alias with no mapping yet is refused. `--clear` refuses while any entry carries
a `core_alias` (removing it loses the only copy of the stored id) unless `--include-aliased` is passed.

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
    """`([(registry_key, core_id), ...], [error, ...])` — errors carry no habit name (the key is owner data). An aliased
    id (#6090) is written as its STORED id (`core_habits.alias_map`), so a newly flagged member keys like the old ones."""
    core = _core_habits()
    spec = core.core_spec()
    amap = core.alias_map(registry)
    aliases = {e["id"] for e in spec if e.get("id_alias")}
    resolved = core.resolve_spec(spec, registry)
    habitify_ids = {e["id"] for e in resolved if e["basis"] == "habitify"}
    derived = {e["id"] for e in spec if e["basis"] != "habitify"}
    direct = {core.flag_of(m) for m in (registry or {}).values()}  # an alias some entry already carries as its flag
    writes, errors, seen = [], [], set()
    for i, raw in enumerate(pairs, 1):
        cid, sep, key = raw.partition("=")
        cid, key = cid.strip(), key.strip()
        if cid in aliases and cid in amap:
            cid = amap[cid]  # the stored id: never printed below, the caller passed the public alias
        if not sep or not cid or not key:
            errors.append(f"--set #{i}: expected ID=KEY")
        elif cid in derived:
            errors.append(f"--set #{i}: {cid!r} is a derived-basis core habit; it carries no registry flag")
        elif cid in aliases and cid not in direct:
            errors.append(f"--set #{i}: {cid!r} is a public alias with no private mapping yet; run --alias {cid} first")
        elif cid not in habitify_ids:
            errors.append(f"--set #{i}: {cid!r} is not a Habitify-basis id in habits.core")
        elif not isinstance(registry.get(key), dict):
            errors.append(f"--set #{i}: no registry entry has that key")
        elif registry[key].get("status") != "active":
            errors.append(f"--set #{i}: that registry entry is not active")
        elif key in seen:
            errors.append(f"--set #{i}: that registry entry is already in this run")
        else:
            seen.add(key)
            writes.append((key, cid))
    return writes, errors


def alias_plan(registry: dict, alias: str) -> tuple[list[str], int, list[str]]:
    """#6090: `([registry_key to write], already_mapped, [error, ...])` for `--alias ALIAS` — the entries carrying the
    ONE `core` flag the local charter does not name (the stored id ALIAS replaced) get `core_alias: ALIAS`. Refuses
    when ALIAS is not an `id_alias` Habitify entry, when no or several such flags exist, or when an entry already maps
    elsewhere. Errors and counts carry no habit name and no stored id."""
    core = _core_habits()
    spec = core.core_spec()
    entry = next((e for e in spec if e["id"] == alias), None)
    if entry is None or not entry.get("id_alias") or entry["basis"] != "habitify":
        return [], 0, [f"{alias!r} is not a Habitify-basis id_alias entry in the local charter's habits.core"]
    named = {e["id"] for e in spec}
    reg = {k: m for k, m in (registry or {}).items() if isinstance(m, dict)}
    orphans = {core.flag_of(m) for m in reg.values() if core.flag_of(m) and core.flag_of(m) not in named}
    if not orphans:
        return [], 0, ["no registry entry carries a core flag the local charter does not name — nothing to map"]
    if len(orphans) > 1:
        return [], 0, [f"{len(orphans)} distinct core flags the charter does not name — cannot tell which one {alias} replaces"]
    stored = next(iter(orphans))
    writes, already, errors = [], 0, []
    for k, m in reg.items():
        if core.flag_of(m) != stored:
            continue
        have = m.get(core.ALIAS_FLAG)
        if have == alias:
            already += 1
        elif have:
            errors.append(f"an entry flagged for {alias} already carries a different {core.ALIAS_FLAG}")
        else:
            writes.append(k)
    return writes, already, errors


def alias_readback(registry: dict, alias: str) -> tuple[bool, str]:
    """`(ok, line)` — whether ALIAS resolves through the registry to a stored id with at least one active member and
    the flag drift is clean. The line is counts only (never a name, never the stored id)."""
    core = _core_habits()
    stored = core.alias_map(registry).get(alias)
    mem = core.members(registry).get(stored, []) if stored else []
    drift = core.flag_drift(registry)
    ok = bool(stored) and bool(mem) and not drift["core_flag_unknown"] and not drift["core_ids_unflagged"]
    return ok, f"alias {alias}: resolves={'yes' if stored else 'no'} active_members={len(mem)} drift={drift}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", dest="pairs", action="append", default=[], metavar="ID=KEY")
    ap.add_argument("--clear", action="store_true", help="remove every core flag")
    ap.add_argument("--include-aliased", action="store_true", help="with --clear: also clear entries carrying a core_alias")
    ap.add_argument("--alias", metavar="ALIAS", help="#6090: write the private mapping for a charter id_alias entry")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    if sum((bool(a.pairs), a.clear, bool(a.alias))) != 1:
        ap.error("pass exactly one of --set ID=KEY (repeatable), --clear or --alias ALIAS")
    import boto3  # noqa: PLC0415 — lazy, so plan() is testable offline

    table = boto3.resource("dynamodb", region_name="us-west-2").Table(TABLE)
    registry = table.get_item(Key=KEY).get("Item", {}).get("habit_registry") or {}
    core = _core_habits()
    if a.alias:
        return _run_alias(table, registry, a.alias, a.apply)
    if a.clear:
        names = sorted(k for k, m in registry.items() if core.flag_of(m))
        aliased = [k for k in names if isinstance(registry[k], dict) and registry[k].get(core.ALIAS_FLAG)]
        print(f"clear: {len(names)} of {len(registry)} registry entries carry a core flag ({len(aliased)} with a {core.ALIAS_FLAG})")
        if aliased and not a.include_aliased:
            print("refused: clearing an aliased entry loses the only copy of its stored id; pass --include-aliased to clear it")
            return 1
        if not a.apply:
            print("dry-run: nothing written (pass --apply)")
            return 0
        for n in names:
            table.update_item(
                Key=KEY,
                UpdateExpression="REMOVE habit_registry.#n.#c, habit_registry.#n.#a",
                ExpressionAttributeNames={"#n": n, "#c": core.FLAG, "#a": core.ALIAS_FLAG},
            )
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
    stored_alias = {v: k for k, v in core.alias_map(registry).items()}  # #6090: a new member of an aliased id carries both
    for k, cid in writes:
        names, values, expr = {"#n": k, "#c": core.FLAG}, {":c": cid}, "SET habit_registry.#n.#c = :c"
        if cid in stored_alias:
            names["#a"], values[":a"], expr = core.ALIAS_FLAG, stored_alias[cid], expr + ", habit_registry.#n.#a = :a"
        table.update_item(Key=KEY, UpdateExpression=expr, ExpressionAttributeNames=names, ExpressionAttributeValues=values)
    print(f"applied {len(writes)} flag(s); now run scripts/check_habit_registry_drift.py --live")
    return 0


def _run_alias(table, registry: dict, alias: str, apply: bool) -> int:
    """#6090 `--alias`: dry-run by default; `--apply` writes `core_alias` (conditional on the entry still carrying the
    stored flag), then re-reads the row and prints the read-back. Counts only."""
    core = _core_habits()
    writes, already, errors = alias_plan(registry, alias)
    for e in errors:
        print("ERROR " + e)
    print(f"alias {alias}: {len(writes)} entr(y/ies) to map, {already} already mapped")
    if errors:
        print("refused: fix the errors above; nothing written")
        return 1
    if not apply:
        after = {k: dict(m) for k, m in registry.items() if isinstance(m, dict)}
        for k in writes:
            after[k][core.ALIAS_FLAG] = alias
        print("after (preview): " + alias_readback(after, alias)[1])
        print("dry-run: nothing written (pass --apply)")
        return 0
    for k in writes:
        table.update_item(
            Key=KEY,
            UpdateExpression="SET habit_registry.#n.#a = :a",
            ConditionExpression="habit_registry.#n.#c = :s",
            ExpressionAttributeNames={"#n": k, "#a": core.ALIAS_FLAG, "#c": core.FLAG},
            ExpressionAttributeValues={":a": alias, ":s": core.flag_of(registry[k])},
        )
    fresh = table.get_item(Key=KEY, ConsistentRead=True).get("Item", {}).get("habit_registry") or {}
    ok, line = alias_readback(fresh, alias)
    print(f"applied {len(writes)} mapping(s); read-back: {line}")
    print("READ-BACK: " + ("OK" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
