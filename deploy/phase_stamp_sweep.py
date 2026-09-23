#!/usr/bin/env python3
"""phase_stamp_sweep.py — the standing corrector for #4040: a no-reset world stamps no
pre-genesis EXPERIMENT_SCOPED row.

THE DEFECT
  `deploy/restart_phase_tag.py` (the tagger) was the only thing that stamped `phase=pilot`
  onto an `EXPERIMENT_SCOPED` row dated before genesis, and it ran only as part of a reset.
  Under the owner's 2026-09-21 no-further-resets ruling (ADR-077 amendment, PR #4037) the
  tagger never runs again. A row written after its last run and dated before genesis keeps
  whatever `phase` it was born with — often none, sometimes the CURRENT-phase constant —
  forever. Measured 2026-09-22 (`deploy/restart_verify.py`'s #3513 check): 16 such rows over
  45,896 scanned.

  The nightly `data:coach_ensemble_phase_stamp_coverage` leg (`lambdas/operational/
  qa_smoke_lambda.py`, via `experiment.pk_census.scoped_stamp_audit`'s `mis_stamped` leaf)
  is the DETECTOR — it WARNs, by name and with rows, every night this recurs. This script is
  the CORRECTOR: read-only unless `--apply`, and idempotent (a clean re-run finds nothing).

WHY A NEW SCRIPT AND NOT restart_phase_tag.py
  `restart_phase_tag.py` does a full-table Scan filtered to `USER#matthew#SOURCE#*` — the
  RCU of the whole live table (45,896+ items and growing), appropriate for a one-time reset
  pass and wasteful for a leg meant to run routinely. This script Queries each
  `EXPERIMENT_SCOPED` source's own pk PARTITION individually — bounded, key-range reads per
  family (the #4040 acceptance criterion) — instead of a full-table scan. It shares
  `restart_phase_tag.extract_date`/`desired_phase` (the tagger's own date rule) and
  `phase_taxonomy.pre_genesis_scoped_violation` (the shared predicate `restart_verify.py`
  check 21 and the nightly leg also use) so all three instruments agree by construction.

  One-off `restart_phase_tag.py --apply` remains an acceptable FIRST run over the historical
  backlog (#4040 acceptance box 2) — this script is the standing mechanism from here.

THE SERVED-LEAD-IN EXEMPTION (load-bearing — read before running --apply)
  A chronicle row is not "pre-genesis and stale" merely because its `sk` predates genesis —
  a reset re-dates a carried-forward lead-in by writing a new `date` ATTRIBUTE and leaving
  the `sk` alone (#3650). Incident, 2026-09-22: `deploy/reconcile_countdown_gap.py --apply`
  tombstoned the served `DATE#2026-09-05` chronicle lead-in on `sk` age alone; the live
  manifest kept serving the now-archived row and `chronicle:manifest_provenance` +
  `recall:corpus_freshness` both went red 14h later. This script excludes every `(pk, sk)`
  `chronicle_manifest_qa.served_chronicle_keys` resolves to a live post BEFORE it ever
  considers correcting a row — never guessed at, never overridden by a flag.

WHAT IT DOES NOT TOUCH
  The COACH#/ENSEMBLE#/insights tagger-blind set stays `deploy/backfill_coach_ensemble_
  phase_stamps.py`'s job (it repairs UNSTAMPED rows there under a safe `attribute_not_exists`
  condition). This script covers every OTHER `EXPERIMENT_SCOPED` SOURCE# family, and unlike
  the backfill it also corrects a row that already carries the WRONG phase — the #4040 shape
  the tagger used to fix and the backfill's `attribute_not_exists` guard cannot reach, by
  design (a wrong stamp there is a distinct, more damaging defect on the tagger-blind set,
  #3514 DA-6 — untouched here). It never touches `phase` on a CROSS_PHASE/SYSTEM_STATE
  family or any row dated on/after genesis (that is `EXPERIMENT_PHASE_CURRENT`'s job, at
  write time, per `experiment_stamp_for`).

Usage:
    python3 deploy/phase_stamp_sweep.py            # dry-run (default)
    python3 deploy/phase_stamp_sweep.py --apply    # write DynamoDB
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Key

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "lambdas"))
sys.path.insert(0, str(REPO_ROOT / "deploy"))

from experiment.phase_taxonomy import SCOPED_SOURCES, pre_genesis_scoped_violation  # noqa: E402
from operational.chronicle_manifest_qa import served_chronicle_keys  # noqa: E402
from restart_phase_tag import extract_date  # noqa: E402  — the tagger's own date reader, one derivation

from lambdas.common.constants import EXPERIMENT_PHASE_PRIOR, EXPERIMENT_START_DATE  # noqa: E402

REGION = "us-west-2"
TABLE_NAME = "life-platform"
S3_BUCKET = "matthew-life-platform"
USER_ID = "matthew"


def query_partition(table, pk: str) -> list[dict]:
    """Every item under one SOURCE# partition — a bounded, key-range Query, never a Scan.
    This is the #4040 acceptance criterion: per-family reads, not a full-table sweep."""
    items: list[dict] = []
    lek = None
    while True:
        kw = {"KeyConditionExpression": Key("pk").eq(pk)}
        if lek:
            kw["ExclusiveStartKey"] = lek
        resp = table.query(**kw)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            return items


def find_violations(items: list[dict], pk: str, genesis: str, exempt_keys: set) -> list[dict]:
    """Every item in `items` that `pre_genesis_scoped_violation` flags and `exempt_keys`
    does not excuse. Pure over the item list — the caller does the DDB I/O."""
    out = []
    for it in items:
        sk = str(it.get("sk", ""))
        if (pk, sk) in exempt_keys:
            continue
        d = extract_date(it)
        if pre_genesis_scoped_violation(pk, sk, it.get("phase"), d, genesis):
            out.append(it)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write DynamoDB (default: dry-run)")
    args = ap.parse_args()

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    genesis = EXPERIMENT_START_DATE
    print(f"phase_stamp_sweep (#4040) — mode: {'APPLY' if args.apply else 'DRY RUN'} — genesis: {genesis}")

    try:
        s3 = boto3.client("s3", region_name=REGION)
        exempt_keys = served_chronicle_keys(table, s3, S3_BUCKET)
    except Exception as e:  # noqa: BLE001 — an unreadable manifest exempts nothing; stays conservative
        print(f"  (served_chronicle_keys unavailable, exempting nothing: {e})")
        exempt_keys = set()
    if exempt_keys:
        print(f"  {len(exempt_keys)} served chronicle row(s) exempted: {sorted(exempt_keys)}")

    total_found = 0
    total_fixed = 0
    for source in SCOPED_SOURCES:
        pk = f"USER#{USER_ID}#SOURCE#{source}"
        items = query_partition(table, pk)
        if not items:
            continue
        violations = find_violations(items, pk, genesis, exempt_keys)
        if not violations:
            continue
        total_found += len(violations)
        print(f"\n{pk}: {len(items)} row(s) scanned — {len(violations)} pre-genesis violation(s)")
        for it in violations:
            sk = str(it.get("sk", ""))
            before = it.get("phase")
            suffix = "" if args.apply else "  (dry-run)"
            print(f"    {sk}  phase={before!r} -> {EXPERIMENT_PHASE_PRIOR!r}{suffix}")
            if args.apply:
                try:
                    table.update_item(
                        Key={"pk": pk, "sk": sk},
                        UpdateExpression="SET #p = :p",
                        ExpressionAttributeNames={"#p": "phase"},
                        ExpressionAttributeValues={":p": EXPERIMENT_PHASE_PRIOR},
                    )
                    total_fixed += 1
                except Exception as e:  # noqa: BLE001 — one row's write error must not stop the sweep
                    print(f"      SKIP (write error: {e})")

    if total_found == 0:
        print("\nnothing to repair — every EXPERIMENT_SCOPED row dated before genesis carries phase=pilot.")
        return 0

    verb = "found" if not args.apply else f"corrected ({total_fixed} written)"
    print(f"\ndone. {total_found} pre-genesis provenance violation(s) {verb}." + ("" if args.apply else "  Re-run with --apply to write."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
