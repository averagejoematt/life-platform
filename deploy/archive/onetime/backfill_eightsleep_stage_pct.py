#!/usr/bin/env python3
"""
backfill_eightsleep_stage_pct.py — retire impossible stage percentages (2026-08-21).

WHY. `/api/sleep_detail` served this row to the public site:

    2026-08-20   deep 11.1 + rem 31.1 + light 106.7  =  148.9%

`light_pct` over 100 is not a rounding artifact. The stored Eight Sleep row:

    deep_hours 0.15 + rem_hours 0.42 + light_hours 1.44 = 2.01h
    sleep_duration_hours (TST)                          = 1.35h
    awake_hours                                         = 0.61h

The vendor's stage hours carried the awake time; TST excluded it.
`compute_derived_fields` divided by TST anyway, because it asserted the
reconciliation rather than checking it. All three percentages are therefore wrong
on such a night — `deep_pct` 11.1 was equally bogus (7.5% of the real stage total);
it merely landed inside a plausible range and so read as fine.

The ingestion fix (`eightsleep_lambda.compute_derived_fields`) omits the three as a
SET and records `stage_pct_omitted_reason` when the stages and TST disagree by more
than rounding. That stops NEW bad rows. This script corrects the archive.

WHY OMIT RATHER THAN RECOMPUTE AGAINST THE STAGE SUM. Percent-of-TST is what these
fields MEAN (see the field block in eightsleep_lambda.py, and every consumer that
reads them). Re-basing them onto a different denominator would silently change the
semantics of a stored field across the whole archive. ADR-104's answer for "cannot
compute this honestly" is absence, and absence with a stated reason is better than a
plausible-looking number nobody can reconcile.

Read-only by default. Apply with --apply.

  python3 deploy/backfill_eightsleep_stage_pct.py            # dry-run report
  python3 deploy/backfill_eightsleep_stage_pct.py --apply    # write corrections
"""

import argparse
import os
import sys

import boto3
from boto3.dynamodb.conditions import Key

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
PK = "USER#matthew#SOURCE#eightsleep"
PCT_FIELDS = ("rem_pct", "deep_pct", "light_pct")
STAGE_HOURS = ("rem_hours", "deep_hours", "light_hours")


def _f(v):
    return None if v is None else float(v)


def stage_ratio(row):
    """(stage_sum, TST) for a row, or (None, None) when it has no stage breakdown."""
    tst = _f(row.get("sleep_duration_hours"))
    present = [_f(row.get(k)) for k in STAGE_HOURS if row.get(k) is not None]
    if not tst or tst <= 0 or not present:
        return None, None
    return sum(present), tst


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write corrections (default: dry-run)")
    args = ap.parse_args()

    table = boto3.resource("dynamodb", region_name="us-west-2").Table(TABLE_NAME)

    rows, key = [], None
    while True:
        kw = {"KeyConditionExpression": Key("pk").eq(PK) & Key("sk").begins_with("DATE#")}
        if key:
            kw["ExclusiveStartKey"] = key
        resp = table.query(**kw)
        rows.extend(resp.get("Items", []))
        key = resp.get("LastEvaluatedKey")
        if not key:
            break

    print(f"Scanned {len(rows)} eightsleep DATE# rows in {TABLE_NAME}\n")

    # SCOPE — deliberately only the impossible ones, matching the ingestion guard.
    # 45 of these 991 rows have stage hours exceeding TST (mostly 105-124%, a systematic
    # vendor skew), and only ONE of the 45 ever published a percentage over 100. Widening
    # this to "everything that fails to reconcile" would strip 44 nights of plausible
    # figures from the archive to fix one live defect — a mass mutation nobody reviewed,
    # in the name of a bug fix. The skew is real and separately tracked; it is an accuracy
    # question about the vendor's stage accounting, not an impossible-number question.
    bad = []
    skewed_but_possible = 0
    for row in rows:
        stage_sum, tst = stage_ratio(row)
        stored = {k: _f(row.get(k)) for k in PCT_FIELDS if row.get(k) is not None}
        impossible = {k: v for k, v in stored.items() if v is not None and not (0 <= v <= 100)}
        if not impossible:
            if stage_sum and tst and stage_sum > tst * 1.02 + 0.05:
                skewed_but_possible += 1
            continue
        bad.append((row, stage_sum, tst, stored, impossible))

    if skewed_but_possible:
        print(
            f"ℹ️  {skewed_but_possible} further row(s) have stage hours exceeding TST but publish no "
            "impossible percentage — deliberately NOT touched here (systematic vendor skew, tracked separately).\n"
        )

    if not bad:
        print("✅ every row's stage percentages reconcile with TST — nothing to correct.")
        return 0

    print(f"{len(bad)} row(s) need correction:\n")
    for row, stage_sum, tst, stored, impossible in bad:
        date = row["sk"].replace("DATE#", "")
        ratio = f"{stage_sum / tst * 100:.0f}%" if stage_sum and tst else "n/a"
        print(f"  {date}  stages {stage_sum}h vs TST {tst}h ({ratio})")
        print(f"     stored: {stored}")
        if impossible:
            print(f"     IMPOSSIBLE: {impossible}")
        print(f"     -> remove {', '.join(k for k in PCT_FIELDS if k in stored)}; set stage_pct_omitted_reason")

    if not args.apply:
        print("\nDry run — nothing written. Re-run with --apply to correct.")
        return 0

    for row, stage_sum, tst, stored, _ in bad:
        present = [k for k in PCT_FIELDS if k in stored]
        reason = (
            f"stage hours sum to {round(stage_sum, 2)}h against TST {round(tst, 2)}h "
            f"({round(stage_sum / tst * 100)}% — stages appear to include awake time); "
            "percent-of-TST is undefined, so rem/deep/light_pct are omitted rather than published wrong"
        )
        # ONE atomic update. DynamoDB accepts `SET … REMOVE …` in a single expression,
        # each clause taking a comma-separated list — so the percentages disappear and
        # the reason appears together. Two sequential updates would leave a window where
        # a reader sees neither the value nor the explanation.
        expr = "SET stage_pct_omitted_reason = :r"
        if present:
            expr += " REMOVE " + ", ".join(present)
        table.update_item(
            Key={"pk": row["pk"], "sk": row["sk"]},
            UpdateExpression=expr,
            ExpressionAttributeValues={":r": reason},
        )
        print(f"  ✔ corrected {row['sk'].replace('DATE#', '')} ({expr})")

    print(f"\n✅ {len(bad)} row(s) corrected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
