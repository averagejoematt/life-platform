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

from experiment.pk_census import census_snapshot, scoped_partitions_from_snapshot  # noqa: E402

ARTIFACT = REPO_ROOT / "deploy" / "generated" / "pk_family_census.json"


def write_artifact(snap: dict) -> Path:
    """Write the census snapshot to the ONE artifact path and return it.

    THE ONLY place a `deploy/generated/` path for this artifact is constructed. The reset's
    Step [0] calls this rather than building the path itself, deliberately: `restart_verify_
    gates.reset_artifact_writers()` derives the pre-merge test lane from which `deploy/*.py`
    files construct such a path, so a second constructor would (correctly) enrol every test
    that merely MENTIONS that file — for restart_pipeline.py that is six more files including
    the AWS-integration suite, which cannot run pre-merge. One writer keeps the derivation
    honest and the lane small, which is the same single-home argument #3860 settled.
    """
    ARTIFACT.write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ARTIFACT


def read_artifact_families() -> dict:
    """The committed census's families, or {} when the artifact is absent."""
    if not ARTIFACT.exists():
        return {}
    return (json.loads(ARTIFACT.read_text(encoding="utf-8")) or {}).get("families", {})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print what would change, write nothing")
    args = ap.parse_args()

    snap = census_snapshot()
    old = read_artifact_families()
    added = sorted(set(snap["families"]) - set(old))
    removed = sorted(set(old) - set(snap["families"]))
    print(f"families: {snap['family_count']}  (+{len(added)} / -{len(removed)})")
    if added:
        print("  added:   " + ", ".join(added))
    if removed:
        print("  removed: " + ", ".join(removed))
    # #3599: the coverage-granularity half of the same scan, read back through the ONE
    # reader `deploy/restart_intelligence_wipe.assert_registry_coverage`'s CI twin uses —
    # so an artifact whose coverage block is unreadable says so HERE, at write time, and
    # not on the PR of whoever next grades the wipe against it.
    scoped = scoped_partitions_from_snapshot(snap)
    print(f"coverage partitions: {len(scoped)} EXPERIMENT_SCOPED full pk(s) — {', '.join(sorted(scoped))}")
    unresolved = sorted(f for f, v in snap["families"].items() if v.get("class") is None)
    if unresolved:
        print(f"  UNRESOLVED (phase_taxonomy cannot classify): {', '.join(unresolved)}")
    if args.dry_run:
        print("(dry-run) — nothing written.")
        return 0
    write_artifact(snap)
    print(f"wrote {ARTIFACT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
