#!/usr/bin/env python3
"""write_pk_family_census.py — refresh deploy/generated/pk_family_census.json (#3514).

The live pk-family census as a COMMITTED artifact, so CI can grade docs/SCHEMA.md against
a measured family list rather than a hand-typed one. Needs AWS credentials; the reset's
Step [0] refreshes it as a side effect of the preflight it already runs, and this script
is the attended way to refresh it between resets.

READ-ONLY against DynamoDB. Writes exactly one file.

    python3 deploy/write_pk_family_census.py            # write the artifact
    python3 deploy/write_pk_family_census.py --dry-run  # print the diff summary only
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

from experiment.pk_census import census_snapshot  # noqa: E402

ARTIFACT = REPO_ROOT / "deploy" / "generated" / "pk_family_census.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print what would change, write nothing")
    args = ap.parse_args()

    snap = census_snapshot()
    old = {}
    if ARTIFACT.exists():
        old = (json.loads(ARTIFACT.read_text(encoding="utf-8")) or {}).get("families", {})
    added = sorted(set(snap["families"]) - set(old))
    removed = sorted(set(old) - set(snap["families"]))
    print(f"families: {snap['family_count']}  (+{len(added)} / -{len(removed)})")
    if added:
        print("  added:   " + ", ".join(added))
    if removed:
        print("  removed: " + ", ".join(removed))
    unresolved = sorted(f for f, v in snap["families"].items() if v.get("class") is None)
    if unresolved:
        print(f"  UNRESOLVED (phase_taxonomy cannot classify): {', '.join(unresolved)}")
    if args.dry_run:
        print("(dry-run) — nothing written.")
        return 0
    ARTIFACT.write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {ARTIFACT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
