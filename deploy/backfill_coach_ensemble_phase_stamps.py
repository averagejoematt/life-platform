#!/usr/bin/env python3
"""backfill_coach_ensemble_phase_stamps.py — one-shot data repair for #1970.

Before this issue's fix, `deploy/seed_genesis_preregistration.py::write_predictions`
wrote PREDICTION# rows to the tagger-blind COACH#* partition with no phase/cycle
stamp — `lambdas/experiment/phase_filter.py`'s PHASE_FILTER_EXPRESSION admits
`attribute_not_exists(phase)` forever, and `restart_phase_tag.py` (the reset-time
tagger) only reaches `USER#matthew#SOURCE#*` pks, never `COACH#*`/`ENSEMBLE#*` —
so an unstamped row on these EXPERIMENT_SCOPED-but-tagger-blind partitions
(`lambdas/experiment/phase_taxonomy.py`) survives every read filter and leaks
into the next reset cycle as if it were freshly current, until the wipe's
backstop pass finally reaches it.

The seeder now applies `experiment_stamp()` (phase_taxonomy.py, #1233 — the same
write-time provenance stamp `coach_state_updater._put_item` and
`dispute_docket._stamped` already use) to every row it writes going forward. This
script repairs what was ALREADY WRITTEN before that fix landed: it walks the same
tagger-blind pk set that `lambdas/operational/qa_smoke_lambda.py`'s
`check_coach_ensemble_phase_stamp_coverage()` nightly-audits (#1970 AC3) — every
COACH#<coach_id> partition, COACH#computation, and the ENSEMBLE#{digest,
disagreements, dispute, docket} singletons (ENSEMBLE#influence_graph is excluded
deliberately — SYSTEM_STATE static config, never phase-stamped by design) — and
applies the same `experiment_stamp()` to any row still missing a `phase`
attribute. This is deliberately broader than "just the two PREDICTION# rows named
in the issue": any other stray unstamped row on the same tagger-blind partitions
(from before the #1233 write-time-stamping precedent existed at all) gets the
same repair, so the qa-smoke guard can actually reach zero.

SAFE / IDEMPOTENT: read-only (Query, no Scan) unless --apply. Each write is a
single-item UpdateExpression guarded by `ConditionExpression=attribute_not_exists(
phase)` — it can ONLY set phase+cycle where phase is currently absent, so a
re-run (or a race against a concurrent stamped write) can never clobber a row
that already carries its own provenance. Numeric `cycle` is cast to Decimal
before the write, matching the repo's DynamoDB convention.

Usage:
    python3 deploy/backfill_coach_ensemble_phase_stamps.py            # dry-run (default)
    python3 deploy/backfill_coach_ensemble_phase_stamps.py --apply    # write DynamoDB
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Key

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

from coach.persona_registry import OPERATIONAL_COACH_IDS  # noqa: E402
from experiment.phase_taxonomy import experiment_stamp  # noqa: E402

REGION = "us-west-2"
TABLE_NAME = "life-platform"

# ENSEMBLE#influence_graph is deliberately excluded: SYSTEM_STATE static config
# (phase_taxonomy._PK_RULES), not an EXPERIMENT_SCOPED write, never phase-stamped.
_ENSEMBLE_PKS = ["ENSEMBLE#digest", "ENSEMBLE#disagreements", "ENSEMBLE#dispute", "ENSEMBLE#docket"]


def target_pks() -> list[str]:
    """The exact tagger-blind pk set qa_smoke_lambda's coverage check audits."""
    return [f"COACH#{cid}" for cid in OPERATIONAL_COACH_IDS] + ["COACH#computation"] + _ENSEMBLE_PKS


def query_unstamped(table, pk: str) -> list[dict]:
    """Every item under `pk` with no `phase` attribute. Paginated Query, no Scan."""
    items: list[dict] = []
    lek = None
    while True:
        kw = {
            "KeyConditionExpression": Key("pk").eq(pk),
            "FilterExpression": "attribute_not_exists(#phase)",
            "ExpressionAttributeNames": {"#phase": "phase"},
        }
        if lek:
            kw["ExclusiveStartKey"] = lek
        resp = table.query(**kw)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
    return items


def _update_kwargs(pk: str, sk: str, stamp: dict) -> dict:
    """Build the guarded UpdateItem call for one row. Condition-guarded so this
    can only ever set phase (+cycle) onto a row that is currently unstamped."""
    names = {"#phase": "phase"}
    values = {":phase": stamp["phase"]}
    set_parts = ["#phase = :phase"]
    if "cycle" in stamp:
        names["#cycle"] = "cycle"
        values[":cycle"] = Decimal(str(int(stamp["cycle"])))  # Decimal before any DDB write
        set_parts.append("#cycle = :cycle")
    return {
        "Key": {"pk": pk, "sk": sk},
        "UpdateExpression": "SET " + ", ".join(set_parts),
        "ConditionExpression": "attribute_not_exists(#phase)",
        "ExpressionAttributeNames": names,
        "ExpressionAttributeValues": values,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill write-time phase stamps onto unstamped COACH#/ENSEMBLE# rows (#1970)")
    ap.add_argument("--apply", action="store_true", help="write DynamoDB (default: dry-run)")
    args = ap.parse_args()

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    stamp = experiment_stamp()
    if not stamp.get("phase"):
        print("experiment_stamp() returned no phase (constants import failed?) — refusing to run.")
        return 1
    print(f"backfill_coach_ensemble_phase_stamps (#1970) — mode: {'APPLY' if args.apply else 'DRY RUN'} — stamp: {stamp}")

    total_found = 0
    total_fixed = 0
    for pk in target_pks():
        items = query_unstamped(table, pk)
        if not items:
            continue
        total_found += len(items)
        print(f"\n{pk}: {len(items)} unstamped row(s)")
        for it in items:
            sk = it["sk"]
            suffix = "" if args.apply else "  (dry-run)"
            print(f"    {sk} -> phase={stamp.get('phase')} cycle={stamp.get('cycle')}{suffix}")
            if args.apply:
                try:
                    table.update_item(**_update_kwargs(pk, sk, stamp))
                    total_fixed += 1
                except Exception as e:  # noqa: BLE001 — a lost condition race is not fatal to the run
                    print(f"      SKIP (already stamped by a concurrent writer, or error: {e})")

    if total_found == 0:
        print("\nnothing to do — every row on the audited COACH#/ENSEMBLE# partitions already carries a phase stamp.")
        return 0

    verb = "found" if not args.apply else f"backfilled ({total_fixed} written)"
    print(f"\ndone. {total_found} unstamped row(s) {verb}." + ("" if args.apply else "  Re-run with --apply to write."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
