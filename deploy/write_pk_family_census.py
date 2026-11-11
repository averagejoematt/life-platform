#!/usr/bin/env python3
"""write_pk_family_census.py — refresh deploy/generated/pk_family_census.json (#3514).

The live pk-family census as a COMMITTED artifact, so CI can grade docs/SCHEMA.md against
a measured family list rather than a hand-typed one. Needs AWS credentials; the reset's
Step [0] refreshes it as a side effect of the preflight it already runs, and this script
is the attended way to refresh it between resets.

READ-ONLY against DynamoDB. Writes exactly one file.

    python3 deploy/write_pk_family_census.py            # write the artifact
    python3 deploy/write_pk_family_census.py --dry-run  # print the diff summary only
    python3 deploy/write_pk_family_census.py --refresh-if-older-than-days 28   # the wrap's cadence

THE CADENCE (#5524). The artifact used to be refreshed "at reset", and no reset will come.
`--refresh-if-older-than-days N` is the wrap's gather gate (`scripts/wrap_gates.py`
`pk-census`): it costs nothing while the artifact is younger than N days (no scan at all), and
past N it re-scans, writes, then runs the pytest files that READ this artifact (every
`tests/test_*.py` naming its filename, `census_reader_tests()`). If any of
them reds on the fresh census, the previous bytes are restored and the run exits 1 naming the
delta — the wrap commits straight to main, so a refresh that would red main is never kept; the
new family is the finding, and `tests/test_schema_families_census.py` reds at 35 days until a PR
documents it. No AWS credentials prints UNVERIFIED and exits 0 (the wrap's degrade line).
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
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


def artifact_age_days(today=None) -> int | None:
    """Whole days since the committed artifact's `generated_at` (UTC), or None when absent/unreadable."""
    if not ARTIFACT.exists():
        return None
    try:
        stamp = json.loads(ARTIFACT.read_text(encoding="utf-8"))["generated_at"]
        taken = datetime.fromisoformat(stamp).astimezone(timezone.utc).date()
    except (ValueError, KeyError, TypeError):
        return None
    return ((today or datetime.now(timezone.utc).date()) - taken).days


def census_reader_tests() -> list:
    """The pytest files that read THIS artifact — every tests/test_*.py naming its filename.

    Derived, never hand-listed; a name match (not the `deploy/generated/` path needle the reset's
    #3477 leg uses) so a reader that builds the path from parts is still enrolled. Raises on an
    empty result: a refresh graded by zero readers is a check that cannot fail."""
    out = sorted(
        f"tests/{p.name}"
        for p in (REPO_ROOT / "tests").glob("test_*.py")
        if ARTIFACT.name in p.read_text(encoding="utf-8", errors="replace")
    )
    if not out:
        raise RuntimeError(f"no test reads {ARTIFACT.name} — the reader derivation went blind")
    return out


def refresh_if_stale(max_age_days: int, scan=census_snapshot, run=subprocess.run) -> int:
    """The wrap gate (#5524): no-op while fresh; past `max_age_days` re-scan, write, and keep
    the write only if every reader of the artifact still passes against it."""
    age = artifact_age_days()
    if age is not None and age < max_age_days:
        print(f"pk-family census: fresh ({age}d old < {max_age_days}d) — no scan")
        return 0
    try:
        snap = scan()
    except Exception as exc:  # noqa: BLE001 — any botocore failure (no creds, expired SSO, throttle) is a degrade
        if type(exc).__module__.startswith("botocore"):
            print(f"pk-family census: UNVERIFIED — could not scan ({type(exc).__name__}: {exc}); artifact is {age}d old")
            return 0
        raise
    previous = ARTIFACT.read_bytes() if ARTIFACT.exists() else None
    old = read_artifact_families()
    write_artifact(snap)
    readers = census_reader_tests()
    proc = run(
        [sys.executable, "-m", "pytest", *readers, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    added = sorted(set(snap["families"]) - set(old))
    if proc.returncode != 0:
        if previous is not None:
            ARTIFACT.write_bytes(previous)
        tail = "\n".join((proc.stdout or "").splitlines()[-15:])
        print(
            f"pk-family census: refresh NOT kept — {len(readers)} reader test file(s) red on the fresh scan "
            f"(new families: {', '.join(added) or 'none'}). Fix in a PR (document/classify the family), then refresh.\n{tail}"
        )
        return 1
    print(
        f"pk-family census: refreshed ({snap['family_count']} families, +{len(added)}: {', '.join(added) or '-'}); {len(readers)} reader file(s) green — commit {ARTIFACT.name}"
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print what would change, write nothing")
    ap.add_argument(
        "--refresh-if-older-than-days", type=int, metavar="N", help="the wrap's cadence: scan only past N days, keep only if readers pass"
    )
    args = ap.parse_args()

    if args.refresh_if_older_than_days is not None:
        return refresh_if_stale(args.refresh_if_older_than_days)

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
