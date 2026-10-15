#!/usr/bin/env python3
"""
check_habit_registry_drift.py — #4632: does every name-keyed habit structure still
point at a habit that exists in Habitify?

Three structures are keyed on a habit's DISPLAY NAME, so a rename in the app silently
orphans them: the profile's `habit_registry` (its keys plus each entry's
`habitify_names` aliases, #4362), and the supplements bridge's `SUPPLEMENT_MAP`
(`lambdas/ingestion/habitify_lambda.py`). This check reports, as COUNTS ONLY (habit
names are owner data and never leave this script):

  live_without_registry   a live habit no registry entry answers to
  registry_without_live   a registry entry none of whose names is a live habit
  bridge_without_live     a SUPPLEMENT_MAP key that is not a live habit, directly or
                          through a registry alias (the bridge resolves both ways)

Exit 1 when any of the three is non-zero, 0 otherwise.

Modes:
  --fixture PATH   offline, fixture-driven: a JSON file with `journal` (the vendor's
                   `/journal` list, or `live_names`), `habit_registry`, and optionally
                   `bridge_keys` (default: the code's SUPPLEMENT_MAP). Needs no creds.
  --live           READ-ONLY: Secrets Manager GetSecretValue (life-platform/habitify),
                   Habitify `GET /journal` for today (Pacific), and one DynamoDB
                   GetItem of the canonical profile row. Writes nothing anywhere.

Usage:
    python3 scripts/check_habit_registry_drift.py --fixture path/to/fixture.json
    python3 scripts/check_habit_registry_drift.py --live [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRIFT_KEYS = ("live_without_registry", "registry_without_live", "bridge_without_live")


def live_names(journal) -> set[str]:
    """The live habit names: every non-archived journal entry's name."""
    return {e["name"] for e in journal or [] if isinstance(e, dict) and isinstance(e.get("name"), str) and not e.get("is_archived")}


def registry_name_sets(registry) -> list[set[str]]:
    """Each registry entry as the set of names it answers to (its key + `habitify_names`)."""
    out = []
    for key, meta in (registry or {}).items():
        names = {key}
        aliases = meta.get("habitify_names") if isinstance(meta, dict) else None
        if isinstance(aliases, (list, tuple, set)):
            names.update(a for a in aliases if isinstance(a, str) and a)
        out.append(names)
    return out


def drift_counts(live: set[str], registry, bridge_keys) -> dict:
    """The COUNTS the check reports — never a name."""
    entries = registry_name_sets(registry)
    known = set().union(*entries) if entries else set()

    def _bridge_live(key: str) -> bool:
        return key in live or any(key in names and names & live for names in entries)

    return {
        "live_habits": len(live),
        "registry_entries": len(entries),
        "bridge_keys": len(list(bridge_keys)),
        "live_without_registry": sum(1 for n in live if n not in known),
        "registry_without_live": sum(1 for names in entries if not names & live),
        "bridge_without_live": sum(1 for k in bridge_keys if not _bridge_live(k)),
    }


def _lambda_imports():
    for k, v in (("TABLE_NAME", "life-platform"), ("S3_BUCKET", "matthew-life-platform"), ("USER_ID", "matthew")):
        os.environ.setdefault(k, v)
    os.environ.setdefault("AWS_REGION", "us-west-2")
    for p in (ROOT / "lambdas", ROOT / "lambdas" / "ingestion"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import habitify_lambda  # noqa: E402  (lazy: --fixture mode needs no AWS at all)

    return habitify_lambda


def load_fixture(path: str) -> tuple[set[str], dict, list]:
    data = json.loads(Path(path).read_text())
    live = set(data["live_names"]) if "live_names" in data else live_names(data.get("journal"))
    bridge = data.get("bridge_keys")
    if bridge is None:
        bridge = list(_lambda_imports().SUPPLEMENT_MAP)
    return live, data.get("habit_registry") or {}, list(bridge)


def load_live() -> tuple[set[str], dict, list]:  # pragma: no cover — read-only AWS + vendor GET
    import boto3

    hab = _lambda_imports()
    secret = boto3.client("secretsmanager", region_name="us-west-2").get_secret_value(SecretId=hab.SECRET_NAME)
    api_key = hab.authenticate(json.loads(secret["SecretString"]))["api_key"]
    journal = hab.fetch_journal(api_key, hab.pacific_today())
    table = boto3.resource("dynamodb", region_name="us-west-2").Table(os.environ["TABLE_NAME"])
    profile = (table.get_item(Key={"pk": f"USER#{hab.USER_ID}", "sk": "PROFILE#v1"}) or {}).get("Item") or {}
    return live_names(journal), profile.get("habit_registry") or {}, list(hab.SUPPLEMENT_MAP)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fixture", help="offline JSON fixture (no creds needed)")
    mode.add_argument("--live", action="store_true", help="read-only live check")
    ap.add_argument("--json", action="store_true", help="print the counts as JSON")
    args = ap.parse_args(argv)
    live, registry, bridge = load_fixture(args.fixture) if args.fixture else load_live()
    counts = drift_counts(live, registry, bridge)
    if args.json:
        print(json.dumps(counts, sort_keys=True))
    else:
        for k, v in counts.items():
            print(f"{k}: {v}")
    drifted = any(counts[k] for k in DRIFT_KEYS)
    print("HABIT-REGISTRY-DRIFT: " + ("FAIL" if drifted else "OK"))
    return 1 if drifted else 0


if __name__ == "__main__":
    sys.exit(main())
