#!/usr/bin/env python3
# ──────────────────────────────────────────────────────────────────────────
# ARCHIVED 2026-07-11 (#972) — one-time script, retired from the live deploy/ surface.
# DONE-ONCE: executed for #726 (epic #715) — the legacy SOURCE#coach_thread# embedded
# prediction arrays were tombstoned to `predictions_voided_726`. The canonical
# PREDICTION# store is live; re-running would be a no-op dry-run scan.
# ──────────────────────────────────────────────────────────────────────────
"""void_legacy_predictions_726.py — tombstone the legacy prediction corruption (#726, epic #715).

Two prediction stores existed. The canonical one — `COACH#{coach}_coach` /
`PREDICTION#` — is evaluator-graded, code-stamped (#725), and serves the public
site. The legacy one — `predictions` arrays embedded in `USER#matthew` /
`SOURCE#coach_thread#...` records — held pre-#725 LLM-authored metadata:
hallucinated IDs (`pred_2024...`, `pred_20250000_*`), past-or-null target
dates, daily re-emission duplicates. 88 pending, 0 ever gradeable.

This script VOIDS (never deletes — ADR-077) the corrupt population:

  - A prediction is CORRUPT iff it lacks `semantic_key` — the stamp only
    #725's code path mints, so its absence exactly identifies pre-fix records.
  - Per thread record: corrupt entries move `predictions` →
    `predictions_voided_726`; clean (#725-stamped) entries stay in place.
  - The record is stamped `predictions_voided_at` / `predictions_voided_by` /
    `voided_cycle` (SSM /life-platform/experiment-cycle, ADR-077 convention).

Idempotent: a re-run finds no unstamped predictions and changes nothing.
Read-only by default; `--apply` commits.

Usage:
    python3 deploy/void_legacy_predictions_726.py            # dry-run preview
    python3 deploy/void_legacy_predictions_726.py --apply    # commit
"""
import argparse
import os
from collections import defaultdict
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

TABLE_NAME = "life-platform"
USER_ID = os.environ.get("LIFE_PLATFORM_USER", "matthew")
LEGACY_PK = f"USER#{USER_ID}"
LEGACY_SK_PREFIX = "SOURCE#coach_thread#"
REGION = "us-west-2"
SSM_CYCLE_PARAM = "/life-platform/experiment-cycle"
DEFAULT_CYCLE = 4  # current cycle at authoring time; SSM is authoritative


def current_cycle() -> int:
    """Read the cycle number from SSM (ADR-077)."""
    try:
        ssm = boto3.client("ssm", region_name=REGION)
        return int(ssm.get_parameter(Name=SSM_CYCLE_PARAM)["Parameter"]["Value"])
    except Exception:
        return DEFAULT_CYCLE


def split_predictions(preds):
    """(clean, corrupt): #725-stamped entries carry semantic_key; corrupt ones don't."""
    clean, corrupt = [], []
    for p in preds or []:
        if isinstance(p, dict) and p.get("semantic_key"):
            clean.append(p)
        else:
            corrupt.append(p)
    return clean, corrupt


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="commit the void (default: dry-run)")
    args = ap.parse_args()

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    cycle = current_cycle()
    now_iso = datetime.now(timezone.utc).isoformat()

    scanned = touched = voided_total = kept_total = already = 0
    by_status = defaultdict(int)
    samples = []

    kwargs = {"KeyConditionExpression": Key("pk").eq(LEGACY_PK) & Key("sk").begins_with(LEGACY_SK_PREFIX)}
    while True:
        resp = table.query(**kwargs)
        for item in resp.get("Items", []):
            scanned += 1
            clean, corrupt = split_predictions(item.get("predictions"))
            if not corrupt:
                if item.get("predictions_voided_726") is not None:
                    already += 1
                continue
            touched += 1
            voided_total += len(corrupt)
            kept_total += len(clean)
            for p in corrupt:
                if isinstance(p, dict):
                    by_status[str(p.get("status", "?"))] += 1
                    if len(samples) < 12:
                        samples.append(f"{item['sk'][:60]}  ->  {p.get('prediction_id', '<no id>')}  target={p.get('target_date')}")
            if args.apply:
                # Append-safe: a record voided in a prior partial run keeps that
                # tombstone content (list_append onto existing or fresh list).
                table.update_item(
                    Key={"pk": item["pk"], "sk": item["sk"]},
                    UpdateExpression=(
                        "SET predictions = :clean, "
                        "predictions_voided_726 = list_append(if_not_exists(predictions_voided_726, :empty), :void), "
                        "predictions_voided_at = :at, predictions_voided_by = :by, voided_cycle = :cyc"
                    ),
                    ExpressionAttributeValues={
                        ":clean": clean,
                        ":void": corrupt,
                        ":empty": [],
                        ":at": now_iso,
                        ":by": "issue-726",
                        ":cyc": cycle,
                    },
                )
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek

    mode = "APPLIED" if args.apply else "DRY-RUN (nothing written; --apply to commit)"
    print(f"\n{mode}")
    print(f"  thread records scanned:            {scanned}")
    print(f"  records with corrupt predictions:  {touched}")
    print(f"  predictions voided:                {voided_total}  (by status: {dict(by_status)})")
    print(f"  clean (#725-stamped) kept:         {kept_total}")
    print(f"  previously-voided records seen:    {already}")
    print(f"  cycle stamp:                       {cycle}")
    if samples:
        print("\n  sample voided (sk -> prediction_id):")
        for s in samples:
            print(f"    {s}")


if __name__ == "__main__":
    main()
